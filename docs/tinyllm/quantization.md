---
title: "第 25 章：量化"
description: "用更少的比特存权重和 KV cache：INT8/INT4 量化，以及怎样测量化带来的损失。"
pageClass: tinyllm-course
---

# 第 25 章：量化

[课程总览](./index.md) · [上一章](./inference-efficiency.md) · [下一章](./instruction-finetuning.md)

::: info 本章状态：规划中
正文与 notebook 尚未完成。预计覆盖：对称与非对称量化、按通道与分组量化、权重量化（INT8/INT4）、KV cache 量化，以及量化前后困惑度与生成样例的对比。量化和[第 17 章](./precision.md)的混合精度不同：混合精度管训练时用什么格式计算，量化主要压缩推理时的存储和带宽。
:::

<TinyLLMMap active="quantization" />

## 本章主线选择（待实验验证）

训练和评估沿用[第 17 章](./precision.md)的精度设置；部署时显存或带宽受限，先对权重做按通道或分组的 <strong>INT8 量化</strong>，在同一验证集上比较困惑度和生成样例，损失可以接受后再试 INT4。[LLM.int8()](https://arxiv.org/abs/2208.07339) · [GPTQ](https://arxiv.org/abs/2210.17323)
