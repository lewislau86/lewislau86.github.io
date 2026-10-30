---
title: "第 33 章：指令微调"
description: "在预训练模型上做监督微调：对话模板、只对答案计算 loss。"
pageClass: tinyllm-course
---

# 第 33 章：指令微调

[课程总览](./index.md) · [上一章](./inference-optimization.md) · [下一章](./lora-finetuning.md)

::: info 本章状态：规划中
正文与 notebook 尚未完成。预计覆盖：预训练与监督微调、对话模板、只对答案计算 loss、基础评估。
:::

<TinyLLMMap active="instruction-finetuning" />

## 本章主线选择（待实验验证）

在预训练权重上做 <strong>SFT</strong>，固定对话模板和终止 token，并仅对助手答案位置计算 loss。这样监督目标对应模型需要生成的内容；模板或 mask 不一致会让训练目标和推理提示词错位。数据量不足或显存受限时再比较 [LoRA](lora-finetuning.md) 微调。
