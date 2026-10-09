---
editLink: false
---

# 08 发布订阅为什么改变连接状态

[上一章](/mini-redis/07-expiration.md) · [目录](/mini-redis/index.md) · [下一章](/mini-redis/09-clients.md)

GET 是客户端先问、服务器再答。订阅新闻频道后，客户端可能很久不发请求，服务器却需要在别人发布消息时主动推送。这就不再是简单的“一次请求对应一次普通响应”。

## 先把两条连接与一个内部通道分开

```text
订阅客户端 Client::subscribe → TCP S → Handler S::run
    → Command::apply → Subscribe::apply（在这里长期等待）
        → subscribe_to_channel → Db::subscribe → Receiver
        → StreamMap.next → 写 message 帧 → TCP S → Subscriber::next_message
                                            ↑
发布客户端 Client::publish → TCP P → Handler P::run
    → Publish::apply → Db::publish → broadcast Sender.send
    → 写 Integer 接收者数 → TCP P → Client::publish 返回
```

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

Occupied/Vacant 让“找到已有频道或插入新频道”在一次 entry 操作里表达。这里的 `Entry` 是导入的 `std::collections::hash_map::Entry`，不是存储值的自定义 Entry；阅读局部 `use` 能避免同名混淆。

每个频道有一个有界 broadcast 通道。每次 subscribe 返回自己的 Receiver；发布者通过 Sender 发送，接收者各自推进读取进度。没有活跃接收者时，本地 publish 返回 0；返回接收者数量不意味着这些接收者已经成功消费消息。

## Subscribe::apply 接管连接

[subscribe.rs](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/mini-redis/source/src/cmd/subscribe.rs) 建立 `StreamMap<String, Messages>`，把多个频道的消息源合并在同一个连接任务里。它循环等待三类事件：

```text
某个频道有消息 ─→ 写 ["message", channel, content]
客户端又发命令 ─→ 更新订阅集合或返回错误
收到停机通知   ─→ 返回，释放订阅与连接
```

将上面的三类事件对应到 [Subscribe::apply](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/mini-redis/source/src/cmd/subscribe.rs) 的实际循环，省略注释如下：

<!-- source: src/cmd/subscribe.rs:115-154; comments omitted -->
```rust
let mut subscriptions = StreamMap::new();

    loop {
        for channel_name in self.channels.drain(..) {
            subscribe_to_channel(channel_name, &mut subscriptions, db, dst).await?;
        }

        select! {
            Some((channel_name, msg)) = subscriptions.next() => {
                dst.write_frame(&make_message_frame(channel_name, msg)).await?;
            }
            res = dst.read_frame() => {
                let frame = match res? {
                    Some(frame) => frame,
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

调用它的外层 Handler 正停在 `cmd.apply(...).await`，因此外层 read_frame 暂时不会再执行；客户端发来的后续命令由这里的 dst.read_frame 接手。函数里没有“订阅数为零则 return”的分支，所以不能从退订计数为零推断回到普通请求模式。

`self.channels` 是尚待建立的订阅，`subscriptions` 是已经在监听的集合，二者职责不同。handle_command 收到新 SUBSCRIBE 时只追加待办，下一轮 drain 才调用 subscribe_to_channel；收到 UNSUBSCRIBE 则移除已有流并发送确认。

进入 [subscribe_to_channel](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/mini-redis/source/src/cmd/subscribe.rs) 看资源交接：

<!-- source: src/cmd/subscribe.rs:176-197; comments omitted -->
```rust
let mut rx = db.subscribe(channel_name.clone());

let rx = Box::pin(async_stream::stream! {
    loop {
        match rx.recv().await {
            Ok(msg) => yield msg,
            Err(broadcast::error::RecvError::Lagged(_)) => {}
            Err(_) => break,
        }
    }
});

subscriptions.insert(channel_name.clone(), rx);

let response = make_subscribe_frame(channel_name, subscriptions.len());
dst.write_frame(&response).await?;

Ok(())
```

Db 创建/复用频道并返回 Receiver；这里将 Receiver 移进流，流放入当前连接自己的 StreamMap，然后写订阅确认。因而确认到达客户端前，服务端已经建立接收关系。移除 StreamMap 中的流会释放对应 Receiver，但不会顺便删除 Db.pub_sub 中的 Sender 表项。


最初 SUBSCRIBE 还会逐频道确认 `['subscribe', channel, 当前订阅数]`。UNSUBSCRIBE 回 `['unsubscribe', channel, 剩余订阅数]`。这些是数组帧，末尾计数是 Integer，不是文本数字。

`self.channels.drain(..)` 一边交出待订阅的 String，一边将列表清空，因此下一轮不会把老的待办再做一遍。新增 SUBSCRIBE 会把名字追加到待办列表，下一轮再建立流。

在当前实现里，订阅后的连接只处理 SUBSCRIBE 和 UNSUBSCRIBE；其他命令交给 Unknown 返回错误。即使所有频道都退订了，代码也没有从内部循环跳回普通 Handler 模式。不要把它写成“退订到零自动恢复普通客户端”。真正 Redis 的订阅规则还区分协议版本，见[官方 Pub/Sub 文档](https://redis.io/docs/latest/develop/pubsub/)。

## Publish 的返回值在哪结束，推送又在哪继续

[Publish::apply](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/mini-redis/source/src/cmd/publish.rs) 接受的 dst 属于发布连接：

<!-- source: src/cmd/publish.rs:67-87; comments omitted -->
```rust
pub(crate) async fn apply(self, db: &Db, dst: &mut Connection) -> crate::Result<()> {
    let num_subscribers = db.publish(&self.channel, self.message);

    let response = Frame::Integer(num_subscribers as u64);

    dst.write_frame(&response).await?;

    Ok(())
}
```

它调用的 [Db::publish](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/mini-redis/source/src/db.rs) 只访问内部频道表：

<!-- source: src/db.rs:256-269; comments omitted -->
```rust
pub(crate) fn publish(&self, key: &str, value: Bytes) -> usize {
    let state = self.shared.state.lock().unwrap();

    state
        .pub_sub
        .get(key)
        .map(|tx| tx.send(value).unwrap_or(0))
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

这里移动外层 Pin/Box 句柄，并不等于移动堆上已固定的流。Pin 也不是“线程锁”，不负责并发互斥。你暂时不需要手写 unsafe 投影，只要理解为什么组合流需要这一层包装。

`async_stream::stream!` 把 `rx.recv().await` 的循环包装为流；`yield msg` 每次产出一条消息。Future 通常完成一次，Stream 可以多次产出。`StreamExt` 扩展 trait 提供 `.next()` 这样的便利方法，因此 `use` 一个 trait 有时是为了让方法调用可用。

## 慢订阅者不是可靠队列

每个 broadcast 通道容量为 1024。接收者跟不上时，旧消息会被覆盖，`recv` 返回 `Lagged`。当前源码对这个分支直接跳过，再继续接收；既没有重放，也没有向客户端汇报缺了多少条。

因此不能把这一机制拿来推导“消息至少送达一次”。网络中断、进程退出或消费落后都可能使消息丢失。Redis Pub/Sub 同样不提供持久重放语义；需要消费组、确认和历史记录时，应进一步学习 Streams 等机制，而不是把 Pub/Sub 当持久任务队列。

还有一个本地限制：[Subscriber::next_message](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/mini-redis/source/src/clients/client.rs) 通过 `content.to_string()` 再构造 Bytes。非 UTF-8 的 Bulk 会走展示字符串路径，不能据此宣称高级订阅 API 任意二进制往返无损。配套实验使用文本消息；底层帧保存 Bytes 与高级 API 处理 Bytes 是两个不同的验证点。

## 亲手收一条消息

保持第 01 章的服务运行，终端 B：

```sh
cargo run --locked --bin mini-redis-cli -- --port 16379 subscribe news
```

终端 C：

```sh
cargo run --locked --bin mini-redis-cli -- --port 16379 publish news hello
```

终端 B 应打印频道及 `hello` 内容。先让订阅命令完成再发布，避免消息在订阅建立之前被发走；可自动复现的版本见 [roundtrip 实验](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/mini-redis/source/docs/labs/src/bin/roundtrip.rs)，它等待 subscribe API 成功返回后才发布。

为什么不能在正在等待订阅消息的同一 Client 上直接调用 GET？

<details>
<summary>参考答案</summary>

线上随时可能出现主动推送，不能再按“下一帧必然是刚才 GET 的响应”解释数据。服务端已进入订阅循环，客户端 API 也通过消费 Client、返回 Subscriber 表达状态变化。普通查询应使用另一个连接。

</details>
