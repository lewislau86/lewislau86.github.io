---
title: "第 19 章：RiskEngine：下单前检查与限流"
description: RiskEngine 在提交和改单路径上做哪些检查、按什么顺序；价格、数量、到期时间、只减仓、名义金额、余额和保证金检查各自看什么；为什么要“预留”尚未被账户反映的资金；交易状态 ACTIVE、REDUCING、HALTED；提交与改单的限流；被拒时产生什么事件。
---

# 第 19 章：RiskEngine：下单前检查与限流

[全书目录](./index.md) · [上一章](./data-engine.md) · [下一章](./execution-engine.md)

::: tip 本章学习目标
能按顺序列出一张订单在风控里经过的检查，知道每一项失败时的拒绝原因；能解释“预留”为什么能拦住连续几张单合起来超额的情况；知道三种交易状态各允许什么、被保护止损在 `REDUCING` 下怎样才能通过；知道限流超出时订单会被拒绝而不是排队；知道哪些命令根本不经过风控。

**源码版本：** `develop` 分支，提交 `364254f`（2026-11-18）。风控引擎在 `crates/risk/src/engine/mod.rs`，配置在 `engine/config.rs`，头寸规模计算在 `crates/risk/src/sizing.rs`，限流器在 `crates/common/src/throttler.rs`。

**对应官方文档：** [Execution](https://nautilustrader.io/docs/latest/concepts/execution/)（Risk engine、Order denied reasons 两节）
:::

第 3 章说过，风控不检查价格是否对齐最小变动价位；第 5 章说过，本地仿真单在释放前不经过风控；第 15 章说过，策略下单先发到 `RiskEngine.queue_execute`。这一章把这些零散的说法合在一起，看风控引擎到底检查什么、按什么顺序、通过之后把命令交给谁。

主线例子：一个 ETHUSDT 现金账户（余额 1,000 USDT）上，策略在同一秒里连续提交四张买单：`1 @ 423.50`、`1 @ 423.505`、`2 @ 423.50`，以及第 101 张单。

## 1. 风控在执行路径上的位置 {#position}

官方文档 Execution 一页给出了命令的流向：

```text
Strategy → OrderEmulator 或 ExecutionAlgorithm 或 RiskEngine
OrderEmulator → ExecutionAlgorithm 或 RiskEngine
ExecutionAlgorithm → RiskEngine → ExecutionEngine → ExecutionClient
```

风控只在“提交”和“改单”两条路径上，撤单和查询直接发给执行引擎，不经过它。它还订阅订单事件（比如仿真器发出的 `OrderReleased`），用来维护自己的状态。风控引擎在内核构造时注册两个端点：`RiskEngine.execute`（直接执行）和 `RiskEngine.queue_execute`（排队执行，第 15 章第 5.1 节）。

配置 `bypass = true` 时，提交命令直接转发给执行引擎，跳过所有检查和交易状态。官方文档特别提醒：这时交易状态也不再生效，只减仓的约束只能靠执行客户端自己遵守。

## 2. 一张单经过的检查 {#checks}

`handle_submit_order`（`engine/mod.rs`）的顺序是：

```rust
// 节选自 crates/risk/src/engine/mod.rs（handle_submit_order，有删节）
fn handle_submit_order(&mut self, command: SubmitOrder) {
    if self.config.bypass { Self::send_to_execution(…); return; }
    let order = /* 从缓存取出订单 */;
    // ① 只减仓：指定了仓位时，这张单不能让仓位变大；仓位不存在也拒绝
    // ② 品种必须在缓存里
    let full_position_exit = self.is_full_position_exit(&command, &instrument, &order);
    if !self.check_order(&instrument, &order, full_position_exit) { return; }   // ③ 单张订单的检查
    let Some(reservations) = self.check_orders_risk(…) else { return; };        // ④ 账户层面的检查
    self.execution_gateway(TradingCommand::SubmitOrder(command), reservations);  // ⑤ 交易状态与限流
}
```

<strong>③ 单张订单。</strong>`check_order` 依次检查：价格和触发价的精度不超过品种精度、价格为正（期货、期权、价差和现货商品允许负价）；数量精度不超过品种精度、数量在 `min_quantity` 和 `max_quantity` 之间；`GTD` 订单必须有到期时间且尚未过期。第 3 章说过的那个缝隙在这里：它不检查价格是否是最小变动价位的整数倍，也不检查每手股数。

<strong>④ 账户层面。</strong>`check_orders_risk` 先为命令选定一个账户（下一节），再检查名义金额：配置里的单笔上限 `max_notional_per_order`（按品种设置，以报价币计），以及品种自己的 `min_notional`、`max_notional`。然后看账户类型：现金账户检查这张单对余额的影响够不够付，保证金账户检查初始保证金（`check_margin`）。能减少已有仓位的订单不需要新的保证金或资金，会跳过这两项。

<strong>⑤ 交易状态与限流。</strong>`execution_gateway` 按当前的交易状态决定放行还是拒绝，放行的命令交给提交限流器，限流器再发给执行引擎的 `ExecEngine.queue_execute` 端点（第 4、5 节）。

任何一步失败，风控都会生成一个 `OrderDenied` 事件，带一个标准化的原因（官方文档 Order denied reasons 一节有完整列表），经执行引擎发布，策略在 `on_order_denied` 里收到；订单进入终态 `DENIED`。改单失败则生成 `OrderModifyDenied`，订单状态不变（第 5 章）。

回到主线例子的前两张单：`1 @ 423.50` 通过所有检查；`1 @ 423.505` 的价格精度是 3，超过 ETHUSDT 的 2，在第 ③ 步被拒，原因是价格精度超过最大值。如果策略用 `make_price` 处理过这个价格，它会被舍成 423.50（第 3 章第 3 节），就不会被拒。

![一张订单在风控里的路径：只减仓与品种检查、单张订单检查、选定账户后的名义金额与余额或保证金检查、交易状态与限流，任一步失败都生成 OrderDenied](/nautilus-trader/figures/risk-engine-pipeline.svg)

怎么读这张图：从左到右是检查的顺序，每一站下面写着它看什么。最右边的限流器之后才是执行引擎；任何一站往下的红色箭头都通向 `OrderDenied`。

## 3. 选哪个账户，以及“预留” {#reservations}

余额和保证金要对某一个账户检查，但订单在这时还没有账户（`OrderSubmitted` 才会带来账户 ID，第 16 章）。官方文档描述的选择顺序是：订单已有账户就用它（改单时）；命令指定的是外部客户端时，只在这个交易所恰好只有一个账户的情况下用它；命令指定的是已注册的执行客户端时用那个客户端的账户；否则用这个交易所路由到的客户端的账户，再退到默认客户端的账户。找不到账户，或者账户还没进缓存，订单以校验失败被拒，绝不会退而求其次用别的账户。

接着是主线例子的第三张单 `2 @ 423.50`。单看它，名义金额 847 USDT，账户余额 1,000 USDT，似乎够了。可第一张单刚刚通过，交易所还没确认，账户的冻结额还没反映它（第 7 章的冻结要等订单挂出后才重算）。如果风控只看账户上的可用余额，两张单合起来 1,270.50 USDT 就都能通过。

风控用“预留”解决这个问题。源码注释写的是：在账户反映这些订单之前，替已发出执行的订单占住它们的可用余额。第一张单通过时，风控记下一条预留（423.50 USDT）；检查第三张单时，可用余额先减去未被账户反映的预留，只剩 576.50 USDT，不够 847，于是第三张单因余额不足被拒。等订单的事件让账户真正反映了冻结，或者订单被拒、被撤，对应的预留就释放。官方文档还提到，通过的提交也会为之后的减仓检查预留数量，避免两张平仓单合起来超过仓位。

## 4. 交易状态 {#trading-state}

风控引擎有一个 `TradingState`，三个取值，越往后越严格：

| 状态 | 允许的命令 |
| :--- | :--- |
| `ACTIVE` | 提交、改单、撤单、查询都正常 |
| `REDUCING` | 只允许符合条件的单张只减仓提交，以及撤单和查询 |
| `HALTED` | 只允许撤单和查询，新提交和改单一律拒绝 |

`REDUCING` 下的单张提交要同时满足：订单设了 `reduce_only`；命令和订单是同一个品种；命令里给出的仓位 ID 对应选定账户上一个开着的仓位；方向与仓位相反；数量不超过仓位数量。订单组和改单一律拒绝。

这些规则对仿真单释放后的提交同样适用（第 5 章第 6 节）：在 `REDUCING` 下，一张保护性止损必须是只减仓的、并满足上述条件才能通过；在 `HALTED` 下，连保护性止损也会被拒，被拒的止损还可能通过条件单处理连带撤掉止盈单。所以把交易状态切到 `HALTED` 是一个很重的操作，它会让本地仿真的止损失效。

交易状态通过 `set_trading_state` 改变，变化时风控在 `events.risk` 主题上发布一个交易状态变化事件。

## 5. 限流 {#throttling}

`RiskEngineConfig` 有两个速率限制：`max_order_submit` 和 `max_order_modify`，默认都是每秒 100 条（改单时，批量改单里的每一张单分别计数）。风控为它们各建一个 `Throttler`（`crates/common/src/throttler.rs`）。

限流器本身可以“缓冲”或“丢弃”超额的消息，风控用的是后者，并且给了一个丢弃回调：

```rust
// 节选自 crates/risk/src/engine/mod.rs（create_submit_throttler）
let success_handler = Box::new(move |command: TradingCommand| {
    msgbus::send_trading_command(MessagingSwitchboard::exec_engine_queue_execute(), command);
});
let failure_handler = Box::new(move |command: TradingCommand| {
    let reason = OrderDeniedReason::RateLimitExceeded.to_string();
    // … 为这张单生成 OrderDenied，发给 ExecEngine.process
});
```

所以主线例子里第 101 张单不会被延后到下一秒发出，而是直接以 `RateLimitExceeded` 被拒。这对策略的写法有影响：高频重下单的策略要自己控制节奏，或者调高限额，不能指望风控替它排队。适配器还有自己面向交易所的限流（第 38 章翻译的开发指南里有一整节），两者是两层不同的保护。

## 6. 头寸规模 {#sizing}

`crates/risk/src/sizing.rs` 提供了一个按固定风险计算头寸规模的函数 `calculate_fixed_risk_position_size`：输入品种、入场价、止损价、账户权益、每笔交易愿意承担的风险比例、手续费率、报价币到权益币的汇率，以及可选的硬上限和分批参数，算出在风险预算之内向下取整的数量；反向合约按价格倒数计算盈亏。它只是一个工具函数，风控引擎在检查时不会调用它；策略需要时自己调用。

::: warning 常见误区
- **以为撤单也要过风控。** 撤单和查询直接发给执行引擎，只有提交和改单经过风控。
- **以为风控会对齐价格。** 它只检查精度和上下限，对齐要用 `next_bid_price` 等方法（第 3 章）。
- **以为超出速率的单会排队等待。** 风控的限流器丢弃超额消息，并为它生成 `OrderDenied`。
- **连续下几张单，以为每张只和账户余额比。** 已通过但尚未反映到账户的订单会占用预留，后面的单要和扣掉预留后的余额比。
- **以为切到 `HALTED` 能“暂停开仓、保留止损”。** `HALTED` 也会拒绝释放出来的仿真止损单；只想禁止开仓用 `REDUCING`。
- **打开 `bypass` 以为只是跳过检查。** 交易状态也不再生效。
:::

## 本章结论

风控引擎守在提交和改单两条路径上：先检查只减仓的约束和品种是否存在，再做单张订单的检查（精度、正负、数量上下限、GTD），然后选定账户，检查名义金额上下限以及现金账户的余额或保证金账户的初始保证金，并用预留把已通过、尚未反映到账户的订单计算在内；最后按交易状态放行或拒绝，放行的命令经限流器交给执行引擎，超出速率的直接拒绝。任何一步失败都生成带标准原因的 `OrderDenied` 或 `OrderModifyDenied`。

## 检查理解

1. 账户余额 1,000 USDT，策略在同一时刻提交 `BUY 1 @ 423.50` 和 `BUY 1 @ 423.50`，两张单都会通过吗？第三张 `BUY 1 @ 423.50` 呢？

   <details><summary>参考答案</summary>

   第一张通过并预留 423.50；第二张检查时可用余额是 `1000 - 423.50 = 576.50`，够付 423.50，通过并再预留 423.50；第三张检查时可用余额只剩 `1000 - 847 = 153`，不够，因余额不足被拒。前提是前两张单还没被账户反映；被反映后，冻结额替代了预留，结果相同。

   </details>

2. 交易状态是 `REDUCING`，策略持有多 2 ETH 的仓位 `P-1`，下了一张 `SELL 3 ETH`、`reduce_only=true`、指定 `P-1` 的单，会怎样？

   <details><summary>参考答案</summary>

   被拒。`REDUCING` 要求提交数量不超过仓位数量，3 大于 2。把数量改成 2 或更少才能通过。

   </details>

3. 一个做市策略每次报价更新都撤掉旧单、挂新单，高峰时每秒要提交 150 张单。在默认配置下会发生什么？应当怎样处理？

   <details><summary>参考答案</summary>

   默认 `max_order_submit` 是每秒 100 条，超出的约 50 张会被限流器丢弃，并各自生成 `RateLimitExceeded` 的 `OrderDenied`，不会延后发出。撤单不受这个限制，因为它们不经过风控。处理办法是降低报价频率、改用改单代替撤单重挂（改单另有 `max_order_modify` 限额），或在确认交易所允许的前提下调高 `max_order_submit`。

   </details>

## 参考资料

- 官方文档：[Execution · Risk engine](https://nautilustrader.io/docs/latest/concepts/execution/)
- 源码：[`crates/risk/src/engine/mod.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/risk/src/engine/mod.rs) · [`crates/risk/src/engine/config.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/risk/src/engine/config.rs) · [`crates/risk/src/sizing.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/risk/src/sizing.rs) · [`crates/common/src/throttler.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/common/src/throttler.rs)
- 配图由 `scripts/generate-nautilus-trader-figures.py` 生成。

通过风控的命令交给执行引擎。下一章看它怎样把命令路由给执行客户端，又怎样处理回来的订单事件和成交。[第 20 章：ExecutionEngine](./execution-engine.md)。
