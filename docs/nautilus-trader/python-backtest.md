---
title: "第 41 章：在 Python 里跑回测"
description: 从 Python 跑回测的两条路：低层的 BacktestEngine 自己装配交易所、品种、数据和组件，可以 reset 后换参数重跑、分批流式运行；高层的 BacktestNode 用 BacktestRunConfig 从 Parquet 数据目录读取、可分块；结果怎样以 BacktestResult、DataFrame 报表和 HTML 业绩报告取出；shutdown_on_error 怎样让回测提前结束；以及数据回调出错时“回测正常跑完、一张单也没有”的陷阱。
---

# 第 41 章：在 Python 里跑回测

[全书目录](./index.md) · [上一章](./python-components.md) · [下一章](./python-live.md)

::: tip 本章学习目标
能根据数据放在哪里、多大、要跑几组参数，选择 `BacktestEngine` 或 `BacktestNode`；会用 `reset` 复用已加载的数据做参数扫描，会用流式运行处理放不进内存的数据；会把数据写进 Parquet 数据目录，用 `BacktestRunConfig` 和可导入配置描述一次运行；知道结果从哪里取、报表什么时候还能取；知道 `shutdown_on_error` 的作用和数据回调出错时的表现。

**源码版本：** `develop` 分支，提交 `364254f`（2026-11-18）。回测引擎和节点的 Python 绑定在 `crates/backtest/src/python/`（`engine.rs`、`node.rs`、`config.rs`），业绩报告在 `python/nautilus_trader/analysis/tearsheet.py`，报表在 `analysis/reporter.py`。

**对应官方文档：** [Backtesting · APIs and runs](https://nautilustrader.io/docs/latest/concepts/backtesting/apis-and-runs/) · [Reports](https://nautilustrader.io/docs/latest/concepts/reports/) · [Visualization](https://nautilustrader.io/docs/latest/concepts/visualization/)
:::

第四部分从 Rust 一侧讲了回测引擎的主循环（第 24 章）、数据目录（第 25 章）和统计（第 28 章）。这一章换到 Python 用户的位置：同样的 Rust 引擎，在 Python 里有两种用法，各适合什么场景，结果怎样拿出来。

主线例子：一个双均线策略，在 ETHUSDT 的 69,806 笔成交上、以每 250 笔一根的 K 线运行（第 11、12 章用过的数据）。我们用四种方式跑它：一次性用 `BacktestEngine`、`reset` 之后重跑、分批流式运行、用 `BacktestNode` 从数据目录读，看结果是否一致。

## 1. 两条路 {#paths}

官方文档把两者称为低层和高层 API：

| | `BacktestEngine` | `BacktestNode` |
| --- | --- | --- |
| 数据从哪来 | 任何来源，你自己加进内存 | `ParquetDataCatalog` |
| 怎样描述一次运行 | 一连串方法调用 | 一个 `BacktestRunConfig` |
| 大数据 | 手动分批流式运行 | 设 `chunk_size` 自动分块 |
| 参数扫描 | `reset` 后复用已加载的数据 | 每组配置一个新节点 |

两者最后都落到同一个 Rust `BacktestEngine`（第 24 章）：`BacktestNode` 只是替你建引擎、从目录读数据、按配置加组件。

![Python 里跑回测的两条路：上面是 BacktestEngine 的手工装配、reset 重跑和流式运行；中间是 BacktestNode 从数据目录按配置运行、可分块；下面是 BacktestResult、DataFrame 报表、HTML 业绩报告和 shutdown_on_error](/nautilus-trader/figures/python-backtest-paths.svg)

怎么读这张图：上下两条泳道是两种用法，每个方框是一次方法调用或一个配置对象；最下面一行是两条路共用的结果出口。

## 2. BacktestEngine：自己装配 {#engine}

顺序是建引擎、加交易所和品种、加数据、加组件、运行：

```python
engine = BacktestEngine(BacktestEngineConfig(logging=LoggerConfig(stdout_level=LogLevel.ERROR)))
engine.add_venue(venue=BINANCE_VENUE, oms_type=OmsType.NETTING, account_type=AccountType.CASH,
                 base_currency=None, starting_balances=[...], fee_model=MakerTakerFeeModel(...))
engine.add_instrument(instrument)
engine.add_data(trades)
engine.add_strategy(EmaCross(EmaCrossConfig()))
engine.run()
```

几条官方文档里写明、实验里也能看到的规则：

- **每次 `add_data` 是一条独立的流。** 引擎在每条流内部按 `ts_init` 排序，运行时把所有流按时间归并（第 24 章的 k 路归并）。同一时刻的数据，先加入的流先送达。`add_data` 会拷贝输入，之后修改或清空原来的 Python 列表不影响已加载的数据。
- **交易所的费用必须显式给出。** 费用属于交易所配置，不属于品种；想要零费率基线，也要显式传一个零费率的 `MakerTakerFeeModel`。
- **`run()` 在当前线程上同步跑完。** 所有回调都在这个线程上（第 39 章）。

**重复运行。** `reset()` 把订单、仓位、账户余额、组件状态、计数器清回初始值，但保留已加载的数据、品种、交易所配置和已注册的组件。所以参数扫描的写法是：数据只加一次，每轮 `clear_strategies()`、加入新参数的策略、`run()`、`reset()`。实验里加载 69,806 笔成交只要 0.05 秒，每轮运行约 0.4 秒；同样的参数跑两次，结果逐项相同。

**数据放不进内存。** 低层 API 没有生成器式的接口，要自己分批：每批 `add_data`，`run(streaming=True)` 跑完这一批就暂停，`clear_data()` 释放，最后调用一次 `end()`。`end()` 才会把计时器推进到最后、调用组件的 `on_stop`、生成最终结果。实验里按每批 1 万笔成交分 7 批跑，结果和一次性运行完全相同，策略看到的也是同样的 279 根 K 线：K 线聚合器和指标的状态在批与批之间保留了下来。

## 3. BacktestNode：按配置从数据目录跑 {#node}

高层 API 要求数据在 Parquet 数据目录里（第 25 章）。从 Python 写目录很直接：

```python
catalog = ParquetDataCatalog(path)
catalog.write_instruments([instrument])
catalog.write_trade_ticks(trades)
```

一次运行由一个 `BacktestRunConfig` 描述：交易所（`BacktestVenueConfig`）、数据（`BacktestDataConfig`，指明数据类型、目录、品种）、引擎配置，以及可选的 `chunk_size`、时间范围、`dispose_on_completion`。策略在 `build()` 之后按运行 ID 加入，通常用可导入配置：

<<< @/public/nautilus-trader/code/python-lab/ch41_python_backtest.py#node

几点要注意：

- **可导入配置用“模块路径:类名”。** 策略类和配置类都要能被 `import` 到；`config` 字典交给配置类构造。这让一次运行可以完全用数据描述，方便保存、比较、分发到别的进程。
- **`chunk_size` 打开分块读取。** 取值在 1 到 1,000,000 之间；不设就一次读完。实验里不分块和每块 5,000 笔，结果完全相同。
- **运行结束后还要不要取报表。** `dispose_on_completion` 默认会在运行结束后释放引擎；要在 `run()` 之后用 `generate_*_report(run_config_id)` 取报表，要把它设为 `False`，用完自己 `dispose()`。
- **一组配置一个节点。** 官方文档的建议是：要跑几组独立的配置，就依次建节点、运行、释放，不要在一个进程里同时开多个节点（第 39 章第 7 节）。

## 4. 取出结果 {#results}

结果有三种形态：

- **`BacktestResult`**：`engine.get_result()` 或 `node.run()` 的返回值。里面有迭代次数、事件数、订单数、仓位数、起止时间，以及第 28 章的三组统计：`stats_pnls`（按币种）、`stats_returns`、`stats_general`，外加收益序列 `returns_series`。
- **报表**：`generate_orders_report()`、`generate_order_fills_report()`、`generate_positions_report()`、`generate_account_report(...)`，返回 pandas `DataFrame`，一行一个订单、成交或仓位。
- **业绩报告**：`nautilus_trader.analysis.tearsheet.create_tearsheet(engine)` 生成一份交互式的 HTML（用 plotly），包含权益曲线、回撤、月度收益、统计表等，可以用 `TearsheetConfig` 选择图表。

## 5. 出错时：提前结束，或者悄悄继续 {#errors}

**`shutdown_on_error`。** `BacktestEngineConfig(shutdown_on_error=True)` 时，Rust 日志器一旦记录一条 ERROR，就请求正常关闭：停止 Trader 和引擎，返回到那时为止的结果，进程不会退出。策略里的 `self.log.error(...)` 走的是 Rust 日志器，会触发；Python 标准库的 `logging.error(...)` 不会。实验里策略在第 100 根 K 线记一条 ERROR，打开这个开关后回测停在第 25,000 笔成交（正好 100 根 K 线），不开则照常跑完。

**数据回调里的异常。** 第 39 章说过，`on_bar` 里的异常只记一条 ERROR 日志，回测照常进行。这在回测里尤其危险。写这一章的实验时我就踩到了：第一版策略调用了一个不存在的方法 `self.portfolio.is_flat(...)`（正确的是 `is_net_flat`），每根 K 线都抛 `AttributeError`，回测正常跑完，结果是 0 张订单、0 个仓位，只在日志里留下一串 traceback。如果只看结果，很容易把它当成“策略没有发出信号”。两个办法：回测时打开 `shutdown_on_error`，第一个错误就会让运行停下来；或者至少检查运行结束后有没有 ERROR 日志。

## 6. 动手验证 {#lab}

::: info 实验环境
Linux（aarch64，4 核）上的 Python 3.14，nautilus_trader 2.0 的扩展模块由“从零编译”一章的 `make build-debug` 编出（未优化），对应提交 `364254f`。代码是 <a href="/nautilus-trader/code/python-lab/ch41_python_backtest.py" download><code>ch41_python_backtest.py</code></a>（[在 GitHub 查看](https://github.com/lewislau86/lewislau86.github.io/tree/master/docs/public/nautilus-trader/code/python-lab)），运行命令是 `uv run --project python --no-sync python ch41_python_backtest.py [段落名]`。`node` 段按模块路径导入脚本里的类，要直接运行这个文件、不要改名。下面的输出原样摘录，引擎日志已略去，耗时每次运行略有不同。
:::

策略本身：

<<< @/public/nautilus-trader/code/python-lab/ch41_python_backtest.py#strategy

**一次性运行与报表：**

<<< @/public/nautilus-trader/code/python-lab/ch41_python_backtest.py#engine

```text
  run took 0.39 s
  get_result(): iterations=69806 orders=16 positions=8 PnL(USDT)=-0.3561
  stats_pnls currencies: ['ETH', 'USDT']; first stats_returns keys: ['Average (Return)', 'Average Loss (Return)', 'Average Win (Return)']
  generate_orders_report(): DataFrame (16, 31)
  generate_order_fills_report(): DataFrame (16, 31)
  generate_positions_report(): DataFrame (8, 37)
```

**`reset` 后重跑与换参数：**

<<< @/public/nautilus-trader/code/python-lab/ch41_python_backtest.py#reset

```text
  add_data once: 0.05 s for 69806 trades
  EMA(10,20) in 0.40 s: iterations=69806 orders=16 positions=8 PnL(USDT)=-0.3561
  EMA(10,20) in 0.39 s: iterations=69806 orders=16 positions=8 PnL(USDT)=-0.3561
  EMA(5,15) in 0.40 s: iterations=69806 orders=20 positions=10 PnL(USDT)=0.0952
```

**分批流式运行：**

<<< @/public/nautilus-trader/code/python-lab/ch41_python_backtest.py#streaming

```text
  streaming, 10000 trades per batch: iterations=69806 orders=16 positions=8 PnL(USDT)=-0.3561
  strategy saw 279 bars
```

**`BacktestNode`**（代码见第 3 节）：

```text
  catalog files:
    data/currency_pair/ETHUSDT.BINANCE/1970-01-01T00-00-00-000000000Z_1970-01-01T00-00-00-000000000Z.parquet
    data/trades/ETHUSDT.BINANCE/2020-08-14T10-00-00-223000000Z_2020-08-14T14-59-58-693000000Z.parquet
  BacktestNode chunk_size=None in 0.49 s: iterations=69806 orders=16 positions=8 PnL(USDT)=-0.3561
    order fills report after the run: (16, 31)
  BacktestNode chunk_size=5000 in 0.47 s: iterations=69806 orders=16 positions=8 PnL(USDT)=-0.3561
    order fills report after the run: (16, 31)
```

数据目录里品种按类别存放（`currency_pair`），成交按品种存成一个覆盖整个时间范围的文件，文件名就是时间区间，和第 25 章讲的布局一致。

**`shutdown_on_error`：**

<<< @/public/nautilus-trader/code/python-lab/ch41_python_backtest.py#shutdown

```text
  shutdown_on_error=False: bars seen=279, iterations=69806
  shutdown_on_error=True: bars seen=100, iterations=25000
```

**业绩报告：**

<<< @/public/nautilus-trader/code/python-lab/ch41_python_backtest.py#tearsheet

```text
  create_tearsheet wrote 4724 KiB of HTML
```

报告是一个自包含的 HTML 文件，体积主要来自内嵌的 plotly 脚本。

四种跑法（一次性、`reset` 后重跑、流式、`BacktestNode` 分块与不分块）得到的订单数、仓位数和盈亏完全相同：16 张订单、8 个仓位、-0.3561 USDT。

::: warning 常见误区
- **只看回测结果，不看日志。** 数据回调里的异常只记日志，回测照常结束，结果可能是 0 张订单；打开 `shutdown_on_error` 或检查 ERROR 日志。
- **用 Python 的 `logging.error` 期望触发 `shutdown_on_error`。** 只有 Rust 日志器（组件的 `self.log`）的 ERROR 会触发。
- **参数扫描时每轮重新建引擎、重新加数据。** 数据只加一次，每轮 `clear_strategies()`、`run()`、`reset()`。
- **流式运行后忘了 `end()`。** 没有 `end()`，`on_stop` 不会被调用，最终结果也不完整。
- **想在 `BacktestNode.run()` 之后取报表，却用了默认的 `dispose_on_completion`。** 要设成 `False`，用完自己释放。
- **省略 `fee_model`，以为默认没有手续费。** 费用要在交易所配置里显式给出，零费率也要显式写。
:::

## 本章结论

Python 里跑回测有两条路，最后都落到同一个 Rust 回测引擎。`BacktestEngine` 适合数据在内存里、需要直接控制的场景：每次 `add_data` 是一条独立的流，`reset` 保留数据和组件、只清交易状态，适合参数扫描；数据太大时按批 `run(streaming=True)`，最后 `end()`。`BacktestNode` 适合数据在 Parquet 目录里的场景：一个 `BacktestRunConfig` 描述交易所、数据和引擎，策略用可导入配置加入，`chunk_size` 打开分块读取，`dispose_on_completion=False` 才能在运行后取报表。结果有 `BacktestResult`、DataFrame 报表和 HTML 业绩报告三种形态。实验里四种跑法结果完全一致。`shutdown_on_error` 让 Rust 日志器的第一条 ERROR 提前结束回测；不开它时，数据回调里的异常只会悄悄地让策略少做事。

## 检查理解

1. 你要在同一份 3 个月的分钟 K 线上测试 50 组均线参数，数据能放进内存。应该怎样组织代码？

   <details><summary>参考答案</summary>

   用 `BacktestEngine`：建一次引擎，加交易所、品种和数据各一次；然后循环 50 次，每次 `clear_strategies()`、加入当前参数的策略、`run()`、取 `get_result()`、`reset()`。`reset` 只清交易状态，保留数据和交易所配置，省掉 50 次加载和排序。每轮的结果之间互不影响，实验里同样的参数跑两次结果逐项相同。

   </details>

2. 一次回测跑完了，订单数是 0。在怀疑策略逻辑之前，应该先检查什么？

   <details><summary>参考答案</summary>

   先看日志里有没有 `Python on_bar failed`（或其他回调）的 ERROR。数据回调里的异常不会让回测停止，只会让那条消息的处理中断；如果每根 K 线都抛异常，结果就是一张单也没有。之后的回测可以打开 `shutdown_on_error=True`，让第一个错误就终止运行。

   </details>

3. `BacktestNode` 的运行配置设了 `chunk_size=5000`。和不设相比，结果会不同吗？什么情况下可能不同？

   <details><summary>参考答案</summary>

   对普通的成交、报价、K 线，结果应该相同：分块只改变从目录读取数据的方式，回放顺序不变，实验里两者完全一致。需要注意的是订单簿增量：节点默认把一个完整的订单簿事件（到 `F_LAST` 为止）作为一批回放，分块按批计数，时间边界或过滤条件如果把一个事件切开，可能得到不完整的事件，官方文档要求选择能保持事件完整的边界。

   </details>

## 参考资料

- 官方文档：[Backtesting · APIs and runs](https://nautilustrader.io/docs/latest/concepts/backtesting/apis-and-runs/) · [Reports](https://nautilustrader.io/docs/latest/concepts/reports/) · [Visualization](https://nautilustrader.io/docs/latest/concepts/visualization/)
- 源码：[`crates/backtest/src/python/engine.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/backtest/src/python/engine.rs) · [`crates/backtest/src/python/node.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/backtest/src/python/node.rs) · [`python/nautilus_trader/analysis/tearsheet.py`](https://github.com/nautechsystems/nautilus_trader/blob/develop/python/nautilus_trader/analysis/tearsheet.py) · [`python/nautilus_trader/analysis/reporter.py`](https://github.com/nautechsystems/nautilus_trader/blob/develop/python/nautilus_trader/analysis/reporter.py)
- 实验代码：[`python-lab`](https://github.com/lewislau86/lewislau86.github.io/tree/master/docs/public/nautilus-trader/code/python-lab)
- 配图由 `scripts/generate-nautilus-trader-figures.py` 生成。

回测验证过的策略，下一步是放到实盘节点里。下一章看在 Python 里跑实盘：`run()` 和 `run_async()` 的区别、怎样把节点托管在 asyncio 应用里。[第 42 章：在 Python 里跑实盘](./python-live.md)。
