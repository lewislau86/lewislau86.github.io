---
title: "第 17 章：学习率策略（notebook 在线查看）"
search: false
editLink: false
prev: false
next: false
pageClass: tinyllm-course
---

<!-- 本页由 scripts/build-tinyllm-code.py 根据 notebook 自动生成，请勿手改。 -->

::: tip 这是 notebook 的只读预览
[返回教案](/tinyllm/learning-rate) · [在 Colab 中运行](https://colab.research.google.com/github/lewislau86/lewislau86.github.io/blob/master/docs/public/tinyllm/notebooks/learning-rate.ipynb) · <a href="/tinyllm/notebooks/learning-rate.ipynb" download>下载 .ipynb</a> · <a href="/tinyllm/code/learning-rate.py" download>下载 .py</a> · [在 GitHub 上查看](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/tinyllm/notebooks/learning-rate.ipynb)

下面的代码和输出与 notebook 文件完全一致。想修改、运行，请用 Colab 打开或下载到本地。
:::

::: v-pre
# 第 17 章：学习率策略

配套教案：https://lewislau86.github.io/tinyllm/learning-rate

从上到下运行即可（`python learning-rate.py`），CPU 上约两分钟（一共训练 17 个小模型，每个约 7 秒）。需要安装 PyTorch 和 `tokenizers`。
这个文件是本章代码的唯一来源：教案中的代码片段由 `# region 名字` / `# endregion 名字`
标记的区域直接引用，notebook 也由它生成（scripts/build-tinyllm-code.py）。

第 12 章的学习率固定为 3e-3，第 13 章换成了“先升后降”的 lr_at。本章用对照实验回答：要不要调度、峰值取多大、warmup 有什么用。
:::

<p class="nb-label">In [1]</p>

```python
import json
import math
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
## 0. 第 12 章的模型，缩小成一个代理模型

模型代码、数据划分、评估口径都从第 12 章原样复制。学习率实验要训练十几次，原尺寸一次要一分半，
所以把配置缩小：词表 1024、宽度 64、2 层。损失的绝对值因此和第 12 章的 5.579 不能直接比（词表不同），只在本章内部比较。
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

cfg = TinyConfig(vocab_size=1024, d_model=64, n_layers=2)       # 代理模型：只改这三个尺寸
STEPS, BATCH = 240, 16
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
## 1. 一次训练：学习率由一个函数给出

训练循环和第 12 章相同（AdamW、weight decay 0.1、梯度裁剪 1.0），只多一行：每步开始前，按 `schedule(step)` 设置学习率。
batch 计划由单独的随机数生成器排好，所有对照共用；`seed` 只决定初始参数。
:::

<p class="nb-label">In [6]</p>

```python
plan = torch.Generator().manual_seed(1234)
starts = torch.randint(0, len(train_ids) - cfg.context - 1, (STEPS, BATCH), generator=plan)

def train(schedule, seed, every=30):
    torch.manual_seed(seed)
    model = TinyLLM(cfg)
    decay = [p for p in model.parameters() if p.dim() >= 2]
    no_decay = [p for p in model.parameters() if p.dim() < 2]
    optimizer = torch.optim.AdamW([{"params": decay, "weight_decay": 0.1},
                                   {"params": no_decay, "weight_decay": 0.0}], lr=schedule(0))
    log = {"train": [], "val_step": [], "val": []}
    for step in range(STEPS):
        for group in optimizer.param_groups:
            group["lr"] = schedule(step)                         # 每个优化器步之前设置学习率
        idx = starts[step][:, None] + torch.arange(cfg.context + 1)
        _, loss = model(train_ids[idx[:, :-1]], train_ids[idx[:, 1:]])
        optimizer.zero_grad(set_to_none=True)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        optimizer.step()
        log["train"].append(loss.item())
        if (step + 1) % every == 0 and (seed == 0 or step + 1 == STEPS):    # 种子 0 记整条曲线，其余只测最后一次
            log["val_step"].append(step + 1)
            log["val"].append(evaluate(model)[0])
    return log
```

::: v-pre
## 2. 先扫一遍固定学习率

不加任何调度，学习率从 1e-3 到 1e-2 取三个值，各训练一次（单个种子，先看大致范围）：
:::

<p class="nb-label">In [7]</p>

```python
constant = lambda lr: (lambda step: lr)
runs = {}
t0 = time.time()
for lr in (1e-3, 3e-3, 1e-2):
    runs[("constant", lr, 0)] = train(constant(lr), seed=0)
    print(f"固定 {lr:.0e}：最终验证损失 {runs[('constant', lr, 0)]['val'][-1]:.3f}")
print(f"每次训练约 {(time.time() - t0) / 3:.1f} 秒")
```

```text
固定 1e-03：最终验证损失 5.074
```

```text
固定 3e-03：最终验证损失 4.797
```

```text
固定 1e-02：最终验证损失 4.944
每次训练约 8.3 秒
```

::: v-pre
## 3. 几种调度的形状

第 13 章的 `lr_at` 是“线性 warmup + 余弦降到峰值的 10%”。再加两种常见的：WSD（warmup-stable-decay：升上去、保持、最后 20% 线性降到 0），
以及从头到尾线性下降。都写成“给步数、返回学习率”的函数：
:::

<p class="nb-label">In [8]</p>

```python
def warmup_cosine(peak, warmup=30, floor=0.1):
    def lr(step):
        if step < warmup:
            return peak * (step + 1) / warmup
        progress = (step - warmup) / (STEPS - warmup)
        return peak * (floor + (1 - floor) * 0.5 * (1 + math.cos(math.pi * progress)))
    return lr

def wsd(peak, warmup=30, decay_frac=0.2):
    decay_steps = int(STEPS * decay_frac)
    def lr(step):
        if step < warmup:
            return peak * (step + 1) / warmup
        if step < STEPS - decay_steps:
            return peak
        return peak * (STEPS - step) / decay_steps
    return lr

def linear(peak, warmup=30):
    return lambda step: peak * (step + 1) / warmup if step < warmup else peak * (STEPS - step) / (STEPS - warmup)

shapes = {"固定": constant(1e-2), "warmup+余弦": warmup_cosine(1e-2), "WSD": wsd(1e-2), "warmup+线性": linear(1e-2)}
for name, f in shapes.items():
    print(f"{name:<10}" + "  ".join(f"{s:>3}步 {f(s):.4f}" for s in (0, 15, 29, 120, 191, 215, 239)))
```

```text
固定          0步 0.0100   15步 0.0100   29步 0.0100  120步 0.0100  191步 0.0100  215步 0.0100  239步 0.0100
warmup+余弦   0步 0.0003   15步 0.0053   29步 0.0100  120步 0.0065  191步 0.0022  215步 0.0013  239步 0.0010
WSD         0步 0.0003   15步 0.0053   29步 0.0100  120步 0.0100  191步 0.0100  215步 0.0052  239步 0.0002
warmup+线性   0步 0.0003   15步 0.0053   29步 0.0100  120步 0.0057  191步 0.0023  215步 0.0012  239步 0.0000
```

::: v-pre
PyTorch 自带的 `LambdaLR` 做的是同一件事：每次 `scheduler.step()`，把学习率设成“初始学习率 × 函数值”。核对一下：
:::

<p class="nb-label">In [9]</p>

```python
opt = torch.optim.AdamW([torch.zeros(1, requires_grad=True)], lr=1e-2)
scheduler = torch.optim.lr_scheduler.LambdaLR(opt, lambda step: wsd(1e-2)(step) / 1e-2)
seen = []
for step in range(STEPS):
    seen.append(opt.param_groups[0]["lr"])                    # 这一步实际用的学习率
    opt.step()
    scheduler.step()                                          # 每个优化器步之后调用一次
print("和 wsd() 的最大差：", max(abs(a - wsd(1e-2)(s)) for s, a in enumerate(seen)))
```

```text
和 wsd() 的最大差： 8.673617379884035e-19
```

::: v-pre
## 4. 对照：衰减本身有用吗？峰值要不要跟着变？

每种设置 3 个种子（0、1、2），batch 计划相同。先在最好的固定学习率 3e-3 上加 warmup+余弦，再把峰值提到 1e-2：
:::

<p class="nb-label">In [10]</p>

```python
settings = [("固定 3e-3", "constant", 3e-3, constant(3e-3)),
            ("warmup+余弦，峰值 3e-3", "cosine", 3e-3, warmup_cosine(3e-3)),
            ("warmup+余弦，峰值 1e-2", "cosine", 1e-2, warmup_cosine(1e-2)),
            ("WSD，峰值 1e-2", "wsd", 1e-2, wsd(1e-2))]
summary = {}
for label, kind, lr, f in settings:
    finals = []
    for seed in (0, 1, 2):
        key = (kind, lr, seed)
        if key not in runs:
            runs[key] = train(f, seed)
        finals.append(runs[key]["val"][-1])
    summary[label] = finals
    print(f"{label:<18} 平均 {sum(finals) / 3:.3f}  范围 {min(finals):.3f}～{max(finals):.3f}")
```

```text
固定 3e-3            平均 4.805  范围 4.797～4.810
```

```text
warmup+余弦，峰值 3e-3  平均 4.987  范围 4.970～5.014
```

```text
warmup+余弦，峰值 1e-2  平均 4.801  范围 4.788～4.821
```

```text
WSD，峰值 1e-2        平均 4.748  范围 4.733～4.757
```

::: v-pre
## 5. 对照：去掉 warmup

同样是峰值 1e-2 的 WSD，warmup 从 30 步改成 1 步（第一步就用满学习率）：
:::

<p class="nb-label">In [11]</p>

```python
finals = []
for seed in (0, 1, 2):
    runs[("wsd-no-warmup", 1e-2, seed)] = train(wsd(1e-2, warmup=1), seed)
    finals.append(runs[("wsd-no-warmup", 1e-2, seed)]["val"][-1])
summary["WSD，峰值 1e-2，无 warmup"] = finals
print(f"无 warmup：平均 {sum(finals) / 3:.3f}  范围 {min(finals):.3f}～{max(finals):.3f}")
for name, key in [("有 warmup", ("wsd", 1e-2, 0)), ("无 warmup", ("wsd-no-warmup", 1e-2, 0))]:
    head = runs[key]["train"][:30]
    print(f"{name}（种子 0）前 30 步训练损失：第 1 步 {head[0]:.2f}，第 10 步 {head[9]:.2f}，第 30 步 {head[29]:.2f}")
```

```text
无 warmup：平均 4.884  范围 4.836～4.915
有 warmup（种子 0）前 30 步训练损失：第 1 步 7.43，第 10 步 6.47，第 30 步 6.05
无 warmup（种子 0）前 30 步训练损失：第 1 步 7.43，第 10 步 6.09，第 30 步 5.94
```

::: v-pre
## 6. 读损失曲线：衰减段的“下台阶”

把种子 0 的验证损失按步数打印出来（每 30 步一次）：
:::

<p class="nb-label">In [12]</p>

```python
print("步数  " + "  ".join(f"{s:>5}" for s in runs[("constant", 3e-3, 0)]["val_step"]))
for name, key in [("固定 3e-3", ("constant", 3e-3, 0)), ("余弦 1e-2", ("cosine", 1e-2, 0)), ("WSD 1e-2", ("wsd", 1e-2, 0))]:
    print(f"{name:<8}" + "  ".join(f"{v:5.2f}" for v in runs[key]["val"]))
```

```text
步数     30     60     90    120    150    180    210    240
固定 3e-3  6.00   5.78   5.30   5.13   5.00   4.92   4.84   4.80
余弦 1e-2  6.05   5.56   5.26   5.10   4.97   4.89   4.83   4.80
WSD 1e-2 6.05   5.56   5.28   5.12   4.98   4.92   4.82   4.73
```

<p class="nb-label">In [13]</p>

```python
lr_log = {
    "steps": STEPS, "sweep": {f"{lr:.0e}": runs[("constant", lr, 0)]["val"][-1] for lr in (1e-3, 3e-3, 1e-2)},
    "summary": summary,
    "schedules": {name: [f(s) for s in range(STEPS)] for name, f in shapes.items()},
    "curves": {f"{k[0]}|{k[1]:.0e}|{k[2]}": v for k, v in runs.items()},
}
with open("learning_rate_log.json", "w", encoding="utf-8") as f:
    json.dump(lr_log, f, ensure_ascii=False)
```

