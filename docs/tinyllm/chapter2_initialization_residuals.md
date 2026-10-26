# Chapter 2：初始化与残差路径

[Chapter 1](chapter1_pytorch_autograd.md) 已经把输入、参数、损失和梯度接成一条计算链。现在把一个线性层叠成几十层，会遇到两个新问题：<strong>参数起点决定信号最初有多大；信号和梯度要怎样经过许多层？</strong>本章先用方差估计初始化的尺度，再用残差连接和归一化的位置理解深层网络。配套的 <a href="/tinyllm/chapter2_Initialization_Residuals/ch2.ipynb" download>ch2.ipynb</a> 在 CPU 上运行，图表使用 Plotly。

## 学习目标与记号

读完后应能区分参数分布与模型结构，能根据权重形状找出 `fan_in`、`fan_out`，能写出 Pre-LN、Post-LN 的数据流，并能检查多层网络中激活与梯度是否异常。这里令 $x\in\mathbb R^d$ 表示一个 token 的隐藏向量，$F$ 表示注意力或前馈子层。对 `[batch, seq, hidden]` 张量，下面的线性变换逐 token 作用在最后一轴。归一化公式已在 [Chapter 0](chapter0_normalization.md) 介绍。

## 1. 为什么不能把所有权重设为相同的数

设一个线性层有 $n_{\mathrm{in}}$ 个输入，某个输出为 $y=\sum_{i=1}^{n_{\mathrm{in}}}w_i x_i$。若 $w_i$ 独立、零均值，且与输入独立，在输入方差大致相同的简化条件下，

$$
\operatorname{Var}(y)\approx n_{\mathrm{in}}\operatorname{Var}(w)\operatorname{Var}(x).
$$

若权重方差与输入宽度无关，宽度一变，输出方差就可能随之膨胀或缩小。这只是初始化时的粗略估计；训练后权重和输入未必独立，残差、归一化、注意力和非线性也会改变结果。它说明了为何需要按层的形状选择初始尺度。

把同一层所有权重都设为零，还有一个不同的问题：对称的隐藏单元收到相同梯度，难以学出不同特征。偏置设为零通常没这个问题，因为随机权重已经打破对称性；但把<strong>最后一层输出投影</strong>特意设为零，有时可让某个残差分支在起点接近恒等映射。这是针对结构的选择，不能推广成“所有权重设零”。

在 PyTorch 中，`nn.Linear(d_in, d_out).weight` 的形状是 `[d_out, d_in]`，所以 `fan_in=d_in`、`fan_out=d_out`。这与计算时输入乘权重转置相配。自己写 `x @ W` 且 `W` 为 `[d_in, d_out]` 时，不能直接把同一初始化函数套到 `W` 上而不检查它如何解释轴。

## 2. 正态、截断正态、Xavier 与 He 各管什么

以下都只描述<strong>抽样规则或初始尺度</strong>，不是训练算法。实验要在相同输入、相同宽度和重复随机种子下比较；一次抽样的样本标准差不会精确等于目标值。

| 方法 | 典型形式 | 先检查什么 |
| --- | --- | --- |
| 普通正态 | $w\sim\mathcal N(0,\sigma^2)$ | `std` 是否按层宽度与结构选取；固定的 `0.02` 不是通用答案 |
| 截断正态 | 从正态分布抽样，只保留区间 $[a,b]$ 内的值 | 截断后实测标准差通常小于原分布参数 `std`；不要把它误当成裁剪 `clamp` |
| Xavier/Glorot normal | $\operatorname{Var}(w)=2/(fan_{in}+fan_{out})$（`gain=1`） | 同时考虑输入和输出宽度，常作线性或近似对称非线性网络的起点 |
| He/Kaiming normal | $\operatorname{Var}(w)=2/fan_{in}$（ReLU、`fan_in` 模式） | 补偿 ReLU 将不少负输入置零造成的方差变化 |

均匀版 Xavier、He 使用对应的均匀分布界限，目标方差与表中思路一致。若层宽相等，Xavier normal 的标准差约为 $1/\sqrt d$，ReLU 的 He normal 约为 $\sqrt{2/d}$。notebook 先测<strong>激活函数之前</strong>的线性层输出，所以 He 的标准差接近 $\sqrt 2$ 是预期现象；ReLU 后再看二阶矩，才对应它的推导目标。这些推导有输入独立、分布近似等条件；<strong>SwiGLU 的门控乘积不能直接套用 ReLU 的 He 推导</strong>。在完整 Transformer 中还要考虑嵌入、残差分支、归一化和输出投影。不要仅凭一张初始化表挑整网方案。

```python
import torch
from torch import nn

torch.manual_seed(7)
linear = nn.Linear(64, 128)
print(linear.weight.shape)  # [128, 64]：fan_in=64，fan_out=128

with torch.no_grad():
    nn.init.xavier_normal_(linear.weight)
    nn.init.zeros_(linear.bias)

weights = torch.empty(100_000)
nn.init.trunc_normal_(weights, mean=0.0, std=1.0, a=-2.0, b=2.0)
print(weights.min().item(), weights.max().item(), weights.std().item())
```

`trunc_normal_` 的 `std=1` 指截断<strong>之前</strong>的正态分布尺度，实测标准差会低于 1。`nn.init` 系列原地改参数，宜在模块构造或训练开始前运行；不要在每次前向中重新初始化。PyTorch 的 `nn.Linear` 默认有自己的初始化，不等于上面手动选择的 Xavier。要复现实验，应明确写出初始化函数并记录随机种子。[PyTorch 初始化 API](https://docs.pytorch.org/docs/stable/nn.init.html)列出了分布和 `fan` 的定义。

## 3. 残差连接：保留一条直接路径

普通堆叠计算 $x_{l+1}=F_l(x_l)$；残差子层计算

$$
x_{l+1}=x_l+F_l(x_l).
$$

加法要求两支形状相同。若输入与输出宽度不同，可以先用投影对齐；本课程中的 Transformer 子层都回到隐藏宽度 $d$，所以能直接相加。`x_l` 是<strong>残差流</strong>，注意力和前馈层在它上面提供更新，不能把残差理解为“误差”或“训练损失”。

反向看，局部雅可比矩阵是 $I+J_{F_l}$。其中 $I$ 对应直接路径，梯度可以绕过本层的复杂运算回传；但多个矩阵相乘仍可能放大、抵消或缩小梯度，所以“有残差就绝不会梯度消失/爆炸”是错误的。下面用一个极简标量检查：若 $F(x)=0.1x$，则 $y=1.1x$，导数为 $1.1$；没有残差时导数是 $0.1$。这只是局部例子，不代表真实深网的统计分布。

```python
x = torch.tensor(2.0, requires_grad=True)
y = x + 0.1 * x
y.backward()
print(y.item(), x.grad.item())  # 2.2, 1.1
```

## 4. Pre-LN 和 Post-LN 放置的是什么

写清计算顺序比记缩写可靠。以一个子层 $F$ 为例：

$$
\begin{aligned}
\text{Pre-LN:}\quad &y=x+F(\operatorname{Norm}(x)),\\
\text{Post-LN:}\quad &y=\operatorname{Norm}(x+F(x)).
\end{aligned}
$$

在 Pre-LN 中，残差加法的输出没有立刻穿过归一化，局部直接路径仍是 $x\mapsto x$。在 Post-LN 中，加法结果再经过归一化，反向的直接路径也要经过归一化的雅可比。原始 Transformer 采用残差加法后归一化；许多后续模型采用 Pre-LN。两者还涉及最终归一化、学习率和初始化等配置，不能只改一行顺序就断言哪种模型全面更好。[Pre-LN/Post-LN 梯度分析](https://arxiv.org/abs/2002.04745)讨论了初始化附近的差异。

对一个含注意力 $A$ 和前馈层 $M$ 的 Pre-LN Block，实际会有<strong>两个</strong>残差加法：

$$
u=x+A(\operatorname{Norm}_1(x)),\qquad
y=u+M(\operatorname{Norm}_2(u)).
$$

Chapter 3 会展开 $M$，Chapter 7 再展开 $A$。不要把 `Norm` 与 `Residual` 当成互斥结构：归一化决定输入或输出怎样缩放，残差决定两条路径怎样相加。Chapter 0 的 LayerNorm/RMSNorm 是可放在这些位置的具体运算。

## 5. 深度增加时，为什么还要关心残差分支的尺度

把 $L$ 层更新不断加到残差流中，即使每层的输出均值接近零，更新的方差也可能累积。一个教学用的显式缩放写成

$$
x_{l+1}=x_l+\alpha F_l(\operatorname{Norm}(x_l)).
$$

$\alpha=1$ 是未显式缩放的情况。减小 $\alpha$ 会改变前向更新和反向传播的尺度，但也可能让分支学得太慢；它不是对任意层数都有效的“安全按钮”。另一类做法不在每次前向乘 $\alpha$，而是在<strong>初始化时</strong>缩小写回残差流的输出投影。例如 nanoGPT 对每个 Block 中注意力和 MLP 的 `c_proj.weight` 使用 `0.02 / sqrt(2 * n_layer)` 的初始标准差；这里的 2 对应每层两条残差分支。这是特定架构的经验设计，不等同于把整层所有权重都按此比例缩小，也不等同于 [Chapter 0 的 DeepNorm](chapter0_normalization.md#_5-deepnorm) 完整配置。[nanoGPT 源码](https://github.com/karpathy/nanoGPT/blob/master/model.py)给出了这个具体实现。

## 6. 动手实验：测量，而不是只看一条损失曲线

<a href="/tinyllm/chapter2_Initialization_Residuals/ch2.ipynb" download>ch2.ipynb</a> 分三步运行：

1. 对多次抽样的权重记录均值、标准差和截断范围；观察 `fan_in` 改变后，固定 `std` 与 Xavier/He 的输出方差有何不同。Plotly 图展示各方法的实测标准差。
2. 让同一个输入通过一串小型线性残差层，对比纯堆叠、Pre-LN、Post-LN 与带显式缩放的 Pre-LN。记录每层输出的 RMS 和输入梯度范数，而不只看最后一个数。
3. 改变深度和随机种子重复观察。仅有初始化时的前向/反向，不包含优化器和数据训练；曲线不能证明某种结构在语言模型任务上更好。

排查深层网络时同时记下 `loss` 是否有限、每层激活 RMS、各层参数梯度范数和输入梯度范数。值偏大或偏小要结合宽度、深度、目标函数、归一化和学习率判断；`NaN` 则应先定位第一次出现的位置。实验中的 `float32` 和 CPU 只是为降低环境差异，不能替代大模型的低精度与长时间训练验证。

## 检查理解

* `nn.Linear(32, 96)` 的权重形状是什么？`fan_in` 与 `fan_out` 各是多少？
* 为什么把每个隐藏层的权重全设为零，与把某个残差输出投影设为零，不是同一件事？
* 写出一个 Pre-LN Block 的两次残差加法；哪条路径让输入可以直接走到输出？
* 一张“深度 32 比深度 4 的梯度更大”的图，为什么还不足以判断训练一定失败？

## 参考资料与下一步

* [PyTorch 初始化函数与 `fan` 定义](https://docs.pytorch.org/docs/stable/nn.init.html)
* [Glorot 与 Bengio：Xavier 初始化](https://proceedings.mlr.press/v9/glorot10a.html)
* [He 等：ReLU 网络初始化](https://arxiv.org/abs/1502.01852)
* [He 等：残差网络](https://arxiv.org/abs/1512.03385)
* [Vaswani 等：原始 Transformer](https://arxiv.org/abs/1706.03762)
* [Xiong 等：Pre-LN/Post-LN 分析](https://arxiv.org/abs/2002.04745)

下一章把残差分支中的前馈层拆开，看 [激活函数与门控前馈层](chapter3_activations_ffn.md)。返回 [课程总目录](index.md#课程路线规划)。
