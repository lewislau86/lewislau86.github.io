---
title: "第 37 章：继续预训练与灾难性遗忘（notebook 在线查看）"
search: false
editLink: false
prev: false
next: false
pageClass: tinyllm-course
---

<!-- 本页由 scripts/build-tinyllm-code.py 根据 notebook 自动生成，请勿手改。 -->

::: tip 这是 notebook 的只读预览
[返回教案](/tinyllm/continued-pretraining) · [在 Colab 中运行](https://colab.research.google.com/github/lewislau86/lewislau86.github.io/blob/master/docs/public/tinyllm/notebooks/continued-pretraining.ipynb) · <a href="/tinyllm/notebooks/continued-pretraining.ipynb" download>下载 .ipynb</a> · <a href="/tinyllm/code/continued-pretraining.py" download>下载 .py</a> · [在 GitHub 上查看](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/tinyllm/notebooks/continued-pretraining.ipynb)

下面的代码和输出与 notebook 文件完全一致。想修改、运行，请用 Colab 打开或下载到本地。
:::

::: v-pre
# 第 37 章：继续预训练与灾难性遗忘

配套教案：https://lewislau86.github.io/tinyllm/continued-pretraining

从上到下运行即可（`python continued-pretraining.py`），CPU 约两分钟。需要安装 PyTorch 和 `tokenizers`。
这个文件是本章代码的唯一来源：教案中的代码片段由 `# region 名字` / `# endregion 名字`
标记的区域直接引用，notebook 也由它生成（scripts/build-tinyllm-code.py）。

本章用第 17 章的代理模型：先只在五言上训练一个基线，再在七言上接着训，比较回放多少五言、学习率多大，
同时看新领域（七言）学会了多少、旧领域（五言）忘了多少；最后和“从头在两份数据上一起训”比较。
结论性的对比都用 3 个种子（只决定初始参数），报告平均。
:::

<p class="nb-label">In [1]</p>

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
## 0. 第 17 章的代理模型

模型代码从第 12 章原样复制，尺寸用第 17 章的代理模型：词表 1024、宽度 64、2 层，batch 16、上下文 64。
这一章要训 3 个基线和几十段继续预训练，原尺寸太慢；损失的绝对值只在本章内部比较。
:::

<p class="nb-label">In [2]</p>

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

cfg = TinyConfig(vocab_size=1024, d_model=64, n_layers=2)       # 第 17 章的代理模型
BATCH = 16
print(cfg)
```

```text
TinyConfig(vocab_size=1024, d_model=64, n_layers=2, n_heads=4, context=64, rope_base=10000.0)
```

<p class="nb-label">In [3]</p>

```python
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
```

<p class="nb-label">In [4]</p>

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

QIYAN_URL = "https://lewislau86.github.io/tinyllm/data/tang-qiyan.jsonl"
QIYAN_SHA256 = "0a23e00937f16763adc2d5de9774c66da98aa18391ce08ebc714447455e6dad0"

def load_qiyan():
    """第 37 章的“新领域”：528 首七言绝句和律诗（来源见“实验环境”页）。和 load_poems 一样先找本地，没有就下载。"""
    near = Path(os.environ.get("TINYLLM_DATA", "tang-poems.jsonl")).with_name("tang-qiyan.jsonl")
    candidates = [near, Path("tang-qiyan.jsonl"), Path("../data/tang-qiyan.jsonl")]
    path = next((p for p in candidates if p.exists()), None)
    if path is None:
        path = Path("tang-qiyan.jsonl")
        with urlopen(QIYAN_URL, timeout=120) as r:
            path.write_bytes(r.read())
    raw = path.read_bytes().replace(b"\r\n", b"\n")
    if hashlib.sha256(raw).hexdigest() != QIYAN_SHA256:
        raise RuntimeError(f"{path} 不是本课使用的七言语料版本，删掉它再运行一次即可重新下载")
    return [json.loads(line) for line in raw.decode("utf-8").splitlines()]
```

::: v-pre
## 1. 两份数据：旧的五言，新的七言
:::

<p class="nb-label">In [5]</p>

```python
poems = load_poems(6000)
wu_train = [p["text"] for p in poems if p["split"] == "train"]
wu_val = [p["text"] for p in poems if p["split"] == "val"]
qiyan = load_qiyan()
qi_train = [p["text"] for p in qiyan if p["split"] == "train"]
qi_val = [p["text"] for p in qiyan if p["split"] == "val"]
tokenizer = train_tokenizer(wu_train, cfg.vocab_size)          # 基线的分词器：只见过五言
EOS = tokenizer.token_to_id("<eos>")

def to_stream(texts):
    ids = []
    for t in texts:
        ids += tokenizer.encode(t).ids + [EOS]
    return torch.tensor(ids)

W, W_val, Q, Q_val = map(to_stream, (wu_train, wu_val, qi_train, qi_val))
wu_chars = set("".join(wu_train))
new_chars = {c for c in "".join(qi_train) if c not in wu_chars}
print(f"五言：训练 {len(wu_train)} 首 {len(W):,} 个 token，验证 {len(wu_val)} 首 {len(W_val):,} 个 token")
print(f"七言：训练 {len(qi_train)} 首 {len(Q):,} 个 token，验证 {len(qi_val)} 首 {len(Q_val):,} 个 token")
print(f"七言训练集只有五言训练集的 {len(Q) / len(W):.1%}；七言里有 {len(new_chars)} 个字五言训练集里没出现过，"
      f"每个字平均 {len(Q) / sum(len(t) + 1 for t in qi_train):.2f} 个 token（五言 {len(W) / sum(len(t) + 1 for t in wu_train):.2f}）")

@torch.no_grad()
def evaluate(model, ids, T=cfg.context, batch=64):
    model.eval()
    n = (len(ids) - 1) // T * T
    xs, ys = ids[:n].view(-1, T), ids[1:n + 1].view(-1, T)
    total = sum(F.cross_entropy(model(xs[i:i + batch]).flatten(0, 1), ys[i:i + batch].flatten(), reduction="sum").item()
                for i in range(0, len(xs), batch))
    model.train()
    return total / ys.numel()

FORMAT = torch.tensor(sorted(set(tokenizer.encode("，。").ids + [EOS])))   # 标点和 <eos>：管“句子多长、诗多长”

@torch.no_grad()
def format_share(model, ids=W_val, T=cfg.context, batch=64):
    """五言验证集的平均损失拆成两部分：预测标点和 <eos> 的、预测字的（两者相加等于总的平均损失）。"""
    model.eval()
    n = (len(ids) - 1) // T * T
    xs, ys = ids[:n].view(-1, T), ids[1:n + 1].view(-1, T)
    lp = torch.cat([F.cross_entropy(model(xs[i:i + batch]).transpose(1, 2), ys[i:i + batch], reduction="none")
                    for i in range(0, len(xs), batch)])
    is_format = torch.isin(ys, FORMAT)
    model.train()
    return lp[is_format].sum().item() / lp.numel(), lp[~is_format].sum().item() / lp.numel()

def report(model):
    fmt, content = format_share(model)
    return {"wu": evaluate(model, W_val), "qi": evaluate(model, Q_val), "qi_train": evaluate(model, Q), "wu_format": fmt, "wu_content": content}
```

```text
五言：训练 5419 首 296,250 个 token，验证 291 首 15,892 个 token
七言：训练 478 首 25,168 个 token，验证 50 首 2,617 个 token
七言训练集只有五言训练集的 8.5%；七言里有 123 个字五言训练集里没出现过，每个字平均 1.30 个 token（五言 1.24）
```

::: v-pre
## 2. 基线：只在五言上训练
:::

<p class="nb-label">In [6]</p>

```python
def make_optimizer(model, lr):
    decay = [p for p in model.parameters() if p.dim() >= 2]
    no_decay = [p for p in model.parameters() if p.dim() < 2]
    return torch.optim.AdamW([{"params": decay, "weight_decay": 0.1}, {"params": no_decay, "weight_decay": 0.0}], lr=lr)

def rows(stream, starts):
    return stream[starts[:, None] + torch.arange(cfg.context + 1)]

def train_step(model, optimizer, x, lr):
    for group in optimizer.param_groups:
        group["lr"] = lr
    _, loss = model(x[:, :-1].contiguous(), x[:, 1:].contiguous())
    optimizer.zero_grad(set_to_none=True)
    loss.backward()
    torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
    optimizer.step()

def wsd(step, total, peak, warmup=30, decay_frac=0.2):
    decay_start = int(total * (1 - decay_frac))
    if step < warmup:
        return peak * (step + 1) / warmup
    return peak if step < decay_start else peak * (total - step) / (total - decay_start)

def mixed_batch(plan, p_new, new=Q, old=W):
    """每一行以概率 p_new 取自新数据（七言），否则取自旧数据（五言）。"""
    use_new = torch.rand(BATCH, generator=plan) < p_new
    o = torch.randint(0, len(old) - cfg.context - 1, (BATCH,), generator=plan)
    n = torch.randint(0, len(new) - cfg.context - 1, (BATCH,), generator=plan)
    return torch.where(use_new[:, None], rows(new, n), rows(old, o))

def train_from_scratch(seed, steps=800, p_new=0.0):
    torch.manual_seed(seed)
    model = TinyLLM(cfg)
    optimizer = make_optimizer(model, 1e-2)
    plan = torch.Generator().manual_seed(1234)
    for step in range(steps):
        train_step(model, optimizer, mixed_batch(plan, p_new), wsd(step, steps, 1e-2))
    return model, optimizer

SEEDS = (0, 1, 2)
t0 = time.perf_counter()
bases = {}
for seed in SEEDS:
    model, optimizer = train_from_scratch(seed)
    bases[seed] = (copy.deepcopy(model.state_dict()), copy.deepcopy(optimizer.state_dict()))
print(f"[计时，本机] 3 个基线各 800 步，共 {time.perf_counter() - t0:.1f} 秒")

def mean(rows_, key):
    return sum(r[key] for r in rows_) / len(rows_)

def load(seed):
    model = TinyLLM(cfg)
    model.load_state_dict(bases[seed][0])
    return model

base_rows = [report(load(s)) for s in SEEDS]
print(f"基线：五言验证 {mean(base_rows, 'wu'):.3f}  七言验证 {mean(base_rows, 'qi'):.3f}")
```

```text
[计时，本机] 3 个基线各 800 步，共 35.8 秒
```

```text
基线：五言验证 4.417  七言验证 5.951
```

::: v-pre
## 3. 只喂七言：学会了什么，忘了什么
:::

<p class="nb-label">In [7]</p>

```python
def continue_pretrain(seed, steps=100, p_replay=0.0, peak=3e-3, warmup=10, curve=False, new=Q):
    """从基线出发，在七言上接着训；每一行以概率 p_replay 回放五言。学习率先 warmup 到 peak，再线性降到 0。"""
    model = load(seed)
    optimizer = make_optimizer(model, peak)
    optimizer.load_state_dict(copy.deepcopy(bases[seed][1]))
    plan = torch.Generator().manual_seed(4321)
    trace = []
    for step in range(steps):
        if curve and step % 10 == 0:
            trace.append((step, report(model)))
        lr = peak * (step + 1) / warmup if step < warmup else peak * (steps - step) / (steps - warmup)
        train_step(model, optimizer, mixed_batch(plan, 1 - p_replay, new=new), lr)
    if curve:
        trace.append((steps, report(model)))
    return model, trace

t0 = time.perf_counter()
curves = {r: [continue_pretrain(s, p_replay=r, curve=True)[1] for s in SEEDS] for r in (0.0, 0.1)}
print(f"[计时，本机] {time.perf_counter() - t0:.1f} 秒")
for r in (0.0, 0.1):
    for k in range(len(curves[r][0])):
        step = curves[r][0][k][0]
        rs = [c[k][1] for c in curves[r]]
        print(f"回放 {r:.0%} 第 {step:3} 步：五言验证 {mean(rs, 'wu'):.3f}  七言验证 {mean(rs, 'qi'):.3f}  七言训练 {mean(rs, 'qi_train'):.3f}")
log = {"base": base_rows, "curves": {str(r): [[(s, x) for s, x in c] for c in curves[r]] for r in curves}}
```

```text
[计时，本机] 16.5 秒
回放 0% 第   0 步：五言验证 4.417  七言验证 5.951  七言训练 6.010
回放 0% 第  10 步：五言验证 5.292  七言验证 4.894  七言训练 4.900
回放 0% 第  20 步：五言验证 5.297  七言验证 4.749  七言训练 4.719
回放 0% 第  30 步：五言验证 5.287  七言验证 4.691  七言训练 4.609
回放 0% 第  40 步：五言验证 5.408  七言验证 4.656  七言训练 4.527
回放 0% 第  50 步：五言验证 5.484  七言验证 4.635  七言训练 4.472
回放 0% 第  60 步：五言验证 5.516  七言验证 4.628  七言训练 4.432
回放 0% 第  70 步：五言验证 5.544  七言验证 4.615  七言训练 4.400
回放 0% 第  80 步：五言验证 5.580  七言验证 4.605  七言训练 4.379
回放 0% 第  90 步：五言验证 5.594  七言验证 4.601  七言训练 4.365
回放 0% 第 100 步：五言验证 5.596  七言验证 4.599  七言训练 4.359
回放 10% 第   0 步：五言验证 4.417  七言验证 5.951  七言训练 6.010
回放 10% 第  10 步：五言验证 5.155  七言验证 4.883  七言训练 4.891
回放 10% 第  20 步：五言验证 4.915  七言验证 4.768  七言训练 4.750
回放 10% 第  30 步：五言验证 4.867  七言验证 4.727  七言训练 4.664
回放 10% 第  40 步：五言验证 5.015  七言验证 4.686  七言训练 4.572
回放 10% 第  50 步：五言验证 4.913  七言验证 4.673  七言训练 4.530
回放 10% 第  60 步：五言验证 4.882  七言验证 4.667  七言训练 4.498
回放 10% 第  70 步：五言验证 4.852  七言验证 4.661  七言训练 4.472
回放 10% 第  80 步：五言验证 4.931  七言验证 4.638  七言训练 4.442
回放 10% 第  90 步：五言验证 4.915  七言验证 4.637  七言训练 4.431
回放 10% 第 100 步：五言验证 4.917  七言验证 4.634  七言训练 4.426
```

::: v-pre
## 4. 回放多少旧数据
:::

<p class="nb-label">In [8]</p>

```python
REPLAYS = (0.0, 0.05, 0.1, 0.3, 0.5)
replay = {r: [report(continue_pretrain(s, p_replay=r)[0]) for s in SEEDS] for r in REPLAYS}
for r in REPLAYS:
    rs = replay[r]
    print(f"回放 {r:>4.0%}：五言验证 {mean(rs, 'wu'):.3f}（比基线 {mean(rs, 'wu') - mean(base_rows, 'wu'):+.3f}）  "
          f"七言验证 {mean(rs, 'qi'):.3f}（比基线 {mean(rs, 'qi') - mean(base_rows, 'qi'):+.3f}）  七言训练 {mean(rs, 'qi_train'):.3f}")

for r in (0.0, 0.1, 0.5):
    rs = replay[r]
    df, dc = mean(rs, "wu_format") - mean(base_rows, "wu_format"), mean(rs, "wu_content") - mean(base_rows, "wu_content")
    print(f"回放 {r:>4.0%}：五言验证升了 {df + dc:.3f}，其中标点和 <eos> {df:+.3f}（{df / (df + dc):.0%}），字 {dc:+.3f}")
log["replay"] = {str(r): v for r, v in replay.items()}
```

```text
回放   0%：五言验证 5.596（比基线 +1.179）  七言验证 4.599（比基线 -1.352）  七言训练 4.359
回放   5%：五言验证 5.111（比基线 +0.694）  七言验证 4.619（比基线 -1.333）  七言训练 4.396
回放  10%：五言验证 4.917（比基线 +0.500）  七言验证 4.634（比基线 -1.317）  七言训练 4.426
回放  30%：五言验证 4.621（比基线 +0.204）  七言验证 4.687（比基线 -1.264）  七言训练 4.524
回放  50%：五言验证 4.519（比基线 +0.102）  七言验证 4.746（比基线 -1.205）  七言训练 4.631
回放   0%：五言验证升了 1.179，其中标点和 <eos> +0.959（81%），字 +0.220
回放  10%：五言验证升了 0.500，其中标点和 <eos> +0.332（66%），字 +0.168
回放  50%：五言验证升了 0.102，其中标点和 <eos> +0.064（63%），字 +0.037
```

::: v-pre
## 5. 学习率：重新升多高
:::

<p class="nb-label">In [9]</p>

```python
PEAKS = (1e-3, 3e-3, 1e-2)
rewarm = {p: [report(continue_pretrain(s, p_replay=0.1, peak=p)[0]) for s in SEEDS] for p in PEAKS}
for p in PEAKS:
    rs = rewarm[p]
    print(f"回放 10%，峰值 {p:.0e}：五言验证 {mean(rs, 'wu'):.3f}  七言验证 {mean(rs, 'qi'):.3f}  七言训练 {mean(rs, 'qi_train'):.3f}")
log["rewarm"] = {str(p): v for p, v in rewarm.items()}
```

```text
回放 10%，峰值 1e-03：五言验证 4.906  七言验证 4.666  七言训练 4.592
回放 10%，峰值 3e-03：五言验证 4.917  七言验证 4.634  七言训练 4.426
回放 10%，峰值 1e-02：五言验证 5.029  七言验证 4.699  七言训练 4.208
```

::: v-pre
遗忘有多少是“学习率重新升起来”造成的，有多少是“数据换了”造成的？做一个对照：数据不换，接着训五言，学习率照样升到 3e-3 再降下来。
:::

<p class="nb-label">In [10]</p>

```python
same = [continue_pretrain(s, new=W, curve=True)[1] for s in SEEDS]
for k in (1, 3, 10):
    rs = [c[k][1] for c in same]
    print(f"只升温、不换数据（接着训五言）第 {same[0][k][0]:3} 步：五言验证 {mean(rs, 'wu'):.3f}（比基线 {mean(rs, 'wu') - mean(base_rows, 'wu'):+.3f}）")
log["rewarm_only"] = [[(s, x) for s, x in c] for c in same]
```

```text
只升温、不换数据（接着训五言）第  10 步：五言验证 4.417（比基线 -0.000）
只升温、不换数据（接着训五言）第  30 步：五言验证 4.412（比基线 -0.006）
只升温、不换数据（接着训五言）第 100 步：五言验证 4.393（比基线 -0.024）
```

::: v-pre
## 6. 和从头一起训比
:::

<p class="nb-label">In [11]</p>

```python
t0 = time.perf_counter()
joint = [report(train_from_scratch(s, steps=900, p_new=0.1)[0]) for s in SEEDS]
print(f"[计时，本机] 3 个种子从头训 900 步，共 {time.perf_counter() - t0:.1f} 秒")
print(f"从头一起训（900 步，七言占 10%）：五言验证 {mean(joint, 'wu'):.3f}  七言验证 {mean(joint, 'qi'):.3f}  七言训练 {mean(joint, 'qi_train'):.3f}")
log["joint"] = joint
```

```text
[计时，本机] 3 个种子从头训 900 步，共 25.8 秒
从头一起训（900 步，七言占 10%）：五言验证 4.428  七言验证 4.920  七言训练 4.764
```

::: v-pre
## 7. 写几首看看
:::

<p class="nb-label">In [12]</p>

```python
@torch.no_grad()
def sample(model, n=24, max_new=60, temperature=0.8):
    model.eval()
    g = torch.Generator().manual_seed(7)
    out = []
    for _ in range(n):
        idx = torch.tensor([[EOS]])
        for _ in range(max_new):
            probs = F.softmax(model(idx[:, -cfg.context:])[:, -1] / temperature, dim=-1)
            nxt = torch.multinomial(probs, 1, generator=g)
            if nxt.item() == EOS:
                break
            idx = torch.cat([idx, nxt], dim=1)
        out.append(tokenizer.decode(idx[0, 1:].tolist()))
    model.train()
    return out

def line_lengths(texts):
    import re
    lens = [len(s) for t in texts for s in re.split("[，。]", t) if s]
    return sum(l == 5 for l in lens) / len(lens), sum(l == 7 for l in lens) / len(lens)

for name, model in [("基线", load(0)), ("回放 0%", continue_pretrain(0, p_replay=0.0)[0]), ("回放 10%", continue_pretrain(0, p_replay=0.1)[0])]:
    texts = sample(model)
    five, seven = line_lengths(texts)
    print(f"{name}：24 首里五字句占 {five:.0%}，七字句占 {seven:.0%}；例：{texts[0]}")
```

```text
基线：24 首里五字句占 95%，七字句占 0%；例：晓村连水涒，药退入米心。何足擁少思，花马下山中。雪满松雪入，春来窜物休。幽畑中事好，一月鸟惊看。
```

```text
回放 0%：24 首里五字句占 1%，七字句占 57%；例：晓烟连水涒露下，时峰中涛小竹阴。损金花开花马下，猎雪初曾早入寒。
```

```text
回放 10%：24 首里五字句占 14%，七字句占 39%；例：晓烟连邑月落。退峰中涯小竹，玉换金广花马台。
```

<p class="nb-label">In [13]</p>

```python
with open("continued_pretraining_log.json", "w", encoding="utf-8") as f:
    json.dump(log, f, ensure_ascii=False)
print("已写出 continued_pretraining_log.json")
```

```text
已写出 continued_pretraining_log.json
```

