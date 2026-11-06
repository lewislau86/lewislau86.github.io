---
title: "第 22 章：训练诊断与评估（notebook 在线查看）"
search: false
editLink: false
prev: false
next: false
pageClass: tinyllm-course
---

<!-- 本页由 scripts/build-tinyllm-code.py 根据 notebook 自动生成，请勿手改。 -->

::: tip 这是 notebook 的只读预览
[返回教案](/tinyllm/training-evaluation) · [在 Colab 中运行](https://colab.research.google.com/github/lewislau86/lewislau86.github.io/blob/master/docs/public/tinyllm/notebooks/training-evaluation.ipynb) · <a href="/tinyllm/notebooks/training-evaluation.ipynb" download>下载 .ipynb</a> · <a href="/tinyllm/code/training-evaluation.py" download>下载 .py</a> · [在 GitHub 上查看](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/tinyllm/notebooks/training-evaluation.ipynb)

下面的代码和输出与 notebook 文件完全一致。想修改、运行，请用 Colab 打开或下载到本地。
:::

::: v-pre
# 第 22 章：训练诊断与评估

配套教案：https://lewislau86.github.io/tinyllm/training-evaluation

从上到下运行即可（`python training-evaluation.py`），CPU 上约一分钟。需要安装 PyTorch 和 `tokenizers`。
这个文件是本章代码的唯一来源：教案中的代码片段由 `# region 名字` / `# endregion 名字`
标记的区域直接引用，notebook 也由它生成（scripts/build-tinyllm-code.py）。

损失曲线好看，不代表代码没有 bug。本章故意埋 6 个常见的 bug，用 6 项检查去抓；再看评估本身的误差有多大，
以及验证损失和生成质量是不是一回事。
:::

<p class="nb-label">In [1]</p>

```python
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

模型代码从第 12 章复制，尺寸是第 17 章的代理模型（词表 1024、宽度 64、2 层），训练用第 17 章的 WSD（峰值 1e-2）、240 步。
唯一的改动：注意力层多了一个 `causal` 开关，默认打开，和第 12 章完全一样；第 2 节要用它埋一个 bug。
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
STEPS, BATCH, PEAK_LR = 240, 16, 1e-2                           # 第 17 章的 WSD：峰值 1e-2
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
        self.causal = True                                            # 本章加的开关，默认和第 12 章一样
        self.qkv = nn.Linear(cfg.d_model, 3 * cfg.d_model, bias=False)
        self.proj = nn.Linear(cfg.d_model, cfg.d_model, bias=False)   # 输出投影：写回残差流

    def forward(self, x, cos, sin):
        B, T, D = x.shape
        q, k, v = (t.view(B, T, self.n_heads, D // self.n_heads).transpose(1, 2)
                   for t in self.qkv(x).split(D, dim=-1))
        y = F.scaled_dot_product_attention(apply_rope(q, cos, sin), apply_rope(k, cos, sin), v, is_causal=self.causal)
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
## 1. 六个常见的 bug

每个 bug 都是真实项目里常见的一行之差。`bug=None` 是正确的代码。
:::

<p class="nb-label">In [6]</p>

```python
BUGS = {
    None: "正确的代码",
    "漏了因果掩码": "注意力能看到后面的 token",
    "标签没错位": "目标用了 x 而不是 y",
    "双重 softmax": "把概率当成 logits 传给 cross_entropy",
    "忘了清梯度": "每步没有 zero_grad",
    "每步同一个 batch": "取 batch 时写成了第 0 行",
    "初始化放大 10 倍": "词嵌入的标准差多乘了 10",
}

def make_model(bug, seed=0):
    torch.manual_seed(seed)
    model = TinyLLM(cfg)
    if bug == "漏了因果掩码":
        for block in model.blocks:
            block.attn.causal = False
    if bug == "初始化放大 10 倍":
        with torch.no_grad():
            model.embed.weight.mul_(10)
    return model

def lm_loss(model, x, y, bug):
    logits = model(x)
    target = x if bug == "标签没错位" else y
    if bug == "双重 softmax":
        logits = F.softmax(logits, dim=-1)                    # 错：cross_entropy 自己会做 log_softmax
    return F.cross_entropy(logits.flatten(0, 1), target.flatten())
```

::: v-pre
训练和评估都用同一个 `lm_loss`：真实项目里，训练和评估通常共用一份损失函数，bug 也就一起共用了。
:::

<p class="nb-label">In [7]</p>

```python
plan = torch.Generator().manual_seed(1234)
starts = torch.randint(0, len(train_ids) - cfg.context - 1, (STEPS, BATCH), generator=plan)

def get_batch(step, bug=None):
    row = 0 if bug == "每步同一个 batch" else step              # 错：本该是 starts[step]
    idx = starts[row][:, None] + torch.arange(cfg.context + 1)
    return train_ids[idx[:, :-1]], train_ids[idx[:, 1:]]

def wsd(step, warmup=30, decay_frac=0.2):
    decay_steps = int(STEPS * decay_frac)
    if step < warmup:
        return PEAK_LR * (step + 1) / warmup
    return PEAK_LR if step < STEPS - decay_steps else PEAK_LR * (STEPS - step) / decay_steps

def train(bug, steps=STEPS, batches=None, lr_at=wsd, snapshot=()):
    model = make_model(bug)
    decay = [p for p in model.parameters() if p.dim() >= 2]
    no_decay = [p for p in model.parameters() if p.dim() < 2]
    optimizer = torch.optim.AdamW([{"params": decay, "weight_decay": 0.1},
                                   {"params": no_decay, "weight_decay": 0.0}], lr=lr_at(0))
    log = {"loss": [], "grad_norm": [], "snapshots": {}}
    for step in range(steps):
        for group in optimizer.param_groups:
            group["lr"] = lr_at(step)
        x, y = batches(step) if batches else get_batch(step, bug)
        if bug != "忘了清梯度":
            optimizer.zero_grad(set_to_none=True)
        loss = lm_loss(model, x, y, bug)
        loss.backward()
        log["grad_norm"].append(torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0).item())
        optimizer.step()
        log["loss"].append(loss.item())
        if step + 1 in snapshot:
            log["snapshots"][step + 1] = {k: v.clone() for k, v in model.state_dict().items()}
    return model, log

@torch.no_grad()
def val_loss(model, bug=None, T=cfg.context, batch=64):
    model.eval()
    n = (len(val_ids) - 1) // T * T
    xs, ys = val_ids[:n].view(-1, T), val_ids[1:n + 1].view(-1, T)
    total = sum(lm_loss(model, xs[i:i + batch], ys[i:i + batch], bug).item() * len(xs[i:i + batch])
                for i in range(0, len(xs), batch))
    model.train()
    return total / len(xs)
```

::: v-pre
## 2. 一条“好看”的曲线

正确的代码和“漏了因果掩码”各训练 240 步：
:::

<p class="nb-label">In [8]</p>

```python
t0 = time.time()
results = {}
for bug in (None, "漏了因果掩码"):
    model, log = train(bug, snapshot=(30, 60, 120, 180, 230, 240) if bug is None else ())
    results[bug] = {"model": model, "log": log, "val": val_loss(model, bug)}
    print(f"{bug or '正确的代码'}：最后 20 步训练损失 {sum(log['loss'][-20:]) / 20:.3f}  验证损失 {results[bug]['val']:.3f}")
print(f"每次训练约 {(time.time() - t0) / 2:.1f} 秒")
```

```text
正确的代码：最后 20 步训练损失 4.732  验证损失 4.733
```

```text
漏了因果掩码：最后 20 步训练损失 0.113  验证损失 0.111
每次训练约 2.6 秒
```

::: v-pre
让两个模型各写几行（从 `<eos>` 开始，温度 0.8，固定随机种子）：
:::

<p class="nb-label">In [9]</p>

```python
@torch.no_grad()
def sample(model, n=32, max_tokens=60, seed=0, prompt=""):
    model.eval()
    g = torch.Generator().manual_seed(seed)
    idx = torch.tensor([[EOS] + tokenizer.encode(prompt).ids] * n)
    for _ in range(max_tokens):
        logits = model(idx[:, -cfg.context:])[:, -1, :] / 0.8
        idx = torch.cat([idx, torch.multinomial(F.softmax(logits, dim=-1), 1, generator=g)], dim=1)
    model.train()
    poems = []
    for row in idx[:, 1:].tolist():
        row = row[:row.index(EOS)] if EOS in row else row             # 写到 <eos> 为止
        poems.append(tokenizer.decode(row))
    return poems

for bug in (None, "漏了因果掩码"):
    print((bug or "正确的代码") + "：")
    for poem in sample(results[bug]["model"], n=3):
        print("   ", poem[:36])
```

```text
正确的代码：
    别难松气，山雨物雪阳。苷长色户湿，潝忽直照山。欲笑首交筮，迷苦见又心。山
    儿寒雪相在，无为有乱斜。携尝谁见屈，西月代来春。
    长里年花，故酒遍衰归。不相见江草，国伴正湖难。平人不驰得，自正时飞游。离
漏了因果掩码：
    别别别别别别别别别别别别别别别别别别别别别别别别别别别别别别别别别别别别
    ������������������������������������
    野野野野野野野野野野野野野野野野野野野野野野野野野野野野野野野野野野野野
```

::: v-pre
## 3. 六项检查

每项检查都很便宜，都给出“通过 / 不通过”：
:::

<p class="nb-label">In [10]</p>

```python
LN_V = math.log(cfg.vocab_size)

def check_initial_loss(bug):
    """① 初始损失：随机初始化的模型应该接近均匀乱猜，ln V。"""
    x, y = get_batch(0)
    with torch.no_grad():
        loss = lm_loss(make_model(bug), x, y, bug).item()
    return loss, abs(loss - LN_V) < 1.0

def check_overfit_one_batch(bug):
    """② 单 batch 过拟合：反复训练同一个 batch 100 步，损失应该降到接近 0。"""
    _, log = train(bug, steps=100, batches=lambda step: get_batch(0), lr_at=lambda step: 3e-3)
    return log["loss"][-1], log["loss"][-1] < 0.5

def check_causality(bug, pos=40):
    """③ 因果性：改掉第 pos 个 token，它前面各位置的输出应该完全不变。"""
    model = make_model(bug).eval()
    x = get_batch(0)[0][:1]
    x2 = x.clone()
    x2[0, pos] = (x2[0, pos] + 1) % cfg.vocab_size
    with torch.no_grad():
        diff = (model(x)[0, :pos] - model(x2)[0, :pos]).abs().max().item()
    return diff, diff < 1e-6

def check_curves(log, val, initial):
    """④ 训练、验证曲线：验证损失比初始下降超过 1，并且和训练损失相差不到 0.5。"""
    gap = val - sum(log["loss"][-20:]) / 20
    return (val, gap), initial - val > 1.0 and abs(gap) < 0.5

def format_rate(poems):
    lines = [s for p in poems for s in re.split(r"[，。]", p) if s]
    return sum(len(s) == 5 for s in lines) / max(1, len(lines))

def check_samples(model):
    """⑤ 生成样例：按句号逗号切开，五个字的句子应该占一半以上。"""
    rate = format_rate(sample(model))
    return rate, rate >= 0.5

def check_grad_norm(log):
    """⑥ 梯度范数：中位数在 0.05～5 之间，最大值不超过 10。"""
    norms = sorted(log["grad_norm"])
    median, top = norms[len(norms) // 2], norms[-1]
    return (median, top), 0.05 <= median <= 5 and top <= 10
```

::: v-pre
## 4. 六个 bug × 六项检查
:::

<p class="nb-label">In [11]</p>

```python
matrix = {}
for bug in BUGS:
    if bug not in results:
        model, log = train(bug)
        results[bug] = {"model": model, "log": log, "val": val_loss(model, bug)}
    r = results[bug]
    init = check_initial_loss(bug)
    matrix[bug] = {"初始损失": init, "单 batch 过拟合": check_overfit_one_batch(bug), "因果性": check_causality(bug),
                   "训练/验证曲线": check_curves(r["log"], r["val"], init[0]), "生成样例": check_samples(r["model"]),
                   "梯度范数": check_grad_norm(r["log"])}

def pad(text, width):
    """按显示宽度补空格：汉字占两格。"""
    return text + " " * (width - sum(2 if ord(ch) > 0x2E80 else 1 for ch in text))

CHECKS = list(matrix[None])
print("  ".join(f"{n}{c}" for n, c in zip("①②③④⑤⑥", CHECKS)))
print(pad("", 18) + "  ".join("①②③④⑤⑥"))
for bug, row in matrix.items():
    print(pad(bug or "正确的代码", 18) + "  ".join("✓" if ok else "✗" for _, ok in row.values()))
```

```text
①初始损失  ②单 batch 过拟合  ③因果性  ④训练/验证曲线  ⑤生成样例  ⑥梯度范数
                  ①  ②  ③  ④  ⑤  ⑥
正确的代码        ✓  ✓  ✓  ✓  ✓  ✓
漏了因果掩码      ✓  ✓  ✗  ✓  ✗  ✓
标签没错位        ✗  ✓  ✓  ✓  ✗  ✗
双重 softmax      ✓  ✗  ✓  ✗  ✗  ✗
忘了清梯度        ✓  ✓  ✓  ✓  ✗  ✓
每步同一个 batch  ✓  ✓  ✓  ✗  ✗  ✗
初始化放大 10 倍  ✗  ✓  ✓  ✓  ✗  ✗
```

::: v-pre
每一格背后的数：
:::

<p class="nb-label">In [12]</p>

```python
def fmt(value):
    return "/".join(f"{v:.3g}" for v in value) if isinstance(value, tuple) else f"{value:.3g}"

print(f"ln V = {LN_V:.3f}")
for bug, row in matrix.items():
    print(pad(bug or "正确的代码", 18) + "  ".join(f"{n} {fmt(v)}" for n, (v, _) in zip("①②③④⑤⑥", row.values())))
```

```text
ln V = 6.931
正确的代码        ① 7.43  ② 0.0212  ③ 0  ④ 4.73/0.00187  ⑤ 0.82  ⑥ 0.52/2.03
漏了因果掩码      ① 7.43  ② 0.0144  ③ 0.577  ④ 0.111/-0.00196  ⑤ 0  ⑥ 0.329/3.22
标签没错位        ① 4.53  ② 0.00793  ③ 0  ④ 0.0027/0.00025  ⑤ 0  ⑥ 0.0039/3.17
双重 softmax      ① 6.93  ② 6.87  ③ 0  ④ 6.87/0.000729  ⑤ 0  ⑥ 6.88e-05/0.131
忘了清梯度        ① 7.43  ② 0.0661  ③ 0  ④ 5.66/-0.0201  ⑤ 0.043  ⑥ 1.24/2.1
每步同一个 batch  ① 7.43  ② 0.0212  ③ 0  ④ 8.65/8.64  ⑤ 0.0629  ⑥ 0.00598/1.57
初始化放大 10 倍  ① 77.9  ② 0.00767  ③ 0  ④ 5.35/-0.00577  ⑤ 0.206  ⑥ 0.641/23.8
```

::: v-pre
## 5. 验证损失本身有多准

验证集只有 291 首诗。换一批诗，验证损失会差多少？把每个 token 的损失按所在的诗分组，对诗做 bootstrap（有放回地重抽 291 首，算 1000 次）。
比较第 230 步和第 240 步的检查点：
:::

<p class="nb-label">In [13]</p>

```python
@torch.no_grad()
def poem_losses(state):
    """每首验证诗的 (损失总和, token 数)。"""
    model = TinyLLM(cfg)
    model.load_state_dict(state)
    model.eval()
    T = cfg.context
    n = (len(val_ids) - 1) // T * T
    xs, ys = val_ids[:n].view(-1, T), val_ids[1:n + 1].view(-1, T)
    losses, ys = F.cross_entropy(model(xs).flatten(0, 1), ys.flatten(), reduction="none"), ys.flatten()
    out, start = [], 0
    for end in (ys == EOS).nonzero().flatten().tolist():      # 每首诗以 <eos> 结束
        out.append((losses[start:end + 1].sum().item(), end + 1 - start))
        start = end + 1
    return out

def mean_loss(poems):
    return sum(s for s, _ in poems) / sum(n for _, n in poems)

snaps = results[None]["log"]["snapshots"]
a, b = poem_losses(snaps[230]), poem_losses(snaps[240])
rng = random.Random(0)
boot = {"第 230 步": [], "第 240 步": [], "差（230 − 240）": []}
for _ in range(1000):
    pick = [rng.randrange(len(a)) for _ in range(len(a))]          # 两个模型用同一批重抽的诗：配对
    ma, mb = mean_loss([a[i] for i in pick]), mean_loss([b[i] for i in pick])
    boot["第 230 步"].append(ma)
    boot["第 240 步"].append(mb)
    boot["差（230 − 240）"].append(ma - mb)

print(f"{len(a)} 首完整的验证诗")
for name, values in boot.items():
    v = sorted(values)
    point = {"第 230 步": mean_loss(a), "第 240 步": mean_loss(b)}.get(name, mean_loss(a) - mean_loss(b))
    print(f"{name:<12} {point:.4f}   95% 区间 {v[25]:.4f}～{v[974]:.4f}（宽 {v[974] - v[25]:.4f}）")
```

```text
290 首完整的验证诗
第 230 步      4.7509   95% 区间 4.7319～4.7693（宽 0.0374）
第 240 步      4.7333   95% 区间 4.7145～4.7516（宽 0.0370）
差（230 − 240） 0.0176   95% 区间 0.0149～0.0199（宽 0.0049）
```

::: v-pre
## 6. 损失和生成质量是一回事吗

同一次训练的几个检查点：验证损失、五字句占比、乱码（半个汉字，显示为 �）占比、和训练集完全相同的句子占比。
:::

<p class="nb-label">In [14]</p>

```python
train_lines = {s for p in train_poems for s in re.split(r"[，。]", p) if len(s) == 5}

def quality(state):
    model = TinyLLM(cfg)
    model.load_state_dict(state)
    poems = sample(model, n=64)
    lines = [s for p in poems for s in re.split(r"[，。]", p) if s]
    five = [s for s in lines if len(s) == 5]
    chars = "".join(poems)
    return {"val": mean_loss(poem_losses(state)), "五字句": len(five) / max(1, len(lines)),
            "乱码": chars.count("�") / max(1, len(chars)), "照抄训练集": sum(s in train_lines for s in five) / max(1, len(five))}

quality_log = {}
print("步数   验证损失   五字句   乱码   照抄训练集")
for step in (30, 60, 120, 180, 240):
    q = quality_log[step] = quality(snaps[step])
    print(f"{step:4d}   {q['val']:7.3f}   {q['五字句']:6.0%}   {q['乱码']:5.1%}   {q['照抄训练集']:6.1%}")
```

```text
步数   验证损失   五字句   乱码   照抄训练集
```

```text
  30     6.049       7%   32.3%     0.0%
```

```text
  60     5.558      21%    5.1%     0.0%
```

```text
 120     5.122      54%    1.8%     0.0%
```

```text
 180     4.888      59%    0.8%     0.0%
```

```text
 240     4.733      79%    0.4%     0.0%
```

::: v-pre
固定提示词“明月”，看看第 60、120、240 步各写出什么（同一个随机种子）：
:::

<p class="nb-label">In [15]</p>

```python
for step in (60, 120, 240):
    model = TinyLLM(cfg)
    model.load_state_dict(snaps[step])
    print(f"第 {step:3d} 步：", " | ".join(p[:24] for p in sample(model, n=2, prompt="明月", seed=1)))
```

```text
第  60 步： 明月笤。 | 明月花。
第 120 步： 明月笤。戦将名城酒，城后出声。雊�醉竹慆，清园人 | 明月，浃回尋似。人归多怜见，此倻抭行。
第 240 步： 明月笨。细涧名寸草，后出声动中。风天日竹急，独许 | 明月花落，风兴古似村。归多怜见宿，候膿古入。有寒
```

<p class="nb-label">In [16]</p>

```python
eval_log = {
    "steps": STEPS, "ln_v": LN_V,
    "curves": {str(bug): {"loss": r["log"]["loss"], "val": r["val"]} for bug, r in results.items()},
    "matrix": {str(bug): {c: {"value": v, "ok": ok} for c, (v, ok) in row.items()} for bug, row in matrix.items()},
    "bootstrap": boot, "points": {"230": mean_loss(a), "240": mean_loss(b)},
    "quality": quality_log,
}
with open("training_evaluation_log.json", "w", encoding="utf-8") as f:
    json.dump(eval_log, f, ensure_ascii=False)
```

