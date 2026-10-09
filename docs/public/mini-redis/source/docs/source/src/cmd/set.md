# src/cmd/set.rs：解析可选 TTL，先写入再确认

<!-- analyzes: src/cmd/set.rs -->

[打开对应源码](../../../../src/cmd/set.rs) · [源码文章索引](../../README.md) · [总目录](../../../README.md)

Set 持有 key、Bytes 值和可选 Duration。它连接了客户端参数、RESP 编码、服务端参数解析以及数据库更新，是最适合练习 Option、所有权和错误传播的文件。

## 它和哪些代码交互

```text
Client::set / set_expires → Set::new → into_frame → 网络
Command::from_frame → Set::parse_frames → Command::Set
Command::apply → Set::apply → Db::set → Simple OK → 网络
```

## 必需参数与可选参数有不同错误含义

<!-- source: src/cmd/set.rs:80-121; comments omitted -->
```rust
pub(crate) fn parse_frames(parse: &mut Parse) -> crate::Result<Set> {
    use ParseError::EndOfStream;

    let key = parse.next_string()?;

    let value = parse.next_bytes()?;

    let mut expire = None;

    match parse.next_string() {
        Ok(s) if s.to_uppercase() == "EX" => {
            let secs = parse.next_int()?;
            expire = Some(Duration::from_secs(secs));
        }
        Ok(s) if s.to_uppercase() == "PX" => {
            let ms = parse.next_int()?;
            expire = Some(Duration::from_millis(ms));
        }
        Ok(_) => return Err("currently `SET` only supports the expiration option".into()),
        Err(EndOfStream) => {}
        Err(err) => return Err(err.into()),
    }

    Ok(Set { key, value, expire })
}
```

key 必须可转换为 UTF-8 String，value 通过 next_bytes 保留字节。前两项缺失立即失败；第三项缺失则表示没有 TTL。EX/PX 后的整数是必需项，分别转为秒或毫秒；其他选项被拒绝。Command::from_frame 最后还会检查是否有剩余参数。

这里只实现无条件写入和可选过期，不支持完整 Redis 的 NX/XX 等选项。Duration 是相对时长，绝对到期 Instant 在 Db::set 中生成。

## 写库和写回响应不是一个事务

<!-- source: src/cmd/set.rs:128-138; comments omitted -->
```rust
pub(crate) async fn apply(self, db: &Db, dst: &mut Connection) -> crate::Result<()> {
    db.set(self.key, self.value, self.expire);

    let response = Frame::Simple("OK".to_string());
    debug!(?response);
    dst.write_frame(&response).await?;

    Ok(())
}
```

Set 被消费，key 与 value 移入 Db；数据库同步更新完成，才构造 OK 并 await 网络发送。此时若客户端断开，Db 中的值不会回滚。追踪副作用必须看这两个调用的顺序，不能仅从 Result<()> 推断失败时没有写入。

## 编码总是选择毫秒选项

<!-- source: src/cmd/set.rs:144-160; comments omitted -->
```rust
pub(crate) fn into_frame(self) -> Frame {
    let mut frame = Frame::array();
    frame.push_bulk(Bytes::from("set".as_bytes()));
    frame.push_bulk(Bytes::from(self.key.into_bytes()));
    frame.push_bulk(self.value);
    if let Some(ms) = self.expire {
        frame.push_bulk(Bytes::from("px".as_bytes()));
        frame.push_bulk(Bytes::from(ms.as_millis().to_string()));
    }
    frame
}
```

客户端没有过期时间时只写三个元素，有过期时追加 px 与毫秒文本。服务端同时接受 EX 和 PX，并不意味着客户端会保留调用者最初用的时间单位。小于一毫秒的 Duration 转换会丢失不足毫秒的部分；修改时间精度要连同这一边界一起考虑。

## 追踪覆盖行为要继续进入 Db

new 与 getters 建立/查询命令值，不涉及共享状态。Db::set 才负责覆盖旧值、删除旧过期索引、插入新索引及必要唤醒。不带 TTL 覆盖旧 TTL 键时也必须撤销原索引，否则后台可能误删新值。测试不能只验证一次 set 后 get，还应覆盖旧 TTL 被替换和取消。

## 读完后沿哪里继续

[src/clients/client.rs](../clients/client.md) → [src/parse.rs](../parse.md) → [src/cmd/mod.rs](mod.md) → [src/db.rs](../db.md)。

跨文件串读：[第 03 章：SET/GET 完整调用链](../../../03-request-path.md)。
