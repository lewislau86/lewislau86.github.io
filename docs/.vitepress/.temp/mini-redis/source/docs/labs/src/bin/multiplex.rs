//! 对应第 09 章：多个调用者通过队列共享一个 Client。
use bytes::Bytes;
use mini_redis::{BufferedClient, Client};
use mini_redis_reading_labs::Server;
use std::net::SocketAddr;
use tokio::time::{timeout, Duration};

async fn scenario(addr: SocketAddr) -> mini_redis::Result<()> {
    let client = Client::connect(addr).await?;
    let buffered = BufferedClient::buffer(client);
    let mut tasks = Vec::new();
    for i in 0..8 {
        let mut handle = buffered.clone();
        tasks.push(tokio::spawn(async move {
            let key = format!("worker:{i}");
            let value = Bytes::from(format!("value:{i}"));
            handle.set(&key, value.clone()).await?;
            assert_eq!(handle.get(&key).await?, Some(value));
            Ok::<(), mini_redis::Error>(())
        }));
    }
    for task in tasks {
        task.await??;
    }
    // 所有 Sender 释放后，后台 run 的 recv 将得到 None。
    drop(buffered);
    Ok(())
}

#[tokio::main]
async fn main() -> mini_redis::Result<()> {
    let server = Server::start().await?;
    let result = timeout(Duration::from_secs(10), scenario(server.addr)).await;
    let shutdown = server.stop().await;
    result??;
    shutdown?;
    println!("multiplex OK：8 个调用任务共享一个连接，完成 16 次命令；受控停机完成");
    Ok(())
}
