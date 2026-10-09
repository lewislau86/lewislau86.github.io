---
editLink: false
---

# src/clients/buffered_client.rs：用消息队列串行共享 Client

<!-- analyzes: src/clients/buffered_client.rs -->

[打开对应源码](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/mini-redis/source/src/clients/buffered_client.rs) · [源码文章索引](/mini-redis/source/index.md) · [总目录](/mini-redis/index.md)

BufferedClient 让多个任务克隆一个发送句柄，把请求交给唯一拥有 Client 的后台任务。这里的 buffered 指排队，不是建立很多连接，也不代表同时发送多条请求。

## 它和哪些代码交互

```text
调用任务 A/B → BufferedClient 克隆句柄
 → mpsc 队列（容量 32）→ run 独占 Client → TCP
 ← 每请求独立 oneshot ← 操作结果
```

## 消息同时携带工作与回信地址

<!-- source: src/clients/buffered_client.rs:9-43; comments omitted -->
```rust
#[derive(Debug)]
enum Command {
    Get(String),
    Set(String, Bytes),
}

type Message = (Command, oneshot::Sender<Result<Option<Bytes>>>);

async fn run(mut client: Client, mut rx: Receiver<Message>) {
    while let Some((cmd, tx)) = rx.recv().await {
        let response = match cmd {
            Command::Get(key) => client.get(&key).await,
            Command::Set(key, value) => client.set(&key, value).await.map(|_| None),
        };

        let _ = tx.send(response);
    }
}
```

Command 只支持 Get/Set，与服务端 Command 是两个类型。Message 中的 oneshot Sender 是此次请求的回复地址。run 每次完整 await 一个 Client 操作，再处理下一项，因此响应不会被另一个调用者读走；Set 的 unit 被统一映射成 None，以复用回复类型。

## buffer 创建唯一消费者

<!-- source: src/clients/buffered_client.rs:67-77; comments omitted -->
```rust
pub fn buffer(client: Client) -> BufferedClient {
    let (tx, rx) = channel(32);

    tokio::spawn(async move { run(client, rx).await });

    BufferedClient { tx }
}
```

Client 的所有权移动进 spawn 的任务，调用者只拿到 mpsc Sender。克隆 BufferedClient 只克隆队列入口。32 是尚未消费的消息容量，不是连接数，也不是任务总数上限；队列满时 send().await 等待，形成背压。

## GET 在两次等待之间跨越任务边界

<!-- source: src/clients/buffered_client.rs:83-98; comments omitted -->
```rust
pub async fn get(&mut self, key: &str) -> Result<Option<Bytes>> {
    let get = Command::Get(key.into());

    let (tx, rx) = oneshot::channel();

    self.tx.send((get, tx)).await?;

    match rx.await {
        Ok(res) => res,
        Err(err) => Err(err.into()),
    }
}
```

第一次等待把工作交给队列，第二次等待对应的 oneshot 结果。外层错误可能来自通道关闭，内层错误来自 Client 网络操作。set 使用同样路径，最后把统一的可选值结果转换为 unit。

## 取消和关闭会发生什么

调用者放弃等待，不会撤销已经入队的 SET。后台可能完成写入，再发现 oneshot 接收者消失；当前忽略发送回复失败。所有 mpsc Sender 释放后，接收端处理完剩余消息才得到 None，循环退出并释放 Client。

Client 操作失败会作为一次回复送回，但 run 不因此立即退出，也不重建连接。增加自动重连、超时或 pipelining 都需要重新定义失败请求和响应对应关系。tests/buffered_client.rs 的测试名包含 pool，但实现依然是一条连接的队列包装。

## 读完后沿哪里继续

[src/clients/client.rs](/mini-redis/source/src/clients/client.md) → [tests/buffered_client.rs](/mini-redis/source/tests/buffered_client.md) → [src/clients/mod.rs](/mini-redis/source/src/clients/mod.md)。

跨文件串读：[第 09 章：三种客户端](/mini-redis/09-clients.md)。
