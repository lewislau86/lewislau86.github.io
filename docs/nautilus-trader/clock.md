---
title: "第 17 章：Clock 与计时器：时间从哪里来"
description: NautilusTrader 的 Clock trait 提供什么；回测用的 VirtualClock 怎样用一个最小堆管理计时器、怎样被推进；回测引擎怎样把计时器和数据排在同一条时间线上，同一时刻的数据和计时器谁先谁后；实盘的 LiveClock 和严格单调的原子时钟；计时器的命名、回调查找与常见参数。
---

# 第 17 章：Clock 与计时器：时间从哪里来

[全书目录](./index.md) · [上一章](./cache.md) · [下一篇](./futu-adapter.md)

::: tip 本章学习目标
能用 `set_timer` 和 `set_time_alert` 设计时器并说清各个参数的作用；知道回调是怎样被找到的；能推演回测里一串数据和几个计时器的执行顺序，包括同一时刻的数据和计时器谁先执行；知道实盘时钟的时间从哪里来、为什么严格单调，计时器到点后怎样回到核心线程。

**源码版本：** `develop` 分支，提交 `364254f`（2026-11-18）。`Clock` trait 在 `crates/common/src/clock/mod.rs`，`VirtualClock` 在 `clock/virtual.rs`，时间事件与回调在 `crates/common/src/timer.rs`，实盘时钟在 `crates/common/src/live/clock.rs`，原子时钟在 `crates/core/src/time.rs`，回测引擎推进时间的逻辑在 `crates/backtest/src/engine.rs`。

**对应官方文档：** [Actors](https://nautilustrader.io/docs/latest/concepts/actors/)（Timers and alerts 一节）· [Architecture](https://nautilustrader.io/docs/latest/concepts/architecture/) · [Backtesting](https://nautilustrader.io/docs/latest/concepts/backtesting/)
:::

第 2 章说过，NautilusTrader 的时间一律是 `u64` 纳秒；第 11 章的时间 K 线靠一个计时器驱动；第 14 章说内核构造时第二步就是选时钟。这一章回答两个问题：组件说“现在几点”时，答案从哪里来；组件说“10 秒后叫我”时，这件事在回测和实盘里分别怎样实现。回测和实盘的策略代码一模一样，差别全在时钟里，所以时钟是“回测实盘同构”最关键的一环。

主线例子是一段回测：策略在 10:00:00 设了一个每 30 秒触发的计时器 `heartbeat`，同时订阅了 1 分钟 K 线（于是有一个 10:01:00 到点的 `TIME_BAR_…` 计时器）；数据里有一笔成交恰好发生在 10:01:00.000。

## 1. Clock trait {#clock-trait}

`Clock`（`clock/mod.rs`）的方法可以分成三组：

- <strong>读时间。</strong>`timestamp_ns`、`timestamp_us`、`timestamp_ms`、`timestamp`（秒，`f64`）、`utc_now`。
- <strong>设计时器。</strong>`set_time_alert`/`set_time_alert_ns`（到某个时刻提醒一次）、`set_timer`/`set_timer_ns`（按间隔反复触发）、`set_timer_schedule`（按一个自定义的绝对时刻表触发，第 11 章月线、年线用的日历提醒就是这一类需求）。
- <strong>管理。</strong>`timer_names`、`timer_count`、`timer_exists`、`next_time_ns`、`cancel_timer`、`cancel_timers`、`register_default_handler`、`reset`。

两个实现：回测用 `VirtualClock`，实盘和沙盒用 `LiveClock`。由谁选、何时选，见第 14 章第 1 节：`ClockFactory::for_environment` 按环境决定。值得注意的是，每个组件拿到的是自己的一个时钟实例（`Trader` 注册组件时用 `ClockFactory::create_component_clock` 创建，第 9 章第 4 节），而不是和内核共用一个；回测里新建的虚拟时钟会从主时钟的当前时间开始。

## 2. 设一个计时器 {#set-timer}

`set_timer_ns` 的参数是：名字、间隔、开始时间、结束时间、回调、`allow_past`、`fire_immediately`。trait 的文档把规则写得很细：

- <strong>名字唯一。</strong>同名的计时器已经存在时，旧的会被取消并记一条警告，然后设置新的。
- <strong>开始时间。</strong>`None` 或 0 表示从当前时间开始；`fire_immediately` 为假时，第一次触发在开始时间加一个间隔，为真时在开始时间立即触发一次。
- <strong>过去的时间。</strong>`allow_past` 默认为真：对于一次性提醒，过去的时刻会被挪到“现在”并立即触发；设为假时，过去的时刻直接返回错误。
- <strong>结束时间。</strong>必须晚于开始时间，到点后计时器自动结束。

回调的查找顺序是：调用时显式传入的回调；没传就找之前以同一个名字登记过的回调；再没有就用组件的默认处理器，最终落到 `on_time_event`。三者都没有时，设置计时器直接返回错误。回调本身是 `TimeEventCallback`（`timer.rs`），有三种：Python 可调用对象、可跨线程的 Rust 闭包、只在本线程用的 Rust 闭包（`RustLocal`，第 11 章的时间 K 线聚合器用的就是它）。

主线例子里，策略在 `on_start` 里这样写（示意）：

```rust
// 示意：每 30 秒触发一次，不传回调，于是落到 on_time_event
self.clock().set_timer("heartbeat", Duration::from_secs(30), None, None, None, None, None)?;
```

## 3. VirtualClock：一个最小堆 {#virtual-clock}

```rust
// 节选自 crates/common/src/clock/virtual.rs
pub struct VirtualClock {
    time: AtomicTime,                                  // 静态模式：值由外部设置
    timers: BTreeMap<Ustr, VirtualTimer>,
    pub(super) timer_queue: BinaryHeap<ScheduledTimeEvent>,   // 按到期时间排序
    callbacks: CallbackRegistry,
}
```

虚拟时钟不会自己走，它的时间只在被推进时改变。推进的入口是 `advance_time(to_time_ns, set_time)`：

```rust
// 节选自 crates/common/src/clock/virtual.rs（VirtualClock::advance_time）
assert!(to_time_ns >= from_time_ns, "Invariant: time must be non-decreasing …");
if set_time { self.time.set_time(to_time_ns); }
let mut events: Vec<TimeEvent> = Vec::new();
while self.timer_queue.peek().is_some_and(|entry| entry.0.ts_event <= to_time_ns) {
    let entry = self.timer_queue.pop()?;
    let Some((event, next_event)) = self.advance_timer_from_entry(&entry.0) else { continue };
    events.push(event);
    if let Some(next_event) = next_event {
        self.timer_queue.push(next_event);             // 周期计时器把下一次放回堆里
    }
}
// … 一次产生超过 100 万个事件时警告，按 ts_event 排序后返回
```

这段代码说明了三件事：时间只能向前，倒退会直接断言失败；一次推进会弹出所有到期的事件，周期计时器每弹出一次就把下一次放回去；如果两次数据之间隔了很久、计时器间隔又很短，一次推进会产生海量事件，所以源码在超过 100 万个时警告，并建议在没有数据的长时间段里停掉计时器。

## 4. 回测引擎怎样排时间线 {#backtest-timeline}

单个虚拟时钟只会弹出事件，真正决定“计时器和数据谁先执行”的是回测引擎（`crates/backtest/src/engine.rs`）。它的主循环对每一个数据时间戳 `T` 做三件事：

```rust
// 节选自 crates/backtest/src/engine.rs（主循环与 advance_time_impl，有删节）
if ts_init > self.last_ns {
    self.advance_time_impl(ts_init)?;     // ① 先执行所有严格早于 T 的计时器
}
self.replay_data_row(ts_init)?;           // ② 再处理时间戳为 T 的数据

fn advance_time_impl(&mut self, ts_now: UnixNanos) -> anyhow::Result<()> {
    self.accumulate_time_events(ts_now);                 // 收集所有组件时钟到期的事件
    let ts_before = ts_now.saturating_sub(DurationNanos::new(1));
    while let Some(ts_event) = self.accumulator.peek_next_time().filter(|t| *t <= ts_before) {
        self.run_timer_handlers_at(ts_event)?;           // 把所有时钟设到 ts_event，再调用回调
        // …
    }
    Self::set_all_clocks_time(&self.collect_all_clocks(), ts_now);
    Ok(())
}
```

`replay_data_row` 处理完时间戳为 `T` 的最后一条数据后，再调用 `flush_accumulator_events(T)`，执行恰好在 `T` 到点的计时器（③）。归纳起来，同一个时间轴上的规则是：

1. 严格早于下一条数据的计时器，先执行；执行每个计时器回调之前，所有组件的时钟都被设到这个计时器的时刻，所以回调里读到的“现在”就是它到点的时间。
2. 然后执行这一时刻的全部数据。
3. 最后执行恰好在这一时刻到点的计时器。

回到主线例子：10:00:30 的 `heartbeat` 在它之后的第一笔数据之前触发；10:01:00.000 那笔成交先进入 K 线聚合器，然后 10:01:00 的 `TIME_BAR` 计时器才触发、生成 K 线，所以这笔边界上的成交落在 10:00～10:01 这根 K 线里，和第 11 章默认的左开右闭区间一致。

![回测的时间线：每个数据时间戳之前先执行更早的计时器，然后处理这一时刻的数据，最后执行恰好在这一时刻到点的计时器；执行计时器时所有组件时钟被设到计时器的时刻](/nautilus-trader/figures/clock-timeline.svg)

怎么读这张图：横轴是回测时间，上方是数据，下方是计时器。圈出的数字是执行顺序，注意 10:01:00 那一刻：数据（④）先于计时器（⑤）。

数据全部播完以后，引擎还会继续推进到回测结束时间，执行剩下的计时器（`process_next_timer`）。这也是为什么第 11 章的实验里，最后一根没走完的 1 分钟 K 线不会出现：回测的结束时间就是最后一条数据的时间，下一个整分钟的计时器已经在结束时间之后了。

## 5. LiveClock：时间来自原子时钟 {#live-clock}

```rust
// 节选自 crates/common/src/live/clock.rs
pub struct LiveClock {
    time: &'static AtomicTime,                    // 全进程共享的实时原子时钟
    timers: BTreeMap<Ustr, LiveTimer>,
    callbacks: CallbackRegistry,
    sender: Option<Arc<dyn TimeEventSender>>,     // 把到点的事件送回核心线程
    sender_deferred: bool,
}
```

实盘时钟读的是一个全局的 `AtomicTime`（`crates/core/src/time.rs` 的 `get_atomic_clock_realtime`）。它底下是系统时间，但多了一层保证：每次读取都通过比较交换，确保返回值严格大于上一次返回的值，即使在多个线程上并发读取也一样。所以同一纳秒里发生的两件事也能排出先后，`ts_init` 永远不会重复或倒退。

计时器到点由 Tokio 调度：每个 `LiveTimer` 在后台等待到期，到点后不直接调用回调（回调要访问组件和缓存，只能在核心线程上执行），而是把 `TimeEvent` 连同回调经 `TimeEventSender` 送进一个通道，由实盘节点的事件循环取出后在核心线程上执行。这条通道和它的优先级在第 30 章讲，实时计时器的实现在第 32 章。

这就是回测和实盘的根本差别：回测里时间由数据推着走，计时器和数据在同一条确定的时间线上严格排序，结果可以重放；实盘里时间自己走，计时器事件和行情事件从不同的通道到达，先后由到达的时刻决定。

::: warning 常见误区
- **以为同名计时器会并存。** 同名的旧计时器会被取消并记警告。
- **不传回调也没有 `on_time_event`。** 三级查找都落空时，设置计时器直接报错。
- **以为回测里同一时刻的计时器先于数据执行。** 只有严格更早的计时器在数据之前，恰好同一时刻的计时器在数据之后。
- **在没有数据的长时段里保留高频计时器。** 一次推进可能产生数百万个事件，源码会警告。
- **以为组件共享一个时钟实例。** 每个组件有自己的时钟，回测里由引擎统一推进。
- **在实盘的计时器回调里假设它和某条行情的先后。** 两者来自不同的通道，顺序由到达时刻决定。
:::

## 本章结论

`Clock` trait 统一了读时间、设计时器和管理计时器三件事：计时器按名字唯一，回调按“显式传入、按名字登记、默认处理器”三级查找。回测的 `VirtualClock` 是一个由外部推进的最小堆，回测引擎在每个数据时间戳之前先执行严格更早的计时器、再处理数据、最后执行同一时刻到点的计时器，并在执行计时器前把所有组件的时钟设到它的时刻，让整条时间线确定、可重放。实盘的 `LiveClock` 读一个跨线程严格单调的原子时钟，计时器由 Tokio 调度，到点后经通道把事件送回核心线程执行。

## 检查理解

1. 回测数据的时间戳依次是 10:00:00、10:00:20、10:00:45，策略在 10:00:00 设了一个间隔 10 秒、`fire_immediately=false` 的计时器。在处理 10:00:45 这条数据之前，计时器触发了几次，各在什么时刻？

   <details><summary>参考答案</summary>

   第一次在 10:00:10（开始时间加一个间隔），之后每 10 秒一次。处理 10:00:20 这条数据之前，执行严格早于它的 10:00:10；10:00:20 的那一次恰好和数据同一时刻，在这条数据处理完之后执行。处理 10:00:45 之前，执行 10:00:30 和 10:00:40。所以处理 10:00:45 之前一共触发 4 次：10:00:10、10:00:20、10:00:30、10:00:40。

   </details>

2. 策略在计时器回调里调用 `self.clock().timestamp_ns()`，回测里读到的是计时器到点的时间，还是触发它的那条数据的时间？

   <details><summary>参考答案</summary>

   是计时器到点的时间。回测引擎在执行每个计时器回调之前，把所有组件的时钟都设到这个计时器的 `ts_event`，所以回调里读到的“现在”就是它到点的时刻，而不是之后那条数据的时间。

   </details>

3. 实盘里两个线程几乎同时读时间，读到的值可能相同吗？为什么要这样保证？

   <details><summary>参考答案</summary>

   不会相同。实时原子时钟每次读取都用比较交换保证返回值严格大于上一次返回的值，即使跨线程。这样每个对象的 `ts_init` 都是唯一且递增的，同一纳秒内创建的两个事件也能排出先后，依赖时间戳排序的逻辑（缓存、事件存储、日志）不会遇到并列或倒退。

   </details>

## 参考资料

- 官方文档：[Actors · Timers and alerts](https://nautilustrader.io/docs/latest/concepts/actors/) · [Architecture](https://nautilustrader.io/docs/latest/concepts/architecture/) · [Backtesting](https://nautilustrader.io/docs/latest/concepts/backtesting/)
- 源码：[`crates/common/src/clock/`](https://github.com/nautechsystems/nautilus_trader/tree/develop/crates/common/src/clock) · [`crates/common/src/timer.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/common/src/timer.rs) · [`crates/common/src/live/clock.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/common/src/live/clock.rs) · [`crates/core/src/time.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/core/src/time.rs) · [`crates/backtest/src/engine.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/backtest/src/engine.rs)
- 配图由 `scripts/generate-nautilus-trader-figures.py` 生成。

内核的共享基础设施（时钟、缓存、总线）到这里讲完了。第三部分接下来是三大引擎和组合（第 18～23 章），尚在规划中，回到[全书目录](./index.md)查看；已成文的下一篇是[第 38 章：增加一个券商：以富途为例](./futu-adapter.md)。
