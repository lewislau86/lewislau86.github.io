# %% [markdown]
# # 第 42 章：DPO：直接偏好优化
#
# 配套教案：https://lewislau86.github.io/tinyllm/preference-alignment
#
# 从上到下运行即可（`python preference-alignment.py`），CPU 约两分钟。需要安装 PyTorch 和 `tokenizers`。
# 这个文件是本章代码的唯一来源：教案中的代码片段由 `# region 名字` / `# endregion 名字`
# 标记的区域直接引用，notebook 也由它生成（scripts/build-tinyllm-code.py）。
#
# 和第 41 章同一个 SFT 模型、同一份偏好数据，换成 DPO：不训练奖励模型、不采样，直接用成对的偏好训练策略。
# 比较两个 β，看隐含奖励的准确率，以及“选中”“落选”的概率怎样变化。

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
sft_model = sft(base, sft_data)
print(f"[计时，本机] 预训练 2000 步 + SFT 1500 步（第 38 章种子 0），共 {time.perf_counter() - t0:.1f} 秒")

# %% [markdown]
# ## 3. 和第 41 章同一个“评审”、同一份偏好数据
#
# 评审、偏好数据的造法和第 41 章完全相同（同样的随机种子，所以是同一批对子）：
# 格式不对（句数、每句五字、按时停下）记 0 分；格式对记 1 分，诗里每出现一个不同的意象字（月风花山水云雪春秋夜）加 1 分，最多加 3 分；
# 同一个字出现 3 次以上（堆砌）扣 2 分。这个评审只用来造偏好数据和最后评估，训练过程只能通过偏好数据间接了解它。

# %%
# region judge
IMAGERY = set("月风花山水云雪春秋夜")

def judge(instruction, answer, stopped):
    c = check(instruction, answer, stopped)
    if not (c["count"] and c["stop"]):
        return 0
    images = len(IMAGERY & set(answer))
    most = max(answer.count(ch) for ch in set(answer) - set("，。"))
    return 1 + min(images, 3) - (2 if most >= 3 else 0)
# endregion judge

jue_poems = [p for p in sft_poems if len(lines_of(p)) == 4]
prompts = [make_instruction(p, random.Random(i)) for i, p in enumerate(jue_poems)]
eval_jue = [make_instruction(p, random.Random(i)) for i, p in enumerate(q for q in eval_poems if len(lines_of(q)) == 4)][:64]

# %%
# region pairs
t0 = time.perf_counter()
g, rng = torch.Generator().manual_seed(41), random.Random(41)
pairs = []
for p in prompts[:60]:
    outs = sample(sft_model, encode_chat(p), 64, g, temperature=1.0, max_new=60)
    scored = [(judge(p, a, s), row) for row, a, s in outs]
    rng.shuffle(scored)
    for (s1, r1), (s2, r2) in zip(scored[0::2], scored[1::2]):
        if s1 == s2:
            continue
        good, bad = (r1, r2) if s1 > s2 else (r2, r1)
        flipped = rng.random() < 0.1
        pairs.append({"prompt": p, "chosen": bad if flipped else good, "rejected": good if flipped else bad, "flipped": flipped})
train_pairs, test_pairs = pairs[:int(0.8 * len(pairs))], pairs[int(0.8 * len(pairs)):]
print(f"[计时，本机] {time.perf_counter() - t0:.1f} 秒；得到 {len(pairs)} 对（训练 {len(train_pairs)}、留出 {len(test_pairs)}），其中 {sum(x['flipped'] for x in pairs)} 对标反了")
# endregion pairs

# %% [markdown]
# ## 4. DPO：直接用偏好对训练策略
#
# 不训练奖励模型，也不采样。每一步取 16 对，算策略和参考模型（SFT，冻住）在“选中”“落选”两个回答上的对数概率之和，
# 损失是 $-\log\sigma\big(\beta[(\log\pi(y_w)-\log\pi_\text{ref}(y_w)) - (\log\pi(y_l)-\log\pi_\text{ref}(y_l))]\big)$。
# $\beta(\log\pi-\log\pi_\text{ref})$ 就是 DPO 隐含的“奖励”。

# %%
# region dpo
def response_ids(row):
    return row[:row.index(EOS) + 1] if EOS in row else [t for t in row if t != PAD]

def pad_batch(seqs):
    x = torch.full((len(seqs), max(len(s) for s in seqs)), PAD)
    for i, s in enumerate(seqs):
        x[i, :len(s)] = torch.tensor(s)
    return x, torch.tensor([len(s) for s in seqs])

def sequence_logprob(model, batch, key):
    """一批对子里，key（chosen 或 rejected）回答部分每个 token 的对数概率之和。"""
    seqs = [encode_chat(b["prompt"]) + response_ids(b[key]) for b in batch]
    x, lengths = pad_batch(seqs)
    lp = F.log_softmax(model(x[:, :-1]), dim=-1).gather(-1, x[:, 1:, None]).squeeze(-1)
    mask = torch.zeros_like(lp)
    for i, b in enumerate(batch):
        mask[i, len(encode_chat(b["prompt"])) - 1:lengths[i] - 1] = 1
    return (lp * mask).sum(1)

def dpo(start, beta=0.1, steps=300, batch=16, lr=1e-3, seed=0, record=(), nll=0.0):
    policy, ref = copy.deepcopy(start), start
    optimizer = torch.optim.AdamW(policy.parameters(), lr=lr, weight_decay=0.0)
    plan, trace = torch.Generator().manual_seed(seed), {}
    for i in range(steps):
        pick = [train_pairs[k] for k in torch.randint(0, len(train_pairs), (batch,), generator=plan).tolist()]
        with torch.no_grad():
            ref_w, ref_l = sequence_logprob(ref, pick, "chosen"), sequence_logprob(ref, pick, "rejected")
        pol_w, pol_l = sequence_logprob(policy, pick, "chosen"), sequence_logprob(policy, pick, "rejected")
        loss = -F.logsigmoid(beta * ((pol_w - ref_w) - (pol_l - ref_l))).mean()
        if nll:                                                   # 第 7 节：再加上“选中”回答的负对数似然
            n_tokens = torch.tensor([len(response_ids(b["chosen"])) for b in pick])
            loss = loss + nll * (-pol_w / n_tokens).mean()
        optimizer.zero_grad()
        loss.backward()
        torch.nn.utils.clip_grad_norm_(policy.parameters(), 1.0)
        optimizer.step()
        if i + 1 in record:
            trace[i + 1] = copy.deepcopy(policy)
    return policy, trace

@torch.no_grad()
def implicit_accuracy(policy, beta):
    """留出的对子上，DPO 隐含奖励给“选中”打分更高的比例（和标签、和评审的真实判断分别比）。"""
    margin = beta * ((sequence_logprob(policy, test_pairs, "chosen") - sequence_logprob(sft_model, test_pairs, "chosen"))
                     - (sequence_logprob(policy, test_pairs, "rejected") - sequence_logprob(sft_model, test_pairs, "rejected")))
    flipped = torch.tensor([b["flipped"] for b in test_pairs])
    return (margin > 0).float().mean().item(), ((margin > 0) != flipped).float().mean().item()
# endregion dpo

# %% [markdown]
# ## 5. 评估：和第 41 章用同一套指标
#
# 64 条没见过的绝句指令，每条采样一个回答（温度 0.8）：评审的平均分、意象字的个数、堆砌的比例、首字对、和 SFT 的 KL。

# %%
# region alignment-eval
def token_logprobs(model, x):
    return F.log_softmax(model(x[:, :-1]), dim=-1).gather(-1, x[:, 1:, None]).squeeze(-1)

@torch.no_grad()
def report(model, seed=7):
    g, rows = torch.Generator().manual_seed(seed), []
    for p in eval_jue:
        prompt = encode_chat(p)
        row, answer, stopped = sample(model, prompt, 1, g)[0]
        x, n = pad_batch([prompt + response_ids(row)])
        kl = (token_logprobs(model, x) - token_logprobs(sft_model, x))[0, len(prompt) - 1:].sum().item()
        most = max([answer.count(ch) for ch in set(answer) - set("，。")] or [0])
        c = check(p, answer, stopped)
        rows.append({"judge": judge(p, answer, stopped), "images": len(IMAGERY & set(answer)),
                     "stuffed": most >= 3, "first": c["first"], "kl": kl})
    mean = lambda k: sum(r[k] for r in rows if r[k] is not None) / max(1, sum(r[k] is not None for r in rows))
    return {k: mean(k) for k in ("judge", "images", "stuffed", "first", "kl")}

def show(name, r):
    print(f"{name:14} 评审 {r['judge']:.2f}  意象字 {r['images']:.2f}  堆砌 {r['stuffed']:.0%}  首字对 {r['first']:.2f}  KL {r['kl']:5.1f}")
# endregion alignment-eval

# %% [markdown]
# ## 6. 两个 β，各训 300 步
#
# β = 0.1 时，种子 0 另在第 100、200 步各存一份。

# %%
# region dpo-runs
t0 = time.perf_counter()
main, trace = dpo(sft_model, beta=0.1, record=(100, 200))
strong, _ = dpo(sft_model, beta=1.0)
print(f"[计时，本机] 两次 DPO 各 300 步，共 {time.perf_counter() - t0:.1f} 秒")
results = {"SFT": report(sft_model)}
for k, m in trace.items():
    results[f"DPO β=0.1 第 {k} 步"] = report(m)
results["DPO β=0.1"], results["DPO β=1"] = report(main), report(strong)
for name, r in results.items():
    show(name, r)
for name, m, beta in (("β=0.1", main, 0.1), ("β=1", strong, 1.0)):
    a, t = implicit_accuracy(m, beta)
    print(f"DPO {name} 的隐含奖励：留出的 {len(test_pairs)} 对上和标签一致 {a:.0%}，和评审的真实判断一致 {t:.0%}")
g = torch.Generator().manual_seed(3)
for p in eval_jue[:2]:
    print(f"DPO β=0.1：{p} → {sample(main, encode_chat(p), 1, g)[0][1]}")
# endregion dpo-runs
log["results"] = results

# %% [markdown]
# ## 7. 选中和落选的对数概率都在降
#
# DPO 只要求两者的差变大，不要求“选中”的概率变高。看看留出的对子上，两者的平均对数概率（相对 SFT）怎样变化；
# 再试一个常见的补救：损失里加上“选中”回答的负对数似然（按 token 平均，系数 1），把它的概率拴住。

# %%
# region logprob-drift
t0 = time.perf_counter()
anchored, _ = dpo(sft_model, beta=0.1, nll=1.0)
print(f"[计时，本机] {time.perf_counter() - t0:.1f} 秒")

@torch.no_grad()
def drift(policy):
    w = (sequence_logprob(policy, test_pairs, "chosen") - sequence_logprob(sft_model, test_pairs, "chosen")).mean().item()
    l = (sequence_logprob(policy, test_pairs, "rejected") - sequence_logprob(sft_model, test_pairs, "rejected")).mean().item()
    return w, l

for name, m in [("第 100 步", trace[100]), ("第 200 步", trace[200]), ("第 300 步", main), ("加 NLL，第 300 步", anchored)]:
    w, l = drift(m)
    print(f"β=0.1 {name:12}：选中 {w:+7.2f}  落选 {l:+7.2f}  差 {w - l:+6.2f}")
anchored_result = report(anchored)
show("DPO β=0.1 + NLL", anchored_result)
# endregion logprob-drift
log["drift"] = {name: drift(m) for name, m in [("100", trace[100]), ("200", trace[200]), ("300", main), ("nll", anchored)]}
log["results"]["DPO β=0.1 + NLL"] = anchored_result

# %%
with open("preference_alignment_log.json", "w", encoding="utf-8") as f:
    json.dump(log, f, ensure_ascii=False)
print("已写出 preference_alignment_log.json")
