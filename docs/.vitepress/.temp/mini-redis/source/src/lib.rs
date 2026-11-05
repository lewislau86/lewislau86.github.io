//! 用于学习 Tokio 异步 Rust 的精简 Redis 服务端与客户端，不是完整生产数据库。
//!
//! # 模块与入口
//!
//! 本文件是库 crate 的根；src/bin 下的程序是同一个 Cargo 包中的独立 binary crate。
//! 包名 mini-redis 在代码中写作 mini_redis。mod 声明模块，pub 开放访问，use 引入名字。
//! pub use 还会重新导出名字，使调用者不必依赖内部文件路径。
//!
//! * server：接收 TcpListener，每连接创建一个异步任务。
//! * clients：基础异步客户端，以及队列和同步包装。
//! * cmd：命令编码、参数解析与业务执行。
//! * frame：命令与 TCP 字节之间的协议数据类型。
//! * connection：读取完整帧及编码发送，隐藏半帧和缓冲细节。
//!
//! 部分模块为教学而公开，实际库设计应按稳定 API 边界收敛可见性。

pub mod clients;
pub use clients::{BlockingClient, BufferedClient, Client};

pub mod cmd;
pub use cmd::Command;

mod connection;
// 重新导出类型，模块本身保持私有；外部仍能使用 mini_redis::Connection。
pub use connection::Connection;

pub mod frame;
pub use frame::Frame;

mod db;
use db::Db;
use db::DbDropGuard;

mod parse;
use parse::{Parse, ParseError};

// 声明公开 server 模块；此处按文件规则加载 src/server.rs。
// 外部完整路径为 mini_redis::server::run，use 只是让调用处能写短名字。
pub mod server;

mod shutdown;
use shutdown::Shutdown;

/// 入口未指定端口时使用的默认值；常量不会自动覆盖示例里的硬编码地址。
pub const DEFAULT_PORT: u16 = 6379;

/// 多数操作共用的错误类型别名。
///
/// Box 持有堆上的错误，dyn Error 隐藏具体错误类型；Send + Sync 要求它可跨线程移动及共享引用。
/// 这不会自动重试或记录错误。? 可通过 From 转换把不同错误汇入这里。
/// 频繁匹配的状态仍用具体枚举：frame::Error::Incomplete 表示半帧，ParseError::EndOfStream 表示参数耗尽。
/// 它们实现标准错误 trait 后才能参与需要的错误转换。
pub type Error = Box<dyn std::error::Error + Send + Sync>;

/// 固定错误类型的 Result 别名；T 仍由调用者决定。
/// Result<()> 表示成功时只返回单元值 ()，不表示没有错误或没有副作用。
pub type Result<T> = std::result::Result<T, Error>;
