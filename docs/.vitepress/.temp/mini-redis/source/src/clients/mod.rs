//! 客户端模块入口：mod 声明子模块，pub use 把选定类型重新导出。
//! 外部使用 mini_redis::clients::Client，不必访问私有 client 模块路径。

mod client;
pub use client::{Client, Message, Subscriber};

mod blocking_client;
pub use blocking_client::BlockingClient;

mod buffered_client;
pub use buffered_client::BufferedClient;
