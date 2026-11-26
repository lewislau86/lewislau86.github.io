---
title: "第 23 章：Trader：组件的生命周期与动态管理"
description: 组件生命周期的十四个状态和触发器；Trader 持有什么、为什么只存 ID；加入 Actor、策略、执行算法时各有什么限制；启动和停止各按什么顺序、出错怎样处理；运行时怎样启停、移除组件，Controller 怎样通过消息总线接受这些命令。
---

# 第 23 章：Trader：组件的生命周期与动态管理

[全书目录](./index.md) · [上一章](./portfolio.md) · [下一章](./backtest-engine.md)

::: tip 本章学习目标
能画出组件生命周期的主路径，说出 `reset`、`resume`、`degrade`、`dispose`、`fault` 各从哪些状态出发、到哪里结束；知道 Trader 为什么只存组件 ID；能说出启动和停止时三类组件的先后顺序，以及打开 `manage_stop` 的策略为什么不会马上停下；会在运行时停止、移除一个策略，知道 Controller 提供哪些命令、有什么限制。

**源码版本：** `develop` 分支，提交 `364254f`（2026-11-18）。Trader 在 `crates/system/src/trader.rs`，Controller 在 `crates/system/src/controller.rs`，控制命令在 `crates/system/src/messages/controller.rs`，生命周期状态机在 `crates/common/src/component.rs` 和 `crates/common/src/enums.rs`。

**对应官方文档：** [Architecture](https://nautilustrader.io/docs/latest/concepts/architecture/)（Component state management 一节） · [Strategies](https://nautilustrader.io/docs/latest/concepts/strategies/)
:::

前面几章分别讲了组件本身：第 9 章的策略、第 13 章的 Actor 和执行算法；第 14 章讲了内核怎样在启动和关闭时调用 Trader。这一章看 Trader 自己：它怎样登记组件、按什么顺序启停它们，以及运行中怎样增删组件。

主线例子：一个实盘节点里有 Actor `SpreadMonitor-001`、策略 `EMACross-001`（打开了 `manage_stop`）和执行算法 `TWAP`。节点运行后，我们要停掉 `EMACross-001`，再加入一个新策略。

## 1. 组件生命周期 {#lifecycle}

Actor、策略、执行算法，连同 Trader 自己，都实现 `Component` trait，共用一个状态机。状态有 14 个，主路径是：

```text
PRE_INITIALIZED → READY → STARTING → RUNNING → STOPPING → STOPPED
```

每个公开方法都按同一个模板写：先触发进入过渡状态，再调用对应的 `on_*` 回调，回调成功后再触发进入目标状态。以 `start` 为例：

```rust
fn start(&mut self) -> anyhow::Result<()> {
    self.transition_state(ComponentTrigger::Start)?;          // -> STARTING
    self.on_start()?;
    self.transition_state(ComponentTrigger::StartCompleted)?; // -> RUNNING
    Ok(())
}
```

回调返回错误时，状态停在过渡状态（这里是 `STARTING`），不会自动回退。

主路径之外还有五种操作：

| 操作 | 允许的起点 | 过渡状态 | 终点 |
| --- | --- | --- | --- |
| `reset()` | `READY`、`STOPPED` | `RESETTING` | `READY` |
| `resume()` | `STOPPED`、`DEGRADED` | `RESUMING` | `RUNNING` |
| `degrade()` | `RUNNING` | `DEGRADING` | `DEGRADED` |
| `dispose()` | `READY`、`STOPPING`、`STOPPED` 等 | `DISPOSING` | `DISPOSED` |
| `fault()` | `STARTING`、`RUNNING`、`STOPPING`、`STOPPED` 等 | `FAULTING` | `FAULTED` |

不在表里的组合会报错 `Invalid state trigger`，比如对 `RUNNING` 的组件直接调用 `reset()`，必须先停止。`reset` 和 `fault` 在调用回调后还会释放组件的全部订阅；`dispose` 的回调失败时，组件转入 `FAULTED`。

![组件生命周期：主路径从 PRE_INITIALIZED 经 READY、STARTING、RUNNING、STOPPING 到 STOPPED；STOPPED 可以经 RESETTING 回到 READY，或经 RESUMING 回到 RUNNING；下方列出 degrade、dispose、fault 三种操作，以及 Trader 启动和停止三类组件的顺序](/nautilus-trader/figures/component-lifecycle.svg)

怎么读这张图：上方一行是主路径，箭头上的字是触发它的方法。两条弧线是回头路：上面一条是 `reset()`，下面一条是 `resume()`。左下是其余三种操作，右下是 Trader 对三类组件的启停顺序，注意两者并不对称。

只有 `RUNNING` 状态的组件会收到数据、事件和计时器回调（第 10 章）。所以一个停在 `STARTING` 的策略不会收到任何行情，也不会报错，这是排查“策略没反应”时首先要看的。

## 2. Trader 持有什么 {#holds}

Trader 本身也是组件，它的字段里几乎没有组件对象，只有 ID：

- `actor_ids`、`strategy_ids`、`exec_algorithm_ids`：三类组件的 ID 列表，按加入顺序排列。
- `clocks`：每个组件一个时钟，由时钟工厂创建（回测里是各自独立的 `VirtualClock`，创建时对齐到主时钟的当前时间，由回测引擎统一推进；实盘里是 `LiveClock`，第 17 章）。
- 状态回调：每个 Actor 和策略一对 `load`、`save` 函数指针，供 `load_state`、`save_state` 使用（第 14 章第 4 节）。
- 策略的事件处理器 ID：订阅 `events.order.{strategy_id}` 和 `events.position.{strategy_id}` 时返回的处理器 ID，移除策略时用来退订。
- 策略的停止函数：停止时调用 `Strategy::stop`，它决定是否马上停（第 4 节）。

组件对象本身在加入时被移进两个全局注册表（第 9 章第 4 节）：组件注册表用于生命周期操作，Actor 注册表用于回调派发。Trader 启停组件时调用的是 `start_component(id)` 这样的函数，按 ID 到注册表里找对象。这样设计是因为组件同时被很多地方引用：总线上的处理器、时钟上的计时器回调、Trader 自己。如果每个地方都持有对象，就会遇到 Rust 的借用冲突；只持有 ID、用时再取，就避开了这个问题。

## 3. 加入组件 {#add}

三类组件各有一个加入方法：`add_actor`、`add_strategy`、`add_exec_algorithm`。它们的共同步骤是：检查 Trader 的状态、检查 ID 是否已被占用、建一个时钟、调用组件的 `register` 接上时钟和缓存、调用 `initialize()` 进入 `READY`、移入注册表、记下 ID。策略还要额外订阅自己的订单和仓位事件、注册市场退出的控制端点（第 9 章列过完整的 7 步）。

几条限制：

- **Trader 的状态。** Actor 和策略在 Trader 处于 `PRE_INITIALIZED`、`READY`、`STARTING`、`RUNNING`、`STOPPED` 时都可以加入；执行算法不能在 `RUNNING` 时加入。`DISPOSED` 之后什么都不能加。
- **订单号标签唯一。** 策略 ID 的最后一段（比如 `EMACross-001` 的 `001`）是订单号标签，会出现在它生成的每个 `client_order_id` 里。两个策略的标签相同会被拒绝。没有配置策略 ID 时，Trader 用类型名加下一个未被占用的序号生成。
- **节点层的限制更严。** `LiveNode::add_strategy` 只允许在节点空闲时调用，节点运行后再加会报错。它在调用 `Trader::add_strategy` 之外，还会向执行引擎登记策略的 OMS 类型（第 20 章第 1 节），并为 `external_order_instrument_ids` 登记外部订单认领。回测引擎的 `add_strategy` 同样会登记 OMS 类型。

## 4. 启动与停止的顺序 {#order}

内核的 `start_trader` 调用 `Trader::start_with_component_callbacks`（第 14 章）。它把 Trader 转入 `STARTING`，然后：

1. 依次启动所有 Actor；
2. 依次启动所有策略；
3. 依次启动所有执行算法：先恢复执行算法对策略事件的订阅，再启动；任何一个失败，就撤销已经恢复的订阅并返回错误；
4. 记录启动时间，Trader 转入 `RUNNING`。

已经是 `RUNNING` 的组件会被跳过，所以运行中单独启动过的组件不会被重复启动。先 Actor 后策略，是为了让策略启动时，提供数据或信号的 Actor 已经在运行。

停止（`stop_components`）的顺序不同：**Actor，然后执行算法，最后策略**。每一步的错误被收集起来，不会中断后面的组件，最后一起返回。策略放在最后，是因为策略停止时可能还要下单平仓，这时执行算法虽然已经停了，但风控、执行引擎和执行客户端都还在。

对策略，Trader 先调用它的停止函数 `Strategy::stop`：

- 没有打开 `manage_stop`：返回 `true`，Trader 接着调用 `stop_component`，策略进入 `STOPPED`。
- 打开了 `manage_stop` 且策略正在运行：策略标记“等待停止”，发起市场退出（撤销挂单、平掉仓位，第 9 章），返回 `false`。Trader 这时不调用 `stop_component`，策略保持 `RUNNING`，等市场退出完成后由策略自己完成停止。

主线例子里，节点关闭时 `SpreadMonitor-001` 和 `TWAP` 先停，`EMACross-001` 发起市场退出，平仓完成后才进入 `STOPPED`。

启动途中出错时，内核调用 `stop_trader_after_start_failure`，它再调用 Trader 的 `stop_after_start_failure`：按“Actor、执行算法（并清理订阅）、策略”的顺序停掉所有已经在 `STARTING`、`RUNNING` 或 `DEGRADED` 状态的组件。这条路径不经过策略的停止函数，所以不会发起市场退出。

`reset_components` 按“Actor、策略、执行算法”的顺序重置，回测引擎跑下一轮时用；`dispose_components` 在内核 `dispose` 时释放所有组件。

## 5. 运行时管理组件 {#runtime}

Trader 提供按 ID 操作单个组件的方法：

| 方法 | 作用 |
| --- | --- |
| `start_actor` / `stop_actor` / `remove_actor` | 启动、停止、移除一个 Actor |
| `start_strategy` / `stop_strategy` / `remove_strategy` | 同上，作用于策略；`stop_strategy` 同样经过停止函数 |
| `market_exit_strategy` | 让一个策略发起市场退出，不停止它 |

移除比停止多做很多事。以 `remove_strategy` 为例：先尽量把策略停下；然后释放它（转入 `DISPOSED`），清掉它的外部订单认领，退订它的订单和仓位事件，注销市场退出端点，释放它的时钟，从两个注册表里删除，最后从 ID 列表里删除。移除之后，同样的 ID 可以再次加入。

这些方法要在核心线程上调用，手里要有 Trader 的引用。**Controller** 把它们包装成可以通过消息总线发送的命令。Controller 本身是一个 Actor，启动时注册端点 `Controller.execute`，停止时注销。它接受的 `ControllerCommand` 有九种：

| 对 Actor | 对策略 |
| --- | --- |
| `CreateActor`、`StartActor`、`StopActor`、`RemoveActor` | `CreateStrategy`、`StartStrategy`、`StopStrategy`、`ExitMarket`、`RemoveStrategy` |

任何组件都可以用 `Controller::send(&command)` 发命令；Controller 收到后调用 Trader 的对应方法，失败时只记一条错误日志，不会把错误返回给发送方。

主线例子的运行时操作是这样的：

```rust
// 在某个 Actor 的回调里（核心线程）
let ts = self.clock().timestamp_ns();
let cmd = StopStrategy::new(StrategyId::from("EMACross-001"), UUID4::new(), ts);
Controller::send(&ControllerCommand::StopStrategy(cmd))?;
```

`EMACross-001` 打开了 `manage_stop`，所以收到停止命令后先做市场退出，平仓完成后才停下。要加入新策略，Rust 代码可以直接调用 `controller.create_strategy(strategy, true)`：它调用 `Trader::add_strategy`，然后启动这个策略；启动失败时会回滚，把刚加入的策略移除。

使用 Controller 有三点要注意：

- **按配置创建组件需要 Python。** `CreateActor` 和 `CreateStrategy` 命令携带的是可导入的配置（模块路径加配置），只有编译了 `python` 特性时才能执行，否则报错。纯 Rust 里要用 `create_strategy` 这类直接传对象的方法。在节点配置里声明 Controller（`LiveNodeConfig.controller`）也同样需要 `python` 特性。
- **运行时加入的策略不会登记 OMS 类型。** Controller 只调用 `Trader::add_strategy`，不经过 `LiveNode::add_strategy`，所以策略配置里的 `oms_type` 和外部订单认领都没有登记到执行引擎。依赖 HEDGING 覆盖的策略不适合这样加入。
- **执行算法不能在运行时加入。** Controller 没有对应的命令，Trader 也拒绝在 `RUNNING` 时加入执行算法。

## 6. 和其他章节的分工 {#map}

| 话题 | 章节 |
| --- | --- |
| 策略注册时 Trader 接上的 7 样东西 | 第 9 章第 4 节 |
| 只有 `RUNNING` 才派发回调 | 第 10 章 |
| Actor 和执行算法本身 | 第 13 章 |
| 内核什么时候调用 Trader 的启停、状态保存与恢复 | 第 14 章 |
| 市场退出、`manage_stop` 的配置 | 第 9 章 |

::: warning 常见误区
- **以为 `on_start` 报错后组件会回到 `READY`。** 它停在 `STARTING`，不会收到任何回调，需要人工处理。
- **对运行中的组件直接调用 `reset()`。** 必须先 `stop()`，否则状态机报错。
- **以为停止顺序和启动顺序相反。** 启动是 Actor、策略、执行算法；停止是 Actor、执行算法、策略。
- **以为 `stop_strategy` 返回后策略已经停了。** 打开 `manage_stop` 时，它只是发起了市场退出，策略还在运行。
- **用两个订单号标签相同的策略。** 第二个会被拒绝；不配置 ID 时 Trader 会自动避开已用的序号。
- **在运行时用 Controller 加一个 HEDGING 策略。** OMS 类型没有登记，它的成交会按执行客户端的 OMS 类型处理。
:::

## 本章结论

所有组件共用一个 14 状态的生命周期状态机，每个操作都是“进入过渡状态、调用回调、进入目标状态”，回调失败就停在过渡状态。Trader 只保存组件 ID、每个组件的时钟和几组回调，组件对象放在全局注册表里按 ID 取用。启动按 Actor、策略、执行算法的顺序，停止按 Actor、执行算法、策略的顺序；打开 `manage_stop` 的策略会先做市场退出再停。运行时可以按 ID 启停、移除组件，Controller 把这些操作变成消息总线上的命令，但按配置创建组件需要 Python，运行时加入的策略也不会登记 OMS 类型。

## 检查理解

1. 一个策略的 `on_start` 里订阅了一个不存在的品种并返回错误。节点会怎样？这个策略处于什么状态？

   <details><summary>参考答案</summary>

   策略停在 `STARTING`。`start_with_component_callbacks` 把错误向上返回，内核启动失败，调用 `stop_after_start_failure`，把已经在 `STARTING`、`RUNNING` 或 `DEGRADED` 的组件都停掉，这个策略也在其中，会进入 `STOPPED`。这条路径不调用策略的停止函数，所以不会发起市场退出。

   </details>

2. 回测跑完一轮后，想用同一个引擎和同一组策略再跑一轮。组件的状态要怎样变化？

   <details><summary>参考答案</summary>

   一轮结束后组件处于 `STOPPED`。引擎 `reset()` 时 Trader 依次重置 Actor、策略和执行算法，它们经 `RESETTING` 回到 `READY`，同时释放了全部订阅；策略的 `on_reset` 要清掉指标和自己的状态。下一轮启动时再走一遍 `READY → STARTING → RUNNING`，订阅在 `on_start` 里重新建立。

   </details>

3. 运行中想把一个策略换成参数不同的新版本，两者 ID 相同。应该怎样做？

   <details><summary>参考答案</summary>

   先移除旧策略（`remove_strategy` 或 `RemoveStrategy` 命令）：它会停止、释放策略，退订事件，并从注册表和 ID 列表里删除，之后同一个 ID 可以再次使用。然后用 `create_strategy(new_strategy, true)` 加入并启动新版本。如果旧策略打开了 `manage_stop`，停止时会先做市场退出，平掉它的仓位；不想平仓的话要先关掉这个选项。另外要记得，运行时加入的策略不会登记 `oms_type`。

   </details>

## 参考资料

- 官方文档：[Architecture](https://nautilustrader.io/docs/latest/concepts/architecture/) · [Strategies](https://nautilustrader.io/docs/latest/concepts/strategies/)
- 源码：[`crates/system/src/trader.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/system/src/trader.rs) · [`crates/system/src/controller.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/system/src/controller.rs) · [`crates/system/src/messages/controller.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/system/src/messages/controller.rs) · [`crates/common/src/component.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/common/src/component.rs)
- 配图由 `scripts/generate-nautilus-trader-figures.py` 生成。

第三部分到这里结束。第四部分把这些组件放进一个由历史数据驱动的循环里，先看回测引擎本身。[第 24 章：BacktestEngine 与 BacktestNode](./backtest-engine.md)。
