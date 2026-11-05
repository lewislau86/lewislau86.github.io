---
title: "第 13 章：TinyLLM 在 GPU 上完整实现"
description: "第 12 章的模型代码一行不改，只换配置和训练循环，在 GPU 上用 BF16、梯度累积、学习率调度和检查点完整训练一个更大的 TinyLLM；并点出 GPU 上还能优化的地方，留给后面各章。"
pageClass: tinyllm-course
---

# 第 13 章：TinyLLM 在 GPU 上完整实现

[课程总览](./index.md) · [上一章](./tinyllm-model.md) · [下一章](./data-pipeline.md)

::: tip 本章学习目标
能把第 12 章的模型原样搬上 GPU：说清哪几行代码因为换设备而改变、哪些完全不变；能在动手前估出一档配置要多少参数和显存，并在显存不够时用梯度累积换出同样的有效批量；能读懂一个完整的 GPU 训练循环（BF16 autocast、学习率调度、梯度裁剪、计时、显存峰值、检查点）；能说出 GPU 训练里还有哪些地方可以优化，以及它们分别在后面哪一章展开。

**前置：** [第 12 章：完整 TinyLLM](./tinyllm-model.md)。用到的混合精度、梯度累积、学习率调度在[第 19 章](./precision.md)、[第 20 章](./gradient-stability.md)、[第 17 章](./learning-rate.md)细讲，本章先给一句话的直觉。

**实践方式：** <a href="/tinyllm/code/gpu-training.py" download>gpu-training.py</a>。有 NVIDIA 显卡时默认按“GPU 小”配置完整训练；没有显卡时自动改用“CPU 冒烟”配置，几十步跑通整条流程，约半分钟。[gpu-training.ipynb](/tinyllm/notebooks/gpu-training) 是在 CPU 上生成的，也可以[在 Colab 中运行](https://colab.research.google.com/github/lewislau86/lewislau86.github.io/blob/master/docs/public/tinyllm/notebooks/gpu-training.ipynb)（运行时选 GPU）。
:::

<TinyLLMMap active="tinyllm-model" />

## 问题：基线还在下降，CPU 却跑不动了

第 12 章的基线训练到第 300 步，验证损失还在往下走。想让它继续学，要么训练更久，要么把模型和数据一起放大，可 CPU 上 131 万参数的模型每秒只能处理几千个 token。

GPU 擅长的正是这种计算：大块的矩阵乘法可以同时铺到几千个核上。本章用**同一份模型代码**，只改配置和训练循环，在 GPU 上把 TinyLLM 放大二十多倍完整训练一遍。读完你会看到，搬上 GPU 本身只改了几行；真正值得花功夫的，是让这几千个核一直有活干，那是后面几章的事。本章把这些地方先一一点出来。

::: info 本章代码从哪里来
本章所有代码都在一个文件里：<a href="/tinyllm/code/gpu-training.py" download>gpu-training.py</a>（[在 GitHub 上查看](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/tinyllm/code/gpu-training.py)）。下面的代码块都是从这个文件里直接截取的片段。正文里的输出来自本站在 CPU 上生成 notebook 时的“冒烟”运行（torch 2.14.1+cpu）；在 GPU 上运行的实测数字留在第 7 节，等补上真实显卡的结果。
:::

## 1. 设备与精度：三行决定一切

<<< @/public/tinyllm/code/gpu-training.py#device

```text
设备： CPU
混合精度： 关闭（FP32）
```

有 GPU 时，后面所有张量都放到 `cuda` 上；显卡支持 BF16 就打开 BF16 混合精度：前向在 BF16 里算，权重和优化器状态仍然是 FP32，所以既快又不怎么损失精度（[第 19 章](./precision.md)）。TF32 那两行让剩下的 FP32 矩阵乘也走张量核，这是第一个“免费”的优化。

模型代码（`TinyConfig`、RoPE、注意力、SwiGLU、Block、`TinyLLM`）和[第 12 章](./tinyllm-model.md)逐字相同，本章不再重复贴出。放大模型只改配置。

## 2. 三档配置：动手之前先估显存

<<< @/public/tinyllm/code/gpu-training.py#presets

“CPU 冒烟”就是第 12 章的基线尺寸，只为在没有显卡的机器上检查流程；两档 GPU 配置把宽度、层数、上下文一起放大，词表也从 4096 加到 8192。

`micro_batch × accum` 是每一步真正用到的序列数。**梯度累积**的直觉是：显存一次放不下 32 条长序列，就分 4 次各放 8 条，前向、反向各做 4 次，把梯度加起来再更新一次。这和一次放 32 条算出的梯度相同（每次的损失先除以 4），只是慢一些（[第 20 章](./gradient-stability.md)）。“GPU 中”就是这样配的。

显卡够不够，动手之前就能估：

<<< @/public/tinyllm/code/gpu-training.py#estimate

```text
配置                  参数量   每步 token     训练状态      激活      合计
cpu-smoke     1,311,360      2,048    0.02G   0.05G   0.07G
gpu-small    29,364,736     16,384    0.47G   3.36G   3.83G
gpu-medium   91,245,312     32,768    1.46G   3.10G   4.56G
```

几列数字的来历：

- **参数量**：把模型在 PyTorch 的 `meta` 设备上真正构建一遍再数，不占内存。“GPU 中”约 9,100 万参数，和 GPT-2 small 差不多大。
- **训练状态**：每个参数 16 字节，即 FP32 权重、FP32 梯度、AdamW 的两个状态各 4 字节（[第 16 章](./optimizers.md)、[第 19 章](./precision.md)）。
- **激活**：反向传播要用到前向的中间结果，按 BF16、注意力用 SDPA（不存整张 T×T 分数表）估，每层每条序列约 34·T·d 字节（[Korthikanti 等，2022](https://arxiv.org/abs/2205.05198)），再加输出层 logits 和它的梯度。激活只和 `micro_batch` 有关，和 `accum` 无关：这正是梯度累积能省显存的原因。
- **没算进去的**：CUDA 上下文、显存碎片、框架缓存，通常还要再加 1～2 GB。

按这个估算，两档 GPU 配置在 8 GB 显存的消费级显卡上都能跑。显存不够就把 `micro_batch` 减半、`accum` 加倍，有效批量不变。

## 3. 语料：统一唐诗语料和唐宋诗大语料 {#corpora}

放大的模型需要更多数据。常用的经验是每个参数配大约 20 个训练 token（[Hoffmann 等，2022](https://arxiv.org/abs/2203.15556)），2,936 万参数的“GPU 小”就需要约 6 亿个 token；统一唐诗语料只有约 77 万字，只用它训练，模型几乎一定会把这 1.7 万首诗背下来。所以 GPU 配置优先用一份**唐宋诗大语料**，找不到时退回统一唐诗语料的全部 17,439 首：

| 项目 | 统一唐诗语料 | 唐宋诗大语料 |
| --- | --- | --- |
| 内容 | 五言绝句、五言律诗 | 《全唐诗》《全宋诗》的全部诗作，不限体裁 |
| 规模 | 17,439 首，约 77 万字 | 296,659 首（唐 50,286、宋 246,373），约 1,726 万字 |
| 不同的字 | 5,702 | 10,319 |
| 划分 | 训练 / 验证 / 测试 ≈ 90% / 5% / 5% | 同样的规则：训练 266,957、验证 14,768、测试 14,934 首 |
| 文件 | 4.2 MB，放在网站和整包下载里 | 约 90 MB，**在本机生成**，不放进仓库 |

大语料来自同一个开源数据集（chinese-poetry，MIT 许可证）的同一个固定版本。只保留由汉字和常用中文标点组成、长度 10～400 字的诗作（带注释或缺字的整首丢弃），繁体转简体、去重、打乱，再按正文哈希划分。生成方法：

```sh
python -m pip install opencc-python-reimplemented==0.1.7
python scripts/prepare-tinyllm-large-corpus.py
```

脚本会下载约 130 MB 的源数据（缓存在 `.cache/`，中断后可以接着下），在仓库根目录生成 `data/tang-song-poems.jsonl`，最后和 [`manifest-large.json`](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/tinyllm/data/manifest-large.json) 里的校验值（SHA-256 `23ce7f9b…`）核对。繁简转换的结果依赖 OpenCC 词典，请用上面指定的版本，否则校验值可能不同。`gpu-training.py` 会在环境变量 `TINYLLM_LARGE_DATA`、当前目录、`../data/` 和仓库根目录的 `data/` 里找这个文件。

<<< @/public/tinyllm/code/gpu-training.py#data

即使换成大语料，“GPU 小”训练 6000 步共处理约 9,800 万个 token，按每字约 1 个 token 粗算，相当于把训练集过五六遍，离“每参数 20 个 token”仍然很远。所以这一档要盯着验证损失：它什么时候开始回升，就说明模型开始背了。分词器在 CPU 上训练，大语料要几分钟。

## 4. 搬上设备

和第 12 章相比，只多了三处：模型 `.to(device)`；GPU 上用 `fused=True` 的 AdamW，把每个参数上的一串小运算合成少数几个内核；可选的 `torch.compile`。学习率不再固定，先用几百步从 0 线性升到峰值，再按余弦曲线降到峰值的十分之一：刚开始参数还很乱，先走小步更稳，最后走小步收尾（[第 17 章](./learning-rate.md)）。

<<< @/public/tinyllm/code/gpu-training.py#setup

## 5. 训练循环

评估沿用第 12 章的口径，只多了把数据搬到设备上、在 autocast 里算前向：

<<< @/public/tinyllm/code/gpu-training.py#evaluate

训练循环本身也和第 12 章是同一个骨架：按 batch 计划取数据，前向、反向、裁剪、更新。多出来的是 `accum` 那一层内循环、每步设置学习率，以及计时：

<<< @/public/tinyllm/code/gpu-training.py#train

计时前后都调用了 `synchronize()`，因为 GPU 是**异步**执行的：Python 把运算交给 GPU 之后马上返回，不等它算完。不同步就读时间，量到的只是“发命令”的时间。

在 CPU 上冒烟运行的输出（60 步）：

```text
step     0  验证损失 8.750  (12.05 比特/字)
step    30  验证损失 6.474  (8.91 比特/字)
step    60  验证损失 6.293  (8.66 比特/字)
```

第 0 步的 8.750 和第 12 章完全一样：同样的数据、同样的初始化种子、同样的评估口径。流程通了，数字也接得上。

## 6. 显存、检查点与生成

在 GPU 上，脚本会打印 `torch.cuda.max_memory_allocated()` 测得的显存峰值，和第 2 节的估算对照：

<<< @/public/tinyllm/code/gpu-training.py#memory

大模型一训就是几小时，中途断了要能接着训。检查点至少存模型、优化器、配置和步数；存完立刻读进一个新模型，验证损失应该一模一样（[第 21 章](./training-loop.md)会补上调度器和随机数状态）：

<<< @/public/tinyllm/code/gpu-training.py#checkpoint

```text
存之前 6.2932，读回来 6.2932
```

最后用和第 12 章相同的采样函数写几首。CPU 冒烟只训练了 60 步，输出还不成句，个别位置的“�”是字节级 BPE 只生成了半个汉字的字节：

```text
晓如恻，何下花成。惬阳台苏回，病载归足，秋金天�风。营集时前，�定路春城。叶安篇��得，悬不同空。
期晚，长月住孤方。高影轻群，独有，禅退吟游。贵带隔，萤，一意怜。，犹得相访乐�，簟。已无支。
未月天圃，似老女尽。关河贪照远，穿麟疎难君语。
```

## 7. 在你的 GPU 上跑

```sh
cd tinyllm-code/code
python gpu-training.py                               # 有显卡时默认 gpu-small
TINYLLM_PRESET=gpu-medium python gpu-training.py     # 约 GPT-2 small 大小
TINYLLM_COMPILE=1 python gpu-training.py             # 打开 torch.compile 对照
```

Windows PowerShell 里先执行 `$env:TINYLLM_PRESET="gpu-medium"` 再运行。脚本运行结束会在当前目录写出 `gpu_training_log.json`（逐步损失、验证损失和吞吐）。

::: info 待补的实测
下表等在真实显卡上运行后补上，口径与上面相同：吞吐只算训练步、不算评估；显存是 `max_memory_allocated` 的峰值；验证损失是第 6000 步、单个种子。

| 显卡 | 配置 | 吞吐（token/s） | 6000 步用时 | 显存峰值 / 估算 | 最终验证损失 |
| --- | --- | --- | --- | --- | --- |
| 待实测（如 RTX 4090） | gpu-small | — | — | — / 3.83 GB | — |
| 待实测（如 RTX 4090） | gpu-medium | — | — | — / 4.56 GB | — |
| 待实测（如 Colab T4） | gpu-small | — | — | — / 3.83 GB | — |
:::

T4 不支持 BF16，脚本会自动关闭混合精度、用 FP32 训练，吞吐和显存都会和支持 BF16 的显卡差很多；想在 T4 上用 FP16，需要配合 GradScaler（第 19 章）。

## 8. GPU 上还能怎么优化 {#gpu-optimizations}

本章的训练循环是“能跑通、口径对”的写法，不是最快的写法。下图把一个训练步拆开，红圈标出后面可以优化的地方：

![GPU 上一个训练步的流程：CPU 按计划切出 batch 拷到显存，GPU 上依次做 BF16 前向、交叉熵、反向求梯度，重复 accum 次后裁剪并用 AdamW 更新；七个红圈标出数据预取、减少拷贝、FlashAttention、torch.compile、激活重计算、融合优化器、减少同步七个优化点](/tinyllm/figures/gpu-step-anatomy.svg)

| | 优化点 | 现在的写法 | 改进方向 | 在哪里展开 |
| --- | --- | --- | --- | --- |
| ① | 数据准备 | 每步在 CPU 上切片，GPU 等着 | `DataLoader` 多进程预取、锁页内存、`non_blocking` 异步拷贝 | [第 14 章](./data-pipeline.md) |
| ② | 主机到显存的拷贝 | 每步拷一次 batch | 整条 token 流一次性放进显存，直接在 GPU 上切片 | [第 14 章](./data-pipeline.md) |
| ③ | 注意力内核 | `scaled_dot_product_attention`，由 PyTorch 自动选后端 | 确认走的是 FlashAttention 内核；长上下文时它决定显存和速度 | [第 27 章](./attention-kernels.md) |
| ④ | 逐元素小算子 | RMSNorm、RoPE、SiLU×乘各自一个内核，反复读写显存 | `torch.compile` 把它们融合成少数几个内核（`TINYLLM_COMPILE=1` 可以先试） | [第 27 章](./attention-kernels.md) |
| ⑤ | 激活显存 | 前向的中间结果全部保留到反向 | 激活重计算：反向时重算一部分，省下显存换更大的 `micro_batch` | [第 23 章](./large-model-stability.md) |
| ⑥ | 优化器 | 已用 `fused=True` 的 AdamW | 显存紧张时换状态更小的优化器 | [第 16 章](./optimizers.md) |
| ⑦ | CPU 与 GPU 的同步 | 每步 `loss.item()` 让 CPU 等 GPU 算完 | 日志每 N 步取一次，让 CPU 提前把下一步的命令发出去 | [第 21 章](./training-loop.md) |

还有两类优化不在这张图里：一张卡放不下时的**多卡训练**（数据并行、FSDP，见[第 23 章](./large-model-stability.md)）；模型训好之后的**推理优化**（KV cache 见[第 26 章](./inference-efficiency.md)，注意力内核见[第 27 章](./attention-kernels.md)，连续批处理见[第 30 章](./batching.md)，投机解码见[第 29 章](./speculative-decoding.md)，逐项对照见[第 32 章](./inference-optimization.md)）。尺寸上也有一个小讲究：宽度和词表取 64 的倍数（本章的 512、768、8192 都是），矩阵乘才能整齐地铺满张量核。

这些优化各有一章，是因为它们都要回答同一个问题：**改了以后，结果还和原来一样吗、快了多少？** 所以本章刻意不叠加任何一项，先留下一条口径清楚的 GPU 基线。

<!-- real-model:start -->

## 在真实模型里

用 transformers 的 Trainer 在 GPU 上训练时，本章训练循环里的几件事分别在这些地方。下表的链接都指向 Hugging Face transformers 的固定版本 `v5.21`，精确到行。读代码时可以先跳过缓存、掩码、并行这些工程细节，只看和本章对应的那几行。

| 本章的零件 | 真实代码 | 对照要点 |
| --- | --- | --- |
| 梯度累积：什么时候才更新 | [`trainer.py 第 1872 行`](https://github.com/huggingface/transformers/blob/v5.21/src/transformers/trainer.py#L1872) | 每累积 `gradient_accumulation_steps` 个 micro-batch 才裁剪、更新一次，和本章的 `accum` 循环一样 |
| 一个 micro-batch 的前向与反向 | [`Trainer.training_step`](https://github.com/huggingface/transformers/blob/v5.21/src/transformers/trainer.py#L2023-L2100) | 在 autocast 里算损失、按累积步数缩放后 backward |
| 混合精度的上下文 | [`Trainer.compute_loss_context_manager`](https://github.com/huggingface/transformers/blob/v5.21/src/transformers/trainer.py#L2191-L2201) | 把 autocast 套在前向外面，对应本章的 `autocast()` |
| 梯度裁剪 | [`Trainer._clip_grad_norm`](https://github.com/huggingface/transformers/blob/v5.21/src/transformers/trainer.py#L2738-L2744) | 按全局范数裁剪，和本章 `clip_grad_norm_(…, 1.0)` 相同 |
| 保存检查点 | [`Trainer._save_checkpoint`](https://github.com/huggingface/transformers/blob/v5.21/src/transformers/trainer.py#L3318-L3385) | 模型、优化器、调度器、随机数状态和步数一起存，比本章多存了调度器和随机数状态（第 21 章） |

想在本机看源码，可以先 `pip install transformers`，再用 `python -m inspect transformers.models.llama.modeling_llama:LlamaMLP` 这样的命令打印出任意一个类。

<!-- real-model:end -->

## 本章结论：TinyLLM 的选择 {#tinyllm-choice}

TinyLLM 在 GPU 上的完整实现保持第 12 章的模型代码不变，只改两样东西：**配置**（“GPU 小”：d=512、8 层、上下文 512、词表 8192，约 2,940 万参数；“GPU 中”：d=768、12 层、上下文 1024，约 9,120 万参数）和**训练循环**（BF16 autocast、TF32、fused AdamW、warmup 加余弦学习率、梯度累积、梯度裁剪、计时、显存峰值、检查点）。数据划分、batch 计划和验证口径沿用第 12 章，所以 CPU 冒烟运行的第 0 步验证损失和第 12 章逐位相同。

优化点只点名、不叠加：先有一条口径清楚的 GPU 基线，后面各章每打开一项优化，都单独测吞吐、显存，并核对结果没有变差。

::: warning 常见误区
- **搬上 GPU 不需要改模型。** 只要模型里的张量都通过 `register_buffer` 或参数注册，`.to(device)` 就会一起搬过去；本章的 RoPE 表就是这样处理的。手写在 `forward` 里的 `torch.arange` 之类，要记得指定 `device`。
- **不同步就计时，量到的是假的。** GPU 异步执行，读时间之前要 `torch.cuda.synchronize()`。
- **梯度累积省的是激活显存，不是训练状态。** 权重、梯度、优化器状态的 16 字节 / 参数一分不少；累积只是让每次前向放进显存的序列变少。
- **估算只是下限。** `nvidia-smi` 看到的占用还包括 CUDA 上下文和缓存，通常比 `max_memory_allocated` 大 1～2 GB。
- **吞吐提高不等于训练更好。** 换了精度、换了内核以后，要在同一验证集上确认损失没有变差，才算优化。
:::

## 检查理解

1. “GPU 中”的 `micro_batch=8, accum=4` 改成 `micro_batch=32, accum=1`，每步处理的 token 数、训练状态显存、激活显存分别怎么变？

   <details><summary>参考答案</summary>

   每步 token 数不变（都是 32 × 1024 = 32,768）。训练状态不变（只和参数量有关，约 1.46 GB）。激活变成原来的 4 倍：按第 2 节的公式约 3.10 × 4 ≈ 12.4 GB，合计约 13.9 GB，8 GB 的卡就放不下了。

   </details>

2. 为什么 CPU 冒烟运行第 0 步的验证损失（8.750）和第 12 章完全相同？哪一处改动会让它不同？

   <details><summary>参考答案</summary>

   两边用同一份前 6000 首诗、同样训练出来的 4096 词表、同一个模型初始化种子（`torch.manual_seed(0)`）和同一个验证口径，第 0 步还没有任何更新，所以是同一个模型在同一份数据上的损失。改词表大小、改初始化种子、改验证窗口长度，或者在 GPU 上用 BF16 计算，都会让这个数变（BF16 只会让末几位不同）。

   </details>

3. 在 GPU 上打开 `TINYLLM_COMPILE=1` 后，第一步明显变慢，之后变快。为什么？比较吞吐时应该怎么处理第一步？

   <details><summary>参考答案</summary>

   `torch.compile` 在第一次调用时分析模型、生成并编译融合后的内核，这一步要花几秒到几十秒；之后每步直接用编译好的内核。比较吞吐时应该先跑若干步预热，或者把前几步排除在计时之外，否则编译时间会被摊进平均吞吐里。

   </details>

## 参考资料

- [PyTorch：自动混合精度](https://docs.pytorch.org/docs/stable/amp.html) · [CUDA 语义与 TF32](https://docs.pytorch.org/docs/stable/notes/cuda.html#tensorfloat-32-tf32-on-ampere-and-later-devices) · [CUDA 内存管理](https://docs.pytorch.org/docs/stable/notes/cuda.html#memory-management)
- [PyTorch：`torch.compile` 教程](https://docs.pytorch.org/tutorials/intermediate/torch_compile_tutorial.html) · [性能调优指南](https://docs.pytorch.org/tutorials/recipes/recipes/tuning_guide.html)
- [FlashAttention，Dao 等，2022](https://arxiv.org/abs/2205.14135)
- [Reducing Activation Recomputation in Large Transformer Models，Korthikanti 等，2022](https://arxiv.org/abs/2205.05198)（激活显存估算）
- [Training Compute-Optimal Large Language Models，Hoffmann 等，2022](https://arxiv.org/abs/2203.15556)（参数与数据的比例）

模型能在 GPU 上放大了，下一个瓶颈是数据：[第 14 章：语料与数据管线](./data-pipeline.md)。
