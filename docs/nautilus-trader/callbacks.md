---
title: "第 5 章：回调：一条消息怎样变成 on_xxx"
description: NautilusTrader 里策略和 actor 的回调从哪里来：订阅时登记了什么，一条报价怎样走到 on_quote，一笔成交怎样依次触发 on_order_filled、on_order_event、on_position_opened，计时器和生命周期回调怎样触发，Python 回调和 Rust 回调有什么不同，回调里能做什么、不能做什么。
---

# 第 5 章：回调：一条消息怎样变成 on_xxx

[全书目录](./index.md) · [上一章](./rust-strategy.md) · [下一章](./bar-aggregation.md)

::: tip 本章学习目标
能说清 `on_quote`、`on_order_filled`、`on_position_opened`、`on_time_event`、`on_start` 这些回调分别由谁、在什么时候、以什么顺序调用；知道订阅时框架替你登记了什么；知道回调在 `RUNNING` 之外为什么收不到数据；知道 Python 回调比 Rust 回调多做了哪几步、抛异常会怎样；能判断一段代码放在回调里是否安全。

**源码版本：** `develop` 分支，提交 `364254f`（2026-11-18）。读完[第 1 章](./architecture.md)就可以读本章；策略框架本身（怎样写、怎样注册、下单 API）见[第 4 章](./rust-strategy.md)。
:::

第 0 章第 3.4 节说，Python 代码在 v2 里只出现在三处，第一处就是用户组件的回调。回调是你写的代码和框架之间唯一的接口：框架在 Rust 里处理行情、订单和仓位，到了需要你做决定的时候，就调用一个 `on_xxx` 方法。所以弄清回调的来龙去脉，等于弄清你的代码在什么时机、看到什么状态。

## 1. 回调有哪几类

`DataActor` 和 `Strategy` 两个 trait（`crates/common/src/actor/data_actor.rs`、`crates/trading/src/strategy/mod.rs`）一共定义了六十多个 `on_xxx`，Python 基类和它们一一对应。按触发来源可以分成六类：

| 类别 | 主要回调 | 由什么触发 | 需要自己订阅吗 |
| --- | --- | --- | --- |
| 生命周期 | `on_start`、`on_stop`、`on_resume`、`on_reset`、`on_dispose`、`on_degrade`、`on_fault` | `Trader` 改变组件状态 | 不需要 |
| 实时数据 | `on_quote`、`on_trade`、`on_bar`、`on_book_deltas`、`on_book`、`on_instrument`、`on_mark_price`、`on_funding_rate`、`on_data` 等 | 总线上的数据主题 | 需要，`subscribe_*` |
| 历史数据 | `on_historical_quotes`、`on_historical_bars`、`on_historical_data` 等 | 请求的响应 | 需要，`request_*` |
| 订单事件 | `on_order_initialized` … `on_order_filled` … 共 19 个，最后统一调 `on_order_event` | 总线主题 `events.order.{strategy_id}` | 不需要，注册时自动订阅 |
| 仓位事件 | `on_position_opened`、`on_position_changed`、`on_position_closed`，最后调 `on_position_event` | 总线主题 `events.position.{strategy_id}` | 不需要，注册时自动订阅 |
| 时间 | `on_time_event` | 时钟上的计时器或时间提醒 | 需要，`clock.set_timer` 等 |

前两类和时间回调属于 `DataActor`，所有 actor 都有；订单和仓位回调属于 `Strategy`。另外还有 `on_signal`（信号）、`on_save` / `on_load`（状态持久化）、`on_market_exit`（市场退出流程）等少数几个，本章不展开。

不管哪一类，送达的方式只有一种：**消息总线上的一次发布，加上订阅时登记的一个闭包**。下面先看闭包是怎样登记的。

![回调的调用流程：左边一条报价，DataEngine 先写缓存再发布到行情主题，MessageBus 按优先级派发，订阅时登记的闭包从注册表取出组件，handle_quote 更新指标并检查状态后调用 on_quote；右边一笔成交，执行引擎更新订单和仓位后先发布订单事件，触发 on_order_filled 和 on_order_event，再发布仓位事件，触发 on_position_opened 等](/nautilus-trader/figures/callback-flow.svg)

怎么读这张图：橙色框是你写的回调，其余都是框架代码。左右两条路的形状一样：引擎先更新状态，再发布消息，总线按订阅找到闭包，闭包从注册表里取出组件，框架代码做完检查之后才调用你的方法。

## 2. 订阅时登记了什么

以 `self.subscribe_quotes(instrument_id)` 为例。Rust 的实现在 `crates/common/src/actor/data_actor.rs`：

```rust
// 节选自 crates/common/src/actor/data_actor.rs（DataActor::subscribe_quotes）
let actor_id = self.core().actor_id().inner();
let handler = TypedHandler::from(move |quote: &QuoteTick| {
    if let Some(mut actor) = try_get_actor_unchecked::<Self>(&actor_id) {
        actor.handle_quote(quote);
    } else {
        log::error!("Actor {actor_id} not found for quote handling");
    }
});
DataActorCore::subscribe_quotes(self.core_mut(), handler, instrument_ids, client_id, params)
```

这里登记的不是组件本身，而是一个**只记住 `actor_id` 的闭包**。闭包被调用时，再按 ID 去全局的 actor 注册表里取出组件。这样总线不需要持有组件的引用，组件被移除后闭包也只是找不到人、记一条错误。

`DataActorCore::subscribe_quotes` 接着做三件事：

1. 对每个标的算出主题 `data.quotes.{venue}.{symbol}`，把闭包记进组件自己的 `quote_handlers` 表；同一主题重复订阅只会打一条警告。
2. 调用 `msgbus::subscribe_quotes(topic, handler, None)`，把闭包登记到总线的报价路由上。最后一个参数是优先级，组件用默认的 0。
3. 只对这次新增的标的，给 `DataEngine` 发一条 `DataCommand::Subscribe`。数据引擎为每个订阅记引用计数，第一个订阅者到来时才让数据客户端去交易所订阅，最后一个订阅者离开时才退订。

Python 的 `Strategy.subscribe_quotes`（`crates/trading/src/python/strategy.rs`）把参数从 Python 对象转成 Rust 值之后，调用的就是同一个 `DataActor::subscribe_quotes`，只是 `Self` 换成了 `PyStrategyInner`。所以 Python 策略的订阅和 Rust 策略走的是完全相同的路。

订单和仓位事件不用自己订阅。策略注册到 `Trader` 时，`Trader::add_strategy_id_with_subscriptions`（`crates/system/src/trader.rs`）替它订阅了两个主题：`events.order.{strategy_id}` 和 `events.position.{strategy_id}`，登记的同样是“按 ID 取出策略、再调用 `handle_order_event` 或 `handle_position_event`”的闭包。

## 3. 一条报价怎样走到 `on_quote`

按图左边那一列从上往下：

1. **引擎先改状态，再发布。** `DataEngine` 处理报价时先 `cache.add_quote`，再发布到 `data.quotes.{venue}.{symbol}`。所以 `on_quote` 里调用 `self.cache.quote(instrument_id)`，拿到的就是这一条（除非后面又来了新的）。
2. **总线按优先级派发。** 报价走类型化的 `TopicRouter<QuoteTick>`，找到所有模式匹配的订阅（匹配结果有缓存，见第 0 章第 5.10 节），按优先级从高到低依次调用。`Portfolio` 订阅报价时用的优先级是 10（`crates/portfolio/src/portfolio.rs`），组件是 0，所以**你的 `on_quote` 被调用时，组合的未实现盈亏已经按这条报价更新过了**。
3. **闭包取出组件。** 第 2 节登记的闭包按 `actor_id` 从注册表取出组件，调用 `handle_quote`。
4. **框架代码先做两件事**（`DataActor::handle_quote`）：先更新用 `register_indicator_for_quotes` 挂在这个组件上的指标；然后检查组件状态，**不在 `RUNNING` 就直接丢弃**，只打一条日志。
5. **调用你的 `on_quote`。** Rust 策略就是一次普通的 trait 方法调用。Python 策略多三步：`PyStrategyInner::on_quote` 调用 `dispatch_on_quote`，先 `Python::attach` 拿到 GIL，再用 `into_py_any` 把这条 `QuoteTick` 包成一个新的 Python 对象，最后经弱引用找到你的 Python 实例，`call_method1("on_quote", (quote,))`。
6. **出错只记日志。** `on_quote` 返回错误（Python 是抛出异常，会被转成 `Python on_quote failed:` 加完整的 traceback），`handle_quote` 只记一条错误日志，然后返回。总线继续派发给下一个订阅者，节点不会停下。

成交、K 线、订单簿等其他实时数据的路径完全一样，只是换了主题、路由和 `handle_*` / `on_*` 的名字。

## 4. 一笔成交怎样依次触发三个回调

图右边那一列。执行客户端报来的成交，经 channel 到达 `ExecEngine.process` 端点，执行引擎在 `apply_order_event`（`crates/execution/src/engine/mod.rs`）里按这个顺序处理：

1. **更新缓存里的订单。** 订单 `apply` 这笔成交，状态、已成交数量、均价随之变化。
2. **处理仓位**（`handle_order_fill`）：通知 `Portfolio`（`Portfolio.update_order` 端点）；按 OMS 类型决定仓位 ID，开仓、加减仓或反手，写进缓存；另外在按标的划分的成交主题 `events.order_filled.{instrument_id}` 上发布一次。
3. **发布订单事件**到 `events.order.{strategy_id}`。`Portfolio` 用优先级 10 订阅了 `events.order.*`，先收到；然后才是策略。
4. **发布仓位事件**到 `events.position.{strategy_id}`。

策略收到订单事件后，`Strategy::handle_order_event` 依次做：

- 记日志：被拒、被否决的事件按警告级别记录；
- 如果是终态事件（成交完、撤单、拒单、过期），取消这笔订单的 GTD 过期计时器；
- **不在 `RUNNING` 就到此为止**；
- 交给 `OrderManager` 处理关联订单（OCO、OTO 等，配置了 `manage_contingent_orders` 时）；
- 调用对应的具体回调，比如 `on_order_filled`；
- 最后调用通用回调 `on_order_event`。

仓位事件同理：先 `on_position_opened` / `on_position_changed` / `on_position_closed`，再 `on_position_event`。

把顺序串起来，一笔开仓的成交在策略里看到的是：

```text
on_order_filled(fill)        ← 此时缓存里的订单和仓位都已更新
on_order_event(fill)
on_position_opened(event)
on_position_event(event)
```

<!-- 顺序依据 crates/execution/src/engine/mod.rs 的 apply_order_event 与 crates/trading/src/strategy/mod.rs 的 handle_order_event -->

有两点值得记住。第一，`on_order_filled` 先于 `on_position_opened`，但在 `on_order_filled` 里查缓存，仓位已经存在了，因为仓位在发布订单事件之前就处理好了。第二，具体回调和通用回调都会被调用，两处都写逻辑会执行两次，一般只覆盖其中一个。

订单回调出错时，Python 策略会通过 `log_callback_error` 记录错误，同样不中断后续回调。

## 5. 时间回调

`self.clock.set_timer(name, interval)` 或 `set_time_alert(name, alert_time)` 登记计时器。没有传入专门的回调函数时，计时器到点产生的 `TimeEvent` 交给组件的默认处理函数，走 `handle_time_event`：同样先检查组件是否在 `RUNNING`，再调用 `on_time_event`。

时间事件从哪里来，回测和实盘不同，但到达组件之后的路径相同：

- **回测：** `VirtualClock` 把计时器放在一个按到期时间排序的堆里，回测主循环每处理一条数据之前，先把时钟推进到这条数据的时间，依次触发期间到点的计时器。所以计时器和数据在同一条时间线上严格排序。
- **实盘：** 计时器由 Tokio 调度，到点后把 `TimeEvent` 经时间事件的 channel 送回核心线程，`AsyncRunner` 取出后派发（`crates/live/src/runner.rs`，第 20 章细讲）。

## 6. 生命周期回调

`Trader` 启动组件时调用 `Component::start`，组件先进入过渡状态 `STARTING`，调用 `on_start`，成功后进入 `RUNNING`。官方架构文档写明：回调返回错误时，状态停在过渡状态，不会进入下一个稳定状态。Python 的 `on_start` 抛异常，就是这种情况。

对策略来说，`on_start` 前面还有一段框架代码（`Strategy::on_start`）：确认已注册，按配置恢复 GTD 订单的过期计时器。Python 策略的 `on_start` 由 `PyStrategyInner` 先调框架这段，再调你的 Python 方法。

第 3、4 节反复出现的“不在 `RUNNING` 就丢弃”决定了一条惯例：**订阅放在 `on_start` 里做**。在构造函数里组件还没注册，订阅会直接报错；在 `on_start` 之前到达的数据和事件，你的回调也收不到。

## 7. 回调里能做什么，不能做什么

回调都在核心线程上**同步**执行：框架调用你的方法，等它返回，才继续派发下一个订阅者、处理下一条消息。由此有几条规则：

- **不要做阻塞 I/O 或重计算。** 回调慢一毫秒，整个节点就停一毫秒，包括所有行情和订单处理。官方文档建议把这类工作交给线程池或别的进程。
- **下单不会立刻执行。** `submit_order` 把命令发到 `RiskEngine.queue_execute`，命令先排队，当前这轮回调结束后才被处理（第 1 章第 5.2 节）。所以在 `on_quote` 里下的单，不会在 `on_quote` 返回之前就收到 `on_order_submitted`。
- **发布消息会立刻同步派发。** 在回调里 `publish_data`、`publish_signal`，订阅者会在你的 `publish` 调用返回之前就被调用，形成嵌套。官方的开发文档（`docs/developer_guide/callback_dispatch.md`）已经设计好一套“排队派发”的约定，保证嵌套发布不会插到前一次发布的未完成派发前面，但文档开头写明它**还没有启用**，现在的派发仍是同步的。
- **回调里看到的是“当前”状态，不是事件发生那一刻的快照。** 官方架构文档特意提醒：回调可能看到比它正在处理的事件更新的缓存状态。比如嵌套派发里，后一条报价已经写进缓存，前一条报价的回调才执行。
- **Python 回调拿到的都是拷贝。** 报价、订单事件在跨边界时被复制成新的 Python 对象；在回调里修改它们不会影响框架（第 0 章第 6.2 节）。

## 8. Python 回调和 Rust 回调的差别

| | Rust 策略 | Python 策略 |
| --- | --- | --- |
| 怎么写 | 结构体持有 `StrategyCore`，写 `nautilus_strategy!(MyStrategy)`，在 `impl DataActor` / `impl Strategy` 里覆盖方法 | 继承 `nautilus_trader.trading.Strategy`，覆盖同名方法 |
| 谁实现 trait | 你的结构体 | `PyStrategyInner`，它把每个 `on_xxx` 转发给 Python |
| 一次回调的额外开销 | 无 | 拿 GIL；把 Rust 值包成新的 Python 对象；按名字查找并调用方法 |
| 回调出错 | 返回 `Err`，框架记日志 | 抛异常，框架连同 traceback 记日志 |
| 订阅、下单 | 直接调用 trait 方法 | 参数先从 Python 对象转成 Rust 值，再调用同一个 trait 方法 |

两者共用同一个 `StrategyCore`、同一套注册和派发路径，所以行为（顺序、状态检查、出错处理）完全一样，差别只在每次跨语言调用的开销上。行情很密的策略，这个开销会累积起来，这是用 Rust 写策略的主要理由。

::: warning 常见误区
- **在构造函数里订阅。** 那时组件还没注册到 `Trader`，订阅会报错；订阅放在 `on_start` 里。
- **以为停止后还能收到回调。** 组件不在 `RUNNING` 时，数据、订单事件、时间事件都会被丢弃（只记日志）。
- **同时覆盖 `on_order_filled` 和 `on_order_event`，逻辑执行两次。** 两个都会被调用，先具体、后通用。
- **以为 `on_order_filled` 里还查不到仓位。** 仓位在发布订单事件之前已经处理并写进缓存了。
- **以为回调抛异常会让节点停下。** 只会记一条错误日志，派发继续；这也意味着错误可能被悄悄吞掉，要盯日志。
- **在回调里等网络或算大模型。** 回调同步执行，会拖住整个节点。
:::

## 本章结论

所有回调都由同一套机制送达：引擎先更新缓存，再在总线上发布；总线按优先级调用订阅时登记的闭包；闭包按 ID 从注册表取出组件；框架代码检查组件是否在运行、更新指标或处理关联订单，最后才调用你的 `on_xxx`。数据回调要自己在 `on_start` 里订阅，订单和仓位回调由 `Trader` 自动订阅；一笔成交依次触发 `on_order_filled`、`on_order_event`、`on_position_opened`、`on_position_event`。Python 回调走的是同一条路，只是在最后一步多了拿 GIL 和复制对象。

## 检查理解

1. 在 `on_quote` 里读 `self.portfolio.unrealized_pnl(instrument_id)`，得到的是用这条报价算的，还是上一条报价算的？

   <details><summary>参考答案</summary>

   用这条报价算的。`Portfolio` 订阅报价的优先级是 10，策略是 0，总线按优先级从高到低派发，所以组合先处理这条报价，策略后收到。

   </details>

2. 一个策略在 `on_start` 之前，构造完就收到了一条报价吗？

   <details><summary>参考答案</summary>

   不会。构造时组件还没注册，不能订阅；即使有别的组件订阅了同一个主题、报价已经在总线上流动，闭包取出这个组件后，`handle_quote` 发现它不在 `RUNNING`，也会直接丢弃。

   </details>

3. Python 策略的 `on_order_filled` 抛了 `KeyError`，接下来会发生什么？

   <details><summary>参考答案</summary>

   `PyStrategyInner` 把异常转成错误，通过 `log_callback_error` 记下 traceback；`handle_order_event` 继续调用 `on_order_event`，随后执行引擎发布仓位事件，`on_position_opened` 等照常被调用。节点不会停，订单和仓位状态也不受影响，因为它们在调用回调之前就已经更新了。

   </details>

## 参考资料

- 官方文档：[Actors](https://github.com/nautechsystems/nautilus_trader/blob/develop/docs/concepts/actors.md) · [Strategies](https://github.com/nautechsystems/nautilus_trader/blob/develop/docs/concepts/strategies.md) · [Message bus](https://github.com/nautechsystems/nautilus_trader/blob/develop/docs/concepts/message_bus.md) · [Callback dispatch contract](https://github.com/nautechsystems/nautilus_trader/blob/develop/docs/developer_guide/callback_dispatch.md)
- 源码：[`crates/common/src/actor/data_actor.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/common/src/actor/data_actor.rs) · [`crates/trading/src/strategy/mod.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/trading/src/strategy/mod.rs) · [`crates/system/src/trader.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/system/src/trader.rs) · [`crates/execution/src/engine/mod.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/execution/src/engine/mod.rs) · [`crates/trading/src/python/strategy.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/trading/src/python/strategy.rs)
- 配图由 `scripts/generate-nautilus-trader-figures.py` 生成。

下一章看回调最常见的数据来源之一：K 线是怎样在 Rust 里合成、再送到 `on_bar` 的，见[第 6 章：K 线聚合器](./bar-aggregation.md)。后面的第二部分会逐个拆开本章提到的组件：总线、缓存、时钟、数据和执行引擎、组合、Trader，回到[全书目录](./index.md)查看规划。
