---
editLink: false
---

# src/bin/server.rs：把进程配置接到服务生命周期

<!-- analyzes: src/bin/server.rs -->

[打开对应源码](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/mini-redis/source/src/bin/server.rs) · [源码文章索引](/mini-redis/source/index.md) · [总目录](/mini-redis/index.md)

这是 mini-redis-server 可执行文件的入口。它负责启动环境和监听地址，实际 accept 与请求处理交给库中的 server.rs；两个文件名字相同，但处于不同层级。

## 它和哪些代码交互

```text
操作系统启动 binary → Tokio main
 → set_up_logging → Cli::parse → TcpListener::bind
 → server::run(listener, signal::ctrl_c()) → 返回后 main 结束
```

## 沿 main 看创建顺序

<!-- source: src/bin/server.rs:31-44; comments omitted -->
```rust
#[tokio::main]
pub async fn main() -> mini_redis::Result<()> {
    set_up_logging()?;

    let cli = Cli::parse();
    let port = cli.port.unwrap_or(DEFAULT_PORT);

    let listener = TcpListener::bind(&format!("127.0.0.1:{port}")).await?;

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

## 读完后沿哪里继续

[src/server.rs](/mini-redis/source/src/server.md) → [src/shutdown.rs](/mini-redis/source/src/shutdown.md)。

跨文件串读：[第 05 章：服务执行边界](/mini-redis/05-tokio-server.md)。
