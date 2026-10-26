# Chapter 24：扩展专题

本章教案与实验尚在规划中。预计覆盖：GQA、FlashAttention、量化、分布式训练与对齐方法；Agent 记忆和检索另见 [Chapter 25](chapter25_agent_memory.md)。

## 本章主线选择（待实验验证）

优先通过 **PyTorch `scaled_dot_product_attention`** 表达因果注意力，让框架在可用条件下选择实现；高效内核可能影响速度与显存，不会改变模型应预测的目标。GQA 已在 [Chapter 7](chapter7_self_attention.md) 作为 KV cache 权衡引入；量化、分布式和对齐各有独立目标，只有相应部署或训练约束出现时才加入主线。[PyTorch SDPA 文档](https://docs.pytorch.org/docs/stable/generated/torch.nn.functional.scaled_dot_product_attention.html)

返回 [课程总目录](index.md#课程路线规划)。
