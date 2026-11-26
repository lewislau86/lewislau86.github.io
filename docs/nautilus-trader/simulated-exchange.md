---
title: "第 26 章：模拟交易所与撮合引擎"
description: SimulatedExchange 持有什么、命令怎样进入它；每个品种一个 OrderMatchingEngine，里面的订单簿、撮合核心和 ID 生成器各做什么；订单到达时的检查和按类型的处理；新行情到来时怎样撮合已挂订单；L1 订单簿上市价单、限价单、止损单的成交价规则；报价、成交、K 线、订单簿数据分别怎样驱动撮合，K 线怎样拆成四个价格点；场所配置的常用选项。
---

# 第 26 章：模拟交易所与撮合引擎

[全书目录](./index.md) · [上一章](./data-catalog.md) · [下一章](./behavioral-models.md)

::: tip 本章学习目标
能说出一条下单命令从回测执行客户端到撮合引擎经过哪些对象；能解释一张市价单、一张限价单、一张止损单到达时各自怎样处理；能在 L1 订单簿上手算市价单的成交价，包括数量超过盘口时的“剩余部分差一个价位”；知道哪些数据会更新撮合引擎的订单簿、哪些只交给策略；能解释 K 线回测时止损单为什么有时按触发价成交、有时按开盘价成交。

**源码版本：** `develop` 分支，提交 `364254f`（2026-11-18）。模拟交易所在 `crates/backtest/src/exchange.rs`，回测执行客户端在 `crates/backtest/src/execution_client.rs`，撮合引擎在 `crates/execution/src/matching_engine/`（`mod.rs`、`ids_generator.rs`、`config.rs`），撮合核心在 `crates/execution/src/matching.rs`，场所配置在 `crates/backtest/src/config.rs`。

**对应官方文档：** [Backtesting](https://nautilustrader.io/docs/latest/concepts/backtesting/)（Data and Venues、Fill Prices and Matching、Bar-Based Execution、Trade-Based Execution 几页）
:::

第 24 章说过，主循环每处理一条数据，先交给模拟交易所，再交给策略；策略的命令在第三阶段到达交易所。这一章打开模拟交易所，看它怎样接收命令、怎样用历史数据撮合，以及成交价是怎样定出来的。

主线例子：场所 `SIM` 使用 L1 订单簿，品种 `AUD/USD.SIM`，价格最小变动 0.00001。当前报价是买 0.65005 / 卖 0.65008，两边各 10 万。策略依次下三张单：一张已挂着的买入限价单 10 万 @ 0.65010（下面会看到它为什么还没成交），一张买入市价单 15 万，一张卖出止损单，触发价 0.64990。

## 1. 交易所里有什么 {#exchange}

`SimulatedExchange` 是一个场所的模拟。它持有：

- **场所级的设定**：OMS 类型、账户类型、订单簿类型、初始资金、杠杆，以及第 6 节的各种开关。
- **四个模型**：成交模型、手续费模型、可选的延迟模型、可选的保证金模型（第 27 章）。
- **撮合引擎表**：每个品种一个 `OrderMatchingEngine`，在 `add_instrument` 时建立。
- **两个命令队列**：一个普通队列 `message_queue`，一个按到达时间排序的在途队列 `inflight_queue`（有延迟模型时用）。
- **模拟模块**：每个时间戳末尾运行一次的插件，比如外汇隔夜利息（第 27 章）。
- **执行客户端**：交易所产生的订单事件经它回到执行引擎。

回测引擎在 `add_venue` 时一起建好交易所和 `BacktestExecutionClient`（第 24 章第 2 节）。策略下单后，命令经风控、执行引擎到达这个客户端；客户端先生成 `OrderSubmitted` 并缓冲起来，再调用交易所的 `send(command)`：

- 默认 `use_message_queue = true`：没有延迟模型时，命令进入普通队列；有延迟模型时，按模型算出的到达时间进入在途队列。主循环的 `settle_venues` 稍后处理到期的命令。
- `use_message_queue = false`：立即处理。

交易所不支持查询命令（查询订单、查询账户），收到时记一条警告。

账户由交易所在运行开始时初始化：按初始资金生成一个 `AccountState`，经执行客户端交给 Portfolio。

::: tip 和官方文档的差别
配置注释说 `frozen_account = true` 时“账户余额不随模拟交易变化”。但在这个提交的 Rust 回测里，`BacktestExecutionClient` 只把这个值存进一个带下划线前缀、没有被读取的字段 `_frozen_account`，交易所也不读它；真正使用它的只有沙盒执行客户端（关闭账户的本地计算）。在 Rust 回测里依赖这个开关之前，先确认余额确实没有变化。
:::

## 2. 撮合引擎的组成 {#engine}

每个 `OrderMatchingEngine` 只管一个品种，主要部件是：

- **订单簿 `book`**：由数据维护的市场订单簿，按场所的 `book_type` 是 L1、L2 或 L3（第 4 章）。模拟成交**不会修改**这个订单簿，它始终是历史数据的样子。
- **撮合核心 `core`**：一个 `OrderMatchingCore`，按价格存放本地挂着的订单（买单、卖单，限价、止损分开），以及当前用于撮合的买价、卖价、最新价。第 21 章的订单仿真器用的也是同一个类型。
- **ID 生成器**：生成场所订单 ID 和仓位 ID，默认格式 `{场所}-{品种编号}-{计数}`，比如 `SIM-1-1`；`use_random_ids = true` 时改用 UUID。成交 ID 是确定的哈希（第 24 章第 7 节）。
- **成交模型和手续费模型**：从交易所传进来。
- 一些附加状态：流动性消耗计数、队列位置、K 线执行用的状态等。

## 3. 订单到达时 {#orders}

交易所处理一条提交命令时，找到品种对应的撮合引擎，调用 `process_order`。先做一组检查，任何一项不通过就生成 `OrderRejected`：

- 合约已到期、尚未生效，或者市场不在交易状态；
- 数量、显示数量的精度和品种不符；价格、触发价的精度不符或不在品种的价格范围内；
- 场所关闭了只减仓支持（`use_reduce_only = false`）时，只减仓单被拒；
- OTO 子单的父单已被拒绝，或联动的订单已经关闭。

然后按订单类型处理：

| 类型 | 到达时 |
| --- | --- |
| 市价单 | 对面没有价格就拒绝（“No market”）；否则立即成交 |
| 限价单 | `post_only` 且会立即成交就拒绝；否则接受，能成交的部分按吃单成交，其余挂单 |
| 止损市价单 | 已经满足触发条件时，默认拒绝（`reject_stop_orders = true`）；否则接受并挂单 |
| 止损限价单等 | 和止损市价单类似，触发后按限价单处理 |

限价单是 IOC 或 FOK 且不能立即成交时直接撤销。市价单默认不产生 `OrderAccepted`，直接成交；`use_market_order_acks = true` 时先发一个接受事件。`AT_THE_OPEN`、`AT_THE_CLOSE` 两种有效期目前不支持。

主线例子的卖出止损单，触发价 0.64990。卖出止损的触发条件是 bid ≤ 触发价（第 21 章第 3 节），当前 bid 0.65005 高于它，所以止损单被接受、挂在撮合核心里。如果当时 bid 已经是 0.64980，这张单会被拒绝，原因写着“order stop px of 0.64990 was in the market … but rejected because of configuration”。

## 4. 新行情到来时 {#iterate}

数据经 `route_data_to_exchange` 进入交易所，交易所交给对应品种的撮合引擎。不同数据在不同订单簿类型下的作用不同：

| 数据 | L1 场所 | L2 / L3 场所 |
| --- | --- | --- |
| 报价 | 更新订单簿 | 忽略 |
| 成交 | 触发撮合 | 触发撮合 |
| K 线 | 拆成四个价格点更新订单簿 | 忽略 |
| 订单簿增量 | 忽略 | 更新订单簿 |
| 订单簿深度快照 | 更新订单簿 | 更新订单簿 |

“忽略”只是说撮合引擎不用它，策略照样能收到这些数据。反过来，NautilusTrader 不能从低级别的数据生成高级别的订单簿：L2 场所只有报价数据时，挂单永远不会成交，第 24 章第 7 节的误区说的就是这个，`run` 会直接报错。

更新订单簿之后，撮合引擎调用 `iterate`：

1. 让过期的 GTD 订单过期；
2. 把订单簿的最优买卖价设成撮合核心的当前价；
3. 市场开放时，先检查所有买单、再检查所有卖单是否满足成交或触发条件，对满足的执行成交或触发；
4. 维护追踪止损、检查合约到期等。

主线例子里，假设上一条报价是买 0.65012 / 卖 0.65015，策略当时挂出的买入限价 0.65010 没有成交（卖价高于限价）。新报价到来，卖价跌到 0.65008，低于限价，于是在第 3 步成交。

## 5. 成交价怎样定 {#prices}

### 5.1 L1 订单簿

L1 订单簿只有最优买卖价和各自的数量。规则是：

- **限价单作为挂单方被撮合**（像上面那张），按**自己的限价**成交：0.65010，而不是更好的 0.65008。这是保守的假设，模拟交易所不给挂单“价格改善”。
- **限价单到达时就能成交**（作为吃单方），按对面的最优价成交，但不会比限价差。
- **市价单**按对面的最优价成交，数量以盘口显示的数量为限；盘口数量用完后，**剩余部分全部按最后成交价差一个价位**成交。

主线例子的市价买单 15 万：卖一 0.65008 只有 10 万，先成交 10 万 @ 0.65008，剩下 5 万 @ 0.65009（差一个价位）。这条“剩余差一个价位”的规则是确定的，和第 27 章成交模型的随机滑点无关。它不会越过价格保护边界，也不会越过品种的最低、最高价。

- **止损市价单**（以及触价单、追踪止损市价单）触发后按市价单处理；但在 K 线回测里有一个例外，见 5.3。

### 5.2 L2、L3 订单簿

有深度数据时，市价单逐档吃掉对面的价位，直到数量满足；对面深度不够时部分成交。限价单作为吃单方逐档吃到限价为止，作为挂单方按限价成交。

`price_protection_points` 可以限制市价单和止损市价单最多吃到离当前最优价多远：买单不超过 `ask + 点数 × 最小变动价位`，卖单不低于 `bid - 点数 × 最小变动价位`，超出的部分不成交。设为 0 表示不限制。

默认情况下，模拟成交不消耗订单簿的数量：同一档 10 万的卖量，可以让两张各 10 万的买单都成交。打开 `liquidity_consumption` 后，引擎记录每个价位已被消耗的数量，直到新的数据刷新这个价位。

### 5.3 成交数据和 K 线

**成交数据。** `trade_execution = true`（默认）时，一笔成交被当作“这个价格有人成交过”的证据：卖方主动的成交可以撮合挂着的买单，买方主动的成交可以撮合挂着的卖单，没有方向的成交两边都可能。撮合时，撮合核心的买卖价被临时移到成交价，撮合完再恢复。由成交触发的成交数量以这笔成交的数量为上限。

**K 线。** 只有在场所 `bar_execution = true`（默认）、订单簿是 L1、K 线来自外部（不是内部聚合）时，K 线才驱动撮合，而且必须是按时间聚合的 K 线。每根 K 线被拆成四个价格点：开、高、低、收，成交量平均分成四份（余数给收盘），每个点更新一次订单簿、撮合一次。默认顺序是开→高→低→收；`bar_adaptive_high_low_ordering = true` 时，开盘价离高点近就先走高点，离低点近就先走低点。四个点都处理完后，完整的 K 线才交给策略的 `on_bar`。所以策略在 `on_bar` 里下的单，最早也只能和这根 K 线的收盘价撮合。

同一品种有多种周期的外部 K 线时，撮合引擎只用周期最短的那一种，其余的不驱动撮合。

K 线回测对止损单有一条特殊规则：如果 K 线**开盘就越过了**触发价（跳空），按开盘的模拟价格成交；如果开盘还没触发、之后的高低点穿过了触发价，**按触发价成交**，假设价格是连续走过触发价的。例如卖出止损 100，下一根 K 线开盘 90，成交在 90；开盘 102、最低 98，成交在 100。

K 线的时间戳有一个约定：`ts_init` 必须是 K 线结束的时间。如果数据源用开始时间打时间戳，要加上一个周期，否则整根 K 线会在它形成之前就被看到。

## 6. 场所配置的常用选项 {#config}

`BacktestVenueConfig`（以及引擎直接使用的 `SimulatedVenueConfig`）里和撮合有关的选项：

| 选项 | 默认 | 作用 |
| --- | --- | --- |
| `book_type` | 必填 | `L1_MBP`、`L2_MBP` 或 `L3_MBO` |
| `bar_execution` | `true` | 外部 K 线驱动撮合 |
| `bar_adaptive_high_low_ordering` | `false` | 按离开盘价的远近决定高低点顺序 |
| `trade_execution` | `true` | 成交数据驱动撮合 |
| `liquidity_consumption` | `false` | 记录各价位已被消耗的数量 |
| `queue_position` | `false` | 跟踪挂单前面排队的数量 |
| `reject_stop_orders` | `true` | 到达时已触发的止损单拒绝 |
| `support_gtd_orders` | `true` | 支持 GTD 有效期 |
| `support_contingent_orders` | `true` | 支持 OTO、OCO、OUO |
| `use_reduce_only` | `true` | 执行只减仓约束 |
| `use_position_ids` | `true` | 场所生成仓位 ID |
| `use_random_ids` | `false` | 场所订单 ID 用 UUID |
| `use_market_order_acks` | `false` | 市价单先发接受事件 |
| `frozen_account` | `false` | 账户余额不变（见第 1 节的说明） |
| `price_protection_points` | 0 | 市价单最多吃到的价位数 |

此外还有 `oms_type`、`account_type`、`starting_balances`、`base_currency`、默认杠杆和按品种的杠杆、`allow_cash_borrowing`（现金账户是否允许余额为负）、`oto_trigger_mode`（OTO 子单在父单部分成交还是全部成交时释放），以及第 27 章的四个模型。

![模拟交易所的结构：左边是行情进入撮合引擎、更新订单簿并撮合；上方是命令经回测执行客户端进入交易所的队列，再由撮合引擎按订单类型处理；撮合引擎内部有订单簿、撮合核心、ID 生成器和成交、手续费模型；右边是产生的订单事件经执行客户端回到执行引擎；底部是 L1 上市价买单 15 万的成交价计算](/nautilus-trader/figures/simulated-exchange.svg)

怎么读这张图：中间的大框是一个品种的撮合引擎，它有两个入口：左边是行情，上边是命令。行情只更新订单簿、触发 `iterate`；命令进入撮合核心，或者立即成交。两条路的出口都是右边的订单事件。底部是主线例子的 L1 计算。

::: warning 常见误区
- **以为模拟成交会改变订单簿。** 历史订单簿保持不变；默认情况下同一档数量可以被多张模拟订单重复使用，需要更保守时打开 `liquidity_consumption`。
- **以为挂单被行情穿过时能拿到更好的价格。** 挂单方按自己的限价成交。
- **以为市价单大于盘口数量时会按盘口价全部成交。** L1 上剩余部分差一个价位成交。
- **在 L2 场所上只提供报价或 K 线。** 撮合引擎不用这些数据，挂单不会成交。
- **K 线用开始时间做 `ts_init`。** 会产生前视偏差，要用结束时间。
- **以为 `on_bar` 里下的单能按这根 K 线的开盘价成交。** 这根 K 线的四个价格点已经撮合完，最早按收盘时的状态成交。
- **止损单到达时已在触发区间，以为会立即成交。** 默认被拒绝，`reject_stop_orders = false` 时才立即成交。
:::

## 本章结论

模拟交易所为每个品种建一个撮合引擎，命令经回测执行客户端进入交易所的队列，再交给撮合引擎；行情经主循环进入撮合引擎，更新只读的订单簿后用 `iterate` 撮合挂单。订单到达时先做到期、市场状态、精度、价格范围和只减仓等检查，再按类型立即成交、接受挂单或拒绝。L1 上挂单方按限价成交，吃单方按对面最优价成交，市价单用完盘口数量后剩余部分差一个价位；L2、L3 上逐档吃深度，可以用价格保护限制。报价和 K 线只对 L1 场所有效，订单簿增量只对 L2、L3 有效，成交数据对两者都有效；K 线拆成开高低收四个点，止损单在 K 线内被穿过时按触发价成交、跳空时按开盘价成交。

## 检查理解

1. L1 场所，报价买 1.1000（20 万）/ 卖 1.1002（5 万），最小变动 0.0001。一张买入市价单 12 万会怎样成交？如果配置了 `price_protection_points = 0` 呢？

   <details><summary>参考答案</summary>

   先成交 5 万 @ 1.1002（盘口数量），剩余 7 万 @ 1.1003（最后成交价差一个价位）。`price_protection_points = 0` 表示不启用价格保护，结果相同。

   </details>

2. 只用 1 分钟 K 线回测，持有多头，挂着止盈（卖出限价 101）和止损（卖出止损 98），两者是 OUO 联动。下一根 K 线开 100、高 101.5、低 97.5、收 99。默认设置下哪张单先成交？打开 `bar_adaptive_high_low_ordering` 呢？

   <details><summary>参考答案</summary>

   默认顺序是开→高→低→收，先走到高点 101.5，止盈先成交（挂单方，按限价 101），场所的联动随即撤掉止损。打开自适应顺序后，开盘 100 离高点 101.5 的距离是 1.5，离低点 97.5 是 2.5，离高点更近，仍然先走高点，结果相同。如果开盘是 98.5，离低点更近，就会先走低点，止损按触发价 98 成交。这说明同一根 K 线里同时包含止盈和止损时，结果取决于一个假设，需要更细的数据才能确定。

   </details>

3. 你用报价数据做回测，场所配置成 `L2_MBP`，因为“深度更真实”。会发生什么？

   <details><summary>参考答案</summary>

   L2 场所的撮合引擎忽略报价，订单簿没有数据，挂单不会成交。回测引擎在 `run` 时会检查到这个品种有数据却没有订单簿数据，直接报错，提示把 `book_type` 改成 `L1_MBP` 或提供订单簿数据。NautilusTrader 不会从报价生成深度。

   </details>

## 参考资料

- 官方文档：[Data and Venues](https://nautilustrader.io/docs/latest/concepts/backtesting/data-and-venues/) · [Fill Prices and Matching](https://nautilustrader.io/docs/latest/concepts/backtesting/fill-prices-and-matching/) · [Bar-Based Execution](https://nautilustrader.io/docs/latest/concepts/backtesting/bar-execution/) · [Trade-Based Execution](https://nautilustrader.io/docs/latest/concepts/backtesting/trade-execution/)
- 源码：[`crates/backtest/src/exchange.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/backtest/src/exchange.rs) · [`crates/execution/src/matching_engine/mod.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/execution/src/matching_engine/mod.rs) · [`crates/execution/src/matching.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/execution/src/matching.rs) · [`crates/backtest/src/config.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/backtest/src/config.rs)
- 配图由 `scripts/generate-nautilus-trader-figures.py` 生成。

上面提到的成交模型、手续费模型、延迟模型和保证金模型，决定了模拟有多“真实”。下一章逐个看它们。[第 27 章：行为模型](./behavioral-models.md)。
