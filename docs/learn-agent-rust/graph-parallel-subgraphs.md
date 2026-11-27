---
title: "第 7 章：图并行、归并与子图"
description: "用 adk-graph 让两项发布检查并行运行、按业务规则归并，验证局部失败后的恢复、并行写入的丢失更新、隔离子图与节点超时。"
pageClass: learn-agent-rust-course
prev:
  text: 第 6 章 · 图暂停、检查点与恢复
  link: /learn-agent-rust/graph-pause-resume
next:
  text: 第 8 章 · 可见的任务清单
  link: /learn-agent-rust/todo-planning
---

# 第 7 章：图并行、归并与子图

[课程总览](./index.md) · [上一章](./graph-pause-resume.md) · [图编排导读](./graph-orchestration.md) · [下一章](./todo-planning.md)

::: tip 本章学习目标
- 让两项检查在同一个超步里并行运行，等两项都到齐后归并一次。
- 把“归并”写成业务规则：通过、不通过、缺失三种情况分别处理。
- 验证局部失败后的恢复、并行写同一通道时的丢失更新、隔离子图的通道契约与节点超时。

**前置：** [图状态与路由](./graph-state-routing.md)、[图暂停与恢复](./graph-pause-resume.md)。

**实践方式：** <a href="/learn-agent-rust/graph-parallel-subgraphs.zip" download>下载独立工程</a>，按[第 8 节](#hands-on)取一次 ADK-Rust 源码后运行；无需模型或数据库。
:::

::: info 本章已迁移到 ADK-Rust 3.0
本章实验基于 ADK-Rust 3.0 发布候选版的 adk-graph（固定提交，尚未发布到 crates.io）。旧版本章用 graph-flow 的 `FanOutTask` 在一个节点内部并发，归并、子图和超时都由应用包装，可从 git 标签 `learn-agent-rust-v1` 取得。adk-graph 直接提供并行调度、自动汇合、归并规则、子图和节点超时，第 8 节的对应表列出了变化。
:::

发布 3.0 之前要做两项检查：安全公告和许可证。两项互不依赖，可以同时做；但结论必须等两项都有结果才能给出，任何一项缺失都不能当成“通过”。

<LearnAgentRustMap active="graph-parallel-subgraphs" />

<!-- experiment-library:start -->

全书实验可从[统一代码库](./experiments.md#graph-parallel-subgraphs)下载；解压后进入 `chapters/graph-parallel-subgraphs/`，或运行 `python3 run.py run G03`。

<!-- experiment-library:end -->

## 1. 先画出执行和汇总的边界

![plan 之后安全与许可证检查在同一个超步里并行运行，merge 等两项都到齐后运行一次，按业务规则给出 ready、blocked 或 incomplete。](/learn-agent-rust/figures/g03-parallel-join.svg)

图里有三类边界：并行从哪里开始（`plan` 的两条出边），在哪里汇合（`merge` 的两条入边），汇合时按什么规则给结论（`merge` 节点的业务逻辑）。前两类由框架负责，第三类是应用的。

## 2. 两条出边就是并行

<<< @/public/learn-agent-rust/code/graph-parallel-subgraphs/src/main.rs#graph

`plan` 有两条出边，`security` 和 `license` 在下一个超步里一起运行。`merge` 有两条普通（无条件）入边，框架在建图时自动把它标成“等待节点”：它等所有还能到达的前驱都到齐，然后只运行一次。不需要额外配置。条件边的目标不算：条件边运行时只选一个去处，不保证一定到达。

<<< @/public/learn-agent-rust/code/graph-parallel-subgraphs/src/main.rs#checks

每项检查只写自己的通道（`security`、`license`），互不覆盖。同一个超步里多个节点的更新，框架按节点名的顺序应用，而不是按完成的先后，所以同样的输入总是得到同样的状态。

## 3. 归并是一项业务规则

<<< @/public/learn-agent-rust/code/graph-parallel-subgraphs/src/main.rs#merge

| 安全 | 许可证 | 结论 |
| --- | --- | --- |
| 通过 | 通过 | `ready` |
| 任一不通过 | — | `blocked` |
| 任一缺失 | — | `incomplete` |

“缺失”单独一类：框架能保证 `merge` 只运行一次、在前驱到齐后运行，但不知道“没有结果”在业务上意味着什么。第 7 节的超时场景就会出现缺失。

正常运行：

<<< @/public/learn-agent-rust/outputs/g03-normal.txt

第 1 步里两项检查一起运行，第 2 步 `merge` 只运行一次。

## 4. 一项检查失败，完成的结果仍然保留

<<< @/public/learn-agent-rust/code/graph-parallel-subgraphs/src/main.rs#failure

<<< @/public/learn-agent-rust/outputs/g03-failure.txt

安全检查第一次执行失败，这一步以错误结束，`merge` 没有运行。同一步里已经完成的许可证检查，框架把它的输出作为“待写入”记进检查点。在同一个线程上再运行一次，框架只重跑没有完成的 `security`（第二次成功），`license` 不再运行（`license_runs=1`），然后 `merge` 给出结论。

这是检查点带来的能力：没有检查点时，失败就是整次运行失败，重跑要从头开始。

## 5. 线程安全为什么仍会丢更新

<<< @/public/learn-agent-rust/code/graph-parallel-subgraphs/src/main.rs#collision

<<< @/public/learn-agent-rust/outputs/g03-collision.txt

两个并行节点都从同一个状态读到 `count=0`，各自写 `old + 1`。通道是覆盖规则，两次写入都是 `1`，后应用的覆盖先应用的，结果是 1，丢了一次更新。框架没有出错，状态也没有损坏：每次写入都被正确应用了，只是“读出来再写回去”这个组合不是原子的。

把通道换成计数规则，两个节点各写“加 1”，框架把两个增量都加上，结果是 2。并行写同一个通道时，要么各写各的通道再由归并节点汇总，要么选一个能正确合并并发写入的归并规则。

## 6. 把子图包装成一个父节点

<<< @/public/learn-agent-rust/code/graph-parallel-subgraphs/src/main.rs#subgraph

<<< @/public/learn-agent-rust/outputs/g03-subgraph.txt

子图是一张独立编译的图，有自己的通道。`SubgraphNode` 把它当作父图的一个节点运行：

- `isolated()` 以后，父子之间只交换显式写出的通道：父图的 `notes` 进入子图的 `text`，子图的 `score` 写回父图的 `risk`。子图内部的 `scratch` 不会泄漏到父图，即使父图恰好也有一个同名通道。
- 映射写错了子图的通道名（`scor`），**父图编译时**就被拒绝（`SubgraphChannelMismatch`），不会等到运行时才发现值是空的。

子图的每次运行使用自己的线程（父线程加节点名和步号）。子图里也可以暂停，恢复父图时会重新进入子图，从子图自己的检查点继续，所以子图要能暂停恢复，自己就得配检查点（声明了暂停关口却没有检查点的子图，父图编译时就会被拒绝）。本章没有演示这一点。

## 7. 超时怎样返回

<<< @/public/learn-agent-rust/code/graph-parallel-subgraphs/src/main.rs#timeout

<<< @/public/learn-agent-rust/outputs/g03-timeout.txt

许可证检查要 300 毫秒，超时上限 50 毫秒：

- `OnTimeout::Fail`：运行以 `NodeTimedOut` 结束。
- `OnTimeout::Skip`：跳过这个节点，当作它输出为空，运行继续。`merge` 拿不到许可证结果，按业务规则判为 `incomplete`，而不是 `ready`。

“跳过”让运行能继续，也让“没有结果”流进了下游。归并规则必须能识别缺失，否则一次超时就会变成一次“通过”。

## 8. 动手实验 {#hands-on}

下载并解压<a href="/learn-agent-rust/graph-parallel-subgraphs.zip" download>本章工程</a>，先取一次 ADK-Rust 源码，再运行：

```sh
cd graph-parallel-subgraphs
python3 fetch-adk-rust.py ../adk-rust    # 需要 git 与 GitHub 访问；不行时加 --method cdn
cargo run --locked -- normal
cargo run --locked -- failure
cargo run --locked -- collision
cargo run --locked -- subgraph
cargo run --locked -- timeout
```

命令要在 `graph-parallel-subgraphs` 目录里运行。编译时会看到 adk-core 的 3 条弃用警告（上游固定 Rust 1.95.0），不影响运行和检查。

网站维护者运行 `python3 scripts/verify-agent-orchestration.py`：它对 G01–G03 三个工程分别打包、在临时目录解压并在旁边放好 `adk-rust/`，执行格式检查、Clippy 和 Rust 测试；每个场景连跑两次必须逐字节相同，并逐项核对契约。加 `--check` 检查产物是否过期。

### 与旧版场景的对应

| 旧版（graph-flow） | 新版（adk-graph） | 说明 |
| --- | --- | --- |
| `normal`：`FanOutTask` 在一个节点内部并发两个子任务 | `normal`：两条出边，同一个超步并行 | 并行由框架调度，汇合自动完成。 |
| `failure`：一个子任务失败，另一个结果保留，归并不运行 | `failure`：同上，并且恢复时只重跑失败的节点 | 新增“恢复”这一半，由检查点的待写入提供。 |
| `collision`：共享计数器丢失更新 | `collision`：覆盖通道丢失更新，计数通道不丢 | 丢失更新的原因相同；新版多了正确的做法。 |
| `subgraph`：应用 `Task` 包装子图，新建 Session | `subgraph`：`SubgraphNode` 加隔离的通道映射 | 通道名错误改为父图编译时发现。 |
| `timeout`：图任务超时返回宿主 | `timeout`：节点超时，失败或跳过 | 新增“跳过”，以及归并对缺失的处理。 |

## 框架替你做了什么、没做什么

| 框架做了 | 仍归应用 |
| --- | --- |
| 同一个超步里的节点一起运行；有多条无条件入边的节点自动等前驱到齐，只运行一次。 | 决定哪些检查可以并行（彼此不依赖）。 |
| 按节点名的顺序应用同一步的更新，结果可复现。 | 选归并规则；并行写同一个通道时别用“读出来再写回去”。 |
| 一步里有节点失败时，保存已完成节点的输出；恢复只重跑失败的节点。 | 让检查节点可以安全地重跑。 |
| 子图的通道映射在父图编译时检查；隔离以后只交换声明的通道。 | 设计父子之间的数据契约。 |
| 节点超时：失败、重试或跳过。 | 跳过时，归并规则要能识别缺失，不能当成通过。 |

<!-- adk-refs:start -->

## 在 ADK-Rust 源码里

本章的并行、归并、失败恢复、超时与子图，在 adk-graph 里分布在这几处：

| 本章内容 | 源码位置 | 对照要点 |
| --- | --- | --- |
| 多条入边的节点自动等待 | [`adk-graph/src/graph.rs` · `StateGraph::defer_unconditional_fan_in`](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-graph/src/graph.rs#L220-L249) | 编译时把有多条无条件入边的节点标成汇合节点：上游都到齐才运行，而且只运行一次 |
| 同一步的更新按什么顺序应用 | [`adk-graph/src/executor.rs` 第 1789 行](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-graph/src/executor.rs#L1789) | 按节点名、通道名排序后逐个经过归并规则，与谁先完成无关 |
| 失败的一步里已完成的节点 | [`adk-graph/src/executor.rs` 第 1362 行](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-graph/src/executor.rs#L1362) | 重试这一步时直接应用保存下来的结果，只重跑失败的节点 |
| 超时策略 | [`adk-graph/src/timeout.rs` · `TimeoutPolicy`](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-graph/src/timeout.rs#L60-L67) | 运行时长与空闲时长两种上限，超时后按 `OnTimeout` 失败、重试或跳过 |
| 超时后的三种处理 | [`adk-graph/src/timeout.rs` · `OnTimeout`](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-graph/src/timeout.rs#L35-L43) | `Skip` 让节点以空输出继续，缺失要由下游归并规则识别 |
| 子图节点只交换声明的通道 | [`adk-graph/src/subgraph.rs` · `SubgraphNode::isolated`](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-graph/src/subgraph.rs#L127-L130) | 不加时，两边同名的通道自动互通；加上后只交换 `with_input` / `with_output` 声明的通道，子图的草稿通道不会带回父图 |
| 通道映射在父图编译时检查 | [`adk-graph/src/subgraph.rs` 第 220 行](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-graph/src/subgraph.rs#L220) | 映射到对方没有声明的通道时报 `SubgraphChannelMismatch`，不会等到运行 |

源码固定在 ADK-Rust `98515241133d`（3.0.0，2026-11-26，尚未发布到 crates.io）。本节由 `scripts/learn-agent-rust-adk-refs.py` 生成。

<!-- adk-refs:end -->

::: warning 常见误区
- 两项检查都没报错，不等于归并结果正确：还要核对每项贡献恰好纳入一次、成员是否齐全。
- 框架不报错、状态没损坏，也会丢更新：覆盖通道上的“读出来再写回去”不是原子的。
- 超时“跳过”让运行继续，也让缺失流进下游。
- 本章的“并行”指同一个超步里一起调度，没有测量耗时。
:::

## 本章结论

并行从多条出边开始，在多入边的节点汇合，汇合后的结论由业务规则给出。框架负责调度、汇合、按确定的顺序应用更新、局部失败后的恢复、子图契约检查和超时；应用负责决定什么能并行、怎样归并、缺失算什么。

## 迁移思考：并发安全与业务归并分别验证

两个检查都成功且没有数据竞争异常，汇总值就一定正确吗？

<details><summary>参考推演</summary>

核对每项贡献是否恰好纳入一次、成员是否齐全，以及读改写是否存在丢失更新；线程安全容器只能保护它承诺的单次操作。

迁移到并行订单统计时，让任务写独立结果，再按订单身份去重归并，并显式报告缺失成员。

</details>

## 检查理解

1. `merge` 有两条入边，为什么只运行一次？

   <details><summary>参考答案</summary>

   有多条无条件入边的节点在建图时被自动标成等待节点，等所有还能到达的前驱都到齐后才运行，只运行一次。

   </details>

2. 安全检查失败后再运行一次，为什么许可证检查没有重跑？

   <details><summary>参考答案</summary>

   失败的那一步里，已经完成的许可证检查的输出作为待写入记进了检查点。恢复时框架只重跑没有完成的节点。

   </details>

3. 覆盖通道为什么会丢更新，计数通道为什么不会？

   <details><summary>参考答案</summary>

   两个节点从同一个状态读到 0，各写 1，覆盖规则只留下后应用的那个。计数规则把两个写入当作增量相加，得到 2。

   </details>

4. 子图映射写错了通道名，什么时候发现？

   <details><summary>参考答案</summary>

   父图编译时。父子两边的通道都在编译前已知，映射的每一端都要在它所属的那一边声明过：`with_input(父, 子)` 的父通道要在父图里、子通道要在子图里，`with_output` 反过来；任何一端缺失都会被拒绝（`SubgraphChannelMismatch`），哪怕另一边恰好有同名通道。

   </details>

5. 超时用“跳过”以后，为什么结论是 `incomplete` 而不是 `ready`？

   <details><summary>参考答案</summary>

   被跳过的节点输出为空，许可证通道没有结果。`merge` 的业务规则把缺失单独判为 `incomplete`，不把“没有结果”当成“通过”。

   </details>

## 参考资料

- ADK-Rust（固定提交）：[Graph Agents 文档的并行、子图与可靠性部分](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/docs/official_docs/agents/graph-agents.md)。
- LangGraph [Graph API](https://docs.langchain.com/oss/python/langgraph/graph-api)：并行分支、reducer 与子图的概念对照。

下一章进入[可见的任务清单](./todo-planning.md)。
