---
title: "第 36 章：长上下文扩展（notebook 在线查看）"
search: false
editLink: false
prev: false
next: false
pageClass: tinyllm-course
---

<!-- 本页由 scripts/build-tinyllm-code.py 根据 notebook 自动生成，请勿手改。 -->

::: tip 这是 notebook 的只读预览
[返回教案](/tinyllm/long-context) · [在 Colab 中运行](https://colab.research.google.com/github/lewislau86/lewislau86.github.io/blob/master/docs/public/tinyllm/notebooks/long-context.ipynb) · <a href="/tinyllm/notebooks/long-context.ipynb" download>下载 .ipynb</a> · <a href="/tinyllm/code/long-context.py" download>下载 .py</a> · [在 GitHub 上查看](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/tinyllm/notebooks/long-context.ipynb)

下面的代码和输出与 notebook 文件完全一致。想修改、运行，请用 Colab 打开或下载到本地。
:::

::: v-pre
# 第 36 章：长上下文扩展

配套教案：https://lewislau86.github.io/tinyllm/long-context

从上到下运行即可（`python long-context.py`），CPU 约两分钟。需要安装 PyTorch 和 `tokenizers`。
这个文件是本章代码的唯一来源：教案中的代码片段由 `# region 名字` / `# endregion 名字`
标记的区域直接引用，notebook 也由它生成（scripts/build-tinyllm-code.py）。

本章用第 17 章的代理模型，在 64 个位置上训练，再把上下文扩到 256：比较直接外推、位置插值、调大 RoPE base、YaRN，
每种都看“不训练”和“用长序列训一小段”两种情况；除了按位置看损失，还用一个检索任务检查模型是否真的用到了远处的信息。
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
这一章要训练 3 个基线和十几段扩展，原尺寸太慢；损失的绝对值只在本章内部比较。
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
```

::: v-pre
## 1. 数据，以及一个“找回字母”的任务

普通数据还是统一语料的前 6000 首，按 `split` 分训练和验证，分词器只用训练集。
光看语言模型的损失，分不出模型有没有用到远处的信息：一串互不相干的诗拼在一起，远处的诗对预测下一个字几乎没用。
所以另加一个检索任务（和 passkey retrieval 同一个思路）：在某一行的某个位置放一个字母（a～p 之一，唐诗里从不出现），
后面再出现 `<bos>` 时，下一个 token 必须是那个字母。字母和 `<bos>` 之间隔多远，就是要检索的距离。
:::

<p class="nb-label">In [5]</p>

```python
poems = load_poems(6000)
train_poems = [p["text"] for p in poems if p["split"] == "train"]
val_poems = [p["text"] for p in poems if p["split"] == "val"]
tokenizer = train_tokenizer(train_poems, cfg.vocab_size)
EOS, BOS = tokenizer.token_to_id("<eos>"), tokenizer.token_to_id("<bos>")

def to_stream(texts):
    ids = []
    for t in texts:
        ids += tokenizer.encode(t).ids + [EOS]
    return torch.tensor(ids)

train_ids, val_ids = to_stream(train_poems), to_stream(val_poems)
KEYS = [tokenizer.encode(c).ids[0] for c in "abcdefghijklmnop"]          # 16 个字母，每个都是单独一个 token
assert not any((train_ids == k).any() or (val_ids == k).any() for k in KEYS)
print(f"训练流 {len(train_ids):,} 个 token，验证流 {len(val_ids):,} 个 token；检索用的字母 {len(KEYS)} 个，语料里一次也没出现过")

def plain_row(stream, T, g):
    s = torch.randint(0, len(stream) - T - 1, (1,), generator=g).item()
    return stream[s:s + T + 1].tolist()

def retrieval_row(T, g, max_dist, far_first):
    """训练用：一行普通文本里放一个字母，再插几处查询（<bos>+字母），每处查询都是一个训练目标。
    far_first=False（基线）：几处查询随机落在字母之后 max_dist 个位置以内，后面的查询可以从前面的查询抄。
    far_first=True（扩展）：第一处查询离字母正好 d 个位置，d 在 3～max_dist 之间均匀；其余查询都在它之后。"""
    row = plain_row(train_ids, T, g)
    key = KEYS[torch.randint(len(KEYS), (1,), generator=g).item()]
    d = torch.randint(3, max_dist + 1, (1,), generator=g).item()
    p0 = torch.randint(0, T - d, (1,), generator=g).item()
    row[p0] = key
    if far_first:
        row[p0 + d:p0 + d + 2] = [BOS, key]
        lo = p0 + d + 3
    else:
        lo = p0 + 2
    hi = T if far_first else p0 + d
    for q in sorted(set(torch.randint(lo, max(hi, lo + 1), (5,), generator=g).tolist())):
        if q < hi and row[q - 1] != BOS:
            row[q:q + 2] = [BOS, key]
    return row[:T + 1]

def make_batch(T, rows, g, p_retrieval, max_dist, far_first=False):
    return torch.tensor([retrieval_row(T, g, max_dist, far_first) if torch.rand(1, generator=g).item() < p_retrieval
                         else plain_row(train_ids, T, g) for _ in range(rows)])

@torch.no_grad()
def retrieval_acc(model, d, T=256, n=96):
    """测试用：长 T 的一行验证文本，倒数第 2 个位置放 <bos>，往前第 d 个位置放字母，看下一个 token 猜得对不对。"""
    model.eval()
    g, hit = torch.Generator().manual_seed(777), 0
    for _ in range(n):
        row = plain_row(val_ids, T, g)
        key = KEYS[torch.randint(len(KEYS), (1,), generator=g).item()]
        q = T - 2
        row[q - d], row[q] = key, BOS
        hit += int(model(torch.tensor(row[:q + 1])[None])[0, -1].argmax().item() == key)
    model.train()
    return hit / n
```

```text
训练流 296,250 个 token，验证流 15,892 个 token；检索用的字母 16 个，语料里一次也没出现过
```

::: v-pre
## 2. 基线：在 64 个位置上训练

第 17 章的 WSD：warmup 30 步，峰值 1e-2，最后 20% 线性降到 0，共 800 步。四分之一的行带检索任务，字母到查询的距离不超过 60。
三个种子只决定初始参数，batch 由单独的生成器排好。
:::

<p class="nb-label">In [6]</p>

```python
def make_optimizer(model, lr):
    decay = [p for p in model.parameters() if p.dim() >= 2]
    no_decay = [p for p in model.parameters() if p.dim() < 2]
    return torch.optim.AdamW([{"params": decay, "weight_decay": 0.1}, {"params": no_decay, "weight_decay": 0.0}], lr=lr)

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

def train_base(seed, steps=800):
    torch.manual_seed(seed)
    model = TinyLLM(cfg)
    optimizer = make_optimizer(model, 1e-2)
    plan = torch.Generator().manual_seed(1234)
    for step in range(steps):
        train_step(model, optimizer, make_batch(cfg.context, BATCH, plan, 0.25, 60), wsd(step, steps, 1e-2))
    return model

SEEDS = (0, 1, 2)
t0 = time.perf_counter()
bases = {seed: copy.deepcopy(train_base(seed).state_dict()) for seed in SEEDS}
print(f"[计时，本机] 3 个基线各 800 步，共 {time.perf_counter() - t0:.1f} 秒")
```

```text
[计时，本机] 3 个基线各 800 步，共 23.3 秒
```

::: v-pre
## 3. 四种位置方案

训练长度 64，目标长度 256，倍数 s = 4。第 7 章的 RoPE 给第 i 对维度的旋转速度是 θ_i = base^(-2i/d_head)，位置 m 转过 m·θ_i。
- 直接外推：什么都不改，位置 64～255 用训练时没见过的角度。
- 位置插值（PI）：位置除以 s，256 个位置压回 0～64 的角度范围。
- 调大 base（NTK 公式）：base 换成 base·s^(d_head/(d_head−2))，低频维度变慢得多、高频维度几乎不变。
- YaRN：按每一维在训练长度内转了几圈分段处理，转得多的维度不动、转得少的维度做插值，中间线性过渡；再把注意力分数乘一个温度。
:::

<p class="nb-label">In [7]</p>

```python
HEAD_DIM = cfg.d_model // cfg.n_heads

def rope_angles(method, T, s=4.0, base=cfg.rope_base, train_len=cfg.context, alpha=1.0, beta=32.0, temperature=True):
    """返回 (T, HEAD_DIM/2) 的旋转角度，以及 q、k 各乘的系数。"""
    i = torch.arange(0, HEAD_DIM, 2).float()
    theta = base ** (-i / HEAD_DIM)
    pos, scale = torch.arange(T).float(), 1.0
    if method == "pi":                                           # 位置插值：位置除以 s
        pos = pos / s
    elif method == "ntk":                                        # 调大 base：低频维度变慢得多
        theta = (base * s ** (HEAD_DIM / (HEAD_DIM - 2))) ** (-i / HEAD_DIM)
    elif method == "yarn":
        turns = train_len * theta / (2 * math.pi)                # 训练长度内转了几圈
        keep = ((turns - alpha) / (beta - alpha)).clamp(0, 1)    # 1：不动；0：完全插值
        theta = keep * theta + (1 - keep) * theta / s
        scale = 0.1 * math.log(s) + 1 if temperature else 1.0    # q、k 各乘一次，注意力分数乘它的平方
    return pos[:, None] * theta, scale

def with_rope(state, method, T=256, **kw):
    model = TinyLLM(cfg)
    model.load_state_dict(state)
    angle, scale = rope_angles(method, T, **kw)
    model.cos, model.sin = angle.cos() * scale, angle.sin() * scale
    return model

METHODS = ("direct", "pi", "ntk", "yarn")
NAMES = {"direct": "直接外推", "pi": "位置插值", "ntk": "调大 base", "yarn": "YaRN"}
print("每一对维度最多转几圈（最后一个位置的角度 ÷ 2π）；第 0 对转得最快")
print(f"{'训练（64 个位置）':12}", " ".join(f"{t:6.2f}" for t in (rope_angles('direct', 64)[0][-1] / (2 * math.pi)).tolist()))
for m in METHODS:
    print(f"{NAMES[m] + '（256）':12}", " ".join(f"{t:6.2f}" for t in (rope_angles(m, 256)[0][-1] / (2 * math.pi)).tolist()))
```

```text
每一对维度最多转几圈（最后一个位置的角度 ÷ 2π）；第 0 对转得最快
训练（64 个位置）    10.03   3.17   1.00   0.32   0.10   0.03   0.01   0.00
直接外推（256）     40.58  12.83   4.06   1.28   0.41   0.13   0.04   0.01
位置插值（256）     10.15   3.21   1.01   0.32   0.10   0.03   0.01   0.00
调大 base（256）  40.58  10.53   2.73   0.71   0.18   0.05   0.01   0.00
YaRN（256）     19.17   3.90   1.02   0.32   0.10   0.03   0.01   0.00
```

::: v-pre
## 4. 不训练，直接用到 256 个位置
:::

<p class="nb-label">In [8]</p>

```python
@torch.no_grad()
def position_loss(model, T=256, chunk=64):
    """把验证流切成长 T 的段，按位置分组（每 64 个一组）报告平均损失。"""
    model.eval()
    n = (len(val_ids) - 1) // T * T
    xs, ys = val_ids[:n].view(-1, T), val_ids[1:n + 1].view(-1, T)
    per = torch.cat([F.cross_entropy(model(xs[i:i + 16]).transpose(1, 2), ys[i:i + 16], reduction="none") for i in range(0, len(xs), 16)]).mean(0)
    model.train()
    return [per[a:a + chunk].mean().item() for a in range(0, T, chunk)]

DISTS = (16, 48, 112, 176, 240)

def report(model):
    return {"loss": position_loss(model), "acc": {d: retrieval_acc(model, d) for d in DISTS}}

def show(name, rows):
    loss = [sum(r["loss"][k] for r in rows) / len(rows) for k in range(4)]
    acc = [sum(r["acc"][d] for r in rows) / len(rows) for d in DISTS]
    print(f"{name:14} 损失（位置 0-63 / 64-127 / 128-191 / 192-255） " + " ".join(f"{x:.3f}" for x in loss)
          + "   检索准确率（距离 " + "/".join(map(str, DISTS)) + "） " + " ".join(f"{a:.2f}" for a in acc))

untrained = {m: [report(with_rope(bases[s], m)) for s in SEEDS] for m in METHODS}
untrained["yarn-notemp"] = [report(with_rope(bases[s], "yarn", temperature=False)) for s in SEEDS]
for m in METHODS:
    show(NAMES[m], untrained[m])
show("YaRN（去掉温度）", untrained["yarn-notemp"])
```

```text
直接外推           损失（位置 0-63 / 64-127 / 128-191 / 192-255） 4.461 4.744 6.144 6.176   检索准确率（距离 16/48/112/176/240） 0.96 0.41 0.10 0.26 0.23
位置插值           损失（位置 0-63 / 64-127 / 128-191 / 192-255） 5.851 5.973 5.948 5.965   检索准确率（距离 16/48/112/176/240） 0.99 0.99 0.86 0.56 0.57
调大 base        损失（位置 0-63 / 64-127 / 128-191 / 192-255） 5.085 5.176 5.078 5.503   检索准确率（距离 16/48/112/176/240） 0.97 0.71 0.53 0.19 0.12
YaRN           损失（位置 0-63 / 64-127 / 128-191 / 192-255） 5.928 6.058 6.034 6.057   检索准确率（距离 16/48/112/176/240） 1.00 1.00 1.00 0.97 0.93
YaRN（去掉温度）     损失（位置 0-63 / 64-127 / 128-191 / 192-255） 5.871 5.986 5.966 5.984   检索准确率（距离 16/48/112/176/240） 0.99 0.99 0.85 0.54 0.53
```

::: v-pre
## 5. 用长序列训一小段
:::

<p class="nb-label">In [9]</p>

```python
def extend(state, method, steps=150, max_dist=254, peak=3e-3, T=256, rows=4):
    model = with_rope(state, method, T)
    optimizer = make_optimizer(model, peak)
    plan = torch.Generator().manual_seed(4321)
    for step in range(steps):
        lr = peak * (step + 1) / 10 if step < 10 else peak * (steps - step) / (steps - 10)   # warmup 10 步，再线性降到 0
        train_step(model, optimizer, make_batch(T, rows, plan, 0.25, max_dist, far_first=True), lr)
    return model

t0 = time.perf_counter()
trained = {m: [report(extend(bases[s], m)) for s in SEEDS] for m in METHODS}
print(f"[计时，本机] 4 种方案 × 3 个种子，各在长度 256 上训 150 步，共 {time.perf_counter() - t0:.1f} 秒")
for m in METHODS:
    show(NAMES[m] + "+训练", trained[m])
log["untrained"], log["trained"] = untrained, trained
```

```text
[计时，本机] 4 种方案 × 3 个种子，各在长度 256 上训 150 步，共 27.2 秒
直接外推+训练        损失（位置 0-63 / 64-127 / 128-191 / 192-255） 4.437 4.387 4.353 4.395   检索准确率（距离 16/48/112/176/240） 1.00 1.00 1.00 1.00 1.00
位置插值+训练        损失（位置 0-63 / 64-127 / 128-191 / 192-255） 4.573 4.510 4.473 4.509   检索准确率（距离 16/48/112/176/240） 1.00 1.00 1.00 1.00 1.00
调大 base+训练     损失（位置 0-63 / 64-127 / 128-191 / 192-255） 4.429 4.382 4.343 4.377   检索准确率（距离 16/48/112/176/240） 1.00 1.00 1.00 1.00 1.00
YaRN+训练        损失（位置 0-63 / 64-127 / 128-191 / 192-255） 4.526 4.462 4.431 4.458   检索准确率（距离 16/48/112/176/240） 1.00 1.00 1.00 1.00 1.00
```

::: v-pre
## 6. 长序列里只有近处的依赖时

上一节扩展用的长序列里，四分之一的行带检索任务，第一处查询离字母 3～254 个位置（均匀）。
如果长序列虽然长，依赖却都在近处（这个距离仍不超过 60，和基线训练时一样），模型会不会自己学会远处的检索？对直接外推和 YaRN 各做一次。
:::

<p class="nb-label">In [10]</p>

```python
plain = {m: [report(extend(bases[s], m, max_dist=60)) for s in SEEDS] for m in ("direct", "yarn")}
for m in ("direct", "yarn"):
    show(NAMES[m] + "+近距离", plain[m])
log["plain"] = plain
```

```text
直接外推+近距离       损失（位置 0-63 / 64-127 / 128-191 / 192-255） 4.437 4.388 4.354 4.395   检索准确率（距离 16/48/112/176/240） 1.00 1.00 0.81 0.95 0.90
YaRN+近距离       损失（位置 0-63 / 64-127 / 128-191 / 192-255） 4.523 4.460 4.429 4.457   检索准确率（距离 16/48/112/176/240） 1.00 1.00 1.00 0.98 0.97
```

::: v-pre
## 7. 训得更久

150 步之后，直接外推的损失最低、远距离检索却最差；YaRN 正好相反。从基线重新开始，把扩展训练加长到 450 步（学习率调度按 450 步重排），看差距会不会消失。
:::

<p class="nb-label">In [11]</p>

```python
longer = {m: [report(extend(bases[s], m, steps=450)) for s in SEEDS] for m in ("direct", "yarn")}
for m in ("direct", "yarn"):
    show(NAMES[m] + "+450 步", longer[m])
log["longer"] = longer
```

```text
直接外推+450 步     损失（位置 0-63 / 64-127 / 128-191 / 192-255） 4.386 4.327 4.290 4.316   检索准确率（距离 16/48/112/176/240） 1.00 1.00 1.00 1.00 1.00
YaRN+450 步     损失（位置 0-63 / 64-127 / 128-191 / 192-255） 4.417 4.345 4.315 4.340   检索准确率（距离 16/48/112/176/240） 1.00 1.00 1.00 1.00 1.00
```

::: v-pre
## 8. 代价：上下文长 4 倍，要多花多少

KV cache 随长度线性增长；注意力分数的计算量随长度平方增长（第 28、29 章）。下面先按公式算，再在本机量一次前向的时间。
:::

<p class="nb-label">In [12]</p>

```python
def kv_bytes(T, layers=cfg.n_layers, d=cfg.d_model, bytes_per=4):
    return 2 * layers * T * d * bytes_per                         # K 和 V，每层每个位置各 d 个数

def flops_per_token(T, layers=cfg.n_layers, d=cfg.d_model, V=cfg.vocab_size):
    hidden = 8 * d // 3
    dense = layers * (4 * d * d + 3 * d * hidden) + d * V         # 每个 token 的矩阵乘（乘加算 1 次）
    attn = layers * T * d                                         # 和前面 T 个位置算分数、加权求和（平均约 T/2 个，两步合计）
    return dense, attn

for T in (64, 256, 1024):
    dense, attn = flops_per_token(T)
    print(f"长度 {T:4}：KV cache {kv_bytes(T) / 1024:6.0f} KiB/条  每 token 计算量 稠密 {dense:,} + 注意力 {attn:,}（注意力占 {attn / (dense + attn):.0%}）")
model = with_rope(bases[0], "yarn", 1024)
model.eval()
with torch.no_grad():
    for T in (64, 256, 1024):
        x = val_ids[:T * (1024 // T)].view(-1, T)
        t0 = time.perf_counter()
        for _ in range(5):
            model(x)
        print(f"[计时，本机] 1024 个 token 切成长 {T:4} 的段，一次前向 {(time.perf_counter() - t0) / 5 * 1000:.1f} ms")
```

```text
长度   64：KV cache     64 KiB/条  每 token 计算量 稠密 163,584 + 注意力 8,192（注意力占 5%）
长度  256：KV cache    256 KiB/条  每 token 计算量 稠密 163,584 + 注意力 32,768（注意力占 17%）
长度 1024：KV cache   1024 KiB/条  每 token 计算量 稠密 163,584 + 注意力 131,072（注意力占 44%）
[计时，本机] 1024 个 token 切成长   64 的段，一次前向 2.3 ms
[计时，本机] 1024 个 token 切成长  256 的段，一次前向 3.2 ms
[计时，本机] 1024 个 token 切成长 1024 的段，一次前向 5.1 ms
```

<p class="nb-label">In [13]</p>

```python
with open("long_context_log.json", "w", encoding="utf-8") as f:
    json.dump({k: v for k, v in log.items()}, f, ensure_ascii=False)
print("已写出 long_context_log.json")
```

```text
已写出 long_context_log.json
```

