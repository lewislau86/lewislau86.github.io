---
title: "专题 2：外部操作的可靠性"
description: "用独立客户端与工单服务复现提交后的未知结果，验证操作身份、幂等、Outbox 和对账。"
pageClass: learn-agent-rust-course
prev: false
next: false
---

# 专题 2：外部操作的可靠性

[课程总览](./index.md) · [专题 1 提纲](./postgres-checkpoints.md) · [学习路径](./learning-path.md#p02) · [专题 3 提纲](./model-evaluation.md)

::: tip 本章学习目标
- 沿一次创建工单的过程，指出外部提交、结果接收和本地检查点之间的故障窗口。
- 让同一业务操作跨重试保留身份，验证同键同参数复用、同键不同参数拒绝。
- 运行进程退出实验，分别检查 Outbox、服务端业务行和本地检查点，决定重发、对账或停止。

**前置：** [错误分类与恢复](./error-recovery.md)、[持久化任务系统](./task-system.md)、[自主任务领取](./autonomous-workers.md)。[专题 1](./postgres-checkpoints.md)规划完整 PostgreSQL 会话检查点；本章提供独立 SQLite 实验，可先运行。

**实践方式：** 下载<a href="/learn-agent-rust/side-effect-reliability.zip" download>完整 side-effect-reliability.zip</a>，进入解压后的同名目录执行 `cargo run --locked`。固定 Rust 1.99.1，SQLite 随 `rusqlite` 编译，需要本机 C 编译工具链；无需 API Key 或数据库服务。
:::

工作区助手发现超时配置有问题，准备替用户创建一张“审查 Rust 超时处理”的工单。服务已经把工单写入数据库，但客户端还没拿到回执就退出了。重启后，本地只看见“这一步尚未完成”。

现在应该再创建一次吗？如果上次没提交，重试能补上工作；如果上次已经提交，重试可能多出第二张工单。仅看本地异常，无法分辨这两种情况。

本章围绕这张工单往前走：先制造重复，再为操作分配稳定身份，把发送意图保存下来，最后查询服务端结果，恢复本地记录。

<LearnAgentRustMap active="side-effect-reliability" />

::: info 本章实验状态
已验证独立 Rust 客户端与 provider 进程、两份真实 SQLite 数据库、事务提交前后直接退出、重启重放及对账。默认演示使用本机子进程 JSON 通信；模型、HTTP、真实第三方服务、完整 Agent 会话恢复和 PostgreSQL 集成尚未接入。

客户端是顺序实验控制器；服务端另验证四个进程并发提交同一幂等操作。逻辑 tick 与故障点由控制器注入，测试结果不代表物理断电耐久性或跨主机的交付保证。
:::

## 1. 先运行：一张工单，两个持久化世界

::: info 代码与输出只有一个来源
完整工程位于 `docs/public/learn-agent-rust/code/side-effect-reliability/`。`client.rs` 保存意图、发送与检查点；`provider.rs` 创建工单和查询结果；`main.rs` 提供 CLI 与默认恢复演示。下文代码直接引用这些文件，实验记录由同一工程运行生成。

[下载工程及全部实验记录](/learn-agent-rust/side-effect-reliability.zip) · <a href="/learn-agent-rust/code/side-effect-reliability/README.md" download>运行说明</a> · [GitHub 源码](https://github.com/lewislau86/lewislau86.github.io/tree/master/docs/public/learn-agent-rust/code/side-effect-reliability)
:::

```sh
cargo fetch --locked
cargo run --locked
cargo test --locked
```

默认程序自建临时目录和两份数据库，创建工单后让服务进程在提交完成的位置直接退出，再启动新的客户端进程恢复。先预测：恢复前，服务端工单数和本地检查点数是否一样？

<<< @/public/learn-agent-rust/outputs/p02-demo.txt

`before_recovery` 中 Outbox 为 `unknown`、检查点为零；`provider` 中有一张真实工单。恢复查回同一条结果后，`after_recovery` 的检查点才变成一。临时目录在子进程全部结束后删除。

![客户端先保存意图，服务端另行提交工单，再保存本地回执与检查点；两份数据库之间存在未知结果窗口。](/learn-agent-rust/figures/p02-commit-windows.svg)

从上往下读三个阶段：准备意图、执行外部操作、确认本地进度。客户端还会单独提交发送前的 unknown 标记和收到回执后的 acked 状态，后文逐个展开。图中的间隙正是“本地尚未确认、外部可能已完成”的位置。SQLite 的事务只覆盖各自数据库。

## 2. 先看反例：捕获异常后直接重试

验证脚本直接调用无幂等模式的 provider：第一次提交后退出，第二次再调用相同参数。

<<< @/public/learn-agent-rust/outputs/p02-naive-retry.txt

最后真的有两张工单。这个反例没有客户端意图和检查点，检查点数为零是刻意保留的对照。它说明自动重试之前，必须先知道服务如何识别“上次那一件事”。

[第十一章](./error-recovery.md)把结果不明与明确失败分开。本章把这个区别落到数据库：**异常是客户端的观察，工单是否提交要检查服务端证据。**

## 3. 给业务操作一个能跨重启保留的名字

<<< @/public/learn-agent-rust/code/side-effect-reliability/src/main.rs#identity

例子的身份是 `(tenant=course, operation_id=review-42)`。它在创建发送意图时确定，后续发送、查询和恢复都继续使用。一次模型响应的 tool call ID 用于消息关联；同一业务操作可能经历新的模型轮次、调用 ID 和网络请求，仍应沿用原操作身份。

| 标识 | 关联的对象 | 重试时怎样处理 |
| --- | --- | --- |
| tool call ID | 模型消息与工具结果 | 按模型协议配对 |
| 请求尝试 | 本次发送动作 | 计入累计次数 |
| operation ID | 用户确认的那一次业务意图 | 重放继续使用 |
| ticket ID | 服务实际创建的工单 | 根据回执或查询确认 |

`digest` 对固定结构的请求 JSON 做 SHA-256，覆盖租户、操作 ID 和标题。同一个 ID 换成另一个标题会冲突；标题相同但 ID 不同，表示两个独立意图。摘要检测内容错配，身份认证仍属于真实服务的授权层。

客户端和服务端都检查参数：同键同参数可以重复；同键不同参数必须显式冲突。实验还验证同一 ID 放到另一租户会生成另一张工单，键的作用域需要写进接口约定。

## 4. 服务端把“去重”和“创建”放在同一事务

<<< @/public/learn-agent-rust/code/side-effect-reliability/src/provider.rs#provider-transaction

在 `key` 模式下，服务先开启 `BEGIN IMMEDIATE`，查找尚未到期的键。找到相同摘要时直接返回原回执；摘要变化返回 `idempotency_conflict`；首次请求则在同一事务创建工单、保存回执与键。

这一步的关键在服务端。客户端先查一次“键不存在”，然后各自发送，仍可能遇到竞争。实验同时启动四个 provider 进程，事务串行化键检查与创建，最终四次调用得到同一回执、只有一条工单。

![稳定操作 ID 和相同参数在有效期内返回原回执，同键不同参数被拒绝，新 ID 表示新意图。](/learn-agent-rust/figures/p02-idempotency-scope.svg)

从左侧请求沿三条路线读：相同操作复用结果，改变参数触发冲突，改变操作身份则创建新结果。图中的数量来自实际服务数据库；缓存期限稍后单独讨论。

### 返回没收到，可以再发原来的操作吗？

<<< @/public/learn-agent-rust/outputs/p02-response-lost-replay.txt

`attempts=2` 表示客户端真的尝试了两次发送，`apply_commits=2` 表示服务两次 apply 事务都提交了日志，而 `tickets=1` 表示只有一张业务工单。三种计数刻意分开。

这种重放成立依赖服务契约：键作用域一致、参数未变、原键仍在保留期内、服务将键与业务操作原子保存。将一个字段命名为 `idempotency_key` 本身不会建立这些能力。

## 5. Outbox 保存“我需要发送”，重启后仍能找到

<<< @/public/learn-agent-rust/code/side-effect-reliability/src/client.rs#outbox-prepare

客户端在一个事务中同时插入 `actions` 和 `outbox`，内容包括冻结的请求、摘要、幂等模式、最晚允许发送时间和累计次数。重复 prepare 返回已有意图，不更换参数、不延长重试窗口。

可以在“两次 INSERT 之间”终止进程，再由另一个进程打开数据库：两条记录都没有。也可以在 COMMIT 之后终止：两条记录都还在。这个本地事务防止“业务说要创建工单，但发送意图丢了”。

::: details 手动观察提交后的未知结果

在空实验目录中，按顺序执行下载包里的命令：

```sh
cargo run --locked -- prepare client.sqlite '{"tenant":"course","operation_id":"review-42","title":"Review Rust timeout handling"}' key 0 none
cargo run --locked -- dispatch client.sqlite provider.sqlite course review-42 1 provider-after-commit
cargo run --locked -- inspect-client client.sqlite
cargo run --locked -- inspect-provider provider.sqlite
cargo run --locked -- recover client.sqlite provider.sqlite course review-42 2 none
```

第二条命令预期返回错误 `outcome_unknown`（退出码 10），因为 provider 子进程在提交后以 82 退出，没返回 JSON。后续 inspect 和 recover 命令用于检查并修复本地认知。这里的相对数据库路径会写入当前目录；默认无参数演示使用自建临时目录。

:::

### 发送前为什么先写 unknown？

<<< @/public/learn-agent-rust/code/side-effect-reliability/src/client.rs#dispatch

发送前先持久化 `unknown` 并增加 attempts。这样即使发送前刚好退出，重启也走保守恢复路径。它可能把“实际上还没发”的操作也标成未知，这是有意的：应用把不可分割的窗口放在一个可以统一处理的状态中。

![Outbox 从 pending 进入 unknown，收到合法回执后进入 acked，再与检查点一起完成；未知结果通过重放或对账恢复。](/learn-agent-rust/figures/p02-outbox-recovery.svg)

沿主线看 `pending → unknown → acked → completed`；再看 unknown 的恢复分支。Outbox 负责保留发送意图，服务幂等或对账负责解释外部结果。单独使用 Outbox 仍可能重复发送。

本例累计最多三次发送尝试，进程退出不会清零。一次发送前退出也计入次数；耗尽后保持 unknown，由调用方决定进一步处理。它没有后台调度器或多客户端租约，运行器按顺序派发；[第十七章](./autonomous-workers.md)讨论的所有权仍需在真实多 worker 集成时另接。

## 6. 回执到手后，还要把检查点保存完整

<<< @/public/learn-agent-rust/code/side-effect-reliability/src/client.rs#checkpoint

收到回执后，先核对请求身份、完整参数、摘要和合法工单 ID，再保存 `acked`。之后用一个本地事务保存检查点，并把业务状态和 Outbox 一起置为 completed。

在保存回执后退出，重启直接用本地回执补检查点，不再调用 provider。在检查点事务提交前退出，事务回滚，状态仍为 acked；提交后退出，三份本地记录都为完成。`normal` 再次恢复时，服务的 apply 计数仍为一。

本章检查点只是一份创建工单的回执。它用于说明外部结果和本地进度的边界，完整模型历史、图节点位置和 PostgreSQL 会话版本由[专题 1](./postgres-checkpoints.md)单独实现。

## 7. 不确定时先对账，查不到也可能要停

<<< @/public/learn-agent-rust/code/side-effect-reliability/src/provider.rs#reconciliation-query

查询使用同一个租户和 operation ID。本实验 provider 保留工单里的客户引用，因此幂等缓存被清理后仍能按业务记录找到结果。recover 接受一条完整、唯一且参数匹配的回执；多条结果则返回 `reconciliation_ambiguous`。

| 查询结果 | 客户端动作 |
| --- | --- |
| 唯一、完整且参数匹配 | 保存回执，补本地检查点 |
| 同一客户引用匹配多张工单 | 保持 unknown，交人工核对 |
| 返回不完整或查询失败 | 保持 unknown，等待后续核对 |
| 完整查询为空，服务支持有效期内幂等 | 可用原键重放 |
| 查询为空，原操作不支持幂等 | 保持 unknown，停止自动重发 |

最后一行值得先猜：测试明确在发送前终止，因此实验作者知道服务没收到，但恢复代码仍然不自动重发。恢复者只能看到持久化的 unknown；真实网络中还可能存在尚未完成的旧请求。一次空查询无法普遍证明“以后也不会出现原结果”。

`hidden` 与 `unavailable` 是注入的查询故障。真实接口可能没有 `complete` 标识，也可能只有最终一致的列表，需要以它的真实查询保证重新设计恢复策略。

### 幂等键有保留期

provider 在首次成功的 tick +100 后清理键；客户端从准备意图的 tick 起只允许 100 tick 内发送，重复 prepare 不刷新。边界 `now >= safe_until` 就停止发送。本实验 tick 是逻辑输入，没有秒的含义。

![服务端键过期后直接重放会创建第二张工单；客户端期限保护会停止发送，仍可通过业务引用查回原结果。](/learn-agent-rust/figures/p02-retention-boundary.svg)

先看反例：删除键再直接 apply，工单从一张变成两张。再看客户端保护：过期后停止重发，保留未知状态；对账路径仍可从工单表查回原回执。服务保留业务引用的能力与幂等键缓存是两份不同的契约。

## 8. 动手实验：把窗口逐个打开

完整验证命令在网站仓库运行；下载包读者先执行 `cargo test --locked` 与默认演示即可：

```sh
python3 scripts/verify-agent-effects.py --check
python3 scripts/generate-learn-agent-rust-figures.py --lesson P02
```

验证器执行 29 个场景、11 项 Rust 测试与 Clippy。每次 CLI 都是独立进程；脚本另用 Python SQLite 连接核对真实业务行、摘要、检查点和本地事务一致性。最终 zip 再解压编译，全部场景重新运行并比较结果。

### 全部场景的实际记录

<!-- p02-results:start -->

| 场景 | 服务工单 | 本地检查点 | apply 提交 / 对账查询 | 最终 Outbox 状态 |
| --- | --- | --- | --- | --- |
| `normal` | 1 | 1 | 1 / 0 | `completed` |
| `naive-retry` | 2 | 0 | 2 / 0 | 无意图 |
| `response-lost-reconcile` | 1 | 1 | 1 / 1 | `completed` |
| `response-lost-replay` | 1 | 1 | 2 / 0 | `completed` |
| `exit-before-send` | 1 | 1 | 1 / 1 | `completed` |
| `provider-rollback` | 1 | 1 | 1 / 1 | `completed` |
| `outbox-rollback` | 1 | 1 | 1 / 0 | `completed` |
| `prepare-committed` | 1 | 1 | 1 / 0 | `completed` |
| `response-received-local-lost` | 1 | 1 | 1 / 1 | `completed` |
| `ack-without-checkpoint` | 1 | 1 | 1 / 0 | `completed` |
| `checkpoint-rollback` | 1 | 1 | 1 / 0 | `completed` |
| `checkpoint-committed` | 1 | 1 | 1 / 0 | `completed` |
| `intent-conflict` | 1 | 1 | 1 / 0 | `completed` |
| `provider-conflict` | 1 | 0 | 2 / 0 | 无意图 |
| `new-operation-id` | 2 | 2 | 2 / 0 | `completed`, `completed` |
| `tenant-scope` | 2 | 2 | 2 / 0 | `completed`, `completed` |
| `concurrent-provider` | 1 | 0 | 4 / 0 | 无意图 |
| `retry-budget` | 0 | 0 | 0 / 0 | `unknown` |
| `expired-key-unsafe` | 2 | 0 | 2 / 0 | 无意图 |
| `expired-client-stop` | 1 | 0 | 1 / 0 | `unknown` |
| `expired-reconcile` | 1 | 1 | 1 / 1 | `completed` |
| `no-key-reconcile` | 1 | 1 | 1 / 1 | `completed` |
| `no-key-empty` | 0 | 0 | 0 / 1 | `unknown` |
| `ambiguous-reconcile` | 2 | 0 | 2 / 1 | `unknown` |
| `incomplete-query` | 1 | 0 | 1 / 1 | `unknown` |
| `query-unavailable` | 1 | 0 | 1 / 1 | `unknown` |
| `receipt-mismatch` | 1 | 1 | 1 / 1 | `completed` |
| `corrupt-intent` | 0 | 0 | 0 / 0 | `pending` |
| `clock-regression` | 1 | 1 | 1 / 0 | `completed` |

<!-- p02-results:end -->

`apply 提交` 是 provider 事务中已提交的日志数量，提交前退出的 apply 不计入；`对账查询` 只计服务端查询调用。表中的零检查点和 unknown 在拒绝或人工核对场景中是预期结果，表示程序没有编造成功。

实验退出点使用 `std::process::exit`，跳过 Rust 的正常析构；SQL 故障恢复在新进程中观察。这验证了进程终止窗口，不覆盖磁盘控制器、物理断电、网络分区或第三方 SLA。

::: warning 常见误区
- 使用新的 operation ID 重试同一意图，会绕过原键的去重；标题相同不能替代业务身份。
- 本地事务只保护本地业务意图与 Outbox。服务端操作需要自己的原子幂等契约，Outbox 仍可能多次投递。
- 回执里的工单 ID 和摘要需要与原请求核对；本例摘要不认证发送者，真实传输还需认证和授权。
- 幂等保留期之外不能沿用期内的保证。对账查不到结果时，要结合服务可见性和仍在途请求处理。
- 本实验没有实际网络、完整 Agent、跨 worker 调度或 PostgreSQL 集成；两份 SQLite 的验证不能代替这些系统的验收。
:::

## 本章结论

先把同一业务意图的身份和参数保存下来，再发送。服务把幂等键、业务结果和回执原子保存；客户端通过 Outbox 找回待处理意图，通过合法回执和检查点记录进度。结果不明时，按服务契约重放或对账，证据不足就保留 unknown。

这套实验让“是否再次调用”和“外部是否多做了一次”成为两个可以分别核对的问题。它的保证范围由身份作用域、幂等保留期、查询能力和本地提交边界共同决定。

## 检查理解

1. provider 已提交、客户端没有收到结果，本地为什么不能直接标失败？

   <details><summary>参考答案</summary>

   异常只说明客户端未确认。服务端可能已有工单；标成明确失败并重发非幂等请求会创建重复结果。应保存 unknown，再用原键重放或对账。

   </details>

2. tool call ID、operation ID 和 ticket ID 分别用于什么？

   <details><summary>参考答案</summary>

   tool call ID 配对模型调用和工具结果；operation ID 标识跨重试的业务意图；ticket ID 标识实际创建的工单。一次业务意图可经历多次模型或传输调用，但重放应保留其 operation ID。

   </details>

3. Outbox 已和业务记录一起提交，为什么仍可能出现两张工单？

   <details><summary>参考答案</summary>

   Outbox 的事务没有覆盖外部服务。服务提交后客户端可能没来得及确认，恢复后会再次投递。外部服务还需要原子幂等机制，或通过对账避免盲目重发。

   </details>

4. 幂等键过期后还能直接重发吗？

   <details><summary>参考答案</summary>

   本实验直接重发会创建第二张工单。客户端先停止发送，若服务保留客户引用，可以查询实际业务记录并核对唯一结果；缺乏可靠证据时保留 unknown。

   </details>

5. 无幂等服务查询为空，为什么恢复者仍停止自动重发？

   <details><summary>参考答案</summary>

   一次空查询可能看不到在途请求或尚未可见的结果。恢复者无法仅凭 unknown 和空查询证明原请求永远不会提交，需要服务的额外保证或人工核对。

   </details>

## 参考资料

- [AWS Builders' Library：Making retries safe with idempotent APIs](https://aws.amazon.com/builders-library/making-retries-safe-with-idempotent-APIs/)：客户请求身份、同意图重试与迟到请求。
- [Transactional Outbox 模式](https://microservices.io/patterns/data/transactional-outbox.html)：本地事务保存消息意图与重复投递问题。
- [Stripe 幂等请求文档](https://docs.stripe.com/api/idempotent_requests)：真实服务的键、参数和保留策略示例；具体接口以服务文档为准。
- [SQLite 原子提交](https://www.sqlite.org/atomiccommit.html)与[隔离性](https://www.sqlite.org/isolation.html)：本实验事务所依赖的数据库语义。
- <a href="/learn-agent-rust/code/side-effect-reliability/README.md" download>完整实验运行说明</a>：命令、退出码、期限、计数与未验证范围。

下一篇规划为[专题 3：模型协议与质量评估](./model-evaluation.md)，分别验证协议完成与业务任务完成。
