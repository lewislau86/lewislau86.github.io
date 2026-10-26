# Chapter 23：大规模训练稳定性

本章教案与实验尚在规划中。预计覆盖：μP、DeepNorm/残差缩放、深度与宽度扩展；在 Chapter 0 的公式基础上比较完整训练配置。

## 本章主线选择（待实验验证）

小模型继续使用 [Pre-RMSNorm 与残差投影缩放](chapter2_initialization_residuals.md)，记录激活 RMS、logits 和梯度范数随深度/宽度的变化。出现可复现的扩展问题时，再把 μP 或 DeepNorm 作为<strong>整套参数化与训练配方</strong>比较；只改一个系数、沿用原学习率，不能代表这些方法的效果。[μP 论文](https://arxiv.org/abs/2203.03466) · [DeepNorm 论文](https://arxiv.org/abs/2203.00555)

返回 [课程总目录](index.md#课程路线规划)。
