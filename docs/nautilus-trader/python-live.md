---
title: "第 42 章：在 Python 里跑实盘"
description: 从 Python 运行实盘节点：用 LiveNode.builder 加官方适配器的工厂和配置、加内置的 Rust 策略；run() 占住调用线程并接管 SIGINT 和 SIGTERM，run_async() 把节点托管在已有的 asyncio 循环上，运行期间节点被借出、只能用事先取好的 cache 和 handle；停止、取消与 dispose 的规则；一个进程只能有一个节点，换节点要先释放旧节点的引用。
---

# 第 42 章：在 Python 里跑实盘

[全书目录](./index.md) · [上一章](./python-backtest.md) · [下一章](./python-adapter.md)

::: tip 本章学习目标
会用 Python 组装一个实盘节点：加数据和执行客户端、加 Python 组件或内置的 Rust 组件；能说出 `run()` 和 `run_async()` 各自占用什么、谁处理信号、怎样停止、运行期间能访问什么；知道 `dispose()` 什么时候生效；知道为什么一个进程只能有一个节点，以及换节点的正确写法；知道把节点托管在 ASGI 应用里时的几条限制。

**源码版本：** `develop` 分支，提交 `364254f`（2026-11-18）。Python 版节点在 `crates/live/src/python/node.rs`（构建器、`run`、`run_async`、内置组件的注册表），运行时的桥接在 `crates/live/src/python/runtime.rs`。

**对应官方文档：** [Live Trading](https://nautilustrader.io/docs/latest/concepts/live/)（Live node lifecycle、Hosted event loops 两节） · [Python](https://nautilustrader.io/docs/latest/concepts/python/)（Async execution 一节）
:::

第 30 章从 Rust 讲了实盘节点：核心线程上的事件循环、启动和停止的顺序。第 29 章讲了 Python 节点的线程：`run()` 先释放 GIL，再在调用它的线程上驱动节点。这一章看 Python 用户直接面对的部分：节点怎样组装，两种运行方式的区别，以及几条只有在 Python 里才会遇到的生命周期规则。

主线例子：一个 Python 服务，既要运行交易节点，又要用 ASGI 框架提供一个查看持仓的网页。

## 1. 组装节点 {#build}

官方示例的写法都是构建器：

```python
# 节选自 examples/live/okx/data_tester.py
node = (
    LiveNode.builder("OKX-DATA-TESTER-001", TRADER_ID, Environment.LIVE)
    .add_data_client(None, OKXDataClientFactory(),
                     OKXDataClientConfig(instrument_types=[OKXInstrumentType.SWAP],
                                         environment=OKXEnvironment.LIVE))
    .build()
)
node.add_builtin_actor("DataTester", DataTesterConfig(...))
node.run()
```

三点说明：

- **客户端是 Rust 的。** 官方适配器在 Rust 里实现，Python 拿到的是它们的配置类和工厂（第 38 章附录 C 的路线 A）。构建器的 `with_*` 方法设置节点的各项配置（对账、宽限期、缓存、消息总线、日志），和第 30 章的 `LiveNodeConfig` 一一对应。
- **组件可以是 Python 的，也可以是内置的 Rust 组件。** `add_strategy`、`add_actor` 加 Python 组件（第 39、40 章）；`add_builtin_strategy("EmaCross", config)`、`add_builtin_actor("DataTester", config)` 加仓库里编进扩展模块的 Rust 示例组件，回调不经过 Python。这个列表是固定的：`EmaCross`、`ExecTester`、`GridMarketMaker`、`OrderBookImbalance` 等几个，自己写的 Rust 策略不能这样加，要编进扩展模块，或者整个节点用 Rust 写（第 9 章）。
- **自定义的 Python 适配器另有一套。** 用 Python 写的数据和执行客户端走 `nautilus_trader.live.clients` 的基类，通过 `LiveNode.build(..., data_factories=..., exec_factories=...)` 注册，下一章细讲。

## 2. 两种运行方式 {#modes}

![Python 里跑实盘节点的两种模式：run() 占用调用它的线程并处理信号，run_async() 托管在宿主的 asyncio 循环上、信号归宿主，运行中只能用事先取好的 cache 和 portfolio；两者有同样的生命周期，一个进程只能有一个节点](/nautilus-trader/figures/python-live-modes.svg)

怎么读这张图：每一行是一个问题，两列分别是两种运行方式的答案；底部是两者共同的规则。

**`run()`：节点拥有线程。** 调用后一直阻塞，直到节点完整关闭。节点安装 `SIGINT` 和 `SIGTERM` 的处理函数，所以在终端里按 Ctrl-C，或者进程收到 `SIGTERM`，节点会走正常的关闭流程（停 Trader、宽限期、断开客户端，第 30 章第 5 节），然后 `run()` **正常返回**，不会在 Python 里抛 `KeyboardInterrupt`。要从程序里停止，在别的线程调用 `node.handle().stop()`。

**`run_async()`：节点托管在你的循环上。** 它返回一个协程，你把它放进已有的 asyncio 循环（官方测试过默认循环和 uvloop，也可以放在 Uvicorn 管理的 ASGI 生命周期里）。两种方式跑的是同一套生命周期：启动顺序、维护计时器、对账、关闭都一样；区别只在于谁拥有线程和信号：

- **信号归宿主。** 托管模式下节点不安装任何信号处理函数，Ctrl-C 由宿主应用决定怎么办。
- **节点在运行期间被借给协程。** 运行时通过节点对象读状态（`node.cache` 等）会抛 `RuntimeError`，错误信息直接告诉你该怎么做：用运行前取好的 `cache`、`portfolio` 和 `handle()`。这些对象在运行期间一直可用。
- **定期让出。** 运行期间节点会定期把控制权还给宿主循环，一阵密集的事件不会饿死宿主自己的任务；但启动和关闭阶段要一次性处理完积压的队列，不让出，所以大量品种加载或关闭时的积压会占住循环一段时间。
- **不支持数据库后端的缓存。** 这类后端等待自己的后台任务时会阻塞调用线程，放在宿主循环上就是阻塞整个循环，所以节点会拒绝；用 Python 写的自定义客户端在两种模式下都要驱动 asyncio，也都不支持。

## 3. 停止、取消与 dispose {#stop}

托管模式下，官方文档给出的服务生命周期是：

1. 启动前取好 `cache`、`portfolio`、`handle()`；
2. `asyncio.create_task(node.run_async())`，等到 `handle.is_running` 为真再报告启动完成，期间检查任务是否已经失败；
3. 服务运行期间监督这个任务，它意外结束就当作服务失败；
4. 停止时调用 `handle.stop()`，再 `await` 任务；
5. 任务结束后调用 `node.dispose()`。

几条细节：

- **`handle.stop()` 立即返回。** 它只是请求关闭，`await` 任务才是等关闭完成。`LiveNodeHandle` 可以从任何线程调用，包括信号处理函数。实验里 `stop()` 之后约 90 毫秒 `on_stop` 被调用（第 30 章的停止检查每 100 毫秒一次）。
- **取消任务等于请求关闭。** `task.cancel()` 会触发同样的正常关闭，等关闭完成后再把 `CancelledError` 抛给等待者，所以 `asyncio.timeout` 和任务组的语义不变。
- **运行中调用 `dispose()` 什么也不做。** 它不会被推迟执行，任务结束后要再调用一次。
- **关闭时还有结果未知的提交**（第 34 章），`await` 会抛出错误并列出这些订单 ID；如果任务是被取消的，`CancelledError` 仍会抛出，关闭错误作为它的 `__cause__` 保留。

## 4. 一个进程一个节点 {#one-node}

节点把 channel 的发送端和消息总线绑在线程局部变量里，别的运行时状态是进程级的，所以官方要求一个进程同时只运行一个 `LiveNode`；`run_async()` 也会拒绝在同一个循环上托管第二个节点。要跑多个节点，用多个进程。

更容易踩到的是“换节点”。同一个线程上，旧节点还存在时再构建新节点会失败（第 30 章第 6 节），而 `dispose()` 并不解除这个限制：

```python
node.dispose()
node = build_node()      # 失败：右边先执行，旧节点此时仍被 node 引用
```

正确的写法是先 `del node`（还要释放异常对象、未完成的协程等其他引用），必要时 `gc.collect()`，再构建新的。实验里，只 `dispose()` 之后再构建失败，`del` 加 `gc.collect()` 之后成功。

这条规则也决定了 ASGI 部署方式：构建节点的那个应用只能用一个 worker，也不能开热重载（重载会重启 worker 和它的节点）；HTTP 请求要扩容，就用不构建节点的其他进程来处理。

## 5. 动手验证 {#lab}

实验里的节点不接任何交易所，只有一个每 10 毫秒触发一次计时器的策略，足以观察生命周期。

::: info 实验环境
Linux（aarch64，4 核）上的 Python 3.14，nautilus_trader 2.0 的扩展模块由“从零编译”一章的 `make build-debug` 编出，对应提交 `364254f`。代码是 <a href="/nautilus-trader/code/python-lab/ch42_python_live.py" download><code>ch42_python_live.py</code></a>（[在 GitHub 查看](https://github.com/lewislau86/lewislau86.github.io/tree/master/docs/public/nautilus-trader/code/python-lab)），运行命令是 `uv run --project python --no-sync python ch42_python_live.py [段落名]`。下面的输出原样摘录，时间每次运行略有不同。
:::

**`run()` 与 SIGINT：**

<<< @/public/nautilus-trader/code/python-lab/ch42_python_live.py#owned

```text
      316 ms  node.run() (SIGINT will arrive at ~1000 ms)
      316 ms  on_start
     1318 ms  on_stop after 99 timer events
     1321 ms  node.run() returned normally
```

进程给自己发了一个 `SIGINT`，节点接住它，正常关闭，`run()` 正常返回，Python 里没有出现 `KeyboardInterrupt`。

**托管在 asyncio 上：**

<<< @/public/nautilus-trader/code/python-lab/ch42_python_live.py#hosted

```text
        3 ms  on_start
       15 ms  handle.is_running = True
       15 ms  node.cache during the run -> RuntimeError: LiveNode is being run by `run_async`; use the handle returned by `handle()` to stop it, and the `cache` and `portfolio` captured before the run to read state
       15 ms  captured cache still works: 0 instruments
       15 ms  node.dispose() during the run returned (no-op)
     1016 ms  handle.stop() returned immediately
     1106 ms  on_stop after 109 timer events
     1109 ms  run task finished; host task ticked 97 times meanwhile
```

运行期间 `node.cache` 被拒绝，事先取好的 `cache` 照常可用；运行中的 `dispose()` 直接返回。宿主循环上一个每 10 毫秒醒一次的任务，在节点运行的约 1.1 秒里醒了 97 次，没有被节点的计时器事件挤掉。

**取消任务：**

<<< @/public/nautilus-trader/code/python-lab/ch42_python_live.py#cancel

```text
        3 ms  on_start
      516 ms  task.cancel()
      606 ms  on_stop after 59 timer events
      609 ms  CancelledError re-raised after shutdown; handle.is_running = False
```

**一个线程一个节点：**

<<< @/public/nautilus-trader/code/python-lab/ch42_python_live.py#one_node

```text
  second build while the first exists -> RuntimeError: A LiveNode already exists or is being built on this thread; drop it before building another
  after first.dispose() only -> RuntimeError
  after del + gc.collect(): built LAB-001 again
```

::: warning 常见误区
- **在 `run()` 外面包一层 `try/except KeyboardInterrupt` 来做清理。** 节点自己处理 SIGINT 并正常返回，清理写在 `run()` 之后即可。
- **托管模式下以为节点会处理 Ctrl-C。** 信号归宿主，宿主要自己在收到信号时调用 `handle.stop()`。
- **运行中通过 `node.cache` 读状态。** 托管模式下会抛错，要用运行前取好的对象。
- **以为 `handle.stop()` 返回时节点已经停了。** 它只是请求，要 `await` 运行任务。
- **在运行中调用 `dispose()` 以为会在结束时生效。** 不会，结束后要再调用一次。
- **`node = LiveNode.build(...)` 直接替换旧节点。** 右边先执行，旧节点还在，构建失败；先 `del node`。
- **ASGI 应用开多个 worker 或热重载。** 每个 worker 都会构建一个节点，重载会重启节点。
- **想用 `add_builtin_strategy` 加自己写的 Rust 策略。** 内置列表是固定的，自己的 Rust 策略要编进扩展模块或用 Rust 写整个节点。
:::

## 本章结论

Python 里的实盘节点用构建器组装：官方适配器以 Rust 工厂和配置加入，组件可以是 Python 类，也可以是编进扩展模块的几个内置 Rust 组件。`run()` 占用调用线程、接管 `SIGINT` 和 `SIGTERM`，收到信号后正常关闭并正常返回；`run_async()` 把同一套生命周期托管在宿主的 asyncio 循环上，信号归宿主，运行期间节点被借出，只能用事先取好的 `cache`、`portfolio` 和 `handle()`，节点会定期让出循环但启动和关闭阶段不让出，不支持数据库后端的缓存。停止用 `handle.stop()` 加 `await`，取消任务等价于请求关闭；`dispose()` 要在运行结束后调用。一个进程只能有一个节点，换节点要先释放旧节点的全部引用，ASGI 部署只能用一个 worker、不能热重载。

## 检查理解

1. 一个 Python 脚本用 `node.run()` 运行节点，部署在 systemd 下。`systemctl stop` 发送 `SIGTERM`，策略需要在退出前撤掉所有挂单。应该把撤单写在哪里？会被执行吗？

   <details><summary>参考答案</summary>

   写在策略的 `on_stop` 里。节点接管了 `SIGTERM`，会走正常的关闭流程：先停 Trader，策略的 `on_stop` 被调用并发出撤单，然后在 `delay_post_stop` 宽限期内处理撤单回报，最后断开客户端，`run()` 正常返回。要注意宽限期的长度（第 30 章），以及 systemd 的停止超时要比它长，否则进程会在宽限期结束前被强制杀掉。

   </details>

2. 你用 FastAPI 托管节点，在一个 HTTP 接口里写了 `return node.portfolio.net_position(...)`。为什么会报错？怎样改？

   <details><summary>参考答案</summary>

   托管模式下节点在运行期间被借给 `run_async()` 的协程，通过节点对象访问状态会抛 `RuntimeError`。应该在启动节点之前取好 `portfolio = node.portfolio`（以及 `cache`、`handle`），保存在应用状态里，接口里用这个对象查询。

   </details>

3. 一个 Jupyter 笔记本里，你运行了一个节点，停下后修改配置，再执行 `node = build_node(new_config)`，报错说节点已经存在。为什么？怎样改？

   <details><summary>参考答案</summary>

   赋值语句先执行右边：构建新节点时，旧节点仍被变量 `node` 引用，同一个线程上不能同时有两个节点；`dispose()` 也不解除这个限制。先 `del node`，如果笔记本里还有别的引用（比如上一次异常的 traceback、`_` 变量），也要清掉，必要时 `gc.collect()`，再构建新节点。

   </details>

## 参考资料

- 官方文档：[Live Trading](https://nautilustrader.io/docs/latest/concepts/live/) · [Python](https://nautilustrader.io/docs/latest/concepts/python/)
- 源码：[`crates/live/src/python/node.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/live/src/python/node.rs) · [`crates/live/src/python/runtime.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/live/src/python/runtime.rs) · [`examples/live/okx/data_tester.py`](https://github.com/nautechsystems/nautilus_trader/blob/develop/examples/live/okx/data_tester.py)
- 实验代码：[`python-lab`](https://github.com/lewislau86/lewislau86.github.io/tree/master/docs/public/nautilus-trader/code/python-lab)
- 配图由 `scripts/generate-nautilus-trader-figures.py` 生成。

官方适配器之外，也可以用 Python 自己写数据和执行客户端。下一章看 `nautilus_trader.live.clients` 的基类，并动手写一个能跑的适配器：[第 43 章：用 Python 写适配器](./python-adapter.md)。
