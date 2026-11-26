---
title: "第 14 章：NautilusKernel：组装、启动与关闭"
description: NautilusKernel 怎样按依赖顺序构造时钟、事件存储、缓存、消息总线、组合、三大引擎、订单仿真器和 Trader；start、start_trader、stop_trader、finalize_stop、reset、dispose 各做什么、按什么顺序；实盘节点怎样在 start 和 start_trader 之间连接客户端和对账；状态的保存与恢复；出错即关停。
---

# 第 14 章：NautilusKernel：组装、启动与关闭

[全书目录](./index.md) · [上一章](./actors-and-config.md) · [下一章](./message-bus.md)

::: tip 本章学习目标
能按顺序说出内核构造时创建了哪些部件、为什么是这个顺序；能说清 `start` 和 `start_trader` 为什么要分两步，实盘节点在两步之间做了什么；知道关停时状态保存、引擎停止、计时器取消、事件存储封存的先后；知道 `load_state`、`save_state`、`shutdown_on_error` 这几个开关的实际效果。

**源码版本：** `develop` 分支，提交 `364254f`（2026-11-18）。内核在 `crates/system/src/kernel.rs`，内核配置在 `config.rs`，建造者在 `builder.rs`，时钟工厂在 `clock_factory.rs`，`Trader` 在 `trader.rs`；实盘节点的启动顺序在 `crates/live/src/node/mod.rs`。

**对应官方文档：** [Architecture](https://nautilustrader.io/docs/latest/concepts/architecture/) · [Live Trading](https://nautilustrader.io/docs/latest/concepts/live/)
:::

第三部分逐个拆开内核里的组件，第一个就是内核本身。第 1 章第 3 节已经给过 `NautilusKernel` 的字段和一个七步的构造顺序，这一章把它展开：每一步为什么在那里，启动和关闭各分几步，哪些步骤失败时会怎样收尾。读完这一章，第 15～23 章讲的每个组件，你都知道它是在什么时候被创建、什么时候开始工作的。

主线例子是一个实盘节点从启动到关闭的一生：构造、启动、连接客户端、对账、启动策略、运行、收到关停请求、停止、释放。

## 1. 构造：依赖决定顺序 {#construction}

`NautilusKernel::new_with_dependencies`（`kernel.rs`）按下面的顺序创建部件，后创建的依赖先创建的：

1. <strong>日志和机器标识。</strong>先初始化日志（`initialize_logging`，返回一个 `LogGuard` 存在内核里），后面每一步才能记日志。
2. <strong>时钟。</strong>`ClockFactory::for_environment` 按环境选时钟：回测用 `VirtualClock`，实盘和沙盒用实时时钟（第 17 章）。
3. <strong>事件存储（可选）。</strong>传入了 `EventStoreFactory` 才创建，它要用时钟和实例 ID（第 8 章第 5 节）。
4. <strong>缓存。</strong>`initialize_cache` 按缓存配置创建 `Cache`，有数据库适配器时接上（第 16 章）。
5. <strong>消息总线。</strong>创建 `MessageBus` 后立即 `set_message_bus` 放进线程局部存储，不作为内核的字段。从这一刻起，任何代码都能用 `get_message_bus()` 找到它（第 15 章）。
6. <strong>组合与三大引擎。</strong>依次创建 `Portfolio`、`RiskEngine`、`ExecutionEngine`、`OrderEmulator`、`DataEngine`；都拿到同一个时钟和同一个缓存。开启 `streaming` 特性时，数据目录也在这里注册给数据引擎。
7. <strong>注册总线处理器。</strong>`DataEngine`、`RiskEngine`、`ExecutionEngine`、`OrderEmulator` 各自调用 `register_msgbus_handlers`，把处理函数挂到总线的端点上。这一步必须在总线存在之后、任何组件发消息之前。
8. <strong>关停处理器。</strong>订阅关停主题，收到发给本交易员的 `ShutdownSystem` 命令时把一个共享的 `shutdown_requested` 标志置真。
9. <strong>Trader。</strong>最后创建 `Trader`，它要用到时钟工厂（给每个组件发一个独立的时钟）、缓存和组合。

这个顺序里有两个设计决定值得记住。第一，所有组件共享的只有时钟、缓存和总线三样东西，它们最先创建；引擎之间不互相持有引用，而是通过总线的端点通信。第二，总线是线程局部的，所以一个内核只能活在一个线程上，这就是第 1 章说的“单线程核心”在构造层面的体现。

除了直接调用 `new`，也可以用 `NautilusKernel::builder(...)`（`builder.rs`）逐项配置：`with_cache_config`、`with_cache_database`、`with_data_engine_config`、`with_risk_engine_config`、`with_exec_engine_config`、`with_msgbus_config`、`with_event_store`、`with_clock_factory` 等，最后 `build()`。

![内核的构造顺序和一生：上半是九步构造，下半是实盘节点从 start 到 dispose 的时间线，start 和 start_trader 之间是连接客户端和对账](/nautilus-trader/figures/kernel-lifecycle.svg)

怎么读这张图：上半看依赖，箭头从被依赖的指向依赖它的；下半看时间，从左到右是一次实盘运行，蓝色是内核的方法，青色是实盘节点在内核方法之间插入的步骤。

## 2. 启动分两步 {#start}

### 2.1 start：引擎和客户端

`NautilusKernel::start` 做三件事：

```rust
// 节选自 crates/system/src/kernel.rs（NautilusKernel::start）
pub fn start(&mut self) {
    arm_shutdown_on_error(self.config.shutdown_on_error());
    if let Some(event_store) = self.event_store.as_deref_mut() {
        // load_state 时先从父运行恢复缓存，再打开新的运行文件，并把快照锚点交给执行引擎
        // …
    }
    if self.event_store_replay {
        // 事件存储回放模式：不启动引擎、客户端和 Trader，直接返回
        return;
    }
    self.start_engines();          // 数据、风控、执行引擎启动；引擎再启动各自的客户端
    if self.trader.borrow().state() == ComponentState::PreInitialized {
        self.trader.borrow_mut().initialize()?;   // Trader 进入 READY
    }
    self.ts_started = Some(self.clock.borrow().timestamp_ns());
}
```

第一行是一个开关：`shutdown_on_error` 打开时，之后任何一条 ERROR 级别的日志都会被记成一个“关停触发”，内核在下次检查 `is_shutdown_requested()` 时把它转换成一条 `ShutdownSystem` 命令发到关停主题上。配置注释特意说明，被过滤掉或绕过日志系统的错误日志同样会触发。这就是 crash-only 设计在运行时的体现：出了错不硬撑，而是有序地停下来。

### 2.2 两步之间：实盘节点做的事

`start` 之后，策略还没有启动。实盘节点 `LiveNode::start`（`crates/live/src/node/mod.rs`）在这时插入了几步，模块注释把顺序写得很清楚：

1. 连接数据客户端，品种以数据事件的形式进入通道；
2. 把通道里积压的数据事件和命令全部冲进缓存（`flush_pending_data`），这样品种已经在缓存里；
3. 连接执行客户端，它们加载品种时就能从缓存里读到；
4. 排空剩余事件，然后做启动对账（第 34 章）。

连接有一个总的期限 `timeout_connection`，任何一个客户端连接失败、超时或者对账失败，节点都会中止启动并有序收尾。

### 2.3 start_trader：策略开始运行

只有上面这些都完成，节点才调用 `NautilusKernel::start_trader`：

- `load_state` 为真时，先从缓存数据库读出每个 Actor 和策略保存过的状态，调用它们的 `on_load`（`Trader::load_state`）；
- 启动订单仿真器；
- `Trader::start_with_component_callbacks` 依次启动所有 Actor、策略和执行算法（先 Actor 后策略，让策略启动时数据侧的组件已经在运行），它们的 `on_start` 在这里被调用，订阅从这里开始。

如果有组件启动失败，内核立即停止已经启动的那部分、停止仿真器、保存已有状态，然后返回一个汇总了所有错误的结果。

为什么要分两步？因为策略的 `on_start` 通常会订阅行情、查询品种、甚至下单。如果在客户端还没连上、品种还没进缓存、本地订单状态还没和交易所对齐时就启动策略，订阅会落空，下单会被拒，或者基于过期的状态做决定。两步之间的那段时间，就是留给“让本地世界和外部世界对齐”的。回测没有这个问题，`BacktestEngine` 在运行开始时直接依次调用两步。

## 3. 关闭：先停策略，再停引擎 {#stop}

关闭同样分步：

<strong>stop_trader。</strong>先撤掉“出错即关停”的开关（避免关闭过程中的错误日志再次触发关停），然后让 `Trader` 停止所有组件，它们的 `on_stop` 在这里被调用。

<strong>finalize_stop。</strong>在客户端断开之后调用：

```rust
// 节选自 crates/system/src/kernel.rs（NautilusKernel::finalize_stop）
let save_result = self.save_trader_state();            // save_state 时调用组件的 on_save
self.portfolio.borrow_mut().finalize_equity_curve();
self.stop_engines();                                     // 引擎再停止各自的客户端
self.cancel_timers();
if let Some(event_store) = self.event_store.as_deref_mut() {
    event_store.seal(ts_shutdown);                       // 写 RunEnded，清单封存为 Ended
}
```

顺序是：保存状态、结算权益曲线、停止引擎、取消计时器、封存事件存储。保存状态放在最前面，是因为后面的步骤会让组件失去访问缓存的机会。

<strong>reset 与 dispose。</strong>`reset` 让 `Trader`、三大引擎、仿真器和组合回到初始状态，回测要用同一个引擎跑下一轮时用它。`dispose` 是最终的释放：如果 `Trader` 还在运行就先停下，保存状态，释放 `Trader`，停止引擎，取消计时器，封存事件存储（源码注释说明，回测的 `end()` 不调用 `finalize_stop`，所以由 `dispose` 负责封存），然后依次释放三大引擎、仿真器、缓存，最后释放消息总线。

## 4. 状态的保存与恢复 {#state}

内核配置里有两个开关：`save_state` 和 `load_state`。它们保存和恢复的不是订单或仓位（那些在缓存里），而是每个 Actor 和策略自己的状态：

```rust
// 节选自 crates/system/src/trader.rs（Trader::save_state）
for (strategy_id, callbacks) in strategy_callbacks {
    match (callbacks.save)(strategy_id.inner()) {              // 调用策略的 on_save
        Ok(state) => {
            if let Err(e) = cache.borrow().update_strategy_state(&strategy_id, &state) {
                errors.push(format!("strategy {strategy_id} persistence: {e:#}"));
            }
        }
        Err(e) => errors.push(format!("strategy {strategy_id} callback: {e:#}")),
    }
}
```

策略在 `on_save` 里返回一个“键到字节”的映射，内核把它写进缓存数据库；下次 `start_trader` 时，`load_state` 读出来交给 `on_load`。前提是缓存有数据库后端（Redis 或 PostgreSQL）：没有时，`start_trader` 会警告这两个开关都不起作用，`save_state` 和 `load_state` 也直接返回。

`load_state` 还有第二个用途：第 8 章说的事件存储回放要求它为真。这时 `start` 会先从父运行恢复缓存，并进入“回放模式”，跳过引擎、客户端、对账和 `Trader` 的启动，只用来查看恢复出来的状态。

## 5. 一个内核，多种外壳 {#shells}

内核本身不知道自己在回测还是实盘，区别全在外壳：

- `BacktestEngine`（`crates/backtest/src/engine.rs`，第 24 章）用 `VirtualClock` 构造内核，按交易所建 `SimulatedExchange`，运行时由数据迭代器推进时钟；
- `LiveNode`（`crates/live/src/node/`，第 30 章）用实时时钟构造内核，持有 `AsyncRunner` 和 `ExecutionManager`，在 `start` 和 `start_trader` 之间连接客户端、对账，运行时由一个 `tokio::select!` 循环驱动；
- 沙盒是 `LiveNode` 加上模拟执行客户端（第 1 章第 7 节）。

实盘节点还有自己的状态机 `NodeState`：`Idle`、`Starting`、`Running`、`ShuttingDown`、`Stopped`。`add_actor`、`add_strategy` 只能在 `Idle` 时调用（第 9 章），所以组件要在 `run()` 之前全部加好。

::: warning 常见误区
- **在构造函数里假设总线或缓存已经可用。** 组件是在 `Trader` 注册时才接上时钟和缓存的（第 9 章），总线虽然在构造时就进了线程局部存储，但组件那时还没注册。
- **以为 `start` 之后策略就开始运行。** 策略在 `start_trader` 里才启动，中间隔着客户端连接和对账。
- **没有数据库后端却打开 `save_state`、`load_state`。** 两个开关都不起作用，只会得到一条警告。
- **以为 `load_state` 恢复的是订单和仓位。** 它恢复的是组件自己的 `on_save` 状态；订单和仓位靠缓存快照和对账。
- **在多个线程上使用同一个内核。** 总线是线程局部的，内核和所有组件都只能待在创建它的线程上。
- **打开 `shutdown_on_error` 后在回调里随手记错误日志。** 任何一条 ERROR 日志都会触发有序关停。
:::

## 本章结论

`NautilusKernel` 按依赖顺序构造：日志、时钟、可选的事件存储、缓存、放进线程局部存储的消息总线、组合和三大引擎（并注册各自的总线处理器）、关停处理器，最后是 `Trader`。启动分两步：`start` 启动引擎和客户端并初始化 `Trader`，`start_trader` 恢复组件状态、启动仿真器和所有组件；实盘节点在两步之间连接客户端、把品种冲进缓存并完成对账。关闭时先停组件，再保存状态、停引擎、取消计时器、封存事件存储。内核不区分回测和实盘，差别由外壳决定。

## 检查理解

1. 一个策略在 `on_start` 里调用 `cache.instrument(...)`，回测里总能取到，实盘里偶尔是 `None`。在分两步启动的设计下，这可能是什么原因？

   <details><summary>参考答案</summary>

   实盘节点在 `start_trader` 之前连接数据客户端，并用 `flush_pending_data` 把已到达的品种冲进缓存。如果这个品种不在数据客户端启动时加载的范围内（例如提供器只加载了部分品种），或者加载是异步的、在对账完成时还没到达，策略启动时缓存里就还没有它。需要检查品种提供器的配置，或者在策略里用 `request_instrument` 并在回调里继续。

   </details>

2. `finalize_stop` 为什么先保存状态，再停止引擎和封存事件存储？

   <details><summary>参考答案</summary>

   保存状态要调用组件的 `on_save`，并把结果写进缓存数据库；组件在这时可能还需要读缓存。先停引擎、取消计时器，后续步骤就可能失去这些能力；先封存事件存储，保存过程中产生的消息就无法再被记录。所以把需要完整系统的步骤放在最前面。

   </details>

3. 配置了 `shutdown_on_error = true`，策略在 `on_bar` 里记了一条 `log::error!`，接下来会发生什么？

   <details><summary>参考答案</summary>

   这条错误日志被记成一个关停触发。内核下次检查 `is_shutdown_requested()` 时，把它转换成一条 `ShutdownSystem` 命令发布到关停主题；内核自己订阅了这个主题，于是把 `shutdown_requested` 标志置真，节点的运行循环看到后开始有序关停：停止策略、断开客户端、保存状态、停止引擎、封存事件存储。

   </details>

## 参考资料

- 官方文档：[Architecture](https://nautilustrader.io/docs/latest/concepts/architecture/) · [Live Trading](https://nautilustrader.io/docs/latest/concepts/live/)
- 源码：[`crates/system/src/kernel.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/system/src/kernel.rs) · [`crates/system/src/config.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/system/src/config.rs) · [`crates/system/src/builder.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/system/src/builder.rs) · [`crates/system/src/trader.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/system/src/trader.rs) · [`crates/live/src/node/mod.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/live/src/node/mod.rs)
- 配图由 `scripts/generate-nautilus-trader-figures.py` 生成。

内核的部件之间不互相持有引用，它们都靠消息总线说话。下一章打开这条总线。[第 15 章：MessageBus](./message-bus.md)。
