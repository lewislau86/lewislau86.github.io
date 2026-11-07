---
title: "第 13 章：后台任务"
description: "用有界线程、任务句柄、协作取消和完成通知，让慢工具拥有可查询、可回收的生命周期。"
pageClass: learn-agent-rust-course
---

# 第 13 章：后台任务

[课程总览](./index.md) · [上一章：持久化任务系统](./task-system.md) · [下一章：定时调度](./scheduling.md)

::: tip 本章学习目标
- 解释一次后台启动返回的句柄与业务任务 ID 各自负责什么。
- 实现有并发上限、可查询、可取消的后台执行，并正确处理取消与完成竞争。
- 验证成功、失败、通知溢出和退出时的线程与文件回收。

**前置：** [R12 持久化任务系统](./task-system.md)的业务身份与执行状态概念，以及 [R06 子任务](./subagents.md)的线程归属、[R11 错误恢复](./error-recovery.md)的副作用边界。本章实验提供独立运行所需的全部代码。

**实践方式：** <a href="/learn-agent-rust/background-tasks-lab.zip" download>下载独立 Rust 实验包</a>。最低 Rust 1.85，edition 2024，仅用标准库；无需密钥、网络或数据库。
:::

用户让助手导出一份报告。导出还在写文件，用户又问“现在做到哪一步了？”如果启动报告的函数一直等到写完才返回，当前循环就无法受理这个查询。

我们把导出交给后台线程，让启动函数先返回 `job_id`。但这只解决了一半问题：谁保管线程句柄？用户取消后，半份报告怎么办？程序关闭时，线程是否还在写？本章沿着一份报告的生成过程，把这些问题逐个补齐。

<LearnAgentRustMap active="background-tasks" />

## 1. 先分清：业务任务、执行句柄与工具调用

上一章计划解决“这项工作在重启后还记得吗”。本章解决“这次工作正在由谁执行”。例如业务任务 `report-2026` 可以有多次执行尝试；本次进程中的 `job_id=1` 只指向其中一次后台执行。

| 身份 | 解决的问题 | 本章存放位置 |
| --- | --- | --- |
| 业务任务 ID | 用户希望完成哪项工作，依赖谁，完成条件是什么？ | R12 的职责；本实验未接入持久化任务库。 |
| 后台 `job_id` | 当前管理器中的哪次执行，可查询或取消哪一个 worker？ | 管理器内存中的递增整数。 |
| `JoinHandle` | 哪个 Rust 值负责等待线程退出？ | 管理器私有 `jobs` 表。 |
| 工具 `call_id` | 哪条模型工具请求对应哪条工具回复？ | R01–R02 的消息协议；本实验没有模型消息。 |

`job_id` 可以放进结构化的启动回复，真正的 `JoinHandle` 留在宿主程序中。Rust 的句柄代表等待线程的所有权，不能复制成两份交给不同节点。丢弃它会让线程脱离等待关系，所以管理器必须持有它直到 `join`。

![前台只拿到任务 ID，管理器拥有执行句柄并在收集后发布终态与通知。](/learn-agent-rust/figures/r13-handle-ownership.svg)

读图时沿着蓝色启动路径走：前台得到的是 ID。沿着青色完成路径返回时，先收集线程，再更新状态，最后发通知。右侧的业务任务库是后续接线位置，本实验的执行记录全部留在进程内。

将来接回 Agent 循环时，启动工具可返回“已受理，`job_id=1`”，随后独立的查询工具返回当前快照。启动请求只产生一次工具回复；完成通知作为宿主事件在下一轮边界加入上下文。这个消息接线是本章给出的设计映射，下面实验验证执行管理器本身。

## 2. 用一份三段报告观察后台执行

实验工具依次写入三行：`chunk=1`、`chunk=2`、`chunk=3`。写入过程中使用 `job-1.part`；全部写完才重命名为 `job-1.txt`，向前台发布完整结果。

先预测：只允许第一段写入后，目录里会出现最终报告吗？线程执行了真实文件 I/O，但它还没得到完成后两段的许可，所以此时只有半成品。

::: info 代码只有一个来源
以下 Rust 代码直接引用 <a href="/learn-agent-rust/code/background-tasks.rs" download>完整源码</a>；运行说明见 <a href="/learn-agent-rust/code/background-tasks-README.md" download>README</a>，也可在 [GitHub 查看源码](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/learn-agent-rust/code/background-tasks.rs)。输出同样从实际运行记录导入，完整实验包包含源码、14 个场景输出和校验记录。
:::

解压下载包，在目录中执行：

```sh
rustc --edition=2024 -D warnings background-tasks.rs -o background
./background normal
```

<<< @/public/learn-agent-rust/outputs/r13-normal.txt

启动后可以立即查询 `Running`。前台继续执行固定的后续步骤，观察一段写入，再放行剩余两段；收集线程后才得到 `Completed` 和通知 `[1]`。最后的 `started=1 joined=1 active=0` 是管理器计数，验证脚本还会从进程外读取实际报告，核对三行内容。

这里使用真实 OS 线程和真实磁盘文件。为稳定观察中间状态，`Condvar` 配合 `permits` 控制每段何时继续，代替依赖电脑快慢的 `sleep`。它是**实验控制门**：实际导出任务可以换成逐块编码或分页读取，并在块之间保留取消检查。前台由确定性脚本驱动，未调用真实模型，也没有测量延迟或吞吐量。

### 状态与线程分别由谁持有

<<< @/public/learn-agent-rust/code/background-tasks.rs#ownership

`states` 是可查询快照，`jobs` 保存仍未回收的线程。worker 共享的 `Gate` 只存检查点与取消条件，前台通过管理器查询状态，避免多个线程分别宣布终态。

`CancelRequested` 表示管理器接受了取消请求。终态 `Completed`、`Cancelled`、`Failed` 则由管理器收集线程后写入。`query` 返回最近一次收集的快照，宿主应在事件循环边界调用 `poll`，再处理查询和下一轮模型请求。

## 3. “有界”从创建线程之前开始

如果每收到一次请求就创建一个线程，后台执行会把前台等待转变成资源膨胀。本实验同时限制三类资源：

| 资源 | 实验上限 | 达到上限时的行为 |
| --- | --- | --- |
| 未回收的 worker | 2 | 启动返回 `capacity`，不创建新线程、不排队。 |
| 已结束的记录与报告 | 最近 4 条 | 淘汰最早的记录，并尝试删除对应报告。 |
| 完成通知缓冲 | 1 条 ID | 通知丢弃计数增加，终态仍可查询。 |

上限来自本章程序配置，不是性能建议。报告每份固定三行；业务中的输出大小、单次 I/O 和远端连接还需要各自的限制。

<<< @/public/learn-agent-rust/code/background-tasks.rs#start

先 `poll` 回收已结束线程，再检查槽位，最后才 `spawn`。线程创建失败会返回 `spawn_failed`，成功后管理器保存句柄并返回 ID。ID 可以出现空号，当前管理器不会重用旧 ID。

运行 `./background capacity`：

<<< @/public/learn-agent-rust/outputs/r13-capacity.txt

两个线程都到达等待点时，第三次启动被拒绝。第一个执行完成并被回收后，新执行得到 `replacement_id=3`。场景结束时关闭管理器，另外两个线程被取消，所以最终只留下第一个完整报告。

这里选择满载直接拒绝。调用者可显示“稍后重试”，或由上层实现有上限的等待策略；本章没有等待队列和公平调度实现。

## 4. 取消先是一条请求，再是一个结果

用户看到一段报告已写出，决定取消。最容易犯的错误是把状态直接改成 `Cancelled`，然后返回：文件可能还在写，线程也可能仍然占用资源。

正确顺序是设置取消条件、唤醒线程、等待线程在检查点退出，最后收集并宣布终态。

<<< @/public/learn-agent-rust/code/background-tasks.rs#cancel

`Accepted` 说明请求已经记录；`AlreadyRequested` 说明已有请求；`TooLate` 说明结果已发布或执行已经结束；`Unknown` 说明当前管理器里没有这个 ID。重复取消不会创建另一个执行，也不会发布第二份终态。

worker 每写一小段前检查取消，最后发布前再检查一次：

<<< @/public/learn-agent-rust/code/background-tasks.rs#worker

条件变量醒来后重新检查条件，避免把一次唤醒误当成继续写入的许可。小块写入和取消检查共用互斥锁，取消可能等待当前这一小块 I/O 结束。`Partial` 的析构负责删除半成品；成功时半成品已经改名，析构不会删掉最终报告。

### 取消与发布相遇时，谁算赢

![取消与最终文件发布使用同一互斥锁，取消先获得锁会清理半成品，发布先获得锁则保留完整报告。](/learn-agent-rust/figures/r13-cancel-publication.svg)

这张图比较两种受控顺序。橙色路径中，取消条件先写入，worker 最终返回 `Cancelled`；青色路径中，报告已经发布，后来的取消返回 `TooLate`。两种结果都由实际测试验证，图中不暗示取消总能优先。

运行 `./background cancel`，第一段写入后发送取消：

<<< @/public/learn-agent-rust/outputs/r13-cancel.txt

此时半成品和最终文件都为零。再运行 `./background late-cancel`：

<<< @/public/learn-agent-rust/outputs/r13-late-cancel.txt

完整报告保留下来。取消与 `rename` 的决定在同一把锁内，程序不会一边回复“取消已受理”，一边越过检查点继续发布成功文件。

取消仍有边界：如果 worker 已失败退出但宿主尚未收集，请求与失败也可能交错，最终按实际线程结果记录 `Failed`。协作请求的接受本身不承诺终态一定是 `Cancelled`。本实验没有强杀线程，也没有撤销远端写入的机制。

## 5. 通知负责提醒，状态负责回答

后台完成后，宿主需要知道“有结果可以看了”。可以用通知减少无效轮询，但通知消费者可能暂时忙于模型请求，不能让它拖住线程回收。

<<< @/public/learn-agent-rust/code/background-tasks.rs#collect

日常 `poll` 只挑 `is_finished()` 的线程，再执行 `join`。显式 `join_one` 也用于实验等待；实际前台请求不应随意等待仍在运行的句柄。终态写入之后，管理器用 `try_send` 尝试投递 ID，缓冲满时只增加丢弃计数。

运行 `./background notifications`，让两个任务先后完成，期间暂不消费通知：

<<< @/public/learn-agent-rust/outputs/r13-notifications.txt

通知只有 `[1]`，但查询 1、2 都得到 `Completed`，两份报告也都存在。宿主消费通知后应按 ID 查询当前状态，并在每轮边界收集终态；这样即使通知溢出，也能从状态中获得结果。

![两个执行都完成并留下报告，容量为一的通知队列只保留一个提醒，查询仍能看到两个终态。](/learn-agent-rust/figures/r13-notification-results.svg)

读图时对比“通知收到”和“可查询完成”两列：少一条提醒不代表少完成一项工作。本实验最多保留最近四条终态；过期 ID 查询返回 `None`，通知也可能指向已淘汰记录。需要长期结果时，应在淘汰前将业务事实交给持久化存储。

这也说明后台工具结果应有大小上限：通知仅传 ID，实际内容由查询或读取结果接口按需取得，避免把大段日志一次塞进模型上下文。

## 6. 退出要关闭入口、唤醒并等待

关闭程序时，先停止接收新后台请求，再对仍在运行的任务发取消，最后等待所有线程退出。

<<< @/public/learn-agent-rust/code/background-tasks.rs#shutdown

这里先向所有 worker 发请求，再逐个 `join`，让各线程都有机会退出。`Drop for Manager` 也调用同一条清理路径；重复 `shutdown` 不会重复回收。实验的 `Workspace` 在管理器之后销毁，先结束写入，再清理目录。

运行 `./background shutdown`，一个线程已经写过一段，另一个仍在等待：

<<< @/public/learn-agent-rust/outputs/r13-shutdown.txt

两个线程都回收后，`active=0`，半成品为零。`closed` 场景额外核对关闭后启动被拒绝；`drop` 场景通过离开管理器作用域触发相同清理。

清理依赖 worker 能在检查点响应取消。本实验没有关闭超时；如果把 worker 改成无法中断的系统调用，`join` 就可能一直等待。执行外部命令需要拥有子进程句柄、终止与等待策略，并另外验证进程树的归属；线程示例的结论只覆盖这里的固定文件工具。

### worker 失败怎么办

`failure` 在第一段后返回注入错误，`panic` 在同一位置触发 panic。两者都在管理器中记为 `Failed`，并通过 `join` 释放槽位。Rust 默认的 panic unwind 会执行局部值析构，实验因此还检查了 panic 后半成品被删除。

这个精简管理器只公开失败状态；业务接线时可把 R11 的类型化错误和有上限的诊断信息保存到任务记录。`panic=abort`、进程被强杀和断电不会走这里的析构清理，需要在新的持久化恢复实验中处理。

## 7. 动手实验：从状态计数核对真实文件

先运行回归测试，再尝试保留输出目录：

```sh
rustc --edition=2024 -D warnings --test background-tasks.rs -o background-tests
./background-tests
./background normal ./inspect-normal
./background cancel ./inspect-cancel
```

两个目录都必须尚不存在。第一个目录里应有 `job-1.txt`，内容为三行；第二个目录应为空。目录由你指定时会保留，方便检查；不指定时自动创建并清理临时目录。

**本章验证记录：** 本地使用 `rustc 1.99.1 (58cf8f9c3 2026-10-13)`，通过 12 个 Rust 测试和以下 14 个 CLI 场景，并已使用 Rust 1.85.0 重跑核对；故障与检查点由程序控制，线程、文件写入、重命名与清理均真实执行。`repeat-cancel` 验证重复请求可以得到“已请求”或“已结束”，终态与结果不会重复。测试还分别固定“取消先到”和“发布先到”两个顺序。

| 场景 | 启动线程 | 回收线程 | 丢弃通知 | 完整报告 |
| --- | --- | --- | --- | --- |
| `normal` | 1 | 1 | 0 | 1 |
| `cancel` | 1 | 1 | 0 | 0 |
| `cancel-before-work` | 1 | 1 | 0 | 0 |
| `late-cancel` | 1 | 1 | 0 | 1 |
| `repeat-cancel` | 1 | 1 | 0 | 0 |
| `capacity` | 3 | 3 | 2 | 1 |
| `failure` | 1 | 1 | 0 | 0 |
| `panic` | 1 | 1 | 0 | 0 |
| `notifications` | 2 | 2 | 1 | 2 |
| `unknown` | 0 | 0 | 0 | 0 |
| `shutdown` | 2 | 2 | 1 | 0 |
| `history` | 6 | 6 | 0 | 4 |
| `closed` | 0 | 0 | 0 | 0 |

第 14 个场景 `drop` 不读取已销毁的管理器计数，而是从外部核对作用域退出后目录为空；Rust 测试同时检查析构返回时文件已经清理。`history` 启动六次后只保留最近四条终态和四份报告，旧 ID 不复用。所有场景结束后的半成品都为零。

在网站仓库中执行下面命令可重新生成记录与下载包；`--check` 会复验已保存产物，并从最终下载包解压编译、再次核对全部场景：

```sh
python3 scripts/verify-agent-background.py
python3 scripts/verify-agent-background.py --check
python3 scripts/generate-learn-agent-rust-figures.py --lesson R13
```

验证脚本会读取实际文件内容、核对表中计数、检查现有目录不被覆盖、确认默认临时目录自动清理。证据包含源文件 SHA-256，配图生成器遇到过期证据会拒绝生成。

## 8. 放回课程架构与参考原图

在课程目标架构中，后台管理器属于宿主执行层：模型请求启动、查询或取消；应用先应用 R03 的执行策略，再调用固定工具。图节点可以把 `job_id` 写进可序列化状态，运行时持有管理器与真实句柄，在轮次边界收集事件。这个接线还需要在 R20 中单独验收。

R12 的业务任务可以记录“本次执行关联哪个后台 ID”，但进程重启后旧线程已不存在。重启应先核对业务状态和实际产物，再决定是否重新执行；恢复时直接把旧 ID 当成活线程会出错。本章只验证单进程执行生命周期。

以下保留图来自参考课程的 Python/Claude 教学实现，接口、编号与数量均沿用原图：

![参考课程将慢工具放入后台线程，并在后续轮次注入完成通知。](/learn-agent-rust/figures/upstream/r13-background-tasks-overview.svg)

图源：[参考章节](https://learn.shareai.run/zh/s13/) · [原图](https://learn.shareai.run/course-assets/s13_background_tasks/background-tasks-overview.svg)。关注启动、查询和通知的连接。本章 Rust 实验进一步明确并发准入、取消与发布的竞争、句柄所有权及退出等待；实际验证范围以本章记录为准。来源版本与许可见[参考资料说明](./architecture.md#reference-assets)。

::: warning 常见误区
- 丢弃 `JoinHandle` 会脱离等待关系；管理器应持有并回收线程。
- “取消已受理”只表示请求已记录；完成回收后才能根据实际执行结果宣布终态。
- 把慢工具移到后台仍需执行权限判断。这个实验只运行固定文件工具，没有任意 shell 命令入口。
- 通知是提醒，可查询快照也有保留期限；长期业务事实需要持久化存储。
- 本地文件的受控取消与清理实验，不能推导出任意阻塞 I/O、外部进程或远端副作用都能被撤销。
- 清理删除使用尽力而为策略；实验在正常临时文件系统中验证成功，未模拟删除失败或验证断电持久性。
:::

## 本章结论：让后台执行有明确的主人

本章选择进程内管理器持有全部线程句柄，在创建前限制并发，以 ID 提供查询与取消；worker 在小块操作之间响应取消，管理器在收集后写终态，再发送有界通知。退出时关闭准入、取消并等待，完整结果与半成品分别处理。

这套机制解决的是一次运行里的慢工具生命周期。业务任务如何重启恢复属于 R12；何时自动触发、错过时间如何补偿，交给下一章。

## 检查理解

1. 把 `JoinHandle` 序列化进 R12 的任务文件，重启后继续查询，可以吗？

   <details><summary>参考答案</summary>

   句柄是当前进程等待某个线程的所有权，无法恢复成另一个进程中的活线程。可以持久化业务任务 ID、执行尝试与结果事实；重启后需要核对并重新建立执行状态。本章 `job_id` 也只在所属管理器内有效。

   </details>

2. 第一段已写入时调用取消，为什么不立即返回 `Cancelled`？

   <details><summary>参考答案</summary>

   请求只设置取消条件并唤醒 worker。worker 还要停止后续操作、关闭文件并清理半成品；管理器 `join` 后才写实际终态。请求到达前若执行已失败，终态也可能是 `Failed`。

   </details>

3. 报告已发布，管理器还没 `poll`，快照仍是 `Running`，这时能接受取消吗？

   <details><summary>参考答案</summary>

   实验还会在与发布共用的互斥锁内检查 `published`。一旦发布成功，取消返回 `TooLate`，不会把完整结果宣布成已取消。随后收集线程，快照更新为 `Completed`。

   </details>

4. 两个任务都成功，但只收到一条通知，是否要重新启动另一个任务？

   <details><summary>参考答案</summary>

   先查询当前状态。通知缓冲容量为一，第二条提醒可以丢弃，但两个终态和报告仍可存在。盲目重新启动会造成重复工作；超过历史保留期后，应由持久化记录判断业务结果。

   </details>

5. `shutdown` 能保证五秒内结束吗？

   <details><summary>参考答案</summary>

   本实现没有关闭截止时间，依赖固定 worker 在检查点响应取消。测试中五秒是等待观察结果的保护上限，不是关闭时限。对不可中断 I/O 或外部进程，需要另外设计和验证超时、终止、等待与未完成状态处理。

   </details>

## 参考资料

- [Rust `JoinHandle`：等待所有权、丢弃行为与线程完成](https://doc.rust-lang.org/std/thread/struct.JoinHandle.html)。
- [Rust `Condvar`：在互斥锁保护下检查条件](https://doc.rust-lang.org/std/sync/struct.Condvar.html)。
- [Rust `sync_channel`：有界缓冲](https://doc.rust-lang.org/std/sync/mpsc/fn.sync_channel.html)与 [`try_send`](https://doc.rust-lang.org/std/sync/mpsc/struct.SyncSender.html#method.try_send)。
- [Learn Claude Code · Background Tasks](https://learn.shareai.run/zh/s13/)，通用机制参考，原图按上游语境保留。
- <a href="/learn-agent-rust/code/background-tasks.rs" download>本章完整源码</a> · <a href="/learn-agent-rust/code/background-tasks-README.md" download>运行说明</a> · <a href="/learn-agent-rust/background-tasks-lab.zip" download>独立实验包</a>。

下一章：[第 14 章：定时调度](./scheduling.md)。有了后台执行的生命周期，再讨论一次定时触发怎样生成可追踪、可恢复的执行请求。
