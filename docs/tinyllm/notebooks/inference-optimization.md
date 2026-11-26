---
title: "第 34 章：推理优化：逐项对照与推理服务（notebook 在线查看）"
search: false
editLink: false
prev: false
next: false
pageClass: tinyllm-course
---

<!-- 本页由 scripts/build-tinyllm-code.py 根据 notebook 自动生成，请勿手改。 -->

::: tip 这是 notebook 的只读预览
[返回教案](/tinyllm/inference-optimization) · [在 Colab 中运行](https://colab.research.google.com/github/lewislau86/lewislau86.github.io/blob/master/docs/public/tinyllm/notebooks/inference-optimization.ipynb) · <a href="/tinyllm/notebooks/inference-optimization.ipynb" download>下载 .ipynb</a> · <a href="/tinyllm/code/inference-optimization.py" download>下载 .py</a> · [在 GitHub 上查看](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/tinyllm/notebooks/inference-optimization.ipynb)

下面的代码和输出与 notebook 文件完全一致。想修改、运行，请用 Colab 打开或下载到本地。
:::

::: v-pre
# 第 34 章：推理优化：逐项对照与推理服务

配套教案：https://lewislau86.github.io/tinyllm/inference-optimization

从上到下运行即可（`python inference-optimization.py`），CPU 上约一分半（训练基线模型、算单独跑的基准输出各占一部分）。
需要安装 PyTorch 和 `tokenizers`；服务只用 Python 标准库（http.server），不需要另装 Web 框架。
这个文件是本章代码的唯一来源：教案中的代码片段由 `# region 名字` / `# endregion 名字`
标记的区域直接引用，notebook 也由它生成（scripts/build-tinyllm-code.py）。

本章的硬条件：每一项优化、每一种组合、经 HTTP 返回的结果，都必须和对应模型单独贪心生成的输出逐 token 相同（用 assert 检查）；
INT8 会改变模型本身，所以它对齐的是 INT8 模型自己的贪心输出，质量另外报告。
调度实验的时间沿用第 32 章写明了的成本模型；以“[计时，本机]”开头的输出是本机的墙钟时间，换一台机器会不同。
运行时加 `--serve` 参数，会在 8000 端口起一个一直运行的服务，可以用 curl 调用。
:::

<p class="nb-label">In [1]</p>

```python
import copy
import heapq
import json
import math
import queue
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import torch
from torch import nn
from torch.nn import functional as F
from tokenizers import Tokenizer, decoders, models, pre_tokenizers, trainers
from tokenizers.decoders import DecodeStream

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

模型与第 28～33 章相同（d=128、4 层、4 个头、词表 4096、上下文 64），训练 300 步，种子 0。
一层 Block 照第 32 章拆成两半（`attn_inputs` 和 `finish`），中间的注意力按块表读写 K、V。
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
## 2. 一个可以逐项开关的引擎

前面几章的优化各自写在自己的脚本里。这里把它们装进同一个引擎，每一项都是一个开关：

- `max_running`：同时最多跑几个请求（1 = 一次一个，大于 1 = 第 32 章的连续批）；
- `chunk`：分块 prefill 的额度：decode 行先排，剩下的额度给提示词（第 32 章）；
- `block`：块大小，等于上下文上限时就是按上限预留，小了就是分页（第 33 章）；
- `prefix`：前缀缓存（第 33 章）；
- `quant`：INT8 权重（第 30 章）；
- `gamma`：投机解码每轮起草几个 token，草稿用“在已有文本里查”（第 31 章），不用另训草稿模型。

第 29 章的注意力内核没有做成开关：本章的序列最长 64 个位置，朴素写法和 SDPA 的差别在这个长度上量不出来；
引擎里的注意力一直是 SDPA。块池、块表和前缀缓存的代码与第 33 章相同，正文不再列出。
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

@torch.no_grad()
def paged_step(kv, rows, net):
    """rows: [(seq, 新 token 列表), ...]，调用前每个 seq 都已经 grow 过。和第 33 章相同，
    只多两处：模型 net 作为参数传进来（换成量化后的模型只改这里）；返回每一行所有新位置的 logits（投机解码要验证每个位置）。"""
    n = [len(t) for _, t in rows]
    ids = torch.tensor([x for _, t in rows for x in t])
    pos = torch.cat([torch.arange(s.length, s.length + c) for (s, _), c in zip(rows, n)])
    blk = torch.tensor([s.table[p // kv.bs] for s, t in rows for p in range(s.length, s.length + len(t))])
    off = pos % kv.bs
    cos, sin = net.cos[pos][:, None], net.sin[pos][:, None]
    x = net.embed(ids)
    for i, b in enumerate(net.blocks):
        q, k, v = b.attn_inputs(x, cos, sin)
        kv.k[i][blk, :, off], kv.v[i][blk, :, off] = k, v
        ys, start = [], 0
        for (s, _), c in zip(rows, n):
            end = s.length + c
            table = torch.tensor(s.table[:-(-end // kv.bs)])
            keys = kv.k[i][table].transpose(0, 1).flatten(1, 2)[:, :end]
            vals = kv.v[i][table].transpose(0, 1).flatten(1, 2)[:, :end]
            mask = torch.arange(end)[None] <= pos[start:start + c, None]
            y = F.scaled_dot_product_attention(q[start:start + c].transpose(0, 1), keys, vals, attn_mask=mask)
            ys.append(y.transpose(0, 1).flatten(-2))
            start += c
        x = b.finish(x, torch.cat(ys))
    for s, t in rows:
        s.length += len(t)
        s.tokens += t
    return net.head(x).split(n)
```

<p class="nb-label">In [6]</p>

```python
def lookup_draft(context, gamma, n=2):
    """第 31 章的“在已有文本里查”：找最后 n 个 token 最近一次出现的位置，把它后面的 gamma 个 token 当草稿。"""
    key = context[-n:]
    for start in range(len(context) - n - 1, -1, -1):
        if context[start:start + n] == key:
            return context[start + n:start + n + gamma]
    return []
```

<p class="nb-label">In [7]</p>

```python
BASE = {"max_running": 1, "block": CTX, "pool": 8 * CTX, "chunk": None, "prefix": False, "quant": False, "gamma": 0}

class Replica:
    """一个推理实例：一个块池、一个等待队列、一组正在跑的请求，和一个只属于它的时钟。
    opt 里每一项对应一个优化，BASE 是全部关掉：一次只跑一个请求，KV 按上下文上限预留。"""
    def __init__(self, opt, dry=False):
        self.opt, self.dry = opt, dry
        self.net = model_q if opt["quant"] else model
        self.kv = (PrefixKV if opt["prefix"] else PagedKV)(opt["pool"] // opt["block"], opt["block"])
        self.waiting, self.running, self.clock = [], [], 0.0
        self.w = WEIGHT_UNITS_Q if opt["quant"] else 1.0     # 成本模型：读一遍权重花多少个单位
        self.stats = {"forwards": 0, "tokens": 0, "prefill": 0, "cached": 0, "preempt": 0, "recompute": 0,
                      "drafted": 0, "accepted": 0, "busy": 0.0, "alloc_x_dt": 0.0, "alloc_peak": 0}

    def load(self):
        return len(self.waiting) + len(self.running)

    def add(self, r):
        self.waiting.append(r)

    def _target(self, r):                                     # 这个请求接下来该出的 token（dry 时直接查基准）
        return r["ref_q"] if self.opt["quant"] else r["ref"]

    def step(self):
        """调度一次、前向一次、收结果。返回这一步结束的请求。"""
        opt, kv = self.opt, self.kv
        # ---- 1. 正在生成的请求：起草（投机时），保证块够用，不够就抢占最晚进来的 ----
        for st in list(self.running):
            if st not in self.running or st["todo"]:
                continue
            r = st["r"]
            left = r["n_out"] - len(r["out"])
            draft = lookup_draft(r["prompt"] + r["out"], min(opt["gamma"], left - 1)) if opt["gamma"] else []
            while not kv.grow(st["seq"], 1 + len(draft)):
                if draft:
                    draft = []                                # 块不够时先放弃草稿
                    continue
                victim = self.running.pop()
                victim["r"]["written"] = victim["seq"].length
                kv.drop(victim["seq"]); self.waiting.append(victim["r"]); self.stats["preempt"] += 1
                if victim is st:
                    break
            st["draft"] = draft
        # ---- 2. 放新请求进来：按到达顺序，块池放得下整段提示词才进 ----
        self.waiting.sort(key=lambda r: r["t_arrive"])
        while self.waiting and len(self.running) < opt["max_running"]:
            r, seq = self.waiting[0], Seq()
            feed = r["prompt"] + r["out"]
            hit = kv.match(seq, feed) if opt["prefix"] else 0
            if not kv.grow(seq, len(feed) - seq.length):
                kv.drop(seq)
                break
            self.waiting.pop(0)
            self.stats["prefill"] += len(feed); self.stats["cached"] += hit
            self.stats["recompute"] += max(0, r.get("written", 0) - hit)
            self.running.append({"r": r, "seq": seq, "todo": feed[seq.length:], "draft": []})
        if not self.running:
            return []
        # ---- 3. 这一次前向里每个请求送哪些 token：decode 在前，提示词按额度分块 ----
        rows, budget = [], opt["chunk"]
        for st in sorted(self.running, key=lambda st: len(st["todo"]) > 0):
            if not st["todo"]:
                take = [st["r"]["out"][-1]] + st["draft"]
            else:
                take = st["todo"] if budget is None else st["todo"][:max(budget, 0)]
                if not take:
                    continue
            if budget is not None:
                budget -= len(take)
            rows.append((st, take))
        # ---- 4. 前向 ----
        if self.dry:
            for st, take in rows:
                st["seq"].length += len(take); st["seq"].tokens += take
            logits = None
        else:
            logits = paged_step(kv, [(st["seq"], take) for st, take in rows], self.net)
        n_tok = sum(len(take) for _, take in rows)
        dt = max(self.w, n_tok / K)                           # 成本模型：读一遍权重，或者算 n_tok 个 token，取慢的
        self.clock += dt
        alloc = kv.in_use() * kv.bs
        s = self.stats
        s["forwards"] += 1; s["tokens"] += n_tok; s["busy"] += dt
        s["alloc_x_dt"] += alloc * dt; s["alloc_peak"] = max(s["alloc_peak"], alloc)
        # ---- 5. 收结果：提示词送完才出第一个 token；decode 行逐个位置验证草稿 ----
        finished = []
        for j, (st, take) in enumerate(rows):
            r, seq = st["r"], st["seq"]
            if st["todo"]:
                st["todo"] = st["todo"][len(take):]
                if st["todo"]:
                    continue
                draft = []
            else:
                draft = st["draft"]
            if self.dry:
                target = self._target(r)[len(r["out"]):]
                k = 0
                while k < len(draft) and draft[k] == target[k]:
                    k += 1
                new = target[:k + 1]
            else:
                pred = logits[j][-1 - len(draft):].argmax(-1).tolist()   # 最后一个真 token 和每个草稿位置的预测
                k = 0
                while k < len(draft) and draft[k] == pred[k]:
                    k += 1
                new = draft[:k] + [pred[k]]
            if draft:                                         # 没被接受的草稿：从缓存里退掉
                seq.length -= len(draft) - k
                del seq.tokens[seq.length:]
                while len(seq.table) > -(-seq.length // kv.bs):
                    kv.release(seq.table.pop())
                s["drafted"] += len(draft); s["accepted"] += k
            if r.get("eos") and EOS in new:                   # 服务里的请求遇到 <eos> 就停（实验里的请求按固定长度生成）
                new = new[:new.index(EOS) + 1]
                r["n_out"] = len(r["out"]) + len(new)
            r["out"] += new
            r["times"] += [self.clock] * len(new)
            if opt["prefix"]:
                kv.register(seq)
            if len(r["out"]) >= r["n_out"]:
                kv.drop(seq); self.running.remove(st); finished.append(r)
        return finished
```

<p class="nb-label">In [8]</p>

```python
def run(reqs, opt, n_rep=1, router=None, dry=False, scale=1.0):
    """离散事件模拟：请求按到达时间交给某个实例（router 决定交给谁），每个实例按自己的时钟一步一步跑。
    多轮对话的下一轮在上一轮结束后、用户想一会儿再到。"""
    reqs = [dict(r, out=[], times=[]) for r in reqs]
    reps = [Replica(opt, dry) for _ in range(n_rep)]
    events = [(r["arrive"] * scale, i) for i, r in enumerate(reqs) if "after" not in r]
    heapq.heapify(events)
    follow = {r["after"]: i for i, r in enumerate(reqs) if "after" in r}
    index = {id(r): i for i, r in enumerate(reqs)}
    done = 0
    while done < len(reqs):
        busy = [rep for rep in reps if rep.waiting or rep.running]
        t_step = min((rep.clock for rep in busy), default=math.inf)
        if events and events[0][0] <= t_step:
            t, i = heapq.heappop(events)
            r = reqs[i]; r["t_arrive"] = t
            rep = reps[0] if n_rep == 1 else router(reps, r)
            if not (rep.waiting or rep.running):
                rep.clock = max(rep.clock, t)
            rep.add(r)
            continue
        rep = min(busy, key=lambda x: x.clock)
        for r in rep.step():
            done += 1
            j = follow.get(index[id(r)])
            if j is not None:
                heapq.heappush(events, (rep.clock + reqs[j]["think"], j))
    for r in reqs:
        want = r["ref_q"] if opt["quant"] else r["ref"]
        assert r["out"][:r["n_out"]] == want, "任何优化都不能改变输出（量化时对齐量化模型自己的贪心输出）"
    return reqs, reps
```

::: v-pre
## 3. INT8 模型、请求流和指标

INT8 用第 30 章的按通道对称量化，但比第 30 章更保守：只量化 Block 里的线性层，
嵌入表（也是输出层，第 30 章测出它对量化最敏感）保留 FP32。
这里是“假量化”：把权重量化再还原成浮点，只模拟误差，CPU 上不会变快。它在成本模型里的作用是每次前向读权重的量变少。

成本模型在第 32 章的基础上多一项：一次前向花 $\max(w, N/K)$ 个单位，N 是新 token 数，K=16，
w 是读一遍权重的时间（FP32 时为 1，INT8 时按字节数折算）。显存（KV）统一给 512 个位置。
:::

<p class="nb-label">In [9]</p>

```python
def int8_per_channel(w):
    """第 30 章的 INT8 按通道对称量化（再还原成浮点，只模拟误差）。"""
    s = w.abs().amax(dim=1, keepdim=True).clamp(min=1e-12) / 127
    return torch.round(w / s).clamp(-127, 127) * s

model_q = copy.deepcopy(model)
with torch.no_grad():
    for b in model_q.blocks:
        for lin in (b.qkv, b.proj, b.gate, b.up, b.down):
            lin.weight.copy_(int8_per_channel(lin.weight))
lin_params = sum(lin.weight.numel() for b in model.blocks for lin in (b.qkv, b.proj, b.gate, b.up, b.down))
lin_rows = sum(lin.weight.shape[0] for b in model.blocks for lin in (b.qkv, b.proj, b.gate, b.up, b.down))
bytes_fp32 = n_params * 4
bytes_q = (n_params - lin_params) * 4 + lin_params * 1 + lin_rows * 2   # 嵌入表（也是输出层）和归一化留 FP32，每行一个 16 位缩放因子
WEIGHT_UNITS_Q = bytes_q / bytes_fp32

@torch.no_grad()
def val_loss(net, n_batches=20):
    g = torch.Generator().manual_seed(0)
    val_ids = to_stream(val_poems)
    starts = torch.randint(0, len(val_ids) - CTX - 1, (n_batches, 32), generator=g)
    total = 0.0
    for st in starts:
        idx = st[:, None] + torch.arange(CTX + 1)
        total += F.cross_entropy(net(val_ids[idx[:, :-1]]).view(-1, V), val_ids[idx[:, 1:]].view(-1)).item()
    return total / n_batches

print(f"INT8 按通道量化 Block 里的线性层（{lin_params:,} 个参数），嵌入表 {V * D:,} 个参数保留 FP32：")
print(f"权重 {bytes_fp32 / 2**20:.2f} MiB → {bytes_q / 2**20:.2f} MiB，每次前向读权重的量是原来的 {WEIGHT_UNITS_Q:.2f}")
print(f"验证损失 {val_loss(model):.4f} → {val_loss(model_q):.4f}")
```

```text
INT8 按通道量化 Block 里的线性层（785,920 个参数），嵌入表 524,288 个参数保留 FP32：
权重 5.00 MiB → 2.76 MiB，每次前向读权重的量是原来的 0.55
```

```text
验证损失 5.5852 → 5.5851
```

<p class="nb-label">In [10]</p>

```python
K = 16                                                        # 成本模型的拐点（第 32 章）
STREAM_SEEDS, SCALE = (0, 1, 2), 1.0                          # 过载：平均每个单位到达一个请求（第 32 章第 8 节、第 33 章第 4 节）

@torch.no_grad()
def greedy(net, prompt, n):
    ids = list(prompt)
    for _ in range(n):
        ids.append(net(torch.tensor([ids]))[0, -1].argmax().item())
    return ids[len(prompt):]

def general_requests(seed, n=40):
    """第 32 章的请求流：四分之三短提示词、生成 8～40 个；四分之一长提示词（40 个 token）、生成 4～12 个。"""
    g = torch.Generator().manual_seed(seed)
    reqs, t = [], 0.0
    pool = val_poems[seed * 100:(seed + 1) * 100]
    for i in range(n):
        t += -math.log(1 - torch.rand(1, generator=g).item())
        if torch.rand(1, generator=g).item() < 0.25:
            prompt, n_out = tok.encode(pool[i]).ids[:40], int(torch.randint(4, 13, (1,), generator=g))
        else:
            prompt, n_out = tok.encode(pool[i].split("，")[0] + "，").ids, int(torch.randint(8, 41, (1,), generator=g))
        reqs.append({"arrive": t, "prompt": prompt, "n_out": n_out})
    return reqs

SYSTEM = next(ids for ids in (tok.encode(p).ids for p in train_poems) if len(ids) >= 24)[:24]
def system_requests(seed, n=40):
    """第 33 章的请求流：每个请求开头都是同一段 24 个 token 的“系统提示词”，后面接一首诗的第一句，生成 8～24 个。"""
    g = torch.Generator().manual_seed(100 + seed)
    pool = val_poems[seed * 90:(seed + 1) * 90]
    reqs, t = [], 0.0
    for i in range(n):
        t += -math.log(1 - torch.rand(1, generator=g).item())
        reqs.append({"arrive": t, "prompt": SYSTEM + tok.encode(pool[i].split("，")[0] + "，").ids,
                     "n_out": int(torch.randint(8, 25, (1,), generator=g))})
    return reqs

WORKLOADS = {"通用": general_requests, "系统提示词": system_requests}
streams = {}
for name, make in WORKLOADS.items():
    for s in STREAM_SEEDS:
        reqs = make(s)
        for r in reqs:
            r["ref"], r["ref_q"] = greedy(model, r["prompt"], r["n_out"]), greedy(model_q, r["prompt"], r["n_out"])
        streams[name, s] = reqs
same = [r["ref"] == r["ref_q"] for reqs in streams.values() for r in reqs]
print(f"{len(same)} 个请求里，INT8 模型的贪心输出和 FP32 逐 token 相同的有 {sum(same)} 个")
```

```text
240 个请求里，INT8 模型的贪心输出和 FP32 逐 token 相同的有 224 个
```

<p class="nb-label">In [11]</p>

```python
SLO_TTFT, SLO_TPOT = 20.0, 1.5

def summarize(reqs, reps):
    ttft = [r["times"][0] - r["t_arrive"] for r in reqs]
    tpot = [(r["times"][-1] - r["times"][0]) / (len(r["times"]) - 1) for r in reqs]
    span = max(r["times"][-1] for r in reqs) - min(r["t_arrive"] for r in reqs)
    ok = [r for r, a, b in zip(reqs, ttft, tpot) if a <= SLO_TTFT and b <= SLO_TPOT]
    st = {k: sum(rep.stats[k] for rep in reps) for k in reps[0].stats}
    pct = lambda xs, q: sorted(xs)[min(len(xs) - 1, int(round(q * (len(xs) - 1))))]
    gap = [max(b - a for a, b in zip(r["times"], r["times"][1:])) for r in reqs if len(set(r["times"])) > 1]
    return {"ttft50": pct(ttft, .5), "ttft90": pct(ttft, .9), "tpot50": pct(tpot, .5), "gap_max": max(gap),
            "throughput": sum(r["n_out"] for r in reqs) / span, "goodput": sum(r["n_out"] for r in ok) / span,
            "ok": len(ok), "kv_avg": st["alloc_x_dt"] / st["busy"], "kv_peak": max(rep.stats["alloc_peak"] for rep in reps),
            "forwards": st["forwards"], "computed": st["prefill"] - st["cached"],
            "accept": st["accepted"] / max(st["drafted"], 1), **{k: st[k] for k in ("preempt", "drafted", "accepted")}}
```

::: v-pre
## 4. 一次只打开一项

基线是第 28 章的做法：一次只跑一个请求，KV cache 按上下文上限预留，FP32 权重，普通贪心。
在它上面一次只打开一项，别的都不动。分块 prefill 只在多个请求同时跑时才有意义，所以不单列；
分页单独打开时什么都不改变（只有一个请求），所以和前缀缓存一起打开。
:::

<p class="nb-label">In [12]</p>

```python
FULL = {"max_running": 12, "block": 8, "pool": 8 * CTX, "chunk": K, "prefix": True, "quant": True, "gamma": 3}
ALONE = {"基线": BASE,
         "连续批": dict(BASE, max_running=8),                 # 显存按上限预留时，512 个位置最多放 8 个请求
         "分页 + 前缀缓存": dict(BASE, block=8, prefix=True),
         "INT8 权重": dict(BASE, quant=True),
         "投机（γ=3）": dict(BASE, gamma=3)}
LEAVE_ONE_OUT = {"全部打开": FULL,
                 "去掉连续批": dict(FULL, max_running=1),
                 "去掉分块 prefill": dict(FULL, chunk=None),
                 "去掉分页": dict(FULL, block=CTX),            # 块大小等于上限：显存只放得下 8 个，前缀也无从共享
                 "去掉前缀缓存": dict(FULL, prefix=False),
                 "去掉 INT8": dict(FULL, quant=False),
                 "去掉投机": dict(FULL, gamma=0)}
```

<p class="nb-label">In [13]</p>

```python
wall = {}
def evaluate(opt, workload):
    rows = []
    for s in STREAM_SEEDS:
        t0 = time.perf_counter()
        reqs, reps = run(streams[workload, s], opt, scale=SCALE)
        if s == STREAM_SEEDS[0]:
            wall[json.dumps(opt, sort_keys=True), workload] = time.perf_counter() - t0
        rows.append(summarize(reqs, reps))
    return rows

def show(label, rows):
    a = lambda k: sum(r[k] for r in rows) / len(rows)
    g = [r["goodput"] for r in rows]
    print(f"  {label:<10} TTFT 中位 {a('ttft50'):5.1f}  TPOT 中位 {a('tpot50'):4.2f}  最长卡顿 {a('gap_max'):4.2f}  吞吐 {a('throughput'):5.2f}  "
          f"goodput {a('goodput'):5.2f} [{min(g):5.2f}, {max(g):5.2f}]  KV 平均 {a('kv_avg'):3.0f}  前向 {a('forwards'):3.0f}")

ablation = {}
for workload in WORKLOADS:
    print(f"【{workload}】")
    for label, opt in ALONE.items():
        ablation["alone", workload, label] = rows = evaluate(opt, workload)
        show(label, rows)
print("全部请求的输出都和各自模型的贪心输出逐 token 相同")
```

```text
【通用】
```

```text
  基线         TTFT 中位 398.5  TPOT 中位 1.00  最长卡顿 1.00  吞吐  0.98  goodput  0.05 [ 0.04,  0.06]  KV 平均  64  前向 794
```

```text
  连续批        TTFT 中位  32.2  TPOT 中位 1.15  最长卡顿 3.52  吞吐  5.75  goodput  1.94 [ 1.47,  2.27]  KV 平均 437  前向 119
```

```text
  分页 + 前缀缓存  TTFT 中位 398.5  TPOT 中位 1.00  最长卡顿 1.00  吞吐  0.98  goodput  0.05 [ 0.04,  0.06]  KV 平均  25  前向 794
```

```text
  INT8 权重    TTFT 中位 215.6  TPOT 中位 0.55  最长卡顿 0.55  吞吐  1.74  goodput  0.09 [ 0.07,  0.10]  KV 平均  64  前向 794
```

```text
  投机（γ=3）    TTFT 中位 367.2  TPOT 中位 0.99  最长卡顿 1.00  吞吐  1.08  goodput  0.05 [ 0.04,  0.06]  KV 平均  64  前向 723
【系统提示词】
```

```text
  基线         TTFT 中位 335.5  TPOT 中位 1.00  最长卡顿 1.00  吞吐  0.95  goodput  0.03 [ 0.03,  0.03]  KV 平均  64  前向 657
```

```text
  连续批        TTFT 中位  47.5  TPOT 中位 1.55  最长卡顿 8.17  吞吐  4.43  goodput  0.47 [ 0.32,  0.67]  KV 平均 465  前向  93
```

```text
  分页 + 前缀缓存  TTFT 中位 318.6  TPOT 中位 1.00  最长卡顿 1.00  吞吐  1.00  goodput  0.04 [ 0.03,  0.05]  KV 平均  41  前向 657
```

```text
  INT8 权重    TTFT 中位 193.9  TPOT 中位 0.55  最长卡顿 0.55  吞吐  1.58  goodput  0.10 [ 0.08,  0.13]  KV 平均  64  前向 657
```

```text
  投机（γ=3）    TTFT 中位 331.5  TPOT 中位 1.00  最长卡顿 1.00  吞吐  0.96  goodput  0.03 [ 0.03,  0.03]  KV 平均  64  前向 650
全部请求的输出都和各自模型的贪心输出逐 token 相同
```

::: v-pre
## 5. 全部打开，再一次去掉一项

“单独打开”回答的是“在什么都没有的系统上，这一项值多少”。真正部署时其他几项已经开着，
要问的是“在全部打开的系统上去掉这一项，会损失多少”。全部打开：连续批（最多 12 个）+ 分块 prefill（额度 16 个 token）
+ 分页（块大小 8）+ 前缀缓存 + INT8 权重 + 投机（γ=3）。
:::

<p class="nb-label">In [14]</p>

```python
for workload in WORKLOADS:
    print(f"【{workload}】")
    for label, opt in LEAVE_ONE_OUT.items():
        ablation["loo", workload, label] = rows = evaluate(opt, workload)
        show(label, rows)
spec = {w: ablation["loo", w, "全部打开"] for w in WORKLOADS}
print("投机的接受率（全部打开时）：" + "  ".join(
    f"{w} {sum(r['accepted'] for r in rows) / sum(r['drafted'] for r in rows):.0%}（起草 {sum(r['drafted'] for r in rows) / 3:.0f} 个/流）"
    for w, rows in spec.items()))
```

```text
【通用】
```

```text
  全部打开       TTFT 中位  20.2  TPOT 中位 0.97  最长卡顿 1.27  吞吐  8.31  goodput  4.86 [ 3.66,  6.37]  KV 平均 230  前向 106
```

```text
  去掉连续批      TTFT 中位 199.3  TPOT 中位 0.55  最长卡顿 0.55  吞吐  1.89  goodput  0.10 [ 0.09,  0.11]  KV 平均  25  前向 744
```

```text
  去掉分块 prefill TTFT 中位  18.2  TPOT 中位 1.27  最长卡顿 5.46  吞吐  8.34  goodput  4.71 [ 3.81,  6.42]  KV 平均 246  前向  80
```

```text
  去掉分页       TTFT 中位  21.8  TPOT 中位 0.78  最长卡顿 1.15  吞吐  8.26  goodput  4.17 [ 3.64,  4.99]  KV 平均 464  前向 118
```

```text
  去掉前缀缓存     TTFT 中位  20.2  TPOT 中位 0.97  最长卡顿 1.27  吞吐  8.31  goodput  4.86 [ 3.66,  6.37]  KV 平均 230  前向 106
```

```text
  去掉 INT8    TTFT 中位  20.5  TPOT 中位 0.99  最长卡顿 1.17  吞吐  7.56  goodput  4.33 [ 3.49,  5.52]  KV 平均 220  前向 105
```

```text
  去掉投机       TTFT 中位  16.3  TPOT 中位 0.97  最长卡顿 1.00  吞吐  8.81  goodput  5.87 [ 5.01,  6.87]  KV 平均 237  前向 106
【系统提示词】
```

```text
  全部打开       TTFT 中位   8.0  TPOT 中位 0.90  最长卡顿 1.10  吞吐 10.12  goodput  9.75 [ 8.66, 10.46]  KV 平均 192  前向  76
```

```text
  去掉连续批      TTFT 中位 165.9  TPOT 中位 0.55  最长卡顿 0.55  吞吐  1.83  goodput  0.12 [ 0.10,  0.15]  KV 平均  41  前向 650
```

```text
  去掉分块 prefill TTFT 中位   6.4  TPOT 中位 0.96  最长卡顿 1.77  吞吐 10.34  goodput 10.34 [10.16, 10.68]  KV 平均 189  前向  72
```

```text
  去掉分页       TTFT 中位  39.0  TPOT 中位 1.00  最长卡顿 1.00  吞吐  5.35  goodput  1.66 [ 1.58,  1.75]  KV 平均 474  前向 130
```

```text
  去掉前缀缓存     TTFT 中位  39.0  TPOT 中位 1.00  最长卡顿 1.00  吞吐  5.35  goodput  1.66 [ 1.58,  1.75]  KV 平均 381  前向 130
```

```text
  去掉 INT8    TTFT 中位   9.4  TPOT 中位 1.00  最长卡顿 1.15  吞吐  8.72  goodput  7.90 [ 5.78,  9.29]  KV 平均 189  前向  75
```

```text
  去掉投机       TTFT 中位   6.5  TPOT 中位 0.85  最长卡顿 1.00  吞吐 10.79  goodput 10.79 [10.28, 11.27]  KV 平均 190  前向  76
投机的接受率（全部打开时）：通用 34%（起草 201 个/流）  系统提示词 10%（起草 82 个/流）
```

::: v-pre
根据上面两张表定下本章的配置：去掉投机，分块的额度从 16 放宽到 32（第 32 章的结论：额度要明显大于同时在 decode 的请求数，这里最多 12 个）。
:::

<p class="nb-label">In [15]</p>

```python
CHOICE = dict(FULL, gamma=0, chunk=32)
for workload in WORKLOADS:
    ablation["choice", workload] = rows = evaluate(CHOICE, workload)
    print(f"【{workload}】")
    show("本章的选择", rows)
base_wall = {w: wall[json.dumps(BASE, sort_keys=True), w] for w in WORKLOADS}
for label, opt in [("连续批", ALONE["连续批"]), ("投机（γ=3）", ALONE["投机（γ=3）"]), ("全部打开", FULL), ("本章的选择", CHOICE)]:
    print(f"[计时，本机] {label:<8} 跑完种子 0 的两份请求流：" + "  ".join(
        f"{w} {wall[json.dumps(opt, sort_keys=True), w]:.2f} s（基线 {base_wall[w]:.2f} s）" for w in WORKLOADS))
log["ablation"] = {" | ".join(k): v for k, v in ablation.items()}
log["wall"] = {f"{k[1]} | {k[0]}": v for k, v in wall.items()}
```

```text
【通用】
  本章的选择      TTFT 中位  15.8  TPOT 中位 1.13  最长卡顿 2.00  吞吐  8.73  goodput  6.14 [ 4.80,  6.89]  KV 平均 243  前向  92
```

```text
【系统提示词】
  本章的选择      TTFT 中位   5.0  TPOT 中位 0.87  最长卡顿 1.73  吞吐 11.02  goodput 11.02 [10.70, 11.52]  KV 平均 185  前向  74
[计时，本机] 连续批      跑完种子 0 的两份请求流：通用 0.19 s（基线 0.86 s）  系统提示词 0.18 s（基线 0.66 s）
[计时，本机] 投机（γ=3）  跑完种子 0 的两份请求流：通用 0.70 s（基线 0.86 s）  系统提示词 0.68 s（基线 0.66 s）
[计时，本机] 全部打开     跑完种子 0 的两份请求流：通用 0.21 s（基线 0.86 s）  系统提示词 0.17 s（基线 0.66 s）
[计时，本机] 本章的选择    跑完种子 0 的两份请求流：通用 0.18 s（基线 0.86 s）  系统提示词 0.17 s（基线 0.66 s）
```

::: v-pre
## 6. 多个实例：请求发给谁

一个实例忙不过来，就开几个一样的实例，前面放一个路由器决定每个请求发给谁。
有了前缀缓存以后，“发给谁”会影响命中：多轮对话的下一轮发回上一轮的那个实例，才能用上它留着的块。
比较四种路由：轮询、最少负载、前缀优先（发给能命中最长前缀的实例）、前缀优先 + 负载上限（命中最长的实例比最闲的多排了 4 个以上请求时，改发最闲的）。
两份负载：48 段多轮对话；所有请求共用同一段系统提示词的“热门前缀”。
:::

<p class="nb-label">In [16]</p>

```python
def chat_requests(seed, n_conv=48, turns=3, n_out=8, gap=0.5, think=10.0):
    """第 33 章的多轮对话，放大到 48 段、平均每 0.5 个单位开始一段：第 k 轮的提示词 = 上一轮的提示词 + 模型的回答 + 诗的下一句。"""
    g = torch.Generator().manual_seed(300 + seed)
    reqs, t, poems_iter = [], 0.0, iter(val_poems[seed * 97:] + val_poems[:seed * 97])
    while len(reqs) < n_conv * turns:
        lines = [tok.encode(s + "。").ids for s in next(poems_iter).split("。") if s][:turns]
        if len(lines) < turns or sum(map(len, lines)) + turns * n_out > CTX:
            continue
        t += -math.log(1 - torch.rand(1, generator=g).item()) * gap
        context = []
        for j, line in enumerate(lines):
            prompt = context + line
            r = {"prompt": prompt, "n_out": n_out, "ref_q": greedy(model_q, prompt, n_out)}   # 这里只用 INT8 模型
            if j == 0:
                r["arrive"] = t
            else:
                r["after"], r["think"] = len(reqs) - 1, -math.log(1 - torch.rand(1, generator=g).item()) * think
            reqs.append(r)
            context = prompt + r["ref_q"]                    # 服务用的是 INT8 模型，对话接着它的回答往下走
    return reqs

def hot_requests(seed, gap=0.25):
    """“热门前缀”：把三份系统提示词请求流（共 120 个请求，开头都是同一段系统提示词）合在一起，重新按平均每 0.25 个单位到达一个排时间。"""
    g = torch.Generator().manual_seed(500 + seed)
    reqs, t = [], 0.0
    for r in [r for s in STREAM_SEEDS for r in streams["系统提示词", s]]:
        t += -math.log(1 - torch.rand(1, generator=g).item()) * gap
        reqs.append(dict(r, arrive=t))
    return reqs

ROUTE_WORKLOADS = {"多轮对话": {s: chat_requests(s) for s in STREAM_SEEDS}, "热门前缀": {s: hot_requests(s) for s in STREAM_SEEDS}}
print(f"多轮对话：每份 {len(ROUTE_WORKLOADS['多轮对话'][0])} 个请求（48 段 × 3 轮）；热门前缀：每份 {len(ROUTE_WORKLOADS['热门前缀'][0])} 个请求；"
      f"4 个实例，每个都是本章的选择，KV 显存各 {8 * CTX} 个位置")
```

```text
多轮对话：每份 144 个请求（48 段 × 3 轮）；热门前缀：每份 120 个请求；4 个实例，每个都是本章的选择，KV 显存各 512 个位置
```

<p class="nb-label">In [17]</p>

```python
def cached_prefix(kv, tokens):
    """只看不改：这个实例的前缀缓存能命中 tokens 开头的多少个 token。"""
    key, hit = None, 0
    for j in range((len(tokens) - 1) // kv.bs):
        key = hash((key, *tokens[j * kv.bs:(j + 1) * kv.bs]))
        if key not in kv.cached:
            break
        hit += kv.bs
    return hit

def round_robin():
    state = {"next": 0}
    def route(reps, r):
        state["next"] = (state["next"] + 1) % len(reps)
        return reps[state["next"]]
    return route

def least_loaded():
    return lambda reps, r: min(reps, key=lambda rep: rep.load())

def prefix_aware(slack=None):
    """选能命中最长前缀的实例，一样长时选最闲的；slack 不为空时，命中最长的那个实例如果比最闲的多排了 slack 个以上的请求，就改去最闲的。"""
    def route(reps, r):
        tokens = r["prompt"]
        best = max(reps, key=lambda rep: (cached_prefix(rep.kv, tokens), -rep.load()))
        idle = min(reps, key=lambda rep: rep.load())
        if slack is not None and best.load() - idle.load() > slack:
            return idle
        return best
    return route

ROUTERS = {"轮询": round_robin, "最少负载": least_loaded, "前缀优先": prefix_aware, "前缀优先 + 负载上限": lambda: prefix_aware(slack=4)}
```

<p class="nb-label">In [18]</p>

```python
route_res = {}
for workload, wl in ROUTE_WORKLOADS.items():
    print(f"【{workload}】")
    for name, make in ROUTERS.items():
        rows = []
        for s in STREAM_SEEDS:
            reqs, reps = run(wl[s], CHOICE, n_rep=4, router=make(), dry=s != STREAM_SEEDS[0])   # 种子 0 真跑模型，其余只记账
            m = summarize(reqs, reps)
            m["hit"] = sum(rep.stats["cached"] for rep in reps) / sum(rep.stats["prefill"] for rep in reps)
            work = [rep.stats["tokens"] for rep in reps]
            m["imbalance"] = max(work) / (sum(work) / len(work))
            rows.append(m)
        route_res[workload, name] = rows
        a = lambda k: sum(r[k] for r in rows) / len(rows)
        g = [r["goodput"] for r in rows]
        print(f"  {name:<10} 命中 {a('hit'):4.0%}  TTFT 中位 {a('ttft50'):5.2f}  P90 {a('ttft90'):6.2f}  "
              f"goodput {a('goodput'):5.2f} [{min(g):5.2f}, {max(g):5.2f}]  最忙的实例干的活是平均的 {a('imbalance'):.2f} 倍")
log["routing"] = {" | ".join(k): v for k, v in route_res.items()}
```

```text
【多轮对话】
```

```text
  轮询         命中  10%  TTFT 中位  3.94  P90   8.87  goodput  6.28 [ 5.63,  6.92]  最忙的实例干的活是平均的 1.08 倍
```

```text
  最少负载       命中  15%  TTFT 中位  3.96  P90   8.58  goodput  7.83 [ 7.11,  9.04]  最忙的实例干的活是平均的 1.06 倍
```

```text
  前缀优先       命中  50%  TTFT 中位  1.73  P90   3.74  goodput 11.59 [ 9.92, 12.51]  最忙的实例干的活是平均的 1.12 倍
```

```text
  前缀优先 + 负载上限 命中  48%  TTFT 中位  1.90  P90   4.31  goodput 11.69 [ 9.86, 12.61]  最忙的实例干的活是平均的 1.08 倍
【热门前缀】
```

```text
  轮询         命中  78%  TTFT 中位  2.30  P90   8.04  goodput 41.79 [41.12, 42.84]  最忙的实例干的活是平均的 1.01 倍
```

```text
  最少负载       命中  78%  TTFT 中位  2.30  P90   7.73  goodput 40.09 [39.87, 40.48]  最忙的实例干的活是平均的 1.06 倍
```

```text
  前缀优先       命中  80%  TTFT 中位 62.29  P90 112.34  goodput  2.37 [ 2.23,  2.50]  最忙的实例干的活是平均的 4.00 倍
```

```text
  前缀优先 + 负载上限 命中  78%  TTFT 中位  3.36  P90   8.59  goodput 40.13 [39.62, 41.11]  最忙的实例干的活是平均的 1.06 倍
```

::: v-pre
## 7. 包成服务

最后把本章的选择包成一个 OpenAI 兼容的 HTTP 接口：`POST /v1/chat/completions`（普通和流式两种返回）、`GET /metrics`、`GET /health`。
结构是两种线程：HTTP 线程只负责收请求、发结果；一个后台线程独占模型，一步一步跑 Replica，把每一步新出的 token 放进各请求自己的队列。
只用标准库，方便在任何环境里跑；生产环境一般用 FastAPI + uvicorn 这类异步框架，结构相同。
:::

<p class="nb-label">In [19]</p>

```python
class EngineLoop:
    """后台线程：从收件箱取新请求交给 Replica，一步一步跑，把每一步新出的 token 放进各请求自己的队列。
    HTTP 线程只和收件箱、各请求的队列打交道，不碰模型。"""
    def __init__(self, opt):
        self.rep = Replica(opt)
        self.inbox, self.active = queue.Queue(), []
        self.accepting, self.stopped, self.error = True, threading.Event(), None
        self.lock = threading.Lock()                          # “检查能不能收”和“放进收件箱”要一起做，不能被退出插在中间
        self.counters = {"ok": 0, "rejected": 0, "tokens": 0}
        self.ttft = []
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def submit(self, prompt, max_tokens):
        with self.lock:
            if not self.accepting:
                self.counters["rejected"] += 1
                return None
            r = {"prompt": prompt, "n_out": max_tokens, "eos": True, "out": [], "times": [],
                 "t_arrive": time.monotonic(), "sent": 0, "q": queue.Queue()}
            self.inbox.put(r)
            return r

    def _loop(self):
        try:
            self._run()
        except Exception as e:                                # 引擎线程挂了：不再收请求，/health 变 503，手上的请求都结束掉
            self.error = repr(e)
            with self.lock:
                self.accepting = False
            for r in self.active:
                r["q"].put(None)
            raise

    def _run(self):
        while not (self.stopped.is_set() and not self.active and self.inbox.empty()):
            try:                                              # 没活干时在收件箱上等，不空转
                while True:
                    r = self.inbox.get(timeout=0.05 if not self.active else 0)
                    self.rep.add(r); self.active.append(r)
            except queue.Empty:
                pass
            if not self.active:
                continue
            finished = self.rep.step()
            now = time.monotonic()
            for r in self.active:
                new = r["out"][r["sent"]:]
                if new:
                    if r["sent"] == 0:
                        self.ttft.append(now - r["t_arrive"])
                    r["sent"] = len(r["out"]); self.counters["tokens"] += len(new)
                    r["q"].put(new)
            for r in finished:
                r["q"].put(None); self.active.remove(r); self.counters["ok"] += 1

    def shutdown(self):
        """优雅退出：先不收新请求，正在跑的跑完，再停线程。"""
        with self.lock:
            self.accepting = False
        self.stopped.set()
        self.thread.join()

    def metrics(self):
        kv, c = self.rep.kv, self.counters
        q = lambda p: sorted(self.ttft)[int(p * (len(self.ttft) - 1))] if self.ttft else 0.0
        lines = [f'tinyllm_requests_total{{status="ok"}} {c["ok"]}', f'tinyllm_requests_total{{status="rejected"}} {c["rejected"]}',
                 f"tinyllm_generated_tokens_total {c['tokens']}", f"tinyllm_running_requests {len(self.rep.running)}",
                 f"tinyllm_waiting_requests {len(self.rep.waiting)}", f"tinyllm_kv_blocks_used {kv.in_use()}",
                 f"tinyllm_kv_blocks_cached {len(getattr(kv, 'idle', {}))}", f"tinyllm_kv_blocks_total {kv.num_blocks}", f"tinyllm_prefix_hit_tokens_total {self.rep.stats['cached']}",
                 f"tinyllm_prefill_tokens_total {self.rep.stats['prefill']}", f"tinyllm_preemptions_total {self.rep.stats['preempt']}",
                 f'tinyllm_ttft_seconds{{quantile="0.5"}} {q(0.5):.4f}', f'tinyllm_ttft_seconds{{quantile="0.9"}} {q(0.9):.4f}']
        return "\n".join(lines) + "\n"

class Handler(BaseHTTPRequestHandler):
    engine = None                                             # 启动时塞进来

    def log_message(self, *args):                             # 访问日志交给 /metrics，不往终端刷
        pass

    def _json(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/metrics":
            body = self.engine.metrics().encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; version=0.0.4")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/health":
            status = "ok" if self.engine.accepting else ("dead" if self.engine.error else "draining")
            self._json(200 if status == "ok" else 503, {"status": status})
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/v1/chat/completions":
            return self._json(404, {"error": "not found"})
        req = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        prompt = tok.encode("".join(m["content"] for m in req["messages"])).ids   # 本模型没有对话模板，把内容直接接起来（对话模板见第 44 章）
        max_tokens = min(int(req.get("max_tokens", 16)), CTX - len(prompt))
        if not prompt or max_tokens < 1:
            return self._json(400, {"error": "提示词为空或超过上下文长度"})
        r = self.engine.submit(prompt, max_tokens)
        if r is None:
            return self._json(503, {"error": "服务正在退出，请重试其他实例" if not self.engine.error else "引擎已停止"})
        rid, created = f"chatcmpl-{id(r):x}", int(time.time())
        if not req.get("stream"):
            while r["q"].get() is not None:
                pass
            if self.engine.error:
                return self._json(500, {"error": self.engine.error})
            reason = "stop" if r["out"][-1] == EOS else "length"
            return self._json(200, {"id": rid, "object": "chat.completion", "created": created, "model": "tinyllm",
                                    "choices": [{"index": 0, "message": {"role": "assistant", "content": tok.decode(r["out"])},
                                                 "finish_reason": reason}],
                                    "usage": {"prompt_tokens": len(prompt), "completion_tokens": len(r["out"]),
                                              "total_tokens": len(prompt) + len(r["out"])}})
        self.send_response(200)                                # 流式：Server-Sent Events，每出一批 token 发一条
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        stream = DecodeStream(skip_special_tokens=True)       # 一个汉字可能拆在两个 token 里：攒够完整的字才吐出来
        while (new := r["q"].get()) is not None:
            delta = "".join(c for c in (stream.step(tok, t) for t in new) if c)
            if delta:
                self._sse({"id": rid, "object": "chat.completion.chunk", "created": created, "model": "tinyllm",
                           "choices": [{"index": 0, "delta": {"content": delta}, "finish_reason": None}]})
        reason = "stop" if r["out"] and r["out"][-1] == EOS else "length"
        self._sse({"id": rid, "object": "chat.completion.chunk", "created": created, "model": "tinyllm",
                   "choices": [{"index": 0, "delta": {}, "finish_reason": reason}]})
        self.wfile.write(b"data: [DONE]\n\n"); self.wfile.flush()

    def _sse(self, obj):
        self.wfile.write(f"data: {json.dumps(obj, ensure_ascii=False)}\n\n".encode()); self.wfile.flush()

def start_server(opt, port=0):
    Handler.engine = EngineLoop(opt)
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    httpd.daemon_threads = False                              # 关服务时等每个连接把响应写完
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, Handler.engine
```

<p class="nb-label">In [20]</p>

```python
def post(port, body, stream=False):
    req = urllib.request.Request(f"http://127.0.0.1:{port}/v1/chat/completions", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            if not stream:
                return resp.status, json.loads(resp.read())
            events = [line[6:] for line in resp.read().decode().split("\n") if line.startswith("data: ")]
            text = "".join(json.loads(e)["choices"][0]["delta"].get("content", "") for e in events if e != "[DONE]")
            return resp.status, {"text": text, "events": len(events), "last": events[-1]}
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())

def expected(prompt_text, n):
    ids = greedy(model_q, tok.encode(prompt_text).ids, n)
    return tok.decode(ids[:ids.index(EOS) + 1] if EOS in ids else ids)

httpd, engine = start_server(CHOICE)
port = httpd.server_address[1]
prompts = [p.split("，")[0] + "，" for p in val_poems[200:208]]
results = [None] * len(prompts)
def client(i):
    body = {"model": "tinyllm", "messages": [{"role": "user", "content": prompts[i]}], "max_tokens": 24, "stream": i % 2 == 1}
    results[i] = post(port, body, stream=i % 2 == 1)
t0 = time.perf_counter()
threads = [threading.Thread(target=client, args=(i,)) for i in range(len(prompts))]
for th in threads:
    th.start()
for th in threads:
    th.join()
wall = time.perf_counter() - t0
texts = [res["choices"][0]["message"]["content"] if i % 2 == 0 else res["text"] for i, (code, res) in enumerate(results)]
same = sum(t == expected(p, 24) for t, p in zip(texts, prompts))
assert all(code == 200 for code, _ in results) and same == len(prompts), "经 HTTP 拿到的文本必须和本地直接调用相同"
print(f"8 个并发请求（4 个普通、4 个流式）：全部 200，{same}/8 与本地直接贪心生成的文本相同")
print(f"流式请求 1 收到 {results[1][1]['events']} 条事件，最后一条是 {results[1][1]['last']}")
print(f"请求 0 的回答：{prompts[0]}{texts[0]}")
print(f"[计时，本机] 8 个请求全部返回用了 {wall * 1000:.0f} ms")
print("—— GET /metrics ——")
print(urllib.request.urlopen(f"http://127.0.0.1:{port}/metrics").read().decode().strip())
```

```text
8 个并发请求（4 个普通、4 个流式）：全部 200，8/8 与本地直接贪心生成的文本相同
流式请求 1 收到 8 条事件，最后一条是 [DONE]
请求 0 的回答：宫锦三十段，山中一水开。
[计时，本机] 8 个请求全部返回用了 1057 ms
—— GET /metrics ——
tinyllm_requests_total{status="ok"} 8
tinyllm_requests_total{status="rejected"} 0
tinyllm_generated_tokens_total 56
tinyllm_running_requests 0
tinyllm_waiting_requests 0
tinyllm_kv_blocks_used 0
tinyllm_kv_blocks_cached 8
tinyllm_kv_blocks_total 64
tinyllm_prefix_hit_tokens_total 0
tinyllm_prefill_tokens_total 44
tinyllm_preemptions_total 0
tinyllm_ttft_seconds{quantile="0.5"} 0.0086
tinyllm_ttft_seconds{quantile="0.9"} 0.0107
```

<p class="nb-label">In [21]</p>

```python
long_res = {}
th = threading.Thread(target=lambda: long_res.update(r=post(port, {"messages": [{"role": "user", "content": prompts[0]}], "max_tokens": 40})))
th.start()
while not engine.active:                                      # 等它真的开始跑
    time.sleep(0.001)
closer = threading.Thread(target=engine.shutdown)
closer.start()
while engine.accepting:
    time.sleep(0.001)
late = post(port, {"messages": [{"role": "user", "content": prompts[1]}], "max_tokens": 8})
closer.join(); th.join()
httpd.shutdown(); httpd.server_close()
code, res = long_res["r"]
print(f"退出时正在跑的请求：{code}，生成了 {res['usage']['completion_tokens']} 个 token，finish_reason={res['choices'][0]['finish_reason']}")
print(f"退出开始后才到的请求：{late[0]} {late[1]['error']}")
```

```text
退出时正在跑的请求：200，生成了 7 个 token，finish_reason=stop
退出开始后才到的请求：503 服务正在退出，请重试其他实例
```

<p class="nb-label">In [22]</p>

```python
with open("inference_optimization_log.json", "w", encoding="utf-8") as f:
    json.dump(log, f, ensure_ascii=False)
print("已写出 inference_optimization_log.json")
```

```text
已写出 inference_optimization_log.json
```

<p class="nb-label">In [23]</p>

```python
if "--serve" in sys.argv:                                     # python inference-optimization.py --serve
    httpd, engine = start_server(CHOICE, port=8000)
    print('已在 http://127.0.0.1:8000 启动，试试：curl -N http://127.0.0.1:8000/v1/chat/completions '
          '-H "Content-Type: application/json" -d \'{"messages":[{"role":"user","content":"床前明月光，"}],"stream":true}\'')
    try:
        threading.Event().wait()
    except KeyboardInterrupt:                                 # Ctrl-C：先不收新请求，跑完手上的再退出
        engine.shutdown(); httpd.shutdown(); httpd.server_close()
```

