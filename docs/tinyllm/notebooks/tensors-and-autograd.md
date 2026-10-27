---
title: "第 2 章：PyTorch 张量与自动求导（notebook 在线查看）"
search: false
editLink: false
prev: false
next: false
pageClass: tinyllm-course
---

<!-- 本页由 scripts/build-tinyllm-code.py 根据 notebook 自动生成，请勿手改。 -->

::: tip 这是 notebook 的只读预览
[返回教案](/tinyllm/tensors-and-autograd) · [在 Colab 中运行](https://colab.research.google.com/github/lewislau86/lewislau86.github.io/blob/master/docs/public/tinyllm/notebooks/tensors-and-autograd.ipynb) · <a href="/tinyllm/notebooks/tensors-and-autograd.ipynb" download>下载 .ipynb</a> · [在 GitHub 上查看](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/tinyllm/notebooks/tensors-and-autograd.ipynb)

下面的代码和输出与 notebook 文件完全一致。想修改、运行，请用 Colab 打开或下载到本地。
:::

::: v-pre
# 第 2 章：PyTorch 张量与自动求导

配套[教案](https://lewislau86.github.io/tinyllm/tensors-and-autograd)。请从上到下运行，先猜形状和数值，再看输出。核心实验固定在 CPU；末尾另测本机 CUDA/MPS 与可选 MLX。
:::

::: v-pre
## 0. 环境与符号

`batch` 是一批样本数，`seq` 是每条样本的 token 数，`hidden` 是每个 token 的特征数。固定随机种子只是让随机示例易复现，不改变以下手算结论。
:::

<p class="nb-label">In [1]</p>

```python
import torch
from torch import nn

torch.manual_seed(7)
print("PyTorch:", torch.__version__)
print("CUDA 可用:", torch.cuda.is_available())
print("MPS 可用:", torch.backends.mps.is_available())
```

```text
PyTorch: 2.11.0
CUDA 可用: False
MPS 可用: True
```

::: v-pre
## 1. 张量：形状、类型与索引

先预测 `hidden[0, 1, :]` 是哪 4 个数。词元 ID 用整数，隐藏状态用浮点数。
:::

<p class="nb-label">In [2]</p>

```python
token_ids = torch.tensor([[1, 2, 3], [4, 5, 6]], dtype=torch.long)
hidden = torch.arange(24, dtype=torch.float32).reshape(2, 3, 4)
print("token_ids:", token_ids.shape, token_ids.dtype)
print("hidden:", hidden.shape, "ndim=", hidden.ndim, "device=", hidden.device)
print("第 1 个样本的第 2 个 token:", hidden[0, 1, :])
assert hidden[0, 1, :].tolist() == [4., 5., 6., 7.]
```

```text
token_ids: torch.Size([2, 3]) torch.int64
hidden: torch.Size([2, 3, 4]) ndim= 3 device= cpu
第 1 个样本的第 2 个 token: tensor([4., 5., 6., 7.])
```

::: v-pre
### `reshape` 与 `transpose` 不同

`reshape` 重新安排形状；`transpose` 交换两个轴。`transpose` 后的内存布局通常不连续。`reshape` 是否复制取决于布局；要独立副本请显式 `clone()`。
:::

<p class="nb-label">In [3]</p>

```python
flat = hidden.reshape(2, 12)
swapped = hidden.transpose(1, 2)
print("reshape:", flat.shape, "transpose:", swapped.shape)
print("transpose 连续吗:", swapped.is_contiguous(), "stride:", swapped.stride())
print("独立副本:", hidden.clone().shape)
assert flat.shape == (2, 12) and swapped.shape == (2, 4, 3)
```

```text
reshape: torch.Size([2, 12]) transpose: torch.Size([2, 4, 3])
transpose 连续吗: False stride: (12, 1, 4)
独立副本: torch.Size([2, 3, 4])
```

::: v-pre
## 2. 广播：从右向左比形状

`bias` 是 `[4]`，与 `[2,3,4]` 相加时，最后一轴匹配；每个 token 都加同一个偏置。
:::

<p class="nb-label">In [4]</p>

```python
x = torch.zeros(2, 3, 4)
bias = torch.tensor([1., 2., 3., 4.])
y = x + bias
print("x + bias:", y.shape, y[0, 0], y[1, 2])
assert y.shape == (2, 3, 4)
assert torch.equal(y[0, 0], bias) and torch.equal(y[1, 2], bias)
```

```text
x + bias: torch.Size([2, 3, 4]) tensor([1., 2., 3., 4.]) tensor([1., 2., 3., 4.])
```

::: v-pre
## 3. 逐元素乘法、矩阵乘法与 `nn.Linear`

`*` 不会求内积；`@` 使用末尾两个轴做矩阵乘法。`nn.Linear(4,6)` 存 `[6,4]` 权重，内部使用权重的转置。
:::

<p class="nb-label">In [5]</p>

```python
weight = torch.ones(4, 6)
print("逐元素乘法:", (bias * bias).shape)
print("矩阵乘法:", (y @ weight).shape)
linear = nn.Linear(in_features=4, out_features=6, bias=True)
result = linear(y)
manual = y @ linear.weight.T + linear.bias
print("Linear 权重:", linear.weight.shape, "输出:", result.shape)
assert result.shape == (2, 3, 6)
assert torch.allclose(result, manual)
```

```text
逐元素乘法: torch.Size([4])
矩阵乘法: torch.Size([2, 3, 6])
Linear 权重: torch.Size([6, 4]) 输出: torch.Size([2, 3, 6])
```

::: v-pre
### 注意力中的转置检查

Q 的末尾是 `[query_len, head_dim]`；K 的末尾是 `[key_len, head_dim]`。只有把 K **最后两轴**交换，乘积才得到 `[query_len, key_len]`。
:::

<p class="nb-label">In [6]</p>

```python
q = torch.randn(2, 3, 4, 5)
k = torch.randn(2, 3, 6, 5)
scores = q @ k.transpose(-2, -1)
print("Q:", q.shape, "K:", k.shape, "K 转置后:", k.transpose(-2, -1).shape)
print("注意力分数:", scores.shape)
assert scores.shape == (2, 3, 4, 6)
```

```text
Q: torch.Size([2, 3, 4, 5]) K: torch.Size([2, 3, 6, 5]) K 转置后: torch.Size([2, 3, 5, 6])
注意力分数: torch.Size([2, 3, 4, 6])
```

::: v-pre
## 4. 自动求导：手算后再反传

$L=(wx-t)^2$，若 $w=2,x=3,t=1$，则 $L=25$，$dL/dw=2(wx-t)x=30$。`Parameter` 默认追踪梯度，`grad_fn` 显示损失来自运算图。
:::

<p class="nb-label">In [7]</p>

```python
w = nn.Parameter(torch.tensor(2.0))
x_scalar = torch.tensor(3.0)
target = torch.tensor(1.0)
loss = (w * x_scalar - target).square()
print("loss:", loss.item(), "grad_fn:", type(loss.grad_fn).__name__)
loss.backward()
print("自动求导:", w.grad.item(), "手算:", 2 * (2 * 3 - 1) * 3)
assert w.grad.item() == 30.0
```

```text
loss: 25.0 grad_fn: PowBackward0
自动求导: 30.0 手算: 30
```

::: v-pre
### 梯度会累积

重新前向计算同一损失并反传，`.grad` 会从 30 变为 60。准备下一步训练前，需要清空梯度；优化器通常提供 `zero_grad(set_to_none=True)`。
:::

<p class="nb-label">In [8]</p>

```python
second_loss = (w * x_scalar - target).square()
second_loss.backward()
print("两次反传后:", w.grad.item())
assert w.grad.item() == 60.0
w.grad = None
print("清空后:", w.grad)
```

```text
两次反传后: 60.0
清空后: None
```

::: v-pre
### `no_grad`、`detach` 与 `eval`

`no_grad` 停止记录新运算；`detach` 从旧图分离结果；`eval()` 仅切换模块行为，不关掉自动求导。
:::

<p class="nb-label">In [9]</p>

```python
z = w * x_scalar
with torch.no_grad():
    pred = w * x_scalar
separated = z.detach()
probe = nn.Linear(1, 1)
probe.eval()
probe_out = probe(torch.ones(1, 1))
print("正常结果追踪:", z.requires_grad, "no_grad:", pred.requires_grad)
print("detach:", separated.requires_grad, "eval 后仍追踪:", probe_out.requires_grad)
assert z.requires_grad and not pred.requires_grad and not separated.requires_grad
assert probe_out.requires_grad
```

```text
正常结果追踪: True no_grad: False
detach: False eval 后仍追踪: True
```

::: v-pre
## 5. 梯度检查：自动求导与数值差分

用 `float64` 和中心差分核对 `w=2` 时的导数。差分是近似值，容许很小误差。
:::

<p class="nb-label">In [10]</p>

```python
w64 = torch.tensor(2.0, dtype=torch.float64, requires_grad=True)
def loss_at(v):
    return (v * 3.0 - 1.0).square()
loss_at(w64).backward()
h = 1e-6
finite_diff = (loss_at(torch.tensor(2.0 + h, dtype=torch.float64)) - loss_at(torch.tensor(2.0 - h, dtype=torch.float64))) / (2 * h)
print("手算: 30.0 | autograd:", w64.grad.item(), "| 差分:", finite_diff.item())
assert abs(w64.grad.item() - 30.0) < 1e-12
assert abs(finite_diff.item() - 30.0) < 1e-6
```

```text
手算: 30.0 | autograd: 30.0 | 差分: 30.000000000640625
```

::: v-pre
## 6. 可用设备上的小型前向与反向

同一设备上的 `Linear` 与输入可以计算。这里逐一测试 CPU、可用的 CUDA/MPS；结果只说明这个小算子可运行，不代表所有算子兼容或性能更好。
:::

<p class="nb-label">In [11]</p>

```python
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
```

```text
cpu 输出: (2, 3, 2) 权重梯度: (2, 4)
```

```text
mps 输出: (2, 3, 2) 权重梯度: (2, 4)
```

::: v-pre
## 7. 可选 MLX：另一框架的函数式梯度

MLX 不是 PyTorch 的 `device`。此格只在安装 MLX 的环境运行；使用 `mx.grad`，不调用 `.backward()`。未安装时会明确报告跳过。
:::

<p class="nb-label">In [12]</p>

```python
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
```

```text
MLX 未安装：跳过可选实验
```

::: v-pre
## 回看与练习

1. 把 `hidden` 形状改为 `[2,4,3]` 时，`hidden[0,1,:]` 有几个数？
2. 如果 K 为 `[2,3,6,5]`，为什么不能用 `k.transpose(1,2)` 计算 QK 分数？
3. 两次 `backward()` 得到 60，怎样使下一次只得到 30？

参考答案：分别是 3；它交换了 head 与 seq 轴而非末尾的 `seq` 与 `head_dim`；下一次反传前令 `w.grad=None`，或用优化器的 `zero_grad(set_to_none=True)`。下一章学习参数初始化与残差路径。
:::

