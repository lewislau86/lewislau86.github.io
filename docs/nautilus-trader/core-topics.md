---
title: "附录：重点主题速览"
description: 读 NautilusTrader Rust 核心时绕不开的十个主题：定点数值类型、时钟与两种时间戳、订单状态机与事件溯源、缓存、单线程并发模型、风控与订单仿真、对账、数据与持久化、PyO3 边界、测试与错误处理。每个主题说清在哪里、为什么这样设计、扩展时容易踩什么坑。本页原是第 3 章，现作为速览保留，各主题在正文对应章节展开。
---

# 附录：重点主题速览

[全书目录](./index.md) · [上一篇](./futu-adapter.md)

::: tip 本页用途
第 0、1 章是地图。这一页把读源码、写适配器、写策略时反复遇到的十个主题集中讲一遍。每个主题回答四个问题：它是什么、代码在哪里、为什么这样设计、扩展时容易踩什么坑。可以按需跳读。

**源码版本：** `develop` 分支，2026-11-14 核对。

**对应官方文档：** [Value Types](https://nautilustrader.io/docs/latest/concepts/value_types/) · [Orders](https://nautilustrader.io/docs/latest/concepts/orders/) · [Cache](https://nautilustrader.io/docs/latest/concepts/cache/) · [Execution](https://nautilustrader.io/docs/latest/concepts/execution/) · [DST](https://nautilustrader.io/docs/latest/concepts/dst/)
:::

::: info 本页的去向
本页原是第 3 章。全书按官方文档的概念划分调整结构后，这十个主题会在正文对应章节完整展开；那些章节成文之前，本页作为速览保留。

| 本页小节 | 在正文里展开的位置 |
| :--- | :--- |
| 1. 定点数 | 第 2 章 数值类型、标识符与时间戳 |
| 2. 时钟与时间戳 | 第 2 章；第 17 章 Clock 与计时器 |
| 3. 订单状态机与事件溯源 | 第 5 章 订单；第 8 章 事件与事件溯源 |
| 4. 缓存 | 第 16 章 Cache |
| 5. 并发模型 | 第 1 章；第 30 章 LiveNode 与 AsyncRunner |
| 6. 风控、订单仿真与执行算法 | 第 19 章 RiskEngine；第 21 章 OrderEmulator；第 13 章 执行算法 |
| 7. 对账 | 第 34 章 ExecutionManager |
| 8. 数据与持久化 | 第 4 章 行情数据；第 25 章 数据目录 |
| 9. PyO3 边界 | 第 0 章第 4 节；第 39 章 Python 策略 |
| 10. 测试与错误处理 | 第 37 章 确定性仿真测试 |
:::

## 1. 价格和数量：定点数，不是浮点数

`Price`、`Quantity`、`Money` 都是定点数：内部存一个放大过的整数 `raw`，再记一个精度。

```rust
// 示意，crates/model/src/types/{price,quantity,money}.rs
pub struct Price    { raw: PriceRaw,    pub precision: u8 }   // raw 是 pub(crate)，外部用 .raw() 读
pub struct Quantity { raw: QuantityRaw, pub precision: u8 }
pub struct Money    { raw: MoneyRaw,    pub currency: Currency }   // 没有精度字段，精度跟着币种走
```

放大倍数由 `crates/model/src/types/fixed.rs` 定义，并且有两种模式，由 `high-precision` feature 切换（默认关闭，开启 `defi` 时自动打开）：

| | 标准模式 | `high-precision` |
| --- | --- | --- |
| `PriceRaw` / `MoneyRaw` | `i64` | `i128` |
| `QuantityRaw` | `u64` | `u128` |
| `FIXED_PRECISION`（小数位） | 9 | 16 |
| `PRICE_MAX` | 约 92 亿 | 约 17 万亿 |

**为什么不用 `f64`：** 0.1 + 0.2 在浮点数里不等于 0.3，交易系统里价格比较、数量累加、盈亏计算都不能接受这种误差，而且回测要求结果可复现。`types/mod.rs` 的说法是“fixed-point arithmetic internally for deterministic calculations”。`fixed.rs` 的文档里还记了一个真实的教训：旧版数据转换用 `int(value * FIXED_SCALAR)`，引入了浮点误差。正确的写法是先按精度取整，再放大。

两个值相等看的是数值，精度只影响显示。时间戳也一样不用浮点：`UnixNanos`（`crates/core/src/nanos.rs`）是一个 `u64` 纳秒数，和表示时长的 `DurationNanos` 在类型上分开。

::: warning 坑
- 交易所发来的是浮点数时，要在解析边界经 `Decimal` 转换，不要 `Price::new(f64)` 一路传下去。
- 64 位和 128 位两种模式编出来的二进制和 Parquet 数据互不兼容。开发指南要求 `high-precision` 要传递给所有依赖它的 crate；很多适配器 crate 默认就开了它。
:::

## 2. 时间：两种时钟，两个时间戳

**时钟。** `Clock` trait 在 `crates/common/src/clock/mod.rs`，提供当前时间和计时器（`set_timer`、`set_time_alert`）。有两个实现：

- `LiveClock`（`crates/common/src/live/clock.rs`）：读全局的实时原子时钟，计时器由 Tokio 调度，到点后把 `TimeEvent` 经 channel 送回核心线程；
- `VirtualClock`（`crates/common/src/clock/virtual.rs`）：回测用，内部是一个按时间排序的堆，`advance_time` 推进到某个时刻并返回期间到点的事件。旧版里叫 `TestClock`，现在的 Rust 代码里已经没有这个名字。

实时时钟底下是 `AtomicTime`（`crates/core/src/time.rs`）：每次读取都保证至少比上一次大 1 纳秒，严格单调，所以同一纳秒内的两个事件也能排出先后。

**两个时间戳。** 几乎每个数据和事件都带两个时间：

- `ts_event`：事件实际发生的时间，通常是交易所时间；
- `ts_init`：Nautilus 创建这个对象的时间。回测按 `ts_init` 稳定排序回放。

::: warning 坑
用 `ts_init - ts_event` 当延迟，只在两边时钟同步时才成立；时钟有偏差时 `ts_init` 甚至可能早于 `ts_event`。
:::

## 3. 订单：状态机加事件溯源

订单有 9 种类型（市价、限价、止损市价、止损限价、触价、跟踪止损等），统一用 `OrderAny` 表示，代码在 `crates/model/src/orders/`。

**事件溯源。** 订单的状态不是直接改字段改出来的，而是由事件推出来的：`OrderCore::apply` 先校验状态迁移是否合法，再执行这个事件的处理逻辑，最后把事件追加到订单的事件列表里。所以可以用 `OrderAny::from_events` 重放事件流，重建出一模一样的订单。订单事件有 19 种，定义在 `crates/model/src/events/order/any.rs`：`Initialized`、`Denied`、`Submitted`、`Accepted`、`Rejected`、`Canceled`、`Expired`、`Triggered`、`PendingUpdate`、`PendingCancel`、`Updated`、`Filled` 等。

**状态机。** `OrderStatus` 有 15 个状态（Initialized、Denied、Emulated、Released、Submitted、Accepted、Rejected、Canceled、Expired、Triggered、PendingUpdate、PendingCancel、PartiallyFilled、Filled、Voided）。合法的迁移写在 `crates/model/src/orders/mod.rs` 的 `OrderStatus::transition` 里，是一张大 match 表，不在表里的组合返回 `InvalidStateTransition`。表里特意允许了一些“现实中会发生”的迁移，比如已取消的订单又收到成交（`Canceled → Filled`）：撤单请求和成交在路上交错，是真实交易所常见的情况。

**仓位 ID 与 OMS 类型。** `OmsType` 决定一个标的上是一个净仓位还是多个独立仓位（`crates/execution/src/engine/mod.rs` 里分配仓位 ID）：

- `Netting`：一个标的、一个策略只有一个仓位，ID 是 `{instrument_id}-{strategy_id}`；
- `Hedging`：每次开仓一个新仓位，优先用成交回报里带的仓位 ID。

::: warning 坑
迁移表里，成交事件一律迁到 `Filled`；“部分成交”是成交处理函数里按已成交数量和订单数量比较之后改写出来的。只读迁移表会以为没有 `PartiallyFilled` 这条路。
:::

## 4. 缓存：引擎写，别人读

`Cache`（`crates/common/src/cache/mod.rs`）存放运行时的全部状态：标的、订单簿、最近的报价成交和 K 线（有界队列）、账户、订单、仓位。它可以挂一个数据库后端（`CacheDatabaseAdapter` trait，实现有 `crates/infrastructure` 里的 Redis 和 PostgreSQL），重启时从里面恢复。

所有权规则是：**数据引擎和执行引擎负责写，其他人只读。** 适配器拿到的是 `CacheView`（`crates/common/src/cache/view.rs`），它只暴露只读的 `borrow`；源码注释写的是“so cache writes stay owned by the data and execution engines”。适配器要改状态，就发事件或报告，让引擎去改。

还有一条持久化语义：写内存不依赖写数据库成功；持久化失败只记 ERROR 日志、不往上抛。所以“缓存调用成功”不等于“已经落盘”。

::: warning 坑
缓存是 `Rc<RefCell<…>>`，持有一个借用（比如订单的引用）时再去分发事件，事件处理函数又来借用缓存，就会触发 `RefCell` 的重入 panic。开发指南要求分发事件之前先释放借用，之后再重新查询。
:::

## 5. 并发模型：单线程核心，异步 I/O 在外

第 1 章说过，核心是单线程的。具体落到代码上有四件事：

- **线程局部的单例。** 消息总线、组件注册表都放在 `thread_local!` 里，只在核心线程上存在。
- **channel 是唯一的入口。** `crates/live/src/runner.rs` 的 `AsyncRunner` 持有 7 对 Tokio channel（时间事件、系统事件、系统命令、执行事件、交易命令、数据事件、数据命令）。`bind_senders` 把发送端放进线程局部存储，适配器用 `get_data_event_sender()`、`get_exec_event_sender()` 取出来，在后台任务里发事件；`LiveNode::run` 在核心线程上用带 `biased;` 的 `tokio::select!` 收，系统和执行事件优先于行情。
- **trait 不要求 `Send`。** `DataClient`、`ExecutionClient` 用的是 `#[async_trait(?Send)]`，因为客户端对象只在核心线程上，还可能持有不能跨线程的 Python 对象。
- **不准直接 `tokio::spawn`。** 适配器的后台任务交给 `TaskGroup`（`crates/live/src/task.rs`）管理，预提交钩子 `.pre-commit-hooks/check_tokio_usage.sh` 会拦截直接的 `tokio::spawn`。这样节点停止时能把任务一起收掉，确定性模拟测试（第 10 节）也能接管调度。

::: warning 坑
`get_exec_event_sender()` 读的是线程局部存储，从别的线程调用会 panic，因为那个线程的槽是空的。在工厂里先用 `try_get_exec_event_sender()` 检查，把发送端克隆好再交给后台任务。
:::

## 6. 风控、订单仿真与执行算法

**风控引擎**（`crates/risk/src/engine/mod.rs`）是订单去交易所之前的最后一道关：

- 交易状态 `TradingState`：`Active` 正常；`Reducing` 只允许减仓；`Halted` 拒绝一切新订单和改单；
- 价格检查：精度不能超过标的的精度，价格必须为正等；数量检查：精度、最大最小数量；名义金额：`max_notional_per_order`；
- 限流：下单和改单各一个 `Throttler`，默认每秒 100 次（`engine/config.rs`）。

**订单仿真器**（`crates/execution/src/order_emulator/emulator.rs`）让交易所不支持的订单类型也能用：比如交易所只支持限价单，平台可以在本地盯着价格，触发后再把止损单“释放”成市价或限价单发出去。可仿真的有限价、止损、触价、跟踪止损等类型。

**执行算法**（`crates/trading/src/algorithm/`）把一个大单拆成多个子单，自带的是 TWAP（`TwapAlgorithm`，参数是总时长和间隔）。它实现的是 `DataActor` 而不是 `Strategy`，因为它不持有仓位；子单的 ID 是 `{父单 ClientOrderId}-E{序号}`。

::: warning 坑
被仿真器持有、还没释放的订单不经过风控，也不占用资金（`docs/concepts/orders/emulated.md`）。风控检查发生在释放之后。
:::

## 7. 对账：本地状态要和交易所对齐

平台的订单和仓位状态是从事件推出来的；断线、重启、漏推送都会让它和交易所的真实状态不一致。对账就是定期去交易所查一遍，把差异补齐。官方文档的原则很严格：交易所报告的持仓是权威的，对不齐就“fail-closed”，策略不启动；**没收到报告不等于空仓**。

- **启动时**：调用适配器的 `generate_order_status_reports`、`generate_fill_reports`、`generate_position_status_reports`（默认的 `generate_mass_status` 把三者合在一起）。官方文档写的处理顺序是订单、成交、仓位，平台不认识的订单会补建成外部订单。
- **运行中**：`ExecutionManager`（`crates/live/src/execution/manager.rs`）定期检查“在途订单”（已提交但迟迟没有回报的），可选地定期检查挂单和仓位。

主要配置（`LiveExecutionEngineConfig`，`crates/live/src/node/config.rs`）：

| 参数 | 默认值 |
| --- | --- |
| `reconciliation` | `true` |
| `reconciliation_startup_delay_secs` | 10 秒 |
| `inflight_check_interval_ms` | 2000 |
| `inflight_check_threshold_ms` | 5000 |
| `inflight_check_retries` | 5 |
| `open_check_interval_secs`、`position_check_interval_secs` | 不开启 |

::: warning 坑
`generate_mass_status` 的默认实现用的是实时时钟。用模拟时钟或回测时钟的客户端必须自己覆盖它，否则报告的时间戳会错。
:::

## 8. 数据与持久化

**数据类型**在 `crates/model/src/data/`：`QuoteTick`、`TradeTick`、`Bar`、`OrderBookDelta(s)`、`OrderBookDepth`，以及标记价、指数价、资金费率、期权希腊值、标的状态等，统一包在 `enum Data` 里。注意 `OrderBookDepth10` 已经改名为 `OrderBookDepth`：10 档以内存在栈上，更深的自动放到堆上。

**K 线**由 `BarType` 描述，里面的 `BarSpecification` 是“步长 + 聚合方式 + 价格类型”，聚合方式有 18 种：按笔数、成交量、成交额及它们的不平衡和游程变体，按毫秒到年的时间，以及 Renko。聚合器在 `crates/data/src/aggregation.rs`。

**订单簿**在 `crates/model/src/orderbook/`，支持 L1、L2（按价位）和 L3（逐笔订单）三种，每一侧是一个 `BTreeMap<价格, 价位>`。`OwnOrderBook` 单独跟踪自己挂的单，方便策略区分“市场的量”和“自己的量”。

**数据目录** `ParquetDataCatalog`（`crates/persistence/src/backend/parquet/catalog/`）基于 object_store 和 DataFusion，按“数据类型/标的”分目录，文件名是这段数据的起止时间。Python 端的同名类就是它的包装。

::: warning 坑
同一个 Parquet 文件里的价格精度必须一致。交易所调整过最小变动价位的话，调整前后的数据不能合进一个文件。
:::

## 9. PyO3 边界：Rust 是唯一的事实来源

Python 包用 maturin 构建（`python/pyproject.toml` 指向 `crates/pyo3/Cargo.toml`）。`crates/pyo3/src/lib.rs` 里的 `#[pymodule] fn _libnautilus` 把各 crate 的 `python` 子模块挂到一起，Python 端的 `nautilus_trader.model` 等模块就是从 `nautilus_trader._libnautilus.model` 导入的。

各 crate 在 `python` feature 下给类型加 `#[pyclass]`，类型存根（`.pyi`）由 `make py-stubs` 生成。另外 `core` 和 `model` 还保留一个可选的 C FFI（`ffi` feature，头文件由 cbindgen 生成）。

对读源码的意义是：**逻辑都在 Rust 里**。读核心代码时可以先跳过各 crate 的 `src/python/` 和 `src/ffi/` 目录，它们只是包装；Python 部分的笔记再回来看这一层。

## 10. 测试与错误处理

**测试工具。** `crates/testkit` 提供测试数据（带 SHA-256 校验）和两个验收工具 `DataTester`、`ExecTester`，第 38 章的里程碑就是用它们验收的。此外还有 proptest 属性测试（`proptest-regressions/` 目录记录失败用例）、libFuzzer 模糊测试（适配器的 `fuzz` feature，`scripts/fuzz-adapter.sh`）、Criterion 和 iai 基准测试；Rust 测试用 cargo nextest 跑。

**确定性模拟测试（DST）**（`docs/concepts/dst.md`、`crates/common/src/live/dst.rs`）：把 Tokio 的时间、任务、运行时、信号换成 madsim 的确定性实现，同一个随机种子就能重现同一次运行，用来测断线、重连、乱序这类难复现的问题。要同时打开 `nautilus-common` 的 `simulation` feature 和 `RUSTFLAGS="--cfg madsim"`，只开一个会悄悄退回真正的 Tokio。代码要配合：`select!` 加 `biased;`，迭代顺序要确定（用 `IndexMap` 或排序），随机数用 `madsim::rand`，不能用 `spawn_blocking`。这也是“不准直接 `tokio::spawn`”的原因之一。开发指南要求维护中的官方适配器满足 DST 契约，暂时做不到的要有一份按交易所记录的迁移说明跟踪差距；OKX 适配器是参考实现。

**错误处理**（`docs/developer_guide/rust.md`）：库和领域 API 返回类型化的 `Result`，错误类型用 thiserror 定义；适配器和应用层的编排代码用 `anyhow::Result`；输入校验走 `new_checked()` 返回 `Result`、`new()` 校验失败就 panic 的配对模式。内部不变量被破坏时允许 panic，配合 release 下的 `panic = "abort"`，这就是 crash-only。

::: warning 坑
仓库并没有在 lint 层面禁止 `unwrap`：`clippy::unwrap_used` 在根 `Cargo.toml` 里是注释掉的，只在 `make clippy-strict-audit` 里作为审查提示。生产代码里要不要 `unwrap`，靠的是代码审查和“这里 panic 是不是不变量被破坏”的判断。
:::

## 小结：读源码时的几个抓手

| 想弄清楚的事 | 先看 |
| --- | --- |
| 一个值为什么不用浮点 | `crates/model/src/types/fixed.rs` |
| 订单为什么进不了某个状态 | `crates/model/src/orders/mod.rs` 的 `OrderStatus::transition` |
| 谁能写缓存 | `crates/common/src/cache/view.rs` |
| 后台任务的数据怎样进核心 | `crates/live/src/runner.rs` |
| 订单为什么被拒 | `crates/risk/src/engine/mod.rs` |
| 重启后状态怎样恢复 | `docs/concepts/execution/reconciliation.md`、`crates/live/src/execution/manager.rs` |
| 某个 Python 类对应哪段 Rust | `crates/pyo3/src/lib.rs`，再到对应 crate 的 `src/python/` |

## 参考资料

- 官方文档：[architecture](https://github.com/nautechsystems/nautilus_trader/blob/develop/docs/concepts/architecture.md) · [value_types](https://github.com/nautechsystems/nautilus_trader/blob/develop/docs/concepts/value_types.md) · [positions](https://github.com/nautechsystems/nautilus_trader/blob/develop/docs/concepts/positions.md) · [reconciliation](https://github.com/nautechsystems/nautilus_trader/blob/develop/docs/concepts/execution/reconciliation.md) · [dst](https://github.com/nautechsystems/nautilus_trader/blob/develop/docs/concepts/dst.md) · [rust 开发指南](https://github.com/nautechsystems/nautilus_trader/blob/develop/docs/developer_guide/rust.md) · [ffi](https://github.com/nautechsystems/nautilus_trader/blob/develop/docs/developer_guide/ffi.md)
- 源码：[`crates/model/src/types/`](https://github.com/nautechsystems/nautilus_trader/tree/develop/crates/model/src/types) · [`crates/model/src/orders/`](https://github.com/nautechsystems/nautilus_trader/tree/develop/crates/model/src/orders) · [`crates/common/src/cache/`](https://github.com/nautechsystems/nautilus_trader/tree/develop/crates/common/src/cache) · [`crates/risk/src/engine/`](https://github.com/nautechsystems/nautilus_trader/tree/develop/crates/risk/src/engine) · [`crates/live/src/`](https://github.com/nautechsystems/nautilus_trader/tree/develop/crates/live/src)

这些主题在正文里的完整展开见上面“本页的去向”；从写策略的人的角度看，可以读[第 9 章：Rust 策略的框架与运行机制](./rust-strategy.md)和[第 10 章：回调：一条消息怎样变成 on_xxx](./callbacks.md)。回到[全书目录](./index.md)查看规划。
