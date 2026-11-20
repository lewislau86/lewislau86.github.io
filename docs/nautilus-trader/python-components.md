---
title: "第 40 章：Python 的其他组件：DataActor、ExecutionAlgorithm 与 Controller"
description: 除了策略，Python 里还能写三种组件：只收数据的 DataActor、拆单的 ExecutionAlgorithm、在运行时增删组件的 Controller。它们和策略用同一种包装，但 ID 规则、加入方式、启动顺序不同；信号的值会被转成字符串，Python 自定义数据传递的是同一个对象，行情和订单是拷贝；在嵌套回调里修改订阅会遇到 PyO3 的借用冲突。
---

# 第 40 章：Python 的其他组件：DataActor、ExecutionAlgorithm 与 Controller

[全书目录](./index.md) · [上一章](./python-strategy.md) · [附录](./core-topics.md)

::: tip 本章学习目标
知道 Python 里的 `DataActor`、`ExecutionAlgorithm`、`Controller` 和第 39 章的 `Strategy` 哪些地方一样、哪些地方不一样；能说出四种组件的默认 ID 怎样来、怎样加入引擎、按什么顺序启动和停止；知道信号、自定义数据、行情、订单穿过 PyO3 边界时各是什么待遇；能解释嵌套回调里的 `already borrowed` 错误并避开它；会用 Python 写一个最简单的执行算法和一个 Controller。

**源码版本：** `develop` 分支，提交 `364254f`（2026-11-18）。`DataActor` 的绑定在 `crates/common/src/python/actor.rs`，执行算法在 `crates/trading/src/python/algorithm.rs`，`Controller` 在 `crates/system/src/python/controller.rs`，注册在 `crates/system/src/python/registration.rs`，Python 自定义数据的装饰器在 `python/nautilus_trader/model/custom.py`。

**对应官方文档：** [Python](https://nautilustrader.io/docs/latest/concepts/python/) · [Actors](https://nautilustrader.io/docs/latest/concepts/actors/) · [Execution](https://nautilustrader.io/docs/latest/concepts/execution/)（Execution algorithms 一节） · [Custom Data](https://nautilustrader.io/docs/latest/concepts/custom_data/)
:::

第 13 章从 Rust 的角度讲过三种组件：只收数据、不下单的 Actor，拆单的执行算法，以及它们共用的配置和日志。第 39 章讲了 Python 策略的包装方式。这一章把两者合起来，看另外三种 Python 组件：它们是第 39 章那套包装在不同组件上的复用，但各有几处不一样的规则，其中有几条只有跑一遍才会发现。

主线例子：一个 Python 策略在开盘时发出“市场状态”信号，一个 Python Actor 订阅这个信号和一份自定义的情绪数据；策略下单时交给一个 Python 执行算法拆成三份；另有一个 Controller 在运行中按需创建新的策略。

## 1. 同一种包装 {#wrapper}

三种组件的 Rust 结构和策略几乎逐字段相同：

```rust
// 节选自 crates/common/src/python/actor.rs
#[pyo3::pyclass(module = "nautilus_trader.common", name = "DataActor",
                unsendable, subclass, weakref)]
pub struct PyDataActor {
    inner: Rc<UnsafeCell<PyDataActorInner>>,
}

pub struct PyDataActorInner {
    core: DataActorCore,
    py_self: Option<Py<PyWeakrefReference>>,
    config: Option<Py<PyAny>>,
    clock: PyClock,
    logger: PyLogger,
}
```

`ExecutionAlgorithm` 的 Inner 把 `DataActorCore` 换成第 13 章的 `ExecutionAlgorithmCore`；`Controller` 没有自己的 Inner，它用 PyO3 的 `extends = PyDataActor` 继承 `DataActor`，自己只多一个字段：指向 Trader 的弱引用。

所以第 39 章说的那些机制对它们全部成立：Inner 进 Trader 的注册表，Python 对象由一张表强引用；回调要升级弱引用、拿 GIL、拷贝数据、按名字调用；数据回调里的异常只记日志。下面只讲不同的地方。

## 2. ID、加入方式与生命周期 {#lifecycle}

| 组件 | 默认 ID | 加入方式 |
| --- | --- | --- |
| `DataActor` | 类名 | `add_actor` |
| `Strategy` | 类名-三位标签 | `add_strategy` |
| `ExecutionAlgorithm` | 类名 | `add_exec_algorithm` |
| `Controller` | 类名 | 只能经 `ImportableControllerConfig` |

策略的默认 ID 带一个自动递增的标签（第 39 章），Actor 和执行算法没有：同一个 Actor 类加两个实例，第二个会因为 `Actor 'Watcher' is already registered` 失败，要在配置里给它一个不同的 `actor_id`。和策略一样，ID 字段要传 `ActorId(...)`、`ExecAlgorithmId(...)` 这类类型，传字符串会报 `TypeError`。

**启动和停止的顺序与加入顺序无关。** Trader 启动时先启动所有 Actor，再启动策略，最后启动执行算法；停止时先停 Actor，再停执行算法，最后停策略（第 23 章）。实验里按“策略、执行算法、Actor”的顺序加入，启动顺序仍是 Actor、策略、执行算法。这条顺序有一个实际用处：Actor 在自己的 `on_start` 里订阅，就一定能收到策略在 `on_start` 里发出的信号；反过来，一个 Actor 在 `on_start` 里发出的信号，策略收不到，因为那时策略还没启动、还没订阅。

## 3. 信号、自定义数据与拷贝 {#crossing}

组件之间传消息的两条路（第 13 章）在 Python 里的待遇差别很大。

**信号的值一律变成字符串。** `publish_signal(name, value, ts_event)` 的 Python 绑定是这样写的：

```rust
// 节选自 crates/common/src/python/actor.rs（py_publish_signal）
let value_str: String = value.bind(py).str()?.extract()?;
self.inner().publish_signal(name, value_str, UnixNanos::from(ts_event));
```

不论传的是整数、浮点数、布尔值还是字典，接收方的 `signal.value` 都是 `str(value)` 的结果：`42` 变成 `'42'`，`{"a": 1}` 变成 `"{'a': 1}"`。信号适合传一个状态名或一个数字，接收方要自己转回去；结构化的内容用自定义数据。

**Python 自定义数据传的是同一个对象。** 用 `@customdataclass` 定义、`register_custom_data_class` 注册的 Python 类，包进 `CustomData` 后，Rust 里是一个 `PythonCustomDataWrapper`，按官方文档 Custom Data 一节的说明，它保存的是 Python 对象的引用。所以订阅方 `on_data` 里拿到的 `data.data`，和发布方创建的对象是**同一个** Python 对象（实验里 `is` 判断为真）。好处是没有拷贝；要注意的是，接收方改了它，发布方手里的那个也变了。

**行情和订单是拷贝。** 第 39 章已经看到，`Bar`、`QuoteTick`、订单每穿过一次边界都是一份新的拷贝。执行算法这里有一个更隐蔽的例子：`on_order(order)` 收到的主单是拷贝，算法调用 `spawn_market(order, qty)` 拆出子单后，Rust 一侧会把主单的数量减掉子单的数量（`reduce_primary` 默认为真），但手里那个 `order` 对象的数量不会变。实验里拆出两份 0.1 之后，`order.quantity` 仍是 0.3，`self.cache.order(...)` 读到的是 0.1。

## 4. 嵌套回调里的借用冲突 {#reentry}

PyO3 给每个 Python 对象维护一个借用标志，组件的 Python 方法调用期间会借用这个对象：`publish_signal` 是共享借用，`subscribe_*`、`unsubscribe_*` 要可变借用。消息总线的投递是同步的（第 15 章），所以如果一次调用同步地触发了同一个对象的回调，回调里再调用要可变借用的方法，就会失败：外层调用还借着这个对象。

实验的场景是：组件订阅了信号 `reentry`，收到 `outer` 时自己再发布一个 `inner`，嵌套的 `on_signal` 里退订。`DataActor` 和 `Strategy` 都失败了，只是报错信息不同：

- `DataActor`：`Cannot modify Python actor during unsubscribe_signal: it is already borrowed. … callback reentry can cause this conflict`（它的绑定专门包装了这条信息）；
- `Strategy`：只有 PyO3 原始的 `Already borrowed`。

仓库里的示例 `examples/backtest/callback_borrow_reentrancy.py` 还演示了另一种情形：在 Python 里直接调用 `actor.start()`，`on_start` 里的订阅同样失败，因为 `start()` 本身借着这个对象。由引擎启动时不会有这个问题。避开它的办法是不要在“自己发布、自己同步收到”的链条里修改订阅：把修改推迟到下一个回调（比如设一个很短的计时器），或者把发布和订阅放在不同的组件里。

## 5. 用 Python 写执行算法 {#exec-algorithm}

执行算法的入口是 `on_order(order)`：策略下单时在订单上指定 `exec_algorithm_id`，执行引擎不把它发往交易所，而是交给这个算法（第 13 章）。算法用 `spawn_market`、`spawn_limit`、`spawn_market_to_limit` 从主单派生子单，再 `submit_order` 提交。实验里的算法把每张主单拆成三份：

<<< @/public/nautilus-trader/code/python-lab/ch40_python_components.py#algo

几点和 Rust 版一致的规则，实验里都能看到：

- 子单 ID 是主单 ID 加 `-E1`、`-E2`……（第 13 章 TWAP 的规则）；
- 最后一份不必再派生，直接提交主单本身，此时主单的数量已经被减到剩余的 0.1；
- 子单归属发起的策略，成交事件交给策略的 `on_order_filled`，算法不需要转发。

## 6. Controller：在运行时增删组件 {#controller}

`Controller` 是一个特殊的 `DataActor`，多了 `create_actor_from_config`、`create_strategy_from_config`、`start_*`、`stop_*`、`remove_*`、`market_exit_strategy` 这些方法，用来在运行中管理别的组件。它们都通过 Trader 完成，所以 Controller 必须知道 Trader 是谁：

```rust
// 节选自 crates/system/src/python/controller.rs
#[pyclass(module = "nautilus_trader.trading", name = "Controller",
          extends = PyDataActor, subclass, unsendable)]
pub struct PyController {
    trader: Option<Weak<RefCell<Trader>>>,
}
```

这个弱引用只在一个地方被填上：Trader 的 `add_controller_from_importable_config`。也就是说，Controller 只能通过可导入配置加入，回测是 `BacktestEngineConfig(controller=ImportableControllerConfig(...))`，实盘是节点构建器的 `with_controller`。用 `add_actor` 把同一个类当普通 Actor 加进去，它照样会启动，但第一次调用管理方法就报 `Controller is not registered with a trader`。

<<< @/public/nautilus-trader/code/python-lab/ch40_python_components.py#controller

可导入配置用“模块路径:类名”指定类，配置对象由 `config_path` 指定的配置类加上 `config` 字典构造，所以这些类必须能被 `import` 到。Controller 创建的策略同样走第 39 章的注册流程，策略 ID、标签规则都一样；第 23 章提到的限制也适用：运行时加入的策略不会把 `oms_type` 登记到执行引擎。

![四种 Python 组件与边界上的待遇：上排是 DataActor、Strategy、ExecutionAlgorithm、Controller 的 ID 规则和加入方式；中间是启动和停止顺序；下方四行是行情订单、信号、Python 自定义数据、嵌套回调穿过边界时的不同待遇](/nautilus-trader/figures/python-components.svg)

怎么读这张图：上排四种组件共用第 39 章的包装，区别在 ID 和加入方式；中间一行是与加入顺序无关的生命周期顺序；下面四行是写 Python 组件时最容易踩到的四种边界行为，红框的两种会直接报错或悄悄改变数据类型。

## 7. 动手验证 {#lab}

::: info 实验环境
Linux（aarch64，4 核）上的 Python 3.14，nautilus_trader 2.0 的扩展模块由“从零编译”一章的 `make build-debug` 编出，对应提交 `364254f`。代码是 <a href="/nautilus-trader/code/python-lab/ch40_python_components.py" download><code>ch40_python_components.py</code></a>（[在 GitHub 查看](https://github.com/lewislau86/lewislau86.github.io/tree/master/docs/public/nautilus-trader/code/python-lab)），运行命令是 `uv run --project python --no-sync python ch40_python_components.py [段落名]`。`controller` 段按模块路径导入脚本里的类，要直接运行这个文件、不要改名。下面的输出原样摘录。
:::

**ID：**

<<< @/public/nautilus-trader/code/python-lab/ch40_python_components.py#ids

```text
  add_actor(Watcher()): ok, id = Watcher
  add_actor(Watcher()) again: RuntimeError: Actor 'Watcher' is already registered
  add_actor(Watcher(DataActorConfig(actor_id='WATCH-2'))): ok, id = WATCH-2
  add_exec_algorithm(Slicer()): ok, id = Slicer
```

**生命周期：**

<<< @/public/nautilus-trader/code/python-lab/ch40_python_components.py#lifecycle

```text
  order added: StrategyS, AlgoE, ActorA
  start ActorA
  start StrategyS
  start AlgoE
  stop  ActorA
  stop  AlgoE
  stop  StrategyS
```

**嵌套回调：**

<<< @/public/nautilus-trader/code/python-lab/ch40_python_components.py#reentry

```text
  DataActor: nested unsubscribe -> RuntimeError: Cannot modify Python actor during unsubscribe_signal: it is already borrowed. Release existing borrows before accessing it mutably; callback reentry can cause this conflict
  Strategy: nested unsubscribe -> RuntimeError: Already borrowed
```

**信号：**

<<< @/public/nautilus-trader/code/python-lab/ch40_python_components.py#signals

```text
  on_signal: name='regime' value='42' (str)
  on_signal: name='regime' value='3.5' (str)
  on_signal: name='regime' value='high' (str)
  on_signal: name='regime' value='True' (str)
  on_signal: name='regime' value="{'a': 1}" (str)
```

**自定义数据：**

<<< @/public/nautilus-trader/code/python-lab/ch40_python_components.py#custom

```text
  on_data: CustomData wrapping Sentiment, score=0.8
  the payload is the publisher's own Python object: True
```

**执行算法**（代码见第 5 节）：

```text
  strategy: submit O-20200814-100050-001-000-1 qty=0.30000 via SLICES
  algo: spawned O-20200814-100050-001-000-1-E1 qty=0.10000
  algo: spawned O-20200814-100050-001-000-1-E2 qty=0.10000
  algo: last slice is the primary itself; the order passed in still says qty=0.30000, the cache says qty=0.10000
  strategy: on_order_filled O-20200814-100050-001-000-1-E1 qty=0.10000
  strategy: on_order_filled O-20200814-100050-001-000-1-E2 qty=0.10000
  strategy: on_order_filled O-20200814-100050-001-000-1 qty=0.10000
  cache: O-20200814-100050-001-000-1 FILLED filled=0.10000 strategy=AlgoUser-000
  cache: O-20200814-100050-001-000-1-E1 FILLED filled=0.10000 strategy=AlgoUser-000
  cache: O-20200814-100050-001-000-1-E2 FILLED filled=0.10000 strategy=AlgoUser-000
```

三张订单全部成交，每张 0.1，都归 `AlgoUser-000`；主单最终的数量是 0.1，算法手里那个主单对象却仍然显示 0.3。

**Controller**（代码见第 6 节）：

```text
  Late-009: on_start (created at runtime by the controller)
  controller LabController: created and started Late-009
  added with add_actor instead: RuntimeError: Controller is not registered with a trader
```

`Late-009` 的 `on_start` 先于 Controller 的那行输出打印：`create_strategy_from_config(..., start=True)` 在返回之前就同步启动了新策略。

::: warning 常见误区
- **同一个 Actor 类加两个实例。** Actor 和执行算法的默认 ID 是类名，没有自动标签，第二个会注册失败。
- **以为组件按加入顺序启动。** 顺序固定是 Actor、策略、执行算法；Actor 在 `on_start` 里发的信号，策略收不到。
- **用信号传数字或字典。** 值会被 `str()` 转成字符串，接收方要自己解析。
- **在 `on_data` 里修改收到的 Python 自定义数据。** 那是发布方的同一个对象。
- **在执行算法里用 `on_order` 收到的主单对象判断剩余数量。** 它是拷贝，派生子单后要从缓存重新读。
- **在“自己发布、自己同步收到”的回调链里修改订阅。** 会报 `already borrowed`；推迟到下一个回调，或者拆到不同的组件里。
- **用 `add_actor` 加入 Controller。** 它不会被绑定到 Trader，管理方法全部报错；要用可导入配置。
:::

## 本章结论

`DataActor`、`ExecutionAlgorithm`、`Controller` 和 `Strategy` 用的是同一种包装：可子类化、只能单线程使用的 Rust 类，持有一个进入 Trader 注册表的 Inner，回调经弱引用、GIL、拷贝和按名字调用到达 Python。不同的是规则：Actor 和执行算法默认以类名为 ID，同类第二个实例会冲突；Controller 继承 `DataActor`，靠一个指向 Trader 的弱引用管理其他组件，这个引用只在经可导入配置加入时才被填上。组件按 Actor、策略、执行算法的顺序启动，与加入顺序无关。穿过边界时，行情和订单是拷贝，信号的值变成字符串，Python 自定义数据传的是同一个对象；在同步触发自己回调的链条里修改订阅，会因为 PyO3 的借用标志而失败。

## 检查理解

1. 一个 Actor 在 `on_start` 里 `publish_signal("regime", "risk_off")`，一个策略在 `on_start` 里订阅了 `regime`。策略能收到这个信号吗？要让它收到，可以怎么改？

   <details><summary>参考答案</summary>

   收不到。Actor 先于策略启动，Actor 发布时策略还没有订阅。可以反过来让策略发布、Actor 订阅；或者让 Actor 推迟发布，比如在 `on_start` 里设一个计时器，在第一次计时器回调里再发布，那时所有组件都已启动；或者干脆让 Actor 把状态写进自定义数据或缓存，策略启动后主动读取。

   </details>

2. 你用信号传一个浮点数阈值 `0.25`，接收方写 `if signal.value > 0.2:`。会发生什么？

   <details><summary>参考答案</summary>

   `signal.value` 是字符串 `'0.25'`，和浮点数比较会抛 `TypeError`；这个异常发生在数据回调里，只会被记成一条 ERROR 日志，接收方悄悄地少处理了这条信号。应该写 `float(signal.value) > 0.2`，或者改用自定义数据传结构化的数值。

   </details>

3. 一个 Python 执行算法在 `on_order` 里先 `spawn_market(order, qty)` 两次，然后根据 `order.quantity` 计算最后一份的大小再派生第三张子单。为什么结果会超出主单的数量？

   <details><summary>参考答案</summary>

   `order` 是传进来时的拷贝，派生子单时 Rust 一侧会把主单数量减掉子单数量，但这个 Python 对象不会更新。用它的 `quantity` 算出的“剩余”仍是原始数量，于是第三张子单的数量过大。应该在派生后从 `self.cache.order(order.client_order_id)` 读主单的当前数量，或者像实验那样直接提交主单本身作为最后一份。

   </details>

## 参考资料

- 官方文档：[Python](https://nautilustrader.io/docs/latest/concepts/python/) · [Actors](https://nautilustrader.io/docs/latest/concepts/actors/) · [Custom Data](https://nautilustrader.io/docs/latest/concepts/custom_data/)
- 源码：[`crates/common/src/python/actor.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/common/src/python/actor.rs) · [`crates/trading/src/python/algorithm.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/trading/src/python/algorithm.rs) · [`crates/system/src/python/controller.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/system/src/python/controller.rs) · [`crates/system/src/python/registration.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/system/src/python/registration.rs) · [`python/nautilus_trader/model/custom.py`](https://github.com/nautechsystems/nautilus_trader/blob/develop/python/nautilus_trader/model/custom.py) · [`examples/backtest/callback_borrow_reentrancy.py`](https://github.com/nautechsystems/nautilus_trader/blob/develop/examples/backtest/callback_borrow_reentrancy.py)
- 实验代码：[`python-lab`](https://github.com/lewislau86/lewislau86.github.io/tree/master/docs/public/nautilus-trader/code/python-lab)
- 配图由 `scripts/generate-nautilus-trader-figures.py` 生成。

组件写好了，接下来是把它们放进引擎里跑。下一章看在 Python 里跑回测：`BacktestEngine` 和 `BacktestNode` 怎么选，结果怎样取出来。第 41 章还在规划中，暂时可以先读附录：[附录：重点主题速览](./core-topics.md)。
