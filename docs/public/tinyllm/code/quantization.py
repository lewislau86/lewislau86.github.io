# %% [markdown]
# # 第 30 章：量化
#
# 配套教案：https://lewislau86.github.io/tinyllm/quantization
#
# 从上到下运行即可（`python quantization.py`），CPU 上约两分钟（大部分是用 3 个种子各训练一次基线模型）。
# 需要安装 PyTorch 和 `tokenizers`。
# 这个文件是本章代码的唯一来源：教案中的代码片段由 `# region 名字` / `# endregion 名字`
# 标记的区域直接引用，notebook 也由它生成（scripts/build-tinyllm-code.py）。
#
# 本章只做“存储格式”的实验：权重、激活、KV cache 用 8 位或 4 位整数存，计算前再还原成浮点（模拟量化）。
# 报告的是体积和质量（验证损失、与原模型输出分布的 KL、下一个 token 的一致率），不报告速度。

# %%
# region imports
import copy
import json
import math

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
# ## 1. 研究对象：3 个第 12 章的基线模型
#
# 模型代码与第 28、29 章相同（[第 12 章](https://lewislau86.github.io/tinyllm/tinyllm-model)的配置，训练 300 步）。
# 量化的影响要在不止一个模型上看，所以用 3 个种子各训练一次：种子只决定初始参数，batch 顺序由单独的生成器固定。
# 每层注意力调用全局变量 `ATTN`，第 7 节会在这里插入 KV cache 的量化。

# %%
# region model
poems = load_poems(6000)
train_poems = [p["text"] for p in poems if p["split"] == "train"]
val_poems = [p["text"] for p in poems if p["split"] == "val"]

V, D, L, H, CTX = 4096, 128, 4, 4, 64
tok = Tokenizer(models.BPE())
tok.pre_tokenizer = pre_tokenizers.ByteLevel(add_prefix_space=False)
tok.decoder = decoders.ByteLevel()
tok.train_from_iterator(train_poems, trainers.BpeTrainer(
    vocab_size=V, special_tokens=["<pad>", "<unk>", "<bos>", "<eos>"],
    initial_alphabet=pre_tokenizers.ByteLevel.alphabet(), show_progress=False))
EOS = tok.token_to_id("<eos>")

def sdpa(q, k, v):
    return F.scaled_dot_product_attention(q, k, v, is_causal=True)

ATTN = sdpa

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
        y = ATTN(apply_rope(q, cos, sin), apply_rope(k, cos, sin), v)
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
        return self.norm(x) @ self.embed.weight.T          # 输出层与嵌入表共享权重

def to_stream(texts):
    ids = []
    for t in texts:
        ids += tok.encode(t).ids + [EOS]
    return torch.tensor(ids)

train_ids, val_ids = to_stream(train_poems), to_stream(val_poems)
# endregion model

# %%
# region train
def train_model(seed, steps=300, batch=32):
    torch.manual_seed(seed)                                 # 种子只决定初始参数
    model = Tiny()
    plan = torch.Generator().manual_seed(1234)              # batch 顺序对所有种子相同
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

SEEDS = (0, 1, 2)
trained = {s: train_model(s) for s in SEEDS}
# endregion train

# %% [markdown]
# 评估协议：验证集切成不重叠的 64 个 token 一段，全部算一遍。除了验证损失，再和原模型逐位置比较两样东西：
# 输出分布的 KL 散度（量化让分布偏了多少），以及概率最高的下一个 token 是否相同。

# %%
# region eval
n_val = (len(val_ids) - 1) // CTX
val_x = val_ids[: n_val * CTX].view(n_val, CTX)
val_y = val_ids[1: n_val * CTX + 1].view(n_val, CTX)

@torch.no_grad()
def compare(base, quant):
    """返回 (量化模型的验证损失, 与原模型的平均 KL, 下一个 token 的一致率)。"""
    loss = kl = agree = 0.0
    for i in range(0, n_val, 64):
        x, y = val_x[i:i + 64], val_y[i:i + 64]
        lp = F.log_softmax(base(x), dim=-1)
        lq = F.log_softmax(quant(x), dim=-1)
        loss += F.nll_loss(lq.reshape(-1, V), y.reshape(-1), reduction="sum").item()
        kl += (lp.exp() * (lp - lq)).sum().item()
        agree += (lp.argmax(-1) == lq.argmax(-1)).sum().item()
    n = n_val * CTX
    return loss / n, kl / n, agree / n

base_loss = {s: compare(m, m)[0] for s, m in trained.items()}
n_params = sum(p.numel() for p in trained[0].parameters())
print(f"验证集 {n_val} 段 × {CTX} 个 token；参数 {n_params:,} 个，FP32 占 {n_params * 4 / 2**20:.2f} MiB")
for s in SEEDS:
    print(f"种子 {s}：验证损失 {base_loss[s]:.4f}")
# endregion eval
log["base_loss"] = base_loss

# %% [markdown]
# ## 2. 公式：一个缩放因子，一个零点
#
# 把浮点数映射到 $b$ 位整数。**对称量化**只用一个缩放因子 $s=\max|x|/(2^{b-1}-1)$，整数 $q=\text{round}(x/s)$，
# 还原 $\hat x = s\,q$。**非对称量化**用数据的最小值和最大值，多一个零点 $z$：$q=\text{round}(x/s)+z$，$\hat x = s(q-z)$。
# 先拿种子 0 的嵌入表里“，”这一行（128 个数）试一下。

# %%
# region formula
def quantize(x, bits, symmetric=True):
    """把一组数量化成 bits 位整数再还原。返回 (整数, 缩放因子, 零点, 还原值)。"""
    if symmetric:
        qmax = 2 ** (bits - 1) - 1                          # INT8：-127…127
        s = x.abs().max() / qmax
        q = torch.round(x / s).clamp(-qmax, qmax)
        return q, s, 0, s * q
    qmin, qmax = 0, 2 ** bits - 1                           # 非对称：0…255（8 位）
    s = (x.max() - x.min()) / (qmax - qmin)
    z = torch.round(-x.min() / s)
    q = torch.clamp(torch.round(x / s) + z, qmin, qmax)
    return q, s, int(z), s * (q - z)

row = trained[0].embed.weight[tok.encode("，").ids[0]].detach()
for bits in (8, 4):
    q, s, z, x_hat = quantize(row, bits)
    err = (x_hat - row).abs()
    print(f"INT{bits} 对称：s={s:.5f}  前 6 个整数 {q[:6].int().tolist()}  最大误差 {err.max():.5f}  平均误差 {err.mean():.5f}")
print(f"原始值的范围 [{row.min():.3f}, {row.max():.3f}]，前 6 个 {[round(v, 3) for v in row[:6].tolist()]}")
# endregion formula

# %% [markdown]
# 嵌入行的数值大致关于 0 对称，对称量化正合适。SiLU 门控的输出就不一样了：它最小只到 −0.28，正的一侧却很长。
# 对称量化要按绝对值最大的那一侧定刻度，负半边的整数几乎全浪费了：

# %%
# region asymmetric
with torch.no_grad():
    h = trained[0].blocks[0].norm2(trained[0].embed(val_x[:1]))
    act = F.silu(trained[0].blocks[0].gate(h))[0].flatten()   # 一段文本、第 0 层的 SiLU 输出
for symmetric in (True, False):
    q, s, z, x_hat = quantize(act, 4, symmetric)
    used = len(q.unique())
    name = "对称  " if symmetric else "非对称"
    print(f"INT4 {name}：零点 {z:>2}，16 个整数里用到 {used:>2} 个，平均误差 {(x_hat - act).abs().mean():.4f}")
print(f"SiLU 输出的范围 [{act.min():.3f}, {act.max():.3f}]")
# endregion asymmetric
counts, edges = torch.histogram(act, bins=60)
log["act_hist"] = {"counts": counts.tolist(), "edges": edges.tolist()}
log["act_levels"] = {name: torch.unique(quantize(act, 4, sym)[3]).tolist() for name, sym in (("sym", True), ("asym", False))}
log["row"] = row.tolist()
log["row_levels"] = torch.unique(quantize(row, 4)[1] * torch.arange(-7, 8)).tolist()

# %% [markdown]
# ## 3. 按什么单位共用一个缩放因子
#
# 一个缩放因子管多少个数，叫量化的**粒度**：整个矩阵共用一个（按张量）、每个输出通道一行一个（按通道）、
# 每 $g$ 个相邻的输入一个（分组）。单位越小，每组的最大值越贴近组内的数，误差越小；代价是多存缩放因子，
# 每个缩放因子按 FP16 记 16 位。下面用对称量化处理种子 0 的全部权重矩阵（嵌入表和所有线性层），
# 看相对误差和摊到每个权重上的位数。

# %%
# region fake-quant
def fake_quant(w, bits, group):
    """对称量化一个矩阵再还原。group：'tensor'、'channel'（每行）或整数 g（每行每 g 个输入）。"""
    qmax = 2 ** (bits - 1) - 1
    rows, cols = w.shape
    if group == "tensor":
        x = w.reshape(1, 1, -1)
    else:
        g = cols if group == "channel" else group
        x = F.pad(w, (0, (-cols) % g)).reshape(rows, -1, g)   # 列数不是 g 的倍数时，最后一组补 0
    s = x.abs().amax(dim=-1, keepdim=True).clamp(min=1e-12) / qmax
    x_hat = torch.round(x / s).clamp(-qmax, qmax) * s
    return x_hat.reshape(rows, -1)[:, :cols] if group != "tensor" else x_hat.reshape(rows, cols)

def n_scales(w, group):
    rows, cols = w.shape
    if group == "tensor":
        return 1
    g = cols if group == "channel" else group
    return rows * math.ceil(cols / g)

def weight_matrices(model):
    yield "嵌入", model.embed.weight
    for b in model.blocks:
        for name in ("qkv", "proj"):
            yield "注意力", getattr(b, name).weight
        for name in ("gate", "up", "down"):
            yield "前馈", getattr(b, name).weight

SCHEMES = [(8, "tensor"), (8, "channel"), (4, "tensor"), (4, "channel"), (4, 64), (4, 32), (3, 32)]
def scheme_name(bits, group):
    return f"INT{bits} " + {"tensor": "按张量", "channel": "按通道"}.get(group, f"分组 {group}")

granularity = []
with torch.no_grad():
    for bits, group in SCHEMES:
        err2 = ref2 = 0.0
        n_w = n_s = 0
        for _, w in weight_matrices(trained[0]):
            err2 += (fake_quant(w, bits, group) - w).pow(2).sum().item()
            ref2 += w.pow(2).sum().item()
            n_w += w.numel()
            n_s += n_scales(w, group)
        bpw = bits + 16 * n_s / n_w
        granularity.append({"scheme": scheme_name(bits, group), "rel_err": math.sqrt(err2 / ref2), "bpw": bpw})
        print(f"{scheme_name(bits, group):<14} 相对误差 {math.sqrt(err2 / ref2):6.2%}   每个权重 {bpw:6.3f} 位   "
              f"权重共 {n_w * bpw / 8 / 2**20:.2f} MiB（FP32 是 {n_w * 4 / 2**20:.2f} MiB）")
# endregion fake-quant
log["granularity"] = granularity

# %% [markdown]
# ## 4. 放回模型：3 个种子上的验证损失
#
# 把每种方案用到全部权重上（嵌入表和输出层是同一个矩阵，量化一次两处都变），在 3 个模型上分别和原模型比较。

# %%
# region quantize-model
def quantize_model(model, bits, group, parts=("嵌入", "注意力", "前馈")):
    q = copy.deepcopy(model)
    with torch.no_grad():
        for part, w in weight_matrices(q):
            if part in parts:
                w.copy_(fake_quant(w, bits, group))
    return q

results = {}
for bits, group in SCHEMES:
    name = scheme_name(bits, group)
    rows = [compare(m, quantize_model(m, bits, group)) for m in trained.values()]
    results[name] = rows
    dl = [r[0] - base_loss[s] for r, s in zip(rows, SEEDS)]
    kl = [r[1] for r in rows]
    ag = [r[2] for r in rows]
    print(f"{name:<14} 损失 {sum(dl) / 3:+.4f} [{min(dl):+.4f}, {max(dl):+.4f}]   "
          f"KL {sum(kl) / 3:.4f}   一致率 {sum(ag) / 3:6.2%} [{min(ag):.2%}, {max(ag):.2%}]")
# endregion quantize-model
log["results"] = {k: [list(r) for r in v] for k, v in results.items()}

# %% [markdown]
# 一致率是“原模型和量化模型在同一位置上最可能的下一个 token 是否相同”。贪心生成时，只要有一个位置不同，后面的文本就会分岔。
# 用种子 0 的模型，从 8 个开头各贪心生成 32 个 token，看各方案和原模型从第几个 token 开始不一样：

# %%
# region generate
@torch.no_grad()
def greedy(model, prompt, n=32):
    ids = tok.encode(prompt).ids
    for _ in range(n):
        ids.append(model(torch.tensor([ids[-CTX:]]))[0, -1].argmax().item())
    return ids

prompts = ["春眠不觉晓，", "床前明月光，", "白日依山尽，", "千山鸟飞绝，", "独在异乡为异客，", "国破山河在，", "空山不见人，", "红豆生南国，"]
reference = [greedy(trained[0], p) for p in prompts]
divergence = {}
for bits, group in [(8, "channel"), (4, 32), (4, "tensor"), (3, 32)]:
    qm = quantize_model(trained[0], bits, group)
    first_diff = []
    for p, ref in zip(prompts, reference):
        out = greedy(qm, p)
        start = len(tok.encode(p).ids)
        same = next((i for i in range(start, len(ref)) if out[i] != ref[i]), len(ref)) - start
        first_diff.append(same)
        if p == prompts[0]:
            sample = tok.decode(out[start:])
    divergence[scheme_name(bits, group)] = first_diff
    print(f"{scheme_name(bits, group):<14} 与原模型相同的前缀长度：{first_diff}  “春眠不觉晓，”→ {sample!r}")
print(f"{'原模型':<14} “春眠不觉晓，”→ {tok.decode(reference[0][len(tok.encode(prompts[0]).ids):])!r}")
# endregion generate
log["divergence"] = divergence

# %% [markdown]
# ## 5. 哪一部分最怕量化
#
# 只把一部分权重用 INT4 按张量量化（误差最大的那种），其余保持 FP32，看损失涨在哪里：

# %%
# region sensitivity
sensitivity = {}
for part in ("嵌入", "注意力", "前馈"):
    rows = [compare(m, quantize_model(m, 4, "tensor", parts=(part,))) for m in trained.values()]
    dl = [r[0] - base_loss[s] for r, s in zip(rows, SEEDS)]
    sensitivity[part] = dl
    share = sum(w.numel() for p, w in weight_matrices(trained[0]) if p == part) / n_params
    print(f"只量化{part}（占参数 {share:5.1%}）：损失 {sum(dl) / 3:+.4f} [{min(dl):+.4f}, {max(dl):+.4f}]")
# endregion sensitivity
log["sensitivity"] = sensitivity

# %% [markdown]
# ## 6. 激活的离群值
#
# 前面只量化了权重，计算时还原成浮点。要让矩阵乘本身用整数算（比如 INT8 × INT8），激活也得量化。
# 激活和权重不同：它随输入变化，而且某些通道会系统性地特别大。统计种子 0 的模型在一批验证文本上，
# 每个线性层输入的每个通道出现过的最大绝对值：

# %%
# region outliers
@torch.no_grad()
def channel_absmax(model, x=val_x[:64]):
    stats, hooks = {}, []
    for i, b in enumerate(model.blocks):
        for name in ("qkv", "proj", "gate", "down"):
            def hook(mod, inp, out, key=(i, name)):
                stats[key] = inp[0].reshape(-1, inp[0].shape[-1]).abs().amax(dim=0)
            hooks.append(getattr(b, name).register_forward_hook(hook))
    model(x)
    for h in hooks:
        h.remove()
    return stats

absmax = channel_absmax(trained[0])
for name in ("qkv", "proj", "gate", "down"):
    ratios = [(absmax[(i, name)].max() / absmax[(i, name)].median()).item() for i in range(L)]
    print(f"{name:<5} 的输入：最大通道 / 中位数通道 = " + "  ".join(f"{r:5.1f}" for r in ratios) + "（第 0～3 层）")
# endregion outliers
log["absmax_down1"] = absmax[(1, "down")].tolist()
log["absmax_qkv1"] = absmax[(1, "qkv")].tolist()

# %% [markdown]
# `down` 的输入是 SiLU 门控乘上 `up` 的结果，少数通道比中位数大十几倍。按张量量化激活时，刻度由这几个通道决定，
# 其余通道只能用到很少几个整数。三种处理方式：
#
# - **按张量**：整个激活一个缩放因子，最省事，受离群值影响最大；
# - **按 token**：每个位置一个缩放因子，运行时多算一次最大值；
# - **SmoothQuant**：每个输入通道 $j$ 选一个系数 $s_j$，激活除以 $s_j$、权重的第 $j$ 列乘以 $s_j$。
#   乘积不变（$XW^\top = (X\,\mathrm{diag}(s)^{-1})(W\,\mathrm{diag}(s))^\top$），但激活的离群通道被压平了，难度挪了一部分给权重。
#   $s_j = \max|X_j|^{\alpha} / \max|W_j|^{1-\alpha}$，这里取 $\alpha=0.5$。

# %%
# region smoothquant
def smooth_factors(absmax_x, w, alpha=0.5):
    return absmax_x.clamp(min=1e-5) ** alpha / w.abs().amax(dim=0).clamp(min=1e-5) ** (1 - alpha)

w = trained[0].blocks[1].down.weight.detach()
x = torch.randn(8, w.shape[1]) * absmax[(1, "down")]           # 带着同样离群通道的一组输入
s = smooth_factors(absmax[(1, "down")], w)
print(f"等价性：|XWᵀ − (X/s)(W·s)ᵀ| 最大 {(x @ w.T - (x / s) @ (w * s).T).abs().max().item():.1e}")
xs = absmax[(1, "down")] / s
print(f"第 1 层 down 的输入：最大通道 / 中位数通道 {(absmax[(1, 'down')].max() / absmax[(1, 'down')].median()).item():.1f}"
      f" → 平滑后 {(xs.max() / xs.median()).item():.1f}")

def quantize_activations(model, bits, mode, alpha=None):
    """权重 INT8 按通道；每个线性层的输入按 mode 量化（'tensor' 或 'token'）。alpha 不为 None 时先做 SmoothQuant。"""
    q = copy.deepcopy(model)
    stats = channel_absmax(model)
    qmax = 2 ** (bits - 1) - 1
    for i, b in enumerate(q.blocks):
        for name in ("qkv", "proj", "gate", "up", "down"):
            lin = getattr(b, name)
            key = (i, "gate" if name == "up" else name)             # gate 和 up 的输入相同
            sm = smooth_factors(stats[key], lin.weight) if alpha is not None else None
            with torch.no_grad():
                if sm is not None:
                    lin.weight.mul_(sm)
                lin.weight.copy_(fake_quant(lin.weight, 8, "channel"))
            def pre_hook(mod, inp, sm=sm):
                x = inp[0] / sm if sm is not None else inp[0]
                amax = x.abs().amax() if mode == "tensor" else x.abs().amax(dim=-1, keepdim=True)
                scale = amax.clamp(min=1e-8) / qmax
                return (torch.round(x / scale).clamp(-qmax, qmax) * scale,)
            lin.register_forward_pre_hook(pre_hook)
    return q

act_results = {}
for bits in (8, 6):
    for label, mode, alpha in (("按张量", "tensor", None), ("按 token", "token", None), ("SmoothQuant + 按张量", "tensor", 0.5)):
        dl = [compare(m, quantize_activations(m, bits, mode, alpha))[0] - base_loss[s] for s, m in trained.items()]
        act_results[f"W8A{bits} {label}"] = dl
        print(f"权重 INT8、激活 INT{bits} {label:<18} 损失 {sum(dl) / 3:+.4f} [{min(dl):+.4f}, {max(dl):+.4f}]")
# endregion smoothquant
log["act_results"] = act_results
log["absmax_down1_smoothed"] = xs.tolist()

# %% [markdown]
# ## 7. KV cache 量化
#
# [第 28 章](https://lewislau86.github.io/tinyllm/inference-efficiency)算过，长上下文时缓存会比权重还大。
# 缓存里的 K、V 也可以量化：每个 token、每个头的一组 K（32 个数）共用一个缩放因子。
# 在注意力里，K、V 写进缓存前量化、读出来时还原，等价于把下面这个函数换进 `ATTN`：

# %%
# region kv-quant
def quantize_kv(x, bits):                                     # x: [B, 头, T, 每头维度]，每个 (token, 头) 一组
    qmax = 2 ** (bits - 1) - 1
    s = x.abs().amax(dim=-1, keepdim=True).clamp(min=1e-8) / qmax
    return torch.round(x / s).clamp(-qmax, qmax) * s

class KVQuantized(nn.Module):
    """包一层：前向时把每层注意力换成“K、V 先量化再参与计算”的版本，结束后换回来。"""
    def __init__(self, model, bits):
        super().__init__()
        self.model, self.bits = model, bits
    def forward(self, idx):
        global ATTN
        ATTN = lambda q, k, v: sdpa(q, quantize_kv(k, self.bits), quantize_kv(v, self.bits))
        try:
            return self.model(idx)
        finally:
            ATTN = sdpa

kv_results = {}
for bits in (8, 4):
    rows = [compare(m, KVQuantized(m, bits)) for m in trained.values()]
    dl = [r[0] - base_loss[s] for r, s in zip(rows, SEEDS)]
    kv_results[f"KV INT{bits}"] = [list(r) for r in rows]
    print(f"KV cache INT{bits}：损失 {sum(dl) / 3:+.4f} [{min(dl):+.4f}, {max(dl):+.4f}]   "
          f"KL {sum(r[1] for r in rows) / 3:.4f}   一致率 {sum(r[2] for r in rows) / 3:.2%}")
# endregion kv-quant
log["kv_results"] = kv_results

# %% [markdown]
# 缓存的字节数用第 28 章的公式：$2 \times$ 层数 $\times$ token 数 $\times$ KV 头数 $\times$ 每头维度 $\times$ 每元素字节，
# 量化后每元素的字节变小，另外每组（每个 token、每个头）多存一个 FP16 缩放因子。

# %%
# region kv-bytes
def kv_bytes(layers, tokens, kv_heads, head_dim, bits):
    groups = 2 * layers * tokens * kv_heads
    return groups * head_dim * bits / 8 + groups * 2 * (bits < 16)      # 量化时每组加 2 字节缩放因子

for name, cfg in [("TinyLLM，64 个 token", (4, 64, 4, 32)), ("Llama 3 8B，8192 个 token", (32, 8192, 8, 128))]:
    sizes = {b: kv_bytes(*cfg, b) for b in (16, 8, 4)}
    unit, div = ("KiB", 2**10) if sizes[16] < 2**20 else ("MiB", 2**20)
    print(f"{name}：FP16 {sizes[16] / div:7.1f} {unit}   INT8 {sizes[8] / div:7.1f} {unit}   INT4 {sizes[4] / div:7.1f} {unit}")
# endregion kv-bytes

# %% [markdown]
# ## 8. 换算到真实模型
#
# 权重的体积 = 参数个数 × 每个权重的位数 ÷ 8。每个权重的位数要算上缩放因子：分组 128 的 INT4 是 $4 + 16/128 = 4.125$ 位。
# 再用第 28 章的带宽上限（单请求 decode 每生成一个 token 要把权重读一遍）估一下速度的上限。

# %%
# region real-models
real = {"Llama 3 8B": 8.03e9, "Qwen3-32B": 32.8e9, "Llama 3 70B": 70.6e9}
formats = [("BF16", 16), ("INT8 按通道", 8), ("INT4 分组 128", 4 + 16 / 128)]
bandwidth = 3.35e12                                            # H100 SXM 公布的显存带宽，字节/秒
real_rows = {}
for name, n in real.items():
    sizes = [n * bpw / 8 for _, bpw in formats]
    real_rows[name] = sizes
    print(f"{name:<12}" + "".join(f"  {f} {b / 1e9:6.1f} GB（≤{bandwidth / b:5.0f} token/s）" for (f, _), b in zip(formats, sizes)))
print("按通道 INT8 的缩放因子只有每行一个，可以忽略；token/s 是单请求、只算读权重的上限，不是实测。")
# endregion real-models
log["real"] = real_rows

# %%
with open("quantization_log.json", "w", encoding="utf-8") as f:
    json.dump(log, f, ensure_ascii=False)
print("已写出 quantization_log.json")
