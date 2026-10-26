# Chapter 7：自注意力

本章教案与实验尚在规划中。预计覆盖：Q/K/V、缩放点积、因果 mask、多头注意力、张量转置与形状核对。

## 本章主线选择（待实验验证）

先实现带<strong>因果掩码的缩放点积 MHA</strong>，核对 Q/K/V 形状、mask 和 softmax；模型需要更低 KV cache 占用时，再用较少的 KV 头改成 <strong>GQA</strong>，并保持相同训练/评估口径。GQA 是推理内存与质量之间的权衡，不应只看头数判断更优。[GQA 论文](https://arxiv.org/abs/2305.13245)

返回 [课程总目录](index.md#课程路线规划)。
