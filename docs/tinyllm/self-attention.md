---
title: "第 9 章：自注意力"
description: "Q/K/V、缩放点积、因果 mask、多头注意力；以及控制注意力分数尺度的 QK Norm。"
pageClass: tinyllm-course
---

# 第 9 章：自注意力

[课程总览](./index.md) · [上一章](./position-encoding.md) · [下一章](./transformer-block.md)

::: info 本章状态：规划中
正文与 notebook 尚未完成。计划覆盖 Q/K/V、缩放点积、因果 mask、多头注意力、张量转置与形状核对。下面的 QK Norm 一节已经成文（从原归一化章节移入），可以先读。
:::

<TinyLLMMap active="self-attention" />

## 本章主线选择（待实验验证）

先实现带**因果掩码的缩放点积多头注意力（MHA）**，核对 Q/K/V 形状、mask 和 softmax；模型需要更低 KV cache 占用时，再用较少的 KV 头改成 **GQA**，并保持相同训练和评估口径。GQA 是推理内存与质量之间的权衡，不能只看头数判断优劣。[GQA 论文](https://arxiv.org/abs/2305.13245)

## QK Norm：控制注意力分数的尺度 {#qk-norm}

### 要解决的问题

注意力分数由 Q 与 K 的点积得到，再经过 softmax 变成权重。如果 Q、K 的长度在训练中越变越大，点积也会跟着变大，softmax 就会“饱和”：某一个 key 的权重接近 1，其余接近 0，梯度也随之变得极小或剧烈波动。QK Norm 在点积**之前**分别把 Q、K 的尺度控制住。

它和[第 4 章](./normalization.md)的 RMSNorm 管的是不同的地方：RMSNorm 处理进入子层前的隐藏状态，QK Norm 处理注意力**内部**的 Q 和 K。两者可以同时存在，Qwen3、Gemma 3、OLMo 2 都是这样做的。

### 原始做法：逐头 L2 归一化

[原始 QKNorm 论文](https://aclanthology.org/2020.findings-emnlp.379/)把每个头的 q、k 都除以自己的 L2 长度，再乘一个可学习尺度 $g$，代替固定的 $1/\sqrt{d_k}$：

$$
\widehat q=\frac{q}{\|q\|_2+\epsilon},\qquad
\widehat k=\frac{k}{\|k\|_2+\epsilon},\qquad
s(q,k)=g\,\widehat q^{\mathsf T}\widehat k
$$

归一化后，点积就是两个单位向量的夹角余弦，取值在 $[-1,1]$，再由 $g$ 决定整体幅度。

```python
# q, k, v: [batch, heads, seq, head_dim]；g 是模型里注册的可学习标量
q_unit = F.normalize(q, p=2, dim=-1, eps=1e-6)   # 一定写 dim=-1：每个头的 head_dim
k_unit = F.normalize(k, p=2, dim=-1, eps=1e-6)
out = F.scaled_dot_product_attention(
    q_unit * g,     # scale 参数不接受 Parameter，所以把 g 先乘到 q 上
    k_unit, v,
    is_causal=True,
    scale=1.0,      # 关掉默认的 1/sqrt(head_dim)，避免重复缩放
)
```

### 现代模型的两种粒度

今天的公开模型多用 RMSNorm 而不是 L2，并且有两种统计范围：

| 粒度 | 在哪一维求 RMS | 公开模型例子 |
| --- | --- | --- |
| 整层（layerwise） | 拆头之前，对每个 token 的整条 Q 或 K 投影 | [OLMo 2、OLMo 3](https://allenai.org/papers/olmpool) |
| 逐头（headwise） | 拆头之后，对每个头的 `head_dim` | [Qwen 3、Gemma 3、Marin 32B](https://allenai.org/papers/olmpool) |

逐头版本可在拆头后用 `nn.RMSNorm(head_dim)` 分别处理 q、k；整层版本要在拆头前对完整投影宽度做 RMSNorm。两者统计维度不同，不能只换模块名。RoPE、缩放和归一化的先后顺序也要以目标模型的代码为准。

### 取舍

QK Norm 让训练更稳定，但也改变了注意力的表达方式。[OlmPool](https://allenai.org/papers/olmpool) 的受控实验发现它有助于稳定训练，却在长上下文扩展实验中损害了部分效果。所以 TinyLLM 默认**不加** QK Norm，先监测注意力 logits 的最大值和注意力熵；训练中出现分数失控时再引入，并在目标上下文长度上重新评估。

<a href="/tinyllm/notebooks/normalization.ipynb" download>normalization.ipynb</a> 的 QK Norm 单元格用两个长度差异很大的 Q/K 向量演示：原始点积最大为 100，L2 归一化后最大为 1，softmax 分布随之变平。

## 参考资料

- [Query-Key Normalization for Transformers，Henry 等，2020](https://aclanthology.org/2020.findings-emnlp.379/)
- [OlmPool 架构研究](https://allenai.org/papers/olmpool)
- [Qwen3 技术报告](https://arxiv.org/abs/2505.09388)
- [PyTorch `scaled_dot_product_attention`](https://docs.pytorch.org/docs/stable/generated/torch.nn.functional.scaled_dot_product_attention.html)
