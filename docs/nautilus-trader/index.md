---
title: 深入理解 NautilusTrader
description: 从源码读开源量化交易平台 NautilusTrader：先从零编译、看全景架构（分层、源码目录、核心数据结构、PyO3 绑定），再读 Rust 核心（运行时、增加一个券商、重点主题），之后逐章拆开 NautilusKernel 的核心组件和 Tokio 运行时，最后读 Python 层。
---

# 深入理解 NautilusTrader

**从源码读一个量化交易平台**

[NautilusTrader](https://github.com/nautechsystems/nautilus_trader) 是一个开源的事件驱动交易平台：同一套策略代码既能回测，也能接实盘。它的核心已经全部用 Rust 实现，Python 层通过 PyO3 调用 Rust。本书先读 Rust 部分，再读 Python 部分。Rust 部分以“给它接入一个新券商（富途）”为主线：要接一个券商，就得弄清楚平台和外部世界之间的边界在哪里、边界两侧各自负责什么。

::: tip 阅读约定
源码以 GitHub 上 `develop` 分支为准，文中引用的文件路径、trait 和函数名都在 2026-11 核对过。项目更新很快，读到时如有出入，以仓库为准。网上很多资料讲的是旧的 Cython 版本（v1，现在在 `develop_v1` 分支），读的时候要分清。
:::

## 动手准备

- [从零编译：Rust 与 Python 两部分](./build-from-source.md)：从一台干净的 macOS 或 Ubuntu 开始，装工具链、取源码；Rust 部分用 `cargo` 跑通 `engine-ema-cross` 回测示例和单元测试，Python 部分用 `make build-debug` 编出 `_libnautilus` 并跑通一个 Python 回测；解释锁定的工具链、依赖冷却期检查、`PYO3_PYTHON` 等环境变量和各种构建 profile

## 导读

- [第 0 章 · NautilusTrader 架构](./nautilus-architecture.md)：一个节点的四层（Python、PyO3、节点外壳、内核）和两种线程；Rust 24 个 crate 的七层分层与每个 crate 的目录；Python 包怎样从 `_libnautilus` 转出、哪些是纯 Python；Rust 核心数据结构（定点数、标识符、行情、订单簿、订单、仓位、`Cache`、`MessageBus`）；这些结构投影到 Python 后的三种关系和快照语义

## 第一部分 · Rust 核心

- [第 1 章 · 整体架构](./architecture.md)：设计理念（单线程核心、回测实盘同构、crash-only），crate 分层与依赖图，`NautilusKernel`，线程局部的消息总线，一条报价和一笔订单的完整路径，组件与策略，回测、沙盒、实盘三种模式的异同
- [第 2 章 · 增加一个券商：以富途为例](./futu-adapter.md)：适配器要实现的 trait，富途适配器在 crate 依赖图和运行时里的位置，为什么参照 IB 适配器，富途 OpenD 协议要点，两边概念对照，Python 绑定的三条路线（PyO3 注册表、纯 Python 客户端、独立扩展），五个实现里程碑
- [第 3 章 · 其他需要重点理解的主题](./core-topics.md)：定点数值类型、时钟与两种时间戳、订单状态机与事件溯源、缓存、并发模型、风控与订单仿真、对账、数据与持久化、PyO3 边界、测试与错误处理
- [第 4 章 · 回调：一条消息怎样变成 on_xxx](./callbacks.md)：回调的六类来源；订阅时登记了什么（按 ID 取组件的闭包、总线订阅、数据引擎的引用计数）；一条报价怎样走到 `on_quote`；一笔成交怎样依次触发 `on_order_filled`、`on_order_event`、`on_position_opened`；计时器和生命周期回调；回调里能做什么、不能做什么；Python 回调和 Rust 回调的差别

## 规划中的章节

下面两部分尚未成文，先列出每章要回答的问题和对应的源码，写作时按这个顺序推进。第二部分逐个拆开内核里的组件，第三部分讲把内核接到真实世界的异步那一侧。每章都按同一个顺序展开：它持有什么数据、对外暴露哪些入口（总线端点、主题、trait 方法）、一条典型消息怎样流过它、回测和实盘下有什么不同、扩展时容易踩的坑。

### 第二部分 · NautilusKernel 与核心组件

| 章 | 主题 | 要回答的问题 | 主要源码 |
| --- | --- | --- | --- |
| 5 | NautilusKernel：组装、启动与关闭 | 构造顺序为什么是这样；`start`、`start_trader`、`stop`、`dispose` 各做什么；事件存储怎样在启动时恢复；crash-only 下重启走哪条路径 | `crates/system/src/{kernel,builder,clock_factory,event_store,config}.rs` |
| 6 | MessageBus：端点、主题与类型化路由 | 点对点、发布/订阅、请求/响应各怎样实现；类型化路由和 `topic_cache` 怎样省掉动态分派和模式匹配；订阅优先级；重入时的派发顺序 | `crates/common/src/msgbus/` |
| 7 | Cache：状态、索引与持久化接口 | 35 个字段和 31 张索引分别服务哪些查询；谁能写、谁只能读；`CacheApi` 为什么返回快照；`CacheDatabaseAdapter` 的写入语义 | `crates/common/src/cache/` |
| 8 | Clock 与计时器：时间从哪里来 | `Clock` trait；`VirtualClock` 的计时器堆怎样和数据时间线对齐；`TimeEvent` 怎样回到组件；两个时间戳 `ts_event`、`ts_init` | `crates/common/src/clock/`、`crates/common/src/timer.rs` |
| 9 | DataEngine：订阅、聚合与回放 | 订阅的引用计数和“最后一个持有者才退订”；K 线聚合；订单簿维护；历史数据请求；期权链 | `crates/data/src/engine/`、`aggregation.rs`、`option_chains/` |
| 10 | RiskEngine：下单前检查与限流 | 价格、数量、名义金额、余额、只减仓检查；`Throttler` 限流；交易状态 Active / Halted / Reducing；头寸规模计算 | `crates/risk/src/{engine,sizing.rs}`、`crates/common/src/throttler.rs` |
| 11 | ExecutionEngine：命令路由、订单与仓位 | 命令怎样路由到执行客户端；订单事件怎样驱动状态机；成交怎样开仓、加仓、平仓、反手；Netting 和 Hedging 的仓位 ID | `crates/execution/src/engine/` |
| 12 | OrderEmulator 与 OrderManager：本地条件单与关联订单 | 交易所不支持的条件单怎样在本地仿真、触发后释放；OCO / OTO / OUO 关联订单的联动；跟踪止损价的计算 | `crates/execution/src/{order_emulator,order_manager,trailing.rs}` |
| 13 | Portfolio：净头寸、盈亏与账户状态 | 净头寸和敞口怎样随报价更新；已实现、未实现盈亏；`AccountsManager` 怎样算冻结资金和保证金；权益曲线与统计 | `crates/portfolio/src/{portfolio,manager}.rs` |
| 14 | Trader：Actor、Strategy、执行算法与 Controller | 组件生命周期状态机；`DataActorCore`、`StrategyCore` 的组成；注册时接上了什么；执行算法和 TWAP；`Controller` 动态增删组件 | `crates/system/src/trader.rs`、`crates/common/src/actor/`、`crates/trading/src/` |
| 15 | 回测外壳：BacktestEngine 与模拟撮合 | 主循环一次迭代做什么；`SimulatedExchange` 和 `OrderMatchingEngine` 怎样撮合；手续费、成交、延迟模型；回测结果怎样产出 | `crates/backtest/src/{engine,exchange}.rs`、`crates/execution/src/matching_engine/` |

### 第三部分 · Tokio 运行时与实盘外壳

| 章 | 主题 | 要回答的问题 | 主要源码 |
| --- | --- | --- | --- |
| 16 | 全局 Tokio 运行时 | 为什么全进程只有一个运行时；`get_runtime()` 的懒初始化、`NAUTILUS_WORKER_THREADS`、`set_runtime` 注入；Python 下的初始化与退出；哪些后台工作不在 Tokio 上（日志线程） | `crates/common/src/live/runtime.rs` |
| 17 | LiveNode 与 AsyncRunner：核心线程上的事件循环 | 7 对 channel 和它们的优先级；发送端怎样存在线程局部里；`run` 与 `run_async`；启动和关闭的顺序 | `crates/live/src/{node,runner.rs}`、`crates/common/src/live/{runner,sender}.rs` |
| 18 | 任务管理：TaskGroup 与有界关闭 | 为什么不准直接 `tokio::spawn`；`TaskGroup`、`TaskSlot` 怎样把任务挂在所有者上；关闭时怎样在期限内收尾 | `crates/live/src/task.rs`、`crates/common/src/live/task.rs` |
| 19 | LiveClock 与实时计时器 | 实时计时器怎样由 Tokio 调度、到点后经 channel 回到核心线程；`AtomicTime` 的严格单调 | `crates/common/src/live/{clock,timer}.rs` |
| 20 | 网络层：HTTP、WebSocket 与 Socket 客户端 | 重连、退避、心跳；GCRA 限流；Socket 状态怎样发布、重连命令怎样下达；适配器怎样复用这一层 | `crates/network/src/`、`crates/live/src/socket.rs` |
| 21 | ExecutionManager：实盘执行管理与对账 | 启动对账和持续对账；订单、成交、持仓三类报告怎样合成本地事件；“结果未知”的命令怎样收尾 | `crates/live/src/execution/`、`crates/live/src/node/reconciliation.rs` |
| 22 | 订单簿同步与恢复 | 增量流断档时怎样发现、怎样用快照恢复；一致性检查 | `crates/live/src/book/` |
| 23 | 外部后端：Redis、PostgreSQL 与外部消息流 | 缓存怎样异步落盘、重启时怎样恢复；消息总线怎样把指定主题发布到 Redis 流、再从外部流收回 | `crates/infrastructure/src/{redis,sql}/`、`crates/common/src/msgbus/external/`、`crates/common/src/live/listener.rs` |
| 24 | 确定性仿真测试：让异步代码可重放 | DST 怎样替换 Tokio 的时间、任务和网络原语；`make cargo-test-sim` 跑什么；为什么官方适配器要求它 | `crates/common/src/live/dst.rs`、`crates/network/src/dst/` |

### 第四部分 · Python 层

待定。

