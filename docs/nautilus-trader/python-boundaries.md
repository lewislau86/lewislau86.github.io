---
title: "第 44 章：边界与迁移"
description: Python 层的边界：生成的类型存根才是公开接口，存根里没有的运行时属性不受支持；数值以定点整数跨过边界，wheel 是 16 位小数的高精度模式，运算结果可能是 Price、Decimal 或 float；Rust 的错误在边界上映射为 ValueError、TypeError、OverflowError，release 构建里的 panic 会终止进程；Python 读到的是拷贝。v1 迁移到 v2 时，导入路径和方法名的错误会立刻报出，旧回调名、NO_* 常量、avg_px 的类型、is_initialized 这几类变化不会报错；最后讨论什么时候该把 Python 代码换成 Rust。
---

# 第 44 章：边界与迁移

[全书目录](./index.md) · [上一章](./python-adapter.md) · [附录](./core-topics.md)

::: tip 本章学习目标
知道 Python 层的公开接口以什么为准、怎样用它检查自己的代码；知道数值、错误和对象跨过 Python 与 Rust 的边界时会变成什么；能把一个 v1 的 Python 策略迁移到 v2，并说出哪些错误会立刻报出、哪些不会；能根据具体条件判断一段代码该留在 Python 还是换成 Rust。

**源码版本：** `develop` 分支，提交 `364254f`（2026-11-18）。存根由 `python/generate_stubs.py` 调用 `python-stub-gen` 生成，放在 `python/nautilus_trader/` 下各个模块的 `__init__.pyi`；迁移指南是仓库根目录的 `MIGRATION_V2.md`。

**对应官方文档：** [Python](https://nautilustrader.io/docs/latest/concepts/python/)（Public API contract、Support boundaries、Choosing Python or Rust 三节） · [Value Types](https://nautilustrader.io/docs/latest/concepts/value_types/) · [Installation](https://nautilustrader.io/docs/latest/getting_started/installation/)（Precision mode 一节） · [Migrate From v1 to v2](https://github.com/nautechsystems/nautilus_trader/blob/develop/MIGRATION_V2.md)
:::

第 39～43 章分别看了 Python 层的几个部分：策略、其他组件、回测、实盘、适配器。每一章都碰到过同一类问题：Python 对象背后是 Rust 的状态，跨过这条边界时，有些东西会被拷贝、转换或拒绝。这一章把这些规则放在一起，再看两个实际问题：手上有 v1 的代码，怎样迁移；新写的代码，什么时候该用 Rust。

主线例子：一个在 v1 上跑了两年的港股策略，要迁到 v2。

## 1. 公开接口以存根为准 {#contract}

v2 的 Python 包大部分是 PyO3 绑定的 Rust 类型。哪些类、方法、属性、参数类型是受支持的？官方的答案是：**生成的类型存根**。`python/nautilus_trader/` 下每个模块都有一个 `__init__.pyi`，由 `python-stub-gen` 从 Rust 绑定的源码生成（`make py-stubs`，`make build-debug` 会先跑这一步），记录公开的类、方法、属性、参数和返回类型。实验里这个提交一共有 42 个 `.pyi` 文件，约 2.6 万行。

几条规则：

- **存根里没有的运行时属性不算公开接口。** 用 `dir()` 能看到、但存根里没有的东西，随时可能变化。另外，文档化的 Python 客户端、品种提供者和可导入配置类（第 43 章）也是公开接口。
- **存根是生成物，不是独立的接口定义。** 绑定变了，改的是 Rust 源码，然后重新生成；手改 `.pyi` 没有意义。
- **静态类型检查器能用。** 存根完整描述了参数和返回类型，mypy、pyright 可以直接拿来检查用户代码。迁移时，这是找出旧名字最便宜的办法（第 4 节）。

有一类“运行时能调用、存根里没有”的例外，官方点名列出了几个（Kraken 的批量下单方法），说明这条规则是认真执行的：没有存根的东西，静态检查器解析不了，也不在支持范围内。

## 2. 数值怎样跨过边界 {#values}

第 2 章讲过，`Price`、`Quantity`、`Money` 内部是定点整数加精度。跨到 Python 这一侧，要注意三件事。

**wheel 是高精度模式。** 官方 Python wheel 和源码构建（`python/pyproject.toml` 的 maturin feature 里有 `high-precision`）都是 128 位、最多 16 位小数；纯 Rust 程序默认是 64 位、最多 9 位小数，要自己打开 `high-precision`（第 0 章第 5.1 节）。Python 里可以直接查：`nautilus_trader.model.HIGH_PRECISION` 是 1，`FIXED_PRECISION` 是 16。从 `float` 构造时最多 16 位小数；Python 包还打开了 `defi` 特性，从字符串构造可以到 18 位（wei 精度）。

**运算结果的类型取决于对方。** 同类相加减仍是 `Price`；乘除、和 `int` 或 `Decimal` 运算得到 `Decimal`；和 `float` 运算得到 `float`。用 `float` 构造会按精度舍入，`Price(1.25, 1)` 得到 `1.3`。

**比较会因类型而变。** `Price` 和 `float` 比较是按数值的（`Price.from_str("0.7") == 0.7` 为真），但 Python 自己的 `Decimal` 和 `float` 比较是精确的：`Decimal("0.70000") == 0.7` 为假，因为 0.7 这个 `float` 并不精确等于 0.7。v2 把 `Order.avg_px` 和 `Order.slippage` 从 `float` 改成了 `Decimal`，v1 里 `order.avg_px == 423.76` 这样的写法，v2 里会悄悄变成假。

## 3. 错误怎样跨过边界 {#errors}

**参数先校验。** PyO3 在 Rust 代码执行之前校验参数类型，类型不对抛 `TypeError`（比如把字符串传给 `Price(value, precision)` 的 `value`）。

**可失败的操作映射为 Python 异常。** Rust 侧返回错误的操作，在边界上变成 Python 异常：解析失败、超出范围、精度超限、货币不匹配都是 `ValueError`，定点运算溢出是 `OverflowError`。官方的要求是：代码按文档里的异常类型处理，不要依赖 Rust 内部错误的表示（比如解析异常消息里的 Rust 类型名）。

**panic 不是异常。** 上面这些是 Rust 侧“预料到的错误”。真正的 bug 会 panic；仓库的 release 配置是 `panic = "abort"`，所以用官方 wheel 时，一个 panic 会直接终止进程，Python 的 `try/except` 接不住。

**回调里的异常留在 Python 这一侧。** 反方向，Python 回调抛出的异常不会穿回 Rust：数据回调里的异常只记日志，`on_start` 里的异常让启动失败（第 39 章）；适配器钩子的异常记日志后执行下一个命令（第 43 章）；回测里可以用 `shutdown_on_error` 让第一个错误日志结束运行（第 41 章）。

**对象是拷贝。** 最后一类边界规则前面几章反复出现：Python 从缓存、组合、命令里读到的都是拷贝或快照，改了不影响内核（第 39、43 章）；托管运行时节点被借出，只能用事先取好的句柄（第 42 章）；同一个进程只能有一个节点（第 42 章）。

## 4. 从 v1 迁移 {#migration}

![Python 与 Rust 的边界：接口以生成的存根为准，数值是定点整数，错误映射为 ValueError、TypeError、OverflowError，Python 读到的是拷贝；v1 迁移到 v2 时，导入路径、方法名、参数类型的错误会立刻报出，旧回调名、NO_* 常量、avg_px 的类型、is_initialized 的含义这几类变化不会报错](/nautilus-trader/figures/python-boundaries.svg)

怎么读这张图：上半部分是第 1～3 节的四条边界规则；下半部分把迁移时会遇到的错误分成两类，左边会立刻报错，右边不会。

v1 是 Cython 实现，v2 是 Rust 内核加 PyO3 绑定。两者都以 `nautilus_trader` 的名字安装和导入，所以**要用两个独立的虚拟环境**，不能装在一起。v1 留在 `develop_v1` 分支上，切换之后只接受约三个月的关键安全修复。官方建议一次迁一个工作流：先改导入和配置，再改组件和模型 API，然后是节点、数据目录，最后对照“已知限制”一节。

`MIGRATION_V2.md` 有一千三百多行，大部分是对照表。按迁移时出错的方式，可以分成两类。

**响亮的失败：一运行就报错。** 这类改动多，但好处理：

| v1 | v2 | 不改会怎样 |
| --- | --- | --- |
| `nautilus_trader.live.node.TradingNode` | `nautilus_trader.live.LiveNode` | `ModuleNotFoundError` |
| `nautilus_trader.backtest.engine.BacktestEngine` | `nautilus_trader.backtest.BacktestEngine` | `ModuleNotFoundError` |
| `TradingNodeConfig`、`LoggingConfig` | `LiveNodeConfig`、`LoggerConfig` | `ImportError` |
| `subscribe_quote_ticks` | `subscribe_quotes` | `AttributeError` |
| `cache.quote_tick` | `cache.quote` | `AttributeError` |
| `Strategy.id` | `Strategy.strategy_id` | `AttributeError` |
| `Order.events`、`Position.events` 属性 | `events()` 方法 | 拿到方法对象，迭代时 `TypeError` |

配置类的迁移也属于这一类：v1 的配置是 msgspec 的 `Struct`，带类型注解的字段不会带到 v2；v2 的写法是关键字参数的 `__init__` 加 `**_kwargs`，再无参调用 `super().__init__()`（第 39 章）。

**沉默的失败：不报错，结果不对。** 这类改动少，但危险：

- **回调改名。** `on_quote_tick` → `on_quote`，`on_trade_tick` → `on_trade`，`on_order_book_deltas` → `on_book_deltas`，等等。v1 名字的方法在 v2 里只是一个普通方法，没有任何东西调用它，也不报错。实验里一个只改了订阅、没改回调名的策略，`on_trade_tick` 被调用 0 次，`on_trade` 被调用 1000 次。
- **`NO_*` 常量变成 `None`。** `OrderSide.NO_ORDER_SIDE`、`PositionSide.NO_POSITION_SIDE`、`TriggerType.NO_TRIGGER` 等现在的值是 `None`，不再是枚举成员，没有 `.name`、`.value`。`side == OrderSide.NO_ORDER_SIDE` 仍然能工作，但 `side.name` 会在 `side` 为 `None` 时出错；`OrderStatusReport.order_side` 等字段也可能返回 `None`。
- **`avg_px` 从 `float` 变成 `Decimal`。** 第 2 节说过，和 `float` 的相等比较会变成假。
- **`is_initialized` 不能直接换成 `is_ready()`。** v1 的 `is_initialized` 是“状态已经越过 `PRE_INITIALIZED`”；v2 的 `is_ready()` 是“状态恰好是 `READY`”，运行中、已停止的组件都返回假。`is_initialized` 本身在 v2 里没有了（会抛 `AttributeError`），危险的是顺手换成 `is_ready()`。要表达原来的意思，比较 `state()` 和 `ComponentState.PRE_INITIALIZED`。
- **其他语义变化。** 比如直接调用 `Position.apply` 时，穿过零的成交会把开仓价重置为这笔成交的价格（v1 保留旧方向的开仓价）；`AggressorSide.BUYER` 改成 `BUY`。这些要逐条读迁移指南。

**怎样把沉默的失败变成响亮的。** 两个办法。一是对照存根：实验里写了一个几十行的检查脚本，用 `ast` 解析策略源码，把以 `on_` 开头、但 `Strategy` 存根里没有的方法，以及 `self.xxx` 里存根没有的名字列出来；类型检查器能做得更完整。二是跑一遍回测，核对每个回调实际被调用的次数和结果，再上实盘。

**还没有对应物的部分。** 迁移指南最后列出了 v2 还不支持的东西，迁移前要确认自己没用到，比如：`BacktestNode` 的数据配置不支持 v1 的数据客户端工厂、即时下载和自定义数据；`BacktestNode` 内部构建引擎，所以不能注册自定义的组合统计，要用 `BacktestEngine`（第 41 章）；带自定义 Python 客户端的节点不支持数据库后端的缓存（第 43 章）；PostgreSQL 后端不保存组件状态。v1 的 Cython 适配器要按第 43 章的接口重写。

## 5. 留在 Python，还是换成 Rust {#choose}

官方的说法很简短：应用组装、快速开发策略、分析工具、需要和 Python 生态集成时用 Python；程序必须在没有 Python 运行时的环境里运行，或者需要原生 trait、直接控制 crate 时用 Rust。两条路用的是同一套 Rust 领域模型和引擎；除了 Controller 和 tearsheet 只在 Python 侧、执行算法两边都只有 TWAP 之外，组件在两边都能用。

结合前面几章的实测，可以更具体一些：

| 条件 | 倾向 | 依据 |
| --- | --- | --- |
| 回调频率低（K 线、定时器、订单事件） | Python | 一次回调约 1 微秒的开销可以忽略（第 39 章） |
| 逐笔成交、盘口增量上的逻辑 | 热路径换成 Rust | 回调开销成为主要成本（第 39 章） |
| 研究、参数扫描、报告 | Python | `BacktestEngine` 的 `reset`、DataFrame 报告、tearsheet（第 41 章） |
| 要嵌进 ASGI 服务 | Python | `run_async()` 托管在宿主循环上（第 42 章） |
| 交易所协议的编解码、高频推送 | Rust（路线 A 或 C） | 第 38 章附录 C |
| 要用 Redis 或 PostgreSQL 做缓存后端，同时有自定义客户端 | Rust 适配器 | Python 客户端不支持（第 43 章） |
| 需要可重放的异步测试 | Rust | 确定性仿真在 Rust 侧（第 37 章） |
| 部署环境不能装 Python | Rust | 整个节点用 Rust（第 9、30 章） |

不必一次决定。常见的路径是：先全部用 Python 跑通；发现某个回调是热点，就把那部分写成 Rust 组件（编进扩展模块，或者整个节点换成 Rust）；协议层先用 Python 适配器（路线 B），稳定之后换成 Rust（路线 C 或 A）。边界规则在每一步都一样，这一章的内容在每一步都适用。

## 6. 动手验证 {#lab}

::: info 实验环境
Linux（aarch64，4 核）上的 Python 3.14，nautilus_trader 2.0 的扩展模块由“从零编译”一章的 `make build-debug` 编出，对应提交 `364254f`。代码是 <a href="/nautilus-trader/code/python-lab/ch44_python_boundaries.py" download><code>ch44_python_boundaries.py</code></a>（[在 GitHub 查看](https://github.com/lewislau86/lewislau86.github.io/tree/master/docs/public/nautilus-trader/code/python-lab)），运行命令是 `uv run --project python --no-sync python ch44_python_boundaries.py [段落名]`。下面的输出原样摘录。
:::

**对照存根检查一个 v1 策略。** `stub_methods` 用 `ast` 读出存根里 `Strategy` 类声明的成员；`lint` 检查一段 v1 风格的策略源码：

<<< @/public/nautilus-trader/code/python-lab/ch44_python_boundaries.py#contract

```text
== contract
  42 generated .pyi files, 26418 lines
  HIGH_PRECISION=1 FIXED_PRECISION=16 FIXED_SCALAR=1e+16
  Strategy stub declares 170 members, 63 of them on_* callbacks
  line 4: self.subscribe_quote_ticks is not in the Strategy stub
  line 5: self.is_initialized is not in the Strategy stub
  line 6: self.id is not in the Strategy stub
  line 7: def on_quote_tick is not a Strategy callback; it will never be called
  line 9: def on_order_book_deltas is not a Strategy callback; it will never be called
```

五处都找到了。其中第 4～6 行运行时也会报 `AttributeError`，第 7、9 行运行时不会报任何错。

**数值：**

<<< @/public/nautilus-trader/code/python-lab/ch44_python_boundaries.py#values

```text
== values
  Price + Price                      -> Price    1.75
  Price + Decimal                    -> Decimal  1.75
  Price + int                        -> Decimal  2.50
  Price + float                      -> float    1.75
  Price * Price                      -> Decimal  2.2500
  Price(1.25, 1)                     -> Price    1.3
  Price.from_str('1.' + 16 digits)   -> Price    1.1234567890123456
  Price.from_str('1.' + 17 digits)   -> Price    1.12345678901234567
  Price.from_str('0.7') == 0.7      -> True
  Decimal('0.70000') == 0.7         -> False
  OrderSide.NO_ORDER_SIDE           -> None
  PositionSide.NO_POSITION_SIDE     -> None
```

**错误：**

<<< @/public/nautilus-trader/code/python-lab/ch44_python_boundaries.py#errors

```text
== errors
  Price.from_str('abc')                  ValueError: Error parsing `input` string 'abc' as Decimal: Invalid decimal value '
  Price('1.5', 1)                        TypeError: must be real number, not str
  Price(1.5, 17)                         ValueError: `precision` exceeded maximum float precision (16), use `Price::from_we
  Quantity(-1, 0)                        ValueError: invalid f64 for 'value' not in range [0, 34028236692093], was -1
  Quantity(1, 0) - Quantity(2, 0)        ValueError: Quantity subtraction would result in negative value: 1 - 2
  Price(1.7e13, 0) + Price(1.7e13, 0)    OverflowError: Fixed-point arithmetic overflow
  Money USD + Money HKD                  ValueError: Currency mismatch: USD vs HKD
  InstrumentId.from_str('BAD')           ValueError: invalid `InstrumentId` value 'BAD': missing '.' separator between symb
  TraderId('nohyphen')                   ValueError: invalid string for 'value' did not contain '-', was 'nohyphen'
  Currency.from_str('XXXQ', strict=True) ValueError: Unknown currency: XXXQ
```

全部是普通的 Python 异常，`except Exception` 都能接住。范围上限和第 2 章的数字一致：高精度模式下 `Quantity` 最大约 34 万亿，`Price` 约 ±17 万亿，两个最大价格相加溢出。

**沉默的失败。** 一个改了一半的策略：订阅改成了 v2 的名字，成交回调还是 v1 的名字。用 1000 笔成交跑一次回测：

<<< @/public/nautilus-trader/code/python-lab/ch44_python_boundaries.py#silent

```text
== silent
  loud: ModuleNotFoundError: No module named 'nautilus_trader.live.node'
  loud: 'Ported' object has no attribute 'subscribe_trade_ticks'
  on_trade_tick (v1 name) called 0 times; on_trade called 1000 times
  order.avg_px = Decimal('423.76') (Decimal); == 423.76 as float: False
  strategy.state() = ComponentState.STOPPED, is_ready() = False, hasattr(is_initialized) = False
```

旧的导入路径和旧的订阅方法立刻报错；旧名字的回调一次也没有被调用，没有任何警告。订单的 `avg_px` 是 `Decimal('423.76')`，和 `float` 的 423.76 比较为假。停止后的策略 `is_ready()` 为假，`is_initialized` 已经不存在。

::: warning 常见误区
- **用 `dir()` 发现了一个方便的属性就直接用。** 存根里没有的东西不在支持范围内，可能在下个版本消失。
- **在同一个环境里装 v1 和 v2。** 两者导入名相同，要用两个虚拟环境。
- **迁移后“没报错”就以为迁完了。** 回调改名不会报错；用存根检查，再用回测核对回调次数。
- **把 `is_initialized` 换成 `is_ready()`。** 含义不同，运行中的组件 `is_ready()` 为假。
- **`avg_px == some_float`。** v2 的 `avg_px` 是 `Decimal`，和 `float` 精确比较；用 `Decimal("...")` 或 `Decimal(str(x))`。
- **用 `try/except` 兜底 Rust 侧的 panic。** release 构建里 panic 直接终止进程；能接住的只有映射过来的异常。
- **解析异常消息里的 Rust 类型名来判断错误种类。** 按文档化的异常类型处理，消息文本不是接口。
- **以为 Rust 程序和 Python 包的精度一样。** wheel 是 16 位小数，纯 Rust 默认 9 位，要显式打开 `high-precision`。
:::

## 本章结论

Python 层的公开接口以生成的类型存根为准，存根里没有的运行时属性不受支持，存根本身由 Rust 绑定源码生成，可以直接交给类型检查器。数值以定点整数跨过边界，wheel 是 16 位小数的高精度模式，和其他类型运算会得到 `Decimal` 或 `float`，`Decimal` 与 `float` 的比较是精确的。Rust 侧的可预料错误映射为 `ValueError`、`TypeError`、`OverflowError`，panic 在 release 构建里终止进程；Python 回调的异常留在 Python 这一侧。迁移 v1 代码时，导入路径、方法名、参数类型的错误会立刻报出，回调改名、`NO_*` 常量、`avg_px` 的类型、`is_initialized` 的含义这几类变化不会，要靠存根检查和回测核对发现。Python 和 Rust 用的是同一套内核，选哪一边取决于回调频率、部署环境和需要的特性，可以从 Python 起步，按热点逐步换成 Rust。

## 检查理解

1. 迁移后的策略跑回测，没有任何报错，但一笔交易都没有。日志里能看到订阅成功。最先该检查什么？

   <details><summary>参考答案</summary>

   先检查数据回调的名字是不是还停在 v1：`on_quote_tick`、`on_trade_tick`、`on_order_book_deltas` 在 v2 里不会被调用，也不报错。把它们改成 `on_quote`、`on_trade`、`on_book_deltas`。用类型检查器或对照 `Strategy` 存根的脚本能一次找出全部；回测时在回调里计数也能直接看出来。

   </details>

2. 一段 v1 代码写的是 `if order.avg_px == target_px: ...`，`target_px` 是 `float`。迁到 v2 后这个分支再也不进。为什么？怎样改？

   <details><summary>参考答案</summary>

   v2 的 `Order.avg_px` 是 `Decimal`，Python 的 `Decimal` 和 `float` 比较是精确的，而大多数小数在 `float` 里不能精确表示，比如 `Decimal("423.76") == 423.76` 为假。把 `target_px` 也做成 `Decimal`（`Decimal("423.76")` 或 `Decimal(str(target_px))`），或者把两边都转成 `Price` 后比较。

   </details>

3. 一个策略在逐笔成交上计算一个自定义指标，回测时 Python 回调占了大部分时间；另一个策略只在 1 分钟 K 线上做决策。你会怎样分配 Python 和 Rust？

   <details><summary>参考答案</summary>

   K 线策略留在 Python：每分钟一次回调，约 1 微秒的跨边界开销可以忽略，开发和调试更快。逐笔成交上的指标是热路径，把它用 Rust 实现（写法见第 12 章第 8 节的自定义指标教程），Python 策略只在指标结果上做决策；或者让 K 线聚合等预处理在 Rust 侧完成，降低到达 Python 的频率。如果整个策略都在热路径上，再考虑用 Rust 写整个策略或节点。

   </details>

## 参考资料

- 官方文档：[Python](https://nautilustrader.io/docs/latest/concepts/python/) · [Value Types](https://nautilustrader.io/docs/latest/concepts/value_types/) · [Installation](https://nautilustrader.io/docs/latest/getting_started/installation/) · [Rust](https://nautilustrader.io/docs/latest/concepts/rust/)（Capability matrix 一节）
- 迁移指南：[`MIGRATION_V2.md`](https://github.com/nautechsystems/nautilus_trader/blob/develop/MIGRATION_V2.md)
- 源码：[`python/generate_stubs.py`](https://github.com/nautechsystems/nautilus_trader/blob/develop/python/generate_stubs.py) · [`python/nautilus_trader/trading/__init__.pyi`](https://github.com/nautechsystems/nautilus_trader/blob/develop/python/nautilus_trader/trading/__init__.pyi) · [`Cargo.toml`](https://github.com/nautechsystems/nautilus_trader/blob/develop/Cargo.toml)（`[profile.release]`）
- 实验代码：[`python-lab`](https://github.com/lewislau86/lewislau86.github.io/tree/master/docs/public/nautilus-trader/code/python-lab)
- 配图由 `scripts/generate-nautilus-trader-figures.py` 生成。

第七部分到这里结束，全书正文也到此为止。附录把散落在各章的重点主题和常用配置汇总在一起，适合回头查阅：[附录：重点主题速览](./core-topics.md)。
