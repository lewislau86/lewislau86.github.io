---
title: "第 23 章：超参数与自动化调参（notebook 在线查看）"
search: false
editLink: false
prev: false
next: false
pageClass: tinyllm-course
---

<!-- 本页由 scripts/build-tinyllm-code.py 根据 notebook 自动生成，请勿手改。 -->

::: tip 这是 notebook 的只读预览
[返回教案](/tinyllm/hyperparameter-tuning) · [在 Colab 中运行](https://colab.research.google.com/github/lewislau86/lewislau86.github.io/blob/master/docs/public/tinyllm/notebooks/hyperparameter-tuning.ipynb) · <a href="/tinyllm/notebooks/hyperparameter-tuning.ipynb" download>下载 .ipynb</a> · <a href="/tinyllm/code/hyperparameter-tuning.py" download>下载 .py</a> · [在 GitHub 上查看](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/tinyllm/notebooks/hyperparameter-tuning.ipynb)

下面的代码和输出与 notebook 文件完全一致。想修改、运行，请用 Colab 打开或下载到本地。
:::

::: v-pre
# 第 23 章：超参数与自动化调参

配套教案：https://lewislau86.github.io/tinyllm/hyperparameter-tuning

从上到下运行即可（`python hyperparameter-tuning.py`），CPU 上约两分钟（一共训练约 50 个小模型）。需要安装 PyTorch 和 `tokenizers`。
这个文件是本章代码的唯一来源：教案中的代码片段由 `# region 名字` / `# endregion 名字`
标记的区域直接引用，notebook 也由它生成（scripts/build-tinyllm-code.py）。

第 16～18 章零散地调过学习率、调度和正则化。本章把它们放在一起：先量噪声底线，再排敏感度，
然后在同样的训练预算下比较网格搜索、随机搜索和逐轮淘汰，最后看调参里最常见的两个陷阱。
:::

<p class="nb-label">In [1]</p>

```python
import copy
import json
import math
import random
import time
from dataclasses import dataclass

import torch
from torch import nn
from torch.nn import functional as F
from tokenizers import Tokenizer, decoders, models, pre_tokenizers, trainers

print("PyTorch", torch.__version__)

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
## 0. 实验对象

模型代码、数据划分、评估口径都和第 17 章的代理模型相同（词表 1024、宽度 64、2 层），主线配置是第 17 章的 WSD（峰值 1e-2）。
本章要训练约 50 次，每次约 2～3 秒。
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
STEPS, BATCH = 240, 16                                          # 主线：240 步 × 16 段
print(cfg)
```

```text
TinyConfig(vocab_size=1024, d_model=64, n_layers=2, n_heads=4, context=64, rope_base=10000.0)
```

<p class="nb-label">In [3]</p>

```python
poems = load_poems(6000)
train_poems = [p["text"] for p in poems if p["split"] == "train"]
val_poems = [p["text"] for p in poems if p["split"] == "val"]
test_poems = [p["text"] for p in poems if p["split"] == "test"]     # 只在最后复核赢家时用

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
```

<p class="nb-label">In [5]</p>

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

print("训练流", len(train_ids), "个 token；验证流", len(val_ids), "个 token；参数", sum(p.numel() for p in TinyLLM(cfg).parameters()))
```

```text
训练流 296250 个 token；验证流 15892 个 token；参数 163904
```

::: v-pre
## 1. 一次训练：配置是一个字典

六个超参数：峰值学习率、weight decay、warmup 占总步数的比例、Adam 的 β2、衰减段占总步数的比例、batch 大小。
token 预算固定为 240 × 16 段：batch 变大，步数就相应变少。`Run` 可以分段推进，第 5 节的逐轮淘汰要用。
:::

<p class="nb-label">In [6]</p>

```python
test_ids = to_stream(test_poems)
TOKENS = STEPS * BATCH                                            # 固定的 token 预算
BASE = {"lr": 1e-2, "wd": 0.1, "warmup": 0.125, "beta2": 0.999, "decay": 0.2, "batch": 16}

_plans = {}
def plan_for(batch):
    """每种 batch 大小一份 batch 计划，所有配置共用；seed 只决定初始参数。"""
    if batch not in _plans:
        g = torch.Generator().manual_seed(1234)
        _plans[batch] = torch.randint(0, len(train_ids) - cfg.context - 1, (TOKENS // batch, batch), generator=g)
    return _plans[batch]

def lr_at(step, steps, c):
    """WSD：warmup、保持、最后一段线性降到 0（第 17 章）。"""
    warmup = max(1, round(c["warmup"] * steps))
    decay_from = steps - round(c["decay"] * steps)
    if step < warmup:
        return c["lr"] * (step + 1) / warmup
    if step < decay_from:
        return c["lr"]
    return c["lr"] * (steps - step) / (steps - decay_from)

class Run:
    def __init__(self, c, seed=0):
        self.c, self.steps, self.step = c, TOKENS // c["batch"], 0
        torch.manual_seed(seed)
        self.model = TinyLLM(cfg)
        decay = [p for p in self.model.parameters() if p.dim() >= 2]
        no_decay = [p for p in self.model.parameters() if p.dim() < 2]
        self.opt = torch.optim.AdamW([{"params": decay, "weight_decay": c["wd"]},
                                      {"params": no_decay, "weight_decay": 0.0}], lr=c["lr"], betas=(0.9, c["beta2"]))

    def advance(self, until, lr_fn=None):
        """训练到第 until 步。"""
        starts = plan_for(self.c["batch"])
        while self.step < until:
            lr = lr_fn(self.step) if lr_fn else lr_at(self.step, self.steps, self.c)
            for group in self.opt.param_groups:
                group["lr"] = lr
            idx = starts[self.step][:, None] + torch.arange(cfg.context + 1)
            _, loss = self.model(train_ids[idx[:, :-1]], train_ids[idx[:, 1:]])
            self.opt.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(self.model.parameters(), 1.0)
            self.opt.step()
            self.step += 1
        return self

    def fork_decay(self, length):
        """从当前状态分出一个副本，学习率在 length 步内线性降到 0，测它的验证损失；原来的训练不受影响。"""
        twin, start, peak = copy.deepcopy(self), self.step, self.c["lr"]
        twin.advance(start + length, lr_fn=lambda s: peak * (start + length - s) / length)
        return evaluate(twin.model)[0]

def train(c, seed=0, peek=96):
    """一口气训练完；顺便在第 peek 步（还在峰值阶段）测一次验证损失，第 6 节要用。"""
    run = Run(c, seed).advance(peek)
    early = evaluate(run.model)[0]
    run.advance(run.steps)
    return {"config": c, "val": evaluate(run.model)[0], "val_at_peek": early, "model": run.model}
```

::: v-pre
## 2. 噪声底线：同一个配置，换 5 个种子
:::

<p class="nb-label">In [7]</p>

```python
t0 = time.time()
noise = [train(BASE, seed=s) for s in range(5)]
print(f"每次训练约 {(time.time() - t0) / 5:.1f} 秒")
vals = [r["val"] for r in noise]
mean = sum(vals) / len(vals)
sigma = (sum((v - mean) ** 2 for v in vals) / (len(vals) - 1)) ** 0.5
print("5 个种子的验证损失：", "  ".join(f"{v:.4f}" for v in vals))
print(f"平均 {mean:.4f}，标准差 σ = {sigma:.4f}，最大减最小 {max(vals) - min(vals):.4f}")
```

```text
每次训练约 2.5 秒
5 个种子的验证损失： 4.7334  4.7581  4.7520  4.7332  4.7125
平均 4.7378，标准差 σ = 0.0180，最大减最小 0.0456
```

::: v-pre
## 3. 敏感度：每次只改一个超参数

以主线配置（种子 0）为中心，每次只把一个超参数换成更小或更大的值（单个种子），看变化有几个 σ：
:::

<p class="nb-label">In [8]</p>

```python
SWEEP = {"lr": (3.3e-3, 3e-2), "batch": (8, 32), "warmup": (0.02, 0.375), "wd": (0.0, 1.0),
         "beta2": (0.95, 0.99), "decay": (0.1, 0.4)}
center = noise[0]["val"]
sensitivity = {}
for key, values in SWEEP.items():
    sensitivity[key] = {}
    for v in values:
        c = dict(BASE, **{key: v})
        sensitivity[key][v] = train(c)["val"]
    spread = max(abs(x - center) for x in sensitivity[key].values())
    print(f"{key:<7} 主线 {BASE[key]!s:<6}" + "".join(f"  {v!s:>6} → {x:.4f}（{(x - center) / sigma:+5.1f}σ）"
                                                      for v, x in sensitivity[key].items()) + f"   最大偏离 {spread / sigma:4.1f}σ")
```

```text
lr      主线 0.01    0.0033 → 4.8204（ +4.8σ）    0.03 → 5.2104（+26.5σ）   最大偏离 26.5σ
```

```text
batch   主线 16           8 → 4.6892（ -2.5σ）      32 → 5.0272（+16.3σ）   最大偏离 16.3σ
```

```text
warmup  主线 0.125     0.02 → 4.8563（ +6.8σ）   0.375 → 4.7197（ -0.8σ）   最大偏离  6.8σ
```

```text
wd      主线 0.1        0.0 → 4.7634（ +1.7σ）     1.0 → 4.8212（ +4.9σ）   最大偏离  4.9σ
```

```text
beta2   主线 0.999     0.95 → 4.7278（ -0.3σ）    0.99 → 4.7450（ +0.6σ）   最大偏离  0.6σ
```

```text
decay   主线 0.2        0.1 → 4.7544（ +1.2σ）     0.4 → 4.7400（ +0.4σ）   最大偏离  1.2σ
```

::: v-pre
## 4. 耦合：batch 变了，学习率要不要跟着变

上面 batch 32 时步数只剩 120，学习率还是 1e-2。第 17 章说过，batch 变大时常拿“学习率放大 √2 倍”当起点；
这里往两个方向都试一下：
:::

<p class="nb-label">In [9]</p>

```python
coupling = {}
for lr in (5e-3, 1e-2, 1e-2 * 2 ** 0.5):
    c = dict(BASE, batch=32, lr=lr)
    coupling[lr] = sensitivity["batch"][32] if lr == 1e-2 else train(c)["val"]
    print(f"batch 32，学习率 {lr:.2e}：验证损失 {coupling[lr]:.4f}（{(coupling[lr] - center) / sigma:+.1f}σ）")
```

```text
batch 32，学习率 5.00e-03：验证损失 4.9929（+14.4σ）
batch 32，学习率 1.00e-02：验证损失 5.0272（+16.3σ）
```

```text
batch 32，学习率 1.41e-02：验证损失 5.0786（+19.2σ）
```

::: v-pre
## 5. 三种搜索方法，同样的预算

搜索空间：学习率 1e-3～3e-2、weight decay 1e-3～1、1−β2 在 1e-3～1e-1，都按对数均匀取；warmup、衰减比例、batch 用主线的值。
每种方法大约花 9 次完整训练的步数。
:::

<p class="nb-label">In [10]</p>

```python
def sample_config(rng):
    return dict(BASE, lr=10 ** rng.uniform(-3, math.log10(3e-2)), wd=10 ** rng.uniform(-3, 0),
                beta2=1 - 10 ** rng.uniform(-3, -1))

rng = random.Random(0)
pool = [sample_config(rng) for _ in range(27)]               # 随机搜索用前 9 个，逐轮淘汰用全部 27 个
grid = [dict(BASE, lr=lr, wd=wd) for lr in (1e-3, 10 ** -2.25, 10 ** -1.5) for wd in (1e-3, 10 ** -1.5, 1.0)]
```

::: v-pre
网格搜索：学习率和 weight decay 各取 3 个值（对数等距），β2 固定。随机搜索：9 个随机配置。
:::

<p class="nb-label">In [11]</p>

```python
def describe(c):
    return f"lr {c['lr']:.2e}  wd {c['wd']:.2e}  β2 {c['beta2']:.4f}"

searches = {}
for name, configs in (("网格", grid), ("随机", pool[:9])):
    results = [train(c) for c in configs]
    best = min(results, key=lambda r: r["val"])
    searches[name] = {"results": results, "best": best, "steps": len(configs) * STEPS}
    print(f"{name}搜索：{len(configs)} 次 × {STEPS} 步，最好 {best['val']:.4f}（{describe(best['config'])}）")
    print("   试过的学习率：", " ".join(f"{lr:.1e}" for lr in sorted({r['config']['lr'] for r in results})))
```

```text
网格搜索：9 次 × 240 步，最好 4.7398（lr 5.62e-03  wd 1.00e+00  β2 0.9990）
   试过的学习率： 1.0e-03 5.6e-03 3.2e-02
```

```text
随机搜索：9 次 × 240 步，最好 4.7145（lr 7.27e-03  wd 5.30e-01  β2 0.9898）
   试过的学习率： 2.3e-03 2.4e-03 2.6e-03 5.0e-03 7.3e-03 1.2e-02 1.4e-02 1.6e-02 1.8e-02
```

::: v-pre
逐轮淘汰（successive halving）：27 个配置先各训练一小段，只留最好的三分之一，再多训练一段，再留三分之一……
评估时借用 WSD 的性质：从峰值阶段分出一个副本，接一小段衰减再测，原来的训练接着往下走，前面的步数不浪费。
:::

<p class="nb-label">In [12]</p>

```python
RUNGS = [(32, 6), (96, 19)]                                   # (训练到第几步, 分叉衰减多少步)
alive = [Run(c) for c in pool]
spent, rungs = 0, []
for until, fork in RUNGS:
    scored = []
    for run in alive:
        spent += until - run.step + fork
        run.advance(until)
        scored.append((run.fork_decay(fork), evaluate(run.model)[0], run))   # (分叉衰减后, 不衰减直接测, 训练)
    scored.sort(key=lambda t: t[0])
    rungs.append([(s[0], s[1], s[2].c) for s in scored])
    alive = [s[2] for s in scored[:len(scored) // 3]]
    print(f"第 {until:3d} 步：{len(scored)} 个配置，留下 {len(alive)} 个；分叉衰减后的验证损失 "
          + " ".join(f"{s[0]:.3f}" for s in scored[:len(alive)]))
finals = []
for run in alive:
    spent += run.steps - run.step
    run.advance(run.steps)
    finals.append({"config": run.c, "val": evaluate(run.model)[0], "model": run.model})
best = min(finals, key=lambda r: r["val"])
searches["逐轮淘汰"] = {"results": finals, "best": best, "steps": spent}
print(f"逐轮淘汰：一共 {spent} 步（约 {spent / STEPS:.1f} 次完整训练），试了 {len(pool)} 个配置，最好 {best['val']:.4f}（{describe(best['config'])}）")
```

```text
第  32 步：27 个配置，留下 9 个；分叉衰减后的验证损失 5.868 5.919 5.922 5.923 5.955 5.957 5.958 5.958 5.964
```

```text
第  96 步：9 个配置，留下 3 个；分叉衰减后的验证损失 5.075 5.090 5.130
```

```text
逐轮淘汰：一共 2205 步（约 9.2 次完整训练），试了 27 个配置，最好 4.7185（lr 1.16e-02  wd 1.57e-02  β2 0.9554）
```

::: v-pre
## 6. 陷阱一：按中间的损失排名

网格和随机搜索的 18 次训练，都在第 96 步（还在峰值阶段）测过一次验证损失。按它排名，和按最终验证损失排名一致吗？
:::

<p class="nb-label">In [13]</p>

```python
def ranks(xs):
    order = sorted(range(len(xs)), key=xs.__getitem__)
    r = [0] * len(xs)
    for k, i in enumerate(order):
        r[i] = k
    return r

def spearman(a, b):
    ra, rb = ranks(a), ranks(b)
    n = len(a)
    return 1 - 6 * sum((x - y) ** 2 for x, y in zip(ra, rb)) / (n * (n * n - 1))

full = searches["网格"]["results"] + searches["随机"]["results"]
early, final = [r["val_at_peek"] for r in full], [r["val"] for r in full]
print(f"18 次训练：第 96 步的验证损失和最终验证损失的秩相关 {spearman(early, final):.2f}")
by_early = min(full, key=lambda r: r["val_at_peek"])
by_final = min(full, key=lambda r: r["val"])
print(f"按第 96 步挑：{describe(by_early['config'])}，最终 {by_early['val']:.4f}")
print(f"按最终挑：    {describe(by_final['config'])}，最终 {by_final['val']:.4f}")
first = rungs[0]
keep = len(first) // 3
fork_keep = {id(c) for _, _, c in first[:keep]}
raw_keep = {id(c) for _, _, c in sorted(first, key=lambda t: t[1])[:keep]}
print(f"逐轮淘汰第一轮：按“分叉衰减后”和按“不衰减直接测”各留 {keep} 个，相同的有 {len(fork_keep & raw_keep)} 个；"
      f"最终最好的配置{'在' if id(best['config']) in raw_keep else '不在'}“不衰减直接测”留下的名单里")
```

```text
18 次训练：第 96 步的验证损失和最终验证损失的秩相关 0.69
按第 96 步挑：lr 1.20e-02  wd 4.97e-01  β2 0.9767，最终 4.7546
按最终挑：    lr 7.27e-03  wd 5.30e-01  β2 0.9898，最终 4.7145
逐轮淘汰第一轮：按“分叉衰减后”和按“不衰减直接测”各留 9 个，相同的有 7 个；最终最好的配置在“不衰减直接测”留下的名单里
```

::: v-pre
## 7. 陷阱二：赢家的成绩偏乐观

每种方法挑出的赢家，都是在种子 0 上表现最好的那一个。换两个新种子重新训练，再在测试集上测一次：
:::

<p class="nb-label">In [14]</p>

```python
curse = {}
for name, s in searches.items():
    c = s["best"]["config"]
    again = [train(c, seed=seed)["val"] for seed in (1, 2)]
    test = evaluate(s["best"]["model"], test_ids)[0]
    curse[name] = {"picked": s["best"]["val"], "new_seeds": again, "test": test}
    print(f"{name:<4} 挑中时 {s['best']['val']:.4f}   新种子 {again[0]:.4f} {again[1]:.4f}（平均 {sum(again) / 2:.4f}）   测试集 {test:.4f}")
print(f"主线配置：5 个种子平均 {mean:.4f}，种子 0 的测试集 {evaluate(noise[0]['model'], test_ids)[0]:.4f}")
```

```text
网格   挑中时 4.7398   新种子 4.7354 4.7402（平均 4.7378）   测试集 4.7272
```

```text
随机   挑中时 4.7145   新种子 4.7134 4.7276（平均 4.7205）   测试集 4.7030
```

```text
逐轮淘汰 挑中时 4.7185   新种子 4.7611 4.7708（平均 4.7660）   测试集 4.6998
主线配置：5 个种子平均 4.7378，种子 0 的测试集 4.7173
```

<p class="nb-label">In [15]</p>

```python
tuning_log = {
    "steps": STEPS, "base": BASE, "sigma": sigma, "noise": vals, "center": center,
    "sensitivity": {k: {str(v): x for v, x in d.items()} for k, d in sensitivity.items()},
    "coupling": {f"{k:.4g}": v for k, v in coupling.items()},
    "searches": {name: {"steps": s["steps"], "best": s["best"]["val"],
                        "results": [{"config": r["config"], "val": r["val"], "val_at_peek": r.get("val_at_peek")} for r in s["results"]]}
                 for name, s in searches.items()},
    "rungs": [[{"fork": f, "raw": raw, "config": c} for f, raw, c in rung] for rung in rungs],
    "pool": pool, "curse": curse,
}
with open("hyperparameter_tuning_log.json", "w", encoding="utf-8") as f:
    json.dump(tuning_log, f, ensure_ascii=False)
```

