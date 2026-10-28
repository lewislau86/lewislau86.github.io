---
title: "第 23 章：自回归生成"
description: "逐 token 解码、温度、top-k、top-p、停止条件与重复问题。"
pageClass: tinyllm-course
---

# 第 23 章：自回归生成

[课程总览](./index.md) · [上一章](./mixture-of-experts.md) · [下一章](./inference-efficiency.md)

::: info 本章状态：规划中
正文与 notebook 尚未完成。预计覆盖：逐 token 解码、温度、top-k、top-p、停止条件与重复问题。
:::

<TinyLLMMap active="generation" />

## 本章主线选择（待实验验证）

固定评估先用<strong>贪心解码</strong>，使同一提示词的输出可复现；开放式交互提供温度与 top-p 采样，并明确 EOS、最大输出长度和随机种子。温度低通常更集中，高温或较大 top-p 可增加多样性，也可能增加错误；没有跨任务通用的最佳采样参数。[Nucleus Sampling 论文](https://arxiv.org/abs/1904.09751)
