---
title: "第 22 章：Portfolio：净头寸、盈亏与账户状态"
description: Portfolio 订阅哪些行情和事件、为什么优先级是 10；订单事件为什么走端点和主题两条路；账户状态什么时候本地重算、什么时候发布；未实现盈亏怎样取价、什么时候重算；净头寸、敞口、已实现盈亏、权益与快照；启动时的初始化。
---

# 第 22 章：Portfolio：净头寸、盈亏与账户状态

[全书目录](./index.md) · [上一章](./order-emulator.md) · [下一章](./trader.md)

::: tip 本章学习目标
能说出 Portfolio 订阅了哪些主题和端点，知道它的回调为什么总在策略之前执行；能解释一笔成交之后账户在哪一步被重算、`events.account.{account_id}` 在哪一步发布；能说出未实现盈亏的取价顺序，以及报价到来时 Portfolio 做了什么、没做什么；会用净头寸、敞口、已实现和未实现盈亏、权益这几组查询，知道它们各自返回 `None` 或空表的常见原因。

**源码版本：** `develop` 分支，提交 `364254f`（2026-11-18）。Portfolio 在 `crates/portfolio/src/portfolio.rs`，账户管理器在 `manager.rs`，配置在 `config.rs`，策略侧的查询接口 `PortfolioApi` 在 `crates/trading/src/strategy/api.rs`。

**对应官方文档：** [Portfolio](https://nautilustrader.io/docs/latest/concepts/portfolio/) · [Accounting](https://nautilustrader.io/docs/latest/concepts/accounting/)
:::

第 7 章讲了账户本身：余额的三个数、现金账户和保证金账户的冻结与保证金怎样算。那一章把“谁来调用这些计算”留到了这里。Portfolio 是这个调用者：它订阅行情、订单事件和仓位事件，调用 `AccountsManager` 重算账户，维护净头寸和盈亏，并回答策略的查询。

主线例子接着第 20 章：账户 `BINANCE-001` 是本地计算状态的现金账户（回测里都是这样），策略 `EMACross-001` 以 423.50 买入 1 ETH，然后收到报价 bid 430.00 / ask 430.10，最后以 432.00 卖出平仓。为了让数字简单，假设手续费为零。

## 1. Portfolio 是什么样的对象 {#object}

Portfolio 不是 Actor，没有启动、停止这些生命周期状态。内核在构造时创建它（第 14 章），它在构造函数里就注册好所有消息处理器，之后由内核持有，同时以共享引用交给每个策略和 Actor。策略通过 `self.portfolio()` 拿到一个只读的 `PortfolioApi`。

它的内部状态放在一个 `PortfolioState` 里，主要有这几类：

- **账户管理器 `AccountsManager`：** 第 7 章那些冻结、余额、保证金计算的入口。
- **按品种的盈亏缓存：** `unrealized_pnls`、`realized_pnls`。
- **净头寸 `net_positions`：** 每个品种所有未平仓位的带符号数量之和，跨策略汇总。
- **取价的后备：** 每个品种最近一根外部 K 线的收盘价，以及每个品种、每个方向最近一次有效价格。
- **待计算集合 `pending_calcs`：** 因为缺价格或汇率暂时算不出来的品种。
- **快照：** 每个账户最近的组合快照（第 7 节）。

`AccountsManager` 只做计算，不改缓存。Portfolio 先从缓存取出账户，让账户管理器在这个副本上计算，再写回缓存。

## 2. 它听什么 {#inputs}

| 输入 | 类型 | 何时注册 |
| --- | --- | --- |
| `Portfolio.update_account` | 端点 | 总是 |
| `Portfolio.update_order` | 端点 | 总是 |
| `data.quotes.*` | 主题，优先级 10 | 总是 |
| `data.bars.*EXTERNAL` | 主题，优先级 10 | `bar_updates = true`（默认） |
| `data.mark_prices.*` | 主题，优先级 10 | `use_mark_prices = true`（默认） |
| `events.order.*` | 主题，优先级 10 | 总是 |
| `events.position.*` | 主题，优先级 10 | 总是 |

优先级 10 的意义在第 15 章讲过：同一个主题的订阅者按优先级从高到低调用，策略默认是 0。所以同一条报价、同一个订单事件、同一个仓位事件，Portfolio 总是先处理，策略后处理。策略在 `on_quote`、`on_order_filled`、`on_position_opened` 里查询 Portfolio，看到的都是已经反映了这条消息的状态。

`Portfolio.update_account` 接收执行客户端上报的 `AccountState`（第 7 章第 5 节）：Portfolio 把它应用到缓存里的账户，然后发布到 `events.account.{account_id}`。

## 3. 订单事件为什么走两条路 {#orders}

第 20 章说过，执行引擎把一部分订单事件**发到** `Portfolio.update_order` 端点，然后再**发布**到 `events.order.{strategy_id}` 主题。Portfolio 两边都听，分工是：

- **端点：重算账户。** 只在账户由本地计算（`calculate_account_state = true`）或是 Wallet 账户时才做事，否则直接返回。成交时先调用 `AccountsManager::update_balances` 更新余额（现金账户扣报价货币、加基础货币，第 7 章），并重算该品种的未实现盈亏；然后无论什么事件，都用这个品种在该账户下所有挂着的订单重算冻结额（`update_orders_in_place`）。结果写回缓存，但不发布。
- **主题：发布账户状态。** 对 `Accepted`、`Canceled`、`Expired`、`Rejected`、`Updated` 这几种会改变冻结额的事件，把账户最新的 `AccountState` 发布到 `events.account.{account_id}`。成交事件在这里不做事，账户状态等仓位事件到来时再发布（第 4 节）。

分成两步是为了顺序：执行引擎在更新仓位之前就通过端点把成交交给 Portfolio，保证仓位事件到来时余额已经更新；而账户状态的发布放在主题上，借助优先级排在策略回调之前。仿真器在本地生成的撤单和改单事件（第 21 章）也走同样的两条路。

## 4. 仓位事件：净头寸、盈亏与保证金 {#positions}

每个仓位事件（开仓、变化、平仓）到来时，Portfolio 依次做：

1. 用缓存里这个品种所有未平仓位重算净头寸。
2. 仓位平掉时，把这一轮的已实现盈亏记录下来，供统计使用。
3. 重算这个品种的未实现盈亏和已实现盈亏，写进缓存。算不出来（缺价格或汇率）就把品种放进 `pending_calcs`。
4. 本地计算的保证金账户：按当前持仓重算维持保证金（`recompute_margin_account`），生成新的 `AccountState`。
5. 把账户最新的 `AccountState` 发布到 `events.account.{account_id}`。

主线例子里，买入成交的处理顺序是：执行引擎通过端点把成交交给 Portfolio，余额变为 576.50 USDT 和 1 ETH；执行引擎开仓并发布 `OrderFilled`；接着发布 `PositionOpened`，Portfolio 把净头寸设为 1，再发布账户状态；最后策略的 `on_position_opened` 被调用。

## 5. 未实现盈亏：怎样取价、什么时候算 {#unrealized}

未实现盈亏要一个当前价格。Portfolio 的 `get_price` 按下面的顺序找，找到第一个有效的就用：

1. 标记价格（`use_mark_prices = true` 且缓存里有）。
2. 报价：多头用 bid，空头用 ask。
3. 最新成交价。
4. 最近一根外部 K 线的收盘价（`bar_updates = true` 时才会记录）。

价格必须为正；期货、期权这类允许负价的品种例外。四个来源都没有时，用这个品种、这个方向上次的有效价格，并把它标记为“过期”；从来没有过有效价格的，这个仓位算不出盈亏，品种被记入缺价跟踪（`missing_price_instruments`）。需要换算到账户基础货币时，汇率也是同样的处理：取不到就沿用上次的有效汇率，从来没有就算不出来，不会按 1 换算。

报价到来时 Portfolio 做的事比想象的少：它只是把这个品种缓存的未实现盈亏删掉。真正的计算推迟到查询时：

```rust
fn on_quote(&mut self, quote: &QuoteTick) -> anyhow::Result<()> {
    let id = quote.instrument_id;
    let pnl = self.portfolio().unrealized_pnl(&id);    // Some(6.50 USDT)
    let exposure = self.portfolio().net_exposure(&id, None);  // Some(430.00 USDT)
    let net = self.portfolio().net_position(&id);      // 1
    Ok(())
}
```

主线例子里，多头取 bid 430.00，未实现盈亏是 `(430.00 - 423.50) × 1 = 6.50 USDT`；敞口是按同一价格算的名义金额，多头为正、空头为负，这里是 `430.00 USDT`。只要这个品种还有未平仓位，`unrealized_pnl` 每次查询都按当前价格重算，不会返回旧值。

以 432.00 卖出平仓后，净头寸回到 0，`realized_pnl` 返回 `8.50 USDT`。NETTING 下同一个仓位 ID 多次开平时，已实现盈亏把缓存里的仓位快照（第 6 章）也加进来，所以统计的是这个品种全部轮次的合计，而不只是当前这一轮。

## 6. 策略能查什么 {#queries}

`PortfolioApi` 提供的查询可以分成四组：

| 组 | 方法 | 说明 |
| --- | --- | --- |
| 净头寸 | `net_position`、`is_net_long`、`is_net_short`、`is_net_flat`、`is_completely_net_flat` | 跨策略汇总的带符号数量 |
| 盈亏 | `unrealized_pnl(s)`、`realized_pnl(s)`、`total_pnl(s)` | 单品种或按场所汇总 |
| 敞口与权益 | `net_exposure(s)`、`mark_values`、`equity` | 名义金额与按市值计的权益 |
| 账户层面 | `balances_locked`、`instrument_initial_margins`、`instrument_maintenance_margins` | 来自账户 |

几点需要留意：

- **净头寸是跨策略的。** 两个策略分别持有多 1 和空 1 ETH，`net_position` 是 0。只想看自己的仓位，要从缓存按策略 ID 查。
- **带 `_for_account` 后缀的版本**可以指定账户；不带后缀的版本覆盖这个品种的所有账户。Rust 的 `PortfolioApi` 不提供指定价格和目标货币的参数，需要这些要用 Python 的 Portfolio，它的查询方法接受 `target_currency`。
- **权益 `equity(venue, account_id)`** 是余额合计加上持仓的市值部分。现金账户加持仓市值，但已经计入余额的基础资产不重复计；本地计算的保证金账户加未实现盈亏（期权这类权利金品种加带符号的市值）。各种账户的细节见官方文档 Portfolio 一页的 Equity formula。
- **Rust 的 Portfolio 没有 `account()` 方法。** Rust 策略从缓存读账户，比如 `cache().account_for_venue(&venue)`；Python 的 `portfolio.account(venue)` 返回的是一份脱离的副本，之后的更新不会反映到它上面。

`equity` 比预期小时，先查 `missing_price_instruments(venue)`：缺价的品种不计入合计。

## 7. 初始化、快照与统计 {#lifecycle}

**初始化。** 实盘节点完成启动对账后，依次调用 `initialize_orders`、`initialize_positions`、`initialize_wallet_orders`（第 34 章）：用缓存里已有的挂单和持仓，把每个账户的冻结和保证金算一遍。算不出来的品种进入 `pending_calcs`，等它的下一条报价到来时再算；全部算完之前，`is_initialized()` 返回 `false`。回测从空状态开始，不需要这一步。

**快照。** `equity_curve = true`（默认）时，Portfolio 为每个账户记录并发布组合快照 `PortfolioSnapshot`，发布到 `events.portfolio.{account_id}`：账户第一次注册时一次，之后每个 UTC 零点一次（即使空仓），节点关闭时再一次。快照里有按市值计的权益、未实现盈亏，以及哪些品种用了过期价格、哪些算不出来。更细的快照可以用 `snapshot_interval_ms` 打开，它只在账户有持仓时按间隔发布。`build_snapshot(account_id)` 随时算一份，但不会加入记录。

**统计。** `statistics()` 用全部账户、仓位、仓位快照和组合快照算一组绩效统计，每次调用都重新算，不要放在热路径上。统计的内容和回测报告一起在第 28 章讲。

`PortfolioConfig` 的选项都已在上面出现：

| 选项 | 默认 | 作用 |
| --- | --- | --- |
| `use_mark_prices` | `true` | 取价时优先用标记价格 |
| `use_mark_xrates` | `false` | 汇率优先用标记汇率 |
| `bar_updates` | `true` | 订阅外部 K 线作为取价后备 |
| `convert_to_account_base_currency` | `true` | 换算到账户基础货币 |
| `equity_curve` | `true` | 记录每日权益快照 |
| `snapshot_interval_ms` | 无 | 持仓期间按间隔发布快照 |

![Portfolio 的输入与输出：左侧是两个端点和五个主题，中间是 Portfolio 内部的账户管理器、盈亏缓存、净头寸和快照，右侧是写回缓存的账户、发布的账户状态和组合快照，以及策略的查询](/nautilus-trader/figures/portfolio-flow.svg)

怎么读这张图：左边是输入，实线是端点，虚线是主题订阅，都以优先级 10 排在策略之前。中间的四块是 Portfolio 的内部状态。右边是输出：账户写回缓存，账户状态发布到 `events.account.{account_id}`，组合快照发布到 `events.portfolio.{account_id}`，策略通过 `PortfolioApi` 查询。注意报价这条线只到盈亏缓存，作用是让缓存失效，计算推迟到查询时。

::: warning 常见误区
- **以为每条报价都会让 Portfolio 重算一遍所有盈亏。** 报价只让缓存失效，查询时才算。
- **以为 `net_position` 是本策略的仓位。** 它跨策略汇总。
- **在实盘里以为账户一定是本地算的。** `calculate_account_state = false` 时，Portfolio 不重算账户，余额和保证金以交易所上报为准。
- **`unrealized_pnl` 返回 `None` 就以为没有持仓。** 更常见的原因是还没收到过这个品种的任何价格，或者缺换算汇率。
- **持有 Python `portfolio.account()` 返回的对象，以为它会自动更新。** 它是一份副本，要再次调用才能拿到最新状态。
- **在每个回调里调用 `statistics()`。** 它每次都重新计算全部统计。
:::

## 本章结论

Portfolio 在内核构造时创建，以优先级 10 订阅报价、K 线、标记价格、订单事件和仓位事件，并接收两个端点的消息。执行引擎通过端点把会影响资金的订单事件交给它，本地计算的账户在这里更新余额和冻结；账户状态在订单主题或仓位主题上发布到 `events.account.{account_id}`，排在策略回调之前。仓位事件到来时它更新跨策略的净头寸和盈亏，并重算保证金。未实现盈亏按“标记价、报价、成交价、K 线收盘价”的顺序取价，报价只让缓存失效，计算推迟到查询。权益快照按日记录并发布到 `events.portfolio.{account_id}`。

## 检查理解

1. 一个实盘现金账户的 `calculate_account_state = false`。策略挂出一张限价买单后立即在 `on_order_accepted` 里查询这个账户的冻结额，看到的是什么？

   <details><summary>参考答案</summary>

   看到的是交易所最近一次上报的冻结额。这个账户不由本地计算，Portfolio 收到 `Portfolio.update_order` 时直接返回，不会重算冻结。等交易所推送新的账户状态，经 `Portfolio.update_account` 应用后，冻结额才会变化。

   </details>

2. 回测里策略持有多 1 ETH，但数据里只有成交（TradeTick），没有报价，也没有 K 线。`unrealized_pnl` 会用什么价格？

   <details><summary>参考答案</summary>

   标记价格没有，报价没有，于是用第三项“最新成交价”。如果连成交都还没有到过，这个仓位就算不出盈亏，品种会出现在 `missing_price_instruments` 里。

   </details>

3. 两个策略各自在 NETTING 下交易同一个品种，A 持有多 2 ETH，B 持有空 0.5 ETH。`net_position`、`is_net_long` 分别返回什么？B 怎样知道自己的仓位？

   <details><summary>参考答案</summary>

   `net_position` 返回 1.5，`is_net_long` 返回 `true`，因为它们汇总了所有未平仓位。B 要看自己的仓位，应从缓存按策略 ID 查询未平仓位，或者直接用确定的仓位 ID `{instrument_id}-{strategy_id}` 查。

   </details>

## 参考资料

- 官方文档：[Portfolio](https://nautilustrader.io/docs/latest/concepts/portfolio/) · [Accounting](https://nautilustrader.io/docs/latest/concepts/accounting/)
- 源码：[`crates/portfolio/src/portfolio.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/portfolio/src/portfolio.rs) · [`crates/portfolio/src/manager.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/portfolio/src/manager.rs) · [`crates/portfolio/src/config.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/portfolio/src/config.rs) · [`crates/trading/src/strategy/api.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/trading/src/strategy/api.rs)
- 配图由 `scripts/generate-nautilus-trader-figures.py` 生成。

到这里，内核里的引擎和服务都看过了。最后一章看谁来管理策略、Actor 和执行算法这些组件的生命周期。[第 23 章：Trader](./trader.md)。
