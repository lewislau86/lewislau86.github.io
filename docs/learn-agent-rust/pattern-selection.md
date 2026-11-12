---
title: "第 15 章：模式选择：单次调用、工作流与自主循环"
description: "任务需要多少控制结构，什么时候值得让模型决定下一步？"
pageClass: learn-agent-rust-course
prev:
  text: 第 14 章 · 系统提示词组装
  link: /learn-agent-rust/system-prompts
next:
  text: 第 16 章 · 提示链与条件路由
  link: /learn-agent-rust/prompt-chaining-routing
---

# 第 15 章：模式选择：单次调用、工作流与自主循环

[课程总览](./index.md) · [上一章](./system-prompts.md) · [本部分导读](./agent-design-patterns.md) · [下一章](./prompt-chaining-routing.md)

::: tip 本章学习目标
- 能根据步骤是否已知、下一步由谁决定，选择单次调用、工作流或有界工具循环。
- 为升级报告列出最小基线、失败条件和引入更复杂模式的证据。

**前置与基础：** [R01 · 最小 Agent 循环](./agent-loop.md)、[G01 · 图状态、条件路由与有界循环](./graph-state-routing.md)、[R10 · 系统提示词组装](./system-prompts.md)。
:::

<LearnAgentRustMap active="pattern-selection" />

::: info 完整代码与运行方式
本章使用 Rust 1.99.1 与固定提交的 graph-flow 0.8.1。下载<a href="/learn-agent-rust/pattern-selection.zip" download>独立 Rust 工程</a>，解压后运行 `cargo run --locked -- suite`；`cargo test --locked` 运行回归测试，`cargo clippy --locked --all-targets -- -D warnings` 检查代码。

源码唯一位置为 `docs/public/learn-agent-rust/code/pattern-selection/`，下文代码直接引用该工程。验证命令：`python3 scripts/verify-agent-patterns.py --lesson D01 --check`。默认没有真实模型调用。
:::

## 1. 从任务问题开始

任务需要多少控制结构，什么时候值得让模型决定下一步？

比较单次调用、预设工作流和有界工具循环，建立成本与风险基线。

## 2. 适用与不适用

输入已齐全、一次变换足够时，先用单次调用；步骤与验收点已知时，用工作流；下一步依赖工具观察时，再考虑有界自主循环。

不要因为有模型或检索，就默认需要多 Agent；也不要把固定流程的模型分类节点等同于整个系统自主决策。

## 3. 场景与流程

同一份升级报告有三种需求：提供完整资料后整理摘要；按既定清单读取资料并核对字段；检查中遇到未知依赖，需要自行决定补读什么。三者分别形成基线、固定工作流与有界循环。

![图展示本章实际图节点的推进关系，失败在对应合同处停止。](/learn-agent-rust/figures/d01-pattern-flow.svg)

沿上方节点读取主流程，重点看下方的accept · 验收或停止。配图只表达拓扑；真实节点次序见下方输出中的 trace，不把示意布局当作性能测量。

## 状态与控制契约

| 边界 | 实验约束 |
| --- | --- |
| 输入 | 用户目标、允许动作、完成标准，以及预先给定的资料。 |
| 状态 | 证据清单、已执行动作、剩余额度与当前终止原因；不要求记录模型私有思维过程。 |
| 控制权 | 工作流路径由代码限定；自主循环可提出下一动作，宿主仍验证工具参数、权限与额度。 |
| 输出 | 报告及来源，或带原因的未完成结果；模型说“完成”不能替代目标检查。 |

## 4. 从合同到 Rust 实现

### 先看一次调用为什么足够

`choose(ready, dynamic)` 的第一个判断是资料是否齐全。`single` 已拿到 root 证据，于是图从 choose 跳到 generate，省去读取节点。这个分支没有把“少调用”当成更聪明，只是输入合同已经满足。workflow 的资料未齐全但步骤已知，按 read → observe → generate 推进。

### 观察怎样改变下一步

`adaptive` 第一次读取 root 后发现 member，observe 通过 `GoTo("read")` 再读一次，再回到生成。读者可以先预测两条轨迹中 read 出现几次，然后查看实测 JSON 的 `trace`、`data.reads` 和 `used`。两种输入不同，因此这组实验是在验证选型行为，不能拿调用数直接宣称自主循环更差。

### 预算与动作权限由宿主执行

Node 在执行领域逻辑前调用 `charge(1)`，拒绝后直接结束；模型提出下一步也不能跳过这个入口。`forbidden` 在增加 reads 之前停止，`missing` 不进入生成。这里的读动作由确定性夹具表示，并未真正访问项目文件；本章证明控制结构和拒绝顺序。真实文件、模型选择质量分别由原工具章与第 22 章入口另验。

先看统一运行账本。State 的 `used` 在执行前扣除，stop 记录业务终态，trace 记录真实经过的图节点。graph-flow 的 Completed 只表示图执行结束，成功与否由 stop 判断。

<<< @/public/learn-agent-rust/code/pattern-selection/src/main.rs#state

本章的关键领域代码如下。先沿 match 找正常分支，再找过期、缺失或失败分支，观察它们是否在产生后续效果之前停止。

<<< @/public/learn-agent-rust/code/pattern-selection/src/main.rs#selection

节点适配器把状态读出、扣费、调用领域逻辑，再保存回 Context。`GoTo` 表示受应用控制的跳转；宿主还有限制 64 次推进的兜底。每个场景从全新 Session 开始。

<<< @/public/learn-agent-rust/code/pattern-selection/src/main.rs#runner

## 动手实验与真实运行

先预测正常场景中的 trace，再预测 budget 场景能执行几个节点。运行独立工程后对照下面保存的真实输出。suite 每行是一个场景的状态，字段包括 scenario、used、limit、trace、stop 和 data；JSON 展开仅改变显示格式。

<<< @/public/learn-agent-rust/outputs/d01-suite.json

验证器在独立临时目录运行 4 项 Rust 回归测试、全部正常与故障场景和 Clippy，再解压最终下载包离线重新编译、复验输出。<a href="/learn-agent-rust/pattern-selection.zip" download>下载包</a>内的 evidence.json 记录源码摘要、场景与额外检查。运行平台为本次 macOS aarch64，Rust 1.99.1；默认固定决策，不需要密钥。

## 已验证范围与真实模型边界

真实 graph-flow；读取与决策是内存夹具，模型质量另验。 规则、角色和输入由代码预先给定，因此输出能够复核控制合同，但不能据此推导真实模型成功率或质量收益。第 22 章提供[统一模型对照入口](./pattern-composition.md#model-comparison)，配置标准 OpenAI 兼容服务后再运行；当前未产生真实模型结果。

::: warning 常见误区
“循环更多”“角色更多”都不是改进证据。只有基线在明确需求上失败，才有理由增加结构。
:::

## 本章结论

先检查输入合同，再决定谁选择下一步。资料齐全选单次变换，步骤已知选工作流，新观察会改变动作时使用有界循环；三者共享执行前权限与预算检查。

## 迁移思考：输入合同决定最小结构

资料已齐全，却仍让循环反复补读，会增加什么？

增加调用与失败位置，却未增加必要信息。先对照输入合同和最终验收，而非把轨迹长短当能力。

在报表生成中，完整表格可以直接转换；未知数据源才需要逐步发现。

## 检查理解

1. 为什么 single 不运行 read？

   <details><summary>参考答案</summary>

   它的输入已经包含 root 证据，choose 跳到 generate；少一次调用来自输入条件，而非自动获得更高质量。

   </details>

2. adaptive 的第二次读取由谁触发？

   <details><summary>参考答案</summary>

   observe 检查第一次读取的结果，再返回 GoTo(read)。下一步依赖当前观察。

   </details>

3. 把 limit 设为 1 后，会读取资料吗？

   <details><summary>参考答案</summary>

   不会。choose 用掉唯一额度，read 入口扣费失败，读取计数仍为 0。

   </details>

4. 工作流里能否包含模型节点？

   <details><summary>参考答案</summary>

   可以。工作流描述路径由程序限定，节点内部仍能调用模型；是否使用模型不是两者的分类标准。

   </details>

5. 本章调用数能否证明哪种结构最优？

   <details><summary>参考答案</summary>

   不能。不同分支使用不同输入条件，且决策采用夹具。公平质量比较需同任务、同工具和同总预算，见第 22 章。

   </details>

## 参考资料

- [Building effective agents](https://www.anthropic.com/research/building-effective-agents)：工作流、Agent 与可组合模式的工程导读；本文取其结构分类，不沿用过时 API。
- [LangGraph：Workflows and agents](https://docs.langchain.com/oss/python/langgraph/workflows-agents)：对照模式拓扑；Python API 不视为 graph-flow 等价接口。
- [ReAct](https://arxiv.org/abs/2210.03629)：观察、行动与任务推理交替的研究入口；本课程记录动作、结果与公开决策摘要。

下一章：[第 16 章 · 提示链与条件路由](./prompt-chaining-routing.md)。回到[本部分导读](./agent-design-patterns.md)比较模式。
