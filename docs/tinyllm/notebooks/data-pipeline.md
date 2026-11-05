---
title: "第 14 章：语料与数据管线（notebook 在线查看）"
search: false
editLink: false
prev: false
next: false
pageClass: tinyllm-course
---

<!-- 本页由 scripts/build-tinyllm-code.py 根据 notebook 自动生成，请勿手改。 -->

::: tip 这是 notebook 的只读预览
[返回教案](/tinyllm/data-pipeline) · [在 Colab 中运行](https://colab.research.google.com/github/lewislau86/lewislau86.github.io/blob/master/docs/public/tinyllm/notebooks/data-pipeline.ipynb) · <a href="/tinyllm/notebooks/data-pipeline.ipynb" download>下载 .ipynb</a> · <a href="/tinyllm/code/data-pipeline.py" download>下载 .py</a> · [在 GitHub 上查看](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/tinyllm/notebooks/data-pipeline.ipynb)

下面的代码和输出与 notebook 文件完全一致。想修改、运行，请用 Colab 打开或下载到本地。
:::

::: v-pre
# 第 14 章：语料与数据管线

配套教案：https://lewislau86.github.io/tinyllm/data-pipeline

从上到下运行即可（`python data-pipeline.py`），CPU 上约两分钟（其中泄漏实验训练 3 个小模型约一分钟）。
需要安装 PyTorch、`tokenizers` 和 `opencc-python-reimplemented`（繁体转简体）。
这个文件是本章代码的唯一来源：教案中的代码片段由 `# region 名字` / `# endregion 名字`
标记的区域直接引用，notebook 也由它生成（scripts/build-tinyllm-code.py）。

本章跟着一首诗走完整条数据管线：《全唐诗》的原始记录 → 清洗筛选 → 繁转简 → 去重 → 划分 → 泄漏检查
→ 拼成 token 流 → 切成 batch。每一步都问一句：不做会怎样？
:::

<p class="nb-label">In [1]</p>

```python
import math
import random
import re
import time
from collections import Counter, defaultdict
from dataclasses import dataclass

import torch
from torch import nn
from torch.nn import functional as F
from tokenizers import Tokenizer, decoders, models, pre_tokenizers, trainers
from opencc import OpenCC

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
## 1. 原始记录长什么样

统一语料是从开源数据集 chinese-poetry（MIT 许可证）加工出来的。这里取《全唐诗》最前面的 3 个源文件，
和上游固定版本 `b8594f81` 逐字节相同，本课网站上有一份镜像。
:::

<p class="nb-label">In [2]</p>

```python
RAW_URL = "https://lewislau86.github.io/tinyllm/data/"
RAW_FILES = {
    "poet.tang.0.json": "4f88f429938082523cdc72a1612bd7a7c3e3f7a33f8192c61ae51340efc3c92d",
    "poet.tang.1000.json": "6e703b8d8dcedbd6110f6d48d043665ca2131db2035a5bfcef5e59a19aeb6d75",
    "poet.tang.2000.json": "ec28efa7e2ae9cdbbba09f0ed186e32ccae47a325ad1e5816b7ad56071c1665a",
}

def load_raw_tang():
    """《全唐诗》最前面 3 个源文件里的全部原始记录。和 load_poems 一样先在本地找，找不到就从网站下载。"""
    data_dir = Path(os.environ.get("TINYLLM_DATA", "tang-poems.jsonl")).parent
    records = []
    for name, sha in RAW_FILES.items():
        path = next((p for p in (data_dir / name, Path(name), Path("../data") / name) if p.exists()), None)
        if path is None:
            path = Path(name)
            with urlopen(RAW_URL + name, timeout=120) as r:
                path.write_bytes(r.read())
        raw = path.read_bytes().replace(b"\r\n", b"\n")
        if hashlib.sha256(raw).hexdigest() != sha:
            raise RuntimeError(f"{path} 和上游版本不一致，删掉它再运行一次即可重新下载")
        records += json.loads(raw)
    return records

records = load_raw_tang()
print("原始记录：", len(records), "条")
print(json.dumps(records[0], ensure_ascii=False, indent=1))
```

```text
原始记录： 3002 条
{
 "author": "太宗皇帝",
 "paragraphs": [
  "秦川雄帝宅，函谷壯皇居。",
  "綺殿千尋起，離宮百雉餘。",
  "連甍遙接漢，飛觀迥凌虛。",
  "雲日隱層闕，風煙出綺疎。"
 ],
 "title": "帝京篇十首 一",
 "id": "3ad6d468-7ff1-4a7b-8b24-a27d70d00ed4"
}
```

::: v-pre
正文分散在 `paragraphs` 列表里，每个元素是一联（两句）。用的是繁体字。再看几条“不干净”的记录：
:::

<p class="nb-label">In [3]</p>

```python
def body(record):
    return "".join(record.get("paragraphs", []))

for label, pattern in [("缺字", "□"), ("校勘记号", r"\["), ("扩展区生僻字", r"[\U00020000-\U0003FFFF㐀-䶿]")]:
    hits = [r for r in records if re.search(pattern, body(r))]
    text = body(hits[0])
    m = re.search(pattern, text)
    print(f"{label}：{len(hits)} 条，例如《{hits[0]['title']}》…{text[max(0, m.start() - 9):m.start() + 9]}…")
```

```text
缺字：3 条，例如《守歲》…分。綬吐芽猶嫩，冰□已鏤津。薄紅梅色…
校勘记号：55 条，例如《重陽日中外同歡以詩言志因示羣官》…[爽]節在重九，物…
扩展区生僻字：29 条，例如《幸武功慶善宮》…于陪武帳，日逐衛文㮰。端扆朝四岳，無…
```

::: v-pre
## 2. 清洗与筛选：一个漏斗

每条规则只做一件事，按顺序过一遍，数一数每一步还剩多少。
:::

<p class="nb-label">In [4]</p>

```python
LINE5 = re.compile(r"[一-鿿]{5}，[一-鿿]{5}。")      # 一联：五字，五字。只允许基本区汉字

def funnel(records):
    steps = [("原始记录", records)]
    keep = lambda name, rule: steps.append((name, [r for r in steps[-1][1] if rule(r)]))
    keep("正文非空", lambda r: body(r))
    keep("没有缺字和校勘记号", lambda r: not re.search(r"[□\[\]]", body(r)))
    keep("只含常用汉字和，。", lambda r: re.fullmatch(r"[一-鿿，。]+", body(r)))
    keep("五言绝句或律诗", lambda r: len(r["paragraphs"]) in (2, 4) and all(LINE5.fullmatch(p) for p in r["paragraphs"]))
    return steps

stages = funnel(records)
for name, rows in stages:
    print(f"{name:<12}{len(rows):>6}")
```

```text
原始记录          3002
正文非空          3002
没有缺字和校勘记号     2944
只含常用汉字和，。     2786
五言绝句或律诗        936
```

::: v-pre
统一语料只用五言绝句和律诗，所以最后一步筛掉了大半。剩下的转成简体：
:::

<p class="nb-label">In [5]</p>

```python
t2s = OpenCC("t2s").convert
wuyan = stages[-1][1]
trad = [body(r) for r in wuyan]
simp = [t2s(t) for t in trad]
print(trad[0], "→", simp[0])
```

```text
秦川雄帝宅，函谷壯皇居。綺殿千尋起，離宮百雉餘。連甍遙接漢，飛觀迥凌虛。雲日隱層闕，風煙出綺疎。 → 秦川雄帝宅，函谷壮皇居。绮殿千寻起，离宫百雉余。连甍遥接汉，飞观迥凌虚。云日隐层阙，风烟出绮疎。
```

::: v-pre
## 3. 去重

先看完全相同的正文。注意顺序：繁转简之前数一次，之后再数一次。
:::

<p class="nb-label">In [6]</p>

```python
dup_trad = len(trad) - len(set(trad))
dup_simp = len(simp) - len(set(simp))
print(f"繁体时完全重复：{dup_trad} 首；转成简体后：{dup_simp} 首")
variants = defaultdict(set)                     # 简体正文 → 它来自哪几种繁体写法
for a, b in zip(trad, simp):
    variants[b].add(a)
for b, forms in variants.items():
    if len(forms) > 1:
        x, y = sorted(forms)[:2]
        i = next(i for i in range(len(x)) if x[i] != y[i])          # 第一个不同的字
        print(f"  …{x[max(0, i - 3):i + 2]}… 和 …{y[max(0, i - 3):i + 2]}… → 简体都是 …{b[max(0, i - 3):i + 2]}…")
unique = list(dict.fromkeys(simp))
```

```text
繁体时完全重复：9 首；转成简体后：11 首
  …天子按琱戈… 和 …天子按雕戈… → 简体都是 …天子按雕戈…
  …。自憐回雪… 和 …。自憐迴雪… → 简体都是 …。自怜回雪…
```

::: v-pre
再看“几乎相同”的诗：同一首诗传抄出几个版本，只差一两个字。逐句比对会漏掉“每句都差一个字”的版本，
所以按**字的二元组**（相邻两个字）来比：两首诗共有的二元组，占较短那首的比例，叫重合度。
两首诗互相比较要两两配对，用倒排索引（二元组 → 含有它的诗）只和至少共享一个二元组的诗比。
:::

<p class="nb-label">In [7]</p>

```python
def bigrams(text):
    s = re.sub("[，。]", "", text)
    return {s[i:i + 2] for i in range(len(s) - 1)}

class NearDupIndex:
    """倒排索引：二元组 → 含有它的诗的编号。查询时只和至少共享一个二元组的诗比较。"""
    def __init__(self):
        self.grams, self.index = [], defaultdict(list)

    def add(self, text):
        g = bigrams(text)
        for b in g:
            self.index[b].append(len(self.grams))
        self.grams.append(g)

    def best(self, text):
        """返回 (最高重合度, 对应的诗的编号)；重合度 = 共有二元组数 ÷ 较短那首的二元组数。"""
        g = bigrams(text)
        shared = Counter(k for b in g for k in self.index[b])
        if not shared:
            return 0.0, None
        score = lambda k: shared[k] / min(len(g), len(self.grams[k]))
        k = max(shared, key=score)
        return score(k), k

def dedup_near(texts, threshold=0.5):
    kept, index, removed = [], NearDupIndex(), []
    for t in texts:
        score, k = index.best(t)
        if score >= threshold:
            removed.append((t, kept[k], score))
            continue
        kept.append(t)
        index.add(t)
    return kept, removed

kept, removed = dedup_near(unique)
print(f"精确去重后 {len(unique)} 首，近重复去掉 {len(removed)} 首，剩 {len(kept)} 首")
for t, k, s in sorted(removed, key=lambda x: x[2])[:3]:
    print(f"  重合度 {s:.2f}：{t[:24]}\n            {k[:24]}")
```

```text
精确去重后 925 首，近重复去掉 33 首，剩 892 首
  重合度 0.72：倡楼启曙扉，杨柳正依依。莺啼知岁隔，条变识春归。
            倡楼启曙扉，园柳正依依。鸟鸣知岁隔，条变识春归。
  重合度 0.77：不分君恩断，观妆视镜中。容华尚春日，娇爱已秋风。
            不分君恩断，新妆视镜中。容华尚春日，娇爱已秋风。
  重合度 0.79：荷恩承顾托，执契恭临抚。庙畧静边荒，天兵耀神武。
            荷恩承顾托，执契恭临抚。庙略静边荒，天兵曜神武。
```

::: v-pre
阈值 0.5 是怎么定的？把每首诗和它“最像的那首”的重合度画成分布：
:::

<p class="nb-label">In [8]</p>

```python
index = NearDupIndex()
best = []
for t in unique:
    best.append(index.best(t))
    index.add(t)
best_scores = [s for s, _ in best]
hist = Counter(min(int(s * 10), 9) for s in best_scores)
for b in range(10):
    print(f"{b / 10:.1f}～{(b + 1) / 10:.1f} {hist[b]:>5} {'█' * math.ceil(hist[b] / 10)}")
```

```text
0.0～0.1   754 ████████████████████████████████████████████████████████████████████████████
0.1～0.2   130 █████████████
0.2～0.3     3 █
0.3～0.4     4 █
0.4～0.5     1 █
0.5～0.6     0 
0.6～0.7     0 
0.7～0.8     4 █
0.8～0.9    12 ██
0.9～1.0    17 ██
```

::: v-pre
中间空档（0.2～0.5）里的那几首是什么？
:::

<p class="nb-label">In [9]</p>

```python
for t, (s, k) in zip(unique, best):
    if 0.2 <= s < 0.5:
        print(f"{s:.2f}  {t[:12]}  ｜  {unique[k][:12]}")
```

```text
0.26  陌头杨柳枝，已被春风吹。  ｜  玉窗朝日映，罗帐春风吹。
0.32  自君之出矣，弦吹绝无声。  ｜  自君之出矣，梁尘静不飞。
0.32  自君之出矣，宝镜为谁明。  ｜  自君之出矣，梁尘静不飞。
0.21  自君之出矣，万物看成古。  ｜  自君之出矣，梁尘静不飞。
0.49  妙算干戈止，神谋宇宙清。  ｜  妙筭申帷幄，神谋及庙庭。
0.26  自君之出矣，金炉香不然。  ｜  自君之出矣，梁尘静不飞。
0.32  自君之出矣，红颜转憔悴。  ｜  自君之出矣，梁尘静不飞。
0.37  自君之出矣，明镜罢红妆。  ｜  自君之出矣，红颜转憔悴。
```

::: v-pre
## 4. 划分：按诗的哈希

每首诗按正文的 SHA-256 决定去哪个集合，统一语料就是这样划分的。
:::

<p class="nb-label">In [10]</p>

```python
def split_of(text):
    h = int(hashlib.sha256(text.encode("utf-8")).hexdigest(), 16) % 20
    return "val" if h == 0 else "test" if h == 1 else "train"

corpus = load_poems(17439)
field = {p["text"]: p["split"] for p in corpus[39:]}            # 前 39 首是第 1 章的诗，固定放在训练集
same = [split_of(t) == field[t] for t in kept if t in field]
print(f"样本里有 {len(same)} 首也在统一语料中，算出的划分和 split 字段一致：{sum(same)}/{len(same)}")
print("样本的划分：", Counter(split_of(t) for t in kept))
```

```text
样本里有 890 首也在统一语料中，算出的划分和 split 字段一致：890/890
样本的划分： Counter({'train': 798, 'val': 52, 'test': 42})
```

::: v-pre
和“打乱后取前 5%”比一比：语料从 5000 首增加到 6000 首时，原来那 5000 首里有多少首换了集合？
:::

<p class="nb-label">In [11]</p>

```python
def random_split(texts, seed=0):
    order = list(range(len(texts)))
    random.Random(seed).shuffle(order)
    n_val = len(texts) // 20
    return {texts[i]: ("val" if r < n_val else "train") for r, i in enumerate(order)}

texts = [p["text"] for p in corpus]
before, after = random_split(texts[:5000]), random_split(texts[:6000])
moved = sum(before[t] != after[t] for t in texts[:5000])
print(f"打乱再切：5000 首里有 {moved} 首换了集合")
before_h, after_h = {t: split_of(t) for t in texts[:5000]}, {t: split_of(t) for t in texts[:6000]}
print(f"按哈希：  5000 首里有 {sum(before_h[t] != after_h[t] for t in texts[:5000])} 首换了集合")
```

```text
打乱再切：5000 首里有 465 首换了集合
按哈希：  5000 首里有 0 首换了集合
```

::: v-pre
## 5. 泄漏检查：在我们自己的语料上

统一语料的生成脚本已经去过重（正文相同，或首句、末句都相同，只留一份）。用上面的重合度再查一遍：
验证集里的诗，在训练集里有没有“近亲”？
:::

<p class="nb-label">In [12]</p>

```python
def leak_report(poems, threshold=0.5):
    train = [p["text"] for p in poems if p["split"] == "train"]
    val = [p["text"] for p in poems if p["split"] == "val"]
    index = NearDupIndex()
    for t in train:
        index.add(t)
    hits = [(v, train[k], s) for v in val for s, k in [index.best(v)] if s >= threshold]
    return train, val, index, hits

for n in (6000, 17439):
    train, val, index, hits = leak_report(corpus[:n])
    print(f"前 {n:>5} 首：验证集 {len(val)} 首，其中 {len(hits)} 首在训练集里有重合度 ≥ 0.5 的近亲")
for v, t, s in sorted(hits, key=lambda x: -x[2])[:3]:
    print(f"  {s:.2f} 验证：{v[:24]}\n       训练：{t[:24]}")
val_scores = [index.best(v)[0] for v in val]
```

```text
前  6000 首：验证集 291 首，其中 2 首在训练集里有重合度 ≥ 0.5 的近亲
```

```text
前 17439 首：验证集 852 首，其中 36 首在训练集里有重合度 ≥ 0.5 的近亲
  0.95 验证：何事长门闭，珠帘只自垂。月移深殿早，春向后宫迟。
       训练：何事长门闭，珠帘只自垂。月移深殿早，春向后宫迟。
  0.95 验证：簟凉秋气初，长信恨何如。拂黛月生指，解鬟云满梳。
       训练：簟凉秋气初，长信恨何如。拂黛月生指，解鬟云满梳。
  0.95 验证：不语焚香坐，心知道已成。流年衰此世，定力见他生。
       训练：不语焚香坐，心知道已成。流年衰此世，定力见他生。
```

::: v-pre
## 6. 实验：泄漏会让验证损失好看多少

用第 12 章的模型代码（原样复制）和第 12 章的分词器做法。为了让泄漏的效果显出来，故意放在“能背下来”的设定：
训练集只有 300 多首（含上面那些近亲），模型训练 200 步。三个评估集：

- 训练集本身；
- 干净验证集：200 首和训练集毫无重合（重合度 < 0.2）的验证诗；
- 近亲验证集：上一节查出来、在训练集里有近亲的验证诗。
:::

<p class="nb-label">In [13]</p>

```python
@dataclass
class TinyConfig:
    vocab_size: int = 4096     # BPE 词表大小（含 4 个特殊 token）
    d_model: int = 128         # 每个 token 向量的宽度 d
    n_layers: int = 4          # Block 层数 L
    n_heads: int = 4           # 注意力头数，每头 d / n_heads = 32 维
    context: int = 64          # 一次最多看多少个 token
    rope_base: float = 10000.0

cfg = TinyConfig()

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

train_poems = [p["text"] for p in corpus[:6000] if p["split"] == "train"]     # 第 12 章基线的训练集
tokenizer = train_tokenizer(train_poems, cfg.vocab_size)
EOS = tokenizer.token_to_id("<eos>")

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
第 12 章的数据流与评估口径：每首诗之后接 `<eos>`，验证时切成不重叠的窗口全部算一遍。
:::

<p class="nb-label">In [14]</p>

```python
def to_stream(texts):
    ids = []
    for t in texts:
        ids += tokenizer.encode(t).ids + [EOS]
    return torch.tensor(ids)

@torch.no_grad()
def evaluate(model, ids, T=cfg.context, batch=64):
    model.eval()
    n = (len(ids) - 1) // T * T
    xs, ys = ids[:n].view(-1, T), ids[1:n + 1].view(-1, T)
    total = sum(F.cross_entropy(model(xs[i:i + batch]).flatten(0, 1), ys[i:i + batch].flatten(), reduction="sum").item()
                for i in range(0, len(xs), batch))
    model.train()
    return total / ys.numel()
```

<p class="nb-label">In [15]</p>

```python
train_all, val_all, index, hits = leak_report(corpus)
partners = list(dict.fromkeys(t for _, t, _ in hits))                  # 训练集里的那些“近亲”
others = [t for t in train_all[:400] if t not in partners][:300]
small_train = partners + others
clean_val = [v for v, s in zip(val_all, (index.best(v)[0] for v in val_all)) if s < 0.2][:200]
dup_val = [v for v, _, _ in hits]
sets = {"训练集": to_stream(small_train), "干净验证": to_stream(clean_val), "近亲验证": to_stream(dup_val)}
for name, ids in sets.items():
    print(f"{name}：{ids.numel():>6} 个 token")
```

```text
训练集： 13019 个 token
干净验证：  8480 个 token
近亲验证：  1411 个 token
```

<p class="nb-label">In [16]</p>

```python
small = TinyConfig(n_layers=2)
steps, batch_size, every = 200, 16, 20
plan = torch.Generator().manual_seed(1234)                           # batch 计划：三个种子共用
starts = torch.randint(0, len(sets["训练集"]) - small.context - 1, (steps, batch_size), generator=plan)

curves = {}
for seed in (0, 1, 2):
    torch.manual_seed(seed)                                          # 种子只决定初始参数
    model = TinyLLM(small)
    optimizer = torch.optim.AdamW(model.parameters(), lr=3e-3, weight_decay=0.1)
    curve = {name: [] for name in sets}
    for step in range(steps + 1):
        if step % every == 0:
            for name, ids in sets.items():
                curve[name].append(evaluate(model, ids))
        if step == steps:
            break
        idx = starts[step][:, None] + torch.arange(small.context + 1)
        xb, yb = sets["训练集"][idx[:, :-1]], sets["训练集"][idx[:, 1:]]
        _, loss = model(xb, yb)
        optimizer.zero_grad(set_to_none=True)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        optimizer.step()
    curves[seed] = curve
```

<p class="nb-label">In [17]</p>

```python
print("步数   训练集        干净验证        近亲验证      （3 个种子的平均，括号里是最小～最大）")
for i in range(0, steps // every + 1, 2):
    row = []
    for name in sets:
        vals = [curves[s][name][i] for s in curves]
        row.append(f"{sum(vals) / 3:.2f} ({min(vals):.2f}～{max(vals):.2f})")
    print(f"{i * every:>4}  " + "  ".join(row))
```

```text
步数   训练集        干净验证        近亲验证      （3 个种子的平均，括号里是最小～最大）
   0  8.83 (8.78～8.89)  8.84 (8.79～8.88)  8.83 (8.78～8.89)
  40  5.67 (5.57～5.75)  6.74 (6.73～6.75)  6.01 (5.93～6.06)
  80  4.23 (4.07～4.36)  6.94 (6.89～6.97)  4.99 (4.87～5.06)
 120  2.95 (2.82～3.06)  7.31 (7.25～7.36)  4.11 (4.02～4.18)
 160  1.95 (1.83～2.01)  7.73 (7.67～7.80)  3.39 (3.29～3.49)
 200  1.25 (1.16～1.30)  8.15 (8.09～8.21)  2.85 (2.77～2.91)
```

::: v-pre
统一语料的验证集里，近亲占多少？如果不把它们挑出来，报出来的验证损失会被拉低多少？（按首数的比例近似加权）
:::

<p class="nb-label">In [18]</p>

```python
share = len(hits) / len(val_all)                                     # 统一语料验证集里近亲所占的比例
print(f"近亲占验证集的 {share:.1%}（{len(hits)}/{len(val_all)} 首）")
for i in (2, 10):
    c = sum(curves[s]["干净验证"][i] for s in curves) / 3
    d = sum(curves[s]["近亲验证"][i] for s in curves) / 3
    print(f"第 {i * every:>3} 步：干净 {c:.2f} → 混在一起报出 {(1 - share) * c + share * d:.2f}（低了 {share * (c - d):.2f}）")
```

```text
近亲占验证集的 4.2%（36/852 首）
第  40 步：干净 6.74 → 混在一起报出 6.71（低了 0.03）
第 200 步：干净 8.15 → 混在一起报出 7.92（低了 0.22）
```

::: v-pre
## 7. 从诗到 batch

回到第 12 章的基线数据（前 6000 首的训练集）。每首诗切成 token 之后有多长？
:::

<p class="nb-label">In [19]</p>

```python
lengths = [len(tokenizer.encode(t).ids) + 1 for t in train_poems]      # +1 是 <eos>
print("每首诗的 token 数（含 <eos>）：最短", min(lengths), "最长", max(lengths), "平均", round(sum(lengths) / len(lengths), 1))
print("绝句（24 字）平均", round(sum(l for l, t in zip(lengths, train_poems) if len(t) == 24) / sum(len(t) == 24 for t in train_poems), 1),
      "个 token；律诗（48 字）平均", round(sum(l for l, t in zip(lengths, train_poems) if len(t) == 48) / sum(len(t) == 48 for t in train_poems), 1))
```

```text
每首诗的 token 数（含 <eos>）：最短 17 最长 60 平均 41.5
绝句（24 字）平均 23.6 个 token；律诗（48 字）平均 46.2
```

::: v-pre
三种组 batch 的办法，各浪费多少位置？

1. **逐首补齐**：一个 batch 32 首诗，按最长那首补 `<pad>`；
2. **按长度分桶**：先按长度排序再 32 首一组（组的顺序再打乱），同一组里长度接近；
3. **拼接成流**（第 12 章的做法）：所有诗首尾相接，切成等长窗口，没有空位。
:::

<p class="nb-label">In [20]</p>

```python
def pad_waste(batches):
    used = sum(sum(b) for b in batches)
    total = sum(max(b) * len(b) for b in batches)
    return 1 - used / total

order = list(range(len(lengths)))
random.Random(0).shuffle(order)
random_batches = [[lengths[i] for i in order[k:k + 32]] for k in range(0, len(order), 32)]
by_length = sorted(range(len(lengths)), key=lambda i: lengths[i])
bucket_batches = [[lengths[i] for i in by_length[k:k + 32]] for k in range(0, len(by_length), 32)]
print(f"逐首补齐：{pad_waste(random_batches):.1%} 的位置是 <pad>")
print(f"按长度分桶：{pad_waste(bucket_batches):.1%}")
print(f"拼接成流：0.0%")
```

```text
逐首补齐：21.3% 的位置是 <pad>
按长度分桶：0.3%
拼接成流：0.0%
```

::: v-pre
拼接成流不浪费位置，代价是窗口会跨过诗的边界：`<eos>` 之后的 token，注意力还能看到上一首诗。
按第 12 章的 batch 计划数一数，有多少个预测位置的窗口里含有别的诗：
:::

<p class="nb-label">In [21]</p>

```python
train_ids = to_stream(train_poems)
plan = torch.Generator().manual_seed(1234)                           # 和第 12 章完全相同的 batch 计划
starts12 = torch.randint(0, len(train_ids) - cfg.context - 1, (300, 32), generator=plan)
windows = train_ids[starts12.flatten()[:, None] + torch.arange(cfg.context)]      # (9600, 64)
seen_eos = (windows == EOS).int().cumsum(dim=1)                       # 到这个位置为止见过几个 <eos>
crossed = (seen_eos[:, :-1] > 0).float().mean().item()
print(f"窗口里平均有 {(windows == EOS).sum(1).float().mean().item():.1f} 个 <eos>，"
      f"{crossed:.0%} 的位置在预测时能看到不属于当前这首诗的 token")
```

```text
窗口里平均有 1.5 个 <eos>，66% 的位置在预测时能看到不属于当前这首诗的 token
```

::: v-pre
想让每首诗只看自己，可以把因果掩码改成“块对角”的文档掩码。拿一个 10 个 token、含两首诗的小例子看看：
:::

<p class="nb-label">In [22]</p>

```python
def document_mask(ids, eos):
    """True = 可以看。因果，并且只看同一首诗（<eos> 算作它所结束的那首）。"""
    doc = torch.cat([torch.zeros(1, dtype=torch.long), (ids == eos).long().cumsum(0)[:-1]])
    causal = torch.ones(len(ids), len(ids), dtype=torch.bool).tril()
    return causal & (doc[:, None] == doc[None, :])

toy = torch.tensor([11, 12, 13, EOS, 21, 22, 23, 24, 25, EOS])
for row in document_mask(toy, EOS).int().tolist():
    print(" ".join("■" if v else "·" for v in row))
```

```text
■ · · · · · · · · ·
■ ■ · · · · · · · ·
■ ■ ■ · · · · · · ·
■ ■ ■ ■ · · · · · ·
· · · · ■ · · · · ·
· · · · ■ ■ · · · ·
· · · · ■ ■ ■ · · ·
· · · · ■ ■ ■ ■ · ·
· · · · ■ ■ ■ ■ ■ ·
· · · · ■ ■ ■ ■ ■ ■
```

::: v-pre
## 8. 采样与覆盖

第 12 章每步随机选 32 个起点，300 步一共 9600 个窗口。训练流里的每个 token，被当作预测目标多少次？
:::

<p class="nb-label">In [23]</p>

```python
def coverage(starts, n, T=cfg.context):
    """每个位置被当作目标（窗口里第 1～T 个预测位置）的次数。"""
    hits = torch.zeros(n + 1, dtype=torch.long)
    s = starts.flatten() + 1
    hits.index_add_(0, s, torch.ones_like(s))
    hits.index_add_(0, s + T, -torch.ones_like(s))
    return hits.cumsum(0)[:n]

n = len(train_ids)
random_cov = coverage(starts12, n)
epochs = starts12.numel() * cfg.context / n
plan = torch.Generator().manual_seed(1234)
per_epoch = (n - 1) // cfg.context
epoch_starts = torch.cat([torch.randperm(per_epoch, generator=plan) * cfg.context
                          for _ in range(math.ceil(starts12.numel() / per_epoch))])[:starts12.numel()]
epoch_cov = coverage(epoch_starts, n)
print(f"9600 个窗口 × 64 = 训练流的 {epochs:.2f} 遍")
for name, cov in [("随机起点（第 12 章）", random_cov), ("按轮打乱", epoch_cov)]:
    c = Counter(min(int(v), 5) for v in cov[1:].tolist())
    print(f"{name:<12}" + "  ".join(f"{k if k < 5 else '≥5'} 次 {c[k] / (n - 1):5.1%}" for k in range(6)))
print(f"随机起点下，从没被当作目标的比例约 {(random_cov[1:] == 0).float().mean().item():.1%}，"
      f"泊松近似 e^-{epochs:.2f} = {math.exp(-epochs):.1%}")
```

```text
9600 个窗口 × 64 = 训练流的 2.73 遍
随机起点（第 12 章）0 次  6.7%  1 次 17.7%  2 次 24.2%  3 次 22.0%  4 次 15.2%  ≥5 次 14.2%
按轮打乱        0 次  0.0%  1 次  0.0%  2 次 26.9%  3 次 73.1%  4 次  0.0%  ≥5 次  0.0%
随机起点下，从没被当作目标的比例约 6.7%，泊松近似 e^-2.73 = 6.5%
```

::: v-pre
## 9. 喂数据要多快

训练一步要多久，准备一个 batch 又要多久？三件事分别计时：从预先分好词的流里切 batch、每步临时分词再切、
用第 12 章的完整模型训练一步。
:::

<p class="nb-label">In [24]</p>

```python
def timed(fn, repeat):
    fn()
    t0 = time.perf_counter()
    for _ in range(repeat):
        fn()
    return (time.perf_counter() - t0) / repeat

def batch_from_stream():
    s = torch.randint(0, len(train_ids) - cfg.context - 1, (32,))
    idx = s[:, None] + torch.arange(cfg.context + 1)
    return train_ids[idx[:, :-1]], train_ids[idx[:, 1:]]

def batch_from_text():
    picks = random.sample(train_poems, 64)                            # 64 首诗大约够切 32 个窗口
    ids = torch.tensor([i for e in tokenizer.encode_batch(picks) for i in e.ids + [EOS]])
    s = torch.randint(0, len(ids) - cfg.context - 1, (32,))
    idx = s[:, None] + torch.arange(cfg.context + 1)
    return ids[idx[:, :-1]], ids[idx[:, 1:]]

torch.manual_seed(0)
model = TinyLLM(cfg)
optimizer = torch.optim.AdamW(model.parameters(), lr=3e-3)
def train_step():
    xb, yb = batch_from_stream()
    _, loss = model(xb, yb)
    optimizer.zero_grad(set_to_none=True)
    loss.backward()
    optimizer.step()

t_stream, t_text, t_step = timed(batch_from_stream, 200), timed(batch_from_text, 50), timed(train_step, 5)
print(f"从 token 流切一个 batch：{t_stream * 1e3:.2f} 毫秒")
print(f"临时分词再切：        {t_text * 1e3:.2f} 毫秒")
print(f"训练一步（CPU）：     {t_step * 1e3:.0f} 毫秒")
```

```text
从 token 流切一个 batch：0.04 毫秒
临时分词再切：        1.71 毫秒
训练一步（CPU）：     332 毫秒
```

::: v-pre
## 10. 混合多个来源

第 13 章的大语料有两个来源：《全唐诗》50,286 首、《全宋诗》246,373 首（见 manifest-large.json）。
按什么比例抽样？假设总共训练相当于“全部诗过一遍”的量：
:::

<p class="nb-label">In [25]</p>

```python
sizes = {"全唐诗": 50_286, "全宋诗": 246_373}
budget = sum(sizes.values())
def mix(weights):
    total = sum(weights.values())
    return {k: (weights[k] / total, budget * weights[k] / total / sizes[k]) for k in sizes}

for name, weights in [("按自然比例", sizes), ("两边各一半", {k: 1 for k in sizes}),
                      ("温度采样 α=0.5", {k: v ** 0.5 for k, v in sizes.items()})]:
    print(f"{name:<12}" + "   ".join(f"{k} 占 {p:5.1%}、相当于过 {e:.2f} 遍" for k, (p, e) in mix(weights).items()))
```

```text
按自然比例       全唐诗 占 17.0%、相当于过 1.00 遍   全宋诗 占 83.0%、相当于过 1.00 遍
两边各一半       全唐诗 占 50.0%、相当于过 2.95 遍   全宋诗 占 50.0%、相当于过 0.60 遍
温度采样 α=0.5  全唐诗 占 31.1%、相当于过 1.84 遍   全宋诗 占 68.9%、相当于过 0.83 遍
```

<p class="nb-label">In [26]</p>

```python
data_log = {
    "funnel": [(name, len(rows)) for name, rows in stages]
              + [("繁转简后精确去重", len(unique)), ("近重复去重", len(kept))],
    "dedup": {"exact_trad": dup_trad, "exact_simp": dup_simp, "near": len(removed)},
    "split": Counter(split_of(t) for t in kept),
    "best_scores": best_scores, "val_scores": val_scores, "leak_hits": len(hits), "val_total": len(val),
    "leak_curves": {str(s): c for s, c in curves.items()}, "leak_every": every,
    "leak_tokens": {k: v.numel() for k, v in sets.items()},
    "lengths": lengths,
    "padding": {"random": pad_waste(random_batches), "bucket": pad_waste(bucket_batches)},
    "coverage": {"random": Counter(min(int(v), 6) for v in random_cov[1:].tolist()),
                 "epoch": Counter(min(int(v), 6) for v in epoch_cov[1:].tolist()), "epochs": epochs},
}
with open("data_pipeline_log.json", "w", encoding="utf-8") as f:
    json.dump(data_log, f, ensure_ascii=False)
```

