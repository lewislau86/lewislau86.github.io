---
title: "第 28 章：注意力内核与算子融合"
description: "同一个注意力，换一种写法就少存、少搬：用一个挂在 PyTorch 算子分发上的记账员量出朴素注意力的 T×T 分数表要占多少、搬多少；手写 online softmax 和分块注意力，与 scaled_dot_product_attention 对齐到浮点舍入；再看反向为什么只存每行一个数，以及 torch.compile 把一层里的 37 个算子融合成了什么。"
pageClass: tinyllm-course
---

# 第 28 章：注意力内核与算子融合

[课程总览](./index.md) · [上一章](./inference-efficiency.md) · [下一章](./quantization.md)

::: tip 本章学习目标
能算出朴素注意力的 $T\times T$ 分数表要占多少内存、被读写几遍；能手写 online softmax 和分块注意力，并验证它们与 `F.scaled_dot_product_attention` 的结果只差浮点舍入；能说清块大小怎样决定 K、V 被重读的次数，以及它为什么受片上存储限制；能解释反向传播为什么只需要每行一个 lse；能用读写字节数说明算子融合省下的是什么。

**前置：** [第 6 章](./self-attention.md)的缩放点积注意力与因果掩码，[第 12 章](./tinyllm-model.md)的基线模型，[第 27 章](./inference-efficiency.md)的“带宽决定速度”。

**实践方式：** [attention-kernels.ipynb](/tinyllm/notebooks/attention-kernels)（也可以直接运行 <a href="/tinyllm/code/attention-kernels.py" download>attention-kernels.py</a>），CPU 约一分钟，需要 PyTorch 和 `tokenizers`；第 7 节的 `torch.compile` 还需要一个 C++ 编译器，没有时那一段会跳过。
:::

<TinyLLMMap active="attention-kernels" />

## 问题：同样的计算，搬多少数据

[第 27 章](./inference-efficiency.md)用 KV cache 去掉了重复计算，还看到 decode 慢在“每做一点计算就要读一遍权重”：速度常常不由算了多少决定，而由搬了多少决定。本章把同一个观察用在一次前向的内部。

[第 6 章](./self-attention.md)的注意力写法很直接：算出 $T\times T$ 的分数表，盖掩码，softmax，再乘 V。每一步都把结果完整地写进内存，下一步再读出来。长度 4096 时，这样的一张表在一个头上就有 1600 多万个数。这些数真的有必要全部写下来吗？

本章不比快慢。快慢取决于硬件，在 CPU 上测出来的结论搬不到 GPU 上去。本章只数两样与硬件无关的量：<strong>峰值时同时要存多少字节</strong>，以及<strong>一共要从内存读写多少字节</strong>。朴素写法、手写的分块写法、PyTorch 的 `scaled_dot_product_attention`（下面简称 SDPA）三者先对齐数值，再比这两样。

::: info 本章代码从哪里来
本章所有代码都在一个文件里：<a href="/tinyllm/code/attention-kernels.py" download>attention-kernels.py</a>（[在 GitHub 上查看](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/tinyllm/code/attention-kernels.py)）。下面的代码块都是从这个文件里直接截取的片段，所以单独复制一段可能缺少 `import` 或前面定义的变量；想自己运行，请下载完整文件，`python attention-kernels.py` 从头跑到尾即可。notebook 版本也由同一个文件生成，可以[在线查看](/tinyllm/notebooks/attention-kernels)，或[在 Colab 中直接运行](https://colab.research.google.com/github/lewislau86/lewislau86.github.io/blob/master/docs/public/tinyllm/notebooks/attention-kernels.ipynb)。正文引用的输出来自 torch 2.14.1+cpu、tokenizers 0.23.3，单线程运行。
:::

## 1. 研究对象：第 12 章的基线模型

和第 27 章一样，按[第 12 章](./tinyllm-model.md)的配置训练 300 步（d=128、4 层、4 个头、每头 32 维、上下文 64）。只改了一处：每层的注意力调用全局变量 `ATTN` 指向的函数，后面可以把它换成自己写的版本。

<<< @/public/tinyllm/code/attention-kernels.py#train

```text
训练 300 步，最后一步的训练损失 5.488
```

再取 4 段验证文本，拿出第 0 层算出来的真实 Q、K、V，后面的数值对比都用它们：

<<< @/public/tinyllm/code/attention-kernels.py#capture

```text
第 0 层的 Q、K、V：形状 (4, 4, 64, 32)，即 [batch, 头, 位置, 每头维度]
```

## 2. 朴素注意力：先把整张分数表写出来

这是第 6 章的写法，只是把每一步拆开写：

<<< @/public/tinyllm/code/attention-kernels.py#naive

```text
朴素写法与 F.scaled_dot_product_attention 的最大误差：4.8e-07
```

两者算的是同一个东西。区别在过程：朴素写法每一步都产生一个完整的张量。为了看清楚，下面写一个“记账员”。它挂在 PyTorch 的算子分发机制上（`TorchDispatchMode`），每执行一个底层的 aten 算子，就记下读了多少字节、写了多少字节，同时跟踪此刻还活着的中间张量一共占多少字节、最高到过多少。transpose、view 这类只改变“怎么看”、不搬数据的操作不记读写。

<<< @/public/tinyllm/code/attention-kernels.py#tracker

它的口径是“每个算子都从内存读输入、把输出写回内存”。这正是 eager 模式下算子之间交接数据的方式；算子内部怎么用缓存，它看不见。先在真实的 Q、K、V 上看一遍：

<<< @/public/tinyllm/code/attention-kernels.py#ledger-naive

```text
  bmm            读   256.0 KiB   写   256.0 KiB
  div            读   256.0 KiB   写   256.0 KiB
  ones           读     0.0 KiB   写     4.0 KiB
  triu           读     4.0 KiB   写     4.0 KiB
  masked_fill    读   260.0 KiB   写   256.0 KiB
  _softmax       读   256.0 KiB   写   256.0 KiB
  clone          读   128.0 KiB   写   128.0 KiB
  bmm            读   384.0 KiB   写   128.0 KiB
合计读写 2832.0 KiB；中间张量峰值 1412.0 KiB；一张 [B,H,T,T] 分数表 256.0 KiB
F.scaled_dot_product_attention 在 CPU 上调用的算子： ['_scaled_dot_product_flash_attention_for_cpu']
```

逐行看：第一个 `bmm` 写出分数表（256 KiB），`div` 读一遍再写一遍，`masked_fill` 又读写一遍，`_softmax` 再读写一遍，最后的 `bmm` 把它读进来乘 V。那张 256 KiB 的表前后被写了 4 次、读了 4 次。合计 2832 KiB 的读写里，Q、K、V 和输出本身占不到三成。

SDPA 在 CPU 上只调用了一个算子，名字里就写着 flash attention：PyTorch 把整个注意力交给了一个专门的内核。

这张表按长度的平方增长。同样 batch 1、4 个头、每头 32 维，把长度从 256 加到 4096：

<<< @/public/tinyllm/code/attention-kernels.py#memory-scaling

```text
T=  256：朴素峰值     2.56 MiB（一张表   1.00 MiB）   SDPA 峰值  0.13 MiB   朴素读写      8.8 MiB
T= 1024：朴素峰值    35.00 MiB（一张表  16.00 MiB）   SDPA 峰值  0.52 MiB   朴素读写    134.0 MiB
T= 4096：朴素峰值   536.00 MiB（一张表 256.00 MiB）   SDPA 峰值  2.06 MiB   朴素读写   2120.0 MiB
```

长度每翻 4 倍，朴素写法的峰值翻 16 倍，峰值时同时活着两张表（`div` 的输入和输出）和一张布尔掩码；SDPA 只翻 4 倍，2.06 MiB 里 2 MiB 是输出本身，剩下的是每行一个数（第 6 节讲它是什么）。在真实的大模型上，一张卡上的 batch 和头数要大得多：32 个头、长度 8192 时，一张 FP16 的分数表就是 4 GiB，而且每一层都要来一遍。

那张表在 SDPA 里并不是消失了，而是从来没有完整地出现过。下面亲手写一个不需要整张表的版本。

## 3. online softmax：不看完整行也能算对

把整张表写出来，是因为 softmax 似乎必须先看到一整行：要知道最大值（减掉它，防止 $e^s$ 溢出）和总和（做分母）。可是这两样都可以边走边算。

设已经看过的分数里最大值是 $m$，以它为基准的指数和是 $\ell=\sum e^{s_i-m}$，加权和是 $o=\sum e^{s_i-m}v_i$。新来一块分数，最大值可能变大成 $m'$。旧的指数和与加权和都是以 $m$ 为基准算的，换到新基准只要乘一个校正系数：

$$
e^{s_i-m'} = e^{s_i-m}\cdot e^{m-m'},\qquad \ell' = e^{m-m'}\,\ell + \sum_{\text{新块}} e^{s_j-m'},\qquad o' = e^{m-m'}\,o + \sum_{\text{新块}} e^{s_j-m'}v_j .
$$

全部走完以后，输出就是 $o/\ell$。用第 0 层、第 0 句、第 0 个头的最后一个位置试一下：它能看到全部 64 个位置，分 4 块、每块 16 个依次送进来。

<<< @/public/tinyllm/code/attention-kernels.py#online-softmax

```text
第  0–15 个分数：本块最大  1.112  目前最大 m= 1.112  校正系数 0.000  ℓ=  5.721
第 16–31 个分数：本块最大  0.776  目前最大 m= 1.112  校正系数 1.000  ℓ= 10.515
第 32–47 个分数：本块最大  1.267  目前最大 m= 1.267  校正系数 0.856  ℓ= 14.434
第 48–63 个分数：本块最大  2.176  目前最大 m= 2.176  校正系数 0.403  ℓ=  9.421
online 结果与先算完整 softmax 再加权的最大误差：6.0e-08
```

![online softmax 的更新过程：一行 64 个分数分 4 块到来，每块之后更新目前最大值 m、校正系数和指数和 ℓ；第三、四块出现了更大的分数，旧的指数和要乘以小于 1 的校正系数](/tinyllm/figures/kernels-online.svg)

怎么读这张表：第一块之前什么都没有，校正系数是 0。第二块的最大值 0.776 没超过 1.112，基准不变，校正系数是 1，$\ell$ 只是往上加。第三、四块各出现了一次更大的分数，旧的 $\ell$ 分别乘上 0.856 和 0.403 再加新的部分，所以最后一块之后 $\ell$ 反而变小了：它是以更大的 $m$ 为基准的。最后的误差 6.0e-08 只是浮点舍入。

这个算法本身并不新：[Milakov 与 Gimelshein（2018）](https://arxiv.org/abs/1805.02867)把它用于单遍计算 softmax，[Rabe 与 Staats（2021）](https://arxiv.org/abs/2112.05682)用它说明注意力不需要 $O(T^2)$ 的内存，[FlashAttention](https://arxiv.org/abs/2205.14135) 把它和 GPU 上的分块结合起来。

## 4. 分块注意力：把 online softmax 用到每一行

一行能分块，所有行就能一起分块：把 Q 按行切成块，每个 Q 块依次和 K、V 的各块相遇，每次只算一个“Q 块 × K 块”的小方块分数，用上一节的公式更新这些行的 $m$、$\ell$、$o$。因果掩码让对角线右上方的整块完全不用算，直接跳过。

<<< @/public/tinyllm/code/attention-kernels.py#tiled

函数里的 `stats` 记两件事：算了几个方块、跳过几个，以及从“主存”读进了多少字节（每个 Q 块读一次，每个方块读一个 K 块和一个 V 块），写回了多少字节（每个 Q 块的输出和每行一个 lse）。先核对结果：

<<< @/public/tinyllm/code/attention-kernels.py#tiled-check

```text
分块（16×16）与朴素写法的最大误差：8.9e-07
分块（16×16）与 SDPA 的最大误差：  9.2e-07
64 个位置切成 4×4 = 16 个方块，算了 10 个，跳过 6 个（整块都在未来）
```

![分块注意力的计算顺序：左边 4×4 个方块，因果掩码跳过右上方 6 块，对角线上的块只算左下半；右边是一行 Q 块的处理过程，Q 块常驻片上，K、V 块依次读进来，只把输出和 lse 写回主存](/tinyllm/figures/kernels-tiling.svg)

怎么读这张图：左边每个方块就是一次 `s = qi @ kj.T`，只有 16×16 个分数。对角线上的方块一半在未来，靠 `masked_fill` 盖掉；对角线右上方的 6 块整块都在未来，连乘法都不做。右边是一行 Q 块的旅程：Q 块和这些行的 $m$、$\ell$、$o$ 一直留在片上，K、V 的块一个接一个读进来，分数块用完就扔，最后只把输出和 lse 写回去。

把它放回整个模型，4 层注意力全部换成分块版本（以及朴素版本），在 8 段验证文本上算损失：

<<< @/public/tinyllm/code/attention-kernels.py#swap

```text
朴素     验证损失 5.559044，与 SDPA（5.559043）相差 4.8e-07
分块 16  验证损失 5.559043，与 SDPA（5.559043）相差 0.0e+00
```

三种写法给出同一个模型。分块版本和 SDPA 的损失差在打印精度下是 0，朴素写法差 4.8e-07：不同的求和顺序带来不同的舍入，大小在 FP32 的精度范围内。

## 5. 数一数：分块少搬了多少字节

分块不是没有代价。每个 Q 块都要把它左边的 K、V 块重新读一遍：块越小，Q 块越多，K、V 被重读得越多。块也不能无限大：一个方块连同它的 Q、K、V 块和累加器，要能一起放进片上的快速存储。把分块版本实际读写的字节数和记账员记下的朴素写法放在一起，每种块大小都顺便和 SDPA 核对一遍结果：

<<< @/public/tinyllm/code/attention-kernels.py#traffic

```text
T=  256  朴素     8.8 MiB   块  16:    2.4 MiB   块  64:    0.9 MiB   块 256:    0.5 MiB
T= 1024  朴素   134.0 MiB   块  16:   33.5 MiB   块  64:    9.5 MiB   块 256:    3.5 MiB
T= 4096  朴素  2120.0 MiB   块  16:  518.1 MiB   块  64:  134.1 MiB   块 256:   38.1 MiB
一个方块同时要放在片上的数据（Q、K、V 块 + 分数块 + 累加器，FP32、每头 32 维）： 块 16: 9 KiB，块 64: 48 KiB，块 256: 384 KiB
```

![左：朴素注意力与 SDPA 的中间张量峰值随序列长度变化；右：朴素写法与三种块大小的分块写法的读写字节数，块越大读写越少](/tinyllm/figures/kernels-memory.svg)

怎么读这张图：右边四条线的斜率一样，都随 $T^2$ 增长，差别在系数上。

- 朴素写法的系数来自那几张 $T\times T$ 的表：每个头每个位置对，要读写 8 次多（T=4096 时 2120 MiB，而 4 个头的一张表是 256 MiB）。
- 分块写法的读写大头是 K、V 的重读。T 个位置切成 $T/B$ 个 Q 块，每个 Q 块平均要读一半的 K 和 V，合计约 $T^2 d / B$ 个数，$d$ 是每头维度、$B$ 是块大小。T=4096、块 64 时就是 134 MiB，和打印的数对得上。



“片上存储”在 GPU 上指的是下面这一层：

![GPU 的存储层次（H100 SXM）：HBM 显存 80 GB、约 3.35 TB/s；L2 缓存 50 MB；每个 SM 的共享内存最多 228 KB，共 132 个 SM；寄存器每个 SM 256 KB](/tinyllm/figures/gpu-memory-hierarchy.svg)

怎么读这张图：从上往下越来越小、越来越快。权重、KV cache、激活都放在最上面的 HBM 里；分块内核把一个方块的 Q、K、V 和累加器搬进第三层的共享内存，在那里算完再把输出写回 HBM。朴素写法的 $T\times T$ 表放不进共享内存，只能在 HBM 里来回读写。

所以块越大越省：块 16、64、256 的读写分别是朴素写法的约四分之一、十六分之一、五十六分之一。可块 256 要在片上同时放下 384 KiB，超过了 GPU 上单个计算单元（SM）的共享内存：[A100 每个 SM 最多 164 KB](https://docs.nvidia.com/cuda/ampere-tuning-guide/index.html)，[H100 最多 228 KB](https://docs.nvidia.com/cuda/hopper-tuning-guide/index.html)。FlashAttention 的块大小就是按这个容量、每头维度和数据类型定下来的，[论文](https://arxiv.org/abs/2205.14135)把这笔账写成“读写量随共享内存容量 $M$ 增大而减少”。

左边的峰值也一样：SDPA 那条线是一次方增长，因为它只存输出和每行一个数。

## 6. 训练时：反向传播不存那张表

上面都是前向。训练时，自动求导还要为反向传播保存一些中间结果。朴素写法的 softmax 会把它的输出 $P$（一张 $T\times T$ 的表）存下来；分块版本每行只多留一个数，就是前向最后算出的

$$
\text{lse} = m + \log \ell = \log \sum_j e^{s_j}.
$$

反向需要 $P$ 时，用 $P = e^{QK^\top/\sqrt d - \text{lse}}$ 当场重算一块就够了。先验证这个式子：

<<< @/public/tinyllm/code/attention-kernels.py#recompute

```text
用 lse 重算的 P 与存下来的 P 最大误差：2.3e-06
要存的量：P 是 65,536 个数，lse 是 1,024 个数
```

再直接量一量：让 PyTorch 在保存反向所需张量时告诉我们存了多少字节（`saved_tensors_hooks`），长度 1024 下比较朴素写法和 SDPA，并核对两者的梯度：

<<< @/public/tinyllm/code/attention-kernels.py#saved

```text
朴素   为反向保存  18.50 MiB
SDPA 为反向保存   2.02 MiB
Q、K、V 梯度的最大差（相对于梯度最大值）：1.4e-06；一张 [1,4,1024,1024] 的表是 16 MiB
```

朴素写法存下了 softmax 的输出 $P$ 这一整张表（16 MiB），外加一张布尔掩码和 Q、K、V；SDPA 只存 Q、K、V、输出和每行一个 lse，梯度和朴素写法在浮点舍入范围内一致。反向多算一遍矩阵乘，换来不存一张随长度平方增长的表。这和[第 24 章](./large-model-stability.md)的激活重计算是同一笔交易，只是做在了一个算子内部。

## 7. 算子融合：其余的小算子

注意力之外，每层还有一串逐元素的小运算：RMSNorm、RoPE、SiLU 门控。它们的计算量很小，但在 eager 模式下每个运算都是一个独立的算子，读一遍输入、写一遍输出，下一个再读回来。用记账员数一数它们实际读写的字节，和“输入只读一遍、输出只写一遍”的下限比一比：

<<< @/public/tinyllm/code/attention-kernels.py#fusion-ledger

```text
RMSNorm  6 个算子 ['pow', 'mean', 'add_', 'rsqrt', 'mul', 'mul']
         读写  7.05 MiB，下限  2.00 MiB，多搬 3.5 倍
RoPE     7 个算子 ['mul', 'mul', 'sub', 'mul', 'mul', 'add', 'stack']
         读写  9.02 MiB，下限  2.00 MiB，多搬 4.5 倍
SiLU 门控  2 个算子 ['silu', 'mul']
         读写 13.32 MiB，下限  7.99 MiB，多搬 1.7 倍
```

`nn.RMSNorm` 在 CPU 上拆成了 6 个算子：平方、求均值、加 eps、开方倒数、两次乘法，每一步的中间结果都写进内存。RoPE 把输入拆成奇偶两半，乘、减、加之后再拼回去，7 个算子每一步都把结果写进内存。这些运算每个元素只做几次乘加，时间几乎全花在搬数据上，搬多少倍就大致慢多少倍。

![逐元素小算子的读写：RMSNorm、RoPE、SiLU 门控在 eager 模式下的读写字节，与融合成一个内核后的下限对比](/tinyllm/figures/kernels-fusion.svg)

怎么读这张图：每个算子一组柱子，红柱是 eager 模式下实际读写的字节，绿柱是“输入读一次、输出写一次”的下限，括号里是多搬的倍数。RMSNorm 和 RoPE 由五六个小算子拼成，每一步的中间结果都写回内存，所以多搬三四倍；SiLU 门控只有两个算子，多搬得少。

下限就是融合以后能做到的：把一串逐元素运算写进同一个循环，每个元素读进来、在寄存器里算完、写出去一次。`torch.compile` 会自动做这件事：它把 Python 代码追踪成计算图，再为能合并的运算生成一个内核（CPU 上是 C++ 循环，GPU 上是 Triton 内核）。看它为一整层 Block 生成了什么：

<<< @/public/tinyllm/code/attention-kernels.py#compile

```text
eager：一层 Block 调用 37 个非视图算子
compile：生成 6 个融合内核，矩阵乘和注意力仍调用现成的库函数
   cpp_fused__unsafe_view_add_5
   cpp_fused__unsafe_view_add_mean_mul_pow_rsqrt_3
   cpp_fused__unsafe_view_add_mul_slice_split_stack_sub_transpose_view_1
   cpp_fused__unsafe_view_mul_silu_4
   cpp_fused_add_mean_mul_pow_rsqrt_0
   cpp_fused_clone_transpose_2
compile 与 eager 输出的最大误差：3.8e-06
```

融合内核的名字列出了它合并了哪些运算：`add_mean_mul_pow_rsqrt` 是 RMSNorm（第二个还顺带做了注意力之后的残差相加），`mul_slice_split_stack_sub_transpose` 是把 QKV 切开再做 RoPE，`clone_transpose` 是一次调整内存布局的拷贝，`mul_silu` 是 SwiGLU 的门控，最后的 `add` 是前馈层之后的残差。矩阵乘和注意力不在里面，它们本来就各是一个算子，交给现成的库函数（CPU 上是 BLAS 一类的数学库，GPU 上是 cuBLAS 和 FlashAttention 一类的内核）。

内核名字和个数随 PyTorch 版本变化，上面是 2.14.1 的结果。这一节在 CPU 上验证的是“合并了什么、结果是否一致”；合并后快多少，取决于硬件带宽和内核写得好不好，要在 GPU 上按[第 13 章](./gpu-training.md)的方法单独测。

## 8. CPU 上验证了什么，GPU 上还要测什么

这一章在 CPU 上确认了三件事：分块加 online softmax 与朴素写法数值等价；它不需要那张 $T\times T$ 的表，峰值与读写都可以按公式算出来；SDPA 在 CPU 上走的就是这种内核。没有回答的是“快多少”。原因有两个：

- 我们手写的分块版本是 Python 循环，每个方块要经过好几次算子调用，比一次大矩阵乘慢得多。它是用来看懂算法的，不是用来跑的。
- 速度来自片上存储、线程排布和指令级的细节，这些在 GPU 上才成立。[FlashAttention](https://arxiv.org/abs/2205.14135) 论文报告 GPT-2（长度 1K）训练端到端快了约 3 倍；后来的 [FlashAttention-2](https://arxiv.org/abs/2307.08691) 改进了线程之间的分工，[FlashAttention-3](https://arxiv.org/abs/2407.08608) 利用 H100 的异步执行和 FP8。这些数字都依赖具体的 GPU 和形状。

在 GPU 上验证时，可以用 `torch.nn.attention.sdpa_kernel` 指定 SDPA 只用某一种后端（FlashAttention、memory-efficient 或数学实现），在相同的 batch、长度和精度下各测一次，先预热、排除首次编译，再报告墙钟时间与峰值显存（`torch.cuda.max_memory_allocated`）。PyTorch 选不到 FlashAttention 后端时（比如传了它不支持的掩码形状或数据类型），会悄悄退回别的实现，所以要确认实际走的是哪一个。

## 动手实验

1. **块大小与重读次数。** 在第 5 节的循环里加上块 32 和块 128，验证 K、V 的读写约等于 $T^2 d/B$。再把每头维度从 32 改成 128（Llama 的常见值），块 64 时片上要放多少 KiB？还能放进 A100 的一个 SM 吗？
2. **不同长度的 Q 和 K。** decode 时 Q 只有 1 行，K、V 有 $T$ 行。用 `tiled_attention` 的思路写一个 `q.shape[2] == 1` 的版本（因果掩码可以去掉），和 SDPA 对齐。这时分块还能省下什么？提示：没有 $T\times T$ 的表可省，[第 32 章](./kv-memory.md)的分页 KV cache 解决的是另一件事。
3. **融合的边界。** 把 RMSNorm 和它后面的 `qkv` 矩阵乘一起交给 `torch.compile`，看生成的代码里 RMSNorm 有没有被并进矩阵乘。为什么逐元素运算容易融合，而矩阵乘通常不和它们并在一起？

<!-- real-model:start -->

## 在真实模型里

transformers 里的注意力层不自己写 softmax，而是按配置把 Q、K、V 交给某个注意力实现；默认就是本章用的 SDPA。下表的链接都指向 Hugging Face transformers 的固定版本 `v5.21`，精确到行。读代码时可以先跳过缓存、掩码、并行这些工程细节，只看和本章对应的那几行。

| 本章的零件 | 真实代码 | 对照要点 |
| --- | --- | --- |
| 选择注意力实现 | [`modeling_llama.py 第 253 行`](https://github.com/huggingface/transformers/blob/v5.21/src/transformers/models/llama/modeling_llama.py#L253) | 按 `config._attn_implementation`（`eager`、`sdpa`、`flash_attention_2` 等）挑一个函数，找不到时退回朴素写法；注意力层本身不关心用的是哪种内核 |
| 朴素写法 | [`eager_attention_forward`](https://github.com/huggingface/transformers/blob/v5.21/src/transformers/models/llama/modeling_llama.py#L180-L202) | 先算出完整的分数矩阵、加掩码、softmax、再乘 V，和本章 `naive_attention` 一样，会写出整张 T×T 的表 |
| SDPA | [`sdpa_attention_forward`](https://github.com/huggingface/transformers/blob/v5.21/src/transformers/integrations/sdpa_attention.py#L80-L186) | 整理形状和掩码后调用 `torch.nn.functional.scaled_dot_product_attention`，由 PyTorch 选分块内核 |
| FlashAttention | [`flash_attention_forward`](https://github.com/huggingface/transformers/blob/v5.21/src/transformers/integrations/flash_attention.py#L27-L110) | 调用 flash-attn 库的 GPU 内核；需要单独安装，只支持部分 GPU 和数据类型 |

想在本机看源码，可以先 `pip install transformers`，再用 `python -m inspect transformers.models.llama.modeling_llama:LlamaMLP` 这样的命令打印出任意一个类。

<!-- real-model:end -->

## 本章结论：TinyLLM 的选择 {#tinyllm-choice}

TinyLLM 的注意力在训练和推理里都调用 `F.scaled_dot_product_attention`，让 PyTorch 去选 FlashAttention 一类的分块内核；逐元素的小算子交给 `torch.compile` 融合。自己写的朴素版本和分块版本只用于理解和核对：三者在第 0 层的真实 Q、K、V 上误差都在 1e-6 以内，换进整个模型后验证损失的差在 5e-7 以内。

为什么：朴素写法的峰值和读写都由 $T\times T$ 的表决定，长度 4096 时峰值 536 MiB、读写 2120 MiB，而 SDPA 的峰值 2.06 MiB 几乎就是输出本身；训练时它为反向只多存每行一个 lse（长度 1024 时 2.02 MiB 对 18.50 MiB）。分块的读写约为 $T^2 d/B$，块越大越省，块大小的上限由片上存储决定。

什么情况下要换：需要特殊掩码（比如文档内掩码、滑动窗口、[第 3 章](./architecture-evolution.md)的混合注意力）而 SDPA 不支持时，可以用 PyTorch 的 FlexAttention 一类可编程内核，或回到数学实现，先用本章的方法核对结果，再在 GPU 上测速度和显存。在 GPU 上比较内核时，固定后端、形状和精度，先预热，再报告墙钟时间与峰值显存。

::: warning 常见误区
- **FlashAttention 是一种近似注意力。** 它和朴素写法算的是同一个数学结果，差别只在求和顺序带来的舍入（本章在 1e-6 量级）。省下的是内存与读写，不是计算精度。
- **分块减少了计算量。** 乘法次数基本不变（因果掩码下整块跳过能省一部分，但不是主要收益）。省下的是 $T\times T$ 表的存储和反复读写。
- **块越大越好。** 读写确实随块变大而减少，但方块必须放进片上存储；放不下时要么溢出到慢速内存，要么根本无法运行。
- **CPU 上测出 SDPA 更快，就说明 FlashAttention 在 GPU 上也快这么多。** 两边的内存层次、并行方式完全不同，速度结论要在目标硬件上测。
- **算子融合减少了计算。** 融合减少的是中间结果的读写和内核启动次数；每个元素上的乘加一次不少。
:::

## 检查理解

1. 32 个头、长度 8192、FP16，朴素注意力的一张分数表有多大？如果 softmax 的输出还要为反向存一份，一个 32 层的模型一次前向要存多少？

   <details><summary>参考答案</summary>

   一张表 $32 \times 8192 \times 8192 \times 2$ 字节 $= 4\ \text{GiB}$（batch 为 1）。每层存一份 $P$，32 层就是 128 GiB，比大多数单卡的显存都大。分块内核每层只存每行一个 lse：$32 \times 8192 \times 4$ 字节 $= 1\ \text{MiB}$（lse 一般用 FP32 存）。这就是长上下文训练离不开 FlashAttention 一类内核的原因。

   </details>

2. 第 3 节最后一块之后，$\ell$ 从 14.434 变成了 9.421，加了 16 个正数却变小了。为什么这不是错的？

   <details><summary>参考答案</summary>

   $\ell$ 是以当前最大值 $m$ 为基准的指数和 $\sum e^{s_i - m}$。最后一块把 $m$ 从 1.267 提高到 2.176，旧的 $\ell$ 要乘以校正系数 $e^{1.267-2.176} \approx 0.403$，变成约 5.82，再加上新块的部分。换算到同一个基准，总和其实是增加的。最后输出是 $o/\ell$，$o$ 也乘了同样的系数，所以基准的选择不影响结果。

   </details>

3. 分块写法的读写约为 $T^2 d / B$。为什么每头维度 $d$ 越大，分块相对朴素写法的优势越小？FlashAttention 在 $d=128$ 时通常怎样取块大小？

   <details><summary>参考答案</summary>

   朴素写法的读写主要是那几张 $T\times T$ 的表，与 $d$ 无关；分块写法的读写是重读 K、V，每次读 $d$ 维，所以和 $d$ 成正比，优势约为“几倍 × $B/d$”。$d$ 越大，同样的块大小省得越少；而 $d$ 大时，一个块的 Q、K、V 也更占片上空间，块又不能取得太大。实际内核会按共享内存容量、$d$ 和数据类型折中，比如 $d=128$、FP16 时取几十到一百多行一块，具体值由内核作者针对每种 GPU 调好。

   </details>

## 参考资料

- [FlashAttention：IO 感知的精确注意力，Dao 等，2022](https://arxiv.org/abs/2205.14135) · [FlashAttention-2，Dao，2023](https://arxiv.org/abs/2307.08691) · [FlashAttention-3，Shah 等，2024](https://arxiv.org/abs/2407.08608)
- [Online normalizer calculation for softmax，Milakov 与 Gimelshein，2018](https://arxiv.org/abs/1805.02867) · [Self-attention does not need O(n²) memory，Rabe 与 Staats，2021](https://arxiv.org/abs/2112.05682)
- [PyTorch：scaled_dot_product_attention](https://docs.pytorch.org/docs/stable/generated/torch.nn.functional.scaled_dot_product_attention.html) · [torch.compile 入门](https://docs.pytorch.org/tutorials/intermediate/torch_compile_tutorial.html)
- [NVIDIA Ampere 调优指南（共享内存容量）](https://docs.nvidia.com/cuda/ampere-tuning-guide/index.html) · [Hopper 调优指南](https://docs.nvidia.com/cuda/hopper-tuning-guide/index.html)

注意力的读写省下来了，可模型的权重和 KV cache 本身还是那么大：每个数用 32 位或 16 位存。下一章把每个数变短：[第 29 章：量化](./quantization.md)。
