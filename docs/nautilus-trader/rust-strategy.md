---
title: "第 9 章：Rust 策略的框架与运行机制"
description: 用 Rust 写一个 NautilusTrader 策略需要写什么、框架替你做了什么：StrategyCore 与 StrategyConfig，nautilus_strategy! 宏生成的代码，注册到 Trader 时接上了哪些部件，生命周期怎样推进，下单 API 怎样工作，关联订单、GTD、市场退出这些托管功能，以及怎样在回测和实盘里跑起来。
---

# 第 9 章：Rust 策略的框架与运行机制

[全书目录](./index.md) · [上一章](./events.md) · [下一章](./callbacks.md)

::: tip 本章学习目标
能从零写出一个 Rust 策略并把它放进回测或实盘节点；说清一个策略由哪几部分拼成，哪些是你写的、哪些是宏生成的、哪些是框架的默认实现；知道 `StrategyCore` 在注册前后有什么区别，注册时 `Trader` 替你接上了什么；知道下单、改单、撤单、平仓的 API 和它们背后的路由；知道关联订单、GTD 过期、市场退出这些托管功能怎样打开。

**源码版本：** `develop` 分支，提交 `364254f`（2026-11-18）。策略框架在 `crates/trading/src/strategy/`，宏在 `crates/trading/src/macros.rs`，注册在 `crates/system/src/trader.rs`。

**对应官方文档：** [Strategies](https://nautilustrader.io/docs/latest/concepts/strategies/) · [Actors](https://nautilustrader.io/docs/latest/concepts/actors/) · [Rust](https://nautilustrader.io/docs/latest/concepts/rust/)
:::

前面几章从平台的角度看策略：第 1 章看一笔订单从策略出发走到交易所，第 0 章看 `StrategyCore` 的字段。这一章换到写策略的人的角度：我要写什么，框架会在什么时候调用我，我能调用框架的什么。回调的具体派发过程放在下一章。

Python 也能写策略，但 Python 的 `Strategy` 是这套 Rust 框架的绑定，走的是同一个 `StrategyCore` 和同一套注册、派发流程（第 0 章第 6.1 节）；它的细节放在第七部分 Python 层。

## 1. 一个最小的 Rust 策略

仓库自带的 `EmaCross`（`crates/trading/src/examples/strategies/ema_cross/strategy.rs`）是最好的起点，去掉注释和 `Debug` 实现之后只有几十行：

```rust
// 节选自 crates/trading/src/examples/strategies/ema_cross/strategy.rs
pub struct EmaCross {
    core: StrategyCore,                    // 框架要求的唯一字段
    instrument_id: InstrumentId,           // 下面都是策略自己的东西
    trade_size: Quantity,
    ema_fast: ExponentialMovingAverage,
    ema_slow: ExponentialMovingAverage,
    prev_fast_above: Option<bool>,
}

impl EmaCross {
    pub fn from_config(config: EmaCrossConfig) -> Self {
        Self {
            core: StrategyCore::new(config.base),   // base 是 StrategyConfig
            // … 指标和参数
        }
    }

    fn enter(&mut self, side: OrderSide) -> anyhow::Result<()> {
        let order = self.order().market(self.instrument_id, side, self.trade_size,
                                        None, None, None, None, None, None, None);
        self.submit_order(order, None, None, None)
    }
}

nautilus_strategy!(EmaCross);              // 生成样板代码

impl DataActor for EmaCross {
    fn on_start(&mut self) -> anyhow::Result<()> {
        self.subscribe_quotes(self.instrument_id, None, None);
        Ok(())
    }

    fn on_quote(&mut self, quote: &QuoteTick) -> anyhow::Result<()> {
        self.ema_fast.handle_quote(quote)?;
        self.ema_slow.handle_quote(quote)?;
        // 均线金叉买、死叉卖：self.enter(OrderSide::Buy) / self.enter(OrderSide::Sell)
        Ok(())
    }

    fn on_stop(&mut self) -> anyhow::Result<()> {
        self.unsubscribe_quotes(self.instrument_id, None, None);
        Ok(())
    }

    fn on_reset(&mut self) -> anyhow::Result<()> {
        self.ema_fast.reset();
        self.ema_slow.reset();
        self.prev_fast_above = None;
        Ok(())
    }
}
```

写一个策略只需要四件事：一个持有 `StrategyCore` 的结构体；一个构造函数；一行 `nautilus_strategy!`；一个 `impl DataActor`，覆盖你关心的回调。注意 `on_quote` 是 `DataActor` 的方法而不是 `Strategy` 的：行情回调属于“能收数据的组件”，所有 actor 都有；`Strategy` 在它之上加的是交易能力。

## 2. 一个策略由三部分拼成

![Rust 策略的组成：左边是你写的结构体、impl DataActor 和可选的 Strategy 覆盖；中间是 nautilus_strategy! 宏生成的 DataActorNative、StrategyNative 和空的 impl Strategy；右边是框架提供的 Component 通用实现以及 DataActor、Strategy 的默认方法；下方是 StrategyCore 的组成，注册之后才完整](/nautilus-trader/figures/rust-strategy.svg)

怎么读这张图：上面三栏从左到右是“你写的、宏生成的、框架提供的”，合起来才是一个能被 `Trader` 管理的策略；下面一行是 `StrategyCore` 里装的部件。

这套设计里有四个 trait，分工如下：

| trait | 定义在 | 作用 | 谁来实现 |
| --- | --- | --- | --- |
| `DataActor` | `crates/common/src/actor/data_actor.rs` | 数据回调 `on_*`、订阅和请求 `subscribe_*` / `request_*`、派发前检查 `handle_*` | 你（只写需要的回调，其余用默认实现） |
| `Strategy` | `crates/trading/src/strategy/mod.rs` | 下单、改单、撤单、平仓；订单和仓位回调；`handle_order_event` 等 | 宏生成空实现，全部用默认方法；需要时在宏里覆盖 |
| `DataActorNative`、`StrategyNative` | `common/src/actor/`、`trading/src/strategy/core.rs` | 告诉默认方法“核心在哪个字段”：`core()`、`strategy_core()` | 宏生成 |
| `Component` | `crates/common/src/component.rs` | 生命周期状态机：`start`、`stop`、`reset`、`dispose` | 框架：`impl<T> Component for T where T: DataActor + DataActorNative` |

关键在中间那一行。`DataActor` 和 `Strategy` 的几十个方法都有默认实现，这些默认实现需要访问组件的状态（时钟、缓存、订阅表、下单工厂），而 trait 本身没有字段。`DataActorNative` 和 `StrategyNative` 就是“把状态交出来”的接口：默认方法通过 `self.core()`、`self.strategy_core_mut()` 拿到 `StrategyCore`，再做事。

`nautilus_strategy!` 宏（`crates/trading/src/macros.rs`）展开后正好生成这些：

```rust
// nautilus_strategy!(EmaCross) 展开后的大意
impl EmaCross {
    pub fn config(&self) -> &StrategyConfig { self.core.config() }
}
impl DataActorNative for EmaCross {
    fn core(&self) -> &DataActorCore { /* self.core 里的 DataActorCore */ }
    fn core_mut(&mut self) -> &mut DataActorCore { /* 同上 */ }
    fn dispatch_start(&mut self) -> anyhow::Result<()> {
        Strategy::on_start(self)?;     // 先跑框架的启动逻辑
        DataActor::on_start(self)      // 再跑你的 on_start
    }
}
impl StrategyNative for EmaCross {
    fn strategy_core(&self) -> &StrategyCore { &self.core }
    fn strategy_core_mut(&mut self) -> &mut StrategyCore { &mut self.core }
}
impl Strategy for EmaCross {}          // 宏的花括号里写的方法会放进这里
```

宏有四种写法：`nautilus_strategy!(T)`；字段不叫 `core` 时 `nautilus_strategy!(T, my_core)`；要覆盖 `Strategy` 的方法时 `nautilus_strategy!(T, { fn on_order_filled(&mut self, event: &OrderFilled) { … } })`；以及两者同时用。也就是说，订单和仓位回调不是写在单独的 `impl Strategy` 里，而是写进宏的花括号。

## 3. `StrategyCore` 与 `StrategyConfig`

`StrategyCore::new(config)` 只是把配置存下来。它的其他部件（时钟、缓存、下单工厂、关联订单管理器、组合）都是 `Option`，注册到 `Trader` 时才填上。所以在构造函数里调用 `self.order()`、`self.cache()`、`self.subscribe_*()` 都会失败：这时它们还不存在。

`StrategyConfig`（`crates/trading/src/strategy/config.rs`）的字段可以分成五组：

| 分组 | 字段 | 说明 |
| --- | --- | --- |
| 身份 | `strategy_id`、`order_id_tag` | 不配置时，策略 ID 由类型名和一个序号拼成，比如第 1 章跑的回测里是 `EMA_CROSS-001` |
| 订单号格式 | `use_uuid_client_order_ids`、`use_hyphens_in_client_order_ids` | 默认是 `O-日期-时间-交易员标签-策略标签-序号` 这样的可读格式 |
| 仓位 | `oms_type` | 覆盖交易所的 OMS 类型（Netting / Hedging），决定成交怎样归到仓位 |
| 托管功能 | `manage_contingent_orders`、`manage_gtd_expiry`、`manage_stop`、`market_exit_*` | 第 6 节 |
| 外部订单与日志 | `external_order_instrument_ids`、`log_events`、`log_commands` 等 | 认领不是本策略下的订单；控制事件和命令是否记日志 |

`EmaCrossConfig` 的做法值得照抄：自己的参数放在外层结构体里，`StrategyConfig` 作为 `base` 字段嵌进去，构造时 `StrategyCore::new(config.base)`。配置结构体用 `bon::Builder` 生成构造器，所以可以写 `EmaCrossConfig::builder().instrument_id(…).trade_size(…).build()`。

## 4. 注册：从 `new()` 到 `READY`

`BacktestEngine::add_strategy(strategy)` 和 `LiveNode::add_strategy(strategy)` 都把工作交给 `Trader::add_strategy`（`crates/system/src/trader.rs`），它按顺序做这些事：

1. **确定策略 ID。** 配置里有就用配置的；没有就用类型名加序号生成，并检查订单号标签不和已有策略重复。
2. **给这个组件建一个时钟。** 每个组件有自己的时钟实例（回测里是 `VirtualClock`，实盘里是 `LiveClock`），这样各自的计时器互不干扰。
3. **注册 `StrategyCore`**（`StrategyCore::register`）：把交易员 ID、时钟、缓存交给 `DataActorCore`；用交易员 ID、策略 ID 和时钟建一个 `OrderFactory`；建一个 `OrderManager`；挂上 `Portfolio`。
4. **登记默认的时间事件处理函数**：之后用 `clock.set_timer` 设的计时器，没指定回调时都会走到 `on_time_event`。
5. **`initialize()`**：组件状态从 `PRE_INITIALIZED` 变成 `READY`。
6. **放进两个全局注册表**：组件注册表（生命周期管理用）和 actor 注册表（回调派发时按 ID 取组件用，见第 10 章）。
7. **订阅订单和仓位事件**：`events.order.{strategy_id}`、`events.position.{strategy_id}`，以及市场退出之类的控制命令。

策略对象本身在第 6 步被移进了注册表，`add_strategy` 返回后你手里就没有它了。之后想访问它，只能通过回调里的 `self`。实盘节点还有一条限制：只能在 `run()` 之前添加策略，节点运行后再加会直接报错。

## 5. 运行：生命周期怎样推进

节点启动时，`Trader` 逐个调用组件的 `start()`。对策略来说，这一步发生的是：

```text
start()
  → 状态 READY → STARTING
  → dispatch_start()
       Strategy::on_start      框架：确认已注册；配置了 manage_gtd_expiry 时恢复 GTD 订单的过期计时器
       DataActor::on_start     你的代码：订阅行情、设置计时器
  → 状态 STARTING → RUNNING
```

之后的每一次行情、订单事件、计时器，都只在 `RUNNING` 状态下才会送到你的回调（第 10 章）。停止时 `stop()` 调用 `on_stop`，进入 `STOPPED`；`reset()` 调用 `on_reset`，清掉指标和自己的状态，回到 `READY`，可以再次启动（回测引擎跑多轮时就是这样）；`dispose()` 释放资源。任何一个回调返回错误，状态都会停在对应的过渡状态（如 `STARTING`）。

`on_reset` 是最容易漏的：回测引擎 `reset()` 后再跑一轮，策略对象是同一个，指标里还留着上一轮的数据。`EmaCross` 在 `on_reset` 里把两条均线和 `prev_fast_above` 都清掉了，就是这个原因。

## 6. 下单 API

**造订单。** `self.order()` 返回一个 `OrderApi`，它包着注册时建好的 `OrderFactory`，提供 `market`、`limit`、`stop_market`、`stop_limit`、`market_to_limit`、`market_if_touched`、`limit_if_touched`、`trailing_stop_market`、`trailing_stop_limit` 九种订单，以及组合订单 `bracket`（入场单加止盈止损）和 `create_list`。工厂负责生成 `ClientOrderId`，并把交易员 ID、策略 ID、当前时间填进订单。参数里大量的 `None` 表示用默认值（时间有效性、只减仓、执行算法、标签等）。

**提交和管理订单。** 这些都是 `Strategy` trait 的默认方法：

| 方法 | 做什么 |
| --- | --- |
| `submit_order(order, position_id, client_id, params)` | 订单写进缓存，发出 `OrderInitialized`，再按条件路由：设置了仿真触发的进 `OrderEmulator`，指定了执行算法的进算法，其余进 `RiskEngine` 排队（第 1 章第 5.2 节） |
| `submit_order_list(…)` | 提交一组关联订单，比如 `bracket` 造出来的 |
| `modify_order(client_order_id, quantity, price, trigger_price, …)` | 改数量、价格、触发价 |
| `cancel_order`、`cancel_orders`、`cancel_all_orders(instrument_id, order_side, …)` | 撤单 |
| `close_position(&position, …)`、`close_all_positions(…)` | 用一笔反向市价单平仓，本质还是 `submit_order` |
| `query_order`、`query_account` | 让执行客户端去交易所查询，结果以事件形式回来 |

这些方法都返回 `anyhow::Result`。返回 `Ok` 只表示命令发出去了，订单有没有被接受、有没有成交，要等后面的订单事件，在回调里处理。所以策略的写法总是“在一个回调里发命令，在另一个回调里看结果”。

**查询状态。** `self.cache()` 读缓存（拿到的是快照，第 0 章第 5.9 节），`self.portfolio()` 读组合的净头寸和盈亏，`self.clock()` 读时间、设计时器。

## 7. 托管功能：框架替你管的几件事

下面几项默认开或关由 `StrategyConfig` 决定，打开之后框架在订单事件的处理流程里替你做：

- **关联订单**（`manage_contingent_orders`）：`OrderManager` 跟踪 OCO（一个成交撤另一个）、OTO（一个成交后触发另一个）等关系，订单事件到来时自动撤单、改数量或提交下一笔。止盈止损组合靠它在本地维持，不依赖交易所是否原生支持。
- **GTD 过期**（`manage_gtd_expiry`）：对“到某时刻失效”的订单，框架用计时器在到期时撤单；订单进入终态时取消计时器，策略重启时恢复计时器（第 5 节里框架那段 `on_start` 做的就是这个）。
- **市场退出**（`market_exit()`）：撤掉本策略所有挂单、用市价单平掉所有仓位，并按 `market_exit_interval_ms` 反复检查，最多 `market_exit_max_attempts` 次，直到订单都结束、仓位都平掉。开始时调用 `on_market_exit`，完成后策略继续运行。
- **托管停止**（`manage_stop`）：打开后，`stop()` 不会立刻停止，而是先完成（或发起）一次市场退出，再进入 `STOPPED`。实盘里想“停策略时顺带清仓”就打开它。
- **认领外部订单**（`external_order_instrument_ids`）：对账时发现的、不是本系统下的订单（比如在券商 App 上手动下的），可以按标的认领给这个策略，之后它的事件就会送到这个策略的回调。

## 8. 跑起来：回测和实盘

回测（`crates/backtest/examples/engine_ema_cross.rs`，第 0 章的从零编译里实际跑过）：

```rust
// 节选自 crates/backtest/examples/engine_ema_cross.rs
let mut engine = BacktestEngine::new(BacktestEngineConfig::default())?;
engine.add_venue(/* SimulatedVenueConfig：交易所、OMS、账户类型、初始资金 … */)?;
engine.add_instrument(&instrument)?;
engine.add_strategy(EmaCross::new(instrument_id, Quantity::from("100000"), 10, 20))?;
engine.add_data(quotes, None, true, true)?;
engine.run(None, None, None, false)?;
```

实盘（`examples/tutorials/src/bin/lighter_nvda_composite_mm.rs`）：

```rust
// 节选自 examples/tutorials/src/bin/lighter_nvda_composite_mm.rs
let mut node = LiveNode::builder(trader_id, environment)?
    .add_data_client(/* 数据客户端的名字、工厂、配置 */)?
    .add_exec_client(/* 执行客户端的名字、工厂、配置 */)?
    .build()?;
node.add_strategy(CompositeMarketMaker::new(strategy_config))?;
node.run().await?;
```

同一个策略类型在两处的代码完全一样，换的只是外壳（第 1 章第 7 节）。在自己的项目里写策略时，按[从零编译](./build-from-source.md)第 3.6 节用 git 依赖引入 `nautilus-trading`、`nautilus-backtest` 等 crate；宏展开时用到的类型由 `nautilus-trading` 的 `_macro_reexports` 重新导出，不需要你额外引入。

仓库里还有几个更完整的示例策略值得读：`orderbook_imbalance`（订单簿不平衡）、`grid_mm`（网格做市）、`composite_market_maker`（组合做市）、`delta_neutral_vol`（期权 Delta 中性）、`hurst_vpin_directional`，都在 `crates/trading/src/examples/strategies/` 下，每个都带 `tests.rs`。

::: warning 常见误区
- **在构造函数里订阅或造订单。** 那时 `StrategyCore` 还没注册，时钟、缓存、下单工厂都不存在；放到 `on_start` 里。
- **把订单回调写进单独的 `impl Strategy`。** 宏已经生成了 `impl Strategy`，再写一个会冲突；要覆盖的方法写进宏的花括号。
- **以为 `submit_order` 返回 `Ok` 就是下单成功。** 那只是命令发出去了，结果看后面的订单事件。
- **忘了 `on_reset`。** 回测多轮运行时，指标和自己的状态会带到下一轮。
- **`add_strategy` 之后还想用原来的变量访问策略。** 策略已经被移进注册表，只能在回调里通过 `self` 访问。
- **实盘节点运行后再加策略。** 只能在 `run()` 之前添加。
:::

## 本章结论

一个 Rust 策略是三部分拼起来的：你写持有 `StrategyCore` 的结构体和 `impl DataActor` 里的回调，`nautilus_strategy!` 宏生成把核心交给框架的样板代码，框架用默认方法提供订阅、下单、派发和生命周期管理。注册到 `Trader` 时，`StrategyCore` 才拿到时钟、缓存、下单工厂、关联订单管理器和组合，并开始接收订单和仓位事件。之后的运行完全由回调驱动：在 `on_start` 里订阅，在数据回调里下单，在订单回调里看结果。

## 检查理解

1. 为什么 `EmaCross` 的 `on_quote` 写在 `impl DataActor` 里，而 `on_order_filled` 要写进宏的花括号？

   <details><summary>参考答案</summary>

   `on_quote` 是 `DataActor` trait 的方法，所有能收数据的组件都有；`on_order_filled` 是 `Strategy` trait 的方法。宏已经为策略生成了 `impl Strategy for EmaCross {}`，同一个类型不能有两个 `impl Strategy`，所以要覆盖 `Strategy` 的方法，只能把它们放进宏的花括号，让宏把它们放进自己生成的那个 `impl` 里。

   </details>

2. 回测引擎 `reset()` 后再跑一轮，为什么必须在 `on_reset` 里清掉指标？

   <details><summary>参考答案</summary>

   策略对象在注册时被移进了注册表，`reset()` 不会重新构造它，只会让它回到 `READY` 并调用 `on_reset`。指标是策略结构体里的字段，不清掉就会带着上一轮的数据进入下一轮，均线的初值和交叉判断都会错。

   </details>

3. 打开 `manage_stop` 后调用 `stop()`，策略会立刻进入 `STOPPED` 吗？

   <details><summary>参考答案</summary>

   不会。框架会先完成正在进行的市场退出，或者发起一次：撤掉所有挂单、平掉所有仓位，按配置的间隔和次数检查，结束后才真正停止。

   </details>

## 参考资料

- 官方文档：[Strategies](https://github.com/nautechsystems/nautilus_trader/blob/develop/docs/concepts/strategies.md) · [Actors](https://github.com/nautechsystems/nautilus_trader/blob/develop/docs/concepts/actors.md) · [Rust](https://github.com/nautechsystems/nautilus_trader/blob/develop/docs/concepts/rust.md)
- 源码：[`crates/trading/src/strategy/`](https://github.com/nautechsystems/nautilus_trader/tree/develop/crates/trading/src/strategy) · [`crates/trading/src/macros.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/trading/src/macros.rs) · [`crates/trading/src/examples/strategies/`](https://github.com/nautechsystems/nautilus_trader/tree/develop/crates/trading/src/examples/strategies) · [`crates/system/src/trader.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/system/src/trader.rs)
- 配图由 `scripts/generate-nautilus-trader-figures.py` 生成。

框架会在什么时候、以什么顺序调用这些回调，下一章细讲：[第 10 章：回调：一条消息怎样变成 on_xxx](./callbacks.md)。
