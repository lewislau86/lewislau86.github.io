# %% [markdown]
# # 第 18 章：数值精度与混合精度
#
# 配套教案：https://lewislau86.github.io/tinyllm/precision
#
# 从上到下运行即可（`python precision.py`）。基础数值实验只需 CPU 和 PyTorch；
# CUDA/MPS 的计时实验和 MLX 实验是可选的，环境里没有时会打印提示并跳过。
# 这个文件是本章代码的唯一来源：教案中的代码片段由 `# region 名字` / `# endregion 名字`
# 标记的区域直接引用，notebook 也由它生成（scripts/build-tinyllm-code.py）。
# 本章遵循 **What → How → Do**：先看浮点数能存什么，再看运算路径，最后比较同一模型的结果。

# %% [markdown]
# ## 0. 准备
#
# 固定随机种子，记录 PyTorch 版本和设备。不同设备/版本的最后几位可能不同；我们主要看现象和量级。

# %%
import torch
from torch import nn

torch.manual_seed(15)
print('PyTorch:', torch.__version__)
print('CUDA 可用:', torch.cuda.is_available(), 'MPS 可用:', torch.backends.mps.is_available())
print('基础数值实验在 CPU 运行；设备与 MLX 可选实验在后面')

# %% [markdown]
# ## 问题：1001 去哪儿了？
#
# 先猜下面三行的输出。

# %%
# region opening
print(torch.tensor([1000., 1001.]).to(torch.bfloat16))
print(torch.tensor([1000., 1001.]).to(torch.float16))
print(torch.tensor(300., dtype=torch.float16).square())
# endregion opening

# %% [markdown]
# 同样占 16 位，BF16 把 1000 和 1001 存成了同一个数（刻度太粗），FP16 却连 $300^2=90000$ 都存不下（范围太窄）。
# 换成 BF16 再平方：范围够了，但结果会舍入到最近的刻度。

# %%
# region bf16-square
print(torch.tensor(300., dtype=torch.bfloat16).square())  # tensor(90112., dtype=torch.bfloat16)
# endregion bf16-square

# %% [markdown]
# ## What 1. 范围和刻度是两件事
#
# `torch.finfo(dtype).eps`：1 附近相邻两个可表示数的间隔；`tiny`：最小**正规**正数，不一定是最小非零数；`max`：最大有限数。这里的 `eps` 与归一化公式的防零参数不同。

# %%
# region finfo
for dtype in (torch.float32, torch.float16, torch.bfloat16):
    info = torch.finfo(dtype)
    print(dtype, info.eps, info.tiny, info.max)
# endregion finfo

n = 1_000_000
for dtype in (torch.float32, torch.float16, torch.bfloat16):
    print(dtype, '一百万个元素的原始张量约占', n * torch.empty((), dtype=dtype).element_size() / 1e6, 'MB')

# %% [markdown]
# **读输出：**FP16/BF16 单个元素都占 2 字节，但 FP16 的 1 附近刻度更细，BF16 的可表示范围更宽。这个存储量只计算一个张量本身，不能据此推出训练模型总显存恰好减半。

# %% [markdown]
# ## What 2. 舍入：输入转换时信息可能已经丢失
#
# 先在 FP32 里创建相邻整数，再转成低精度；最后转回 FP32 只是为了容易打印，不能恢复原数。

# %%
near_1000 = torch.tensor([999., 1000., 1001., 1002., 1003.])
for dtype in (torch.float32, torch.float16, torch.bfloat16):
    stored = near_1000.to(dtype)
    print(dtype, '存储结果:', stored.float().tolist(), '可区分值数:', torch.unique(stored).numel())

# %% [markdown]
# **读输出：**若两个输入存成同一个 BF16 数，之后的 FP32 计算也无法知道它们原来不同。刻度粗细随数值大小变化，不应把 1000 附近的间隔当作所有位置的间隔。

# %% [markdown]
# ## How 3. 有限输入仍可能在运算中溢出或下溢
#
# FP16 能存下 1000，却存不下它的平方。很小的数也可能在转换或运算时变为 0。先转 FP32 再做后续运算，只有在信息仍存在时才有用。

# %%
big = torch.tensor([1000.], dtype=torch.float16)
small = torch.tensor([1e-8, 1e-7, 1e-5], dtype=torch.float32)
print('输入 1000 是否有限:', torch.isfinite(big).item())
print('FP16 平方:', big.square().item(), '是否有限:', torch.isfinite(big.square()).item())
print('先升到 FP32 再平方:', big.float().square().item())
for dtype in (torch.float16, torch.bfloat16):
    print(dtype, '小数存储后:', small.to(dtype).float().tolist())

# %% [markdown]
# **读输出：**`isfinite` 只检查是否为有限数，不能证明结果准确。`1e-8` 在某些 FP16 路径上会变成 0；BF16 的范围较宽，但并不因此拥有更多尾数位。非正规数处理可能随设备变化。

# %% [markdown]
# ## How 4. 相同的数学式，运算顺序不同
#
# 直接对大 logits 求 `exp` 会溢出；先减最大值再求指数，softmax 的数学结果不变。`torch.softmax` 是实际应调用的函数。

# %%
logits = torch.tensor([1000., 1001., 1002.])
naive = logits.exp() / logits.exp().sum()
shifted = (logits - logits.max()).exp()
stable_by_hand = shifted / shifted.sum()
print('直接 exp:', naive, '有限:', torch.isfinite(naive).all().item())
print('先减最大值:', stable_by_hand)
print('torch.softmax:', torch.softmax(logits, dim=-1))

# %% [markdown]
# **读输出：**`inf / inf` 产生 `NaN`。减最大值解决的是中间值范围问题，不会给 FP32、FP16 或 BF16 添加有效位。

# %% [markdown]
# ## Do 5. 用同一个矩阵乘法比较精度
#
# 用 FP64 结果作较高精度的**数值参照**。分别打印平均/最大绝对误差与非有限值数量；参考值接近零时，单看相对误差容易误导。这里的输入量级较温和，具体误差随设备和内核变化。

# %%
a = torch.randn(64, 64)
b = torch.randn(64, 64)
reference64 = a.double() @ b.double()
for dtype in (torch.float32, torch.float16, torch.bfloat16):
    result = a.to(dtype) @ b.to(dtype)
    diff = (result.double() - reference64).abs()
    print(dtype, '输出 dtype:', result.dtype,
          '平均绝对误差:', f'{diff.mean().item():.6g}',
          '最大绝对误差:', f'{diff.max().item():.6g}',
          '非有限值:', (~torch.isfinite(result)).sum().item())

# %% [markdown]
# **读输出：**低精度矩阵乘法通常会有更大的误差，但不能从输出 dtype 反推出内核的每一步累加精度。FP64 也不是精确实数答案。

# %% [markdown]
# ## How 5. `autocast` 的基本用法
#
# 参数保持 FP32，输入也从 FP32 开始；进入 `autocast` 区域后由框架按算子选择 dtype。

# %%
# region autocast
# model 保持 FP32 参数；输入也从 FP32 开始。
# CUDA/MPS 上先试 FP16；CPU 示例使用 BF16。
device = torch.device("cuda" if torch.cuda.is_available() else
                      "mps" if torch.backends.mps.is_available() else "cpu")
amp_dtype = torch.float16 if device.type in ("cuda", "mps") else torch.bfloat16
model = torch.nn.Sequential(torch.nn.Linear(4, 4), torch.nn.LayerNorm(4))
x = torch.randn(2, 4)
model, x = model.to(device), x.to(device)
with torch.autocast(device_type=device.type, dtype=amp_dtype):
    y = model(x)
print(y.dtype)  # 这是最终输出 dtype，不代表所有内部算子的 dtype
# endregion autocast

# %% [markdown]
# ## Do 6. 同一小模型的 FP32 与 autocast
#
# 模型权重和输入从 FP32 开始。CUDA 使用 FP16 autocast，CPU 使用 BF16 autocast；`autocast` 按算子和设备选择 dtype，不等于直接把整个模型调用 `.half()`。观察线性层、激活函数、归一化和最终输出各自的 dtype，并与 FP32 输出比较。

# %%
class TinyBlock(nn.Module):
    def __init__(self, d=32):
        super().__init__()
        self.fc1 = nn.Linear(d, 64)
        self.fc2 = nn.Linear(64, d)
        self.norm = nn.LayerNorm(d)

    def forward(self, x):
        linear = self.fc1(x)
        activated = torch.nn.functional.gelu(linear)
        projected = self.fc2(activated)
        normalized = self.norm(projected)
        return linear, activated, projected, normalized

device = torch.device('cuda' if torch.cuda.is_available() else
                      'mps' if torch.backends.mps.is_available() else 'cpu')
amp_dtype = torch.float16 if device.type in ('cuda', 'mps') else torch.bfloat16
model = TinyBlock().to(device).eval()
x = torch.randn(8, 32, device=device)
with torch.inference_mode():
    fp32_stages = model(x)
    with torch.autocast(device_type=device.type, dtype=amp_dtype):
        amp_stages = model(x)
print('设备:', device, 'autocast 目标 dtype:', amp_dtype)
print('参数存储 dtype:', next(model.parameters()).dtype, '输入 dtype:', x.dtype)
for name, plain, mixed in zip(('fc1', 'GELU', 'fc2', 'LayerNorm'), fp32_stages, amp_stages):
    print(name, 'FP32 输出:', plain.dtype, 'autocast 输出:', mixed.dtype)
print('最终输出最大绝对差:', (fp32_stages[-1] - amp_stages[-1].float()).abs().max().item())

# %% [markdown]
# **读输出：**模型参数仍是 FP32；某个阶段输出为 BF16/FP16，并不证明该算子内部每一步都用 BF16/FP16。不同后端的 autocast 策略可能不同。这个误差反映本机小模型的一次前向，不代表训练收敛质量。

# %% [markdown]
# ## Do 7. 当前 PyTorch 加速设备的速度与峰值显存（可选）
#
# CUDA 与 MPS 均可计时，并在测量前后同步。CPU 跳过设备性能测试。**MPS 的 autocast 算子覆盖与 CUDA 不同**，实验打印实际输出 dtype；若 dtype 没变，不应把两组时间解释成 FP32 对 FP16。CUDA 用 `max_memory_allocated`，MPS 用 `driver_allocated_memory` 记录测得的驱动分配量；两者统计口径不同，不能跨设备直接比较。

# %%
if device.type == 'cpu':
    print('无 CUDA/MPS：跳过加速设备的计时与显存实验。')
else:
    import time
    bench = nn.Sequential(nn.Linear(256, 512), nn.GELU(),
                          nn.Linear(512, 256), nn.LayerNorm(256)).to(device).eval()
    bench_x = torch.randn(128, 256, device=device)

    def sync_device():
        if device.type == 'cuda':
            torch.cuda.synchronize()
        else:
            torch.mps.synchronize()

    def measure(use_amp):
        def run_once():
            with torch.inference_mode(), torch.autocast(device.type, dtype=torch.float16, enabled=use_amp):
                return bench(bench_x)
        for _ in range(5):
            run_once()
        sync_device()
        if device.type == 'cuda':
            torch.cuda.reset_peak_memory_stats()
        start = time.perf_counter()
        for _ in range(30):
            output = run_once()
        sync_device()
        elapsed_ms = (time.perf_counter() - start) * 1000 / 30
        if device.type == 'cuda':
            memory_mb = torch.cuda.max_memory_allocated() / 1e6
            memory_name = '峰值已分配 MB'
        else:
            memory_mb = torch.mps.driver_allocated_memory() / 1e6
            memory_name = 'MPS 驱动已分配 MB（当前值）'
        return elapsed_ms, memory_mb, memory_name, output.dtype

    for label, enabled in [('FP32', False), ('autocast FP16', True)]:
        ms, mb, memory_name, out_dtype = measure(enabled)
        print(device.type, label, '每次前向 ms:', round(ms, 3),
              memory_name, round(mb, 2), '输出 dtype:', out_dtype)

# %% [markdown]
# **读输出：**如果 autocast 没变快，可能是模型太小、算子策略未降精度，或转换/调度开销占主导。MPS 打印的是测量结束时的驱动分配量，**不是峰值显存**；CUDA 打印峰值已分配显存。两者不能直接比较。

# %% [markdown]
# ## Do 8. MLX：Apple silicon 上的同题实验（可选）
#
# MLX 与 PyTorch MPS 是不同框架。这里用 **MLX 原生数组**复现“存储舍入、矩阵乘法误差、归一化后尺度”三个关键现象，能安装 MLX 时还测一次 MLX GPU 的前向时间。`mlx.core` 采用惰性求值，所以计时前后用 `mx.eval` 强制完成计算。无法导入 MLX 时给出安装提示，不影响前面的 PyTorch 实验。MLX 示例采用单独的随机数据，不与 PyTorch 的时间或误差作严格横向排名。

# %%
try:
    import mlx.core as mx
    import mlx.nn as mlx_nn
    mlx_available = True
    print('MLX 可用；默认设备:', mx.default_device())
except ImportError:
    mlx_available = False
    print('未安装 MLX；Apple silicon 原生 Python 可运行 pip install mlx 后重试本节。')

# %%
if mlx_available:
    mlx_values = mx.array([999., 1000., 1001., 1002., 1003.])
    for dtype in (mx.float32, mx.float16, mx.bfloat16):
        info = mx.finfo(dtype)
        stored = mlx_values.astype(dtype)
        mx.eval(stored)
        print(dtype, 'eps:', info.eps, 'max:', info.max,
              '1000 附近:', stored.tolist())

    # 只在 Apple Metal GPU 可用时做 GPU 实验；其余环境可观察默认设备。
    mlx_x = mx.array([[999., 1000., 1001., 1002.]])
    mlx_norm = mlx_nn.LayerNorm(4, affine=False)
    normalized = mlx_norm(mlx_x)
    mx.eval(normalized)
    print('MLX LayerNorm 输出:', normalized.tolist())

    mx.random.seed(15)
    mlx_a = mx.random.normal((64, 64))
    mlx_b = mx.random.normal((64, 64))
    for dtype in (mx.float32, mx.float16, mx.bfloat16):
        result = mlx_a.astype(dtype) @ mlx_b.astype(dtype)
        mx.eval(result)
        print('MLX 矩阵乘法输出 dtype:', result.dtype,
              '全部有限:', bool(mx.all(mx.isfinite(result)).item()))

# %% [markdown]
# **读输出：**MLX 也能显示 FP16/BF16 在 1000 附近的刻度差异。这里检查矩阵乘法是否有限，不把不同框架、设备或随机输入的误差数字直接当作性能排行。MLX 的原生 `LayerNorm` 与 PyTorch 的 `nn.LayerNorm` 作用相近，但两套实现的内核、默认设备和 API 不应混用。

# %%
if mlx_available and mx.device_count(mx.gpu) > 0:
    import time
    mlx_input = mx.random.normal((128, 256))
    mlx_w = mx.random.normal((256, 256))
    mx.eval(mlx_input, mlx_w)
    for dtype in (mx.float32, mx.float16):
        x_low, w_low = mlx_input.astype(dtype), mlx_w.astype(dtype)
        mx.eval(x_low, w_low)
        for _ in range(5):
            mx.eval(x_low @ w_low)
        start = time.perf_counter()
        for _ in range(30):
            mx.eval(x_low @ w_low)  # 强制求值，避免只测到提交计算图的时间
        print('MLX GPU', dtype, '每次矩阵乘法 ms:', round((time.perf_counter()-start)*1000/30, 3))
else:
    print('MLX GPU 不可用，跳过 MLX GPU 计时。')

# %% [markdown]
# **读输出：**MLX 计时采用单次矩阵乘法，与前面的 PyTorch 多层模型不同，不能比较两栏的绝对时间。MLX 的惰性求值需要 `mx.eval`；缺少它会低估实际计算时间。

# %% [markdown]
# ## 9. 思考练习与答案
#
# 1. 把 logits 改为 `[-1000,-999,-998]`，直接 `exp` 再相除会怎样？
# 2. 把矩阵乘法中的 `a` 与 `b` 都乘以 `1000`，你预期 FP16 输出是否仍全部有限？
# 3. 若 BF16 输入中 `1000` 与 `1001` 已存成相同的值，后续转回 FP32 能否恢复差异？
#
# **答案：**1. 直接 `exp` 可能全部下溢为 0，导致 `0/0 → NaN`；先减最大值仍可计算。2. 数值会显著增大，FP16 输出可能溢出；用 `torch.isfinite` 检查，结果还取决于设备与运算路径。3. 不能，丢失的信息不会因转换回来而出现。
