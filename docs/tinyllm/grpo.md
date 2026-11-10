---
title: "第 43 章：GRPO 与可验证奖励"
description: "推理模型的主流训练方式：同一个问题采样一组回答、组内比较打分，省掉价值模型；奖励来自能自动判对错的规则。"
pageClass: tinyllm-course
---

# 第 43 章：GRPO 与可验证奖励

[课程总览](./index.md) · [上一章](./preference-alignment.md) · [下一章](./llm-agent-interaction.md)

::: info 本章状态：规划中
正文与 notebook 尚未完成。预计覆盖：

- **GRPO。** 同一个提示采样一组回答，用组内的平均分做基线，省掉 PPO 的价值模型；它和[第 41 章](./rlhf.md) PPO 的关系。
- **可验证奖励。** 答案对不对、代码能不能通过测试、格式合不合规，由程序判分，不需要奖励模型，也更难被“钻空子”。
- **推理模型。** 训练中回答长度和正确率怎样变化；“思考模式”是怎么来的。
- **风险。** 奖励只盯一个指标时，其他能力会不会退化；KL 约束还要不要。
:::

<TinyLLMMap active="grpo" />

## 本章主线选择（待实验验证）

唐诗本身就带着能自动判分的规则：每句字数、句数、偶数句是否押韵（押韵判定需要额外安装 `pypinyin`）。在[第 38 章](./instruction-finetuning.md)的 SFT 模型上，用“格式 + 押韵”当奖励做 GRPO，报告合格率在训练前后的变化，同时盯住验证损失和生成样例，防止为了押韵把语言能力训坏。[DeepSeekMath（GRPO），Shao 等，2024](https://arxiv.org/abs/2402.03300) · [DeepSeek-R1，2025](https://arxiv.org/abs/2501.12948)
