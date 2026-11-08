---
title: "第 5 章：图状态、条件路由与有界循环"
description: "真实运行 graph-flow，学习类型化业务状态、条件边、GoTo、逐节点推进与有界修复，并检查常见路由误区。"
pageClass: learn-agent-rust-course
prev:
  text: 第 4 章 · 生命周期与 Hooks
  link: /learn-agent-rust/hooks
next:
  text: 第 6 章 · 图暂停、会话存储与恢复
  link: /learn-agent-rust/graph-pause-resume
---

# 第 5 章：图状态、条件路由与有界循环

[课程总览](./index.md) · [上一章](./hooks.md) · [图编排导读](./graph-orchestration.md) · [下一章](./graph-pause-resume.md)

::: tip 本章学习目标
- 给升级审查定义状态，区分业务结果、节点返回值和会话游标。
- 用条件边与 GoTo 实现修复回路，解释何时控制权返回宿主。
- 验证无后继、错误跳转、共享 Context 与步数上限，判断图编译检查的范围。

**前置：** [工具注册与图调度](./tools-and-graph.md)。本章只用 graph-flow，先把图的语义单独看清。

**实践方式：** <a href="/learn-agent-rust/graph-state-routing.zip" download>下载独立工程</a>，Rust 1.99.1、graph-flow 0.8.1 固定 revision；首次获取依赖需要网络，运行无需模型或数据库。
:::

升级报告已经有一个初稿，检查要求至少达到等级 2。第一稿只有等级 1。我们希望程序先检查，再修复、重新检查，达到要求就接受，连续两次修复仍不合格就转人工。

这次先用整数等级模拟固定审查规则。报告质量不是实验目标；我们要观察每一步怎样改变状态、怎样决定后继，以及什么时候必须停止。

<LearnAgentRustMap active="graph-state-routing" />

<!-- experiment-library:start -->

全书实验可从[统一代码库](./experiments.md#graph-state-routing)下载；解压后进入 `chapters/graph-state-routing/`，或运行 `python3 run.py run G01`。

<!-- experiment-library:end -->

::: info 唯一源码与验证范围
下文片段均来自<a href="/learn-agent-rust/code/graph-state-routing/src/main.rs" download>完整 main.rs</a>，工程同时提供 Cargo.lock 与运行说明。真实调用固定 `graph-flow`，节点采用确定性业务规则，没有 `langchain-rust` 或模型请求。实验标识 G01 用于命令定位，正文使用正常主线章号。
:::

## 1. 先定义什么东西需要跨步骤保留

初稿等级、目标要求、修复次数和最终结果都属于业务状态。节点名称属于编排，不能混在一句“执行成功”的日志里。我们将业务数据组成 `Review`，保存在 `Context` 的 `review` 键中：

<<< @/public/learn-agent-rust/code/graph-state-routing/src/main.rs#state

| 字段 | 为什么保留 | 谁更新 |
| --- | --- | --- |
| `schema` | 判断数据是否符合当前节点预期 | 创建会话时设定，入口读取时校验。 |
| `draft`、`required` | 决定是否通过检查 | 准备/修复节点更新初稿，要求来自输入。 |
| `repairs`、`max_repairs` | 限制业务修复次数 | 修复节点检查后递增。 |
| `outcome` | 区分接受与人工交接 | 两个终态节点明确设置。 |
| `trace` | 记录实际经过的节点 | 每个业务节点追加。 |

`Context` 本身是动态键值容器。`get::<Review>` 失败时可能是键不存在，也可能是内容不能反序列化。这里把两者都视为契约错误，拒绝继续；默认返回一个“空的好状态”可能把错误数据带到接受分支。

## 2. 图的形状来自业务分工

先预测正常轨迹：prepare → check → repair → check → accept。然后看每条边有没有明确原因。

![审查从准备到检查，满足要求则接受，否则在有限额度内修复再检查，耗尽后交给人工。](/learn-agent-rust/figures/g01-state-routing.svg)

横向读通过路径，再沿下方回路看修复。`handoff` 也是图的正常结束节点，但它的业务结果是 `needs_human`；因此图的 `Completed` 与业务成功要分开读。

<<< @/public/learn-agent-rust/code/graph-state-routing/src/main.rs#nodes

一个节点有三个职责：读取并校验输入，完成当前业务变更，返回下一步的控制意图。`TaskResult.response` 只是可选响应；必须保留的数据显式写入 Context。`TaskResult` 由框架补上实际执行的 `task_id`，路由据此寻找出边。

本例将状态组装好后一次写回 `review`。这便于阅读，但不会把任意多个 `Context.set` 变成事务。节点已经修改状态后返回错误，框架也不会自动恢复到入口快照。

## 3. 条件边与 GoTo 各解决什么

<<< @/public/learn-agent-rust/code/graph-state-routing/src/main.rs#graph

固定版本的 `add_conditional_edge(from, predicate, yes, no)` 增加一个带谓词的 yes 候选，以及一个无条件 no 后备。`find_next_task` 按插入顺序查找：第一个满足的条件优先；没有条件满足时，使用第一个无条件后备。

这带来两个设计要求：谓词应只读当前状态，避免边检查产生业务效果；多个条件可能同时为真时，要显式规定优先级，或者把路由结果先计算成一个互斥枚举。增加两条普通边只提供多个候选，不会让框架并行执行两个节点。

本例的 `check` 用条件边表达“通过 / 修复”。`repair` 用 `GoTo` 表达“回到检查 / 转人工”，目标必须已经注册；`GoTo` 可以跳到没有静态边连接的节点，所以完整可达路径不能只靠静态边图推断。

## 4. 一次调用究竟运行几个节点

| `NextAction` | 固定版本对游标的处理 | 调用返回时 |
| --- | --- | --- |
| `Continue` | 查找出边，更新到后继 | 返回 `Paused`，后继尚未运行。 |
| `ContinueAndExecute` | 查找出边并立即运行后继 | 可在本次调用内继续多个节点。 |
| `GoTo(id)` | 核对目标存在并更新游标 | 返回 `Paused`，目标留待下次执行。 |
| `WaitForInput` | 保持当前节点 | 返回 `WaitingForInput`，等待宿主提供输入。 |
| `End` | 保持结束节点 | 返回 `Completed`；宿主决定是否再调用。 |

本例逐步版正常运行 5 次框架调用。连续版会让 prepare、check 和 repair 在第一次调用内运行；repair 返回 GoTo 后控制权返回宿主，第二次调用再执行 check、accept。因此业务 trace 相同，框架调用数是 2。

运行：

```sh
cargo run --locked -- normal
cargo run --locked -- direct
cargo run --locked -- exhausted
cargo run --locked -- probes
```

逐步版实际输出：

<<< @/public/learn-agent-rust/outputs/g01-normal.txt

连续版实际输出：

<<< @/public/learn-agent-rust/outputs/g01-direct.txt

4 项 Rust 测试中的一项比较两种执行方式的完整 `Review`，包括 trace、修复数和结果。它没有把“一次调用”和“一个业务节点”混为同一个指标。

## 5. 循环必须有两种额度

业务层的 `max_repairs=2` 限制修复次数。宿主驱动器的累计调用上限覆盖跨调用的 `GoTo` 与 `Continue`。框架的 `with_max_execution_steps` 则限制一次 `execute_session` 内连续的 `ContinueAndExecute` 跳转；它不会替宿主累计多次调用。

额度检查发生的位置也要看清：固定版本在当前节点已经运行、游标已更新后才检查链式跳转数。触发上限不是“这次节点完全没运行”，已发生的 Context 变更仍在。

<<< @/public/learn-agent-rust/outputs/g01-exhausted.txt

本例转人工仍返回图的 Completed，业务字段保留 `needs_human`。后续[目标控制](./workflow-and-goal-control.md)会进一步验证“程序正常返回”和“用户目标完成”的区别。

## 6. 建图检查与运行时检查分别能发现什么

<<< @/public/learn-agent-rust/code/graph-state-routing/src/main.rs#probes

<<< @/public/learn-agent-rust/outputs/g01-probes.txt

构建时，悬空静态边和不存在的显式起点会被拒绝。运行时才知道动态 GoTo 是否存在、状态是否符合 schema、循环是否触发额度。一个没有出边却返回 Continue 的节点，在固定版本会保持原游标并返回 Paused；宿主若盲目续跑，就会重复这个节点。

最后一个重要细节是 `Context.clone()`：它复制的是共享句柄，修改 clone 也会改变原对象。本例通过序列化再反序列化创建独立快照，测试确认它不再共享数据。需要隔离的子图会在[并行与子图](./graph-parallel-subgraphs.md)用新 Session 实现。

::: warning 常见误区
- GraphBuilder 的 build 验证不保证业务路径正确、循环终止或所有分支可达。
- 条件边的 else 是后备；多组条件叠加时应核对插入顺序和覆盖关系。
- Context 线程安全的单次读写不代表跨读写事务，更不代表节点失败自动回滚。
- 本例的等级规则是固定夹具，只验证编排；没有验证模型审查质量。
:::

## 本章结论

先定义业务状态，再安排节点、条件与回路。每次运行都同时观察业务结果、实际 trace、Session 游标和框架状态；用业务额度、调用额度和单次连续执行额度分别约束它们负责的边界。

## 迁移思考：路由正确与业务完成分别检查

图顺利走到 accept，就能证明升级报告合格吗？

<details><summary>参考推演</summary>

先核对条件读取的是当前且有效的审查结果，再检查报告本身满足独立要求；路由只能证明按给定状态选择了路径。

迁移到退款审批时，同样需要独立核对订单事实和额度，不能把进入批准节点当作业务正确的证据。

</details>

## 检查理解

1. 为什么要分开 `outcome` 和框架的 Completed？

   <details><summary>参考答案</summary>

   Completed 表示图本次到达 End。接受、拒绝、转人工都可以这样结束，业务结果需要应用状态表达。

   </details>

2. 两个普通出边会并行吗？

   <details><summary>参考答案</summary>

   固定版本只选择第一个适用后继；并行使用 FanOutTask 或应用明确的并发机制。

   </details>

3. GoTo 为什么还需要宿主累计额度？

   <details><summary>参考答案</summary>

   它会返回宿主，下一次调用重新开始框架的单次计数。跨调用循环需要外层累计限制。

   </details>

4. 克隆 Context 适合用作失败回滚快照吗？

   <details><summary>参考答案</summary>

   不适合，clone 共享底层状态。需要独立数据快照或事务，并明确外部效果的恢复策略。

   </details>

5. 连续版调用数减少，是否证明运行更快？

   <details><summary>参考答案</summary>

   只说明控制权交接次数减少。时延和吞吐需要独立测量，本章没有性能结论。

   </details>

## 参考资料

- 固定版本 [graph.rs](https://github.com/a-agmon/rs-graph-llm/blob/9bbca193f20a8c4ba23289621549ecb3d35fee64/graph-flow/src/graph.rs)：执行、条件查找与建图检查。
- [task.rs](https://github.com/a-agmon/rs-graph-llm/blob/9bbca193f20a8c4ba23289621549ecb3d35fee64/graph-flow/src/task.rs)与 [context.rs](https://github.com/a-agmon/rs-graph-llm/blob/9bbca193f20a8c4ba23289621549ecb3d35fee64/graph-flow/src/context.rs)：返回动作与共享状态。

下一章进入[图暂停、会话存储与恢复](./graph-pause-resume.md)，让另一个进程继续当前游标。
