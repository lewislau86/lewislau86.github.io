---
title: "第 10 章：Transformer Block"
description: "注意力、前馈层、残差与归一化怎样连成一个 Block，再叠成多层。"
pageClass: tinyllm-course
---

# 第 10 章：Transformer Block

[课程总览](./index.md) · [上一章](./self-attention.md) · [下一章](./tinyllm-model.md)

::: info 本章状态：规划中
正文与 notebook 尚未完成。预计覆盖：注意力、前馈层、残差、归一化的连接方式；搭建多个 Block。
:::

<TinyLLMMap active="transformer-block" />

## 本章主线选择（待实验验证）

一个 Block 默认依次计算 `x + Attention(RMSNorm(x))` 与 `u + SwiGLU(RMSNorm(u))`，也就是两个 <strong>Pre-Norm 残差子层</strong>。这样既沿用 [第 4 章的 RMSNorm](normalization.md) 与 [第 5 章的 SwiGLU](activations-and-ffn.md)，又给梯度保留直接路径；额外的 Post-Norm 或 QK Norm 只在诊断显示需要时评估。[Pre-LN 梯度分析](https://arxiv.org/abs/2002.04745)
