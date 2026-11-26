# %% [markdown]
# # 第 38 章：指令微调
#
# 配套教案：https://lewislau86.github.io/tinyllm/instruction-finetuning
#
# 从上到下运行即可（`python instruction-finetuning.py`），CPU 约两分钟。需要安装 PyTorch 和 `tokenizers`。
# 这个文件是本章代码的唯一来源：教案中的代码片段由 `# region 名字` / `# endregion 名字`
# 标记的区域直接引用，notebook 也由它生成（scripts/build-tinyllm-code.py）。
#
# 本章先在唐诗上预训练一个基座，再用“指令—回答”数据做监督微调（SFT）：对话模板、只在回答上算损失、停止 token，
# 以及推理时模板不一致会怎样。合格与否由程序判定（每句五字、句数、首字、是否按时停下）。

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

# %% [markdown]
# ## 3. 一条训练样本长什么样
#
# 打印一条 SFT 样本：每个 token 和它的 loss 掩码。只有回答和最后的 `<eos>` 参与损失。

# %%
# region show-example
ids, mask = encode_chat(*sft_data[0])

def render(ids):
    """把 token 还原成文本，特殊 token 原样写出来。"""
    out, run = [], []
    for t in ids + [None]:
        if t in (USER, ASSISTANT, EOS, None):
            out.append(tokenizer.decode(run))
            run = []
            if t is not None:
                out.append(tokenizer.id_to_token(t))
        else:
            run.append(t)
    return "".join(out)

cut = mask.index(1)
print(f"共 {len(ids)} 个 token，其中 {sum(mask)} 个算损失")
print("不算损失：", render(ids[:cut]))
print("算损失：  ", render(ids[cut:]))
# endregion show-example

# %% [markdown]
# ## 4. 基座会照指令写吗
#
# 把同样的模板交给只预训练过的基座。它从来没见过 `<user>`、`<assistant>`，也没见过指令。

# %%
# region base-eval
def show(name, r):
    print(f"{name:16} 每句五字 {r['five']:.2f}  句数对 {r['count']:.2f}  首字对 {r['first']:.2f}  按时停下 {r['stop']:.2f}  │ 全部照做 {r['all']:.2f}")

base_result = evaluate(base)
show("基座（未微调）", base_result)
for i, p in enumerate(eval_prompts[:2]):
    print(p, "→", sample(base, encode_chat(p), 1, torch.Generator().manual_seed(i))[0][1])
# endregion base-eval

# %% [markdown]
# ## 5. SFT：只在回答上算损失
#
# 同一个基座，SFT 1500 步（每步 16 条，学习率 warmup 10 步到 3e-3，再线性降到 0），换 3 个种子（只决定抽样顺序）。
# 种子 0 另在第 500、1000 步各存一份，看合格率随步数怎样变化。

# %%
# region sft-run
t0 = time.perf_counter()
runs = {}
for seed in (0, 1, 2):
    if seed == 0:
        runs[seed], mids = sft(base, sft_data, seed=seed, checkpoints=(500, 1000))
    else:
        runs[seed] = sft(base, sft_data, seed=seed)
print(f"[计时，本机] 3 个种子各 SFT 1500 步，共 {time.perf_counter() - t0:.1f} 秒")
results = {seed: evaluate(m) for seed, m in runs.items()}
for seed, r in results.items():
    show(f"SFT 种子 {seed}", r)
curve = {k: evaluate(m) for k, m in mids.items()}
for k, r in curve.items():
    show(f"种子 0 第 {k} 步", r)
print("预训练验证损失：基座 {:.3f}  SFT 后 {}".format(pretrain_loss(base), " ".join(f"{pretrain_loss(m):.3f}" for m in runs.values())))
for i, p in enumerate(eval_prompts[:4]):
    print(p, "→", sample(runs[0], encode_chat(p), 1, torch.Generator().manual_seed(i))[0][1])
# endregion sft-run
log["base"], log["sft"], log["curve"] = base_result, results, {str(k): r for k, r in curve.items()}

# %% [markdown]
# ## 6. 两个对照：在全部 token 上算损失；训练时去掉 `<eos>`
#
# 第一个对照和种子 0 的设置完全相同，只是指令部分也算损失。第二个对照只为看“停不停得下来”，训 500 步就够了。

# %%
# region ablations
t0 = time.perf_counter()
all_tokens = sft(base, sft_data, answer_only=False)
no_eos = sft(base, sft_data, steps=500, eos=False)
print(f"[计时，本机] 两个对照（1500 步、500 步）共 {time.perf_counter() - t0:.1f} 秒")
ablation = {"all_tokens": evaluate(all_tokens), "no_eos": evaluate(no_eos)}
show("只算回答（种子 0）", results[0])
show("全部 token 都算", ablation["all_tokens"])
show("训练时没有 <eos>", ablation["no_eos"])
print("预训练验证损失：只算回答 {:.3f}  全部 token {:.3f}".format(pretrain_loss(runs[0]), pretrain_loss(all_tokens)))
_, text, stopped = sample(no_eos, encode_chat(eval_prompts[0]), 1, torch.Generator().manual_seed(1))[0]
print("没有 <eos> 的模型：", text[:60], "…" if not stopped else "")
# endregion ablations
log.update(ablation)

# %% [markdown]
# ## 7. 推理时换一个模板
#
# 训练时的模板是 `<user>指令<assistant>`。推理时如果少了 `<assistant>`，或者把指令换成训练时没见过的说法，会怎样？

# %%
# region template-mismatch
def no_assistant(instruction):
    return [USER] + tokenizer.encode(instruction).ids

reworded = [p.replace("写一首", "请作一首").replace("用“", "以“") for p in eval_prompts]
mismatch = {"no_assistant": evaluate(runs[0], template=no_assistant), "reworded": evaluate(runs[0], prompts=reworded)}
show("训练时的模板", results[0])
show("少了 <assistant>", mismatch["no_assistant"])
show("换一种说法", mismatch["reworded"])
# endregion template-mismatch
log["mismatch"] = mismatch

# %%
with open("instruction_finetuning_log.json", "w", encoding="utf-8") as f:
    json.dump(log, f, ensure_ascii=False)
print("已写出 instruction_finetuning_log.json")
