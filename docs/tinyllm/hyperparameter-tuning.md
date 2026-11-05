---
title: "第 23 章：超参数与自动化调参"
description: "训练里哪些超参数最要紧、哪些可以放心用默认值、它们怎样互相牵连；先量出噪声底线，再在同样的训练预算下比较网格、随机、逐轮淘汰与基于模型的搜索。"
pageClass: tinyllm-course
---

# 第 23 章：超参数与自动化调参

[课程总览](./index.md) · [上一章](./training-evaluation.md) · [下一章](./large-model-stability.md)

::: info 本章状态：规划中
正文与 notebook 尚未完成。第 16～18 章已经零散地调过学习率、调度、weight decay 和 dropout，本章把这些经验串起来，回答“该调什么、按什么顺序调、怎么判断调好了”。预计覆盖：

- **噪声底线**：同一配置换种子，结果差多少；小于这个差别的“改进”不算数。
- **敏感度排序**：在代理模型上实测哪些超参数一动结果就大变，哪些在合理范围内都差不多，预算该花在哪里。
- **耦合与换参数**：峰值学习率与衰减要一起调（[第 17 章](./learning-rate.md)），weight decay 要按时间尺度 1/(lr·wd) 理解（[第 18 章](./regularization.md)），学习率随 batch 大小变化；怎样换成更“互不干扰”的参数来调。
- **调参的顺序与预算**：先固定什么、先扫什么、什么时候停；区分要研究的超参数、需要跟着调的超参数和可以固定的超参数。
- **自动化方法**：网格搜索、随机搜索、逐轮淘汰（successive halving、Hyperband、ASHA）、基于模型的搜索（TPE、高斯过程），以及边训练边调的 PBT；在同样的训练次数下比较谁先找到好配置。
- **陷阱**：早期淘汰会错杀后期才发力的配置（比如 WSD 在衰减前损失更高）；挑选次数越多，验证集上的最好结果越偏乐观。
- **从小到大**：代理模型上调出的数字怎样迁移到大模型；超参数随算力变化的经验规律，以及 μP 这类让最佳学习率不随宽度变化的参数化（下一章展开）。
:::

<TinyLLMMap active="hyperparameter-tuning" />

## 本章主线选择（待实验验证）

先用同一配置的多个种子量出<strong>噪声底线</strong>，再按敏感度从高到低调：学习率（对数网格粗扫）优先，其余超参数用随机搜索配合逐轮淘汰；所有候选共用同一份 batch 计划，用验证集挑、用测试集报。代理模型上调出的具体数值不直接搬到大模型，只迁移“哪些要调、怎么调”的规律。

## 参考资料（写作时要读）

经验与方法论：

- [Deep Learning Tuning Playbook，Godbole 等（Google Research），2023](https://github.com/google-research/tuning_playbook)（调参的流程与预算分配）
- [A Recipe for Training Neural Networks，Karpathy，2019](https://karpathy.github.io/2019/04/25/recipe/)
- [Practical Recommendations for Gradient-Based Training of Deep Architectures，Bengio，2012](https://arxiv.org/abs/1206.5533)

搜索算法：

- [Random Search for Hyper-Parameter Optimization，Bergstra 与 Bengio，2012](https://jmlr.org/papers/v13/bergstra12a.html)（随机搜索为什么常比网格好）
- [Algorithms for Hyper-Parameter Optimization，Bergstra 等，2011](https://papers.nips.cc/paper/4443-algorithms-for-hyper-parameter-optimization)（TPE）
- [Practical Bayesian Optimization of Machine Learning Algorithms，Snoek 等，2012](https://arxiv.org/abs/1206.2944)（高斯过程）
- [Non-stochastic Best Arm Identification and Hyperparameter Optimization，Jamieson 与 Talwalkar，2016](https://arxiv.org/abs/1502.07943)（successive halving）
- [Hyperband: A Novel Bandit-Based Approach to Hyperparameter Optimization，Li 等，2018](https://arxiv.org/abs/1603.06560)
- [A System for Massively Parallel Hyperparameter Tuning，Li 等，2020](https://arxiv.org/abs/1810.05934)（ASHA）
- [Population Based Training of Neural Networks，Jaderberg 等，2017](https://arxiv.org/abs/1711.09846)
- [Optuna: A Next-generation Hyperparameter Optimization Framework，Akiba 等，2019](https://arxiv.org/abs/1907.10902)

语言模型的超参数与规模：

- [DeepSeek LLM: Scaling Open-Source Language Models with Longtermism，DeepSeek-AI，2024](https://arxiv.org/abs/2401.02954)（最佳学习率与 batch 大小随算力的幂律）
- [MiniCPM: Unveiling the Potential of Small Language Models with Scalable Training Strategies，Hu 等，2024](https://arxiv.org/abs/2404.06395)（用小模型做“风洞实验”）
- [Tensor Programs V: Tuning Large Neural Networks via Zero-Shot Hyperparameter Transfer，Yang 等，2022](https://arxiv.org/abs/2203.03466)（μP）
- [How to set AdamW's weight decay as you scale model and dataset size，Wang 与 Aitchison，2024](https://arxiv.org/abs/2405.13698)（weight decay 的时间尺度）
- [An Empirical Model of Large-Batch Training，McCandlish 等，2018](https://arxiv.org/abs/1812.06162)（临界 batch 大小）
