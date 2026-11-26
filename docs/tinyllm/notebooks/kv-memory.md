---
title: "第 33 章：KV 显存管理：分页与前缀缓存（notebook 在线查看）"
search: false
editLink: false
prev: false
next: false
pageClass: tinyllm-course
---

<!-- 本页由 scripts/build-tinyllm-code.py 根据 notebook 自动生成，请勿手改。 -->

::: tip 这是 notebook 的只读预览
[返回教案](/tinyllm/kv-memory) · [在 Colab 中运行](https://colab.research.google.com/github/lewislau86/lewislau86.github.io/blob/master/docs/public/tinyllm/notebooks/kv-memory.ipynb) · <a href="/tinyllm/notebooks/kv-memory.ipynb" download>下载 .ipynb</a> · <a href="/tinyllm/code/kv-memory.py" download>下载 .py</a> · [在 GitHub 上查看](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/tinyllm/notebooks/kv-memory.ipynb)

下面的代码和输出与 notebook 文件完全一致。想修改、运行，请用 Colab 打开或下载到本地。
:::

::: v-pre
# 第 33 章：KV 显存管理：分页与前缀缓存

配套教案：https://lewislau86.github.io/tinyllm/kv-memory

从上到下运行即可（`python kv-memory.py`），CPU 上约 40 秒（一半多是训练基线模型和算单独跑的基准输出）。
需要安装 PyTorch 和 `tokenizers`。
这个文件是本章代码的唯一来源：教案中的代码片段由 `# region 名字` / `# endregion 名字`
标记的区域直接引用，notebook 也由它生成（scripts/build-tinyllm-code.py）。

本章的硬条件：KV cache 怎么分块、怎么共享、怎么抢占和淘汰，每个请求生成的 token 都必须和它单独跑时逐个相同（用 assert 检查）。
显存用“能放多少个位置的 K、V”来计数，与硬件无关；调度实验的时间沿用第 32 章写明了的成本模型。
第 8 节 offloading 的数字是按公布的硬件参数做的估算，不是实测。
:::

<p class="nb-label">In [1]</p>

```python
import json
import math
import time

import torch
from torch import nn
from torch.nn import functional as F
from tokenizers import Tokenizer, decoders, models, pre_tokenizers, trainers

print("PyTorch", torch.__version__)
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
PyTorch 2.14.1+cpu
```

::: v-pre
## 1. 研究对象：第 12 章的基线模型

模型与第 28～32 章相同（d=128、4 层、4 个头、词表 4096、上下文 64），训练 300 步，种子 0。
本章不改模型，只改 K、V 放在哪里，所以只需要一个训好的模型。一层 Block 照第 32 章拆成两半：
`attn_inputs` 算出加了 RoPE 的 Q、K、V，`finish` 接上注意力的输出；中间 K、V 写到哪里、从哪里读，正是本章要改的地方。
所有结果都要对齐同一个基准：单独跑一个请求，每一步把整段前缀送进模型、取 argmax。
:::

<p class="nb-label">In [2]</p>

```python
poems = load_poems(6000)
train_poems = [p["text"] for p in poems if p["split"] == "train"]
val_poems = [p["text"] for p in poems if p["split"] == "val"]

V, D, L, H, CTX = 4096, 128, 4, 4, 64
DH = D // H
tok = Tokenizer(models.BPE())
tok.pre_tokenizer = pre_tokenizers.ByteLevel(add_prefix_space=False)
tok.decoder = decoders.ByteLevel()
tok.train_from_iterator(train_poems, trainers.BpeTrainer(
    vocab_size=V, special_tokens=["<pad>", "<unk>", "<bos>", "<eos>"],
    initial_alphabet=pre_tokenizers.ByteLevel.alphabet(), show_progress=False))
PAD, EOS = tok.token_to_id("<pad>"), tok.token_to_id("<eos>")

def rope_tables(context, head_dim, base=10000.0):
    theta = base ** (-torch.arange(0, head_dim, 2).float() / head_dim)
    angle = torch.arange(context).float()[:, None] * theta
    return angle.cos(), angle.sin()

def apply_rope(x, cos, sin):                                  # cos、sin 已经按每个位置取好
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

    def attn_inputs(self, x, cos, sin):                       # x: [..., D] → q、k、v: [..., H, DH]
        q, k, v = (t.unflatten(-1, (H, DH)) for t in self.qkv(self.norm1(x)).split(D, dim=-1))
        return apply_rope(q, cos, sin), apply_rope(k, cos, sin), v

    def finish(self, x, y):                                   # y: 注意力的输出 [..., D]
        x = x + self.proj(y)
        h = self.norm2(x)
        return x + self.down(F.silu(self.gate(h)) * self.up(h))

    def forward(self, x, cos, sin):                           # 单条序列、一次算完：[B, T, D]
        q, k, v = (t.transpose(1, 2) for t in self.attn_inputs(x, cos[:, None], sin[:, None]))
        y = F.scaled_dot_product_attention(q, k, v, is_causal=True)
        return self.finish(x, y.transpose(1, 2).flatten(-2))

class Tiny(nn.Module):
    def __init__(self):
        super().__init__()
        self.embed = nn.Embedding(V, D)
        self.blocks = nn.ModuleList(Block() for _ in range(L))
        self.norm = nn.RMSNorm(D)
        cos, sin = rope_tables(CTX, DH)
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

    def head(self, x):
        return self.norm(x) @ self.embed.weight.T              # 输出层与嵌入表共享权重

    def forward(self, idx):
        T = idx.shape[1]
        x = self.embed(idx)
        for b in self.blocks:
            x = b(x, self.cos[:T], self.sin[:T])
        return self.head(x)

def to_stream(texts):
    ids = []
    for t in texts:
        ids += tok.encode(t).ids + [EOS]
    return torch.tensor(ids)

train_ids = to_stream(train_poems)
```

<p class="nb-label">In [3]</p>

```python
def train_model(seed, steps=300, batch=32):
    torch.manual_seed(seed)                                   # 种子只决定初始参数
    model = Tiny()
    plan = torch.Generator().manual_seed(1234)                # batch 顺序和前几章相同
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
    return model.eval()

model = train_model(0)
n_params = sum(p.numel() for p in model.parameters())
print(f"参数 {n_params:,} 个，FP32 权重 {n_params * 4 / 2**20:.2f} MiB")

@torch.no_grad()
def reference(prompt, n):
    """单独跑一个请求：每一步把整段前缀重新送进模型，取 argmax。这是所有拼批结果要对齐的基准。"""
    ids = list(prompt)
    for _ in range(n):
        ids.append(model(torch.tensor([ids]))[0, -1].argmax().item())
    return ids[len(prompt):]
```

```text
参数 1,311,360 个，FP32 权重 5.00 MiB
```

::: v-pre
## 2. 分页：块表把逻辑位置映射到物理块

第 32 章的引擎给每个槽位预留一整段 [64 个位置] 的 K、V。换一种放法：

- 显存是一个**块池**：每层一份 [块数, 头, 块大小, 每头维度] 的张量，块大小取 4、8、16 这样的小数；
- 每个请求有一张**块表**：第 j 个逻辑块（位置 j×块大小 到 (j+1)×块大小−1）放在哪个物理块里；
- 序列变长时，写满了才再要一块；请求结束，把块还给池子；
- 注意力按块表把 K、V 拼回来再算。

这就是 vLLM 的 PagedAttention（Kwon 等，2023）的做法，名字来自操作系统的分页：块是“页”，块表是“页表”。
下面先写块池（只管分配和引用计数），再写按块表读写的一次前向。写时复制（`shared` 那几行）和 `fork` 第 6 节才用到。
:::

<p class="nb-label">In [4]</p>

```python
class Seq:
    """一个请求在缓存里的样子：块表（第几个逻辑块 → 哪个物理块）、已写进缓存的长度、写进去的 token。"""
    def __init__(self):
        self.table, self.length, self.tokens, self.keys = [], 0, [], []

class PagedKV:
    """物理块池：每层一份 [块数, 头, 块大小, 每头维度] 的 K 和 V，一张空闲表，每块一个引用计数。
    它只管“哪一块给谁”，不关心块里算的是什么。"""
    def __init__(self, num_blocks, block_size, shuffle=None):
        self.bs, self.num_blocks = block_size, num_blocks
        self.k = [torch.zeros(num_blocks, H, block_size, DH) for _ in range(L)]
        self.v = [torch.zeros(num_blocks, H, block_size, DH) for _ in range(L)]
        order = torch.randperm(num_blocks, generator=shuffle).tolist() if shuffle else list(range(num_blocks))
        self.free, self.ref, self.copies = order, [0] * num_blocks, 0

    def n_free(self):
        return len(self.free)

    def in_use(self):
        return self.num_blocks - self.n_free()

    def alloc(self):
        b = self.free.pop(0)
        self.ref[b] = 1
        return b

    def release(self, b):
        self.ref[b] -= 1
        if self.ref[b] == 0:
            self.free.append(b)

    def grow(self, seq, n_new):
        """保证 seq 还能再写 n_new 个位置。块不够就返回 False，什么也不改。"""
        j = seq.length // self.bs                                   # 下一个位置落在第 j 个逻辑块
        shared = j < len(seq.table) and self.ref[seq.table[j]] > 1  # 这块还有别人在用：写之前先复制一份
        need = -(-(seq.length + n_new) // self.bs) - len(seq.table)
        if need + shared > self.n_free():
            return False
        if shared:
            old, new = seq.table[j], self.alloc()
            for i in range(L):
                self.k[i][new], self.v[i][new] = self.k[i][old], self.v[i][old]
            self.release(old)
            seq.table[j] = new
            self.copies += 1
        seq.table += [self.alloc() for _ in range(need)]
        return True

    def fork(self, seq):
        """复制一个请求：块表照抄，每块的引用计数加 1，不复制任何 K、V。"""
        child = Seq()
        child.table, child.length = list(seq.table), seq.length
        child.tokens, child.keys = list(seq.tokens), list(seq.keys)
        for b in seq.table:
            self.ref[b] += 1
        return child

    def drop(self, seq):
        for b in reversed(seq.table):                               # 从尾部往前还（第 7 节的淘汰顺序会用到）
            self.release(b)
        seq.table, seq.length, seq.tokens, seq.keys = [], 0, [], []
```

<p class="nb-label">In [5]</p>

```python
@torch.no_grad()
def paged_step(kv, rows):
    """rows: [(seq, 新 token 列表), ...]，调用前每个 seq 都已经 grow 过。
    和第 32 章的引擎一样把新 token 首尾相接排成一行；不同的只是 K、V 按块表写进、读出物理块。"""
    n = [len(t) for _, t in rows]
    ids = torch.tensor([x for _, t in rows for x in t])
    pos = torch.cat([torch.arange(s.length, s.length + c) for (s, _), c in zip(rows, n)])
    blk = torch.tensor([s.table[p // kv.bs] for s, t in rows for p in range(s.length, s.length + len(t))])
    off = pos % kv.bs                                                   # 块内偏移
    cos, sin = model.cos[pos][:, None], model.sin[pos][:, None]
    x = model.embed(ids)
    for i, b in enumerate(model.blocks):
        q, k, v = b.attn_inputs(x, cos, sin)
        kv.k[i][blk, :, off], kv.v[i][blk, :, off] = k, v              # 写：位置 p → 物理块 table[p // 块大小] 的第 p % 块大小 格
        ys, start = [], 0
        for (s, _), c in zip(rows, n):
            end = s.length + c
            table = torch.tensor(s.table[:-(-end // kv.bs)])
            keys = kv.k[i][table].transpose(0, 1).flatten(1, 2)[:, :end]    # 读：按块表把块拼回 [头, 位置, 每头维度]
            vals = kv.v[i][table].transpose(0, 1).flatten(1, 2)[:, :end]
            mask = torch.arange(end)[None] <= pos[start:start + c, None]
            y = F.scaled_dot_product_attention(q[start:start + c].transpose(0, 1), keys, vals, attn_mask=mask)
            ys.append(y.transpose(0, 1).flatten(-2))
            start += c
        x = b.finish(x, torch.cat(ys))
    for s, t in rows:
        s.length += len(t)
        s.tokens += t
    return model.head(x[torch.tensor(n).cumsum(0) - 1])
```

::: v-pre
先证明分页不改变结果。和第 32 章一样：12 个请求，8 个先到、4 个第 6 步加入，各生成 24 个 token。
块大小取 64（每个请求正好一整块，这就是第 32 章“每个槽位预留 64 个位置”的引擎）、16、8、4、1，
块大小小于 64 时把空闲表打乱，让每个请求拿到的物理块散落在池子各处。每一步的 logits 都和块大小 64 比。
:::

<p class="nb-label">In [6]</p>

```python
@torch.no_grad()
def run_together(kv, prompts, join_at, n_new):
    seqs, out, logits_log, live = [Seq() for _ in prompts], [[] for _ in prompts], [[] for _ in prompts], {}
    for t in range(200):
        rows = []
        for i, lg in live.items():
            out[i].append(lg.argmax().item()); logits_log[i].append(lg)
            if len(out[i]) < n_new:
                rows.append((i, [out[i][-1]]))
        rows += [(i, prompts[i]) for i in range(len(prompts)) if join_at[i] == t]
        if not rows:
            return out, logits_log
        for i, toks in rows:
            assert kv.grow(seqs[i], len(toks))
        logits = paged_step(kv, [(seqs[i], toks) for i, toks in rows])
        live = {i: lg for (i, _), lg in zip(rows, logits)}

check_prompts = [tok.encode(p.split("，")[0] + "，").ids for p in val_poems[:12]]
check_refs = [reference(p, 24) for p in check_prompts]
runs = {}
for bs in (64, 16, 8, 4, 1):
    kv = PagedKV(12 * CTX // bs, bs, shuffle=torch.Generator().manual_seed(0) if bs < CTX else None)
    runs[bs] = run_together(kv, check_prompts, [0] * 8 + [6] * 4, 24)
    same = sum(o == r for o, r in zip(runs[bs][0], check_refs))
    diff = max((a - b).abs().max().item() for la, lb in zip(runs[bs][1], runs[64][1]) for a, b in zip(la, lb))
    assert same == 12, "分页以后的输出必须和单独跑逐 token 相同"
    print(f"块大小 {bs:>2}（{kv.num_blocks:>3} 个物理块，{'顺序打乱' if bs < CTX else '每个请求一整块'}）："
          f"{same}/12 与单独跑逐 token 相同，每一步的 logits 与块大小 64 的最大差 {diff:.1e}")
```

```text
块大小 64（ 12 个物理块，每个请求一整块）：12/12 与单独跑逐 token 相同，每一步的 logits 与块大小 64 的最大差 0.0e+00
块大小 16（ 48 个物理块，顺序打乱）：12/12 与单独跑逐 token 相同，每一步的 logits 与块大小 64 的最大差 0.0e+00
块大小  8（ 96 个物理块，顺序打乱）：12/12 与单独跑逐 token 相同，每一步的 logits 与块大小 64 的最大差 0.0e+00
```

```text
块大小  4（192 个物理块，顺序打乱）：12/12 与单独跑逐 token 相同，每一步的 logits 与块大小 64 的最大差 0.0e+00
块大小  1（768 个物理块，顺序打乱）：12/12 与单独跑逐 token 相同，每一步的 logits 与块大小 64 的最大差 0.0e+00
```

::: v-pre
## 3. 预留了多少，用了多少

换到第 32 章的请求流上看显存。请求流完全相同（泊松到达，四分之三短提示词、生成 8～40 个；四分之一长提示词、生成 4～12 个），
时间也沿用它的成本模型：一次前向花 $\max(1, N/K)$ 个单位，N 是这次前向的新 token 数，K=16。
显存总共 512 个位置（第 32 章的 8 个槽位 × 64），调度是不分块的连续批：
每一步先管正在生成的请求：每个都要多写一个位置，没有空块时**抢占**最晚进来的那个请求：
还掉它所有的块，放回等待队列，下次进来时把“提示词 + 已经生成的 token”重新算一遍（重算）。
然后才放新请求进来：按到达顺序，块池放得下它的提示词才进来，放不下就停。
输出不受影响，最后用 assert 检查。`dry=True` 时不跑模型、直接用基准输出，只记账（第 7 节的大量组合用它）。
:::

<p class="nb-label">In [7]</p>

```python
K = 16                                                        # 成本模型的拐点，和第 32 章相同
def step_cost(n_tokens, k=K):
    return max(1.0, n_tokens / k)

def make_requests(seed, n=40):
    """和第 32 章完全相同的请求流。"""
    g = torch.Generator().manual_seed(seed)
    reqs, t = [], 0.0
    pool = val_poems[seed * 100:(seed + 1) * 100]
    for i in range(n):
        t += -math.log(1 - torch.rand(1, generator=g).item())   # 指数分布的到达间隔，平均 1 个单位
        text = pool[i]
        if torch.rand(1, generator=g).item() < 0.25:
            prompt = tok.encode(text).ids[:40]
            n_out = int(torch.randint(4, 13, (1,), generator=g))
        else:
            prompt = tok.encode(text.split("，")[0] + "，").ids
            n_out = int(torch.randint(8, 41, (1,), generator=g))
        reqs.append({"arrive": t, "prompt": prompt, "n_out": n_out})
    return reqs

STREAM_SEEDS = (0, 1, 2)
streams = {s: make_requests(s) for s in STREAM_SEEDS}
for s in STREAM_SEEDS:
    for r in streams[s]:
        r["ref"] = reference(r["prompt"], r["n_out"])
r0 = streams[0]
print(f"种子 0：40 个请求，每个请求最终长度（提示词 + 输出）平均 {sum(len(r['prompt']) + r['n_out'] for r in r0) / 40:.1f} 个 token，"
      f"最长 {max(len(r['prompt']) + r['n_out'] for r in r0)}；按上下文上限预留，每个请求 {CTX} 个位置")
```

```text
种子 0：40 个请求，每个请求最终长度（提示词 + 输出）平均 32.3 个 token，最长 51；按上下文上限预留，每个请求 64 个位置
```

<p class="nb-label">In [8]</p>

```python
@torch.no_grad()
def serve(reqs, kv, max_running=32, scale=1.0, k=K, dry=False):
    """连续批（不分块），显存由 kv 管。scale 把到达间隔整体拉长；多轮对话的下一轮（带 "after" 的请求）在上一轮结束后才到。"""
    n = len(reqs)
    arrive = [r["arrive"] * scale if "after" not in r else None for r in reqs]
    out, times = [[] for _ in reqs], [[] for _ in reqs]
    waiting, running, clock, done = [], [], 0.0, 0
    arrived, written = [False] * n, [0] * n                   # written：被抢占时已经写进缓存的长度
    trace = {"t": [], "dt": [], "running": [], "used": [], "alloc": [], "future": []}
    stats = {"preempt": 0, "recompute": 0, "prefill": 0, "cached": 0}
    while done < n:
        for i in range(n):
            if not arrived[i] and arrive[i] is not None and arrive[i] <= clock:
                arrived[i] = True; waiting.append(i)
        # ---- 先管正在跑的：每个都要多写一个位置；没有空块就抢占最晚进来的 ----
        for st in list(running):
            if st not in running:
                continue
            while not kv.grow(st["seq"], 1):
                victim = running.pop()
                written[victim["i"]] = victim["seq"].length
                kv.drop(victim["seq"]); waiting.append(victim["i"])
                stats["preempt"] += 1
                if victim is st:
                    break
        # ---- 再放新的：按到达顺序（被抢占的请求到得早，排在前面），放不下就停 ----
        waiting.sort(key=lambda i: arrive[i])
        while waiting and len(running) < max_running:
            i, seq = waiting[0], Seq()
            feed = reqs[i]["prompt"] + out[i]                 # 被抢占过的请求：已生成的 token 也要重算
            hit = kv.match(seq, feed) if hasattr(kv, "match") else 0   # 前缀缓存（第 5 节）
            if not kv.grow(seq, len(feed) - seq.length):
                kv.drop(seq)
                break
            waiting.pop(0)
            stats["prefill"] += len(feed); stats["cached"] += hit
            stats["recompute"] += max(0, written[i] - hit)
            running.append({"i": i, "seq": seq, "todo": feed[seq.length:]})
        if not running:                                       # 没事可做：时间跳到下一个到达
            clock = max(clock, min(arrive[i] for i in range(n) if not arrived[i] and arrive[i] is not None))
            continue
        # ---- 一次前向 ----
        rows = [(st["seq"], st["todo"] or [out[st["i"]][-1]]) for st in running]
        if dry:
            for s, toks in rows:
                s.length += len(toks); s.tokens += toks
            new = [reqs[st["i"]]["ref"][len(out[st["i"]])] for st in running]
        else:
            new = paged_step(kv, rows).argmax(-1).tolist()
        dt = step_cost(sum(len(toks) for _, toks in rows), k)
        clock += dt
        trace["t"].append(clock); trace["dt"].append(dt); trace["running"].append(len(running))
        trace["used"].append(sum(st["seq"].length for st in running))     # 真正存着 K、V 的位置
        trace["alloc"].append(kv.in_use() * kv.bs)                         # 分配出去的位置
        trace["future"].append(sum(len(reqs[st["i"]]["prompt"]) + reqs[st["i"]]["n_out"] - 1 - st["seq"].length
                                   for st in running))                     # 以后还会写的位置（最后一个输出不用写进缓存）
        # ---- 收结果 ----
        for st, t in zip(list(running), new):
            i = st["i"]
            st["todo"] = []
            out[i].append(t); times[i].append(clock)
            if hasattr(kv, "register"):
                kv.register(st["seq"])                        # 前缀缓存：登记新写满的块（第 5 节）
            if len(out[i]) == reqs[i]["n_out"]:
                kv.drop(st["seq"]); running.remove(st); done += 1
                for j in range(n):
                    if reqs[j].get("after") == i:             # 多轮对话：用户想一会儿再发下一轮
                        arrive[j] = clock + reqs[j]["think"]
    assert all(out[i] == reqs[i]["ref"] for i in range(n)), "显存怎么管都不能改变任何请求的输出"
    return {"times": times, "arrive": arrive, "trace": trace, "stats": stats}
```

<p class="nb-label">In [9]</p>

```python
def pct(xs, q):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(q * (len(xs) - 1))))]

def summarize(res):
    ttft = [t[0] - a for t, a in zip(res["times"], res["arrive"])]
    tpot = [(t[-1] - t[0]) / (len(t) - 1) for t in res["times"] if len(t) > 1]
    span = max(t[-1] for t in res["times"]) - min(res["arrive"])
    tr = res["trace"]
    w = tr["dt"]                                                         # 按每一步的时长加权平均，空闲的时间不算
    avg = lambda xs: sum(x * d for x, d in zip(xs, w)) / sum(w)
    return {"ttft50": pct(ttft, .5), "ttft90": pct(ttft, .9), "tpot50": pct(tpot, .5), "tpot90": pct(tpot, .9),
            "throughput": sum(len(t) for t in res["times"]) / span, "running": avg(tr["running"]),
            "used": avg(tr["used"]), "alloc": avg(tr["alloc"]), "future": avg(tr["future"]), **res["stats"]}

def mean_range(rows, key, fmt="{:.1f}"):
    xs = [r[key] for r in rows]
    return f"{fmt.format(sum(xs) / len(xs))} [{fmt.format(min(xs))}, {fmt.format(max(xs))}]"
```

::: v-pre
第 32 章的重负载（平均每 2 个单位到达一个请求），块大小从 64 换到 1，看分配出去的位置里有多少真的存着 K、V。
块大小 64 时把“分配了但空着”的部分再拆成两份：以后这个请求还会写到的，和到它结束都用不上的。
:::

<p class="nb-label">In [10]</p>

```python
POOL = 8 * CTX                                                # 显存：512 个位置
HEAVY, OVERLOAD = 2.0, 1.0
waste = {}
for bs in (64, 16, 8, 4, 1):
    rows = [summarize(serve(streams[s], PagedKV(POOL // bs, bs), scale=HEAVY)) for s in STREAM_SEEDS]
    waste[bs] = rows
    a = lambda key: sum(r[key] for r in rows) / 3
    used, alloc, fut = a("used"), a("alloc"), a("future")
    line = f"块大小 {bs:>2}：平均分配 {alloc:5.1f} 个位置，存着 K、V 的 {used / alloc:4.0%}"
    if bs == CTX:
        line += f"，以后才会写的 {fut / alloc:.0%}，到结束都用不上的 {(alloc - used - fut) / alloc:.0%}"
    else:
        line += f"，最后一块没写满的 {1 - used / alloc:.0%}"
    print(line + f"  │  TTFT 中位 {a('ttft50'):.1f}  吞吐 {a('throughput'):.2f}")
log["waste"] = waste
log["trace"] = {bs: serve(streams[0], PagedKV(POOL // bs, bs), scale=HEAVY)["trace"] for bs in (64, 8)}
```

```text
块大小 64：平均分配 428.9 个位置，存着 K、V 的  33%，以后才会写的 19%，到结束都用不上的 47%  │  TTFT 中位 13.7  吞吐 5.64
```

```text
块大小 16：平均分配 259.3 个位置，存着 K、V 的  75%，最后一块没写满的 25%  │  TTFT 中位 3.0  吞吐 6.71
```

```text
块大小  8：平均分配 229.9 个位置，存着 K、V 的  86%，最后一块没写满的 14%  │  TTFT 中位 3.0  吞吐 6.65
```

```text
块大小  4：平均分配 214.6 个位置，存着 K、V 的  94%，最后一块没写满的 6%  │  TTFT 中位 3.0  吞吐 6.72
```

```text
块大小  1：平均分配 201.1 个位置，存着 K、V 的 100%，最后一块没写满的 0%  │  TTFT 中位 3.0  吞吐 6.75
```

::: v-pre
## 4. 省下来的显存怎么用

把到达压到每个单位一个请求（过载），沿用第 32 章的时延目标：TTFT 不超过 20 个单位、TPOT 不超过 1.5 个单位，
两个都满足的请求，它的 token 才算进 goodput。比较几种配置：

- 块大小 64、512 个位置：显存最多放 8 个请求，就是第 32 章 B=8 的那一档；
- 块大小 8、只给一半显存（256 个位置）、最多 8 个请求同时在跑：同样的并发，看一半显存够不够；
- 块大小 8、512 个位置，最多同时跑 32、16、12 个请求：显存放得下就放，放满了靠抢占腾地方。
:::

<p class="nb-label">In [11]</p>

```python
SLO_TTFT, SLO_TPOT = 20.0, 1.5

def goodput(res):
    ok = [t for t, a in zip(res["times"], res["arrive"])
          if t[0] - a <= SLO_TTFT and (len(t) < 2 or (t[-1] - t[0]) / (len(t) - 1) <= SLO_TPOT)]
    return sum(len(t) for t in ok) / (max(t[-1] for t in res["times"]) - min(res["arrive"])), len(ok)

CONFIGS = [(64, 512, 32), (8, 256, 8), (8, 512, 32), (8, 512, 16), (8, 512, 12)]   # (块大小, 显存位置数, 最多同时在跑)
capacity = {}
for bs, pool, cap in CONFIGS:
    rows = []
    for s in STREAM_SEEDS:
        res = serve(streams[s], PagedKV(pool // bs, bs), max_running=cap, scale=OVERLOAD)
        m = summarize(res)
        m["goodput"], m["ok"] = goodput(res)
        rows.append(m)
    capacity[f"{bs}-{pool}-{cap}"] = rows
    a = lambda key: sum(r[key] for r in rows) / 3
    print(f"块 {bs:>2}、显存 {pool}、最多 {cap:>2} 个：同时在跑 {a('running'):4.1f}  占用 {a('alloc'):3.0f}  │  "
          f"吞吐 {a('throughput'):.2f}  TTFT 中位 {a('ttft50'):4.1f}  TPOT 中位 {a('tpot50'):.2f}  │  "
          f"goodput {mean_range(rows, 'goodput', '{:.2f}')}（达标 {a('ok'):4.1f}/40）  抢占 {a('preempt'):4.1f} 次、重算 {a('recompute'):3.0f} 个 token")
print("全部请求的输出都和单独跑逐 token 相同")
log["capacity"] = capacity
```

```text
块 64、显存 512、最多 32 个：同时在跑  6.8  占用 437  │  吞吐 5.75  TTFT 中位 32.2  TPOT 中位 1.15  │  goodput 1.94 [1.47, 2.27]（达标 12.7/40）  抢占  0.0 次、重算   0 个 token
```

```text
块  8、显存 256、最多  8 个：同时在跑  6.8  占用 169  │  吞吐 5.64  TTFT 中位 33.2  TPOT 中位 1.16  │  goodput 1.90 [1.43, 2.27]（达标 12.7/40）  抢占  1.0 次、重算  29 个 token
```

```text
块  8、显存 512、最多 32 个：同时在跑 15.7  占用 364  │  吞吐 7.49  TTFT 中位  6.0  TPOT 中位 2.20  │  goodput 0.17 [0.00, 0.47]（达标  1.0/40）  抢占  7.7 次、重算 120 个 token
```

```text
块  8、显存 512、最多 16 个：同时在跑 11.6  占用 282  │  吞吐 7.56  TTFT 中位 10.1  TPOT 中位 1.48  │  goodput 2.06 [0.87, 3.90]（达标 11.7/40）  抢占  0.0 次、重算   0 个 token
```

```text
块  8、显存 512、最多 12 个：同时在跑  9.5  占用 233  │  吞吐 7.13  TTFT 中位 19.2  TPOT 中位 1.31  │  goodput 3.98 [2.90, 5.53]（达标 19.7/40）  抢占  0.0 次、重算   0 个 token
全部请求的输出都和单独跑逐 token 相同
```

::: v-pre
## 5. 前缀共享：开头一样的请求共用块

两个请求开头的 token 一样，开头那几块的 K、V 就一样（因果注意力里，位置 p 的 K、V 只取决于第 0～p 个 token）。
于是可以让它们的块表前几项指向同一批物理块，只算后面不一样的部分。做法：

- 只登记**写满的块**。块的键是“前一块的键 + 这一块的 token”的哈希，所以同一个键代表同一段完整前缀；
- 新请求进来时，从头一块一块查，查到第一块对不上就停；命中的块引用计数加 1，接到它的块表上；
  至少留最后一个 token 不命中，因为要用它算出第一个输出的 logits；
- 引用计数降到 0 的块先不清空，留在 `idle` 里等人命中；真没空块了才淘汰（第 7 节）。
:::

<p class="nb-label">In [12]</p>

```python
class PrefixKV(PagedKV):
    """在块池上加前缀缓存。policy 决定没空块时淘汰谁：
    "lru" 最久没被用到的；"fifo" 最早登记的；"all" 一次把留着的全部清空；"none" 不留，用完就清。"""
    def __init__(self, num_blocks, block_size, policy="lru"):
        super().__init__(num_blocks, block_size)
        self.policy = policy
        self.cached, self.key_of, self.born = {}, {}, {}      # 键 → 块；块 → 键；块 → 登记的先后
        self.idle, self.evictions = {}, 0                     # idle：没人用但留着的块，字典的顺序就是被还回来的先后
        self.n_registered = 0

    def n_free(self):
        return len(self.free) + len(self.idle)

    def alloc(self):
        if not self.free:                                     # 没有空块：淘汰留着的块
            if self.policy == "fifo":
                victims = [min(self.idle, key=self.born.get)]
            elif self.policy == "all":
                victims = list(self.idle)
            else:
                victims = [next(iter(self.idle))]
            for b in victims:
                del self.idle[b], self.cached[self.key_of.pop(b)]
                self.free.append(b)
            self.evictions += len(victims)
        return super().alloc()

    def release(self, b):
        self.ref[b] -= 1
        if self.ref[b] == 0:
            if b in self.key_of and self.policy != "none":
                self.idle[b] = None                           # 留着，排到队尾
            else:
                if b in self.key_of:
                    del self.cached[self.key_of.pop(b)]
                self.free.append(b)

    def match(self, seq, tokens):
        """新请求进来时从头按块查缓存，命中的块直接接到它的块表上，返回命中的 token 数。"""
        key = None
        for j in range((len(tokens) - 1) // self.bs):         # 至少留最后一个 token 去算 logits
            key = hash((key, *tokens[j * self.bs:(j + 1) * self.bs]))
            b = self.cached.get(key)
            if b is None:
                break
            if self.ref[b] == 0:
                del self.idle[b]
            self.ref[b] += 1
            seq.table.append(b); seq.keys.append(key)
        seq.length = len(seq.table) * self.bs
        seq.tokens = list(tokens[:seq.length])
        return seq.length

    def register(self, seq):
        """每次前向之后，把这个请求新写满的块登记进缓存。生成出来的 token 也算，多轮对话要靠它。"""
        while len(seq.keys) < seq.length // self.bs:
            j = len(seq.keys)
            key = hash((seq.keys[-1] if seq.keys else None, *seq.tokens[j * self.bs:(j + 1) * self.bs]))
            seq.keys.append(key)
            if key not in self.cached:                        # 同样内容已经有一块了，这块就不登记
                b = seq.table[j]
                self.cached[key], self.key_of[b] = b, key
                self.n_registered += 1
                self.born[b] = self.n_registered
```

::: v-pre
两种最常见的命中场景：

- **固定的系统提示词**：每个请求开头都是同一段 24 个 token 的“系统提示词”（这里借一首诗的开头充当），后面接一首诗的第一句；
- **多轮对话**：第 1 轮送诗的第一句，模型写 8 个 token；下一轮的提示词 = 上一轮的提示词 + 模型的输出 + 诗的下一句，共 3 轮。
  对话的开始时间是泊松过程（平均每 3 个单位一个），每轮结束后用户平均想 10 个单位再发下一轮。

块大小 8，显存 512 个位置，和不开前缀缓存的同一个块池比较。
:::

<p class="nb-label">In [13]</p>

```python
SYSTEM = next(ids for ids in (tok.encode(p).ids for p in train_poems) if len(ids) >= 24)[:24]   # 第一首够 24 个 token 的诗

def system_prompt_requests(seed, n=40):
    g = torch.Generator().manual_seed(100 + seed)
    pool = val_poems[seed * 90:(seed + 1) * 90]
    reqs, t = [], 0.0
    for i in range(n):
        t += -math.log(1 - torch.rand(1, generator=g).item())
        prompt = SYSTEM + tok.encode(pool[i].split("，")[0] + "，").ids
        n_out = int(torch.randint(8, 25, (1,), generator=g))
        reqs.append({"arrive": t, "prompt": prompt, "n_out": n_out, "ref": reference(prompt, n_out)})
    return reqs

def chat_requests(seed, n_conv=14, turns=3, n_out=8, think=10.0):
    g = torch.Generator().manual_seed(200 + seed)
    reqs, t, poems_iter = [], 0.0, iter(val_poems[seed * 90:(seed + 1) * 90])
    while len(reqs) < n_conv * turns:
        sents = [s + "。" for s in next(poems_iter).split("。") if s][:turns]
        lines = [tok.encode(s).ids for s in sents]
        if len(lines) < turns or sum(map(len, lines)) + turns * n_out > CTX:
            continue                                          # 三轮放不进 64 个位置的诗跳过
        t += -math.log(1 - torch.rand(1, generator=g).item()) * 3.0
        context = []
        for j, line in enumerate(lines):
            prompt = context + line
            r = {"prompt": prompt, "n_out": n_out, "ref": reference(prompt, n_out)}
            if j == 0:
                r["arrive"] = t
            else:
                r["after"], r["think"] = len(reqs) - 1, -math.log(1 - torch.rand(1, generator=g).item()) * think
            reqs.append(r)
            context = prompt + r["ref"]
    return reqs

sys_streams = {s: system_prompt_requests(s) for s in STREAM_SEEDS}
chat_streams = {s: chat_requests(s) for s in STREAM_SEEDS}
c0 = chat_streams[0]
print(f"系统提示词：每个请求 {len(SYSTEM)} 个共同的 token + 平均 {sum(len(r['prompt']) for r in sys_streams[0]) / 40 - len(SYSTEM):.1f} 个各自的 token")
print(f"多轮对话：14 段对话 × 3 轮；种子 0 三轮提示词平均长 "
      + "、".join(f"{sum(len(r['prompt']) for r in c0[j::3]) / 14:.1f}" for j in range(3)) + " 个 token")
```

```text
系统提示词：每个请求 24 个共同的 token + 平均 5.8 个各自的 token
多轮对话：14 段对话 × 3 轮；种子 0 三轮提示词平均长 11.6、30.5、50.2 个 token
```

<p class="nb-label">In [14]</p>

```python
prefix_res = {}
for name, wl, scale in [("系统提示词", sys_streams, HEAVY), ("多轮对话", chat_streams, 1.0)]:
    for label, make in [("不共享", lambda: PagedKV(POOL // 8, 8)), ("前缀缓存", lambda: PrefixKV(POOL // 8, 8))]:
        rows = [summarize(serve(wl[s], make(), scale=scale)) for s in STREAM_SEEDS]
        for r in rows:
            r["hit"] = r["cached"] / r["prefill"]
        prefix_res[(name, label)] = rows
        print(f"{name} {label:<4}：命中 {mean_range(rows, 'hit', '{:.0%}')}  实际 prefill {mean_range(rows, 'prefill', '{:.0f}')} 中算了 "
              f"{sum(r['prefill'] - r['cached'] for r in rows) / 3:.0f}  平均占用 {mean_range(rows, 'alloc', '{:.0f}')} 个位置  "
              f"TTFT 中位 {mean_range(rows, 'ttft50', '{:.2f}')}  吞吐 {mean_range(rows, 'throughput', '{:.2f}')}  抢占 {mean_range(rows, 'preempt')}")
print("全部请求的输出都和单独跑逐 token 相同")
log["prefix"] = {f"{k[0]}-{k[1]}": v for k, v in prefix_res.items()}
```

```text
系统提示词 不共享 ：命中 0% [0%, 0%]  实际 prefill 1466 [1403, 1509] 中算了 1466  平均占用 420 [411, 433] 个位置  TTFT 中位 23.20 [10.23, 33.78]  吞吐 4.41 [4.26, 4.50]  抢占 8.7 [7.0, 10.0]
```

```text
系统提示词 前缀缓存：命中 79% [79%, 79%]  实际 prefill 1188 [1186, 1191] 中算了 252  平均占用 141 [126, 149] 个位置  TTFT 中位 1.53 [1.46, 1.65]  吞吐 6.57 [5.98, 6.91]  抢占 0.0 [0.0, 0.0]
```

```text
多轮对话 不共享 ：命中 0% [0%, 0%]  实际 prefill 1311 [1289, 1353] 中算了 1311  平均占用 281 [255, 296] 个位置  TTFT 中位 5.54 [4.76, 6.89]  吞吐 2.70 [2.53, 2.87]  抢占 0.3 [0.0, 1.0]
```

```text
多轮对话 前缀缓存：命中 37% [34%, 41%]  实际 prefill 1294 [1289, 1302] 中算了 820  平均占用 214 [195, 238] 个位置  TTFT 中位 2.34 [2.10, 2.57]  吞吐 3.28 [2.98, 3.57]  抢占 0.0 [0.0, 0.0]
全部请求的输出都和单独跑逐 token 相同
```

::: v-pre
## 6. 写时复制：一个提示词，采好几条

同一个提示词要采 4 条不同的回答（并行采样）。提示词的 K、V 对 4 条都一样，没必要算 4 遍、存 4 份：
prefill 一次，然后 `fork` 出另外 3 条，块表照抄、引用计数加 1。
麻烦在最后一块：提示词 37 个 token，块大小 8，第 5 块只写了 5 格，4 条接下来都要往这块里写各自的 token。
所以写之前先看引用计数：大于 1 就先复制一份再写（`grow` 里 `shared` 那几行），这就是**写时复制**（copy-on-write）。
每条用自己的随机数生成器，和单独采样逐 token 比较。
:::

<p class="nb-label">In [15]</p>

```python
def sample_next(logits, g, temperature=0.8):
    return torch.multinomial(F.softmax(logits / temperature, -1), 1, generator=g).item()

@torch.no_grad()
def reference_sample(prompt, n, seed):
    """单独采样一条：每一步把整段前缀送进模型，用自己的随机数生成器抽下一个 token。"""
    g, ids = torch.Generator().manual_seed(seed), list(prompt)
    for _ in range(n):
        ids.append(sample_next(model(torch.tensor([ids]))[0, -1], g))
    return ids[len(prompt):]

@torch.no_grad()
def parallel_sample(prompt, n_samples, n_new, share=True, bs=8):
    """share=True：提示词只 prefill 一次，其余几条 fork 出来；share=False：每条各自 prefill。返回输出、块数峰值、复制次数。"""
    kv = PagedKV(128, bs)
    gens = [torch.Generator().manual_seed(s) for s in range(n_samples)]
    if share:
        root = Seq()
        kv.grow(root, len(prompt))
        first = paged_step(kv, [(root, prompt)])[0]
        seqs, logits = [root] + [kv.fork(root) for _ in range(n_samples - 1)], [first] * n_samples
    else:
        seqs = [Seq() for _ in range(n_samples)]
        for s in seqs:
            kv.grow(s, len(prompt))
        logits = paged_step(kv, [(s, prompt) for s in seqs])
    outs = [[sample_next(lg, g)] for lg, g in zip(logits, gens)]
    peak = kv.in_use()
    for _ in range(n_new - 1):
        for s in seqs:
            assert kv.grow(s, 1)
        logits = paged_step(kv, [(s, [o[-1]]) for s, o in zip(seqs, outs)])
        for o, lg, g in zip(outs, logits, gens):
            o.append(sample_next(lg, g))
        peak = max(peak, kv.in_use())
    return outs, peak, kv.copies

fork_prompt = tok.encode(val_poems[5]).ids[:37]
fork_log = {}
for share in (False, True):
    outs, peak, copies = parallel_sample(fork_prompt, 4, 16, share=share)
    same = sum(o == reference_sample(fork_prompt, 16, s) for s, o in enumerate(outs))
    assert same == 4, "每一条都要和单独采样逐 token 相同"
    fork_log["share" if share else "separate"] = {"peak": peak, "copies": copies}
    print(f"{'fork 共用提示词的块' if share else '每条各自 prefill'}：4 条采样 {same}/4 与单独采样逐 token 相同，"
          f"块数峰值 {peak}，写时复制 {copies} 次")
log["fork"] = fork_log
```

```text
每条各自 prefill：4 条采样 4/4 与单独采样逐 token 相同，块数峰值 28，写时复制 0 次
```

```text
fork 共用提示词的块：4 条采样 4/4 与单独采样逐 token 相同，块数峰值 16，写时复制 3 次
```

::: v-pre
## 7. 淘汰：显存不够时留谁

前缀缓存的命中全靠“留着的块”。显存紧了，留着的块要让给正在跑的请求，留谁、清谁就是淘汰策略。
在多轮对话上比较四种：不保留（用完就清）、缺块时一次全部清空、最早登记的先清（FIFO）、最久没被用到的先清（LRU）。
显存从 256 个位置调到 768 个位置。这里组合多，用 `dry=True` 只记账：调度不改变输出，这一点上面已经用模型核对过。
:::

<p class="nb-label">In [16]</p>

```python
POLICIES = {"none": "不保留", "all": "一次清空", "fifo": "FIFO", "lru": "LRU"}
eviction = {}
for pool in (256, 320, 384, 448, 512, 640, 768):
    row = {}
    for pol in POLICIES:
        hits = []
        for s in STREAM_SEEDS:
            r = summarize(serve(chat_streams[s], PrefixKV(pool // 8, 8, pol), dry=True))
            hits.append(r["cached"] / r["prefill"])
        row[pol] = hits
    eviction[pool] = row
    print(f"显存 {pool:>3} 个位置：" + "  ".join(f"{POLICIES[p]} {sum(h) / 3:5.1%}" for p, h in row.items()))
log["eviction"] = eviction
```

```text
显存 256 个位置：不保留  0.0%  一次清空  8.5%  FIFO 12.6%  LRU 12.2%
显存 320 个位置：不保留  0.0%  一次清空 14.2%  FIFO 16.7%  LRU 18.2%
显存 384 个位置：不保留  0.0%  一次清空 16.3%  FIFO 19.5%  LRU 24.4%
显存 448 个位置：不保留  0.0%  一次清空 21.4%  FIFO 24.8%  LRU 29.7%
显存 512 个位置：不保留  0.0%  一次清空 27.8%  FIFO 29.5%  LRU 36.7%
显存 640 个位置：不保留  0.0%  一次清空 45.5%  FIFO 50.3%  LRU 49.9%
显存 768 个位置：不保留  0.0%  一次清空 53.4%  FIFO 53.4%  LRU 53.4%
```

::: v-pre
## 8. offloading 的边界：搬回来还是重算

显存放不下的 K、V 还可以搬到内存甚至 SSD 上（offloading），要用时再搬回来；另一条路是直接扔掉，要用时重算（第 3 节的抢占就是重算）。
哪条路便宜，比的是每个 token：

- 搬回来：KV 字节数 ÷ 链路带宽；
- 重算：约 $2N$ 次浮点运算（N 是参数量），再加注意力的 $2 \cdot \text{层数} \cdot d \cdot n$（前缀长 n，平均每个 token 看一半前缀），÷ 算力。

下面是**估算**，不是实测：算力按 H100 SXM 的 BF16 稠密峰值 989 TFLOPS 的一半，链路按 PCIe 5.0 x16 的理论单向带宽 64 GB/s（H100 SXM 和主机之间就是这条）和一块 PCIe 4.0 NVMe SSD 的约 7 GB/s，前缀长 4096（TinyLLM 取 64）。
:::

<p class="nb-label">In [17]</p>

```python
def kv_bytes_per_token(layers, kv_heads, head_dim, nbytes):
    return 2 * layers * kv_heads * head_dim * nbytes          # K 和 V，每层每个 KV 头一份

FLOPS = 989e12 * 0.5
LINKS = {"PCIe": 64e9, "SSD": 7e9}
MODELS = [("TinyLLM（FP32）", n_params, kv_bytes_per_token(L, H, DH, 4), L, D, CTX),
          ("Llama 2 7B（MHA，32 个 KV 头）", 6.74e9, kv_bytes_per_token(32, 32, 128, 2), 32, 4096, 4096),
          ("Llama 3 8B（GQA，8 个 KV 头）", 8.03e9, kv_bytes_per_token(32, 8, 128, 2), 32, 4096, 4096),
          ("Llama 3 70B（GQA，8 个 KV 头）", 70.6e9, kv_bytes_per_token(80, 8, 128, 2), 80, 8192, 4096)]
offload = {}
for name, N, kvb, layers, d, prefix in MODELS:
    recompute = (2 * N + 2 * layers * d * prefix) / FLOPS
    move = {link: kvb / bw for link, bw in LINKS.items()}
    offload[name] = {"kv_bytes": kvb, "recompute_us": recompute * 1e6, **{f"{k}_us": v * 1e6 for k, v in move.items()}}
    print(f"{name:<22} 每个 token 的 KV {kvb / 1024:6.1f} KiB │ 重算 {recompute * 1e6:8.4f} µs │ "
          f"从内存搬回 {move['PCIe'] * 1e6:7.3f} µs（重算是它的 {recompute / move['PCIe']:5.2f} 倍）│ "
          f"从 SSD 搬回 {move['SSD'] * 1e6:7.3f} µs（{recompute / move['SSD']:5.2f} 倍）")
log["offload"] = offload
```

```text
TinyLLM（FP32）          每个 token 的 KV    4.0 KiB │ 重算   0.0054 µs │ 从内存搬回   0.064 µs（重算是它的  0.08 倍）│ 从 SSD 搬回   0.585 µs（ 0.01 倍）
Llama 2 7B（MHA，32 个 KV 头） 每个 token 的 KV  512.0 KiB │ 重算  29.4312 µs │ 从内存搬回   8.192 µs（重算是它的  3.59 倍）│ 从 SSD 搬回  74.898 µs（ 0.39 倍）
Llama 3 8B（GQA，8 个 KV 头） 每个 token 的 KV  128.0 KiB │ 重算  34.6486 µs │ 从内存搬回   2.048 µs（重算是它的 16.92 倍）│ 从 SSD 搬回  18.725 µs（ 1.85 倍）
Llama 3 70B（GQA，8 个 KV 头） 每个 token 的 KV  320.0 KiB │ 重算 296.3978 µs │ 从内存搬回   5.120 µs（重算是它的 57.89 倍）│ 从 SSD 搬回  46.811 µs（ 6.33 倍）
```

<p class="nb-label">In [18]</p>

```python
with open("kv_memory_log.json", "w", encoding="utf-8") as f:
    json.dump(log, f, ensure_ascii=False)
print("已写出 kv_memory_log.json")
```

```text
已写出 kv_memory_log.json
```

