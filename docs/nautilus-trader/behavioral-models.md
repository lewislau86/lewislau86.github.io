---
title: "第 27 章：行为模型：成交、手续费、延迟与保证金"
description: 四类行为模型各回答什么问题、在撮合流程的哪一步被调用；成交模型的两个概率参数和合成订单簿；手续费模型怎样按名义金额和挂单、吃单方向计算佣金；延迟模型怎样决定命令的到达时间和释放时机；保证金模型的选择；模拟模块（外汇隔夜利息、差价合约掉期）的生命周期；Trait、Any 枚举与 Handle 三种形态。
---

# 第 27 章：行为模型：成交、手续费、延迟与保证金

[全书目录](./index.md) · [上一章](./simulated-exchange.md) · [下一章](./reports-and-statistics.md)

::: tip 本章学习目标
能说出四类行为模型分别回答什么问题、在一笔模拟成交的哪一步起作用；会配置成交模型的 `prob_fill_on_limit` 和 `prob_slippage`，知道它们在 L1 和 L2 订单簿上的区别；能手算一笔成交的挂单或吃单佣金；能解释加了延迟模型后，一张单什么时候到达交易所、什么时候真正被处理；知道模拟模块和行为模型的区别；会在 Rust 里实现一个自定义模型并传进场所配置。

**源码版本：** `develop` 分支，提交 `364254f`（2026-11-18）。成交、手续费、延迟模型在 `crates/execution/src/models/`（`fill.rs`、`fee.rs`、`latency.rs`），佣金计算在 `crates/model/src/fees.rs`，保证金模型在 `crates/model/src/accounts/margin_model.rs`，模拟模块在 `crates/backtest/src/modules/`，撮合引擎里的调用点在 `crates/execution/src/matching_engine/mod.rs`。

**对应官方文档：** [Behavioral Models](https://nautilustrader.io/docs/latest/concepts/behavioral_models/) · [Fill Models](https://nautilustrader.io/docs/latest/concepts/backtesting/fill-models/) · [Simulation Modules](https://nautilustrader.io/docs/latest/concepts/backtesting/simulation-modules/)
:::

第 26 章的撮合规则是确定的：同样的数据、同样的订单，结果总是一样。但历史数据回答不了一些问题：你的挂单排在队列第几位？下单后过多久交易所才收到？交易所收多少手续费？行为模型把这些假设变成可以替换的插件，不用改引擎，也不用改策略。

主线例子接着第 26 章：场所 `SIM`、L1 订单簿、`AUD/USD.SIM`。我们给场所配上四个模型：成交模型 `DefaultFillModel(prob_fill_on_limit = 0.5, prob_slippage = 0.2, 随机种子 42)`，手续费模型 `MakerTakerFeeModel(挂单 0.00002, 吃单 0.00002)`，延迟模型 `StaticLatencyModel`（基础 1 毫秒），保证金模型用默认值。

## 1. 四类模型 {#families}

| 类别 | 回答的问题 | 内置实现 |
| --- | --- | --- |
| 成交 | 挂单被碰到时成不成交、成交价是否滑一个价位、对面有多少流动性 | `DefaultFillModel` 等 11 种 |
| 手续费 | 这笔成交收多少佣金 | `MakerTakerFeeModel`、`FixedFeeModel`、`PerContractFeeModel` 等 |
| 延迟 | 命令过多久到达交易所 | `StaticLatencyModel` |
| 保证金 | 挂单和持仓各要占用多少保证金 | `LeveragedMarginModel`、`StandardMarginModel` |

成交和延迟模型只影响模拟执行（回测和沙盒），不决定实盘交易所怎样成交。手续费模型同样只用于回测和沙盒：实盘的佣金来自交易所的成交回报（第 3 章）。保证金模型用于本地计算的保证金账户，回测和实盘都可能用到（第 7 章）。

四类模型都在场所上配置，参数顺序是 `fill_model`、`fee_model`、`margin_model`、`latency_model`。手续费模型是必填的：官方的说法是，零费率也要显式写一个零费率模型，避免无意中得到“没有摩擦”的回测。

## 2. 成交模型 {#fill}

成交模型的接口很小：

```rust
pub trait FillModel {
    fn is_limit_filled(&mut self) -> anyhow::Result<bool>;   // 挂单被碰到时是否成交
    fn is_slipped(&mut self) -> anyhow::Result<bool>;        // 这笔成交是否滑一个价位
    fn fill_limit_inside_spread(&self) -> anyhow::Result<bool> { Ok(false) }  // 有默认实现
    fn get_orderbook_for_fill_simulation(&mut self, instrument: &InstrumentAny, order: &OrderAny,
        best_bid: Option<Price>, best_ask: Option<Price>)
        -> anyhow::Result<Option<OrderBook>>;                // 合成订单簿，返回 None 表示用历史订单簿
}
```

默认的 `DefaultFillModel` 有两个概率参数：

- **`prob_fill_on_limit`**（默认 1.0）：挂单方的限价单在行情**恰好碰到**限价时，按这个概率决定是否成交，用来近似“排在队列后面、轮不到”的情况。行情**越过**限价时不抽签，一定成交。
- **`prob_slippage`**（默认 0.0）：只用于 L1 订单簿。每一笔成交按这个概率向不利方向滑一个价位，挂单和吃单都算；但不会滑过订单的限价、价格保护边界或品种的价格范围，所以按限价成交的挂单永远不会滑。

L2、L3 订单簿上，滑点由订单簿本身的深度决定，`prob_slippage` 不起作用，`prob_fill_on_limit` 仍然起作用。

::: tip “恰好碰到”在源码里的含义
撮合引擎只在两种情况下调用 `is_limit_filled`：成交数据的成交价等于限价，或者报价里**同侧**的最优价等于限价（买单看买价，卖单看卖价）。源码测试里的注释也是这样写的。对一张买入限价单来说，报价的卖价跌到恰好等于限价，已经满足撮合条件（卖价 ≤ 限价），但同侧的买价不等于限价，所以不抽签、直接成交。结果是：只用报价数据时，这个参数几乎不起作用；它主要影响由成交数据触发的挂单成交。官方文档只说“碰到但没有越过”，没有写出这个区别。
:::

两个参数都依赖随机数。给模型一个 `random_seed`，同样的数据跑两次结果才一样。没给种子时，每次运行的抽签都不同。

主线例子里，第 26 章那张挂着的买入限价 0.65010：如果有一笔成交恰好打在 0.65010，就有一半的概率不成交；如果报价的卖价跌到 0.65010 或更低，按上面的说明不抽签，直接按限价 0.65010 成交。市价买单的两笔成交（10 万 @ 0.65008、5 万 @ 0.65009）各自有 20% 的概率再滑一个价位。注意第二笔的“差一个价位”是第 26 章的确定性规则，模型的随机滑点是额外的。

其余 10 种内置成交模型通过 `get_orderbook_for_fill_simulation` 提供一个**合成订单簿**，代替历史订单簿来决定成交：`BestPriceFillModel` 在最优价提供无限数量，`OneTickSlippageFillModel` 在差一个价位处提供无限数量，`TwoTierFillModel` 在最优价放 10 个单位、其余差一个价位，`ThreeTierFillModel` 在三档分别放 50、30、20 个单位，等等。这些档位的数量是模型里的常数，单位是品种的数量单位；对一个每手 10 万的外汇品种，“10 个单位”几乎等于没有，使用前要确认它们适合你的品种。合成订单簿不参与第 26 章的流动性消耗计数。

## 3. 手续费模型 {#fee}

手续费模型的接口只有一个必需的方法：

```rust
pub trait FeeModel {
    fn get_commission(&self, order: &OrderAny, fill_quantity: Quantity,
                      fill_px: Price, instrument: &InstrumentAny) -> anyhow::Result<Money>;
}
```

撮合引擎每生成一笔成交就调用一次，结果写进 `OrderFilled` 的 `commission`。

**`MakerTakerFeeModel`** 按订单这笔成交的流动性方向（挂单还是吃单）选费率，再乘以名义金额：

```text
佣金 = |名义金额| × 费率，按币种精度用银行家舍入
```

名义金额按品种计算（第 3 章），币种是名义金额的币种，对 `AUD/USD` 来说是美元。主线例子的第一笔成交 10 万 @ 0.65008 是吃单：`65,008 × 0.00002 = 1.30016`，舍入到美分是 1.30 美元。费率可以按品种覆盖默认值；挂单费率可以是负数，表示返佣。

**`FixedFeeModel`** 每笔收固定金额；默认 `charge_commission_once = true`，只在订单的第一笔成交收，后面的部分成交不再收。**`PerContractFeeModel`** 按合约数量乘以每张的固定金额。另外还有三种给期权和概率定价品种用的模型：`ProbabilityPriceFeeModel`、`CappedOptionFeeModel`、`TieredNotionalOptionFeeModel`。需要标的价格的模型实现 `get_commission_with_context`，引擎对期权品种会传入标的价格。

## 4. 延迟模型 {#latency}

没有延迟模型时，策略在时间戳 `T` 发出的命令在 `T` 就被交易所处理（第 24 章第 4 节）。有了延迟模型，命令进入交易所的在途队列，带一个到达时间：

```text
到达时间 = 命令的 ts_init + 延迟
```

延迟由三个方法给出，分别对应提交、改单、撤单：

| 方法 | 命令 |
| --- | --- |
| `get_insert_latency` | `SubmitOrder`、`SubmitOrderList` |
| `get_update_latency` | `ModifyOrder`、`BatchModifyOrders` |
| `get_delete_latency` | `CancelOrder`、`BatchCancelOrders`、`CancelAllOrders` |

`StaticLatencyModel` 有四个参数：基础延迟，以及提交、改单、撤单各自的附加延迟；三种命令的延迟分别是“基础 + 附加”。

到达时间到了，命令也不是立刻处理，而是等到一个“结算点”。官方文档列出了规则：

| 结算点 | 释放哪些到期命令 |
| --- | --- |
| 行情数据 | 同一时刻的命令，以及**这个品种**更早到期的命令 |
| 只有组合快照计时器 | 同一时刻的命令 |
| 其他计时器 | 所有到期的命令 |
| 资金费率结算 | 所有到期的命令 |
| 回测结束 | 时钟推进到最后一条在途命令的到达时间，全部处理 |

这样设计的原因是：另一个品种的行情到来时，不应该让这个品种的命令以过时的订单簿状态成交。

主线例子里，策略在 10:00:00.000 收到报价后提交市价单，延迟 1 毫秒，到达时间 10:00:00.001。如果下一条 `AUD/USD` 报价在 10:00:00.250 到来，这张单就在那条报价**更新订单簿之后**、以那一刻的卖价成交，而不是以 10:00:00.000 的卖价成交。只用 K 线回测时，这意味着在 `on_bar` 里下的单要等到下一根 K 线的四个价格点都走完，按它的收盘状态成交。

延迟模型只在命令进入队列时被调用。`BacktestVenueConfig` 建的场所总是排队；`BacktestEngine` 直接加场所时，如果设置了 `use_message_queue = false`，命令立即处理，延迟模型不会被调用。

## 5. 保证金模型 {#margin}

保证金模型决定保证金账户上挂单的初始保证金和持仓的维持保证金，第 7 章第 4 节已经用数字比较过两种内置模型：

- `LeveragedMarginModel`（保证金账户的默认）：`|名义金额| ÷ 杠杆 × 品种的 margin_init（或 margin_maint）`。
- `StandardMarginModel`：`|名义金额| × margin_init`，不考虑杠杆。

传统券商通常按固定比例收保证金，用标准模型；加密交易所的保证金随杠杆降低，用杠杆模型。

## 6. 模拟模块 {#modules}

有些行为不是“这笔成交怎样”，而是“每天收盘后账户要发生什么”，比如外汇隔夜利息、差价合约的掉期费。这类行为做成**模拟模块**（`SimulationModule`），挂在场所上：

1. `pre_process`：交易所处理每条行情之前调用，模块可以记录价格；
2. `process`：每个时间戳结清命令之后调用一次（第 24 章第 4 节的“一个时间戳的收尾”），模块读取交易所的只读快照，返回一批资金调整；
3. 交易所按顺序把调整应用到账户，然后调用模块的 `acknowledge`，告诉它每笔调整的结果。

任何一步出错，交易所进入错误状态，直到模块重置成功，以免已经入账的调整被重复应用。内置的两个模块是外汇隔夜利息 `FXRolloverInterestModule` 和差价合约掉期 `CfdSwapModule`。永续合约的资金费率不是模块，而是交易所自己处理的（第 24 章的资金费率结算）。

## 7. 三种形态：Trait、Any 与 Handle {#forms}

每一类模型在源码里都有三种形态：

| 形态 | 例子 | 能装什么 | 分派方式 |
| --- | --- | --- | --- |
| Trait | `FillModel` | 定义接口 | — |
| Any 枚举 | `FillModelAny` | 内置实现和 Python 桥接 | `match` |
| Handle | `FillModelHandle` | 任何实现了 trait 的 Rust 类型 | trait 对象 |

`BacktestVenueConfig` 这类可以序列化的配置存 `Any` 枚举；`SimulatedVenueConfig` 和运行时的交易所存 `Handle`。所以在 Rust 里写一个自定义模型，只要实现 trait，再包成 `Handle` 交给 `SimulatedVenueConfig`：

```rust
/// 碰到限价时隔一次成交一次，从不滑点，不提供合成订单簿（演示用，结果确定）
struct EveryOtherTouch { touches: u64 }

impl FillModel for EveryOtherTouch {
    fn is_limit_filled(&mut self) -> anyhow::Result<bool> {
        self.touches += 1;
        Ok(self.touches % 2 == 0)
    }
    fn is_slipped(&mut self) -> anyhow::Result<bool> { Ok(false) }
    fn get_orderbook_for_fill_simulation(&mut self, _: &InstrumentAny, _: &OrderAny,
        _: Option<Price>, _: Option<Price>) -> anyhow::Result<Option<OrderBook>> {
        Ok(None)
    }
}

engine.change_fill_model(Venue::from("SIM"), FillModelHandle::new(EveryOtherTouch { touches: 0 }));
```

Python 里可以继承 `FillModel`、`FeeModel`、`LatencyModel`、`MarginModel`，或者传一个有同名方法的对象。要注意一点：自定义模型对象在多次运行和 `reset()` 之间是共享的，它的随机数生成器和内部状态会延续下去；需要每次运行独立时，自己重置状态，或者每次新建模型。原生插件（运行时加载动态库）不在开源版本里，Rust 模型只能在编译时链接进来。

![一笔模拟成交经过的行为模型：命令先由延迟模型给出到达时间，在结算点进入撮合引擎；撮合时成交模型决定挂单是否成交、是否滑点，或提供合成订单簿；生成成交时手续费模型算佣金；成交后保证金模型重算保证金；每个时间戳末尾运行模拟模块，把资金调整记入账户](/nautilus-trader/figures/behavioral-models.svg)

怎么读这张图：从左到右是一笔订单从命令到账户的路径，每个橙色框是一个可替换的模型，标出了它被调用的位置。最右边的模拟模块不在单笔订单的路径上，而是每个时间戳末尾作用于整个账户。

::: warning 常见误区
- **以为默认设置下回测没有任何摩擦。** 手续费模型必须显式配置；L1 上市价单用完盘口数量后的“差一个价位”是确定性规则，不受成交模型控制。
- **用概率参数却不给随机种子。** 每次运行结果都不同，无法比较参数。
- **以为 `prob_slippage` 在 L2 订单簿上也起作用。** 它只用于 L1。
- **在外汇品种上用 `TwoTierFillModel`。** 最优价只有 10 个单位，几乎所有成交都会差一个价位。
- **加了 1 毫秒延迟，以为成交价只差 1 毫秒。** 命令要等到这个品种的下一条行情才处理，只用 K 线时可能差一整根 K 线。
- **在多次 `reset()` 之间复用同一个有状态的 Python 模型。** 它的状态会延续到下一轮。
:::

## 本章结论

行为模型把历史数据回答不了的假设变成可替换的插件：成交模型决定挂单被碰到时是否成交、L1 成交是否随机滑一个价位，或者提供一个合成订单簿；手续费模型按挂单、吃单方向和名义金额计算每笔成交的佣金；延迟模型给命令一个到达时间，命令在到达后的第一个合适的结算点被处理；保证金模型决定保证金账户的占用。每个时间戳末尾运行的模拟模块处理隔夜利息这类账户级的调整。每类模型都有 trait、Any 枚举和 Handle 三种形态，Rust 自定义模型实现 trait 后包成 Handle 传给场所。

## 检查理解

1. L1 场所，`DefaultFillModel(prob_fill_on_limit = 0.3, prob_slippage = 0)`，同时有报价和成交数据。你挂了一张买入限价 1.1000。先来了一笔恰好在 1.1000 的卖方主动成交，之后一条报价的卖价是 1.0998。这张单分别会怎样？

   <details><summary>参考答案</summary>

   那笔成交的价格等于限价，满足“恰好碰到”的条件，按 0.3 的概率抽签，有 70% 的可能这次不成交。之后报价的卖价 1.0998 越过了限价，不抽签，一定成交，按限价 1.1000（挂单方不给价格改善）。如果第一次抽中了，订单在第一笔成交时就成交，数量以那笔成交的数量为上限（第 26 章第 5.3 节）。

   </details>

2. `MakerTakerFeeModel` 挂单费率 -0.0001、吃单费率 0.0004，`ETHUSDT` 现货。一张买入限价单 2 ETH @ 3,000 挂在盘口，后来被行情穿过成交。佣金是多少？如果这张单到达时就能立即成交呢？

   <details><summary>参考答案</summary>

   名义金额 6,000 USDT。挂单方成交：源码先对名义金额取绝对值再乘以费率，符号来自费率，`6,000 × (-0.0001) = -0.6` USDT，负的佣金表示返佣。到达时立即成交是吃单方：`6,000 × 0.0004 = 2.4` USDT。

   </details>

3. 只用 1 小时 K 线回测，配置了 `StaticLatencyModel`，基础延迟 50 毫秒。策略在 `on_bar` 里提交市价单。这张单按什么价格成交？和不加延迟相比有什么不同？

   <details><summary>参考答案</summary>

   不加延迟：命令在同一时间戳结清，按这根 K 线收盘时的订单簿成交，也就是收盘价附近。加了 50 毫秒延迟：到达时间是 K 线结束后 50 毫秒，但在下一根 K 线到来之前没有这个品种的行情，命令一直在在途队列里；下一根 K 线到来时，它的开、高、低、收四个点先依次撮合，之后命令才被处理，按下一根 K 线收盘时的状态成交。所以只用 K 线时，一点点延迟就会让成交推迟一整根 K 线。除非期间有计时器触发，计时器会释放所有到期命令。

   </details>

## 参考资料

- 官方文档：[Behavioral Models](https://nautilustrader.io/docs/latest/concepts/behavioral_models/) · [Fill Models](https://nautilustrader.io/docs/latest/concepts/backtesting/fill-models/) · [Execution Flow](https://nautilustrader.io/docs/latest/concepts/backtesting/execution-flow/) · [Simulation Modules](https://nautilustrader.io/docs/latest/concepts/backtesting/simulation-modules/)
- 源码：[`crates/execution/src/models/fill.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/execution/src/models/fill.rs) · [`crates/execution/src/models/fee.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/execution/src/models/fee.rs) · [`crates/execution/src/models/latency.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/execution/src/models/latency.rs) · [`crates/model/src/fees.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/model/src/fees.rs) · [`crates/model/src/accounts/margin_model.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/model/src/accounts/margin_model.rs) · [`crates/backtest/src/modules/`](https://github.com/nautechsystems/nautilus_trader/tree/develop/crates/backtest/src/modules)
- 配图由 `scripts/generate-nautilus-trader-figures.py` 生成。

回测跑完了，怎样知道它跑得好不好？下一章看回测结果、报告和统计指标是怎样算出来的。[第 28 章：报告、统计与可视化](./reports-and-statistics.md)。
