---
title: "第 18 章：DataEngine：订阅、路由与历史请求"
description: DataEngine 在数据客户端和其余组件之间做什么：订阅命令怎样路由到客户端、怎样按持有者计数、最后一个持有者离开才真正退订；行情到达后先写缓存再发布；订单簿的维护与缓冲；历史请求怎样登记、分派和响应；合成品种、K 线、连续期货、期权链这些引擎内的派生数据。
---

# 第 18 章：DataEngine：订阅、路由与历史请求

[全书目录](./index.md) · [上一章](./clock.md) · [下一章](./risk-engine.md)

::: tip 本章学习目标
能说出一条订阅命令从策略到适配器经过的每一步，知道它在什么情况下根本不会发到适配器；能解释两个策略订阅同一个品种时，适配器为什么只收到一次订阅、退订时又为什么要等最后一个；知道行情到达后数据引擎依次做了什么；能追踪一次历史请求从登记到响应送回的全过程。

**源码版本：** `develop` 分支，提交 `364254f`（2026-11-18）。数据引擎在 `crates/data/src/engine/`：`mod.rs`（结构、命令执行、响应处理）、`dispatch.rs`（行情处理）、`registry.rs`（客户端注册与路由）、`book.rs`（订单簿）、`bar.rs`（K 线聚合接线，第 11 章）、`requests.rs`、`synthetic.rs`、`futures.rs`、`option_chain.rs`；客户端适配器和订阅计数在 `crates/data/src/client.rs`、`subscription.rs`。

**对应官方文档：** [Data](https://nautilustrader.io/docs/latest/concepts/data/) · [Architecture](https://nautilustrader.io/docs/latest/concepts/architecture/)（Data flow 一节）
:::

数据引擎是第 4、11 章反复出场的“幕后角色”：K 线聚合器是它建的，合成品种的价格是它算的，订单簿是它维护的，历史请求是它分派的。`engine/mod.rs` 的模块注释给它的定位是“整个数据栈的中心”：一边是若干个数据客户端（适配器），一边是平台的其余部分，它用一个扇入扇出的模式执行数据命令、处理数据响应和行情对象。

主线例子：两个策略 A 和 B 都订阅了 ETHUSDT 的报价，随后 A 退订，再随后 B 退订；中间 A 还发出了一个“过去一小时成交”的历史请求。

## 1. 数据引擎持有什么 {#state}

`DataEngine` 有五十多个字段，按用途分成几组：

- <strong>共享部件。</strong>时钟、缓存、配置。
- <strong>客户端与路由。</strong>`clients`（客户端 ID 到 `DataClientAdapter`）、`routing_map`（交易所到客户端 ID）、`default_client_id`，以及外部客户端的订阅登记。
- <strong>订单簿。</strong>每个品种的 `BookUpdater`、快照定时器、增量和深度的订阅计数、缓冲中的增量。
- <strong>K 线聚合。</strong>`bar_aggregators` 及其处理器、预热缓冲（第 11 章）。
- <strong>请求。</strong>`inflight_requests`（进行中的请求）、分段请求与合并请求的状态、连续期货请求。
- <strong>派生数据。</strong>合成品种的报价、成交来源，价差报价，期权链管理器。
- <strong>计数器。</strong>命令、数据、请求、响应各一个计数。

每个 `DataClientAdapter`（`client.rs`）包着一个实现了 `DataClient` trait 的适配器，另外记着这个客户端上每类数据各订阅了哪些品种，以及一个“活跃订阅”登记表。第 38 章接入富途时写的就是被它包起来的那个 `DataClient`。

## 2. 订阅：路由与计数 {#subscribe}

### 2.1 先在引擎内部解决的订阅

订阅命令到达 `DataEngine.execute`（第 15 章的端点）后，并不是每一条都会发给适配器。有几类在引擎内部就解决了：

- `INTERNAL` 的 K 线：引擎自己建聚合器，转而订阅底层的成交或报价（第 11 章第 2 节）；
- 合成品种的报价、成交：引擎订阅各个成分品种，自己算价（第 3 章第 6 节）；
- 订单簿的定时快照：引擎订阅增量，用自己的定时器发布整本簿（第 4 章第 5 节）；
- 带换月表的 K 线：交给连续期货的逻辑（第 3 章第 7 节）。

剩下的才需要一个客户端。

### 2.2 找哪个客户端

`registry.rs` 里的 `get_client` 按三级顺序找：

```rust
// 节选自 crates/data/src/engine/registry.rs
pub fn get_client(&mut self, client_id: Option<&ClientId>, venue: Option<&Venue>)
    -> Option<&mut DataClientAdapter>
{
    if let Some(client_id) = client_id {
        return self.clients.get_mut(client_id);           // ① 命令里显式指定了客户端
    }
    if let Some(v) = venue && let Some(client_id) = self.routing_map.get(v) {
        return self.clients.get_mut(client_id);           // ② 按交易所查路由表
    }
    self.get_default_client()                             // ③ 默认客户端
}
```

订阅和退订用的是它外面再包一层的 `get_command_client`：只要注册了 ID 为 `BACKTEST` 的客户端，所有订阅命令都发给它，不管命令里写的是什么。这是回测能用实盘的策略代码不改一行就跑起来的原因之一：策略照常写 `subscribe_quotes(instrument_id)`，回测里接到订阅的是回测数据客户端，它只记一笔账，真正的数据由回测引擎按时间推送。历史请求不走这个覆盖。

路由表的来源：客户端注册时（`register_client(client, routing)`）可以给一个交易所，作为它负责的路由；也可以注册一个默认客户端，兜底所有找不到路由的命令。接入富途时，`HKEX`、`NASDAQ` 这类交易所都应当路由到同一个富途数据客户端（第 38 章）。

### 2.3 按持有者计数

主线例子里，A 和 B 都订阅了 ETHUSDT 的报价。适配器应该只向交易所订阅一次，A 退订时也不能真的退订，因为 B 还在用。这件事由 `subscription.rs` 里的 `SubscriptionRegistry` 负责：

```rust
// 节选自 crates/data/src/subscription.rs
pub(crate) fn retain(&mut self, key: K, owner_id: UUID4, command: T) -> bool {
    if let Some(active) = self.entries.get_mut(&key) {
        if active.acquisitions.insert(owner_id) {
            active.owners += 1;                        // 已有人订阅：只加一个持有者
        }
        return false;                                  // 不需要真正下发
    }
    self.entries.insert(key, ActiveSubscription { command, acquisitions: …, owners: 1 });
    true                                               // 第一个持有者：需要真正下发
}

pub(crate) fn release(&mut self, key: &K) -> SubscriptionRelease<T> {
    // … owners 减一；还有人持有返回 Retained，归零才返回 Final(原订阅命令)
}
```

键是“数据类型加品种”（`SubscriptionKey::Quotes(instrument_id)` 等），持有者用订阅命令的 ID 区分，同一条命令重复到达不会重复计数。于是主线例子里：A 订阅时 `retain` 返回真，适配器真的订阅；B 订阅时返回假，适配器什么也不做；A 退订时 `release` 返回 `Retained`，适配器继续收数据；B 退订时返回 `Final`，适配器才真正退订。

组件这一侧也有一层去重：第 11 章提到的 `DataActorCore::subscribe_bars` 会先在组件自己的订阅表里登记，同一个组件对同一个主题重复订阅，命令只发一次。

![两个策略订阅、退订同一品种报价时，数据引擎的持有者计数和发给适配器的命令：只有第一次订阅和最后一次退订会真正下发](/nautilus-trader/figures/data-engine-subscriptions.svg)

怎么读这张图：上面一行是组件发出的四条命令，中间是登记表里持有者数量的变化，下面是真正发给适配器的命令。注意中间两条命令在最下面一行没有对应的动作。

## 3. 行情到达：先写缓存，再发布 {#process}

适配器收到的行情经通道（实盘）或数据迭代器（回测）进入 `DataEngine::process_data`，按类型分派。以报价为例：

```rust
// 节选自 crates/data/src/engine/dispatch.rs（handle_quote）
pub(super) fn handle_quote(&self, quote: QuoteTick) {
    if let Err(e) = self.cache.as_ref().borrow_mut().add_quote(quote) {
        log_error_on_cache_insert(&e);                       // ① 先写缓存
    }
    for synthetic_quote in self.synthetic_quotes_from_quote(quote) {
        let topic = switchboard::get_quotes_topic(synthetic_quote.instrument_id);
        msgbus::publish_quote(topic, &synthetic_quote);       // ② 以它为成分的合成品种
    }
    let topic = switchboard::get_quotes_topic(quote.instrument_id);
    msgbus::publish_quote(topic, &quote);                     // ③ 发布原报价
}
```

“先写缓存再发布”保证了策略在 `on_quote` 里调用 `cache.quote(...)` 时，拿到的就是这一条（官方文档 Cache 一页也写明了这个顺序）。一个细节：如果有合成品种以这个品种为成分，合成报价会先于原报价发布。成交、标记价、指数价、资金费率都是同样的模式；K 线走第 11 章的 `process_engine_bar`，可选地检查时间戳顺序；品种更新写进缓存后以 `on_instrument` 通知订阅者。

订单簿稍有不同。增量和深度快照不写进缓存的“历史”，而是直接发布；缓存里那本订单簿由每个品种一个的 `BookUpdater` 订阅这些增量来维护。`buffer_deltas` 打开时，引擎把增量攒起来直到遇到 `F_LAST` 才一起发布（第 4 章第 2 节）。`emit_quotes_from_book`、`emit_quotes_from_book_depths` 两个配置项让引擎在订单簿的最优价变化时顺便生成并发布一条报价，适合只有订单簿数据、策略却想用报价的场景。

## 4. 历史请求 {#requests}

主线例子里，A 调用了 `request_trades(instrument_id, start=一小时前)`。这次请求在数据引擎里经历：

1. <strong>登记。</strong>组件先用请求 ID 在总线上登记响应处理器（第 15 章第 6 节），再把 `RequestTrades` 命令发给数据引擎。
2. <strong>预处理。</strong>引擎检查参数：带 `bar_types` 的，先建历史模式的 K 线聚合器（第 11 章第 7 节）；带换月表的，交给连续期货逻辑；配置了数据目录的，可能直接从目录读。
3. <strong>分派。</strong>`dispatch_request_to_client` 把请求记进 `inflight_requests`，用 `get_client` 找客户端（这里不走 `BACKTEST` 覆盖），调用适配器的 `request_trades`。适配器返回错误时，错误信息被包上 “Data client … request failed”；第 11 章在回测里看到的正是这条。
4. <strong>响应。</strong>适配器拿到数据后，把一个 `DataResponse` 送回引擎的 `DataEngine.response` 端点。引擎从 `inflight_requests` 里取出原请求，裁剪超出请求时间范围的数据，品种类的响应顺手写进缓存，喂给历史模式的聚合器（如果有），最后按关联 ID 把响应送回组件，组件在 `on_historical_trades` 里收到。

适配器的请求可以部分失败：`request_failed` 会记一条错误日志，同时保留已经返回的那部分数据，照常完成请求。大跨度的请求还可以被引擎拆成按时间分段的子请求，再把结果合并起来（`time_range.rs`），这时响应会分多次到达（第 15 章说的“未完成的响应只调用、不删除处理器”就是为它准备的）。

## 5. 外部客户端与回放 {#external}

`DataEngineConfig` 里有一个 `external_clients` 列表：列在里面的客户端 ID 被当作“外部”的，引擎不会把订阅发给它们，只在 `subscriptions_external` 里登记，假定数据由别的进程经外部消息流送进来（第 36 章）。配置了数据目录时，请求可以从 Parquet 文件里读取，这部分在第 25 章。

::: warning 常见误区
- **以为每次 `subscribe_*` 都会发到适配器。** 内部 K 线、合成品种、订单簿快照在引擎内部解决；其余的只有第一个持有者才真正下发。
- **以为一个组件退订了，数据就停了。** 只要还有别的持有者，适配器继续订阅，其他组件照常收到。
- **回测里在订阅命令里写了具体的客户端 ID，以为会生效。** 注册了 `BACKTEST` 客户端时，所有订阅都发给它。
- **在 `on_quote` 里读缓存担心读到旧值。** 引擎先写缓存再发布，读到的就是这一条。
- **以为订单簿增量也进了缓存的行情历史。** 增量直接发布，缓存里的簿由 `BookUpdater` 维护，没有增量历史。
- **请求失败就以为什么数据都没有。** 部分失败会保留已返回的数据，照常完成请求。
:::

## 本章结论

数据引擎站在数据客户端和其余组件之间：订阅命令先看能否在引擎内部解决（内部 K 线、合成品种、订单簿快照、连续期货），否则按“显式客户端、交易所路由、默认客户端”找到客户端，回测里一律交给 `BACKTEST` 客户端；客户端上的订阅按命令 ID 计持有者，第一个持有者到来时才真正订阅，最后一个离开时才真正退订。行情到达后先写缓存、再发布合成品种的派生报价、最后发布原报价；订单簿增量直接发布，由 `BookUpdater` 维护缓存里的簿。历史请求先登记、再分派、响应经裁剪和缓存后按关联 ID 送回请求者。

## 检查理解

1. 策略 A 订阅了 `ETHUSDT.BINANCE-1-MINUTE-LAST-INTERNAL`，策略 B 订阅了 ETHUSDT 的成交。适配器会收到几次成交订阅？A 退订 K 线以后，B 还能收到成交吗？

   <details><summary>参考答案</summary>

   一次。A 的 K 线订阅在引擎内部变成一条对 ETHUSDT 成交的订阅（以聚合器的名义），B 的成交订阅是同一个键，第二次只增加持有者，不再下发。A 退订 K 线时，聚合器的那份持有者被释放，计数从 2 变成 1，返回 `Retained`，适配器不退订，B 照常收到成交。

   </details>

2. 实盘里富途数据客户端注册时没有给任何交易所路由，也没注册成默认客户端。策略 `subscribe_quotes(InstrumentId::from("00700.XHKG"))` 会怎样？

   <details><summary>参考答案</summary>

   命令没有指定客户端，交易所 `XHKG` 在路由表里查不到，也没有默认客户端，`get_client` 返回 `None`，引擎无法下发这条订阅，策略收不到数据。修正办法是注册客户端时给出它负责的交易所路由，或注册为默认客户端，或在订阅时显式传入客户端 ID。

   </details>

3. 策略在 `on_quote` 里调用 `cache.quote(&instrument_id)`，拿到的是触发这次回调的报价，还是上一条？为什么？

   <details><summary>参考答案</summary>

   是触发这次回调的报价。`handle_quote` 先 `add_quote` 写进缓存，再发布到总线，策略的处理器是在发布时被调用的，这时缓存里已经是这一条了。

   </details>

## 参考资料

- 官方文档：[Data](https://nautilustrader.io/docs/latest/concepts/data/) · [Architecture](https://nautilustrader.io/docs/latest/concepts/architecture/) · [Cache](https://nautilustrader.io/docs/latest/concepts/cache/)
- 源码：[`crates/data/src/engine/`](https://github.com/nautechsystems/nautilus_trader/tree/develop/crates/data/src/engine) · [`crates/data/src/client.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/data/src/client.rs) · [`crates/data/src/subscription.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/data/src/subscription.rs)
- 配图由 `scripts/generate-nautilus-trader-figures.py` 生成。

数据进来了，策略据此下单。下一章看订单在离开系统之前要通过的那道关卡。[第 19 章：RiskEngine](./risk-engine.md)。
