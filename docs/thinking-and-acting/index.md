---
title: 思考与行动之间
description: 从 Transformer 到自我进化 Agent 的论文研读。
---

# 思考与行动之间

**从 Transformer 到自我进化 Agent 的论文研读**

本书沿两条相互交织的主线阅读论文：大语言模型的结构、效率与推理，以及 Agent 的行动、反馈与自我改进。每个专题关注论文要解决的问题、方法、实验和结论边界。

::: tip 当前进度
本书正在编写：Transformer 论文解读已成文，其余章节仍在规划中，顺序与范围可能调整。
:::

## 阅读路线

先从 Transformer 和 GPT 建立模型基础，再学习注意力优化与推理；Agent 主线从 ReAct 和反馈机制出发，延伸到 Dream-RSI，并以评测与可靠性贯穿。已有基础的读者也可以直接从感兴趣的专题入手。

## 第一部分 · Transformer 与 GPT

- [第 1 章 · Transformer：Attention Is All You Need](./transformer.md)（已成文）
- GPT-2：从语言建模到零样本任务（规划中）
- GPT-3：上下文学习与少样本任务（规划中）

## 第二部分 · 模型效率与推理

- FlashAttention：精确注意力与显存读写（规划中）
- FlashAttention 2–4：并行与硬件协同（规划中）
- DeepSeek-R1：强化学习与推理能力（规划中）
- 推理过程的收益与局限（规划中）

## 第三部分 · Agent 基础

- ReAct：推理、行动与环境反馈（规划中）
- Reflexion：语言反馈与反思记忆（规划中）
- 工具使用、规划与上下文管理（规划中）

## 第四部分 · Agent 自我改进

- RISE：通过训练学习迭代改进（规划中）
- Dream-RSI：历史回放与探索策略（规划中）
- Agent Harness 的递归改进（规划中）

## 第五部分 · 评测与开放问题

- Agent 评测：任务、环境与指标（规划中）
- 可靠性、成本与复现（规划中）
- 近期论文与研究方向（规划中）

## 研读方式

每篇论文计划围绕六个问题展开：解决什么问题、已有方法有什么限制、核心思路是什么、实验如何验证、结论的边界在哪里，以及它与其他论文有什么联系。

模型基础可以配合 [TinyLLM 教程](/tinyllm/) 阅读；Agent 的工程实现可参考 [Learn Agent by Rust](/learn-agent-rust/)。
