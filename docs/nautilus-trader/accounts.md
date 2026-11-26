---
title: "第 7 章：账户与保证金"
description: NautilusTrader 的四类账户、余额的 total / locked / free 三个数和它们的不变式；现金账户怎样为挂单冻结资金、成交怎样改变余额；保证金账户的杠杆、初始与维持保证金、两种内置保证金模型和两种保证金口径；AccountState 事件与本地计算还是交易所上报。
---

# 第 7 章：账户与保证金

[全书目录](./index.md) · [上一章](./positions.md) · [下一章](./events.md)

::: tip 本章学习目标
能对一个现金账户手算下单、成交、再下单之后各币种的总额、冻结额和可用额；知道保证金账户的冻结额由什么组成，能用两种保证金模型算出同一笔交易的初始和维持保证金；分得清“本地计算的账户状态”和“交易所上报的账户状态”，知道适配器上报保证金时选哪种口径。

**源码版本：** `develop` 分支，提交 `364254f`（2026-11-18）。账户在 `crates/model/src/accounts/`，余额类型在 `crates/model/src/types/balance.rs`，账户事件在 `crates/model/src/events/account/state.rs`，冻结和保证金的计算调度在 `crates/portfolio/src/manager.rs`（`AccountsManager`）。

**对应官方文档：** [Accounting](https://nautilustrader.io/docs/latest/concepts/accounting/) · [Portfolio](https://nautilustrader.io/docs/latest/concepts/portfolio/)
:::

上一章的仓位回答“持有什么、赚了多少”，账户回答另一个问题：“现在还能花多少”。风控在下单前要问这个问题（余额够不够、保证金够不够），组合在报告盈亏时也要问。这一章的主线例子沿用第 11 章实验里的回测交易所设置：币安现货，现金账户，初始余额 1,000,000 USDT 和 10 ETH，手续费 0.1%。

## 1. 四类账户，一个基础结构 {#account-types}

`AccountType` 有四个取值，`AccountAny`（`crates/model/src/accounts/any.rs`）对应四个结构体：

| 类型 | 典型用途 | 冻结什么 |
| :--- | :--- | :--- |
| `Cash` | 现货：币对、股票 | 买单冻结名义金额，卖单冻结要交付的基础资产 |
| `Margin` | 期货、永续等可加杠杆的品种 | 挂单的初始保证金，加上持仓的维持保证金 |
| `Betting` | 体育博彩、预测市场 | 交易所要求的下注额 |
| `Wallet` | 链上钱包 | 待成交订单在本地预留的金额 |

四者都包着一个 `BaseAccount`（`accounts/base.rs`），里面是账户 ID、类型、可选的基础币种、按币种存的余额 `balances`、起始余额、累计手续费，以及全部 `AccountState` 事件的历史。

<strong>单币种还是多币种。</strong>`base_currency` 有值时是单币种账户：所有金额都折算到这个币种记账。为 `None` 时是多币种账户：每个币种各记一份。主线例子是多币种账户，USDT 和 ETH 各有一行余额。

## 2. 余额：三个数和一个不变式 {#balance}

```rust
// 节选自 crates/model/src/types/balance.rs
pub struct AccountBalance {
    pub currency: Currency,
    pub total: Money,    // 总额
    pub locked: Money,   // 为挂单和持仓冻结的部分
    pub free: Money,     // 可用于新订单的部分
}
```

构造函数 `new_checked` 强制三件事：三个金额的币种相同，并且 `locked + free == total` 在 `Money` 的整数表示上严格成立（不是近似相等）。官方文档建议适配器优先用派生的构造函数（给出其中两个，第三个算出来），而不是自己算三个数再传进去，这样不变式和截断规则由一处统一保证。

## 3. 现金账户：一步一步算 {#cash}

### 3.1 下一张买单

策略挂出一张限价买单：`BUY 1 ETH @ 423.50`，交易所接受后订单进入挂单状态。账户管理器 `AccountsManager::update_balance_locked`（`crates/portfolio/src/manager.rs`）会用这个品种所有挂着的订单重新计算冻结额。对一张买单，冻结额是剩余数量的名义金额：

```rust
// 节选自 crates/model/src/accounts/base.rs（base_calculate_balance_locked）
match side {
    OrderSide::Buy => {
        let notional = calculate_notional(instrument, quantity, price, use_quote_for_inverse)?;
        Ok(notional.max(Money::zero(notional.currency)))   // 负价格的买单不冻结
    }
    OrderSide::Sell => match instrument.base_currency() {
        Some(currency) => Ok(money_from_qty(quantity, currency)?),   // 冻结要交付的基础资产
        None => Ok(Money::from_raw_checked(0, instrument.quote_currency())?),
    },
}
```

所以 USDT 这一行变成：总额 1,000,000，冻结 423.50，可用 999,576.50。ETH 不变。

三个细节：冻结用的是订单的剩余数量 `leaves_qty`，部分成交后冻结额随之减少；没有价格的订单（市价单）不冻结，有触发价没有限价的单用触发价；只减仓（`reduce_only`）的订单不冻结。冻结额不含手续费。

### 3.2 成交

这张单以 423.50 全部成交，吃单方手续费 `423.50 × 0.1% = 0.4235 USDT`。对多币种现金账户，一笔买入成交带来两笔变动（`base_calculate_pnls`）：USDT 减少名义金额 423.50，ETH 增加 1；手续费再从 USDT 里扣掉。订单结束后冻结额重算为 0。于是：

- USDT：总额 `1,000,000 - 423.50 - 0.4235 = 999,576.0765`，冻结 0，可用 999,576.0765；
- ETH：总额 11，冻结 0，可用 11。

单币种账户没有基础币那一行，成交只改变折算后的那一个币种。

### 3.3 再下一张卖单

接着挂 `SELL 5 ETH @ 430.00`。卖单冻结的是要交付的 ETH，而不是 USDT：ETH 总额 11，冻结 5，可用 6。官方文档解释了这样设计的原因：卖出交付的是基础资产，把冻结额记在报价币上，等于把“股数”当成“钱”，还会锁住一笔这次卖出根本不会动用的抵押。

![现金账户在初始、挂买单、买单成交、挂卖单四个时刻的余额：买单冻结 USDT 名义金额，成交后 USDT 减少名义金额加手续费、ETH 增加，卖单冻结要交付的 ETH](/nautilus-trader/figures/account-balances.svg)

怎么读这张图：每一列是一个时刻，每一格写着“总额 / 冻结 / 可用”。注意第二列和第四列：冻结的币种跟着方向走，买单冻结报价币，卖单冻结基础币。

股票这类品种的 `base_currency()` 是 `None`，卖单什么也不冻结；库存够不够由交易所检查，拒单走正常的订单事件。回测和沙盒在提交时会额外检查一次卖出数量不超过多头持仓，用来模拟“现金账户不能卖空”。

## 4. 保证金账户 {#margin}

### 4.1 冻结的组成

`MarginAccount`（`accounts/margin.rs`）在 `BaseAccount` 之外多了几样东西：按品种的杠杆 `leverages`、默认杠杆 `default_leverage`（构造时是 1）、两组保证金记录，以及一个保证金模型。它的冻结额由两部分组成：每张挂单的初始保证金，加上每个持仓的维持保证金。

### 4.2 两种保证金模型

两种内置模型（`accounts/margin_model.rs`）都按名义金额的百分比计算，百分比来自品种的 `margin_init` 和 `margin_maint`（第 3 章），区别只在杠杆是否参与：

```rust
// 节选自 crates/model/src/accounts/margin_model.rs（StandardMarginModel）
let notional = instrument.try_calculate_notional_value(quantity, price, Some(use_quote))?;
let margin = notional.as_decimal().abs().checked_mul(instrument.margin_init())?;   // 忽略杠杆
```

`LeveragedMarginModel` 先把名义金额除以杠杆，再乘百分比，杠杆不大于 0 时直接报错。`MarginAccount` 默认用后者；回测可以在交易所配置里换成前者；Python 里还可以传入自己写的模型（`MarginModelAny::Python`）。

用主线例子的数字比较一下。假设在一个保证金账户里交易 ETH 永续，品种的 `margin_init = 1.00`、`margin_maint = 0.35`（和第 3 章那个测试品种的取值一样），杠杆 10 倍，挂单 `BUY 1 @ 423.50`，随后全部成交：

| 模型 | 挂单的初始保证金 | 持仓的维持保证金 |
| :--- | :--- | :--- |
| `LeveragedMarginModel` | 423.50 ÷ 10 × 1.00 = 42.35 USDT | 423.50 ÷ 10 × 0.35 = 14.8225 USDT |
| `StandardMarginModel` | 423.50 × 1.00 = 423.50 USDT | 423.50 × 0.35 = 148.225 USDT |

官方文档的例子更极端：EUR/USD 名义 110,000 美元、杠杆 50 倍、`margin_init` 3%，标准模型要 3,300 美元，杠杆模型只要 66 美元。选错模型，回测里能开的仓位会差几十倍。官方的建议是：传统券商（如盈透）按固定比例收保证金，用标准模型；加密交易所的保证金随杠杆降低，用杠杆模型；按每张合约固定金额收保证金的期货交易所，就把品种的两个比例设成能还原出那个金额的值。

在 HEDGING 模式下，同一个品种可能同时有几个多仓和空仓。账户管理器会先把它们按开仓时间合成一个假想的净仓位，再对净数量和净均价算一次保证金，所以保证金跟着净敞口走，和 NETTING 下的结果一致。

### 4.3 两种口径

`MarginBalance` 有四个字段：初始、维持、币种，以及一个可选的 `instrument_id`，它决定口径：

- <strong>逐品种。</strong>`instrument_id` 有值，适用于逐仓保证金，以及回测和本地计算时按品种算出的保证金。
- <strong>全账户。</strong>`instrument_id` 为 `None`，按抵押币种记一份，适用于全仓保证金的交易所只上报一个总数的情况。

两种口径存在同一个账户的两个独立表里，`MarginAccount.apply()` 按 `instrument_id` 分流。官方文档在这里有一个警告，对写适配器很重要：`apply()` 收到 `AccountState` 时会用事件里的保证金整体替换两个表，而不是合并。适配器如果只上报变化了的那几项，没上报的就会被清掉，直到下一次全量上报。余额则相反：事件里带了的币种被替换，没带的保留。

## 5. AccountState：账户怎样更新 {#account-state}

账户的每一次变化都是一个 `AccountState` 事件：

```rust
// 节选自 crates/model/src/events/account/state.rs
pub struct AccountState {
    pub account_id: AccountId,
    pub account_type: AccountType,
    pub base_currency: Option<Currency>,
    pub balances: Vec<AccountBalance>,
    pub margins: Vec<MarginBalance>,
    pub is_reported: bool,     // 交易所上报（true）还是本地计算（false）
    pub event_id: UUID4,
    pub ts_event: UnixNanos,
    pub ts_init: UnixNanos,
}
```

账户状态有两个来源。一是交易所上报：适配器把交易所推送或查询到的余额和保证金翻译成 `AccountState`，`is_reported = true`。二是本地计算：`AccountsManager` 在订单挂出或撤销时重算冻结，在成交时更新余额，在持仓变化时重算保证金，生成 `is_reported = false` 的事件。回测里只有后者。实盘里是否本地计算由账户的 `calculate_account_state` 决定；关掉时，启动和缺少价格、汇率的重试都会保留交易所上报的余额和保证金，风控检查新订单时用上报的可用余额。

策略读账户的方式是 `portfolio.account(venue)` 或缓存里的账户。保证金账户提供逐品种的查询（某个品种的初始、维持保证金）和全账户的查询，以及合计；组合层面还有按交易所汇总的保证金和盈亏查询。组合怎样把这些拼起来，在第 22 章。

::: tip 对富途意味着什么
富途的证券账户分现金账户和融资融券（保证金）账户。前者对应 `AccountType::Cash` 比较直接；后者对应 `Margin` 时，要先回答两个问题：富途按每只股票不同的融资比例收保证金，这更接近 `StandardMarginModel` 的“固定百分比”还是需要自己写一个模型；富途上报的是账户层面的购买力和保证金总数，应当用全账户口径（`instrument_id = None`），并且每次都全量上报，否则会触发上一节说的“整体替换”问题。港股、美股、A 股通在同一个富途账户下以不同币种结算，多币种账户（`base_currency = None`）更贴近实际。
:::

::: warning 常见误区
- **以为冻结额包含手续费。** 买单只冻结名义金额，手续费在成交时才扣。
- **以为卖单冻结的是报价币。** 现金账户的卖单冻结要交付的基础资产；股票这类没有基础币的品种不冻结。
- **以为市价单会冻结资金。** 没有价格的订单不冻结，只有限价或触发价的订单才冻结。
- **回测和实盘用了不同的保证金模型却没意识到。** 两种模型的结果可以差几十倍，回测要选和交易所一致的那个。
- **适配器只上报变化了的保证金。** `apply()` 会整体替换保证金表，没上报的会被清掉。
- **手工算 `total`、`locked`、`free` 三个数再构造余额。** 优先用派生构造函数，让不变式由一处保证。
:::

## 本章结论

账户由“总额、冻结、可用”三元组按币种记账，`locked + free == total` 严格成立。现金账户为挂单冻结资金：买单冻结剩余数量的名义金额，卖单冻结要交付的基础资产，市价单和只减仓的单不冻结，手续费在成交时扣。保证金账户冻结挂单的初始保证金和持仓的维持保证金，两种内置模型都按名义金额的百分比计算，区别是杠杆是否参与。账户的每次变化是一个 `AccountState` 事件，来自交易所上报或本地计算；适配器上报保证金时要选对口径，并且每次全量上报。

## 检查理解

1. 主线例子的第 3.3 步之后，那张卖单以 430.00 成交了 2 ETH（手续费 0.86 USDT）。USDT 和 ETH 的总额、冻结、可用各是多少？

   <details><summary>参考答案</summary>

   成交让 ETH 减少 2、USDT 增加 `2 × 430 = 860`，再扣手续费 0.86。USDT 总额 `999,576.0765 + 860 - 0.86 = 1,000,435.2165`，冻结 0，可用同总额。ETH 总额 `11 - 2 = 9`；卖单还剩 3 ETH 挂着，按剩余数量冻结 3，可用 6。

   </details>

2. 同一笔 `BUY 1 @ 423.50`，在保证金账户、杠杆 5 倍、`margin_init = 0.10` 的品种上，两种模型的初始保证金各是多少？

   <details><summary>参考答案</summary>

   杠杆模型：`423.50 ÷ 5 × 0.10 = 8.47 USDT`。标准模型忽略杠杆：`423.50 × 0.10 = 42.35 USDT`。

   </details>

3. 一个全仓保证金交易所每次只推送“发生变化的币种”的保证金。适配器直接把推送翻译成 `AccountState` 交给内核，会出现什么问题？怎么改？

   <details><summary>参考答案</summary>

   `MarginAccount.apply()` 用事件里的保证金整体替换保证金表，没出现在这次事件里的币种的保证金会被清掉，账户显示的保证金偏小，风控可能放行本不该放行的订单。适配器应当在本地维护一份完整的保证金快照，每次推送合并之后再全量上报。

   </details>

## 参考资料

- 官方文档：[Accounting](https://nautilustrader.io/docs/latest/concepts/accounting/) · [Portfolio](https://nautilustrader.io/docs/latest/concepts/portfolio/)
- 源码：[`crates/model/src/accounts/`](https://github.com/nautechsystems/nautilus_trader/tree/develop/crates/model/src/accounts) · [`crates/model/src/types/balance.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/model/src/types/balance.rs) · [`crates/model/src/events/account/state.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/model/src/events/account/state.rs) · [`crates/portfolio/src/manager.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/portfolio/src/manager.rs)
- 配图由 `scripts/generate-nautilus-trader-figures.py` 生成。

订单、仓位、账户的每一次变化都是一个事件。下一章把这些事件放在一起：它们有哪些、从哪里发出、怎样串成因果链，以及怎样记录下来用于恢复。[第 8 章：事件与事件溯源](./events.md)。
