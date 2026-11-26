---
title: "第 16 章：Cache：状态、索引与持久化接口"
description: NautilusTrader 的 Cache 存了哪些东西、为什么分成 35 个字段和 31 张索引；一张订单在它的一生中怎样进出各个索引；谁能写、谁只能读，读到的为什么是快照；行情历史的容量与淘汰；数据库后端的“尽力持久化”语义与启动恢复；长时间运行时的清理。
---

# 第 16 章：Cache：状态、索引与持久化接口

[全书目录](./index.md) · [上一章](./message-bus.md) · [下一章](./clock.md)

::: tip 本章学习目标
能说出缓存里存了哪几类东西、哪些有容量上限；能跟着一张订单的状态变化，说出它在每一步属于哪几个索引集合；知道用户代码通过什么接口读缓存、读到的是不是“活”的；知道缓存写入数据库失败时会怎样、重启时哪些东西能恢复；知道长时间运行的节点怎样控制缓存的内存。

**源码版本：** `develop` 分支，提交 `364254f`（2026-11-18）。缓存在 `crates/common/src/cache/`：`mod.rs`（结构与读写）、`index.rs`（索引）、`api.rs`（面向用户的读接口）、`view.rs`（面向适配器的只读视图）、`refs.rs`（带生命周期的借用）、`database.rs`（数据库适配器 trait）、`config.rs`、`bounded.rs`。

**对应官方文档：** [Cache](https://nautilustrader.io/docs/latest/concepts/cache/)
:::

前面很多章都在说“写进缓存”“从缓存读”：数据引擎先写缓存再发布行情（第 4、11 章），执行引擎先更新缓存里的订单和仓位再发布事件（第 6、8 章），策略在回调里读缓存拿最新状态（第 10 章）。这一章看缓存本身：它的结构为什么是这个样子，读和写的权限怎样分开，以及它和数据库之间的关系。

主线例子是一张 ETHUSDT 限价买单：跟着它从创建到成交，看它在缓存里留下了哪些记录。

## 1. 缓存里有什么 {#contents}

`Cache`（`cache/mod.rs`）有 35 个字段，可以分成五组：

| 类别 | 主要字段 | 说明 |
| :--- | :--- | :--- |
| 参考数据 | `currencies`、`instruments`、`synthetics`、`instrument_closes` | 第 2、3 章的币种和品种 |
| 行情 | `quotes`、`trades`、`bars`、`books`、`own_books`、`mark_prices`、`index_prices`、`funding_rates`、`instrument_statuses`、`custom_data`、`greeks` 等 | 有界的历史和最新状态 |
| 交易对象 | `orders`、`order_lists`、`positions`、`position_snapshots`、`accounts` | 第 5～7 章的订单、仓位、账户 |
| 路由与归属 | `client_routes`、`client_accounts`、`default_client_id`、`external_order_claims` 等 | 哪个交易所用哪个客户端、外部订单归哪个策略 |
| 其他 | `general`（键到字节）、`index`、`database`、`config` | 组件状态、索引、数据库后端 |

两个细节值得一提。订单、仓位、账户存的是 `SharedCell<T>`，也就是可共享、可内部修改的单元，引擎更新时原地替换内容；行情历史存的是 `BoundedVecDeque<T>`，一个有容量上限的双端队列，新的在前面，满了就从后面淘汰最老的。第 12 章提到的 `cache.bars()` 返回“第 0 个是最新的”，就是这个结构的直接结果。

## 2. 索引：31 张表回答常见查询 {#index}

`CacheIndex`（`cache/index.rs`）有 31 个字段，全部是 ID 到 ID 集合的映射或 ID 集合，它们只存 ID，不存对象。分成三类：

- <strong>归属关系。</strong>`venue_orders`、`venue_positions`、`venue_accounts`、`instrument_orders`、`instrument_positions`、`strategy_orders`、`strategy_positions`、`account_orders`、`account_positions`、`exec_algorithm_orders`、`exec_spawn_orders`，以及反向的 `order_strategy`、`order_client`、`order_position`、`position_strategy`、`position_orders`、`position_oms`。
- <strong>ID 对照。</strong>`venue_order_ids`（交易所订单号到本地订单号）和 `client_order_ids`（反方向）。交易所的回报里常常只有交易所订单号，适配器和执行引擎靠前者找回本地订单（第 0 章检查理解第 4 题）。
- <strong>状态集合。</strong>`orders`、`orders_active_local`、`orders_inflight`、`orders_open`、`orders_closed`、`orders_emulated`、`orders_pending_cancel`、`positions`、`positions_open`、`positions_closed`，以及 `strategies`、`exec_algorithms`。

有了这些集合，“某个策略在某个品种上所有挂着的单”这类查询就变成几次集合求交，不需要遍历所有订单。代价是每次订单状态变化都要维护这些集合，而且维护必须和订单本身的变化保持一致。

## 3. 主线例子：一张限价单的足迹 {#footprint}

策略下了一张 `BUY 1 ETH @ 423.50` 的限价单，看它在每一步之后属于哪些状态集合：

| 步骤 | 订单状态 | 所在的状态集合 | 其他变化 |
| :--- | :--- | :--- | :--- |
| `add_order` | `INITIALIZED` | `orders`、`orders_active_local` | 写入 `strategy_orders`、`instrument_orders`、`venue_orders` 等归属索引 |
| 提交后 | `SUBMITTED` | `orders`、`orders_inflight` | 离开 `orders_active_local`；`OrderSubmitted` 带来账户 ID，写入 `account_orders` |
| 交易所接受 | `ACCEPTED` | `orders`、`orders_open` | 记下 `venue_order_ids` |
| 全部成交 | `FILLED` | `orders`、`orders_closed` | 仓位建立，写入 `order_position`、`position_orders` 等 |

驱动这些变化的是 `Cache::update_order`（`cache/mod.rs`），执行引擎每处理一个订单事件就调用它一次：

```rust
// 节选自 crates/common/src/cache/mod.rs（Cache::update_order）
pub fn update_order(&mut self, event: &OrderEventAny) -> anyhow::Result<OrderAny> {
    // 先按本地订单号找；找不到就用事件里的交易所订单号反查
    let client_order_id = /* … */;
    let order_cell = self.orders.get(&client_order_id).cloned()?;
    // 先在副本上应用：apply 失败（例如非法的状态转移）时，缓存里的订单保持不变
    let mut snapshot = order_cell.borrow().clone();
    snapshot.apply(event.clone())?;
    // … 校验交易所订单号的归属
    *order_cell.borrow_mut() = snapshot.clone();          // 成功后整体替换
    if let Err(e) = self.refresh_order(&snapshot) {      // 按新状态维护各个索引
        log::error!("Error updating order in cache: {e}");
    }
    Ok(snapshot)
}
```

“先在副本上应用、成功再替换”保证了一件重要的事：第 5 章那张转移表拒绝的事件，不会让缓存里的订单停在一个改了一半的状态。`refresh_order` 则按订单的新状态，把它加进或移出 `orders_active_local`、`orders_inflight`、`orders_open`、`orders_closed`、`orders_pending_cancel`、`orders_emulated` 这些集合；只要订单的 `is_open()`、`is_closed()` 这些判断是对的，索引就是对的。

![一张限价单在四个时刻属于哪些状态集合：本地、在途、挂单、已结束依次点亮，交易所订单号在接受时登记，仓位索引在成交时建立](/nautilus-trader/figures/cache-order-footprint.svg)

怎么读这张图：每一行是一个状态集合，每一列是一个时刻，橙色格子表示订单在那个时刻属于这个集合。注意 `orders` 那一行始终是橙色的，订单从不离开总表，直到被清理。

## 4. 谁能写，谁只能读 {#access}

缓存的写方法（`add_order`、`update_order`、`add_position`、`add_quote`、`add_bar` 等）都是 `&mut self` 的，只有持有 `Rc<RefCell<Cache>>` 的引擎会调用：数据引擎写行情和品种，执行引擎写订单和仓位，组合和账户管理器写账户。其他代码拿到的都是只读接口，并且有三种：

<strong>CacheApi：给 Actor 和策略。</strong>`api.rs` 的说明是：单个对象的读取尽量返回拥有所有权的快照，这样组件代码不会持有指向活缓存的借用；复数形式的读取返回所有匹配对象的快照，并特意取名为“批量读取”；热路径上更推荐只要数量、ID 或 `has_*` 的方法。这就是第 0 章第 6.2 节说的“快照语义”：Python 里拿到的订单不会自己变，Rust 用户代码通过 `CacheApi` 读到的也一样。

<strong>CacheView：给适配器。</strong>`view.rs` 的注释写明：适配器拿到的是这个只读视图，而不是可变的缓存句柄，这样缓存的写入始终由数据引擎和执行引擎掌握。第 38 章翻译的开发指南里那条“适配器不要直接写缓存”，在类型上就是这样保证的。

<strong>带生命周期的借用：给引擎内部。</strong>`refs.rs` 里的类型包着一个 `Ref` 或 `RefMut`，借用随作用域结束。注释给了这样设计的理由：如果有人试图跨一次缓存修改持有它，运行时会 panic，“大声失败好过克隆带来的悄悄过期”。需要跨边界交出数据时，用对应的 `*_owned` 方法拿快照。

## 5. 行情历史的容量 {#capacity}

`CacheConfig` 里有两个容量参数：`data_capacity`（报价、成交、标记价、指数价、资金费率等，每个品种各自一份）和 `bar_capacity`（每种 K 线各自一份），默认都是 10,000，取值范围 1 到 1,000,000。满了就淘汰最老的一条。所以同时用 1 分钟和 5 分钟 K 线时，各自能保存 10,000 根；要靠缓存做长回看的指标预热（第 12 章第 7 节），要先确认容量够。

## 6. 数据库后端：尽力持久化 {#database}

缓存可以接一个实现了 `CacheDatabaseAdapter`（`database.rs`）的后端，仓库自带 Redis 和 PostgreSQL 两种（第 36 章）。接上以后，订单、仓位、账户、品种、组件状态等的写入都会同时交给后端。

官方文档的“持久化失败策略”是理解这一层的关键：缓存在内存里的修改不依赖可选的持久化，持久化失败只记一条 ERROR 日志，不会让缓存操作失败，也不会打断事件发布或命令派发。对排队写入的后端，失败可能发生在进入写入通道时，也可能发生在后台的数据库线程里，两种都只记日志。所以缓存操作成功只确认了内存里的修改，既不确认已进入写入队列，也不确认已落盘，重启后恢复出来的状态可能和运行时不同。想在持久化出错时停机，就打开第 14 章的 `shutdown_on_error`，持久化错误日志同样会触发有序关停。

启动恢复时，缓存从后端读回已成功保存的通用数据、币种、品种、合约收盘、合成品种、账户、订单和仓位（PostgreSQL 还能恢复希腊值和收益率曲线）。有界的行情历史不恢复，后端也不是完整的事件档案；多个节点即使共用一个数据库命名空间，也各自拥有自己的内存缓存，不会互相同步。这就是为什么实盘重启除了恢复缓存，还必须做一次对账（第 34 章）：缓存告诉你“上次退出时我以为的状态”，对账告诉你“交易所现在的真实状态”。

## 7. 长时间运行：清理 {#purge}

缓存里的订单、仓位、账户事件会一直累积。缓存提供两类清理：按对象的 `purge_order`、`purge_position`、`purge_instrument`（跳过还没结束的订单和仓位），以及按时间的 `purge_closed_orders`、`purge_closed_positions`、`purge_account_events`（只清理关闭时间早于缓冲期的）。实盘的执行引擎配置可以让它们定时运行，官方文档给的建议起点是：每 15 分钟清理一次，保留最近 60 分钟。清理默认只动内存，要同时删除数据库里的记录得显式传 `purge_from_database=True`。

两条提醒来自官方文档：`purge_instrument` 会连带清掉这个品种的订单簿和行情历史，别的组件还在用时会导致查不到品种；HEDGING 下发生过虚拟反手的那个已平仓位，在它的订单还可能收到成交之前不要清理，否则引擎找不到路由新成交的历史，会拒绝这些成交。

::: warning 常见误区
- **以为通过 `CacheApi` 拿到的订单会随事件更新。** 它是快照，要最新状态就重新读。
- **在适配器里写缓存。** 适配器拿到的是只读的 `CacheView`，状态应当经事件交给引擎去写。
- **以为缓存操作成功就代表已经持久化。** 持久化是尽力而为，失败只记日志。
- **以为重启后行情历史还在。** 有界的行情历史不恢复，指标需要重新预热。
- **以为恢复了缓存就不必对账。** 缓存只是上次退出时的本地认知，实盘重启必须对账。
- **长时间运行却不配置清理。** 已关闭的订单、仓位和账户事件会一直占用内存。
:::

## 本章结论

缓存是内核里唯一的状态仓库：35 个字段存放参考数据、有界的行情历史、订单仓位账户和路由信息，31 张只存 ID 的索引把常见查询变成集合运算。订单的每个事件经 `update_order` 先在副本上应用、成功后整体替换，再按新状态维护索引。写入只属于数据引擎、执行引擎和组合，Actor 和策略通过返回快照的 `CacheApi` 读，适配器通过只读的 `CacheView` 读。数据库后端是尽力而为的持久化，恢复的是参考数据和交易对象，不是行情历史，也不能替代对账。

## 检查理解

1. 交易所的成交回报里只有交易所订单号 `V-778`，没有本地订单号。执行引擎怎样在缓存里找到这张单？如果这张单在接受时没有记下交易所订单号，会怎样？

   <details><summary>参考答案</summary>

   `update_order` 先按事件里的本地订单号找，找不到就用事件的交易所订单号去 `venue_order_ids` 索引反查。这个索引是在订单收到带交易所订单号的事件（通常是 `OrderAccepted`）时由 `refresh_order` 登记的。如果没有登记过，反查失败，返回 `OrderError::NotFound`，这笔回报无法对应到本地订单，需要对账来处理。

   </details>

2. 一个 `OrderCanceled` 事件到达时，订单在缓存里是 `FILLED`。缓存里的订单会怎样？

   <details><summary>参考答案</summary>

   `FILLED` 状态下 `Canceled` 不在第 5 章的转移表里，`apply` 返回 `InvalidStateTransition`。因为 `update_order` 是在副本上应用的，失败时直接返回错误，缓存里的订单仍是原来的 `FILLED`，索引也不变。

   </details>

3. 节点每天运行 20 小时，订单量很大，内存一直上涨。应当打开哪些配置？清理会不会影响当天的盈亏统计？

   <details><summary>参考答案</summary>

   在实盘执行引擎配置里打开定时清理，例如 `purge_closed_orders_interval_mins=15`、`purge_closed_orders_buffer_mins=60`，以及对应的仓位和账户事件清理。按时间的清理只清理关闭时间早于缓冲期的订单和仓位，以及较早的账户事件（最新一条总会保留）。被清理的仓位不再出现在缓存的查询里，如果盈亏统计依赖缓存里的历史仓位，需要在清理之前另行记录，或者把缓冲期设得足够长。

   </details>

## 参考资料

- 官方文档：[Cache](https://nautilustrader.io/docs/latest/concepts/cache/)
- 源码：[`crates/common/src/cache/mod.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/common/src/cache/mod.rs) · [`index.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/common/src/cache/index.rs) · [`api.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/common/src/cache/api.rs) · [`view.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/common/src/cache/view.rs) · [`refs.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/common/src/cache/refs.rs) · [`database.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/common/src/cache/database.rs)
- 配图由 `scripts/generate-nautilus-trader-figures.py` 生成。

缓存里每一条记录都带着时间戳，计时器也要知道“现在几点”。下一章看时间从哪里来。[第 17 章：Clock 与计时器](./clock.md)。
