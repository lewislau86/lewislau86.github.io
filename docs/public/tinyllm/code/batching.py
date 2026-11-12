# %% [markdown]
# # 第 32 章：批处理与调度
#
# 配套教案：https://lewislau86.github.io/tinyllm/batching
#
# 从上到下运行即可（`python batching.py`），CPU 上约一分钟（一半是训练基线模型）。
# 需要安装 PyTorch 和 `tokenizers`。
# 这个文件是本章代码的唯一来源：教案中的代码片段由 `# region 名字` / `# endregion 名字`
# 标记的区域直接引用，notebook 也由它生成（scripts/build-tinyllm-code.py）。
#
# 本章的硬条件：不管怎样拼批、怎样调度，每个请求生成的 token 都必须和它单独跑时逐个相同（用 assert 检查）。
# 调度实验的时间用一个写明了的成本模型来算（单位是“一次小前向”），与硬件无关；
# 以“[计时，本机]”开头的输出是本机的墙钟时间，换一台机器会不同。

# %%
# region imports
import json
import math
import time

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
# ## 1. 研究对象：第 12 章的基线模型
#
# 模型与第 28～31 章相同（d=128、4 层、4 个头、词表 4096、上下文 64），训练 300 步，种子 0。
# 批处理不改变模型，只改变“一次前向里放谁”，所以这里只需要一个训好的模型。
# 为了在拼批时复用同一套计算，把一层 Block 拆成两半：`attn_inputs` 算出加了 RoPE 的 Q、K、V，
# `finish` 接上注意力的输出，做完残差和前馈层。两半中间的注意力怎么算，正是拼批要动的地方。

# %%
# region model
poems = load_poems(6000)
train_poems = [p["text"] for p in poems if p["split"] == "train"]
val_poems = [p["text"] for p in poems if p["split"] == "val"]

V, D, L, H, CTX = 4096, 128, 4, 4, 64
DH = D // H
tok = Tokenizer(models.BPE())
tok.pre_tokenizer = pre_tokenizers.ByteLevel(add_prefix_space=False)
tok.decoder = decoders.ByteLevel()
tok.train_from_iterator(train_poems, trainers.BpeTrainer(
    vocab_size=V, special_tokens=["<pad>", "<unk>", "<bos>", "<eos>"],
    initial_alphabet=pre_tokenizers.ByteLevel.alphabet(), show_progress=False))
PAD, EOS = tok.token_to_id("<pad>"), tok.token_to_id("<eos>")

def rope_tables(context, head_dim, base=10000.0):
    theta = base ** (-torch.arange(0, head_dim, 2).float() / head_dim)
    angle = torch.arange(context).float()[:, None] * theta
    return angle.cos(), angle.sin()

def apply_rope(x, cos, sin):                                  # cos、sin 已经按每个位置取好
    x1, x2 = x[..., 0::2], x[..., 1::2]
    return torch.stack([x1 * cos - x2 * sin, x1 * sin + x2 * cos], dim=-1).flatten(-2)

class Block(nn.Module):
    def __init__(self):
        super().__init__()
        self.norm1, self.norm2 = nn.RMSNorm(D), nn.RMSNorm(D)
        self.qkv = nn.Linear(D, 3 * D, bias=False)
        self.proj = nn.Linear(D, D, bias=False)
        self.gate = nn.Linear(D, 8 * D // 3, bias=False)
        self.up = nn.Linear(D, 8 * D // 3, bias=False)
        self.down = nn.Linear(8 * D // 3, D, bias=False)

    def attn_inputs(self, x, cos, sin):                       # x: [..., D] → q、k、v: [..., H, DH]
        q, k, v = (t.unflatten(-1, (H, DH)) for t in self.qkv(self.norm1(x)).split(D, dim=-1))
        return apply_rope(q, cos, sin), apply_rope(k, cos, sin), v

    def finish(self, x, y):                                   # y: 注意力的输出 [..., D]
        x = x + self.proj(y)
        h = self.norm2(x)
        return x + self.down(F.silu(self.gate(h)) * self.up(h))

    def forward(self, x, cos, sin):                           # 单条序列、一次算完：[B, T, D]
        q, k, v = (t.transpose(1, 2) for t in self.attn_inputs(x, cos[:, None], sin[:, None]))
        y = F.scaled_dot_product_attention(q, k, v, is_causal=True)
        return self.finish(x, y.transpose(1, 2).flatten(-2))

class Tiny(nn.Module):
    def __init__(self):
        super().__init__()
        self.embed = nn.Embedding(V, D)
        self.blocks = nn.ModuleList(Block() for _ in range(L))
        self.norm = nn.RMSNorm(D)
        cos, sin = rope_tables(CTX, DH)
        self.register_buffer("cos", cos, persistent=False)
        self.register_buffer("sin", sin, persistent=False)
        for m in self.modules():
            if isinstance(m, nn.Linear):
                nn.init.xavier_normal_(m.weight)
        nn.init.normal_(self.embed.weight, std=D ** -0.5)
        with torch.no_grad():
            for b in self.blocks:
                b.proj.weight.mul_((2 * L) ** -0.5)
                b.down.weight.mul_((2 * L) ** -0.5)

    def head(self, x):
        return self.norm(x) @ self.embed.weight.T              # 输出层与嵌入表共享权重

    def forward(self, idx):
        T = idx.shape[1]
        x = self.embed(idx)
        for b in self.blocks:
            x = b(x, self.cos[:T], self.sin[:T])
        return self.head(x)

def to_stream(texts):
    ids = []
    for t in texts:
        ids += tok.encode(t).ids + [EOS]
    return torch.tensor(ids)

train_ids = to_stream(train_poems)
# endregion model

# %%
# region train
def train_model(seed, steps=300, batch=32):
    torch.manual_seed(seed)                                   # 种子只决定初始参数
    model = Tiny()
    plan = torch.Generator().manual_seed(1234)                # batch 顺序和前几章相同
    starts = torch.randint(0, len(train_ids) - CTX - 1, (steps, batch), generator=plan)
    opt = torch.optim.AdamW([{"params": [p for p in model.parameters() if p.dim() >= 2], "weight_decay": 0.1},
                             {"params": [p for p in model.parameters() if p.dim() < 2], "weight_decay": 0.0}], lr=3e-3)
    for step in range(steps):
        idx = starts[step][:, None] + torch.arange(CTX + 1)
        out = model(train_ids[idx[:, :-1]])
        loss = F.cross_entropy(out.view(-1, V), train_ids[idx[:, 1:]].view(-1))
        opt.zero_grad(set_to_none=True)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        opt.step()
    return model.eval()

model = train_model(0)
n_params = sum(p.numel() for p in model.parameters())
print(f"参数 {n_params:,} 个，FP32 权重 {n_params * 4 / 2**20:.2f} MiB")

@torch.no_grad()
def reference(prompt, n):
    """单独跑一个请求：每一步把整段前缀重新送进模型，取 argmax。这是所有拼批结果要对齐的基准。"""
    ids = list(prompt)
    for _ in range(n):
        ids.append(model(torch.tensor([ids]))[0, -1].argmax().item())
    return ids[len(prompt):]
# endregion train

# %% [markdown]
# ## 2. 拼成矩形：padding、掩码和位置
#
# 最直接的批法：把几个提示词拼成一个 [B, T] 的矩形，短的用 `<pad>` 补齐。补在左边（left padding），
# 每一行的最后一个位置都是真 token，下一个 token 的 logits 都在最后一列。但要做对两件事：
#
# - **掩码**：真 token 不能看见 pad，注意力里要把 pad 所在的列遮掉；
# - **位置**：位置从这一行第一个真 token 开始数（`mask.cumsum(-1) - 1`），而不是矩形里的列号。
#
# 下面 4 个长度不同的提示词，按四种写法拼批，和单独跑的结果比较最后一个位置的 logits。
# “位置用列号”这一种在 RoPE 下结果不变：同一行的真 token 整体平移了同样的格数，RoPE 只看相对距离；
# 换成 GPT-2 那样按绝对位置查表的位置编码，它就会出错。

# %%
# region padded
@torch.no_grad()
def padded_last_logits(prompts, side="left", fix_positions=True, mask_pad=True):
    T = max(len(p) for p in prompts)
    ids = torch.full((len(prompts), T), PAD)
    real = torch.zeros(len(prompts), T, dtype=torch.bool)
    for i, p in enumerate(prompts):
        cols = slice(T - len(p), T) if side == "left" else slice(0, len(p))
        ids[i, cols], real[i, cols] = torch.tensor(p), True
    pos = (real.long().cumsum(-1) - 1).clamp(min=0) if fix_positions else torch.arange(T).expand(len(prompts), T)
    allowed = torch.ones(T, T, dtype=torch.bool).tril()[None]          # 因果：只看自己和前面
    if mask_pad:
        allowed = allowed & real[:, None, :]                            # 再遮掉 pad 所在的列
    allowed = allowed | torch.eye(T, dtype=torch.bool)                  # pad 行至少看自己，避免整行全遮
    x = model.embed(ids)
    for b in model.blocks:
        q, k, v = (t.transpose(1, 2) for t in b.attn_inputs(x, model.cos[pos][:, :, None], model.sin[pos][:, :, None]))
        y = F.scaled_dot_product_attention(q, k, v, attn_mask=allowed[:, None])
        x = b.finish(x, y.transpose(1, 2).flatten(-2))
    logits = model.head(x)
    return logits[:, -1], real.sum().item() / real.numel()

prompts4 = [tok.encode(t).ids[:n] for t, n in zip(val_poems[:4], (6, 12, 24, 40))]
single = torch.stack([model(torch.tensor([p]))[0, -1] for p in prompts4])
for name, kw in [("左补齐，位置和掩码都对", {}), ("左补齐，位置用列号", {"fix_positions": False}),
                 ("左补齐，不遮 pad", {"mask_pad": False}), ("右补齐，取最后一列", {"side": "right"})]:
    out, used = padded_last_logits(prompts4, **kw)
    same = (out.argmax(-1) == single.argmax(-1)).sum().item()
    print(f"{name:<14} 与单独跑的最大差 {(out - single).abs().max():.1e}  下一个 token 相同 {same}/4")
print(f"提示词长度 {[len(p) for p in prompts4]}：矩形里真 token 只占 {used:.0%}，其余位置是白算的 pad")
# endregion padded

# %% [markdown]
# ## 3. 一个最小的连续批处理引擎
#
# 矩形批要补齐，而且整批一起开始、一起结束。换一种组织方式：
#
# - 每个请求占一个**槽位**，槽位里放它自己的 KV cache 和已有长度，长短互不影响；
# - 一次前向的输入是一个列表 `[(槽位, 这次要送的 token), ...]`：在 decode 的请求送 1 个，
#   刚来的请求送整段（或一段）提示词；
# - 所有 token **首尾相接排成一行**（不补齐），线性层、前馈层对这一行一起算——权重读一遍，所有请求共用；
# - 注意力按请求分开算：每个请求只看自己槽位里的 K、V。
#
# 这就是 [Orca](https://www.usenix.org/conference/osdi22/presentation/yu) 的“选择性批处理”和今天推理框架里
# “varlen（变长）批”的思路。每次前向返回每个请求最后一个位置的 logits。

# %%
# region engine
class Engine:
    """最多 slots 个请求同时在跑；每个槽位有自己的 KV cache（[槽位, 头, 位置, 每头维度]）和长度。"""
    def __init__(self, slots):
        self.k = [torch.zeros(slots, H, CTX, DH) for _ in range(L)]
        self.v = [torch.zeros(slots, H, CTX, DH) for _ in range(L)]
        self.length = [0] * slots

    def free(self, slot):                                     # 请求结束，槽位留给下一个
        self.length[slot] = 0

    @torch.no_grad()
    def step(self, rows):
        """rows: [(槽位, 新 token 列表), ...]。返回每一行最后一个新位置的 logits，[len(rows), V]。"""
        slots, n = [s for s, _ in rows], [len(t) for _, t in rows]
        ids = torch.tensor([x for _, t in rows for x in t])               # 所有新 token 排成一行，不补齐
        pos = torch.cat([torch.arange(self.length[s], self.length[s] + c) for s, c in zip(slots, n)])
        owner = torch.repeat_interleave(torch.tensor(slots), torch.tensor(n))   # 每个 token 属于哪个槽位
        cos, sin = model.cos[pos][:, None], model.sin[pos][:, None]
        x = model.embed(ids)                                              # [所有新 token, D]
        for i, b in enumerate(model.blocks):
            q, k, v = b.attn_inputs(x, cos, sin)
            self.k[i][owner, :, pos], self.v[i][owner, :, pos] = k, v      # 写进各自的槽位
            ys, start = [], 0
            for s, c in zip(slots, n):                                    # 注意力逐个请求算
                end = self.length[s] + c
                mask = torch.arange(end)[None] <= pos[start:start + c, None]
                y = F.scaled_dot_product_attention(q[start:start + c].transpose(0, 1),
                                                   self.k[i][s, :, :end], self.v[i][s, :, :end], attn_mask=mask)
                ys.append(y.transpose(0, 1).flatten(-2))
                start += c
            x = b.finish(x, torch.cat(ys))
        for s, c in zip(slots, n):
            self.length[s] += c
        last = torch.tensor(n).cumsum(0) - 1                              # 每一行最后一个新位置
        return model.head(x[last])
# endregion engine

# %% [markdown]
# 先检查对不对：8 个请求同时进来，各生成 24 个 token；第 6 步时再加进 4 个新请求（它们的提示词和别人的 decode 在同一次前向里）。
# 每个请求的输出都要和 `reference` 单独跑的结果逐 token 相同。

# %%
# region engine-check
@torch.no_grad()
def run_together(prompt_list, join_at, n_new):
    eng, out, live = Engine(len(prompt_list)), [[] for _ in prompt_list], {}
    first = [i for i in range(len(prompt_list)) if join_at[i] == 0]
    logits = eng.step([(i, prompt_list[i]) for i in first])
    live = dict(zip(first, logits))
    for t in range(1, 200):
        rows = []
        for i, lg in live.items():
            out[i].append(lg.argmax().item())
            if len(out[i]) < n_new:
                rows.append((i, [out[i][-1]]))                    # 在 decode 的请求：送上一步的输出
        rows += [(i, prompt_list[i]) for i in range(len(prompt_list)) if join_at[i] == t]   # 新来的：送整段提示词
        if not rows:
            return out
        logits = eng.step(rows)
        live = {i: lg for (i, _), lg in zip(rows, logits)}

check_prompts = [tok.encode(p.split("，")[0] + "，").ids for p in val_poems[:12]]
outs = run_together(check_prompts, [0] * 8 + [6] * 4, 24)
same = sum(o == reference(p, 24) for o, p in zip(outs, check_prompts))
assert same == 12, "拼批以后的输出必须和单独跑逐 token 相同"
print(f"12 个请求（8 个先到、4 个第 6 步加入）：{same}/12 和单独跑逐 token 相同")
# endregion engine-check

# %% [markdown]
# ## 4. 为什么要批：一次前向带多少个请求
#
# 把 B 个请求的 decode 放进同一次前向，权重只读一遍。在同一台机器上量：缓存里每个请求已有 16 个位置，
# 一次前向给 B 个请求各算一个新 token，要多久（热身后测 3 组，取最快的一组）；再量一个请求一次送进 N 个 token 要多久。

# %%
# region batch-cost
def time_step(rows, repeat=30, past=16):
    best = float("inf")
    for _ in range(3):
        eng = Engine(max(s for s, _ in rows) + 1)
        eng.step([(s, [5] * past) for s, _ in rows])                      # 先填 past 个位置
        t0 = time.perf_counter()
        for _ in range(repeat):
            eng.step(rows)
            for s, t in rows:
                eng.length[s] -= len(t)                                   # 退回去，下一次还是同样的长度
        best = min(best, (time.perf_counter() - t0) / repeat)
    return best * 1000

eng_warm = Engine(1); eng_warm.step([(0, [5] * 8)])                       # 热身
batch_ms = {B: time_step([(s, [5]) for s in range(B)]) for B in (1, 2, 4, 8, 16, 32)}
for B, ms in batch_ms.items():
    print(f"[计时，本机] 一次前向带 {B:>2} 个请求：{ms:.2f} ms，摊到每个 token {ms / B:.3f} ms")
prefill_ms = {N: time_step([(0, [5] * N)]) for N in (1, 8, 16, 32, 48)}
for N, ms in prefill_ms.items():
    print(f"[计时，本机] 一个请求一次送进 {N:>2} 个 token：{ms:.2f} ms")
weight_mib = n_params * 4 / 2**20
for B in (1, 8, 32):
    print(f"一次前向带 {B:>2} 个请求：权重读一遍 {weight_mib:.2f} MiB，摊到每个 token {weight_mib / B:.2f} MiB")
# endregion batch-cost
log["batch_ms"], log["prefill_ms"] = batch_ms, prefill_ms

# %% [markdown]
# ## 5. 请求流和成本模型
#
# 调度要在“同一份请求流”上比较。请求流由单独的随机数生成器预先排好：到达时间是泊松过程，
# 四分之三是短提示词（一首诗的第一句）、要生成 8～40 个 token；四分之一是长提示词（一首诗的前 40 个 token）、
# 只生成 4～12 个 token。三种随机种子各一份，两档负载用同一批请求，只把到达间隔拉开或压紧。
#
# 时间用一个写明了的**成本模型**来算：一次前向的时间是 $\max(1, N/K)$ 个单位，N 是这次前向里新 token 的总数，
# K=16。意思是：一次前向至少花 1 个单位（读一遍权重），新 token 不超过 K 个时几乎不多花，超过以后按 token 数线性变长。
# 这是第 28 章屋顶线的形状；真实 GPU 上拐点在几百个 token，这里按本章提示词的长度把它缩小到 16。

# %%
# region workload
K = 16                                                        # 成本模型：一次前向能“顺带”处理的 token 数
def step_cost(n_tokens, k=K):
    return max(1.0, n_tokens / k)

def make_requests(seed, n=40):
    g = torch.Generator().manual_seed(seed)
    reqs, t = [], 0.0
    pool = val_poems[seed * 100:(seed + 1) * 100]
    for i in range(n):
        t += -math.log(1 - torch.rand(1, generator=g).item())   # 指数分布的到达间隔，平均 1 个单位
        text = pool[i]
        if torch.rand(1, generator=g).item() < 0.25:
            prompt = tok.encode(text).ids[:40]
            n_out = int(torch.randint(4, 13, (1,), generator=g))
        else:
            prompt = tok.encode(text.split("，")[0] + "，").ids
            n_out = int(torch.randint(8, 41, (1,), generator=g))
        reqs.append({"id": i, "gap_sum": t, "prompt": prompt, "n_out": n_out})
    return reqs

STREAM_SEEDS = (0, 1, 2)
streams = {s: make_requests(s) for s in STREAM_SEEDS}
refs = {s: [reference(r["prompt"], r["n_out"]) for r in streams[s]] for s in STREAM_SEEDS}
r0 = streams[0]
print(f"每份请求流 {len(r0)} 个请求；种子 0：长提示词 {sum(len(r['prompt']) > 20 for r in r0)} 个，"
      f"提示词共 {sum(len(r['prompt']) for r in r0)} 个 token，要生成 {sum(r['n_out'] for r in r0)} 个 token")
# endregion workload

# %% [markdown]
# 调度器每次做一个决定：这一次前向里放谁、各送几个 token。四种策略：
#
# - **静态批**：等凑够 B 个请求（流的末尾凑不够就等最后一个到）再一起开始，整批一起结束；
#   早结束的请求不离开，它的位置照算（矩形批里就是这样），记作“白算的行”。
# - **动态批**：引擎空闲时，从队首请求到达算起最多等 W 个单位，到时有多少收多少（最多 B 个），之后同样整批一起结束。
# - **连续批**：每次前向之后，结束的请求立刻离开，等待的请求立刻补进空槽位，它的整段提示词和别人的 decode 放在同一次前向里。
# - **连续批 + 分块 prefill**：每次前向最多 K 个新 token。先给在 decode 的请求各 1 个，
#   剩下的额度按到达顺序分给提示词，没送完的下一次接着送（transformers 的 FIFO 调度器就是这个顺序）。
#
# 每次前向都真的在引擎上跑，最后检查每个请求的输出都和单独跑相同。

# %%
# region schedulers
@torch.no_grad()
def serve(reqs, ref, policy, slots=8, window=4.0, scale=1.0, k=K):
    """按 policy 调度一份请求流。scale 把到达间隔整体拉长（负载变轻），k 是成本模型的拐点。返回每个请求的时间记录和统计。"""
    arrive = [r["gap_sum"] * scale for r in reqs]
    eng, clock = Engine(slots), 0.0
    waiting, running, free_slots = [], {}, list(range(slots))           # running: 槽位 → 请求状态
    nxt = 0                                                             # 下一个还没到的请求
    rec = {r["id"]: {"arrive": arrive[i], "tokens": [], "times": []} for i, r in enumerate(reqs)}
    stats = {"steps": 0, "wasted_rows": 0, "tokens": 0}
    batch_open = False                                                  # 静态 / 动态批：当前这一批还没结束
    while nxt < len(reqs) or waiting or running:
        while nxt < len(reqs) and arrive[nxt] <= clock:
            waiting.append(nxt); nxt += 1
        # ---- 决定谁进来 ----
        if policy in ("static", "dynamic") and not batch_open and waiting:
            full = len(waiting) >= slots or nxt == len(reqs)
            timeout = policy == "dynamic" and clock >= arrive[waiting[0]] + window
            if full or timeout:
                for i in waiting[:slots]:
                    running[free_slots.pop(0)] = {"i": i, "todo": list(reqs[i]["prompt"]), "done": False}
                waiting, batch_open = waiting[slots:], True
        if policy.startswith("continuous"):
            while waiting and free_slots:
                i = waiting.pop(0)
                running[free_slots.pop(0)] = {"i": i, "todo": list(reqs[i]["prompt"]), "done": False}
        if not running:                                                 # 没事可做：时间跳到下一个事件
            events = [arrive[nxt]] if nxt < len(reqs) else []
            if policy == "dynamic" and waiting:
                events.append(arrive[waiting[0]] + window)
            clock = max(clock, min(events))
            continue
        # ---- 决定这次前向里每个请求送几个 token ----
        rows, budget = [], k if policy == "continuous-chunked" else None
        for s, st in sorted(running.items(), key=lambda kv: (len(kv[1]["todo"]) > 0, kv[1]["i"])):  # decode 在前
            if st["done"]:
                continue
            if not st["todo"]:
                take = [rec[reqs[st["i"]]["id"]]["tokens"][-1]]          # decode：送上一步的输出
            else:
                take = st["todo"] if budget is None else st["todo"][:max(budget, 0)]
            if budget is not None:
                if not take:
                    continue
                budget -= len(take)
            rows.append((s, take))
        wasted = sum(st["done"] for st in running.values())             # 早结束、但还占着位置的行
        n_tokens = sum(len(t) for _, t in rows) + wasted
        logits = eng.step(rows)
        clock += step_cost(n_tokens, k)
        stats["steps"] += 1; stats["wasted_rows"] += wasted; stats["tokens"] += n_tokens
        # ---- 收结果 ----
        for (s, take), lg in zip(rows, logits):
            st = running[s]
            if st["todo"]:
                st["todo"] = st["todo"][len(take):]
                if st["todo"]:
                    continue                                            # 提示词还没送完，这一步不出 token
            r = rec[reqs[st["i"]]["id"]]
            r["tokens"].append(lg.argmax().item()); r["times"].append(clock)
            if len(r["tokens"]) == reqs[st["i"]]["n_out"]:
                st["done"] = True
        for s in [s for s, st in running.items() if st["done"]]:
            if policy.startswith("continuous") or all(x["done"] for x in running.values()):
                del running[s]; eng.free(s); free_slots.append(s)
        if not running:
            batch_open = False
    assert all(rec[r["id"]]["tokens"] == ref[j] for j, r in enumerate(reqs)), "调度不能改变任何请求的输出"
    return rec, stats
# endregion schedulers

# %% [markdown]
# 每个请求记下到达时间和每个 token 出来的时刻，算出：
# TTFT（到达到第一个 token）、TPOT（之后平均每个 token 的间隔）、最大间隔（用户看到的最长一次“卡住”）、
# 整份请求流的吞吐（输出 token 数 ÷ 从第一个到达到最后一个完成的时间）。

# %%
# region metrics
def pct(xs, q):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(q * (len(xs) - 1))))]

def summarize(rec, stats):
    ttft = [r["times"][0] - r["arrive"] for r in rec.values()]
    tpot = [(r["times"][-1] - r["times"][0]) / (len(r["times"]) - 1) for r in rec.values() if len(r["times"]) > 1]
    gap = [max(b - a for a, b in zip(r["times"], r["times"][1:])) for r in rec.values() if len(r["times"]) > 1]
    span = max(r["times"][-1] for r in rec.values()) - min(r["arrive"] for r in rec.values())
    out = sum(len(r["times"]) for r in rec.values())
    return {"ttft50": pct(ttft, .5), "ttft90": pct(ttft, .9), "tpot50": pct(tpot, .5), "tpot90": pct(tpot, .9),
            "gap_max": max(gap), "throughput": out / span, "wasted": stats["wasted_rows"] / stats["tokens"],
            "steps": stats["steps"], "ttft": ttft, "tpot": tpot, "span": span}
# endregion metrics

# %% [markdown]
# ## 6. 三种批法，同一份请求流
#
# 槽位 B=8，动态批最多等 W=4 个单位。两档负载：平均每 2 个单位到达 1 个请求（重），以及每 8 个单位 1 个（轻）。
# 每格是 3 份请求流的平均，方括号是范围。

# %%
# region compare
POLICIES = {"static": "静态批", "dynamic": "动态批", "continuous": "连续批"}
HEAVY, LIGHT = 2.0, 8.0
LOADS = {"重": HEAVY, "轻": LIGHT}
results = {}
t_all = time.perf_counter()
for load, scale in LOADS.items():
    for pol, name in POLICIES.items():
        rows = [summarize(*serve(streams[s], refs[s], pol, scale=scale)) for s in STREAM_SEEDS]
        results[(load, pol)] = rows
        f = lambda key, fmt="{:.1f}": f"{fmt.format(sum(r[key] for r in rows) / 3)} [{fmt.format(min(r[key] for r in rows))}, {fmt.format(max(r[key] for r in rows))}]"
        print(f"{load}负载 {name}：TTFT 中位 {f('ttft50')}  P90 {f('ttft90')}  │  TPOT 中位 {f('tpot50', '{:.2f}')}  │  "
              f"吞吐 {f('throughput', '{:.2f}')} token/单位  │  白算 {f('wasted', '{:.0%}')}")
print("全部请求的输出都和单独跑逐 token 相同")
print(f"[计时，本机] 6 组 × 3 份请求流在引擎上实际跑完用了 {time.perf_counter() - t_all:.1f} s")
# endregion compare
log["compare"] = {f"{k[0]}-{k[1]}": [{kk: vv for kk, vv in r.items() if kk not in ("ttft", "tpot")} for r in v]
                  for k, v in results.items()}
log["cdf"] = {pol: {"ttft": results[("重", pol)][0]["ttft"], "tpot": results[("重", pol)][0]["tpot"]} for pol in POLICIES}

# %% [markdown]
# ## 7. 长提示词卡住别人：分块 prefill
#
# 连续批里，一个 40 个 token 的提示词进来时，它和所有正在 decode 的请求在同一次前向里，
# 这次前向按成本模型要花 $\max(1, (40+7)/16)\approx 2.9$ 个单位，正在 decode 的 7 个请求这一步都要等这么久。
# 分块 prefill 把每次前向的新 token 限制在 K=16 个以内，提示词分几次送完，decode 每一步都能继续。

# %%
# region chunked
for pol, name in [("continuous", "连续批"), ("continuous-chunked", "连续批 + 分块 prefill")]:
    rows = [summarize(*serve(streams[s], refs[s], pol, scale=HEAVY)) for s in STREAM_SEEDS]
    results[("重", pol)] = rows
    f = lambda key, fmt="{:.2f}": f"{fmt.format(sum(r[key] for r in rows) / 3)} [{fmt.format(min(r[key] for r in rows))}, {fmt.format(max(r[key] for r in rows))}]"
    print(f"{name:<12} 最长卡顿 {f('gap_max')}  TPOT P90 {f('tpot90')}  TTFT 中位 {f('ttft50')}  P90 {f('ttft90')}  吞吐 {f('throughput')}")
pairs = zip(results[("重", "continuous")], results[("重", "continuous-chunked")])
print("逐份请求流的 TTFT 中位：" + "  ".join(f"种子 {s} {a['ttft50']:.1f} → {b['ttft50']:.1f}" for s, (a, b) in zip(STREAM_SEEDS, pairs)))
# endregion chunked
log["chunked"] = {pol: [{kk: vv for kk, vv in r.items() if kk not in ("ttft", "tpot")} for r in results[("重", pol)]]
                  for pol in ("continuous", "continuous-chunked")}
timeline = {pol: serve(streams[0], refs[0], pol, scale=HEAVY)[0] for pol in ("static", "continuous", "continuous-chunked")}
log["timeline"] = {pol: [{"arrive": r["arrive"], "times": r["times"], "prompt": len(streams[0][i]["prompt"])}
                         for i, r in rec.items()] for pol, rec in timeline.items()}

# %% [markdown]
# ## 8. 批开多大：吞吐和延迟的交换
#
# 槽位数 B 决定最多多少个请求同时在跑。为了让大的 B 真的被用满，这里把到达压到每个单位 1 个请求（过载），
# 用不分块的连续批，把 B 从 1 调到 32。再加一个时延目标（SLO）：TTFT 不超过 20 个单位、TPOT 不超过 1.5 个单位，
# 两个都满足的请求，它的 token 才算进 goodput。

# %%
# region slots
SLO_TTFT, SLO_TPOT, OVERLOAD = 20.0, 1.5, 1.0
sweep = {}
for B in (1, 2, 4, 8, 16, 32):
    rows = []
    for s in STREAM_SEEDS:
        rec, stats = serve(streams[s], refs[s], "continuous", slots=B, scale=OVERLOAD)
        m = summarize(rec, stats)
        ok = [r for r in rec.values() if r["times"][0] - r["arrive"] <= SLO_TTFT and
              (len(r["times"]) < 2 or (r["times"][-1] - r["times"][0]) / (len(r["times"]) - 1) <= SLO_TPOT)]
        m["goodput"] = sum(len(r["times"]) for r in ok) / m["span"]
        m["ok"] = len(ok)
        rows.append(m)
    sweep[B] = rows
    avg = lambda key: sum(r[key] for r in rows) / 3
    good = [r["goodput"] for r in rows]
    print(f"B={B:>2}：吞吐 {avg('throughput'):.2f}  goodput {avg('goodput'):.2f} [{min(good):.2f}, {max(good):.2f}]（达标 {avg('ok'):.1f}/40 个请求）  "
          f"TTFT 中位 {avg('ttft50'):6.1f}  TPOT 中位 {avg('tpot50'):.2f}  P90 {avg('tpot90'):.2f}")
# endregion slots
log["slots"] = {B: [{kk: vv for kk, vv in r.items() if kk not in ("ttft", "tpot")} for r in rows] for B, rows in sweep.items()}

# %% [markdown]
# 成本模型的拐点 K=16 是本章定的。换成 8 和 32 再比一次重负载下四种策略的 TTFT 中位数（3 份请求流平均），
# 看排序会不会变。

# %%
# region sensitivity
sens = {}
for k in (8, 16, 32):
    row = {}
    for pol in ("static", "dynamic", "continuous", "continuous-chunked"):
        row[pol] = sum(summarize(*serve(streams[s], refs[s], pol, scale=HEAVY, k=k))["ttft50"] for s in STREAM_SEEDS) / 3
    sens[k] = row
    print(f"K={k:>2}：TTFT 中位  静态 {row['static']:6.1f}  动态 {row['dynamic']:6.1f}  连续 {row['continuous']:5.1f}  连续 + 分块 {row['continuous-chunked']:5.1f}")
# endregion sensitivity
log["sensitivity"] = sens

# %%
with open("batching_log.json", "w", encoding="utf-8") as f:
    json.dump(log, f, ensure_ascii=False)
print("已写出 batching_log.json")
