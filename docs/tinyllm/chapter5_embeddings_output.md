# Chapter 5：词嵌入与输出层

上一章把文本变成了 token ID。假设“我 在 学习”被编码成 `[2, 3, 4]`：2、3、4 只是词表行号，模型不能把它们当成有大小关系的语言特征。它需要在输入端把 ID 变成向量，在输出端把向量变成“下一个 token 是谁”的分数。本章沿着这一次往返，把两端接起来。

配套 <a href="/tinyllm/chapter5_Embeddings_Output/ch5.ipynb" download>ch5.ipynb</a> 使用固定的六项教学词表和 PyTorch；CPU 即可运行，不下载模型或语料。先猜形状和结果，再运行每一格核对。这里的数字只为看清机制，不代表训练好的语言能力。

## 一个 ID 怎样变成一个向量

设词表大小为 $V$，隐藏维数为 $d$。输入嵌入表 $E$ 是形状为 $[V,d]$ 的<strong>可训练参数</strong>。一个 ID $i$ 对应第 $i$ 行 $E_i$；一批输入 ID 的形状若为 `[batch, seq]`，查表结果就是 `[batch, seq, d]`。[PyTorch `nn.Embedding`](https://docs.pytorch.org/docs/stable/generated/torch.nn.Embedding.html) 做的正是这种按索引取行的操作。

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

两个样本都以“我”开头，所以它们取到同一行向量。这里的“相同”仅指<strong>查表刚结束时</strong>；后面的注意力层会结合位置与上下文，令两个位置的隐藏状态不同。嵌入表本身不知道“我”处在句首，也不记得前一轮对话。位置的信息将在 [Chapter 6](chapter6_position_encoding.md) 加入，词与词怎样相互影响将在 [Chapter 7](chapter7_self_attention.md) 讲解。

把 `nn.Embedding` 想成一张表有助于理解它与 one-hot 向量的关系。若先构造长度为 $V$、只有第 $i$ 项为 1 的 one-hot 向量，再乘 $E$，结果仍是 $E_i$；但真的建立庞大的 one-hot 张量没有必要。

```python
one_hot = torch.nn.functional.one_hot(ids, num_classes=len(vocab)).float()
assert torch.allclose(one_hot @ embedding.weight, vectors)
```

ID 的数值和语义距离无关。`我` 的 ID 为 2、`在` 为 3，不意味着它们比 ID 为 5 的 `数学` 更相似；向量之间的关系由训练数据、目标函数和参数更新形成。初始化时的随机向量不应被解释为已经学会了词义。

## 词嵌入怎样进入 Q、K、V

查表只是入口。以一个注意力头为例，先给每个位置的输入加入位置信息，得到 $X$；当前层再用三组<strong>不同的可训练投影</strong>形成查询、键和值：

$$
Q=XW_Q,\qquad K=XW_K,\qquad V=XW_V,\qquad
A=\operatorname{softmax}\!\left(\frac{QK^\top}{\sqrt{d_k}}+M\right),\qquad Y=AV.
$$

$M$ 是因果掩码，让位置 $t$ 只能看见自己与之前的位置。对一个 token，Q 可以理解为“这一位置需要查什么”，K 是“这一位置供别人匹配的特征”，V 是“被选中后提供的内容”。<strong>Q、K、V 不是三套词嵌入表</strong>：它们由当前层的隐藏状态投影而来；深层的输入已经包含此前层处理过的上下文。实际模型的 RoPE 等位置方法可能作用在 Q/K 上，而不是简单把位置向量加到 $X$；这里用加法位置向量，只为了看清数据流。[Hugging Face 对注意力与缓存的说明](https://huggingface.co/docs/transformers/main/cache_explanation)

下面的一头、小维度实验同时检查掩码和形状。权重随机，注意力数值不表示真实语义：

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

注意力确实用 Q/K 的点积做匹配，但这种匹配<strong>只在本次前向的 token 位置之间</strong>进行。K 的形状随位置数增长，V 还要参与加权求和；把某一层的 K 当成“整篇文档的语义向量”，既缺少明确的文本级聚合，也没有经过检索任务训练。[Chapter 7](chapter7_self_attention.md) 会继续展开多头、缩放和掩码。

### KV cache 保存的是什么

生成时先处理整段提示词（prefill），得到每一层、每个注意力头对已有 token 的 K/V。随后每生成一个 token，只为<strong>新位置</strong>计算 Q/K/V，把新 K/V 接到缓存；新 Q 仍要与所有可见 K 做点积，经 softmax 得到权重，再加权读取 V。缓存避免反复计算旧位置的 K/V，<strong>不缓存“哪些旧位置最相似”这一结果</strong>，因为新 Q 不同，注意力权重也要重算。

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

这个等式成立，是因为因果模型中旧位置不能看未来，新 token 到来时旧位置的 K/V 无须因未来内容而改变。实际缓存还要处理多层、多头、批量、位置编码、padding 和服务端的内存管理；训练时通常不这样逐 token 缓存。缓存是本次推理的<strong>计算复用</strong>，一般不跨会话保存用户事实；前缀复用也要求输入与模型状态满足匹配条件。[Hugging Face KV cache 文档](https://huggingface.co/docs/transformers/kv_cache)和 [Chapter 20](chapter20_inference_efficiency.md)分别介绍实现策略与显存成本。

## 向量怎样变回词表上的分数

Transformer 接收嵌入向量，输出每个位置的隐藏状态 $H$，形状仍为 `[batch, seq, d]`。Chapter 8 才会构造 Transformer Block；现在用 `vectors` 暂代 $H$，只检查输出端的形状。输出层把每个 $d$ 维向量映射成 $V$ 个分数：

$$
z_{b,t,j}=H_{b,t}\cdot W_j+b_j,\qquad
W\in\mathbb{R}^{V\times d},\quad z\in\mathbb{R}^{B\times T\times V}.
$$

这里 $j$ 遍历词表；$z_{b,t,j}$ 是位置 $(b,t)$ 对候选 token $j$ 的 <strong>logit</strong>，还不是概率。PyTorch 的 `nn.Linear(d, V)` 把权重存为 `[V,d]`，计算等价于 `H @ W.T + b`。

```python
output = nn.Linear(4, len(vocab), bias=True)
logits = output(vectors)
probabilities = logits.softmax(dim=-1)

assert output.weight.shape == (6, 4)
assert logits.shape == (2, 3, 6)
assert torch.allclose(probabilities.sum(dim=-1), torch.ones(2, 3))
```

`softmax(dim=-1)` 在六个候选之间归一化。`argmax` 只取最高分 ID；实际生成还可能按温度、top-k 或 top-p 采样，见 [Chapter 19](chapter19_autoregressive_generation.md)。每个输入位置都对<strong>下一</strong>个 token 做预测，不能把输出误读成“重建这个位置的输入 token”。

## 让一次预测真正产生梯度

我们用一条完整的教学序列 `我 在 学习 <eos>`。输入前三项 `[2,3,4]`，目标是后移一位的 `[3,4,1]`：看见“我”预测“在”，看见“我 在”预测“学习”，看见“我 在 学习”预测结束。这个“错开一位”的训练目标将在 [Chapter 11](chapter11_language_model_loss.md) 进一步展开。

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

`cross_entropy` 接收<strong>原始 logits</strong>，内部处理 log-softmax；不要先手动 softmax 再把概率送进去。[PyTorch 交叉熵接口](https://docs.pytorch.org/docs/stable/generated/torch.nn.functional.cross_entropy.html)规定了输入与目标形状。上述 loss 只演示一次反向传播：没有 `optimizer.step()`，参数尚未更新。现在用同一批数据走一步更新，再重新计算损失：

```python
optimizer = torch.optim.SGD(list(embedding.parameters()) + list(output.parameters()), lr=0.1)
before = loss.item()
optimizer.step()
after_logits = output(embedding(input_ids))
after = F.cross_entropy(after_logits.reshape(-1, len(vocab)), target_ids.reshape(-1)).item()
assert after < before
print("更新前/后:", round(before, 4), round(after, 4))
```

这只能证明小样本上的这一步更新降低了损失；模型仍没有位置编码或注意力，尚不能根据完整上下文预测。

普通 `nn.Embedding` 默认返回稠密梯度。未作为输入出现的行，在这个<strong>未共享</strong>示例中输入嵌入梯度为零；出现多次的 ID，会从各次使用中累积梯度。输出层则对六个候选都打分，其权重梯度通常不只落在目标 ID 的一行。Notebook 会逐行打印两边的梯度范数。若设置 `padding_idx`，那一行在作为输入嵌入时不参与正常更新；这与在损失里用 `ignore_index` 跳过补齐目标是两件事。[`nn.Embedding` 参数说明](https://docs.pytorch.org/docs/stable/generated/torch.nn.Embedding.html)

## 为什么有人让输入和输出共用一张表

输入表 $E$ 和输出权重 $W$ 都是 `[V,d]`。若分别训练，需要两份这样的矩阵；若<strong>权重共享</strong>（weight tying），就令 $W=E$，用输入表的行同时作为输出候选向量：

$$
z_{b,t,j}=H_{b,t}\cdot E_j.
$$

这样少了一份 $V\times d$ 权重。为让等式直接成立，本节用<strong>无偏置输出层</strong>；带输出偏置的模型仍可共享权重，但偏置是额外参数。[Press 与 Wolf 的研究](https://arxiv.org/abs/1608.05859)讨论了共享输入和输出嵌入的训练效果。它是一种设计选择，不能只凭省参数就断言每个模型都会更好。

```python
tied_embedding = nn.Embedding(len(vocab), 4)
tied_output = nn.Linear(4, len(vocab), bias=False)
tied_output.weight = tied_embedding.weight  # 同一个 Parameter，不是复制数值

assert tied_output.weight is tied_embedding.weight
assert tied_output.weight.data_ptr() == tied_embedding.weight.data_ptr()
assert len({id(p) for p in list(tied_embedding.parameters()) +
            list(tied_output.parameters())}) == 1
```

共享后，输出分类的梯度和输入查表的梯度会汇入<strong>同一个参数</strong>。因此，“未出现在输入中的行梯度为零”只适用于前面的未共享输入表，不能照搬到共享模型。Notebook 会用 `F.linear(hidden, embedding.weight)` 对照共享层的结果，并检查反向传播后未出现在输入中的行也可能获得梯度。

共享有形状条件：输出端使用的隐藏维数要与嵌入维数匹配；若不匹配，需要额外投影。tokenizer 与模型的 ID 映射也必须一致。更换词表或重排 ID 会改变每一行的意义，输入和输出两端都要处理；只在固定词表上改变切分算法虽然不需要重建矩阵，也会改变模型看到的序列分布，见 [Chapter 4](chapter4_tokenization.md)。

## 一个常见的同名词：Agent 的记忆 embedding

上面学的 $E_i$ 是语言模型内部、按 token ID 读取的参数表。Agent 的记忆检索常把<strong>一段完整文本</strong>编码成一个向量，用相似度查找历史内容；检索出的文本进入当前提示词，再经过 tokenizer 和模型内部嵌入层。它一般属于独立的检索系统，不会因为语言模型在本章调用 `backward()` 而自动更新。

| 问题 | 模型内部嵌入 | Agent 记忆检索向量 |
| --- | --- | --- |
| 输入与输出 | 单个 token ID → 一个可训练向量 | 一段文本 → 一个用于比较的向量 |
| 更新 | 随语言模型损失训练 | 通常由独立编码器生成，历史记录需按版本管理 |
| 用途 | 参与模型前向计算 | 帮助找回证据，再把证据放回上下文 |

向量相近不等于记忆仍有效。“去年住上海”和“现在住北京”都可能被找到；还要保存来源、时间和更新关系，并评价最终回答能否使用正确证据。完整的 Agent 记忆设计和开源评测放在 [Chapter 25](chapter25_agent_memory.md)，本章只保留这条接口边界。

### 为什么通常使用单独的文本编码模型

若 Agent 有十万条历史，它需要<strong>提前</strong>把每条记忆编码、存入索引；新问题到来时，只编码问题，再从索引中找候选。常见的双塔检索模型把问题与文档分别编码为固定维度向量 $e_q$、$e_m$，用余弦相似度或内积排序：

$$
\operatorname{cos}(e_q,e_m)=\frac{e_q\cdot e_m}{\|e_q\|\,\|e_m\|}.
$$

同一个记忆向量要能与许多未来的问题比较。这要求模型学习<strong>跨文本、可复用的向量空间</strong>，通常还要把整段文本的多个 token 表示汇成一个向量，并用相关/不相关的文本对训练。检索模型内部也可能使用 Transformer 和 Q/K/V 注意力；不同之处主要是<strong>最终取出的表示和训练目标</strong>。生成模型的 Q/K/V 服务于每层、每头、当前上下文内的下一 token 计算；其形状、位置依赖、生命周期和训练目标都不同。仅把生成模型某层的 K 或词嵌入行拿出来求余弦，没有理由保证它能找回相关记忆。这是<strong>目标与接口不匹配</strong>，并非注意力点积本身不能表达相似性。

[Hugging Face 上的多语言 MiniLM](https://huggingface.co/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2)展示了一个具体实现：Transformer 先生成每个 token 的上下文化表示，再按 attention mask 做平均池化，得到一个 384 维句子向量。[multilingual-e5-small 的模型卡](https://huggingface.co/intfloat/multilingual-e5-small?library=sentence-transformers)把查询与材料分别加上 `query:`、`passage:` 前缀；[BGE-M3](https://huggingface.co/BAAI/bge-m3)同时支持稠密向量、稀疏检索和多向量检索。较新的 [Qwen3-Embedding-0.6B](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B) 则展示了另一种做法：在其示例中读取最后一个有效位置的隐藏状态，查询还可使用任务指令。<strong>文本级向量不一定都靠平均池化</strong>；要遵守对应模型卡的取向量与输入格式约定。这些是有不同训练与输出接口的检索模型例子，不是 TinyLLM 当前使用的依赖，也不能只按维度或模型大小选“最好”的一个。

真实系统也并非绝对不能复用生成模型：可以对它的隐藏状态做池化、指定提示格式，再用检索数据微调或蒸馏成文本 embedding 模型。但这已经增加了文本级表示和检索训练目标，而不是直接复用现成 Q/K/V 的一行缓存。选择独立模型的实际好处是记忆可离线建索引、问题可快速检索；代价是多一套模型、存储与版本管理。替换编码器或改变池化/前缀规则后，旧索引向量往往要重算。检索返回的仍是<strong>原始记忆文本</strong>，随后它作为新提示词进入语言模型并产生新的 token 嵌入、Q/K/V 和 KV cache。

可以在 Hugging Face 模型卡所列的环境里用下面的流程试验；首次运行会下载模型，本章 notebook 默认不执行这一段：

```python
from sentence_transformers import SentenceTransformer

retriever = SentenceTransformer("intfloat/multilingual-e5-small")
query_vec = retriever.encode(["query: 这个项目的图表库是什么？"], normalize_embeddings=True)
memory_vecs = retriever.encode(
    ["passage: 本项目统一使用 Plotly 画图。", "passage: 模型使用 PyTorch。"],
    normalize_embeddings=True,
)
scores = query_vec @ memory_vecs.T
print(scores)  # 两段材料各一个检索分数；仍须检查来源和事实是否有效
```

实验时要固定模型版本、查询/材料前缀、池化方式和归一化规则。还要在中文、多项目同名事实、事实更新与无答案问题上测检索命中和最终回答；单次余弦分数不能证明记忆系统可靠。[Chapter 25](chapter25_agent_memory.md) 给出完整评测路线。

## 动手检查

运行 notebook 后，试着不用看输出回答以下问题：

1. 若输入是 `[2, 5]`，词嵌入输出为什么是 `[2, 5, d]`，输出 logits 又为什么是 `[2, 5, V]`？
2. 同一个 ID 在两个位置的初始嵌入是否相同？经过位置表示和注意力后呢？
3. `argmax(logits)` 得到的是当前 token，还是本例训练目标中的下一个 token？
4. 未共享时，输入嵌入表与输出权重各有多少参数？共享后哪部分梯度会合在一起？
5. 对同一段文本，只改变 tokenizer 的 ID 映射，为什么不能沿用旧嵌入表？
6. KV cache 里有没有上一步的注意力概率？新 Q 到来时哪些量重用、哪些量重算？
7. 把一条历史消息存在向量索引，与把它的 K/V 留在缓存里，分别能回答什么问题？

本章的实验验证查表、单头注意力与 KV 复用、logits、梯度和共享参数；没有训练完整语言模型，也没有用真实记忆数据评测检索模型。下一章会系统讲位置表示，随后再构造完整的注意力层。

返回 [课程总目录](index.md#课程路线规划)，或继续 [Chapter 6：位置表示](chapter6_position_encoding.md)。
