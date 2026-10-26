# Chapter 10：语料与数据管线

本章教案与实验尚在规划中。预计覆盖：清洗、去重、训练/验证划分、shuffle、batching、bucketing、数据来源混合、数据泄漏检查。

## 本章主线选择（待实验验证）

默认先清洗、去重，再以<strong>文档或来源为单位</strong>固定训练/验证划分，并检查跨集合近重复，记录语料来源和混合比例。这样能减少同一文档的片段同时落入训练与验证集造成的泄漏；混合比例没有通用最优值，要按目标语种、领域和数据质量调整。[Deduplicating Training Data Makes Language Models Better](https://arxiv.org/abs/2107.06499)

返回 [课程总目录](index.md#课程路线规划)。
