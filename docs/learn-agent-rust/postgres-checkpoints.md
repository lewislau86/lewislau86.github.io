---
title: "专题 1：PostgreSQL 检查点"
description: "保存消息、下一步和累计预算，用真实 PostgreSQL 与独立进程验证恢复、并发拒写和不确定动作。"
pageClass: learn-agent-rust-course
---

# 专题 1：PostgreSQL 检查点

[课程总览](./index.md) · [学习路径](./learning-path.md#p01) · [下一专题：外部操作的可靠性](./side-effect-reliability.md)

::: tip 本章学习目标
- 判断一个保存点是否包含继续执行所需的消息、位置和预算。
- 用修订号与保存身份处理并发更新，以及提交后丢失确认的重试。
- 比较整批工具与逐工具保存，识别动作结果不确定时的恢复边界。

**前置：** [第 2 章的消息与图节点](./tools-and-graph.md)、[第 11 章的错误与预算](./error-recovery.md)、[第 12 章的持久化状态](./task-system.md)。本章工程可独立运行。

**实践方式：** [下载 Cargo 学习包](/learn-agent-rust/postgres-checkpoints-lab.zip)，准备 Rust、Python 3.9+ 和 PostgreSQL 18 服务端工具。模型采用固定响应，无需密钥；验证器自动创建、运行并清理专用临时数据库。
:::

助手已经读完 README，接着准备读取 Cargo.toml，终端却关闭了。重新启动后，它应该再次询问用户，重读 README，还是直接继续第二次读取？

如果只保存最终回答，程序不知道进行到了哪里；只保存“正在执行工具”，又不知道哪个调用已回传。我们需要留下一份能重建执行现场的数据：已看到的消息、接下来执行的位置，以及已经消耗的预算。

本章继续使用“核对启动命令”的小任务。脚本模型一次提出两条调用，程序分别读取 README.md 和 Cargo.toml，再把结果交回模型。每次 `step` 都由新进程执行，结束后只剩数据库和练习文件。

<LearnAgentRustMap active="postgres-checkpoints" />

<!-- experiment-library:start -->

全书实验可从[统一代码库](./experiments.md#postgres-checkpoints)下载；解压后进入 `chapters/postgres-checkpoints/`，或在代码库根目录运行 `python3 run.py run P01`。

<!-- experiment-library:end -->

## 1. 恢复一次任务，需要留下什么？

先预测：读取第一个文件后，只存下正文，是否足以恢复？还差三个问题：正文属于哪条调用、下一个该读什么、剩余预算是多少。

| 状态 | 本例保存什么 | 恢复用途 |
| --- | --- | --- |
| 消息历史 | 用户请求、assistant 的调用 ID、工具结果 | 重建模型可见上下文，保留请求与结果配对。 |
| 推进位置 | phase、工具 cursor、工作流版本 | 决定下一次进入模型、工具、对账还是结束。 |
| 累计预算 | 模型轮次、工具分发次数及上限 | 重启后继续扣同一份额度。 |
| 存储身份 | 会话 ID、revision、save_id | 区分会话、检测旧写入、识别同一次保存重试。 |
| 不确定标记 | model_in_flight、tool_in_flight、uncertain | 结果缺失时保留现场，避免自动重复动作。 |

![新进程从数据库读回消息、推进位置和预算，再重新创建数据库连接与工具对象。](/learn-agent-rust/figures/p01-state-boundary.svg)

从左向右看：进程把可序列化状态写进数据库，新进程读回后重建运行对象。数据库连接、文件句柄与 Rust 函数指针没有进入快照，由程序重新创建；代码通过 `workflow_version` 与快照对齐。

::: info 源码、输出与实验范围
下文代码直接导入 <a href="/learn-agent-rust/code/postgres-checkpoints/src/state.rs" download>state.rs</a>、<a href="/learn-agent-rust/code/postgres-checkpoints/src/store.rs" download>store.rs</a> 与 <a href="/learn-agent-rust/code/postgres-checkpoints/src/driver.rs" download>driver.rs</a>；完整工程见[学习包](/learn-agent-rust/postgres-checkpoints-lab.zip)。

本次环境为 Rust 1.99.1、postgres 0.19.12、本机 PostgreSQL 18.6。模型是确定性脚本，文件访问与数据库进程真实。实验验证应用状态机的持久化契约；graph-flow Storage、真实模型服务与完整 Agent 集成另行验收。
:::

<<< @/public/learn-agent-rust/code/postgres-checkpoints/src/state.rs#state

这份状态为小任务固定了两次模型轮次和两次工具分发。`cursor=1` 表示第一条结果已进入历史，下次从第二条调用开始。计数保存到数据库，换进程也不会归零。

### 三种版本分别回答什么？

`format_version` 说明如何解码快照结构；`workflow_version` 说明哪个版本的代码可以解释它；数据库里的 `revision` 表示同一会话已经更新了多少次。

本例只接受格式 1 和工作流 `p01-v1`。读到其他版本会拒绝推进，原数据保留。迁移需要单独设计和验收，解码失败时不能悄悄换成空会话。

## 2. 把快照保存到 PostgreSQL

这里的“检查点”是应用状态快照。PostgreSQL 内部也有数据库恢复用的 CHECKPOINT；本章通过普通事务保存应用记录，不发送 CHECKPOINT 来表示一轮 Agent 完成。

两张表承担不同职责：`p01_sessions` 保存当前快照，`p01_checkpoints` 追加历史快照和保存身份。

<<< @/public/learn-agent-rust/code/postgres-checkpoints/src/store.rs#schema

每次更新把“当前快照”和“新增历史行”放在同一事务。读取者看到已提交的版本，本实验中不会看到写者尚未提交的中间更新。依据见 [PostgreSQL 事务入门](https://www.postgresql.org/docs/18/tutorial-transactions.html)和 [Read Committed](https://www.postgresql.org/docs/18/transaction-iso.html#XACT-READ-COMMITTED)。

### JSON 能解析，还要校验什么？

恢复前核对消息与位置一致。例如 `cursor=1` 时，必须恰好有第一条调用的结果；孤立工具消息不能伪装成已完成工作。预算不能超过上限，结束状态要有完整结果，in-flight 状态必须已经预留本次额度。

<<< @/public/learn-agent-rust/code/postgres-checkpoints/src/state.rs#validate

校验面向本章固定流程，便于完整读懂规则。状态上限为 16 KiB，每条工具结果最多 4096 个 UTF-8 字节；版本、配对和预算不合法时拒绝载入或保存。扩展到开放任务时，需要对应的通用状态契约。

## 3. 两个进程都拿到修订 0，谁能保存？

假设 A、B 都读到 `revision=0`。A 保存后修订变为 1；B 仍按 0 写入时，应收到冲突，重新读取后再决定后续动作。

<<< @/public/learn-agent-rust/code/postgres-checkpoints/src/store.rs#save

沿代码读一次：开启事务 → FOR UPDATE NOWAIT 锁定会话行 → 核对保存身份 → 核对预期修订 → 更新当前快照 → 追加历史 → 提交。

`NOWAIT` 让已有写者时立即返回 `store_busy`；如果前一个写者已提交，后一个拿到锁后会看到新修订，返回 `revision_conflict`。行锁只在短暂的数据库事务中持有，模型与工具在事务外运行。[官方锁文档](https://www.postgresql.org/docs/18/explicit-locking.html#LOCKING-ROWS)说明了行锁与 NOWAIT 的语义。

验证器让三个真实进程都停在保存前的管道门闩，再统一放行，断言只有一个成功写者、历史只新增一份。胜者名字及另外两次拒绝的分布由调度决定，因此下面引用核对摘要，完整普通 CLI 响应在学习包 evidence.json。

<<< @/public/learn-agent-rust/outputs/p01-race-three.txt

另一个 `lock-and-reader` 场景让 A 更新后停在事务内：B 普通读取仍得到修订 0，竞争写入返回忙；A 提交后新进程读到修订 1。门闩按真实检查点同步，没有用固定 sleep 猜测并发是否发生。

### save_id 解决哪一种重复？

数据库已提交，进程却在打印成功响应前退出，调用方可能不知道结果。直接换新身份重试，可能把同一快照再存一次。

本例让调用方带稳定的 `save_id`，历史表以 `(session_id, save_id)` 唯一约束记录它。相同身份、相同预期修订、相同完整状态，返回原保存回执；任何一项不一致，返回 `save_identity_conflict`。

回执中的修订表示**那一次保存的位置**。如果会话后来推进了，重试旧保存仍返回旧修订；继续执行前必须重新载入当前状态。这只处理数据库保存重试，外部工具的业务幂等另有契约。

## 4. 一轮结束保存，还是每个工具后保存？

模型在一轮中提出 `read-1` 和 `read-2`。使用相同文件、调用顺序和预算，只改变结果保存粒度。

| 粒度 | 一次工具步骤做什么 | 第一个工具后能恢复到哪里？ |
| --- | --- | --- |
| batch | 顺序执行两个工具，结果一起保存 | 批次尚无结果检查点，中断时留下批次 in-flight。 |
| tool | 每次执行一个工具，各自保存 | 第一条结果和 cursor=1 已提交，下次从第二条继续。 |

![同样的两次读取在 batch 模式中合并保存，在 tool 模式中分别保存，后者可以从第二条调用继续。](/learn-agent-rust/figures/p01-checkpoint-granularity.svg)

先读相同的调用 ID，再看保存位置。图中的结果数与游标来自真实场景：完成一次工具步骤后，batch 保存两条结果，tool 保存一条。这比较的是恢复边界，没有进行性能测量。

每个正常步骤保存两次：先记录“准备执行”和预算，再保存结果。逐工具流程如下：

| 独立进程 | 执行内容 | 提交后的修订 |
| --- | --- | --- |
| 创建会话 | 初始用户消息，尚未运行 | 0 |
| 第一次 step | 预留模型轮次，保存两条调用 | 2 |
| 第二次 step | 预留一次工具额度，保存 README 结果 | 4 |
| 第三次 step | 预留第二次额度，保存 Cargo.toml 结果 | 6 |
| 第四次 step | 预留最后一次模型轮次，保存最终回答 | 8 |

<<< @/public/learn-agent-rust/code/postgres-checkpoints/src/driver.rs#step

本章用显式 phase 表达推进位置。接回第 2 章的图时，如果一批工具放在一个节点中，节点结束时的保存自然对应整批边界；逐工具恢复需要把游标、单个结果与保存点一并接进驱动器。仅改变数据库后端，无法自动细分节点内部的检查点。

### 怎样证明没有重新读第一个文件？

`resume-next-tool` 场景保存 README 结果后，真实删除 README.md。下一个独立进程完成第二次读取，模型从已保存的第一条结果核对 cargo run，最终结束。

<<< @/public/learn-agent-rust/outputs/p01-resume-next-tool.txt

删除文件让“从第一条重新执行”变成可观察的失败，实验确实从游标 1 继续。重建的是可序列化执行状态，旧进程的栈与线程没有恢复。

练习工作区由验证器创建并信任，路径在每次 step 时传入。实际系统还应绑定工作区身份和输入版本：已保存的结果继续沿用，尚未执行的读取会看到恢复时的文件，快照本身不会冻结整个文件系统。

## 5. 工具做完了，结果却没保存

把第二个工具换成向 `audit.log` 追加一行 `report delivered`，并调用 sync_all()。在文件写入成功后、数据库结果保存前，以退出码 75 终止进程。

新进程看到：第一条工具结果已保存，第二次工具额度已消耗，phase=tool_in_flight，但没有第二条结果。实际日志已经有一行。

![文件追加已经成功，数据库仍只有动作前标记；恢复保留预算并进入对账，避免自动追加第二次。](/learn-agent-rust/figures/p01-uncertain-action.svg)

沿时间线看，文件系统写入与数据库提交处于不同边界。数据库没有结果，无法据此判断动作尚未开始、正在执行还是已经完成。图中的日志行数、已保存结果数和预留次数来自故障场景。

<<< @/public/learn-agent-rust/outputs/p01-external-effect-window.txt

### 先保存 in-flight，有什么作用？

它告诉新进程“这次额度已预留，结果需要核对”。本例恢复时转成 reconcile：

<<< @/public/learn-agent-rust/code/postgres-checkpoints/src/driver.rs#recover

重复 step 仍保持对账状态，日志不会新增第二行，预算也不重置。这个选择偏保守：进程在动作真正开始前退出，也会留下相同标记，需要先核对。

模型也有同类窗口。`model-reply-window` 让脚本模型返回后退出；数据库保留已预留的一轮，恢复不自动再次调用。接真实服务时，费用、超时与响应身份需要对应重试协议。

恢复操作应在原执行者已退出或已被外部机制停止后进行。本章没有执行者租约或取消协议，in-flight 本身也不表示原进程已经停止。多执行者所有权见[自主任务领取](./autonomous-workers.md)。

### 普通保存错误也要核对

`save-failure` 在第二个工具结果事务提交前主动返回错误，结果回滚，先前的 in-flight 标记保留。下一次恢复同样进入对账。`tool-failure` 真实删除第二个输入文件，检查文件访问失败后已预留的额度仍然保留。

本章没有“补写成功”或自动对账命令。可重放读取与有副作用动作需要分别制定策略；[专题 2](./side-effect-reliability.md)继续处理业务操作身份、幂等与对账。

## 6. 在提交两侧退出，再重启数据库

为了隔离保存事务本身，验证器直接调用可信 save 接口保存同一份合法状态，核对事务两侧退出的区别。

![提交前退出时状态与历史都不前进，提交后确认丢失时二者均已保存；相同保存身份使重试返回原回执。](/learn-agent-rust/figures/p01-commit-recovery.svg)

比较左右两列的新进程读取结果。相同的非正常退出可能留下不同的数据库事实；先读取当前修订与历史，再决定重试。

<<< @/public/learn-agent-rust/outputs/p01-exit-before-commit.txt

提交前以 73 退出，当前修订为 0，历史一份；用原保存身份重试后得到修订 1。

<<< @/public/learn-agent-rust/outputs/p01-exit-after-commit.txt

提交后、正常响应前以 74 退出，修订已是 1；原身份重试返回 replayed=true，历史不再追加。

### 数据库进程退出以后呢？

`database-restart` 保存第一条工具结果后，对专用临时 PostgreSQL 执行 immediate stop，重新启动同一数据目录，确认快照一致，再由新客户端完成任务。`server-crash-uncommitted` 在事务内暂停写者后立即停止数据库，重启确认当前状态和历史都没有保留未提交更新。

<<< @/public/learn-agent-rust/outputs/p01-database-restart.txt

本例打开 fsync、full_page_writes 和 synchronous_commit，真实执行数据库进程恢复。立即停止模式见[服务器关闭文档](https://www.postgresql.org/docs/18/server-shutdown.html)。未进行物理断电、磁盘损坏、主从切换或远程网络故障实验；持久化承诺仍依赖数据库与存储配置，见[异步提交说明](https://www.postgresql.org/docs/18/wal-async-commit.html)。

## 7. 动手实验：从下载包重跑

解压进入 postgres-checkpoints-lab。确认 PostgreSQL **服务端**工具在同一版本目录；只有 psql 客户端不足以创建临时数据库。

```sh
# macOS Homebrew 示例；Linux 可改为 /usr/lib/postgresql/18/bin
export P01_PG_BIN=/opt/homebrew/opt/postgresql@18/bin
cargo test --locked
cargo build --locked
python3 lab.py --binary target/debug/learn-agent-p01 --output ./results
```

以普通用户运行，无需先启动常驻数据库服务。脚本在 /tmp 新建专用集群和独有 Unix socket 目录，关闭 TCP 监听，只操作自己的数据目录；退出时停止并清理。结果在 results/，完整请求与响应见 results.json，各 txt 是验证器断言摘要。

手动逐步执行的方法见包内 README，在专用练习数据库上设置 P01_DATABASE_URL。连接串通过环境变量传入，不打印进记录。本地实验使用 NoTls，远程加密、认证与租户隔离另行配置。

### 本次验证清单

每轮 25 个场景启动 **108 个独立 Rust CLI 进程**；初始化和版本探测另计，PostgreSQL 工具进程也不包含在这个数字中。验证器另运行 10 个 Rust 单元测试、Clippy，并实际解压最终 zip，在另一个目标目录离线重新编译、复验全部场景。

<!-- p01-results:start -->

| 场景 | 独立 Rust CLI 进程 | 验证结果 |
| --- | --- | --- |
| `normal` | 8 | 通过断言 |
| `tool-granularity` | 3 | 通过断言 |
| `batch-granularity` | 3 | 通过断言 |
| `resume-next-tool` | 5 | 通过断言 |
| `model-reply-window` | 4 | `exit=76` |
| `tool-result-window` | 6 | `exit=75` |
| `batch-first-tool-window` | 5 | `exit=75` |
| `external-effect-window` | 7 | `exit=75` |
| `save-failure` | 6 | `injected_failure` |
| `exit-before-commit` | 4 | `exit=73` |
| `exit-after-commit` | 4 | `exit=74` |
| `save-identity` | 6 | `save_identity_conflict` |
| `revision-conflict` | 4 | `revision_conflict` |
| `race-three` | 4 | 通过断言 |
| `lock-and-reader` | 4 | `store_busy` |
| `database-restart` | 7 | 通过断言 |
| `server-crash-uncommitted` | 4 | 通过断言 |
| `format-version` | 3 | `format_version` |
| `workflow-version` | 3 | `workflow_version` |
| `corrupt-state` | 3 | `corrupt_state` |
| `invalid-budget` | 3 | `invalid_budget` |
| `message-pairing` | 3 | `message_pairing` |
| `tool-failure` | 6 | `tool_failed` |
| `duplicate-session` | 2 | `duplicate_session` |
| `missing-session` | 1 | `session_missing` |

<!-- p01-results:end -->

仓库内复验：

```sh
python3 scripts/verify-agent-checkpoints.py --check
python3 scripts/generate-learn-agent-rust-figures.py --lesson P01
npm run docs:build
```

证据在 scripts/data/learn-agent-rust/p01-results.json，图由中央生成器读取证据生成。--check 会重新执行实验，并核对源码摘要、输出与学习包。

::: warning 常见误区
- 应用快照、PostgreSQL 内部 CHECKPOINT 与外部业务结果分属不同层次；普通文件写入或远程调用不在本章保存事务中。
- save_id 去重的是数据库保存。外部业务幂等需要服务认可的操作身份。
- 状态校验保证本例数据形状与内部一致性。save 是可信应用接口，不提供用户认证，也不验证任意调用方提出的业务迁移是否合法。
- 本例没有自动重试不确定动作、快照清理、旧格式迁移或框架适配。实验通过范围以清单和证据为准。
:::

<!-- transfer-thinking:start -->

## 迁移思考：检查点是可重建的承诺

消息保存了但工具游标没保存，下次从哪里执行？先给出你的判断，再展开下面的推演。

<details><summary>推演与应用</summary>

同时核对位置、调用、结果与累计额度；只保存聊天记录无法唯一确定下一步。

为恢复设计状态时，先写重启算法，再判断保存的信息是否充分。

</details>

这是一道迁移练习，推演不代表新增实验已通过。对照[全书审查中的证据层次](./course-review.md#evidence-layers)，说明你的判断还需要哪一级证据。

<!-- transfer-thinking:end -->

## 本章结论：把下一步和已消耗额度一起保存

恢复所需的不只有聊天文本。消息配对、推进位置、累计预算和代码版本共同组成快照；修订号阻止旧状态覆盖，保存身份让确认丢失后的重试能找到原提交。

本章选择在动作前预留预算、标记 in-flight，动作后保存结果。逐工具检查点允许从下一条调用继续，结果不确定时保留现场并停下来对账。数据库负责快照事务，业务动作的可靠性继续由下一专题处理。

## 检查理解

1. 第一条结果已保存，为什么还要保存 cursor 和工具次数？

   <details><summary>参考答案</summary>

   cursor 指定下一条调用，次数保留累计预算。只存结果文本无法完整重建推进位置，重启后也可能错误恢复额度。这些字段必须与历史一致。

   </details>

2. 两个写者读到修订 0，一个已提交，另一个如何处理？

   <details><summary>参考答案</summary>

   第二个取得行锁后发现修订不同，返回 revision_conflict，调用方重新读取再决定下一步。如果第一个仍持锁，NOWAIT 返回 store_busy。本例不在存储层无限等待或自动覆盖。

   </details>

3. 原 save_id 重试返回修订 1，当前会话已经到 3，可以从 1 继续吗？

   <details><summary>参考答案</summary>

   修订 1 是原保存回执，不代表当前状态。继续执行前 load 最新状态，再按最新修订保存。相同身份也必须核对相同 expected 和完整状态。

   </details>

4. 保存了 in-flight，为什么还不能断言工具成功？

   <details><summary>参考答案</summary>

   退出可能发生在调用之前、调用之中，或成功后而结果尚未保存。这些路径留下相同标记。本例保留预算进入 reconcile，后续检查真实结果，不能单凭标记自动完成或重复调用。

   </details>

5. 一个图节点顺序执行两个工具，接入 PostgreSQL 后自动获得逐工具恢复吗？

   <details><summary>参考答案</summary>

   需要检查框架的实际保存点。节点结束时保存只覆盖整批边界；逐工具恢复还要显式保存游标、单条结果和预算，并让驱动器从对应调用继续。

   </details>

## 参考资料

- [PostgreSQL 18：事务](https://www.postgresql.org/docs/18/tutorial-transactions.html)、[事务隔离](https://www.postgresql.org/docs/18/transaction-iso.html)、[显式锁](https://www.postgresql.org/docs/18/explicit-locking.html)。
- [异步提交与持久化边界](https://www.postgresql.org/docs/18/wal-async-commit.html)、[服务器关闭](https://www.postgresql.org/docs/18/server-shutdown.html)。
- [postgres 0.19.12 Rust 驱动](https://docs.rs/postgres/0.19.12/postgres/)、[Transaction 接口](https://docs.rs/postgres/0.19.12/postgres/struct.Transaction.html)。
- [本章学习包](/learn-agent-rust/postgres-checkpoints-lab.zip)：固定依赖、实验驱动、保存记录与源码摘要。

接下来阅读[专题 2：外部操作的可靠性](./side-effect-reliability.md)，继续处理“业务成功、确认丢失”的窗口。
