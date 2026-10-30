---
title: "第 28 章：推理优化"
description: "把生成、KV cache 与量化拼成一套推理系统：连续批处理、分页 KV、投机解码、算子融合与编译，以及怎样用首字延迟、每 token 延迟和吞吐衡量它们。"
pageClass: tinyllm-course
---

# 第 28 章：推理优化

[课程总览](./index.md) · [上一章](./quantization.md) · [下一章](./instruction-finetuning.md)

::: info 本章状态：规划中
正文与 notebook 尚未完成。前三章各解决推理的一个环节：[第 25 章](./generation.md)决定每一步怎样选字，[第 26 章](./inference-efficiency.md)用 KV cache 避免重算前缀，[第 27 章](./quantization.md)压缩权重和缓存。本章把它们放进同一个推理循环，处理“很多请求同时来”时才出现的问题。预计覆盖：

- **怎样衡量：** 首字延迟（TTFT）、每 token 延迟（TPOT）、吞吐（tokens/s）三个指标，以及为什么只看一个会误判；
- **批处理：** 静态批处理的空转问题，连续批处理（continuous batching）按 token 步调度请求；
- **KV 显存管理：** 分页 KV cache（PagedAttention）与前缀共享，接上第 26 章的显存估算；
- **投机解码：** 用小模型起草、大模型一次验证多个 token，输出分布与原模型一致的条件；
- **算子与运行时：** 回收[第 13 章](./gpu-training.md)点名的 GPU 优化——SDPA/FlashAttention 的 decode 路径、`torch.compile` 与 CUDA Graph 消除逐步的启动开销、权重只读带来的带宽瓶颈。
:::

<TinyLLMMap active="inference-optimization" />

## 本章主线选择（待实验验证）

以第 26 章“KV cache + 贪心解码”的单请求实现为<strong>基线</strong>，逐项加入连续批处理、分页 KV、投机解码与 `torch.compile`。每一项都用同一组请求、同样的输出长度测 TTFT、TPOT 和吞吐，并确认输出与基线一致（投机解码要求逐 token 一致，量化要求在同一验证集上质量不降），只打开一项时测一次，不把几项叠加后的提升归给其中某一项。生产系统可直接对照 [vLLM](https://docs.vllm.ai/) 的实现。

## 参考资料

- [Efficient Memory Management for Large Language Model Serving with PagedAttention，Kwon 等，2023](https://arxiv.org/abs/2309.06180)
- [Orca: A Distributed Serving System for Transformer-Based Generative Models，Yu 等，2022](https://www.usenix.org/conference/osdi22/presentation/yu)（迭代级调度，连续批处理的来源）
- [Fast Inference from Transformers via Speculative Decoding，Leviathan 等，2023](https://arxiv.org/abs/2211.17192)
- [PyTorch：torch.compile 教程](https://docs.pytorch.org/tutorials/intermediate/torch_compile_tutorial.html)
