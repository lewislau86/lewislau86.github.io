---
title: "第 30 章：参数高效微调（LoRA）"
description: "冻结原模型，只训练低秩增量：LoRA 节省了什么、没有节省什么。"
pageClass: tinyllm-course
---

# 第 30 章：参数高效微调（LoRA）

[课程总览](./index.md) · [上一章](./instruction-finetuning.md) · [下一章](./rlhf.md)

::: info 本章状态：规划中
正文与 notebook 尚未完成。预计覆盖：低秩分解、LoRA 插在哪些线性层、秩与缩放系数、与全参数微调的显存和效果对比、把增量合并回原权重后推理。
:::

<TinyLLMMap active="lora-finetuning" />

## 本章主线选择（待实验验证）

TinyLLM 小模型先用<strong>全参数微调</strong>建立质量和显存基线；只有微调显存或优化器状态成为约束时，才试 LoRA。LoRA 主要减少可训练参数和对应的优化器状态，并不减少基础权重的推理存储；合并增量后推理速度与原模型相同。MoE 属于模型结构，见[第 24 章](./mixture-of-experts.md)。[LoRA 论文](https://arxiv.org/abs/2106.09685)
