---
title: "第 3 章：架构演进：从 Transformer 到 GPT 再到今天"
description: "三代架构怎样服务同一个目标：2017 年为翻译设计的 Transformer，只留解码器、预测下一个 token 的 GPT，以及 2026 年用稀疏专家和混合注意力做大做省的 Kimi K3。"
pageClass: tinyllm-course
---

# 第 3 章：架构演进：从 Transformer 到 GPT 再到今天

[课程总览](./index.md) · [上一章](./tensors-and-autograd.md) · [下一章](./tokenization.md)

::: tip 本章学习目标
能说出三代架构各自为什么目标设计、数据怎样流过它们：编码器-解码器的 Transformer、只有解码器的 GPT、以 Kimi K3 为代表的稀疏混合架构；能指出每一代解决了上一代的什么问题、又留下了什么问题；能说清 TinyLLM 选的是哪一代、哪些零件放到后面的专题。

**前置：** [第 1 章](./first-run.md)跑通的流水线；知道“预测下一个 token”是什么意思。

**实践方式：** [architecture-evolution.ipynb](/tinyllm/notebooks/architecture-evolution)（也可以直接运行 <a href="/tinyllm/code/architecture-evolution.py" download>architecture-evolution.py</a>），CPU 几秒钟。本章不训练模型，只用很小的张量把几代架构最关键的区别算出来。
:::

<TinyLLMMap active="architecture-evolution" />

## 问题：TinyLLM 的每个零件从哪里来？

[第 1 章](./first-run.md)跑通的模型里，有注意力、位置向量、归一化、前馈层、残差……为什么偏偏是这些零件、这样排列？它们不是一次设计出来的，而是八九年里一代代改出来的。每一代都在回答同一个问题：<strong>怎样把“预测下一个 token”做得更好、做得更大、用得起。</strong>

先看全貌，再一代一代拆开：

![第一代（2017）：为翻译设计的编码器-解码器 Transformer，用注意力取代循环网络、用位置编码标出词序，需要成对数据。第二代（2018～2023）：只有解码器，预测下一个 token；GPT-1 去掉编码器，GPT-2 把归一化挪到子层前，GPT-3 扩大到 1750 亿参数，2021 年出现 RoPE，2023 年 LLaMA 与 Llama 2 采用 RMSNorm、SwiGLU、RoPE 和 GQA。第三代（2024～2026）：稀疏加混合注意力；DeepSeek-V2/V3 用 MLA 压缩 KV 并采用细粒度 MoE，Qwen3-Next 与 Kimi Linear 把线性注意力和完整注意力按 3:1 混合，Kimi K3 有 2.8 万亿参数、896 个专家每次选 16 个、100 万 token 上下文](/tinyllm/figures/architecture-timeline.svg)

::: info 本章代码从哪里来
本章所有代码都在一个文件里：<a href="/tinyllm/code/architecture-evolution.py" download>architecture-evolution.py</a>（[在 GitHub 上查看](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/tinyllm/code/architecture-evolution.py)）。下面的代码块都是从这个文件里直接截取的片段；想自己运行，请下载完整文件，`python architecture-evolution.py` 从头跑到尾即可。notebook 版本也由同一个文件生成，可以[在线查看](/tinyllm/notebooks/architecture-evolution)，或[在 Colab 中直接运行](https://colab.research.google.com/github/lewislau86/lewislau86.github.io/blob/master/docs/public/tinyllm/notebooks/architecture-evolution.ipynb)。
:::

## 1. 第一代：Transformer（2017），为翻译而生

**目标：** 输入一句英文，输出一句中文。

在 Transformer 之前，翻译模型多用循环神经网络（RNN）：一个词一个词地读，前面的信息要一步步传下去，句子一长就容易丢，而且没法并行计算。2017 年的《Attention Is All You Need》把循环整个拿掉，只用注意力。模型分成两半：

- **编码器**一次读完整句原文。原文的每个词都能看其他所有词，前后都能看。
- **解码器**一个词一个词地写译文。写的时候只能看自己已经写出的部分（不能偷看后面的答案），还要通过**交叉注意力**回头看原文的任意位置。

这三种注意力的区别，就在于“谁能看谁”：

<<< @/public/tinyllm/code/architecture-evolution.py#masks

```text
编码器自注意力: 形状 (5, 5)，能看的位置 25 / 25
解码器自注意力: 形状 (4, 4)，能看的位置 10 / 16
交叉注意力: 形状 (4, 5)，能看的位置 20 / 20
```

解码器那张表是下三角：第 1 个译词只能看自己，第 4 个能看前 4 个。这正是[第 6 章](./self-attention.md)的因果掩码。

![左：2017 年的 Transformer 用编码器读完整句英文 the book on the table，解码器逐词生成“桌子上的书”，每生成一个词都通过交叉注意力回头看原文的任意位置，因此词序不同也能对上。右：GPT 去掉编码器，只保留只能看前文的解码器，在连续文本上预测下一个 token](/tinyllm/figures/transformer-to-gpt.svg)

**它怎样实现目标：** 注意力让“书”可以直接去看 book，不管它们隔得多远、语序是否相同；所有位置可以同时计算，训练比 RNN 快得多。注意力本身分不出先后，所以要加**位置编码**（[第 7 章](./position-encoding.md)）；每个子层后面接残差和 LayerNorm（Post-Norm），再配一个前馈层。今天大模型里的零件，在这里已经基本齐了。

**留下的问题：** 训练要“原文 → 译文”成对的数据，需要人去准备，数量有限；整个结构也是为“读一段、写另一段”的任务设计的。

## 2. 第二代：GPT（2018～2023），只留下解码器

**目标：** 根据前面的字，预测下一个字。就这一件事。

2018 年的 GPT 做了一个减法：去掉编码器，也就不需要交叉注意力，只剩“只能看前面”的解码器。好处立刻显现：**训练数据不用再配对了**，任何一段文字错开一位，就是输入和答案：

<<< @/public/tinyllm/code/architecture-evolution.py#data-format

```text
看到 “床” → 预测 “前”
看到 “床前” → 预测 “明”
看到 “床前明” → 预测 “月”
看到 “床前明月” → 预测 “光”
这一句 12 个字，自动得到 11 道“预测下一个字”的练习题
```

书、网页、代码、论坛帖子都能拿来练，数据从此不再是瓶颈。接下来的几年，目标没变，主要是把规模做大：

![GPT-1 于 2018 年发布，1.17 亿参数，训练语料约 7000 本书；GPT-2 于 2019 年，15 亿参数，约 40GB 网页文本；GPT-3 于 2020 年，1750 亿参数，约 3000 亿 token；2022 年的 ChatGPT 在 GPT-3.5 基础上做了指令微调和人类反馈训练](/tinyllm/figures/gpt-scale.svg)

研究者发现，损失会随着数据、参数和算力的增加，按相当稳定的规律下降（缩放定律）。GPT-3 有 1750 亿参数，只要在提示词里看几个例子，就能做没专门训练过的任务。

**零件也在悄悄换。** 模型越大，越需要训得稳、算得省，于是第一代的几个零件被陆续替换。这些替换合起来，就是今天常说的“现代稠密解码器”，也正是 TinyLLM 的主线：

| 零件 | 2017 年的做法 | 换成了什么 | 什么时候 | 本课 |
| --- | --- | --- | --- | --- |
| 归一化的位置 | 子层之后（Post-Norm） | 子层之前（Pre-Norm），深层更好训 | GPT-2，2019 | [第 9 章](./transformer-block.md)、[第 11 章](./normalization.md) |
| 位置 | 正弦位置编码，加在输入上 | RoPE，在注意力里旋转 q、k | 2021 | [第 7 章](./position-encoding.md) |
| 归一化 | LayerNorm | RMSNorm，少一步减均值 | LLaMA，2023 | [第 11 章](./normalization.md) |
| 前馈层 | ReLU 两层 | SwiGLU 门控 | LLaMA，2023 | [第 8 章](./activations-and-ffn.md) |
| K、V 头数 | 每个头一组 | 几个头共用一组（GQA），省缓存 | Llama 2，2023 | [第 6 章](./self-attention.md) |

**它怎样实现目标：** 目标简单到只有一个，数据几乎无限，结构又能整齐地一层层叠上去（[第 9 章](./transformer-block.md)），于是可以一直放大。

**留下的问题：** 放大以后，三笔账越来越重。

- **注意力的账。** 完整注意力生成每个 token 时都要回看全部前文，要把每个旧 token 的 K、V 存着（KV cache，[第 26 章](./inference-efficiency.md)），上下文越长，缓存越大：

<<< @/public/tinyllm/code/architecture-evolution.py#kv-cost

```text
上下文     4,096：全部完整注意力    0.54 GB    3:1 混合    0.14 GB
上下文    32,768：全部完整注意力    4.29 GB    3:1 混合    1.08 GB
上下文   131,072：全部完整注意力   17.18 GB    3:1 混合    4.30 GB
上下文 1,048,576：全部完整注意力  137.44 GB    3:1 混合   34.37 GB
```

  这还只是一个 32 层的中等模型、一条请求。上下文到 100 万 token 时，光缓存就要 137 GB（右边那一列先不管，第 3 节再说）。

- **前馈层的账。** 稠密模型里每个参数对每个 token 都要算一遍。想多装一倍知识就要多一倍参数，计算量也跟着翻倍。
- **训练稳定性的账。** 层数、宽度、数据量都在涨，损失突然发散、训练中断的风险也在涨。

## 3. 第三代：Kimi K3（2026），稀疏专家 + 混合注意力

**目标：** 还是预测下一个 token。但要做到 2.8 万亿参数、一次读 100 万 token，同时让训练和使用的成本可以承受。

我们选 Kimi K3 作为第三代的代表：它是 2026 年 7 月公开权重和技术报告的模型，在 2026 年 10 月的多个榜单上位列最强的开放权重模型（例如 LMArena 开放模型第一）。它的公开配置如下：

| 项目 | Kimi K3 |
| --- | --- |
| 总参数 / 每个 token 用到的参数 | 2.8 万亿 / 1040 亿 |
| 层数 | 93 层（其中 1 层稠密） |
| 注意力 | 69 层 KDA（线性注意力）+ 24 层 Gated MLA（完整注意力） |
| 前馈层 | MoE：896 个专家每次选 16 个，另有 2 个共享专家 |
| 隐藏维度 / 注意力头 | 7168 / 96 |
| 词表 / 上下文 | 16 万 / 1,048,576 token |
| 其他 | 原生多模态（4 亿参数的视觉编码器）；训练时就按 MXFP4 权重量化 |

它对第二代留下的三笔账，各有一个回答。

**① 注意力的账：大部分层换成线性注意力。** 线性注意力不保留每个旧 token 的 K、V，而是边读边把信息累加进一个固定大小的“状态”。最朴素的版本去掉 softmax 就能写成这样，下面验证它和“一次算整张表”结果相同：

<<< @/public/tinyllm/code/architecture-evolution.py#linear-attention

```text
两种写法最大差异: 5.960464477539063e-08
状态 S 的形状: (4, 4) —— 读了 6 个 token，读 100 万个也还是这么大
```

状态的大小和读了多少 token 无关，所以线性注意力的层不会随上下文变长而占用更多缓存。代价是“压缩”会丢细节，没法像完整注意力那样精确地回头找某一个字。Kimi K3 的做法是混合：大约每 4 层里 3 层用 KDA（在朴素线性注意力上加了按通道的遗忘门和 delta 更新规则），1 层保留完整注意力，用 Gated MLA（KV 先压缩再存）。上一节表格右边那一列，就是这种 3:1 混合的缓存估算，约为全部用完整注意力的四分之一：

![按 32 层、每层 8 个 KV 头、每头 128 维、BF16 估算：每层都用完整注意力时，缓存从 4096 个 token 的 0.54 GB 涨到 100 万个 token 的 137 GB；3 层线性注意力加 1 层完整注意力时只有约四分之一，100 万个 token 约 34 GB](/tinyllm/figures/architecture-cost.svg)

**② 前馈层的账：稀疏专家（MoE）。** 把一个大前馈层拆成很多个小前馈层（专家），路由器给每个 token 只挑少数几个：

<<< @/public/tinyllm/code/architecture-evolution.py#moe-count

```text
每个 token 选中的专家: [[6, 5], [4, 3], [2, 3], [2, 3], [3, 2]]
玩具 MoE：总参数 133,120，每个 token 用到 33,664（25%）
Kimi K3：总参数 2.8 万亿，每个 token 用到 1040 亿（3.7%）
```

参数多，能装下的规律就多；每个 token 只用其中 3.7%，计算量就不会跟着参数一起暴涨。代价是要让 896 个专家分工均衡，训练更难（[第 24 章](./mixture-of-experts.md)会做实验）。

**③ 训练稳定性的账：改残差和优化器。** Kimi K3 的 Attention Residuals 把“每层简单地加回残差流”改成：每一层可以有选择地回看前面所有层的输出。配合专门为稀疏 MoE 设计的稳定训练方法，才撑得住这么大的规模。

![左：GPT-1 由 12 个相同的 Block 组成，每个 Block 是完整注意力加稠密前馈层。右：2026 年的典型做法每 4 层为一组，前 3 层用便宜的线性注意力、第 4 层用完整注意力，每层后接 MoE 前馈层；MoE 由很多小专家组成，路由器为每个 token 只挑少数几个，另有所有 token 共用的共享专家](/tinyllm/figures/modern-block.svg)

Kimi K3 不是唯一的路线。2026 年另外两个公开了架构细节的代表，在“省”的方向上一致，具体做法不同：

| | GPT-1（2018） | Kimi K3（2026） | DeepSeek V4-Pro（2026） | Qwen3.5（2026） |
| --- | --- | --- | --- | --- |
| 总参数 / 每个 token 实际用到 | 1.17 亿 / 全部 | 2.8 万亿 / 1040 亿 | 1.6 万亿 / 490 亿 | 旗舰 3970 亿 / 170 亿；另有 20 亿等稠密小尺寸（全部用到） |
| 注意力 | 每层完整注意力 | 69 层线性注意力（KDA）+ 24 层完整注意力（Gated MLA） | 两种压缩注意力（CSA、HCA）混合 | 每 4 层：3 层线性注意力（Gated DeltaNet）+ 1 层完整注意力 |
| 前馈层 | 稠密 | MoE：896 个专家选 16 个，另有 2 个共享专家 | MoE | 旗舰为 MoE：512 个专家选 10 个，另有 1 个共享专家；小尺寸为稠密 |
| 一次能读多长 | 512 token | 约 100 万 token | 约 100 万 token | 原生 262,144 token，可扩展到约 100 万 |
| 开放方式 | 论文 | 权重 + 技术报告，Kimi K3 License | 权重 + 技术报告，MIT | 权重，Apache-2.0 |
| 训练目标 | 预测下一个 token | 预测下一个 token | 预测下一个 token | 预测下一个 token |

DeepSeek V4 保留注意力，但把要回看的内容压缩；Qwen3.5 也是“3 层线性注意力 + 1 层完整注意力”交替，而且有 20 亿参数的稠密小尺寸，普通电脑就能下载下来和 TinyLLM 逐层对照。

## 4. 三代对照：同一个目标，三种实现

| | 第一代：Transformer | 第二代：GPT（现代稠密解码器） | 第三代：Kimi K3 |
| --- | --- | --- | --- |
| 为什么设计 | 翻译 | 预测下一个 token | 预测下一个 token，做大且省 |
| 训练数据 | 成对的原文和译文 | 任何文本 | 任何文本，外加图像、视频 |
| 结构 | 编码器 + 解码器 | 只有解码器 | 只有解码器 |
| 注意力 | 编码器双向、解码器因果、加交叉注意力 | 每层完整的因果注意力 | 约 3/4 层线性注意力，1/4 层完整注意力 |
| 前馈层 | 稠密 | 稠密（SwiGLU） | 稀疏 MoE，每次用 3.7% 的参数 |
| 解决了 | RNN 难并行、长距离对不齐 | 不再需要配对数据，可以一直放大 | 长上下文的缓存、参数增长带来的计算 |
| 留下的问题 | 数据要人工配对 | 缓存随上下文增长、计算随参数增长 | 训练更复杂，需要专门的稳定方法 |

<!-- real-model:start -->

## 在真实模型里

第二代和第三代的区别，在 transformers 里就是两个 Block 类的区别。下表的链接都指向 Hugging Face transformers 的固定版本 `v5.21`，精确到行。读代码时可以先跳过缓存、掩码、并行这些工程细节，只看和本章对应的那几行。

| 本章的零件 | 真实代码 | 对照要点 |
| --- | --- | --- |
| 第二代：现代稠密解码器的 Block | [`LlamaDecoderLayer`](https://github.com/huggingface/transformers/blob/v5.21/src/transformers/models/llama/modeling_llama.py#L273-L313) | 每层都是完整注意力加 SwiGLU，TinyLLM 的主线就是它 |
| 第三代：混合注意力的 Block | [`Qwen3_5DecoderLayer`](https://github.com/huggingface/transformers/blob/v5.21/src/transformers/models/qwen3_5/modeling_qwen3_5.py#L848-L901) | `config.layer_types` 决定这一层用线性注意力（`linear_attn`）还是完整注意力（`self_attn`），对应本章的 3:1 混合 |
| 线性注意力层 | [`Qwen3_5GatedDeltaNet`](https://github.com/huggingface/transformers/blob/v5.21/src/transformers/models/qwen3_5/modeling_qwen3_5.py#L490-L650) | Gated DeltaNet：在本章朴素线性注意力的基础上加了遗忘门和 delta 更新规则 |
| 逐 token 更新状态 | [`torch_recurrent_gated_delta_rule`](https://github.com/huggingface/transformers/blob/v5.21/src/transformers/models/qwen3_5/modeling_qwen3_5.py#L424-L483) | 一个 token 一个 token 地更新固定大小的状态，和本章 linear-attention 那段代码的写法二是同一个思路 |

想在本机看源码，可以先 `pip install transformers`，再用 `python -m inspect transformers.models.llama.modeling_llama:LlamaMLP` 这样的命令打印出任意一个类。

<!-- real-model:end -->

## 本章结论：TinyLLM 的选择 {#tinyllm-choice}

TinyLLM 的主线采用**第二代的现代稠密解码器**：只有解码器，因果注意力配 RoPE，Pre-Norm 的 RMSNorm，SwiGLU 前馈层。这一代的每个零件都能在 CPU 上单独做实验、看清它的作用，而且至今仍是第三代模型的骨架：Kimi K3 换掉的是注意力的种类和前馈层的密度，“只有解码器、预测下一个 token、Block 一层层叠”的整体结构没有变。第三代的零件放在后面的专题里，在主线基础上逐个替换、对照：MoE 在[第 24 章](./mixture-of-experts.md)，KV cache 和推理成本在[第 26 章](./inference-efficiency.md)，量化在[第 28 章](./quantization.md)。

::: warning 常见误区
- **新架构没有改变目标。** 从 GPT-1 到 Kimi K3，训练目标都是预测下一个 token；变的是怎样算得更省、做得更大。
- **线性注意力没有完全取代完整注意力。** 它把前文压成固定大小的状态，会丢细节，所以主流做法是混合，保留一部分完整注意力层做精确查找。
- **2.8 万亿参数不等于每个 token 算 2.8 万亿次。** MoE 每次只激活一小部分，Kimi K3 每个 token 用到约 1040 亿个参数。
- **编码器-解码器没有被淘汰。** 语音识别、一些翻译系统仍在用它；只是在“通用语言模型”这条路上，只有解码器的结构更容易放大。
:::

## 检查理解

1. 第一代 Transformer 里有哪三种注意力？各自“谁能看谁”？

   <details><summary>参考答案</summary>

   编码器自注意力：原文每个词能看原文所有词；解码器自注意力：译文每个词只能看自己和前面已写出的词（下三角）；交叉注意力：译文每个词能看原文所有词。

   </details>

2. GPT 去掉编码器以后，训练数据发生了什么变化？为什么这对放大规模很关键？

   <details><summary>参考答案</summary>

   不再需要“原文 → 译文”成对的数据，任何一段文本错开一位就是输入和答案。数据几乎不受限制，才能支撑参数和算力一起放大。

   </details>

3. 上下文从 13 万 token 增加到 100 万 token，完整注意力的 KV cache 变大多少倍？线性注意力的状态呢？

   <details><summary>参考答案</summary>

   KV cache 和上下文长度成正比，约变大 8 倍（17.18 GB → 137.44 GB）；线性注意力的状态大小固定，不随上下文变化。

   </details>

4. Kimi K3 为什么不把所有层都换成线性注意力？

   <details><summary>参考答案</summary>

   线性注意力把前文压缩进固定大小的状态，会丢掉细节，难以精确找回某个具体位置的信息。保留约四分之一的完整注意力层，用来做精确查找；其余层用线性注意力省缓存和计算。

   </details>

5. TinyLLM 为什么选第二代的稠密解码器，而不是直接做 Kimi K3 那样的结构？

   <details><summary>参考答案</summary>

   第二代结构是第三代的骨架，每个零件都能在 CPU 上单独实验、看清作用；MoE、混合注意力等第三代零件都是为大规模和长上下文准备的，在小模型上收益有限、训练更复杂，放在后面的专题里对照着讲更清楚。

   </details>

## 参考资料

- [Attention Is All You Need，Vaswani 等，2017](https://arxiv.org/abs/1706.03762)
- [Improving Language Understanding by Generative Pre-Training（GPT-1），Radford 等，2018](https://cdn.openai.com/research-covers/language-unsupervised/language_understanding_paper.pdf) · [Language Models are Unsupervised Multitask Learners（GPT-2），2019](https://cdn.openai.com/better-language-models/language_models_are_unsupervised_multitask_learners.pdf) · [Language Models are Few-Shot Learners（GPT-3），2020](https://arxiv.org/abs/2005.14165)
- [Scaling Laws for Neural Language Models，Kaplan 等，2020](https://arxiv.org/abs/2001.08361)
- [LLaMA，Touvron 等，2023](https://arxiv.org/abs/2302.13971) · [GQA，Ainslie 等，2023](https://arxiv.org/abs/2305.13245)
- [DeepSeek-V2（MLA 与 DeepSeekMoE），2024](https://arxiv.org/abs/2405.04434) · [Kimi Linear（KDA），2025](https://arxiv.org/abs/2510.26692)
- [Kimi K3 模型仓库与技术报告](https://github.com/MoonshotAI/Kimi-K3) · [2026 年 10 月开放权重模型榜单汇总](https://www.taskade.com/blog/open-source-llms)

知道了这些零件的来历，接下来就沿着第二代解码器的数据流，从第一站开始一件件搭：文字怎样变成模型能处理的编号，[第 4 章：文本与词元化](./tokenization.md)。
