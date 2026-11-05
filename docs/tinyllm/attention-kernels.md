---
title: "第 27 章：注意力内核与算子融合"
description: "同一个注意力，为什么换一种写法就快：N×N 分数表的内存账、分块与 online softmax、算子融合，以及这些收益在 CPU 和 GPU 上各自能验证到什么程度。"
pageClass: tinyllm-course
---

# 第 27 章：注意力内核与算子融合

[课程总览](./index.md) · [上一章](./inference-efficiency.md) · [下一章](./quantization.md)

::: info 本章状态：规划中
正文与 notebook 尚未完成。上一章用 KV cache 去掉了重复计算，本章处理另一件事：同样的计算量，内存怎么搬。预计覆盖：

- **先算一笔内存账。** 长度 $T$ 的朴素注意力要写出一张 $T \times T$ 的分数表，再读回来做 softmax、再读一次乘 V。序列翻倍，这张表变成 4 倍；计两者各自搬了多少字节。
- **分块。** 把 Q、K、V 切成能放进片上内存的小块，一次只处理一块；softmax 用 online 形式累加，不需要看到整行分数也能得到正确结果。
- **验证等价。** 用第 12 章的 TinyLLM 注意力做基准，逐一比较朴素写法、分块写法与 `F.scaled_dot_product_attention` 的输出，误差应在浮点舍入的量级。
- **算子融合。** [第 13 章](./gpu-training.md)点名的逐元素小算子（RMSNorm、RoPE、SiLU 门控）为什么要在显存里来回搬，`torch.compile` 融合之后省掉的是什么。
- **边界。** CPU 上能验证的是等价性和“峰值内存少了一张 $T \times T$ 表”；真正的吞吐收益来自 GPU 内核、线程与共享内存的排布，那部分放在[第 13 章](./gpu-training.md)的 GPU 路线里测，不在本章下结论。
:::

<TinyLLMMap active="attention-kernels" />

## 本章主线选择（待实验验证）

主线先写朴素注意力把过程摊开，再写分块加 online softmax 的版本，两者数值对齐后才讨论性能。注意力在前向里仍用 PyTorch 的缩放点积注意力接口，让框架去选 FlashAttention 一类的内核；自己写分块版本是为了看懂它省了什么，不是为了替换它。核算指标以“峰值要存多少元素”和“读写多少字节”为主——这两个量与硬件无关，CPU 上也能测出来；墙钟时间和吞吐只在标注了 GPU 型号与 batch 的条件下报告，且要先预热、排除首次编译。

这条路线解决的是<strong>单个算子内部的效率</strong>。请求之间怎样排队见[第 30 章](./batching.md)，缓存怎样分配见[第 31 章](./kv-memory.md)，两者和内核优化不互相替代。
