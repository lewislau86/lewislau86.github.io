---
title: "第 2 章：增加一个券商：以富途为例"
description: 适配器在 NautilusTrader 里的接口边界；富途适配器放在 Rust 架构的哪一层、运行时在哪个线程；为什么照着 Interactive Brokers 适配器写；富途 OpenD 协议要点和概念对照；Python 怎么绑定；以及从协议层到实盘节点的实现里程碑。
---

# 第 2 章：增加一个券商：以富途为例

[全书目录](./index.md) · [上一章](./architecture.md) · [下一章](./core-topics.md)

::: tip 本章要回答的问题
在 NautilusTrader 里，一个券商要接进来，需要实现哪些 trait、放在 Rust 架构的哪一层、运行时跑在哪个线程上；富途这种“本地网关 + 私有 TCP 协议”的券商，应该照着哪个现有适配器写；富途的协议有哪些地方会影响设计；写好的 Rust 适配器怎样暴露给 Python；第一步做什么、怎样验收。

**源码版本：** NautilusTrader `develop` 分支，2026-11-13 核对，第 2 节和第 6 节按提交 `5997d82`（2026-11-17）补充。**富途文档：** OpenAPI v10.12。文中的 `futu-opend`、`adapters/futu` 及其文件和类型名都是本书的设计建议，仓库里还没有。
:::

## 结论先行

富途应该照着 **Interactive Brokers（IB）适配器**写，而不是照着 Bybit、OKX 这类加密货币交易所的适配器。这是本书按协议形态做的判断：开发指南 `docs/developer_guide/adapters.md` 推荐的参考适配器是 Bybit、OKX、Binance、Kraken、Lighter、Derive，并没有 IB，而且提醒“有选择地参考”。

富途的接口不直接对外：你要先在本机运行它的网关程序 **OpenD**，登录后再通过 TCP（也可以配置成 WebSocket）连上去，每个包是 44 字节的包头加一段 protobuf。IB 的情况几乎一样：它也只能连本地的 TWS 或 IB Gateway。现在的 IB 适配器 `crates/adapters/interactive_brokers` 已经是纯 Rust 实现，底层协议交给第三方的 `ibapi` crate，适配器本身没有 `http/`、`websocket/` 模块，只做领域对象映射、订阅管理、下单和对账。IB 的集成文档（`docs/integrations/interactive_brokers.md`）的原话是它“does not own a transport”，所以其他适配器标配的 `http`、`websocket` 模块在这里不存在。

所以富途适配器分两层：

1. **一个独立的 Rust 版 OpenD 客户端**（暂且叫 `futu-opend`），负责连接、包头编解码、加密、心跳、请求和回包的对应，地位相当于 IB 里的 `ibapi`；
2. **适配器 crate `crates/adapters/futu`**，把富途的概念翻译成 Nautilus 的概念：标的、行情、订单、成交、账户和对账。

## 1. 适配器在 NautilusTrader 里的边界

[第 1 章](./architecture.md)讲了整体架构：适配器位于最外层，通过 channel 把数据和事件送进单线程的核心。一个适配器对平台只暴露几个 trait，全部定义在 `nautilus_common` 里：

| trait | 文件 | 作用 |
| --- | --- | --- |
| `DataClient` | `crates/common/src/clients/data.rs` | 行情：`subscribe_*` / `unsubscribe_*`（报价、成交、盘口、K 线等），`request_*`（历史数据、标的） |
| `ExecutionClient` | `crates/common/src/clients/execution.rs` | 交易：`submit_order`、`modify_order`、`cancel_order` 等命令，以及 `generate_order_status_report`（查单个订单）、`generate_order_status_reports`、`generate_fill_reports`、`generate_position_status_reports`、`generate_mass_status` 这几个对账方法 |
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

## 2. 富途适配器放在 Rust 架构的哪里

### 2.1 在 crate 依赖图里

![富途适配器在 crate 依赖图中的位置：adapters/futu 与 adapters/interactive_brokers 平级，被 pyo3 在 adapters feature 下依赖，自己依赖 live 并实现 common 里的 DataClient、ExecutionClient trait；下面另有一个新增的独立协议库 futu-opend，对应 IB 依赖的第三方 ibapi](/nautilus-trader/figures/futu-in-crates.svg)

怎么读这张图：橙色虚线框是要新增的，其余都是仓库里现有的（依赖关系见[第 1 章](./architecture.md)第 2 节的完整依赖图）。

- **和 IB 适配器平级，挂在 `live` 之下。** IB 适配器 `Cargo.toml` 里 nautilus 方面的必选依赖是 `nautilus-common`、`nautilus-core`、`nautilus-live`、`nautilus-model`，另有 `ibapi`、`tokio`、`anyhow`、`async-trait` 等第三方依赖；`nautilus-execution`、`nautilus-network` 是可选的，但默认的 `execution` feature 会打开它们；`nautilus-system` 只在 `python` feature 下打开，因为 Python 用到的工厂注册表 `get_global_pyo3_registry()` 定义在 `crates/system/src/python/registry.rs`。富途照此设计。
- **trait 来自 `common`。** 适配器真正“插进”平台的接口是第 1 节那几个 trait，它们在 `nautilus-common` 里；`live` 提供的是节点、`TaskGroup`、命令失败分类等运行时设施。
- **协议库单独成 crate。** `futu-opend` 只管和 OpenD 说话，地位等同 IB 适配器下面的 `ibapi`。要注意一个约束：进官方仓库的适配器必须满足确定性仿真测试（DST）的约定，`docs/concepts/dst.md` 要求时间、任务、随机数都经 `nautilus_common::live::dst` 获取，TCP 连接要经 `nautilus_network::net` 建立，不能直接 `tokio::net::TcpStream::connect`。所以如果目标是进官方仓库，`futu-opend` 不能完全不依赖 nautilus，至少要用这两处的替身；只在自己的仓库里维护（第 8 节）时才可以完全独立。这样它能单独测试、单独发布，别的 Rust 项目也能用。
- **最上面是 `pyo3`。** 它在 `adapters` feature 下可选依赖各个适配器（`blockchain` 例外，挂在 `defi` 下），依赖声明里同时打开适配器的 `python` feature，这是第 6 节 Python 绑定的入口。

两个新 crate 的 `Cargo.toml` 大致如下：

```toml
# 示意：crates/adapters/futu/Cargo.toml（依赖照 interactive_brokers，feature 参考 okx）
[package]
name = "nautilus-futu"

[dependencies]
nautilus-common = { workspace = true }
nautilus-core = { workspace = true }
nautilus-live = { workspace = true }
nautilus-model = { workspace = true }
nautilus-system = { workspace = true, optional = true }
futu-opend = { path = "../../futu-opend" }      # 即 crates/futu-opend；或独立仓库、crates.io
tokio = { workspace = true }
anyhow = { workspace = true }
async-trait = { workspace = true }              # 客户端 trait 用 #[async_trait(?Send)]
pyo3 = { workspace = true, optional = true }
pyo3-stub-gen = { workspace = true, optional = true }

[features]
default = ["high-precision"]                    # IB 没有这个 feature；这里照 OKX、Bybit 等多数适配器
high-precision = ["nautilus-model/high-precision"]
python = ["dep:nautilus-system", "nautilus-system/python", "nautilus-live/python",
          "nautilus-model/python", "nautilus-common/python", "pyo3", "pyo3-stub-gen"]
extension-module = ["python", "pyo3/extension-module", "nautilus-model/extension-module" /* … */]
```

### 2.2 建议的目录

按开发指南的推荐结构（见[第 0 章](./nautilus-architecture.md)第 2.5 节）和 IB 适配器的实际目录，富途适配器可以这样组织：

```text
crates/futu-opend/             # 独立协议库（不依赖 nautilus；也可以放在单独的仓库）
  build.rs                     # prost-build 从 .proto 生成代码
  proto/                       # 从 PyPI futu-api 包里取的 .proto
  src/codec.rs                 # 44 字节包头 + 包体的 tokio_util 编解码器
  src/crypto.rs                # RSA（InitConnect）、FTAES_ECB
  src/client.rs                # 连接、InitConnect、KeepAlive、serial_no → 等待中的请求、推送分发

crates/adapters/futu/
  src/lib.rs
  src/common/                  # FUTU venue 常量、枚举映射、Security{market, code} ↔ InstrumentId；
                               # shared_client.rs：数据、执行、标的加载共用一条 OpenD 连接（同 IB）
  src/config.rs                # FutuDataClientConfig、FutuExecutionClientConfig、FutuInstrumentProviderConfig
  src/providers.rs             # FutuInstrumentProvider：GetStaticInfo → Equity
  src/data/                    # FutuDataClient：订阅额度记账、推送 → QuoteTick / TradeTick / OrderBookDeltas / Bar
  src/execution/               # FutuExecutionClient：下单限流、2208/2218 → 订单事件、对账报告
  src/factories.rs             # FutuDataClientFactory、FutuExecutionClientFactory
  src/python/                  # PyO3 投影（第 6 节）
  tests/                       # 公开边界的集成测试（开发指南要求有）
  examples/                    # node_data_tester.rs、node_exec_tester.rs
  test_data/                   # 录下来的 OpenD 回包和推送
```

### 2.3 运行时：在哪个线程上做什么

![富途适配器的运行时位置：核心线程上 DataEngine、ExecutionEngine 经适配器包装调用 FutuDataClient、FutuExecutionClient 的同步方法，方法把网络工作交给 Tokio 上 TaskGroup 的任务后立刻返回；任务经共享连接 FutuSharedClient 和本机 OpenD 通信；推送解析后经 channel 交给 AsyncRunner，再派发回引擎](/nautilus-trader/figures/futu-runtime.svg)

怎么读这张图：左边是核心线程，中间是 Tokio，右边是外部进程。命令从左往右走，事件从右往左回来。

- **trait 方法是同步的，要立刻返回。** `DataClient::subscribe_quotes(&mut self, cmd) -> anyhow::Result<()>`、`ExecutionClient::submit_order(&self, cmd) -> anyhow::Result<()>` 都是普通函数，在核心线程上被引擎经 `DataClientAdapter`（`crates/data/src/client.rs`）和 `ExecutionClientAdapter`（`crates/execution/src/client/mod.rs`）调用。它们只能做校验和记账，然后把真正的网络请求交给后台任务。只有 `connect`、`disconnect` 和几个 `generate_*` 对账方法是 `async` 的（trait 用 `#[async_trait(?Send)]` 声明）。
- **后台任务放进 `TaskGroup`。** `nautilus_live::task::TaskGroup` 负责任务的启动、取消和收尾；IB 的数据客户端就持有 `session_tasks`、`command_tasks` 两个 `TaskGroup`。开发指南不允许在适配器代码里直接 `tokio::spawn`（预提交钩子会拦下），确实需要时用 `nautilus_common::live::get_runtime().spawn()`。
- **一条共享连接。** 订阅、下单、查询都经过同一个 `FutuSharedClient`：它持有编解码器、`serial_no` 到等待中请求的映射、KeepAlive 定时器、按 `proto_id` 的推送分发和限流器。
- **事件只能经 channel 回来。** 推送解析成 Nautilus 对象后，用 `get_data_event_sender()`、`get_exec_event_sender()`（`crates/common/src/live/runner.rs`）发出去；核心线程上的 `AsyncRunner` 取出来，送到 `DataEngine.process_data`、`ExecEngine.process` 这些端点。适配器能拿到的缓存是只读的 `CacheView`。

### 2.4 放进仓库时要改的现有文件

开发指南 “Repository and Python wiring” 一节列了新适配器必须接入的地方：

| 位置 | 改什么 |
| --- | --- |
| 根 `Cargo.toml` | `members` 加 `crates/adapters/futu`，`[workspace.dependencies]` 加 `nautilus-futu` |
| `Makefile` | `ADAPTER_CRATES` 加 `nautilus-futu`（工作区测试清单会检查） |
| `crates/pyo3/Cargo.toml` | 可选依赖 `nautilus-futu`（`features = ["python"]`），加进 `adapters` feature，并在 `extension-module`、`high-precision` 等 feature 里传递 |
| `crates/pyo3/src/lib.rs` | 注册 `_libnautilus.futu` 子模块（第 6 节） |
| 适配器自己的 `src/python/` | 向全局注册表登记工厂和配置的提取函数 |
| Python 包、示例、文档 | `python/nautilus_trader/adapters/futu/`、`examples/live/futu/`、`python/tests/unit/adapters/futu/`、`docs/integrations/futu.md` |

## 3. 照着 IB 适配器写什么

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

## 4. 富途 OpenD 协议要点

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

**包体**是 proto2 语法的 protobuf，每个协议都是 `Request{ c2s }` / `Response{ retType, retMsg, errCode, s2c }`，推送只有 `Response`。`retType` 里 -100 是超时、-200 是断开，对应第 1 节的 `Ambiguous`。Rust 侧可以用 `prost` 从 `.proto` 生成代码。

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

## 5. 两边的概念对照

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

## 6. Python 怎么绑定

![富途适配器的 Python 绑定：路线 A 和 IB 一样，在 Rust 类型上加 pyclass、在 pymodule 里登记、由 crates/pyo3 挂成 _libnautilus.futu、再由 Python 包转出，用户把工厂和配置交给 LiveNode.builder 的 add_data_client，节点按名字查注册表取出 Rust 对象；路线 B 是继承 nautilus_trader.live.clients 的纯 Python 客户端；路线 C 是独立的 Rust/PyO3 包](/nautilus-trader/figures/futu-python-binding.svg)

怎么读这张图：左边是官方适配器的路线，每一步对应一个文件；右边是不改 NautilusTrader 仓库也能走的两条路。

### 6.1 路线 A：Rust 适配器 + PyO3 绑定

这是 IB、OKX 等官方适配器的做法。适配器全部逻辑在 Rust 里，Python 只拿到**配置类和工厂类**，用来告诉节点“建一个富途客户端”。客户端本身不出现在 Python 里，跑起来以后和纯 Rust 节点完全一样。

**① 配置和工厂类型加 `#[pyclass]`。** 和第 0 章讲的模型类型一样，在 `python` feature 下给 Rust 结构体加属性，Python 侧的模块名写公开路径：

```rust
// 示意：crates/adapters/futu/src/factories.rs（照 interactive_brokers/src/factories.rs）
#[derive(Clone, Debug)]
#[cfg_attr(feature = "python",
    pyo3::pyclass(module = "nautilus_trader.adapters.futu", from_py_object))]
#[cfg_attr(feature = "python",
    pyo3_stub_gen::derive::gen_stub_pyclass(module = "nautilus_trader.adapters.futu"))]
pub struct FutuDataClientFactory;

impl DataClientFactory for FutuDataClientFactory {
    fn create(&self, name: &str, config: &dyn ClientConfig, cache: CacheView,
              _clock: Rc<RefCell<dyn Clock>>) -> anyhow::Result<Box<dyn DataClient>> {
        let config = config.as_any().downcast_ref::<FutuDataClientConfig>()
            .ok_or_else(|| anyhow::anyhow!("expected FutuDataClientConfig"))?.clone();
        Ok(Box::new(FutuDataClient::new(ClientId::from(name), config, cache)?))
    }
    fn name(&self) -> &str { "FUTU" }          // 注册表靠这个名字找提取函数
    fn config_type(&self) -> &str { "FutuDataClientConfig" }
}

// 示意：crates/adapters/futu/src/python/factories.rs（照 IB 的同名文件）
#[pymethods]
#[pyo3_stub_gen::derive::gen_stub_pymethods]
impl FutuDataClientFactory {
    #[new]
    fn py_new() -> Self { Self }
    #[pyo3(name = "name")]
    fn py_name(&self) -> &str { "FUTU" }      // Python 侧也要能调用 name()
}
```

工厂必须在 `#[pymethods]` 里把 `name()` 暴露给 Python（IB 的 `src/python/factories.rs` 就有 `py_name`），因为节点的 Rust 代码会通过 PyO3 调用这个 Python 对象的 `name()` 方法，拿返回值去查注册表。每个 `#[pymethods]` 下面都要紧跟 `gen_stub_pymethods`，否则生成的 `.pyi` 里没有这些方法。配置类在 `src/python/config.rs` 里再写一个 `#[new]`，参数全部可选，这样 Python 可以用关键字参数构造（IB 的 `InteractiveBrokersDataClientConfig` 就是这样，有十几个可选参数）。

**② `#[pymodule] fn futu`。** 在 `src/python/mod.rs` 里把类登记到模块，并向**全局工厂注册表**登记两类提取函数：

```rust
// 示意：crates/adapters/futu/src/python/mod.rs（照 interactive_brokers/src/python/mod.rs）
fn extract_futu_data_factory(py: Python<'_>, factory: Py<PyAny>)
    -> PyResult<Box<dyn DataClientFactory>> {
    factory.extract::<FutuDataClientFactory>(py)
        .map(|f| Box::new(f) as Box<dyn DataClientFactory>)
        .map_err(|e| to_pyvalue_err(format!("Failed to extract FutuDataClientFactory: {e}")))
}

fn extract_futu_data_config(py: Python<'_>, config: Py<PyAny>)
    -> PyResult<Box<dyn ClientConfig>> {
    config.extract::<FutuDataClientConfig>(py)
        .map(|c| Box::new(c) as Box<dyn ClientConfig>)
        .map_err(|e| to_pyvalue_err(format!("Failed to extract FutuDataClientConfig: {e}")))
}

#[pymodule]
pub fn futu(_py: Python<'_>, m: &Bound<'_, PyModule>) -> PyResult<()> {
    // 开发指南要求客户端相关的 add_class 按导出类型名的字母序排列（IB 自己没遵守）
    m.add_class::<FutuDataClientConfig>()?;
    m.add_class::<FutuDataClientFactory>()?;
    m.add_class::<FutuExecutionClientConfig>()?;
    m.add_class::<FutuExecutionClientFactory>()?;

    let registry = nautilus_system::get_global_pyo3_registry();
    registry.register_factory_extractor("FUTU".to_string(), extract_futu_data_factory)
        .map_err(|e| to_pyruntime_err(format!("{e}")))?;
    registry.register_config_extractor("FutuDataClientConfig".to_string(), extract_futu_data_config)
        .map_err(|e| to_pyruntime_err(format!("{e}")))?;
    // 执行客户端用 register_exec_factory_extractor，配置同上
    Ok(())
}
```

**③ 挂到 `_libnautilus`。** 在 `crates/pyo3/src/lib.rs` 里照其他适配器加一段：

```rust
// 示意：crates/pyo3/src/lib.rs
#[cfg(feature = "adapters")]
{
    let n = "futu";
    let submodule = pyo3::wrap_pymodule!(nautilus_futu::python::futu);
    m.add_wrapped(submodule)?;
    sys_modules.set_item(format!("{module_name}.{n}"), m.getattr(n)?)?;
}
```

`crates/pyo3/Cargo.toml` 同时加上 `nautilus-futu = { workspace = true, optional = true, features = ["python"] }`，并把 `dep:nautilus-futu` 写进 `adapters` feature、把 `nautilus-futu?/extension-module` 写进 `extension-module` feature。

**④ Python 包转出。** 新建 `python/nautilus_trader/adapters/futu/__init__.py`，照 IB 的写：导入 `fixup_module_names`，`from nautilus_trader._libnautilus.futu import *`，**手写一个 `__all__` 列表**列出公开的类，最后调用 `fixup_module_names(globals(), __name__)`。`__init__.pyi` 由 `make py-stubs` 生成，不手写；生成脚本会把 `__init__.py` 里的 `__all__` 抄进存根，适配器的外观模块没有 `__all__` 会直接报错。

**⑤⑥ 用户脚本和节点。** Python 里的用法和 IB 的 `examples/live/interactive_brokers/data_tester.py` 一样：

```python
# 示意：examples/live/futu/data_tester.py
from nautilus_trader.adapters.futu import FutuDataClientConfig, FutuDataClientFactory
from nautilus_trader.common import Environment
from nautilus_trader.live import LiveNode
from nautilus_trader.model import TraderId

node = (
    LiveNode.builder("FUTU-DATA-TESTER-001", TraderId.from_str("TESTER-001"), Environment.LIVE)
    .add_data_client(None, FutuDataClientFactory(), FutuDataClientConfig(host="127.0.0.1", port=11111))
    .build()
)
node.run()
```

`add_data_client` 是 `crates/live/src/python/node.rs` 里的现成代码。它先判断工厂是不是 Python 写的（路线 B）；不是的话，调用工厂的 `name()` 得到 `"FUTU"`，在注册表里找到 ② 登记的提取函数，把 Python 对象提取成 `Box<dyn DataClientFactory>`；再用配置对象的**类名** `"FutuDataClientConfig"` 找到配置提取函数，得到 `Box<dyn ClientConfig>`；最后交给 Rust 的 `LiveNodeBuilder`。因为是 `from_py_object` 提取，Rust 拿到的是配置的一份拷贝，之后在 Python 里改配置对象不会影响已经建好的节点。

这条路线的注册表是一张“名字 → 函数指针”的表，这就是为什么 PyO3 能把一个 Python 对象变回 Rust 的 trait 对象：每个适配器在自己的模块初始化时把“怎样从 Python 对象还原出我的工厂”登记进去，节点按名字查表即可，`live` crate 不需要认识任何具体的适配器。

### 6.2 路线 B：纯 Python 适配器

不改 NautilusTrader 仓库，直接在 Python 里写客户端。`nautilus_trader/live/clients.py` 提供了基类，用法见开发指南 `docs/developer_guide/python_adapters.md` 和 `examples/live/_template/`：

```python
# 示意：一个自己维护的 Python 包
from nautilus_trader.config import DataClientConfig
from nautilus_trader.live.clients import DataClientFactory, MarketDataClient
from nautilus_trader.model import QuoteTick

class FutuPyDataClient(MarketDataClient):
    async def _connect(self) -> None:
        ...  # 连 OpenD，加载标的后逐个 self._handle_instrument(instrument)

    async def _subscribe_quotes(self, command) -> None:
        for instrument_id in command.instrument_ids:
            ...  # Qot_Sub；收到 3005 推送后构造 QuoteTick，调用 self._handle_data(quote)

class FutuPyDataClientFactory(DataClientFactory):
    @staticmethod
    def create(*, name, config, cache, clock):
        return FutuPyDataClient(name=name, config=config, cache=cache, clock=clock, venue=FUTU_VENUE)

builder = builder.add_data_client("FUTU", FutuPyDataClientFactory, DataClientConfig())
```

和路线 A 的区别：

- 注册时**必须给名字**，配置要是 `DataClientConfig` 或它的子类；节点把工厂包成 `PythonDataFactory`。
- 订阅和命令钩子都是 `async`，跑在节点绑定的 asyncio 事件循环上；拿到的缓存是只读的 `ClientCache`，返回的都是快照；`_handle_data`、`_handle_instrument`、`_handle_report` 等输出方法把对象**排队**交给 Rust 引擎。
- 可以直接用富途官方的 `futu-api` Python SDK 连 OpenD，省掉第 4 节的协议实现，是最快跑通的路。要注意那个 SDK 用自己的线程回调推送，回调里不要直接调 `_handle_data`，应先用 `self.loop.call_soon_threadsafe(...)` 切回节点的事件循环（开发指南写明缓存和输出能力都只能在节点所属的线程和事件循环上使用，持有 GIL 也不算）。
- 代价是协议处理和对象转换都在 Python 里，高频行情下 CPU 开销比路线 A 大；也进不了官方仓库。

### 6.3 路线 C：独立的 Rust/PyO3 包

协议和解析用 Rust 写，但编成一个**独立的** Python 扩展（自己的 `Cargo.toml` 和 `pyproject.toml`），外观仍然继承路线 B 的 Python 基类。开发指南对这条路有一个硬性限制：这个扩展只能通过已安装 wheel 里的模型类交换对象（在 Rust 里 `import nautilus_trader.model` 再构造 `QuoteTick`），不能链接第二套 Nautilus 模型类，也不能跨扩展模块传 Rust trait 对象。也就是说它和 NautilusTrader 的边界是 Python 协议，不是 Rust ABI。

三条路线怎么选：先用路线 B（加官方 SDK）把模拟盘的行情和下单跑通，验证概念映射；性能或可靠性需要时，把协议层换成 Rust（路线 C）；要进官方仓库再走路线 A，届时 `futu-opend` 可以原样复用。

## 7. 从哪里开始：五个里程碑

全程先连**模拟盘**（`TrdEnv = SIMULATE`），不用解锁交易密码。注意美股模拟盘不支持盘前盘后。

| 里程碑 | 内容 | 验收 |
| --- | --- | --- |
| M0 协议层 | 包头编解码、SHA1、InitConnect、KeepAlive；写一个 `bin` 例子打印 GetGlobalState | 连上本机 OpenD，心跳稳定几个小时不断线 |
| M1 标的 | GetStaticInfo → `Equity`；代码与 `InstrumentId` 互转 | 往返测试；港股每手股数正确 |
| M2 行情 | 先只订阅 00700 的报价，推送转成 `QuoteTick` | 官方的 `DataTester` 例子能跑通 |
| M3 交易 | 先做账户和对账（`generate_mass_status`），再做下单和撤单 | `ExecTester` 能跑通；重启后对账结果一致 |
| M4 组装 | 工厂、配置、`LiveNode` 例子；最后才是 PyO3 绑定（第 6.1 节的 ①～④） | Python 侧能用同一个配置启动 |

开发指南把适配器开发分成 0～9 个阶段：范围、协议核心、标的、行情、执行、可选能力、工厂和 PyO3、一致性测试、性能测试和 fuzz、文档。上面的里程碑大致沿着前七个阶段走，但验收方式不同：开发指南要求阶段 1～4 先用模拟的传输层（mock peer）写确定性测试，阶段 7 才跑 `DataTester`、`ExecTester` 这类连真实环境的验收测试，并明确“确定性测试通过之后才跑验收测试”。表里的验收栏是为了自己调试方便写的，进官方仓库时要按开发指南补齐各阶段的确定性测试。

## 8. 放进官方仓库，还是自己维护

| | 放进官方仓库（in-tree） | 自己维护（out-of-tree） |
| --- | --- | --- |
| 形式 | `crates/adapters/futu`，接入第 2.4 节列出的文件；Python 走第 6.1 节的路线 A | 独立的 Python 包（路线 B），或独立的 Rust/PyO3 包（路线 C） |
| 门槛 | 高：开发指南要求维护中的官方适配器满足确定性仿真测试（DST）约定，并有一致性测试和集成文档；fuzz 不是硬性门槛，但富途这种二进制帧编解码正是开发指南建议做 fuzz 的场景 | 低：按 `docs/developer_guide/python_adapters.md` 写 |
| 限制 | 跟着主仓库的节奏和规范走 | 独立的 Rust 包只能通过已安装 wheel 里的 Python 模型类交换对象，不能和 Nautilus 共享 Rust trait 对象 |

先在自己的仓库里把模拟盘跑通，等结构稳定了再考虑往上游提。

::: warning 容易踩的坑
- **把 OpenD 当成 REST 服务。** 它是长连接 + 推送，下单的回包只说明“OpenD 收到了”，订单状态要看 2208 推送或查询。
- **忘了调 `Trd_SubAccPush`。** 不调就收不到任何订单和成交推送，看起来像“下了单没反应”。
- **用 GitHub master 上的 `.proto`。** 比文档旧，生成的代码缺字段。
- **每手股数写死。** 港股每只不同。
- **超时当拒单。** 超时和断线是“结果未知”，要等对账查清楚。
- **在 trait 方法里等网络。** `subscribe_*`、`submit_order` 在核心线程上同步执行，里面阻塞会卡住整个节点；网络活交给 `TaskGroup`。
- **在 SDK 回调线程里直接产出数据。** 路线 B 用官方 Python SDK 时，推送回调在 SDK 自己的线程上，要先切回节点的事件循环。
- **把订阅额度当成无限。** 额度用完后订阅会失败，退订还要等 1 分钟才生效。
:::

## 待核实

以下几点文档没写清楚，动手前要在 OpenD 上实测：漏发 KeepAlive 多久会被断开；包序号是否必须严格递增（文档说“要求递增”，Python SDK 却用随机的唯一 ID）；重复的 `PacketID` 被拒时的具体行为；碎股下单规则；“最多 128 条连接”只出现在官方示例的注释里。

## 参考资料

- NautilusTrader：[仓库（develop 分支）](https://github.com/nautechsystems/nautilus_trader) · [适配器开发指南](https://github.com/nautechsystems/nautilus_trader/blob/develop/docs/developer_guide/adapters.md) · [树外适配器指南](https://github.com/nautechsystems/nautilus_trader/blob/develop/docs/developer_guide/python_adapters.md) · [IB 适配器源码](https://github.com/nautechsystems/nautilus_trader/tree/develop/crates/adapters/interactive_brokers) · [IB 的 PyO3 模块](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/adapters/interactive_brokers/src/python/mod.rs) · [工厂注册表](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/system/src/python/registry.rs) · [Python 版 LiveNode 构建器](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/live/src/python/node.rs) · [Python 适配器模板](https://github.com/nautechsystems/nautilus_trader/tree/develop/examples/live/_template)
- 配图由 `scripts/generate-nautilus-trader-figures.py` 生成。
- 富途 OpenAPI：[底层协议介绍](https://openapi.futunn.com/futu-api-doc/ftapi/protocol.html) · [OpenD 概述](https://openapi.futunn.com/futu-api-doc/opend/opend-intro.html) · [OpenD 命令行参数](https://openapi.futunn.com/futu-api-doc/opend/opend-cmd.html) · [权限与额度](https://openapi.futunn.com/futu-api-doc/intro/authority.html) · [订阅规则](https://openapi.futunn.com/futu-api-doc/quote/sub.html) · [交易接口总览](https://openapi.futunn.com/futu-api-doc/trade/trade.html)
- [py-futu-api](https://github.com/FutunnOpen/py-futu-api)：`futu/common/constant.py`（协议号）、`utils.py`（包头）、`conn_mng.py`（加密）、`pb/*.proto`

适配器只是 Rust 核心的一个入口。下一章把读源码、写适配器时反复遇到的其他主题集中讲一遍：定点数、时钟、订单状态机、缓存、并发模型、风控、对账等。[第 3 章：其他需要重点理解的主题](./core-topics.md)。
