---
title: "第 7 章：词嵌入与输出层"
description: "token ID 怎样查表变成向量，向量怎样变回词表上的分数；Q/K/V 与 KV cache 从哪里来；为什么输入输出可以共用一张表。"
pageClass: tinyllm-course
---

# 第 7 章：词嵌入与输出层

[课程总览](./index.md) · [上一章](./tokenization.md) · [下一章](./position-encoding.md)

::: tip 本章学习目标
说清 `[batch, seq] → [batch, seq, d] → [batch, seq, V]` 的形状变化；解释 logits、交叉熵梯度与权重共享；说出 KV cache 复用了什么、每步重算什么；区分模型内部的词嵌入与检索用的文本向量。

**前置：** [第 6 章](./tokenization.md)的 token ID；[第 2 章](./tensors-and-autograd.md)的矩阵乘法与梯度。

**实践方式：** [embeddings-and-output.ipynb](/tinyllm/notebooks/embeddings-and-output)，固定的六项教学词表和 PyTorch，CPU 即可，不下载模型或语料。先猜形状和结果，再运行每一格核对；这里的数字只为看清机制，不代表训练好的语言能力。
:::

[上一章](./tokenization.md)把文本变成了 token ID。假设“我 在 学习”被编码成 `[2, 3, 4]`：2、3、4 是词表的行号，它们之间的大小毫无语言含义。模型要用它们做计算，两端各缺一步：<strong>输入端</strong>要把 ID 变成向量，<strong>输出端</strong>要把向量变回“下一个 token 是谁”的分数。本章沿着这一次往返，把两端接起来，再顺带看看向量进入注意力之后变成了什么。

<TinyLLMMap active="embeddings-and-output" />

## 1. 一个 ID 怎样变成一个向量

设词表大小为 $V$，隐藏维数为 $d$。输入嵌入表 $E$ 是形状为 $[V,d]$ 的<strong>可训练参数</strong>，ID $i$ 对应第 $i$ 行 $E_i$。先猜：一批形状为 `[2, 3]` 的 ID 查表后是什么形状？

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
```

![六项词表的嵌入表 E 形状为 [6,4]；ID 序列 [2,3,4] 分别取出第 2、3、4 行，拼成形状为 [3,4] 的向量序列](/tinyllm/figures/embedding-lookup.svg)

图左边是整张嵌入表，每一行属于一个词表条目；右边是查表结果。ID 2、3、4 就是三个行号，`nn.Embedding` 按行号把这三行原样取出、按输入顺序排好，于是 `[3]` 个 ID 变成 `[3, 4]` 的向量。整批输入 `[batch, seq]` 也是同样的逐个取行，结果是 `[batch, seq, d]`。[PyTorch `nn.Embedding`](https://docs.pytorch.org/docs/stable/generated/torch.nn.Embedding.html) 做的正是这种按索引取行的操作。

两条样本都以“我”开头，所以它们取到同一行向量。这里的“相同”仅限<strong>查表刚结束时</strong>：嵌入表只认 ID，不知道“我”处在句首，也不记得前一轮对话。位置信息在 [第 8 章](position-encoding.md) 加入，词与词怎样相互影响在 [第 9 章](self-attention.md) 讲解，经过它们之后两个位置的隐藏状态就会各不相同。

查表也可以看成矩阵乘法：先构造长度为 $V$、只有第 $i$ 项为 1 的 one-hot 向量，再乘 $E$，结果就是 $E_i$。两种写法数值相同，查表省去了构造庞大 one-hot 张量的开销：

```python
one_hot = torch.nn.functional.one_hot(ids, num_classes=len(vocab)).float()
assert torch.allclose(one_hot @ embedding.weight, vectors)
```

向量之间的关系由训练数据、目标函数和参数更新逐步形成。刚初始化时，`我` 和 `在` 的向量只是两组随机数，谈不上谁和谁更像。

## 2. 向量怎样变回词表上的分数

Transformer 接收嵌入向量，输出每个位置的隐藏状态 $H$，形状仍为 `[batch, seq, d]`。完整的 Transformer Block 要到第 10 章才构造；现在用 `vectors` 暂代 $H$，只检查输出端的形状。输出层把每个 $d$ 维向量映射成 $V$ 个分数：

$$
z_{b,t,j}=H_{b,t}\cdot W_j+b_j,\qquad
W\in\mathbb{R}^{V\times d},\quad z\in\mathbb{R}^{B\times T\times V}.
$$

$j$ 遍历词表，$z_{b,t,j}$ 是位置 $(b,t)$ 对候选 token $j$ 的 <strong>logit</strong>，即 softmax 之前的原始分数。PyTorch 的 `nn.Linear(d, V)` 把权重存为 `[V,d]`，计算等价于 `H @ W.T + b`。先猜 `logits` 的形状：

```python
output = nn.Linear(4, len(vocab), bias=True)
logits = output(vectors)
probabilities = logits.softmax(dim=-1)

assert output.weight.shape == (6, 4)
assert logits.shape == (2, 3, 6)
assert torch.allclose(probabilities.sum(dim=-1), torch.ones(2, 3))
```

`softmax(dim=-1)` 在六个候选之间归一化，每个位置得到一个概率分布。每个位置的分布都是对<strong>下一个</strong> token 的预测。`argmax` 取最高分的 ID；实际生成还可能按温度、top-k 或 top-p 采样，见 [第 21 章](generation.md)。

## 3. 让一次预测真正产生梯度

用一条完整的教学序列 `我 在 学习 <eos>`：输入前三项 `[2,3,4]`，目标是后移一位的 `[3,4,1]`。看见“我”预测“在”，看见“我 在”预测“学习”，看见“我 在 学习”预测结束，和第 6 章构造的标签一样。这个训练目标在 [第 13 章](language-model-loss.md) 进一步展开。

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

`cross_entropy` 直接接收<strong>原始 logits</strong>，内部自己做 log-softmax。[PyTorch 交叉熵接口](https://docs.pytorch.org/docs/stable/generated/torch.nn.functional.cross_entropy.html)规定了输入与目标的形状。上面只做了一次反向传播，参数还没动。现在用同一批数据走一步更新，再重新计算损失：

```python
optimizer = torch.optim.SGD(list(embedding.parameters()) + list(output.parameters()), lr=0.1)
before = loss.item()
optimizer.step()
after_logits = output(embedding(input_ids))
after = F.cross_entropy(after_logits.reshape(-1, len(vocab)), target_ids.reshape(-1)).item()
assert after < before
print("更新前/后:", round(before, 4), round(after, 4))
```

损失下降，说明梯度确实从输出端一路传回了嵌入表。这一步只证明了小样本上的一次更新有效；模型还没有位置编码和注意力，无法利用完整上下文。

梯度落在哪些行上？两端的情况不同：

- <strong>输入嵌入表</strong>：普通 `nn.Embedding` 默认返回稠密梯度，但只有作为输入出现过的行有非零值；出现多次的 ID，会把各次使用的梯度累加起来。
- <strong>输出层</strong>：它对全部六个候选都打分，所以权重梯度通常分布在所有行上，目标 ID 那一行只是其中之一。

Notebook 会逐行打印两边的梯度范数。另外，`padding_idx` 让嵌入表的那一行在作为输入时保持不更新，而损失里的 `ignore_index` 是跳过补齐位置的<strong>目标</strong>，两者各管一端。[`nn.Embedding` 参数说明](https://docs.pytorch.org/docs/stable/generated/torch.nn.Embedding.html)

## 4. 输入和输出共用一张表

对比两端：输入表 $E$ 是 `[V,d]`，输出权重 $W$ 也是 `[V,d]`，每一行都对应同一个词表条目。既然如此，可以令 $W=E$，让输入表的行同时充当输出候选向量，这叫<strong>权重共享</strong>（weight tying）：

$$
z_{b,t,j}=H_{b,t}\cdot E_j.
$$

![权重共享：输入端按 ID 取出 E 的第 i 行，输出端用 logits = h @ E^T 把 [B,T,d] 映射成 [B,T,V]，两端引用的是同一个 Parameter](/tinyllm/figures/tied-output.svg)

图的两侧是同一张表的两种用法。左边（输入）按行读取：ID $i$ 取出 $E_i$。右边（输出）整张表一起用：隐藏状态 $h$ 与每一行做点积，`h @ E^T` 把 `[B,T,d]` 变成 `[B,T,V]`。中间只有一个 Parameter，所以省下了一份 $V\times d$ 权重；训练时两端的梯度也汇入这同一个张量。

为了让上面的等式直接成立，本节用<strong>无偏置输出层</strong>；带输出偏置的模型同样可以共享权重，偏置作为额外参数单独存在。[Press 与 Wolf 的研究](https://arxiv.org/abs/1608.05859)讨论了共享输入和输出嵌入的训练效果；它是一种设计选择，效果要在具体模型上验证。

```python
tied_embedding = nn.Embedding(len(vocab), 4)
tied_output = nn.Linear(4, len(vocab), bias=False)
tied_output.weight = tied_embedding.weight  # 同一个 Parameter，不是复制数值

assert tied_output.weight is tied_embedding.weight
assert tied_output.weight.data_ptr() == tied_embedding.weight.data_ptr()
assert len({id(p) for p in list(tied_embedding.parameters()) +
            list(tied_output.parameters())}) == 1
```

共享之后，第 3 节“只有出现过的行才有输入梯度”的规律就要改写：输出分类的梯度落在所有行上，并与输入查表的梯度汇合，所以没有出现在输入中的行也会获得梯度。Notebook 会用 `F.linear(hidden, embedding.weight)` 对照共享层的结果，并在反向传播后检查这一点。

共享有两个前提。一是形状：输出端的隐藏维数要等于嵌入维数，否则需要额外投影。二是 ID 映射：tokenizer 与模型要用同一份词表。更换词表或重排 ID 会改变每一行的意义，输入和输出两端都要处理；只在固定词表上改变切分算法，矩阵可以保留，但模型看到的序列分布会变，见 [第 6 章](tokenization.md)。

## 5. 嵌入之后：Q、K、V 从哪里来

输入和输出两端已经接通。中间的注意力层怎样使用这些向量？这里先看一个单头的预览，完整机制留到第 9 章。先给每个位置的输入加入位置信息，得到 $X$；当前层再用三组<strong>不同的可训练投影</strong>得到查询、键和值：

$$
Q=XW_Q,\qquad K=XW_K,\qquad V=XW_V,\qquad
A=\operatorname{softmax}\!\left(\frac{QK^\top}{\sqrt{d_k}}+M\right),\qquad Y=AV.
$$

$M$ 是因果掩码，让位置 $t$ 只看见自己与之前的位置。对一个 token，Q 可以理解为“这一位置要查什么”，K 是“这一位置供别人匹配的特征”，V 是“被选中后提供的内容”。Q、K、V 都由<strong>当前层的隐藏状态</strong>投影而来；深层的输入已经混入了前面各层处理过的上下文。实际模型的 RoPE 等位置方法作用在 Q/K 上；这里把位置向量直接加到 $X$，只为看清数据流。[Hugging Face 对注意力与缓存的说明](https://huggingface.co/docs/transformers/main/cache_explanation)

下面的单头、小维度实验同时检查掩码和形状；权重随机，注意力数值没有语义：

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
```

注意力用 Q/K 的点积做匹配，匹配范围是<strong>本次前向中的 token 位置</strong>。K 的行数随位置数增长，V 参与加权求和；某一层的 K 是逐 token 的中间特征，没有经过文本级聚合，也没有为检索任务训练，所以它和第 7 节要讲的“文本向量”是两种东西。[第 9 章](self-attention.md) 会继续展开多头、缩放和掩码。

## 6. KV cache 保存的是什么

生成文本时，模型一次只多出一个 token。每一步都把整段序列重新算一遍显然浪费，KV cache 就是为此准备的：

![KV cache 的两个阶段：prefill 一次算出提示词所有位置的 K/V；之后每个解码步只为新 token 计算 K/V 并追加到缓存，新 token 的 Q 与缓存中全部 K 打分，再对全部 V 加权求和](/tinyllm/figures/kv-cache.svg)

先看左半部分：生成开始时处理整段提示词（prefill），得到每一层、每个注意力头对已有 token 的 K/V，存进缓存。再看右半部分的每个解码步：只为<strong>新位置</strong>计算 Q/K/V，把新 K/V 追加到缓存末尾；新 Q 与缓存中所有 K 做点积，经 softmax 得到权重，再对所有 V 加权求和。缓存复用的是旧位置的 K/V；注意力权重取决于新 Q，所以每一步都重新计算。

用上一节的 `x` 逐个位置跑一遍，结果应该和一次性计算的 `context` 一致：

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
```

这个等式成立，是因为因果模型中每个位置只看过去：新 token 到来时，旧位置的 K/V 保持原样。实际缓存还要处理多层、多头、批量、位置编码、padding 和服务端的内存管理；训练时通常整段并行计算，用不到逐 token 缓存。缓存是<strong>本次推理内的计算复用</strong>，生命周期随请求结束；前缀复用也要求输入与模型状态满足匹配条件。[Hugging Face KV cache 文档](https://huggingface.co/docs/transformers/kv_cache)和 [第 22 章](inference-efficiency.md)分别介绍实现策略与显存成本。

## 7. 一个同名词：Agent 的记忆 embedding

本章的 $E_i$ 是语言模型**内部**、按 token ID 读取的参数表。Agent 做记忆检索时也说“embedding”，那通常是另一个专门训练的文本编码模型，把**一整段文本**编码成一个向量，用来按相似度找回历史内容；找回的仍是原始文本，它要重新放进提示词、经过分词器和本章的嵌入层才能被模型使用。两者的输入、训练目标和生命周期都不同，详细对比和检索模型的用法见[第 27 章](./agent-memory.md#two-kinds-of-embedding)。

## 8. 动手实验

打开 [embeddings-and-output.ipynb](/tinyllm/notebooks/embeddings-and-output)，从上到下运行。

| 实验 | 应该看到 |
| --- | --- |
| 查表与 one-hot | `[2, 3]` 的 ID 变成 `[2, 3, 4]`；one-hot 乘 $E$ 与查表结果相同 |
| logits | 形状 `[2, 3, 6]`，每个位置的概率和为 1 |
| 一步更新 | 更新后损失低于更新前；逐行梯度范数中，输入表只有出现过的行非零 |
| 权重共享 | 两端是同一个 Parameter；反向后未出现在输入中的行也有梯度 |
| 单头注意力与 KV 复用 | 第 0 个位置对未来的权重为 0；逐 token 缓存的结果与一次性计算一致 |

运行后，再想一想下面两个问题：

1. 对同一段文本，只改变 tokenizer 的 ID 映射，为什么旧嵌入表要跟着重建？
2. 把一条历史消息存在向量索引，与把它的 K/V 留在缓存里，分别能回答什么问题？

本章的实验验证查表、单头注意力与 KV 复用、logits、梯度和共享参数；没有训练完整语言模型，也没有用真实记忆数据评测检索模型。

## 本章结论：TinyLLM 的选择 {#tinyllm-choice}

<strong>输入使用可训练的 token embedding；输出 logits 投影与它共享同一张权重表。</strong>输出前保留 [最终 RMSNorm](normalization.md#tinyllm-choice)。

理由：小模型里 $V\times d$ 的词表矩阵占参数的比例很大，共享能省下一整份；两端每一行对应同一个词表条目，共享在形状和语义上都自然。这是教学预算下的选择，各个 LLM 的做法并不统一。

什么时候改：若词表输出能力或模型配置需要独立的输出头，就解耦两端，并比较验证损失。若保持共享，第 3 章的初始化对这张张量只执行一次。

::: warning 常见误区
- **ID 的数值大小与语义无关。** 2 和 3 相邻只是行号相邻；初始化时的随机向量也还没有学到词义。
- **Q、K、V 与词嵌入表是两回事。** 它们由每一层的隐藏状态经各自的投影得到，深层的 Q/K/V 已经混入了上下文。
- **KV cache 只存 K 和 V。** 注意力权重取决于新 Q，每步重算；缓存也只在本次推理内有效，用户事实要靠其他记忆机制保存。
- **`cross_entropy` 要的是原始 logits。** 先手动 softmax 再传入，会让概率被处理两次，损失和梯度都会出错。
- **`padding_idx` 与 `ignore_index` 管两件事。** 前者冻结嵌入表的补齐行，后者让损失跳过补齐位置的目标。
- **模型内部的词嵌入与 Agent 的文本向量同名不同物。** 一个按 token 查表，一个把整段文本编码成检索向量。
:::

## 检查理解

1. 若输入 ID 的形状是 `[2, 5]`，词嵌入输出是什么形状？输出 logits 呢？

   <details><summary>参考答案</summary>

   词嵌入输出 `[2, 5, d]`：每个 ID 取出一行 $d$ 维向量。logits 是 `[2, 5, V]`：每个位置对词表中 $V$ 个候选各打一个分。

   </details>

2. 同一个 ID 在两个位置的初始嵌入是否相同？经过位置表示和注意力后呢？

   <details><summary>参考答案</summary>

   查表刚结束时相同，因为取的是同一行；加入位置信息并经过注意力结合上下文后，两个位置的隐藏状态就不同了。

   </details>

3. 在本章的训练设置里，位置 $t$ 的 `argmax(logits)` 给出的是当前 token，还是下一个 token？

   <details><summary>参考答案</summary>

   下一个 token。目标是输入后移一位的序列，例如看见“我 在”的位置要预测“学习”。

   </details>

4. 未共享时，输入嵌入表与输出权重各有多少参数？共享后哪部分梯度会合在一起？

   <details><summary>参考答案</summary>

   各 $V\times d$ 个（输出层若带偏置再加 $V$ 个）。共享后只剩一份 $V\times d$，输入查表的梯度和输出分类的梯度累加到同一个参数上。

   </details>

5. KV cache 里有没有上一步的注意力概率？新 Q 到来时哪些量重用、哪些量重算？

   <details><summary>参考答案</summary>

   没有，缓存只存各层各头的 K 和 V。旧位置的 K/V 重用；新位置的 Q/K/V、新 Q 对所有 K 的分数和 softmax 权重、对 V 的加权和每步重算。

   </details>

## 参考资料

- [PyTorch `nn.Embedding`](https://docs.pytorch.org/docs/stable/generated/torch.nn.Embedding.html) · [`F.cross_entropy`](https://docs.pytorch.org/docs/stable/generated/torch.nn.functional.cross_entropy.html)
- [Using the Output Embedding to Improve Language Models，Press 与 Wolf，2016](https://arxiv.org/abs/1608.05859)
- [Hugging Face：注意力与缓存说明](https://huggingface.co/docs/transformers/main/cache_explanation) · [KV cache 文档](https://huggingface.co/docs/transformers/kv_cache)

下一章系统讲位置表示（[第 8 章](./position-encoding.md)，规划中），随后再构造完整的注意力层；已完成的后续章节可以直接跳到[第 14 章：优化器](./optimizers.md)。
