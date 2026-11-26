---
title: "第 37 章：确定性仿真测试：让异步代码可重放"
description: 异步代码的竞态为什么难以复现；DST 怎样用一个种子决定任务调度、计时器和随机数；第一层：用 madsim 替换 Tokio 的时间、任务、运行时和信号；第二层：时钟、随机数、迭代顺序、select 轮询顺序这些运行时之外的不确定来源；确定性契约和它成立的条件；提交前钩子的七条规则；模拟的 HTTP 与 WebSocket 传输、Turmoil 网络种子扫描；make cargo-test-sim 跑什么；适配器的 DST 契约；DST 不覆盖什么。
---

# 第 37 章：确定性仿真测试：让异步代码可重放

[全书目录](./index.md) · [上一章](./external-backends.md) · [下一篇](./futu-adapter.md)

::: tip 本章学习目标
能解释为什么一个“偶尔失败”的异步测试很难修，以及 DST 怎样把它变成“用同一个种子必然失败”；能说出 DST 的两层：哪些 Tokio 原语被替换、哪些不确定来源要靠代码约定；能列出确定性契约成立的条件，知道违反其中一条时会发生什么；能读懂 `// dst-ok` 标记和提交前钩子的报错；会用 `MADSIM_TEST_SEED` 重放一次失败；知道适配器为什么要满足 DST 契约，以及 DST 不保证什么。

**源码版本：** `develop` 分支，提交 `364254f`（2026-11-18）。运行时门面在 `crates/common/src/live/dst.rs`，网络层的模拟在 `crates/network/src/dst.rs`、`dst/stream.rs` 和 `http/simulation.rs`，墙上时间的接缝在 `crates/core/src/time.rs`，静态检查在 `.pre-commit-hooks/check_dst_conventions.sh` 和 `clippy.toml`，测试入口在 `Makefile` 的 `cargo-test-sim`。

**对应官方文档：** [DST](https://nautilustrader.io/docs/latest/concepts/dst/)
:::

第五部分的前八章讲的都是并发：事件循环同时等着 7 个 channel（第 30 章），任务组在两个期限内收尾（第 31 章），计时器在工作线程上到点（第 32 章），WebSocket 断线重连（第 33 章），对账请求和行情推送交错到达（第 34 章），订单簿恢复和重连同时发生（第 35 章）。这些代码最容易出的问题是**竞态**：某个顺序下才会出现的错误。比如关闭时，如果某个任务恰好在另一个任务之前被唤醒，一条消息就会丢失。

竞态的麻烦在于不可复现：Tokio 的调度顺序、计时器的精度、操作系统的线程调度、哈希表的随机种子，每次运行都不一样。CI 上失败了一次，本地跑一千次都过。**确定性仿真测试**（DST，deterministic simulation testing）把这些不确定的来源全部换成一个种子驱动的伪随机序列：不同的种子探索不同的交错顺序，同一个种子必然得到同一个顺序。失败时记下种子，就能无限次重放同一次执行。这个做法来自 FoundationDB，Rust 生态里用 madsim 实现。

主线例子：网络层的一个 WebSocket 重连测试在 CI 的某个种子上失败了。我们看它是怎样被重放、被定位的。

## 1. 第一层：替换 Tokio {#layer1}

在 `nautilus-common` 打开 `simulation` 特性，并且用 `RUSTFLAGS="--cfg madsim"` 编译时，`nautilus_common::live::dst` 这个门面模块会把四组原语从 Tokio 换成 madsim：

| 子模块 | 内容 | 普通构建 | 仿真构建 |
| --- | --- | --- | --- |
| `time` | 计时器、间隔、单调时间 `Instant` | `tokio` | `madsim` |
| `task` | spawn、join、`yield_now` | `tokio` | `madsim` |
| `runtime` | 运行时的构建器和句柄 | `tokio` | `madsim`（单线程、确定性） |
| `signal` | `ctrl_c`、`SIGTERM` | `tokio` | `ctrl_c` 用 madsim，`terminate` 永不完成 |

源码里处在 DST 路径上的代码不直接写 `tokio::time::sleep`，而是写 `dst::time::sleep`：第 30 章事件循环里的 `dst::time::interval`、第 31 章任务组里的 `dst::task::spawn`、第 33 章退避里的 `dst::time` 都是这样。普通构建下它们就是 Tokio，仿真构建下变成 madsim。madsim 的运行时是单线程的：`new_multi_thread()` 返回的也是确定性的单线程运行时，`worker_threads()` 不起作用。

在仿真运行时里，时间是**虚拟**的：`sleep(1 分钟)` 不会真的等 1 分钟，调度器直接把虚拟时钟拨到 1 分钟后。所以一个测试几十分钟的重连退避，几毫秒就跑完了。源码里有一个专门的测试确认墙上时间也跟着虚拟时间走：

```rust
// 节选自 crates/common/src/live/dst.rs
#[madsim::test]
async fn test_dst_wall_clock_advances_with_virtual_time() {
    let before = nanos_since_unix_epoch();
    time::sleep(time::Duration::from_mins(1)).await;     // 虚拟的 1 分钟
    let after = nanos_since_unix_epoch();
    assert!(after - before >= 60 * NANOSECONDS_IN_SECOND);
}
```

Tokio 的 `sync`、`io`、`fs`、`net` 和 `select!` 宏没有被替换，仍然是真的 Tokio。`sync` 里的 channel 本身是真的，但收发两端的任务由 madsim 调度，所以 channel 的投递顺序仍然在确定性契约之内。

## 2. 第二层：运行时之外的不确定来源 {#layer2}

替换运行时只解决了调度和计时器。代码里还有很多别的不确定来源，每一个都要有一个“接缝”：

- **墙上时间。** 所有读取系统时间的地方都经过 `nautilus_core::time::duration_since_unix_epoch`。仿真时它读 madsim 的虚拟时间，第 32 章的 `AtomicTime` 也由此得到虚拟的“现在”。
- **单调时间。** 用 `dst::time::Instant`，网络层（它在依赖图上低于 `common`）用自己的 `nautilus_network::dst::time`。
- **随机数。** UUID 生成（`UUID4::new()`）、没给种子的成交模型（第 27 章）、重连的抖动（第 33 章）在仿真运行时里都改用 `madsim::rand`。
- **迭代顺序。** `AHashMap` 和 `AHashSet` 的哈希器每个进程随机，遍历顺序不确定。凡是遍历顺序会影响结果的地方（发布事件的顺序、从成交模型抽随机数的顺序），改用 `IndexMap`、`IndexSet` 或在使用时排序。第 20 章执行引擎的客户端表、第 26 章交易所的撮合引擎表都是 `IndexMap`，原因就在这里。
- **`select!` 的轮询顺序。** 不带 `biased;` 的 `tokio::select!` 用一个没有被拦截的随机数决定先检查哪个分支。所以 DST 路径上每一个生产代码里的 `select!` 都以 `biased;` 开头，第 30 章的事件循环、第 31 章的任务包装和 OKX 的 `spawn_task` 都是。

## 3. 确定性契约 {#contract}

在下面的条件都满足时，同一个种子、同一个二进制、同一份配置、同一个平台的两次运行，任务调度顺序、计时器触发（虚拟的单调时间和墙上时间）、`madsim::rand` 的输出、`tokio::sync` channel 的投递顺序**逐位相同**：

| 来源 | 必须满足 | 违反时 |
| --- | --- | --- |
| 构建 | 同时打开 `simulation` 特性和 `--cfg madsim` | 只设其一会**静默地**退回真的 Tokio |
| `select!` | 生产代码里每个都以 `biased;` 开头 | 轮询顺序由未拦截的随机数决定 |
| 单调时间 | 用 `dst::time` | `std::time::Instant::now` 读宿主时钟 |
| 墙上时间 | 用 `duration_since_unix_epoch` 接缝 | 绕过虚拟时间 |
| 随机数 | 用 `madsim::rand` | `rand::rng()`、`fastrand`、`OsRng` 不被拦截 |
| 迭代顺序 | `IndexMap`、`IndexSet` 或排序 | 哈希随机导致顺序变化 |
| 本地任务 | 仿真下不用 `LocalSet` | madsim 没有 `LocalSet` |
| 阻塞任务 | 不用 `spawn_blocking` | 阻塞调用逃出确定性调度 |

第一行最容易出错：只设了特性、忘了 `--cfg madsim`，编译不会报错，测试照样跑，只是跑在真的 Tokio 上，什么都不确定。`Makefile` 里的 `SIM_RUSTFLAGS := --cfg madsim` 就是为此统一设置的。

## 4. 静态检查 {#enforcement}

靠审查者记住这些约定是不够的，所以有两层自动检查：

- **Clippy**：`clippy.toml` 禁止直接调用 `getrandom::{fill, u32, u64}`，禁止 `tokio::task::LocalSet`（第 29 章提到过）。
- **提交前钩子 `check-dst-conventions`**：Clippy 表达不了的、和路径或 `cfg` 相关的结构性规则，共七条：

| 规则 | 拒绝 |
| --- | --- |
| 1 | 直接读时钟：`Instant::now()`、`SystemTime::now()`、`jiff::Timestamp::now()` 等 |
| 2 | 未拦截的随机数：`rand::rng()`、`fastrand`、`getrandom`、`OsRng`、`Uuid::new_v4()` |
| 3 | 生产代码里前三行没有 `biased;` 的 `tokio::select!` |
| 4 | `std::thread::spawn`、`std::thread::Builder::new`、`spawn_blocking` |
| 5 | 对账管理器和撮合引擎里的 `AHashMap`、`AHashSet` |
| 6 | 直接 `TcpStream::connect`、`TcpListener::bind`（要经 `nautilus_network::net`） |
| 7 | madsim 构建路径上的生产代码里直接写 `tokio::{time, task, runtime, signal}` |

规则覆盖 17 个 crate（`nautilus-live` 依赖闭包里的 16 个，加上 `backtest`），以及登记过的适配器文件。确实需要例外的行加注释 `// dst-ok` 并写明理由，比如只用于日志的计时；测试、`python/`、`ffi/` 目录不在检查范围内。第 29 章提到日志线程是 `std::thread::Builder` 建的，它用 `#[cfg(not(madsim))]` 排除在仿真构建之外：仿真时不启动日志线程，日志事件被丢弃。

## 5. 网络：两种模拟 {#network}

适配器的核心是网络 I/O，网络层有两种模拟手段：

**madsim 字节流。** 仿真构建下，`nautilus-network` 把明文的 HTTP/1.1 请求和 Tungstenite 的 WebSocket 连接跑在 madsim 的字节流上，测试可以在同一个仿真里起一个本地的“假交易所”。它只支持 `http://` 和 `ws://`：HTTPS、WSS、代理和 sockudo 后端在打开连接前就会被拒绝。模拟覆盖的是 HTTP 请求的字节、WebSocket 消息的负载和领域事件；为了让请求字节可复现，请求头按名字排序（因此和实盘的请求头顺序不一定一样），每个请求都开一个新连接，不模拟连接池。

**Turmoil 网络种子扫描。** Turmoil 是另一个模拟器，它模拟网络本身：链路延迟、节点顺序、分区。网络层用它测试连接、重连、分区、在重连途中关闭、在退避途中关闭、服务端反复掉线这些场景，并断言应用消息的顺序完全一致。有一个默认忽略的“种子浸泡”测试，用 `scripts/soak-network-turmoil.sh` 不停地扫描种子，每个种子随机化节点顺序和 1～25 毫秒的链路延迟，对两种 WebSocket 后端各跑一遍。madsim 和 Turmoil 不能在同一次构建里同时打开。

## 6. 跑测试与重放 {#run}

`make cargo-test-sim` 设置 `--cfg madsim`，用 nextest 跑三组测试：

1. 标准精度：`nautilus-common`、`nautilus-core`、`nautilus-event-store`、`nautilus-network`、`nautilus-execution`、`nautilus-live` 中与仿真兼容的测试；
2. 标准精度：每个登记过的适配器的 `dst` 集成测试，不带适配器的默认特性；
3. 高精度：`nautilus-common` 和 `nautilus-execution` 的全部测试，覆盖 `i128`、`u128` 的原始值路径（第 2 章）。

`make pre-flight` 在跑其他测试之前先跑这一步；每晚的 CI 也跑它，并且从运行编号算出连续 5 个种子。

`#[madsim::test]` 默认每次用不同的种子，失败时把种子打印出来。主线例子里，CI 报告重连测试在种子 `1234567` 上失败，本地这样重放：

```bash
MADSIM_TEST_SEED=1234567 RUSTFLAGS="--cfg madsim" \
  cargo nextest run -p nautilus-network --features simulation --test simulation
```

同一个种子下，任务唤醒顺序、虚拟时间、抖动的随机数都和 CI 上完全一样，失败必然复现。加日志、加断点、改代码之后再用同一个种子验证修复。

## 7. 适配器与 DST {#adapters}

第 38 章翻译的适配器开发指南里提到，官方维护的适配器要么满足 DST 契约，要么附一份迁移记录说明还差什么；OKX 是参考实现。适配器的 DST 契约要求它声明的每一条路径：

- 暴露并传递 `simulation` 特性，仿真构建下能编译运行，没有只为测试存在的生产行为；
- 被静态检查覆盖，或者有记录在案的豁免理由；
- 时间、计时器、随机数、生成的 ID 都来自门面或接缝；任务、计时器、`select!` 遵守上面的约定；连接、重连、重试、退订、关闭都是确定的；
- 发到交易所的字节可复现：重试和重连保留协议里的 ID，同样的输入产生逐字节相同的请求；
- 端点指向测试里受控的本地对端，不含写死的交易所地址、真实凭证或真实的交易所状态；
- 在全新的进程里，同样的种子、配置和对端脚本产生相同的线路记录和领域输出，并且至少能识别出一个故意引入的错误。

## 8. DST 不保证什么 {#scope}

契约的边界同样重要：

- **Python 和 FFI 不在范围内。** DST 在原生 Rust 测试框架里运行，不启动 Python。用 Python 写的策略可能调用 `time.time()`、发网络请求、依赖线程调度，Rust 内核按契约处理它发来的命令，但从 Python 入口开始的端到端重放没有保证。只有 Rust 写的策略，或者由 Rust 测试框架驱动时，才能完整重放。
- **跨平台不保证逐位一致。** madsim 拦截系统时钟和随机数的方式依赖平台，Linux x86_64 上能复现的种子，在 macOS aarch64 上不一定。
- **未被替换的依赖会静默逃逸。** 直接调用 `libc`、绕过 `std::net`、使用未接入的随机数源，都会在没有任何报错的情况下读到真实世界。TLS、Redis、SQL 客户端内部用的是真的 Tokio，不在模拟范围内。
- **适配器默认不在范围内**，除非它在集成指南里登记了经过审查的部分。
- DST 不替代单元测试、集成测试、属性测试和验收测试，它补充的是异步时序和恢复路径这一块。

![DST 的两层：第一层由 nautilus_common::live::dst 门面在 simulation 加 cfg(madsim) 时把 time、task、runtime、signal 换成 madsim；第二层用接缝处理墙上时间、单调时间、随机数、迭代顺序和 select 轮询顺序；静态检查的七条规则守住这些约定；同一个种子得到相同的调度、计时器和随机数，失败时用 MADSIM_TEST_SEED 重放](/nautilus-trader/figures/dst-layers.svg)

怎么读这张图：中间一列是一份源码在两种构建下的样子，左边是普通构建、右边是仿真构建，门面和接缝是两者之间的开关。底部是种子：它是仿真运行里唯一的不确定输入。

## 9. 动手验证 {#lab}

同一个小程序编译两次：一次只打开 `simulation` 特性，一次再加上 `--cfg madsim`。程序起五个任务，每个在两个 `yield_now` 之后记下自己的名字（`0a` 是任务 0 的第一步），然后睡 3 秒，生成一个 UUID，再遍历一个 6 个键的 `AHashMap`。每个种子在一个新的子进程里跑，种子 1 跑两次。

::: info 实验环境
Linux（aarch64，4 核、3 GB 内存）上的 Rust 1.100.0，`nautilus-common`、`nautilus-core` 来自提交 `364254f`，madsim 0.2.34。代码在独立的小工程 `dst-lab` 里（[在 GitHub 查看](https://github.com/lewislau86/lewislau86.github.io/tree/master/docs/public/nautilus-trader/code/dst-lab)，`README.md` 写了运行方法），因为 `--cfg madsim` 会让依赖全部重新编译。下面的输出原样摘录。
:::

<<< @/public/nautilus-trader/code/dst-lab/src/main.rs#scenario

<<< @/public/nautilus-trader/code/dst-lab/src/main.rs#runtime

**只打开特性**（`cargo run --features sim`）：

```text
build: feature sim = true, cfg(madsim) = false
seed 1:
    interleaving 2a 0a 4a 1a 3a 2b 1b 4b 0b 3b
    uuid c5d1d116  ahash order ["ETH", "BTC", "XRP", "SOL", "DOGE", "ADA"]  wall clock advanced 3.005 s
    real time 3.006 s
seed 1:
    interleaving 0a 4a 1a 3a 0b 2a 1b 3b 4b 2b
    uuid 2e3de56a  ahash order ["ETH", "DOGE", "XRP", "ADA", "BTC", "SOL"]  wall clock advanced 3.004 s
    real time 3.006 s
seed 2:
    interleaving 4a 0a 3a 4b 1a 2a 2b 1b 3b 0b
    uuid 9fae8b96  ahash order ["ADA", "ETH", "BTC", "XRP", "DOGE", "SOL"]  wall clock advanced 3.005 s
    real time 3.007 s
```

**再加上 `--cfg madsim`**（`RUSTFLAGS="--cfg madsim" cargo run --features sim`）：

```text
build: feature sim = true, cfg(madsim) = true
seed 1:
    interleaving 2a 2b 1a 4a 1b 0a 0b 3a 4b 3b
    uuid 18fbf7bd  ahash order ["SOL", "ADA", "BTC", "ETH", "XRP", "DOGE"]  wall clock advanced 3.000 s
    real time 0.000 s
seed 1:
    interleaving 2a 2b 1a 4a 1b 0a 0b 3a 4b 3b
    uuid 18fbf7bd  ahash order ["SOL", "BTC", "ADA", "XRP", "ETH", "DOGE"]  wall clock advanced 3.000 s
    real time 0.000 s
seed 2:
    interleaving 1a 3a 0a 2a 2b 4a 0b 3b 4b 1b
    uuid 0ea16da4  ahash order ["ADA", "BTC", "XRP", "SOL", "DOGE", "ETH"]  wall clock advanced 3.000 s
    real time 0.000 s
```

两次对照，第 1 到第 3 节的说法都看得到：

- **只开特性等于没开。** 第一组的 `cfg(madsim) = false`，跑的是真的 Tokio：`dst::time::sleep(3 秒)` 真的睡了 3 秒，同样写着“种子 1”的两次运行，任务交错顺序和 UUID 都不一样。编译没有任何提示，这就是第 3 节表格第一行说的“静默退回”。
- **同一个种子，逐位相同。** 第二组里种子 1 的两次运行，在两个独立的进程里得到完全相同的交错顺序和 UUID；种子 2 则换了一种交错、一个不同的 UUID。UUID 相同说明 `UUID4::new()` 的随机数走的是 madsim 的确定性随机源。
- **时间是虚拟的。** 仿真里墙上时间前进了整整 3.000 秒，真实耗时 0.000 秒：`nanos_since_unix_epoch()` 这条接缝读的是虚拟时钟。
- **`AHashMap` 的遍历顺序不受种子控制。** 种子 1 的两次运行，同样 6 个键的遍历顺序不一样。这就是第 2 节要求在影响输出顺序的地方用 `IndexMap` 或排序的原因：哪怕调度、时间、随机数都确定了，一个随手写的哈希表遍历仍然会让两次运行分叉。

::: warning 常见误区
- **只打开 `simulation` 特性，忘了 `--cfg madsim`。** 会静默地跑在真的 Tokio 上，什么都不确定。
- **在 DST 路径上写 `tokio::time::sleep` 或 `Instant::now()`。** 要用 `dst::time` 和时间接缝，钩子会拒绝直接写法。
- **写一个不带 `biased;` 的 `select!`。** 分支顺序由未拦截的随机数决定。
- **在影响输出顺序的地方用 `AHashMap` 遍历。** 每个进程顺序不同，用 `IndexMap` 或排序。
- **以为 DST 能重放一个 Python 策略的完整运行。** Python 不在范围内。
- **在 Mac 上用 Linux CI 报的种子重放失败了，就以为问题不存在。** 跨平台不保证一致，要在同样的平台上重放。
- **以为仿真里测过 WSS 和 TLS。** 模拟只支持明文 `http://`、`ws://`。
:::

## 本章结论

DST 把异步系统里所有不确定的来源换成一个种子：第一层由 `nautilus_common::live::dst` 门面在 `simulation` 特性加 `--cfg madsim` 时把 Tokio 的时间、任务、运行时和信号换成 madsim 的确定性实现，时间变成虚拟的；第二层用接缝处理墙上时间、单调时间、随机数、迭代顺序和 `select!` 轮询顺序。条件全部满足时，同一种子、二进制、配置和平台的运行逐位相同，失败用 `MADSIM_TEST_SEED` 重放。Clippy 规则和提交前钩子的七条规则守住这些约定，`// dst-ok` 标记少数审查过的例外。网络层另有 madsim 字节流和 Turmoil 两种模拟，`make cargo-test-sim` 跑三组仿真测试。Python、FFI、TLS、Redis、未审查的适配器和跨平台一致性都不在契约之内。

## 检查理解

1. 你给一个适配器加了一个后台任务，里面用 `tokio::time::sleep(Duration::from_secs(5))` 做轮询，用 `std::collections::HashMap` 记录订阅。在 DST 下会有什么问题？提交前钩子会发现哪些？

   <details><summary>参考答案</summary>

   `tokio::time::sleep` 绕过了门面，仿真构建下仍然是真的 Tokio 计时器，而且会在 madsim 运行时里出问题；钩子的规则 7 会拒绝在 madsim 路径上直接写 `tokio::time`（前提是这个文件在钩子登记的适配器路径里）。`HashMap` 的遍历顺序同样随进程变化，如果遍历顺序决定了发出订阅请求的顺序，同一个种子也会产生不同的线路字节；规则 5 只检查对账管理器和撮合引擎两个文件，不会发现这一处，需要自己改成 `IndexMap` 或排序。

   </details>

2. 为什么第 30 章的事件循环、第 31 章的任务包装里，每个 `select!` 都以 `biased;` 开头？去掉会怎样？

   <details><summary>参考答案</summary>

   一方面是业务需要：事件循环要让信号、停止检查优先于行情。另一方面是 DST 的要求：不带 `biased;` 的 `select!` 在多个分支同时就绪时，用一个没有被 madsim 拦截的随机数决定先检查哪个，同一个种子下的两次运行可能选了不同的分支，确定性就被破坏了。钩子的规则 3 会拒绝前三行里没有 `biased;` 的生产 `select!`。

   </details>

3. 一个用 Python 写的策略在实盘里偶尔出错，你想用 DST 重放。可行吗？

   <details><summary>参考答案</summary>

   不能直接做到。DST 不启动 Python，Python 策略可能读真实时间、发网络请求、依赖线程调度，这些都不受种子控制。可行的做法是把出问题的逻辑用 Rust 写一个等价的策略，或者在 Rust 测试框架里构造策略发出的那串命令，再在仿真里重放内核对它们的处理。

   </details>

## 参考资料

- 官方文档：[DST](https://nautilustrader.io/docs/latest/concepts/dst/)
- 源码：[`crates/common/src/live/dst.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/common/src/live/dst.rs) · [`crates/network/src/dst.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/network/src/dst.rs) · [`crates/network/src/http/simulation.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/network/src/http/simulation.rs) · [`.pre-commit-hooks/check_dst_conventions.sh`](https://github.com/nautechsystems/nautilus_trader/blob/develop/.pre-commit-hooks/check_dst_conventions.sh) · [`Makefile`](https://github.com/nautechsystems/nautilus_trader/blob/develop/Makefile)（`cargo-test-sim`）
- 实验代码：[`dst-lab`](https://github.com/lewislau86/lewislau86.github.io/tree/master/docs/public/nautilus-trader/code/dst-lab)
- 延伸阅读：[FoundationDB 的测试方法](https://apple.github.io/foundationdb/testing.html) · [madsim](https://github.com/madsim-rs/madsim) · [Turmoil](https://github.com/tokio-rs/turmoil)
- 配图由 `scripts/generate-nautilus-trader-figures.py` 生成。

第五部分到这里结束。第六部分把前面所有内容用在一个具体的任务上：给 NautilusTrader 接入一个新的券商。[第 38 章：增加一个券商：以富途为例](./futu-adapter.md)。
