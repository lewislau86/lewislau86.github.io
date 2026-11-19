---
title: 深入理解 NautilusTrader
description: 从源码读开源量化交易平台 NautilusTrader：先从零编译、看全景架构和运行全景，再按官方文档的概念划分逐部分深入：交易领域模型、写策略（策略框架、回调、K 线、指标）、内核组件、回测、实盘与 Tokio 运行时，最后以接入富途为综合实战，并读 Python 层。
---

# 深入理解 NautilusTrader

**从源码读一个量化交易平台**

[NautilusTrader](https://github.com/nautechsystems/nautilus_trader) 是一个开源的事件驱动交易平台：同一套策略代码既能回测，也能接实盘。它的核心已经全部用 Rust 实现，Python 层通过 PyO3 调用 Rust。官方文档是一份使用手册，讲每个概念是什么、怎样用；本书从源码讲它们怎样实现、为什么这样设计、扩展时会踩什么坑。全书的结构和官方文档的概念划分对齐，文末有一张[官方文档对照表](#official-docs)。

::: tip 阅读约定
源码以 GitHub 上 `develop` 分支为准，文中引用的文件路径、trait 和函数名都在 2026-11 核对过。项目更新很快，读到时如有出入，以仓库为准。网上很多资料讲的是旧的 Cython 版本（v1，现在在 `develop_v1` 分支），读的时候要分清。
:::

::: info 全书结构
导读给出静态的地图（第 0 章）和动态的全景（第 1 章）。第一部分讲交易领域模型：品种、数据、订单、仓位、账户、事件，这是读后面所有章节的词汇表。第二部分从写策略的人的角度看：策略框架、回调、K 线、指标。第三部分逐个拆开内核组件。第四部分讲回测，第五部分讲实盘和 Tokio 运行时。第六部分以接入富途为综合实战，用到前面所有部分。第七部分讲 Python 层。已成文的章节可以跳着读，每章开头都写了前置知识和对应的官方文档。
:::

## 动手准备

- [从零编译：Rust 与 Python 两部分](./build-from-source.md)：从一台干净的 macOS 或 Ubuntu 开始，装工具链、取源码；Rust 部分用 `cargo` 跑通 `engine-ema-cross` 回测示例和单元测试，Python 部分用 `make build-debug` 编出 `_libnautilus` 并跑通一个 Python 回测；解释锁定的工具链、依赖冷却期检查、`PYO3_PYTHON` 等环境变量和各种构建 profile

## 导读

- [第 0 章 · NautilusTrader 架构](./nautilus-architecture.md)：一个节点的四层（Python、PyO3、节点外壳、内核）和两种线程；Rust 24 个 crate 的七层分层与每个 crate 的目录；Python 包怎样从 `_libnautilus` 转出、哪些是纯 Python；Rust 核心数据结构（定点数、标识符、行情、订单簿、订单、仓位、`Cache`、`MessageBus`）；这些结构投影到 Python 后的三种关系和快照语义
- [第 1 章 · 运行全景](./architecture.md)：设计理念（单线程核心、回测实盘同构、crash-only），crate 分层与依赖图，`NautilusKernel`，线程局部的消息总线，一条报价和一笔订单的完整路径，组件与策略，回测、沙盒、实盘三种模式的异同

## 第一部分 · 交易领域模型（规划中）

| 章 | 主题 | 要回答的问题 | 主要源码 |
| --- | --- | --- | --- |
| 2 | 数值类型、标识符与时间戳 | `Price`、`Quantity`、`Money` 为什么是定点数，64 位和 128 位两种精度模式；各种标识符的格式和约束；`UnixNanos`、`ts_event` 与 `ts_init`、`UUID4` | `crates/model/src/{types,identifiers}/`、`crates/core/src/{nanos,uuid}.rs` |
| 3 | 品种：从现货到期权、合成品种与连续期货 | 十几种品种类型各有哪些字段；价格精度、最小变动价位、乘数怎样影响下单和盈亏；合成品种怎样由表达式算价；连续期货怎样换月 | `crates/model/src/instruments/`、`crates/data/src/engine/{synthetic,futures}.rs` |
| 4 | 行情数据与订单簿 | 报价、成交、K 线、订单簿增量与快照、标记价、资金费率各是什么结构；增量的标志位和事件边界；`OrderBook` 怎样维护、自有订单怎样跟踪；自定义数据怎样注册 | `crates/model/src/{data,orderbook}/`、`crates/common/src/custom.rs` |
| 5 | 订单：类型、有效期、状态机与条件单 | 九种订单类型和七种有效期；只挂单、只减仓、冰山；订单状态机的十几个状态和十九种事件；OCO / OTO / OUO；本地仿真单 | `crates/model/src/orders/`、`crates/model/src/enums.rs` |
| 6 | 成交、仓位与盈亏 | 成交怎样开仓、加仓、减仓、反手；Netting 和 Hedging 两种订单管理模式下仓位 ID 怎样分配；已实现和未实现盈亏、手续费怎样计 | `crates/model/src/position.rs`、`crates/model/src/events/position/` |
| 7 | 账户与保证金 | 现金、保证金、博彩、钱包四类账户；余额与冻结；逐品种和全账户两种保证金口径；保证金模型 | `crates/model/src/accounts/` |
| 8 | 事件与事件溯源 | 订单、仓位、账户、时间四类事件；从成交到仓位事件的因果链；事件存储怎样记录、怎样回放和恢复 | `crates/model/src/events/`、`crates/system/src/event_store.rs` |

## 第二部分 · 写策略

- [第 9 章 · Rust 策略的框架与运行机制](./rust-strategy.md)：一个最小策略要写什么；你写的、`nautilus_strategy!` 宏生成的、框架默认实现的三部分怎样拼成一个策略；`StrategyCore` 与 `StrategyConfig`；注册到 `Trader` 时接上了什么；生命周期；下单 API 与路由；关联订单、GTD、市场退出等托管功能；在回测和实盘里跑起来
- [第 10 章 · 回调：一条消息怎样变成 on_xxx](./callbacks.md)：回调的六类来源；订阅时登记了什么（按 ID 取组件的闭包、总线订阅、数据引擎的引用计数）；一条报价怎样走到 `on_quote`；一笔成交怎样依次触发 `on_order_filled`、`on_order_event`、`on_position_opened`；计时器和生命周期回调；回调里能做什么、不能做什么；Python 回调和 Rust 回调的差别
- [第 11 章 · K 线聚合器](./bar-aggregation.md)：`BarType` 字符串怎样决定 K 线从成交、报价还是更小的 K 线合成；`subscribe_bars` 之后 `DataEngine` 建了哪个聚合器、订了什么；`BarBuilder` 怎样累计；按笔数、成交量、成交额、失衡、连续、Renko、时间七种关闭规则；时间 K 线的定时器、时间戳与配置；组合 K 线与历史聚合；用 69,806 笔真实成交跑出来的实验
- [第 12 章 · 指标](./indicators.md)：内置指标在哪、按什么分类、为什么用 `f64`；`Indicator` trait 和 EMA、SMA、MACD、ATR 的实现细节；自己喂和注册给框架两种用法；`Indicators` 注册表怎样在 `on_bar` 之前更新指标、出错和停止时怎样处理；Rust 注册要打开的特性；Python 注册的指标每次更新怎样穿过语言边界；怎样预热；怎样自己写一个指标
- 第 13 章 · Actor、执行算法与配置（规划中）：不下单的 `Actor` 能做什么；执行算法（如 TWAP）怎样拆单、怎样被策略调用；配置结构体在 Rust 和 Python 两侧怎样定义、默认值怎样解析；日志怎样配置

## 规划中的章节

下面几部分尚未成文，先列出每章要回答的问题和对应的源码，写作时按这个顺序推进。内核组件的每章都按同一个顺序展开：它持有什么数据、对外暴露哪些入口（总线端点、主题、trait 方法）、一条典型消息怎样流过它、回测和实盘下有什么不同、扩展时容易踩的坑。

### 第三部分 · 内核组件

| 章 | 主题 | 要回答的问题 | 主要源码 |
| --- | --- | --- | --- |
| 14 | NautilusKernel：组装、启动与关闭 | 构造顺序为什么是这样；`start`、`start_trader`、`stop`、`dispose` 各做什么；事件存储怎样在启动时恢复；crash-only 下重启走哪条路径 | `crates/system/src/{kernel,builder,clock_factory,event_store,config}.rs` |
| 15 | MessageBus：端点、主题与类型化路由 | 点对点、发布/订阅、请求/响应各怎样实现；类型化路由和 `topic_cache` 怎样省掉动态分派和模式匹配；订阅优先级；重入时的派发顺序 | `crates/common/src/msgbus/` |
| 16 | Cache：状态、索引与持久化接口 | 35 个字段和 31 张索引分别服务哪些查询；谁能写、谁只能读；`CacheApi` 为什么返回快照；`CacheDatabaseAdapter` 的写入语义 | `crates/common/src/cache/` |
| 17 | Clock 与计时器：时间从哪里来 | `Clock` trait；`VirtualClock` 的计时器堆怎样和数据时间线对齐；`TimeEvent` 怎样回到组件；两个时间戳 `ts_event`、`ts_init` | `crates/common/src/clock/`、`crates/common/src/timer.rs` |
| 18 | DataEngine：订阅、路由与历史请求 | 订阅的引用计数和“最后一个持有者才退订”；数据怎样写缓存再发布；K 线聚合的引擎侧接线（聚合器本身见第 11 章）；订单簿维护；历史数据请求；期权链 | `crates/data/src/engine/`、`aggregation.rs`、`option_chains/` |
| 19 | RiskEngine：下单前检查与限流 | 价格、数量、名义金额、余额、只减仓检查；`Throttler` 限流；交易状态 Active / Halted / Reducing；头寸规模计算 | `crates/risk/src/{engine,sizing.rs}`、`crates/common/src/throttler.rs` |
| 20 | ExecutionEngine：命令路由、订单与仓位 | 命令怎样路由到执行客户端；订单事件怎样驱动状态机；成交怎样开仓、加仓、平仓、反手；Netting 和 Hedging 的仓位 ID | `crates/execution/src/engine/` |
| 21 | OrderEmulator 与 OrderManager：本地条件单与关联订单 | 交易所不支持的条件单怎样在本地仿真、触发后释放；OCO / OTO / OUO 关联订单的联动；跟踪止损价的计算 | `crates/execution/src/{order_emulator,order_manager,trailing.rs}` |
| 22 | Portfolio：净头寸、盈亏与账户状态 | 净头寸和敞口怎样随报价更新；已实现、未实现盈亏；`AccountsManager` 怎样算冻结资金和保证金；权益曲线与统计 | `crates/portfolio/src/{portfolio,manager}.rs` |
| 23 | Trader：组件的生命周期与动态管理 | 组件生命周期状态机；`Trader` 怎样登记、启动、停止各类组件；`Controller` 动态增删组件；和第 9、13 章的分工 | `crates/system/src/trader.rs`、`crates/common/src/actor/`、`crates/trading/src/` |

### 第四部分 · 回测

| 章 | 主题 | 要回答的问题 | 主要源码 |
| --- | --- | --- | --- |
| 24 | BacktestEngine 与 BacktestNode | 低层 API 和高层 API 各适合什么；主循环一次迭代做什么、数据和计时器怎样交替推进；一次运行怎样配置、怎样重置再跑 | `crates/backtest/src/{engine,node,data_iterator}.rs` |
| 25 | 数据目录：Parquet 与 Arrow | 数据目录的文件布局和命名；怎样写入、查询、合并；回测怎样从目录流式读数据 | `crates/persistence/src/`、`crates/serialization/` |
| 26 | 模拟交易所与撮合引擎 | `SimulatedExchange` 持有什么；`OrderMatchingEngine` 怎样用报价、成交、K 线、订单簿撮合；K 线数据下的成交价怎样推断 | `crates/backtest/src/exchange.rs`、`crates/execution/src/matching_engine/` |
| 27 | 行为模型：成交、手续费、延迟与保证金 | 成交模型、手续费模型、延迟模型、保证金模型各在哪一步起作用；怎样自定义一个模型 | `crates/execution/src/models/`、`crates/model/src/accounts/margin_model.rs` |
| 28 | 报告、统计与可视化 | 订单、成交、仓位、账户报告怎样生成；收益统计怎样计算；Python 一侧的 tearsheet 怎样画 | `crates/analysis/src/`、`python/nautilus_trader/analysis/` |

### 第五部分 · 实盘与 Tokio 运行时

| 章 | 主题 | 要回答的问题 | 主要源码 |
| --- | --- | --- | --- |
| 29 | 全局 Tokio 运行时 | 为什么全进程只有一个运行时；`get_runtime()` 的懒初始化、`NAUTILUS_WORKER_THREADS`、`set_runtime` 注入；Python 下的初始化与退出；哪些后台工作不在 Tokio 上（日志线程） | `crates/common/src/live/runtime.rs` |
| 30 | LiveNode 与 AsyncRunner：核心线程上的事件循环 | 7 对 channel 和它们的优先级；发送端怎样存在线程局部里；`run` 与 `run_async`；启动和关闭的顺序 | `crates/live/src/{node,runner.rs}`、`crates/common/src/live/{runner,sender}.rs` |
| 31 | 任务管理：TaskGroup 与有界关闭 | 为什么不准直接 `tokio::spawn`；`TaskGroup`、`TaskSlot` 怎样把任务挂在所有者上；关闭时怎样在期限内收尾 | `crates/live/src/task.rs`、`crates/common/src/live/task.rs` |
| 32 | LiveClock 与实时计时器 | 实时计时器怎样由 Tokio 调度、到点后经 channel 回到核心线程；`AtomicTime` 的严格单调 | `crates/common/src/live/{clock,timer}.rs` |
| 33 | 网络层：HTTP、WebSocket 与 Socket 客户端 | 重连、退避、心跳；GCRA 限流；Socket 状态怎样发布、重连命令怎样下达；适配器怎样复用这一层 | `crates/network/src/`、`crates/live/src/socket.rs` |
| 34 | ExecutionManager：实盘执行管理与对账 | 启动对账和持续对账；订单、成交、持仓三类报告怎样合成本地事件；“结果未知”的命令怎样收尾 | `crates/live/src/execution/`、`crates/live/src/node/reconciliation.rs` |
| 35 | 订单簿同步与恢复 | 增量流断档时怎样发现、怎样用快照恢复；一致性检查 | `crates/live/src/book/` |
| 36 | 外部后端：Redis、PostgreSQL 与外部消息流 | 缓存怎样异步落盘、重启时怎样恢复；消息总线怎样把指定主题发布到 Redis 流、再从外部流收回 | `crates/infrastructure/src/{redis,sql}/`、`crates/common/src/msgbus/external/`、`crates/common/src/live/listener.rs` |
| 37 | 确定性仿真测试：让异步代码可重放 | DST 怎样替换 Tokio 的时间、任务和网络原语；`make cargo-test-sim` 跑什么；为什么官方适配器要求它 | `crates/common/src/live/dst.rs`、`crates/network/src/dst/` |

## 第六部分 · 接入券商

- [第 38 章 · 增加一个券商：以富途为例](./futu-adapter.md)：官方开发指南《Adapters》的中文全译（一致性清单、适配器结构、0～9 实现阶段、Rust 适配器模式、执行与对账、HTTP / WebSocket 客户端模式、任务管理、测试、性能与文档），每一节后附“富途怎么做”；附录给出富途 OpenD 协议要点、两边的概念对照和 Python 绑定的三条路线

这一章会用到前面所有部分：数据和执行引擎、对账、网络层、任务管理和确定性仿真测试。放在最后，是把它当作综合实战；只想先接入券商的读者，读完导读也可以直接读，遇到没讲过的组件再回头查。

### 第七部分 · Python 层（规划中）

| 章 | 主题 | 要回答的问题 | 主要源码 |
| --- | --- | --- | --- |
| 39 | Python 策略：Rust 策略框架的绑定 | Python 的 `Strategy` 怎样包住第 9 章的 Rust 框架：`PyStrategy` 与 `PyStrategyInner`、配置类的取值、注册时做了什么、每个回调怎样转发到 Python、下单参数怎样转成 Rust 值；和 Rust 策略相比多了哪些开销、少了哪些能力 | `crates/trading/src/python/strategy.rs`、`crates/system/src/python/registration.rs` |

其余章节待定。

## 附录

- [重点主题速览](./core-topics.md)：定点数值类型、时钟与两种时间戳、订单状态机与事件溯源、缓存、并发模型、风控与订单仿真、对账、数据与持久化、PyO3 边界、测试与错误处理。本页原是第 3 章，各主题会在正文对应章节展开，那些章节成文之前作为速览保留

## 官方文档对照表 {#official-docs}

下表按官方文档 Concepts 的页面顺序列出本书对应的章节。“—”表示本书暂不覆盖。

| 官方页面 | 本书章节 |
| :--- | :--- |
| Overview、Architecture | 第 0 章、第 1 章 |
| Rust、Python | 第 0 章第 2～4 节；第 9 章；第七部分 |
| Instruments、Synthetics、Continuous Futures | 第 3 章 |
| Value Types | 第 2 章 |
| Data、Order Book、Custom Data | 第 4 章；第 11 章（K 线聚合）；第 18 章 |
| Options、Greeks | — |
| Events、Event Sourcing | 第 8 章；第 10 章（回调） |
| Orders | 第 5 章；第 21 章（仿真单与关联订单） |
| Execution | 第 20 章；第 13 章（执行算法）；第 34 章（对账） |
| Positions | 第 6 章 |
| Accounting、Portfolio | 第 7 章；第 22 章 |
| Reports、Visualization | 第 28 章 |
| Actors、Strategies | 第 9、10、12、13 章 |
| Cache、Message Bus | 第 16 章；第 15 章 |
| Configuration、Logging | 第 13 章 |
| Backtesting、Behavioral Models | 第四部分（第 24～28 章） |
| Live Trading | 第五部分（第 29～37 章） |
| Adapters、Networking | 第 38 章；第 33 章 |
| DST | 第 37 章 |
| 开发指南 Adapters | 第 38 章（全文翻译） |
