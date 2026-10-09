# src/cmd/ping.rs：用最小命令理解可选参数

<!-- analyzes: src/cmd/ping.rs -->

[打开对应源码](../../../../src/cmd/ping.rs) · [源码文章索引](../../README.md) · [总目录](../../../README.md)

PING 不访问数据库，很适合先理解一条命令如何完成解析、执行和编码。无参数返回 PONG，有参数则回显原字节。

## 它和哪些代码交互

```text
Client::ping → Ping::new → into_frame → 网络
Command::from_frame → Ping::parse_frames
Command::apply → Ping::apply → Connection::write_frame
```

## 参数结束在这里是合法状态

<!-- source: src/cmd/ping.rs:42-48; comments omitted -->
```rust
pub(crate) fn parse_frames(parse: &mut Parse) -> crate::Result<Ping> {
    match parse.next_bytes() {
        Ok(msg) => Ok(Ping::new(Some(msg))),
        Err(ParseError::EndOfStream) => Ok(Ping::default()),
        Err(e) => Err(e.into()),
    }
}
```

next_bytes 成功得到 Some，EndOfStream 对应默认值 None，其他解析错误仍然返回。derive(Default) 让 Option 字段默认 None，不代表所有错误都忽略。额外参数由外层 finish 拒绝。

## 返回帧类型随是否带参数变化

<!-- source: src/cmd/ping.rs:55-67; comments omitted -->
```rust
pub(crate) async fn apply(self, dst: &mut Connection) -> crate::Result<()> {
    let response = match self.msg {
        None => Frame::Simple("PONG".to_string()),
        Some(msg) => Frame::Bulk(msg),
    };

    debug!(?response);

    dst.write_frame(&response).await?;

    Ok(())
}
```

没有数据库锁，也没有共享状态副作用；只负责构造响应并发送。空 Bytes 是 Some(empty)，应回显空 Bulk，与完全没有参数的 Simple PONG 不同。

## into_frame 和影响边界

<!-- source: src/cmd/ping.rs:73-80; comments omitted -->
```rust
pub(crate) fn into_frame(self) -> Frame {
    let mut frame = Frame::array();
    frame.push_bulk(Bytes::from("ping".as_bytes()));
    if let Some(msg) = self.msg {
        frame.push_bulk(msg);
    }
    frame
}
```

数组先放 ping，再根据 Option 加消息。若把所有响应都改成 PONG，带消息回显的 Client 和 tests/client.rs 将不再符合约定。PING 成功只能证明本次连接和命令路径可用，不能证明过期、存储持久性或订阅功能正常。

## 读完后沿哪里继续

[src/clients/client.rs](../clients/client.md) → [src/cmd/mod.rs](mod.md) → [tests/client.rs](../../tests/client.md)。

跨文件串读：[第 03 章：SET/GET 完整调用链](../../../03-request-path.md)。
