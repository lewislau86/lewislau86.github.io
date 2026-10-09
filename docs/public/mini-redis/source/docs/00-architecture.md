# 00 整体架构：代码职责、连接通信与后续优化

[目录](README.md) · [下一章：跑通第一条请求](01-first-run.md)

先把 mini-redis 想象成一个可以通过网络访问的内存字典：客户端发出“保存 course=rust”，服务器把数据留在自己的内存中；之后任何连接到同一个服务实例的客户端，都可以请求读取它。除了读写，这个项目还展示了定时删除、消息订阅以及停止服务时的资源回收。

本章先建立整张地图，不要求你已经读懂 Rust。读完应该能回答三个问题：某项行为应该去哪个文件找，数据怎样从客户端走到数据库，又有哪些地方值得以后改进。后面的章节再逐层展开语法与实现。

本文以本仓库 `mini-redis 0.4.1`、commit `3d93b42bc363220f85af4fc9e1bebd35b588a4a3` 为分析基线。图中的箭头表示数据流、调用或资源关系，并非实测线程轨迹；优化部分是建议，尚未实施，也没有对应的性能收益测量。

## 先分清程序、库、连接和数据

仓库包含两个主要可执行程序，以及一套供它们调用的库：

| 对象 | 是什么 | 主要责任 |
| --- | --- | --- |
| `mini-redis-server` | 长期运行的服务器进程 | 监听连接，处理请求，保存共享数据 |
| `mini-redis-cli` | 用户在终端运行的客户端进程 | 解析命令行，连接服务，发命令并打印结果 |
| `mini_redis` | Rust 库 | 提供 Client、Connection、Frame、server 等实现 |
| `Client` | 客户端进程中的 Rust 对象 | 管理一个连接，编码请求、读取响应 |
| `Handler` | 服务端一个已接入连接的处理对象 | 循环读命令、调用数据库、写响应 |
| `Db` | 服务端共享数据库的句柄 | 访问内存状态，多个句柄指向同一份数据 |

客户端与服务器可以在同一台机器上，但仍有各自的进程内存。客户端的 Client 不会直接访问服务器的 HashMap，它必须发送字节。相反，同一服务器内的多个 Handler 访问 Db 是普通函数调用和内存访问，不会再走一次 TCP。

第 01 章手动启动的服务与客户端是两个进程；配套 roundtrip 实验则在同一进程里启动服务任务和客户端，即使这样，它们之间依然建立真正的本地 TCP 连接。

## 一张图看完整体

```text
客户端进程                                  服务端进程
┌────────────────────────┐                 ┌─────────────────────────────┐
│ CLI / 自己写的 Rust 程序 │                 │ server binary               │
│           ↓            │                 │  └─ runtime、监听、关闭信号 │
│         Client         │                 │           ↓                 │
│           ↓            │                 │ Listener：配额 → accept     │
│      命令 → Frame      │                 │           ↓                 │
│           ↓            │                 │ 每连接一个 Handler 任务     │
│       Connection       │                 │  Connection → Frame        │
│           ↕            │                 │       → Command → apply    │
│        TcpStream       │ ←─ TCP 字节流 ─→ │              ↕              │
└────────────────────────┘                 │       Db → 共享 State       │
                                           │       ↑                     │
                                           │ 后台任务：清理到期键         │
                                           └─────────────────────────────┘
```

TCP 是传输通道，RESP 是约定这些字节含义的格式，Frame 是解析后的 Rust 数据结构，Command 是有业务意义的指令，Db 是执行数据操作的地方。它们分别解决不同问题。

例如：收到 `$4\r\nrust\r\n` 时，帧解析器知道这是四个字节的 Bulk；但只有命令解析器结合它在数组中的位置，才知道它是 SET 的值。数据库则不需要知道这个值当初分了几次网络读取才到达。

Tokio runtime 为等待网络、计时器与任务调度提供运行环境。它不是业务数据库，也不替你决定一条命令的含义。任务可以在 runtime 的工作线程上被调度；图中的模块不各自占用一个线程。

## 哪个文件负责什么

初读时按“入口 → 请求处理 → 状态”找代码，先不要从每个辅助函数开始。

| 文件 | 先看这些对象/函数 | 它负责什么 |
| --- | --- | --- |
| [Cargo.toml](../Cargo.toml) | package、bin、dependencies、features | 描述编译目标与依赖，不参与一次请求的业务执行 |
| [src/lib.rs](../src/lib.rs) | mod、pub use、Result | 建立模块边界，对外提供统一库入口 |
| [src/bin/server.rs](../src/bin/server.rs) | main | 解析端口、设置日志、创建监听，再调用 server::run |
| [src/bin/cli.rs](../src/bin/cli.rs) | main、CLI Command | 将终端参数转换为客户端 API 调用；CLI 枚举与服务端命令枚举是不同类型 |
| [src/server.rs](../src/server.rs) | Listener、Handler、run | 接入连接、限制数量、spawn 任务、驱动请求循环、协调停机 |
| [src/connection.rs](../src/connection.rs) | read_frame、parse_frame、write_frame | 管理 TCP 读写缓冲，将字节流转换为一帧一帧的数据 |
| [src/frame.rs](../src/frame.rs) | Frame、check、parse | 表示和读取协议类型，不解释 GET/SET 的业务含义 |
| [src/parse.rs](../src/parse.rs) | Parse、next_string、next_bytes、finish | 依次取出帧数组中的参数，检查参数类型及是否用完 |
| [src/cmd/mod.rs](../src/cmd/mod.rs) | Command::from_frame、apply | 根据命令名选择具体命令，再统一分发执行 |
| [src/db.rs](../src/db.rs) | Db、Shared、State、purge_expired_tasks | 维护键值、过期索引、频道和同步访问 |
| [src/shutdown.rs](../src/shutdown.rs) | Shutdown::recv | 将关闭通道的通知转换为当前连接的停止状态 |
| [src/clients/client.rs](../src/clients/client.rs) | Client、Subscriber | 连接服务并完成往返请求，或进入订阅接收模式 |
| [src/clients/buffered_client.rs](../src/clients/buffered_client.rs) | BufferedClient、run | 用队列让多个调用者共享一个后台 Client |
| [src/clients/blocking_client.rs](../src/clients/blocking_client.rs) | BlockingClient | 为同步代码封装 runtime.block_on 调用 |
| [tests](../tests) / [docs/labs](labs/README.md) | 测试 / 教学实验 | 观察并验证行为，不是服务器处理请求必须经过的模块 |

具体命令再看下面几个文件。大部分命令同时提供“客户端构造请求”和“服务端解析执行”所需的方法，但每个进程使用的是自己的对象。

| 命令代码 | 对数据或连接做什么 |
| --- | --- |
| [get.rs](../src/cmd/get.rs) | 读取键，返回 Bulk 或 Null |
| [set.rs](../src/cmd/set.rs) | 保存值，可附带 EX/PX 过期时间；返回 OK |
| [ping.rs](../src/cmd/ping.rs) | 返回 PONG 或传入的消息，不依赖 Db |
| [publish.rs](../src/cmd/publish.rs) | 向频道发送消息，返回当次发送对应的接收者数量 |
| [subscribe.rs](../src/cmd/subscribe.rs) | 维护订阅集合、推送消息、处理 SUBSCRIBE/UNSUBSCRIBE |
| [unknown.rs](../src/cmd/unknown.rs) | 为未知命令构造协议错误响应 |

## 连接究竟怎样建立

服务器入口先执行 `TcpListener::bind`。当前 binary 绑定 `127.0.0.1`，默认端口 6379；笔记通过 `--port 16379` 使用单独的实验端口。只修改端口不会让这个 binary 自动监听其他机器可访问的地址。

客户端调用 `Client::connect(address)`，内部用 `TcpStream::connect` 请求建立 TCP 连接。操作系统负责握手与字节传输，应用代码通过 await 等待结果。服务器的 Listener 取得一个连接许可，再调用 accept 得到该客户端对应的 socket。

```text
服务器：bind 监听地址 → 获取 permit → accept → socket → Handler → spawn
客户端：指定服务器地址 → connect → socket → Connection → Client
                                 两端 socket 共同构成一条 TCP 连接
```

本地每个 `server::run` 创建一个共享数据库；每接入一个连接，便将 Db 的共享句柄交给 Handler。连接的读缓冲区是各自独立的，数据库内容是共享的。

一个 Client 可以在同一连接上连续执行多个命令；每次运行普通 CLI 命令则会新建客户端进程及连接，完成后退出。服务端读到完整消息边界上的 EOF，会结束对应 Handler，但不会因此清空其他连接使用的数据库。

源码限制同时处理的连接数为 250。许可在 accept 之前获取，满额后暂停继续接入；这不保证第 251 次 TCP connect 立即报错，因为操作系统还存在监听队列。连接数量限制也没有限制单个值、单条帧或数据库总内存。

## 一条 SET 如何走到内存，再回到客户端

仍使用本书贯穿始终的 `SET course rust`。网络上发的不是 Rust 对象，而是下面这段 RESP 字节：

```text
*3\r\n$3\r\nset\r\n$6\r\ncourse\r\n$4\r\nrust\r\n
```

其中 `*3` 表示三个数组元素，`$6` 表示后面的 course 有六个字节。这里的 `\r\n` 是控制字节的可见表示。

| 顺序 | 执行位置 | 数据怎样变化 |
| --- | --- | --- |
| 1 | Client::set | 调用参数构造成 Set，未指定 TTL |
| 2 | Set::into_frame | Set 变成包含命令名、键和值的 Array 帧 |
| 3 | 客户端 Connection::write_frame | Frame 编成字节，写入并 flush |
| 4 | 服务端 Connection::read_frame | 追加接收缓冲；不完整则继续读，完整则返回 Frame |
| 5 | Command::from_frame / Set::parse_frames | 从数组取参数，得到 Set 指令 |
| 6 | Set::apply → Db::set | 持锁更新 entries 及必要的过期索引，然后解锁 |
| 7 | Set::apply | 构造 Simple("OK")，通过原连接写回 `+OK\r\n` |
| 8 | Client::set_cmd | 解析响应，确认 OK 后返回成功 |

GET 复用同样的连接与协议层：`Db::get` 查到值就返回 Bytes，命令层将其编码为 `$4\r\nrust\r\n`；没有值则写 `$-1\r\n`，客户端得到 None。

TCP 不提供应用消息边界。Connection 可能先读到半个 SET，也可能一次读到 SET 和 GET；它会保留未处理字节，一次向上交付一帧。当前 Handler 顺序执行本连接的命令，所以本地普通客户端通过请求/响应顺序配对，不依赖额外请求 ID。

SET 返回成功表示服务器执行了这次内存修改，并成功将应用层响应传回；本地没有持久化路径，所以它不代表写入已耐久落盘。如果连接在写入后、响应收到前断开，客户端也不能仅凭错误推断“SET 一定没发生”，重试策略需要考虑这一点。

## 进程内部怎样共享与通信

不要把下面这些通道与 TCP 频道混为一谈：它们都是本进程内的协作方式，真正传给远端客户端仍须经 Connection 编码。

| 协作双方 | 使用机制 | 在哪里使用 |
| --- | --- | --- |
| 多个 Handler 与同一数据库 | `Arc<Shared>` + `Mutex<State>` | Arc 管理共同持有，Mutex 保护内存修改 |
| 写入任务与过期清理任务 | 共享过期索引 + Notify | 新增更早 deadline 时，唤醒清理任务重新检查状态 |
| 发布者与各订阅连接 | 每频道一个 broadcast | 发布消息交给活跃接收者，再由订阅 Handler 推送 |
| 多个 BufferedClient 调用者与后台 Client | 有界 mpsc + 每次请求的 oneshot | 请求排队，结果送回对应调用者 |
| 主服务与连接任务 | broadcast 关闭通知 + mpsc 发送端生命周期 | 通知退出，等待所有 Handler 释放完成句柄 |

共享数据实际放在这里：

```text
Handler A 的 Db ─┐
Handler B 的 Db ─┼→ 同一个 Shared
后台清理任务 ───┘      ├─ Mutex<State>
                       │   ├─ entries：key → Bytes 与可选到期时刻
                       │   ├─ expirations：按时间排序的 (到期时刻, key)
                       │   ├─ pub_sub：频道名 → broadcast Sender
                       │   └─ shutdown：后台任务停止标记
                       └─ Notify：提醒后台任务重新检查
```

普通 get/set 在短同步临界区内完成内存操作，网络 await 在解锁之后。这里的锁不会让两次独立命令自动成为事务：两个客户端各自 GET、计算、SET，仍可能在命令之间交错。

## 发布订阅是另一条通信路径

普通连接等待“我刚发出的命令的响应”；订阅连接还必须接收别人发布的消息，因此服务端的 `Subscribe::apply` 会接管该连接，进入专门的事件循环。

```text
订阅客户端 ── SUBSCRIBE news ──→ 订阅 Handler
订阅客户端 ←─ 订阅确认 ───────── 订阅 Handler 持有 Receiver

发布客户端 ── PUBLISH news hello → 发布 Handler → Db::publish
                                                │
                              进程内 broadcast ──┘
                                      ↓
订阅客户端 ←─ TCP 推送消息帧 ──── 订阅 Handler
发布客户端 ←─ TCP 返回接收者数 ── 发布 Handler
```

发布响应与订阅消息沿不同连接返回。接收者数量不是业务消费确认，也没有消息持久化或重放。本地通道容量为 1024，落后接收者产生 Lagged 时，当前适配逻辑跳过该错误继续接收，可能丢掉旧消息。

当前订阅模式仅处理 SUBSCRIBE/UNSUBSCRIBE，即使订阅数归零也不会自动回到普通请求循环。客户端也用 Subscriber 类型表达这种状态；做普通 GET/SET 应使用另一个连接。细节见[第 08 章](08-pubsub.md)。

## 没有请求的时候，服务还在做什么

过期清理任务按最早的到期时间休眠；插入更早到期键时，Notify 使它重新计算。它不必靠客户端不断发 GET 才运行。但当前 GET 不主动判断 expires_at，逻辑到期与后台实际删掉之间可能存在调度窗口，详见[第 07 章](07-expiration.md)。

停机时，主流程退出接入循环，通过关闭 broadcast 发送端让 Handler 得知停止；再等待它们各自持有的完成通道发送端全部释放。DbDropGuard 另外设置清理任务的停止标记并通知它；清理任务没有在同一套完成等待中被显式 join。

普通命令已开始的响应写入不在读帧 select 中被中断，本地也没有统一停机时限。完整的“通知退出”与“确认退出”区别见[第 10 章](10-shutdown-and-tests.md)。

## 后期先完善哪些行为

下面是基于当前实现的改进路线。先把功能承诺与失败方式定义清楚，再做性能取舍；“源码中存在一个复制或一把锁”本身不能证明它就是瓶颈。

### 第一阶段：让边界行为更明确

| 方向 | 当前源码依据 | 可做的修改 | 怎样确认有效 |
| --- | --- | --- | --- |
| 过期可见性 | `Db::get` 只查 entries，没有到期判断 | 在持锁读取时判断到期，并一致更新主表与索引 | 未到期、到期边界、覆盖为新 TTL、覆盖为永久值 |
| 帧完整校验与资源上限 | `Frame::check/parse` 的 Bulk 路径跳过末尾两字节；Connection 初始 4 KiB 不是上限 | 校验 CRLF、数字和长度运算，设帧/数组元素/嵌套深度上限；明确错误返回 | 半帧、正文内 CRLF、错误尾部、超长输入、超深数组，不应 panic 或无限增长 |
| 订阅字节保真 | `Subscriber::next_message` 经 `content.to_string()` 再生成 Bytes | 匹配内容帧类型，直接取得 Bulk 字节，避免展示文本转换 | 发布非 UTF-8、零字节、CRLF 后逐字节比较 |
| 错误处理一致性 | Unknown 写错误帧；已知命令参数错误经 Handler 返回 Err 并关闭连接 | 区分可回复的命令错误与失去同步的协议错误，规定连接是否保留 | 错误命令之后紧跟合法命令，核对响应与连接状态 |
| 有界停机 | 部分写入可能长时间等待，清理任务无显式 join | 保存任务完成句柄，设计总体 deadline 与超时后的退出策略 | 空闲连接、订阅连接、慢读者和清理任务均有可观察完成条件 |

“严格校验”还应覆盖 `Frame::parse` 直接调用时的非法前缀与写入器的嵌套数组边界。选择返回错误还是支持更多格式，需要先定义库接口；不能只消掉一次 panic，就宣称完整 RESP 兼容。

### 第二阶段：为容量与慢调用者设置规则

本地连接许可为 250，BufferedClient 队列容量为 32，但 entries 的总大小、单值大小以及历史频道名数量没有统一预算。`pub_sub` 插入的频道 Sender 没有对应的空闲清理流程。大量不同频道被订阅过之后，单纯释放 Receiver 不等于移除频道表项。

可以考虑把连接数、请求大小、键值总量、读写等待上限和频道生命周期变成明确配置。每种限制都要写清“到上限时等待、拒绝还是清理”：例如清理无订阅者频道时，要与新订阅/发布协调；给慢订阅者断开连接，会改变用户能观察到的行为，不能当作无影响的内部优化。

验收时看实际资源是否受控：进程内存是否趋于稳定，空闲频道能否回收，队列满时调用者是否按预期等待或失败，慢连接是否影响其他连接。连接超时后的写命令还可能已经执行，应将这种结果不确定性传递给调用者。

### 第三阶段：测出瓶颈，再优化吞吐与延迟

| 候选方向 | 为什么值得测 | 改动时要保留的约束 |
| --- | --- | --- |
| 缩短锁占用 / 按键分片 | 所有状态共享一把 Mutex；高并发时可能等待锁 | 键值与过期索引必须一致；跨分片操作更复杂，热点单键不会自动均匀分散 |
| 分批清理过期键 | 一次清理循环在锁内处理当时已到期的所有键；集中到期可能延长持锁 | 每批处理有预算并继续调度；不能长期饿死清理，也不能错删被覆盖的新值 |
| 帧解析与内存分配 | 当前先 check 再 parse，Bulk 用 copy_from_slice | 共享切片可能让一个小值长期保留整个大缓冲；节省复制与内存驻留要一起测 |
| 批量请求 / 合并写入 | Client 一次往返一个请求，write_frame 每帧 flush | 保持响应顺序，限制批量大小和在途请求数，处理部分失败及慢消费者 |
| 多连接并发 | BufferedClient 的克隆共享一条串行连接 | 若改为连接池，必须规定连接归属与生命周期；订阅连接不能随意用于普通请求 |

短临界区使用同步 Mutex 是当前设计的合理起点。若测到争用，应比较缩短临界区、分片或由单独任务管理资源，而不是只把锁换成 Tokio Mutex。可参考 [Tokio 共享状态教程](https://tokio.rs/tokio/tutorial/shared-state)。

批量发送请求可以减少逐次网络往返等待，但会增加在途数据和响应缓冲需求。概念可参考 [Redis pipelining 文档](https://redis.io/docs/latest/develop/using-commands/pipelining/)；它不代表本地 Client 已经提供这项 API。只去掉 flush 可能让客户端等不到响应，批量机制必须连同刷新时机和客户端读取一起设计。

建议先用固定工作负载建立基线：相同工具链与构建模式、相同机器、固定值大小与读写比例，再分别改变并发连接数、热点比例和集中 TTL 数量。记录吞吐、P50/P95/P99 响应时间、错误率、CPU、内存及锁等待/持有时间；P99 指 99% 请求延迟不超过的值。一次只改一个方向，用相同数据再测。当前笔记中的实验验证功能，尚未给出这些基准数据。

### 第四阶段：按需求扩展数据库能力

持久化、复制、更多数据类型和集群会改变系统的责任与故障模型，属于更大的功能设计。先回答“成功响应是否要求耐久落盘”“重启允许丢多少数据”“是否真的需要跨机器扩展”，再规划模块和协议，不能只把它们排成几个性能开关。

这些概念在[第 11 章](11-real-redis.md)展开。若目的是学 Rust，建议先完成[第 12 章](12-exercises-and-index.md)的单键 DEL、过期或字节保真练习，再承担跨进程一致性的复杂度。

## 带着地图继续阅读

进入核心章节后，把本章地图缩小到具体调用处。第 03—10 章都把“调用者 → 当前函数 → 被调用者/接收任务 → 返回影响”接起来，并穿插相应源码。特别留意三个不同的结果：返回值告诉调用者什么，共享状态已经改变了什么，资源释放又会唤醒谁。

例如 `Db::set` 的返回值只有 `()`，但它已经更新两张表并可能唤醒后台任务；`Set::apply` 随后写响应失败也不撤销这些效果。只看函数返回类型无法理解这条请求，必须把[第 03 章](03-request-path.md)的命令执行、[第 06 章](06-shared-storage.md)的状态更新和[第 07 章](07-expiration.md)的后台唤醒连起来。

第一次先记住“Client → TCP → Connection → Command → Db → 响应”，到[第 01 章](01-first-run.md)实际运行它。之后遇到问题就按边界定位：连不上看入口与地址，半帧看 Connection/Frame，参数错误看 Parse/Command，数据与 TTL 看 Db，订阅与停机再看各自的事件循环。

最后检查一下：客户端 A 写入的数据，客户端 B 为什么能读到？是不是因为两个 Client 共享同一个 Arc？

<details>
<summary>参考答案</summary>

两个客户端分别通过 TCP 把请求发给同一个服务实例。共享 Arc 的是服务器内部两个 Handler 持有的 Db 句柄；客户端进程之间没有用这个 Arc 共享内存。服务器共享数据，连接分别传输请求和响应。

</details>
