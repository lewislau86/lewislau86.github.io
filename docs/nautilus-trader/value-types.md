---
title: "第 2 章：数值类型、标识符与时间戳"
description: 一行成交记录在 NautilusTrader 里变成了哪些值：Price、Quantity、Money 怎样用定点整数表示、两种精度模式差在哪里、运算和比较有什么规则；币种表；各种标识符的格式、校验与生成规则；UnixNanos、ts_event 与 ts_init、UUID4。
---

# 第 2 章：数值类型、标识符与时间戳

[全书目录](./index.md) · [上一章](./architecture.md) · [下一章](./instruments.md)

::: tip 本章学习目标
能说出一个价格在内存里是什么整数、在两种精度模式下各是多少，知道 `Price::new` 和 `from_str` 怎样决定精度、什么时候会悄悄舍入；知道数值类型相加、相减、比较的规则和会 panic 的情形；能读懂并生成各种标识符，知道它们的校验规则；分得清 `ts_event` 和 `ts_init`。

**源码版本：** `develop` 分支，提交 `364254f`（2026-11-18）。数值类型在 `crates/model/src/types/`，标识符在 `crates/model/src/identifiers/`，ID 生成器在 `crates/common/src/generators/`，时间与 UUID 在 `crates/core/src/{nanos,uuid,datetime}.rs`。

**对应官方文档：** [Value Types](https://nautilustrader.io/docs/latest/concepts/value_types/) · [Overview](https://nautilustrader.io/docs/latest/concepts/overview/)（Timestamps、UUIDs、Value types 三节）· [Data](https://nautilustrader.io/docs/latest/concepts/data/)（Timestamps 一节）
:::

第 0 章第 5 节用几行代码列过 `Price`、`Quantity`、`Money` 和标识符的结构，第 1 章第 8 节给过一张标识符速查表。这一章把它们当成整本书的词汇表，认真读一遍：后面的品种、订单、仓位、账户，全都由这几种值拼成，它们的规则（什么时候舍入、什么时候 panic、两个值什么时候相等）会一路影响到盈亏和对账。

主线例子是第 11 章实验里那份成交数据（仓库的 `test_data/binance/ethusdt-trades.csv`）的第一行。文件里的原文是：

```text
timestamp,trade_id,price,quantity,buyer_maker
2020-08-14 10:00:00.223000+00:00,148568980,423.76,2.67900,True
```

测试工具 `TestDataProvider.trades_from_binance_csv`（`python/nautilus_trader/testkit/providers.py`）把它读成一个 `TradeTick`，打印出来是：

```text
ETHUSDT.BINANCE,423.76,2.67900,SELL,148568980,1597399200223000000
```

先猜一下：`423.76` 这个价格在 NautilusTrader 的内存里是什么？

## 1. 一行成交，拆成六个值 {#one-trade}

这个 `TradeTick` 的六个字段各是一种值类型（`buyer_maker = True` 表示买方是挂单方，主动方是卖方，所以是 `SELL`）：

| 原文 | 字段 | 类型 |
| :--- | :--- | :--- |
| `ETHUSDT.BINANCE`（来自品种定义） | `instrument_id` | `InstrumentId`（`Symbol` + `Venue`） |
| `423.76` | `price` | `Price` |
| `2.67900` | `size` | `Quantity` |
| `SELL` | `aggressor_side` | `AggressorSide` 枚举 |
| `148568980` | `trade_id` | `TradeId` |
| `2020-08-14 10:00:00.223000+00:00` | `ts_event`、`ts_init` | `UnixNanos` |

![一行成交拆成六个值：价格和数量是定点整数加精度，标识符是驻留字符串或栈上字符串，时间是 u64 纳秒；同一个价格在高精度模式下的 raw 是标准模式的一千万倍](/nautilus-trader/figures/value-types-trade.svg)

怎么读这张图：每个框的第二行是你在日志里看到的样子，下面是它在内存里的真实形态。注意价格和数量那两个框：显示的是 `423.76`，存的却是一个很大的整数，而且这个整数随编译模式不同而不同。

## 2. 定点数：一个整数加一个精度 {#fixed-point}

答案揭晓：`423.76` 存成一个整数 `raw`，外加一个精度 `precision = 2`。

```rust
// 节选自 crates/model/src/types/price.rs
pub struct Price {
    pub(crate) raw: PriceRaw,   // 放大后的整数；外部用 .raw() 读
    pub precision: u8,          // 小数位数，只影响显示和序列化
}
```

关键在放大倍数。它不是 `10^precision`，而是一个全局常量 `FIXED_SCALAR`，等于 `10^FIXED_PRECISION`（`crates/model/src/types/fixed.rs`）：

| 模式 | `PriceRaw` | `FIXED_PRECISION` | `423.76` 的 `raw` |
| :--- | :--- | :--- | :--- |
| 标准（64 位） | `i64` | 9 | `423_760_000_000` |
| 高精度（128 位） | `i128` | 16 | `4_237_600_000_000_000_000` |

所有价格不管精度是 2 还是 5，`raw` 都按同一个倍数放大。这样两个价格比较大小、相加相减，直接对 `raw` 做整数运算就行，不用先对齐小数位。精度 2 的价格，`raw` 的末尾必然有 `FIXED_PRECISION - 2` 个 0；`from_raw` 会检查这一点（`check_fixed_raw_*`），末尾不是 0 就报错，防止有人塞进一个“精度 2 却有第 3 位小数”的值。

### 2.1 从浮点数构造：先按精度取整

`Price::new(value, precision)` 的核心是 `f64_to_fixed_i128`（标准模式是 `_i64` 版本）：

```rust
// 节选自 crates/model/src/types/fixed.rs
pub fn f64_to_fixed_i128(value: f64, precision: u8) -> i128 {
    let pow1 = 10_i128.pow(u32::from(precision));
    let pow2 = 10_i128.pow(u32::from(FIXED_PRECISION - precision));
    let rounded = (value * pow1 as f64).round() as i128;   // 先在目标精度上取整
    rounded.checked_mul(pow2).expect("Overflow when scaling f64 to fixed-point i128")
}
```

先猜：`Price::new(1.005, 2)` 是 `1.01` 还是 `1.00`？按四舍五入应该是 `1.01`，但 `1.005` 在二进制里存不准，`1.005 × 100` 算出来是 `100.49999999999999`，取整得 100，结果是 `1.00`。这正是为什么第 0 章说“交易所发来的是字符串时，别先转成 `f64`”：同一个数用 `Price::from("1.005")` 就不会有这个问题，只是精度会变成 3。有意思的是，主线例子用的测试工具恰好走的是浮点路径：它写的是 `Price(float(row[2]), precision=price_precision)`。对 `423.76` 这种两位小数的价格没有问题，换成边界值就可能踩坑。

### 2.2 从字符串构造：精度由小数位数决定

`Price::from_str` 不经过浮点数。它把字符串拆成整数尾数和小数位数，精度就是字符串里的小数位数：`"423.76"` 精度 2，`"2.67900"` 精度 5，`"1e-3"` 这类科学计数法经 `Decimal` 解析。数字之间的下划线会被去掉，`"1_000.5"` 也能解析。这条规则意味着同一个数写法不同，精度就不同：`"423.760"` 的精度是 3。

### 2.3 两个哨兵值

`raw` 的两个极值被留作特殊含义：`PRICE_UNDEF = PriceRaw::MAX` 表示“没有价格”（比如市价单的价格字段），`PRICE_ERROR = PriceRaw::MIN` 表示出错。它们不参与范围检查，取反时保持不变。正常价格的范围由 `PRICE_MIN`、`PRICE_MAX` 限定：标准模式约 ±92 亿，高精度模式约 ±17 万亿。`Quantity` 不能为负，`QUANTITY_MAX` 分别约 184 亿和 34 万亿。

## 3. 运算与比较的规则 {#arithmetic}

<strong>相等只看数值。</strong>`Price` 的 `Ord` 实现直接比较 `raw`，所以 `Price::from("1.0") == Price::from("1.00")`，两者 `raw` 相同。`Hash` 也特意做成一致：哈希前先去掉末尾多余的 0（`canonical_raw`），两个相等的价格放进 `HashMap` 是同一个键。官方文档的说法是“Precision controls display, not identity”。

<strong>同类相加，精度取大。</strong>

```rust
// 节选自 crates/model/src/types/price.rs
impl Add for Price {
    fn add(self, rhs: Self) -> Self::Output {
        assert!(raw_scales_match(self.precision, rhs.precision), "…mismatched decimal scales");
        Self {
            raw: self.raw.checked_add(rhs.raw).expect("Overflow occurred when adding `Price`"),
            precision: self.precision.max(rhs.precision),
        }
    }
}
```

`raw_scales_match` 在非 DeFi 构建里总是成立（两个精度都不超过 `FIXED_PRECISION` 时 raw 的倍数相同），所以精度 1 的 `100.5` 加精度 3 的 `0.125`，结果是精度 3 的 `100.625`。只有打开 `defi` 特性、精度超过 16 位（如 18 位的 wei）时，两个精度不同的值才不能直接相加。

<strong>会 panic 的三种情况。</strong>溢出（`checked_add` 失败）；`Quantity` 相减结果为负（`QuantityRaw` 是无符号整数，`checked_sub` 失败，信息是 “Underflow occurred when subtracting `Quantity`”，Python 一侧表现为 `ValueError`）；两个币种不同的 `Money` 相加减（`assert_eq!` 币种，信息是 “Currency mismatch”）。在 Rust 代码里做减法前，先比较大小。

<strong>混合运算换类型。</strong>`Price` 和 `Decimal` 运算得到 `Decimal`，和 `f64` 运算得到 `f64`，`Quantity * Quantity` 仍是 `Quantity`。需要累计、求平均的地方，源码一律用 `Decimal`：订单的 `avg_px`、仓位的 `signed_qty` 和 `avg_px_open` 都是 `rust_decimal::Decimal`（第 5、6 章）。

## 4. 两种精度模式 {#precision-modes}

上面的表已经说了两种模式的区别，这里补三件和工程有关的事。

第一，你实际在用哪种模式取决于构建方式：Python wheel 是高精度模式；纯 Rust 程序默认是标准模式，但大多数适配器 crate 的默认特性打开了 `high-precision`，Cargo 会把它统一到整个依赖图（第 0 章第 5.1 节）。源码里有一个导出给 C 的静态变量 `HIGH_PRECISION_MODE` 记录当前模式。

第二，数据目录里的价格和数量不存原始整数，而是统一存成 16 位小数的 `Decimal128(38, 16)`，所以两种模式写出的文件格式相同：标准模式写入时把原始值乘以 10<sup>7</sup>，读取时再除回来；如果文件里的值在第 9 位小数之后还有非零数字，标准模式读取会报错。旧版本目录用 8 字节或 16 字节的定长二进制存原始值，读取时按宽度换算，`FIXED_PRECISION_STANDARD = 9` 用在这些换算里（第 25 章）。

第三，`f64` 构造函数有一个独立的上限 `MAX_FLOAT_PRECISION = 16`：双精度浮点数只有 15～17 位有效数字，更高的精度只能用整数或字符串构造。第 12 章提到 Python 指标会检查价格精度不超过 16 位，用的就是这个常量。

## 5. 币种与金额 {#currency-money}

`Money` 没有自己的精度字段，精度跟着币种走：

```rust
// 节选自 crates/model/src/types/{money,currency}.rs
pub struct Money    { pub(crate) raw: MoneyRaw, pub currency: Currency }
pub struct Currency {
    pub code: Ustr,           // "USDT"
    pub precision: u8,        // 8
    pub iso4217: u16,         // 法币的 ISO 4217 数字代码，加密货币为 0
    pub name: Ustr,
    pub currency_type: CurrencyType,   // Crypto / Fiat / CommodityBacked
}
```

`crates/model/src/currencies.rs` 用一个宏声明了内置币种表，我数了一下是 92 种：29 种法币、60 种加密货币、3 种商品（如 `XAU` 黄金）。每一行同时生成访问函数和注册项，“声明了却忘了注册”在结构上不可能发生。几个和本书有关的：`USD` 精度 2、`HKD` 精度 2（ISO 344）、`CNH` 精度 2、`USDT` 精度 8、`ETH` 精度 8。

适配器遇到表里没有的币种时，常用 `Currency::get_or_create_crypto(code)`：查不到就按“精度 8、ISO 代码 0、加密货币”新建并注册进全局表 `CURRENCY_MAP`。注意它对法币也会这样建，所以接入新的法币市场时，最好在启动时用 `Currency::register` 显式登记。

回到主线例子。这笔成交的名义金额是 `423.76 × 2.679 = 1135.25304`，以 USDT 计价，用 `Money` 表示就是 `1135.25304000 USDT`（显示到币种的 8 位）。官方文档还提到 `Money.from_decimal_exact`、`from_str_exact` 两个精确构造函数：它们能保留比币种精度更细的金额，而普通的 `from_str`、`from_decimal` 会按币种精度舍入。

## 6. 标识符：格式、校验与生成 {#identifiers}

### 6.1 两种存储

大多数标识符是 `Ustr` 的新类型：全进程共享一张字符串表，标识符本身只是一个带预算哈希的指针，复制和比较都像整数一样便宜，代价是表里的条目永不释放（第 0 章第 5.2 节）。`TradeId` 是例外，它是栈上的定长字符串 `StackStr`，最多 36 个字符，因为成交 ID 数量最多，不能让它们在字符串表里无限累积。主线例子里的 `148568980` 就是这样一个 `TradeId`。`UUID4` 也是定长的，见第 7 节。

### 6.2 校验规则

每个标识符都有 `new_checked`，规则各不相同，读源码时值得逐个看一眼：

| 类型 | 格式 | 校验（`crates/model/src/identifiers/`） |
| :--- | :--- | :--- |
| `InstrumentId` | `Symbol.Venue` | 按最后一个 `.` 切分，所以代码里可以有点：`ES.FUT.XCME` 的代码是 `ES.FUT` |
| `Symbol` | 任意 | 合法 UTF-8 即可，可以是中文 |
| `Venue` | ASCII | 只允许 ASCII |
| `TraderId`、`StrategyId` | `名字-标签` | 必须含 `-`，按最后一个 `-` 切分，两边非空；`StrategyId` 允许特殊值 `EXTERNAL` |
| `AccountId` | `发行方-账号` | 必须含 `-`，按第一个 `-` 切分，两边非空 |
| `TradeId` | 任意 | 最多 36 个字符 |

`TraderId` 和 `StrategyId` 的“标签”有实际用途：`get_tag()` 取出 `-` 后面那段，ID 生成器用它拼订单号和仓位号。

### 6.3 订单号和仓位号怎样生成

`ClientOrderIdGenerator`（`crates/common/src/generators/client_order_id.rs`）默认生成这种格式：

```text
O-{UTC 日期}-{UTC 时分秒}-{trader 标签}-{strategy 标签}-{计数}
O-20200814-100000-001-001-1        ← 测试用例里是 O-19700101-000000-001-001-1
```

时间取自组件时钟（回测里是回测时间），计数器在策略内递增。为了快，生成器把前缀缓存起来，同一秒内只截断末尾的计数再追加新值。配置项 `use_uuids` 打开时改用 UUID4 作订单号，`use_hyphens = false` 时去掉所有连字符。

`PositionIdGenerator` 生成 `P-{日期}-{时分秒}-{trader 标签}-{strategy 标签}-{计数}`，计数按策略分开；参数 `flipped` 为真时在末尾加一个 `F`，表示这是一次反手产生的新仓位（第 6 章）。

`VenueOrderId` 由交易所给，平台不生成；`ClientOrderId` 和 `VenueOrderId` 的对应关系由执行引擎和适配器维护（第 20 章、第 38 章）。

::: tip 对富途意味着什么
富途 OpenAPI 的股票代码写作“市场前缀.代码”，例如 `HK.00700`、`US.AAPL`。这和 `InstrumentId` 的“代码.场所”顺序正好相反：直接 `InstrumentId::from("HK.00700")` 会被切成代码 `HK`、场所 `00700`，校验也能通过，错误要到后面才暴露。适配器应当在解析边界做一次显式转换，例如映射成 `00700.XHKG` 或 `00700.HKEX` 这类形式，具体用哪种场所代码是第 38 章的设计问题。
:::

## 7. 时间：UnixNanos、两个时间戳与 UUID4 {#time}

`UnixNanos`（`crates/core/src/nanos.rs`）是 `u64` 的新类型，表示自 UNIX 纪元以来的纳秒数，能表示到 2554 年左右。表示时长的是另一个类型 `DurationNanos`，两者在类型上分开：两个时间戳相减得到 `DurationNanos`，如果被减数更早会 panic（“UnixNanos underflow in timestamp subtraction”），时间可能乱序时用 `duration_since` 或 `saturating_duration_since`。

从字符串解析时，`UnixNanos` 依次尝试三种写法：纯整数当纳秒，带小数点的数当秒，再按 RFC 3339 解析日期时间（日期和时间之间可以是 `T` 或空格）。主线例子 CSV 里的时间先被测试工具转成纳秒 `1597399200223000000`，再格式化回 RFC 3339 是：

```text
2020-08-14T10:00:00.223000000Z
```

`unix_nanos_to_iso8601`（`crates/core/src/datetime.rs`）总是输出 9 位小数和 `Z` 后缀；另有一个毫秒版本，用于 GTD 到期时间这类显示。

### 7.1 ts_event 和 ts_init

几乎每个数据和事件都带两个时间戳：

- `ts_event`：事件发生的时间。行情是交易所的时间，成交是交易所的成交时间，K 线是配置的开盘或收盘边界（第 11 章）。
- `ts_init`：NautilusTrader 创建这个对象的时间。外部数据通常就是本地收到并转换的时间；内部生成的命令和事件也有 `ts_init`，这时它就是创建时间。

主线例子里两个时间戳相同，因为测试工具把 CSV 里的同一个时间同时填进了 `ts_event=ts_ns, ts_init=ts_ns`。实盘里两者通常不同。官方文档强调两点：一是 `ts_init - ts_event` 只有在两边时钟同步时才能当作延迟，否则还混着时钟偏差，甚至可能是负数；二是回测按 `ts_init` 做稳定排序来回放，所以 `ts_init` 决定了回测里“谁先发生”。

### 7.2 UUID4

`UUID4`（`crates/core/src/uuid.rs`）是事件 ID、命令 ID、请求 ID 的统一类型，内部是一个 37 字节的定长数组（36 个字符加 C 字符串结尾的 0），所以它是 `Copy`，不用堆分配。解析时用 `uuid` crate 校验版本位和变体位，不是第 4 版的 UUID 会被拒绝。生成用的随机数平时来自系统随机源；在确定性仿真测试的 madsim 运行时里换成带种子的随机数生成器（第 37 章），这样同一个种子每次生成的 ID 都一样，测试才能重放。

::: warning 常见误区
- **以为 `raw` 等于数值乘以 `10^precision`。** 放大倍数是全局的 `10^9` 或 `10^16`，和这个值自己的精度无关；用 `from_raw` 时要按当前模式算。
- **用 `Price::new(f64, …)` 处理交易所发来的字符串。** 浮点转换会悄悄舍入（`1.005` 变成 `1.00`），用 `from_str` 或经 `Decimal` 转换。
- **以为精度不同的两个价格不相等。** 相等只看数值；精度只影响显示和序列化。
- **在 Rust 里直接做 `Quantity` 减法。** 结果为负会 panic，先比较大小或用 `Decimal`。
- **把两个币种的 `Money` 相加。** 会 panic，跨币种要先换算（第 7 章）。
- **把富途的 `HK.00700` 直接当 `InstrumentId`。** 它会被切成代码 `HK`、场所 `00700`。
- **把 `ts_init - ts_event` 当延迟。** 只有两边时钟同步时才成立。
:::

## 本章结论

NautilusTrader 的价格、数量、金额都是“全局倍数放大的整数加一个显示精度”，比较和相加直接做整数运算，精度不同也能相加、相等，精度只影响显示；金额的精度来自币种，币种由一张 92 项的内置表加运行时注册组成。标识符大多是永不释放的驻留字符串，成交 ID 是栈上定长字符串，订单号和仓位号由生成器按“前缀-时间-标签-计数”拼出来。时间一律是 `u64` 纳秒，`ts_event` 记事件发生的时间，`ts_init` 记对象创建的时间，回测按后者排序。

## 检查理解

1. 在高精度模式下，`Price::from("0.5")` 和 `Price::new(0.5, 3)` 的 `raw` 各是多少？两者相等吗？`Price::from("0.5") + Price::new(0.25, 3)` 的精度是多少？

   <details><summary>参考答案</summary>

   两者的 `raw` 都是 `0.5 × 10^16 = 5_000_000_000_000_000`，精度分别是 1 和 3。相等，因为比较只看 `raw`。相加的结果是 `0.75`，精度取两者较大的 3。

   </details>

2. 一个策略的 `StrategyId` 是 `EMACross-001`，节点的 `TraderId` 是 `BACKTESTER-001`，回测时钟是 2020-08-14 10:00:00 UTC，它生成的第一个订单号是什么？如果把 `StrategyId` 写成 `EMACross001` 会怎样？

   <details><summary>参考答案</summary>

   `O-20200814-100000-001-001-1`：两个标签都是最后一个 `-` 后面的 `001`。`EMACross001` 不含 `-`，`StrategyId::new_checked` 会因为 `check_string_contains(value, "-")` 失败而报错，`StrategyId::new` 会 panic。

   </details>

3. 一笔成交的 `ts_event` 是 `2020-08-14T10:00:00.223Z`，`ts_init` 是 `2020-08-14T10:00:00.221Z`，比 `ts_event` 还早。这说明数据有问题吗？在回测里它会排在哪个时间点？

   <details><summary>参考答案</summary>

   不一定。`ts_event` 来自交易所时钟，`ts_init` 来自本地时钟，两边有偏差时本地时间可以早于交易所时间，官方文档明确说 `ts_init` 不保证不小于 `ts_event`。回测按 `ts_init` 排序，所以它排在 10:00:00.221 这一时刻。

   </details>

## 参考资料

- 官方文档：[Value Types](https://nautilustrader.io/docs/latest/concepts/value_types/) · [Overview](https://nautilustrader.io/docs/latest/concepts/overview/) · [Data](https://nautilustrader.io/docs/latest/concepts/data/)
- 源码：[`crates/model/src/types/`](https://github.com/nautechsystems/nautilus_trader/tree/develop/crates/model/src/types) · [`crates/model/src/currencies.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/model/src/currencies.rs) · [`crates/model/src/identifiers/`](https://github.com/nautechsystems/nautilus_trader/tree/develop/crates/model/src/identifiers) · [`crates/common/src/generators/`](https://github.com/nautechsystems/nautilus_trader/tree/develop/crates/common/src/generators) · [`crates/core/src/nanos.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/core/src/nanos.rs) · [`crates/core/src/uuid.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/core/src/uuid.rs)
- 配图由 `scripts/generate-nautilus-trader-figures.py` 生成。

有了价格、数量和标识符，下一章看它们被组织成什么：一个“品种”带着哪些精度和规则，怎样把任意一个数变成合法的价格和数量。[第 3 章：品种](./instruments.md)。
