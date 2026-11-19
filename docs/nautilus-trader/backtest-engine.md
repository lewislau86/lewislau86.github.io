---
title: "第 24 章：BacktestEngine 与 BacktestNode"
description: 回测引擎由什么组成；加入交易所、品种、策略和数据时各发生什么；多条数据流怎样按时间合并、相同时间戳谁先；主循环处理一条数据的三个阶段，以及命令为什么要排队、怎样在同一时刻结清；end、reset、dispose 各做什么；BacktestNode 怎样从配置建引擎、一次性加载与分块流式运行有什么不同；怎样做参数扫描。
---

# 第 24 章：BacktestEngine 与 BacktestNode

[全书目录](./index.md) · [上一章](./trader.md) · [下一章](./data-catalog.md)

::: tip 本章学习目标
能用 `BacktestEngine` 从零搭一个回测，说出 `add_venue` 替你建了哪些对象；能解释多条数据流在相同时间戳上谁先谁后；能按顺序说出主循环处理一条数据的三个阶段，以及策略在回调里下的单什么时候到达模拟交易所；知道 `end`、`reset`、`dispose` 的区别；能在一次性加载和分块流式两种 `BacktestNode` 运行方式之间做选择。

**源码版本：** `develop` 分支，提交 `364254f`（2026-11-18）。回测引擎在 `crates/backtest/src/engine.rs`，节点在 `node.rs`，配置在 `config.rs`，结果在 `result.rs`，数据迭代器在 `data_iterator.rs` 和 `crates/data/src/replay/iterator.rs`，同步命令队列在 `crates/common/src/runner.rs`。示例是 `crates/backtest/examples/engine_ema_cross.rs` 和 `node_ema_cross.rs`。

**对应官方文档：** [Backtesting](https://nautilustrader.io/docs/latest/concepts/backtesting/)（APIs and Repeated Runs、Execution Flow 两页）
:::

第三部分拆开了内核的每个组件。回测就是把这些组件放进一个由数据驱动的循环里：数据按时间顺序一条条播放，时钟跟着数据走，交易所由本地的模拟交易所代替。这一章看这个循环本身，下一章看数据从哪里来，第 26、27 章看模拟交易所怎样撮合。

主线例子是官方的 `engine_ema_cross` 示例，也是“动手准备”里跑通的那个：一个名为 `SIM` 的模拟交易所（HEDGING、保证金账户、L1 订单簿、初始资金 100 万美元），品种 `AUD/USD.SIM`，第 1 章那个 EMA 交叉策略（快线 10、慢线 20、每次 10 万），745 条每秒一条的报价。

## 1. 引擎由什么组成 {#structure}

`BacktestEngine` 是一层外壳，里面装着第 14 章的 `NautilusKernel`。它自己持有的东西不多：

- **内核**：用 `BacktestEngineConfig` 构造，环境是 `Backtest`，所以时钟是 `VirtualClock`（第 17 章）。构造时引擎会强制把缓存配置的 `drop_instruments_on_reset` 设为 `false`，因为重置后不会再调用一遍 `add_instrument`，品种必须留在缓存里。
- **交易所表** `venues`：每个场所一个 `SimulatedExchange`。
- **执行客户端列表** `exec_clients`：每个场所一个 `BacktestExecutionClient`。
- **数据迭代器** `data_iterator`：把多条数据流按时间合并的迭代器。
- **时间事件累加器** `accumulator`：收集所有组件时钟上到期的计时器，按时间顺序交给主循环（第 17 章第 4 节）。
- 运行状态：本次运行的 ID、起止时间、迭代次数、是否被要求停止等。

## 2. 搭一个回测 {#setup}

示例的 `main` 函数是这样写的：

```rust
let mut engine = BacktestEngine::new(BacktestEngineConfig::default())?;

engine.add_venue(
    SimulatedVenueConfig::builder()
        .venue(Venue::from("SIM"))
        .oms_type(OmsType::Hedging)
        .account_type(AccountType::Margin)
        .book_type(BookType::L1_MBP)
        .starting_balances(vec![Money::from("1_000_000 USD")])
        .fee_model(FeeModelAny::MakerTaker(MakerTakerFeeModel::zero()).into())
        .build()?,
)?;

let instrument = InstrumentAny::CurrencyPair(audusd_sim());
engine.add_instrument(&instrument)?;
engine.add_strategy(EmaCross::new(instrument.id(), Quantity::from("100000"), 10, 20))?;
engine.add_data(generate_quotes(instrument.id()), None, true, true)?;
engine.run(None, None, None, false)?;
```

每一步背后发生的事：

**`add_venue`** 一次建好一个场所需要的全部对象：

1. 一个 `SimulatedExchange`，和内核共享缓存与时钟（第 26 章）；
2. 一个 `BacktestExecutionClient`，账户 ID 固定为 `{venue}-001`，这里是 `SIM-001`；
3. 把客户端登记到执行引擎，并把场所 `SIM` 路由到它（第 20 章第 1 节）；
4. 把客户端注册到交易所，交易所产生的订单事件经它回到执行引擎。

同一个场所加两次会报错。

**`add_instrument`** 要求场所已经加过。它把品种交给这个场所的交易所（交易所为它建一个撮合引擎），品种有到期时间的话设一个到期计时器；然后为这个场所建一个回测用的数据客户端（如果还没有），再把品种交给数据引擎写入缓存。同一个品种定义再加一次什么都不做，同一个 ID 换了定义会报错。有一条限制：单一币种的现金账户上不能加货币对这类多币种现货。

**`add_strategy`** 交给 `Trader::add_strategy`（第 23 章），并把策略配置里的 `oms_type` 登记到执行引擎。

**`add_data`** 每调用一次就新建一条命名数据流（`backtest_data_0`、`backtest_data_1`…），同时记下涉及哪些品种、数据的最早和最晚时间。最早和最晚时间就是 `run(None, None, …)` 时默认的起止时间。

## 3. 多条数据流怎样合并 {#streams}

数据迭代器把每条流先按时间排好，然后用一个最小堆做多路归并，每次取出所有流里时间最早的那一条。比较的键依次是：

1. 数据的 `ts_init`；
2. 流的优先级：先加入的流优先；
3. 在流内的位置：保持原来的先后。

所以相同时间戳的数据，先 `add_data` 的那一批先播放。官方文档举的例子很实用：如果策略在 `on_bar` 里要用到同一时刻的自定义数据，就要先 `add_data(flows)` 再 `add_data(bars)`，否则 `on_bar` 先被调用，那一刻的自定义数据还没到。

`add_data` 的最后一个参数 `sort` 在 Python 文档里的意思是“是否排序”。在 Rust 实现里，每条流加入时总会按时间排序，这个参数只影响一个“已就绪”的标记：传 `false` 后，`run` 会报错要求先调用 `sort_data()`。这个设计是为了让分批加载数据的代码显式地声明“数据已经加完”。

## 4. 主循环：一条数据经过的三个阶段 {#loop}

`run` 先做初始化：把所有时钟设到开始时间，初始化各交易所的账户，启动内核，再启动 Trader（策略的 `on_start` 在这里被调用）。启动 Trader 后，引擎先把 `on_start` 里发出的数据订阅命令处理完，这样内部 K 线聚合器在第一条数据到来前就已经订阅好，不会漏掉第一笔成交。

然后进入主循环。对每一个数据时间戳 `T`，第 17 章讲过计时器的规则：严格早于 `T` 的计时器先执行，恰好在 `T` 的计时器在这一时刻的数据之后执行。夹在中间的“处理一条数据”（`replay_data_row`）分三个阶段：

1. **交易所先看到数据。** `route_data_to_exchange` 把报价、成交、K 线、订单簿数据交给对应场所的模拟交易所，交易所更新它的订单簿，并让已经挂着的订单和新行情撮合。品种定义、指数价格、期权希腊值和自定义数据不经过交易所。
2. **策略再看到数据。** 数据交给数据引擎（`process_data_ref`），写缓存、发布，策略的 `on_quote` 等回调被调用。策略在回调里下的单不会立即执行，而是进入一个线程局部的交易命令队列。
3. **结清命令。** `drain_command_queues` 依次处理交易命令队列、数据命令队列、执行客户端缓冲的事件和待派发的回调，直到全部为空；然后 `settle_venues` 让有待处理命令的交易所处理它们、再撮合一次，撮合产生的成交又可能让策略发出新的命令（比如在 `on_order_filled` 里下止损单），于是循环，直到没有交易所还有到期的命令。

顺序的意义在于：已经挂着的订单先于新订单看到新行情。一张在 `T` 时刻收到报价后才提交的市价单，按 `T` 时刻的报价成交，而不会“提前”和这条报价之前的挂单抢同一个价格。

![回测主循环处理一个时间戳 T：先执行早于 T 的计时器；交易所用新数据撮合已挂订单；数据引擎把数据交给策略，策略的命令进入队列；结清阶段反复处理命令队列、交易所命令和撮合，直到没有新命令；最后执行恰好在 T 的计时器，运行模拟模块和强平检查](/nautilus-trader/figures/backtest-loop.svg)

怎么读这张图：从上到下是处理一个时间戳的顺序。右边的回环是第三阶段：命令、撮合、成交回调、新命令，直到队列为空。最下面一格在这个时间戳的最后一条数据处理完之后才执行。

主线例子里，当某条报价让快线上穿慢线时，策略在 `on_quote` 里提交一张买入 10 万的市价单。这张单先进入队列；第三阶段里它依次经过风控、执行引擎，到达执行客户端，客户端生成 `OrderSubmitted` 并把命令交给交易所；交易所在 `settle_venues` 里处理它，按这条报价的卖价成交；成交事件经执行引擎回到策略。这一切都发生在同一个时间戳里，下一条报价到来之前。

**命令为什么要排队。** 策略的回调是在数据引擎派发数据时被调用的，那时数据引擎、缓存都处于借用之中。如果下单立即同步执行，一路调用到交易所再回到执行引擎，很容易在同一个 `RefCell` 上重复借用。回测启动时引擎把命令发送器换成同步队列版本（`SyncTradingCommandSender`），命令先入队，等派发结束后由主循环统一处理。实盘用的是另一种发送器，命令在事件循环的下一轮处理（第 30 章）。执行客户端出于同样的原因，也先把 `OrderSubmitted` 缓冲起来。

**一个时间戳的收尾。** 这一时刻的最后一条数据处理完后，引擎执行恰好在 `T` 的计时器，再调用 `finalize_timestamp`：再次结清命令，结算到期的资金费率，然后运行各交易所的模拟模块（比如外汇隔夜利息，第 27 章），最后做强平检查。模块和强平每个时间戳只运行一次。

数据全部播完以后，如果不是流式运行，引擎还会继续推进时钟，把结束时间之前剩下的计时器执行完（`process_next_timer`）。

## 5. 结束、重置与释放 {#end}

非流式的 `run` 在播放完数据后自动调用 `end()`。`end` 的顺序是：

1. 把计时器推进到结束时间；
2. 结清这一时刻已到期的命令，让策略在停止前看到最终状态；
3. 停止 Trader，策略的 `on_stop` 被调用；
4. 再结清一次 `on_stop` 里发出的命令（比如平掉所有仓位）。如果配置了延迟模型，时钟会被推进到最后一条在途命令的到达时间，保证它们也被处理；
5. 如果还有策略处于 `RUNNING`（比如 `manage_stop` 的市场退出没有完成），记一条错误；
6. 保存组件状态，记录最后一个权益快照，停止三大引擎，切回实时日志时钟，打印运行后的统计。

`on_stop` 发出的平仓单产生的成交，不会再调用策略的 `on_order_filled`，因为策略此时已经是 `STOPPED`（第 23 章）。需要对这些成交做反应的逻辑，要在 `on_stop` 返回之前完成。

`reset()` 让引擎可以再跑一轮：停止并重置数据引擎、执行引擎、风控引擎、仿真器、各交易所、Trader 和 Portfolio，清空本次运行的状态和计时器，把所有数据流的游标拨回开头。保留的是：加入过的数据、场所、品种、策略和其他组件。`dispose()` 是最终释放，之后引擎不能再用。

`get_result()` 返回一个 `BacktestResult`：运行 ID、起止时间、迭代次数、事件数、订单数、仓位数，以及收益、盈亏和一般统计（第 28 章）。主线例子的结果是 745 次迭代、12 张订单、12 个仓位。

## 6. BacktestNode：从配置运行 {#node}

`BacktestEngine` 适合数据已经在内存里、或者你想自己控制每一步的情况。`BacktestNode` 则从配置出发，数据来自 Parquet 数据目录（第 25 章）。一个 `BacktestRunConfig` 描述一次运行：

| 字段 | 含义 |
| --- | --- |
| `venues` | 场所配置列表 |
| `data` | 数据配置列表：数据类型、目录、品种、时间范围 |
| `engine` | 引擎配置，默认值即可 |
| `chunk_size` | 分块大小，`None` 表示一次性加载 |
| `start`、`end` | 回测时间范围 |
| `raise_exception` | 出错时是否中断，默认 `false`（只记日志） |
| `dispose_on_completion` | 跑完是否释放引擎，默认 `true` |

`node_ema_cross` 示例先把同样的 745 条报价写进一个临时数据目录，然后：

```rust
let mut node = BacktestNode::new(vec![run_config])?;
node.build()?;                                   // 建引擎、加场所、从目录加载品种
node.get_engine_mut(RUN_ID).unwrap()
    .add_strategy(EmaCross::new(instrument_id, Quantity::from("100000"), 10, 20))?;
node.run()?;
```

`build` 为每个运行配置建一个 `BacktestEngine`，加入场所，并从数据目录读出数据配置涉及的品种加进去。策略要在 `build` 之后、`run` 之前通过 `get_engine_mut` 加入。

`run` 按 `chunk_size` 选择两种方式：

- **一次性加载**（`chunk_size = None`）：对每个数据配置从目录读出全部数据，各自 `add_data`，再运行一次。简单，但所有数据都要放得进内存。
- **分块流式**（`chunk_size` 在 1 到 100 万之间）：把所有数据配置的查询结果合并成一条按时间有序的流，每次取出大约 `chunk_size` 条，`add_data` 后以 `streaming = true` 运行，然后 `clear_data`，再取下一块，最后调用 `end()`。取块时会把同一时间戳的数据放在同一块里，订单簿增量也会凑齐一个完整事件，所以实际块大小可能超过 `chunk_size`。

流式运行时，`run` 在数据耗尽时暂停，不推进到批次之后的计时器，也不调用 `end()`；下一块的开始时间接着上一块的结束时间，时钟连续。直接用 `BacktestEngine` 时也可以这样手动分批，流程完全相同。

订单簿增量数据默认按事件成批播放（`batch_deltas = true`）：同一品种的增量攒到带 `F_LAST` 标志的那一条为止，作为一个 `OrderBookDeltas` 播放。撮合引擎因此只会看到完整事件之后的订单簿，不会和一个“更新到一半”的订单簿撮合。

## 7. 重复运行与参数扫描 {#repeat}

两种做法各有用途：

- **复用数据：** 同一个 `BacktestEngine`，跑完后 `reset()`，换掉策略（`clear_strategies` 再 `add_strategy`），再 `run()`。数据只加载一次，适合在同一份数据上扫参数。
- **独立运行：** 每组配置建一个新的 `BacktestNode`，跑完 `dispose()`。互不影响，适合配置差别大或要并行的情况。

`reset()` 之后，策略对象还是原来那个，指标和策略自己的字段要在 `on_reset` 里清掉（第 9 章）。另外，模拟交易所生成的成交 ID 是确定的，格式为 `T-{哈希}-{计数}`，哈希由场所、内部编号和 `ts_init` 算出。同样的数据每次运行得到同样的 ID，便于比较两次运行的输出；因为 `ts_init` 来自数据，`reset()` 之后也不会和缓存里旧的 ID 冲突。

::: warning 常见误区
- **以为策略在 `on_quote` 里下的单立即成交。** 它先进入命令队列，在这个时间戳的第三阶段才到达交易所；成交价是这一时刻的行情，不会和更早的挂单抢价格。
- **相同时间戳的两类数据，没注意 `add_data` 的顺序。** 先加入的流先播放。
- **在 `on_stop` 里平仓，又指望 `on_order_filled` 处理这些成交。** 策略已经停止，回调不会被调用。
- **`reset()` 后指标还留着上一轮的数据。** 要在 `on_reset` 里清掉。
- **在 `build()` 之前给 `BacktestNode` 加策略。** 引擎在 `build()` 时才建出来。
- **用 L2 或 L3 订单簿类型的场所，却只提供报价或 K 线数据。** `run` 会报错，要么把 `book_type` 改成 `L1_MBP`，要么提供订单簿数据。
:::

## 本章结论

`BacktestEngine` 把内核、每个场所一套模拟交易所和执行客户端、一个多路归并的数据迭代器装在一起。数据按 `ts_init`、加入顺序和流内顺序播放；每条数据先交给交易所撮合已挂订单，再交给数据引擎和策略，策略的命令进入同步队列，在第三阶段反复结清，直到这一时刻没有新命令。计时器按第 17 章的规则插在数据之间，每个时间戳最后运行模拟模块和强平检查。`end` 停止 Trader 并结清 `on_stop` 的命令，`reset` 保留数据和组件、清空状态。`BacktestNode` 从配置建引擎、从数据目录加载数据，可以一次性加载，也可以按时间对齐的块流式运行。

## 检查理解

1. 时间戳 `T` 有一条报价。策略在 `on_quote` 里提交一张买入市价单，成交后又在 `on_order_filled` 里提交一张止损单。这两张单分别在什么时候到达交易所？止损单会不会等到下一条报价？

   <details><summary>参考答案</summary>

   两张单都在时间戳 `T` 的第三阶段到达交易所。市价单在第一次结清时被处理、按 `T` 的报价成交；成交事件回到策略，`on_order_filled` 发出的止损单进入队列，`settle_venues` 的循环发现还有命令，再处理一轮，止损单被挂到交易所。它不会等到下一条报价，但它是否被触发要看之后的行情。

   </details>

2. 你有分钟 K 线和同一时刻发布的自定义资金流数据，策略在 `on_bar` 里要用这一分钟的资金流。应该怎样加入数据？

   <details><summary>参考答案</summary>

   先 `add_data(资金流)`，再 `add_data(K 线)`。相同 `ts_init` 时先加入的流优先，于是 `on_data` 先拿到资金流，`on_bar` 被调用时状态已经更新。同时要确认资金流的 `ts_init` 是它实际可用的时间，不能晚于 K 线。

   </details>

3. 用同一份数据扫 50 组参数，用 `BacktestEngine` 的 `reset()` 和每组新建一个 `BacktestNode` 各有什么利弊？

   <details><summary>参考答案</summary>

   `reset()` 复用已加载的数据和场所设置，省掉 50 次读数据的开销，但要求策略的 `on_reset` 把状态清干净，否则上一轮会影响下一轮，而且只能串行。每组新建节点彼此完全独立，不怕残留状态，可以在多个进程里并行，但每次都要重新从数据目录加载数据。数据量大时，可以在单个进程里用 `reset()`，再按进程分组并行。

   </details>

## 参考资料

- 官方文档：[Backtesting](https://nautilustrader.io/docs/latest/concepts/backtesting/)（[APIs and Repeated Runs](https://nautilustrader.io/docs/latest/concepts/backtesting/apis-and-runs/)、[Execution Flow](https://nautilustrader.io/docs/latest/concepts/backtesting/execution-flow/)）
- 源码：[`crates/backtest/src/engine.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/backtest/src/engine.rs) · [`crates/backtest/src/node.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/backtest/src/node.rs) · [`crates/backtest/src/config.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/backtest/src/config.rs) · [`crates/data/src/replay/iterator.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/data/src/replay/iterator.rs) · [`crates/backtest/examples/`](https://github.com/nautechsystems/nautilus_trader/tree/develop/crates/backtest/examples)
- 配图由 `scripts/generate-nautilus-trader-figures.py` 生成。

回测的数据从哪里来？`BacktestNode` 读的是 Parquet 数据目录。下一章看这个目录的文件布局、写入和查询。[第 25 章：数据目录](./data-catalog.md)。
