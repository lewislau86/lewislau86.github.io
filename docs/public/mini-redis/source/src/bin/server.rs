//! mini-redis 服务程序入口。
//!
//! 本文件是独立 binary 的 crate 根：解析参数、创建监听器，再调用库的 server::run。
//! 库根 src/lib.rs 用 pub mod server 声明公开模块；下面的 use 只引入名字，不启动服务。
//! 命令行参数由 clap 解析，连接和任务生命周期交给 src/server.rs。

use mini_redis::{server, DEFAULT_PORT};

use clap::Parser;
use tokio::net::TcpListener;
use tokio::signal;

#[cfg(feature = "otel")]
// 启用 otel feature 才编译此导入，用于设置全局传播器。
use opentelemetry::global;
#[cfg(feature = "otel")]
// as sdktrace 为模块起局部别名，避免冗长路径。
use opentelemetry::sdk::trace as sdktrace;
#[cfg(feature = "otel")]
// 用于在服务之间传播 X-Ray 链路标识。
use opentelemetry_aws::trace::XrayPropagator;
#[cfg(feature = "otel")]
// 导入扩展 trait 后，Registry 才能通过方法语法组合 layer 和初始化订阅器。
use tracing_subscriber::{
    fmt, layer::SubscriberExt, util::SubscriberInitExt, util::TryInitError, EnvFilter,
};

// 属性宏生成同步入口和 Tokio runtime，然后驱动下面的 async 函数体。
#[tokio::main]
pub async fn main() -> mini_redis::Result<()> {
    // ? 解开 Ok；Err 则转换为 main 的错误类型并提前返回。
    set_up_logging()?;

    // Parser 是 trait，derive(Parser) 生成实现；导入 trait 后可调用 parse。
    let cli = Cli::parse();
    // Option<u16>：Some 使用用户端口，None 使用默认值；这里不是会 panic 的 unwrap。
    let port = cli.port.unwrap_or(DEFAULT_PORT);

    // 绑定本机监听地址；await 等待绑定结果，? 在失败时提前返回 main。
    let listener = TcpListener::bind(&format!("127.0.0.1:{port}")).await?;

    // server 来自顶部 use mini_redis::server，并非指当前这个同名文件。
    // listener 被移动给库；ctrl_c() 返回等待信号的 Future，此处没有先等待 Ctrl+C。
    // run 内部并发等待接入与停止；它返回后 main 才继续执行 Ok(())。
    server::run(listener, signal::ctrl_c()).await;

    Ok(())
}

// derive 是派生宏：Parser 生成命令行解析实现，Debug 支持调试格式化。
#[derive(Parser, Debug)]
#[command(name = "mini-redis-server", version, author, about = "A Redis server")]
struct Cli {
    // clap 辅助属性生成 --port 选项；Option 表示可省略。
    #[arg(long)]
    port: Option<u16>,
}

// cfg 在编译期选择实现；与运行时 if 不同，未选中代码不进入本次编译。
#[cfg(not(feature = "otel"))]
fn set_up_logging() -> mini_redis::Result<()> {
    // 安装默认日志订阅器；try_init 返回错误而不是直接 panic。参考：https://docs.rs/tracing
    tracing_subscriber::fmt::try_init()
}

#[cfg(feature = "otel")]
fn set_up_logging() -> Result<(), TryInitError> {
    // 设置 X-Ray 全局传播器；跨服务传播还需要在请求边界注入/提取上下文。
    // 仅这一行不会自动完成分布式链路接入。示例：
    // https://github.com/open-telemetry/opentelemetry-rust/blob/v0.19.0/examples/aws-xray/src/server.rs#L14-L26
    global::set_text_map_propagator(XrayPropagator::default());

    let tracer = opentelemetry_otlp::new_pipeline()
        .tracing()
        .with_exporter(opentelemetry_otlp::new_exporter().tonic())
        .with_trace_config(
            sdktrace::config()
                .with_sampler(sdktrace::Sampler::AlwaysOn)
                // 使用兼容 X-Ray 格式的链路 ID 生成器。
                .with_id_generator(sdktrace::XrayIdGenerator::default()),
        )
        .install_simple()
        .expect("Unable to initialize OtlpPipeline");

    // 将配置好的 tracer 包装为 tracing layer。
    let opentelemetry = tracing_opentelemetry::layer().with_tracer(tracer);

    // 从 RUST_LOG 环境变量读取日志过滤规则。
    let filter = EnvFilter::from_default_env();

    // 通过扩展 trait 的 with 逐层组合订阅器，最后尝试全局初始化。
    tracing_subscriber::registry()
        .with(opentelemetry)
        .with(filter)
        .with(fmt::Layer::default())
        .try_init()
}
