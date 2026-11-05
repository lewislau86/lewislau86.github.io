use mini_redis::{
    clients::{BufferedClient, Client},
    server,
};
use std::net::SocketAddr;
use tokio::net::TcpListener;
use tokio::task::JoinHandle;

/// 启动临时服务，建立 Client 并包装为 BufferedClient，顺序验证 SET/GET 的精确字节。
/// 测试名含 pool，但实现是一条连接的队列，不是连接池，也没有覆盖多任务并发。
#[tokio::test]
async fn pool_key_value_get_set() {
    let (addr, _) = start_server().await;

    let client = Client::connect(addr).await.unwrap();
    let mut client = BufferedClient::buffer(client);

    client.set("hello", "world".into()).await.unwrap();

    let value = client.get("hello").await.unwrap().unwrap();
    assert_eq!(b"world", &value[..])
}

async fn start_server() -> (SocketAddr, JoinHandle<()>) {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();

    let handle = tokio::spawn(async move { server::run(listener, tokio::signal::ctrl_c()).await });

    (addr, handle)
}
