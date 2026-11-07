---
title: "第 12 章：持久化任务系统"
description: "用稳定任务 ID、依赖校验、合法状态迁移与整板快照，验证跨进程恢复和保存失败的边界。"
prev:
  text: 第 11 章 · 错误分类与恢复
  link: /learn-agent-rust/error-recovery
next:
  text: 第 13 章 · 后台任务
  link: /learn-agent-rust/background-tasks
pageClass: learn-agent-rust-course
---

# 第 12 章：持久化任务系统

[课程总览](./index.md) · [上一章：错误分类与恢复](./error-recovery.md) · [下一章：后台任务](./background-tasks.md)

::: tip 本章学习目标
- 区分会话清单、业务任务与图执行节点，为任务建立稳定身份和依赖。
- 用合法状态迁移、整板版本和尝试序号，拒绝过期或矛盾的更新。
- 从新进程读取任务，并验证保存失败、异常退出与损坏快照的处理。

**前置：** [第 5 章：可见的任务清单](./todo-planning.md)、[第 11 章：错误分类与恢复](./error-recovery.md)；Rust 的枚举、所有权、`Result` 与文件操作。

**实践方式：** 下载[独立 Cargo 学习包](/learn-agent-rust/task-system-lab.zip)，使用 Rust 1.99.1。依赖 `serde` 与 `serde_json`，版本由 `Cargo.lock` 固定。首次获取工具链与依赖需要网络；运行无需模型密钥或数据库。
:::

工作区助手要整理一份启动指南：先读项目说明，再核对启动命令，最后整理指南。第 5 章的清单能展示这三个步骤，但终端一关，内存中的进度就消失了。第二天重新打开，助手应该从哪里继续？

把清单保存成 JSON 是第一步。接下来还要回答：前置任务没完成，能不能直接写指南？旧进程的结果晚到了，会不会覆盖新的尝试？保存返回错误时，磁盘上究竟是旧状态还是新状态？

本章建立一个小型任务板。**恢复的依据是经过校验并成功保存的任务记录；遇到执行结果不明，先核对再决定。**

先预测：任务已经保存为 `running`，进程随后退出。新进程读到它时，应该自动改回 `pending` 吗？读完第 7 节，再检查这个选择会不会重复执行外部动作。

<LearnAgentRustMap active="task-system" />

## 1. 先确定我们保存的是什么

| 对象 | 表达的问题 | 生命周期与边界 |
| --- | --- | --- |
| 第 5 章会话清单 | 当前助手准备做哪些步骤？ | 本次运行的可见计划。 |
| 本章业务任务 | 哪件工作已完成，依赖谁，尝试过几次？ | 稳定 ID 与磁盘状态跨进程保留。 |
| 图执行节点 | 运行时现在调用哪个处理函数？ | 同一节点可以处理不同业务任务。 |
| 完整运行检查点 | 消息、预算、待处理调用和恢复位置是什么？ | 需要额外设计保存契约，不能只保存任务板。 |

一个 `readme` 任务可以经历多轮模型和工具调用；一个 `ExecuteTools` 节点也可以服务很多业务任务。不要把任务 ID、工具 `call_id` 和图节点名混用。

::: info 源码与实验范围
全文 Rust 片段直接导入[完整 Cargo 源码](https://github.com/lewislau86/lewislau86.github.io/tree/master/docs/public/learn-agent-rust/code/task-system)；[下载工程与证据](/learn-agent-rust/task-system-lab.zip)。工程包含 `main.rs`、`tasks.rs`、`storage.rs`、测试与锁文件。

这是**任务元数据实验**。CLI 的可信调用者提交完成结果或失败原因，程序不会执行任务标题中的命令。磁盘读写、独立进程、竞争锁和终止子进程是真实操作；没有连接模型、`graph-flow`、任务 worker 或数据库。
:::

## 2. 跑起来：关闭进程，任务仍然在

解压后进入 `task-system-lab`。以下命令适用于 macOS/Linux shell，`demo` 是新建的专用数据目录；再次运行同一组命令请换一个新目录。`init` 不会覆盖现有快照。

```sh
cargo test --locked
cargo run --locked -- demo init
cargo run --locked -- demo apply 0 '{"op":"add","id":"readme","title":"读取项目说明","depends_on":[],"max_attempts":2}'
cargo run --locked -- demo apply 1 '{"op":"add","id":"guide","title":"整理启动指南","depends_on":["readme"],"max_attempts":2}'
cargo run --locked -- demo apply 2 '{"op":"start","id":"readme"}'
cargo run --locked -- demo show
cargo run --locked -- demo apply 3 '{"op":"complete","id":"readme","attempt":1,"result":"已核对启动命令 cargo run"}'
```

每条 `cargo run` 都启动新进程。`show` 仍读到 `readme` 正在运行，说明状态来自磁盘。最后一条命令是调用者报告结果；字符串中出现 `cargo run`，并不表示实验执行过项目启动命令。

`apply` 后的数字是你刚读到的整板 `revision`。上面依次使用 `0`、`1`、`2`、`3`；成功修改后递增，单纯 `show` 不递增。CLI 标准输出为 JSON，包含 `board`、`ready` 与 `reconcile`；发生错误时输出错误 JSON 并以状态码 `1` 退出。

验证器另建三个任务 `readme → check → guide`，每次操作也用独立进程。下面是**从真实 JSON 字段整理的摘要**，不是 CLI 原始标准输出；`#1` 表示累计尝试一次，`-` 表示空列表。原始响应保存在下载包的 `evidence.json` 中。后文所有实验输出采用同一口径。

<<< @/public/learn-agent-rust/outputs/r12-new-process-chain.txt

观察两个时刻：`readme` 开始后 `ready=-`；它完成后 `ready=check`。仅仅结束启动命令的进程，既不会完成业务任务，也不会解锁后继。

![实际三任务链在 revision 3 时只有 readme 可运行，完成前置任务后才逐个解锁。](/learn-agent-rust/figures/r12-task-dependencies.svg)

箭头表示执行先后，任务内部 `depends_on` 保存前置 ID。图下的版本与可运行列表取自实验实际响应；增加任务时的版本变化也算整板更新。

## 3. 给任务一个稳定身份和受控状态

<<< @/public/learn-agent-rust/code/task-system/src/tasks.rs#model

`id` 表示同一件业务工作，重试时沿用；`title` 供人阅读，不用来匹配任务。任务板中 ID 唯一，本例不提供删除与 ID 复用入口。

三个数字有不同职责：

| 字段 | 范围 | 用途 |
| --- | --- | --- |
| `schema` | 存储格式 | 当前仅接受 `1`，未知版本停止加载。 |
| `revision` | 整张任务板 | 防止拿旧视图提交更新，包括依赖修改。 |
| `attempts` | 单个业务任务 | 每次开始递增，结果中的 `attempt` 必须与当前值一致。 |

`max_attempts` 包含第一次尝试。`retry` 只把失败任务重新放回待运行状态，不减少次数，也不抹掉最近失败。`Completed` 是终态，本章不提供重新打开已完成任务的操作。

本例刻意设小上限：最多 32 个任务，每个最多 8 条依赖，尝试上限为 1–5；ID 最多 40 字节，标题最多 160 字节，结果与错误最多 512 字节。字符串长度按 UTF-8 **字节**计算。这些是实验边界，避免小示例变成无界存储。

## 4. 先校验整个依赖图，再接受修改

只检查“依赖都已完成”还不够。如果 `a` 等待 `b`、`b` 又等待 `a`，它们可能永远等下去。

本章用 DFS 维护两个集合：`visiting` 表示当前递归路径，`done` 表示已完整检查的节点。再次遇到 `visiting` 中的 ID，就发现了环；遇到 `done` 可直接返回。自依赖也会被同一规则拒绝。

<<< @/public/learn-agent-rust/code/task-system/src/tasks.rs#graph

同一次 `validate` 还检查任务 ID、重复依赖、缺失前置、计数范围、结果与状态是否相容，以及最多一个 `Running`。**从磁盘加载也执行同一套校验。** 有效 JSON 只能证明语法能解析，不能证明它代表合法任务板。

依赖只能在首次开始前修改；开始过一次，即使失败后重新进入 `Pending`，依赖仍冻结。这样，已经执行过的尝试不会被悄悄换成另一项前提不同的工作。

<<< @/public/learn-agent-rust/outputs/r12-dependency-cycle.txt

上述更新试图形成环，返回 `dependency_cycle`。验证器还逐字节比较拒绝前后的正式快照，确认失败没有改动磁盘；同样覆盖缺失依赖、自环与重复 ID。

## 5. 把更新做成一次完整事务

合法迁移如下：

| 操作 | 起点 → 终点 | 额外条件 |
| --- | --- | --- |
| `start` | Pending → Running | 前置全部完成、执行位置空闲、次数未用尽；先增加次数。 |
| `complete` | Running → Completed | 提交的 `attempt` 匹配，结果非空。 |
| `fail` | Running → Failed | 提交的 `attempt` 匹配，失败原因非空。 |
| `retry` | Failed → Pending | 仍有尝试额度，保留已有次数与失败信息。 |

`Board::propose` 检查当前版本后，克隆出候选板，在候选上修改并重新校验。任何一步失败，都不会改变原板。

<<< @/public/learn-agent-rust/code/task-system/src/tasks.rs#transition

例如，你看到 `revision=5`，别人已经把任务板改到 `6`。即使你修改另一项任务，也必须重新加载、重新判断后提交。这里采用整板版本，宁可让无关任务产生一次冲突，也不实现复杂的局部合并。

版本正确仍不代表结果属于当前尝试。第 1 次失败后开始了第 2 次，旧 worker 的第 1 次完成通知即使带着最新板版本，也会因 `attempt_conflict` 被拒绝。尝试序号用于拒绝过期结果，不能代替执行者认证或外部操作幂等键。

存储入口把读取、候选计算、保存与应答串起来：

<<< @/public/learn-agent-rust/code/task-system/src/storage.rs#transaction

将来接入真实工具时，应先确认 `start` 已保存，再派发外部工作。若保存结果不明，先重读核对；不能看到一个错误就直接派发或再开始一次。

## 6. 一次保存，哪里是边界？

专用数据目录里有三个角色：

| 文件 | 职责 |
| --- | --- |
| `tasks.json` | 唯一正式快照，保存整张板。 |
| `.tasks.lock` | 持久存在的锁文件，持锁状态由操作系统管理。 |
| `.tasks.pending` | 本次更新写入的新候选，通过独占新建避免覆盖遗留候选。 |

### 文件锁先保护读—改—写

<<< @/public/learn-agent-rust/code/task-system/src/storage.rs#lock

所有命令，包括 `show`，都先尝试取得同一个文件的排他锁。`Storage` 保管文件句柄直到命令结束，因此另一进程不能插进事务中间。竞争时立即返回 `store_busy`，没有忙等循环。API 的锁语义见 [File::try_lock](https://doc.rust-lang.org/std/fs/struct.File.html#method.try_lock)。

锁文件本身一直存在。**不要通过删除 `.tasks.lock` 解锁。** 实验在持锁子进程被终止并回收后，用新进程重新取得锁。文件存在不代表锁被占用；替换文件可能让不同进程锁住不同对象。

锁仅串行化合作 CLI 的元数据事务。一个 `start` 命令退出后，操作系统锁释放，但保存的 `Running` 仍占用业务执行位置。本章没有租约、owner、心跳、多执行者领取或分布式锁，可信目录检查也不是对抗恶意文件竞争的安全沙箱。

### 先写新快照，再替换正式快照

<<< @/public/learn-agent-rust/code/task-system/src/storage.rs#save

保存顺序为：验证候选 → 序列化 → 独占新建临时文件 → 完整写入并 `sync_all` → 同目录 `rename` → Unix 下同步父目录 → 返回成功。`Pending` 的析构只清理本次成功创建的候选，不删除操作前已有的文件。

[File::sync_all](https://doc.rust-lang.org/std/fs/struct.File.html#method.sync_all)用于请求同步文件内容和元数据；[`rename`](https://doc.rust-lang.org/std/fs/fn.rename.html)替换目标路径，并有文件系统与平台条件。这里固定同一目录、同一文件系统，整板快照让依赖和状态随同一次替换更新。它没有让外部业务写入与任务板成为同一个事务。

![在 rename 前后分别终止进程，正式快照的版本、状态与遗留候选不同。](/learn-agent-rust/figures/r12-save-boundary.svg)

图中两个实验都等待子进程发出指定检查点，再执行终止并等待回收。左侧停在替换前，右侧停在文件替换与目录同步后；图里的版本与次数来自随后新进程的读取。

### 返回错误不一定表示没有保存

替换前注入普通返回错误，旧快照保留，析构清理本次临时文件。替换后、目录同步前注入错误，返回 `durability_unknown`，且 `committed=true`：

<<< @/public/learn-agent-rust/outputs/r12-save-after-rename.txt

此处的 `committed` 专指**已经越过 rename 边界**。新进程实际读到新版本，但这个字段不能证明物理断电后仍保留。调用者应重读、核对任务及尝试序号，而不是用旧版本重放。

替换前强制终止进程时，析构不会执行，候选会遗留：

<<< @/public/learn-agent-rust/outputs/r12-crash-before-rename.txt

新进程可以读取正式快照，但继续写入会返回 `pending_unavailable`。程序不会自行选择候选覆盖正式文件。验证器只在自己的隔离目录中，确认子进程已回收、正式快照有效且候选版本符合预期后，移除该未提交候选并重试。实际系统需要受控的维护流程，不能把“启动时删掉临时文件”当作恢复策略。

## 7. 重启之后，Running 应该怎么办？

查询逻辑主动区分“可以开始”和“需要核对”：

<<< @/public/learn-agent-rust/code/task-system/src/tasks.rs#queries

`ready` 只包含前置完成、次数可用的待运行任务；板上有一个 `Running` 时，整个列表为空。`reconcile` 列出正在运行的任务 ID。即使原进程已退出，也不能据此判断业务效果是否发生。

![重启保留 Running 与已用次数，核对失败后显式 retry 才能开始下一次尝试。](/learn-agent-rust/figures/r12-restart-state.svg)

这是 `running-restart` 的实际路径：已保存的 `Running#1` 被新进程原样读出，直接 `start` 被拒绝；可信调用者核对后报告失败，再显式 `retry`，下一次开始成为 `Running#2`。

<<< @/public/learn-agent-rust/outputs/r12-running-restart.txt

真实接入时应分别处理：确认外部操作已完成，提交匹配尝试的 `complete`；确认失败且允许重试，记录 `fail` 后再决定 `retry`；仍不确定，继续保留待核对状态。若旧执行者仍可能运行，必须先停止或隔离它，不能仅靠修改任务板阻止它产生外部效果。

恢复后次数不会清零。`max_attempts=2` 的任务两次失败后，再次 `retry` 返回 `attempt_limit`。这里持久化的是**业务任务开始次数**；第 11 章的模型调用总账、工具内部重试、累计等待与截止时间没有自动纳入本板。完整运行恢复还需要这些状态各自的持久化契约。

## 8. 损坏记录不能悄悄变成空板

<<< @/public/learn-agent-rust/code/task-system/src/storage.rs#load

加载最多读取 65,537 字节，用多出的一个字节判断是否超过 65,536 字节上限；随后严格解析字段并调用 `validate`。缺文件、未知 schema、非法状态、坏依赖图、未知字段和超长内容都有明确错误。

`init` 是独立操作，不会因为读取失败而自动创建空板。验证器对损坏场景保存原始字节，并确认失败后文件没有被“修复”或覆盖。记录异常时，应保留证据并进行显式恢复或迁移。

## 9. 用进程与文件验证承诺

本章完成 **26 个场景和 14 个 Rust 测试**。每轮场景共启动 **119 次独立 CLI 进程**；随后实际解压最终学习包，重新编译，再完整执行同一组场景。正常响应与正式快照逐项比对；拒绝操作前后比较文件字节；异常退出测试使用同步检查点、终止与回收，避免靠固定等待时间猜测进度。

<!-- r12-results:start -->

| 场景 | 独立进程 | 验证结果 |
| --- | --- | --- |
| `new-process-chain` | 15 | `completed=3` |
| `dependency-blocked` | 4 | `dependency_incomplete` |
| `dependency-cycle` | 5 | `dependency_cycle` |
| `self-cycle` | 3 | `dependency_cycle` |
| `missing-dependency` | 3 | `dependency_missing` |
| `duplicate-id` | 3 | `duplicate_id` |
| `illegal-transition` | 3 | `illegal_transition` |
| `stale-revision` | 3 | `revision_conflict` |
| `stale-attempt` | 7 | `attempt_conflict` |
| `retry-budget` | 8 | `attempt_limit` |
| `single-executor` | 7 | `single_running` |
| `running-restart` | 8 | `explicit_recovery_attempt=2` |
| `save-before-rename` | 5 | `old_snapshot_preserved` |
| `save-after-rename` | 5 | `new_snapshot_visible` |
| `crash-before-rename` | 7 | `kill_before_commit` |
| `crash-after-commit` | 5 | `kill_after_commit` |
| `corrupt-json` | 3 | `corrupt_store` |
| `unknown-schema` | 3 | `schema_version` |
| `invalid-state` | 3 | `invalid_state` |
| `corrupt-cycle` | 3 | `dependency_cycle` |
| `unknown-field` | 3 | `corrupt_store` |
| `size-limit` | 3 | `size_limit` |
| `pending-file` | 3 | `pending_preserved` |
| `invalid-store-file` | 3 | `invalid_store_file` |
| `invalid-request` | 3 | `invalid_request` |
| `missing-store` | 1 | `store_missing` |

<!-- r12-results:end -->

表中 `committed` 与快照内容分别核对；原始响应、最终快照摘要及文件 SHA-256 见学习包的 `evidence.json`。正文输出和三张自制图均由同一份证据生成。

在网站仓库复验：

```sh
python3 scripts/verify-agent-tasks.py --check
python3 scripts/generate-learn-agent-rust-figures.py --lesson R12
python3 scripts/sync-learn-agent-rust-course.py --check
npm run docs:build
```

本地结果来自 macOS arm64 和 Rust 1.99.1；仓库增加 Ubuntu CI 配置，远端执行结果以实际运行记录为准。尚未实测 Windows、网络文件系统、磁盘真实写满或物理断电。故障注入验证控制流与可见快照，不能替代这些环境的耐久性实验，也不能证明完整 Agent 会话恢复或外部动作恰好执行一次。

::: warning 常见误区
- **保存 JSON 就能恢复整个 Agent。** 本章只保存业务任务板；消息、审批、模型上下文和预算需要各自的恢复契约。
- **进程退出就把 Running 改回 Pending。** 外部动作可能已完成；先核对，再显式记录结果或失败。
- **有文件锁就有任务领取。** 锁保护一条 CLI 事务；跨命令的执行位置由持久状态约束，多执行者还需 ownership 与租约。
- **保存返回错误就安全重试。** 替换后错误可能已留下新快照，必须重读核对。
- **清理临时文件就是修复数据。** 遗留候选和损坏正式文件都需要保留与受控检查，不能自动当成新空板。
:::

## 本章结论

稳定 ID 让同一任务跨进程保持身份，依赖校验阻止无效执行顺序，状态迁移约束每一步是否合法。整板版本拒绝旧视图，尝试序号拒绝旧结果，保存顺序明确了什么时候可以应答。

恢复时，我们重新读取经过校验的正式快照，并保留已用次数。对于 `Running` 与保存结果不明的情形，任务板提供的是核对入口；下一章再为实际后台执行建立句柄、取消和回收机制。

## 检查理解

### 1. 工具调用 ID、业务任务 ID 和图节点名能共用一个字符串吗？

<details><summary>参考答案</summary>

它们代表不同身份：业务任务跨多轮与多次尝试存在；工具调用 ID 配对一次请求与结果；图节点名指向处理逻辑。应该分别保存，必要时建立显式关联。

</details>

### 2. 有文件锁，为什么还检查 revision？

<details><summary>参考答案</summary>

锁只保护当前命令的读—改—写。调用者做决定时看到的板可能已经过期；`revision` 检查这次意图是否仍基于当前视图，拒绝后要求重新加载与判断。

</details>

### 3. 重启读到 Running#1，能直接标为 Pending 并重试吗？

<details><summary>参考答案</summary>

不能仅根据进程退出这样做。外部效果可能已经产生，旧执行者也可能仍存在。先核对并控制执行者，再显式报告完成或失败；只有失败且允许重试、额度足够时，才重新开始，并保留次数。

</details>

### 4. rename 已完成，随后返回 durability_unknown，应该怎么处理？

<details><summary>参考答案</summary>

将其视为越过替换边界、耐久性未确认。重新读取正式快照，核对版本、任务和尝试；不能假设没有保存，更不能直接重放业务动作。新进程看见新状态也不能证明物理断电耐久性。

</details>

### 5. 为什么不在 JSON 解析失败时返回 Board::empty？

<details><summary>参考答案</summary>

解析失败可能意味着损坏或格式升级。返回空板会隐藏问题，并可能在下次保存时覆盖原始证据。应明确报错、保留文件，由显式恢复或迁移处理。

</details>

## 参考资料

- [完整 Rust 工程与实验记录](/learn-agent-rust/task-system-lab.zip)：任务模型、存储、测试、输出与证据。
- [Rust File::try_lock](https://doc.rust-lang.org/std/fs/struct.File.html#method.try_lock)、[File::sync_all](https://doc.rust-lang.org/std/fs/struct.File.html#method.sync_all)、[std::fs::rename](https://doc.rust-lang.org/std/fs/fn.rename.html)：文件锁、同步与替换的 API 契约。
- [参考课程 S12：Task System](https://learn.shareai.run/zh/s12/)：关注稳定身份、依赖与跨会话任务；本章 Rust 实验采用整板快照，并额外验证环、版本与保存边界。
- [课程架构与参考资料说明](./architecture.md#reference-assets)、[PostgreSQL 检查点专题](./postgres-checkpoints.md)、[外部操作可靠性专题](./side-effect-reliability.md)：后两项仍是规划专题。

<details><summary>对照参考课程原图</summary>

以下图片原样保留自参考课程，展示其 Python/Claude 教学实现；接口、编号与统计沿用原图。它们不代表本章 Rust 工程的验证结果。

![参考课程用文件任务板组织任务身份、依赖与状态。](/learn-agent-rust/figures/upstream/r12-task-system-overview.svg)

图源：[参考章节](https://learn.shareai.run/zh/s12/) · [原图](https://learn.shareai.run/course-assets/s12_task_system/task-system-overview.svg)。

![参考课程的任务依赖图。](/learn-agent-rust/figures/upstream/r12-task-dag.svg)

图源：[参考章节](https://learn.shareai.run/zh/s12/) · [原图](https://learn.shareai.run/course-assets/s12_task_system/task-dag.svg)。来源版本和许可见[参考资料说明](./architecture.md#reference-assets)。

</details>

下一章：[第 13 章：后台任务](./background-tasks.md)。为耗时工作建立可查询、可取消、可回收的执行生命周期，并区分持久业务身份与本次执行句柄。
