# Chapter 8：Transformer Block

本章教案与实验尚在规划中。预计覆盖：注意力、前馈层、残差、归一化的连接方式；搭建多个 Block。

## 本章主线选择（待实验验证）

一个 Block 默认依次计算 `x + Attention(RMSNorm(x))` 与 `u + SwiGLU(RMSNorm(u))`，也就是两个 <strong>Pre-Norm 残差子层</strong>。这样既沿用 [Chapter 0 的 RMSNorm](chapter0_normalization.md) 与 [Chapter 3 的 SwiGLU](chapter3_activations_ffn.md)，又给梯度保留直接路径；额外的 Post-Norm 或 QK Norm 只在诊断显示需要时评估。[Pre-LN 梯度分析](https://arxiv.org/abs/2002.04745)

返回 [课程总目录](index.md#课程路线规划)。
