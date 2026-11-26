# %% [markdown]
# # 第 39 章：参数高效微调（LoRA）
#
# 配套教案：https://lewislau86.github.io/tinyllm/lora-finetuning
#
# 从上到下运行即可（`python lora-finetuning.py`），CPU 约两分钟。需要安装 PyTorch 和 `tokenizers`。
# 这个文件是本章代码的唯一来源：教案中的代码片段由 `# region 名字` / `# endregion 名字`
# 标记的区域直接引用，notebook 也由它生成（scripts/build-tinyllm-code.py）。
#
# 本章沿用第 38 章的基座和 SFT 数据，比较全参数微调和 LoRA：可训练参数、显存账、照指令做的效果、原来的语言能力掉了多少，
# 以及把增量合并回原权重后推理和原模型一样。

# %%
# region imports
import copy
import json
import math
import random
import re
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
# 模型代码从第 12 章原样复制，尺寸用第 17 章的代理模型：词表 1024、宽度 64、2 层、4 个头，上下文放到 128（一条指令加一首律诗放得下）。
# 第八部分每一章都要从头训一遍基座和 SFT，原尺寸太慢；损失和合格率的绝对值只在第八部分内部比较。

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
cfg = TinyConfig(vocab_size=1024, d_model=64, n_layers=2, context=128)   # 第 17 章的代理模型，上下文放到 128
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
        special_tokens=["<pad>", "<unk>", "<bos>", "<eos>", "<user>", "<assistant>"],   # 后两个是对话模板用的
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
# ## 1. 数据：预训练用的诗，SFT 用的“指令—回答”
#
# 统一语料的前 6000 首用来预训练基座（按 `split` 分训练和验证），第 6001～12000 首的训练集用来造 SFT 数据，
# 同一段里的验证集、测试集诗用来造评估用的指令。三份数据没有重叠。分词器只用预训练的诗训练。

# %%
# region data
poems = load_poems(12000)
pre_train = [p["text"] for p in poems[:6000] if p["split"] == "train"]
pre_val = [p["text"] for p in poems[:6000] if p["split"] == "val"]
sft_poems = [p["text"] for p in poems[6000:] if p["split"] == "train"]
eval_poems = [p["text"] for p in poems[6000:] if p["split"] != "train"]
tokenizer = train_tokenizer(pre_train, cfg.vocab_size)
PAD, EOS, USER, ASSISTANT = (tokenizer.token_to_id(t) for t in ("<pad>", "<eos>", "<user>", "<assistant>"))

def to_stream(texts):
    ids = []
    for t in texts:
        ids += tokenizer.encode(t).ids + [EOS]
    return torch.tensor(ids)

P_train, P_val = to_stream(pre_train), to_stream(pre_val)
# endregion data
print(f"预训练：{len(pre_train)} 首 {len(P_train):,} 个 token；SFT 素材 {len(sft_poems)} 首；评估素材 {len(eval_poems)} 首")

# %%
# region instructions
def lines_of(poem):
    return [s for s in re.split("[，。]", poem) if s]

def make_instruction(poem, rng):
    """从一首诗反推一条它满足的指令：体裁总要说，六成再要求第一个字。"""
    kind = "绝句" if len(lines_of(poem)) == 4 else "律诗"
    if rng.random() < 0.4:
        return f"写一首五言{kind}。"
    return f"写一首五言{kind}，用“{poem[0]}”字开头。"

def check(instruction, answer, stopped):
    """程序判分：每句五字、句数对、首字对（有要求时）、按时停下（生成了 <eos>）。"""
    kind = 4 if "绝句" in instruction else 8
    first = re.search("[用以]“(.)”字开头", instruction)
    five = re.fullmatch(r"([一-鿿]{5}，[一-鿿]{5}。)+", answer) is not None
    count = five and len(lines_of(answer)) == kind
    first_ok = None if first is None else answer[:1] == first.group(1)
    return {"five": five, "count": count, "first": first_ok, "stop": stopped,
            "all": five and count and first_ok is not False and stopped}
# endregion instructions

# region chat-template
def encode_chat(instruction, answer=None):
    """对话模板：<user>指令<assistant>回答<eos>。返回 token 和 loss 掩码（只有回答和 <eos> 是 1）。"""
    prompt = [USER] + tokenizer.encode(instruction).ids + [ASSISTANT]
    if answer is None:
        return prompt
    reply = tokenizer.encode(answer).ids + [EOS]
    return prompt + reply, [0] * len(prompt) + [1] * len(reply)
# endregion chat-template

rng = random.Random(38)
sft_data = [(make_instruction(p, rng), p) for p in sft_poems]
eval_prompts = [make_instruction(p, random.Random(i)) for i, p in enumerate(eval_poems[:64])]

# %% [markdown]
# ## 2. 预训练基座
#
# 第 17 章的 WSD：warmup 30 步、峰值 1e-2、最后 20% 线性降到 0，共 2000 步；每步 8 行、每行 128 个 token（和第 17 章每步 16 行 × 64 个 token 的量相同）。

# %%
# region pretrain
def make_optimizer(model, lr):
    decay = [p for p in model.parameters() if p.dim() >= 2]
    no_decay = [p for p in model.parameters() if p.dim() < 2]
    return torch.optim.AdamW([{"params": decay, "weight_decay": 0.1}, {"params": no_decay, "weight_decay": 0.0}], lr=lr)

def step(model, optimizer, loss, lr):
    for group in optimizer.param_groups:
        group["lr"] = lr
    optimizer.zero_grad(set_to_none=True)
    loss.backward()
    torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
    optimizer.step()

def wsd(i, total, peak, warmup=30, decay_frac=0.2):
    start = int(total * (1 - decay_frac))
    if i < warmup:
        return peak * (i + 1) / warmup
    return peak if i < start else peak * (total - i) / (total - start)

def pretrain(seed=0, steps=2000, rows=8):
    torch.manual_seed(seed)
    model = TinyLLM(cfg)
    optimizer = make_optimizer(model, 1e-2)
    plan, T = torch.Generator().manual_seed(1234), cfg.context
    for i in range(steps):
        starts = torch.randint(0, len(P_train) - T - 1, (rows,), generator=plan)
        x = P_train[starts[:, None] + torch.arange(T + 1)]
        _, loss = model(x[:, :-1].contiguous(), x[:, 1:].contiguous())
        step(model, optimizer, loss, wsd(i, steps, 1e-2))
    return model

@torch.no_grad()
def pretrain_loss(model, T=cfg.context, batch=32):
    """预训练验证集上每 token 的损失：看后训练有没有把原来的语言能力训坏。"""
    model.eval()
    n = (len(P_val) - 1) // T * T
    xs, ys = P_val[:n].view(-1, T), P_val[1:n + 1].view(-1, T)
    total = sum(F.cross_entropy(model(xs[i:i + batch]).flatten(0, 1), ys[i:i + batch].flatten(), reduction="sum").item()
                for i in range(0, len(xs), batch))
    model.train()
    return total / ys.numel()
# endregion pretrain

# region sft
def sft(base, data, steps=1500, batch=16, peak=3e-3, answer_only=True, seed=0, eos=True, checkpoints=()):
    """监督微调：从基座复制一份，每步随机取 batch 条指令—回答，右侧补 <pad>，只在掩码为 1 的位置算交叉熵。"""
    model = copy.deepcopy(base)
    optimizer = make_optimizer(model, peak)
    plan = torch.Generator().manual_seed(seed)
    encoded = [encode_chat(i, a) for i, a in data]
    if not eos:                                                    # 第 5 节的对照：训练时去掉回答末尾的 <eos>
        encoded = [(ids[:-1], mask[:-1]) for ids, mask in encoded]
    saved = {}
    for i in range(steps):
        pick = torch.randint(0, len(encoded), (batch,), generator=plan).tolist()
        L = max(len(encoded[k][0]) for k in pick)
        x, w = torch.full((batch, L), PAD), torch.zeros(batch, L)
        for r, k in enumerate(pick):
            ids, mask = encoded[k]
            x[r, :len(ids)] = torch.tensor(ids)
            w[r, :len(ids)] = torch.tensor(mask if answer_only else [1] * len(ids))
        logits = model(x[:, :-1])
        lp = F.cross_entropy(logits.transpose(1, 2), x[:, 1:], reduction="none")
        loss = (lp * w[:, 1:]).sum() / w[:, 1:].sum()
        lr = peak * (i + 1) / 10 if i < 10 else peak * (steps - i) / (steps - 10)
        step(model, optimizer, loss, lr)
        if i + 1 in checkpoints:
            saved[i + 1] = copy.deepcopy(model)
    return (model, saved) if checkpoints else model
# endregion sft

# region generate
@torch.no_grad()
def sample(model, prompt_ids, n, generator, temperature=0.8, max_new=80):
    """同一个提示采样 n 个回答（一个 batch 一起生成）。返回每个回答的 token、文本、是否生成了 <eos>。"""
    model.eval()
    x = torch.tensor([prompt_ids] * n)
    done = torch.zeros(n, dtype=torch.bool)
    for _ in range(max_new):
        logits = model(x[:, -cfg.context:])[:, -1] / temperature
        nxt = torch.multinomial(F.softmax(logits, dim=-1), 1, generator=generator).squeeze(1)
        nxt = torch.where(done, torch.full_like(nxt, PAD), nxt)
        x = torch.cat([x, nxt[:, None]], dim=1)
        done |= nxt == EOS
        if done.all():
            break
    model.train()
    outs = []
    for row in x[:, len(prompt_ids):].tolist():
        stopped = EOS in row
        ids = row[:row.index(EOS)] if stopped else [t for t in row if t != PAD]
        outs.append((row, tokenizer.decode(ids), stopped))
    return outs

def evaluate(model, prompts=None, seed=7, template=encode_chat):
    """每条指令采样一个回答，按 check 判分，返回各项合格率。"""
    prompts = eval_prompts if prompts is None else prompts
    g = torch.Generator().manual_seed(seed)
    rows = []
    for p in prompts:
        _, answer, stopped = sample(model, template(p), 1, g)[0]
        rows.append(check(p, answer, stopped))
    rate = lambda key: sum(r[key] for r in rows if r[key] is not None) / max(1, sum(r[key] is not None for r in rows))
    return {k: rate(k) for k in ("five", "count", "first", "stop", "all")}
# endregion generate

# %%
t0 = time.perf_counter()
base = pretrain()
print(f"[计时，本机] 预训练 2000 步 {time.perf_counter() - t0:.1f} 秒；预训练验证损失 {pretrain_loss(base):.3f}")

def show(name, r, loss):
    print(f"{name:20} 每句五字 {r['five']:.2f}  句数对 {r['count']:.2f}  首字对 {r['first']:.2f}  全部照做 {r['all']:.2f}  │ 预训练验证损失 {loss:.3f}")

# %% [markdown]
# ## 3. LoRA：冻住原权重，只训练低秩增量
#
# 每个线性层 W（形状 out×in）旁边加一条支路：x → A（r×in）→ B（out×r），输出乘 α/r 再加回去。
# A 随机初始化、B 初始化为 0，所以刚加上时模型和原来完全一样。原来的 W 冻住，只训练 A、B。

# %%
# region lora
class LoRALinear(nn.Module):
    def __init__(self, linear, r, alpha):
        super().__init__()
        self.linear = linear                                         # 原来的层，冻住
        self.A = nn.Parameter(torch.randn(r, linear.in_features) / linear.in_features ** 0.5)
        self.B = nn.Parameter(torch.zeros(linear.out_features, r))  # 从 0 开始：刚加上时输出不变
        self.scale = alpha / r

    def forward(self, x):
        return self.linear(x) + (x @ self.A.T @ self.B.T) * self.scale

    def merged(self):
        """把增量合并回原权重：W + (α/r)·B·A，得到一个普通的线性层。"""
        out = nn.Linear(self.linear.in_features, self.linear.out_features, bias=False)
        out.weight.data = self.linear.weight.data + self.scale * self.B.data @ self.A.data
        return out

class NewTokenRows(nn.Module):
    """嵌入表冻住，只给指定的几行（新加的特殊 token）一个可训练的增量。输出层和嵌入表共享，所以也一起变。"""
    def __init__(self, embed, rows):
        super().__init__()
        self.embed = embed
        self.register_buffer("rows", torch.tensor(rows))
        self.delta = nn.Parameter(torch.zeros(len(rows), embed.embedding_dim))

    @property
    def weight(self):
        return self.embed.weight.index_add(0, self.rows, self.delta)

    def forward(self, idx):
        return F.embedding(idx, self.weight)

LINEARS = {"attn": ("qkv", "proj"), "ffn": ("gate", "up", "down")}

def add_lora(model, r, new_token_rows=()):
    """复制一份模型，冻住全部参数，给每个 Block 的 5 个线性层加 LoRA（α = 2r）。"""
    model = copy.deepcopy(model)
    for p in model.parameters():
        p.requires_grad_(False)
    for block in model.blocks:
        for part, names in LINEARS.items():
            for name in names:
                module = getattr(block, part)
                setattr(module, name, LoRALinear(getattr(module, name), r, alpha=2 * r))
    if new_token_rows:
        model.embed = NewTokenRows(model.embed, list(new_token_rows))
    return model

def count(model):
    """可训练的参数个数。"""
    return sum(p.numel() for p in model.parameters() if p.requires_grad)
# endregion lora

# %% [markdown]
# ## 4. 全参数微调与几种 LoRA
#
# 全参数微调和第 38 章种子 0 完全相同（学习率峰值 3e-3）。LoRA 加在每个 Block 的 5 个线性层上，学习率峰值 1e-2（LoRA 常用比全参数微调大的学习率），
# 比较秩 r = 4 和 32；再试一组 r = 32、同时让两个新特殊 token（`<user>`、`<assistant>`）的嵌入可训练。其余设置都和第 38 章相同，1500 步。

# %%
# region runs
n_total = sum(p.numel() for p in base.parameters())
configs = {
    "全参数微调": (lambda: base, 3e-3),
    "LoRA r=4": (lambda: add_lora(base, 4), 1e-2),
    "LoRA r=32": (lambda: add_lora(base, 32), 1e-2),
    "LoRA r=32 + 新 token": (lambda: add_lora(base, 32, new_token_rows=(USER, ASSISTANT)), 1e-2),
}
models, results, trainable = {}, {}, {}
t0 = time.perf_counter()
for name, (build, peak) in configs.items():
    start = build()
    trainable[name] = count(start) if name != "全参数微调" else n_total
    models[name] = sft(start, sft_data, peak=peak)
    results[name] = (evaluate(models[name]), pretrain_loss(models[name]))
print(f"[计时，本机] 4 组各 SFT 1500 步，共 {time.perf_counter() - t0:.1f} 秒")
print(f"模型共 {n_total:,} 个参数")
for name, (r, loss) in results.items():
    print(f"{name:20} 可训练 {trainable[name]:>7,}（{trainable[name] / n_total:6.1%}）")
for name, (r, loss) in results.items():
    show(name, r, loss)
# endregion runs
log["results"] = {k: {"eval": r, "pretrain_loss": l, "trainable": trainable[k]} for k, (r, l) in results.items()}
log["base_loss"], log["n_total"] = pretrain_loss(base), n_total

# %% [markdown]
# ## 5. 显存账：LoRA 省下的是什么
#
# 训练时显存里有四样东西：权重、梯度、优化器状态（AdamW 每个可训练参数存两份）、激活。
# 下面按 FP32（每个数 4 字节）算前三样；激活和 batch、长度有关，两种做法基本相同，不计入。

# %%
# region memory
def train_memory(n_params, n_trainable, bytes_per=4):
    weights = n_params * bytes_per
    grads = n_trainable * bytes_per
    adam = 2 * n_trainable * bytes_per
    return weights, grads, adam

for name in ("全参数微调", "LoRA r=4", "LoRA r=32"):
    extra = trainable[name] if name != "全参数微调" else 0          # LoRA 的 A、B 本身也要存
    w, g, a = train_memory(n_total + extra, trainable[name])
    print(f"{name:12} 权重 {w / 2**20:5.2f} MiB  梯度 {g / 2**20:5.2f} MiB  优化器状态 {a / 2**20:5.2f} MiB  合计 {(w + g + a) / 2**20:5.2f} MiB")
# 换成 Llama 2 7B 的形状：d=4096、FFN 11008、32 层、词表 32000，输入输出两张表不共享
d, ffn, L, V = 4096, 11008, 32, 32000
n7b = L * (4 * d * d + 3 * d * ffn) + 2 * V * d
lora7b = L * 16 * (4 * (d + d) + 2 * (d + ffn) + (ffn + d))        # r=16，加在 q、k、v、o 和三个 FFN 线性层上
full_bytes = n7b * (2 + 2 + 4 + 8)        # BF16 权重、BF16 梯度、FP32 主权重、AdamW 两份 FP32 状态
lora_bytes = n7b * 2 + lora7b * (2 + 2 + 4 + 8)
print(f"7B 级模型 {n7b / 1e9:.2f}B 个参数：全参数微调（混合精度）约 {full_bytes / 2**30:.0f} GiB；"
      f"LoRA r=16 只训练 {lora7b / 1e6:.0f}M 个参数，冻住的 BF16 权重加上 LoRA 部分约 {lora_bytes / 2**30:.1f} GiB")
# endregion memory

# %% [markdown]
# ## 6. 合并：推理时和原模型一样快
#
# 训练完把 (α/r)·B·A 加回 W，LoRA 就消失了：模型的结构、参数量、速度都和原来一样。检查合并前后的输出是否一致。

# %%
# region merge
lora = models["LoRA r=32"]
merged = copy.deepcopy(lora)
for block in merged.blocks:
    for part, names in LINEARS.items():
        module = getattr(block, part)
        for name in names:
            setattr(module, name, getattr(module, name).merged())
x = torch.tensor([encode_chat(eval_prompts[0])])
with torch.no_grad():
    diff = (lora(x) - merged(x)).abs().max().item()
print(f"合并前参数 {sum(p.numel() for p in lora.parameters()):,}，合并后 {sum(p.numel() for p in merged.parameters()):,}（和原模型 {n_total:,} 相同）")
print(f"合并前后 logits 的最大差 {diff:.2e}")
full_delta = models["全参数微调"].blocks[0].attn.qkv.weight - base.blocks[0].attn.qkv.weight
s = torch.linalg.svdvals(full_delta.detach())
print(f"对照：全参数微调后第 1 层 qkv 权重的变化，前 32 个奇异值占全部能量的 {(s[:32] ** 2).sum() / (s ** 2).sum():.1%}，前 4 个占 {(s[:4] ** 2).sum() / (s ** 2).sum():.1%}")
# endregion merge
log["full_delta_energy"] = {"top4": ((s[:4] ** 2).sum() / (s ** 2).sum()).item(), "top32": ((s[:32] ** 2).sum() / (s ** 2).sum()).item()}

# %%
with open("lora_finetuning_log.json", "w", encoding="utf-8") as f:
    json.dump(log, f, ensure_ascii=False)
print("已写出 lora_finetuning_log.json")
