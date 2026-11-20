---
title: "第 31 章：任务管理：TaskGroup 与有界关闭"
description: 适配器为什么不能随手 spawn 后台任务；TaskGroup 怎样在任务开始运行前登记它、怎样用“代”隔离一次连接和下一次连接；关闭分为同步的开始和异步的收尾两段，先优雅取消再强制取消，各有一个期限；超时后任务仍被持有；panic 和意外取消怎样被记录；TaskSlot 和 finish_task 处理单个有返回值的任务。
---

# 第 31 章：任务管理：TaskGroup 与有界关闭

[全书目录](./index.md) · [上一章](./live-node.md) · [下一章](./live-clock.md)

::: tip 本章学习目标
能说出直接 `get_runtime().spawn` 留下的三个问题；能解释 `TaskGroup` 的“先登记后运行”和“代”各解决什么问题；能按时间线说出 `begin_shutdown` 和 `finish_shutdown` 的两段取消、两个期限，以及超时后的状态；会用 `TaskSpawner` 让任务派生子任务；知道什么时候用 `TaskSlot` 而不是 `TaskGroup`。

**源码版本：** `develop` 分支，提交 `364254f`（2026-11-18）。任务组在 `crates/live/src/task.rs`，更底层的句柄容器 `TaskHandles` 在 `crates/common/src/live/task.rs`，OKX 适配器的用法在 `crates/adapters/okx/src/common/task.rs` 和 `websocket/client.rs`。

**对应官方文档：** [Adapters 开发指南](https://nautilustrader.io/docs/latest/developer_guide/adapters/)（Task management 一节，中文译文见第 38 章）
:::

第 29 章说适配器要用 `get_runtime().spawn`，不要用 `tokio::spawn`。但这只是第一步。一个 WebSocket 客户端连接后会 spawn 好几个后台任务：读消息、发心跳、处理重连、执行下单请求。断开时，这些任务必须全部停下来，而且要在有限的时间内停下来，否则节点关不掉，或者下次连接时新旧任务同时在跑。这一章看 NautilusTrader 怎样管理这些任务。

主线例子：OKX 的 WebSocket 客户端。它把消息处理任务放在一个 `TaskGroup` 里，断开时调用 `terminate_tasks`：先优雅取消，等 1 秒，再强制取消，再等 2 秒。

## 1. 直接 spawn 的问题 {#problem}

`get_runtime().spawn(future)` 返回一个 `JoinHandle`。如果随手丢掉它，会有三个问题：

- **停不下来。** 没有句柄，就没法取消它；它可能在节点关闭后还在发请求。
- **不知道是否停了。** 即使发了取消信号，也不知道任务什么时候真正结束；关闭流程只能盲目地等，或者干脆不等。
- **新旧混在一起。** 断线重连时，旧连接的任务还没结束，新连接的任务已经开始，两边同时处理消息。

还有一个隐蔽的竞态：关闭流程正在收集“所有任务”时，另一个线程恰好 spawn 了一个新任务。如果新任务先跑起来、后被登记，关闭流程就可能漏掉它。

## 2. TaskGroup：先登记，后运行 {#group}

`TaskGroup` 持有一组输出为 `()` 的任务。它的 `spawn` 做两步：

1. 在一个互斥锁内检查当前是否允许加入新任务（组是否“开放”）；允许的话，从任务跟踪器（`tokio_util` 的 `TaskTracker`）领一个令牌，完成登记；不允许就返回 `TaskSpawnError`，并丢弃这个 future。
2. 登记成功后，才把一个包装过的 future 交给运行时：

```rust
// 节选自 crates/live/src/task.rs（spawn_registered，有删节）
spawn(async move {
    let result = AssertUnwindSafe(async move {
        tokio::select! {
            biased;
            () = force.cancelled() => {}     // 强制取消：直接丢弃用户的 future
            () = future => {}
        }
    })
    .catch_unwind()                          // 捕获 panic
    .await;
    registration.complete(result.err());     // 归还令牌，记录 panic
});
```

因为登记在运行之前，关闭流程只要关上“开放”这扇门，就能确定此后不会有新任务漏进来，而门关上之前登记的任务都在跟踪器里。包装还做了两件事：用 `catch_unwind` 把任务里的 panic 记成一条失败信息，而不是让它悄悄消失；如果登记对象在任务没有正常结束、也没有被强制取消的情况下被丢弃（比如运行时被外部中止），记一条“被意外取消”。

`spawn_named(name, future)` 还会返回一个只读的 `TaskRef`，带有名字、唯一 ID 和“是否已结束”的状态，失败信息里也会带上名字，方便排查是哪个任务出了问题。它不转移所有权：取消和等待仍然只能由组来做。

**任务派生子任务。** 一个长期运行的任务（比如消息处理循环）可能需要再 spawn 子任务。它不能持有 `TaskGroup` 本身，而是从组里取一个 `TaskSpawner`。`TaskSpawner` 绑定在取出它时的那一“代”上，子任务登记进同一代。

## 3. 代：隔离一次连接和下一次连接 {#generation}

`TaskGroup` 内部不是直接存任务，而是存一个“当前代”（`TaskGeneration`）。每一代有自己的任务跟踪器、两个取消令牌（优雅和强制）、一个状态和一组失败记录。状态只有三种：

| 状态 | 含义 |
| --- | --- |
| `Open` | 接受新任务 |
| `Closing` | 已开始关闭，拒绝新任务，正在收尾 |
| `Drained` | 所有任务都已结束 |

`start_generation()` 只有在当前代是 `Drained` 且没有剩余任务时才会成功，它用一个全新的代替换当前代。这样一次断线重连就变成：关闭旧的一代，等它排空，再打开新的一代。旧一代的 `TaskSpawner` 被某个迟到的旧任务拿着也没关系，它只能往已经关闭的旧一代里登记，会被拒绝，永远进不了新一代。

## 4. 两段关闭，两个期限 {#shutdown}

关闭分成同步的开始和异步的收尾，因为它们发生在不同的地方：组件的 `stop`、`reset`、`dispose` 是同步方法，不能 `await`；而 `disconnect` 是异步的。

**`begin_shutdown()`**（同步）：把当前代设为 `Closing`，关闭跟踪器，触发**优雅取消令牌**。它不等待任何东西，可以在同步方法里放心调用，重复调用也没关系。

**`finish_shutdown(优雅期限, 强制期限)`**（异步）：

1. 当前代还是 `Open` 时直接返回 `StillOpen` 错误，必须先 `begin_shutdown`；
2. 在优雅期限内等所有任务结束；全部结束就把代设为 `Drained`，返回成功（如果期间有任务 panic，返回 `Join` 错误，带上失败信息）；
3. 优雅期限到了还有任务，触发**强制取消令牌**：包装里的 `select!` 立刻丢弃用户的 future；
4. 在强制期限内再等一次；还有任务没结束（比如用户的 future 卡在一个不响应取消的同步调用里），返回 `Timeout` 错误，带上剩余任务数。

两个令牌的区别很重要。优雅取消只是一个信号，任务要自己监听它，在合适的时候退出，比如先把手头的消息处理完、给交易所发一个干净的关闭帧。强制取消不需要任务配合，直接丢弃 future，代价是任务可能停在任意一个 `.await` 点上。

超时以后，这一代**保持 `Closing`**，剩余任务仍然被组持有。调用方可以稍后再调用一次 `finish_shutdown` 继续等，而不是把它们分离出去不管。`start_generation` 在这之前不会成功，所以新连接不会和没收尾的旧任务同时存在。

`TaskGroup` 被丢弃时会触发强制取消，但不能等待任务结束。需要确认任务已经停下的组件，必须显式调用 `finish_shutdown`。

主线例子里，OKX 的封装是：

```rust
// 节选自 crates/adapters/okx/src/common/task.rs
pub(crate) fn spawn_task<F>(tasks: &TaskSpawner, fut: F)
where F: Future<Output = ()> + Send + 'static {
    let cancel = tasks.cancellation_token();                 // 优雅取消令牌
    if let Err(e) = tasks.spawn(async move {
        tokio::select! { biased; () = cancel.cancelled() => {} () = fut => {} }
    }) {
        log::debug!("Skipping task spawn after OKX shutdown began: {e}");
    }
}

pub(crate) async fn terminate_tasks(tasks: &TaskGroup, owner: &str) -> anyhow::Result<()> {
    tasks.begin_shutdown();
    tasks.finish_shutdown(Duration::from_secs(1), Duration::from_secs(2)).await
        .map_err(|e| anyhow::anyhow!("Failed to terminate {owner} tasks: {e}"))?;
    Ok(())
}
```

断开时的时间线：第 0 秒关门并发出优雅取消，每个任务的 `select!` 看到 `cancel.cancelled()` 后退出；第 1 秒还没退出的，被强制丢弃；第 3 秒还没结束的，以 `Timeout` 报错，OKX 客户端把错误向上返回。

![TaskGroup 的一代任务：开放时 spawn 先登记再运行；begin_shutdown 关门并发出优雅取消；finish_shutdown 先在优雅期限内等待，再发出强制取消并在强制期限内等待；全部结束则进入 Drained，可以 start_generation 开新的一代；超时则保持 Closing 并保留剩余任务](/nautilus-trader/figures/task-group.svg)

怎么读这张图：上面一行是一代任务的三个状态，箭头上写着触发它的调用；下面是 `finish_shutdown` 的时间轴，两个期限首尾相接。注意从 `Closing` 回到 `Open` 的路只有一条：先排空到 `Drained`，再开新的一代。

## 5. 半途失败的回滚 {#guard}

`connect` 可能在建好一部分东西之后失败，比如 WebSocket 连上了、心跳任务也 spawn 了，但订阅认证失败。`TaskGroupGuard::new(&[&group1, &group2], rollback)` 在作用域结束时，如果没有被 `disarm()`，就关闭这些组并执行一个同步的回滚回调。设置成功后调用 `disarm()`。注意它只做同步部分，异步的 `finish_shutdown` 仍然要由调用方在返回错误前完成。

## 6. 单个有结果的任务：TaskSlot {#slot}

`TaskGroup` 只装输出为 `()` 的任务。有些任务的结果很重要，比如一个启动握手任务返回连接参数，一个下单任务返回交易所的确认。把它的 `JoinHandle<T>` 塞进组里就丢掉了结果。这时用：

- **`TaskSlot<T>`**：持有一个任务，保留输出类型 `T`；
- **`SharedTaskSlot<T>`**：同上，供多个克隆共享同一个任务的客户端使用，并保证并发的收尾请求是串行的；
- **`finish_task(slot, 优雅期限, 强制期限)`**：两段有界等待，但没有优雅取消信号：先等优雅期限，到期直接中止任务，再等强制期限。返回 `TaskJoinOutcome`：`Completed(T)`（正常完成，带结果）、`Aborted`（被强制中止）、`Failed`（panic 或连接错误）、`Incomplete`（中止后仍未结束，任务留在槽里）。第 7 节的实验分别得到了其中三种。

更底层的 `TaskHandles`（`crates/common`）只是一个装 `JoinHandle<()>` 的容器，提供 `abort_all`、`take_all` 等方法，不规定任何关闭策略，给需要自己定义策略的组件用。

## 7. 动手验证 {#lab}

把第 4 节的时间线放到秒表下面看。实验用和 OKX 一样的期限（优雅 1 秒、强制 2 秒），分别关闭三种任务：会听优雅取消的、不听但会在 `.await` 处让出的、卡在同步调用里的。

::: info 实验环境
Linux（aarch64，4 核、3 GB 内存）上的 Rust 1.100.0，NautilusTrader 各 crate 来自提交 `364254f`。代码是 <a href="/nautilus-trader/code/live-lab/examples/ch31_task_group.rs" download><code>ch31_task_group.rs</code></a>，属于第五部分的实验工程 `live-lab`（[在 GitHub 查看](https://github.com/lewislau86/lewislau86.github.io/tree/master/docs/public/nautilus-trader/code/live-lab)，`README.md` 写了运行方法）。运行命令是 `cargo run --example ch31_task_group`。下面的输出原样摘录，毫秒数每次运行略有不同。
:::

<<< @/public/nautilus-trader/code/live-lab/examples/ch31_task_group.rs#shutdown

<<< @/public/nautilus-trader/code/live-lab/examples/ch31_task_group.rs#cases

```text
cooperative     finish_shutdown after    206 ms -> Ok(()); task finished = true
ignores-cancel  finish_shutdown after   1012 ms -> Ok(()); task finished = true
blocking        finish_shutdown after   3011 ms -> Err("task shutdown timed out with 1 task(s) still owned"); task finished = false
after timeout: len = 1, start_generation -> Err("prior task group generation has not fully drained")
second finish_shutdown -> Ok(()); start_generation -> Ok(())
```

三种任务正好落在时间线的三个位置：

- 会配合的任务收到优雅取消后清理 200 毫秒退出，`finish_shutdown` 在约 0.2 秒返回成功。
- 不听优雅取消的任务等满 1 秒的优雅期限，被强制取消在 `.await` 处丢弃，约 1.0 秒返回成功。所以强制取消并不算错误，`finish_shutdown` 的结果仍是 `Ok`。
- 卡在 `std::thread::sleep` 里的任务连强制取消也丢不掉，在 1 + 2 = 3 秒时返回 `Timeout`，组里还留着 1 个任务，`start_generation` 被拒绝。等它自己睡醒（5 秒）后再调用一次 `finish_shutdown`，这一代才排空，新的一代才能打开。

准入、代和 panic：

<<< @/public/nautilus-trader/code/live-lab/examples/ch31_task_group.rs#admission

<<< @/public/nautilus-trader/code/live-lab/examples/ch31_task_group.rs#panic

```text
finish_shutdown while open -> Err("task group admission is still open")
spawn after begin_shutdown -> Err("task group admission is closed")
new generation open = true; old spawner.spawn -> Err("task group admission is closed"); group.spawn -> Ok(())
panicking task -> Err("task shutdown observed join failures: task 'reader' (4) panicked: bad frame")
```

没有 `begin_shutdown` 就 `finish_shutdown` 会得到 `StillOpen`；关门之后的 `spawn` 被拒绝；新的一代打开后，旧一代取出的 `TaskSpawner` 仍然进不去，组本身可以正常 `spawn`。panic 被包装层捕获，在关闭时作为 `Join` 错误报告出来，带着任务名 `reader` 和 panic 信息。

最后是 `TaskSlot` 和 `finish_task`：

<<< @/public/nautilus-trader/code/live-lab/examples/ch31_task_group.rs#slot

```text
slot, returns 42 -> Completed(42)
after  112 ms: slot, sleeps 60 s -> Aborted
slot, blocks 500 ms -> Incomplete
same slot, asked again -> Completed(0)
```

`finish_task` 和 `finish_shutdown` 有一点不同：它没有优雅取消信号可发，只是先等优雅期限，到期就直接中止任务，再等强制期限。所以睡 60 秒的任务在约 0.1 秒时得到 `Aborted`。同步阻塞的任务中止不掉，得到 `Incomplete`，任务仍留在槽里；过一会儿再问一次，它已经自己跑完，结果是 `Completed(0)`。中止请求只能在 `.await` 处生效，任务在那之前就返回了，返回值照样交回来。

::: warning 常见误区
- **在同步的 `stop()` 里 `await` 任务结束。** 同步方法只调用 `begin_shutdown`，等待放到异步的 `disconnect` 里。
- **以为 `begin_shutdown` 会让任务立刻停止。** 它只发出优雅取消信号，任务要自己监听 `cancellation_token()`。
- **以为强制期限一过任务就一定被清掉了。** 卡在同步阻塞调用里的任务丢不掉，组会返回 `Timeout` 并继续持有它。
- **超时后直接 `start_generation` 开始新连接。** 会失败，必须先把旧的一代排空。
- **任务里捕获了 `RefCell` 借用或缓存的引用。** 后台任务会比方法调用活得久，只能捕获克隆好的、自己拥有的数据。
- **把有返回值的任务放进 `TaskGroup`。** 结果会丢失，用 `TaskSlot`。
:::

## 本章结论

`TaskGroup` 让后台任务始终有一个所有者：`spawn` 先在锁内登记、再交给运行时，所以关闭时不会漏掉任务；包装层捕获 panic 和意外取消并记录下来。任务按“代”组织，`start_generation` 只在上一代完全排空后才能打开新的一代，避免新旧连接的任务同时存在。关闭分两段：同步的 `begin_shutdown` 关门并发出优雅取消，异步的 `finish_shutdown` 先在优雅期限内等待、再强制取消并在第二个期限内等待，超时则保留剩余任务和关闭状态。有返回值的单个任务用 `TaskSlot` 和 `finish_task`，同样是两段有界的等待。

## 检查理解

1. 一个任务在 `begin_shutdown` 之后、`finish_shutdown` 之前调用了 `TaskSpawner::spawn`。会发生什么？如果它在 `start_generation` 之后用的还是旧的 `TaskSpawner` 呢？

   <details><summary>参考答案</summary>

   两种情况都返回 `TaskSpawnError`，future 被丢弃。第一种是因为当前代已经是 `Closing`，不再接受新任务。第二种是因为 `TaskSpawner` 绑定在取出它时的那一代上，旧一代已经关闭，即使组已经打开了新的一代，旧的 spawner 也进不去。

   </details>

2. 一个 WebSocket 读任务里有一行同步的 `std::thread::sleep(Duration::from_secs(30))`。用 `finish_shutdown(1 秒, 2 秒)` 关闭时会怎样？

   <details><summary>参考答案</summary>

   优雅取消令牌被触发，但任务卡在同步的 `sleep` 里，没机会检查令牌。1 秒后强制取消令牌被触发，包装层的 `select!` 也要等任务回到一个 `.await` 点才能丢弃它，同样做不到。再过 2 秒，`finish_shutdown` 返回 `Timeout`，剩余任务数为 1；这一代保持 `Closing`，任务仍归组所有。真正的问题是在异步任务里做了阻塞调用，要改成 `tokio::time::sleep`，或者用 `spawn_blocking`。

   </details>

3. 一个下单任务返回交易所给的场所订单 ID，客户端需要在断开前确认它是否成功。应该用什么来管理这个任务？

   <details><summary>参考答案</summary>

   用 `TaskSlot<anyhow::Result<VenueOrderId>>`，断开时调用 `finish_task`。返回 `Completed(Ok(id))` 表示成功拿到 ID；`Failed` 表示任务 panic；`Aborted` 表示被取消；`Incomplete` 表示超时仍未结束，结果未知。后两种情况下，这张单的结果要交给对账确认（第 34 章）。放进 `TaskGroup` 的话，结果会被丢弃，只能知道“任务结束了”。

   </details>

## 参考资料

- 官方文档：[Adapters 开发指南](https://nautilustrader.io/docs/latest/developer_guide/adapters/)（Task management）
- 源码：[`crates/live/src/task.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/live/src/task.rs) · [`crates/common/src/live/task.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/common/src/live/task.rs) · [`crates/adapters/okx/src/common/task.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/adapters/okx/src/common/task.rs)
- 实验代码：[`live-lab`](https://github.com/lewislau86/lewislau86.github.io/tree/master/docs/public/nautilus-trader/code/live-lab) 的 `examples/ch31_task_group.rs`
- 配图由 `scripts/generate-nautilus-trader-figures.py` 生成。

实时计时器也是 Tokio 上的任务，它们到点后怎样把事件送回核心线程？下一章看 `LiveClock`。[第 32 章：LiveClock 与实时计时器](./live-clock.md)。
