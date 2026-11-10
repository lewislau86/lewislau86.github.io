---
title: "第 21 章：人工介入与审批恢复"
description: "哪里需要人的补充、选择或批准，恢复时怎样确认批准仍有效？"
pageClass: learn-agent-rust-course
prev:
  text: 第 20 章 · 评估、反思与有界修复
  link: /learn-agent-rust/evaluator-reflection
next:
  text: 第 22 章 · 模式组合与选型实战
  link: /learn-agent-rust/pattern-composition
---

# 第 21 章：人工介入与审批恢复

[课程总览](./index.md) · [上一章](./evaluator-reflection.md) · [本部分导读](./agent-design-patterns.md) · [下一章](./pattern-composition.md)

::: tip 本章学习目标
- 区分澄清输入、人工编辑和动作批准，明确人参与流程的位置。
- 把批准绑定到待执行动作的具体修订，处理拒绝、变更与重复恢复。

**前置与基础：** [D02 · 提示链与条件路由](./prompt-chaining-routing.md)、[G02 · 图暂停、会话存储与恢复](./graph-pause-resume.md)、[R03 · 工具权限与审批](./permissions.md)。
:::

<LearnAgentRustMap active="human-in-the-loop" />

::: info 完整代码与运行方式
本章使用 Rust 1.99.1 与固定提交的 graph-flow 0.8.1。下载<a href="/learn-agent-rust/human-in-the-loop.zip" download>独立 Rust 工程</a>，解压后运行 `cargo run --locked -- suite`；`cargo test --locked` 运行回归测试，`cargo clippy --locked --all-targets -- -D warnings` 检查代码。

源码唯一位置为 `docs/public/learn-agent-rust/code/human-in-the-loop/`，下文代码直接引用该工程。验证命令：`python3 scripts/verify-agent-patterns.py --lesson D07 --check`。默认没有真实模型调用。
:::

## 1. 从任务问题开始

哪里需要人的补充、选择或批准，恢复时怎样确认批准仍有效？

澄清、编辑与审批三类暂停，动作修订绑定和失效处理。

## 2. 适用与不适用

目标缺信息、结果需要人工编辑，或高影响动作需要明确授权时，在对应边界暂停并保存待解决问题。

不应在每次只读步骤都要求批准；也不应把用户曾批准某份报告解释为对所有后续动作的长期授权。

## 3. 场景与流程

升级报告先等待用户补充目标版本；草稿允许用户编辑；发布前展示目标、内容摘要和动作修订。编辑改变内容后，旧批准失效，需要重新展示再批准。

![图展示本章实际图节点的推进关系，失败在对应合同处停止。](/learn-agent-rust/figures/d07-pattern-flow.svg)

沿上方节点读取主流程，重点看下方的finish · 本地完成状态。配图只表达拓扑；真实节点次序见下方输出中的 trace，不把示意布局当作性能测量。

## 状态与控制契约

| 边界 | 实验约束 |
| --- | --- |
| 等待记录 | request_id、intervention_type、action_revision、展示内容摘要与当前状态。 |
| 响应 | request_id、decision、edited_payload 与响应身份；编辑是新输入，不自动形成批准。 |
| 动作绑定 | 批准绑定具体目标、参数与内容修订；变更、过期、已拒绝或已完成的请求不得重放为新授权。 |
| 恢复 | 恢复后重新校验必要前提；批准与外部动作效果的事务边界留给 P02，不能声称暂停恢复保证只执行一次。 |

## 4. 从合同到 Rust 实现

### 三种人工输入各改变什么

澄清把缺失目标补入内容，编辑改正文，两者都会增加 revision 并清空 approved。批准则把当前修订保存到 approved，拒绝设置 denied。edit 场景先批准修订 1，再修改内容，所以 resume 得到 needs_approval，而不是复用旧批准。

### 恢复要同时检查身份、修订与终态

decision 比较 request_id、revision，以及是否已经决定或完成。resume 只接受 approved 等于当前 revision 的请求，并防止终态重放。身份是本实验固定 CLI 输入的请求关联，不是用户认证；真实用户是谁、有无权限仍需应用层身份系统。

### 让状态跨进程保留

同一工程另提供 disk 命令。它读取 JSON、检查响应后再写临时文件，sync_all 后 rename；每条命令是独立进程。验证器会核对旧批准和重复恢复失败时原文件未被修改。限定单写者，本实现没有数据库事务、并发 CAS、目录 fsync 或物理断电耐久保证，也没有真的发布外部报告。

先看统一运行账本。State 的 `used` 在执行前扣除，stop 记录业务终态，trace 记录真实经过的图节点。graph-flow 的 Completed 只表示图执行结束，成功与否由 stop 判断。

<<< @/public/learn-agent-rust/code/human-in-the-loop/src/main.rs#state

本章的关键领域代码如下。先沿 match 找正常分支，再找过期、缺失或失败分支，观察它们是否在产生后续效果之前停止。

<<< @/public/learn-agent-rust/code/human-in-the-loop/src/main.rs#approval

节点适配器把状态读出、扣费、调用领域逻辑，再保存回 Context。`GoTo` 表示受应用控制的跳转；宿主还有限制 64 次推进的兜底。每个场景从全新 Session 开始。

<<< @/public/learn-agent-rust/code/human-in-the-loop/src/main.rs#runner

## 动手实验与真实运行

先预测正常场景中的 trace，再预测 budget 场景能执行几个节点。运行独立工程后对照下面保存的真实输出。suite 每行是一个场景的状态，字段包括 scenario、used、limit、trace、stop 和 data；JSON 展开仅改变显示格式。

<<< @/public/learn-agent-rust/outputs/d07-suite.json

验证器在独立临时目录运行 4 项 Rust 回归测试、全部正常与故障场景和 Clippy，再解压最终下载包离线重新编译、复验输出。<a href="/learn-agent-rust/human-in-the-loop.zip" download>下载包</a>内的 evidence.json 记录源码摘要、场景与额外检查。运行平台为本次 macOS aarch64，Rust 1.99.1；默认固定决策，不需要密钥。

## 已验证范围与真实模型边界

真实跨 CLI JSON 状态；单写者，无认证服务或外部发布。 规则、角色和输入由代码预先给定，因此输出能够复核控制合同，但不能据此推导真实模型成功率或质量收益。第 22 章提供[统一模型对照入口](./pattern-composition.md#model-comparison)，配置标准 OpenAI 兼容服务后再运行；当前未产生真实模型结果。

### 跨 CLI 进程恢复

下面是运行命令，不是预填输出。每条命令都会退出，再由下一进程读取同一文件；`request.json` 必须是新的路径。

```sh
cargo run --locked -- disk request.json init
cargo run --locked -- disk request.json approve 1 1
cargo run --locked -- disk request.json edit "edited report"
# 旧批准已经失效，此命令应拒绝，退出码为 2：
cargo run --locked -- disk request.json resume
cargo run --locked -- disk request.json approve 1 2
cargo run --locked -- disk request.json resume
cargo run --locked -- disk request.json show
```

落盘代码直接来自独立工程，写入前先完成校验，拒绝路径不会保存：

<<< @/public/learn-agent-rust/code/human-in-the-loop/src/main.rs#persistence

::: warning 常见误区
人在环路中也要有明确契约；一个 yes/no 提示并不能覆盖所有人工介入类型。
:::

## 本章结论

人工输入是带身份与修订的状态转换。澄清和编辑形成新输入，批准只覆盖展示过的修订；恢复前重新核对，拒绝与完成状态都不能被当成新授权。

## 迁移思考：编辑使旧批准失效

批准之后改了一句报告文字，恢复时应做什么？

内容修订变化后清空旧批准，展示新修订再决定；失败响应不得改写原状态。

发布、付款和发邮件都应把授权绑定具体内容与目标。

## 检查理解

1. 用户编辑内容等于批准吗？

   <details><summary>参考答案</summary>

   不等于。edit 增加 revision 并清空 approved，必须重新展示与批准。

   </details>

2. 为什么批准要带 request_id？

   <details><summary>参考答案</summary>

   防止把对另一个待办的响应应用到当前动作；它仍不代替用户身份认证。

   </details>

3. 重复批准为什么被拒绝？

   <details><summary>参考答案</summary>

   待办已经作出决定，重放不应形成第二次授权。

   </details>

4. disk 命令验证了什么持久化范围？

   <details><summary>参考答案</summary>

   单写者在不同 CLI 进程之间读取和保存本地 JSON。没有证明并发写、外部效果一次性或物理断电耐久。

   </details>

5. 拒绝旧批准时是否应该保存一次？

   <details><summary>参考答案</summary>

   本实验拒绝路径不保存，验证器逐字比较文件，避免错误响应改变当前状态。

   </details>

## 参考资料

- [LangGraph：Workflows and agents](https://docs.langchain.com/oss/python/langgraph/workflows-agents)：对照模式拓扑；Python API 不视为 graph-flow 等价接口。
- [LangGraph：Interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts)：暂停恢复的设计问题；Rust 行为以 G02 固定版本实验为准。

下一章：[第 22 章 · 模式组合与选型实战](./pattern-composition.md)。回到[本部分导读](./agent-design-patterns.md)比较模式。
