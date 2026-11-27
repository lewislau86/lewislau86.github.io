---
title: "专题 2：外部操作的可靠性"
description: "用独立客户端与工单服务复现提交后的未知结果，验证操作身份、幂等、Outbox 和对账。"
pageClass: learn-agent-rust-course
prev:
  text: 专题 1 · PostgreSQL 检查点
  link: /learn-agent-rust/postgres-checkpoints
next:
  text: 专题 3 · 模型协议与质量评估
  link: /learn-agent-rust/model-evaluation
---

# 专题 2：外部操作的可靠性

[课程总览](./index.md) · [上一专题：PostgreSQL 检查点](./postgres-checkpoints.md) · [学习路径](./learning-path.md#p02) · [下一专题：模型协议与质量评估](./model-evaluation.md)

::: tip 本章学习目标
- 沿一次创建工单的过程，指出外部提交、结果接收和本地检查点之间的故障窗口。
- 让同一业务操作跨重试保留身份，验证同键同参数复用、同键不同参数拒绝。
- 运行进程退出实验，分别检查 Outbox、服务端业务行和本地检查点，决定重发、对账或停止。
- 把创建工单放进 ADK-Rust 3.0 的 Runner，分清框架动作账本管住的窗口和仍要业务身份补上的窗口。

**前置：** [错误分类与恢复](./error-recovery.md)、[持久化任务系统](./task-system.md)、[自主任务领取](./autonomous-workers.md)。[专题 1](./postgres-checkpoints.md)使用 PostgreSQL 保存会话检查点；本章提供独立 SQLite 实验，可先运行。

**实践方式：** 下载<a href="/learn-agent-rust/side-effect-reliability.zip" download>完整 side-effect-reliability.zip</a>，进入解压后的同名目录执行 `cargo run --locked`。固定 Rust 1.99.1，SQLite 随 `rusqlite` 编译，需要本机 C 编译工具链；无需 API Key 或数据库服务。第 9 节的 ADK-Rust 工程在同一目录的 `adk/` 子目录，运行前先取一次 ADK-Rust 源码（见第 9 节）。
:::

工作区助手发现超时配置有问题，准备替用户创建一张“审查 Rust 超时处理”的工单。服务已经把工单写入数据库，但客户端还没拿到回执就退出了。重启后，本地只看见“这一步尚未完成”。

现在应该再创建一次吗？如果上次没提交，重试能补上工作；如果上次已经提交，重试可能多出第二张工单。仅看本地异常，无法分辨这两种情况。

本章围绕这张工单往前走：先制造重复，再为操作分配稳定身份，把发送意图保存下来，最后查询服务端结果，恢复本地记录。

<LearnAgentRustMap active="side-effect-reliability" />

<!-- experiment-library:start -->

全书实验可从[统一代码库](./experiments.md#side-effect-reliability)下载；解压后进入 `chapters/side-effect-reliability/`，或在代码库根目录运行 `python3 run.py run P02`。

<!-- experiment-library:end -->

::: info 本章实验状态
已验证独立 Rust 客户端与 provider 进程、两份真实 SQLite 数据库、事务提交前后直接退出、重启重放及对账。默认演示使用本机子进程 JSON 通信；模型、HTTP、真实第三方服务、完整 Agent 会话恢复和 PostgreSQL 集成尚未接入。

客户端是顺序实验控制器；服务端另验证四个进程并发提交同一幂等操作。逻辑 tick 与故障点由控制器注入，测试结果不代表物理断电耐久性或跨主机的交付保证。

第 9 节另有 ADK-Rust 3.0 工程：脚本模型、SQLite 会话与动作账本、工具内和工具后的真实进程退出、6 个场景（含一个正常基线）；它验证框架层的恢复语义，不代替第 1–8 节的业务协议实验。
:::

::: info 本章已迁移到 ADK-Rust 3.0
第 1–8 节的业务协议实验本来就只依赖标准库与 rusqlite，迁移时原样保留；第 9 节新增 ADK-Rust 3.0（发布候选版，固定提交）的动作账本实验。全书正在逐章迁移，旧版本章可从 git 标签 `learn-agent-rust-v1` 取得。
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

## 9. 放进 ADK-Rust：动作账本管同一次调用，业务身份管同一件事

前八节的客户端是我们自己写的控制器。换成 Agent 以后，创建工单是模型提出的一次工具调用，由 ADK-Rust 的 `Runner` 执行。3.0 为这类调用准备了一套机制：没有声明为只读或幂等的工具按“非幂等”对待，不自动重试；配置了动作账本（`ActionLedger`）时，非幂等调用执行前记下“开始”，执行后记下结果，同一幂等键最多执行一次；进程意外退出、重新启动后，应用调用 `Runner::recover_unanswered_calls`，由它用账本回答那些“发出了调用、却没有结果”的调用，而且不再执行工具。注意恢复不会自动发生：普通的 `Runner::run` 不调用它，要由应用（或框架的持久化 worker）在重启后先调用。

问题是：账本能替我们管住前面哪些窗口？

### 9.1 实验怎样搭

工程在本章目录的 `adk/` 子目录。每次运行程序是一个独立进程，状态都在一个临时目录里：`agent.sqlite` 同时存会话事件（`SqliteSessionService`）和动作账本（`SqliteActionLedger`），`provider.jsonl` 扮演外部工单服务，每行一张工单，按操作身份去重；`provider-attempts.log` 记下服务每次被调用，用来区分“调用了几次”和“建了几张工单”。这个服务替身做了简化：单进程顺序访问，“先查再追加”不是原子操作，同一身份带不同内容也不报冲突。真实服务要像第 4 节那样在一个事务里完成去重和创建，并拒绝同键不同参数。

<<< @/public/learn-agent-rust/code/side-effect-reliability/adk/src/main.rs#provider

工具本身没有声明 `ToolEffect`，所以框架按非幂等对待。操作身份有两种取法：框架给的幂等键（`ctx.idempotency_key()`），或者由“应用 / 用户 / 会话 + 工单标题”算出的业务身份。后者是演示用的简化：它把“同一会话里为同一标题建工单”当成同一件事，同一会话里两张同名工单会被合并，换个说法的标题又不会去重，和第 3 节“标题相同不能替代业务身份”的提醒正好相反。可靠的做法仍是第 3、5 节那样，在创建意图时生成操作 ID 并和意图一起保存（例如写进会话状态），工具读取它。进程退出点有两个：工具里外部工单写入之后（`--crash in-tool`），以及工具返回之后、结果写进会话之前（在 `after_tool_callback` 里退出，`--crash after-tool`）。

<<< @/public/learn-agent-rust/code/side-effect-reliability/adk/src/main.rs#tool

Runner 的组装：会话和账本放在同一个 SQLite 文件；对照组用只存在内存里的账本。

<<< @/public/learn-agent-rust/code/side-effect-reliability/adk/src/main.rs#runner

### 9.2 六个场景

| 场景 | 依次运行的进程 | 会话里最后一条工具结果 | 服务被调用 | 外部工单 |
| --- | --- | --- | --- | --- |
| `normal` | `first` | `ok` | 1 | 1 |
| `crash-in-tool` | `first --crash in-tool`（退出码 9）→ `recover` | `outcome_unknown` | 1 | 1 |
| `crash-after-tool` | `first --crash after-tool`（退出码 9）→ `recover` | `already_succeeded` | 1 | 1 |
| `retry-call-key` | 同 `crash-in-tool` → `retry` | `ok`，新工单 `T-2` | 2 | **2** |
| `retry-business-key` | 同上，但两次都用业务身份 | `ok`，`deduplicated: true`，仍是 `T-1` | 2 | 1 |
| `memory-ledger` | `first --crash after-tool --ledger memory`（退出码 9）→ `recover --ledger memory` | `outcome_unknown` | 1 | 1 |

完整轨迹见[实验输出](/learn-agent-rust/outputs/p02adk-summary.txt)。轨迹里的 `status=` 是结果注解里的状态，`already_succeeded` 在注解里记作 `succeeded`。“服务被调用”在 `recover` 前后不变，说明恢复确实没有再执行工具。读法：

- **工具里退出：** 外部工单已经写入，账本只有“开始”没有“结果”。恢复时框架不知道动作是否生效，回答 `outcome_unknown`，附带说明“可能已经生效，再调用前先核对结果”，并且没有再执行工具，外部仍是 1 张。这正是第 1 节“服务已写入、客户端没拿到回执”的窗口。框架的处理相当于第 7 节表格最后一行的“保持 unknown、停止自动重发”；查询服务端核对结果仍要应用自己做。框架也没有提供“用原来的键安全重发”的路径，即使外部服务像第 4 节那样支持同键重放。
- **工具后退出：** 账本已经记下结果，只是会话里还没有。恢复时框架回答 `already_succeeded`，附带结果的哈希摘要，同样不执行工具。这只补上了第 6 节“回执到手、检查点没保存”窗口的一半：账本只存哈希，不存结果本身，恢复后的答案里没有工单号 `T-1`。要拿回工单号，仍需第 7 节的对账查询。
- **内存账本：** 同样在工具后退出，但账本随进程消失，恢复时只能回答 `outcome_unknown`。账本要和会话一样持久，才能分辨这两个窗口。

### 9.3 账本管不到的地方：新的一次调用

`retry-call-key` 是关键。恢复只是补上答案；之后用户再次发出同样的请求，脚本模型在新的一轮运行里再次请求创建同一张工单（真实模型看到 `outcome_unknown` 后也可能这样做）。框架的幂等键由“应用 / 用户 / 会话 / 本次运行 / 调用 ID”组成。两轮里的调用 ID 都是 `scripted_tc_0_0`，变的只是本次运行的 ID，但这已经足够生成新键：账本把它当作一次全新的调用，外部服务也看到一个新的操作身份，于是出现第二张工单。

ADK-Rust 的文档把这一点列为已知限制。它和第 3 节的结论完全一致：**去重依赖的身份必须跨重试稳定**。`retry-business-key` 让工具用业务身份（同一会话里“为这个标题创建工单”）作为操作身份，外部服务按它去重，第二次请求返回原来的 `T-1`。业务身份怎样定义、外部服务怎样原子去重、身份冲突时怎样拒绝，仍是第 3–7 节讲的应用合同。

### 9.4 框架替你做了什么、没做什么

| 框架做了 | 仍归应用 |
| --- | --- |
| 未声明副作用的工具按非幂等对待，不自动重试。 | 如实声明 `ToolEffect`；只读或幂等的工具才值得重试。 |
| 配置了账本时，非幂等调用前后记下开始与结果，同一幂等键最多执行一次；账本可以放在 SQLite、PostgreSQL 等持久存储。 | 选持久账本，并让所有进程读同一份。 |
| `recover_unanswered_calls` 用账本回答没有结果的调用：`already_succeeded`、`already_failed` 或 `outcome_unknown`，不再执行工具。 | 重启后先调用它（或使用框架的持久化 worker）；看到 `outcome_unknown` 先核对外部结果（第 7 节的对账）；需要工单号时自己查回。 |
| 每次调用有一个幂等键（`ctx.idempotency_key()`）。 | 跨运行、跨模型重试保持稳定的业务身份；外部服务按它原子去重（第 3–4 节）。 |
| — | Outbox、回执核对、幂等保留期与期满后的处理（第 5–7 节）。 |

在 `adk/` 目录里运行这个实验：

```sh
cd side-effect-reliability
python3 fetch-adk-rust.py ../adk-rust    # 一次即可；需要 git 与 GitHub 访问，不行时加 --method cdn
cd adk
cargo test --locked
rm -rf /tmp/p02-demo                                         # 每次从空目录开始，否则会沿用上次的会话和工单
cargo run --locked -- /tmp/p02-demo first --crash in-tool    # 预期退出码 9，cargo 会报 process didn't exit successfully
cargo run --locked -- /tmp/p02-demo recover
cargo run --locked -- /tmp/p02-demo inspect
```

`.cargo/config.toml` 把 ADK 依赖指向章节目录旁边的 `adk-rust/`，cargo 只读取当前目录及上级目录里的这个文件，所以命令要在 `adk/` 里运行。网站维护者运行 `python3 scripts/verify-agent-effects-adk.py`（专题 2 的验证器会先调用它）：每个场景用独立进程依次运行，最后从 SQLite 会话读回轨迹、数外部工单，核对契约，整套场景连跑两遍必须逐字节相同。

<!-- adk-refs:start -->

## 在 ADK-Rust 源码里

第 9 节用到的动作账本与恢复，在 ADK-Rust 里分布在这几处：

| 本章内容 | 源码位置 | 对照要点 |
| --- | --- | --- |
| 工具的副作用声明 | [`adk-core/src/tool.rs` · `ToolEffect`](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-core/src/tool.rs#L668-L677) | 没有声明的工具按 `NonIdempotent` 对待：只执行一次，不自动重试 |
| 每次调用的幂等键 | [`adk-agent/src/llm_agent.rs` · `idempotency_key`](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-agent/src/llm_agent.rs#L2358-L2369) | 普通调用为应用 / 用户 / 会话 / 本次运行 / 调用 ID，换一轮运行就是新键（`retry-call-key` 出现第二张工单的原因）；等待批准后恢复的调用沿用第一次的键 |
| 动作账本的接口 | [`adk-core/src/action_ledger.rs` · `ActionLedger`](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-core/src/action_ledger.rs#L245-L268) | 调用前记开始、调用后记结果；恢复时按键查询 |
| SQLite 上的账本 | [`adk-session/src/sqlite_action_ledger.rs` · `SqliteActionLedger`](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-session/src/sqlite_action_ledger.rs#L31-L33) | 本章把它和会话放在同一个 SQLite 文件；`InMemoryActionLedger` 进程退出即丢 |
| 恢复没有结果的调用 | [`adk-runner/src/runner.rs` · `Runner::recover_unanswered_calls`](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-runner/src/runner.rs#L2423-L2425) | 按账本回答 `already_succeeded` / `already_failed` / `outcome_unknown`，不执行任何工具 |
| 结果未知时交给模型的答案 | [`adk-core/src/action_ledger.rs` · `outcome_unknown_response`](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-core/src/action_ledger.rs#L51-L53) | 提醒“可能已经生效，再调用前先核对”；判断用 `is_outcome_unknown` |

源码固定在 ADK-Rust `98515241133d`（3.0.0，2026-11-26，尚未发布到 crates.io）。本节由 `scripts/learn-agent-rust-adk-refs.py` 生成。

<!-- adk-refs:end -->

::: warning 常见误区
- 使用新的 operation ID 重试同一意图，会绕过原键的去重；标题相同不能替代业务身份。
- 本地事务只保护本地业务意图与 Outbox。服务端操作需要自己的原子幂等契约，Outbox 仍可能多次投递。
- 回执里的工单 ID 和摘要需要与原请求核对；本例摘要不认证发送者，真实传输还需认证和授权。
- 幂等保留期之外不能沿用期内的保证。对账查不到结果时，要结合服务可见性和仍在途请求处理。
- 本实验没有实际网络、跨 worker 调度或 PostgreSQL 集成；第 9 节只验证单个工具在单机进程退出后的恢复语义。这些验证不能代替真实系统的验收。
- 框架的动作账本只管同一次调用的重放；模型在新一轮里重发，就是新的幂等键，去重要靠稳定的业务身份。
:::

<!-- transfer-thinking:start -->

## 迁移思考：业务身份比重试次数稳定

同一业务意图重试时生成新 operation_id，会绕过幂等吗？先给出你的判断，再展开下面的推演。

<details><summary>推演与应用</summary>

检查唯一约束针对的身份是否跨重试稳定，且相同身份携带不同内容时明确拒绝。

可靠性依赖双方共享的业务合同；客户端少重试几次无法替代服务端去重。

</details>

这是一道迁移练习，推演不代表新增实验已通过。对照[全书审查中的证据层次](./course-review.md#evidence-layers)，说明你的判断还需要哪一级证据。

<!-- transfer-thinking:end -->

## 本章结论

先把同一业务意图的身份和参数保存下来，再发送。服务把幂等键、业务结果和回执原子保存；客户端通过 Outbox 找回待处理意图，通过合法回执和检查点记录进度。结果不明时，按服务契约重放或对账，证据不足就保留 unknown。

这套实验让“是否再次调用”和“外部是否多做了一次”成为两个可以分别核对的问题。它的保证范围由身份作用域、幂等保留期、查询能力和本地提交边界共同决定。

放进 ADK-Rust 3.0 以后，框架的动作账本接手了“同一次调用”的部分：在账本持久、工具为非幂等、重启后先调用恢复的前提下，进程在工具里或工具后退出，恢复时都不会再执行工具，并如实回答 `outcome_unknown` 或 `already_succeeded`。新的一次调用不在它的范围内，业务身份、外部去重和对账仍是应用自己的合同。

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

6. 进程在工具里退出，恢复后模型在新一轮运行里重发了创建请求，为什么动作账本没有拦住第二张工单？

   <details><summary>参考答案</summary>

   账本按幂等键记账，而 ADK-Rust 的幂等键包含本次运行和调用 ID。新一轮运行里的调用是新键，账本视为一次新调用，外部服务看到的也是新的操作身份。要避免重复，操作身份必须跨运行稳定，并由外部服务按它原子去重。`retry-business-key` 场景用“会话 + 标题”演示了这一点；更可靠的做法是在创建意图时生成操作 ID 并保存，后续每次调用都沿用它（第 3、5 节）。

   </details>

## 参考资料

- [AWS Builders' Library：Making retries safe with idempotent APIs](https://aws.amazon.com/builders-library/making-retries-safe-with-idempotent-APIs/)：客户请求身份、同意图重试与迟到请求。
- [Transactional Outbox 模式](https://microservices.io/patterns/data/transactional-outbox.html)：本地事务保存消息意图与重复投递问题。
- [Stripe 幂等请求文档](https://docs.stripe.com/api/idempotent_requests)：真实服务的键、参数和保留策略示例；具体接口以服务文档为准。
- [SQLite 原子提交](https://www.sqlite.org/atomiccommit.html)与[隔离性](https://www.sqlite.org/isolation.html)：本实验事务所依赖的数据库语义。
- <a href="/learn-agent-rust/code/side-effect-reliability/README.md" download>完整实验运行说明</a>：命令、退出码、期限、计数与未验证范围。
- ADK-Rust（固定提交）：[持久运行与动作账本](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/docs/official_docs/core/durable-runtime.md)、[2.x → 3.0 迁移指南](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/docs/official_docs/migration/2.x-to-3.0.md)。

下一专题是[模型协议与质量评估](./model-evaluation.md)，分别验证协议完成与业务任务完成。
