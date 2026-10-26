# Chapter 11：语言模型目标函数

本章教案与实验尚在规划中。预计覆盖：输入与目标错位、softmax、交叉熵、负对数似然、困惑度、padding 与 loss mask。

## 本章主线选择（待实验验证）

预训练默认做<strong>下一 token 预测</strong>，对有效目标位置计算交叉熵平均值；有 padding 时明确掩码，不能让填充位置改变分母。它直接对应自回归生成。指令微调会在 [Chapter 21](chapter21_instruction_finetuning.md) 改为只统计助手答案位置，避免把用户提示词当成同等监督目标。

返回 [课程总目录](index.md#课程路线规划)。
