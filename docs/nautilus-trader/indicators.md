---
title: "第 12 章：指标"
description: NautilusTrader 的技术指标在哪里、长什么样、怎样被更新：nautilus-indicators crate 的 Indicator 与 MovingAverage trait，EMA、SMA、MACD、ATR 的实现细节，手动喂数据与注册到组件两种用法，Indicators 注册表怎样在 on_bar 之前更新指标，Rust 注册要打开的特性，Python 注册的指标怎样穿过语言边界、代价多大，怎样用历史数据预热，以及一个从零写指标的动手教程：定规格、实现 Indicator、用 rstest 和 proptest 写单元测试、在回测里和独立算法逐根对账，再用纯 Python 做一遍。
---

# 第 12 章：指标

[全书目录](./index.md) · [上一章](./bar-aggregation.md) · [下一章](./actors-and-config.md)

::: tip 本章学习目标
知道内置指标在哪个 crate、按什么分类、数值用什么类型；能读懂一个指标的实现（以 EMA 为例），说清它什么时候算“已初始化”；分得清手动喂数据和注册到组件两种用法，知道注册之后框架在什么时候、按什么顺序更新指标；知道 Rust 注册和 Python 注册各自要付出什么；能正确地用历史数据预热指标；能从零写一个指标，用单元测试守住手算值，并在回测里用独立算法验证它接到框架之后的数值。

**源码版本：** `develop` 分支，提交 `364254f`（2026-11-18）。指标在 `crates/indicators/`，注册表在 `crates/common/src/actor/indicators.rs`，Python 一侧的包装在 `crates/common/src/python/indicators.rs`。

**对应官方文档：** [Strategies](https://nautilustrader.io/docs/latest/concepts/strategies/) · [Data](https://nautilustrader.io/docs/latest/concepts/data/) 的 Register indicators before requesting data 一节
:::

上一章讲了 K 线怎样在 Rust 里合成。指标是 K 线之后的下一站：均线、RSI、布林带这些都在 Rust 里实现，Python 拿到的是同一批 Rust 结构体。和 K 线不同的是，指标不在引擎里，而是挂在你的策略上，由框架在调用 `on_bar` 之前替你更新。这一章先看指标本身，再看框架怎样更新它，最后看 Python 注册的指标怎样穿过语言边界。

::: info 关于本章的验证
第 1～7 节的结论来自源码和仓库自带的测试（`crates/common/src/actor/indicators.rs`、`crates/trading/src/python/strategy.rs` 里的测试用例）。第 8 节的代码在 Linux 上实际编译运行过：Rust 部分的单元测试和回测、Python 部分的单元测试和回测都通过，输出原样摘录；第 5 节的注册写法和 `indicators` 特性也借这个例子验证了。
:::

## 1. 指标在哪：nautilus-indicators {#crate}

全部内置指标在 `nautilus-indicators` 这个 crate 里，约两万行（含测试）。它只依赖 `nautilus-core` 和 `nautilus-model`，不依赖消息总线、缓存或引擎，所以可以脱离整个平台单独使用，比如在研究脚本里对一列价格算 EMA。

按目录分成五类：

| 目录 | 类别 | 例子 |
| :--- | :--- | :--- |
| `average/` | 均线与回归 | EMA、SMA、DEMA、HMA、WMA、Wilder（RMA）、AMA、VIDYA、VWAP、线性回归、Z 分数 |
| `momentum/` | 动量与震荡 | RSI、MACD、布林带、随机指标、CCI、ROC、Aroon、一目均衡表、OBV、KVO |
| `volatility/` | 波动率 | ATR、唐奇安通道、肯特纳通道、RVI、波动率比、模糊 K 线 |
| `ratio/` | 比率 | 效率比、价差分析器 |
| `book/` | 订单簿 | 订单簿失衡比 |

另外 `support/` 里放着几个内部工具（滚动矩、滚动最小二乘），`python/` 下是每个指标的 PyO3 方法。Python 的 `nautilus_trader.indicators` 模块就是 `_libnautilus.indicators` 的转出，里面没有一行 Python 实现。

指标内部全部用 `f64` 计算。行情里的 `Price`、`Quantity` 是定点数（第 0 章第 5.1 节），进指标时先转成 `f64`，这样做换来的是速度和实现上的简单；代价是指标值有浮点误差，比较两个指标值时不要用相等。

## 2. 一个指标长什么样 {#anatomy}

所有指标实现同一个 trait（`crates/indicators/src/indicator.rs`）：

```rust
pub trait Indicator {
    fn name(&self) -> String;
    fn has_inputs(&self) -> bool;     // 收到过数据没有
    fn initialized(&self) -> bool;    // 数据够了没有，值能不能用
    fn handle_quote(&mut self, quote: &QuoteTick) -> anyhow::Result<()> { /* 默认返回错误 */ }
    fn handle_trade(&mut self, trade: &TradeTick) { /* 默认 panic */ }
    fn handle_bar(&mut self, bar: &Bar)           { /* 默认 panic */ }
    fn handle_book(&mut self, book: &OrderBook)   { /* 默认 panic */ }
    // handle_delta / handle_deltas / handle_depth 同样默认 panic
    fn reset(&mut self);
}

pub trait MovingAverage: Indicator {
    fn value(&self) -> f64;
    fn count(&self) -> usize;
    fn update_raw(&mut self, value: f64);   // 直接喂一个数
}
```

注意那几个默认实现：一个指标只实现它支持的输入，其余的默认方法会 panic（报价是返回错误）。比如 OBV、VWAP 只实现了 `handle_bar`，订单簿失衡比只实现了 `handle_book`。把指标接到它不支持的数据上，后果见第 4 节。

### 2.1 EMA：先用简单均值起步

以最常用的指数移动平均为例（`average/ema.rs`）。它的状态就是几个数：

```rust
pub struct ExponentialMovingAverage {
    pub period: usize,
    pub price_type: PriceType,   // 用报价时取买价、卖价还是中间价，默认 LAST
    pub alpha: f64,              // 2 / (period + 1)
    pub value: f64,
    pub count: usize,
    pub initialized: bool,
    has_inputs: bool,
    seed_sum: f64,
}
```

三个 `handle_*` 都只是取出一个价格交给 `update_raw`：K 线取收盘价，成交取成交价，报价按 `price_type` 取。核心在 `update_raw`：

```rust
fn update_raw(&mut self, value: f64) {
    if !value.is_finite() { return; }          // NaN、无穷大直接丢掉
    self.has_inputs = true;
    self.count += 1;
    if self.count < self.period {              // 前 period-1 个：只累加
        self.seed_sum += value;
        return;
    }
    if self.count == self.period {             // 第 period 个：用简单均值作初值
        self.seed_sum += value;
        self.value = self.seed_sum / self.period as f64;
        self.initialized = true;
        return;
    }
    self.value = self.alpha.mul_add(value, (1.0 - self.alpha) * self.value);
}
```

算一个例子。`EMA(3)` 依次收到收盘价 10、11、12、13：前两个只累加，`value` 还是 0；第三个时 `value = (10 + 11 + 12) / 3 = 11`，`initialized` 变成 `true`；`alpha = 2 / 4 = 0.5`，第四个时 `value = 0.5 × 13 + 0.5 × 11 = 12`。所以在 `initialized` 变真之前读 `value` 得到的是 0，不是“不太准的均值”。

### 2.2 SMA：环形缓冲和定期重算

简单移动平均用一个 `VecDeque` 存最近 `period` 个值，维护一个滚动和：新值进来加上，最老的出去减掉。浮点数反复加减会累积误差，所以每更新 `16 × period` 次，它就用缓冲区里的值把和重新算一遍（`SMA_RESEED_WINDOWS = 16`）。`period` 的上限是 2²⁴（`MAX_PERIOD`）。

### 2.3 组合指标

MACD 内部持有三条均线（`Box<dyn MovingAverage>`），快慢线和信号线的类型可以选（默认 EMA，信号线周期默认 9），用 `MovingAverageFactory` 按类型造出来；它输出 `value`、`signal`、`histogram` 三个值。ATR 内部持有一条均线（默认 Wilder），用 K 线的高、低、收算真实波幅。布林带输出 `upper`、`middle`、`lower`。多输出的指标没有统一的 `value()`，直接读各自的字段。

两个和直觉不一样的细节：ATR 的 `handle_quote`、`handle_trade` 是空实现，接到报价或成交上不会报错，但也不会更新；VWAP 没有按交易日自动清零，窗口要你自己调用 `reset` 来切。RSI 的取值范围是 0～100。

## 3. 两种用法：自己喂，还是注册给框架 {#two-ways}

指标是个普通结构体，用法有两种。

<strong>自己喂。</strong>在回调里亲手调用 `handle_*`。仓库的 Rust 示例 `EmaCross` 就是这样：

```rust
// 节选自 crates/trading/src/examples/strategies/ema_cross/strategy.rs
fn on_quote(&mut self, quote: &QuoteTick) -> anyhow::Result<()> {
    self.ema_fast.handle_quote(quote)?;
    self.ema_slow.handle_quote(quote)?;
    if !self.ema_fast.initialized() || !self.ema_slow.initialized() {
        return Ok(());
    }
    let fast_above = self.ema_fast.value() > self.ema_slow.value();
    // …与上一次比较，金叉买、死叉卖
    Ok(())
}

fn on_reset(&mut self) -> anyhow::Result<()> {
    self.ema_fast.reset();
    self.ema_slow.reset();
    Ok(())
}
```

什么时候更新、喂什么、出错怎么办，全在你手里，代码一眼能看明白。

<strong>注册给框架。</strong>在 `on_start` 里调用 `register_indicator_for_bars`（还有 `_quote_ticks`、`_trade_ticks` 两个版本），框架会在每根匹配的 K 线到达时，先更新指标、再调用 `on_bar`。Python 教程里的 `EMACross` 是这样写的：

```python
# 节选自 docs/tutorials/ema_cross.py
def on_start(self) -> None:
    self.register_indicator_for_bars(self.config.bar_type, self.fast_ema)
    self.register_indicator_for_bars(self.config.bar_type, self.slow_ema)
    self.subscribe_bars(self.config.bar_type)

def on_bar(self, _bar: Bar) -> None:
    if not self.indicators_initialized():
        return
    if self.fast_ema.value >= self.slow_ema.value:
        ...
```

注意注册和订阅是两回事：注册只是告诉框架“这类 K 线来了顺便更新这个指标”，并不会订阅数据，`subscribe_bars` 还得自己调用。

## 4. 注册之后：框架怎样更新指标 {#dispatch}

![指标的注册表与更新路径](/nautilus-trader/figures/indicator-flow.svg)

每个组件的 `DataActorCore` 里有一个 `Indicators`，由四个集合组成：

```rust
// crates/common/src/actor/indicators.rs
pub struct Indicators {
    indicators: Vec<SharedActorIndicator>,                         // 全部指标
    indicators_for_quotes: AHashMap<InstrumentId, Vec<SharedActorIndicator>>,
    indicators_for_trades: AHashMap<InstrumentId, Vec<SharedActorIndicator>>,
    indicators_for_bars: AHashMap<(InstrumentId, BarSpecification), Vec<SharedActorIndicator>>,
}
```

`SharedActorIndicator` 是 `Rc<dyn ActorIndicator>`，`ActorIndicator` 是框架用来抹平 Rust 指标和 Python 指标差别的一层接口，只有 `initialized`、`handle_quote`、`handle_trade`、`handle_bar` 四个方法，外加一个用对象地址做的 `key`。同一个指标对象重复注册只记一次。

第 10 章讲过，一根 K 线到达组件时先进框架的 `handle_bar`，然后才是你的 `on_bar`。指标就在这中间更新：

```rust
// 节选自 DataActor::handle_bar（crates/common/src/actor/data_actor.rs）
if let Err(e) = self.core().handle_indicators_for_bar(bar) {
    log_error(&e);
    return;                       // 指标出错：这根 K 线不再调用 on_bar
}
if self.not_running() {
    log_not_running(&bar);
    return;                       // 组件不在 RUNNING：指标已经更新，on_bar 不调用
}
if let Err(e) = self.on_bar(bar) {
    log_error(&e);
}
```

从这几行和注册表的结构能读出五条规则：

1. 指标先于 `on_bar` 更新，所以 `on_bar` 里读到的已经包含当前这根 K 线。
2. K 线表的键是“品种 + K 线规格”（`bar_type.id_spec_key()`），不含聚合来源。为 `…-1-MINUTE-LAST-EXTERNAL` 注册的指标，也会被同品种同规格的 `INTERNAL` K 线更新；仓库的测试 `test_register_indicator_routes_quote_trade_and_bar_with_deduplication` 就是这样用的。两种来源同时订阅时，指标会被喂两次。
3. 任何一个指标出错，就跳过这次 `on_bar`，只留一条错误日志。更危险的是 Rust 一侧注册的指标：`Indicator` 默认的 `handle_bar`、`handle_trade` 是 panic 而不是返回错误，而工作区的 `release` 配置是 `panic = "abort"`，一个不支持 K 线的指标被注册到 K 线上，第一根 K 线就会让整个进程退出。注册前要确认指标支持这种输入。
4. 组件停止后指标照样更新，只是 `on_bar` 不调用；重新启动时指标是连续的。
5. `indicators_initialized()` 要求所有已注册的指标都初始化；一个都没注册时返回 `false`，不是 `true`。

历史数据走同样的规则：`handle_bars_response` 先用整批 K 线更新指标，再调用 `on_historical_bars`。框架不会替你重置指标，`ActorIndicator` 里根本没有 `reset` 方法；回测引擎 `reset()` 后再跑一轮，要在 `on_reset` 里自己清。

## 5. 在 Rust 里注册 {#rust-register}

Rust 一侧让一个指标能注册，靠的是 `nautilus-common` 里的这个泛型实现：

```rust
// crates/common/src/actor/indicators.rs
#[cfg(feature = "indicators")]
impl<T> ActorIndicator for RefCell<T>
where
    T: Indicator + 'static,
{
    fn handle_bar(&self, bar: &Bar) -> anyhow::Result<()> {
        self.borrow_mut().handle_bar(bar);
        Ok(())
    }
    // initialized / handle_quote / handle_trade 同理
}
```

于是 `Rc<RefCell<ExponentialMovingAverage>>` 可以直接当 `SharedActorIndicator` 用：策略字段里留一份 `Rc`，注册时交一份 `Rc` 给框架，两边指向同一个指标。`bar_type` 要先复制到局部变量：`core_mut()` 可变借用了整个 `self`，同一个调用的参数里再读 `self.bar_type` 会报 E0503。

```rust
use std::{cell::RefCell, rc::Rc};
use nautilus_indicators::{average::ema::ExponentialMovingAverage, indicator::MovingAverage};

// 策略结构体里：ema: Rc<RefCell<ExponentialMovingAverage>>
fn on_start(&mut self) -> anyhow::Result<()> {
    let bar_type = self.bar_type;          // 先复制出来，见下文
    let ema = Rc::clone(&self.ema);
    self.core_mut().register_indicator_for_bars(bar_type, ema);
    self.subscribe_bars(bar_type, None, None);
    Ok(())
}

fn on_bar(&mut self, _bar: &Bar) -> anyhow::Result<()> {
    if !self.core().indicators_initialized()? {
        return Ok(());
    }
    let value = self.ema.borrow().value();
    // …
    Ok(())
}
```

问题在那行 `#[cfg(feature = "indicators")]`：整个工作区里没有任何 crate 打开 `nautilus-common` 的 `indicators` 特性，只有 docs.rs 的文档构建列了它。所以照搬上面的代码会编译失败，提示 `RefCell<ExponentialMovingAverage>` 没有实现 `ActorIndicator`（E0277，第 8 节实测过）。在自己项目的 `Cargo.toml` 里显式打开它即可（Cargo 会把特性合并到同一个 `nautilus-common` 上）：

```toml
nautilus-common = { git = "https://github.com/nautechsystems/nautilus_trader", branch = "develop", features = ["indicators"] }
```

另一条路是不注册，像 `EmaCross` 那样在回调里自己喂。仓库里所有 Rust 示例策略都走这条路，这大概也是这个特性默认关着的原因：在 Rust 里手动调用一个方法没有任何额外开销，注册带来的只是“少写两行”和“历史响应自动喂”。

## 6. 在 Python 里注册：每次更新都要过一次边界 {#python-register}

Python 里的 `ExponentialMovingAverage` 不是 Python 实现，而是第 2 节那个 Rust 结构体本身（`#[pyclass]`），`self.fast_ema.value` 读的是 Rust 结构体的字段。但注册时框架并不知道它是 Rust 对象，`register_indicator_for_bars` 收到的是一个任意的 Python 对象：

```rust
// crates/trading/src/python/strategy.rs
#[pyo3(name = "register_indicator_for_bars")]
fn py_register_indicator_for_bars(&mut self, py: Python<'_>, bar_type: BarType, indicator: Py<PyAny>) {
    let indicator = wrap_python_indicator(py, indicator);   // 包成 PyActorIndicator
    DataActorNative::core_mut(&mut self.inner_mut().core).register_indicator_for_bars(bar_type, indicator);
}
```

`PyActorIndicator` 实现 `ActorIndicator` 的方式是按名字调用 Python 方法：

```rust
// crates/common/src/python/indicators.rs
fn handle_bar(&self, bar: &Bar) -> anyhow::Result<()> {
    Python::attach(|py| {
        let bar = (*bar).into_py_any(py)?;                    // 造一个新的 Python Bar 对象
        self.indicator.call_method1(py, "handle_bar", (bar,)) // 按名字调用
    })
    .map(|_| ())
    .map_err(|e| anyhow::anyhow!("{e}"))
}
```

于是一个注册在 Python 策略上的内置 EMA，每根 K 线的更新路径是：Rust 的 `Indicators::handle_bar` → 拿 GIL → 把 `Bar` 转成新的 Python 对象 → 在 Python 里按名字查找 `handle_bar` → PyO3 把参数借回 Rust → 检查价格精度不超过 16 位（`float_precision::check_bar`，Rust 一侧不做这个检查）→ Rust 的 `handle_bar` 更新 `f64`。算术本身仍在 Rust 里，开销在边界上：注册了 k 个指标，每根 K 线就要造 k 个 Python `Bar` 对象，再加上 `on_bar` 自己的那一个。对分钟级 K 线这可以忽略；对逐笔成交、报价上注册多个指标，就值得测一下了。

反过来，这种按名字调用意味着任何“长得像指标”的 Python 对象都能注册：有 `handle_bar`（或 `handle_quote_tick`、`handle_trade_tick`）方法，有 `initialized` 属性（也可以是无参方法）就行。仓库的测试 `TrackingIndicator` 就是一个纯 Python 类，测试同时验证了顺序：同一根 K 线上，`indicator:bar` 一定在 `strategy:bar` 之前。

Python 方法名和 Rust 不完全一样：报价、成交分别叫 `handle_quote_tick`、`handle_trade_tick`。还有，Python 一侧不是每个指标都绑定了全部三个方法，例如 OBV、VWAP 只有 `handle_bar`。把它们注册到报价上，每笔报价都会因为找不到方法而报错，`on_quote` 也会因此一直被跳过（第 4 节第 3 条）。

## 7. 预热：让指标在开盘前就有值 {#warmup}

指标要攒够数据才能初始化，`EMA(20)` 至少要 20 根 K 线。实盘启动时常用历史数据先把它喂热，分两种情况。

<strong>外部 K 线</strong>（`…-EXTERNAL`，交易所或数据商直接给 K 线）。按官方文档的顺序：先注册，再请求，再订阅。

```python
def on_start(self) -> None:
    self.register_indicator_for_bars(self.bar_type, self.ema)   # 必须在 request 之前
    self.request_bars(self.bar_type, start=self.clock.utc_now() - timedelta(days=1))
    self.subscribe_bars(self.bar_type)
```

请求的响应进入 `handle_bars_response`，先用整批 K 线更新指标，再调 `on_historical_bars`。顺序反过来，响应到达时指标还没注册，就什么也没喂到。

<strong>本地合成的 K 线</strong>（`…-INTERNAL`）。第 11 章第 7 节讲过，这时要请求成交或报价并带上 `bar_types` 参数，引擎在历史模式下合成 K 线。但引擎源码里写得很明白：“Request-generated bars are delivered only through the cache.” 这些 K 线只写进缓存，不会经过 `handle_bars_response`，所以注册在这种 K 线上的指标不会被喂到。要在请求完成的回调里自己从缓存取出来喂：

```python
def on_start(self) -> None:
    self.register_indicator_for_bars(self.bar_type, self.ema)
    self.request_trades(
        self.instrument_id,
        start=self.clock.utc_now() - timedelta(hours=2),
        params={"bar_types": [str(self.bar_type)], "update_subscriptions": True},
        callback=self._on_warmup_done,
    )
    self.subscribe_bars(self.bar_type)

def _on_warmup_done(self, request_id) -> None:
    bars = self.cache.bars(self.bar_type) or []
    for bar in reversed(bars):        # 缓存里第 0 个是最新的，要从旧到新喂
        self.ema.handle_bar(bar)
```

两个细节：`cache.bars` 按时间倒序返回，必须反过来喂；缓存每种 K 线默认最多保留 10,000 根（`CacheConfig.bar_capacity`）。如果在请求进行中已经有实时 K 线到达并被注册的指标处理过，再从缓存整批喂一遍就会重复，这种情况下更稳妥的做法是不注册、全程自己喂。

回测里不需要这些：让回测从更早的时间开始，指标会在正式交易前自然喂热，`on_bar` 里用 `indicators_initialized()` 挡住前面那一段即可。仓库示例 `crypto_ema_cross_ethusdt_trade_ticks.py` 用 `250-TICK` K 线配 `EMA(10)` 和 `EMA(20)`，要到第 20 根 K 线 `indicators_initialized()` 才变成真；按第 11 章的实验，这份数据一共只有 279 根这样的 K 线。

## 8. 动手：从零写一个指标 {#custom}

内置指标不够用时，可以自己写一个。这一节从头做一遍：先把规格写清楚，再在 Rust 里实现 `Indicator`，用单元测试守住手算的数值，最后放进一次真实的回测，和一份不经过框架的独立算法逐根对账。之后再用纯 Python 写同一个指标，走同样三步。

例子是**平均内部 K 线强度**（Internal Bar Strength，IBS）。一根 K 线的 IBS 是收盘价在当根振幅里的位置，`(close - low) / (high - low)`，收在最高是 1，收在最低是 0；指标取最近 `period` 根的平均。内置指标里没有它，公式简单到能手算，又有一个必须想清楚的边界：振幅为 0 的 K 线。

完整代码是一个小工程 `ibs-lab`（[在 GitHub 查看](https://github.com/lewislau86/lewislau86.github.io/tree/master/docs/public/nautilus-trader/code/ibs-lab)，目录里的 `README.md` 写了运行方法），下文代码块都从这些文件里直接截取，不另抄一份：Rust 部分是 <a href="/nautilus-trader/code/ibs-lab/Cargo.toml" download><code>Cargo.toml</code></a>、<a href="/nautilus-trader/code/ibs-lab/src/lib.rs" download><code>src/lib.rs</code></a>、<a href="/nautilus-trader/code/ibs-lab/examples/backtest_ibs.rs" download><code>examples/backtest_ibs.rs</code></a>，Python 部分是 <a href="/nautilus-trader/code/ibs-lab/python/ibs.py" download><code>python/ibs.py</code></a>、<a href="/nautilus-trader/code/ibs-lab/python/test_ibs.py" download><code>python/test_ibs.py</code></a>、<a href="/nautilus-trader/code/ibs-lab/python/backtest_ibs.py" download><code>python/backtest_ibs.py</code></a>。

::: info 本节的运行环境
Linux（aarch64，4 核、3 GB 内存）上的 Rust 1.100.0，NautilusTrader 的各个 crate 用 `path` 依赖指向提交 `364254f` 的本地检出；发布出来的 `Cargo.toml` 改成了钉在同一提交上的 `git` 依赖，内容相同。Python 部分用“从零编译”一章在同一台机器上编出的 debug 版扩展模块（Python 3.14）。下文的输出都是这次运行的原样摘录。
:::

![从零写一个指标的四步：上排是定规格、实现 Indicator、单元测试；下方是回测对账，同一份成交一路经框架聚合 K 线并更新指标，另一路用独立算法计算，两路逐根比较](/nautilus-trader/figures/custom-indicator-lab.svg)

怎么读这张图：上排三步在任何地方都能做，不需要引擎，`cargo test` 一秒内跑完。下方第四步才把指标放回框架里：左边是框架的路，成交由 DataEngine 聚合成 K 线，注册表在 `on_bar` 之前更新指标；右边是一条完全不用框架代码的路，自己切 K 线、自己算平均。两条路的输入是同一个 CSV 文件，输出逐根比较。单元测试管“公式算得对不对”，回测对账管“接到框架上之后，喂进去的是不是你以为的那些 K 线、读出来的是不是这根 K 线之后的值”。

### 8.1 先定规格，再写代码

写代码之前先回答四个问题，答案就是后面测试要断言的东西：

| 情况 | 处理 |
| :--- | :--- |
| 攒够 `period` 根之前 | `initialized` 为假，`value` 保持 0 |
| 振幅为 0（`high == low`） | 跳过，不进窗口 |
| 非有限值、`high < low`、收盘不在区间内 | 跳过 |
| `reset()` | 清空窗口和全部状态 |

第一条和内置的 EMA 一致（第 2.1 节）：未初始化时读到的 0 不是“不太准的值”。对 IBS 这一点更要小心，因为 0 本身是合法的 IBS（收在最低），只能靠 `initialized` 区分。第二条是一个设计选择：振幅为 0 的 K 线没有“收在区间哪里”可言，`0 / 0` 会得到 NaN，而 NaN 一旦进了滚动和，之后每个值都是 NaN；另一种常见做法是记成 0.5。这里选跳过，并且要用测试把这个选择固定下来。

用 `period = 3` 手算四根 K 线，这张表就是后面的测试数据：

| K 线 | 高 | 低 | 收 | IBS | `value` |
| :--- | ---: | ---: | ---: | ---: | :--- |
| 1 | 12 | 8 | 11 | 3 / 4 = 0.75 | 0（未初始化） |
| 2 | 10 | 8 | 8.5 | 0.5 / 2 = 0.25 | 0（未初始化） |
| 3 | 20 | 12 | 16 | 4 / 8 = 0.5 | (0.75 + 0.25 + 0.5) / 3 = 0.5 |
| 4 | 5 | 1 | 1 | 0 / 4 = 0 | (0.25 + 0.5 + 0) / 3 = 0.25 |

数字特意选成 2 的幂做分母，四个 IBS 都能用二进制浮点数精确表示。

### 8.2 建一个独立的 crate

指标不必放进 NautilusTrader 仓库，一个普通的 crate 就行。`Cargo.toml` 如下：

<<< @/public/nautilus-trader/code/ibs-lab/Cargo.toml

几处说明：

- 所有 `nautilus-*` 依赖钉在同一个提交上。这些 crate 互相依赖，混用不同提交会编出两份同名类型，报出难懂的类型不匹配错误。目录里同时提供了 `Cargo.lock`，第三方依赖的版本和仓库一致。
- `nautilus-common` 打开了 `indicators` 特性。第 5 节说过，没有它就不能把指标注册给框架；这次实测关掉它，回测示例编译失败，报错正是 `` the trait `ActorIndicator` is not implemented for `RefCell<InternalBarStrength>` ``（E0277）。
- `nautilus-model` 的 `test-support` 特性提供 `currency_pair_ethusdt()` 这类品种桩，回测示例要用。
- `debug = false` 去掉调试信息。实测在上面的机器上，依赖下载完之后，第一次 `cargo build --examples --tests` 不到 3 分钟，`target/` 约 1.6 GB。

### 8.3 实现 Indicator

先是结构体和构造函数。对外公开 `value`、`initialized` 和 `period`，和内置指标的习惯一样，策略里直接读字段；窗口和滚动和是内部状态：

<<< @/public/nautilus-trader/code/ibs-lab/src/lib.rs#new

计算放在 `update_raw` 里，接收三个 `f64`。这样单元测试不用构造 `Bar`，以后要接报价或别的数据源，也只是换一种取数方式：

<<< @/public/nautilus-trader/code/ibs-lab/src/lib.rs#update

顺序是：先挡坏数据，再挡零振幅，确认收下这个值之后才置 `has_inputs`，然后滑动窗口，最后在窗口满时更新 `value`。窗口一旦满过就不会再变短，所以 `initialized` 一旦为真就一直为真，直到 `reset`。

滚动和是“加新的、减最老的”，浮点误差会随更新次数慢慢累积。内置的 SMA 为此每 `16 × period` 次用缓冲区重算一遍和（第 2.2 节）。IBS 的取值在 0 到 1 之间，下文回测里 279 根 K 线累积的误差是 10⁻¹⁶ 量级；要跑几百万根，可以照 SMA 的办法定期重算。

最后实现 `Indicator` trait：

<<< @/public/nautilus-trader/code/ibs-lab/src/lib.rs#indicator

只实现了 `handle_bar`，所以这个指标只能接 K 线。`handle_quote`、`handle_trade` 用 trait 的默认实现：报价返回错误，成交直接 panic（第 4 节第 3 条），panic 信息里的名字就来自 `name()`。`Price::as_f64` 把定点数转成 `f64`，所有内置指标进来的第一步也是这样（第 1 节）。

### 8.4 写单元测试

测试写法照仓库里内置指标的习惯：用 `rstest` 的 fixture 提供一个新指标，用 `#[case]` 把手算表的几行变成几个用例；算出来的值用 `nautilus_indicators::testing::assert_approx_equal` 比较（相对误差 10⁻⁹、绝对误差 10⁻¹⁵），重置后的 0、`period = 1` 这类不变量用 `==`，这是 `testing.rs` 文档注释里的约定。

fixture 和手算数据：

<<< @/public/nautilus-trader/code/ibs-lab/src/lib.rs#fixture

手算表里的值、窗口滑动、零振幅 K 线：

<<< @/public/nautilus-trader/code/ibs-lab/src/lib.rs#values

坏数据。注意它们只能通过 `update_raw` 测：`Bar::new` 会检查 `high >= low`、收盘和开盘落在区间内，构造不出这样的 K 线。但实盘数据未必都经过 `Bar::new`，指标自己再挡一层不多余。

<<< @/public/nautilus-trader/code/ibs-lab/src/lib.rs#invalid

用一根真正的 `Bar` 走一遍 `handle_bar`，确认取的是高、低、收而不是开盘价：

<<< @/public/nautilus-trader/code/ibs-lab/src/lib.rs#handle-bar

手算用例只覆盖几个点。再加一个属性测试（`proptest`，仓库也在用）：随机生成周期和最多 200 根合法 K 线，断言指标的值总是等于“最近 `period` 个 IBS 的朴素平均”，并且落在 0 到 1 之间。这是在拿一个慢而显然正确的实现去对照快的实现：

<<< @/public/nautilus-trader/code/ibs-lab/src/lib.rs#proptest

运行 `cargo test`：

```text
running 13 tests
test tests::test_hand_computed_values::case_1 ... ok
test tests::test_hand_computed_values::case_2 ... ok
test tests::test_invalid_input_is_ignored::case_1 ... ok
test tests::test_invalid_input_is_ignored::case_2 ... ok
test tests::test_invalid_input_is_ignored::case_3 ... ok
test tests::test_invalid_input_is_ignored::case_4 ... ok
test tests::test_new ... ok
test tests::test_new_with_zero_period_panics - should panic ... ok
test tests::test_reset_then_replay_gives_same_value ... ok
test tests::test_value_is_zero_until_initialized ... ok
test tests::test_zero_range_bar_is_skipped ... ok
test tests::test_handle_bar ... ok
test tests::prop_matches_naive_mean_of_last_period ... ok

test result: ok. 13 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.06s
```

全部通过还不能说明测试有用。故意把 `update_raw` 里挡零振幅的三行删掉再跑一次，看测试能不能抓住：

```text
test tests::test_zero_range_bar_is_skipped ... FAILED
thread 'tests::test_zero_range_bar_is_skipped' (22) panicked at src/lib.rs:176:9:
approx_equal failed
  actual:   NaN
  expected: 0.5
  absolute error: NaN
  relative error: NaN
```

只有这一个手写用例失败，属性测试照样通过：它的生成器给的振幅至少是 0.01，从来不产生零振幅的 K 线。属性测试只覆盖生成器能产生的输入，边界情况还是要单独写。

### 8.5 在回测里验证数值

单元测试证明公式对。接到框架上之后还有一串事情可能出错：特性没开、注册的 K 线类型和订阅的对不上、读值的时机早了一根、K 线本身和你想的不一样。这些只能放进回测里看。

做法是写一个只收数据的 Actor（[第 13 章](./actors-and-config.md)），把指标注册到 K 线上，在 `on_bar` 里把每根 K 线和当时的指标值记下来；回测结束后，用一份完全不经过框架的算法从原始成交重算期望值，逐根比较。期望值必须来自另一条路径：拿指标自己再算一遍，只能证明它和自己一致。

数据用仓库自带的 `test_data/binance/ethusdt-trades.csv`（第 11 章的实验用过），K 线用 `ETHUSDT.BINANCE-250-TICK-LAST-INTERNAL`：每 250 笔成交一根。选成交笔数聚合而不是 1 分钟，是因为独立算法可以简单地每 250 笔切一块，不用操心时间 K 线在边界上的取舍。

Actor 本身：

<<< @/public/nautilus-trader/code/ibs-lab/examples/backtest_ibs.rs#actor

`on_start` 里先把 `bar_type` 复制到局部变量再调用 `core_mut()`。直接写 `self.core_mut().register_indicator_for_bars(self.bar_type, ibs)` 编译不过（E0503）：`core_mut()` 已经可变借用了整个 `self`，参数里不能再读 `self.bar_type`。`on_stop` 里退订，否则停止时框架会打一条“`on_stop` 没有覆盖”的 WARN。

读 CSV 时有一个坑：

<<< @/public/nautilus-trader/code/ibs-lab/examples/backtest_ibs.rs#load

最初的版本用 `Price::from(cols[2])` 直接解析字符串。CSV 里的价格会省掉末尾的 0（`423.7` 而不是 `423.70`），`Price::from` 按字符串推断精度，得到精度 1 的价格，而品种要求精度 2。运行时先是撮合引擎不断报 `Invalid trade price precision 1, expected 2`，跳过这些成交，接着聚合出的 K 线开、高、低、收精度不一致，在 `Bar::new_checked` 的 `debug_assert!` 上 panic：`Bar prices must share a uniform precision`。这个断言只在 debug 构建里存在，release 构建下不会 panic，只剩那些 WARN。改成 `instrument.make_price` 和 `make_qty`，按品种的精度构造（取整规则见[第 3 章第 3 节](./instruments.md#make-price)）。

独立算法，就是把 8.1 节的定义直接写成循环：

<<< @/public/nautilus-trader/code/ibs-lab/examples/backtest_ibs.rs#oracle

组装引擎和[第 24 章](./backtest-engine.md)的 `engine_ema_cross` 示例一样：一个模拟的 BINANCE 现货账户、一个品种、一个 Actor、一批成交：

<<< @/public/nautilus-trader/code/ibs-lab/examples/backtest_ibs.rs#engine

逐根比较。K 线的高、低、收要求完全相等，指标值允许 10⁻¹² 的误差，没攒满的那几根要求 `value` 还是 0：

<<< @/public/nautilus-trader/code/ibs-lab/examples/backtest_ibs.rs#compare

运行 `cargo run --example backtest_ibs -- <仓库>/test_data/binance/ethusdt-trades.csv`，引擎日志之外的输出是：

```text
trades: 69806
bars seen by actor: 279, oracle bars: 279
first initialized at bar #10 (1-based)
max |indicator - oracle| = 6.106226635438361e-16
bar # 10: high=424.95 low=424.52 close=424.91 ibs=0.591697
bar # 11: high=425.25 low=424.86 close=425.04 ibs=0.621184
bar # 12: high=425.11 low=424.42 close=425.06 ibs=0.669493
last bar: ibs=0.545296
indicator object after run: InternalBarStrength(10)
OK
```

逐行看能读出几件事：

- **279 根。** 69,806 笔成交每 250 笔一根是 279 根，剩下 56 笔凑不满，不会生成 K 线。框架聚合出的每根 K 线的高、低、收都和自己切块的结果完全相同；这份数据里没有零振幅的 K 线。
- **第 10 根开始有值。** `period = 10`，前 9 根 `value` 都是 0。
- **误差 6×10⁻¹⁶。** 独立算法每次重新求和，指标用滚动和，两者只差在浮点舍入上，比 `f64` 在 0.5 附近的间距（约 10⁻¹⁶）大几倍。
- **`on_bar` 读到的值已经包含当前这根 K 线。** 如果指标在 `on_bar` 之后才更新，每个值都会和期望值错开一根，误差会是 10⁻² 量级而不是 10⁻¹⁶。这就是第 4 节的第 1 条规则，这里用数据验证了一遍。

几种可能的失败和它们指向的问题：根数不对，查 K 线类型和聚合；值整体错开一根，查读值的时机或者是否手动又喂了一次；编译时报 E0277，查 `indicators` 特性；跑起来就 panic，信息是 `` `handle_bar` is not implemented for … ``，是把只支持报价或成交的指标注册到了 K 线上。

### 8.6 Python 版：同样三步

Python 里不需要编译，任何有 `handle_bar` 方法和 `initialized` 属性的对象都能注册（第 6 节）。把 Rust 版逐行翻译过来：

<<< @/public/nautilus-trader/code/ibs-lab/python/ibs.py

`bar.high` 是 Rust 的 `Price` 对象，`as_double()` 转成 `float`。`reset` 框架不会调用（第 4 节），留着给 `on_reset` 用。

单元测试 <a href="/nautilus-trader/code/ibs-lab/python/test_ibs.py" download><code>test_ibs.py</code></a> 用的是同一张手算表，用 `pytest.approx` 比较，另外构造一根真正的 `nautilus_trader.model.Bar` 测 `handle_bar`。在 nautilus_trader 的检出目录里运行（环境按“从零编译”一章准备）：

```bash
uv run --project python --no-sync pytest /path/to/ibs-lab/python/test_ibs.py
```

结果是 `9 passed`。回测脚本 <a href="/nautilus-trader/code/ibs-lab/python/backtest_ibs.py" download><code>backtest_ibs.py</code></a> 用 `Strategy` 而不是 Actor，用 `TestDataProvider` 读同一个 CSV，独立算法换成 pandas：

<<< @/public/nautilus-trader/code/ibs-lab/python/backtest_ibs.py#probe

<<< @/public/nautilus-trader/code/ibs-lab/python/backtest_ibs.py#oracle

```bash
uv run --project python --no-sync python /path/to/ibs-lab/python/backtest_ibs.py
```

```text
trades: 69806
bars seen by strategy: 279, oracle bars: 279
first initialized at bar #10 (1-based)
max |indicator - oracle| = 6.661338e-16
bar # 10: high=424.95 low=424.52 close=424.91 ibs=0.591697
bar # 11: high=425.25 low=424.86 close=425.04 ibs=0.621184
bar # 12: high=425.11 low=424.42 close=425.06 ibs=0.669493
last bar: ibs=0.545296
OK
```

打印出来的指标值和 Rust 版逐位相同。这也是一次交叉验证：Python 扩展模块默认用高精度模式编译，Rust 示例用的是标准精度（第 2 章），但这份数据的价格只有两位小数，两种模式下的 K 线完全一样。最大误差略有不同，是因为 pandas 的 `rolling().mean()` 和 Rust 的朴素循环求和方式不同。

纯 Python 指标的代价在第 6 节说过：每根 K 线都要把 `Bar` 转成 Python 对象再按名字调用，计算也在 Python 里。这里每 250 笔成交才有一根 K 线，开销可以忽略；挂在逐笔数据上时就值得考虑 Rust 版。

### 8.7 另外两条路

还有两种做法，各有适用的场合：

- **把 Rust 指标暴露给 Python。** 给结构体加 `#[pyclass]`，写一组 `#[pymethods]`，再像第 38 章附录 C 那样把类注册进一个 PyO3 模块。内置指标都是这么做的（`python/` 目录）。这已经是在扩展 `_libnautilus`，要重新编译整个扩展模块。
- **不当指标，直接在 `on_bar` 里算。** 只有一个策略用、逻辑又和信号写在一起时，这往往最清楚。仓库里的 `hurst_vpin_directional` 就把 Hurst 指数和 VPIN 直接算在 `on_bar` 和 `on_trade` 里（第 11 章第 9 节）。代价是不能注册、不能复用，测试也要连同策略一起写。

::: warning 常见误区
- **注册了指标就以为订阅了数据。** 注册只决定“来了就更新”，订阅要另外调用 `subscribe_*`。
- **在 `initialized` 之前读 `value`。** EMA 这时是 0，不是近似值；用 `indicators_initialized()` 或单个指标的 `initialized` 挡住。
- **把指标注册到它不支持的输入上。** 返回错误时这类数据的回调会被一直跳过；Rust 一侧注册的指标默认 panic，`release` 构建下进程直接退出；ATR 这类空实现则是悄悄不更新。
- **同时订阅同规格的 INTERNAL 和 EXTERNAL K 线。** K 线表的键不含来源，指标会被喂两次。
- **以为回测 `reset()` 会清空指标。** 框架不会重置指标，要在 `on_reset` 里自己调用 `reset`。
- **以为本地合成的历史 K 线会自动预热指标。** 它们只进缓存，要自己从缓存倒序取出来喂。
- **在 Rust 里注册指标却编译不过。** 打开 `nautilus-common` 的 `indicators` 特性，或者改成自己喂。
- **用 `==` 比较两个指标值。** 指标是 `f64`，比较大小或用容差。
- **在回测里用指标自己验证自己。** 期望值要来自一条不经过框架、不复用指标代码的独立算法，否则只证明了它和自己一致。
- **用 `Price::from` 读 CSV 里的价格。** 末尾的 0 被省掉时精度会变小；按品种精度用 `make_price`、`make_qty` 构造。
- **以为属性测试能覆盖所有边界。** 它只覆盖生成器能产生的输入，零振幅这类情况要单独写用例。
:::

## 本章结论

内置指标全部在 `nautilus-indicators` 里用 Rust 实现，内部用 `f64` 计算，实现同一个 `Indicator` trait，只支持自己声明的那几种输入。用法有两种：自己在回调里调用 `handle_*`，或者注册到组件的 `Indicators` 表上，让框架在每次 `on_bar`（以及 `on_quote`、`on_trade`、`on_historical_bars`）之前先更新它们。Rust 注册是零开销的直接调用，但要打开 `indicators` 特性；Python 注册的指标被包成 `PyActorIndicator`，每次更新都要拿 GIL、造一个 Python 对象、按名字调用，算术仍在 Rust 里。预热时，交易所给的 K 线经响应自动喂进指标，本地合成的历史 K 线只进缓存，要自己喂。自己写指标时，先把初始化、坏数据和边界情况写成规格，再用手算值和属性测试守住公式，最后在回测里和独立算法逐根对账，确认接到框架之后读到的是你以为的值。

## 检查理解

1. `EMA(5)` 收到前 4 根 K 线后，`value` 和 `initialized` 分别是什么？第 5 根之后呢？

   <details><summary>参考答案</summary>

   前 4 根之后 `value` 是 0，`initialized` 是 `false`，收盘价只累加在 `seed_sum` 里。第 5 根到达时，`value` 等于这 5 个收盘价的简单平均，`initialized` 变成 `true`；从第 6 根起才按 `alpha = 2 / 6` 做指数平滑。

   </details>

2. 一个 Python 策略给同一种 1 分钟 K 线注册了 3 个内置指标，每根 K 线到达时，框架要创建几个 Python `Bar` 对象？为什么？

   <details><summary>参考答案</summary>

   4 个。每个注册的指标都被包成 `PyActorIndicator`，它的 `handle_bar` 每次都要把 Rust 的 `Bar` 转成一个新的 Python 对象再按名字调用，3 个指标就是 3 个；之后调用策略的 `on_bar` 时还要再转一个。

   </details>

3. 策略订阅了 `…-5-MINUTE-LAST-INTERNAL`，启动时用 `request_trades` 加 `bar_types` 参数合成了过去两小时的 5 分钟 K 线，注册在这种 K 线上的 EMA 为什么还是没初始化？怎么办？

   <details><summary>参考答案</summary>

   请求中合成的 K 线只写进缓存，不经过 `handle_bars_response`，所以注册表里的指标收不到它们。办法是在请求的回调里调用 `cache.bars(bar_type)`，倒序（从旧到新）逐根调用指标的 `handle_bar`；或者干脆不注册、全程自己喂。

   </details>

4. 第 8 节的回测里，如果把读值和喂数据的顺序弄反（例如不注册，在 `on_bar` 末尾才手动调用 `handle_bar`，却在开头读 `value`），对账会出现什么现象？为什么单元测试发现不了？

   <details><summary>参考答案</summary>

   每根 K 线读到的都是上一根之后的值，整条序列和期望值错开一根，误差从 10⁻¹⁶ 量级变成 10⁻² 量级（相邻两根的平均 IBS 差几个百分点），初始化也晚一根才被看到。单元测试只调用指标本身，测的是公式；喂数据和读值的时机属于策略和框架之间的接线，只有放进回测、和一条独立算法比较才看得出来。

   </details>

## 参考资料

- 官方文档：[Strategies](https://github.com/nautechsystems/nautilus_trader/blob/develop/docs/concepts/strategies.md)（注册指标与预热）· [Data · Register indicators before requesting data](https://github.com/nautechsystems/nautilus_trader/blob/develop/docs/concepts/data/index.md) · [Write a Rust strategy](https://github.com/nautechsystems/nautilus_trader/blob/develop/docs/how_to/write_rust_strategy.md)
- 源码：[`crates/indicators/`](https://github.com/nautechsystems/nautilus_trader/tree/develop/crates/indicators) · [`crates/common/src/actor/indicators.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/common/src/actor/indicators.rs) · [`crates/common/src/python/indicators.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/common/src/python/indicators.rs) · [`crates/trading/src/python/strategy.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/trading/src/python/strategy.rs) · [`docs/tutorials/ema_cross.py`](https://github.com/nautechsystems/nautilus_trader/blob/develop/docs/tutorials/ema_cross.py)
- 第 8 节完整代码：[`ibs-lab`](https://github.com/lewislau86/lewislau86.github.io/tree/master/docs/public/nautilus-trader/code/ibs-lab)；数据是仓库的 [`test_data/binance/ethusdt-trades.csv`](https://github.com/nautechsystems/nautilus_trader/blob/develop/test_data/binance/ethusdt-trades.csv)；测试写法参考 [`crates/indicators/src/testing.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/indicators/src/testing.rs) 和 [`volatility/dc.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/indicators/src/volatility/dc.rs) 的测试
- 配图由 `scripts/generate-nautilus-trader-figures.py` 生成。

策略之外，系统里还有只收数据的 Actor 和负责拆单的执行算法，下一章讲它们以及所有组件共用的配置和日志：[第 13 章：Actor、执行算法与配置](./actors-and-config.md)。
