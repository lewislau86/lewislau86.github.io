//! 第 01 章：连接已经启动的服务器，亲手完成一次 SET/GET。
use mini_redis::{Client, Result};

#[tokio::main]
async fn main() -> Result<()> {
    // 默认对应第 01 章的独立实验端口，也可以从命令行指定地址。
    let addr = std::env::args()
        .nth(1)
        .unwrap_or_else(|| "127.0.0.1:16379".to_string());
    let mut client = Client::connect(&addr).await?;
    client.set("course", "rust".into()).await?;
    let value = client.get("course").await?;
    assert_eq!(value.as_deref(), Some(&b"rust"[..]));
    println!("course = {:?}", value);
    Ok(())
}
