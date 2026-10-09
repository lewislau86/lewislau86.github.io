//! 最小客户端示例：连接已有服务，写 hello=world，再读取 hello。
//! 这里不启动服务；先在另一终端执行 cargo run --bin mini-redis-server，
//! 再执行 cargo run --example hello_world。默认连接本机 6379。

#![warn(rust_2018_idioms)]

use mini_redis::{clients::Client, Result};

#[tokio::main]
pub async fn main() -> Result<()> {
    // 等待建连；Client 需要 mut，后续 set/get 都通过 &mut self 操作同一条连接。
    let mut client = Client::connect("127.0.0.1:6379").await?;

    // 目标参数类型是 Bytes，因此 .into() 将字符串转换为 Bytes。
    client.set("hello", "world".into()).await?;

    // GET 在 SET 成功返回后才执行；下方 is_some 只检查有值，没有断言值一定等于 world。
    let result = client.get("hello").await?;

    println!("got value from the server; success={:?}", result.is_some());

    Ok(())
}
