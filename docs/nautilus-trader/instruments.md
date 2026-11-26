---
title: "第 3 章：品种：从现货到期权、合成品种与连续期货"
description: NautilusTrader 的品种定义了什么：InstrumentAny 的 18 种品种、Instrument trait 的精度与限制字段、make_price 和 make_qty 怎样舍入、为什么它们不保证对齐最小变动价位、价位表（tick scheme）、名义金额与反向合约、品种从哪里来，以及合成品种和连续期货。
---

# 第 3 章：品种：从现货到期权、合成品种与连续期货

[全书目录](./index.md) · [上一章](./value-types.md) · [下一章](./market-data.md)

::: tip 本章学习目标
能说出一个品种定义里哪些字段约束价格和数量、哪些约束风控、哪些只是元数据；知道 `make_price`、`make_qty` 的舍入规则，以及它们和风控检查之间的缝隙；会用价位表得到对齐的报价；理解合成品种和连续期货是怎样在数据引擎里“算”出来的。

**源码版本：** `develop` 分支，提交 `364254f`（2026-11-18）。品种在 `crates/model/src/instruments/`，价位表在同目录的 `tick_scheme.rs`，合成品种的计算在 `crates/data/src/engine/synthetic.rs`，连续期货在 `crates/data/src/engine/futures.rs`，下单前的检查在 `crates/risk/src/engine/mod.rs`。

**对应官方文档：** [Instruments](https://nautilustrader.io/docs/latest/concepts/instruments/) · [Synthetics](https://nautilustrader.io/docs/latest/concepts/synthetics/) · [Continuous Futures](https://nautilustrader.io/docs/latest/concepts/continuous_futures/)
:::

上一章的 `Price` 和 `Quantity` 只知道自己有几位小数，不知道在某个交易所里什么样的价格是合法的。这件事由品种决定：ETHUSDT 在币安现货的价格精确到 0.01、数量精确到 0.00001，最小下单金额 10 USDT；腾讯控股在港交所每手 100 股，价位随股价分段变化。品种定义写错了，后果不是报错，而是悄悄地按错误的精度截断价格、用错误的币种算名义金额，或者让回测接受实盘会拒绝的价格（官方文档在 Symbology 一节专门用红框警告过这一点）。

主线例子还是第 11 章那份数据的品种：测试工具 `TestInstrumentProvider.ethusdt_binance()` 造出来的 `CurrencyPair`。

## 1. 十八种品种，一个 trait {#instrument-any}

`InstrumentAny`（`crates/model/src/instruments/any.rs`）是一个枚举，我数了一下有 18 个变体。按市场结构分组：

| 类别 | 变体 |
| :--- | :--- |
| 现货 | `Equity`、`CurrencyPair`、`Commodity`、`IndexInstrument`、`TokenizedAsset` |
| 期货 | `FuturesContract`、`FuturesSpread`、`CryptoFuture`、`CryptoFuturesSpread` |
| 期权 | `OptionContract`、`OptionSpread`、`CryptoOption`、`CryptoOptionSpread`、`BinaryOption` |
| 永续 | `CryptoPerpetual`、`PerpetualContract` |
| 其他 | `Cfd`、`Betting` |

官方文档的品种表里还有第 19 项 `SyntheticInstrument`，但它不在 `InstrumentAny` 里：合成品种是一个独立的结构体，只能本地计算价格，不能交易（第 6 节）。

所有变体都实现 `Instrument` trait（`instruments/mod.rs`），枚举通过 `enum_dispatch` 把调用转发到具体类型。这个 trait 的方法可以分成四组：

- <strong>身份。</strong>`id()`、`raw_symbol()`（交易所原生代码）、`asset_class()`、`instrument_class()`、`underlying()`、`isin()`、`exchange()`、期权的 `strike_price()` 与 `option_kind()`、有到期日的品种的 `activation_ns()`/`expiration_ns()`。
- <strong>币种。</strong>`base_currency()`（现货和反向合约才有）、`quote_currency()`、`settlement_currency()`，以及 `is_inverse()`、`is_quanto()`。
- <strong>精度与限制。</strong>`price_precision`、`size_precision`、`price_increment`、`size_increment`、`multiplier`、`lot_size`，以及六个可选限制 `min/max_quantity`、`min/max_notional`、`min/max_price`，和保证金参数 `margin_init`、`margin_maint`。
- <strong>工具方法。</strong>`make_price`、`make_qty`、`try_normalize_price`、`calculate_notional_value`、`next_bid_price`、`next_ask_price` 等，第 2～4 节逐个看。

有一样东西你可能在找却找不到：手续费率。v2 的品种不带 maker/taker 费率，官方文档说得很直接：回测和沙盒的佣金由手续费模型计算（第 27 章），实盘的佣金来自交易所的成交回报。

## 2. 主线例子：ETHUSDT 现货 {#ethusdt}

测试工具里的定义（`python/nautilus_trader/testkit/providers.py`）是：

```python
# 节选自 TestInstrumentProvider.ethusdt_binance()
CurrencyPair(
    instrument_id=InstrumentId(Symbol("ETHUSDT"), Venue("BINANCE")),
    raw_symbol=Symbol("ETHUSDT"),
    base_currency=Currency.from_str("ETH"),
    quote_currency=Currency.from_str("USDT"),
    price_precision=2,
    size_precision=5,
    price_increment=Price(1e-02, precision=2),
    size_increment=Quantity(1e-05, precision=5),
    max_quantity=Quantity(9000, precision=5),
    min_quantity=Quantity(1e-05, precision=5),
    min_notional=Money(10.00, Currency.from_str("USDT")),
    max_price=Price(1000000, precision=2),
    min_price=Price(0.01, precision=2),
    margin_init=Decimal("1.00"),
    margin_maint=Decimal("0.35"),
    ts_event=0,
    ts_init=0,
)
```

构造时会跑一遍 `validate_instrument_common`：`size_increment`、`multiplier`、两个保证金率必须为正；`price_increment` 的精度必须等于 `price_precision`，`size_increment` 的精度必须等于 `size_precision`；可选限制如果给了，也必须为正，`max_price`、`min_price` 的精度同样要和 `price_precision` 一致。所以“精度 2 配增量 `0.010`（精度 3）”这种定义在构造时就会失败。

不同品种类型的字段并不完全一样。`Equity` 根本没有 `size_precision` 和 `size_increment` 字段，trait 方法直接返回 0 和 1：股票只能整股下单；它也没有 `multiplier` 字段，固定为 1。

## 3. make_price 和 make_qty：舍入，但不对齐 {#make-price}

策略算出来的价格往往是 `f64`，比如均线加减一个偏移。下单前要把它变成这个品种合法的 `Price`，官方推荐的做法是 `instrument.make_price(value)`。它的实现是：

```rust
// 节选自 crates/model/src/instruments/mod.rs
fn try_make_price(&self, value: f64) -> anyhow::Result<Price> {
    let dec_value = Decimal::from_str(&value.to_string())?;           // 先转成十进制字符串
    self.try_make_price_from_decimal(dec_value)
}
fn try_make_price_from_decimal(&self, value: Decimal) -> anyhow::Result<Price> {
    let precision = u32::from(self.min_price_increment_precision());  // 价格增量的小数位数
    let rounded_decimal =
        value.round_dp_with_strategy(precision, RoundingStrategy::MidpointNearestEven);
    Price::from_decimal_dp(rounded_decimal, self.price_precision()).map_err(Into::into)
}
```

两个细节决定了结果。第一，它先把 `f64` 按最短的十进制字符串转成 `Decimal`，避开了上一章 `Price::new` 的二进制误差。第二，它用“四舍六入五成双”（银行家舍入），恰好在中点时取偶数。

先猜：对 ETHUSDT 调用 `make_price(423.765)` 和 `make_price(423.775)`，分别得到什么？`423.765` 的 `f64` 转成字符串还是 `"423.765"`，在两位小数上正好是中点，向偶数取 `423.76`；`423.775` 则取 `423.78`。再对照上一章：`Price::new(1.015, 2)` 因为 `1.015 × 100 = 101.49999999999999` 得到 `1.01`，而 `make_price(1.015)` 得到 `1.02`。同一个数，两条路的结果不同。

`make_qty(value, round_down)` 结构相同，多一个参数：`round_down = true` 时向零截断，否则也是银行家舍入。它还多一个检查：一个正数舍入后变成 0 时直接报错（“value rounded to zero for quantity”），比如对 ETHUSDT 调用 `make_qty(0.000004)`。

接下来是官方文档也特意强调的一点：这两个方法只按增量的小数位数舍入，不保证结果是增量的整数倍。如果一个期权的价格增量是 `0.05`，`make_price(1.03)` 得到的是 `1.03`，而不是 `1.05` 或 `1.00`。

那么下单时谁来检查？`RiskEngine` 的 `check_price`、`check_quantity`（`crates/risk/src/engine/mod.rs`）只检查三件事：精度不超过品种精度、数量在 `min/max_quantity` 之间、价格在 `min/max_price` 之间；名义金额的上下限在账户风控里检查。它既不检查增量的整数倍，也不检查 `lot_size`。所以要得到严格对齐的价格，有两个办法：用第 4 节的 `next_bid_price`/`next_ask_price`，或者用 `try_normalize_price`，它对没有对齐的价格直接报错（“`price` is not aligned to price increment”），适合在适配器的边界上做最后检查。

![从策略算出的浮点数到交易所能接受的价格：make_price 只按小数位舍入，RiskEngine 只查精度和上下限，next_bid_price 和 try_normalize_price 才保证对齐最小变动价位](/nautilus-trader/figures/instrument-price-path.svg)

怎么读这张图：从左到右是一个价格从策略走到交易所的路，每一站下面写着它检查什么、不检查什么。红色框是缝隙：一个只做过 `make_price` 的价格可以通过风控，却被交易所以“价格不是最小变动价位的整数倍”拒绝。

## 4. 价位表、名义金额与反向合约 {#tick-scheme}

### 4.1 价位表

`next_bid_price(value, n)` 返回不高于 `value` 的第 `n` 个合法买价，`next_ask_price` 返回不低于 `value` 的第 `n` 个合法卖价。品种没有价位表时，它用增量对齐：卖价是 `ceil(value / increment) × increment`，买价向下取整，再加减 `n` 个增量；有价位表时交给价位表计算。结果超出 `min/max_price` 时返回 `None`。

价位表（tick scheme）是一个按名字登记的全局规则（`tick_scheme.rs`），有两种：

- `FixedTickScheme`：固定增量。内置的有 `FIXED`（增量 1）和一组 `FIXED_PRECISION_N`，从 0 到当前模式的最大精度每个精度一个（`FIXED_PRECISION_2` 的增量就是 0.01）。
- `TieredTickScheme`：按价格分段使用不同增量，每段写成 `(起点, 终点, 增量)`，起点含、终点不含。内置的有 `BETFAIR`（10 段，从 1.01～2.0 的 0.01 到 100～1010 的 10）和 `TOPIX100`（11 段，从 1000 日元以下的 0.1 到 3000 万日元以上的 10000）。

自己的价位表用 `register_tick_scheme` 登记，名字不区分大小写，登记后整个进程内不能替换或删除。品种通过 `tick_scheme` 字段引用名字；从数据目录加载品种时会按名字校验，所以官方文档提醒：自定义价位表要在加载品种之前登记。

::: tip 对富途意味着什么
港股按股价分段使用不同的最小价位（港交所称为“价位表”），正好对应 `TieredTickScheme`；仓库里没有内置的港股价位表，富途适配器需要按港交所公布的分段自己登记一个，并在构造港股 `Equity` 时引用它。另一件事是每手股数：港股 `Equity` 可以把它写进 `lot_size`，但上一节说过，风控不检查 `lot_size`，整手的约束要由适配器在下单边界检查（或者由交易所拒单），碎股单在富途侧是单独的订单类型，这些都是第 38 章要设计的地方。
:::

### 4.2 名义金额

`calculate_notional_value(quantity, price)` 算一笔交易的名义金额，结果是 `Money`。正向品种是 `数量 × 乘数 × 价格`，币种是报价币（跨币种结算的 quanto 合约用结算币）。上一章主线例子的成交就是 `2.679 × 1 × 423.76 = 1135.25304 USDT`。

反向合约（`is_inverse() == true`，例如以美元报价、以币结算的永续）是 `数量 × 乘数 ÷ 价格`，币种是基础币：100 张面值 1 美元的合约在价格 50000 时，名义金额是 `100 × 1 ÷ 50000 = 0.002` 个币。这就是为什么反向品种必须有 `base_currency`，否则这里会报错。期权一类按权利金计价的品种不做这个除法（`InstrumentClass::divides_notional_by_price`）。

名义金额会用在三个地方：风控检查 `min/max_notional` 和单笔名义上限、账户计算冻结资金和保证金（第 7 章）、仓位计算盈亏（第 6 章）。

## 5. 品种从哪里来 {#loading}

品种由适配器的 `InstrumentProvider`（`crates/common/src/providers.rs`）加载：`load_all` 加载全部、`load_ids` 加载指定的几个、`load` 加载一个，加载结果先放进提供器自己的 `InstrumentStore`，再交给数据引擎写进缓存，并以 `on_instrument` 回调通知订阅者。回测里则是 `engine.add_instrument(...)` 直接写进缓存。

下游几乎所有操作都假设品种已经在缓存里：订阅行情（第 11 章说过，建 K 线聚合器要先取品种的精度）、下单（风控要取品种做检查）、算盈亏。实盘里品种加载慢于策略启动，是“订阅了却收不到数据”或“下单被拒”的常见原因之一。

品种也会变：交易所调整最小价位或数量精度时，提供器会推送一个新版本的品种。官方文档提醒，精度变化前后的行情数据不能合并到同一个 Parquet 文件里，因为文件元数据只记一个精度。

## 6. 合成品种：本地算出来的价格 {#synthetic}

合成品种（`crates/model/src/instruments/synthetic.rs`）由几个成分品种和一个公式定义，场所固定是 `SYNTH`：

```rust
// 节选自 crates/model/src/instruments/synthetic.rs
pub struct SyntheticInstrument {
    pub id: InstrumentId,              // {symbol}.SYNTH
    pub price_precision: u8,
    pub price_increment: Price,
    pub components: Vec<InstrumentId>,
    pub formula: String,               // 例如 "BTCUSDT.BINANCE - ETHUSDT.BINANCE"
    // … ts_event、ts_init
    component_names: Vec<String>,
    compiled_formula: CompiledExpression,   // 构造时编译一次
}
```

公式由内置的表达式引擎（`crates/model/src/expressions/`）编译，支持四则运算、乘方、比较、逻辑运算、局部变量和注释，成分品种直接用 `InstrumentId` 原文引用。合成品种不能下单，用途有三个：让策略订阅它的报价或成交、作为本地仿真单的触发价格（第 21 章）、用它的报价合成 K 线。

计算发生在数据引擎里（`crates/data/src/engine/synthetic.rs`）。以报价为例：任何一个成分品种来了新报价，引擎就用这条报价加上其他成分在缓存里的最新报价，分别把买价、卖价代入公式算一遍，生成一条合成品种的 `QuoteTick` 并发布：

```rust
// 节选自 crates/data/src/engine/synthetic.rs（synthetic_quote_from_update）
for instrument_id in &synthetic.components {
    let (bid_price, ask_price) = if *instrument_id == update.instrument_id {
        (update.bid_price, update.ask_price)
    } else {
        let Some(component_quote) = cache.quote(instrument_id) else {
            log::warn!("Cannot calculate synthetic instrument {} price, no quotes for {} yet", …);
            return None;                       // 有一个成分还没有报价，就不出价
        };
        (component_quote.bid_price, component_quote.ask_price)
    };
    bid_inputs.push(bid_price.as_f64());
    ask_inputs.push(ask_price.as_f64());
}
// … 用 bid_inputs、ask_inputs 各算一次公式；数量固定为 1
```

三点值得记住：所有成分都至少有过一次报价之前，合成品种什么也不发布；公式按 `f64` 计算，结果再转成 `Price`；合成报价的买卖数量固定是 1，没有意义。成交同理，只用成分的成交价。

## 7. 连续期货：用换月表拼出一条 K 线 {#continuous-futures}

期货合约会到期，研究时常要一条“连续”的价格序列。NautilusTrader 不把连续期货建模成一个品种，而是建模成“一个目标 K 线类型加一张显式的换月表”，在请求或订阅 K 线时通过 `params` 传进去（`docs/concepts/continuous_futures.md`）：

```python
# 节选自官方文档
params = {
    "continuous_future_transitions": [
        {
            "transition_time_ns": 1773671460000000000,  # ESH26 换到 ESM26 的时刻
            "pre_instrument_id": "ESH26.XCME",
            "post_instrument_id": "ESM26.XCME",
            "pre_price": "6001.00",    # 换月前旧合约的最后价格
            "post_price": "5995.50",   # 换月后新合约的第一个价格
        },
    ],
    "continuous_future_adjustment_mode": "BACKWARD_SPREAD",
}
```

数据引擎按换月时刻把时间切成几段，每一段选用当时的真实合约作为数据源，算出这一段的累计调整量，然后把调整后的数据送进第 11 章讲过的 K 线聚合流程（`BarBuilder` 有专门的调整字段，就是为此准备的）。调整方式有四种：向后或向前，加法（价差）或乘法（比例）。以 `BACKWARD_SPREAD` 为例，最后一个合约不调整，更早的每一段都加上它之后所有换月点的 `post - pre`。乘法调整要求价格严格为正。

换月表由你提供，引擎不会自己判断何时换月；这让结果完全可复现，也意味着换月规则（按成交量、按持仓量还是按固定日期）是策略层面的决定。

::: warning 常见误区
- **以为 `make_price` 会对齐最小变动价位。** 它只按小数位数舍入，`0.05` 增量的品种上 `make_price(1.03)` 还是 `1.03`；要对齐用 `next_bid_price`/`next_ask_price`，或在边界上用 `try_normalize_price` 检查。
- **以为风控会拦住没对齐的价格或不足一手的数量。** `RiskEngine` 只查精度和上下限，不查增量的整数倍和 `lot_size`。
- **在品种里找手续费率。** v2 的品种不带费率，回测用手续费模型，实盘以成交回报为准。
- **以为 `make_price` 和 `Price::new` 的结果一样。** 前者经十进制、银行家舍入，后者经二进制浮点、四舍五入，中点附近会不同。
- **加载品种之后才登记自定义价位表。** 加载时会按名字校验，先登记再加载。
- **以为合成品种能下单，或者一订阅就有价格。** 它只能本地计算，每个成分都有过报价之后才开始出价。
:::

## 本章结论

品种是“价格和数量在某个市场里怎样才合法”的定义。18 种品种共用一个 `Instrument` trait：精度和增量约束价格与数量，六个可选上下限约束风控，保证金率参与账户计算，费率则不在品种里。`make_price`、`make_qty` 经十进制做银行家舍入，但只舍到小数位，不对齐增量；风控也不查对齐和整手，严格对齐要靠价位表和 `next_bid_price`、`try_normalize_price`。合成品种和连续期货都不是交易所的品种，而是数据引擎按公式或换月表在本地算出来的价格序列。

## 检查理解

1. ETHUSDT 的定义里 `min_notional = 10 USDT`。策略在价格 423.76 时下了一个 0.02 ETH 的限价买单，会被哪里拒绝？

   <details><summary>参考答案</summary>

   名义金额是 `0.02 × 423.76 = 8.4752 USDT`，低于 10 USDT。数量本身满足精度和 `min_quantity`（0.00001），`check_quantity` 能通过；名义金额下限在风控的账户检查里比较，订单会在那里被拒绝（`OrderDenied`）。

   </details>

2. 一个期权的 `price_increment` 是 `0.05`、精度 2。策略对 `1.03` 分别调用 `make_price`、`next_bid_price(1.03, 0)`、`next_ask_price(1.03, 0)`，各得到什么？

   <details><summary>参考答案</summary>

   `make_price(1.03)` 只按两位小数舍入，得到 `1.03`，没有对齐 `0.05`。`next_bid_price(1.03, 0)` 向下对齐到 `1.00`，`next_ask_price(1.03, 0)` 向上对齐到 `1.05`（没有价位表时用增量对齐）。

   </details>

3. 合成品种 `BTC-ETH:BINANCE.SYNTH` 的公式是 `BTCUSDT.BINANCE - ETHUSDT.BINANCE`。启动后先收到了 100 条 ETHUSDT 报价，还没有任何 BTCUSDT 报价，合成品种发布了几条报价？

   <details><summary>参考答案</summary>

   一条也没有。每次 ETHUSDT 报价到达时，引擎要去缓存里取 BTCUSDT 的最新报价，取不到就记一条警告并返回 `None`。直到 BTCUSDT 有了第一条报价，之后任一成分的新报价才会触发计算。

   </details>

## 参考资料

- 官方文档：[Instruments](https://nautilustrader.io/docs/latest/concepts/instruments/) · [Synthetics](https://nautilustrader.io/docs/latest/concepts/synthetics/) · [Continuous Futures](https://nautilustrader.io/docs/latest/concepts/continuous_futures/)
- 源码：[`crates/model/src/instruments/`](https://github.com/nautechsystems/nautilus_trader/tree/develop/crates/model/src/instruments) · [`tick_scheme.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/model/src/instruments/tick_scheme.rs) · [`crates/model/src/expressions/`](https://github.com/nautechsystems/nautilus_trader/tree/develop/crates/model/src/expressions) · [`crates/data/src/engine/synthetic.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/data/src/engine/synthetic.rs) · [`crates/data/src/engine/futures.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/data/src/engine/futures.rs) · [`crates/risk/src/engine/mod.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/risk/src/engine/mod.rs)
- 配图由 `scripts/generate-nautilus-trader-figures.py` 生成。

品种说明了“什么价格合法”，下一章看市场实际发来了什么：报价、成交、订单簿增量，以及订单簿怎样在本地维护。[第 4 章：行情数据与订单簿](./market-data.md)。
