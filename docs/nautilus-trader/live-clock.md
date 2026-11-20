---
title: "第 32 章：LiveClock 与实时计时器"
description: 实盘的“现在”从哪里来、AtomicTime 怎样用比较交换保证严格单调；设一个实时计时器时发生了什么：每个计时器一个 Tokio 任务；固定间隔和日程两种节奏；过期的开始时间怎样处理、错过的触发怎样补发；到点后事件怎样跨线程回到核心线程，Send 回调和线程局部回调走不同的路；时间事件的两个时间戳；单次提醒、取消和重启。
---

# 第 32 章：LiveClock 与实时计时器

[全书目录](./index.md) · [上一章](./task-management.md) · [下一章](./networking.md)

::: tip 本章学习目标
能解释实盘时钟为什么永远不会返回重复或倒退的时间；能说出设一个实时计时器后，哪个线程在等待、到点后事件经过哪条 channel、回调最终在哪个线程执行；能区分时间事件的 `ts_event` 和 `ts_init`，以及回调执行时的“现在”；知道固定间隔的计时器在核心线程忙不过来时会怎样补发、日程类计时器怎样跳过错过的时间点；知道单次提醒其实也是一个计时器。

**源码版本：** `develop` 分支，提交 `364254f`（2026-11-18）。实盘时钟在 `crates/common/src/live/clock.rs`，实时计时器在 `crates/common/src/live/timer.rs`，计时器间隔类型在 `crates/common/src/timer.rs`，原子时钟在 `crates/core/src/time.rs`，时间事件的派发在 `crates/live/src/runner.rs`。

**对应官方文档：** [Live Trading](https://nautilustrader.io/docs/latest/concepts/live/) · [Architecture](https://nautilustrader.io/docs/latest/concepts/architecture/)
:::

第 17 章讲了 `Clock` 这个 trait 和回测用的 `VirtualClock`，最后一节简单提到实盘用 `LiveClock`，计时器由 Tokio 调度。这一章把实盘这一侧展开。

主线例子：一个策略在 `on_start` 里做两件事：设一个每 30 秒触发一次的心跳计时器 `heartbeat`，和一个在 10:00:00 触发一次的提醒 `open_auction`。

## 1. 实盘的“现在” {#atomic-time}

实盘时钟的 `timestamp_ns()` 读的是全进程共享的 `AtomicTime`，处于实时模式。它的读取方法是：

```rust
// 节选自 crates/core/src/time.rs（AtomicTime::time_since_epoch，有删节）
let now = nanos_since_unix_epoch();                       // 系统时间
loop {
    let last = self.timestamp_ns.load(Ordering::Acquire);
    let next = now.max(last.checked_add(1).expect("AtomicTime overflow"));
    if self.timestamp_ns
        .compare_exchange(last, next, Ordering::AcqRel, Ordering::Acquire)
        .is_ok()
    {
        return UnixNanos::from(next);                      // 严格大于上一次返回的值
    }
}
```

每次读取取“系统时间”和“上一次返回值 + 1 纳秒”中较大的那个，再用比较交换写回。写回失败说明有别的线程刚读过，重新来一次。结果是：

- 不论多少个线程并发读取，返回值严格递增，不会有两个相同的时间戳；
- 系统时间被往回调（比如 NTP 校时）时，返回值也不会倒退，而是每次加 1 纳秒，直到系统时间追上来。

这也是为什么 `ts_init` 可以用来给事件排序（第 2 章）。代价是高并发读取时比较交换可能要重试几次，源码注释认为实际中很少发生。

## 2. 设一个计时器时发生了什么 {#set-timer}

策略调用 `clock.set_timer("heartbeat", 30 秒, …)`，`LiveClock::set_timer_ns` 做的事是：

1. 检查参数，处理开始和结束时间（第 17 章第 2 节的规则）；
2. 同名的旧计时器被取消（第 17 章说的“同名计时器不会并存”）；
3. 按第 17 章的三级查找确定回调；
4. 取得**时间事件发送端**：线程局部变量里的那个，即第 30 章 7 个 channel 中的“时间事件”；
5. 建一个 `LiveTimer`，调用 `start()`。

`start()` 在全局运行时上 **spawn 一个任务**，每个计时器一个。这个任务循环做三件事：等到下一个触发时间，构造一个 `TimeEvent`，把它发进时间事件 channel；然后算出再下一次的时间，继续等。核心线程上的事件循环从 channel 里取出这个事件，执行回调。

单次提醒 `set_time_alert_ns` 没有单独的实现：它就是一个间隔为“提醒时间 − 现在”、结束时间等于提醒时间的计时器，触发一次后到达结束时间，任务退出。主线例子的 `open_auction` 就是这样一个只触发一次的计时器。

取消计时器（`cancel_timer`）会中止对应的任务。时钟的 `reset()` 取消所有计时器。

## 3. 两种节奏 {#intervals}

计时器的间隔类型 `TimerInterval` 有两种：

- **固定间隔** `Fixed`：比如每 30 秒。任务内部用 Tokio 的 `interval_at`，触发时间落在“开始时间 + n × 间隔”这张固定的网格上。
- **日程** `Schedule`：由一个 `TimerSchedule` 提供一串绝对的 UTC 时间点，比如每个交易日的开盘时刻。任务每次计算离下一个时间点还有多久，然后睡到那时。

两种节奏处理“错过”的方式不同。假设核心线程或者运行时卡了 2 分钟：

- 固定间隔的计时器用的是 Tokio `interval` 的默认行为，会**连续补发**错过的触发，每个事件的 `ts_event` 仍是网格上原来的时间点。心跳计时器卡了 2 分钟之后，会紧接着收到 4 个事件，时间戳分别是被错过的那 4 个 30 秒整点。
- 日程类计时器**只补发一次**：立即发出被错过的那个时间点（保留它原来的时间戳），然后跳到“现在之后”的第一个时间点。

**开始时间已经过去。** 如果计时器启动时，第一次触发时间已经在过去（比如设了一个开始时间是 5 分钟前的计时器），会记一条警告，把第一次触发调整为“现在”，立即触发一次。例外是第一次触发恰好等于结束时间的情况：这时保留原来的时间，以免越过结束边界。

**结束时间。** 结束时间是闭区间：恰好等于结束时间的那次会触发，并且是最后一次。下一次时间超出 `UnixNanos` 能表示的范围时，也视为最后一次。

## 4. 事件怎样回到核心线程 {#dispatch}

计时器任务跑在工作线程上，回调要访问策略、缓存这些只在核心线程上的东西，所以回调不能在工作线程上执行。事件跨线程的方式取决于回调的类型：

| 回调 | 能跨线程吗 | 怎样回到核心线程 |
| --- | --- | --- |
| 线程安全的 Rust 回调 | 能 | 回调本身随事件一起发进 channel |
| 线程局部的 Rust 回调（持有 `Rc`） | 不能 | 回调留在核心线程的注册表里，只把一个令牌发过去，核心线程凭令牌取回回调 |
| Python 回调，且没有发送端 | — | 在工作线程上直接调用（拿 GIL） |

策略和 Actor 的计时器回调通常是第二种：`Trader` 注册的默认处理函数要通过 ID 找到组件，而组件在核心线程的注册表里（第 23 章）。令牌还带一个“租约”：事件发出时先领租约，所以一个**已经发进 channel** 的事件，即使计时器随后被取消、回调被注销，核心线程取出时仍然能执行它（源码测试 `test_live_clock_revokes_queued_callbacks` 断言的正是这一点）。取消只阻止此后的触发。计时器重启和事件发出之间的竞态，源码用“预留”和“退役”两个步骤处理：要么旧任务来不及发出，要么新任务能看到旧任务已经预留的下一次时间。

核心线程取出事件后，`handle_time_event` 按消息类型取得回调并调用。这时所有组件的时钟读到的都是实时的“现在”，而不是事件的时间。

## 5. 时间事件的两个时间戳 {#timestamps}

一个 `TimeEvent` 带两个时间：

- `ts_event`：**计划**触发的时间，即网格上或日程里的那个时间点；
- `ts_init`：工作线程**实际**构造这个事件时读到的时间。

回调被执行时，`clock.timestamp_ns()` 又是一个更晚的时间。三者的差，就是计时器在实盘里的延迟：`ts_init - ts_event` 是 Tokio 调度的延迟，`回调时的现在 - ts_init` 是事件在 channel 里排队的时间。第 30 章说过，时间事件在事件循环里的优先级排在执行事件之前，但处理一个时间事件后会被 `skip_time` 压到行情之后，所以行情密集、计时器又多时，这段排队可能明显变长。

主线例子里，`heartbeat` 的事件 `ts_event` 恰好是 30 秒的整数倍；`open_auction` 的 `ts_event` 是 10:00:00.000，而 `on_time_event` 里读到的时间可能是 10:00:00.003。依赖“恰好在开盘那一刻执行”的逻辑，应该用 `ts_event` 判断属于哪个时间点，而不是用回调时的当前时间。

这一点和回测正好相反：回测里执行回调时，所有时钟都被设到计时器的时刻（第 17 章第 4 节），三个时间完全相同。

![一个实时计时器的生命周期：核心线程上的策略调用 set_timer，LiveClock 建 LiveTimer 并在全局运行时上 spawn 一个任务；任务在工作线程上等待到点，构造 TimeEvent（ts_event 为计划时间，ts_init 为实际时间），按回调类型把回调或令牌发进时间事件 channel；核心线程的事件循环取出事件，执行回调](/nautilus-trader/figures/live-timer.svg)

怎么读这张图：左边是核心线程，右边是工作线程，中间的 channel 是唯一的通道。下方的时间轴标出了三个时间：计划时间、事件构造时间、回调执行时间。

::: warning 常见误区
- **以为实盘的时间戳可能重复。** `AtomicTime` 保证严格递增，系统时间回调时也不会倒退。
- **以为计时器回调在工作线程上执行。** 除了没有发送端的 Python 回调，都回到核心线程执行。
- **在回调里用 `timestamp_ns()` 判断是哪一个时间点。** 用事件的 `ts_event`。
- **以为卡顿之后固定间隔计时器只会触发一次。** 它会连续补发错过的触发；日程类计时器才只补一次。
- **设一个开始时间在过去的计时器，以为会从下一个整点开始。** 它会立即触发一次，并记警告。
- **以为单次提醒和计时器是两套机制。** 提醒就是一个只触发一次的计时器。
- **以为取消计时器后不会再收到它的事件。** 已经发进 channel 的事件仍会执行。
:::

## 本章结论

实盘时钟读的是全局的 `AtomicTime`，它用比较交换保证每次返回的时间严格大于上一次，并发读取不重复，系统时间回调也不倒退。每个实时计时器是全局运行时上的一个任务，固定间隔的按网格触发、错过时连续补发，日程类的按绝对时间点触发、错过时只补一次；开始时间已过时立即触发一次，结束时间是闭区间，单次提醒是只触发一次的计时器。事件在工作线程上构造，带计划时间 `ts_event` 和构造时间 `ts_init`，经时间事件 channel 回到核心线程；线程局部的回调只把令牌发过去，回调本身始终在核心线程上执行。

## 检查理解

1. 两个工作线程在同一纳秒里都调用了 `get_time_ns()`，系统时间都是 T。它们分别得到什么？

   <details><summary>参考答案</summary>

   一个得到 T，另一个得到 T + 1 纳秒（假设之前的最大值小于 T）。第一个线程比较交换成功，把 T 写回；第二个线程的比较交换失败，重新读到 T，于是取 `max(T, T + 1) = T + 1` 写回。两个值不同，且都不会小于此前返回过的任何值。

   </details>

2. 一个每秒触发一次的固定间隔计时器，回调里做了一次耗时 5 秒的同步计算。之后会发生什么？

   <details><summary>参考答案</summary>

   计时器任务在工作线程上照常按网格发出事件，这 5 秒里事件在 channel 里堆积；回调执行完后，核心线程依次取出这些事件，回调被连续调用 4、5 次，每个事件的 `ts_event` 是各自的整秒。如果 Tokio 的工作线程本身也被阻塞，`interval` 会在恢复后连续补发。回调里不应该做耗时的同步计算；需要的话，放到一个后台任务里，结果通过消息送回。

   </details>

3. 策略在 09:59:55 设了一个 10:00:00 的提醒，然后在 09:59:58 又用同样的名字设了一个 10:00:05 的提醒。10:00:00 会触发吗？

   <details><summary>参考答案</summary>

   不会。同名计时器会被取消：09:59:58 第二次设置时，旧计时器的任务还在等待 10:00:00，它被中止，回调令牌被关闭，所以不会触发。只有 10:00:05 的提醒会触发。要注意的是另一种情况：如果旧计时器已经触发、事件已经在 channel 里排队，之后再取消，这个事件仍然会被执行，取消只阻止以后的触发。

   </details>

## 参考资料

- 官方文档：[Live Trading](https://nautilustrader.io/docs/latest/concepts/live/)
- 源码：[`crates/common/src/live/clock.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/common/src/live/clock.rs) · [`crates/common/src/live/timer.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/common/src/live/timer.rs) · [`crates/common/src/timer.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/common/src/timer.rs) · [`crates/core/src/time.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/core/src/time.rs)
- 配图由 `scripts/generate-nautilus-trader-figures.py` 生成。

计时器之外，工作线程上最主要的工作是网络 I/O。下一章看网络层的 HTTP、WebSocket 和 Socket 客户端。[第 33 章：网络层](./networking.md)。
