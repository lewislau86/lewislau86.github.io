# %% [markdown]
# # 第 21 章：训练循环与检查点
#
# 配套教案：https://lewislau86.github.io/tinyllm/training-loop
#
# 从上到下运行即可（`python training-loop.py`），CPU 上约半分钟（训练步数加起来约 1900 步）。需要安装 PyTorch 和 `tokenizers`。
# 这个文件是本章代码的唯一来源：教案中的代码片段由 `# region 名字` / `# endregion 名字`
# 标记的区域直接引用，notebook 也由它生成（scripts/build-tinyllm-code.py）。
#
# 本章把前几章的零件装成一个完整、可中断、可恢复的训练循环，并用一个严格的标准检验检查点：
# 中断后接着训，和一口气训完相比，参数能不能逐位相同？

# %%
# region imports
import io
import json
import math
import os
import tempfile
import warnings
from dataclasses import asdict, dataclass
from pathlib import Path

import torch
from torch import nn
from torch.nn import functional as F
from torch.utils.data import DataLoader, Dataset, Sampler
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
# 模型代码和第 18 章相同（第 12 章的模型加上 dropout），尺寸是第 17 章的代理模型（词表 1024、宽度 64、2 层）。
# 本章打开 `dropout=0.1`，让训练用到全局随机数，好检验“随机数状态”有没有存对。

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
    dropout: float = 0.0       # 第 18 章加的：训练时随机丢弃的比例，0 表示不用
# endregion config

# region proxy
cfg = TinyConfig(vocab_size=1024, d_model=64, n_layers=2, dropout=0.1)   # 第 17 章的代理模型，打开 dropout
STEPS, BATCH, PEAK_LR = 240, 16, 1e-2                                    # 第 17 章的 WSD：峰值 1e-2
N_POEMS, SEED, DATA_SEED = 1200, 0, 1234                                 # 训练集取前 1200 首，好在 240 步里跨过几个 epoch
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

train_ids, val_ids = to_stream(train_poems[:N_POEMS]), to_stream(val_poems)

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
# ## 1. 数据：Dataset、Sampler、DataLoader
#
# 把训练集的 token 流切成不重叠的窗口，每个窗口是一个样本。打乱顺序交给一个自己写的 Sampler：
# 每个 epoch 的顺序只由 `(DATA_SEED, epoch)` 决定，`start` 用来跳过这个 epoch 已经用过的样本。

# %%
# region dataset
class Windows(Dataset):
    """把 token 流切成不重叠的窗口：第 i 个样本是 (输入, 目标)，各 context 个 token，错开一位。"""
    def __init__(self, ids, T):
        n = (len(ids) - 1) // T
        self.x, self.y = ids[:n * T].view(n, T), ids[1:n * T + 1].view(n, T)

    def __len__(self):
        return len(self.x)

    def __getitem__(self, i):
        return self.x[i], self.y[i]

class EpochShuffle(Sampler):
    """每个 epoch 的打乱顺序只由 (seed, epoch) 决定；start 跳过这个 epoch 已经用过的样本。"""
    def __init__(self, n, seed):
        self.n, self.seed, self.epoch, self.start = n, seed, 0, 0

    def set_epoch(self, epoch, start=0):
        self.epoch, self.start = epoch, start

    def __iter__(self):
        g = torch.Generator().manual_seed(self.seed + self.epoch)
        return iter(torch.randperm(self.n, generator=g)[self.start:].tolist())

    def __len__(self):
        return self.n - self.start

dataset = Windows(train_ids, cfg.context)
sampler = EpochShuffle(len(dataset), DATA_SEED)
loader = DataLoader(dataset, batch_size=BATCH, sampler=sampler, drop_last=True)
print(f"{len(dataset)} 个窗口，每个 epoch {len(loader)} 个 batch；{STEPS} 步约 {STEPS / len(loader):.1f} 个 epoch")
x, y = next(iter(loader))
print("一个 batch：", tuple(x.shape), tuple(y.shape), "目标是输入错开一位：", torch.equal(x[0, 1:], y[0, :-1]))
# endregion dataset

# %% [markdown]
# ## 2. 构造训练对象
#
# 模型、优化器、学习率调度器。调度用第 17 章的 WSD，写成 `LambdaLR`：

# %%
# region build
def wsd(step, warmup=30, decay_frac=0.2):
    """WSD（第 17 章）：返回峰值学习率的倍数。"""
    decay_steps = int(STEPS * decay_frac)
    if step < warmup:
        return (step + 1) / warmup
    if step < STEPS - decay_steps:
        return 1.0
    return (STEPS - step) / decay_steps

def build(config, seed=SEED):
    torch.manual_seed(seed)
    model = TinyLLM(config)
    decay = [p for p in model.parameters() if p.dim() >= 2]
    no_decay = [p for p in model.parameters() if p.dim() < 2]
    optimizer = torch.optim.AdamW([{"params": decay, "weight_decay": 0.1},
                                   {"params": no_decay, "weight_decay": 0.0}], lr=PEAK_LR)
    scheduler = torch.optim.lr_scheduler.LambdaLR(optimizer, wsd)
    return model, optimizer, scheduler
# endregion build

# %% [markdown]
# ## 3. 训练循环
#
# `progress` 记着训练进行到哪里：第几步、第几个 epoch、这个 epoch 用掉了几个 batch。循环从 `progress` 接着往下走，
# 一直训练到第 `until` 步。每一步的顺序：清梯度 → 前向 → 反向 → 裁剪 → 更新参数 → 推进学习率。

# %%
# region loop
def train(model, optimizer, scheduler, progress, until, history, on_step=None, log_every=None):
    model.train()
    while progress["step"] < until:
        sampler.set_epoch(progress["epoch"], start=progress["batch_in_epoch"] * BATCH)
        for x, y in loader:
            optimizer.zero_grad(set_to_none=True)
            _, loss = model(x, y)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            scheduler.step()                                   # 每个优化器步之后推进一次
            progress["step"] += 1
            progress["batch_in_epoch"] += 1
            history.append(loss.detach())                      # 先存张量，不急着 .item()
            if log_every and progress["step"] % log_every == 0:
                recent = torch.stack(history[-log_every:]).mean().item()   # 每 log_every 步才同步一次
                print(f"  step {progress['step']:4d}  epoch {progress['epoch']}  最近 {log_every} 步平均损失 {recent:.3f}"
                      f"  学习率 {scheduler.get_last_lr()[0]:.2e}")
            if on_step is not None:
                on_step(model, optimizer, scheduler, progress)
            if progress["step"] == until:
                return
        progress["epoch"] += 1                                  # 这个 epoch 的 batch 用完了
        progress["batch_in_epoch"] = 0
# endregion loop

# %% [markdown]
# 一口气训练 240 步，作为参照。再从头训练一次，检查两次是否逐位相同：比较“续训”之前，先确认训练本身是确定的。

# %%
# region reference
def fresh_progress():
    return {"step": 0, "epoch": 0, "batch_in_epoch": 0}

def run_reference(log_every=None):
    model, optimizer, scheduler = build(cfg)
    history = []
    train(model, optimizer, scheduler, fresh_progress(), STEPS, history, log_every=log_every)
    return {k: v.clone() for k, v in model.state_dict().items()}, torch.stack(history), evaluate(model, val_ids)

reference, ref_losses, ref_val = run_reference(log_every=40)
print(f"参照：240 步后验证损失 {ref_val:.4f}")
again, _, _ = run_reference()

def max_diff(state):
    return max((state[k] - reference[k]).abs().max().item() for k in reference)

print(f"再训练一次：参数最大差 {max_diff(again)}")
# endregion reference

# %% [markdown]
# ## 4. 检查点里存什么
#
# 能“接着训”需要的全部东西：模型参数、优化器状态、调度器状态、训练进度、随机数状态；再加上配置，新进程才能先把对象造出来。
# 保存时先写临时文件，写完再改名替换，避免写到一半时断电留下一个坏文件。

# %%
# region checkpoint
def make_checkpoint(model, optimizer, scheduler, progress):
    return {
        "model": model.state_dict(),
        "optimizer": optimizer.state_dict(),                 # AdamW 的 m、v、步数，以及当前学习率
        "scheduler": scheduler.state_dict(),                 # 调度器走到了第几步
        "progress": dict(progress),                          # 第几步、第几个 epoch、这个 epoch 用掉几个 batch
        "rng": {"torch": torch.get_rng_state()},             # dropout 用的全局随机数；GPU 上还要 torch.cuda.get_rng_state_all()
        "config": asdict(cfg),
        "train_config": {"steps": STEPS, "batch": BATCH, "peak_lr": PEAK_LR, "seed": SEED,
                         "data_seed": DATA_SEED, "n_poems": N_POEMS},
    }

def save_checkpoint(ckpt, path):
    tmp = path.with_name(path.name + ".tmp")
    torch.save(ckpt, tmp)
    os.replace(tmp, path)                                    # 原子替换：path 要么是旧文件，要么是完整的新文件

def keep_last(folder, n):
    """只保留最新的 n 个检查点。"""
    for old in sorted(folder.glob("step_*.pt"))[:-n]:
        old.unlink()
# endregion checkpoint

# %% [markdown]
# 从头训练，每 40 步存一次、只保留最新 2 个，训练到第 120 步时“断电”：

# %%
# region crash
def train_until_crash(crash_at=120):
    folder = Path(tempfile.mkdtemp(prefix="tinyllm-ckpt-"))
    tokenizer.save(str(folder / "tokenizer.json"))           # 分词器和检查点放在一起

    def save_every_40(model, optimizer, scheduler, progress):
        if progress["step"] % 40 == 0:
            save_checkpoint(make_checkpoint(model, optimizer, scheduler, progress), folder / f"step_{progress['step']:06d}.pt")
            keep_last(folder, 2)

    model, optimizer, scheduler = build(cfg)
    history = []
    train(model, optimizer, scheduler, fresh_progress(), crash_at, history, on_step=save_every_40)
    return folder, history                                   # 函数返回，模型、优化器都随之消失：进程“死掉”了

workdir, crash_history = train_until_crash()
print("目录里剩下：", ", ".join(f"{p.name}（{p.stat().st_size / 1024:.0f} KB）" for p in sorted(workdir.iterdir())))
# endregion crash

# %% [markdown]
# ## 5. 恢复，接着训练
#
# 新进程只有磁盘上的文件：先按存下的配置把模型、优化器、调度器造出来，再把各自的状态装回去。
# `parts` 用来做对照：故意少恢复一样东西，看会发生什么。

# %%
# region resume
ALL = ("model", "optimizer", "scheduler", "progress", "rng")

def resume(path, parts=ALL):
    ckpt = torch.load(path, weights_only=True)               # 只读张量和基本类型，不执行任意代码
    model, optimizer, scheduler = build(TinyConfig(**ckpt["config"]))
    if "model" in parts:
        model.load_state_dict(ckpt["model"])
    if "optimizer" in parts:
        optimizer.load_state_dict(ckpt["optimizer"])
    if "scheduler" in parts:
        scheduler.load_state_dict(ckpt["scheduler"])
    if "progress" in parts:
        progress = dict(ckpt["progress"])
    else:                                                    # 只知道步数，数据从第 0 个 epoch 的开头重新读
        progress = {"step": ckpt["progress"]["step"], "epoch": 0, "batch_in_epoch": 0}
    if "rng" in parts:
        torch.set_rng_state(ckpt["rng"]["torch"])
    return model, optimizer, scheduler, progress

def resume_and_finish(folder, crash_history, parts=ALL):
    latest = sorted(folder.glob("step_*.pt"))[-1]
    model, optimizer, scheduler, progress = resume(latest, parts)
    history = list(crash_history)
    train(model, optimizer, scheduler, progress, STEPS, history)
    return model, torch.stack(history)

latest = sorted(workdir.glob("step_*.pt"))[-1]
print(f"从 {latest.name} 恢复：{resume(latest)[3]}")
model, losses = resume_and_finish(workdir, crash_history)
first = (losses != ref_losses).nonzero()
print(f"接着训到 240 步：验证损失 {evaluate(model, val_ids):.4f}（参照 {ref_val:.4f}），参数最大差 {max_diff(model.state_dict()):.2e}")
print(f"第一次和参照不同的是第 {first[0].item() + 1} 步：{losses[first[0]].item():.6f} 对 {ref_losses[first[0]].item():.6f}" if len(first) else "每一步的损失都和参照相同")
# endregion resume

# %% [markdown]
# ## 6. 找原因：DataLoader 偷偷用了全局随机数
#
# 模型、优化器、调度器、数据位置、随机数状态都存了，第 121 步还是不一样。第 121 步的 batch 是对的（数据位置），
# 那就只剩 dropout 的随机掩码。恢复之后、第 121 步之前，有谁动过全局随机数？

# %%
# region rng-leak
state = torch.get_rng_state()
iter(loader)
print("iter(loader) 之后，全局随机数状态变了：", not torch.equal(state, torch.get_rng_state()))

loader = DataLoader(dataset, batch_size=BATCH, sampler=sampler, drop_last=True,
                    generator=torch.Generator().manual_seed(DATA_SEED))   # 给它一个自己的随机数生成器
state = torch.get_rng_state()
iter(loader)
print("换成自己的 generator 之后，变了：", not torch.equal(state, torch.get_rng_state()))
# endregion rng-leak

# %% [markdown]
# 换上新的 `loader`，重新跑一遍：参照、训练到第 120 步“断电”、恢复后接着训练。

# %%
# region fixed
reference, ref_losses, ref_val = run_reference()
workdir, crash_history = train_until_crash()
model, losses = resume_and_finish(workdir, crash_history)
print(f"参照验证损失 {ref_val:.4f}；恢复后接着训练 {evaluate(model, val_ids):.4f}")
print(f"参数最大差 {max_diff(model.state_dict())}；240 步的训练损失逐个相同：{torch.equal(losses, ref_losses)}")
# endregion fixed

# %% [markdown]
# ## 7. 对照：每次少恢复一样东西

# %%
# region ablation
variants = {"完整恢复": ALL}
for missing, label in [("optimizer", "缺优化器状态"), ("scheduler", "缺调度器状态"),
                       ("progress", "缺数据位置"), ("rng", "缺随机数状态")]:
    variants[label] = tuple(p for p in ALL if p != missing)

ablation = {}
print(f"{'':<8}{'第 121 步损失':>12}{'后 120 步最大损失差':>16}{'参数最大差':>12}{'最终验证':>10}")
print(f"{'参照':<8}{ref_losses[120].item():14.4f}{0:20.4f}{0:15.2e}{ref_val:12.4f}")
for label, parts in variants.items():
    model, losses = resume_and_finish(workdir, crash_history, parts)
    gap = (losses[120:] - ref_losses[120:]).abs().max().item()
    ablation[label] = {"losses": losses.tolist(), "val": evaluate(model, val_ids), "param_diff": max_diff(model.state_dict())}
    print(f"{label:<8}{losses[120].item():12.4f}{gap:16.4f}{ablation[label]['param_diff']:12.2e}{ablation[label]['val']:10.4f}")
# endregion ablation

# %% [markdown]
# 缺调度器状态时，学习率从哪里开始？把恢复后前几步实际用的学习率打印出来：

# %%
# region lr-after-resume
for label in ("完整恢复", "缺调度器状态"):
    model, optimizer, scheduler, progress = resume(latest := sorted(workdir.glob("step_*.pt"))[-1], variants[label])
    lrs = []
    for step in range(4):
        lrs.append(optimizer.param_groups[0]["lr"])          # 这一步实际用的学习率
        optimizer.step()                                     # 没有梯度，参数不变；只为按正确顺序推进
        scheduler.step()
    print(f"{label:<8} 恢复后前 4 步的学习率：" + "  ".join(f"{v:.2e}" for v in lrs)
          + f"   （参照：" + "  ".join(f"{PEAK_LR * wsd(s):.2e}" for s in range(120, 124)) + "）")
# endregion lr-after-resume

# %% [markdown]
# ## 8. 写到一半断电会怎样
#
# 直接往检查点文件里写，写到一半断电，留下的文件读不出来；先写临时文件再替换，旧检查点不受影响：

# %%
# region atomic
good = workdir / "step_000120.pt"
data = good.read_bytes()

broken = workdir / "direct.pt"                                # 直接写目标文件，只写了一半
broken.write_bytes(data[:len(data) // 2])
try:
    torch.load(broken, weights_only=True)
except Exception as e:
    print(f"直接写、写到一半：读取失败（{type(e).__name__}）")

(workdir / "step_000120.pt.tmp").write_bytes(data[:len(data) // 2])   # 原子写：临时文件写到一半，还没来得及 replace
print("原子写、写到一半：目标文件仍可读取，步数", torch.load(good, weights_only=True)["progress"]["step"])
# endregion atomic

# %% [markdown]
# ## 9. 检查点有多大

# %%
# region sizes
def nbytes(obj):
    buf = io.BytesIO()
    torch.save(obj, buf)
    return buf.tell()

ckpt = torch.load(good, weights_only=True)
sizes = {k: nbytes(v) for k, v in ckpt.items()}
n_params = sum(v.numel() for v in ckpt["model"].values())
for k, v in sizes.items():
    print(f"{k:<12} {v / 1024:8.1f} KB")
print(f"{n_params} 个参数；模型 {sizes['model'] / n_params:.2f} 字节/参数，优化器 {sizes['optimizer'] / n_params:.2f} 字节/参数")
# endregion sizes

# %% [markdown]
# ## 10. 调度器和优化器的先后
#
# 把 `scheduler.step()` 放到 `optimizer.step()` 之前，PyTorch 会给出警告，学习率序列也整体提前了一步：

# %%
# region order
for order in ("optimizer 先", "scheduler 先"):
    w = torch.zeros(1, requires_grad=True)
    opt = torch.optim.SGD([w], lr=PEAK_LR)
    sch = torch.optim.lr_scheduler.LambdaLR(opt, wsd)
    used = []
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        for step in range(3):
            w.grad = torch.ones(1)
            if order == "scheduler 先":
                sch.step()
            used.append(opt.param_groups[0]["lr"])
            opt.step()
            if order == "optimizer 先":
                sch.step()
    message = str(caught[0].message) if caught else ""
    note = "；PyTorch 警告：" + message[:message.index("optimizer.step()`") + 17] if caught else ""
    print(f"{order}：前 3 步用的学习率 " + "  ".join(f"{v:.2e}" for v in used) + note)
# endregion order

# %%
loop_log = {
    "steps": STEPS, "resume_step": 120, "batches_per_epoch": len(loader),
    "reference": ref_losses.tolist(), "reference_val": ref_val,
    "ablation": ablation,
    "lr_reference": [PEAK_LR * wsd(s) for s in range(STEPS)],
    "sizes": sizes, "n_params": n_params,
}
with open("training_loop_log.json", "w", encoding="utf-8") as f:
    json.dump(loop_log, f, ensure_ascii=False)
