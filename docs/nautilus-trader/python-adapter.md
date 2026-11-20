---
title: "第 43 章：用 Python 写适配器"
description: 用 nautilus_trader.live.clients 的基类写自己的数据和执行客户端：工厂同步返回、不碰事件循环，_connect 时才绑定循环；命令按客户端排成 FIFO 队列，后台工作交给 create_task 托管；ClientCache 是只读快照，输出方法只是把类型化的值排队交给 Rust 内核；超时不等于拒单，留给在途检查用 _query_order 查清；两种注册方式和 v1 的迁移对照。实验写一个对接假 OpenD 的完整适配器。
---

# 第 43 章：用 Python 写适配器

[全书目录](./index.md) · [上一章](./python-live.md) · [下一章](./python-boundaries.md)

::: tip 本章学习目标
能用 Python 写出一个数据客户端和一个执行客户端，并通过工厂注册到 `LiveNode`；能说出工厂、构造函数和 `_connect` 各自能做什么、不能做什么；知道命令钩子按什么顺序执行、为什么钩子里要尽快返回；知道适配器怎样读内核状态（只读快照）、怎样把数据和事件交给内核（排队输出）；会处理“结果不明”的命令：不拒单，交给对账；知道 v1 适配器迁移到 v2 时要改哪些地方。

**源码版本：** `develop` 分支，提交 `364254f`（2026-11-18）。基类在 `python/nautilus_trader/live/clients.py`，品种提供者在 `python/nautilus_trader/live/providers.py`，桥接在 `crates/live/src/python/` 下；模板适配器在 `examples/live/_template/`。

**对应官方文档：** [Python Adapter Interface](https://nautilustrader.io/docs/latest/developer_guide/python_adapters/) · [Adapters](https://nautilustrader.io/docs/latest/concepts/adapters/)
:::

第 38 章用富途做例子，从 Rust 讲了一个适配器要做的事，附录 C 列了三条 Python 路线，其中路线 B 是纯 Python 适配器，建议先用它跑通。这一章把路线 B 落到代码上：基类有哪些钩子，运行时给它们什么保证，又要求它们遵守什么约定。

主线例子还是富途：一个 Python 适配器，通过 OpenD 收港股行情、下市价单。实验里用一个进程内的假 OpenD 代替真网关，它会推行情、接单，还会“丢掉”一次下单回包。

## 1. 三个基类和一个工厂 {#classes}

适配器从 `nautilus_trader.live.clients` 继承：

| 基类 | 负责 |
| --- | --- |
| `DataClient` | 订阅和历史请求 |
| `MarketDataClient` | 与 `DataClient` 完全相同，只是名字 |
| `ExecutionClient` | 订单命令、账户更新、对账报告 |

品种由 `nautilus_trader.live.providers.InstrumentProvider` 加载，覆盖 `load_all_async`（或 `load_ids_async`、`load_async`）即可。

客户端不由你直接构造，而是交给节点一个**工厂**：

```python
class FutuExecutionClientFactory(ExecutionClientFactory):
    @staticmethod
    def create(*, name, config, cache, clock, trader_id):
        return FutuExecutionClient(name=name, config=config, cache=cache, clock=clock,
                                   trader_id=trader_id, venue=VENUE, account_id=..., ...)
```

数据工厂的签名是 `create(*, name, config, cache, clock)`，执行工厂多一个 `trader_id`。执行客户端还必须给出 `venue`、`account_id`、`account_type`、`oms_type`，这四项决定了它产生的事件归属哪个账户。工厂必须**同步**返回客户端。

注册有两种写法。直接注册用构建器的 `add_data_client(name, factory, config)` 和 `add_exec_client(...)`；按配置注册则把名字到配置的映射写进 `LiveNodeConfig(data_clients=..., exec_clients=...)`，再把工厂交给 `LiveNode.build(name, config, data_factories=..., exec_factories=...)`。按名字找工厂时先查完整名字，再查第一个连字符之前的前缀，所以 `"FUTU-HK"` 和 `"FUTU-US"` 两个客户端可以共用 `"FUTU"` 这一个工厂。官方的 Rust 适配器和自己的 Python 适配器可以放在同一个节点里；名字不能重复。

适配器自己的配置字段，写在 `DataClientConfig` 或 `ExecutionClientConfig` 的子类里，规则和第 39 章的策略配置一样：在 Python 的 `__init__` 里声明关键字参数，用 `**kwargs` 接住公共字段。配置会被序列化，所以不要在里面放运行时资源；凭证也会跟着序列化出去，要保护好结果。

## 2. 什么时候能碰事件循环 {#lifecycle}

![Python 适配器的结构：左边是 Rust 内核，引擎是唯一写交易状态的地方，ClientCache 是只读视图，对账和在途检查会调用命令钩子；中间是适配器，工厂同步返回，_connect 时循环已绑定，命令钩子排在每个客户端一条的 FIFO 队列里，后台任务由运行时托管；右边是交易所。超时不等于拒单，订单留在 SUBMITTED，由在途检查调用 _query_order 查清](/nautilus-trader/figures/python-adapter-flow.svg)

怎么读这张图：左列是 Rust 内核，中列是你写的适配器，右列是交易所。蓝色箭头是内核发给适配器的命令，橙色箭头是适配器交回内核的输出；中列从上到下是一个客户端的生命周期。

**构造时不能碰。** 工厂和构造函数里不能启动任务、不能取事件循环、不能打开网络连接。这时 `client.loop` 是 `None`；v1 风格的工厂如果声明了 `loop` 参数，拿到的也是 `None`。原因是工厂在节点构建时就被调用，那时节点还不知道自己会跑在哪个循环上：`run()` 会在调用线程上新建一个 asyncio 循环，`run_async()` 则用宿主的循环（第 42 章）。

**`_connect` 里才可以。** 启动时，运行时先把每个自定义客户端绑定到实际运行的循环上，再调用 `_connect`。依赖循环的东西（会话、锁、网络客户端、OpenD 的 TCP 连接）都在这里创建。实验里，工厂创建客户端时 `loop` 还没有绑定，`_connect` 被调用时已经绑定，而且就在调用 `node.run()` 的主线程上。

**同一个线程。** 带自定义客户端的节点，`run()` 在调用它的线程上驱动 asyncio；Rust 内核、Python 策略和适配器的钩子都在这个线程上执行。实验里策略的 `on_start`、`on_order_filled` 和适配器的 `_connect` 都在 `MainThread`。所以钩子里任何阻塞调用（同步的 HTTP 请求、`time.sleep`）都会卡住整个节点。

**数据库后端的缓存不能用。** Redis 和 PostgreSQL 后端在等后台工作时会阻塞调用线程，放在 asyncio 循环上就是卡住循环，所以带自定义 Python 客户端的节点在两种运行方式下都不支持（第 36 章、第 42 章）。

## 3. 命令怎样到达钩子 {#commands}

数据客户端的钩子按“动作 + 数据族”命名：订阅报价是 `_subscribe_quotes(command)`，退订是 `_unsubscribe_quotes(command)`，请求历史报价是 `_request_quotes(request)`；盘口是 `book_deltas`、`book_depth`，K 线是 `bars`，等等。执行客户端的钩子是 `_submit_order`、`_submit_order_list`、`_modify_order`、`_cancel_order`、`_cancel_all_orders`、`_query_account`、`_query_order`。所有钩子都是 `async` 的，收到的命令是一份拷贝，没有覆盖的钩子会抛 `NotImplementedError`。

几条运行时保证：

- **每个客户端一条 FIFO 队列。** 命令和订阅变更按到达顺序排队，一个执行完才执行下一个，最多排 1,024 个，满了就拒绝新的命令。一个钩子抛异常会被记日志，然后接着执行下一个。
- **钩子要短。** 一个钩子没返回，这个客户端后面的命令都在等。下单钩子里等交易所回包，就会挡住紧跟着的撤单。实验的写法是：钩子里只发 `generate_order_submitted`，然后用 `create_task` 把真正的网络请求放到后台，立即返回。
- **历史请求和对账不排这条队列。** 它们另外执行，网络等待不会挡住命令。
- **订阅命令带的是列表。** 读 `command.instrument_ids` 或 `command.bar_types`，不要读单数的 `instrument_id`；同一个钩子可能一次收到多个品种。队列接纳命令时就算“接受”了，之后钩子失败只会记日志，不会通知引擎；所以退订钩子要能容忍当初订阅失败的品种。

**后台工作用 `self.create_task(coroutine, name)`。** 运行时会持有这个任务直到取回它的结果，失败时用客户端名和任务名记日志，断开时负责取消和收尾。直接用 `asyncio.create_task` 或第三方库建的任务，运行时不管，要在 `_disconnect` 里自己等它们结束。

**断开的顺序。** 节点停止时先过宽限期（第 30 章），让策略 `on_stop` 里的撤单走正常的命令路径；然后对每个客户端：关闭队列入口并丢弃还在排队的命令，取消正在执行的命令，再调用 `_disconnect`，在里面关闭网络资源、等自己的任务结束。整个过程有超时；运行时对每个任务最多请求一次取消，到时间还没收尾就报告“清理未完成”，不会反复取消。客户端实例和它绑定的品种提供者只属于一次节点运行。

## 4. 读状态和交输出 {#io}

**读：`ClientCache` 是只读快照。** 工厂拿到的 `cache` 不是内核的缓存本身，而是一个只读视图：`instrument`、`instruments`、`quote`、`order_book`、`account`、`position`、`order`、`orders_open`、`orders_inflight` 等方法返回的是拷贝，改了不影响内核。在别的线程上读、节点 dispose 之后读、或者内核正在以不兼容的方式借用时读，都会抛异常。

**写：输出方法只是排队。** 内核是交易状态唯一的写入者；适配器调用输出方法，只是把类型化的值排进队列，由内核按顺序处理：

| 输出 | 方法 |
| --- | --- |
| 品种定义 | `_handle_instrument` |
| 行情数据 | `_handle_data` |
| 历史请求的回应 | `_handle_response` |
| 执行事件 | `generate_account_state`、`generate_order_*`、`_handle_event` |
| 对账报告 | `_handle_report` |

所以“加载品种”分两步：品种提供者把品种存在适配器本地，`_connect` 里再逐个 `_handle_instrument` 交给内核，内核的缓存里才有它。`_handle_data` 接受 `QuoteTick`、`TradeTick`、`Bar`、盘口增量和深度、标记价格、资金费率、`CustomData` 等类型，必须是 `nautilus_trader.model` 里的类；`_handle_report` 接受订单状态、成交、仓位报告和 `ExecutionMassStatus`，报告里的账户必须和客户端注册的账户一致。

## 5. 结果不明的命令 {#ambiguous}

第 34 章和第 38 章都强调过：超时不等于拒单。富途 OpenD 回 `retType = -100` 时，订单可能已经在交易所成交了，只是回包丢了。

在 Python 适配器里的做法是：**什么都不发。** 不发 `generate_order_rejected`，订单留在 `SUBMITTED`，处于在途状态。运行期的在途检查（默认每 2 秒一次，在途超过 5 秒的订单）会为它调用 `_query_order`；适配器在这里向交易所查询订单的真实状态，用 `_handle_report(OrderStatusReport, fills=[FillReport, ...])` 交给内核，由对账逻辑补出缺失的接受和成交事件。启动时的对账走的是另一组钩子：`_generate_order_status_reports`、`_generate_fill_reports`、`_generate_position_status_reports`，它们抛出的异常会让启动对账失败。

实验里第二张单就是这样：回包丢失后适配器只打一行日志；约 7 秒后在途检查调用 `_query_order`，假 OpenD 说已成交，报告交上去以后，策略收到了 `on_order_filled`。

## 6. 从 v1 迁移 {#migration}

v1 的 Cython 适配器不能原样搬过来。官方文档里的对照表，摘主要几行：

| v1 | v2 |
| --- | --- |
| `LiveDataClient` 等 | `DataClient` 等，从 `nautilus_trader.live.clients` 导入 |
| `quote_ticks`、`trade_ticks` 钩子 | `quotes`、`trades` 钩子 |
| `order_book_*` 钩子 | `book_*` 钩子 |
| `_handle_*` 历史数据方法 | `_handle_response(类型化回应)` |
| `_send_*` 执行方法 | `_handle_event`、`_handle_report` |
| 直接写缓存 | 排队输出，内核来写 |
| 构造时的事件循环 | 启动后的 `client.loop`，资源在 `_connect` 里建 |
| `cancel_pending_tasks` | 节点断开时统一收尾 |
| `run_after_delay` | `asyncio.sleep` 加 `create_task` |

还有几处没有对应物：订阅状态的跟踪方法没有了，要在适配器里自己按交易所的确认维护；v1 里那些 HTTP 和 WebSocket 的 Python 绑定已经移除，这套接口不会恢复它们，网络库要自己选；客户端不能发布或订阅消息总线的主题，自定义数据只能通过 `CustomData` 输出。

协议层写成 Rust 也可以（第 38 章附录 C 的路线 C）：独立的 PyO3 包，Python 外观仍继承这一章的基类、用同样的工厂注册。关键约束是只能和已安装 wheel 里的模型类交换对象，不能再链接一套 Nautilus 的模型类型。

## 7. 动手验证 {#lab}

实验写一个完整的适配器，对接一个进程内的假 OpenD，由 `LiveNode` 驱动 10 秒。

::: info 实验环境
Linux（aarch64，4 核）上的 Python 3.14，nautilus_trader 2.0 的扩展模块由“从零编译”一章的 `make build-debug` 编出，对应提交 `364254f`。代码是 <a href="/nautilus-trader/code/python-lab/ch43_python_adapter.py" download><code>ch43_python_adapter.py</code></a>（[在 GitHub 查看](https://github.com/lewislau86/lewislau86.github.io/tree/master/docs/public/nautilus-trader/code/python-lab)），运行命令是 `uv run --project python --no-sync python ch43_python_adapter.py`。下面的输出原样摘录，时间每次运行略有不同。
:::

**假交易所。** 每次取报价时价格上下走半格；市价单 30 毫秒后成交；带 `lose-ack` 标签的单照样成交，但回包丢失：

<<< @/public/nautilus-trader/code/python-lab/ch43_python_adapter.py#venue

**品种提供者和数据客户端。** `_connect` 加载品种并交给内核；订阅报价时启动一个托管的后台任务，每 50 毫秒推一条报价：

<<< @/public/nautilus-trader/code/python-lab/ch43_python_adapter.py#provider

<<< @/public/nautilus-trader/code/python-lab/ch43_python_adapter.py#data

**执行客户端。** 下单钩子只发“已提交”就返回，网络请求放到后台；超时什么也不发；`_query_order` 把交易所的真实状态作为报告交上去：

<<< @/public/nautilus-trader/code/python-lab/ch43_python_adapter.py#execution

**工厂、策略和节点。** 策略在第 3 条报价时买 100 股，第 6 条报价时再买 100 股、并打上 `lose-ack` 标签。为了少等，周期检查的启动延迟设成 1 秒：

<<< @/public/nautilus-trader/code/python-lab/ch43_python_adapter.py#factories

<<< @/public/nautilus-trader/code/python-lab/ch43_python_adapter.py#strategy

<<< @/public/nautilus-trader/code/python-lab/ch43_python_adapter.py#node

```text
      324 ms  factory: created LAB execution client, loop bound: False
      325 ms  node.run() on thread MainThread
      326 ms  data _connect on thread MainThread, loop bound: True
      328 ms  strategy on_start on thread MainThread
      328 ms  _subscribe_quotes ['00700.HKEX']
      435 ms  quote #3 ask=502.0: submit O-20261120-093621-001-000-1 tags=None
      468 ms  on_order_filled O-20261120-093621-001-000-1 100 @ 502.0 on thread MainThread
      598 ms  quote #6 ask=501.5: submit O-20261120-093621-001-000-2 tags=['lose-ack']
      635 ms  venue: retType=-100: request timed out for O-20261120-093621-001-000-2; leaving it SUBMITTED
     7433 ms  _query_order O-20261120-093621-001-000-2: venue says FILLED
     7434 ms  on_order_filled O-20261120-093621-001-000-2 100 @ 501.5 on thread MainThread
    10332 ms  on_stop: O-20261120-093621-001-000-1 status=FILLED filled=100
    10332 ms  on_stop: O-20261120-093621-001-000-2 status=FILLED filled=100
    10332 ms  on_stop: net position 200, quotes seen 183
    10839 ms  node.run() returned
```

逐行对照：

- **循环的绑定时机。** 工厂里 `loop` 还是 `None`，`_connect` 时已经绑定。所有回调都在 `MainThread` 上，也就是调用 `run()` 的线程。
- **正常的一张单。** 提交后 33 毫秒（假交易所 30 毫秒的往返加调度）收到成交，`generate_order_accepted` 和 `generate_order_filled` 经内核处理后到达策略的 `on_order_filled`。
- **回包丢失的一张单。** 598 毫秒提交，635 毫秒超时，适配器什么也没发。在途超过 5 秒之后，下一次在途检查（每 2 秒一次）在 7433 毫秒调用 `_query_order`；报告交上去 1 毫秒后策略收到成交，价格是交易所实际的成交价 501.5。
- **最终状态一致。** 两张单都是 `FILLED`，净持仓 200 股，和假交易所记录的一致。如果第二张单在超时时被拒掉，本地会以为只有 100 股。
- **停止。** 10 秒时 `handle.stop()`，`on_stop` 之后过 0.5 秒的宽限期，`run()` 返回。

::: warning 常见误区
- **在工厂或 `__init__` 里建连接、开任务。** 那时循环还没绑定，资源要在 `_connect` 里建。
- **在钩子里用同步的网络库或 `time.sleep`。** 钩子和整个节点在同一个线程上，会卡住所有东西。
- **在下单钩子里一直等回包。** 同一个客户端后面的撤单都在排队等它；发完“已提交”就把等待放到后台。
- **用 `asyncio.create_task` 开后台任务又不管它。** 运行时只托管 `self.create_task` 建的任务，其他的要在 `_disconnect` 里自己收尾。
- **以为改 `self.cache` 返回的对象能改内核状态。** 那是快照；要改状态只能通过输出方法排队。
- **加载品种后没有 `_handle_instrument`。** 品种只在适配器本地，内核缓存里没有，策略订阅时找不到品种。
- **超时就 `generate_order_rejected`。** 结果不明不是拒单；什么都不发，在 `_query_order` 里查清。
- **订阅钩子读 `command.instrument_id`。** v2 的订阅命令带列表，要读 `command.instrument_ids`。
- **和 Redis 缓存后端一起用。** 带自定义 Python 客户端的节点不支持数据库后端。
:::

## 本章结论

Python 适配器继承 `nautilus_trader.live.clients` 的 `DataClient` 或 `ExecutionClient`，由同步返回的工厂创建，通过构建器或 `LiveNode.build` 的工厂映射注册，可以和官方的 Rust 适配器共用一个节点。工厂和构造函数里不能碰事件循环，`_connect` 时循环才绑定；所有钩子和 Rust 内核、Python 策略在同一个线程上，不能阻塞。命令按客户端排成最多 1,024 个的 FIFO 队列，钩子要尽快返回，长时间的工作交给运行时托管的 `self.create_task`。适配器通过只读的 `ClientCache` 读状态，通过排队的输出方法交出品种、数据、事件和报告，内核是唯一的写入者。结果不明的命令什么都不发，交给在途检查调用 `_query_order` 查清。v1 适配器要按对照表改名、改输出方式、把资源创建移到 `_connect`。

## 检查理解

1. 你在富途执行客户端的 `__init__` 里写了 `self._session = aiohttp.ClientSession()`，启动时报错或行为异常。为什么？应该怎样改？

   <details><summary>参考答案</summary>

   构造时客户端还没有绑定事件循环（`client.loop` 是 `None`），节点也还不知道自己会跑在 `run()` 新建的循环上还是宿主的循环上；在这时创建依赖循环的会话，可能绑到错误的循环或者根本没有循环。应该在 `_connect` 里创建会话，在 `_disconnect` 里关闭它。

   </details>

2. 策略在同一个毫秒里先下单、再撤掉另一张单。你的 `_submit_order` 里 `await` 了交易所的下单回包，平均 300 毫秒。撤单会发生什么？怎样改？

   <details><summary>参考答案</summary>

   同一个客户端的命令按 FIFO 顺序执行，`_submit_order` 没返回，`_cancel_order` 就在队列里等着，撤单会晚 300 毫秒才发出。改法是钩子里只做必要的同步工作（比如 `generate_order_submitted`），把网络请求和等待回包放进 `self.create_task(...)`，钩子立即返回，让队列继续。

   </details>

3. 下单请求超时了，你的适配器调用了 `generate_order_rejected`。之后交易所推来了这张单的成交。会出现什么问题？正确做法是什么？

   <details><summary>参考答案</summary>

   本地订单已经是 `REJECTED`，这是终态，之后的成交事件不能再应用到这张订单上，本地持仓会和交易所对不上，直到对账发现差异。超时是“结果不明”，正确做法是什么都不发，订单留在 `SUBMITTED`；在途检查会调用 `_query_order`，适配器向交易所查询真实状态，用 `_handle_report` 交出订单状态和成交报告，由对账补齐事件。

   </details>

## 参考资料

- 官方文档：[Python Adapter Interface](https://nautilustrader.io/docs/latest/developer_guide/python_adapters/) · [Adapters](https://nautilustrader.io/docs/latest/concepts/adapters/)
- 源码：[`python/nautilus_trader/live/clients.py`](https://github.com/nautechsystems/nautilus_trader/blob/develop/python/nautilus_trader/live/clients.py) · [`python/nautilus_trader/live/providers.py`](https://github.com/nautechsystems/nautilus_trader/blob/develop/python/nautilus_trader/live/providers.py) · [`examples/live/_template/`](https://github.com/nautechsystems/nautilus_trader/tree/develop/examples/live/_template)
- 实验代码：[`python-lab`](https://github.com/lewislau86/lewislau86.github.io/tree/master/docs/public/nautilus-trader/code/python-lab)
- 配图由 `scripts/generate-nautilus-trader-figures.py` 生成。

第七部分最后一章回头看 Python 层的边界：哪些是公开的接口，精度和异常怎样跨过边界，v1 的代码怎样迁移，什么时候该把 Python 代码换成 Rust：[第 44 章：边界与迁移](./python-boundaries.md)。
