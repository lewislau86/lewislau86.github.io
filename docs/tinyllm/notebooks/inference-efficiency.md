---
title: "第 26 章：推理效率：prefill、decode 与 KV cache（notebook 在线查看）"
search: false
editLink: false
prev: false
next: false
pageClass: tinyllm-course
---

<!-- 本页由 scripts/build-tinyllm-code.py 根据 notebook 自动生成，请勿手改。 -->

::: tip 这是 notebook 的只读预览
[返回教案](/tinyllm/inference-efficiency) · [在 Colab 中运行](https://colab.research.google.com/github/lewislau86/lewislau86.github.io/blob/master/docs/public/tinyllm/notebooks/inference-efficiency.ipynb) · <a href="/tinyllm/notebooks/inference-efficiency.ipynb" download>下载 .ipynb</a> · <a href="/tinyllm/code/inference-efficiency.py" download>下载 .py</a> · [在 GitHub 上查看](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/tinyllm/notebooks/inference-efficiency.ipynb)

下面的代码和输出与 notebook 文件完全一致。想修改、运行，请用 Colab 打开或下载到本地。
:::

::: v-pre
# 第 26 章：推理效率：prefill、decode 与 KV cache

配套教案：https://lewislau86.github.io/tinyllm/inference-efficiency

从上到下运行即可（`python inference-efficiency.py`），CPU 上约一分钟（绝大部分是训练基线模型）。
需要安装 PyTorch 和 `tokenizers`。
这个文件是本章代码的唯一来源：教案中的代码片段由 `# region 名字` / `# endregion 名字`
标记的区域直接引用，notebook 也由它生成（scripts/build-tinyllm-code.py）。

本章把一次生成拆成两个阶段（prefill 与 decode），量出两件事：KV cache 省掉了多少重复投影，
以及 decode 每一步为什么要读一遍全部权重。计时用的机器不同、结果就不同，
所以正文引用的都是与硬件无关的计数（投影行数、缓存字节数），时间只写进导出的记录，用图呈现。
:::

<p class="nb-label">In [1]</p>

```python
import json
import math
import time

import torch
from torch import nn
from torch.nn import functional as F
from tokenizers import Tokenizer, decoders, models, pre_tokenizers, trainers

torch.set_num_threads(1)                      # 计时对比要稳，固定成单线程
torch.manual_seed(0)
print("PyTorch", torch.__version__, " 线程数", torch.get_num_threads())

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
PyTorch 2.14.1+cpu  线程数 1
```

::: v-pre
## 1. 拿第 12 章的基线模型当研究对象

后面所有的量都在这一个模型上测：[第 12 章](https://lewislau86.github.io/tinyllm/tinyllm-model)的配置
（d=128、4 层、4 头、上下文 64、词表 4096）和同样的 300 步训练。
推理效率与模型写得好不好无关，所以这里不需要一个好模型，只需要一个尺寸确定、参数已知的模型。
:::

<p class="nb-label">In [2]</p>

```python
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
model = Tiny()
steps, batch = 300, 32
plan = torch.Generator().manual_seed(1234)
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
model.eval()

n_params = sum(p.numel() for p in model.parameters())
weight_bytes = sum(p.numel() * p.element_size() for p in model.parameters())
print(f"参数 {n_params:,} 个，权重占 {weight_bytes / 2**20:.1f} MiB（FP32）")
print(f"词表 {V}，上下文 {CTX}，{L} 层，{H} 个头，每头 {D // H} 维")
```

```text
参数 1,311,360 个，权重占 5.0 MiB（FP32）
词表 4096，上下文 64，4 层，4 个头，每头 32 维
```

::: v-pre
## 2. 一次生成分成两段：prefill 和 decode

提示词的每个 token 在生成之前就已经全部到齐，可以一次性并行送进模型——这段叫 **prefill**。
之后每步只多出一个 token，却要再走一遍完整的模型——每步叫一次 **decode**。

两个阶段算的东西不一样：

- prefill 一次处理 $T$ 个位置，矩阵乘法的行数是 $T$，算力用满，**卡在计算**；
- decode 一次只处理 1 个位置，矩阵乘法的行数是 1，但每步都要把**全部权重**从内存读一遍，**卡在带宽**。

下面各走一遍，把两段的耗时分开记下来。
:::

<p class="nb-label">In [3]</p>

```python
prompt_ids = torch.tensor([tok.encode("春眠不觉晓，处处闻啼鸟。").ids])
n_prefill = prompt_ids.shape[1]

with torch.no_grad():
    model(prompt_ids)                                   # 预热：第一次调用要建各种缓冲，不算进计时
    t0 = time.perf_counter()
    for _ in range(5):
        logits = model(prompt_ids)
    prefill_s = (time.perf_counter() - t0) / 5
    one = prompt_ids[:, -1:]
    t0 = time.perf_counter()
    for _ in range(50):
        model(one)
    decode_s = (time.perf_counter() - t0) / 50

print(f"提示词 {n_prefill} 个 token：prefill 一次 {prefill_s * 1000:.1f} ms，之后每步 decode {decode_s * 1000:.1f} ms")
print(f"同样一次前向：prefill 处理 {n_prefill} 个位置，decode 处理 1 个；"
      f"摊到每个位置，decode 要贵 {decode_s / (prefill_s / n_prefill):.0f} 倍")
```

```text
提示词 10 个 token：prefill 一次 1.4 ms，之后每步 decode 1.2 ms
同样一次前向：prefill 处理 10 个位置，decode 处理 1 个；摊到每个位置，decode 要贵 9 倍
```

::: v-pre
最后一个数才是关键：prefill 处理 **每个位置** 的耗时，比 decode 处理 **一个位置** 低一个数量级。
为什么？因为 decode 每一步都要把上面算出的 5 左右 MiB 权重从头读一遍，而只做了一行矩阵乘法。
权重读一遍的时间是固定的，分摊给 1 个位置还是 60 个位置，差别就在这里。

一次请求的延迟由两段拼起来：从发出请求到第一个字出来，是 prefill 的耗时，叫**首字延迟**（TTFT）；
之后每个字的间隔，是 decode 的耗时，叫**每 token 延迟**（TPOT 或 ITL）。这两个指标分开报，
因为优化它们的手段完全不同。
:::

::: v-pre
## 3. 不缓存，每一步都要重算整段前缀

上一节的 decode 里，每步都把整段前缀重新送进模型。可是旧位置的 K、V 只取决于旧 token，不会因为后面新来了一个字就改变。
把它们存下来，就叫 **KV cache**。

先用第 5 章的六项教学词表把“一次算完”和“逐步缓存”并排放好，确认两者结果完全一致：
:::

<p class="nb-label">In [4]</p>

```python
torch.manual_seed(7)
embedding = nn.Embedding(6, 4)              # 第 5 章的六项教学词表
position = nn.Embedding(3, 4)               # 教学用的绝对位置向量
x = embedding(torch.tensor([2, 3, 4])) + position(torch.arange(3))  # “我 在 学习” → [3, 4]

q_proj, k_proj, v_proj = (nn.Linear(4, 4, bias=False) for _ in range(3))
q, k, v = q_proj(x), k_proj(x), v_proj(x)
scores = q @ k.T / math.sqrt(4)
future = torch.triu(torch.ones(3, 3, dtype=torch.bool), diagonal=1)   # 不许看未来
weights = scores.masked_fill(future, float("-inf")).softmax(dim=-1)
context = weights @ v                       # 一次性算出 3 个位置的输出
print("context 形状:", tuple(context.shape))
```

```text
context 形状: (3, 4)
```

<p class="nb-label">In [5]</p>

```python
cached_k, cached_v, incremental = [], [], []
for t in range(len(x)):
    q_t = q_proj(x[t:t+1])                  # 只为新位置算 Q
    cached_k.append(k_proj(x[t:t+1]))       # 新位置的 K、V 追加进缓存
    cached_v.append(v_proj(x[t:t+1]))
    all_k, all_v = torch.cat(cached_k), torch.cat(cached_v)
    attention_t = (q_t @ all_k.T / math.sqrt(4)).softmax(dim=-1)   # 权重每步重算
    incremental.append(attention_t @ all_v)
assert torch.allclose(torch.cat(incremental), context, atol=1e-6)
print("一次性计算与逐步缓存的最大误差:", (torch.cat(incremental) - context).abs().max().item())
print("缓存了", len(cached_k), "个位置的 K 和 V；缓存的是 K/V，不是注意力分数")
```

```text
一次性计算与逐步缓存的最大误差: 2.9802322387695312e-08
缓存了 3 个位置的 K 和 V；缓存的是 K/V，不是注意力分数
```

::: v-pre
![KV cache 的两个阶段：prefill 一次算出提示词所有位置的 K/V；之后每个解码步只为新 token 计算 K/V 并追加到缓存，新 token 的 Q 与缓存中全部 K 打分，再对全部 V 加权求和](/tinyllm/figures/kv-cache.svg)

怎么读这张图：左边 prefill 一次把提示词的 K、V 全算出来；右边每个 decode 步只算新来的一个位置。
橙色是这一步新算的，灰色是从缓存直接读的。
:::

::: v-pre
## 4. 数一数：不缓存要多算多少行

把位置加到 12 个，数每一步实际投影了几行 K、V。这一步与硬件无关，在任何机器上都是这个结果。
:::

<p class="nb-label">In [6]</p>

```python
torch.manual_seed(0)
xs = torch.randn(12, 4)                     # 12 个位置的输入向量（示意）

def attend(q_t, ks, vs):
    return (q_t @ ks.T / math.sqrt(4)).softmax(dim=-1) @ vs

no_cache, with_cache, cache_k, cache_v = [], [], [], []
for t in range(len(xs)):
    q_t = q_proj(xs[t:t+1])
    ks, vs = k_proj(xs[:t+1]), v_proj(xs[:t+1])          # 不缓存：前面所有位置重算一遍
    out_full = attend(q_t, ks, vs)
    cache_k.append(k_proj(xs[t:t+1]))                   # KV cache：只算新位置
    cache_v.append(v_proj(xs[t:t+1]))
    out_cached = attend(q_t, torch.cat(cache_k), torch.cat(cache_v))
    assert torch.allclose(out_full, out_cached, atol=1e-6)
    no_cache.append(ks.shape[0])
    with_cache.append(cache_k[-1].shape[0])
print("不缓存，每步重算的 K/V 行数:", no_cache, "合计", sum(no_cache))
print("KV cache，每步新算的 K/V 行数:", with_cache, "合计", sum(with_cache))
print(f"生成 12 个字：不缓存 {sum(no_cache)} 行 = 12 × 13 / 2，有缓存 {sum(with_cache)} 行 = 12")
```

```text
不缓存，每步重算的 K/V 行数: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12] 合计 78
KV cache，每步新算的 K/V 行数: [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1] 合计 12
生成 12 个字：不缓存 78 行 = 12 × 13 / 2，有缓存 12 行 = 12
```

::: v-pre
不缓存时第 $t$ 步要重算 $t$ 行，生成 $n$ 个字一共 $n(n+1)/2$ 行，随长度平方增长；有缓存时每步只算 1 行，一共 $n$ 行。
两种做法并排播放：
:::

<p class="nb-label">In [7]</p>

```python
import json
with open("kv_cache_counts.json", "w", encoding="utf-8") as f:
    json.dump({"tokens": list("春乃发生。随风潜入夜，润"), "no_cache": no_cache, "with_cache": with_cache}, f, ensure_ascii=False)
```

::: v-pre
<KVCacheRace />

注意省下的只是 K、V 的 **投影**。新 Q 仍然要和缓存里所有的 K 打分，这部分计算随上下文变长而增加；
缓存本身也要占内存。
:::

::: v-pre
## 5. 缓存有多大：一条公式和一张表

对普通全注意力 Decoder，每层要为每个 token 存一组 K 和一组 V，每个头的维度是 `每头维度`，元素按 FP16 存就占 2 字节：

$$
\text{缓存字节} = 2 \times \text{层数} \times \text{token 数} \times \text{KV 头数} \times \text{每头维度} \times \text{每元素字节}
$$

最前面的 2 对应 K 和 V。乘以并发请求数，就是这一批请求要占的总量。
:::

<p class="nb-label">In [8]</p>

```python
def kv_bytes(tokens, layers, kv_heads, head_dim, nbytes=2, concurrency=1):
    return 2 * layers * tokens * kv_heads * head_dim * nbytes * concurrency

head_dim = D // H
print(f"TinyLLM（{L} 层，{H} 个 KV 头，每头 {head_dim} 维）")
for T in (64, 256, 1024):
    print(f"  {T:>5} 个 token：FP32 {kv_bytes(T, L, H, head_dim, 4) / 2**20:7.2f} MiB   "
          f"FP16 {kv_bytes(T, L, H, head_dim, 2) / 2**20:7.2f} MiB")
print(f"  上下文 {CTX}、8 个请求并发（FP32）：{kv_bytes(CTX, L, H, head_dim, 4, 8) / 2**20:.2f} MiB")

# 对照：Llama 3 8B 的公布配置（32 层、8 个 KV 头、每头 128 维、FP16）
print("Llama 3 8B（32 层，8 个 KV 头，每头 128 维，FP16）")
for T in (1024, 8192, 32768):
    print(f"  {T:>6} 个 token：{kv_bytes(T, 32, 8, 128, 2) / 2**30:6.2f} GiB")
per_token = kv_bytes(1, 32, 8, 128, 2)
print(f"  每个 token {per_token / 1024:.0f} KiB；权重 FP16 约 16 GiB，80 GiB 的卡上留给缓存的空间约 64 GiB，"
      f"理论上限约 {64 * 2**30 // (per_token * 8192)} 条 8K 序列")
```

```text
TinyLLM（4 层，4 个 KV 头，每头 32 维）
     64 个 token：FP32    0.25 MiB   FP16    0.12 MiB
    256 个 token：FP32    1.00 MiB   FP16    0.50 MiB
   1024 个 token：FP32    4.00 MiB   FP16    2.00 MiB
  上下文 64、8 个请求并发（FP32）：2.00 MiB
Llama 3 8B（32 层，8 个 KV 头，每头 128 维，FP16）
    1024 个 token：  0.12 GiB
    8192 个 token：  1.00 GiB
   32768 个 token：  4.00 GiB
  每个 token 128 KiB；权重 FP16 约 16 GiB，80 GiB 的卡上留给缓存的空间约 64 GiB，理论上限约 64 条 8K 序列
```

::: v-pre
![KV cache 占多少：横轴是上下文长度（对数），两条线是 TinyLLM 与 Llama 3 8B 的单请求缓存；右侧条形图是同一张 80 GiB 卡上权重与缓存的空间分配](/tinyllm/figures/kv-cache-size.svg)

怎么读这张图：**KV cache 随 token 数线性增长，而权重是常数。** 小模型上权重占大头，
大模型上缓存会先撑满显存——Llama 3 8B 每条 8K 序列要 1 GiB，一张 80 GiB 卡把 16 GiB 留给权重之后，
剩下的只够约 60 条并发序列。这就是“到底能同时服务多少用户，往往先卡在缓存而不是权重”的来源。

缓存还有另一种代价：`2 × 层数 × 头数` 这个因子决定了 GQA 为什么省缓存——[第 6 章](https://lewislau86.github.io/tinyllm/self-attention)
讲的 GQA 让多个 Q 头共用一组 K、V，KV 头数从 32 降到 8，缓存直接变成四分之一。
:::

::: v-pre
## 6. decode 为什么慢：每步都要搬一遍权重

一次 decode 只做一行矩阵乘法，却要把全部权重读进来。算一笔账：权重 $W$ 字节，内存带宽 $B$ 字节/秒，
那么每秒最多前向 $B / W$ 次——这是带宽给出的**上限**，与算力无关。
:::

<p class="nb-label">In [9]</p>

```python
for name, params, nbytes, bw in (("TinyLLM（FP32）", n_params, 4, 200e9), ("Llama 3 8B（FP16）", 8.03e9, 2, 3.35e12)):
    w = params * nbytes
    print(f"{name}：权重 {w / 1e9:.2f} GB，若带宽 {bw / 1e9:.0f} GB/s，"
          f"每秒最多前向 {bw / w:,.0f} 次 → 单请求上限 {bw / w:,.0f} token/s")
print("H100 的 3.35 TB/s 是公布值；200 GB/s 是台式机内存的常见量级，不是实测。")
```

```text
TinyLLM（FP32）：权重 0.01 GB，若带宽 200 GB/s，每秒最多前向 38,128 次 → 单请求上限 38,128 token/s
Llama 3 8B（FP16）：权重 16.06 GB，若带宽 3350 GB/s，每秒最多前向 209 次 → 单请求上限 209 token/s
H100 的 3.35 TB/s 是公布值；200 GB/s 是台式机内存的常见量级，不是实测。
```

::: v-pre
Llama 3 8B 在 H100 上的上限是每秒 417 个 token，和实践中单请求 decode 的速度在同一量级。
这项估算说明的是：**decode 的天花板由带宽决定，批处理之所以有效，就是因为一次读进权重可以同时伺候多个请求。**
批量把这份读取代价摊薄，是[第 30 章](https://lewislau86.github.io/tinyllm/batching)的主题。
:::

::: v-pre
## 7. 指标：TTFT、TPOT、ITL、E2EL

一次请求的延迟由几个时间段拼成，名字要分开记：

- **TTFT**（Time to First Token）：请求发出到第一个字出现，主要由 prefill 决定；
- **ITL**（Inter-Token Latency）：相邻两个字之间的间隔；
- **TPOT**（Time per Output Token）：第一个字之后的总时间除以生成的 token 数减一，即 $\text{TPOT} = \frac{\text{E2EL} - \text{TTFT}}{n - 1}$；
- **E2EL**（End-to-End Latency）：从发出请求到最后一个字，$\text{E2EL} = \text{TTFT} + (n-1) \times \text{平均 ITL}$。

单条请求上，平均 ITL 就等于 TPOT；多条请求上要注意口径：**按请求平均的 TPOT** 和
**按 token 平均的 ITL** 不是同一个数，后者给长回答更多权重。看别人的基准报告时，先确认它用的是哪个。
:::

<p class="nb-label">In [10]</p>

```python
@torch.no_grad()
def one_request(prompt, n_new=16):
    idx = torch.tensor([tok.encode(prompt).ids])
    t0 = time.perf_counter()
    model(idx)
    ttft = time.perf_counter() - t0                  # 第一个字出来之前的那次前向
    gaps = []
    for _ in range(n_new - 1):
        t1 = time.perf_counter()
        logits = model(idx)
        nxt = int(logits[0, -1].argmax())
        idx = torch.cat([idx, torch.tensor([[nxt]])], dim=1)
        gaps.append(time.perf_counter() - t1)
    e2e = time.perf_counter() - t0
    return {"ttft": ttft, "e2e": e2e, "gaps": gaps, "tokens": n_new}

runs = [one_request(p[:6]) for p in val_poems[:8]]
ttfts = sorted(r["ttft"] for r in runs)
e2es = sorted(r["e2e"] for r in runs)
tpots = sorted((r["e2e"] - r["ttft"]) / (r["tokens"] - 1) for r in runs)
def pctl(xs, q):
    return xs[min(len(xs) - 1, int(round(q * (len(xs) - 1))))]
print(f"{len(runs)} 条请求，各生成 {runs[0]['tokens']} 个字")
print(f"TTFT  中位 {pctl(ttfts, .5) * 1000:.1f} ms   最慢 {ttfts[-1] * 1000:.1f} ms")
print(f"TPOT  中位 {pctl(tpots, .5) * 1000:.1f} ms   最慢 {tpots[-1] * 1000:.1f} ms")
print(f"E2EL  中位 {pctl(e2es, .5) * 1000:.1f} ms   最慢 {e2es[-1] * 1000:.1f} ms")
print("报两个数（中位数 + 最慢），是因为只看平均会被少数慢请求带偏；生产上常报 P50 与 P99。")
```

```text
8 条请求，各生成 16 个字
TTFT  中位 1.2 ms   最慢 1.7 ms
TPOT  中位 1.4 ms   最慢 1.7 ms
E2EL  中位 21.8 ms   最慢 27.3 ms
报两个数（中位数 + 最慢），是因为只看平均会被少数慢请求带偏；生产上常报 P50 与 P99。
```

::: v-pre
## 8. goodput：只有达标的那部分吞吐才算数

吞吐（每秒完成多少个请求、每秒生成多少个 token）单独看会骗人：把 batch 开大，吞吐上去了，
但每个请求都变慢了，用户不一定还能用。于是有了 **goodput**：在满足时延目标（SLO）的前提下，
每秒完成了多少请求。

这批请求的 E2EL 中位数约 21 ms。把 SLO 设在它附近：松一点（25 ms）和紧一点（21 ms），各数一次。
:::

<p class="nb-label">In [11]</p>

```python
span = sum(r["e2e"] for r in runs)                  # 串行跑完这 8 条的总时间
throughput = len(runs) / span
e2e_sorted = sorted(r["e2e"] for r in runs)
slo_table = {}
print("SLO 用这一批请求自己的分位数定出来，每一档的达标条数因此是固定的：")
for name, k in (("松（= 最慢的那条）", len(runs)), ("中（= 中位数）", len(runs) // 2), ("紧（= 下四分位）", len(runs) // 4)):
    SLO = e2e_sorted[k - 1]
    slo_table[name] = {"slo": SLO, "k": k}
    print(f"  {name:<16} SLO {SLO * 1000:5.1f} ms  达标 {k}/{len(runs)} 条  "
          f"goodput 是吞吐的 {k / len(runs):.0%}")
print(f"吞吐（不看时延目标）{throughput:.1f} 请求/秒；goodput 依次是它的 100%、50%、25%——"
      "系统一个参数都没改，能用的部分变少了。")
print(f"生成的 token 数 {sum(r['tokens'] for r in runs)}，输出吞吐 {sum(r['tokens'] for r in runs) / span:.0f} token/秒")
```

```text
SLO 用这一批请求自己的分位数定出来，每一档的达标条数因此是固定的：
  松（= 最慢的那条）       SLO  27.3 ms  达标 8/8 条  goodput 是吞吐的 100%
  中（= 中位数）         SLO  21.6 ms  达标 4/8 条  goodput 是吞吐的 50%
  紧（= 下四分位）        SLO  21.1 ms  达标 2/8 条  goodput 是吞吐的 25%
吞吐（不看时延目标）44.5 请求/秒；goodput 依次是它的 100%、50%、25%——系统一个参数都没改，能用的部分变少了。
生成的 token 数 128，输出吞吐 711 token/秒
```

::: v-pre
![延迟指标的时间线：请求发出 → prefill（这段是 TTFT）→ 逐个 decode（每段是一个 ITL）→ 最后一个字（全部加起来是 E2EL）；下面标出 TPOT = (E2EL − TTFT) / (n − 1)](/tinyllm/figures/latency-metrics.svg)

怎么读这张图：TTFT 只覆盖 prefill，E2EL 覆盖全程，TPOT 是 decode 段的平均值。
一个系统可以 TTFT 很快、TPOT 很慢（长提示词、小 batch、算力不够），也可以反过来，所以三个数必须一起报。
:::

::: v-pre
## 9. chunked prefill：长提示词不再把别人堵住

线上不会只有一条请求。一个长提示词的 prefill 会占住整个前向，正在 decode 的请求只能在旁边等——
用户看到的是“输出卡住了一下”。把提示词切成几块、分几次前向，每块之间让 decode 插进来，就叫 **chunked prefill**。

分块不改变数学结果：后面的块通过 KV cache 看到前面的块，等价于一次算完。先证明这一点。
:::

<p class="nb-label">In [12]</p>

```python
ids_full = torch.tensor([tok.encode(val_poems[0][:20]).ids])
with torch.no_grad():
    full = model(ids_full)[0]                                    # 一次算完：每个位置的 logits

def forward_piece(x, past_k, past_v):
    """只算 x 这一块；注意力通过 past_k / past_v 看到前面所有块，掩码负责因果。
    返回这一块的 logits，以及拼上这一块之后的 K、V。"""
    h = model.embed(x)
    T = x.shape[1]
    base = 0 if past_k is None else past_k[0].shape[2]      # 这一块从第几个位置开始
    cos, sin = model.cos[base:base + T], model.sin[base:base + T]   # RoPE 要按全局位置转
    ks, vs = [], []
    for b_i, block in enumerate(model.blocks):
        q, k, v = (t.view(1, T, H, D // H).transpose(1, 2)
                   for t in block.qkv(block.norm1(h)).split(D, dim=-1))
        q, k, v = apply_rope(q, cos, sin), apply_rope(k, cos, sin), v
        ks.append(k)
        vs.append(v)
        K = k if past_k is None else torch.cat([past_k[b_i], k], dim=2)
        V = v if past_v is None else torch.cat([past_v[b_i], v], dim=2)
        mask = torch.ones(T, K.shape[2], dtype=torch.bool).tril(base)   # 第 i 行能看到前面 base 个位置加上自己
        y = F.scaled_dot_product_attention(q, K, V, attn_mask=mask)
        h = h + block.proj(y.transpose(1, 2).reshape(1, T, D))
        hh = block.norm2(h)
        h = h + block.down(F.silu(block.gate(hh)) * block.up(hh))
    return model.norm(h) @ model.embed.weight.T, ks, vs

def run_chunked(chunk_list):
    past_k = past_v = None
    parts = []
    with torch.no_grad():
        for ch in chunk_list:
            logits, new_k, new_v = forward_piece(ch, past_k, past_v)
            parts.append(logits)
            past_k = new_k if past_k is None else [torch.cat([a, b], dim=2) for a, b in zip(past_k, new_k)]
            past_v = new_v if past_v is None else [torch.cat([a, b], dim=2) for a, b in zip(past_v, new_v)]
    return torch.cat(parts, dim=1)

chunks = [ids_full[:, i:i + 8] for i in range(0, ids_full.shape[1], 8)]
piecewise = run_chunked(chunks)
print("提示词切成", len(chunks), "块（每块最多 8 个 token），共", ids_full.shape[1], "个位置")
print("一次算完与分块计算的最大误差:", (piecewise - full).abs().max().item())
```

```text
提示词切成 3 块（每块最多 8 个 token），共 21 个位置
一次算完与分块计算的最大误差: 0.0
```

::: v-pre
误差在浮点舍入的量级（~1e-6），说明分块只是在调度上把一次大的前向切成几次小的，
算术上完全等价。它的收益是**别的请求不必等这一次长前向做完**，代价是调度更复杂、
小块要反复读 KV cache，反而可能变慢——块大小没有通用最优值。
:::

::: v-pre
## 10. 把这章的量存下来

网站上的三张图用这份记录画：缓存大小表、延迟指标时间线、缓存省下的投影行数。
:::

<p class="nb-label">In [13]</p>

```python
data = {
    "model": {"params": n_params, "weight_bytes": weight_bytes, "layers": L, "kv_heads": H,
              "head_dim": D // H, "context": CTX, "vocab": V},
    "phases": {"n_prefill": n_prefill, "prefill_ms": round(prefill_s * 1000, 2), "decode_ms": round(decode_s * 1000, 2)},
    "counts": {"no_cache": no_cache, "with_cache": with_cache},
    "cache_bytes": {"tiny": {T: kv_bytes(T, L, H, D // H, 2) for T in (64, 256, 1024, 4096)},
                    "llama8b": {T: kv_bytes(T, 32, 8, 128, 2) for T in (1024, 8192, 32768)}},
    "metrics": {k: [round(r[k] * 1000, 2) for r in runs] for k in ("ttft", "e2e")},
    "tpot_ms": [round((r["e2e"] - r["ttft"]) / (r["tokens"] - 1) * 1000, 2) for r in runs],
    "throughput": round(throughput, 3),
    "goodput": {name: {"slo_ms": round(v["slo"] * 1000, 2), "ok": v["k"], "n": len(runs)}
                for name, v in slo_table.items()},
    "chunked": {"chunks": len(chunks), "tokens": int(ids_full.shape[1]),
                "max_err": round(float((piecewise - full).abs().max()), 8)},
}
with open("inference_efficiency.json", "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False)
print("写好了 inference_efficiency.json：", sorted(data))
```

```text
写好了 inference_efficiency.json： ['cache_bytes', 'chunked', 'counts', 'goodput', 'metrics', 'model', 'phases', 'throughput', 'tpot_ms']
```

