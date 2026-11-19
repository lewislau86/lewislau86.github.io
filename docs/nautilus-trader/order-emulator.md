---
title: "第 21 章：OrderEmulator 与 OrderManager：本地仿真与订单联动"
description: 仿真单怎样被持有、按什么行情条件触发、释放时变成什么订单；改单、撤单和追踪止损在本地怎样处理；OrderManager 怎样处理 OTO、OCO、OUO 三种联动；仿真器和策略各有一个订单管理器，各管哪些订单。
---

# 第 21 章：OrderEmulator 与 OrderManager：本地仿真与订单联动

[全书目录](./index.md) · [上一章](./execution-engine.md) · [下一章](./portfolio.md)

::: tip 本章学习目标
能说出一张仿真单从提交到释放经过的步骤，以及每种订单类型在什么行情条件下触发、释放成什么类型；知道仿真单在持有期间不经过风控、不占用资金；能解释一张带仿真止盈止损的括号单在入场成交、止损触发、止损成交时各发生什么；能区分仿真器里的订单管理器和策略里的订单管理器各管哪些订单。

**源码版本：** `develop` 分支，提交 `364254f`（2026-11-18）。仿真器在 `crates/execution/src/order_emulator/emulator.rs`，订单管理器在 `crates/execution/src/order_manager/manager.rs`，本地撮合核心在 `crates/execution/src/matching.rs`，追踪止损计算在 `crates/execution/src/trailing.rs`，括号单工厂在 `crates/common/src/factories/order.rs`。

**对应官方文档：** [Emulated orders](https://nautilustrader.io/docs/latest/concepts/orders/emulated/) · [Advanced orders](https://nautilustrader.io/docs/latest/concepts/orders/advanced/)（Contingency types、Bracket orders 两节）
:::

第 5 章介绍过仿真单：给订单设置 `emulation_trigger`，系统就在本地盯着行情，条件满足时才把订单发出去，用来在不支持某种订单类型的场所上使用这种订单。第 19 章说过持有中的仿真单不经过风控。这一章看仿真器内部怎么做，以及和它配合的订单管理器怎样处理订单之间的联动。

主线例子：策略 `EMACross-001` 用订单工厂创建一张括号单：入场 `BUY 1 ETHUSDT.BINANCE MARKET`，止损 `STOP_MARKET` 触发价 400.00，止盈 `LIMIT` 450.00，`emulation_trigger = BID_ASK`。入场单是市价单，不能仿真；止损和止盈都由本地仿真。

## 1. 两个组件、两个订单管理器 {#roles}

**OrderEmulator** 是内核里的一个组件，注册端点 `OrderEmulator.execute`。它为每个触发品种维护一个本地撮合核心（`OrderMatchingCore`），把持有的仿真单挂在里面，收到报价或成交时检查哪些单该触发。

**OrderManager** 不是独立组件，而是一个处理订单联动的工具：订单事件进来，它返回一组“该做什么”的动作（`OrderManagerAction`），由持有它的组件去执行。动作只有六种：发布 `OrderInitialized`、提交给仿真器、提交给风控、提交给执行算法、本地撤单、本地改数量。

系统里有两处持有 OrderManager：

| 持有者 | `active_local` | 管哪些订单 | 何时生效 |
| --- | --- | --- | --- |
| OrderEmulator | `true` | 仍在本地的订单 | 总是 |
| 每个策略 | `false` | 已经离开本地的订单 | `manage_contingent_orders = true` |

“仍在本地”指订单状态是 `INITIALIZED`、`EMULATED` 或 `RELEASED`（`is_active_local`），也就是还没有交给执行客户端。两个管理器按这个状态划分，同一张单不会被两边同时管理。

命令怎样到达仿真器，由策略决定（第 9 章）：`submit_order` 遇到设置了 `emulation_trigger` 的单，发到 `OrderEmulator.execute`；`submit_order_list` 只要列表里有一张仿真单，整个列表都发给仿真器。

## 2. 持有一张仿真单 {#hold}

仿真器的 `handle_submit_order` 依次做下面几件事：

1. 把原始的 `SubmitOrder` 命令存起来，释放时还要用。
2. 检查触发类型。只接受 `DEFAULT`、`BID_ASK`、`LAST_PRICE` 三种，前两种看报价，后一种看成交价。其他值（比如 `MARK_PRICE`）记一条错误，订单在本地被撤销。
3. 取触发品种的撮合核心，没有就新建。触发品种默认是订单自己的品种，也可以用 `trigger_instrument_id` 指定另一个品种（包括合成品种，第 18 章）。新建时用缓存里最新的报价或成交价给核心赋初值。
4. 追踪止损先算一次触发价（第 5 节）。
5. 订阅该策略的订单事件主题 `events.order.{strategy_id}`，后面的联动要靠它。
6. **立即检查一次。** 用核心里已有的价格判断这张单是否已经满足条件，满足就直接释放。这种情况不会产生 `OrderEmulated` 事件。
7. 按触发类型订阅报价或成交（同一品种只订阅一次）。
8. 把订单挂进撮合核心，生成 `OrderEmulated`：写入缓存，发给风控引擎（`RiskEngine.process`），并发布到策略的订单主题，策略的 `on_order_emulated` 被调用。

持有期间订单的状态是 `EMULATED`。风控没有看过它，它也不占用账户资金；风控检查要等到释放之后（第 4 节）。

## 3. 触发规则 {#matching}

每收到一条报价，仿真器更新核心里的买一价和卖一价；每收到一笔成交，更新最新成交价。然后逐个检查挂着的订单：先检查买单，再检查卖单。用报价时，买单看卖一价（ask），卖单看买一价（bid）：

| 订单类型 | 买单触发条件 | 卖单触发条件 | 释放为 |
| --- | --- | --- | --- |
| `LIMIT` | ask ≤ 限价 | bid ≥ 限价 | `MARKET` |
| `STOP_MARKET` | ask ≥ 触发价 | bid ≤ 触发价 | `MARKET` |
| `STOP_LIMIT` | ask ≥ 触发价 | bid ≤ 触发价 | `LIMIT` |
| `MARKET_IF_TOUCHED` | ask ≤ 触发价 | bid ≥ 触发价 | `MARKET` |
| `LIMIT_IF_TOUCHED` | ask ≤ 触发价 | bid ≥ 触发价 | `LIMIT` |
| `TRAILING_STOP_MARKET` | 同 `STOP_MARKET` | 同 `STOP_MARKET` | `MARKET` |
| `TRAILING_STOP_LIMIT` | 同 `STOP_LIMIT` | 同 `STOP_LIMIT` | `LIMIT` |

`LAST_PRICE` 触发时，表里的 ask 和 bid 都换成最新成交价。`MARKET` 和 `MARKET_TO_LIMIT` 不能仿真。

主线例子里，止损是卖出 `STOP_MARKET`，触发条件是 bid ≤ 400.00；止盈是卖出 `LIMIT`，触发条件是 bid ≥ 450.00。

## 4. 释放 {#release}

条件满足后，`release_order` 做这几步：

1. **确定释放价。** 买单取 ask，卖单取 bid，`LAST_PRICE` 取最新成交价。还没有价格就记一条警告，等下一条行情再试。
2. **变换订单。** 释放为 `MARKET` 时，有效期 `GTD` 改为 `GTC`（市价单不支持 GTD），其余字段沿用；释放为 `LIMIT` 时，用原单的限价构造限价单，追踪止损限价单还没有限价时，等下一条行情再试。新订单的 `emulation_trigger` 为空，所以别的组件不再把它当仿真单。`client_order_id` 不变，原单的事件历史被接到新订单前面。
3. **取出存好的 `SubmitOrder`，从撮合核心删除订单。**
4. **替换缓存里的订单**，并把新订单的 `OrderInitialized` 发布到策略的订单主题。命令里的 `order_init` 也换成新订单的。
5. **生成 `OrderReleased`**（带释放价），写入缓存，发给风控引擎，并发布到策略的订单主题。
6. **发送命令：** 订单带执行算法 ID 就发给执行算法，否则发给 `RiskEngine.execute`。

从这里开始，订单走正常路径：风控检查、执行引擎路由、执行客户端下单。如果风控拒绝（比如交易状态是 `HALTED`），订单变成 `DENIED`，不会重试；第 6 节会看到，这还会触发联动，撤掉它的兄弟单。

::: warning 仿真限价单释放为市价单
表里第一行容易被忽略：仿真的 `LIMIT` 单在行情到达限价时，释放出去的是 `MARKET` 单。这意味着限价保护和 `post_only` 都没有了，成交价可能比限价差，也拿不到挂单手续费。括号单的止盈默认是 `post_only` 的 `LIMIT`，一旦设置了仿真，止盈实际是“到价后市价平仓”。
:::

## 5. 改单、撤单与追踪止损 {#modify}

**改单。** 持有中的仿真单可以改数量、价格和触发价。仿真器在本地生成 `OrderUpdated`，写入缓存，发给 Portfolio，发布到策略的订单主题；然后用新价格立即检查一次，满足就直接释放。改单同样不经过风控。

**撤单。** 订单还在撮合核心里，就在本地撤销：从核心删除，生成 `OrderCanceled`，写入缓存、发给 Portfolio、发布到策略的订单主题。如果订单已经释放、不再是仿真单，撤单命令被转发给执行引擎。撤全部订单时，执行引擎会给仿真器单独发一条 `CancelAllOrders`（第 20 章第 3 节）。

**追踪止损。** 每轮检查完触发条件后，仿真器为每张追踪止损单重算触发价（`trailing_stop_calculate`）。以卖出追踪止损、偏移 5.00 为例：基准是 bid，候选触发价是 `bid - 5.00`，只有候选价比当前触发价更高时才移动；买单方向相反。追踪止损限价单的限价按 `limit_offset` 同样移动。设置了激活价的单，在价格触及激活价之前不移动、不触发。

触发价移动时，仿真器生成 `OrderUpdated` 写入缓存，但这条事件只发给风控引擎，不发布到策略的订单主题，所以策略的 `on_order_updated` 收不到追踪止损的移动。要看当前触发价，从缓存里查订单。

## 6. OrderManager：订单联动 {#contingency}

括号单由三张单组成：入场单的联动类型是 OTO（一单成交触发其他单），两张退出单是它的子单，彼此之间是 OUO（一单成交，更新另一单的数量）。另一种常见类型是 OCO（一单成交，撤掉其他单）。OrderManager 收到订单事件后按联动类型处理：

| 事件 | OTO 父单 | OCO | OUO |
| --- | --- | --- | --- |
| 成交 | 子单数量跟随父单累计成交量；仍在本地的子单提交一次 | 撤掉兄弟单 | 兄弟单数量改为本单剩余量，剩余为零则撤掉 |
| 拒绝、撤销、过期 | 父单零成交就关闭时，撤掉子单 | 撤掉兄弟单 | 撤掉兄弟单 |
| 释放后被风控拒绝 | 同上 | 同上 | 同上 |

OTO 子单的数量有两个修正：子单是只减仓单时，数量不超过当前仓位；数量向下取整到子单品种的数量步长。

两个管理器的分工在这张表上体现为：OTO 子单的“提交”只有仿真器的管理器会做（它只管仍在本地的订单）；策略的管理器只对已经发到场所的订单发撤单和改单命令，不会提交一张非本地的 OTO 子单。官方文档 Advanced orders 一节也明确说，`manage_contingent_orders` 不会给场所增加原生联动能力。

主线例子按时间顺序走一遍：

| 时刻 | 入场单 | 止损 | 止盈 |
| --- | --- | --- | --- |
| 提交括号单 | 发往风控 | 等父单 | 等父单 |
| 入场成交 1 @ 423.50 | `FILLED` | `EMULATED` | `EMULATED` |
| bid 跌到 399.90 | | 释放为 `MARKET` | `EMULATED` |
| 止损成交 | | `FILLED` | 本地撤销 |

1. 整个列表发给仿真器。仿真器跳过两张子单（父单是 OTO），入场单不是仿真单，由管理器生成 `SubmitOrder` 交给风控。
2. 入场单成交，事件发布到 `events.order.EMACross-001`，仿真器订阅了这个主题。管理器算出两张子单的数量都是 1，它们仍在本地，于是各生成一条提交命令，因为它们是仿真单，命令交回仿真器自己，两张单进入 `EMULATED`。
3. bid 跌到 399.90，满足止损的触发条件。止损释放为卖出 1 的市价单，释放价 399.90，经风控和执行引擎发到 Binance。
4. 止损成交。管理器看到止损是 OUO，它已经没有剩余数量，于是对止盈生成本地撤单；止盈还在本地，仿真器直接生成 `OrderCanceled`。

如果第 2 步之后行情先涨到 bid ≥ 450.00，就是止盈先释放为市价单，成交后止损被本地撤销。

![一张带仿真止盈止损的括号单：四个时刻里入场单、止损、止盈三张单的状态。提交时入场单发往风控、两张退出单等父单；入场成交后两张退出单进入本地仿真；买一价跌破止损触发价后止损释放为市价单；止损成交后止盈被本地撤销](/nautilus-trader/figures/order-emulator-bracket.svg)

怎么读这张图：每一列是一个时刻，每一行是一张订单。橙色格子表示订单在本地（仿真器持有或等待父单），蓝色表示已经交给风控和执行引擎，灰色表示已经关闭。止盈从头到尾没有离开本地，所以撤销它不需要和交易所通信。

## 7. 重启后 {#restart}

缓存配置了数据库时，仿真单和其他订单一样会被持久化。仿真器启动时（`on_start`）找出缓存里所有仍是仿真状态的订单，重新挂进撮合核心、重新订阅行情，所以节点重启不会丢掉本地的止损单。前提是缓存真的从数据库加载了这些订单；没有数据库后端时，重启后这些止损单就不存在了，而场所那边也从来没有过它们。

::: warning 常见误区
- **以为仿真单在提交时就过了风控。** 持有期间不经过风控、不占用资金；释放时才检查，被拒绝就是 `DENIED`，不会重试。
- **以为仿真限价单会以限价单发出。** 它释放为市价单，限价保护和 `post_only` 都没有了。
- **持有一个订单对象的引用。** 释放时缓存里的订单被换成一个新类型的订单；要用 `client_order_id` 从缓存查。
- **在 `on_order_updated` 里跟踪追踪止损。** 仿真器移动触发价时不发布 `OrderUpdated` 到策略主题。
- **以为打开 `manage_contingent_orders` 就能在不支持括号单的场所上用括号单。** 它只撤或改已经在场所上的订单，不会在父单成交后提交场所上的子单；要本地提交子单，就让子单成为仿真单。
- **以为重启后仿真止损一定还在。** 只有缓存有数据库后端时才会恢复。
:::

## 本章结论

仿真器为每个触发品种维护一个本地撮合核心，持有设置了 `emulation_trigger` 的订单，按报价或成交价检查触发条件；满足时把订单变换为市价单或限价单，生成 `OrderReleased`，交给执行算法或风控，从此走正常路径。持有期间的改单和撤单在本地完成，追踪止损的触发价在本地移动。OrderManager 负责 OTO、OCO、OUO 联动：仿真器里的那个管理仍在本地的订单，可以提交子单、本地撤单和改数量；策略里的那个在 `manage_contingent_orders` 打开时管理已到场所的订单，只发撤单和改单命令。

## 检查理解

1. 一张仿真的 `BUY STOP_MARKET`，触发价 430.00，`emulation_trigger = BID_ASK`。提交时缓存里的最新报价是 bid 430.10 / ask 430.20。会发生什么？

   <details><summary>参考答案</summary>

   提交时仿真器用缓存里的报价给撮合核心赋初值，立即检查一次：买入止损看 ask，430.20 ≥ 430.00，满足条件，立即释放为市价单，释放价 430.20，发给风控。这种情况不会产生 `OrderEmulated`，策略看到的是 `OrderInitialized`（原单）、`OrderInitialized`（变换后的市价单）、`OrderReleased`，然后是正常的提交事件。

   </details>

2. 交易状态是 `HALTED`，主线例子里的止损被触发了，会怎样？止盈会怎样？

   <details><summary>参考答案</summary>

   止损释放后发到风控，`HALTED` 拒绝所有提交，止损变为 `DENIED`。仿真器的管理器看到这张单是从 `RELEASED` 变成 `DENIED` 的，并且带有联动类型，于是执行联动：止盈作为 OUO 兄弟单被本地撤销。结果是仓位还在，止损和止盈都没有了。所以只想禁止开仓时应该用 `REDUCING`（第 19 章）。

   </details>

3. 场所不支持括号单，策略没有设置 `emulation_trigger`，但打开了 `manage_contingent_orders`。入场单成交后，止损和止盈会被发到场所吗？

   <details><summary>参考答案</summary>

   取决于列表交给谁处理。列表里没有仿真单，所以整张列表发给风控和执行引擎，由执行客户端决定：有的适配器把三张单都发出去，有的使用场所的原生指令，有的拒绝整张列表。策略的管理器只管理已到场所的订单，不会在父单成交后替你提交子单。要让系统在本地等父单成交再提交子单，就给退出单设置 `emulation_trigger`，让它们由仿真器管理。

   </details>

## 参考资料

- 官方文档：[Emulated orders](https://nautilustrader.io/docs/latest/concepts/orders/emulated/) · [Advanced orders](https://nautilustrader.io/docs/latest/concepts/orders/advanced/)
- 源码：[`crates/execution/src/order_emulator/emulator.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/execution/src/order_emulator/emulator.rs) · [`crates/execution/src/order_manager/manager.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/execution/src/order_manager/manager.rs) · [`crates/execution/src/matching.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/execution/src/matching.rs) · [`crates/execution/src/trailing.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/execution/src/trailing.rs)
- 配图由 `scripts/generate-nautilus-trader-figures.py` 生成。

订单和仓位的变化最终都要反映到账户和盈亏上。下一章看 Portfolio 怎样根据订单事件、仓位事件和行情计算余额、保证金、敞口和未实现盈亏。[第 22 章：Portfolio](./portfolio.md)。
