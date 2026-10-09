---
editLink: false
---

# tests/buffered_client.rs：验证队列包装后的基本读写

<!-- analyzes: tests/buffered_client.rs -->

[打开对应源码](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/mini-redis/source/tests/buffered_client.rs) · [源码文章索引](/mini-redis/source/index.md) · [总目录](/mini-redis/index.md)

唯一测试名叫 pool_key_value_get_set，但被测类型是 BufferedClient：单个后台任务独占一条 Client 连接。名字中的 pool 不代表实现了多连接池。

## 它和哪些代码交互

```text
测试 → start_server → Client::connect
 → BufferedClient::buffer → 后台 run
 → set 入队并等回复 → get 入队并等回复 → 比较字节
```

## 这个测试真正完成的路径

<!-- source: tests/buffered_client.rs:13-24; comments omitted -->
```rust
#[tokio::test]
async fn pool_key_value_get_set() {
    let (addr, _) = start_server().await;

    let client = Client::connect(addr).await.unwrap();
    let mut client = BufferedClient::buffer(client);

    client.set("hello", "world".into()).await.unwrap();

    let value = client.get("hello").await.unwrap().unwrap();
    assert_eq!(b"world", &value[..])
}
```

set/get 顺序 await，因此覆盖消息进入 mpsc、后台调用 Client、oneshot 返回以及实际服务器读写。第二次 unwrap 要求 GET 有值，字节断言验证内容。

## 它没有制造并发竞争

没有 clone BufferedClient，没有多个调用任务，也没有把 32 个队列槽位压满。测试通过说明基本包装路径可用，但不能证明队列满时的背压、取消调用者、全部发送端关闭或故障连接后的行为。第 09 章和 multiplex 实验另行讨论多调用者场景。

## 启动和退出的范围

<!-- source: tests/buffered_client.rs:26-33; comments omitted -->
```rust
async fn start_server() -> (SocketAddr, JoinHandle<()>) {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();

    let handle = tokio::spawn(async move { server::run(listener, tokio::signal::ctrl_c()).await });

    (addr, handle)
}
```

本地端口 0 避免固定端口冲突；返回的 JoinHandle 在测试中被忽略，没有显式等待 server 停机。这与 docs/labs 中发送专用停止信号并等待退出的实验不同。

可执行 `cargo test --locked --test buffered_client`。本文没有新增或运行测试，既有结果见[验证记录](/mini-redis/validation.md)。若未来把此实现改成真正的连接池，应新增连接分配与跨连接状态边界的验证，不能只沿用这个测试名作为依据。

## 读完后沿哪里继续

[src/clients/buffered_client.rs](/mini-redis/source/src/clients/buffered_client.md) → [src/clients/client.rs](/mini-redis/source/src/clients/client.md) → [tests/client.rs](/mini-redis/source/tests/client.md)。

跨文件串读：[第 09 章：多调用者共享连接](/mini-redis/09-clients.md)。
