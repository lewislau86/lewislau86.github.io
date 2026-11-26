---
title: "第 20 章：ExecutionEngine：路由命令、处理订单事件与成交"
description: 执行引擎的两个方向：命令怎样校验、怎样选出执行客户端、提交时还要检查什么；订单事件回来后怎样找到订单、更新缓存、按什么顺序发布；成交怎样决定 OMS 类型和仓位 ID、怎样去重和处理超额成交、怎样开仓、更新和翻转仓位。
---

# 第 20 章：ExecutionEngine：路由命令、处理订单事件与成交

[全书目录](./index.md) · [上一章](./risk-engine.md) · [下一章](./order-emulator.md)

::: tip 本章学习目标
能说出执行引擎为一条命令选执行客户端的顺序，以及找不到时会发生什么；能列出提交命令在交给客户端前的几项检查；能按顺序说出一笔成交在执行引擎里经过的步骤，知道缓存、Portfolio、仓位和三类主题各在哪一步更新或发布；能解释 OMS 类型和仓位 ID 怎样决定，以及 NETTING 和 HEDGING 下仓位翻转的区别。

**源码版本：** `develop` 分支，提交 `364254f`（2026-11-18）。执行引擎在 `crates/execution/src/engine/mod.rs`，配置在 `engine/config.rs`，仓位 ID 生成器在 `crates/common/src/generators/position_id.rs`，主题名在 `crates/common/src/msgbus/switchboard.rs`。

**对应官方文档：** [Execution](https://nautilustrader.io/docs/latest/concepts/execution/)（Execution flow、OMS、Cancel-all routing、Own order books、Overfills 几节）
:::

上一章结束时，通过风控的命令被送到 `ExecEngine.queue_execute`。执行引擎是命令离开系统前的最后一站，也是订单事件回到系统的第一站：它把命令交给对应的执行客户端，又把客户端回报的事件写进缓存、换算成仓位，再发布给策略。

主线例子：策略 `EMACross-001` 提交 `BUY 1 ETHUSDT.BINANCE LIMIT @ 423.50`，节点注册了一个 `BINANCE` 执行客户端（OMS 类型 NETTING）。这张单先成交 0.4，再成交 0.6。

## 1. 两个方向、四个端点 {#endpoints}

执行引擎在内核构造时注册四个端点（第 14 章、第 15 章）：

| 端点 | 方向 | 用途 |
| --- | --- | --- |
| `ExecEngine.execute` | 命令 | 立即执行一条交易命令 |
| `ExecEngine.queue_execute` | 命令 | 排队执行，风控放行后用它 |
| `ExecEngine.process` | 事件 | 处理执行客户端回报的订单事件 |
| `ExecEngine.reconcile_execution_report` | 报告 | 对账，第 34 章 |

`execute` 最终调用 `execute_command`，`process` 调用 `handle_event`。实盘里执行客户端不直接调用引擎：它把事件通过通道交给运行器，运行器的 `handle_exec_event` 再把事件发到 `ExecEngine.process`（第 30 章）。回测里模拟撮合引擎直接发到同一个端点。

执行客户端在启动前注册进来，相关方法有四个：

- `register_client`：按 `ClientId` 登记客户端，重复登记报错；同时在缓存里记下这个客户端对应的账户 ID。
- `register_default_client`：登记并设为默认客户端，找不到其他路由时用它。
- `register_venue_routing(client_id, venue)`：把一个场所路由到某个客户端；同一场所不能改路由到另一个客户端。
- `register_oms_type(strategy_id, oms_type)`：为某个策略登记 OMS 类型覆盖，第 5 节会用到。

配置里的 `external_clients` 列出“外部”客户端：它们不在本进程内，命令要通过总线转发出去（第 2 节）。

## 2. 命令：校验与路由 {#routing}

`execute_command` 收到命令后先做三件事。

**第一，校验提交。** `validate_submission` 只看提交类命令：订单已经不在可提交的状态（比如已被拒绝），这条提交被当作过期，记一条警告后跳过；订单已经发给过某个客户端，这条提交被当作重复，同样跳过；订单列表不合规（比如指定了仓位 ID 却包含多个品种），生成 `OrderDenied`。

**第二，处理外部客户端。** 如果命令的 `client_id` 在 `external_clients` 里，引擎把命令原样发布到 `commands.trading.{client_id}` 主题，把订单标记为已发出，然后返回。外部客户端自己订阅这个主题，自己负责后续的处理。

**第三，选执行客户端。** `find_client_for_command` 按下面的顺序找：

1. 命令带了 `client_id`，且这个客户端已登记，就用它。
2. 订单已经有账户 ID（只有提交、改单、撤单和查询账户这几种命令会去查），取账户 ID 的发行方，比如 `BINANCE-001` 的 `BINANCE`：先找同名客户端，再查场所路由表。
3. 按命令里品种的场所查路由表。
4. 用默认客户端。

四步都找不到，引擎调用 `deny_unroutable_command`：提交生成 `OrderDenied`，原因是 `NoExecutionClient`。

主线例子里，策略没有指定 `client_id`，订单刚创建、还没有账户 ID（账户 ID 随 `OrderSubmitted` 才到，第 16 章），所以落到第 3 步：场所 `BINANCE` 路由到 `BINANCE` 客户端。等这张单被提交之后，改单和撤单会在第 2 步就按账户 ID 找到同一个客户端。

::: tip 和官方文档的差别
官方文档 Cancel-all routing 一节写的顺序是“显式 `client_id` → 场所路由 → 默认客户端”。这对 `CancelAllOrders` 是准确的，因为这类命令不按账户查。对单张订单的改单和撤单，源码在场所路由之前还多一步“按订单账户 ID 的发行方查找”。
:::

## 3. 提交：交给客户端之前 {#submit}

选到客户端后，`SubmitOrder` 进入 `handle_submit_order`：

1. 如果缓存里还没有这张订单，从命令携带的 `order_init` 重建并加入缓存。
2. 检查这个客户端是否处理订单所在的场所（`handles_order_venue`），不处理就拒绝，原因是 `ClientVenueMismatch`。
3. `check_position_id_against_oms`：如果这张单的有效 OMS 类型是 NETTING，而命令带了仓位 ID，这个 ID 必须等于 `{instrument_id}-{strategy_id}`，否则拒绝，原因是 `InvalidPositionId`，说明里会建议改用 HEDGING。
4. `claim_order_clients`：在缓存里记下这张单归哪个客户端，以后的成交按这个记录找 OMS 类型（第 5 节）。
5. 如果开启了 `manage_own_order_books`，把订单加入自有订单簿（第 4 章）。
6. 调用 `client.submit_order(cmd)`。返回错误就拒绝，原因是 `SubmitFailed`；成功就把订单标记为已发出。

第 3 步正好放过最常见的平仓写法：`close_position(position)` 会带上 `position.id`，在 NETTING 下它恰好就是确定的那个 ID。想给仓位起自定义 ID，要把策略的 OMS 类型设为 HEDGING。

`OrderSubmitted` 不是执行引擎产生的，而是执行客户端在发出请求时生成的，它和其他回报一样经 `ExecEngine.process` 回到引擎（第 8 章）。

其他命令的处理更短：改单、撤单、查询各自交给客户端的对应方法。`CancelAllOrders` 稍特别，引擎为选定的客户端和账户生成三类子命令：给客户端一条 `CancelAllOrders`，给订单仿真器一条 `CancelAllOrders`，给每张仍在执行算法手里的订单各一条 `CancelOrder`。它只选一个客户端，不会广播到所有客户端。

## 4. 事件：找订单、更新缓存、发布 {#events}

`ExecEngine.process` 收到订单事件后，`apply_order_event` 先找订单。事件里的 `client_order_id` 在缓存里找得到就用它；找不到，再用事件里的 `venue_order_id` 反查 `client_order_id`。两样都找不到，记一条错误后丢弃（价差合约的单腿成交另有处理，不在本书范围内）。

找到订单后，非成交事件只走一条短路径 `update_cached_order`：

1. `cache.update_order(event)`：把事件应用到订单（订单状态机在这里检查转换是否合法，第 5 章），再更新缓存的索引。
2. 不合法的转换记一条警告后丢弃；如果失败的是拒绝、撤销、过期这类终态事件，引擎会把订单从自有订单簿中强制移除，避免留下“幽灵”挂单。
3. 订单不再处于可提交的状态时，清掉“已发出”的标记。
4. 配置了 `snapshot_orders` 且缓存有数据库后端时，保存一份订单快照。
5. 会影响冻结资金的事件（`Accepted`、`Canceled`、`Expired`、`Rejected`、`Updated`）发到 `Portfolio.update_order`（第 22 章）。

更新成功后发布事件。每个事件都先发到 `events.order.{strategy_id}`，策略的 `on_order_*` 回调从这里收到；多数事件还会再发到一个按类型和品种命名的主题，比如 `events.order_canceled.ETHUSDT.BINANCE`，供只关心某一类事件的组件订阅。`Filled` 不走这条按类型的发布，它的品种主题在成交处理里单独发布（第 5 节）。

## 5. 成交 {#fills}

成交是执行引擎最重的一条路径，因为一笔成交既要改订单，又要改仓位，还要通知 Portfolio。`apply_order_event` 对 `OrderFilled` 的处理顺序是：

1. **跳过零数量成交。**
2. **决定 OMS 类型。** `determine_oms_type` 先看策略有没有登记覆盖（`register_oms_type`，且不是 `UNSPECIFIED`）；没有，就用这张单所属客户端的 OMS 类型（第 3 节第 4 步记下的归属）；归属也找不到，退回 NETTING。如果仓位已经在缓存里，以缓存记录的 OMS 类型为准。
3. **决定仓位 ID。** 缓存里已经为这张单记了仓位 ID 就用它；否则 NETTING 用 `{instrument_id}-{strategy_id}`，HEDGING 先用场所在成交里给的仓位 ID，没有再由生成器生成。生成的 ID 形如 `P-20261119-093000-001-001-1`：前缀、UTC 日期和时间、交易者标签、策略标签、该策略的计数；翻转产生的新仓位末尾再加 `F`。决定后把 ID 写回成交的 `position_id`。
4. **校验。** 同一个 `trade_id`、同方向、同价格、同数量的成交已经应用过，作为重复跳过；`trade_id` 相同但价格不同，作为价格更正（restatement），只重算均价，不改数量；仓位里已经有这个 `trade_id`，也作为重复跳过；最后检查超额成交（第 7 节）。
5. **更新订单。** 同第 4 节的 `update_cached_order`，但这一步不发 Portfolio。
6. **处理成交 `handle_order_fill`。** 先把成交发到 `Portfolio.update_order`（保证金账户上的价差合约成交例外）；再更新仓位：没有仓位就开仓，仓位已平就重开，这笔成交会让仓位反向就翻转（第 6 节），其余情况更新仓位；如果订单是 OTO 的父单，把刚开出的仓位 ID 写进子单；最后发布到 `events.order_filled.{instrument_id}`。
7. **发布订单事件**到 `events.order.{strategy_id}`。
8. **发布仓位事件**（`PositionOpened`、`PositionChanged`、`PositionClosed`）到 `events.position.{strategy_id}`。

任何一步决定不应用这笔成交（重复、超额、找不到订单），引擎都把原样的事件发布到 `events.order_fill_declined.{instrument_id}`。原因只写在日志里，事件本身不带。需要确认自己的成交是否被接受的适配器可以订阅这个主题。

主线例子按这个顺序走一遍：

| 成交 | 仓位 ID | 订单 | 仓位事件 |
| --- | --- | --- | --- |
| 0.4 @ 423.50 | `ETHUSDT.BINANCE-EMACross-001` | `PARTIALLY_FILLED` | `PositionOpened` |
| 0.6 @ 423.50 | 同上 | `FILLED` | `PositionChanged` |

第一笔成交时缓存里没有这个仓位，于是开仓。策略先在 `on_order_filled` 里看到成交，再在 `on_position_opened` 里看到仓位，因为第 7 步在第 8 步之前。不过两个回调被调用时，缓存里的订单和仓位都已经更新完，Portfolio 也已经在第 6 步收到了这笔成交，所以在 `on_order_filled` 里查询仓位，查到的已经是新仓位。

如果在策略配置里把 OMS 类型设为 HEDGING，引擎会为这个策略登记覆盖。同样两笔成交，第一笔由生成器产生一个新的仓位 ID，第二笔通过缓存里“这张单对应的仓位”找到同一个 ID。之后再下一张买单，会开出第二个仓位，而不是加到第一个上。

## 6. 仓位翻转 {#flip}

持有多 1 ETH 时卖出 1.5 ETH，仓位不能直接变成负数。`flip_position` 用 `split_for_position_flip` 把这笔成交拆成两份：第一份 1 ETH 用来平掉原仓位，第二份 0.5 ETH 开一个新的空头仓位。成交带手续费时按数量比例拆分；成交没带手续费时，引擎记一条警告，两份都不带手续费。

两种 OMS 类型的区别在新仓位的 ID：

- **NETTING：** 新仓位沿用同一个 ID。引擎先把平掉的那一段存为仓位快照（第 6 章），再在同一个 ID 上开新仓位。
- **HEDGING：** 新仓位由生成器生成一个带 `F` 后缀的新 ID，原仓位保持已平状态。

NETTING 下“平仓后又开仓”（不是翻转，而是先平再买）也走类似的路径：引擎发现仓位已平，先把它存为快照，再在同一个 ID 上重开。`carry_replay_events_on_reopen` 决定重开后是否保留旧周期的事件，以便后来的成交作废（`OrderFillVoided`）还能找到它们。回测默认不保留；实盘的 `LiveExecutionEngineConfig` 总是保留。

![执行引擎的两个方向：上排是命令路径，从入口经提交校验、选执行客户端到提交前检查，交给执行客户端；下排是事件路径，从找订单、成交前置处理、更新订单到仓位处理，最后按顺序发布三类主题](/nautilus-trader/figures/execution-engine-flow.svg)

怎么读这张图：上排从左往右是命令路径，下排从右往左是事件路径，中间的执行客户端把两者连起来。上排每一步都可能以 `OrderDenied` 结束；下排每一步都可能以“丢弃”结束，被丢弃的成交发到 `order_fill_declined`。下排第二格和最左一格是成交独有的步骤，非成交事件更新完订单就直接发布到 `events.order.{strategy_id}`。最底下的一行是成交时三次发布的顺序。

## 7. 超额成交与常用配置 {#config}

超额成交是指一张单的累计成交量超过下单数量，比如 100 的单收到合计 110 的成交。它可能是交易所真的多成交了，也可能是同一笔成交换了 `trade_id` 被重复推送，单看数量无法区分。`check_overfill` 的行为由 `allow_overfills` 决定：

- `false`（默认）：记一条警告，拒绝这笔成交，发到 `order_fill_declined`。
- `true`：记一条警告，照常应用，订单的 `overfill_qty` 记下多出的部分，状态变为 `FILLED`，`leaves_qty` 取零。

由对账产生的成交另有规则，第 34 章再讲。

`ExecutionEngineConfig` 里和本章相关的选项：

| 选项 | 默认 | 作用 |
| --- | --- | --- |
| `load_cache` | `true` | 启动时从缓存加载订单和仓位 |
| `manage_own_order_books` | `false` | 维护自有订单簿 |
| `snapshot_orders` | `false` | 每次更新订单都存快照 |
| `snapshot_positions` | `false` | 仓位变化时存快照 |
| `snapshot_positions_interval_secs` | 无 | 定时为持仓存快照 |
| `allow_overfills` | `false` | 是否接受超额成交 |
| `external_clients` | 无 | 外部执行客户端列表 |

快照只在缓存有数据库后端时才真正写入（第 16 章）。另外还有一组 `purge_*` 选项，定时从内存里清理已关闭的订单、已平的仓位和账户事件，适合长期运行的实盘节点。

::: warning 常见误区
- **以为 `OrderSubmitted` 是执行引擎产生的。** 它由执行客户端生成，经 `ExecEngine.process` 回到引擎。
- **以为路由只看品种的场所。** 显式 `client_id` 和订单账户 ID 都排在场所之前，最后才是默认客户端。
- **在 NETTING 策略里给订单指定自定义仓位 ID。** 提交时会被拒绝；需要多个仓位要用 HEDGING。
- **以为 `on_order_filled` 时仓位还没更新。** 仓位事件确实在订单事件之后发布，但两者被发布时缓存里的仓位都已经更新完。
- **以为重复推送的成交会让仓位翻倍。** 相同 `trade_id` 的成交会被识别为重复并跳过；换了 `trade_id` 的重复推送无法识别，只有累计数量超出时才会作为超额成交被拒绝。
- **以为 HEDGING 翻转会在原仓位上继续。** 原仓位被平掉，反向部分开在一个带 `F` 后缀的新仓位上。
:::

## 本章结论

执行引擎在命令方向上校验提交、转发外部客户端的命令，按“显式客户端、账户发行方、品种场所、默认客户端”的顺序选执行客户端，并在提交前检查场所匹配和 NETTING 下的仓位 ID。在事件方向上，它先找到订单，把事件应用到缓存里的订单；对成交，还要先决定 OMS 类型和仓位 ID、去重、检查超额，然后通知 Portfolio、开仓、更新或翻转仓位，最后依次发布成交主题、策略的订单主题和仓位主题。被拒绝的成交统一发到 `order_fill_declined`。

## 检查理解

1. 节点登记了 `BINANCE` 和 `BYBIT` 两个执行客户端，`BYBIT` 是默认客户端，场所路由只登记了 `BINANCE`。策略提交一张 `ETHUSDT.OKX` 的单，没有指定 `client_id`，会发给谁？

   <details><summary>参考答案</summary>

   选中的是 `BYBIT`。订单还没有账户 ID，第 2 步跳过；`OKX` 不在路由表里，第 3 步找不到；最后落到默认客户端。接下来 `handle_submit_order` 会检查 `BYBIT` 客户端是否处理 `OKX` 场所的订单，不处理就拒绝，原因是 `ClientVenueMismatch`。

   </details>

2. NETTING 下，策略持有多 1 ETH，又收到一笔卖出 1.5 ETH 的成交。仓位缓存和仓位事件会怎样变化？

   <details><summary>参考答案</summary>

   成交被拆成 1 ETH 和 0.5 ETH 两份。前一份把原仓位平掉，平掉的这段被存为仓位快照；后一份在同一个 ID `ETHUSDT.BINANCE-EMACross-001` 上开一个空 0.5 ETH 的新仓位。策略会先后收到平仓和开仓对应的仓位事件。HEDGING 下则会生成一个带 `F` 后缀的新 ID。

   </details>

3. 一个实盘适配器同时从 WebSocket 和定期查询两个渠道拿到同一笔成交，两次的 `trade_id` 相同。第二次到达时会发生什么？如果交易所第二次换了 `trade_id` 呢？

   <details><summary>参考答案</summary>

   `trade_id`、方向、价格、数量都相同时，第二次被识别为重复，跳过，并发布到 `events.order_fill_declined.{instrument_id}`。换了 `trade_id` 后，引擎认为这是另一笔成交：如果累计数量超过下单数量，默认 `allow_overfills = false` 会拒绝它，同样发到 `order_fill_declined`；如果没有超出（比如这张单本来只成交了一部分），引擎会把它当成新成交照常应用，这类问题要靠对账发现。

   </details>

## 参考资料

- 官方文档：[Execution](https://nautilustrader.io/docs/latest/concepts/execution/)
- 源码：[`crates/execution/src/engine/mod.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/execution/src/engine/mod.rs) · [`crates/execution/src/engine/config.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/execution/src/engine/config.rs) · [`crates/common/src/generators/position_id.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/common/src/generators/position_id.rs) · [`crates/common/src/msgbus/switchboard.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/common/src/msgbus/switchboard.rs)
- 配图由 `scripts/generate-nautilus-trader-figures.py` 生成。

不是所有订单都直接发往执行引擎：仿真单在本地等待触发，带止盈止损的订单组要在本地联动。下一章看订单仿真器和订单管理器怎样处理这些订单。[第 21 章：OrderEmulator 与 OrderManager](./order-emulator.md)。
