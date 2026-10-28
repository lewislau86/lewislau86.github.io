---
title: "第 4 章：词嵌入与输出层（notebook 在线查看）"
search: false
editLink: false
prev: false
next: false
pageClass: tinyllm-course
---

<!-- 本页由 scripts/build-tinyllm-code.py 根据 notebook 自动生成，请勿手改。 -->

::: tip 这是 notebook 的只读预览
[返回教案](/tinyllm/embeddings-and-output) · [在 Colab 中运行](https://colab.research.google.com/github/lewislau86/lewislau86.github.io/blob/master/docs/public/tinyllm/notebooks/embeddings-and-output.ipynb) · <a href="/tinyllm/notebooks/embeddings-and-output.ipynb" download>下载 .ipynb</a> · <a href="/tinyllm/code/embeddings-and-output.py" download>下载 .py</a> · [在 GitHub 上查看](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/tinyllm/notebooks/embeddings-and-output.ipynb)

下面的代码和输出与 notebook 文件完全一致。想修改、运行，请用 Colab 打开或下载到本地。
:::

::: v-pre
# 第 4 章：词嵌入与输出层

配套教案：https://lewislau86.github.io/tinyllm/embeddings-and-output

从上到下运行即可（`python embeddings-and-output.py`），CPU 上几秒钟。只需要安装 PyTorch。
这个文件是本章代码的唯一来源：教案中的代码片段由 `# region 名字` / `# endregion 名字`
标记的区域直接引用，notebook 也由它生成（scripts/build-tinyllm-code.py）。
固定六项词表、固定随机种子；没有下载和训练完整模型，数字只为看清机制。
:::

::: v-pre
## 1. 从 token ID 查表

先猜 `ids`、权重和输出各有几维。
:::

<p class="nb-label">In [1]</p>

```python
import torch
from torch import nn

torch.manual_seed(7)
vocab = ["<pad>", "<eos>", "我", "在", "学习", "数学"]
ids = torch.tensor([[2, 3, 4], [2, 3, 5]], dtype=torch.long)
embedding = nn.Embedding(num_embeddings=len(vocab), embedding_dim=4)
vectors = embedding(ids)

assert embedding.weight.shape == (6, 4)
assert vectors.shape == (2, 3, 4)
assert torch.equal(vectors[0, 0], embedding.weight[2])
assert torch.equal(vectors[0, 0], vectors[1, 0])
print("ID:", ids.shape, "词表:", embedding.weight.shape, "向量:", vectors.shape)
```

```text
ID: torch.Size([2, 3]) 词表: torch.Size([6, 4]) 向量: torch.Size([2, 3, 4])
```

::: v-pre
相同 ID 刚查表时得到相同向量。此时还没有位置表示或上下文计算。
查表也可以写成 one-hot 向量乘参数表，两者数值相同。
:::

<p class="nb-label">In [2]</p>

```python
one_hot = torch.nn.functional.one_hot(ids, num_classes=len(vocab)).float()
assert torch.allclose(one_hot @ embedding.weight, vectors)
print("one-hot × 参数表 = 查表:", True)
```

```text
one-hot × 参数表 = 查表: True
```

::: v-pre
## 2. 把向量投影回词表

这里用查表结果暂代 Transformer 的隐藏状态，只验证输出端的张量形状。
:::

<p class="nb-label">In [3]</p>

```python
output = nn.Linear(4, len(vocab), bias=True)
logits = output(vectors)
probabilities = logits.softmax(dim=-1)

assert output.weight.shape == (6, 4)
assert logits.shape == (2, 3, 6)
assert torch.allclose(probabilities.sum(dim=-1), torch.ones(2, 3))
print("输出权重:", output.weight.shape, "logits:", logits.shape)
print("第一位置六个候选概率:", probabilities[0, 0].tolist())
```

```text
输出权重: torch.Size([6, 4]) logits: torch.Size([2, 3, 6])
第一位置六个候选概率: [0.22834962606430054, 0.07945547997951508, 0.25815266370773315, 0.07703278213739395, 0.25543317198753357, 0.10157634317874908]
```

::: v-pre
## 3. 下一 token 损失与梯度

`我 在 学习 <eos>` 的输入是前三项，目标是后三项。交叉熵直接接收 logits。
:::

<p class="nb-label">In [4]</p>

```python
import torch.nn.functional as F

input_ids = torch.tensor([[2, 3, 4]])
target_ids = torch.tensor([[3, 4, 1]])
model_input = embedding(input_ids)
model_logits = output(model_input)  # 此处还没有 Transformer，只演示两端
loss = F.cross_entropy(model_logits.reshape(-1, len(vocab)), target_ids.reshape(-1))

embedding.zero_grad()
output.zero_grad()
loss.backward()
assert embedding.weight.grad is not None
assert output.weight.grad is not None
print("loss:", round(loss.item(), 4))
```

```text
loss: 2.0682
```

::: v-pre
逐行看两边的梯度范数：输入表只有作为输入出现过的行（2、3、4）非零，输出层的每一行都有梯度。
:::

<p class="nb-label">In [5]</p>

```python
print("输入嵌入各行梯度范数:", embedding.weight.grad.norm(dim=1).tolist())
print("输出权重各行梯度范数:", output.weight.grad.norm(dim=1).tolist())
assert torch.count_nonzero(embedding.weight.grad[[0, 1, 5]]) == 0
assert torch.count_nonzero(output.weight.grad[5]) > 0
```

```text
输入嵌入各行梯度范数: [0.0, 0.0, 0.17230860888957977, 0.17935223877429962, 0.1277640014886856, 0.0]
输出权重各行梯度范数: [0.331432580947876, 0.6191422343254089, 0.3923816382884979, 0.5850269794464111, 0.38869521021842957, 0.26645326614379883]
```

::: v-pre
反向传播只写入梯度。现在用 SGD 真正更新两张表，并比较同一批数据的损失。
:::

<p class="nb-label">In [6]</p>

```python
optimizer = torch.optim.SGD(list(embedding.parameters()) + list(output.parameters()), lr=0.1)
before = loss.item()
optimizer.step()
after_logits = output(embedding(input_ids))
after = F.cross_entropy(after_logits.reshape(-1, len(vocab)), target_ids.reshape(-1)).item()
assert after < before
print("更新前/后:", round(before, 4), round(after, 4))
```

```text
更新前/后: 2.0682 1.9201
```

::: v-pre
未作为输入的 ID 1、5 在未共享输入表中没有梯度；输出层仍为所有候选打分。`<pad>` 行在这里也没作为输入出现。
:::

::: v-pre
## 4. 权重共享

共享指同一个 `Parameter` 对象，不是两张表初始化成同样数字。
:::

<p class="nb-label">In [7]</p>

```python
tied_embedding = nn.Embedding(len(vocab), 4)
tied_output = nn.Linear(4, len(vocab), bias=False)
tied_output.weight = tied_embedding.weight  # 同一个 Parameter，不是复制数值

assert tied_output.weight is tied_embedding.weight
assert tied_output.weight.data_ptr() == tied_embedding.weight.data_ptr()
assert len({id(p) for p in list(tied_embedding.parameters()) +
            list(tied_output.parameters())}) == 1
hidden = tied_embedding(input_ids)
assert torch.allclose(tied_output(hidden), F.linear(hidden, tied_embedding.weight))
print("未共享两端参数（含输出偏置）:", embedding.weight.numel() + sum(p.numel() for p in output.parameters()))
print("共享权重元素数:", tied_embedding.weight.numel())
```

```text
未共享两端参数（含输出偏置）: 54
共享权重元素数: 24
```

<p class="nb-label">In [8]</p>

```python
tied_embedding.zero_grad()
tied_logits = tied_output(tied_embedding(input_ids))
tied_loss = F.cross_entropy(tied_logits.reshape(-1, len(vocab)), target_ids.reshape(-1))
tied_loss.backward()
print("共享表各行梯度范数:", tied_embedding.weight.grad.norm(dim=1).tolist())
assert torch.count_nonzero(tied_embedding.weight.grad[5]) > 0
```

```text
共享表各行梯度范数: [0.09091351181268692, 0.6183667182922363, 0.47734642028808594, 0.9597447514533997, 1.7288321256637573, 0.010493326932191849]
```

::: v-pre
ID 5 没出现在输入中，却能从输出分类路径得到梯度。共享后的输入与输出梯度汇入同一张表。
:::

::: v-pre
## 5. 从词嵌入到 Q/K/V

这个一头、四维的教学实验用加法位置向量。真实模型也可能把 RoPE 施加在 Q/K 上。三组投影是不同参数；Q/K 的点积选择当前上下文中的位置，V 提供被加权的内容。权重随机，注意力数值没有语义。
:::

<p class="nb-label">In [9]</p>

```python
import math

position = nn.Embedding(3, 4)
x = vectors[0] + position(torch.arange(3))  # [seq, d]，教学用绝对位置向量
q_proj, k_proj, v_proj = (nn.Linear(4, 4, bias=False) for _ in range(3))
q, k, v = q_proj(x), k_proj(x), v_proj(x)
scores = q @ k.T / math.sqrt(4)
future = torch.triu(torch.ones(3, 3, dtype=torch.bool), diagonal=1)
weights = scores.masked_fill(future, float("-inf")).softmax(dim=-1)
context = weights @ v
assert context.shape == (3, 4)
assert torch.allclose(weights[0, 1:], torch.zeros(2))
print("嵌入/位置后:", x.shape, "Q/K/V:", q.shape, k.shape, v.shape)
print("注意力权重:\n", weights)
```

```text
嵌入/位置后: torch.Size([3, 4]) Q/K/V: torch.Size([3, 4]) torch.Size([3, 4]) torch.Size([3, 4])
注意力权重:
 tensor([[1.0000, 0.0000, 0.0000],
        [0.4987, 0.5013, 0.0000],
        [0.2243, 0.2163, 0.5595]], grad_fn=<SoftmaxBackward0>)
```

::: v-pre
同一个词元的静态查表向量、当前层的 K、检索模型的整段文本向量分别有不同用途。缓存中的 K/V 依赖层、位置与本次前缀，不能当作跨会话语义索引。
:::

::: v-pre
## 7. Agent 检索向量的边界

真实文本 embedding 模型把整段文本编码成可跨请求比较的向量，常有池化与检索训练目标。下面仅用手工词项特征示意接口；它不是 Hugging Face 模型，也不代表语义检索质量。检索模型的用法见第 29 章。
:::

<p class="nb-label">In [10]</p>

```python
keywords = ["Plotly", "PyTorch", "图表"]
def retrieval_vector(text):
    return torch.tensor([float(word in text) for word in keywords])
memories = ["图表统一使用 Plotly", "模型使用 PyTorch"]
query = "图表用什么"
query_vector = retrieval_vector(query)
scored = [(F.cosine_similarity(query_vector, retrieval_vector(m), dim=0).item(), m) for m in memories]
print(sorted(scored, reverse=True))
assert max(scored)[1] == memories[0]
```

```text
[(0.7071067690849304, '图表统一使用 Plotly'), (0.0, '模型使用 PyTorch')]
```

::: v-pre
检索向量用于找回原文。原文再经过 tokenizer、词嵌入和 Q/K/V；它不会直接塞进 `nn.Embedding`。真实记忆还需处理时间、来源、更新与删除，见第 29 章。
:::

::: v-pre
## 检查

1. 把 `ids` 改成形状 `[2, 5]`，两端的形状各是什么？
2. 为什么未共享输入表第 5 行没有梯度，共享后却有？
3. 把词表 ID 重新排序但不调整权重，会发生什么？
4. 哪个实验尚未证明模型具有语言能力？
:::

