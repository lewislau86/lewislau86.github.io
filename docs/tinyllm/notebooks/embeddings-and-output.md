---
title: "第 7 章：词嵌入与输出层（notebook 在线查看）"
search: false
editLink: false
prev: false
next: false
pageClass: tinyllm-course
---

<!-- 本页由 scripts/build-tinyllm-code.py 根据 notebook 自动生成，请勿手改。 -->

::: tip 这是 notebook 的只读预览
[返回教案](/tinyllm/embeddings-and-output) · [在 Colab 中运行](https://colab.research.google.com/github/lewislau86/lewislau86.github.io/blob/master/docs/public/tinyllm/notebooks/embeddings-and-output.ipynb) · <a href="/tinyllm/notebooks/embeddings-and-output.ipynb" download>下载 .ipynb</a> · [在 GitHub 上查看](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/tinyllm/notebooks/embeddings-and-output.ipynb)

下面的代码和输出与 notebook 文件完全一致。想修改、运行，请用 Colab 打开或下载到本地。
:::

::: v-pre
# 第 7 章：词嵌入与输出层

按顺序运行。固定六项词表、固定随机种子，CPU 即可复现；没有下载和训练完整模型。
:::

::: v-pre
## 1. 从 token ID 查表

先猜 `ids`、权重和输出各有几维。
:::

<p class="nb-label">In [1]</p>

```python
import torch
from torch import nn
import torch.nn.functional as F

torch.manual_seed(7)
vocab = ["<pad>", "<eos>", "我", "在", "学习", "数学"]
ids = torch.tensor([[2, 3, 4], [2, 3, 5]], dtype=torch.long)
embedding = nn.Embedding(len(vocab), 4)
vectors = embedding(ids)
print("ID:", ids.shape, "词表:", embedding.weight.shape, "向量:", vectors.shape)
assert vectors.shape == (2, 3, 4)
assert torch.equal(vectors[0, 0], vectors[1, 0])
```

```text
ID: torch.Size([2, 3]) 词表: torch.Size([6, 4]) 向量: torch.Size([2, 3, 4])
```

::: v-pre
相同 ID 刚查表时得到相同向量。此时还没有位置表示或上下文计算。
:::

<p class="nb-label">In [2]</p>

```python
one_hot = F.one_hot(ids, num_classes=len(vocab)).float()
assert torch.allclose(one_hot @ embedding.weight, vectors)
print("one-hot × 参数表 = 查表:", True)
```

```text
one-hot × 参数表 = 查表: True
```

::: v-pre
## 2. 从词嵌入到 Q/K/V

这个一头、四维的教学实验用加法位置向量。真实模型也可能把 RoPE 施加在 Q/K 上。三组投影是不同参数；Q/K 的点积选择当前上下文中的位置，V 提供被加权的内容。
:::

<p class="nb-label">In [3]</p>

```python
import math
position = nn.Embedding(3, 4)
x = vectors[0] + position(torch.arange(3))
q_proj, k_proj, v_proj = (nn.Linear(4, 4, bias=False) for _ in range(3))
q, k, v = q_proj(x), k_proj(x), v_proj(x)
scores = q @ k.T / math.sqrt(4)
future = torch.triu(torch.ones(3, 3, dtype=torch.bool), diagonal=1)
weights = scores.masked_fill(future, float("-inf")).softmax(dim=-1)
context = weights @ v
print("嵌入/位置后:", x.shape, "Q/K/V:", q.shape, k.shape, v.shape)
print("注意力权重:\n", weights)
assert context.shape == (3, 4)
assert torch.allclose(weights[0, 1:], torch.zeros(2))
```

```text
嵌入/位置后: torch.Size([3, 4]) Q/K/V: torch.Size([3, 4]) torch.Size([3, 4]) torch.Size([3, 4])
注意力权重:
 tensor([[1.0000, 0.0000, 0.0000],
        [0.4860, 0.5140, 0.0000],
        [0.4708, 0.3611, 0.1681]], grad_fn=<SoftmaxBackward0>)
```

::: v-pre
## 3. KV cache 是计算复用

逐步生成时保留旧 K/V；每个新位置重新计算 Q 与所有 K 的分数。下面比较一次性因果注意力和逐步缓存的结果。
:::

<p class="nb-label">In [4]</p>

```python
cached_k, cached_v, incremental = [], [], []
for t in range(len(x)):
    q_t = q_proj(x[t:t+1])
    cached_k.append(k_proj(x[t:t+1]))
    cached_v.append(v_proj(x[t:t+1]))
    all_k, all_v = torch.cat(cached_k), torch.cat(cached_v)
    attention_t = (q_t @ all_k.T / math.sqrt(4)).softmax(dim=-1)
    incremental.append(attention_t @ all_v)
assert torch.allclose(torch.cat(incremental), context, atol=1e-6)
print("全量与逐步 KV 复用最大误差:", (torch.cat(incremental)-context).abs().max().item())
print("缓存位置数:", len(cached_k), "；缓存的是 K/V，不是注意力分数")
```

```text
全量与逐步 KV 复用最大误差: 5.960464477539063e-08
缓存位置数: 3 ；缓存的是 K/V，不是注意力分数
```

::: v-pre
同一个词元的静态查表向量、当前层的 K、检索模型的整段文本向量分别有不同用途。缓存中的 K/V 依赖层、位置与本次前缀，不能当作跨会话语义索引。
:::

::: v-pre
## 4. 把向量投影回词表

这里用查表结果暂代 Transformer 的隐藏状态，只验证输出端的张量形状。
:::

<p class="nb-label">In [5]</p>

```python
output = nn.Linear(4, len(vocab), bias=True)
logits = output(vectors)
probs = logits.softmax(dim=-1)
print("输出权重:", output.weight.shape, "logits:", logits.shape)
print("第一位置六个候选概率:", probs[0, 0].tolist())
assert logits.shape == (2, 3, 6)
assert torch.allclose(probs.sum(-1), torch.ones(2, 3))
```

```text
输出权重: torch.Size([6, 4]) logits: torch.Size([2, 3, 6])
第一位置六个候选概率: [0.057196181267499924, 0.36962994933128357, 0.17588721215724945, 0.09651432931423187, 0.07434379309415817, 0.2264285385608673]
```

::: v-pre
## 5. 下一 token 损失与梯度

`我 在 学习 <eos>` 的输入是前三项，目标是后三项。交叉熵直接接收 logits。
:::

<p class="nb-label">In [6]</p>

```python
input_ids = torch.tensor([[2, 3, 4]])
target_ids = torch.tensor([[3, 4, 1]])
embedding.zero_grad()
output.zero_grad()
model_logits = output(embedding(input_ids))
loss = F.cross_entropy(model_logits.reshape(-1, len(vocab)), target_ids.reshape(-1))
loss.backward()
print("loss:", round(loss.item(), 4))
print("输入嵌入各行梯度范数:", embedding.weight.grad.norm(dim=1).tolist())
print("输出权重各行梯度范数:", output.weight.grad.norm(dim=1).tolist())
assert torch.count_nonzero(embedding.weight.grad[[0, 1, 5]]) == 0
assert torch.count_nonzero(output.weight.grad[5]) > 0
```

```text
loss: 1.7919
输入嵌入各行梯度范数: [0.0, 0.0, 0.19234707951545715, 0.15704676508903503, 0.11473093181848526, 0.0]
输出权重各行梯度范数: [0.10596393793821335, 0.4110339283943176, 0.205150306224823, 0.5842531323432922, 0.4550133943557739, 0.2615610659122467]
```

::: v-pre
反向传播只写入梯度。现在用 SGD 真正更新两张表，并比较同一批数据的损失。
:::

<p class="nb-label">In [7]</p>

```python
optimizer = torch.optim.SGD(list(embedding.parameters()) + list(output.parameters()), lr=0.1)
before = loss.item()
optimizer.step()
after_logits = output(embedding(input_ids))
after = F.cross_entropy(after_logits.reshape(-1, len(vocab)), target_ids.reshape(-1)).item()
print("更新前/后:", round(before, 4), round(after, 4))
assert after < before
```

```text
更新前/后: 1.7919 1.6911
```

::: v-pre
未作为输入的 ID 1、5 在未共享输入表中没有梯度；输出层仍为所有候选打分。`<pad>` 行在这里也没作为输入出现。
:::

::: v-pre
## 6. 权重共享

共享指同一个 `Parameter` 对象，不是两张表初始化成同样数字。
:::

<p class="nb-label">In [8]</p>

```python
tied_embedding = nn.Embedding(len(vocab), 4)
tied_output = nn.Linear(4, len(vocab), bias=False)
tied_output.weight = tied_embedding.weight
assert tied_output.weight is tied_embedding.weight
assert tied_output.weight.data_ptr() == tied_embedding.weight.data_ptr()
hidden = tied_embedding(input_ids)
assert torch.allclose(tied_output(hidden), F.linear(hidden, tied_embedding.weight))
print("未共享两端参数（含输出偏置）:", embedding.weight.numel() + sum(p.numel() for p in output.parameters()))
print("共享两端唯一参数:", len({id(p) for p in list(tied_embedding.parameters()) + list(tied_output.parameters())}))
print("共享权重元素数:", tied_embedding.weight.numel())
```

```text
未共享两端参数（含输出偏置）: 54
共享两端唯一参数: 1
共享权重元素数: 24
```

<p class="nb-label">In [9]</p>

```python
tied_embedding.zero_grad()
tied_logits = tied_output(tied_embedding(input_ids))
tied_loss = F.cross_entropy(tied_logits.reshape(-1, len(vocab)), target_ids.reshape(-1))
tied_loss.backward()
print("共享表各行梯度范数:", tied_embedding.weight.grad.norm(dim=1).tolist())
assert torch.count_nonzero(tied_embedding.weight.grad[5]) > 0
```

```text
共享表各行梯度范数: [0.00844821147620678, 0.447761207818985, 0.39632025361061096, 0.11909018456935883, 0.620768666267395, 0.0025366025511175394]
```

::: v-pre
ID 5 没出现在输入中，却能从输出分类路径得到梯度。共享后的输入与输出梯度汇入同一张表。
:::

::: v-pre
## Agent 检索向量的边界

真实文本 embedding 模型把整段文本编码成可跨请求比较的向量，常有池化与检索训练目标。下面仅用手工词项特征示意接口；它不是 Hugging Face 模型，也不代表语义检索质量。Hugging Face 多语言 MiniLM、E5、BGE-M3 的模型卡与调用方式见教案。
:::

<p class="nb-label">In [10]</p>

```python
keywords = ["Plotly", "PyTorch", "图表"]
def retrieval_vector(text):
    return torch.tensor([float(word in text) for word in keywords])
memories = ["图表统一使用 Plotly", "模型使用 PyTorch"]
query = "图表用什么"
q = retrieval_vector(query)
scored = [(F.cosine_similarity(q, retrieval_vector(m), dim=0).item(), m) for m in memories]
print(sorted(scored, reverse=True))
assert max(scored)[1] == memories[0]
```

```text
[(0.7071067690849304, '图表统一使用 Plotly'), (0.0, '模型使用 PyTorch')]
```

::: v-pre
检索向量用于找回原文。原文再经过 tokenizer、词嵌入和 Q/K/V；它不会直接塞进 `nn.Embedding`。真实记忆还需处理时间、来源、更新与删除，见 第 27 章。
:::

::: v-pre
## 检查

1. 把 `ids` 改成形状 `[2, 5]`，两端的形状各是什么？
2. 为什么未共享输入表第 5 行没有梯度，共享后却有？
3. 把词表 ID 重新排序但不调整权重，会发生什么？
4. 哪个实验尚未证明模型具有语言能力？
:::

