---
title: "第 29 章：全局 Tokio 运行时"
description: 同步内核和异步 I/O 怎样分工；为什么全进程只有一个 Tokio 运行时；get_runtime 的懒初始化、NAUTILUS_WORKER_THREADS 和 set_runtime 注入；在同步代码里调用异步函数的三个桥接函数；Rust 和 Python 下各有哪些线程、节点跑在哪个线程上；不准直接 tokio::spawn 的约定；进程退出时运行时怎样收尾。
---

# 第 29 章：全局 Tokio 运行时

[全书目录](./index.md) · [上一章](./reports-and-statistics.md) · [下一章](./live-node.md)

::: tip 本章学习目标
能说出哪些 crate 是同步的、哪些用 Tokio，以及这条界线由什么保证；知道全局运行时什么时候被创建、工作线程数怎样设置、怎样注入自己的运行时以及注入的限制；能在同步代码里正确地调用一个异步函数，知道直接 `block_on` 会出什么问题；能画出一个 Rust 节点和一个 Python 节点各自的线程分布；知道写适配器时为什么要用 `get_runtime().spawn` 而不是 `tokio::spawn`。

**源码版本：** `develop` 分支，提交 `364254f`（2026-11-18）。运行时在 `crates/common/src/live/runtime.rs`，Python 退出钩子在 `crates/pyo3/src/lib.rs`，Python 节点的运行入口在 `crates/live/src/python/node.rs`，日志线程在 `crates/common/src/logging/logger.rs`，Tokio 用法检查在 `.pre-commit-hooks/check_tokio_usage.sh`，`LocalSet` 禁用规则在 `clippy.toml`。

**对应官方文档：** [Rust 开发指南 · Async code](https://nautilustrader.io/docs/latest/developer_guide/rust/) · [Live Trading](https://nautilustrader.io/docs/latest/concepts/live/)
:::

第四部分的回测是一个纯同步的循环：数据一条条播放，没有网络，没有等待。实盘不一样：行情从 WebSocket 推过来，下单要发 HTTP 请求，计时器要在真实时间到点。这些都是异步 I/O，NautilusTrader 用 Tokio 处理。第五部分讲实盘这一层，从最底下的 Tokio 运行时开始。

主线例子：一个用 Python 写策略的实盘节点，接入 OKX 的行情和交易。我们看这个进程里有哪些线程、每个线程在做什么。

## 1. 两种代码，一条界线 {#boundary}

NautilusTrader 的代码分成两类：

- **同步内核**：数据引擎、风控、执行引擎、组合、缓存、策略（第三部分）。它们跑在一个线程上，大量使用 `Rc<RefCell<…>>`，不知道 Tokio 的存在。
- **异步 I/O**：适配器的数据和执行客户端、网络层、实盘节点的事件循环。它们用 Tokio 的任务、计时器和 channel。

这条界线不是靠自觉维持的。`.pre-commit-hooks/check_tokio_usage.sh` 列出了 13 个“同步核心 crate”：`analysis`、`backtest`、`core`、`cryptography`、`data`、`execution`、`indicators`、`model`、`portfolio`、`risk`、`serialization`、`system`、`trading`。它们只能把 Tokio 作为开发依赖（写测试用），不能作为正式依赖；`common` 可以依赖 Tokio，但必须是可选的，只在 `live` 特性下打开。所以一个只做回测的程序，依赖图里根本没有 Tokio 的运行时代码。

两边通过 channel 交换消息：异步一侧把行情、订单事件发进 channel，核心线程从 channel 里取出来处理；核心线程的命令也经 channel 交给异步一侧。channel 的细节在第 30 章。

## 2. 一个全局运行时 {#global}

所有异步工作共用一个 Tokio 运行时，它是一个进程级的静态变量：

```rust
// 节选自 crates/common/src/live/runtime.rs
static RUNTIME: OnceLock<NautilusRuntime> = OnceLock::new();

pub fn get_runtime() -> &'static tokio::runtime::Runtime {
    &RUNTIME.get_or_init(initialize_runtime).runtime
}
```

源码注释给出的理由是：一个长期存在的运行时，省掉反复创建和销毁的开销。它是**懒初始化**的，第一次调用 `get_runtime()` 时才创建。`initialize_runtime` 做三件事：

1. 编译了 `python` 特性时，先初始化 Python 解释器，确保工作线程启动前 Python 已就绪；
2. 读环境变量 `NAUTILUS_WORKER_THREADS`，是正整数就设为工作线程数；没设、为 0 或不是数字时，用 Tokio 的默认值（CPU 核数）；
3. 建一个多线程运行时，打开所有驱动（I/O、计时器），并在每个工作线程启动时设置一个线程局部标记 `NAUTILUS_RUNTIME_THREAD`，用来识别“当前是不是 Nautilus 运行时的工作线程”（第 3 节会用到）。

**注入自己的运行时。** Rust 程序如果已经有一个配置好的运行时，可以在第一次使用之前调用 `set_runtime(runtime)` 交给 NautilusTrader。有两个限制：必须是多线程运行时（适配器会用到 `block_in_place`，单线程运行时不支持）；全局运行时已经存在时会失败，并把传入的运行时原样还给你。官方要求在 `LiveNode::build()` 和任何适配器使用之前完成注入。另外，注入的运行时绕过了上面的初始化过程，包括 Python 初始化；同时用 `python` 特性时，要自己先初始化 Python。

## 3. 在同步代码里调用异步函数 {#bridge}

同步代码有时必须等一个异步函数的结果，比如 Python 绑定里的一个同步方法要连接网关。直觉的做法是 `get_runtime().block_on(future)`，但如果当前线程已经处在某个 Tokio 运行时里（比如在一个异步任务里被调用），Tokio 会直接 panic：不能在运行时里再启动一个运行时。`runtime.rs` 提供了三个桥接函数，按当前线程的情况选择做法：

| 函数 | 不在任何运行时里 | 在 Nautilus 运行时的工作线程上 | 在别的运行时里 |
| --- | --- | --- | --- |
| `block_on_nautilus(fut)` | `get_runtime().block_on` | `block_in_place` 包住 `block_on` | 多线程：同左；单线程：panic |
| `block_on_nautilus_with(make_fut)` | `get_runtime().block_on` | `block_in_place` 包住 `block_on` | 在一个临时线程里 `block_on` |
| `block_in_place_on_nautilus(f)` | 直接调用 `f` | `block_in_place(f)` | 直接调用 `f` |

`block_in_place` 告诉 Tokio“这个工作线程要阻塞一会儿”，Tokio 会把它手上的其他任务交给别的工作线程，避免整个运行时卡住。`block_on_nautilus_with` 接收的是一个“生成 future 的闭包”，所以可以把它挪到另一个线程去创建和运行，这是它能处理“在别的运行时里”这种情况的原因。盈透适配器的 Python 绑定用的就是这个函数。

## 4. 进程里有哪些线程 {#threads}

**Python 节点。** 主线例子里，Python 调用 `node.run()`。绑定代码先释放 GIL（`py.detach`），然后在**调用它的那个 Python 线程**上执行 `get_runtime().block_on(node.run())`。于是：

- **核心线程**就是这个 Python 线程。`LiveNode::run` 这个 future 在它上面被驱动：事件循环、所有引擎、策略回调都在这里执行。策略是 Python 写的，回调时临时重新拿 GIL（第 39 章）。
- **Tokio 工作线程**属于全局运行时，适配器的 WebSocket 读写、HTTP 请求、重连、实时计时器的等待都在这里。
- **日志线程**是一个普通的操作系统线程，名字叫 `logging`，不属于 Tokio。所有组件把日志事件发进一个标准库的 channel，由它写到终端和文件，所以磁盘 I/O 不会阻塞核心线程（第 13 章）。

**Rust 节点。** 官方示例（比如 OKX 的 `node_exec_tester`）用 `#[tokio::main]` 写 `main` 函数，再 `node.run().await`。这时 `main` 函数所在的线程由 `#[tokio::main]` 建的运行时驱动，它就是核心线程；而适配器内部调用 `get_runtime()`，用的是 Nautilus 的全局运行时。也就是说，这样的进程里有**两个** Tokio 运行时：一个只用来驱动主线程上的节点，另一个承担所有 I/O。想合并成一个，就在 `main` 里自己建运行时，`set_runtime` 交给 NautilusTrader，再在这个运行时上运行节点。

不论哪种情况，节点都被绑定在一个线程上：`LiveNode::build` 会在线程局部变量里登记“这个线程已经有一个节点”，同一个线程上再建第二个会报错。

![一个实盘节点的线程分布：核心线程上运行节点的事件循环、各引擎和策略；全局 Tokio 运行时的工作线程上运行适配器的网络任务和实时计时器；日志线程独立写日志；三者之间通过 channel 通信](/nautilus-trader/figures/tokio-runtime-threads.svg)

怎么读这张图：中间一列是核心线程，所有带 `Rc` 的状态都只在这里。左边是 Tokio 工作线程，数量由 `NAUTILUS_WORKER_THREADS` 决定。右边是日志线程。箭头都是 channel，没有任何共享的可变状态跨越线程。

## 5. 写异步代码的约定 {#conventions}

官方 Rust 开发指南对异步代码有几条约定，其中一部分由提交前钩子检查：

- **用 `get_runtime().spawn`，不用 `tokio::spawn`。** 适配器的方法可能在 Python 线程上被调用，那里没有 Tokio 的线程局部上下文，`tokio::spawn` 会 panic。`get_runtime()` 要从 `nautilus_common::live` 导入。
- **Tokio 的 `spawn`、`time`、`sync` 写全路径。** 比如写 `tokio::time::sleep` 而不是先 `use tokio::time::sleep`，这样检查脚本能找到每一处用法。确实需要例外时，在那一行加注释 `// tokio-import-ok`。
- **测试里用 `#[tokio::test]` 自带的运行时**，测试里直接 `tokio::spawn` 是可以的。
- **不用 `tokio::task::LocalSet`。** `clippy.toml` 把它列为禁用类型，因为确定性仿真（第 37 章）用的 madsim 运行时没有它，替代品是 `nautilus_common::live::dst::task::spawn_local`。

第 31 章会看到，适配器里正式的做法是更进一步：任务不直接 spawn 到运行时上，而是挂在一个 `TaskGroup` 上，以便关闭时能统一收尾。

## 6. 进程退出 {#shutdown}

Python 扩展模块加载时，会用 `atexit` 注册一个退出函数，在解释器退出时调用 `shutdown_runtime(10 秒)`。不过从源码看，这个函数做的事很少：它在运行时上执行一次带 10 秒超时的 `yield_now`，让调度器转一圈就返回。运行时本身是一个静态变量，永远不会被 drop；工作线程随进程结束由操作系统回收。所以真正保证“关闭时任务收尾干净”的，不是这个函数，而是节点的 `stop` 流程和第 31 章的 `TaskGroup`。

## 7. 动手验证 {#lab}

前面几节的说法都能在一个小程序里直接看到。全局运行时一个进程只能建一次，所以实验把每个场景放进一个子进程里跑，主进程只负责依次启动它们、打印输出。

::: info 实验环境
Linux（aarch64，4 核、3 GB 内存）上的 Rust 1.100.0，NautilusTrader 各 crate 来自提交 `364254f`。代码是 <a href="/nautilus-trader/code/live-lab/examples/ch29_runtime.rs" download><code>ch29_runtime.rs</code></a>，属于第五部分的实验工程 `live-lab`（[在 GitHub 查看](https://github.com/lewislau86/lewislau86.github.io/tree/master/docs/public/nautilus-trader/code/live-lab)，`README.md` 写了运行方法）。运行命令是 `cargo run --example ch29_runtime`。下面的输出原样摘录，毫秒数每次运行略有不同。
:::

**懒创建与线程数。** 第一次调用 `get_runtime()` 之前和之后，各列一次进程里的线程名（读 Linux 的 `/proc/self/task`）：

<<< @/public/nautilus-trader/code/live-lab/examples/ch29_runtime.rs#lazy

```text
available CPUs: 4
== lazy 
before get_runtime: ch29_runtime ×1
after  get_runtime: ch29_runtime ×1, tokio-rt-worker ×4 (num_workers = 4)
== lazy NAUTILUS_WORKER_THREADS=2 
before get_runtime: ch29_runtime ×1
after  get_runtime: ch29_runtime ×1, tokio-rt-worker ×2 (num_workers = 2)
== lazy NAUTILUS_WORKER_THREADS=zero 
before get_runtime: ch29_runtime ×1
after  get_runtime: ch29_runtime ×1, tokio-rt-worker ×4 (num_workers = 4)
```

调用之前进程里只有主线程，运行时确实是第一次用到时才建的。机器有 4 个 CPU，默认就是 4 个工作线程；`NAUTILUS_WORKER_THREADS=2` 把它变成 2 个；设成不是数字的值时被忽略，回到默认。工作线程在系统里的名字是 `tokio-rt-worker`，用 `top -H` 或调试器看线程时认的就是它。

**注入的两个限制。**

<<< @/public/nautilus-trader/code/live-lab/examples/ch29_runtime.rs#inject

```text
== inject 
set_runtime(current_thread) -> Err (runtime handed back)
set_runtime(multi_thread, 3 workers) -> Ok
get_runtime().num_workers = 3
set_runtime again -> Err (runtime handed back)
== late-inject 
get_runtime() first, then set_runtime -> Err (runtime handed back)
```

单线程运行时被拒绝，多线程的被接受，之后 `get_runtime()` 返回的就是注入的那个（3 个工作线程）。全局运行时一旦存在，不论是注入的还是 `get_runtime()` 懒创建的，再注入都会失败，传进去的运行时原样还回来。

**在同步代码里调用异步函数。** 在三种线程上分别试一遍：

<<< @/public/nautilus-trader/code/live-lab/examples/ch29_runtime.rs#bridge

```text
== bridge 
[main thread] block_on_nautilus -> 1
[main thread] tokio::spawn -> panic: there is no reactor running, must be called from the context of a Tokio 1.x runtime
[main thread] get_runtime().spawn -> 2
[nautilus worker] get_runtime().block_on -> panic: Cannot start a runtime from within a runtime. This happens because a function (like `block_on`) attempted to block the current thread while the thread is being used to drive asynchronous tasks. If you are in an async function, use `.await` on the future instead of blocking on it.
[nautilus worker] block_on_nautilus -> 3
[other current_thread rt] block_on_nautilus -> panic: block_on_nautilus cannot run inside a current-thread Tokio runtime; use block_on_nautilus_with
[other current_thread rt] block_on_nautilus_with -> 4
```

三种情况和第 3 节的表一一对应：在普通线程上 `tokio::spawn` 找不到运行时，`get_runtime().spawn` 可以；在 Nautilus 的工作线程上直接 `block_on` 触发 Tokio 的“运行时里启动运行时”，`block_on_nautilus` 改用 `block_in_place` 后正常返回；在别的单线程运行时里，`block_on_nautilus` 主动 panic 并提示改用 `block_on_nautilus_with`，后者在临时线程上完成。

**两个运行时。** 模拟 `#[tokio::main]`：自己建一个 2 线程的运行时驱动 `main`，里面再碰一下 `get_runtime()`：

<<< @/public/nautilus-trader/code/live-lab/examples/ch29_runtime.rs#two-runtimes

```text
== two-runtimes 
threads: ch29_runtime ×1, main-rt-worker ×2, tokio-rt-worker ×4
```

两组工作线程同时存在，一共 6 个，这就是第 4 节说的“Rust 节点默认有两个运行时”。

::: warning 常见误区
- **在异步上下文里调用 `get_runtime().block_on`。** 会因为“运行时里启动运行时”而 panic，用 `block_on_nautilus` 系列函数。
- **在适配器里写 `tokio::spawn`。** 从 Python 线程调用时没有 Tokio 上下文，会 panic；要用 `get_runtime().spawn`，或者第 31 章的 `TaskGroup`。
- **在 `get_runtime()` 之后才调用 `set_runtime`。** 会失败，运行时被原样还给你。
- **注入一个单线程运行时。** `set_runtime` 会拒绝它。
- **以为日志也跑在 Tokio 上。** 日志有自己的操作系统线程。
- **以为 `#[tokio::main]` 的运行时就是 NautilusTrader 用的那个。** 不是，除非你用 `set_runtime` 把它交出去。
- **在同一个线程上建两个 `LiveNode`。** 第二个会报错。
:::

## 本章结论

NautilusTrader 把代码分成同步内核和异步 I/O 两边，13 个核心 crate 不依赖 Tokio，由提交前钩子保证。所有异步工作共用一个进程级的多线程 Tokio 运行时，第一次 `get_runtime()` 时懒创建，工作线程数由 `NAUTILUS_WORKER_THREADS` 设置，也可以在首次使用前用 `set_runtime` 注入一个多线程运行时。同步代码要等异步结果时，用 `block_on_nautilus` 系列函数，它们按当前线程是否在运行时里选择 `block_on`、`block_in_place` 或临时线程。节点的事件循环和所有引擎跑在一个核心线程上：Python 节点是调用 `run()` 的那个线程，Rust 节点是驱动 `main` 的那个线程；适配器的 I/O 在全局运行时的工作线程上，日志在专用线程上，彼此用 channel 通信。

## 检查理解

1. 一台 4 核机器上跑一个 Python 实盘节点，没有设置任何环境变量。进程里大约有哪些线程？想把 Tokio 工作线程限制为 2 个，怎样做？

   <details><summary>参考答案</summary>

   一个核心线程（调用 `node.run()` 的 Python 主线程），4 个 Tokio 工作线程（默认等于 CPU 核数），一个名为 `logging` 的日志线程，以及 Python 和 Tokio 自己的辅助线程（比如阻塞任务线程池，按需创建）。在启动 Python 之前设置环境变量 `NAUTILUS_WORKER_THREADS=2`；它只在全局运行时第一次创建时读取，运行时创建之后再改不起作用。

   </details>

2. 你在一个适配器的异步任务里，需要调用一个只有同步接口的函数，而那个函数内部又会 `get_runtime().block_on(...)`。会发生什么？怎样改？

   <details><summary>参考答案</summary>

   这个异步任务运行在 Nautilus 运行时的工作线程上，函数内部再 `block_on` 会因为“在运行时里启动运行时”而 panic。把那个函数内部的 `block_on` 改成 `block_on_nautilus`：它会发现当前线程是 Nautilus 运行时的工作线程，改用 `block_in_place` 包住 `block_on`，让 Tokio 先把这个线程上的其他任务移走。

   </details>

3. 一个 Rust 程序用 `#[tokio::main]` 运行节点，同时在 `main` 里自己 `tokio::spawn` 了一个监控任务，监控任务里调用了适配器的 HTTP 客户端。这个进程里有几个 Tokio 运行时？监控任务和 HTTP 请求各在哪个运行时上？

   <details><summary>参考答案</summary>

   两个。监控任务是在 `#[tokio::main]` 建的运行时上 spawn 的；HTTP 客户端如果内部用 `get_runtime().spawn` 发后台任务，那些任务在 Nautilus 的全局运行时上，而监控任务里直接 `await` 的部分仍在主运行时上。功能上没问题，但线程数翻了一倍。想只用一个运行时，就自己建一个多线程运行时，先 `set_runtime` 交给 NautilusTrader，再在 `get_runtime().block_on(async_main())` 里运行一切。

   </details>

## 参考资料

- 官方文档：[Rust 开发指南](https://nautilustrader.io/docs/latest/developer_guide/rust/)（Async code 一节） · [Live Trading](https://nautilustrader.io/docs/latest/concepts/live/)
- 源码：[`crates/common/src/live/runtime.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/common/src/live/runtime.rs) · [`crates/pyo3/src/lib.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/pyo3/src/lib.rs) · [`crates/live/src/python/node.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/live/src/python/node.rs) · [`.pre-commit-hooks/check_tokio_usage.sh`](https://github.com/nautechsystems/nautilus_trader/blob/develop/.pre-commit-hooks/check_tokio_usage.sh)
- 实验代码：[`live-lab`](https://github.com/lewislau86/lewislau86.github.io/tree/master/docs/public/nautilus-trader/code/live-lab) 的 `examples/ch29_runtime.rs`
- 配图由 `scripts/generate-nautilus-trader-figures.py` 生成。

核心线程上的那个事件循环是怎样从 channel 里取消息的？下一章看 `LiveNode` 和 `AsyncRunner`。[第 30 章：LiveNode 与 AsyncRunner](./live-node.md)。
