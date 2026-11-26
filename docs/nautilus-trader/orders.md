---
title: "第 5 章：订单：类型、有效期、状态机与条件单"
description: NautilusTrader 的九种订单类型各需要哪些价格字段，七种有效期和执行指令，订单状态机的 15 个状态和 19 种事件怎样驱动迁移，部分成交、重复成交和撤单后成交怎样处理，以及 OTO、OCO、OUO 条件单、括号单和本地仿真单。
---

# 第 5 章：订单：类型、有效期、状态机与条件单

[全书目录](./index.md) · [上一章](./market-data.md) · [下一章](./positions.md)

::: tip 本章学习目标
能为一个交易意图选对订单类型和执行指令，知道构造时会检查什么；能画出订单状态机的主路径，说出每个状态是“在途”“挂着”还是“已结束”，知道部分成交、重复成交、撤单后又成交时状态怎样变；理解括号单里 OTO 和 OUO 的关系，以及本地仿真单什么时候被释放。

**源码版本：** `develop` 分支，提交 `364254f`（2026-11-18）。订单在 `crates/model/src/orders/`（状态机在 `mod.rs`），订单事件在 `crates/model/src/events/order/`，枚举在 `crates/model/src/enums.rs`，下单工厂在 `crates/common/src/factories/order.rs`。

**对应官方文档：** [Orders](https://nautilustrader.io/docs/latest/concepts/orders/)（含 Advanced orders、Emulated orders 两页）
:::

第 9 章从写策略的角度讲过下单 API：`order_factory().limit(...)`、`submit_order(...)`。这一章看那个被提交的东西本身：一个订单由哪些字段组成，交易所和内核回来的每个事件怎样改变它，什么时候它算“结束了”。附录第 3 节用十几行带过的订单状态机，这里把它完整读一遍。

主线例子是一张 ETHUSDT 的括号单：以 423.50 限价买入 1 ETH，止盈 430.00、止损 420.00。

## 1. 九种订单类型 {#order-types}

`OrderAny`（`crates/model/src/orders/any.rs`）有 9 个变体，区别在于需要哪些价格：

| 类型 | 需要的价格 | 一句话 |
| :--- | :--- | :--- |
| `MARKET` | 无 | 按当前市场价成交 |
| `LIMIT` | `price` | 不劣于限价才成交 |
| `STOP_MARKET` | `trigger_price` | 触发后变成市价单 |
| `STOP_LIMIT` | `trigger_price`、`price` | 触发后变成限价单 |
| `MARKET_TO_LIMIT` | 无 | 先按市价成交，剩余部分以成交价挂限价 |
| `MARKET_IF_TOUCHED` | `trigger_price` | 价格触及后变成市价单（方向与止损相反） |
| `LIMIT_IF_TOUCHED` | `trigger_price`、`price` | 价格触及后变成限价单 |
| `TRAILING_STOP_MARKET` | `trailing_offset`，可选 `activation_price` | 触发价随市场追踪 |
| `TRAILING_STOP_LIMIT` | 再加 `limit_offset` | 追踪触发后挂限价 |

所有类型共用一个 `OrderCore`（`orders/mod.rs`），里面是身份（`trader_id`、`strategy_id`、`instrument_id`、`client_order_id`、交易所给的 `venue_order_id`）、方向和数量、有效期与执行指令、条件单关系（`contingency_type`、`order_list_id`、`linked_order_ids`、`parent_order_id`）、执行算法（`exec_algorithm_id` 等）、成交统计（`filled_qty`、`leaves_qty`、`avg_px`、`commissions`、`trade_ids`），以及全部事件历史 `events`。注意 `avg_px` 和 `slippage` 是 `Decimal`（第 2 章第 3 节）。

## 2. 有效期与执行指令 {#instructions}

`TimeInForce` 有 7 个取值：`GTC`（撤单前一直有效）、`IOC`（立即成交，剩余撤销）、`FOK`（全部成交否则全部撤销）、`GTD`（到指定时间失效）、`DAY`（当日有效）、`AT_THE_OPEN`、`AT_THE_CLOSE`（只在开盘或收盘集合竞价时有效）。

执行指令是订单上的几个开关：`post_only`（只做挂单方，会立即成交就拒绝）、`reduce_only`（只能减仓，不能开仓或加仓）、`quote_quantity`（数量以报价币计，例如“买 100 USDT 的 ETH”）、`display_qty`（冰山单的可见数量）、`expire_time`（`GTD` 的到期时间）、`emulation_trigger`（本地仿真，第 6 节）。

构造时模型本身只检查少数几条，在每个订单类型的 `new_checked` 里：数量必须为正；`display_qty` 不能大于数量；`GTD` 必须带非零的 `expire_time`；市价单不能是 `GTD`（“GTD not supported for Market orders”）。价格精度、数量上下限这些和品种有关的检查不在这里，而在风控引擎里（第 3 章第 3 节，第 19 章）。交易所支不支持某个指令，则由适配器和交易所决定。

触发类订单还要选 `TriggerType`：用最新成交价（`LAST_PRICE`）、买一卖一（`BID_ASK`，买单看卖一、卖单看买一）、连续两次（`DOUBLE_LAST`、`DOUBLE_BID_ASK`）、中间价、标记价、指数价，或者 `DEFAULT`（交易所默认）。这个选择在交易所那边只是一个参数，但在本地仿真时决定了仿真器要订阅哪种行情。

## 3. 状态机：15 个状态，19 种事件 {#state-machine}

`OrderStatus` 有 15 个取值，`OrderEventAny` 有 19 种事件。订单本身不会自己改状态，状态只随事件改变：每来一个事件，`OrderCore::apply(event)` 先用 `OrderStatus::transition` 查一张转移表，查不到就返回 `OrderError::InvalidStateTransition`，订单保持不变。

![订单状态机的主路径：本地创建、提交、交易所接受、部分成交、全部成交；左侧是本地仿真的分支，中间一行是挂着时的触发和改撤单中间态，最下面一行是六个终态](/nautilus-trader/figures/order-state-machine.svg)

怎么读这张图：颜色说明订单“在哪里”。蓝色是还在本地或在路上（`is_open` 和 `is_closed` 都为假），青色是挂在交易所上（`is_open` 为真），灰色是已经结束（`is_closed` 为真）。主路径是最上面一行。

转移表本身是一个大的 `match`，节选几行就能看出它的风格：

```rust
// 节选自 crates/model/src/orders/mod.rs（OrderStatus::transition）
let new_state = match (self, event) {
    (status, OrderEventAny::ModifyDenied(_) | OrderEventAny::CancelDenied(_)) => *status,
    (Self::Initialized, OrderEventAny::Submitted(_)) => Self::Submitted,
    (Self::Initialized, OrderEventAny::Accepted(_)) => Self::Accepted,   // External orders
    (Self::Submitted, OrderEventAny::Accepted(_)) => Self::Accepted,
    (Self::Submitted, OrderEventAny::Canceled(_)) => Self::Canceled,     // FOK and IOC cases
    (Self::Accepted, OrderEventAny::Triggered(_)) => Self::Triggered,
    (Self::Accepted, OrderEventAny::Filled(_)) => Self::Filled,
    (Self::Canceled, OrderEventAny::Filled(_)) => Self::Filled,          // Real world possibility
    (Self::PendingCancel, OrderEventAny::Accepted(_)) => Self::Accepted, // Allow failed cancel requests
    (Self::Filled, OrderEventAny::FillVoided(_)) => Self::Voided,
    // … 共约 90 行
    _ => return Err(OrderError::InvalidStateTransition),
};
```

几行注释透露了设计取向：这张表是照着真实交易所会发生的事写的，不是照着理想流程写的。

- <strong>外部订单可以跳步。</strong>在别处下的单（手机 App、另一个程序）被对账发现时，内核只能从 `INITIALIZED` 直接到 `ACCEPTED`、`CANCELED` 甚至 `TRIGGERED`（第 34 章）。
- <strong>撤单后还能成交。</strong>撤单请求和成交在网络上交错，交易所先确认了撤单、随后又推送一笔撤单前发生的成交，这在现实中会发生，所以 `CANCELED → FILLED` 和 `EXPIRED → FILLED` 都是合法的。
- <strong>改撤单失败要回到原状态。</strong>`PENDING_UPDATE`、`PENDING_CANCEL` 是“请求已发出、交易所还没回”的中间态。被拒绝时（`ModifyRejected`、`CancelRejected`）表里写的是保持中间态，真正的恢复由对应的处理函数用 `previous_status` 字段完成；`ModifyDenied`、`CancelDenied` 是本地拒绝（请求根本没发出去），任何状态下都保持不变。
- <strong>成交可以被撤销。</strong>`FillVoided` 表示交易所事后撤销了一笔成交，`FILLED` 会变成 `VOIDED`。

### 3.1 部分成交不在表里

先猜：表里 `(Accepted, Filled)` 写的是 `Filled`，那部分成交怎么变成 `PARTIALLY_FILLED`？答案在 `apply` 的后半段。转移表只判断“这个事件在当前状态下是否合法”，具体是部分还是全部，由 `update_fill_status` 按数量决定：

```rust
// 节选自 crates/model/src/orders/mod.rs（update_fill_status）
if new_filled_qty >= self.quantity {
    self.status = OrderStatus::Filled;
    self.ts_closed = Some(event.ts_event);
} else if matches!(source_status, OrderStatus::Canceled | OrderStatus::Expired) {
    self.status = source_status;                    // 撤单后的迟到成交：不重新打开
} else {
    self.status = OrderStatus::PartiallyFilled;
    if matches!(source_status, OrderStatus::PendingUpdate | OrderStatus::PendingCancel) {
        self.previous_status = Some(self.status);   // 改撤单在途：保持中间态，记下恢复目标
        self.status = source_status;
    }
}
```

这里还藏着两个细节：撤单后迟到的部分成交只累加数量、不把订单重新打开；如果累计成交超过了订单数量，超出部分记进 `overfill_qty`，而不是报错。

### 3.2 重复成交和价格更正

`apply` 在查表之前先按 `trade_id` 检查成交是否见过：同一个 `trade_id`、同一个价格，返回 `OrderError::DuplicateFill`，订单不变；同一个 `trade_id`、不同价格，则当作交易所的价格更正，改写那笔成交的价格。实盘里交易所重发成交回报很常见，适配器不需要自己去重，但必须保证 `trade_id` 稳定。

## 4. 主线例子：一张括号单的一生 {#bracket}

`OrderFactory::bracket`（`crates/common/src/factories/order.rs`）一次生成三张单和它们的关系。按我们的参数：

```text
入场  LIMIT       BUY  1 ETH @ 423.50   contingency=OTO  linked=[止损, 止盈]
止盈  LIMIT       SELL 1 ETH @ 430.00   contingency=OUO  parent=入场  linked=[止损]  reduce_only post_only
止损  STOP_MARKET SELL 1 ETH 触发 420.00 contingency=OUO  parent=入场  linked=[止盈]  reduce_only
```

工厂的默认值值得记住：入场默认是市价单（这里改成了限价），止盈默认 `LIMIT` 且 `post_only`，止损默认 `STOP_MARKET`，两张出场单都是 `reduce_only`，标签分别是 `ENTRY`、`TAKE_PROFIT`、`STOP_LOSS`。两张出场单之间默认是 OUO（一个成交就更新另一个的数量），而不是很多人以为的 OCO；数量相等时，一张全部成交会把另一张的目标数量降到 0，效果和 OCO 一样。

下面是这张单可能经历的事件序列，以及每一步之后入场单的状态：

| 步骤 | 事件 | 入场单状态 | 谁发出 |
| :--- | :--- | :--- | :--- |
| 1 | `OrderInitialized` | `INITIALIZED` | 下单工厂 |
| 2 | `OrderSubmitted` | `SUBMITTED` | 执行客户端（适配器），在把订单发往交易所时 |
| 3 | `OrderAccepted` | `ACCEPTED` | 适配器，转述交易所的确认 |
| 4 | `OrderFilled` 0.4 ETH | `PARTIALLY_FILLED` | 适配器 |
| 5 | `OrderFilled` 0.6 ETH | `FILLED` | 适配器 |

OTO 关系决定两张出场单什么时候放出去：回测交易所默认在入场第一次部分成交时就释放（`OtoTriggerMode.PARTIAL`），可以配成全部成交后再释放；实盘则取决于适配器，可能用交易所原生的条件单，也可能由本地的 `OrderManager` 管理（第 21 章）。之后止盈单在 430.00 全部成交，OUO 让止损单的目标数量变成 0，于是它被撤销，最终三张单分别以 `FILLED`、`FILLED`、`CANCELED` 结束。

这张表也说明了一件容易混淆的事：订单状态由事件决定，事件由谁发出各不相同。下单工厂只发 `OrderInitialized`，风控拒绝时发 `OrderDenied`；订单经过风控和执行引擎到达执行客户端后，由客户端发 `OrderSubmitted`（实盘适配器经 `live/src/execution/emitter.rs`，回测由撮合引擎代发），其余大部分事件来自适配器对交易所回报的翻译。每一种事件的字段和发布主题见第 8 章。

## 5. 订单组与条件单 {#contingency}

`ContingencyType` 有三种（对应 FIX 的 `ContingencyType <1385>`）：

- <strong>OTO（一触发多）。</strong>父单按触发条件放出子单。子单的数量会随父单的成交量调整，挂在仓位上的 `reduce_only` 子单还会被限制在当前仓位之内。
- <strong>OCO（一撤多）。</strong>一张成交（全部或部分），就请求撤销其他几张。
- <strong>OUO（一改多）。</strong>一张成交，就把其他几张的数量更新为这张的剩余数量；剩余为 0 时撤销。

几张有关系的单通常放进一个 `OrderList`（`orders/list.rs`），共享一个 `OrderListId`，用 `submit_order_list` 一起提交。官方文档在这里反复强调一点：工厂只负责生成订单和关系元数据，关系由谁来执行取决于运行环境。回测交易所可以在本地持有子单；实盘适配器可能映射成交易所原生的条件单，也可能把所有腿一起提交、拒绝整组，或者要求策略自己管理。所以同一张括号单在回测和实盘里的行为可能不同，接入新券商时要明确选一种（第 38 章）。

## 6. 本地仿真单 {#emulated}

交易所不支持某种条件单时，可以给订单设 `emulation_trigger`，让 `OrderEmulator` 在本地模拟它。提交后订单进入 `EMULATED` 状态：仿真器缓存原始的提交命令，订阅所需的行情，在本地的撮合核心里盯着价格。条件满足时，它把订单改写成一张市价单或限价单（再发一个 `OrderInitialized` 事件，把 `emulation_trigger` 清掉），发出 `OrderReleased`，状态变成 `RELEASED`，然后按正常路径提交。改写规则是：`LIMIT`、`STOP_MARKET`、`MARKET_IF_TOUCHED`、`TRAILING_STOP_MARKET` 释放成 `MARKET`；`STOP_LIMIT`、`LIMIT_IF_TOUCHED`、`TRAILING_STOP_LIMIT` 释放成 `LIMIT`；`MARKET` 和 `MARKET_TO_LIMIT` 不能仿真。订单号在改写前后保持不变。

官方文档用一个警告框提醒了仿真单最危险的地方：持有期间的仿真单不经过风控，也不冻结账户资金；风控检查发生在释放时。如果那时交易状态是 `HALTED`，或者余额已经不够，释放出来的单会被直接 `DENIED`，不会重试。一张被拒的止损单还会触发条件单处理，可能连带撤掉它的止盈单。仿真器的内部实现在第 21 章。

::: warning 常见误区
- **以为部分成交是转移表里的一个分支。** 表只判断事件是否合法，部分还是全部由成交数量决定。
- **把撤单后的成交当成错误。** `CANCELED → FILLED` 是合法转移，网络交错时会发生。
- **以为 `SUBMITTED` 的订单就在交易所的簿上。** 它还在路上，`is_open` 为假，要等 `ACCEPTED`。
- **以为括号单的两张出场单是 OCO。** 工厂默认是 OUO，等量时效果相同，不等量时不同。
- **以为同一张条件单在回测和实盘里行为一样。** 关系由谁执行取决于运行环境和适配器。
- **以为仿真单在持有期间受风控保护。** 它不经过风控、不冻结资金，释放时才检查，失败就被拒。
- **适配器自己做成交去重。** 订单按 `trade_id` 去重和更正价格，适配器要保证 `trade_id` 稳定。
:::

## 本章结论

订单是一个由事件驱动的状态机：9 种类型共用一个 `OrderCore`，15 个状态由 19 种事件按一张转移表推进，表是照着真实交易所会发生的乱序和失败写的（外部订单跳步、撤单后成交、改撤单失败回退、成交撤销）。部分成交、迟到成交、超额成交由数量逻辑处理，重复成交按 `trade_id` 去重。条件单和括号单在模型里只是关系元数据，由回测交易所、`OrderManager`、适配器或交易所来执行；本地仿真单在释放之前不受风控保护。

## 检查理解

1. 一张限价单处于 `PENDING_CANCEL`，这时交易所先推来一笔部分成交，随后又推来 `CancelRejected`。订单最后是什么状态？

   <details><summary>参考答案</summary>

   部分成交到达时，`update_fill_status` 发现数量没满、来源状态是 `PENDING_CANCEL`，于是把 `previous_status` 设成 `PARTIALLY_FILLED`，状态保持 `PENDING_CANCEL`。随后的 `CancelRejected` 在表里保持中间态，由撤单拒绝的处理函数用 `previous_status` 恢复，最终是 `PARTIALLY_FILLED`。

   </details>

2. 适配器重连后把最近 10 笔成交回报全部重发了一遍，其中一笔的价格还被交易所更正过。订单的已成交数量会翻倍吗？

   <details><summary>参考答案</summary>

   不会。`apply` 在状态转移之前按 `trade_id` 查找：同一 `trade_id` 同一价格的重发返回 `DuplicateFill`，订单不变；同一 `trade_id` 不同价格的那一笔当作价格更正，只改写那笔成交的价格，不增加数量。

   </details>

3. 一张带 `emulation_trigger` 的止损单持有了三天，期间账户余额被其他订单用光了。止损触发时会发生什么？

   <details><summary>参考答案</summary>

   持有期间仿真单不经过风控、不冻结资金。触发时仿真器把它改写成市价单并释放，释放后的提交要经过风控；余额不足或交易状态不允许时，订单被 `DENIED`，不会自动重试，并可能触发条件单处理，连带撤掉关联的止盈单。

   </details>

## 参考资料

- 官方文档：[Orders](https://nautilustrader.io/docs/latest/concepts/orders/) · [Events](https://nautilustrader.io/docs/latest/concepts/events/)
- 源码：[`crates/model/src/orders/`](https://github.com/nautechsystems/nautilus_trader/tree/develop/crates/model/src/orders) · [`crates/model/src/events/order/`](https://github.com/nautechsystems/nautilus_trader/tree/develop/crates/model/src/events/order) · [`crates/model/src/enums.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/model/src/enums.rs) · [`crates/common/src/factories/order.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/common/src/factories/order.rs)
- 配图由 `scripts/generate-nautilus-trader-figures.py` 生成。

订单成交之后，持仓就变了。下一章看成交怎样开仓、加仓、平仓和反手，盈亏怎样算。[第 6 章：成交、仓位与盈亏](./positions.md)。
