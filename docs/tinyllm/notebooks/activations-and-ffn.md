---
title: "第 5 章：激活函数与门控前馈层（notebook 在线查看）"
search: false
editLink: false
prev: false
next: false
pageClass: tinyllm-course
---

<!-- 本页由 scripts/build-tinyllm-code.py 根据 notebook 自动生成，请勿手改。 -->

::: tip 这是 notebook 的只读预览
[返回教案](/tinyllm/activations-and-ffn) · [在 Colab 中运行](https://colab.research.google.com/github/lewislau86/lewislau86.github.io/blob/master/docs/public/tinyllm/notebooks/activations-and-ffn.ipynb) · <a href="/tinyllm/notebooks/activations-and-ffn.ipynb" download>下载 .ipynb</a> · [在 GitHub 上查看](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/tinyllm/notebooks/activations-and-ffn.ipynb)

下面的代码和输出与 notebook 文件完全一致。想修改、运行，请用 Colab 打开或下载到本地。这份 notebook 没有保存运行输出，运行后才能看到结果。
:::

::: v-pre
# 第 5 章：激活函数与门控前馈层

配套[教案](https://lewislau86.github.io/tinyllm/activations-and-ffn)。按顺序运行，CPU 即可。图表使用 Plotly；需要 `torch` 和 `plotly`。
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

::: v-pre
## 1. 从饱和到门控：函数与导数曲线

对比 Sigmoid/Tanh 在区间两端的饱和、ReLU 负半轴的零梯度，以及 GELU/SiLU 的平滑变化。`autograd` 对每个采样点求导；ReLU 在 0 处不可导，PyTorch 采用约定的梯度。
:::

<p class="nb-label">In [2]</p>

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

::: v-pre
## 2. 普通 FFN 和 SwiGLU：检查所有形状

`[batch, seq, d]` 的最后一轴参与投影。两个模型都使用无偏置线性层以便准确核对权重参数公式。
:::

<p class="nb-label">In [3]</p>

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
    def __init__(self, d, m):
        super().__init__()
        self.gate = nn.Linear(d, m, bias=False)
        self.value = nn.Linear(d, m, bias=False)
        self.down = nn.Linear(m, d, bias=False)

    def forward(self, x):
        return self.down(F.silu(self.gate(x)) * self.value(x))

x = torch.randn(2, 3, 12)
plain = PlainFFN(12, 48)
gated = SwiGLUFFN(12, 32)
print('plain up:', tuple(plain.up(x).shape), 'output:', tuple(plain(x).shape))
print('gate/value:', tuple(gated.gate(x).shape), tuple(gated.value(x).shape), 'output:', tuple(gated(x).shape))
assert plain(x).shape == gated(x).shape == x.shape
```

::: v-pre
## 3. 相近权重预算的比较

普通 FFN：`2dm`；SwiGLU：`3dm`。本例 `d=12`，中间宽度 48 与 32 时权重都为 1152 个。
:::

<p class="nb-label">In [4]</p>

```python
count = lambda model: sum(p.numel() for p in model.parameters())
print('plain:', count(plain), 'expected:', 2 * 12 * 48)
print('gated:', count(gated), 'expected:', 3 * 12 * 32)
assert count(plain) == count(gated) == 1152
```

::: v-pre
## 4. 梯度要经过三条投影和残差路径

使用一个标量平方损失检查 `backward()` 连通性。
:::

<p class="nb-label">In [5]</p>

```python
probe = x.detach().clone().requires_grad_()
loss = gated(probe).square().mean()
loss.backward()
for name, parameter in gated.named_parameters():
    print(name, 'gradient norm=', float(parameter.grad.norm()))
    assert parameter.grad is not None and torch.isfinite(parameter.grad).all()
assert probe.grad is not None and torch.isfinite(probe.grad).all()

class PreNormFFN(nn.Module):
    def __init__(self, d, m):
        super().__init__()
        self.norm = nn.RMSNorm(d)
        self.ffn = SwiGLUFFN(d, m)

    def forward(self, x):
        return x + self.ffn(self.norm(x))

block = PreNormFFN(12, 32)
probe = x.detach().clone().requires_grad_()
block(probe).square().mean().backward()
print('Pre-RMSNorm residual input gradient norm=', float(probe.grad.norm()))
assert probe.grad is not None and torch.isfinite(probe.grad).all()
```

::: v-pre
## 5. 固定合成数据上的小型拟合

为了检查训练代码能运行，构造 128 个 12 维向量及固定非线性目标。两个模型权重预算相同、训练步数相同；单个随机种子的短程曲线不是架构优劣基准。
:::

<p class="nb-label">In [6]</p>

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

::: v-pre
**思考**：若两个模型都取 `m=48`，参数量还能比较吗？`x + FFN(Norm(x))` 中哪条是直接路径？参见[教案的检查理解](https://lewislau86.github.io/tinyllm/activations-and-ffn#检查理解)。
:::

