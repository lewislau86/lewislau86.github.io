---
title: "第 18 章：规划、执行与动态重规划"
description: "未知步骤怎样先规划，并根据执行证据调整剩余工作？"
pageClass: learn-agent-rust-course
prev:
  text: 第 17 章 · 并行分解与结果归并
  link: /learn-agent-rust/parallel-decomposition
next:
  text: 第 19 章 · 协调者、工作者与任务交接
  link: /learn-agent-rust/orchestrator-workers-handoffs
---

# 第 18 章：规划、执行与动态重规划

[课程总览](./index.md) · [上一章](./parallel-decomposition.md) · [本部分导读](./agent-design-patterns.md) · [下一章](./orchestrator-workers-handoffs.md)

::: tip 本章学习目标
- 区分会话内待办清单与能随观察修订的执行计划。
- 让计划修订保留已确认效果，并为重规划设置触发条件与上限。

**前置与基础：** [D02 · 提示链与条件路由](./prompt-chaining-routing.md)、[R05 · 可见的任务清单](./todo-planning.md)、[R06 · 子 Agent 与上下文隔离](./subagents.md)。
:::

<LearnAgentRustMap active="plan-execute-replan" />

::: info 完整代码与运行方式
本章使用 Rust 1.99.1 与固定提交的 graph-flow 0.8.1。下载<a href="/learn-agent-rust/plan-execute-replan.zip" download>独立 Rust 工程</a>，解压后运行 `cargo run --locked -- suite`；`cargo test --locked` 运行回归测试，`cargo clippy --locked --all-targets -- -D warnings` 检查代码。

源码唯一位置为 `docs/public/learn-agent-rust/code/plan-execute-replan/`，下文代码直接引用该工程。验证命令：`python3 scripts/verify-agent-patterns.py --lesson D04 --check`。默认没有真实模型调用。
:::

## 1. 从任务问题开始

未知步骤怎样先规划，并根据执行证据调整剩余工作？

计划版本、步骤依赖、结果账本与有界重规划。

## 2. 适用与不适用

任务大致目标已知，但实际步骤会因读取到的依赖、故障或新约束而改变时，适合先计划再按证据修订。

少量固定步骤无需引入规划器；不可逆动作没有明确授权与效果记录时，不应靠重新生成计划来恢复。

## 3. 场景与流程

原计划只检查顶层 Cargo.toml，执行中发现多个 workspace 成员。规划器增加各成员检查，废弃“顶层检查即足够”的假设，再更新汇总依赖。

![图展示本章实际图节点的推进关系，失败在对应合同处停止。](/learn-agent-rust/figures/d04-pattern-flow.svg)

沿上方节点读取主流程，重点看下方的发现成员 → 新版剩余计划。配图只表达拓扑；真实节点次序见下方输出中的 trace，不把示意布局当作性能测量。

## 状态与控制契约

| 边界 | 实验约束 |
| --- | --- |
| 计划 | plan_revision、step_id、dependencies、expected_artifact 与验收条件；拒绝环、未知依赖和无限展开。 |
| 结果账本 | 完成步骤关联实际产物、来源修订和已发生的效果，计划更新不能删除这些记录。 |
| 重规划 | 由新事实、失败分类或验收缺项触发；保存 old_revision、new_revision 与可公开的变更摘要。 |
| 额度与终态 | 累计所有模型、工具和重规划消耗；无法推进、重复计划或额度耗尽时转为未完成。 |

## 4. 从合同到 Rust 实现

### 计划和结果为什么分成两份

Plan 保存 revision 与步骤依赖，done 保存已执行身份。discover 最初只包含 root，execute 完成后 observe 发现 member，将计划改为修订 2，并给 member 添加 root 依赖。done 没有被覆盖，所以 root 不会重做。计划描述未来工作，结果账本记录已经发生的事情。

### 先证明计划能推进

validate_plan 用深度优先访问检查未知依赖与环，再允许执行一个就绪步骤。cycle 的 root 依赖自己；unknown 指向 ghost。两者都在执行前停止，done 为空。示例最多四步，用于把有限状态问题讲清楚；大量步骤应另行考虑拓扑排序与索引。

### 什么才算一次有意义的重规划

repeat 模拟新计划没有增加信息，observe 直接结束为 repeated_plan。正常新增成员时返回 validate，而非重建 State；used 因此不会清零。当前任务只执行内存中的检查标识，没有外部写操作；跨进程恢复和业务效果去重继续使用可靠性专题的合同。

先看统一运行账本。State 的 `used` 在执行前扣除，stop 记录业务终态，trace 记录真实经过的图节点。graph-flow 的 Completed 只表示图执行结束，成功与否由 stop 判断。

<<< @/public/learn-agent-rust/code/plan-execute-replan/src/main.rs#state

本章的关键领域代码如下。先沿 match 找正常分支，再找过期、缺失或失败分支，观察它们是否在产生后续效果之前停止。

<<< @/public/learn-agent-rust/code/plan-execute-replan/src/main.rs#replan

节点适配器把状态读出、扣费、调用领域逻辑，再保存回 Context。`GoTo` 表示受应用控制的跳转；宿主还有限制 64 次推进的兜底。每个场景从全新 Session 开始。

<<< @/public/learn-agent-rust/code/plan-execute-replan/src/main.rs#runner

## 动手实验与真实运行

先预测正常场景中的 trace，再预测 budget 场景能执行几个节点。运行独立工程后对照下面保存的真实输出。suite 每行是一个场景的状态，字段包括 scenario、used、limit、trace、stop 和 data；JSON 展开仅改变显示格式。

<<< @/public/learn-agent-rust/outputs/d04-suite.json

验证器在独立临时目录运行 4 项 Rust 回归测试、全部正常与故障场景和 Clippy，再解压最终下载包离线重新编译、复验输出。<a href="/learn-agent-rust/plan-execute-replan.zip" download>下载包</a>内的 evidence.json 记录源码摘要、场景与额外检查。运行平台为本次 macOS aarch64，Rust 1.99.1；默认固定决策，不需要密钥。

## 已验证范围与真实模型边界

真实图推进与依赖验证；检查动作为内存夹具，无跨进程恢复。 规则、角色和输入由代码预先给定，因此输出能够复核控制合同，但不能据此推导真实模型成功率或质量收益。第 22 章提供[统一模型对照入口](./pattern-composition.md#model-comparison)，配置标准 OpenAI 兼容服务后再运行；当前未产生真实模型结果。

::: warning 常见误区
把每次失败都交回规划器可能掩盖永久错误。重试、重规划与请求人工帮助必须有不同的触发条件。
:::

## 本章结论

重规划修改尚需做的工作，已经确认的结果继续保留。先验证依赖，再执行就绪步骤；没有新信息或额度耗尽时停止，而不是反复生成同一份计划。

## 迁移思考：重规划保留结果账本

新发现一个 workspace 成员后，为什么不重跑整个计划？

已确认的 root 结果仍有效。修订剩余步骤并保留 done，可以避免重复效果，同时保持累计预算。

数据管道新增分区时，也应区分已确认产物和待处理分区。

## 检查理解

1. 为什么不能直接清空 done？

   <details><summary>参考答案</summary>

   会丢失完成证据，导致旧步骤或外部效果重复执行。

   </details>

2. 环在什么时候被发现？

   <details><summary>参考答案</summary>

   validate 阶段，任何 execute 之前。

   </details>

3. member 为什么依赖 root？

   <details><summary>参考答案</summary>

   成员身份来自 root 的观察，依赖使其只在发现完成后进入执行。

   </details>

4. 新计划用了新 revision 就一定有进展吗？

   <details><summary>参考答案</summary>

   不一定。还需检查计划内容或新证据；repeat 示范无实质变化时停止。

   </details>

5. 这里的重规划包含进程恢复吗？

   <details><summary>参考答案</summary>

   没有。它是同一运行中的状态更新，跨进程恢复与效果重放需另外验证。

   </details>

## 参考资料

- [LangGraph：Workflows and agents](https://docs.langchain.com/oss/python/langgraph/workflows-agents)：对照模式拓扑；Python API 不视为 graph-flow 等价接口。
- [ReAct](https://arxiv.org/abs/2210.03629)：观察、行动与任务推理交替的研究入口；本课程记录动作、结果与公开决策摘要。

下一章：[第 19 章 · 协调者、工作者与任务交接](./orchestrator-workers-handoffs.md)。回到[本部分导读](./agent-design-patterns.md)比较模式。
