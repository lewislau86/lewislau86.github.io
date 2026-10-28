---
title: "第 10 章：初始化与残差路径（notebook 在线查看）"
search: false
editLink: false
prev: false
next: false
pageClass: tinyllm-course
---

<!-- 本页由 scripts/build-tinyllm-code.py 根据 notebook 自动生成，请勿手改。 -->

::: tip 这是 notebook 的只读预览
[返回教案](/tinyllm/initialization-and-residuals) · [在 Colab 中运行](https://colab.research.google.com/github/lewislau86/lewislau86.github.io/blob/master/docs/public/tinyllm/notebooks/initialization-and-residuals.ipynb) · <a href="/tinyllm/notebooks/initialization-and-residuals.ipynb" download>下载 .ipynb</a> · <a href="/tinyllm/code/initialization-and-residuals.py" download>下载 .py</a> · [在 GitHub 上查看](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/tinyllm/notebooks/initialization-and-residuals.ipynb)

下面的代码和输出与 notebook 文件完全一致。想修改、运行，请用 Colab 打开或下载到本地。
:::

::: v-pre
# 第 10 章：初始化与残差路径

配套教案：https://lewislau86.github.io/tinyllm/initialization-and-residuals

从上到下运行即可，CPU 上几秒钟。需要安装 PyTorch 和 Plotly（画图）。
这个文件是本章代码的唯一来源：教案中的代码片段由 `# region 名字` / `# endregion 名字`
标记的区域直接引用，notebook 也由它生成（scripts/build-tinyllm-code.py）。
随机种子只让本次演示易复现，不能代替多次试验。
:::

<p class="nb-label">In [1]</p>

```python
import math
import torch
from torch import nn
import plotly.graph_objects as go

torch.manual_seed(7)
print('PyTorch:', torch.__version__)
```

```text
PyTorch: 2.14.1+cpu
```

::: v-pre
## 1. 检查权重形状与初始化分布

先预测 `nn.Linear(64,128)` 的权重形状，再用 Xavier 重设权重。截断正态的 `std` 是截断前分布的参数；观察实测值。
:::

<p class="nb-label">In [2]</p>

```python
torch.manual_seed(7)
linear = nn.Linear(64, 128)
print(linear.weight.shape)  # torch.Size([128, 64])：fan_in=64，fan_out=128

with torch.no_grad():
    nn.init.xavier_normal_(linear.weight)
    nn.init.zeros_(linear.bias)

weights = torch.empty(100_000)
nn.init.trunc_normal_(weights, mean=0.0, std=1.0, a=-2.0, b=2.0)
print(weights.min().item(), weights.max().item(), weights.std().item())
assert tuple(linear.weight.shape) == (128, 64)
assert weights.min() >= -2 and weights.max() <= 2 and weights.std() < 1
print('Xavier 后权重标准差:', linear.weight.std().item(), ' 理论值:', (2 / (64 + 128)) ** 0.5)
```

```text
torch.Size([128, 64])
-1.9999624490737915 1.999965786933899 0.8809995055198669
Xavier 后权重标准差: 0.1019958034157753  理论值: 0.10206207261596575
```

::: v-pre
## 2. 比较固定正态、Xavier 和 He

固定输入为单位方差，宽度依次为 16、64、256。表和图记录激活函数之前的线性层输出标准差；He 在等宽时接近根号 2 是预期现象，因为这里还未经过 ReLU。这不代表完整 Transformer。
:::

<p class="nb-label">In [3]</p>

```python
widths = [16, 64, 256]
methods = ['fixed 0.1', 'Xavier', 'He/ReLU']
rows = []
for d in widths:
    x = torch.randn(4096, d)
    for name in methods:
        layer = nn.Linear(d, d, bias=False)
        with torch.no_grad():
            if name == 'fixed 0.1':
                nn.init.normal_(layer.weight, std=0.1)
            elif name == 'Xavier':
                nn.init.xavier_normal_(layer.weight)
            else:
                nn.init.kaiming_normal_(layer.weight, mode='fan_in', nonlinearity='relu')
            weight_std = float(layer.weight.std())
            out_std = float(layer(x).std())
            rows.append((d, name, weight_std, out_std))
for row in rows:
    print('width=%3d  %-10s weight_std=%.3f  output_std=%.3f' % row)
assert all(math.isfinite(row[3]) for row in rows)
```

```text
width= 16  fixed 0.1  weight_std=0.091  output_std=0.368
width= 16  Xavier     weight_std=0.273  output_std=1.096
width= 16  He/ReLU    weight_std=0.359  output_std=1.440
width= 64  fixed 0.1  weight_std=0.099  output_std=0.790
width= 64  Xavier     weight_std=0.125  output_std=0.998
width= 64  He/ReLU    weight_std=0.177  output_std=1.422
width=256  fixed 0.1  weight_std=0.100  output_std=1.599
width=256  Xavier     weight_std=0.063  output_std=1.001
width=256  He/ReLU    weight_std=0.088  output_std=1.407
```

<p class="nb-label">In [4]</p>

```python
fig = go.Figure()
for name in methods:
    chosen = [r for r in rows if r[1] == name]
    fig.add_trace(go.Scatter(x=[r[0] for r in chosen], y=[r[3] for r in chosen], mode='lines+markers', name=name))
fig.update_layout(title='初始化时线性层输出的标准差', xaxis_title='输入/输出宽度 d', yaxis_title='输出标准差（无单位）')
fig.show()
```

![第 4 格输出的图表（静态快照，交互版请在 Colab 或本地运行）](/tinyllm/notebooks/img/initialization-and-residuals-4-1.svg)

::: v-pre
## 3. 残差的局部梯度

`F(x)=0.1x` 时，纯分支导数是 0.1，加上直接路径后是 1.1。
:::

<p class="nb-label">In [5]</p>

```python
x = torch.tensor(2.0, requires_grad=True)
y = x + 0.1 * x
y.backward()
print(y.item(), x.grad.item())  # 约 2.2 和 1.1（float32 有舍入误差）
assert abs(float(x.grad) - 1.1) < 1e-6
```

```text
2.200000047683716 1.100000023841858
```

::: v-pre
## 4. 多层路径：记录激活和梯度

同宽线性子层分别构成纯堆叠、Pre-LN、Post-LN 和缩放的 Pre-LN。每层随机权重重新生成，所以曲线只可看数量级与趋势；不训练参数。`h.grad` 是该层输出在最终平方损失下的梯度。
:::

<p class="nb-label">In [6]</p>

```python
def trace_stack(kind, depth=16, width=32, seed=7):
    torch.manual_seed(seed)
    layers = nn.ModuleList([nn.Linear(width, width, bias=False) for _ in range(depth)])
    norms = nn.ModuleList([nn.LayerNorm(width) for _ in range(depth)])
    for layer in layers:
        nn.init.xavier_normal_(layer.weight)
    x = torch.randn(8, width, requires_grad=True)
    h = x
    states = [h]
    for layer, norm in zip(layers, norms):
        if kind == 'plain':
            h = layer(h)
        elif kind == 'pre':
            h = h + layer(norm(h))
        elif kind == 'post':
            h = norm(h + layer(h))
        elif kind == 'scaled-pre':
            h = h + layer(norm(h)) / math.sqrt(depth)
        else:
            raise ValueError(kind)
        h.retain_grad()
        states.append(h)
    target = torch.linspace(-1, 1, width).expand_as(h)
    (h - target).square().mean().backward()
    rms = lambda t: float(t.square().mean().sqrt())
    return [rms(s.detach()) for s in states], [rms(s.grad) for s in states]

kinds = ['plain', 'pre', 'post', 'scaled-pre']
traces = {kind: trace_stack(kind) for kind in kinds}
for kind, (activation, gradient) in traces.items():
    print(kind, 'last activation RMS=', round(activation[-1], 4), 'input gradient RMS=', round(gradient[0], 6))
    assert all(math.isfinite(v) for v in activation + gradient)
```

```text
plain last activation RMS= 0.8442 input gradient RMS= 0.019154
pre last activation RMS= 4.6482 input gradient RMS= 0.239465
post last activation RMS= 1.0 input gradient RMS= 0.004591
scaled-pre last activation RMS= 1.4457 input gradient RMS= 0.017322
```

<p class="nb-label">In [7]</p>

```python
for metric, idx in [('激活 RMS', 0), ('梯度 RMS', 1)]:
    fig = go.Figure()
    for kind in kinds:
        fig.add_trace(go.Scatter(x=list(range(len(traces[kind][idx]))), y=traces[kind][idx], mode='lines+markers', name=kind))
    fig.update_layout(title=metric + ' 随深度的变化（随机初始化）', xaxis_title='层数（0 为输入）', yaxis_title=metric + '（无单位）')
    fig.show()
```

![第 7 格输出的图表（静态快照，交互版请在 Colab 或本地运行）](/tinyllm/notebooks/img/initialization-and-residuals-7-1.svg)

![第 7 格输出的图表（静态快照，交互版请在 Colab 或本地运行）](/tinyllm/notebooks/img/initialization-and-residuals-7-2.svg)

::: v-pre
## 5. 改深度和种子

改变 `depth` 与 `seed`，看单条曲线是否稳定。由于损失是对固定目标的均方误差，梯度大小还受最终激活大小影响；不能直接把曲线当作训练好坏。
:::

<p class="nb-label">In [8]</p>

```python
for depth in [4, 16, 32]:
    for seed in [7, 11, 19]:
        a, g = trace_stack('scaled-pre', depth=depth, seed=seed)
        print('depth=%2d seed=%2d final_RMS=%.3f input_grad_RMS=%.5f' % (depth, seed, a[-1], g[0]))
```

```text
depth= 4 seed= 7 final_RMS=1.387 input_grad_RMS=0.01559
depth= 4 seed=11 final_RMS=1.385 input_grad_RMS=0.01647
depth= 4 seed=19 final_RMS=1.463 input_grad_RMS=0.01789
```

```text
depth=16 seed= 7 final_RMS=1.446 input_grad_RMS=0.01732
depth=16 seed=11 final_RMS=1.340 input_grad_RMS=0.01626
depth=16 seed=19 final_RMS=1.402 input_grad_RMS=0.01604
depth=32 seed= 7 final_RMS=1.447 input_grad_RMS=0.01659
depth=32 seed=11 final_RMS=1.423 input_grad_RMS=0.01570
depth=32 seed=19 final_RMS=1.313 input_grad_RMS=0.01696
```

::: v-pre
**思考**：如果把 `scaled-pre` 的系数改成 1，会怎样？如果把所有隐藏层权重设成零，它和仅把残差输出投影设零有什么区别？参见[教案的检查理解](https://lewislau86.github.io/tinyllm/initialization-and-residuals#检查理解)。
:::

