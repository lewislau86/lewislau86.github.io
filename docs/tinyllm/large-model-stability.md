---
title: "第 25 章：大规模训练稳定性"
description: "模型变大以后的三类新问题：数值失控、超参数搬不过去、一张卡装不下。在 16 万参数的小模型上用大学习率复现注意力分数失控并用 QK Norm 压住；用 μP 让最佳学习率不随宽度漂移；再用张量运算模拟激活重计算、数据并行、ZeRO/FSDP 与张量并行，算清显存和通信的账。"
pageClass: tinyllm-course
---

# 第 25 章：大规模训练稳定性

[课程总览](./index.md) · [上一章](./scaling-laws.md) · [下一章](./mixture-of-experts.md)

::: tip 本章学习目标
能说清模型变大以后的三类新问题：数值失控、超参数搬不过去、一张卡装不下，以及各自的常见对策；能在小模型上用大学习率复现注意力分数失控，并用 QK Norm 压住它；能解释 μP 为什么能让小模型上调好的学习率直接用到大模型上；能算出数据并行、ZeRO/FSDP 各阶段每张卡要放多少训练状态，说清激活重计算、数据并行、张量并行各自省的是什么、代价是什么。

**前置：** [第 6 章](./self-attention.md#qk-norm)的 QK Norm，[第 10 章](./initialization-and-residuals.md)的初始化与残差缩放，[第 13 章](./gpu-training.md)的显存估算，[第 17 章](./learning-rate.md)与[第 23 章](./hyperparameter-tuning.md)的学习率扫描，[第 20 章](./gradient-stability.md)的梯度尖峰与梯度累积。

**实践方式：** [large-model-stability.ipynb](/tinyllm/notebooks/large-model-stability)（也可以直接运行 <a href="/tinyllm/code/large-model-stability.py" download>large-model-stability.py</a>），CPU 约一分半，需要 PyTorch 和 `tokenizers`。
:::

本课到目前为止，最大的模型是[第 13 章](./gpu-training.md)在 GPU 上训练的 3000 万参数；大部分实验用的是 16 万参数的代理模型。真实的语言模型有几十亿到上万亿参数。模型变大以后，会冒出三类小模型上看不到的问题：

1. **数值失控。** 注意力分数、输出 logits 越长越大，某一天损失突然跳起，训练再也回不去。
2. **超参数搬不过去。** 小模型上调好的学习率，用到大模型上就发散了；可大模型训练一次太贵，没法在它上面扫。
3. **一张卡装不下。** 参数、梯度、优化器状态、激活，加起来远超一张卡的显存。

本章逐一处理。前两类，我们在 CPU 上的小模型里**提前复现**出来；第三类没法在 CPU 上真的跑多卡，就用张量运算模拟几种解法，验证它们和单卡的结果一样，并算清显存和通信的账。

<TinyLLMMap active="large-model-stability" />

::: info 本章代码从哪里来
本章所有代码都在一个文件里：<a href="/tinyllm/code/large-model-stability.py" download>large-model-stability.py</a>（[在 GitHub 上查看](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/tinyllm/code/large-model-stability.py)）。下面的代码块都是从这个文件里直接截取的片段，所以单独复制一段可能缺少 `import` 或前面定义的变量；想自己运行，请下载完整文件，`python large-model-stability.py` 从头跑到尾即可。notebook 版本也由同一个文件生成，可以[在线查看](/tinyllm/notebooks/large-model-stability)，或[在 Colab 中直接运行](https://colab.research.google.com/github/lewislau86/lewislau86.github.io/blob/master/docs/public/tinyllm/notebooks/large-model-stability.ipynb)。正文引用的输出来自 torch 2.14.1+cpu、tokenizers 0.23.3。
:::

## 0. 实验对象

模型代码从第 12 章复制，尺寸是[第 17 章](./learning-rate.md)的代理模型。配置里多了两个开关，默认关闭，这时和第 12 章的模型完全一样：

<<< @/public/tinyllm/code/large-model-stability.py#config

训练函数和第 17 章相同（AdamW、weight decay 0.1、裁剪 1.0、WSD），多了两个选项：z-loss 的系数，以及 μP 时按参数类型分组设置学习率（第 4 节）：

<<< @/public/tinyllm/code/large-model-stability.py#run

## 1. 怎样在小模型上看到大模型的问题

大模型的不稳定很难研究：训练一次要几千张卡跑几个月，出了问题也没法反复试。[Wortsman 等（2023）](https://arxiv.org/abs/2309.14322)发现了一个办法：**大模型上出现的几种不稳定，小模型在大学习率下也会出现**，而大模型上用过的对策，在小模型上同样有效。于是可以在小模型上扫学习率，把“学习率多大时开始坏、坏成什么样”看清楚。

训练完以后，量两个“尺度”：

<<< @/public/tinyllm/code/large-model-stability.py#probes

- **注意力分数的最大值**：softmax 之前的 $q\cdot k/\sqrt{d}$。它太大时，softmax 几乎把全部权重给一个位置，梯度变得极小或极不稳定（[第 6 章](./self-attention.md#qk-norm)）。
- **输出 logits 的 log-sum-exp**：[第 15 章](./language-model-loss.md)讲 z-loss 时用过它。它一路变大，说明 logits 整体在漂移；低精度下，这会让 softmax 的舍入误差变大。

## 2. 数值失控：注意力分数越长越大

峰值学习率从 3e-3 扫到 3e-1（主线是 1e-2），比较三种设置：原样、加 QK Norm、加 z-loss（系数 1e-4，PaLM 用的值）。QK Norm 用 Qwen3 的写法，对每个头的 q、k 各做一次 RMSNorm，再算点积：

<<< @/public/tinyllm/code/large-model-stability.py#attention

（[第 6 章](./self-attention.md#qk-norm)讲的是另一种写法：把 q、k 归一化成单位长度，再乘一个可学习的尺度。两者的目的一样，都是在点积之前把 q、k 的长度控制住。）

先猜一下：学习率变大时，注意力分数会怎样？

<<< @/public/tinyllm/code/large-model-stability.py#instability

```text
峰值学习率               3e-03     1e-02     3e-02     1e-01     3e-01
原样        验证         4.835     4.733     5.210     5.696     6.047
            注意力       15.48     36.37     898.7 1.184e+04 2.223e+05
            lse           8.29      8.62      8.03      7.16      6.65
加 QK Norm  验证         4.856     4.739     5.033     5.131     5.412
            注意力       5.817     7.201      13.7     26.58     216.7
            lse           8.23      8.67      8.42      8.14      7.40
加 z-loss   验证         4.833     4.737     5.239     5.771     5.982
            注意力       14.15     19.14     951.4 1.257e+04 9.281e+04
            lse           8.29      8.58      7.85      6.99      6.69
原样：5 个学习率上的平均验证损失 5.304
加 QK Norm：5 个学习率上的平均验证损失 5.034
加 z-loss：5 个学习率上的平均验证损失 5.312
```

![左：峰值学习率从 3e-3 扫到 3e-1。主线 1e-2 附近三种设置差不多；学习率更大时，原样和加 z-loss 迅速变差，加 QK Norm 变差得慢得多。右：注意力分数的最大值，原样时从 36 涨到 22 万；QK Norm 把它压在 217 以内。z-loss 管的是输出 logits，对注意力分数没有作用](/tinyllm/figures/scale-instability.svg)

怎么读这张表和这张图：

- **原样时，注意力分数随学习率爆炸式增长。** 主线 1e-2 时最大 36；3e-2 时 899；3e-1 时 22 万。分数这么大，softmax 早就饱和了：每个位置几乎只看一个 key，模型学不到东西，验证损失跟着变差。这就是 Wortsman 等人说的“注意力分数增长”，他们在大模型上看到的也是这个现象。
- **QK Norm 把分数压住了，模型对学习率宽容得多。** 3e-1 时最大只有 217；1e-1 时验证损失 5.131，原样是 5.696。5 个学习率上的平均，从 5.304 降到 5.034。
- **在主线学习率上，QK Norm 没有收益。** 1e-2 时 4.739 对 4.733，3e-3 时 4.856 对 4.835，都在第 23 章量出的噪声底线（$\sigma \approx 0.018$）附近。它的价值是让“能用的学习率范围”变宽，而不是让最佳点更好。
- **z-loss 在这里没有起作用。** 它约束的是输出 logits 的大小，而这个小模型的输出 logits 并没有失控：log-sum-exp 一直在 6.6～8.7 之间，学习率越大反而越小。它要防的是另一种失控（输出 logits 越漂越远，低精度下 softmax 出错），这次的实验里没有发生。所以“加 z-loss”的三行和原样几乎一样。

这对大模型意味着什么？大模型上最佳学习率是多少，事先并不知道；而且同样的学习率，模型越大越容易越界（Wortsman 等人发现，模型越大，出现这种失控的学习率越小）。把“能用的学习率范围”拓宽，就是给大模型训练留出安全余量。这也是很多新模型都加 QK Norm 的原因：[ViT-22B](https://arxiv.org/abs/2302.05442) 加它就是为了解决注意力分数发散；OLMo 2 把 QK Norm、z-loss 以及其他几项改动一起用上，把一条满是损失尖峰的训练曲线变得平滑（[OLMo 团队，2024](https://arxiv.org/abs/2501.00656)）。

TinyLLM 的主线仍然**不加** QK Norm（[第 6 章](./self-attention.md#qk-norm)讲过原因：它会改变注意力的表达方式，对长上下文有影响）；把模型放大、或者学习率不得不往上推时，再加上它，并重新评估。

## 3. 深度：残差缩放与 DeepNorm

宽度之外，另一个放大的方向是加深。Wortsman 等人还发现，**加深比加宽更容易让训练对学习率敏感**。[第 10 章](./initialization-and-residuals.md)已经给 TinyLLM 的残差输出投影乘了 $1/\sqrt{2L}$，层数越多，每层写回残差流的更新越小。下面是另一种为极深网络设计的方案。

### DeepNorm：为极深网络改写残差块 {#deepnorm}

[第 11 章](./normalization.md)的 Post-Norm 把相加结果再归一化，直通路径要穿过归一化层；网络一深，训练初期的更新容易过大。DeepNet 论文提出的 DeepNorm 保留 Post-Norm 的位置，同时改两件事：**放大残差直通支、缩小子层权重的初始化**。

$$
x_{\mathrm{next}}=\mathrm{LayerNorm}(\alpha x+F(x))
$$

$\alpha>1$ 让直通路径占更大比重；配套地，子层中指定权重在标准初始化后再乘 $\beta<1$。对 **decoder-only、共 $M$ 层**的模型，论文给出

$$
\alpha=(2M)^{1/4},\qquad \beta=(8M)^{-1/4},
$$

$\beta$ 作用于前馈层权重，以及注意力的 value 投影和 output 投影；query、key 投影不在名单内。编码器或 encoder-decoder 的系数不同，不能套用这组公式。具体见 [DeepNet 论文第 4.3 节](https://arxiv.org/pdf/2203.00555)。

```python
# 示意代码，不能单独运行；可运行的 DeepNorm 实验见 normalization.py
M = 24                                   # 总层数
alpha, beta = (2 * M) ** 0.25, (8 * M) ** -0.25
norm = nn.LayerNorm(d)
y = norm(alpha * x + sublayer(x))        # 只是残差块的前向；初始化还要另做
```

**DeepNorm 是一整套方案**：只给残差乘一个任意的 $\alpha$、不改初始化，不能叫做 DeepNorm；它也不是“把 RMSNorm 换掉”就能得到的收益。论文在最高 1000 层的 Transformer 上验证了它，但 BERT、GPT、LLaMA 的原始架构都没有采用它。

[normalization.ipynb](/tinyllm/notebooks/normalization) 的 DeepNorm 单元格先比较 `alpha=1` 与演示值 `alpha=1.5` 对 LayerNorm 输入的影响，再按论文系数构造一个带因果注意力和前馈层的小 Block，检查形状和梯度。它不验证深层训练效果；本章也没有做深层的训练实验，在 CPU 上训练几十层的模型太慢了。

## 4. 超参数搬不过去：μP

[第 17 章](./learning-rate.md)说过：用标准的参数化，模型越宽，最佳学习率越小；[第 13 章](./gpu-training.md)把宽度从 128 放大到 512、768 时，学习率也从 3e-3 降到了 1e-3、6e-4。这意味着每换一个尺寸都要重新扫学习率，而在大模型上扫，太贵了。

**μP**（maximal update parametrization，[Yang 等，2022](https://arxiv.org/abs/2203.03466)）的思路是：问题不在学习率本身，而在“参数化方式”。标准参数化下，宽度变大时，每一步更新对输出的影响也跟着变大，所以要用更小的学习率抵消。μP 按参数的类型，分别调整初始化、学习率和输出的乘子，让每一步更新对输出的影响不随宽度变。对 Adam 来说，核心规则是：

- **隐藏层的矩阵**（注意力和前馈层里的权重）：学习率乘 $\text{基准宽度}/\text{宽度}$。
- **输出层**：logits 乘 $\text{基准宽度}/\text{宽度}$。
- **词嵌入**：初始化和学习率都不随宽度变。

本章的实现就是这三条（见上面 `config` 里的 `mup_base`、模型的 `init_weights` 和 `forward`，以及训练函数里 `make_optimizer` 的分组）。μP 对注意力的缩放也有要求（用 $1/d_{\text{head}}$ 代替 $1/\sqrt{d_{\text{head}}}$）；这里让每个头固定 16 维、宽度变了只改头数，就绕开了这一条。在基准宽度 64 上，μP 和标准参数化完全相同。

宽度 32、64、128，各扫 5 个学习率（训练 120 步，单个种子）：

<<< @/public/tinyllm/code/large-model-stability.py#mup

```text
学习率              1e-03    3e-03    1e-02    3e-02    1e-01   最好的学习率
SP  宽度 32        6.046    5.822    5.217    5.177    5.579   3e-02
SP  宽度 64        5.884    5.243    5.141    5.285    5.735   1e-02
SP  宽度 128       5.457    5.051    5.215    5.401    5.874   3e-03
μP  宽度 32        5.902    5.696    5.253    5.323    5.842   1e-02
μP  宽度 64        5.884    5.243    5.141    5.285    5.735   1e-02
μP  宽度 128       5.783    5.090    5.017    5.297    5.713   1e-02
```

![左：标准参数化下，宽度 32、64、128 的最佳学习率分别是 3e-2、1e-2、3e-3，宽度每翻一倍，最佳学习率就往小移一档。右：μP 下三种宽度的最佳学习率都是 1e-2，而且同一个学习率下，宽度越大验证损失越低](/tinyllm/figures/scale-mup.svg)

- **标准参数化下，最佳学习率随宽度漂移。** 宽度 32 最好是 3e-2，64 是 1e-2，128 是 3e-3。宽度每翻一倍，最佳学习率就往小移一档（网格每档约 3 倍；理论上按宽度成反比，即每翻一倍减半，网格分辨不出这个差别）。在宽度 64 上调好的 1e-2，直接用到宽度 128 上，验证损失是 5.215，比它在 3e-3 上的 5.051 差了不少。
- **μP 下，三种宽度的最佳学习率都是 1e-2。** 在宽度 64 上调好的学习率，可以直接用到宽度 32 和 128 上。
- **μP 下，宽度越大越好。** 同一个学习率 1e-2，宽度 32、64、128 的验证损失是 5.253、5.141、5.017，一路下降。这是 μP 的另一个承诺：参数化对了，加宽模型就是稳定的改进，不需要每次重新找学习率才能看到收益。

这就是第 23 章说的“在小模型上做风洞实验”：在小宽度上用 μP 扫好学习率，直接用到大宽度上。MiniCPM 就是这样确定大模型的超参数的（[Hu 等，2024](https://arxiv.org/abs/2404.06395)）。

实验的边界：只测了宽度 32 到 128（4 倍），每种 5 个学习率、单个种子、120 步；μP 的实现是针对 Adam 和共享输入输出嵌入的简化版本，没有覆盖深度方向的迁移（深度方向需要另外的缩放规则）。在更大的范围上，μP 的迁移效果见原论文；也有工作发现，训练时长、batch 大小变化时，最佳学习率仍会移动，需要配合第 23 章讲的随规模变化的经验规律。

## 5. 一张卡装不下：先算账

[第 13 章](./gpu-training.md)算过：用混合精度和 AdamW 训练，每个参数大约要 16 字节：BF16 的参数 2 字节、梯度 2 字节，FP32 的主权重 4 字节、Adam 的 $m$ 和 $v$ 各 4 字节。70 亿参数的模型，光这些训练状态就是 112 GB，一张 80 GB 的卡放不下，还没算激活。

[ZeRO](https://arxiv.org/abs/1910.02054)（Zero Redundancy Optimizer）的想法是：多卡数据并行时，每张卡都存一整份训练状态，这是冗余的。把它们切成几份，每张卡只存自己那一份。按切的东西多少分三个阶段。70 亿参数、8 张卡，每张卡要放多少：

<<< @/public/tinyllm/code/large-model-stability.py#memory

```text
数据并行（每张卡一整份）   参数   14.0 GB  梯度   14.0 GB  优化器   84.0 GB  合计  112.0 GB
ZeRO-1：切优化器状态       参数   14.0 GB  梯度   14.0 GB  优化器   10.5 GB  合计   38.5 GB
ZeRO-2：再切梯度           参数   14.0 GB  梯度    1.8 GB  优化器   10.5 GB  合计   26.2 GB
ZeRO-3 / FSDP：再切参数    参数    1.8 GB  梯度    1.8 GB  优化器   10.5 GB  合计   14.0 GB
```

![70 亿参数、8 张卡，混合精度每个参数 16 字节。普通数据并行每张卡放一整份，112 GB，超过一张 80 GB 的卡；ZeRO-1 把优化器状态切成 8 份，降到 38.5 GB；ZeRO-2 再切梯度，26.2 GB；ZeRO-3 / FSDP 连参数也切，14.0 GB](/tinyllm/figures/scale-memory.svg)

优化器状态（FP32 主权重、$m$、$v$，共 12 字节）是最大的一块，ZeRO-1 只切它，就从 112 GB 降到 38.5 GB。ZeRO-3 把参数也切开，每张卡只剩总量的八分之一。PyTorch 的 [FSDP](https://arxiv.org/abs/2304.11277)（Fully Sharded Data Parallel）就是 ZeRO-3 的思路。

这张表只算了训练状态。激活是另一大块，而且它随 batch 和序列长度增长，下一节处理。

## 6. 激活重计算

反向传播要用前向的中间结果（[第 2 章](./tensors-and-autograd.md)），所以前向时每一层的输出都要存着，等反向用完才能释放。**激活重计算**（activation checkpointing，也叫 gradient checkpointing，[Chen 等，2016](https://arxiv.org/abs/1604.06174)）用时间换显存：前向时只存每个 Block 的输入，Block 内部的中间结果都不存；反向到这个 Block 时，从它的输入把前向重算一遍，再接着反向。

![激活重计算：普通训练时 Block 内部的中间结果全都存着；激活重计算只存每个 Block 的输入，反向到这个 Block 时从输入重算](/tinyllm/figures/activation-recompute.svg)

怎么读这张图：黄格是一直留在显存里、等反向用的激活。上面一行每个 Block 都存了输入和五个中间结果；下面一行只存输入，中间结果算完就扔（虚线格），反向传播到这个 Block 时从黄格出发重算一遍。下面的代码直接量出两种做法各存了多少字节。

把“为反向保存下来的张量”一共多少字节直接量出来（参数本身不算）。用一个 8 层、宽度 128 的模型：

<<< @/public/tinyllm/code/large-model-stability.py#recompute

```text
1705088 个参数，batch 16 × 64 个 token
为反向保存的张量：不重算 100.5 MB，每个 Block 重算 9.5 MB（9%）
梯度最大差： 0.0
```

- **省下了九成多的激活。** 从 100.5 MB 降到 9.5 MB，剩下的是 8 个 Block 的输入和最后的 logits。
- **梯度逐位相同。** 重算就是把同样的计算再做一遍，结果完全一样（模型里没有 dropout；有 dropout 时，`checkpoint` 会保存和恢复随机数状态，保证重算时的掩码一样）。
- **代价是多一次前向。** 这次在 CPU 上测，每步慢了约 30%（输出里还打印了实测的倍数）。一个常见的折中是只重算一部分层，或者只重算注意力这类激活特别大的部分。

[第 13 章](./gpu-training.md)优化点 ⑤ 说的就是它：省下的激活显存，可以换成更大的 `micro_batch`。

## 7. 数据并行：每张卡算一份 batch

最常用的多卡训练方式是**数据并行**：每张卡放一份完整的模型，各自拿 batch 的一部分算梯度，然后把所有卡的梯度平均（all-reduce），每张卡用同样的平均梯度更新，模型就保持一致。用 4 份 batch 模拟 4 张卡：

<<< @/public/tinyllm/code/large-model-stability.py#data-parallel

```text
4 张卡平均后和整个 batch 的梯度最大差： 3.4e-08
4 张卡、FP32 梯度：每步每张卡收发约 2·(4-1)/4 × 0.63 MB = 0.94 MB（环形 all-reduce）
8 张卡、FP32 梯度：每步每张卡收发约 2·(8-1)/8 × 0.63 MB = 1.09 MB（环形 all-reduce）
```

结果和[第 20 章](./gradient-stability.md)的梯度累积是同一个道理：每份 batch 的 token 数相同，各自求平均再平均，等于一起算。区别是梯度累积在一张卡上依次算，数据并行在多张卡上同时算，代价是每步要把梯度在卡之间传一遍。用环形 all-reduce 时，每张卡要收发约 $2(N-1)/N$ 份梯度，卡越多越接近 2 份，几乎不随卡数增长。

几个和前几章相关的细节：

- **梯度累积加数据并行时**，每个 micro-batch 反传完都同步一次是浪费的。PyTorch 的 `DistributedDataParallel` 提供 `no_sync()`，只在最后一个 micro-batch 同步（[第 20 章](./gradient-stability.md)）。
- **各卡的 token 数不同时**（比如长短不一的样本），“各自平均再平均”就不等于一起算了，要按[第 15 章](./language-model-loss.md)的做法：先求和，再除以所有卡的总 token 数。
- **随机数**：每张卡的数据顺序要不同、dropout 掩码也应不同，所以每张卡用不同的数据分片和随机种子；保存检查点时，每张卡的随机数状态都要存（[第 21 章](./training-loop.md)）。

## 8. ZeRO/FSDP 与张量并行

数据并行要求每张卡放得下整个模型。放不下时，有两条路：

- **把训练状态切开**（ZeRO-3 / FSDP，第 5 节）。每张卡只存参数的一部分；算到某一层时，用 all-gather 从其他卡把这一层的参数临时收齐，算完就丢掉；反向后用 reduce-scatter 把梯度求和并切开，每张卡只拿回自己负责的那一份。显存除以卡数，通信量比普通数据并行多约一半。
- **把每个矩阵切开**（张量并行，[Shoeybi 等，2019](https://arxiv.org/abs/1909.08053)）。所有卡处理同一个 batch，每张卡只算矩阵的一部分。以 SwiGLU 为例：gate 和 up 按输出维（中间宽度）切开，每张卡算一半中间维；down 按输入维切开，每张卡得到一份“部分和”，最后把各卡的结果相加。模拟两张卡：

<<< @/public/tinyllm/code/large-model-stability.py#tensor-parallel

```text
中间宽度 170，每张卡 85；两卡相加后和单卡的最大差 6.0e-07
每个前馈层前向要 all-reduce 一次，大小 = batch × 长度 × 宽度 = 65536 个数
```

这种“先按列切、再按行切”的安排，让中间那个 SiLU 门控完全在各卡内部算完，前向只在最后需要一次 all-reduce。注意力也可以这样切：按头分到不同的卡上。张量并行每一层都要通信，通信量和激活一样大，所以通常只在同一台机器内、用高速互连的几张卡之间做。

![数据并行：每张卡放完整的模型，各算 batch 的一部分，反向后 all-reduce 梯度。ZeRO-3/FSDP：每张卡只放参数、梯度、优化器状态的一部分，每层用之前 all-gather 参数，反向后 reduce-scatter 梯度。张量并行：每个矩阵切开放在不同的卡上，所有卡处理同一个 batch，每个子层之后 all-reduce 激活](/tinyllm/figures/scale-parallel.svg)

怎么读这张图：三栏是三种切法，每栏上下两个框是两张卡，写着这张卡上放了什么、处理哪一部分数据；红色箭头和下面的红字是这种切法需要的通信。数据并行每张卡都有完整的模型，切的是数据；ZeRO-3/FSDP 每张卡只放模型的一份，用到某一层时再从别的卡把参数凑齐；张量并行把每个矩阵切开，两张卡处理同一批数据。下面这张图把张量并行展开到一个前馈层。

![SwiGLU 的张量并行切分：两张卡各有完整输入，gate 和 up 按列切成两半，门控在本卡内完成，down 按行切成两半得到部分和，最后 all-reduce 相加](/tinyllm/figures/tensor-parallel-swiglu.svg)

怎么读这张图：左右两个大框是两张卡，每张卡只存一半的 gate、up 和 down。gate、up 按列切，所以每张卡算出的是中间 341 维里的一半，SiLU 门控只看自己这一半就能算完；down 按行切，每张卡得到的是完整形状的一份部分和，最后一次 all-reduce 把两份加起来。整个前馈层只通信一次。

还有一种是**流水线并行**：把不同的层放在不同的卡上，像流水线一样把一个 batch 拆成几份依次传下去。真实的大模型训练常常把几种并行组合起来用：机器内张量并行，机器间流水线并行，最外层数据并行（或 FSDP）。

最后是[第 21 章](./training-loop.md)留下的问题：**多卡时怎样存检查点**。训练状态切在多张卡上时，每张卡只存自己那一份，同时记下“怎么切的”。PyTorch 的 `torch.distributed.checkpoint` 就是这样做的，它还支持恢复时换一种切法（比如从 8 张卡换到 16 张卡），自动重新切分。第 21 章“逐位相同”的标准在多卡上仍然适用，只是要存的东西多了每张卡的随机数状态和数据位置。

## 9. 放大以后的稳定性清单

把本章和前几章的手段整理在一起。训练大模型时，它们往往是一起用的，像 OLMo 2 那样，“稳定性”是一整套配方：

| 现象 | 常见对策 | 本课在哪里讲过 |
| --- | --- | --- |
| 注意力分数越来越大 | QK Norm | 本章第 2 节，[第 6 章](./self-attention.md#qk-norm) |
| 输出 logits 漂移 | z-loss | [第 15 章](./language-model-loss.md)，本章第 2 节 |
| 损失偶尔尖峰 | 梯度裁剪；较小的 $\beta_2$（如 0.95）；退回检查点、跳过附近的数据 | [第 20 章](./gradient-stability.md)，[第 21 章](./training-loop.md) |
| 训练初期发散 | 更长的 warmup；较小的峰值学习率 | [第 17 章](./learning-rate.md) |
| 换尺寸后学习率不对 | μP；或者按随规模变化的经验规律重新扫 | 本章第 4 节，[第 23 章](./hyperparameter-tuning.md) |
| 网络很深时不稳 | 残差输出缩放；极深时 DeepNorm | [第 10 章](./initialization-and-residuals.md)，本章第 3 节 |
| 低精度下数值出错 | BF16；关键归约用 FP32 | [第 19 章](./precision.md) |
| 数据里有大量重复片段 | 训练前过滤 | [第 14 章](./data-pipeline.md) |

最重要的一条仍然是监测（[第 20 章](./gradient-stability.md)第 9 节）：梯度范数、注意力分数和输出 logits 的大小、各层激活的大小，都应该随训练一起记录。很多失控在损失尖峰出现之前，就已经在这些量上露出了苗头。

## 动手实验

1. **找到失控的起点。** 在第 2 节的学习率网格里加几个点（比如 1.5e-2、2e-2），找出原样设置下注意力分数开始猛增的学习率。加 QK Norm 后，这个点往后移了多少？
2. **让 z-loss 起作用。** 去掉输出层和词嵌入的权重共享（输出层单独一个 `nn.Linear`），并关掉它的 weight decay，用大学习率训练，看 log-sum-exp 会不会漂移；这时再加 z-loss，有什么变化？
3. **把 μP 扩到宽度 256。** 在第 4 节加上宽度 256（每次约 6 秒），标准参数化的最佳学习率会继续往小移吗？μP 还在 1e-2 吗？
4. **只重算一部分层。** 第 6 节只给前 4 个 Block 加 `checkpoint`，保存的字节数和用时各是多少？画出“重算的层数 - 显存 - 用时”的关系。

<!-- real-model:start -->

## 在真实模型里

本章的几个手段，在 transformers 里分别对应下面这几处。下表的链接都指向 Hugging Face transformers 的固定版本 `v5.21`，精确到行。读代码时可以先跳过缓存、掩码、并行这些工程细节，只看和本章对应的那几行。

| 本章的零件 | 真实代码 | 对照要点 |
| --- | --- | --- |
| QK Norm | [`modeling_qwen3.py 第 229 行`](https://github.com/huggingface/transformers/blob/v5.21/src/transformers/models/qwen3/modeling_qwen3.py#L229) | Qwen3 给每个头的 q、k 各配一个 RMSNorm，和本章 `qk_norm=True` 的写法相同 |
| 激活重计算的开关 | [`PreTrainedModel.gradient_checkpointing_enable`](https://github.com/huggingface/transformers/blob/v5.21/src/transformers/modeling_utils.py#L3109-L3175) | 给模型里的每一层打开重计算，底层就是本章用的 `torch.utils.checkpoint` |
| Trainer 何时打开它 | [`trainer.py 第 1507 行`](https://github.com/huggingface/transformers/blob/v5.21/src/transformers/trainer.py#L1507) | `TrainingArguments(gradient_checkpointing=True)` 时，训练开始前调用上面那个方法 |

想在本机看源码，可以先 `pip install transformers`，再用 `python -m inspect transformers.models.llama.modeling_llama:LlamaMLP` 这样的命令打印出任意一个类。

<!-- real-model:end -->

## 本章结论：TinyLLM 的选择 {#tinyllm-choice}

TinyLLM 的主线保持基础的 Pre-RMSNorm 配置和第 10 章的残差输出缩放，不加 QK Norm、z-loss，也不用 μP；训练时记录注意力分数的最大值和输出 logits 的 log-sum-exp。模型放大时，**先加 QK Norm**，拓宽能用的学习率范围；需要在多个宽度之间迁移学习率时，**整套采用 μP**（隐藏层学习率、输出乘子、词嵌入三条一起改），在小宽度上扫好学习率再搬到大宽度；输出 logits 出现漂移、或改用低精度时，再加 z-loss。显存不够时，按“激活重计算 → ZeRO-1/2 → FSDP → 张量并行”的顺序考虑，每一步都先验证结果和单卡一致。

理由来自本章的实验（代理模型、单个种子）：峰值学习率从 3e-3 扫到 3e-1，原样时注意力分数从 36 涨到 22 万，QK Norm 把它压在 217 以内，5 个学习率上的平均验证损失从 5.304 降到 5.034，而主线学习率上两者差别在噪声以内；z-loss 在这里没有作用，因为输出 logits 没有漂移。标准参数化下最佳学习率随宽度从 3e-2 移到 3e-3，μP 下宽度 32 到 128 都是 1e-2，而且越宽越好。激活重计算省下九成多的激活、梯度逐位相同，每步慢约三成；数据并行和张量并行的模拟结果与单卡一致。

这些选择在什么情况下要换：宽度、深度都放大很多倍时，μP 之外还要考虑深度方向的缩放；张量并行只在同一台机器内的高速互连上划算；不同的硬件和规模下，最合适的并行组合要实测吞吐来定。

::: warning 常见误区
- **小模型上看不到的问题，只能在大模型上研究。** 很多不稳定在小模型上用大学习率就能复现，对策也一样有效。
- **QK Norm 能让模型更好。** 在主线学习率上它没有收益，作用是拓宽能用的学习率范围；它也会改变注意力的行为，加了要重新评估。
- **z-loss 是通用的稳定剂。** 它只管输出 logits 的大小；本章的不稳定出在注意力分数上，z-loss 毫无作用。
- **μP 就是把学习率除以宽度。** μP 是一整套参数化：隐藏层学习率、输出乘子、词嵌入的初始化和学习率要一起改；只改其中一条，学习率仍然迁移不过去。
- **激活重计算会改变结果。** 它只是把前向再算一遍，梯度逐位相同；代价只是时间。
- **数据并行和梯度累积不一样。** 两者在数学上是同一件事（每份 token 数相同时），区别只是在一张卡上依次算，还是多张卡同时算再通信。
:::

## 检查理解

1. 第 2 节里，学习率变大时，原样设置的注意力分数为什么会暴涨？QK Norm 为什么能压住它，却在主线学习率上没有带来收益？

   <details><summary>参考答案</summary>

   注意力分数是 $q\cdot k/\sqrt{d}$，而 $q$、$k$ 是隐藏状态乘以权重得到的；学习率大时，权重更新的步子大，$q$、$k$ 的长度越长越大，点积随之暴涨（本章从 36 涨到 22 万），softmax 饱和，模型学不到东西。QK Norm 在点积之前把每个头的 $q$、$k$ 用 RMSNorm 拉回固定的尺度，点积就不会无限制地增长。主线学习率下，注意力分数本来就不大（最大 36），没有失控，所以 QK Norm 没什么可修的，差别在噪声以内。它的价值是拓宽能用的学习率范围。

   </details>

2. 标准参数化下，为什么模型越宽，最佳学习率越小？μP 是怎样让它不随宽度变的？

   <details><summary>参考答案</summary>

   一个隐藏层矩阵的输出，是输入的 $d$ 个分量各自乘以权重再相加。Adam 每一步对每个权重的改动大小约等于学习率，和宽度无关；这 $d$ 个改动方向相关（都朝降低损失的方向），加起来对输出的影响约与 $d$ 成正比。所以宽度越大，同样的学习率让输出变化越大，就得用更小的学习率抵消。μP 把隐藏层矩阵的学习率乘 $\text{基准宽度}/\text{宽度}$，正好抵消这个增长；输出层的 logits 也乘同样的因子；词嵌入的输入只有一个“1”（查表），不存在这个问题，所以保持不变。这样，每一步对输出的影响不随宽度变，最佳学习率也就不随宽度变。

   </details>

3. 70 亿参数、混合精度、8 张卡。用 ZeRO-1 时每张卡要放多少训练状态？为什么只切优化器状态就能省这么多？

   <details><summary>参考答案</summary>

   每个参数 16 字节：参数 2、梯度 2、优化器状态 12（FP32 主权重 4、$m$ 4、$v$ 4）。ZeRO-1 只把优化器状态切成 8 份：$7\times10^9 \times (2 + 2 + 12/8) = 38.5$ GB。优化器状态占了 16 字节里的 12 字节，是最大的一块，所以只切它就从 112 GB 降到了 38.5 GB。

   </details>

4. 激活重计算和梯度累积都能“省显存”，它们省的是同一块显存吗？各自的代价是什么？

   <details><summary>参考答案</summary>

   两者省的都是激活，但方式不同。梯度累积把一个大 batch 拆成几个小的依次算，每次前向的激活变少，代价是要多跑几次（总计算量不变，但每次的矩阵更小，硬件利用率可能变低）。激活重计算不改 batch 大小，而是前向时只存每个 Block 的输入，反向时重算 Block 内部，代价是多一次前向（本章约慢 30%）。两者可以一起用。权重、梯度、优化器状态这些训练状态，它们都省不了，那要靠 ZeRO/FSDP。

   </details>

## 参考资料

- [Small-scale proxies for large-scale Transformer training instabilities，Wortsman 等，2023](https://arxiv.org/abs/2309.14322)（在小模型上用大学习率复现注意力分数增长、输出 logits 发散）
- [Scaling Vision Transformers to 22 Billion Parameters，Dehghani 等，2023](https://arxiv.org/abs/2302.05442)（用 QK Norm 解决注意力分数发散）
- [2 OLMo 2 Furious，OLMo 团队，2024](https://arxiv.org/abs/2501.00656)（QK Norm、z-loss 等一整套稳定性配方）
- [PaLM: Scaling Language Modeling with Pathways，Chowdhery 等，2022](https://arxiv.org/abs/2204.02311)（z-loss 与损失尖峰）
- [DeepNet: Scaling Transformers to 1,000 Layers，Wang 等，2022](https://arxiv.org/abs/2203.00555)
- [Tensor Programs V: Tuning Large Neural Networks via Zero-Shot Hyperparameter Transfer，Yang 等，2022](https://arxiv.org/abs/2203.03466)（μP）
- [MiniCPM: Unveiling the Potential of Small Language Models with Scalable Training Strategies，Hu 等，2024](https://arxiv.org/abs/2404.06395)（用 μP 在小模型上确定超参数）
- [ZeRO: Memory Optimizations Toward Training Trillion Parameter Models，Rajbhandari 等，2020](https://arxiv.org/abs/1910.02054)
- [PyTorch FSDP: Experiences on Scaling Fully Sharded Data Parallel，Zhao 等，2023](https://arxiv.org/abs/2304.11277)
- [Megatron-LM: Training Multi-Billion Parameter Language Models Using Model Parallelism，Shoeybi 等，2019](https://arxiv.org/abs/1909.08053)（张量并行）
- [Training Deep Nets with Sublinear Memory Cost，Chen 等，2016](https://arxiv.org/abs/1604.06174)（激活重计算）
- [PyTorch：`torch.utils.checkpoint`](https://docs.pytorch.org/docs/stable/checkpoint.html) 与 [Distributed Checkpoint](https://docs.pytorch.org/docs/stable/distributed.checkpoint.html)

模型越大越难训，可有没有办法让参数变多、每个 token 的计算量却不变？[第 26 章：稀疏专家（MoE）](./mixture-of-experts.md)。
