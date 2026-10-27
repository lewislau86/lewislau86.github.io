---
title: "第 4 章 · LLM 归一化：PyTorch 数据实验（notebook 在线查看）"
search: false
editLink: false
prev: false
next: false
pageClass: tinyllm-course
---

<!-- 本页由 scripts/build-tinyllm-code.py 根据 notebook 自动生成，请勿手改。 -->

::: tip 这是 notebook 的只读预览
[返回教案](/tinyllm/normalization) · [在 Colab 中运行](https://colab.research.google.com/github/lewislau86/lewislau86.github.io/blob/master/docs/public/tinyllm/notebooks/normalization.ipynb) · <a href="/tinyllm/notebooks/normalization.ipynb" download>下载 .ipynb</a> · [在 GitHub 上查看](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/tinyllm/notebooks/normalization.ipynb)

下面的代码和输出与 notebook 文件完全一致。想修改、运行，请用 Colab 打开或下载到本地。
:::

::: v-pre
# 第 4 章 · LLM 归一化：PyTorch 数据实验

本 notebook 与 [本章教案](https://lewislau86.github.io/tinyllm/normalization) 的第 1–5 节一一对应。读者应先知道张量的形状、最后一维和矩阵乘法；不需要训练模型。运行环境需要 **PyTorch（本例在 2.11.0 验证）** 和 Jupyter。按顺序执行所有单元格。

**学习目标**：观察同一组数据在 LayerNorm、RMSNorm、ScaleNorm 前后的均值/RMS/L2；观察 QK Norm 如何改变注意力分数；理解 DeepNorm 的残差缩放为何不能等同于完整算法。

本实验用固定数据，便于手算与核对。每个代码单元后面有“读输出”的说明。
:::

::: v-pre
## 0. 准备数据与统计工具

输入形状为 `[batch=1, seq_len=4, hidden_size=4]`。四行分别是普通向量、整体加 10 的向量、含负数的向量、全零向量。归一化统计量应沿最后一维计算，也就是每个 token 单独算。
:::

<p class="nb-label">In [1]</p>

```python
import torch
from torch import nn
from torch.nn import functional as F

torch.set_printoptions(precision=3, sci_mode=False)
x = torch.tensor([[[1., 2., 3., 4.],
                   [11., 12., 13., 14.],
                   [-4., -2., 0., 2.],
                   [0., 0., 0., 0.]]])
d = x.shape[-1]

def summarize(name, t):
    print(name)
    print(t.detach())
    print('mean:', t.mean(dim=-1).detach())
    print('RMS: ', t.square().mean(dim=-1).sqrt().detach())
    print('L2:  ', t.norm(p=2, dim=-1).detach())

print('PyTorch:', torch.__version__, '| shape:', tuple(x.shape))
summarize('原始输入', x)
```

```text
PyTorch: 2.11.0 | shape: (1, 4, 4)
原始输入
tensor([[[ 1.,  2.,  3.,  4.],
         [11., 12., 13., 14.],
         [-4., -2.,  0.,  2.],
         [ 0.,  0.,  0.,  0.]]])
mean: tensor([[ 2.500, 12.500, -1.000,  0.000]])
RMS:  tensor([[ 2.739, 12.550,  2.449,  0.000]])
L2:   tensor([[ 5.477, 25.100,  4.899,  0.000]])
```

::: v-pre
**读输出：**前两行均值分别为 2.5 和 12.5，但元素间距相同。接下来观察“减均值”是否消除整体加 10 的影响。全零行可检查除零保护。`mean(dim=-1)`、`square().mean(dim=-1).sqrt()` 和 `norm(p=2, dim=-1)` 分别得到均值、均方根和 L2 长度。
:::

::: v-pre
## 1. LayerNorm：减均值，再按标准差缩放

对应 教案 的 **1. LayerNorm**。`nn.LayerNorm(normalized_shape=d, eps=1e-5)` 在最后 `d` 维中归一化；这里 `d` 是整数，因此只处理最后一维。默认 `elementwise_affine=True, bias=True`，会创建形状为 `[d]` 的 `weight` 和 `bias`，初值分别为 1 和 0。`eps` 加在方差上，防止除零。
:::

<p class="nb-label">In [2]</p>

```python
ln = nn.LayerNorm(normalized_shape=d, eps=1e-5)
y_ln = ln(x)
summarize('LayerNorm 输出', y_ln)
print('可学习参数:', [(name, tuple(p.shape)) for name, p in ln.named_parameters()])
print('前两行相同:', torch.allclose(y_ln[0, 0], y_ln[0, 1], atol=1e-5))
```

```text
LayerNorm 输出
tensor([[[-1.342, -0.447,  0.447,  1.342],
         [-1.342, -0.447,  0.447,  1.342],
         [-1.342, -0.447,  0.447,  1.342],
         [ 0.000,  0.000,  0.000,  0.000]]])
mean: tensor([[0., 0., 0., 0.]])
RMS:  tensor([[1.000, 1.000, 1.000, 0.000]])
L2:   tensor([[2.000, 2.000, 2.000, 0.000]])
可学习参数: [('weight', (4,)), ('bias', (4,))]
前两行相同: True
```

::: v-pre
**读输出：**前两行变成同一向量，说明 LayerNorm 消除了整体平移。非零行的均值约为 0，RMS 约为 1。全零行仍是零；学习后 `weight/bias` 可以改变输出的均值和尺度。不要把“初始化状态的输出统计量”误认为训练后永远成立。
:::

::: v-pre
## 2. RMSNorm：保留均值，只控制均方根

对应 教案 的 **2. RMSNorm**。`nn.RMSNorm(normalized_shape=d, eps=1e-5)` 同样只处理最后一维。默认 `elementwise_affine=True`，只创建 `[d]` 的 `weight`，没有 `bias`。若不显式传 `eps`，PyTorch 的默认值是 `None`，会按内部计算类型（opmath dtype）选择 machine epsilon；官方文档说明 FP16/BF16 输入在此采用 FP32 的 epsilon；这里固定 `1e-5` 以方便对照。
:::

<p class="nb-label">In [3]</p>

```python
rms = nn.RMSNorm(normalized_shape=d, eps=1e-5)
y_rms = rms(x)
summarize('RMSNorm 输出', y_rms)
print('可学习参数:', [(name, tuple(p.shape)) for name, p in rms.named_parameters()])
print('前两行相同:', torch.allclose(y_rms[0, 0], y_rms[0, 1], atol=1e-5))
```

```text
RMSNorm 输出
tensor([[[ 0.365,  0.730,  1.095,  1.461],
         [ 0.877,  0.956,  1.036,  1.116],
         [-1.633, -0.816,  0.000,  0.816],
         [ 0.000,  0.000,  0.000,  0.000]]])
mean: tensor([[ 0.913,  0.996, -0.408,  0.000]])
RMS:  tensor([[1.000, 1.000, 1.000, 0.000]])
L2:   tensor([[2.000, 2.000, 2.000, 0.000]])
可学习参数: [('weight', (4,))]
前两行相同: False
```

::: v-pre
**读输出：**非零行的 RMS 约为 1，均值却不为 0；整体加 10 后输出也不同。这就是 RMSNorm 与 LayerNorm 最直观的差别。全零行保持有限值。
:::

::: v-pre
## 3. ScaleNorm：控制 L2 长度

对应 教案 的 **3. ScaleNorm**。PyTorch 没有同名 `nn.ScaleNorm` 标准模块；可以用 `F.normalize(x, p=2, dim=-1, eps=1e-6)` 做 L2 归一化，再乘标量 $g$。**务必写 `dim=-1`**：`F.normalize` 的默认 `dim=1` 会在本例中沿 `seq_len`，不是隐藏维度。`eps` 通过 `max(L2, eps)` 保护零向量。
:::

<p class="nb-label">In [4]</p>

```python
g = 1.0  # 为观察 L2=1，暂固定；训练时可使用 nn.Parameter。
y_scale = g * F.normalize(x, p=2, dim=-1, eps=1e-6)
summarize('ScaleNorm 输出（g=1）', y_scale)
print('非零行 L2:', y_scale.norm(p=2, dim=-1)[0, :3])
# 可学习写法：self.g = nn.Parameter(torch.tensor(1.0))，放在 nn.Module 内。
```

```text
ScaleNorm 输出（g=1）
tensor([[[ 0.183,  0.365,  0.548,  0.730],
         [ 0.438,  0.478,  0.518,  0.558],
         [-0.816, -0.408,  0.000,  0.408],
         [ 0.000,  0.000,  0.000,  0.000]]])
mean: tensor([[ 0.456,  0.498, -0.204,  0.000]])
RMS:  tensor([[0.500, 0.500, 0.500, 0.000]])
L2:   tensor([[1.000, 1.000, 1.000, 0.000]])
非零行 L2: tensor([1.000, 1.000, 1.000])
```

::: v-pre
**读输出：**前三行的 L2 长度约为 1，均值不一定为 0；全零行的 L2 仍为 0。与 RMSNorm 比较：对维度数为 `d` 的非零向量，`RMS = L2 / sqrt(d)`，所以初始化权重为 1 的 RMSNorm 输出 L2 约为 `sqrt(d)`，而这里 ScaleNorm 的输出 L2 约为 `g=1`。
:::

::: v-pre
### API 小实验：`dim` 写错会怎样？

下列单元格演示默认 `dim=1` 的危险。先比较每个 token 的 L2；正确设置应让前三个 token 的 L2 接近 1。
:::

<p class="nb-label">In [5]</p>

```python
wrong = F.normalize(x, p=2)  # 默认 dim=1：沿 token/seq 维度
right = F.normalize(x, p=2, dim=-1)
print('省略 dim 时各 token 的 L2:', wrong.norm(p=2, dim=-1))
print('dim=-1 时各 token 的 L2:', right.norm(p=2, dim=-1))
```

```text
省略 dim 时各 token 的 L2: tensor([[0.398, 1.919, 0.401, 0.000]])
dim=-1 时各 token 的 L2: tensor([[1.000, 1.000, 1.000, 0.000]])
```

::: v-pre
## 4. QK Norm：注意力内部的归一化

对应第 9 章《自注意力》中的 **QK Norm** 一节。核心目标是控制 Q/K 点积形成的 attention logits，减少 softmax 过度饱和及相关训练不稳定风险。现代模型还分为拆头前对整条 Q/K 投影归一化的 layerwise 版本（OLMo 2/3）和拆头后逐头归一化的 headwise 版本（Qwen 3、Gemma 3、Marin 32B）；下面实验只演示原论文的逐头 L2 形式，并非所有模型的 QK Norm 实现。Q/K 形状为 `[batch, heads, seq_len, head_dim]`；`F.normalize(..., dim=-1)` 处理每个头的向量。先计算原始 `q @ k.transpose(-2, -1)`，再观察归一化后的 logits 和 softmax。`transpose(-2, -1)` 只交换 key 的 `seq_len` 与 `head_dim`，保留 batch/head 维度：`[B,H,S_k,D] → [B,H,D,S_k]`；因此分数形状为 `[B,H,S_q,S_k]`。softmax 要沿最后一维 `S_k` 计算，即每个 query 对所有 key 的概率。
:::

<p class="nb-label">In [6]</p>

```python
q = torch.tensor([[[[10., 0.], [0., 1.]]]])
k = torch.tensor([[[[10., 0.], [0., 1.]]]])
raw_scores = q @ k.transpose(-2, -1)
q_unit = F.normalize(q, p=2, dim=-1, eps=1e-6)
k_unit = F.normalize(k, p=2, dim=-1, eps=1e-6)
norm_scores = q_unit @ k_unit.transpose(-2, -1)
print('原始 logits:', raw_scores)
print('归一化后 logits（g=1）:', norm_scores)
print('原始 softmax:', raw_scores.softmax(dim=-1))
print('归一化后 softmax:', norm_scores.softmax(dim=-1))
```

```text
原始 logits: tensor([[[[100.,   0.],
          [  0.,   1.]]]])
归一化后 logits（g=1）: tensor([[[[1., 0.],
          [0., 1.]]]])
原始 softmax: tensor([[[[1.000, 0.000],
          [0.269, 0.731]]]])
归一化后 softmax: tensor([[[[0.731, 0.269],
          [0.269, 0.731]]]])
```

::: v-pre
**读输出：**原始最大 logit 是 100，第一行 softmax 几乎变成 `[1,0]`；L2 归一化后最大 logit 是 1，概率约为 `[0.731,0.269]`。这只是刻意选的示例，不表示 QK Norm 在真实模型中总会得到这个概率。可学习尺度 $g$ 会再次调整 logit 幅度。
:::

::: v-pre
### PyTorch 注意力调用

`F.scaled_dot_product_attention(q,k,v,is_causal=False,scale=1.0)` 返回加权后的 value，**不直接返回 logits/概率**。`scale` 只能是 Python 数值，不能直接传 `nn.Parameter`。若 $g$ 可学习，可以先做 `q_unit * g`，再设 `scale=1.0`。不传 `scale` 时，函数会默认使用 $1/\sqrt{d_k}$。本例无因果掩码；自回归模型应设置 `is_causal=True`。
:::

<p class="nb-label">In [7]</p>

```python
v = torch.tensor([[[[1., 0.], [0., 1.]]]])
g_qk = nn.Parameter(torch.tensor(1.0))
attention_out = F.scaled_dot_product_attention(
    q_unit * g_qk, k_unit, v, is_causal=False, scale=1.0
)
print('注意力输出:', attention_out)
print('与手算概率一致:', torch.allclose(attention_out, norm_scores.softmax(dim=-1) @ v))
```

```text
注意力输出: tensor([[[[0.731, 0.269],
          [0.269, 0.731]]]],
       grad_fn=<ScaledDotProductFlashAttentionForCpuBackward0>)
与手算概率一致: True
```

::: v-pre
## 5. DeepNorm：残差路径与初始化配合

对应第 25 章《大规模训练稳定性》中的 **DeepNorm** 一节。这里仅观察 `LayerNorm(alpha*x + branch)` 中 `alpha` 对数据的影响。`alpha=1.5` 是**演示值，不是论文系数**。完整 DeepNorm 必须按模型深度和编码器/解码器结构选择系数，并使用配套的权重初始化；PyTorch 没有独立 `nn.DeepNorm` 标准模块。
:::

<p class="nb-label">In [8]</p>

```python
residual_x = torch.tensor([[[1., 2., 3., 4.]]])
branch = torch.tensor([[[2., -1., 1., -2.]]])
post_norm = nn.LayerNorm(4, eps=1e-5)
plain_input = residual_x + branch
alpha = 1.5
scaled_input = alpha * residual_x + branch
summarize('普通残差和，alpha=1', plain_input)
summarize('缩放后的残差和，alpha=1.5', scaled_input)
summarize('LayerNorm(alpha*x + branch)', post_norm(scaled_input))
```

```text
普通残差和，alpha=1
tensor([[[3., 1., 4., 2.]]])
mean: tensor([[2.500]])
RMS:  tensor([[2.739]])
L2:   tensor([[5.477]])
缩放后的残差和，alpha=1.5
tensor([[[3.500, 2.000, 5.500, 4.000]]])
mean: tensor([[3.750]])
RMS:  tensor([[3.953]])
L2:   tensor([[7.906]])
LayerNorm(alpha*x + branch)
tensor([[[-0.200, -1.400,  1.400,  0.200]]])
mean: tensor([[0.000]])
RMS:  tensor([[1.000]])
L2:   tensor([[2.000]])
```

::: v-pre
**读输出：**改变残差路径权重后，送入 LayerNorm 的向量改变，归一化后的方向也改变。由于 LayerNorm 会重新调整尺度，只比较最终输出的 RMS 并不足以理解 DeepNorm；训练稳定性还依赖深度相关系数和初始化。
:::

::: v-pre
## 6. 一张图定位归一化

与 [教案](https://lewislau86.github.io/tinyllm/normalization) 对照，下面是一种可能的 decoder-only Block。隐藏状态归一化可选 LayerNorm/RMSNorm/ScaleNorm；QK Norm 在注意力里面、点积之前；DeepNorm 改残差连接及初始化。因果 mask 在 softmax 之前。

```text
x ──┬────────────────────────────────────────────────┐
    └→ Norm → Q/K/V 投影 → QK Norm(Q,K) → QKᵀ → mask
                                   → softmax → 加权 V → 输出投影
                                      ↓
                         x + 注意力输出 → Norm → MLP → 残差相加

若用 DeepNorm，则相应残差块为 LayerNorm(alpha * x + 子层输出)，
并需用论文规定的 beta 初始化指定权重。
```

图只说明相对位置；具体模型的 QK Norm、RoPE 和归一化先后顺序须看其架构。
:::

::: v-pre
## 7. 输入平移与缩放：三种方法保留了什么？

以 `base=[1,2,3,4]` 为例。`base+10` 是**每个特征同时平移**；`base*3` 是**正数整体放大**。暂用 FP32、初始参数和很小的 `eps`。预测哪种方法会让 `base` 与 `base+10` 的输出一致？
:::

<p class="nb-label">In [9]</p>

```python
base = torch.tensor([[[1., 2., 3., 4.]]])
variants = {'原始': base, '整体加 10': base + 10, '整体乘 3': base * 3}
modules = {
    'LayerNorm': nn.LayerNorm(4, eps=1e-8, elementwise_affine=False),
    'RMSNorm': nn.RMSNorm(4, eps=1e-8, elementwise_affine=False),
}
def scale_norm(z):
    return F.normalize(z, p=2, dim=-1, eps=1e-8)
for name, operation in [*modules.items(), ('ScaleNorm', scale_norm)]:
    outputs = {label: operation(t) for label, t in variants.items()}
    print(name)
    for label, result in outputs.items():
        print(' ', label, result.flatten())
    print('  平移后相同:', torch.allclose(outputs['原始'], outputs['整体加 10'], atol=1e-6))
    print('  正数缩放后相同:', torch.allclose(outputs['原始'], outputs['整体乘 3'], atol=1e-6))
```

```text
LayerNorm
  原始 tensor([-1.342, -0.447,  0.447,  1.342])
  整体加 10 tensor([-1.342, -0.447,  0.447,  1.342])
  整体乘 3 tensor([-1.342, -0.447,  0.447,  1.342])
  平移后相同: True
  正数缩放后相同: True
RMSNorm
  原始 tensor([0.365, 0.730, 1.095, 1.461])
  整体加 10 tensor([0.877, 0.956, 1.036, 1.116])
  整体乘 3 tensor([0.365, 0.730, 1.095, 1.461])
  平移后相同: False
  正数缩放后相同: True
ScaleNorm
  原始 tensor([0.183, 0.365, 0.548, 0.730])
  整体加 10 tensor([0.438, 0.478, 0.518, 0.558])
  整体乘 3 tensor([0.183, 0.365, 0.548, 0.730])
  平移后相同: False
  正数缩放后相同: True
```

::: v-pre
**读输出：**只有 LayerNorm 会消除共同平移；三种方法对正数整体缩放都近似不变。`eps` 不为零时这是近似性质，数值误差和可学习参数也会影响具体数值。若输入乘负数，方向会翻转；LayerNorm 若有非零 `bias`，也不能直接说整个输出简单变号。
:::

::: v-pre
## 8. DeepNorm 系数与初始化：decoder-only 的具体例子

[DeepNet 论文第 4.3 节](https://arxiv.org/pdf/2203.00555) 给出 decoder-only、$M$ 层时的 $\alpha=(2M)^{1/4}$、$\beta=(8M)^{-1/4}$。$\alpha$ 固定用于残差分支，$\beta$ 用于**标准初始化之后**缩放每层的前馈权重、注意力 value 投影和 output 投影权重。下面构造一个缩小的模块演示参数选择；没有训练网络，不能用它推断深层训练稳定性。
:::

<p class="nb-label">In [10]</p>

```python
M = 12  # decoder-only Transformer 层数；可改成 24 观察系数
alpha_deep = (2 * M) ** 0.25
beta_deep = (8 * M) ** -0.25
print(f'M={M}, alpha={alpha_deep:.4f}, beta={beta_deep:.4f}')

class TinySublayer(nn.Module):
    def __init__(self, d):
        super().__init__()
        self.q_proj = nn.Linear(d, d, bias=False)
        self.k_proj = nn.Linear(d, d, bias=False)
        self.v_proj = nn.Linear(d, d, bias=False)
        self.out_proj = nn.Linear(d, d, bias=False)
        self.ffn_up = nn.Linear(d, 2 * d, bias=False)
        self.ffn_down = nn.Linear(2 * d, d, bias=False)

    def deepnorm_init(self, beta):
        with torch.no_grad():
            for layer in [self.q_proj, self.k_proj, self.v_proj,
                          self.out_proj, self.ffn_up, self.ffn_down]:
                nn.init.xavier_uniform_(layer.weight)  # 第一步：标准初始化
            for layer in [self.v_proj, self.out_proj,
                          self.ffn_up, self.ffn_down]:
                layer.weight.mul_(beta)                 # 第二步：仅缩放论文指定的投影类别

block = TinySublayer(d=4)
block.deepnorm_init(beta_deep)
print('被 beta 缩放: v_proj, out_proj, ffn_up, ffn_down')
print('没有 beta 缩放: q_proj, k_proj')
print('残差示意: LayerNorm(alpha * x + sublayer(x))')
```

```text
M=12, alpha=2.2134, beta=0.3195
被 beta 缩放: v_proj, out_proj, ffn_up, ffn_down
没有 beta 缩放: q_proj, k_proj
残差示意: LayerNorm(alpha * x + sublayer(x))
```

::: v-pre
**读输出：**`M` 增大时，`alpha` 增大而 `beta` 减小。这里的模块只为看清初始化名单，`TinySublayer` 没有定义完整注意力与前馈前向传播；完整 DeepNorm 需要对每个真实残差子层应用系数和初始化。不要把第 5 节的任意 `alpha=1.5` 混同于这个论文公式。
:::

::: v-pre
## 9. BF16/FP16：输入表示与计算精度

对应 [教案](https://lewislau86.github.io/tinyllm/normalization)。`torch.finfo(dtype).eps` 是 1 附近的间隔，`tiny` 是最小**正规范数**正数，`max` 是最大有限数；它们与归一化层的 `eps` 参数不是同一个概念。各设备/内核对中间值的处理可能不同，所以先看输入被舍入成什么，再看归一化输出。
:::

<p class="nb-label">In [11]</p>

```python
for dtype in (torch.float32, torch.float16, torch.bfloat16):
    info = torch.finfo(dtype)
    print(dtype, 'eps=', info.eps, 'tiny=', info.tiny, 'max=', info.max)

small = torch.tensor([1e-8, 1e-7, 1e-5, 1e-4], dtype=torch.float32)
near_1000 = torch.tensor([999., 1000., 1001., 1002.], dtype=torch.float32)
for dtype in (torch.float32, torch.float16, torch.bfloat16):
    print(dtype)
    print('  微小输入存储后:', [f'{v:.9g}' for v in small.to(dtype).float().tolist()])
    print('  1000 附近存储后:', near_1000.to(dtype).float())
```

```text
torch.float32 eps= 1.1920928955078125e-07 tiny= 1.1754943508222875e-38 max= 3.4028234663852886e+38
torch.float16 eps= 0.0009765625 tiny= 6.103515625e-05 max= 65504.0
torch.bfloat16 eps= 0.0078125 tiny= 1.1754943508222875e-38 max= 3.3895313892515355e+38
torch.float32
  微小输入存储后: ['9.99999994e-09', '1.00000001e-07', '9.99999975e-06', '9.99999975e-05']
  1000 附近存储后: tensor([ 999., 1000., 1001., 1002.])
torch.float16
  微小输入存储后: ['0', '1.1920929e-07', '1.00135803e-05', '0.000100016594']
  1000 附近存储后: tensor([ 999., 1000., 1001., 1002.])
torch.bfloat16
  微小输入存储后: ['1.00117177e-08', '1.00117177e-07', '1.00135803e-05', '0.000100135803']
  1000 附近存储后: tensor([1000., 1000., 1000., 1000.])
```

::: v-pre
**读输出：**FP16 的动态范围较窄，`1e-8` 这样的输入可能变成 0；BF16 的范围较宽，却在 1000 附近不能区分所有相邻整数。某个值是否消失取决于它的量级和舍入规则。转换后再 `.float()` 只显示已经存下来的值，**不能恢复丢失的信息**。
:::

::: v-pre
### 先平方还是先升到 FP32？

下面故意选择容易让低精度平方/求和出问题的数值。它说明手写公式的运算顺序和中间 dtype 很重要，不等于断言 PyTorch 内置归一化层都采用低精度平方。
:::

<p class="nb-label">In [12]</p>

```python
for dtype, values in [
    (torch.float16, [1000., 1001., 999., 1002.]),
    (torch.bfloat16, [1000., 1001., 999., 1002.]),
]:
    z = torch.tensor(values, dtype=dtype)
    naive = z.square().mean()
    promoted = z.float().square().mean()
    print(dtype, '低精度平方均值:', naive, '先转 FP32:', promoted)

# 内置模块对不同 dtype 的输入：不带仿射参数，隔离统计量效果。
reference = torch.tensor([[999., 1000., 1001., 1002.]], dtype=torch.float32)
for norm_type in (nn.LayerNorm, nn.RMSNorm):
    module = norm_type(4, eps=1e-5, elementwise_affine=False)
    ref_out = module(reference).float()
    print('\n', norm_type.__name__, 'FP32 参考:', ref_out)
    for dtype in (torch.float16, torch.bfloat16):
        low_input = reference.to(dtype)
        low_out = module(low_input).float()
        print(dtype, '存储输入:', low_input.float(), '输出:', low_out,
              '最大绝对差:', (low_out - ref_out).abs().max().item())
```

```text
torch.float16 低精度平方均值: tensor(inf, dtype=torch.float16) 先转 FP32: tensor(1001001.500)
torch.bfloat16 低精度平方均值: tensor(999424., dtype=torch.bfloat16) 先转 FP32: tensor(1000000.)

 LayerNorm FP32 参考: tensor([[-1.342, -0.447,  0.447,  1.342]])
torch.float16 存储输入: tensor([[ 999., 1000., 1001., 1002.]]) 输出: tensor([[-1.342, -0.447,  0.447,  1.342]]) 最大绝对差: 0.0001614093780517578
torch.bfloat16 存储输入: tensor([[1000., 1000., 1000., 1000.]]) 输出: tensor([[0.002, 0.002, 0.002, 0.002]]) 最大绝对差: 1.3435885906219482

 RMSNorm FP32 参考: tensor([[0.999, 0.999, 1.000, 1.001]])
torch.float16 存储输入: tensor([[ 999., 1000., 1001., 1002.]]) 输出: tensor([[0.999, 1.000, 1.001, 1.002]]) 最大绝对差: 0.0004773139953613281
torch.bfloat16 存储输入: tensor([[1000., 1000., 1000., 1000.]]) 输出: tensor([[1., 1., 1., 1.]]) 最大绝对差: 0.0014998316764831543
```

::: v-pre
**读输出：**低精度直接平方可能出现 `inf` 或较大的舍入误差；先转 FP32 可保护后续统计计算，却不能找回 BF16/FP16 输入转换时失去的差异。内置 LayerNorm/RMSNorm 的输出取决于 PyTorch 版本、设备和内核，观察本机结果即可，不应把某次输出推广为所有硬件的保证。

实际训练通常使用 AMP。FP16 还要考虑梯度下溢/溢出与 loss scaling；BF16 有较宽动态范围，但有效精度较低。两者都应检查 `eps`、统计量计算 dtype 和实际模型的有限值。
:::

::: v-pre
### 归一化放在后续低精度运算之前，会发生什么？

同样是约 1000 的输入，FP16 可以存下输入，却存不下它的平方。先在 FP32 中运行归一化，再转成 FP16 去平方，可以比较后续运算是否仍得到有限值。这是**运算顺序与数值范围**的小实验，不是在测试归一化层的内部精度，也不代表所有模型中的数值都被限制在 1 附近。
:::

<p class="nb-label">In [13]</p>

```python
large = torch.tensor([[999., 1000., 1001., 1002.]], dtype=torch.float32)
raw_half = large.to(torch.float16)
print('原输入转 FP16 后平方:', raw_half.square())
print('全部有限:', torch.isfinite(raw_half.square()).all().item())

for norm_type in (nn.LayerNorm, nn.RMSNorm):
    norm = norm_type(4, eps=1e-5, elementwise_affine=False)
    normalized_half = norm(large).to(torch.float16)  # 先在 FP32 中归一化
    squared = normalized_half.square()                 # 再用 FP16 做后续运算
    print(norm_type.__name__, '归一化后:', normalized_half)
    print('  FP16 平方:', squared, '全部有限:', torch.isfinite(squared).all().item())
```

```text
原输入转 FP16 后平方: tensor([[inf, inf, inf, inf]], dtype=torch.float16)
全部有限: False
LayerNorm 归一化后: tensor([[-1.342, -0.447,  0.447,  1.342]], dtype=torch.float16)
  FP16 平方: tensor([[1.801, 0.200, 0.200, 1.801]], dtype=torch.float16) 全部有限: True
RMSNorm 归一化后: tensor([[0.999, 1.000, 1.001, 1.002]], dtype=torch.float16)
  FP16 平方: tensor([[0.997, 0.999, 1.002, 1.004]], dtype=torch.float16) 全部有限: True
```

::: v-pre
**读输出：**原输入的 FP16 平方含 `inf`；两种归一化把这组数据送到较合适的量级，后续 FP16 平方得到有限值。这里用 `elementwise_affine=False`，故意去掉可能再次放大数值的可学习缩放。若输入在转换到低精度时已经被舍入，或后续权重/残差重新放大激活，归一化不能保证结果准确、有限，也不能增加 FP16 的有效位数。
:::

::: v-pre
## 10. 五种方法的教学版实现

本节与 [教案中的各方法小节](https://lewislau86.github.io/tinyllm/normalization) 对应。先写公式对应的 PyTorch 算子，再检查输出和梯度。代码强调运算步骤；它不使用融合内核，**不能用运行时间与 `torch.nn` 比性能**。LayerNorm/RMSNorm 使用 FP32 小张量，便于与内置模块比较；前面第 9 节解释了低精度边界。
:::

::: v-pre
### 10.1 手写 LayerNorm

沿最后一维 `mean` 求均值；减均值后求平方均值（方差）；`rsqrt` 计算倒数平方根。`weight`/`bias` 是逐维参数。`eps` 放在方差里面，与 `nn.LayerNorm` 对照。
:::

<p class="nb-label">In [14]</p>

```python
class TeachingLayerNorm(nn.Module):
    def __init__(self, d, eps=1e-5):
        super().__init__()
        self.weight = nn.Parameter(torch.ones(d))   # gamma：逐维缩放
        self.bias = nn.Parameter(torch.zeros(d))    # beta：逐维平移
        self.eps = eps

    def forward(self, x):
        mean = x.mean(dim=-1, keepdim=True)         # 每个 token 的均值
        centered = x - mean                         # 减均值
        variance = centered.square().mean(dim=-1, keepdim=True)
        normalized = centered * torch.rsqrt(variance + self.eps)
        return normalized * self.weight + self.bias

manual_ln = TeachingLayerNorm(d=4, eps=1e-5)
builtin_ln = nn.LayerNorm(4, eps=1e-5)
builtin_ln.load_state_dict(manual_ln.state_dict())
probe_a = torch.tensor([[[1., 2., 3., 4.], [11., 12., 13., 14.]]], requires_grad=True)
probe_b = probe_a.detach().clone().requires_grad_()
out_a, out_b = manual_ln(probe_a), builtin_ln(probe_b)
assert torch.allclose(out_a, out_b, atol=1e-5)
loss_a, loss_b = out_a.square().sum(), out_b.square().sum()
loss_a.backward(); loss_b.backward()
assert torch.allclose(probe_a.grad, probe_b.grad, atol=1e-4)
for name in ('weight', 'bias'):
    assert torch.allclose(getattr(manual_ln, name).grad,
                          getattr(builtin_ln, name).grad, atol=1e-4)
print('LayerNorm：输出、输入梯度、weight/bias 梯度均与 nn.LayerNorm 接近')
```

```text
LayerNorm：输出、输入梯度、weight/bias 梯度均与 nn.LayerNorm 接近
```

::: v-pre
**读结果：**断言验证前向输出与反向梯度。`rsqrt(variance + eps)` 等于 `1 / sqrt(variance + eps)`；`keepdim=True` 保留维度用于广播。浮点计算的不同实现可能出现微小误差，因此使用容差而非逐位比较。
:::

::: v-pre
### 10.2 手写 RMSNorm

省去均值和中心化方差，只计算 `x.square().mean(dim=-1)`。默认只有逐维 `weight`；没有 `bias`。
:::

<p class="nb-label">In [15]</p>

```python
class TeachingRMSNorm(nn.Module):
    def __init__(self, d, eps=1e-5):
        super().__init__()
        self.weight = nn.Parameter(torch.ones(d))   # gamma：逐维缩放
        self.eps = eps

    def forward(self, x):
        mean_square = x.square().mean(dim=-1, keepdim=True)
        normalized = x * torch.rsqrt(mean_square + self.eps)
        return normalized * self.weight

manual_rms = TeachingRMSNorm(d=4, eps=1e-5)
builtin_rms = nn.RMSNorm(4, eps=1e-5)
builtin_rms.load_state_dict(manual_rms.state_dict())
probe_a = torch.tensor([[[1., 2., 3., 4.], [11., 12., 13., 14.]]], requires_grad=True)
probe_b = probe_a.detach().clone().requires_grad_()
out_a, out_b = manual_rms(probe_a), builtin_rms(probe_b)
assert torch.allclose(out_a, out_b, atol=1e-5)
out_a.square().sum().backward(); out_b.square().sum().backward()
assert torch.allclose(probe_a.grad, probe_b.grad, atol=1e-4)
assert torch.allclose(manual_rms.weight.grad, builtin_rms.weight.grad, atol=1e-4)
print('RMSNorm：输出、输入梯度、weight 梯度均与 nn.RMSNorm 接近')
```

```text
RMSNorm：输出、输入梯度、weight 梯度均与 nn.RMSNorm 接近
```

::: v-pre
**读结果：**RMSNorm 少了 `mean`、`centered` 和中心化方差对应的运算依赖。两个模块仍能对 token 和向量内的归约并行；这里仅展示数据流，不能由教学代码直接推出加速百分比。
:::

::: v-pre
### 10.3 手写 ScaleNorm

`torch.linalg.vector_norm(..., ord=2, dim=-1, keepdim=True)` 取得 L2 长度。一个可学习标量 `g` 乘到每个 token 的归一化向量上。这里使用 教案 公式的 `norm + eps`；它和 `F.normalize` 的 `max(norm, eps)` 只在接近零时有差别。
:::

<p class="nb-label">In [16]</p>

```python
class TeachingScaleNorm(nn.Module):
    def __init__(self, g_init=1.0, eps=1e-6):
        super().__init__()
        self.g = nn.Parameter(torch.tensor(float(g_init)))  # 单个可学习标量
        self.eps = eps

    def forward(self, x):
        length = torch.linalg.vector_norm(x, ord=2, dim=-1, keepdim=True)
        return self.g * x / (length + self.eps)

scale_layer = TeachingScaleNorm(g_init=1.0)
scale_input = torch.tensor([[[3., 4.], [0., 0.]]], requires_grad=True)
scale_output = scale_layer(scale_input)
reference_scale = scale_input / (scale_input.norm(p=2, dim=-1, keepdim=True) + 1e-6)
assert torch.allclose(scale_output, reference_scale)
assert torch.isfinite(scale_output).all()
scale_output.square().sum().backward()
assert scale_layer.g.grad is not None and torch.isfinite(scale_layer.g.grad)
print('ScaleNorm 输出:', scale_output.detach())
print('g 的梯度:', scale_layer.g.grad.item())
```

```text
ScaleNorm 输出: tensor([[[0.600, 0.800],
         [0.000, 0.000]]])
g 的梯度: 1.9999992847442627
```

::: v-pre
**读结果：**非零向量 `[3,4]` 的长度约变成 `g=1`；零向量仍为零。`g` 收到梯度，说明它可学习。PyTorch 没有同名 `nn.ScaleNorm` 内置模块。
:::

::: v-pre
### 10.4 手写 QK Norm（逐头 L2 版本）

`q/k` 为 `[B,H,S,D]`。分别沿 `D` 维做 L2 归一化；`k.transpose(-2,-1)` 变成 `[B,H,D,S_k]`；分数 `[B,H,S_q,S_k]` 在最后一维 softmax。可学习尺度 `g` 乘在 query 上，再用 `scaled_dot_product_attention(..., scale=1.0)` 对照。这里不加因果 mask，便于逐项观察；自回归模型要在 softmax 前遮住未来 key。
:::

<p class="nb-label">In [17]</p>

```python
class TeachingQKNorm(nn.Module):
    def __init__(self, g_init=1.0, eps=1e-6):
        super().__init__()
        self.g = nn.Parameter(torch.tensor(float(g_init)))
        self.eps = eps

    def forward(self, q, k, v):
        q_unit = q / q.norm(p=2, dim=-1, keepdim=True).clamp_min(self.eps)
        k_unit = k / k.norm(p=2, dim=-1, keepdim=True).clamp_min(self.eps)
        logits = (self.g * q_unit) @ k_unit.transpose(-2, -1)
        probabilities = logits.softmax(dim=-1)
        return probabilities @ v, logits, probabilities

qk_layer = TeachingQKNorm(g_init=1.0)
q_demo = torch.tensor([[[[10., 0.], [0., 1.]]]], requires_grad=True)
k_demo = torch.tensor([[[[10., 0.], [0., 1.]]]])
v_demo = torch.tensor([[[[1., 0.], [0., 1.]]]])
manual_out, logits, probabilities = qk_layer(q_demo, k_demo, v_demo)
q_unit = F.normalize(q_demo, p=2, dim=-1, eps=1e-6)
k_unit = F.normalize(k_demo, p=2, dim=-1, eps=1e-6)
sdpa_out = F.scaled_dot_product_attention(
    q_unit * qk_layer.g, k_unit, v_demo, is_causal=False, scale=1.0
)
assert torch.allclose(manual_out, sdpa_out, atol=1e-6)
manual_out.square().sum().backward()
assert qk_layer.g.grad is not None and q_demo.grad is not None
print('logits:', logits.detach())
print('概率:', probabilities.detach())
print('与 SDPA 输出接近，且 g、q 均有梯度')
```

```text
logits: tensor([[[[1., 0.],
          [0., 1.]]]])
概率: tensor([[[[0.731, 0.269],
          [0.269, 0.731]]]])
与 SDPA 输出接近，且 g、q 均有梯度
```

::: v-pre
**读结果：**这个类实现原论文的逐头 L2 思路。若目标模型用逐头 RMSNorm、RoPE 或可学习的逐头尺度，应按模型定义修改，不能只换名称。`F.scaled_dot_product_attention` 只返回加权的 value，不返回 logits 或概率。
:::

::: v-pre
### 10.5 手写 decoder-only DeepNorm Block

这是完整的**小型 decoder-only Block 结构演示**：两个子层各用 `LayerNorm(alpha*x + F(x))`，`alpha=(2M)^(1/4)`；所有线性层先用 Xavier 初始化，随后只将注意力的 V/O 投影及前馈层的两个投影乘 `beta=(8M)^(-1/4)`。注意力使用因果 mask。代码体现论文针对 decoder-only 的系数与初始化规则；它并未训练 $M$ 个 Block，因此无法证明稳定性收益。
:::

<p class="nb-label">In [18]</p>

```python
class TeachingDeepNormBlock(nn.Module):
    def __init__(self, d, heads, model_layers, eps=1e-5):
        super().__init__()
        assert d % heads == 0 and model_layers > 0
        self.heads = heads
        self.head_dim = d // heads
        self.alpha = (2 * model_layers) ** 0.25
        beta = (8 * model_layers) ** -0.25
        self.q_proj = nn.Linear(d, d, bias=False)
        self.k_proj = nn.Linear(d, d, bias=False)
        self.v_proj = nn.Linear(d, d, bias=False)
        self.o_proj = nn.Linear(d, d, bias=False)
        self.ff_up = nn.Linear(d, 2 * d, bias=False)
        self.ff_down = nn.Linear(2 * d, d, bias=False)
        self.attn_norm = nn.LayerNorm(d, eps=eps)
        self.ff_norm = nn.LayerNorm(d, eps=eps)
        with torch.no_grad():
            for layer in (self.q_proj, self.k_proj, self.v_proj,
                          self.o_proj, self.ff_up, self.ff_down):
                nn.init.xavier_uniform_(layer.weight)
            for layer in (self.v_proj, self.o_proj, self.ff_up, self.ff_down):
                layer.weight.mul_(beta)

    def forward(self, x):
        b, s, d = x.shape
        def split(projected):
            return projected.reshape(b, s, self.heads, self.head_dim).transpose(1, 2)
        q = split(self.q_proj(x))
        k = split(self.k_proj(x))
        v = split(self.v_proj(x))
        attention = F.scaled_dot_product_attention(q, k, v, is_causal=True)
        joined = attention.transpose(1, 2).reshape(b, s, d)
        x = self.attn_norm(self.alpha * x + self.o_proj(joined))
        ff = self.ff_down(F.gelu(self.ff_up(x)))
        return self.ff_norm(self.alpha * x + ff)

block = TeachingDeepNormBlock(d=4, heads=2, model_layers=12)
block_input = torch.randn(2, 3, 4, requires_grad=True)
block_output = block(block_input)
assert block_output.shape == block_input.shape
block_output.square().sum().backward()
assert block_input.grad is not None and torch.isfinite(block_input.grad).all()
print('alpha:', round(block.alpha, 4), '| 输出形状:', tuple(block_output.shape))
print('因果注意力、两个残差子层与初始化已组合；反向梯度有限')
```

```text
alpha: 2.2134 | 输出形状: (2, 3, 4)
因果注意力、两个残差子层与初始化已组合；反向梯度有限
```

::: v-pre
**读结果：**与前面的任意 `alpha=1.5` 残差示意相比，这个 Block 根据总层数计算系数，并在初始化时缩放指定投影。`transpose(1,2)` 负责把 `[B,S,H,D]` 变成 `[B,H,S,D]`，注意力输出后再交换回来；`k.transpose(-2,-1)` 的分数计算由 SDPA 内部完成。它是透明的教学模型，不等同于 DeepNet 论文的完整训练配置或性能复现。
:::

::: v-pre
## 11. 思考练习

1. 把第 7 节的 `base+10` 改成 `base+1000`，预测哪种方法在 FP32 下仍消除共同平移。
2. 把第 7 节的正数乘数 `3` 改为 `0.001`；为什么结果可能不再几乎相同？提示：看 `eps`。
3. 把第 8 节的 `M=12` 改为 `M=48`，预测 `alpha`、`beta` 各朝哪个方向变化。
4. 对 `near_1000`，先转 BF16 再转 FP32，能否恢复原始的四个整数？

答案见下一单元格；建议先运行实验再看。
:::

::: v-pre
### 练习答案

1. LayerNorm 理论上消除共同平移；实际计算仍受有限精度限制。
2. `eps` 与缩小后的平方或范数相比不再可以忽略，缩放不变性只是近似的。
3. `alpha` 增大、`beta` 减小。
4. 不能；低精度存储时已被舍入到可表示值。

补充：第 4 节 QK Norm 的尺度 `g` 增大时，softmax 通常变得更尖锐；`F.normalize` 的 `dim`、注意力 softmax 的维度和 `Kᵀ` 的最后两维仍是最常见的代码错误。
:::

::: v-pre
## 12. API 参数速查与下一步

| API | 关键参数 | 本实验的取值或说明 |
| --- | --- | --- |
| `nn.LayerNorm` | `normalized_shape`, `eps`, `elementwise_affine`, `bias` | `d`, `1e-5`, `True`, `True`；默认有 `weight/bias` |
| `nn.RMSNorm` | `normalized_shape`, `eps`, `elementwise_affine` | `d`, `1e-5`, `True`；默认仅有 `weight` |
| `F.normalize` | `p`, `dim`, `eps` | `2`, `-1`, `1e-6`；不创建可学习参数 |
| `Tensor.norm` | `p`, `dim`, `keepdim` | 常用 `2`, `-1`, `True`；`keepdim=True` 便于广播 |
| `F.scaled_dot_product_attention` | `is_causal`, `scale`, `dropout_p` | 本例 `False`, `1.0`, `0.0`；自回归通常用 `is_causal=True` |

下一步可回到 [教案的公式与论文链接](https://lewislau86.github.io/tinyllm/normalization) 核对各方法的定义。若要比较性能，应控制设备、dtype、输入形状与内核；本 notebook 展示概念、数据表示与局部初始化，不验证深层训练稳定性。
:::

::: v-pre
## 12. MLX 对照实验（可选）

前面的 PyTorch 实验可在 CPU 上运行；Apple silicon 用户也可以用 PyTorch MPS 执行适用的张量运算。本节另用 **MLX 原生数组**对照五种方法的关键步骤。MLX 和 PyTorch MPS 是不同框架；没有安装 MLX 时自动跳过。MLX 惰性求值，打印前用 `mx.eval` 完成计算。这里用无可学习参数或固定参数的小数据展示数学步骤；训练版模块及梯度检查仍以本章 PyTorch 实现为准。
:::

<p class="nb-label">In [19]</p>

```python
try:
    import mlx.core as mx
    import mlx.nn as mlx_nn
    mlx_available = True
    print('MLX 默认设备:', mx.default_device())
except ImportError:
    mlx_available = False
    print('未安装 MLX；Apple silicon 原生 Python 可用 pip install mlx，然后重跑本节。')
```

```text
未安装 MLX；Apple silicon 原生 Python 可用 pip install mlx，然后重跑本节。
```

<p class="nb-label">In [20]</p>

```python
if mlx_available:
    v = mx.array([[1., 2., 3., 4.]])
    d = v.shape[-1]
    eps = 1e-5
    centered = v - mx.mean(v, axis=-1, keepdims=True)
    layer = centered / mx.sqrt(mx.mean(centered * centered, axis=-1, keepdims=True) + eps)
    rms = v / mx.sqrt(mx.mean(v * v, axis=-1, keepdims=True) + eps)
    scale = v / mx.maximum(mx.sqrt(mx.sum(v * v, axis=-1, keepdims=True)), 1e-6)
    mx.eval(layer, rms, scale)
    print('手写 LayerNorm:', layer.tolist())
    print('手写 RMSNorm:', rms.tolist())
    print('手写 ScaleNorm (g=1):', scale.tolist())
    built_ln = mlx_nn.LayerNorm(d, eps=eps, affine=False)(v)
    built_rms = mlx_nn.RMSNorm(d, eps=eps)  # 默认缩放权重初始化为 1(v)
    mx.eval(built_ln, built_rms)
    print('mlx.nn.LayerNorm:', built_ln.tolist())
    print('mlx.nn.RMSNorm:', built_rms.tolist())
```

::: v-pre
**读输出：**LayerNorm 先减均值，RMSNorm 只控制均方根，ScaleNorm 控制 L2 长度。`mlx.nn.LayerNorm` / `mlx.nn.RMSNorm` 是 MLX 原生模块；手写式用于看步骤，不用作性能基准。
:::

<p class="nb-label">In [21]</p>

```python
if mlx_available:
    # 单头 Q/K，各有两个 token；先在最后一维按 RMS 归一化，再计算注意力。
    q = mx.array([[[2., 0.], [0., 1.]]])
    k = mx.array([[[1., 0.], [0., 2.]]])
    v_attn = mx.array([[[1., 2.], [3., 4.]]])
    def rms_last(z):
        return z / mx.sqrt(mx.mean(z * z, axis=-1, keepdims=True) + 1e-5)
    q_norm, k_norm = rms_last(q), rms_last(k)
    logits = q_norm @ mx.swapaxes(k_norm, -1, -2)
    attention = mx.softmax(logits, axis=-1) @ v_attn
    # DeepNorm 的局部残差式：alpha * x + F(x)，这里 F(x)=0.1*x。
    M = 12
    alpha = (2 * M) ** 0.25
    beta = (8 * M) ** -0.25
    x_res = mx.array([[1., 2., 3., 4.]])
    deep_local = mlx_nn.LayerNorm(4, affine=False)(alpha * x_res + 0.1 * x_res)
    mx.eval(logits, attention, deep_local)
    print('QK Norm logits:', logits.tolist(), '注意力输出:', attention.tolist())
    print('DeepNorm 局部示意 alpha/beta:', alpha, beta, '输出:', deep_local.tolist())
```

::: v-pre
**读输出：**QK Norm 作用于注意力点积之前的 Q/K；DeepNorm 还要求按论文规则调整多层残差和指定权重初始化。这里仅演示 `alpha` 的局部残差式，`beta` 只打印以提醒它属于初始化部分；不能据此声称复现了完整 DeepNorm。
:::

