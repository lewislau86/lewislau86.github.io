# src/cmd/unknown.rs：把未知操作写成协议错误

<!-- analyzes: src/cmd/unknown.rs -->

[打开对应源码](../../../../src/cmd/unknown.rs) · [源码文章索引](../../README.md) · [总目录](../../../README.md)

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

<!-- source: src/cmd/unknown.rs:26-34; comments included -->
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

## 这里的 Rust 写法：一个 Result 成功可以携带另一端的失败消息

服务端 apply 成功表示 Error 帧写出成功；客户端 read_response 再把这帧解释为 Err。这两个 Result 分属不同进程和函数，不是同一个返回值。format! 创建拥有的 String，into() 或 Frame::Error 保存它，临时命令名借用结束后响应仍能存活。

需要拆开语法时，接着读 [Rust 阅读说明的对应小节](../../../rust-reading-guide.md#results)。

## 读完后沿哪里继续

[src/cmd/mod.rs](mod.md) → [src/cmd/subscribe.rs](subscribe.md) → [src/clients/client.rs](../clients/client.md) → [tests/server.rs](../../tests/server.md)。

跨文件串读：[第 03 章：SET/GET 完整调用链](../../../03-request-path.md)。
