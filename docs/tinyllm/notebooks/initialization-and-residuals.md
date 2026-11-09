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

从上到下运行即可，CPU 上约一分半（大部分是第 6 节训练 12 个 8 层的代理模型）。需要安装 PyTorch、`tokenizers` 和 Plotly（画图）。
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

::: v-pre
## 6. 真实 Block 上的 1/√(2L)

前面的子层只是 `Linear`。下面换成 TinyLLM 真正的 Pre-RMSNorm Block（RoPE 因果注意力 + SwiGLU），尺寸用第 17 章的代理模型（宽度 64、4 个头），
只改层数。`init_weights` 先用 Xavier，再把每个 Block 的 `proj` 和 `down` 乘 $1/\sqrt{2L}$；“不缩放”就是把这一步撤掉。
:::

<p class="nb-label">In [9]</p>

```python
import copy
import json
import math
import time
from dataclasses import dataclass

import torch
from torch import nn
from torch.nn import functional as F
from tokenizers import Tokenizer, decoders, models, pre_tokenizers, trainers


import hashlib
import json
import os
from pathlib import Path
from urllib.request import urlopen

CORPUS_URL = "https://lewislau86.github.io/tinyllm/data/tang-poems.jsonl"
CORPUS_SHA256 = "764f0614663c20e95927c6ecb63e454629f6cb0efefe9ac84454e256f7173fb1"

def load_poems(n):
    """本课统一唐诗语料的前 n 首（来源和处理方式见“实验环境”页）。
    依次找：环境变量 TINYLLM_DATA、当前目录、../data/（整包下载解压后的位置）；都没有就从网站下载一份。"""
    candidates = [os.environ.get("TINYLLM_DATA", ""), "tang-poems.jsonl", "../data/tang-poems.jsonl"]
    path = next((Path(p) for p in candidates if p and Path(p).exists()), None)
    if path is None:
        path = Path("tang-poems.jsonl")
        with urlopen(CORPUS_URL, timeout=120) as r:
            path.write_bytes(r.read())
    raw = path.read_bytes().replace(b"\r\n", b"\n")
    if hashlib.sha256(raw).hexdigest() != CORPUS_SHA256:
        raise RuntimeError(f"{path} 不是本课使用的语料版本，删掉它再运行一次即可重新下载")
    return [json.loads(line) for line in raw.decode("utf-8").splitlines()[:n]]
```

::: v-pre
## 0. 第 17 章的代理模型

模型代码、数据划分、评估口径都从第 12 章原样复制，尺寸和第 17 章的代理模型相同（词表 1024、宽度 64、2 层）。
本章要训练二十多次，所以用这个缩小的版本；损失只在本章内部比较。
:::

<p class="nb-label">In [10]</p>

```python
@dataclass
class TinyConfig:
    vocab_size: int = 4096     # BPE 词表大小（含 4 个特殊 token）
    d_model: int = 128         # 每个 token 向量的宽度 d
    n_layers: int = 4          # Block 层数 L
    n_heads: int = 4           # 注意力头数，每头 d / n_heads = 32 维
    context: int = 64          # 一次最多看多少个 token
    rope_base: float = 10000.0

cfg = TinyConfig()

cfg = TinyConfig(vocab_size=1024, d_model=64, n_layers=2)       # 代理模型：只改这三个尺寸
STEPS, BATCH = 240, 16
print(cfg)
```

```text
TinyConfig(vocab_size=1024, d_model=64, n_layers=2, n_heads=4, context=64, rope_base=10000.0)
```

<p class="nb-label">In [11]</p>

```python
poems = load_poems(6000)
train_poems = [p["text"] for p in poems if p["split"] == "train"]
val_poems = [p["text"] for p in poems if p["split"] == "val"]

def train_tokenizer(texts, vocab_size):
    tok = Tokenizer(models.BPE())
    tok.pre_tokenizer = pre_tokenizers.ByteLevel(add_prefix_space=False)
    tok.decoder = decoders.ByteLevel()
    trainer = trainers.BpeTrainer(
        vocab_size=vocab_size,
        special_tokens=["<pad>", "<unk>", "<bos>", "<eos>"],
        initial_alphabet=pre_tokenizers.ByteLevel.alphabet(),
        show_progress=False,
    )
    tok.train_from_iterator(texts, trainer)
    return tok

tokenizer = train_tokenizer(train_poems, cfg.vocab_size)
EOS = tokenizer.token_to_id("<eos>")
```

<p class="nb-label">In [12]</p>

```python
def rope_tables(context, head_dim, base):
    theta = base ** (-torch.arange(0, head_dim, 2).float() / head_dim)
    angle = torch.arange(context).float()[:, None] * theta        # (T, head_dim/2)
    return angle.cos(), angle.sin()

def apply_rope(x, cos, sin):                                      # x: (B, 头数, T, head_dim)
    T = x.shape[-2]
    cos, sin = cos[:T], sin[:T]
    x1, x2 = x[..., 0::2], x[..., 1::2]
    return torch.stack([x1 * cos - x2 * sin, x1 * sin + x2 * cos], dim=-1).flatten(-2)

class CausalSelfAttention(nn.Module):
    def __init__(self, cfg):
        super().__init__()
        self.n_heads = cfg.n_heads
        self.qkv = nn.Linear(cfg.d_model, 3 * cfg.d_model, bias=False)
        self.proj = nn.Linear(cfg.d_model, cfg.d_model, bias=False)   # 输出投影：写回残差流

    def forward(self, x, cos, sin):
        B, T, D = x.shape
        q, k, v = (t.view(B, T, self.n_heads, D // self.n_heads).transpose(1, 2)
                   for t in self.qkv(x).split(D, dim=-1))
        y = F.scaled_dot_product_attention(apply_rope(q, cos, sin), apply_rope(k, cos, sin), v, is_causal=True)
        return self.proj(y.transpose(1, 2).reshape(B, T, D))

class SwiGLU(nn.Module):
    def __init__(self, cfg):
        super().__init__()
        hidden = 8 * cfg.d_model // 3
        self.gate = nn.Linear(cfg.d_model, hidden, bias=False)
        self.up = nn.Linear(cfg.d_model, hidden, bias=False)
        self.down = nn.Linear(hidden, cfg.d_model, bias=False)        # 输出投影：写回残差流

    def forward(self, x):
        return self.down(F.silu(self.gate(x)) * self.up(x))

class Block(nn.Module):
    def __init__(self, cfg):
        super().__init__()
        self.norm1 = nn.RMSNorm(cfg.d_model)
        self.attn = CausalSelfAttention(cfg)
        self.norm2 = nn.RMSNorm(cfg.d_model)
        self.ffn = SwiGLU(cfg)

    def forward(self, x, cos, sin):
        x = x + self.attn(self.norm1(x), cos, sin)
        return x + self.ffn(self.norm2(x))

class TinyLLM(nn.Module):
    def __init__(self, cfg):
        super().__init__()
        self.cfg = cfg
        self.embed = nn.Embedding(cfg.vocab_size, cfg.d_model)
        self.blocks = nn.ModuleList(Block(cfg) for _ in range(cfg.n_layers))
        self.norm = nn.RMSNorm(cfg.d_model)
        cos, sin = rope_tables(cfg.context, cfg.d_model // cfg.n_heads, cfg.rope_base)
        self.register_buffer("cos", cos, persistent=False)
        self.register_buffer("sin", sin, persistent=False)
        self.init_weights()

    def init_weights(self):
        for m in self.modules():
            if isinstance(m, nn.Linear):
                nn.init.xavier_normal_(m.weight)
        nn.init.normal_(self.embed.weight, mean=0.0, std=self.cfg.d_model ** -0.5)
        scale = (2 * self.cfg.n_layers) ** -0.5
        with torch.no_grad():
            for b in self.blocks:
                b.attn.proj.weight.mul_(scale)
                b.ffn.down.weight.mul_(scale)

    def forward(self, idx, targets=None):
        x = self.embed(idx)                                   # (B, T) → (B, T, d)
        for block in self.blocks:
            x = block(x, self.cos, self.sin)
        logits = self.norm(x) @ self.embed.weight.T           # (B, T, d) → (B, T, V)，与嵌入共享权重
        if targets is None:
            return logits
        loss = F.cross_entropy(logits.view(-1, logits.size(-1)), targets.view(-1))
        return logits, loss
```

<p class="nb-label">In [13]</p>

```python
def to_stream(texts):
    ids = []
    for t in texts:
        ids += tokenizer.encode(t).ids + [EOS]
    return torch.tensor(ids)

train_ids, val_ids = to_stream(train_poems), to_stream(val_poems)
tokens_per_char = len(val_ids) / sum(len(t) + 1 for t in val_poems)   # 每首诗的 <eos> 记作一个“字”

@torch.no_grad()
def evaluate(model, ids=val_ids, T=cfg.context, batch=64):
    model.eval()
    n = (len(ids) - 1) // T * T
    xs, ys = ids[:n].view(-1, T), ids[1:n + 1].view(-1, T)
    total = sum(F.cross_entropy(model(xs[i:i + batch]).flatten(0, 1), ys[i:i + batch].flatten(), reduction="sum").item()
                for i in range(0, len(xs), batch))
    model.train()
    nats = total / ys.numel()
    return nats, nats * tokens_per_char / math.log(2)    # (每 token 的 nats, 每字比特)
```

<p class="nb-label">In [14]</p>

```python
from dataclasses import replace

plan = torch.Generator().manual_seed(1234)                 # batch 计划：所有对照共用，种子只决定初始参数
starts = torch.randint(0, len(train_ids) - cfg.context - 1, (STEPS, BATCH), generator=plan)

def get_batch(step):
    idx = starts[step][:, None] + torch.arange(cfg.context + 1)
    return train_ids[idx[:, :-1]], train_ids[idx[:, 1:]]

def build(n_layers, scaled, seed):
    torch.manual_seed(seed)
    model = TinyLLM(replace(cfg, n_layers=n_layers))      # init_weights 里已经乘了 1/√(2L)
    if not scaled:                                         # 撤掉这一步：乘回 √(2L)
        with torch.no_grad():
            for b in model.blocks:
                b.attn.proj.weight.mul_((2 * n_layers) ** 0.5)
                b.ffn.down.weight.mul_((2 * n_layers) ** 0.5)
    return model

@torch.no_grad()
def stream_rms(model, x):
    """嵌入之后、每个 Block 之后，残差流的 RMS。"""
    h = model.embed(x)
    out = [h.pow(2).mean().sqrt().item()]
    for b in model.blocks:
        h = b(h, model.cos, model.sin)
        out.append(h.pow(2).mean().sqrt().item())
    return out

x0, _ = get_batch(0)
rms_log = {}
for n_layers in (8, 24):
    for scaled in (False, True):
        runs = [stream_rms(build(n_layers, scaled, seed), x0) for seed in (0, 1, 2)]
        mean = [sum(r[i] for r in runs) / 3 for i in range(n_layers + 1)]
        rms_log[f"{n_layers}|{scaled}"] = mean
        print(f"{n_layers:>2} 层 {'乘 1/√(2L)' if scaled else '不缩放    '}  嵌入 {mean[0]:.3f} → 最后一层 {mean[-1]:.3f}"
              f"（{mean[-1] / mean[0]:.1f} 倍，3 个种子平均）")
```

```text
 8 层 不缩放      嵌入 0.124 → 最后一层 1.840（14.8 倍，3 个种子平均）
 8 层 乘 1/√(2L)  嵌入 0.124 → 最后一层 0.415（3.3 倍，3 个种子平均）
```

```text
24 层 不缩放      嵌入 0.124 → 最后一层 3.455（27.8 倍，3 个种子平均）
24 层 乘 1/√(2L)  嵌入 0.124 → 最后一层 0.433（3.5 倍，3 个种子平均）
```

::: v-pre
再训练 8 层的模型：第 17 章的 WSD 调度、240 步、裁剪到 1.0，峰值学习率取 1e-2 和 3e-3 两档，各 3 个种子。
第 1 步的梯度范数也记下来：缩放会改变训练一开始各层收到的梯度。
:::

<p class="nb-label">In [15]</p>

```python
def wsd(step, peak, warmup=30, decay_frac=0.2):            # 第 17 章的调度
    decay_start = int(STEPS * (1 - decay_frac))
    if step < warmup:
        return peak * (step + 1) / warmup
    if step < decay_start:
        return peak
    return peak * (STEPS - step) / (STEPS - decay_start)

def train(scaled, seed, peak, n_layers=8):
    model = build(n_layers, scaled, seed)
    decay = [p for p in model.parameters() if p.dim() >= 2]
    no_decay = [p for p in model.parameters() if p.dim() < 2]
    optimizer = torch.optim.AdamW([{"params": decay, "weight_decay": 0.1},
                                   {"params": no_decay, "weight_decay": 0.0}], lr=peak)
    first_norm = None
    for step in range(STEPS):
        for group in optimizer.param_groups:
            group["lr"] = wsd(step, peak)
        x, y = get_batch(step)
        _, loss = model(x, y)
        optimizer.zero_grad(set_to_none=True)
        loss.backward()
        norm = torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0).item()
        first_norm = norm if first_norm is None else first_norm
        optimizer.step()
    return evaluate(model)[0], first_norm

train_log = {}
for peak in (1e-2, 3e-3):
    for scaled in (False, True):
        runs = [train(scaled, seed, peak) for seed in (0, 1, 2)]
        vals = [r[0] for r in runs]
        train_log[f"{peak}|{scaled}"] = vals
        print(f"峰值 {peak:g}  {'乘 1/√(2L)' if scaled else '不缩放    '}  验证损失 {' '.join(f'{v:.3f}' for v in vals)}"
              f"  平均 {sum(vals) / 3:.3f}   第 1 步梯度范数 {sum(r[1] for r in runs) / 3:.2f}")
```

```text
峰值 0.01  不缩放      验证损失 5.036 5.032 5.028  平均 5.032   第 1 步梯度范数 1.99
```

```text
峰值 0.01  乘 1/√(2L)  验证损失 4.698 4.727 4.670  平均 4.698   第 1 步梯度范数 3.31
```

```text
峰值 0.003  不缩放      验证损失 5.041 5.079 5.054  平均 5.058   第 1 步梯度范数 1.99
```

```text
峰值 0.003  乘 1/√(2L)  验证损失 4.737 4.747 4.742  平均 4.742   第 1 步梯度范数 3.31
```

<p class="nb-label">In [16]</p>

```python
import json
with open("initialization_residuals_log.json", "w", encoding="utf-8") as f:
    json.dump({"rms": rms_log, "train": train_log}, f, ensure_ascii=False)
print("已写出 initialization_residuals_log.json")
```

```text
已写出 initialization_residuals_log.json
```

