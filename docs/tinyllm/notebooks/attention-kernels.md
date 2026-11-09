---
title: "第 28 章：注意力内核与算子融合（notebook 在线查看）"
search: false
editLink: false
prev: false
next: false
pageClass: tinyllm-course
---

<!-- 本页由 scripts/build-tinyllm-code.py 根据 notebook 自动生成，请勿手改。 -->

::: tip 这是 notebook 的只读预览
[返回教案](/tinyllm/attention-kernels) · [在 Colab 中运行](https://colab.research.google.com/github/lewislau86/lewislau86.github.io/blob/master/docs/public/tinyllm/notebooks/attention-kernels.ipynb) · <a href="/tinyllm/notebooks/attention-kernels.ipynb" download>下载 .ipynb</a> · <a href="/tinyllm/code/attention-kernels.py" download>下载 .py</a> · [在 GitHub 上查看](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/tinyllm/notebooks/attention-kernels.ipynb)

下面的代码和输出与 notebook 文件完全一致。想修改、运行，请用 Colab 打开或下载到本地。
:::

::: v-pre
# 第 28 章：注意力内核与算子融合

配套教案：https://lewislau86.github.io/tinyllm/attention-kernels

从上到下运行即可（`python attention-kernels.py`），CPU 上约一分半（一半是训练基线模型）。
需要安装 PyTorch 和 `tokenizers`；最后一节的 `torch.compile` 还需要一个 C++ 编译器（Linux/macOS 自带或装一下即可，
Colab 自带），没有编译器时那一节会打印原因并跳过。
这个文件是本章代码的唯一来源：教案中的代码片段由 `# region 名字` / `# endregion 名字`
标记的区域直接引用，notebook 也由它生成（scripts/build-tinyllm-code.py）。

本章不比快慢，只数两样与硬件无关的量：峰值时要同时存多少字节，一共要从内存读写多少字节。
朴素注意力、分块加 online softmax 的注意力、PyTorch 的 scaled_dot_product_attention 三者先对齐数值，再比这两样。
:::

<p class="nb-label">In [1]</p>

```python
import json
import math
import weakref

import torch
from torch import nn
from torch.nn import functional as F
from torch.utils._python_dispatch import TorchDispatchMode
from torch.utils._pytree import tree_flatten
from tokenizers import Tokenizer, decoders, models, pre_tokenizers, trainers

torch.set_num_threads(1)                      # 与第 27 章一致：单线程，结果可复现
torch.manual_seed(0)
print("PyTorch", torch.__version__, " 线程数", torch.get_num_threads())
log = {}

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

```text
PyTorch 2.14.1+cpu  线程数 1
```

::: v-pre
## 1. 研究对象：第 12 章的基线模型

和第 27 章一样，先按[第 12 章](https://lewislau86.github.io/tinyllm/tinyllm-model)的配置训 300 步。
唯一的改动：每层的注意力不直接写死，而是调用全局变量 `ATTN` 指向的函数，后面可以把它换成自己写的版本。
:::

<p class="nb-label">In [2]</p>

```python
poems = load_poems(6000)
train_poems = [p["text"] for p in poems if p["split"] == "train"]
val_poems = [p["text"] for p in poems if p["split"] == "val"]

V, D, L, H, CTX = 4096, 128, 4, 4, 64
tok = Tokenizer(models.BPE())
tok.pre_tokenizer = pre_tokenizers.ByteLevel(add_prefix_space=False)
tok.decoder = decoders.ByteLevel()
tok.train_from_iterator(train_poems, trainers.BpeTrainer(
    vocab_size=V, special_tokens=["<pad>", "<unk>", "<bos>", "<eos>"],
    initial_alphabet=pre_tokenizers.ByteLevel.alphabet(), show_progress=False))
EOS = tok.token_to_id("<eos>")

def sdpa(q, k, v):
    return F.scaled_dot_product_attention(q, k, v, is_causal=True)

ATTN = sdpa                                    # 每层注意力调用的函数，后面会换掉

def rope_tables(context, head_dim, base=10000.0):
    theta = base ** (-torch.arange(0, head_dim, 2).float() / head_dim)
    angle = torch.arange(context).float()[:, None] * theta
    return angle.cos(), angle.sin()

def apply_rope(x, cos, sin):
    T = x.shape[-2]
    cos, sin = cos[:T], sin[:T]
    x1, x2 = x[..., 0::2], x[..., 1::2]
    return torch.stack([x1 * cos - x2 * sin, x1 * sin + x2 * cos], dim=-1).flatten(-2)

class Block(nn.Module):
    def __init__(self):
        super().__init__()
        self.norm1, self.norm2 = nn.RMSNorm(D), nn.RMSNorm(D)
        self.qkv = nn.Linear(D, 3 * D, bias=False)
        self.proj = nn.Linear(D, D, bias=False)
        self.gate = nn.Linear(D, 8 * D // 3, bias=False)
        self.up = nn.Linear(D, 8 * D // 3, bias=False)
        self.down = nn.Linear(8 * D // 3, D, bias=False)

    def heads(self, x, cos, sin):              # 这一层的 Q、K、V：[B, H, T, 每头维度]
        B, T, _ = x.shape
        q, k, v = (t.view(B, T, H, D // H).transpose(1, 2) for t in self.qkv(self.norm1(x)).split(D, dim=-1))
        return apply_rope(q, cos, sin), apply_rope(k, cos, sin), v

    def forward(self, x, cos, sin):
        B, T, _ = x.shape
        y = ATTN(*self.heads(x, cos, sin))
        x = x + self.proj(y.transpose(1, 2).reshape(B, T, D))
        h = self.norm2(x)
        return x + self.down(F.silu(self.gate(h)) * self.up(h))

class Tiny(nn.Module):
    def __init__(self):
        super().__init__()
        self.embed = nn.Embedding(V, D)
        self.blocks = nn.ModuleList(Block() for _ in range(L))
        self.norm = nn.RMSNorm(D)
        cos, sin = rope_tables(CTX, D // H)
        self.register_buffer("cos", cos, persistent=False)
        self.register_buffer("sin", sin, persistent=False)
        for m in self.modules():
            if isinstance(m, nn.Linear):
                nn.init.xavier_normal_(m.weight)
        nn.init.normal_(self.embed.weight, std=D ** -0.5)
        with torch.no_grad():
            for b in self.blocks:
                b.proj.weight.mul_((2 * L) ** -0.5)
                b.down.weight.mul_((2 * L) ** -0.5)

    def forward(self, idx):
        x = self.embed(idx)
        for b in self.blocks:
            x = b(x, self.cos, self.sin)
        return self.norm(x) @ self.embed.weight.T

def to_stream(texts):
    ids = []
    for t in texts:
        ids += tok.encode(t).ids + [EOS]
    return torch.tensor(ids)

train_ids, val_ids = to_stream(train_poems), to_stream(val_poems)
model = Tiny()
steps, batch = 300, 32
plan = torch.Generator().manual_seed(1234)
starts = torch.randint(0, len(train_ids) - CTX - 1, (steps, batch), generator=plan)
opt = torch.optim.AdamW([{"params": [p for p in model.parameters() if p.dim() >= 2], "weight_decay": 0.1},
                         {"params": [p for p in model.parameters() if p.dim() < 2], "weight_decay": 0.0}], lr=3e-3)
for step in range(steps):
    idx = starts[step][:, None] + torch.arange(CTX + 1)
    out = model(train_ids[idx[:, :-1]])
    loss = F.cross_entropy(out.view(-1, V), train_ids[idx[:, 1:]].view(-1))
    opt.zero_grad(set_to_none=True)
    loss.backward()
    torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
    opt.step()
model.eval()
print(f"训练 {steps} 步，最后一步的训练损失 {loss.item():.3f}")
```

```text
训练 300 步，最后一步的训练损失 5.488
```

::: v-pre
取 4 段验证文本，拿出第 0 层算出来的真实 Q、K、V，后面的数值对比都用它们。
:::

<p class="nb-label">In [3]</p>

```python
val_starts = torch.arange(4) * 997                       # 固定的 4 段验证文本
val_batch = val_ids[val_starts[:, None] + torch.arange(CTX + 1)]
with torch.no_grad():
    x0 = model.embed(val_batch[:, :-1])
    q, k, v = model.blocks[0].heads(x0, model.cos, model.sin)
B_, H_, T_, d = q.shape
print(f"第 0 层的 Q、K、V：形状 {tuple(q.shape)}，即 [batch, 头, 位置, 每头维度]")
```

```text
第 0 层的 Q、K、V：形状 (4, 4, 64, 32)，即 [batch, 头, 位置, 每头维度]
```

::: v-pre
## 2. 朴素注意力：先把整张分数表写出来

第 6 章的写法：先算出 $T \times T$ 的分数表，盖上因果掩码，做 softmax，再乘 V。
:::

<p class="nb-label">In [4]</p>

```python
def naive_attention(q, k, v):
    T, d = q.shape[-2], q.shape[-1]
    s = q @ k.transpose(-2, -1) / math.sqrt(d)            # 分数表 [B, H, T, T]
    future = torch.ones(T, T, dtype=torch.bool).triu(1)
    s = s.masked_fill(future, float("-inf"))
    p = s.softmax(dim=-1)                                 # 又一张 [B, H, T, T]
    return p @ v

with torch.no_grad():
    err = (naive_attention(q, k, v) - sdpa(q, k, v)).abs().max().item()
print(f"朴素写法与 F.scaled_dot_product_attention 的最大误差：{err:.1e}")
log["err_naive_sdpa"] = err
```

```text
朴素写法与 F.scaled_dot_product_attention 的最大误差：4.8e-07
```

::: v-pre
两者算的是同一个东西。区别在过程：朴素写法每一步都把结果写成一个完整的张量，下一步再读回来。
下面写一个“记账员”：它挂在 PyTorch 的算子分发上，每执行一个底层算子（aten 算子）就记下读了多少字节、写了多少字节，
并跟踪此刻还活着的中间张量一共占多少字节、最高到过多少。只读视图（transpose、view 这类不搬数据的操作）不记读写。
:::

<p class="nb-label">In [5]</p>

```python
VIEW_OPS = {"view", "_unsafe_view", "transpose", "expand", "t", "slice", "select", "unsqueeze",
            "squeeze", "permute", "alias", "detach", "split", "split_with_sizes", "unbind", "as_strided"}

class MemoryLedger(TorchDispatchMode):
    """记下每个 aten 算子读写的字节数，以及中间张量同时存在时的峰值。"""
    def __init__(self):
        super().__init__()
        self.ops, self.live, self.now, self.peak = [], {}, 0, 0

    def _free(self, key):
        self.now -= self.live.pop(key, 0)

    def __torch_dispatch__(self, func, types, args=(), kwargs=None):
        out = func(*args, **(kwargs or {}))
        ins = [a for a in tree_flatten((args, kwargs))[0] if isinstance(a, torch.Tensor)]
        outs = [o for o in tree_flatten(out)[0] if isinstance(o, torch.Tensor)]
        name = func.overloadpacket.__name__
        if name not in VIEW_OPS:
            self.ops.append((name, sum(t.nbytes for t in ins), sum(t.nbytes for t in outs)))
        for o in outs:                                    # 新分配的存储才算进“活着的”字节
            st = o.untyped_storage()
            if st.data_ptr() in self.live or st.nbytes() == 0:
                continue
            self.live[st.data_ptr()] = st.nbytes()
            self.now += st.nbytes()
            self.peak = max(self.peak, self.now)
            weakref.finalize(st, self._free, st.data_ptr())
        return out

    def traffic(self):
        return sum(r + w for _, r, w in self.ops)
```

::: v-pre
先在真实的 Q、K、V 上看一遍朴素写法调用了哪些算子：
:::

<p class="nb-label">In [6]</p>

```python
with torch.no_grad(), MemoryLedger() as ledger:
    naive_attention(q, k, v)
for name, r, w in ledger.ops:
    print(f"  {name:<14} 读 {r / 1024:7.1f} KiB   写 {w / 1024:7.1f} KiB")
print(f"合计读写 {ledger.traffic() / 1024:.1f} KiB；中间张量峰值 {ledger.peak / 1024:.1f} KiB；"
      f"一张 [B,H,T,T] 分数表 {B_ * H_ * T_ * T_ * 4 / 1024:.1f} KiB")
with torch.no_grad(), MemoryLedger() as ledger:
    sdpa(q, k, v)
print("F.scaled_dot_product_attention 在 CPU 上调用的算子：", [n for n, _, _ in ledger.ops])
```

```text
  bmm            读   256.0 KiB   写   256.0 KiB
  div            读   256.0 KiB   写   256.0 KiB
  ones           读     0.0 KiB   写     4.0 KiB
  triu           读     4.0 KiB   写     4.0 KiB
  masked_fill    读   260.0 KiB   写   256.0 KiB
  _softmax       读   256.0 KiB   写   256.0 KiB
  clone          读   128.0 KiB   写   128.0 KiB
  bmm            读   384.0 KiB   写   128.0 KiB
合计读写 2832.0 KiB；中间张量峰值 1412.0 KiB；一张 [B,H,T,T] 分数表 256.0 KiB
F.scaled_dot_product_attention 在 CPU 上调用的算子： ['_scaled_dot_product_flash_attention_for_cpu']
```

::: v-pre
朴素写法的读写几乎全花在那几张 $T\times T$ 的表上：写一次分数、除以 $\sqrt d$ 再读写一次、盖掩码读写一次、
softmax 读写一次、乘 V 再读一次。而 `scaled_dot_product_attention` 在 CPU 上只调用了一个算子，
PyTorch 把整个注意力交给了一个专门的内核（名字里就写着 flash attention）。

上下文变长时，这张表按平方增长。在同样的 batch 1、4 个头、每头 32 维下，把长度从 256 加到 4096：
:::

<p class="nb-label">In [7]</p>

```python
torch.manual_seed(0)
memory_rows = []
for T in (256, 1024, 4096):
    qs, ks, vs = (torch.randn(1, 4, T, 32) for _ in range(3))
    with torch.no_grad(), MemoryLedger() as a:
        naive_attention(qs, ks, vs)
    with torch.no_grad(), MemoryLedger() as b:
        sdpa(qs, ks, vs)
    table = 4 * T * T * 4                                 # 一张 [1, 4, T, T] 的 FP32 表
    memory_rows.append({"T": T, "naive_peak": a.peak, "sdpa_peak": b.peak, "table": table,
                        "naive_traffic": a.traffic(), "sdpa_traffic": b.traffic()})
    print(f"T={T:>5}：朴素峰值 {a.peak / 2**20:8.2f} MiB（一张表 {table / 2**20:6.2f} MiB）"
          f"   SDPA 峰值 {b.peak / 2**20:5.2f} MiB   朴素读写 {a.traffic() / 2**20:8.1f} MiB")
log["memory"] = memory_rows
```

```text
T=  256：朴素峰值     2.56 MiB（一张表   1.00 MiB）   SDPA 峰值  0.13 MiB   朴素读写      8.8 MiB
T= 1024：朴素峰值    35.00 MiB（一张表  16.00 MiB）   SDPA 峰值  0.52 MiB   朴素读写    134.0 MiB
```

```text
T= 4096：朴素峰值   536.00 MiB（一张表 256.00 MiB）   SDPA 峰值  2.06 MiB   朴素读写   2120.0 MiB
```

::: v-pre
长度翻 4 倍，朴素写法的峰值翻 16 倍，SDPA 只翻 4 倍：它的峰值里只有输出本身（加上每行一个数，后面会讲是什么）。
那张表并不是消失了，而是从来没有完整地出现过。下面亲手写一个不需要整张表的版本。
:::

::: v-pre
## 3. online softmax：不看完整行也能算对

softmax 要先知道一行的最大值和总和。如果一行分数是一块一块到来的，可以边走边改：
维护目前为止的最大值 $m$、以 $m$ 为基准的指数和 $\ell$、以及加权求和的累加器 $o$；
新的一块带来更大的最大值时，把旧的 $\ell$ 和 $o$ 乘以 $e^{m_\text{旧}-m_\text{新}}$ 校正一下。
:::

<p class="nb-label">In [8]</p>

```python
row = 63                                                  # 第 0 句、第 0 个头的最后一个位置：能看到全部 64 个位置
scores = (q[0, 0, row] @ k[0, 0].T) / math.sqrt(d)        # 这一行的 64 个分数
values = v[0, 0]                                          # 64 个位置的 V，每个 32 维

m, l, o = torch.tensor(float("-inf")), torch.tensor(0.0), torch.zeros(d)
trace = []
for start in range(0, 64, 16):                            # 每次只看 16 个分数
    s, vals = scores[start:start + 16], values[start:start + 16]
    m_new = torch.maximum(m, s.max())
    alpha = torch.exp(m - m_new)                          # 旧累加量的校正系数
    p = torch.exp(s - m_new)
    l = alpha * l + p.sum()
    o = alpha * o + p @ vals
    m = m_new
    trace.append((start, s.max().item(), m.item(), alpha.item(), l.item()))
    print(f"第 {start:>2}–{start + 15:>2} 个分数：本块最大 {s.max().item():6.3f}  "
          f"目前最大 m={m.item():6.3f}  校正系数 {alpha.item():.3f}  ℓ={l.item():7.3f}")
online = o / l
exact = scores.softmax(dim=-1) @ values
print(f"online 结果与先算完整 softmax 再加权的最大误差：{(online - exact).abs().max().item():.1e}")
log["online"] = trace
```

```text
第  0–15 个分数：本块最大  1.112  目前最大 m= 1.112  校正系数 0.000  ℓ=  5.721
第 16–31 个分数：本块最大  0.776  目前最大 m= 1.112  校正系数 1.000  ℓ= 10.515
第 32–47 个分数：本块最大  1.267  目前最大 m= 1.267  校正系数 0.856  ℓ= 14.434
第 48–63 个分数：本块最大  2.176  目前最大 m= 2.176  校正系数 0.403  ℓ=  9.421
online 结果与先算完整 softmax 再加权的最大误差：6.0e-08
```

::: v-pre
第一块之前什么都没有，校正系数是 0；之后校正系数小于 1 的那一步，是新的一块里出现了更大的分数：之前所有的指数都要按新的基准缩小。
最后除以 $\ell$，结果和先算完整 softmax 一样，差别只在浮点舍入。

## 4. 分块注意力：把 online softmax 用到每一行

把 Q 按行切成块，每个 Q 块依次和 K、V 的各块打交道，每次只算一个小方块的分数。
因果掩码让对角线右上方的整块根本不用算，直接跳过。同时数一数：每处理一个方块，要从内存搬进来多少数据。
:::

<p class="nb-label">In [9]</p>

```python
def tiled_attention(q, k, v, block=16, stats=None):
    B, H, T, d = q.shape
    out, lse = torch.empty_like(q), torch.empty(B, H, T)
    for i0 in range(0, T, block):
        qi = q[:, :, i0:i0 + block] / math.sqrt(d)                       # 读一个 Q 块
        rows = torch.arange(i0, i0 + qi.shape[2])
        m = torch.full((B, H, len(rows)), float("-inf"))
        l = torch.zeros(B, H, len(rows))
        acc = torch.zeros(B, H, len(rows), d)
        for j0 in range(0, T, block):
            if j0 > rows[-1]:                                             # 整块都在未来：不算
                if stats is not None:
                    stats["skipped"] += 1
                continue
            kj, vj = k[:, :, j0:j0 + block], v[:, :, j0:j0 + block]       # 读一个 K 块、一个 V 块
            s = qi @ kj.transpose(-2, -1)                                 # 只有 block × block 的分数
            cols = torch.arange(j0, j0 + kj.shape[2])
            s = s.masked_fill(cols[None, :] > rows[:, None], float("-inf"))
            m_new = torch.maximum(m, s.amax(dim=-1))
            alpha = torch.exp(m - m_new)
            p = torch.exp(s - m_new[..., None])
            l = alpha * l + p.sum(dim=-1)
            acc = alpha[..., None] * acc + p @ vj
            m = m_new
            if stats is not None:
                stats["tiles"] += 1
                stats["read"] += (kj.numel() + vj.numel()) * 4
        out[:, :, i0:i0 + block] = acc / l[..., None]                     # 写回这一块的输出
        lse[:, :, i0:i0 + block] = m + torch.log(l)                       # 每行只留一个数：log Σ e^s
        if stats is not None:
            stats["read"] += qi.numel() * 4
            stats["write"] += (acc.numel() + l.numel()) * 4
    return out, lse
```

<p class="nb-label">In [10]</p>

```python
stats = {"tiles": 0, "skipped": 0, "read": 0, "write": 0}
with torch.no_grad():
    o_tiled, lse = tiled_attention(q, k, v, block=16, stats=stats)
    o_naive, o_sdpa = naive_attention(q, k, v), sdpa(q, k, v)
print(f"分块（16×16）与朴素写法的最大误差：{(o_tiled - o_naive).abs().max().item():.1e}")
print(f"分块（16×16）与 SDPA 的最大误差：  {(o_tiled - o_sdpa).abs().max().item():.1e}")
per_head = (stats["tiles"], stats["skipped"])            # 循环一次处理全部 batch 和头，所以这就是每个头的数
print(f"64 个位置切成 4×4 = 16 个方块，算了 {per_head[0]} 个，跳过 {per_head[1]} 个（整块都在未来）")
log["tiles_per_head"] = per_head
log["err_tiled"] = [(o_tiled - o_naive).abs().max().item(), (o_tiled - o_sdpa).abs().max().item()]
```

```text
分块（16×16）与朴素写法的最大误差：8.9e-07
分块（16×16）与 SDPA 的最大误差：  9.2e-07
64 个位置切成 4×4 = 16 个方块，算了 10 个，跳过 6 个（整块都在未来）
```

::: v-pre
把它放回整个模型：4 层注意力全部换成分块版本（或朴素版本），在 8 段验证文本上算损失，和 SDPA 版比较。
:::

<p class="nb-label">In [11]</p>

```python
def val_loss(attn):
    global ATTN
    ATTN, saved = attn, ATTN
    idx = val_ids[(torch.arange(8) * 499)[:, None] + torch.arange(CTX + 1)]
    with torch.no_grad():
        logits = model(idx[:, :-1])
    ATTN = saved
    return F.cross_entropy(logits.reshape(-1, V), idx[:, 1:].reshape(-1)).item()

base = val_loss(sdpa)
for name, attn in [("朴素", naive_attention), ("分块 16", lambda q, k, v: tiled_attention(q, k, v, 16)[0])]:
    loss_ = val_loss(attn)
    print(f"{name:<6} 验证损失 {loss_:.6f}，与 SDPA（{base:.6f}）相差 {abs(loss_ - base):.1e}")
```

```text
朴素     验证损失 5.559044，与 SDPA（5.559043）相差 4.8e-07
分块 16  验证损失 5.559043，与 SDPA（5.559043）相差 0.0e+00
```

::: v-pre
## 5. 数一数：分块到底少搬了多少字节

分块不是没有代价：每个 Q 块都要把它左边的 K、V 块重新读一遍。块越大，Q 块越少，K、V 被重读的次数越少；
但一个方块连同它的 Q、K、V、累加器要能一起放进片上的快速存储，块不能无限大。
下面在不同长度和块大小下，把分块版本实际读写的字节数和朴素写法（记账员记下的）放在一起，
顺便确认每种块大小算出来的都和 SDPA 一样。
:::

<p class="nb-label">In [12]</p>

```python
torch.manual_seed(0)
traffic_rows = []
for T in (256, 1024, 4096):
    qs, ks, vs = (torch.randn(1, 4, T, 32) for _ in range(3))
    with torch.no_grad():
        ref = sdpa(qs, ks, vs)
        naive_bytes = next(r["naive_traffic"] for r in memory_rows if r["T"] == T)
        line = f"T={T:>5}  朴素 {naive_bytes / 2**20:7.1f} MiB"
        row = {"T": T, "naive": naive_bytes}
        for blk in (16, 64, 256):
            st = {"tiles": 0, "skipped": 0, "read": 0, "write": 0}
            o_blk, _ = tiled_attention(qs, ks, vs, blk, st)
            assert (o_blk - ref).abs().max() < 1e-5
            row[blk] = st["read"] + st["write"]
            line += f"   块 {blk:>3}: {row[blk] / 2**20:6.1f} MiB"
    traffic_rows.append(row)
    print(line)
working_set = {blk: (3 * blk * 32 + blk * blk + blk * 32) * 4 for blk in (16, 64, 256)}
print("一个方块同时要放在片上的数据（Q、K、V 块 + 分数块 + 累加器，FP32、每头 32 维）：",
      "，".join(f"块 {b}: {s / 1024:.0f} KiB" for b, s in working_set.items()))
log["traffic"] = traffic_rows
log["working_set"] = working_set
```

```text
T=  256  朴素     8.8 MiB   块  16:    2.4 MiB   块  64:    0.9 MiB   块 256:    0.5 MiB
```

```text
T= 1024  朴素   134.0 MiB   块  16:   33.5 MiB   块  64:    9.5 MiB   块 256:    3.5 MiB
```

```text
T= 4096  朴素  2120.0 MiB   块  16:  518.1 MiB   块  64:  134.1 MiB   块 256:   38.1 MiB
一个方块同时要放在片上的数据（Q、K、V 块 + 分数块 + 累加器，FP32、每头 32 维）： 块 16: 9 KiB，块 64: 48 KiB，块 256: 384 KiB
```

::: v-pre
朴素写法的读写随长度平方增长，而且系数大：每张 $T\times T$ 的表都要写一次、读一次，前后好几遍。
分块版本也随长度平方增长（K、V 要被每个 Q 块重读），但系数是“每头维度 ÷ 块大小”，块越大越省。
块 256 时读写只有朴素写法的几十分之一，可它要在片上同时放下几百 KiB 的数据，超过了 GPU 单个计算单元的共享内存。
FlashAttention 的块大小就是按片上内存定的。
:::

::: v-pre
## 6. 训练时：反向传播不存那张表

训练时，自动求导要为反向传播保存一些中间结果。朴素写法会把 softmax 的输出 P（一张 $T\times T$ 的表）存下来；
分块版本每行只多存一个数：前向最后算出的 $\text{lse} = m + \log \ell$。反向需要 P 时，
用 $P = e^{QK^\top/\sqrt d - \text{lse}}$ 当场重算一块就够了。先验证这个式子：
:::

<p class="nb-label">In [13]</p>

```python
with torch.no_grad():
    s_full = (q @ k.transpose(-2, -1) / math.sqrt(d)).masked_fill(
        torch.ones(T_, T_, dtype=torch.bool).triu(1), float("-inf"))
    p_stored = s_full.softmax(dim=-1)                   # 朴素写法为反向存下的 P
    p_recomputed = torch.exp(s_full - lse[..., None])   # 只用每行一个 lse 重算
print(f"用 lse 重算的 P 与存下来的 P 最大误差：{(p_recomputed - p_stored).abs().max().item():.1e}")
print(f"要存的量：P 是 {p_stored.numel():,} 个数，lse 是 {lse.numel():,} 个数")
```

```text
用 lse 重算的 P 与存下来的 P 最大误差：2.3e-06
要存的量：P 是 65,536 个数，lse 是 1,024 个数
```

::: v-pre
再直接量一下：让 PyTorch 在保存反向所需张量时告诉我们存了多少字节，长度 1024 下比较朴素写法和 SDPA，并核对两者的梯度。
:::

<p class="nb-label">In [14]</p>

```python
def saved_bytes(attn, q, k, v):
    seen = {}
    def pack(t):
        seen[t.untyped_storage().data_ptr()] = t.untyped_storage().nbytes()
        return t
    with torch.autograd.graph.saved_tensors_hooks(pack, lambda t: t):
        out = attn(q, k, v)
    out.square().sum().backward()
    return sum(seen.values())

torch.manual_seed(0)
base_qkv = [torch.randn(1, 4, 1024, 32) for _ in range(3)]
grads, saved = {}, {}
for name, attn in [("朴素", naive_attention), ("SDPA", sdpa)]:
    leaves = [t.clone().requires_grad_() for t in base_qkv]
    saved[name] = saved_bytes(attn, *leaves)
    grads[name] = [t.grad for t in leaves]
    print(f"{name:<4} 为反向保存 {saved[name] / 2**20:6.2f} MiB")
gerr = max(((a - b).abs().max() / a.abs().max()).item() for a, b in zip(grads["朴素"], grads["SDPA"]))
print(f"Q、K、V 梯度的最大差（相对于梯度最大值）：{gerr:.1e}；一张 [1,4,1024,1024] 的表是 {4 * 1024 * 1024 * 4 / 2**20:.0f} MiB")
log["saved"] = saved
```

```text
朴素   为反向保存  18.50 MiB
SDPA 为反向保存   2.02 MiB
Q、K、V 梯度的最大差（相对于梯度最大值）：1.4e-06；一张 [1,4,1024,1024] 的表是 16 MiB
```

::: v-pre
朴素写法为反向存下了 softmax 的输出 P 这一整张 $T\times T$ 的表（外加一张布尔掩码），
SDPA 只存 Q、K、V、输出和每行一个 lse，梯度和朴素写法在浮点舍入范围内一致。用多算一遍换少存一张表，
和[第 24 章](https://lewislau86.github.io/tinyllm/large-model-stability)的激活重计算是同一个交换，只是做在了一个算子内部。
:::

::: v-pre
## 7. 算子融合：其余的小算子

注意力之外，每层还有一串逐元素的小运算：RMSNorm、RoPE、SiLU 门控。它们计算量很小，
但在 eager 模式下每个运算都是一个独立的算子：读一遍输入、写一遍输出，下一个再读回来。
用记账员数一数它们实际读写的字节，和“输入只读一遍、输出只写一遍”的下限比一比。
:::

<p class="nb-label">In [15]</p>

```python
torch.manual_seed(0)
blk0 = model.blocks[0]
x_in = torch.randn(32, CTX, D)                         # 一个训练 batch 的激活
q_in = torch.randn(32, H, CTX, D // H)
g_in, u_in = torch.randn(32, CTX, 8 * D // 3), torch.randn(32, CTX, 8 * D // 3)
cos_, sin_ = model.cos, model.sin
cases = [("RMSNorm", lambda x: blk0.norm1(x), (x_in,)),
         ("RoPE", lambda x: apply_rope(x, cos_, sin_), (q_in,)),
         ("SiLU 门控", lambda g, u: F.silu(g) * u, (g_in, u_in))]
fusion_rows = []
for name, fn, args in cases:
    with torch.no_grad(), MemoryLedger() as led:
        out_ = fn(*args)
    lower = sum(a.nbytes for a in args) + out_.nbytes
    fusion_rows.append({"name": name, "ops": len(led.ops), "traffic": led.traffic(), "lower": lower})
    print(f"{name:<8} {len(led.ops)} 个算子 {[n for n, _, _ in led.ops]}")
    print(f"         读写 {led.traffic() / 2**20:5.2f} MiB，下限 {lower / 2**20:5.2f} MiB，"
          f"多搬 {led.traffic() / lower:.1f} 倍")
log["fusion"] = fusion_rows
```

```text
RMSNorm  6 个算子 ['pow', 'mean', 'add_', 'rsqrt', 'mul', 'mul']
         读写  7.05 MiB，下限  2.00 MiB，多搬 3.5 倍
RoPE     7 个算子 ['mul', 'mul', 'sub', 'mul', 'mul', 'add', 'stack']
         读写  9.02 MiB，下限  2.00 MiB，多搬 4.5 倍
SiLU 门控  2 个算子 ['silu', 'mul']
         读写 13.32 MiB，下限  7.99 MiB，多搬 1.7 倍
```

::: v-pre
下限就是融合以后能做到的：把一串逐元素运算写进同一个循环，每个元素读进来、在寄存器里算完、写出去一次。
`torch.compile` 会自动做这件事。它把 Python 函数追踪成计算图，再为能合并的逐元素运算生成一个内核
（CPU 上是 C++ 循环，GPU 上是 Triton 内核）。下面看它为一整层 Block 生成了什么。
:::

<p class="nb-label">In [16]</p>

```python
try:
    from torch._inductor.utils import run_and_get_code
    xb = torch.randn(32, CTX, D)
    with torch.no_grad():
        eager_out = blk0(xb, cos_, sin_)
        with MemoryLedger() as led:
            blk0(xb, cos_, sin_)
        compiled = torch.compile(blk0)
        comp_out, code = run_and_get_code(compiled, xb, cos_, sin_)
    src = "\n".join(code)
    fused = sorted(set(line.split("=")[0].strip() for line in src.splitlines() if "= async_compile.cpp" in line))
    print(f"eager：一层 Block 调用 {len(led.ops)} 个非视图算子")
    print(f"compile：生成 {len(fused)} 个融合内核，矩阵乘和注意力仍调用现成的库函数")
    for name in fused:
        print("  ", name)
    print(f"compile 与 eager 输出的最大误差：{(comp_out - eager_out).abs().max().item():.1e}")
    log["compile"] = {"eager_ops": len(led.ops), "fused": fused}
except Exception as e:                                   # 没有 C++ 编译器等情况
    print("torch.compile 不可用，跳过这一节：", type(e).__name__, str(e).splitlines()[0][:120])
```

```text
eager：一层 Block 调用 37 个非视图算子
compile：生成 6 个融合内核，矩阵乘和注意力仍调用现成的库函数
   cpp_fused__unsafe_view_add_5
   cpp_fused__unsafe_view_add_mean_mul_pow_rsqrt_3
   cpp_fused__unsafe_view_add_mul_slice_split_stack_sub_transpose_view_1
   cpp_fused__unsafe_view_mul_silu_4
   cpp_fused_add_mean_mul_pow_rsqrt_0
   cpp_fused_clone_transpose_2
compile 与 eager 输出的最大误差：3.8e-06
```

::: v-pre
融合内核的名字就是它合并了哪些运算：比如 RMSNorm 里的平方、求均值、加 eps、开方倒数、两次乘法被并成一个内核。
这一节在 CPU 上只验证“合并了什么、结果是否一致”；合并以后快多少，取决于硬件的带宽和内核写得好不好，
要在 GPU 上按[第 13 章](https://lewislau86.github.io/tinyllm/gpu-training)的方法单独测。
:::

<p class="nb-label">In [17]</p>

```python
with open("attention_kernels_log.json", "w", encoding="utf-8") as f:
    json.dump(log, f, ensure_ascii=False)
print("已写出 attention_kernels_log.json")
```

```text
已写出 attention_kernels_log.json
```

