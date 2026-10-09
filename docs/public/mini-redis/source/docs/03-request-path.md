# 03 沿着 SET/GET 走一遍

[上一章](02-rust-foundations.md) · [目录](README.md) · [下一章](04-resp-and-connection.md)

这一章以 `client.set("course", "rust".into()).await?` 为主线。我们关心的不是单独背会 Set 的几个方法，而是跟踪一条请求：谁创建命令，谁把它发送出去，谁修改状态，又是谁最终向业务调用者报告成功或失败。

## 先固定这一次请求的位置

```text
客户端进程 / 当前调用任务
  hello_tokio::main 或 CLI main
    → Client::set → set_cmd → Set::into_frame
    → Connection::write_frame
                   │ TCP 字节流（不是 Rust 函数调用）
                   ▼
服务端进程 / 此连接的 Handler 任务
  Handler::run → Connection::read_frame
    → Command::from_frame → Parse → Set::parse_frames
    → Command::apply → Set::apply → Db::set
    → Connection::write_frame
                   │ 原 TCP 连接上的响应
                   ▼
客户端：Client::read_response → set_cmd 检查 OK → main 继续 GET
```

客户端的 Set 对象不会穿过网络：它被编码、消费；服务器从收到的字节创建另一个 Set 对象。两端可以复用同一库里的代码定义，但各自拥有独立的对象与内存。

本章源码节选直接取自链接文件，只去掉注释及不影响阅读的空行；片段需要放回所属 impl、模块与依赖中阅读，不是独立可运行程序。

## 发命令之前，Client 已经拥有什么

入口由 [hello_tokio 实验](labs/src/bin/hello_tokio.rs)或 [CLI main](../src/bin/cli.rs) 调用 [Client::connect](../src/clients/client.rs)。它先建立 TcpStream，再创建 Connection，最后把 Connection 放进 Client。成功返回意味着客户端有了 socket 和读写缓冲，不意味着服务器已写入任何键。

服务端接入这一 socket 的过程在[第 05 章](05-tokio-server.md)。先记住：普通请求由这个连接自己的 Handler 循环消费，多个 Handler 的 Db 句柄访问同一份共享数据。

## 第一站：Client::set 把调用意图交给 set_cmd

[Client::set](../src/clients/client.rs) 由业务代码调用，接收借用的 key 和拥有的 Bytes。它本身只是一个委托入口：

<!-- source: src/clients/client.rs:194-199; comments omitted -->
```rust
pub async fn set(&mut self, key: &str, value: Bytes) -> crate::Result<()> {
    self.set_cmd(Set::new(key, value, None)).await
}
```

`Set::new` 将 key 转成自己的 String，接管 value，并把 expire 设成 None；之后 `set_cmd` 统一承担普通 SET 与带 TTL 的 SET 的网络往返。`Client::set_expires` 也调用它，只是传入 Some(duration)。

[set_cmd](../src/clients/client.rs) 是客户端这一轮请求的控制点：

<!-- source: src/clients/client.rs:255-271; comments omitted -->
```rust
async fn set_cmd(&mut self, cmd: Set) -> crate::Result<()> {
    let frame = cmd.into_frame();

    debug!(request = ?frame);

    self.connection.write_frame(&frame).await?;

    match self.read_response().await? {
        Frame::Simple(response) if response == "OK" => Ok(()),
        frame => Err(frame.to_error()),
    }
}
```

从上往下看三条依赖：`into_frame` 必须先产生请求；`write_frame` 完成后才读取响应；响应必须是 Simple 且内容为 OK，才返回 `Ok(())` 给最初的 `Client::set` 调用者。

因此它需要 `&mut self`：发送与接收一起独占这个 Client 的连接状态。如果把发送与读取拆成任意两个任务，下一帧可能被错误的调用者拿走，返回值就无法再对应原请求。

`Set::new(key: impl ToString, ...)` 的 trait 约束表示 key 必须能转成字符串；`"rust".into()` 则按 set 的参数类型转换为 Bytes。转换承担了明确的数据所有权交接，不是把原来的引用自动延长寿命。

## 第二站：into_frame 决定线上参数排列

[Set::into_frame](../src/cmd/set.rs) 的调用者是上面的 set_cmd：

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

它消费 self，将 key、value 移入 Array。普通请求的结构是 `["set", "course", "rust"]`；带 TTL 的客户端路径统一追加 `"px"` 和毫秒文本。对应的 Connection 编码详见[第 04 章](04-resp-and-connection.md)。

这里改字段顺序会直接影响另一端 `Set::parse_frames` 读到的含义。修改命令格式时，必须同时追踪编码端和解析端，不能只确认这个方法返回了一个合法 Frame。

## 第三站：Handler 把完整帧交给命令分发器

服务端不是由 Db 主动取请求。入口在 [Handler::run](../src/server.rs)：`read_frame` 成功后，它调用 `Command::from_frame(frame)?`，再 await `cmd.apply(...)`。具体循环在[第 05 章](05-tokio-server.md)。

[Command::from_frame](../src/cmd/mod.rs) 的分发代码如下：

<!-- source: src/cmd/mod.rs:44-84; comments omitted -->
```rust
pub fn from_frame(frame: Frame) -> crate::Result<Command> {
    let mut parse = Parse::new(frame)?;

    let command_name = parse.next_string()?.to_lowercase();

    let command = match &command_name[..] {
        "get" => Command::Get(Get::parse_frames(&mut parse)?),
        "publish" => Command::Publish(Publish::parse_frames(&mut parse)?),
        "set" => Command::Set(Set::parse_frames(&mut parse)?),
        "subscribe" => Command::Subscribe(Subscribe::parse_frames(&mut parse)?),
        "unsubscribe" => Command::Unsubscribe(Unsubscribe::parse_frames(&mut parse)?),
        "ping" => Command::Ping(Ping::parse_frames(&mut parse)?),
        _ => {
            return Ok(Command::Unknown(Unknown::new(command_name)));
        }
    };

    parse.finish()?;

    Ok(command)
}
```

`Parse::new` 要求输入是 Array，取得数组的消费式迭代器。第一次 `next_string` 吃掉命令名，所以交给 `Set::parse_frames` 时，第一个剩余元素已经是 key。这层约定解释了为什么具体命令解析器不会再读取一次 "set"。

`parse.finish()` 检查具体命令是否把参数用完。Unknown 分支则提前返回，不走 finish。这导致“未知命令带参数”与“已知命令多参数”出现不同的后续行为，不能只把它们统称为解析失败。

[Set::parse_frames](../src/cmd/set.rs) 依次读取键、值和可选 TTL：

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

这里的 EndOfStream 要看发生位置：读取必需的 key/value 时缺数据，经 `?` 传播为错误；在可选 TTL 位置读不到参数，则表示“不设置过期”。如果已经读到 PX，却没读到数值，`next_int()?` 仍会报错。

跟一条具体输入走：`["set", "course", "rust", "PX", "1000"]` 经命令名分发后，剩余四项交给 Set；它产生 `Set { key, value, expire: Some(1 秒) }`，外层 finish 确认无剩余项。到这一步只是创建了指令，尚未修改数据库。

## 第四站：apply 才产生数据与网络效果

[Command::apply](../src/cmd/mod.rs) 的 `Set(cmd) => cmd.apply(db, dst).await` 将控制权交给 [Set::apply](../src/cmd/set.rs)：

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

传进来的 db 来自 Handler 的共享句柄，dst 就是该 Handler 正在处理的原连接。Db::set 同步修改内存，释放锁后返回；然后 Set::apply 写响应。`Ok(())` 表示这一层完成执行与写回，不是把 Frame 交给 Handler 再让它代写。

这两步没有事务回滚：如果 `db.set` 已成功，而 `write_frame` 失败，内存中的新值仍然存在。错误经 Command::apply 返回 Handler，再到连接任务的日志处理，结束的是这个连接；不会自动撤销数据，也不会作为 accept 循环的返回错误停止整个服务。

数据库如何同时更新 entries 与过期索引，在[第 06 章](06-shared-storage.md)接着追；是否唤醒后台清理，则在[第 07 章](07-expiration.md)接着追。

## 第五站：响应回到客户端，GET 使用另一条结果分支

`Client::read_response` 在本地 Connection::read_frame 之上多做一层语义解释：收到 Error 帧转换成 Err，收到普通帧交给命令专属方法判断，读到 EOF 则报告连接被服务器关闭。set_cmd 因而只能在读到正确 OK 后报告成功。

GET 走同一条通信路径，但 [Get::apply](../src/cmd/get.rs) 从数据库读出可选值：

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

Db 返回 Some 时，Get 构造 Bulk；返回 None 时构造 Null。两者都是正常响应，都会经同一个 dst 写回。[Client::get](../src/clients/client.rs) 再将响应恢复为调用者使用的 Option：

<!-- source: src/clients/client.rs:145-165; comments omitted -->
```rust
pub async fn get(&mut self, key: &str) -> crate::Result<Option<Bytes>> {
    let frame = Get::new(key).into_frame();

    debug!(request = ?frame);

    self.connection.write_frame(&frame).await?;

    match self.read_response().await? {
        Frame::Simple(value) => Ok(Some(value.into())),
        Frame::Bulk(value) => Ok(Some(value)),
        Frame::Null => Ok(None),
        frame => Err(frame.to_error()),
    }
}
```

读到 Null 是 `Ok(None)`，而断连是 Err。这样业务调用者才能区分“键不存在”与“根本没有取得查询结果”。GET 中 clone 出来的 Bytes 为什么可以在数据库解锁后仍然发送，见第 06 章。

## 把正常、失败与副作用一起对照

| 触发点 | 返回到谁 | 调用者随后做什么 | 用户与其他连接能观察到什么 |
| --- | --- | --- | --- |
| 正常 SET | set_cmd → Client::set → 业务代码 | 下一句 GET 可以继续 | 新值已写入共享状态；没有持久化保证 |
| GET 不存在 | Get::apply 写 Null → Client::get | 返回 Ok(None) | 正常缺失，不关闭连接 |
| 未知命令 | Unknown::apply 写 Error，服务端返回 Ok | Handler 继续读下一帧；Client 转换为 Err | 本次命令失败，连接可继续使用 |
| SET 缺参数/多参数 | parse_frames / finish → Handler 的 `?` | Handler 返回 Err，任务日志记录后结束 | 无本次写入；客户端通常观察到连接关闭而非 Error 帧 |
| SET 已写内存，回包失败 | Set::apply → Handler | 结束当前连接任务 | 新值仍可能被其他连接读到，原调用者不能确认结果 |

读 `?` 时应沿调用链向外读。`Client::connect(...).await?` 中，调用先产生 Future，await 得到 Result，`?` 才取出成功值或提前返回错误；GET 同理，但成功值是 Option。`?` 自身不写错误帧、不做回滚，也不会自动决定关闭哪一层资源。

## 怎样沿这一章查源码

建议按这个顺序打开文件，而不是把每个文件从头读到底：Client::set/set_cmd → Set::into_frame → Connection 的写/读 → Handler::run → Command::from_frame → Set::parse_frames → Command::apply → Set::apply → Db::set → Client::read_response。网络箭头两边是不同任务，沿链路时要主动切换视角。

现在自己追一次 [Ping::apply](../src/cmd/ping.rs)：它没有 Db 参数，会影响哪份数据？收到未知命令时，为什么 Handler 没有退出？

<details>
<summary>参考答案</summary>

PING 只根据输入构造响应，不访问共享数据库。未知命令被包装为 Unknown，apply 成功写 Error 帧后返回 Ok，所以 Handler 继续循环；协议里的 Error 帧和 Rust 返回值 Err 不是同一件事。写错误帧本身若失败，仍会通过 Err 结束连接任务。

</details>
