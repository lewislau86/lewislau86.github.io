---
title: "第 0 章：NautilusTrader 架构"
description: NautilusTrader 的全景图：一个节点由哪几层组成，Rust 的 24 个 crate 和 Python 包各自对应哪些源码目录，Rust 实现里的核心数据结构长什么样，以及这些结构投影到 Python 之后的语义。
---

# 第 0 章：NautilusTrader 架构

[全书目录](./index.md) · [下一章](./architecture.md)

::: tip 本章学习目标
看完这一章，你应该能：画出一个节点的分层图，说清每一层在哪个目录里；拿到 `crates/` 下任意一个 crate 名，说出它在哪一层、负责什么、该先读哪几个文件；说清 `python/nautilus_trader/` 里哪些是 Rust 的转出口、哪些是纯 Python 代码；认出 `Price`、`QuoteTick`、`OrderAny`、`OrderBook`、`Cache`、`MessageBus` 这几个核心结构的字段和所有权；知道在 Python 里拿到的订单为什么不会“自己更新”。

**源码版本：** `develop` 分支，提交 `5997d82`（2026-11-17）。文中路径都相对仓库根目录。
:::

官方的 [Architecture](https://nautilustrader.io/docs/latest/concepts/architecture/) 页面讲了组件、线程模型和 crash-only 设计，但它停在“有哪些组件”这一层：没有把组件对到源码目录，也没有讲数据结构。这一章补上这两块，作为后面各章的地图。第 1 章再沿着这张地图，讲一条报价和一笔订单在运行时怎么走。

## 1. 整体架构 {#overview}

### 1.1 先分清版本

NautilusTrader 正在从 v1 换到 v2，两代的架构差别很大，读资料前先确认读的是哪一代：

| | v1（`develop_v1` 分支） | v2（`develop` 分支，本书的对象） |
| --- | --- | --- |
| 核心实现 | Cython（`.pyx`/`.pxd`），部分 Rust | 全部 Rust |
| Python 包 | 仓库根目录 `nautilus_trader/`，核心逻辑就在里面 | `python/nautilus_trader/`，大多数模块只是把 Rust 绑定转出来 |
| PyPI 版本 | 正式版 1.231.0 | 预发布 2.0.0rc9，要用 `pip install --pre` |
| 维护状态 | 切换后约三个月只回移关键安全补丁 | 所有新功能 |

两代都以 `nautilus_trader` 为包名导入，不能装进同一个虚拟环境。官网 `docs/latest` 下的概念文档已经按 v2 写了，但直接 `pip install nautilus_trader` 装到的仍是 v1。另外 Rust crate 有自己的版本号：`Cargo.toml` 里是 `0.69.0`，和 Python 包的 `2.0.0` 不是一回事。

### 1.2 一个节点的四层

![NautilusTrader 节点全貌：Python 应用层在最上，经 PyO3 扩展模块进入 Rust；节点外壳包着 NautilusKernel，内核里的 Trader、MessageBus、各引擎、Cache、Portfolio、Clock 都在核心线程上；适配器客户端、网络和后台写入跑在 Tokio 线程上，只通过 channel 把事件送回核心](/nautilus-trader/figures/system-overview.svg)

怎么读这张图：从上往下是四层，从左往右是两种线程。

- **Python 应用层**（`python/nautilus_trader/`）是控制面：写策略子类、组装配置、启动节点、看报表。包的文档字符串原话是“Python serving as the control plane for strategy logic, configuration, and orchestration”。
- **PyO3 绑定**是语言边界。整个 Rust 实现编成一个扩展模块 `nautilus_trader._libnautilus`，第 3 节细讲。
- **节点**是一个运行单位，一个进程只能同时跑一个。节点外壳有两种：回测用 `BacktestEngine`/`BacktestNode`，实盘和沙盒用 `LiveNode`。两种外壳里装的是同一个 `NautilusKernel`。
- **内核**里的东西全部在**核心线程**上串行执行：消息派发、策略回调、风控检查、执行协调、缓存读写。网络连接、日志、写数据库跑在右边的 Tokio 运行时上，只能通过 channel 把数据和事件送回核心线程。

最下面是外部世界。回测时，成交由节点内部的 `SimulatedExchange` 撮合；实盘时，适配器连到真实的交易所或券商。

### 1.3 内核里的组件和它们的源码位置

| 组件 | 职责 | 定义在 |
| --- | --- | --- |
| `NautilusKernel` | 组装点：创建并持有下面所有组件，按环境选时钟 | `crates/system/src/kernel.rs` |
| `MessageBus` | 组件之间唯一的通信方式：点对点、发布/订阅、请求/响应 | `crates/common/src/msgbus/` |
| `Cache` | 内存里的全部交易状态：标的、行情、订单、仓位、账户 | `crates/common/src/cache/` |
| `DataEngine` | 管订阅，把行情写进缓存再发布给订阅者，聚合 K 线 | `crates/data/src/engine/` |
| `RiskEngine` | 下单前检查：价格、数量、名义金额、余额、限流、交易状态 | `crates/risk/src/engine/` |
| `ExecutionEngine` | 把交易命令路由到执行客户端，处理回报，维护订单和仓位状态 | `crates/execution/src/engine/` |
| `OrderEmulator` | 在本地模拟交易所不支持的条件单，触发后再释放 | `crates/execution/src/order_emulator/` |
| `Portfolio` | 余额、净头寸、保证金、已实现和未实现盈亏 | `crates/portfolio/src/portfolio.rs` |
| `Trader` | 注册和管理 actor、策略、执行算法的生命周期 | `crates/system/src/trader.rs` |
| `Clock` | 当前时间和计时器；回测用 `VirtualClock`，实盘用 `LiveClock` | `crates/common/src/clock/`、`crates/common/src/live/clock.rs` |

实盘外壳还多两个东西：`AsyncRunner`（`crates/live/src/runner.rs`）把后台 channel 里的消息搬到核心线程上派发；`ExecutionManager`（`crates/live/src/execution/manager.rs`）负责启动对账和运行中的持续对账。

### 1.4 三种环境，一套内核

| 环境 | 行情 | 成交 | 时钟 |
| --- | --- | --- | --- |
| Backtest | 历史数据 | `SimulatedExchange` 模拟撮合 | `VirtualClock`，跟着数据时间走 |
| Sandbox | 实时行情 | 模拟成交 | `LiveClock` |
| Live | 实时行情 | 真实交易所或券商（含模拟盘账户） | `LiveClock` |

三种环境共用 `NautilusKernel`。差别只在“时间从哪里来”和“成交由谁决定”，所以同一个策略不改代码就能从回测切到实盘。具体机制见[第 1 章](./architecture.md)第 7 节。

## 2. Rust 部分：crate 与源码目录 {#rust-layout}

### 2.1 工作区

根目录的 `Cargo.toml` 是一个工作区，成员有三类：

- `crates/` 下的 24 个 crate，包名统一是 `nautilus-<目录名>`，比如 `crates/model` 是 `nautilus-model`；
- `crates/adapters/` 下的 21 个适配器：architect_ax、betfair、binance、blockchain、bybit、coinapi、coinbase、databento、deribit、derive、dydx、finfeed、hyperliquid、interactive_brokers、kalshi、kraken、lighter、okx、polymarket、sandbox、tardis；
- `crates/` 本身是一个伞形 crate `nautilus-trader`（入口 `crates/lib.rs`），只重导出 `core`、`common`、`model` 三个；另外还有 `examples/tutorials`。

工作区要求 Rust 1.100、edition 2024。

### 2.2 七层

![Rust crate 分层图：从下到上依次是地基 core、macros、model；工具库 network、cryptography、serialization、indicators、analysis；公共服务 common；后端 persistence、infrastructure；引擎 data、execution、portfolio、risk、trading；外壳 system、backtest、live、event_store；外围 21 个适配器以及 pyo3、testkit、plugin、cli](/nautilus-trader/figures/rust-crates.svg)

怎么读这张图：分层是按各 crate 的 `Cargo.toml` 里 `[dependencies]` 排的，上层只依赖下层。几处容易看错的地方：

- `common` 单独占一层。它依赖 `model`，又被所有引擎依赖；`indicators` 和 `serialization` 是它的可选依赖，所以这两个画在它下面。
- `persistence` 在引擎下面：`data` 引擎可选依赖它（流式读写数据目录）。`infrastructure` 只依赖 `common` 和 `cryptography`。
- `event_store` 在外壳层：它依赖 `system`，不是反过来。
- `testkit` 被 `live` 可选依赖（`examples` feature），平时只在测试和示例里用到。

### 2.3 每个 crate 的目录

下面按层列出每个 crate 的关键目录和文件。只写读源码时值得先打开的，`tests.rs`、`stubs.rs`（测试夹具）一类不列。

**地基**

| crate | 关键目录和文件 | 里面是什么 |
| --- | --- | --- |
| `core` | `nanos.rs`、`uuid.rs`、`time.rs`、`correctness.rs`、`shared.rs`、`string/`、`ffi/`、`python/` | `UnixNanos`、`UUID4`、`AtomicTime`、参数检查、`SharedCell`（`Rc<RefCell<T>>` 的包装）、定长字符串 `StackStr` |
| `macros` | `model.rs`、`serialization.rs` | 过程宏 |
| `model` | `types/` | `Price`、`Quantity`、`Money`、`Currency`、`AccountBalance`，定点数实现在 `fixed.rs` |
| | `identifiers/` | 每种 ID 一个文件：`instrument_id.rs`、`client_order_id.rs`、`venue_order_id.rs`、`trade_id.rs`… |
| | `data/` | 行情：`quote.rs`、`trade.rs`、`bar.rs`、`delta.rs`、`deltas.rs`、`depth.rs`、`prices.rs`（标记价、指数价）、`funding.rs`、`status.rs`、`custom.rs`；`mod.rs` 里是 `Data` 枚举 |
| | `instruments/` | 18 种标的，`any.rs` 是 `InstrumentAny`，`mod.rs` 是 `Instrument` trait |
| | `orderbook/` | `book.rs`、`ladder.rs`、`level.rs`，`own.rs` 是自己挂单的簿 |
| | `orders/` | 9 种订单，`any.rs` 是 `OrderAny`，`mod.rs` 是 `OrderCore` 和状态机，`builder.rs`、`list.rs` |
| | `events/` | `order/`、`position/`、`account/`、`portfolio/`、`funding/` |
| | `position.rs`、`accounts/`、`reports/` | 仓位；现金、保证金、博彩、钱包四种账户；对账用的订单、成交、仓位报告 |
| | `enums.rs`、`currencies.rs`、`venues.rs`、`defi/`、`ffi/`、`python/` | 所有领域枚举；内置币种；DeFi 类型；C ABI；Python 绑定 |

**工具库**

| crate | 关键目录和文件 | 里面是什么 |
| --- | --- | --- |
| `network` | `http/`、`websocket/`、`socket/`、`ratelimiter/`、`backoff.rs`、`retry.rs`、`dst/` | 带重连和限流的网络客户端；`dst/` 是确定性仿真测试用的替身 |
| `cryptography` | `providers.rs`、`tls.rs` | TLS 和加密提供者 |
| `serialization` | `arrow/`、`sbe/` | 每种数据一个 Arrow 编解码（数据目录用），SBE 二进制编码 |
| `indicators` | `average/`、`momentum/`、`volatility/`、`ratio/`、`book/` | 均线、动量、波动率等技术指标 |
| `analysis` | `analyzer.rs`、`statistics/` | 绩效分析；`statistics/` 里每个统计量一个文件（夏普、索提诺、最大回撤…） |

**公共服务**

| crate | 关键目录和文件 | 里面是什么 |
| --- | --- | --- |
| `common` | `msgbus/` | `MessageBus`（`core.rs`）、模式匹配、类型化路由（`typed_router.rs`、`typed_endpoints.rs`）、主题和端点名（`switchboard.rs`） |
| | `cache/` | `Cache`（`mod.rs`）、索引（`index.rs`）、用户读接口（`api.rs`）、只读视图（`view.rs`）、数据库后端 trait（`database.rs`） |
| | `clock/`、`timer.rs`、`live/` | `Clock` trait 和 `VirtualClock`；实盘时钟、`AsyncRunner` 用到的 channel 发送端（`sender.rs`）、Tokio 运行时（`runtime.rs`） |
| | `actor/`、`component.rs` | `Actor`、`DataActor`、`DataActorCore`；`Component` 生命周期状态机 |
| | `clients/`、`factories/`、`providers.rs` | 适配器要实现的 `DataClient`、`ExecutionClient` trait，客户端工厂，`InstrumentProvider` |
| | `messages/` | 命令和事件：`data/`（订阅、请求、响应）、`execution/`（下单、改单、撤单、查询、报告）、`system/` |
| | `generators/`、`throttler.rs`、`logging/`、`xrate.rs` | 订单 ID 和仓位 ID 生成器、限流器、日志、汇率计算 |

**后端与引擎**

| crate | 关键目录和文件 | 里面是什么 |
| --- | --- | --- |
| `persistence` | `catalog/`、`backend/parquet/`、`writer/` | Parquet 数据目录（DataFusion 查询）、流式写入 |
| `infrastructure` | `redis/`、`sql/` | `Cache` 和 `MessageBus` 的 Redis 后端，PostgreSQL 缓存后端 |
| `data` | `engine/`、`aggregation.rs`、`subscription.rs`、`client.rs`、`option_chains/`、`replay/` | `DataEngine`（处理函数在 `handlers.rs`，订阅在 `commands.rs`，请求在 `requests.rs`）、K 线聚合、期权链 |
| `execution` | `engine/`、`client/`、`order_emulator/`、`order_manager/`、`matching_engine/`、`models/`、`reconciliation/`、`trailing.rs` | `ExecutionEngine`（仓位处理在 `engine/position.rs`）；回测撮合 `OrderMatchingEngine`；手续费、成交、延迟模型；对账；跟踪止损计算 |
| `portfolio` | `portfolio.rs`、`manager.rs` | `Portfolio` 和账户管理 |
| `risk` | `engine/`、`sizing.rs` | `RiskEngine`，仓位规模计算 |
| `trading` | `strategy/`、`algorithm/`、`controller.rs`、`sessions.rs`、`examples/strategies/` | `Strategy` trait 和 `StrategyCore`；执行算法（含 `twap.rs`）；动态管理组件的 `Controller`；示例策略 |

**外壳**

| crate | 关键目录和文件 | 里面是什么 |
| --- | --- | --- |
| `system` | `kernel.rs`、`trader.rs`、`builder.rs`、`clock_factory.rs`、`controller.rs` | `NautilusKernel`、`Trader`、按环境选时钟 |
| `backtest` | `engine.rs`、`node.rs`、`exchange.rs`、`data_iterator.rs`、`execution_client.rs`、`modules/` | `BacktestEngine`、`BacktestNode`、`SimulatedExchange`、按时间归并多路数据的迭代器；外汇隔夜利息和 CFD 掉期模块 |
| `live` | `node/`、`runner.rs`、`execution/`、`book/`、`dispatch.rs` | `LiveNode` 和 `LiveNodeBuilder`；`AsyncRunner`；`ExecutionManager` 与对账（`execution/reconciliation.rs`）；订单簿快照恢复 |
| `event_store` | `backend/`（内存、redb）、`writer/`、`reader/`、`replay.rs`、`markers/`、`verifier/` | 事件存储：记录、校验、重放 |

**外围**

| crate | 里面是什么 |
| --- | --- |
| `adapters/<venue>` | 一个交易所或数据源一个 crate，下面单独讲 |
| `pyo3` | 只有一个 `src/lib.rs`：把各 crate 的 Python 子模块汇总成 `_libnautilus` |
| `testkit` | `testers/` 下的 `DataTester`、`ExecTester`（验收适配器用），测试数据工具 |
| `plugin`、`cli` | 原生插件的宿主接口；`nautilus` 命令行（数据库初始化、区块链数据同步） |

### 2.4 每个 crate 都有的两个目录

很多 crate 里都有 `src/python/`，`core` 和 `model` 里还有 `src/ffi/`：

- `src/python/` 是 PyO3 绑定，只在打开 `python` feature 时编译。18 个非适配器 crate 有它：analysis、backtest、common、core、data、execution、indicators、infrastructure、live、model、network、persistence、portfolio、risk、serialization、system、testkit、trading。
- `src/ffi/` 是 C ABI，只在 `ffi` feature 下编译，给需要按 C 布局直接共享结构体的调用方用。

读核心逻辑时可以先跳过这两个目录，它们只是包装；第 3 节讲 Python 时再回来看 `src/python/`。

几个影响数据结构的 feature 值得记住：

| feature | 打开后 |
| --- | --- |
| `python` | 编译 PyO3 绑定，类型加上 `#[pyclass]` |
| `high-precision` | 定点数从 64 位换成 128 位，小数位从 9 位变成 16 位（见第 4.1 节） |
| `defi` | 加入链上类型，并隐含打开 `high-precision` |
| `streaming` | 数据、系统、实盘、回测 crate 接入数据目录的流式读写 |
| `ffi` | 只在 `core`、`model` 上，生成 C ABI |

### 2.5 一个适配器 crate 的目录

官方开发指南给了一个推荐结构（`docs/developer_guide/adapters.md`，“Structure of an adapter”），只有 `Cargo.toml` 和 `src/lib.rs` 是必须的，其他按需要加：

```text
crates/adapters/<venue>/src/
├── common/       # 凭证、URL、枚举、符号映射、共用的解析函数
├── http/         # REST：client.rs、models.rs、parse.rs、query.rs、error.rs
├── websocket/    # 流：client.rs、handler.rs、messages.rs、parse.rs
├── config.rs     # 数据客户端和执行客户端的配置
├── data.rs       # 实现 DataClient
├── execution.rs  # 实现 ExecutionClient
├── factories.rs  # 实现客户端工厂，供 LiveNode 构建
├── python/       # PyO3 绑定
└── lib.rs
```

真实的适配器会按协议调整。OKX 是标准的 REST 加 WebSocket，所以有 `http/`、`websocket/`，另外多了一个 `book/`；Interactive Brokers 封装的是 TWS API，没有 `http/` 和 `websocket/`，取而代之的是 `gateway/`、`historical/`、`providers/`。第 2 章写富途适配器时，会参照后者。

### 2.6 读 Rust 源码的顺序

由下往上：先 `model`（它定义了整个系统的词汇），再 `common` 的 `msgbus/`、`cache/`、`actor/`，然后 `data`、`execution` 的 `engine/`，最后看 `system/src/kernel.rs` 怎样把它们组装起来，以及 `live/src/runner.rs` 和 `backtest/src/engine.rs` 怎样驱动内核。可运行的入口有 `crates/backtest/examples/`（回测）和各适配器下的 `examples/`（实盘）。

## 3. Python 部分：包结构与源码目录 {#python-layout}

### 3.1 `python/` 目录

v2 的 Python 包不在仓库根目录，而在 `python/` 下：

```text
python/
├── pyproject.toml          # maturin 构建配置，指向 ../crates/pyo3/Cargo.toml
├── generate_stubs.py       # 从 Rust 绑定生成 .pyi 类型存根
├── generate_docstrings.py  # 把 Rust 的 /// 文档注释复制给 PyO3 包装
├── tests/                  # pytest：unit/、acceptance/
└── nautilus_trader/        # 发布出去的包
```

`pyproject.toml` 里的 `[tool.maturin]` 决定了这个包怎么构建：`manifest-path = "../crates/pyo3/Cargo.toml"`、`module-name = "nautilus_trader._libnautilus"`，并打开 `extension-module`、`arrow`、`high-precision`、`mimalloc`、`redis`、`postgres`、`defi` 等 feature。要求 Python 3.13 到 3.15。

### 3.2 三层：Python 外观、扩展模块、Rust crate

Python 包里的模块几乎都只有三行实质代码：

```python
# 示意，python/nautilus_trader/trading/__init__.py
from nautilus_trader._fixup import fixup_module_names
from nautilus_trader._libnautilus.trading import *
fixup_module_names(globals(), __name__)
```

`_libnautilus` 是编译出来的扩展模块，它由 `crates/pyo3/src/lib.rs` 里的 `#[pymodule] fn _libnautilus` 组装：对每个 crate 调用 `wrap_pymodule!(nautilus_<crate>::python::<crate>)` 挂上一个子模块，同时把它登记到 `sys.modules["nautilus_trader._libnautilus.<crate>"]`，这样 `from nautilus_trader._libnautilus.trading import *` 才能工作。适配器的子模块在 `adapters` feature 下同样挂上去。

`fixup_module_names` 的作用是把这些类的 `__module__` 从内部路径 `nautilus_trader._libnautilus.trading` 改成公开路径 `nautilus_trader.trading`。不改的话 `pickle` 会按内部路径去导入，失败。

所以一个 Python 名字可以一路追到 Rust 源码：

| Python 模块 | 来自扩展子模块 | Rust 源码 | 纯 Python 代码 |
| --- | --- | --- | --- |
| `nautilus_trader.core` | `_libnautilus.core` | `crates/core/src/python/` | `core/datetime.py`：纳秒与 `datetime`、`pd.Timestamp` 互转 |
| `nautilus_trader.model` | `_libnautilus.model` | `crates/model/src/python/` | `model/custom.py`：`@customdataclass` 装饰器 |
| `nautilus_trader.common` | `_libnautilus.common` | `crates/common/src/python/` | — |
| `nautilus_trader.data` | `_libnautilus.data` | `crates/data/src/python/` | — |
| `nautilus_trader.execution` | `_libnautilus.execution` | `crates/execution/src/python/` | — |
| `nautilus_trader.risk`、`.portfolio` | 同名子模块 | 对应 crate 的 `src/python/` | — |
| `nautilus_trader.trading` | `_libnautilus.trading` | `crates/trading/src/python/`，外加 `crates/system` 的 `Controller` | — |
| `nautilus_trader.backtest` | `_libnautilus.backtest` | `crates/backtest/src/python/` | — |
| `nautilus_trader.live` | `_libnautilus.live` | `crates/live/src/python/` | `clients.py`、`providers.py`、`config.py`、`_coroutine.py`：Python 写的适配器基类 |
| `nautilus_trader.persistence` | `_libnautilus.persistence` | `crates/persistence/src/python/` | `loaders.py`（CSV / Parquet 读取器）、`catalog_to_df.py`（目录查询转 Arrow / pandas） |
| `nautilus_trader.analysis` | `_libnautilus.analysis` | `crates/analysis/src/python/` | `reporter.py`、`tearsheet.py`（3120 行，Plotly 报表）、`statistic.py`、`themes.py`、`config.py` |
| `nautilus_trader.indicators`、`.network`、`.serialization`、`.infrastructure` | 同名子模块 | 对应 crate 的 `src/python/` | — |
| `nautilus_trader.testkit` | `_libnautilus.testkit` | `crates/testkit/src/python/` | `providers.py`：测试用的标的和数据 |
| `nautilus_trader.config` | 没有对应子模块 | — | 从其他模块收集配置类，方便一处导入 |
| `nautilus_trader.adapters.<venue>` | `_libnautilus.<venue>` | `crates/adapters/<venue>/src/python/` | 大多只有 `__init__.py`；`binance/instruments.py` 是少数例外 |

两个例外要留意：`config` 不对应任何 Rust 模块，只是一个汇总入口；`system` crate 没有单独的 Python 子模块，它的 `Controller` 被挂进了 `trading`，因为 `system` 依赖 `trading`，`trading` 自己没法注册它。

整个 `nautilus_trader/` 下有 57 个 `.py` 和 42 个 `.pyi`，`.py` 里大部分是上面这种三行的 `__init__.py`。真正有分量的纯 Python 代码只集中在分析报表、数据加载和 Python 适配器基类这几处。

### 3.3 类型存根是公开接口

`.pyi` 不是手写的。各 crate 在类型上加 `#[pyo3_stub_gen::derive::gen_stub_pyclass(module = "nautilus_trader.model")]` 一类的标注，`make py-stubs` 运行 `generate_stubs.py` 生成存根，`generate_docstrings.py` 再把 Rust 的文档注释复制过去。官方文档（`docs/concepts/python.md`）的约定是：**存根里有的才是受支持的 API**，运行时能访问到、存根里没有的属性不算公开接口。所以查 Python API，最快的办法是打开对应模块的 `__init__.pyi`，`model/__init__.pyi` 有 8749 行、188 个类。

### 3.4 Python 代码在哪里运行

v2 里 Python 代码只出现在三个位置：

1. **用户组件。** 继承 PyO3 基类 `DataActor`、`Strategy`、`ExecutionAlgorithm`、`Controller`，覆盖 `on_start`、`on_quote`、`on_bar`、`on_order_filled` 等回调。这些回调在核心线程上同步执行，回调里做阻塞 I/O 或重计算会拖住整个节点。
2. **编排与分析。** 构造配置、`BacktestNode`/`BacktestEngine`/`LiveNode`，跑完后读缓存、组合和报表。`LiveNode.run()` 阻塞当前线程；`LiveNode.run_async()` 让节点跑在宿主的 asyncio 事件循环上（比如 ASGI 应用里）。
3. **Python 写的适配器。** 官方适配器全部是 Rust 实现、Python 只拿到配置和工厂；自己用 Python 写适配器时，继承 `nautilus_trader/live/clients.py` 里的 `DataClient`、`ExecutionClient`。它们跑在节点绑定的 asyncio 循环上，拿到的是只读的缓存视图，产出的数据、事件、报告经队列交给 Rust。

除此之外，路由、引擎状态、订单管理、记账、交易所连接都在 Rust 里。

### 3.5 和 v1 目录的对照

v1 的 `nautilus_trader/` 在仓库根目录，按 `model/`、`common/`、`execution/` 这样的子包组织，每个子包里是 `.pyx`、`.pxd` 和 `.py`，核心逻辑就写在里面。v2 把逻辑全部移进 `crates/`，Python 包变成了一层很薄的外观。所以 v1 的源码阅读笔记里“去 `nautilus_trader/execution/engine.pyx` 看”这类指引，在 v2 里要换成“去 `crates/execution/src/engine/` 看”。

## 4. Rust 实现中的核心数据结构 {#rust-structures}

这一节从小到大：值 → 标识 → 行情 → 订单簿 → 标的 → 订单 → 仓位与账户 → 消息 → 两个状态容器（`Cache`、`MessageBus`）→ 组件。只讲结构和所有权；它们的行为，比如定点数为什么不用浮点、订单状态机怎样迁移，见[第 3 章](./core-topics.md)。

### 4.1 值类型：定点数

```rust
// 示意，节选自 crates/model/src/types/{price,quantity,money,currency}.rs
#[repr(C)]
#[derive(Clone, Copy)]
pub struct Price    { pub(crate) raw: PriceRaw,    pub precision: u8 }
pub struct Quantity { pub(crate) raw: QuantityRaw, pub precision: u8 }
pub struct Money    { pub(crate) raw: MoneyRaw,    pub currency: Currency }
pub struct Currency { pub code: Ustr, pub precision: u8, pub iso4217: u16,
                      pub name: Ustr, pub currency_type: CurrencyType }
```

`PriceRaw` 在标准模式下是 `i64`、高精度模式下是 `i128`；`QuantityRaw` 对应 `u64`/`u128`（数量不能为负）。`raw` 等于数值乘以 `FIXED_SCALAR`：标准模式 10⁹，高精度模式 10¹⁶。`raw` 的两个极值被留作哨兵：`PRICE_UNDEF = PriceRaw::MAX` 表示“没有价格”，`PRICE_ERROR = PriceRaw::MIN` 表示出错。

一个容易忽略的事实：**Rust crate 默认是 64 位模式，Python wheel 是 128 位模式**（`pyproject.toml` 的 maturin feature 里有 `high-precision`）。所以同一个价格，在 Python 里 `Price.raw` 的放大倍数是 10¹⁶，在默认编译的 Rust 程序里是 10⁹，两边的 Parquet 数据也不能混用。

这些类型都是 `Copy`，传值和传引用一样便宜。需要更高精度的累计量用 `rust_decimal::Decimal`：订单的 `avg_px`、仓位的 `signed_qty`、`avg_px_open` 都是 `Decimal`。

### 4.2 时间与标识符

```rust
// 示意，crates/core/src/{nanos,uuid}.rs 与 crates/model/src/identifiers/
pub struct UnixNanos(u64);                         // 纳秒时间戳
pub struct UUID4 { value: [u8; 37] }               // 定长，带 C 字符串结尾
pub struct Venue(Ustr);
pub struct Symbol(Ustr);
pub struct InstrumentId { pub symbol: Symbol, pub venue: Venue }   // "AAPL.XNAS"
pub struct ClientOrderId(Ustr);
pub struct TradeId(StackStr);                      // 最多 36 字符，存在栈上
```

大部分标识符是 `Ustr` 的新类型。`Ustr` 是一个“驻留字符串”：全进程共享一张字符串表，同一个字符串只存一份，`Ustr` 本身只是一个指针大小、带预先算好哈希的 `Copy` 句柄。好处是标识符可以像整数一样复制、比较、做哈希键。代价写在开发指南的“Identifier storage”一节：字符串表里的条目**永不释放**。`Venue`、`InstrumentId` 这类取值有限的没有问题，但 `ClientOrderId`、`VenueOrderId`、`PositionId`、`OrderListId` 也是 `Ustr`，每笔订单都会在表里留下几条，一个长期运行的节点的内存会随订单数缓慢增长。`TradeId` 已经换成了栈上的 `StackStr`，就是为了避开这个问题。

### 4.3 行情数据

```rust
// 示意，节选自 crates/model/src/data/
pub struct QuoteTick {
    pub instrument_id: InstrumentId,
    pub bid_price: Price,  pub ask_price: Price,
    pub bid_size: Quantity, pub ask_size: Quantity,
    pub ts_event: UnixNanos, pub ts_init: UnixNanos,
}
pub struct TradeTick {
    pub instrument_id: InstrumentId, pub price: Price, pub size: Quantity,
    pub aggressor_side: AggressorSide, pub trade_id: TradeId,
    pub ts_event: UnixNanos, pub ts_init: UnixNanos,
}
pub struct Bar {
    pub bar_type: BarType,
    pub open: Price, pub high: Price, pub low: Price, pub close: Price,
    pub volume: Quantity, pub ts_event: UnixNanos, pub ts_init: UnixNanos,
}
```

三个共同点：全是 `Copy`；全部带 `ts_event`（交易所时间）和 `ts_init`（本地创建时间）两个时间戳；字段全是前面讲过的定长值类型，所以一个 `QuoteTick` 是一块不含堆指针的连续内存。

`BarType` 是一个枚举：`Standard { instrument_id, spec, aggregation_source }` 或 `Composite { … }`。`spec` 是 `BarSpecification { step: NonZeroUsize, aggregation: BarAggregation, price_type: PriceType }`，比如“1 分钟、按时间聚合、用最新价”。

订单簿的增量更新拆成三种粒度：

```rust
// 示意，节选自 crates/model/src/data/{order,delta,deltas,depth}.rs
pub type OrderId = u64;
pub struct BookOrder { pub side: Option<OrderSide>, pub price: Price, pub size: Quantity, pub order_id: OrderId }
pub struct OrderBookDelta  { pub instrument_id: InstrumentId, pub action: BookAction, pub order: BookOrder,
                             pub flags: u8, pub sequence: u64, pub ts_event: UnixNanos, pub ts_init: UnixNanos }
pub struct OrderBookDeltas { pub instrument_id: InstrumentId, pub deltas: Vec<OrderBookDelta>, /* flags、sequence、两个时间戳 */ }
pub struct OrderBookDepth  { pub instrument_id: InstrumentId,
                             pub bids: SmallVec<[BookOrder; 10]>, pub asks: SmallVec<[BookOrder; 10]>,
                             pub bid_counts: SmallVec<[u32; 10]>, pub ask_counts: SmallVec<[u32; 10]>, /* … */ }
```

`OrderBookDelta` 是一条增、改、删或清空，`OrderBookDeltas` 是一批，`flags` 里的 `F_LAST`、`F_SNAPSHOT` 等位标出一批的结尾和快照。`OrderBookDepth` 是前 10 档快照，用 `SmallVec` 让 10 档以内不上堆。

所有行情最后都装进一个枚举在系统里流动：

```rust
// 示意，crates/model/src/data/mod.rs
pub enum Data {
    Custom(CustomData),
    Instrument(Box<InstrumentAny>),
    BookDelta(OrderBookDelta),
    BookDeltas(Box<OrderBookDeltas>),
    BookDepth(Box<OrderBookDepth>),
    Quote(QuoteTick), Trade(TradeTick), Bar(Bar),
    MarkPrice(MarkPriceUpdate), IndexPrice(IndexPriceUpdate), FundingRate(FundingRateUpdate),
    OptionGreeks(OptionGreeks), InstrumentStatus(InstrumentStatus), InstrumentClose(InstrumentClose),
    // defi feature 下还有 Defi(Box<DefiData>)
}
```

注意哪些变体被 `Box` 了：标的、批量增量、深度快照。枚举的大小等于最大变体的大小，把大的变体放到堆上，`Data` 本身就能保持和 `QuoteTick` 差不多大，在 channel 里搬运最常见的报价和成交时不浪费。

### 4.4 订单簿

![OrderBook 数据结构：OrderBook 下有 bids 和 asks 两条 BookLadder，每条是 BTreeMap<BookPrice, BookLevel>，买方向排序反转，两边第一个元素都是最优价；每个 BookLevel 用 IndexMap 按插入顺序保存该价位的 BookOrder](/nautilus-trader/figures/order-book.svg)

怎么读这张图：三层容器各管一件事。

```rust
// 示意，节选自 crates/model/src/orderbook/{book,ladder,level}.rs
pub struct OrderBook {
    pub instrument_id: InstrumentId, pub book_type: BookType,   // L1_MBP / L2_MBP / L3_MBO
    pub sequence: u64, pub ts_last: UnixNanos, pub update_count: u64,
    pub(crate) bids: BookLadder, pub(crate) asks: BookLadder,
}
pub(crate) struct BookLadder {
    pub side: OrderSide, pub book_type: BookType,
    pub levels: BTreeMap<BookPrice, BookLevel>,   // 有序：第一个就是最优价
    pub cache: HashMap<u64, BookPrice>,           // 订单号 → 所在价位
    /* … */
}
pub struct BookPrice { pub value: Price, pub side: OrderSide }
pub struct BookLevel { pub price: BookPrice, pub(crate) orders: IndexMap<OrderId, BookOrder> }
```

- `BTreeMap` 让价位始终有序。`BookPrice` 实现 `Ord` 时，买方向把比较反过来（`other.value.cmp(&self.value)`），所以买卖两边都可以用“第一个元素”拿最优价，不用分开写。
- `cache` 是订单号到价位的反向索引。修改或删除一笔订单时，先查它在哪个价位，再去那一档里删，不用遍历阶梯。
- `IndexMap` 保留插入顺序，对 L3（逐笔）簿来说就是同价位的排队顺序。L2 簿的订单号是由价格算出的，每档只有一条聚合后的 `BookOrder`。

`OwnOrderBook`（`orderbook/own.rs`）是同样形状的另一本簿，只放自己挂出去的单，用来从市场深度里扣掉自己的量。

### 4.5 标的

```rust
// 示意，crates/model/src/instruments/
pub trait Instrument: Any + Send {
    fn id(&self) -> InstrumentId;
    fn price_precision(&self) -> u8;
    fn price_increment(&self) -> Price;
    fn size_increment(&self) -> Quantity;
    fn multiplier(&self) -> Quantity;
    fn make_price(&self, value: f64) -> Price;   // 按标的精度造 Price
    fn make_qty(&self, value: f64, round_down: Option<bool>) -> Quantity;
    // 还有 lot_size、min/max_quantity、margin_init、is_inverse … 共几十个方法
}
pub enum InstrumentAny {
    Betting(BettingInstrument), BinaryOption(BinaryOption), Cfd(Cfd), Commodity(Commodity),
    CryptoFuture(CryptoFuture), CryptoFuturesSpread(CryptoFuturesSpread), CryptoOption(CryptoOption),
    CryptoOptionSpread(CryptoOptionSpread), CryptoPerpetual(CryptoPerpetual), CurrencyPair(CurrencyPair),
    Equity(Equity), FuturesContract(FuturesContract), FuturesSpread(FuturesSpread),
    IndexInstrument(IndexInstrument), OptionContract(OptionContract), OptionSpread(OptionSpread),
    PerpetualContract(PerpetualContract), TokenizedAsset(TokenizedAsset),
}
```

这里能看到整个代码库的一个习惯：**用枚举而不是 trait 对象表示“若干种之一”**。`InstrumentAny`、`OrderAny`、`AccountAny`、`OrderEventAny` 都是这样：每个具体类型是一个普通 struct，再用一个 `…Any` 枚举把它们收拢起来，并为枚举实现同一个 trait（订单用 `enum_dispatch` 宏自动生成分派代码）。这样容器里可以直接存值，`match` 能被编译器检查是否穷尽，也省掉了动态分派。

以股票为例，`Equity` 的字段有 `id`、`raw_symbol`、`isin`、`currency`、`price_precision`、`price_increment`、`lot_size`（每手股数，港股适配器要用到）、`max_quantity`、`min_quantity`、`max_price`、`min_price`、`margin_init`、`margin_maint`、`info` 和两个时间戳。合成标的 `SyntheticInstrument` 不在 `InstrumentAny` 里，`Cache` 单独存它。

### 4.6 订单与订单事件

```rust
// 示意，节选自 crates/model/src/orders/
#[enum_dispatch(Order)]
pub enum OrderAny {
    Limit(LimitOrder), LimitIfTouched(LimitIfTouchedOrder), Market(MarketOrder),
    MarketIfTouched(MarketIfTouchedOrder), MarketToLimit(MarketToLimitOrder),
    StopLimit(StopLimitOrder), StopMarket(StopMarketOrder),
    TrailingStopLimit(TrailingStopLimitOrder), TrailingStopMarket(TrailingStopMarketOrder),
}
pub struct LimitOrder {
    core: OrderCore,                       // 所有订单共有的部分
    pub price: Price, pub expire_time: Option<UnixNanos>, pub is_post_only: bool,
    pub display_qty: Option<Quantity>, pub trigger_instrument_id: Option<InstrumentId>,
}
pub struct OrderCore {
    events: Vec<OrderEventAny>,            // 事件溯源：订单的全部历史
    pub status: OrderStatus, pub previous_status: Option<OrderStatus>,
    pub trader_id: TraderId, pub strategy_id: StrategyId, pub instrument_id: InstrumentId,
    pub client_order_id: ClientOrderId, pub venue_order_id: Option<VenueOrderId>,
    pub position_id: Option<PositionId>, pub account_id: Option<AccountId>,
    pub side: OrderSide, pub order_type: OrderType, pub quantity: Quantity, pub time_in_force: TimeInForce,
    pub filled_qty: Quantity, pub leaves_qty: Quantity, pub overfill_qty: Quantity,
    pub avg_px: Option<Decimal>, pub commissions: IndexMap<Currency, Money>,
    pub venue_order_ids: Vec<VenueOrderId>, pub trade_ids: Vec<TradeId>,
    pub ts_init: UnixNanos, pub ts_submitted: Option<UnixNanos>, pub ts_accepted: Option<UnixNanos>,
    pub ts_closed: Option<UnixNanos>, pub ts_last: UnixNanos,
    // 还有 OCO/OTO 关联、执行算法参数、仿真触发、标签等约 20 个字段
}
```

“具体类型 = `OrderCore` + 自己特有的几个字段”是订单的统一形状：限价单多了价格和过期时间，止损单多了触发价，跟踪止损多了偏移量。`OrderCore` 里最重要的字段是 `events`：订单的当前状态（`status`、`filled_qty`、`avg_px`…）都是把事件一个个 `apply` 上去得到的，`events` 保留了全部历史。`OrderStatus` 有 15 个取值，`OrderEventAny` 有 19 种事件；状态机细节见[第 3 章](./core-topics.md)第 3 节。

最常用的事件是成交：

```rust
// 示意，节选自 crates/model/src/events/order/filled.rs
pub struct OrderFilled {
    pub trader_id: TraderId, pub strategy_id: StrategyId, pub instrument_id: InstrumentId,
    pub client_order_id: ClientOrderId, pub venue_order_id: VenueOrderId, pub account_id: AccountId,
    pub trade_id: TradeId, pub order_side: OrderSide, pub order_type: OrderType,
    pub last_qty: Quantity, pub last_px: Price, pub currency: Currency, pub liquidity_side: LiquiditySide,
    pub event_id: UUID4, pub ts_event: UnixNanos, pub ts_init: UnixNanos, pub reconciliation: bool,
    pub position_id: Option<PositionId>, pub commission: Option<Money>, /* … */
}
```

每个事件都自带完整的上下文（哪个交易员、哪个策略、哪个账户），可以单独存储、单独重放，不需要回头查订单。

### 4.7 仓位与账户

```rust
// 示意，节选自 crates/model/src/position.rs 与 accounts/
pub struct Position {
    pub events: Vec<OrderFilled>,          // 这个仓位经历的所有成交
    pub id: PositionId, pub instrument_id: InstrumentId, pub strategy_id: StrategyId, pub account_id: AccountId,
    pub opening_order_id: ClientOrderId, pub closing_order_id: Option<ClientOrderId>,
    pub entry: OrderSide, pub side: PositionSide,
    pub signed_qty: Decimal, pub quantity: Quantity, pub peak_qty: Quantity,
    pub avg_px_open: Decimal, pub avg_px_close: Option<Decimal>,
    pub realized_pnl: Option<Money>, pub commissions: IndexMap<Currency, Money>,
    pub trade_ids: AHashSet<TradeId>, pub buy_qty: Quantity, pub sell_qty: Quantity,
    pub ts_opened: UnixNanos, pub ts_closed: Option<UnixNanos>, /* … */
}
pub enum AccountAny { Margin(MarginAccount), Cash(CashAccount), Betting(BettingAccount), Wallet(WalletAccount) }
pub struct BaseAccount {
    pub id: AccountId, pub account_type: AccountType, pub base_currency: Option<Currency>,
    pub events: Arc<Vec<AccountState>>,
    pub balances: IndexMap<Currency, AccountBalance>,   // 每个币种 total / locked / free
    pub balances_starting: IndexMap<Currency, Money>, pub commissions: AHashMap<Currency, Money>, /* … */
}
pub struct CashAccount   { pub base: BaseAccount, pub allow_borrowing: bool, /* 按 (标的, 币种) 冻结的金额 */ }
pub struct MarginAccount { pub base: BaseAccount, pub leverages: AHashMap<InstrumentId, Decimal>,
                           pub margins: IndexMap<InstrumentId, MarginBalance>, /* … */ }
```

仓位和订单一样是事件溯源的，只不过它的事件是 `OrderFilled`：`trade_ids` 用集合存，用来拒绝重复成交。账户的历史是一串 `AccountState` 事件，每个事件带全部余额和保证金。现金账户和保证金账户的差别全在 `BaseAccount` 外面那几个字段上。

### 4.8 在 channel 和总线上流动的消息

适配器和引擎之间、组件和组件之间传的是下面几个枚举（`crates/common/src/messages/`）：

| 枚举 | 方向 | 变体 |
| --- | --- | --- |
| `DataCommand` | 策略 → 数据引擎 → 数据客户端 | `Request`、`Subscribe`、`Unsubscribe` |
| `DataEvent` | 数据客户端 → 数据引擎 | `Data(Data)`、`Response`、`RequestFailed`、`ResponseEnvelope` |
| `TradingCommand` | 策略 → 风控 → 执行引擎 → 执行客户端 | `SubmitOrder`、`SubmitOrderList`、`ModifyOrder`、`ModifyOrders`、`CancelOrder`、`CancelOrders`、`CancelAllOrders`、`QueryOrder`、`QueryAccount` |
| `ExecutionEvent` | 执行客户端 → 执行引擎 | `Order(OrderEventAny)`、三种批量事件、`Report`、`Account(AccountState)`、`Data(CustomData)` |

一个细节：`SubmitOrder` 命令里放的不是订单对象，而是订单的第一个事件 `order_init: OrderInitialized`。命令因此是一个不带可变状态的值，可以序列化、跨进程传递。执行引擎收到命令后先按 `client_order_id` 查缓存；查不到（比如命令来自外部总线）时，用 `OrderAny::from_events` 从这个事件重建出订单，再放进缓存。

### 4.9 Cache：状态的唯一存放处

![Cache 内部布局：左边是 Cache 主表，按 ID 存标的、订单簿、行情环形队列、订单、仓位、账户；订单是 SharedCell<OrderAny>，里面是具体订单类型加 OrderCore；右下是 CacheIndex，31 个只存 ID 的映射和集合](/nautilus-trader/figures/cache-layout.svg)

怎么读这张图：左边存“东西”，右下存“关系”。`Cache` 有 35 个字段，归成四组：

- **静态数据：** `currencies`、`instruments: AHashMap<InstrumentId, InstrumentAny>`、`synthetics`。
- **行情：** `books: AHashMap<InstrumentId, OrderBook>`，以及 `quotes`、`trades`、`bars`、`mark_prices` 等，每个标的一个 `BoundedVecDeque`（定长环形队列，默认容量 10,000，可在 `CacheConfig` 里改），满了就丢最旧的。
- **交易状态：** `orders: AHashMap<ClientOrderId, SharedCell<OrderAny>>`、`positions`、`accounts`，三者都包在 `SharedCell` 里。`SharedCell<T>` 是 `core` 里对 `Rc<RefCell<T>>` 的一层包装，能在单线程里共享和就地修改。
- **索引：** `index: CacheIndex`，31 个 `AHashMap`/`AHashSet`，只存 ID。例如 `venue_order_ids: VenueOrderId → ClientOrderId`（收到交易所回报时反查本地订单）、`orders_open`、`orders_inflight`（已发出、未确认）、`strategy_orders`、`instrument_positions`。查“某策略的所有未成交订单”就是两个集合求交，再去主表取对象。

另外 `database: Option<Box<dyn CacheDatabaseAdapter>>` 是可选的持久化后端（`infrastructure` 里的 Redis、PostgreSQL 实现）。

读写规则落在类型上：引擎拿着 `Rc<RefCell<Cache>>` 直接写；用户代码通过 `DataActor::cache()` 拿到的是 `CacheApi`，源码注释写明“Point reads return owned snapshots where possible”，也就是 `cache.order(&id)` 返回一个克隆出来的 `OrderAny`，`cache.quote(&id)` 返回一个复制的 `QuoteTick`；适配器拿到的是只能借读的 `CacheView`。这样用户代码手里不会攥着一个指向缓存内部的借用，也就不会在事件派发时撞上 `RefCell` 的重复借用。

### 4.10 MessageBus：类型化的路由表

```rust
// 示意，节选自 crates/common/src/msgbus/core.rs
pub struct MessageBus {
    pub trader_id: TraderId, pub instance_id: UUID4,
    pub(crate) topics: IndexMap<MStr<Topic>, Vec<Subscription>>,              // 通用发布/订阅
    pub(crate) endpoints: IndexMap<MStr<Endpoint>, ShareableMessageHandler>,  // 通用点对点
    pub(crate) correlation_index: AHashMap<UUID4, TypedHandler<DataResponseEnvelope>>, // 请求/响应
    pub(crate) router_quotes: TopicRouter<QuoteTick>,
    pub(crate) router_trades: TopicRouter<TradeTick>,
    pub(crate) router_bars: TopicRouter<Bar>,
    pub(crate) router_order_events: TopicRouter<OrderEventAny>,
    // … 共约 20 个类型化路由：deltas、depth、book 快照、标记价、资金费率、仓位事件、账户状态 …
    pub(crate) endpoints_trading_commands: IntoEndpointMap<TradingCommand>,
    pub(crate) endpoints_data_commands: IntoEndpointMap<DataCommand>,
    pub(crate) endpoints_data: IntoEndpointMap<Data>,
    // … 以及计数器、外部后端、编码配置
}
pub struct TopicRouter<T> {
    pub(crate) subscriptions: IndexSet<TypedSubscription<T>>,
    topic_cache: IndexMap<MStr<Topic>, SmallVec<[usize; 64]>>,   // 主题 → 匹配到的订阅下标
}
pub struct Subscription { pub handler: ShareableMessageHandler, pub handler_id: Ustr,
                          pub pattern: MStr<Pattern>, pub priority: u32 }
pub struct MStr<T> { value: Ustr, _marker: PhantomData<T> }
```

这个结构里有三个设计决定：

- **每种热路径消息一张专用路由表。** 报价走 `router_quotes`，处理函数的签名就是 `&QuoteTick`，不经过 `dyn Any` 再向下转型。只有冷门类型和 Python 互操作才走通用的 `topics`/`endpoints`。
- **匹配结果缓存起来。** 订阅用的是带通配符的模式（`data.quotes.*`），每次发布都去匹配一遍太贵。`topic_cache` 把“这个具体主题匹配到哪些订阅”记下来，下次直接用；订阅表一变就整体清空（因为 `swap_remove` 会挪动下标）。
- **用类型区分字符串。** `MStr<Topic>`、`MStr<Pattern>`、`MStr<Endpoint>` 底下都是同一个 `Ustr`，只靠一个零大小的标记类型区分，编译器能拦住“把模式当主题发布”这种错误，运行时没有任何开销。

`EndpointMap<T>` 和 `IntoEndpointMap<T>` 的区别是借用还是转移：前者把 `&T` 交给处理函数，后者把 `T` 本身交过去，命令和 `Data` 走后者，省一次复制。

### 4.11 时钟与组件

```rust
// 示意，节选自 crates/common/src/{clock,timer,component}.rs 与 actor/
pub trait Clock {
    fn timestamp_ns(&self) -> UnixNanos;
    fn set_timer_ns(/* name, interval, start, stop, callback, … */) -> anyhow::Result<()>;
    fn set_time_alert_ns(/* name, alert_time, callback, … */) -> anyhow::Result<()>;
    // utc_now、timer_names、cancel_timer …
}
pub struct TimeEvent { pub name: Ustr, pub event_id: UUID4, pub ts_event: UnixNanos, pub ts_init: UnixNanos }
pub struct VirtualClock {
    time: AtomicTime,
    timers: BTreeMap<Ustr, VirtualTimer>,
    pub(super) timer_queue: BinaryHeap<ScheduledTimeEvent>,   // 按到期时间排序
    callbacks: CallbackRegistry,
}
pub trait Component { fn component_id(&self) -> ComponentId; fn state(&self) -> ComponentState;
                      fn transition_state(&mut self, trigger: ComponentTrigger) -> anyhow::Result<()>; /* start/stop/… */ }
pub trait Actor: Any + Debug { fn id(&self) -> Ustr; fn handle(&mut self, msg: &dyn Any); fn as_any(&self) -> &dyn Any; }
pub struct DataActorCore {
    pub actor_id: ActorId, pub config: DataActorConfig,
    clock: Option<Rc<RefCell<dyn Clock>>>,   // 注册时接上
    cache: Option<Rc<RefCell<Cache>>>,       // 注册时接上
    state: ComponentState,
    quote_handlers: AHashMap<MStr<Topic>, Subscription<TypedHandler<QuoteTick>>>,
    // trade_handlers、bar_handlers、deltas_handlers … 每种数据一张订阅表
}
pub struct StrategyCore {
    pub(crate) actor: DataActorCore,
    pub config: StrategyConfig,
    pub(crate) order_manager: Option<OrderManager>,
    pub(crate) order_factory: Option<Rc<RefCell<OrderFactory>>>,
    pub(crate) portfolio: Option<Rc<RefCell<Portfolio>>>,
    pub(crate) gtd_timers: AHashMap<ClientOrderId, Ustr>,   // GTD 订单的到期计时器
    // …
}
```

`Actor` 和 `Component` 是两个独立的 trait：`Actor` 管“按 ID 收消息”，`Component` 管“生命周期状态机”。策略两个都要，`Trader` 只要后者，限流器 `Throttler` 只要前者。`VirtualClock` 的计时器放在一个二叉堆里，回测推进时间时依次弹出到期事件，所以回测里的定时器和数据按同一条时间线严格排序。

`StrategyCore` 包着 `DataActorCore`，`DataActorCore` 在注册时才拿到 `clock` 和 `cache` 的 `Rc`。这就是为什么策略在注册到 `Trader` 之前不能访问缓存和时钟：那两个字段还是 `None`。

### 4.12 谁拥有谁

把上面的结构串起来，所有权大致是：

```text
NautilusKernel
├── cache: Rc<RefCell<Cache>>                  ← 引擎、组合、策略各持一个 Rc
│   ├── orders: ClientOrderId → SharedCell<OrderAny>   ← OrderAny = 具体订单 { OrderCore { events, … } }
│   ├── positions: PositionId → SharedCell<Position>   ← Position { events: Vec<OrderFilled>, … }
│   ├── books: InstrumentId → OrderBook                ← BookLadder × 2 → BookLevel → BookOrder
│   └── index: CacheIndex（只有 ID）
├── data_engine / risk_engine / exec_engine: Rc<RefCell<…>>
├── portfolio: Rc<RefCell<Portfolio>>
└── trader: Rc<RefCell<Trader>>                ← 管理所有 actor 和策略
MessageBus：不在内核里，放在核心线程的 thread_local 中，所有组件用 get_message_bus() 取
```

整个内核是一张 `Rc` 图，没有 `Arc`、没有锁，代价是它只能待在一个线程上；这正是“核心单线程”在类型层面的体现。

## 5. Python 实现中的核心数据结构 {#python-structures}

v2 里没有一套独立的 Python 数据结构。Python 的 `Price`、`QuoteTick`、`LimitOrder` 就是第 4 节那些 Rust struct，在 `python` feature 下多加了一个 `#[pyclass]`。所以“Python 的数据结构”这一节要讲的，是这些 Rust 结构投影到 Python 之后，**行为上**有哪些不同。

### 5.1 三种投影

![Python 对象与 Rust 状态的三种关系：值对象跨边界就复制；Cache、Portfolio、Clock 是句柄，共享内核里唯一的状态；Strategy 是可继承的基类，Rust 通过弱引用回调 Python 子类](/nautilus-trader/figures/python-projection.svg)

怎么读这张图：看中间那一行的“绑定方式”，它决定了上下两行是不是同一份数据。

**① 值对象：跨边界就复制。** 绝大多数模型类型是这样声明的：

```rust
// 示意，crates/model/src/types/price.rs、data/quote.rs、orders/limit.rs
#[cfg_attr(feature = "python", pyo3::pyclass(module = "nautilus_trader.model", frozen, from_py_object))]
pub struct Price { /* … */ }
#[cfg_attr(feature = "python", pyo3::pyclass(module = "nautilus_trader.model", from_py_object))]
pub struct QuoteTick { /* … */ }
#[cfg_attr(feature = "python", pyo3::pyclass(module = "nautilus_trader.model", from_py_object))]
pub struct LimitOrder { /* … */ }
```

`from_py_object` 让 Rust 函数可以直接收这些类型作参数，代价是每次从 Python 传进 Rust 都会**复制**一份；反方向用 `into_py_any` 把一个 Rust 值包成新的 Python 对象，同样是一份新的。`Price` 还多一个 `frozen`：Python 侧不可变。

**② 句柄：共享同一份状态。** `Cache`、`Portfolio`、`Clock`、`OrderFactory` 在 Python 里是这样的包装：

```rust
// 示意，crates/common/src/python/{cache,clock,order_factory}.rs 与 crates/portfolio/src/python/mod.rs
#[pyo3::pyclass(module = "nautilus_trader.common", name = "Cache", unsendable, from_py_object)]
pub struct PyCache(Rc<RefCell<Cache>>);
pub struct PyPortfolio(Rc<RefCell<Portfolio>>);
pub struct PyClock(Rc<RefCell<dyn Clock>>);
pub struct PyOrderFactory(Rc<RefCell<OrderFactory>>);
```

Python 对象里只有一个 `Rc`，指向内核里那唯一一份状态。`unsendable` 让 PyO3 在别的线程访问它时直接报错，因为 `Rc` 不能跨线程。官方文档（`docs/concepts/python.md`）的说法是“Python objects such as `Cache` and `Portfolio` are wrappers over Rust-owned state”。

**③ 可继承的基类：Rust 回调 Python。** `Strategy`、`DataActor`、`ExecutionAlgorithm` 要让 Python 子类覆盖回调，结构是：

```rust
// 示意，crates/trading/src/python/strategy.rs
#[pyo3::pyclass(module = "nautilus_trader.trading", name = "Strategy", unsendable, subclass, weakref)]
pub struct PyStrategy { inner: Rc<UnsafeCell<PyStrategyInner>> }

pub struct PyStrategyInner {
    core: StrategyCore,                       // 和 Rust 策略用的是同一个核心
    py_self: Option<Py<PyWeakrefReference>>,  // 指回 Python 子类实例的弱引用
    config: Option<Py<PyAny>>, clock: PyClock, logger: PyLogger,
}
impl Strategy for PyStrategyInner { /* … */ }
impl DataActor for PyStrategyInner { /* on_quote 等转发到下面的 dispatch_* */ }

impl PyStrategyInner {
    fn dispatch_on_quote(&mut self, quote: QuoteTick) -> PyResult<()> {
        if let Some(py_self) = self.python_instance()? {
            Python::attach(|py| py_self.call_method1(py, "on_quote", (quote.into_py_any(py)?,)))?;
        }
        Ok(())
    }
}
```

Rust 的 `Trader` 管理的是 `PyStrategyInner`，它和 Rust 写的策略一样实现 `Strategy` trait；行情到来时，它通过弱引用找到 Python 实例，按名字调用 `on_quote`。用弱引用是为了不让 Rust 侧把 Python 对象“吊住”，形成循环引用。`__init__` 里会调用 `set_python_instance` 记下这个弱引用，所以 Python 子类的 `__init__` 必须调用 `super().__init__()`。

### 5.2 快照语义：订单不会“自己更新”

把 ① 和 ② 放在一起，就得到 v2 Python 里最需要记住的一条规则。`Cache.order` 的 Python 实现是：

```rust
// 示意，crates/common/src/python/cache.rs
#[pyo3(name = "order")]
fn py_order(&self, py: Python, client_order_id: ClientOrderId) -> PyResult<Option<Py<PyAny>>> {
    let cache = self.0.borrow();
    match cache.order(&client_order_id) {
        Some(order) => Ok(Some(order_any_to_pyobject(py, order.clone())?)),
        None => Ok(None),
    }
}
```

`order.clone()`：Python 拿到的是那一刻的订单拷贝。之后交易所回了成交，内核里的订单变了，你手里那个 Python 对象的 `status` 和 `filled_qty` 不会变。下单方向也一样：`strategy.submit_order(order)` 先用 `pyobject_to_order_any` 按 `order_type` 把 Python 对象提取成一个 `OrderAny`（又一次复制），再交给 Rust 的 `Strategy::submit_order`。

所以在 Python 策略里，订单对象只当作“当时的记录”；要最新状态，在回调里重新 `self.cache.order(client_order_id)`。v1 的 Cython 版本里，缓存返回的是同一个可变对象，很多 v1 写法依赖“对象会自己更新”，迁移时要逐个检查。这条规则在 Rust 用户代码里同样成立（`CacheApi` 返回快照），区别只是 Rust 侧还能在引擎内部拿到 `OrderRef` 借用。

### 5.3 数值类型在 Python 里的行为

`Price`、`Quantity`、`Money` 在 Python 里实现了运算符，结果类型按操作数决定（`crates/model/src/python/types/price.rs`）：

| 表达式 | 结果 |
| --- | --- |
| `Price + Price`、`Price - Price` | `Price`（两者精度必须一致） |
| `Price + float` | `float` |
| `Price * Price`、`Price * Decimal` | `Decimal` |
| `float(price)`、`price.as_double()` | `float` |
| `round(price)`、`price.as_decimal()` | `Decimal` |

构造方式有 `Price.from_str("100.25")`、`Price.from_int(100)`、`Price(100.25, 2)`、`Price.from_raw(raw, precision)`，以及 `from_decimal`、`from_mantissa_exponent`。用 `from_raw` 时要记得 wheel 是高精度模式，`raw` 的放大倍数是 10¹⁶。订单的 `avg_px`、`slippage` 是 `decimal.Decimal`（v1 是 `float`），`Decimal("0.70000") == 0.7` 为假，比较时要用 `Decimal` 对 `Decimal`。

### 5.4 纯 Python 的数据结构

真正用 Python 写的数据结构只有下面几类，都在“边缘”：

| 结构 | 位置 | 作用 |
| --- | --- | --- |
| `@customdataclass` | `model/custom.py` | 把普通 dataclass 变成自定义数据：补上 `ts_event`、`ts_init`、`to_dict`/`from_dict` 和 Arrow schema；用 `register_custom_data_class` 登记后包进 `CustomData` 发布 |
| `StrategyConfig` 子类 | 用户代码 | 基类是 Rust/PyO3 类型；自定义字段写成 `__init__` 的仅关键字参数，并调用无参的 `super().__init__()`（v1 是 msgspec `Struct`，带注解的字段不会带过来） |
| `ImportableConfig`、`ImportableFactoryConfig` | `live/config.py` | 用“模块路径:类名”字符串描述组件和工厂，节点按路径动态导入 |
| `InstrumentProvider` | `live/providers.py` | Python 适配器的标的加载器，内部是 `dict` |
| `DataClient`、`ExecutionClient` | `live/clients.py` | Python 适配器基类，经 `ClientRuntime` 把数据、事件、报告排队交给 Rust |
| `ReportProvider`、Tearsheet | `analysis/` | 把订单、成交、仓位、账户转成 pandas `DataFrame`，画 Plotly 报表 |
| `CSVTickDataLoader` 等 | `persistence/loaders.py` | 从 CSV / Parquet 读成 DataFrame，再转成模型对象 |

数据目录查询（`persistence/catalog_to_df.py`）在 Rust 侧完成，结果经 Arrow C Stream 交给 Python，变成 `pyarrow.Table` 或 DataFrame，中间不逐行构造 Python 对象。

### 5.5 序列化与 pickle

值对象都实现了 `__reduce__`，行情类型还有 `__getstate__`/`__setstate__`，以及 `to_dict`、`from_dict`、`to_json_bytes`、`to_msgpack_bytes`。pickle 能工作依赖第 3.2 节的 `fixup_module_names`：pickle 记下的是 `nautilus_trader.model.QuoteTick`，而不是内部的 `_libnautilus` 路径。v2 的 pickle 数据和 v1 不通用，`OrderBook` 的快照要用 v2 重新生成。

::: warning 常见误区
- **把 v1 的目录和文档当成现在的代码。** `pip install nautilus_trader` 装到的是 v1（1.231.0）；v2 在 `develop` 分支，PyPI 上是 `--pre` 的 2.0.0rc 版本。v1 的核心在仓库根目录的 `.pyx` 里，v2 在 `crates/`。
- **在 Python 包里找实现。** `python/nautilus_trader/` 下大多数模块只是转出 `_libnautilus`，逻辑要去对应 crate 的 `src/` 里找，`src/python/` 只是包装。
- **以为 Python 拿到的订单是活的。** 缓存返回的是快照，提交订单时也是复制进去的；要最新状态就重新向缓存要。
- **混用 64 位和 128 位数据。** Python wheel 是 `high-precision`，默认编译的 Rust 程序不是；两边的 `raw` 放大倍数和 Parquet 数据都不同。
- **以为 `Ustr` 标识符不占内存。** 字符串表永不释放，订单 ID 一类不断增长的标识符会让长期运行的节点内存缓慢上涨。
- **在策略注册前访问 `cache`、`clock`。** 这些字段在注册到 `Trader` 时才接上，之前访问会报错。
:::

## 本章结论

NautilusTrader v2 是“一个 Rust 内核，两种外壳，一层 Python 外观”。Rust 侧按依赖分成七层、24 个 crate，读源码从 `model` 和 `common` 开始；Python 侧的 `nautilus_trader` 几乎全是 `_libnautilus` 的转出口，纯 Python 代码只在报表、数据加载和 Python 适配器基类里。核心数据结构有两个共同风格：用 `…Any` 枚举代替 trait 对象，用事件列表推出订单、仓位、账户的状态；状态集中在 `Cache` 里，由引擎在单线程上写，用户代码不论 Rust 还是 Python，读到的都是快照。

## 检查理解

1. 在 `python/nautilus_trader/` 里找不到 `ExecutionEngine` 的实现，它在哪里？Python 是怎样拿到这个类的？

   <details><summary>参考答案</summary>

   实现在 `crates/execution/src/engine/`，Python 绑定在 `crates/execution/src/python/`。`crates/pyo3/src/lib.rs` 的 `_libnautilus` 用 `wrap_pymodule!(nautilus_execution::python::execution)` 把它挂成子模块并登记到 `sys.modules`，`python/nautilus_trader/execution/__init__.py` 再 `from nautilus_trader._libnautilus.execution import *` 转出来，最后用 `fixup_module_names` 把 `__module__` 改成公开路径。

   </details>

2. Python 策略在 `on_start` 里保存了 `self.order = self.order_factory.limit(...)`，提交后在 `on_order_filled` 里检查 `self.order.status`，发现还是 `INITIALIZED`。为什么？应该怎么写？

   <details><summary>参考答案</summary>

   `LimitOrder` 是值对象（`from_py_object`），`submit_order` 时被复制成 Rust 的 `OrderAny` 交给内核，之后内核里那份随事件更新，Python 手里这份不变。应该在回调里用事件里的 `client_order_id` 重新查：`self.cache.order(event.client_order_id)`。

   </details>

3. `Data` 枚举里为什么 `Quote(QuoteTick)` 不装箱，而 `BookDepth(Box<OrderBookDepth>)` 装箱？

   <details><summary>参考答案</summary>

   枚举的大小由最大的变体决定。`OrderBookDepth` 带 10 档买卖盘，比 `QuoteTick` 大得多，如果直接放进枚举，所有 `Data` 值（包括数量最多的报价和成交）都得按它的大小分配和复制。把少见的大变体放到堆上，枚举就保持小，热路径上的报价在 channel 和总线里搬运更便宜。

   </details>

4. `CacheIndex` 里为什么要同时有 `venue_order_ids` 和 `client_order_ids` 两张表？适配器什么时候会用到前者？

   <details><summary>参考答案</summary>

   平台用 `ClientOrderId` 标识订单，交易所用自己的 `VenueOrderId`，两边各查一个方向。交易所推送的成交或状态回报里往往只有交易所的订单号，适配器或执行引擎要用 `venue_order_ids` 反查出本地的 `ClientOrderId`，才能找到对应订单、生成正确的订单事件。

   </details>

## 参考资料

- 官方概念文档：[Architecture](https://nautilustrader.io/docs/latest/concepts/architecture/) · [Python](https://github.com/nautechsystems/nautilus_trader/blob/develop/docs/concepts/python.md) · [Rust](https://github.com/nautechsystems/nautilus_trader/blob/develop/docs/concepts/rust.md) · [Value types](https://github.com/nautechsystems/nautilus_trader/blob/develop/docs/concepts/value_types.md) · [Cache](https://github.com/nautechsystems/nautilus_trader/blob/develop/docs/concepts/cache.md) · [Message bus](https://github.com/nautechsystems/nautilus_trader/blob/develop/docs/concepts/message_bus.md)
- 开发指南：[Rust（含 Identifier storage）](https://github.com/nautechsystems/nautilus_trader/blob/develop/docs/developer_guide/rust.md) · [Adapters（含 Structure of an adapter）](https://github.com/nautechsystems/nautilus_trader/blob/develop/docs/developer_guide/adapters.md) · [Python adapters](https://github.com/nautechsystems/nautilus_trader/blob/develop/docs/developer_guide/python_adapters.md)
- 迁移指南：[MIGRATION_V2.md](https://github.com/nautechsystems/nautilus_trader/blob/develop/MIGRATION_V2.md)
- 源码：[`Cargo.toml`](https://github.com/nautechsystems/nautilus_trader/blob/develop/Cargo.toml) · [`crates/pyo3/src/lib.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/pyo3/src/lib.rs) · [`python/pyproject.toml`](https://github.com/nautechsystems/nautilus_trader/blob/develop/python/pyproject.toml) · [`crates/model/src/`](https://github.com/nautechsystems/nautilus_trader/tree/develop/crates/model/src) · [`crates/common/src/cache/`](https://github.com/nautechsystems/nautilus_trader/tree/develop/crates/common/src/cache) · [`crates/common/src/msgbus/core.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/common/src/msgbus/core.rs) · [`crates/trading/src/python/strategy.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/trading/src/python/strategy.rs)
- 配图由 `scripts/generate-nautilus-trader-figures.py` 生成。

有了这张静态的地图，下一章让系统动起来：内核怎样启动，一条报价和一笔订单怎样在这些结构之间流动。[第 1 章：整体架构](./architecture.md)。
