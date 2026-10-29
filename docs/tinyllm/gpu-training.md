---
title: "可选路线：GPU 完整训练"
description: "学完第 12 章的完整模型后，用同一份代码放大配置，在 GPU 上训练一个更大的 TinyLLM：配置、参数量、显存与计算量估算，以及需要的语料规模。"
pageClass: tinyllm-course
---

# 可选路线：GPU 完整训练

[课程总览](./index.md) · [上一章](./tinyllm-model.md) · [下一章](./data-pipeline.md)

::: info 本页状态：规划中
这是一条**可选路线**，不影响主线：主线各章都只需要 CPU。等[第 12 章：完整 TinyLLM](./tinyllm-model.md) 写完，这里会补上可直接运行的训练脚本，以及在真实 GPU 上测得的训练时间和显存。唐宋诗大语料已经可以生成（见下文）。下面的参数量是把模型真正构建出来数的；显存和计算量是公式估算，用来在动手之前判断“我的显卡够不够”。
:::

## 这条路线做什么

主线的完整模型（第 12 章）要在 CPU 上几分钟训完，只能做得很小。这条路线用**同一份代码**，只改配置：把宽度、层数、上下文长度放大，换到 GPU 上，在更多的语料上训练更久。目的不是追求效果，而是亲眼看到三件事：

1. 同一份代码，放大以后哪些地方会先撑不住（显存、速度、数值稳定）；
2. 第 18 章的混合精度、第 19 章的梯度累积、第 20 章的检查点，在真实规模下为什么必要；
3. 模型、数据、算力一起放大时，验证损失怎样变化（第 1 章说的“规模”）。

## 三档配置

结构和 TinyLLM 主线完全一样：Pre-Norm RMSNorm、带 RoPE 的因果注意力、SwiGLU（中间宽度 8d/3）、输入嵌入和输出层共享权重。词表暂按字符级计算：统一唐诗语料 5,703 个字，唐宋诗大语料 10,320 个字（都含换行符）；第 12 章换成 BPE 后会重新计算。

| 配置 | 语料 | 宽度 d | 层数 | 头数 | 上下文 | 每步序列数 | 参数量 | 训练状态 | 激活 | 显存合计（估算） |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| CPU 基线（第 12 章） | 统一唐诗语料 | 256 | 6 | 8 | 128 | 32 | 6.2M | 0.10 GB | 0.40 GB | 约 0.5 GB |
| GPU 小 | 统一唐诗语料 | 512 | 8 | 8 | 512 | 32 | 28.1M | 0.45 GB | 3.03 GB | 约 3.5 GB |
| GPU 小 | 唐宋诗大语料 | 512 | 8 | 8 | 512 | 32 | 30.5M | 0.49 GB | 3.63 GB | 约 4.1 GB |
| GPU 中（约 GPT-2 small 大小） | 统一唐诗语料 | 768 | 12 | 12 | 1024 | 16 | 89.3M | 1.43 GB | 5.88 GB | 约 7.3 GB |
| GPU 中（约 GPT-2 small 大小） | 唐宋诗大语料 | 768 | 12 | 12 | 1024 | 16 | 92.9M | 1.49 GB | 6.49 GB | 约 8.0 GB |

几列数字的来历：

- **参数量**：把模型在 PyTorch 的 `meta` 设备上真正构建一遍再数，不占内存。大语料的词表更大，嵌入表多出约 240 万到 350 万个参数。
- **训练状态**：每个参数 16 字节，即 FP32 主权重、FP32 梯度、AdamW 的两个状态各 4 字节（[第 15 章](./optimizers.md)、[第 18 章](./precision.md)）。
- **激活**：按 BF16 混合精度、注意力用 SDPA/FlashAttention（不存整张 T×T 分数表）估算，每层每条序列约 34·T·d 字节（[Korthikanti 等，2022](https://arxiv.org/abs/2205.05198)），再加上输出层 logits 及其梯度。
- **没算进去的**：CUDA 上下文、内存碎片、框架缓存，通常还要再加 1～2 GB。

按这个估算，“GPU 小”在 8 GB 显存的消费级显卡上就能跑；“GPU 中”要 10 GB 左右，显存不够时减小每步序列数，用梯度累积补回同样的有效批量（[第 19 章](./gradient-stability.md)）。

## 语料：统一唐诗语料和唐宋诗大语料 {#corpora}

统一唐诗语料只有约 77 万字。常用的经验是每个参数配大约 20 个训练 token（[Hoffmann 等，2022](https://arxiv.org/abs/2203.15556)），2,810 万参数的“GPU 小”就需要约 5.6 亿个 token；只用唐诗训练，模型几乎一定会把这 1.7 万首诗背下来。所以这条路线另备了一份**唐宋诗大语料**：

| 项目 | 统一唐诗语料 | 唐宋诗大语料 |
| --- | --- | --- |
| 内容 | 五言绝句、五言律诗 | 《全唐诗》《全宋诗》的全部诗作，不限体裁 |
| 规模 | 17,439 首，约 77 万字 | 296,659 首（唐 50,286、宋 246,373），约 1,726 万字 |
| 不同的字 | 5,702 | 10,319 |
| 划分 | 训练 / 验证 / 测试 ≈ 90% / 5% / 5% | 同样的规则：训练 266,957、验证 14,768、测试 14,934 首 |
| 文件 | 4.2 MB，放在网站和整包下载里 | 约 90 MB，**在本机生成**，不放进仓库 |
| 每轮的计算量（GPU 小 / GPU 中） | 0.13 / 0.41 PFLOP | 3.21 / 9.78 PFLOP |
| 每个参数分到的 token（GPU 小 / GPU 中，训练一轮） | 0.03 / 0.01 | 0.58 / 0.19 |

大语料来自同一个开源数据集（chinese-poetry，MIT 许可证）的同一个固定版本。只保留由汉字和常用中文标点组成、长度 10～400 字的诗作（带注释或缺字的整首丢弃），繁体转简体、去重、打乱，再按正文哈希划分。生成方法：

```sh
python -m pip install opencc-python-reimplemented==0.1.7
python scripts/prepare-tinyllm-large-corpus.py
```

脚本会下载约 130 MB 的源数据（缓存在 `.cache/`，中断后可以接着下），在仓库根目录生成 `data/tang-song-poems.jsonl`，最后和 [`manifest-large.json`](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/tinyllm/data/manifest-large.json) 里的校验值（SHA-256 `23ce7f9b…`）核对。繁简转换的结果依赖 OpenCC 词典，请用上面指定的版本，否则校验值可能不同。

即使换成大语料，每个参数分到的 token 也还不到 1 个，离“20 个”很远。这条路线的打算是：“GPU 小”在大语料上多训练几轮，观察验证损失什么时候开始回升；“GPU 中”主要用来体会显存和速度的变化，不追求训练到最优。

## 待补的实测

第 12 章完成后，这里会按同样的口径补上：

- 每种配置在常见显卡（例如 RTX 3090/4090、Colab 的 T4）上每秒处理多少 token、训练一轮要多久；
- `torch.cuda.max_memory_allocated()` 实测的显存峰值，和上表的估算对照；
- 训练损失与验证损失曲线，以及生成样例。

估算由 `scripts/tinyllm-gpu-estimates.py` 生成，结果在 `scripts/data/tinyllm-gpu-estimates.json`。

## 参考资料

- [Reducing Activation Recomputation in Large Transformer Models，Korthikanti 等，2022](https://arxiv.org/abs/2205.05198)（激活显存估算）
- [Training Compute-Optimal Large Language Models，Hoffmann 等，2022](https://arxiv.org/abs/2203.15556)（参数与数据的比例）
- [PyTorch CUDA 内存管理](https://docs.pytorch.org/docs/stable/notes/cuda.html#memory-management)

回到主线：[第 13 章：语料与数据管线](./data-pipeline.md)。
