---
editLink: false
---

# examples/pub.rs：一次发布调用的应用入口

<!-- analyzes: examples/pub.rs -->

[打开对应源码](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/mini-redis/source/examples/pub.rs) · [源码文章索引](/mini-redis/source/index.md) · [总目录](/mini-redis/index.md)

此示例连接本地服务，向 foo 频道发布 bar，然后退出。它需要与 sub 示例配合，才能看到消息到达另一条连接。

## 它和哪些代码交互

```text
pub main → Client::connect → Client::publish(foo, bar)
 → Publish::apply → Db::publish → 已存在的订阅 Receiver
 ← 接收者数量（本例丢弃）→ main 返回
```

## main 没有保留发布计数

<!-- source: examples/pub.rs:9-18; comments included -->
```rust
#[tokio::main]
async fn main() -> Result<()> {
    // 发布者使用自己的 TCP 连接，通过服务器的频道表与订阅者通信。
    let mut client = Client::connect("127.0.0.1:6379").await?;

    // await? 检查调用成败，但本例丢弃成功返回的接收者数量；0 也会正常退出。
    client.publish("foo", "bar".into()).await?;

    Ok(())
}
```

publish 的 Result 被 `?` 检查，但成功值没有赋给变量。无订阅者时服务端返回 0，这个程序依然正常结束；退出成功只说明命令调用没有报错，不能证明 sub 收到了消息。

## 正确理解三个终端的先后关系

先运行默认端口服务，再运行 `cargo run --locked --example sub`，等订阅完成后运行 `cargo run --locked --example pub`。pub 和 sub 各自建立 TCP 连接，通过同一个服务的频道状态沟通，没有进程间直接函数调用。

先发布再订阅没有历史重放；发布内容不会变成可以用 GET foo 读到的值。若需要程序化地保证顺序，应等待 subscribe API 成功，再发起发布，不能仅用固定 sleep 推测订阅准备好了。本轮仅分析源码，未重新运行此示例。

## 适合从哪里扩展

想观察无人订阅，把返回数量保存并输出；想连续发布，在 main 加循环即可进入同一 Client 的顺序调用路径。可靠投递、重放与消费确认则超出这个示例和当前 broadcast 模型，需要另外设计协议与存储。

## 这里的 Rust 写法：分号会丢弃成功值，问号仍检查错误

publish(...).await? 先检查错误，再产生 u64 数量；后面的分号丢弃这个数量。因此无人订阅的 0 不会使程序失败。若想展示数量，需绑定该值再输出；不能从进程退出码推导实际接收人数。

需要拆开语法时，接着读 [Rust 阅读说明的对应小节](/mini-redis/rust-reading-guide.md#results)。

## 读完后沿哪里继续

[examples/sub.rs](/mini-redis/source/examples/sub.md) → [src/clients/client.rs](/mini-redis/source/src/clients/client.md) → [src/cmd/publish.rs](/mini-redis/source/src/cmd/publish.md) → [src/db.rs](/mini-redis/source/src/db.md)。

跨文件串读：[第 08 章：发布订阅](/mini-redis/08-pubsub.md)。
