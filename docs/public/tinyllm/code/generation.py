# %% [markdown]
# # 第 25 章：自回归生成
#
# 配套教案：https://lewislau86.github.io/tinyllm/generation
#
# 从上到下运行即可（`python generation.py`），CPU 上约一分半（其中训练 1200 步约 80 秒）。
# 需要安装 PyTorch 和 `tokenizers`。
# 这个文件是本章代码的唯一来源：教案中的代码片段由 `# region 名字` / `# endregion 名字`
# 标记的区域直接引用，notebook 也由它生成（scripts/build-tinyllm-code.py）。
#
# 本章把“模型输出 logits”到“屏幕上出现一个字”之间隔的那几步拆开：温度、top-k、top-p、
# 重复惩罚、随机种子与停止条件，最后把格式写进掩码的约束解码。

# %%
# region imports
import json
import math

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
# ## 1. 从 logits 到概率：温度只是除一下
#
# 模型对下一个位置输出的是每个 token 的原始打分（logits），不是概率。要变成概率得先过 softmax。
# 温度就是先把打分整体除以 $T$，再取 softmax：
#
# $$p_i = \frac{\exp(z_i / T)}{\sum_j \exp(z_j / T)}$$
#
# 手写一组六个候选的打分，用三个温度算一遍。同时算两件后面一直要用到的事：
# **熵**（这个分布有多平，越大越难猜）和 **top-p 需要几个候选**（按概率从大到小累加到 0.9 为止）。

# %%
# region hand
tokens = ["床", "前", "明", "月", "光", "霜"]
hand_logits = torch.tensor([4.0, 2.0, 1.0, 0.5, -1.0, -2.0])

def probs_at(z, T=1.0):
    return F.softmax(z / T, dim=-1)

def entropy(p):
    return float(-(p * p.clamp_min(1e-12).log()).sum())

def nucleus_size(p, threshold=0.9):
    """按概率从大到小累加，达到 threshold 时用了几个候选。"""
    ordered = p.sort(descending=True).values
    return int((ordered.cumsum(0) < threshold).sum().item()) + 1

for T in (0.5, 1.0, 2.0):
    p = probs_at(hand_logits, T)
    print(f"T={T:<4} 概率 {[round(float(v), 3) for v in p]}  熵 {entropy(p):.3f}  top-p(0.9) 用到 {nucleus_size(p)} 个")
# endregion hand

# %% [markdown]
# 除以一个正数不改变谁大谁小，只改变差距：$T<1$ 把高分推得更高、低分压得更低，$T>1$ 抹平差距。
# $T \to 0$ 时概率全落到最大那一个，就是贪心解码。熵从 0.115 涨到 1.358，说明同一个位置的“犹豫程度”
# 完全由 $T$ 决定，模型本身在里面没有变化。

# %% [markdown]
# ## 2. top-k 与 top-p：截掉长尾再抽样
#
# 直接在整张词表上抽样，偶尔会抽到概率极低的字，读起来就是错字。两种截法都先砍掉长尾：
# top-k 留打分最高的 $k$ 个；top-p 留累计概率刚好达到 $p$ 的最小集合，其余置零后重新归一化。
# 它们的区别在集合大小是否随位置变化。

# %%
# region truncate
def truncate(p, k=None, top_p=None):
    z = p.clone()
    if k is not None and k < len(z):
        mask = torch.zeros_like(z, dtype=torch.bool)
        mask[z.topk(k).indices] = True
        z = z.masked_fill(~mask, 0.0)
    if top_p is not None:
        ordered, order = z.sort(descending=True)
        drop = ordered.cumsum(0) - ordered > top_p     # 去掉“多它一个就超过 p”的部分
        mask = torch.zeros_like(z, dtype=torch.bool)
        mask[order] = ~drop
        z = z.masked_fill(~mask, 0.0)
    return z / z.sum()

peaked = F.softmax(torch.tensor([6.0, 5.0, 0.0, -1.0, -2.0, -3.0]), dim=-1)
flat = F.softmax(torch.tensor([1.2, 1.1, 1.0, 0.9, 0.8, 0.7]), dim=-1)
for name, p in [("尖峰", peaked), ("平坦", flat)]:
    keep_k = int((truncate(p, k=3) > 0).sum())
    keep_p = int((truncate(p, top_p=0.9) > 0).sum())
    print(f"{name}分布：top-k=3 留 {keep_k} 个，top-p=0.9 留 {keep_p} 个，熵 {entropy(p):.3f}")
# endregion truncate

# %% [markdown]
# 尖峰分布里 top-p 只留 2 个，平坦分布里留 6 个；top-k 一律留 3 个。
# 诗句里“句末必然是标点”的位置分布很尖，“逗号之后该起什么字”的位置分布很平，
# 下一节会在同一个模型上看到这两种位置的差距有多大。这正是 top-p 比 top-k 更常用的原因。

# %% [markdown]
# ## 3. 训练一个小模型，用真实分布做实验
#
# 前两节的数字是手写的。要观察采样参数的实际效果，得有一个真的会写诗的小模型。
# 这里沿用[第 12 章](https://lewislau86.github.io/tinyllm/tinyllm-model)的配方，把配置缩小到 CPU 能在一分多钟内跑完：
# 词表 2048、宽度 128、4 层、4000 首唐诗、1200 步。它写得不好，但足够用来比较采样参数——
# 本章的结论都不依赖它写得好不好。

# %%
# region train
poems = load_poems(4000)
train_poems = [p["text"] for p in poems if p["split"] == "train"]
val_poems = [p["text"] for p in poems if p["split"] == "val"]

V, D, L, H, CTX = 2048, 128, 4, 4, 64
tok = Tokenizer(models.BPE())
tok.pre_tokenizer = pre_tokenizers.ByteLevel(add_prefix_space=False)
tok.decoder = decoders.ByteLevel()
tok.train_from_iterator(train_poems, trainers.BpeTrainer(
    vocab_size=V, special_tokens=["<pad>", "<unk>", "<bos>", "<eos>"],
    initial_alphabet=pre_tokenizers.ByteLevel.alphabet(), show_progress=False))
EOS = tok.token_to_id("<eos>")

def rope_tables(context, head_dim, base=10000.0):
    theta = base ** (-torch.arange(0, head_dim, 2).float() / head_dim)
    angle = torch.arange(context).float()[:, None] * theta
    return angle.cos(), angle.sin()

def apply_rope(x, cos, sin):
    T = x.shape[-2]
    cos, sin = cos[:T], sin[:T]
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

    def forward(self, x, cos, sin):
        B, T, _ = x.shape
        q, k, v = (t.view(B, T, H, D // H).transpose(1, 2) for t in self.qkv(self.norm1(x)).split(D, dim=-1))
        y = F.scaled_dot_product_attention(apply_rope(q, cos, sin), apply_rope(k, cos, sin), v, is_causal=True)
        x = x + self.proj(y.transpose(1, 2).reshape(B, T, D))
        h = self.norm2(x)
        return x + self.down(F.silu(self.gate(h)) * self.up(h))

class Tiny(nn.Module):
    def __init__(self):
        super().__init__()
        self.embed = nn.Embedding(V, D)
        self.blocks = nn.ModuleList(Block() for _ in range(L))
        self.norm = nn.RMSNorm(D)
        cos, sin = rope_tables(CTX, D // H)
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

    def forward(self, idx):
        x = self.embed(idx)
        for b in self.blocks:
            x = b(x, self.cos, self.sin)
        return self.norm(x) @ self.embed.weight.T

def to_stream(texts):
    ids = []
    for t in texts:
        ids += tok.encode(t).ids + [EOS]
    return torch.tensor(ids)

train_ids, val_ids = to_stream(train_poems), to_stream(val_poems)
torch.manual_seed(0)
model = Tiny()
steps, batch = 1200, 32
plan = torch.Generator().manual_seed(1234)          # batch 计划：只由这个生成器决定
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

@torch.no_grad()
def val_loss():
    n = (len(val_ids) - 1) // CTX * CTX
    xs, ys = val_ids[:n].view(-1, CTX), val_ids[1:n + 1].view(-1, CTX)
    total = sum(F.cross_entropy(model(xs[i:i + 32]).flatten(0, 1), ys[i:i + 32].flatten(), reduction="sum").item()
                for i in range(0, len(xs), 32))
    return total / ys.numel()

train_chars = set("".join(train_poems))
print(f"{sum(p.numel() for p in model.parameters()):,} 个参数，{steps} 步后验证损失 {val_loss():.3f} nats/token")
print(f"训练集里不同的字 {len(train_chars)}，词表 {V}")
# endregion train

# %% [markdown]
# ## 4. 同一个模型，每个位置的难度差很多
#
# 拿一句熟悉的诗逐字喂给模型，看它预测下一个字时的熵和 top-p 需要的候选数。
# 每个位置做一次前向，取最后一个位置的 logits。

# %%
# region difficulty
@torch.no_grad()
def next_logits(text):
    return model(torch.tensor([tok.encode(text).ids]))[0, -1]

def top_tokens(z, n=3):
    p = probs_at(z)
    values, index = p.topk(n)
    return " ".join(f"{tok.decode([int(i)])!s}{float(v):.2f}" for v, i in zip(values, index))

rows = []
for prompt in ("春眠不觉晓，", "空山不见人，"):
    ids = tok.encode(prompt).ids
    print(f"\n提示词“{prompt}”")
    for k in range(len(ids) - 1):                    # 只看给出字之后的位置，最后一个是标点后的交界
        prefix = tok.decode(ids[:k + 1])
        z = next_logits(prefix)
        p = probs_at(z)
        rows.append({"prompt": prompt, "pos": k, "char": tok.decode([ids[k]]),
                     "entropy": round(entropy(p), 3), "nucleus": nucleus_size(p)})
        print(f"  “{tok.decode([ids[k]])!s}”之后：熵 {entropy(p):5.2f}  "
              f"top-p(0.9) {nucleus_size(p):4d} 个  前三个 {top_tokens(z)}")
# endregion difficulty

# %% [markdown]
# 规律很清楚：句末标点的位置几乎已经确定，熵落到 1 左右，top-p 只要一两个候选；
# 逗号之后要起新句，熵在 6 上下，top-p 要几百个候选才凑够 90%。
# 固定的 top-k 在这两种位置上要么太宽、要么太窄；top-p 自动跟着分布走。

# %% [markdown]
# ## 5. 温度把整条分布拉开或压扁
#
# 挑一个犹豫的位置（逗号之后），把同一个 logits 用不同温度换算成概率，比较熵和需要的候选数。

# %%
# region temps
z_mid = next_logits("春眠不觉晓，")
temp_table = {}
for T in (0.3, 0.5, 1.0, 1.5, 2.0):
    p = probs_at(z_mid, T)
    temp_table[T] = {"entropy": round(entropy(p), 3), "nucleus": nucleus_size(p),
                     "top": [[tok.decode([int(i)]), round(float(v), 4)] for v, i in zip(p.topk(5).values, p.topk(5).indices)]}
    top5 = "  ".join(f"{tok.decode([int(i)])!s}{float(v):.3f}" for v, i in zip(p.topk(5).values, p.topk(5).indices))
    print(f"T={T:<4} 熵 {entropy(p):5.2f}  top-p(0.9) 需要 {nucleus_size(p):4d} 个  前五个 {top5}")
# endregion temps

# %% [markdown]
# 温度不改模型，只改“从模型已有的判断里取多宽的样本”。
# 把温度调高不会让诗更有文采，只会让低分候选更容易被抽到；调低也不会让模型多知道什么，
# 只是更快地退化成贪心。写诗时常见的 0.7～1.0，是在“有变化”和“不出错字”之间的折中，
# 不是一条通用定律。

# %% [markdown]
# ## 6. 抽样、复现与停止条件
#
# 生成循环只有四步：前向拿最后一个位置的 logits → 可选地改打分（惩罚、掩码）→ 除以温度、截断、softmax → 按概率抽一个。
# 抽完接到序列末尾，直到遇到 `<eos>` 或到 `max_new_tokens`。
# 贪心解码每次取最大，输出固定；抽样要复现同一段文字，就得固定随机数生成器的初始状态。

# %%
# region penalty
def apply_repetition_penalty(logits, generated, penalty):
    """乘法惩罚：出现过的 token，正打分除以 penalty，负打分乘 penalty。"""
    z = logits.clone()
    if not generated or penalty == 1.0:
        return z
    seen = torch.tensor(sorted(set(generated)), dtype=torch.long)
    hit = z[seen]
    z[seen] = torch.where(hit > 0, hit / penalty, hit * penalty)
    return z
# endregion penalty

# region sample
@torch.no_grad()
def generate(prompt, max_new_tokens=40, T=1.0, k=None, top_p=None, penalty=1.0,
             allowed=None, generator=None, greedy=False, ban_eos=False):
    idx = torch.tensor([tok.encode(prompt).ids])
    start = len(prompt)                              # 模板位置按“字符”数，不按 token 数
    out = []
    for _ in range(max_new_tokens):
        z = model(idx[:, -CTX:])[0, -1].clone()
        z = apply_repetition_penalty(z, out, penalty)
        if allowed is not None:                      # 约束解码：把不合法的 token 打分设成 -inf
            allow = allowed(start + len(tok.decode(out)))
            if not allow:
                break                                # 模板已经写完，停下
            mask = torch.full_like(z, float("-inf"))
            mask[allow] = z[allow]
            z = mask
        if greedy:
            nxt = int(z.argmax())
        else:
            p = truncate(F.softmax(z / T, dim=-1), k=k, top_p=top_p)
            nxt = int(torch.multinomial(p, 1, generator=generator))
        if nxt == EOS and not ban_eos:
            break
        out.append(nxt)
        idx = torch.cat([idx, torch.tensor([[nxt]])], dim=1)
    return tok.decode(out)
# endregion sample

PROMPT = "春眠不觉晓，"
print("贪心             ", generate(PROMPT, greedy=True))
g = torch.Generator().manual_seed(3)
print("T=0.9，种子 3     ", generate(PROMPT, T=0.9, top_p=0.95, generator=g))
g = torch.Generator().manual_seed(3)
print("T=0.9，种子 3 再跑 ", generate(PROMPT, T=0.9, top_p=0.95, generator=g), " ← 与上一行完全相同")
g = torch.Generator().manual_seed(4)
print("T=0.9，种子 4     ", generate(PROMPT, T=0.9, top_p=0.95, generator=g), " ← 换个种子就不同")

# %% [markdown]
# “固定种子”保证的是**同一个随机数流**，不保证跨硬件完全一致：
# 浮点求和顺序会随 batch 大小和并行方式变化，同一个种子在大模型上偶尔也会差一个 token。
# 需要严格可复现的评估，就用贪心解码——这是[课程总览](https://lewislau86.github.io/tinyllm/#mainline-choices)主线里写下的选择。

# %% [markdown]
# ## 7. 温度调高以后，生僻字变多了
#
# 温度的实际影响要看整段生成。同一个开头、同一批种子，只改温度，各写满 24 个字（不让它提前停），
# 数一件事：生成的字里有多少**不在训练集中**——这些多半是字节 token 拼出来的怪字。

# %%
# region temp-eval
temp_quality = {}
for T in (0.5, 0.9, 1.3, 1.8):
    texts = [generate(PROMPT, max_new_tokens=24, T=T, top_p=0.95, ban_eos=True,
                      generator=torch.Generator().manual_seed(500 + i)) for i in range(8)]
    chars = [c for t in texts for c in t if not c.isspace()]
    outside = sum(c not in train_chars for c in chars) / len(chars)
    per = sum(len(t) for t in texts) / len(texts)
    temp_quality[T] = {"outside": round(outside, 3), "per_poem": round(per, 1), "sample": texts[0]}
    print(f"T={T:<4} 训练集外的字占 {outside:.3f}  平均每首 {per:.1f} 字  例：{texts[0]}")
# endregion temp-eval

# %% [markdown]
# ## 8. 重复惩罚：改的不是概率，是打分
#
# 生成古诗最常见的问题是同一句反复出现。重复惩罚在抽样之前直接改 logits：
# 已经出现过的 token 打折扣。乘法形式（Hugging Face 的 `repetition_penalty`）把正 logits 除以系数、负 logits 乘以系数。
# 下面用贪心解码（不受随机性干扰），从同一个开头连写 48 个字，数两字组的多样性。

# %%
# %%
# region penalty-eval
penalty_table = {}
for penalty in (1.0, 1.2, 1.4, 1.6):
    text = generate("何人不可归，", max_new_tokens=48, penalty=penalty, greedy=True, ban_eos=True)
    bigrams = [text[i:i + 2] for i in range(len(text) - 1)]
    diversity = len(set(bigrams)) / len(bigrams)
    penalty_table[penalty] = {"diversity": round(diversity, 3), "text": text}
    print(f"penalty={penalty:<4} 不同两字组占 {diversity:.3f}  {text}")
# endregion penalty-eval

# %% [markdown]
# ## 9. 约束解码：把格式写进掩码
#
# 前面几节都是接受模型给出的分布，只在里面挑。如果格式是确定的——五言绝句：四句、每句五字、句末标点——
# 可以在**每一步**只允许合法的 token：其余位置打分设成 $-\infty$，softmax 后概率为 0，采样永远抽不到。
#
# 这是约束解码的最小版本。它不改模型，也不保证内容对，只保证格式对；代价是每步多算一次掩码。
# 生产系统用有限状态机或文法来表示允许集合，支持 JSON、正则等复杂格式，原理与这里相同。

# %%
# region guided
def single_char_tokens():
    """词表里所有“解码出来正好是一个汉字”的 token。"""
    return [i for i in range(V) if len(tok.decode([i])) == 1 and "一" <= tok.decode([i]) <= "鿿"]

HANZI = single_char_tokens()
COMMA = [i for i in range(V) if tok.decode([i]) == "，"]
STOP = [i for i in range(V) if tok.decode([i]) == "。"]
print(f"词表 {V} 个 token 里，单字 {len(HANZI)} 个，逗号 {len(COMMA)} 个，句号 {len(STOP)} 个")

def poem_allowed(pos):
    """五言绝句的模板：每 6 个字符一组 = 五字 + 一个标点；前三个用逗号，最后用句号，写满 24 个字符为止。"""
    if pos >= 24:
        return []
    if pos % 6 == 5:
        return COMMA if pos < 18 else STOP
    return HANZI

def valid_poem(text, offset):
    """从 offset 开始，按“五字一个标点、最后一句用句号”核对整段。"""
    if len(text) != 24 - offset:
        return False
    for i, ch in enumerate(text):
        pos = offset + i
        if pos % 6 == 5:
            if ch != ("，" if pos < 18 else "。"):
                return False
        elif not ("一" <= ch <= "鿿"):
            return False
    return True

free, guided = [], []
for i, poem in enumerate(val_poems[:12]):
    head = poem[:6]                                   # 五字加一个逗号
    free.append(generate(head, max_new_tokens=30, T=0.9, top_p=0.95,
                         generator=torch.Generator().manual_seed(200 + i)))
    guided.append(generate(head, max_new_tokens=30, T=0.9, top_p=0.95,
                           allowed=poem_allowed, generator=torch.Generator().manual_seed(200 + i)))
print(f"不加约束：{sum(valid_poem(t, 6) for t in free)}/12 首格式合法；加了掩码：{sum(valid_poem(t, 6) for t in guided)}/12 首")
print("不加约束的一首：", free[0])
print("加掩码的一首：  ", guided[0])
# endregion guided

# %% [markdown]
# ## 10. 把这一章的数字存下来
#
# 网站上的配图用这一份记录画，图里的数字和上面的输出是同一批。

# %%
# region export
data = {
    "hand": {"tokens": tokens, "logits": [float(x) for x in hand_logits],
             "probs": {str(T): [round(float(v), 4) for v in probs_at(hand_logits, T)] for T in (0.5, 1.0, 2.0)},
             "entropy": {str(T): round(entropy(probs_at(hand_logits, T)), 3) for T in (0.5, 1.0, 2.0)},
             "nucleus": {str(T): nucleus_size(probs_at(hand_logits, T)) for T in (0.5, 1.0, 2.0)}},
    "truncate": {"peaked": {"k": int((truncate(peaked, k=3) > 0).sum()), "p": int((truncate(peaked, top_p=0.9) > 0).sum())},
                 "flat": {"k": int((truncate(flat, k=3) > 0).sum()), "p": int((truncate(flat, top_p=0.9) > 0).sum())}},
    "difficulty": rows,
    "temps": {str(T): temp_table[T] for T in temp_table},
    "temp_quality": {str(T): temp_quality[T] for T in temp_quality},
    "penalty": {str(k): v for k, v in penalty_table.items()},
    "guided": {"free_valid": sum(valid_poem(t, 6) for t in free),
               "guided_valid": sum(valid_poem(t, 6) for t in guided),
               "n": len(free), "free_sample": free[0], "guided_sample": guided[0]},
}
with open("sampling.json", "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False)
print("写好了 sampling.json：", sorted(data))
# endregion export
