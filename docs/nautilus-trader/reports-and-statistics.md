---
title: "第 28 章：报告、统计与可视化"
description: 回测结束后 BacktestResult 里有什么；Portfolio 的统计怎样由 PortfolioAnalyzer 算出，三类统计各用什么输入；仓位收益和组合收益两条收益序列的区别；夏普比率、盈亏比、期望值等指标的具体公式和几个容易误解的细节；怎样写自定义统计；Python 的 ReportProvider 报表和 Plotly 业绩报告。
---

# 第 28 章：报告、统计与可视化

[全书目录](./index.md) · [上一章](./behavioral-models.md) · [下一篇](./futu-adapter.md)

::: tip 本章学习目标
能说出一次回测结束后有哪些结果可看、各自从哪里来；能解释三类统计（盈亏、收益、一般）分别用什么数据计算；知道统计用的收益序列在什么条件下是“组合日收益”、什么条件下退回“仓位收益”；能手算胜率、期望值、夏普比率，知道 NautilusTrader 的夏普比率不扣无风险利率、盈亏比是用收益而不是盈亏算的；会注册一个自定义统计；知道报表和业绩报告目前只在 Python 里有。

**源码版本：** `develop` 分支，提交 `364254f`（2026-11-18）。分析器和统计在 `crates/analysis/src/`（`analyzer.rs`、`statistic.rs`、`statistics/`），回测结果在 `crates/backtest/src/result.rs` 和 `engine.rs`（`get_result`、`log_post_run`），仓位收益在 `crates/model/src/position.rs`，报表和业绩报告在 `python/nautilus_trader/analysis/`（`reporter.py`、`tearsheet.py`）。

**对应官方文档：** [Reports](https://nautilustrader.io/docs/latest/concepts/reports/) · [Portfolio](https://nautilustrader.io/docs/latest/concepts/portfolio/)（Portfolio statistics、Returns 两节） · [Visualization](https://nautilustrader.io/docs/latest/concepts/visualization/)
:::

第 24 章的回测跑完后，`get_result()` 返回一个 `BacktestResult`，日志里还会打印一段“PORTFOLIO PERFORMANCE”。这一章看这些数字是怎样算出来的，以及怎样把它们变成表格和图。

主线例子用两组小数字，方便手算：一个 10 万美元的账户先后平掉了四个仓位，已实现盈亏依次是 +120、-50、+80、-30 美元；另有三天的组合日收益 +1%、-0.5%、+0.2%。

## 1. 跑完以后有什么 {#outputs}

`BacktestResult` 的字段分三组：

- **运行信息**：交易员 ID、实例 ID、运行配置 ID、运行 ID、运行的实际开始和结束时间（墙上时间）、回测数据的起止时间、迭代次数、事件数、订单数、仓位数（含快照）。注意 `elapsed_time_secs` 是**回测数据覆盖的时间跨度**（回测结束时间减开始时间），不是程序运行了多久；运行耗时要用 `run_finished - run_started`。
- **摘要** `summary`：一张字符串字典，有订单的开、平、仿真、在途数量，仓位的开、平、快照数量，每个场所账户的类型、基础货币和各币种余额。
- **统计**：`stats_pnls`（按币种，再按统计名）、`stats_returns`、`stats_general`，以及统计所用的收益序列 `returns_series`。

三类统计都来自 `Portfolio.statistics()`（第 22 章第 7 节）。`BacktestEngineConfig.run_analysis` 默认是 `true`，这时 `end()` 之后会把这三类统计打印到日志里，标题是 `PORTFOLIO PERFORMANCE`。

## 2. 统计从哪里来 {#analyzer}

Portfolio 内部有一个 `PortfolioAnalyzer`。调用 `statistics()` 时，Portfolio 把这些数据交给它：

- 每个账户的**初始余额**和**当前余额**；
- 缓存里的所有仓位，加上仓位快照（NETTING 下同一个 ID 的历史轮次，第 6 章）；
- 每个仓位平仓时记录下来的已实现盈亏（第 22 章第 4 节）；
- 组合快照（每日权益曲线，第 22 章第 7 节）。

分析器把它们整理成三种输入，每个统计按自己实现了哪个方法，归入对应的类别：

| 统计方法 | 输入 | 归入 |
| --- | --- | --- |
| `calculate_from_realized_pnls` | 某个币种按时间排列的每笔已实现盈亏 | `stats_pnls` |
| `calculate_from_returns` | 收益序列（第 3 节） | `stats_returns` |
| `calculate_from_positions` | 仓位和仓位快照 | `stats_general` |

一个统计可以实现多个方法，就会出现在多个类别里。除了注册的统计，盈亏类别里总有两项：`PnL (total)` 和 `PnL% (total)`，后者是 `(当前余额 + 未实现盈亏 - 初始余额) ÷ 初始余额 × 100`。

Portfolio 默认注册 20 个统计（`PortfolioAnalyzer::default`）：

- **按已实现盈亏**：最大、平均、最小盈利（`Max/Avg/Min Winner`），最小、平均、最大亏损（`Min/Avg/Max Loser`），期望值 `Expectancy`，胜率 `Win Rate`；
- **按收益**：年化波动率、偏度、峰度，平均收益、平均亏损收益、平均盈利收益，夏普比率、索提诺比率、尾部比率、盈亏比 `Profit Factor`、风险收益比 `Risk Return Ratio`；
- **按仓位**：多头比例 `Long Ratio`。

官方文档只说默认集合“包括”胜率、盈亏比、夏普比率和多头比例，完整列表要看源码。最大回撤 `MaxDrawdown`、卡玛比率、CAGR 等另外 14 个统计虽然已经实现，但默认没有注册，需要自己调用 `register_statistic` 加上。

## 3. 两条收益序列 {#returns}

收益类的统计用哪条序列，结果会很不一样。分析器维护两条：

- **仓位收益**：每个仓位平仓时记一个点，时间是平仓时间，值是这个仓位的 `realized_return`，即“按方向算的价格变动 ÷ 开仓均价”：多头是 `(平仓均价 - 开仓均价) ÷ 开仓均价`，空头相反。它只看价格变了百分之几，和仓位大小、杠杆、账户规模都无关。
- **组合收益**：从每日的组合快照算出的账户权益日变化率。一个 10 万美元账户某天赚了 900 美元，这一天的收益约是 0.9%。

规则是：组合快照覆盖**至少两个不同的 UTC 日期**时，用组合收益；否则退回仓位收益。所以一个只跑了 12 分钟的回测（比如第 24 章的例子），收益统计用的是仓位收益；而一个跨好几个月的回测，用的是组合收益。两者的夏普比率可能相差很大，比较两次回测的统计之前，先确认它们用的是同一种序列。

收益类统计在计算前还会做一步**按日合并**：同一个 UTC 日内的多个收益按复利合并成一个日收益。仓位收益如果一天平了很多仓位，也会被合成一个点。

## 4. 手算几个统计 {#examples}

**按已实现盈亏。** 四笔盈亏 +120、-50、+80、-30：

| 统计 | 计算 | 结果 |
| --- | --- | --- |
| 胜率 | 盈利笔数 ÷ (盈利 + 亏损笔数) | 2 ÷ 4 = 0.5 |
| 平均盈利 | (120 + 80) ÷ 2 | 100 |
| 平均亏损 | (-50 - 30) ÷ 2 | -40 |
| 期望值 | 平均盈利 × 胜率 + 平均亏损 × 败率 | 100 × 0.5 - 40 × 0.5 = 30 |
| 合计盈亏 | 求和 | 120 |

盈亏恰好为 0 的仓位既不算盈利也不算亏损，胜率和期望值的分母都不含它们。

**按收益。** 三个日收益 +1%、-0.5%、+0.2%：

- **夏普比率**：`均值 ÷ 样本标准差 × √252`。均值 0.2333%，样本标准差（除以 n-1）0.7506%，结果 `0.3109 × 15.87 ≈ 4.94`。注意两点：它**不扣无风险利率**；`252` 是 `SharpeRatio::new(None)` 的默认周期，可以换成别的值。
- **风险收益比**：同样的 `均值 ÷ 标准差`，但不年化，约 0.311。
- **盈亏比**：`正收益之和 ÷ |负收益之和|` = 1.2% ÷ 0.5% = 2.4。名字叫 Profit Factor，但源码里它实现的是 `calculate_from_returns`，用的是**收益**而不是盈亏，所以它出现在 `stats_returns` 里，而不是 `stats_pnls`。传统意义上“总盈利 ÷ 总亏损”的盈亏比，用第一组数字算是 200 ÷ 80 = 2.5，要自己写一个统计。
- **最大回撤**（需要先注册）：从 1 开始复利累乘，1.01、1.00495、1.00696，峰值 1.01 之后最低点 1.00495，回撤 0.5%，返回值是负数 `-0.005`。

数据不够时，多数统计返回 `NaN`：比如没有任何已实现盈亏时胜率是 `NaN`，只有一个日收益时标准差无法估计，夏普比率是 `NaN`。

## 5. 自定义统计 {#custom}

Rust 里的统计实现 `PortfolioStatistic` trait。要注意一个细节：`calculate_from_returns`、`calculate_from_realized_pnls`、`calculate_from_positions` 三个方法的默认实现会 **panic**，而分析器对每个注册的统计都会调用这三个方法，所以三个都要实现，不支持的类别返回 `None`（只有和基准比较的那个方法默认返回 `None`）。Python 的 `PortfolioStatistic` 则相反，没覆盖的方法不贡献结果。按传统定义算盈亏比：

```rust
#[derive(Debug)]
struct GrossProfitFactor;

impl PortfolioStatistic for GrossProfitFactor {
    type Item = f64;

    fn name(&self) -> String { "Gross Profit Factor".to_string() }

    fn calculate_from_realized_pnls(&self, pnls: &[f64]) -> Option<f64> {
        let profit: f64 = pnls.iter().filter(|p| **p > 0.0).sum();
        let loss: f64 = pnls.iter().filter(|p| **p < 0.0).sum();
        (loss < 0.0).then(|| profit / -loss)       // 没有亏损时返回 None
    }

    // 默认实现会 panic，不支持的类别显式返回 None
    fn calculate_from_returns(&self, _: &Returns) -> Option<f64> { None }
    fn calculate_from_positions(&self, _: &[Position]) -> Option<f64> { None }
}

engine.kernel().portfolio.borrow_mut().register_statistic(Arc::new(GrossProfitFactor));
```

同名的统计会被替换；在运行之前注册，回测结果和运行后的日志里才会有它。统计的计算方法在 Portfolio 持有内部借用时被调用，所以不要在里面再去调用会修改 Portfolio 的方法，否则会 panic；它应该是输入数据的纯函数。Python 里继承 `PortfolioStatistic`，规则相同。

如果要和基准比较（阿尔法、贝塔、信息比率、跟踪误差、上下行捕获率），这些统计实现的是 `calculate_from_returns_with_benchmark`，要用 `PortfolioAnalyzer.get_performance_stats_returns_vs_benchmark()` 并自己传入基准收益序列，Portfolio 的 `statistics()` 不会计算它们。

## 6. 报表 {#reports}

报表是把缓存里的订单、成交、仓位、账户状态转成 pandas `DataFrame`，由 Python 的 `ReportProvider` 生成，回测和实盘用法相同：

| 报表 | 每行是 | 生成方法 |
| --- | --- | --- |
| 订单 | 一张订单 | `generate_orders_report` |
| 已成交订单 | 一张有成交的订单 | `generate_order_fills_report` |
| 成交 | 一笔成交 | `generate_fills_report` |
| 仓位 | 一个仓位（可含快照） | `generate_positions_report` |
| 账户 | 一次账户状态的一个币种余额 | `generate_account_report` |

回测引擎和回测节点都有同名的便捷方法，直接读引擎自己的缓存。生成仓位报表时要把仓位快照一起传进去，否则 NETTING 下同一个 ID 多次开平的历史盈亏会丢失。价格、数量这类字段在报表里是字符串，保留了原始精度，做数值计算前要先转换。

Rust 这边目前没有对应的报表模块：Rust 程序直接从缓存读订单、成交和仓位，自己汇总。

## 7. 业绩报告 {#tearsheet}

`create_tearsheet` 用 Plotly 生成一个独立的 HTML 文件，可以直接在浏览器里打开，也可以导出成静态图片。需要安装 `visualization` 附加依赖（pandas、Plotly、Kaleido）。内置的图表有：运行信息表、统计表、权益曲线（可叠加基准）、回撤、月度收益热力图、收益分布、60 天滚动夏普、年度收益，以及带成交标记的 K 线图。图表和主题都可以注册自定义的。

```python
from nautilus_trader.analysis import create_tearsheet

engine.run()
create_tearsheet(engine=engine, output_path="backtest_results.html")
```

业绩报告里的收益序列和第 3 节的规则一致：有足够的组合快照就用组合收益，否则用仓位收益，再不行退回账户报表。

![回测结果的分析流程：左边是账户余额、仓位与快照、平仓时记录的已实现盈亏、每日组合快照四类输入；中间的 PortfolioAnalyzer 把它们整理成按币种的盈亏序列、收益序列（组合收益优先，否则仓位收益）和仓位列表，分别交给统计的三个计算方法；右边输出为三类统计、BacktestResult、运行后日志，以及 Python 的报表和业绩报告](/nautilus-trader/figures/analysis-pipeline.svg)

怎么读这张图：从左到右是数据的流向。中间三条横线对应第 2 节表格的三行。收益那一行有一个分叉：组合快照够两天就走上面，否则走下面，这决定了右边所有收益类统计的含义。

::: warning 常见误区
- **把 `elapsed_time_secs` 当成程序运行时间。** 它是回测数据的时间跨度。
- **比较两次回测的夏普比率，没注意收益序列不同。** 一次用组合日收益，另一次用仓位收益，数值不可比。
- **以为夏普比率扣了无风险利率。** 没有扣，周期默认 252。
- **把 `Profit Factor` 当成总盈利 ÷ 总亏损。** 源码用的是收益序列。
- **找不到最大回撤。** 它默认没有注册，要先 `register_statistic`。
- **生成仓位报表时不传快照。** NETTING 下的历史轮次会丢失。
- **在自定义统计里调用 Portfolio 的修改方法。** 会因为重复借用而 panic。
- **Rust 自定义统计只实现了一个计算方法。** 另外两个的默认实现会 panic，三个都要写。
:::

## 本章结论

回测结果由运行信息、摘要和三类统计组成，统计来自 Portfolio 内部的 `PortfolioAnalyzer`：按已实现盈亏算的进 `stats_pnls`，按收益序列算的进 `stats_returns`，按仓位算的进 `stats_general`。收益序列在组合快照覆盖两个以上 UTC 日期时用组合日收益，否则用仓位的价格收益，并且按日复利合并。默认注册 20 个统计，夏普比率不扣无风险利率、按 252 年化，盈亏比用的是收益，最大回撤需要手动注册。自定义统计实现 `PortfolioStatistic` 的某个计算方法后注册即可。报表和 HTML 业绩报告目前由 Python 提供。

## 检查理解

1. 一个只跑了一个交易日（UTC 同一天）的回测，平了 30 个仓位。夏普比率是多少？为什么？

   <details><summary>参考答案</summary>

   组合快照只覆盖一个 UTC 日期，用不了组合收益，退回仓位收益；30 个仓位的收益都在同一天，按日合并后只剩一个点。一个点算不出样本标准差，夏普比率是 `NaN`。想在日内回测上评估风险调整后的收益，要自己写一个不按日合并的统计，或者用多天的数据。

   </details>

2. 已实现盈亏是 +300、+300、-100、0。胜率、期望值、合计盈亏各是多少？

   <details><summary>参考答案</summary>

   0 不算盈利也不算亏损。胜率 = 2 ÷ 3 ≈ 0.667；平均盈利 300，平均亏损 -100，期望值 = 300 × 2/3 + (-100) × 1/3 ≈ 166.67；合计盈亏 500。注意期望值不是 500 ÷ 4 = 125，因为分母不含盈亏为 0 的那一笔。

   </details>

3. 你想在回测结果里看到最大回撤和一个“按盈亏算的传统盈亏比”。应该怎样做？

   <details><summary>参考答案</summary>

   在运行之前，对引擎的 Portfolio 调用 `register_statistic`，注册内置的 `MaxDrawdown` 和一个自定义统计（实现 `calculate_from_realized_pnls`，返回总盈利 ÷ 总亏损的绝对值）。运行后它们会出现在 `stats_returns` 和 `stats_pnls` 里，也会打印在运行后的日志中。最大回撤是负数，比如 -0.05 表示回撤 5%。

   </details>

## 参考资料

- 官方文档：[Reports](https://nautilustrader.io/docs/latest/concepts/reports/) · [Portfolio](https://nautilustrader.io/docs/latest/concepts/portfolio/) · [Visualization](https://nautilustrader.io/docs/latest/concepts/visualization/)
- 源码：[`crates/analysis/src/analyzer.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/analysis/src/analyzer.rs) · [`crates/analysis/src/statistic.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/analysis/src/statistic.rs) · [`crates/analysis/src/statistics/`](https://github.com/nautechsystems/nautilus_trader/tree/develop/crates/analysis/src/statistics) · [`crates/backtest/src/result.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/backtest/src/result.rs) · [`python/nautilus_trader/analysis/`](https://github.com/nautechsystems/nautilus_trader/tree/develop/python/nautilus_trader/analysis)
- 配图由 `scripts/generate-nautilus-trader-figures.py` 生成。

第四部分到这里结束。第五部分（实盘与 Tokio 运行时）还在规划中，下一篇已成文的章节是第六部分的综合实战：[第 38 章：增加一个券商：以富途为例](./futu-adapter.md)。
