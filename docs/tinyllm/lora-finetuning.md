---
title: "第 39 章：参数高效微调（LoRA）"
description: "冻住原模型，只训练低秩增量：LoRA 的结构与初始化，省下了梯度和优化器状态、没省下什么；和全参数微调在同一份 SFT 数据上比效果和遗忘；新加的特殊 token 为什么要单独放开；以及把增量合并回原权重后推理和原模型一样。"
pageClass: tinyllm-course
---

# 第 39 章：参数高效微调（LoRA）

[课程总览](./index.md) · [上一章](./instruction-finetuning.md) · [下一章](./distillation.md)

::: tip 本章学习目标
能写出一个 LoRA 线性层：原权重冻住，旁边加一条 $B A$ 的低秩支路，并说清 A、B 为什么这样初始化、α/r 起什么作用；能算出 LoRA 省下的是哪几块显存，没省下的是哪几块；能在同一份 SFT 数据上比较全参数微调和不同秩的 LoRA，同时看学会了多少和忘了多少；知道新加的特殊 token 在 LoRA 下为什么学不好、怎样单独放开；能把 LoRA 合并回原权重，并验证合并前后输出一致。

**前置：** [第 38 章](./instruction-finetuning.md)的基座、对话模板与 SFT，[第 16 章](./optimizers.md)的 AdamW 状态，[第 13 章](./gpu-training.md)的显存估算。

**实践方式：** [lora-finetuning.ipynb](/tinyllm/notebooks/lora-finetuning)（也可以直接运行 <a href="/tinyllm/code/lora-finetuning.py" download>lora-finetuning.py</a>），CPU 约两分钟，需要 PyTorch 和 `tokenizers`。
:::

<TinyLLMMap active="lora-finetuning" />

## 问题：全参数微调要多少显存

第 38 章的 SFT 是**全参数微调**：模型的每个参数都在动。训练时显存里除了权重本身，还要放每个参数的梯度，以及 AdamW 为每个参数存的两份动量（第 16 章）。混合精度下，一个参数要占约 16 字节：BF16 的权重和梯度各 2 字节，FP32 的主权重 4 字节，两份 FP32 动量 8 字节。一个 7B 的模型，光这些就要 100 GiB 左右，一张 80 GB 的卡放不下。

[LoRA](https://arxiv.org/abs/2106.09685)（low-rank adaptation）的想法是：微调时权重的**变化量**大概不需要满秩。原来的权重 W 冻住不动，只训练一个低秩的增量 $\Delta W = BA$，其中 A 是 r×in、B 是 out×r，r 远小于 in 和 out。要训练的参数从 in·out 个变成 r·(in+out) 个，梯度和优化器状态也跟着缩小。论文报告在 GPT-3 175B 上，可训练参数减少到万分之一，显存减少到三分之一；[QLoRA](https://arxiv.org/abs/2305.14314)再把冻住的权重量化成 4 比特（第 30 章），在一张 48GB 的卡上微调 65B 的模型。

这一章在第 38 章的设定上，比较全参数微调和 LoRA：显存账、照指令做的效果、原来的能力掉了多少。

::: info 本章代码从哪里来
本章所有代码都在一个文件里：<a href="/tinyllm/code/lora-finetuning.py" download>lora-finetuning.py</a>（[在 GitHub 上查看](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/tinyllm/code/lora-finetuning.py)）。下面的代码块都是从这个文件里直接截取的片段，所以单独复制一段可能缺少 `import` 或前面定义的变量；想自己运行，请下载完整文件，`python lora-finetuning.py` 从头跑到尾即可。notebook 版本也由同一个文件生成，可以[在线查看](/tinyllm/notebooks/lora-finetuning)，或[在 Colab 中直接运行](https://colab.research.google.com/github/lewislau86/lewislau86.github.io/blob/master/docs/public/tinyllm/notebooks/lora-finetuning.ipynb)。正文引用的输出来自 torch 2.14.1+cpu、tokenizers 0.23.3；以“[计时，本机]”开头的输出和机器有关，正文只引用它们的大致数值。
:::

## 1. 基座与 SFT 数据

模型、分词器、数据、指令、判分、预训练和 SFT 的代码都和[第 38 章](./instruction-finetuning.md)完全相同，这里不再列出，只重新训练一遍基座：

```text
[计时，本机] 预训练 2000 步 21.2 秒；预训练验证损失 4.305
```

## 2. LoRA 线性层

![LoRA 的结构：输入同时经过冻住的 W 和一条低秩支路 A、B，支路输出乘 α/r 后相加；训练完把增量合并回 W](/tinyllm/figures/lora-structure.svg)

怎么读这张图：灰色是原来的线性层，冻住；橙色是新加的支路，只有它在训练。下方是合并：把支路的乘积加回 W 以后，支路就不存在了。

<<< @/public/tinyllm/code/lora-finetuning.py#lora

几个细节：

- **B 初始化为 0。** 刚加上 LoRA 时 $BA = 0$，模型的输出和原来完全一样，训练从基座的状态平稳开始。A 不能也是 0，否则两个矩阵的梯度都是 0，永远学不动。
- **输出乘 α/r。** LoRA 论文的做法是固定 α、只改 r：r 变大，支路的输出会变大，除以 r 把它拉回来，换秩时就不用重调学习率。很多实践（包括本章）改用 α = 2r，相当于不管 r 多大都固定乘 2；这样 r 越大，支路一开始的更新也越大，所以本章 r=4 和 r=32 的对比里，除了“秩”还混着“更新幅度”这个因素。
- **加在哪些层。** 每个 Block 的 5 个线性层（注意力的 qkv、输出投影，前馈层的 gate、up、down）都加。嵌入表（也是输出层，第 5 章）冻住。
- **新加的特殊 token。** `<user>`、`<assistant>` 是第 38 章为对话模板新加的，基座在预训练时一次也没见过它们，嵌入表里这两行没学过“这是什么”。嵌入表冻住以后，它们也就永远学不了了。`NewTokenRows` 只放开这两行：嵌入表本身仍冻住，只给这两行加一个可训练的增量，一共 2×64 = 128 个参数。

## 3. 全参数微调与几种 LoRA

全参数微调和第 38 章种子 0 完全相同，学习率峰值 3e-3。LoRA 用 1e-2：LoRA 的参数少、初始的 B 为 0，通常要比全参数微调大一些的学习率。比较秩 r=4 和 r=32，再试一组 r=32 同时放开两个新 token。其余设置都和第 38 章相同，1500 步，一个种子。

<<< @/public/tinyllm/code/lora-finetuning.py#runs

```text
[计时，本机] 4 组各 SFT 1500 步，共 103.2 秒
模型共 163,904 个参数
全参数微调                可训练 163,904（100.0%）
LoRA r=4             可训练   8,688（  5.3%）
LoRA r=32            可训练  69,504（ 42.4%）
LoRA r=32 + 新 token  可训练  69,632（ 42.5%）
全参数微调                每句五字 0.92  句数对 0.91  首字对 0.39  全部照做 0.58  │ 预训练验证损失 4.640
LoRA r=4             每句五字 0.91  句数对 0.89  首字对 0.00  全部照做 0.34  │ 预训练验证损失 4.505
LoRA r=32            每句五字 0.89  句数对 0.88  首字对 0.05  全部照做 0.44  │ 预训练验证损失 4.580
LoRA r=32 + 新 token  每句五字 0.81  句数对 0.81  首字对 0.21  全部照做 0.45  │ 预训练验证损失 4.583
```

![全参数微调与 LoRA 的对比：左图是合格率，中图是预训练验证损失，右图是训练时的显存账](/tinyllm/figures/lora-results.svg)

怎么读这张图：左图每组四根柱子是四种做法；中图的虚线是基座的预训练验证损失，柱子越高忘得越多；右图把训练时的显存拆成权重、梯度、AdamW 状态三块。

先说参数量：TinyLLM 的宽度只有 64，r=32 已经是宽度的一半，LoRA 的参数占到 42%；在大模型上，宽度几千、r 取 8～64，LoRA 的参数通常不到 1%。所以本章的显存账只能说明“省在哪”，省多少要看真实模型的尺寸（第 4 节）。

再看效果：

- **格式和句数，LoRA 和全参数微调差不多。** 句数对 0.81～0.89 对 0.91。学会“律诗写八句”只需要很小的改动。
- **首字，LoRA 明显学不会。** r=4 是 0，r=32 是 0.05，全参数微调是 0.39。可能的原因有两个，本章没有把它们分开：一是首字要模型现学一种“抄字”的注意力模式，这个改动不是低秩的增量能轻易表达的；二是 LoRA 把嵌入表冻住了，而它同时也是输出层，全参数微调却可以改它。下一条的结果说明第二个原因至少占了一部分。
- **放开两个新 token 以后，首字对升到 0.21。** 只多了 128 个参数，效果比 r 从 4 加到 32（多了 6 万个参数）还大：模型得先知道 `<assistant>` 是什么，才能在它后面开始“抄”。代价是格式变差了一点（0.81），这一组只有一个种子，不能把这个下降看得太重。
- **LoRA 忘得少。** 预训练验证损失，基座 4.305，全参数微调升到 4.640，LoRA r=4 只升到 4.505，r=32 升到 4.580。秩越低，改动越受限，原来的能力保留得越多。

“学得少、忘得也少”正是 [Biderman 等（2024）](https://arxiv.org/abs/2405.09673)在代码和数学上的结论：标准设置下 LoRA 明显不如全参数微调，但更好地保住了基座在其他任务上的能力；他们还发现全参数微调学到的权重变化，秩比常用的 LoRA 设置高 10～100 倍。

## 4. 显存账：LoRA 省下的是什么

<<< @/public/tinyllm/code/lora-finetuning.py#memory

```text
全参数微调        权重  0.63 MiB  梯度  0.63 MiB  优化器状态  1.25 MiB  合计  2.50 MiB
LoRA r=4     权重  0.66 MiB  梯度  0.03 MiB  优化器状态  0.07 MiB  合计  0.76 MiB
LoRA r=32    权重  0.89 MiB  梯度  0.27 MiB  优化器状态  0.53 MiB  合计  1.69 MiB
7B 级模型 6.74B 个参数：全参数微调（混合精度）约 100 GiB；LoRA r=16 只训练 40M 个参数，冻住的 BF16 权重加上 LoRA 部分约 13.1 GiB
```

- **省的是梯度和优化器状态。** 它们只为可训练的参数存，LoRA 的可训练参数少，这两块就小。
- **权重一点没省，还多了一点。** 冻住的权重照样要整份放在显存里（前向要用），A、B 还是额外的。要省权重，得把冻住的部分量化（QLoRA）。
- **激活基本没省。** 反向传播要经过每一层才能算到 A、B 的梯度，每层的激活照样要存（这里没计入）。长序列、大 batch 时，激活常常是显存的大头（第 13 章的重计算）。
- **计算没省多少。** 前向一次不少，反向少了权重梯度那一半矩阵乘，但输入梯度那一半还在，还多了支路上的小矩阵乘。本章在 CPU 上没有单独给每组计时（四组约 100 秒里还包括评估），所以不比较速度；在这么小的模型上，支路的额外开销和省下的权重梯度差不多大，大模型上 LoRA 通常快一些。

## 5. 合并：推理时和原模型一样快

<<< @/public/tinyllm/code/lora-finetuning.py#merge

```text
合并前参数 233,408，合并后 163,904（和原模型 163,904 相同）
合并前后 logits 的最大差 7.63e-06
对照：全参数微调后第 1 层 qkv 权重的变化，前 32 个奇异值占全部能量的 92.4%，前 4 个占 47.1%
```

合并以后，模型的结构、参数量和原来一模一样，推理没有任何额外开销；输出只差浮点舍入的量级。这是 LoRA 和早期“插一个小网络”的 adapter 方法的主要区别。反过来，不合并也有用处：同一个基座可以挂很多套 LoRA，按请求切换，每套只占几 MB 到几十 MB（检查理解 4）。

最后一行是个侧面的参考：全参数微调学到的 qkv 权重变化（192×64，秩最多 64），前 4 个奇异值占能量的 47%，要到 32 个才占 92%。这不算很低秩，但也不是完全分散；而且这个变化里还混着 AdamW 权重衰减把整个矩阵缩小一点的成分，它本身就是满秩的。所以它只能说明“SFT 的改动不一定低秩”，不能单独解释 LoRA 在首字上学不好。

## 动手实验

1. **只加在注意力上。** 把 `LINEARS` 改成只有 `{"attn": ("qkv", "proj")}`，r=32。首字和格式各怎么变？LoRA 论文最初只加在注意力的 q、v 上，后来的经验多是全部线性层都加。
2. **学习率。** LoRA r=32 的峰值换成 3e-3（和全参数微调相同）和 3e-2。学习率小了会怎样？
3. **全参数微调加上同样的放开方式。** 全参数微调本来就训练整张嵌入表。如果反过来冻住嵌入表、只训练 Block，首字对会掉吗？这说明了什么？
4. **多套 LoRA。** 用同一个基座训两套 LoRA：一套只用绝句的数据，一套只用律诗的数据。推理时按指令切换，和一套混合训练的 LoRA 比怎样？

<!-- real-model:start -->

## 在真实模型里

LoRA 在 Hugging Face 生态里由 PEFT 库实现：`get_peft_model(model, LoraConfig(...))` 把指定的线性层换成带 LoRA 支路的层，模型代码不用改。下表的链接都指向 Hugging Face peft 的固定版本 `v0.22.0`，精确到行。读代码时可以先跳过缓存、掩码、并行这些工程细节，只看和本章对应的那几行。

| 本章的零件 | 真实代码 | 对照要点 |
| --- | --- | --- |
| 配置：秩、α、加在哪里 | [`LoraConfig`](https://github.com/huggingface/peft/blob/v0.22.0/src/peft/tuners/lora/config.py#L514-L1240) | `r` 默认 8、`lora_alpha` 默认 8，支路输出乘 α/r（`use_rslora=True` 时是 α/√r）；`target_modules` 选加在哪些层；`trainable_token_indices` 只训练嵌入表里指定的几行，正是本章给两个新特殊 token 的做法 |
| 初始化 | [`LoraLayer.reset_lora_parameters`](https://github.com/huggingface/peft/blob/v0.22.0/src/peft/tuners/lora/layer.py#L364-L385) | A 用 `nn.Linear` 默认的 kaiming 均匀分布，B 全部置零，所以刚加上时模型输出不变，和本章相同 |
| 前向 | [`Linear.forward`](https://github.com/huggingface/peft/blob/v0.22.0/src/peft/tuners/lora/layer.py#L1177-L1218) | `result = result + lora_B(lora_A(dropout(x))) * scaling`：原层的输出加上低秩支路；已经合并过（`self.merged`）时直接走原层 |
| 合并 | [`Linear.get_delta_weight`](https://github.com/huggingface/peft/blob/v0.22.0/src/peft/tuners/lora/layer.py#L1146-L1175) | 增量就是 `B @ A` 乘 scaling；`merge()` 把它加回原权重，`merge_and_unload()` 再把 LoRA 层换回普通线性层，对应本章的 `merged` |

想在本机看源码，可以先 `pip install peft`，再用 `python -m inspect peft.tuners.lora.config:LoraConfig` 这样的命令打印出任意一个类。

<!-- real-model:end -->

## 本章结论：TinyLLM 的选择 {#tinyllm-choice}

TinyLLM 的小模型先用<strong>全参数微调</strong>（第 38 章），把它当作质量和遗忘的基线；只有显存或要同时维护多套微调时，才换成 LoRA：加在每个 Block 的全部线性层上，B 初始化为 0，α = 2r，学习率比全参数微调大（这里 1e-2 对 3e-3），新加的特殊 token 单独放开嵌入行；训练完合并回原权重再部署。比较两者时，同时看任务效果和原来能力的损失。

为什么：在同一个基座和 SFT 数据上（一个种子），全参数微调的首字对 0.39，LoRA r=4、r=32 只有 0 和 0.05，放开两个新 token 后升到 0.21；格式和句数两者差不多（0.81～0.91）。LoRA 忘得少：预训练验证损失全参数微调升了 0.335，LoRA 只升了 0.20～0.28。LoRA 省下的是梯度和优化器状态（r=4 时三块合计从 2.50 MiB 降到 0.76 MiB），权重和激活没省；按 7B 模型的形状算，全参数微调约 100 GiB，LoRA r=16 约 13 GiB。合并后的输出和合并前只差 7.6e-6。

实验边界：模型只有宽 64、2 层，r=32 已经是宽度的一半，LoRA 的参数比例（5%～42%）远高于大模型上的常见设置（不到 1%），“低秩”的意味在这里很弱；每组只有一个种子，64 条评估指令，首字只在其中 38 条上算（0.05 是 2 条，0.21 是 8 条），几个百分点的差别不能当真；α=2r 让不同秩的对比混着更新幅度；LoRA 的学习率只试了 1e-2，没有为每个秩单独调；显存是按公式算的 FP32 账，没有实测，也没算激活。什么情况下要换：显存够、任务和预训练差得远（要学新能力而不只是新格式）时，用全参数微调；要在一个基座上服务很多用户或任务、每个只训一小套时，用 LoRA 并按请求切换；显存连冻住的权重都放不下时，用 QLoRA。

::: warning 常见误区
- **LoRA 让微调的显存降到原来的百分之一。** 降的是梯度和优化器状态；冻住的权重照样要整份放着，激活也基本没省。7B 模型用 LoRA 仍要 13 GiB 左右。
- **LoRA 和全参数微调效果一样。** 学格式、学风格时常常差不多；要学新能力时，LoRA 常常明显不如（本章的首字，以及 Biderman 等在代码和数学上的结果）。
- **LoRA 推理更慢。** 合并以后和原模型完全一样；不合并时多一条小支路，开销很小。
- **秩越大越好。** r 加大，效果有时只提高一点，遗忘却更多；本章 r 从 4 到 32（α=2r，一个种子），首字对只从 0 到 0.05，遗忘从 0.20 增加到 0.28。
- **加了新的特殊 token，LoRA 自己会学会它们。** 嵌入表冻住时，新 token 的那几行永远停在初始值；要把这几行单独放开（PEFT 的 `trainable_token_indices`）。
:::

## 检查理解

1. 一个线性层 4096×4096，加 r=16 的 LoRA。可训练参数是原来的多少？AdamW 状态（FP32）从多少变成多少？

   <details><summary>参考答案</summary>

   原来 4096×4096 ≈ 1678 万个参数；LoRA 是 16×(4096+4096) = 131072 个，约为原来的 0.78%。AdamW 两份 FP32 状态从 1678 万 × 8 字节 ≈ 128 MiB 变成 131072 × 8 字节 = 1 MiB。冻住的权重本身（BF16 下 32 MiB）不变。

   </details>

2. 为什么 B 初始化为 0、A 随机，而不是两个都随机，或者两个都为 0？

   <details><summary>参考答案</summary>

   两个都随机，刚加上时 $BA \ne 0$，模型一开始就被改动了，SFT 从一个被扰乱的起点开始。两个都为 0，$\partial L/\partial A$ 正比于 B、$\partial L/\partial B$ 正比于 A，梯度都是 0，永远学不动。B 为 0、A 随机：输出不变，而 B 的梯度正比于 $A x$，不为 0，第一步就能动起来，之后 A 也跟着动。

   </details>

3. 放开两个新 token 只多了 128 个参数，为什么对首字的帮助比把 r 从 4 加到 32 还大？

   <details><summary>参考答案</summary>

   `<user>`、`<assistant>` 在预训练里从未出现，嵌入表里这两行没有学到有用的表示；嵌入表冻住时，它们在 SFT 里也学不到。首字要求模型在 `<assistant>` 这个位置启动“去指令里找字”的注意力，这个位置的输入向量本身就不对，后面的层再怎么加 LoRA 都事倍功半。放开这两行，等于直接修好了这个位置的输入。

   </details>

4. 一个服务要给 100 个客户各自微调一个 7B 模型。用全参数微调和用 LoRA，部署时各需要存多少权重？

   <details><summary>参考答案</summary>

   全参数微调是 100 份完整的模型，BF16 下每份约 13.5 GB，共约 1.35 TB，而且每个客户都要单独加载。LoRA 只存一份基座（13.5 GB）加 100 套增量；r=16 加在全部线性层上每套约 4000 万个参数，BF16 下约 80 MB，100 套共约 8 GB。推理时基座常驻，按请求切换增量（或多套增量在同一个 batch 里一起算）。

   </details>

## 参考资料

- [LoRA: Low-Rank Adaptation of Large Language Models，Hu 等，2021](https://arxiv.org/abs/2106.09685)
- [QLoRA: Efficient Finetuning of Quantized LLMs，Dettmers 等，2023](https://arxiv.org/abs/2305.14314)
- [LoRA Learns Less and Forgets Less，Biderman 等，2024](https://arxiv.org/abs/2405.09673)
- [PEFT（GitHub）](https://github.com/huggingface/peft/tree/v0.22.0)

这两章的 SFT 数据都是从诗反推出来的。真实的小模型，后训练数据往往来自一个更大的模型：让大模型写，小模型学，甚至直接学大模型的概率分布。[第 40 章：蒸馏与合成数据](./distillation.md)。
