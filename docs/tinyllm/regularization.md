---
title: "第 18 章：正则化与泛化"
description: "Weight Decay、Dropout、Label Smoothing、Early Stopping 与训练/验证损失。"
pageClass: tinyllm-course
---

# 第 18 章：正则化与泛化

[课程总览](./index.md) · [上一章](./learning-rate.md) · [下一章](./precision.md)

::: info 本章状态：规划中
正文与 notebook 尚未完成。预计覆盖：Weight Decay、L1/L2、Dropout、Label Smoothing、Early Stopping；训练损失与验证损失。区分通用方法与语言模型预训练的具体选择。
:::

<TinyLLMMap active="regularization" />

## 本章主线选择（待实验验证）

主线先用 AdamW 的适度 <strong>weight decay</strong>，`dropout=0` 且不加 label smoothing，持续比较训练与验证损失。若小语料明显过拟合，再尝试 dropout 或调整训练步数；这些设置不应因为“大模型常这样做”就无条件照搬。[AdamW 原论文](https://arxiv.org/abs/1711.05101)
