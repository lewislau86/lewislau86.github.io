---
title: "第 17 章：并行分解与结果归并"
description: "独立子问题怎样同时处理，再合成可用结论？"
pageClass: learn-agent-rust-course
prev:
  text: 第 16 章 · 提示链与条件路由
  link: /learn-agent-rust/prompt-chaining-routing
next:
  text: 第 18 章 · 规划、执行与动态重规划
  link: /learn-agent-rust/plan-execute-replan
---

# 第 17 章：并行分解与结果归并

[课程总览](./index.md) · [上一章](./prompt-chaining-routing.md) · [本部分导读](./agent-design-patterns.md) · [下一章](./plan-execute-replan.md)

::: tip 本章学习目标
- 识别真正独立的子问题，区分按问题拆分和对同一问题多次生成。
- 定义并发上限、局部失败政策及确定性归并契约。

**前置与基础：** [D02 · 提示链与条件路由](./prompt-chaining-routing.md)、[G03 · 图并行、归并与子图](./graph-parallel-subgraphs.md)。
:::

<LearnAgentRustMap active="parallel-decomposition" />

::: info 完整代码与运行方式
本章使用 Rust 1.99.1 与固定提交的 graph-flow 0.8.1。下载<a href="/learn-agent-rust/parallel-decomposition.zip" download>独立 Rust 工程</a>，解压后运行 `cargo run --locked -- suite`；`cargo test --locked` 运行回归测试，`cargo clippy --locked --all-targets -- -D warnings` 检查代码。

源码唯一位置为 `docs/public/learn-agent-rust/code/parallel-decomposition/`，下文代码直接引用该工程。验证命令：`python3 scripts/verify-agent-patterns.py --lesson D03 --check`。默认没有真实模型调用。
:::

## 1. 从任务问题开始

独立子问题怎样同时处理，再合成可用结论？

固定任务分片、独立状态、有界并发与确定性归并。

## 2. 适用与不适用

依赖、文档和配置可以各自检查时，可以按问题分片并行；同一判断的多样化生成则需要另外说明抽样和判分规则。

存在顺序依赖、争写同一文件或无法归并的任务，不宜直接同时启动；多个相似模型的投票也不自动等于独立证据。

## 3. 场景与流程

升级审查同时检查依赖兼容性、启动文档与配置变更，三个检查者只读同一修订，各自产生有来源的发现，最终由归并器形成报告。

![图展示本章实际图节点的推进关系，失败在对应合同处停止。](/learn-agent-rust/figures/d03-pattern-flow.svg)

沿上方节点读取主流程，重点看下方的report · 确定顺序。配图只表达拓扑；真实节点次序见下方输出中的 trace，不把示意布局当作性能测量。

## 状态与控制契约

| 边界 | 实验约束 |
| --- | --- |
| 输入 | 预先确定的成员清单、同一资料修订与每个成员的只读输入。 |
| 分支状态 | task_id、input_revision、status、findings 和 error；分支输出写入独立命名空间。 |
| 归并 | 验证成员齐全、无重复和版本一致，按 task_id 排序；冲突留待判定，不能只采用最后写入值。 |
| 失败与取消 | 明确全有或全无、允许部分结果的条件、超时和取消后的线程或任务回收。 |

## 4. 从合同到 Rust 实现

### 独立任务怎样真正重叠

checks 用 JoinSet 启动 config、deps、docs 三个 Tokio 任务，用 Semaphore 将同时工作的数量限制为 2。每个任务持有独立 Finding；原子计数器记录活跃峰值。短暂停顿是调度夹具，使两个任务确实重叠，不是模拟外部服务耗时，也不用于推导生产加速比。

### 完成顺序与报告顺序分开

normal 与 reverse 改变各分支的停顿顺序。收集后按成员排序，merge 再逐项核对必须出现的三个身份，拒绝重复、缺失和旧修订。仅比较数组长度不够：两个 docs 加一个 config 仍有三个元素，却缺 deps。任何必要成员失败都不生成报告。

### 取消也要等待句柄结束

cancel 在任务启动后调用 abort_all，再持续 join_next，直到 JoinSet 为空。它验证 Tokio 任务的回收，并不代表远端请求已撤销。预算在派发前预留三份 worker 额度，避免并发分支各自重新获得完整预算。

先看统一运行账本。State 的 `used` 在执行前扣除，stop 记录业务终态，trace 记录真实经过的图节点。graph-flow 的 Completed 只表示图执行结束，成功与否由 stop 判断。

<<< @/public/learn-agent-rust/code/parallel-decomposition/src/main.rs#state

本章的关键领域代码如下。先沿 match 找正常分支，再找过期、缺失或失败分支，观察它们是否在产生后续效果之前停止。

<<< @/public/learn-agent-rust/code/parallel-decomposition/src/main.rs#parallel

节点适配器把状态读出、扣费、调用领域逻辑，再保存回 Context。`GoTo` 表示受应用控制的跳转；宿主还有限制 64 次推进的兜底。每个场景从全新 Session 开始。

<<< @/public/learn-agent-rust/code/parallel-decomposition/src/main.rs#runner

## 动手实验与真实运行

先预测正常场景中的 trace，再预测 budget 场景能执行几个节点。运行独立工程后对照下面保存的真实输出。suite 每行是一个场景的状态，字段包括 scenario、used、limit、trace、stop 和 data；JSON 展开仅改变显示格式。

<<< @/public/learn-agent-rust/outputs/d03-suite.json

验证器在独立临时目录运行 4 项 Rust 回归测试、全部正常与故障场景和 Clippy，再解压最终下载包离线重新编译、复验输出。<a href="/learn-agent-rust/parallel-decomposition.zip" download>下载包</a>内的 evidence.json 记录源码摘要、场景与额外检查。运行平台为本次 macOS aarch64，Rust 1.99.1；默认固定决策，不需要密钥。

## 已验证范围与真实模型边界

真实 Tokio 并发与任务回收；停顿是夹具，无生产加速结论。 规则、角色和输入由代码预先给定，因此输出能够复核控制合同，但不能据此推导真实模型成功率或质量收益。第 22 章提供[统一模型对照入口](./pattern-composition.md#model-comparison)，配置标准 OpenAI 兼容服务后再运行；当前未产生真实模型结果。

::: warning 常见误区
异步调用和并行设计模式不是同一层概念；能同时启动，并不表示问题可以独立求解。
:::

## 本章结论

并行把独立检查同时推进，正确汇总仍由应用负责。限制活跃任务数、预留共享额度、按身份核对结果，并在取消后回收句柄，才形成完整生命周期。

## 迁移思考：归并要验证成员身份

三个并行结果中有两份来自同一成员，会发生什么？

即使结果数量正确，也会缺一个必要检查；merge 比较排序后的成员身份，拒绝通过。

批处理、分片搜索和多审查者报告都需要身份、版本和失败合同。

## 检查理解

1. 为什么三个结果还可能不完整？

   <details><summary>参考答案</summary>

   成员身份可能重复。必须比较完整成员集合，而不仅是结果数。

   </details>

2. peak=2 表示什么？

   <details><summary>参考答案</summary>

   当前短暂停顿夹具下两个任务确实同时活跃，且未超过 Semaphore 上限；它不是速度提升倍数。

   </details>

3. reverse 改变了什么？

   <details><summary>参考答案</summary>

   改变分支完成顺序；最终 report 应与 normal 一致。

   </details>

4. abort_all 之后为什么还调用 join_next？

   <details><summary>参考答案</summary>

   发送取消请求后还要确认任务结束，直到所有句柄回收。

   </details>

5. 能把相似模型投票当独立证据吗？

   <details><summary>参考答案</summary>

   不能自动这样解释。输入与误差可能相关，需另设抽样与独立判分规则。

   </details>

## 参考资料

- [Building effective agents](https://www.anthropic.com/research/building-effective-agents)：工作流、Agent 与可组合模式的工程导读；本文取其结构分类，不沿用过时 API。
- [LangGraph：Workflows and agents](https://docs.langchain.com/oss/python/langgraph/workflows-agents)：对照模式拓扑；Python API 不视为 graph-flow 等价接口。

下一章：[第 18 章 · 规划、执行与动态重规划](./plan-execute-replan.md)。回到[本部分导读](./agent-design-patterns.md)比较模式。
