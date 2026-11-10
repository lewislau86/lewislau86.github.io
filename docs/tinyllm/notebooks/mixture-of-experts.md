---
title: "第 26 章：稀疏专家（MoE）（notebook 在线查看）"
search: false
editLink: false
prev: false
next: false
pageClass: tinyllm-course
---

<!-- 本页由 scripts/build-tinyllm-code.py 根据 notebook 自动生成，请勿手改。 -->

::: tip 这是 notebook 的只读预览
[返回教案](/tinyllm/mixture-of-experts) · [在 Colab 中运行](https://colab.research.google.com/github/lewislau86/lewislau86.github.io/blob/master/docs/public/tinyllm/notebooks/mixture-of-experts.ipynb) · <a href="/tinyllm/notebooks/mixture-of-experts.ipynb" download>下载 .ipynb</a> · <a href="/tinyllm/code/mixture-of-experts.py" download>下载 .py</a> · [在 GitHub 上查看](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/tinyllm/notebooks/mixture-of-experts.ipynb)

下面的代码和输出与 notebook 文件完全一致。想修改、运行，请用 Colab 打开或下载到本地。
:::

::: v-pre
# 第 26 章：稀疏专家（MoE）

配套教案：https://lewislau86.github.io/tinyllm/mixture-of-experts

从上到下运行即可（`python mixture-of-experts.py`），CPU 上约一分半（一共训练 21 个小模型）。需要安装 PyTorch 和 `tokenizers`。
这个文件是本章代码的唯一来源：教案中的代码片段由 `# region 名字` / `# endregion 名字`
标记的区域直接引用，notebook 也由它生成（scripts/build-tinyllm-code.py）。

把每个 Block 的前馈层换成 8 个专家和一个路由器，每个 token 只用其中 2 个。和三种稠密模型比较，看负载均衡和专家分工，
再把一个训练到一半的稠密模型“升级”成 MoE 接着训练，最后算真实模型的推理账。
:::

<p class="nb-label">In [1]</p>

```python
import copy
import json
import math
import time
from dataclasses import dataclass, replace

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

模型代码从第 12 章复制，尺寸是第 17 章的代理模型，训练用第 17 章的 WSD（峰值 1e-2）、240 步。
配置里多了几个开关：前馈层的中间宽度、专家个数、每个 token 选几个专家、怎样做负载均衡。默认值下和第 12 章的模型完全一样。
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
    ffn_hidden: int = 0        # 本章加的：前馈层中间宽度，0 表示 8d/3
    n_experts: int = 0         # 本章加的：专家个数，0 表示稠密前馈层
    top_k: int = 2             # 每个 token 选几个专家
    balance: str = "bias"      # 负载均衡："bias"（无辅助损失的偏置）、"aux"（辅助损失）、"none"

cfg = TinyConfig()

cfg = TinyConfig(vocab_size=1024, d_model=64, n_layers=2)       # 第 17 章的代理模型
STEPS, BATCH = 240, 16
print(cfg)
```

```text
TinyConfig(vocab_size=1024, d_model=64, n_layers=2, n_heads=4, context=64, rope_base=10000.0, ffn_hidden=0, n_experts=0, top_k=2, balance='bias')
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
        hidden = cfg.ffn_hidden or 8 * cfg.d_model // 3
        self.gate = nn.Linear(cfg.d_model, hidden, bias=False)
        self.up = nn.Linear(cfg.d_model, hidden, bias=False)
        self.down = nn.Linear(hidden, cfg.d_model, bias=False)        # 输出投影：写回残差流

    def forward(self, x):
        return self.down(F.silu(self.gate(x)) * self.up(x))

class MoE(nn.Module):
    """路由器给每个 token 打分，选分数最高的 top_k 个专家，按分数加权求和。"""
    def __init__(self, cfg):
        super().__init__()
        self.n, self.k, self.balance = cfg.n_experts, cfg.top_k, cfg.balance
        self.router = nn.Linear(cfg.d_model, cfg.n_experts, bias=False)
        self.experts = nn.ModuleList(SwiGLU(cfg) for _ in range(cfg.n_experts))   # 每个专家就是一个普通的前馈层
        self.register_buffer("bias", torch.zeros(cfg.n_experts))     # 无辅助损失的均衡：只影响“选谁”
        self.gamma = 0.005                                           # 偏置每步调整的幅度
        self.aux, self.load, self.choice = torch.zeros(()), None, None

    def forward(self, x):
        B, T, D = x.shape
        flat = x.reshape(-1, D)
        probs = F.softmax(self.router(flat), dim=-1)                 # (B·T, 专家数)
        chosen = (probs + self.bias if self.balance == "bias" else probs).topk(self.k, dim=-1).indices
        weights = probs.gather(-1, chosen)
        weights = weights / weights.sum(-1, keepdim=True)            # 选中的 k 个专家，权重和为 1
        out = torch.zeros_like(flat)
        for e, expert in enumerate(self.experts):
            token, slot = (chosen == e).nonzero(as_tuple=True)       # 哪些 token 选了第 e 个专家
            if len(token):
                out.index_add_(0, token, expert(flat[token]) * weights[token, slot, None])
        load = torch.zeros(self.n).index_add_(0, chosen.flatten(), torch.ones(chosen.numel())) / chosen.numel()
        self.aux = self.n * (load * probs.mean(0)).sum()             # Switch Transformer 的负载均衡损失
        self.load, self.choice = load, chosen[:, 0]
        if self.training and self.balance == "bias":
            with torch.no_grad():                                    # 忙的专家降偏置，闲的升偏置
                self.bias += self.gamma * torch.sign(1.0 / self.n - load)
        return out.view(B, T, D)

class Block(nn.Module):
    def __init__(self, cfg):
        super().__init__()
        self.norm1 = nn.RMSNorm(cfg.d_model)
        self.attn = CausalSelfAttention(cfg)
        self.norm2 = nn.RMSNorm(cfg.d_model)
        self.ffn = MoE(cfg) if cfg.n_experts else SwiGLU(cfg)          # 本章：稠密或 MoE

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
                for ffn in b.ffn.modules():                           # MoE 时每个专家的 down 都缩小
                    if isinstance(ffn, SwiGLU):
                        ffn.down.weight.mul_(scale)

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
## 1. 参数账：总参数与激活参数

本章的 MoE：每层 8 个专家，每个专家和主线的前馈层一样大（中间宽度 170），每个 token 选 2 个。
和三种稠密模型比：主线（中间宽度 170）、激活参数相同（340）、总参数相同（1360）。
:::

<p class="nb-label">In [6]</p>

```python
MOE = replace(cfg, n_experts=8, top_k=2)
CONFIGS = {
    "稠密（主线）": cfg,
    "稠密，激活参数相同": replace(cfg, ffn_hidden=340),
    "稠密，总参数相同": replace(cfg, ffn_hidden=1360),
    "MoE 8 选 2": MOE,
}

def count(c):
    model = TinyLLM(c)
    total = sum(p.numel() for p in model.parameters())
    if not c.n_experts:
        return total, total
    expert = sum(p.numel() for p in model.blocks[0].ffn.experts[0].parameters())
    idle = c.n_layers * (c.n_experts - c.top_k) * expert      # 每个 token 用不到的专家参数
    return total, total - idle

for name, c in CONFIGS.items():
    total, active = count(c)
    print(f"{name:<12} 总参数 {total:>7,}   每个 token 用到 {active:>7,}（{active / total:.0%}）")
```

```text
稠密（主线）       总参数 163,904   每个 token 用到 163,904（100%）
稠密，激活参数相同    总参数 229,184   每个 token 用到 229,184（100%）
稠密，总参数相同     总参数 620,864   每个 token 用到 620,864（100%）
MoE 8 选 2    总参数 621,888   每个 token 用到 230,208（37%）
```

::: v-pre
## 2. 训练函数
:::

<p class="nb-label">In [7]</p>

```python
plan = torch.Generator().manual_seed(1234)
starts = torch.randint(0, len(train_ids) - cfg.context - 1, (STEPS, BATCH), generator=plan)

def wsd(step, peak=1e-2, warmup=30, decay_frac=0.2):
    decay_from = STEPS - int(STEPS * decay_frac)
    if step < warmup:
        return peak * (step + 1) / warmup
    return peak if step < decay_from else peak * (STEPS - step) / (STEPS - decay_from)

def make_optimizer(model):
    decay = [p for p in model.parameters() if p.dim() >= 2]
    no_decay = [p for p in model.parameters() if p.dim() < 2]
    return torch.optim.AdamW([{"params": decay, "weight_decay": 0.1},
                              {"params": no_decay, "weight_decay": 0.0}], lr=1e-2)

def train(model, steps=range(STEPS), optimizer=None, aux=0.0):
    optimizer = optimizer or make_optimizer(model)
    model.train()
    for step in steps:
        for group in optimizer.param_groups:
            group["lr"] = wsd(step)
        idx = starts[step][:, None] + torch.arange(cfg.context + 1)
        _, loss = model(train_ids[idx[:, :-1]], train_ids[idx[:, 1:]])
        if aux:
            loss = loss + aux * sum(b.ffn.aux for b in model.blocks)   # 负载均衡的辅助损失
        optimizer.zero_grad(set_to_none=True)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        optimizer.step()
    return optimizer

def busiest(model):
    """最忙的那个专家拿走了多少比例的“选择”（理想是 1/8 = 12.5%）。"""
    return max(b.ffn.load.max().item() for b in model.blocks)
```

::: v-pre
## 3. 对照：MoE 和三种稠密模型

每种设置 3 个种子。MoE 用三种负载均衡方式：不均衡、辅助损失（系数 0.01）、无辅助损失的偏置。
:::

<p class="nb-label">In [8]</p>

```python
SEEDS = (0, 1, 2)
results, models = {}, {}
t0 = time.time()
for name, c in CONFIGS.items():
    if c.n_experts:
        continue
    results[name] = []
    for seed in SEEDS:
        torch.manual_seed(seed)
        model = TinyLLM(c)
        if name == "稠密（主线）":                                   # 第 120 步存一份，第 7 节的稀疏升级要用
            opt = train(model, steps=range(120))
            models[("稠密@120", seed)] = (copy.deepcopy(model), copy.deepcopy(opt))
            train(model, steps=range(120, STEPS), optimizer=opt)
        else:
            train(model)
        results[name].append(evaluate(model)[0])
for label, balance, aux in (("MoE，不均衡", "none", 0.0), ("MoE，辅助损失", "aux", 0.01), ("MoE，偏置均衡", "bias", 0.0)):
    results[label], results[label + "·最忙"] = [], []
    for seed in SEEDS:
        torch.manual_seed(seed)
        model = TinyLLM(replace(MOE, balance=balance))
        train(model, aux=aux)
        results[label].append(evaluate(model)[0])
        results[label + "·最忙"].append(busiest(model))
        models[(label, seed)] = model
print(f"一共 {len(SEEDS) * 6} 次训练，用时 {time.time() - t0:.0f} 秒")
for name, vals in results.items():
    if name.endswith("·最忙"):
        continue
    extra = f"   最忙的专家占 {'/'.join(f'{v:.0%}' for v in results[name + '·最忙'])}" if name + "·最忙" in results else ""
    print(f"{name:<12} 验证损失 {sum(vals) / 3:.3f}（{min(vals):.3f}～{max(vals):.3f}）{extra}")
```

```text
一共 18 次训练，用时 66 秒
稠密（主线）       验证损失 4.748（4.733～4.758）
稠密，激活参数相同    验证损失 4.697（4.681～4.721）
稠密，总参数相同     验证损失 4.701（4.676～4.742）
MoE，不均衡      验证损失 4.713（4.676～4.742）   最忙的专家占 43%/40%/44%
MoE，辅助损失     验证损失 4.702（4.683～4.713）   最忙的专家占 19%/18%/18%
MoE，偏置均衡     验证损失 4.721（4.717～4.728）   最忙的专家占 14%/14%/14%
```

::: v-pre
## 4. 专家分工：谁处理了什么

用偏置均衡的 MoE（种子 0），把验证集送进去，看每类 token 第一选择的是哪个专家：
:::

<p class="nb-label">In [9]</p>

```python
model = models[("MoE，偏置均衡", 0)].eval()
T = cfg.context
n = (len(val_ids) - 1) // T * T
xs = val_ids[:n].view(-1, T)
choices = {i: [] for i in range(cfg.n_layers)}
with torch.no_grad():
    for i in range(0, len(xs), 64):
        model(xs[i:i + 64])
        for layer, block in enumerate(model.blocks):
            choices[layer].append(block.ffn.choice)
tokens = xs.flatten()
comma, period = tokenizer.encode("，").ids[0], tokenizer.encode("。").ids[0]   # 字节级 BPE：用 encode 查编号（第 4 章）
classes = {"逗号": tokens == comma, "句号": tokens == period, "<eos>": tokens == EOS}
classes["其余（汉字）"] = ~(classes["逗号"] | classes["句号"] | classes["<eos>"])
routing = {}
for layer in range(cfg.n_layers):
    first = torch.cat(choices[layer])
    print(f"第 {layer} 层          " + "".join(f"{f'专家{e}':>7}" for e in range(8)))
    for name, mask in classes.items():
        share = torch.bincount(first[mask], minlength=8).float() / mask.sum()
        routing[f"{layer}|{name}"] = share.tolist()
        print(f"  {name:<10}{mask.sum().item():>6} 个 " + "".join(f"{v:7.0%}" for v in share.tolist()))
model.train()
```

```text
第 0 层              专家0    专家1    专家2    专家3    专家4    专家5    专家6    专家7
  逗号          1045 个      0%     0%   100%     0%     0%     0%     0%     0%
  句号          1044 个      0%     0%     0%     0%     0%     0%     0%   100%
  <eos>        290 个      0%     0%     0%     0%     0%     0%   100%     0%
  其余（汉字）     13493 个      7%    22%    10%    13%    17%     8%    10%    13%
第 1 层              专家0    专家1    专家2    专家3    专家4    专家5    专家6    专家7
  逗号          1045 个      0%     0%     0%     0%     0%     0%     0%   100%
  句号          1044 个      0%     0%     0%    21%     0%     0%     0%    79%
  <eos>        290 个      0%     0%     0%   100%     0%     0%     0%     0%
  其余（汉字）     13493 个     17%    16%    20%     4%    12%    10%    19%     1%
```

```text
TinyLLM(
  (embed): Embedding(1024, 64)
  (blocks): ModuleList(
    (0-1): 2 x Block(
      (norm1): RMSNorm((64,), eps=None, elementwise_affine=True)
      (attn): CausalSelfAttention(
        (qkv): Linear(in_features=64, out_features=192, bias=False)
        (proj): Linear(in_features=64, out_features=64, bias=False)
      )
      (norm2): RMSNorm((64,), eps=None, elementwise_affine=True)
      (ffn): MoE(
        (router): Linear(in_features=64, out_features=8, bias=False)
        (experts): ModuleList(
          (0-7): 8 x SwiGLU(
            (gate): Linear(in_features=64, out_features=170, bias=False)
            (up): Linear(in_features=64, out_features=170, bias=False)
            (down): Linear(in_features=170, out_features=64, bias=False)
          )
        )
      )
    )
  )
  (norm): RMSNorm((64,), eps=None, elementwise_affine=True)
)
```

::: v-pre
## 5. 稀疏升级：把训练到一半的稠密模型改成 MoE

第 3 节存下了主线稠密模型第 120 步的参数和优化器状态。把每层的前馈层复制成 8 个一模一样的专家，
新加一个路由器（随机初始化），优化器状态也照样复制，接着训练到第 240 步：
:::

<p class="nb-label">In [10]</p>

```python
def upcycle(dense, dense_opt):
    torch.manual_seed(100)
    moe = TinyLLM(MOE)
    source = dense.state_dict()
    state = {}
    def origin(name):                                        # MoE 的参数名 → 稠密模型里对应的参数名
        if ".ffn.experts." in name:
            layer, rest = name.split(".ffn.experts.")
            return layer + ".ffn." + rest.split(".", 1)[1]
        return name
    for name, value in moe.state_dict().items():
        state[name] = source[origin(name)].clone() if origin(name) in source else value
    moe.load_state_dict(state)
    with torch.no_grad():
        for block in moe.blocks:
            nn.init.normal_(block.ffn.router.weight, std=0.02)   # 路由器从“几乎均匀”开始
    optimizer = make_optimizer(moe)
    dense_params = dict(dense.named_parameters())
    for name, p in moe.named_parameters():                   # Adam 的 m、v 也复制给每个专家
        src = dense_params.get(origin(name))
        if src is not None and src in dense_opt.state:
            optimizer.state[p] = {k: v.clone() for k, v in dense_opt.state[src].items()}
    return moe, optimizer

x = val_ids[:cfg.context][None]
upcycled = {}
for seed in SEEDS:
    dense, dense_opt = models[("稠密@120", seed)]
    moe, opt = upcycle(dense, dense_opt)
    if seed == 0:
        with torch.no_grad():
            diff = (dense.eval()(x) - moe.eval()(x)).abs().max().item()
        print(f"升级前后，同一段输入的 logits 最大差 {diff:.1e}；验证损失 稠密 {evaluate(dense)[0]:.4f}，升级后 {evaluate(moe)[0]:.4f}")
    train(moe, steps=range(120, STEPS), optimizer=opt)
    upcycled[seed] = moe
up = [evaluate(m)[0] for m in upcycled.values()]
results["稀疏升级"] = up
print(f"继续训练到第 240 步：稀疏升级 {sum(up) / 3:.3f}（{min(up):.3f}～{max(up):.3f}）"
      f"   稠密（主线） {sum(results['稠密（主线）']) / 3:.3f}   从头训练的 MoE（偏置均衡） {sum(results['MoE，偏置均衡']) / 3:.3f}")

def expert_similarity(model):
    """同一层 8 个专家两两之间，down 权重的余弦相似度的平均。"""
    sims = []
    for block in model.blocks:
        w = [e.down.weight.flatten() for e in block.ffn.experts]
        sims += [F.cosine_similarity(w[i], w[j], dim=0).item() for i in range(8) for j in range(i + 1, 8)]
    return sum(sims) / len(sims)

print(f"专家之间的相似度：稀疏升级 {sum(expert_similarity(m) for m in upcycled.values()) / 3:.3f}，"
      f"从头训练 {sum(expert_similarity(models[('MoE，偏置均衡', s)]) for s in SEEDS) / 3:.3f}（1 表示完全相同，0 表示毫无关系）")
```

```text
升级前后，同一段输入的 logits 最大差 3.3e-06；验证损失 稠密 5.1219，升级后 5.1219
```

```text
继续训练到第 240 步：稀疏升级 4.742（4.737～4.751）   稠密（主线） 4.748   从头训练的 MoE（偏置均衡） 4.721
专家之间的相似度：稀疏升级 0.484，从头训练 -0.000（1 表示完全相同，0 表示毫无关系）
```

::: v-pre
## 6. 推理的账：真实模型

几个公开模型的总参数和激活参数（来自各自的技术报告或模型卡）。BF16 下每个参数 2 字节。
批量为 B 时，假设路由均匀、互相独立，一层里至少被一个 token 选中的专家比例约为 1 − (1 − k/E)^B。
:::

<p class="nb-label">In [11]</p>

```python
REAL = {   # 名字: (总参数, 激活参数, 每层专家数 E, 每个 token 选几个 k)
    "Qwen3-32B（稠密）": (32.8e9, 32.8e9, 1, 1),
    "Mixtral 8x7B": (46.7e9, 12.9e9, 8, 2),
    "Qwen3-30B-A3B": (30.5e9, 3.3e9, 128, 8),
    "MiMo-V2-Flash": (309e9, 15e9, 256, 8),
    "DeepSeek-V3": (671e9, 37e9, 256, 8),
}
print(f"{'':<18}{'权重(BF16)':>10}{'每 token 计算':>14}{'每 token 读权重':>14}")
for name, (total, active, E, k) in REAL.items():
    print(f"{name:<18}{total * 2 / 1e9:>8.0f} GB{2 * active / 1e9:>11.0f} GFLOP{active * 2 / 1e9:>11.1f} GB")
print("\n批量 B 时，一层里被用到的专家比例：")
coverage = {}
for name, (total, active, E, k) in REAL.items():
    if E == 1:
        continue
    coverage[name] = [1 - (1 - k / E) ** B for B in (1, 4, 16, 64, 256)]
    print(f"  {name:<16}" + "".join(f"  B={B:<3}{c:5.0%}" for B, c in zip((1, 4, 16, 64, 256), coverage[name])))
```

```text
                    权重(BF16)    每 token 计算   每 token 读权重
Qwen3-32B（稠密）           66 GB         66 GFLOP       65.6 GB
Mixtral 8x7B            93 GB         26 GFLOP       25.8 GB
Qwen3-30B-A3B           61 GB          7 GFLOP        6.6 GB
MiMo-V2-Flash          618 GB         30 GFLOP       30.0 GB
DeepSeek-V3           1342 GB         74 GFLOP       74.0 GB

批量 B 时，一层里被用到的专家比例：
  Mixtral 8x7B      B=1    25%  B=4    68%  B=16   99%  B=64  100%  B=256 100%
  Qwen3-30B-A3B     B=1     6%  B=4    23%  B=16   64%  B=64   98%  B=256 100%
  MiMo-V2-Flash     B=1     3%  B=4    12%  B=16   40%  B=64   87%  B=256 100%
  DeepSeek-V3       B=1     3%  B=4    12%  B=16   40%  B=64   87%  B=256 100%
```

<p class="nb-label">In [12]</p>

```python
moe_log = {
    "configs": {name: dict(zip(("total", "active"), count(c))) for name, c in CONFIGS.items()},
    "results": results, "routing": routing,
    "similarity": {"upcycled": sum(expert_similarity(m) for m in upcycled.values()) / 3,
                   "scratch": sum(expert_similarity(models[("MoE，偏置均衡", s)]) for s in SEEDS) / 3},
    "real": {k: list(v) for k, v in REAL.items()}, "coverage": coverage,
}
with open("mixture_of_experts_log.json", "w", encoding="utf-8") as f:
    json.dump(moe_log, f, ensure_ascii=False)
```

