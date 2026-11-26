---
title: "第 15 章：MessageBus：端点、主题与类型化路由"
description: NautilusTrader 的消息总线怎样实现点对点、发布订阅和请求响应三种通信；主题、模式和端点的命名与类型；类型化路由和通用路由的区别与代价；发布一条报价时总线内部的每一步，包括匹配缓存、优先级排序和可重入派发；引擎端点与排队执行；消息不可变原则。
---

# 第 15 章：MessageBus：端点、主题与类型化路由

[全书目录](./index.md) · [上一章](./kernel.md) · [下一章](./cache.md)

::: tip 本章学习目标
能说出三种通信方式各用在什么地方、用哪组函数；能根据一个主题和一组订阅模式，算出处理器的调用顺序；知道类型化路由为什么快、为什么不能和通用路由混用；能解释在回调里发布或下单为什么不会造成 `RefCell` 的重复借用；知道一条命令发到不存在的端点时会发生什么。

**源码版本：** `develop` 分支，提交 `364254f`（2026-11-18）。总线在 `crates/common/src/msgbus/`：`core.rs`（结构与设计说明）、`api.rs`（对外函数）、`typed_router.rs`（类型化发布订阅）、`matching.rs`（通配符匹配）、`switchboard.rs`（主题与端点名）、`mstr.rs`（带类型标记的字符串）。

**对应官方文档：** [Message Bus](https://nautilustrader.io/docs/latest/concepts/message_bus/)
:::

第 14 章说过，内核的部件之间不互相持有引用，全靠消息总线通信。第 0 章第 5.10 节列过 `MessageBus` 的字段，第 10 章从回调的角度走过一遍派发。这一章打开总线本身：它提供哪几种通信方式，一条消息在里面怎样找到它的处理器，以及几个看起来细小、实际决定了系统能不能正确运行的设计（匹配缓存、可重入派发、排队执行）。

主线例子是一条 ETHUSDT 报价的发布：主题 `data.quotes.BINANCE.ETHUSDT`，有三个订阅者，分别是组合（优先级 10）、一个 K 线聚合器（优先级 5）和一个策略（优先级 0）。

## 1. 三种通信方式 {#patterns}

`msgbus/mod.rs` 的模块注释开门见山：

- <strong>点对点。</strong>用 `send_*` 发给一个有名字的端点，只有注册在这个端点上的那一个处理器收到。命令走这条路，例如策略下单时把 `SubmitOrder` 发给 `RiskEngine.queue_execute`。
- <strong>发布订阅。</strong>用 `publish_*` 发到一个主题，所有订阅模式能匹配这个主题的处理器都收到。行情和事件走这条路。
- <strong>请求响应。</strong>请求方用一个关联 ID 注册响应处理器，响应方用 `send_response` 按 ID 送回。历史数据请求走这条路。

总线放在线程局部存储里，每个线程一个实例，所以内部没有锁。对外的函数都是自由函数（`msgbus::publish_quote(...)`），内部先用 `get_message_bus()` 取到当前线程的总线。

## 2. 主题、模式、端点 {#naming}

三种名字底下都是驻留字符串 `Ustr`，但在类型上分开：

```rust
// 节选自 crates/common/src/msgbus/mstr.rs（示意）
pub struct MStr<T> { value: Ustr, _marker: PhantomData<T> }
// MStr<Topic>：发布用的具体主题，如 "data.quotes.BINANCE.ETHUSDT"
// MStr<Pattern>：订阅用的模式，如 "data.quotes.*"
// MStr<Endpoint>：点对点的端点，如 "RiskEngine.execute"
```

这个零大小的类型标记让编译器拦住“拿模式去发布”“往主题上 send”这类错误，运行时没有任何开销。

主题的格式由 `switchboard.rs` 统一生成，前面几章已经见过不少：`data.quotes.{venue}.{symbol}`、`data.trades.{venue}.{symbol}`、`data.bars.{bar_type}`、`data.book.deltas.{venue}.{symbol}`、`events.order.{strategy_id}`、`events.position.{strategy_id}`、`events.account.{account_id}`。官方文档补充了一点：请求、回放等非实时的数据走 `data.pipeline.{kind}...` 这一组主题，不承诺和实时数据相同的顺序和时序语义。

订阅模式支持两个通配符：`*` 匹配零个或多个字符，`?` 匹配恰好一个字符。匹配算法（`matching.rs`）是一个贪心的双指针算法，源码注释说明了为什么不用动态规划（空间开销）、递归回溯（栈溢出风险）或正则（编译开销）。

## 3. 两套路由 {#routing}

总线里有两套完全独立的路由结构，这是理解它的关键。`core.rs` 的设计说明写得很直白：

| | 类型化路由 | 通用路由 |
| :--- | :--- | :--- |
| 函数 | `publish_quote`、`subscribe_quotes` 等 | `publish_any`、`subscribe_any` |
| 数据结构 | 每种类型一个 `TopicRouter<T>` | `topics` 映射 |
| 处理器收到 | `&T`，直接用 | `&dyn Any`，要自己向下转型 |
| 用在哪里 | 行情、订单和仓位事件、账户状态 | 自定义数据、信号、低频消息、Python |

类型化路由的处理器收到的是 `&T` 引用：同一条消息发给 N 个处理器不需要复制，处理器自己决定要不要克隆；报价、成交、K 线都是 `Copy` 的，代价为零。通用路由的每个处理器都要做一次运行时类型检查和向下转型。源码引用的基准（`benches/msgbus_typed.rs`）是：空处理器派发快约 10 倍，5 个订阅者时快约 3.5 倍，10 个时约 2 倍，百万条消息的大批量场景快约 7%。

设计说明里最重要的一句是：两套路由的数据结构是分开的，发布方和订阅方必须用配套的接口，混用会“悄无声息地丢消息”。`publish_quote` 走 `router_quotes`，用 `subscribe_any` 订阅同一个主题的处理器永远收不到。第 13 章的信号走的是通用路由，所以要用 `subscribe_signal` 而不是某个类型化的订阅函数。

## 4. 主线例子：发布一条报价 {#publish}

`publish_quote` 只是一层薄包装，真正的工作在 `publish_typed`（`api.rs`）：

```rust
// 节选自 crates/common/src/msgbus/api.rs
fn publish_typed<T: 'static>(topic, tls, fill_fn, message: &T) {
    let _publication = PublicationScope::enter();
    dispatch_tap_publish(topic, message);                  // ① 事件存储的抓取点（第 8 章）

    let mut handlers = tls.with_borrow_mut(std::mem::take); // ② 取出线程局部的处理器缓冲区

    let bus_rc = get_message_bus();
    {
        let mut bus = bus_rc.borrow_mut();                  // ③ 短暂借用总线
        fill_fn(&mut bus, &mut handlers);                   //    把匹配的处理器复制进缓冲区
        bus.increment_pub_count();
    }                                                       //    借用在派发前结束

    for handler in &handlers {                              // ④ 依次调用
        handler.handle(message);
    }

    handlers.clear();                                       // ⑤ 归还缓冲区
    tls.with_borrow_mut(|buf| *buf = handlers);
}
```

`publish_quote` 在这之后还会调用 `forward_to_external_egress`，把配置了外部流的主题转发到 Redis 等外部后端（第 36 章）。

### 4.1 找处理器：匹配缓存和优先级

第 ③ 步的 `fill_matching_handlers` 先查 `topic_cache`：这个具体主题以前算过匹配结果没有。没有就遍历全部订阅，用通配符算法挑出匹配的，再按投递顺序排序，结果（订阅的下标列表）存进缓存：

```rust
// 节选自 crates/common/src/msgbus/typed_router.rs
fn delivery_order(&self, other: &Self) -> Ordering {
    other.priority.cmp(&self.priority)                 // 优先级高的在前
        .then_with(|| self.pattern.cmp(&other.pattern)) // 同优先级按模式字符串
        .then_with(|| self.handler_id.cmp(&other.handler_id))
}
```

主线例子里，组合订阅的是 `data.quotes.*`（优先级 10），聚合器订阅 `data.quotes.BINANCE.ETHUSDT`（优先级 5），策略订阅同一个具体主题（优先级 0）。第一次发布到这个主题时算出顺序 [组合, 聚合器, 策略] 并缓存；之后每一条 ETHUSDT 报价都直接用缓存，不再做任何字符串匹配。任何一次订阅或退订都会清空整个缓存（因为订阅表用 `swap_remove` 删除元素，下标会变）。

同一个处理器重复订阅同一个模式会被忽略（只记一条调试日志），源码注释举的例子是订单簿的增量和快照共用一个更新器。

### 4.2 可重入派发

第 ② 和第 ③ 步的安排是为了一个具体问题：处理器在被调用时，常常还要用总线。策略在 `on_quote` 里下单，聚合器在处理报价时发布一根 K 线，组合在更新时发布账户状态。如果派发时还借着总线，这些嵌套的调用就会撞上 `RefCell` 的重复借用而 panic。

所以 `publish_typed` 只在第 ③ 步短暂借用总线，把处理器复制进一个缓冲区就放开，然后才调用处理器。缓冲区是线程局部的、每种消息类型一个，用 `std::mem::take` 取走：如果处理器里又发布了同类型的消息，嵌套的那次调用会拿到一个空的新缓冲区，互不干扰；最外层结束时再把缓冲区放回去，下一次发布可以复用它的内存。这也决定了一个语义：在派发过程中新增或取消的订阅，不影响正在进行的这一次派发，只从下一次发布开始生效。

![一条报价在总线里的路径：抓取点、取缓冲区、短暂借用总线查匹配缓存、按优先级依次调用组合、聚合器和策略，处理器内部可以再次发布或发送命令](/nautilus-trader/figures/msgbus-publish.svg)

怎么读这张图：中间灰色的那一段是唯一借用总线的地方，它很短；右边三个处理器运行时总线已经放开，所以聚合器发布 K 线、策略发送下单命令都能正常进行。

## 5. 点对点：端点与排队执行 {#endpoints}

端点由各引擎在 `register_msgbus_handlers` 里注册（第 14 章第 1 节第 7 步）。`switchboard.rs` 里的端点名有：`DataEngine.execute`、`DataEngine.process`、`DataEngine.response`、`RiskEngine.execute`、`RiskEngine.process`、`ExecEngine.execute`、`ExecEngine.process`、`ExecEngine.reconcile_execution_report`、`OrderEmulator.execute`、`Portfolio.update_account`、`Portfolio.update_order` 等，以及几个带 `queue_execute` 的变体。命令和数据走的端点表用 `TypedIntoHandler`，把消息的所有权交给处理器，省掉一次复制。

发到一个没有注册的端点，不会 panic，只记一条错误日志：`send_trading_command: no registered endpoint '…'`。这条日志值得留意，它通常意味着组件注册顺序出了问题，或者执行算法的 ID 写错了（第 13 章的 `{id}.execute`）。

### 5.1 为什么下单要先排队

策略的 `submit_order` 并不直接发到 `RiskEngine.execute`，而是发到 `RiskEngine.queue_execute`。风控引擎注册这个端点时的注释解释了原因：

```rust
// 节选自 crates/risk/src/engine/mod.rs（register_msgbus_handlers）
// When a strategy calls `submit_order()` from within an event handler
// (e.g., `on_order_filled`), the command is routed through this endpoint.
// In live mode the `TradingCommandSender` queues the command for the next
// event-loop iteration, preventing a synchronous `deny_order()` from
// dispatching an `OrderDenied` back into a strategy that still holds a
// mutable borrow - which would otherwise panic on `RefCell` re-entrancy.
msgbus::register_trading_command_endpoint(
    MessagingSwitchboard::risk_engine_queue_execute(),
    TypedIntoHandler::from(move |cmd: TradingCommand| {
        if let Some(sender) = try_get_trading_cmd_sender() {
            sender.execute(TradingCommandMessage::new(MessagingSwitchboard::risk_engine_execute(), cmd));
        } else {
            msgbus::send_trading_command(MessagingSwitchboard::risk_engine_execute(), cmd);
        }
    }),
);
```

问题和第 4.2 节类似，但发生在组件内部：策略在 `on_order_filled` 里下单时，它自己正被可变借用着。如果风控同步地拒绝这张单，`OrderDenied` 会立刻派发回这个策略，再次可变借用它，于是 panic。实盘里，`TradingCommandSender` 把命令放进通道，等事件循环的下一轮再执行（第 30 章）；回测里没有安装发送器，就退回到直接调用。所以同一段策略代码在两种环境下，下单命令被执行的时机略有不同：实盘晚一轮，回测立即。

## 6. 请求与响应 {#request-response}

请求方先用 `register_response_handler(correlation_id, handler)` 登记处理器，再把请求命令发给数据引擎。响应方处理完后调用 `send_response`，总线按关联 ID 找到处理器：如果这是最后一个响应（`completed()` 为真），就把处理器从表里取走；否则只调用不删除，所以一个请求可以分多次响应（第 7、18 章的长时间请求就是这样）。响应在派发前也会经过事件存储的抓取点；官方文档提到的 `data.response` 主题是一个抓取用的通道，不是数据的传递路径。

## 7. 消息不可变 {#immutability}

官方文档专门有一节“Message integrity”：消息一旦创建，字段就不能再改，包括 `params` 这样的容器字段。组件可以读消息、据此维护自己的状态，但不能改写原消息；需要一条派生的消息时，就新建一条。由此有三条归属规则：调用方给的请求选项留在消息上，返回给调用方的响应元数据留在响应上，组件的工作流状态（分段的日期范围、游标、计数器）放在组件自己按消息 ID 索引的上下文里。这条原则是第 8 章事件存储能够回放的前提：同一条消息，每个消费者看到的都一样，事后看到的也一样。

## 8. 配置与外部流 {#config}

`MessageBusConfig`（`msgbus/config.rs`）的字段几乎都和外部流有关：编码方式（JSON 或 MessagePack，市场数据可单独配置，部分数据可用 SBE）、时间戳是否格式化为 ISO 8601、缓冲间隔、流的自动裁剪、流键的前缀规则（交易员前缀、交易员 ID、实例 ID、是否每个主题一条流），以及 `external_streams`。打开后，总线把选定主题的消息写到 Redis 流，另一个节点可以从这些流读回，实现跨进程的分发。这一层在第 36 章展开。

::: warning 常见误区
- **用 `subscribe_any` 订阅一个用 `publish_quote` 发布的主题。** 两套路由互不相通，订阅者永远收不到，也不会报错。
- **以为订阅在派发过程中立即生效。** 派发前处理器列表已经复制好，新订阅从下一次发布开始生效。
- **以为优先级相同的处理器按订阅先后调用。** 同优先级按模式字符串排序，再按处理器 ID 排序。
- **以为发到不存在的端点会报错返回。** 只记一条错误日志，消息被丢弃。
- **以为策略下单是同步执行的。** 实盘里经 `queue_execute` 排到下一轮事件循环；回测里才是同步的。
- **在处理器里修改收到的消息。** 消息不可变，需要派生就新建一条。
:::

## 本章结论

消息总线是一个放在线程局部存储里的无锁结构，提供点对点（端点）、发布订阅（主题与模式）、请求响应（关联 ID）三种通信。热路径上的行情和事件走类型化路由，每种类型一个 `TopicRouter`，处理器直接拿到 `&T`；自定义数据、信号和 Python 走通用路由；两者不能混用。发布时总线先经过事件存储的抓取点，再短暂借用自己、从匹配缓存里取出按优先级排好序的处理器，放开借用后依次调用，所以处理器内部可以安全地再发布、再发送。策略下单经 `queue_execute` 端点，实盘里延到下一轮事件循环，避免同步拒单撞上组件自身的借用。

## 检查理解

1. 一个 Actor 用模式 `data.quotes.BINANCE.*` 以默认优先级订阅了报价，主线例子里的三个订阅者不变。一条 ETHUSDT 报价发布时，四个处理器的调用顺序是什么？

   <details><summary>参考答案</summary>

   先按优先级：组合（10）、聚合器（5），然后是两个优先级为 0 的处理器，按模式字符串排序：`data.quotes.BINANCE.*` 和 `data.quotes.BINANCE.ETHUSDT` 比较，`*` 的字节值（42）小于 `E`（69），所以 Actor 在策略之前。顺序是组合、聚合器、Actor、策略。

   </details>

2. 策略在 `on_quote` 里订阅了另一个品种的报价，并且立刻发布了一条同主题的报价（假设是测试场景）。新订阅会收到哪一条？会 panic 吗？

   <details><summary>参考答案</summary>

   不会 panic：派发外层只在复制处理器时短暂借用总线，订阅和嵌套发布都能拿到借用；嵌套发布用的是一个新的空缓冲区。订阅会清空匹配缓存，嵌套的那次发布重新计算匹配，所以如果新订阅匹配那个主题，它会收到嵌套发布的那一条；外层正在进行的派发不受影响。

   </details>

3. 为什么策略在 `on_order_filled` 里下的单，在回测和实盘里被风控处理的时机不同？

   <details><summary>参考答案</summary>

   策略下单发到 `RiskEngine.queue_execute`。实盘安装了 `TradingCommandSender`，命令被放进通道，等事件循环下一轮才交给 `RiskEngine.execute`；回测没有安装发送器，这个端点直接调用 `RiskEngine.execute`，同步执行。排队是为了避免同步拒单时 `OrderDenied` 派发回一个正被可变借用的策略。

   </details>

## 参考资料

- 官方文档：[Message Bus](https://nautilustrader.io/docs/latest/concepts/message_bus/)
- 源码：[`crates/common/src/msgbus/core.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/common/src/msgbus/core.rs) · [`api.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/common/src/msgbus/api.rs) · [`typed_router.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/common/src/msgbus/typed_router.rs) · [`matching.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/common/src/msgbus/matching.rs) · [`switchboard.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/common/src/msgbus/switchboard.rs) · [`crates/risk/src/engine/mod.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/risk/src/engine/mod.rs)
- 配图由 `scripts/generate-nautilus-trader-figures.py` 生成。

总线负责传递，缓存负责保存。下一章看那个所有组件共享、只有引擎能写的状态仓库。[第 16 章：Cache](./cache.md)。
