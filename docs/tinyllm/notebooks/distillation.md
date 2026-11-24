---
title: "第 40 章：蒸馏与合成数据（notebook 在线查看）"
search: false
editLink: false
prev: false
next: false
pageClass: tinyllm-course
---

<!-- 本页由 scripts/build-tinyllm-code.py 根据 notebook 自动生成，请勿手改。 -->

::: tip 这是 notebook 的只读预览
[返回教案](/tinyllm/distillation) · [在 Colab 中运行](https://colab.research.google.com/github/lewislau86/lewislau86.github.io/blob/master/docs/public/tinyllm/notebooks/distillation.ipynb) · <a href="/tinyllm/notebooks/distillation.ipynb" download>下载 .ipynb</a> · <a href="/tinyllm/code/distillation.py" download>下载 .py</a> · [在 GitHub 上查看](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/tinyllm/notebooks/distillation.ipynb)

下面的代码和输出与 notebook 文件完全一致。想修改、运行，请用 Colab 打开或下载到本地。
:::

::: v-pre
# 第 40 章：蒸馏与合成数据

配套教案：https://lewislau86.github.io/tinyllm/distillation

从上到下运行即可（`python distillation.py`），CPU 约两分钟。需要安装 PyTorch 和 `tokenizers`。
这个文件是本章代码的唯一来源：教案中的代码片段由 `# region 名字` / `# endregion 名字`
标记的区域直接引用，notebook 也由它生成（scripts/build-tinyllm-code.py）。

老师是第 38 章的预训练基座，学生是宽度减半的小模型。同样的训练量下比较三种训法：从头训、在老师写的诗上训（序列级蒸馏）、
拟合老师每个位置的概率分布（软标签蒸馏），以及温度、只留前 k 个概率、训得更久时差别还在不在。
:::

<p class="nb-label">In [1]</p>

```python
import copy
import json
import math
import random
import re
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
这一章要训练六七十段，原尺寸太慢；损失的绝对值只在本章内部比较。
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

cfg = TinyConfig(vocab_size=1024, d_model=64, n_layers=2, context=128)   # 第 17 章的代理模型，上下文放到 128
print(cfg)
```

```text
TinyConfig(vocab_size=1024, d_model=64, n_layers=2, n_heads=4, context=128, rope_base=10000.0)
```

<p class="nb-label">In [3]</p>

```python
def train_tokenizer(texts, vocab_size):
    tok = Tokenizer(models.BPE())
    tok.pre_tokenizer = pre_tokenizers.ByteLevel(add_prefix_space=False)
    tok.decoder = decoders.ByteLevel()
    trainer = trainers.BpeTrainer(
        vocab_size=vocab_size,
        special_tokens=["<pad>", "<unk>", "<bos>", "<eos>", "<user>", "<assistant>"],   # 后两个是对话模板用的
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
```

::: v-pre
## 1. 数据与老师

和第 38 章相同：统一语料前 6000 首，按 `split` 分训练和验证。老师就是第 38 章的预训练基座（宽 64、2 层，训 2000 步）。
:::

<p class="nb-label">In [5]</p>

```python
poems = load_poems(6000)
pre_train = [p["text"] for p in poems[:6000] if p["split"] == "train"]
pre_val = [p["text"] for p in poems[:6000] if p["split"] == "val"]
tokenizer = train_tokenizer(pre_train, cfg.vocab_size)
PAD, EOS, USER, ASSISTANT = (tokenizer.token_to_id(t) for t in ("<pad>", "<eos>", "<user>", "<assistant>"))

def to_stream(texts):
    ids = []
    for t in texts:
        ids += tokenizer.encode(t).ids + [EOS]
    return torch.tensor(ids)

P_train, P_val = to_stream(pre_train), to_stream(pre_val)
print(f"训练流 {len(P_train):,} 个 token，验证流 {len(P_val):,} 个 token")
```

```text
训练流 296,428 个 token，验证流 15,900 个 token
```

<p class="nb-label">In [6]</p>

```python
def make_optimizer(model, lr):
    decay = [p for p in model.parameters() if p.dim() >= 2]
    no_decay = [p for p in model.parameters() if p.dim() < 2]
    return torch.optim.AdamW([{"params": decay, "weight_decay": 0.1}, {"params": no_decay, "weight_decay": 0.0}], lr=lr)

def step(model, optimizer, loss, lr):
    for group in optimizer.param_groups:
        group["lr"] = lr
    optimizer.zero_grad(set_to_none=True)
    loss.backward()
    torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
    optimizer.step()

def wsd(i, total, peak, warmup=30, decay_frac=0.2):
    start = int(total * (1 - decay_frac))
    if i < warmup:
        return peak * (i + 1) / warmup
    return peak if i < start else peak * (total - i) / (total - start)

def pretrain(seed=0, steps=2000, rows=8):
    torch.manual_seed(seed)
    model = TinyLLM(cfg)
    optimizer = make_optimizer(model, 1e-2)
    plan, T = torch.Generator().manual_seed(1234), cfg.context
    for i in range(steps):
        starts = torch.randint(0, len(P_train) - T - 1, (rows,), generator=plan)
        x = P_train[starts[:, None] + torch.arange(T + 1)]
        _, loss = model(x[:, :-1].contiguous(), x[:, 1:].contiguous())
        step(model, optimizer, loss, wsd(i, steps, 1e-2))
    return model

@torch.no_grad()
def pretrain_loss(model, T=cfg.context, batch=32):
    """预训练验证集上每 token 的损失：看后训练有没有把原来的语言能力训坏。"""
    model.eval()
    n = (len(P_val) - 1) // T * T
    xs, ys = P_val[:n].view(-1, T), P_val[1:n + 1].view(-1, T)
    total = sum(F.cross_entropy(model(xs[i:i + batch]).flatten(0, 1), ys[i:i + batch].flatten(), reduction="sum").item()
                for i in range(0, len(xs), batch))
    model.train()
    return total / ys.numel()

@torch.no_grad()
def sample(model, prompt_ids, n, generator, temperature=0.8, max_new=80):
    """同一个提示采样 n 个回答（一个 batch 一起生成）。返回每个回答的 token、文本、是否生成了 <eos>。"""
    model.eval()
    x = torch.tensor([prompt_ids] * n)
    done = torch.zeros(n, dtype=torch.bool)
    for _ in range(max_new):
        logits = model(x[:, -cfg.context:])[:, -1] / temperature
        nxt = torch.multinomial(F.softmax(logits, dim=-1), 1, generator=generator).squeeze(1)
        nxt = torch.where(done, torch.full_like(nxt, PAD), nxt)
        x = torch.cat([x, nxt[:, None]], dim=1)
        done |= nxt == EOS
        if done.all():
            break
    model.train()
    outs = []
    for row in x[:, len(prompt_ids):].tolist():
        stopped = EOS in row
        ids = row[:row.index(EOS)] if stopped else [t for t in row if t != PAD]
        outs.append((row, tokenizer.decode(ids), stopped))
    return outs

t0 = time.perf_counter()
teacher = pretrain()
teacher.eval()
print(f"[计时，本机] 老师预训练 2000 步 {time.perf_counter() - t0:.1f} 秒；验证损失 {pretrain_loss(teacher):.3f}")
```

```text
[计时，本机] 老师预训练 2000 步 20.6 秒；验证损失 4.305
```

::: v-pre
## 2. 学生：更小的模型

学生宽 32、2 层、2 个头，参数约为老师的三分之一。三种训法用同样的步数（600 步，每步 8 行 × 128 个 token）、同样的学习率（WSD，峰值 1e-2）：
- 从头训：在真实的诗上做下一个 token 预测（硬标签）；真实的诗只取和老师写的一样多（约 10 万个 token），三种训法见到的不同 token 一样多；
- 序列级蒸馏：先让老师写一批诗，学生在老师写的诗上做下一个 token 预测；
- 软标签蒸馏：在真实的诗上，让学生每个位置的分布去拟合老师的分布（KL 散度）。
:::

<p class="nb-label">In [7]</p>

```python
student_cfg = TinyConfig(vocab_size=cfg.vocab_size, d_model=32, n_layers=2, n_heads=2, context=cfg.context)
n_teacher = sum(p.numel() for p in teacher.parameters())
n_student = sum(p.numel() for p in TinyLLM(student_cfg).parameters())
print(f"老师 {n_teacher:,} 个参数，学生 {n_student:,} 个参数（{n_student / n_teacher:.0%}）")
```

```text
老师 163,904 个参数，学生 57,440 个参数（35%）
```

::: v-pre
## 3. 让老师写一批诗

从 `<eos>` 开始无条件采样（温度 1.0，就是老师自己的分布），只留写完了（生成了 `<eos>`）的诗，凑够约 10 万个 token。
:::

<p class="nb-label">In [8]</p>

```python
t0 = time.perf_counter()
g = torch.Generator().manual_seed(40)
written = []
while sum(len(x) for x in written) < 100_000:
    for _, text, stopped in sample(teacher, [EOS], 64, g, temperature=1.0, max_new=90):
        if stopped and text:
            written.append(tokenizer.encode(text).ids + [EOS])
G_train = torch.tensor([t for poem in written for t in poem])
S_train = P_train[:len(G_train)]                      # 真实的诗也只取同样多，三种训法看到的不同 token 一样多
print(f"[计时，本机] 老师写了 {len(written)} 首、{len(G_train):,} 个 token，用时 {time.perf_counter() - t0:.1f} 秒")
print(f"学生 600 步共看 {600 * 8 * cfg.context:,} 个 token，约是这份数据的 {600 * 8 * cfg.context / len(G_train):.1f} 遍")
for poem in written[:3]:
    print("  ", tokenizer.decode(poem[:-1]))
```

```text
[计时，本机] 老师写了 1788 首、103,223 个 token，用时 11.3 秒
学生 600 步共看 614,400 个 token，约是这份数据的 6.0 遍
   居阔丝物，寂寂道与乡。邻随步号马，离枝上向人。雨医何伤	，纷子贪江移。寄会如荣发，经秋岂有闲。
   神出世人居，何合楚艳东。失孝自小艴，何人不几时。
   壁不可�跎，此心诗求异源。败台凉霄遭，秦树映金营。菊来到五字，即有有时分。失桥居讫事，虚觉大归书。
```

::: v-pre
## 4. 三种训法
:::

<p class="nb-label">In [9]</p>

```python
def kd_loss(student_logits, teacher_logits, temperature=1.0, top_k=None):
    """每个位置上 KL(老师 ‖ 学生)：前向 KL，学生要覆盖老师认为可能的所有 token。"""
    t = teacher_logits / temperature
    if top_k is not None:                                   # 只保留老师前 k 个 token（离线存储时常这样做），其余视为 0
        kth = t.topk(top_k, dim=-1).values[..., -1:]
        t = t.masked_fill(t < kth, float("-inf"))
    p_teacher = F.softmax(t, dim=-1)
    log_student = F.log_softmax(student_logits / temperature, dim=-1)
    kl = (p_teacher * (torch.log(p_teacher.clamp_min(1e-12)) - log_student)).sum(-1)
    return kl.mean() * temperature ** 2

def train_student(seed, mode, steps=600, rows=8, peak=1e-2, temperature=1.0, top_k=None, record=(200, 400, 600)):
    torch.manual_seed(seed)
    model = TinyLLM(student_cfg)
    optimizer = make_optimizer(model, peak)
    plan, T = torch.Generator().manual_seed(1234), cfg.context
    source = G_train if mode == "序列级蒸馏" else S_train
    curve = {}
    for i in range(steps):
        starts = torch.randint(0, len(source) - T - 1, (rows,), generator=plan)
        x = source[starts[:, None] + torch.arange(T + 1)]
        logits = model(x[:, :-1].contiguous())
        if mode == "软标签蒸馏":
            with torch.no_grad():
                teacher_logits = teacher(x[:, :-1].contiguous())
            loss = kd_loss(logits, teacher_logits, temperature, top_k)
        else:
            loss = F.cross_entropy(logits.flatten(0, 1), x[:, 1:].flatten())
        step(model, optimizer, loss, wsd(i, steps, peak))
        if i + 1 in record:
            curve[i + 1] = pretrain_loss(model)
    return model, curve

@torch.no_grad()
def kl_to_teacher(model, T=cfg.context, batch=32):
    """验证集上每个位置 KL(老师 ‖ 学生) 的平均：学生的分布离老师有多远。"""
    model.eval()
    n = (len(P_val) - 1) // T * T
    xs = P_val[:n].view(-1, T)
    total = sum(kd_loss(model(xs[i:i + batch]), teacher(xs[i:i + batch])).item() * len(xs[i:i + batch]) for i in range(0, len(xs), batch))
    model.train()
    return total / len(xs)

MODES = ("从头训", "序列级蒸馏", "软标签蒸馏")
t0 = time.perf_counter()
runs = {m: [train_student(s, m) for s in (0, 1, 2)] for m in MODES}
print(f"[计时，本机] 3 种训法 × 3 个种子，各 600 步，共 {time.perf_counter() - t0:.1f} 秒")
summary = {}
for m in MODES:
    final = [c[600] for _, c in runs[m]]
    kl = [kl_to_teacher(model) for model, _ in runs[m]]
    summary[m] = {"curve": {k: sum(c[k] for _, c in runs[m]) / 3 for k in (200, 400, 600)}, "final": final, "kl": kl}
    print(f"{m:6}  验证损失 第 200/400/600 步 " + " ".join(f"{summary[m]['curve'][k]:.3f}" for k in (200, 400, 600))
          + f"  │ 最终 [{min(final):.3f}, {max(final):.3f}]  离老师的 KL {sum(kl) / 3:.3f}")
print(f"老师自己的验证损失 {pretrain_loss(teacher):.3f}")
log["summary"] = summary
```

```text
[计时，本机] 3 种训法 × 3 个种子，各 600 步，共 41.9 秒
```

```text
从头训     验证损失 第 200/400/600 步 4.998 4.800 4.675  │ 最终 [4.631, 4.701]  离老师的 KL 0.558
```

```text
序列级蒸馏   验证损失 第 200/400/600 步 5.038 4.880 4.761  │ 最终 [4.739, 4.800]  离老师的 KL 0.553
```

```text
软标签蒸馏   验证损失 第 200/400/600 步 4.767 4.567 4.471  │ 最终 [4.444, 4.506]  离老师的 KL 0.253
老师自己的验证损失 4.305
```

::: v-pre
## 5. 软标签的几个变体

种子 0 再试三种：温度 2（先把老师和学生的分布都“摊平”再比，KL 乘 T² 保持梯度的量级）；只保留老师前 8 个 token 的概率；训得更久（1800 步，和从头训比）。
:::

<p class="nb-label">In [10]</p>

```python
t0 = time.perf_counter()
variants = {
    "软标签，温度 2": train_student(0, "软标签蒸馏", temperature=2.0)[1][600],
    "软标签，只留前 8 个": train_student(0, "软标签蒸馏", top_k=8)[1][600],
}
long = {m: train_student(0, m, steps=1800, record=(600, 1200, 1800))[1] for m in ("从头训", "软标签蒸馏")}
print(f"[计时，本机] {time.perf_counter() - t0:.1f} 秒")
print(f"软标签，温度 1（种子 0）    验证损失 {runs['软标签蒸馏'][0][1][600]:.3f}")
for k, v in variants.items():
    print(f"{k:14} 验证损失 {v:.3f}")
with torch.no_grad():
    xs = P_val[:(len(P_val) - 1) // cfg.context * cfg.context]
    top8 = teacher(xs.view(-1, cfg.context)).topk(8, dim=-1).indices
    hit = (top8 == P_val[1:len(xs) + 1].view(-1, cfg.context)[..., None]).any(-1).float().mean().item()
print(f"验证集上，真实的下一个字落在老师前 8 个候选里的比例 {hit:.0%}")
for m, c in long.items():
    print(f"{m}，1800 步：第 600/1200/1800 步 " + " ".join(f"{c[k]:.3f}" for k in (600, 1200, 1800)))
log["variants"], log["long"] = variants, long
```

```text
[计时，本机] 43.9 秒
软标签，温度 1（种子 0）    验证损失 4.462
软标签，温度 2       验证损失 4.590
软标签，只留前 8 个    验证损失 6.327
验证集上，真实的下一个字落在老师前 8 个候选里的比例 43%
从头训，1800 步：第 600/1200/1800 步 4.756 4.778 4.613
软标签蒸馏，1800 步：第 600/1200/1800 步 4.553 4.451 4.371
```

<p class="nb-label">In [11]</p>

```python
with open("distillation_log.json", "w", encoding="utf-8") as f:
    json.dump(log, f, ensure_ascii=False)
print("已写出 distillation_log.json")
```

```text
已写出 distillation_log.json
```

