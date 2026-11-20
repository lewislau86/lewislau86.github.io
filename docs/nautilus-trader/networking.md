---
title: "第 33 章：网络层：HTTP、WebSocket 与 Socket 客户端"
description: nautilus-network 提供的三种客户端各适合什么；GCRA 限流怎样用一个“理论到达时间”实现突发和匀速，一个请求怎样同时等待多个额度；WebSocket 客户端的控制器、写入任务、读取任务和心跳任务；心跳超时与空闲超时的区别；重连的指数退避、抖动、稳定阈值和每两分钟三次的节流；连接纪元；套接字状态怎样变成总线上的事件，重连命令怎样下达；原始 TCP 客户端的分帧限制。
---

# 第 33 章：网络层：HTTP、WebSocket 与 Socket 客户端

[全书目录](./index.md) · [上一章](./live-clock.md) · [下一章](./reconciliation.md)

::: tip 本章学习目标
能根据交易所的接口形式选择 HTTP、WebSocket 或原始 TCP 客户端；能手算一个 GCRA 额度允许的突发数和之后的节奏，知道一个请求带多个限流键时怎样等待；能说出 WebSocket 客户端里四个后台任务的分工；能区分心跳超时和空闲超时；能写出默认配置下的重连等待序列，知道什么时候退避会被重置、什么时候会被节流；知道策略怎样得知连接断开、怎样请求重连。

**源码版本：** `develop` 分支，提交 `364254f`（2026-11-18）。网络层在 `crates/network/src/`：HTTP 在 `http/client.rs`，限流在 `ratelimiter/`（`gcra.rs`、`quota.rs`、`mod.rs`），WebSocket 在 `websocket/client.rs` 和 `websocket/config.rs`，退避在 `backoff.rs`，TCP 在 `socket/client.rs`。套接字状态和重连命令在 `crates/common/src/messages/system/socket.rs`、`crates/live/src/socket.rs` 和 `crates/live/src/node/mod.rs`。OKX 的用法在 `crates/adapters/okx/src/http/client.rs` 和 `websocket/client.rs`。

**对应官方文档：** [Networking](https://nautilustrader.io/docs/latest/concepts/networking/)
:::

适配器要和交易所通信，绝大多数交易所提供两种接口：下单、查询用 HTTP 请求，行情和订单推送用 WebSocket 长连接。少数券商（比如第 38 章的富途 OpenD）用自定义的 TCP 协议。`nautilus-network` 这个 crate 为这三种情况各提供一个客户端，在底层库之上加了交易系统需要的策略：限流、连接复用、存活检测、重连控制和有界读取。适配器只负责把交易所的消息翻译成 NautilusTrader 的数据和事件（第 38 章）。

主线例子是 OKX 适配器：它的 HTTP 客户端有一个全局额度和几十个按接口的额度；它的 WebSocket 客户端每隔一段时间发一个文本 `ping`，其余配置全部用默认值。

## 1. 三种客户端 {#clients}

| 客户端 | 底层库 | 适合 | 额外提供 |
| --- | --- | --- | --- |
| `HttpClient` | Hyper | 一问一答的请求 | 多层限流、连接池、超时、代理、有界响应体 |
| `WebSocketClient` | tokio-tungstenite 或 sockudo-ws | 长期的消息流 | 限流、心跳、存活检测、自动重连、连接纪元 |
| `SocketClient` | Tokio 加 rustls | 按后缀分隔的字节流 | 分帧、初次重试、心跳、重连、按序重放 |

WebSocket 的底层库在运行时由配置的 `backend` 选择，两者都被包在一个中性的传输接口后面，所以适配器不依赖具体的 WebSocket 库。

## 2. 限流：GCRA {#rate-limit}

交易所对请求频率有严格限制，超限会被拒绝甚至封 IP。网络层的限流器用 **GCRA**（通用信元速率算法）。一个额度 `Quota` 有两个参数：突发上限 `max_burst` 和补充间隔（每多久补充一个名额）。比如 `Quota::per_second(10)` 表示突发上限 10、每 100 毫秒补充一个。

GCRA 不维护一个“桶里还剩几个令牌”的计数器，而是给每个键只存一个时间：**理论到达时间**（TAT）。设补充间隔为 T，容忍度 τ = T × 突发上限：

- 请求在时刻 t 到来时，如果 `t < TAT - τ`，被拒绝，要等到 `TAT - τ`；
- 否则放行，并把 TAT 推进到 `max(TAT, t + T) + T`。

用 `per_second(10)` 手算：T = 100 毫秒，τ = 1 秒。时刻 0 连续来 11 个请求：第 1 个之后 TAT = 200 毫秒，第 k 个之后 TAT = 100 × (k + 1) 毫秒；第 10 个之后 TAT = 1,100 毫秒，第 11 个检查时 `TAT - τ = 100 毫秒 > 0`，要等 100 毫秒。之后每 100 毫秒放行一个。这正是“突发 10 个、之后每秒 10 个”的含义，而且每个键只需要一个 64 位原子整数，并发更新用比较交换完成。

**多个键。** 一个限流器有一个默认额度和若干按键的额度，一个请求可以带多个键，同时等待它们（`await_keys_ready`）。OKX 的 HTTP 客户端给每个请求都带上全局键 `okx:global`（每秒 250 个），再加上接口自己的键，比如查余额 `okx:/api/v5/account/balance`（每秒 5 个）。查余额的请求要两个额度都有名额才发出。多个 HTTP 客户端共享同一个限流器（`Arc`）时，额度是进程级的，而不是每个连接各有一份。

## 3. WebSocket 客户端的内部 {#websocket}

一个处于处理器模式（handler mode）的 WebSocket 客户端内部有四个后台任务：

- **控制器**：负责连接状态的转换，包括重连和关闭；
- **写入任务**：唯一操作发送端的任务，所有发送（包括心跳）都经过它，保证不会并发写；
- **读取任务**：每个连接一个，把收到的消息交给适配器的回调；
- **心跳任务**（可选）：按固定间隔通过写入任务发 Ping 帧或交易所规定的文本。

另一种流模式（stream mode）把读取交给调用方，不自动重连，适合需要自己控制背压或有特殊重连流程的适配器。`nautilus-network` 在依赖关系上位于 `nautilus-live` 之下，用不了第 31 章的 `TaskGroup`，这几个任务由客户端自己用 `JoinHandle` 持有、在关闭时收尾；适配器自己 spawn 的消息处理任务才放进 `TaskGroup`。

**发送的语义。** 普通的发送方法在消息进入写入队列后就返回，**返回成功不代表已经送达**。重连期间或写入失败后，应用消息留在缓冲区里，按先进先出顺序在新连接上重放；但控制帧（Ping、Pong、Close）属于发出它的那个连接，失败就丢弃，不重放。写入队列、在途写入和重连缓冲合计最多 1,024 条（`writer_capacity`）。

**连接纪元。** 每换一次底层连接，纪元加一。读取任务会丢弃旧纪元的帧；适配器可以用“绑定纪元”的发送方法，要求消息只能发到某一次连接上，连接换了就失败而不是重放。这对下单这类不能在不确定的连接上重发的消息很重要：绑定纪元的写入如果在开始后超时，结果是**不确定**的，调用方不能盲目重试，要交给对账（第 34 章）。

## 4. 存活检测 {#liveness}

连接可能“假活”：TCP 没断，但对面已经不发东西了。有两种超时检测它：

- **心跳超时**：收到**任何**帧（包括 Ping、Pong）都会重置。配置了心跳间隔而没配心跳超时时，默认是 3 倍心跳间隔。它检测的是“对面完全沉默”。
- **空闲超时**：只有收到**文本或二进制的应用数据**才会重置。它检测的是“连接还活着，但行情不推了”，控制帧不能掩盖这种情况。默认不开启；要开启，它应该小于心跳间隔才有意义。

读写失败、收到 Close 帧、任一超时、显式的重连请求，都会让客户端进入重连状态。

## 5. 重连 {#reconnect}

重连等待用指数退避加抖动，默认参数是：初始 2 秒、上限 30 秒、倍数 1.5、抖动 0～100 毫秒，而且**第一次重连立即进行**。所以一次断线之后，各次尝试前的等待大约是：

```text
0 → 2.0 s → 3.0 s → 4.5 s → 6.75 s → 10.1 s → 15.2 s → 22.8 s → 30 s → 30 s …（每次另加 0～100 ms）
```

默认不限次数。三条额外的规则：

- **稳定阈值**：新连接保持 10 秒以上，退避和次数都重置。所以偶尔断一次总是从“立即重连”开始。
- **节流**：任意两分钟的滑动窗口内已经有 3 次重连尝试时，此后每次至少等 1 秒，不论退避算出多少。原因是交易所按 IP 限制新建连接的频率（官方文档举例，币安是每 5 分钟 300 个，OKX 是每秒 3 个），一个不加节流的重连循环可能把一次短暂断线变成整个 IP 被封。
- **次数上限**：配置了 `reconnect_max_attempts` 时，连续失败（或连上不到 10 秒又断）达到这个次数，客户端关闭。设为 0 表示断了就关闭，不重连。

重连成功后，交易所那边的订阅和登录状态都没了。网络层提供两个辅助：`AuthTracker` 在断线时把认证状态标记为失效，可以让重连缓冲里的消息等到重新认证后再发；`SubscriptionState` 记录已确认、待订阅、待退订的主题，由适配器据此重新订阅。网络层自己不发任何协议消息。

## 6. 让节点知道连接状态 {#state}

客户端可以配置一个 `SocketStateSink`。它只发布两种边沿：连上了（`Connected`）、断开了（`Disconnected`）：

1. 初次连接成功，发布 `Connected`；
2. 连接丢失或接受了显式的重连请求，发布 `Disconnected`；
3. 新连接成功，发布 `Connected`。

单次重连尝试、重试耗尽、主动断开都不发布。这些边沿作为**系统事件**进入第 30 章的系统事件 channel，节点把它包成 `SocketStateChanged`，发布到总线主题 `events.system.SocketStateChanged.{client_id}.{endpoint}`。策略或 Actor 订阅 `events.system.SocketStateChanged.OKX.*` 这样的模式，就能在行情断开时暂停下单。

反方向，组件可以发一个 `ReconnectSocket { client_id, endpoint }` 系统命令，节点在套接字登记表里找到对应的重连句柄，调用 `request_reconnect()`。结果分为已接受、已在重连、已断开、已关闭、不支持（流模式）、找不到客户端或端点几种，被拒绝时记警告。

![WebSocket 客户端的结构与重连：适配器经限流器把消息交给写入任务，读取任务把消息交给适配器，心跳任务经写入任务发送；控制器在连接丢失、超时或收到重连请求时进入重连，按指数退避等待，成功后换上新连接、纪元加一，并通过状态接收器发布 Connected 与 Disconnected，节点把它们变成总线上的 SocketStateChanged 事件](/nautilus-trader/figures/websocket-client.svg)

怎么读这张图：上半部分是一个连接内部的四个任务，所有写入都汇到写入任务。下半部分是控制器的状态和重连等待序列。右侧是状态边沿怎样经节点变成总线上的事件，以及重连命令的反向路径。

## 7. 原始 TCP 客户端 {#socket}

`SocketClient` 用于不走 HTTP 和 WebSocket 的协议。它按**后缀**分帧：每条消息以一个约定的字节序列结尾（比如 `\r\n`），客户端在字节流里找这个后缀切出消息。空后缀会被拒绝。它同样有心跳、存活检测、重连和按序重放。

这意味着“包头里写长度”的二进制协议（比如富途 OpenD：44 字节的包头里带包体长度）不能直接用它，要自己写一个按长度分帧的编解码器，连接本身仍然通过网络层建立，以便沿用 TLS 和套接字选项。第 38 章的富途方案就是这样做的。

::: warning 常见误区
- **以为 WebSocket 的 `send` 返回成功就是交易所收到了。** 它只表示进入了写入队列。
- **对绑定纪元的写入超时后直接重发。** 结果不确定，可能重复下单，要交给对账确认。
- **只配置心跳，以为能发现行情断流。** 交易所回 Pong 就会重置心跳超时，要发现行情断流得配置空闲超时。
- **把重连上限设成 0 以为是“无限重连”。** 0 表示不重连；默认（不设置）才是无限。
- **每个 HTTP 客户端各建一个限流器。** 额度会成倍放大，应共享同一个限流器。
- **以为重连后订阅会自动恢复。** 网络层只记录订阅意图，重新订阅由适配器完成。
- **用 `SocketClient` 接一个按长度分帧的协议。** 它只支持后缀分帧。
:::

## 本章结论

网络层为 HTTP、WebSocket 和后缀分帧的 TCP 各提供一个客户端，适配器在其上只做协议翻译。限流用 GCRA，每个键只存一个理论到达时间，额度表示为“突发上限加补充间隔”，一个请求可以同时等待多个键。WebSocket 客户端由控制器、写入、读取、心跳四个任务组成，所有写入经同一个写入任务；心跳超时检测对面沉默，空闲超时检测行情断流。断线后按“立即、2 秒起、1.5 倍、上限 30 秒、加抖动”的退避重连，稳定 10 秒后重置，两分钟内超过 3 次则每次至少等 1 秒。连接状态的变化以 `SocketStateChanged` 事件发布到总线，组件也可以用 `ReconnectSocket` 命令请求重连。

## 检查理解

1. 额度是 `Quota::per_second(5)`。时刻 0 一次来了 8 个请求，各在什么时候被放行？

   <details><summary>参考答案</summary>

   T = 200 毫秒，τ = 1 秒。前 5 个在时刻 0 立即放行，之后 TAT = 1,200 毫秒；第 6 个要等到 `TAT - τ = 200 毫秒`，放行后 TAT = 1,400；第 7 个在 400 毫秒；第 8 个在 600 毫秒。也就是突发 5 个，之后每 200 毫秒一个。

   </details>

2. OKX 的行情连接在 10:00:00 断开，之后前四次重连都失败，第五次成功。默认配置下，大约在什么时候连上？如果连上 5 秒后又断了呢？

   <details><summary>参考答案</summary>

   第一次立即尝试（10:00:00），失败后等 2 秒、3 秒、4.5 秒、6.75 秒（各加不到 0.1 秒的抖动），但两分钟内第 4 次起受节流约束，每次至少等 1 秒，这里退避本来就大于 1 秒，不受影响。第五次尝试大约在 10:00:16.3 前后成功。连上 5 秒后又断，不满 10 秒稳定阈值，退避不重置，下一次等待接着是约 10.1 秒；同时两分钟内已有多次尝试，节流仍然生效。

   </details>

3. 一个策略希望行情连接断开时立即撤掉所有挂单，恢复后再重新报价。应该订阅什么？

   <details><summary>参考答案</summary>

   订阅总线模式 `events.system.SocketStateChanged.OKX.*`（或具体的端点）。收到 `Disconnected` 时撤单，收到 `Connected` 时恢复报价。注意只有可用性的边沿才会发布：单次重连尝试失败不会产生事件，所以不会收到一连串 `Disconnected`。

   </details>

## 参考资料

- 官方文档：[Networking](https://nautilustrader.io/docs/latest/concepts/networking/)
- 源码：[`crates/network/src/ratelimiter/gcra.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/network/src/ratelimiter/gcra.rs) · [`crates/network/src/backoff.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/network/src/backoff.rs) · [`crates/network/src/websocket/client.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/network/src/websocket/client.rs) · [`crates/network/src/socket/client.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/network/src/socket/client.rs) · [`crates/live/src/socket.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/live/src/socket.rs)
- 配图由 `scripts/generate-nautilus-trader-figures.py` 生成。

网络会断，请求会超时，交易所的回报会丢。本地状态和交易所的真实状态迟早会不一致。下一章看实盘节点怎样发现并修正这种不一致。[第 34 章：ExecutionManager 与对账](./reconciliation.md)。
