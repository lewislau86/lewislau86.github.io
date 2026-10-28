---
title: "第 7 章：位置表示"
description: "注意力本身分不出先后。可学习绝对位置、正弦编码、RoPE 三种做法，两个对照实验，以及比训练更长时会发生什么。"
pageClass: tinyllm-course
---

# 第 7 章：位置表示

[课程总览](./index.md) · [上一章](./self-attention.md) · [下一章](./activations-and-ffn.md)

::: tip 本章学习目标
能用代码说明注意力为什么分不出先后；能写出可学习绝对位置、正弦位置编码和 RoPE，并说出各自把位置放在哪里；能解释 RoPE 为什么只依赖相对距离；能读懂两个对照实验：背唐诗时三种做法差不多，一旦任务必须数位置，没有位置就做不成；能说出超过训练长度时 RoPE 会怎样。

**前置：** [第 6 章](./self-attention.md)的因果注意力与多头；[第 1 章](./first-run.md)里的 `pos` 位置表。

**实践方式：** [position-encoding.ipynb](/tinyllm/notebooks/position-encoding)（也可以直接运行 <a href="/tinyllm/code/position-encoding.py" download>position-encoding.py</a>），CPU 约两分钟。
:::

<TinyLLMMap active="position-encoding" />

## 问题：注意力分不出“我在学习”和“在我学习”

[第 6 章](./self-attention.md)的注意力做的是“打分、softmax、加权求和”。分数只取决于两个向量像不像，加权求和也不管谁先谁后。把前面几个字的顺序换一下，最后一个位置取回的东西完全一样。

::: info 本章代码从哪里来
本章所有代码都在一个文件里：<a href="/tinyllm/code/position-encoding.py" download>position-encoding.py</a>（[在 GitHub 上查看](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/tinyllm/code/position-encoding.py)）。下面的代码块都是从这个文件里直接截取的片段，所以单独复制一段可能缺少 `import` 或前面定义的变量；想自己运行，请下载完整文件，`python position-encoding.py` 从头跑到尾即可。notebook 版本也由同一个文件生成，可以[在线查看](/tinyllm/notebooks/position-encoding)，或[在 Colab 中直接运行](https://colab.research.google.com/github/lewislau86/lewislau86.github.io/blob/master/docs/public/tinyllm/notebooks/position-encoding.ipynb)。
:::

<<< @/public/tinyllm/code/position-encoding.py#order-blind

```text
最后一个位置的输出相同吗？ True
```

两句话的最后一个字都是“学习”，它看得见的都是“我、在、学习”这三个字，只是前两个换了位置。注意力给出的结果完全相同。对语言来说这是不能接受的：“狗咬人”和“人咬狗”用的字一样，意思正好相反。

所以要另外告诉模型：**这个字在第几个位置**。下面三种做法，区别在于位置信息放在哪里、用什么形式。

![可学习绝对位置为每个位置查一行可训练向量，加到词向量上，只能处理表里有的位置；正弦位置编码用固定公式算出位置向量再相加，不用训练；RoPE 不加向量，而是在每一层注意力里把 q 和 k 按位置旋转，点积只依赖两者的相对距离](/tinyllm/figures/position-methods.svg)

## 1. 可学习绝对位置：再查一张表

最直接的办法和词嵌入一样：准备一张 `[最大长度, d]` 的表，位置 0 查第 0 行，位置 1 查第 1 行……查出来的向量加到词向量上。[第 1 章](./first-run.md)的模型就是这么做的。

<<< @/public/tinyllm/code/position-encoding.py#learned

```text
加上位置向量后还相同吗？ False
```

“我”在位置 0 和在位置 1 加上的向量不同，进入注意力时已经是两个不同的向量，结果也就不同了。这张表和词嵌入一样随训练更新，模型自己决定每个位置的向量长什么样。GPT-2 用的就是这种做法。

它的问题在表的大小。表只有 24 行，第 25 个位置根本查不到：

<<< @/public/tinyllm/code/position-encoding.py#learned-limit

```text
超过 24 个位置：IndexError: index out of range in self
```

即使把表做大，靠后的那些行只有在训练时真的遇到长文本才会被更新到，否则还是随机初始化的样子。

## 2. 正弦位置编码：用公式算，不用学

2017 年的原始 Transformer 换了个思路：位置向量不学，直接用公式算。第 $i$ 对维度用一个频率 $\omega_i = 10000^{-2i/d}$，位置 $m$ 上这一对的值是 $\sin(m\omega_i)$ 和 $\cos(m\omega_i)$：

<<< @/public/tinyllm/code/position-encoding.py#sinusoidal

```text
(100, 16) 位置 0 的前 4 维: [0.0, 1.0, 0.0, 1.0]
```

可以把每一对维度想成一根指针，位置每往后一格，指针转一个固定角度。前面几对转得快，像秒针；后面的转得很慢，像时针。把所有指针的读数合在一起，每个位置都得到一个独一无二的向量。

![左图是 64 个位置、32 维的正弦位置编码，低维度变化快、高维度变化慢；右图画出三个维度随位置的变化：维度 0 约 6 个位置一圈，维度 8 约 63 个位置一圈，维度 20 变化很慢](/tinyllm/figures/sinusoidal-heatmap.svg)

公式对任何位置都算得出来，不会出现查不到的情况。但它和可学习位置一样，是在输入处加一次：位置信息和词的信息混在同一个向量里，后面每一层都要自己把它们分开。

## 3. RoPE：把位置变成旋转

注意力里真正需要位置的是打分那一步：位置 $m$ 的 $q$ 和位置 $n$ 的 $k$ 点积。多数时候，有用的不是“我在第 37 个位置”，而是“它在我前面 3 个字”。

RoPE（旋转位置编码）就是从这里下手的。它不往输入上加东西，而是在**每一层注意力里**把 $q$ 和 $k$ 旋转一下：每两维看成平面上的一个点，位置 $m$ 就转 $m\theta$ 角。不同的维度对用不同的转速 $\theta_i$，取法和正弦编码相同。

<<< @/public/tinyllm/code/position-encoding.py#rope

为什么转一下就能表示相对位置？两个向量同时转同一个角度，夹角不变，点积也不变。$q$ 转了 $m\theta$，$k$ 转了 $n\theta$，它们之间的夹角只多了 $(m-n)\theta$。所以点积只和相隔的距离 $m-n$ 有关，和它们具体在哪里无关：

$$
\langle R_m q,\; R_n k\rangle = \langle q,\; R_{n-m}\, k\rangle
$$

![左边两幅是同一对二维向量：位置 2 和 0、位置 6 和 4 时 q、k 都被转了不同角度，但两者夹角相同，点积也相同；右图是 64 维随机向量，把 k 放在位置 0、20、60，分数随相隔距离变化的三条曲线完全重合](/tinyllm/figures/rope-rotation.svg)

用代码验证：同一对 $q$、$k$，放在不同的地方，只要相隔一样，分数就一样。

<<< @/public/tinyllm/code/position-encoding.py#rope-relative

```text
(m=3,  n=1)  的分数: 0.3248
(m=13, n=11) 的分数: 0.3248
(m=40, n=38) 的分数: 0.3248
(m=3,  n=0)  的分数: 0.1397
```

自己拖一下更直观。下面用的就是上面代码里那对 8 维的 $q$、$k$：拖动两个滑块改变位置，或者点“保持相隔，一起往后移”，看两根箭头一起转、夹角和分数都不变：

<RopeSlider />

再回到开头的例子。只把 $q$、$k$ 转一下，$v$ 不动，注意力就能分出先后了：

<<< @/public/tinyllm/code/position-encoding.py#rope-order

```text
用 RoPE 之后还相同吗？ False
```

放进模型里，就是在第 6 章的多头注意力里加两行：拆出每个头的 $q$、$k$ 之后、算分数之前，各转一次。每一层、每个头都这样做；词向量本身不再加任何位置向量。

<<< @/public/tinyllm/code/position-encoding.py#pos-attention

## 4. 对照实验一：背唐诗

现在用[第 1 章](./first-run.md)的唐诗和同样的模型，比较三种做法：没有位置、可学习绝对位置、RoPE。先把实验条件固定下来：前 35 首诗训练、最后 4 首只用来验证；用一个单独的随机数发生器预先抽好 400 步的 batch，三个模型第几步就用第几个 batch，随机种子只决定初始参数。评估时不再随机抽样，而是在语料上按固定步长切出所有窗口：

<<< @/public/tinyllm/code/position-encoding.py#poem-data

<<< @/public/tinyllm/code/position-encoding.py#poem-ablation

```text
没有位置：训练集损失 0.159  验证集损失 7.929
可学习绝对位置：训练集损失 0.156  验证集损失 8.294
RoPE：训练集损失 0.153  验证集损失 7.670
```

![左图：唐诗语料上三种做法按同一组 batch 训练 400 步，训练损失几乎一样。右图：输出往前数第 3 个符号的任务，在新生成的测试序列上、3 个种子平均，没有位置时准确率 0.21，可学习绝对位置和 RoPE 都是 1.00；RoPE 在长度 48 上 0.90，长度 96 上 0.46](/tinyllm/figures/position-ablation.svg)

先看训练集：结果有点出人意料，<strong>没有位置的模型也背得一样好</strong>，三个训练损失都在 0.15 左右。开头不是说注意力分不出先后吗？

原因在因果掩码。第 0 个位置只看得见 1 个字，第 10 个位置看得见 11 个字，越往后，取回来的是越多个向量的加权平均。模型能从“平均了多少个东西”里大致猜出自己在哪里，再叠几层就够用了。这种现象有人专门研究过，叫 NoPE（no positional encoding），只对带因果掩码的解码器成立。再加上背诗主要靠“前面出现过哪些字”，对精确的位置要求不高。

再看验证集：三个模型都在 7.7～8.3，比对 556 个字乱猜的 6.32 还差，和第 1 章看到的过拟合一样。几十首诗只够背诵，这个实验只能说明“三种做法都能把训练集背下来”，说明不了谁写诗更好。而且这是单个随机种子的结果，三者之间零点几的差别不该当真。

所以背唐诗这个任务测不出位置表示的作用，需要换一个必须数位置的任务。

## 5. 对照实验二：往前数第 3 个符号

输入一串随机符号（32 种），每个位置要输出“往前数第 3 个”是什么。这个任务和语义完全无关：同样的符号出现在哪里都有可能，模型只能靠位置找到答案。训练数据由一个固定的发生器生成，三种做法看到的是同一串 batch；测试用另外生成的 256 条新序列，训练时一条都没见过。每种做法用 3 个随机种子：

<<< @/public/tinyllm/code/position-encoding.py#offset-task

```text
没有位置：测试准确率 0.210（0.209～0.213）
可学习绝对位置：测试准确率 1.000（1.000～1.000）
RoPE：测试准确率 1.000（1.000～1.000）
```

这次差别非常明显（右图左边三根柱子），3 个种子的结果几乎一样。有位置信息的两种做法都做到了 100%；没有位置的模型只有约 21%，比瞎猜的 1/32 好一点，但远远不够。从“平均了多少个东西”里大致猜出自己在哪，和准确地数出“往前第 3 个”完全是两回事。

## 6. 比训练时更长，RoPE 能直接用吗？

两个实验里，训练时每段都是 24 个位置。可学习绝对位置的表只有 24 行，更长的输入根本跑不了。RoPE 对任何位置都算得出旋转角度，至少能跑起来。效果怎样？位置任务在测试集上看；唐诗只看长度的影响，所以在训练语料上算损失（模型背过的文本），不当作泛化结果：

<<< @/public/tinyllm/code/position-encoding.py#extrapolate

```text
位置任务（测试集），RoPE，长度 24：准确率 1.000（1.000～1.000）
位置任务（测试集），RoPE，长度 48：准确率 0.901（0.859～0.960）
位置任务（测试集），RoPE，长度 96：准确率 0.455（0.433～0.485）
唐诗（训练语料），RoPE，长度 24（训练长度）：损失 0.153
唐诗（训练语料），RoPE，长度 48（训练长度的两倍）：损失 0.269
```

长度翻一倍，位置任务的准确率掉到约 90%（3 个种子在 86%～96% 之间）；翻两倍，只剩约 46%。就连模型背过的唐诗，长度翻倍后损失也从 0.15 涨到 0.27。可是任务要找的始终是“往前第 3 个”，这个距离在训练时见过无数次，为什么还会变差？

问题不在要找的那个字，而在**其他的字**。训练时，一个位置最多只看见前面 23 个字，相隔 24 以上的分数从来没被训练过。长度 96 时，每个位置要给前面几十个“没见过的距离”打分，这些分数没有被约束，其中一些会偏高，从正确答案那里抢走注意力权重。

RoPE 解决的是“能不能算”，不是“算得对不对”。实际的大模型想用更长的上下文，通常有两步：一是调整旋转频率，例如把 base 从 10000 调大（Llama 3 用 500000），或者用 Position Interpolation、YaRN 这类方法把长位置“压缩”回训练见过的角度范围；二是用一些长文本继续训练，让模型真正见过这些距离。宣称支持 128K 上下文的模型，也都是在这么长的数据上训练或微调过的。

<!-- real-model:start -->

## 在真实模型里

RoPE 在真实代码里分成“算角度”和“转 q、k”两步。下表的链接都指向 Hugging Face transformers 的固定版本 `v5.21`，精确到行。读代码时可以先跳过缓存、掩码、并行这些工程细节，只看和本章对应的那几行。

| 本章的零件 | 真实代码 | 对照要点 |
| --- | --- | --- |
| 预先算好每个位置的 cos、sin | [`LlamaRotaryEmbedding`](https://github.com/huggingface/transformers/blob/v5.21/src/transformers/models/llama/modeling_llama.py#L72-L116) | `inv_freq` 就是本章的 θ_i = base^(-2i/d)；base 由配置 `rope_theta` 给出 |
| 把维度分成两半 | [`rotate_half`](https://github.com/huggingface/transformers/blob/v5.21/src/transformers/models/llama/modeling_llama.py#L119-L123) | 把前一半和后一半配成一对，本章是相邻两维配一对；两种都对，但加载权重时必须一致（见本章常见误区） |
| 旋转 q 和 k | [`apply_rotary_pos_emb`](https://github.com/huggingface/transformers/blob/v5.21/src/transformers/models/llama/modeling_llama.py#L127-L149) | 只转 q、k，不转 v，和本章一样 |
| 扩展上下文：YaRN | [`_compute_yarn_parameters`](https://github.com/huggingface/transformers/blob/v5.21/src/transformers/modeling_rope_utils.py#L345-L483) | 本章第 6 节提到的调整旋转频率的方法之一 |

想在本机看源码，可以先 `pip install transformers`，再用 `python -m inspect transformers.models.llama.modeling_llama:LlamaMLP` 这样的命令打印出任意一个类。

<!-- real-model:end -->

## 本章结论：TinyLLM 的选择 {#tinyllm-choice}

TinyLLM 在每一层注意力里对 $q$、$k$ 使用 **RoPE**，不再在输入处加可学习的位置向量；$v$ 不旋转。它让分数只依赖相对距离，不受固定表长的限制，也是目前多数开源解码器模型（Llama、Qwen、DeepSeek 等）的做法。超过训练长度时，RoPE 只保证能运行，不保证效果：上下文要变长，就调整旋转频率并在长文本上继续训练，然后在目标长度上重新评估。[RoFormer 论文](https://arxiv.org/abs/2104.09864)

::: warning 常见误区
- **RoPE 不是加到词向量上的。** 它在每一层注意力里旋转 $q$ 和 $k$，词向量和残差流里都没有位置向量。
- **$v$ 不需要旋转。** 位置只影响“看谁”（打分），不影响“取回什么”。
- **两种实现的维度配对不一样。** 本章把相邻两维 `(0,1)`、`(2,3)`…… 配成一对；Hugging Face 的 Llama 等实现把前一半和后一半配对（`rotate_half`）。两种都对，但加载别人的权重时必须用同一种，否则模型会完全失效。
- **背得出唐诗，不代表位置表示没用。** 带因果掩码的模型能从“看见了几个字”里粗略猜出位置，所以背诗测不出差别；换成必须精确数位置的任务，差别就出来了。另外，训练损失只说明背没背下来，要比较泛化得看验证集。
- **RoPE 不等于“任意长度都能用”。** 本章的模型长度翻倍后，位置任务的准确率就从 100% 掉到约 90%。
:::

## 检查理解

1. 不加任何位置信息，把 `[我, 在, 学习]` 换成 `[在, 我, 学习]`，最后一个位置的注意力输出会变吗？第一个位置呢？

   <details><summary>参考答案</summary>

   最后一个位置不变：它看见的还是同样三个字，加权求和与顺序无关。第一个位置会变：因果掩码让它只看见自己，原来是“我”，现在是“在”，看见的字本身不同了。

   </details>

2. RoPE 里，位置 5 的 $q$ 和位置 2 的 $k$ 的分数，与位置 105 的 $q$ 和位置 102 的 $k$ 的分数相同吗？前提是什么？

   <details><summary>参考答案</summary>

   相同，前提是旋转前的 $q$ 和 $k$ 本身一样。两种情况都相隔 3 个位置，旋转后的夹角只多了同样的 $3\theta$。真实模型里，不同位置的 $q$、$k$ 一般不同，所以分数不同，但位置的影响只通过相隔的距离起作用。

   </details>

3. 正弦位置编码和 RoPE 都用到了 $10000^{-2i/d}$ 这组频率。它们最大的区别是什么？

   <details><summary>参考答案</summary>

   位置信息放的地方不同。正弦编码在输入处加一次，和词的信息混在同一个向量里；RoPE 不加向量，而是在每一层注意力里旋转 $q$、$k$，直接作用在打分上，因此分数只依赖相对距离。

   </details>

4. 对照实验一里，没有位置的模型损失和另外两个差不多。为什么不能据此说“位置表示没用”？

   <details><summary>参考答案</summary>

   因果掩码让第 $t$ 个位置看见 $t+1$ 个字，模型可以从中粗略推断出自己的位置；背诗主要靠前文出现过哪些字，对精确位置要求不高。实验二要求精确地数出“往前第 3 个”，没有位置的模型准确率只有约 21%，有位置的两种都是 100%。

   </details>

5. 训练长度是 24。长度 96 时，RoPE 模型找“往前第 3 个”的准确率为什么会下降？可以怎样改善？

   <details><summary>参考答案</summary>

   相隔 3 的分数没问题，但每个位置还要给相隔 24 以上的字打分，这些距离训练时从未出现，分数没有被约束，会从正确答案那里抢走注意力权重。改善的办法是调整旋转频率（加大 base，或用 Position Interpolation、YaRN），再用更长的数据继续训练。

   </details>

## 参考资料

- [Attention Is All You Need，Vaswani 等，2017](https://arxiv.org/abs/1706.03762)（正弦位置编码）
- [RoFormer: Enhanced Transformer with Rotary Position Embedding，Su 等，2021](https://arxiv.org/abs/2104.09864)
- [Transformer Language Models without Positional Encodings Still Learn Positional Information，Haviv 等，2022](https://arxiv.org/abs/2203.16634) · [The Impact of Positional Encoding on Length Generalization in Transformers，Kazemnejad 等，2023](https://arxiv.org/abs/2305.19466)
- [Extending Context Window of Large Language Models via Positional Interpolation，Chen 等，2023](https://arxiv.org/abs/2306.15595) · [YaRN，Peng 等，2023](https://arxiv.org/abs/2309.00071)

到这里，注意力已经知道“看谁”和“谁在前面”了。可它取回来的只是前面各个位置的加权平均，还需要一个地方对每个位置的信息再加工一次，那就是前馈层。下一章：[第 8 章：激活函数与门控前馈层](./activations-and-ffn.md)。
