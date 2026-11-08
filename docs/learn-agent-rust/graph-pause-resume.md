---
title: "第 6 章：图暂停、会话存储与恢复"
description: "实现真实 graph-flow SessionStorage，用 SQLite 保存游标与状态，跨进程恢复审批并验证修订、冲突和终态边界。"
pageClass: learn-agent-rust-course
prev:
  text: 第 5 章 · 图状态、条件路由与有界循环
  link: /learn-agent-rust/graph-state-routing
next:
  text: 第 7 章 · 图并行、归并与子图
  link: /learn-agent-rust/graph-parallel-subgraphs
---

# 第 6 章：图暂停、会话存储与恢复

[课程总览](./index.md) · [上一章](./graph-state-routing.md) · [下一章](./graph-parallel-subgraphs.md)

::: tip 本章学习目标
- 解释 WaitForInput 以后再次执行的位置，并设计可重新进入的审批节点。
- 实现 SessionStorage，通过 FlowRunner 保存、加载和推进真实图会话。
- 验证跨进程恢复、旧修订拒绝、存储冲突与终态保护。

**前置：** [图状态与路由](./graph-state-routing.md)、[工具权限与审批](./permissions.md)。

**实践方式：** <a href="/learn-agent-rust/graph-pause-resume.zip" download>下载独立工程</a>。固定 Rust 1.99.1、graph-flow 0.8.1 revision 与 SQLite 依赖；首次获取依赖需要网络，运行无需模型或数据库服务。
:::

升级报告进入批准环节，但审批人明天才回复。今天的进程退出以后，明天的新进程至少要知道三件事：正在批准哪一版报告、当前停在哪个节点、此前哪些步骤已经完成。

本章沿用升级审查，只生成 Context 中的一份报告字符串。我们把“等待”变成可保存的会话，再逐步验证恢复入口。实验标识 G02 用于命令定位，章节顺序由课程清单决定。

<LearnAgentRustMap active="graph-pause-resume" />

<!-- experiment-library:start -->

全书实验可从[统一代码库](./experiments.md#graph-pause-resume)下载；解压后进入 `chapters/graph-pause-resume/`，或运行 `python3 run.py run G02`。

<!-- experiment-library:end -->

::: info 唯一源码与验证范围
所有片段来自<a href="/learn-agent-rust/code/graph-pause-resume/src/main.rs" download>完整 main.rs</a>。节点与存储真实调用固定 graph-flow；SQLite 真正写入磁盘，验证器通过独立 CLI 进程继续会话。审批输入由本地固定命令提供，身份认证、外部发布与多执行者业务推进另验。
:::

## 1. 先区分会话、图和存储

图包含处理函数，每次 CLI 启动都从代码重新构建。Session 包含会话身份、图身份、当前游标、版本与 Context；存储保存它的序列化数据。恢复时，我们先核对保存的数据能否交给当前这张图，再执行游标指向的节点。

![宿主从 SQLite 加载会话，在等待节点保存当前位置，独立进程提交绑定修订的决定后继续执行，再保存新的版本。](/learn-agent-rust/figures/g02-resume-boundary.svg)

沿箭头看 load → run → save；下方标出的窗口说明：节点运行和会话保存是两个边界。以后若节点调用了外部服务，数据库中的会话版本不会自动覆盖服务已经发生的效果。

| 保存内容 | 恢复时要回答的问题 |
| --- | --- |
| `id`、`graph_id` | 这是哪个会话，应由哪一版图处理？ |
| `current_task_id` | 下次重新进入哪个节点？ |
| `version` | 当前写入者读到的是不是最新快照？ |
| `schema`、`revision` | 数据结构是否兼容，批准是否对应当前提案？ |
| `decision`、`terminal`、步骤结果 | 输入是否已经提交，业务是否已经结束？ |

本例只接受图身份 `release-review-v1`、schema 1 与已知游标。这里的图身份是应用约定；需要改变节点契约时，维护者应升级它并提供迁移或拒绝策略。

## 2. 等待意味着以后重新运行这个节点

流程为 draft → approve；批准后跳到 render，拒绝则跳到 reject。没有决定时，approve 返回 `WaitForInput`，游标仍是 approve。

<<< @/public/learn-agent-rust/code/graph-pause-resume/src/main.rs#approval

再次执行会从 approve 的 `run` 开头进入。为了让行为可见，节点每次增加 `visits.approve`。这个计数也提醒我们：等待前放置发送邮件之类的动作，会在重新进入时再次发生。需要一次性效果时，应另设步骤和稳定的操作身份，并在[外部操作可靠性](./side-effect-reliability.md)定义重放策略。

本例提交决定时同时写入 `approved_revision`。提交入口和审批节点都检查它与当前 `revision` 一致；重复提交也会拒绝。真实业务可把路径、金额、内容摘要等纳入审批对象，本例用修订号展示这一绑定。

::: tip 与 LangGraph 的联系
LangGraph 的 interrupt/resume 帮助我们提出“恢复会重跑哪些代码”的问题。本章实际使用 graph-flow 的 WaitForInput：输入由应用写入 Context，再重新调用当前节点。接口和保存机制以本章固定源码为准，概念对照见[图编排导读](./graph-orchestration.md)。
:::

## 3. 把真实 SessionStorage 接到 SQLite

<<< @/public/learn-agent-rust/code/graph-pause-resume/src/main.rs#storage

save 在 `BEGIN IMMEDIATE` 事务中读取版本，再比较调用者携带的版本。已有记录不匹配，或者旧版本非零但记录不存在，都返回 `SessionConflict`。成功时递增版本，把新版本与 Session JSON 一起提交。get 核对 SQL 行身份、版本与 JSON 中的对应字段，损坏数据直接返回错误。

这不是简单地“把某个 HashMap 写成 JSON”：实现的是框架的 SessionStorage trait，FlowRunner 会实际使用它。序列化也创建了独立数据快照，避开 `Context.clone()` 共享底层数据的问题。

这里使用同步 SQLite 接口服务于短生命周期 CLI；若迁入高并发异步服务，需要单独设计阻塞隔离、连接管理和执行所有权。

## 4. 宿主怎样决定继续还是返回

<<< @/public/learn-agent-rust/code/graph-pause-resume/src/main.rs#runner

固定版本的 FlowRunner 负责加载会话、执行图，并在执行返回 Ok 后保存。一次运行几个节点，取决于节点返回 Continue、GoTo 或 ContinueAndExecute 等动作；本例每次最多运行一个业务节点。

本例的宿主还先检查 `terminal`。这是必要的应用约束：graph-flow 的 End 保持终态节点的游标，再次直接执行仍会进入该节点。Rust 测试绕过宿主保护，确认 render 可以被调用两次；正常 CLI 会打印 already_completed，不再渲染。

这个保护针对本章单执行者的正常续跑。两个执行者同时进入 render 时，保存时 CAS 才发现冲突；如果 render 有外部效果，两个执行者可能都已调用它。因此 CAS 解决旧快照覆盖，业务执行权与幂等还需要另外设计。

## 5. 用多个真实进程走完一次审批

在解压后的工程目录运行，每行都是一次独立 CLI 进程。使用尚不存在的数据库路径：

```sh
cargo run --locked -- review.db init
cargo run --locked -- review.db step
cargo run --locked -- review.db step
cargo run --locked -- review.db step
cargo run --locked -- review.db approve 1 yes
cargo run --locked -- review.db step
cargo run --locked -- review.db step
cargo run --locked -- review.db step
cargo run --locked -- review.db show
```

实际输出：

<<< @/public/learn-agent-rust/outputs/g02-approved.txt

draft 只进入一次。没有批准时两次进入 approve，批准后第三次进入并转移游标，render 只进入一次。最后一次 step 由宿主拒绝重复推进，版本仍为 7。

另建数据库，把 yes 改为 no，真实拒绝路径输出：

<<< @/public/learn-agent-rust/outputs/g02-denied.txt

reject 同样是正常终态，但没有报告。Completed 仍然只说明图的结束状态。

## 6. 先预测恢复失败，再运行拒绝路径

批准 revision 0 会怎样？已经保存一次决定以后再提交会怎样？两个写入者同时持有同一版快照，后保存者会怎样？验证器实际执行并核对数据库，得到：

<<< @/public/learn-agent-rust/outputs/g02-approval-refusals.txt

<<< @/public/learn-agent-rust/outputs/g02-conflict.txt

再分别修改保存记录的图身份、schema、游标、行版本与 JSON，恢复入口逐一拒绝：

<<< @/public/learn-agent-rust/outputs/g02-invalid-snapshots.txt

独立工程包含 4 项 Rust 测试；完整验证器还执行 10 组正常或拒绝场景，通过独立 CLI 进程和 Python SQLite 查询核对保存结果，再解压下载包重新编译复验。运行维护验证：

```sh
python3 scripts/verify-agent-orchestration.py --check
```

这条命令在网站仓库运行，会一起检查三章编排实验。解压后的单章工程运行 `cargo test --locked`，完整步骤见包内 README。

::: warning 常见误区
- WaitForInput 会在下次运行重新进入当前节点；等待前的代码需要考虑重复执行。
- End 没有自动保存“永远不能再运行”的锁；本例由宿主检查持久化终态。
- CAS 保护保存版本，不会撤回此前的节点效果；本例只允许一个业务执行者推进。
- 本地 approve 命令没有用户认证，也没有验证真实审批服务或外部发布。
:::

## 本章结论

恢复协议由图、会话和宿主共同完成：保存游标与数据，校验图和 schema，绑定批准对象，明确终态，并验证新进程真正从保存位置继续。只保存一份结果文本不足以表达这些契约。

## 迁移思考：保存冲突与效果重放分别处理

两个执行者都读取旧版本，后写入者被 CAS 拒绝，是否已经避免重复发布？

<details><summary>参考推演</summary>

先检查发布发生在保存之前还是之后；保存冲突只能阻止旧快照覆盖，无法撤销两个执行者已经发出的请求。

迁移到付款审批时，需要把执行所有权、稳定操作身份和业务幂等与会话版本一起设计。

</details>

## 检查理解

1. 恢复时为什么需要重新建立 Graph？

   <details><summary>参考答案</summary>

   Session 保存数据和游标，节点处理函数由当前程序提供。入口还要检查图契约与保存的数据兼容。

   </details>

2. 批准为什么同时保存修订号？

   <details><summary>参考答案</summary>

   它把决定绑定到具体提案；内容改变以后旧批准不应自动继续授权新提案。

   </details>

3. waiting 状态第二次 step 会执行哪里？

   <details><summary>参考答案</summary>

   重新从 approve 的 run 开始；本例访问计数随之增加，未提交决定时继续等待。

   </details>

4. 为什么 SQL version 与 JSON version 要一起保存？

   <details><summary>参考答案</summary>

   版本比较和恢复数据必须属于同一份快照。get 再核对二者一致，避免接受损坏或错配的记录。

   </details>

5. 可以把本例称为跨进程恢复通过吗？

   <details><summary>参考答案</summary>

   可以，范围是本地 SQLite 会话和固定审批流程；外部效果、认证、多执行者推进和任意旧版本迁移需要分别验证。

   </details>

## 参考资料

- 固定版本 [runner.rs](https://github.com/a-agmon/rs-graph-llm/blob/9bbca193f20a8c4ba23289621549ecb3d35fee64/graph-flow/src/runner.rs)、[storage.rs](https://github.com/a-agmon/rs-graph-llm/blob/9bbca193f20a8c4ba23289621549ecb3d35fee64/graph-flow/src/storage.rs)、[graph.rs](https://github.com/a-agmon/rs-graph-llm/blob/9bbca193f20a8c4ba23289621549ecb3d35fee64/graph-flow/src/graph.rs)。
- LangGraph 官方 [Interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts)与 [Persistence](https://docs.langchain.com/oss/python/langgraph/persistence)，查阅：2026-11-08。
- [SQLite 事务](https://www.sqlite.org/lang_transaction.html)。

下一章进入[图并行、归并与子图](./graph-parallel-subgraphs.md)，让两项检查同时运行，再按明确契约汇总。
