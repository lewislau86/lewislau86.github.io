# %% [markdown]
# # 第 18 章：正则化与泛化
#
# 配套教案：https://lewislau86.github.io/tinyllm/regularization
#
# 从上到下运行即可（`python regularization.py`），CPU 上约两分钟（一共训练 29 个小模型，每个 3～5 秒）。需要安装 PyTorch 和 `tokenizers`。
# 这个文件是本章代码的唯一来源：教案中的代码片段由 `# region 名字` / `# endregion 名字`
# 标记的区域直接引用，notebook 也由它生成（scripts/build-tinyllm-code.py）。
#
# 第 12 章的基线训练集有 5419 首诗，训练损失和验证损失贴在一起，还没有开始“背书”。本章故意只给模型 300 首诗，
# 让它过拟合，再逐个试：更多数据、提前停止、weight decay、dropout、label smoothing；最后回到全部数据，看这些手段还有没有用。

# %%
# region imports
import copy
import json
import math
import time
from dataclasses import dataclass, replace

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
# ## 0. 实验对象：第 17 章的代理模型，加上 dropout
#
# 模型代码从第 12 章复制，尺寸和第 17 章的代理模型相同（词表 1024、宽度 64、2 层）。唯一的改动是加了 dropout，
# 默认 `dropout=0.0`，这时和第 12 章的模型完全一样。

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
    dropout: float = 0.0       # 本章新增：训练时随机丢弃的比例，0 表示不用
# endregion config

# region proxy
cfg = TinyConfig(vocab_size=1024, d_model=64, n_layers=2)       # 第 17 章的代理模型
STEPS, BATCH, LR = 300, 16, 3e-3                                # 学习率固定 3e-3，和第 12 章一样
# endregion proxy
print(cfg)

# %%
# region data
poems = load_poems(6000)
train_poems = [p["text"] for p in poems if p["split"] == "train"]
val_poems = [p["text"] for p in poems if p["split"] == "val"]
test_poems = [p["text"] for p in poems if p["split"] == "test"]    # 本章新增：测试集，只用来报告最终结果
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
        self.dropout = cfg.dropout
        self.qkv = nn.Linear(cfg.d_model, 3 * cfg.d_model, bias=False)
        self.proj = nn.Linear(cfg.d_model, cfg.d_model, bias=False)   # 输出投影：写回残差流

    def forward(self, x, cos, sin):
        B, T, D = x.shape
        q, k, v = (t.view(B, T, self.n_heads, D // self.n_heads).transpose(1, 2)
                   for t in self.qkv(x).split(D, dim=-1))
        y = F.scaled_dot_product_attention(apply_rope(q, cos, sin), apply_rope(k, cos, sin), v, is_causal=True,
                                           dropout_p=self.dropout if self.training else 0.0)   # ① 注意力权重
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
        self.drop = nn.Dropout(cfg.dropout)

    def forward(self, x, cos, sin):
        x = x + self.drop(self.attn(self.norm1(x), cos, sin))       # ② 子层输出，加回残差流之前
        return x + self.drop(self.ffn(self.norm2(x)))
# endregion block

# region model
class TinyLLM(nn.Module):
    def __init__(self, cfg):
        super().__init__()
        self.cfg = cfg
        self.embed = nn.Embedding(cfg.vocab_size, cfg.d_model)
        self.drop = nn.Dropout(cfg.dropout)
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
        x = self.drop(self.embed(idx))                        # ③ 词嵌入之后；(B, T) → (B, T, d)
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

val_ids, test_ids = to_stream(val_poems), to_stream(test_poems)

@torch.no_grad()
def evaluate(model, ids, T=cfg.context, batch=64):
    model.eval()                                              # 关掉 dropout
    n = (len(ids) - 1) // T * T
    xs, ys = ids[:n].view(-1, T), ids[1:n + 1].view(-1, T)
    total = sum(F.cross_entropy(model(xs[i:i + batch]).flatten(0, 1), ys[i:i + batch].flatten(), reduction="sum").item()
                for i in range(0, len(xs), batch))
    model.train()
    return total / ys.numel()                                 # 每 token 的 nats
# endregion eval-protocol

# %% [markdown]
# ## 1. 只给 300 首诗：训练集、验证集、测试集
#
# 训练集只取前 300 首训练诗；验证集用来挑模型（停在哪一步、用哪个超参数），测试集只在最后报告一次。
# 每种训练集大小各有一份 batch 计划，由单独的随机数生成器排好，所有对照共用；`seed` 只决定初始参数（和 dropout 的随机掩码）。

# %%
# region subsets
SMALL = 300
train_sets = {}
for n in (300, 600, 1200, len(train_poems)):
    ids = to_stream(train_poems[:n])
    plan = torch.Generator().manual_seed(1234)
    starts = torch.randint(0, len(ids) - cfg.context - 1, (STEPS, BATCH), generator=plan)
    train_sets[n] = (ids, starts)
    print(f"训练集 {n:>4} 首：{len(ids):>6} 个 token，{STEPS} 步约过 {STEPS * BATCH * cfg.context / len(ids):4.1f} 遍")
print(f"验证集 {len(val_poems)} 首：{len(val_ids)} 个 token；测试集 {len(test_poems)} 首：{len(test_ids)} 个 token")
# endregion subsets

# %% [markdown]
# 提前停止的工具先定义好，训练函数里要用：验证损失连续 `patience` 次没有创新低就停，并记住验证损失最低时的参数。

# %%
# region early-stopping
class EarlyStopping:
    def __init__(self, patience=math.inf, min_delta=1e-3):
        self.patience, self.min_delta = patience, min_delta
        self.best, self.best_step, self.best_state, self.bad = math.inf, 0, None, 0

    def update(self, val_loss, model, step):
        """每次测完验证损失调用一次；返回 True 表示该停了。"""
        if val_loss < self.best - self.min_delta:
            self.best, self.best_step, self.bad = val_loss, step, 0
            self.best_state = copy.deepcopy(model.state_dict())   # 存下目前最好的参数
        else:
            self.bad += 1
        return self.bad >= self.patience
# endregion early-stopping

# %% [markdown]
# 训练函数和第 17 章一样（AdamW、梯度裁剪 1.0），学习率固定 3e-3。每 25 步测一次验证损失（`model.eval()`，即关掉 dropout）；
# 训练结束后恢复验证损失最低时的参数，在测试集上测一次。种子 0 还会记下训练集上的损失曲线（最多取前 8192 个 token）。

# %%
# region run
EVAL_TOKENS = 8192

def train(n_poems=SMALL, seed=0, weight_decay=0.0, dropout=0.0, smoothing=0.0, patience=math.inf, every=25):
    ids, starts = train_sets[n_poems]
    torch.manual_seed(seed)
    model = TinyLLM(replace(cfg, dropout=dropout))
    decay = [p for p in model.parameters() if p.dim() >= 2]
    no_decay = [p for p in model.parameters() if p.dim() < 2]
    optimizer = torch.optim.AdamW([{"params": decay, "weight_decay": weight_decay},
                                   {"params": no_decay, "weight_decay": 0.0}], lr=LR)
    stopper = EarlyStopping(patience)
    log = {"step": [], "val": [], "train": [], "norm": []}
    for step in range(STEPS):
        idx = starts[step][:, None] + torch.arange(cfg.context + 1)
        logits = model(ids[idx[:, :-1]])
        loss = F.cross_entropy(logits.flatten(0, 1), ids[idx[:, 1:]].flatten(), label_smoothing=smoothing)
        optimizer.zero_grad(set_to_none=True)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        optimizer.step()
        if (step + 1) % every == 0:
            log["step"].append(step + 1)
            log["val"].append(evaluate(model, val_ids))
            log["norm"].append(torch.cat([p.detach().flatten() for p in decay]).norm().item())   # 矩阵权重的 L2 范数
            if seed == 0:
                log["train"].append(evaluate(model, ids[:EVAL_TOKENS]))
            if stopper.update(log["val"][-1], model, step + 1):
                break
    model.load_state_dict(stopper.best_state)                      # 回到验证损失最低的那一步
    log.update(best_step=stopper.best_step, best_val=stopper.best, test=evaluate(model, test_ids))
    return log
# endregion run

# %% [markdown]
# ## 2. 过拟合现场
#
# 不加任何正则化（`weight_decay=0`、`dropout=0`），在 300 首诗上训练 300 步：

# %%
# region overfit
runs = {}
t0 = time.time()
runs[("无正则化", 0)] = log = train()
print(f"一次训练 {time.time() - t0:.1f} 秒")
print("步数    训练    验证   验证-训练")
for s, tr, va in zip(log["step"], log["train"], log["val"]):
    if s in (25, 50, 100, 150, 200, 250, 300):
        print(f"{s:>4}  {tr:6.3f}  {va:6.3f}  {va - tr:+6.3f}")
print(f"验证损失最低在第 {log['best_step']} 步：{log['best_val']:.3f}；那一步的参数在测试集上 {log['test']:.3f}")
# endregion overfit

# %% [markdown]
# ## 3. 第一个办法：更多数据
#
# 同一个模型、同样 300 步，训练集换成 600、1200 首（单个种子）和全部 5419 首（3 个种子）。

# %%
# region more-data
SEEDS = (0, 1, 2)

def report(label, logs):
    """多个种子：最好的一步、那一步参数的测试损失（平均与范围）、第 STEPS 步的验证损失。"""
    tests = [l["test"] for l in logs]
    finals = [l["val"][-1] for l in logs]
    if len(logs) == 1:
        print(f"{label:<18} 最好的一步 {logs[0]['best_step']:<11} 测试 {tests[0]:.3f}                第 {STEPS} 步验证 {finals[0]:.3f}")
    else:
        print(f"{label:<18} 最好的一步 {'/'.join(str(l['best_step']) for l in logs):<11} "
              f"测试 {sum(tests) / len(tests):.3f}（{min(tests):.3f}～{max(tests):.3f}）  第 {STEPS} 步验证 {sum(finals) / len(finals):.3f}")
    return tests

def run_seeds(label, seeds=SEEDS, **kw):
    for seed in seeds:
        if (label, seed) not in runs:
            runs[(label, seed)] = train(seed=seed, **kw)
    return report(label, [runs[(label, seed)] for seed in seeds])

FULL = len(train_poems)
summary = {}
summary["300 首"] = run_seeds("无正则化")
summary["600 首"] = run_seeds("600 首", seeds=(0,), n_poems=600)
summary["1200 首"] = run_seeds("1200 首", seeds=(0,), n_poems=1200)
summary[f"{FULL} 首"] = run_seeds(f"{FULL} 首", n_poems=FULL)
# endregion more-data

# %% [markdown]
# ## 4. 提前停止
#
# 前面每次训练都跑满 300 步，只是事后取验证损失最低的那一步。真正用提前停止时，看到验证损失连续几次不再下降就停下：

# %%
# region stop-demo
log = train(seed=0, patience=4)                  # 每 25 步测一次，连续 4 次（100 步）没进步就停
print(f"在第 {log['step'][-1]} 步停下（省下 {STEPS - log['step'][-1]} 步）；最好的一步是第 {log['best_step']} 步，"
      f"验证 {log['best_val']:.3f}，测试 {log['test']:.3f}")
# endregion stop-demo

# %% [markdown]
# ## 5. weight decay
#
# AdamW 每一步先把矩阵权重乘以 `1 - lr × weight_decay`，再做 Adam 的更新。先算一下几个取值每步缩多少，再各训练一次（种子 0）：

# %%
# region wd-sweep
for wd in (0.1, 1.0, 3.0, 10.0):
    print(f"weight_decay={wd:<4}：每步乘 {1 - LR * wd:.4f}，{STEPS} 步累计乘 {(1 - LR * wd) ** STEPS:.3f}，时间尺度 1/(lr·wd) ≈ {1 / (LR * wd):.0f} 步")
sweep = {"0": runs[("无正则化", 0)]["test"]}
for wd in (0.1, 1.0, 3.0, 10.0):
    sweep[f"{wd:g}"] = run_seeds(f"weight_decay {wd:g}", seeds=(0,), weight_decay=wd)[0]
print("第 300 步矩阵权重的 L2 范数（种子 0）：",
      "  ".join(f"{k} → {runs[(n, 0)]['norm'][-1]:.1f}" for k, n in
                [("0", "无正则化"), ("0.1", "weight_decay 0.1"), ("1", "weight_decay 1"), ("3", "weight_decay 3"), ("10", "weight_decay 10")]))
# endregion wd-sweep

# %% [markdown]
# ## 6. dropout
#
# 训练时把一部分数随机置零、其余放大 `1/(1-p)`；`model.eval()` 时原样通过。先看同一个 batch 在两种模式下的损失：

# %%
# region dropout-modes
torch.manual_seed(0)
probe = TinyLLM(replace(cfg, dropout=0.3))
ids, starts = train_sets[SMALL]
idx = starts[0][:, None] + torch.arange(cfg.context + 1)
x, y = ids[idx[:, :-1]], ids[idx[:, 1:]]
probe.train()
print("train 模式，连算两次：", f"{probe(x, y)[1].item():.4f}", f"{probe(x, y)[1].item():.4f}")
probe.eval()
print("eval 模式，连算两次： ", f"{probe(x, y)[1].item():.4f}", f"{probe(x, y)[1].item():.4f}")
z = nn.Dropout(0.3)(torch.ones(100_000))
print(f"nn.Dropout(0.3) 作用在 10 万个 1 上：置零的比例 {(z == 0).float().mean():.3f}，留下的值都是 {z.max():.4f}，平均 {z.mean():.4f}")
# endregion dropout-modes

# %% [markdown]
# 在 300 首诗上试 `dropout=0.1` 和 `0.3`（种子 0）：

# %%
# region dropout-sweep
t0 = time.time()
for p in (0.1, 0.3):
    sweep[f"dropout {p}"] = run_seeds(f"dropout {p}", seeds=(0,), dropout=p)[0]
print(f"加 dropout 后每次训练 {(time.time() - t0) / 2:.1f} 秒")
for name in ("无正则化", "dropout 0.3"):
    log = runs[(name, 0)]
    i = log["step"].index(log["best_step"])
    print(f"{name:<10} 最好的一步（第 {log['best_step']} 步）：训练 {log['train'][i]:.3f}  验证 {log['val'][i]:.3f}  差 {log['val'][i] - log['train'][i]:+.3f}")
# endregion dropout-sweep

# %% [markdown]
# ## 7. 3 个种子确认
#
# 单个种子的扫描只用来找范围。把第 12 章用的 `weight_decay=0.1`、扫描里最好的 `weight_decay=3` 和 `dropout=0.3`，
# 再加上 label smoothing（ε=0.1，第 15 章讲过；验证和测试仍用普通交叉熵），各跑 3 个种子：

# %%
# region confirm
summary["weight_decay 0.1"] = run_seeds("weight_decay 0.1", weight_decay=0.1)
summary["weight_decay 3"] = run_seeds("weight_decay 3", weight_decay=3.0)
summary["dropout 0.3"] = run_seeds("dropout 0.3", dropout=0.3)
summary["label smoothing 0.1"] = run_seeds("label smoothing 0.1", smoothing=0.1)
# endregion confirm

# %% [markdown]
# ## 8. 回到全部 5419 首：这些手段还有用吗？
#
# 全部数据 300 步只过了约一遍。把在 300 首上有效的两种设置用到全部数据上（3 个种子）：

# %%
# region full-data
full = {"无正则化": summary[f"{FULL} 首"]}
print(f"{'无正则化':<18}", f"测试 {sum(full['无正则化']) / 3:.3f}（{min(full['无正则化']):.3f}～{max(full['无正则化']):.3f}）")
full["weight_decay 3"] = run_seeds(f"全部 weight_decay 3", n_poems=FULL, weight_decay=3.0)
full["dropout 0.1"] = run_seeds(f"全部 dropout 0.1", n_poems=FULL, dropout=0.1)
log = runs[(f"{FULL} 首", 0)]
print(f"全部数据、无正则化（种子 0）第 {STEPS} 步：训练 {log['train'][-1]:.3f}  验证 {log['val'][-1]:.3f}")
# endregion full-data

# %%
reg_log = {
    "steps": STEPS, "small": SMALL, "full": FULL,
    "summary": summary, "sweep": sweep, "full_summary": full,
    "runs": {f"{k[0]}|{k[1]}": v for k, v in runs.items()},
}
with open("regularization_log.json", "w", encoding="utf-8") as f:
    json.dump(reg_log, f, ensure_ascii=False)
