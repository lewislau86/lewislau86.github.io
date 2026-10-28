---
title: "第 5 章：自注意力"
description: "让每个 token 去看前面的字：Q/K/V、缩放点积、因果掩码、多头注意力，以及注意力为什么必不可少、代价在哪里。"
pageClass: tinyllm-course
---

# 第 5 章：自注意力

[课程总览](./index.md) · [上一章](./embeddings-and-output.md) · [下一章](./position-encoding.md)

::: tip 本章学习目标
能手算一次三个位置的因果注意力（打分、遮住未来、softmax、加权求和）；能说出 Q、K、V 各自的作用；能写出多头注意力，并核对每一步张量形状；能解释注意力的代价为什么随上下文长度平方增长。

**前置：** [第 2 章](./tensors-and-autograd.md)的矩阵乘法与 `transpose`；[第 4 章](./embeddings-and-output.md)的词嵌入。

**实践方式：** [self-attention.ipynb](/tinyllm/notebooks/self-attention)（也可以直接运行 <a href="/tinyllm/code/self-attention.py" download>self-attention.py</a>），CPU 约一分钟。
:::

<TinyLLMMap active="self-attention" />

## 问题：查完表，每个字还是孤立的

[第 4 章](./embeddings-and-output.md)把“我 在 学习”变成了三个向量。可是查表只认 ID：不管“学习”前面是“我”还是“数学”，它查到的都是同一行。

::: info 本章代码从哪里来
本章所有代码都在一个文件里：<a href="/tinyllm/code/self-attention.py" download>self-attention.py</a>（[在 GitHub 上查看](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/tinyllm/code/self-attention.py)）。下面的代码块都是从这个文件里直接截取的片段，所以单独复制一段可能缺少 `import` 或前面定义的变量；想自己运行，请下载完整文件，`python self-attention.py` 从头跑到尾即可。notebook 版本也由同一个文件生成，可以[在线查看](/tinyllm/notebooks/self-attention)，或[在 Colab 中直接运行](https://colab.research.google.com/github/lewislau86/lewislau86.github.io/blob/master/docs/public/tinyllm/notebooks/self-attention.ipynb)。
:::

<<< @/public/tinyllm/code/self-attention.py#isolated

要预测“学习”后面是什么，模型必须知道前面说了什么。每个位置都需要一种办法，去前面的位置里**把有用的信息取回来**。这就是注意力要做的事。

## 1. 打分：每个位置去问其他位置

可以把注意力想成在图书馆里找资料。每个位置手里有三样东西：

- **Q（query，查询）**：我想找什么；
- **K（key，键）**：我这里有什么，供别人来匹配；
- **V（value，值）**：别人选中我以后，我交出去的内容。

位置 $i$ 用自己的 $q_i$ 和每个位置的 $k_j$ 做点积，点积越大说明越匹配；再用 softmax 把一行分数变成和为 1 的权重；最后按权重把所有位置的 $v_j$ 加起来，就是位置 $i$ 取回的信息：

$$
\operatorname{Attention}(Q,K,V)=\operatorname{softmax}\!\left(\frac{QK^\top}{\sqrt{d}}\right)V
$$

先用一个能手算的小例子：三个位置，每个向量只有 2 维。

<<< @/public/tinyllm/code/self-attention.py#hand

看“学习”这一行（第 3 行）：$q=[1,1]$ 和三个 $k$ 的点积分别是 1、1、2，除以 $\sqrt 2$ 得到 0.71、0.71、1.41；softmax 之后是 0.25、0.25、0.50；输出就是 $0.25\,v_0+0.25\,v_1+0.50\,v_2=[1.76,\ 2.01]$。

**为什么要除以 $\sqrt d$？** 两个 $d$ 维随机向量的点积，方差大约随 $d$ 线性增长。$d$ 一大，分数就动辄几十，softmax 会把几乎全部权重压到一个位置上，其余位置的梯度接近 0。除以 $\sqrt d$ 把分数拉回差不多的尺度，这一点和[第 9 章](./initialization-and-residuals.md)讲的“按宽度选初始化尺度”是同一个道理。

## 2. 因果掩码：只许看自己和前面

上面那张权重表里，“我”也给后面的“学习”分了 0.40 的权重。生成文本时，“我”出现的那一刻，“学习”还没写出来，所以训练时也必须遮住未来，否则模型就是在偷看答案。做法是把对角线以上的分数改成 $-\infty$，softmax 之后这些位置的权重正好是 0：

<<< @/public/tinyllm/code/self-attention.py#causal

![三个位置“我、在、学习”：先算 Q 与 K 的点积除以根号 2 得到分数；把对角线以上的未来位置改成负无穷；按行 softmax 得到权重，“学习”这一行是 0.25、0.25、0.50；最后用权重对 V 加权求和得到输出，“我”只看见自己，输出等于自己的 V](/tinyllm/figures/attention-steps.svg)

从左往右读这四步。第 1 行“我”只看得见自己，权重是 1，输出就是它自己的 $v_0$；第 2 行“在”能看见“我”和自己；第 3 行“学习”能看见全部三个位置，结果和不加掩码时一样。整张权重表变成了下三角。这种只看前文的注意力叫**因果注意力**，第 1 章那个模型里用的就是它（`is_causal=True`）。

## 3. 真实模型里的 Q、K、V：三个投影

手算时 Q、K、V 是我们直接给的。真实模型里，它们都从同一份输入 $x$ 经过三个**不同的线性层**得到：$Q=xW_Q$，$K=xW_K$，$V=xW_V$。这三个矩阵是可训练参数，训练会自己学出“该找什么、该亮出什么、该交出什么”。

<<< @/public/tinyllm/code/self-attention.py#single-head

自己写的版本和 PyTorch 的 `F.scaled_dot_product_attention` 最大只差约 $10^{-7}$，说明实现是对的。实际使用时推荐直接调用这个官方函数：它在 GPU 上会自动选用更快、更省显存的内核（例如 FlashAttention），算的是同一个数学式。

## 4. 多头：分成几组，各看各的

一个位置可能同时需要好几种信息：上一个字是什么、这句话的主语在哪、押韵的字在哪。只用一组 Q、K、V，权重只能有一种分配方式。**多头注意力**把 $d$ 维切成 $H$ 份，每份各做一次注意力，再拼回来：

![输入 x 的形状是 B、T、D；线性层算出 Q、K、V；把最后一维切成 H 份并转置成 B、H、T、D/H；每个头各做一次因果注意力；再转置、reshape 拼回 B、T、D，最后经过输出投影](/tinyllm/figures/multihead-shapes.svg)

整个过程就是[第 2 章](./tensors-and-autograd.md)讲过的 `view` 和 `transpose`：把头这一维挪到前面，后两维就是每个头自己的 `[T, D/H]`，矩阵乘法会自动对每个头分别计算。

<<< @/public/tinyllm/code/self-attention.py#multi-head

切成多个头并不增加计算量：$H$ 个头各算 $D/H$ 维，合起来和一个 $D$ 维的头一样多。最后的 `proj` 把各个头取回的信息再混合一次。脚本里还用同一组权重和官方函数逐数对照了一遍，最大差约 $6\times10^{-8}$。

## 5. 去掉注意力会怎样？

注意力到底有多重要，最直接的办法是把它拿掉试试。下面用[第 1 章](./first-run.md)的同一份唐诗、同一个模型、同样 600 步训练，只改一处：Block 里跳过注意力。这样每个位置只能看见自己这个字和它的位置，没法看前面的字。

<<< @/public/tinyllm/code/self-attention.py#ablation

![同一份唐诗语料、同一个模型、同样 600 步：有注意力时训练损失降到约 0.11；把注意力去掉后，每个位置只能看到自己，损失停在约 1.6](/tinyllm/figures/attention-ablation.svg)

两条曲线开头几乎重合，100 步以后就分开了。有注意力的模型损失降到约 0.11，能把整首诗背出来；没有注意力的模型停在约 1.6，因为它只知道“当前这个字后面常跟什么字”。以“床前”开头各生成一次：

```text
有注意力：  床前明月光，疑是地上霜。举头望明月，低头思故乡。
没有注意力：床前，清晨入旧年绿树村边。征。随风潜入大荒城。
```

没有注意力的那句，两个字两个字地看都像唐诗（“绿树”“村边”“随风潜入”），但五个字一顿的节奏、前后的意思全乱了：它根本不知道前面写过什么。**注意力是模型里唯一让不同位置交换信息的地方**；前馈层、归一化都只对每个位置单独计算。

## 6. 代价：上下文长度的平方

每个头都要算一张 $T\times T$ 的分数表，上下文长度翻一倍，这张表就变成四倍。只算这张表本身（32 个头、FP32）要多少内存：

<<< @/public/tinyllm/code/self-attention.py#cost

```text
T =   1,000  分数矩阵       0.13 GB
T =   4,000  分数矩阵       2.05 GB
T =  32,000  分数矩阵     131.07 GB
T = 128,000  分数矩阵    2097.15 GB
```

这还只是一层。现实中有几种办法分头应对：

- **不存这张表**：FlashAttention 一块一块地算，算完就丢，内存不再随 $T^2$ 增长；但计算量仍然是 $T^2$。`F.scaled_dot_product_attention` 在条件满足时会自动用上。
- **生成时不重算前文**：每生成一个字，旧位置的 K、V 不会变，可以存起来复用，这就是 KV cache，见[第 22 章](./inference-efficiency.md#kv-cache)。缓存要占显存，GQA 让几个头共用一组 K、V 来省这部分显存。
- **换一种注意力**：[第 1 章](./first-run.md)对比表里的 Kimi K3、Qwen3.5 把大部分层换成线性注意力，把前文压成固定大小的状态，只留四分之一的层做完整注意力。

## 7. 延伸：QK Norm {#qk-norm}

### 要解决的问题

注意力分数由 Q 与 K 的点积得到，再经过 softmax 变成权重。如果 Q、K 的长度在训练中越变越大，点积也会跟着变大，softmax 就会“饱和”：某一个 key 的权重接近 1，其余接近 0，梯度也随之变得极小或剧烈波动。QK Norm 在点积**之前**分别把 Q、K 的尺度控制住。

它和[第 10 章](./normalization.md)的 RMSNorm 管的是不同的地方：RMSNorm 处理进入子层前的隐藏状态，QK Norm 处理注意力**内部**的 Q 和 K。两者可以同时存在，Qwen3、Gemma 3、OLMo 2 都是这样做的。

### 原始做法：逐头 L2 归一化

[原始 QKNorm 论文](https://aclanthology.org/2020.findings-emnlp.379/)把每个头的 q、k 都除以自己的 L2 长度，再乘一个可学习尺度 $g$，代替固定的 $1/\sqrt{d_k}$：

$$
\widehat q=\frac{q}{\|q\|_2+\epsilon},\qquad
\widehat k=\frac{k}{\|k\|_2+\epsilon},\qquad
s(q,k)=g\,\widehat q^{\mathsf T}\widehat k
$$

归一化后，点积就是两个单位向量的夹角余弦，取值在 $[-1,1]$，再由 $g$ 决定整体幅度。

下面故意把 Q、K 放大 10 倍，看归一化前后分数差多少：

<<< @/public/tinyllm/code/self-attention.py#qk-norm

### 现代模型的两种粒度

今天的公开模型多用 RMSNorm 而不是 L2，并且有两种统计范围：

| 粒度 | 在哪一维求 RMS | 公开模型例子 |
| --- | --- | --- |
| 整层（layerwise） | 拆头之前，对每个 token 的整条 Q 或 K 投影 | [OLMo 2、OLMo 3](https://allenai.org/papers/olmpool) |
| 逐头（headwise） | 拆头之后，对每个头的 `head_dim` | [Qwen 3、Gemma 3、Marin 32B](https://allenai.org/papers/olmpool) |

逐头版本可在拆头后用 `nn.RMSNorm(head_dim)` 分别处理 q、k；整层版本要在拆头前对完整投影宽度做 RMSNorm。两者统计维度不同，不能只换模块名。RoPE、缩放和归一化的先后顺序也要以目标模型的代码为准。

### 取舍

QK Norm 让训练更稳定，但也改变了注意力的表达方式。[OlmPool](https://allenai.org/papers/olmpool) 的受控实验发现它有助于稳定训练，却在长上下文扩展实验中损害了部分效果。所以 TinyLLM 默认**不加** QK Norm，先监测注意力 logits 的最大值和注意力熵；训练中出现分数失控时再引入，并在目标上下文长度上重新评估。

上面那段代码里，放大后的原始分数绝对值最大到 228，QK Norm 之后只有 3.4，不会超过 $g=4$。[normalization.ipynb](/tinyllm/notebooks/normalization) 还有一个更小的例子：两个长度差异很大的 Q/K 向量，原始点积最大为 100，L2 归一化后最大为 1。

## 本章结论：TinyLLM 的选择 {#tinyllm-choice}

先实现带**因果掩码的缩放点积多头注意力（MHA）**，核对 Q/K/V 形状、mask 和 softmax；实际计算交给 `F.scaled_dot_product_attention`。模型需要更低 KV cache 占用时，再用较少的 KV 头改成 **GQA**，并保持相同训练和评估口径。GQA 是推理内存与质量之间的权衡，不能只看头数判断优劣。[GQA 论文](https://arxiv.org/abs/2305.13245)

::: warning 常见误区
- **Q、K、V 不是三张词嵌入表。** 它们由每一层的隐藏状态经三个投影得到，深层的 Q、K、V 已经混入了前面各层取回的上下文。
- **因果掩码要加在 softmax 之前。** 先 softmax 再把未来位置清零，剩下的权重加起来就不是 1 了。
- **多头不会让计算量翻 H 倍。** 每个头只算 $D/H$ 维，总量和一个 $D$ 维的头相同。
- **注意力权重不等于“模型的解释”。** 它说明信息从哪些位置取回，但经过多层、多头和前馈层之后，不能直接读成“模型因为这个字才这样回答”。
:::

## 检查理解

1. 手算：只有两个位置，$q_1=[0,2]$，$k_0=[1,0]$，$k_1=[0,1]$，$d=2$。位置 1 对两个位置的分数和因果注意力权重各是多少？

   <details><summary>参考答案</summary>

   点积分别是 0 和 2，除以 $\sqrt2$ 得 0 和 1.41；softmax 后约为 0.20 和 0.80。位置 1 能看见位置 0 和自己，所以不需要遮挡。

   </details>

2. 如果把因果掩码去掉再训练，训练损失会怎样？为什么这样训练出的模型不能用来生成？

   <details><summary>参考答案</summary>

   训练损失会降得很低，因为每个位置能直接看到下一个字，答案就在输入里。生成时下一个字还不存在，模型从没学过只靠前文预测，所以生成会失败。

   </details>

3. `[B, T, D] = [2, 10, 64]`、8 个头时，拆头之后 Q 的形状是什么？每个头的分数矩阵是多大？

   <details><summary>参考答案</summary>

   `[2, 8, 10, 8]`；每个头的分数矩阵是 `10 × 10`，一共有 `2 × 8` 张。

   </details>

4. 对照实验里，去掉注意力的模型为什么还能写出“绿树”“村边”这样的词？它缺的是什么？

   <details><summary>参考答案</summary>

   每个位置仍然知道当前这个字，可以学到“这个字后面常跟哪个字”，所以两个字一组看起来通顺。它缺的是前文：不知道这句已经写了几个字、前面写了什么，所以节奏和语义都乱了。

   </details>

5. 上下文从 4000 增加到 32000，每个头的分数矩阵变大多少倍？FlashAttention 解决了其中哪一部分？

   <details><summary>参考答案</summary>

   $8^2=64$ 倍。FlashAttention 分块计算、不把整张表存下来，解决的是内存；计算量仍然随 $T^2$ 增长。

   </details>

## 参考资料

- [Attention Is All You Need，Vaswani 等，2017](https://arxiv.org/abs/1706.03762)
- [PyTorch `scaled_dot_product_attention`](https://docs.pytorch.org/docs/stable/generated/torch.nn.functional.scaled_dot_product_attention.html)
- [FlashAttention，Dao 等，2022](https://arxiv.org/abs/2205.14135)
- [GQA，Ainslie 等，2023](https://arxiv.org/abs/2305.13245)
- [Query-Key Normalization for Transformers，Henry 等，2020](https://aclanthology.org/2020.findings-emnlp.379/) · [OlmPool 架构研究](https://allenai.org/papers/olmpool) · [Qwen3 技术报告](https://arxiv.org/abs/2505.09388)

注意力本身只看“谁和谁匹配”，不看先后：把输入的顺序打乱，每个位置取回的信息不会变，模型分不出“我在学习”和“学习在我”。下一章讲怎样把位置信息放进去，[第 6 章：位置表示](./position-encoding.md)（规划中）；已完成的下一章是[第 7 章：激活函数与门控前馈层](./activations-and-ffn.md)。
