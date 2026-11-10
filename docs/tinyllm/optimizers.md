---
title: "第 16 章：优化器"
description: "梯度只说明往哪边走，优化器决定每一步怎么走：SGD、Momentum、RMSProp、Adam、AdamW、Adafactor 与参数分组。"
pageClass: tinyllm-course
---

# 第 16 章：优化器

[课程总览](./index.md) · [上一章](./language-model-loss.md) · [下一章](./learning-rate.md)

::: tip 本章学习目标
能手写 SGD、Momentum、Adam 的一步更新；用一张图解释 AdamW 与“Adam + L2 正则”的区别；为 TinyLLM 划分需要和不需要 weight decay 的参数组，并正确保存优化器状态。

**前置：** [第 2 章](./tensors-and-autograd.md)的梯度与 `backward()`；[第 1 章](./first-run.md)的训练循环。

**实践方式：** [optimizers.ipynb](/tinyllm/notebooks/optimizers)（也可以直接运行 <a href="/tinyllm/code/optimizers.py" download>optimizers.py</a>），CPU 约一分半（大部分是第 11 节训练 21 个代理模型），需要 PyTorch 和 `tokenizers`，画交互图需要 `plotly`。
:::

<TinyLLMMap active="optimizers" />

## 问题：一个学习率管不住所有方向

[第 1 章](./first-run.md)的训练循环最后一行是 `optimizer.step()`，那个 `optimizer` 是 `torch.optim.AdamW`。[第 2 章](./tensors-and-autograd.md)我们亲手走过一步：梯度是 30，学习率取 0.01，于是 $w \leftarrow 2-0.01\times30=1.7$，损失从 25 降到 16.81。既然一步更新这么简单，为什么不对每个参数都这样做，而要用一个名字复杂的 AdamW？

先看一个只有两个参数的损失 $f(a,b)=0.5\,(a^2+25\,b^2)$。它的谷底在原点，但 $b$ 方向比 $a$ 方向陡 25 倍。从 $(-4.5,\ 1.6)$ 出发，用四种规则各走 40 步：

<OptimizerRace />

先看 SGD（学习率 0.075）：它在陡的 $b$ 方向上左右折返，在平缓的 $a$ 方向上却走得很慢，40 步后停在 $(-0.20,\ 0.01)$。学习率再大，$b$ 方向会发散；再小，$a$ 方向更慢。**一个统一的步长同时对付两个尺度不同的方向，这就是普通梯度下降的难处。**

另外三条线代表两种改进思路。Momentum（学习率 0.01，$\beta=0.9$）记住过去的方向，在 $a$ 方向上越走越快，甚至冲过谷底，停在 $(0.62,\ -0.08)$；RMSProp（学习率 0.1）给每个方向单独定步长，停在 $(-0.009,\ 0.0)$；Adam（学习率 0.2）两者兼有，这次也冲过了头，停在 $(0.48,\ 0.08)$。这段动画只说明它们**怎么走**，各条线的终点取决于这里选的学习率和步数，算不上排名。

本章从 SGD 出发，依次加上“惯性”和“按参数调步长”，得到 Adam；再处理权重衰减放在哪里的问题，得到 AdamW；最后把它接回 TinyLLM 的训练循环。<strong>优化器就是把梯度变成参数更新的一套规则。</strong>

## 1. 从手动更新到 `optimizer.step()`

::: info 本章代码从哪里来
本章所有代码都在一个文件里：<a href="/tinyllm/code/optimizers.py" download>optimizers.py</a>（[在 GitHub 上查看](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/tinyllm/code/optimizers.py)）。下面的代码块都是从这个文件里直接截取的片段，所以单独复制一段可能缺少 `import` 或前面定义的变量；想自己运行，请下载完整文件，`python optimizers.py` 从头跑到尾即可。notebook 版本也由同一个文件生成，可以[在线查看](/tinyllm/notebooks/optimizers)，或[在 Colab 中直接运行](https://colab.research.google.com/github/lewislau86/lewislau86.github.io/blob/master/docs/public/tinyllm/notebooks/optimizers.ipynb)。
:::

设模型只有一个参数 $w$，损失为 $L(w)$。第 2 章的手动更新写成公式是：

$$
w_{t+1}=w_t-\eta\,g_t,\qquad g_t=\frac{\partial L}{\partial w_t}
$$

$\eta$ 是学习率，决定步子大小；$g_t$ 是当前梯度。梯度为正就把参数减小，为负就增大。下面让 $w$ 学会把 $x=2$ 映射到 $t=6$，理想值是 $w=3$。运行之前先猜：学习率 0.1 时，$w$ 会单调逼近 3，还是在 3 两边跳？

<<< @/public/tinyllm/code/optimizers.py#manual-update

答案是单调逼近。把梯度 $8w-24$ 代进去，更新变成 $w \leftarrow 0.2\,w+2.4$：每一步离 3 的距离缩小到原来的 0.2 倍。学习率改成 0.2，系数变成 $-0.6$，$w$ 会在 3 两边跳着收敛；改成 0.3，系数是 $-1.4$，越跳越远。

真实训练有数百万个参数、随机小批量和复杂的计算图，这部分交给 `torch.optim`。基本用法只有三步：

<<< @/public/tinyllm/code/optimizers.py#optim-basics

三步的顺序是固定的：`backward()` 写入新梯度，`step()` 读取它来改参数，`zero_grad()` 在下一步开始前清掉旧梯度，否则新旧梯度会相加。

## 2. SGD 在语言模型里遇到的三件事

开头那张图里的狭长谷只是其中一件。训练语言模型时，三种情况同时存在：

- **小批量带来噪声。** 每步只取一个小批量，算出的梯度是总体梯度的估计，相邻两步的方向会抖动。抖动让训练可行，有时还能帮助离开不好的区域，但也让曲线不平滑。
- **不同参数的尺度不同。** 嵌入表、线性层、归一化参数的梯度大小可能差很多，统一的学习率对一些参数偏大，对另一些偏小。
- **地形不平。** 在狭长的谷里 SGD 左右摆动；在梯度突然变大的位置，步子又可能失控。

Momentum、AdaGrad、RMSProp 和 Adam 分别针对其中一部分问题，每一种都带着自己的假设和需要保存的状态。下面逐个加上去。

## 3. Momentum：给梯度装上惯性

Momentum 保存一个速度 $v_t$，把最近几步的方向累积起来：

$$
v_t=\beta v_{t-1}+g_t,\qquad w_{t+1}=w_t-\eta v_t
$$

$\beta$ 越接近 1，记忆越长。连续朝同一方向的梯度会叠加，来回变化的分量则部分抵消。回到开头的图：$a$ 方向的梯度一直指向原点，速度越积越大；$b$ 方向的梯度来回变号，互相抵消。代价是惯性也会把参数带过谷底。

<<< @/public/tinyllm/code/optimizers.py#momentum

速度 $v_t$ 是<strong>优化器状态</strong>，保存在优化器里，`model.parameters()` 里没有它：

<<< @/public/tinyllm/code/optimizers.py#momentum-state

第 7 节讲检查点时会用到这一点。

## 4. 自适应步长：AdaGrad、RMSProp 与 Adam

Momentum 解决的是“方向”，下面三种方法解决“步长”：给每个参数按它自己的梯度大小分配步长。

### AdaGrad：给走过很多路的方向降速

AdaGrad 累加每个参数历史梯度的平方：

$$
G_t=G_{t-1}+g_t^2,\qquad
w_{t+1}=w_t-\eta\frac{g_t}{\sqrt{G_t}+\epsilon}
$$

某个方向一直有较大梯度，分母就变大，后续步子变小；很少得到梯度的稀疏特征则保留较大的步子。缺点是 $G_t$ 只增不减，训练很久后步长会小到几乎不动。

### RMSProp：只记住最近的梯度尺度

RMSProp 把累加改成指数移动平均：

$$
S_t=\rho S_{t-1}+(1-\rho)g_t^2,\qquad
w_{t+1}=w_t-\eta\frac{g_t}{\sqrt{S_t}+\epsilon}
$$

旧梯度逐渐淡出，步长随最近的梯度尺度上下调整。开头图里 RMSProp 几乎直达原点，正是因为陡的 $b$ 方向被除以一个大数，缓的 $a$ 方向被除以一个小数，两个方向的实际步长被拉到相近的量级。PyTorch 接口是 `torch.optim.RMSprop`。

### Adam：方向和尺度一起估计

Adam 把 Momentum 和 RMSProp 合在一起：同时保存梯度的一阶移动平均 $m_t$ 和平方的二阶移动平均 $v_t$：

$$
m_t=\beta_1m_{t-1}+(1-\beta_1)g_t
$$
$$
v_t=\beta_2v_{t-1}+(1-\beta_2)g_t^2
$$

两者初值都是 0，前几步的平均会偏小，所以做偏差修正：

$$
\hat m_t=\frac{m_t}{1-\beta_1^t},\qquad
\hat v_t=\frac{v_t}{1-\beta_2^t}
$$

最后更新：

$$
w_{t+1}=w_t-\eta\frac{\hat m_t}{\sqrt{\hat v_t}+\epsilon}
$$

默认的 `betas=(0.9, 0.999)` 就是这两个指数平均的记忆系数。Adam 在训练初期通常比较省心，学习率仍然要调，损失和梯度仍然要看。

![AdamW 一步的数据流：梯度同时更新 m（平均方向）和 v（平均大小），偏差修正后用 m 除以根号 v 得到每个方向各自归一的步子，乘学习率后减掉，权重衰减直接作用在参数上；下方是每个参数 16 字节的内存账](/tinyllm/figures/adam-step.svg)

怎么读这张图：从左上的梯度出发，分成两路记忆：$m$ 记方向，$v$ 记大小。它们在除法那一步汇合，每个参数的步子都按自己的 $\sqrt{\hat v}$ 归一，所以不同方向可以走不同大小的步。右边红框是第 5 节要讲的 AdamW：衰减不经过 $m$、$v$，直接作用在参数上。下面的内存账说明了为什么优化器状态要占显存的大头，第 7 节和[第 21 章](./training-loop.md)会用到。

<<< @/public/tinyllm/code/optimizers.py#adam

## 5. AdamW：权重衰减放在哪里

“让权重别无限变大”有两种写法。第一种把 L2 惩罚加到损失上：

$$
L'=L+\frac{\lambda}{2}\|w\|^2
$$

反向传播得到的梯度变成 $g+\lambda w$，再交给 Adam。第二种是<strong>解耦权重衰减</strong>：梯度只来自原损失，Adam 更新之后，再单独把参数往 0 拉一点：

$$
w_{t+1}=w_t-\eta\,\mathrm{AdamStep}(g_t)-\eta\lambda w_t
$$

![左：Adam + L2 先把 λw 加进梯度，再一起更新 m、v，衰减项也被除以根号 v；右：AdamW 只用原损失的梯度更新 m、v，衰减项 ηλw 绕过自适应缩放，直接作用在参数上](/tinyllm/figures/adamw-vs-l2.svg)

读图时跟着 $\lambda w$ 这一项走。左边（Adam + L2）它先混进梯度 $g=\nabla L+\lambda w$，然后和梯度一起进入 $m$、$v$，最后被除以 $\sqrt{v}$：梯度一直很大的参数，衰减反而被压小。右边（AdamW）梯度只有 $\nabla L$，衰减 $\eta\lambda w$ 绕过 $m$、$v$，对每个参数按同样的比例生效。在普通 SGD 中两种写法很接近；在 Adam 中它们的效果不同。AdamW 采用右边的方式，是语言模型常用的默认选择：

<<< @/public/tinyllm/code/optimizers.py#adamw

`weight_decay` 是优化器更新的一部分。[PyTorch AdamW 文档](https://docs.pytorch.org/docs/stable/generated/torch.optim.AdamW.html)给出了完整算法；本章 notebook 会在一个标量参数上把 Adam + L2 与 AdamW 的单步结果直接打印出来。

## 6. 参数组：不同参数用不同的衰减

Transformer 常见的做法是：矩阵权重使用 weight decay，偏置和归一化的缩放参数不衰减。实现方式是把参数拆成多个 parameter group：

<<< @/public/tinyllm/code/optimizers.py#param-groups

`parameter.ndim == 1` 是常见的工程规则，用来覆盖 LayerNorm/RMSNorm 的缩放参数（[第 11 章](./normalization.md)的 $\gamma$）；具体项目也可能采用别的约定。建好之后检查一遍，确认参数没有漏掉或重复：

<<< @/public/tinyllm/code/optimizers.py#check-groups

## 7. 优化器状态与检查点

模型参数描述“模型现在是什么样”，优化器状态描述“优化器记得什么”。SGD 带 Momentum 时有动量缓冲区；Adam/AdamW 为每个参数保存 `exp_avg`（即 $m$）、`exp_avg_sq`（即 $v$）和步数。训练中断后要沿原来的轨迹继续，就把两者一起保存：

<<< @/public/tinyllm/code/optimizers.py#checkpoint

恢复时先建立<strong>相同结构和参数组</strong>的模型与优化器，再加载两份状态。只加载模型时，模型照样能前向，但 Adam 的动量和历史尺度都从 0 重新开始，前几步的更新会和中断前不同。

## 8. Adafactor：在超大模型上节省状态内存

Adam/AdamW 为每个参数保存两份同形状的移动平均，优化器状态是参数本身的两倍。模型很大时，这部分内存可能成为瓶颈。Adafactor 用分解的行、列统计量近似矩阵参数的平方梯度，减少状态存储；代价是实现和超参数更复杂，更新行为也与 AdamW 不同。读大模型训练配置时会遇到它。

实际项目常使用 Transformers 等库的 Adafactor 实现。换用时要核对版本、学习率规则以及是否自带相对步长，整套配置一起调整。

## 9. 动手：在同一条曲线上比较四个优化器

下面让一个两层 tanh 小网络拟合固定的正弦数据。四个优化器从同一份初始参数开始，训练步数、批量和学习率都写在代码里。运行之前先猜：谁下降得最快？AdamW 和 Adam 的曲线会差多少？

<<< @/public/tinyllm/code/optimizers.py#fixed-data
<<< @/public/tinyllm/code/optimizers.py#compare

![同一初始化下 300 步的训练损失（对数坐标）：四条曲线都从 0.735 开始，SGD 降到 0.0256，Momentum 降到 0.0017，Adam 与 AdamW 都降到 0.0070，两条曲线几乎重合](/tinyllm/figures/optimizer-curves.svg)

四条曲线都从 0.735 出发。这一次运行里，SGD 300 步后到 0.0256；Momentum 最低，到 0.0017；Adam 和 AdamW 都到 0.0070，曲线几乎重合，因为 `weight_decay=1e-3` 在 300 步里对参数的影响很小。这组数字只属于这组学习率和步数：把 Adam 的学习率改成 `0.1`，或把 SGD 的学习率改成 `0.001`，曲线会明显变化。<strong>公平比较优化器，要固定数据、初始参数和训练预算，并为每个优化器分别调学习率。</strong>

如果环境中有 `plotly`，可以画出交互式曲线：

<<< @/public/tinyllm/code/optimizers.py#plot

## 10. 优化器在训练循环里的位置

语言模型训练的一次更新通常是：

1. 从数据管线取一个 `[batch, seq]` 的 token 批次。
2. 模型计算 logits，语言模型损失比较“下一个 token”的预测。
3. `optimizer.zero_grad(set_to_none=True)` 清理旧梯度。
4. `loss.backward()` 计算所有参数的梯度。
5. 必要时做梯度裁剪，再调用 `optimizer.step()`。
6. 由学习率调度器更新下一步的学习率；这部分在 [第 17 章](learning-rate.md) 展开。

优化器在这个流程里的职责很窄：读取参数的 `.grad`，读取并更新自己的状态，然后修改参数。数据、自动求导和模型结构都由别的部分负责。混合精度下还要注意 loss scaling 和梯度裁剪的顺序，见 [第 19 章](precision.md) 与 [第 20 章](gradient-stability.md)。

### 一份 TinyLLM 配置起点

小模型可以从 AdamW 开始：学习率在 `1e-3` 到 `1e-2` 之间按 3 倍左右的间隔扫几个点（第 12 章的基线用 `3e-3`，[第 17 章](./learning-rate.md)的代理模型峰值取 `1e-2`）；大模型常见的 `3e-4` 量级是在更宽、更深的网络上调出来的，宽度变了要重扫（[第 25 章](./large-model-stability.md)的 μP 讲怎样迁移）。`weight_decay` 比较 `0.01` 和 `0.1`。最终取值由 batch size、模型宽度、数据量、训练步数和验证损失决定。每次只改一个因素，并记录配置、训练步数和验证结果。

<<< @/public/tinyllm/code/optimizers.py#tinyllm-config

`betas=(0.9, 0.999)` 是 PyTorch 的默认值，第 12 章的基线就用它；`(0.9, 0.95)` 是一些大模型配置会尝试的设置，可以作为一个候选。调参前先用固定小数据过拟合一个 batch，确认训练循环正确，再扩大数据；这样“优化器选得不好”和“模型或数据管线有 bug”这两类问题就能分开排查。

## 11. 接回 TinyLLM：在代理模型上比较

第 9 节的正弦曲线只能说明“每个优化器要单独调学习率”。真正关心的是在语言模型上谁更好。下面换成[第 17 章](./learning-rate.md)的代理模型（词表 1024、宽度 64、2 层），模型代码、数据划分和评估口径都从[第 12 章](./tinyllm-model.md)原样复制；所有对照用同一组预先排好的 batch，随机种子只决定初始参数；学习率固定不变、不加调度，训练 240 步，梯度裁剪到 1.0。

<<< @/public/tinyllm/code/optimizers.py#proxy-run

先用种子 0 给每个优化器扫 3 个学习率。SGD 的学习率和 Adam 不在一个量级：Adam 的步长已经按 $\sqrt{\hat v}$ 归一过，SGD 的步长直接正比于梯度。

<<< @/public/tinyllm/code/optimizers.py#proxy-sweep

```text
SGD+Momentum   lr=0.1    5.274  lr=0.3    5.118  lr=1      5.187
Adam           lr=0.001  5.078  lr=0.003  4.803  lr=0.01   4.967
AdamW          lr=0.001  5.074  lr=0.003  4.796  lr=0.01   4.954
```

三个优化器的最好学习率都在扫描范围的中间，说明范围是够的。每个取自己最好的学习率，再换两个种子：

<<< @/public/tinyllm/code/optimizers.py#proxy-seeds

```text
SGD+Momentum  lr=0.3    3 个种子 5.118 5.123 5.072  平均 5.104
Adam          lr=0.003  3 个种子 4.803 4.814 4.812  平均 4.810
AdamW         lr=0.003  3 个种子 4.796 4.814 4.807  平均 4.806
```

**Adam 类比 SGD 好得多**：调好学习率以后，平均差 0.3，3 个种子的范围离得很远。语言模型里各参数的梯度大小差别很大（第 2 节），一个全局学习率照顾不过来，这正是自适应步长的用武之地。**Adam 和 AdamW 在这里打平**：4.810 对 4.806，范围重叠。weight decay 0.1、240 步，衰减对参数的累计影响很小，第 18 章会看到它在训练更久、数据更少时才起作用。

最后看第 5、6 节的两件事：weight decay 放在哪里，以及哪些参数衰减。先在 AdamW 最好的学习率 3e-3 上比，再在 1e-2 上比一次：

<<< @/public/tinyllm/code/optimizers.py#proxy-decay

```text
lr=0.003  AdamW        4.796 4.814 4.807  平均 4.806
lr=0.003  AdamW（全部衰减）  4.812 4.819 4.806  平均 4.812
lr=0.003  Adam+L2      6.235 6.220 6.349  平均 6.268
lr=0.01   AdamW        4.954 4.859 5.026  平均 4.946
lr=0.01   AdamW（全部衰减）  4.889 4.835 4.917  平均 4.880
lr=0.01   Adam+L2      6.196 6.204 6.194  平均 6.198
```

**同样写 `weight_decay=0.1`，Adam+L2 坏到 6.2 以上**，接近训练刚开始的水平。原因就是第 5 节那张图：L2 项 $0.1\,w$ 加进梯度以后，要和梯度一起除以 $\sqrt{\hat v}$。对梯度本来就很小的参数（比如很少出现的 token 的嵌入行），这一项占了大头，除下来每一步都差不多是“朝 0 走一个学习率那么远”，而 AdamW 每步只衰减 $\eta\lambda w$：学习率 3e-3、大小 0.1 的权重每步约 3e-5，两者能差上百倍。所以 Adam+L2 的系数和 AdamW 的系数不能直接对应，要用 Adam+L2 就得重新调一个小得多的系数。

**分组衰减和全部衰减的差别在噪声以内**：3e-3 时 4.806 对 4.812，1e-2 时全部衰减平均反而低一点（4.880 对 4.946），但 3 个种子的范围重叠。RMSNorm 的缩放参数只有几百个，衰不衰减在这个尺度上看不出影响。本章仍然按惯例把它们放进不衰减的组：归一化的缩放参数本来就该在 1 附近，把它往 0 拉没有道理；这个选择在这里没有被实验证明更好，也没有被证明更差。

这组实验的边界：代理模型、固定学习率、240 步。换成第 17 章的学习率调度、训练更久或模型更大，数值会变；“每个优化器单独调学习率”“Adam+L2 和 AdamW 的系数不能互换”这两条结论不依赖这些细节。

<!-- real-model:start -->

## 在真实模型里

用 transformers 的 Trainer 训练时，优化器在这里创建。下表的链接都指向 Hugging Face transformers 的固定版本 `v5.21`，精确到行。读代码时可以先跳过缓存、掩码、并行这些工程细节，只看和本章对应的那几行。

| 本章的零件 | 真实代码 | 对照要点 |
| --- | --- | --- |
| 创建优化器 | [`Trainer.create_optimizer`](https://github.com/huggingface/transformers/blob/v5.21/src/transformers/trainer.py#L1256-L1342) | 默认 AdamW；参数分成“衰减”和“不衰减”两组 |
| 哪些参数不做权重衰减 | [`Trainer.get_decay_parameter_names`](https://github.com/huggingface/transformers/blob/v5.21/src/transformers/trainer.py#L1405-L1415) | 名字里带 `bias`、`norm` 的参数不衰减，和本章 AdamW 一节的参数分组一致 |

想在本机看源码，可以先 `pip install transformers`，再用 `python -m inspect transformers.models.llama.modeling_llama:LlamaMLP` 这样的命令打印出任意一个类。

<!-- real-model:end -->

## 本章结论：TinyLLM 的选择 {#tinyllm-choice}

**默认用 AdamW。**

理由：自适应更新便于建立训练基线，解耦的 weight decay 可以单独控制。第 11 节的代理模型上（3 个种子），调好学习率以后 AdamW 平均 4.806、Adam 4.810，SGD+Momentum 只有 5.104；同样写 `weight_decay=0.1`，Adam+L2 坏到 6.268，两种写法的系数不能互换。普通矩阵权重设置衰减，归一化缩放参数和偏置（若有）设 `weight_decay=0`；峰值学习率与衰减系数由验证损失确定，上面的数值只是起点。权重衰减只在 AdamW 里设置一次。

什么时候改：优化器状态的内存占用成为瓶颈时，再评估 Adafactor 等节省状态的方案。

::: warning 常见误区
- **Adam 不是“免调参”。** 它对学习率没那么敏感，但学习率、`betas`、`eps` 仍然影响结果，损失曲线仍然要看。
- **Adam + L2 不等于 AdamW。** 在 Adam 里，加进损失的 L2 项会被 $\sqrt{v}$ 缩放；AdamW 的衰减绕过这一步。
- **别把同一参数衰减两次。** 已经在 AdamW 里设了 `weight_decay`，就不要再往损失里手动加同一组参数的 L2 项。
- **只存模型参数不算严格续训。** Adam 的 `exp_avg`、`exp_avg_sq` 和步数也是训练状态，要和模型一起保存、一起加载。
- **一次小实验不能给优化器排名。** 开头的轨迹图和动手实验的曲线，都随学习率和步数改变。
- **Adafactor 不能只换类名。** 它的学习率规则和相对步长设置与 AdamW 不同，要整套核对。
:::

## 检查理解

1. 开头的狭长谷里，为什么 SGD 很难选出一个合适的学习率？

   <details><summary>参考答案</summary>

   $b$ 方向比 $a$ 方向陡 25 倍：学习率大到让 $a$ 方向走得快时，$b$ 方向会来回折返甚至发散；小到让 $b$ 方向稳定时，$a$ 方向又走得很慢。

   </details>

2. Momentum 和 RMSProp 分别给 SGD 加了什么？Adam 和它们是什么关系？

   <details><summary>参考答案</summary>

   Momentum 记住过去的方向（一阶移动平均），RMSProp 按每个参数最近的梯度尺度调整步长（二阶移动平均）。Adam 同时保存两者，并对启动阶段做偏差修正。

   </details>

3. Adam + L2 和 AdamW 的区别在哪一步？

   <details><summary>参考答案</summary>

   Adam + L2 把 $\lambda w$ 加进梯度，它随后被除以 $\sqrt{v}$；AdamW 的梯度只来自原损失，衰减 $\eta\lambda w$ 在自适应缩放之外直接作用于参数。

   </details>

4. 训练中断后只加载了 `model.state_dict()`，继续训练会有什么不同？

   <details><summary>参考答案</summary>

   模型能正常前向，但 Adam 的 $m$、$v$ 和步数都丢了，从 0 重新累积，偏差修正也从头开始，前几步的更新与中断前的轨迹不同。

   </details>

5. 为什么 RMSNorm 的 $\gamma$ 和偏置通常放进 `weight_decay=0` 的参数组？

   <details><summary>参考答案</summary>

   它们是一维的缩放或平移参数，作用是调整尺度和偏移，往 0 拉会改变归一化后的标准尺寸；衰减主要用于矩阵权重。常用 `ndim == 1` 或名字以 `bias` 结尾来识别。

   </details>

## 参考资料

- 《动手学深度学习》[优化算法章节](https://zh.d2l.ai/chapter_optimization/index.html)：本章的算法脉络参考于此，公式、示例和实验均改写为 TinyLLM 的学习场景
- [PyTorch 优化器文档 `torch.optim`](https://docs.pytorch.org/docs/stable/optim.html)：本章的 API 依据
- [PyTorch AdamW](https://docs.pytorch.org/docs/stable/generated/torch.optim.AdamW.html)
- [Adam: A Method for Stochastic Optimization，Kingma 与 Ba，2014](https://arxiv.org/abs/1412.6980)
- [Decoupled Weight Decay Regularization（AdamW），Loshchilov 与 Hutter，2017](https://arxiv.org/abs/1711.05101)
- [Adafactor，Shazeer 与 Stern，2018](https://arxiv.org/abs/1804.04235)

下一章会把“每一步走多大”进一步交给学习率策略：warmup、衰减和按 step 更新的调度器：[第 17 章：学习率调度](./learning-rate.md)。
