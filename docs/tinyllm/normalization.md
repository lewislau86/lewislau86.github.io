---
title: "第 10 章：归一化"
description: "每个 token 的向量为什么要先“量一量尺寸”再送进子层；LayerNorm、RMSNorm、ScaleNorm 怎样算，放在 Block 的哪里。"
pageClass: tinyllm-course
---

# 第 10 章：归一化

[课程总览](./index.md) · [上一章](./initialization-and-residuals.md) · [下一章](./tinyllm-model.md)

::: tip 本章学习目标
对形状为 `[batch, seq, d]` 的隐藏状态，说清楚归一化沿哪一维计算；能手算 LayerNorm、RMSNorm 的输出；能画出 Pre-Norm 与 Post-Norm 的数据流，并解释 TinyLLM 为什么选 Pre-Norm + RMSNorm。

**前置：** [第 2 章](./tensors-and-autograd.md)的张量形状，[第 9 章](./initialization-and-residuals.md)的残差连接。

**实践方式：** [normalization.ipynb](/tinyllm/notebooks/normalization)（也可以直接运行 <a href="/tinyllm/code/normalization.py" download>normalization.py</a>），CPU 即可，不需要训练模型。
:::

<TinyLLMMap active="normalization" />

## 问题：信号越往深处走，尺寸越难控制

[第 9 章](./initialization-and-residuals.md)把 Block 写成“旧状态 + 子层更新”。每经过一层，残差流就多加一份更新。下面的实验把 32 个随机初始化的子层叠起来，记录每一层**子层实际收到的输入**有多大（用均方根 RMS 衡量）：

![32 层随机残差网络中各层子层输入的 RMS：不做归一化时随层数指数增长到约 100；Pre-Norm 时子层输入始终约为 1，残差流本身缓慢增长](/tinyllm/figures/norm-motivation.svg)

红线没有归一化：到第 32 层，子层收到的数值已经比第 1 层大一百多倍。子层里的线性层、softmax 都是按“输入大约是这个尺寸”设计和初始化的，输入尺寸一直漂移，训练就很难稳定。绿线在每个子层前加了一步归一化：不管残差流（灰色虚线）长到多大，子层看到的输入 RMS 始终约为 1。

这就是本章要讲的工具。它做的事情很朴素：**在把一个 token 的向量交给子层之前，先把它的尺寸调回统一的标准。**

## 1. 先看一个向量：归一化沿哪一维做

::: info 本章代码从哪里来
本章所有代码都在一个文件里：<a href="/tinyllm/code/normalization.py" download>normalization.py</a>（[在 GitHub 上查看](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/tinyllm/code/normalization.py)）。下面的代码块都是从这个文件里直接截取的片段，所以单独复制一段可能缺少 `import` 或前面定义的变量；想自己运行，请下载完整文件，`python normalization.py` 从头跑到尾即可。notebook 版本也由同一个文件生成，可以[在线查看](/tinyllm/notebooks/normalization)，或[在 Colab 中直接运行](https://colab.research.google.com/github/lewislau86/lewislau86.github.io/blob/master/docs/public/tinyllm/notebooks/normalization.ipynb)。
:::

隐藏状态的形状是 `[batch, seq, d]`。归一化**对每个 token 单独处理**，只在最后一维的 $d$ 个数之间算统计量，不跨 token、也不跨样本：

<<< @/public/tinyllm/code/normalization.py#token-axis

所以下面所有公式都只针对**一个**向量 $x=(x_1,\ldots,x_d)$。我们用 $x=[1,2,3]$ 手算，$d=3$；为了算得干净，暂时令防止除零的 $\epsilon=0$、可学习参数取初值。

## 2. LayerNorm：先居中，再缩放

LayerNorm 先求这个向量的均值 $\mu$ 和方差 $\sigma^2$，把均值挪到 0，再把方差缩放到 1：

$$
\mu=\frac{1}{d}\sum_{i=1}^{d}x_i,\qquad
\sigma^2=\frac{1}{d}\sum_{i=1}^{d}(x_i-\mu)^2,\qquad
y_i=\gamma_i\,\frac{x_i-\mu}{\sqrt{\sigma^2+\epsilon}}+\beta_i
$$

手算 $x=[1,2,3]$：均值 $\mu=2$，方差 $\sigma^2=(1+0+1)/3=2/3$，于是

$$
y=\frac{[1,2,3]-2}{\sqrt{2/3}}\approx[-1.225,\ 0,\ 1.225].
$$

$\gamma_i$、$\beta_i$ 是每一维各一个的可学习缩放和平移，初值分别为 1 和 0。它们让模型在需要时把“标准尺寸”再调回别的值，所以归一化并不剥夺表达能力。

<<< @/public/tinyllm/code/normalization.py#layernorm

## 3. RMSNorm：只管长度，不管均值

RMSNorm 省掉“减均值”这一步，直接用均方根（root mean square）当尺子：

$$
\mathrm{RMS}(x)=\sqrt{\frac{1}{d}\sum_{i=1}^{d}x_i^2+\epsilon},\qquad
y_i=\gamma_i\,\frac{x_i}{\mathrm{RMS}(x)}
$$

手算 $x=[1,2,3]$：$\mathrm{RMS}=\sqrt{(1+4+9)/3}=\sqrt{14/3}\approx2.160$，于是 $y\approx[0.463,\ 0.926,\ 1.389]$。和 LayerNorm 不同，输出的均值不是 0，只是均方根变成了 1。标准形式只有 $\gamma$，没有平移项 $\beta$。

几何上看，RMSNorm 把每个向量沿原方向拉长或压短，让它们都落在同一个“球面”上。二维时就是一个圆：

![二维平面上散落的向量沿各自方向被拉伸或压缩，全部落到半径为根号 2 的圆上](/tinyllm/figures/norm-geometry.svg)

<<< @/public/tinyllm/code/normalization.py#rmsnorm

`nn.RMSNorm` 的 `eps` 默认是 `None`，会按内部计算类型自动选取；这里显式写 `1e-5`，方便和其他实现对照。参见 [PyTorch RMSNorm 文档](https://docs.pytorch.org/docs/stable/generated/torch.nn.RMSNorm.html)。

### 少了“减均值”，差别在哪里？

给向量的每一维都加同一个常数，就能看出两者的区别：

![输入 [1,2,3,4] 与整体加 10 后的 [11,12,13,14]：LayerNorm 两组输出完全重合；RMSNorm 与 ScaleNorm 两组输出不同，平移后各分量差别被压小](/tinyllm/figures/norm-three-ways.svg)

LayerNorm 先减均值，整体平移被完全抵消，两组柱子重合。RMSNorm 不减均值，加了 10 之后整个向量主要由“10 左右”这个共同部分组成，归一化后各分量的差别被压小了。

两种做法各有道理：LayerNorm 对整体平移不敏感；RMSNorm 少算一套均值，公式更简单，保留了均值信息，由后续的线性层自己决定怎么用。[RMSNorm 论文](https://arxiv.org/abs/1910.07467)在其实验中发现，去掉居中对效果影响不大，同时在其测试实现上快了约 7%–64%。实际速度取决于内核与硬件，两者都可以高度并行；RMSNorm 的优势在于少一组归约和依赖，而不是“LayerNorm 不能并行”。

## 4. ScaleNorm：用一个标量控制长度

ScaleNorm 是第三种思路，常作对照实验。它用向量的 L2 长度归一化，再乘**一个**可学习标量 $g$（而不是每维一个 $\gamma_i$）：

$$
y=g\,\frac{x}{\|x\|_2+\epsilon}
$$

手算 $x=[1,2,3]$：$\|x\|_2=\sqrt{14}\approx3.742$，$g=1$ 时 $y\approx[0.267,\ 0.535,\ 0.802]$。它和 RMSNorm 只差一个常数倍 $\sqrt d$，区别主要在于可学习参数的个数。PyTorch 没有内置模块，自己写几行即可：

<<< @/public/tinyllm/code/normalization.py#scalenorm

ScaleNorm 出自 [Transformers without Tears](https://arxiv.org/abs/1910.05895) 的机器翻译实验；论文还同时改了其他设计，不能把效果全归到这一层。

### 三种方法放在一起

| 方法 | 做什么 | 每层可学习参数 | 对整体平移 | 代表模型 |
| --- | --- | --- | --- | --- |
| LayerNorm | 减均值，除以标准差 | $\gamma,\beta$ 各 $d$ 个 | 不敏感 | 原始 Transformer、BERT、GPT-2/3 |
| RMSNorm | 除以均方根 | $\gamma$ 共 $d$ 个 | 敏感 | LLaMA、Gemma 2、Qwen3 |
| ScaleNorm | 除以 L2 长度 | $g$ 共 1 个 | 敏感 | 研究架构 |

手算答案汇总：对 $[1,2,3]$，三者分别得到 $[-1.225,0,1.225]$、$[0.463,0.926,1.389]$、$[0.267,0.535,0.802]$。打开 notebook 第一节，用代码核对这三行数字。

## 5. 放在哪里：Pre-Norm 与 Post-Norm

上面讲的是**怎么算**。同样重要的是**放在哪里算**。一个子层 $F$（注意力或前馈层）配一次残差和一次归一化，有两种经典摆法：

![左：Pre-Norm 先归一化再进入子层，残差直通路径不经过归一化；右：Post-Norm 先相加再归一化，直通路径也要经过归一化](/tinyllm/figures/pre-post-norm.svg)

$$
\text{Pre-Norm: } y=x+F(\operatorname{Norm}(x)),\qquad
\text{Post-Norm: } y=\operatorname{Norm}(x+F(x)).
$$

区别在左边那条直通路径。Pre-Norm 里，输入 $x$ 不经任何处理直接加到输出上，梯度也能沿它原样传回去；子层只负责往残差流上“加一笔更新”。Post-Norm 里，相加后的结果还要再过一次归一化，直通路径上多了一道关卡。[Xiong 等的分析](https://arxiv.org/abs/2002.04745)表明，Pre-Norm 在初始化附近的梯度更平稳，对 warmup 和学习率不那么敏感，这也是 GPT-2 之后多数 Decoder-only 模型采用它的原因。

Pre-Norm 有一个副作用：残差流本身从不被归一化，会随层数慢慢变大（开头那张图的灰色虚线）。所以在所有 Block 之后、输出层之前，还要**再加一次最终归一化**。总图里“最终 RMSNorm”就是它。

一个 Block 有注意力和前馈两个子层，所以有两次归一化、两次残差：

<<< @/public/tinyllm/code/normalization.py#block

还有一些摆法是这两种的变体。比如 Gemma 2 在子层前后都放 RMSNorm（常叫 Sandwich Norm），NormFormer 在注意力和前馈层内部再加几处归一化。它们改的都是**位置**，不是新的统计公式。

## 6. 归一化与低精度：一句话版本

归一化把数值拉回 1 附近，后续的矩阵乘法、平方就不容易在 FP16 里溢出。但它**不会增加浮点格式的精度**：在 BF16 里已经被舍入掉的小差异，归一化找不回来；归一化内部的平方和本身也需要足够的计算精度。完整的讨论和实验在[第 17 章《数值精度》](./precision.md#normalization-and-precision)。

## 7. 动手实验

打开 [normalization.ipynb](/tinyllm/notebooks/normalization)，从上到下运行。输入固定，不需要下载数据。

| 实验 | 输入 | 应该看到 |
| --- | --- | --- |
| LayerNorm | `[1,2,3,4]` 和加 10 后的 `[11,12,13,14]` | 两行输出相同，均值约 0 |
| RMSNorm | 同上 | 两行输出不同，均方根约 1，均值一般不为 0 |
| ScaleNorm | 同上，`g=1` | L2 长度约 1 |
| 全零向量 | `[0,0,0,0]` | 三种输出都是有限的零向量，`eps` 防止了除零 |
| 平移与缩放 | `x`、`x+c`、`a*x` | 正数缩放 $a$ 对三者都几乎没有影响；平移只有 LayerNorm 不受影响 |
| 教学版实现 | 自己写的 LayerNorm/RMSNorm | 输出和梯度与 `nn.LayerNorm`、`nn.RMSNorm` 一致 |

notebook 后半部分还有 QK Norm 和 DeepNorm 的单元格，分别对应[第 5 章](./self-attention.md#qk-norm)和[第 25 章](./large-model-stability.md#deepnorm)；有 Apple 芯片的读者可选运行最后的 MLX 对照。

## 8. 延伸：其他与归一化有关的方法

下面这些方法的名字里常带 “Norm”，但作用的层次不同。初学时知道它们“管哪一段”即可。

| 方法 | 管什么 | 和本章的关系 | 详见 |
| --- | --- | --- | --- |
| QK Norm | 注意力内部 Q、K 的尺度 | 可与 RMSNorm 同时使用（Qwen3、Gemma 3、OLMo 2） | [第 5 章](./self-attention.md#qk-norm) |
| DeepNorm | 极深网络的残差系数与初始化 | 是一整套结构方案，不是换一层 | [第 25 章](./large-model-stability.md#deepnorm) |
| pRMSNorm | 只用部分维度估计 RMS | RMSNorm 的近似变体 | [RMSNorm 论文](https://arxiv.org/abs/1910.07467) |
| NormFormer、Sandwich Norm | 增加归一化的位置 | 位置变体 | [NormFormer](https://arxiv.org/abs/2110.09456) |
| DyT | 用带参数的 tanh 代替归一化层 | 替代方案，不计算统计量 | [DyT 论文](https://arxiv.org/abs/2503.10622) |
| BatchNorm | 跨 batch 统计 | 依赖批次统计，不适合逐 token 自回归 | [PyTorch 归一化层](https://docs.pytorch.org/docs/stable/nn.html#normalization-layers) |

## 本章结论：TinyLLM 的选择 {#tinyllm-choice}

**每个注意力和前馈子层的输入处用 RMSNorm（Pre-Norm），所有 Block 之后、输出层之前再用一次 RMSNorm。**

理由：Pre-Norm 保留一条不经处理的残差直通路径，训练更平稳；RMSNorm 只控制尺度，公式简单，[LLaMA](https://arxiv.org/abs/2302.13971) 等公开模型采用同样的组合。

什么时候改：复现使用 LayerNorm 的模型（如 GPT-2）时，照原模型来；训练中注意力分数失控时，在注意力里加 QK Norm（第 5 章）；网络非常深时，再整套评估 DeepNorm（第 25 章）。加载预训练权重时，不能只因“RMSNorm 更常用”就替换原模型的归一化层。

::: warning 常见误区
- **`F.normalize` 一定要写 `dim=-1`。** 它默认 `dim=1`，对 `[batch, seq, d]` 会沿 seq 归一化，结果完全不对。
- **`torch.finfo(dtype).eps` 不是归一化层的 `eps`。** 前者是浮点格式在 1 附近的间隔，后者是加在分母里防止除零的小常数。
- **Pre-Norm、残差、RMSNorm 不是三选一。** 一个是位置，一个是结构，一个是公式，TinyLLM 三者同时使用。
:::

## 检查理解

1. 对 `[batch, seq, d]` 的张量做 RMSNorm，一共计算多少个 RMS？

   <details><summary>参考答案</summary>

   batch × seq 个，每个 token 一个。

   </details>

2. 不看代码，手算 $x=[2,2,2]$ 经过 LayerNorm 和 RMSNorm（$\epsilon=0$）的输出。

   <details><summary>参考答案</summary>

   LayerNorm：方差为 0，分母为 0，所以真实实现必须有正的 $\epsilon$，输出为 $[0,0,0]$。RMSNorm：RMS=2，输出 $[1,1,1]$。

   </details>

3. 为什么 Pre-Norm 结构在所有 Block 之后还要再加一次归一化？

   <details><summary>参考答案</summary>

   Pre-Norm 只归一化子层的输入，残差流本身一直没被归一化，会随层数变大；最终归一化把它调回标准尺寸再交给输出层。

   </details>

4. 有人把模型里的 `nn.LayerNorm` 全部替换成 `nn.RMSNorm`，然后加载原来的预训练权重。会有什么问题？

   <details><summary>参考答案</summary>

   RMSNorm 没有 bias，也不减均值；原权重是在 LayerNorm 的输出分布上训练出来的，替换后每层的输入分布都变了，模型效果通常会明显下降。

   </details>

## 参考资料

- [Layer Normalization，Ba 等，2016](https://arxiv.org/abs/1607.06450)
- [Root Mean Square Layer Normalization，Zhang 与 Sennrich，2019](https://arxiv.org/abs/1910.07467)
- [Transformers without Tears：ScaleNorm，Nguyen 与 Salazar，2019](https://arxiv.org/abs/1910.05895)
- [On Layer Normalization in the Transformer Architecture，Xiong 等，2020](https://arxiv.org/abs/2002.04745)
- [NormFormer，Shleifer 等，2021](https://arxiv.org/abs/2110.09456)
- [Transformers without Normalization：DyT，Zhu 等，2025](https://arxiv.org/abs/2503.10622)
- [LLaMA，Touvron 等，2023](https://arxiv.org/abs/2302.13971) · [Gemma 2，2024](https://arxiv.org/abs/2408.00118) · [Qwen3，2025](https://arxiv.org/abs/2505.09388)
- [PyTorch LayerNorm](https://docs.pytorch.org/docs/stable/generated/torch.nn.LayerNorm.html) · [RMSNorm](https://docs.pytorch.org/docs/stable/generated/torch.nn.RMSNorm.html) · [`F.normalize`](https://docs.pytorch.org/docs/stable/generated/torch.nn.functional.normalize.html)

到这里，让深层网络训得动的三件工具都齐了：残差、初始化、归一化。下一章把所有零件组装成完整的 TinyLLM：[第 11 章：完整 TinyLLM](./tinyllm-model.md)（规划中）；已完成的后续章节是[第 14 章：优化器](./optimizers.md)。
