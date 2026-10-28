---
title: "第 7 章：激活函数与门控前馈层"
description: "两个线性层之间为什么要有激活函数；ReLU、GELU、SiLU 的区别；SwiGLU 门控前馈层怎样搭、参数量怎样算。"
pageClass: tinyllm-course
---

# 第 7 章：激活函数与门控前馈层

[课程总览](./index.md) · [上一章](./position-encoding.md) · [下一章](./transformer-block.md)

::: tip 本章学习目标
能用一行矩阵乘法说明非线性为什么必要；能比较 ReLU、GELU、SiLU 的函数曲线与导数曲线；能写出 SwiGLU 前馈层，并手算它与普通 FFN 在相同参数预算下的中间宽度。

**前置：** [第 2 章](./tensors-and-autograd.md)的矩阵乘法，[第 4 章](./embeddings-and-output.md)的隐藏向量形状 `[batch, seq, d]`。

**实践方式：** [activations-and-ffn.ipynb](/tinyllm/notebooks/activations-and-ffn)（也可以直接运行 <a href="/tinyllm/code/activations-and-ffn.py" download>activations-and-ffn.py</a>），CPU 即可，图表使用 Plotly。
:::

<TinyLLMMap active="activations-and-ffn" />

## 问题：两个线性层，只学会了一条直线

注意力（[第 5 章](./self-attention.md)）负责让每个 token 去看前面的字，把需要的信息取回来。取回来之后，每个 token 还要自己“消化”一下：把手里的特征重新组合，算出新的特征。这一步交给**前馈层**（FFN），它对每个 token 单独计算，Block 里大约三分之二的参数都在这里。

最朴素的想法是放两个线性层：先把宽度放大，再投影回来。

做个小实验：用一个 $1\to32\to1$ 的两层网络拟合区间 $[-\pi,\pi]$ 上的 $\sin x$，Adam、学习率 0.01、训练 1500 步。一个版本两层之间什么都不加，另一个版本在中间加一个 GELU。先猜：中间有 32 个隐藏单元，不加激活的版本能拟合出正弦曲线吗？

![两层网络拟合 sin(x)：不加激活函数时只能得到一条直线，MSE 为 0.200；中间加 GELU 后几乎与正弦曲线重合，MSE 为 5.2e-7](/tinyllm/figures/activation-fit.svg)

灰色是目标 $\sin x$。不加激活的版本训练完只得到一条斜直线，均方误差停在 0.200；加了 GELU 的版本几乎与正弦曲线重合，误差只有 $5.2\times10^{-7}$。32 个隐藏单元本身没有帮上忙，起作用的是中间那一步非线性。

本章先解释这个现象，再比较几种常用的激活函数，最后搭出 TinyLLM 使用的 SwiGLU 门控前馈层。

## 1. 两个线性层为什么会合并成一个

没有激活函数时，连续两层线性变换可以直接合并：

$$
xW_1W_2=x(W_1W_2)=xW.
$$

不管中间宽度是 32 还是 4096，整体仍是一个线性映射；加上偏置也只是仿射映射，画出来就是一条直线（高维时是一个平面）。上图那条直线正是这样来的。激活函数对中间结果<strong>逐元素</strong>做一次非线性变换，两层就再也合并不了，模型才能拼出弯曲的函数。

Transformer 的前馈层（FFN）因此写成

$$
\operatorname{FFN}(x)=W_{down}\,\phi(W_{up}x+b_{up})+b_{down}.
$$

::: info 本章代码从哪里来
本章所有代码都在一个文件里：<a href="/tinyllm/code/activations-and-ffn.py" download>activations-and-ffn.py</a>（[在 GitHub 上查看](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/tinyllm/code/activations-and-ffn.py)）。下面的代码块都是从这个文件里直接截取的片段，所以单独复制一段可能缺少 `import` 或前面定义的变量；想自己运行，请下载完整文件，`python activations-and-ffn.py` 从头跑到尾即可。notebook 版本也由同一个文件生成，可以[在线查看](/tinyllm/notebooks/activations-and-ffn)，或[在 Colab 中直接运行](https://colab.research.google.com/github/lewislau86/lewislau86.github.io/blob/master/docs/public/tinyllm/notebooks/activations-and-ffn.ipynb)。
:::

公式把 $x$ 当列向量；PyTorch 以最后一轴为特征，等价代码是 `down(phi(up(x)))`。记 $d$ 为模型隐藏宽度、$m$ 为前馈层中间宽度：`up` 把 $d$ 放大到 $m$，`down` 再投回 $d$，所以输入和输出都是 `[batch, seq, d]`。

<<< @/public/tinyllm/code/activations-and-ffn.py#ffn-shape

先猜中间那个张量的形状：`up` 之后是 `[2, 3, 32]`，32 落在最后一轴，也就是每个 token 的特征从 8 个扩成 32 个。FFN 对<strong>每个 token 分别使用同一组参数</strong>，token 之间的信息交换由注意力层负责；上下文通过注意力更新后的隐藏状态间接影响 FFN 的输入。

## 2. ReLU、GELU、SiLU：负输入怎样处理

三种常用激活在正半轴都接近 $y=x$，区别主要在负半轴：

| 函数 | 定义 | 读图时关注 |
| --- | --- | --- |
| ReLU | $\max(0,x)$ | 负半轴输出为 0，导数也为 0；在 0 处有一个尖角 |
| GELU | $x\Phi(x)$，$\Phi$ 是标准正态分布累积分布函数 | 平滑地压低负值，部分负输入仍有非零输出；`approximate='tanh'` 是近似实现 |
| SiLU/Swish | $x\sigma(x)$，$\sigma(x)=1/(1+e^{-x})$ | 用 Sigmoid 做平滑门控，负输入被逐渐压小 |

![ReLU、GELU、SiLU 在输入 -4 到 4 时的函数曲线：ReLU 将负值置零，GELU 和 SiLU 在负半轴平滑变化](/tinyllm/figures/activation-functions.svg)

横轴是输入 $x$，纵轴是函数输出。蓝色实线为 ReLU，橙色虚线为 GELU，紫色点线为 SiLU。正半轴三条线逐渐靠拢；负半轴 ReLU 是一条贴着 0 的直线，GELU 和 SiLU 先略微下探再回到 0 附近。配套 notebook 可以改变区间重画曲线。

## 3. 从导数看：每种选择解决了什么，又留下什么

反向传播要把每层的局部导数相乘，所以挑激活函数时，导数曲线和函数曲线同样重要。

![Sigmoid、Tanh、ReLU、GELU 与 SiLU 在输入 -4 到 4 时的导数曲线：Sigmoid 与 Tanh 在两端趋近 0，ReLU 在负半轴为 0、正半轴为 1，GELU 与 SiLU 平滑过渡并在部分负输入上保留梯度](/tinyllm/figures/activation-derivatives.svg)

### Sigmoid 与 Tanh：两端饱和

早期网络常用 Sigmoid 或 Tanh 把数值压进固定区间。它们处处可导，但 $|x|$ 大时曲线变平，导数趋近 0：

$$
\sigma'(x)=\sigma(x)(1-\sigma(x))\leq\tfrac14,\qquad
\tanh'(x)=1-\tanh^2(x).
$$

手算 $x=4$：Sigmoid 的导数约为 0.018，Tanh 约为 0.0013。路径上反复乘这样的小因子，靠近输入的层收到的梯度就会很小，这叫<strong>梯度消失</strong>。图中两条曲线在区间两端都贴近 0，就是这个原因。[Glorot 与 Bengio 的分析](https://proceedings.mlr.press/v9/glorot10a.html)展示了 Sigmoid 饱和对深层训练的影响。它们在输出概率、门控等位置仍然很有用；这里讨论的是把它们当作深层前馈网络的主要隐藏层激活。

### ReLU：正半轴导数恒为 1

ReLU 在正半轴的导数恒为 1，活跃路径上的梯度不再被压小，计算也最简单。代价在负半轴：输出和导数都是 0。如果某个单元在相关输入上长期为负，它通过这条路径就得不到更新，常称为“死亡 ReLU”。

ReLU 在 $x=0$ 处有尖角，数学上不可导；PyTorch 在这一点约定梯度为 0，其他位置照常求导，训练不受影响。实际更值得检查的是有多少输入落在负半轴。[PyTorch 自动求导规则](https://docs.pytorch.org/docs/stable/notes/autograd.html#gradients-for-non-differentiable-functions)说明了不可导点的处理，[整流网络论文](https://proceedings.mlr.press/v15/glorot11a.html)讨论了它的训练性质。

### GELU 与 SiLU：平滑地放行

GELU 用 $\Phi(x)$、SiLU 用 $\sigma(x)$ 对输入做随数值变化的平滑加权：中等大小的负输入不会立刻归零，0 处的尖角也消失了。导数图上，它们在部分负输入上仍有梯度；很负时导数同样趋近 0，在负半轴的一小段甚至略小于 0。[GELU 论文](https://arxiv.org/abs/1606.08415)和 [Swish/SiLU 论文](https://arxiv.org/abs/1710.05941)在各自的实验设置中观察到了收益。它们计算稍复杂；深层网络整体的梯度是否稳定，还要靠[初始化与残差路径](./initialization-and-residuals.md)、[归一化](./normalization.md)和合适的学习率共同保证。

用代码核对几个点上的输出和导数：

<<< @/public/tinyllm/code/activations-and-ffn.py#activation-points

`F.gelu` 默认计算精确形式，`F.gelu(x, approximate='tanh')` 使用常见的 tanh 近似，两者只有微小的数值差别，模型结构相同。`nn.SiLU` 与 `F.silu` 是同一个激活，“Swish”也常用来称呼同样的 $x\sigma(x)$。详见 [PyTorch GELU](https://docs.pytorch.org/docs/stable/generated/torch.nn.GELU.html) 和 [SiLU](https://docs.pytorch.org/docs/stable/generated/torch.nn.SiLU.html) 文档。

## 4. 门控前馈层：两条投影相乘

上面的激活都是对一条投影的结果逐元素变换。SwiGLU 再加一条由输入决定的<strong>门控</strong>路径：同一个输入经过两条投影，一条先过 SiLU 当作“门”，再与另一条<strong>逐元素相乘</strong>：

$$
g=\operatorname{SiLU}(W_gx+b_g),\qquad
v=W_vx+b_v,\qquad
\operatorname{SwiGLU}(x)=W_d(g\odot v)+b_d.
$$

$g$ 与 $v$ 的形状都是 `[batch, seq, m]`，$\odot$ 是同一 token、同一特征上的乘法；$W_d$ 再把宽度 $m$ 投回 $d$。门 $g$ 由当前输入算出，逐个特征地决定 $v$ 里的信息放行多少。所以从普通 FFN 换到 SwiGLU，结构从两个投影变成了三个投影，同时激活换成了 SiLU。[GLU Variants Improve Transformer](https://arxiv.org/abs/2002.05202) 系统比较了这类门控前馈变体，结论来自该论文的实验配置。

<<< @/public/tinyllm/code/activations-and-ffn.py#swiglu

三个投影都不带偏置，便于直接数参数。也可以把 `gate`、`value` 融合成一次宽度 `2m` 的投影再拆成两半，只要权重与拆分轴对应，数学上完全相同；初学时分开写更方便检查每个张量的形状。

## 5. 公平比较：同样的参数预算，中间宽度取多少

忽略偏置，普通 FFN 有 `up`、`down` 两个投影，权重数为 $dm+md=2dm$；SwiGLU 有 `gate`、`value`、`down` 三个投影，是 $3dm$。如果两者都取 $m=4d$，门控版这部分权重多出一半，效果差异就很难归到激活函数头上。

先猜：普通 FFN 取 $m=4d$ 时，SwiGLU 的 $m$ 取多少，两者权重数才相同？

![普通 FFN 与 SwiGLU 的结构与参数量对比：普通 FFN 由 d 升到 4d、激活、再降回 d，共 8d² 个权重；SwiGLU 的 gate 和 value 都由 d 升到 m，SiLU(gate) 与 value 逐元素相乘后降回 d，m 约为 8d/3 时同样是 8d²；d=12 时中间宽度分别为 48 与 32，权重都是 1152 个](/tinyllm/figures/swiglu-vs-ffn.svg)

左边是普通 FFN：$2\times d\times4d=8d^2$。右边是 SwiGLU：令 $3dm=8d^2$，得 $m=8d/3$，也就是普通版中间宽度的 $2/3$，实际再按硬件或实现需要取整。图中用 $d=12$ 手算：普通版 $m=48$，权重 $2\times12\times48=1152$；门控版 $m=32$，权重 $3\times12\times32=1152$，两边相等。

加入偏置时，普通版额外有 $m+d$ 个参数，门控版额外有 $2m+d$ 个；本章示例统一设 `bias=False`，让比较更清楚。参数量对齐之后，计算时间和显存仍会有差别：门控版多一次投影和一次逐元素乘法，实际速度还取决于算子融合、批量、设备、dtype 和需要保存的中间张量。前馈层的宽度也影响残差分支的输出尺度，初始化要和[第 9 章](./initialization-and-residuals.md)一起检查。

## 6. 放进 Pre-Norm Block，接上残差

前馈层不会单独使用。[第 8 章](./transformer-block.md)会把它和注意力一起装进 Block，它在 Block 里的样子是

$$
y=u+\operatorname{FFN}(\operatorname{Norm}_2(u)),
$$

其中 $u$ 是注意力处理之后的隐藏状态。这里先把另外两个零件当成黑盒：`Norm` 把输入调回统一尺寸，“$u+$”这一步叫残差连接，保留一条直通路径；它们为什么必不可少，要等到第 8 章把 Block 叠深、发现训不动之后，在[第 9 章](./initialization-and-residuals.md)和[第 10 章](./normalization.md)讲清楚。下面先实现这个<strong>前馈半块</strong>：

<<< @/public/tinyllm/code/activations-and-ffn.py#prenorm-ffn

三个部件各管一件事：删掉 `x + ...`，它仍有非线性，但不再是残差子层；把 `norm` 挪到加法之后，就变成 Post-Norm 位置；把 SiLU 换成 ReLU 或 GELU，只改变激活，Pre-Norm 与残差的结构不变。这里用的 `nn.RMSNorm` 是 TinyLLM 的主线选择，第 10 章会和 LayerNorm 一起比较。

## 7. 动手实验：曲线、梯度、参数与简单拟合

[activations-and-ffn.ipynb](/tinyllm/notebooks/activations-and-ffn) 包含四组检查：

1. 用 Plotly 同时画 Sigmoid、Tanh、ReLU、GELU、SiLU 的函数和 `autograd` 导数曲线；对照饱和区、ReLU 负半轴和零点附近。
2. 在 `[2, 3, d]` 输入上运行普通 FFN 与 SwiGLU，打印每一步形状，并用 `sum(p.numel() for p in model.parameters())` 核对第 5 节的参数公式。
3. 对同一个输入与标量损失运行 `backward()`，确认三条 SwiGLU 投影都有梯度，并检查残差前馈半块能把梯度传回输入。
4. 用一个固定的合成回归任务比较普通 FFN 与门控 FFN 的短程拟合曲线。只用一个种子和很小的数据集，<strong>它是代码连通性演示</strong>，用来确认各部件接对了。

要真正比较架构，需要同时控制参数预算、初始化、优化器、学习率、训练步数、数据、设备和随机种子，并重复多次。门控版在同一 `m` 下参数更多，先按第 5 节对齐预算，再讨论其他因素。

## 本章结论：TinyLLM 的选择 {#tinyllm-choice}

<strong>默认用无偏置 SwiGLU：</strong>`SiLU(gate(x)) * value(x)` 再经 `down` 写回残差流。普通两投影 FFN 若用中间宽度 `4d`，门控版取约 `8d/3`，使两者的权重数都约为 `8d²`（第 5 节）。这样既能学习由输入决定的门控，又避免在同一 `4d` 宽度下多用一半权重、却把收益全算在激活函数头上。[GLU 变体论文](https://arxiv.org/abs/2002.05202)报告了相对 ReLU/GELU 的改进，[LLaMA](https://arxiv.org/abs/2302.13971) 也采用 SwiGLU；这些是特定规模和数据上的结果。

<strong>何时改选？</strong>复现 GPT 风格模型时，用 GELU 普通 FFN；需要最简单的算子和教学对照时，用 ReLU 普通 FFN。模型能否稳定训练，还取决于[初始化与残差](./initialization-and-residuals.md)、[归一化](./normalization.md)、优化器和学习率。notebook 保留了参数匹配的普通 FFN 作对照。

::: warning 常见误区
- **把普通 FFN 的 `GELU` 换成 `SiLU` 还不是 SwiGLU。** SwiGLU 的关键是 gate、value 两条投影逐元素相乘，一共三个投影。
- **SwiGLU 的“门”是逐特征的乘法。** 它和注意力的 Q/K/V、MoE 的专家路由都无关。
- **梯度消失说的是导数很小，函数本身照样可导。** Sigmoid 在 $x=4$ 处导数约 0.018，问题出在多层相乘。
- **ReLU 在 0 处不可导，并不妨碍反向传播。** 框架在这一点约定梯度为 0；需要关注的是大量输入落在负半轴。
- **参数量相同，速度和显存未必相同。** 门控版多一次投影和逐元素乘法，实际开销取决于实现与硬件。
:::

## 检查理解

1. 为什么两个没有激活函数的线性层可以合成一个？

   <details><summary>参考答案</summary>

   因为 $xW_1W_2=x(W_1W_2)$，两个矩阵的乘积仍是一个矩阵，整体只是一个线性（加偏置后仿射）映射，开头的拟合实验因此只得到一条直线。

   </details>

2. Sigmoid 在 $x=4$ 的导数很小，ReLU 在 $x=-1$ 的导数为零：这两种小梯度来自同一种机制吗？

   <details><summary>参考答案</summary>

   不同。Sigmoid 是饱和：曲线在两端变平，导数很小但不为 0，多层相乘后才变得极小；ReLU 是在负半轴整段关闭，导数恰好为 0，该单元对这个输入完全没有梯度。

   </details>

3. `d=12`、`m_plain=48` 时，匹配权重参数量的 SwiGLU 中间宽度是多少？

   <details><summary>参考答案</summary>

   32。普通版 $2\times12\times48=1152$，SwiGLU 版 $3\times12\times32=1152$。

   </details>

4. 在 `x + FFN(Norm(x))` 中，哪一部分让梯度有直接路径，哪一部分提供非线性？

   <details><summary>参考答案</summary>

   加号左边的 `x` 是直通路径，梯度原样传回输入；非线性来自 FFN 内部的激活（SwiGLU 中的 SiLU 及门控乘法）。

   </details>

## 参考资料

- [PyTorch ReLU](https://docs.pytorch.org/docs/stable/generated/torch.nn.ReLU.html) · [GELU](https://docs.pytorch.org/docs/stable/generated/torch.nn.GELU.html) · [SiLU](https://docs.pytorch.org/docs/stable/generated/torch.nn.SiLU.html)
- [PyTorch：不可导点的自动求导规则](https://docs.pytorch.org/docs/stable/notes/autograd.html#gradients-for-non-differentiable-functions)
- [Glorot 与 Bengio：深层网络与 Sigmoid 饱和](https://proceedings.mlr.press/v9/glorot10a.html)
- [Glorot 等：整流网络](https://proceedings.mlr.press/v15/glorot11a.html)
- [Hendrycks 与 Gimpel：GELU](https://arxiv.org/abs/1606.08415)
- [Ramachandran 等：Swish](https://arxiv.org/abs/1710.05941)
- [Shazeer：GLU Variants Improve Transformer](https://arxiv.org/abs/2002.05202)
- [Vaswani 等：Transformer 前馈层](https://arxiv.org/abs/1706.03762)
- [LLaMA，Touvron 等，2023](https://arxiv.org/abs/2302.13971)

到这里，Block 里的两种子层都有了：注意力负责 token 之间交换信息，前馈层负责每个 token 自己加工。下一章把它们装进 Block 并叠起来：[第 8 章：Transformer Block](./transformer-block.md)（规划中）；已完成的下一章是[第 9 章：初始化与残差路径](./initialization-and-residuals.md)。
