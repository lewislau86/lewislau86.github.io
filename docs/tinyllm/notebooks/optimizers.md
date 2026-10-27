---
title: "第 14 章：优化器（notebook 在线查看）"
search: false
editLink: false
prev: false
next: false
pageClass: tinyllm-course
---

<!-- 本页由 scripts/build-tinyllm-code.py 根据 notebook 自动生成，请勿手改。 -->

::: tip 这是 notebook 的只读预览
[返回教案](/tinyllm/optimizers) · [在 Colab 中运行](https://colab.research.google.com/github/lewislau86/lewislau86.github.io/blob/master/docs/public/tinyllm/notebooks/optimizers.ipynb) · <a href="/tinyllm/notebooks/optimizers.ipynb" download>下载 .ipynb</a> · [在 GitHub 上查看](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/tinyllm/notebooks/optimizers.ipynb)

下面的代码和输出与 notebook 文件完全一致。想修改、运行，请用 Colab 打开或下载到本地。
:::

::: v-pre
# 第 14 章：优化器

本 notebook 用固定数据比较 SGD、Momentum、Adam 和 AdamW，并检查优化器状态、参数组以及 AdamW 与 L2 惩罚的区别。请从上到下运行。
:::

::: v-pre
## 0. 环境与固定数据

我们让一个两层网络拟合 `sin(x)`。所有优化器从同一份初始参数开始，比较才公平。
:::

<p class="nb-label">In [1]</p>

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
print(x.shape, y.shape)
```

```text
torch.Size([128, 1]) torch.Size([128, 1])
```

::: v-pre
## 1. 先看一步 SGD

优化器的顺序是：清梯度、反向传播、更新参数。
:::

<p class="nb-label">In [2]</p>

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
## 2. 比较四种优化器

改变优化器会改变参数走法；数据、初始参数和训练步数保持不变。
:::

<p class="nb-label">In [3]</p>

```python
optimizers = {
    "SGD": lambda p: torch.optim.SGD(p, lr=0.05),
    "Momentum": lambda p: torch.optim.SGD(p, lr=0.05, momentum=0.9),
    "Adam": lambda p: torch.optim.Adam(p, lr=0.01),
    "AdamW": lambda p: torch.optim.AdamW(p, lr=0.01, weight_decay=1e-3),
}
results = {}
for name, make_optimizer in optimizers.items():
    model = copy.deepcopy(base)
    model.load_state_dict(initial)
    optimizer = make_optimizer(model.parameters())
    history = []
    for _ in range(300):
        loss = (model(x) - y).square().mean()
        optimizer.zero_grad(set_to_none=True)
        loss.backward()
        optimizer.step()
        history.append(loss.item())
    results[name] = history
    print(name, round(history[0], 4), "->", round(history[-1], 6))
```

```text
SGD 0.735 -> 0.025631
Momentum 0.735 -> 0.001722
Adam 0.735 -> 0.00695
AdamW 0.735 -> 0.006997
```

::: v-pre
如果安装了 `plotly`，再画出损失曲线。对数纵轴可以同时看早期快速下降和后期细小差异。
:::

<p class="nb-label">In [4]</p>

```python
# 用 CDN 加载 plotly.js，避免把数 MB 的脚本嵌进 notebook。
try:
    import plotly.graph_objects as go
    from IPython.display import HTML, display
    figure = go.Figure()
    for name, history in results.items():
        figure.add_trace(go.Scatter(y=history, mode="lines", name=name))
    figure.update_layout(
        title="四种优化器的训练损失",
        xaxis_title="step",
        yaxis_title="mean squared error",
        yaxis_type="log",
    )
    display(HTML(figure.to_html(include_plotlyjs="cdn", full_html=False)))
except ImportError:
    print("未安装 plotly，跳过绘图。")
```

> 这里是一张交互式图表，网页预览无法显示，请在 Colab 或本地运行查看。

::: v-pre
## 3. 看看 Adam 保存了什么

动量、平方梯度平均和步数都属于优化器状态，不在模型参数中。
:::

<p class="nb-label">In [5]</p>

```python
model = copy.deepcopy(base)
optimizer = torch.optim.AdamW(model.parameters(), lr=0.01, weight_decay=1e-3)
loss = (model(x) - y).square().mean()
optimizer.zero_grad(set_to_none=True)
loss.backward()
optimizer.step()
for parameter, state in optimizer.state.items():
    print("参数形状:", tuple(parameter.shape), "状态:", list(state))
    break
```

```text
参数形状: (16, 1) 状态: ['step', 'exp_avg', 'exp_avg_sq']
```

::: v-pre
## 4. 参数组：归一化和偏置不衰减

常见规则是矩阵权重衰减，偏置和一维归一化参数不衰减。这里用模型名称和维度建立分组。
:::

<p class="nb-label">In [6]</p>

```python
decay, no_decay = [], []
for name, parameter in model.named_parameters():
    if parameter.ndim == 1 or name.endswith("bias"):
        no_decay.append((name, parameter))
    else:
        decay.append((name, parameter))
optimizer = torch.optim.AdamW([
    {"params": [p for _, p in decay], "weight_decay": 0.1},
    {"params": [p for _, p in no_decay], "weight_decay": 0.0},
], lr=1e-3)
print("衰减:", [name for name, _ in decay])
print("不衰减:", [name for name, _ in no_decay])
all_ids = [id(p) for group in optimizer.param_groups for p in group["params"]]
assert len(all_ids) == len(set(all_ids))
```

```text
衰减: ['0.weight', '2.weight']
不衰减: ['0.bias', '2.bias']
```

::: v-pre
## 5. Adam 加 L2 和 AdamW 的单步差别

Adam 中把 L2 加到梯度，会让正则项也受到 Adam 的自适应缩放；AdamW 则把衰减直接从参数上解耦。具体差异会随参数、梯度和超参数变化。
:::

<p class="nb-label">In [7]</p>

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
## 6. 练习

1. 把 SGD 的学习率改成 `0.001` 和 `0.5`，观察曲线。
2. 把 Momentum 的 `momentum` 改为 `0.0`，它就退化成什么？
3. 删除 `optimizer.zero_grad()`，观察梯度为什么会累积。
4. 保存并恢复 `model.state_dict()` 与 `optimizer.state_dict()`，比较严格续训和只恢复模型的差异。
:::

