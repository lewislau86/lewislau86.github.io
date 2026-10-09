---
editLink: false
---

# 01 跑通第一条请求

[上一章：整体架构](/mini-redis/00-architecture.md) · [目录](/mini-redis/index.md) · [下一章：Rust 基础](/mini-redis/02-rust-foundations.md)

Rust 写法辅助阅读：[逐项拆解模块、类型与异步语法](/mini-redis/rust-reading-guide.md#modules)。遇到陌生写法时先读对应小节，再回到下面的调用链。

本章对应的独立源码文章：[src/bin/server.rs](/mini-redis/source/src/bin/server.md)、[src/bin/cli.rs](/mini-redis/source/src/bin/cli.md)、[examples/hello_world.rs](/mini-redis/source/examples/hello_world.md)。完整的一一对应关系见 [源码文章索引](/mini-redis/source/index.md)。

数据库在这里首先是一个持续运行的进程。客户端连上它，发送命令；进程修改内存，再返回结果。关闭客户端不会清空服务器的数据，关闭并重启这个服务器则会，因为 mini-redis 没有持久化。

## 启动两个角色

先在仓库根目录确认工具链：

```sh
rustc --version
cargo --version
cargo build --locked --bins
```

`rustc` 编译 Rust；Cargo 负责包、依赖、编译目标和测试。`Cargo.toml` 描述依赖约束，`Cargo.lock` 记录解析出的具体版本。`--locked` 要求 Cargo 不擅自更改锁文件。第一次构建可能需要下载依赖。

终端 A 启动服务：

```sh
RUST_LOG=debug cargo run --locked --bin mini-redis-server -- --port 16379
```

`--bin` 选择可执行文件，独立的 `--` 后面才是传给程序的参数。这里用 16379，避免与本机默认 6379 上的其他服务混淆。若该端口已被占用，选择另一个空闲端口，并同步修改客户端参数。

终端 B 依次运行：

```sh
cargo run --locked --bin mini-redis-cli -- --port 16379 ping
cargo run --locked --bin mini-redis-cli -- --port 16379 set course rust
cargo run --locked --bin mini-redis-cli -- --port 16379 get course
cargo run --locked --bin mini-redis-cli -- --port 16379 get missing
```

命令输出依次为 `"PONG"`、`OK`、`"rust"`、`(nil)`。Cargo 的编译提示不属于服务响应。这里 `(nil)` 表示键不存在；它不同于值为空字符串。

再设置一个短期值：

```sh
cargo run --locked --bin mini-redis-cli -- --port 16379 set temporary hello 1000
# 等待两秒后再执行下一行
cargo run --locked --bin mini-redis-cli -- --port 16379 get temporary
```

CLI 的最后一个位置参数 `1000` 表示毫秒。它不是原生 Redis CLI 的 `PX 1000` 写法；本项目 CLI 会替你构造协议参数。预期第二条命令返回 `(nil)`，过期任务的细节留到第 07 章。

在终端 A 按 Ctrl+C 停机。重启后再查 `course`，预期也是 `(nil)`，因为这一份数据库只存于进程内存。

## 从使用 CLI 走到自己写客户端

刚才的 CLI 已经帮我们完成了连接和请求。接下来把这几步写进自己的 Rust 程序，才能自然地进入源码阅读。[Hello Tokio 官方教程](https://tokio.rs/tokio/tutorial/hello-tokio)也以一个小客户端开始：建立连接、写一个值、再读回来。这里沿用本书的 `course/rust` 和端口 16379，直接调用本地库。

保持终端 A 的服务运行，在终端 B 执行：

```sh
cargo run --locked --manifest-path docs/labs/Cargo.toml --bin hello_tokio
```

这次执行的是我们自己的 [hello_tokio.rs](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/mini-redis/source/docs/labs/src/bin/hello_tokio.rs)。它不会自动启动服务，默认连接 `127.0.0.1:16379`；若你修改了服务器端口，可以在命令后追加 `-- 127.0.0.1:新端口`。核心逻辑如下，地址参数处理省略：

```rust
use mini_redis::{Client, Result};

#[tokio::main]
async fn main() -> Result<()> {
    let mut client = Client::connect("127.0.0.1:16379").await?;
    client.set("course", "rust".into()).await?;
    let value = client.get("course").await?;
    println!("course = {:?}", value);
    Ok(())
}
```

预期输出 `course = Some(b"rust")`。`Some` 表示有值，`b"rust"` 是字节内容的调试表示；它和 CLI 打印的 `"rust"` 来自同一份响应，只是展示形式不同。

先按执行顺序读，不必现在记住每个类型：

| 表达式 | 这一步拿到了什么 | 后面在哪里深入 |
| --- | --- | --- |
| `Client::connect(...).await?` | 连接成功后得到 Client；失败提前返回 | 第 03、05 章 |
| `let mut client` | 允许后续方法通过可变借用推进连接状态 | 第 02 章 |
| `"rust".into()` | 按 set 参数要求转换成 Bytes | 第 03 章 |
| `client.set(...).await?` | 等服务器确认本次写入 | 第 03 章 |
| `client.get(...).await?` | 取得可能存在的值 | 第 02、03 章 |
| `Ok(())` | main 成功结束 | 第 03 章 |

这三次 await 在当前程序中依次发生。GET 不会在 SET 完成前开始；异步不等于几行代码自动一起运行。如果当前没有其他就绪任务，等待网络期间也可以没有新的业务代码执行。第 05 章会用无网络的小实验，把“创建异步操作”和“实际执行”拆开观察。

## 让教程代码对应到这份仓库

官方网站与本地源码提供的接口有差别。不要只看包名和版本范围相似，就假设代码可以直接互换。

| 位置 | 连接接口 / 运行条件 |
| --- | --- |
| [官方 Hello Tokio](https://tokio.rs/tokio/tutorial/hello-tokio) | 页面示例为 `mini_redis::client::connect`，使用安装好的服务程序及 6379 |
| [本地 Client](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/mini-redis/source/src/clients/client.rs) | `mini_redis::clients::Client::connect`；lib.rs 也重导出为 `mini_redis::Client` |
| [本地 hello_world 示例](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/mini-redis/source/examples/hello_world.rs) | 使用 Client::connect，但写死 6379，打印 `success=true` |
| 本书 hello_tokio 实验 | 路径依赖当前源码，默认 16379，打印实际读取的值 |

因而，照本书操作时不需要再 `cargo install mini-redis`。`cargo run --example hello_world` 是另一个有效入口，但它不会连接这里的 16379；先读清地址，避免以为启动了一个服务就能运行所有客户端示例。

官方从 `cargo new` 开始搭项目。当前已有源码，我们把教学程序集中在 [docs/labs/Cargo.toml](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/mini-redis/source/docs/labs/Cargo.toml)，其依赖关键配置为：

```toml
[dependencies]
mini-redis = { path = "../.." }
tokio = { version = "=1.32.0", features = ["full"] }
```

路径相对于这份 Cargo.toml，`../..` 正好指回仓库根目录，因此调试的就是你正在读的源码。`--manifest-path` 告诉 Cargo 使用哪个包，`--bin hello_tokio` 选择 `src/bin/hello_tokio.rs`。独立锁文件让这个学习包的依赖解析可复核。

`features = ["full"]` 打开 Tokio 的一组编译期能力，方便教学使用网络、计时器和宏；它不会启动服务或改变端口。第 05 章再说明启用能力与创建 runtime 的区别。

如果遇到错误，先检查最靠近现象的一层：

| 现象 | 先检查什么 |
| --- | --- |
| 找不到 `mini_redis::client` | 是否直接复制了官方页面的 API；对照本地导出 |
| Connection refused | 服务是否仍在运行，客户端地址是否与监听地址一致 |
| Address already in use | 服务选用的端口是否已被其他进程占用 |
| 得到 `None` / `(nil)` | 是否查询了另一个键、连到另一个实例，或服务已重启/值已过期 |

## 先认清目录，再读入口

| 路径 | 职责 |
| --- | --- |
| [Cargo.toml](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/mini-redis/source/Cargo.toml) | 包名、依赖、两个 binary、可选 feature |
| [src/lib.rs](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/mini-redis/source/src/lib.rs) | 库入口，声明模块和公开 API |
| [src/bin/server.rs](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/mini-redis/source/src/bin/server.rs) | 服务器命令行入口，初始化日志与监听 |
| [src/bin/cli.rs](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/mini-redis/source/src/bin/cli.rs) | 客户端命令行入口 |
| [src/server.rs](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/mini-redis/source/src/server.rs) | 连接管理与请求循环 |
| [src/connection.rs](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/mini-redis/source/src/connection.rs) | TCP 与完整帧之间的转换 |
| [src/frame.rs](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/mini-redis/source/src/frame.rs) | RESP 帧的数据表示与解析 |
| [src/parse.rs](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/mini-redis/source/src/parse.rs) | 从帧数组逐项读取命令参数 |
| [src/cmd](https://github.com/lewislau86/lewislau86.github.io/tree/master/docs/public/mini-redis/source/src/cmd) | 每一种命令的解析和执行 |
| [src/db.rs](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/mini-redis/source/src/db.rs) | 内存状态、过期索引、发布订阅 |
| [src/clients](https://github.com/lewislau86/lewislau86.github.io/tree/master/docs/public/mini-redis/source/src/clients) | 三种客户端封装 |
| [tests](https://github.com/lewislau86/lewislau86.github.io/tree/master/docs/public/mini-redis/source/tests) | 从公开接口验证行为的集成测试 |

一个 package 可以同时包含 library crate 和 binary crate。这里库在代码里写作 `mini_redis`，Cargo 包名则是 `mini-redis`。文件夹本身不会自动把所有 `.rs` 编进库；`mod` 声明建立模块树。

例如 `lib.rs` 中：

```rust
mod connection;
pub use connection::Connection;
```

第一行声明内部模块，第二行把类型重新导出。所以外部调用者可以写 `mini_redis::Connection`，无需访问私有的 `connection` 模块。`pub` 表示公开，`pub(crate)` 表示仅当前 crate 内可见；`crate::` 从当前 crate 的根开始寻找名字。

## 拆开服务器入口

下面是 [server binary](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/mini-redis/source/src/bin/server.rs) 的关键步骤，省略日志与参数解析：

```rust
#[tokio::main]
pub async fn main() -> mini_redis::Result<()> {
    let listener = TcpListener::bind("127.0.0.1:16379").await?;
    server::run(listener, signal::ctrl_c()).await;
    Ok(())
}
```

这是解释执行顺序的节选，不是独立文件；完整入口还包含 `use`、CLI 和日志设置。

`fn` 定义函数，`->` 后面是返回类型；`()` 是 unit，表示没有有意义的返回数据。`Ok(())` 表示“成功完成”。末尾表达式没有分号时会成为函数返回值；加上分号就把它当成普通语句。

`#[tokio::main]` 是属性宏，它生成启动 Tokio runtime 的入口代码。`async` 函数给出一个可被驱动的异步计算，`.await` 等待结果，`?` 在失败时提前返回。你现在只需看懂顺序：创建监听 → 运行服务器并等待关闭 → 成功结束。第 03、05 章再拆开错误和异步机制。

`TcpListener` 是接入点；每次 `accept` 产生的 `TcpStream` 才代表一个客户端连接。不要把监听端口和已建立连接混为一谈。

## 一次小检查

为什么连续两次执行 CLI，第二次仍能读到第一次写入的值？

<details>
<summary>参考答案</summary>

两次 CLI 是不同进程，也分别建立连接，但它们访问同一个服务器进程。所有连接的 Handler 都持有同一个共享 Db 的句柄。值归服务器所有，不归某次 CLI 调用所有。

</details>

下一章先离开网络片刻，理解“归谁所有”在 Rust 中到底意味着什么。
