---
title: "第 35 章：RLHF：奖励模型与 PPO"
description: "SFT 之后怎样让回答更符合人的偏好：偏好数据、奖励模型、PPO 与 KL 约束，这是 ChatGPT 背后的经典流程。"
pageClass: tinyllm-course
---

# 第 35 章：RLHF：奖励模型与 PPO

[课程总览](./index.md) · [上一章](./lora-finetuning.md) · [下一章](./preference-alignment.md)

::: info 本章状态：规划中
正文与 notebook 尚未完成。预计覆盖：RLHF 的三步流程（SFT → 训练奖励模型 → 用强化学习优化策略）；偏好数据怎样收集（同一个问题的两个回答，人来选更好的那个）；奖励模型怎样从“二选一”学出打分（Bradley–Terry 损失）；PPO 的策略、参考、奖励、价值四个模型各做什么；KL 惩罚为什么必不可少；奖励被“钻空子”（reward hacking）的例子。
:::

<TinyLLMMap active="rlhf" />

## 本章主线选择（待实验验证）

在[第 33 章](./instruction-finetuning.md)的 SFT 模型上，用一个可控的小任务把 <strong>RLHF 三步完整实现一遍</strong>：先训练奖励模型，再用 PPO 加 KL 惩罚优化，并记录奖励、KL 和生成样例。RLHF 是理解后面所有对齐方法的基础；但它要同时维护四个模型，训练也容易不稳定，TinyLLM 实际使用的对齐方法见[第 36 章](./preference-alignment.md)。[InstructGPT](https://arxiv.org/abs/2203.02155) · [PPO](https://arxiv.org/abs/1707.06347) · [Learning to Summarize from Human Feedback](https://arxiv.org/abs/2009.01325)
