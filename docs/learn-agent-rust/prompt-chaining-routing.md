---
title: "第 16 章：提示链与条件路由"
description: "已知步骤怎样串联，不同输入怎样进入合适的处理分支？"
pageClass: learn-agent-rust-course
prev:
  text: 第 15 章 · 模式选择：单次调用、工作流与自主循环
  link: /learn-agent-rust/pattern-selection
next:
  text: 第 17 章 · 并行分解与结果归并
  link: /learn-agent-rust/parallel-decomposition
---

# 第 16 章：提示链与条件路由

[课程总览](./index.md) · [上一章](./pattern-selection.md) · [本部分导读](./agent-design-patterns.md) · [下一章](./parallel-decomposition.md)

::: tip 本章学习目标
- 把任务拆成有输入输出契约的提示链，在步骤之间设置可检查的质量门。
- 区分业务规则路由与模型分类路由，并为未知类别设置兜底。

**前置与基础：** [D01 · 模式选择：单次调用、工作流与自主循环](./pattern-selection.md)、[G01 · 图状态、条件路由与有界循环](./graph-state-routing.md)。
:::

<LearnAgentRustMap active="prompt-chaining-routing" />

::: info 完整代码与运行方式
本章使用 Rust 1.99.1 与固定提交的 graph-flow 0.8.1。下载<a href="/learn-agent-rust/prompt-chaining-routing.zip" download>独立 Rust 工程</a>，解压后运行 `cargo run --locked -- suite`；`cargo test --locked` 运行回归测试，`cargo clippy --locked --all-targets -- -D warnings` 检查代码。

源码唯一位置为 `docs/public/learn-agent-rust/code/prompt-chaining-routing/`，下文代码直接引用该工程。验证命令：`python3 scripts/verify-agent-patterns.py --lesson D02 --check`。默认没有真实模型调用。
:::

## 1. 从任务问题开始

已知步骤怎样串联，不同输入怎样进入合适的处理分支？

步骤间结构化产物、质量门、类型化路由与兜底分支。

## 2. 适用与不适用

资料读取、事实抽取、报告生成有稳定顺序时适合提示链；文档、代码、配置需要不同处理器时适合条件路由。

步骤无法预先列出时不宜硬编码成很长的链；没有足够样本检验分类错误时，不宜把高影响动作直接交给模型路由。

## 3. 场景与流程

升级报告先从文件抽取依赖，再核对版本，最后写结论。入口按文件类型路由：README 进入说明抽取，Cargo.toml 进入依赖解析，未知输入进入澄清。

![图展示本章实际图节点的推进关系，失败在对应合同处停止。](/learn-agent-rust/figures/d02-pattern-flow.svg)

沿上方节点读取主流程，重点看下方的render · 消费已验产物。配图只表达拓扑；真实节点次序见下方输出中的 trace，不把示意布局当作性能测量。

## 状态与控制契约

| 边界 | 实验约束 |
| --- | --- |
| 输入 | 输入类型、文件版本和允许处理的类别枚举。 |
| 中间产物 | 抽取记录包含 source、revision、facts、missing_fields；下一步消费校验后的字段。 |
| 控制权 | 路由输出只能选择已注册类别；业务节点映射类别到后继，禁止任意节点名或路径。 |
| 停止 | 质量门失败时补资料或结束；循环仍受总步数和调用预算约束。 |

## 4. 从合同到 Rust 实现

### 路由的结果是类型，不是任意地址

classify 只允许 README.md 和 Cargo.toml，返回固定类别。输入 other.bin 转为 needs_input；没有将外部文本拼进节点名称。这里采用文件名规则，读者可把分类器替换成模型，但必须保留同一个类别白名单和兜底分支。

### 为什么抽取后还要一道门

Artifact 不只是 command 字符串，还携带 source 与 revision。extract 产生的对象先存入状态，gate 才检查必填字段与当前资料修订。stale 场景将产物修订设为 1，而当前输入是 2，render 因此不会运行。即使旧命令看起来正确，也不应作为本轮证据。

### 失败不能沿用上一轮的成功产物

Node 的 stop 会结束图，render 只消费通过 gate 的 artifact。本实验每个场景使用新 Session；生产复用会话时，还应在开始新修订时清理旧产物，并保留来源身份。Cargo 分支的 cargo test 来自固定抽取夹具，未声称实现通用 TOML 解析。

先看统一运行账本。State 的 `used` 在执行前扣除，stop 记录业务终态，trace 记录真实经过的图节点。graph-flow 的 Completed 只表示图执行结束，成功与否由 stop 判断。

<<< @/public/learn-agent-rust/code/prompt-chaining-routing/src/main.rs#state

本章的关键领域代码如下。先沿 match 找正常分支，再找过期、缺失或失败分支，观察它们是否在产生后续效果之前停止。

<<< @/public/learn-agent-rust/code/prompt-chaining-routing/src/main.rs#chain

节点适配器把状态读出、扣费、调用领域逻辑，再保存回 Context。`GoTo` 表示受应用控制的跳转；宿主还有限制 64 次推进的兜底。每个场景从全新 Session 开始。

<<< @/public/learn-agent-rust/code/prompt-chaining-routing/src/main.rs#runner

## 动手实验与真实运行

先预测正常场景中的 trace，再预测 budget 场景能执行几个节点。运行独立工程后对照下面保存的真实输出。suite 每行是一个场景的状态，字段包括 scenario、used、limit、trace、stop 和 data；JSON 展开仅改变显示格式。

<<< @/public/learn-agent-rust/outputs/d02-suite.json

验证器在独立临时目录运行 4 项 Rust 回归测试、全部正常与故障场景和 Clippy，再解压最终下载包离线重新编译、复验输出。<a href="/learn-agent-rust/prompt-chaining-routing.zip" download>下载包</a>内的 evidence.json 记录源码摘要、场景与额外检查。运行平台为本次 macOS aarch64，Rust 1.99.1；默认固定决策，不需要密钥。

## 已验证范围与真实模型边界

规则路由与固定抽取；真实 graph-flow 产物门，模型分类另验。 规则、角色和输入由代码预先给定，因此输出能够复核控制合同，但不能据此推导真实模型成功率或质量收益。第 22 章提供[统一模型对照入口](./pattern-composition.md#model-comparison)，配置标准 OpenAI 兼容服务后再运行；当前未产生真实模型结果。

::: warning 常见误区
提示链中的每个节点不一定是 Agent；确定性解析器和校验器应保留在适合的位置。
:::

## 本章结论

提示链的价值来自步骤间合同：上游明确产物来源与修订，下游只消费已验证字段。路由负责选合法路径，质量门负责阻止缺项和旧数据。

## 迁移思考：中间成功也需要版本

抽取正确但属于上一版文件，能继续生成报告吗？

不能。先核对来源修订，再让下游消费；字段正确和证据当前有效是两个条件。

订单核验中的旧库存、旧价格也需要同样的版本门。

## 检查理解

1. 为什么不直接让模型返回节点名？

   <details><summary>参考答案</summary>

   节点名属于执行权限。把模型输出限制为合法类别，再由宿主映射，能拒绝未知或越权目标。

   </details>

2. command 非空就能进入 render 吗？

   <details><summary>参考答案</summary>

   还要验证 artifact.revision 与当前输入一致；非空的旧命令仍然过期。

   </details>

3. unknown 分支的正确结果是什么？

   <details><summary>参考答案</summary>

   needs_input，返回澄清入口，而不是猜测一个解析器。

   </details>

4. gate 和 extract 能否合并？

   <details><summary>参考答案</summary>

   可以在实现上合并，但抽取合同与验收责任仍应清楚；分开后更易定位错误与替换模型。

   </details>

5. 如何评价真实模型路由？

   <details><summary>参考答案</summary>

   在固定有标签任务集统计分类错误、兜底率及最终通过率，分别报告，不能只统计模型是否返回 JSON。

   </details>

## 参考资料

- [Building effective agents](https://www.anthropic.com/research/building-effective-agents)：工作流、Agent 与可组合模式的工程导读；本文取其结构分类，不沿用过时 API。
- [LangGraph：Workflows and agents](https://docs.langchain.com/oss/python/langgraph/workflows-agents)：对照模式拓扑；Python API 不视为 graph-flow 等价接口。

下一章：[第 17 章 · 并行分解与结果归并](./parallel-decomposition.md)。回到[本部分导读](./agent-design-patterns.md)比较模式。
