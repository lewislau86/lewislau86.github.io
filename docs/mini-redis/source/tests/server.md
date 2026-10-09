---
editLink: false
---

# tests/server.rs：用原始 TCP 检查线上协议

<!-- analyzes: tests/server.rs -->

[打开对应源码](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/mini-redis/source/tests/server.rs) · [源码文章索引](/mini-redis/source/index.md) · [总目录](/mini-redis/index.md)

此文件绕过 Client，自行写 RESP 字节并 read_exact 比较响应。因此客户端和服务端即使共同犯了同一种编码错误，也不一定能通过这些固定字节断言。

## 它和哪些代码交互

```text
测试 → start_server → server::run
测试持有 TcpStream → 写手工 RESP → Handler / Command / Db
 ← 原始响应字节 → read_exact / timeout → assert_eq
```

## 基本读写同时检查缺失值与半关闭

<!-- source: tests/server.rs:43-57; comments omitted -->
```rust
.write_all(b"*2\r\n$3\r\nGET\r\n$5\r\nhello\r\n")
        .await
        .unwrap();

    stream.shutdown().await.unwrap();

    let mut response = [0; 11];
    stream.read_exact(&mut response).await.unwrap();
    assert_eq!(b"$5\r\nworld\r\n", &response);

    assert_eq!(0, stream.read(&mut response).await.unwrap());
}
```

前面先验证缺失键的 $-1 与 SET 的 +OK，最后发送 GET 后 shutdown 写半边，仍继续读 world 响应，并断言最终 EOF。关闭发送方向不等于丢弃整个 socket；服务器可以处理已收到的数据，再观察到输入结束。

## 七个测试串起哪些模块

| 测试 | 主要验证对象 |
| --- | --- |
| key_value_get_set | GET/SET 响应、写半关闭后继续读取与 EOF |
| key_value_timeout | 带 EX 的写入与推进时间后的缺失响应 |
| pub_sub | 无接收者返回 0，有订阅时计数和推送，频道隔离 |
| manage_subscription | 增加、移除及取消全部频道的确认 |
| send_error_unknown_command | 未知命令 Error 帧 |
| send_error_get_set_after_subscribe | 订阅模式拒绝普通 GET/SET |
| send_error_publish_after_subscribe | 订阅模式拒绝 PUBLISH |

Pub/Sub 用有上限的等待检查没有多余消息，但这只能说明该时间窗口内的观察。固定长度 read_exact 便于断言已知响应，若被测服务没有返回预期字节，缺少外层超时的读取也可能一直等。

## 虚拟时间测试的意图与已知执行结果

key_value_timeout 调 pause，再 SET EX 1，读到值后 advance 一秒，期待 Null。虚拟时间让计时器可控，但测试同时使用真实 TCP，后台清理任务是否已经运行仍涉及调度。

2026-10-08 的实际执行中，这条测试未结束，单独运行也在外部 20 秒上限被终止；当时没有确定根因。本轮只分析文档，未重新诊断，不能把“测试想验证过期”写成“这项测试已通过”。完整边界见[验证记录](/mini-redis/validation.md)。

## 运行与新增断言的方向

现有可用分组命令是 `cargo test --locked --test server -- --skip key_value_timeout`；这会明确排除已知未完成场景，不构成全套测试通过。测试启动服务绑定端口 0，spawn 后不保存可等待的服务句柄，因此它也不是优雅停机完成性的专门验证。

修改服务时，可按调用链选择断言：命令格式改动看线上字节，Db 改动看覆盖和跨连接可见性，订阅改动看确认与推送交错，退出改动则需要增加受控停止并等待所有任务的场景。

## 读完后沿哪里继续

[src/server.rs](/mini-redis/source/src/server.md) → [src/cmd/mod.rs](/mini-redis/source/src/cmd/mod.md) → [src/db.rs](/mini-redis/source/src/db.md) → [src/cmd/subscribe.rs](/mini-redis/source/src/cmd/subscribe.md) → [tests/client.rs](/mini-redis/source/tests/client.md)。

跨文件串读：[第 10 章：停机与测试](/mini-redis/10-shutdown-and-tests.md)。
