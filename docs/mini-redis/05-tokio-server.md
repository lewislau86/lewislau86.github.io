---
editLink: false
---

# 05 为什么服务器能同时服务多人

[上一章](/mini-redis/04-resp-and-connection.md) · [目录](/mini-redis/index.md) · [下一章](/mini-redis/06-shared-storage.md)

前面已经从客户端走完 SET/GET 的调用链，并看过 Connection 怎样处理字节。现在回到第 01 章留下的问题：代码中的 `.await` 究竟让谁等待，服务器又怎样在等待一个客户端时处理其他连接？先看一个不需要网络的实验，再进入服务端的任务循环。

## 先创建操作，再观察它何时开始

运行 [async_basics.rs](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/mini-redis/source/docs/labs/src/bin/async_basics.rs)：

```sh
cargo run --locked --manifest-path docs/labs/Cargo.toml --bin async_basics
```

预期输出顺序固定：

```text
两个 Future 已创建，函数体尚未执行
执行 SET
SET 完成后才开始等待第二个 Future
执行 GET
async_basics OK：创建、依次执行、丢弃未执行 Future
```

实验中的 stage 只是打印名称并等待一个短计时器，没有实际访问数据库。关键片段是：

```rust
let first = stage("SET");
let second = stage("GET");
println!("两个 Future 已创建，函数体尚未执行");
let first_result = first.await;
println!("{first_result} 完成后才开始等待第二个 Future");
let second_result = second.await;
```

虽然第二个 Future 很早就创建了，它的函数体仍要等到 `second.await` 才开始被驱动。这里两个操作顺序执行；在 SET 的计时器等待期间，GET 不会自行开始。实验还创建并立即丢弃一个未被轮询的 Future，其阶段名称不会打印出来。

这能帮助你发现一种常见疏漏：只写 `let operation = client.set(...);` 并没有完成 SET。对 `async fn` 而言，函数体是惰性执行的。这个结论不能扩展成“任何返回 Future 的普通函数都无副作用”，也不能套在已经 spawn 的任务上。

## async 函数给出可被暂停的计算

调用 `async fn` 会返回一个 Future；函数体需要被轮询才推进。Tokio runtime 负责调度任务和驱动 I/O、计时器。当 `.await` 的对象暂时无法完成时，当前任务可以返回 Pending，让执行线程去做其他工作；就绪后通过唤醒机制再次推进。

“轮询”不是应用代码不停重试 socket，而是执行器调用 Future 的 `poll`，判断当前能否继续；尚未完成时，等待就绪通知后再推进。Future 完成后给出 `Output`，例如 `Client::connect` 的 Output 是 `Result<Client>`。这是标准库 [Future 接口](https://doc.rust-lang.org/std/future/trait.Future.html)的基本模型；实际业务里通常用 await，无须自己调用 poll。

编译器会把 async 函数转换成保存执行进度的状态机。可以把一次 SET 理解为“尚未开始 → 写请求 → 等响应 → 完成”；需要跨越挂起点继续使用的局部值保存在 Future 状态里。这里是帮助理解的逻辑状态，不是对编译器生成结构的逐字段还原，也不是每个 async 函数背后创建了一个线程。

因此 `.await` 有可能立即得到结果，并不保证每次都让出执行权。把长时间 CPU 循环写在 async 函数里，也不会自动变成不阻塞调度的工作。异步代码中使用 `std::thread::sleep` 会阻塞线程；这里的网络等待和定时使用 Tokio 接口。

并发指多项工作在时间上交错推进；并行指同一时刻在不同执行资源上运行。单线程 runtime 也能并发处理 I/O，多线程 runtime 可以让任务并行推进。Tokio 的[任务教程](https://tokio.rs/tokio/tutorial/spawning)可以帮助建立这一层区别。

## main 的 Future 由谁驱动

Rust 提供 async/await 语法与 Future trait；Tokio 提供执行这些异步 I/O 程序需要的 runtime。runtime 包括任务调度、I/O 事件驱动、时间驱动等组件。`use tokio::...` 只把名字引入作用域，不会创建 runtime。

第 01 章的 `#[tokio::main]` 负责在同步程序入口建立 runtime，再驱动异步主体。对于本书默认的多线程入口，可以用下面的**概念等价代码**理解；这不是宏展开结果的逐字复制：

```rust
fn main() -> mini_redis::Result<()> {
    let runtime = tokio::runtime::Builder::new_multi_thread()
        .enable_all()
        .build()?;
    runtime.block_on(async {
        let mut client = mini_redis::Client::connect("127.0.0.1:16379").await?;
        client.set("course", "rust".into()).await?;
        Ok(())
    })
}
```

`block_on` 会让同步调用者等待这个根 Future 完成，同时驱动 runtime；异步主体内部仍可以在等待 I/O 时让其他任务推进。所以“同步入口等待完成”和“内部使用非阻塞 I/O”并不矛盾。

配套 async_basics 使用显式 Builder，而不是属性宏，让你看见这层启动过程。它选用 `new_current_thread()`，只用当前线程驱动普通异步任务，也能使用计时器；不需要为了一个等待动作新建一条线程。宏、Builder 和调度器选项可对照 [Tokio 1.32.0 runtime API](https://docs.rs/tokio/1.32.0/tokio/runtime/index.html)以及[入口宏文档](https://docs.rs/tokio/1.32.0/tokio/attr.main.html)，本文同时核对了本机锁定版本的源码文档。

## Cargo features 与运行时分别管什么

[根 Cargo.toml](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/mini-redis/source/Cargo.toml) 使用 `tokio = { version = "1", features = ["full"] }`。`version = "1"` 是版本约束，具体构建版本来自 Cargo.lock；`features` 决定编译时包含哪些能力。以本地 Tokio 1.32.0 为例：

| feature | 提供的能力 | 本项目的使用点 |
| --- | --- | --- |
| `macros` | tokio::main、tokio::test 等宏 | 程序与测试入口 |
| `rt` / `rt-multi-thread` | runtime 基础 / 多线程调度器 | current-thread CLI、多线程服务器 |
| `net` | 网络类型 | TcpListener、TcpStream |
| `io-util` | I/O 扩展方法与工具 | read_buf、write_all、BufWriter |
| `time` | 时间工具 | 退避等待、过期清理 |
| `sync` | 同步与通信工具 | Semaphore、Notify、各类 channel |
| `signal` | 信号处理 | Ctrl+C 停机 |

`full` 组合开启常用能力，**不是“开多线程”的另一种写法**，也不等于包含所有可选 feature。本项目测试用的 `test-util` 还在 dev-dependencies 中单独声明。构建时选中了 time/net 等能力，显式 Builder 还要通过 `.enable_all()` 启用相应可用驱动；只“编译得见”并不等于已经有正在工作的运行环境。上述 feature 对应关系已按锁定版本的 Cargo.toml 核对，可继续阅读 [Tokio feature 文档](https://docs.rs/tokio/1.32.0/tokio/index.html#feature-flags)。

现在可以分别回答三个问题：Cargo 选择哪些代码参与构建，runtime 为异步操作提供怎样的执行环境，具体任务由谁提交和等待。不要用一个“Tokio 已开启”代替这三层判断。

## 一个连接一个 Handler 任务

如果接入第一个客户端后就直接 `handler.run().await`，接入循环要等这个 Handler 结束才会继续。这仍是异步等待，却会阻止该循环接入下一位客户端。因此服务器还需要把连接处理作为独立任务提交。

在 [Listener::run](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/mini-redis/source/src/server.rs) 中，每轮做四件事：取得连接配额，accept 一个 socket，构造 Handler，spawn 任务运行它。

源码关键结构：

```rust
tokio::spawn(async move {
    if let Err(err) = handler.run().await {
        error!(cause = ?err, "connection error");
    }
    drop(permit);
});
```

`async move` 把捕获到的 Handler 和 permit 移入 Future。这样 accept 循环可以继续走，任务也不需要借用这一轮循环里的局部变量。任务结束后，其持有的 socket、permit、停机发送端等资源都会被释放。

| 写法 | 当前执行流接下来做什么 |
| --- | --- |
| `let work = handle();` | 仅取得 async fn 返回的 Future，函数体尚未执行 |
| `handle().await` | 在当前任务中驱动 handle，并等到它完成 |
| `let task = tokio::spawn(handle());` | 提交独立任务，得到 JoinHandle，当前任务可继续 |
| `task.await` | 等已提交任务结束，得到包含任务执行状态的结果 |

spawn 的任务在 runtime 得到驱动时就可以推进，不必等调用者 await JoinHandle 才开始；丢弃 JoinHandle 也不等于取消任务。这与实验中丢弃“尚未被执行的 async fn Future”不同。主入口返回、runtime 被销毁时，也不能假设所有未完成任务会自动做完；第 10 章因此安排了明确的停机等待。

服务器入口用默认 `#[tokio::main]`，本地启用的 Tokio features 支持多线程 runtime；CLI 则显式用 `flavor = "current_thread"`。不要因 CLI 单线程就认为服务器也在使用同一种配置。

一个 Handler 内部按“读一帧 → 解析 → 执行 → 再读”的顺序工作。同一连接上的命令不会在这里被分别 spawn；不同连接之间则可能交错执行。客户端一次发来多个请求，服务端可以按序处理，但本地基础 Client 没有实现流水线的多请求管理。

## Send、Sync 与 'static

`tokio::spawn` 要求提交的 Future 可在线程间移动，并且不借用会提前消失的外部短期数据。常见约束是 `Send + 'static`，其输出也有相应约束。

- `Send`：一个值可以安全地把所有权交给另一个线程。
- `Sync`：共享引用 `&T` 可以安全地在线程间传递。
- `T: 'static`：T 不包含需要受短期外部借用约束的引用；不意味着这个值必须活到进程结束。

`async move` 可以接管 String、Db 等拥有的数据，但把一个短期引用 move 进去并不会把被引用的对象也变成长寿命对象。反过来，普通拥有的 String 可以满足 `'static` 约束，任务结束时照样正常释放。

为什么跨 await 持有 `std::sync::MutexGuard` 容易报 Future 不是 Send？因为挂起后的任务必须保存下一次执行还要用到的局部状态，Guard 也在其中。第 06 章通过短同步临界区避免这一问题。

## 连接限制不是立刻拒绝新连接

`MAX_CONNECTIONS` 是 250，配额由 `Arc<Semaphore>` 管理。`acquire_owned().await` 在 accept **之前**执行。没有许可时服务器暂停继续 accept，已经存在的 Handler 仍可运行。

所以这不是“第 251 个 TCP connect 一定马上失败”的承诺：操作系统的监听队列仍会参与连接建立与排队。配额限制的是应用接入处理，实际客户端观察受 backlog、超时等影响。

permit 是资源句柄。任务正常结束或者释放时，许可归还；成功路径中的显式 `drop(permit)` 让归还位置容易阅读。这是 RAII 在容量管理上的应用。

accept 失败后，代码采用 1、2、4、8、16、32、64 秒退避；持续失败到下轮时返回错误。它避免错误状态下无限忙循环，不代表对所有错误都进行了分类恢复。

## select 是同时等待多个事件

Handler 在“收到一帧”和“停机通知”之间等待：

```rust
let maybe_frame = tokio::select! {
    res = self.connection.read_frame() => res?,
    _ = self.shutdown.recv() => return Ok(()),
};
```

两条分支在当前任务中被驱动，不会因此创建两个线程。一个分支胜出，未完成分支的 Future 被丢弃。于是必须问：被取消的操作有没有已经修改外部状态，下一次调用还能否继续？

这里已读取的字节保存在 Connection 的成员 buffer 中，而不是只放在临时 Future 的局部容器里；`read_buf` 的取消语义也参与正确性。遇到其他 API 时不能照搬“取消一定安全”的结论。官方 [select 教程](https://tokio.rs/tokio/tutorial/select)专门解释了分支取消。

命令的 `apply(...).await` 位于这个 select 外部。普通命令开始执行后，停机不会通过这处 select 直接打断写响应。订阅命令另有内部 select；具体退出行为在第 10 章分析。

为什么不对每个 GET 都 spawn 一个新任务？

<details>
<summary>参考答案</summary>

同一个连接的请求与响应有顺序关系，Connection 还需要独占可变访问。随意拆成任务会引入响应配对与写入交错问题。这里每连接顺序处理已经足以展示异步 I/O 并发；跨连接共享数据的并发问题由 Db 处理。

</details>
