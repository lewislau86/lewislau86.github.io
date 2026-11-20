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

## 第一部分 · 交易领域模型

- [第 2 章 · 数值类型、标识符与时间戳](./value-types.md)：一行成交在内存里是什么；`Price`、`Quantity`、`Money` 的定点表示和两种精度模式；`Price::new` 与 `from_str` 怎样决定精度、何时悄悄舍入；运算、比较与会 panic 的情形；92 种内置币种；标识符的格式、校验与订单号、仓位号的生成；`UnixNanos`、`ts_event` 与 `ts_init`、`UUID4`
- [第 3 章 · 品种：从现货到期权、合成品种与连续期货](./instruments.md)：18 种品种与 `Instrument` trait；`make_price`、`make_qty` 的银行家舍入，以及它们和风控之间“不对齐最小变动价位”的缝隙；价位表、名义金额与反向合约；品种从哪里来；合成品种的公式计算；连续期货的换月表
- [第 4 章 · 行情数据与订单簿](./market-data.md)：`Data` 枚举里的内置行情类型；订单簿增量的四种动作和 `F_LAST`、`F_SNAPSHOT` 标志；一步一步维护一本二档簿；乱序、缺单与交叉；托管的簿与三种订阅；自有订单簿与过滤视图；自定义数据
- [第 5 章 · 订单：类型、有效期、状态机与条件单](./orders.md)：九种订单类型和七种有效期；15 个状态、19 种事件的转移表，以及它照着真实交易所写的几条规则；部分成交、重复成交与价格更正；一张括号单的一生；OTO、OCO、OUO；本地仿真单
- [第 6 章 · 成交、仓位与盈亏](./positions.md)：`Position` 的字段；NETTING 与 HEDGING 下仓位 ID 怎样分配；一串成交逐步算出均价、已实现盈亏与手续费；反手时成交怎样拆分；平仓后再开仓的快照；反向合约与盈亏币种
- [第 7 章 · 账户与保证金](./accounts.md)：四类账户；`total`、`locked`、`free` 与不变式；现金账户为挂单冻结什么、成交怎样改变余额；保证金账户的两种模型与两种口径；`AccountState` 的本地计算与交易所上报
- [第 8 章 · 事件与事件溯源](./events.md)：四类事件与 19 种订单事件；事件主题；一张平仓单的完整事件链；订单、仓位、账户怎样由事件重建；事件存储的抓取、写入、封存与回放，以及它目前的边界

## 第二部分 · 写策略

- [第 9 章 · Rust 策略的框架与运行机制](./rust-strategy.md)：一个最小策略要写什么；你写的、`nautilus_strategy!` 宏生成的、框架默认实现的三部分怎样拼成一个策略；`StrategyCore` 与 `StrategyConfig`；注册到 `Trader` 时接上了什么；生命周期；下单 API 与路由；关联订单、GTD、市场退出等托管功能；在回测和实盘里跑起来
- [第 10 章 · 回调：一条消息怎样变成 on_xxx](./callbacks.md)：回调的六类来源；订阅时登记了什么（按 ID 取组件的闭包、总线订阅、数据引擎的引用计数）；一条报价怎样走到 `on_quote`；一笔成交怎样依次触发 `on_order_filled`、`on_order_event`、`on_position_opened`；计时器和生命周期回调；回调里能做什么、不能做什么；Python 回调和 Rust 回调的差别
- [第 11 章 · K 线聚合器](./bar-aggregation.md)：`BarType` 字符串怎样决定 K 线从成交、报价还是更小的 K 线合成；`subscribe_bars` 之后 `DataEngine` 建了哪个聚合器、订了什么；`BarBuilder` 怎样累计；按笔数、成交量、成交额、失衡、连续、Renko、时间七种关闭规则；时间 K 线的定时器、时间戳与配置；组合 K 线与历史聚合；用 69,806 笔真实成交跑出来的实验
- [第 12 章 · 指标](./indicators.md)：内置指标在哪、按什么分类、为什么用 `f64`；`Indicator` trait 和 EMA、SMA、MACD、ATR 的实现细节；自己喂和注册给框架两种用法；`Indicators` 注册表怎样在 `on_bar` 之前更新指标、出错和停止时怎样处理；Rust 注册要打开的特性；Python 注册的指标每次更新怎样穿过语言边界；怎样预热；动手从零写一个指标：定规格、实现、rstest 与 proptest 单元测试、在回测里和独立算法逐根对账，Rust 和纯 Python 各做一遍
- [第 13 章 · Actor、执行算法与配置](./actors-and-config.md)：`DataActor`、`Strategy`、`ExecutionAlgorithm` 三种组件的能力边界；写一个 Rust Actor；用信号和自定义数据在组件之间通信；TWAP 怎样把一张主单拆成 `-E1`、`-E2`…子单；配置结构体的默认值与两条构造路径；日志线程与 `NAUTILUS_LOG`

## 第三部分 · 内核组件

- [第 14 章 · NautilusKernel：组装、启动与关闭](./kernel.md)：九步构造与依赖顺序；`start` 与 `start_trader` 为什么分两步、实盘节点在中间做什么；`stop_trader`、`finalize_stop`、`reset`、`dispose`；`save_state`、`load_state` 与 `shutdown_on_error`
- [第 15 章 · MessageBus：端点、主题与类型化路由](./message-bus.md)：点对点、发布订阅、请求响应；主题、模式与端点的类型；类型化路由与通用路由；发布一条报价时的匹配缓存、优先级与可重入派发；`queue_execute` 为什么存在；消息不可变
- [第 16 章 · Cache：状态、索引与持久化接口](./cache.md)：35 个字段与 31 张索引；一张限价单在索引里的足迹；`CacheApi`、`CacheView` 与带生命周期的借用；行情历史容量；尽力持久化与启动恢复；长时间运行的清理
- [第 17 章 · Clock 与计时器：时间从哪里来](./clock.md)：`Clock` trait 与计时器参数；回调的三级查找；`VirtualClock` 的最小堆；回测里同一时刻的数据与计时器谁先执行；严格单调的实时原子时钟与 `LiveClock`
- [第 18 章 · DataEngine：订阅、路由与历史请求](./data-engine.md)：订阅命令怎样选数据客户端；按持有者计数、最后一个持有者离开才真正退订；行情先写缓存再发布；订单簿的维护与缓冲；历史请求的登记、分派与响应；外部客户端
- [第 19 章 · RiskEngine：下单前检查与限流](./risk-engine.md)：一张单经过的检查与顺序；选账户与“预留”；交易状态 ACTIVE、REDUCING、HALTED；提交与改单的限流；头寸规模计算
- [第 20 章 · ExecutionEngine：路由命令、处理订单事件与成交](./execution-engine.md)：选执行客户端的四步顺序；提交前的场所与仓位 ID 检查；订单事件怎样找订单、更新缓存、发布；成交怎样决定 OMS 类型与仓位 ID、去重、处理超额；仓位翻转
- [第 21 章 · OrderEmulator 与 OrderManager：本地仿真与订单联动](./order-emulator.md)：仿真单的持有、触发规则与释放；仿真限价单为什么释放成市价单；本地改单、撤单与追踪止损；OTO、OCO、OUO 联动；仿真器和策略各自的订单管理器
- [第 22 章 · Portfolio：净头寸、盈亏与账户状态](./portfolio.md)：优先级 10 的订阅；订单事件为什么走端点和主题两条路；仓位事件触发的重算；未实现盈亏的取价顺序与延迟计算；查询接口、初始化与权益快照
- [第 23 章 · Trader：组件的生命周期与动态管理](./trader.md)：14 个状态的生命周期；Trader 为什么只存 ID；加入组件的限制；启动与停止的不同顺序和 `manage_stop`；运行时启停、移除组件与 Controller

## 第四部分 · 回测

- [第 24 章 · BacktestEngine 与 BacktestNode](./backtest-engine.md)：`add_venue` 建了哪些对象；多条数据流按 `ts_init` 和加入顺序合并；主循环处理一条数据的三个阶段与同步命令队列；`end`、`reset`、`dispose`；节点的一次性加载与分块流式运行；参数扫描
- [第 25 章 · 数据目录：Parquet 与 Arrow](./data-catalog.md)：按类型和标识符分目录、文件名即时间范围；写入时的升序、单一标识与区间不重叠检查；价格统一存成 `Decimal128(38, 16)`；查询先按文件名筛文件再用 DataFusion SQL；合并、删除与 Feather 流式写入
- [第 26 章 · 模拟交易所与撮合引擎](./simulated-exchange.md)：命令和行情两个入口；订单到达时的检查与按类型处理；L1 上挂单按限价成交、市价单剩余部分差一个价位；哪些数据驱动哪种订单簿；K 线拆成四个价格点与止损的跳空规则；场所配置
- [第 27 章 · 行为模型：成交、手续费、延迟与保证金](./behavioral-models.md)：成交模型的两个概率参数与合成订单簿；挂单、吃单佣金的计算；延迟模型的到达时间与结算点；模拟模块；Trait、Any 与 Handle 三种形态
- [第 28 章 · 报告、统计与可视化](./reports-and-statistics.md)：`BacktestResult` 的内容；三类统计各用什么输入；组合收益与仓位收益两条序列；夏普、期望值、盈亏比的公式与细节；自定义统计；Python 报表与业绩报告

## 第五部分 · 实盘与 Tokio 运行时

- [第 29 章 · 全局 Tokio 运行时](./tokio-runtime.md)：同步内核与异步 I/O 的界线；懒初始化的全局运行时、`NAUTILUS_WORKER_THREADS` 与 `set_runtime`；`block_on_nautilus` 系列桥接函数；Rust 和 Python 节点的线程分布；不准直接 `tokio::spawn` 的约定
- [第 30 章 · LiveNode 与 AsyncRunner：核心线程上的事件循环](./live-node.md)：7 对 channel 与 biased select 的优先级；防饿死的两个标记；线程局部的发送端；先连数据、再连执行、对账、再启动 Trader；维护计时器；宽限期与断开顺序
- [第 31 章 · 任务管理：TaskGroup 与有界关闭](./task-management.md)：先登记后运行；按“代”隔离连接；`begin_shutdown` 与 `finish_shutdown` 的两段取消、两个期限；超时后仍持有任务；`TaskSlot` 与 `finish_task`
- [第 32 章 · LiveClock 与实时计时器](./live-clock.md)：`AtomicTime` 的比较交换；每个计时器一个任务；固定间隔与日程两种节奏、错过时的补发；回调与令牌怎样回到核心线程；`ts_event`、`ts_init` 与回调时间
- [第 33 章 · 网络层：HTTP、WebSocket 与 Socket 客户端](./networking.md)：GCRA 限流与多键等待；WebSocket 的四个任务与连接纪元；心跳超时与空闲超时；重连退避、稳定阈值与节流；`SocketStateChanged` 与重连命令；TCP 的后缀分帧
- [第 34 章 · ExecutionManager：实盘执行管理与对账](./reconciliation.md)：四种执行报告；启动对账的五步与拒绝启动；缺少报告不等于空仓；外部订单的归属；在途、未结订单、仓位三种检查；`RetainUnresolved` 与 `ResolveLocally`
- [第 35 章 · 订单簿同步与恢复](./book-sync.md)：用序号发现断档；`BookSync` 的三个阶段与“必须有负责者”；标记、请求、认领、运行；快照闸门；180 秒 8 次再到 15 分钟的重试；输出契约
- [第 36 章 · 外部后端：Redis、PostgreSQL 与外部消息流](./external-backends.md)：不阻塞的成批写入；Redis 的键与事件列表；两种后端的持久化范围；消息总线的出站 `XADD` 与入站 `XREAD`；采集节点加策略节点的例子
- [第 37 章 · 确定性仿真测试：让异步代码可重放](./dst.md)：madsim 替换时间、任务、运行时和信号；时钟、随机数、迭代顺序、`biased;` 等接缝；确定性契约；提交前钩子的七条规则；`MADSIM_TEST_SEED` 重放；DST 的边界

## 第六部分 · 接入券商

- [第 38 章 · 增加一个券商：以富途为例](./futu-adapter.md)：官方开发指南《Adapters》的中文全译（一致性清单、适配器结构、0～9 实现阶段、Rust 适配器模式、执行与对账、HTTP / WebSocket 客户端模式、任务管理、测试、性能与文档），每一节后附“富途怎么做”；附录给出富途 OpenD 协议要点、两边的概念对照和 Python 绑定的三条路线

这一章会用到前面所有部分：数据和执行引擎、对账、网络层、任务管理和确定性仿真测试。放在最后，是把它当作综合实战；只想先接入券商的读者，读完导读也可以直接读，遇到没讲过的组件再回头查。

## 第七部分 · Python 层（规划中）

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
| Data、Order Book、Custom Data | 第 4 章；第 11 章（K 线聚合）；第 18 章；第 25 章（数据目录） |
| Options、Greeks | — |
| Events、Event Sourcing | 第 8 章；第 10 章（回调） |
| Orders | 第 5 章；第 21 章（仿真单与关联订单） |
| Execution | 第 19、20 章；第 13 章（执行算法）；第 34 章（对账） |
| Positions | 第 6 章 |
| Accounting、Portfolio | 第 7 章；第 22 章 |
| Reports、Visualization | 第 28 章 |
| Actors、Strategies | 第 9、10、12、13 章；第 23 章（生命周期） |
| Cache、Message Bus | 第 16 章；第 15 章；第 36 章（外部后端） |
| Configuration、Logging | 第 13 章 |
| Backtesting、Behavioral Models | 第 24、26、27 章 |
| Live Trading | 第 29～34 章；第 36 章 |
| Adapters、Networking | 第 38 章；第 33、35 章 |
| DST | 第 37 章 |
| 开发指南 Adapters | 第 38 章（全文翻译） |
