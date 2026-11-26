---
title: "第 11 章：K 线聚合器"
description: NautilusTrader 怎样把逐笔成交、报价合成 K 线：BarType 字符串怎样决定数据来源，subscribe_bars 之后 DataEngine 建了什么、订了什么，BarBuilder 怎样累计开高低收，按笔数、成交量、成交额、失衡、连续、Renko、时间七种关闭规则各自怎样实现，时间 K 线的定时器、时间戳与配置项，组合 K 线和历史聚合，以及一次用真实成交数据跑出来的实验。
---

# 第 11 章：K 线聚合器

[全书目录](./index.md) · [上一章](./callbacks.md) · [下一章](./indicators.md)

::: tip 本章学习目标
能看懂并写出任意一种 `BarType` 字符串，知道它决定了 K 线从成交、报价还是更小的 K 线合成；能说清 `subscribe_bars` 之后 `DataEngine` 建了哪个聚合器、向数据客户端订了什么、一笔成交怎样一路变成 `on_bar`；知道七种聚合器各自什么时候关闭一根 K 线，时间 K 线的时间戳和空 K 线怎么处理；能用回测验证自己的 K 线配置。

**源码版本：** `develop` 分支，提交 `364254f`（2026-11-18）。聚合器在 `crates/data/src/aggregation.rs`，接线在 `crates/data/src/engine/bar.rs` 和 `engine/handlers.rs`，配置在 `engine/config.rs`。官方说明在 `docs/concepts/data/index.md` 的 “Bars and aggregation” 一节。

**对应官方文档：** [Data](https://nautilustrader.io/docs/latest/concepts/data/) 的 Bars and aggregation 一节
:::

K 线和指标是策略最常用的两样输入。先回答一个常见的问题：它们是不是在 Rust 里算好、Python 直接调用？前半句对，后半句要改一下。v2 里 K 线完全在 Rust 的 `DataEngine` 里合成，但 Python 并不“调用”聚合器，Python 层甚至没有任何聚合器类（`_libnautilus` 的存根里找不到 `BarAggregator` 或 `BarBuilder`）。不管策略用 Rust 还是 Python 写，你只做一件事：用一个 `BarType` 订阅 K 线。引擎替你建聚合器、订源数据、逐笔累计，合成好的 K 线经消息总线回到你的 `on_bar`。Python 策略只在最后一步拿 GIL 被回调。

指标是另一回事，放在第 12 章：指标挂在策略上，由框架在 `on_bar` 之前更新，Python 策略注册的指标每次更新都要穿过一次语言边界。

## 1. BarType：一个字符串决定 K 线从哪来 {#bar-type}

订阅 K 线时传的是一个 `BarType`。它的字符串格式有两种：

```text
标准 K 线：{instrument_id}-{step}-{aggregation}-{price_type}-{INTERNAL|EXTERNAL}
组合 K 线：{instrument_id}-{step}-{aggregation}-{price_type}-INTERNAL@{step}-{aggregation}-{INTERNAL|EXTERNAL}
```

拿 `ETHUSDT.BINANCE-1-MINUTE-LAST-INTERNAL` 拆开看：

| 部分 | 这里的值 | 含义 |
| :--- | :--- | :--- |
| 品种 | `ETHUSDT.BINANCE` | `InstrumentId`，合成时要从缓存里取它的价格、数量精度 |
| 步长 | `1` | 关闭条件的阈值：1 分钟、250 笔、100 个单位的量 |
| 聚合方式 | `MINUTE` | 按什么关闭，见第 5 节 |
| 价格类型 | `LAST` | `LAST` 用成交，`BID`、`ASK`、`MID` 用报价 |
| 来源 | `INTERNAL` | 本地合成；`EXTERNAL` 表示交易所或数据商已经合成好 |

最后两项决定了 K 线的数据来源，这是整章最重要的一条规则：

- `EXTERNAL`：引擎不合成，把订阅转给数据客户端，收到什么就发布什么。
- `INTERNAL` 且没有 `@`：本地合成。`LAST` 订阅成交 `TradeTick`，`BID`、`ASK`、`MID` 订阅报价 `QuoteTick`。
- `INTERNAL` 且带 `@`：用 `@` 后面那种更小的 K 线合成，例如 `…-5-MINUTE-LAST-INTERNAL@1-MINUTE-EXTERNAL` 用交易所给的 1 分钟 K 线合成 5 分钟。`@` 后面也可以是 `INTERNAL`，这样就能一层层往上叠：成交 → 1 分钟 → 5 分钟 → 1 小时。

时间类步长有校验：`MILLISECOND` 的步长要整除 1000，`SECOND`、`MINUTE` 要整除 60，`HOUR` 要整除 24，`MONTH` 要整除 12。步长等于上一级单位时要换成上一级，写 `1-HOUR` 而不是 `60-MINUTE`（`12-MONTH` 例外）。

::: info 组合 K 线回来时没有 @
K 线发布到总线、写进缓存时都用标准类型（`bar_type.standard()`），`@` 后面的部分会被去掉。订阅 `…-5-MINUTE-LAST-INTERNAL@1-MINUTE-INTERNAL`，`on_bar` 里收到的 `bar.bar_type` 是 `…-5-MINUTE-LAST-INTERNAL`，从缓存取也要用这个标准类型。第 8 节的实验一开始就因为用带 `@` 的字符串做字典键，统计出来是 0 根。
:::

## 2. 订阅时：DataEngine 建了什么、订了什么 {#subscribe}

![K 线聚合的订阅与数据流](/nautilus-trader/figures/bar-aggregation-flow.svg)

图的上半部分是订阅时发生的事，按调用顺序走一遍。

第一步在策略这边。`subscribe_bars` 是 `DataActor` 的默认方法，Rust 策略和 Python 策略调用的是同一个实现（`crates/common/src/actor/data_actor.rs`）。它先在总线上登记一个处理器，主题用标准类型；再发一条 `SubscribeBars` 命令给 `DataEngine`：

```rust
// 节选自 DataActorCore::subscribe_bars（crates/common/src/actor/data_actor.rs）
for bar_type in &command.bar_types {
    let member = command.with_bar_types(*bar_type);
    let topic = get_bars_topic(bar_type.standard());   // "data.bars.{标准类型}"
    if self.add_bar_subscription(topic, handler.clone(), /* 命令 */) {
        acquired.push(*bar_type);
    }
}
if !acquired.is_empty() {
    self.send_data_cmd(DataCommand::Subscribe(SubscribeCommand::Bars(/* acquired */)));
}
```

第二步在 `DataEngine`。它按来源分流，`INTERNAL` 的 K 线自己合成，`EXTERNAL` 的才交给客户端（`engine/mod.rs` 里只把外部 K 线记进客户端的订阅意图）：

```rust
// crates/data/src/engine/bar.rs
pub(super) fn subscribe_bars(&mut self, cmd: &SubscribeBars) -> anyhow::Result<()> {
    match bar_type.aggregation_source() {
        AggregationSource::Internal => self.start_bar_aggregation(cmd)?,
        AggregationSource::External => { /* 交给客户端；合成品种不支持外部 K 线 */ }
    }
    Ok(())
}
```

第三步，`start_bar_aggregation` 建聚合器。聚合器存在 `bar_aggregators` 表里，键是“标准 BarType + 请求 ID”，实时订阅的请求 ID 是 `None`。所以同一种 K 线不管几个策略订阅，引擎里只有一个聚合器；已经在跑就直接复用。建之前要从缓存取品种，拿价格精度和数量精度，品种不在缓存里会报错 `no instrument found`。具体建哪种聚合器由 `create_bar_aggregator` 按聚合方式分派：时间类建 `TimeBarAggregator`，其余按 `TICK`、`VOLUME`、`VALUE`、三种 `_IMBALANCE`、三种 `_RUNS`、`RENKO` 一一对应。

第四步，`subscribe_bar_aggregator_handlers` 把聚合器接到源数据的主题上，优先级是 5：

| K 线类型 | 订阅的主题 | 处理器 |
| :--- | :--- | :--- |
| 带 `@` 的组合 K 线 | `data.bars.{源 K 线}` | `BarBarHandler` |
| `LAST` | `data.trades.{venue}.{symbol}` | `BarTradeHandler` |
| `BID` / `ASK` / `MID` | `data.quotes.{venue}.{symbol}` | `BarQuoteHandler` |

处理器只持有聚合器的弱引用，聚合器停掉以后处理器自然失效。如果把失衡类或连续类聚合配成了报价，这里会打一条警告：这两类要看成交的主动方向，报价里没有，K 线不会正确产生。

第五步，向数据客户端订阅源数据：`LAST` 发 `SubscribeTrades`，报价类发 `SubscribeQuotes`，组合 K 线的源如果是 `EXTERNAL` 就发源 K 线的 `SubscribeBars`。最后 `setup_bar_aggregator` 给时间类聚合器接上引擎的时钟、启动定时器（第 6 节）。

退订是反过来的：主题上还有别的订阅者就什么都不做；最后一个订阅者走了，才停掉聚合器、取消定时器，并退订源数据。

## 3. 运行时：一笔成交怎样变成 on_bar {#runtime}

图的下半部分是运行时。一笔成交进来，`DataEngine` 先写缓存，再发布到 `data.trades.BINANCE.ETHUSDT`。总线按优先级从高到低派发（第 10 章）：聚合器的处理器是 5，策略是 0，所以聚合器先拿到这笔成交。

`BarTradeHandler` 调 `handle_trade`，默认实现就是把价格、数量、`ts_init` 交给 `update`；报价走 `handle_quote`，按价格类型取出买价、卖价或中间价和对应的量；组合 K 线走 `handle_bar`，把整根源 K 线交给 `update_bar`。`update` 里各聚合器先让 `BarBuilder` 累计（第 4 节），再判断关闭条件，满足了就生成一根 K 线，交给建聚合器时传进去的处理函数：

```rust
// crates/data/src/engine/dispatch.rs
pub(super) fn process_engine_bar(cache: &Rc<RefCell<Cache>>, validate_sequence: bool,
                                 publish: bool, bar: Bar) {
    if !validate_bar_sequence(cache, validate_sequence, &bar) { return; }  // 默认不检查
    if let Err(e) = cache.as_ref().borrow_mut().add_bar(bar) { log_error_on_cache_insert(&e); }
    if publish {
        msgbus::publish_bar(switchboard::get_bars_topic(bar.bar_type), &bar);
    }
}
```

K 线先写进缓存，再发布到 `data.bars.{标准类型}`。策略订阅时登记的闭包收到它，走第 10 章讲过的那条路：`handle_bar` 先更新注册在这种 K 线上的指标，组件不在 `RUNNING` 就丢弃，然后调用你的 `on_bar`。Python 策略在这一步拿 GIL，把 `Bar` 转成 Python 对象，按名字调用 `on_bar`；前面的累计、判断、生成都在 Rust 里完成，不碰 Python。

整条路是同步的，嵌套在那笔成交的派发里面。这带来一个容易忽略的顺序：凑满一根 K 线的那笔成交，策略先在 `on_bar` 里看到包含它的 K 线，然后才在 `on_trade_tick` 里看到这笔成交本身。

`validate_data_sequence` 打开时，`ts_event` 或 `ts_init` 比缓存里上一根同类 K 线还早的 K 线会被丢弃并打警告；默认关闭。

## 4. BarBuilder：每根 K 线的累加器 {#bar-builder}

所有聚合器内部都有一个 `BarAggregatorCore`，里面是一个 `BarBuilder`、一个生成后调用的处理函数、一个是否在运行的标志。`BarBuilder` 记录正在形成的这根 K 线：

| 字段 | 作用 |
| :--- | :--- |
| `open` / `high` / `low` / `close` | 开高低收，都是 `Option<Price>`，还没数据时为空 |
| `volume` / `count` | 累计成交量、累计笔数 |
| `ts_last` | 最近一次更新的 `ts_init` |
| `last_close` | 上一根 K 线的收盘价，用来补空 K 线 |
| `initialized` | 收到过第一笔数据没有 |

`update` 的逻辑一眼就能看完：

```rust
// 节选自 BarBuilder::update（crates/data/src/aggregation.rs）
if ts_init < self.ts_last { return; }        // 比上一笔还早的数据直接忽略
if self.open.is_none() {                      // 这根 K 线的第一笔
    self.open = Some(price);
    self.high = Some(price);
    self.low = Some(price);
    self.initialized = true;
} else {
    /* price 比 high 高就更新 high，比 low 低就更新 low */
}
self.close = Some(price);
self.volume = self.volume.add(size);
self.count += 1;
self.ts_last = ts_init;
```

`update_bar` 是组合 K 线用的版本，拿源 K 线的开高低收来更新。`build` 生成 K 线时，如果这段时间一笔数据都没有，开高低收全用 `last_close` 补，成交量为 0，这就是“平 K 线”；生成后 `reset` 清空开高低收、成交量和笔数，开始下一根。阈值类聚合器生成 K 线时调用 `build_now`，K 线的 `ts_event` 和 `ts_init` 都是最后一笔数据的 `ts_init`。

## 5. 七种关闭规则 {#aggregators}

![BarBuilder 与七种聚合器](/nautilus-trader/figures/bar-aggregators.svg)

各聚合器的区别只在 `update` 里怎样判断“这根 K 线该关了”。

<strong>按笔数</strong>（`TickBarAggregator`）。最简单：累计后 `count >= step` 就生成。

<strong>按成交量</strong>（`VolumeBarAggregator`）。一笔大单可能一次跨过阈值，它会被拆开：先拿刚好凑满当前 K 线的那部分，生成一根，剩下的放进下一根，循环到用完为止。所以每根量 K 线的成交量都正好等于步长。

```rust
// 节选自 VolumeBarAggregator::update
while size_update.non_zero() {
    let size_diff = step - self.core.builder.volume;     // 当前 K 线还差多少
    if size_update < size_diff {
        self.core.builder.update(price, size_update, ts_init);
        break;
    }
    self.core.builder.update(price, size_diff, ts_init);  // 只放进去差的那部分
    self.core.build_now_and_send();
    size_update = size_update - size_diff;                // 剩下的进下一根
}
```

<strong>按成交额</strong>（`ValueBarAggregator`），也叫美元 K 线。累计价格乘数量，到步长就生成，同样按比例拆单。拆出来的量不足最小数量单位时会被抬到最小单位，避免出现成交量为 0 的 K 线；合成组合 K 线时用源 K 线的 (高 + 低 + 收) / 3 当价格。

<strong>按失衡</strong>（`TickImbalance`、`VolumeImbalance`、`ValueImbalance`）。主动买的成交记正、主动卖的记负，分别按笔数、成交量、成交额累计，净值的绝对值到步长就生成。买卖互相抵消，所以平衡的市场里 K 线形成得慢，单边行情里快。

<strong>按连续</strong>（`TickRuns`、`VolumeRuns`、`ValueRuns`）。只数同一方向连续的成交，方向一变计数清零、正在形成的 K 线也重置，所以一根连续 K 线只包含那一段单边成交。

失衡和连续这两类都要成交的 `aggressor_side`，只能用 `LAST`。`aggressor_side` 是 `NoAggressor` 的成交只计入开高低收，不计入失衡或连续计数。

<strong>Renko</strong>（`RenkoBarAggregator`）。砖块大小 = 品种的 `price_increment` × 步长，ETHUSDT 的最小价位是 0.01，`50-RENKO` 就是 0.50 一块。价格离上一块的收盘超过一块，就生成一块：上涨砖开在旧收盘、收在旧收盘加一块，下跌反之。一次跳很远会连续生成多块。读源码时注意一个细节：同一次更新生成的多块砖，每块的成交量都记成这次累计的总量，而不是平分。

<strong>按时间</strong>（`TimeBarAggregator`）。关闭条件不在 `update` 里，而在时钟定时器上，下一节单独讲。

<strong>组合</strong>。组合不是一种新聚合器，而是给上面任一种聚合器换一个输入：源 K 线通过 `handle_bar` → `update_bar` 喂进来。官方文档的性能说明里提到，组合 K 线处理的是一根根源 K 线而不是每笔数据，所以比直接从成交合成大周期便宜。

## 6. 时间 K 线：定时器、时间戳和配置 {#time-bars}

时间 K 线不看数据决定何时关闭，而是在启动时向时钟登记一个定时器，名字是 `TIME_BAR_{bar_type}`，到点就调用 `build_bar`。

<strong>启动。</strong>`start_timer` 先按当前时间算出所在区间的开始和结束（`get_time_bar_bounds`），加上 `time_bars_build_delay`，然后登记定时器。分钟、小时这类固定长度的区间用周期定时器 `set_timer_ns`；月、年，以及时区不是 UTC 时的日、周，长度不固定，改用一次性的 `set_time_alert_ns`，每次触发后再算下一个边界。

<strong>到点。</strong>`build_bar` 只在两种情况下生成 K 线：收到过第一笔数据（`initialized`），并且这段时间有数据或者允许生成空 K 线。不管生成与否，这次的触发时间都成为下一根 K 线的开盘时间。

```rust
// 节选自 TimeBarAggregator::build_bar
if self.core.builder.initialized
    && (self.build_with_no_updates || self.core.builder.count > 0)
{
    let ts_init = event.ts_event;                 // ts_init 永远是触发时间
    let ts_event = if self.is_left_open {
        if self.timestamp_on_close { event.ts_event } else { self.stored_open_ns }
    } else {
        self.stored_open_ns                       // RIGHT_OPEN 总是用开盘时间
    };
    self.build_and_send(ts_event, ts_init);
}
self.stored_open_ns = event.ts_event;             // 收盘时间就是下一根的开盘时间
```

注意最后一个分支：区间类型是 `RIGHT_OPEN` 时，`ts_event` 总是开盘时间，`time_bars_timestamp_on_close` 不起作用。

这些行为由 `DataEngineConfig` 里的几个选项控制，对所有时间 K 线生效：

| 选项 | 默认 | 作用 |
| :--- | :--- | :--- |
| `time_bars_interval_type` | `LEFT_OPEN` | 区间左开右闭（不含开始、含结束）或 `RIGHT_OPEN` 左闭右开 |
| `time_bars_timestamp_on_close` | `True` | `ts_event` 用收盘时间；`False` 用开盘时间 |
| `time_bars_build_with_no_updates` | `True` | 没有数据的区间也生成一根平 K 线 |
| `time_bars_skip_first_non_full_bar` | `False` | 启动在区间中途时，跳过第一根不完整的 K 线 |
| `time_bars_build_delay` | `0` | 每个边界之后再延迟多少微秒生成 |
| `time_bars_origin_offset` | `{}` | 按聚合方式平移边界，单位纳秒 |
| `time_bars_time_zone` | `None` | 日及以上周期按哪个 IANA 时区对齐，默认 UTC |

`build_delay` 主要用在回测：边界时刻正好有数据时，延迟一点能让这些数据先进入 K 线，再触发生成。`origin_offset` 的例子：给 `DAY` 设 `34_200_000_000_000` 纳秒，日 K 线就在 UTC 09:30 切分；再配上 `time_bars_time_zone="America/New_York"`，就是每天纽约时间 09:30 收盘，跨夏令时也不会错位。单个订阅可以用 `params={"time_zone": "UTC"}` 覆盖时区，但共享同一个聚合器的订阅必须用同一个时区，否则报错 `Cannot reuse bar aggregator … with a different time zone`。

<strong>组合时间 K 线的顺序。</strong>5 分钟 K 线从 1 分钟 K 线合成时，10:05 这一刻两个定时器同时到点。如果 5 分钟先触发，就会漏掉 10:04–10:05 那根 1 分钟 K 线。引擎在 `connect_time_bar_sources` 里把 1 分钟聚合器登记为 5 分钟聚合器的 `timer_source`；5 分钟的定时器触发时，先检查源聚合器是不是也在这一刻到点，是就先让源生成，再生成自己。第 8 节的实验验证了这一点：59 根 5 分钟 K 线全部等于对应 5 根 1 分钟 K 线的汇总。

## 7. 历史 K 线：请求与预热 {#historical}

策略启动时常常要先用历史数据把指标喂热，再接实时 K 线。这里 v2 的接口和官方概念文档的示例有出入，按源码来。

`request_bars` 只接受标准类型，传组合类型会直接报错，错误信息给出了正确做法：

```rust
// crates/common/src/actor/data_actor.rs，DataActorCore::request_bars
anyhow::ensure!(
    bar_type.is_standard(),
    "Composite bar types are not supported for `request_bars`, was {bar_type}; \
     request aggregation via the `bar_types` params instead",
);
```

所以要“本地合成历史 K 线”，做法是请求源数据，并在 `params` 里带上要合成的 K 线类型：

```python
# 请求过去 30 分钟的成交，引擎边收边合成 1 分钟 K 线
self.request_trades(
    instrument_id,
    start=now - timedelta(minutes=30),
    params={
        "bar_types": ["ETHUSDT.BINANCE-1-MINUTE-LAST-INTERNAL"],
        "update_subscriptions": True,   # 合成完把状态交给实时聚合器
    },
)
```

`DataEngine` 看到 `bar_types` 参数，就为这个请求建一组历史模式的聚合器（`engine/bar.rs` 的 `prepare_request_bar_aggregators`）。历史模式和实时模式有三点不同：

- 每个时间聚合器有自己独立的 `VirtualClock`，跟着数据的时间戳往前推，不用引擎的时钟，所以历史数据再快也不会和实时定时器打架。
- 生成的 K 线只写缓存、不发布到总线（`process_engine_bar` 的 `publish` 为 `false`）。
- `update_subscriptions` 为 `True` 时，请求用的就是实时订阅的那个聚合器；请求还没结束时到达的实时数据先放进预热缓冲区，请求结束后按到达顺序回放，再切到实时。为 `False` 时请求有自己独立的聚合器，请求结束就清理掉。

带 `@` 的多层合成也可以这样请求：`bar_types` 里按顺序列出各层，引擎按“源在前、依赖在后”的顺序把它们串起来（`sources_before_dependents`）。

::: warning 回测里这条路走不通
在 `BacktestEngine` 里对模拟交易所调用 `request_trades` 会失败，日志是 `Data client BINANCE request failed`，本章实验里试过。回测引擎的数据是预先加载、按时间推送的，模拟数据客户端不提供历史请求；回测里要预热，就让回测从更早的时间开始，让指标在正式交易前自然喂热。历史请求主要用在实盘节点。
:::

## 8. 动手实验：一份成交数据，八种 K 线 {#experiment}

下面的实验在第 2 版开发分支（`364254f`）上实际跑过，环境是[从零编译](./build-from-source.md)得到的 Python 包。数据是仓库测试数据里的 `binance/ethusdt-trades.csv`：ETHUSDT 69,806 笔成交，从 2020-08-14 10:00:00.223 到 14:59:58.693（UTC），差不多 5 小时。一个不下单的策略同时订阅八种 K 线，只做计数：

```python
from collections import defaultdict
from nautilus_trader.model import BarType
from nautilus_trader.config import StrategyConfig
from nautilus_trader.trading import Strategy

SPECS = [
    "ETHUSDT.BINANCE-1-MINUTE-LAST-INTERNAL",
    "ETHUSDT.BINANCE-5-MINUTE-LAST-INTERNAL@1-MINUTE-INTERNAL",
    "ETHUSDT.BINANCE-250-TICK-LAST-INTERNAL",
    "ETHUSDT.BINANCE-100-VOLUME-LAST-INTERNAL",
    "ETHUSDT.BINANCE-50000-VALUE-LAST-INTERNAL",
    "ETHUSDT.BINANCE-100-TICK_IMBALANCE-LAST-INTERNAL",
    "ETHUSDT.BINANCE-20-TICK_RUNS-LAST-INTERNAL",
    "ETHUSDT.BINANCE-50-RENKO-LAST-INTERNAL",
]

class BarLab(Strategy):
    def __init__(self):
        super().__init__(StrategyConfig())
        self.bars = defaultdict(list)

    def on_start(self):
        for s in SPECS:
            self.subscribe_bars(BarType.from_str(s))

    def on_bar(self, bar):
        self.bars[str(bar.bar_type)].append(bar)   # 注意：键是标准类型
```

引擎的搭法和仓库示例 `examples/backtest/crypto_ema_cross_ethusdt_trade_ticks.py` 一样（加交易所、品种、成交数据，再 `add_strategy`、`run`）；v2 的回测交易所必须显式给 `fee_model`，不收费也要传一个费率为 0 的 `MakerTakerFeeModel`。结果：

| K 线类型 | 根数 | 观察 |
| :--- | ---: | :--- |
| `1-MINUTE` | 299 | 第一根 10:01:00 收盘，最后一根 14:59:00；15:00 那根没等到定时器 |
| `5-MINUTE@1-MINUTE-INTERNAL` | 59 | 收到时类型是 `…-5-MINUTE-LAST-INTERNAL`；59 根全部等于 5 根 1 分钟的汇总 |
| `250-TICK` | 279 | 69,806 ÷ 250 = 279.2，剩下的 56 笔还在累加器里 |
| `100-VOLUME` | 1,912 | 每根正好 100.00000 ETH，合计 191,200；总成交量 191,261.09，差的 61.09 是最后一根没凑满 |
| `50000-VALUE` | 1,627 | 每根成交额约 50,000 USDT，成交量约 118 ETH（= 50,000 ÷ 423.6） |
| `100-TICK_IMBALANCE` | 65 | 净失衡到 100 笔才关，一根平均覆盖 1,000 多笔 |
| `20-TICK_RUNS` | 247 | 第一根成交量只有 16.7 ETH，因为方向一变就重置，只剩那段连续成交 |
| `50-RENKO` | 158 | 砖块 0.50；第一块 423.76 → 423.26 是下跌砖 |

只订阅其中三种 K 线时，整轮回测 0.44 秒跑完 69,806 笔成交。再改 `DataEngineConfig` 看时间 K 线的几个选项：

| 配置 | 结果 |
| :--- | :--- |
| `1-SECOND`，默认 | 17,998 根 |
| `1-SECOND`，`time_bars_build_with_no_updates=False` | 14,612 根：有 3,386 秒一笔成交都没有，默认会补成平 K 线 |
| `1-MINUTE`，`time_bars_skip_first_non_full_bar=True` | 298 根：回测时钟从 10:00:00.223 开始，第一分钟不完整，被跳过 |
| `1-MINUTE`，`time_bars_timestamp_on_close=False` | 299 根，开高低收不变，第一根的 `ts_event` 从 10:01:00 变成 10:00:00 |
| `1-MINUTE`，`engine.run(start=…12:00 的纳秒时间戳)` | 179 根：12:01 到 14:59 |

两点值得记住。第一，阈值类 K 线的最后一根、时间 K 线最后那个没到点的区间都不会生成，回测结束时它们还在累加器里。第二，`build_with_no_updates` 对秒级 K 线影响很大，指标如果不想被平 K 线稀释，就关掉它。

## 9. 在 Rust 策略里用 {#rust-usage}

Rust 策略的用法完全一样，订阅放在 `on_start`，处理写在 `impl DataActor` 的 `on_bar` 里。仓库示例 `hurst_vpin_directional` 就是在美元 K 线（`VALUE` 聚合）上算 Hurst 指数和 VPIN：

```rust
// 节选自 crates/trading/src/examples/strategies/hurst_vpin_directional/strategy.rs
fn on_start(&mut self) -> anyhow::Result<()> {
    // …检查 bar_type 的品种和交易品种一致
    self.subscribe_bars(self.config.bar_type, None, None);
    // …
    Ok(())
}

fn on_bar(&mut self, bar: &Bar) -> anyhow::Result<()> {
    // 每根美元 K 线关闭时：对数收益进入滚动窗口，更新 Hurst 和 VPIN
    Ok(())
}
```

它的 README 解释了为什么选美元 K 线：每根 K 线都在成交了固定名义金额后关闭，采样频率跟着市场活跃度走，正好和 VPIN 按成交量分桶的定义对齐。

::: warning 常见误区
- **以为 Python 能拿到聚合器对象。** v2 的 Python 层没有聚合器类，只能订阅；要自定义合成规则，就在 `on_trade_tick` 里自己累计，或者用 Rust 写。
- **订阅失衡类、连续类 K 线却用了 `BID`/`ASK`/`MID`。** 报价没有主动方向，K 线不会正确产生，日志里有警告。
- **用带 `@` 的字符串去匹配收到的 K 线或查缓存。** 收到的都是标准类型。
- **在 Python 里对组合类型调用 `request_bars`。** v2 会报错，改用源数据请求加 `bar_types` 参数。
- **品种还没进缓存就订阅 K 线。** 聚合器要用品种的精度，会报 `no instrument found`。
- **以为每根时间 K 线都有成交。** 默认会补平 K 线，成交量为 0。
- **以为 `timestamp_on_close=False` 在 `RIGHT_OPEN` 下才生效。** 正好相反，`RIGHT_OPEN` 总是用开盘时间，这个选项只影响 `LEFT_OPEN`。
:::

## 本章结论

K 线在 Rust 的 `DataEngine` 里合成，策略只用一个 `BarType` 声明要什么：来源是 `INTERNAL` 就本地合成，价格类型决定用成交还是报价，`@` 决定用更小的 K 线。订阅时引擎按标准类型建一个共享的聚合器，以优先级 5 接到源数据主题上，并向客户端订阅源数据；运行时每笔数据进 `BarBuilder` 累计，满足关闭条件（笔数、成交量、成交额、失衡、连续、价格砖块，或者时钟到点）就生成 K 线，写缓存、发布，最后经 `handle_bar` 更新指标、调用 `on_bar`。Python 只在最后一步被回调。

## 检查理解

1. 两个策略都订阅了 `ETHUSDT.BINANCE-1-MINUTE-LAST-INTERNAL`，引擎里有几个聚合器？其中一个策略退订后呢？

   <details><summary>参考答案</summary>

   一个。聚合器按“标准 BarType + 请求 ID”存放，实时订阅的请求 ID 都是 `None`，第二个订阅直接复用。一个策略退订时，主题上还有另一个订阅者，`unsubscribe_bars` 直接返回，聚合器继续跑；两个都退订后才停掉聚合器、取消定时器、退订成交。

   </details>

2. 一笔 350 ETH 的成交进入 `100-VOLUME` 聚合器，此前当前 K 线已累计 30 ETH，会生成几根 K 线？累加器里还剩多少？

   <details><summary>参考答案</summary>

   先放 70 凑满第一根，剩 280；再放 100 生成第二根，剩 180；再放 100 生成第三根，剩 80；80 不够 100，放进累加器。共生成 3 根，每根正好 100 ETH，累加器里剩 80 ETH。这几根 K 线的时间戳都是这笔成交的 `ts_init`。

   </details>

3. 订阅 `…-5-MINUTE-LAST-INTERNAL@1-MINUTE-INTERNAL` 时，10:05 这一刻 1 分钟和 5 分钟的定时器同时到点，引擎怎样保证 5 分钟 K 线包含 10:04–10:05 那根 1 分钟 K 线？

   <details><summary>参考答案</summary>

   `connect_time_bar_sources` 把 1 分钟聚合器登记为 5 分钟聚合器的 `timer_source`。5 分钟的定时器回调 `dispatch_timer` 先检查源聚合器的下一个收盘时间是不是正好等于这次触发时间，是就先让源生成 1 分钟 K 线，这根 K 线经总线进入 5 分钟聚合器的 `update_bar`，然后 5 分钟聚合器才生成自己。

   </details>

## 参考资料

- 官方文档：[Data · Bars and aggregation](https://github.com/nautechsystems/nautilus_trader/blob/develop/docs/concepts/data/index.md) · [Bar](https://github.com/nautechsystems/nautilus_trader/blob/develop/docs/concepts/data/bar.md)
- 源码：[`crates/data/src/aggregation.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/data/src/aggregation.rs) · [`crates/data/src/engine/bar.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/data/src/engine/bar.rs) · [`crates/data/src/engine/handlers.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/data/src/engine/handlers.rs) · [`crates/data/src/engine/config.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/data/src/engine/config.rs) · [`hurst_vpin_directional`](https://github.com/nautechsystems/nautilus_trader/tree/develop/crates/trading/src/examples/strategies/hurst_vpin_directional)
- 信息驱动 K 线的出处：Marcos López de Prado，《Advances in Financial Machine Learning》第 2 章。
- 配图由 `scripts/generate-nautilus-trader-figures.py` 生成。

下一章讲指标：Rust 指标怎样挂在策略上、在 `on_bar` 之前更新，Python 策略注册的指标怎样穿过语言边界，见[第 12 章：指标](./indicators.md)。
