---
title: "第 22 章：稀疏专家（MoE）"
description: "把前馈层换成多个专家和一个路由器：同样的计算量装下更多参数，以及怎样让专家分工均衡。"
pageClass: tinyllm-course
---

# 第 22 章：稀疏专家（MoE）

[课程总览](./index.md) · [上一章](./large-model-stability.md) · [下一章](./generation.md)

::: info 本章状态：规划中
正文与 notebook 尚未完成。预计覆盖：路由器与 top-k 专家；与“激活参数相同”和“总参数相同”的稠密模型对比；路由崩塌与负载均衡（辅助损失、无辅助损失的偏置调整）；观察专家的分工；稀疏升级（把训练好的稠密模型改成 MoE 继续训练）。
:::

<TinyLLMMap active="mixture-of-experts" />

## 本章主线选择（待实验验证）

TinyLLM 主线保持<strong>稠密</strong>。本章把每个 Block 的 SwiGLU 换成路由器加多个小专家，其余代码不变，用相同数据和训练步数从头训练，与主线对比；再用稀疏升级，从已经训练好的稠密模型出发继续训练。MoE 是模型做大以后的选择：参数规模或推理成本成为瓶颈时再切换，具体结论以本章实验为准。[Switch Transformer](https://arxiv.org/abs/2101.03961) · [DeepSeek-V3 技术报告](https://arxiv.org/abs/2412.19437) · [Sparse Upcycling](https://arxiv.org/abs/2212.05055)
