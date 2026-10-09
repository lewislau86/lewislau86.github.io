---
editLink: false
---

# src/cmd/get.rs：从 Db 读取并生成响应

<!-- analyzes: src/cmd/get.rs -->

[打开对应源码](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/mini-redis/source/src/cmd/get.rs) · [源码文章索引](/mini-redis/source/index.md) · [总目录](/mini-redis/index.md)

Get 把一条 GET 请求表示为拥有 key 的值。它既供客户端构造请求，也供服务端解析和执行；两端共用结构定义，但不会共享一个 Rust 对象。

## 它和哪些代码交互

```text
Client::get → Get::new → into_frame → 网络
网络 → Command::from_frame → Get::parse_frames
 → Command::apply → Get::apply → Db::get
 → Bulk / Null → Connection::write_frame → Client::get
```

## 同一结构的两个入口

<!-- source: src/cmd/get.rs:50-57; comments omitted -->
```rust
pub(crate) fn parse_frames(parse: &mut Parse) -> crate::Result<Get> {
    let key = parse.next_string()?;

    Ok(Get { key })
}
```

客户端 new 接受 impl ToString 并保存 String；服务端 parse_frames 从 Parse 取一个文本 key 再构造 Get。key() 只借用内部 str，不复制。命令名已由 Command::from_frame 读掉，剩余参数检查也由它调用 finish 完成。

## 真正读取发生在 apply

<!-- source: src/cmd/get.rs:64-81; comments omitted -->
```rust
pub(crate) async fn apply(self, db: &Db, dst: &mut Connection) -> crate::Result<()> {
    let response = if let Some(value) = db.get(&self.key) {
        Frame::Bulk(value)
    } else {
        Frame::Null
    };

    debug!(?response);

    dst.write_frame(&response).await?;

    Ok(())
}
```

Db::get 同步取得 Option&lt;Bytes>。这里用 match 将业务结果翻译为协议结果：Some 是 Bulk，None 是 Null；随后 await 发送。这次等待发生在数据库锁释放之后，所以慢客户端不会让这里一直持有 Db 的互斥锁。

## 客户端方向是相反的转换

<!-- source: src/cmd/get.rs:87-92; comments omitted -->
```rust
pub(crate) fn into_frame(self) -> Frame {
    let mut frame = Frame::array();
    frame.push_bulk(Bytes::from("get".as_bytes()));
    frame.push_bulk(Bytes::from(self.key.into_bytes()));
    frame
}
```

into_frame 消费 Get，构造 [get, key] 数组；并没有访问 Db。区分“生成 GET 请求”和“执行 GET 请求”，才能理解为什么 Client 与服务端会引用同一个文件。

## 改变这里会影响什么

将缺失键改为 Error 会改变 Client::get 的 Option 语义；加入额外读取参数要同步修改 parse_frames/into_frame 与客户端 API。过期判断当前不在本文件，也不在 Db::get，而依靠后台清理；分析过期准确性必须继续读 db.rs。网络写失败仅终止此连接的操作，不会修改读到的值。

## 读完后沿哪里继续

[src/clients/client.rs](/mini-redis/source/src/clients/client.md) → [src/cmd/mod.rs](/mini-redis/source/src/cmd/mod.md) → [src/db.rs](/mini-redis/source/src/db.md) → [src/connection.rs](/mini-redis/source/src/connection.md)。

跨文件串读：[第 03 章：SET/GET 完整调用链](/mini-redis/03-request-path.md)。
