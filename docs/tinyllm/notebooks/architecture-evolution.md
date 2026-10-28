---
title: "第 3 章：架构演进：从 Transformer 到 GPT 再到今天（notebook 在线查看）"
search: false
editLink: false
prev: false
next: false
pageClass: tinyllm-course
---

<!-- 本页由 scripts/build-tinyllm-code.py 根据 notebook 自动生成，请勿手改。 -->

::: tip 这是 notebook 的只读预览
[返回教案](/tinyllm/architecture-evolution) · [在 Colab 中运行](https://colab.research.google.com/github/lewislau86/lewislau86.github.io/blob/master/docs/public/tinyllm/notebooks/architecture-evolution.ipynb) · <a href="/tinyllm/notebooks/architecture-evolution.ipynb" download>下载 .ipynb</a> · <a href="/tinyllm/code/architecture-evolution.py" download>下载 .py</a> · [在 GitHub 上查看](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/tinyllm/notebooks/architecture-evolution.ipynb)

下面的代码和输出与 notebook 文件完全一致。想修改、运行，请用 Colab 打开或下载到本地。
:::

::: v-pre
# 第 3 章：架构演进：从 Transformer 到 GPT 再到今天

配套教案：https://lewislau86.github.io/tinyllm/architecture-evolution

从上到下运行即可（`python architecture-evolution.py`），CPU 上几秒钟。只需要安装 PyTorch。
这个文件是本章代码的唯一来源：教案中的代码片段由 `# region 名字` / `# endregion 名字`
标记的区域直接引用，notebook 也由它生成（scripts/build-tinyllm-code.py）。
本章不训练模型，只用很小的张量把三代架构最关键的区别算给你看。
:::

<p class="nb-label">In [1]</p>

```python
import json
import math

import torch
from torch import nn
from torch.nn import functional as F

torch.manual_seed(0)
print("PyTorch", torch.__version__)
```

```text
PyTorch 2.14.1+cpu
```

::: v-pre
## 1. 2017 年的 Transformer：三种注意力，三种“谁能看谁”

编码器里每个词能看整句原文；解码器里每个词只能看已经写出的译文；交叉注意力让译文的每个词去看原文。
:::

<p class="nb-label">In [2]</p>

```python
src = ["the", "book", "on", "the", "table"]          # 原文 5 个词
tgt = ["桌子", "上", "的", "书"]                       # 译文 4 个词

encoder_mask = torch.ones(len(src), len(src), dtype=torch.bool)               # 原文：谁都能看谁
decoder_mask = torch.tril(torch.ones(len(tgt), len(tgt), dtype=torch.bool))   # 译文：只能看前面
cross_mask = torch.ones(len(tgt), len(src), dtype=torch.bool)                 # 译文的每个词看整句原文

for name, m in [("编码器自注意力", encoder_mask), ("解码器自注意力", decoder_mask), ("交叉注意力", cross_mask)]:
    print(f"{name}: 形状 {tuple(m.shape)}，能看的位置 {int(m.sum())} / {m.numel()}")
print(decoder_mask.int())
```

```text
编码器自注意力: 形状 (5, 5)，能看的位置 25 / 25
解码器自注意力: 形状 (4, 4)，能看的位置 10 / 16
交叉注意力: 形状 (4, 5)，能看的位置 20 / 20
tensor([[1, 0, 0, 0],
        [1, 1, 0, 0],
        [1, 1, 1, 0],
        [1, 1, 1, 1]], dtype=torch.int32)
```

::: v-pre
## 2. GPT：去掉编码器，任何文本都能当训练数据

翻译模型要“原文 → 译文”成对的数据；GPT 只要一段普通文本，把它错开一位就是输入和答案。
:::

<p class="nb-label">In [3]</p>

```python
pair = ("the book on the table", "桌子上的书")          # 翻译：一条数据 = 一对句子，需要人工准备
text = "床前明月光，疑是地上霜。"                        # GPT：随便一段文字
x, y = text[:-1], text[1:]                               # 输入和答案只差一位
for i in range(4):
    print(f"看到 “{x[: i + 1]}” → 预测 “{y[i]}”")
print(f"这一句 {len(text)} 个字，自动得到 {len(x)} 道“预测下一个字”的练习题")
```

```text
看到 “床” → 预测 “前”
看到 “床前” → 预测 “明”
看到 “床前明” → 预测 “月”
看到 “床前明月” → 预测 “光”
这一句 12 个字，自动得到 11 道“预测下一个字”的练习题
```

::: v-pre
## 3. 完整注意力的代价：KV cache 随上下文线性增长

生成时，完整注意力要把前面每个 token 的 K、V 都留着（第 25 章的 KV cache）。
下面按一个 32 层、每层 8 个 KV 头、每头 128 维、BF16 的模型估算缓存大小。
:::

<p class="nb-label">In [4]</p>

```python
layers, kv_heads, head_dim, bytes_per = 32, 8, 128, 2

def kv_cache_gb(T, full_layers=layers):
    return 2 * full_layers * kv_heads * head_dim * T * bytes_per / 1e9   # 2 = K 和 V

def linear_state_gb(linear_layers):
    return linear_layers * kv_heads * head_dim * head_dim * bytes_per / 1e9  # 每层一个 d×d 的状态，与 T 无关

lengths = [4_096, 32_768, 131_072, 1_048_576]
cost = {"T": lengths, "full": [], "hybrid": []}
for T in lengths:
    full = kv_cache_gb(T)
    hybrid = kv_cache_gb(T, full_layers=layers // 4) + linear_state_gb(layers - layers // 4)   # 3 层线性 + 1 层完整
    cost["full"].append(full)
    cost["hybrid"].append(hybrid)
    print(f"上下文 {T:>9,}：全部完整注意力 {full:7.2f} GB    3:1 混合 {hybrid:7.2f} GB")
```

```text
上下文     4,096：全部完整注意力    0.54 GB    3:1 混合    0.14 GB
上下文    32,768：全部完整注意力    4.29 GB    3:1 混合    1.08 GB
上下文   131,072：全部完整注意力   17.18 GB    3:1 混合    4.30 GB
上下文 1,048,576：全部完整注意力  137.44 GB    3:1 混合   34.37 GB
```

::: v-pre
## 4. 线性注意力：把前文压成一个固定大小的状态

最朴素的线性注意力去掉 softmax，用 φ(q)·φ(k) 代替 exp(q·k)。这样可以边读边把 φ(k)ᵀv 累加进一个 d×d 的状态，
每读一个 token 只做一次更新，不再需要保留全部 K、V。下面验证“逐个累加”和“一次性算整张表”结果相同。
（Kimi K3 用的 KDA 在此基础上加了按通道的遗忘门和 delta 更新规则，思路相同：状态大小固定。）
:::

<p class="nb-label">In [5]</p>

```python
T, d = 6, 4
q, k, v = torch.randn(T, d), torch.randn(T, d), torch.randn(T, d)
phi = lambda t: F.elu(t) + 1                            # 让特征为正，充当“相似度”

# 写法一：像普通注意力一样算整张 T×T 的表（只看自己和前面）
scores = (phi(q) @ phi(k).T).tril()
out_table = (scores @ v) / scores.sum(-1, keepdim=True)

# 写法二：从左往右读，只保留一个 d×d 的状态 S 和一个长度 d 的归一化向量 z
S, z, out_stream = torch.zeros(d, d), torch.zeros(d), []
for t in range(T):
    S = S + phi(k[t])[:, None] * v[t][None, :]          # 把这个 token 的信息“写”进状态
    z = z + phi(k[t])
    out_stream.append((phi(q[t]) @ S) / (phi(q[t]) @ z))
out_stream = torch.stack(out_stream)

print("两种写法最大差异:", (out_table - out_stream).abs().max().item())
print("状态 S 的形状:", tuple(S.shape), "—— 读了", T, "个 token，读 100 万个也还是这么大")
assert torch.allclose(out_table, out_stream, atol=1e-5)
```

```text
两种写法最大差异: 5.960464477539063e-08
状态 S 的形状: (4, 4) —— 读了 6 个 token，读 100 万个也还是这么大
```

::: v-pre
## 5. MoE：参数很多，每个 token 只用一小部分

把一个大前馈层换成很多个小“专家”，路由器给每个 token 挑几个。先用一个玩具层数一数，再看 Kimi K3 的公开数字。
:::

<p class="nb-label">In [6]</p>

```python
d, hidden, n_experts, top_k = 64, 128, 8, 2
experts = nn.ModuleList(nn.Sequential(nn.Linear(d, hidden), nn.SiLU(), nn.Linear(hidden, d)) for _ in range(n_experts))
router = nn.Linear(d, n_experts, bias=False)

x = torch.randn(5, d)                                   # 5 个 token
weights, chosen = router(x).softmax(-1).topk(top_k, dim=-1)
print("每个 token 选中的专家:", chosen.tolist())

per_expert = sum(p.numel() for p in experts[0].parameters())
total = per_expert * n_experts + router.weight.numel()
active = per_expert * top_k + router.weight.numel()
print(f"玩具 MoE：总参数 {total:,}，每个 token 用到 {active:,}（{active / total:.0%}）")
print(f"Kimi K3：总参数 2.8 万亿，每个 token 用到 1040 亿（{104 / 2800:.1%}）")
```

```text
每个 token 选中的专家: [[6, 5], [4, 3], [2, 3], [2, 3], [3, 2]]
玩具 MoE：总参数 133,120，每个 token 用到 33,664（25%）
Kimi K3：总参数 2.8 万亿，每个 token 用到 1040 亿（3.7%）
```

::: v-pre
## 6. 保存记录（可选）

网站上的“缓存大小随上下文增长”图就是用这份记录画的。
:::

<p class="nb-label">In [7]</p>

```python
with open("architecture_cost.json", "w", encoding="utf-8") as f:
    json.dump({"config": {"layers": layers, "kv_heads": kv_heads, "head_dim": head_dim, "bytes": bytes_per}, **cost}, f)
```

