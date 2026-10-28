---
title: "第 28 章：偏好对齐与强化学习"
description: "让回答更符合人的偏好、更会推理：RLHF、DPO 与基于可验证奖励的强化学习。"
pageClass: tinyllm-course
---

# 第 28 章：偏好对齐与强化学习

[课程总览](./index.md) · [上一章](./lora-finetuning.md) · [下一章](./agent-memory.md)

::: info 本章状态：规划中
正文与 notebook 尚未完成。预计覆盖：偏好数据（同一个问题的两个回答哪个更好）、奖励模型与 RLHF、DPO、基于可验证奖励的强化学习（例如算术题答案对不对、代码能不能通过测试），以及用 KL 约束防止模型偏离 SFT 模型太远。
:::

<TinyLLMMap active="preference-alignment" />

## 本章主线选择（待实验验证）

在[第 26 章](./instruction-finetuning.md)的 SFT 模型上先用 <strong>DPO</strong>：数据只需要成对的偏好，不用单独训练奖励模型，流程和 SFT 接近。有能自动判对错的任务时，再用 GRPO 一类基于可验证奖励的方法对比。对齐后要同时检查目标任务和原有能力，防止为了迎合偏好而退化。[InstructGPT](https://arxiv.org/abs/2203.02155) · [DPO](https://arxiv.org/abs/2305.18290) · [DeepSeekMath（GRPO）](https://arxiv.org/abs/2402.03300)
