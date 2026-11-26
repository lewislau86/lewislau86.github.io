---
title: "第 4 章：行情数据与订单簿"
description: NautilusTrader 的内置行情类型有哪些、各带什么字段；订单簿增量的四种动作和 F_LAST、F_SNAPSHOT 标志怎样划定事件边界；OrderBook 怎样按 L1、L2、L3 三种类型维护，乱序、缺单、交叉时怎样处理；自有订单簿和过滤视图；自定义数据。
---

# 第 4 章：行情数据与订单簿

[全书目录](./index.md) · [上一章](./instruments.md) · [下一章](./orders.md)

::: tip 本章学习目标
能列出 `Data` 枚举里的内置行情类型和它们的关键字段；能读懂一串订单簿增量，说出每一步之后的盘口；知道 `F_LAST` 和 `F_SNAPSHOT` 为什么重要、漏了会怎样；知道 `OrderBook` 在三种类型下怎样存订单、遇到乱序和缺单时怎样处理；知道自有订单簿和过滤视图能回答什么问题。

**源码版本：** `develop` 分支，提交 `364254f`（2026-11-18）。行情类型在 `crates/model/src/data/`，订单簿在 `crates/model/src/orderbook/`，相关枚举在 `crates/model/src/enums.rs`，数据引擎的配置在 `crates/data/src/engine/config.rs`。

**对应官方文档：** [Data](https://nautilustrader.io/docs/latest/concepts/data/) · [Order Book](https://nautilustrader.io/docs/latest/concepts/order_book/) · [Custom Data](https://nautilustrader.io/docs/latest/concepts/custom_data/)
:::

前两章讲了“值”和“品种”，这一章看市场实际发来了什么。报价和成交都是一条一条的独立事实，最简单；订单簿不一样，交易所发来的是一串“改动”，本地要把它们按顺序应用到一本簿上，才能知道此刻的盘口。改动的顺序、边界和缺失，都会影响你看到的价格。

主线例子是一本 ETHUSDT 的二档订单簿：先收到一个快照，再收到更新、删除和一条“更新一个不存在的价位”，每一步都看看盘口变成了什么。

## 1. 内置行情类型 {#data-types}

所有行情在内核里都是 `Data` 枚举（`crates/model/src/data/mod.rs`）的一个变体：

```rust
// 节选自 crates/model/src/data/mod.rs
pub enum Data {
    Custom(CustomData),
    Instrument(Box<InstrumentAny>),
    BookDelta(OrderBookDelta),
    BookDeltas(Box<OrderBookDeltas>),
    BookDepth(Box<OrderBookDepth>), // This variant is significantly larger
    Quote(QuoteTick),
    Trade(TradeTick),
    Bar(Bar),
    MarkPrice(MarkPriceUpdate),
    IndexPrice(IndexPriceUpdate),
    FundingRate(FundingRateUpdate),
    OptionGreeks(OptionGreeks),
    InstrumentStatus(InstrumentStatus),
    InstrumentClose(InstrumentClose),
    #[cfg(feature = "defi")]
    Defi(Box<DefiData>),
}
```

大的变体（品种、增量批、深度快照、DeFi 数据）放在堆上，让枚举本身保持小，因为数量最多的报价和成交要在 channel 和总线里频繁搬运。各类型的关键字段：

| 类型 | 关键字段 | 说明 |
| :--- | :--- | :--- |
| `QuoteTick` | 买价、卖价、买量、卖量 | 最优一档报价 |
| `TradeTick` | 价格、数量、`aggressor_side`、`trade_id` | 一笔成交；主动方可以是 `Buy`、`Sell` 或 `NoAggressor` |
| `Bar` | `bar_type`、开高低收、成交量 | 见第 11 章 |
| `OrderBookDelta` | `action`、`order`、`flags`、`sequence` | 订单簿的一次改动 |
| `OrderBookDeltas` | 一组 `OrderBookDelta` | 同一事件的一批改动 |
| `OrderBookDepth` | 买卖各最多 10 档的 `BookOrder` 和档内订单数 | 深度快照 |
| `MarkPriceUpdate`、`IndexPriceUpdate` | `value` | 标记价、指数价 |
| `FundingRateUpdate` | `rate`（`Decimal`）、`interval`、`next_funding_ns` | 资金费率 |
| `InstrumentStatus` | `action`（15 种）、`is_trading`、`is_quoting`、`is_short_sell_restricted` | 交易状态变化，如开盘、停牌、熔断 |
| `InstrumentClose` | `close_price`、`close_type` | 收盘价或合约到期结算价 |
| `OptionGreeks` | Delta、Gamma 等 | 交易所给的希腊值 |

每个类型都带 `ts_event` 和 `ts_init`（含义见第 2 章第 7 节）。另外有两个细节值得一提。`OrderBookDepth` 的买卖两边是 `SmallVec<[BookOrder; 10]>`：10 档以内放在结构体里，超过 10 档也能放，只是转到堆上，所以官方文档说它是“可变深度、内联容量 10 档”，而不是固定十档。`FundingRateUpdate` 的费率用 `Decimal` 而不是 `Price`，因为费率可以是负数，而且精度和价格无关。

## 2. 订单簿增量：一次改动长什么样 {#deltas}

```rust
// 节选自 crates/model/src/data/{delta,order}.rs
pub struct OrderBookDelta {
    pub instrument_id: InstrumentId,
    pub action: BookAction,     // Add / Update / Delete / Clear
    pub order: BookOrder,
    pub flags: u8,              // RecordFlag 位标志
    pub sequence: u64,          // 交易所的序号
    pub ts_event: UnixNanos,
    pub ts_init: UnixNanos,
}
pub struct BookOrder {
    pub side: Option<OrderSide>,
    pub price: Price,
    pub size: Quantity,
    pub order_id: OrderId,      // u64；L3 簿里是真实的订单号
}
```

`flags` 用的是 `RecordFlag`（`enums.rs`）的四个有效位：

| 标志 | 值 | 含义 |
| :--- | :--- | :--- |
| `F_LAST` | 128 | 一个逻辑事件的最后一条改动 |
| `F_TOB` | 64 | 这条改动只描述最优一档 |
| `F_SNAPSHOT` | 32 | 这条改动属于一个快照，不是增量 |
| `F_MBP` | 16 | 这条改动按价位聚合（没有订单号） |

最要紧的是 `F_LAST`。交易所的一次撮合可能同时改动好几档，这几条增量在中间状态下的盘口没有意义，甚至可能是交叉的。数据引擎的配置项 `buffer_deltas` 打开时（默认关闭），引擎会把增量攒起来，直到遇到带 `F_LAST` 的那一条才一起发布。快照的约定是：先发一条 `Clear`，再发若干条 `Add` 重建整本簿，所有条目都带 `F_SNAPSHOT`，最后一条同时带 `F_SNAPSHOT | F_LAST`。

官方文档在这里用了一个警告框：如果一组改动的最后一条漏了 `F_LAST`，攒增量的消费者会一直攒下去、什么也不发布；只有一条 `Clear` 的空快照也一样要带 `F_LAST`。这是写适配器时最容易犯的错误之一（第 38 章）。

## 3. 主线例子：一步一步维护一本二档簿 {#walkthrough}

`OrderBook::new(instrument_id, BookType::L2_MBP)` 建一本空簿，然后依次应用下面四组增量（价格单位 USDT，数量单位 ETH）：

```text
① 快照   CLEAR                          flags=SNAPSHOT
         ADD   BUY  423.70 × 5.0        flags=SNAPSHOT
         ADD   BUY  423.60 × 3.0        flags=SNAPSHOT
         ADD   SELL 423.80 × 2.0        flags=SNAPSHOT
         ADD   SELL 423.90 × 4.0        flags=SNAPSHOT|LAST
② 更新   UPDATE BUY 423.70 × 1.5        flags=LAST
③ 删除   DELETE SELL 423.80             flags=LAST
④ 更新   UPDATE BUY 423.65 × 2.0        flags=LAST   ← 簿里没有这个价位
```

先猜一下每一步之后的最优买卖价，再看图。

![二档订单簿依次应用快照、更新、删除和一条更新不存在价位的增量后的四个状态：删除最优卖价后价差从 0.10 扩大到 0.20；更新一个不存在的价位等于新增](/nautilus-trader/figures/book-deltas.svg)

怎么读这张图：每一列是一步之后的整本簿，上半是卖盘、下半是买盘，橙色是这一步动过的档位。注意第 ④ 列：簿里本来没有 423.65 这一档，`UPDATE` 却让它出现了。

前三步符合直觉：快照之后最优买 423.70、最优卖 423.80，价差 0.10，中间价 423.75；第 ② 步只改了数量；第 ③ 步删掉最优卖价，最优卖变成 423.90，价差扩大到 0.20。

第 ④ 步要看源码。`BookLadder::update`（`orderbook/ladder.rs`）先按订单号去缓存里找这张单在哪个价位；找不到时并不报错，而是落到最后一段：

```rust
// 节选自 crates/model/src/orderbook/ladder.rs（BookLadder::update 的末尾）
// Only add if the order has positive size
if order.size.is_positive() {
    self.add(order, flags);
}
```

所以“更新一个不存在的订单”等于新增，数量为 0 的更新等于删除。删除一个不存在的订单则什么也不做（`remove_order` 找不到就直接返回）。这套“尽量接受”的语义让交易所重放或重复发送改动时，簿最终还能到达事件描述的状态。

二档簿里还有一个容易困惑的地方：增量里的 `order_id` 被忽略了。`pre_process_order`（`orderbook/aggregation.rs`）在应用之前改写订单号：`L2_MBP` 簿用价格算出订单号，每个价位只有一张“订单”；`L1_MBP` 簿用买卖方向当订单号，每边只有一档；`L3_MBO` 簿保留真实订单号，只有当增量带 `F_TOB` 或 `F_MBP`、或者订单号是 0 时才改写。

有了簿，就能问一些下单前关心的问题。`get_avg_px_for_quantity(qty, side)` 按簿上的挂单从最优价开始吃，算出均价：在第 ② 步之后买 3 ETH，先吃 423.80 的 2 个，再吃 423.90 的 1 个，均价是 `(2 × 423.80 + 1 × 423.90) ÷ 3 ≈ 423.833`；第 ③ 步之后同样买 3 ETH，全部在 423.90 成交。`get_worst_px_for_quantity`、`get_quantity_for_price`、`simulate_fills` 是同一类问题的不同问法。

## 4. 乱序、缺单与交叉 {#integrity}

交易所的增量流并不总是干净的。`OrderBook` 对几类异常的处理是（`orderbook/book.rs`，以及官方文档 Integrity checks 一节）：

<strong>乱序的改动照样应用。</strong>序号或时间戳倒退的增量和深度快照不会被拒绝，只保护簿的元数据：`ts_last` 永远不倒退，`sequence` 只在全量清空时允许重置。每遇到一次倒退记一条警告：普通增量每条一次，快照每次一条。有些交易所清空簿时会把序号从头开始，所以不带 `F_SNAPSHOT` 的全量 `Clear` 会把它的序号当成新的高水位。由报价或成交驱动的 `L1_MBP` 簿是例外：过期的报价或成交直接跳过，簿不变。

<strong>没有方向的改动。</strong>增量的 `side` 是 `None` 而订单号非 0 时，簿先按订单号查它在哪一边：查不到时，`Add` 返回 `BookIntegrityError::NoOrderSide`，`Update`、`Delete` 跳过；两边都查到时，`Add` 返回 `AmbiguousOrderSide`，`Update`、`Delete` 跳过并警告。

<strong>品种不匹配直接报错。</strong>`apply_delta`、`apply_deltas` 第一件事就是比较品种 ID，不一致返回 `InstrumentMismatch`。

<strong>交叉盘口不会自动检查。</strong>应用增量时不检查最优买价是否高于最优卖价。要检查得显式调用 `book_check_integrity`（`orderbook/analysis.rs`）：它检查 `L1_MBP` 每边不超过一档、`L2_MBP` 每个价位不超过一张单，以及最优买价不高于最优卖价（相等的“锁定盘口”是合法的）。实盘的订单簿一致性检查和断档恢复会用到它，见第 35 章。

## 5. 订阅方式与托管的簿 {#subscriptions}

策略可以用三种方式订阅订单簿：`subscribe_book_deltas` 收增量（回调 `on_book_deltas`），`subscribe_book_depth` 收深度快照（`on_book_depth`），`subscribe_book_at_interval` 按固定间隔收整本簿（`on_book`）。数据引擎为每个品种在缓存里维护一本“托管”的 `OrderBook`，它的数据源要么是增量、要么是深度快照，二者只能选一个：增量订阅和间隔订阅可以共用一本由增量维护的簿，但托管的深度订阅不能和它们同时存在，引擎会拒绝冲突的请求。想在增量之外顺便收深度回调，就把深度订阅设成 `managed=False`，这些回调不会更新缓存里的簿。订阅和簿的维护属于数据引擎，细节在第 18 章。

## 6. 自有订单簿与过滤视图 {#own-book}

做市一类策略常问：“这一档的挂单里，有多少是我自己的？”`OwnOrderBook`（`orderbook/own.rs`）专门记录自己的在途订单，按价位组织，和公开的簿结构平行。执行引擎的 `manage_own_order_books` 打开时，订单每次状态变化都会同步到自有簿：订单提交时加入（发往外部执行客户端的订单在收到第一个订单事件时加入），`Accepted`、`PartiallyFilled` 等非终态更新数量，`Filled`、`Canceled`、`Rejected` 等终态移除。`IOC`、`FOK` 订单和被本地仿真器持有的订单不进自有簿。

有了它，`book.filtered_view(Some(&own_book), …)` 返回一本减掉了自己挂单的新 `OrderBook`，所有分析方法（价差、均价等）在这本净簿上照样能用；`bids_filtered_as_map` 只要价位到数量的映射。过滤还可以按订单状态和挂单时长筛选，比如只扣除交易所已经确认、挂了超过一定时间的单。

## 7. 自定义数据 {#custom-data}

内置类型之外的数据（新闻、链上指标、自己的信号）用自定义数据承载。`Data::Custom(CustomData)` 是统一的外壳：里面是一个 `DataType`（类型名加元数据，用来区分订阅主题）和一个实现了 `CustomDataTrait` 的载荷，时间戳由载荷提供。载荷有两种写法：纯 Python 类，用 `register_custom_data_class` 登记，序列化经 Python 回调和 Arrow C 接口；或者在同一个二进制里用 `#[custom_data]` 宏声明的 Rust 类型，编解码全在 Rust 里。两种方式最后都落到同一个 `CustomData` 包装和进程级的注册表上，所以发布、订阅、写进数据目录的接口是一样的。

::: warning 常见误区
- **一组增量的最后一条漏了 `F_LAST`。** 打开 `buffer_deltas` 的消费者会一直攒、不发布；空快照的那条 `Clear` 也要带。
- **以为更新不存在的价位会报错。** 它等于新增；数量为 0 的更新等于删除；删除不存在的订单什么也不做。
- **以为应用增量时会检查交叉盘口。** 不会，要显式调用 `book_check_integrity`。
- **在二档簿里依赖增量的 `order_id`。** `L2_MBP` 簿按价格改写订单号，原值被忽略。
- **以为 `OrderBookDepth` 固定十档。** 它是可变深度，10 档是内联容量。
- **同时开托管的深度订阅和增量订阅。** 同一个品种的托管簿只能有一个数据源，引擎会拒绝。
:::

## 本章结论

内置行情类型都是 `Data` 枚举的变体，大的放在堆上；每条数据带 `ts_event` 和 `ts_init`。订单簿由一串带标志位的增量维护：`F_SNAPSHOT` 标出快照，`F_LAST` 标出一个事件的结尾，漏了它，攒增量的消费者就会卡住。`OrderBook` 按三种类型改写订单号，对乱序、重复和缺单采取“尽量应用”的语义，只保护元数据不倒退；交叉盘口要显式检查。自有订单簿记录自己的挂单，过滤视图回答“扣掉自己之后还剩多少流动性”。

## 检查理解

1. 一本 `L2_MBP` 簿当前最优卖价 423.80 × 2.0。收到 `UPDATE SELL 423.80 × 0`，再收到 `DELETE SELL 423.80`，簿会怎样？会报错吗？

   <details><summary>参考答案</summary>

   第一条把 423.80 这一档的数量更新为 0，`BookLevel` 会移除这张单，档位空了就整档删除。第二条删除时按订单号已经找不到，`remove_order` 直接返回，不报错。最终 423.80 这一档消失，最优卖价变成下一档。

   </details>

2. 适配器把交易所的一次快照拆成 1 条 `Clear` 和 20 条 `Add`，全部带了 `F_SNAPSHOT`，但忘了给最后一条加 `F_LAST`。在 `buffer_deltas=True` 的配置下，策略会看到什么？

   <details><summary>参考答案</summary>

   什么也看不到。数据引擎在遇到带 `F_LAST` 的增量之前一直缓冲，这 21 条增量会和后面的增量一起被攒着，直到某一条带 `F_LAST` 才一起发布。如果后续增量也都没有 `F_LAST`，订阅者就永远收不到。

   </details>

3. 做市策略在 423.70 挂了 3 ETH 的买单，公开簿显示 423.70 这一档共 5 ETH。怎样得到“扣掉自己之后”的买一数量？需要打开什么配置？

   <details><summary>参考答案</summary>

   打开执行引擎的 `manage_own_order_books`，让订单状态变化同步到 `OwnOrderBook`；然后用 `book.filtered_view(Some(&own_book), …)` 或 `bids_filtered_as_map`，423.70 这一档的净数量是 2 ETH。

   </details>

## 参考资料

- 官方文档：[Data](https://nautilustrader.io/docs/latest/concepts/data/) · [Order Book](https://nautilustrader.io/docs/latest/concepts/order_book/) · [Custom Data](https://nautilustrader.io/docs/latest/concepts/custom_data/)
- 源码：[`crates/model/src/data/`](https://github.com/nautechsystems/nautilus_trader/tree/develop/crates/model/src/data) · [`crates/model/src/orderbook/`](https://github.com/nautechsystems/nautilus_trader/tree/develop/crates/model/src/orderbook) · [`crates/model/src/enums.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/model/src/enums.rs) · [`crates/data/src/engine/config.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/data/src/engine/config.rs)
- 配图由 `scripts/generate-nautilus-trader-figures.py` 生成。

行情告诉你市场在哪里，下一章看你怎样对市场出手：订单有哪些类型、怎样随事件在状态之间迁移。[第 5 章：订单](./orders.md)。
