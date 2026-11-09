---
title: "图编排导读：从 LangGraph 概念到 graph-flow 实践"
description: "建立模型交互与图编排两条主线，沿状态、路由、会话恢复、并行归并和子图学习 graph-flow。"
pageClass: learn-agent-rust-course
---

# 图编排导读：从 LangGraph 概念到 graph-flow 实践

[课程总览](./index.md) · [学习路径](./learning-path.md) · [开始图状态与路由](./graph-state-routing.md)

::: tip 本章学习目标
- 区分一次模型请求与一段工作流执行：谁提出动作，谁决定下一步运行哪里。
- 建立 State、Node、Edge、Session、Storage 和并行归并的联系。
- 沿三个可独立运行的 graph-flow 工程验证编排语义，再回到完整 Agent。

**前置：** [最小 Agent 循环](./agent-loop.md)与[工具注册与图调度](./tools-and-graph.md)。后续恢复章还需要理解[工具权限](./permissions.md)。

**实践方式：** 三章分别提供 Cargo 工程与下载包，真实使用固定 graph-flow 0.8.1，无模型密钥；首次下载依赖需要网络。
:::

## 1. 工具循环之后，还缺什么

一个助手可以反复调用模型和工具。现在让它完成升级审查：准备报告、检查要求、修复缺项、等待批准，再汇总结果。此时问题已经从“怎样调用一个模型”扩大到“不同阶段怎样共享状态，怎样决定下一步，退出以后从哪里继续”。

我们把这条流程做成三个递进实验：先用固定业务规则看清图的语义，再加入真实会话存储，最后引入并行检查与子图封装。节点以后可以调用 `langchain-rust`，本组实验先用确定性逻辑让编排行为容易观察。

![langchain-rust 负责消息与模型工具交互，graph-flow 负责节点、状态、路由与会话推进，宿主应用把两者连接并约束执行。](/learn-agent-rust/figures/graph-orchestration-layers.svg)

左边回答本轮生成什么请求，右边回答程序接下来执行哪里。一个节点既可以调用模型，也可以只做输入校验、读取、等待或归并。

## 2. 从熟悉的 LangGraph 概念找到位置

LangGraph 的官方 [Graph API](https://docs.langchain.com/oss/python/langgraph/graph-api)以状态、节点、边与执行步骤组织图，并说明 reducer、条件路由和并行等概念。下表是学习上的职责对照；两库的具体行为必须分别验证，不能据名称相似推断实现相同。

| 关注点 | LangGraph 阅读入口 | 本课程 graph-flow 实现与边界 |
| --- | --- | --- |
| 状态 | State schema、状态更新与 reducer | `Context` 保存可序列化值；业务层定义有 schema 的结构体，显式读写和校验。 |
| 节点 | Node 函数 | `Task::run(Context) -> TaskResult`，结果包含 `NextAction`。 |
| 顺序与分支 | 普通边、条件边 | `GraphBuilder::add_edge`、`add_conditional_edge`，或节点返回 `GoTo`。 |
| 执行位置 | 图的调度与检查点 | `Session.current_task_id` 表示当前位置；`execute_session` 的返回点取决于 `NextAction`。 |
| 等待外部输入 | interrupt / resume | 本例用 `WaitForInput` 停留在当前节点，写入输入后重新运行该节点。 |
| 持久化 | checkpointer、thread 与持久执行 | 实现 `SessionStorage`，由 `FlowRunner` 执行 load → run → save；图与状态版本检查由应用补充。 |
| 并行与归并 | 并行边、状态 reducer 等 | 固定版本用 `FanOutTask` 在一个节点内部并发；应用编写归并节点，没有自动业务 reducer。 |
| 子图 | 图组合、父子状态传递 | 本例用应用 `Task` 包装子 `Graph`，新建 Session 并明确输入输出；父子持久恢复未实现。 |

LangGraph 的恢复语义与设计见官方 [Interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts)、[Persistence](https://docs.langchain.com/oss/python/langgraph/persistence)。本教程用它们帮助提出问题，Rust 的实际行为以固定源码和实验为准。

## 3. 三章共用一条升级审查故事

| 章节 | 新增问题 | 实际实验 |
| --- | --- | --- |
| [图状态、条件路由与有界循环](./graph-state-routing.md) | 未达要求时怎样修复再检查？ | 类型化状态、条件边、GoTo、逐步/连续执行、错误路径。 |
| [图暂停、会话存储与恢复](./graph-pause-resume.md) | 等待批准后退出，另一个进程怎样继续？ | 真实 SessionStorage trait、SQLite 事务、修订绑定、版本冲突与终态保护。 |
| [图并行、归并与子图](./graph-parallel-subgraphs.md) | 两项检查怎样同时运行并可靠汇总？ | FanOutTask、Barrier、局部失败、共享更新冲突、显式 reducer 与隔离子图。 |

三章全部有真实框架代码、测试、输出和下载包解压复验。模型质量、外部发布与跨进程子图恢复各有自己的验收需求。后续课程再将这些编排概念用于知识输入、长期任务与完整集成。

## 4. 一次执行时要追踪的四个对象

| 对象 | 回答什么 | 生命周期 |
| --- | --- | --- |
| `Graph` | 存在哪些节点，普通边和条件是什么？ | 启动时从代码重新构建，包含编译后的处理函数。 |
| `Context` | 当前业务输入、步骤结果与预算是什么？ | 节点共享；需要持久化时序列化为会话数据。 |
| `Session` | 这个会话目前在哪个节点，版本是多少？ | 通过存储保存和加载，绑定图身份与业务 schema。 |
| 宿主驱动器 | 何时继续、等待、保存或交回控制？ | CLI、请求处理器或服务循环；负责终态与累计额度。 |

图编排本身不会把工具效果变成可恢复事务，也不会自动判断用户目标是否完成。前者在[外部操作可靠性](./side-effect-reliability.md)继续验证，后者在[目标控制](./workflow-and-goal-control.md)独立检查。

::: warning 常见误区
- 普通边从一个节点指向两个节点，在固定版本中只会选中一个后继；并行要显式使用相应机制。
- `Context.clone()` 共享底层状态；创建隔离子图要新建上下文并传递字段。
- `ContinueAndExecute` 可以在一次调用运行多个节点，`FlowRunner.run()` 不能一概理解为只执行一个节点。
- LangGraph 的执行模型、检查点历史、reducer 与动态分发能力不能直接视为 graph-flow 已有的同等接口。
:::

## 本章结论

课程从此沿两条主线推进：模型与工具交互解释请求和结果，图编排解释状态和控制权。先把编排作为独立能力学清楚，再把模型调用放进节点，才能判断错误发生在生成、路由、存储还是业务效果边界。

## 检查理解

1. “模型要读文件”与“下一节点是 ExecuteTools”分别由哪一层表达？

   <details><summary>参考答案</summary>

   结构化工具请求由模型交互层表达，下一节点由编排与宿主策略决定；动作执行前还要检查授权。

   </details>

2. 图可以完全不调用模型吗？

   <details><summary>参考答案</summary>

   可以。校验、等待、读写和归并都可以是普通业务节点。本组实验以固定规则验证图语义。

   </details>

3. 为什么只保存 Context 还不够恢复？

   <details><summary>参考答案</summary>

   还要知道下一执行位置、会话身份、图版本和状态 schema。恢复时必须重新构建与数据兼容的图。

   </details>

4. 并行子任务都成功就能直接拼接最终报告吗？

   <details><summary>参考答案</summary>

   还要检查成员是否齐全、身份是否唯一、结果是否可合并，并明确冲突和顺序。应用负责归并契约。

   </details>

5. 一次框架调用返回成功，等于用户目标完成吗？

   <details><summary>参考答案</summary>

   框架状态只能说明调度结果。业务目标仍要依据文件、记录和独立验收条件检查。

   </details>

## 参考资料

- [LangGraph Graph API](https://docs.langchain.com/oss/python/langgraph/graph-api)、[Interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts)、[Persistence](https://docs.langchain.com/oss/python/langgraph/persistence)，查阅：2026-11-08。
- [graph-flow 固定源码](https://github.com/a-agmon/rs-graph-llm/tree/9bbca193f20a8c4ba23289621549ecb3d35fee64/graph-flow/src)：本课程真实运行的接口与语义基线。

从[图状态、条件路由与有界循环](./graph-state-routing.md)开始实际建图。
