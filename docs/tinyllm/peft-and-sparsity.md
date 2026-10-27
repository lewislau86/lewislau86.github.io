---
title: "第 24 章：参数高效与稀疏结构"
description: "LoRA、MoE、稀疏与剪枝分别节省的是什么。"
pageClass: tinyllm-course
---

# 第 24 章：参数高效与稀疏结构

[课程总览](./index.md) · [上一章](./instruction-finetuning.md) · [下一章](./large-model-stability.md)

::: info 本章状态：规划中
正文与 notebook 尚未完成。预计覆盖：LoRA、MoE、结构化/非结构化稀疏、剪枝；分别说明节省的是训练参数、推理计算还是存储。
:::

<TinyLLMMap active="peft-and-sparsity" />

## 本章主线选择（待实验验证）

TinyLLM 小模型先用<strong>全参数训练</strong>建立质量和吞吐基线；只有在微调显存/优化器状态成为约束时，才优先试 LoRA。LoRA 主要减少可训练权重与对应优化器状态，并不自动减少基础权重的推理存储；MoE、稀疏和剪枝分别改变计算或模型结构，需要独立验证。[LoRA 论文](https://arxiv.org/abs/2106.09685)
