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

### [深入理解 NautilusTrader](./nautilus-trader/index.md)

从源码读开源量化交易平台 NautilusTrader，结构和官方文档的概念划分对齐。开篇带你从零编译 Rust 和 Python 两部分（附一次完整编译的实测记录），第 0 章给出静态地图（节点分层、源码目录、核心数据结构、PyO3 绑定），第 1 章给出运行全景（内核、消息总线、一条报价和一笔订单的完整路径、回测/沙盒/实盘三种模式）。第一部分交易领域模型七章：数值类型与标识符、品种、行情数据与订单簿、订单状态机与条件单、成交仓位与盈亏、账户与保证金、事件与事件溯源，每章都有一条贯穿的手算例子。“写策略”一部分四章：Rust 策略的框架与运行机制、回调的完整流程、K 线聚合器（附真实成交数据的实验）、指标（注册表、Python 边界的开销、预热，以及一个从零实现、写单元测试、在回测里验证数值的动手教程），以及 Actor、执行算法与配置。第三部分内核组件十章：NautilusKernel 的组装与启动关闭、MessageBus 的路由与可重入派发、Cache 的索引与持久化、Clock 与回测时间线，DataEngine 的订阅计数与历史请求、RiskEngine 的检查与限流、ExecutionEngine 的路由与成交处理、订单仿真与联动、Portfolio 的盈亏与账户重算、Trader 的组件生命周期。第四部分回测五章：回测引擎的主循环与命令结清、Parquet 数据目录、模拟交易所的撮合与成交价规则、成交手续费延迟保证金四类行为模型、回测统计与报告。第五部分实盘与 Tokio 运行时九章：全局运行时与线程分布、节点的事件循环与启动关闭顺序、任务组的有界关闭、实时计时器、网络层的限流与重连、执行对账、订单簿断档恢复、Redis 与 PostgreSQL 外部后端、确定性仿真测试，前五章各附一组在本机实际运行过的实验。第 38 章以富途为例接入一个券商，正文是官方适配器开发指南的中文全译，逐节附富途的做法。规划中的部分：Python 层。

[进入全书 →](./nautilus-trader/index.md) · [从零编译 →](./nautilus-trader/build-from-source.md) · [第 0 章：NautilusTrader 架构 →](./nautilus-trader/nautilus-architecture.md)

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
