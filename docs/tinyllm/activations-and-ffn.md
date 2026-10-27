---
title: "第 5 章：激活函数与门控前馈层"
description: "两个线性层之间为什么要有激活函数；ReLU、GELU、SiLU 的区别；SwiGLU 门控前馈层怎样搭、参数量怎样算。"
pageClass: tinyllm-course
---

# 第 5 章：激活函数与门控前馈层

[课程总览](./index.md) · [上一章](./normalization.md) · [下一章](./tokenization.md)

::: tip 本章学习目标
解释非线性为什么必要；比较 ReLU、GELU、SiLU 的函数与导数；能写出 SwiGLU 前馈层并计算它与普通 FFN 的参数量。

**前置：** [第 3 章](./initialization-and-residuals.md)的残差子层，[第 4 章](./normalization.md)的 RMSNorm。

**实践方式：** <a href="/tinyllm/notebooks/activations-and-ffn.ipynb" download>activations-and-ffn.ipynb</a>，CPU 即可，图表使用 Plotly。
:::

[第 3 章](initialization-and-residuals.md) 把隐藏状态写成“旧状态 + 一个子层更新”。这个子层怎样把每个 token 的特征重新组合？本章先看 ReLU、GELU、SiLU 的函数与梯度，再搭建普通前馈层和 SwiGLU 门控前馈层。

<TinyLLMMap active="activations-and-ffn" />

## 记号

设输入 $x$ 的形状是 `[batch, seq, d]`，`d` 是模型隐藏宽度，`m` 是前馈层中间宽度。本章实验只需 CPU，不训练完整语言模型。

## 1. 两个线性层之间为什么要有激活函数

若没有非线性，连续两层线性变换可以合并：$xW_1W_2=xW$。即使增加中间宽度，整体仍是一个线性映射；加上偏置也只是仿射映射。激活函数把中间结果逐元素变换，模型才可以表示更复杂的关系。

普通 Transformer 前馈层常写成

$$
\operatorname{FFN}(x)=W_{down}\,\phi(W_{up}x+b_{up})+b_{down}.
$$

公式把 $x$ 当列向量；PyTorch 用最后一轴为特征，等价代码是 `down(phi(up(x)))`。`up: d→m`，`down: m→d`，所以输入和输出都是 `[batch, seq, d]`。它对<strong>每个 token 分别使用同一组参数</strong>；序列位置之间的信息交换发生在注意力层，而不是这个逐 token 前馈层中。上下文仍会间接影响 FFN 的输入，因为它接收注意力更新后的隐藏状态。

```python
import torch
from torch import nn

x = torch.randn(2, 3, 8)  # 2 条样本，每条 3 个 token，隐藏宽度 8
ffn = nn.Sequential(nn.Linear(8, 32), nn.GELU(), nn.Linear(32, 8))
print(ffn(x).shape)  # torch.Size([2, 3, 8])
```

## 2. ReLU、GELU、SiLU 分别怎样处理负输入

| 函数 | 定义 | 读图时关注 |
| --- | --- | --- |
| ReLU | $\max(0,x)$ | 负半轴输出为 0，负半轴导数为 0；在 0 处数学上不可导，框架采用约定的梯度 |
| GELU | $x\Phi(x)$，$\Phi$ 是标准正态分布累积分布函数 | 平滑地压低负值，部分负输入仍给出非零输出；`approximate='tanh'` 是近似实现 |
| SiLU/Swish | $x\sigma(x)$，$\sigma(x)=1/(1+e^{-x})$ | 平滑门控，负输入一般也不是直接截为 0 |

![ReLU、GELU、SiLU 在输入 -4 到 4 时的函数曲线：ReLU 将负值置零，GELU 和 SiLU 在负半轴平滑变化](/tinyllm/figures/activation-functions.svg)

图中横轴是输入 $x$，纵轴是函数输出。蓝色实线为 ReLU，橙色虚线为 GELU，紫色点线为 SiLU；三者在正半轴逐渐接近，但负半轴的形状不同。配套 notebook 可以改变区间并重画曲线。

### 旧选择解决了什么，又留下什么问题

早期网络常用 Sigmoid 或 Tanh 把数值压进固定区间。它们处处可导，但当 $|x|$ 很大时输出接近区间边界，曲线变平，导数趋近 0：

$$
\sigma'(x)=\sigma(x)(1-\sigma(x))\leq\tfrac14,\qquad
\tanh'(x)=1-\tanh^2(x).
$$

例如 $x=4$ 时，Sigmoid 的导数约为 $0.018$，Tanh 的导数约为 $0.0013$。反向传播要把多层的局部导数相乘；若路径上反复出现很小的因子，前面层收到的梯度可能变得很小。这叫<strong>梯度消失</strong>，不是“函数不能求导”。它们在输出概率、门控等位置仍有用途；这里讨论的是把它们作为深层前馈网络的主要隐藏层激活。[Glorot 与 Bengio 的分析](https://proceedings.mlr.press/v9/glorot10a.html)展示了 Sigmoid 饱和对深层训练的影响。

ReLU 在正半轴的导数恒为 1，缓解了活跃路径上由 Sigmoid/Tanh 饱和造成的梯度缩小，而且计算简单。但它把负输入直接变为 0，负半轴导数也为 0；如果某个单元在相关输入上长期为负，它通过这条激活路径就难以得到更新，常称为“死亡 ReLU”。<strong>ReLU 在 $x=0$ 数学上不可导，不等于模型无法反向传播。</strong>PyTorch 在这个点选用梯度 0，其他位置照常求导；实际更值得检查的是大量输入是否落入负半轴。[PyTorch 自动求导规则](https://docs.pytorch.org/docs/stable/notes/autograd.html#gradients-for-non-differentiable-functions)说明了不可导点的处理，[整流网络论文](https://proceedings.mlr.press/v15/glorot11a.html)也讨论了其训练性质。

### 为什么尝试 GELU、SiLU

GELU 用 $\Phi(x)$、SiLU 用 $\sigma(x)$ 对输入做平滑的、随数值变化的加权。它们让中等大小的负输入不必像 ReLU 那样立刻归零，并消除了 ReLU 在 0 处的尖角。这给前馈层另一种控制信息通过的方式，相关研究在各自实验设置中观察到收益：[GELU 论文](https://arxiv.org/abs/1606.08415)、[Swish/SiLU 论文](https://arxiv.org/abs/1710.05941)。

![Sigmoid、Tanh、ReLU、GELU 与 SiLU 在输入 -4 到 4 时的导数曲线](/tinyllm/figures/activation-derivatives.svg)

导数图让代价和收益同时可见：Sigmoid/Tanh 在区间两端接近 0；ReLU 的负半轴为 0；GELU/SiLU 在部分负输入上仍有梯度，但<strong>很负时也趋近 0，局部导数甚至可以为负</strong>。它们计算更复杂，也不能单靠“平滑”防止深层网络的梯度消失、爆炸或数值溢出。那些问题还受 [初始化与残差路径](initialization-and-residuals.md)、[归一化](normalization.md)和学习率等因素影响。

```python
import torch.nn.functional as F

values = torch.tensor([-2.0, -1.0, 0.0, 1.0, 2.0], requires_grad=True)
for name, fn in [('Sigmoid', torch.sigmoid), ('Tanh', torch.tanh),
                 ('ReLU', F.relu), ('GELU', F.gelu), ('SiLU', F.silu)]:
    probe = values.detach().clone().requires_grad_()
    output = fn(probe)
    gradient = torch.autograd.grad(output.sum(), probe)[0]
    print(name, output.detach().tolist(), gradient.tolist())
```

`F.gelu` 默认计算精确形式；`F.gelu(x, approximate='tanh')` 使用常见的 tanh 近似。两者的微小数值差别不是不同的模型结构。`nn.SiLU` 与 `F.silu` 表示同一激活；“Swish”常用于称呼相同的 $x\sigma(x)$ 形式。详情见 [PyTorch GELU](https://docs.pytorch.org/docs/stable/generated/torch.nn.GELU.html) 和 [SiLU](https://docs.pytorch.org/docs/stable/generated/torch.nn.SiLU.html) 文档。

## 3. 门控前馈层：两条投影相乘

平滑激活只是对一条投影的结果逐元素变换。SwiGLU 再增加一条由输入决定的门控路径：它让同一个输入经过两条投影，其中一条先过 SiLU，再与另一条<strong>逐元素相乘</strong>：

$$
g=\operatorname{SiLU}(W_gx+b_g),\qquad
v=W_vx+b_v,\qquad
\operatorname{SwiGLU}(x)=W_d(g\odot v)+b_d.
$$

$g$ 与 $v$ 的形状都为 `[batch, seq, m]`，$\odot$ 表示同一位置、同一特征的乘法；`W_d` 再把宽度 $m$ 投回 $d$。这里“门”由输入计算得到，控制另一支特征通过的幅度，<strong>不是注意力的 Q/K/V，也不是 MoE 的专家路由</strong>。从普通 FFN 换到 SwiGLU，不仅是把 ReLU 换成 SiLU，还把两投影结构换成三投影结构；它并非针对 ReLU 在 0 处不可导的修补。这类门控前馈变体在 [GLU Variants Improve Transformer](https://arxiv.org/abs/2002.05202) 中作过系统比较；该论文的效果来自特定实验配置，不能只凭函数名保证本课程的小模型一定更好。

```python
import torch.nn.functional as F

class SwiGLUFFN(nn.Module):
    def __init__(self, d: int, m: int):
        super().__init__()
        self.gate = nn.Linear(d, m, bias=False)
        self.value = nn.Linear(d, m, bias=False)
        self.down = nn.Linear(m, d, bias=False)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.down(F.silu(self.gate(x)) * self.value(x))

swiglu = SwiGLUFFN(8, 24)
print(swiglu(x).shape)  # torch.Size([2, 3, 8])
```

这里使用三个无偏置投影，便于直接数参数。也可把 `gate`、`value` 融合为一次宽度 `2m` 的投影，再拆成两半；只要权重与拆分轴对应，数学结构相同。两次独立线性层的写法更适合初学时检查每个张量的形状。

## 4. 公平比较前，先把宽度和参数量算清

忽略偏置，普通两层 FFN 的权重参数量是 $dm+md=2dm$；SwiGLU 有 `gate`、`value`、`down` 三个投影，是 $3dm$。若都取 $m=4d$，门控版的这部分权重比普通版多一半，不能把两者的速度或效果差异都归因于激活函数。

若要在相近参数预算下比较，普通 FFN 用 $m_{plain}=4d$ 时，SwiGLU 可先取 $m_{gate}\approx(2/3)m_{plain}=8d/3$，再按硬件或实现需要取整。比如 $d=12$：普通版 $m=48$ 有 $2\times12\times48=1152$ 个权重；门控版 $m=32$ 有 $3\times12\times32=1152$ 个权重。加入偏置时，普通版额外有 $m+d$ 个，门控版额外有 $2m+d$ 个；本章示例统一设 `bias=False`，让比较更清楚。

参数量接近仍<strong>不等于</strong>计算时间或显存相同。门控版有额外的投影与逐元素乘法，实际速度还受算子融合、批量、设备、dtype 和中间张量保存影响。前馈层宽度也影响残差分支输出尺度，初始化应与 第 3 章一起检查。

## 5. 放进 Pre-LN Block，别漏了残差

第 3 章的第二个子层可写为

$$
y=u+\operatorname{FFN}(\operatorname{Norm}_2(u)),
$$

其中 $u$ 已是注意力残差后的隐藏状态。`Norm`、普通 FFN 或 SwiGLU、残差加法分别承担不同作用。下面先不实现注意力，只演示这个<strong>前馈半块</strong>：

```python
class PreNormFFN(nn.Module):
    def __init__(self, d: int, m: int):
        super().__init__()
        self.norm = nn.RMSNorm(d)
        self.ffn = SwiGLUFFN(d, m)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return x + self.ffn(self.norm(x))

block = PreNormFFN(8, 24)
out = block(x)
print(out.shape)  # torch.Size([2, 3, 8])
```

若把 `x + ...` 删掉，它仍有非线性，但不再是这里定义的残差子层。若把 `norm` 移到加法之后，则变成 Post-Norm 位置。只换 ReLU/GELU/SiLU 不会改变 Pre-Norm 与 Post-Norm 的定义。这里用 `nn.RMSNorm` 与 第 4 章的主线一致；LayerNorm 也能按同一位置放置。

## 6. 动手实验：曲线、梯度、参数与简单拟合

<a href="/tinyllm/notebooks/activations-and-ffn.ipynb" download>activations-and-ffn.ipynb</a> 包含四组检查：

1. 用 Plotly 同时画 Sigmoid、Tanh、ReLU、GELU、SiLU 的函数和 `autograd` 导数曲线；对照饱和区、ReLU 负半轴和零点附近。
2. 在 `[2, 3, d]` 输入上运行普通 FFN 与 SwiGLU，打印每一步形状，并用 `sum(p.numel() for p in model.parameters())` 核对公式。
3. 对同一个输入与标量损失运行 `backward()`，确认三条 SwiGLU 投影都有梯度，也看残差前馈半块能把梯度传回输入。
4. 用一个固定的合成回归任务比较普通 FFN 与门控 FFN 的短程拟合曲线。只用一个种子和很小的数据集，<strong>这是代码连通性演示，不是架构优劣基准</strong>。

训练比较要同时控制参数预算、初始化、优化器、学习率、训练步数、数据、设备和随机种子；单看一条曲线不能得出“一种激活总是更强”的结论。特别是门控版在同一 `m` 下参数更多，先按第 4 节匹配预算再讨论别的因素。

## 本章结论：TinyLLM 的选择 {#tinyllm-choice}

<strong>默认用无偏置 SwiGLU：</strong>`SiLU(gate(x)) * value(x)` 再经 `down` 写回残差流。普通两投影 FFN 若用中间宽度 `4d`，门控版先取约 `8d/3`，使权重数同为约 `8d²`；第 4 节会推导。这样选既能学习由输入决定的门控，又避免在同一 `4d` 宽度下多用约一半权重却误以为收益全来自激活函数。[GLU 变体论文](https://arxiv.org/abs/2002.05202)报告了相对于 ReLU/GELU 的改进，[LLaMA](https://arxiv.org/abs/2302.13971)也采用 SwiGLU；这不是每个数据规模上的胜负保证。

<strong>何时改选？</strong>复现 GPT 风格模型时可用 GELU 普通 FFN；需要最简单的算子和教学对照时可用 ReLU 普通 FFN。SiLU 是 SwiGLU 中门控支的激活，不能只把普通 FFN 的 `GELU` 改成 `SiLU` 就称为 SwiGLU。模型是否稳定还取决于 [初始化与残差](initialization-and-residuals.md)、[归一化](normalization.md)、优化器和学习率。以下演示会保留普通 FFN 作参数匹配的对照。

## 检查理解

* 为什么两个没有激活函数的线性层可以合成一个？
* Sigmoid 在 $x=4$ 的导数很小，ReLU 在 $x=-1$ 的导数为零：这两种小梯度来自同一种机制吗？
* ReLU 在 0 处不可导，为什么 PyTorch 仍能训练含 ReLU 的模型？GELU/SiLU 又为什么不能保证梯度稳定？
* `[2, 3, 8]` 的输入经过 `8→24→8` 普通 FFN 后，形状是什么？24 对应哪一轴？
* `d=12`、`m_plain=48` 时，匹配权重参数量的 SwiGLU 中间宽度是多少？
* 在 `x + FFN(Norm(x))` 中，哪一部分让梯度有直接路径，哪一部分提供非线性？

## 参考资料与下一步

* [PyTorch ReLU](https://docs.pytorch.org/docs/stable/generated/torch.nn.ReLU.html) · [GELU](https://docs.pytorch.org/docs/stable/generated/torch.nn.GELU.html) · [SiLU](https://docs.pytorch.org/docs/stable/generated/torch.nn.SiLU.html)
* [PyTorch：不可导点的自动求导规则](https://docs.pytorch.org/docs/stable/notes/autograd.html#gradients-for-non-differentiable-functions)
* [Glorot 与 Bengio：深层网络与 Sigmoid 饱和](https://proceedings.mlr.press/v9/glorot10a.html)
* [Glorot 等：整流网络](https://proceedings.mlr.press/v15/glorot11a.html)
* [Hendrycks 与 Gimpel：GELU](https://arxiv.org/abs/1606.08415)
* [Ramachandran 等：Swish](https://arxiv.org/abs/1710.05941)
* [Shazeer：GLU Variants Improve Transformer](https://arxiv.org/abs/2002.05202)
* [Vaswani 等：Transformer 前馈层](https://arxiv.org/abs/1706.03762)

到这里，Block 里除注意力以外的零件都讲完了。下一部分从文本入口开始构造语言模型：[第 6 章：文本与词元化](./tokenization.md)。
