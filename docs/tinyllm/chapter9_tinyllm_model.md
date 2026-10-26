# Chapter 9：完整 TinyLLM

本章教案与实验尚在规划中。预计覆盖：组装 Decoder-only 模型，检查参数量、前向形状和下一 token logits。

## 本章主线选择（待实验验证）

组装<strong>稠密 Decoder-only Transformer</strong>：可学习 token embedding、RoPE 因果注意力、Pre-RMSNorm 残差 Block、SwiGLU、最终 RMSNorm 与词表输出头。小模型先共享输入/输出嵌入权重，训练和生成跑通后再比较解耦输出头、GQA 或 MoE。各子模块的选择与调整条件集中在 [课程总览](index.md#贯穿全书的主线选择)；不能把不同模型的超参数直接拼接成已验证的整机配置。

返回 [课程总目录](index.md#课程路线规划)。
