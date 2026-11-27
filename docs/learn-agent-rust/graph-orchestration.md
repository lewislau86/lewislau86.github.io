---
title: "图编排导读：从 LangGraph 概念到 adk-graph 实践"
description: "建立模型交互与图编排两条主线，沿状态通道、路由、检查点与恢复、并行汇合和子图学习 ADK-Rust 3.0 的 adk-graph。"
pageClass: learn-agent-rust-course
---

# 图编排导读：从 LangGraph 概念到 adk-graph 实践

[课程总览](./index.md) · [学习路径](./learning-path.md) · [开始图状态与路由](./graph-state-routing.md)

::: info 正在迁移到 ADK-Rust 3.0
全书实验正在逐章从 `graph-flow + langchain-rust` 迁移到 [ADK-Rust](https://github.com/zavora-ai/adk-rust) 3.0（发布候选版，固定提交）。已迁移的章节在课程地图和目录里标注“实验基于 ADK-Rust 3.0”，目前是第 0–7 章与[专题 2](./side-effect-reliability.md)。本导读与第 5–7 章基于 adk-graph；第五部分的设计模式章节仍是旧版 graph-flow 实验，迁移前的完整旧版可从 git 标签 `learn-agent-rust-v1` 取得。
:::

::: tip 本章学习目标
- 区分一次模型请求与一段工作流执行：谁提出动作，谁决定下一步运行哪里。
- 建立状态通道、节点、边、超步、检查点和汇合之间的联系。
- 沿三个可独立运行的 adk-graph 工程验证编排语义，再回到完整 Agent。

**前置：** [最小 Agent 循环](./agent-loop.md)与[工具注册与图调度](./tools-and-graph.md)。后续恢复章还需要理解[工具权限](./permissions.md)。

**实践方式：** 三章分别提供 Cargo 工程与下载包，真实运行固定提交的 adk-graph，无模型密钥；首次编译需要取一次 ADK-Rust 源码（见[环境准备](./setup.md#install-adk)）。
:::

## 1. 工具循环之后，还缺什么

一个助手可以反复调用模型和工具。现在让它完成升级审查：准备报告、检查要求、修复缺项、等待批准，再汇总结果。此时问题已经从“怎样调用一个模型”扩大到“不同阶段怎样共享状态，怎样决定下一步，退出以后从哪里继续”。

我们把这条流程做成三个递进实验：先用固定业务规则看清图的语义，再加入真实的 SQLite 检查点和跨进程恢复，最后引入并行检查与子图封装。节点以后可以是一个 `LlmAgent`（用 `AgentNode` 包装，[第 2 章](./tools-and-graph.md)已经做过），本组实验先用确定性逻辑让编排行为容易观察。

![LlmAgent 运行模型与工具的循环，adk-graph 管理节点的执行顺序、状态与检查点；宿主应用决定图的形状与规则。](/learn-agent-rust/figures/graph-orchestration-layers.svg)

左边回答本轮生成什么请求，右边回答程序接下来执行哪里。一个节点既可以调用模型，也可以只做输入校验、等待审批或归并结果。

## 2. 从熟悉的 LangGraph 概念找到位置

adk-graph 的设计明显参照了 LangGraph：官方 [Graph API](https://docs.langchain.com/oss/python/langgraph/graph-api) 里的状态与 reducer、条件边、超步、检查点和 interrupt，在 adk-graph 里大多有同名或近名的对应。下表是学习上的对照；具体行为以固定源码和本组实验为准，不能只凭名字相似推断实现相同。

| 关注点 | LangGraph 阅读入口 | adk-graph 实现与本课程验证的边界 |
| --- | --- | --- |
| 状态 | State schema、reducer | `StateSchema` 声明通道，每个通道一个归并规则：覆盖、追加列表、求和（按浮点数）或自定义。`with_strict_channels` 才拒绝写未声明的通道。 |
| 节点 | Node 函数 | `add_node_fn` 的异步函数，读 `ctx.state`（一份拷贝），返回 `NodeOutput` 列出要写的通道。 |
| 顺序与分支 | 普通边、条件边、`Command(goto=…)` | `add_edge`、`add_conditional_edges`（未列出的路由键是运行时错误），或节点返回 `with_goto` 替代自己的出边。 |
| 执行模型 | 超步（Pregel） | 同样按超步执行：一步运行所有就绪节点，一起应用更新。一次 `invoke` / `stream` 跑到结束、暂停或出错；`with_recursion_limit` 限制一次运行的超步数（默认 100），暂停后恢复会接着累计。 |
| 等待外部输入 | `interrupt` / `Command(resume=…)` | 节点返回 `NodeOutput::interrupt_with_data`，可附答案格式；恢复时这个节点**重新运行**，用 `ctx.resume_value()` 读到回答。严格恢复只认框架算出的暂停 ID。 |
| 持久化 | checkpointer、thread | `Checkpointer` trait，自带内存与 SQLite 实现；检查点按线程保存，版本只增不减，并发写入后到者报 `CheckpointConflict`。框架不核对图的版本，由宿主补上。 |
| 并行与汇合 | 多条出边、reducer | 两条普通出边就是并行；有多条无条件入边的节点自动等上游到齐、只运行一次（条件边不算）。同一步的更新按节点名顺序应用，业务归并仍要自己写。 |
| 子图 | 子图作为节点 | `SubgraphNode` 包装另一张编译好的图；`isolated()` 后只交换声明的通道，映射错误在父图编译时发现。 |

LangGraph 的恢复语义与设计见官方 [Interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts)、[Persistence](https://docs.langchain.com/oss/python/langgraph/persistence)。两者一个重要的相同点是“暂停的节点恢复时从头重跑”，所以暂停之前的代码不能有不可重复的效果。本课程着重验证的是答案绑定：adk-graph 的严格恢复模式要求按暂停 ID 回答，ID 由线程、步号、节点、问题、数据和答案格式算出，其中任何一项变了 ID 就变，针对旧问题的回答会被拒绝。

## 3. 三章共用一条升级审查故事

| 章节 | 新增问题 | 实际实验 |
| --- | --- | --- |
| [图状态、条件路由与有界循环](./graph-state-routing.md) | 未达要求时怎样修复再检查？ | 状态通道与归并规则、条件边、`with_goto`、超步上限，以及建图检查与运行时检查各能发现什么。 |
| [图暂停、检查点与恢复](./graph-pause-resume.md) | 等待批准后退出，另一个进程怎样继续？ | SQLite 检查点、按暂停 ID 严格恢复、答案格式校验、修订后旧回答失效、并发写入冲突与图版本检查。 |
| [图并行、归并与子图](./graph-parallel-subgraphs.md) | 两项检查怎样同时运行并可靠汇总？ | 超步并行与自动汇合、业务归并、失败后只重跑失败节点、同步更新冲突、超时与隔离子图。 |

三章全部有真实框架代码、测试、输出和下载包解压复验。模型质量、外部效果与生产审批各有自己的验收需求。后续课程再将这些编排概念用于知识输入、长期任务与完整集成。

这些章节建立编排机制。[第五部分 · 常见 Agent 设计模式](./agent-design-patterns.md)进一步从业务问题组织提示链、路由、并行、规划重规划、协调交接、评估修复与人工介入。G01 的规则修复循环、G02 的 CLI 审批和 G03 的固定并行检查是已有基础；动态计划、生产审批和角色交接仍需要分别实现和验证。

## 4. 一次执行时要追踪的四个对象

| 对象 | 回答什么 | 生命周期 |
| --- | --- | --- |
| `CompiledGraph` | 存在哪些节点，边和路由是什么，哪些节点是汇合点？ | 每次启动从代码重新构建并编译；编译时检查悬空的边和缺少的起点。 |
| 状态（`State`） | 当前业务输入、步骤结果与额度是什么？ | 按通道和归并规则更新；随检查点保存。 |
| 线程与检查点 | 这条执行走到第几步，下一步运行哪些节点，有没有未回答的暂停？ | `ExecutionConfig::new(线程 ID)` 指定线程；检查点由 `Checkpointer` 保存和加载。 |
| 宿主程序 | 何时启动、回答暂停、拒绝不兼容的数据？ | CLI、请求处理器或服务循环；负责图版本、终态与业务验收。 |

图编排本身不会把工具效果变成可恢复事务，也不会自动判断用户目标是否完成。前者在[外部操作可靠性](./side-effect-reliability.md)继续验证，后者在[目标控制](./workflow-and-goal-control.md)独立检查。

::: warning 常见误区
- 一个节点有两条普通出边，两个后继在下一个超步**都**运行；二选一要用条件边或 `with_goto`。
- 节点里拿到的 `ctx.state` 是拷贝，直接改它不会写回状态；要写的通道放进 `NodeOutput`。
- 一次 `invoke` 不是“只运行一个节点”，而是一直跑到结束、暂停或出错；要限制步数用 `with_recursion_limit`，它数的是整次运行，暂停恢复前后的步数合在一起算。
- 检查点能恢复状态，不能证明恢复用的是同一张图：节点改了名，框架照样加载，并静默结束。图版本要由宿主检查。
:::

## 本章结论

课程从此沿两条主线推进：模型与工具交互解释请求和结果，图编排解释状态和控制权。先把编排作为独立能力学清楚，再把模型调用放进节点，才能判断错误发生在生成、路由、检查点还是业务效果边界。

## 检查理解

1. “模型要读文件”与“下一节点是 repair”分别由哪一层表达？

   <details><summary>参考答案</summary>

   结构化工具请求由 Agent 层（模型与工具的循环）表达，下一节点由图的边、路由函数或节点的 `with_goto` 决定；工具执行前还要经过授权。

   </details>

2. 图可以完全不调用模型吗？

   <details><summary>参考答案</summary>

   可以。校验、等待审批、读写和归并都可以是普通业务节点。本组实验以固定规则验证图语义。

   </details>

3. 为什么只保存状态还不够恢复？

   <details><summary>参考答案</summary>

   还要知道下一步运行哪些节点、有没有未回答的暂停、检查点属于哪个线程，以及恢复时重建的图与保存时是否兼容。前三项在检查点里，最后一项框架不检查，要由宿主核对图版本。

   </details>

4. 两项并行检查都成功，就能直接拼接最终报告吗？

   <details><summary>参考答案</summary>

   还要检查成员是否齐全、结果能否合并，并明确冲突和缺失怎样处理。框架只保证汇合节点等上游到齐、同一步的更新按固定顺序应用；“齐了是否可以发布”是业务归并规则。

   </details>

5. 一次图调用返回成功，等于用户目标完成吗？

   <details><summary>参考答案</summary>

   不等于。图结束只说明调度走完了；转人工的 `handoff` 同样是正常结束。业务目标仍要依据状态里的结果、文件和独立验收条件检查。

   </details>

## 参考资料

- [LangGraph Graph API](https://docs.langchain.com/oss/python/langgraph/graph-api)、[Interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts)、[Persistence](https://docs.langchain.com/oss/python/langgraph/persistence)，查阅：2026-11-08。
- [adk-graph 固定源码](https://github.com/zavora-ai/adk-rust/tree/98515241133d24f7e41f8fd272649035416a142f/adk-graph/src)：本课程真实运行的接口与语义基线。

从[图状态、条件路由与有界循环](./graph-state-routing.md)开始实际建图。
