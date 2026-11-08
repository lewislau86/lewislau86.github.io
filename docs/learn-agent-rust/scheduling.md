---
title: "第 18 章：定时调度"
description: "用具名时区、稳定触发身份和 SQLite 事务，验证每日计划的重启补触发、去重与提交边界。"
pageClass: learn-agent-rust-course
prev:
  text: 第 17 章 · 后台任务
  link: /learn-agent-rust/background-tasks
next:
  text: 第 19 章 · Agent 团队
  link: /learn-agent-rust/agent-teams
---

# 第 18 章：定时调度

[课程总览](./index.md) · [上一章](./background-tasks.md) · [学习路径](./learning-path.md#r14) · [下一章](./agent-teams.md)

::: tip 本章学习目标
- 把“每天当地 09:00”变成有明确时区和身份的到期事件，处理夏令时的缺失与重复时刻。
- 验证错过触发时补哪一次、重复扫描是否重复入队，以及进程退出后怎样继续。
- 在同一个数据库事务里保存待执行任务和扫描进度，区分入队成功与任务完成。

**前置：** 理解[第 13 章的跨进程存储](./memory.md)与[第 15 章的有限重试](./error-recovery.md)。课程上的前置为[持久化任务系统](./task-system.md)、[后台任务](./background-tasks.md)，R12 已有持久化任务实验，R13 已提供独立后台实验；本章也提供独立的调度与队列实验，可以直接运行。

**实践方式：** 下载 [scheduling-lab.zip](/learn-agent-rust/scheduling-lab.zip)，进入解压后的 `scheduling-lab` 执行 `cargo build --locked`。本机验证使用 Rust 1.99.1、edition 2024。SQLite 随依赖编译，首次构建需要网络和 C 编译器；运行时无需模型密钥或数据库服务。
:::

工作区助手已经可以接到一个目标再开始行动。现在用户提出另一个要求：

> 每天上海时间 09:00，生成一份项目日报任务。

如果只把这句话放在模型历史里，下一轮什么时候发生？电脑休眠错过了 09:00，启动后要补哪一次？同一分钟扫描两次，会不会出现两份日报任务？

这一章沿着这一个计划向前走。先把时间规则存下来，再由程序定期检查到期点，将工作写入持久队列。模型是否有空、怎样生成日报，是消费队列之后的下一段流程。

<LearnAgentRustMap active="scheduling" />

<!-- experiment-library:start -->

全书实验可从[统一代码库](./experiments.md#scheduling)下载；解压后进入 `chapters/scheduling/`，或在代码库根目录运行 `python3 run.py run R14`。

<!-- experiment-library:end -->

::: info 本章实验状态
已验证真实 SQLite 文件、独立 CLI 进程、具名时区换算与两个明确的进程退出点。配套验证覆盖 27 个场景、10 个 Rust 测试和 Clippy，并实际解压最终学习包、独立编译与复验全部场景。

主要实验注入固定时刻；另运行两次真实时钟轮询，核对正常退出。工程只生成 `daily_report / queued` 记录，尚未接入 Agent、报告执行者、两库图调度或系统服务。长期准点率、断电、多机故障与外部操作可靠性另行验收。
:::

## 1. 先跑一次：同一个到期点扫描两遍

::: info 代码与输出只有一个来源
所有 Rust 片段引用网站工程 `docs/public/learn-agent-rust/code/scheduling/`。正文输出由验证器执行同一份源码生成，zip 包还包含锁文件、README 和实验记录。

[下载完整工程与记录](/learn-agent-rust/scheduling-lab.zip) · <a href="/learn-agent-rust/code/scheduling/src/scheduler.rs" download>下载调度源码</a> · [在 GitHub 查看工程](https://github.com/lewislau86/lewislau86.github.io/tree/master/docs/public/learn-agent-rust/code/scheduling)
:::

在解压后的目录执行：

```sh
cargo build --locked
cargo run --locked -- init demo.db
cargo run --locked -- add demo.db report Asia/Shanghai 09:00 coalesce --start 2026-11-07T00:59:00Z
cargo run --locked -- tick demo.db 2026-11-07T00:59:59Z
cargo run --locked -- tick demo.db 2026-11-07T01:00:00Z
cargo run --locked -- tick demo.db 2026-11-07T01:00:00Z
cargo run --locked -- show demo.db
```

`report` 是不可变的计划 ID；`Asia/Shanghai 09:00` 是每日的当地时间规则。`--start` 给出已经检查完的 UTC 游标：首次只考虑它之后的到期点，不追溯创建起点之前的历史。所有实验时间都固定在命令中，无需等待现实中的 09:00。

先猜三个扫描结果：上海时间 08:59:59、09:00:00、再次 09:00:00，分别新增几条任务？

<<< @/public/learn-agent-rust/outputs/r14-normal.txt

结果依次是 `inserted=0`、`1`、`0`，最后队列里只有一条任务。输出中的 `DB` 是验证器对临时路径的统一显示；每个命令标签下的 JSON 来自对应进程。前一次进程退出，下一次才启动，数据库文件是它们之间保留状态的地方。

`show` 中的 `due` 是计划到期时刻，`cursor` 是已经扫描到的时刻。它们职责不同：电脑晚启动时，到期时刻仍指向原来的时间，而游标会前进到这次实际检查的时间。

![每日计划由轮询器检查，时间换算和到期选择完成后，在同一个 SQLite 事务中写入排队任务与扫描游标。](/learn-agent-rust/figures/r14-schedule-to-queue.svg)

从左到右读：程序可以自动扫描，待执行工作留在磁盘队列。本章止于右侧的 `queued`，没有把一条入队记录解释成日报已经生成。

## 2. 每天 09:00，为什么不能直接加 86400 秒？

上海的例子容易让人想到：记住本次 UTC 时间，下一次加一天就好。换成有夏令时的地区，这个做法会改变当地钟表上的时间。

本例保存的是**具名时区 + 当地时分**。每次扫描枚举候选日期，把该日期的当地时刻转换为 UTC，再筛选到期点。固定依赖 `chrono-tz` 提供 IANA 时区数据；其文档也用跨夏令时加 24 小时的例子说明当地钟表时间可能变化，见 [Chrono-TZ 文档](https://docs.rs/chrono-tz/0.10.4/chrono_tz/)。

### 一个本地时刻，可能对应几个 UTC 时刻？

<<< @/public/learn-agent-rust/code/scheduling/src/scheduler.rs#timezone

关注 `from_local_datetime` 的三个分支：正常时是一个结果，回拨时可能有两个结果，跳时后可能没有结果。[Chrono 的 LocalResult 文档](https://docs.rs/chrono/0.4.45/chrono/offset/enum.LocalResult.html)说明 `Ambiguous` 按较早、较晚的顺序返回。

本章为每日计划选择以下规则：

| 映射结果 | 本章处理 |
| --- | --- |
| `Single` | 使用该 UTC 时刻。 |
| `Ambiguous`，当地时刻出现两次 | 只使用较早一次。 |
| `None`，当地时刻不存在 | 该日不触发。 |

这是一套应用策略，换算库不会替我们决定业务应补哪一次。本例使用自带时区数据、受限日期范围；无法映射的当地时刻按跳过处理。

可以直接查看固定日期的映射：

```sh
cargo run --locked -- resolve America/New_York 2026-03-08 02:30
cargo run --locked -- resolve America/New_York 2026-11-01 01:30
```

![固定时区数据中，纽约 2026 年 3 月 8 日 02:30 不存在；11 月 1 日 01:30 对应两个 UTC 时刻，本例只选择较早一次。](/learn-agent-rust/figures/r14-dst-mapping.svg)

先看左侧缺少 UTC 候选的情形，再看右侧两个候选中被选中的较早时刻。图中时间来自真实 `resolve` 输出；调度场景还验证了春季当天不入队、秋季第二次到达 01:30 时不再次入队。

测试也核对纽约跨春季切换前后两个当地 09:00 的 UTC 间隔为 23 小时。它说明每日钟表规则应重新按日历换算；“每隔固定 24 小时”则是另一种需求，需要另外定义。

时区数据库会随政策变更更新。本包固定 Cargo 版本，并在 `evidence.json` 记录内置时区数据版本；升级后应重跑这些边界案例。计划配置在本例中不可编辑，改时区或时分要使用新 ID，旧计划的停用与迁移尚未实现。

## 3. 到底哪些时刻算“这次到期”？

<<< @/public/learn-agent-rust/code/scheduling/src/scheduler.rs#due

`due` 先检查时间是否向后、窗口是否过大，然后枚举候选当地日期。日期枚举在 UTC 起止日期的两端各留一天余量，以覆盖本例支持范围中的时区偏移；候选转换成 UTC 后再严格过滤。

真正的筛选条件只有一个区间：**`cursor < due <= now`**。

左侧开区间让上次已经检查过的时刻不会再次被选中；右侧闭区间保证恰好到点也会触发。随后按 UTC 排序，准备决定这次要保留哪一个到期点。

这里先发生夏令时选择，再发生区间过滤。如果回拨日的较早一次已经过去，程序不会把较晚一次当成新的补发机会。

### 时间回拨与长时间停机

如果传入 `now` 早于任意计划的游标，本次扫描返回 `clock_regression`，整次事务回滚。这样系统时钟回拨时不会悄悄倒退进度；程序也不会自动猜测操作者是否想重放历史。

单次扫描窗口最多 `31 × 86400` 秒，计划最多 32 条，防止一次启动扫描无界历史。超过窗口返回 `scan_window_limit`，游标保持原样。恢复时可以按递增的时间分段扫描，但每一段都会分别应用补触发策略；它与把全部停机窗口合并为一次扫描，可能产生不同的任务数，需要由操作者先选择恢复口径。

时间输入要求带偏移的 RFC 3339、整秒，并限制 UTC 年份为 2000–2100。本例按 POSIX 时间秒组织身份，没有另行实现闰秒调度。

## 4. 电脑错过三天，只补哪一次？

假设计划从 2026 年 11 月 6 日上海时间 08:59 开始，直到 11 月 8 日 09:05 才扫描。窗口中有 6 日、7 日、8 日三个 09:00，到底应生成三份日报任务还是一份？

先看 `coalesce` 的真实输出：

<<< @/public/learn-agent-rust/outputs/r14-coalesce.txt

三个点被发现，但只保留最新的 8 日 09:00，`discarded=2`。对“给我当前项目状态”这样的任务，最新一次可能比连续生成三份当前快照更合适；如果需要每一天历史时点的报告，应另外实现逐点回补与对应历史数据读取。

现在只改变策略，改成 `skip`：

<<< @/public/learn-agent-rust/outputs/r14-skip.txt

本例 `skip` 也只看最新到期点，并增加 **60 秒宽限**：晚到不超过 60 秒可以入队，再晚就放弃。这里晚了 5 分钟，所以三个点全被丢弃，游标仍前进到本次扫描时刻，下次不会再反复检查这些点。

![相同的三个到期点，在 coalesce 下只生成最近一次任务，在 skip 下因最近一次也超出宽限而全部丢弃。](/learn-agent-rust/figures/r14-misfire-policy.svg)

两行使用完全相同的时区、时分、起点和扫描时刻，只改变策略。图里的发现数、入队数和丢弃数来自实际运行。`60 秒` 是本例的固定常量，测试核对了恰好 60 秒与 61 秒的分界。

因此“支持补触发”需要说清策略和扫描窗口。每次晚启动都把所有旧任务补齐，会造成一阵突发工作；每次都跳过，又可能长期漏掉任务。这里选择显式配置与有界处理，把结果输出给调用方。

## 5. 为什么任务与游标必须一起保存？

假设程序已经把日报任务写入队列，随后还没保存游标就退出。重启时看到旧游标，它会再次发现同一个到期点。反过来，如果先保存游标、还没写任务就退出，这次工作可能被跳过去。

本例让两份状态处于一个数据库事务中：

<<< @/public/learn-agent-rust/code/scheduling/src/scheduler.rs#transaction

沿这段代码阅读：`BEGIN IMMEDIATE` → 读取计划 → 计算到期点 → 插入任务 → 更新游标 → `COMMIT`。循环中任何一个计划校验失败，整批计划的修改都会回滚。

`IMMEDIATE` 会在开始时尝试取得写事务，已有写者时可能返回忙，具体行为见 [SQLite 事务文档](https://www.sqlite.org/lang_transaction.html)。本例立即返回 `store_busy`，验证器先持有真实写锁观察拒绝，再释放锁重试；没有进行高并发负载或多机竞争测试。调用方需要重试时，应继续遵循[第 15 章](./error-recovery.md)的次数、等待与总预算约束。

### 同一个触发，怎样认出来？

<<< @/public/learn-agent-rust/code/scheduling/src/scheduler.rs#schema

任务身份由 `计划 ID@到期 UTC 秒` 组成，表上同时有 `UNIQUE(schedule_id, due_utc)`。**实际扫描时刻没有进入任务身份**，因此晚 1 秒扫描、重启后重新扫描，都不会把同一到期点变成另一个任务。

计划 ID 在本例中不能改写或复用，也没有删除命令。固定配置让这套身份保持明确；将来支持原地编辑规则时，还要定义计划版本、旧到期点与新配置的关系。

正常重复扫描时，开区间首先排除了旧点；唯一约束是另一层检查。`duplicate-identity` 场景故意只回退游标、保留已有队列行，再扫描一次，验证唯一约束仍使新增数为 0。这个操作只是隔离验证身份约束的故障夹具，不是恢复建议。

队列最多保存 4096 条记录，超限时本次事务整体拒绝，游标不前进。本章没有消费者和保留期管理，所以持续使用前还需要设计领取、完成、清理与历史保留策略。

## 6. 在两个退出点重启

我们先主动返回一个保存错误，再让进程在两个不同位置直接退出。三个实验都启动新进程读取同一数据库。输出中的 `process_exit` 行由验证器根据真实退出码记录，故障进程本身没有返回 JSON。

### 插入之后、提交之前退出

<<< @/public/learn-agent-rust/outputs/r14-exit-before-commit.txt

故障选项 `--exit-after-insert` 在任务插入语句之后直接调用 `process::exit(73)`，跳过 Rust 作用域的正常清理。新进程读到的队列和游标仍与插入前相同；随后重试同一时刻，恰好生成一条任务。

这里验证了进程在指定未提交位置退出后的状态。SQLite 的日志与恢复机制见[原子提交说明](https://www.sqlite.org/atomiccommit.html)；这次演练没有切断供电，也没有证明所有文件系统上的持久性。

### 提交完成、返回确认之前退出

<<< @/public/learn-agent-rust/outputs/r14-exit-after-commit.txt

`--exit-after-commit` 在成功提交后以退出码 74 结束，调用方没有收到正常 JSON 确认。新进程却能读到队列行和已前进的游标；重试只新增 0 条任务。

![提交前退出时任务与游标都不保留，提交后未返回确认时二者均已保留；新进程重试最终都只保留一条排队记录。](/learn-agent-rust/figures/r14-commit-recovery.svg)

先比较两列标题中的提交位置，再沿箭头向下读。相同的非零退出状态，并不代表相同的持久化结果。两个场景都通过重新读取数据库判断状态，没有单凭退出码假设“什么都没发生”。

另一个 `rollback` 场景使用 `--fail-after-insert` 返回普通错误，验证 Rust 事务正常释放时回滚；`rollback-all` 则让后一个计划失败，检查前一个计划刚插入的任务也被回滚。

### 唯一入队之后，业务就只执行一次了吗？

本章的证明范围是：在这个库与身份规则下，同一个到期点最多保留一条排队记录。下一步消费者仍可能领取后崩溃、调用工具成功但未记录完成，或重试外部请求。

日报写入、发消息或其他外部操作的幂等性，需要在[外部操作可靠性专题](./side-effect-reliability.md)单独设计。调度器也不恢复模型消息、审批或运行中的后台线程；它只让到期工作持久留在队列。

## 7. 真正按钟表轮询，谁来调用 tick？

前面把 `now` 放进命令，是为了让夏令时、重启与故障实验可重复。工程另外提供真实时钟入口：

```sh
cargo run --locked -- tick-now demo.db
cargo run --locked -- run demo.db 10
```

`tick-now` 读取当前 UTC 时钟扫描一次；`run` 在前台自动扫描 10 次，轮次之间等待 1 秒，最后退出。轮数限制为 1–60，遇到存储或时间错误立即返回错误。它需要数据库里的游标与当前时钟相容；较老的练习库若超过扫描窗口，应先按第 3 节选择恢复方案。

<<< @/public/learn-agent-rust/code/scheduling/src/main.rs#cli

整个过程不需要模型回合来“记得检查时间”。前台程序退出期间没有调度线程继续运行；再次启动后，程序从磁盘游标计算窗口，并按 `coalesce` 或 `skip` 处理错过的时刻。长期服务的启动、守护、取消与监控需要在集成阶段另外实现。

验证器对一个空计划库执行 `run DB 2`，确认两次真实时钟扫描正常结束；主要触发实验仍使用固定时间。短轮询成功只能说明这个入口接线正确，不能当作长时间运行的延迟或准点率测量。

## 8. 动手实验：每次改变一个条件

1. 用新数据库重复第 1 节。先检查 08:59:59，然后正好 09:00，再重复正好 09:00，核对队列数与 `inserted`。
2. 把起点改为 11 月 6 日 08:59，扫描改为 11 月 8 日 09:05。分别使用 `coalesce`、`skip`，保持其他输入完全一致。
3. 在新库的首次到期扫描后加 `--exit-after-insert`。重新执行 `show`，再不带故障选项扫描。用另一个新库测试 `--exit-after-commit`，比较两次首次重启看到的状态。
4. 用 `resolve` 检查纽约的两个夏令时案例，预测哪个会没有任务、哪个只生成一次，再查看 `dst-gap` / `dst-fold` 的实际输出。

固定时间实验都使用 2026 年的明确日期。每组换一个新的 `.db` 文件名；`init` 会拒绝已有文件，避免练习命令覆盖上一次的记录。不要手动删除正在使用的 SQLite journal。

以下结果表由验证器生成。“独立 CLI 进程”包含建库、配置、扫描、查询与故障进程；“最终排队数”只统计数据库中的 `queued` 记录，所有场景都没有实际执行日报。

<!-- r14-results:start -->

| 场景 | 独立 CLI 进程 | 最终排队数 | 故障 / 拒绝 |
| --- | --- | --- | --- |
| `normal` | 6 | 1 | — |
| `restart` | 6 | 2 | — |
| `coalesce` | 4 | 1 | — |
| `skip` | 4 | 0 | — |
| `grace` | 4 | 1 | — |
| `grace-expired` | 4 | 0 | — |
| `not-due` | 4 | 0 | — |
| `dst-gap` | 5 | 0 | — |
| `dst-fold` | 6 | 1 | — |
| `rollback` | 7 | 1 | `injected_after_insert` |
| `exit-before-commit` | 7 | 1 | `exit=73` |
| `exit-after-commit` | 6 | 1 | `exit=74` |
| `duplicate-identity` | 5 | 1 | — |
| `clock-regression` | 5 | 0 | `clock_regression` |
| `window-limit` | 5 | 0 | `scan_window_limit` |
| `rollback-all` | 6 | 0 | `clock_regression` |
| `busy` | 7 | 1 | `store_busy` |
| `duplicate-schedule` | 5 | 0 | `duplicate_schedule` |
| `invalid-config` | 7 | 0 | `invalid_id` / `invalid_local_time` / `invalid_misfire` / `invalid_timezone` |
| `invalid-time` | 7 | 0 | `invalid_timestamp` / `unsupported_timestamp` |
| `missing` | 1 | — | `database_error` |
| `corrupt` | 1 | — | `database_error` |
| `schema` | 3 | 0 | `unsupported_schema` |
| `invalid-cursor` | 4 | 0 | `invalid_cursor` |
| `queue-limit` | 3 | 4096 | `queue_limit` |
| `invalid-cli` | 9 | 0 | `database_exists` / `invalid_ticks` / `usage` |
| `real-clock-poll` | 3 | 0 | — |

<!-- r14-results:end -->

`queue-limit` 的 4096 条记录是验证器在临时库中构造的满队列夹具；`corrupt`、`schema` 与 `invalid-cursor` 也会刻意修改临时文件，核对失败时没有继续入队。缺失数据库不会被普通读取命令静默创建。完整输出、源码摘要、Rust host、SQLite 和时区数据版本见学习包的 `evidence.json`。

在网站仓库根目录复验：

```sh
python3 scripts/verify-agent-scheduling.py --check
python3 scripts/generate-learn-agent-rust-figures.py --lesson R14
```

验证器把工程复制到仓库外的临时目录，运行格式检查、10 个 Rust 测试、Clippy 和全部场景；再实际解压最终 zip，在另一个构建目录离线编译，重新执行全部场景并比较输出。证据中的初次生成环境标签会在 `--check` 时保留，行为会在当前机器重新测量。

::: warning 常见误区
- **把当地时间当固定偏移。** 每日规则保存具名时区，并明确缺失、重复时刻的策略；时区数据升级需要重验。
- **把补触发理解成补齐所有历史。** 本章每个计划每次扫描最多生成一条任务，分段扫描也会改变合并范围。
- **把非零退出码理解成未提交。** 提交后返回确认前也可能退出，恢复时先读取持久状态。
- **把唯一入队理解成外部操作恰好执行一次。** 消费者、幂等与完成确认属于后续执行协议。
- **把短轮询当长期服务。** 本包提供有界前台程序，没有安装守护服务，也没有验证长期准点率与断电恢复。
:::

<!-- transfer-thinking:start -->

## 迁移思考：时间事件需要稳定身份

服务宕机错过每日任务，重启后补跑两次会怎样？先给出你的判断，再展开下面的推演。

<details><summary>推演与应用</summary>

先定义补触发策略，再让游标与触发身份共同提交；检查重复触发是否生成同一业务任务。

按日调度涉及业务日、时区和重启语义，不能仅依赖 sleep 间隔。

</details>

这是一道迁移练习，推演不代表新增实验已通过。对照[全书审查中的证据层次](./course-review.md#evidence-layers)，说明你的判断还需要哪一级证据。

<!-- transfer-thinking:end -->

## 本章结论

工作区助手现在有了一层按时间生产工作的机制：每日规则按当地日历换算，扫描窗口明确，错过触发的策略显式配置；任务用稳定的触发身份入队，并与扫描游标一起提交。

本章选择小范围的持久化调度核心：每日时分、具名时区、最多一次合并补触发与 SQLite 原子入队。接下来的执行者可以消费这些工作，但仍要独立处理领取、权限、取消、业务副作用与完成确认。

## 检查理解

1. 为什么到期身份使用 `计划 ID + 到期 UTC 秒`，而不用“这次扫描的 UTC 秒”？

   <details><summary>参考答案</summary>

   同一个到期点可能被晚扫描、重试或重启后的进程再次看见。扫描时刻会变化，规则推导出的到期点保持相同，才能识别同一份工作。计划 ID 在本例中还必须保持配置不可变且不能复用。

   </details>

2. `skip` 场景丢弃三个到期点后，游标该不该前进？

   <details><summary>参考答案</summary>

   应当前进到本次检查的时刻。这三个点已经按配置决定跳过；不推进会在下一次反复处理同一段历史。策略选择与游标更新在同一事务中保存。

   </details>

3. 为什么纽约“每天 09:00”与“每隔 86400 秒”可能生成不同时间？

   <details><summary>参考答案</summary>

   当地日历会受时区规则影响。跨夏令时切换时，相邻两个当地 09:00 的 UTC 间隔可能变化；固定秒数表达的是经过时长。本章按日期重新换算，并测试了春季相邻两次间隔为 23 小时。

   </details>

4. 事务已提交、调用方却未收到确认，重试时为什么没有第二条任务？

   <details><summary>参考答案</summary>

   新进程读到已经前进的游标，开区间排除旧点；数据库还对计划 ID 与到期 UTC 秒建立唯一约束。此结论针对入队记录，外部业务是否重复执行仍需消费者协议保证。

   </details>

5. 停机 90 天后，直接把游标改成今天是否是一种可靠恢复？

   <details><summary>参考答案</summary>

   这会直接放弃中间的到期点。应先决定业务是否需要回补，再选择分段扫描、人工生成工作或重新建立起点；分段扫描还要考虑每段分别合并导致的任务数变化。本例超出窗口时保持原游标并报错。

   </details>

## 参考资料

- [Chrono 0.4.45：LocalResult](https://docs.rs/chrono/0.4.45/chrono/offset/enum.LocalResult.html)、[Chrono-TZ 0.10.4](https://docs.rs/chrono-tz/0.10.4/chrono_tz/)：本地时刻映射与具名时区数据。
- [SQLite：事务](https://www.sqlite.org/lang_transaction.html)、[原子提交](https://www.sqlite.org/atomiccommit.html)、[UPSERT](https://www.sqlite.org/lang_upsert.html)：对照事务边界、写锁和唯一键冲突处理。
- [参考课程 s14 Cron Scheduler](https://learn.shareai.run/zh/s14/)：对照调度、排队与消费的分层；上游 Python/Claude 的完整机制与本章独立 Rust 工程分别验收。

### 保留的参考原图

![参考实现把调度线程、到期队列与空闲时启动 Agent 的消费流程分开，本章 Rust 实验验证持久化调度与排队部分。](/learn-agent-rust/figures/upstream/r14-cron-scheduler-overview.svg)

先辨认图中的生产与消费边界。本章使用具名时区的每日规则与 SQLite 队列，没有实现原图的完整 cron 表达式、Agent 空闲检查或自动交付。图源：[参考章节](https://learn.shareai.run/zh/s14/) · [原图](https://learn.shareai.run/course-assets/s14_cron_scheduler/cron-scheduler-overview.svg)。来源版本与许可见[参考资料说明](./architecture.md#reference-assets)。

下一章：[Agent 团队](./agent-teams.md)。当多个执行者能够接收工作时，继续讨论各自的会话、邮箱与生命周期。
