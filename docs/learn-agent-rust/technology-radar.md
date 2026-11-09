---
title: 技术跟踪与迁移边界
description: 截至 2026-11-08 的一手资料核对：MCP、Agent Skills、长任务 Harness、独立评估与 Agent RSI。
prev: false
next: false
pageClass: learn-agent-rust-course
---

# 技术跟踪与迁移边界

[课程总览](./index.md) · [全书审查](./course-review.md) · [Agent RSI](./agent-rsi.md)

**资料核对日期：2026-11-08。** 本页记录查阅到的规范版本、研究版本和对本书的具体影响；它是一个有日期的快照。下次更新需要重新打开一手来源，不能把这里的“当前”理解成永久结论。

本书保留两条线：固定版本的实验用于复现，技术跟踪用于判断哪些假设需要重新检验。升级依赖、切换模型和增添新机制，都应该留下前后对照证据。

![一手资料先形成迁移假设，通过隔离对照和故障验证后才能进入课程基线。](/learn-agent-rust/figures/review-technology-migration.svg)

从左到右读：读到新规范只完成第一步。旧版能运行、新版有文档与新版实验通过，是三个不同的事实。

## 1. 版本与证据分开记录

| 主题 | 本书可复现基线 | 本次核对的一手资料 | 影响与处理 |
| --- | --- | --- | --- |
| 两库接线 | graph-flow 源码 `9bbca193…`、langchain-rust 源码 `5fc3f5ac…`，各包保留 Cargo.lock | [graph-flow 仓库](https://github.com/a-agmon/rs-graph-llm)、[langchain-rust 仓库](https://github.com/Abraxas-365/langchain-rust) | 本次没有升级依赖，也没有将 README 版本等同于最新 crate 版本；版本选择与重跑要求见[环境准备](./setup.md#install-frameworks)。 |
| MCP | R19 的 rmcp 3.9.0、协议 2025-11-25；R20 沿用其协议合同 | [规范 2026-07-28](https://modelcontextprotocol.io/specification/2026-07-28)、[变更清单](https://modelcontextprotocol.io/specification/2026-07-28/changelog) | 需要新的生命周期、能力与结果解析测试，见下一节；现有实验保留为旧版基线。 |
| Agent Skills | R07 验证目录发现、版本、正文注入与宿主权限 | [Agent Skills 规范](https://agentskills.io/specification)，于本页日期查阅的可变页面 | 把格式兼容、按需加载和宿主执行权分别验收；allowed-tools 仍标注 Experimental。 |
| 长任务 Harness | R08 压缩、R09 事实记忆、P01 检查点、P05 目标控制 | Anthropic [2025-11-26 长任务实践](https://www.anthropic.com/research/effective-harnesses-for-long-running-agents)、[2026-03-24 Harness 设计](https://www.anthropic.com/research/harness-design-long-running-apps) | 关注交接材料、独立验收以及新模型下哪些支架仍有必要；不要把全部机制默认打开。 |
| Agent 评估 | P03 的本地协议与固定任务夹具 | Anthropic [2026-01-09 Agent evals](https://www.anthropic.com/research/demystifying-evals-for-ai-agents) | 保留任务、试验、判分器、轨迹和最终效果；协议通过与真实模型完成率分别报告。 |
| RSI 研究 | P06 的有限策略门控实验 | DGM、Hyperagents、Skill∞，版本见第 4 节 | 将任务层改进与元改进分开；本书实验不宣称实现开放式 RSI。 |

源码短哈希只为便于阅读，完整固定值在[课程架构](./architecture.md#reference-assets)与各工程依赖中。上表没有给真实 provider 的质量、价格或框架维护状态作未经验证的判断。

## 2. MCP：2025-11-25 到 2026-07-28 需要重验什么？ {#mcp-migration}

R19 讲解 initialize 握手与 rmcp 连接生命周期，准确对应其固定基线。官方当前规范已经改变了这套合同。以下对照来自 [2026-07-28 变更清单](https://modelcontextprotocol.io/specification/2026-07-28/changelog)，不能用更新字符串代替实现迁移。

| 变化位置 | 2026-07-28 的变化 | Rust 迁移时的最小验收 |
| --- | --- | --- |
| 初始化与能力 | 移除 initialize / initialized；每个请求在 `_meta` 携带版本与客户端能力，新增 server/discover | discovery、缺失元数据、版本不匹配与旧服务兼容分别测试。 |
| HTTP 状态 | 移除协议级会话与 Mcp-Session-Id；跨调用业务状态使用显式 handle | 把业务会话身份与传输连接拆开；重连后重新核对权限和操作身份。 |
| 返回值 | 结果携带 resultType；MRTR 用 input_required 表达多轮补充输入 | 普通完成、补充输入、旧服务缺字段与未知类型分别解析；补输入继续沿用累计预算。 |
| 通知 | subscriptions/listen 取代旧订阅入口；请求相关通知与订阅通知分流 | 测试来源关联、取消、断连与订阅资源回收。 |
| 长任务 | tasks 从核心协议移到官方扩展，接口也有重新设计 | 明确扩展支持；不能直接把协议 task 映射成 R12 的业务任务所有权。 |
| HTTP 流中断 | 移除 SSE 恢复与消息重送；重新发起请求使用新 request ID | 新 RPC 身份下仍复用原业务 operation_id；按 P02 合同判断能否重放。 |

这里最后一行直接连接本书可靠性主线：传输重发的身份会变，业务意图的身份应按幂等合同保持稳定。新版协议的存在没有消除“动作完成而回执丢失”的窗口。

**迁移状态：尚未实现或运行新版 MCP 实验。** 需要选择实际支持该版的 SDK，保留旧版对照，复验 R19 的发现、schema、权限、超时、实际效果和进程回收，再重跑 R20 的跨机制场景。此处没有承诺当前 rmcp 版本支持新版。

## 3. 让 Harness 随证据演化

[Agent Skills 规范](https://agentskills.io/specification)采用元数据、正文与资源逐级加载，建议控制主文档规模。R07 的目录先发现、正文后加载与此相连；兼容一个文件格式不代表各宿主对权限字段采用相同解释。R10 仍需保留来源，R03 仍在动作前执行授权。

Anthropic 的 [2025 长任务文章](https://www.anthropic.com/research/effective-harnesses-for-long-running-agents)展示初始化、逐项推进与清晰交接材料；[2026 Harness 文章](https://www.anthropic.com/research/harness-design-long-running-apps)进一步讨论生成与评估分工，以及随模型能力变化逐项移除不再有用的支架。这些是作者在具体应用上的经验，不能推导出“更多 Agent 一定更好”。

给自己的系统做一次小型消融：固定任务、模型版本与额度，分别运行基础循环、加入技能、加入审查者三个配置。每次只改变一个因素，同时记录产物验收、调用次数、费用与失败轨迹。模型更换后重新做，而不是沿用旧结论。**这是建议的后续实验，本书尚未提供这组三配置的真实模型结果。**

[P03](./model-evaluation.md)提供独立判分入口；它的确定性重复验证复现性。[Agent evals 文章](https://www.anthropic.com/research/demystifying-evals-for-ai-agents)强调保留轨迹与环境效果，正好帮助回答“为何成功/失败”，而不只得出一个总分。

## 4. RSI 研究：追踪可改变的对象 {#rsi-research}

| 一手资料 | 本次查阅版本 | 改变的对象与阅读重点 | 证据地位 |
| --- | --- | --- | --- |
| [AlphaEvolve](https://deepmind.google/blog/alphaevolve-a-gemini-powered-coding-agent-for-designing-advanced-algorithms/) | 2025-05-14 官方介绍 | 候选算法程序与自动评估器；先问目标是否可执行验证。 | 官方系统报告，不能直接推断搜索器自身递归改进。 |
| [Darwin Gödel Machine](https://arxiv.org/abs/2505.22954v3) | v3，2026-03-12；初稿 2025-05-29 | 修改 Agent 代码，保存候选档案，以编程任务作经验验证。 | 原论文；经验结果不等于改动有益的数学证明。 |
| [Hyperagents](https://arxiv.org/abs/2603.19461v2) | v2，2026-11-01；初稿 2026-03-19 | 任务 Agent 与元 Agent 放进可编辑程序，元改进过程也可改。 | 作者报告跨任务元改进现象；本站未独立复现。 |
| [Skill∞](https://arxiv.org/abs/2610.35434v1) | v1，2026-10-26 | 任务技能与元技能两个层次，优化技能的程序也作为技能被改进。 | 近期预印本；本文不把其报告当成已独立验证的通用结论。 |

研究细节及其与 Rust 实验的区别见[专题 6](./agent-rsi.md)。本书选择这些资料，是因为它们明确指出了改进对象、搜索方式与评估边界；这份清单不声称覆盖全部最新论文。

## 5. 下一次更新怎样进入正文 {#maintenance}

先记录来源 URL、查阅日期、规范或论文版本及影响章节，再写出“旧机制会在哪个具体输入下失效”的迁移假设。在独立实验中固定任务与预算，保留旧结果，运行新版正常和故障路径。最后更新源码、锁文件、输出、配图、正文与下载包，并在这里标明迁移是否已经验收。

遇到真实服务价格或行为变化时，连同模型实际标识、请求参数、usage、墙钟时间和计价日期保存；缺少数据就保留未知，不用本地夹具填补。

回到[全书审查](./course-review.md)，或继续[Agent RSI：让改进经得起独立验收](./agent-rsi.md)。
