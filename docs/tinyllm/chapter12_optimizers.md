# Chapter 12：优化器

第 1、5 章已经讲过：模型先做前向计算得到损失，`backward()` 再把梯度写入参数的 `.grad`。但梯度只回答“当前位置往哪边走”，没有回答“每一步走多远、过去的方向要不要保留、不同参数是否应该使用不同步长”。<strong>优化器就是把梯度变成参数更新的一套规则。</strong>

本章用一个很小的回归模型，把这件事从头走一遍，再把结论接回 TinyLLM。你不需要先记住公式；先观察参数怎样变化，再回头看公式会更容易。配套实验见 <a href="/tinyllm/chapter12_Optimizers/ch12.ipynb" download>ch12.ipynb</a>，只用固定数据，CPU 即可运行。

## TinyLLM 主线怎么选

默认用 <strong>AdamW</strong>：自适应更新便于建立训练基线，解耦的 weight decay 可以单独控制。给普通矩阵权重设置衰减，给归一化缩放参数和偏置（若有）设置 `weight_decay=0`；峰值学习率与衰减系数由验证损失确定，不把下面的演示数值当固定配方。若优化器状态占用成为瓶颈，再评估 Adafactor 等节省状态的方案。不要同时在 loss 中给同一参数加 L2 项又在 AdamW 中施加衰减。

## 先看一次普通的梯度下降

假设模型只有一个参数 $w$，输入为 $x$，目标为 $t$，损失为 $L(w)$。上一章的手动更新是：

$$
w_{t+1}=w_t-\eta\,g_t,\qquad g_t=\frac{\partial L}{\partial w_t}
$$

$\eta$ 是学习率，决定步子大小；$g_t$ 是当前梯度。梯度为正，就把参数减小；梯度为负，就把参数增大。学习率太大，可能在最低点两边来回跳甚至发散；太小，虽然稳，却要走很多步。

```python
import torch

# 让 w 学会把 x=2 映射到 t=6：理想 w=3
x = torch.tensor(2.0)
target = torch.tensor(6.0)
w = torch.tensor(0.0)
learning_rate = 0.1

for step in range(8):
    prediction = w * x
    loss = (prediction - target).square()
    grad = 2 * (prediction - target) * x  # 这一行也可以由 autograd 得到
    w = w - learning_rate * grad
    print(step, round(w.item(), 4), round(loss.item(), 4))
```

这里每次都重新计算损失和梯度。真实训练还会有数百万个参数、随机小批量和复杂的计算图，所以我们通常把这部分交给 `torch.optim`。优化器的基本用法只有三步：

```python
model = torch.nn.Linear(1, 1)
optimizer = torch.optim.SGD(model.parameters(), lr=0.1)

prediction = model(torch.tensor([[2.0]]))
loss = (prediction - torch.tensor([[6.0]])).square().mean()
optimizer.zero_grad()  # 清除上一步留下的梯度
loss.backward()        # 计算本步梯度
optimizer.step()       # 按 SGD 规则更新参数
```

顺序不能颠倒：没有 `backward()`，优化器看不到新梯度；不清零，旧梯度会和新梯度相加；不调用 `step()`，参数不会改变。

## 为什么需要比 SGD 更聪明的更新

### 小批量带来的噪声

语言模型不会每次把整个语料库都送进网络，而是取一个小批量。小批量梯度是总体梯度的估计，因此不同批次的方向会有抖动。抖动不一定是坏事，它让训练可行且有时能离开不好的区域，但也会让曲线不平滑。

### 不同参数的尺度不同

嵌入表、线性层、归一化参数的梯度大小可能差很多。一个统一的学习率对某些参数太大，对另一些参数又太小。于是优化器会保存一些历史信息，给每个参数安排更合适的更新。

### 深度模型的地形并不平

在狭长的损失谷里，普通 SGD 可能左右摆动；在梯度突然变大的位置，步子又可能失控。Momentum、AdaGrad、RMSProp 和 Adam 都是在解决这些具体问题。它们不是“永远更好”的替代品，而是带有不同假设和状态的更新规则。

## Momentum：给梯度装上惯性

Momentum 保存一个速度 $v_t$，让最近几步的方向累积起来：

$$
v_t=\beta v_{t-1}+g_t,\qquad w_{t+1}=w_t-\eta v_t
$$

$β$ 越接近 1，记忆越长。连续朝同一方向的梯度会叠加，来回变化的噪声则部分抵消。PyTorch 中最常见的写法是：

```python
optimizer = torch.optim.SGD(
    model.parameters(),
    lr=0.01,
    momentum=0.9,
)
```

注意：Momentum 的速度是<strong>优化器状态</strong>，不在 `model.parameters()` 里。保存检查点时只保存模型参数而丢掉优化器状态，恢复训练后的前几步会和原来不同。

```python
state = optimizer.state_dict()
print(state.keys())  # state 和 param_groups
# state 中会出现 momentum_buffer
```

## 自适应步长：AdaGrad、RMSProp 与 Adam

### AdaGrad：给走过很多路的方向降速

AdaGrad 累加每个参数历史梯度的平方：

$$
G_t=G_{t-1}+g_t^2,\qquad
w_{t+1}=w_t-\eta\frac{g_t}{\sqrt{G_t}+\epsilon}
$$

某个方向如果一直有较大梯度，分母会变大，后续步子变小；稀疏特征得到的方向则能保留较大的步子。它的缺点也很明显：$G_t$ 只增不减，训练很久后学习率可能小到几乎不动。

### RMSProp：只记住最近的梯度尺度

RMSProp 把累加改成指数移动平均：

$$
S_t=\rho S_{t-1}+(1-\rho)g_t^2,\qquad
w_{t+1}=w_t-\eta\frac{g_t}{\sqrt{S_t}+\epsilon}
$$

旧梯度会逐渐淡出，因此不容易像 AdaGrad 那样永久降速。PyTorch 接口是 `torch.optim.RMSprop`。

### Adam：方向和尺度一起估计

Adam 同时保存梯度的一阶移动平均 $m_t$ 和平方的二阶移动平均 $v_t$：

$$
m_t=\beta_1m_{t-1}+(1-\beta_1)g_t
$$
$$
v_t=\beta_2v_{t-1}+(1-\beta_2)g_t^2
$$

由于初始状态是 0，前几步的移动平均会偏小，所以做偏差修正：

$$
\hat m_t=\frac{m_t}{1-\beta_1^t},\qquad
\hat v_t=\frac{v_t}{1-\beta_2^t}
$$

最后更新：

$$
w_{t+1}=w_t-\eta\frac{\hat m_t}{\sqrt{\hat v_t}+\epsilon}
$$

默认的 `betas=(0.9, 0.999)` 就是这两个指数平均的记忆系数。Adam 通常在训练初期比较省心，但它仍然需要调学习率，不能替代观察损失和梯度。

```python
optimizer = torch.optim.Adam(
    model.parameters(),
    lr=3e-4,
    betas=(0.9, 0.999),
    eps=1e-8,
)
```

## Adam 和 AdamW：权重衰减放在哪里

“让权重不要无限变大”可以有两种写法。第一种把 L2 惩罚加到损失：

$$
L'=L+\frac{\lambda}{2}\|w\|^2
$$

这样反向传播得到的梯度变成 $g+\lambda w$，再交给 Adam。第二种是<strong>解耦权重衰减</strong>：先按 Adam 的梯度更新，再直接把参数乘一个衰减因子：

$$
w_{t+1}=w_t-\eta\,\mathrm{AdamStep}(g_t)-\eta\lambda w_t
$$

在普通 SGD 中，这两种写法很接近；在 Adam 中，L2 项也会被 Adam 的自适应缩放，效果不再相同。AdamW 采用解耦方式，所以通常是语言模型的默认选择：

```python
optimizer = torch.optim.AdamW(
    model.parameters(),
    lr=3e-4,
    weight_decay=0.1,
)
```

`weight_decay` 不是“再调用一次正则化层”，而是优化器更新的一部分。不要同时把同一组参数手动加 L2 惩罚，又设置 `weight_decay`，否则相当于衰减两次。PyTorch 的 `AdamW` 文档给出了算法定义；本章 notebook 会在一个标量参数上把 Adam 加 L2 与 AdamW 的单步结果直接打印出来。

## Adafactor：在超大模型上节省状态内存

Adam/AdamW 为每个参数保存两份与参数同形状的移动平均。模型很大时，优化器状态可能比参数本身还占内存。Adafactor 用分解的行、列统计量近似平方梯度，在部分矩阵参数上减少状态存储；代价是实现和超参数更复杂，更新行为也与 AdamW 不同。它不是 TinyLLM 小模型的默认选择，但读大模型训练配置时会遇到。

PyTorch 核心优化器中并不总是提供 `Adafactor`；实际项目常使用 Transformers 等库的实现。使用时要核对版本、学习率规则和是否自带相对步长，不要只把类名替换成 `AdamW`。本章先把 SGD、Momentum、Adam 和 AdamW 的状态与更新关系弄清楚，再把 Adafactor 当作内存优化方案理解。

## 参数组：不一定所有参数用同一个规则

Transformer 常见的做法是：矩阵权重使用 weight decay，偏置和归一化的缩放参数不衰减。做法是把参数拆成多个 parameter group：

```python
weight_decay, no_decay = [], []
for name, parameter in model.named_parameters():
    if not parameter.requires_grad:
        continue
    if parameter.ndim == 1 or name.endswith("bias"):
        no_decay.append(parameter)
    else:
        weight_decay.append(parameter)

optimizer = torch.optim.AdamW([
    {"params": weight_decay, "weight_decay": 0.1},
    {"params": no_decay, "weight_decay": 0.0},
], lr=3e-4)
```

这里的 `parameter.ndim == 1` 是常见的工程规则，用来覆盖 LayerNorm/RMSNorm 的缩放参数；具体项目也可能采用不同约定。检查分组数量和名称，避免参数漏掉或重复：

```python
all_ids = [id(p) for group in optimizer.param_groups for p in group["params"]]
assert len(all_ids) == len(set(all_ids))
print([group["weight_decay"] for group in optimizer.param_groups])
```

## 优化器状态与检查点

模型参数描述“模型现在是什么样”，优化器状态描述“优化器记得什么”。SGD 可能只有动量缓冲区；Adam/AdamW 至少会为每个参数保存 `exp_avg`、`exp_avg_sq` 和步数。训练中断后，要恢复原来的学习轨迹，应同时保存：

```python
checkpoint = {
    "model": model.state_dict(),
    "optimizer": optimizer.state_dict(),
    "step": 1200,
}
torch.save(checkpoint, "tinyllm_step1200.pt")
```

恢复时先建立<strong>相同结构和参数组</strong>的模型与优化器，再加载两份状态。只加载模型而不加载优化器，模型可以继续前向，但 Adam 的历史尺度和动量会丢失，不能称为严格续训。

## 动手：在同一条曲线上比较四个优化器

下面的实验让一个两层小网络拟合固定的正弦数据。每个优化器从同一份初始参数开始，训练步数、批量和学习率都写在代码里。先看损失曲线，再问：谁下降得快？谁的后期更平稳？改变学习率后结论是否还成立？

```python
import copy
import math
import torch

torch.manual_seed(7)
x = torch.linspace(-math.pi, math.pi, 128).unsqueeze(1)
y = torch.sin(x)
base = torch.nn.Sequential(
    torch.nn.Linear(1, 16),
    torch.nn.Tanh(),
    torch.nn.Linear(16, 1),
)
initial = copy.deepcopy(base.state_dict())

optimizers = {
    "SGD": lambda parameters: torch.optim.SGD(parameters, lr=0.05),
    "Momentum": lambda parameters: torch.optim.SGD(parameters, lr=0.05, momentum=0.9),
    "Adam": lambda parameters: torch.optim.Adam(parameters, lr=0.01),
    "AdamW": lambda parameters: torch.optim.AdamW(parameters, lr=0.01, weight_decay=1e-3),
}
results = {}
for name, make_optimizer in optimizers.items():
    model = copy.deepcopy(base)
    model.load_state_dict(initial)
    optimizer = make_optimizer(model.parameters())
    history = []
    for step in range(300):
        prediction = model(x)
        loss = (prediction - y).square().mean()
        optimizer.zero_grad(set_to_none=True)
        loss.backward()
        optimizer.step()
        history.append(loss.item())
    results[name] = history
    print(name, round(history[0], 4), "->", round(history[-1], 6))
```

如果环境中有 `plotly`，可以画出交互式曲线：

```python
import plotly.graph_objects as go
figure = go.Figure()
for name, history in results.items():
    figure.add_trace(go.Scatter(y=history, mode="lines", name=name))
figure.update_layout(
    title="四种优化器的训练损失",
    xaxis_title="step",
    yaxis_title="mean squared error",
    yaxis_type="log",
)
figure.show()
```

这个实验不是为了宣布某个优化器永远最好。它只让你看到：优化器改变的是参数走法；公平比较必须固定数据、初始参数和训练预算。把 `Adam` 的学习率改成 `0.1`，或者把 SGD 的学习率改成 `0.001`，曲线会明显变化。

## 把小实验接回 TinyLLM

语言模型训练的一次更新通常是：

1. 从数据管线取一个 `[batch, seq]` 的 token 批次。
2. 模型计算 logits，语言模型损失比较“下一个 token”的预测。
3. `optimizer.zero_grad(set_to_none=True)` 清理旧梯度。
4. `loss.backward()` 计算所有参数的梯度。
5. 必要时做梯度裁剪，再调用 `optimizer.step()`。
6. 由学习率调度器更新下一步的学习率；这部分在 [Chapter 13](chapter13_learning_rate.md) 展开。

优化器不负责数据、不负责自动求导，也不负责决定模型结构。它只读取参数的 `.grad`、读取和更新自己的状态，然后修改参数。混合精度下还要注意 loss scaling 和梯度裁剪的顺序，见 [Chapter 15](chapter15_precision.md) 与 [Chapter 16](chapter16_gradient_stability.md)。

### 一份实际可用的 TinyLLM 配置起点

小模型可以从 AdamW 开始：学习率先用 `3e-4` 到 `1e-3` 的量级试验，`weight_decay` 从 `0.01` 或 `0.1` 比较；但这不是通用答案。真正选择要看 batch size、模型宽度、数据量、训练步数和验证损失。每次只改一个因素，并记录配置、训练步数和验证结果。

```python
# 这里假设前面的参数分组已经得到两个列表。
decay_parameters = weight_decay
no_decay_parameters = no_decay
optimizer = torch.optim.AdamW(
    [
        {"params": decay_parameters, "weight_decay": 0.1},
        {"params": no_decay_parameters, "weight_decay": 0.0},
    ],
    lr=3e-4,
    betas=(0.9, 0.95),
    eps=1e-8,
)
```

`betas=(0.9, 0.95)` 是一些语言模型配置会尝试的设置，不代表所有 TinyLLM 都应使用它。先用固定小数据过拟合一个 batch，确认训练循环正确，再扩大数据和调参；不要把“优化器没选对”和“模型或数据管线有 bug”混在一起。

## 读完后的检查

- 学习率控制当前步子的大小；Momentum 还记住过去的方向。
- Adam 为每个参数估计梯度方向和尺度，并用偏差修正启动阶段的估计。
- AdamW 把权重衰减从 Adam 的梯度变换中分离出来；它和在损失中加 L2 项不应混为一谈。
- 优化器状态是训练状态的一部分，严格续训时要和模型参数一起保存。
- 参数组允许矩阵权重、偏置和归一化参数使用不同的 weight decay。

下一章会把“每一步走多大”进一步交给学习率策略：warmup、衰减和按 step 更新的调度器。返回 [课程总目录](index.md#课程路线规划)。

本章的算法脉络参考《动手学深度学习》的[优化算法章节](https://zh.d2l.ai/chapter_optimization/index.html)，公式、示例和实验均改写为 TinyLLM 的学习场景，并以 [PyTorch 优化器文档](https://docs.pytorch.org/docs/stable/optim.html) 为 API 依据。
