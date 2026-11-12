---
title: "第 22 章：模式组合与选型实战"
description: "怎样将多个模式组合为一条可以解释和验收的任务链？"
pageClass: learn-agent-rust-course
prev:
  text: 第 21 章 · 人工介入与审批恢复
  link: /learn-agent-rust/human-in-the-loop
next:
  text: 第 23 章 · 错误分类与恢复
  link: /learn-agent-rust/error-recovery
---

# 第 22 章：模式组合与选型实战

[课程总览](./index.md) · [上一章](./human-in-the-loop.md) · [本部分导读](./agent-design-patterns.md) · [下一章](./error-recovery.md)

::: tip 本章学习目标
- 把用户目标、证据需求与动作风险映射为必要的模式组合。
- 用一条升级报告任务检验组合接缝，并以最小基线为对照。

**前置与基础：** [D03 · 并行分解与结果归并](./parallel-decomposition.md)、[D04 · 规划、执行与动态重规划](./plan-execute-replan.md)、[D05 · 协调者、工作者与任务交接](./orchestrator-workers-handoffs.md)、[D06 · 评估、反思与有界修复](./evaluator-reflection.md)、[D07 · 人工介入与审批恢复](./human-in-the-loop.md)。
:::

<LearnAgentRustMap active="pattern-composition" />

::: info 完整代码与运行方式
本章使用 Rust 1.99.1 与固定提交的 graph-flow 0.8.1。下载<a href="/learn-agent-rust/pattern-composition.zip" download>独立 Rust 工程</a>，解压后运行 `cargo run --locked -- suite`；`cargo test --locked` 运行回归测试，`cargo clippy --locked --all-targets -- -D warnings` 检查代码。

源码唯一位置为 `docs/public/learn-agent-rust/code/pattern-composition/`，下文代码直接引用该工程。验证命令：`python3 scripts/verify-agent-patterns.py --lesson D08 --check`。默认没有真实模型调用。
:::

## 1. 从任务问题开始

怎样将多个模式组合为一条可以解释和验收的任务链？

需求到拓扑、最小基线、组合契约与分层验收。

## 2. 适用与不适用

单个模式已无法表达完整业务责任，且各子结构都有明确输入、输出、额度和终止条件时，再进行组合。

不要把本部分所有模式堆进每个应用；有外部效果的端到端可靠性应继续连接后续工程与可靠性章节。

## 3. 场景与流程

升级报告采用入口路由识别资料类型，并行只读检查后归并；仅在缺少成员信息时重规划；报告通过证据评估后等待用户批准。专业角色交接只在目标需要时引入。

![图展示本章实际图节点的推进关系，失败在对应合同处停止。](/learn-agent-rust/figures/d08-pattern-flow.svg)

沿上方节点读取主流程，重点看下方的approve / publish · 修订绑定。配图只表达拓扑；真实节点次序见下方输出中的 trace，不把示意布局当作性能测量。

## 状态与控制契约

| 边界 | 实验约束 |
| --- | --- |
| 统一状态 | task_id、input_revision、evidence_revision、candidate_revision、budget 与 terminal_reason。 |
| 组合接缝 | 子结构返回 Completed、NeedsInput 或 Failed，并携带产物引用；不要用一句自然语言“成功”触发后续动作。 |
| 全局额度 | 子循环、分支和子 Agent 都记入同一累计账本，局部重试不得重新获得完整预算。 |
| 验收 | 分别检查路径是否合法、证据是否支持结论、外部效果是否发生及用户目标是否满足。 |

## 4. 从合同到 Rust 实现

### 先把接缝写成一个状态合同

统一状态记录资料修订、计划修订、成员身份、候选修订、反馈修订、批准修订与共享预算。discover 在 plan 增加 member，parallel 启动实际 Tokio 任务，merge 比较排序后的完整成员身份，并核对每个结果的修订和成功状态。旧分支、缺成员或失败分支都在生成前停止。

### 让反馈与批准追踪同一份产物

初稿故意缺 sources，evaluate 生成绑定 report_revision 的反馈。repair 添加已经归并的 evidence，候选修订从 1 变为 2。重新检查通过后才进入 approve；stale_approval 仍批准修订 1，因此 publish 拒绝。任何局部成功都不能绕过最终的版本绑定。

### 累计资源与真实文件分别核对

图节点和每个派发 worker 都在同一 State 上扣额度，不会随修复或新增成员清零。normal 与 discover 最终可输出一个真实 JSON 报告文件；验证器另外检查旧批准路径没有创建文件。这里的 publish 节点先完成内存验收，CLI 随后以 create_new 写文件；若写入失败，进程失败，不能把这条路径理解为外部发布事务或幂等恢复。

本章独立工程在同一图中组合路由、有限规划、并发、归并、修复和批准合同。它没有链接其他七个工程的模块，也没有整合 R20 的完整工具、MCP、数据库或框架会话；这些额外组合仍需各自接线验证。

先看统一运行账本。State 的 `used` 在执行前扣除，stop 记录业务终态，trace 记录真实经过的图节点。graph-flow 的 Completed 只表示图执行结束，成功与否由 stop 判断。

<<< @/public/learn-agent-rust/code/pattern-composition/src/main.rs#state

本章的关键领域代码如下。先沿 match 找正常分支，再找过期、缺失或失败分支，观察它们是否在产生后续效果之前停止。

<<< @/public/learn-agent-rust/code/pattern-composition/src/main.rs#composition

节点适配器把状态读出、扣费、调用领域逻辑，再保存回 Context。`GoTo` 表示受应用控制的跳转；宿主还有限制 64 次推进的兜底。每个场景从全新 Session 开始。

<<< @/public/learn-agent-rust/code/pattern-composition/src/main.rs#runner

## 动手实验与真实运行

先预测正常场景中的 trace，再预测 budget 场景能执行几个节点。运行独立工程后对照下面保存的真实输出。suite 每行是一个场景的状态，字段包括 scenario、used、limit、trace、stop 和 data；JSON 展开仅改变显示格式。

<<< @/public/learn-agent-rust/outputs/d08-suite.json

验证器在独立临时目录运行 4 项 Rust 回归测试、全部正常与故障场景和 Clippy，再解压最终下载包离线重新编译、复验输出。<a href="/learn-agent-rust/pattern-composition.zip" download>下载包</a>内的 evidence.json 记录源码摘要、场景与额外检查。运行平台为本次 macOS aarch64，Rust 1.99.1；默认固定决策，不需要密钥。

## 已验证范围与真实模型边界

真实图、Tokio、报告文件与本地 HTTP；模型决策和批准仍为夹具。 规则、角色和输入由代码预先给定，因此输出能够复核控制合同，但不能据此推导真实模型成功率或质量收益。第 22 章提供[统一模型对照入口](./pattern-composition.md#model-comparison)，配置标准 OpenAI 兼容服务后再运行；当前未产生真实模型结果。

## 配置真实模型对照 {#model-comparison}

独立工程带有 `model_compare.py` 和公开的 `model-cases.json`，只用 Python 标准库。先运行本地 HTTP 自检：

```sh
python3 model_compare.py self-test ./fixture-run
```

它启动真实 loopback HTTP 服务，用固定响应跑 9 种结构、每种 4 道题，共 36 项任务。全通过只表示驱动器正常，fixture 的 token 是合成数据，不能当模型用量或费用。

你可以在本机设置 `OPENAI_BASE_URL`（例如服务地址加 `/v1`）、`OPENAI_MODEL` 和服务需要的 `OPENAI_API_KEY`，然后运行：

```sh
# 请先在本机环境配置服务地址、模型和密钥；不要写入仓库。
python3 model_compare.py live ./live-run --repeats 3
# 也可先比较最小基线与组合：
python3 model_compare.py live ./live-pair --repeats 3 --variants single composed
```

HTTP 适配器发送标准非流式 chat/completions 请求，显式设置 temperature=0、max_tokens=512；服务若不支持这些字段，会记录失败而不是自动改变配方。允许 HTTPS 或本机 HTTP，禁止重定向和系统代理。模型凭据不写入结果。

<<< @/public/learn-agent-rust/code/pattern-composition/model_compare.py#http

九种变体有真实不同的控制路径：single 一次生成，chain 先抽取再生成，routing 先选 README，parallel 限并发抽取，replan 观察清单后修订读取计划，workers 由模型提出白名单任务，repair 在公开结构与来源检查失败时有限修复，human 为候选绑定脚本批准，composed 组合动态分派、并行、修复与批准。

<<< @/public/learn-agent-rust/code/pattern-composition/model_compare.py#patterns

**比较口径。** 同一四题公开合成诊断集，覆盖单项目、workspace、含恶意指令资料和缺失文件；每种变体重复 3 次，固定顺序随机化种子 1729。重复是推理试验，不是训练种子；temperature=0 也不保证服务完全确定。每个任务最多 8 次 HTTP 请求，派发最多并发 2 个，每次最多生成 512 token，无自动重试。全九种共计划 108 项任务、上限 864 次请求；single/composed 共 24 项任务、上限 192 次请求。各结构实际调用数不同，需与成功率一起报告。 这是方案级比较：组合同时改变分解、筛选、并行与反馈，结果差异不能单独归因给其中一个模式；需要归因时，再逐个关闭组件做同输入消融。

评分器对照独立标签检查每个 member 的精确启动命令、null 缺失值和来源列表。标签不进入模型请求；修复反馈只检查公开的结构、成员和来源，不把正确命令直接告诉模型。批准为脚本输入，不测人工决策质量；没有执行真实发布操作。

`attempts.json` 保存每个尝试、答案、失败、调用数、服务原始 usage 和耗时；`report.json` 保存任务、策略、驱动器哈希、请求与响应模型、每次重复成功率及平均和范围。失败留在计划分母内；认证或限流时提前停止并记录 attempted/planned。缺 usage 保持 null，费用未知，不填零。请求耗时和任务耗时分别记录；p95 在小样本中不稳定。

**当前状态：真实服务未运行。** 本节提供可复现的评估入口，不预填质量提升数字。Python 驱动器验证 OpenAI 兼容服务上的模式对照，Rust 工程验证真实 graph-flow 合同；目前没有把该 HTTP 模型适配器接入 Rust 节点。四题都是公开诊断样例，不构成独立泛化测试、供应商排名或生产质量保证。

::: warning 常见误区
组合正确性需要接缝证据；每个局部模式单独通过，不代表一起运行时状态、额度与权限仍正确。
:::

## 本章结论

组合的验收对象是跨节点合同：同一资料修订、完整成员、当前反馈、有效批准和累计预算。图走到最后之前，先证明证据支持当前产物，再允许创建报告。

## 迁移思考：组合验证接缝

分支结果与批准都各自有效，但属于不同修订，能创建报告吗？

不能。先用统一修订关系串起证据、候选和批准；局部有效不构成同一交付的有效证据。

跨服务业务需要同样的关联身份和版本合同，并另验外部效果与恢复。

## 检查理解

1. 每个局部节点通过就能保证组合正确吗？

   <details><summary>参考答案</summary>

   不能。旧分支、旧反馈和旧批准都可能在接缝处失配，需要额外场景验证。

   </details>

2. discover 增加成员后检查什么？

   <details><summary>参考答案</summary>

   检查完整成员集合、来源修订以及最终来源列表，不能只判断某个任务返回成功。

   </details>

3. 修复后的旧批准为什么无效？

   <details><summary>参考答案</summary>

   report_revision 已从 1 变为 2，批准必须覆盖当前产物修订。

   </details>

4. 本地 HTTP fixture 的全通过说明什么？

   <details><summary>参考答案</summary>

   说明对照驱动器的接线、预算、评分与并发路径可运行；响应由固定程序提供，不代表真实模型效果。

   </details>

5. 真实服务配置后怎样解释成功率？

   <details><summary>参考答案</summary>

   在公开四题诊断集、固定总预算下报告各变体每次重复和平均范围，失败保留分母；不能据此推断泛化或模型排名。

   </details>

## 参考资料

- [Building effective agents](https://www.anthropic.com/research/building-effective-agents)：工作流、Agent 与可组合模式的工程导读；本文取其结构分类，不沿用过时 API。
- [LangGraph：Workflows and agents](https://docs.langchain.com/oss/python/langgraph/workflows-agents)：对照模式拓扑；Python API 不视为 graph-flow 等价接口。

下一章：[第 23 章 · 错误分类与恢复](./error-recovery.md)。回到[本部分导读](./agent-design-patterns.md)比较模式。
