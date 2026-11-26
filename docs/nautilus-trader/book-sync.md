---
title: "第 35 章：订单簿同步与恢复"
description: 增量订单簿为什么会失步；适配器怎样用交易所的序号发现断档；BookSync 的三个阶段和“没人负责的订单簿必须请求恢复”这条规则；恢复的四步：标记、请求、认领、运行；快照闸门为什么要等订阅确认后才打开；重试预算（8 次尝试，总时长不超过 180 秒）和之后从 1 分钟翻倍到 15 分钟的间隔；陈旧检测；订单簿流的输出契约和一致性检查。
---

# 第 35 章：订单簿同步与恢复

[全书目录](./index.md) · [上一章](./reconciliation.md) · [下一章](./external-backends.md)

::: tip 本章学习目标
能解释为什么一条丢失的增量会让本地订单簿“悄悄地错”；能用 OKX 的 `prevSeqId`、`seqId` 判断一批增量是否接得上；能说出 `BookSync` 的三个阶段，以及失步期间为什么一条行情也不输出；能按顺序说出恢复的四步和快照闸门的作用；能写出恢复失败时的重试节奏；知道适配器输出的订单簿增量要满足什么契约。

**源码版本：** `develop` 分支，提交 `364254f`（2026-11-18）。共享的同步与恢复机制在 `crates/live/src/book/`（`sync.rs`、`recovery.rs`、`snapshot.rs`、`mod.rs`，输出契约检查在 `conformance.rs`），OKX 的序号规则在 `crates/adapters/okx/src/book/sync.rs`，订单簿完整性检查在 `crates/model/src/orderbook/analysis.rs`。

**对应官方文档：** [Adapters 开发指南](https://nautilustrader.io/docs/latest/developer_guide/adapters/)（Order book recovery ownership 一节） · [Data](https://nautilustrader.io/docs/latest/concepts/data/)（Delta flags and event boundaries 一节）
:::

第 4 章讲过订单簿的数据：交易所先推一份快照，之后只推增量（某个价位的数量变成多少）。本地订单簿 = 快照 + 之后所有增量按顺序应用。这个方式很省带宽，但有一个致命的弱点：**只要丢了一条增量，本地订单簿就错了，而且之后每一条增量都会在错误的基础上继续应用**。它不会报错，只会悄悄地和交易所不一样。策略看到的买一卖一可能根本不存在。

所以实盘里订单簿需要两件事：发现断档，以及断档后用一份新快照恢复。这一章看 NautilusTrader 怎样把这件事做成一套各适配器共用的机制。

主线例子：OKX 的 `books` 频道。每批推送带两个序号：`seqId` 是这批的序号，`prevSeqId` 是上一批的序号；快照的 `prevSeqId` 是 -1。

## 1. 发现断档：序号 {#sequence}

怎样判断“接得上”是各交易所自己的规则，由适配器实现。OKX 的规则是：快照的 `prevSeqId` 必须是 -1；每一批增量的 `prevSeqId` 必须等于上一批（已接受的）的 `seqId`。

```rust
// 节选自 crates/adapters/okx/src/book/sync.rs（validate_sequence，有删节）
let mut expected = book.position().copied().flatten();          // 上一批的 seqId
for &(prev_seq_id, seq_id) in sequences {
    let linked = matches!((expected, prev_seq_id),
        (Some(e), Some(p)) if p >= 0 && p as u64 == e);
    if !linked {
        return handle_sequence_gap(book, instrument_id, prev_seq_id, seq_id);  // 断档
    }
    expected = Some(seq_id);
}
book.advance(Some(final_seq_id), now);
BookSequenceOutcome::Accept
```

主线例子：快照（`prevSeqId = -1`，`seqId = 100`）被接受，订单簿同步在 100；增量（101，前一批 100）接得上，接受；下一批增量写着前一批是 103，而本地期待的是 101，说明 102、103 两批丢了，判为断档。

验证的结果是三选一（`BookSequenceOutcome`）：接受（`Accept`）、丢弃这一批但不算错误（`Suppress`，比如重复的快照）、需要恢复（`Recover`）。

## 2. BookSync：一个订单簿的同步状态 {#booksync}

`BookSync` 保存一个订阅中的订单簿的同步状态。它不做任何 I/O，只是一组状态加方法，适配器把它放在自己已有的锁或者所属任务里。它的阶段（`BookPhase`）只有三个：

| 阶段 | 含义 | 输出增量吗 |
| --- | --- | --- |
| `Waiting` | 刚订阅，等第一份快照 | 否 |
| `Synced(P)` | 已同步，`P` 是最后接受的位置（OKX 是 `seqId`） | 是 |
| `Recovering` | 失步，等待恢复 | 否 |

**只有在 `Synced` 阶段才输出。** 失步期间，即使增量源源不断地来，也一条都不交给数据引擎。策略看到的是“订单簿暂时不更新”，而不是一个错误的订单簿。

**失步的订单簿必须有人负责。** 负责者可以是一个正在运行的恢复，或者一个已经设好期限的快照等待。`BookSync::gap()` 把订单簿设为 `Recovering`，如果此时没有任何负责者，就返回 `Recover`，请适配器发起恢复；已经有负责者时返回 `Suppress`。返回 `Recover` 并不代表恢复已经开始，所以适配器要把失步期间的**每一条**增量都交给 `gap()`：如果上一次发起恢复失败了（比如那时连接还没恢复），下一条增量会再次请求。只看“现在是 `Recovering`”就丢弃增量，会让一个没人负责的订单簿永远停在失步状态。

**陈旧检测。** `BookSync::stale(阈值, 现在)` 检查一个没有恢复在运行的订单簿多久没有前进了，超过阈值就返回经过的时间，适配器据此发出一个 `BookSyncSignal`（陈旧，或快照迟迟没来）。信号本身不会触发恢复，由适配器决定怎么办。

## 3. 恢复的四步 {#recovery}

1. **标记**：`gap()` 把订单簿设为 `Recovering`，停止输出。
2. **请求**：同一个调用在没有负责者时返回 `Recover`。
3. **认领**：适配器确认恢复需要的东西都在（连接、频道、令牌），然后调用 `claim()`。`claim()` 一次只允许一个恢复在运行，所以连续的断档报告不会同时发起好几个恢复；认领同时取消原来的快照等待。
4. **运行**：适配器在自己的任务组（第 31 章）里 spawn `BookRecovery::run`。

**快照闸门。** 恢复的方式通常是重新订阅，让交易所再推一份快照。这里有一个竞态：重新订阅的请求还在发送途中，旧订阅的一份快照可能恰好到达；如果接受了它，又会接着应用不连续的增量。所以每次尝试开始时，先关上一个快照闸门（`SnapshotGate`）；等**目标连接确认了订阅写入**之后，才打开闸门；只有闸门打开后到达的、合法的快照才会被 `accept_snapshot` 接受。写入完成本身不算恢复完成，只有接受了新快照才算。

接受快照会把订单簿的所有价位整体替换掉（快照为空时也是），订单簿回到 `Synced`，恢复结束，重新开始输出。

主线例子里：发现 103 断档后，订单簿停止输出；OKX 适配器认领恢复，关闭闸门，重新发送 `books` 的订阅；订阅确认后打开闸门；新快照（`prevSeqId = -1`，`seqId = 210`）到达并被接受，订单簿同步在 210，之后的增量从 211 接着走。

## 4. 恢复失败时 {#retry}

重新订阅也可能失败：连接断了、交易所拒绝、快照一直不来。`BookRecovery::run` 的重试策略是：

- **预算内**：最多 8 次尝试，总时长不超过 180 秒。尝试之间的退避是首次重试立即、之后 1 秒起翻倍、上限 10 秒、加不超过 1 秒的抖动，所以 8 次尝试通常在 40 秒内就用完了（第 6 节实测约 36 秒）。
- **预算用完后**（或者适配器把错误判定为不可重试）：每次尝试间隔从 1 分钟开始翻倍，最长 15 分钟，加抖动，并记一条错误；之后每次失败记一条警告。每次尝试最长 `max(快照超时, 60 秒)`，所以一次卡住的写入或者没有设快照期限，也不会让重试停下来。

**一个订单簿永远不会进入“恢复失败”的终态。** 恢复会一直进行，直到接受了快照，或者恢复被取消（取消订阅、关闭节点）。长间隔的设计是为了限制一个持续失败的订单簿给交易所带来的订阅流量。

**重连不会重置预算。** 网络层重连（第 33 章）时，正在运行的恢复会保留下来，不会因为“换了连接”就重新获得 8 次机会，也不会放弃一次写到一半的订阅。如果恢复正处于预算之后的长间隔等待中，重连会唤醒它，让下一次尝试立即用新连接进行。

![订单簿的同步与恢复：Waiting 收到快照进入 Synced 并开始输出；增量接不上时 gap 把它设为 Recovering 并停止输出，没有负责者时请求恢复；适配器认领后运行恢复，每次尝试关闭快照闸门、重新订阅、确认后打开闸门，接受新快照后回到 Synced；失败时先在 180 秒内重试 8 次，之后间隔从 1 分钟翻倍到 15 分钟](/nautilus-trader/figures/book-sync.svg)

怎么读这张图：上面是三个阶段，只有中间的 `Synced` 输出增量。下面是一次恢复内部的尝试循环，闸门的“关”和“开”夹住了重新订阅的写入。最下面是重试间隔随时间的变化。

## 5. 输出契约与一致性检查 {#contract}

适配器交给数据引擎的订单簿增量要满足一个契约（第 4 章、第 18 章）：

- 每批以带 `F_LAST` 标志的增量结束；批内更早的 `F_LAST` 结束一个事件组，数据引擎按组发布。
- 快照组以 `Clear` 开头，后面全是 `Add`，每条都带 `F_SNAPSHOT`；空快照就是一条单独的 `Clear`。
- 增量组不带 `F_SNAPSHOT`、不含 `Clear`，并且出现在快照之后。
- 订单簿关闭后不再输出。

`crates/live/src/book/conformance.rs` 里的 `BookStreamChecker` 是一个测试工具：它消费适配器输出的增量，遇到第一个违反契约的批次就报错，还能把维护出来的订单簿和交易所的真实订单簿比较，并统计每一次恢复是否都被验证过。官方要求适配器的测试覆盖断档、重连和重新订阅这些场景。

模型层还有一个通用的完整性检查 `book_check_integrity`：买一价不能高于卖一价（订单簿交叉）、L1 订单簿每边只能有一个价位、L2 订单簿每个价位只能有一个聚合订单等。它能发现明显的错误，但发现不了“少了一条增量导致某个价位的数量不对”这种情况，这正是序号检查存在的原因。

## 6. 动手验证 {#lab}

`BookSync` 和 `BookRecovery` 都不做 I/O，可以直接拿来驱动：前半段用一串手写的 OKX 序号走一遍阶段变化和快照闸门，后半段让每次恢复尝试都失败，看重试节奏。后半段跑在 Tokio 的暂停时钟上（`start_paused`），一个半小时的等待瞬间完成，打印的时间是虚拟时间。

::: info 实验环境
Linux（aarch64，4 核、3 GB 内存）上的 Rust 1.100.0，NautilusTrader 各 crate 来自提交 `364254f`。代码是 <a href="/nautilus-trader/code/live-lab/examples/ch35_book_sync.rs" download><code>ch35_book_sync.rs</code></a>，属于第五部分的实验工程 `live-lab`（[在 GitHub 查看](https://github.com/lewislau86/lewislau86.github.io/tree/master/docs/public/nautilus-trader/code/live-lab)，`README.md` 写了运行方法）。运行命令是 `cargo run --example ch35_book_sync`。下面的输出原样摘录，毫秒数每次运行略有不同。
:::

**序号、阶段和认领。** 序号检查照 OKX 适配器的规则简化而来（第 1 节）：

<<< @/public/nautilus-trader/code/live-lab/examples/ch35_book_sync.rs#sequence

```text
start: phase = Waiting
snapshot             ( -1, 500) -> snapshot accepted = true                       phase = Synced(500)
delta                (500, 501) -> linked, emit delta                             phase = Synced(501)
delta                (501, 502) -> linked, emit delta                             phase = Synced(502)
delta (503,504 lost) (504, 505) -> GAP -> gap() = Recover (nobody owns recovery)  phase = Recovering
delta                (505, 506) -> GAP -> gap() = Recover (nobody owns recovery)  phase = Recovering
claim() -> Some(recovery)
delta                (506, 507) -> GAP -> gap() = Suppress                        phase = Recovering
claim() again -> None (one recovery at a time)
stale snapshot       ( -1, 600) -> snapshot accepted = false                      phase = Recovering
fresh snapshot       ( -1, 610) -> snapshot accepted = true                       phase = Synced(610)
recovery accepted = true
delta                (610, 611) -> linked, emit delta                             phase = Synced(611)
```

逐行对照第 2、3 节：

- 快照让订单簿从 `Waiting` 进入 `Synced(500)`，两批增量接上，位置推进到 502。
- 503、504 两批丢失，下一批的 `prevSeqId` 是 504，接不上：`gap()` 把阶段设为 `Recovering`，返回 `Recover`。
- 这时还没有人认领恢复，下一批增量再交给 `gap()`，**又一次**返回 `Recover`。这就是“失步期间每条增量都要交给 `gap()`”的原因：上一次请求如果没能发起恢复，这一次还会再请求。
- `claim()` 之后有了负责者，再来的增量得到 `Suppress`；第二次 `claim()` 返回 `None`，一个订单簿同时只有一个恢复。
- 恢复尝试开始时关上快照闸门（`begin_replacement`）。闸门关着时到达的快照被拒绝，阶段仍是 `Recovering`；订阅确认、打开闸门之后到达的快照被接受，回到 `Synced(610)`，恢复标记为已接受，之后的增量从 610 接着走。

**重试节奏。** 每次尝试都返回错误；在虚拟时间 1,500 秒时模拟一次网络重连：

<<< @/public/nautilus-trader/code/live-lab/examples/ch35_book_sync.rs#retry

```text
  [t = 1500 s] network reconnected -> reset_on_reconnect()
  attempt  1 at     0.0 s  (+   0.0 s)
  attempt  2 at     0.0 s  (+   0.0 s)
  attempt  3 at     1.3 s  (+   1.3 s)
  attempt  4 at     3.6 s  (+   2.3 s)
  attempt  5 at     8.6 s  (+   5.0 s)
  attempt  6 at    16.7 s  (+   8.1 s)
  attempt  7 at    26.4 s  (+   9.7 s)
  attempt  8 at    35.5 s  (+   9.1 s)
  attempt  9 at    99.9 s  (+  64.4 s)
  attempt 10 at   222.8 s  (+ 122.9 s)
  attempt 11 at   464.9 s  (+ 242.0 s)
  attempt 12 at   947.2 s  (+ 482.4 s)
  attempt 13 at  1500.0 s  (+ 552.8 s)
  attempt 14 at  2398.0 s  (+ 898.0 s)
  attempt 15 at  3296.7 s  (+ 898.6 s)
  attempt 16 at  4192.1 s  (+ 895.4 s)
  attempt 17 at  5089.6 s  (+ 897.5 s)
```

和第 4 节的描述对照，有一处要说得更准确：

- **预算内的 8 次尝试只用了约 36 秒，不是 180 秒。** 预算的退避是“首次重试立即、之后 1 秒起翻倍、上限 10 秒、加不超过 1 秒的抖动”，所以前 8 次尝试在 0、0、1.1、3.5、8.4、16.8、26.6、36.3 秒。180 秒是这一阶段总时长的上限，不是 8 次尝试平摊的时间。
- **预算用完后从 1 分钟翻倍到 15 分钟。** 第 9 次起的间隔是 63、120、242、483 秒，之后封顶在 895～900 秒（抖动不超过 5 秒）。
- **重连唤醒长间隔等待，但不重置预算。** 1,500 秒时那次重连让正在进行的长等待立即结束，第 13 次尝试马上进行；之后的间隔仍是约 900 秒，没有回到预算内的快速重试。

::: warning 常见误区
- **以为丢一条增量会报错。** 本地订单簿只会悄悄地错下去，必须靠序号发现。
- **失步期间继续把增量交给数据引擎。** 失步时一条都不输出，直到接受新快照。
- **失步期间只看阶段就丢弃增量，不再调用 `gap()`。** 上一次没能发起恢复的订单簿会永远失步。
- **重新订阅的写入一完成就接受下一份快照。** 要等目标连接确认写入、打开闸门后才接受。
- **以为恢复失败若干次后会放弃。** 它会以越来越长的间隔一直重试，直到成功或被取消。
- **以为 `book_check_integrity` 能发现丢失的增量。** 它只能发现交叉、层级数这类结构性错误。
:::

## 本章结论

增量订单簿丢一条增量就会悄悄出错，所以适配器用交易所的序号验证每一批是否接得上，结果是接受、丢弃或需要恢复。`BookSync` 为每个订阅中的订单簿保存三个阶段，只有同步时才输出；失步的订单簿必须有一个负责者，`gap()` 在没有负责者时请求恢复，适配器认领后运行 `BookRecovery`。每次尝试先关闭快照闸门，重新订阅并得到确认后才打开，只有接受了新快照才算恢复完成。重试先用 8 次尝试的预算（快速退避，总时长不超过 180 秒，实测约 36 秒用完），之后间隔从 1 分钟翻倍到 15 分钟，永不放弃；重连会唤醒长间隔等待，但不重置预算。适配器的输出要满足 `F_LAST`、`F_SNAPSHOT` 的事件边界契约，测试用 `BookStreamChecker` 检查。

## 检查理解

1. OKX 推来的三批数据依次是：快照（-1，500）、增量（500，501）、增量（501，502）、增量（504，505）。每一批的验证结果是什么？之后发生什么？

   <details><summary>参考答案</summary>

   快照：接受，同步在 500。增量（500，501）：接受，同步在 501。增量（501，502）：接受，同步在 502。增量（504，505）：前一批是 504，但本地期待 502，说明 503、504 丢了，判为断档；订单簿进入 `Recovering`，停止输出，没有负责者时返回 `Recover`，OKX 适配器认领恢复并重新订阅，等待新快照。

   </details>

2. 恢复正在进行，网络层这时重连了。重连之后，恢复的 8 次重试预算会被重置吗？

   <details><summary>参考答案</summary>

   不会。正在运行的恢复在重连期间保留，既不重新获得预算，也不会丢下一个写到一半的订阅请求。只有当恢复已经用完预算、正处于长间隔等待中时，重连才会唤醒它，让下一次尝试立即在新连接上进行。

   </details>

3. 策略订阅了订单簿，突然连续 30 秒没有收到任何更新。可能是什么原因？怎样区分？

   <details><summary>参考答案</summary>

   可能是订单簿失步、正在恢复（这期间不输出），也可能是交易所那边这个品种确实没有变化，或者连接断了。适配器的陈旧检测会对一个没有恢复在运行、又长时间没有前进的订单簿发出 `BookSyncSignal`；连接断开则会有第 33 章的 `SocketStateChanged` 事件；正在恢复时，日志里有“Book sequence gap … requesting a fresh snapshot”和恢复的进度。结合这三种信息可以判断原因。

   </details>

## 参考资料

- 官方文档：[Adapters 开发指南](https://nautilustrader.io/docs/latest/developer_guide/adapters/)（Order book recovery ownership） · [Data](https://nautilustrader.io/docs/latest/concepts/data/)
- 源码：[`crates/live/src/book/sync.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/live/src/book/sync.rs) · [`crates/live/src/book/recovery.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/live/src/book/recovery.rs) · [`crates/live/src/book/snapshot.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/live/src/book/snapshot.rs) · [`crates/adapters/okx/src/book/sync.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/adapters/okx/src/book/sync.rs) · [`crates/model/src/orderbook/analysis.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/model/src/orderbook/analysis.rs)
- 实验代码：[`live-lab`](https://github.com/lewislau86/lewislau86.github.io/tree/master/docs/public/nautilus-trader/code/live-lab) 的 `examples/ch35_book_sync.rs`
- 配图由 `scripts/generate-nautilus-trader-figures.py` 生成。

对账和订单簿恢复都依赖“重启后还能找回之前的状态”。下一章看缓存怎样落盘到 Redis 或 PostgreSQL，以及消息总线怎样把消息发布到外部的消息流。[第 36 章：外部后端](./external-backends.md)。
