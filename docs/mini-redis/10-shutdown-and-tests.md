---
editLink: false
---

# 10 如何停机与验证行为

[上一章](/mini-redis/09-clients.md) · [目录](/mini-redis/index.md) · [下一章](/mini-redis/11-real-redis.md)

结束进程当然可以让一切停止，但一个可理解的服务器应该回答三个问题：什么时候不再接收新工作，现有任务怎么知道要停，主流程又如何确认它们都停了？

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

如果误把一个完成 Sender 留在某个长期存活对象里，即使所有真正工作都已结束，等待仍不会完成。所有权在这里同时承担了生命周期记账。

## 数据库后台任务单独收尾

[DbDropGuard::drop](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/mini-redis/source/src/db.rs) 调用 `shutdown_purge_task`：置 State.shutdown 为 true，释放锁，再 Notify。清理任务下次检查状态后退出。

Db 与 DbDropGuard 不一样：Db 会被每个连接 clone；DbDropGuard 由 Listener 持有，负责管理后台任务停止。不能让任意一个连接的 Db 析构就停掉整台服务器的清理任务。

源码没有保存清理任务的 JoinHandle 并显式 await 它。因此要区分：连接任务通过 mpsc 生命周期等待；清理任务收到退出请求，但并不在同一条完成确认通道中。Drop 也是同步方法，不能在其中直接 await。

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
