//! 订阅示例：当前代码只订阅 foo，并读取一条消息后退出。
//! 先运行 cargo run --bin mini-redis-server，再运行 cargo run --example sub，
//! 等订阅建立后在另一终端运行 cargo run --example pub。

#![warn(rust_2018_idioms)]

use mini_redis::{clients::Client, Result};

#[tokio::main]
pub async fn main() -> Result<()> {
    // Client 不需要 mut，因为 subscribe 消费 self，而不是由此变量提供可变借用。
    let client = Client::connect("127.0.0.1:6379").await?;

    // 先等订阅确认，再得到可读取推送的 Subscriber；原 Client 已移动。
    let mut subscriber = client.subscribe(vec!["foo".into()]).await?;

    // if let 只读取一次；持续接收需要循环，EOF 的 None 会跳过打印。
    if let Some(msg) = subscriber.next_message().await? {
        println!(
            "got message from the channel: {}; message = {:?}",
            msg.channel, msg.content
        );
    }

    Ok(())
}
