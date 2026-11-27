---
title: "第 5 章：图状态、条件路由与有界循环"
description: "用 ADK-Rust 3.0 的 adk-graph 实现升级审查的修复回路：状态通道与归并规则、条件边与 with_goto、超步上限，并检查建图与运行时各能发现什么。"
pageClass: learn-agent-rust-course
prev:
  text: 第 4 章 · 生命周期与 Hooks
  link: /learn-agent-rust/hooks
next:
  text: 第 6 章 · 图暂停、检查点与恢复
  link: /learn-agent-rust/graph-pause-resume
---

# 第 5 章：图状态、条件路由与有界循环

[课程总览](./index.md) · [上一章](./hooks.md) · [图编排导读](./graph-orchestration.md) · [下一章](./graph-pause-resume.md)

::: tip 本章学习目标
- 给升级审查定义图状态：哪些字段跨步骤保留，每个字段的新值怎样和旧值合并。
- 用条件边和 `with_goto` 实现修复回路，说清“谁决定下一步”。
- 区分业务额度和框架的超步上限，并验证建图检查与运行时检查各能发现什么。

**前置：** [工具注册与图调度](./tools-and-graph.md)。本章只用 adk-graph，先把图的语义单独看清。

**实践方式：** <a href="/learn-agent-rust/graph-state-routing.zip" download>下载独立工程</a>，按[第 4 节](#hands-on)取一次 ADK-Rust 源码后运行；无需模型或数据库。
:::

::: info 本章已迁移到 ADK-Rust 3.0
本章实验基于 ADK-Rust 3.0 发布候选版的 adk-graph（固定提交，尚未发布到 crates.io）。旧版本章用 graph-flow 实现，可从 git 标签 `learn-agent-rust-v1` 取得。两者的执行模型不同：graph-flow 由宿主一步一步推进游标；adk-graph 按“超步”一次跑到结束、暂停或出错。第 6 节的对应表列出了这带来的变化。
:::

升级报告已经有一个初稿，检查要求至少达到等级 2，第一稿只有等级 1。我们希望程序先检查，再修复、重新检查，达到要求就接受，连续两次修复仍不合格就转人工。

这次先用整数等级模拟固定审查规则。报告质量不是实验目标；我们要观察每一步怎样改变状态、怎样决定后继，以及什么时候必须停止。

<LearnAgentRustMap active="graph-state-routing" />

<!-- experiment-library:start -->

全书实验可从[统一代码库](./experiments.md#graph-state-routing)下载；解压后进入 `chapters/graph-state-routing/`，或运行 `python3 run.py run G01`。

<!-- experiment-library:end -->

::: info 唯一源码与验证范围
下文片段均来自<a href="/learn-agent-rust/code/graph-state-routing/src/main.rs" download>完整 main.rs</a>，工程同时提供 Cargo.lock 与运行说明。图的执行、路由、归并规则和超步上限都是 adk-graph 的真实实现，节点采用确定性业务规则，不调用模型。实验标识 G01 用于命令定位，正文使用正常主线章号。
:::

## 1. 先定义什么东西需要跨步骤保留

初稿等级、目标要求、修复次数、最终结果和经过的节点，都属于要跨步骤保留的状态。adk-graph 的状态是一组**通道**，每个通道带一个归并规则（reducer），决定节点写入的新值怎样和旧值合并：

<<< @/public/learn-agent-rust/code/graph-state-routing/src/main.rs#state

| 通道 | 归并规则 | 谁写入 |
| --- | --- | --- |
| `draft`、`required` | 覆盖（默认） | `required` 来自输入，`draft` 由准备和修复节点更新。 |
| `repairs` | 计数：写入的值加到原值上 | 修复节点每次写 1。 |
| `outcome` | 覆盖 | 两个终态节点明确设置。 |
| `trace` | 列表：写入单个值追加一项，写入数组则逐项追加 | 每个业务节点写自己的名字。 |

节点不直接改状态，而是返回 `NodeOutput`，里面列出要写哪些通道；框架在这一步结束时按归并规则应用。所以 `trace` 不需要节点自己读出旧列表再拼上，`repairs` 也不需要读出旧值再加一。

`level` 读取等级字段时，值不存在或不是非负整数都算契约错误，拒绝继续；默认当成 0 走下去，可能把错误数据带到接受分支。这里有一个实测到的细节：计数通道按浮点数累加，写入 `1`，读出来是 `1.0`，所以按数值而不是按整数读取（见第 6 节的 `counter_channel` 探针）。

## 2. 图的形状来自业务分工

先预测正常轨迹：prepare → check → repair → check → accept。然后看每条边有没有明确原因。

![审查从准备到检查，满足要求则接受，否则在有限额度内修复再检查，耗尽后交给人工。](/learn-agent-rust/figures/g01-state-routing.svg)

横向读通过路径，再沿下方回路看修复。`handoff` 也是图的正常结束节点，但它的业务结果是 `needs_human`；因此“图运行完成”与“业务成功”要分开读。

<<< @/public/learn-agent-rust/code/graph-state-routing/src/main.rs#nodes

一个节点有三个职责：读取并校验输入，完成当前业务变更，返回下一步的控制意图。修复节点是这里最有意思的一个：它自己决定下一步，额度还有就修复并回到 `check`，额度用完就转人工。

## 3. 条件边与 with_goto 各解决什么

<<< @/public/learn-agent-rust/code/graph-state-routing/src/main.rs#graph

两种路由方式：

| 方式 | 谁决定 | 什么时候确定可能的去处 | 本例用在 |
| --- | --- | --- | --- |
| 条件边 `add_conditional_edges(节点, 路由函数, [(键, 目标)])` | 路由函数读状态，返回一个键 | 建图时列出全部目标，图里看得见 | `check`：接受或修复 |
| `NodeOutput::with_goto([目标])` | 节点自己，在写状态的同一步里 | 运行时，可以指向任何节点，图里没有边 | `repair`：回到检查或转人工 |

几条规则值得记住（都在第 6 节的探针里验证）：

- 路由函数返回了没有列出的键，或者 `with_goto` 指向不存在的节点，都是**运行时**错误（`UnknownRouteTarget`），建图时发现不了。
- 节点设置了 `with_goto` 就不再走它声明的出边，goto 替代出边。
- 一个节点有两条普通出边时，两个后继在下一个超步**都**运行，这是并行，不是二选一（[第 7 章](./graph-parallel-subgraphs.md)展开）。

路由函数应只读当前状态，不要在里面产生业务效果。条件多时，先把结果算成一个互斥的键，再交给条件边，比叠加多组条件更容易核对。

## 4. 一次调用跑多少步 {#hands-on}

adk-graph 按**超步**执行：每一步运行当前所有就绪的节点，等它们都完成，应用它们的状态更新，再决定下一步运行哪些节点。一次 `invoke` 或 `stream` 会一直跑到结束、暂停或出错，宿主不需要一步一步推进。

<<< @/public/learn-agent-rust/code/graph-state-routing/src/main.rs#run

用 `stream` 而不是 `invoke`，是为了在每个超步结束时收到一个 `StepComplete` 事件，看清每一步跑了哪个节点。

下载并解压<a href="/learn-agent-rust/graph-state-routing.zip" download>本章工程</a>，先取一次 ADK-Rust 源码，再运行：

```sh
cd graph-state-routing
python3 fetch-adk-rust.py ../adk-rust    # 需要 git 与 GitHub 访问；不行时加 --method cdn
cargo run --locked -- normal
cargo run --locked -- exhausted
cargo run --locked -- runaway
cargo run --locked -- probes
```

命令要在 `graph-state-routing` 目录里运行。编译时会看到 adk-core 的 3 条弃用警告（上游固定 Rust 1.95.0），不影响运行和检查。

正常运行的实际输出：

<<< @/public/learn-agent-rust/outputs/g01-normal.txt

五个超步各跑一个节点。`repairs=1` 是计数通道累加出来的：修复节点只写了“加 1”；`draft` 是覆盖通道，`draft=2` 是修复节点自己算好的新初稿。

## 5. 循环必须有两种额度

业务层的 `MAX_REPAIRS=2` 限制修复次数：

<<< @/public/learn-agent-rust/outputs/g01-exhausted.txt

修复无效，两次额度用完后第三次进入 `repair` 时转人工。图正常结束，业务结果是 `needs_human`。后续[目标控制](./workflow-and-goal-control.md)会进一步验证“程序正常返回”和“用户目标完成”的区别。

业务额度依赖代码正确地计数。如果修复节点忘了写 `repairs`（`runaway` 场景模拟这个 bug），业务额度永远到不了，就只能靠框架的超步上限停下：

<<< @/public/learn-agent-rust/outputs/g01-runaway.txt

`with_recursion_limit(12)` 让运行在第 12 个超步后以 `RecursionLimitExceeded` 结束（不设置时默认 100）。上限是在节点已经运行、状态已经保存之后才触发的：检查点里留着 12 条轨迹，`outcome` 仍是空的。触发上限不是“什么都没发生”，已经发生的状态变更还在。还要注意上限数的是这次运行从头开始的步数：运行中途暂停或失败、之后再恢复，之前走过的步也算在内（下一章的暂停恢复会遇到）。

两种额度保护不同的东西：业务额度表达“最多修几次”，超步上限是兜底，防止代码错误让循环永远跑下去。

## 6. 建图检查与运行时检查分别能发现什么

<<< @/public/learn-agent-rust/code/graph-state-routing/src/main.rs#probes

<<< @/public/learn-agent-rust/outputs/g01-probes.txt

| 探针 | 结果 | 说明 |
| --- | --- | --- |
| `dangling_edge` | 建图时拒绝 | 边指向不存在的节点。 |
| `missing_start` | 建图时拒绝 | 没有从 `START` 出发的边。 |
| `bad_goto` | 运行时拒绝 | `with_goto` 的目标只有运行时才知道。 |
| `unmapped_route` | 运行时拒绝 | 路由函数返回了没有声明的键。 |
| `no_edge` | 正常完成 | 没有出边的节点结束这条分支，运行完成。 |
| `two_edges` | 三个节点都运行 | 两条普通出边是并行，不是二选一。 |
| `typo_channel` | 不报错 | 节点 b 把 `trace` 拼成了 `traces`：框架按覆盖通道收下这个新名字，列表通道 `trace` 里少了 b。 |
| `strict_channels` | 拒绝 | `with_strict_channels()` 下，节点照常运行，框架在应用它的更新时发现未声明的通道，以 `UndeclaredChannel` 结束运行。 |
| `local_mutation` | 改动无效 | 节点拿到的是状态的副本，改本地副本不影响图；只有 `NodeOutput` 里的更新才生效。 |
| `malformed_required` | 运行时拒绝 | 输入不符合契约，节点返回错误，运行以错误结束。 |
| `counter_channel` | `n=2.0` | 计数通道按浮点数累加。 |

建图检查只看结构：边的两端是否存在、有没有入口。目标是否可达、路由函数会返回什么、状态是否符合契约、循环会不会结束，都要到运行时才知道。

### 与旧版场景的对应

| 旧版（graph-flow） | 新版（adk-graph） | 说明 |
| --- | --- | --- |
| `normal`：宿主逐节点推进，5 次框架调用 | `normal`：一次 `stream`，5 个超步 | adk-graph 没有“由宿主推进一步”的执行方式，用超步事件观察每一步。 |
| `direct`：连续执行，2 次框架调用 | 删除 | 一次调用就跑完，“调用次数”不再是要观察的量。 |
| `exhausted` | 保留 | 业务额度用完转人工。 |
| 宿主累计调用上限、单次链式上限 | `runaway`：超步上限 | 由 `with_recursion_limit` 提供；新增“忘了计数”的场景说明它为什么必要。 |
| 探针：无边节点暂停在原游标 | 探针：无边节点结束分支 | 两个框架的行为相反。 |
| 探针：重叠条件取第一个 | 探针：路由键未声明时报错；两条出边并行 | 条件边改为“函数返回一个键”，重叠条件的问题不再存在。 |
| 探针：`Context.clone()` 共享数据 | 探针：节点改本地副本无效 | adk-graph 的状态按值传给节点。 |

## 框架替你做了什么、没做什么

| 框架做了 | 仍归应用 |
| --- | --- |
| 按超步调度节点，按通道的归并规则应用更新。 | 为每个通道选对归并规则；需要时打开 `with_strict_channels()`。 |
| 建图时拒绝悬空边和缺少入口。 | 保证业务路径正确、所有需要的分支可达。 |
| 运行时拒绝不存在的路由目标。 | 路由函数只读状态、结果互斥。 |
| 超步上限兜底，防止无限循环。 | 设定业务额度，并让循环真正计数。 |
| 把状态按值交给节点，只接受 `NodeOutput` 里的更新。 | 校验输入契约，拒绝不合格的状态。 |
| — | 区分“图运行完成”和“业务成功”。 |

<!-- adk-refs:start -->

## 在 ADK-Rust 源码里

本章观察到的状态通道、路由和步数上限，在 adk-graph 里分布在这几处：

| 本章内容 | 源码位置 | 对照要点 |
| --- | --- | --- |
| 通道的三种归并规则 | [`adk-graph/src/state.rs` · `StateSchema::apply_update`](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-graph/src/state.rs#L144-L171) | 覆盖、追加、求和；求和按浮点数算，写 1 读回来是 `1.0`（`counter_channel n=2.0` 的来历） |
| 条件边 | [`adk-graph/src/graph.rs` · `StateGraph::add_conditional_edges`](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-graph/src/graph.rs#L129-L144) | 路由函数返回一个键，按映射表找到目标节点 |
| 建图检查 | [`adk-graph/src/graph.rs` · `StateGraph::compile`](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-graph/src/graph.rs#L169-L203) | 悬空的边、缺少起点在这里被拒绝；路由函数返回什么要到运行时才知道 |
| 运行时选出下一批节点 | [`adk-graph/src/graph.rs` · `CompiledGraph::get_next_nodes`](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-graph/src/graph.rs#L706-L714) | 映射表里没有的键报 `UnknownRouteTarget`；没有出边的节点只结束自己这一支 |
| 节点自己指定后继 | [`adk-graph/src/node.rs` · `NodeOutput::with_goto`](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-graph/src/node.rs#L537-L544) | 替换这个节点声明的边；目标不存在同样报 `UnknownRouteTarget` |
| 超步上限 | [`adk-graph/src/graph.rs` · `CompiledGraph::with_recursion_limit`](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-graph/src/graph.rs#L457-L460) | 默认 100；超出时报 `RecursionLimitExceeded`，检查点保留已经走到的状态 |
| 每个超步开始前检查上限 | [`adk-graph/src/executor.rs` 第 348 行](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-graph/src/executor.rs#L348) | 数的是这次运行从头开始的步数：暂停或失败后恢复，之前走过的步也算在内 |
| 只允许写声明过的通道 | [`adk-graph/src/graph.rs` · `CompiledGraph::with_strict_channels`](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-graph/src/graph.rs#L508-L511) | 不打开时，拼错名字的通道会被当成新通道直接覆盖写入 |

源码固定在 ADK-Rust `98515241133d`（3.0.0，2026-11-26，尚未发布到 crates.io）。本节由 `scripts/learn-agent-rust-adk-refs.py` 生成。

<!-- adk-refs:end -->

::: warning 常见误区
- 编译通过不等于业务路径正确、循环会终止或所有分支可达。
- 两条普通出边不是 if/else，两个后继都会运行；二选一要用条件边。
- 写错通道名默认不报错，会悄悄变成一个覆盖通道。
- 本例的等级规则是固定夹具，只验证编排；没有验证模型审查质量。
:::

## 本章结论

先定义状态和每个通道的归并规则，再安排节点、条件边与回路。每次运行同时观察业务结果、实际轨迹和每个超步跑了什么；用业务额度表达“最多做几次”，用超步上限兜住代码错误。

## 迁移思考：路由正确与业务完成分别检查

图顺利走到 accept，就能证明升级报告合格吗？

<details><summary>参考推演</summary>

先核对条件读取的是当前且有效的审查结果，再检查报告本身满足独立要求；路由只能证明按给定状态选择了路径。

迁移到退款审批时，同样需要独立核对订单事实和额度，不能把进入批准节点当作业务正确的证据。

</details>

## 检查理解

1. 为什么要分开 `outcome` 和图运行完成？

   <details><summary>参考答案</summary>

   图运行完成只表示没有更多节点要跑。接受、转人工都可以这样结束，业务结果需要状态里的 `outcome` 表达。

   </details>

2. 两个普通出边会并行吗？

   <details><summary>参考答案</summary>

   会。adk-graph 在下一个超步运行两个后继（`two_edges` 探针）。要二选一，用条件边或 `with_goto`。

   </details>

3. 已经有了 `MAX_REPAIRS`，为什么还要超步上限？

   <details><summary>参考答案</summary>

   业务额度依赖代码正确计数。`runaway` 场景里修复节点忘了写 `repairs`，业务额度永远到不了，只有超步上限能停下运行。两者保护的是不同的错误。

   </details>

4. 节点里改了 `ctx.state`，为什么图状态没变？

   <details><summary>参考答案</summary>

   节点拿到的是状态的副本。框架只在一步结束时应用 `NodeOutput` 里列出的更新，所以改本地副本不影响图（`local_mutation` 探针）。

   </details>

5. 写了一个没声明的通道名，为什么没有报错？

   <details><summary>参考答案</summary>

   没声明的通道按默认的覆盖规则收下。本该追加到列表通道的内容写进了另一个名字，只有打开 `with_strict_channels()` 才会被拒绝（`typo_channel` 与 `strict_channels` 探针）。

   </details>

## 参考资料

- ADK-Rust（固定提交）：[Graph Agents 文档](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/docs/official_docs/agents/graph-agents.md)（超步、条件边、goto、归并规则、超步上限）、[adk-graph README](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-graph/README.md)。
- LangGraph [Graph API](https://docs.langchain.com/oss/python/langgraph/graph-api)：状态、reducer 与条件边的概念对照。

下一章进入[图暂停、检查点与恢复](./graph-pause-resume.md)，让另一个进程接着等待中的审批继续运行。
