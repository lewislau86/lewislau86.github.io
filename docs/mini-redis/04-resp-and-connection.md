---
editLink: false
---

# 04 TCP 字节如何变成帧

[上一章](/mini-redis/03-request-path.md) · [目录](/mini-redis/index.md) · [下一章](/mini-redis/05-tokio-server.md)

TCP 给应用的是有序字节流，不保留“这次 write 对应一次 read”的消息边界。一个 GET 可以分两次读到，两个 GET 也可以一次读到。服务端必须自己确定一条消息在哪里结束。

## 手工编码一个 GET

本项目围绕 RESP2 的一部分实现。`GET course` 的实际字节是：

```text
*2\r\n$3\r\nGET\r\n$6\r\ncourse\r\n
```

展开来看：

```text
*2\r\n       数组：2 个元素
$3\r\n       第 1 个元素有 3 字节
GET\r\n      第 1 个元素内容及尾部 CRLF
$6\r\n       第 2 个元素有 6 字节
course\r\n   第 2 个元素内容及尾部 CRLF
```

这里写出的 `\r\n` 是两个控制字节的可见表示。命令行传入的文本、内存中的 Frame、网络上的 RESP 字节，是三个层次的表示。

| 本地 Frame | 线上示例 | 说明 |
| --- | --- | --- |
| `Simple(String)` | `+OK\r\n` | 简单文本响应 |
| `Error(String)` | `-ERR unknown command 'x'\r\n` | 协议错误响应 |
| `Integer(u64)` | `:1\r\n` | 本地只使用无符号整数 |
| `Bulk(Bytes)` | `$4\r\nrust\r\n` | 按字节长度读取，可以包含 CRLF |
| `Null` | `$-1\r\n` | 空 Bulk，常用于不存在的 GET |
| `Array(Vec<Frame>)` | `*2\r\n...` | 元素数量在前，各元素自行编码 |

协议边界要看[官方 RESP 规范](https://redis.io/docs/latest/develop/reference/protocol-spec/)：RESP2 整数是有符号的，而本地是 u64；本地 Null 使用 `$-1\r\n`，不能替换成 RESP3 的 `_\r\n`；本地也没有覆盖 RESP2/RESP3 的全部类型。这些是教学实现的范围。

## Connection 把不完整留在缓冲区

[Connection](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/mini-redis/source/src/connection.rs) 持有两样东西：`BufWriter<TcpStream>` 和 `BytesMut`。前者批量写，后者缓存读到但还没有处理完的字节。初始 4 KiB 是预分配容量，不是接收上限。

`read_frame` 的循环按下列顺序工作：

1. 尝试从已有 buffer 中解析一帧。
2. 成功就返回这一帧，未消费的数据留给下次调用。
3. 若数据不够，`read_buf` 继续追加字节，然后回到第 1 步。
4. 若读到 0 字节，表示 EOF：buffer 为空是正常关闭，非空则是半帧断开。

用一个具体 buffer 来推演：

```text
第 1 次读取：*2\r\n$3\r\nGE
结果：Incomplete，原字节全部保留

第 2 次追加：T\r\n$6\r\ncourse\r\n*1\r\n$4\r\nPING\r\n
结果：第一个完整帧是 GET，消费 25 字节
余下：*1\r\n$4\r\nPING\r\n

下一次 read_frame：直接从余下 buffer 得到 PING，不必等新网络数据
```

一次返回一帧并不代表一次只接收了一帧；这是 API 的边界选择。

## check 与 parse 为什么分开

`Connection::parse_frame` 构造 `Cursor<&[u8]>`：Cursor 保存当前位置，底层切片仍借用原始 buffer。它先调用 `Frame::check`，成功后记录游标位置作为这一帧长度，再将游标归零、调用 `Frame::parse` 构建对象，最后 `buffer.advance(len)` 消费已处理部分。

`check` 避免在常见的半帧情况下反复分配整个 Frame 树；`parse` 才创建 String、Bytes、Vec。这不是“所有输入已经得到完整严格验证”的承诺：本地 Bulk 路径按长度跳过尾部两个字节，并没有逐字节核验它们一定是 CRLF。`Frame::parse` 的未知前缀分支还会 panic，因此实验也遵循先 check 再 parse 的调用约定。

读源码时同时记录设计意图与实际检查范围，比只读注释更可靠。给帧加大小、递归深度限制，校验完整的数字和 CRLF，可以作为后续练习；这里没有宣称协议解析器已经生产可用。

## 借用输入的一小段：生命周期

[frame.rs](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/mini-redis/source/src/frame.rs) 中最值得逐字读的签名是：

```rust
fn get_line<'a>(src: &mut Cursor<&'a [u8]>) -> Result<&'a [u8], Error>
```

它返回从输入字节中借来的一段切片。`'a` 表达返回引用依赖底层字节的有效期；它不是延长数据寿命的命令，也不要求所有变量实际同时销毁。

这里存在两层引用：外层 `&mut Cursor` 是为了更新游标，内层 `&'a [u8]` 指向被读取的数据。函数返回的切片依赖内层数据，不需要让游标的可变借用持续到切片最后一次使用。因此显式写出 `'a` 比简单套用“输入输出同寿命”更准确。

函数找到 CRLF 后，返回 `&src.get_ref()[start..i]`，不会复制内容。Simple 帧随后把这一段转成拥有的 String；Bulk 帧使用 `Bytes::copy_from_slice`，这里也发生了复制。数据库里的 `Bytes::clone` 便宜，不等于从 socket 到数据库全程零拷贝。

## 写回也有边界

`write_frame` 按类型写前缀、长度、正文与 CRLF，最后 flush 缓冲区。对于数组，它先写数组头，再依次调用 `write_value`。当前写入器的 `write_value` 遇到 Array 使用 `unreachable!()`，因此虽然解析器能递归解析数组，写入器并不支持嵌套数组。

源码注释用旧式概括说明异步递归困难。准确理解应是：直接递归 async fn 会造成无限大小的 Future，需要间接层（例如装箱）等处理；不是 Rust 永远不能实现异步递归。这份代码只是没有实现那条路径。

运行 [frames 实验](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/mini-redis/source/docs/labs/src/bin/frames.rs)：

```sh
cargo run --locked --manifest-path docs/labs/Cargo.toml --bin frames
```

它会检查每一个不完整 GET 前缀、完整 GET、Null 和连续两个帧。网络拆分与连续请求实验在 [roundtrip](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/mini-redis/source/docs/labs/src/bin/roundtrip.rs) 中。两次 `write_all` 不保证两次底层 read，因此网络实验只证明服务端处理拆开发送的请求成功；逐前缀实验直接验证解析器遇到半帧的行为。

为什么 Bulk 的正文不能简单按 CRLF 分割？

<details>
<summary>参考答案</summary>

正文可以包含任意二进制字节，包括 CRLF。必须先读取长度，再精确取出该数量的字节，随后处理正文后的终止符。`$0\r\n\r\n` 是存在但长度为零的值，`$-1\r\n` 才是 Null。

</details>
