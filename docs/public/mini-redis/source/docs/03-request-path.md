# 03 沿着 SET/GET 走一遍

[上一章](02-rust-foundations.md) · [目录](README.md) · [下一章](04-resp-and-connection.md)

第 01 章已经通过自己的 hello_tokio 客户端读回 `course`，第 02 章也解释了值的移动与借用。现在跟踪同一行 `client.set("course", "rust".into()).await?`，进入它背后的实现。先不钻进每个协议字节，重点观察各层接收什么、返回什么、谁持有数据。

## 发命令之前，Client 已经拥有什么

[Client::connect](../src/clients/client.rs) 先等待 `TcpStream::connect(addr)`，再把得到的 socket 移入 `Connection::new(socket)`，最后返回 `Client { connection }`。至此已经有一条 TCP 连接以及配套缓冲区，尚未写入任何业务键值。

```text
地址 → TcpStream → Connection（socket + 读写缓冲）→ Client
```

Client 是当前进程内管理连接的对象，不是远端数据库的副本，也不是另一个 runtime。第 01 章创建的客户端与服务端分别由各自进程里的 runtime 驱动，通过 TCP 交换数据。下一步的 `set` 才把业务意图发送过去。

## 客户端把意图变成命令

在 [Client::set](../src/clients/client.rs) 中，客户端调用 `Set::new(key, value, None)`。`None` 表示不设 TTL，再交给内部 `set_cmd`。

[Set::new](../src/cmd/set.rs) 的 `key: impl ToString` 表示：接受任意实现 `ToString` trait 的具体类型。trait 描述一组能力，泛型约束规定输入需要哪些能力。这里调用 `key.to_string()` 得到自己的 String，所以调用者传进来的临时借用不会被存进 Set。

`impl ToString` 用在参数中可以理解为一个匿名泛型参数。`Client::connect<T: ToSocketAddrs>(addr: T)` 则把泛型命名为 T，让签名明确写出约束。两者都不是“任何类型都能传”。

`"rust".into()` 利用 `Into` 转换到目标类型 `Bytes`，目标由 `set` 的参数类型推断。遇到推断不清时可以写清楚 `Bytes::from_static(b"rust")`。`Into` 不是任意强制类型转换，它需要对应的 trait 实现。

## 命令被消费，变成 Frame

`Set::into_frame(self)` 消费命令，把字段移动进数组帧。对我们的例子，逻辑结构是：

```text
Frame::Array
  ├─ Frame::Bulk("set")
  ├─ Frame::Bulk("course")
  └─ Frame::Bulk("rust")
```

`Connection::write_frame(&frame)` 借用帧完成编码，最后 flush。接着 `Client::set_cmd` 读取一个响应，只接受内容为 `OK` 的 Simple 帧。

为什么必须等待响应？TCP 写成功只表示数据交给了相应网络栈，并不证明服务器已经执行命令；应用层响应才告诉调用者这次请求的结果。

## 服务端从 Frame 恢复业务含义

在 [Handler::run](../src/server.rs) 中找到这三步：

```rust
// 源码关键调用，frame 来自 connection.read_frame().await。
let cmd = Command::from_frame(frame)?;
cmd.apply(&self.db, &mut self.connection, &mut self.shutdown)
    .await?;
```

[Command::from_frame](../src/cmd/mod.rs) 先用 `Parse::new(frame)` 取得数组的 `IntoIter<Frame>`。`into_iter()` 消费容器，逐项交出其中元素的所有权；`iter()` 产生共享引用；`iter_mut()` 产生可变引用。这不是三种随意替换的写法。

解析器读取第一项作为命令名、转成小写，然后分发到 `Set::parse_frames`。后者依次取出 key、value，按需读取 `EX` 秒或 `PX` 毫秒。最后 `parse.finish()` 保证没有多余参数。

`Frame` 只知道“数组里有几个字符串”，`Command` 才知道“第三项是要存储的值”。这样把传输格式与业务语义分开，才能让同一套网络层服务不同命令。

## 真正修改数据的地方

`Set::apply(self, db: &Db, dst: &mut Connection)` 核心代码：

```rust
db.set(self.key, self.value, self.expire);
let response = Frame::Simple("OK".to_string());
dst.write_frame(&response).await?;
Ok(())
```

字段移动进数据库，不必让命令继续存在。`Db::set` 是同步函数：持锁更新内存后返回。写响应才需要 `.await`。因此共享状态锁并不会被这个函数一直带到网络等待期间。

调用链可以从头重述为：

```text
Client::set → Set::new → Set::into_frame
→ 客户端 Connection::write_frame → TCP
→ 服务端 Connection::read_frame → Command::from_frame
→ Set::parse_frames → Set::apply → Db::set
→ Frame::Simple("OK") → TCP → Client::set_cmd
```

GET 的方向相同，但 `Db::get` 返回 `Option<Bytes>`。有值时 `Get::apply` 构造 Bulk，无值时构造 Null；客户端再把它翻译回 `Some(bytes)` 或 `None`。

## 读懂 Result，才读懂失败路径

[lib.rs](../src/lib.rs) 定义：

```rust
pub type Error = Box<dyn std::error::Error + Send + Sync>;
pub type Result<T> = std::result::Result<T, Error>;
```

`type` 是别名，没有创建一种全新的包装类型。`Result<T, E>` 有 `Ok(T)` 和 `Err(E)` 两个分支；`Box` 持有堆上的值；`dyn Error` 是 trait 对象，允许用一个类型承载多种具体错误。`Send + Sync` 是跨线程传递/共享的能力约束，第 05 章再解释。

`?` 可近似展开为：

```rust
// 教学展开：实际转换由对应的 From 实现完成。
let cmd = match Command::from_frame(frame) {
    Ok(value) => value,
    Err(err) => return Err(err.into()),
};
```

它不是忽略异常，而是把失败向当前函数的调用者传播。`unwrap()` 则在 Err 或 None 时 panic，含义完全不同。正常协议输入的错误应读清它被传播到哪里，不能一律假设客户端会收到错误帧。

再把 `.await?` 拆开：调用 `Client::connect(...)` 得到 Future，`.await` 得到其完成结果 `Result<Client>`，`?` 再从成功结果里取出 Client；失败时则从当前函数返回 Err。`.await` 负责等待，`?` 负责错误传播，两者不是同一个操作。对于 GET，`?` 取出的是 `Option<Bytes>`，所以即使没有出错，仍然可能读到 None。

| 情况 | 本地行为 |
| --- | --- |
| GET 键不存在 | 正常返回 Null，客户端得到 `Ok(None)` |
| 未知命令 | `Unknown::apply` 写 Error 帧，普通请求循环可继续 |
| 已知命令缺参数/多参数 | 解析返回 Err，经 Handler 传播，连接任务结束 |
| 接收到半帧但连接仍开着 | 继续读，不当作业务失败 |
| 只有半帧时对端关闭 | Connection 返回错误 |

`Result<Option<Frame>>` 也就有三层含义：`Ok(Some(frame))` 收到一帧、`Ok(None)` 干净地读到 EOF、`Err(e)` 失败。不要把 `None` 和 `Err` 合并。

## 自己追一次 PING

打开 [ping.rs](../src/cmd/ping.rs)，依次找到 `new`、`parse_frames`、`apply`、`into_frame`，再回到 Client。为什么 PING 的 apply 没有 Db 参数？

<details>
<summary>参考答案</summary>

PING 的响应只依赖命令是否带消息，不读取或修改共享数据库。参数列表本身就表达了依赖关系：需要连接写回响应，不需要数据库。命令枚举仍用统一分发入口把它接入请求循环。

</details>
