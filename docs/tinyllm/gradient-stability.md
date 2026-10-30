---
title: "第 20 章：梯度稳定与累积"
description: "梯度裁剪、FP16 Loss Scaling、梯度累积与梯度监测。"
pageClass: tinyllm-course
---

# 第 20 章：梯度稳定与累积

[课程总览](./index.md) · [上一章](./precision.md) · [下一章](./training-loop.md)

::: info 本章状态：规划中
正文与 notebook 尚未完成。预计覆盖：Gradient Clipping、FP16 Loss Scaling（`GradScaler`）、梯度累积与梯度数值监测；解释它们在训练循环中的调用顺序。
:::

<TinyLLMMap active="gradient-stability" />

## 本章主线选择（待实验验证）

默认记录全局梯度范数，并在 `optimizer.step()` 前按全局范数裁剪；显存不足时用梯度累积达到目标有效 batch。BF16/FP32 不默认使用 `GradScaler`；FP16 路径先 `unscale_` 再裁剪，防止把放大后的梯度当真实范数。裁剪阈值应随损失归一化、模型和训练曲线调整。[PyTorch AMP 梯度裁剪示例](https://docs.pytorch.org/docs/stable/notes/amp_examples.html#gradient-clipping)
