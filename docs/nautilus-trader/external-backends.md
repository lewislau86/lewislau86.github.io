---
title: "第 36 章：外部后端：Redis、PostgreSQL 与外部消息流"
description: 缓存的数据库后端怎样在不阻塞核心线程的前提下写入：一条命令 channel、一个后台写任务、按间隔成批提交；Redis 里的键怎样组织，订单为什么存成事件列表；Redis 和 PostgreSQL 各能持久化什么；重启时恢复什么、不恢复什么。消息总线怎样把消息发布到 Redis 流（出站），又怎样从外部流收回再发布到本地总线（入站）；流的键、编码、类型过滤和自动修剪；一个“采集节点 + 策略节点”的例子。
---

# 第 36 章：外部后端：Redis、PostgreSQL 与外部消息流

[全书目录](./index.md) · [上一章](./book-sync.md) · [下一章](./dst.md)

::: tip 本章学习目标
能解释缓存的数据库写入为什么不会拖慢核心线程，以及“缓存写入成功”到底确认了什么；能说出 Redis 里一张订单存成什么样、重启后怎样恢复；知道 Redis 和 PostgreSQL 在持久化范围上的差别；能配置一个节点把行情发布到 Redis 流、另一个节点从流里接收；知道外部流的入站为什么不会重放启动前的消息。

**源码版本：** `develop` 分支，提交 `364254f`（2026-11-18）。Redis 缓存在 `crates/infrastructure/src/redis/cache.rs`（键和写入）与 `queries.rs`（读取），Redis 消息总线在 `redis/msgbus.rs`，PostgreSQL 在 `crates/infrastructure/src/sql/`，外部消息的编码和再发布在 `crates/common/src/msgbus/external/`，入站监听在 `crates/common/src/live/listener.rs`。

**对应官方文档：** [Cache](https://nautilustrader.io/docs/latest/concepts/cache/)（Database configuration 一节） · [Message Bus](https://nautilustrader.io/docs/latest/concepts/message_bus/)（External egress and ingress、External streams 两节）
:::

到目前为止，节点的一切都在进程的内存里：缓存是内存里的数据结构（第 16 章），消息总线只在进程内分发（第 15 章）。这一章看两种“外部后端”：一是给缓存接一个数据库，让订单、仓位、账户在重启后还能找回来；二是让消息总线把消息写到 Redis 流里，供别的进程或别的节点使用。两者都由 `nautilus-infrastructure` 这个 crate 提供，核心 crate 只定义接口，不依赖 Redis 或 PostgreSQL。

主线例子有两部分：一个策略节点给缓存接上本机的 Redis；另外有一个专门的“采集节点”订阅币安行情，把行情发布到名为 `binance` 的 Redis 流，策略节点从这个流接收行情。

## 1. 缓存后端：不阻塞的写入 {#cache-writes}

第 16 章说过，缓存接上后端以后，订单、仓位、账户、品种、组件状态的每次写入都会同时交给后端，而且是“尽力而为”的：写入失败只记日志，不影响缓存操作。这一节看它是怎样做到不阻塞的。

Redis 后端用两个连接，分工明确：

- **读连接**：由后端对象自己持有，用于同步的查询，比如启动时把所有数据读回来；
- **写连接**：由一个跑在全局运行时（第 29 章）上的**后台任务**持有。

核心线程上的缓存每次写入，只是把一条命令（插入、更新、删除）发进一个无界 channel，然后立刻返回。后台任务从 channel 里取命令，攒成一批，用 Redis 的管道（pipeline）一次提交。`CacheConfig.buffer_interval_ms` 控制攒多久：设为 100 毫秒，就是每 100 毫秒提交一次；不设或为 0，就是收到一条提交一条。PostgreSQL 后端的结构相同：一个无界 channel，一个后台任务。

所以“缓存写入成功”只说明内存里的修改完成了，不说明命令已经进入 channel，更不说明已经落盘。关闭时，同步的 `close` 和 `flush` 通过一个回复 channel 等后台任务确认完成；如果是在 Nautilus 运行时的工作线程上调用，会自动用 `block_in_place`（第 29 章第 3 节）避免卡住运行时。

## 2. Redis 里的键 {#keys}

所有键共用一个前缀：`trader-{trader_id}:`，配置了 `use_instance_id` 时再加上实例 ID。前缀之后按集合分开：

| 集合 | 例子 | Redis 类型 |
| --- | --- | --- |
| 品种、币种、合成品种 | `trader-TRADER-001:instruments:ETHUSDT.BINANCE` | 字符串 |
| 订单、仓位、账户 | `trader-TRADER-001:orders:O-20261120-…-1` | 列表 |
| 组件状态 | `trader-TRADER-001:strategies:EMACross-001` | 字符串 |
| 索引 | `trader-TRADER-001:index:orders_open` | 集合或哈希 |

订单、仓位、账户存成**列表**，每个元素是一个事件：订单每产生一个事件，后台任务就往它的列表末尾追加一条（`RPUSH`）。重启时把列表读出来，按事件依次重建对象，这正是第 8 章“订单由事件重建”的另一个用处。索引存成集合（比如所有未结订单的 ID）或哈希（比如订单到仓位的映射），恢复时不必扫描所有订单就能重建第 16 章的那些索引。值的编码由 `CacheConfig.encoding` 决定，可以是 JSON 或 MessagePack。

## 3. 能持久化什么，恢复什么 {#scope}

两个后端的范围不同：

| 数据 | Redis | PostgreSQL |
| --- | --- | --- |
| 订单、仓位、账户、品种、组件状态 | 是 | 是 |
| 报价、成交、K 线 | 否 | 是（`save_market_data`） |
| 希腊值、收益率曲线 | 否 | 是 |
| 订单簿、资金费率 | 否 | 否 |

对不支持的类型，打开 `save_market_data` 后每次写入都会记一条错误日志，数据只留在内存里，所以用 Redis 时应该关掉它。PostgreSQL 需要先用 `nautilus database init` 建表；它按交易员隔离订单、仓位、账户这些交易数据，品种、行情这类参考数据则在多个交易员之间共享。

**启动恢复**（`load_cache = true`，默认）读回已经成功持久化的通用数据、币种、品种、合约收盘、合成品种、账户、订单和仓位。不恢复的是有界的行情历史和进程的运行状态。后端也不是完整的事件档案，多个节点即使共用一个数据库，也各自有自己的内存缓存，不会互相同步。所以实盘重启时，缓存恢复之后还要做一次对账（第 34 章）：缓存给出“上次退出时以为的状态”，对账给出“交易所现在的真实状态”。

## 4. 消息总线：出站 {#egress}

给消息总线配置一个外部后端后，每次**发布**（publish）时，消息先照常分发给进程内的订阅者，然后被序列化成一条 `BusMessage` 记录交给出站接口：

- `topic`：内部发布用的主题，比如 `data.quotes.BINANCE.ETHUSDT`；
- `type`：负载的类型名，比如 `QuoteTick`；
- `encoding`：编码，JSON、MessagePack，或者对行情数据用 SBE；
- `payload`：序列化后的字节。

Redis 的出站实现和缓存一样：消息进一个无界 channel，一个后台任务攒批后用 `XADD` 写进 Redis 流。出站调用不能阻塞核心线程，有界的出站实现在队列满时直接丢弃，而不是让交易循环等它。

**流的键**默认是 `trader-{trader_id}:{streams_prefix}`；`use_trader_prefix`、`use_trader_id`、`use_instance_id` 三个开关控制前面几段，`streams_prefix` 默认是 `streams`。`stream_per_topic = true` 时每个主题一个流，否则所有消息写进同一个流、主题作为字段保存。

几个常用的控制项：

- **类型过滤** `types_filter`：列出的类型不发布到外部，比如把高频的 `QuoteTick` 排除掉，避免流被淹没；
- **自动修剪** `autotrim_mins`、`autotrim_maxlen`：按时间窗口或条数修剪流，Redis 至少每分钟修剪一次，所以条目可能比窗口多留约一分钟；按时间修剪用到 Redis 6.2 的 `MINID`，这也是 Redis 的最低版本要求；
- **编码** `encoding` 和 `encoding_market_data`：比如其余消息用 MessagePack、行情用 SBE。

只有能序列化的类型会被发布：行情、品种、账户状态、订单事件、仓位事件、组合快照、自定义数据等。配置了外部流（下一节）时，订阅命令、交易命令、数据请求和响应、执行报告也会发布出去。

## 5. 消息总线：入站 {#ingress}

反方向，节点可以从外部流读消息，再发布到本地总线上。配置 `MessageBusConfig.external_streams = ["binance"]` 后，Redis 后端会启动一个读取任务，用 `XREAD` 读这些流，把每条记录交给节点。第 30 章的事件循环里有一个“外部消息总线入站”分支，取出消息后：

1. 先交给用 `add_stream_processor` 注册的处理函数（如果有）；
2. 解码，按原来的主题在本地总线上再发布一次，但**不会**再转发出去，避免循环；
3. 账户状态不直接发布，而是交给 Portfolio 的账户端点（第 22 章），由它更新缓存后再发布。

如果消息是行情，而数据引擎里把对应的客户端声明为**外部客户端**（`LiveDataEngineConfig.external_clients`，第 18 章），数据引擎会像处理本地行情一样写缓存、维护订单簿，而不是只做转发。同时，数据引擎不会把这个客户端的订阅命令发给任何本地客户端，因为数据由外部流提供。

有一个限制要注意：内置的 Redis 入站从**当前时刻**开始读每个流，节点启动之前已经在流里的消息不会被重放。外部流提供的是实时转发，不是一个消费者组式的积压队列。需要启动前的历史时，用缓存恢复或事件存储（第 8 章）。

主线例子的两个节点：

```rust
// 采集节点：订阅币安行情，发布到名为 binance 的流
let msgbus = MessageBusConfig {
    use_trader_id: false, use_trader_prefix: false, use_instance_id: false,
    streams_prefix: "binance".to_string(),      // 流的键就是 binance
    stream_per_topic: false,
    autotrim_mins: Some(30),
    ..Default::default()
};
let node = LiveNode::builder(trader_id, Environment::Live)?
    .with_msgbus_config(msgbus)
    .with_external_msgbus_factory(Box::new(RedisMessageBusConfig::default()))
    .build()?;

// 策略节点：从 binance 流接收，把 BINANCE_EXT 当作外部数据客户端
let data_engine = LiveDataEngineConfig {
    external_clients: Some(vec![ClientId::from("BINANCE_EXT")]),
    ..Default::default()
};
let msgbus = MessageBusConfig {
    external_streams: Some(vec!["binance".to_string()]),
    ..Default::default()
};
```

策略节点里的策略照常订阅 `ETHUSDT.BINANCE` 的报价，指定客户端 `BINANCE_EXT`；订阅命令不会发出去，报价从 Redis 流进来，经数据引擎写缓存后交给策略。采集节点让流的键简单固定（三个开关都关掉，键就是 `binance`），消费者才能直接用这个名字订阅。

![外部后端的两条路径：上面是缓存后端，核心线程上的缓存把写命令发进 channel，后台任务按间隔成批用管道写入 Redis 或 PostgreSQL，启动时经读连接恢复；下面是消息总线，采集节点的总线在本地分发后把 BusMessage 交给出站任务，用 XADD 写进 Redis 流，策略节点的入站任务用 XREAD 读取，经事件循环的外部消息分支在本地总线上再发布](/nautilus-trader/figures/external-backends.svg)

怎么读这张图：上下两条路径都遵循同一个原则：核心线程只往 channel 里放东西，所有 I/O 在全局运行时的后台任务里做。下面的路径跨了两个进程，中间的 Redis 流是它们唯一的连接。

::: warning 常见误区
- **以为缓存写入成功就已经落盘。** 它只确认了内存修改；写入在后台成批进行，失败只记日志。
- **用 Redis 后端又打开 `save_market_data`。** Redis 不存行情，每次写入都会记错误日志。
- **以为恢复了缓存就不需要对账。** 缓存只是“上次以为的状态”，重启后必须对账。
- **以为几个节点共用一个 Redis 就能共享缓存。** 每个节点各有自己的内存缓存，后端不同步它们。
- **期望消费节点启动后能收到之前流里的消息。** 内置的 Redis 入站从当前时刻开始读。
- **采集节点保留默认的流键前缀，消费节点用 `binance` 订阅。** 两边的键对不上；要么关掉前缀，要么消费端写完整的键。
- **没有把外部客户端声明进数据引擎。** 外部来的行情只会被直接转发，不会写缓存、维护订单簿。
:::

## 本章结论

缓存后端和消息总线后端都遵循同一个模式：核心线程把命令或消息放进无界 channel 后立刻返回，全局运行时上的后台任务成批地写入 Redis 或 PostgreSQL。Redis 的缓存键以 `trader-{trader_id}:` 开头，订单、仓位、账户存成事件列表，重启时按事件重建；Redis 不存行情，PostgreSQL 可以存报价、成交、K 线。恢复的是参考数据和交易对象，不是行情历史，也替代不了对账。消息总线的出站把发布的消息序列化成 `BusMessage`，用 `XADD` 写进 Redis 流，可以按类型过滤、自动修剪；入站用 `XREAD` 从当前时刻开始读外部流，在本地总线上再发布，声明为外部客户端的行情会像本地行情一样进入数据引擎。

## 检查理解

1. `buffer_interval_ms = 100`。策略在某一刻提交了一张单，随即进程被 `kill -9`。重启后缓存里有这张单吗？

   <details><summary>参考答案</summary>

   不一定。订单的初始化事件进入了写命令 channel，但后台任务每 100 毫秒才提交一批；如果在提交之前进程被杀，这条事件就丢了。缓存恢复后没有这张单，但交易所那边可能已经收到了它。启动对账会从交易所的订单报告里发现它，作为外部订单新建（如果策略认领了这个品种，就归这个策略）。所以持久化缩小了需要对账的范围，但不能替代对账。

   </details>

2. 你想用一个采集节点把 10 个品种的成交和 K 线发布出去，供 3 个策略节点使用，但不想发布报价。应该怎样配置采集节点？

   <details><summary>参考答案</summary>

   给采集节点配置 Redis 消息总线后端；把 `types_filter` 设为 `["QuoteTick"]`，排除报价；关掉 `use_trader_prefix`、`use_trader_id`、`use_instance_id`，把 `streams_prefix` 设成一个固定的名字，方便消费节点订阅；设置 `autotrim_mins` 防止流无限增长。3 个策略节点都在 `external_streams` 里写这个名字，并把对应的客户端 ID 声明为数据引擎的外部客户端。

   </details>

3. 策略节点在 10:00 启动，采集节点从 9:00 起一直在往流里写 K 线。策略需要过去一小时的 K 线来预热指标，能从流里拿到吗？

   <details><summary>参考答案</summary>

   不能。内置的 Redis 入站从当前时刻开始读，9:00 到 10:00 的条目不会被重放。预热应该用历史数据请求（第 18 章），由数据目录（第 25 章）或交易所的历史接口提供。

   </details>

## 参考资料

- 官方文档：[Cache](https://nautilustrader.io/docs/latest/concepts/cache/) · [Message Bus](https://nautilustrader.io/docs/latest/concepts/message_bus/)
- 源码：[`crates/infrastructure/src/redis/cache.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/infrastructure/src/redis/cache.rs) · [`crates/infrastructure/src/redis/msgbus.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/infrastructure/src/redis/msgbus.rs) · [`crates/infrastructure/src/sql/`](https://github.com/nautechsystems/nautilus_trader/tree/develop/crates/infrastructure/src/sql) · [`crates/common/src/msgbus/external/mod.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/common/src/msgbus/external/mod.rs) · [`crates/common/src/live/listener.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/common/src/live/listener.rs)
- 配图由 `scripts/generate-nautilus-trader-figures.py` 生成。

第五部分讲的这些异步机制，网络、计时器、重连、恢复，最难的是测试：真实时间、真实网络都无法重现。最后一章看 NautilusTrader 怎样让异步代码的执行可以重放。[第 37 章：确定性仿真测试](./dst.md)。
