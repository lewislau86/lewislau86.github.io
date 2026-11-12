---
title: "第 20 章：评估、反思与有界修复"
description: "怎样依据可检查反馈修复结果，而不是无限自我评价？"
pageClass: learn-agent-rust-course
prev:
  text: 第 19 章 · 协调者、工作者与任务交接
  link: /learn-agent-rust/orchestrator-workers-handoffs
next:
  text: 第 21 章 · 人工介入与审批恢复
  link: /learn-agent-rust/human-in-the-loop
---

# 第 20 章：评估、反思与有界修复

[课程总览](./index.md) · [上一章](./orchestrator-workers-handoffs.md) · [本部分导读](./agent-design-patterns.md) · [下一章](./human-in-the-loop.md)

::: tip 本章学习目标
- 让评估反馈指向具体可验证的缺陷，而不是自由文本“再想一遍”。
- 区分单次结果修复、跨任务经验反思与受控策略改进。

**前置与基础：** [D02 · 提示链与条件路由](./prompt-chaining-routing.md)、[G01 · 图状态、条件路由与有界循环](./graph-state-routing.md)。
:::

<LearnAgentRustMap active="evaluator-reflection" />

::: info 完整代码与运行方式
本章使用 Rust 1.99.1 与固定提交的 graph-flow 0.8.1。下载<a href="/learn-agent-rust/evaluator-reflection.zip" download>独立 Rust 工程</a>，解压后运行 `cargo run --locked -- suite`；`cargo test --locked` 运行回归测试，`cargo clippy --locked --all-targets -- -D warnings` 检查代码。

源码唯一位置为 `docs/public/learn-agent-rust/code/evaluator-reflection/`，下文代码直接引用该工程。验证命令：`python3 scripts/verify-agent-patterns.py --lesson D06 --check`。默认没有真实模型调用。
:::

## 1. 从任务问题开始

怎样依据可检查反馈修复结果，而不是无限自我评价？

生成与评估分离、结构化缺陷、修复上限与保留基线。

## 2. 适用与不适用

输出有可检查的格式、引用、测试或明确评分标准时，适合生成后评估、按缺陷修复。

只有同一模型的主观“满意”且没有外部标准时，不应声称质量提高；开放式任务也不适合没有停止条件的自我反思。

## 3. 场景与流程

报告生成器提交草稿，评估器发现一个结论没有当前来源，返回 claim_id 与 missing_evidence。修复器补检索或删去无法支持的断言，再按同一标准复核。

![图展示本章实际图节点的推进关系，失败在对应合同处停止。](/learn-agent-rust/figures/d06-pattern-flow.svg)

沿上方节点读取主流程，重点看下方的重新检查 → accept / 停止。配图只表达拓扑；真实节点次序见下方输出中的 trace，不把示意布局当作性能测量。

## 状态与控制契约

| 边界 | 实验约束 |
| --- | --- |
| 候选 | candidate_revision、evidence_revision 和报告产物；保存修复前基线。 |
| 反馈 | criterion_id、claim_id、evidence、severity 和建议修复类型；评估输出须通过 schema 校验。 |
| 修复 | 只消费当前候选的有效反馈，修复后重新检查全部强制条件，不能通过删除验收规则“通过”。 |
| 判定 | 固定规则与独立评分口径优先；预算耗尽、反复同一缺陷或候选退化时返回已知状态。 |

## 4. 从合同到 Rust 实现

### 先把“质量不好”缩成可检查缺陷

Candidate 包含报告正文、来源和修订。evaluate 检查正文非空、来源必须为 README.md。normal 的初稿缺来源，反馈指出 missing_evidence。这个小规则用于验证修复机制，不能代表对复杂报告的全面质量评分。

### 反馈只能修改它检查过的候选

Feedback 用 deny_unknown_fields 和类型反序列化拒绝错误格式。repair 比较 candidate_revision，stale 的反馈来自修订 0，因此不能修改修订 1 的报告。有效修复增加修订，baseline 仍保留原候选，为以后比较提供对照。

### 修了一项，也可能破坏另一项

new_error 在补来源时清空正文。返回 evaluate 后会发现 empty_report，不能因为“上次缺的来源已经补了”就直接通过。no_progress 的修复没有改变正文或来源，立即停止；最多两次修复和宿主总额度提供额外边界。真实模型对照中的公开反馈只检查结构与引用，不把隐藏答案交给修复器。

先看统一运行账本。State 的 `used` 在执行前扣除，stop 记录业务终态，trace 记录真实经过的图节点。graph-flow 的 Completed 只表示图执行结束，成功与否由 stop 判断。

<<< @/public/learn-agent-rust/code/evaluator-reflection/src/main.rs#state

本章的关键领域代码如下。先沿 match 找正常分支，再找过期、缺失或失败分支，观察它们是否在产生后续效果之前停止。

<<< @/public/learn-agent-rust/code/evaluator-reflection/src/main.rs#evaluation

节点适配器把状态读出、扣费、调用领域逻辑，再保存回 Context。`GoTo` 表示受应用控制的跳转；宿主还有限制 64 次推进的兜底。每个场景从全新 Session 开始。

<<< @/public/learn-agent-rust/code/evaluator-reflection/src/main.rs#runner

## 动手实验与真实运行

先预测正常场景中的 trace，再预测 budget 场景能执行几个节点。运行独立工程后对照下面保存的真实输出。suite 每行是一个场景的状态，字段包括 scenario、used、limit、trace、stop 和 data；JSON 展开仅改变显示格式。

<<< @/public/learn-agent-rust/outputs/d06-suite.json

验证器在独立临时目录运行 4 项 Rust 回归测试、全部正常与故障场景和 Clippy，再解压最终下载包离线重新编译、复验输出。<a href="/learn-agent-rust/evaluator-reflection.zip" download>下载包</a>内的 evidence.json 记录源码摘要、场景与额外检查。运行平台为本次 macOS aarch64，Rust 1.99.1；默认固定决策，不需要密钥。

## 已验证范围与真实模型边界

真实图与固定规则修复；未复现完整 Reflexion，无模型质量结论。 规则、角色和输入由代码预先给定，因此输出能够复核控制合同，但不能据此推导真实模型成功率或质量收益。第 22 章提供[统一模型对照入口](./pattern-composition.md#model-comparison)，配置标准 OpenAI 兼容服务后再运行；当前未产生真实模型结果。

::: warning 常见误区
局部自我修复不等于 Reflexion 论文的完整方法，也不等于 RSI。需要跨任务经验时，另行定义写入、召回与污染控制。
:::

## 本章结论

先固定标准，再生成绑定候选版本的反馈。每次修复都重验全部条件、保留基线，并用无进展与总额度终止循环；规则通过与真实模型质量提升分别报告。

## 迁移思考：修复后重验完整合同

补充来源时把正文删空，为什么不能接受？

修复只能改变候选，不能改变验收规则；evaluate 重新检查所有强制条件，拒绝空产物。

自动修代码后也要重跑全部相关检查，不能只看原来那一条失败消失。

## 检查理解

1. 为什么保留 baseline？

   <details><summary>参考答案</summary>

   用于对照修复是否改变了结果，避免把最终状态误当原始能力。

   </details>

2. 反馈必须带哪一个版本？

   <details><summary>参考答案</summary>

   被评估候选的 revision，不能用过期反馈修改新候选。

   </details>

3. 补上引用后为什么还要检查正文？

   <details><summary>参考答案</summary>

   修复可能引入新错误，new_error 就把正文清空了。

   </details>

4. 无进展如何识别？

   <details><summary>参考答案</summary>

   当前小实验比较正文和来源是否变化，未变化即停止；复杂任务需要事先定义独立进展指标。

   </details>

5. 规则通过能否说明真实模型推理更好？

   <details><summary>参考答案</summary>

   不能。它只说明当前产物符合这组规则，质量收益需要真实服务、固定任务集与独立判分。

   </details>

## 参考资料

- [Building effective agents](https://www.anthropic.com/research/building-effective-agents)：工作流、Agent 与可组合模式的工程导读；本文取其结构分类，不沿用过时 API。
- [LangGraph：Workflows and agents](https://docs.langchain.com/oss/python/langgraph/workflows-agents)：对照模式拓扑；Python API 不视为 graph-flow 等价接口。
- [Reflexion](https://arxiv.org/abs/2303.11366)：跨尝试语言反馈与反思记忆的研究入口，区别于单次报告修复。

下一章：[第 21 章 · 人工介入与审批恢复](./human-in-the-loop.md)。回到[本部分导读](./agent-design-patterns.md)比较模式。
