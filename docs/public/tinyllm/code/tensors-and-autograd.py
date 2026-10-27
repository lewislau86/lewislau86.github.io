# %% [markdown]
# # 第 2 章：PyTorch 张量与自动求导
#
# 配套教案：https://lewislau86.github.io/tinyllm/tensors-and-autograd
#
# 从上到下运行即可，CPU 上几秒钟。只需要安装 PyTorch（MLX 可选）。
# 这个文件是本章代码的唯一来源：教案中的代码片段由 `# region 名字` / `# endregion 名字`
# 标记的区域直接引用，notebook 也由它生成（scripts/build-tinyllm-code.py）。
# 请先猜形状和数值，再看输出。核心实验固定在 CPU；末尾另测本机 CUDA/MPS 与可选 MLX。

# %% [markdown]
# ## 0. 环境与符号
#
# `batch` 是一批样本数，`seq` 是每条样本的 token 数，`hidden` 是每个 token 的特征数。固定随机种子只是让随机示例易复现，不改变以下手算结论。

# %%
import torch
from torch import nn

torch.manual_seed(7)
print("PyTorch:", torch.__version__)
print("CUDA 可用:", torch.cuda.is_available())
print("MPS 可用:", torch.backends.mps.is_available())

# %% [markdown]
# ## 1. 张量：形状、类型与索引
#
# 两句话，每句三个 token，用整数编号。形状 `[2, 3]` 读作 `[batch, seq]`。

# %%
# region token-ids
token_ids = torch.tensor([[1, 2, 3], [4, 5, 6]], dtype=torch.long)
print(token_ids.shape)  # torch.Size([2, 3])
# endregion token-ids
print("dtype:", token_ids.dtype)

# %% [markdown]
# 先预测 `hidden[0, 1, :]` 是哪 4 个数。词元 ID 用整数，隐藏状态用浮点数。

# %%
# region hidden
hidden = torch.arange(24, dtype=torch.float32).reshape(2, 3, 4)
print(hidden.shape)       # torch.Size([2, 3, 4])
print(hidden[0, 1, :])    # tensor([4., 5., 6., 7.])
# endregion hidden
print("ndim=", hidden.ndim, "dtype=", hidden.dtype, "device=", hidden.device)
assert hidden[0, 1, :].tolist() == [4., 5., 6., 7.]

# %% [markdown]
# ### `reshape` 与 `transpose` 不同
#
# `reshape` 重新安排形状；`transpose` 交换两个轴。`transpose` 后的内存布局通常不连续。`reshape` 是否复制取决于布局；要独立副本请显式 `clone()`。

# %%
# region reshape
flat = hidden.reshape(2, 12)
print(flat.shape)  # torch.Size([2, 12])
# endregion reshape
swapped = hidden.transpose(1, 2)
print("transpose:", swapped.shape)
print("transpose 连续吗:", swapped.is_contiguous(), "stride:", swapped.stride())
print("独立副本:", hidden.clone().shape)
assert flat.shape == (2, 12) and swapped.shape == (2, 4, 3)

# %% [markdown]
# ## 2. 广播：从右向左比形状
#
# `bias` 是 `[4]`，与 `[2,3,4]` 相加时，最后一轴匹配；每个 token 都加同一个偏置。

# %%
# region broadcast
bias = torch.tensor([1., 2., 3., 4.])
shifted = hidden + bias
print(shifted.shape)       # torch.Size([2, 3, 4])
print(shifted[0, 1, :])    # tensor([ 5.,  7.,  9., 11.])
# endregion broadcast
assert shifted[0, 1, :].tolist() == [5., 7., 9., 11.]

# 再用全零张量看得更清楚：每个 token 加到的都是同一个 bias
y = torch.zeros(2, 3, 4) + bias
print("zeros + bias:", y.shape, y[0, 0], y[1, 2])
assert y.shape == (2, 3, 4)
assert torch.equal(y[0, 0], bias) and torch.equal(y[1, 2], bias)

# %% [markdown]
# ## 3. 逐元素乘法、矩阵乘法与 `nn.Linear`
#
# `*` 不会求内积；`@` 使用末尾两个轴做矩阵乘法。

# %%
# region matmul
weight = torch.ones(4, 6)
out = hidden @ weight
print(out.shape)          # torch.Size([2, 3, 6])
print(out[0, 1, :])       # tensor([22., 22., 22., 22., 22., 22.])
# endregion matmul
print("逐元素乘法:", (bias * bias).shape)
assert out[0, 1, :].tolist() == [22.] * 6

# %% [markdown]
# `nn.Linear(4,6)` 存 `[6,4]` 权重，内部使用权重的转置，再加偏置。

# %%
# region linear
linear = torch.nn.Linear(4, 6)
print(linear.weight.shape)   # torch.Size([6, 4])
print(linear(hidden).shape)  # torch.Size([2, 3, 6])
# endregion linear
result = linear(hidden)
manual = hidden @ linear.weight.T + linear.bias
assert result.shape == (2, 3, 6)
assert torch.allclose(result, manual)

# %% [markdown]
# ### 注意力中的转置检查
#
# Q 的末尾是 `[query_len, head_dim]`；K 的末尾是 `[key_len, head_dim]`。只有把 K **最后两轴**交换，乘积才得到 `[query_len, key_len]`。

# %%
q = torch.randn(2, 3, 4, 5)
k = torch.randn(2, 3, 6, 5)
scores = q @ k.transpose(-2, -1)
print("Q:", q.shape, "K:", k.shape, "K 转置后:", k.transpose(-2, -1).shape)
print("注意力分数:", scores.shape)
assert scores.shape == (2, 3, 4, 6)

# %% [markdown]
# ## 4. 自动求导：先让 PyTorch 算，再手算核对
#
# $L=(wx-t)^2$，若 $w=2,x=3,t=1$，则 $L=25$，$dL/dw=2(wx-t)x=30$。`Parameter` 默认追踪梯度，`grad_fn` 显示损失来自运算图。

# %%
# region autograd
w = torch.nn.Parameter(torch.tensor(2.0))
x = torch.tensor(3.0)
target = torch.tensor(1.0)

prediction = w * x
loss = (prediction - target).square()

print(w.requires_grad)           # True：需要计算 w 的梯度
print(x.requires_grad)           # False：不需要计算输入 x 的梯度
print(w.grad)                    # None：此时还没有反向计算
print(prediction.grad_fn is not None)  # True：乘法被记录下来
print(loss.grad_fn is not None)        # True：损失也连在计算图上

loss.backward()

print(prediction.item())  # 6.0
print(loss.item())        # 25.0
print(w.grad.item())      # 30.0
# endregion autograd
print("grad_fn:", type(loss.grad_fn).__name__, "| 手算:", 2 * (2 * 3 - 1) * 3)
assert w.grad.item() == 30.0

# %% [markdown]
# ### 两个参数
#
# 再加一个可学习偏置 $b$，`backward()` 会把梯度分别交给两个参数。

# %%
# region two-params
w2 = torch.nn.Parameter(torch.tensor(2.0))
b2 = torch.nn.Parameter(torch.tensor(0.0))
prediction2 = w2 * x + b2
loss2 = (prediction2 - target).square()
loss2.backward()
print(w2.grad.item(), b2.grad.item())  # 30.0 10.0
print(x.grad)                           # None
# endregion two-params
assert (w2.grad.item(), b2.grad.item()) == (30.0, 10.0)

# %% [markdown]
# ### 手动更新一步
#
# 学习率 0.01：$w$ 从 2 变为 1.7，损失从 25 降到 16.81。

# %%
# region update
with torch.no_grad():
    w -= 0.01 * w.grad

new_loss = (w * x - target).square()
print(w.item())         # 约 1.7
print(new_loss.item())  # 约 16.81
# endregion update
assert abs(w.item() - 1.7) < 1e-6 and abs(new_loss.item() - 16.81) < 1e-4

# %% [markdown]
# ### 清空梯度后再反传
#
# 参数已经变了，新梯度对应更新后的 $w$：$2\times(1.7\times3-1)\times3=24.6$。

# %%
# region zero-grad
w.grad = None
loss = (w * x - target).square()
loss.backward()
print(w.grad.item())  # 对应更新后的 w，约为 24.6
# endregion zero-grad
assert abs(w.grad.item() - 24.6) < 1e-4

# %% [markdown]
# ### 梯度会累积
#
# 换一个新参数，在更新前连续做两次独立前向与反传，`.grad` 会从 30 变为 60。准备下一步训练前，需要清空梯度；优化器通常提供 `zero_grad(set_to_none=True)`。

# %%
w_acc = nn.Parameter(torch.tensor(2.0))
(w_acc * x - target).square().backward()
print("一次反传后:", w_acc.grad.item())
(w_acc * x - target).square().backward()
print("两次反传后:", w_acc.grad.item())
assert w_acc.grad.item() == 60.0
w_acc.grad = None
print("清空后:", w_acc.grad)

# %% [markdown]
# ### `no_grad`、`detach` 与 `eval`
#
# `no_grad` 停止记录新运算；`detach` 从旧图分离结果；`eval()` 仅切换模块行为，不关掉自动求导。

# %%
z = w * x
with torch.no_grad():
    pred = w * x
separated = z.detach()
probe = nn.Linear(1, 1)
probe.eval()
probe_out = probe(torch.ones(1, 1))
print("正常结果追踪:", z.requires_grad, "no_grad:", pred.requires_grad)
print("detach:", separated.requires_grad, "eval 后仍追踪:", probe_out.requires_grad)
assert z.requires_grad and not pred.requires_grad and not separated.requires_grad
assert probe_out.requires_grad

# %% [markdown]
# ## 5. 梯度检查：自动求导与数值差分
#
# 用 `float64` 和中心差分核对 `w=2` 时的导数。差分是近似值，容许很小误差。

# %%
w64 = torch.tensor(2.0, dtype=torch.float64, requires_grad=True)
def loss_at(v):
    return (v * 3.0 - 1.0).square()
loss_at(w64).backward()
h = 1e-6
finite_diff = (loss_at(torch.tensor(2.0 + h, dtype=torch.float64)) - loss_at(torch.tensor(2.0 - h, dtype=torch.float64))) / (2 * h)
print("手算: 30.0 | autograd:", w64.grad.item(), "| 差分:", finite_diff.item())
assert abs(w64.grad.item() - 30.0) < 1e-12
assert abs(finite_diff.item() - 30.0) < 1e-6

# %% [markdown]
# ## 6. 可用设备上的小型前向与反向
#
# 同一设备上的 `Linear` 与输入可以计算。这里逐一测试 CPU、可用的 CUDA/MPS；结果只说明这个小算子可运行，不代表所有算子兼容或性能更好。

# %%
devices = [torch.device("cpu")]
if torch.cuda.is_available():
    devices.append(torch.device("cuda"))
if torch.backends.mps.is_available():
    devices.append(torch.device("mps"))
for device in devices:
    layer = nn.Linear(4, 2).to(device)
    batch = torch.ones(2, 3, 4, device=device)
    output = layer(batch)
    output.square().mean().backward()
    print(device, "输出:", tuple(output.shape), "权重梯度:", tuple(layer.weight.grad.shape))
    assert output.shape == (2, 3, 2) and layer.weight.grad.shape == (2, 4)

# %% [markdown]
# ## 7. 可选 MLX：另一框架的函数式梯度
#
# MLX 不是 PyTorch 的 `device`。此格只在安装 MLX 的环境运行；使用 `mx.grad`，不调用 `.backward()`。未安装时会明确报告跳过。

# %%
try:
    import mlx.core as mx
except ImportError:
    print("MLX 未安装：跳过可选实验")
else:
    mlx_x = mx.array([1.0, 2.0], dtype=mx.float32)
    mlx_grad = mx.grad(lambda a: mx.sum(a * a))(mlx_x)
    mx.eval(mlx_grad)
    print("MLX 梯度:", mlx_grad)
    assert mx.allclose(mlx_grad, mx.array([2.0, 4.0]))

# %% [markdown]
# ## 回看与练习
#
# 1. 把 `hidden` 形状改为 `[2,4,3]` 时，`hidden[0,1,:]` 有几个数？
# 2. 如果 K 为 `[2,3,6,5]`，为什么不能用 `k.transpose(1,2)` 计算 QK 分数？
# 3. 两次 `backward()` 得到 60，怎样使下一次只得到 30？
#
# 参考答案：分别是 3；它交换了 head 与 seq 轴而非末尾的 `seq` 与 `head_dim`；下一次反传前令 `w.grad=None`，或用优化器的 `zero_grad(set_to_none=True)`。下一章学习参数初始化与残差路径。
