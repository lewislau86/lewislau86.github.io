---
title: "第 34 章：ExecutionManager：实盘执行管理与对账"
description: 为什么实盘需要对账；谁负责什么：LiveNode、ExecutionManager、ExecutionEngine；四种执行报告；启动对账的顺序：拉报告、去重、订单、成交、仓位，仓位对不上时生成 RECONCILIATION 订单，仍对不上则拒绝启动；外部订单的归属；运行期的三种检查：在途、未结订单、仓位；“结果未知”的命令怎样收尾，RetainUnresolved 与 ResolveLocally 的区别；常用配置。
---

# 第 34 章：ExecutionManager：实盘执行管理与对账

[全书目录](./index.md) · [上一章](./networking.md) · [下一章](./book-sync.md)

::: tip 本章学习目标
能说出本地状态和交易所状态会在哪些情况下不一致；能按顺序说出启动对账的五个步骤，以及仓位对不上时系统会做什么、什么情况下拒绝启动；知道外部订单的策略 ID 和标签怎样决定；能说出三种运行期检查各自的默认间隔和触发条件；能解释一张“提交后没有回音”的订单在两种恢复策略下各怎样收尾；知道“缺少仓位报告”为什么不等于“空仓”。

**源码版本：** `develop` 分支，提交 `364254f`（2026-11-18）。执行管理器在 `crates/live/src/execution/manager.rs`，对账的共享类型和决策在 `execution/reconciliation.rs`，节点侧的周期任务在 `crates/live/src/node/reconciliation.rs`，配置在 `crates/live/src/node/config.rs`（`LiveExecEngineConfig`），报告到事件的转换在 `crates/execution/src/reconciliation/`。

**对应官方文档：** [Execution Reconciliation](https://nautilustrader.io/docs/latest/concepts/execution/reconciliation/) · [Execution Policies](https://nautilustrader.io/docs/latest/concepts/execution/policies/)
:::

回测里，本地状态就是全部真相：模拟交易所和执行引擎在同一个进程里，不会丢消息。实盘不一样：节点可能在挂单期间崩溃重启，WebSocket 可能在一笔成交推送到一半时断开（第 33 章），下单请求可能超时而交易所其实已经收到，用户也可能在交易所的网页上手动下单。这些都会让本地缓存里的订单和仓位，和交易所的真实状态不一致。**对账**就是定期拿交易所的报告和本地状态比对、补齐差异的过程。

主线例子：一个交易 `ETH-USDT-SWAP.OKX` 的节点在 9:00 崩溃，9:30 重启。缓存（有数据库后端，第 36 章）里记着：订单 A 买入 1 ETH @ 3,000，状态 `ACCEPTED`；没有仓位。这半小时里，订单 A 成交了 0.6 ETH；用户还在网页上挂了一张卖单 B，0.5 ETH @ 3,100。

## 1. 谁负责什么 {#roles}

- **`LiveNode`**：拥有 `ExecutionManager`，在启动时调用启动对账，在维护计时器上安排周期检查（第 30 章第 4 节），管理请求报告的异步任务和截止时间。
- **`ExecutionManager`**：持有对账的状态（每张订单查过几次、最近的活动、已处理过的成交 ID），决定发现差异后该怎么办，生成对账事件。
- **`ExecutionEngine`**：把对账事件应用到订单和仓位上，和平常处理回报一样（第 20 章）。

## 2. 四种执行报告 {#reports}

执行客户端向交易所查询后，把结果翻译成四种报告（第 38 章说适配器要实现的三个 `generate_*_reports` 方法就是产生它们）：

| 报告 | 内容 | 本地找不到对应订单时 |
| --- | --- | --- |
| `OrderStatusReport` | 一张订单的当前状态和累计成交量 | 新建订单，并推断报告里的成交 |
| `FillReport` | 一笔成交 | 新建一张带 `FILL_REPORT` 标记的市价单，再应用成交 |
| `OrderWithFills` | 订单状态加它的成交 | 新建订单，应用成交，推断剩余 |
| `PositionStatusReport` | 交易所的仓位快照 | 只记日志；仓位始终由成交推出 |

启动时，三类报告合成一个 `ExecutionMassStatus`。它还可以声明历史的边界：`lookback_start` 表示更早的成交不在报告里，`reports_complete` 表示所有来源都完整取回并映射成功。

有一类交易所（比如 OKX）要求“权威成交”：不能从订单状态里的累计成交量推断成交，必须等交易所真正给出成交报告或成交推送。对这类客户端，缺失的成交和依赖它的状态变化会一直等待，而不是被推断出来。

## 3. 启动对账 {#startup}

第 30 章第 3 节说过，启动对账在执行客户端连接之后、Trader 启动之前进行。对每个执行客户端（`reconciliation = true` 时，默认开启）：

1. **拉报告。** 调用客户端生成订单、成交、仓位三类报告，回溯 `reconciliation_lookback_mins` 分钟（不设时用适配器的默认值），超时由 `timeout_reconciliation` 控制（默认 30 秒）。
2. **去重。** 同一批里重复的订单报告去掉并记警告；重复的成交 ID 记警告。
3. **订单对账。** 对每张订单生成把本地状态推进到报告状态所需的事件。本地没有的订单作为外部订单新建（第 4 节）。
4. **成交对账。** 对报告里有、本地没有的成交生成 `OrderFilled`；没有成交报告时，除非客户端要求权威成交，否则从累计成交量推断。事件按成交时间排序后应用。成交价、手续费和本地记录不一致时，保留本地记录并记警告。
5. **仓位对账。** 按账户和品种，把本地的净仓位和交易所的仓位报告比较，允许账户的数量容差。

**仓位对不上时。** `generate_missing_orders`（默认开启）时，系统生成标签为 `RECONCILIATION` 的合成市价单和成交，把本地仓位补到报告的数量：从空仓开仓用报告的开仓均价；加仓用一个计算出的价格，使加仓后的均价等于报告的均价；减仓用报告的均价；翻转则先平掉本地仓位，再按报告开新仓。合成订单的 ID 和成交 ID 由逻辑事件确定地算出，重启后重放会被去重。

**仍然对不上时，拒绝启动。** 补齐之后，如果在容差内仍然不一致，启动失败，Actor 和策略都不会启动。官方文档把这一点放在最显眼的位置：**明确的仓位报告是权威的**，系统要么对齐它，要么拒绝运行。

**缺少报告不等于空仓。** 交易所没返回某个品种的仓位报告、报告里数量为空、交易所根本不提供仓位接口，都不能当作“空仓”的证据。对这些品种，有限回溯窗口里的历史成交只更新订单状态，不改变仓位（只有满足条件的平仓成交可以减少已有的仓位）。

主线例子里：订单 A 有一份 `PARTIALLY_FILLED`、累计 0.6 的状态报告和一份 0.6 的成交报告，系统生成 `OrderFilled(0.6)`，A 变为部分成交，本地开出一个 0.6 的多头仓位；卖单 B 本地没有，作为外部订单新建，状态 `ACCEPTED`；OKX 的仓位报告是多 0.6，和本地一致，对账完成，策略开始运行。如果交易所报告的是多 1.0（比如有一笔成交早于回溯窗口），系统生成一张 `RECONCILIATION` 买单 0.4 补齐差额；如果配置关掉了 `generate_missing_orders`，节点拒绝启动。

## 4. 外部订单归谁 {#external}

外部订单的策略 ID 和标签取决于来源，以及有没有策略“认领”这个品种：

| 来源 | 没有策略认领 | 有策略认领 |
| --- | --- | --- |
| 交易所上的订单 | `EXTERNAL`，标签 `VENUE` | 认领的策略，无标签 |
| 仓位对账生成的订单 | `EXTERNAL`，标签 `RECONCILIATION` | 认领的策略，标签 `RECONCILIATION` |

策略在配置里写 `external_order_instrument_ids`，就是声明要认领这些品种上的外部订单和对账活动（第 20 章的“外部订单认领”）。这样一个策略重启后，即使缓存是空的，也能接管交易所上已有的挂单和仓位。主线例子里，如果策略认领了 `ETH-USDT-SWAP.OKX`，卖单 B 就归这个策略，策略能在 `on_start` 之后看到并管理它；否则它属于 `EXTERNAL`，仍然计入仓位和组合，但没有策略会主动撤它。

NETTING 账户上，交易所报告的是账户级的净仓位。同一账户、同一品种上有多个策略各自持仓时，对账会记警告；官方建议每个账户和品种只由一个策略认领。

## 5. 运行期的三种检查 {#runtime}

启动对账完成后，再等 `reconciliation_startup_delay_secs`（默认 10 秒），周期检查开始：

| 检查 | 默认 | 做什么 |
| --- | --- | --- |
| 在途检查 | 每 2 秒，开启 | 找出提交、待改、待撤超过 5 秒没有回音的订单，逐个查询 |
| 未结订单检查 | 关闭（`open_check_interval_secs`） | 拉取交易所的未结订单，和本地比对 |
| 仓位检查 | 关闭（`position_check_interval_secs`） | 拉取仓位报告，和本地比对 |

这三种检查都由第 30 章的维护计时器调度，查询交易所的请求在后台进行，不阻塞事件循环。

**未结订单检查** 发现差异时的处理：本地 `ACCEPTED`、交易所说已撤销、已过期或已拒绝，就照办；本地有、交易所的“未结订单”列表里没有，默认的“只看未结订单”模式（`open_check_open_only = true`）不会据此认定订单不存在，因为未结订单接口通常不包含刚成交或刚撤销的订单；连续 5 次（`open_check_missing_retries`）缺失后，单独查询这张订单的状态，查到就照常对账，查不到也不作结论。最近 5 秒内有活动的订单跳过检查，避免和正在途中的回报冲突。已成交的订单查不到时直接忽略。

**仓位检查** 和启动时的仓位对账规则相同：先补应用交易所的权威成交，仍有差异再生成合成事件。交易所的仓位查询失败时，这一轮跳过该交易所的仓位，而不是把“没有报告”当成空仓。

单张订单的查询每轮最多 10 次（`max_single_order_queries_per_cycle`），两次之间间隔 100 毫秒（`single_order_query_delay_ms`），避免对账本身触发交易所的限流。

## 6. 结果未知的命令 {#unknown}

最棘手的情况是：策略提交了一张单，请求发出去了，但交易所既没确认也没拒绝。可能是请求没到，也可能到了而回报丢了。直接当作“失败”重新下单，可能重复下单；直接当作“成功”，可能以为有一张不存在的挂单。

在途检查对这类订单的处理：每 2 秒检查一次，订单处于在途状态超过 5 秒（`inflight_check_threshold_ms`）就向交易所查询；最多检查 5 次（`inflight_check_retries`）。耗尽之后，取决于 `submission_recovery_policy`：

- **`RetainUnresolved`（默认）**：从未被确认过的提交保持未解决，停止自动的单张查询，等待后续的交易所证据（推送、未结订单检查等）来决定它的结局。节点发布一个 `SubmissionRecoveryExhausted` 诊断事件到 `reconciliation.SubmissionRecoveryExhausted`，这不是订单事件，不代表任何结果。对已确认的订单上的待撤、待改命令，拒绝这个命令、把订单恢复到命令前的状态，订单保持未结。
- **`ResolveLocally`**：按本地规则了结。`SUBMITTED` 的订单以 `INFLIGHT_TIMEOUT` 为原因被拒绝；`PENDING_CANCEL`、`PENDING_UPDATE` 的订单以同样的原因被视为已撤销。

默认策略更保守：宁可让一张单停在未知状态，也不在没有证据的情况下给它一个结局。代价是节点停止时，如果还有未解决的提交，`stop` 会返回错误并列出这些订单 ID（第 30 章第 5 节）。

![对账的两个阶段：启动时拉取订单、成交、仓位三类报告，去重后依次对账订单、成交和仓位，仓位不一致时生成 RECONCILIATION 订单，仍不一致则拒绝启动；运行期由维护计时器调度在途检查、未结订单检查和仓位检查，在途检查耗尽后按 RetainUnresolved 或 ResolveLocally 收尾](/nautilus-trader/figures/reconciliation-flow.svg)

怎么读这张图：上面一行是启动对账，最右边的菱形是“能否启动”的分界。下面是运行期的三条检查线，最下面一行对比了两种恢复策略对同一张在途订单的处理。

::: warning 常见误区
- **以为交易所没返回仓位就是空仓。** 缺少报告不是空仓的证据。
- **关掉 `generate_missing_orders` 以为能“跳过”仓位差异。** 差异仍会导致启动失败。
- **以为默认会周期性检查未结订单和仓位。** 默认只开了在途检查，另外两种要自己配置间隔。
- **以为“未结订单列表里没有”就说明订单不存在。** 默认模式不据此下结论，只在单独查询确认后才处理。
- **以为在途超时的订单默认会被标记为拒绝。** 默认的 `RetainUnresolved` 保持未解决，只发布诊断事件。
- **没设回溯窗口，又没有持久化缓存。** 早于窗口的成交找不回来，只能靠仓位报告补齐，补齐用的是合成价格，历史盈亏无法重建。
:::

## 本章结论

对账用交易所的订单、成交、仓位报告修正本地状态。启动时，节点在连接执行客户端之后、启动 Trader 之前，对每个客户端拉取报告、去重，再依次对账订单、成交和仓位；仓位不一致时生成标签为 `RECONCILIATION` 的合成订单补齐，补齐后仍不一致则拒绝启动。明确的仓位报告是权威的，缺少报告不等于空仓。外部订单归认领该品种的策略，否则归 `EXTERNAL`。运行期默认每 2 秒检查一次在途订单，未结订单和仓位检查需要配置间隔；在途订单查询耗尽后，默认保持未解决并发布诊断事件，也可以选择按本地规则了结。

## 检查理解

1. 一个节点没有数据库后端，重启后缓存是空的。交易所上有一个多 2 ETH 的仓位和一张挂着的止盈卖单。策略没有设置 `external_order_instrument_ids`。启动后会是什么状态？

   <details><summary>参考答案</summary>

   止盈卖单作为外部订单新建，策略 ID 为 `EXTERNAL`、标签 `VENUE`。仓位方面，回溯窗口内能找到的成交会被应用；如果它们不足以解释 2 ETH，系统生成 `RECONCILIATION` 订单补齐，归 `EXTERNAL`。启动成功，但策略看不到这两样东西归自己，不会管理那张止盈单。要让策略接管，应该在配置里认领这个品种。

   </details>

2. 默认配置下，策略在 10:00:00 提交了一张单，交易所一直没有任何回音。之后会发生什么？如果把策略改成 `ResolveLocally` 呢？

   <details><summary>参考答案</summary>

   在途检查每 2 秒运行一次，订单在途超过 5 秒后开始向交易所单独查询，共检查 5 次。默认的 `RetainUnresolved` 下，耗尽后订单保持 `SUBMITTED`，停止自动查询，节点发布 `SubmissionRecoveryExhausted` 诊断事件；之后如果交易所推送了这张单的状态，或者未结订单检查找到了它，就按报告处理。停止节点时，它会作为未解决的提交出现在 `stop` 的错误里。改成 `ResolveLocally` 后，耗尽时订单以 `INFLIGHT_TIMEOUT` 被拒绝。

   </details>

3. 为什么默认的“只看未结订单”模式下，“本地有、交易所未结列表里没有”不会直接把订单判为不存在？

   <details><summary>参考答案</summary>

   交易所的未结订单接口通常不包含刚成交、刚撤销的订单，所以“不在列表里”既可能是“不存在”，也可能是“刚刚结束”。直接判为不存在可能把一张实际已成交的订单标记为拒绝，丢掉成交。所以系统先等连续若干次缺失，再单独查询这张订单；查到了按报告对账，查不到也不作结论，留给后续证据。

   </details>

## 参考资料

- 官方文档：[Execution Reconciliation](https://nautilustrader.io/docs/latest/concepts/execution/reconciliation/) · [Execution Policies](https://nautilustrader.io/docs/latest/concepts/execution/policies/)
- 源码：[`crates/live/src/execution/manager.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/live/src/execution/manager.rs) · [`crates/live/src/execution/reconciliation.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/live/src/execution/reconciliation.rs) · [`crates/live/src/node/reconciliation.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/live/src/node/reconciliation.rs) · [`crates/live/src/node/config.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/live/src/node/config.rs)
- 配图由 `scripts/generate-nautilus-trader-figures.py` 生成。

订单和仓位之外，行情也会出现断档：订单簿的增量流丢了一条，本地的订单簿就和交易所不一样了。下一章看订单簿怎样发现断档、怎样恢复。[第 35 章：订单簿同步与恢复](./book-sync.md)。
