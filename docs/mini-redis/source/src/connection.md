---
editLink: false
---

# src/connection.rs：TCP 字节流与完整 Frame 之间的边界

<!-- analyzes: src/connection.rs -->

[打开对应源码](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/mini-redis/source/src/connection.rs) · [源码文章索引](/mini-redis/source/index.md) · [总目录](/mini-redis/index.md)

Connection 同时被客户端与服务端使用。它拥有 socket、写缓冲和读缓冲，负责消息边界，不知道某个 Bulk 是键还是值，也不会决定重试一条写命令。

## 它和哪些代码交互

```text
服务端 Handler / Subscribe ─┐
客户端 read_response / next_message ─┴→ read_frame → parse_frame → Frame::check/parse
各命令客户端/服务端 apply → write_frame → write_value/write_decimal → flush
```

## new 创建的资源归谁所有

new 消费 TcpStream，包装为 BufWriter，并创建初始容量 4 KiB 的 BytesMut。容量不是最大输入大小；后续 read_buf 可继续增加内容。这个对象归某个 Client 或 Handler，连接之间不会共享读缓冲。

## read_frame 与 parse_frame 的 None 不同

<!-- source: src/connection.rs:56-81; comments omitted -->
```rust
pub async fn read_frame(&mut self) -> crate::Result<Option<Frame>> {
    loop {
        if let Some(frame) = self.parse_frame()? {
            return Ok(Some(frame));
        }

        if 0 == self.stream.read_buf(&mut self.buffer).await? {
            if self.buffer.is_empty() {
                return Ok(None);
            } else {
                return Err("connection reset by peer".into());
            }
        }
    }
}
```

parse_frame 返回 None 仅表示当前 buffer 不够，read_frame 继续追加；read_frame 自己返回 None 才表示无残余字节的 EOF。若 EOF 时还有半帧，返回 Err。服务端把 EOF 当该连接正常结束，Client::read_response 则把等待响应期间的 EOF 当失败。

## 解析成功后再消费 buffer

<!-- source: src/connection.rs:87-146; comments omitted -->
```rust
fn parse_frame(&mut self) -> crate::Result<Option<Frame>> {
    use frame::Error::Incomplete;

    let mut buf = Cursor::new(&self.buffer[..]);

    match Frame::check(&mut buf) {
        Ok(_) => {
            let len = buf.position() as usize;

            buf.set_position(0);

            let frame = Frame::parse(&mut buf)?;

            self.buffer.advance(len);

            Ok(Some(frame))
        }
        Err(Incomplete) => Ok(None),
        Err(e) => Err(e.into()),
    }
}
```

check 在临时 Cursor 上走一遍确定长度；parse 创建拥有内容的 Frame；advance 仅消费这一帧。去掉 advance 会重复执行同一请求，清空全部 buffer 则会丢掉同次到达的后续请求。这个方法是 Frame 解析与连接状态之间的接缝。

## 写入方法的责任

write_frame 为 Array 写头部与逐项 value，其他帧直接写 value，最后 flush。write_value 处理 Simple/Error/Integer/Null/Bulk；遇到嵌套 Array 会 unreachable panic。write_decimal 用栈上字节数组和 Cursor 格式化数字，再写 CRLF。

flush 成功不是数据库耐久写入证明；写失败也可能已经送出部分帧。服务端 Set::apply 在写之前已修改内存，所以 Connection 的 Err 不能撤销业务效果。删除 flush 则可能让小响应留在缓冲中，调用者等不到下一步。

## 修改前需要守住的行为

半帧不能提前交付，连续帧不能吞掉，EOF 与空值不能混淆，接收缓冲与返回 Frame 的所有权不能互相悬空。适合对照 tests/server.rs 的原始字节断言和 docs/labs 的 frames/roundtrip 实验；这些不等于全面协议兼容测试。

## 读完后沿哪里继续

[src/frame.rs](/mini-redis/source/src/frame.md) → [src/server.rs](/mini-redis/source/src/server.md) → [src/clients/client.rs](/mini-redis/source/src/clients/client.md)。

跨文件串读：[第 04 章：帧边界](/mini-redis/04-resp-and-connection.md)。
