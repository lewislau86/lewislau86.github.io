---
title: "第 31 章：投机解码（notebook 在线查看）"
search: false
editLink: false
prev: false
next: false
pageClass: tinyllm-course
---

<!-- 本页由 scripts/build-tinyllm-code.py 根据 notebook 自动生成，请勿手改。 -->

::: tip 这是 notebook 的只读预览
[返回教案](/tinyllm/speculative-decoding) · [在 Colab 中运行](https://colab.research.google.com/github/lewislau86/lewislau86.github.io/blob/master/docs/public/tinyllm/notebooks/speculative-decoding.ipynb) · <a href="/tinyllm/notebooks/speculative-decoding.ipynb" download>下载 .ipynb</a> · <a href="/tinyllm/code/speculative-decoding.py" download>下载 .py</a> · [在 GitHub 上查看](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/tinyllm/notebooks/speculative-decoding.ipynb)

下面的代码和输出与 notebook 文件完全一致。想修改、运行，请用 Colab 打开或下载到本地。
:::

::: v-pre
# 第 31 章：投机解码

配套教案：https://lewislau86.github.io/tinyllm/speculative-decoding

从上到下运行即可（`python speculative-decoding.py`），CPU 上约两分钟（大部分是训练目标模型和 6 个草稿模型）。
需要安装 PyTorch 和 `tokenizers`。
这个文件是本章代码的唯一来源：教案中的代码片段由 `# region 名字` / `# endregion 名字`
标记的区域直接引用，notebook 也由它生成（scripts/build-tinyllm-code.py）。

本章有两条硬条件：贪心解码时，带投机的输出必须和不带投机时逐 token 相同（用 assert 检查）；
采样时用拒绝采样保持目标模型的分布（用大量样本检查）。
前向次数、接受率与硬件无关；墙钟时间只在同一台机器上、热身之后比较，单独打印，换一台机器会不同。
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
## 1. 模型：带回滚的 KV cache

结构与第 28～30 章相同（[第 12 章](https://lewislau86.github.io/tinyllm/tinyllm-model)的配置），只多了两件事：
宽度、层数、头数可以设置（草稿模型要更小），前向时可以带一个 KV cache。
投机解码会把猜错的 token 也送进模型，所以缓存要能**回滚**：`crop(n)` 只保留前 n 个位置。
一次送进 T 个新 token 时，第 i 个新位置能看到缓存里的全部位置和它前面的新位置，掩码是向右平移了 `past` 格的下三角。
:::

<p class="nb-label">In [2]</p>

```python
poems = load_poems(6000)
train_poems = [p["text"] for p in poems if p["split"] == "train"]
val_poems = [p["text"] for p in poems if p["split"] == "val"]

V, CTX = 4096, 64
tok = Tokenizer(models.BPE())
tok.pre_tokenizer = pre_tokenizers.ByteLevel(add_prefix_space=False)
tok.decoder = decoders.ByteLevel()
tok.train_from_iterator(train_poems, trainers.BpeTrainer(
    vocab_size=V, special_tokens=["<pad>", "<unk>", "<bos>", "<eos>"],
    initial_alphabet=pre_tokenizers.ByteLevel.alphabet(), show_progress=False))
EOS = tok.token_to_id("<eos>")

def rope_tables(context, head_dim, base=10000.0):
    theta = base ** (-torch.arange(0, head_dim, 2).float() / head_dim)
    angle = torch.arange(context).float()[:, None] * theta
    return angle.cos(), angle.sin()

def apply_rope(x, cos, sin):                                  # cos、sin 已经按位置切好
    x1, x2 = x[..., 0::2], x[..., 1::2]
    return torch.stack([x1 * cos - x2 * sin, x1 * sin + x2 * cos], dim=-1).flatten(-2)

class KVCache:
    """每层一对 K、V，形状 [B, 头, 已缓存的位置数, 每头维度]。"""
    def __init__(self, n_layers):
        self.k, self.v = [None] * n_layers, [None] * n_layers

    def __len__(self):
        return 0 if self.k[0] is None else self.k[0].shape[2]

    def crop(self, n):                                        # 回滚：只保留前 n 个位置
        self.k = [t if t is None else t[:, :, :n] for t in self.k]
        self.v = [t if t is None else t[:, :, :n] for t in self.v]

class Block(nn.Module):
    def __init__(self, d, heads):
        super().__init__()
        self.h = heads
        self.norm1, self.norm2 = nn.RMSNorm(d), nn.RMSNorm(d)
        self.qkv = nn.Linear(d, 3 * d, bias=False)
        self.proj = nn.Linear(d, d, bias=False)
        self.gate = nn.Linear(d, 8 * d // 3, bias=False)
        self.up = nn.Linear(d, 8 * d // 3, bias=False)
        self.down = nn.Linear(8 * d // 3, d, bias=False)

    def forward(self, x, cos, sin, cache=None, i=0):
        B, T, d = x.shape
        q, k, v = (t.view(B, T, self.h, d // self.h).transpose(1, 2) for t in self.qkv(self.norm1(x)).split(d, dim=-1))
        q, k = apply_rope(q, cos, sin), apply_rope(k, cos, sin)
        if cache is not None:                                 # 新位置的 K、V 接在缓存后面
            if cache.k[i] is not None:
                k, v = torch.cat([cache.k[i], k], dim=2), torch.cat([cache.v[i], v], dim=2)
            cache.k[i], cache.v[i] = k, v
        past = k.shape[2] - T
        if past == 0:
            y = F.scaled_dot_product_attention(q, k, v, is_causal=True)
        else:                                                 # 第 i 个新位置能看到前 past + i + 1 个位置
            mask = torch.ones(T, past + T, dtype=torch.bool).tril(diagonal=past)
            y = F.scaled_dot_product_attention(q, k, v, attn_mask=mask)
        x = x + self.proj(y.transpose(1, 2).reshape(B, T, d))
        h = self.norm2(x)
        return x + self.down(F.silu(self.gate(h)) * self.up(h))

class Tiny(nn.Module):
    def __init__(self, d=128, layers=4, heads=4):
        super().__init__()
        self.embed = nn.Embedding(V, d)
        self.blocks = nn.ModuleList(Block(d, heads) for _ in range(layers))
        self.norm = nn.RMSNorm(d)
        cos, sin = rope_tables(CTX, d // heads)
        self.register_buffer("cos", cos, persistent=False)
        self.register_buffer("sin", sin, persistent=False)
        for m in self.modules():
            if isinstance(m, nn.Linear):
                nn.init.xavier_normal_(m.weight)
        nn.init.normal_(self.embed.weight, std=d ** -0.5)
        with torch.no_grad():
            for b in self.blocks:
                b.proj.weight.mul_((2 * layers) ** -0.5)
                b.down.weight.mul_((2 * layers) ** -0.5)

    def forward(self, idx, cache=None, exit_after=None):      # exit_after=k：只走前 k 层（第 6 节用）
        pos = 0 if cache is None else len(cache)
        T = idx.shape[1]
        cos, sin = self.cos[pos:pos + T], self.sin[pos:pos + T]
        x = self.embed(idx)
        for i, b in enumerate(self.blocks[:exit_after]):
            x = b(x, cos, sin, cache, i)
        return self.norm(x) @ self.embed.weight.T              # 输出层与嵌入表共享权重

def to_stream(texts):
    ids = []
    for t in texts:
        ids += tok.encode(t).ids + [EOS]
    return torch.tensor(ids)

train_ids, val_ids = to_stream(train_poems), to_stream(val_poems)
```

::: v-pre
目标模型就是第 12 章的基线：d=128、4 层、4 个头，训练 300 步。种子 0，和第 30 章种子 0 的模型完全相同。
:::

<p class="nb-label">In [3]</p>

```python
def make_optimizer(model):
    return torch.optim.AdamW([{"params": [p for p in model.parameters() if p.dim() >= 2], "weight_decay": 0.1},
                              {"params": [p for p in model.parameters() if p.dim() < 2], "weight_decay": 0.0}], lr=3e-3)

def batch_plan(steps=300, batch=32):                          # 所有模型共用同一组 batch
    plan = torch.Generator().manual_seed(1234)
    starts = torch.randint(0, len(train_ids) - CTX - 1, (steps, batch), generator=plan)
    return starts[:, :, None] + torch.arange(CTX + 1)

def train_models(seeds, d=128, layers=4, heads=4, teacher=None):
    """每个种子训练一个模型，按同一组 batch 同步推进（结果和逐个训练相同）。
    teacher 为 None 时学语料里的下一个 token；否则学 teacher 的整个输出分布（蒸馏，第 4 节），
    teacher 的输出每个 batch 只算一次，几个模型共用。"""
    nets = {}
    for seed in seeds:
        torch.manual_seed(seed)                               # 种子只决定初始参数
        nets[seed] = Tiny(d, layers, heads)
    opts = {seed: make_optimizer(m) for seed, m in nets.items()}
    for idx in batch_plan():
        x = train_ids[idx[:, :-1]]
        if teacher is None:
            label = train_ids[idx[:, 1:]].reshape(-1)
        else:
            with torch.no_grad():
                label = F.softmax(teacher(x), dim=-1).view(-1, V)   # 软标签：交叉熵等价于最小化 KL(p ‖ q)
        for seed, model in nets.items():
            loss = F.cross_entropy(model(x).view(-1, V), label)
            opts[seed].zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opts[seed].step()
    return {seed: m.eval() for seed, m in nets.items()}

target = train_models([0])[0]
n_params = lambda m: sum(p.numel() for p in m.parameters())
print(f"目标模型：d=128、4 层，参数 {n_params(target):,} 个")
```

```text
目标模型：d=128、4 层，参数 1,311,360 个
```

::: v-pre
## 2. 为什么能“一次验证好几个”

第 28 章说过，单请求 decode 每一步只处理一个位置，却要把全部权重读一遍。那么一次送进好几个位置呢？
先数一数计算量：前向的乘加次数和位置数成正比。再在同一台机器上量一下时间（先热身，取多次平均）。
:::

<p class="nb-label">In [4]</p>

```python
@torch.no_grad()
def time_feed(model, n_new, past=16, repeat=60, exit_after=None):
    """缓存里已有 past 个位置时，一次送进 n_new 个新位置要多久（毫秒）。测 5 组、每组 repeat 次取平均，报最快的一组。"""
    cache = KVCache(len(model.blocks))
    model(torch.zeros(1, past, dtype=torch.long), cache, exit_after)
    ids = torch.zeros(1, n_new, dtype=torch.long)
    for _ in range(20):                                       # 热身
        model(ids, cache, exit_after); cache.crop(past)
    best = float("inf")
    for _ in range(5):
        t0 = time.perf_counter()
        for _ in range(repeat):
            model(ids, cache, exit_after); cache.crop(past)
        best = min(best, (time.perf_counter() - t0) / repeat * 1000)
    return best

feed_ms = {n: time_feed(target, n) for n in (1, 2, 4, 8)}
for n, ms in feed_ms.items():
    print(f"[计时，本机] 一次送进 {n} 个位置：计算量是 1 个位置的 {n} 倍，耗时 {ms:.3f} ms（{ms / feed_ms[1]:.2f} 倍）")
log["feed_ms"] = feed_ms
```

```text
[计时，本机] 一次送进 1 个位置：计算量是 1 个位置的 1 倍，耗时 0.937 ms（1.00 倍）
[计时，本机] 一次送进 2 个位置：计算量是 1 个位置的 2 倍，耗时 0.945 ms（1.01 倍）
[计时，本机] 一次送进 4 个位置：计算量是 1 个位置的 4 倍，耗时 0.948 ms（1.01 倍）
[计时，本机] 一次送进 8 个位置：计算量是 1 个位置的 8 倍，耗时 0.999 ms（1.07 倍）
```

::: v-pre
计算量涨了 8 倍，时间几乎不变：这么小的模型，每次前向的时间主要花在“调用一次”本身（几十个小算子的启动、读一遍权重），
而不是乘法。GPU 上单请求 decode 也是这个形状，只是原因换成了显存带宽（第 28 章）。
既然多验证几个位置几乎不要钱，问题就变成：这几个位置上该放什么 token？
:::

::: v-pre
## 3. 贪心投机解码

先写好不带投机的贪心解码作为基准。`Session` 把“一个模型 + 它自己的缓存”包在一起：
`feed` 送进新 token、返回这些位置的 logits，`rollback(n)` 把缓存截回前 n 个位置。
:::

<p class="nb-label">In [5]</p>

```python
class Session:
    """一个模型 + 它自己的 KV cache。calls 记录前向的次数。"""
    def __init__(self, model, exit_after=None):
        self.model, self.exit_after = model, exit_after
        self.cache = KVCache(len(model.blocks))
        self.calls = 0

    def __len__(self):
        return len(self.cache)

    @torch.no_grad()
    def feed(self, ids):                                      # 返回 [len(ids), V]
        self.calls += 1
        return self.model(torch.tensor([ids]), self.cache, self.exit_after)[0]

    def rollback(self, n):
        self.cache.crop(n)

def greedy(model, prompt, n):
    """普通贪心解码：每次前向出一个 token。返回 (新生成的 n 个 token, 前向次数)。"""
    s, seq = Session(model), list(prompt)
    logits = s.feed(seq)                                      # prefill，同时给出第 1 个 token
    while True:
        seq.append(logits[-1].argmax().item())
        if len(seq) - len(prompt) == n:
            return seq[len(prompt):], s.calls
        logits = s.feed(seq[-1:])
```

::: v-pre
草稿模型每轮从当前文本出发，连续贪心猜 γ 个 token。它也有自己的缓存：上一轮猜错的部分要先回滚掉，
只保留和当前文本相同的前缀，再把缺的 token 补送进去。
:::

<p class="nb-label">In [6]</p>

```python
class ModelDrafter:
    """用一个小模型起草。propose 返回 (草稿 token 列表, 每个位置的草稿分布 q；贪心时为 None)。"""
    def __init__(self, model, exit_after=None):
        self.s, self.fed = Session(model, exit_after), []     # fed：缓存里对应的 token

    def propose(self, seq, gamma, gen=None, temperature=1.0):
        keep = 0                                              # 缓存里还有效的前缀长度
        while keep < min(len(self.fed), len(seq) - 1) and self.fed[keep] == seq[keep]:
            keep += 1
        self.s.rollback(keep)
        logits = self.s.feed(seq[keep:])
        self.fed = list(seq)
        draft, qs = [], []
        for i in range(gamma):
            if gen is None:                                   # 贪心
                x, q = logits[-1].argmax().item(), None
            else:                                             # 采样（第 7 节）
                q = F.softmax(logits[-1] / temperature, dim=-1)
                x = torch.multinomial(q, 1, generator=gen).item()
            draft.append(x); qs.append(q)
            if i < gamma - 1:
                logits = self.s.feed([x]); self.fed.append(x)
        return draft, qs
```

::: v-pre
投机解码的一轮：草稿给出 γ 个 token；目标模型把“上一轮留下的最后一个 token + γ 个草稿”一次送进去，
得到 γ+1 个位置上它自己的选择；从头比较，草稿和目标模型的选择相同就接受，第一次不同就停，
换成目标模型自己的那个 token。草稿全部被接受时，最后一个位置的输出白送一个 token。
所以每轮至少前进 1 个 token，最多 γ+1 个。
:::

<p class="nb-label">In [7]</p>

```python
def speculative_greedy(model, drafter, prompt, n, gamma):
    t, seq = Session(model), list(prompt)
    stats = {"rounds": 0, "tested": 0, "accepted": 0, "with_draft": 0}
    while len(seq) - len(prompt) < n:
        draft, _ = drafter.propose(seq, gamma)
        start = len(t)                                        # 目标模型已经缓存的位置数
        logits = t.feed(seq[start:] + draft)                  # 一次前向验证全部草稿
        choice = logits[len(seq) - start - 1:].argmax(-1).tolist()   # 目标模型在每个草稿位置上的选择，多一个
        k = 0
        while k < len(draft) and draft[k] == choice[k]:
            k += 1
        seq += draft[:k] + [choice[k]]                        # 接受的草稿 + 目标模型自己的一个 token
        t.rollback(len(seq) - 1)                              # 被拒草稿的 K、V 作废；新 token 下一轮再送
        stats["rounds"] += 1
        stats["tested"] += min(k + 1, len(draft))             # 实际比较过的草稿个数
        stats["accepted"] += k
        stats["with_draft"] += len(draft) > 0
    return seq[len(prompt):][:n], stats                       # 最后一轮可能多出几个，截到 n 个
```

::: v-pre
先训一个小草稿：d=64、2 层、2 个头，按同样的 300 个 batch 训练，和目标模型共用同一个分词器
（草稿和目标必须用同一张词表，否则无法逐 token 比较）。用验证集里 12 首诗的第一句当提示词，
每个提示词生成 32 个 token，断言投机的输出与普通贪心逐 token 相同。
:::

<p class="nb-label">In [8]</p>

```python
DRAFT_CFG = dict(d=64, layers=2, heads=2)
DRAFT_SEEDS = (0, 1, 2)
plain_drafts = train_models(DRAFT_SEEDS, **DRAFT_CFG)
print(f"草稿模型：d=64、2 层，参数 {n_params(plain_drafts[0]):,} 个（目标的 {n_params(plain_drafts[0]) / n_params(target):.0%}）")

prompts = [tok.encode(p.split("，")[0] + "，").ids for p in val_poems[:12]]
N_NEW = 32
reference = [greedy(target, p, N_NEW) for p in prompts]

def run_greedy(drafter_factory, gamma):
    """对 12 个提示词各跑一次投机贪心，逐个断言输出不变，汇总计数（seconds 是这一遍的墙钟时间）。"""
    total = {"rounds": 0, "tested": 0, "accepted": 0, "with_draft": 0}
    t0 = time.perf_counter()
    for p, (ref, _) in zip(prompts, reference):
        out, st = speculative_greedy(target, drafter_factory(), p, N_NEW, gamma)
        assert out == ref, "投机解码的输出必须和普通贪心逐 token 相同"
        for key in total:
            total[key] += st[key]
    seconds = time.perf_counter() - t0
    tau = (total["accepted"] + total["rounds"]) / total["rounds"]     # 每轮前进的 token 数：接受的草稿 + 1
    return {**total, "alpha": total["accepted"] / total["tested"], "tau": tau, "seconds": seconds}

r = run_greedy(lambda: ModelDrafter(plain_drafts[0]), gamma=4)
print(f"12 个提示词 × {N_NEW} 个 token：输出与普通贪心完全相同")
print(f"普通贪心：目标模型前向 {sum(c for _, c in reference)} 次")
print(f"投机（γ=4）：目标模型前向 {r['rounds']} 次，平均每轮前进 {r['tau']:.2f} 个 token，"
      f"草稿被接受的比例 α={r['alpha']:.2f}")
```

```text
草稿模型：d=64、2 层，参数 360,512 个（目标的 27%）
```

```text
12 个提示词 × 32 个 token：输出与普通贪心完全相同
普通贪心：目标模型前向 384 次
投机（γ=4）：目标模型前向 264 次，平均每轮前进 1.59 个 token，草稿被接受的比例 α=0.38
```

::: v-pre
看一轮里到底发生了什么：第一个提示词的前 5 轮。
:::

<p class="nb-label">In [9]</p>

```python
def trace(model, drafter, prompt, gamma, rounds):
    t, seq, rows = Session(model), list(prompt), []
    for _ in range(rounds):
        draft, _ = drafter.propose(seq, gamma)
        start = len(t)
        choice = t.feed(seq[start:] + draft)[len(seq) - start - 1:].argmax(-1).tolist()
        k = 0
        while k < len(draft) and draft[k] == choice[k]:
            k += 1
        name = lambda i: "<eos>" if i == EOS else tok.decode([i])
        print(f"草稿 [{' '.join(map(name, draft))}]  目标 [{' '.join(map(name, choice))}]  "
              f"接受 {k} 个 → 新增「{''.join(map(name, draft[:k] + [choice[k]]))}」")
        rows.append({"draft": [name(i) for i in draft], "choice": [name(i) for i in choice], "k": k})
        seq += draft[:k] + [choice[k]]
        t.rollback(len(seq) - 1)
    return rows

print("提示词：", tok.decode(prompts[0]))
log["trace"] = trace(target, ModelDrafter(plain_drafts[0]), prompts[0], gamma=4, rounds=5)
```

```text
提示词： 久为簪组累，
草稿 [风 不 是 山]  目标 [不 子 在 无 声]  接受 0 个 → 新增「不」
草稿 [是 是 山 深]  目标 [将 一 无 声 。]  接受 0 个 → 新增「将」
草稿 [是 无 人 。]  目标 [一 何 人 。 <eos>]  接受 0 个 → 新增「一」
草稿 [人 深 。 <eos>]  目标 [人 相 。 <eos> 一]  接受 1 个 → 新增「人相」
草稿 [。 <eos> 一 闻]  目标 [。 <eos> 一 人 多]  接受 3 个 → 新增「。<eos>一人」
```

::: v-pre
## 4. 草稿越像目标越好：蒸馏

草稿被接受，靠的不是它“写得好”，而是它“和目标想得一样”。按语料训练的草稿学的是语料，
目标模型自己的偏好（包括它的错误）它并不知道。换一种训练目标：让草稿去拟合目标模型在同样输入上的整个输出分布
（软标签交叉熵，等价于最小化 KL(p‖q)），这就是蒸馏（第 40 章会系统地讲）。结构、步数、batch 都不变，3 个种子。
:::

<p class="nb-label">In [10]</p>

```python
distilled_drafts = train_models(DRAFT_SEEDS, **DRAFT_CFG, teacher=target)

n_val = (len(val_ids) - 1) // CTX
val_x = val_ids[: n_val * CTX].view(n_val, CTX)
val_y = val_ids[1: n_val * CTX + 1].view(n_val, CTX)

@torch.no_grad()
def agreement(drafts):
    """验证集上，每个草稿的三个数：自己的损失、与目标 argmax 相同的比例、两个分布的重叠 Σmin(p, q)。"""
    sums = torch.zeros(len(drafts), 3)
    for i in range(0, n_val, 64):
        x, y = val_x[i:i + 64], val_y[i:i + 64]
        p = F.softmax(target(x), dim=-1)
        for j, draft in enumerate(drafts):
            lq = F.log_softmax(draft(x), dim=-1)
            sums[j, 0] += F.nll_loss(lq.reshape(-1, V), y.reshape(-1), reduction="sum").item()
            sums[j, 1] += (p.argmax(-1) == lq.argmax(-1)).sum().item()
            sums[j, 2] += torch.minimum(p, lq.exp()).sum().item()
    return (sums / (n_val * CTX)).tolist()

def mean_range(xs, fmt):
    return f"{fmt.format(sum(xs) / len(xs))} [{fmt.format(min(xs))}, {fmt.format(max(xs))}]"

val_all = agreement([target, *plain_drafts.values(), *distilled_drafts.values()])
draft_rows = {}
for name, drafts, val in [("按语料训练", plain_drafts, val_all[1:4]), ("蒸馏", distilled_drafts, val_all[4:7])]:
    gen = [run_greedy(lambda m=m: ModelDrafter(m), gamma=4) for m in drafts.values()]
    draft_rows[name] = {"val": val, "gen": gen}
    print(f"{name:<6} 验证损失 {mean_range([v[0] for v in val], '{:.3f}')}  "
          f"argmax 相同 {mean_range([v[1] for v in val], '{:.1%}')}  │  "
          f"生成时 α {mean_range([g['alpha'] for g in gen], '{:.2f}')}  每轮前进 {mean_range([g['tau'] for g in gen], '{:.2f}')} 个 token")
print(f"目标模型自己的验证损失 {val_all[0][0]:.3f}")
log["draft_rows"] = draft_rows
```

```text
按语料训练  验证损失 5.844 [5.802, 5.887]  argmax 相同 37.9% [36.6%, 38.8%]  │  生成时 α 0.37 [0.35, 0.38]  每轮前进 1.58 [1.54, 1.59] 个 token
```

```text
蒸馏     验证损失 5.759 [5.746, 5.783]  argmax 相同 50.0% [48.8%, 51.0%]  │  生成时 α 0.45 [0.40, 0.49]  每轮前进 1.81 [1.66, 1.91] 个 token
目标模型自己的验证损失 5.575
```

::: v-pre
## 5. 起草多长

γ 越大，一轮可能前进得越多，但后面的草稿越容易白猜。如果每个草稿被接受的概率都是 α、彼此独立，
一轮前进的 token 数的期望是 $\tau = 1 + \alpha + \alpha^2 + \dots + \alpha^\gamma = \frac{1-\alpha^{\gamma+1}}{1-\alpha}$
（[Leviathan 等，2023](https://arxiv.org/abs/2211.17192)）。拿蒸馏草稿扫一遍 γ，3 个种子，和公式比一比。
公式里的 α 用 γ=1 时测到的接受率。
:::

<p class="nb-label">In [11]</p>

```python
GAMMAS = (1, 2, 3, 4, 6, 8)
sweep = {s: {g: draft_rows["蒸馏"]["gen"][i] if g == 4 else run_greedy(lambda m=m: ModelDrafter(m), g) for g in GAMMAS}
         for i, (s, m) in enumerate(distilled_drafts.items())}             # γ=4 在第 4 节已经跑过
for g in GAMMAS:
    taus = [sweep[s][g]["tau"] for s in DRAFT_SEEDS]
    pred = [(1 - sweep[s][1]["alpha"] ** (g + 1)) / (1 - sweep[s][1]["alpha"]) for s in DRAFT_SEEDS]
    alphas = [sweep[s][g]["alpha"] for s in DRAFT_SEEDS]
    rounds = sum(sweep[s][g]["rounds"] for s in DRAFT_SEEDS) / 3
    print(f"γ={g}：每轮前进 {mean_range(taus, '{:.2f}')} 个 token（公式 {sum(pred) / 3:.2f}），α {mean_range(alphas, '{:.2f}')}，"
          f"目标前向平均 {rounds:.0f} 次")
log["sweep"] = {s: {g: v for g, v in row.items()} for s, row in sweep.items()}
```

```text
γ=1：每轮前进 1.42 [1.38, 1.46] 个 token（公式 1.42），α 0.42 [0.38, 0.46]，目标前向平均 278 次
γ=2：每轮前进 1.56 [1.49, 1.63] 个 token（公式 1.60），α 0.42 [0.37, 0.46]，目标前向平均 260 次
γ=3：每轮前进 1.77 [1.65, 1.84] 个 token（公式 1.68），α 0.48 [0.43, 0.51]，目标前向平均 236 次
γ=4：每轮前进 1.81 [1.66, 1.91] 个 token（公式 1.72），α 0.45 [0.40, 0.49]，目标前向平均 233 次
γ=6：每轮前进 1.84 [1.69, 1.96] 个 token（公式 1.74），α 0.46 [0.41, 0.49]，目标前向平均 230 次
γ=8：每轮前进 1.84 [1.69, 1.96] 个 token（公式 1.74），α 0.45 [0.41, 0.49]，目标前向平均 230 次
```

::: v-pre
前向次数省了，时间省了没有？每轮的代价是 γ 次草稿前向加 1 次目标前向。记草稿一次前向的耗时是目标的 c 倍，
一轮验证和一次普通 decode 差不多贵（第 2 节），那么相对普通 decode 的加速比约为 $\tau / (1 + \gamma c)$。
上面每一遍投机生成都记了墙钟时间（第 3 节的第一遍已经热身过），和同一批提示词上普通贪心的时间比。时间和机器有关，单独打印。
:::

<p class="nb-label">In [12]</p>

```python
t0 = time.perf_counter()
for p in prompts:
    greedy(target, p, N_NEW)
plain_s = time.perf_counter() - t0
c_draft = time_feed(distilled_drafts[0], 1) / feed_ms[1]
wall = {g: [plain_s / sweep[s][g]["seconds"] for s in DRAFT_SEEDS] for g in GAMMAS}
print(f"[计时，本机] 草稿一次前向是目标的 c={c_draft:.2f} 倍")
print("[计时，本机] 蒸馏草稿相对普通贪心的加速比（3 个种子平均）：" + "  ".join(f"γ={g} {sum(w) / 3:.2f}×" for g, w in wall.items()))
log["wall"] = {"plain_s": plain_s, "c": c_draft, "speedup": wall}
```

```text
[计时，本机] 草稿一次前向是目标的 c=0.49 倍
[计时，本机] 蒸馏草稿相对普通贪心的加速比（3 个种子平均）：γ=1 0.86×  γ=2 0.70×  γ=3 0.62×  γ=4 0.52×  γ=6 0.40×  γ=8 0.32×
```

::: v-pre
## 6. 不用训练的草稿

草稿不一定是另一个模型。两种不用额外训练的做法：

- **只走目标模型的前几层**（自投机，self-speculative）：前 2 层的输出直接接最后的 RMSNorm 和输出层当草稿。
- **在已有文本里查**（prompt lookup）：找最近一次出现的“最后 2 个 token”，把它后面紧跟的几个 token 当草稿。
  查不到就不起草，这一轮退化成普通的一步 decode。
:::

<p class="nb-label">In [13]</p>

```python
class LookupDrafter:
    """不用模型：在已有文本里找最近一次出现的最后 n 个 token，把它后面的 γ 个 token 当草稿。"""
    def __init__(self, n=2):
        self.n = n

    def propose(self, seq, gamma, gen=None, temperature=1.0):
        key = seq[-self.n:]
        for start in range(len(seq) - self.n - 1, -1, -1):    # 从近往远找
            if seq[start:start + self.n] == key:
                draft = seq[start + self.n: start + self.n + gamma]
                return draft, [None] * len(draft)
        return [], []

compare = {
    "小模型（按语料训练）": (lambda: ModelDrafter(plain_drafts[0]), time_feed(plain_drafts[0], 1) / feed_ms[1]),
    "小模型（蒸馏）": (lambda: ModelDrafter(distilled_drafts[0]), c_draft),
    "目标的前 2 层": (lambda: ModelDrafter(target, exit_after=2), time_feed(target, 1, exit_after=2) / feed_ms[1]),
    "文本里查（n=2）": (lambda: LookupDrafter(2), 0.0),
}
compare_rows = {}
for name, (factory, c) in compare.items():
    r = run_greedy(factory, gamma=4)
    compare_rows[name] = {**r, "c": c, "speedup": plain_s / r["seconds"]}
    print(f"{name:<10} α={r['alpha']:.2f}  每轮前进 {r['tau']:.2f} 个 token  目标前向 {r['rounds']} 次（普通贪心 {len(prompts) * N_NEW} 次）")
look = compare_rows["文本里查（n=2）"]
print(f"文本里查：{look['rounds']} 轮里只有 {look['with_draft']} 轮查到了草稿")
for name, row in compare_rows.items():
    print(f"[计时，本机] {name:<10} c={row['c']:.2f}  加速比 {row['speedup']:.2f}×")
log["compare"] = compare_rows
```

```text
小模型（按语料训练） α=0.38  每轮前进 1.59 个 token  目标前向 264 次（普通贪心 384 次）
```

```text
小模型（蒸馏）    α=0.49  每轮前进 1.91 个 token  目标前向 219 次（普通贪心 384 次）
```

```text
目标的前 2 层   α=0.53  每轮前进 2.04 个 token  目标前向 202 次（普通贪心 384 次）
```

```text
文本里查（n=2）  α=0.58  每轮前进 1.16 个 token  目标前向 339 次（普通贪心 384 次）
文本里查：339 轮里只有 49 轮查到了草稿
[计时，本机] 小模型（按语料训练） c=0.48  加速比 0.46×
[计时，本机] 小模型（蒸馏）    c=0.49  加速比 0.55×
[计时，本机] 目标的前 2 层   c=0.57  加速比 0.56×
[计时，本机] 文本里查（n=2）  c=0.00  加速比 1.07×
```

::: v-pre
## 7. 采样时：拒绝采样

贪心时“相同就接受”天经地义。采样时，草稿按自己的分布 q 抽出 x，目标的分布是 p；直接接受等于从 q 采样，
输出的分布就变了。[Leviathan 等（2023）](https://arxiv.org/abs/2211.17192)和
[Chen 等（2023）](https://arxiv.org/abs/2302.01318)给出的修正：以 $\min(1, p(x)/q(x))$ 的概率接受 x；
被拒时，从 $\max(0, p-q)$ 归一化后的分布里重新抽一个。这样输出的分布恰好是 p。

先在一个位置上用 20 万个样本检查：提示词“春眠不觉晓，”之后，目标与蒸馏草稿（种子 0）的下一个 token 分布。
对照三种写法：正确的拒绝采样、草稿全部接受、被拒时直接从 p 重抽。
:::

<p class="nb-label">In [14]</p>

```python
@torch.no_grad()
def next_dist(model, ids):
    return F.softmax(model(torch.tensor([ids]))[0, -1], dim=-1)

ctx = tok.encode("春眠不觉晓，").ids
p, q = next_dist(target, ctx), next_dist(distilled_drafts[0], ctx)
N = 200_000
g = torch.Generator().manual_seed(0)
x = torch.multinomial(q, N, replacement=True, generator=g)    # 草稿抽 N 次
accept = torch.rand(N, generator=g) * q[x] < p[x]             # 以 min(1, p/q) 的概率接受
residual = (p - q).clamp(min=0)
residual /= residual.sum()

variants = {
    "直接从 p 抽（基准）": torch.multinomial(p, N, replacement=True, generator=g),
    "拒绝采样（正确）": torch.where(accept, x, torch.multinomial(residual, N, replacement=True, generator=g)),
    "草稿全部接受": x,
    "被拒时从 p 重抽": torch.where(accept, x, torch.multinomial(p, N, replacement=True, generator=g)),
}
tv = {}
for name, s in variants.items():
    freq = torch.bincount(s, minlength=V).float() / N
    tv[name] = 0.5 * (freq - p).abs().sum().item()
    print(f"{name:<10} 与 p 的总变差距离 {tv[name]:.4f}")
print(f"接受率：实测 {accept.float().mean():.4f}，理论 Σmin(p, q) = {torch.minimum(p, q).sum():.4f}")
top = p.topk(8).indices
log["rejection"] = {"tv": tv, "tokens": [tok.decode([i]) for i in top.tolist()],
                    "p": p[top].tolist(), "q": q[top].tolist(), "overlap": torch.minimum(p, q).sum().item()}
```

```text
直接从 p 抽（基准） 与 p 的总变差距离 0.0447
拒绝采样（正确）   与 p 的总变差距离 0.0440
草稿全部接受     与 p 的总变差距离 0.1222
被拒时从 p 重抽  与 p 的总变差距离 0.0753
接受率：实测 0.8860，理论 Σmin(p, q) = 0.8860
```

::: v-pre
“总变差距离”是两个分布差的绝对值之和的一半，0 表示完全相同。20 万个样本本身就有抽样误差，
第一行“直接从 p 抽”给出了这个误差的大小；正确的拒绝采样和它在同一水平，另外两种写法明显偏离。

一个位置对了，整段也就对了：每一轮的第一个草稿位置就是上面的情形；它被接受后，下一个位置以接受的 token 为条件，
又是同样的情形。把它写进完整的生成循环：
:::

<p class="nb-label">In [15]</p>

```python
def speculative_sample(model, drafter, prompt, n, gamma, gen, temperature=1.0):
    t, seq = Session(model), list(prompt)
    stats = {"rounds": 0, "tested": 0, "accepted": 0, "overlap": 0.0}
    while len(seq) - len(prompt) < n:
        draft, qs = drafter.propose(seq, gamma, gen, temperature)
        start = len(t)
        logits = t.feed(seq[start:] + draft)
        ps = F.softmax(logits[len(seq) - start - 1:] / temperature, dim=-1)   # [len(draft)+1, V]
        k, new = 0, None
        for i, x in enumerate(draft):
            q = qs[i] if qs[i] is not None else F.one_hot(torch.tensor(x), ps.shape[-1]).float()   # 不是模型给的草稿：q 是确定的
            stats["tested"] += 1
            stats["overlap"] += torch.minimum(ps[i], q).sum().item()
            if torch.rand(1, generator=gen).item() * q[x] < ps[i, x]:          # 以 min(1, p/q) 的概率接受
                k += 1
                continue
            residual = (ps[i] - q).clamp(min=0)                               # 被拒：从 max(0, p−q) 里重抽
            new = torch.multinomial(residual / residual.sum(), 1, generator=gen).item()
            break
        if new is None:                                                        # 全部接受：从最后一个位置多抽一个
            new = torch.multinomial(ps[len(draft)], 1, generator=gen).item()
        seq += draft[:k] + [new]
        t.rollback(len(seq) - 1)
        stats["rounds"] += 1
        stats["accepted"] += k
    return seq[len(prompt):][:n], stats
```

::: v-pre
整段生成的分布怎么验证？目标模型的词表有 4096 个 token，连续 3 个 token 的组合有 680 亿种，样本不够。
换一对玩具“模型”：词表只有 4 个 token，下一个 token 只看前一个（两张 4×4 的转移表，草稿的表是目标的表加噪声）。
它们和 Tiny 用同一套接口，直接交给上面的 `speculative_sample` 生成 3 个 token，和精确的联合分布（64 种组合）比较。
另外用一个只给 argmax、不给分布的草稿再跑一遍，检查“q 是确定的”那个分支（文本里查就走这个分支）。
:::

<p class="nb-label">In [16]</p>

```python
class Markov(nn.Module):
    """玩具模型：下一个 token 的 logits 只看前一个 token。缓存里只记录送进来的 token，用来支持回滚。"""
    def __init__(self, table):
        super().__init__()
        self.table, self.blocks = table, [None]

    def forward(self, idx, cache=None, exit_after=None):
        if cache is not None:
            new = idx.float().view(1, 1, -1, 1)
            cache.k[0] = new if cache.k[0] is None else torch.cat([cache.k[0], new], dim=2)
            cache.v[0] = cache.k[0]
        return self.table[idx]

g = torch.Generator().manual_seed(1)
p_table = torch.randn(4, 4, generator=g) * 1.5
q_table = p_table + torch.randn(4, 4, generator=g)
toy_p, toy_q = Markov(p_table), Markov(q_table)

P, Q = F.softmax(p_table, -1), F.softmax(q_table, -1)
exact = torch.einsum("a,ab,bc->abc", P[0], P, P).flatten()    # 从 token 0 出发，连续 3 个 token 的精确分布
M = 6000
class GreedyDrafter(ModelDrafter):
    """草稿总是取 argmax、不给分布（q 是确定的），用来检查 speculative_sample 里 one-hot 的那个分支。"""
    def propose(self, seq, gamma, gen=None, temperature=1.0):
        return super().propose(seq, gamma)

def toy_counts(make_drafter):
    counts = torch.zeros(64)
    for _ in range(M):
        out, _ = speculative_sample(toy_p, make_drafter(), [0], 3, gamma=2, gen=g)
        counts[out[0] * 16 + out[1] * 4 + out[2]] += 1
    return counts

counts = toy_counts(lambda: ModelDrafter(toy_q))
counts_greedy = toy_counts(lambda: GreedyDrafter(toy_q))
baseline = torch.bincount(torch.multinomial(exact, M, replacement=True, generator=g), minlength=64).float()
toy_tv = {"投机采样": 0.5 * (counts / M - exact).abs().sum().item(),
          "投机采样（确定性草稿）": 0.5 * (counts_greedy / M - exact).abs().sum().item(),
          "直接从 p 抽（基准）": 0.5 * (baseline / M - exact).abs().sum().item(),
          "草稿自己的分布": 0.5 * (torch.einsum("a,ab,bc->abc", Q[0], Q, Q).flatten() - exact).abs().sum().item()}
for name, d in toy_tv.items():
    print(f"{name:<10} 与目标的精确分布（64 种组合）的总变差距离 {d:.4f}")
log["toy_tv"] = toy_tv
```

```text
投机采样       与目标的精确分布（64 种组合）的总变差距离 0.0327
投机采样（确定性草稿） 与目标的精确分布（64 种组合）的总变差距离 0.0367
直接从 p 抽（基准） 与目标的精确分布（64 种组合）的总变差距离 0.0323
草稿自己的分布    与目标的精确分布（64 种组合）的总变差距离 0.4609
```

::: v-pre
再回到真实的目标模型和蒸馏草稿，温度 1、γ=2 和 4，每个提示词采样一次，3 个种子。
每个被检查的草稿位置，接受的概率应该正好是该位置上的 Σmin(p, q)；把实测接受率和这些重叠的平均放在一起看。
:::

<p class="nb-label">In [17]</p>

```python
def sample(model, prompt, n, gen, temperature=1.0):
    """普通采样：每次前向出一个 token。"""
    s, seq = Session(model), list(prompt)
    logits = s.feed(seq)
    while True:
        seq.append(torch.multinomial(F.softmax(logits[-1] / temperature, dim=-1), 1, generator=gen).item())
        if len(seq) - len(prompt) == n:
            return seq[len(prompt):]
        logits = s.feed(seq[-1:])

g = torch.Generator().manual_seed(99)
t0 = time.perf_counter()
for p_ids in prompts:
    sample(target, p_ids, N_NEW, g)
plain_sample_s = time.perf_counter() - t0

sample_rows = {}
for gamma in (2, 4):
    for s, m in distilled_drafts.items():
        g = torch.Generator().manual_seed(100 + s)
        total = {"rounds": 0, "tested": 0, "accepted": 0, "overlap": 0.0}
        t0 = time.perf_counter()
        for p_ids in prompts:
            _, st = speculative_sample(target, ModelDrafter(m), p_ids, N_NEW, gamma, g)
            for key in total:
                total[key] += st[key]
        total["seconds"] = time.perf_counter() - t0
        sample_rows[f"{gamma}-{s}"] = total
    rows = [sample_rows[f"{gamma}-{s}"] for s in DRAFT_SEEDS]
    print(f"γ={gamma}：实测接受率 {mean_range([r['accepted'] / r['tested'] for r in rows], '{:.3f}')}，"
          f"被检查位置上 Σmin(p, q) 的平均 {mean_range([r['overlap'] / r['tested'] for r in rows], '{:.3f}')}，"
          f"每轮前进 {mean_range([(r['accepted'] + r['rounds']) / r['rounds'] for r in rows], '{:.2f}')} 个 token")
for gamma in (2, 4):
    sp = [plain_sample_s / sample_rows[f"{gamma}-{s}"]["seconds"] for s in DRAFT_SEEDS]
    print(f"[计时，本机] 采样 γ={gamma}：相对普通采样的加速比 {sum(sp) / 3:.2f}×（3 个种子平均）")
log["sample_rows"] = sample_rows
log["plain_sample_s"] = plain_sample_s
```

```text
γ=2：实测接受率 0.777 [0.756, 0.814]，被检查位置上 Σmin(p, q) 的平均 0.771 [0.765, 0.782]，每轮前进 2.39 [2.32, 2.49] 个 token
```

```text
γ=4：实测接受率 0.765 [0.755, 0.778]，被检查位置上 Σmin(p, q) 的平均 0.775 [0.768, 0.789]，每轮前进 3.16 [3.13, 3.18] 个 token
[计时，本机] 采样 γ=2：相对普通采样的加速比 1.06×（3 个种子平均）
[计时，本机] 采样 γ=4：相对普通采样的加速比 0.91×（3 个种子平均）
```

::: v-pre
## 8. 收益的账

把第 5 节的公式算一遍：给定接受率 α 和草稿成本 c，最好的 γ 是多少、最多能快多少。
这里假设一轮验证和一次普通 decode 一样贵，没有算草稿与目标之间切换的开销，是上限。
:::

<p class="nb-label">In [18]</p>

```python
def speedup(alpha, gamma, c):
    return (1 - alpha ** (gamma + 1)) / (1 - alpha) / (1 + gamma * c)

budget = {}
for c in (0.02, 0.1, 0.5):
    cells = []
    for alpha in (0.5, 0.7, 0.9):
        best = max(range(1, 21), key=lambda g: speedup(alpha, g, c))   # γ 在 1～20 里取最好的
        budget[f"{c}-{alpha}"] = (best, speedup(alpha, best, c))
        cells.append(f"α={alpha}: γ={best:>2} {speedup(alpha, best, c):.2f}×")
    print(f"c={c:<4}  " + "   ".join(cells))
log["budget"] = budget
```

```text
c=0.02  α=0.5: γ= 4 1.79×   α=0.7: γ= 8 2.76×   α=0.9: γ=19 6.37×
c=0.1   α=0.5: γ= 2 1.46×   α=0.7: γ= 4 1.98×   α=0.9: γ=10 3.43×
c=0.5   α=0.5: γ= 1 1.00×   α=0.7: γ= 1 1.13×   α=0.9: γ= 3 1.38×
```

<p class="nb-label">In [19]</p>

```python
with open("speculative_decoding_log.json", "w", encoding="utf-8") as f:
    json.dump(log, f, ensure_ascii=False)
print("已写出 speculative_decoding_log.json")
```

```text
已写出 speculative_decoding_log.json
```

