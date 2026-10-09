---
editLink: false
---

# src/cmd/unknown.rs：把未知操作写成协议错误

<!-- analyzes: src/cmd/unknown.rs -->

[打开对应源码](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/mini-redis/source/src/cmd/unknown.rs) · [源码文章索引](/mini-redis/source/index.md) · [总目录](/mini-redis/index.md)

Unknown 保存无法执行的命令名，并在当前连接上写 Error 帧。它让“不认识命令”成为可返回给客户端的协议结果，而不是直接抛 Rust 错误。

## 它和哪些代码交互

```text
Command::from_frame 未知名称 → Unknown
或 Subscribe::handle_command 不支持的操作 → Unknown
 → Unknown::apply → Error Frame → write_frame → 客户端 Err
```

## 它不读取参数，也不访问 Db

new 保存 String，get_name 借用名字供统一日志等调用。未知命令在 Command::from_frame 中提前返回，所以其剩余参数不会经过已知命令的 finish 检查。订阅模式也会主动把当前不允许的命令转换成 Unknown，即使命令在普通模式有实现。

## Error 帧与 Rust Err 的差别

<!-- source: src/cmd/unknown.rs:28-36; comments omitted -->
```rust
#[instrument(skip(self, dst))]
pub(crate) async fn apply(self, dst: &mut Connection) -> crate::Result<()> {
    let response = Frame::Error(format!("ERR unknown command '{}'", self.command_name));

    debug!(?response);

    dst.write_frame(&response).await?;
    Ok(())
}
```

成功写出 Error 帧后，apply 本身返回 Ok。Handler 于是可以继续读取下一条命令；客户端 read_response 则将收到的 Frame::Error 转为自己的 Rust Err。两端的 Result 不是同一个对象，也不必具有相同状态。

只有 write_frame 失败时，这里的 `?` 才把错误传给服务端连接任务。若改成直接 return Err，客户端可能只看见 EOF，原先明确的错误消息就消失了。

## 如何验证影响

tests/server.rs 用原始 TcpStream 检查未知命令及订阅模式下 GET/SET/PUBLISH 的 Error 字节。这能验证线上约定，但不等于所有参数错误都采用同样策略；参数错误通常在到达此类型之前就已返回。

## 读完后沿哪里继续

[src/cmd/mod.rs](/mini-redis/source/src/cmd/mod.md) → [src/cmd/subscribe.rs](/mini-redis/source/src/cmd/subscribe.md) → [src/clients/client.rs](/mini-redis/source/src/clients/client.md) → [tests/server.rs](/mini-redis/source/tests/server.md)。

跨文件串读：[第 03 章：SET/GET 完整调用链](/mini-redis/03-request-path.md)。
