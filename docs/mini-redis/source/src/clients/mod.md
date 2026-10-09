---
editLink: false
---

# src/clients/mod.rs：三种客户端的统一出口

<!-- analyzes: src/clients/mod.rs -->

[打开对应源码](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/mini-redis/source/src/clients/mod.rs) · [源码文章索引](/mini-redis/source/index.md) · [总目录](/mini-redis/index.md)

这个文件只负责组织客户端模块。它没有连接池、队列循环或网络协议实现，阅读价值在于把公开类型准确定位到定义文件。

## 它和哪些代码交互

```text
lib.rs → clients/mod.rs
  client.rs → Client、Message、Subscriber
  blocking_client.rs → BlockingClient
  buffered_client.rs → BufferedClient
```

## 八行代码建立的访问路径

<!-- source: src/clients/mod.rs:1-8; comments omitted -->
```rust
mod client;
pub use client::{Client, Message, Subscriber};

mod blocking_client;
pub use blocking_client::BlockingClient;

mod buffered_client;
pub use buffered_client::BufferedClient;
```

子模块 client、blocking_client、buffered_client 都通过私有 mod 引入，再按需 pub use。外部常见路径是 mini_redis::clients::Client，根 lib.rs 另外重导出 Client、BlockingClient、BufferedClient；Message、Subscriber 在 clients 名字下访问。

## 导出类型不等于导出模块

一个同步订阅者的具体类型虽然在 blocking_client.rs 中声明为 pub，但本文件没有把它作为 BlockingSubscriber 重新导出。业务可以使用公开方法返回值并让编译器推断类型；如果需要稳定地写出公开类型路径，应专门设计导出 API。

更改本文件不会改变一条连接如何排队，但会使依赖旧导入路径的程序无法编译。查“Client 的 get 怎么实现”时，立即进入 client.rs；查“多任务共用连接”时，进入 buffered_client.rs。

## 读完后沿哪里继续

[src/lib.rs](/mini-redis/source/src/lib.md) → [src/clients/client.rs](/mini-redis/source/src/clients/client.md) → [src/clients/buffered_client.rs](/mini-redis/source/src/clients/buffered_client.md) → [src/clients/blocking_client.rs](/mini-redis/source/src/clients/blocking_client.md)。

跨文件串读：[第 09 章：客户端关系](/mini-redis/09-clients.md)。
