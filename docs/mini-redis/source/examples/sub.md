---
editLink: false
---

# examples/sub.rs：建立订阅后接收一条消息

<!-- analyzes: examples/sub.rs -->

[打开对应源码](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/mini-redis/source/examples/sub.rs) · [源码文章索引](/mini-redis/source/index.md) · [总目录](/mini-redis/index.md)

本文件实际只订阅 foo，然后读取一次消息。顶部注释说订阅 foo 和 bar，与当前执行代码不一致；它也不是一个持续接收的聊天程序。

## 它和哪些代码交互

```text
sub main → Client::connect → subscribe([foo])
 → 等待订阅确认 → Subscriber → next_message
 ← message 帧 → Message → 打印 → 释放连接并退出
```

## Client 为什么没有声明 mut

<!-- source: examples/sub.rs:22-39; comments omitted -->
```rust
#[tokio::main]
pub async fn main() -> Result<()> {
    let client = Client::connect("127.0.0.1:6379").await?;

    let mut subscriber = client.subscribe(vec!["foo".into()]).await?;

    if let Some(msg) = subscriber.next_message().await? {
        println!(
            "got message from the channel: {}; message = {:?}",
            msg.channel, msg.content
        );
    }

    Ok(())
}
```

subscribe 消费 Client 的所有权，所以调用者不需要先声明 mut；返回的 Subscriber 才需要 mut，以便 next_message 可变借用。`if let Some` 处理 Ok(Some)，正常 EOF 的 Ok(None) 则直接跳过打印；Err 通过 `?` 提前返回。

## 确认、等待、退出各发生在哪里

subscribe 返回前，客户端已经消费 foo 的确认帧；此时发布者发来的 message 才由 next_message 读取。没有发布者时，这次读取可以一直等待。收到一条后没有 while 循环，main 返回并丢弃 Subscriber，其内部 Client/Connection 也随之释放，服务端最终观察到连接结束。

可在服务启动后运行 `cargo run --locked --example sub`，再由 pub 示例发送。本轮没有重跑；避免把展示的执行顺序误当作已自动验证的同步屏障。

## 从一次接收到持续接收

将 if let 改成 while let 可以持续读，CLI 的订阅分支已有类似形式；也可读 Subscriber::into_stream 的适配。对二进制消息的保真、交错确认和断线处理，仍应先分析 client.rs 与 subscribe.rs 的实现，再决定如何扩展。

## 读完后沿哪里继续

[examples/pub.rs](/mini-redis/source/examples/pub.md) → [src/clients/client.rs](/mini-redis/source/src/clients/client.md) → [src/cmd/subscribe.rs](/mini-redis/source/src/cmd/subscribe.md) → [src/bin/cli.rs](/mini-redis/source/src/bin/cli.md)。

跨文件串读：[第 08 章：发布订阅](/mini-redis/08-pubsub.md)。
