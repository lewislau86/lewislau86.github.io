---
title: "第 36 章：长上下文扩展"
description: "训练时只见过 64 个位置，怎样让模型用上 256 个：直接外推为什么失败，位置插值、调大 RoPE base、YaRN 各改了什么，以及为什么都还需要一小段长序列继续训练。"
pageClass: tinyllm-course
---

# 第 36 章：长上下文扩展

[课程总览](./index.md) · [上一章](./annealing.md) · [下一章](./continued-pretraining.md)

::: info 本章状态：规划中
正文与 notebook 尚未完成。[第 7 章](./position-encoding.md)演示过“超出训练长度就崩”，并用一段文字提到了几种扩展方法；本章把它做成实验。预计覆盖：

- **直接外推为什么失败。** 没见过的旋转角度产生没被约束的注意力分数。
- **三种改法。** 位置插值（PI）把长位置压回训练过的角度；调大 RoPE base（ABF）让旋转变慢；YaRN 按频率分段处理。
- **继续训练。** 三种改法都还要配一小段长序列训练；长样本怎样拼（接[第 14 章](./data-pipeline.md)的打包与文档掩码）。
- **代价。** 上下文变长，KV cache 和注意力计算怎样增长（接[第 28 章](./inference-efficiency.md)、[第 29 章](./attention-kernels.md)）。
- **损失没崩不等于用上了远处的信息。** 用合成的检索任务单独检查。
:::

<TinyLLMMap active="long-context" />

## 本章主线选择（待实验验证）

以[第 12 章](./tinyllm-model.md)的基线（上下文 64）为起点扩展到 256：直接外推、PI、调大 base、YaRN 四组，每组再分“不训练”和“短训练若干步”，按位置画验证损失。另加一个合成检索任务：在长上下文前部放一首诗，末尾要求续写它，检查模型是否真的用到了远处的内容。[Position Interpolation，Chen 等，2023](https://arxiv.org/abs/2306.15595) · [ABF，Xiong 等，2023](https://arxiv.org/abs/2309.16039) · [YaRN，Peng 等，2023](https://arxiv.org/abs/2309.00071)
