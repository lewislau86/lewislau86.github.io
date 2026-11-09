# %% [markdown]
# # 第 16 章：优化器
#
# 配套教案：https://lewislau86.github.io/tinyllm/optimizers
#
# 从上到下运行即可（`python optimizers.py`），CPU 上约一分半（最后一节训练 21 个代理模型）。需要 `torch`、`tokenizers`；画交互图需要 `plotly`。
# 这个文件是本章代码的唯一来源：教案中的代码片段由 `# region 名字` / `# endregion 名字`
# 标记的区域直接引用，notebook 也由它生成（scripts/build-tinyllm-code.py）。
# 本章先手写一步梯度下降，再依次认识 SGD、Momentum、Adam、AdamW 的 PyTorch 接口、
# 参数组和检查点，用固定数据比较四种优化器，最后在第 17 章的代理模型上对照 SGD、Adam、AdamW 和两种 weight decay 写法。

# %%
import copy
import math

import torch

print("PyTorch", torch.__version__)

# %% [markdown]
# ## 1. 从手动更新到 `optimizer.step()`
#
# 让 `w` 学会把 `x=2` 映射到 `t=6`，理想值是 `w=3`。先猜：学习率 0.1 时，`w` 会单调逼近 3，还是在 3 两边跳？

# %%
# region manual-update
# 让 w 学会把 x=2 映射到 t=6：理想 w=3
x = torch.tensor(2.0)
target = torch.tensor(6.0)
w = torch.tensor(0.0)
learning_rate = 0.1

for step in range(8):
    prediction = w * x
    loss = (prediction - target).square()
    grad = 2 * (prediction - target) * x  # 这一行也可以由 autograd 得到
    w = w - learning_rate * grad
    print(step, round(w.item(), 4), round(loss.item(), 4))
# endregion manual-update

# %% [markdown]
# 梯度是 `8w-24`，更新变成 `w ← (1-8η)w + 24η`。学习率 0.1、0.2、0.3 对应的系数是 0.2、-0.6、-1.4：
# 单调收敛、两边跳着收敛、越跳越远。下面各走 8 步验证。

# %%
for learning_rate in (0.1, 0.2, 0.3):
    w = torch.tensor(0.0)
    path = []
    for step in range(8):
        grad = 2 * (w * x - target) * x
        w = w - learning_rate * grad
        path.append(round(w.item(), 3))
    print(f"lr={learning_rate}:", path)

# %% [markdown]
# 真实训练交给 `torch.optim`。基本用法只有三步：清梯度、反向传播、更新参数。

# %%
# region optim-basics
model = torch.nn.Linear(1, 1)
optimizer = torch.optim.SGD(model.parameters(), lr=0.1)

prediction = model(torch.tensor([[2.0]]))
loss = (prediction - torch.tensor([[6.0]])).square().mean()
optimizer.zero_grad()  # 清除上一步留下的梯度
loss.backward()        # 计算本步梯度
optimizer.step()       # 按 SGD 规则更新参数
# endregion optim-basics
print("更新后的参数:", [round(p.item(), 4) for p in model.parameters()])

# %% [markdown]
# ## 3. Momentum：给梯度装上惯性
#
# 速度 $v_t$ 是优化器状态，保存在优化器里，不在 `model.parameters()` 中。

# %%
# region momentum
optimizer = torch.optim.SGD(
    model.parameters(),
    lr=0.01,
    momentum=0.9,
)
# endregion momentum

# %%
# region momentum-state
loss = (model(torch.tensor([[2.0]])) - torch.tensor([[6.0]])).square().mean()
optimizer.zero_grad()
loss.backward()
optimizer.step()  # 第一次 step 之后才会建立动量缓冲区

state = optimizer.state_dict()
print(state.keys())             # dict_keys(['state', 'param_groups'])
print(list(state["state"][0]))  # ['momentum_buffer']
# endregion momentum-state

# %% [markdown]
# ## 4. Adam：方向和尺度一起估计

# %%
# region adam
optimizer = torch.optim.Adam(
    model.parameters(),
    lr=3e-4,
    betas=(0.9, 0.999),
    eps=1e-8,
)
# endregion adam
print(optimizer)

# %% [markdown]
# ## 5. AdamW：权重衰减放在哪里

# %%
# region adamw
optimizer = torch.optim.AdamW(
    model.parameters(),
    lr=3e-4,
    weight_decay=0.1,
)
# endregion adamw

# %% [markdown]
# Adam 中把 L2 加到梯度，会让正则项也受到 Adam 的自适应缩放；AdamW 则把衰减直接从参数上解耦。
# 在一个标量参数上各走一步看看。具体差异会随参数、梯度和超参数变化。

# %%
def one_step(kind):
    parameter = torch.nn.Parameter(torch.tensor(2.0))
    if kind == "adam_l2":
        optimizer = torch.optim.Adam([parameter], lr=0.1, weight_decay=0.1)
    else:
        optimizer = torch.optim.AdamW([parameter], lr=0.1, weight_decay=0.1)
    loss = (parameter - 5).square()
    optimizer.zero_grad(set_to_none=True)
    loss.backward()
    optimizer.step()
    return parameter.item()
print("Adam + L2:", one_step("adam_l2"))
print("AdamW:", one_step("adamw"))

# %% [markdown]
# ## 6. 参数组：不同参数用不同的衰减
#
# 常见规则是矩阵权重衰减，偏置和一维归一化参数不衰减。先搭一个带嵌入、LayerNorm 和输出层的小模型，再按名称和维度分组。

# %%
torch.manual_seed(0)
model = torch.nn.Sequential(
    torch.nn.Embedding(32, 16),
    torch.nn.LayerNorm(16),
    torch.nn.Linear(16, 32),
)

# region param-groups
weight_decay, no_decay = [], []
for name, parameter in model.named_parameters():
    if not parameter.requires_grad:
        continue
    if parameter.ndim == 1 or name.endswith("bias"):
        no_decay.append(parameter)
    else:
        weight_decay.append(parameter)

optimizer = torch.optim.AdamW([
    {"params": weight_decay, "weight_decay": 0.1},
    {"params": no_decay, "weight_decay": 0.0},
], lr=3e-4)
# endregion param-groups

names = {id(p): name for name, p in model.named_parameters()}
print("衰减:", [names[id(p)] for p in weight_decay])
print("不衰减:", [names[id(p)] for p in no_decay])

# %%
# region check-groups
all_ids = [id(p) for group in optimizer.param_groups for p in group["params"]]
assert len(all_ids) == len(set(all_ids))
print([group["weight_decay"] for group in optimizer.param_groups])  # [0.1, 0.0]
# endregion check-groups

# %% [markdown]
# ## 7. 优化器状态与检查点
#
# 先走一步让 AdamW 建立状态，再把模型和优化器一起保存。

# %%
tokens = torch.randint(0, 32, (4, 8))
loss = torch.nn.functional.cross_entropy(model(tokens).flatten(0, 1), tokens.flatten())
optimizer.zero_grad(set_to_none=True)
loss.backward()
optimizer.step()

# region checkpoint
checkpoint = {
    "model": model.state_dict(),
    "optimizer": optimizer.state_dict(),
    "step": 1200,
}
torch.save(checkpoint, "tinyllm_step1200.pt")
# endregion checkpoint

# %% [markdown]
# 恢复时先建立相同结构和参数组的模型与优化器，再加载两份状态。

# %%
restored = torch.load("tinyllm_step1200.pt")
model.load_state_dict(restored["model"])
optimizer.load_state_dict(restored["optimizer"])
print("恢复到 step", restored["step"], "；AdamW 状态:", list(optimizer.state[weight_decay[0]]))

# %% [markdown]
# ## 9. 动手：在同一条曲线上比较四个优化器
#
# 让一个两层 tanh 小网络拟合固定的 `sin(x)`。四个优化器从同一份初始参数开始，比较才公平。

# %%
# region fixed-data
torch.manual_seed(7)
x = torch.linspace(-math.pi, math.pi, 128).unsqueeze(1)
y = torch.sin(x)
base = torch.nn.Sequential(
    torch.nn.Linear(1, 16),
    torch.nn.Tanh(),
    torch.nn.Linear(16, 1),
)
initial = copy.deepcopy(base.state_dict())
# endregion fixed-data
print(x.shape, y.shape)

# %% [markdown]
# 先看 SGD 走 5 步：顺序是清梯度、反向传播、更新参数。

# %%
model = copy.deepcopy(base)
model.load_state_dict(initial)
optimizer = torch.optim.SGD(model.parameters(), lr=0.05)
for step in range(5):
    prediction = model(x)
    loss = (prediction - y).square().mean()
    optimizer.zero_grad(set_to_none=True)
    loss.backward()
    optimizer.step()
    print(step, round(loss.item(), 6))

# %% [markdown]
# 改变优化器会改变参数走法；数据、初始参数和训练步数保持不变。先猜：谁下降得最快？

# %%
# region compare
optimizers = {
    "SGD": lambda parameters: torch.optim.SGD(parameters, lr=0.05),
    "Momentum": lambda parameters: torch.optim.SGD(parameters, lr=0.05, momentum=0.9),
    "Adam": lambda parameters: torch.optim.Adam(parameters, lr=0.01),
    "AdamW": lambda parameters: torch.optim.AdamW(parameters, lr=0.01, weight_decay=1e-3),
}
results = {}
for name, make_optimizer in optimizers.items():
    model = copy.deepcopy(base)
    model.load_state_dict(initial)
    optimizer = make_optimizer(model.parameters())
    history = []
    for step in range(300):
        prediction = model(x)
        loss = (prediction - y).square().mean()
        optimizer.zero_grad(set_to_none=True)
        loss.backward()
        optimizer.step()
        history.append(loss.item())
    results[name] = history
    print(name, round(history[0], 4), "->", round(history[-1], 6))
# endregion compare

# %% [markdown]
# 画出损失曲线。对数纵轴可以同时看早期快速下降和后期细小差异。

# %%
# region plot
import plotly.graph_objects as go
figure = go.Figure()
for name, history in results.items():
    figure.add_trace(go.Scatter(y=history, mode="lines", name=name))
figure.update_layout(
    title="四种优化器的训练损失",
    xaxis_title="step",
    yaxis_title="mean squared error",
    yaxis_type="log",
)
figure.show()
# endregion plot

# %% [markdown]
# 最后一轮循环留下的是 AdamW。动量、平方梯度平均和步数都属于优化器状态，不在模型参数中。

# %%
for parameter, state in optimizer.state.items():
    print("参数形状:", tuple(parameter.shape), "状态:", list(state))
    break

# %% [markdown]
# ## 10. 一份 TinyLLM 配置起点
#
# 沿用第 6 节分好的两个参数列表。

# %%
# region tinyllm-config
# 这里假设前面的参数分组已经得到两个列表。
decay_parameters = weight_decay
no_decay_parameters = no_decay
optimizer = torch.optim.AdamW(
    [
        {"params": decay_parameters, "weight_decay": 0.1},
        {"params": no_decay_parameters, "weight_decay": 0.0},
    ],
    lr=3e-3,                 # 第 12 章基线的取值；第 11 节在代理模型上验证
    betas=(0.9, 0.999),
    eps=1e-8,
)
# endregion tinyllm-config
print([(group["weight_decay"], len(group["params"])) for group in optimizer.param_groups])


# %% [markdown]
# ## 11. 接回 TinyLLM：在代理模型上比较优化器
#
# 前面的正弦曲线只是玩具。下面换成第 17 章的代理模型（词表 1024、宽度 64、2 层），模型代码、数据划分、评估口径都从第 12 章原样复制，
# 所有对照用同一组预先排好的 batch，随机种子只决定初始参数。学习率固定不变（不加调度），每次训练 240 步、裁剪到 1.0。

# %%
# region proxy-imports
import copy
import json
import math
import time
from dataclasses import dataclass

import torch
from torch import nn
from torch.nn import functional as F
from tokenizers import Tokenizer, decoders, models, pre_tokenizers, trainers
# endregion proxy-imports


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
# region proxy-config
@dataclass
class TinyConfig:
    vocab_size: int = 4096     # BPE 词表大小（含 4 个特殊 token）
    d_model: int = 128         # 每个 token 向量的宽度 d
    n_layers: int = 4          # Block 层数 L
    n_heads: int = 4           # 注意力头数，每头 d / n_heads = 32 维
    context: int = 64          # 一次最多看多少个 token
    rope_base: float = 10000.0

cfg = TinyConfig()
# endregion proxy-config

# region proxy-proxy
cfg = TinyConfig(vocab_size=1024, d_model=64, n_layers=2)       # 代理模型：只改这三个尺寸
STEPS, BATCH = 240, 16
# endregion proxy-proxy
print(cfg)

# %%
# region proxy-data
poems = load_poems(6000)
train_poems = [p["text"] for p in poems if p["split"] == "train"]
val_poems = [p["text"] for p in poems if p["split"] == "val"]
# endregion proxy-data

# region proxy-tokenizer
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
# endregion proxy-tokenizer

# %%
# region proxy-rope
def rope_tables(context, head_dim, base):
    theta = base ** (-torch.arange(0, head_dim, 2).float() / head_dim)
    angle = torch.arange(context).float()[:, None] * theta        # (T, head_dim/2)
    return angle.cos(), angle.sin()

def apply_rope(x, cos, sin):                                      # x: (B, 头数, T, head_dim)
    T = x.shape[-2]
    cos, sin = cos[:T], sin[:T]
    x1, x2 = x[..., 0::2], x[..., 1::2]
    return torch.stack([x1 * cos - x2 * sin, x1 * sin + x2 * cos], dim=-1).flatten(-2)
# endregion proxy-rope

# region proxy-attention
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
# endregion proxy-attention

# region proxy-swiglu
class SwiGLU(nn.Module):
    def __init__(self, cfg):
        super().__init__()
        hidden = 8 * cfg.d_model // 3
        self.gate = nn.Linear(cfg.d_model, hidden, bias=False)
        self.up = nn.Linear(cfg.d_model, hidden, bias=False)
        self.down = nn.Linear(hidden, cfg.d_model, bias=False)        # 输出投影：写回残差流

    def forward(self, x):
        return self.down(F.silu(self.gate(x)) * self.up(x))
# endregion proxy-swiglu

# region proxy-block
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
# endregion proxy-block

# region proxy-model
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
# endregion proxy-model

# %%
# region proxy-eval-protocol
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
# endregion proxy-eval-protocol


# %%
# region proxy-run
plan = torch.Generator().manual_seed(1234)                 # batch 计划：所有对照共用
starts = torch.randint(0, len(train_ids) - cfg.context - 1, (STEPS, BATCH), generator=plan)

def get_batch(step):
    idx = starts[step][:, None] + torch.arange(cfg.context + 1)
    return train_ids[idx[:, :-1]], train_ids[idx[:, 1:]]

def make_optimizer(model, kind, lr):
    decay = [p for p in model.parameters() if p.dim() >= 2]     # 矩阵：衰减
    no_decay = [p for p in model.parameters() if p.dim() < 2]   # RMSNorm 的缩放：不衰减
    if kind == "SGD+Momentum":
        return torch.optim.SGD(model.parameters(), lr=lr, momentum=0.9)
    if kind == "Adam":
        return torch.optim.Adam(model.parameters(), lr=lr)
    if kind == "Adam+L2":                                        # weight_decay 加进梯度，再经过 m、v
        return torch.optim.Adam(model.parameters(), lr=lr, weight_decay=0.1)
    if kind == "AdamW（全部衰减）":
        return torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=0.1)
    return torch.optim.AdamW([{"params": decay, "weight_decay": 0.1},       # "AdamW"：本章第 6 节的分组
                              {"params": no_decay, "weight_decay": 0.0}], lr=lr)

def run(kind, lr, seed=0):
    torch.manual_seed(seed)
    model = TinyLLM(cfg)
    optimizer = make_optimizer(model, kind, lr)
    for step in range(STEPS):
        x, y = get_batch(step)
        _, loss = model(x, y)
        optimizer.zero_grad(set_to_none=True)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        optimizer.step()
    return evaluate(model)[0]
# endregion proxy-run

# %% [markdown]
# 先用种子 0 给每个优化器扫 3 个学习率。SGD 的学习率和 Adam 不在一个量级（第 4 节：Adam 的步长已经按 $\sqrt{\hat v}$ 归一过），所以分开扫。

# %%
# region proxy-sweep
sweep = {"SGD+Momentum": (0.1, 0.3, 1.0), "Adam": (1e-3, 3e-3, 1e-2), "AdamW": (1e-3, 3e-3, 1e-2)}
results = {}
for kind, lrs in sweep.items():
    results[kind] = {lr: run(kind, lr) for lr in lrs}
    print(f"{kind:<13}" + "".join(f"  lr={lr:<6g} {v:.3f}" for lr, v in results[kind].items()))
# endregion proxy-sweep

# %% [markdown]
# 每个优化器取自己最好的学习率，再换两个种子，看差别是否超过种子之间的波动：

# %%
# region proxy-seeds
best = {kind: min(r, key=r.get) for kind, r in results.items()}
final = {}
for kind, lr in best.items():
    vals = [results[kind][lr]] + [run(kind, lr, seed) for seed in (1, 2)]
    final[kind] = vals
    print(f"{kind:<13} lr={lr:<6g} 3 个种子 {' '.join(f'{v:.3f}' for v in vals)}  平均 {sum(vals) / 3:.3f}")
# endregion proxy-seeds

# %% [markdown]
# 最后看第 5、6 节的两件事：weight decay 放在哪里（Adam+L2 还是 AdamW）、哪些参数衰减（分组还是全部）。
# 先在 AdamW 最好的学习率上比，再在 1e-2 上比一次：学习率越大，“衰减被 $\sqrt{v}$ 缩放”这件事越明显。

# %%
# region proxy-decay
decay_cmp = {}
for lr in (best["AdamW"], 1e-2):
    for kind in ("AdamW", "AdamW（全部衰减）", "Adam+L2"):
        vals = final[kind] if kind == "AdamW" and lr == best["AdamW"] else [run(kind, lr, seed) for seed in (0, 1, 2)]
        decay_cmp[(kind, lr)] = vals
        print(f"lr={lr:<6g} {kind:<12} {' '.join(f'{v:.3f}' for v in vals)}  平均 {sum(vals) / 3:.3f}")
# endregion proxy-decay

# %% [markdown]
# ## 练习
#
# 1. 把 SGD 的学习率改成 `0.001` 和 `0.5`，观察曲线。
# 2. 把 Momentum 的 `momentum` 改为 `0.0`，它就退化成什么？
# 3. 删除 `optimizer.zero_grad()`，观察梯度为什么会累积。
# 4. 保存并恢复 `model.state_dict()` 与 `optimizer.state_dict()`，比较严格续训和只恢复模型的差异。
