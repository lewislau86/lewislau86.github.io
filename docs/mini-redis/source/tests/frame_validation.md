---
editLink: false
---

# tests/frame_validation.rs：用一个反例区分非法帧与半帧

<!-- analyzes: tests/frame_validation.rs -->

[打开对应源码](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/mini-redis/source/tests/frame_validation.rs) · [源码文章索引](/mini-redis/source/index.md) · [总目录](/mini-redis/index.md)

这是同步测试，不启动服务或 Tokio runtime。它直接构造字节切片的 Cursor，验证 Frame::check 对负 Bulk 长度的分类。

## 它和哪些代码交互

```text
普通 #[test] → Cursor<&[u8]> → Frame::check
合法 $-1 → Ok
非法 $-2 → Error::Other，不能是 Incomplete
```

## 完整测试的输入与判断

<!-- source: tests/frame_validation.rs:5-20; comments included -->
```rust
fn check_rejects_invalid_negative_bulk_length() {
    // 合法 Null Bulk：$-1\r\n；此处直接测 Frame::check，不建立 TCP 连接。
    let mut ok = Cursor::new(&b"$-1\r\n"[..]);
    assert!(Frame::check(&mut ok).is_ok());

    // 非法负长度必须返回 Other，不能误当 Incomplete 让 Connection 继续等待字节。
    let mut bad = Cursor::new(&b"$-2\r\n"[..]);
    let err = Frame::check(&mut bad).unwrap_err();

    match err {
        Error::Other(e) => {
            assert_eq!(e.to_string(), "protocol error; invalid frame format");
        }
        Error::Incomplete => panic!("expected protocol error, got incomplete"),
    }
}
```

$-1 是 Null 表示，$-2 不是有效长度。测试不仅要求后者失败，还要求错误属于 Other 且消息符合预期。若误分类为 Incomplete，Connection::read_frame 就可能继续等待一个永远补不完整的非法请求。

## 这里学到的 Rust 与覆盖边界

Cursor 持有字节切片借用，match 穷尽 Error 的两种分支，错误分支中的 panic 使测试失败。它没有调用 Frame::parse，也没有覆盖网络读取、Bulk 尾部校验、嵌套深度或最大长度；通过这一个反例不等于协议完全兼容。

可执行 `cargo test --locked --test frame_validation`。注释中文化后已复核此测试，执行记录在[验证记录](/mini-redis/validation.md)；这里的目标是说明为什么断言这个错误分类，以及它会影响哪个调用者。

## 这里的 Rust 写法：match 把错误类型也纳入断言

unwrap_err 要求 check 失败，之后 match 再要求它是 Other 而不是 Incomplete。b"..." 是字节串，Cursor 借用切片；测试没有把数据发送到网络。错误分类关系到调用方继续等字节还是结束连接，比只检查 is_err 更具体。

需要拆开语法时，接着读 [Rust 阅读说明的对应小节](/mini-redis/rust-reading-guide.md#patterns)。

## 读完后沿哪里继续

[src/frame.rs](/mini-redis/source/src/frame.md) → [src/connection.rs](/mini-redis/source/src/connection.md) → [tests/server.rs](/mini-redis/source/tests/server.md)。

跨文件串读：[第 04 章：帧边界与错误](/mini-redis/04-resp-and-connection.md)。
