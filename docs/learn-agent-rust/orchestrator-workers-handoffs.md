---
title: "第 19 章：协调者、工作者与任务交接"
description: "何时由中心分派子任务，何时将下一轮控制权交给专门角色？"
pageClass: learn-agent-rust-course
prev:
  text: 第 18 章 · 规划、执行与动态重规划
  link: /learn-agent-rust/plan-execute-replan
next:
  text: 第 20 章 · 评估、反思与有界修复
  link: /learn-agent-rust/evaluator-reflection
---

# 第 19 章：协调者、工作者与任务交接

[课程总览](./index.md) · [上一章](./plan-execute-replan.md) · [本部分导读](./agent-design-patterns.md) · [下一章](./evaluator-reflection.md)

::: tip 本章学习目标
- 区分固定并行、协调者动态分解、子 Agent 调用与角色交接。
- 明确定义每次交接后的控制者、上下文载荷和可用权限。

**前置与基础：** [D03 · 并行分解与结果归并](./parallel-decomposition.md)、[D04 · 规划、执行与动态重规划](./plan-execute-replan.md)、[R06 · 子 Agent 与上下文隔离](./subagents.md)。
:::

<LearnAgentRustMap active="orchestrator-workers-handoffs" />

::: info 完整代码与运行方式
本章使用 Rust 1.99.1 与固定提交的 graph-flow 0.8.1。下载<a href="/learn-agent-rust/orchestrator-workers-handoffs.zip" download>独立 Rust 工程</a>，解压后运行 `cargo run --locked -- suite`；`cargo test --locked` 运行回归测试，`cargo clippy --locked --all-targets -- -D warnings` 检查代码。

源码唯一位置为 `docs/public/learn-agent-rust/code/orchestrator-workers-handoffs/`，下文代码直接引用该工程。验证命令：`python3 scripts/verify-agent-patterns.py --lesson D05 --check`。默认没有真实模型调用。
:::

## 1. 从任务问题开始

何时由中心分派子任务，何时将下一轮控制权交给专门角色？

动态分解、独立工作者上下文、汇总契约与显式控制权交接。

## 2. 适用与不适用

子任务数量或内容由输入决定时，协调者可以动态分派；对话需要由另一个专业角色继续主导时，可以考虑显式交接。

固定几个独立检查用 D03 即可；没有上下文、专业工具或控制需求差异时，不必增加角色。不可将交接等同于自动放宽权限。

## 3. 场景与流程

协调者读取 workspace 清单后按实际成员生成检查任务，汇总结果；发现许可证问题时，暂停技术审查，将后续对话交给合规角色，由其处理后明确归还控制。

![图展示本章实际图节点的推进关系，失败在对应合同处停止。](/learn-agent-rust/figures/d05-pattern-flow.svg)

沿上方节点读取主流程，重点看下方的return · 明确归还控制。配图只表达拓扑；真实节点次序见下方输出中的 trace，不把示意布局当作性能测量。

## 状态与控制契约

| 边界 | 实验约束 |
| --- | --- |
| 子调用 | 父节点等待子结果后继续；子任务输入、输出和额度由父级限定。 |
| 协调分派 | task_spec 包含目标、输入修订、允许工具和输出 schema；限制总工作者数、委派深度与累计预算。 |
| 交接 | handoff_id、from_role、to_role、reason、payload_revision 和 allowed_actions；会话同一时刻只有一个有效控制者。 |
| 汇总与返回 | 结果关联任务身份；拒绝重复、过期和无法解析的返回。交接失败或目标角色不可用时保留原控制权。 |

## 4. 从合同到 Rust 实现

### 动态工作者和固定并行差在哪里

decompose 根据输入夹具产生两个或三个成员。workers 为每个成员建立独立的局部消息数组，通过 JoinSet 收集结果，排序后交给父级。历史是固定脚本消息，没有接入语言模型会话；这里真实验证的是任务数量随输入变化、结果回收与父级控制继续。

### 子调用结束后，谁继续说话

普通 worker 返回时，controller 仍是 technical。handoff 则构造带身份、修订、来源角色、目标角色与 allowed 的对象，transfer 检查通过后将 controller 改为 license。return 节点记录 returned_from，再显式归还 technical。读者应在轨迹中区分“返回结果”和“改变后续主导者”。

### 权限和上下文不能跟着角色名称膨胀

白名单只允许 license 与 read；invalid_role 请求 admin 被拒绝，原 controller 保留。stale 拒绝旧修订，depth 在派发前停止。这里固定最大三个工作者，并在启动前扣共享额度；它不是可无限递归的团队平台，也没有独立进程沙箱。

先看统一运行账本。State 的 `used` 在执行前扣除，stop 记录业务终态，trace 记录真实经过的图节点。graph-flow 的 Completed 只表示图执行结束，成功与否由 stop 判断。

<<< @/public/learn-agent-rust/code/orchestrator-workers-handoffs/src/main.rs#state

本章的关键领域代码如下。先沿 match 找正常分支，再找过期、缺失或失败分支，观察它们是否在产生后续效果之前停止。

<<< @/public/learn-agent-rust/code/orchestrator-workers-handoffs/src/main.rs#handoff

节点适配器把状态读出、扣费、调用领域逻辑，再保存回 Context。`GoTo` 表示受应用控制的跳转；宿主还有限制 64 次推进的兜底。每个场景从全新 Session 开始。

<<< @/public/learn-agent-rust/code/orchestrator-workers-handoffs/src/main.rs#runner

## 动手实验与真实运行

先预测正常场景中的 trace，再预测 budget 场景能执行几个节点。运行独立工程后对照下面保存的真实输出。suite 每行是一个场景的状态，字段包括 scenario、used、limit、trace、stop 和 data；JSON 展开仅改变显示格式。

<<< @/public/learn-agent-rust/outputs/d05-suite.json

验证器在独立临时目录运行 4 项 Rust 回归测试、全部正常与故障场景和 Clippy，再解压最终下载包离线重新编译、复验输出。<a href="/learn-agent-rust/orchestrator-workers-handoffs.zip" download>下载包</a>内的 evidence.json 记录源码摘要、场景与额外检查。运行平台为本次 macOS aarch64，Rust 1.99.1；默认固定决策，不需要密钥。

## 已验证范围与真实模型边界

真实 Tokio 动态派发与角色状态；消息为脚本，非真实多模型协作。 规则、角色和输入由代码预先给定，因此输出能够复核控制合同，但不能据此推导真实模型成功率或质量收益。第 22 章提供[统一模型对照入口](./pattern-composition.md#model-comparison)，配置标准 OpenAI 兼容服务后再运行；当前未产生真实模型结果。

::: warning 常见误区
子图、线程、进程与 Agent 角色是不同概念；一个模式图中的多个框，不代表已经有多个隔离进程。
:::

## 本章结论

协调者决定子任务规格并汇总，交接改变下一轮控制者。为两者分别定义返回、身份、修订和权限，避免把一个角色名称当成授权。

## 迁移思考：返回结果与移交控制分开

子任务完成以后，为什么不自动把 controller 改成工作者？

父级需要继续汇总。只有明确的 handoff 合同才改变后续主导者，并校验接收权限。

技术客服转账单客服时，应明确移交，而后台检索完成通常只返回数据。

## 检查理解

1. 两个和三个工作者由什么决定？

   <details><summary>参考答案</summary>

   由 decompose 的输入成员清单决定，随后才创建任务。

   </details>

2. worker 返回会自动切换角色吗？

   <details><summary>参考答案</summary>

   不会。子调用返回后父级继续；切换由 handoff 节点显式执行。

   </details>

3. 交给 license 后能写文件吗？

   <details><summary>参考答案</summary>

   本实验只允许 read；角色名称不能绕过 allowed 校验。

   </details>

4. 接收角色非法时控制权归谁？

   <details><summary>参考答案</summary>

   保留 technical，且不进入 return。

   </details>

5. 独立消息数组是否等于进程隔离？

   <details><summary>参考答案</summary>

   不是。它们仍共享同一个 Tokio 运行时和宿主资源，进程与工作区隔离另验。

   </details>

## 参考资料

- [Building effective agents](https://www.anthropic.com/research/building-effective-agents)：工作流、Agent 与可组合模式的工程导读；本文取其结构分类，不沿用过时 API。
- [LangGraph：Workflows and agents](https://docs.langchain.com/oss/python/langgraph/workflows-agents)：对照模式拓扑；Python API 不视为 graph-flow 等价接口。

下一章：[第 20 章 · 评估、反思与有界修复](./evaluator-reflection.md)。回到[本部分导读](./agent-design-patterns.md)比较模式。
