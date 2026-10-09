---
editLink: false
---

# 08 发布订阅为什么改变连接状态

[上一章](/mini-redis/07-expiration.md) · [目录](/mini-redis/index.md) · [下一章](/mini-redis/09-clients.md)

GET 是客户端先问、服务器再答。订阅新闻频道后，客户端可能很久不发请求，服务器却需要在别人发布消息时主动推送。这就不再是简单的“一次请求对应一次普通响应”。

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

最初 SUBSCRIBE 还会逐频道确认 `['subscribe', channel, 当前订阅数]`。UNSUBSCRIBE 回 `['unsubscribe', channel, 剩余订阅数]`。这些是数组帧，末尾计数是 Integer，不是文本数字。

`self.channels.drain(..)` 一边交出待订阅的 String，一边将列表清空，因此下一轮不会把老的待办再做一遍。新增 SUBSCRIBE 会把名字追加到待办列表，下一轮再建立流。

在当前实现里，订阅后的连接只处理 SUBSCRIBE 和 UNSUBSCRIBE；其他命令交给 Unknown 返回错误。即使所有频道都退订了，代码也没有从内部循环跳回普通 Handler 模式。不要把它写成“退订到零自动恢复普通客户端”。真正 Redis 的订阅规则还区分协议版本，见[官方 Pub/Sub 文档](https://redis.io/docs/latest/develop/pubsub/)。

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
