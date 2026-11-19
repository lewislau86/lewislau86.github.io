---
title: "第 6 章：成交、仓位与盈亏"
description: 一笔成交怎样变成仓位：Position 结构的关键字段，NETTING 和 HEDGING 两种订单管理模式下仓位 ID 怎样分配，开仓、加仓、减仓、反手各自怎样计算均价和已实现盈亏，手续费怎样计入，反手时成交怎样被拆分，平仓后再开仓时的快照，以及未实现盈亏。
---

# 第 6 章：成交、仓位与盈亏

[全书目录](./index.md) · [上一章](./orders.md) · [下一章](./accounts.md)

::: tip 本章学习目标
能手算一串成交之后的仓位数量、开仓均价、已实现盈亏和手续费；分得清 NETTING 和 HEDGING 两种模式下同一串成交会得到几个仓位、仓位 ID 是什么；知道反手时执行引擎怎样把一笔成交拆成两笔，平仓后在同一个 ID 上再开仓时上一轮的盈亏去了哪里。

**源码版本：** `develop` 分支，提交 `364254f`（2026-11-18）。仓位在 `crates/model/src/position.rs`，成交事件在 `crates/model/src/events/order/filled.rs`，仓位事件在 `crates/model/src/events/position/`，成交到仓位的处理在 `crates/execution/src/engine/mod.rs`。

**对应官方文档：** [Positions](https://nautilustrader.io/docs/latest/concepts/positions/)
:::

上一章结束时，订单变成了 `FILLED`。但策略真正关心的不是订单，而是仓位：我现在持有多少、平均成本是多少、已经赚了多少。这一章把一串成交喂进仓位，一步一步算。第 0 章第 5.7 节有一张“谁在维护仓位”的表，这里补上那张表背后的计算。

主线例子是三笔 ETHUSDT 成交，手续费按成交额的 0.1% 以 USDT 收取：

```text
F1  BUY  1 ETH @ 420.00   手续费 0.42 USDT
F2  BUY  1 ETH @ 430.00   手续费 0.43 USDT
F3  SELL 3 ETH @ 440.00   手续费 1.32 USDT
```

先猜：F3 之后，账面上是一个空 1 ETH 的仓位，还是一个多 2 ETH、一个空 3 ETH 的两个仓位？已实现盈亏是多少？

## 1. 成交事件里和仓位有关的字段 {#order-filled}

一笔成交是一个 `OrderFilled` 事件（`events/order/filled.rs`）。和仓位有关的字段是：`order_side`、`last_qty`（这一笔成交的数量）、`last_px`（成交价）、`commission`（可选的 `Money`）、`liquidity_side`（挂单方还是吃单方）、`trade_id`，以及 `position_id`。最后这个字段由执行引擎在处理成交时填上，它决定了这笔成交进哪个仓位，第 3 节会看到它怎样被决定。

## 2. Position 里记了什么 {#position}

```rust
// 节选自 crates/model/src/position.rs
pub struct Position {
    pub events: Vec<OrderFilled>,        // 本轮的全部成交
    pub id: PositionId,
    pub strategy_id: StrategyId,
    pub instrument_id: InstrumentId,
    pub opening_order_id: ClientOrderId,
    pub closing_order_id: Option<ClientOrderId>,
    pub entry: OrderSide,                // 开仓方向
    pub side: PositionSide,              // LONG / SHORT / FLAT
    pub signed_qty: Decimal,             // 带符号的数量：多为正、空为负
    pub quantity: Quantity,              // signed_qty 的绝对值
    pub peak_qty: Quantity,              // 本轮出现过的最大数量
    pub multiplier: Quantity,
    pub is_inverse: bool,
    pub avg_px_open: Decimal,
    pub avg_px_close: Option<Decimal>,
    pub realized_return: f64,
    pub realized_pnl: Option<Money>,
    pub commissions: IndexMap<Currency, Money>,
    pub cost_open: Decimal,              // 未平部分的开仓成本
    pub cost_close: Decimal,
    pub qty_closed: Decimal,
    // … 时间戳、币种、买卖累计量、调整记录、回放记录等
}
```

计算全部用 `Decimal`，所以不会有浮点误差；`Quantity` 形式的 `quantity` 只是 `signed_qty` 按品种精度转换后的结果。仓位还带着品种的乘数和是否反向，盈亏计算要用到它们。

## 3. NETTING 和 HEDGING：一串成交进几个仓位 {#oms}

订单管理模式（`OmsType`）决定仓位怎样划分，有三个取值：`NETTING`、`HEDGING`，以及 `UNSPECIFIED`（跟随执行客户端的设置）。执行引擎在 `determine_position_id`（`crates/execution/src/engine/mod.rs`）里按模式给成交分配仓位 ID：

```rust
// 节选自 crates/execution/src/engine/mod.rs（determine_netting_position_id）
let position_id = PositionId::new(format!("{}-{}", fill.instrument_id, fill.strategy_id));
```

<strong>NETTING</strong>：同一个策略在同一个品种上只有一个仓位，ID 是固定的“品种-策略”，例如 `ETHUSDT.BINANCE-EMACross-001`。所有成交都进这个仓位。

<strong>HEDGING</strong>：每个仓位有自己的 ID，由第 2 章的 `PositionIdGenerator` 生成（`P-日期-时间-trader 标签-strategy 标签-计数`）。下单时可以用 `submit_order(order, position_id, …)` 指定进哪个仓位；不指定时，新订单的成交开一个新仓位。不同仓位之间不会自动轧差。

回到开头的猜题。在 NETTING 下，三笔成交都进同一个仓位，最后是一个空 1 ETH 的仓位（加上一份已平的上一轮快照，第 5 节）。在 HEDGING 下、三张单都没有指定仓位时，F1、F2、F3 各开一个仓位：两个各多 1 ETH，一个空 3 ETH，净敞口同样是空 1 ETH，但账面上是三个仓位，各算各的盈亏。官方文档还提醒，策略的模式和交易所的模式可以不同：策略 HEDGING、交易所 NETTING 时，NautilusTrader 维护几个“虚拟仓位”，交易所那边只有一个净仓位，保证金按交易所的规则算。

![三笔成交在 NETTING 和 HEDGING 两种模式下的结果：NETTING 下同一个 ID 先平掉多 2 再开空 1，上一轮盈亏存进快照；HEDGING 下三笔成交各自成为一个仓位，净敞口相同但互不轧差](/nautilus-trader/figures/positions-oms.svg)

怎么读这张图：上下两条泳道是同一串成交在两种模式下的去向。NETTING 那条里注意 F3 被拆成了两段，HEDGING 那条里注意没有任何仓位被平掉。

## 4. 主线例子：在 NETTING 下一步一步算 {#walkthrough}

核心逻辑在 `Position::handle_order_fill`：先判断这笔成交是加仓（同方向或从零开始）还是减仓（反方向），再分别处理。

```rust
// 节选自 crates/model/src/position.rs（handle_order_fill）
let increases = self.signed_qty.is_zero()
    || (self.signed_qty > Decimal::ZERO) == (fill.order_side == OrderSide::Buy);
let mut pnl = Decimal::ZERO;
if increases {
    self.cost_open = add_rounded(self.cost_open, mul_rounded(last_px, last_qty)?)?;
    self.avg_px_open = div(self.cost_open, add(prior_qty, last_qty)?)?;   // 加权平均
} else {
    pnl = self.close_fill(last_px, last_qty.min(prior_qty), prior_qty)?;  // 按比例分摊成本
    // … 成交量超过原仓位时，剩余部分以成交价重新开仓
}
let commission = fill.commission
    .filter(|commission| commission.currency == self.settlement_currency)
    // …
pnl = add_pnl(pnl, -commission, self.settlement_currency)?;   // 手续费计入已实现盈亏
self.accumulate_pnl(pnl)?;
```

两个约定要先记住。第一，手续费直接从已实现盈亏里扣，开仓的成交也一样，所以一个刚开的仓位，已实现盈亏就是负的手续费。第二，只有手续费币种等于结算币种时才这样扣；现货币对的手续费如果以基础币收取（例如买 ETH 收 ETH），扣的是仓位数量，用一个 `PositionAdjusted` 事件记录（官方文档 Base-currency commissions 一节）。主线例子的手续费是 USDT，属于第一种。

<strong>F1：买 1 @ 420。</strong>从零开始，算加仓：`cost_open = 420`，`avg_px_open = 420`，`signed_qty = 1`。已实现盈亏 `= -0.42 USDT`。

<strong>F2：买 1 @ 430。</strong>同方向，加仓：`cost_open = 420 + 430 = 850`，`avg_px_open = 850 ÷ 2 = 425`，`signed_qty = 2`。已实现盈亏 `= -0.42 - 0.43 = -0.85 USDT`。

<strong>F3：卖 3 @ 440。</strong>反方向，而且数量超过了现有的 2。执行引擎在把成交交给仓位之前先检查这种情况（`will_flip_position`：方向相反且成交量大于仓位量），然后用 `OrderFilled::split_for_position_flip` 把它拆成两笔：

```text
平仓部分  SELL 2 @ 440   手续费 1.32 × 2/3 = 0.88   原 position_id
开仓部分  SELL 1 @ 440   手续费 1.32 × 1/3 = 0.44   新 event_id，causation_id 指向原成交
```

手续费按数量比例拆分。平仓部分先应用：分摊的成本是全部 `cost_open = 850`，盈亏 `= 440 × 2 - 850 = 30`，减去手续费 0.88 得 29.12，累计已实现盈亏 `= -0.85 + 29.12 = 28.27 USDT`。仓位变成 `FLAT`，`avg_px_close = 440`，`realized_return = (440 - 425) ÷ 425 ≈ 3.53%`。

接下来执行引擎先给这个已平的仓位做一个快照，再用同一个 ID 打开新的一轮：开仓部分从零开始，`side = SHORT`，`avg_px_open = 440`，已实现盈亏重置为 `-0.44 USDT`。所以 F3 之后，缓存里这个 ID 的仓位显示的是新一轮的数字，上一轮的 28.27 USDT 存在快照里，组合（第 22 章）统计品种盈亏时会把快照也算进去。

如果此时最新价是 435，空 1 ETH 的未实现盈亏是 `(440 - 435) × 1 = 5 USDT`，`total_pnl` 是已实现加未实现，即 `-0.44 + 5 = 4.56 USDT`（只算当前这一轮）。

## 5. 平仓之后再开仓：快照 {#snapshots}

NETTING 下仓位 ID 永远是“品种-策略”，这带来一个问题：仓位每次归零再开，都是同一个 ID。`Position::apply_fill` 的处理是，仓位 `FLAT` 时来一笔新成交，就调用 `reset_cycle` 把成交历史、手续费、已实现盈亏、均价、开仓时间全部清空，开始新的一轮。为了不丢掉上一轮，执行引擎在重新打开之前把已平的状态存成快照（`snapshot_position`），快照按仓位 ID 存在缓存里，保存最终的数量、价格、已实现盈亏、全部成交和手续费。

HEDGING 下多数情况不需要这一步：反手时如果原仓位 ID 是 NautilusTrader 自己生成的（“虚拟”的），执行引擎会用生成器给新的一段生成一个新 ID，末尾带 `F`（第 2 章第 6.3 节），原仓位保持已平状态留在缓存里。只有当一个已平仓位的 ID 被后来的成交再次使用时，才同样先归档再替换。

不要把这种“平仓轮次的归档”和执行引擎配置里的 `snapshot_positions` 混在一起：后者是在仓位开、变、平时把状态发布出去（有 Redis 或 PostgreSQL 时还会持久化），用于监控和外部系统，和盈亏统计无关。

## 6. 反向合约、乘数与币种 {#pnl-currency}

上面的公式是正向合约的。乘数不为 1 时，盈亏再乘以乘数（`pnl_from_cost` 末尾）。反向合约的盈亏按“1 ÷ 价格”的差计算，结果以基础币计：多头平仓的盈亏是 `数量 × 乘数 × (1/开仓价 - 1/平仓价)`，空头相反。所以同样是 BTC 永续，USDT 本位合约的盈亏是 USDT，币本位合约的盈亏是 BTC。

盈亏的币种就是结算币：正向品种是报价币，反向品种是基础币，跨币种结算的 quanto 合约是结算币。不同币种的盈亏要先换算才能相加（`Money` 跨币种相加会 panic，第 2 章第 3 节），换算由组合和账户负责（第 7、22 章）。

## 7. 仓位事件 {#position-events}

仓位每变一次，执行引擎发布一个仓位事件：`PositionOpened`（从零开仓）、`PositionChanged`（数量或盈亏变化但没有归零）、`PositionClosed`（归零），以及记录成交以外变化的 `PositionAdjusted`（基础币手续费、资金费）。主线例子里的事件依次是：F1 之后 `PositionOpened`，F2 之后 `PositionChanged`，F3 平仓部分之后 `PositionClosed`，开仓部分之后又一个 `PositionOpened`。它们怎样到达策略的回调见第 10 章，事件字段和发布主题见第 8 章。

::: tip 对富途意味着什么
富途的证券账户在每个股票上只有一个净持仓，交易所侧天然是 NETTING。如果策略用 HEDGING 维护多个虚拟仓位，NautilusTrader 账面上的多个仓位和富途 App 里看到的一个持仓会不一致，对账（第 34 章）也只能对净数量。除非确实需要分仓统计，接富途时策略宜用 NETTING，或者 `UNSPECIFIED` 并让适配器把执行客户端的模式设为 NETTING。港股、美股的手续费是否以结算币种收取、能否在成交回报里拿到，需要对照富途的成交推送字段确认，这决定了已实现盈亏里扣不扣得到手续费。
:::

::: warning 常见误区
- **以为已实现盈亏只在平仓时出现。** 开仓成交的手续费也计入，刚开的仓位已实现盈亏就是负的手续费。
- **以为反手是一笔成交进一个仓位。** 执行引擎会把它拆成平仓和开仓两笔，手续费按数量比例拆分。
- **在 NETTING 下只看当前仓位的 `realized_pnl`。** 平仓再开会重置它，上一轮的盈亏在快照里。
- **以为 HEDGING 会自动轧差。** 不同仓位互不抵消，净敞口要自己汇总；交易所是 NETTING 时它们都是虚拟仓位。
- **以为基础币手续费会扣盈亏。** 现货币对以基础币收的手续费扣的是仓位数量。
- **把 `snapshot_positions` 当成平仓快照。** 前者是状态发布，后者是平仓轮次的归档。
:::

## 本章结论

仓位是成交的累积：同方向加仓按加权平均更新开仓成本，反方向减仓按比例分摊成本算出已实现盈亏，手续费（结算币种时）直接从已实现盈亏里扣。NETTING 下一个策略在一个品种上只有一个固定 ID 的仓位，反手时执行引擎把成交拆成平仓和开仓两笔，并在重新打开前给上一轮做快照；HEDGING 下每个仓位有生成的 ID，彼此不轧差。盈亏以结算币计，反向合约按价格倒数计算。

## 检查理解

1. 在 NETTING 下，F1、F2 之后又来一笔 `SELL 2 @ 415`（手续费 0.83 USDT），仓位和已实现盈亏是多少？

   <details><summary>参考答案</summary>

   卖 2 正好平掉多 2，不拆分。盈亏 `= 415 × 2 - 850 = -20`，减手续费 0.83 得 -20.83，累计已实现盈亏 `= -0.85 - 20.83 = -21.68 USDT`。仓位变成 `FLAT`，`avg_px_close = 415`，`realized_return = (415 - 425) ÷ 425 ≈ -2.35%`。

   </details>

2. HEDGING 下，F1 开出的仓位 ID 是 `P-…-1`。策略下 `SELL 3` 时指定了 `position_id = P-…-1`，会发生什么？

   <details><summary>参考答案</summary>

   这笔卖单进入多 1 的 `P-…-1`，方向相反且数量更大，执行引擎拆分成平仓 1 和开仓 2。`P-…-1` 是生成器生成的虚拟 ID，所以开仓部分用生成器生成一个带 `F` 后缀的新 ID，空 2 ETH；`P-…-1` 以已平状态留在缓存里。F2 开出的多 1 仓位不受影响。

   </details>

3. 一个 BTC 币本位反向永续，乘数 100（每张面值 100 美元），以 50000 开多 10 张、以 55000 全部平仓，已实现盈亏是多少、以什么币计（不计手续费）？

   <details><summary>参考答案</summary>

   `10 × 100 × (1/50000 - 1/55000) = 1000 × (0.00002 - 0.0000181818…) ≈ 0.0018182 BTC`，以基础币 BTC 计。

   </details>

## 参考资料

- 官方文档：[Positions](https://nautilustrader.io/docs/latest/concepts/positions/) · [Execution](https://nautilustrader.io/docs/latest/concepts/execution/)（订单管理模式与仓位 ID）
- 源码：[`crates/model/src/position.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/model/src/position.rs) · [`crates/model/src/events/order/filled.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/model/src/events/order/filled.rs) · [`crates/model/src/events/position/`](https://github.com/nautechsystems/nautilus_trader/tree/develop/crates/model/src/events/position) · [`crates/execution/src/engine/mod.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/execution/src/engine/mod.rs)
- 配图由 `scripts/generate-nautilus-trader-figures.py` 生成。

仓位说的是“持有什么”，账户说的是“还有多少钱可用”。下一章看成交和挂单怎样改变余额、冻结资金和保证金。[第 7 章：账户与保证金](./accounts.md)。
