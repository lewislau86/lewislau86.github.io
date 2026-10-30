---
title: "第 16 章：优化器（notebook 在线查看）"
search: false
editLink: false
prev: false
next: false
pageClass: tinyllm-course
---

<!-- 本页由 scripts/build-tinyllm-code.py 根据 notebook 自动生成，请勿手改。 -->

::: tip 这是 notebook 的只读预览
[返回教案](/tinyllm/optimizers) · [在 Colab 中运行](https://colab.research.google.com/github/lewislau86/lewislau86.github.io/blob/master/docs/public/tinyllm/notebooks/optimizers.ipynb) · <a href="/tinyllm/notebooks/optimizers.ipynb" download>下载 .ipynb</a> · <a href="/tinyllm/code/optimizers.py" download>下载 .py</a> · [在 GitHub 上查看](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/tinyllm/notebooks/optimizers.ipynb)

下面的代码和输出与 notebook 文件完全一致。想修改、运行，请用 Colab 打开或下载到本地。
:::

::: v-pre
# 第 16 章：优化器

配套教案：https://lewislau86.github.io/tinyllm/optimizers

从上到下运行即可（`python optimizers.py`），CPU 上几秒钟。需要 `torch` 和 `plotly`。
这个文件是本章代码的唯一来源：教案中的代码片段由 `# region 名字` / `# endregion 名字`
标记的区域直接引用，notebook 也由它生成（scripts/build-tinyllm-code.py）。
本章先手写一步梯度下降，再依次认识 SGD、Momentum、Adam、AdamW 的 PyTorch 接口、
参数组和检查点，最后用固定数据比较四种优化器。
:::

<p class="nb-label">In [1]</p>

```python
import copy
import math

import torch

print("PyTorch", torch.__version__)
```

```text
PyTorch 2.14.1+cpu
```

::: v-pre
## 1. 从手动更新到 `optimizer.step()`

让 `w` 学会把 `x=2` 映射到 `t=6`，理想值是 `w=3`。先猜：学习率 0.1 时，`w` 会单调逼近 3，还是在 3 两边跳？
:::

<p class="nb-label">In [2]</p>

```python
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

```text
0 2.4 36.0
1 2.88 1.44
2 2.976 0.0576
3 2.9952 0.0023
4 2.999 0.0001
5 2.9998 0.0
6 3.0 0.0
7 3.0 0.0
```

::: v-pre
梯度是 `8w-24`，更新变成 `w ← (1-8η)w + 24η`。学习率 0.1、0.2、0.3 对应的系数是 0.2、-0.6、-1.4：
单调收敛、两边跳着收敛、越跳越远。下面各走 8 步验证。
:::

<p class="nb-label">In [3]</p>

```python
for learning_rate in (0.1, 0.2, 0.3):
    w = torch.tensor(0.0)
    path = []
    for step in range(8):
        grad = 2 * (w * x - target) * x
        w = w - learning_rate * grad
        path.append(round(w.item(), 3))
    print(f"lr={learning_rate}:", path)
```

```text
lr=0.1: [2.4, 2.88, 2.976, 2.995, 2.999, 3.0, 3.0, 3.0]
lr=0.2: [4.8, 1.92, 3.648, 2.611, 3.233, 2.86, 3.084, 2.95]
lr=0.3: [7.2, -2.88, 11.232, -8.525, 19.135, -19.589, 34.624, -41.274]
```

::: v-pre
真实训练交给 `torch.optim`。基本用法只有三步：清梯度、反向传播、更新参数。
:::

<p class="nb-label">In [4]</p>

```python
model = torch.nn.Linear(1, 1)
optimizer = torch.optim.SGD(model.parameters(), lr=0.1)

prediction = model(torch.tensor([[2.0]]))
loss = (prediction - torch.tensor([[6.0]])).square().mean()
optimizer.zero_grad()  # 清除上一步留下的梯度
loss.backward()        # 计算本步梯度
optimizer.step()       # 按 SGD 规则更新参数
print("更新后的参数:", [round(p.item(), 4) for p in model.parameters()])
```

```text
更新后的参数: [1.8517, 2.2967]
```

::: v-pre
## 3. Momentum：给梯度装上惯性

速度 $v_t$ 是优化器状态，保存在优化器里，不在 `model.parameters()` 中。
:::

<p class="nb-label">In [5]</p>

```python
optimizer = torch.optim.SGD(
    model.parameters(),
    lr=0.01,
    momentum=0.9,
)
```

<p class="nb-label">In [6]</p>

```python
loss = (model(torch.tensor([[2.0]])) - torch.tensor([[6.0]])).square().mean()
optimizer.zero_grad()
loss.backward()
optimizer.step()  # 第一次 step 之后才会建立动量缓冲区

state = optimizer.state_dict()
print(state.keys())             # dict_keys(['state', 'param_groups'])
print(list(state["state"][0]))  # ['momentum_buffer']
```

```text
dict_keys(['state', 'param_groups'])
['momentum_buffer']
```

::: v-pre
## 4. Adam：方向和尺度一起估计
:::

<p class="nb-label">In [7]</p>

```python
optimizer = torch.optim.Adam(
    model.parameters(),
    lr=3e-4,
    betas=(0.9, 0.999),
    eps=1e-8,
)
print(optimizer)
```

```text
Adam (
Parameter Group 0
    amsgrad: False
    betas: (0.9, 0.999)
    capturable: False
    decoupled_weight_decay: False
    differentiable: False
    eps: 1e-08
    foreach: None
    fused: None
    lr: 0.0003
    maximize: False
    weight_decay: 0
)
```

::: v-pre
## 5. AdamW：权重衰减放在哪里
:::

<p class="nb-label">In [8]</p>

```python
optimizer = torch.optim.AdamW(
    model.parameters(),
    lr=3e-4,
    weight_decay=0.1,
)
```

::: v-pre
Adam 中把 L2 加到梯度，会让正则项也受到 Adam 的自适应缩放；AdamW 则把衰减直接从参数上解耦。
在一个标量参数上各走一步看看。具体差异会随参数、梯度和超参数变化。
:::

<p class="nb-label">In [9]</p>

```python
def one_step(kind):
    parameter = torch.nn.Parameter(torch.tensor(2.0))
    if kind == "adam_l2":
        optimizer = torch.optim.Adam([parameter], lr=0.1, weight_decay=0.1)
    else:
        optimizer = torch.optim.AdamW([parameter], lr=0.1, weight_decay=0.1)
    loss = (parameter - 5).square()
    optimizer.zero_grad(set_to_none=True)
    loss.backward()
    optimizer.step()
    return parameter.item()
print("Adam + L2:", one_step("adam_l2"))
print("AdamW:", one_step("adamw"))
```

```text
Adam + L2: 2.0999999046325684
AdamW: 2.0799999237060547
```

::: v-pre
## 6. 参数组：不同参数用不同的衰减

常见规则是矩阵权重衰减，偏置和一维归一化参数不衰减。先搭一个带嵌入、LayerNorm 和输出层的小模型，再按名称和维度分组。
:::

<p class="nb-label">In [10]</p>

```python
torch.manual_seed(0)
model = torch.nn.Sequential(
    torch.nn.Embedding(32, 16),
    torch.nn.LayerNorm(16),
    torch.nn.Linear(16, 32),
)

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

names = {id(p): name for name, p in model.named_parameters()}
print("衰减:", [names[id(p)] for p in weight_decay])
print("不衰减:", [names[id(p)] for p in no_decay])
```

```text
衰减: ['0.weight', '2.weight']
不衰减: ['1.weight', '1.bias', '2.bias']
```

<p class="nb-label">In [11]</p>

```python
all_ids = [id(p) for group in optimizer.param_groups for p in group["params"]]
assert len(all_ids) == len(set(all_ids))
print([group["weight_decay"] for group in optimizer.param_groups])  # [0.1, 0.0]
```

```text
[0.1, 0.0]
```

::: v-pre
## 7. 优化器状态与检查点

先走一步让 AdamW 建立状态，再把模型和优化器一起保存。
:::

<p class="nb-label">In [12]</p>

```python
tokens = torch.randint(0, 32, (4, 8))
loss = torch.nn.functional.cross_entropy(model(tokens).flatten(0, 1), tokens.flatten())
optimizer.zero_grad(set_to_none=True)
loss.backward()
optimizer.step()

checkpoint = {
    "model": model.state_dict(),
    "optimizer": optimizer.state_dict(),
    "step": 1200,
}
torch.save(checkpoint, "tinyllm_step1200.pt")
```

::: v-pre
恢复时先建立相同结构和参数组的模型与优化器，再加载两份状态。
:::

<p class="nb-label">In [13]</p>

```python
restored = torch.load("tinyllm_step1200.pt")
model.load_state_dict(restored["model"])
optimizer.load_state_dict(restored["optimizer"])
print("恢复到 step", restored["step"], "；AdamW 状态:", list(optimizer.state[weight_decay[0]]))
```

```text
恢复到 step 1200 ；AdamW 状态: ['step', 'exp_avg', 'exp_avg_sq']
```

::: v-pre
## 9. 动手：在同一条曲线上比较四个优化器

让一个两层 tanh 小网络拟合固定的 `sin(x)`。四个优化器从同一份初始参数开始，比较才公平。
:::

<p class="nb-label">In [14]</p>

```python
torch.manual_seed(7)
x = torch.linspace(-math.pi, math.pi, 128).unsqueeze(1)
y = torch.sin(x)
base = torch.nn.Sequential(
    torch.nn.Linear(1, 16),
    torch.nn.Tanh(),
    torch.nn.Linear(16, 1),
)
initial = copy.deepcopy(base.state_dict())
print(x.shape, y.shape)
```

```text
torch.Size([128, 1]) torch.Size([128, 1])
```

::: v-pre
先看 SGD 走 5 步：顺序是清梯度、反向传播、更新参数。
:::

<p class="nb-label">In [15]</p>

```python
model = copy.deepcopy(base)
model.load_state_dict(initial)
optimizer = torch.optim.SGD(model.parameters(), lr=0.05)
for step in range(5):
    prediction = model(x)
    loss = (prediction - y).square().mean()
    optimizer.zero_grad(set_to_none=True)
    loss.backward()
    optimizer.step()
    print(step, round(loss.item(), 6))
```

```text
0 0.735006
1 0.395198
2 0.263438
3 0.211766
4 0.19129
```

::: v-pre
改变优化器会改变参数走法；数据、初始参数和训练步数保持不变。先猜：谁下降得最快？
:::

<p class="nb-label">In [16]</p>

```python
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

```text
SGD 0.735 -> 0.025631
```

```text
Momentum 0.735 -> 0.001722
```

```text
Adam 0.735 -> 0.00695
```

```text
AdamW 0.735 -> 0.006997
```

::: v-pre
画出损失曲线。对数纵轴可以同时看早期快速下降和后期细小差异。
:::

<p class="nb-label">In [17]</p>

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

![第 17 格输出的图表（静态快照，交互版请在 Colab 或本地运行）](/tinyllm/notebooks/img/optimizers-17-1.svg)

::: v-pre
最后一轮循环留下的是 AdamW。动量、平方梯度平均和步数都属于优化器状态，不在模型参数中。
:::

<p class="nb-label">In [18]</p>

```python
for parameter, state in optimizer.state.items():
    print("参数形状:", tuple(parameter.shape), "状态:", list(state))
    break
```

```text
参数形状: (16, 1) 状态: ['step', 'exp_avg', 'exp_avg_sq']
```

::: v-pre
## 10. 一份 TinyLLM 配置起点

沿用第 6 节分好的两个参数列表。
:::

<p class="nb-label">In [19]</p>

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
print([(group["weight_decay"], len(group["params"])) for group in optimizer.param_groups])
```

```text
[(0.1, 2), (0.0, 3)]
```

::: v-pre
## 练习

1. 把 SGD 的学习率改成 `0.001` 和 `0.5`，观察曲线。
2. 把 Momentum 的 `momentum` 改为 `0.0`，它就退化成什么？
3. 删除 `optimizer.zero_grad()`，观察梯度为什么会累积。
4. 保存并恢复 `model.state_dict()` 与 `optimizer.state_dict()`，比较严格续训和只恢复模型的差异。
:::

