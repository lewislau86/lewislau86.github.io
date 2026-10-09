# src/cmd/mod.rs：将协议帧分派到具体命令

<!-- analyzes: src/cmd/mod.rs -->

[打开对应源码](../../../../src/cmd/mod.rs) · [源码文章索引](../../README.md) · [总目录](../../../README.md)

Handler 只认识统一的 Command。此文件负责将 Frame 解析成具体命令，再将执行请求交给对应 apply；它是网络协议层与业务实现之间的分派点。

## 它和哪些代码交互

```text
Handler::run → Command::from_frame
 → Parse::new → 读命令名 → 各命令 parse_frames → finish
Handler::run → Command::apply → Get/Set/...::apply
订阅内部 handle_command 也会调用 from_frame
```

## from_frame 在两个阶段之间交接

<!-- source: src/cmd/mod.rs:37-63; comments included -->
```rust
pub fn from_frame(frame: Frame) -> crate::Result<Command> {
    // Parse::new 消费帧并持有数组迭代器；非 Array 立即返回错误。
    let mut parse = Parse::new(frame)?;

    // 先读取命令名并转小写，使 GET/get 等大小写写法走同一分支。
    let command_name = parse.next_string()?.to_lowercase();

    // 借用命令名的 str 切片匹配，再委托具体 parse_frames 读取剩余参数。
    let command = match &command_name[..] {
        "get" => Command::Get(Get::parse_frames(&mut parse)?),
        "publish" => Command::Publish(Publish::parse_frames(&mut parse)?),
        "set" => Command::Set(Set::parse_frames(&mut parse)?),
        "subscribe" => Command::Subscribe(Subscribe::parse_frames(&mut parse)?),
        "unsubscribe" => Command::Unsubscribe(Unsubscribe::parse_frames(&mut parse)?),
        "ping" => Command::Ping(Ping::parse_frames(&mut parse)?),
        _ => {
            // 未知名称提前返回，不检查未消费的参数；Unknown::apply 稍后负责写错误响应。
            return Ok(Command::Unknown(Unknown::new(command_name)));
        }
    };

    // 已知命令必须恰好消费参数；剩余项意味着不支持的格式。
    parse.finish()?;

    // 返回拥有各参数的命令值，交给 Handler 执行。
    Ok(command)
}
```

先把顶层 Frame 变成参数迭代器，再消费命令名并转小写。具体 parse_frames 收到的迭代器已经位于第一个参数。已知命令解析后统一调用 finish，拒绝多余参数；未知命令提前构造 Unknown 返回，不检查其剩余参数。

## apply 决定执行需要哪些上下文

<!-- source: src/cmd/mod.rs:66-84; comments included -->
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
        // 普通模式不接受 Unsubscribe；进入 Subscribe::apply 后由其内部循环处理取消。
        Unsubscribe(_) => Err("`Unsubscribe` is unsupported in this context".into()),
    }
}
```

Db 是跨连接共享状态，Connection 是当前连接，Shutdown 是当前连接的停止接收器。GET/SET 不使用 shutdown，Subscribe 会长时间持有连接控制权，因此拿到三者。普通 Handler 中收到 Unsubscribe 会 Err；订阅模式的取消由 subscribe.rs 内部处理。

## 错误不是都变成 Error 帧

Unknown::apply 主动写 Error 帧后返回 Ok，外层 Handler 可以继续读请求。已知命令缺参数、参数类型错误或普通模式的 Unsubscribe 则可能经 `?` 结束 Handler。区别在于是否存在明确的错误响应写入路径，不在于错误信息听起来是否严重。

get_name 为日志等调用提供统一名字，不负责解析。新增命令要同时补模块导出、枚举、from_frame、apply、get_name，再判断是否需要 Client/CLI 入口；只实现一个结构体还无法让网络请求到达它。

## 这里的 Rust 写法：同名 run 和同名 Command 怎样区分

模块路径和类型作用域决定一个名字指向谁；此处 Command 与 CLI 的参数枚举、BufferedClient 的内部队列枚举互不相同。`use Command::*` 将当前枚举变体引入局部作用域，所以 apply 的 match 可以写 Get(cmd) 等短名字。匹配后 cmd 是具体命令值，self 的所有权被消费。

需要拆开语法时，接着读 [Rust 阅读说明的对应小节](../../../rust-reading-guide.md#patterns)。

## 读完后沿哪里继续

[src/parse.rs](../parse.md) → [src/cmd/get.rs](get.md) → [src/cmd/set.rs](set.md) → [src/cmd/subscribe.rs](subscribe.md) → [src/cmd/unknown.rs](unknown.md) → [src/server.rs](../server.md)。

跨文件串读：[第 03 章：SET/GET 完整调用链](../../../03-request-path.md)。
