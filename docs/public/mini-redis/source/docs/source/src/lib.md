# src/lib.rs：库的入口与公开边界

<!-- analyzes: src/lib.rs -->

[打开对应源码](../../../src/lib.rs) · [源码文章索引](../README.md) · [总目录](../../README.md)

这个文件决定外部程序能从 mini_redis 这个名字访问哪些能力。它没有请求循环，也不会因为导入库就启动服务器；它建立的是编译期模块和类型边界。

## 它和哪些代码交互

```text
binary / examples / tests → mini_redis 公开名字
  lib.rs → clients、Command、Connection、Frame、server
         → 内部 Db、Parse、Shutdown
```

## 先区分 mod 和 pub use

<!-- source: src/lib.rs:27-51; comments omitted -->
```rust
pub mod clients;
pub use clients::{BlockingClient, BufferedClient, Client};

pub mod cmd;
pub use cmd::Command;

mod connection;
pub use connection::Connection;

pub mod frame;
pub use frame::Frame;

mod db;
use db::Db;
use db::DbDropGuard;

mod parse;
use parse::{Parse, ParseError};

pub mod server;

mod shutdown;
use shutdown::Shutdown;
```

`mod connection` 声明私有模块，`pub use connection::Connection` 将类型重新导出。外部可以使用 mini_redis::Connection，却不能依赖私有模块路径。Db 与 DbDropGuard 仅用普通 use 引入根作用域，供 crate 内部模块访问；它们不是开放给业务调用者的存储 API。

## 错误别名连接了哪些返回路径

`Error = Box<dyn std::error::Error + Send + Sync>` 让网络、解析等不同错误可以汇入同一个返回类型，`Result<T>` 只是 std::result::Result 的别名。Frame 与 Parse 自己仍定义专门错误枚举，才能把“半帧”和“参数结束”等状态单独匹配。

如果改掉这个别名，Client、命令 apply、Connection 与 binary main 的 `?` 转换都可能受影响；它不只影响报错字符串。DEFAULT_PORT 为 CLI 和 server binary 提供默认端口，但示例里硬编码的地址不会随这个常量自动更新。

## 阅读时的判断

`pub mod clients` 暴露模块，clients 内部又重导出具体类型，根模块再提供简短路径。判断一个名字能不能被外部访问，要沿整条导出链看；看到 struct 前写 pub，并不足以证明它所在模块也公开。修改这里属于 API 兼容性变更，不会直接加快 SET。

## 读完后沿哪里继续

[src/clients/mod.rs](clients/mod.md) → [src/cmd/mod.rs](cmd/mod.md) → [src/bin/server.rs](bin/server.md)。

跨文件串读：[第 01 章：入口与模块](../../01-first-run.md)。
