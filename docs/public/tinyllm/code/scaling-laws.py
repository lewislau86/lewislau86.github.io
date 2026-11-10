# %% [markdown]
# # 第 24 章：缩放定律与算力预算
#
# 配套教案：https://lewislau86.github.io/tinyllm/scaling-laws
#
# 从上到下运行即可（`python scaling-laws.py`），CPU 上约两分钟（7 个宽度，每个宽度训练一条主干、分叉出 3 个预算）。
# 需要安装 PyTorch 和 `tokenizers`。
# 这个文件是本章代码的唯一来源：教案中的代码片段由 `# region 名字` / `# endregion 名字`
# 标记的区域直接引用，notebook 也由它生成（scripts/build-tinyllm-code.py）。
#
# 第 23 章回答了“给定模型和数据，怎么训”。本章回答更早的一个问题：手里有一份算力，模型该做多大、该训多少 token？

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
from torch.utils.flop_counter import FlopCounterMode
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
# 模型代码和第 17、23 章的代理模型相同（词表 1024、2 层、每个注意力头 16 维），只是宽度从 16 到 128 取 7 档。
# 训练数据换成统一语料的全部训练诗，让大多数训练不必重复数据；分词器和验证集仍用前 6000 首，和第 17、23 章一致。

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
WIDTHS = [16, 24, 32, 48, 64, 96, 128]
BATCH, WARMUP = 16, 10

def config_for(d):
    return TinyConfig(vocab_size=1024, d_model=d, n_layers=2, n_heads=d // 16)

def lr_for(d):
    """标准参数化下，宽度越大最佳学习率越小（第 25 章）；这里按 1/宽度 缩放，宽度 64 时是第 17 章的 1e-2。"""
    return 1e-2 * 64 / d
# endregion proxy
cfg = config_for(64)

# %%
# region data
poems = load_poems(17439)                                              # 统一语料的全部 17,439 首
first = poems[:6000]                                                    # 第 17、23 章用的前 6000 首
train_poems = [p["text"] for p in first if p["split"] == "train"]     # 分词器只在这部分上训练
val_poems = [p["text"] for p in first if p["split"] == "val"]         # 验证集与第 17、23 章相同
all_train = [p["text"] for p in poems if p["split"] == "train"]       # 训练流：全部训练诗
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

train_ids, val_ids = to_stream(all_train), to_stream(val_poems)

@torch.no_grad()
def evaluate(model, ids=val_ids, T=cfg.context, batch=64):
    model.eval()
    n = (len(ids) - 1) // T * T
    xs, ys = ids[:n].view(-1, T), ids[1:n + 1].view(-1, T)
    total = sum(F.cross_entropy(model(xs[i:i + batch]).flatten(0, 1), ys[i:i + batch].flatten(), reduction="sum").item()
                for i in range(0, len(xs), batch))
    model.train()
    return total / ys.numel()                                         # 每 token 的 nats
# endregion eval-protocol

print(f"训练流 {len(train_ids):,} 个 token（{len(all_train)} 首诗）；验证流 {len(val_ids):,} 个 token")

# %% [markdown]
# ## 1. 先算账：一步训练要多少次浮点运算
#
# 7 个宽度的参数量，以及用 PyTorch 的 FlopCounterMode 实测一步（前向 + 反向，16 段 × 64 个 token）的浮点运算次数，
# 和“6 × 参数量 × token 数”比一比。

# %%
# region params
def count_params(model):
    total = sum(p.numel() for p in model.parameters())
    return total, total - model.embed.weight.numel()                 # (全部, 不含词嵌入表)

PARAMS = {d: count_params(TinyLLM(config_for(d))) for d in WIDTHS}
for d in WIDTHS:
    total, no_emb = PARAMS[d]
    print(f"宽度 {d:3d}：参数 {total:7,}，其中词嵌入表 {total - no_emb:7,}（{(total - no_emb) / total:4.0%}）")
# endregion params

# %%
# region flops
x = train_ids[:BATCH * 64].view(BATCH, 64)
y = train_ids[1:BATCH * 64 + 1].view(BATCH, 64)
tokens = x.numel()
FLOPS = {}
for d in (32, 64, 128):
    model = TinyLLM(config_for(d))
    with FlopCounterMode(display=False) as counter:
        _, loss = model(x, y)
        loss.backward()
    measured = FLOPS[d] = counter.get_total_flops()
    total, no_emb = PARAMS[d]
    print(f"宽度 {d:3d}：实测 {measured:.3e}   6×全部参数×token {6 * total * tokens:.3e}（比值 {measured / (6 * total * tokens):.4f}）"
          f"   6×不含嵌入×token {6 * no_emb * tokens:.3e}（比值 {measured / (6 * no_emb * tokens):.2f}）")
# endregion flops

# %% [markdown]
# ## 2. 一条主干，多个预算
#
# 每个宽度只训练一条主干：warmup 10 步后学习率保持不变（WSD 的稳定段）。要知道“总共训练 s 步”的结果时，
# 在第 0.8s 步把主干复制一份，让副本在剩下的 0.2s 步里把学习率线性降到 0，再测验证损失；主干接着往下走。
# 这和单独跑一次长度为 s 的 WSD 训练完全一样（同一组 batch、同样的学习率曲线），但前 0.8s 步只花了一次。

# %%
# region trunk
PLAN = torch.randint(0, len(train_ids) - cfg.context - 1, (2000, BATCH), generator=torch.Generator().manual_seed(1234))

class Trunk:
    def __init__(self, d, seed=0):
        torch.manual_seed(seed)                                       # 种子只决定初始参数，batch 计划所有宽度共用
        self.d, self.lr, self.step = d, lr_for(d), 0
        self.model = TinyLLM(config_for(d))
        decay = [p for p in self.model.parameters() if p.dim() >= 2]
        no_decay = [p for p in self.model.parameters() if p.dim() < 2]
        self.opt = torch.optim.AdamW([{"params": decay, "weight_decay": 0.1},
                                      {"params": no_decay, "weight_decay": 0.0}], lr=self.lr)

    def advance(self, until, lr_fn):
        while self.step < until:
            for group in self.opt.param_groups:
                group["lr"] = lr_fn(self.step)
            idx = PLAN[self.step][:, None] + torch.arange(cfg.context + 1)
            _, loss = self.model(train_ids[idx[:, :-1]], train_ids[idx[:, 1:]])
            self.opt.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(self.model.parameters(), 1.0)
            self.opt.step()
            self.step += 1

    def budget(self, steps):
        """“总共训练 steps 步”的结果：主干走到 0.8×steps，复制一份衰减完再测。返回 (衰减后, 不衰减直接测)。"""
        branch = int(0.8 * steps)
        self.advance(branch, lambda s: self.lr * min(1.0, (s + 1) / WARMUP))
        raw = evaluate(self.model)
        twin = copy.deepcopy(self)
        twin.advance(steps, lambda s: self.lr * (steps - s) / (steps - branch))
        return evaluate(twin.model), raw
# endregion trunk

# %% [markdown]
# ## 3. 同样的算力，怎么分
#
# 三档算力 C = 5e10、1e11、2e11 次浮点运算。每档里，每个宽度按 C = 6ND 算出能训练的 token 数 D，再换成步数。
# 宽度小的模型训练得久，宽度大的训练得短。（单个种子；第 23 章在同一个代理模型上量过，换种子带来的标准差约 0.018。）

# %%
# region grid
BUDGETS = [5e10, 1e11, 2e11]
TOKENS_PER_STEP = BATCH * cfg.context
runs = []
t0 = time.time()
for d in WIDTHS:
    N = PARAMS[d][0]
    trunk = Trunk(d)
    for C in BUDGETS:
        steps = round(C / (6 * N * TOKENS_PER_STEP))
        decayed, raw = trunk.budget(steps)
        runs.append({"d": d, "N": N, "C": C, "steps": steps, "D": steps * TOKENS_PER_STEP, "loss": decayed, "raw": raw})
    print(f"宽度 {d:3d}（N = {N:7,}）：" + "   ".join(
        f"{r['steps']:4d} 步 {r['loss']:.3f}" for r in runs[-len(BUDGETS):]))
print(f"一共 {time.time() - t0:.0f} 秒；最长的一次训练读了 {max(r['D'] for r in runs) / len(train_ids):.1f} 遍训练流")
# endregion grid

# %% [markdown]
# 每一档里，验证损失随参数量先降后升。在最低点附近，对 log N 拟合一条抛物线，抛物线的最低点就是这一档的最优参数量。

# %%
# region isoflop
def fit_parabola(points):
    """在最低点左右各取两个点（不够就取有的），拟合 loss = a·(ln N)² + b·ln N + c。
    返回最低点的 N、最低点的损失，以及这条抛物线本身（给定 N 算损失）。"""
    points = sorted(points, key=lambda r: r["N"])
    i = min(range(len(points)), key=lambda k: points[k]["loss"])
    chosen = points[max(0, i - 2):i + 3]
    x = torch.tensor([math.log(r["N"]) for r in chosen], dtype=torch.float64)
    y = torch.tensor([r["loss"] for r in chosen], dtype=torch.float64)
    a, b, c = torch.linalg.lstsq(torch.stack([x * x, x, torch.ones_like(x)], 1), y[:, None]).solution[:, 0].tolist()
    best = -b / (2 * a)
    curve = lambda N: a * math.log(N) ** 2 + b * math.log(N) + c
    return math.exp(best), curve(math.exp(best)), curve

def power_fit(xs, ys):
    """在对数坐标上拟合直线 ln y = k·ln x + b，返回 (k, b)。"""
    x = torch.tensor([math.log(v) for v in xs], dtype=torch.float64)
    y = torch.tensor([math.log(v) for v in ys], dtype=torch.float64)
    k, b = torch.linalg.lstsq(torch.stack([x, torch.ones_like(x)], 1), y[:, None]).solution[:, 0].tolist()
    return k, b

optima = []
for C in BUDGETS:
    N_opt, loss_opt, curve = fit_parabola([r for r in runs if r["C"] == C])
    D_opt = C / (6 * N_opt)
    best_run = min((r for r in runs if r["C"] == C), key=lambda r: r["loss"])
    optima.append({"C": C, "N": N_opt, "D": D_opt, "loss": loss_opt, "curve": curve})
    print(f"C = {C:.1e}：实测最好的是宽度 {best_run['d']}；抛物线最低点 N = {N_opt:,.0f}，D = {D_opt:,.0f}，"
          f"每个参数 {D_opt / N_opt:.1f} 个 token，损失 {loss_opt:.3f}")
k_N, _ = power_fit(BUDGETS, [o["N"] for o in optima])
k_D, _ = power_fit(BUDGETS, [o["D"] for o in optima])
print(f"最优参数量 ∝ C^{k_N:.2f}，最优 token 数 ∝ C^{k_D:.2f}")
# endregion isoflop

# %% [markdown]
# ## 4. 外推：用小预算预测大预算
#
# 只用前两档的数据，预测第三档（算力翻倍）的结果，再和实测对照。两种做法：
# 一是把前两档的最优参数量连成一条直线，往外延；二是拟合 L(N, D) = E + A/N^α + B/D^β，再在第三档上求最低点。

# %%
# region extrapolate
known = [r for r in runs if r["C"] < BUDGETS[-1]]
k2, b2 = power_fit(BUDGETS[:2], [o["N"] for o in optima[:2]])
N_trend = math.exp(k2 * math.log(BUDGETS[-1]) + b2)
print(f"做法一：前两档的趋势外推，第三档的最优 N ≈ {N_trend:,.0f}（实测抛物线 {optima[-1]['N']:,.0f}）")

def fit_law(points):
    """最小二乘拟合 L = E + A/N^α + B/D^β。少于 60 步的训练里 warmup 和衰减占了大半，不参与拟合。"""
    points = [r for r in points if r["steps"] >= 60]
    N = torch.tensor([r["N"] for r in points], dtype=torch.float64)
    D = torch.tensor([r["D"] for r in points], dtype=torch.float64)
    L = torch.tensor([r["loss"] for r in points], dtype=torch.float64)
    best = None
    for E0 in (1.0, 2.0, 3.0, 4.0):                                    # 换几个起点，取误差最小的
        for a0 in (0.2, 0.4, 0.8):
            theta = torch.tensor([E0, math.log(20.0), a0, math.log(50.0), a0], dtype=torch.float64, requires_grad=True)
            opt = torch.optim.LBFGS([theta], max_iter=500, line_search_fn="strong_wolfe")
            def closure():
                opt.zero_grad()
                E, logA, alpha, logB, beta = theta
                pred = E + torch.exp(logA - alpha * N.log()) + torch.exp(logB - beta * D.log())
                err = ((pred - L) ** 2).mean()
                err.backward()
                return err
            for _ in range(5):
                err = opt.step(closure)
            if torch.isfinite(err) and (best is None or err.item() < best[0]):
                best = (err.item(), theta.detach().tolist())
    E, logA, alpha, logB, beta = best[1]
    return {"E": E, "A": math.exp(logA), "alpha": alpha, "B": math.exp(logB), "beta": beta, "rmse": best[0] ** 0.5}

def law(p, N, D):
    return p["E"] + p["A"] / N ** p["alpha"] + p["B"] / D ** p["beta"]

law_fit = fit_law(known)
print(f"做法二：拟合 {len([r for r in known if r['steps'] >= 60])} 个点：E = {law_fit['E']:.2f}，α = {law_fit['alpha']:.2f}，"
      f"β = {law_fit['beta']:.2f}，拟合误差 {law_fit['rmse']:.3f}")
for r in sorted((r for r in runs if r["C"] == BUDGETS[-1]), key=lambda r: r["N"]):
    print(f"   宽度 {r['d']:3d}：预测 {law(law_fit, r['N'], r['D']):.3f}   实测 {r['loss']:.3f}   差 {law(law_fit, r['N'], r['D']) - r['loss']:+.3f}")
grid_N = [math.exp(i / 200) for i in range(int(200 * math.log(1e4)), int(200 * math.log(1e6)))]
N_law = min(grid_N, key=lambda n: law(law_fit, n, BUDGETS[-1] / (6 * n)))
print(f"   第三档的最低点：N ≈ {N_law:,.0f}，预测损失 {law(law_fit, N_law, BUDGETS[-1] / (6 * N_law)):.3f}"
      f"（实测抛物线 N = {optima[-1]['N']:,.0f}，损失 {optima[-1]['loss']:.3f}）")
last = optima[-1]
print(f"   按做法二选 N ≈ {N_law:,.0f}，在第三档的实测抛物线上，损失只比最低点高 {last['curve'](N_law) - last['loss']:.3f}")
print(f"   实测抛物线的底很平：N 缩小或放大 1.5 倍，损失升高 {last['curve'](last['N'] / 1.5) - last['loss']:.3f}"
      f" / {last['curve'](last['N'] * 1.5) - last['loss']:.3f}")
# endregion extrapolate

# %% [markdown]
# ## 5. 两套结论为什么不同
#
# 同一批训练，换一种“记账”方式再求一遍最优参数量随算力的指数：像 Kaplan 等人那样，参数量和算力都不算词嵌入表。
# 再看另一个容易被忽略的口径：不做衰减，直接读主干在 0.8s 步时的验证损失，会差多少。

# %%
# region kaplan
def no_emb_of(N):
    """按 7 个宽度在对数坐标上插值，把“全部参数”换成“不含嵌入的参数”。"""
    pts = [(math.log(PARAMS[d][0]), math.log(PARAMS[d][1])) for d in WIDTHS]
    x = math.log(N)
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if x <= x1 or (x1, y1) == pts[-1]:
            return math.exp(y0 + (y1 - y0) * (x - x0) / (x1 - x0))

kaplan_N = [no_emb_of(o["N"]) for o in optima]
kaplan_C = [6 * n * o["D"] for n, o in zip(kaplan_N, optima)]
k_kaplan, _ = power_fit(kaplan_C, kaplan_N)
print(f"本章的记账（全部参数，每个预算都衰减完）：最优 N ∝ C^{k_N:.2f}，每个参数 "
      + " / ".join(f"{o['D'] / o['N']:.0f}" for o in optima) + " 个 token")
print(f"参数和算力都不算词嵌入表：                  最优 N ∝ C^{k_kaplan:.2f}，每个参数 "
      + " / ".join(f"{o['D'] / n:.0f}" for o, n in zip(optima, kaplan_N)) + " 个 token")
gaps = sorted(((r["raw"] - r["loss"], r) for r in runs if r["steps"] >= 60), key=lambda t: t[0])
print(f"不衰减直接读，比衰减完高 {gaps[0][0]:.2f}～{gaps[-1][0]:.2f}（{len(gaps)} 次不少于 60 步的训练）；"
      f"最少的是宽度 {gaps[0][1]['d']} 训练 {gaps[0][1]['steps']} 步，最多的是宽度 {gaps[-1][1]['d']} 训练 {gaps[-1][1]['steps']} 步")
# endregion kaplan

# %% [markdown]
# ## 6. 算力最优之外：把推理也算进去
#
# 用 Chinchilla 数据拟合出的 L(N, D) 算一笔账（Besiroglu 等人 2024 年的重新拟合）。先求它在 Chinchilla 那份算力（700 亿参数 × 1.4 万亿 token）下的最优点，
# 再看：要达到同样的损失，换成更小的模型要多训多少 token、训练贵多少、每生成一个 token 省多少。

# %%
# region inference
CHINCHILLA = {"E": 1.8172, "A": 482.01, "alpha": 0.3478, "B": 2085.43, "beta": 0.3658}   # Besiroglu 等，2024，式 (3)
C_chin = 6 * 70e9 * 1.4e12
sizes = [math.exp(i / 200) for i in range(int(200 * math.log(1e9)), int(200 * math.log(1e12)))]
N_star = min(sizes, key=lambda n: law(CHINCHILLA, n, C_chin / (6 * n)))
target = law(CHINCHILLA, N_star, C_chin / (6 * N_star))
print(f"算力 {C_chin:.2e} 下的最优点：{N_star / 1e9:.0f}B 参数、{C_chin / 6 / N_star / 1e12:.1f} 万亿 token"
      f"（每个参数 {C_chin / 6 / N_star / N_star:.0f} 个），损失 {target:.4f}")
N_min = (CHINCHILLA["A"] / (target - CHINCHILLA["E"])) ** (1 / CHINCHILLA["alpha"])
print(f"比 {N_min / 1e9:.1f}B 更小的模型，数据再多也到不了这个损失（光是 A/N^α 一项就超了）")
inference_rows = []
for N in (N_star, N_star * 3 / 4, N_star / 2, N_star / 3):
    gap = target - CHINCHILLA["E"] - CHINCHILLA["A"] / N ** CHINCHILLA["alpha"]
    D = (CHINCHILLA["B"] / gap) ** (1 / CHINCHILLA["beta"])
    extra_train = 6 * N * D - C_chin                                  # 多花的训练算力
    saved_per_token = 2 * N_star - 2 * N                              # 每生成一个 token 省下的推理算力（前向约 2N）
    breakeven = extra_train / saved_per_token if N < N_star else None
    inference_rows.append({"N": N, "D": D, "train": 6 * N * D, "breakeven": breakeven})
    print(f"{N / 1e9:4.0f}B：训练 {D / 1e12:5.1f} 万亿 token（每个参数 {D / N:5.0f} 个），训练算力 ×{6 * N * D / C_chin:4.2f}，"
          f"每个 token 的推理算力 ×{N / N_star:.2f}" + ("" if breakeven is None else f"；生成超过 {breakeven / 1e12:.1f} 万亿 token 后，总账比最优点省"))
# endregion inference

# %%
scaling_log = {
    "widths": WIDTHS, "params": {str(d): PARAMS[d] for d in WIDTHS}, "flops": {str(d): f for d, f in FLOPS.items()}, "tokens_per_step": tokens, "budgets": BUDGETS, "runs": runs,
    "optima": [{k: v for k, v in o.items() if k != "curve"} for o in optima], "k_N": k_N, "k_D": k_D, "N_trend": N_trend, "law": law_fit, "N_law": N_law,
    "kaplan": {"k_kaplan": k_kaplan, "kaplan_N": kaplan_N},
    "inference": {"N_star": N_star, "target": target, "N_min": N_min, "rows": inference_rows},
}
with open("scaling_laws_log.json", "w", encoding="utf-8") as f:
    json.dump(scaling_log, f, ensure_ascii=False)
