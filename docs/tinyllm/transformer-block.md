---
title: "第 8 章：Transformer Block"
description: "把注意力和前馈层装成一个 Block 再叠起来：直接堆叠为什么越深越训不动，Pre-Norm 残差 Block 长什么样、有多少参数，以及残差流里每一层在做什么。"
pageClass: tinyllm-course
---

# 第 8 章：Transformer Block

[课程总览](./index.md) · [上一章](./activations-and-ffn.md) · [下一章](./initialization-and-residuals.md)

::: tip 本章学习目标
能写出 Pre-Norm 残差 Block 的前向计算，并说出注意力和前馈层在 Block 里各管什么；能解释 Block 为什么能一层层叠起来（形状不变）；能用一个控制了数据和随机种子的实验说明“直接堆叠”为什么越深越训不动，并分清它说明了什么、没说明什么；能估算一个 Block 的参数量（约 $12d^2$）；能读懂“残差流”：每一层都只是往同一个向量上加东西。

**前置：** [第 5 章](./self-attention.md)的多头注意力、[第 6 章](./position-encoding.md)的 RoPE、[第 7 章](./activations-and-ffn.md)的 SwiGLU。

**实践方式：** [transformer-block.ipynb](/tinyllm/notebooks/transformer-block)（也可以直接运行 <a href="/tinyllm/code/transformer-block.py" download>transformer-block.py</a>），CPU 约两分钟。
:::

<TinyLLMMap active="transformer-block" />

## 问题：零件都有了，怎么装在一起？

前面三章各做好了一个零件。[第 5 章](./self-attention.md)的注意力让每个字去前面的字里取回信息，[第 6 章](./position-encoding.md)的 RoPE 让它分得清先后，[第 7 章](./activations-and-ffn.md)的前馈层再对每个位置单独加工一遍。一个负责 token 之间交流，一个负责各自消化，正好互补。

把它们组合成一个单元，就是 **Transformer Block**。大模型就是把同一种 Block 叠几十上百层。本章先用最直接的办法装一次，叠起来训练，看看会出什么问题；再换成 TinyLLM 实际使用的写法。

::: info 本章代码从哪里来
本章所有代码都在一个文件里：<a href="/tinyllm/code/transformer-block.py" download>transformer-block.py</a>（[在 GitHub 上查看](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/tinyllm/code/transformer-block.py)）。下面的代码块都是从这个文件里直接截取的片段，所以单独复制一段可能缺少 `import` 或前面定义的变量；想自己运行，请下载完整文件，`python transformer-block.py` 从头跑到尾即可。notebook 版本也由同一个文件生成，可以[在线查看](/tinyllm/notebooks/transformer-block)，或[在 Colab 中直接运行](https://colab.research.google.com/github/lewislau86/lewislau86.github.io/blob/master/docs/public/tinyllm/notebooks/transformer-block.ipynb)。
:::

## 1. 三个零件

先把前三章的代码原样搬过来：带 RoPE 的多头因果注意力，和 SwiGLU 前馈层。

<<< @/public/tinyllm/code/transformer-block.py#parts

## 2. 最直接的装法：先注意力，再前馈层

先交流、再消化，最自然的写法就是把两个子层串起来：

<<< @/public/tinyllm/code/transformer-block.py#naive-block

Block 能一层层往上叠，靠的是一个简单的事实：**进去什么形状，出来还是什么形状**。注意力和前馈层都不改变 `[batch, 序列长度, d]`，所以上一个 Block 的输出可以直接当下一个 Block 的输入：

<<< @/public/tinyllm/code/transformer-block.py#shape-check

```text
进入 Block: (2, 24, 64)  出来: (2, 24, 64)
叠 3 个 Block 之后: (2, 24, 64)
```

## 3. 叠起来训练：越深越糟

用[第 1 章](./first-run.md)的唐诗，搭一个最简单的模型：词嵌入 → N 个 Block → 最后的 RMSNorm → 输出层。位置信息由每层注意力里的 RoPE 提供，输出层和词嵌入共用一张表（[第 4 章](./embeddings-and-output.md)）。

<<< @/public/tinyllm/code/transformer-block.py#model

::: info 这个实验比的是什么
这是一个<strong>结构对照</strong>：只换 Block 的写法和层数，其余全部相同。所有线性层都用 PyTorch 的默认初始化，还没有用第 9 章的初始化配方（Xavier 加残差输出投影缩放），所以图里的数字不是最终 TinyLLM 配方的训练效果。它只回答一个问题：同样的起点，两种装法叠深以后还能不能训练。
:::

为了让比较公平，先把数据准备好：前 35 首诗训练，最后 4 首只用来验证（和第 1 章一样）；再用一个单独的随机数发生器，**预先抽好 150 步要用的 batch**，所有模型第几步就用第几个 batch。这样不同结构初始化时消耗的随机数不一样，也不会让它们看到不同的数据。

<<< @/public/tinyllm/code/transformer-block.py#batches

然后把 Block 叠 1、2、4、8 层，每种设置用 3 个随机种子（种子只决定初始参数）各训练 150 步，报告训练损失、在 4 首没见过的诗上的验证损失，以及第一步时第 1 个 Block 收到的梯度。固定种子只是控制随机性的一个环节，同一份代码换一台机器或换一个 PyTorch 版本，个别数字仍可能不同（[PyTorch 可复现性说明](https://docs.pytorch.org/docs/2.14/notes/randomness.html)），所以这里看的是 3 个种子的平均和范围。下面的循环同时训练了下一节要讲的 Pre-Norm 版本，这里先看“直接堆叠”的四行：

<<< @/public/tinyllm/code/transformer-block.py#depth

```text
直接堆叠       1 层：训练 3.54（3.53～3.54）  验证 6.76（6.56～6.89）  第 1 个 Block 的梯度 9e-02
直接堆叠       2 层：训练 5.22（5.10～5.44）  验证 6.65（6.53～6.88）  第 1 个 Block 的梯度 2e-07
直接堆叠       4 层：训练 6.32（6.32～6.32）  验证 6.32（6.32～6.32）  第 1 个 Block 的梯度 0e+00
直接堆叠       8 层：训练 6.32（6.32～6.32）  验证 6.32（6.32～6.32）  第 1 个 Block 的梯度 0e+00
完全乱猜的损失 ln(556) = 6.321
```

按理说层数越多，模型越强。结果正好相反：1 层还能学到一些东西，2 层就差了很多，4 层和 8 层的训练损失停在 6.32，和对 556 个字完全乱猜一模一样，3 个种子都是如此。第 1 个 Block 的梯度在 2 层时只剩约 $2\times10^{-7}$，4 层以上干脆是 0：训练信号根本传不回去。

再看训练开始前，同一批输入穿过 8 个 Block 时，每个 token 向量的大小怎样变化：

<<< @/public/tinyllm/code/transformer-block.py#signal

```text
直接堆叠       1e-01 4e-05 8e-11 4e-22 0e+00 0e+00 0e+00 0e+00 0e+00 （种子 0）
Pre-Norm 残差 1e-01 2e-01 3e-01 4e-01 5e-01 6e-01 7e-01 8e-01 8e-01 （种子 0）
```

直接堆叠时，信号每过一个 Block 至少缩小上千倍，而且越缩越快，第 4 层之后小到浮点数表示不了，变成了 0（另外两个种子几乎一样）。后面的层收到的全是 0，算出来的东西和输入无关；反向传播时梯度也要沿同一条路一层层缩回去，传到第 1 层就没了。这就是[第 1 章](./first-run.md)总图里那句话的意思：<strong>把 Block 叠深，它会训不动。</strong>

![三个随机种子、同一组 batch、各训练 150 步。左：直接堆叠 1、2 层训练损失 3.54、5.22，4 层和 8 层停在完全乱猜的 6.32；Pre-Norm 残差从 1.25 降到 0.57；所有模型在 4 首没训练过的诗上的验证损失都在 6.3 到 7.1 之间，不低于乱猜。中：第一步时第 1 个 Block 的梯度，直接堆叠 2 层只剩约 2e-7，4 层以上为 0；Pre-Norm 在 0.6 到 0.8 之间。右：训练前信号穿过 8 个 Block，直接堆叠每层至少缩小上千倍，第 4 层后下溢为 0；Pre-Norm 从 0.1 缓慢增长到 0.8](/tinyllm/figures/block-depth.svg)

## 4. 加两个零件：残差和 Pre-Norm

修好它只需要改 `forward` 里的两行，加两样东西：

- **残差**：子层的结果不再替换 `x`，而是**加回** `x`：`x = x + 子层(...)`。
- **Pre-Norm**：子层不直接处理 `x`，而是先用 RMSNorm 把它调成统一的大小，再交给子层。

<<< @/public/tinyllm/code/transformer-block.py#block

![左：直接堆叠，x 先过注意力再过 SwiGLU，输出整个替换 x。右：Pre-Norm 残差 Block，x 沿残差流一路向下，两次分出副本经 RMSNorm 进入注意力或 SwiGLU，结果加回残差流；d=64 时注意力 16,384 个参数，SwiGLU 32,640 个，两个 RMSNorm 128 个](/tinyllm/figures/block-anatomy.svg)

同一个实验里，Pre-Norm 残差 Block 的结果是：

```text
Pre-Norm 残差 1 层：训练 1.25（1.23～1.26）  验证 6.87（6.81～6.91）  第 1 个 Block 的梯度 6e-01
Pre-Norm 残差 2 层：训练 0.79（0.78～0.82）  验证 6.96（6.78～7.16）  第 1 个 Block 的梯度 7e-01
Pre-Norm 残差 4 层：训练 0.66（0.64～0.68）  验证 7.09（6.96～7.25）  第 1 个 Block 的梯度 8e-01
Pre-Norm 残差 8 层：训练 0.57（0.56～0.58）  验证 6.90（6.79～6.98）  第 1 个 Block 的梯度 7e-01
```

这次层数越多，训练损失越低，3 个种子的范围都很窄；第 1 个 Block 的梯度不管叠多少层都在 0.6 到 0.8 之间。上面那张图里，信号也从 0.1 平稳地涨到 0.8，不再一路缩到 0。

再看验证损失这一列。所有训练过的模型在 4 首没见过的诗上都在 6.6 到 7.1 之间，比乱猜的 6.32 还差；反倒是那两个什么都没学到的直接堆叠模型正好等于 6.32。这和[第 1 章](./first-run.md)的结论一样：一千多字的语料只够模型把训练集背下来，背得越熟，对没见过的诗越自信地猜错。所以这个实验能说明的是<strong>两种装法能不能训练</strong>，不能说明哪个模型写诗写得更好。要回答后一个问题，需要更多的数据和正式的评估，见[第 12 章](./data-pipeline.md)和[第 20 章](./training-evaluation.md)。

先给一个直觉，细节留给后面两章：

- **残差留了一条直通路径。** `x` 沿着图右边那条竖线一路往下，每个子层只是往上“加一点”。就算某个子层的输出很小，`x` 本身也原样传了下去；反向传播时，梯度同样可以沿这条线直接回到第 1 层。为什么是“加”、初始化时子层该加多大，是[第 9 章](./initialization-and-residuals.md)的内容。
- **Pre-Norm 让每个子层看到的输入大小固定。** 不管残差流涨到多大，子层读到的总是一份调成统一大小的副本。归一化具体怎么算、为什么放在子层前面，是[第 10 章](./normalization.md)的内容。

直接堆叠会不会换一种初始化就好起来？信号缩小的速度确实和初始参数的大小有关，第 9 章会用同样的测量方法回答这个问题。

## 5. 一个 Block 有多少参数

<<< @/public/tinyllm/code/transformer-block.py#params

```text
注意力        16,384
SwiGLU     32,640
两个 RMSNorm    128
一个 Block 合计 49,152，约等于 12·d² = 49,152
```

注意力有 Q、K、V 和输出投影四个 $d\times d$ 矩阵，共 $4d^2$；SwiGLU 有三个 $d\times\frac{8d}{3}$ 矩阵，约 $8d^2$；两个 RMSNorm 各 $d$ 个缩放系数，可以忽略。所以**一个 Block 约 $12d^2$ 个参数**，其中三分之二在前馈层。

用它核对[第 1 章](./first-run.md)的模型：$d=96$ 时每个 Block 约 $12\times96^2=110{,}592$ 个参数（加上两个 RMSNorm 是 110,784），3 个 Block 约 33 万；再加上词嵌入 $556\times96$、位置表 $24\times96$ 和最后一个 RMSNorm，正好是第 1 章打印的 388,128。大模型的参数量也主要由这个式子决定：层数 × $12d^2$。

## 6. 残差流：每一层都往同一条“流”上加东西

Pre-Norm 残差 Block 有一个很好用的性质：它从不覆盖 `x`，只往上加。可以把 `x` 想成一条从嵌入流到输出层的“流”（**残差流**），每个子层从流里读一份副本，算完把结果加回去。

既然最后交给输出层的就是这条流，那在任何一站之后，都可以直接用最后的 RMSNorm 和输出层“读”一下当时的 `x`，看模型此刻会猜哪个字。下面单独训练一个 4 层的 Pre-Norm 模型（把同一组 batch 用两遍，共 300 步），读一下“举头望明月，低头思故”的最后一个位置：

<<< @/public/tinyllm/code/transformer-block.py#lens

```text
嵌入         故100% 海0% 雨0%
第 1 层 注意力  故98% 圆0% 辛0%
第 1 层 前馈   乡13% 开3% 眠3%
第 2 层 注意力  乡26% 故3% 阳2%
第 2 层 前馈   乡64% 三2% 晓1%
第 3 层 注意力  乡68% 三2% 晓1%
第 3 层 前馈   乡81% 三1% 人1%
第 4 层 注意力  乡85% 不1% 三1%
第 4 层 前馈   乡97% 人0% 归0%
```

点“播放”一站一站地看。左边是 9 个站点和每一站读出正确答案的概率，右边是这一站读出的前 5 名；经过注意力的站点，下方还画出最后一个字在 4 个头里分别看向哪些字。上方可以换另外两句诗：

<ResidualStreamLens />

几个值得注意的地方：

- **嵌入这一站，模型猜的是“故”自己。** 输入和输出共用一张表，“故”的向量和表里最像的就是“故”这一行。这时还没有任何上下文。
- **答案是一点点加出来的。** “乡”的概率从 13% 到 64%，再到 81%、97%，每一站都在前一站的基础上修正，没有哪一层单独“想出”了答案。
- **在这几个例子里，跳得最大的往往是前馈层之后。** 注意力先把前文的信息取到当前位置，前馈层再把它加工成对下一个字的判断。这和第 7 章说的分工一致，但只是这个小模型上的观察，不是普遍规律。
- **不是每句都这么有把握。** “床前明月光，疑是地上”最后读出“霜”的概率只有 63%，前几站一直在猜“上”，到第 3 层才轮到“霜”。

这种“在中间读一下”的方法叫 logit lens。它只是用最后的输出层去近似解读中间状态，中间各层并不是为了被这样读而训练的，所以读数只能当作参考。

## 本章结论：TinyLLM 的选择 {#tinyllm-choice}

TinyLLM 的 Block 采用 **Pre-Norm 残差结构**：`x = x + Attention(RMSNorm(x))`，再 `x = x + SwiGLU(RMSNorm(x))`。注意力带 RoPE，前馈层是无偏置的 SwiGLU，中间宽度约 $8d/3$。整个模型就是：词嵌入 → N 个这样的 Block → 最后一个 RMSNorm → 与嵌入共享权重的输出层。它让层数可以放心往上加，每个 Block 约 $12d^2$ 个参数。初始化细节见[第 9 章](./initialization-and-residuals.md)，归一化的选择见[第 10 章](./normalization.md)，完整模型在[第 11 章](./tinyllm-model.md)组装。[Pre-LN 梯度分析](https://arxiv.org/abs/2002.04745)

::: warning 常见误区
- **残差不是可有可无的优化技巧。** 本章的实验里（PyTorch 默认初始化），去掉残差和归一化，4 层以上的模型完全学不到东西。
- **训练损失更低不等于模型更好。** Pre-Norm 版本层数越多训练损失越低，但验证损失全都比乱猜还差：几十首诗只够背诵。比较模型要看没见过的数据（[第 20 章](./training-evaluation.md)）。
- **“先注意力、再前馈层”不是唯一的顺序。** 也有模型让两个子层并行读同一个 `x`、把结果一起加回去（例如 GPT-J、PaLM），可以少一次同步、加快训练。TinyLLM 先用最常见的串行写法。
- **中间层读出来的预测不是模型“真正的想法”。** logit lens 只是借用输出层去近似解读中间状态，适合观察趋势，不能当作精确解释。
:::

## 检查理解

1. 为什么 Block 能一层层叠起来？如果某个 Block 把形状从 `[B, T, 64]` 变成 `[B, T, 128]`，会出什么问题？

   <details><summary>参考答案</summary>

   注意力和前馈层都不改变 `[batch, 序列长度, d]`，上一个 Block 的输出可以直接当下一个 Block 的输入。形状变了，下一层的线性层和这一层的残差加法就对不上，需要额外的投影；所以同一个模型里的 Block 都保持同一个 $d$。

   </details>

2. 直接堆叠 4 层时，损失停在 6.321。这个数是怎么来的？说明了什么？

   <details><summary>参考答案</summary>

   它等于 $\ln 556$，也就是对 556 个字平均分配概率时的交叉熵。信号在前几层就缩成了 0，最后输出的 logits 和输入无关，模型只能给每个字相同的概率；梯度也传不回去，所以一直停在这里。

   </details>

3. 写出 Pre-Norm 残差 Block 的两行前向计算。和直接堆叠相比，哪里不同？

   <details><summary>参考答案</summary>

   `x = x + attn(norm1(x))`，`x = x + ffn(norm2(x))`。不同有两处：子层的结果加回 `x` 而不是替换它（残差）；子层读的是归一化后的副本（Pre-Norm）。

   </details>

4. $d=512$ 时，一个 Block 大约有多少参数？其中前馈层占多少？

   <details><summary>参考答案</summary>

   约 $12\times512^2\approx315$ 万。注意力约 $4d^2\approx105$ 万，SwiGLU 约 $8d^2\approx210$ 万，前馈层占三分之二。

   </details>

5. 残差流的读数里，嵌入这一站为什么几乎 100% 猜“故”自己？

   <details><summary>参考答案</summary>

   输出层和词嵌入共用一张表，logits 是当前向量和表中每一行的点积。刚查完表时，当前向量就是“故”那一行，和它最像的当然是“故”自己。之后每一站往上加的东西，才把它推向“乡”。

   </details>

## 参考资料

- [Attention Is All You Need，Vaswani 等，2017](https://arxiv.org/abs/1706.03762)
- [On Layer Normalization in the Transformer Architecture，Xiong 等，2020](https://arxiv.org/abs/2002.04745)（Pre-Norm 与 Post-Norm 的梯度分析）
- [A Mathematical Framework for Transformer Circuits，Elhage 等，2021](https://transformer-circuits.pub/2021/framework/index.html)（残差流的视角）
- [interpreting GPT: the logit lens，nostalgebraist，2020](https://www.lesswrong.com/posts/AcKRB8wDpdaN6v6ru/interpreting-gpt-the-logit-lens)
- [PaLM，Chowdhery 等，2022](https://arxiv.org/abs/2204.02311)（并行的注意力与前馈层）

Block 能叠起来了，可为什么加上残差和 Pre-Norm 就好了？参数一开始该取多大？下一章从参数的起点讲起：[第 9 章：初始化与残差路径](./initialization-and-residuals.md)。
