---
title: "第 32 章：推理优化：逐项对照与推理服务"
description: "把前七章的优化放进同一个推理系统，逐项单独打开、各测一次；再往外看多卡、多机、路由与可观测性，最后把 TinyLLM 包成一个能对外服务的接口。"
pageClass: tinyllm-course
---

# 第 32 章：推理优化：逐项对照与推理服务

[课程总览](./index.md) · [上一章](./kv-memory.md) · [下一章](./instruction-finetuning.md)

::: info 本章状态：规划中
正文与 notebook 尚未完成。第六部分的前七章各解决一个环节：[第 25 章](./generation.md)决定每一步怎样选字，[第 26 章](./inference-efficiency.md)用 KV cache 避免重算前缀并给出指标，[第 27 章](./attention-kernels.md)换掉注意力内核的写法，[第 28 章](./quantization.md)压缩权重和缓存，[第 29 章](./speculative-decoding.md)一次推进多个位置，[第 30 章](./batching.md)把请求排进同一个循环，[第 31 章](./kv-memory.md)管理显存里的 KV。本章做三件事：

- **合成一张对照表。** 每一项只单独打开，用同一份请求流、同样的输出长度测首字延迟、每 token 延迟、吞吐和显存；输出必须与基线逐 token 一致（量化则要求同一验证集上质量不降），否则不算优化。几项叠加后的提升不归给其中任何一项。
- **再往外看一层。** 一张卡放不下时的并行方式（数据、张量、流水线、专家并行）、把 prefill 与 decode 分到不同机器（PD 分离）、请求该发往哪台机器（路由：最少负载、前缀命中、KV 压力），以及能看见什么（可观测性：每一层各自的指标）。
- **包成服务。** 用 FastAPI 起一个 `/v1/chat/completions` 兼容接口，流式返回；把日志、指标和优雅退出接上，然后在本地跑通与 `curl` 的往返。
:::

<TinyLLMMap active="inference-optimization" />

## 本章主线选择（待实验验证）

主线是<strong>一项一项单独测</strong>：以[第 26 章](./inference-efficiency.md)的单请求 KV cache 循环为基线，每次只加一项优化，其余全部固定，同一份请求流跑完记录四个指标。对照实验照[课程规范](/guide/course-conventions)的写法：请求流由独立生成器预先排好，至少三个种子，报告平均与范围，并写明实验边界（CPU、模型尺寸、最大上下文）。凡是输出与基线不一致的实现，先当 bug 查，不当作“优化”。

并行、PD 分离、路由与可观测性在这条基线上只做<strong>概念与最小模拟</strong>：张量并行把一个线性层按列切开、拼回来验证结果一致；流水线用微型 stage 排出时间线、量气泡；路由用一个带前缀树的调度器比较命中率。真实的吞吐与显存收益依赖多卡和网络，报告时要标注来源，或者注明尚未实测。

最后一步是把模型包进服务。这一步的产出是接口与观测手段，不是新的算法结论；验收标准是同一份请求经 HTTP 送达后，输出与本地直接调用逐 token 一致。

## 参考资料

- [Efficient Memory Management for Large Language Model Serving with PagedAttention，Kwon 等，2023](https://arxiv.org/abs/2309.06180)
- [Orca: A Distributed Serving System for Transformer-Based Generative Models，Yu 等，2022](https://www.usenix.org/conference/osdi22/presentation/yu)（迭代级调度，连续批处理的来源）
- [Fast Inference from Transformers via Speculative Decoding，Leviathan 等，2023](https://arxiv.org/abs/2211.17192)
- [DistServe：把 prefill 与 decode 拆到不同机器，Zhong 等，2024](https://arxiv.org/abs/2401.09670)
- [PyTorch：torch.compile 教程](https://docs.pytorch.org/tutorials/intermediate/torch_compile_tutorial.html)
- [vLLM 文档](https://docs.vllm.ai/)（生产系统的对照实现）
