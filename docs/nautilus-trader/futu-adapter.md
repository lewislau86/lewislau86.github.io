---
title: 给 nautilus_trader 加一个券商：富途适配器怎么做
description: 适配器在 nautilus_trader 里的接口边界，为什么富途应当参照 Interactive Brokers 适配器，富途 OpenD 协议要点，两边概念的对照，以及从协议层到实盘节点的实现里程碑。
---

# 给 nautilus_trader 加一个券商：富途适配器怎么做

[笔记目录](./index.md)

::: tip 本篇要回答的问题
在 nautilus_trader 里，一个券商要接进来，需要实现哪些 trait、放在哪些文件里；富途这种“本地网关 + 私有 TCP 协议”的券商，应该照着哪个现有适配器写；富途的协议有哪些地方会影响设计；第一步做什么、怎样验收。

**源码版本：** nautilus_trader `develop` 分支，2026-11-13 核对。**富途文档：** OpenAPI v10.12。
:::

## 结论先行

富途应该照着 **Interactive Brokers（IB）适配器**写，而不是照着 Bybit、OKX 这类加密货币交易所的适配器。

富途的接口不直接对外：你要先在本机运行它的网关程序 **OpenD**，登录后再通过 TCP（也可以配置成 WebSocket）连上去，每个包是 44 字节的包头加一段 protobuf。IB 的情况几乎一样：它也只能连本地的 TWS 或 IB Gateway。现在的 IB 适配器 `crates/adapters/interactive_brokers` 已经是纯 Rust 实现，底层协议交给第三方的 `ibapi` crate，适配器本身没有 `http/`、`websocket/` 模块，只做领域对象映射、订阅管理、下单和对账。开发指南的原话是 IB 没有这些模块，因为它“does not own a transport”。

所以富途适配器分两层：

1. **一个独立的 Rust 版 OpenD 客户端**（暂且叫 `futu-opend`），负责连接、包头编解码、加密、心跳、请求和回包的对应，地位相当于 IB 里的 `ibapi`；
2. **适配器 crate `crates/adapters/futu`**，把富途的概念翻译成 Nautilus 的概念：标的、行情、订单、成交、账户和对账。

## 1. 适配器在 nautilus_trader 里的边界

一个适配器对平台只暴露几个 trait，全部定义在 `nautilus_common` 里：

| trait | 文件 | 作用 |
| --- | --- | --- |
| `DataClient` | `crates/common/src/clients/data.rs` | 行情：`subscribe_*` / `unsubscribe_*`（报价、成交、盘口、K 线等），`request_*`（历史数据、标的） |
| `ExecutionClient` | `crates/common/src/clients/execution.rs` | 交易：`submit_order`、`modify_order`、`cancel_order` 等命令，以及 `generate_order_status_reports`、`generate_fill_reports`、`generate_position_status_reports`、`generate_mass_status` 这几个对账方法 |
| `InstrumentProvider` | `crates/common/src/providers.rs` | 加载标的：`load_all`、`load_ids`、`load` |
| `DataClientFactory`、`ExecutionClientFactory`、`ClientConfig` | `crates/common/src/factories/client.rs` | 由配置构造客户端，供实盘节点注册 |

`DataClient` 必须实现的只有 `client_id`、`venue`、`start`、`stop`、`reset`、`dispose`、`is_connected`、`is_disconnected`，其余方法都有默认实现：没实现的 `subscribe_*` 只打日志，没实现的 `request_*` 直接报错。所以可以一种数据一种数据地往上加。

`ExecutionClient` 必须实现的是 `client_id`、`account_id`、`venue`、`oms_type`、`get_account`、`generate_account_state`、`start`、`stop` 和 `is_connected`；下单、改单、撤单和几个对账方法都有默认实现，要逐个覆盖。

数据和事件往回走只有一条路：数据客户端发 `DataEvent`，执行客户端发 `ExecutionEvent`，通过 `nautilus_common::live::runner` 里的 `get_data_event_sender()`、`get_exec_event_sender()` 送进引擎。开发指南明确要求**适配器不要直接写缓存**。

对账是“拉”的模型：引擎在启动和需要时调用 `generate_*` 方法，适配器去券商那里查订单、成交、持仓，整理成 `OrderStatusReport`、`FillReport`、`PositionStatusReport` 交回来。平台自己跟踪的订单，推送来的变化转成订单事件；平台不认识的订单（比如在富途 App 上手动下的）转成报告。

命令失败要分类，用 `nautilus_live` 里的 `CommandFailure::{NotSent, VenueRejected, Ambiguous}`。超时、断线这类“不知道券商收没收到”的情况属于 `Ambiguous`，不能当成拒单处理，否则可能出现平台以为没下、券商那边却成交了的情况。

最后，客户端由工厂构造，注册进实盘节点：

```rust
// 示意，参照 crates/adapters/interactive_brokers/examples/node_data_tester.rs
let node = LiveNode::builder(trader_id, Environment::Live)?
    .add_data_client(None, Box::new(FutuDataClientFactory::new()), Box::new(data_config))?
    .add_exec_client(None, Box::new(FutuExecutionClientFactory::new()), Box::new(exec_config))?
    .build()?;
node.run().await?;
```

`LiveNodeBuilder` 在 `crates/live/src/node/builder.rs`，除了上面两个方法还有带路由的 `add_data_client_with_routing`、`add_exec_client_with_routing`，以及 `with_reconciliation` 等设置。

## 2. 照着 IB 适配器写什么

IB 适配器的目录结构（只列 `src/`）：

```text
src/
  lib.rs  config.rs  factories.rs  data_types.rs  stubs.rs
  common/      consts, contracts, enums, futures, shared_client, spreads, symbology
  data/        cache, convert, core, parse, streams
  execution/   account, commands, conditions, core, incarnations, order_state,
               parse, reports, spreads, transform, updates
  providers/   instruments, parse
  historical/  client.rs
  gateway/     dockerized, startup
  python/      config, conversion, enums, factories, gateway, historical, providers, mod
```

另有 `examples/node_data_tester.rs`、`examples/node_exec_tester.rs`、`test_data/`（录下来的回包）和 `tests/integration/`。

值得照抄的几处设计：

- **共享连接。** 数据、执行、历史三个客户端用同一组 `(host, port, client_id)` 时，共用一条带引用计数的连接（`common/shared_client.rs`）。富途也一样：一个 OpenD 连接既收行情也收交易推送，没必要开两条。
- **客户端 venue 和标的 venue 分开。** IB 的客户端和账户用 venue `IB`，标的却挂在交易所上（比如 `AAPL.XNAS`），所以 `InteractiveBrokersExecutionClient` 把 `handles_order_venue` 覆盖成一律返回 `true`，注释写的是“IB uses a broker venue for the client while routing exchange-MIC instruments”。富途可以照此设计：客户端 venue 用 `FUTU`，标的用交易所，比如 `00700.XHKG`、`AAPL.XNAS`。（具体的 ID 格式是我的建议，还要和平台的符号约定再对一遍。）
- **对账数据从三处来**：订单（未完成和已完成）、成交（连同佣金）、持仓；持仓不生成虚拟订单。
- **命名和配置规范**（来自开发指南）：类型叫 `FutuDataClient`、`FutuDataClientConfig`、`FutuDataClientFactory`、`FutuExecutionClient`……不加 `Live` 前缀，`Execution` 不缩写；配置用强类型字段、严格的 Serde、`bon::Builder`，密码用 `SecretString`。
- **运行时规则**：trait 方法里不能 `block_on`；后台任务交给 `TaskGroup`，预提交检查会拒绝直接 `tokio::spawn`；只有账户和标的在引擎里都能看到之后，才报告“已连接”。
- **价格精度**：价格和数量经 `Decimal` 进 `Price::from_decimal`，不经过 `f64`。券商发的是浮点数时（富途就是），要在解析边界明确处理。

有一处 IB 的写法不能照抄：它把股票的每手股数写死成 100（`lot_size(Quantity::new(100.0, 0))`）。港股每只股票的每手股数不同，富途要用它返回的 `lotSize` 字段。

还有一个基础设施上的坑：`nautilus_network::socket::SocketClient` 只支持“按结尾分隔符切包”（Betfair 的流用 `\r\n`），文档写明空的分隔符会被拒绝。富途的包是“固定包头 + 包体长度”，用不上它，要自己写编解码器（比如基于 `tokio_util::codec`）。

## 3. 富途 OpenD 协议要点

OpenD 是运行在你电脑或服务器上的网关程序，登录富途账号以后在本地开放 Socket 服务（默认 `127.0.0.1:11111`），客户端只连 OpenD。官方 SDK 有 Python、Java、C#、C++、JavaScript 五种，没有 Rust；文档里专门有一页“底层协议介绍”，就是给自己实现协议的人看的。

**包头**，44 字节，全部小端：

```rust
// 示意：字段顺序和大小来自富途“底层协议介绍”页与 Python SDK 的 MESSAGE_HEAD_FMT = "<1s1sI2B2I20s8s"
struct Header {
    flag: [u8; 2],       // b"FT"
    proto_id: u32,       // 协议 ID
    fmt: u8,             // 0 = protobuf，1 = JSON
    ver: u8,             // 0
    serial_no: u32,      // 包序号，用来对应请求和回包
    body_len: u32,       // 包体长度（加密后的）
    body_sha1: [u8; 20], // 包体的 SHA1（按加密前的明文算）
    reserved: [u8; 8],   // 填 0
}
```

**包体**是 proto2 语法的 protobuf，每个协议都是 `Request{ c2s }` / `Response{ retType, retMsg, errCode, s2c }`，推送只有 `Response`。`retType` 里 -100 是超时、-200 是断开，对应上一节的 `Ambiguous`。Rust 侧可以用 `prost` 从 `.proto` 生成代码。

**`.proto` 要从最新版 PyPI 包 `futu-api` 里取**，不要用 GitHub 上 `py-futu-api` 仓库 master 分支的，那里比文档旧，比如 `TimeInForce` 只有 DAY 和 GTC，缺了文档里已有的 IOC 和 GTD。

**加密**是可选的：只有 OpenD 配了 `rsa_private_key` 才启用。InitConnect 用 RSA，之后的包用 InitConnect 返回的 AES 密钥；默认算法 FTAES_ECB 是富途改过的填充方式（补零到 16 的倍数，再追加一个记录原长度余数的 16 字节块）。本机调试可以先不开。

**连接流程**：

1. InitConnect（1001）：上报客户端版本、是否接收推送、加密算法；拿回 `connID`、AES 密钥和心跳间隔 `keepAliveInterval`。
2. 按间隔发 KeepAlive（1004）。
3. GetGlobalState（1002）查各市场状态、行情和交易是否已登录。
4. 随时可能收到 Notify（1003）推送，比如被踢下线。

**常用协议号**（来自 Python SDK `futu/common/constant.py` 的 `ProtoId`，交易和订阅相关的已对照文档逐个核对）：

| 用途 | 协议 |
| --- | --- |
| 连接 | InitConnect 1001、GetGlobalState 1002、Notify 1003（推送）、KeepAlive 1004 |
| 标的 | Qot_GetStaticInfo 3202（含每手股数 `lotSize`） |
| 订阅与行情推送 | Qot_Sub 3001；UpdateBasicQot 3005、UpdateKL 3007、UpdateTicker 3011、UpdateOrderBook 3013 |
| 历史 K 线 | Qot_RequestHistoryKL 3103、剩余额度 3104 |
| 账户 | Trd_GetAccList 2001、Trd_UnlockTrade 2005、Trd_SubAccPush 2008、Trd_GetFunds 2101、Trd_GetPositionList 2102 |
| 下单与改单 | Trd_PlaceOrder 2202、Trd_ModifyOrder 2205（改单和撤单都走它，靠 `ModifyOrderOp` 区分） |
| 订单与成交推送 | Trd_UpdateOrder 2208、Trd_UpdateOrderFill 2218 |
| 查询 | Trd_GetOrderList 2201、Trd_GetOrderFillList 2211、历史订单 2221、历史成交 2222 |

几条会直接影响设计的限制：

- **订阅额度按资产分档**，从 100 到 2000 个不等（一只股票的一种数据占 1 个额度），订阅后至少 1 分钟才能退订。适配器的订阅管理要记账，退订要延后执行。
- **交易限频**（同一账户每 30 秒）：下单 15 次、改单和撤单 20 次，各类查询 10 次。要接限流器；对账查询不能太频繁。
- **`Trd_SubAccPush` 每次都要传完整的账户列表**，不调用就收不到 2208/2218 推送。Python SDK 替你调了，自己实现协议时容易漏。
- **下单要带 `PacketID{connID, serialNo}`**，用来防重放。
- **实盘下单前要 `Trd_UnlockTrade`**（交易密码的 MD5），模拟盘不用；解锁作用于整个 OpenD；图形界面版 OpenD 不支持用接口解锁。
- **代码格式**：港股必须 5 位数字（`00700`），A 股 6 位，美股不限；协议里证券是 `{market, code}`，`HK.00700` 只是 SDK 的字符串写法。

## 4. 两边的概念对照

| 富途 | Nautilus |
| --- | --- |
| OpenD 连接、InitConnect、KeepAlive | 共享连接层（参照 IB 的 `shared_client.rs`），后台任务交给 `TaskGroup` |
| `Security{market, code}` | `InstrumentId` 与富途代码的双向转换，要有往返测试 |
| GetStaticInfo | `InstrumentProvider` 生成 `Equity`，每手股数用 `lotSize` |
| Qot_Sub + 推送 3005 / 3013 / 3011 / 3007 | `subscribe_quotes` / `subscribe_book_deltas` / `subscribe_trades` / `subscribe_bars` |
| RequestHistoryKL | `request_bars` |
| GetAccList、SubAccPush、GetFunds | 执行客户端的连接流程、`AccountState`；现金账户和融资账户对应 `AccountType::Cash` / `Margin` |
| PlaceOrder、ModifyOrder | `submit_order`、`modify_order`、`cancel_order`，前面加限流 |
| UpdateOrder、UpdateOrderFill | 平台跟踪的订单：订单事件、成交事件；平台不认识的订单：`OrderStatusReport`、`FillReport` |
| GetOrderList、GetOrderFillList、GetPositionList | 三个 `generate_*_reports` 对账方法 |
| `retType` -100（超时）、-200（断开） | `CommandFailure::Ambiguous` |
| `OrderStatus`（Submitted、Filled_Part、Cancelled_All……） | Nautilus 的 `OrderStatus`，逐个写映射和测试 |

## 5. 从哪里开始：五个里程碑

全程先连**模拟盘**（`TrdEnv = SIMULATE`），不用解锁交易密码。注意美股模拟盘不支持盘前盘后。

| 里程碑 | 内容 | 验收 |
| --- | --- | --- |
| M0 协议层 | 包头编解码、SHA1、InitConnect、KeepAlive；写一个 `bin` 例子打印 GetGlobalState | 连上本机 OpenD，心跳稳定几个小时不断线 |
| M1 标的 | GetStaticInfo → `Equity`；代码与 `InstrumentId` 互转 | 往返测试；港股每手股数正确 |
| M2 行情 | 先只订阅 00700 的报价，推送转成 `QuoteTick` | 官方的 `DataTester` 例子能跑通 |
| M3 交易 | 先做账户和对账（`generate_mass_status`），再做下单和撤单 | `ExecTester` 能跑通；重启后对账结果一致 |
| M4 组装 | 工厂、配置、`LiveNode` 例子；最后才是 PyO3 绑定 | Python 侧能用同一个配置启动 |

开发指南把适配器开发分成 0～9 个阶段：范围、协议核心、标的、行情、执行、可选能力、工厂和 PyO3、一致性测试、性能测试和 fuzz、文档。上面的里程碑基本对应前七个阶段。

## 6. 放进官方仓库，还是自己维护

| | 放进官方仓库（in-tree） | 自己维护（out-of-tree） |
| --- | --- | --- |
| 形式 | `crates/adapters/futu`，接入根 `Cargo.toml`、`Makefile` 的 `ADAPTER_CRATES`、`crates/pyo3` | 独立的 Python 包，或独立的 Rust/PyO3 包 |
| 门槛 | 高：开发指南要求官方适配器带确定性模拟测试（DST）、fuzz、一致性测试和文档 | 低：按 `docs/developer_guide/python_adapters.md` 写 |
| 限制 | 跟着主仓库的节奏和规范走 | 独立的 Rust 包只能通过已安装 wheel 里的 Python 模型类交换对象，不能和 Nautilus 共享 Rust trait 对象 |

先在自己的仓库里把模拟盘跑通，等结构稳定了再考虑往上游提。

::: warning 容易踩的坑
- **把 OpenD 当成 REST 服务。** 它是长连接 + 推送，下单的回包只说明“OpenD 收到了”，订单状态要看 2208 推送或查询。
- **忘了调 `Trd_SubAccPush`。** 不调就收不到任何订单和成交推送，看起来像“下了单没反应”。
- **用 GitHub master 上的 `.proto`。** 比文档旧，生成的代码缺字段。
- **每手股数写死。** 港股每只不同。
- **超时当拒单。** 超时和断线是“结果未知”，要等对账查清楚。
- **把订阅额度当成无限。** 额度用完后订阅会失败，退订还要等 1 分钟才生效。
:::

## 待核实

以下几点文档没写清楚，动手前要在 OpenD 上实测：漏发 KeepAlive 多久会被断开；包序号是否必须严格递增（文档说“要求递增”，Python SDK 却用随机的唯一 ID）；重复的 `PacketID` 被拒时的具体行为；碎股下单规则；“最多 128 条连接”只出现在官方示例的注释里。

## 参考资料

- nautilus_trader：[仓库（develop 分支）](https://github.com/nautechsystems/nautilus_trader) · [适配器开发指南](https://github.com/nautechsystems/nautilus_trader/blob/develop/docs/developer_guide/adapters.md) · [树外适配器指南](https://github.com/nautechsystems/nautilus_trader/blob/develop/docs/developer_guide/python_adapters.md) · [IB 适配器源码](https://github.com/nautechsystems/nautilus_trader/tree/develop/crates/adapters/interactive_brokers)
- 富途 OpenAPI：[底层协议介绍](https://openapi.futunn.com/futu-api-doc/ftapi/protocol.html) · [OpenD 概述](https://openapi.futunn.com/futu-api-doc/opend/opend-intro.html) · [OpenD 命令行参数](https://openapi.futunn.com/futu-api-doc/opend/opend-cmd.html) · [权限与额度](https://openapi.futunn.com/futu-api-doc/intro/authority.html) · [订阅规则](https://openapi.futunn.com/futu-api-doc/quote/sub.html) · [交易接口总览](https://openapi.futunn.com/futu-api-doc/trade/trade.html)
- [py-futu-api](https://github.com/FutunnOpen/py-futu-api)：`futu/common/constant.py`（协议号）、`utils.py`（包头）、`conn_mng.py`（加密）、`pb/*.proto`
