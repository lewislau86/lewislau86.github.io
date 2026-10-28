---
title: "第 7 章：激活函数与门控前馈层（notebook 在线查看）"
search: false
editLink: false
prev: false
next: false
pageClass: tinyllm-course
---

<!-- 本页由 scripts/build-tinyllm-code.py 根据 notebook 自动生成，请勿手改。 -->

::: tip 这是 notebook 的只读预览
[返回教案](/tinyllm/activations-and-ffn) · [在 Colab 中运行](https://colab.research.google.com/github/lewislau86/lewislau86.github.io/blob/master/docs/public/tinyllm/notebooks/activations-and-ffn.ipynb) · <a href="/tinyllm/notebooks/activations-and-ffn.ipynb" download>下载 .ipynb</a> · <a href="/tinyllm/code/activations-and-ffn.py" download>下载 .py</a> · [在 GitHub 上查看](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/tinyllm/notebooks/activations-and-ffn.ipynb)

下面的代码和输出与 notebook 文件完全一致。想修改、运行，请用 Colab 打开或下载到本地。
:::

::: v-pre
# 第 7 章：激活函数与门控前馈层

配套教案：https://lewislau86.github.io/tinyllm/activations-and-ffn

从上到下运行即可，CPU 上几秒钟。需要安装 `torch` 和 `plotly`（图表使用 Plotly）。
这个文件是本章代码的唯一来源：教案中的代码片段由 `# region 名字` / `# endregion 名字`
标记的区域直接引用，notebook 也由它生成（scripts/build-tinyllm-code.py）。
:::

<p class="nb-label">In [1]</p>

```python
import torch
from torch import nn
import torch.nn.functional as F
import plotly.graph_objects as go

torch.manual_seed(7)
print('PyTorch:', torch.__version__)
```

```text
PyTorch: 2.14.1+cpu
```

::: v-pre
## 0. 前馈层的形状：只在最后一轴上放大再投回

`up` 把隐藏宽度 8 放大到 32，`down` 再投回 8；每个 token 分别使用同一组参数。
:::

<p class="nb-label">In [2]</p>

```python
x = torch.randn(2, 3, 8)  # 2 条样本，每条 3 个 token，隐藏宽度 8
ffn = nn.Sequential(nn.Linear(8, 32), nn.GELU(), nn.Linear(32, 8))
print(ffn(x).shape)  # torch.Size([2, 3, 8])
```

```text
torch.Size([2, 3, 8])
```

::: v-pre
## 1. 从饱和到门控：函数与导数曲线

对比 Sigmoid/Tanh 在区间两端的饱和、ReLU 负半轴的零梯度，以及 GELU/SiLU 的平滑变化。`autograd` 对每个采样点求导；ReLU 在 0 处不可导，PyTorch 采用约定的梯度。
:::

<p class="nb-label">In [3]</p>

```python
grid = torch.linspace(-4, 4, 401)
functions = {
    'Sigmoid': torch.sigmoid,
    'Tanh': torch.tanh,
    'ReLU': F.relu,
    'GELU': F.gelu,
    'SiLU': F.silu,
}
curves = {}
for name, fn in functions.items():
    probe = grid.detach().clone().requires_grad_()
    output = fn(probe)
    derivative = torch.autograd.grad(output.sum(), probe)[0]
    curves[name] = (output.detach(), derivative.detach())
    print(name, 'grad(-1)=', round(float(derivative[150]), 4),
          'grad(4)=', round(float(derivative[-1]), 4))
for title, index in [('激活函数', 0), ('导数', 1)]:
    fig = go.Figure()
    for name, pair in curves.items():
        fig.add_trace(go.Scatter(x=grid.tolist(), y=pair[index].tolist(),
                                 mode='lines', name=name))
    fig.update_layout(title=title, xaxis_title='输入 x（无单位）',
                      yaxis_title=title + '（无单位）')
    fig.show()
```

```text
Sigmoid grad(-1)= 0.1966 grad(4)= 0.0177
Tanh grad(-1)= 0.42 grad(4)= 0.0013
ReLU grad(-1)= 0.0 grad(4)= 1.0
GELU grad(-1)= -0.0833 grad(4)= 1.0005
SiLU grad(-1)= 0.0723 grad(4)= 1.0527
```

![第 3 格输出的图表（静态快照，交互版请在 Colab 或本地运行）](/tinyllm/notebooks/img/activations-and-ffn-3-1.svg)

![第 3 格输出的图表（静态快照，交互版请在 Colab 或本地运行）](/tinyllm/notebooks/img/activations-and-ffn-3-2.svg)

::: v-pre
用几个整数点核对输出和导数：
:::

<p class="nb-label">In [4]</p>

```python
values = torch.tensor([-2.0, -1.0, 0.0, 1.0, 2.0])
for name, fn in [('Sigmoid', torch.sigmoid), ('Tanh', torch.tanh),
                 ('ReLU', F.relu), ('GELU', F.gelu), ('SiLU', F.silu)]:
    probe = values.detach().clone().requires_grad_()
    output = fn(probe)
    gradient = torch.autograd.grad(output.sum(), probe)[0]
    print(name, [round(v, 4) for v in output.tolist()], [round(v, 4) for v in gradient.tolist()])
```

```text
Sigmoid [0.1192, 0.2689, 0.5, 0.7311, 0.8808] [0.105, 0.1966, 0.25, 0.1966, 0.105]
Tanh [-0.964, -0.7616, 0.0, 0.7616, 0.964] [0.0707, 0.42, 1.0, 0.42, 0.0707]
ReLU [0.0, 0.0, 0.0, 1.0, 2.0] [0.0, 0.0, 0.0, 1.0, 1.0]
GELU [-0.0455, -0.1587, 0.0, 0.8413, 1.9545] [-0.0852, -0.0833, 0.5, 1.0833, 1.0852]
SiLU [-0.2384, -0.2689, 0.0, 0.7311, 1.7616] [-0.0908, 0.0723, 0.5, 0.9277, 1.0908]
```

::: v-pre
## 2. 普通 FFN 和 SwiGLU：检查所有形状

`[batch, seq, d]` 的最后一轴参与投影。两个模型都使用无偏置线性层以便准确核对权重参数公式。
:::

<p class="nb-label">In [5]</p>

```python
class PlainFFN(nn.Module):
    def __init__(self, d, m, activation=nn.GELU()):
        super().__init__()
        self.up = nn.Linear(d, m, bias=False)
        self.activation = activation
        self.down = nn.Linear(m, d, bias=False)

    def forward(self, x):
        return self.down(self.activation(self.up(x)))

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

# 下面换成 d=12 的输入，核对两种 FFN 每一步的形状
x12 = torch.randn(2, 3, 12)
plain = PlainFFN(12, 48)
gated = SwiGLUFFN(12, 32)
print('plain up:', tuple(plain.up(x12).shape), 'output:', tuple(plain(x12).shape))
print('gate/value:', tuple(gated.gate(x12).shape), tuple(gated.value(x12).shape), 'output:', tuple(gated(x12).shape))
assert plain(x12).shape == gated(x12).shape == x12.shape
```

```text
torch.Size([2, 3, 8])
plain up: (2, 3, 48) output: (2, 3, 12)
gate/value: (2, 3, 32) (2, 3, 32) output: (2, 3, 12)
```

::: v-pre
## 3. 相近权重预算的比较

普通 FFN：`2dm`；SwiGLU：`3dm`。本例 `d=12`，中间宽度 48 与 32 时权重都为 1152 个。
:::

<p class="nb-label">In [6]</p>

```python
count = lambda model: sum(p.numel() for p in model.parameters())
print('plain:', count(plain), 'expected:', 2 * 12 * 48)
print('gated:', count(gated), 'expected:', 3 * 12 * 32)
assert count(plain) == count(gated) == 1152
```

```text
plain: 1152 expected: 1152
gated: 1152 expected: 1152
```

::: v-pre
## 4. 梯度要经过三条投影和残差路径

使用一个标量平方损失检查 `backward()` 连通性。
:::

<p class="nb-label">In [7]</p>

```python
probe = x12.detach().clone().requires_grad_()
loss = gated(probe).square().mean()
loss.backward()
for name, parameter in gated.named_parameters():
    print(name, 'gradient norm=', float(parameter.grad.norm()))
    assert parameter.grad is not None and torch.isfinite(parameter.grad).all()
assert probe.grad is not None and torch.isfinite(probe.grad).all()
```

```text
gate.weight gradient norm= 0.05146992206573486
value.weight gradient norm= 0.05190759152173996
down.weight gradient norm= 0.0538177452981472
```

::: v-pre
把 SwiGLU 放进 Pre-Norm 残差前馈半块，再检查梯度能否传回输入。
:::

<p class="nb-label">In [8]</p>

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

block = PreNormFFN(12, 32)
probe = x12.detach().clone().requires_grad_()
block(probe).square().mean().backward()
print('Pre-RMSNorm residual input gradient norm=', float(probe.grad.norm()))
assert probe.grad is not None and torch.isfinite(probe.grad).all()
```

```text
torch.Size([2, 3, 8])
Pre-RMSNorm residual input gradient norm= 0.28766894340515137
```

::: v-pre
## 5. 固定合成数据上的小型拟合

为了检查训练代码能运行，构造 128 个 12 维向量及固定非线性目标。两个模型权重预算相同、训练步数相同；单个随机种子的短程曲线不是架构优劣基准。
:::

<p class="nb-label">In [9]</p>

```python
torch.manual_seed(21)
features = torch.randn(128, 12)
with torch.no_grad():
    target = torch.sin(features @ torch.randn(12, 12) / 3)

def fit(model, steps=60):
    optimizer = torch.optim.AdamW(model.parameters(), lr=0.01, weight_decay=0.0)
    history = []
    for _ in range(steps):
        optimizer.zero_grad(set_to_none=True)
        loss = F.mse_loss(model(features), target)
        loss.backward()
        optimizer.step()
        history.append(float(loss.detach()))
    return history

torch.manual_seed(7)
plain_loss = fit(PlainFFN(12, 48))
torch.manual_seed(7)
gated_loss = fit(SwiGLUFFN(12, 32))
print('plain first/last:', plain_loss[0], plain_loss[-1])
print('gated first/last:', gated_loss[0], gated_loss[-1])
assert plain_loss[-1] < plain_loss[0] and gated_loss[-1] < gated_loss[0]
fig = go.Figure()
fig.add_trace(go.Scatter(x=list(range(1, 61)), y=plain_loss, mode='lines', name='普通 GELU FFN'))
fig.add_trace(go.Scatter(x=list(range(1, 61)), y=gated_loss, mode='lines', name='SwiGLU FFN'))
fig.update_layout(title='单种子合成拟合演示', xaxis_title='优化步骤', yaxis_title='均方误差（无单位）')
fig.show()
```

```text
plain first/last: 0.5103849172592163 0.053135957568883896
gated first/last: 0.4679524004459381 0.0717862918972969
```

![第 9 格输出的图表（静态快照，交互版请在 Colab 或本地运行）](/tinyllm/notebooks/img/activations-and-ffn-9-1.svg)

::: v-pre
**思考**：若两个模型都取 `m=48`，参数量还能比较吗？`x + FFN(Norm(x))` 中哪条是直接路径？参见[教案的检查理解](https://lewislau86.github.io/tinyllm/activations-and-ffn#检查理解)。
:::

