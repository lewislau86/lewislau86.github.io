# %% [markdown]
# # 第 14 章：优化器
#
# 配套教案：https://lewislau86.github.io/tinyllm/optimizers
#
# 从上到下运行即可（`python optimizers.py`），CPU 上几秒钟。需要 `torch` 和 `plotly`。
# 这个文件是本章代码的唯一来源：教案中的代码片段由 `# region 名字` / `# endregion 名字`
# 标记的区域直接引用，notebook 也由它生成（scripts/build-tinyllm-code.py）。
# 本章先手写一步梯度下降，再依次认识 SGD、Momentum、Adam、AdamW 的 PyTorch 接口、
# 参数组和检查点，最后用固定数据比较四种优化器。

# %%
import copy
import math

import torch

print("PyTorch", torch.__version__)

# %% [markdown]
# ## 1. 从手动更新到 `optimizer.step()`
#
# 让 `w` 学会把 `x=2` 映射到 `t=6`，理想值是 `w=3`。先猜：学习率 0.1 时，`w` 会单调逼近 3，还是在 3 两边跳？

# %%
# region manual-update
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
# endregion manual-update

# %% [markdown]
# 梯度是 `8w-24`，更新变成 `w ← (1-8η)w + 24η`。学习率 0.1、0.2、0.3 对应的系数是 0.2、-0.6、-1.4：
# 单调收敛、两边跳着收敛、越跳越远。下面各走 8 步验证。

# %%
for learning_rate in (0.1, 0.2, 0.3):
    w = torch.tensor(0.0)
    path = []
    for step in range(8):
        grad = 2 * (w * x - target) * x
        w = w - learning_rate * grad
        path.append(round(w.item(), 3))
    print(f"lr={learning_rate}:", path)

# %% [markdown]
# 真实训练交给 `torch.optim`。基本用法只有三步：清梯度、反向传播、更新参数。

# %%
# region optim-basics
model = torch.nn.Linear(1, 1)
optimizer = torch.optim.SGD(model.parameters(), lr=0.1)

prediction = model(torch.tensor([[2.0]]))
loss = (prediction - torch.tensor([[6.0]])).square().mean()
optimizer.zero_grad()  # 清除上一步留下的梯度
loss.backward()        # 计算本步梯度
optimizer.step()       # 按 SGD 规则更新参数
# endregion optim-basics
print("更新后的参数:", [round(p.item(), 4) for p in model.parameters()])

# %% [markdown]
# ## 3. Momentum：给梯度装上惯性
#
# 速度 $v_t$ 是优化器状态，保存在优化器里，不在 `model.parameters()` 中。

# %%
# region momentum
optimizer = torch.optim.SGD(
    model.parameters(),
    lr=0.01,
    momentum=0.9,
)
# endregion momentum

# %%
# region momentum-state
loss = (model(torch.tensor([[2.0]])) - torch.tensor([[6.0]])).square().mean()
optimizer.zero_grad()
loss.backward()
optimizer.step()  # 第一次 step 之后才会建立动量缓冲区

state = optimizer.state_dict()
print(state.keys())             # dict_keys(['state', 'param_groups'])
print(list(state["state"][0]))  # ['momentum_buffer']
# endregion momentum-state

# %% [markdown]
# ## 4. Adam：方向和尺度一起估计

# %%
# region adam
optimizer = torch.optim.Adam(
    model.parameters(),
    lr=3e-4,
    betas=(0.9, 0.999),
    eps=1e-8,
)
# endregion adam
print(optimizer)

# %% [markdown]
# ## 5. AdamW：权重衰减放在哪里

# %%
# region adamw
optimizer = torch.optim.AdamW(
    model.parameters(),
    lr=3e-4,
    weight_decay=0.1,
)
# endregion adamw

# %% [markdown]
# Adam 中把 L2 加到梯度，会让正则项也受到 Adam 的自适应缩放；AdamW 则把衰减直接从参数上解耦。
# 在一个标量参数上各走一步看看。具体差异会随参数、梯度和超参数变化。

# %%
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

# %% [markdown]
# ## 6. 参数组：不同参数用不同的衰减
#
# 常见规则是矩阵权重衰减，偏置和一维归一化参数不衰减。先搭一个带嵌入、LayerNorm 和输出层的小模型，再按名称和维度分组。

# %%
torch.manual_seed(0)
model = torch.nn.Sequential(
    torch.nn.Embedding(32, 16),
    torch.nn.LayerNorm(16),
    torch.nn.Linear(16, 32),
)

# region param-groups
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
# endregion param-groups

names = {id(p): name for name, p in model.named_parameters()}
print("衰减:", [names[id(p)] for p in weight_decay])
print("不衰减:", [names[id(p)] for p in no_decay])

# %%
# region check-groups
all_ids = [id(p) for group in optimizer.param_groups for p in group["params"]]
assert len(all_ids) == len(set(all_ids))
print([group["weight_decay"] for group in optimizer.param_groups])  # [0.1, 0.0]
# endregion check-groups

# %% [markdown]
# ## 7. 优化器状态与检查点
#
# 先走一步让 AdamW 建立状态，再把模型和优化器一起保存。

# %%
tokens = torch.randint(0, 32, (4, 8))
loss = torch.nn.functional.cross_entropy(model(tokens).flatten(0, 1), tokens.flatten())
optimizer.zero_grad(set_to_none=True)
loss.backward()
optimizer.step()

# region checkpoint
checkpoint = {
    "model": model.state_dict(),
    "optimizer": optimizer.state_dict(),
    "step": 1200,
}
torch.save(checkpoint, "tinyllm_step1200.pt")
# endregion checkpoint

# %% [markdown]
# 恢复时先建立相同结构和参数组的模型与优化器，再加载两份状态。

# %%
restored = torch.load("tinyllm_step1200.pt")
model.load_state_dict(restored["model"])
optimizer.load_state_dict(restored["optimizer"])
print("恢复到 step", restored["step"], "；AdamW 状态:", list(optimizer.state[weight_decay[0]]))

# %% [markdown]
# ## 9. 动手：在同一条曲线上比较四个优化器
#
# 让一个两层 tanh 小网络拟合固定的 `sin(x)`。四个优化器从同一份初始参数开始，比较才公平。

# %%
# region fixed-data
torch.manual_seed(7)
x = torch.linspace(-math.pi, math.pi, 128).unsqueeze(1)
y = torch.sin(x)
base = torch.nn.Sequential(
    torch.nn.Linear(1, 16),
    torch.nn.Tanh(),
    torch.nn.Linear(16, 1),
)
initial = copy.deepcopy(base.state_dict())
# endregion fixed-data
print(x.shape, y.shape)

# %% [markdown]
# 先看 SGD 走 5 步：顺序是清梯度、反向传播、更新参数。

# %%
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

# %% [markdown]
# 改变优化器会改变参数走法；数据、初始参数和训练步数保持不变。先猜：谁下降得最快？

# %%
# region compare
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
# endregion compare

# %% [markdown]
# 画出损失曲线。对数纵轴可以同时看早期快速下降和后期细小差异。

# %%
# region plot
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
# endregion plot

# %% [markdown]
# 最后一轮循环留下的是 AdamW。动量、平方梯度平均和步数都属于优化器状态，不在模型参数中。

# %%
for parameter, state in optimizer.state.items():
    print("参数形状:", tuple(parameter.shape), "状态:", list(state))
    break

# %% [markdown]
# ## 10. 一份 TinyLLM 配置起点
#
# 沿用第 6 节分好的两个参数列表。

# %%
# region tinyllm-config
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
# endregion tinyllm-config
print([(group["weight_decay"], len(group["params"])) for group in optimizer.param_groups])

# %% [markdown]
# ## 练习
#
# 1. 把 SGD 的学习率改成 `0.001` 和 `0.5`，观察曲线。
# 2. 把 Momentum 的 `momentum` 改为 `0.0`，它就退化成什么？
# 3. 删除 `optimizer.zero_grad()`，观察梯度为什么会累积。
# 4. 保存并恢复 `model.state_dict()` 与 `optimizer.state_dict()`，比较严格续训和只恢复模型的差异。
