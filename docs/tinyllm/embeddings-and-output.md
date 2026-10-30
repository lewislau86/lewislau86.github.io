---
title: "第 5 章：词嵌入与输出层"
description: "token ID 怎样查表变成向量，向量怎样变回词表上的分数；Q/K/V 从哪里来；为什么输入输出可以共用一张表。"
pageClass: tinyllm-course
---

# 第 5 章：词嵌入与输出层

[课程总览](./index.md) · [上一章](./tokenization.md) · [下一章](./self-attention.md)

::: tip 本章学习目标
说清 `[batch, seq] → [batch, seq, d] → [batch, seq, V]` 的形状变化；解释 logits、交叉熵梯度与权重共享；区分模型内部的词嵌入与检索用的文本向量。

**前置：** [第 4 章](./tokenization.md)的 token ID；[第 2 章](./tensors-and-autograd.md)的矩阵乘法与梯度。

**实践方式：** [embeddings-and-output.ipynb](/tinyllm/notebooks/embeddings-and-output)（也可以直接运行 <a href="/tinyllm/code/embeddings-and-output.py" download>embeddings-and-output.py</a>），固定的六项教学词表和 PyTorch，CPU 即可，不下载模型或语料。先猜形状和结果，再运行每一格核对；这里的数字只为看清机制，不代表训练好的语言能力。
:::

[上一章](./tokenization.md)把文本变成了 token ID。假设“我 在 学习”被编码成 `[2, 3, 4]`：2、3、4 是词表的行号，它们之间的大小毫无语言含义。模型要用它们做计算，两端各缺一步：<strong>输入端</strong>要把 ID 变成向量，<strong>输出端</strong>要把向量变回“下一个 token 是谁”的分数。本章沿着这一次往返，把两端接起来，再顺带看看向量进入注意力之后变成了什么。

<TinyLLMMap active="embeddings-and-output" />

## 1. 一个 ID 怎样变成一个向量

::: info 本章代码从哪里来
本章所有代码都在一个文件里：<a href="/tinyllm/code/embeddings-and-output.py" download>embeddings-and-output.py</a>（[在 GitHub 上查看](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/tinyllm/code/embeddings-and-output.py)）。下面的代码块都是从这个文件里直接截取的片段，所以单独复制一段可能缺少 `import` 或前面定义的变量；想自己运行，请下载完整文件，`python embeddings-and-output.py` 从头跑到尾即可。notebook 版本也由同一个文件生成，可以[在线查看](/tinyllm/notebooks/embeddings-and-output)，或[在 Colab 中直接运行](https://colab.research.google.com/github/lewislau86/lewislau86.github.io/blob/master/docs/public/tinyllm/notebooks/embeddings-and-output.ipynb)。
:::

设词表大小为 $V$，隐藏维数为 $d$。输入嵌入表 $E$ 是形状为 $[V,d]$ 的<strong>可训练参数</strong>，ID $i$ 对应第 $i$ 行 $E_i$。先猜：一批形状为 `[2, 3]` 的 ID 查表后是什么形状？

<<< @/public/tinyllm/code/embeddings-and-output.py#lookup

![六项词表的嵌入表 E 形状为 [6,4]；ID 序列 [2,3,4] 分别取出第 2、3、4 行，拼成形状为 [3,4] 的向量序列](/tinyllm/figures/embedding-lookup.svg)

图左边是整张嵌入表，每一行属于一个词表条目；右边是查表结果。ID 2、3、4 就是三个行号，`nn.Embedding` 按行号把这三行原样取出、按输入顺序排好，于是 `[3]` 个 ID 变成 `[3, 4]` 的向量。整批输入 `[batch, seq]` 也是同样的逐个取行，结果是 `[batch, seq, d]`。[PyTorch `nn.Embedding`](https://docs.pytorch.org/docs/stable/generated/torch.nn.Embedding.html) 做的正是这种按索引取行的操作。

两条样本都以“我”开头，所以它们取到同一行向量。这里的“相同”仅限<strong>查表刚结束时</strong>：嵌入表只认 ID，不知道“我”处在句首，也不记得前一轮对话。位置信息在 [第 7 章](position-encoding.md) 加入，词与词怎样相互影响在 [第 6 章](self-attention.md) 讲解，经过它们之后两个位置的隐藏状态就会各不相同。

查表也可以看成矩阵乘法：先构造长度为 $V$、只有第 $i$ 项为 1 的 one-hot 向量，再乘 $E$，结果就是 $E_i$。两种写法数值相同，查表省去了构造庞大 one-hot 张量的开销：

<<< @/public/tinyllm/code/embeddings-and-output.py#one-hot

向量之间的关系由训练数据、目标函数和参数更新逐步形成。刚初始化时，`我` 和 `在` 的向量只是两组随机数，谈不上谁和谁更像。

## 2. 向量怎样变回词表上的分数

Transformer 接收嵌入向量，输出每个位置的隐藏状态 $H$，形状仍为 `[batch, seq, d]`。完整的 Transformer Block 要到第 9 章才构造；现在用 `vectors` 暂代 $H$，只检查输出端的形状。输出层把每个 $d$ 维向量映射成 $V$ 个分数：

$$
z_{b,t,j}=H_{b,t}\cdot W_j+b_j,\qquad
W\in\mathbb{R}^{V\times d},\quad z\in\mathbb{R}^{B\times T\times V}.
$$

$j$ 遍历词表，$z_{b,t,j}$ 是位置 $(b,t)$ 对候选 token $j$ 的 <strong>logit</strong>，即 softmax 之前的原始分数。PyTorch 的 `nn.Linear(d, V)` 把权重存为 `[V,d]`，计算等价于 `H @ W.T + b`。先猜 `logits` 的形状：

<<< @/public/tinyllm/code/embeddings-and-output.py#logits

`softmax(dim=-1)` 在六个候选之间归一化，每个位置得到一个概率分布。每个位置的分布都是对<strong>下一个</strong> token 的预测。`argmax` 取最高分的 ID；实际生成还可能按温度、top-k 或 top-p 采样，见 [第 25 章](generation.md)。

## 3. 让一次预测真正产生梯度

用一条完整的教学序列 `我 在 学习 <eos>`：输入前三项 `[2,3,4]`，目标是后移一位的 `[3,4,1]`。看见“我”预测“在”，看见“我 在”预测“学习”，看见“我 在 学习”预测结束，和第 4 章构造的标签一样。这个训练目标在 [第 15 章](language-model-loss.md) 进一步展开。

<<< @/public/tinyllm/code/embeddings-and-output.py#loss

`cross_entropy` 直接接收<strong>原始 logits</strong>，内部自己做 log-softmax。[PyTorch 交叉熵接口](https://docs.pytorch.org/docs/stable/generated/torch.nn.functional.cross_entropy.html)规定了输入与目标的形状。上面只做了一次反向传播，参数还没动。现在用同一批数据走一步更新，再重新计算损失：

<<< @/public/tinyllm/code/embeddings-and-output.py#sgd-step

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

<<< @/public/tinyllm/code/embeddings-and-output.py#tying

共享之后，第 3 节“只有出现过的行才有输入梯度”的规律就要改写：输出分类的梯度落在所有行上，并与输入查表的梯度汇合，所以没有出现在输入中的行也会获得梯度。Notebook 会用 `F.linear(hidden, embedding.weight)` 对照共享层的结果，并在反向传播后检查这一点。

共享有两个前提。一是形状：输出端的隐藏维数要等于嵌入维数，否则需要额外投影。二是 ID 映射：tokenizer 与模型要用同一份词表。更换词表或重排 ID 会改变每一行的意义，输入和输出两端都要处理；只在固定词表上改变切分算法，矩阵可以保留，但模型看到的序列分布会变，见 [第 4 章](tokenization.md)。

## 5. 嵌入之后：Q、K、V 从哪里来

输入和输出两端已经接通。中间的注意力层怎样使用这些向量？这里先看一个单头的预览，完整机制留到第 6 章。先给每个位置的输入加入位置信息，得到 $X$；当前层再用三组<strong>不同的可训练投影</strong>得到查询、键和值：

$$
Q=XW_Q,\qquad K=XW_K,\qquad V=XW_V,\qquad
A=\operatorname{softmax}\!\left(\frac{QK^\top}{\sqrt{d_k}}+M\right),\qquad Y=AV.
$$

$M$ 是因果掩码，让位置 $t$ 只看见自己与之前的位置。对一个 token，Q 可以理解为“这一位置要查什么”，K 是“这一位置供别人匹配的特征”，V 是“被选中后提供的内容”。Q、K、V 都由<strong>当前层的隐藏状态</strong>投影而来；深层的输入已经混入了前面各层处理过的上下文。实际模型的 RoPE 等位置方法作用在 Q/K 上；这里把位置向量直接加到 $X$，只为看清数据流。[Hugging Face 对注意力与缓存的说明](https://huggingface.co/docs/transformers/main/cache_explanation)

下面的单头、小维度实验同时检查掩码和形状；权重随机，注意力数值没有语义：

<<< @/public/tinyllm/code/embeddings-and-output.py#qkv

注意力用 Q/K 的点积做匹配，匹配范围是<strong>本次前向中的 token 位置</strong>。K 的行数随位置数增长，V 参与加权求和；某一层的 K 是逐 token 的中间特征，没有经过文本级聚合，也没有为检索任务训练，所以它和第 6 节要讲的“文本向量”是两种东西。[第 6 章](self-attention.md) 会继续展开多头、缩放和掩码。生成文本时，旧位置的 K、V 还可以存起来反复使用，这就是 KV cache，它只在推理阶段用得上，放在[第 26 章](./inference-efficiency.md#kv-cache)细讲。

## 6. 一个同名词：Agent 的记忆 embedding

本章的 $E_i$ 是语言模型**内部**、按 token ID 读取的参数表。Agent 做记忆检索时也说“embedding”，那通常是另一个专门训练的文本编码模型，把**一整段文本**编码成一个向量，用来按相似度找回历史内容；找回的仍是原始文本，它要重新放进提示词、经过分词器和本章的嵌入层才能被模型使用。两者的输入、训练目标和生命周期都不同，详细对比和检索模型的用法见[第 33 章](./agent-memory.md#two-kinds-of-embedding)。

## 7. 动手实验

打开 [embeddings-and-output.ipynb](/tinyllm/notebooks/embeddings-and-output)，从上到下运行。

| 实验 | 应该看到 |
| --- | --- |
| 查表与 one-hot | `[2, 3]` 的 ID 变成 `[2, 3, 4]`；one-hot 乘 $E$ 与查表结果相同 |
| logits | 形状 `[2, 3, 6]`，每个位置的概率和为 1 |
| 一步更新 | 更新后损失低于更新前；逐行梯度范数中，输入表只有出现过的行非零 |
| 权重共享 | 两端是同一个 Parameter；反向后未出现在输入中的行也有梯度 |
| 单头注意力 | 第 0 个位置对未来的权重为 0 |

运行后，再想一想下面两个问题：

1. 对同一段文本，只改变 tokenizer 的 ID 映射，为什么旧嵌入表要跟着重建？
2. 把一条历史消息存在向量索引，与把它的 K/V 留在缓存里（KV cache 见[第 26 章](./inference-efficiency.md#kv-cache)），分别能回答什么问题？

本章的实验验证查表、单头注意力、logits、梯度和共享参数；没有训练完整语言模型，也没有用真实记忆数据评测检索模型。

<!-- real-model:start -->

## 在真实模型里

本章的查表、输出层和权重共享，在真实代码里各有对应。下表的链接都指向 Hugging Face transformers 的固定版本 `v5.21`，精确到行。读代码时可以先跳过缓存、掩码、并行这些工程细节，只看和本章对应的那几行。

| 本章的零件 | 真实代码 | 对照要点 |
| --- | --- | --- |
| 词嵌入表 | [`modeling_llama.py 第 342 行`](https://github.com/huggingface/transformers/blob/v5.21/src/transformers/models/llama/modeling_llama.py#L342) | `nn.Embedding(vocab_size, hidden_size)`，和本章完全一样 |
| 输出层与权重共享 | [`LlamaForCausalLM`](https://github.com/huggingface/transformers/blob/v5.21/src/transformers/models/llama/modeling_llama.py#L410-L480) | `lm_head` 是一个不带偏置的线性层；类属性 `_tied_weights_keys` 声明它可以和 `embed_tokens` 共享权重，是否共享由配置 `tie_word_embeddings` 决定 |
| 语言模型损失 | [`ForCausalLMLoss`](https://github.com/huggingface/transformers/blob/v5.21/src/transformers/loss/loss_utils.py#L51-L73) | 把标签错开一位再算交叉熵，`ignore_index=-100` 的位置不计入，和本章的标签构造一致 |

想在本机看源码，可以先 `pip install transformers`，再用 `python -m inspect transformers.models.llama.modeling_llama:LlamaMLP` 这样的命令打印出任意一个类。

<!-- real-model:end -->

## 本章结论：TinyLLM 的选择 {#tinyllm-choice}

<strong>输入使用可训练的 token embedding；输出 logits 投影与它共享同一张权重表。</strong>输出前保留 [最终 RMSNorm](normalization.md#tinyllm-choice)。

理由：小模型里 $V\times d$ 的词表矩阵占参数的比例很大，共享能省下一整份；两端每一行对应同一个词表条目，共享在形状和语义上都自然。这是教学预算下的选择，各个 LLM 的做法并不统一。

什么时候改：若词表输出能力或模型配置需要独立的输出头，就解耦两端，并比较验证损失。若保持共享，第 10 章的初始化对这张张量只执行一次。

::: warning 常见误区
- **ID 的数值大小与语义无关。** 2 和 3 相邻只是行号相邻；初始化时的随机向量也还没有学到词义。
- **Q、K、V 与词嵌入表是两回事。** 它们由每一层的隐藏状态经各自的投影得到，深层的 Q/K/V 已经混入了上下文。
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

## 参考资料

- [PyTorch `nn.Embedding`](https://docs.pytorch.org/docs/stable/generated/torch.nn.Embedding.html) · [`F.cross_entropy`](https://docs.pytorch.org/docs/stable/generated/torch.nn.functional.cross_entropy.html)
- [Using the Output Embedding to Improve Language Models，Press 与 Wolf，2016](https://arxiv.org/abs/1608.05859)
- [Hugging Face：注意力与缓存说明](https://huggingface.co/docs/transformers/main/cache_explanation)

现在每个字都还是一个孤立的向量，“学习”并不知道前面是“我”。下一章让这些向量互相看见：[第 6 章：自注意力](./self-attention.md)。
