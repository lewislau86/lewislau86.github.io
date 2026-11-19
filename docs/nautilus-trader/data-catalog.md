---
title: "第 25 章：数据目录：Parquet 与 Arrow"
description: ParquetDataCatalog 的目录布局与文件命名；写入一批报价时经过的检查、Arrow 编码与元数据；价格为什么统一存成 Decimal128(38, 16)、两种精度模式怎样读写同一份数据；查询怎样先按目录和文件名筛文件、再用 DataFusion SQL 过滤；回测怎样从目录加载；文件重命名、合并、删除与 Feather 流式写入。
---

# 第 25 章：数据目录：Parquet 与 Arrow

[全书目录](./index.md) · [上一章](./backtest-engine.md) · [下一章](./simulated-exchange.md)

::: tip 本章学习目标
能画出一个数据目录的文件树，看到文件名就知道它覆盖的时间范围；能说出写入一批数据时会检查什么、什么情况下会被拒绝；知道价格和数量在 Parquet 里存成什么类型、精度信息存在哪里；能解释一次查询怎样决定读哪些文件；会为 `BacktestNode` 写一个数据配置，知道目录的合并、删除操作各有什么风险。

**源码版本：** `develop` 分支，提交 `364254f`（2026-11-18）。目录在 `crates/persistence/src/backend/parquet/catalog/`（`write.rs`、`query.rs`、`store.rs`），路径规则在 `backend/parquet/paths.rs` 和 `common/paths.rs`，SQL 生成在 `common/datafusion.rs`，Arrow 编码在 `crates/serialization/src/arrow/`（`mod.rs`、`quote.rs`、`legacy.rs`），数据类型到目录名的对应在 `crates/model/src/data/mod.rs` 的 `for_each_data_type!`。

**对应官方文档：** [Data Catalog](https://nautilustrader.io/docs/latest/concepts/data/catalog/)
:::

第 24 章的 `BacktestNode` 从数据目录读数据。数据目录是 NautilusTrader 自己的历史数据仓库：一个根目录下按数据类型和品种分好的 Parquet 文件，不需要单独的数据库服务。回测、研究和实盘的历史请求（第 18 章）都可以从这里读。

主线例子接着第 24 章的 `node_ema_cross` 示例：把 `AUD/USD.SIM` 的品种定义和 745 条报价（2025-01-01 00:00:00 起，每秒一条）写进一个空目录，再由回测节点读出来。

## 1. 目录长什么样 {#layout}

示例写入的两行代码是：

```rust
let catalog = ParquetDataCatalog::new(temp_dir.path(), None, None, None, None);
catalog.write_instruments(vec![instrument])?;
catalog.write_to_parquet(&quotes, None, None, None)?;
```

写完以后，目录是这样的：

```text
catalog/
└── data/
    ├── currency_pair/
    │   └── AUDUSD.SIM/
    │       └── 1970-01-01T00-00-00-000000000Z_1970-01-01T00-00-00-000000000Z.parquet
    └── quotes/
        └── AUDUSD.SIM/
            └── 2025-01-01T00-00-00-000000000Z_2025-01-01T00-12-24-000000000Z.parquet
```

三条规则：

- **按类型分目录。** 内置数据类型的目录名由 `for_each_data_type!` 宏统一定义：`quotes`、`trades`、`bars`、`order_book_deltas`、`order_book_depths`、`mark_prices`、`index_prices`、`funding_rates`、`instrument_status`、`option_greeks`、`instrument_closes`。品种定义不放在一个共用的 `instruments` 目录里，而是每个具体品种类一个目录，比如 `currency_pair`、`equity`、`crypto_perpetual`。自定义数据放在 `custom/{类型名}/` 下。
- **按标识符分子目录。** 一般是品种 ID，K 线是完整的 K 线类型。标识符里的 `/` 被删掉，`^` 换成 `_`，所以 `AUD/USD.SIM` 变成 `AUDUSD.SIM`。
- **文件名就是时间范围。** 格式是 `{起始}_{结束}.parquet`，两个时间都是 ISO 8601 格式，把 `:` 和 `.` 换成 `-`。起止默认取这批数据第一条和最后一条的 `ts_init`。示例里 745 条报价的最后一条在第 744 秒，也就是 00:12:24。示例的品种定义 `ts_init` 是 0，所以文件名是 1970 年。

文件名承载了时间范围，这一点很重要：查询时先看文件名就能排除大部分文件，不用打开它们（第 4 节）。也正因为如此，文件名和内容不一致会导致查询漏数据，第 6 节的“重置文件名”就是修这个的。

查询只读这些规范目录。旧版本的布局（比如 `data/quote_tick/`）不会被读到，要先用 `nautilus catalog migrate-parquet` 转换。

## 2. 写入时检查什么 {#write}

`write_to_parquet` 写一批数据时依次做：

1. **检查时间升序。** 这批数据必须按 `ts_init` 不减排列，否则报错。
2. **检查标识一致。** 一次调用只能写一个标识（一个品种，或一个 K 线类型）。要写多个品种，分开调用。
3. **编码成 Arrow 记录批**（第 3 节）。
4. **算出目录和文件名。** 目录由数据类型和记录批元数据里的 `instrument_id`（K 线是 `bar_type`）决定，文件名由起止时间决定。
5. **检查区间不重叠。** 读出这个目录下已有文件的时间区间，加上新文件的区间，要求两两不相交，否则拒绝写入。`skip_disjoint_check` 可以跳过这个检查，只应在你确定重叠是有意为之时使用。
6. **写文件。** 默认用 zstd（级别 1）压缩，每个行组最多 131,072 行。

第 5 步保证了一个性质：同一个目录里，任何时刻最多只有一个文件覆盖它。所以追加新数据时，新的一批必须在时间上接在已有数据之后（或之前），不能覆盖已有的时间段。示例的数据是 00:00:00 到 00:12:24；再写一批 00:12:25 开始的报价可以，再写一遍同样的 745 条就会被拒绝。

## 3. Arrow 编码：一行报价存成什么 {#encoding}

每种内置数据类型都实现了三个 trait：`ArrowSchemaProvider` 给出列定义，`EncodeToRecordBatch` 把一组对象编码成记录批，`DecodeTypedFromRecordBatch` 反过来。报价的列是：

| 列 | Arrow 类型 |
| --- | --- |
| `bid_price`、`ask_price` | `Decimal128(38, 16)` |
| `bid_size`、`ask_size` | `Decimal128(38, 16)` |
| `ts_event`、`ts_init` | `Timestamp(Nanosecond, "UTC")` |
| `identifier` | `Utf8`，可空 |

品种 ID 和精度不在每一行里重复，而是写在 schema 的元数据中：`instrument_id`、`price_precision`、`size_precision`，以及类型名 `type_name`。解码时先读元数据，再用其中的精度把每个十进制值还原成 `Price` 和 `Quantity`。

**价格为什么是 `Decimal128(38, 16)`。** 第 2 章讲过，`Price` 内部是一个按全局精度放大的整数：标准模式放大 10<sup>9</sup>，高精度模式放大 10<sup>16</sup>。目录不直接存这个整数，而是统一换成 16 位小数：标准模式写入时乘以 10<sup>7</sup>，高精度模式原样写入。这样两种模式写出的文件格式完全相同，可以互相读取，只有一个例外：标准模式读到第 9 位小数之后还有非零数字的值时会报错，因为它表示不了。旧版本的目录用 8 字节（标准）或 16 字节（高精度）的定长二进制存原始整数，现在读取时按字节宽度识别，并转换成同样的十进制形式（`legacy.rs`）。

时间戳用 Arrow 原生的纳秒 UTC 时间戳类型。用 Nautilus 自己的查询读不会丢精度，但有些 SQL 工具会把它映射到微秒精度的 `TIMESTAMPTZ`，从而截掉亚微秒部分。

## 4. 查询怎样决定读哪些文件 {#query}

Rust 里查询报价可以写成：

```rust
let quotes: Vec<QuoteTick> = catalog.query(
    Some(vec!["AUD/USD.SIM".to_string()]),   // 标识符
    Some(start), Some(end),                  // ts_init 范围，闭区间
    None,                                    // 额外的 SQL 条件
    None, false,
)?;
```

背后的步骤是：

1. **列出文件。** 递归列出 `data/quotes/` 下所有 `.parquet` 文件。
2. **按标识符筛选。** 只保留 `AUDUSD.SIM` 子目录下的文件。
3. **按文件名筛选。** 从文件名解析出起止时间，只保留和查询范围相交的文件（`query_intersects_filename`）。文件名解析不出来的文件保留，宁可多读也不漏读。
4. **用 DataFusion 查询。** 把剩下的文件注册成表，执行 `SELECT * FROM 表 WHERE (额外条件) AND ts_init >= start AND ts_init <= end ORDER BY ts_init`。额外条件是任意的 DataFusion SQL 表达式，比如 `ts_event <= ts_init`；它被加上括号，所以里面含 `OR` 也不会和时间条件错误地结合。
5. **解码并排序。** 记录批解码成 `QuoteTick`，如果多个文件的结果合起来不是按时间排好的，再排一次。

前三步只看路径和文件名，不打开任何文件；只有第 4 步真正读 Parquet，而 Parquet 的列式存储和行组统计又能让 DataFusion 跳过不相关的行组。所以一个按天切分文件的目录，查询一小时的数据只会打开一个文件。

## 5. 回测从目录加载 {#backtest}

`BacktestNode` 用 `BacktestDataConfig` 描述要加载的数据：

| 字段 | 含义 |
| --- | --- |
| `data_type` | 数据类型，比如 `QuoteTick` |
| `catalog` | 目录配置 `DataCatalogConfig`：路径或 URI、存储选项、压缩等 |
| `instrument_id` / `instrument_ids` / `bar_types` | 三者必须给一个 |
| `start_time`、`end_time` | 时间范围 |
| `filter_expr` | 额外的 SQL 条件 |
| `bar_spec` | 和品种 ID 组合出一个外部 K 线类型 |
| `batch_deltas` | 订单簿增量是否按事件成批播放，默认 `true` |

`build` 时，节点按数据配置从目录读出品种定义并加入引擎；`run` 时按第 24 章第 6 节的两种方式读数据：一次性读出，或者分页读出、和其他数据配置的流按时间合并后分块播放。分页读取（`query_typed_pages`）为每个表建一个流，每次取 `batch_size` 条（默认 1 万），多个流再按时间归并。

目录不一定在本地。路径可以是 `s3://`、`gs://`、`az://`、`http(s)://` 这样的 URI，凭证放在 `storage_options` 里，由 Rust 的 `object_store` 处理。

## 6. 维护操作 {#maintenance}

时间长了，一个目录里会积累很多小文件（比如每天追加一次）。目录提供几类维护操作：

- **合并**（`consolidate_catalog`、`consolidate_data`）：把一个目录里的多个文件合成一个。合并前检查文件之间没有空隙和重叠；`ensure_contiguous_files = false` 时允许合并有空隙的文件，但合并后的文件名会把空隙也算作“已覆盖”。合并先写新文件、再删旧文件；删旧文件失败时，查询会自动排除已被取代的旧文件，不会读到重复数据。
- **按周期切分**（`consolidate_catalog_by_period`）：按固定长度（比如一天）重新切分文件。
- **删除时间段**（`delete_data_range`、`delete_catalog_range`）：删除一段时间的数据，和这段时间部分重叠的文件会被拆开，保留范围外的部分。删除不可撤销。
- **重置文件名**（`reset_all_file_names`、`reset_data_file_names`）：读出每个文件内容的实际 `ts_init` 范围，把文件名改成和内容一致。只能修文件名的问题；如果文件内容本身重叠，重置会失败。

这些操作和写入都会修改文件，同一个目录实例上不要并发调用。

## 7. Feather 流式写入 {#streaming}

回测或实盘运行时，可以把总线上的数据和事件边跑边写下来。直接写 Parquet 不适合频繁追加，所以运行时先写到本地的 Feather 文件（Arrow IPC 格式），再“提升”进 Parquet 目录。`StreamingConfig` 配置 Feather 文件的位置和要提升到的目录；默认在关闭时提升一次，也可以设置 `promotion_interval_ms` 定时提升。提升成功之前，这些数据对目录查询不可见。第 24 章 `end()` 里的“关闭流式写入器”就是这一步。

![数据目录的写入和读取：左边是目录树，按类型、标识符分目录，文件名是时间范围；右上是写入一批报价的六步，从升序检查到区间不重叠检查再到写文件；右下是一次查询的五步，先按目录和文件名筛文件，再用 DataFusion SQL 过滤，最后解码排序](/nautilus-trader/figures/data-catalog-flow.svg)

怎么读这张图：左边的目录树是结构，右边上下两条是写入和读取的流水线。注意读取的前三步都只用到左边的路径信息，没有打开文件；写入的第 5 步也只看文件名。文件名在这个设计里同时是“索引”。

::: warning 常见误区
- **一次写入多个品种的数据。** 一次调用只能写一个标识，混在一起会被拒绝。
- **重复写入同一时间段，以为会覆盖。** 区间重叠会被拒绝；要替换数据，先删除那段时间再写。
- **为了绕过报错随手打开 `skip_disjoint_check`。** 重叠的文件会让查询返回重复数据。
- **手动改了文件名或移动了文件。** 文件名就是时间索引，改错了查询会漏数据，要用 `reset_data_file_names` 修复。
- **以为标准精度构建读不了高精度写出的目录。** 现在的格式两种模式通用，只有超出 9 位小数的值会报错。
- **把 `batch_size` 和 `chunk_size` 混为一谈。** 前者是目录每次读写的行数，后者是回测每块播放的数据条数。
:::

## 本章结论

数据目录是一个根目录下的 Parquet 文件集合，按数据类型、标识符分目录，文件名就是它覆盖的 `ts_init` 范围。写入要求数据按时间升序、只有一个标识、和已有文件区间不重叠；价格和数量统一存成 `Decimal128(38, 16)`，品种和精度写在 schema 元数据里，两种精度模式读写同一种格式。查询先按目录和文件名筛掉无关文件，再用 DataFusion SQL 按时间和附加条件过滤、按 `ts_init` 排序。回测节点用 `BacktestDataConfig` 从目录加载品种和数据；合并、切分、删除、重置文件名这些维护操作都以“文件名即时间索引”为前提。

## 检查理解

1. 目录里 `data/trades/ETHUSDT.BINANCE/` 下有三个文件，分别覆盖 1 月 1 日、1 月 2 日、1 月 3 日全天。查询 1 月 2 日 10:00 到 11:00 的成交，会读哪些文件？

   <details><summary>参考答案</summary>

   只读 1 月 2 日那个文件。查询先按目录选出这三个文件，再从文件名解析出起止时间，只有 1 月 2 日的文件和查询范围相交。DataFusion 在这个文件里再按 `ts_init` 过滤，还可能借助行组统计跳过不相关的行组。

   </details>

2. 你每天收盘后把当天的报价追加进目录。某天脚本出错，把当天的数据写了两遍。会发生什么？第二天发现后，想重写这一天的数据，应该怎样做？

   <details><summary>参考答案</summary>

   第二次写入会因为区间和第一次的文件重叠而被拒绝，目录里只有一份数据。如果第一份数据本身有问题需要重写，先用 `delete_data_range` 删除这一天的报价（这会删掉或拆开对应文件），再写入新数据。不要用 `skip_disjoint_check` 硬写，那样查询会返回重复的报价。

   </details>

3. 一份用 Python wheel（高精度模式）写出的目录，能不能被一个默认特性（标准模式）构建的 Rust 回测读取？

   <details><summary>参考答案</summary>

   能。目录统一存 16 位小数的十进制值，标准模式读取时除以 10<sup>7</sup> 换回自己的原始整数。只要数据的小数位不超过 9 位（绝大多数行情数据都是这样），读取就不会出问题；如果某个值在第 9 位小数之后还有非零数字，读取会报错并指出是哪一行。

   </details>

## 参考资料

- 官方文档：[Data Catalog](https://nautilustrader.io/docs/latest/concepts/data/catalog/)
- 源码：[`crates/persistence/src/backend/parquet/catalog/`](https://github.com/nautechsystems/nautilus_trader/tree/develop/crates/persistence/src/backend/parquet/catalog) · [`crates/persistence/src/common/datafusion.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/persistence/src/common/datafusion.rs) · [`crates/serialization/src/arrow/mod.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/serialization/src/arrow/mod.rs) · [`crates/serialization/src/arrow/quote.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/serialization/src/arrow/quote.rs)
- 配图由 `scripts/generate-nautilus-trader-figures.py` 生成。

数据播放出来以后，第一个看到它的是模拟交易所。下一章看模拟交易所和它里面的撮合引擎怎样用这些数据撮合订单。[第 26 章：模拟交易所与撮合引擎](./simulated-exchange.md)。
