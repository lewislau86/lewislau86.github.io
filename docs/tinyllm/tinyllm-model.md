---
title: "第 12 章：完整 TinyLLM"
description: "把所有零件组装成完整的 Decoder-only 模型，核对参数量与前向形状。"
pageClass: tinyllm-course
---

# 第 12 章：完整 TinyLLM

[课程总览](./index.md) · [上一章](./normalization.md) · [下一章](./data-pipeline.md)

::: info 本章状态：规划中
正文与 notebook 尚未完成。预计覆盖：组装 Decoder-only 模型，检查参数量、前向形状和下一 token logits。
:::

::: tip 想在 GPU 上放大训练？
学完本章后，可以走一条可选路线：同一份代码放大配置，在 GPU 上训练更大的模型，见[可选路线：GPU 完整训练](./gpu-training.md)。
:::

<TinyLLMMap active="tinyllm-model" />

## 本章主线选择（待实验验证）

组装<strong>稠密 Decoder-only Transformer</strong>：可学习 token embedding、RoPE 因果注意力、Pre-RMSNorm 残差 Block、SwiGLU、最终 RMSNorm 与词表输出头。小模型先共享输入/输出嵌入权重，训练和生成跑通后再比较解耦输出头、GQA 或 MoE。各子模块的选择与调整条件集中在 [课程总览](index.md#mainline-choices)；不能把不同模型的超参数直接拼接成已验证的整机配置。
