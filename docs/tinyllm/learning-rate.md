---
title: "第 17 章：学习率策略"
description: "Warmup、Cosine Decay 等学习率策略，以及按 step 更新的学习率曲线。"
pageClass: tinyllm-course
---

# 第 17 章：学习率策略

[课程总览](./index.md) · [上一章](./optimizers.md) · [下一章](./regularization.md)

::: info 本章状态：规划中
正文与 notebook 尚未完成。预计覆盖：Warmup、Cosine Decay、Linear Decay、OneCycle；按 step 更新与学习率曲线。
:::

<TinyLLMMap active="learning-rate" />

## 本章主线选择（待实验验证）

默认按<strong>优化器更新步</strong>做短暂 warmup，随后 cosine decay 到明确设定的最低学习率。它给初始参数和 AdamW 状态一个较温和的起步，并逐步减小后期更新；峰值学习率、warmup 比例和总步数仍需按 batch、模型宽度和验证损失调整。若训练极短，warmup 过长会浪费大部分预算。[PyTorch `CosineAnnealingLR`](https://docs.pytorch.org/docs/stable/generated/torch.optim.lr_scheduler.CosineAnnealingLR.html)
