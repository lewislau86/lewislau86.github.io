---
title: "第 13 章：Actor、执行算法与配置"
description: 策略之外的两种用户组件：只收数据、不下单的 DataActor，以及把一张大单拆成小单的执行算法（以 TWAP 为例）；组件之间怎样用信号和自定义数据通信；配置结构体在 Rust 和 Python 两侧怎样定义、默认值怎样解析；日志线程与日志配置。
---

# 第 13 章：Actor、执行算法与配置

[全书目录](./index.md) · [上一章](./indicators.md) · [下一章](./kernel.md)

::: tip 本章学习目标
能说清 `DataActor`、`Strategy`、`ExecutionAlgorithm` 三种组件各能做什么、不能做什么；会写一个 Rust 的 Actor 并注册到回测或实盘节点；知道 Actor 和策略之间用信号通信时消息走的是哪条路；能追踪一张带 `exec_algorithm_id` 的订单被 TWAP 拆成哪些子单、各自叫什么；读懂一个配置结构体的默认值从哪里来。

**源码版本：** `develop` 分支，提交 `364254f`（2026-11-18）。Actor 在 `crates/common/src/actor/`（宏在 `crates/common/src/macros.rs`），信号在 `crates/common/src/signal.rs`，执行算法在 `crates/trading/src/algorithm/`，日志在 `crates/common/src/logging/`。

**对应官方文档：** [Actors](https://nautilustrader.io/docs/latest/concepts/actors/) · [Execution](https://nautilustrader.io/docs/latest/concepts/execution/)（执行算法一节）· [Configuration](https://nautilustrader.io/docs/latest/concepts/configuration/) · [Logging](https://nautilustrader.io/docs/latest/concepts/logging/)
:::

第 9～12 章都围绕策略展开。但一个交易系统里不只有策略：有的组件只负责看行情、算信号（比如一个监控价差的模块），有的组件只负责把策略的大单拆小、慢慢执行。NautilusTrader 把它们做成另外两种组件：`DataActor` 和 `ExecutionAlgorithm`。这一章看这两种组件，以及所有组件都要用到的配置和日志。

主线例子是一个三件套：一个 Actor 监控 ETHUSDT 的买卖价差并发出信号，一个策略收到信号后决定买入 6 ETH，并把这张单交给 TWAP 算法在 60 秒内分 6 次执行。

## 1. 三种组件 {#components}

| | `DataActor` | `Strategy` | `ExecutionAlgorithm` |
| :--- | :--- | :--- | :--- |
| 订阅、请求数据 | 能 | 能 | 能 |
| 计时器、缓存、日志 | 能 | 能 | 能 |
| 下单 | 不能 | 能 | 只能派生子单 |
| 收订单、仓位事件 | 不能 | 能 | 能（它处理的订单） |
| 拥有仓位 | 否 | 是 | 否，仓位属于发单的策略 |

三者共用第 9 章讲过的那套核心：都持有一个 `DataActorCore`，都通过 `DataActor` trait 的默认方法订阅数据、设置计时器、读缓存，都有同一套生命周期（`READY`、`RUNNING`、`STOPPED`、`DEGRADED`、`FAULTED`、`DISPOSED`，见官方文档 Lifecycle 一节）。策略在此之上加了 `StrategyCore`（下单工厂、订单管理器、组合），执行算法加了 `ExecutionAlgorithmCore`。官方文档在 Actor 一页最后专门说明：Actor 不管理订单，也没有订单事件回调；需要把策略里算出的东西交给 Actor 时，用信号或自定义数据（第 3 节）。

## 2. 写一个 Actor {#actor}

官方的 Rust 指南（`docs/how_to/write_rust_actor.md`）用一个 `SpreadMonitor` 做例子，几乎就是主线例子的第一件：

```rust
// 节选自 docs/how_to/write_rust_actor.md
pub struct SpreadMonitor {
    core: DataActorCore,
    instrument_id: InstrumentId,
}

impl SpreadMonitor {
    pub fn new(instrument_id: InstrumentId) -> Self {
        let config = DataActorConfig {
            actor_id: Some(ActorId::from("SPREAD_MON-001")),
            ..Default::default()
        };
        Self { core: DataActorCore::new(config), instrument_id }
    }
}

nautilus_actor!(SpreadMonitor);   // 生成 DataActorNative：把 core 字段交给框架

impl DataActor for SpreadMonitor {
    fn on_start(&mut self) -> anyhow::Result<()> {
        self.subscribe_quotes(self.instrument_id, None, None);
        Ok(())
    }
    fn on_quote(&mut self, quote: &QuoteTick) -> anyhow::Result<()> {
        let spread = quote.ask_price.as_f64() - quote.bid_price.as_f64();
        log::info!("Spread: {spread:.5}");
        Ok(())
    }
}
```

和第 9 章的策略比，结构一模一样，只是少了一层：`nautilus_actor!` 宏（`crates/common/src/macros.rs`）只生成 `DataActorNative` 的两个访问函数，把名为 `core` 的字段交给框架（第二个参数可以换字段名）；`Actor` 和 `Component` 由框架的通用实现自动提供。注册时，回测用 `engine.add_actor(actor)`，实盘用 `node.add_actor(actor)`。

`DataActorConfig` 只有三个字段：`actor_id`、`log_events`、`log_commands`。`actor_id` 值得认真设：Python 的 Actor 没设时用类名，Rust 的 Actor 没设时一律叫 `DataActor`，而同一个 ID 注册两次会被拒绝。所以同一个 Actor 跑多个实例，或者有两个不同的 Rust Actor，都要显式给 ID。

## 3. 组件之间怎样通信：信号与自定义数据 {#signals}

主线例子里，价差监控在价差扩大时要通知策略。最轻的办法是信号：

```rust
// 节选自 crates/common/src/actor/data_actor.rs（DataActorCore::publish_signal）
pub fn publish_signal(&self, name: &str, value: String, ts_event: UnixNanos) {
    let now = self.timestamp_ns();
    let ts_event = if ts_event.as_u64() == 0 { now } else { ts_event };
    let signal = Signal::new(Ustr::from(name), value, ts_event, now);
    let data_type = DataType::new(&format!("Signal{}", title_case(name)), None, None);
    let data = CustomData::new(Arc::new(signal), data_type);
    let topic = get_custom_topic(&data.data_type);
    msgbus::publish_any(topic, &data);
}
```

几件事一眼可见。信号的值是 `String`，数值要自己格式化和解析；`ts_event` 传 0 时用当前时间。信号本质上是一条自定义数据，类型名是 `Signal` 加上首字母大写的信号名（`publish_signal("spread", …)` 的类型是 `SignalSpread`），经总线的通用发布接口 `publish_any` 发出，不经过数据引擎，也不会发给任何适配器，是纯进程内的通信。接收方在 `on_start` 里 `subscribe_signal("spread")`，在 `on_signal(&Signal)` 里处理。

需要传结构化数据时，用 `publish_data(data_type, custom_data)` 发布自定义数据（第 4 章第 7 节），接收方订阅同一个 `DataType`，在 `on_data` 里处理。两种方式走的都是消息总线的通用主题路由，第 15 章会讲它和报价、成交那些专用路由的区别。

## 4. 执行算法：TWAP 怎样拆单 {#exec-algorithms}

### 4.1 订单怎样到达算法

执行算法的模块注释（`crates/trading/src/algorithm/mod.rs`）把它的定位说得很清楚：它扩展的是 `DataActor` 而不是 `Strategy`，因为它不拥有仓位，派生的子单带的是发单策略的 ID，它是订单的“处理器”，而不是仓位的管理者。订单的流向是：

1. 策略下单时给订单设上 `exec_algorithm_id`（以及算法需要的 `exec_algorithm_params`）；
2. `Strategy::submit_order` 发现这个字段，就不把命令送往风控，而是发到 `{exec_algorithm_id}.execute` 这个端点；
3. 算法在 `on_order` 里收到这张“主订单”；
4. 算法用 `spawn_market`、`spawn_limit`、`spawn_market_to_limit` 派生子单；
5. 子单经过风控再到执行引擎，和普通订单一样；
6. 算法收到子单的成交事件，管理剩余数量。

### 4.2 主线例子：6 ETH，60 秒，每 10 秒一次

策略这样下单（Python 写法，示意）：

```python
order = self.order_factory.market(
    instrument_id,
    OrderSide.BUY,
    Quantity.from_str("6.00000"),
    exec_algorithm_id=ExecAlgorithmId("TWAP"),
    exec_algorithm_params={"horizon_secs": "60", "interval_secs": "10"},
)
self.submit_order(order)
```

`TwapAlgorithm::on_order`（`algorithm/twap.rs`）做的事情依次是：

- 只接受市价主单，其他类型直接 `deny_order`（`UnsupportedOrderType`）；
- 从参数里解析 `horizon_secs` 和 `interval_secs`，两者都是字符串，缺失或不是数字就拒绝；
- 算出间隔数 `60 ÷ 10 = 6`，每份数量 `6 ÷ 6 = 1`，按品种的数量精度向零截断，再对齐到数量增量；
- 算出一个数量表 `[1, 1, 1, 1, 1, 1]`，并检查它们加起来正好等于主单数量（有零头时会多一份或并进最后一份）；
- 用主单的 `client_order_id` 作名字设一个间隔 10 秒的计时器，并立刻提交第一份。

子单由 `spawn_client_order_id` 命名，格式是“主单号-E序号”：

```rust
// 节选自 crates/trading/src/algorithm/core.rs
ClientOrderId::new(format!("{primary_id}-E{sequence}"))
```

所以前五份是 `O-…-1-E1` 到 `O-…-1-E5`，每派生一份，主单的数量就相应减少；最后一份不再派生，而是把剩下 1 ETH 的主单本身提交出去。每张子单的 `exec_spawn_id` 指向主单，成交事件发到发单策略那里，仓位也记在策略名下。

两条退路值得知道：如果每份数量小于数量增量，或者小于品种的最小下单量，算法会放弃拆分，直接把整张主单提交（并记一条警告）。TWAP 是仓库里唯一的内置执行算法，自己写算法就实现 `ExecutionAlgorithm` trait，最核心的是 `on_order`。

![主线例子的三件套：价差监控发出信号，策略收到后下一张带 TWAP 的市价单，主单被送到算法的端点，算法每 10 秒派生一张子单经风控提交，最后一份是主单本身；成交事件回到策略](/nautilus-trader/figures/actor-twap-flow.svg)

怎么读这张图：看订单号。从策略出发的是一个订单号，到了算法之后变成一串带 `-E` 后缀的子单号，但它们的策略 ID 始终是发单的那个策略，所以成交和仓位都回到策略那里。

## 5. 配置 {#configuration}

所有组件和引擎都由配置结构体构造。官方文档 Configuration 一页列了几条设计原则，读源码时很有用：

<strong>确定的值用确定的类型。</strong>超时、重试次数、心跳间隔这类必须有值的字段，用 `u64`、`u32` 这样的普通类型，构造时就解析好，下游代码不再重复处理默认值。

<strong>`Option` 的含义由字段决定。</strong>`None` 可能表示关闭某个功能、不设上限、跟随运行环境，或者使用内部默认值，存下来的 `Option` 不记得调用方是“没传”还是“传了 None”。要看字段文档才知道。

<strong>默认值有两条路。</strong>多数 Rust 配置用 `bon::Builder` 派生建造者，用 `#[builder(default = …)]` 声明默认值；也可能另有一个手写的 `Default` 实现。`Type::default()` 和 `Type::builder().build()` 是两条独立的构造路径，除非文档保证，不要假设它们结果相同。第 11 章用过的 `DataEngineConfig` 就是这样：

```rust
// 节选自官方文档 Configuration 一页
let with_builder = DataEngineConfig::builder().buffer_deltas(true).build();
let with_struct_update = DataEngineConfig { buffer_deltas: true, ..Default::default() };
```

<strong>Python 配置是 Rust 结构体的包装。</strong>多数 Python 配置类是 PyO3 包装，省略某个参数等于传 `None`，再由包装决定是用 Rust 的默认值还是保留空值。所以 Python 一侧有时无法把一个字段设成 Rust 的 `None`：官方的例子是 Bybit 适配器的轮询间隔，Python 传 `None` 仍然得到 60 秒，只有 Rust 能把它设成 `None` 来关闭轮询。

<strong>未知字段的处理取决于构造路径。</strong>Rust 反序列化时，带 `#[serde(deny_unknown_fields)]` 的配置拒绝多余的键；Python 的固定配置类对不支持的关键字抛 `TypeError`，但 `DataActorConfig`、`StrategyConfig`、`ExecutionAlgorithmConfig` 允许多余的关键字，因为用户要在子类里加自己的字段。Python 子类的写法是：自定义字段写成仅限关键字的参数，并接受 `**_kwargs`，再调用无参的 `super().__init__()`，让基类从同一次调用里读到 `actor_id` 和日志开关。

## 6. 日志 {#logging}

NautilusTrader 的日志不在核心线程上写。Python 组件、Rust 组件和用 `log` crate 的第三方库都写进同一个 `Logger`，日志事件经一个多生产者单消费者通道送到专门的日志线程，由它写到标准输出和文件，所以磁盘 I/O 不会阻塞交易循环。用 `tracing` crate 的第三方库（如 `hyper`、`tokio`）走另一条路：可选的 tracing 订阅器直接写标准输出，由 `RUST_LOG` 过滤。

日志级别由 `LoggerConfig` 配置：标准输出和文件分别设最低级别，文件可以按大小轮转、按日期命名、写成 JSON，还可以按组件单独设级别。纯 Rust 程序更常用环境变量 `NAUTILUS_LOG`：

```bash
export NAUTILUS_LOG="stdout=Info;fileout=Debug;RiskEngine=Error;is_colored"
```

规格串用分号分隔：`stdout`、`fileout` 设级别，`RiskEngine=Error` 这样的键按组件名精确匹配，`nautilus_okx::websocket=Debug` 这样的键按模块路径前缀匹配（仅 Rust），`is_colored`、`print_config`、`log_components_only` 是开关。纯 Rust 程序的日志系统在第一次使用时惰性初始化，设好这个变量就不必显式调用初始化函数。组件配置里的 `log_events`、`log_commands` 则控制这个组件是否把收到的事件和发出的命令记进日志。

::: warning 常见误区
- **想在 Actor 里下单或收订单事件。** Actor 没有这些能力，需要下单的逻辑放进策略，策略把结果用信号或自定义数据交给 Actor。
- **两个 Rust Actor 都不设 `actor_id`。** 它们都叫 `DataActor`，第二个注册会被拒绝。
- **把信号当成跨进程的消息。** 信号只在本进程的总线上传递，不经过数据引擎，也不发给适配器。
- **给 TWAP 一张限价主单。** 内置 TWAP 只接受市价主单，其他类型会被拒绝。
- **以为 TWAP 的子单属于算法。** 子单带的是发单策略的 ID，成交和仓位都回到策略。
- **把 `exec_algorithm_params` 的值写成数字。** 参数是字符串到字符串的映射，算法自己解析。
- **以为 `Type::default()` 和 `Type::builder().build()` 一定相同。** 它们是两条独立的构造路径。
:::

## 本章结论

`DataActor`、`Strategy`、`ExecutionAlgorithm` 共用同一个 `DataActorCore` 和同一套生命周期：Actor 只收数据、发信号，策略在此之上能下单和持仓，执行算法则处理带 `exec_algorithm_id` 的订单，把它拆成以“主单号-E序号”命名的子单，子单仍属于发单的策略。组件之间的轻量通信用信号或自定义数据，走总线的通用路由，不出进程。配置结构体用确定类型承载必须有值的字段，用 `Option` 承载语义各异的可选字段，默认值来自建造者或 `Default` 两条路径；日志则由专门的线程写出，不阻塞核心。

## 检查理解

1. 价差监控用 `publish_signal("spread", "0.12".to_string(), UnixNanos::default())` 发了一个信号，策略那边应该订阅什么、在哪个回调里收？收到的信号 `ts_event` 是多少？

   <details><summary>参考答案</summary>

   策略在 `on_start` 里调用 `subscribe_signal("spread")`，在 `on_signal` 里收到 `Signal`，名字是 `spread`、值是字符串 `"0.12"`。因为传入的 `ts_event` 是 0，发布时用当前时间代替，所以 `ts_event` 和 `ts_init` 都是发布那一刻的组件时钟时间。信号的数据类型名是 `SignalSpread`。

   </details>

2. 主线例子里如果主单是 `0.00004 ETH`、间隔数仍是 6，TWAP 会怎样？

   <details><summary>参考答案</summary>

   每份数量是 `0.00004 ÷ 6 ≈ 0.0000066`，按 5 位小数向零截断后是 `0.00000`，小于数量增量 `0.00001`。算法记一条警告“Submitting for entire size”，不再拆分，直接把整张主单提交。

   </details>

3. TWAP 的第三份子单被风控拒绝，策略会在哪个回调里知道？这张被拒的子单叫什么？

   <details><summary>参考答案</summary>

   子单的策略 ID 是发单策略，所以订单事件发布在这个策略的主题上，策略在 `on_order_denied`（以及 `on_order_event`）里收到。子单号是主单号加 `-E3`，例如 `O-20200814-100000-001-001-1-E3`。

   </details>

## 参考资料

- 官方文档：[Actors](https://nautilustrader.io/docs/latest/concepts/actors/) · [Execution](https://nautilustrader.io/docs/latest/concepts/execution/) · [Configuration](https://nautilustrader.io/docs/latest/concepts/configuration/) · [Logging](https://nautilustrader.io/docs/latest/concepts/logging/) · [Write a Rust actor](https://github.com/nautechsystems/nautilus_trader/blob/develop/docs/how_to/write_rust_actor.md)
- 源码：[`crates/common/src/actor/`](https://github.com/nautechsystems/nautilus_trader/tree/develop/crates/common/src/actor) · [`crates/common/src/macros.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/common/src/macros.rs) · [`crates/common/src/signal.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/common/src/signal.rs) · [`crates/trading/src/algorithm/`](https://github.com/nautechsystems/nautilus_trader/tree/develop/crates/trading/src/algorithm) · [`crates/common/src/logging/`](https://github.com/nautechsystems/nautilus_trader/tree/develop/crates/common/src/logging)
- 配图由 `scripts/generate-nautilus-trader-figures.py` 生成。

第二部分到这里结束。第三部分把视线从组件移到组件所在的内核：先看把这一切组装起来的 [第 14 章：NautilusKernel](./kernel.md)。
