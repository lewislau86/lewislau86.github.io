---
title: "第 20 章：训练诊断与评估"
description: "先过拟合一个小 batch，再看验证损失、困惑度与生成样例。"
pageClass: tinyllm-course
---

# 第 20 章：训练诊断与评估

[课程总览](./index.md) · [上一章](./training-loop.md) · [下一章](./large-model-stability.md)

::: info 本章状态：规划中
正文与 notebook 尚未完成。预计覆盖：先过拟合一个小 batch，再观察 loss、梯度、验证集困惑度和生成样例。
:::

<TinyLLMMap active="training-evaluation" />

## 本章主线选择（待实验验证）

先做<strong>单个小 batch 过拟合</strong>来检查前向、反向和参数更新，再在独立验证集报告交叉熵、困惑度以及固定提示词的生成样例。困惑度只在相同 tokenizer 和数据口径下比较；一条训练 loss 曲线既不能证明泛化，也不能单独证明生成质量。
