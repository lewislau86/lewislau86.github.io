---
title: "第 12 章：语料与数据管线"
description: "清洗、去重、划分训练与验证集、batching，以及数据泄漏检查。"
pageClass: tinyllm-course
---

# 第 12 章：语料与数据管线

[课程总览](./index.md) · [上一章](./tinyllm-model.md) · [下一章](./language-model-loss.md)

::: info 本章状态：规划中
正文与 notebook 尚未完成。预计覆盖：清洗、去重、训练/验证划分、shuffle、batching、bucketing、数据来源混合、数据泄漏检查。
:::

<TinyLLMMap active="data-pipeline" />

## 本章主线选择（待实验验证）

默认先清洗、去重，再以<strong>文档或来源为单位</strong>固定训练/验证划分，并检查跨集合近重复，记录语料来源和混合比例。这样能减少同一文档的片段同时落入训练与验证集造成的泄漏；混合比例没有通用最优值，要按目标语种、领域和数据质量调整。[Deduplicating Training Data Makes Language Models Better](https://arxiv.org/abs/2107.06499)
