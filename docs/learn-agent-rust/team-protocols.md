---
title: "第 28 章：团队协作协议"
description: "把计划审批、进度汇报与关闭握手变成可校验的状态迁移，验证消息身份、原计划执行、期限和队友回收。"
pageClass: learn-agent-rust-course
prev:
  text: 第 27 章 · Agent 团队
  link: /learn-agent-rust/agent-teams
next:
  text: 第 29 章 · 自主任务领取
  link: /learn-agent-rust/autonomous-workers
---

# 第 28 章：团队协作协议

[课程总览](./index.md) · [上一章](./agent-teams.md) · [学习路径](./learning-path.md#r16) · [下一章](./autonomous-workers.md)

::: tip 本章学习目标
- 沿一份审查计划，解释请求 ID、双方身份、消息类型和状态如何共同决定回复是否有效。
- 将批准绑定到具体计划，在执行入口检查内容、期限与工具权限，并验证退回、重提和重放。
- 区分关闭请求的批准与队友实际退出，处理拒绝、超时、panic 和取消后的句柄回收。

**前置：** [第 27 章：Agent 团队](./agent-teams.md)的有界邮箱与队友生命周期，以及[第 3 章：权限与审批](./permissions.md)的执行门控。

**实践方式：** 下载<a href="/learn-agent-rust/team-protocols.zip" download>完整 team-protocols.zip</a>，进入解压后的 `team-protocols` 目录，运行 `cargo run --locked`。固定 Rust 1.99.1、Tokio 1.54.1，首次获取依赖需要网络。本章是独立协议内核，无需模型密钥、数据库或两库依赖；框架安装仍见[环境准备](./setup.md#install-frameworks)。
:::

上一章的 `core` 和 `config` 已经能通过邮箱交换审查线索。这次，`core` 想把审查结论保存为 `review.txt`，Lead 要先检查计划，再决定是否允许。写完后，Lead 还要请两位队友退出。

只传一句“同意”会留下几个问题：同意的是哪次请求？是谁回复的？计划后来改了内容，批准还有效吗？队友说“可以关闭”，它的异步任务是否已经结束？本章沿这一次文件写入，把这些问题变成程序可以检查的协议。

<LearnAgentRustMap active="team-protocols" />

<!-- experiment-library:start -->

全书实验可从[统一代码库](./experiments.md#team-protocols)下载；解压后进入 `chapters/team-protocols/`，或在代码库根目录运行 `python3 run.py run R16`。

<!-- experiment-library:end -->

## 1. 先跑完一次提交、批准、写入与退出

解压学习包后，在包含 `Cargo.toml` 的目录执行：

```sh
cargo fetch --locked
cargo run --locked
cargo test --locked
cargo clippy --locked --all-targets -- -D warnings
```

依赖下载完整后，可加 `--offline` 重跑。默认 `normal` 场景的真实输出如下：

<<< @/public/learn-agent-rust/outputs/r16-normal.txt{txt}

先看 `plan-1`：请求从 `Core` 发给 `Lead`，最终是 `Completed`；实际产物的内容与 SHA-256 也打印出来。再看两个 `stop-*` 请求：它们的 `Approved` 表示队友接受关闭，而两行 `join ...=graceful` 才记录任务已经退出。最后检查 `joined=2`、`active=0` 和 `workspace_removed=true`。

程序创建自己的临时工作区，真实创建并读回 `review.txt`，等所有队友回收后删除目录。正文里的审查建议是控制器给定的输入，本章没有重新运行上一章的模型审查。

| 文件 | 负责的边界 |
| --- | --- |
| `src/protocol.rs` | 消息格式、请求表、回复匹配、期限与执行门控。 |
| `src/runtime.rs` | 成员身份、邮箱投递、唯一上行消费者、取消与句柄回收。 |
| `src/main.rs` | 固定场景、故障输入、真实文件核对与输出。 |
| `src/tests.rs` | 15 项行为测试，包括状态不变、实际内容变化和资源清理。 |

## 2. 一句“同意”，必须能找到它对应的请求

本例有五种消息。先把它们与各自的方向对应起来：

| 消息 | 方向 | 程序如何解释 |
| --- | --- | --- |
| `PlanRequest` | 队友 → Lead | 保存待审计划，建立 `Pending` 请求。 |
| `PlanResponse` | Lead → 原申请队友 | 用 `Approve` 或 `Reject` 决定这次计划。 |
| `Progress` | 原申请队友 → Lead | 记录进度文本，保留原审批状态。 |
| `ShutdownRequest` | Lead → 队友 | 建立关闭请求，冻结该成员的新计划。 |
| `ShutdownResponse` | 原接收队友 → Lead | 接受或拒绝这次关闭。 |

![请求表保存原申请者与预期回复者，回复要匹配 ID、类型、双方身份和待决状态才能改变记录。](/learn-agent-rust/figures/r16-request-correlation.svg)

读图时先看中间的请求表。`plan-1` 建立时就保存 `Core → Lead`，因此回复必须是 `Lead → Core`。即使 `config` 也知道这个 ID，它仍然不能替 Lead 批准。

这里有两层校验。第一层由 Serde 把 JSON 解码成有限的消息变体：未知字段、未知消息类型、把 `decision` 写成布尔值都会被拒绝。第二层由请求表检查这条结构正确的消息是否有权改变当前记录。

<details><summary>展开完整消息与请求记录定义</summary>

<<< @/public/learn-agent-rust/code/team-protocols/src/protocol.rs#contracts

</details>

发送者身份来自可信应用创建的 `Endpoint`。JSON 正文没有 `from` 字段，写上 `"from":"lead"` 会因未知字段被拒绝。这个边界用于防止消息正文替自己选择身份；外部进程的身份认证仍需另行实现。

请求表匹配回复的核心代码是：

<<< @/public/learn-agent-rust/code/team-protocols/src/protocol.rs#match-response

检查顺序是找到 ID、匹配协议种类、核对双方身份、确认 `Pending`，最后才写入决定和反馈。已经拒绝的请求，再收到批准回复也无法翻转状态。

运行 `cargo run --locked -- wrong-sender`，可以看到“知道 ID”与“有权回复”的区别：

<<< @/public/learn-agent-rust/outputs/r16-wrong-sender.txt{txt}

`wrong_identity` 之后，清理前 `plan-1` 仍然为 `Pending`。清理阶段才将尚未完成的计划改成 `Cancelled`。输出刻意分开这两个时点，避免把清理行为误认成非法回复的效果。

### 汇报文本只进入日志

试试 `cargo run --locked -- progress-injection`：队友发送一条声称自己是 Lead、要求立即执行的进度文本。程序仍把它当 `Progress`，记录后保持 `Pending`，执行被 `not_approved` 拒绝。批准只能来自通过校验的 `PlanResponse`。

这验证了本地协议的控制边界。若以后把进度放进真实模型上下文，还要为模型侧的资料来源与工具权限保留独立约束。

## 3. 批准绑定哪份计划？从退回后重提看起

`core` 提交的 `Plan` 包含 `revision`、`path` 与 `content`。程序保存这份快照，并对 Serde 序列化得到的 JSON 字节计算 SHA-256。执行时重新计算摘要，确认仍然是 Lead 审过的同一份内容。

先预测：Lead 拒绝 `plan-1` 后，`core` 把 `revision` 改为 2，再使用原来的 ID，应该覆盖记录吗？本例保留旧请求及其反馈，修改后的计划必须用新的 `plan-2` 提交。

![退回的 plan-1 保持 Rejected，修订计划以 plan-2 重新申请，批准后通过内容、期限与权限检查才能写入一次。](/learn-agent-rust/figures/r16-plan-gate.svg)

沿上半部分读：退回是一条有结果的记录；修订产生新请求。下半部分是执行入口，它同时检查申请者、批准状态、期限、计划摘要和工具白名单。图中的写入计数来自 `resubmit` 的真实运行。

```sh
cargo run --locked -- resubmit
```

<<< @/public/learn-agent-rust/outputs/r16-resubmit.txt{txt}

第一次执行返回 `not_approved`，检查确认文件尚不存在。随后 `plan-2` 完成一次真实写入，产物变成修订后的建议，`plan-1` 仍然保留为 `Rejected`。

执行门控位于实际文件操作的入口：

<<< @/public/learn-agent-rust/code/team-protocols/src/protocol.rs#write-gate

这里批准只满足一项条件。工具另有自己的权限：仅 `core` 能创建路径恰好为 `review.txt` 的文件。即使 Lead 批准了 `../escape.txt`，执行仍返回 `permission_denied`。`create_new` 保护现有文件，成功后状态成为 `Completed`，相同批准无法再消费一次。

可以依次运行 `changed-plan`、`forbidden-path`、`replay-write` 和 `write-failed`。它们分别检查审后修改、越权路径、重复执行与真实 I/O 失败。I/O 失败会留下 `Failed`，本例不自动重试；如果写入中途失败，也没有承诺把已经写出的字节回滚。

### 批准还需要有效期

默认请求在逻辑 tick 0 创建，`ttl=10`，因此 `deadline=10`。控制器将时间推进到 10 时，待决请求和未执行的计划批准都过期：

<<< @/public/learn-agent-rust/code/team-protocols/src/protocol.rs#deadlines

这里选择 `now >= deadline` 作为到期边界，并拒绝时间回退。控制器负责在处理消息与执行前更新时钟；tick 是测试输入，没有秒的含义。`late-response` 检查迟到回复，`expired-grant` 检查批准后拖到期限之外的执行，两者都无法恢复旧权限。

## 4. 邮箱满了，请求表也要跟着回滚

请求表与邮箱是两份状态。如果先登记“正在关闭”，再发现队友邮箱满了，就会出现：队友没收到关闭请求，系统却已冻结它、撤销了批准。

本例将修改先应用在候选副本，确认 `try_send` 成功后才提交：

<<< @/public/learn-agent-rust/code/team-protocols/src/runtime.rs#delivery-commit

![容量为 2 的成员邮箱满时，关闭请求返回 mailbox_full，候选表被丢弃；释放空间后原 ID 可以重新提交。](/learn-agent-rust/figures/r16-delivery-commit.svg)

从左向右看失败路径：验证通过只产生候选状态，满邮箱会丢弃这份修改。成功路径才同时保留入队消息和新的请求表。Lead 是控制器本身，发给 Lead 的上行消息由唯一消费者 `next()` 验证并登记；这里没有额外建立 Lead 收件箱。

运行 `cargo run --locked -- mailbox-full`：

<<< @/public/learn-agent-rust/outputs/r16-mailbox-full.txt{txt}

实验先暂停 `core`，用批准消息与执行命令占满它的两个槽位，再尝试发送关闭请求。`failed_send_rolled_back=true` 核对：关闭 ID 没有被占住，成员也没有进入 closing。释放队友后，计划仍能写入一次，原来的关闭 ID 可以重新发送并完成握手。

这一提交边界依赖本例的进程内锁、`current_thread` runtime，以及验证、入队、提交之间没有 `await`。它覆盖的是本地执行顺序；跨进程恢复需要持久化协议，本章的内存快照没有提供这种能力。

## 5. 关闭先冻结工作，再分别确认回复与退出

Lead 成功投递 `ShutdownRequest` 时，立即把该成员加入 `closing`，取消其仍待决或已批准但未执行的计划。这样关闭期间不会继续积累新的批准。

队友可以拒绝关闭。`shutdown-rejected` 故意回复“审查尚未完成”：关闭记录保留 `Rejected`，成员恢复接收新计划，但旧批准仍为 `Cancelled`。后续工作要建立新请求，再获批准。

```sh
cargo run --locked -- shutdown-rejected
```

<<< @/public/learn-agent-rust/outputs/r16-shutdown-rejected.txt{txt}

这次 `plan-2` 可以写入；实验最终仍会发送独立的管理取消来回收所有任务，因此退出结果为 `cancelled`。业务上的“拒绝关闭”与实验结束时的资源清理，记录在不同位置。

![关闭请求的决定与 JoinHandle 回收分别记录，正常退出、无回复、panic、批准但仍存活和忽略取消产生不同的结果。](/learn-agent-rust/figures/r16-shutdown-join.svg)

图中的每一行来自一个实际场景。先看协议列，再看回收列：`ack-without-exit` 已经批准关闭，但任务仍在等邮箱；`shutdown-panic` 没有回复，任务却已因 panic 结束。两个方向都说明，只看回复不足以判断资源状态。

### 没有回复：等待超时与协议过期分别核对

```sh
cargo run --locked -- shutdown-timeout
```

<<< @/public/learn-agent-rust/outputs/r16-shutdown-timeout.txt{txt}

程序先真实等待上行事件 20ms，得到 `real_receive_timeout=true`，再把协议时间推进到 tick 10，使请求成为 `Expired`。人为补发的迟到批准被拒绝，随后通过独立 `watch` 通道取消队友并等待句柄。这分别验证异步等待与状态机期限；没有把 20ms 当作 10 tick。

### 回复批准后，也要等待任务句柄

`ack-without-exit` 刻意让队友发出批准后继续存活：

<<< @/public/learn-agent-rust/outputs/r16-ack-without-exit.txt{txt}

`approved_but_actor_alive=true` 是清理前的观察。最后的 `join Core=cancelled` 则来自后续取消与等待。关闭请求保持 `Approved`，作为原回复结果留存。

统一回收代码如下：

<<< @/public/learn-agent-rust/code/team-protocols/src/runtime.rs#join-cleanup

先对所有成员发送独立取消，再逐一等待句柄。每个句柄最多等待 100ms；故意忽略取消的 `abort-fallback` 会触发 `abort`，随后继续 `await`。`shutdown-panic` 从 `JoinError` 识别 panic，并把尚待决的关闭请求记为 `Failed`。所有句柄处理完毕后才删除工作区。

这里的取消适用于会让出执行权的异步任务。本例文件写入是很小的同步操作，取消不会在 `write_all` 中间抢占它；长期阻塞或外部进程需要独立的生命周期方案。

<details><summary>展开队友接收消息与生成关闭回复的实现</summary>

<<< @/public/learn-agent-rust/code/team-protocols/src/runtime.rs#actor-dispatch

</details>

## 6. 把正常路径与破坏路径一起复验

学习包包含下面 28 个场景。表格由验证器根据运行报告生成；`errors` 是场景故意触发的协议拒绝，出现预期拒绝且全部独立检查通过，命令仍以成功退出。

<!-- r16-results:start -->

| 场景 | 实际写入 | 协议拒绝 / 实验检查 | core 退出结果 |
| --- | --- | --- | --- |
| `normal` | 1 | 通过独立检查 | `graceful` |
| `unapproved` | 0 | `not_approved` | `cancelled` |
| `rejected` | 0 | `not_approved` | `cancelled` |
| `resubmit` | 1 | `not_approved` | `cancelled` |
| `wrong-sender` | 0 | `wrong_identity` | `cancelled` |
| `wrong-recipient` | 0 | `wrong_identity` | `cancelled` |
| `wrong-kind` | 0 | `wrong_kind` | `cancelled` |
| `unknown-request` | 0 | `unknown_request` | `cancelled` |
| `duplicate-request` | 0 | `duplicate_request` | `cancelled` |
| `duplicate-response` | 0 | `request_not_pending` | `cancelled` |
| `late-response` | 0 | `request_not_pending` | `cancelled` |
| `expired-grant` | 0 | `not_approved` | `cancelled` |
| `changed-plan` | 0 | `plan_changed` | `cancelled` |
| `replay-write` | 1 | `not_approved` | `cancelled` |
| `forbidden-path` | 0 | `permission_denied` | `cancelled` |
| `progress-injection` | 0 | `not_approved` | `cancelled` |
| `cancel-request` | 0 | `request_not_pending` | `cancelled` |
| `shutdown-rejected` | 1 | `not_approved` | `cancelled` |
| `shutdown-timeout` | 0 | `request_not_pending` | `cancelled` |
| `shutdown-panic` | 0 | 通过独立检查 | `panic` |
| `ack-without-exit` | 0 | 通过独立检查 | `cancelled` |
| `abort-fallback` | 0 | 通过独立检查 | `aborted` |
| `shutdown-freeze` | 0 | `member_closing` | `graceful` |
| `mailbox-full` | 1 | `mailbox_full` | `graceful` |
| `schema-errors` | 0 | `invalid_message`、`invalid_message`、`invalid_message`、`message_size` | `cancelled` |
| `request-limit` | 0 | `request_limit` | `cancelled` |
| `clock-regression` | 0 | `clock_regression` | `cancelled` |
| `write-failed` | 0 | `write_failed` | `cancelled` |

<!-- r16-results:end -->

每个场景都检查两个句柄已经等待、请求数不超过 16、没有逃逸文件、临时目录已经删除，并核对产物内容及摘要。测试还用两份不同内容调用真实写入，验证批准确实影响落盘内容，而非只改变计数器。

在网站源码根目录可执行维护命令：

```sh
python3 scripts/verify-agent-protocols.py --check
python3 scripts/generate-learn-agent-rust-figures.py --lesson R16
```

验证器运行 15 项 Rust 测试与 Clippy，核对输出和源码摘要，再把最终下载包解压到另一临时目录，离线编译并重跑所有场景。`--check` 只比较现有产物；去掉它才更新输出、证据、下载包与上表。

<!-- transfer-thinking:start -->

## 迁移思考：消息的含义来自状态

同一个 approve 在错误请求或旧计划上到达，会有什么后果？先给出你的判断，再展开下面的推演。

<details><summary>推演与应用</summary>

同时核对请求身份、双方身份、计划修订与允许状态，再检查动作是否只执行一次。

分布式消息、审批和 UI 回调都需要关联身份；“收到某词”不是有效的状态迁移。

</details>

这是一道迁移练习，推演不代表新增实验已通过。对照[全书审查中的证据层次](./course-review.md#evidence-layers)，说明你的判断还需要哪一级证据。

<!-- transfer-thinking:end -->

## 本章结论：把协作约定放进执行边界

本章保留上一章的成员与有界邮箱，把协作推进为带状态的请求。请求表固定双方身份与计划快照，类型化回复决定审批结果，执行入口消费有效批准，关闭流程单独等待每个队友退出。

当前交付是单进程的独立协议内核。消息与决定由控制器脚本提供，真实执行 Tokio 通信、文件操作与任务回收；模型循环、graph-flow 节点接线、持久化消息和外部身份认证分别留在对应集成实验中验收。

::: warning 常见误区
- 把进度文字当批准。只有匹配身份、种类、ID 与待决状态的回复能改变审批。
- 批准后任意改计划或扩大工具权限。摘要绑定修订、路径与内容，工具白名单仍独立检查。
- 在满邮箱时提前登记请求。本例只在入队成功后提交候选记录，失败不占 ID。
- 收到关闭批准就删除工作区。任务可能仍存活，必须等待句柄；abort 后也要等待。
- 将逻辑期限当自动计时。控制器必须推进时钟；20ms 接收超时另有单独检查。
- 把摘要当签名、把内存去重当长期可靠消息。记录含终态最多 16 条，重启即消失；事件日志也只服务于有限实验。同步写入失败没有通用回滚，长期运行需另定清理与恢复策略。
:::

## 检查理解

1. `config` 知道 `plan-1`，为什么仍不能替 Lead 回复批准？

   <details><summary>参考答案</summary>

   请求建立时保存了 requester=Core、responder=Lead。回复必须来自绑定 Lead 的 Endpoint，接收者还必须为 Core。ID 只负责关联请求，不授予回复权限。

   </details>

2. `plan-1` 被退回后，为什么修订版需要使用 `plan-2`？

   <details><summary>参考答案</summary>

   原请求保留它的计划快照、反馈与 Rejected 结果。重复 ID 被拒绝，旧请求的终态无法被后来回复翻转。新 ID 让新一轮审批有独立记录。

   </details>

3. Lead 已批准写 `../escape.txt`，执行端为什么仍拒绝？

   <details><summary>参考答案</summary>

   协议批准与工具权限分别检查。本例工具只允许 Core 创建路径恰好为 review.txt 的文件，越权路径即使摘要正确、批准有效也返回 permission_denied。

   </details>

4. 邮箱满时，为什么不能留下 closing=true，再等下一次投递？

   <details><summary>参考答案</summary>

   接收方尚未得到请求，但登记 closing 会提前冻结工作并撤销批准。候选副本只有在 try_send 成功后才提交，失败时保留原状态，稍后可以用同一 ID 重投。

   </details>

5. 关闭请求为 Approved、队友仍存活时，最后凭什么确认可以删除工作区？

   <details><summary>参考答案</summary>

   Approved 只证明收到有效的同意回复。管理方还要发送取消并等待所有 JoinHandle；超时后 abort 的句柄也继续 await。全部任务处理完毕，才删除临时目录。

   </details>

## 参考资料

- [参考课程：s16 Team Protocols](https://learn.shareai.run/zh/s16/)，对照计划批准与关闭握手的教学思路。
- [Serde：容器属性](https://serde.rs/container-attrs.html)，对照 `tag`、`rename_all` 与 `deny_unknown_fields`。
- [Tokio 1.54.1：try_send](https://docs.rs/tokio/1.54.1/tokio/sync/mpsc/struct.Sender.html#method.try_send)、[watch](https://docs.rs/tokio/1.54.1/tokio/sync/watch/index.html)，对照背压与独立取消通道。
- [Tokio 1.54.1：JoinHandle](https://docs.rs/tokio/1.54.1/tokio/task/struct.JoinHandle.html)、[timeout](https://docs.rs/tokio/1.54.1/tokio/time/fn.timeout.html)，对照任务等待、abort 与超时语义。
- [Rust OpenOptions::create_new](https://doc.rust-lang.org/std/fs/struct.OpenOptions.html#method.create_new)，对照已有路径的保护。

## 保留的参考原图

以下原图保留参考课程的 Python/Claude 教学语境，接口、编号和统计沿用上游。本章 Rust 实验使用自己的请求表、有界通道与执行门控，运行数据见前文自制图。

![参考课程使用类型化消息关联计划审批、进度与关闭请求，区分请求和回复。](/learn-agent-rust/figures/upstream/r16-team-protocols-overview.svg)

图源：[参考章节](https://learn.shareai.run/zh/s16/) · [原图](https://learn.shareai.run/course-assets/s16_team_protocols/team-protocols-overview.svg)。看清每种请求对应哪类回复，再对照 Rust 实验的身份与状态检查。来源版本和许可见[课程架构中的参考资料说明](./architecture.md#reference-assets)。

下一章：[自主任务领取](./autonomous-workers.md)。在明确成员协议之后，继续处理多个执行者怎样竞争领取同一份工作，以及执行权如何失效。
