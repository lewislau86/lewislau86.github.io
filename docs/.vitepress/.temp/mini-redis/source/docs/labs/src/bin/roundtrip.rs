//! 对应第 03、04、07、08、10 章；全程自建临时服务。
use bytes::Bytes;
use mini_redis::{Client, Connection, Frame};
use mini_redis_reading_labs::Server;
use std::net::SocketAddr;
use tokio::io::AsyncWriteExt;
use tokio::net::TcpStream;
use tokio::time::{sleep, timeout, Duration};

async fn scenario(addr: SocketAddr) -> mini_redis::Result<()> {
    let mut client = Client::connect(addr).await?;
    assert_eq!(client.ping(None).await?, Bytes::from_static(b"PONG"));
    assert!(client.get("absent").await?.is_none());
    client.set("course", Bytes::from_static(b"rust")).await?;
    assert_eq!(
        client.get("course").await?,
        Some(Bytes::from_static(b"rust"))
    );

    // 普通 GET/SET 的值可以是非 UTF-8；不要据此推导订阅 API 也无损。
    let binary = Bytes::from_static(&[0, 255, 13, 10]);
    client.set("binary", binary.clone()).await?;
    assert_eq!(client.get("binary").await?, Some(binary));
    println!("SET/GET、缺失键、PING、二进制值：通过");

    client
        .set_expires(
            "short",
            Bytes::from_static(b"old"),
            Duration::from_millis(50),
        )
        .await?;
    // 轮询一个可观察后置条件，有两秒上界，不假设某个精确调度时刻。
    timeout(Duration::from_secs(2), async {
        loop {
            if client.get("short").await?.is_none() {
                break Ok::<(), mini_redis::Error>(());
            }
            sleep(Duration::from_millis(10)).await;
        }
    })
    .await??;
    client
        .set_expires(
            "replace",
            Bytes::from_static(b"old"),
            Duration::from_millis(50),
        )
        .await?;
    client.set("replace", Bytes::from_static(b"new")).await?;
    sleep(Duration::from_millis(120)).await;
    assert_eq!(
        client.get("replace").await?,
        Some(Bytes::from_static(b"new"))
    );
    println!("TTL 删除、覆盖后撤销旧 TTL：通过");

    let sub_client = Client::connect(addr).await?;
    // subscribe 返回时已经读取服务器的订阅确认。
    let mut subscriber = sub_client.subscribe(vec!["news".to_string()]).await?;
    assert_eq!(
        client.publish("news", Bytes::from_static(b"hello")).await?,
        1
    );
    let message = subscriber.next_message().await?.expect("message");
    assert_eq!(message.channel, "news");
    assert_eq!(message.content, Bytes::from_static(b"hello"));
    subscriber.unsubscribe(&[]).await?;
    assert_eq!(
        client.publish("news", Bytes::from_static(b"gone")).await?,
        0
    );
    drop(subscriber);
    println!("订阅确认、文本推送、退订：通过");

    // 两次写入不承诺两次底层 read；确定性的半帧检查见 frames 实验。
    let mut socket = TcpStream::connect(addr).await?;
    let set = b"*3\r\n$3\r\nSET\r\n$4\r\nwire\r\n$5\r\nsplit\r\n";
    socket.write_all(&set[..13]).await?;
    tokio::task::yield_now().await;
    socket.write_all(&set[13..]).await?;
    // 不等 SET 响应，继续发送 GET：服务端仍应顺序返回两个响应。
    socket
        .write_all(b"*2\r\n$3\r\nGET\r\n$4\r\nwire\r\n")
        .await?;
    let mut connection = Connection::new(socket);
    assert_eq!(connection.read_frame().await?.expect("SET response"), "OK");
    match connection.read_frame().await? {
        Some(Frame::Bulk(value)) => assert_eq!(value, Bytes::from_static(b"split")),
        other => panic!("unexpected response: {:?}", other),
    }
    drop(connection);
    drop(client);
    println!("拆开发送、连续请求与顺序响应：通过");
    Ok(())
}

#[tokio::main]
async fn main() -> mini_redis::Result<()> {
    let server = Server::start().await?;
    let result = timeout(Duration::from_secs(10), scenario(server.addr)).await;
    let shutdown = server.stop().await;
    result??;
    shutdown?;
    println!("roundtrip OK：受控停机完成");
    Ok(())
}
