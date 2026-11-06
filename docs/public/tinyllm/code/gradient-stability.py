# %% [markdown]
# # 第 20 章：梯度稳定与累积
#
# 配套教案：https://lewislau86.github.io/tinyllm/gradient-stability
#
# 从上到下运行即可（`python gradient-stability.py`），CPU 上约一分半（一共训练 21 个小模型，每个约 4 秒）。需要安装 PyTorch 和 `tokenizers`。
# 这个文件是本章代码的唯一来源：教案中的代码片段由 `# region 名字` / `# endregion 名字`
# 标记的区域直接引用，notebook 也由它生成（scripts/build-tinyllm-code.py）。
#
# 第 12 章起，每一步都“按全局范数把梯度裁到 1”。本章先看梯度在训练中到底长什么样，再回答：裁剪防的是什么、
# 梯度累积怎样才和大 batch 一样、FP16 为什么要放大损失，以及训练时该盯着哪些数。

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
# 模型代码、数据划分、评估口径都从第 12 章原样复制，尺寸和第 17 章的代理模型相同（词表 1024、宽度 64、2 层）。
# 本章要训练二十多次，所以用这个缩小的版本；损失只在本章内部比较。

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
cfg = TinyConfig(vocab_size=1024, d_model=64, n_layers=2)       # 代理模型：只改这三个尺寸
STEPS, BATCH = 240, 16
# endregion proxy
print(cfg)

# %%
# region data
poems = load_poems(6000)
train_poems = [p["text"] for p in poems if p["split"] == "train"]
val_poems = [p["text"] for p in poems if p["split"] == "val"]
# endregion data

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

tokenizer = train_tokenizer(train_poems, cfg.vocab_size)
EOS = tokenizer.token_to_id("<eos>")
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

# %%
# region eval-protocol
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
# endregion eval-protocol

print("训练流", len(train_ids), "个 token；验证流", len(val_ids), "个 token；参数", sum(p.numel() for p in TinyLLM(cfg).parameters()))

# %% [markdown]
# ## 1. 全局梯度范数
#
# 一次反向传播之后，每个参数张量都有一个 `.grad`。把它们全部拼成一个长向量，这个向量的长度就是**全局梯度范数**：

# %%
# region global-norm
plan = torch.Generator().manual_seed(1234)                 # batch 计划：所有对照共用，seed 只决定初始参数
starts = torch.randint(0, len(train_ids) - cfg.context - 1, (STEPS, BATCH), generator=plan)

def get_batch(step):
    idx = starts[step][:, None] + torch.arange(cfg.context + 1)
    return train_ids[idx[:, :-1]], train_ids[idx[:, 1:]]

torch.manual_seed(0)
model = TinyLLM(cfg)
x, y = get_batch(0)
model(x, y)[1].backward()
grads = [p.grad for p in model.parameters()]
per_tensor = torch.stack([g.norm() for g in grads])        # 每个张量自己的 L2 范数
by_hand = per_tensor.norm()                                # 平方和再开方 = 拼成一个长向量的长度
long_vector = torch.cat([g.flatten() for g in grads]).norm()
print(f"{len(grads)} 个张量，{sum(g.numel() for g in grads)} 个数")
print(f"逐张量再合并：{by_hand:.6f}   拼成长向量：{long_vector:.6f}   clip_grad_norm_ 返回：{torch.nn.utils.clip_grad_norm_(model.parameters(), math.inf):.6f}")
# endregion global-norm

# %% [markdown]
# 按全局范数裁剪：范数超过阈值时，所有梯度**乘同一个系数**，方向不变；按值裁剪（`clip_grad_value_`）则逐个数截断，方向会变。

# %%
# region clip-by-hand
def clip_by_global_norm(params, max_norm):
    grads = [p.grad for p in params if p.grad is not None]
    total = torch.stack([g.norm() for g in grads]).norm()
    scale = min(1.0, max_norm / (total.item() + 1e-6))     # 没超过阈值时 scale = 1，什么也不做
    for g in grads:
        g.mul_(scale)
    return total

original = torch.cat([p.grad.flatten() for p in model.parameters()]).clone()
saved = [p.grad.clone() for p in model.parameters()]

def restore():
    for p, g in zip(model.parameters(), saved):
        p.grad = g.clone()

def flat():
    return torch.cat([p.grad.flatten() for p in model.parameters()])

clip_by_global_norm(list(model.parameters()), 0.5)
mine = flat()
restore()
torch.nn.utils.clip_grad_norm_(model.parameters(), 0.5)
print(f"手写与 clip_grad_norm_ 的最大差：{(mine - flat()).abs().max():.1e}；裁剪后范数 {flat().norm():.4f}")
cos = F.cosine_similarity
print(f"按范数裁到 0.5：和原梯度的夹角余弦 {cos(flat(), original, dim=0):.4f}")
restore()
torch.nn.utils.clip_grad_value_(model.parameters(), 1e-3)
print(f"按值裁到 ±0.001：截断了 {(original.abs() > 1e-3).float().mean():.1%} 的数，夹角余弦 {cos(flat(), original, dim=0):.4f}")
# endregion clip-by-hand

# %% [markdown]
# ## 2. 训练函数：每一步记下梯度范数和更新量
#
# 和第 17 章一样（AdamW、weight decay 0.1、学习率固定 3e-3），每步记三样东西：损失、**裁剪前**的全局梯度范数、
# 这一步参数实际移动的距离（更新量的 L2 范数）。`accum` 把一个 batch 拆成几个 micro-batch 依次反传（第 6 节），
# `spike` 用来模拟一次梯度尖峰（第 4 节）。

# %%
# region run
def make_optimizer(model, kind="adamw", lr=3e-3, betas=(0.9, 0.999)):
    if kind == "sgd":
        return torch.optim.SGD(model.parameters(), lr=lr, momentum=0.9)
    decay = [p for p in model.parameters() if p.dim() >= 2]
    no_decay = [p for p in model.parameters() if p.dim() < 2]
    return torch.optim.AdamW([{"params": decay, "weight_decay": 0.1},
                              {"params": no_decay, "weight_decay": 0.0}], lr=lr, betas=betas)

def train(seed=0, clip=1.0, accum=1, spike=None, probe=(), **opt_kw):
    torch.manual_seed(seed)
    model = TinyLLM(cfg)
    optimizer = make_optimizer(model, **opt_kw)
    log = {"loss": [], "grad_norm": [], "update": [], "probe": {}}
    for step in range(STEPS):
        x, y = get_batch(step)
        factor = spike[1] if spike is not None and step == spike[0] else 1.0   # 模拟尖峰：这一步的梯度放大 factor 倍
        optimizer.zero_grad(set_to_none=True)
        total = 0.0
        for xs, ys in zip(x.chunk(accum), y.chunk(accum)):           # accum=1 时就是整个 batch
            _, loss = model(xs, ys)
            (loss / accum * factor).backward()                       # 梯度在 .grad 里累加
            total += loss.item() / accum
        if step in probe:
            log["probe"][step] = layer_report(model)
        norm = torch.nn.utils.clip_grad_norm_(model.parameters(), clip or math.inf)   # 返回裁剪前的范数
        before = [p.detach().clone() for p in model.parameters()]
        optimizer.step()
        log["loss"].append(total)
        log["grad_norm"].append(norm.item())
        log["update"].append(math.sqrt(sum(((p.detach() - b) ** 2).sum().item() for p, b in zip(model.parameters(), before))))
    log["val"] = evaluate(model)[0]
    return log, model, optimizer
# endregion run

# region layer-report
def layer_report(model):
    """按零件分组：梯度范数、参数范数。"""
    groups = {}
    for name, p in model.named_parameters():
        key = ("RMSNorm" if "norm" in name else "词嵌入" if name.startswith("embed") else
               f"第 {name.split('.')[1]} 层 " + ("注意力" if ".attn." in name else "前馈"))
        g = groups.setdefault(key, [0.0, 0.0])
        g[0] += p.grad.norm().item() ** 2
        g[1] += p.detach().norm().item() ** 2
    return {k: (math.sqrt(a), math.sqrt(b)) for k, (a, b) in groups.items()}
# endregion layer-report

# %% [markdown]
# ## 3. 基线里的梯度长什么样
#
# 第 12 章的设置（裁到 1.0），3 个种子：

# %%
# region baseline
SEEDS = (0, 1, 2)
runs = {}
t0 = time.time()
for seed in SEEDS:
    runs[("裁到 1.0", seed)], last, last_opt = train(seed=seed, probe=(0, STEPS - 1) if seed == 0 else ())
    if seed == 0:
        baseline_model, baseline_opt = last, last_opt
print(f"每次训练约 {(time.time() - t0) / 3:.1f} 秒")
log = runs[("裁到 1.0", 0)]
print("步数        " + "  ".join(f"{s:>5}" for s in (1, 5, 10, 50, 100, 150, 200, 240)))
print("梯度范数    " + "  ".join(f"{log['grad_norm'][s - 1]:5.2f}" for s in (1, 5, 10, 50, 100, 150, 200, 240)))
for seed in SEEDS:
    n = runs[("裁到 1.0", seed)]["grad_norm"]
    print(f"种子 {seed}：超过 1.0 被裁剪的步数 {sum(v > 1.0 for v in n)}/{STEPS}（前 30 步 {sum(v > 1.0 for v in n[:30])}，"
          f"后 120 步 {sum(v > 1.0 for v in n[120:])}），最大 {max(n):.2f}")
# endregion baseline

# %% [markdown]
# 按零件拆开看第 1 步和第 240 步（种子 0）：梯度范数、参数范数，以及这一步更新量和参数大小之比。

# %%
# region per-layer
for step in (0, STEPS - 1):
    print(f"第 {step + 1} 步   梯度范数   参数范数")
    for k, (g, w) in log["probe"][step].items():
        print(f"  {k:<10} {g:8.4f}  {w:8.2f}")
theta = math.sqrt(sum(p.detach().norm().item() ** 2 for p in baseline_model.parameters()))
print(f"第 240 步：这一步的更新量 {log['update'][-1]:.4f}，参数总范数 {theta:.1f}，比值 {log['update'][-1] / theta:.1e}")
# endregion per-layer

# %% [markdown]
# ## 4. 对照：AdamW 下，裁剪阈值改一百倍
#
# 不裁剪、裁到 1.0、裁到 0.01（几乎每一步都被缩小几十倍），各 3 个种子：

# %%
# region thresholds
def report(label, logs):
    vals = [l["val"] for l in logs]
    m = sum(vals) / len(vals)
    rng = f"（{min(vals):.3f}～{max(vals):.3f}）" if len(vals) > 1 else "（单个种子）"
    print(f"{label:<22} 验证损失 {m:.3f}{rng}")
    return vals

summary = {}
for label, clip in [("不裁剪", None), ("裁到 0.01", 0.01)]:
    for seed in SEEDS:
        runs[(label, seed)] = train(seed=seed, clip=clip)[0]
summary["不裁剪"] = report("不裁剪", [runs[("不裁剪", s)] for s in SEEDS])
summary["裁到 1.0"] = report("裁到 1.0（第 12 章）", [runs[("裁到 1.0", s)] for s in SEEDS])
summary["裁到 0.01"] = report("裁到 0.01", [runs[("裁到 0.01", s)] for s in SEEDS])
# endregion thresholds

# %% [markdown]
# Adam 的一步是 $m/\sqrt{v}$：如果每一步的梯度都乘同一个系数 $c$，$m$ 乘 $c$，$\sqrt{v}$ 也乘 $c$，两者相除，$c$ 就消掉了。
# 用一个参数验证一下：

# %%
# region adam-scale
for c in (1.0, 0.01, 1000.0):
    w = torch.zeros(1, requires_grad=True)
    opt = torch.optim.Adam([w], lr=0.1)
    for g in (0.3, -0.1, 0.5, 0.2):
        w.grad = torch.tensor([g * c])
        opt.step()
    print(f"梯度全部乘 {c:>6}：4 步后 w = {w.item():.6f}")
# endregion adam-scale

# %% [markdown]
# ## 5. 裁剪真正防的是什么：一次梯度尖峰
#
# 在第 121 步（`SPIKE_STEP = 120`，从 0 数），把这一步的梯度放大若干倍（模拟一个坏 batch 或一次数值故障），其他什么都不变。先不裁剪，看放大 10、100、1000 倍各有多大影响（种子 0）：

# %%
# region spike-sweep
SPIKE_STEP = 120
for factor in (10, 100, 1000):
    runs[(f"尖峰 ×{factor}，不裁剪", 0)] = train(seed=0, clip=None, spike=(SPIKE_STEP, factor))[0]
    print(f"放大 {factor:>4} 倍：验证损失 {runs[(f'尖峰 ×{factor}，不裁剪', 0)]['val']:.3f}")
print(f"没有尖峰：      验证损失 {runs[('不裁剪', 0)]['val']:.3f}")
# endregion spike-sweep

# %% [markdown]
# 放大 1000 倍，不裁剪和裁到 1.0 各跑 3 个种子：

# %%
# region spike
for seed in SEEDS:
    runs[("尖峰 ×1000，不裁剪", seed)] = runs.get(("尖峰 ×1000，不裁剪", seed)) or train(seed=seed, clip=None, spike=(SPIKE_STEP, 1000))[0]
    runs[("尖峰 ×1000，裁到 1.0", seed)] = train(seed=seed, clip=1.0, spike=(SPIKE_STEP, 1000))[0]
summary["尖峰 ×1000，不裁剪"] = report("尖峰 ×1000，不裁剪", [runs[("尖峰 ×1000，不裁剪", s)] for s in SEEDS])
summary["尖峰 ×1000，裁到 1.0"] = report("尖峰 ×1000，裁到 1.0", [runs[("尖峰 ×1000，裁到 1.0", s)] for s in SEEDS])
# endregion spike

# %% [markdown]
# 尖峰前后，每一步参数实际移动了多远？（种子 0，各段取平均）

# %%
# region spike-mechanism
runs[("尖峰 ×1000，不裁剪，β2=0.95", 0)] = train(seed=0, clip=None, spike=(SPIKE_STEP, 1000), betas=(0.9, 0.95))[0]
segments = [("尖峰前 10 步", 110, 120), ("尖峰后 10 步", 121, 131), ("最后 40 步", 200, 240)]
print(f"{'':<24}" + "".join(f"{name:>12}" for name, _, _ in segments) + "    最终验证")
for label in ("不裁剪", "尖峰 ×1000，不裁剪", "尖峰 ×1000，裁到 1.0", "尖峰 ×1000，不裁剪，β2=0.95"):
    u = runs[(label, 0)]["update"]
    print(f"{label:<22}" + "".join(f"{sum(u[a:b]) / (b - a):14.3f}" for _, a, b in segments) + f"    {runs[(label, 0)]['val']:.3f}")
# endregion spike-mechanism

# %% [markdown]
# ## 6. 对照：SGD 没有自适应的步长
#
# 换成带动量的 SGD、学习率 1.0（单个种子），不裁剪和裁到 1.0：

# %%
# region sgd
for label, clip in [("SGD 1.0，不裁剪", None), ("SGD 1.0，裁到 1.0", 1.0)]:
    runs[(label, 0)] = train(seed=0, clip=clip, kind="sgd", lr=1.0)[0]
    n = runs[(label, 0)]["grad_norm"]
    print(f"{label:<14} 最大梯度范数 {max(n):.3g}  验证损失 {runs[(label, 0)]['val']:.3f}   （乱猜是 ln 1024 = {math.log(1024):.3f}）")
# endregion sgd

# %% [markdown]
# ## 7. 梯度累积
#
# `train(accum=4)`：每一步的 16 段拆成 4 个 micro-batch，各自前向、反向（损失除以 4），梯度在 `.grad` 里累加，最后裁剪、更新一次。
# 先只做一步，和整个 batch 一次算的梯度对拍；再看两种常见的写错方式：

# %%
# region accum-check
def one_step_grads(mode, accum=4):
    torch.manual_seed(0)
    model = TinyLLM(cfg)
    x, y = get_batch(0)
    if mode == "整个 batch":
        model(x, y)[1].backward()
    for xs, ys in zip(x.chunk(accum), y.chunk(accum)):
        if mode == "整个 batch":
            break
        _, loss = model(xs, ys)
        if mode == "正确：损失除以 4":
            loss.div(accum).backward()
        elif mode == "错误：忘了除以 4":
            loss.backward()
        elif mode == "错误：每个 micro-batch 各裁一次":
            saved = [p.grad.clone() if p.grad is not None else torch.zeros_like(p) for p in model.parameters()]
            for p in model.parameters():
                p.grad = None
            loss.div(accum).backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 0.25)   # 把阈值也分成 4 份，还是错
            for p, s in zip(model.parameters(), saved):
                p.grad += s
    raw = torch.cat([p.grad.flatten() for p in model.parameters()]).clone()   # 裁剪前
    if mode != "错误：每个 micro-batch 各裁一次":
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
    return raw, torch.cat([p.grad.flatten() for p in model.parameters()])  # 裁剪前、裁剪后

ref_raw, ref = one_step_grads("整个 batch")
print(f"整个 batch：裁剪前范数 {ref_raw.norm():.4f}，裁剪后 {ref.norm():.4f}")
for mode in ("正确：损失除以 4", "错误：忘了除以 4", "错误：每个 micro-batch 各裁一次"):
    raw, g = one_step_grads(mode)
    print(f"{mode:<24} 裁剪前范数之比 {raw.norm() / ref_raw.norm():.3f}  裁剪后：最大差 {(g - ref).abs().max():.1e}，夹角余弦 {F.cosine_similarity(g, ref, dim=0):.4f}")
# endregion accum-check

# %% [markdown]
# 正确的写法训练满 240 步，和整个 batch 一次算（第 3 节种子 0）比较：

# %%
# region accum-full
runs[("累积 4 步", 0)], accum_model, _ = train(seed=0, accum=4)
diff = max((p - q).abs().max().item() for p, q in zip(accum_model.parameters(), baseline_model.parameters()))
print(f"验证损失：整个 batch {runs[('裁到 1.0', 0)]['val']:.4f}，累积 4 步 {runs[('累积 4 步', 0)]['val']:.4f}；240 步后参数最大差 {diff:.1e}")
# endregion accum-full

# %% [markdown]
# ## 8. FP16 与 loss scaling
#
# 用训练好的基线模型（种子 0），取一个 batch，分别在 FP32 和 FP16 autocast 下反传，比较参数的梯度：

# %%
# region fp16-underflow
x, y = get_batch(STEPS - 1)

def grads_under(model, fp16, scale=1.0):
    model.zero_grad(set_to_none=True)
    with torch.autocast("cpu", dtype=torch.float16, enabled=fp16):
        _, loss = model(x, y)
    (loss * scale).backward()                                  # 放大损失 = 放大反向传播里的每一个梯度
    return torch.cat([p.grad.flatten() / scale for p in model.parameters()])   # 再缩回来

ref = grads_under(baseline_model, fp16=False)
smallest_normal = torch.finfo(torch.float16).smallest_normal     # 比它小就只能用次正规数表示，有效位数变少
smallest_subnormal = 2.0 ** -24                                  # 比它的一半还小就变成 0
print(f"FP16：最小正规数 {smallest_normal:.1e}，最小次正规数 {smallest_subnormal:.1e}")
print(f"FP32 梯度里，绝对值小于 {smallest_normal:.1e} 的占 {(ref.abs() < smallest_normal).float().mean():.1%}，"
      f"小于 {smallest_subnormal:.1e} 的占 {(ref.abs() < smallest_subnormal).float().mean():.2%}")
for scale in (1.0, 2.0 ** 8, 2.0 ** 16, 2.0 ** 24):
    g = grads_under(baseline_model, fp16=True, scale=scale)
    if not torch.isfinite(g).all():
        print(f"放大 2^{int(math.log2(scale)):<2}：出现 inf/nan，这一步的梯度不能用")
        continue
    lost = ((g == 0) & (ref != 0)).float().mean()
    print(f"放大 2^{int(math.log2(scale)):<2}：变成 0 的梯度 {lost:.3%}，和 FP32 的相对误差 {(g - ref).norm() / ref.norm():.2%}")
# endregion fp16-underflow

# %% [markdown]
# `GradScaler` 自动找放大倍数：出现 inf/nan 就跳过这一步、倍数减半；连续若干步正常就加倍。为了几十步之内看到变化，
# 这里从 2^24 起步、每连续 4 步正常就尝试加倍（默认是 2^16 起步、2000 步）。接着基线训练结束时的状态，再训练 24 步。注意先 `unscale_` 再裁剪：

# %%
# region grad-scaler
model = copy.deepcopy(baseline_model)
optimizer = make_optimizer(model)
optimizer.load_state_dict(baseline_opt.state_dict())         # 接着基线的优化器状态
scaler = torch.amp.GradScaler("cpu", init_scale=2.0 ** 24, growth_interval=4)
history = []
for step in range(24):
    x, y = get_batch(step)
    optimizer.zero_grad(set_to_none=True)
    with torch.autocast("cpu", dtype=torch.float16):
        _, loss = model(x, y)
    scaler.scale(loss).backward()                              # 反传的是放大后的损失
    scaled = torch.stack([p.grad.norm() for p in model.parameters()]).norm()
    scaler.unscale_(optimizer)                                 # 先缩回真实大小（顺便检查 inf/nan）
    norm = torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)   # 再裁剪，阈值才有意义
    scale = scaler.get_scale()
    scaler.step(optimizer)                                     # 有 inf/nan 时自动跳过这一步
    scaler.update()                                            # 调整下一步的放大倍数
    history.append((int(math.log2(scale)), scaler.get_scale() < scale, scaled.item(), norm.item()))
print("放大倍数 2^k 的 k：", " ".join(str(k) for k, _, _, _ in history))
print("这一步：          ", " ".join("跳" if skip else "更" for _, skip, _, _ in history))
k, _, scaled, norm = next(h for h in history if not h[1])
print(f"第一次成功更新：放大 2^{k}，放大后的梯度范数 {scaled:.4g}，unscale_ 之后 {norm:.4f}")
print(f"24 步里跳过 {sum(h[1] for h in history)} 步；下一步将用 2^{int(math.log2(scaler.get_scale()))}")
# endregion grad-scaler

# %%
hist_ref = ref.abs().clamp_min(1e-12).log10()
grad_log = {
    "steps": STEPS, "spike_step": SPIKE_STEP,
    "summary": summary,
    "hist": torch.histogram(hist_ref, bins=60, range=(-12.0, 0.0)).hist.tolist(),
    "fp16": {"smallest_normal": smallest_normal, "smallest_subnormal": smallest_subnormal},
    "runs": {f"{k[0]}|{k[1]}": {kk: vv for kk, vv in v.items() if kk != "probe"} for k, v in runs.items()},
    "probe": {str(k): v for k, v in runs[("裁到 1.0", 0)]["probe"].items()},
}
with open("gradient_stability_log.json", "w", encoding="utf-8") as f:
    json.dump(grad_log, f, ensure_ascii=False)
