---
title: "第 22 章：推理效率"
description: "Prefill 与 decode、KV cache、显存开销与批量生成。"
pageClass: tinyllm-course
---

# 第 22 章：推理效率

[课程总览](./index.md) · [上一章](./generation.md) · [下一章](./instruction-finetuning.md)

::: info 本章状态：规划中
正文与 notebook 尚未完成。预计覆盖：Prefill/decode、KV cache、注意力时间与显存开销、批量生成。先建立最重要的边界：这里的 cache 是<strong>推理过程中的计算状态</strong>，不是替 Agent 保存用户事实的长期记忆。
:::

<TinyLLMMap active="inference-efficiency" />

## 本章主线选择（待实验验证）

逐 token decode 默认复用 <strong>KV cache</strong>，分别测量 prefill 延迟、每步 decode 延迟和缓存字节数。它避免旧前缀反复投影成 K/V，但上下文和并发增加时会占用显存；若 KV 压力成为瓶颈，再结合 [第 9 章的 GQA](self-attention.md) 或分页缓存管理。缓存绝不替代跨会话事实存储。

## 为什么生成时要缓存 K 和 V

读入提示词时，模型进行 prefill：每层注意力都会为输入 token 计算查询 Q、键 K、值 V。随后进入 decode，每一步生成一个新 token。因果注意力下，旧 token 的 K/V 可以继续使用；如果每一步都从头计算整段前缀，会反复做相同工作。KV cache 保存旧 token 在各层的 K/V，新一步只算新 token 的 K/V，再用它们和已有缓存完成注意力。[vLLM 的前缀缓存说明](https://docs.vllm.ai/en/stable/design/prefix_caching/)展示了服务系统如何复用满足条件的前缀。

缓存不是免费的。对普通全注意力 Decoder，可把占用近似写为 `2 × 层数 × 已缓存 token 数 × KV 头数 × 每头维度 × 每元素字节数`，再乘并发请求数；其中的 2 对应 K 和 V。这是张量数据量的粗略估计，不包含分配、分页或其他运行开销。上下文越长，并发越高，缓存压力越大。GQA/MQA 减少 KV 头数，KV 量化减少每个元素的字节数，分页管理改善缓存分配与复用；这些方法解决的是不同环节。[vLLM PagedAttention](https://arxiv.org/abs/2309.06180) 是缓存管理的代表工作。

还需区分两种“复用”：同一次生成中复用已计算的前缀 K/V，是 KV cache 的基本用途；跨请求复用相同前缀，需要服务系统识别兼容的 token、模型状态和位置等条件。前缀文字改了，旧缓存不能无条件继续用。前缀缓存即使跨请求存在，也不等于 Agent 能按语义检索用户过去说过的话；后者见 [第 27 章](agent-memory.md)。

后续实验将用同一模型、同一提示词和相同输出长度比较“每步重算前缀”与“缓存旧 K/V”，记录生成时间和缓存占用；再改变上下文长度和并发量，观察收益与内存的交换。基准应同时报告 prefill 与 decode，避免只看单个数字。
