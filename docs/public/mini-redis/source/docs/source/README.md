# 按源码文件阅读：一份源码，一篇分析

[返回总目录](../README.md) · [整体架构](../00-architecture.md) · [SET/GET 跨文件串读](../03-request-path.md)

这里为当前仓库 `src/` 的 20 个 Rust 文件，以及 `examples/`、`tests/` 的各 4 个 Rust 文件建立一一对应的文章，共 28 篇。文件路径原样映射，例如 `src/cmd/set.rs` 对应 `docs/source/src/cmd/set.md`。每篇都有原文件链接、交互关系、关键实现、Rust 解释、状态及错误影响，并链接上下游文件。

一篇对应一个文件，不把每个函数拆成孤立页面：文件内的方法按实际协作关系连读。跨文件章节解释“一次行为如何发生”，这里解释“这个文件在行为中承担什么，以及其他调用场景如何使用它”。新增教学实验 `docs/labs/` 的程序另由 [实验说明](../labs/README.md) 覆盖，不混入原项目源码清单。

遇到类型或语法不熟悉时，使用 [Rust 源码阅读说明](../rust-reading-guide.md)。每篇文章补有“这里的 Rust 写法”，从当前实现解释语法，不要求先记住所有高级特性。

## 如果从 SET/GET 开始

先读 [第 03 章的逐站对应表](../03-request-path.md#这一章对应哪些源码和独立文章)，再按以下顺序进入文件文章：

1. [hello_world.rs](examples/hello_world.md) 看业务入口，[client.rs](src/clients/client.md) 看请求发起和结果解释。
2. [set.rs](src/cmd/set.md)、[get.rs](src/cmd/get.md) 看命令如何编码，以及服务端如何执行。
3. [connection.rs](src/connection.md)、[frame.rs](src/frame.md) 看两端共同使用的网络与帧边界。
4. [server.rs](src/server.md) 看谁循环读取请求；[cmd/mod.rs](src/cmd/mod.md)、[parse.rs](src/parse.md) 看如何选择命令并消费参数。
5. [db.rs](src/db.md) 看值保存在哪里、连接如何共享、TTL 如何维护。
6. [tests/client.rs](tests/client.md)、[tests/server.rs](tests/server.md) 看业务返回值和线上字节分别怎样被断言。

客户端和服务端不是同一个调用栈。Client 构造 Set 后写成字节，服务端才解析出自己的 Set；同一个源码文件可在两个进程中承担不同角色。每篇开头的关系图用来把这种边界保留下来。

## 入口与模块边界

| 对应源码 | 独立文章 |
| --- | --- |
| [src/lib.rs](../../src/lib.rs) | [库的入口与公开边界](src/lib.md) |
| [src/bin/server.rs](../../src/bin/server.rs) | [把进程配置接到服务生命周期](src/bin/server.md) |
| [src/bin/cli.rs](../../src/bin/cli.rs) | [将终端参数翻译成客户端调用](src/bin/cli.md) |
| [src/clients/mod.rs](../../src/clients/mod.rs) | [三种客户端的统一出口](src/clients/mod.md) |

## 连接、协议与服务任务

| 对应源码 | 独立文章 |
| --- | --- |
| [src/server.rs](../../src/server.rs) | [接入任务、连接任务与退出协调](src/server.md) |
| [src/connection.rs](../../src/connection.rs) | [TCP 字节流与完整 Frame 之间的边界](src/connection.md) |
| [src/frame.rs](../../src/frame.rs) | [协议类型、游标解析与展示](src/frame.md) |
| [src/parse.rs](../../src/parse.rs) | [从帧数组按顺序取出命令参数](src/parse.md) |
| [src/shutdown.rs](../../src/shutdown.rs) | [让一个连接记住停止通知](src/shutdown.md) |

## 命令与共享存储

| 对应源码 | 独立文章 |
| --- | --- |
| [src/cmd/mod.rs](../../src/cmd/mod.rs) | [将协议帧分派到具体命令](src/cmd/mod.md) |
| [src/cmd/set.rs](../../src/cmd/set.rs) | [解析可选 TTL，先写入再确认](src/cmd/set.md) |
| [src/cmd/get.rs](../../src/cmd/get.rs) | [从 Db 读取并生成响应](src/cmd/get.md) |
| [src/db.rs](../../src/db.rs) | [共享数据、过期索引与频道的唯一持有处](src/db.md) |
| [src/cmd/ping.rs](../../src/cmd/ping.rs) | [用最小命令理解可选参数](src/cmd/ping.md) |
| [src/cmd/publish.rs](../../src/cmd/publish.rs) | [将一次发布翻译为接收者数量](src/cmd/publish.md) |
| [src/cmd/subscribe.rs](../../src/cmd/subscribe.rs) | [接管连接并复用多个频道流](src/cmd/subscribe.md) |
| [src/cmd/unknown.rs](../../src/cmd/unknown.rs) | [把未知操作写成协议错误](src/cmd/unknown.md) |

## 客户端形态

| 对应源码 | 独立文章 |
| --- | --- |
| [src/clients/client.rs](../../src/clients/client.rs) | [一条连接上的请求与响应](src/clients/client.md) |
| [src/clients/buffered_client.rs](../../src/clients/buffered_client.rs) | [用消息队列串行共享 Client](src/clients/buffered_client.md) |
| [src/clients/blocking_client.rs](../../src/clients/blocking_client.rs) | [把异步 Client 接到同步程序](src/clients/blocking_client.md) |

## 应用示例

| 对应源码 | 独立文章 |
| --- | --- |
| [examples/hello_world.rs](../../examples/hello_world.rs) | [从业务入口走进 SET/GET](examples/hello_world.md) |
| [examples/pub.rs](../../examples/pub.rs) | [一次发布调用的应用入口](examples/pub.md) |
| [examples/sub.rs](../../examples/sub.rs) | [建立订阅后接收一条消息](examples/sub.md) |
| [examples/chat.rs](../../examples/chat.rs) | [尚未实现的聊天入口](examples/chat.md) |

## 测试如何提供证据

| 对应源码 | 独立文章 |
| --- | --- |
| [tests/client.rs](../../tests/client.rs) | [从公开 API 验证端到端返回值](tests/client.md) |
| [tests/server.rs](../../tests/server.rs) | [用原始 TCP 检查线上协议](tests/server.md) |
| [tests/buffered_client.rs](../../tests/buffered_client.rs) | [验证队列包装后的基本读写](tests/buffered_client.md) |
| [tests/frame_validation.rs](../../tests/frame_validation.rs) | [用一个反例区分非法帧与半帧](tests/frame_validation.md) |

## 如何判断自己读懂了一个文件

回到源码，指出进入该文件的调用点、传入资源属于谁、哪一步改变共享状态、返回后谁继续执行，以及 `?` 或 Drop 会结束哪一层。然后沿文章末尾的链接进入调用者或被调用者，验证这一关系，而不是只记住方法名。
