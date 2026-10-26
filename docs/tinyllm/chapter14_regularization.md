# Chapter 14：正则化与泛化

本章教案与实验尚在规划中。预计覆盖：Weight Decay、L1/L2、Dropout、Label Smoothing、Early Stopping；训练损失与验证损失。区分通用方法与语言模型预训练的具体选择。

## 本章主线选择（待实验验证）

主线先用 AdamW 的适度 <strong>weight decay</strong>，`dropout=0` 且不加 label smoothing，持续比较训练与验证损失。若小语料明显过拟合，再尝试 dropout 或调整训练步数；这些设置不应因为“大模型常这样做”就无条件照搬。[AdamW 原论文](https://arxiv.org/abs/1711.05101)

返回 [课程总目录](index.md#课程路线规划)。
