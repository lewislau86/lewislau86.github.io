# %% [markdown]
# # 第 12 章：完整 TinyLLM
#
# 配套教案：https://lewislau86.github.io/tinyllm/tinyllm-model
#
# 从上到下运行即可（`python tinyllm-model.py`），CPU 上约两分钟（其中训练 300 步约一分半）。需要安装 PyTorch 和 `tokenizers`。
# 这个文件是本章代码的唯一来源：教案中的代码片段由 `# region 名字` / `# endregion 名字`
# 标记的区域直接引用，notebook 也由它生成（scripts/build-tinyllm-code.py）。
#
# 本章把第 4～11 章的零件装进同一个模型：字节级 BPE、带 RoPE 的因果注意力、SwiGLU、Pre-RMSNorm、
# 第 10 章的初始化、输入输出共享权重。再固定数据划分和评估口径，训练出后半本书的基线。

# %%
# region imports
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
# ## 1. 配置：一张表写下所有尺寸
#
# 模型的每个尺寸都集中在一个配置对象里，后面的 GPU 章只改这张表、不改模型代码。

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
print(cfg)

# %% [markdown]
# ## 2. 数据：固定的训练集和验证集
#
# 取统一唐诗语料的前 6000 首，按每首诗自带的 `split` 字段分开。验证集里的诗训练时一次也不看。

# %%
# region data
poems = load_poems(6000)
train_poems = [p["text"] for p in poems if p["split"] == "train"]
val_poems = [p["text"] for p in poems if p["split"] == "val"]
# endregion data
print("训练集：", len(train_poems), "首，", sum(map(len, train_poems)), "字")
print("验证集：", len(val_poems), "首，", sum(map(len, val_poems)), "字")

# %% [markdown]
# ## 3. 分词器：在训练集上训练字节级 BPE
#
# 和第 4 章同一个做法。只用训练集训练，免得验证集的信息漏进词表。

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

tokenizer = train_tokenizer(train_poems, cfg.vocab_size)
EOS = tokenizer.token_to_id("<eos>")
# endregion tokenizer

probe = "床前明月光"
print("词表大小：", tokenizer.get_vocab_size())
print(f"“{probe}” →", tokenizer.encode(probe).ids, tokenizer.encode(probe).tokens)

chars = sorted(set("".join(train_poems)))
single = sum(len(tokenizer.encode(c).ids) == 1 for c in chars)
print(f"训练集里不同的字：{len(chars)}，其中 {single} 个是单个 token，其余 {len(chars) - single} 个拆成字节")

# %% [markdown]
# ## 4. 组装模型
#
# 四个零件都来自前面各章，这里写成一个文件。先是 RoPE（第 7 章），预先算好每个位置的 cos/sin：

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

# %% [markdown]
# 注意力（第 6 章）和 SwiGLU 前馈层（第 8 章），线性层都不带偏置：

# %%
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

# %%
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

# %% [markdown]
# Block（第 9、11 章）：两次 Pre-RMSNorm、两次残差相加。

# %%
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

# %% [markdown]
# 整个模型：查表 → L 个 Block → 最终 RMSNorm → 输出层。输出层不另建矩阵，直接用嵌入表（第 5 章的权重共享）。
# 初始化照第 10 章：线性层 Xavier normal，嵌入标准差 `1/√d`，两个输出投影再乘 `1/√(2L)`。

# %%
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

torch.manual_seed(0)
model = TinyLLM(cfg)

# %% [markdown]
# ## 5. 体检一：参数量先估再数
#
# 第 9 章说一个 Block 约 12d² 个参数：注意力 4d²，SwiGLU 3 × d × 8d/3 = 8d²，再加两个归一化的 2d。
# 嵌入表 V × d，输出层共享它，不另算；最后的 RMSNorm 再加 d。

# %%
# region param-count
d, L, V = cfg.d_model, cfg.n_layers, cfg.vocab_size
hidden = 8 * d // 3
predicted = V * d + L * (4 * d * d + 3 * d * hidden + 2 * d) + d
actual = sum(p.numel() for p in model.parameters())
print("估算：", predicted, "  实数：", actual)
for name, part in [("嵌入表（兼输出层）", model.embed), ("全部 Block", model.blocks), ("最终 RMSNorm", model.norm)]:
    n = sum(p.numel() for p in part.parameters())
    print(f"  {name:<12}{n:>9,}  {n / actual:6.1%}")
# endregion param-count

# %% [markdown]
# ## 6. 体检二：沿着数据流看形状

# %%
# region shapes
x = torch.tensor([tokenizer.encode("床前明月光，疑是地上霜。").ids])
print("输入 token ID   ", tuple(x.shape))
h = model.embed(x)
print("查表之后        ", tuple(h.shape))
for i, block in enumerate(model.blocks):
    h = block(h, model.cos, model.sin)
    print(f"第 {i + 1} 个 Block 之后", tuple(h.shape))
logits = model.norm(h) @ model.embed.weight.T
print("输出 logits     ", tuple(logits.shape))
# endregion shapes

# %% [markdown]
# ## 7. 体检三：还没训练时，三件应该成立的事
#
# 1. 随机模型对下一个 token 一无所知，交叉熵应接近“均匀乱猜”的 ln V（logits 有一点起伏，会略高一些）；
# 2. 因果：改动后面的 token，前面位置的 logits 不能变；
# 3. 共享权重：整个模型里只有一张 V × d 的矩阵。

# %%
# region health
with torch.no_grad():
    logits0, loss0 = model(x[:, :-1], x[:, 1:])
print(f"初始损失 {loss0.item():.3f}   ln V = {math.log(V):.3f}   logits 标准差 {logits0.std().item():.3f}")

with torch.no_grad():
    y = x.clone()
    y[0, -1] = (y[0, -1] + 1) % V                            # 只改最后一个 token
    diff = (model(x)[0, :-1] - model(y)[0, :-1]).abs().max().item()
print("改最后一个 token，前面位置 logits 的最大变化：", diff)
print("形状为 (V, d) 的参数张量：", sum(p.shape == (V, d) for p in model.parameters()), "个（只有嵌入表，输出层没有另建矩阵）")
# endregion health

# %% [markdown]
# ## 8. 固定评估口径
#
# 训练集和验证集各自拼成一条长 token 流，每首诗之后接一个 `<eos>`。
# 训练从流里随机切窗口，切哪几段由一个单独的随机数生成器事先排好（batch 计划），后面换结构、换超参数时，大家吃的是同一批数据。
# 验证把整条验证流切成不重叠的窗口，每个位置预测下一个 token，全部算一遍取平均，结果不带随机性。
# 同时把“每 token 损失”换算成“每个字多少比特”，不同分词器之间也能比较。

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

print("训练流", len(train_ids), "个 token；验证流", len(val_ids), "个 token")
print(f"验证集平均每个字 {tokens_per_char:.3f} 个 token")
nats, bpc = evaluate(model)
print(f"训练前验证损失 {nats:.3f} nats/token，{bpc:.2f} 比特/字")

# %% [markdown]
# ## 9. 训练基线
#
# AdamW（第 16 章），学习率固定 3e-3；矩阵权重做 weight decay，归一化的权重不做。每步按全局范数把梯度裁到 1（第 20 章）。
# 学习率调度、正则化、混合精度这些都先不加，后面各章逐项在这个基线上对照。

# %%
# region train
steps, batch_size = 300, 32
plan = torch.Generator().manual_seed(1234)                    # batch 计划：只由这个生成器决定
starts = torch.randint(0, len(train_ids) - cfg.context - 1, (steps, batch_size), generator=plan)

decay = [p for p in model.parameters() if p.dim() >= 2]
no_decay = [p for p in model.parameters() if p.dim() < 2]
optimizer = torch.optim.AdamW([{"params": decay, "weight_decay": 0.1},
                               {"params": no_decay, "weight_decay": 0.0}], lr=3e-3)

log = {"step": [], "loss": [], "val_step": [], "val_loss": [], "val_bpc": []}
t0 = time.time()
for step in range(steps):
    if step % 50 == 0:
        nats, bpc = evaluate(model)
        log["val_step"].append(step); log["val_loss"].append(nats); log["val_bpc"].append(bpc)
        print(f"step {step:3d}  验证损失 {nats:.3f}  ({bpc:.2f} 比特/字)")
    idx = starts[step][:, None] + torch.arange(cfg.context + 1)
    xb, yb = train_ids[idx[:, :-1]], train_ids[idx[:, 1:]]
    _, loss = model(xb, yb)
    optimizer.zero_grad(set_to_none=True)
    loss.backward()
    torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
    optimizer.step()
    log["step"].append(step); log["loss"].append(loss.item())
nats, bpc = evaluate(model)
log["val_step"].append(steps); log["val_loss"].append(nats); log["val_bpc"].append(bpc)
print(f"step {steps:3d}  验证损失 {nats:.3f}  ({bpc:.2f} 比特/字)")
# endregion train
train_seconds = time.time() - t0
print(f"训练 {steps} 步用时约 {train_seconds:.0f} 秒")

# %% [markdown]
# 最后 50 步的平均训练损失和最终验证损失放在一起看：两者接近，说明这个预算下还没有过拟合，模型还在学。

# %%
recent = sum(log["loss"][-50:]) / 50
print(f"最后 50 步平均训练损失 {recent:.3f}，最终验证损失 {log['val_loss'][-1]:.3f}")

# %% [markdown]
# ## 10. 让它写几首
#
# 从 `<eos>`（上一首诗结束）开始，按温度 0.8 逐个采样，直到再次生成 `<eos>`。
# 再逐句核对：生成的句子有多少原样出现在训练集里？

# %%
# region generate
@torch.no_grad()
def generate(model, max_new_tokens=60, temperature=0.8, generator=None):
    model.eval()
    idx = torch.tensor([[EOS]])
    for _ in range(max_new_tokens):
        logits = model(idx[:, -cfg.context:])[:, -1, :] / temperature
        next_id = torch.multinomial(F.softmax(logits, dim=-1), 1, generator=generator)
        if next_id.item() == EOS:
            break
        idx = torch.cat([idx, next_id], dim=1)
    model.train()
    return tokenizer.decode(idx[0, 1:].tolist())
# endregion generate

sampler = torch.Generator().manual_seed(7)
train_lines = {s for t in train_poems for s in t.replace("。", "，").split("，") if s}
for _ in range(4):
    poem = generate(model, generator=sampler)
    lines = [s for s in poem.replace("。", "，").split("，") if s]
    seen = sum(s in train_lines for s in lines)
    print(poem, f"  （{seen}/{len(lines)} 句原样见于训练集）")

# %% [markdown]
# ## 11. 记下基线
#
# 后面各章改动任何一处（数据、损失、学习率、正则化、精度……），都和这一行比。

# %%
# region baseline
baseline = {"params": actual, "vocab": V, "d_model": d, "n_layers": L, "context": cfg.context,
            "train_tokens": len(train_ids), "steps": steps, "batch": batch_size,
            "val_loss": round(log["val_loss"][-1], 3), "val_bpc": round(log["val_bpc"][-1], 2)}
print(baseline)
# endregion baseline

# %%
import json
log["shapes"] = {"batch": 1, "tokens": int(x.shape[1]), "d_model": d, "vocab": V, "n_layers": L,
                 "n_heads": cfg.n_heads, "ffn_hidden": hidden}
log["baseline"] = baseline
with open("tinyllm_model_log.json", "w", encoding="utf-8") as f:
    json.dump(log, f)
