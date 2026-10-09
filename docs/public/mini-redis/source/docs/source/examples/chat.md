# examples/chat.rs：尚未实现的聊天入口

<!-- analyzes: examples/chat.rs -->

[打开对应源码](../../../examples/chat.rs) · [源码文章索引](../README.md) · [总目录](../../README.md)

这是一个占位文件，当前没有连接、订阅、输入处理或消息循环。为它建立独立文章，是为了明确目录中这个文件的真实完成状态。

## 它和哪些代码交互

```text
cargo run --example chat → Tokio main
 → unimplemented!() → panic
没有进入 Client / server / Db
```

## 四行代码的全部行为

<!-- source: examples/chat.rs:1-4; comments omitted -->
```rust
#[tokio::main]
async fn main() {
    unimplemented!();
}
```

#[tokio::main] 为异步入口建立执行环境，unimplemented! 宏运行时立即 panic。文件能够编译，不表示它提供了可运行的聊天功能；不要把它纳入成功的请求演示。本文未执行这条会 panic 的程序。

## 如果以后实现，应该与谁交互

可从 pub/sub 示例组合开始：一条普通 Client 连接发布，另一条 Subscriber 连接接收推送，另外处理用户输入与退出。需要两条连接，是因为此项目中的订阅模式不接受普通 PUBLISH；把一个 Subscriber 当成任意命令 Client 不成立。

这些只是后续设计方向，目前源码没有实现。真正动手前还要定义频道、用户名、消息编码、并发任务停止与错误传播，而不只是替换一行宏。

## 读完后沿哪里继续

[examples/pub.rs](pub.md) → [examples/sub.rs](sub.md) → [src/cmd/subscribe.rs](../src/cmd/subscribe.md)。

跨文件串读：[第 12 章：扩展练习](../../12-exercises-and-index.md)。
