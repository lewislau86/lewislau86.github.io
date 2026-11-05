//! 发布示例：向 foo 频道发送 bar。
//! 先运行 cargo run --bin mini-redis-server，再运行 cargo run --example sub，
//! 等订阅建立后运行 cargo run --example pub；先发布的历史消息不会重放给后加入者。

#![warn(rust_2018_idioms)]

use mini_redis::{clients::Client, Result};

#[tokio::main]
async fn main() -> Result<()> {
    // 发布者使用自己的 TCP 连接，通过服务器的频道表与订阅者通信。
    let mut client = Client::connect("127.0.0.1:6379").await?;

    // await? 检查调用成败，但本例丢弃成功返回的接收者数量；0 也会正常退出。
    client.publish("foo", "bar".into()).await?;

    Ok(())
}
