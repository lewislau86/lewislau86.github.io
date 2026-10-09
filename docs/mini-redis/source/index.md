---
editLink: false
---

# 按源码文件阅读：一份源码，一篇分析

[返回总目录](/mini-redis/index.md) · [整体架构](/mini-redis/00-architecture.md) · [SET/GET 跨文件串读](/mini-redis/03-request-path.md)

这里为当前仓库 `src/` 的 20 个 Rust 文件，以及 `examples/`、`tests/` 的各 4 个 Rust 文件建立一一对应的文章，共 28 篇。文件路径原样映射，例如 `src/cmd/set.rs` 对应 `docs/source/src/cmd/set.md`。每篇都有原文件链接、交互关系、关键实现、Rust 解释、状态及错误影响，并链接上下游文件。

一篇对应一个文件，不把每个函数拆成孤立页面：文件内的方法按实际协作关系连读。跨文件章节解释“一次行为如何发生”，这里解释“这个文件在行为中承担什么，以及其他调用场景如何使用它”。新增教学实验 `docs/labs/` 的程序另由 [实验说明](/mini-redis/labs/index.md) 覆盖，不混入原项目源码清单。

遇到类型或语法不熟悉时，使用 [Rust 源码阅读说明](/mini-redis/rust-reading-guide.md)。每篇文章补有“这里的 Rust 写法”，从当前实现解释语法，不要求先记住所有高级特性。

## 如果从 SET/GET 开始

先读 [第 03 章的逐站对应表](/mini-redis/03-request-path.md#这一章对应哪些源码和独立文章)，再按以下顺序进入文件文章：

1. [hello_world.rs](/mini-redis/source/examples/hello_world.md) 看业务入口，[client.rs](/mini-redis/source/src/clients/client.md) 看请求发起和结果解释。
2. [set.rs](/mini-redis/source/src/cmd/set.md)、[get.rs](/mini-redis/source/src/cmd/get.md) 看命令如何编码，以及服务端如何执行。
3. [connection.rs](/mini-redis/source/src/connection.md)、[frame.rs](/mini-redis/source/src/frame.md) 看两端共同使用的网络与帧边界。
4. [server.rs](/mini-redis/source/src/server.md) 看谁循环读取请求；[cmd/mod.rs](/mini-redis/source/src/cmd/mod.md)、[parse.rs](/mini-redis/source/src/parse.md) 看如何选择命令并消费参数。
5. [db.rs](/mini-redis/source/src/db.md) 看值保存在哪里、连接如何共享、TTL 如何维护。
6. [tests/client.rs](/mini-redis/source/tests/client.md)、[tests/server.rs](/mini-redis/source/tests/server.md) 看业务返回值和线上字节分别怎样被断言。

客户端和服务端不是同一个调用栈。Client 构造 Set 后写成字节，服务端才解析出自己的 Set；同一个源码文件可在两个进程中承担不同角色。每篇开头的关系图用来把这种边界保留下来。

## 入口与模块边界

| 对应源码 | 独立文章 |
| --- | --- |
| [src/lib.rs](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/mini-redis/source/src/lib.rs) | [库的入口与公开边界](/mini-redis/source/src/lib.md) |
| [src/bin/server.rs](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/mini-redis/source/src/bin/server.rs) | [把进程配置接到服务生命周期](/mini-redis/source/src/bin/server.md) |
| [src/bin/cli.rs](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/mini-redis/source/src/bin/cli.rs) | [将终端参数翻译成客户端调用](/mini-redis/source/src/bin/cli.md) |
| [src/clients/mod.rs](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/mini-redis/source/src/clients/mod.rs) | [三种客户端的统一出口](/mini-redis/source/src/clients/mod.md) |

## 连接、协议与服务任务

| 对应源码 | 独立文章 |
| --- | --- |
| [src/server.rs](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/mini-redis/source/src/server.rs) | [接入任务、连接任务与退出协调](/mini-redis/source/src/server.md) |
| [src/connection.rs](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/mini-redis/source/src/connection.rs) | [TCP 字节流与完整 Frame 之间的边界](/mini-redis/source/src/connection.md) |
| [src/frame.rs](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/mini-redis/source/src/frame.rs) | [协议类型、游标解析与展示](/mini-redis/source/src/frame.md) |
| [src/parse.rs](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/mini-redis/source/src/parse.rs) | [从帧数组按顺序取出命令参数](/mini-redis/source/src/parse.md) |
| [src/shutdown.rs](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/mini-redis/source/src/shutdown.rs) | [让一个连接记住停止通知](/mini-redis/source/src/shutdown.md) |

## 命令与共享存储

| 对应源码 | 独立文章 |
| --- | --- |
| [src/cmd/mod.rs](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/mini-redis/source/src/cmd/mod.rs) | [将协议帧分派到具体命令](/mini-redis/source/src/cmd/mod.md) |
| [src/cmd/set.rs](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/mini-redis/source/src/cmd/set.rs) | [解析可选 TTL，先写入再确认](/mini-redis/source/src/cmd/set.md) |
| [src/cmd/get.rs](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/mini-redis/source/src/cmd/get.rs) | [从 Db 读取并生成响应](/mini-redis/source/src/cmd/get.md) |
| [src/db.rs](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/mini-redis/source/src/db.rs) | [共享数据、过期索引与频道的唯一持有处](/mini-redis/source/src/db.md) |
| [src/cmd/ping.rs](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/mini-redis/source/src/cmd/ping.rs) | [用最小命令理解可选参数](/mini-redis/source/src/cmd/ping.md) |
| [src/cmd/publish.rs](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/mini-redis/source/src/cmd/publish.rs) | [将一次发布翻译为接收者数量](/mini-redis/source/src/cmd/publish.md) |
| [src/cmd/subscribe.rs](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/mini-redis/source/src/cmd/subscribe.rs) | [接管连接并复用多个频道流](/mini-redis/source/src/cmd/subscribe.md) |
| [src/cmd/unknown.rs](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/mini-redis/source/src/cmd/unknown.rs) | [把未知操作写成协议错误](/mini-redis/source/src/cmd/unknown.md) |

## 客户端形态

| 对应源码 | 独立文章 |
| --- | --- |
| [src/clients/client.rs](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/mini-redis/source/src/clients/client.rs) | [一条连接上的请求与响应](/mini-redis/source/src/clients/client.md) |
| [src/clients/buffered_client.rs](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/mini-redis/source/src/clients/buffered_client.rs) | [用消息队列串行共享 Client](/mini-redis/source/src/clients/buffered_client.md) |
| [src/clients/blocking_client.rs](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/mini-redis/source/src/clients/blocking_client.rs) | [把异步 Client 接到同步程序](/mini-redis/source/src/clients/blocking_client.md) |

## 应用示例

| 对应源码 | 独立文章 |
| --- | --- |
| [examples/hello_world.rs](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/mini-redis/source/examples/hello_world.rs) | [从业务入口走进 SET/GET](/mini-redis/source/examples/hello_world.md) |
| [examples/pub.rs](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/mini-redis/source/examples/pub.rs) | [一次发布调用的应用入口](/mini-redis/source/examples/pub.md) |
| [examples/sub.rs](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/mini-redis/source/examples/sub.rs) | [建立订阅后接收一条消息](/mini-redis/source/examples/sub.md) |
| [examples/chat.rs](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/mini-redis/source/examples/chat.rs) | [尚未实现的聊天入口](/mini-redis/source/examples/chat.md) |

## 测试如何提供证据

| 对应源码 | 独立文章 |
| --- | --- |
| [tests/client.rs](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/mini-redis/source/tests/client.rs) | [从公开 API 验证端到端返回值](/mini-redis/source/tests/client.md) |
| [tests/server.rs](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/mini-redis/source/tests/server.rs) | [用原始 TCP 检查线上协议](/mini-redis/source/tests/server.md) |
| [tests/buffered_client.rs](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/mini-redis/source/tests/buffered_client.rs) | [验证队列包装后的基本读写](/mini-redis/source/tests/buffered_client.md) |
| [tests/frame_validation.rs](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/mini-redis/source/tests/frame_validation.rs) | [用一个反例区分非法帧与半帧](/mini-redis/source/tests/frame_validation.md) |

## 如何判断自己读懂了一个文件

回到源码，指出进入该文件的调用点、传入资源属于谁、哪一步改变共享状态、返回后谁继续执行，以及 `?` 或 Drop 会结束哪一层。然后沿文章末尾的链接进入调用者或被调用者，验证这一关系，而不是只记住方法名。
