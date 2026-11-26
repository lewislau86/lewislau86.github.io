---
title: "第 8 章：事件与事件溯源"
description: NautilusTrader 的四类事件（订单、仓位、账户、时间）各有哪些、共享哪些字段、发布到哪些主题；一笔成交怎样串成一条事件因果链；订单和账户怎样由事件历史重建；事件存储怎样在总线上抓取状态变化、怎样写成运行文件、崩溃后怎样封存，以及缓存回放能做什么、还不能做什么。
---

# 第 8 章：事件与事件溯源

[全书目录](./index.md) · [上一章](./accounts.md) · [下一章](./rust-strategy.md)

::: tip 本章学习目标
能列出四类事件和订单事件的 19 种类型，知道它们共享哪些字段、发布到哪些主题；能写出一笔成交之后按顺序发生的全部事件；理解“订单和账户是事件的折叠”在源码里是什么意思；知道事件存储抓什么、怎样写、崩溃后怎样处理、回放能恢复什么，以及它目前还不是实盘重启的路径。

**源码版本：** `develop` 分支，提交 `364254f`（2026-11-18）。事件类型在 `crates/model/src/events/`，时间事件在 `crates/common/src/timer.rs`，主题名在 `crates/common/src/msgbus/switchboard.rs`，事件存储在 `crates/event_store/`，内核接入在 `crates/system/src/event_store.rs`。

**对应官方文档：** [Events](https://nautilustrader.io/docs/latest/concepts/events/) · [Event Sourcing](https://nautilustrader.io/docs/latest/concepts/event_sourcing/)
:::

第 5～7 章分别讲了订单、仓位、账户，每一章都在说“它随事件变化”。这一章把事件本身放到台前：一共有哪些事件，一笔成交之后它们按什么顺序出现，以及 NautilusTrader 怎样把这些事件记下来，在需要时重建状态。第 10 章讲的是事件怎样送到策略的回调，这里讲事件是什么、从哪里来、到哪里去。

主线例子：策略持有多 1 ETH（NETTING 仓位），挂一张 `SELL 1 ETH @ 430.00` 的限价单平仓，交易所接受后分两次成交，先 0.4 后 0.6。

## 1. 四类事件 {#categories}

| 类别 | 类型 | 谁产生 |
| :--- | :--- | :--- |
| 订单 | `OrderEventAny` 的 19 种 | 下单工厂、风控、执行客户端（适配器）、本地仿真器 |
| 仓位 | `PositionOpened`、`PositionChanged`、`PositionClosed`、`PositionAdjusted` | 执行引擎 |
| 账户 | `AccountState` | 执行客户端（交易所上报）或账户管理器（本地计算） |
| 时间 | `TimeEvent` | 时钟（计时器和定时提醒） |

订单事件的 19 种按生命周期可以分成五组（`crates/model/src/events/order/any.rs`）：

- 创建与本地：`Initialized`、`Denied`、`Emulated`、`Released`；
- 提交与确认：`Submitted`、`Accepted`、`Rejected`；
- 改撤单：`PendingUpdate`、`PendingCancel`、`ModifyDenied`、`ModifyRejected`、`CancelDenied`、`CancelRejected`、`Updated`；
- 结束：`Canceled`、`Expired`、`Triggered`；
- 成交：`Filled`、`FillVoided`。

（`Triggered` 并不结束订单，只是表示触发类订单已被触发，归在这里是因为它和到期、撤销一样由交易所单方面决定。）每种事件怎样推动状态机，第 5 章第 3 节已经讲过。

所有订单事件共享一组字段：`trader_id`、`strategy_id`、`instrument_id`、`client_order_id`、事件自己的 `event_id`（UUID4）、`ts_event`、`ts_init`，以及一个布尔值 `reconciliation`，表示这个事件是对账时合成出来的，而不是交易所实时推送的（第 34 章）。交易所相关的事件还带 `venue_order_id` 和 `account_id`。成交事件最丰富：

```rust
// 节选自 crates/model/src/events/order/filled.rs
pub struct OrderFilled {
    pub trader_id: TraderId,
    pub strategy_id: StrategyId,
    pub instrument_id: InstrumentId,
    pub client_order_id: ClientOrderId,
    pub venue_order_id: VenueOrderId,
    pub account_id: AccountId,
    pub trade_id: TradeId,
    pub order_side: OrderSide,
    pub order_type: OrderType,
    pub last_qty: Quantity,
    pub last_px: Price,
    pub currency: Currency,
    pub liquidity_side: LiquiditySide,
    pub event_id: UUID4,
    pub ts_event: UnixNanos,
    pub ts_init: UnixNanos,
    pub reconciliation: bool,
    pub position_id: Option<PositionId>,   // 执行引擎处理时填入
    pub commission: Option<Money>,
    pub causation_id: Option<UUID4>,       // 拆分反手成交时指向原成交
    // …
}
```

时间事件很简单：`TimeEvent { name, event_id, ts_event, ts_init }`，`name` 是计时器的名字。第 11 章的时间 K 线就是靠一个名为 `TIME_BAR_{bar_type}` 的计时器产生的时间事件驱动的。

## 2. 事件发布到哪里 {#topics}

事件经消息总线发布，主题名由 `switchboard.rs` 统一生成：

| 主题 | 内容 | 订阅者 |
| :--- | :--- | :--- |
| `events.order.{strategy_id}` | 这个策略的订单事件 | 策略（注册时自动订阅）、组合 |
| `events.position.{strategy_id}` | 这个策略的仓位事件 | 策略、组合 |
| `events.account.{account_id}` | 账户状态 | 需要监听账户变化的组件（由组合发布） |
| `events.order_filled.{instrument_id}` 等 | 按品种细分的订单事件 | 需要按品种监听的组件 |

第 10 章讲过，`Trader` 注册策略时会订阅前两个主题；组合（Portfolio）用通配符 `events.order.*`、`events.position.*` 以优先级 10 订阅，所以组合总是先于策略看到同一个事件。按品种细分的主题有一整组（`events.order_submitted.*`、`events.order_canceled.*`、`events.order_filled.*` 等），例如执行引擎处理完一笔成交后，还会把它发布到 `events.order_filled.{instrument_id}`。

## 3. 主线例子：一张平仓单的事件链 {#chain}

把主线例子的事件按发生顺序排出来（省略风控和执行引擎之间的命令传递）：

| 序 | 事件 | 发布主题 | 状态变化 |
| :--- | :--- | :--- | :--- |
| 1 | `OrderSubmitted` | `events.order.S` | 订单 `SUBMITTED` |
| 2 | `OrderAccepted` | `events.order.S` | 订单 `ACCEPTED`；账户冻结 1 ETH |
| 3 | `OrderFilled` 0.4 @ 430.00 | `events.order.S` | 订单 `PARTIALLY_FILLED` |
| 4 | `PositionChanged` | `events.position.S` | 仓位多 1 → 多 0.6 |
| 5 | `AccountState` | `events.account.A` | 余额更新 |
| 6 | `OrderFilled` 0.6 @ 430.00 | `events.order.S` | 订单 `FILLED` |
| 7 | `PositionClosed` | `events.position.S` | 仓位 `FLAT` |
| 8 | `AccountState` | `events.account.A` | 余额更新，冻结归零 |

`S` 是策略 ID，`A` 是账户 ID。第 3、4 两步的顺序来自执行引擎处理成交的方式（`crates/execution/src/engine/mod.rs` 的 `handle_order_fill`）：先把成交应用到缓存里的订单，再决定仓位 ID、更新或创建仓位并写进缓存，然后发布订单事件，最后发布仓位事件。所以策略在 `on_order_filled` 里读缓存时，仓位已经是更新后的样子（第 10 章第 3 节）。

账户状态什么时候出现，取决于账户是交易所上报还是本地计算（第 7 章第 5 节）：本地计算时由账户管理器在订单和成交事件之后生成，交易所上报时由适配器在收到推送时生成，时机不一定紧跟成交。

![一笔成交的事件链和事件存储：上半是成交从适配器进入执行引擎，依次更新订单、仓位并发布订单、仓位、账户事件；下半是总线上的抓取点把这些消息去重后交给写入线程，分配序号写进按运行划分的文件](/nautilus-trader/figures/event-chain.svg)

怎么读这张图：上半是“事件怎样产生和传播”，下半是“事件怎样被记下来”。两半在消息总线上相交：抓取点挂在总线的派发路径上，和下游处理器看到的是同一个消息。

### 3.1 从仓位找回订单

事件里的 ID 把订单和仓位连在一起。官方文档给了三个常用的导航：`cache.orders_for_position(position_id)` 找出给这个仓位贡献过成交的全部订单；`cache.position_for_order(client_order_id)` 从订单找到它所在的仓位；`position.opening_order_id` 直接记着开仓的那张单。主线例子里，平仓单的 `client_order_id` 会记在仓位的 `closing_order_id` 上。

## 4. 状态是事件的折叠 {#event-sourced}

订单、仓位、账户这三种状态对象都保存着自己的事件历史，并且可以从事件历史重建：

- 订单的 `OrderCore` 有 `events: Vec<OrderEventAny>`，每次 `apply(event)` 先过状态机检查，再修改字段，最后把事件追加进历史。`OrderAny::from_events(events)`（`orders/any.rs`）用第一条 `OrderInitialized` 构造订单，再依次应用后面的事件，得到和原来一样的订单。
- 仓位的 `events` 是本轮的全部 `OrderFilled`，另有 `replay_events` 记录包括成交撤销在内的完整回放序列。成交撤销时，仓位会用剩下的成交重新折叠一遍（第 6 章）。
- 账户的 `BaseAccount.events` 是全部 `AccountState`，`AccountAny::from_events` 由它重建账户。

这就是附录第 3 节说的“订单是状态机加事件溯源”。它带来的好处是，任何时刻的状态都能解释成“从初始事件开始，依次发生了这些事”；代价是事件历史会一直增长，长期运行的节点需要考虑缓存的清理策略（第 16 章）。

## 5. 事件存储：把状态变化记成文件 {#event-store}

单个对象的事件历史在内存里，进程退出就没了。事件存储（`crates/event_store/`）把整个系统的状态变化写进磁盘，官方文档的定位是：事件存储回答“系统是怎样走到这一步的”，缓存只回答“现在是什么”。它是可选的：内核构建时传入 `EventStoreFactory` 才会打开（`LiveNodeBuilder::with_event_store`，或 `LiveNodeConfig` 的 `event_store` 配置），不传就没有。

### 5.1 抓什么

抓取发生在消息总线的派发边界上，抓的是“改变状态的消息”：交易命令（提交、改单、撤单）、数据订阅命令、触发的时间事件、生成的订单、仓位、账户事件、对账前交易所发来的原始执行报告和对账合成的事件、影响状态的数据请求与响应，以及运行的开始和结束标记 `RunStarted`、`RunEnded`。行情本身不抓，留在数据目录里（第 25 章）。

同一个消息常常经过总线不止一次：执行引擎把订单事件发给组合的端点，又发布到策略的主题；交易命令从策略经风控到执行引擎要跳几次。抓取适配器（`capture/adapter.rs` 的 `BusCaptureAdapter`）用一个有界窗口记住最近抓过的消息身份（事件 ID、命令 ID），重复的只记一次，保证回放时同一个事件不会被应用两遍。

### 5.2 怎样写

抓到的消息经一个有界通道交给写入线程 `EventStoreWriter`，由它分配每次运行内单调递增的序号 `seq`，按批提交到后端，后端确认落盘后推进“高水位”。默认参数在 `EventStoreConfig`（`crates/system/src/event_store.rs`）里：通道容量 10,000，每批最多 100 条或 5 毫秒，提交阻塞超过 250 毫秒（`halt_threshold`）就触发停止信号。

每条记录（`EventStoreEntry`）包含：`seq`、`ts_init`、`ts_publish`、主题、载荷类型、编码后的载荷、相关性头和一个对内容的哈希 `entry_hash`。回放的顺序只看 `seq`，时间戳只用来解释发生了什么。

后端默认是 `redb`，每次运行一个文件：`<base>/<instance_id>/<run_id>.redb`，里面是按 `seq` 存的记录、按订单号的二级索引、一份运行清单（运行 ID、上一次运行 ID、二进制哈希、各 crate 版本、特性开关、配置哈希、随机种子、高水位、状态），以及可选的缓存快照锚点。确定性仿真测试可以换成内存后端（`backend/memory.rs`），在仿真运行时里写入是同步的，`seq` 的顺序因此是确定的。

### 5.3 出错时怎样

官方文档用一个警告框强调了一条设计选择：抓取失败不会中断交易。写入阻塞超时或后端提交失败时，写入线程触发停止信号、丢弃未提交的那一批，抓取点记一条日志后停止记录，但消息照常送到处理器，交易继续，只是这次运行余下的部分不再被记录。没有任何组件因为停止信号而让交易员停下来。

下一次启动时，恢复流程会扫描上一次留下的、清单状态还是 `Running` 的运行文件，按落盘的尾部决定怎样封存：

| 落盘的尾部 | 封存状态 | 能否作为下一次运行的父运行 |
| :--- | :--- | :--- |
| 没有记录，或干净但没有 `RunEnded` | `CrashedRecovered` | 能 |
| 干净且以 `RunEnded` 结尾 | `Ended` | 不能 |
| 哈希不符、序号有缺口或结构损坏 | `Quarantined` | 不能 |

一个损坏的文件不会让交易员无法启动：被强杀后打不开的文件先尝试修复，仍然打不开就跳过并记错误，下次启动再试。

### 5.4 回放能做什么

配置 `replay_from_run_id` 后，内核会从一个已封存的运行恢复缓存：先加载缓存快照（如果有锚点），再按 `seq` 扫描锚点之后的记录，把支持的载荷直接应用到缓存上。支持的有合成的订单、仓位、账户事件，订单组，以及品种、报价、成交、资金费率、K 线的完整数据响应和品种收盘事件。回放时不发布到总线、不运行策略、不查询交易所、不做对账、不重新生成 ID、不重新设置时钟；时间事件和原始执行报告只作为查看记录。被隔离（`Quarantined`）的运行会被拒绝，回放还要求内核配置 `load_state=true`。

::: info 现状：设计契约和实现之间的差距
官方文档对事件存储的定位很坦率，读源码时要记住三点。第一，文档开头说明 API 仍在演进，把那一页当作设计契约来读。第二，相关性头（`correlation_id`、`causation_id`）的传递还不完整：只有数据请求和响应带了这些头，交易命令的生产者没有设置它们，订单、仓位、账户事件和执行报告没有提取器，所以大多数记录的头是空的；`OrderFilled.causation_id` 这样的字段在拆分反手成交时会设置，但没有进入记录头。第三，实盘重启仍然走“缓存快照加对账”的老路，事件存储的恢复要等抓取和回放覆盖了所有改变状态的路径之后，才会成为实盘重启的方式。
:::

::: warning 常见误区
- **以为一笔成交只产生一个事件。** 至少有订单事件和仓位事件，账户状态随后更新；反手时仓位事件有两个。
- **以为策略看到的事件顺序和组合一样早。** 组合以更高优先级订阅，先于策略处理同一事件。
- **以为事件存储默认就开着。** 要显式传入工厂或配置，否则没有任何运行文件。
- **以为抓取失败会让交易停下。** 设计上抓取失败只停记录，交易继续；运行在下次启动时被封存。
- **以为可以按 `correlation_id` 追踪任何一条订单链路。** 目前大多数记录的相关性头是空的。
- **以为崩溃后实盘重启会从事件存储恢复。** 实盘仍然是缓存快照加对账；事件存储的回放只恢复缓存，用于查看和分析。
:::

## 本章结论

NautilusTrader 的状态变化都表现为四类事件：19 种订单事件、4 种仓位事件、账户状态和时间事件，它们共享 ID 和两个时间戳，按策略、账户或品种发布到固定格式的主题上。一笔成交在执行引擎里先更新订单、再更新仓位，然后依次发布订单事件和仓位事件，账户状态随后更新。订单、仓位、账户都保存自己的事件历史，可以由事件重建。事件存储把整个系统改变状态的消息按序号写进按运行划分的文件，抓取失败不打断交易，崩溃的运行在下次启动时被封存，回放可以恢复缓存；但相关性头尚不完整，实盘重启也还没有改走这条路。

## 检查理解

1. 主线例子里，如果平仓单一次成交 1.6 ETH（原仓位多 1），会发布哪些仓位事件？

   <details><summary>参考答案</summary>

   执行引擎会把这笔成交拆成平仓 1 和开仓 0.6 两笔（第 6 章第 4 节）。平仓部分让仓位归零，发布 `PositionClosed`；NETTING 下先给已平的一轮做快照，再用同一个 ID 开仓 0.6 空，发布 `PositionOpened`。订单事件只有一个 `OrderFilled`，开仓部分的成交是拆出来的，带着指向原成交的 `causation_id`。

   </details>

2. 事件存储的写入线程因为磁盘满而提交失败。交易会怎样？下次启动时这个运行文件会被怎样处理？

   <details><summary>参考答案</summary>

   写入线程触发停止信号、丢弃未提交的那一批，抓取点停止记录，但消息照常送达处理器，交易继续，只是余下的部分不再记录。下次启动时，恢复流程发现这个运行文件的清单还是 `Running`，检查落盘的尾部：干净而没有 `RunEnded`，就封存为 `CrashedRecovered`，并可以作为新运行的父运行；若有哈希或序号问题，则封存为 `Quarantined`。

   </details>

3. 为什么事件存储要对抓到的消息去重？去重的依据是什么？

   <details><summary>参考答案</summary>

   同一个逻辑消息会多次经过总线：订单事件既发给组合的端点又发布到策略主题，交易命令从策略经风控到执行引擎要跳几次。如果每次都记，回放时同一个事件会被应用多遍。抓取适配器用一个有界窗口记住最近抓过的消息身份（事件 ID、命令 ID），重复出现的只记一次。

   </details>

## 参考资料

- 官方文档：[Events](https://nautilustrader.io/docs/latest/concepts/events/) · [Event Sourcing](https://nautilustrader.io/docs/latest/concepts/event_sourcing/)
- 源码：[`crates/model/src/events/`](https://github.com/nautechsystems/nautilus_trader/tree/develop/crates/model/src/events) · [`crates/common/src/msgbus/switchboard.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/common/src/msgbus/switchboard.rs) · [`crates/event_store/`](https://github.com/nautechsystems/nautilus_trader/tree/develop/crates/event_store) · [`crates/system/src/event_store.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/system/src/event_store.rs) · [`crates/execution/src/engine/mod.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/execution/src/engine/mod.rs)
- 配图由 `scripts/generate-nautilus-trader-figures.py` 生成。

第一部分到这里结束：值、品种、行情、订单、仓位、账户、事件构成了 NautilusTrader 的领域模型。第二部分换到写策略的人的角度，看怎样用这些概念写出一个策略。[第 9 章：Rust 策略的框架与运行机制](./rust-strategy.md)。
