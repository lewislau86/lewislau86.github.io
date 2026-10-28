---
title: "第 14 章：语言模型目标函数"
description: "输入与目标错位、交叉熵、困惑度、padding 与 loss mask。"
pageClass: tinyllm-course
---

# 第 14 章：语言模型目标函数

[课程总览](./index.md) · [上一章](./data-pipeline.md) · [下一章](./optimizers.md)

::: info 本章状态：规划中
正文与 notebook 尚未完成。预计覆盖：输入与目标错位、softmax、交叉熵、负对数似然、困惑度、padding 与 loss mask。
:::

<TinyLLMMap active="language-model-loss" />

## 本章主线选择（待实验验证）

预训练默认做<strong>下一 token 预测</strong>，对有效目标位置计算交叉熵平均值；有 padding 时明确掩码，不能让填充位置改变分母。它直接对应自回归生成。指令微调会在 [第 27 章](instruction-finetuning.md) 改为只统计助手答案位置，避免把用户提示词当成同等监督目标。
