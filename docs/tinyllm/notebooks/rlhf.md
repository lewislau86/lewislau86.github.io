---
title: "第 41 章：RLHF：奖励模型与 PPO（notebook 在线查看）"
search: false
editLink: false
prev: false
next: false
pageClass: tinyllm-course
---

<!-- 本页由 scripts/build-tinyllm-code.py 根据 notebook 自动生成，请勿手改。 -->

::: tip 这是 notebook 的只读预览
[返回教案](/tinyllm/rlhf) · [在 Colab 中运行](https://colab.research.google.com/github/lewislau86/lewislau86.github.io/blob/master/docs/public/tinyllm/notebooks/rlhf.ipynb) · <a href="/tinyllm/notebooks/rlhf.ipynb" download>下载 .ipynb</a> · <a href="/tinyllm/code/rlhf.py" download>下载 .py</a> · [在 GitHub 上查看](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/tinyllm/notebooks/rlhf.ipynb)

下面的代码和输出与 notebook 文件完全一致。想修改、运行，请用 Colab 打开或下载到本地。
:::

::: v-pre
# 第 41 章：RLHF：奖励模型与 PPO

配套教案：https://lewislau86.github.io/tinyllm/rlhf

从上到下运行即可（`python rlhf.py`），CPU 约两分钟。需要安装 PyTorch 和 `tokenizers`。
这个文件是本章代码的唯一来源：教案中的代码片段由 `# region 名字` / `# endregion 名字`
标记的区域直接引用，notebook 也由它生成（scripts/build-tinyllm-code.py）。

从第 38 章的 SFT 模型出发，完整走一遍 RLHF：用一个看不见的“评审”造出成对的偏好数据，训练奖励模型，
再用 PPO 加 KL 约束优化策略；比较有没有 KL 约束时，奖励模型的分和评审的分怎样分道扬镳。
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
## 1. 数据：预训练用的诗，SFT 用的“指令—回答”

统一语料的前 6000 首用来预训练基座（按 `split` 分训练和验证），第 6001～12000 首的训练集用来造 SFT 数据，
同一段里的验证集、测试集诗用来造评估用的指令。三份数据没有重叠。分词器只用预训练的诗训练。
:::

<p class="nb-label">In [5]</p>

```python
poems = load_poems(12000)
pre_train = [p["text"] for p in poems[:6000] if p["split"] == "train"]
pre_val = [p["text"] for p in poems[:6000] if p["split"] == "val"]
sft_poems = [p["text"] for p in poems[6000:] if p["split"] == "train"]
eval_poems = [p["text"] for p in poems[6000:] if p["split"] != "train"]
tokenizer = train_tokenizer(pre_train, cfg.vocab_size)
PAD, EOS, USER, ASSISTANT = (tokenizer.token_to_id(t) for t in ("<pad>", "<eos>", "<user>", "<assistant>"))

def to_stream(texts):
    ids = []
    for t in texts:
        ids += tokenizer.encode(t).ids + [EOS]
    return torch.tensor(ids)

P_train, P_val = to_stream(pre_train), to_stream(pre_val)
print(f"预训练：{len(pre_train)} 首 {len(P_train):,} 个 token；SFT 素材 {len(sft_poems)} 首；评估素材 {len(eval_poems)} 首")
```

```text
预训练：5419 首 296,428 个 token；SFT 素材 5429 首；评估素材 571 首
```

<p class="nb-label">In [6]</p>

```python
def lines_of(poem):
    return [s for s in re.split("[，。]", poem) if s]

def make_instruction(poem, rng):
    """从一首诗反推一条它满足的指令：体裁总要说，六成再要求第一个字。"""
    kind = "绝句" if len(lines_of(poem)) == 4 else "律诗"
    if rng.random() < 0.4:
        return f"写一首五言{kind}。"
    return f"写一首五言{kind}，用“{poem[0]}”字开头。"

def check(instruction, answer, stopped):
    """程序判分：每句五字、句数对、首字对（有要求时）、按时停下（生成了 <eos>）。"""
    kind = 4 if "绝句" in instruction else 8
    first = re.search("[用以]“(.)”字开头", instruction)
    five = re.fullmatch(r"([一-鿿]{5}，[一-鿿]{5}。)+", answer) is not None
    count = five and len(lines_of(answer)) == kind
    first_ok = None if first is None else answer[:1] == first.group(1)
    return {"five": five, "count": count, "first": first_ok, "stop": stopped,
            "all": five and count and first_ok is not False and stopped}

def encode_chat(instruction, answer=None):
    """对话模板：<user>指令<assistant>回答<eos>。返回 token 和 loss 掩码（只有回答和 <eos> 是 1）。"""
    prompt = [USER] + tokenizer.encode(instruction).ids + [ASSISTANT]
    if answer is None:
        return prompt
    reply = tokenizer.encode(answer).ids + [EOS]
    return prompt + reply, [0] * len(prompt) + [1] * len(reply)

rng = random.Random(38)
sft_data = [(make_instruction(p, rng), p) for p in sft_poems]
eval_prompts = [make_instruction(p, random.Random(i)) for i, p in enumerate(eval_poems[:64])]
```

::: v-pre
## 2. 预训练基座

第 17 章的 WSD：warmup 30 步、峰值 1e-2、最后 20% 线性降到 0，共 2000 步；每步 8 行、每行 128 个 token（和第 17 章每步 16 行 × 64 个 token 的量相同）。
:::

<p class="nb-label">In [7]</p>

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

def sft(base, data, steps=1500, batch=16, peak=3e-3, answer_only=True, seed=0, eos=True, checkpoints=()):
    """监督微调：从基座复制一份，每步随机取 batch 条指令—回答，右侧补 <pad>，只在掩码为 1 的位置算交叉熵。"""
    model = copy.deepcopy(base)
    optimizer = make_optimizer(model, peak)
    plan = torch.Generator().manual_seed(seed)
    encoded = [encode_chat(i, a) for i, a in data]
    if not eos:                                                    # 第 5 节的对照：训练时去掉回答末尾的 <eos>
        encoded = [(ids[:-1], mask[:-1]) for ids, mask in encoded]
    saved = {}
    for i in range(steps):
        pick = torch.randint(0, len(encoded), (batch,), generator=plan).tolist()
        L = max(len(encoded[k][0]) for k in pick)
        x, w = torch.full((batch, L), PAD), torch.zeros(batch, L)
        for r, k in enumerate(pick):
            ids, mask = encoded[k]
            x[r, :len(ids)] = torch.tensor(ids)
            w[r, :len(ids)] = torch.tensor(mask if answer_only else [1] * len(ids))
        logits = model(x[:, :-1])
        lp = F.cross_entropy(logits.transpose(1, 2), x[:, 1:], reduction="none")
        loss = (lp * w[:, 1:]).sum() / w[:, 1:].sum()
        lr = peak * (i + 1) / 10 if i < 10 else peak * (steps - i) / (steps - 10)
        step(model, optimizer, loss, lr)
        if i + 1 in checkpoints:
            saved[i + 1] = copy.deepcopy(model)
    return (model, saved) if checkpoints else model

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

def evaluate(model, prompts=None, seed=7, template=encode_chat):
    """每条指令采样一个回答，按 check 判分，返回各项合格率。"""
    prompts = eval_prompts if prompts is None else prompts
    g = torch.Generator().manual_seed(seed)
    rows = []
    for p in prompts:
        _, answer, stopped = sample(model, template(p), 1, g)[0]
        rows.append(check(p, answer, stopped))
    rate = lambda key: sum(r[key] for r in rows if r[key] is not None) / max(1, sum(r[key] is not None for r in rows))
    return {k: rate(k) for k in ("five", "count", "first", "stop", "all")}
```

<p class="nb-label">In [8]</p>

```python
t0 = time.perf_counter()
base = pretrain()
sft_model = sft(base, sft_data)
print(f"[计时，本机] 预训练 2000 步 + SFT 1500 步（第 38 章种子 0），共 {time.perf_counter() - t0:.1f} 秒")
```

```text
[计时，本机] 预训练 2000 步 + SFT 1500 步（第 38 章种子 0），共 39.8 秒
```

::: v-pre
## 3. 一个看不见的“评审”

真实的 RLHF 请人比较两个回答。这里用一个程序代替人，但训练时**不直接用它**，只用它给出的“二选一”：
格式不对（句数、每句五字、按时停下）记 0 分；格式对记 1 分，诗里每出现一个不同的意象字（月风花山水云雪春秋夜）加 1 分，最多加 3 分；
同一个字出现 3 次以上（堆砌）扣 2 分。这个评审只用来造偏好数据和最后评估，训练过程只能通过偏好数据间接了解它。
:::

<p class="nb-label">In [9]</p>

```python
IMAGERY = set("月风花山水云雪春秋夜")

def judge(instruction, answer, stopped):
    c = check(instruction, answer, stopped)
    if not (c["count"] and c["stop"]):
        return 0
    images = len(IMAGERY & set(answer))
    most = max(answer.count(ch) for ch in set(answer) - set("，。"))
    return 1 + min(images, 3) - (2 if most >= 3 else 0)

jue_poems = [p for p in sft_poems if len(lines_of(p)) == 4]
prompts = [make_instruction(p, random.Random(i)) for i, p in enumerate(jue_poems)]
eval_jue = [make_instruction(p, random.Random(i)) for i, p in enumerate(q for q in eval_poems if len(lines_of(q)) == 4)][:64]
```

::: v-pre
## 4. 偏好数据：同一条指令的两个回答，评审选一个

用 SFT 模型对 60 条绝句指令各采样 64 个回答（温度 1.0），随机两两配对；评审打分相同的对子丢掉，其余高分的为“选中”、低分的为“落选”，
再把 10% 的对子标反，模拟人的不一致。
:::

<p class="nb-label">In [10]</p>

```python
t0 = time.perf_counter()
g, rng = torch.Generator().manual_seed(41), random.Random(41)
pairs = []
for p in prompts[:60]:
    outs = sample(sft_model, encode_chat(p), 64, g, temperature=1.0, max_new=60)
    scored = [(judge(p, a, s), row) for row, a, s in outs]
    rng.shuffle(scored)
    for (s1, r1), (s2, r2) in zip(scored[0::2], scored[1::2]):
        if s1 == s2:
            continue
        good, bad = (r1, r2) if s1 > s2 else (r2, r1)
        flipped = rng.random() < 0.1
        pairs.append({"prompt": p, "chosen": bad if flipped else good, "rejected": good if flipped else bad, "flipped": flipped})
train_pairs, test_pairs = pairs[:int(0.8 * len(pairs))], pairs[int(0.8 * len(pairs)):]
print(f"[计时，本机] {time.perf_counter() - t0:.1f} 秒；得到 {len(pairs)} 对（训练 {len(train_pairs)}、留出 {len(test_pairs)}），其中 {sum(x['flipped'] for x in pairs)} 对标反了")
```

```text
[计时，本机] 14.8 秒；得到 1434 对（训练 1147、留出 287），其中 132 对标反了
```

::: v-pre
## 5. 奖励模型：从二选一学出打分

奖励模型就是 SFT 模型去掉输出层、换上一个输出标量的头，读最后一个 token（`<eos>`）位置的隐藏状态。
损失是 Bradley–Terry：$-\log\sigma(r(\text{选中}) - r(\text{落选}))$，只要求选中的分数比落选的高。
:::

<p class="nb-label">In [11]</p>

```python
def hidden(model, x):
    h = model.embed(x)
    for block in model.blocks:
        h = block(h, model.cos, model.sin)
    return model.norm(h)

class RewardModel(nn.Module):
    def __init__(self, lm):
        super().__init__()
        self.lm = copy.deepcopy(lm)
        self.head = nn.Linear(cfg.d_model, 1)

    def forward(self, x, lengths):
        h = hidden(self.lm, x)
        return self.head(h[torch.arange(len(x)), lengths - 1]).squeeze(-1)   # 最后一个 token 的隐藏状态 → 标量

def response_ids(row):
    return row[:row.index(EOS) + 1] if EOS in row else [t for t in row if t != PAD]

def pad_batch(seqs):
    x = torch.full((len(seqs), max(len(s) for s in seqs)), PAD)
    for i, s in enumerate(seqs):
        x[i, :len(s)] = torch.tensor(s)
    return x, torch.tensor([len(s) for s in seqs])

def pair_batch(batch):
    chosen = pad_batch([encode_chat(b["prompt"]) + response_ids(b["chosen"]) for b in batch])
    rejected = pad_batch([encode_chat(b["prompt"]) + response_ids(b["rejected"]) for b in batch])
    return chosen, rejected

def train_reward_model(steps=600, batch=16, lr=1e-3):
    rm = RewardModel(sft_model)
    optimizer = torch.optim.AdamW(rm.parameters(), lr=lr, weight_decay=0.0)
    plan = torch.Generator().manual_seed(0)
    for i in range(steps):
        pick = torch.randint(0, len(train_pairs), (batch,), generator=plan).tolist()
        (xc, lc), (xr, lr_) = pair_batch([train_pairs[k] for k in pick])
        loss = -F.logsigmoid(rm(xc, lc) - rm(xr, lr_)).mean()
        optimizer.zero_grad()
        loss.backward()
        optimizer.step()
    return rm

t0 = time.perf_counter()
rm = train_reward_model()
with torch.no_grad():
    (xc, lc), (xr, lr_) = pair_batch(test_pairs)
    margin = rm(xc, lc) - rm(xr, lr_)
flipped = torch.tensor([b["flipped"] for b in test_pairs])
print(f"[计时，本机] 奖励模型 600 步 {time.perf_counter() - t0:.1f} 秒")
print(f"留出的 {len(test_pairs)} 对：和标签一致 {(margin > 0).float().mean():.0%}，和评审的真实判断一致 {((margin > 0) != flipped).float().mean():.0%}")
```

```text
[计时，本机] 奖励模型 600 步 7.4 秒
留出的 287 对：和标签一致 62%，和评审的真实判断一致 65%
```

::: v-pre
## 6. PPO：用奖励模型打分，用 KL 拴住

四个模型：策略（从 SFT 复制，要训练）、参考（SFT 本身，冻住）、奖励模型（冻住）、价值模型（从奖励模型复制，要训练）。
每一步：8 条指令各采样 4 个回答；每个回答 token 的奖励是 $-\beta(\log\pi - \log\pi_\text{ref})$，最后一个 token 再加上奖励模型的分数；
价值模型估计每个位置之后还能拿多少奖励，用 GAE 算出优势；然后按 PPO 的裁剪目标更新策略 2 轮，价值模型同时回归回报。
:::

<p class="nb-label">In [12]</p>

```python
def token_logprobs(model, x):
    """每个位置下一个 token 的对数概率，形状 (B, L-1)。"""
    return F.log_softmax(model(x[:, :-1]), dim=-1).gather(-1, x[:, 1:, None]).squeeze(-1)

class ValueModel(nn.Module):
    def __init__(self, rm):
        super().__init__()
        self.lm, self.head = copy.deepcopy(rm.lm), copy.deepcopy(rm.head)

    def forward(self, x):
        return self.head(hidden(self.lm, x)).squeeze(-1)

def rollout(policy, batch_prompts, k, g):
    seqs, starts, texts = [], [], []
    for p in batch_prompts:
        prompt = encode_chat(p)
        for row, answer, stopped in sample(policy, prompt, k, g, temperature=1.0, max_new=60):
            seqs.append(prompt + response_ids(row))
            starts.append(len(prompt))
            texts.append((p, answer, stopped))
    x, lengths = pad_batch(seqs)
    mask = torch.zeros(len(seqs), x.shape[1] - 1)
    for i, (s, n) in enumerate(zip(starts, lengths.tolist())):
        mask[i, s - 1:n - 1] = 1                      # 只有预测回答 token 的位置参与
    return x, lengths, mask, texts

def ppo(start, rm, beta=0.05, steps=100, n_prompts=8, k=4, lr=1e-3, epochs=2, clip=0.2, seed=0):
    policy, ref, value = copy.deepcopy(start), start, ValueModel(rm)
    opt_p = torch.optim.AdamW(policy.parameters(), lr=lr, weight_decay=0.0)
    opt_v = torch.optim.AdamW(value.parameters(), lr=lr, weight_decay=0.0)
    g, rng, history = torch.Generator().manual_seed(seed), random.Random(seed), []
    for step_i in range(steps):
        x, lengths, mask, texts = rollout(policy, rng.sample(prompts, n_prompts), k, g)
        with torch.no_grad():
            old, ref_lp = token_logprobs(policy, x), token_logprobs(ref, x)
            values, score = value(x)[:, :-1], rm(x, lengths)
            kl = (old - ref_lp) * mask
            reward = -beta * kl
            reward[torch.arange(len(x)), lengths - 2] += score          # 奖励模型的分数加在最后一个 token 上
            adv, running = torch.zeros_like(reward), torch.zeros(len(x))
            for t in reversed(range(reward.shape[1])):                  # GAE：γ = 1，λ = 0.95
                nxt = values[:, t + 1] * mask[:, t + 1] if t + 1 < reward.shape[1] else torch.zeros(len(x))
                running = (reward[:, t] + nxt - values[:, t] + 0.95 * running) * mask[:, t]
                adv[:, t] = running
            returns = adv + values
            sel = adv[mask > 0]
            adv = (adv - sel.mean()) / (sel.std() + 1e-8) * mask
        for _ in range(epochs):
            ratio = torch.exp(token_logprobs(policy, x) - old)
            loss_p = (-torch.min(ratio * adv, ratio.clamp(1 - clip, 1 + clip) * adv) * mask).sum() / mask.sum()
            opt_p.zero_grad(); loss_p.backward(); torch.nn.utils.clip_grad_norm_(policy.parameters(), 1.0); opt_p.step()
            loss_v = (((value(x)[:, :-1] - returns) ** 2) * mask).sum() / mask.sum()
            opt_v.zero_grad(); loss_v.backward(); torch.nn.utils.clip_grad_norm_(value.parameters(), 1.0); opt_v.step()
        history.append({"rm": score.mean().item(), "judge": sum(judge(*t) for t in texts) / len(texts), "kl": kl.sum(1).mean().item()})
    return policy, history
```

::: v-pre
## 7. 两次 PPO：有 KL 约束（β = 0.05）和没有（β = 0）

每次 100 步。每 20 步打印一次训练中采样到的回答的平均分：奖励模型的分、评审的分、和 SFT 模型的 KL。
:::

<p class="nb-label">In [13]</p>

```python
t0 = time.perf_counter()
runs = {beta: ppo(sft_model, rm, beta=beta) for beta in (0.05, 0.0)}
print(f"[计时，本机] 两次 PPO 各 100 步，共 {time.perf_counter() - t0:.1f} 秒")
for beta, (_, hist) in runs.items():
    for s in range(20, 101, 20):
        h = hist[s - 20:s]
        print(f"β={beta:<4} 第 {s:3} 步  奖励模型 {sum(x['rm'] for x in h) / 20:5.2f}  评审 {sum(x['judge'] for x in h) / 20:4.2f}  KL {sum(x['kl'] for x in h) / 20:5.1f}")
log["history"] = {str(b): h for b, (_, h) in runs.items()}
```

```text
[计时，本机] 两次 PPO 各 100 步，共 54.1 秒
β=0.05 第  20 步  奖励模型  4.56  评审 1.79  KL   9.9
β=0.05 第  40 步  奖励模型  9.41  评审 1.90  KL  25.5
β=0.05 第  60 步  奖励模型  9.83  评审 2.11  KL  24.2
β=0.05 第  80 步  奖励模型  9.86  评审 2.40  KL  22.0
β=0.05 第 100 步  奖励模型  9.79  评审 2.51  KL  21.5
β=0.0  第  20 步  奖励模型  4.67  评审 0.77  KL  18.2
β=0.0  第  40 步  奖励模型  9.80  评审 0.00  KL  82.2
β=0.0  第  60 步  奖励模型 10.20  评审 0.00  KL  96.9
β=0.0  第  80 步  奖励模型 10.40  评审 0.00  KL 147.2
β=0.0  第 100 步  奖励模型 10.48  评审 0.00  KL 167.3
```

::: v-pre
## 8. 评估：64 条没见过的绝句指令

每条指令采样一个回答（温度 0.8），看评审的平均分、奖励模型的平均分、意象字的个数、堆砌（同一个字出现 3 次以上）的比例、首字对，以及和 SFT 的 KL。
:::

<p class="nb-label">In [14]</p>

```python
@torch.no_grad()
def report(model, seed=7):
    g, rows = torch.Generator().manual_seed(seed), []
    for p in eval_jue:
        prompt = encode_chat(p)
        row, answer, stopped = sample(model, prompt, 1, g)[0]
        x, n = pad_batch([prompt + response_ids(row)])
        kl = (token_logprobs(model, x) - token_logprobs(sft_model, x))[0, len(prompt) - 1:].sum().item()
        most = max([answer.count(ch) for ch in set(answer) - set("，。")] or [0])
        c = check(p, answer, stopped)
        rows.append({"judge": judge(p, answer, stopped), "rm": rm(x, n).item(), "images": len(IMAGERY & set(answer)),
                     "stuffed": most >= 3, "first": c["first"], "kl": kl})
    mean = lambda k: sum(r[k] for r in rows if r[k] is not None) / max(1, sum(r[k] is not None for r in rows))
    return {k: mean(k) for k in ("judge", "rm", "images", "stuffed", "first", "kl")}

results = {"SFT": report(sft_model), "PPO β=0.05": report(runs[0.05][0]), "PPO β=0": report(runs[0.0][0])}
for name, r in results.items():
    print(f"{name:11} 评审 {r['judge']:.2f}  奖励模型 {r['rm']:5.2f}  意象字 {r['images']:.2f}  堆砌 {r['stuffed']:.0%}  首字对 {r['first']:.2f}  KL {r['kl']:5.1f}")
for name in ("PPO β=0.05", "PPO β=0"):
    g = torch.Generator().manual_seed(3)
    for p in eval_jue[:2]:
        print(f"{name}：{p} → {sample(runs[0.05 if '0.05' in name else 0.0][0], encode_chat(p), 1, g)[0][1]}")
log["results"] = results
```

```text
SFT         评审 1.67  奖励模型  1.07  意象字 0.86  堆砌 2%  首字对 0.42  KL   0.0
PPO β=0.05  评审 2.53  奖励模型 10.19  意象字 3.59  堆砌 64%  首字对 0.13  KL  29.4
PPO β=0     评审 0.00  奖励模型 10.50  意象字 2.02  堆砌 100%  首字对 0.00  KL 174.0
PPO β=0.05：写一首五言绝句，用“桂”字开头。 → 带月疑春去，春山云去国。白发心花去，春山花正远。
PPO β=0.05：写一首五言绝句。 → 公吽新山处，南花尽几时。路看春去去，春风春笑多。
PPO β=0：写一首五言绝句，用“桂”字开头。 → 花山暮暮暮暮，空暮暮暮暮暮。山山空暮暮暮暮，空山暮暮暮暮。
PPO β=0：写一首五言绝句。 → 花山暮暮暮暮，时暮暮暮暮暮。山山山暮暮暮暮，深空空暮暮暮。
```

<p class="nb-label">In [15]</p>

```python
with open("rlhf_log.json", "w", encoding="utf-8") as f:
    json.dump(log, f, ensure_ascii=False)
print("已写出 rlhf_log.json")
```

```text
已写出 rlhf_log.json
```

