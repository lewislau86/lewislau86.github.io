---
title: "第 25 章：推理效率（已成文部分：KV cache）（notebook 在线查看）"
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
# 第 25 章：推理效率（已成文部分：KV cache）

配套教案：https://lewislau86.github.io/tinyllm/inference-efficiency

从上到下运行即可（`python inference-efficiency.py`），CPU 上不到一秒。只需要安装 PyTorch。
这个文件是本章代码的唯一来源：教案中的代码片段由 `# region 名字` / `# endregion 名字`
标记的区域直接引用，notebook 也由它生成（scripts/build-tinyllm-code.py）。
本章还在规划中，目前只有“KV cache 保存的是什么”一节；例子沿用第 5 章的六项教学词表。
:::

<p class="nb-label">In [1]</p>

```python
import math

import torch
from torch import nn
```

::: v-pre
## 1. 一次性算出三个位置的因果注意力

“我 在 学习”三个 token 查表、加上教学用的绝对位置向量，再做一头、四维的因果注意力。
权重随机，注意力数值没有语义，只用来对照“一次性计算”和“逐步缓存”是否一致。
:::

<p class="nb-label">In [2]</p>

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
print("注意力权重:\n", weights)
```

```text
context 形状: (3, 4)
注意力权重:
 tensor([[1.0000, 0.0000, 0.0000],
        [0.4860, 0.5140, 0.0000],
        [0.4708, 0.3611, 0.1681]], grad_fn=<SoftmaxBackward0>)
```

::: v-pre
## 2. KV cache：逐个位置生成，复用旧的 K/V

每来一个新位置，只算它自己的 Q、K、V，把 K、V 追加进缓存；新 Q 与缓存里所有 K 打分，再对所有 V 加权求和。
:::

<p class="nb-label">In [3]</p>

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
一次性计算与逐步缓存的最大误差: 8.940696716308594e-08
缓存了 3 个位置的 K 和 V；缓存的是 K/V，不是注意力分数
```

::: v-pre
## 3. 数一数：不缓存要重算多少个 K、V

逐个生成 12 个位置。不缓存时，每一步都把前面所有位置重新送进 `k_proj`、`v_proj`；
有 KV cache 时，每一步只算新来的那一个。数出每一步实际投影了几行，并核对两种做法输出一致。
:::

<p class="nb-label">In [4]</p>

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
```

```text
不缓存，每步重算的 K/V 行数: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12] 合计 78
KV cache，每步新算的 K/V 行数: [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1] 合计 12
```

::: v-pre
## 4. 保存计数（可选）

网站上的 KV cache 并排动画就是用这份记录播放的。
:::

<p class="nb-label">In [5]</p>

```python
import json
with open("kv_cache_counts.json", "w", encoding="utf-8") as f:
    json.dump({"tokens": list("春乃发生。随风潜入夜，润"), "no_cache": no_cache, "with_cache": with_cache}, f, ensure_ascii=False)
```

