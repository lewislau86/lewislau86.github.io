# tests/client.rs：从公开 API 验证端到端返回值

<!-- analyzes: tests/client.rs -->

[打开对应源码](../../../tests/client.rs) · [源码文章索引](../README.md) · [总目录](../../README.md)

这个集成测试文件同时运行 Client 和 server，通过真实的本地 TCP 验证业务 API。它适合回答“调用者最终拿到什么”，而协议字节的精确断言主要在 tests/server.rs。

## 它和哪些代码交互

```text
每个 #[tokio::test] → start_server → 绑定端口 0 → spawn server::run
 → Client::connect(分配地址) → API 调用 → 断言
订阅测试 → 第二个 Client 发布 → Subscriber 接收
```

## SET/GET 用断言补全 hello_world

<!-- source: tests/client.rs:29-37; comments included -->
```rust
async fn key_value_get_set() {
    let (addr, _) = start_server().await;

    let mut client = Client::connect(addr).await.unwrap();
    client.set("hello", "world".into()).await.unwrap();

    let value = client.get("hello").await.unwrap().unwrap();
    assert_eq!(b"world", &value[..])
}
```

第一层 unwrap 取 Result，第二层 unwrap 要求 Option 是 Some，最后比较实际字节。与示例只检查 is_some 相比，这里对响应内容有明确约束。断言失败会使测试失败，不能当作生产错误处理方式照搬。

## 六个测试分别覆盖什么

| 测试 | 关键断言 |
| --- | --- |
| ping_pong_without_message | 无消息时返回 PONG |
| ping_pong_with_message | 中文消息按 UTF-8 字节回显 |
| key_value_get_set | 写 world 后读回同样字节 |
| receive_message_subscribed_channel | 单频道的名称与消息内容 |
| receive_message_multiple_subscribed_channels | 两个频道分别收到各自内容 |
| unsubscribes_from_channels | 空取消列表表示取消全部，本地列表长度归零 |

发布任务在 subscribe 返回后才创建，这个调用顺序保证先等确认再发布。取消全部的测试只检查客户端记录，不验证服务端是否恢复普通 GET/SET 模式。

## 临时服务的生命周期

<!-- source: tests/client.rs:103-110; comments included -->
```rust
async fn start_server() -> (SocketAddr, JoinHandle<()>) {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();

    let handle = tokio::spawn(async move { server::run(listener, tokio::signal::ctrl_c()).await });

    (addr, handle)
}
```

端口 0 由系统分配可用端口，避免多个测试争抢 6379。调用者丢弃 JoinHandle，测试没有发送专用停机信号或 await 服务退出；测试 runtime 结束会影响其任务生命周期，不能拿它证明优雅停机协议正确。

## 怎么运行与如何解释结果

可在仓库根目录执行 `cargo test --locked --test client`。注释中文化后已按分组复核；执行范围见[验证记录](../../validation.md)。

现有文本消息断言没有覆盖非 UTF-8 Pub/Sub，基本往返也未覆盖断线重连、重复频道、确认与推送交错或多调用者并发。读测试时把断言与缺失场景区分开，才能判断一个改动到底有没有证据支持。

## 这里的 Rust 写法：异步测试宏和两次 unwrap

tokio::test 建立测试 runtime；unwrap 在这里用于把不符合预期的结果变成测试失败。GET 的第一个 unwrap 检查 Result，第二个检查 Option 是否有值。测试可以选择 panic 表示失败，业务 API 通常应返回或处理错误，不能直接照搬所有 unwrap。

需要拆开语法时，接着读 [Rust 阅读说明的对应小节](../../rust-reading-guide.md#macros)。

## 读完后沿哪里继续

[src/clients/client.rs](../src/clients/client.md) → [tests/server.rs](server.md) → [examples/hello_world.rs](../examples/hello_world.md)。

跨文件串读：[第 10 章：测试与生命周期](../../10-shutdown-and-tests.md)。
