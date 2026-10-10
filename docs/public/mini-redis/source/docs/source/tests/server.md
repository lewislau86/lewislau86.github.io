# tests/server.rs：用原始 TCP 检查线上协议

<!-- analyzes: tests/server.rs -->

[打开对应源码](../../../tests/server.rs) · [源码文章索引](../README.md) · [总目录](../../README.md)

此文件绕过 Client，多数测试自行写 RESP 字节并 read_exact 比较响应；TTL 场景发送原始 SET 请求，随后用 Connection 读取完整帧。因此客户端和服务端即使共同犯了同一种编码错误，也不一定能通过这些固定字节断言。

## 它和哪些代码交互

```text
测试 → start_server → server::run
测试持有 TcpStream → 写手工 RESP → Handler / Command / Db
 ← 原始响应字节 → read_exact / timeout → assert_eq
```

## 基本读写同时检查缺失值与半关闭

<!-- source: tests/server.rs:41-55; comments included -->
```rust
.write_all(b"*2\r\n$3\r\nGET\r\n$5\r\nhello\r\n")
        .await
        .unwrap();

    // 仅关闭写方向，仍允许从同一 socket 读取服务端响应。
    stream.shutdown().await.unwrap();

    // 读取 Bulk world，即使客户端已不再发送新请求。
    let mut response = [0; 11];
    stream.read_exact(&mut response).await.unwrap();
    assert_eq!(b"$5\r\nworld\r\n", &response);

    // AsyncRead 返回 0 表示 EOF；这里直接读 socket，不是 Connection 的 Option 返回值。
    assert_eq!(0, stream.read(&mut response).await.unwrap());
}
```

前面先验证缺失键的 $-1 与 SET 的 +OK，最后发送 GET 后 shutdown 写半边，仍继续读 world 响应，并断言最终 EOF。关闭发送方向不等于丢弃整个 socket；服务器可以处理已收到的数据，再观察到输入结束。

## 七个测试串起哪些模块

| 测试 | 主要验证对象 |
| --- | --- |
| key_value_get_set | GET/SET 响应、写半关闭后继续读取与 EOF |
| key_value_timeout | 真实时间下的 SET EX 与有总上限的删除验证 |
| pub_sub | 无接收者返回 0，有订阅时计数和推送，频道隔离 |
| manage_subscription | 增加、移除及取消全部频道的确认 |
| send_error_unknown_command | 未知命令 Error 帧 |
| send_error_get_set_after_subscribe | 订阅模式拒绝普通 GET/SET |
| send_error_publish_after_subscribe | 订阅模式拒绝 PUBLISH |

Pub/Sub 用有上限的等待检查没有多余消息，但这只能说明该时间窗口内的观察。固定长度 read_exact 便于断言已知响应，若被测服务没有返回预期字节，缺少外层超时的读取也可能一直等。

## TTL 测试为何改用完整帧

旧测试在第一次 GET 等待期间，暂停的 Tokio 时钟自动前进到 1.001 秒。服务器已回复 5 字节的 Null，测试却还在等 world 的 11 字节，所以挂起而不是断言失败。2026-10-10 已捕获具体字节并修复，详见 [第 13 章](../../13-ttl-test-debugging.md)。

现在 key_value_timeout 不暂停时钟，保留原始 SET EX 请求，用 Connection::read_frame 识别 OK/Bulk/Null。GET 返回 world 就继续轮询，Null 表示清理完成，其他帧立即报告实际值。整个网络场景有 5 秒真实时间上限，随后发送 oneshot 停止信号，并在 1 秒内等待服务器退出。

精确过期边界转由 db.rs 的两个无网络单元测试验证；网络测试不假设第一次 GET 必定发生在一秒内。过早删除和后台不工作仍有独立测试检测，未通过放宽时间来掩盖。

## 运行与新增断言的方向

执行 `cargo test --locked` 即可运行完整测试，无需跳过 key_value_timeout。TTL 测试显式持有停止 Sender 和服务 JoinHandle；其他原测试仍使用端口 0 加 Ctrl+C 的辅助函数，不应把其中的基础字节断言当作优雅停机验证。

修改服务时，可按调用链选择断言：命令格式改动看线上字节，Db 改动看覆盖和跨连接可见性，订阅改动看确认与推送交错，退出改动则需要增加受控停止并等待所有任务的场景。

## 这里的 Rust 写法：虚拟时间与真实 I/O 是两个推进条件

tokio::time::advance 推进 runtime 的时钟，TCP 读写依然需要实际 I/O 就绪与任务调度。read_exact 的完成条件是收齐目标长度，不是时钟已经到点。本次修复将时间边界与 TCP 往返分开验证，并以完整帧和等待上限让意外响应可诊断。

需要拆开语法时，接着读 [Rust 阅读说明的对应小节](../../rust-reading-guide.md#tasks)。

## 读完后沿哪里继续

[src/server.rs](../src/server.md) → [src/cmd/mod.rs](../src/cmd/mod.md) → [src/db.rs](../src/db.md) → [src/cmd/subscribe.rs](../src/cmd/subscribe.md) → [tests/client.rs](client.md)。

跨文件串读：[第 10 章：停机与测试](../../10-shutdown-and-tests.md)。
