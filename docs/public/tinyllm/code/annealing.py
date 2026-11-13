# %% [markdown]
# # 第 35 章：退火与数据配比
#
# 配套教案：https://lewislau86.github.io/tinyllm/annealing
#
# 从上到下运行即可（`python annealing.py`），CPU 上约一分半（3 个种子的稳定段，加上六七十段短的衰减）。需要安装 PyTorch 和 `tokenizers`。
# 这个文件是本章代码的唯一来源：教案中的代码片段由 `# region 名字` / `# endregion 名字`
# 标记的区域直接引用，notebook 也由它生成（scripts/build-tinyllm-code.py）。
#
# 本章用第 17 章的代理模型和 WSD 学习率：稳定段只训一次、沿途存检查点，再从检查点分叉出不同的衰减段，
# 比较衰减段里换上多少“高质量数据”、衰减多长、从哪个检查点分叉。
# 结论性的对比都用 3 个种子（只决定初始参数），batch 计划由单独的随机数生成器排好，报告平均和范围。

# %%
# region imports
import copy
import json
import math
import time
from dataclasses import dataclass

import torch
from torch import nn
from torch.nn import functional as F
from tokenizers import Tokenizer, decoders, models, pre_tokenizers, trainers
# endregion imports

print("PyTorch", torch.__version__)
log = {}

# region corpus
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
# endregion corpus

# %% [markdown]
# ## 0. 第 17 章的代理模型
#
# 模型代码从第 12 章原样复制，尺寸用第 17 章的代理模型：词表 1024、宽度 64、2 层，batch 16、上下文 64。
# 这一章要训练六七十段，原尺寸太慢；损失的绝对值只在本章内部比较。

# %%
# region config
@dataclass
class TinyConfig:
    vocab_size: int = 4096     # BPE 词表大小（含 4 个特殊 token）
    d_model: int = 128         # 每个 token 向量的宽度 d
    n_layers: int = 4          # Block 层数 L
    n_heads: int = 4           # 注意力头数，每头 d / n_heads = 32 维
    context: int = 64          # 一次最多看多少个 token
    rope_base: float = 10000.0

cfg = TinyConfig()
# endregion config

# region proxy
cfg = TinyConfig(vocab_size=1024, d_model=64, n_layers=2)       # 第 17 章的代理模型
BATCH = 16
# endregion proxy
print(cfg)

# %%
# region tokenizer
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

# endregion tokenizer

# %%
# region rope
def rope_tables(context, head_dim, base):
    theta = base ** (-torch.arange(0, head_dim, 2).float() / head_dim)
    angle = torch.arange(context).float()[:, None] * theta        # (T, head_dim/2)
    return angle.cos(), angle.sin()

def apply_rope(x, cos, sin):                                      # x: (B, 头数, T, head_dim)
    T = x.shape[-2]
    cos, sin = cos[:T], sin[:T]
    x1, x2 = x[..., 0::2], x[..., 1::2]
    return torch.stack([x1 * cos - x2 * sin, x1 * sin + x2 * cos], dim=-1).flatten(-2)
# endregion rope

# region attention
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
# endregion attention

# region swiglu
class SwiGLU(nn.Module):
    def __init__(self, cfg):
        super().__init__()
        hidden = 8 * cfg.d_model // 3
        self.gate = nn.Linear(cfg.d_model, hidden, bias=False)
        self.up = nn.Linear(cfg.d_model, hidden, bias=False)
        self.down = nn.Linear(hidden, cfg.d_model, bias=False)        # 输出投影：写回残差流

    def forward(self, x):
        return self.down(F.silu(self.gate(x)) * self.up(x))
# endregion swiglu

# region block
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
# endregion block

# region model
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
# endregion model


# %% [markdown]
# ## 1. 两份数据：大量的普通诗，一小份“高质量”诗
#
# 统一语料的前 138 首是第 1 章的 39 首加《唐诗三百首》的 99 首，都是人挑过的名篇，这里把它们当作“高质量数据”。
# 用一个单独的随机数生成器从中固定留出 38 首做高质量验证集，其余 100 首是高质量训练集。
# 普通数据是第 139～6000 首（全部来自《全唐诗》，随机打乱），按语料的 `split` 分训练和验证。
# 分词器只用普通训练集训练，高质量的诗（尤其是验证的 38 首）不参与。

# %%
# region data
poems = load_poems(6000)
hq = [p["text"] for p in poems[:138]]
perm = torch.randperm(len(hq), generator=torch.Generator().manual_seed(35)).tolist()
hq_val = [hq[i] for i in sorted(perm[:38])]                    # 高质量验证集：训练时一次也不用
hq_train = [hq[i] for i in sorted(perm[38:])]                  # 高质量训练集：只在退火段用
gen_train = [p["text"] for p in poems[138:] if p["split"] == "train"]
gen_val = [p["text"] for p in poems[138:] if p["split"] == "val"]

tokenizer = train_tokenizer(gen_train, cfg.vocab_size)
EOS = tokenizer.token_to_id("<eos>")

def to_stream(texts):
    ids = []
    for t in texts:
        ids += tokenizer.encode(t).ids + [EOS]
    return torch.tensor(ids)

G, G_val, H, H_val = map(to_stream, (gen_train, gen_val, hq_train, hq_val))
print(f"普通数据：训练 {len(gen_train)} 首 {len(G):,} 个 token，验证 {len(gen_val)} 首 {len(G_val):,} 个 token")
print(f"高质量数据：训练 {len(hq_train)} 首 {len(H):,} 个 token，验证 {len(hq_val)} 首 {len(H_val):,} 个 token")
print(f"高质量训练集只有普通训练集的 {len(H) / len(G):.1%}")
# endregion data

# region eval
@torch.no_grad()
def evaluate(model, ids, T=cfg.context, batch=64):
    """每 token 的平均交叉熵（nats），评估口径和第 17 章相同：把整条流切成长度 T 的段。"""
    model.eval()
    n = (len(ids) - 1) // T * T
    xs, ys = ids[:n].view(-1, T), ids[1:n + 1].view(-1, T)
    total = sum(F.cross_entropy(model(xs[i:i + batch]).flatten(0, 1), ys[i:i + batch].flatten(), reduction="sum").item()
                for i in range(0, len(xs), batch))
    model.train()
    return total / ys.numel()

def report(model):
    return {"gen_val": evaluate(model, G_val), "hq_val": evaluate(model, H_val), "hq_train": evaluate(model, H)}
# endregion eval

# %% [markdown]
# ## 2. 稳定段：只训一次，沿途存检查点
#
# WSD 分三段：warmup 30 步、稳定段保持峰值学习率 1e-2、衰减段线性降到 0（第 17 章）。
# 稳定段只用普通数据，训练到第 480 步，在第 240、360、480 步各存一份检查点（模型参数和优化器状态）。
# 之后的每一种退火都从某个检查点“分叉”出去，稳定段不用重训。种子 0、1、2 只决定初始参数，batch 计划由单独的生成器排好。

# %%
# region stable
PEAK, WARMUP, STABLE_END, FORKS, SEEDS = 1e-2, 30, 480, (240, 360, 480), (0, 1, 2)

def make_optimizer(model):
    decay = [p for p in model.parameters() if p.dim() >= 2]
    no_decay = [p for p in model.parameters() if p.dim() < 2]
    return torch.optim.AdamW([{"params": decay, "weight_decay": 0.1}, {"params": no_decay, "weight_decay": 0.0}], lr=PEAK)

def rows(stream, starts):
    idx = starts[:, None] + torch.arange(cfg.context + 1)
    return stream[idx]

def train_step(model, optimizer, x, lr):
    for group in optimizer.param_groups:
        group["lr"] = lr
    _, loss = model(x[:, :-1].contiguous(), x[:, 1:].contiguous())
    optimizer.zero_grad(set_to_none=True)
    loss.backward()
    torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
    optimizer.step()

def stable_phase(seed):
    torch.manual_seed(seed)
    model = TinyLLM(cfg)
    optimizer = make_optimizer(model)
    plan = torch.Generator().manual_seed(1234)
    checkpoints = {}
    for step in range(STABLE_END):
        starts = torch.randint(0, len(G) - cfg.context - 1, (BATCH,), generator=plan)
        train_step(model, optimizer, rows(G, starts), PEAK * min(1.0, (step + 1) / WARMUP))
        if step + 1 in FORKS:
            checkpoints[step + 1] = (copy.deepcopy(model.state_dict()), copy.deepcopy(optimizer.state_dict()))
    return checkpoints

t0 = time.perf_counter()
ckpts = {seed: stable_phase(seed) for seed in SEEDS}
print(f"[计时，本机] 3 个种子的稳定段（各 {STABLE_END} 步）共 {time.perf_counter() - t0:.1f} 秒")
# endregion stable

# %% [markdown]
# ## 3. 衰减段换数据：混进多少高质量数据
#
# 从第 480 步的检查点分叉，衰减 120 步（总步数的 20%，和第 17 章的 WSD 相同），学习率从 1e-2 线性降到 0。
# 衰减段的每个 batch 里，每一行以概率 p 取自高质量训练集、否则取自普通训练集。
# 每一行用哪份数据、从哪里截取，都由单独的生成器预先决定，所以不同的 p 用的是同一串随机数（p 大的那组，高质量行包含 p 小的那组）。
# 同时看三个数：普通验证集、高质量验证集、高质量训练集。

# %%
# region anneal
def anneal(ckpt, length, p_hq, hq_stream=None, order=0):
    """从检查点分叉，衰减 length 步；每一行以概率 p_hq 取自高质量数据。order 换一种数据顺序（第 7 节的“汤”用）。"""
    hq_stream = H if hq_stream is None else hq_stream
    model = TinyLLM(cfg)
    model.load_state_dict(ckpt[0])
    optimizer = make_optimizer(model)
    optimizer.load_state_dict(copy.deepcopy(ckpt[1]))       # 要复制：load_state_dict 不复制张量，step() 会原地改掉检查点里的动量
    plan = torch.Generator().manual_seed(4321 + order)
    for step in range(length):
        use_hq = torch.rand(BATCH, generator=plan) < p_hq
        g_starts = torch.randint(0, len(G) - cfg.context - 1, (BATCH,), generator=plan)
        h_starts = torch.randint(0, len(hq_stream) - cfg.context - 1, (BATCH,), generator=plan)
        x = torch.where(use_hq[:, None], rows(hq_stream, h_starts), rows(G, g_starts))
        train_step(model, optimizer, x, PEAK * (length - step) / length)
    return model

def epochs_over_hq(length, p_hq, hq_stream=None):
    """衰减段里高质量数据平均被看了几遍。"""
    hq_stream = H if hq_stream is None else hq_stream
    return length * BATCH * cfg.context * p_hq / len(hq_stream)

def mean_range(xs):
    return f"{sum(xs) / len(xs):.3f} [{min(xs):.3f}, {max(xs):.3f}]"
# endregion anneal

# %%
# region mix
DECAY = 120
MIXES = (0.0, 0.05, 0.1, 0.2, 0.3, 0.5, 1.0)
no_anneal = []
for seed in SEEDS:
    m = TinyLLM(cfg)
    m.load_state_dict(ckpts[seed][STABLE_END][0])
    no_anneal.append(report(m))
print(f"不衰减（第 480 步）   普通验证 {mean_range([r['gen_val'] for r in no_anneal])}  高质量验证 {mean_range([r['hq_val'] for r in no_anneal])}")
mix = {}
for p in MIXES:
    mix[p] = [report(anneal(ckpts[seed][STABLE_END], DECAY, p)) for seed in SEEDS]
    print(f"衰减，高质量 {p:>4.0%}  普通验证 {mean_range([r['gen_val'] for r in mix[p]])}  高质量验证 {mean_range([r['hq_val'] for r in mix[p]])}"
          f"  高质量训练 {sum(r['hq_train'] for r in mix[p]) / 3:.3f}  高质量数据看了 {epochs_over_hq(DECAY, p):4.1f} 遍")
for p in (0.1, 0.2):
    d = [a["hq_val"] - b["hq_val"] for a, b in zip(mix[p], mix[0.0])]
    e = [a["gen_val"] - b["gen_val"] for a, b in zip(mix[p], mix[0.0])]
    print(f"高质量 {p:.0%} 对比 0%（逐种子配对）：高质量验证 {', '.join(f'{x:+.3f}' for x in d)}；普通验证 {', '.join(f'{x:+.3f}' for x in e)}")
# endregion mix
log["no_anneal"], log["mix"] = no_anneal, {str(p): v for p, v in mix.items()}

# %% [markdown]
# ## 4. 高质量数据越少，越容易背
#
# 把高质量训练集缩到 50 首、25 首（取前若干首），衰减段的设置不变，比较 p=10% 和 30%。
# 数据少了，同样的 p 意味着每首诗被看更多遍。

# %%
# region pool-size
pool = {}
for n in (25, 50, 100):
    stream = to_stream(hq_train[:n])
    for p in (0.1, 0.3):
        res = mix[p] if n == len(hq_train) else [report(anneal(ckpts[seed][STABLE_END], DECAY, p, hq_stream=stream)) for seed in SEEDS]
        pool[n, p] = res
        d = [a["hq_val"] - b["hq_val"] for a, b in zip(res, mix[0.0])]
        print(f"高质量训练集 {n:>3} 首，p={p:.0%}：看了 {epochs_over_hq(DECAY, p, stream):5.1f} 遍  "
              f"高质量验证 {mean_range([r['hq_val'] for r in res])}（比 0% {sum(d) / 3:+.3f}）  普通验证 {sum(r['gen_val'] for r in res) / 3:.3f}")
# endregion pool-size
log["pool"] = {f"{n}|{p}": v for (n, p), v in pool.items()}
log["pool_tokens"] = {n: len(to_stream(hq_train[:n])) for n in (25, 50, 100)}

# %% [markdown]
# ## 5. 退火段多长
#
# 还是从第 480 步分叉、p=10%，把衰减段从 120 步换成 30、60、240 步。衰减段越长，总训练量越多，高质量数据也被看得越多。

# %%
# region decay-length
length = {DECAY: mix[0.1]}
length_base = {DECAY: mix[0.0]}
for L in (30, 60, 240):
    length[L] = [report(anneal(ckpts[seed][STABLE_END], L, 0.1)) for seed in SEEDS]
    length_base[L] = [report(anneal(ckpts[seed][STABLE_END], L, 0.0)) for seed in SEEDS]
for L in sorted(length):
    d = [a["hq_val"] - b["hq_val"] for a, b in zip(length[L], length_base[L])]
    print(f"衰减 {L:>3} 步：p=0% 普通验证 {sum(r['gen_val'] for r in length_base[L]) / 3:.3f}  "
          f"p=10% 普通验证 {sum(r['gen_val'] for r in length[L]) / 3:.3f}  高质量验证 {sum(r['hq_val'] for r in length[L]) / 3:.3f}"
          f"（比同长度的 0% {sum(d) / 3:+.3f}）  高质量数据看了 {epochs_over_hq(L, 0.1):4.1f} 遍")
# endregion decay-length
log["length"] = {str(L): {"p10": length[L], "p0": length_base[L]} for L in length}

# %% [markdown]
# ## 6. 从更早的检查点分叉：早期的结论靠得住吗
#
# WSD 最方便的地方，是可以在稳定段的任何一个检查点接一段衰减，得到一个“退火过的”模型。
# 于是可以先在早期检查点上便宜地比较几种退火数据，再决定最终用哪种。Llama 3 就是这样评估小数据集的：
# 在训练到一半的 8B 模型上，把学习率线性降到 0，新数据占 30%（Dubey 等，2024，第 3.1.3 节）。
# 这里在第 240、360、480 步各分叉一次，比较 p=0%、10%、30%，看排序是否一致。

# %%
# region fork-points
forks = {}
for f in FORKS:
    for p in (0.0, 0.1, 0.3):
        forks[f, p] = mix[p] if f == STABLE_END else [report(anneal(ckpts[seed][f], DECAY, p)) for seed in SEEDS]
    order = sorted((0.0, 0.1, 0.3), key=lambda p: sum(r["hq_val"] for r in forks[f, p]))
    print(f"第 {f} 步分叉：高质量验证  " + "  ".join(f"p={p:.0%} {sum(r['hq_val'] for r in forks[f, p]) / 3:.3f}" for p in (0.0, 0.1, 0.3))
          + "  │  排序 " + " < ".join(f"{p:.0%}" for p in order))
k = len(MIXES)
print(f"比较 {k} 种退火数据的训练步数：WSD 稳定段一次 + {k} 段衰减 = {STABLE_END} + {k}×{DECAY} = {STABLE_END + k * DECAY} 步；"
      f"余弦调度每种都要从头训 = {k}×{STABLE_END + DECAY} = {k * (STABLE_END + DECAY)} 步")
# endregion fork-points
log["forks"] = {f"{f}|{p}": v for (f, p), v in forks.items()}

# %% [markdown]
# ## 7. 退火的“汤”：几次退火取平均
#
# 同一个检查点、同样的 p=10%，只换衰减段的数据顺序，退火 3 次，再把 3 个模型的参数直接平均。
# OLMo 2 把这叫 model soup（同一检查点上用不同数据顺序退火几次再平均）；Llama 3 在退火段对检查点取平均。

# %%
# region soup
@torch.no_grad()
def average(models):
    soup = copy.deepcopy(models[0])
    for name, p in soup.named_parameters():
        p.copy_(torch.stack([dict(m.named_parameters())[name] for m in models]).mean(0))
    return soup

soup_rows = []
for seed in SEEDS:
    singles = [anneal(ckpts[seed][STABLE_END], DECAY, 0.1, order=o) for o in range(3)]
    s = [report(m) for m in singles]
    soup_rows.append({"singles": s, "soup": report(average(singles))})
best = [min(r["hq_val"] for r in row["singles"]) for row in soup_rows]
mean_single = [sum(r["hq_val"] for r in row["singles"]) / 3 for row in soup_rows]
souped = [row["soup"]["hq_val"] for row in soup_rows]
print(f"高质量验证：单次退火平均 {mean_range(mean_single)}  三次里最好的 {mean_range(best)}  三次取平均（汤） {mean_range(souped)}")
print(f"普通验证：单次退火平均 {sum(sum(r['gen_val'] for r in row['singles']) / 3 for row in soup_rows) / 3:.3f}  "
      f"汤 {sum(row['soup']['gen_val'] for row in soup_rows) / 3:.3f}")
# endregion soup
log["soup"] = soup_rows

# %%
with open("annealing_log.json", "w", encoding="utf-8") as f:
    json.dump(log, f, ensure_ascii=False)
print("已写出 annealing_log.json")
