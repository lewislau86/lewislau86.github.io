---
title: "第 12 章：完整 TinyLLM"
description: "把第 4～11 章的零件装成一个能训练、能生成的完整模型：先估后数参数量、沿数据流核对形状、三项体检，再固定数据划分与评估口径，训练出后半本书的基线。"
pageClass: tinyllm-course
---

# 第 12 章：完整 TinyLLM

[课程总览](./index.md) · [上一章](./normalization.md) · [下一章](./gpu-training.md)

::: tip 本章学习目标
能把字节级 BPE、RoPE 因果注意力、SwiGLU、Pre-RMSNorm、第 10 章的初始化和权重共享写进同一个模型类；能在训练前先估参数量、再沿数据流核对形状，并用三项体检（初始损失、因果性、权重共享）排除装配错误；能说清本章固定下来的数据划分、batch 计划和验证口径，以及为什么后面每一章都要和这条基线比。

**前置：** [第 4 章](./tokenization.md)的 BPE、[第 5 章](./embeddings-and-output.md)的权重共享、[第 6 章](./self-attention.md)到[第 9 章](./transformer-block.md)的注意力、RoPE、SwiGLU 与 Block，[第 10 章](./initialization-and-residuals.md)的初始化，[第 11 章](./normalization.md)的 RMSNorm。

**实践方式：** [tinyllm-model.ipynb](/tinyllm/notebooks/tinyllm-model)（也可以直接运行 <a href="/tinyllm/code/tinyllm-model.py" download>tinyllm-model.py</a>），CPU 约两分钟，需要 PyTorch 和 `tokenizers`。
:::

<TinyLLMMap active="tinyllm-model" />

## 问题：每个零件都验过了，整机呢？

第 4～11 章各做好一个零件，每一章都只在自己的小实验里证明“这个零件没问题”。[第 1 章](./first-run.md)倒是跑通过一整台机器，但那是为了先看到全貌拼起来的玩具：按字编号、位置用一张可学习的表、39 首诗、随机抽 batch。

本章做两件事。第一，把各章选定的正式零件装进同一个模型类，并在训练之前用几项体检确认没装错。第二，把数据怎么分、batch 怎么抽、验证损失怎么算全部固定下来，训练出一条**基线**。后面的数据、损失、学习率、正则化、精度各章，每改一处都和这条基线比。

::: info 本章代码从哪里来
本章所有代码都在一个文件里：<a href="/tinyllm/code/tinyllm-model.py" download>tinyllm-model.py</a>（[在 GitHub 上查看](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/tinyllm/code/tinyllm-model.py)）。下面的代码块都是从这个文件里直接截取的片段，所以单独复制一段可能缺少 `import` 或前面定义的变量；想自己运行，请下载完整文件，`python tinyllm-model.py` 从头跑到尾即可。notebook 版本也由同一个文件生成，可以[在线查看](/tinyllm/notebooks/tinyllm-model)，或[在 Colab 中直接运行](https://colab.research.google.com/github/lewislau86/lewislau86.github.io/blob/master/docs/public/tinyllm/notebooks/tinyllm-model.ipynb)。正文引用的输出来自 torch 2.14.1+cpu、tokenizers 0.23.3。
:::

## 1. 和第 1 章比，换掉了什么

先把两台机器并排放好。结构骨架没变（嵌入 → 若干 Pre-Norm Block → RMSNorm → 输出层），变的是每个零件换成了各章验证过的版本，以及数据和评估的做法：

| 环节 | 第 1 章的玩具 | 本章的基线 | 依据 |
| --- | --- | --- | --- |
| 分词 | 按字编号，词表 556 | 在训练集上训练的字节级 BPE，词表 4096 | [第 4 章](./tokenization.md) |
| 位置 | 可学习的位置表，最多 24 个位置 | Q、K 上加 RoPE，不占参数 | [第 7 章](./position-encoding.md) |
| 初始化 | 只给嵌入表设了标准差，线性层用 PyTorch 默认 | 线性层 Xavier normal，嵌入 `1/√d`，两个输出投影再乘 `1/√(2L)` | [第 10 章](./initialization-and-residuals.md) |
| 尺寸 | d=96，3 层，上下文 24 | d=128，4 层，4 头，上下文 64 | 本章 |
| 数据 | 39 首诗，其中 4 首留作验证 | 统一语料前 6000 首，按 `split` 字段分训练 / 验证 | [实验环境](./setup.md#数据从哪里来) |
| batch | 每步临时随机抽 | 由单独的随机数生成器事先排好的 batch 计划 | 本章第 5 节 |
| 验证 | 每次随机抽 8 段算平均，结果带随机性 | 整个验证集切成不重叠窗口全部算一遍，另报“每字比特” | 本章第 5 节 |

注意力（[第 6 章](./self-attention.md)）、SwiGLU（[第 8 章](./activations-and-ffn.md)）、Pre-RMSNorm Block（[第 9 章](./transformer-block.md)、[第 11 章](./normalization.md)）、输入输出共享权重（[第 5 章](./embeddings-and-output.md)）两台机器都有，本章原样沿用。

## 2. 配置、数据和分词器

模型的所有尺寸集中在一个配置对象里。[第 13 章](./gpu-training.md)把模型搬上 GPU 时，只改这张表，不改模型代码：

<<< @/public/tinyllm/code/tinyllm-model.py#config

数据取统一唐诗语料的前 6000 首。每首诗自带 `split` 字段（按正文哈希固定划分），验证集里的诗训练时一次也不看：

<<< @/public/tinyllm/code/tinyllm-model.py#data

```text
训练集： 5419 首， 233088 字
验证集： 291 首， 12552 字
```

分词器照[第 4 章](./tokenization.md)的做法训练字节级 BPE，只用训练集，免得验证集的信息漏进词表：

<<< @/public/tinyllm/code/tinyllm-model.py#tokenizer

```text
词表大小： 4096
“床前明月光” → [1069, 498, 1055, 533] ['åºĬ', 'åīį', 'æĺİæľĪ', 'åħī']
训练集里不同的字：4569，其中 2189 个是单个 token，其余 2380 个拆成字节
```

“明月”两个字合成了一个 token（第三个 token 的 6 个字节），其余三个字各占一个。乱码一样的 token 文本是字节级 BPE 的显示方式：每个字节映射成一个可打印字符，第 4 章讲过。

4096 的词表装不下训练集里全部 4569 个字，一半以上的字（多是生僻字）要拆成 2～3 个字节 token；常用的字和词组则合并成单个 token。两头相抵，后面会看到验证集平均每个字约 0.95 个 token。词表开多大是第 4 章讲过的权衡：词表越大，嵌入表和输出层越大，每段文字的 token 越少。本章先取 4096，留作动手实验。

## 3. 把零件装起来

四个零件都来自前面各章，这里写进一个文件。RoPE 的 cos/sin 表按位置预先算好，注册成缓冲区，每层共用：

<<< @/public/tinyllm/code/tinyllm-model.py#rope

注意力和 SwiGLU 前馈层，线性层都不带偏置。两个类里各有一个“输出投影”（`proj`、`down`），它们把子层的结果写回残差流，初始化时要特别处理：

<<< @/public/tinyllm/code/tinyllm-model.py#attention

<<< @/public/tinyllm/code/tinyllm-model.py#swiglu

Block 是第 9、11 章选定的写法，两次 Pre-RMSNorm、两次残差相加：

<<< @/public/tinyllm/code/tinyllm-model.py#block

最后是整机。输出层不另建矩阵，直接乘嵌入表的转置；`init_weights` 把第 10 章的初始化配方一次做完：

<<< @/public/tinyllm/code/tinyllm-model.py#model

![完整 TinyLLM 的数据流：11 个 token 的 ID 查嵌入表变成 [1, 11, 128]，穿过 4 个 Pre-Norm Block 形状不变，最终 RMSNorm 后乘嵌入表的转置得到 [1, 11, 4096] 的 logits；右侧条形图显示 131 万个参数里嵌入表占 40%，4 个 Block 占 60%](/tinyllm/figures/tinyllm-model-shapes.svg)

怎么读这张图：左边从上往下是一次前向计算，虚线框里的 Block 重复 4 次，进出形状都是 `[1, 11, 128]`；橙色虚线表示输出层用的就是最上面那张嵌入表。右边是参数的去处，下一节先猜再数。

## 4. 训练之前的三项体检

一个模型装好，第一次训练之前先排除装配错误。装错的模型往往也能训练、损失也会下降，只是到后面才发现结果不对，那时就很难查了。

### 体检一：参数量先估再数

先猜：d=128、4 层、词表 4096，一共多少参数？

[第 9 章](./transformer-block.md)算过，一个 Block 约 $12d^2$：注意力的 Q/K/V 和输出投影共 $4d^2$；SwiGLU 三个矩阵共 $3 \times d \times 8d/3 = 8d^2$（中间宽度取整为 341，所以略少）；再加两个 RMSNorm 的 $2d$。嵌入表 $V \times d$，输出层共享它，不另算；最后的 RMSNorm 再加 $d$：

$$
4096 \times 128 + 4 \times (4 \times 128^2 + 3 \times 128 \times 341 + 2 \times 128) + 128 = 1{,}311{,}360
$$

<<< @/public/tinyllm/code/tinyllm-model.py#param-count

```text
估算： 1311360   实数： 1311360
  嵌入表（兼输出层）     524,288   40.0%
  全部 Block      786,944   60.0%
  最终 RMSNorm        128    0.0%
```

一个不差。如果对不上，最常见的原因是输出层多建了一张矩阵（没共享）、某个线性层误带了偏置，或者 SwiGLU 的中间宽度写错。

嵌入表占了 40%，这是小模型的特点：$V \times d$ 只随宽度线性增长，Block 却按 $d^2$ 增长。宽度放大到[第 13 章](./gpu-training.md)的几百上千维，Block 的比例就会压倒嵌入表。

### 体检二：沿着数据流看形状

拿一句诗走一遍，每一步打印形状：

<<< @/public/tinyllm/code/tinyllm-model.py#shapes

```text
输入 token ID    (1, 11)
查表之后         (1, 11, 128)
第 1 个 Block 之后 (1, 11, 128)
第 2 个 Block 之后 (1, 11, 128)
第 3 个 Block 之后 (1, 11, 128)
第 4 个 Block 之后 (1, 11, 128)
输出 logits      (1, 11, 4096)
```

“床前明月光，疑是地上霜。”12 个字被切成 11 个 token。中间每一层进出形状都是 `[1, 11, 128]`，Block 才能一层层叠起来（第 9 章）；只有最后一步把宽度 128 换成词表大小 4096：每个位置对下一个 token 的 4096 个打分。

### 体检三：还没训练时应该成立的三件事

<<< @/public/tinyllm/code/tinyllm-model.py#health

```text
初始损失 8.997   ln V = 8.318   logits 标准差 0.997
改最后一个 token，前面位置 logits 的最大变化： 0.0
形状为 (V, d) 的参数张量： 1 个（只有嵌入表，输出层没有另建矩阵）
```

逐条看：

1. **初始损失接近乱猜。** 随机模型对下一个 token 一无所知，交叉熵应接近“4096 个 token 均匀乱猜”的 $\ln 4096 \approx 8.32$。实测略高，因为 logits 并非全为 0，而是有标准差约 1 的起伏；对这种随机打分，期望损失约为 $\ln V + \sigma^2/2 \approx 8.82$，下一节在整个验证集上测得 8.750，和这个估计相符。如果初始损失是几十上百，多半是初始化或权重共享出了问题：输出层直接用 PyTorch 默认的嵌入初始化（标准差 1），logits 的标准差会放大约 $\sqrt{d} \approx 11$ 倍。
2. **因果。** 只改最后一个 token，前面各位置的 logits 一点都没变。要是变了，说明注意力的因果掩码没生效，模型训练时能偷看答案，训练损失会好得不真实。
3. **共享权重。** 整个模型只有一张 `4096 × 128` 的矩阵。

## 5. 固定评估口径 {#eval-protocol}

接下来要训练了。在动手之前，先把“怎么喂数据、怎么算验证损失”定死。这件事看起来琐碎，却决定了后面各章的比较能不能成立：如果两次实验的 batch 顺序不同、验证集抽样不同，损失差 0.05，你分不清是改动带来的，还是运气。

本章的约定有三条：

- **数据流。** 训练集和验证集各自拼成一条长 token 流，每首诗之后接一个 `<eos>`，模型借它学会“一首诗在哪里结束”。
- **batch 计划。** 训练时每步从训练流里切 32 段、每段 65 个 token（输入 64 个，目标往后错一位）。切哪几段由一个单独的随机数生成器事先排好，和模型初始化用的随机种子分开。后面换结构、换超参数时，各个模型吃的是同一批数据、同样的顺序。
- **验证。** 把整条验证流切成不重叠的 64-token 窗口，每个位置预测下一个 token，全部算一遍取平均，结果不带随机性。除了每 token 的 nats，再换算成**每个字多少比特**：不同分词器切出的 token 数不同，每 token 损失无法直接比较，按字算就可以。

<<< @/public/tinyllm/code/tinyllm-model.py#eval-protocol

```text
训练流 225007 个 token；验证流 12256 个 token
验证集平均每个字 0.954 个 token
训练前验证损失 8.750 nats/token，12.05 比特/字
```

“每字比特”这个数可以这样理解：如果模型对下一个字完全没把握、在训练集出现过的 4569 个字里均匀乱猜，需要 $\log_2 4569 \approx 12.2$ 比特；训练前的 12.05 比特就在这个水平。训练让这个数降下去。

## 6. 训练基线

优化器用 [第 16 章](./optimizers.md)选定的 AdamW，学习率固定为 3e-3；矩阵权重做 weight decay，归一化层的权重不做。每步按全局范数把梯度裁到 1，防止偶发的大梯度（[第 20 章](./gradient-stability.md)）。学习率调度、dropout、混合精度都先不加：它们各有一章，要在这条基线上逐项对照。

<<< @/public/tinyllm/code/tinyllm-model.py#train

```text
step   0  验证损失 8.750  (12.05 比特/字)
step  50  验证损失 6.289  (8.66 比特/字)
step 100  验证损失 6.136  (8.45 比特/字)
step 150  验证损失 5.907  (8.13 比特/字)
step 200  验证损失 5.761  (7.93 比特/字)
step 250  验证损失 5.654  (7.78 比特/字)
step 300  验证损失 5.579  (7.68 比特/字)
```

![完整 TinyLLM 基线的训练与验证损失：两条线一起从约 8.75 降到约 5.58，贴在一起，第 300 步时验证损失仍在下降](/tinyllm/figures/tinyllm-model-loss.svg)

怎么读这张图：

- **前 50 步掉得最快。** 从乱猜的 8.75 一下降到 6.3，这一段模型主要学会了“哪些 token 常见”，相当于记住字频。之后的下降慢得多，要靠上下文猜下一个字。
- **两条线贴在一起。** 最后 50 步的平均训练损失是 5.539，最终验证损失 5.579，几乎没有差距：

  ```text
  最后 50 步平均训练损失 5.539，最终验证损失 5.579
  ```

  这和[30 分钟快速体验](./quickstart.md)正好相反：那里只有 182 首诗，训练损失降到 0.27，验证损失却越来越高，模型在背诗。这里有 5419 首诗，300 步把训练集过了约 2.7 遍，131 万参数的模型还背不下来。
- **曲线还在往下走。** 第 300 步时验证损失仍在下降，说明这个预算下模型还没学够。在 CPU 上多训练几倍的步数，要等十几分钟；更大的模型、更多的数据和步数，交给[第 13 章](./gpu-training.md)的 GPU。

这是**单个种子**的一次运行。换种子会让末位数字有出入，所以后面各章拿它做对照时，结论性的比较都会跑 3 个以上的种子。

## 7. 让它写几首

从 `<eos>`（上一首诗刚结束）开始，按温度 0.8 逐个采样，直到模型自己生成 `<eos>`。生成之后逐句核对，看有多少句原样出现在训练集里：

<<< @/public/tinyllm/code/tinyllm-model.py#generate

```text
晓涋花何下，成表故人。苏明龙病载，足雨秋莎波。   （0/4 句原样见于训练集）
长传清素眼，枕路紫微。叶向三年事，堪逢未不同。草仙人初晚，长月住孤伤。独影轻星色，应忘塞吟游。   （0/8 句原样见于训练集）
谁识诸阳寺，一滨正金阳。六相访无劳，风花簟冷津。唯余行叶晚，西北玉摇深。   （0/6 句原样见于训练集）
尽流将伏杖，天影出疎心。语梦无群地，霄汉贵新期。灵林鬓长减，能引转炾花。积赏怀髭沼，巴池出动云。   （0/8 句原样见于训练集）
```

模型学会了诗的“形”：大多是五字一句，逗号句号交替，四句或八句后自己停下，正好对应语料里的绝句和律诗。没有一句是从训练集里照抄的，这和快速体验里几乎句句背诵的情况不同。但意思基本不通，个别句子还少了一个字，偶尔冒出“涋”“炾”这样的生僻字。验证损失 5.58 的模型就是这个水平，它是一条起跑线，不是终点。

## 8. 记下基线

<<< @/public/tinyllm/code/tinyllm-model.py#baseline

```text
{'params': 1311360, 'vocab': 4096, 'd_model': 128, 'n_layers': 4, 'context': 64, 'train_tokens': 225007, 'steps': 300, 'batch': 32, 'val_loss': 5.579, 'val_bpc': 7.68}
```

| 项目 | 基线 |
| --- | --- |
| 模型 | 131 万参数：d=128，4 层，4 头，上下文 64，SwiGLU 中间宽度 341，权重共享 |
| 分词器 | 字节级 BPE，词表 4096，只在训练集上训练 |
| 数据 | 统一唐诗语料前 6000 首：训练 5419 首（22.5 万 token），验证 291 首（1.2 万 token） |
| 训练 | 300 步 × 32 段 × 64 token；AdamW，学习率 3e-3 固定，weight decay 0.1（不含归一化权重），梯度裁剪 1.0 |
| 验证 | 5.579 nats/token，7.68 比特/字（单个种子） |

后面各章改动任何一处，都在同样的数据、同样的 batch 计划下和这一行比。

## 动手实验

1. **换词表大小。** 把 `TinyConfig` 的 `vocab_size` 改成 2048，再跑一遍。每 token 损失和每字比特，哪一个能用来和 4096 的结果比较？为什么？
2. **去掉权重共享。** 给模型加一个独立的 `nn.Linear(d, V, bias=False)` 当输出层。先估参数量会多多少，再看初始损失有没有变化（提示：新输出层是 Xavier 初始化，logits 的标准差会变）。
3. **去掉 `1/√(2L)`。** 注释掉 `init_weights` 里缩小输出投影的两行。体检一、二的结果会变吗？训练曲线呢？只跑一个种子时，差别多大才值得相信？

<!-- real-model:start -->

## 在真实模型里

本章拼出来的整机，在 transformers 里就是 Llama 的这几个类，结构一一对应。下表的链接都指向 Hugging Face transformers 的固定版本 `v5.21`，精确到行。读代码时可以先跳过缓存、掩码、并行这些工程细节，只看和本章对应的那几行。

| 本章的零件 | 真实代码 | 对照要点 |
| --- | --- | --- |
| 整机：主干 + 输出层 | [`LlamaForCausalLM`](https://github.com/huggingface/transformers/blob/v5.21/src/transformers/models/llama/modeling_llama.py#L410-L480) | `self.model` 是主干，后面接 `lm_head`；`_tied_weights_keys` 声明 `lm_head.weight` 可以指向 `embed_tokens.weight`，和本章的权重共享是同一件事 |
| 主干的前向 | [`LlamaModel.forward`](https://github.com/huggingface/transformers/blob/v5.21/src/transformers/models/llama/modeling_llama.py#L356-L406) | 查表 → 逐层调用 Block → 最后一次 `norm`；多出来的是位置编号、缓存和掩码的准备 |
| 一个 Block | [`LlamaDecoderLayer.forward`](https://github.com/huggingface/transformers/blob/v5.21/src/transformers/models/llama/modeling_llama.py#L284-L313) | `input_layernorm` → 注意力 → 残差相加，`post_attention_layernorm` → MLP → 残差相加，和本章 `Block.forward` 两行一样 |
| RoPE 的 cos/sin 表 | [`LlamaRotaryEmbedding`](https://github.com/huggingface/transformers/blob/v5.21/src/transformers/models/llama/modeling_llama.py#L72-L116) | 按位置预先算 cos、sin，再交给每一层的注意力，对应本章的 `rope_tables` |
| 默认初始化 | [`PreTrainedModel._init_weights`](https://github.com/huggingface/transformers/blob/v5.21/src/transformers/modeling_utils.py#L2294-L2358) | 线性层和嵌入都用标准差 `initializer_range`（默认 0.02）的正态分布；本章按第 10 章改用 Xavier 和 `1/√d`，两者是不同的配方 |

想在本机看源码，可以先 `pip install transformers`，再用 `python -m inspect transformers.models.llama.modeling_llama:LlamaMLP` 这样的命令打印出任意一个类。

<!-- real-model:end -->

## 本章结论：TinyLLM 的选择 {#tinyllm-choice}

TinyLLM 的完整模型是一个**稠密 Decoder-only Transformer**：字节级 BPE 的 token 查嵌入表，经过 L 个 Pre-RMSNorm 残差 Block（RoPE 因果注意力 + 无偏置 SwiGLU），最后一次 RMSNorm，再乘嵌入表的转置得到 logits。初始化按第 10 章：线性层 Xavier normal，嵌入标准差 `1/√d`，注意力和 FFN 的输出投影再乘 `1/√(2L)`。

本章还固定了后半本书的**实验口径**：按 `split` 字段划分训练 / 验证，分词器只在训练集上训练；训练 batch 由独立的随机数生成器事先排好；验证损失在整个验证集的不重叠窗口上全部算一遍，同时报 nats/token 和比特/字。在 CPU 上，d=128、4 层、300 步的基线验证损失是 5.579 nats/token（7.68 比特/字，单个种子），而且还在下降。

这些选择在什么情况下要换：词表大小、宽度、层数是跟着数据量和算力走的，[第 13 章](./gpu-training.md)在 GPU 上放大；输出层要不要独立、要不要换成 GQA 或 MoE，要在同样的数据和参数预算下另做对照（[第 24 章](./mixture-of-experts.md)）。

::: warning 常见误区
- **损失在下降不等于模型装对了。** 因果掩码漏掉、初始化尺度错了的模型，损失一样会降。训练之前先做体检：参数量对得上、形状对得上、初始损失接近 $\ln V$、改后面的 token 不影响前面的输出。
- **不同分词器的每 token 损失不能直接比。** 词表变大，同一段文字切出的 token 变少，每个 token 承载的信息变多，每 token 损失自然变高。比较不同分词器时，换算成每字比特（或每字节比特）。
- **训练损失和验证损失接近，不代表模型已经训好。** 本章两者接近是因为还在“学”而不是“背”；曲线仍在下降，说明还远没到头。
- **这条基线不是最佳配置。** 学习率、步数、尺寸都没有调过。它的作用是给后面各章一个固定的比较起点。
:::

## 检查理解

1. 不运行代码，估算 d=256、6 层、词表 4096 时的参数量。嵌入表还占 40% 吗？

   <details><summary>参考答案</summary>

   SwiGLU 中间宽度 $\lfloor 8 \times 256 / 3 \rfloor = 682$。每个 Block：$4 \times 256^2 + 3 \times 256 \times 682 + 2 \times 256 = 262{,}144 + 523{,}776 + 512 = 786{,}432$；6 层共 4,718,592。嵌入表 $4096 \times 256 = 1{,}048{,}576$，再加最终 RMSNorm 256，合计 5,767,424。嵌入表只占约 18%：宽度翻倍时嵌入表翻倍，Block 的 $d^2$ 项却变成 4 倍。

   </details>

2. 为什么分词器只在训练集上训练？如果用全部 6000 首诗训练词表，会让验证损失偏乐观还是偏悲观？

   <details><summary>参考答案</summary>

   验证集代表“训练时没见过的文本”。用验证集训练词表，验证集里的词组会被合并成 token，验证文本切出的 token 更少、更贴合，模型在验证集上的表现会被高估，也就是偏乐观。哪怕词表本身不含模型参数，它也是从数据里“学”出来的，同样要遵守划分。

   </details>

3. 第 5 节为什么要把 batch 计划和模型初始化的随机种子分开？如果共用一个种子，比较“有 `1/√(2L)` 缩放”和“没有缩放”两个模型时会出什么问题？

   <details><summary>参考答案</summary>

   初始化本身会消耗随机数。共用一个随机数流时，两种初始化消耗的随机数个数或顺序一旦不同，后面抽到的 batch 也跟着不同，两个模型就在不同的数据顺序上训练，损失的差别里混进了“运气”。用一个单独的生成器事先排好 batch 计划，两个模型第几步就用第几个 batch，唯一的差别只剩初始化。

   </details>

## 参考资料

- [LLaMA: Open and Efficient Foundation Language Models，Touvron 等，2023](https://arxiv.org/abs/2302.13971)（RMSNorm、SwiGLU、RoPE 组合的稠密解码器）
- [nanoGPT 的 `model.py`](https://github.com/karpathy/nanoGPT/blob/master/model.py)（权重共享与输出投影按层数缩小初始化的实现）
- [Using the Output Embedding to Improve Language Models，Press 与 Wolf，2017](https://arxiv.org/abs/1608.05859)（输入输出共享权重）
- [PyTorch：`scaled_dot_product_attention`](https://docs.pytorch.org/docs/stable/generated/torch.nn.functional.scaled_dot_product_attention.html)

模型能在 CPU 上训练了，但只有 131 万参数、300 步。下一章把同一份代码搬到 GPU 上，放大配置完整训练：[第 13 章：TinyLLM 在 GPU 上完整实现](./gpu-training.md)。
