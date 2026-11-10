---
title: "第 24 章：缩放定律与算力预算"
description: "给定算力，模型该做多大、该训多少 token：损失随参数、数据、算力的幂律，6ND 的估算，Kaplan 与 Chinchilla 为什么结论不同，以及“算力最优”和“推理最优”的取舍。"
pageClass: tinyllm-course
---

# 第 24 章：缩放定律与算力预算

[课程总览](./index.md) · [上一章](./hyperparameter-tuning.md) · [下一章](./large-model-stability.md)

::: info 本章状态：规划中
正文与 notebook 尚未完成。[第 23 章](./hyperparameter-tuning.md)讲了超参数怎样从小模型搬到大模型，没有讲规模本身怎么定。预计覆盖：

- **幂律。** 损失怎样随参数量 $N$、数据量 $D$、算力 $C$ 按幂律下降，以及“不可约损失”是什么。
- **算力账。** 一次训练约 $6ND$ 次浮点运算；给定 $C$，$N$ 和 $D$ 怎样分配。
- **两套结论为什么不同。** Kaplan 等（2020）主张“模型优先”，Chinchilla（2022）主张参数和 token 同比例增长；分歧的一部分来自学习率周期没有和训练长度对齐，正好接[第 17 章](./learning-rate.md)。
- **算力最优与推理最优。** 部署时还要算推理成本，于是小模型多训成为常见选择（Llama 系列远超 Chinchilla 比例的 token 数）。
- **从小规模外推。** 用几档小模型拟合曲线，预测大模型的损失；外推能走多远、在哪里失效。
:::

<TinyLLMMap active="scaling-laws" />

## 本章主线选择（待实验验证）

用[第 17 章](./learning-rate.md)的代理模型，取 4～5 档宽度、3～4 档训练步数，每个组合按同一组预生成 batch 训练，在对数坐标上画出 IsoFLOP 曲线：同样的算力下，哪个宽度的验证损失最低。再用这些最优点拟合幂律，外推一档没训练过的规模并实际验证。单次训练控制在约 8 秒，组合数受时限约束；结论性的比较至少 3 个种子。实验边界要写清：唐诗语料很小，数据受限时“重复几遍”会改变曲线（[第 14 章](./data-pipeline.md)）。[Kaplan 等，2020](https://arxiv.org/abs/2001.08361) · [Chinchilla，Hoffmann 等，2022](https://arxiv.org/abs/2203.15556) · [Muennighoff 等，2023](https://arxiv.org/abs/2305.16264)
