---
title: "第 13 章：TinyLLM 在 GPU 上完整实现（notebook 在线查看）"
search: false
editLink: false
prev: false
next: false
pageClass: tinyllm-course
---

<!-- 本页由 scripts/build-tinyllm-code.py 根据 notebook 自动生成，请勿手改。 -->

::: tip 这是 notebook 的只读预览
[返回教案](/tinyllm/gpu-training) · [在 Colab 中运行](https://colab.research.google.com/github/lewislau86/lewislau86.github.io/blob/master/docs/public/tinyllm/notebooks/gpu-training.ipynb) · <a href="/tinyllm/notebooks/gpu-training.ipynb" download>下载 .ipynb</a> · <a href="/tinyllm/code/gpu-training.py" download>下载 .py</a> · [在 GitHub 上查看](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/tinyllm/notebooks/gpu-training.ipynb)

下面的代码和输出与 notebook 文件完全一致。想修改、运行，请用 Colab 打开或下载到本地。
:::

::: v-pre
# 第 13 章：TinyLLM 在 GPU 上完整实现

配套教案：https://lewislau86.github.io/tinyllm/gpu-training

有 NVIDIA 显卡时运行 `python gpu-training.py`，默认按“GPU 小”配置完整训练；
没有显卡时自动改用“CPU 冒烟”配置，只训练几十步，确认整条流程能跑通（本站 notebook 就是这样生成的，约一分钟）。
用环境变量 TINYLLM_PRESET=gpu-small / gpu-medium / cpu-smoke 可以手动指定，TINYLLM_COMPILE=1 打开 torch.compile。
需要安装 PyTorch 和 `tokenizers`。
这个文件是本章代码的唯一来源：教案中的代码片段由 `# region 名字` / `# endregion 名字`
标记的区域直接引用，notebook 也由它生成（scripts/build-tinyllm-code.py）。

模型代码和第 12 章逐字相同，本章只改配置和训练循环。
:::

<p class="nb-label">In [1]</p>

```python
import contextlib
import math
import os
import time
from dataclasses import asdict, dataclass, replace

import torch
from torch import nn
from torch.nn import functional as F
from tokenizers import Tokenizer, decoders, models, pre_tokenizers, trainers

print("PyTorch", torch.__version__)

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
```

```text
PyTorch 2.14.1+cpu
```

::: v-pre
## 1. 设备：有 GPU 就用 GPU

同一份脚本在两种机器上都能跑。下面三行决定了后面所有张量放在哪里、用什么精度算。
:::

<p class="nb-label">In [2]</p>

```python
device = "cuda" if torch.cuda.is_available() else "cpu"
use_bf16 = device == "cuda" and torch.cuda.is_bf16_supported()       # 第 19 章：支持 BF16 就用 BF16 混合精度
if device == "cuda":
    torch.backends.cuda.matmul.allow_tf32 = True                     # 优化点：FP32 矩阵乘走 TF32 张量核
    torch.backends.cudnn.allow_tf32 = True
print("设备：", torch.cuda.get_device_name() if device == "cuda" else "CPU")
print("混合精度：", "BF16 autocast" if use_bf16 else "关闭（FP32）")
```

```text
设备： CPU
混合精度： 关闭（FP32）
```

::: v-pre
## 2. 模型：和第 12 章逐字相同

下面这几个类原样复制自第 12 章。放大模型只改配置，不改这里的任何一行。
:::

<p class="nb-label">In [3]</p>

```python
@dataclass
class TinyConfig:
    vocab_size: int = 4096     # BPE 词表大小（含 4 个特殊 token）
    d_model: int = 128         # 每个 token 向量的宽度 d
    n_layers: int = 4          # Block 层数 L
    n_heads: int = 4           # 注意力头数，每头 d / n_heads = 32 维
    context: int = 64          # 一次最多看多少个 token
    rope_base: float = 10000.0


def rope_tables(context, head_dim, base):
    theta = base ** (-torch.arange(0, head_dim, 2).float() / head_dim)
    angle = torch.arange(context).float()[:, None] * theta        # (T, head_dim/2)
    return angle.cos(), angle.sin()

def apply_rope(x, cos, sin):                                      # x: (B, 头数, T, head_dim)
    T = x.shape[-2]
    cos, sin = cos[:T], sin[:T]
    x1, x2 = x[..., 0::2], x[..., 1::2]
    return torch.stack([x1 * cos - x2 * sin, x1 * sin + x2 * cos], dim=-1).flatten(-2)

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

class SwiGLU(nn.Module):
    def __init__(self, cfg):
        super().__init__()
        hidden = 8 * cfg.d_model // 3
        self.gate = nn.Linear(cfg.d_model, hidden, bias=False)
        self.up = nn.Linear(cfg.d_model, hidden, bias=False)
        self.down = nn.Linear(hidden, cfg.d_model, bias=False)        # 输出投影：写回残差流

    def forward(self, x):
        return self.down(F.silu(self.gate(x)) * self.up(x))

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
```

::: v-pre
## 3. 三档配置

“CPU 冒烟”就是第 12 章的基线尺寸，只训练几十步，用来在没有显卡的机器上检查流程；
两档 GPU 配置把宽度、层数、上下文一起放大。`micro_batch × accum` 是每步实际用到的序列数：显存放不下时减小 `micro_batch`、增大 `accum`，有效批量不变（第 20 章）。
:::

<p class="nb-label">In [4]</p>

```python
@dataclass
class TrainConfig:
    model: TinyConfig
    corpus: str            # "unified-6000"：统一语料前 6000 首；"large"：唐宋诗大语料（没有就退回统一语料全部）
    micro_batch: int       # 一次前向放进显存的序列数
    accum: int             # 梯度累积次数：每 accum 个 micro-batch 更新一次参数
    steps: int
    lr: float
    warmup: int            # 学习率先线性升到 lr，再余弦降到 lr/10（第 17 章）
    eval_every: int

PRESETS = {
    "cpu-smoke":  TrainConfig(TinyConfig(vocab_size=4096, d_model=128, n_layers=4, n_heads=4, context=64),
                              "unified-6000", micro_batch=16, accum=2, steps=60, lr=3e-3, warmup=10, eval_every=30),
    "gpu-small":  TrainConfig(TinyConfig(vocab_size=8192, d_model=512, n_layers=8, n_heads=8, context=512),
                              "large", micro_batch=32, accum=1, steps=6000, lr=1e-3, warmup=300, eval_every=500),
    "gpu-medium": TrainConfig(TinyConfig(vocab_size=8192, d_model=768, n_layers=12, n_heads=12, context=1024),
                              "large", micro_batch=8, accum=4, steps=6000, lr=6e-4, warmup=300, eval_every=500),
}
preset = os.environ.get("TINYLLM_PRESET", "gpu-small" if device == "cuda" else "cpu-smoke")
tc = PRESETS[preset]
cfg = tc.model
print("配置：", preset, cfg)
```

```text
配置： cpu-smoke TinyConfig(vocab_size=4096, d_model=128, n_layers=4, n_heads=4, context=64, rope_base=10000.0)
```

::: v-pre
## 4. 动手之前：参数量和显存估一估

在 `meta` 设备上把三档模型都建出来数参数，不占内存。显存按两部分估：
训练状态每个参数 16 字节（FP32 权重、梯度、AdamW 两个状态各 4 字节，第 16、19 章）；
激活按 BF16 加 SDPA 注意力估，每层每条序列约 34·T·d 字节，再加 logits 和它的梯度（FP32）。
估算不含 CUDA 上下文和缓存碎片，实际通常再多 1～2 GB。
:::

<p class="nb-label">In [5]</p>

```python
def estimate(tc):
    c = tc.model
    with torch.device("meta"):
        params = sum(p.numel() for p in TinyLLM(c).parameters())
    state = params * 16 / 1e9
    act = tc.micro_batch * (34 * c.context * c.d_model * c.n_layers + 8 * c.context * c.vocab_size) / 1e9
    return params, state, act

print(f"{'配置':<11}{'参数量':>12}{'每步 token':>11}{'训练状态':>9}{'激活':>8}{'合计':>8}")
for name, p in PRESETS.items():
    params, state, act = estimate(p)
    tokens = p.micro_batch * p.accum * p.model.context
    print(f"{name:<11}{params:>12,}{tokens:>11,}{state:>8.2f}G{act:>7.2f}G{state + act:>7.2f}G")
```

```text
配置                  参数量   每步 token     训练状态      激活      合计
```

```text
cpu-smoke     1,311,360      2,048    0.02G   0.05G   0.07G
gpu-small    29,364,736     16,384    0.47G   3.36G   3.83G
gpu-medium   91,245,312     32,768    1.46G   3.10G   4.56G
```

::: v-pre
## 5. 数据与分词器

GPU 配置优先用唐宋诗大语料（在仓库根目录运行 `python scripts/prepare-tinyllm-large-corpus.py` 生成，约 90 MB），
找不到就退回统一唐诗语料的全部 17,439 首。分词器的训练方法和第 12 章相同。
:::

<p class="nb-label">In [6]</p>

```python
def load_large():
    """唐宋诗大语料；依次找环境变量 TINYLLM_LARGE_DATA、当前目录、../data/、../../../../data/（仓库根目录）。没有就返回 None。"""
    candidates = [os.environ.get("TINYLLM_LARGE_DATA", ""), "tang-song-poems.jsonl",
                  "../data/tang-song-poems.jsonl", "../../../../data/tang-song-poems.jsonl"]
    path = next((Path(p) for p in candidates if p and Path(p).exists()), None)
    if path is None:
        return None
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

poems = load_large() if tc.corpus == "large" else None
corpus_name = "唐宋诗大语料" if poems else "统一唐诗语料"
if poems is None:
    poems = load_poems(6000 if tc.corpus == "unified-6000" else 10**9)
train_poems = [p["text"] for p in poems if p["split"] == "train"]
val_poems = [p["text"] for p in poems if p["split"] == "val"]
print(f"语料：{corpus_name}，训练 {len(train_poems)} 首，验证 {len(val_poems)} 首")
```

```text
语料：统一唐诗语料，训练 5419 首，验证 291 首
```

<p class="nb-label">In [7]</p>

```python
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

t0 = time.time()
tokenizer = train_tokenizer(train_poems, cfg.vocab_size)
EOS = tokenizer.token_to_id("<eos>")

def to_stream(texts):
    ids = []
    for enc in tokenizer.encode_batch(texts):
        ids += enc.ids + [EOS]
    return torch.tensor(ids)

train_ids, val_ids = to_stream(train_poems), to_stream(val_poems)
tokens_per_char = len(val_ids) / sum(len(t) + 1 for t in val_poems)
print(f"词表 {tokenizer.get_vocab_size()}，训练流 {len(train_ids):,} 个 token，验证流 {len(val_ids):,} 个 token")
```

```text
词表 4096，训练流 225,007 个 token，验证流 12,256 个 token
```

::: v-pre
## 6. 把模型和优化器搬上设备

和第 12 章相比只多了三处：模型 `.to(device)`；GPU 上用 `fused=True` 的 AdamW（把逐参数的小运算合成少数几个内核）；
可选的 `torch.compile`。混合精度用 autocast 包住前向，权重和优化器状态仍是 FP32（第 19 章）。
:::

<p class="nb-label">In [8]</p>

```python
torch.manual_seed(0)
model = TinyLLM(cfg).to(device)
decay = [p for p in model.parameters() if p.dim() >= 2]
no_decay = [p for p in model.parameters() if p.dim() < 2]
optimizer = torch.optim.AdamW([{"params": decay, "weight_decay": 0.1},
                               {"params": no_decay, "weight_decay": 0.0}],
                              lr=tc.lr, fused=(device == "cuda"))           # 优化点：融合的优化器内核
step_model = torch.compile(model) if os.environ.get("TINYLLM_COMPILE") == "1" else model   # 优化点：编译与算子融合

def autocast():
    return torch.autocast(device_type="cuda", dtype=torch.bfloat16) if use_bf16 else contextlib.nullcontext()

def lr_at(step):                                     # warmup + 余弦，第 17 章细讲
    if step < tc.warmup:
        return tc.lr * (step + 1) / tc.warmup
    progress = (step - tc.warmup) / max(1, tc.steps - tc.warmup)
    return tc.lr * (0.1 + 0.9 * 0.5 * (1 + math.cos(math.pi * progress)))
print(f"参数量 {sum(p.numel() for p in model.parameters()):,}，编译：{'开' if step_model is not model else '关'}")
```

```text
参数量 1,311,360，编译：关
```

::: v-pre
## 7. 评估：和第 12 章同一个口径

验证流切成不重叠的窗口全部算一遍，报每 token 的 nats 和每字比特。只多了把数据搬到设备上、用 autocast 算前向。
:::

<p class="nb-label">In [9]</p>

```python
@torch.no_grad()
def evaluate(ids=val_ids, T=cfg.context, batch=32):
    model.eval()
    n = (len(ids) - 1) // T * T
    xs, ys = ids[:n].view(-1, T), ids[1:n + 1].view(-1, T)
    total = 0.0
    for i in range(0, len(xs), batch):
        x, y = xs[i:i + batch].to(device), ys[i:i + batch].to(device)
        with autocast():
            logits = model(x)
        total += F.cross_entropy(logits.float().flatten(0, 1), y.flatten(), reduction="sum").item()
    model.train()
    nats = total / ys.numel()
    return nats, nats * tokens_per_char / math.log(2)
```

::: v-pre
## 8. 训练循环

每步：按 batch 计划取 `accum` 个 micro-batch，各自前向、反向（损失先除以 `accum`，梯度累加起来正好是整批的平均），
再裁剪梯度、按调度设学习率、更新。计时只算训练，不算评估；GPU 是异步执行的，读时间之前要 `synchronize()`。
:::

<p class="nb-label">In [10]</p>

```python
plan = torch.Generator().manual_seed(1234)                    # batch 计划：和第 12 章一样独立于模型种子
starts = torch.randint(0, len(train_ids) - cfg.context - 1, (tc.steps, tc.accum, tc.micro_batch), generator=plan)
offsets = torch.arange(cfg.context + 1)

def sync():
    if device == "cuda":
        torch.cuda.synchronize()

log = {"step": [], "loss": [], "val_step": [], "val_loss": [], "tokens_per_s": []}
train_time, tokens_seen = 0.0, 0
for step in range(tc.steps + 1):
    if step % tc.eval_every == 0 or step == tc.steps:
        nats, bpc = evaluate()
        log["val_step"].append(step); log["val_loss"].append(nats)
        print(f"step {step:5d}  验证损失 {nats:.3f}  ({bpc:.2f} 比特/字)")
    if step == tc.steps:
        break
    sync(); t = time.time()
    for g in optimizer.param_groups:
        g["lr"] = lr_at(step)
    for micro in range(tc.accum):
        idx = starts[step, micro][:, None] + offsets
        xb = train_ids[idx[:, :-1]].to(device)                # 优化点：每步在 CPU 上切片再同步拷到 GPU
        yb = train_ids[idx[:, 1:]].to(device)
        with autocast():
            _, loss = step_model(xb, yb)
        (loss / tc.accum).backward()
    torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
    optimizer.step()
    optimizer.zero_grad(set_to_none=True)
    sync(); train_time += time.time() - t
    tokens_seen += tc.accum * tc.micro_batch * cfg.context
    log["step"].append(step); log["loss"].append(loss.item())
log["tokens_per_s"] = tokens_seen / train_time
print(f"训练 {tc.steps} 步，吞吐约 {tokens_seen / train_time:,.0f} token/s")
```

```text
step     0  验证损失 8.750  (12.05 比特/字)
```

```text
step    30  验证损失 6.474  (8.91 比特/字)
```

```text
step    60  验证损失 6.293  (8.66 比特/字)
训练 60 步，吞吐约 7,584 token/s
```

::: v-pre
## 9. 实测显存

只在 GPU 上统计。`max_memory_allocated` 是 PyTorch 分配给张量的峰值，和第 4 节的估算对照；
它不含 CUDA 上下文，`nvidia-smi` 看到的数字会更大。
:::

<p class="nb-label">In [11]</p>

```python
if device == "cuda":
    peak = torch.cuda.max_memory_allocated() / 1e9
    params, state, act = estimate(tc)
    print(f"显存峰值 {peak:.2f} GB，估算 {state + act:.2f} GB")
else:
    print("CPU 上不统计显存")
```

```text
CPU 上不统计显存
```

::: v-pre
## 10. 检查点：存下来、读回去，结果一样

大模型一训就是几小时，中途断了要能接着训。检查点至少存模型、优化器、配置和步数（第 21 章展开）。
存完立刻读进一个新模型，验证损失应当一模一样。
:::

<p class="nb-label">In [12]</p>

```python
ckpt = {"model": model.state_dict(), "optimizer": optimizer.state_dict(),
        "config": asdict(cfg), "step": tc.steps, "preset": preset}
torch.save(ckpt, "tinyllm-ckpt.pt")

restored = TinyLLM(TinyConfig(**torch.load("tinyllm-ckpt.pt", map_location=device)["config"])).to(device)
restored.load_state_dict(torch.load("tinyllm-ckpt.pt", map_location=device)["model"])
before = evaluate()[0]
model, restored = restored, model                             # evaluate() 用的是全局的 model
after = evaluate()[0]
model, restored = restored, model
print(f"存之前 {before:.4f}，读回来 {after:.4f}")
```

```text
存之前 6.2932，读回来 6.2932
```

::: v-pre
## 11. 生成

和第 12 章同一个采样函数：从 `<eos>` 开始，温度 0.8，直到生成 `<eos>`。
:::

<p class="nb-label">In [13]</p>

```python
@torch.no_grad()
def generate(max_new_tokens=80, temperature=0.8, generator=None):
    model.eval()
    idx = torch.tensor([[EOS]], device=device)
    for _ in range(max_new_tokens):
        with autocast():
            logits = model(idx[:, -cfg.context:])[:, -1, :].float() / temperature
        next_id = torch.multinomial(F.softmax(logits, dim=-1).cpu(), 1, generator=generator).to(device)
        if next_id.item() == EOS:
            break
        idx = torch.cat([idx, next_id], dim=1)
    model.train()
    return tokenizer.decode(idx[0, 1:].tolist())

sampler = torch.Generator().manual_seed(7)
for _ in range(3):
    print(generate(generator=sampler))
```

```text
晓如恻，何下花成。惬阳台苏回，病载归足，秋金天�风。营集时前，�定路春城。叶安篇��得，悬不同空。
```

```text
期晚，长月住孤方。高影轻群，独有，禅退吟游。贵带隔，萤，一意怜。，犹得相访乐�，簟。已无支。
未月天圃，似老女尽。关河贪照远，穿麟疎难君语。
```

<p class="nb-label">In [14]</p>

```python
import json
with open("gpu_training_log.json", "w", encoding="utf-8") as f:
    json.dump({"preset": preset, "device": device, "bf16": use_bf16, **log}, f)
```

