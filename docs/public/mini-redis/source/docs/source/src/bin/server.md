# src/bin/server.rs：把进程配置接到服务生命周期

<!-- analyzes: src/bin/server.rs -->

[打开对应源码](../../../../src/bin/server.rs) · [源码文章索引](../../README.md) · [总目录](../../../README.md)

这是 mini-redis-server 可执行文件的入口。它负责启动环境和监听地址，实际 accept 与请求处理交给库中的 server.rs；两个文件名字相同，但处于不同层级。

## 它和哪些代码交互

```text
操作系统启动 binary → Tokio main
 → set_up_logging → Cli::parse → TcpListener::bind
 → server::run(listener, signal::ctrl_c()) → 返回后 main 结束
```

## 沿 main 看创建顺序

<!-- source: src/bin/server.rs:28-48; comments included -->
```rust
// 属性宏生成同步入口和 Tokio runtime，然后驱动下面的 async 函数体。
#[tokio::main]
pub async fn main() -> mini_redis::Result<()> {
    // ? 解开 Ok；Err 则转换为 main 的错误类型并提前返回。
    set_up_logging()?;

    // Parser 是 trait，derive(Parser) 生成实现；导入 trait 后可调用 parse。
    let cli = Cli::parse();
    // Option<u16>：Some 使用用户端口，None 使用默认值；这里不是会 panic 的 unwrap。
    let port = cli.port.unwrap_or(DEFAULT_PORT);

    // 绑定本机监听地址；await 等待绑定结果，? 在失败时提前返回 main。
    let listener = TcpListener::bind(&format!("127.0.0.1:{port}")).await?;

    // server 来自顶部 use mini_redis::server，并非指当前这个同名文件。
    // listener 被移动给库；ctrl_c() 返回等待信号的 Future，此处没有先等待 Ctrl+C。
    // run 内部并发等待接入与停止；它返回后 main 才继续执行 Ok(())。
    server::run(listener, signal::ctrl_c()).await;

    Ok(())
}
```

日志初始化先于网络监听；端口缺省时取 DEFAULT_PORT。地址绑定固定为 127.0.0.1，所以 --port 只改端口，不会自动开放其他网卡。bind 失败经 `?` 返回 main，服务处理循环尚未启动。

成功后把 listener 的所有权交给 server::run，并把 Ctrl+C Future 作为退出触发源传入。这个 main 没有自己 spawn 每个客户端，也没有持有键值 HashMap。

## 日志的两个编译分支

默认 set_up_logging 调 tracing_subscriber::fmt::try_init；启用 otel 时编译另一份同名函数，安装传播器、OTLP tracer 和 tracing 层。cfg 在编译时选路径，不是运行时检测是否有 Collector。本文分析默认运行路径，未部署或验证 OpenTelemetry 链路。

`server::run` 返回 `()`，库内处理接入错误并协调退出；这里不能仅凭 main 最后 Ok 就推导服务运行期间没有连接错误。错误信息也要看日志。

## 哪些修改会影响外部使用

修改 bind 地址会改变可连接范围；修改默认端口会影响不带 --port 的用户；把 stop Future 换成其他来源会改变退出触发方式。修改命令或协议应去 cmd/connection，而不是往 main 中继续堆业务。当前入口可由 cargo run --bin mini-redis-server 启动，笔记用 --port 16379 与默认实例区分。

## 这里的 Rust 写法：从 use 和属性宏读懂整个入口

`use mini_redis::{server, DEFAULT_PORT}` 引入库公开的模块与常量；server 不是由本文件的名字自动决定的。`#[tokio::main]` 生成 runtime 来驱动异步函数。`Cli::parse` 来自导入的 Parser trait 和 derive(Parser) 生成的实现。`Option<u16>::unwrap_or` 提供默认端口，`.await?` 先等待再传播错误，最后 `Ok(())` 表示成功且无额外返回值。`signal::ctrl_c()` 先产生 Future，真正等待发生在库的 select 中。

需要拆开语法时，接着读 [Rust 阅读说明的对应小节](../../../rust-reading-guide.md#modules)。

## 读完后沿哪里继续

[src/server.rs](../server.md) → [src/shutdown.rs](../shutdown.md)。

跨文件串读：[第 05 章：服务执行边界](../../../05-tokio-server.md)。
