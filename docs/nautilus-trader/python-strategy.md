---
title: "第 39 章：Python 策略：Rust 策略框架的绑定"
description: NautilusTrader v2 的 Python 策略是什么：nautilus_trader.trading.Strategy 是一个可子类化的 Rust 类，持有 Rc<UnsafeCell<PyStrategyInner>>；配置对象原样保留，策略 ID 怎样生成、order_id_tag 为什么要唯一；注册时 Inner 进注册表、Python 对象被强引用保留；一次回调怎样升级弱引用、拿 GIL、拷贝数据、按名字调用；异常在数据回调和 on_start 里的不同后果；缓存等句柄返回快照；回测与 LiveNode 下回调在哪个线程、GIL 何时释放；每次回调的实测开销。
---

# 第 39 章：Python 策略：Rust 策略框架的绑定

[全书目录](./index.md) · [上一篇](./futu-adapter.md) · [下一章](./python-components.md)

::: tip 本章学习目标
能说清 Python 里的 `Strategy` 和第 9 章的 Rust 策略是什么关系，知道你写的子类、配置对象、Rust 一侧的状态各存在哪里；知道策略 ID 怎样生成、什么情况下注册会失败；能按步骤说出一次 `on_bar` 怎样从 Rust 调进 Python，知道每一步的代价；分得清手里的订单对象和缓存里的订单；知道异常、线程、GIL、计时器回调在回测和实盘下的行为；能用实测数字判断一段逻辑该写在 Python 还是 Rust 里。

**源码版本：** `develop` 分支，提交 `364254f`（2026-11-18）。Python 策略的绑定在 `crates/trading/src/python/strategy.rs`，注册在 `crates/system/src/python/registration.rs`，Python 对象的强引用表在 `crates/common/src/python/wrappers.rs`，回测引擎的 `add_strategy` 在 `crates/backtest/src/python/engine.rs`，Python 包 `python/nautilus_trader/trading/__init__.py` 只是 `_libnautilus.trading` 的转出。

**对应官方文档：** [Python](https://nautilustrader.io/docs/latest/concepts/python/) · [Strategies](https://nautilustrader.io/docs/latest/concepts/strategies/)
:::

第七部分讲 Python 层。第 0 章第 4 节从整体上讲过 PyO3 绑定：Python 包里的类绝大多数就是 Rust 结构体本身。这一章只看最常用的一个：策略。v1 的 Python 策略是 Cython 写的，v2 里它变成了第 9 章那套 Rust 策略框架的一个 Python 外壳。你写的 `on_bar` 是 Python 函数，但订阅、指标更新、下单、风控、缓存，全部仍然在 Rust 里。

主线例子是官方教程里的 `EMACross`（第 12 章第 3 节引用过）：一个 `StrategyConfig` 的子类带上品种和均线参数，策略在 `on_start` 里注册两条 EMA、订阅 K 线，在 `on_bar` 里比较两条均线、下市价单。本章的实验数据仍是 ETHUSDT 的 69,806 笔成交（第 11 章）。

## 1. `Strategy` 是一个 Rust 类 {#pyclass}

`from nautilus_trader.trading import Strategy` 拿到的类定义在 Rust 里：

```rust
// 节选自 crates/trading/src/python/strategy.rs
#[pyo3::pyclass(module = "nautilus_trader.trading", name = "Strategy",
                unsendable, subclass, weakref)]
pub struct PyStrategy {
    inner: Rc<UnsafeCell<PyStrategyInner>>,
}

pub struct PyStrategyInner {
    core: StrategyCore,                          // 第 9 章的 StrategyCore
    py_self: Option<Py<PyWeakrefReference>>,     // 指回 Python 对象的弱引用
    config: Option<Py<PyAny>>,                   // 你传进来的配置对象，原样保留
    clock: PyClock,
    logger: PyLogger,
}
```

三个属性各有用意：`subclass` 允许你在 Python 里继承它；`unsendable` 表示这个对象只能在创建它的线程上使用，PyO3 会在别的线程访问时报错；`weakref` 让 Rust 一侧可以持有指回 Python 对象的弱引用。

真正干活的是 `PyStrategyInner`。它和第 9 章用 `nautilus_strategy!` 宏写出来的 Rust 策略一样，实现了 `DataActor` 和 `Strategy` 两个 trait，所以对 Trader、消息总线、引擎来说，它就是一个普通的 Rust 策略。区别只在回调：Rust 策略的 `on_bar` 是 Rust 代码，`PyStrategyInner` 的 `on_bar` 转身去调用 Python 对象上的同名方法。

为什么是 `Rc<UnsafeCell<…>>`？Trader 的组件注册表和 Actor 注册表存的都是 `Rc<UnsafeCell<dyn …>>`，消息总线的处理函数从注册表里取出组件、直接调用它的回调（第 10 章），Rust 策略也是这样存的。`PyStrategy` 和注册表共用同一个 Inner，所以用的是同一种容器；`unsendable` 保证只在一个线程上访问，源码注释写明调用方不会同时持有可变和共享引用。

回调重入的问题出在另一层：PyO3 给每个 Python 对象维护了一个借用标志，`subscribe_*`、`publish_signal` 这类会修改策略的方法，调用期间持有对象的可变借用。如果这次调用同步地触发了同一个对象的回调（比如在 `on_signal` 里发布一个自己也订阅了的信号），回调里再调用这类方法就会失败。第 40 章用 `DataActor` 和 `Strategy` 各做了一次同样的实验，两者都会报错，只是报错信息不同。

在 Python 里看，基类上的方法都是 Rust 实现的（类型是 `method_descriptor`），你覆盖的方法是普通的 Python 函数，没覆盖的仍是 Rust 的空实现（第 8 节实验）。

## 2. 构造与注册 {#registration}

**构造。** `MyStrategy(config)` 先走 Rust 的 `__new__`：如果 `config` 是 `StrategyConfig`（或它的子类），从中取出 `strategy_id`、`order_id_tag`、`oms_type`、`external_order_instrument_ids`、`manage_*` 等字段建一个 `StrategyCore`；整个配置对象原样存进 `config`，`self.config` 拿回来的就是同一个对象。教程里的写法是这样：

```python
# 节选自 docs/tutorials/ema_cross.py
class EMACrossConfig(StrategyConfig):
    def __init__(self, *, instrument_id, bar_type, trade_size,
                 fast_ema_period=10, slow_ema_period=20, **_kwargs):
        super().__init__()
        self.instrument_id = instrument_id
        ...
```

`StrategyConfig` 本身是 Rust 类，构造参数（比如 `order_id_tag="042"`）由它的 `__new__` 接收，所以子类的 `__init__` 要用 `**_kwargs` 接住这些参数、再无参调用 `super().__init__()`；你自己加的字段只存在于 Python 对象上，Rust 不读它们。另一个容易踩的地方：`strategy_id` 要传 `StrategyId("…")`，传字符串会报 `TypeError`。

构造之后、注册之前，策略还不完整：`self.clock`、`self.cache` 会抛 `RuntimeError: Strategy must be registered with a trader before accessing clock`，`strategy_id` 显示为 `类名-None`。

**注册。** `engine.add_strategy(strategy)`（回测）或 `node.add_strategy(strategy)`（实盘）最后都调用 Trader 的 `add_python_strategy_instance`，分两步：

1. **准备。** 用配置对象配置 `StrategyCore`；确定策略 ID：配置里有就用配置的，否则是“类名-标签”，标签取 `order_id_tag`，没有就取下一个没被占用的三位数（`000`、`001`……）。ID 不能重复，**标签也不能重复**：已有 `Mine-001` 时，再注册一个 `LAB-001` 会因为标签 `001` 冲突而失败（第 8 节实测）。标签会出现在客户端订单 ID 里（第 2 章），所以必须唯一。
2. **提交。** 给策略建一个组件时钟，把 Trader ID、时钟、缓存、组合注入 `StrategyCore`；然后 `register_in_global_registries` 把 Inner 的 `Rc` 放进组件注册表和 Actor 注册表（第 23 章），并在一张线程局部的表里保留 Python 对象的**强引用**；最后订阅这个策略的订单和仓位事件主题。

```rust
// 节选自 crates/trading/src/python/strategy.rs（register_in_global_registries，有删节）
let inner_ref: Rc<UnsafeCell<PyStrategyInner>> = self.inner.clone();
with_component_registry(|r| r.insert(component_id.inner(), inner_ref.clone()));
with_actor_registry(|r| r.insert(actor_id, inner_ref));
retain_python_wrapper(component_id, wrapper, inner.core.actor.message_bus());
```

所以 Rust 和 Python 两边互相持有：注册表持有 Inner，强引用表持有 Python 对象，Inner 再用弱引用指回 Python 对象。`engine.add_strategy(MyStrategy())` 这样不留引用的写法是安全的，回调照常发生。

回测引擎还会读配置对象的 `oms_type` 属性，有的话登记到执行引擎（第 20 章）。实盘节点额外读 `external_order_instrument_ids`，登记外部订单的认领；这一点和 Rust 策略不同，Rust 节点读的是 trait 方法而不是配置（第 34 章第 7 节）。

## 3. 一次回调：从 Rust 到你的 `on_bar` {#dispatch}

![Python 策略怎样挂在 Rust 框架上：左列是 Python 一侧的子类、配置、拷贝和快照；中列是 PyO3 边界，一次回调升级弱引用、拿 GIL、转换对象、按名字调用；右列是 Rust 核心的 PyStrategyInner、注册表、消息总线与下单路径](/nautilus-trader/figures/python-strategy-dispatch.svg)

怎么读这张图：右边是 Rust 核心，所有状态都在这里；中间是一次回调要做的四件事；左边是你写的代码和你拿到的东西。蓝色箭头是回调的方向，橙色箭头是下单的方向。

一根 K 线到达时，前半段和第 10 章讲的完全一样：消息总线的处理函数从 Actor 注册表里找到这个策略（找到的是 `PyStrategyInner`），调用框架的 `handle_bar`，先更新注册在它上面的指标（第 12 章第 4 节），再调用 `on_bar`。到这里为止都是 Rust。`PyStrategyInner` 的 `on_bar` 是这样的：

```rust
// 节选自 crates/trading/src/python/strategy.rs
fn on_bar(&mut self, bar: &Bar) -> anyhow::Result<()> {
    self.dispatch_on_bar(*bar)
        .map_err(|e| anyhow::anyhow!("Python on_bar failed:\n{}", format_exception(&e)))
}

fn dispatch_on_bar(&mut self, bar: Bar) -> PyResult<()> {
    if let Some(py_self) = self.python_instance()? {               // ① 升级弱引用
        Python::attach(|py| {                                       // ② 拿 GIL
            py_self.call_method1(py, "on_bar", (bar.into_py_any(py)?,))  // ③ 拷贝 ④ 按名字调用
        })?;
    }
    Ok(())
}
```

四步各有代价：

1. **升级弱引用**，拿到你的 Python 对象。
2. **`Python::attach`**，拿到 GIL。实盘里节点运行时释放了 GIL（第 29 章第 4 节），每次回调都要重新拿。
3. **`bar.into_py_any`**，把 Rust 的 `Bar` 拷贝成一个新的 Python 对象。`Bar` 是值类型，你拿到的是一份副本。
4. **`call_method1("on_bar", …)`**，按名字查找方法：找到你覆盖的 Python 函数，或者基类里 Rust 的空实现。

注意第 4 步：框架**不检查**你是否覆盖了这个方法。只要订阅了数据，每条消息都会走完这四步，哪怕最后调用的是一个什么都不做的 Rust 方法。第 8 节实测，订阅了成交但不覆盖 `on_trade`，和覆盖成 `pass` 的开销几乎一样。

**异常。** Python 方法抛出的异常被转成 `anyhow` 错误，带上完整的 Python traceback。之后的处理取决于是哪个回调：

- **数据和事件回调**（`on_bar`、`on_trade`、`on_order_filled` 等）：按第 10 章的规则只记一条 ERROR 日志，这条消息的处理到此为止，后面的消息照常送达。实验里 `on_bar` 在第 3 根 K 线抛异常，279 根 K 线全部送达，回测正常结束。
- **`on_start`**：启动失败。回测里 `engine.run()` 直接抛出 `RuntimeError: Failed to start trader: Python on_start failed: …`。

所以数据回调里的异常不会让你的策略停下来，只会让它悄悄地少处理一些消息。生产环境里应该在回调里自己捕获异常，或者打开第 14 章的 `shutdown_on_error`。

## 4. 从 Python 调 Rust：句柄与快照 {#handles}

反方向，策略里用到的几个属性都是 Rust 状态的包装：

| 属性 | 是什么 |
| --- | --- |
| `self.cache` | 包装同一个 `Rc<RefCell<Cache>>`；读取返回拷贝 |
| `self.portfolio` | 包装组合（第 22 章） |
| `self.clock` | 组件时钟（第 17 章） |
| `self.order_factory` | 订单工厂，生成客户端订单 ID |

`self.submit_order(order)` 走的是第 9 章 Rust 策略的同一条路径：`StrategyCore` 生成提交命令，经风控引擎的 `queue_execute` 进执行引擎（第 19、20 章）。

最容易出错的是“拷贝”这件事。订单是值：你在 `on_bar` 里创建并提交的那个 `order` 对象，之后不会自己变。实验里，成交事件到达时，手里那个对象的状态还是 `INITIALIZED`，而 `self.cache.order(order.client_order_id)` 读到的是 `PARTIALLY_FILLED`、`FILLED`；同一个订单连续读两次缓存，得到的是两个不同的 Python 对象。要知道订单现在的状态，每次都从缓存读，或者看事件本身。

## 5. 线程、GIL 与计时器 {#threads}

回调总是在核心线程上执行（第 30 章），对 Python 策略来说，核心线程就是调用 `run()` 的那个 Python 线程：

- **回测**：`engine.run()` 在调用它的线程上同步跑完整个回测，所有回调都在这个线程上。
- **实盘**：`node.run()` 先释放 GIL，再在当前线程上驱动节点的事件循环（第 29 章第 4 节）。回调时临时拿回 GIL，执行完再释放。所以节点运行期间，进程里别的 Python 线程照样能跑：实验里一个纯 Python 的计数线程，在节点运行的 1 秒里循环次数和主线程空闲时差不多。

**计时器回调。** `self.clock.set_timer(...)` 不带回调时，到点调用 `on_time_event`；带一个 Python 函数作回调时，调用那个函数。第 32 章第 4 节的表里说，Python 回调只有在“没有时间事件发送端”时才会在工作线程上直接调用；节点里的组件时钟都有发送端，所以实验里两种计时器回调都在主线程上执行，和其他回调一样。

官方文档对回调的要求只有一句话：同步执行，尽快返回。阻塞的 I/O、模型推理、长计算都会推迟行情和订单的处理，要交给线程池或别的进程，结果再通过消息送回来。

## 6. 开销：什么时候该换成 Rust {#cost}

第 8 节测了五种情况，每种跑三遍取最快的一次：不订阅成交；订阅但不覆盖 `on_trade`；覆盖成 `pass`；在 `on_trade` 里读价格和数量做一次乘法；在 `on_trade` 里查一次缓存。结论：

- 一次空回调（拿 GIL、拷贝成交、按名字调用）约 1 微秒。
- 在回调里读两个字段、转成 `float`，再多 1 微秒左右；查一次缓存（又一次拷贝）再多约 0.3 微秒。

这些数字来自 `make build-debug` 编出的未优化扩展模块，发布版 wheel 会快得多，只能当数量级看。但比例是稳定的：Python 策略的成本主要在“每条消息一次跨边界”，而不在你写的那几行。所以：

- 分钟级 K 线、每天几千次回调，Python 完全够用。
- 逐笔成交、逐笔报价、订单簿增量这类每秒成千上万条的数据，回调本身就是主要开销；把高频的部分（比如自己维护的指标）用 Rust 写，或者降低订阅频率（第 11 章的 K 线聚合在 Rust 里完成）。
- 每注册一个 Python 指标，每条消息还要再跨一次边界（第 12 章第 6 节）。

## 7. Python 策略的边界 {#boundaries}

几件 Python 策略做不到或者做法不同的事：

- **确定性仿真不覆盖 Python。** 第 37 章说过，DST 在 Rust 测试框架里运行，不启动 Python。
- **节点不能并存。** 官方文档明确不支持同一个进程里并发运行多个 `LiveNode` 或 `BacktestNode`；同一个线程上建第二个 `LiveNode` 前，要先释放前一个（第 30 章第 6 节）。
- **状态保存只认字节。** `on_save` 要返回 `dict[str, bytes]`，`on_load` 收到同样的字典，前提是缓存有数据库后端（第 14 章）。
- **用 Python 写适配器是另一回事。** 数据和执行客户端走 `nautilus_trader.live.clients` 的 Python 基类和 asyncio，规则见第 38 章附录 C 的路线 B。

## 8. 动手验证 {#lab}

实验是一个 Python 脚本，分七段，每段对应本章的一节。

::: info 实验环境
Linux（aarch64，4 核）上的 Python 3.14，nautilus_trader 2.0 的扩展模块由“从零编译”一章的 `make build-debug` 编出（未优化），对应提交 `364254f`。代码是 <a href="/nautilus-trader/code/python-lab/ch39_python_strategy.py" download><code>ch39_python_strategy.py</code></a>（[在 GitHub 查看](https://github.com/lewislau86/lewislau86.github.io/tree/master/docs/public/nautilus-trader/code/python-lab)），运行命令是 `uv run --project python --no-sync python ch39_python_strategy.py [段落名]`。下面的输出原样摘录，耗时每次运行略有不同。
:::

**是什么，以及注册前的样子：**

<<< @/public/nautilus-trader/code/python-lab/ch39_python_strategy.py#what

```text
Strategy.on_bar : method_descriptor (implemented in Rust)
Mine.on_bar     : function (your Python override)
Mine.on_trade   : method_descriptor (inherited from Rust)
before registration: strategy_id = Mine-None
before registration: self.clock -> Strategy must be registered with a trader before accessing clock
```

**策略 ID 与标签：**

<<< @/public/nautilus-trader/code/python-lab/ch39_python_strategy.py#ids

```text
  registered ids: ['Mine-000', 'Mine-001', 'Mine-007']
  add LAB-001: RuntimeError: Strategy order_id_tag conflict for '001', explicitly define unique order_id_tag values
  add LAB-002: ok
```

两个没有配置的 `Mine` 拿到标签 `000`、`001`，配置了 `order_id_tag` 的用 `007`；明确指定 `LAB-001` 的那个因为标签 `001` 已被占用而注册失败，`LAB-002` 没问题。

**回调、拷贝与快照：**

<<< @/public/nautilus-trader/code/python-lab/ch39_python_strategy.py#callbacks

```text
  bar 3: submitted O-20200814-100347-001-000-1, held object status = INITIALIZED
  on_order_filled: held object status = INITIALIZED, cache.order(...) status = PARTIALLY_FILLED
  two cache reads are the same object: False
  on_order_filled: held object status = INITIALIZED, cache.order(...) status = FILLED
  two cache reads are the same object: False
  bars delivered: 279
  callbacks ran on the thread that called engine.run(): True
  first bar kept after the run: close = 423.31
```

市价单分两笔成交，所以 `on_order_filled` 被调用两次。每次手里的对象都还是 `INITIALIZED`，缓存里的状态从 `PARTIALLY_FILLED` 变成 `FILLED`；两次读缓存得到两个不同的对象。所有回调都在调用 `engine.run()` 的主线程上；第一根 K 线在回测结束后仍然可用，因为它是一份独立的拷贝。

**异常：**

<<< @/public/nautilus-trader/code/python-lab/ch39_python_strategy.py#errors

```text
  on_start raised: engine.run() -> RuntimeError: Failed to start trader: Python on_start failed:
  engine.run() returned normally; on_bar was called 279 times
```

`on_bar` 抛出的异常在日志里是这样（输出到 stderr）：

```text
2020-08-14T10:03:47.112000000Z [ERROR] BACKTESTER-001.nautilus_common::actor::data_actor: Python on_bar failed:
Traceback (most recent call last):
  File "/tmp/pylab/ch39_python_strategy.py", line 141, in on_bar
    raise ValueError("boom in on_bar")
ValueError: boom in on_bar
```

**不保留引用：**

<<< @/public/nautilus-trader/code/python-lab/ch39_python_strategy.py#weakref

```text
  strategy added without keeping a reference: on_bar called 279 times
```

**实盘节点里的线程与 GIL：**

<<< @/public/nautilus-trader/code/python-lab/ch39_python_strategy.py#live

```text
  on_start                     thread=MainThread   main thread=True
  callback(with_callback)      thread=MainThread   main thread=True
  on_time_event(plain)         thread=MainThread   main thread=True
  callback(with_callback)      thread=MainThread   main thread=True
  on_time_event(plain)         thread=MainThread   main thread=True
  on_time_event(plain)         thread=MainThread   main thread=True
  on_stop                      thread=MainThread   main thread=True
  spinner alone for 1.10 s (main thread sleeping): 38,359,052 loops
  spinner while run() blocked for 1.03 s: 35,657,201 loops
```

节点不接任何交易所，1 秒后由一个 `threading.Timer` 调用 `handle.stop()`。所有回调，包括带 Python 回调函数的计时器，都在主线程上执行。纯 Python 的计数线程在节点运行期间的循环次数，和主线程只是 `sleep` 时相差不到一成，说明 `run()` 期间 GIL 基本是空闲的。

**开销：**

<<< @/public/nautilus-trader/code/python-lab/ch39_python_strategy.py#overhead

```text
== overhead
  not subscribed                                  0.365 s
  subscribed, on_trade not overridden             0.454 s  (+ 1.27 µs per trade)
  subscribed, on_trade: pass                      0.428 s  (+ 0.90 µs per trade)
  subscribed, on_trade reads price and size       0.538 s  (+ 2.47 µs per trade)
  subscribed, on_trade queries cache.instrument   0.562 s  (+ 2.81 µs per trade)
```

括号里是相对“不订阅”多出的时间，除以 69,806 笔成交。“不覆盖”和“`pass`”的差别在测量噪声以内，说明成本在跨边界本身。

::: warning 常见误区
- **以为 Python 的 `Strategy` 是一个 Python 类。** 它是 Rust 类，你的子类只是覆盖了几个回调；状态都在 Rust 一侧。
- **在回调里调用会同步触发自己回调的方法，再在里层修改订阅。** 外层调用还持有对象的借用，里层会报 `Already borrowed`（第 40 章）。
- **在子类配置的 `__init__` 里把参数传给 `super().__init__()`。** `StrategyConfig` 的参数由 `__new__` 接收，`__init__` 用 `**_kwargs` 接住、无参调用父类。
- **手动指定的策略 ID 和自动分配的撞标签。** 标签要全局唯一，`LAB-001` 会和自动分配的 `XXX-001` 冲突；要么都显式指定，要么用 `order_id_tag` 错开。
- **拿着提交时的订单对象等它变化。** 它是拷贝，要从缓存重新读，或者看事件。
- **以为不覆盖某个回调就没有开销。** 只要订阅了，每条消息都会跨一次边界。
- **以为 `on_bar` 抛异常会让回测停下来。** 只记日志，后面的消息照常处理；只有 `on_start` 的异常会让启动失败。
- **在回调里做阻塞操作。** 回调在核心线程上同步执行，会拖住所有行情和订单的处理。
:::

## 本章结论

v2 的 Python 策略是第 9 章 Rust 策略框架的一个绑定：`Strategy` 是一个可子类化、只能单线程使用、支持弱引用的 Rust 类，持有实现了 `DataActor` 和 `Strategy` trait 的 `PyStrategyInner`；配置对象原样保留，策略 ID 由配置或“类名-标签”决定，标签必须唯一。注册时 Inner 进入组件和 Actor 注册表，Python 对象被一张强引用表保留。每次回调要升级弱引用、拿 GIL、把数据拷贝成新的 Python 对象、按名字调用方法，不论子类是否覆盖；数据回调里的异常只记日志，`on_start` 的异常让启动失败。反方向，缓存等句柄包装的是同一份 Rust 状态，但每次读取返回拷贝，下单走 Rust 策略的同一条路径。回调都在调用 `run()` 的线程上执行，实盘节点运行时释放 GIL。实测一次空回调约 1 微秒（未优化构建），成本主要在跨边界本身，高频数据上的逻辑适合放到 Rust 里。

## 检查理解

1. 一个 Python 策略订阅了 BTCUSDT 的逐笔成交，但只覆盖了 `on_bar`，`on_trade` 没写。每笔成交会进入 Python 吗？为什么？

   <details><summary>参考答案</summary>

   会。订阅了成交，消息总线就会把每笔成交交给这个策略的 Rust 一侧，`PyStrategyInner::on_trade` 照样升级弱引用、拿 GIL、把成交拷贝成 Python 对象，再按名字调用 `on_trade`，找到的是基类里 Rust 的空实现。框架不检查方法是否被覆盖。不需要成交就不要订阅它；只需要 K 线时，订阅 K 线即可（聚合在 Rust 里完成）。

   </details>

2. 策略在 `on_bar` 里提交了一张限价单并把 `order` 存在 `self.pending` 里，几秒后在另一个 `on_bar` 里判断 `self.pending.status == OrderStatus.ACCEPTED`。这个判断会成立吗？应该怎样写？

   <details><summary>参考答案</summary>

   不会成立，`self.pending` 是提交那一刻的拷贝，状态永远停在 `INITIALIZED`。应该保存 `client_order_id`，需要时用 `self.cache.order(client_order_id)` 读最新的快照，或者在 `on_order_accepted` 等事件回调里更新自己的记录。

   </details>

3. 实盘节点运行时，你在策略的 `on_start` 里起了一个 Python 线程定期做模型推理。这个线程能跑起来吗？推理结果应该怎样交回策略？

   <details><summary>参考答案</summary>

   能。`node.run()` 释放了 GIL，只在回调时临时拿回，所以别的 Python 线程能正常运行（第 8 节的计数线程就是证据）。但策略对象是 `unsendable` 的，状态都在核心线程上，不能在推理线程里直接调用 `submit_order` 或读写策略的属性。应该把结果交回核心线程：比如推理线程只写一个线程安全的队列，策略设一个计时器，在计时器回调里（核心线程上）取出结果再决定下单。消息总线也只能在核心线程上使用，不能从推理线程直接发布信号。

   </details>

## 参考资料

- 官方文档：[Python](https://nautilustrader.io/docs/latest/concepts/python/) · [Strategies](https://nautilustrader.io/docs/latest/concepts/strategies/) · [Migration from v1](https://github.com/nautechsystems/nautilus_trader/blob/develop/MIGRATION_V2.md)
- 源码：[`crates/trading/src/python/strategy.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/trading/src/python/strategy.rs) · [`crates/system/src/python/registration.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/system/src/python/registration.rs) · [`crates/common/src/python/wrappers.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/common/src/python/wrappers.rs) · [`crates/backtest/src/python/engine.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/backtest/src/python/engine.rs) · [`docs/tutorials/ema_cross.py`](https://github.com/nautechsystems/nautilus_trader/blob/develop/docs/tutorials/ema_cross.py) · [`examples/backtest/callback_borrow_reentrancy.py`](https://github.com/nautechsystems/nautilus_trader/blob/develop/examples/backtest/callback_borrow_reentrancy.py)
- 实验代码：[`python-lab`](https://github.com/lewislau86/lewislau86.github.io/tree/master/docs/public/nautilus-trader/code/python-lab)
- 配图由 `scripts/generate-nautilus-trader-figures.py` 生成。

策略之外，Python 里还能写只收数据的 Actor、拆单的执行算法和管理其他组件的 Controller。下一章看它们和策略的异同：[第 40 章：Python 的其他组件](./python-components.md)。
