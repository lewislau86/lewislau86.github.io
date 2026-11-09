---
title: "第 7 章：图并行、归并与子图"
description: "真实使用 graph-flow FanOutTask，观察共享 Context、局部失败、更新冲突与显式归并，再用独立 Session 封装子图。"
pageClass: learn-agent-rust-course
prev:
  text: 第 6 章 · 图暂停、会话存储与恢复
  link: /learn-agent-rust/graph-pause-resume
next:
  text: 第 8 章 · 可见的任务清单
  link: /learn-agent-rust/todo-planning
---

# 第 7 章：图并行、归并与子图

[课程总览](./index.md) · [上一章](./graph-pause-resume.md) · [下一章](./todo-planning.md)

::: tip 本章学习目标
- 用 FanOutTask 表达并行检查，区分普通出边、子任务返回与父图路由。
- 验证共享 Context 的局部成功和丢失更新，设计确定性的归并节点。
- 用 Task 包装子 Graph，以新 Session 明确传递输入输出。

**前置：** [图状态与路由](./graph-state-routing.md)、[图暂停与恢复](./graph-pause-resume.md)。

**实践方式：** <a href="/learn-agent-rust/graph-parallel-subgraphs.zip" download>下载独立工程</a>。固定 Rust 1.99.1、graph-flow 0.8.1 revision；首次获取依赖需要网络，运行无需模型或数据库。
:::

升级审查要分别检查兼容性和测试结果。这两个检查都只依赖当前输入，可以同时运行；报告汇总必须等两者都有结果。先预测：如果测试检查失败，兼容性检查已经写入的结果会消失吗？

本章运行真正的 FanOutTask，而两个检查采用固定通过或故障规则。我们观察任务的生命周期和状态归并，随后把一段子流程包成父图中的一个节点。实验标识 G03 用于命令定位。

<LearnAgentRustMap active="graph-parallel-subgraphs" />

<!-- experiment-library:start -->

全书实验可从[统一代码库](./experiments.md#graph-parallel-subgraphs)下载；解压后进入 `chapters/graph-parallel-subgraphs/`，或运行 `python3 run.py run G03`。

<!-- experiment-library:end -->

::: info 唯一源码与验证范围
片段来自<a href="/learn-agent-rust/code/graph-parallel-subgraphs/src/main.rs" download>完整 main.rs</a>。实验实际运行 Tokio 任务、Barrier、FanOutTask 与父子 Graph；检查和子图转换采用确定性规则。输出证明编排行为，性能、模型协作质量与跨进程子图恢复另验。
:::

## 1. 先画出执行和汇总的边界

![父图在 checks 节点内并发运行兼容性和测试检查，再由独立 merge 节点检查完整性并按固定顺序归并；子图通过明确字段与父图交换数据。](/learn-agent-rust/figures/g03-parallel-join.svg)

图的 checks → merge 只有一条普通边。真正的并发发生在 checks 节点内部；两个孩子都结束以后，FanOutTask 才返回父图，由父图更新游标到 merge。

这与“给一个普通节点加两条出边”有明显区别。固定 graph-flow 在普通路由中只选一个后继；并行要由专门节点或应用显式创建。

## 2. FanOutTask 怎样运行子任务

<<< @/public/learn-agent-rust/code/graph-parallel-subgraphs/src/main.rs#worker

两个 Check 共享 Barrier。任一个先抵达都要等另一个抵达才能继续，因此实验能检查两项任务确实都已启动。Barrier 是同步证据，没有测量并发带来的提速。

固定版本通过 JoinSet 运行所有子任务，给每个任务传入 Context 的 clone。clone 共享底层状态，因此 children 的任意 set 都能影响父 Context。`with_prefix("checks")` 只控制框架保存 response、status 与 next_action 的键名，不会为孩子的所有读写自动创建隔离空间。

两个孩子都返回 End，但父图仍会继续 merge。FanOutTask 将子任务的控制动作存作诊断数据，并不拿它决定父图下一步；它自身成功时返回 Continue。

## 3. 归并是一项业务规则

<<< @/public/learn-agent-rust/code/graph-parallel-subgraphs/src/main.rs#merge

本例固定成员为 compatibility、tests。Merge 核对两个 response 都存在，再按固定身份顺序生成报告，完成次序不会改变输出。缺少任何一项都返回错误，而不是默默生成半份报告。

这里显式编写 reducer 的职责：哪些结果属于当前批次、成员是否齐全、重复身份怎样处理、冲突是否允许、最后的展示顺序是什么。本例每次新建 Session，成员固定且唯一；如果复用旧会话或支持动态成员，还应增加批次身份和重复校验。

运行正常场景：

```sh
cargo run --locked -- normal
```

<<< @/public/learn-agent-rust/outputs/g03-normal.txt

结果中的 `child_end_ignored=true` 证明子任务的 End 没有终止父图，`both_started=true` 对应 Barrier 同步，报告顺序来自 Merge 的固定成员表。

## 4. 子任务失败，成功结果仍然保留

```sh
cargo run --locked -- failure
```

<<< @/public/learn-agent-rust/outputs/g03-failure.txt

测试孩子注入错误，兼容性孩子成功。固定 FanOutTask 仍等待孩子们结束，保存成功响应，然后向父图返回错误。父游标停在 checks，merge 没有执行，但 Context 中兼容性响应仍在。

以后重跑 checks 时，必须决定复用还是重算这些局部结果。若孩子有外部动作，还要处理重复效果。本例使用新会话验证局部失败，没有实现自动重试或部分结果恢复。多个孩子都失败时，先观察到哪个错误也不应成为稳定的业务优先级。

## 5. 线程安全为什么仍会丢更新

```sh
cargo run --locked -- collision
```

<<< @/public/learn-agent-rust/outputs/g03-collision.txt

两个孩子先各自读取 `shared_counter=0`，在 Barrier 会合，再各自写入 1。单次 get/set 都安全，完整的读 → 加一 → 写并不是事务；最后的值确定为 1，而业务上期待两项贡献相加为 2。

修复时可以让各孩子写自己的结果键，再由单一 Merge 累加；需要共享计数时也可以引入适当的原子操作或锁。本课程优先用独立结果与显式归并，使每个贡献都可核对。

## 6. 把子图包装成一个父节点

我们把输入转成大写当作最小子流程：子图读 input，写 output 和私有 scratch；父图只接收最终 output。转换很简单，重点是父子的状态边界。

<<< @/public/learn-agent-rust/code/graph-parallel-subgraphs/src/main.rs#subgraph

ChildGraph 是应用实现的 Task，内部持有子 Graph。每次调用新建 Session，再从 parent.request 复制到 child.input；完成后把 child.output 导出为 parent.subgraph_result。父私有字段没有传入，子私有字段也没有整体复制回来。

```sh
cargo run --locked -- subgraph
```

<<< @/public/learn-agent-rust/outputs/g03-subgraph.txt

本例不是框架自带的子图 API。包装器设定累计推进额度，并在子图 WaitForInput 时返回错误，要求维护者先定义父子恢复契约。要支持持久恢复，还需要保存父子身份、子游标与关联版本，并规定父取消如何传播给孩子。

## 7. 超时怎样返回到宿主

```sh
cargo run --locked -- timeout
```

<<< @/public/learn-agent-rust/outputs/g03-timeout.txt

超时场景创建一个永不返回的异步节点，Graph 的任务超时设置为 10ms，真实定时器最终返回超时错误。它验证等待 future 的取消边界；如果节点自行启动线程、子进程或远程作业，相关资源的关闭与效果查询需要单独协议。

工程包含 6 项 Rust 测试，覆盖正常并行、局部失败、丢失更新、子图隔离、真实超时和归并缺项。维护验证器会对源码与最终 zip 独立执行 5 个 CLI 场景并比较输出。

::: warning 常见误区
- 普通多出边不会自动并行；本例用 FanOutTask 在一个父节点内创建并发。
- prefix 只给框架结果键加前缀，Context 仍共享；孩子任意写同一键仍可能相互覆盖。
- 孩子 End 不控制父图路由，局部失败也不会自动回滚已成功的孩子。
- 本例的子图是应用包装器；父子跨进程恢复、取消传播和动态分发需要进一步实现。
:::

## 本章结论

并行先明确输入与写入归属，再定义结果身份、完整性、顺序与冲突规则。子图则在此基础上进一步明确状态传递和生命周期。图的形状容易画出来，可预测的失败和恢复行为需要靠这些契约与实验建立。

## 迁移思考：并发安全与业务归并分别验证

两个检查都成功且没有数据竞争异常，汇总值就一定正确吗？

<details><summary>参考推演</summary>

核对每项贡献是否恰好纳入一次、成员是否齐全，以及读改写是否存在丢失更新；线程安全容器只能保护它承诺的单次操作。

迁移到并行订单统计时，让任务写独立结果，再按订单身份去重归并，并显式报告缺失成员。

</details>

## 检查理解

1. Barrier 证明了什么？

   <details><summary>参考答案</summary>

   两个孩子都抵达同步点，证明它们已经启动并参与本次并发；它没有提供吞吐或提速结论。

   </details>

2. 为什么孩子返回 End，父图还会进入 merge？

   <details><summary>参考答案</summary>

   固定 FanOutTask 不用孩子的 next_action 路由；它成功后返回自己的 Continue，父图再沿边推进。

   </details>

3. 孩子失败后可以把 Context 当成入口快照吗？

   <details><summary>参考答案</summary>

   不可以。成功响应和任意子写入可能已经保留，重试必须定义局部结果和外部效果的处理方式。

   </details>

4. 子图为什么新建 Session？

   <details><summary>参考答案</summary>

   它创建独立 Context 和游标，只传入需要的字段。直接 clone 父 Context 会共享所有状态。

   </details>

5. 怎样让合并输出不受完成顺序影响？

   <details><summary>参考答案</summary>

   用稳定成员身份收集结果，检查缺项和重复，再按业务规定的顺序或可交换规则归并。

   </details>

## 参考资料

- 固定版本 [fanout.rs](https://github.com/a-agmon/rs-graph-llm/blob/9bbca193f20a8c4ba23289621549ecb3d35fee64/graph-flow/src/fanout.rs)、[context.rs](https://github.com/a-agmon/rs-graph-llm/blob/9bbca193f20a8c4ba23289621549ecb3d35fee64/graph-flow/src/context.rs)、[graph.rs](https://github.com/a-agmon/rs-graph-llm/blob/9bbca193f20a8c4ba23289621549ecb3d35fee64/graph-flow/src/graph.rs)。
- [Tokio Barrier](https://docs.rs/tokio/latest/tokio/sync/struct.Barrier.html)与 [JoinSet](https://docs.rs/tokio/latest/tokio/task/struct.JoinSet.html)。
- [LangGraph Graph API](https://docs.langchain.com/oss/python/langgraph/graph-api)：状态 reducer 与并行概念，查阅：2026-11-08。

下一章回到长任务本身，从[可见的任务清单](./todo-planning.md)记录计划；需要回顾两条主线时，打开[图编排导读](./graph-orchestration.md)。
