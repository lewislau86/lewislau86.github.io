# %% [markdown]
# # 第 15 章：语言模型目标函数
#
# 配套教案：https://lewislau86.github.io/tinyllm/language-model-loss
#
# 从上到下运行即可（`python language-model-loss.py`），CPU 上约两分钟（其中重训第 12 章的基线约一分半）。
# 需要安装 PyTorch 和 `tokenizers`。
# 这个文件是本章代码的唯一来源：教案中的代码片段由 `# region 名字` / `# endregion 名字`
# 标记的区域直接引用，notebook 也由它生成（scripts/build-tinyllm-code.py）。
#
# 本章拆开第 12 章打印的那个数：验证损失 5.579。它是怎么算出来的、说明了什么、哪些地方会算错。

# %%
# region imports
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
# ## 0. 先把第 12 章的基线原样训练出来
#
# 下面几格是第 12 章的配置、数据、分词器、模型、评估口径和训练循环，一字不改地复制过来。
# 随机种子、batch 计划都一样，所以最后的验证损失应该和第 12 章逐位相同：5.579。

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

torch.manual_seed(0)
model = TinyLLM(cfg)

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

# %% [markdown]
# ## 1. 错位：一段 65 个 token，出 64 道题
#
# 训练时从 token 流里切一段，输入是前 64 个，目标是往后错一位的 64 个。看第一首验证诗的开头：

# %%
# region shift
window = val_ids[:9]
x, y = window[:-1], window[1:]
show = lambda ids: " ".join("<eos>" if i == EOS else tokenizer.decode([i]) or "?" for i in ids.tolist())
print("输入 x：", show(x))
print("目标 y：", show(y))
# endregion shift

# %% [markdown]
# ## 2. 从“整首诗的概率”到“每个 token 的平均损失”
#
# 模型给一首诗的概率，是每一步“猜中下一个 token”的概率连乘。拿第一首验证诗，从 `<eos>`（上一首刚结束）开始，
# 逐个 token 看模型给正确答案的概率。字节级 BPE 会把生僻字拆成几个 token，这里按字合并显示：一个字的概率是它几个 token 概率的乘积。

# %%
# region poem-prob
poem = val_poems[0]
ids = torch.tensor([EOS] + tokenizer.encode(poem).ids + [EOS])
model.eval()
with torch.no_grad():
    logp = F.log_softmax(model(ids[None, :-1])[0], dim=-1)
token_nll = -logp.gather(-1, ids[1:, None])[:, 0]                    # 每个 token：-log p(正确答案)

def by_char(ids, nll):
    """把字节 token 拼回完整的字：一个字的 -log p 是它几个 token 的 -log p 之和。"""
    out, buf, acc = [], [], 0.0
    for i, v in zip(ids.tolist(), nll.tolist()):
        buf.append(i); acc += v
        text = "<eos>" if i == EOS else tokenizer.decode(buf)
        if "�" not in text:
            out.append((text, acc, len(buf))); buf, acc = [], 0.0
    return out

chars = by_char(ids[1:], token_nll)
print(poem)
print("  ".join(f"{t}{'*' if k > 1 else ''} {v:.2f}" for t, v, k in chars[:13]))
print(f"{len(chars)} 个字（含 <eos>），{len(token_nll)} 个 token；带 * 的字被拆成了几个 token")
# endregion poem-prob

# %% [markdown]
# 整首诗的概率是这 48 个概率的乘积。先猜一下：用 float32 乘出来是多少？

# %%
# region underflow
p = token_nll.neg().exp()
print("float32 连乘：", torch.prod(p.float()).item())
print("float64 连乘：", torch.prod(p.double()).item())
print("对数相加：    ", -token_nll.sum().item(), "（以 e 为底）")
print("每 token 平均：", token_nll.mean().item())
# endregion underflow

# %% [markdown]
# ## 3. 交叉熵内部：先 log-softmax，再取正确答案那一项
#
# `F.cross_entropy` 接收原始 logits。自己照公式写 softmax 再取对数，logits 一大就会出事：

# %%
# region naive-softmax
z = torch.tensor([1000.0, 0.0, -1000.0])                          # 三个候选的 logits，第 0 个是正确答案
naive = -torch.log(z.exp() / z.exp().sum())[0]
stable = -(z[0] - torch.logsumexp(z, dim=0)) + 0.0                 # + 0.0 只是让 -0.0 显示成 0.0
print("先 softmax 再取 log：", naive.item())
print("log-sum-exp 写法：   ", stable.item())
print("F.cross_entropy：     ", F.cross_entropy(z[None], torch.tensor([0])).item())
# endregion naive-softmax

# %% [markdown]
# 照 log-sum-exp 的写法，在整个验证集上手算一遍，和第 12 章的 `evaluate` 对一对：

# %%
# region manual-ce
T = cfg.context
n = (len(val_ids) - 1) // T * T
xs, ys = val_ids[:n].view(-1, T), val_ids[1:n + 1].view(-1, T)
with torch.no_grad():
    logits = model(xs)                                               # (窗口数, 64, 4096)
nll = torch.logsumexp(logits, dim=-1) - logits.gather(-1, ys[..., None])[..., 0]
print("手算：    ", nll.mean().item())
print("evaluate：", evaluate(model)[0])
print("一共", nll.numel(), "道题，总损失", round(nll.sum().item(), 1), "nats")
# endregion manual-ce

# %% [markdown]
# 梯度也很简单：对 logits 求导，正好是“softmax 概率减去正确答案的独热向量”，再除以题数。用 autograd 核对一个位置：

# %%
# region grad-check
z1 = logits[0, :2].clone().requires_grad_()                        # 只取两道题
F.cross_entropy(z1, ys[0, :2]).backward()
expected = (F.softmax(z1.detach(), dim=-1) - F.one_hot(ys[0, :2], cfg.vocab_size)) / 2
print("autograd 与公式的最大差：", (z1.grad - expected).abs().max().item())
print("正确答案那一格的梯度：", z1.grad[0, ys[0, 0]].item(), "  其余 4095 格加起来：", (z1.grad[0].sum() - z1.grad[0, ys[0, 0]]).item())
# endregion grad-check

# %% [markdown]
# ## 4. 同一个数的几种读法
#
# nats/token、比特/token、比特/字、困惑度，说的都是一件事。

# %%
# region units
loss = nll.mean().item()
per_char = loss * tokens_per_char                                    # 第 12 章的换算：每字平均 0.954 个 token
print(f"每 token  {loss:.3f} nats   = {loss / math.log(2):.2f} 比特")
print(f"每字      {per_char:.3f} nats   = {per_char / math.log(2):.2f} 比特（每字 {tokens_per_char:.3f} 个 token）")
print(f"困惑度    e^{loss:.3f} = {math.exp(loss):.0f}（每个 token）；每字 2^{per_char / math.log(2):.2f} = {2 ** (per_char / math.log(2)):.0f}")
print(f"均匀乱猜  ln {cfg.vocab_size} = {math.log(cfg.vocab_size):.3f} nats，困惑度 {cfg.vocab_size}")
probs = (-nll).exp()
print(f"正确答案的平均概率 {probs.mean().item():.3f}，几何平均 {math.exp(-loss):.4f}")
# endregion units

# %% [markdown]
# ## 5. 平均的分母
#
# 第 12 章把诗拼成流，每个位置都是真题。逐首补齐（第 14 章）时，batch 里会有 `<pad>`。
# 取 4 首绝句、4 首律诗（都是验证诗，长短交替排列）补齐成一个 batch，用三种方式求平均：

# %%
# region padding
PAD = tokenizer.token_to_id("<pad>")
short = [t for t in val_poems if len(t) == 24][:4]
long = [t for t in val_poems if len(t) == 48][:4]
batch_poems = [t for pair in zip(short, long) for t in pair]            # 绝句、律诗交替
seqs = [[EOS] + tokenizer.encode(t).ids + [EOS] for t in batch_poems]
L = max(map(len, seqs))
batch = torch.tensor([s + [PAD] * (L - len(s)) for s in seqs])
bx, by = batch[:, :-1], batch[:, 1:].clone()
real = by != PAD
with torch.no_grad():
    blog = model(bx)
per_pos = F.cross_entropy(blog.flatten(0, 1), by.flatten(), reduction="none").view(by.shape)

print("每首的 token 数：", real.sum(1).tolist(), f"  <pad> 占 {1 - real.float().mean().item():.0%}")
print(f"① 只算真题、按 token 平均（ignore_index）：{F.cross_entropy(blog.flatten(0, 1), by.masked_fill(~real, -100).flatten()).item():.3f}")
print(f"② <pad> 也当题目算进去：                 {per_pos.mean().item():.3f}")
print(f"③ 先每首平均，再 8 首平均：              {((per_pos * real).sum(1) / real.sum(1)).mean().item():.3f}")
# endregion padding

# %% [markdown]
# 梯度累积时，分母更容易放错：把这 8 首拆成 4 个 micro-batch，每个 2 首，各自求平均再相加除以 4，
# 和 8 首一起按 token 平均，梯度一样吗？

# %%
# region accumulation
def grads(loss_fn):
    model.zero_grad(set_to_none=True)
    loss_fn().backward()
    return torch.cat([p.grad.flatten() for p in model.parameters()])

target = by.masked_fill(~real, -100)
def full():                                                          # 8 首一起：总损失 ÷ 全部真题数
    return F.cross_entropy(model(bx).flatten(0, 1), target.flatten())
def mean_of_means():                                                 # 每个 micro-batch 各自平均，再平均
    return sum(F.cross_entropy(model(bx[i:i + 2]).flatten(0, 1), target[i:i + 2].flatten()) for i in range(0, 8, 2)) / 4
def sum_then_divide():                                               # 各自求和，最后除以全部真题数
    return sum(F.cross_entropy(model(bx[i:i + 2]).flatten(0, 1), target[i:i + 2].flatten(), reduction="sum")
               for i in range(0, 8, 2)) / real.sum()

cos = lambda a, b: F.cosine_similarity(a.double(), b.double(), dim=0).item()
accum_log = []
for label, order in [("原顺序", list(range(8))), ("按长度排序后再分", sorted(range(8), key=lambda i: real[i].sum().item()))]:
    bx, by, real, target = bx[order], by[order], real[order], target[order]
    g_full, g_mom, g_std = grads(full), grads(mean_of_means), grads(sum_then_divide)
    counts = [real[i:i + 2].sum().item() for i in range(0, 8, 2)]
    weights = [real.sum().item() / (4 * c) for c in counts]          # 各自平均再平均时，每道题的权重是一起算时的几倍
    print(f"{label}：每个 micro-batch 的真题数 {counts}，每道题的权重是一起算时的 {[round(w, 2) for w in weights]} 倍")
    print(f"  各自平均再平均   与一起算的梯度：余弦 {cos(g_full, g_mom):.4f}，范数之比 {g_mom.norm() / g_full.norm():.3f}")
    print(f"  各自求和再除总数 与一起算的梯度：最大差 {(g_std - g_full).abs().max().item():.1e}")
    accum_log.append({"label": label, "counts": counts, "weights": weights, "cos": cos(g_full, g_mom)})
model.zero_grad(set_to_none=True)
# endregion accumulation

# %% [markdown]
# ## 6. 哪些位置该算：`<eos>` 一定要算
#
# 验证流里，`<eos>` 是目标的位置有多少，模型猜得怎么样？它在绝句（4 句后）和律诗（8 句后）的句号之后，给“结束”多大概率？

# %%
# region eos
is_eos = ys == EOS
print(f"<eos> 题目 {is_eos.sum().item()} 道，平均损失 {nll[is_eos].mean().item():.3f}")
probs_all = F.softmax(logits, dim=-1)
STOP = tokenizer.encode("。").ids[0]                                  # 字节级 BPE 的 token 名不是原字，按编码取编号
after_stop = xs == STOP
p_eos = probs_all[..., EOS][after_stop]
ends = is_eos[after_stop]
print(f"句号之后：真结束时给 <eos> 的平均概率 {p_eos[ends].mean().item():.3f}，没结束时 {p_eos[~ends].mean().item():.3f}")
# endregion eos

# %% [markdown]
# ## 7. 平均数掩盖了什么
#
# 把验证集的 12224 道题按目标分成四类：标点（，。）、`<eos>`、每句的第一个字（前一个 token 是标点或 `<eos>`）、句中的字。

# %%
# region breakdown
PUNCT = {tokenizer.encode("，").ids[0], tokenizer.encode("。").ids[0]}
yf, xf, nf = ys.flatten(), xs.flatten(), nll.flatten()
kind = torch.full_like(yf, 3)                                         # 3：句中的字
kind[torch.isin(xf, torch.tensor(sorted(PUNCT | {EOS})))] = 2         # 2：每句第一个字
kind[torch.isin(yf, torch.tensor(sorted(PUNCT)))] = 0                 # 0：标点
kind[yf == EOS] = 1                                                   # 1：<eos>
names = ["标点", "<eos>", "句首的字", "句中的字"]
breakdown = []
for k, name in enumerate(names):
    m = kind == k
    row = (name, m.float().mean().item(), nf[m].mean().item(), nf[m].sum().item() / nf.sum().item())
    breakdown.append(row)
    print(f"{name:<6} 占题目 {row[1]:5.1%}   平均损失 {row[2]:.3f}   占总损失 {row[3]:5.1%}")
print(f"去掉标点和 <eos>，只看字：{nf[kind >= 2].mean().item():.3f}")
# endregion breakdown

# %% [markdown]
# ## 8. 模型给的概率可信吗
#
# 交叉熵奖励“说得准”的概率：模型说 30% 的事，最好真的有大约 30% 会发生。把验证集每道题按模型最有把握的那个答案的概率分组，
# 看每组实际猜中了多少：

# %%
# region calibration
conf, pred = probs_all.max(dim=-1)
hit = (pred == ys).float()
edges = torch.linspace(0, 1, 11)
calib = []
for lo, hi in zip(edges[:-1], edges[1:]):
    m = (conf >= lo) & (conf < hi) if hi < 1 else (conf >= lo)
    if m.any():
        calib.append((lo.item(), m.sum().item(), conf[m].mean().item(), hit[m].mean().item()))
        print(f"把握 {lo:.1f}～{hi:.1f}：{m.sum().item():>5} 道   平均把握 {conf[m].mean().item():.2f}   实际猜中 {hit[m].mean().item():.2f}")
ece = sum(n * abs(c - a) for _, n, c, a in calib) / conf.numel()
print(f"总体猜中 {hit.mean().item():.1%}；按题数加权的平均偏差（ECE）{ece:.3f}")
# endregion calibration

# %% [markdown]
# 两种常见的改法。label smoothing 把目标从“独热”改成“正确答案 1-ε，其余平分 ε”；z-loss 额外惩罚 log-sum-exp 的平方，防止 logits 整体漂移。
# 先看 label smoothing 会让损失的下限变成多少，再看基线模型的 log-sum-exp 有多大：

# %%
# region variants
eps, V = 0.1, cfg.vocab_size
q_hit, q_other = 1 - eps + eps / V, eps / V                          # 平滑后的目标分布
floor = -(q_hit * math.log(q_hit) + (V - 1) * q_other * math.log(q_other))
print(f"label smoothing ε={eps}：完美模型的损失下限 {floor:.3f}（不平滑时是 0）")
print(f"基线在验证集上：普通交叉熵 {nll.mean().item():.3f}，按 ε={eps} 平滑算 "
      f"{F.cross_entropy(logits.flatten(0, 1), ys.flatten(), label_smoothing=eps).item():.3f}")
log_z = torch.logsumexp(logits, dim=-1)
print(f"log-sum-exp：平均 {log_z.mean().item():.2f}，最大 {log_z.max().item():.2f}；z-loss（系数 1e-4）= {1e-4 * (log_z ** 2).mean().item():.4f}")
# endregion variants

# %%
loss_log = {
    "poem": poem, "chars": [(t, v) for t, v, _ in chars],
    "units": {"nats": loss, "tokens": nll.numel(), "per_char": per_char, "total": nll.sum().item(), "vocab": cfg.vocab_size},
    "breakdown": breakdown, "calibration": calib, "ece": ece, "accumulation": accum_log,
    "padding": {"lengths": real.sum(1).tolist()},
}
with open("language_model_loss.json", "w", encoding="utf-8") as f:
    json.dump(loss_log, f, ensure_ascii=False)
