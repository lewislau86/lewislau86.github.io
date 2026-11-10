# %% [markdown]
# # 第 25 章：大规模训练稳定性
#
# 配套教案：https://lewislau86.github.io/tinyllm/large-model-stability
#
# 从上到下运行即可（`python large-model-stability.py`），CPU 上约一分半（一共训练 40 个小模型）。需要安装 PyTorch 和 `tokenizers`。
# 这个文件是本章代码的唯一来源：教案中的代码片段由 `# region 名字` / `# endregion 名字`
# 标记的区域直接引用，notebook 也由它生成（scripts/build-tinyllm-code.py）。
#
# 模型变大以后会遇到三类小模型上看不到的问题：数值失控、超参数搬不过去、一张卡装不下。
# 本章在 CPU 上的小模型里把前两类复现出来，再用张量运算模拟第三类的几种解法。

# %%
# region imports
import json
import math
import time
from dataclasses import dataclass, replace

import torch
from torch import nn
from torch.nn import functional as F
from torch.utils.checkpoint import checkpoint
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
# ## 0. 实验对象
#
# 模型代码从第 12 章复制，尺寸是第 17 章的代理模型，训练用第 17 章的 WSD（峰值学习率另行指定）。
# 配置里多了两个开关：`qk_norm`（第 2 节）和 `mup_base`（第 4 节），默认关闭，这时和第 12 章的模型完全一样。

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
    qk_norm: bool = False      # 本章加的：注意力里对每个头的 q、k 各做一次 RMSNorm（第 2 节）
    mup_base: int = 0          # 本章加的：μP 的基准宽度，0 表示用标准参数化（第 4 节）

cfg = TinyConfig()
# endregion config

# region proxy
cfg = TinyConfig(vocab_size=1024, d_model=64, n_layers=2)       # 第 17 章的代理模型
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
        self.qk_norm = cfg.qk_norm
        if cfg.qk_norm:                                               # 和 Qwen3 一样：每个头的 q、k 各一个 RMSNorm
            self.q_norm = nn.RMSNorm(cfg.d_model // cfg.n_heads)
            self.k_norm = nn.RMSNorm(cfg.d_model // cfg.n_heads)

    def qk(self, x, cos, sin):
        B, T, D = x.shape
        q, k, v = (t.view(B, T, self.n_heads, D // self.n_heads).transpose(1, 2)
                   for t in self.qkv(x).split(D, dim=-1))
        if self.qk_norm:
            q, k = self.q_norm(q), self.k_norm(k)
        return apply_rope(q, cos, sin), apply_rope(k, cos, sin), v

    def forward(self, x, cos, sin):
        B, T, D = x.shape
        q, k, v = self.qk(x, cos, sin)
        y = F.scaled_dot_product_attention(q, k, v, is_causal=True)
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
        base = self.cfg.mup_base or self.cfg.d_model                  # μP：词嵌入的初始化不随宽度变
        nn.init.normal_(self.embed.weight, mean=0.0, std=base ** -0.5)
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
        if self.cfg.mup_base:
            logits = logits * (self.cfg.mup_base / self.cfg.d_model)   # μP：输出乘 1/宽度倍数
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
# ## 1. 训练函数
#
# 和第 17 章相同（AdamW、weight decay 0.1、裁剪 1.0、WSD），多两个选项：`z_loss` 系数，以及 μP 时隐藏层矩阵的学习率乘 `基准宽度 / 宽度`。

# %%
# region run
plan = torch.Generator().manual_seed(1234)
starts = torch.randint(0, len(train_ids) - cfg.context - 1, (STEPS, BATCH), generator=plan)

def wsd(step, steps, warmup_frac=0.125, decay_frac=0.2):
    warmup, decay_from = max(1, round(warmup_frac * steps)), steps - int(decay_frac * steps)
    if step < warmup:
        return (step + 1) / warmup
    return 1.0 if step < decay_from else (steps - step) / (steps - decay_from)

def make_optimizer(model, peak):
    c = model.cfg
    hidden = [p for n, p in model.named_parameters() if p.dim() >= 2 and not n.startswith("embed")]
    groups = [
        {"params": hidden, "weight_decay": 0.1, "mult": c.mup_base / c.d_model if c.mup_base else 1.0},  # μP：1/宽度倍数
        {"params": [model.embed.weight], "weight_decay": 0.1, "mult": 1.0},                            # 词嵌入：不随宽度变
        {"params": [p for p in model.parameters() if p.dim() < 2], "weight_decay": 0.0, "mult": 1.0},
    ]
    return torch.optim.AdamW(groups, lr=peak)

def train(c, peak, steps=STEPS, z_loss=0.0, seed=0):
    torch.manual_seed(seed)
    model = TinyLLM(c)
    optimizer = make_optimizer(model, peak)
    for step in range(steps):
        for group in optimizer.param_groups:
            group["lr"] = peak * wsd(step, steps) * group["mult"]
        idx = starts[step][:, None] + torch.arange(c.context + 1)
        logits = model(train_ids[idx[:, :-1]])
        loss = F.cross_entropy(logits.flatten(0, 1), train_ids[idx[:, 1:]].flatten())
        if z_loss:
            loss = loss + z_loss * torch.logsumexp(logits, dim=-1).pow(2).mean()   # z-loss（第 15 章）
        optimizer.zero_grad(set_to_none=True)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        optimizer.step()
    return model
# endregion run

# %% [markdown]
# 训练完以后量两个“尺度”：注意力分数（softmax 之前）绝对值的最大值，以及输出 logits 的 log-sum-exp 的平均值。

# %%
# region probes
@torch.no_grad()
def attention_logit_max(model, x):
    """每一层注意力里，q·k/√d 的绝对值最大是多少（只看因果掩码允许的位置）。"""
    seen = []
    hooks = [b.attn.register_forward_hook(lambda mod, inp, out: seen.append((mod, inp[0]))) for b in model.blocks]
    model(x)
    for h in hooks:
        h.remove()
    top = 0.0
    for attn, h in seen:
        q, k, _ = attn.qk(h, model.cos, model.sin)
        s = q @ k.transpose(-2, -1) / math.sqrt(q.shape[-1])
        T = s.shape[-1]
        top = max(top, s.masked_fill(torch.ones(T, T, dtype=torch.bool).triu(1), 0).abs().max().item())
    return top

@torch.no_grad()
def logit_lse(model, x):
    return torch.logsumexp(model(x), dim=-1).mean().item()

probe_x = train_ids[starts[0][:, None] + torch.arange(cfg.context)]
# endregion probes

# %% [markdown]
# ## 2. 数值失控：在小模型上用大学习率提前看到
#
# 峰值学习率从 3e-3 扫到 3e-1（主线是 1e-2），比较三种设置：原样、加 QK Norm、加 z-loss（系数 1e-4）。

# %%
# region instability
LRS = (3e-3, 1e-2, 3e-2, 1e-1, 3e-1)
VARIANTS = {"原样": (cfg, 0.0), "加 QK Norm": (replace(cfg, qk_norm=True), 0.0), "加 z-loss": (cfg, 1e-4)}
t0 = time.time()
sweep = {}
for name, (c, z) in VARIANTS.items():
    sweep[name] = []
    for lr in LRS:
        model = train(c, lr, z_loss=z)
        sweep[name].append({"lr": lr, "val": evaluate(model)[0], "attn": attention_logit_max(model, probe_x), "lse": logit_lse(model, probe_x)})
print(f"{len(LRS) * len(VARIANTS)} 次训练，每次约 {(time.time() - t0) / (len(LRS) * len(VARIANTS)):.1f} 秒")
def pad(text, width):
    """按显示宽度补空格：汉字占两格。"""
    return text + " " * (width - sum(2 if ord(ch) > 0x2E80 else 1 for ch in text))

print(pad("峰值学习率", 20) + "".join(f"{lr:>10.0e}" for lr in LRS))
for name, rows in sweep.items():
    print(pad(name, 12) + pad("验证", 8) + "".join(f"{r['val']:10.3f}" for r in rows))
    print(pad("", 12) + pad("注意力", 8) + "".join(f"{r['attn']:10.4g}" for r in rows))
    print(pad("", 12) + pad("lse", 8) + "".join(f"{r['lse']:10.2f}" for r in rows))
for name, rows in sweep.items():
    print(f"{name}：5 个学习率上的平均验证损失 {sum(r['val'] for r in rows) / len(rows):.3f}")
# endregion instability

# %% [markdown]
# ## 3. 超参数搬不过去：μP
#
# 宽度 32、64、128（每个头固定 16 维，宽度变了只改头数），各扫 5 个学习率，训练 120 步（单个种子）。
# 标准参数化（SP）和 μP 各一组；基准宽度 64 上两者完全相同，只算一次。

# %%
# region mup
WIDTHS, MUP_LRS, MUP_STEPS = (32, 64, 128), (1e-3, 3e-3, 1e-2, 3e-2, 1e-1), 120
mup = {"SP": {}, "μP": {}}
t0 = time.time()
for d in WIDTHS:
    for kind in ("SP", "μP"):
        if kind == "μP" and d == 64:
            mup["μP"][d] = mup["SP"][d]                       # 基准宽度：μP 和 SP 一模一样
            continue
        c = replace(cfg, d_model=d, n_heads=d // 16, mup_base=64 if kind == "μP" else 0)
        mup[kind][d] = [evaluate(train(c, lr, steps=MUP_STEPS))[0] for lr in MUP_LRS]
print(f"μP 实验用时 {time.time() - t0:.0f} 秒")
print("学习率          " + "".join(f"{lr:>9.0e}" for lr in MUP_LRS) + "   最好的学习率")
for kind, rows in mup.items():
    for d, vals in rows.items():
        best = min(range(len(vals)), key=vals.__getitem__)
        print(f"{kind:<3} 宽度 {d:<4}  " + "".join(f"{v:9.3f}" for v in vals) + f"   {MUP_LRS[best]:.0e}")
# endregion mup

# %% [markdown]
# ## 4. 一张卡装不下：先算账
#
# 混合精度训练时，每个参数大约要 16 字节（第 13 章）：BF16 的参数 2、梯度 2，FP32 的主权重 4、Adam 的 m 和 v 各 4。
# 70 亿参数、8 张卡，ZeRO / FSDP 把其中几项切到 8 张卡上，每张卡要放多少（不含激活）：

# %%
# region memory
P, N = 7e9, 8
stages = {
    "数据并行（每张卡一整份）": (2, 2, 12),
    "ZeRO-1：切优化器状态": (2, 2, 12 / N),
    "ZeRO-2：再切梯度": (2, 2 / N, 12 / N),
    "ZeRO-3 / FSDP：再切参数": (2 / N, 2 / N, 12 / N),
}
memory = {}
for name, (w, g, o) in stages.items():
    memory[name] = [P * w / 1e9, P * g / 1e9, P * o / 1e9]
    print(f"{pad(name, 26)} 参数 {memory[name][0]:6.1f} GB  梯度 {memory[name][1]:6.1f} GB  优化器 {memory[name][2]:6.1f} GB  合计 {sum(memory[name]):6.1f} GB")
# endregion memory

# %% [markdown]
# ## 5. 激活重计算
#
# 反向传播要用前向的中间结果。把“为反向保存下来的张量”一共多少字节量出来（参数本身不算），
# 再用 `torch.utils.checkpoint` 包住每个 Block：前向时只存 Block 的输入，反向时把 Block 重算一遍。用一个 8 层、宽度 128 的模型：

# %%
# region recompute
big = replace(cfg, d_model=128, n_layers=8, n_heads=8)
torch.manual_seed(0)
model = TinyLLM(big)
x, y = train_ids[starts[0][:, None] + torch.arange(cfg.context)], train_ids[starts[0][:, None] + 1 + torch.arange(cfg.context)]
param_storage = {p.untyped_storage().data_ptr() for p in model.parameters()}

def forward(recompute):
    h = model.embed(x)
    for block in model.blocks:
        h = checkpoint(block, h, model.cos, model.sin, use_reentrant=False) if recompute else block(h, model.cos, model.sin)
    return F.cross_entropy((model.norm(h) @ model.embed.weight.T).flatten(0, 1), y.flatten())

def saved_bytes_and_grads(recompute):
    seen, total = set(), 0
    def pack(t):
        nonlocal total
        storage = t.untyped_storage()
        if storage.data_ptr() not in param_storage and storage.data_ptr() not in seen:   # 参数和重复的不算
            seen.add(storage.data_ptr())
            total += storage.nbytes()
        return t
    model.zero_grad()
    with torch.autograd.graph.saved_tensors_hooks(pack, lambda t: t):
        loss = forward(recompute)
    loss.backward()
    return total, [p.grad.clone() for p in model.parameters()]

plain, g1 = saved_bytes_and_grads(False)
ckpt, g2 = saved_bytes_and_grads(True)
print(f"{sum(p.numel() for p in model.parameters())} 个参数，batch {BATCH} × {cfg.context} 个 token")
print(f"为反向保存的张量：不重算 {plain / 2**20:.1f} MB，每个 Block 重算 {ckpt / 2**20:.1f} MB（{ckpt / plain:.0%}）")
print("梯度最大差：", max((a - b).abs().max().item() for a, b in zip(g1, g2)))
times = {}
for recompute in (False, True):
    t0 = time.time()
    for _ in range(5):
        model.zero_grad()
        forward(recompute).backward()
    times[recompute] = (time.time() - t0) / 5
print(f"每步用时：重算是不重算的 {times[True] / times[False]:.2f} 倍")
# endregion recompute

# %% [markdown]
# ## 6. 数据并行：每张卡算一份 batch，再把梯度平均
#
# 用 4 份 batch 模拟 4 张卡：每张卡在自己那 4 段上算梯度，然后 all-reduce（求平均）。和一张卡算整个 batch 比较：

# %%
# region data-parallel
torch.manual_seed(0)
model = TinyLLM(cfg)
x, y = train_ids[starts[0][:, None] + torch.arange(cfg.context)], train_ids[starts[0][:, None] + 1 + torch.arange(cfg.context)]
model(x, y)[1].backward()
full = [p.grad.clone() for p in model.parameters()]

ranks = []
for xs, ys in zip(x.chunk(4), y.chunk(4)):                     # 每张卡拿 4 段
    model.zero_grad()
    model(xs, ys)[1].backward()
    ranks.append([p.grad.clone() for p in model.parameters()])
averaged = [sum(r[i] for r in ranks) / 4 for i in range(len(full))]   # all-reduce：各卡梯度求平均
print("4 张卡平均后和整个 batch 的梯度最大差：", f"{max((a - b).abs().max().item() for a, b in zip(averaged, full)):.1e}")
n_params = sum(p.numel() for p in model.parameters())
for world in (4, 8):
    print(f"{world} 张卡、FP32 梯度：每步每张卡收发约 2·({world}-1)/{world} × {n_params * 4 / 2**20:.2f} MB = "
          f"{2 * (world - 1) / world * n_params * 4 / 2**20:.2f} MB（环形 all-reduce）")
# endregion data-parallel

# %% [markdown]
# ## 7. 张量并行：一个矩阵切到两张卡上
#
# SwiGLU 的 gate、up 按输出维（中间宽度）切成两半，down 按输入维切成两半。每张卡只算自己那一半，最后把两张卡的输出相加（all-reduce）：

# %%
# region tensor-parallel
ffn = model.blocks[0].ffn
h = torch.randn(BATCH, cfg.context, cfg.d_model)
with torch.no_grad():
    reference = ffn(h)
    half = ffn.gate.out_features // 2
    parts = []
    for r in range(2):                                         # 第 r 张卡
        cols = slice(r * half, (r + 1) * half)
        local = F.silu(h @ ffn.gate.weight[cols].T) * (h @ ffn.up.weight[cols].T)   # 列切分：各算一半中间维
        parts.append(local @ ffn.down.weight[:, cols].T)       # 行切分：各得一份“部分和”
    combined = parts[0] + parts[1]                             # all-reduce：相加
print(f"中间宽度 {ffn.gate.out_features}，每张卡 {half}；两卡相加后和单卡的最大差 {(combined - reference).abs().max():.1e}")
print(f"每个前馈层前向要 all-reduce 一次，大小 = batch × 长度 × 宽度 = {combined.numel()} 个数")
# endregion tensor-parallel

# %%
scale_log = {
    "lrs": list(LRS), "sweep": sweep,
    "mup_lrs": list(MUP_LRS), "mup": {k: {str(d): v for d, v in rows.items()} for k, rows in mup.items()},
    "memory": memory, "recompute": {"plain_mb": plain / 2**20, "ckpt_mb": ckpt / 2**20, "time_ratio": times[True] / times[False]},
}
with open("large_model_stability_log.json", "w", encoding="utf-8") as f:
    json.dump(scale_log, f, ensure_ascii=False)
