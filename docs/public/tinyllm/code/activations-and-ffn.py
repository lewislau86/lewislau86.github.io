# %% [markdown]
# # 第 5 章：激活函数与门控前馈层
#
# 配套教案：https://lewislau86.github.io/tinyllm/activations-and-ffn
#
# 从上到下运行即可，CPU 上几秒钟。需要安装 `torch` 和 `plotly`（图表使用 Plotly）。
# 这个文件是本章代码的唯一来源：教案中的代码片段由 `# region 名字` / `# endregion 名字`
# 标记的区域直接引用，notebook 也由它生成（scripts/build-tinyllm-code.py）。

# %%
# region imports
import torch
from torch import nn
import torch.nn.functional as F
import plotly.graph_objects as go
# endregion imports

torch.manual_seed(7)
print('PyTorch:', torch.__version__)

# %% [markdown]
# ## 0. 前馈层的形状：只在最后一轴上放大再投回
#
# `up` 把隐藏宽度 8 放大到 32，`down` 再投回 8；每个 token 分别使用同一组参数。

# %%
# region ffn-shape
x = torch.randn(2, 3, 8)  # 2 条样本，每条 3 个 token，隐藏宽度 8
ffn = nn.Sequential(nn.Linear(8, 32), nn.GELU(), nn.Linear(32, 8))
print(ffn(x).shape)  # torch.Size([2, 3, 8])
# endregion ffn-shape

# %% [markdown]
# ## 1. 从饱和到门控：函数与导数曲线
#
# 对比 Sigmoid/Tanh 在区间两端的饱和、ReLU 负半轴的零梯度，以及 GELU/SiLU 的平滑变化。`autograd` 对每个采样点求导；ReLU 在 0 处不可导，PyTorch 采用约定的梯度。

# %%
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

# %% [markdown]
# 用几个整数点核对输出和导数：

# %%
# region activation-points
values = torch.tensor([-2.0, -1.0, 0.0, 1.0, 2.0])
for name, fn in [('Sigmoid', torch.sigmoid), ('Tanh', torch.tanh),
                 ('ReLU', F.relu), ('GELU', F.gelu), ('SiLU', F.silu)]:
    probe = values.detach().clone().requires_grad_()
    output = fn(probe)
    gradient = torch.autograd.grad(output.sum(), probe)[0]
    print(name, [round(v, 4) for v in output.tolist()], [round(v, 4) for v in gradient.tolist()])
# endregion activation-points

# %% [markdown]
# ## 2. 普通 FFN 和 SwiGLU：检查所有形状
#
# `[batch, seq, d]` 的最后一轴参与投影。两个模型都使用无偏置线性层以便准确核对权重参数公式。

# %%
class PlainFFN(nn.Module):
    def __init__(self, d, m, activation=nn.GELU()):
        super().__init__()
        self.up = nn.Linear(d, m, bias=False)
        self.activation = activation
        self.down = nn.Linear(m, d, bias=False)

    def forward(self, x):
        return self.down(self.activation(self.up(x)))

# region swiglu
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
# endregion swiglu

# 下面换成 d=12 的输入，核对两种 FFN 每一步的形状
x12 = torch.randn(2, 3, 12)
plain = PlainFFN(12, 48)
gated = SwiGLUFFN(12, 32)
print('plain up:', tuple(plain.up(x12).shape), 'output:', tuple(plain(x12).shape))
print('gate/value:', tuple(gated.gate(x12).shape), tuple(gated.value(x12).shape), 'output:', tuple(gated(x12).shape))
assert plain(x12).shape == gated(x12).shape == x12.shape

# %% [markdown]
# ## 3. 相近权重预算的比较
#
# 普通 FFN：`2dm`；SwiGLU：`3dm`。本例 `d=12`，中间宽度 48 与 32 时权重都为 1152 个。

# %%
count = lambda model: sum(p.numel() for p in model.parameters())
print('plain:', count(plain), 'expected:', 2 * 12 * 48)
print('gated:', count(gated), 'expected:', 3 * 12 * 32)
assert count(plain) == count(gated) == 1152

# %% [markdown]
# ## 4. 梯度要经过三条投影和残差路径
#
# 使用一个标量平方损失检查 `backward()` 连通性。

# %%
probe = x12.detach().clone().requires_grad_()
loss = gated(probe).square().mean()
loss.backward()
for name, parameter in gated.named_parameters():
    print(name, 'gradient norm=', float(parameter.grad.norm()))
    assert parameter.grad is not None and torch.isfinite(parameter.grad).all()
assert probe.grad is not None and torch.isfinite(probe.grad).all()


# %% [markdown]
# 把 SwiGLU 放进 Pre-Norm 残差前馈半块，再检查梯度能否传回输入。

# %%
# region prenorm-ffn
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
# endregion prenorm-ffn

block = PreNormFFN(12, 32)
probe = x12.detach().clone().requires_grad_()
block(probe).square().mean().backward()
print('Pre-RMSNorm residual input gradient norm=', float(probe.grad.norm()))
assert probe.grad is not None and torch.isfinite(probe.grad).all()

# %% [markdown]
# ## 5. 固定合成数据上的小型拟合
#
# 为了检查训练代码能运行，构造 128 个 12 维向量及固定非线性目标。两个模型权重预算相同、训练步数相同；单个随机种子的短程曲线不是架构优劣基准。

# %%
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

# %% [markdown]
# **思考**：若两个模型都取 `m=48`，参数量还能比较吗？`x + FFN(Norm(x))` 中哪条是直接路径？参见[教案的检查理解](https://lewislau86.github.io/tinyllm/activations-and-ffn#检查理解)。
