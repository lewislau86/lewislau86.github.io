---
title: "第 29 章：自主任务领取"
description: "从两个执行者争抢同一份日报出发，用真实 SQLite 和独立进程验证原子领取、租约续期、过期接管与旧执行者拒写。"
pageClass: learn-agent-rust-course
prev:
  text: 第 28 章 · 团队协作协议
  link: /learn-agent-rust/team-protocols
next:
  text: 第 30 章 · 工作区隔离
  link: /learn-agent-rust/worktree-isolation
---

# 第 29 章：自主任务领取

[课程总览](./index.md) · [上一章：团队协作协议](./team-protocols.md) · [下一章：工作区隔离](./worktree-isolation.md)

::: tip 本章学习目标
- 解释为什么“先查待办、再标记运行”必须处于同一个存储事务。
- 使用执行者身份、领取代次与租约，验证续期、接管和旧结果拒写。
- 区分任务所有权与业务幂等，用一次退出重放观察外部动作的重复窗口。

**前置：** [第 24 章的持久化任务](./task-system.md)和[第 28 章的协议身份](./team-protocols.md)。本章会直接解释用到的身份概念；配套工程可独立运行。

**实践方式：** [下载本章 Rust 工程](/learn-agent-rust/autonomous-workers-lab.zip)，使用 Rust、Cargo 和系统 C 编译器。SQLite 随 rusqlite 编译，无需数据库服务或模型密钥。
:::

任务板里有一条“整理日报”。worker-a 和 worker-b 几乎同时看到它还没开始，于是都动手了。即使两人都认真完成了任务，系统也收到了两份报告。

给任务加上 owner，问题会消失吗？如果两个进程都先读取 pending，再分别写入自己的名字，它们仍可能都以为自己领取成功。再往前走一步：A 真正领取了，却在工作中失联，B 什么时候可以接管？A 随后恢复，又能否把旧结果覆盖回来？

本章沿这份日报向前走：先把领取变成一个原子操作，再给领取凭证加上截止时间和代次，最后检查业务动作重放。这里的“自主”指执行者自己从队列选择可领取的工作；任务选择由程序规则完成。

<LearnAgentRustMap active="autonomous-workers" />

<!-- experiment-library:start -->

全书实验可从[统一代码库](./experiments.md#autonomous-workers)下载；解压后进入 `chapters/autonomous-workers/`，或在代码库根目录运行 `python3 run.py run R17`。

<!-- experiment-library:end -->

## 1. 领取以后，执行者拿到了什么？

[第 24 章](./task-system.md)把任务依赖、尝试次数与运行状态保存到了文件，但采用单执行者规则。本章建立独立 SQLite 小工程，集中验证多个进程共享任务所有权。它没有迁移第 24 章的 JSON 数据，也没有接入团队邮箱或图会话。

假设 A 在实验时间 100 秒领取 report，租约长度为 10 秒。它拿到的记录包含：

| 字段 | 首次领取后的值 | 回答的问题 |
| --- | --- | --- |
| id | report | 这是哪一项业务任务？ |
| state | running | 任务当前处于哪个阶段？ |
| owner | worker-a | 当前登记的执行者是谁？ |
| token | 1 | 这是这项任务的第几代领取？ |
| lease_until | 110 | 在哪个时刻开始允许接管？ |
| max_claims | 3 | 最多允许领取几次，包括首次领取？ |

`id` 在任务生命周期内不变，`token` 每次领取或接管都增加。租约是有截止时间的所有权：本例约定 **`now < lease_until` 时有效，恰好相等时已到期**。

![同一项任务先由 A 以代次 1 领取，到期后 B 以代次 2 接管；新旧领取具有不同凭证。](/learn-agent-rust/figures/r17-lease-takeover.svg)

按箭头读：100 秒首次领取，109 秒尚未到期，110 秒可接管。图中的时间和代次来自 restart-takeover 场景。接管改变当前凭证，任务 ID 保持不变；截止时间本身不会终止 A 的进程。

::: info 源码、输出和实验范围
正文片段直接导入 <a href="/learn-agent-rust/code/autonomous-workers/src/queue.rs" download>queue.rs</a>、<a href="/learn-agent-rust/code/autonomous-workers/src/main.rs" download>main.rs</a> 和 <a href="/learn-agent-rust/code/autonomous-workers/src/effects.rs" download>effects.rs</a>。完整 import、依赖锁文件和运行说明都在[学习包](/learn-agent-rust/autonomous-workers-lab.zip)中，也可查看 [GitHub 源码](https://github.com/lewislau86/lewislau86.github.io/tree/master/docs/public/learn-agent-rust/code/autonomous-workers)。

本次使用 Rust 1.99.1、rusqlite 0.37.0 与随其编译的 SQLite 3.50.2。实验真实访问本机数据库、启动独立进程；大部分时间值由测试注入，真实系统时钟入口另有核对。没有模型请求、多机数据库服务或常驻 worker。
:::

### 数据库保存哪些约束？

<<< @/public/learn-agent-rust/code/autonomous-workers/src/queue.rs#schema

pending 任务尚未领取，代次为 0，没有 owner 或截止时间；running 必须有正代次和租约；done 还必须有结果。完成后保留最后一份领取信息，便于检查结果来源。

任务 ID 是主键，本例没有删除或复用命令。代次按任务单调增加，不在不同任务之间比较；任务身份如果被删掉重建，旧凭证的解释就可能发生变化，需要额外的身份规则。

## 2. 两个进程同时来，如何只让一个领取？

先想象一个容易出错的顺序：A 查到 pending，B 也查到 pending；A 写 owner=a，B 再写 owner=b。最后数据库只有 B 的名字，但 A 可能已经在执行。这正是“最终只有一行”和“只有一个成功领取者”的区别。

本例把读取候选、更新 owner、增加 token、设置截止时间放在同一个 SQLite 写事务中：

<<< @/public/learn-agent-rust/code/autonomous-workers/src/queue.rs#transaction

`BEGIN IMMEDIATE` 在读取候选之前尝试取得写事务，竞争写者返回忙。具体事务语义见 [SQLite 事务文档](https://www.sqlite.org/lang_transaction.html)。`busy_timeout=0` 使本例立即返回 store_busy，由外层按预算决定是否重试；数据库事务没有覆盖报告生成过程。

真正的领取函数如下：

<<< @/public/learn-agent-rust/code/autonomous-workers/src/queue.rs#claim

候选有两类：从未执行的 pending，或者租约已到期的 running；还必须满足 token 小于 max_claims。候选按 ID 排序，只取一个。UPDATE 再检查一次这些条件，并要求影响行数为 1。

**成功提交后，调用方才开始业务动作。** 如果没有候选，返回 empty；如果没拿到写事务，返回 store_busy。empty 表示这次没有可领取项，既可能是队列为空，也可能是任务正在运行、已经完成或领取次数耗尽。

![四个进程竞争同一项任务，在原子写事务下只有一个领取成功，其余返回空或忙。](/learn-agent-rust/figures/r17-atomic-claim.svg)

沿箭头看，事务提交是业务动作的准入边界；图中的成功数和重试数来自四进程竞争记录。

### 用四个真实进程竞争

验证器先让四个进程都输出 ready，停在进入写事务之前；随后通过各自 stdin 放行。它检查四个 PID 确实不同，最终恰好一条 claimed，数据库 owner 与胜者一致、token=1。

<<< @/public/learn-agent-rust/outputs/r17-race-four.txt

上面的 race_verified 是验证器核对摘要。胜者名字，以及另三个进程得到 empty 还是 store_busy，由系统调度决定，因此只固定成功数和持久化结果。随后四个新进程各重试一次，都得到 empty，没有再次领取有效租约。

held-write-lock 场景另把一个进程停在“已更新、未提交”处：普通读取仍看到 pending，竞争写入返回忙；第一个进程提交后，下一次领取才看到有效租约。实验使用管道检查点组织顺序，没有用固定 sleep 猜测是否发生竞争。

## 3. 原执行者没退出，只是暂停了

A 领取后暂停很久，数据库不会知道它是退出、卡住还是暂时没有响应。租约给接管规定了时间边界，而 token 给旧结果规定了身份边界。

先看最简单的跨进程接管：

<<< @/public/learn-agent-rust/outputs/r17-restart-takeover.txt

每次 CLI 调用结束就是一次进程退出。新进程 B 在 109 秒仍领不到任务，110 秒接管成功并获得 token=2，随后可以完成。

### A 醒来后，用什么条件拒绝它？

提交完成结果必须同时满足：任务仍为 running、owner 相同、token 相同、租约仍有效。

<<< @/public/learn-agent-rust/code/autonomous-workers/src/queue.rs#complete

这里的 token 是代次凭证，也常被称为 fencing token：存储端检查代次，让过时执行者的写入无法覆盖当前任务记录。本例的保护范围就是这个 UPDATE；只有实际校验凭证的存储端才受保护。

stale-live-process 场景并非只在一个进程里修改变量。验证器启动一个携带 A 旧凭证的完成进程，让它停在写事务之前，保持存活；B 在到期时接管后，再放行 A。

<<< @/public/learn-agent-rust/outputs/r17-stale-live-process.txt

A 返回 lease_rejected。验证器还比较拒绝前后的完整任务行与 last_now，确认没有覆盖 B 的状态；最后 B 用 token=2 成功完成。

### 为什么只核对 owner 不够？

进程重启后仍可能叫 worker-a。如果同一个名字再次领取，新旧 owner 完全一样。本例 same-name 场景让 worker-a 在到期后拿到 token=2，再用 token=1 尝试完成和续租，两次均被拒绝。

![同名执行者的新旧领取靠代次区分；完成更新还必须检查状态与租约，任一条件不符都拒绝。](/learn-agent-rust/figures/r17-fenced-writes.svg)

左边是请求携带的身份，右边是任务当前状态。先比较 owner，再比较 token，最后检查状态与时间。即使名字相同，代次不相同仍会被拒绝；这不是用户认证，凭证由可信应用传入。

## 4. 工作还没做完，如何续租？

如果 A 能正常继续，它可以在到期之前请求延长租约：

<<< @/public/learn-agent-rust/code/autonomous-workers/src/queue.rs#renew

续租核对同一套身份与有效期，并要求新截止时间严格晚于旧值。它保留 token，表示仍是同一次领取；接管才增加代次。超过有效期后，即使暂时没有 B 接管，A 也不能迟到续租或完成。

<<< @/public/learn-agent-rust/outputs/r17-renewal.txt

A 在 100 秒领取到 110 秒，105 秒用 ttl=10 续到 115 秒。B 在旧截止时间 110 秒仍领不到，115 秒才接管。新截止时间按“本次 now + ttl”计算，而非在旧截止时间上累加。

late-renewal 还检查了迟到续租、缩短或重复截止时间、错误 owner；expiry-boundary 检查恰好到期时完成被拒绝。所有失败都回滚，不消耗新的领取代次。

本工程由调用者显式调用 renew，没有后台心跳线程。接入长期执行器时，应用需要安排续租，失去租约后停止后续动作，并处理已开始的动作结果；仅记录一个截止时间不会自动完成这些工作。

### 时间由谁说了算？

<<< @/public/learn-agent-rust/code/autonomous-workers/src/queue.rs#clock

传入 now 时，它是秒级逻辑时间夹具，让到期边界可以重现；省略或设为 null 时，在获得写事务之后读取主机 Unix 秒。领取、续租和完成各自检查时间，成功操作会保存 last_now，包括返回 empty 的扫描。

如果 now 比上次成功操作早，返回 clock_regression。本例选择拒绝回拨，直到时钟追上或由操作者处理；失败操作整体回滚，因此不会推进 last_now。主机时钟大幅前跳仍可能使租约提早到期，这个检查没有解决全部时钟问题。

system-clock 场景省略 now，验证领取和完成实际读到了主机调用前后范围内的秒数，截止时间等于本次秒数加 ttl。它是一次真实时钟核对，过期接管的边界仍由固定时间实验覆盖。生产入口应由可信存储或服务提供统一时间，不能让任意 worker 自报未来时刻。

## 5. 接管可以一直重试吗？

每次成功领取，包括接管，都消耗一次 max_claims。续租不会增加代次，完成后的任务不会重新领取。claim-budget 把上限设为 2：

<<< @/public/learn-agent-rust/outputs/r17-claim-budget.txt

两次租约都到期后，第三个执行者得到 empty。记录仍保留 running、最后 owner 和 token=2；它需要调用方检查并对账，而不是自动变成 done。本例没有另外引入失败状态或自动重试队列。

这项上限约束的是领取次数，不代表模型、工具、续租或整个运行的总预算。接回 Agent 驱动器时，仍需遵守[第 23 章](./error-recovery.md)的累计预算。本例按 ID 选择候选，也没有优先级、公平轮转或依赖图；这些是独立的调度策略。

| 教学限制 | 本例约定 |
| --- | --- |
| 保存任务数 | 最多 32 条，没有自动清理。 |
| max_claims | 1–8 次，首次领取包含在内。 |
| ttl | 1–3600 秒。 |
| 时间 | 0–4,000,000,000 Unix 秒，成功操作不倒退。 |
| 任务与执行者 ID | 最多 40 个 ASCII 字母、数字、下划线或短横线。 |
| 标题 / 结果 | 分别最多 160 / 512 个 UTF-8 字节。 |

## 6. 领取事务提交前后退出，会留下什么？

如果程序写入 owner 后、事务提交前退出，重启应看到未领取；如果已经提交、但返回确认前退出，重启应看到有效租约。不能仅凭非零退出码决定立即重试。

exit-before-commit 在更新后、提交前直接以 73 退出。新进程检查任务行和 last_now 都保持原值，重试获得 token=1。exit-after-commit 以 74 退出时，owner、token=1 和截止时间都已经保存；另一个进程当场重试得到 empty，到期后才能以 token=2 接管。

<<< @/public/learn-agent-rust/outputs/r17-exit-after-commit.txt

本例没有为“提交成功但确认丢失”增加领取请求去重身份，选择重新查询并等待租约边界。存储的进程退出恢复依据见 [SQLite 原子提交说明](https://www.sqlite.org/atomiccommit.html)；这次没有切断供电或模拟硬盘损坏。

## 7. 任务只允许一个当前 owner，报告也只生成一次吗？

现在把领取接上一项真实本地动作。work 命令领取 report，在**另一份 SQLite 文件**中写一份报告，然后把任务标记完成：

<<< @/public/learn-agent-rust/code/autonomous-workers/src/main.rs#worker

任务标题只是显示文本，程序没有把它当命令执行。业务动作是固定的本地服务夹具，单次 work 最多处理一项任务，没有自动轮询循环；真实时钟模式下完成前会重新采样时间，实验传入 now 时则复用同一夹具值。

让 A 在业务事务成功、任务完成更新之前退出。B 在租约到期后接管，再做同一件事：

<<< @/public/learn-agent-rust/outputs/r17-effect-replay.txt

业务库 calls 有两行、reports 也有两行；队列最终只有一个 done，最后 token=2。A 的业务事务已经提交，租约到期并不会撤回那份报告。

### 把去重放到实际产生业务结果的一端

保持同样的任务、领取时间和退出点，只改变业务服务的 dedupe 开关。服务用稳定身份 report:report 记录这项操作，去重键与报告在自己的事务内一起提交：

<<< @/public/learn-agent-rust/code/autonomous-workers/src/effects.rs#effect

身份采用 `report:<task_id>`，不带 token。否则每次接管都会得到新的业务身份，反而绕过去重。本例任务 ID 不删除、不复用，且同一业务库中的 ID 必须唯一；真实系统还要纳入业务范围、版本和参数一致性检查。

![相同的业务成功后退出窗口下，关闭去重产生两份报告，开启业务端稳定身份去重后仍调用两次但只产生一份。](/learn-agent-rust/figures/r17-effect-replay.svg)

两列只改变去重开关，最终任务代次都是 2。看清“调用次数”和“业务结果数”两行：开启去重仍发生两次调用，只在这个本地业务事务中保留一份报告。去重不是停止旧进程，也不校验它是否持有当前租约。

<<< @/public/learn-agent-rust/outputs/r17-effect-dedupe.txt

每次实验使用全新数据库并固定一种模式，混用开关不在协议内。这是两个本机数据库之间的重放实验，没有网络、真实外部服务或分布式事务。更完整的操作身份、参数冲突、Outbox 和对账见[专题 2：外部操作的可靠性](./side-effect-reliability.md)。

## 8. 动手实验与验证清单

解压学习包，进入 autonomous-workers-lab。README 提供完整的领取、续租、旧凭证拒写和业务重放命令。先用一套全新文件运行：

```sh
cargo test --locked
cargo run --locked -- tasks.db '{"op":"init"}'
cargo run --locked -- tasks.db '{"op":"add","id":"report","title":"整理日报","max_claims":3}'
cargo run --locked -- tasks.db '{"op":"claim","owner":"worker-a","now":100,"ttl":10}'
cargo run --locked -- tasks.db '{"op":"claim","owner":"worker-b","now":110,"ttl":10}'
cargo run --locked -- tasks.db '{"op":"complete","id":"report","owner":"worker-a","token":1,"now":111,"result":"旧结果"}'
cargo run --locked -- tasks.db '{"op":"complete","id":"report","owner":"worker-b","token":2,"now":111,"result":"已核对"}'
cargo run --locked -- tasks.db '{"op":"show"}'
```

旧凭证的完成命令故意返回退出码 1；继续执行下一行即可。首次编译需要下载固定依赖，运行实验只访问本地文件。

以下结果表由验证器生成。每轮 25 个场景，共 169 个独立 CLI 进程；12 个 Rust 单元测试与 Clippy 另计。验证器实际解压最终下载包，在另一个编译目标目录离线构建，并重跑全部场景。

<!-- r17-results:start -->

| 场景 | 独立 CLI 进程 | 拒绝 / 退出 / 核对摘要 |
| --- | --- | --- |
| `normal` | 7 | `lease_rejected` |
| `restart-takeover` | 6 | 通过 |
| `renewal` | 6 | 通过 |
| `expiry-boundary` | 5 | `lease_rejected` |
| `late-renewal` | 6 | `lease_rejected` |
| `stale-live-process` | 6 | `lease_rejected` |
| `same-name` | 7 | `lease_rejected` |
| `claim-budget` | 6 | 通过 |
| `selection` | 6 | 通过 |
| `empty` | 3 | 通过 |
| `clock-regression` | 6 | `clock_regression` |
| `invalid-input` | 13 | `invalid_command` / `invalid_credential` / `invalid_owner` / `invalid_result` / `invalid_task` / `invalid_time` / `invalid_ttl` / `lease_rejected` / `time_limit` |
| `duplicate-id` | 5 | `duplicate_id` |
| `task-limit` | 34 | `task_limit` |
| `rollback` | 4 | `injected_failure` |
| `exit-before-commit` | 5 | `exit=73` |
| `exit-after-commit` | 6 | `exit=74` |
| `held-write-lock` | 6 | `store_busy` |
| `race-four` | 10 | `race_verified` |
| `effect-replay` | 7 | `exit=75` |
| `effect-dedupe` | 7 | `exit=75` |
| `system-clock` | 4 | `system_clock_verified` |
| `corrupt-store` | 1 | `store_error` |
| `schema-version` | 2 | `schema_version` |
| `missing-store` | 1 | `store_error` |

<!-- r17-results:end -->

大部分输出文件包含 CLI 请求与 JSON 响应，键顺序和临时数据库路径经过归一化。process_exit 行由验证器依据真实退出码补录；竞争与系统时钟场景的末行是断言摘要，避免把不稳定的调度顺序或绝对时间当成固定输出。

仓库内复验：

```sh
python3 scripts/verify-agent-workers.py --check
python3 scripts/generate-learn-agent-rust-figures.py --lesson R17
npm run docs:build
```

源码摘要、场景断言和配图数据保存在 scripts/data/learn-agent-rust/r17-results.json。--check 会重新执行并检查学习包与记录是否过期。

## 参考原图：从任务板到自主执行者

![参考课程的自主执行者从任务板领取工作，结合身份和待机机制推进任务。](/learn-agent-rust/figures/upstream/r17-autonomous-agents-overview.svg)

这是原样保留的 Python/Claude 教学图，接口和计数沿用上游。先看“选择任务 → 领取 → 工作”的主线，再对照本章 Rust 实验的事务、代次与租约。图中的待机或消息机制不在本章独立存储实验中验收。[参考章节](https://learn.shareai.run/zh/s17/) · [原图](https://learn.shareai.run/course-assets/s17_autonomous_agents/autonomous-agents-overview.svg) · [来源与许可](./architecture.md#reference-assets)。

::: warning 常见误区
- 租约到期只是允许接管，旧进程可能仍在运行；失去所有权后停止动作，需要执行器和工具端配合。
- token 只有被实际写入端校验才有效。本例保护任务表，业务库没有凭证检查；任务元数据拒写无法撤回外部结果。
- owner 与注入 now 都来自可信调用方；本例没有身份认证、恶意 worker 防护或多机时钟协议。
- 本章独立队列没有集成第 24 章依赖图、第 26 章调度器、第 28 章邮箱协议、框架会话或真实模型。SQLite 文件适用于本机实验，不代表共享网络文件系统或多机运行验收通过。
:::

<!-- transfer-thinking:start -->

## 迁移思考：所有权必须在写入处生效

租约过期后旧 worker 醒来，应用层知道它过期就足够了吗？先给出你的判断，再展开下面的推演。

<details><summary>推演与应用</summary>

在实际写入位置校验递增代次，让新 owner 接管后旧代次提交被拒；调度时检查一次不够。

把所有权变成资源端可验证的条件，而非执行者自觉遵守的约定。

</details>

这是一道迁移练习，推演不代表新增实验已通过。对照[全书审查中的证据层次](./course-review.md#evidence-layers)，说明你的判断还需要哪一级证据。

<!-- transfer-thinking:end -->

## 本章结论：把领取权和写入权一起约束

本章用一个写事务决定谁成功领取，以执行者、代次和有效期约束后续续租与完成。租约给接管设置时间边界，代次让旧执行者的结果失效；有限领取次数保留故障现场，避免无限接管。

任务所有权与业务结果分别核对。队列内只有一份当前凭证，外部动作仍可能在退出后重放；稳定业务身份需要在真正产生结果的一端生效。

## 检查理解

1. 最后数据库只有一个 owner，为什么还不足以证明只有一个执行者开工？

   <details><summary>参考答案</summary>

   两个进程可能都先查到 pending，分别写入并开工，后写者覆盖了前写者。本例把选取与更新放在同一写事务，并要求领取提交成功后再执行动作，验证的是只有一个成功领取者。

   </details>

2. worker-a 重启后仍叫 worker-a，为什么还需要 token？

   <details><summary>参考答案</summary>

   同名执行者可能持有不同领取代次。只检查名字无法识别重启前的旧请求，token 单调增加可以区分新旧领取，完成和续租都必须匹配当前代次。

   </details>

3. 110 秒到期，A 在 110 秒续租，此时还没有 B 接管，可以允许吗？

   <details><summary>参考答案</summary>

   本例有效区间为 now 小于 lease_until，相等时已经失效。A 的迟到续租和完成都会被拒绝，即使 B 尚未接管。A 如果重新领取，也要获得新的代次并消耗一次额度。

   </details>

4. 返回 empty 是否代表所有任务都已完成？

   <details><summary>参考答案</summary>

   它只表示本次没有可领取候选。队列为空、有效租约仍在运行、任务已完成、领取次数耗尽都可能返回 empty。需要检查任务状态、截止时间与 token/max_claims 才能决定下一步。

   </details>

5. 把 token 放进业务去重键，能否避免接管后的重复报告？

   <details><summary>参考答案</summary>

   接管会增加 token，带代次的去重键也会变化，从而被识别为另一项操作。本例业务身份是稳定的 report:task_id；token 负责识别执行代次，业务幂等键负责识别同一业务意图。

   </details>

## 参考资料

- [SQLite 事务与 BEGIN IMMEDIATE](https://www.sqlite.org/lang_transaction.html)、[原子提交与恢复](https://www.sqlite.org/atomiccommit.html)。
- [rusqlite 0.37.0 TransactionBehavior](https://docs.rs/rusqlite/0.37.0/rusqlite/enum.TransactionBehavior.html)。
- [本章学习包](/learn-agent-rust/autonomous-workers-lab.zip)：固定依赖、完整代码、输出和源码摘要。
- [专题 1：PostgreSQL 检查点](./postgres-checkpoints.md)、[专题 2：外部操作的可靠性](./side-effect-reliability.md)：分别讨论会话快照与业务操作恢复。

接下来阅读[第 30 章：工作区隔离](./worktree-isolation.md)，让并发代码任务拥有明确的文件与变更归属。
