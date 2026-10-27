---
title: "第 8 章：发布订阅为什么改变连接状态"
description: "服务器怎样主动推送，慢订阅者会怎样？"
pageClass: mini-redis-course
---

# 第 8 章：发布订阅为什么改变连接状态

[课程总览](/mini-redis/index.md) · [上一章](/mini-redis/expiration.md) · [下一章](/mini-redis/clients.md)

::: tip 本章学习目标
**要解决的问题：** 服务器怎样主动推送，慢订阅者会怎样？

**顺路学到的 Rust：** channel、Stream、Pin、trait 对象

**语法速查：** [逐项拆解模块、类型与异步语法](/mini-redis/rust-reading-guide.md#streams)

**对应源码：** [src/cmd/publish.rs](/mini-redis/source/src/cmd/publish.md)、[src/cmd/subscribe.rs](/mini-redis/source/src/cmd/subscribe.md)、[src/db.rs](/mini-redis/source/src/db.md)、[src/clients/client.rs](/mini-redis/source/src/clients/client.md)、[examples/pub.rs](/mini-redis/source/examples/pub.md)、[examples/sub.rs](/mini-redis/source/examples/sub.md)。完整的一一对应关系见 [源码文章索引](/mini-redis/source/index.md)。
:::

<MiniRedisMap active="pubsub" />

GET 是客户端先问、服务器再答。订阅新闻频道后，客户端可能很久不发请求，服务器却需要在别人发布消息时主动推送。这就不再是简单的“一次请求对应一次普通响应”。

## 先把两条连接与一个内部通道分开

![订阅客户端经订阅 Handler 取得 broadcast Receiver；发布客户端经发布 Handler 调用 Sender.send；消息在进程内到达订阅 Handler 后推送给订阅客户端，发布 Handler 返回接收者数](/mini-redis/figures/pubsub-flow.svg)

`Db::publish` 没有直接调用订阅连接的 write_frame。它发的是进程内消息，实际写 TCP S 的仍是 Handler S；返回给发布者的整数则由 Handler P 写到 TCP P。一个订阅者断线，不会因为同一条函数返回链而直接使发布者的 Handler 退出。

这也是后面读代码时的定位规则：`dst` 始终属于正在执行这个 apply 的连接。不同 apply 中叫同一个名字的 dst，不代表它们共享 socket。

## 两张名字相似、用途不同的表

Db 中 `entries` 保存键值，`pub_sub` 保存频道到 `broadcast::Sender<Bytes>` 的映射。频道名恰好等于某个数据键，也不会使它们成为同一个对象。

`Db::subscribe(channel)` 使用 HashMap 的 entry API：

```rust
// 源码关键分支；Entry 在此是 HashMap 的占用/空缺枚举。
match state.pub_sub.entry(key) {
    Entry::Occupied(e) => e.get().subscribe(),
    Entry::Vacant(e) => {
        let (tx, rx) = broadcast::channel(1024);
        e.insert(tx);
        rx
    }
}
```

Occupied/Vacant 让“找到已有频道或插入新频道”在一次 entry 操作里表达。这里的 `Entry` 是导入的 `std::collections::hash_map::Entry`，与存储值的自定义 Entry 只是同名；阅读局部 `use` 能避免混淆。

每个频道有一个有界 broadcast 通道。每次 subscribe 返回自己的 Receiver；发布者通过 Sender 发送，接收者各自推进读取进度。没有活跃接收者时，本地 publish 返回 0；有接收者时返回发送那一刻的接收者数量。

## Subscribe::apply 接管连接

[subscribe.rs](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/mini-redis/source/src/cmd/subscribe.rs) 建立 `StreamMap<String, Messages>`，把多个频道的消息源合并在同一个连接任务里。它循环等待三类事件：

```text
某个频道有消息 ─→ 写 ["message", channel, content]
客户端又发命令 ─→ 更新订阅集合或返回错误
收到停机通知   ─→ 返回，释放订阅与连接
```

将上面的三类事件对应到 [Subscribe::apply](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/mini-redis/source/src/cmd/subscribe.rs) 的实际循环，保留当前源码中的中文注释如下：

<!-- source: src/cmd/subscribe.rs:71-108; comments included -->
```rust
// 每个频道有一个 broadcast Receiver；StreamMap 按频道名管理流并合并消息。
    // 频道名唯一，同名 insert 会替换原流，不创建同名并列条目。
    let mut subscriptions = StreamMap::new();

    loop {
        // drain(..) 取出并清空待订阅列表，所有 String 移交建立订阅函数。
        // 后续 SUBSCRIBE 会重新往该 Vec 添加项，下轮循环再处理。
        for channel_name in self.channels.drain(..) {
            subscribe_to_channel(channel_name, &mut subscriptions, db, dst).await?;
        }

        // select 同时等待频道消息、socket 命令和停止；选中分支内的 write_frame 仍需 await。
        // 因此等待写回时，这个任务不会同时处理另一分支。
        select! {
            // Some 模式只接收有消息的流结果；空 StreamMap 返回 None 时本轮禁用该分支。
            Some((channel_name, msg)) = subscriptions.next() => {
                dst.write_frame(&make_message_frame(channel_name, msg)).await?;
            }
            res = dst.read_frame() => {
                let frame = match res? {
                    Some(frame) => frame,
                    // 对端 EOF 结束订阅；流被释放，Receiver 也随之释放。
                    None => return Ok(())
                };

                handle_command(
                    frame,
                    &mut self.channels,
                    &mut subscriptions,
                    dst,
                ).await?;
            }
            _ = shutdown.recv() => {
                return Ok(());
            }
        };
    }
}
```

调用它的外层 Handler 正停在 `cmd.apply(...).await`，因此外层 read_frame 暂时不会再执行；客户端发来的后续命令由这里的 dst.read_frame 接手。函数里没有“订阅数为零则 return”的分支，退订计数降到零后连接仍停留在这个循环中。

`self.channels` 是尚待建立的订阅，`subscriptions` 是已经在监听的集合，二者职责不同。handle_command 收到新 SUBSCRIBE 时只追加待办，下一轮 drain 才调用 subscribe_to_channel；收到 UNSUBSCRIBE 则移除已有流并发送确认。

进入 [subscribe_to_channel](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/mini-redis/source/src/cmd/subscribe.rs) 看资源交接：

<!-- source: src/cmd/subscribe.rs:127-149; comments included -->
```rust
let mut rx = db.subscribe(channel_name.clone());

// stream! 把 recv 循环适配成 Stream；yield 产出一个值后暂停，下一次轮询继续。
// Box::pin 装箱并固定这个匿名流，Receiver 的所有权随流保存。
let rx = Box::pin(async_stream::stream! {
    loop {
        match rx.recv().await {
            Ok(msg) => yield msg,
            // 接收落后时跳过已丢消息继续；当前实现不会把丢失数量通知客户端。
            Err(broadcast::error::RecvError::Lagged(_)) => {}
            Err(_) => break,
        }
    }
});

// 按频道名存入此连接的 StreamMap；clone 为键保留独立的 String。
subscriptions.insert(channel_name.clone(), rx);

// 订阅建立后才发确认，携带该连接当前频道数量。
let response = make_subscribe_frame(channel_name, subscriptions.len());
dst.write_frame(&response).await?;

Ok(())
```

Db 创建/复用频道并返回 Receiver；这里将 Receiver 移进流，流放入当前连接自己的 StreamMap，然后写订阅确认。因而确认到达客户端前，服务端已经建立接收关系。移除 StreamMap 中的流会释放对应 Receiver，但不会顺便删除 Db.pub_sub 中的 Sender 表项。


最初 SUBSCRIBE 还会逐频道确认 `['subscribe', channel, 当前订阅数]`。UNSUBSCRIBE 回 `['unsubscribe', channel, 剩余订阅数]`。这些是数组帧，末尾计数是 Integer 帧，而非文本数字。

`self.channels.drain(..)` 一边交出待订阅的 String，一边将列表清空，因此下一轮不会把老的待办再做一遍。新增 SUBSCRIBE 会把名字追加到待办列表，下一轮再建立流。

在当前实现里，订阅后的连接只处理 SUBSCRIBE 和 UNSUBSCRIBE；其他命令交给 Unknown 返回错误。即使所有频道都退订了，连接也继续留在内部循环里，保持订阅处理模式。真正 Redis 的订阅规则还区分协议版本，见[官方 Pub/Sub 文档](https://redis.io/docs/latest/develop/pubsub/)。

## Publish 的返回值在哪结束，推送又在哪继续

[Publish::apply](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/mini-redis/source/src/cmd/publish.rs) 接受的 dst 属于发布连接：

<!-- source: src/cmd/publish.rs:42-54; comments included -->
```rust
pub(crate) async fn apply(self, db: &Db, dst: &mut Connection) -> crate::Result<()> {
    // Db 向 broadcast Sender 同步发送，得到当前接收者数量。
    // 接收者可能随后断开或落后丢消息，因此数量不是投递完成或消费确认。
    let num_subscribers = db.publish(&self.channel, self.message);

    // 把数量转换为协议 Integer，交回发布者。
    let response = Frame::Integer(num_subscribers as u64);

    // 写发布结果；即使这里失败，之前的广播也不会撤销。
    dst.write_frame(&response).await?;

    Ok(())
}
```

它调用的 [Db::publish](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/mini-redis/source/src/db.rs) 只访问内部频道表：

<!-- source: src/db.rs:187-197; comments included -->
```rust
pub(crate) fn publish(&self, key: &str, value: Bytes) -> usize {
    let state = self.shared.state.lock().unwrap();

    state
        .pub_sub
        .get(key)
        // 有 Sender 时尝试 send；没有活接收者会失败，转成数量 0。
        .map(|tx| tx.send(value).unwrap_or(0))
        // 频道不存在时 Option 为 None，直接返回 0。
        .unwrap_or(0)
}
```

没有频道或没有活跃接收者，都映射为 0；成功的 send 结果被编码成整数。到这里并没有等待各订阅客户端收到，更没有等待业务消费确认。之后各接收任务分别从 StreamMap 得到消息，构造 `["message", channel, content]` 才写出。

| 事件 | 当场改变的状态/控制流 | 影响范围 |
| --- | --- | --- |
| SUBSCRIBE 确认发送成功 | 当前连接保留流并进入 select | 只切换这个连接的处理模式 |
| 某 Receiver 落后，出现 Lagged | 流忽略此错误并继续 recv | 此接收者缺失旧消息；不会向发布者追溯报错 |
| 订阅连接写推送失败 | Subscribe::apply 的 `?` 返回到外层 Handler | 结束订阅连接，释放它的各 Receiver |
| 发布后回整数失败 | Publish::apply 返回 Err | 发布连接失败；已发入内部通道的消息不会回滚 |
| 退订到零 | StreamMap 清空，循环仍等命令/停止 | 连接保持订阅处理模式，而不是重新获得 GET 能力 |


## 读懂一行看起来很难的类型

```rust
type Messages = Pin<Box<dyn Stream<Item = Bytes> + Send>>;
```

从内到外读：

| 部分 | 这里的含义 |
| --- | --- |
| `Stream` | 类似异步迭代器，一次次产生值 |
| `Item = Bytes` | 关联类型 Item 指定每次产出 Bytes |
| `dyn Stream` | 用统一接口持有具体类型被隐藏的流 |
| `+ Send` | 允许这个流随任务在线程间移动 |
| `Box` | 在堆上持有流，给外层一个固定大小的指针表示 |
| `Pin` | 对需要固定位置的值约束移动，以满足异步状态的安全要求 |

移动外层 Pin/Box 句柄时，移动的只是指针，堆上已固定的流留在原位。你暂时不需要手写 unsafe 投影，只要理解为什么组合流需要这一层包装。

`async_stream::stream!` 把 `rx.recv().await` 的循环包装为流；`yield msg` 每次产出一条消息。Future 通常完成一次，Stream 可以多次产出。`StreamExt` 扩展 trait 提供 `.next()` 这样的便利方法，因此 `use` 一个 trait 有时是为了让方法调用可用。

## 慢订阅者不是可靠队列

每个 broadcast 通道容量为 1024。接收者跟不上时，旧消息会被覆盖，`recv` 返回 `Lagged`。当前源码对这个分支直接跳过，再继续接收；既没有重放，也没有向客户端汇报缺了多少条。

这是一种“尽力推送”机制：网络中断、进程退出或消费落后都可能使消息丢失。Redis Pub/Sub 同样不提供持久重放语义；需要消费组、确认和历史记录时，应进一步学习 Streams 等机制。

还有一个本地限制：[Subscriber::next_message](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/mini-redis/source/src/clients/client.rs) 通过 `content.to_string()` 再构造 Bytes。非 UTF-8 的 Bulk 会走展示字符串路径，所以高级订阅 API 只对文本内容保证往返一致。配套实验使用文本消息；底层帧保存 Bytes 与高级 API 处理 Bytes 是两个不同的验证点。

## 亲手收一条消息

保持第 1 章的服务运行，终端 B：

```sh
cargo run --locked --bin mini-redis-cli -- --port 16379 subscribe news
```

终端 C：

```sh
cargo run --locked --bin mini-redis-cli -- --port 16379 publish news hello
```

终端 B 应打印频道及 `hello` 内容。先让订阅命令完成再发布，避免消息在订阅建立之前被发走；可自动复现的版本见 [roundtrip 实验](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/mini-redis/source/docs/labs/src/bin/roundtrip.rs)，它等待 subscribe API 成功返回后才发布。

::: warning 常见误区
- **publish 的返回值不是送达确认。** 它只是发送那一刻的接收者数量；接收者随后可能断开或因落后丢消息。
- **退订到零不会恢复普通客户端。** 当前实现没有“订阅数为零则 return”的分支，连接仍只处理 SUBSCRIBE/UNSUBSCRIBE。
- **Pub/Sub 不是可靠队列。** 慢订阅者遇到 Lagged 会静默跳过旧消息，没有重放，也不能据此推导“至少送达一次”；需要持久任务队列时应考虑 Streams 等机制。
- **Pin 不是线程锁。** 它只约束值的移动，不负责并发互斥。
- **底层帧保存 Bytes 不等于高级订阅 API 二进制无损。** `next_message` 经过 `to_string()`，非 UTF-8 内容不能保证往返一致。
:::

## 本章结论 {#summary}

订阅让一条连接从“一问一答”切换成服务器主动推送：Subscribe::apply 接管连接，用 StreamMap 合并多个频道的 broadcast Receiver，并在 select 中同时等待频道消息、新命令和停机通知。发布与推送经由进程内通道解耦，Handler P 只把接收者数量写回发布者，各订阅 Handler 再各自把消息写到自己的 socket。

broadcast 通道容量有界，慢订阅者会丢掉旧消息，因此这套机制提供的是尽力推送语义；需要确认与重放时要换用其他机制。

## 检查理解

1. 为什么不能在正在等待订阅消息的同一 Client 上直接调用 GET？

   <details><summary>参考答案</summary>

   线上随时可能出现主动推送，不能再按“下一帧必然是刚才 GET 的响应”解释数据。服务端已进入订阅循环，客户端 API 也通过消费 Client、返回 Subscriber 表达状态变化。普通查询应使用另一个连接。

   </details>

2. `Db::publish` 返回 0 有哪两种情况？

   <details><summary>参考答案</summary>

   一是 pub_sub 中没有这个频道，`get` 得到 None；二是频道存在但没有活跃接收者，`tx.send` 失败，经 `unwrap_or(0)` 转成 0。

   </details>

3. 订阅确认为什么能保证服务端已经建立接收关系？

   <details><summary>参考答案</summary>

   subscribe_to_channel 先从 Db 取得 Receiver，把它装进流并放入当前连接的 StreamMap，之后才写订阅确认。客户端收到确认时，接收端已经就位。

   </details>

4. 某个订阅者的 Receiver 落后、出现 Lagged，会发生什么？

   <details><summary>参考答案</summary>

   流忽略这个错误继续 recv，该接收者缺失被覆盖的旧消息；当前实现既不重放，也不告诉客户端丢了多少条，更不会向发布者报错。

   </details>

下一章看客户端一侧怎样组织对连接的访问：[第 9 章：客户端为什么有三种形态](/mini-redis/clients.md)。
