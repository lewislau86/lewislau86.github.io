---
editLink: false
---

# 10 如何停机与验证行为

[上一章](/mini-redis/09-clients.md) · [目录](/mini-redis/index.md) · [下一章](/mini-redis/11-real-redis.md)

本章对应的独立源码文章：[src/server.rs](/mini-redis/source/src/server.md)、[src/shutdown.rs](/mini-redis/source/src/shutdown.md)、[src/db.rs](/mini-redis/source/src/db.md)、[tests/client.rs](/mini-redis/source/tests/client.md)、[tests/server.rs](/mini-redis/source/tests/server.md)、[tests/buffered_client.rs](/mini-redis/source/tests/buffered_client.md)、[tests/frame_validation.rs](/mini-redis/source/tests/frame_validation.md)。完整的一一对应关系见 [源码文章索引](/mini-redis/source/index.md)。

结束进程当然可以让一切停止，但一个可理解的服务器应该回答三个问题：什么时候不再接收新工作，现有任务怎么知道要停，主流程又如何确认它们都停了？

## 从资源的创建点追到释放点

```text
server::run 创建两组通道
  notify_shutdown Sender ────── 只有 Listener 持有
                    Receiver ─ 每个 Handler 的 Shutdown 持有
  shutdown_complete_tx ──────── Listener 持有原发送端
                    clone ──── 每个 Handler 的 _shutdown_complete 持有
  shutdown_complete_rx ──────── server::run 保留并等待
```

[第 05 章](/mini-redis/05-tokio-server.md)的 Handler 构造代码是这张关系图的创建现场。本章倒过来看：谁释放哪个句柄，会唤醒哪个等待者。这里没有专门的“Handler 完成后调用主服务回调”，关闭通道本身承担了通知。

停止来源由 server binary 的 `signal::ctrl_c()` 或实验传入的 Future 提供；单个客户端断开只结束自己的 Handler，不等于触发整个服务的 shutdown Future。

## 退出通知与完成等待是两条通道

[server::run](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/mini-redis/source/src/server.rs) 接收一个 `shutdown: impl Future`。binary 传入 `signal::ctrl_c()`，实验可以传入 oneshot Receiver。服务器不必知道“停止”来自键盘、测试还是另一个控制组件。

外层 select 在 Listener 循环与 shutdown Future 之间等待。触发退出后，代码 drop `notify_shutdown`：这份 broadcast Sender 没有被 Handler 克隆，所有 Handler 只持有 Receiver，所以发送端关闭会唤醒它们。

[Shutdown::recv](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/mini-redis/source/src/shutdown.rs) 不检查 recv 的具体结果，而是在返回后设置 `is_shutdown = true`。也就是说，服务器不是必须先广播一条 `()` 消息；关闭通道本身就是信号。

另一条 mpsc 通道承担“所有 Handler 都结束了”的计数作用。每个 Handler 持有 `_shutdown_complete` Sender，没人实际发送完成消息。主流程释放自己的 Sender 后，等 `shutdown_complete_rx.recv().await`；当所有 Handler 释放自己的 Sender，接收端返回 None，等待结束。

```text
Ctrl+C / 自定义 shutdown Future 完成
  → 退出接入循环，不再创建新 Handler
  → drop broadcast Sender，通知每个 Handler
  → Handler 返回，释放各自的 mpsc Sender 和连接配额
  → 最后一个 mpsc Sender 消失
  → 主流程的 recv 得到 None，server::run 可以结束
```

对照 [server::run](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/mini-redis/source/src/server.rs) 在外层 select 结束后的源码：

<!-- source: src/server.rs:94-109; comments included -->
```rust
// 解构并移出两个 Sender，.. 忽略其余字段。
// 显式释放本地 Sender，避免下面把自己也算作尚未完成的持有者而一直等待。
let Listener {
    shutdown_complete_tx,
    notify_shutdown,
    ..
} = server;

// 关闭广播，所有现有 Receiver 的 recv 将完成并触发各连接停止。
drop(notify_shutdown);
// 释放接入方的完成 Sender，剩余克隆由 Handler 持有。
drop(shutdown_complete_tx);

// 等待所有 Handler 释放完成 Sender，随后 recv 返回 None。
// 这不包含显式 join 过期清理任务，后者由 DbDropGuard 另行通知。
let _ = shutdown_complete_rx.recv().await;
```

`drop(notify_shutdown)` 使 Receiver 结束等待，而非逐个调用 Handler；`drop(shutdown_complete_tx)` 排除主流程自己对“还有任务没完”的占用；最后 recv 才能以 None 观察所有连接任务已经释放发送端。`..` 不是在这里显式等待或 join 所有其他字段，不能把部分字段解构当作数据库后台任务已经退出的证据。

接收一侧的 [Shutdown::recv](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/mini-redis/source/src/shutdown.rs) 是：

<!-- source: src/shutdown.rs:31-43; comments included -->
```rust
pub(crate) async fn recv(&mut self) {
    // 已观察到停止就直接返回，避免重复等待。
    if self.is_shutdown {
        return;
    }

    // 故意忽略 recv 的 Result：收到值或通道关闭都按停止处理。
    // 当前服务通过关闭发送端通知，不依赖发送一条 ()。
    let _ = self.notify.recv().await;

    // 记录停止状态，供 Handler 循环的下一次判断使用。
    self.is_shutdown = true;
}
```

直接调用它的是 Handler::run 的读帧 select，以及 Subscribe::apply 的事件 select。第一次完成时设置标记；后续调用看到标记直接返回。这里不区分收到消息还是发送端关闭，因为两者对当前设计都表示该停止了。

返回之后，普通 Handler 的停机分支 `return Ok(())` 会回到 spawn 闭包；闭包结束时 Handler 被释放，它持有的 `_shutdown_complete` 才真正减少一个发送端。仅仅把 is_shutdown 改成 true，并不会自动销毁 socket。


如果误把一个完成 Sender 留在某个长期存活对象里，即使所有真正工作都已结束，等待仍不会完成。所有权在这里同时承担了生命周期记账。

## 数据库后台任务单独收尾

[DbDropGuard::drop](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/mini-redis/source/src/db.rs) 调用 `shutdown_purge_task`：置 State.shutdown 为 true，释放锁，再 Notify。清理任务下次检查状态后退出。

Db 与 DbDropGuard 不一样：Db 会被每个连接 clone；DbDropGuard 由 Listener 持有，负责管理后台任务停止。不能让任意一个连接的 Db 析构就停掉整台服务器的清理任务。

源码没有保存清理任务的 JoinHandle 并显式 await 它。因此要区分：连接任务通过 mpsc 生命周期等待；清理任务收到退出请求，但并不在同一条完成确认通道中。Drop 也是同步方法，不能在其中直接 await。

把数据库停止路径也追到实际代码。触发方是 [DbDropGuard 的 Drop 实现](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/mini-redis/source/src/db.rs)：

<!-- source: src/db.rs:78-83; comments included -->
```rust
impl Drop for DbDropGuard {
    fn drop(&mut self) {
        // Drop 只能同步通知；此处不能 await 后台任务完成。
        self.db.shutdown_purge_task();
    }
}
```

被调用的 [Db::shutdown_purge_task](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/mini-redis/source/src/db.rs) 负责更新状态并唤醒：

<!-- source: src/db.rs:200-208; comments included -->
```rust
fn shutdown_purge_task(&self) {
    // 先在锁内更新真实状态，再发通知；Notify 自身不保存 shutdown 布尔值。
    let mut state = self.shared.state.lock().unwrap();
    state.shutdown = true;

    // 先解锁再通知，降低唤醒后的无谓争锁。
    drop(state);
    self.shared.background_task.notify_one();
}
```

接收方是第 07 章的 purge_expired_tasks；它重新检查 shared.is_shutdown 后退出。若只设标记而不 Notify，没有待过期键、正等通知的后台任务可能没有机会重新检查。若每个 Db clone 的析构都执行这段逻辑，则一个客户端离开就可能影响其他连接的过期清理，因此生命周期责任放在 DbDropGuard 上。

| 修改或故障 | 直接停在哪个等待点 | 对整台服务的影响 |
| --- | --- | --- |
| 多留一个 notify_shutdown Sender | 空闲 Handler 的 shutdown.recv 不会因发送端归零而醒来 | 主流程可能继续等它释放完成句柄 |
| 主流程没释放 shutdown_complete_tx | shutdown_complete_rx.recv 无法以关闭结束 | 所有 Handler 已退出也可能仍等不到完成 |
| 一个 Handler 卡在响应写入 | 尚未返回外层循环/闭包 | 它的完成 Sender 仍存活，整体停机等待被拖住 |
| 仅停一个客户端连接 | 只释放该 Handler 的资源 | 配额归还，其他连接与后台清理继续 |
| 后台清理收到停止请求 | 清理任务将检查状态退出 | 没有 JoinHandle 等待，不能据此宣称退出已被确认 |

这张表把“代码放在哪一层”的影响具体化：连接任务卡住会拖延协调停机；连接级普通错误不会直接结束接入循环；清理任务的生命周期确认又是另一条路径。


## 优雅不意味着任何情况下都限时结束

普通请求的 apply 位于读帧 select 之后，因此已经执行到写响应的任务会先尝试完成写入，再返回循环检查停止。一个迟迟不读取响应的客户端可能让写入等待很久。本实现没有统一的停机 deadline 或超时强制中断策略。

订阅命令在自己的循环中监听停机，但写某条推送响应时同样可能正在 await。不能把“有 shutdown 分支”理解为“任意 await 都可立刻打断”。网络写取消还可能留下部分帧，因此生产设计需要明确退出与数据完整性的取舍。

配套实验给整个场景和退出等待加 timeout，目的是让实验失败时给出结果；这没有改变服务器本身的停机保证。

## 测试从什么边界观察

| 现有测试文件 | 主要观察边界 |
| --- | --- |
| [tests/frame_validation.rs](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/mini-redis/source/tests/frame_validation.rs) | 给帧检查器非法负 Bulk 长度，验证错误类型 |
| [tests/server.rs](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/mini-redis/source/tests/server.rs) | 直接通过 TCP 写 RESP，核对响应字节 |
| [tests/client.rs](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/mini-redis/source/tests/client.rs) | Client 的 Set/Get/Ping/订阅接口 |
| [tests/buffered_client.rs](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/mini-redis/source/tests/buffered_client.rs) | BufferedClient 的排队读写 |

字节测试可发现编码问题，客户端测试验证用户看到的返回值。两者互补：如果客户端与服务器以同样的错误方式理解协议，只有端到端成功不够证明兼容性。

根目录执行：

```sh
cargo test --locked
```

本机本次验证中，这条命令在 `server::key_value_timeout` 长时间未完成；单独运行该测试 20 秒也超时。这里的测试名称是集成测试函数，命令中应使用 `--test server key_value_timeout`；不是 Rust 模块的完整路径。其余测试与文档测试可用下面的过滤方式验证：

```sh
cargo test --locked -- --skip key_value_timeout
```

详细结果见 [验证记录](/mini-redis/validation.md)。跳过后通过并不意味着原始全套测试通过，也没有证明挂起原因已定位。

## 虚拟时间为何仍需要任务调度

`key_value_timeout` 使用 `tokio::time::pause()` 暂停时间，然后 `advance(Duration::from_secs(1)).await` 推进计时。这样通常能避免真实等待一秒，让测试更快。

但“计时器已经到点”与“处理计时器的任务已经执行完删除”不是同一件事。还需让清理任务被调度，并在测试中定义可观察的完成条件；同时真实 socket I/O 并不会因暂停 Tokio 时间而变成完全受控的虚拟事件。这些是诊断方向，不能在没有证据时据此认定本次挂起的根因。

设计自己的过期测试时，可以把纯时间逻辑放进受控单元测试，网络测试则验证端到端结果并设总超时。避免把固定 sleep 当成所有环境下都可靠的同步方式，也避免在没有上界的循环中一直等待。

## 让日志解释一次请求

`RUST_LOG=debug` 会显示 tracing 记录。`#[instrument(skip(...))]` 为函数调用创建 span，`debug!(?cmd)` 用 Debug 格式记录命令，`error!(cause = ?err, ...)` 记录失败原因。日志可以帮助定位到“接受连接、解析命令、发送响应”的哪一层，但一条“开始处理”日志并不代表处理成功。

为什么完成通道容量只有 1，却能等待很多 Handler？

<details>
<summary>参考答案</summary>

这条通道没有实际排队发送消息，使用的是“所有 Sender 都已释放”这一关闭条件。容量不是并发任务计数上限，Sender 的存活数量才是这里的记账机制。

</details>
