# 从 mini-redis 学 Rust 与 Redis 架构

我们从一个具体问题开始：客户端执行 `SET course rust` 后，服务器如何保存数据，又如何在 `GET course` 时把它交还给客户端？顺着这条链路，你会遇到所有权、枚举、错误处理、异步任务、共享状态、消息通道和资源回收。每一个 Rust 概念都对应一个服务器必须解决的问题。

这套笔记面向 Rust 初学者。你可以有其他语言的经验，但不需要先学完 Rust 或 Tokio。建议打开源码与笔记并排阅读，运行实验，再用自己的话解释结果。目标是能够读懂并修改这个项目、独立写出类似的异步服务，并建立 Redis 的基础架构认识。Rust 的全部高级主题和生产 Redis 的全部实现不可能由这一个小项目覆盖；补充学习路线放在最后一章。

## 阅读顺序

| 章节 | 我们要解决的问题 | 顺路学到的 Rust |
| --- | --- | --- |
| [01 跑通第一条请求](01-first-run.md) | 从 CLI 到自己写客户端，如何完成一次读写？ | Cargo、路径依赖、模块、函数、宏 |
| [02 用所有权管理一份数据](02-rust-foundations.md) | 数据由谁持有，什么时候能借用，什么时候释放？ | 变量、类型、所有权、借用、结构体、枚举 |
| [03 沿着 SET/GET 走一遍](03-request-path.md) | 字节、帧、命令和数据库如何接起来？ | 方法接收者、泛型、trait、Result、`?` |
| [04 TCP 字节如何变成帧](04-resp-and-connection.md) | 半条消息和多条消息一起到达怎么办？ | 切片、Cursor、生命周期、错误枚举 |
| [05 为什么服务器能同时服务多人](05-tokio-server.md) | 异步操作何时执行，等待时其他客户端怎么继续？ | Future、runtime、features、spawn、Send、select |
| [06 数据如何安全地共享](06-shared-storage.md) | 多个连接怎样访问同一张表？ | Arc、Mutex、内部可变性、闭包、RAII |
| [07 到期的数据由谁删除](07-expiration.md) | 不扫描整张表，怎样找到下一条过期记录？ | Option、元组排序、BTreeSet、Notify |
| [08 发布订阅为什么改变连接状态](08-pubsub.md) | 服务器怎样主动推送，慢订阅者会怎样？ | channel、Stream、Pin、trait 对象 |
| [09 客户端为什么有三种形态](09-clients.md) | 多个调用者能安全共用一个连接吗？ | mpsc、oneshot、迭代器、同步与异步边界 |
| [10 如何停机与验证行为](10-shutdown-and-tests.md) | 怎么通知退出，又怎么知道已经退出？ | Drop、通道关闭、测试、虚拟时间 |
| [11 从教学服务器走向 Redis](11-real-redis.md) | 持久化、复制、集群分别解决什么问题？ | 区分语言实现与数据库架构 |
| [12 动手练习与知识索引](12-exercises-and-index.md) | 我是否真的能独立读代码、做修改？ | 编译器诊断、边界测试、知识复盘 |

按顺序完成 01—04，先运行 CLI，再运行自己写的客户端，学会解释语法后进入请求链路；完成 05—07，通过异步小实验理解执行机制，再阅读并发与共享状态；最后读 08—12，把连接生命周期与完整数据库架构连起来。各章安排了思考题与参考答案，最后一章还有综合练习。不要只背名词：能够在源码中找到支持结论的函数，才算真正读懂。

## 本书针对哪一份代码

- 本地包版本：`mini-redis 0.4.1`，Rust edition `2018`。
- 分析基线：Git commit `3d93b42bc363220f85af4fc9e1bebd35b588a4a3`。
- 初稿及首次核验：2026-10-08；Hello Tokio 补充及相关实验核验：2026-10-09。
- 文中的相对源码链接指向本仓库；函数名作为定位依据，避免代码增删后行号失效。
- 正文标为“源码节选”的代码保留关键实现；标为“教学示例”的代码用于说明概念。可完整运行的程序集中在 [labs](labs/README.md)。

实现事实以当前源码为准。比如本版本的 API 是 `Client::connect(...)`；不要把旧教程中的自由函数调用直接复制过来。依赖的具体解析版本看根目录 `Cargo.lock`，并使用 `--locked` 保持一致。

## 先看整体地图

```text
mini-redis-cli / Client
       │ 请求：SET / GET 编码为 RESP 字节
       ▼
TCP → Connection → Frame → Command → Db
       ▲                          │    │
       └────── 响应 Frame ────────┘    ├─ HashMap：键值
                                      ├─ BTreeSet：过期索引
                                      └─ broadcast：订阅消息

server::Listener：接收连接、限制连接数、创建 Handler
每个 Handler：循环处理一个连接的请求
后台清理任务：等待下一次过期时间或 Notify
停机路径：停止接入 → 通知 Handler → 等待连接任务退出
```

图中的箭头是逻辑调用/数据流，不代表每个方框都运行在独立线程。第 05 章会专门解释任务与线程的区别。

## 配套实验与验证

第 01 章的 hello_tokio 连接你手动启动的服务，复现“自己写客户端”的过程：

```sh
# 先按第 01 章在另一个终端启动 16379 服务
cargo run --locked --manifest-path docs/labs/Cargo.toml --bin hello_tokio
```

其余实验从仓库根目录运行，无须预先启动服务或安装真正 Redis：

```sh
cargo run --locked --manifest-path docs/labs/Cargo.toml --bin ownership
cargo run --locked --manifest-path docs/labs/Cargo.toml --bin frames
cargo run --locked --manifest-path docs/labs/Cargo.toml --bin async_basics
cargo run --locked --manifest-path docs/labs/Cargo.toml --bin roundtrip
cargo run --locked --manifest-path docs/labs/Cargo.toml --bin multiplex
```

后两个实验自建监听 `127.0.0.1:0` 的临时服务，操作自己的内存数据库，结束时发出停机通知并等待退出。可复核的执行结果及限制见 [验证记录](validation.md)。

## 如何使用参考资料

你提供的[源码分析系列](https://blog.yqxpro.com/categories/%E6%BA%90%E7%A0%81%E5%88%86%E6%9E%90/mini-redis/)包含概述、存储、帧解析、命令四篇，可在读完对应章节后交叉阅读。本笔记围绕本地代码重新组织教学内容，补上入门语法、客户端、异步执行、停机、实验与真正 Redis 的架构边界。

Rust 语义以 [The Rust Programming Language](https://doc.rust-lang.org/book/) 为系统教材；Tokio 的运行模型可继续阅读 [官方教程](https://tokio.rs/tokio/tutorial)。Redis 协议和数据库能力的官方资料附在相关章节，避免把教学实现当作完整规范。

补充阅读的 [Hello Tokio](https://tokio.rs/tokio/tutorial/hello-tokio) 已融入入门过程，按下面的对应关系阅读即可，不需要在中途另开一套项目：

| 官方页面的内容 | 本笔记中的承接 |
| --- | --- |
| 建项目、加依赖、编写客户端 | 第 01 章与 hello_tokio 实验，使用本地路径依赖 |
| 拆解连接与读写代码 | 第 02 章讲所有权，第 03 章讲 connect、请求链路与 `.await?` |
| 异步调用的执行时机 | 第 05 章与 async_basics 实验 |
| async main、runtime、Cargo features | 第 05 章区分编译配置、运行环境和任务提交 |

这里按本地 API 调整示例，并把“初次接触时看懂顺序”和“读源码时理解机制”分开安排。官方页面、版本锁定的 API 文档与本地源码相互补充。

开始阅读：[01 跑通第一条请求](01-first-run.md)。
