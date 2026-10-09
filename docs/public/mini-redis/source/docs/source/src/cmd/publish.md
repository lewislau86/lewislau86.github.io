# src/cmd/publish.rs：将一次发布翻译为接收者数量

<!-- analyzes: src/cmd/publish.rs -->

[打开对应源码](../../../../src/cmd/publish.rs) · [源码文章索引](../../README.md) · [总目录](../../../README.md)

Publish 持有频道名和 Bytes 消息。它不把消息写入键值表；Db::publish 会向频道对应的 broadcast Sender 发送，订阅连接随后独立读取并写到各自 socket。

## 它和哪些代码交互

```text
Client::publish → Publish::into_frame → 网络
Command::from_frame → Publish::parse_frames
Command::apply → Publish::apply → Db::publish
  → broadcast → Subscribe 流 → 各订阅者连接
  → 数量 → Integer 响应 → 发布者 Client
```

## 参数表达频道与消息

<!-- source: src/cmd/publish.rs:31-39; comments included -->
```rust
pub(crate) fn parse_frames(parse: &mut Parse) -> crate::Result<Publish> {
    // 频道要求合法文本，读取失败则不继续发布。
    let channel = parse.next_string()?;

    // 消息用 next_bytes 读取，不强制 UTF-8。
    let message = parse.next_bytes()?;

    Ok(Publish { channel, message })
}
```

频道要求文本，消息保留 Bytes。new 是客户端入口，into_frame 生成 [publish, channel, message]；解析完成后外层 finish 拒绝额外项。

## 发布结果没有等待订阅者消费

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

Db::publish 同步调用 broadcast send，返回当前接收者数量或 0。这里将数量编码为 Integer 并发送给发布者，没有等待每个 Subscribe 的网络写入，更没有收到业务消费确认。返回 1 不能解释成一个业务系统已处理成功。

## 无订阅与慢订阅的区别

没有接收者时返回 0，这条消息没有持久化或重放路径。有接收者但其读取速度太慢时，容量有限的 broadcast 可能产生 Lagged；subscribe.rs 当前跳过该错误，继续收后续消息。改进可靠性需要协调队列策略与订阅协议，不能只修改这里的返回数字。

频道名可以和 SET 的 key 一样，但分别访问 pub_sub 和 entries，不共享值。服务端处于订阅模式的连接也不能通过普通分派执行 PUBLISH，需看 subscribe.rs 的 handle_command。

## 这里的 Rust 写法：一次函数调用可以同时借用字段和移出字段

apply 消费 self，所以可以借用频道名 `&self.channel`，同时把另一个字段 self.message 移交给 Db。字段互不重叠，借用检查器可以区分。数量转换为 Integer 后写给发布者，订阅者收到数据仍由其他任务处理；函数返回不是跨任务消费屏障。

需要拆开语法时，接着读 [Rust 阅读说明的对应小节](../../../rust-reading-guide.md#receivers)。

## 读完后沿哪里继续

[src/db.rs](../db.md) → [src/cmd/subscribe.rs](subscribe.md) → [src/clients/client.rs](../clients/client.md) → [examples/pub.rs](../../examples/pub.md)。

跨文件串读：[第 08 章：发布订阅](../../../08-pubsub.md)。
