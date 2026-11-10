---
title: "第 42 章：DPO：直接偏好优化"
description: "把 RLHF 变简单：DPO 不训练奖励模型、不跑 PPO，直接从成对的偏好数据学。"
pageClass: tinyllm-course
---

# 第 42 章：DPO：直接偏好优化

[课程总览](./index.md) · [上一章](./rlhf.md) · [下一章](./grpo.md)

::: info 本章状态：规划中
正文与 notebook 尚未完成。预计覆盖：从 RLHF 的目标推出 DPO：为什么可以跳过奖励模型和 PPO，直接用成对偏好训练；参考模型和系数 $\beta$ 起什么作用；DPO 与 RLHF 在同一任务上的效果、显存和稳定性对比；常见变体（IPO、KTO、SimPO）只做对照表。用可自动判分的任务训练推理能力的 GRPO 见[第 43 章](./grpo.md)。
:::

<TinyLLMMap active="preference-alignment" />

## 本章主线选择（待实验验证）

在 SFT 模型上先用 <strong>DPO</strong>：数据只需要成对的偏好，不用单独训练奖励模型，流程和 SFT 接近，和[第 41 章](./rlhf.md)的 RLHF 在同一份数据上对比。对齐后要同时检查目标任务和原有能力，防止为了迎合偏好而退化。[DPO，Rafailov 等，2023](https://arxiv.org/abs/2305.18290)
