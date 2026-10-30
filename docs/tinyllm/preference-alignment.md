---
title: "第 36 章：DPO 与 GRPO"
description: "把 RLHF 变简单：DPO 不用奖励模型直接从偏好数据学；GRPO 不用价值模型，用可自动判分的任务训练推理能力。"
pageClass: tinyllm-course
---

# 第 36 章：DPO 与 GRPO

[课程总览](./index.md) · [上一章](./rlhf.md) · [下一章](./agent-memory.md)

::: info 本章状态：规划中
正文与 notebook 尚未完成。预计覆盖：从 RLHF 的目标推出 DPO：为什么可以跳过奖励模型和 PPO，直接用成对偏好训练；GRPO：同一个问题采样一组回答、组内比较打分，省掉价值模型；可验证奖励（算术题答案对不对、代码能不能通过测试）与推理模型；三种方法在同一任务上的效果、显存和稳定性对比。
:::

<TinyLLMMap active="preference-alignment" />

## 本章主线选择（待实验验证）

在 SFT 模型上先用 <strong>DPO</strong>：数据只需要成对的偏好，不用单独训练奖励模型，流程和 SFT 接近，和[第 35 章](./rlhf.md)的 RLHF 在同一份数据上对比。有能自动判对错的任务时，再用 GRPO 训练并观察回答长度和正确率的变化。对齐后要同时检查目标任务和原有能力，防止为了迎合偏好而退化。[DPO](https://arxiv.org/abs/2305.18290) · [DeepSeekMath（GRPO）](https://arxiv.org/abs/2402.03300) · [DeepSeek-R1](https://arxiv.org/abs/2501.12948)
