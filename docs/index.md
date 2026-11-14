---
title: 文档首页
---

# Lewis 的知识库

记录技术研究，整理项目文档，沉淀学习笔记。

这里按主题和章节组织内容。每篇文档都可以持续补充，让零散的记录逐渐成为可以查阅、复用的知识。

## 文档集

### [TinyLLM · 从零学习语言模型](./tinyllm/index.md)

先用不到 100 行代码跑通一个会写唐诗的小模型，再顺着数据流从分词、词嵌入、注意力一路搭出模型，接着用残差、初始化和归一化让深层网络训得动，最后是预训练、推理、中训练、后训练与应用。课程分九部分、规划 44 章，目前第 1～30 章已有完整教案、配图和配套 notebook；每章开头的架构总图会标出本章负责的零件。只有半小时的话，从[30 分钟快速体验](./tinyllm/quickstart.md)开始。

[进入 TinyLLM 教程 →](./tinyllm/index.md)

### <a href="/moe-handbook-zh/" target="_self">终极 MoE 训练手册（中文译本）</a>

Hugging Face《The Ultimate MoE Training Handbook》的中文社区译本，按路由器、负载均衡、专家配置、训练稳定性和系统性能逐项讲解，并保留原有的交互图表。原作者为 Nouamane Tazi、Leandro von Werra、Thomas Wolf；中文译者为 [leonyuhe](https://github.com/leonyuhe/moe-handbook-zh)。译本按 CC BY 4.0 许可转载，详见[原文](https://huggingface.co/spaces/huggingface/moe-blogpost)与[译文仓库](https://github.com/leonyuhe/moe-handbook-zh)。

<a href="/moe-handbook-zh/" target="_self">阅读终极 MoE 训练手册 →</a>

### [Learn Agent by Rust · 构建可理解、可恢复的 Agent](./learn-agent-rust/index.md)

围绕一个工作区助手，使用 `langchain-rust + graph-flow` 学习模型工具循环、图编排、权限、Skills、RAG、上下文、任务、团队和 MCP，再用恢复、幂等与目标验收实验检查运行边界。课程分十部分，39 个节点已成文并有实验入口；[常见 Agent 设计模式](./learn-agent-rust/agent-design-patterns.md)独立成部分，第 15–22 章附独立 Rust 工程、正常与故障复验及组合实验，真实模型对照待配置服务后运行。第 5–7 章讲图编排，第 11 章讲 RAG；各章明确区分固定夹具、真实效果与待验证范围。

[进入课程 →](./learn-agent-rust/index.md) · [开始第 0 章 →](./learn-agent-rust/architecture-and-setup.md) · [查看学习路径 →](./learn-agent-rust/learning-path.md) · [环境准备 →](./learn-agent-rust/setup.md)

### [思考与行动之间 · Agent 与大模型论文研读](./thinking-and-acting/index.md)

从 Transformer、GPT 和 FlashAttention 出发，沿着推理、行动、反馈与自我改进，研读大模型和 Agent 的经典论文与近期研究。第 1 章重读 Transformer 论文：它的核心论证依赖什么前提、实验证明了什么，以及作者在 2017 年下的判断九年后哪些应验了。其余章节正在规划。

[进入论文研读 →](./thinking-and-acting/index.md) · [阅读第 1 章：重读 Transformer →](./thinking-and-acting/transformer.md)

### [深入理解 Burn 深度学习框架](./burn/index.md)

从环境、模型数学、张量与 Rust 出发，通过 learn-cuda 学习 GPU 的线程、内存与分块，再认识 Rust CUDA 和 CubeCL，随后进入 Burn 的模型、后端、自动微分、训练、执行性能、部署与扩展。全书分七部分、18 章，统一学习目标、实践方式与章间导航；最后用 PyTorch 对照、源码追踪和实验索引检查理解。CPU 学习包以 Burn 0.22.1 为基线，实际验证范围在实验章逐项说明。

另有配备公式、图解、手算和自测的[数学预备篇](./burn/math-foundations.md)，可按需与正文对照阅读。

[进入 Burn 教程 →](./burn/index.md)

### [mini-redis · 从源码学习 Rust 与 Redis 架构](./mini-redis/index.md)

沿着一条 SET/GET 请求，学习 Rust 所有权、Tokio 异步任务、共享存储、过期清理、发布订阅与优雅停机。包含整体架构导读、13 章教程、28 篇逐文件源码分析、Rust 源码阅读说明、6 个可运行实验、源码学习包及原始验证记录。第 13 章记录 TTL 测试挂起的定位与修复过程。

[进入 mini-redis 教程 →](./mini-redis/index.md)

### [nautilus_trader 源码笔记 · 从 Rust 源码读量化交易平台](./nautilus-trader/index.md)

读开源交易平台 nautilus_trader 的 Rust 源码，以“给它接入一个新券商（富途）”为主线：适配器要实现哪些 trait、事件怎样回到引擎、对账怎样做，以及富途 OpenD 私有协议的要点。第一篇说明富途适配器为什么应当参照 Interactive Brokers 适配器来写，并给出从协议层到实盘节点的五个里程碑。

[进入笔记 →](./nautilus-trader/index.md) · [阅读第一篇：富途适配器怎么做 →](./nautilus-trader/futu-adapter.md)

## 从这里开始

更多文档将逐步整理。你可以通过左侧目录浏览文档，通过右侧目录定位当前章节，也可以使用顶部搜索查找内容。

- **技术研究**：记录概念、原理、方案比较与实验结论。
- **项目文档**：整理架构设计、使用说明和实践经验。
- **学习笔记**：按学习路径组织知识点、示例和问题。

## 阅读与查找

点击左侧目录切换文档；阅读长文时，使用右侧的「本页目录」跳转到具体章节。在手机上，点击「文档目录」展开导航。

点击顶部「搜索文档」，或按下 `⌘ K`（Windows / Linux 为 `Ctrl K`），输入关键词即可查找已收录的内容。

## 开始整理文档

准备写第一篇文档时，可以从 [新增与发布文档](./guide/writing.md) 开始。需要标题、代码块、表格等写作格式时，参考 [Markdown 写作示例](./guide/markdown.md)。
