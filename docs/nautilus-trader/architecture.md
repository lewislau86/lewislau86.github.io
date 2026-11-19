---
title: "第 1 章：运行全景"
description: NautilusTrader 的 Rust 核心怎样组织：设计理念、crate 分层与依赖、NautilusKernel、线程局部的消息总线、行情与订单两条主线、组件与策略，以及回测、沙盒、实盘三种模式共用同一个内核的方式。
---

# 第 1 章：运行全景

[全书目录](./index.md) · [上一章](./nautilus-architecture.md) · [下一章](./value-types.md)

::: tip 本章学习目标
能画出 NautilusTrader 的组件图：哪些 crate 是地基、哪些是引擎、哪些是外壳；说清 `NautilusKernel` 拥有什么、消息总线怎样把组件连起来；能沿源码走一遍“一条报价从适配器到策略”和“一笔订单从策略到交易所再回来”的路径；能解释回测、沙盒、实盘三种模式为什么能共用同一套策略代码，以及它们各自的时钟和成交来源。

**源码版本：** `develop` 分支，2026-11-14 核对。文中的路径都相对仓库根目录。

**对应官方文档：** [Architecture](https://nautilustrader.io/docs/latest/concepts/architecture/) · [Message Bus](https://nautilustrader.io/docs/latest/concepts/message_bus/) · [Live Trading](https://nautilustrader.io/docs/latest/concepts/live/)
:::

## 1. 它要解决什么问题

量化交易系统有一个老问题：研究时用一套回测代码，上线时换成另一套实盘代码，两边行为对不上，回测里赚钱的策略上线就变样。NautilusTrader 的回答是**同一个内核跑三种环境**：回测（Backtest）、沙盒（Sandbox，实时行情加模拟成交）、实盘（Live），对应 `Environment` 枚举。`crates/README.md` 的原话是：“research, deterministic simulation, and live execution within a single event-driven architecture, providing research-to-live semantic parity”。

官方架构文档（`docs/concepts/architecture.md`）列出的设计风格有五项：领域驱动设计（DDD）、事件驱动、消息模式（发布/订阅、请求/响应、点对点）、端口与适配器（六边形架构），以及 crash-only 设计。读源码时最该先记住的是两条：

- **核心是单线程的。** 同一个节点里，消息派发、策略逻辑、风控检查、执行协调、缓存读写都在**同一个线程**上串行执行，文档拿 LMAX 交易所的架构作类比。网络 I/O、日志、持久化跑在后台的 Tokio 运行时上，通过 channel 把事件送回核心线程。所以核心代码里到处是 `Rc<RefCell<…>>`，而不是 `Arc<Mutex<…>>`。
- **crash-only。** release 构建遇到 panic 直接退出（`panic = "abort"`），由外部守护进程重启；重启后走正常的启动流程，从缓存或事件存储恢复，再和交易所对账。没有单独的“故障恢复”代码路径。

还有一条现状要知道：`develop` 分支是 v2，核心全部是 Rust，Python 包通过 PyO3 调用 Rust（扩展模块叫 `nautilus_trader._libnautilus`），`python/nautilus_trader/` 只是一层外观。旧的 Cython 版本（v1）留在 `develop_v1` 分支，按 `MIGRATION_V2.md` 的说法，v2 切换后约三个月内只回移关键安全补丁，不再做功能或对齐工作。网上很多文章和旧版文档讲的是 v1，读的时候要分清。

## 2. crate 地图

`crates/` 下的 crate 按职责可以粗分成四层，下表先给出每个 crate 负责什么；它们之间准确的依赖关系看表后的依赖图。

| 层 | crate | 负责什么 |
| --- | --- | --- |
| 地基 | `core` | 时间戳 `UnixNanos`、`UUID4`、正确性检查等原语，不依赖任何 nautilus crate |
| | `macros` | 过程宏 |
| | `model` | 交易领域模型：标识符、标的、订单、仓位、行情数据、事件、价格数量等值类型、订单簿 |
| | `common` | 运行时公共服务：`Cache`、`MessageBus`、`Clock` 与计时器、`Component`/`Actor`/`DataActor`、日志、实盘用的 runner 和 sender，以及适配器要实现的 `DataClient`/`ExecutionClient` trait |
| | `network`、`cryptography`、`serialization` | HTTP/WebSocket/Socket 客户端与限流重连；TLS 与加密提供者；Arrow、SBE 等编码 |
| | `persistence`、`infrastructure` | Parquet 数据目录与流式写入；Redis、PostgreSQL 等缓存后端 |
| 引擎 | `data` | `DataEngine`、K 线聚合、订阅管理 |
| | `execution` | `ExecutionEngine`、`OrderEmulator`、撮合引擎 `matching_engine/`、手续费/成交/延迟模型 |
| | `risk` | `RiskEngine` |
| | `portfolio` | `Portfolio`：账户、仓位、盈亏 |
| | `trading` | `Strategy` trait、执行算法 `ExecutionAlgorithm`（含 TWAP），以及示例策略 |
| | `indicators`、`analysis` | 技术指标；绩效统计。`common` 在 `indicators` feature 下也可选依赖 `indicators` |
| 外壳 | `system` | `NautilusKernel`、`Trader`、`ClockFactory` |
| | `backtest` | `BacktestEngine`、`BacktestNode`、`SimulatedExchange` |
| | `live` | `LiveNode`、`AsyncRunner`、`ExecutionManager`（实盘对账） |
| | `event_store` | 事件存储：记录、校验、重放（它依赖 `system`，所以算外壳） |
| 外围 | `adapters/*` | 各交易所和券商的适配器（第 38 章） |
| | `pyo3` | 把各 crate 的 Python 绑定汇总成一个扩展模块 |
| | `testkit`、`plugin`、`cli` | 测试工具（`DataTester`、`ExecTester`）、插件接口、命令行 |

依赖关系如下图。它是用各 crate `Cargo.toml` 的 `[dependencies]` 按默认 feature 画的，并且省略了能经由其他箭头推出的边（比如 `risk` 也直接依赖 `common`，但 `risk → execution → common` 已经表达了这一点）。

![NautilusTrader crate 依赖图：pyo3 和适配器依赖 backtest 或 live；backtest、live、event_store 依赖 system；system 依赖 data、risk、trading；risk 和 trading 依赖 execution 与 portfolio；data、execution、portfolio、persistence、infrastructure 都依赖 common；common、analysis、indicators 依赖 model；model 依赖 core 和 macros](/nautilus-trader/figures/crate-dependencies.svg)

怎么读这张图：从上往下看，越往下越基础。几个值得注意的地方：

- **`system` 是汇合点。** 它直接依赖 `data`、`risk`、`trading`，再经由它们拿到 `execution`、`portfolio` 和 `common`。`Trader` 定义在 `crates/system/src/trader.rs`，要管理策略，所以 `system` 依赖 `trading`。官方架构文档里的依赖图只画了 `system → common`，省掉了这几条边。
- **`live` 经由 `system` 拿到整个内核。** 这条边来自 `live` 默认打开的 `node` feature；关掉它，`live` 只剩对 `execution`、`network` 的依赖（runner、sender 一类的底层部件）。适配器只依赖 `live`，从而间接用到下面的一切。
- **`common` 是所有引擎的公共底座。** `data`、`execution`、`portfolio` 和两个后端 crate 都直接依赖它；它自己只依赖 `model`（`indicators`、`serialization` 是可选依赖，图中没画）。
- **`persistence` 在引擎下面。** `data` 在 `streaming` feature 下可选依赖它（橙色虚线），`system`、`backtest`、`live` 同样在 `streaming` 下可选依赖它。
- **`event_store` 依赖 `system`**，不是反过来，所以它画在外壳一层。

每个 crate 的源码目录、以及按这张图归纳出的七层，见[第 0 章](./nautilus-architecture.md)第 2 节。

读源码时的建议顺序是由下往上：先 `model`（领域对象是所有代码的词汇表），再 `common`（总线、缓存、时钟、组件），然后各个引擎，最后看 `system` 怎样把它们组装起来。

## 3. 内核：NautilusKernel

`crates/system/src/kernel.rs` 里的 `NautilusKernel` 是整个系统的组装点。它的字段（节选）：

```rust
// 示意，节选自 crates/system/src/kernel.rs
pub struct NautilusKernel {
    pub cache: Rc<RefCell<Cache>>,
    pub clock: Rc<RefCell<dyn Clock>>,
    pub portfolio: Rc<RefCell<Portfolio>>,
    pub data_engine: Rc<RefCell<DataEngine>>,
    pub risk_engine: Rc<RefCell<RiskEngine>>,
    pub exec_engine: Rc<RefCell<ExecutionEngine>>,
    pub order_emulator: OrderEmulatorAdapter,
    pub trader: Rc<RefCell<Trader>>,
    // 还有日志、配置、instance_id、event_store 等
}
```

注意**消息总线不是它的字段**。构造时创建一个 `MessageBus`，然后用 `set_message_bus` 放进线程局部存储，之后所有组件都通过 `get_message_bus()` 找到它。

构造顺序（`new_with_dependencies`）也说明了各部分的依赖：

1. 初始化日志；
2. `ClockFactory::for_environment(env)` 选时钟：回测用 `VirtualClock`，实盘和沙盒用 `LiveClock`；按配置创建事件存储；
3. 创建 `Cache`；
4. 创建 `MessageBus` 并放进线程局部存储；
5. 依次创建 `Portfolio`、`RiskEngine`、`ExecutionEngine`、`OrderEmulator`、`DataEngine`；
6. 各引擎调用自己的 `register_msgbus_handlers`，把处理函数注册到总线的端点上；
7. 创建 `Trader`，它负责管理所有策略和 actor。

启动分两步：`start()` 先恢复事件存储、启动各引擎（引擎再启动各自的客户端）、初始化 `Trader`；`start_trader()` 要等客户端都连上、标的都进了缓存之后才调用，它先启动订单仿真器，再启动所有策略。

回测和实盘是包在内核外面的两层外壳：

- `LiveNode`（`crates/live/src/node/mod.rs`）：持有内核、`AsyncRunner`（负责把后台 channel 的消息搬进核心线程）、`ExecutionManager`（实盘对账）和执行客户端，用 `LiveNode::builder(trader_id, env)` 构建；
- `BacktestEngine`（`crates/backtest/src/engine.rs`）：持有内核、按交易所组织的 `SimulatedExchange`、回测用的执行客户端和数据迭代器。

## 4. 消息总线

组件之间不直接调用，而是通过消息总线通信。总线在 `crates/common/src/msgbus/`，有三个特点。

**线程局部。** 模块文档的原话是“Each thread gets its own `MessageBus` instance”，实现是一个 `thread_local!` 里的 `Rc<RefCell<MessageBus>>`。这和“核心单线程”是一回事：总线只在核心线程上用，所以不需要锁。

**三种通信方式。**

| 方式 | API（`msgbus/api.rs`） | 用在哪里 |
| --- | --- | --- |
| 点对点 | `register_*_endpoint` 注册，`send_*` 发送 | 命令：比如策略把下单命令发给风控引擎 |
| 发布/订阅 | `subscribe_*(pattern, handler, priority)`，`publish_*(topic, &msg)` | 行情、订单事件、仓位事件的广播 |
| 请求/响应 | `register_response_handler`、`send_response`，按关联 ID 配对 | 历史数据请求 |

**两套路由。** 高频的类型（报价、成交、K 线、订单簿、订单事件、仓位事件等）走**类型化**的路由，处理函数直接拿到 `&QuoteTick` 这样的具体类型，不需要动态转换；其他类型和 Python 互操作走 `publish_any`/`subscribe_any`，处理函数拿到 `&dyn Any`。

端点和主题的名字统一定义在 `msgbus/switchboard.rs`，读代码时看到字符串就能对上号：

| 类别 | 例子 |
| --- | --- |
| 端点 | `DataEngine.execute`、`DataEngine.process_data`、`RiskEngine.queue_execute`、`RiskEngine.execute`、`ExecEngine.queue_execute`、`ExecEngine.execute`、`ExecEngine.process`、`OrderEmulator.execute`、`Portfolio.update_order` |
| 主题 | `data.quotes.{venue}.{symbol}`、`data.trades.{venue}.{symbol}`、`data.bars.{bar_type}`、`data.book.deltas.{venue}.{symbol}`、`events.order.{strategy_id}`、`events.position.{strategy_id}`、`events.risk` |

订阅可以用模式匹配，比如风控引擎订阅 `events.order.*`，收到所有策略的订单事件。

## 5. 两条主线

### 5.1 一条报价：从适配器到策略

1. 适配器的 `DataClient` 收到交易所的消息，解析成 `QuoteTick`，包成 `DataEvent::Data(Data::Quote(q))`，发进一个 Tokio 的无界 channel。这一步在后台线程。
2. 核心线程上，`AsyncRunner::handle_data_event`（`crates/live/src/runner.rs`）把它发到端点 `DataEngine.process_data`。
3. `DataEngine` 先把报价写进 `Cache`，再发布到主题 `data.quotes.<VENUE>.<SYMBOL>`。
4. 订阅了这个主题的 `DataActor` 或 `Strategy` 的 `on_quote(&QuoteTick)` 被调用。

回测时没有 channel：`BacktestEngine` 从数据迭代器取出下一条数据，先交给模拟交易所撮合，再直接调用 `DataEngine` 处理。从第 3 步开始，两边完全一样。

### 5.2 一笔订单：从策略到交易所再回来

```text
Strategy.submit_order
  ├─ 写 Cache，发布 OrderInitialized 到 events.order.{strategy_id}
  ├─ 设置了仿真触发   → OrderEmulator.execute（价格到了再释放）
  ├─ 指定了执行算法   → {exec_algorithm_id}.execute（如 TWAP 拆单）
  └─ 其他             → RiskEngine.queue_execute
                          → RiskEngine.execute：价格/数量/名义金额检查、限流、交易状态（Halted/Reducing）
                             失败 → OrderDenied
                          → ExecEngine.queue_execute → ExecutionEngine.execute
                          → ExecutionClient.submit_order（适配器，发给交易所）

交易所回报（推送或查询）
  → 适配器发出 ExecutionEvent → channel → AsyncRunner → ExecEngine.process
  → ExecutionEngine：更新 Cache 里的订单；成交时开仓、加仓或平仓
  → 发布到 events.order.{strategy_id}、events.position.{strategy_id}，通知 Portfolio.update_order
  → Strategy.on_order_accepted / on_order_filled / on_position_opened …
```

几处细节值得留意：

- 路由的核心函数是 `crates/trading/src/strategy/mod.rs` 里的 `submit_order_native`。
- `queue_execute` 是为了**防止重入**：在策略的回调里下单，命令先排到下一轮事件循环，而不是在当前调用栈里一路执行到底。
- 适配器只负责“发命令、报事件”，订单和仓位的状态由 `ExecutionEngine` 维护。这就是第 38 章说“适配器不要直接写缓存”的原因。

## 6. 组件、Actor 与策略

**`Component`**（`crates/common/src/component.rs`）是有生命周期的东西的统一接口：`initialize`、`start`、`stop`、`resume`、`degrade`、`fault`、`reset`、`dispose`，以及对应的 `on_*` 钩子。稳定状态有 PRE_INITIALIZED、READY、RUNNING、STOPPED、DEGRADED、FAULTED、DISPOSED，中间还有 STARTING、STOPPING 等过渡状态。

**`DataActor`**（`crates/common/src/actor/data_actor.rs`）是“能订阅数据、收回调”的组件，用户层的回调有 `on_start`、`on_quote`、`on_trade`、`on_bar`、`on_book_deltas`、`on_instrument`、`on_time_event` 等。

**`Strategy`**（`crates/trading/src/strategy/mod.rs`）在 `DataActor` 之上加了交易能力：`submit_order`、`modify_order`、`cancel_order`、`close_position` 等方法，以及 `on_order_*`、`on_position_*` 回调。

今天用 Rust 写策略的方式，可以看 `crates/trading/src/examples/strategies/ema_cross/strategy.rs`：定义一个持有 `StrategyCore` 的结构体，写一行 `nautilus_strategy!(EmaCross);`，在 `impl DataActor for EmaCross` 里实现 `on_start`（订阅报价）和 `on_quote`（更新均线、下单）。能直接跑的入口有两个：`crates/backtest/examples/engine_ema_cross.rs`（回测），以及各适配器下的 `examples/node_*_tester.rs`（实盘）。

## 7. 回测、沙盒、实盘：三种模式哪些一样、哪些不一样

`Environment` 枚举（`crates/common/src/enums.rs`）有三个值：`Backtest`、`Sandbox`、`Live`。沙盒介于另外两者之间：**行情是实时的，成交是模拟的**，也就是常说的纸面交易（paper trading）。

| | 回测 `Backtest` | 沙盒 `Sandbox` | 实盘 `Live` |
| --- | --- | --- | --- |
| 内核、引擎、缓存、总线、策略代码 | 同一套 | 同一套 | 同一套 |
| 节点外壳 | `BacktestEngine` / `BacktestNode` | `LiveNode`（`LiveNode::builder(trader_id, Environment::Sandbox)`） | `LiveNode`（`Environment::Live`） |
| 时钟 | `VirtualClock`（`crates/common/src/clock/virtual.rs`），按数据的时间往前推 | `LiveClock`（`crates/common/src/live/clock.rs`），读系统时间 | `LiveClock` |
| 行情来源 | 历史数据，由数据迭代器按时间回放 | 真实的数据客户端（适配器） | 真实的数据客户端 |
| 成交由谁决定 | `SimulatedExchange`（`crates/backtest/src/exchange.rs`），每个标的一个 `OrderMatchingEngine` | `SandboxExecutionClient`（`crates/adapters/sandbox`），同样每个标的一个 `OrderMatchingEngine`，拿总线上的实时报价、成交、K 线、订单簿来撮合 | 真实交易所或券商，经适配器的执行客户端 |
| 手续费、成交模型 | 可配置 | 可配置（`SandboxExecutionClientConfig` 里还有起始资金、账户类型、OMS 类型、杠杆、`book_type`） | 交易所说了算 |
| 驱动方式 | 主循环逐条取数据：撮合 → 数据引擎处理 → 排空命令队列 → 结算 → 推进时钟、触发计时器 | `AsyncRunner` 的 7 对 channel（时间事件、系统事件、系统命令、执行事件、交易命令、数据事件、数据命令）在核心线程上用 `tokio::select!` 取消息，系统和执行事件优先于行情 | 同沙盒 |
| 启动 | 直接开始回放 | 和实盘同一套启动流程：连数据客户端、标的写进缓存、连执行客户端、对账、启动策略 | 先连数据客户端、把标的写进缓存，再连执行客户端，然后对账，最后才启动策略 |
| 对账 | 不需要 | 模拟执行客户端从本地缓存生成订单状态报告，成交报告为空 | 和交易所真实状态对账（`ExecutionManager`） |

从表里可以看出两条分界线：**时间从哪里来**把回测和另外两种分开，**成交由谁决定**把实盘和另外两种分开。沙盒和回测共用同一个撮合引擎 `OrderMatchingEngine`（`crates/execution/src/matching_engine/`），和实盘共用同一个 `LiveNode`、同一套数据适配器和时钟。所以一个策略的典型上线路径是：回测验证逻辑 → 沙盒用实时行情检验在线行为（重连、行情延迟、计时器）而不冒资金风险 → 实盘只把执行客户端从 `SandboxExecutionClient` 换成真实券商的执行客户端。

`LiveNode` 只接受 `Sandbox` 和 `Live`，传 `Backtest` 会在构建时报错（`validate_live_environment`）。另外不要把这里的 `Environment::Sandbox` 和交易所自己的“沙盒环境”混在一起：比如 Coinbase、Architect 适配器的配置里也有 `Sandbox`，那指的是交易所提供的测试网，订单会真的发到交易所的测试系统上，属于实盘模式下连接测试账户。

一个限制：同一个进程里不能同时跑多个 `LiveNode` 或 `BacktestNode`，因为日志、线程局部的总线和注册表、Tokio 运行时都是进程或线程共享的；一个接一个地跑可以。

## 8. 标识符速查

`crates/model/src/identifiers/` 下每个标识符一个文件：

| 标识符 | 含义 |
| --- | --- |
| `TraderId` | 一个交易节点 |
| `StrategyId`、`ActorId`、`ComponentId` | 策略、actor、组件 |
| `ClientId` | 一个数据或执行客户端（适配器实例） |
| `Venue`、`Symbol`、`InstrumentId` | 交易场所、代码；`InstrumentId` 由两者组成，字符串形式是 `Symbol.Venue`，比如 `ETH-USDT-SWAP.OKX` |
| `ClientOrderId` | 平台给订单起的 ID |
| `VenueOrderId` | 交易所给订单起的 ID |
| `TradeId` | 一笔成交 |
| `AccountId`、`PositionId` | 账户、仓位 |
| `ExecAlgorithmId`、`OrderListId` | 执行算法、订单组 |

`ClientOrderId` 和 `VenueOrderId` 是两套 ID，适配器要负责维护它们的对应关系，这是第 38 章富途适配器的工作之一。

::: warning 常见误区
- **把 v1 的文档当成现在的代码。** `develop` 上已经没有 Cython 核心，Python 层是 PyO3 包装；很多网上资料讲的是 v1。
- **以为多线程能让策略跑得更快。** 核心刻意是单线程的，并发只在 I/O 层；策略回调里做重计算会拖住整个节点。
- **在回调里直接改缓存或直接调用引擎。** 组件之间只通过消息总线通信；状态由引擎维护，回调里下单也是先排队（`queue_execute`）。
- **以为回测、沙盒、实盘是三套代码。** 三者共用同一个 `NautilusKernel`，差别只在时钟（回测用虚拟时钟）和成交由谁决定（实盘才交给真实交易所）。
:::

## 检查理解

1. 为什么核心代码里用的是 `Rc<RefCell<…>>` 而不是 `Arc<Mutex<…>>`？这个选择对适配器有什么要求？

   <details><summary>参考答案</summary>

   核心是单线程的：总线、引擎、缓存都只在核心线程上访问，用 `Rc<RefCell<…>>` 没有锁的开销，也不需要 `Send`。代价是这些对象不能跨线程，所以适配器的网络任务跑在后台线程时，只能通过 channel（`get_data_event_sender`、`get_exec_event_sender`）把数据和事件送回核心线程，不能直接拿着缓存或引擎的引用去改。

   </details>

2. 策略在 `on_quote` 回调里调用 `submit_order`，命令为什么不立刻发到交易所，而是先进 `RiskEngine.queue_execute`？

   <details><summary>参考答案</summary>

   为了防止重入：如果在当前调用栈里一路执行下去，风控、执行引擎、适配器可能在策略的回调还没返回时就开始处理，而它们又可能发布事件、再次回调策略。先排队，等这一轮回调结束、下一轮事件循环再处理，调用顺序就是确定的，和回测时的行为也一致。

   </details>

3. 同一个 EMA 交叉策略，从回测切到实盘，需要改哪些代码？

   <details><summary>参考答案</summary>

   策略本身不用改。要换的是外壳：回测用 `BacktestEngine`，加模拟交易所、标的和历史数据；沙盒和实盘都用 `LiveNode::builder`，注册数据和执行客户端的工厂与配置，沙盒的执行客户端是 `SandboxExecutionClient`，实盘换成券商的执行客户端。内核会按环境选 `VirtualClock` 或 `LiveClock`，成交也从模拟撮合换成真实交易所。

   </details>

## 参考资料

- [官方架构文档 docs/concepts/architecture.md](https://github.com/nautechsystems/nautilus_trader/blob/develop/docs/concepts/architecture.md) · [crates/README.md](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/README.md) · [MIGRATION_V2.md](https://github.com/nautechsystems/nautilus_trader/blob/develop/MIGRATION_V2.md)
- 源码：[`crates/system/src/kernel.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/system/src/kernel.rs) · [`crates/common/src/msgbus/`](https://github.com/nautechsystems/nautilus_trader/tree/develop/crates/common/src/msgbus) · [`crates/trading/src/strategy/mod.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/trading/src/strategy/mod.rs) · [`crates/live/src/runner.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/live/src/runner.rs) · [`crates/backtest/src/engine.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/backtest/src/engine.rs)
- [LMAX 架构（Martin Fowler）](https://martinfowler.com/articles/lmax.html)

有了这张地图，接下来的第一部分把交易领域模型（数值与标识符、品种、行情、订单、仓位、账户、事件）逐个讲清楚，从最基础的值开始：[第 2 章：数值类型、标识符与时间戳](./value-types.md)。想先看怎样写策略，可以跳到[第 9 章：Rust 策略的框架与运行机制](./rust-strategy.md)；想先看怎样接入一个新券商，可以跳到[第 38 章：增加一个券商：以富途为例](./futu-adapter.md)。
