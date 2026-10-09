---
editLink: false
---

# src/cmd/mod.rs：将协议帧分派到具体命令

<!-- analyzes: src/cmd/mod.rs -->

[打开对应源码](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/mini-redis/source/src/cmd/mod.rs) · [源码文章索引](/mini-redis/source/index.md) · [总目录](/mini-redis/index.md)

Handler 只认识统一的 Command。此文件负责将 Frame 解析成具体命令，再将执行请求交给对应 apply；它是网络协议层与业务实现之间的分派点。

## 它和哪些代码交互

```text
Handler::run → Command::from_frame
 → Parse::new → 读命令名 → 各命令 parse_frames → finish
Handler::run → Command::apply → Get/Set/...::apply
订阅内部 handle_command 也会调用 from_frame
```

## from_frame 在两个阶段之间交接

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

先把顶层 Frame 变成参数迭代器，再消费命令名并转小写。具体 parse_frames 收到的迭代器已经位于第一个参数。已知命令解析后统一调用 finish，拒绝多余参数；未知命令提前构造 Unknown 返回，不检查其剩余参数。

## apply 决定执行需要哪些上下文

<!-- source: src/cmd/mod.rs:90-109; comments omitted -->
```rust
pub(crate) async fn apply(
    self,
    db: &Db,
    dst: &mut Connection,
    shutdown: &mut Shutdown,
) -> crate::Result<()> {
    use Command::*;

    match self {
        Get(cmd) => cmd.apply(db, dst).await,
        Publish(cmd) => cmd.apply(db, dst).await,
        Set(cmd) => cmd.apply(db, dst).await,
        Subscribe(cmd) => cmd.apply(db, dst, shutdown).await,
        Ping(cmd) => cmd.apply(dst).await,
        Unknown(cmd) => cmd.apply(dst).await,
        Unsubscribe(_) => Err("`Unsubscribe` is unsupported in this context".into()),
    }
}
```

Db 是跨连接共享状态，Connection 是当前连接，Shutdown 是当前连接的停止接收器。GET/SET 不使用 shutdown，Subscribe 会长时间持有连接控制权，因此拿到三者。普通 Handler 中收到 Unsubscribe 会 Err；订阅模式的取消由 subscribe.rs 内部处理。

## 错误不是都变成 Error 帧

Unknown::apply 主动写 Error 帧后返回 Ok，外层 Handler 可以继续读请求。已知命令缺参数、参数类型错误或普通模式的 Unsubscribe 则可能经 `?` 结束 Handler。区别在于是否存在明确的错误响应写入路径，不在于错误信息听起来是否严重。

get_name 为日志等调用提供统一名字，不负责解析。新增命令要同时补模块导出、枚举、from_frame、apply、get_name，再判断是否需要 Client/CLI 入口；只实现一个结构体还无法让网络请求到达它。

## 读完后沿哪里继续

[src/parse.rs](/mini-redis/source/src/parse.md) → [src/cmd/get.rs](/mini-redis/source/src/cmd/get.md) → [src/cmd/set.rs](/mini-redis/source/src/cmd/set.md) → [src/cmd/subscribe.rs](/mini-redis/source/src/cmd/subscribe.md) → [src/cmd/unknown.rs](/mini-redis/source/src/cmd/unknown.md) → [src/server.rs](/mini-redis/source/src/server.md)。

跨文件串读：[第 03 章：SET/GET 完整调用链](/mini-redis/03-request-path.md)。
