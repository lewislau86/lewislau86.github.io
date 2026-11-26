---
title: "第 30 章：LiveNode 与 AsyncRunner：核心线程上的事件循环"
description: 实盘节点怎样把异步 I/O 的消息送回核心线程：7 对无界 channel 和它们的优先级、防止饿死的两个标记、每 64 次派发让出一次；发送端为什么放在线程局部变量里；run 的启动顺序（先连数据、再连执行、对账、再启动 Trader）；维护计时器上的对账与清理；停止时的宽限期与断开顺序。
---

# 第 30 章：LiveNode 与 AsyncRunner：核心线程上的事件循环

[全书目录](./index.md) · [上一章](./tokio-runtime.md) · [下一章](./task-management.md)

::: tip 本章学习目标
能说出事件循环里 7 个 channel 各装什么消息、按什么优先级取出，以及为什么计时器和行情不会把其他消息饿死；能解释适配器从哪里拿到发送端；能按顺序说出 `LiveNode::run` 的启动步骤，知道为什么数据客户端要先于执行客户端连接；能说出停止时的宽限期、断开超时各起什么作用；能沿着 channel 追踪一条报价和一张订单在实盘里的路径。

**源码版本：** `develop` 分支，提交 `364254f`（2026-11-18）。节点在 `crates/live/src/node/mod.rs`（模块文档、`run_with_mode`、`initiate_shutdown`、`finalize_stop`），配置在 `node/config.rs`，节点状态在 `node/state.rs`，`AsyncRunner` 和派发函数在 `crates/live/src/runner.rs`，线程局部的发送端在 `crates/common/src/runner.rs` 和 `crates/common/src/live/runner.rs`。

**对应官方文档：** [Live Trading](https://nautilustrader.io/docs/latest/concepts/live/) · [Architecture](https://nautilustrader.io/docs/latest/concepts/architecture/)
:::

第 29 章说，节点的引擎和策略跑在一个核心线程上，适配器的 I/O 跑在 Tokio 工作线程上，两边用 channel 通信。这一章看核心线程上的那个事件循环：它从哪些 channel 取消息、按什么顺序取、启动和停止时做什么。第 14 章讲过内核的 `start` 和 `start_trader` 分两步，那一章留下的“实盘节点在两步之间做什么”，答案也在这里。

主线例子：一个接入 OKX 的节点，一个策略订阅 `ETH-USDT-SWAP.OKX` 的报价，在 `on_quote` 里下一张限价单。

## 1. 七对 channel {#channels}

`AsyncRunner::new()` 创建 7 对 Tokio 无界 channel，外加一对用于停止信号：

| channel | 装什么 | 谁发 |
| --- | --- | --- |
| 时间事件 | 实时计时器到点的事件 | 计时器任务（第 32 章） |
| 系统事件 | 套接字状态变化等 | 网络层 |
| 系统命令 | 套接字重连等 | 网络层、组件 |
| 执行事件 | 订单事件、执行报告、账户状态 | 执行客户端 |
| 交易命令 | 提交、改单、撤单 | 策略、风控、执行引擎 |
| 数据事件 | 行情、品种定义、请求响应 | 数据客户端 |
| 数据命令 | 订阅、退订、请求 | 策略、数据引擎 |

都是**无界**的：发送永远不会阻塞，代价是消费者跟不上时队列会一直变长。节点为此提供了队列监控（第 5 节）。

发送端被装进**线程局部变量**。节点启动时调用 `bind_senders_for_node`，把每个发送端用 `replace_*_sender` 写到当前线程（核心线程）的线程局部存储里。适配器的客户端在核心线程上创建、连接，这时用 `get_data_event_sender()`、`get_exec_event_sender()` 取一份发送端的克隆，再带进它 spawn 到 Tokio 上的后台任务里。所以后台任务不需要知道节点在哪里，它只管往 channel 里发。命令一侧也是这样：策略下单最终调用线程局部的 `TradingCommandSender`，它把命令包成 `DispatchMessage` 发进交易命令 channel，并记下发送它的线程 ID。

这也解释了第 15 章的 `queue_execute`：风控引擎放行的命令不是立即交给执行引擎，而是经这个发送端排进 channel，等事件循环的下一轮再处理，避免在策略回调还没返回时重入执行引擎。

## 2. 事件循环怎样取消息 {#select}

`LiveNode::run` 进入运行阶段后，是一个 `tokio::select!` 循环，`biased` 表示按书写顺序检查分支，前面的优先。分支依次是：

1. `SIGINT`、`SIGTERM` 信号；
2. 停止检查计时器（每 100 毫秒）：外部通过 `LiveNodeHandle` 请求停止，或内核收到 `ShutdownSystem` 命令时，开始关闭；
3. 关闭阶段的截止时间到了，退出循环；
4. 有待派发的回调；
5. 维护计时器（每 100 毫秒，第 4 节）；
6. 时间事件、系统事件、系统命令、执行事件、交易命令；
7. 外部消息总线的入站消息（第 36 章）；
8. 数据事件、数据命令。

固定优先级有一个问题：如果计时器非常密集，或者行情源源不断，排在后面的消息就永远轮不到。循环用两个标记防止这种情况：

- `skip_time`：处理了一个时间事件后置为真。之后只有在数据事件和数据命令的 channel 都空时，才再取时间事件；处理了其他任何消息后复位。
- `skip_data`：处理了一个数据事件后置为真。之后只要数据命令 channel 不空，就先处理数据命令；处理了数据命令后复位。

另外，每派发 64 条消息（`DISPATCHES_PER_YIELD`），循环主动 `yield_now` 一次，把执行权还给 Tokio，让同一线程上的其他 future（比如对账的报告请求）有机会推进。

主线例子里，一条报价在工作线程上被 OKX 的 WebSocket 任务解析成 `QuoteTick`，发进数据事件 channel。核心线程取出它，交给 `DataEngine`，写缓存、发布，策略的 `on_quote` 被调用（第 18 章）。策略下的限价单经风控、`queue_execute` 进入交易命令 channel；下一轮循环取出它，交给执行引擎，执行引擎调用 OKX 执行客户端的 `submit_order`，客户端在 Tokio 上发起 HTTP 请求并立即返回。几毫秒后交易所的确认通过执行事件 channel 回来，交给 `ExecEngine.process`（第 20 章）。执行事件排在行情前面，所以即使行情很密集，订单回报也会先被处理。

## 3. 启动顺序 {#startup}

`run` 在进入上面的循环之前，有一段较长的启动过程：

1. 准备缓存：有数据库后端时安装并加载（第 36 章）。
2. 把发送端绑定到当前线程，节点状态变为 `Starting`。
3. 内核 `start_async`：启动三大引擎和客户端对象（第 14 章的 `start`）。
4. **连接数据客户端。** 期间到达的消息先缓存在一个 `PendingEvents` 里，不派发。连接完成后，把所有数据事件和数据命令灌进缓存：品种定义先于订阅命令处理，否则订阅会因为找不到品种被数据引擎拒绝。
5. **连接执行客户端。** 这时品种已经在缓存里，执行客户端初始化时能找到它们。
6. 处理连接期间积压的其他消息。
7. **启动对账**（第 34 章）：拿交易所的订单、成交、仓位报告和本地缓存比对，补齐差异。
8. **启动 Trader**（内核的 `start_trader`）：策略的 `on_start` 在这里被调用。
9. 进入运行阶段的循环。

所有连接共用一个截止时间 `timeout_connection`（默认 60 秒）。任何一步失败或超时，节点都会走中止流程：停掉已经启动的部分，断开客户端，清空 channel，然后返回错误。

第 3 步和第 8 步之间的第 4 到第 7 步，正是第 14 章说的“实盘节点在 `start` 和 `start_trader` 之间做的事”。把策略的 `on_start` 放在对账之后，是为了让策略启动时看到的订单和仓位已经和交易所一致。

## 4. 维护计时器 {#maintenance}

运行阶段有一个每 100 毫秒醒一次的维护计时器，它负责六件周期性的事：

- 对账（在途订单、未结订单、仓位三种检查，第 34 章）；
- 清理已关闭的订单、已平的仓位、账户事件（第 20 章第 7 节的 `purge_*` 配置）；
- 自有订单簿审计；
- 每分钟一次的近期成交缓存清理。

每件事有自己的间隔和下次触发时间，维护计时器每次醒来只执行到期的那些。所以 100 毫秒是任何维护间隔的下限：配置成 50 毫秒的在途检查，实际也是每 100 毫秒左右执行一次。对账在节点启动后还要再等 `reconciliation_startup_delay_secs`，第一次周期检查才开始。

维护计时器每次醒来还会记录各个 channel 的队列长度，配置了 `queue_monitor` 时据此判断是否积压，并发布状态变化。

## 5. 停止 {#shutdown}

停止的触发方式有四种：`SIGINT`、`SIGTERM`、`LiveNodeHandle::stop()`（可以从别的线程调用）、内核收到 `ShutdownSystem`（比如第 14 章的 `shutdown_on_error`）。它们都进入 `initiate_shutdown`：

1. 停止 Trader：策略的 `on_stop` 被调用，可能发出撤单和平仓命令；
2. 设一个截止时间 `now + delay_post_stop`（默认 10 秒），节点状态变为 `ShuttingDown`。

在这 10 秒宽限期里，事件循环照常运行，处理撤单、平仓的回报（日志里称为“残余事件”）。截止时间一到，退出循环，进入 `finalize_stop`：

1. 记下还没有结果的提交（第 34 章的“结果未知”的命令）；
2. 关闭外部消息总线入站；
3. **并行**地收尾对账报告任务和断开所有客户端，各自最多等 `timeout_disconnection`（默认 10 秒）；
4. 等引擎确认断开，再调用内核的 `finalize_stop`（保存状态、停止引擎、封存事件存储，第 14 章）；
5. 节点状态变为 `Stopped`。如果有未解决的提交、断开失败或超时，把它们汇总成一个错误返回。

节点状态一共五个：`Idle`、`Starting`、`Running`、`ShuttingDown`、`Stopped`。第 9 章说的“只能在节点运行前添加策略”，判断依据就是状态是否为 `Idle`。

![实盘节点的事件循环：左边是 Tokio 工作线程上的客户端任务和计时器，经 7 个 channel 把消息送到核心线程；核心线程上的 select 循环按信号、停止检查、维护计时器、时间事件、系统事件与命令、执行事件、交易命令、外部消息、数据事件、数据命令的顺序取消息，交给各引擎；下方是启动的九个步骤和停止的宽限期](/nautilus-trader/figures/live-node-loop.svg)

怎么读这张图：中间一列是 `select!` 的分支，从上到下优先级递减；右边是每类消息交给谁。底部一行是启动顺序，注意数据客户端在执行客户端之前，对账在 Trader 之前。

## 6. 动手验证 {#lab}

不接任何交易所，也能把一个 `LiveNode` 跑起来：没有客户端，连接和对账几步瞬间完成，事件循环、Trader、计时器照常工作。实验在节点上挂一个 Actor，启动时设一个 400 毫秒的计时器；另开一个线程，1 秒后调用 `LiveNodeHandle::stop()`；每个回调都记下时间和所在线程的名字。

::: info 实验环境
Linux（aarch64，4 核、3 GB 内存）上的 Rust 1.100.0，NautilusTrader 各 crate 来自提交 `364254f`。代码是 <a href="/nautilus-trader/code/live-lab/examples/ch30_live_node.rs" download><code>ch30_live_node.rs</code></a>，属于第五部分的实验工程 `live-lab`（[在 GitHub 查看](https://github.com/lewislau86/lewislau86.github.io/tree/master/docs/public/nautilus-trader/code/live-lab)，`README.md` 写了运行方法）。运行命令是 `cargo run --example ch30_live_node`。下面的输出原样摘录，毫秒数每次运行略有不同。
:::

Actor 只记录，不做别的事：

<<< @/public/nautilus-trader/code/live-lab/examples/ch30_live_node.rs#actor

节点用 `get_runtime().block_on(node.run())` 在主线程上运行，这正是 Python 绑定的做法（第 29 章第 4 节）。同一个线程上还试着建第二个节点：

<<< @/public/nautilus-trader/code/live-lab/examples/ch30_live_node.rs#run

`delay_post_stop` 为 0 时的完整输出：

```text
== 0
delay_post_stop = 0ns
second node on the same thread: A LiveNode already exists or is being built on this thread; drop it before building another
      32.7 ms  run() called [thread main]
      33.6 ms  on_start [thread main]
      33.7 ms  threads now: ch30_live_node ×1, logging ×1, stopper ×1, tokio-rt-worker ×4 [thread main]
     437.5 ms  on_time_event #1 (tick) [thread main]
     838.1 ms  on_time_event #2 (tick) [thread main]
    1041.6 ms  handle.stop() [thread stopper]
    1043.1 ms  on_stop, timers left = ["tick"] [thread main]
    1045.0 ms  run() returned, state = Stopped [thread main]
```

再看宽限期分别是 2 秒和默认值时，停止前后的几行：

```text
delay_post_stop = 2s
    1042.1 ms  handle.stop() [thread stopper]
    1044.1 ms  on_stop, timers left = ["tick"] [thread main]
    3050.9 ms  run() returned, state = Stopped [thread main]
delay_post_stop = 10s
    1033.9 ms  handle.stop() [thread stopper]
    1132.7 ms  on_stop, timers left = ["tick"] [thread main]
   11144.6 ms  run() returned, state = Stopped [thread main]
```

能读出这些事：

- **所有回调都在主线程上。** `on_start`、两次 `on_time_event`、`on_stop` 都标着 `[thread main]`，也就是调用 `run()` 的那个线程。计时器在 Tokio 工作线程上等待，事件经 channel 回到核心线程才执行（第 32 章）。
- **线程分布和第 29 章一致。** 节点启动后进程里有主线程（线程列表里显示为程序名 `ch30_live_node`）、4 个 `tokio-rt-worker`、名为 `logging` 的日志线程，以及实验自己开的 `stopper` 线程。
- **一个线程只能有一个节点。** 第二次 `build` 直接返回错误。
- **停止请求最多等一个检查周期。** `stop()` 只是设置一个标志，由每 100 毫秒一次的停止检查发现，所以 `on_stop` 比 `stop()` 晚几毫秒到 100 毫秒不等。
- **`run()` 在 `on_stop` 之后再过 `delay_post_stop` 才返回。** 0、2 秒、10 秒三种设置，`run()` 返回的时间分别比 `on_stop` 晚约 0、2、10 秒，状态都是 `Stopped`。
- **宽限期里组件的计时器已经停了。** `on_stop` 被调用时计时器还在（`timers left = ["tick"]`），但之后 2 秒、10 秒的宽限期里再也没有 `on_time_event`：组件停止时它的计时器随之取消。宽限期是留给订单回报这类“残余事件”的（第 5 节），不是让策略继续跑的。

::: warning 常见误区
- **以为风控放行后立即调用执行客户端。** 命令先进交易命令 channel，下一轮循环才处理。
- **以为高频行情会让订单回报排队。** 执行事件优先于数据事件。
- **以为计时器会被行情饿死，或者反过来。** 两个标记保证它们轮流得到处理。
- **在适配器的后台任务里调用 `get_data_event_sender()`。** 发送端在核心线程的线程局部变量里，要在核心线程上取好再带进任务。
- **把对账间隔配置成小于 100 毫秒。** 维护计时器的粒度是 100 毫秒。
- **以为 `stop()` 返回时撤单已经完成。** 有 10 秒宽限期处理残余事件，超时后未解决的提交会作为错误返回。
:::

## 本章结论

实盘节点在核心线程上运行一个 `biased` 的 `tokio::select!` 循环，从 7 个无界 channel 取消息，优先级依次是信号、停止检查、维护、时间事件、系统事件与命令、执行事件、交易命令、外部消息、数据事件、数据命令；两个标记防止计时器和行情饿死其他消息，每 64 次派发让出一次。发送端存在核心线程的线程局部变量里，适配器创建时取克隆带进后台任务。启动时先连数据客户端、把品种灌进缓存，再连执行客户端、对账，最后启动 Trader；停止时先停 Trader，在宽限期内处理残余事件，再并行收尾报告任务和断开客户端，最后完成内核的收尾。

## 检查理解

1. 策略在 `on_order_filled` 里立即提交一张止损单。从交易所的成交回报到止损单发出，这条消息在 channel 之间走了几次？

   <details><summary>参考答案</summary>

   成交回报从执行客户端的后台任务进入执行事件 channel，核心线程取出后交给执行引擎，执行引擎更新订单和仓位，策略的 `on_order_filled` 被调用；止损单经风控的 `queue_execute` 进入交易命令 channel；下一轮循环取出，交给执行引擎，再调用执行客户端的 `submit_order`，客户端把请求交给它的后台任务。所以经过两个 channel：执行事件和交易命令。和回测（第 24 章）不同，止损单要等事件循环的下一轮，而不是在同一个时间戳里结清。

   </details>

2. 一个数据客户端连接时推送了 3,000 个品种定义，同时策略的 `on_start` 订阅了其中一个品种的报价。为什么不会出现“订阅时品种还不在缓存里”的错误？

   <details><summary>参考答案</summary>

   有两层保证。第一，策略的 `on_start` 在 Trader 启动时才被调用，而 Trader 在数据客户端连接、执行客户端连接和对账都完成之后才启动。第二，数据客户端连接期间到达的品种定义在连接完成后被统一灌进缓存，处理顺序是先数据事件、后数据命令。

   </details>

3. 节点收到 `SIGTERM`，策略在 `on_stop` 里撤掉了 20 张挂单，但交易所 15 秒后才把撤单确认全部推回来。会发生什么？

   <details><summary>参考答案</summary>

   `initiate_shutdown` 设的宽限期默认是 10 秒。前 10 秒内到达的撤单确认会被正常处理；10 秒后循环退出，进入 `finalize_stop`，客户端被断开，之后的确认收不到。没有收到确认的订单停在 `PENDING_CANCEL`，退出循环时缓存的 `check_residuals` 会在日志里报告这些残余的挂单；它们在交易所的真实状态要等下次启动时由对账修正（第 34 章）。如果交易所通常较慢，可以调大 `delay_post_stop`。

   </details>

## 参考资料

- 官方文档：[Live Trading](https://nautilustrader.io/docs/latest/concepts/live/) · [Architecture](https://nautilustrader.io/docs/latest/concepts/architecture/)
- 源码：[`crates/live/src/node/mod.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/live/src/node/mod.rs) · [`crates/live/src/runner.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/live/src/runner.rs) · [`crates/common/src/runner.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/common/src/runner.rs) · [`crates/common/src/live/runner.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/common/src/live/runner.rs)
- 实验代码：[`live-lab`](https://github.com/lewislau86/lewislau86.github.io/tree/master/docs/public/nautilus-trader/code/live-lab) 的 `examples/ch30_live_node.rs`
- 配图由 `scripts/generate-nautilus-trader-figures.py` 生成。

适配器在 Tokio 上 spawn 的那些后台任务，停止时怎样保证在期限内收尾？下一章看 `TaskGroup`。[第 31 章：任务管理](./task-management.md)。
