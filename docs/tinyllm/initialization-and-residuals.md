---
title: "第 10 章：初始化与残差路径"
description: "参数从哪里开始：Xavier/He 初始化怎样按宽度选尺度；残差连接怎样给深层网络留一条直通路径。"
pageClass: tinyllm-course
---

# 第 10 章：初始化与残差路径

[课程总览](./index.md) · [上一章](./transformer-block.md) · [下一章](./normalization.md)

::: tip 本章学习目标
能根据权重形状找出 `fan_in`、`fan_out`，并估算一个线性层输出的尺度；能写出残差子层的前向式和反向梯度；能用每层激活 RMS 和梯度范数判断一个多层网络在起点是否异常。

**前置：** [第 2 章](./tensors-and-autograd.md)的张量形状与自动求导；知道 Block 由注意力和前馈层两个子层组成（[第 6 章](./self-attention.md)、[第 8 章](./activations-and-ffn.md)、[第 9 章](./transformer-block.md)）。

**实践方式：** [initialization-and-residuals.ipynb](/tinyllm/notebooks/initialization-and-residuals)（也可以直接运行 <a href="/tinyllm/code/initialization-and-residuals.py" download>initialization-and-residuals.py</a>），CPU 即可，图表使用 Plotly。
:::

<TinyLLMMap active="initialization-and-residuals" />

## 问题：随手设的权重，输出会随宽度变大

[第 9 章](./transformer-block.md)把注意力和前馈层装进了 Block，也看到了直接堆叠的下场：叠到 4 层，信号在训练开始前就缩成了 0，损失停在乱猜的水平。加上残差和 Pre-Norm 就好了，但为什么？深层网络还常出现另一种情况：损失一开始就变成 `nan`。这些问题往往在训练开始之前就埋下了，第一个嫌疑是参数的起点。

[第 2 章](./tensors-and-autograd.md)的参数是用 `torch.randn` 随手造出来的，每个数的标准差都是 1。现在把这种权重放进一个更宽的线性层 $y=xW$：输入 $x$ 的标准差为 1，权重是 $n_{\mathrm{in}}\times n_{\mathrm{in}}$ 的方阵。

先猜一猜：$n_{\mathrm{in}}=16$ 时，输出 $y$ 的标准差大约是多少？宽度加到 1024 呢？

![线性层输出的标准差随输入宽度变化：固定 std=1 时从 4.1 增长到 32，固定 std=0.02 时从 0.075 增长到 0.64，Xavier 始终约为 1，He 约为 1.41](/tinyllm/figures/init-fan-in.svg)

横轴是输入宽度 `fan_in`（16 到 1024），纵轴是输出标准差。红线用固定的 `std=1`：宽度 16 时输出标准差约 4.1，宽度 1024 时约 32，正好跟着 $\sqrt{n_{\mathrm{in}}}$ 涨。换成常见的固定 `std=0.02`，曲线整体低了很多，但形状一样，从 0.075 涨到 0.64。只有按宽度调整尺度的 Xavier（约 1.0）和 He（约 1.41）是两条水平线。

一层放大 4 倍还看得过去；几十层叠起来，信号和梯度就会一路放大或一路缩小。本章回答两个问题：<strong>参数的起点该取多大？信号和梯度怎样穿过许多层？</strong>前一个靠方差估计，后一个靠残差连接。

## 1. 一个输出的方差：宽度为什么会出现在公式里

设线性层有 $n_{\mathrm{in}}$ 个输入，某个输出为 $y=\sum_{i=1}^{n_{\mathrm{in}}}w_i x_i$。若 $w_i$ 独立、零均值，且与输入独立，在各输入方差大致相同的简化条件下，

$$
\operatorname{Var}(y)\approx n_{\mathrm{in}}\operatorname{Var}(w)\operatorname{Var}(x).
$$

用它核对上图：$n_{\mathrm{in}}=16$、$\operatorname{Var}(w)=\operatorname{Var}(x)=1$，得 $\operatorname{Var}(y)\approx16$，标准差约 4，实测 4.1；宽度 1024 时标准差约 $\sqrt{1024}=32$。`std=0.02` 时再乘 0.02：$0.02\times4=0.08$、$0.02\times32=0.64$，和图中的 0.075、0.64 吻合。

要让输出方差和输入一样，只需令 $n_{\mathrm{in}}\operatorname{Var}(w)\approx1$，也就是 $\operatorname{std}(w)\approx1/\sqrt{n_{\mathrm{in}}}$。这就是“宽度感知”初始化的核心想法。这个公式是初始化时的粗略估计：训练开始后权重与输入不再独立，残差、归一化、注意力和非线性也会改变结果。

在 PyTorch 中，`nn.Linear(d_in, d_out).weight` 的形状是 `[d_out, d_in]`，所以 `fan_in=d_in`、`fan_out=d_out`，这与计算时“输入乘权重转置”相配。自己写 `x @ W`、让 `W` 为 `[d_in, d_out]` 时，先检查初始化函数怎样解释两根轴，再套用。

## 2. 起点还要打破对称

既然尺度要小，能否干脆全设为 0？同一层的所有权重相同时，每个隐藏单元算出相同的输出、收到相同的梯度，更新后依然相同，永远学不出不同的特征。随机抽样的作用之一就是打破这种对称。

偏置设为 0 通常没问题，因为随机权重已经打破了对称。还有一种有意的零初始化：把某个残差分支的<strong>最后一层输出投影</strong>设为 0，让这个分支在起点接近恒等映射（残差在第 4 节介绍）。它是针对网络结构的选择，只作用在个别投影上。

## 3. 四种常见的抽样规则

下表都是<strong>抽样规则或初始尺度</strong>，只在训练开始前执行一次。比较时用相同输入、相同宽度并重复几个随机种子；一次抽样的样本标准差只会接近目标值。

| 方法 | 典型形式 | 先检查什么 |
| --- | --- | --- |
| 普通正态 | $w\sim\mathcal N(0,\sigma^2)$ | `std` 是否按层宽度与结构选取；固定的 `0.02` 适合某些具体模型，并非通用答案 |
| 截断正态 | 从正态分布抽样，只保留区间 $[a,b]$ 内的值 | 截断后实测标准差通常小于参数 `std`；落在区间外的值会被重新抽样 |
| Xavier/Glorot normal | $\operatorname{Var}(w)=2/(fan_{in}+fan_{out})$（`gain=1`） | 同时考虑输入和输出宽度，常作线性或近似对称非线性网络的起点 |
| He/Kaiming normal | $\operatorname{Var}(w)=2/fan_{in}$（ReLU、`fan_in` 模式） | 补偿 ReLU 把约一半输入置零造成的方差减半 |

均匀版 Xavier、He 使用对应的均匀分布界限，目标方差与表中思路一致。层宽相等时，Xavier normal 的标准差约为 $1/\sqrt d$，正好满足第 1 节的 $n_{\mathrm{in}}\operatorname{Var}(w)\approx1$，所以图中 Xavier 线停在 1.0。ReLU 的 He normal 约为 $\sqrt{2/d}$，方差多了一倍，所以在<strong>激活函数之前</strong>测得的输出标准差约为 $\sqrt2\approx1.41$；经过 ReLU 去掉一半之后，二阶矩才回到 1，这才是它的推导目标。

::: info 本章代码从哪里来
本章所有代码都在一个文件里：<a href="/tinyllm/code/initialization-and-residuals.py" download>initialization-and-residuals.py</a>（[在 GitHub 上查看](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/tinyllm/code/initialization-and-residuals.py)）。下面的代码块都是从这个文件里直接截取的片段，所以单独复制一段可能缺少 `import` 或前面定义的变量；想自己运行，请下载完整文件，`python initialization-and-residuals.py` 从头跑到尾即可。notebook 版本也由同一个文件生成，可以[在线查看](/tinyllm/notebooks/initialization-and-residuals)，或[在 Colab 中直接运行](https://colab.research.google.com/github/lewislau86/lewislau86.github.io/blob/master/docs/public/tinyllm/notebooks/initialization-and-residuals.ipynb)。
:::

<<< @/public/tinyllm/code/initialization-and-residuals.py#init-api

`trunc_normal_` 的 `std=1` 指截断<strong>之前</strong>的正态分布尺度，实测标准差会低于 1。`nn.init` 系列原地修改参数，放在模块构造时或训练开始前运行一次即可。`nn.Linear` 自带一套默认初始化（与上面手动选择的 Xavier 不同）；要复现实验，就明确写出初始化函数并记录随机种子。[PyTorch 初始化 API](https://docs.pytorch.org/docs/stable/nn.init.html)列出了各分布和 `fan` 的定义。

这些推导都假设输入独立、分布近似对称。在完整 Transformer 中还要一起考虑嵌入、残差分支、归一化和输出投影，所以初始化表只是起点，整网方案要靠测量来确认。

## 4. 残差连接：保留一条直通路径

初始化管住了单层的尺度，但每层的非线性仍会一点点改变信号。普通堆叠计算 $x_{l+1}=F_l(x_l)$，残差子层则计算

$$
x_{l+1}=x_l+F_l(x_l).
$$

![残差块示意：前向时输入 x 一路经过子层 F，一路直接走到加法处，输出 y = x + F(x)；反向时上游梯度 g 同样分成两路，dL/dx = g + J_F(x)^T g](/tinyllm/figures/residual-path.svg)

上半部分是前向：输入 $x$ 分成两路，一路经过子层 $F$，一路原样绕过去，两路在加号处汇合。下半部分是反向：从输出传回的梯度 $g$ 也分成两路，

$$
\frac{\partial L}{\partial x}=g+J_F(x)^{\top}g.
$$

第一项 $g$ 来自直通路径，原样传回输入，不管 $F$ 内部发生了什么；第二项才经过子层的雅可比 $J_F$。所以即使 $J_F$ 很小，输入端也至少收到上游的梯度。

加法要求两支形状相同。本课程中的 Transformer 子层都把输出投回隐藏宽度 $d$，所以能直接相加。$x_l$ 叫做<strong>残差流</strong>：它是一路传下去的隐藏状态，注意力和前馈层在它上面写入更新。

用一个标量手算：令 $F(x)=0.1x$，有残差时 $y=x+0.1x=1.1x$，导数为 1.1；没有残差时导数只有 0.1。

<<< @/public/tinyllm/code/initialization-and-residuals.py#residual-grad

每层的局部雅可比因此是 $I+J_{F_l}$，深层网络的总梯度是很多个这样的矩阵相乘。乘积里的 $J_{F_l}$ 仍可能把梯度一路放大。下一节用 32 层的实验看清这一点。

## 5. 32 层实测：信号和梯度怎样穿过深层

实验设置：32 层，宽度 $d=64$，每个子层 $F$ 都是 `tanh(Linear(x))`，用 Xavier 初始化；batch 为 256，损失取最后一层输出经一个固定随机投影后的均值。比较四种连法，记录每层输出的 RMS（左）和损失对每层输出的梯度范数（右）。这里只做初始化时的一次前向和反向，不训练。

其中两种连法用到 $\operatorname{Norm}$，暂时把它理解为“把每个 token 向量调回统一尺寸的一步”，具体公式见[第 11 章](./normalization.md)：

$$
\begin{aligned}
\text{Pre-LN:}\quad &y=x+F(\operatorname{Norm}(x)),\\
\text{Post-LN:}\quad &y=\operatorname{Norm}(x+F(x)).
\end{aligned}
$$

先猜：纯堆叠时，每层的信号会变大还是变小？只加残差、不做归一化呢？

![32 层网络各层输出 RMS 与梯度范数：纯堆叠时信号从 0.64 缩到 0.13、梯度在靠近输入处只剩 0.06；无归一化残差的信号从 1.2 涨到 4.75、梯度在输入端涨到 6.2；Pre-LN 信号涨得较慢，从 1.2 到 3.6，梯度 1.7 对 0.49；Post-LN 信号固定为 1.0，梯度 1.05 对 0.47](/tinyllm/figures/residual-depth.svg)

逐条读：

- <strong>纯堆叠</strong>：RMS 从第 1 层的 0.64 缩到第 32 层的 0.13。tanh 每层都把信号压小一点，Xavier 只保证线性部分不放大。梯度也一样：最后一层收到 0.44，传回第 1 层只剩 0.06，这就是梯度消失。
- <strong>残差、无归一化</strong>：每层都往残差流上加一份更新，RMS 从 1.2 一路涨到 4.75。梯度方向相反，最后一层 0.5，第 1 层 6.2，越往输入越大。直通路径保住了梯度，但 $I+J_F$ 连乘让它放大了。
- <strong>Pre-LN</strong>：残差流仍在增长（1.2 到 3.6），但每个子层看到的输入尺寸是统一的，增长慢了；梯度第 1 层 1.7、最后一层 0.49，差距小得多。
- <strong>Post-LN</strong>：每次相加后都归一化，RMS 固定在 1.0；梯度 1.05 对 0.47，在这张图里最平。

这张图只反映初始化时刻。[Xiong 等的分析](https://arxiv.org/abs/2002.04745)指出，Post-LN 在真实 Transformer 训练初期对学习率和 warmup 更敏感，Pre-LN 更容易稳定地训练起来；这类训练动态要在训练过程中观察，图里看不出来。

## 6. Pre-LN Block 里的两次残差

一个 Transformer Block 有注意力 $A$ 和前馈层 $M$ 两个子层。按 Pre-LN 连接，就有<strong>两次</strong>残差加法：

$$
u=x+A(\operatorname{Norm}_1(x)),\qquad
y=u+M(\operatorname{Norm}_2(u)).
$$

从 $x$ 到 $u$ 再到 $y$，有一条只经过两个加号的直通路径；两个子层各自往残差流上写一笔更新。在 Pre-LN 中，加法的输出直接往下传，局部直通路径就是 $x\mapsto x$。在 Post-LN 中，加法结果还要再经过归一化，反向的直通路径也要穿过归一化的雅可比。原始 Transformer 采用 Post-LN，许多后续的 Decoder-only 模型采用 Pre-LN；两者还牵涉最终归一化、学习率和初始化等配置，比较时要整套考虑。

归一化和残差各管一件事：归一化决定子层输入的尺寸，残差决定两条路径怎样相加，一个 Block 里两者同时存在。$M$ 就是[第 8 章](./activations-and-ffn.md)的前馈层，$A$ 是[第 6 章](./self-attention.md)的注意力。

## 7. 深度增加时，残差分支的尺度

上一节的“残差、无归一化”曲线说明：$L$ 层更新不断加到残差流里，即使每层输出均值接近零，方差也会累积。一个教学用的显式缩放写成

$$
x_{l+1}=x_l+\alpha F_l(\operatorname{Norm}(x_l)).
$$

$\alpha=1$ 就是不缩放。减小 $\alpha$ 会同时缩小前向更新和反向梯度，但也可能让分支学得太慢，所以它需要配合深度调参。

另一类做法只在<strong>初始化时</strong>缩小写回残差流的输出投影，前向时不再乘系数。例如 nanoGPT 对每个 Block 中注意力和 MLP 的 `c_proj.weight` 使用 `0.02 / sqrt(2 * n_layer)` 的初始标准差，这里的 2 对应每层两条残差分支。这是特定架构的经验设计，只作用在输出投影上；[第 22 章的 DeepNorm](./large-model-stability.md#deepnorm) 是另一套完整配置。[nanoGPT 源码](https://github.com/karpathy/nanoGPT/blob/master/model.py)给出了具体实现。

## 8. 动手实验：测量每一层，而不只看一条损失曲线

[initialization-and-residuals.ipynb](/tinyllm/notebooks/initialization-and-residuals) 分三步运行：

1. 对多次抽样的权重记录均值、标准差和截断范围；改变 `fan_in`，比较固定 `std` 与 Xavier/He 的输出方差，Plotly 图和本章开头那张图思路相同，只是宽度取 16、64、256 三档。
2. 让同一个输入通过一串小型残差层，对比纯堆叠、Pre-LN、Post-LN 与带显式缩放的 Pre-LN。记录每层输出的 RMS 和输入梯度范数。它和第 5 节的图思路相同，但规模更小（16 层、宽度 32），所以具体数值不同；第 5 节的图由 `scripts/tinyllm-figure-data.py` 以 32 层、宽度 64 单独生成。
3. 改变深度和随机种子重复观察。

这些实验只包含初始化时的前向和反向，没有优化器和训练数据，用来练习“怎么测”，而不是判断哪种结构在语言模型上更好。

排查深层网络时，同时记下 `loss` 是否有限、每层激活 RMS、各层参数梯度范数和输入梯度范数。数值偏大或偏小，要结合宽度、深度、目标函数、归一化和学习率一起判断；出现 `NaN` 时，先定位它第一次出现的位置。实验用 `float32` 和 CPU 是为了减少环境差异，大模型的低精度与长时间训练还需要单独验证。

<!-- real-model:start -->

## 在真实模型里

真实模型的默认初始化比本章的配方简单。下表的链接都指向 Hugging Face transformers 的固定版本 `v5.21`，精确到行。读代码时可以先跳过缓存、掩码、并行这些工程细节，只看和本章对应的那几行。

| 本章的零件 | 真实代码 | 对照要点 |
| --- | --- | --- |
| 默认初始化 | [`PreTrainedModel._init_weights`](https://github.com/huggingface/transformers/blob/v5.21/src/transformers/modeling_utils.py#L2294-L2358) | 线性层和嵌入一律用均值 0、标准差 `initializer_range` 的正态分布，不按宽度调整，也不对残差输出投影额外缩小 |
| 标准差从哪里来 | [`configuration_llama.py 第 72 行`](https://github.com/huggingface/transformers/blob/v5.21/src/transformers/models/llama/configuration_llama.py#L72) | Llama 默认 0.02；本章第 1 节的实验说明了固定 0.02 会随宽度变化 |
| 残差加法 | [`LlamaDecoderLayer.forward`](https://github.com/huggingface/transformers/blob/v5.21/src/transformers/models/llama/modeling_llama.py#L284-L313) | `hidden_states = residual + hidden_states` 出现两次，就是本章的两条残差 |

想在本机看源码，可以先 `pip install transformers`，再用 `python -m inspect transformers.models.llama.modeling_llama:LlamaMLP` 这样的命令打印出任意一个类。

<!-- real-model:end -->

## 本章结论：TinyLLM 的选择 {#tinyllm-choice}

<strong>先用宽度感知的随机初始化：</strong>普通 `nn.Linear` 的权重用 Xavier normal，token embedding 用零均值、标准差 $1/\sqrt d$ 的正态分布，偏置（若有）设为 0，RMSNorm 的缩放权重设为 1。每个 Block 有注意力和 FFN 两次残差写回；对注意力输出投影和 SwiGLU 的 `down` 投影，在 Xavier 抽样后再乘 $1/\sqrt{2L}$，其中 $L$ 是 Block 数。输出头若与 embedding 共享权重，只初始化共享张量一次。这是本课程的<strong>可测量起点</strong>：Xavier 并非专门为 SwiGLU 推导，这套配置也只是一个经得起检查的默认值。

为什么这样选？全零会让隐藏单元保持对称；所有层用同一个固定 `std` 又忽略了宽度（开头那张图）。Xavier 按输入和输出宽度给出起始尺度；Pre-RMSNorm 让每个子层看到统一尺寸的输入；残差直通路径保留梯度。粗略假设各层的两次更新相互独立时，写回分支随 $L$ 缩小可以减轻残差流方差的累积。[Pre-LN 分析](https://arxiv.org/abs/2002.04745)解释了初始化附近的梯度差异；[nanoGPT](https://github.com/karpathy/nanoGPT/blob/master/model.py)展示了按 $2L$ 缩小残差投影的另一种配方，它的基础尺度是 `std=0.02`，本课程的基础尺度是 Xavier，两者是不同的实现。

<strong>何时改选？</strong>复现某个模型时，以该模型的初始化和归一化配方为准。若初始激活 RMS、logits、各层梯度随深度明显漂移，先检查权重是否被重复初始化、输出头和残差投影是否设对、学习率是否过大，再比较固定标准差、截断正态、零初始化的残差输出或更专门的深层方案。第 7 节的前向残差系数 $\alpha$ 与这里<strong>仅在初始化时缩小输出投影</strong>是两种不同操作。

::: warning 常见误区
- **残差不是“误差”。** 残差流是一路传下去的隐藏状态，子层在它上面写更新，和训练损失无关。
- **有残差也可能梯度爆炸。** 直通路径保证梯度能传回去，但 $I+J_F$ 连乘仍会放大；第 5 节无归一化的残差网络，第 1 层梯度是最后一层的十几倍。
- **截断正态的 `std` 是截断前的参数。** 实测标准差会更小；截断也不是把超出区间的值 `clamp` 到边界。
- **He 初始化是为 ReLU 推导的。** SwiGLU 的门控乘积不满足它的假设，不能机械套用。
- **把残差输出投影设为零，和把所有权重设为零是两回事。** 前者让一个分支起点接近恒等映射，后者让整层隐藏单元永远对称。
:::

## 检查理解

1. `nn.Linear(32, 96)` 的权重形状是什么？`fan_in` 与 `fan_out` 各是多少？

   <details><summary>参考答案</summary>

   形状为 `[96, 32]`，`fan_in=32`，`fan_out=96`。

   </details>

2. 为什么把每个隐藏层的权重全设为零，与把某个残差输出投影设为零，不是同一件事？

   <details><summary>参考答案</summary>

   全零让同层隐藏单元输出和梯度都相同，永远无法分化；只把残差分支的输出投影设零，其他权重仍是随机的，分支只是在起点不写入更新，整个子层接近恒等映射。

   </details>

3. 写出一个 Pre-LN Block 的两次残差加法；哪条路径让输入可以直接走到输出？

   <details><summary>参考答案</summary>

   $u=x+A(\operatorname{Norm}_1(x))$，$y=u+M(\operatorname{Norm}_2(u))$。只经过两个加号的 $x\to u\to y$ 是直通路径，前向和反向都不经过子层和归一化。

   </details>

4. 一张“深度 32 比深度 4 的梯度更大”的图，为什么还不足以判断训练一定失败？

   <details><summary>参考答案</summary>

   它通常只测了初始化时的一次前向和反向；梯度大小还要结合宽度、归一化、学习率和优化器判断，训练是否失败要看实际训练中 loss 是否有限、是否下降。

   </details>

## 参考资料

- [PyTorch 初始化函数与 `fan` 定义](https://docs.pytorch.org/docs/stable/nn.init.html)
- [Glorot 与 Bengio：Xavier 初始化](https://proceedings.mlr.press/v9/glorot10a.html)
- [He 等：ReLU 网络初始化](https://arxiv.org/abs/1502.01852)
- [He 等：残差网络](https://arxiv.org/abs/1512.03385)
- [Vaswani 等：原始 Transformer](https://arxiv.org/abs/1706.03762)
- [Xiong 等：Pre-LN/Post-LN 分析](https://arxiv.org/abs/2002.04745)
- [nanoGPT `model.py`](https://github.com/karpathy/nanoGPT/blob/master/model.py)

下一章回答“每个子层的输入怎样保持统一尺寸”：[第 11 章：归一化](./normalization.md)。
