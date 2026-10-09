use mini_redis::{clients::Client, DEFAULT_PORT};

use bytes::Bytes;
use clap::{Parser, Subcommand};
use std::num::ParseIntError;
use std::str;
use std::time::Duration;

#[derive(Parser, Debug)]
#[command(
    name = "mini-redis-cli",
    version,
    author,
    about = "Issue Redis commands"
)]
struct Cli {
    #[clap(subcommand)]
    command: Command,

    #[arg(id = "hostname", long, default_value = "127.0.0.1")]
    host: String,

    #[arg(long, default_value_t = DEFAULT_PORT)]
    port: u16,
}

#[derive(Subcommand, Debug)]
enum Command {
    Ping {
        /// PING 可选回显内容；None 表示请求 PONG，Some 表示回显给定字节。
        msg: Option<Bytes>,
    },
    /// 读取指定键的值。
    Get {
        /// 要读取的键名。
        key: String,
    },
    /// 写入键值，可附带过期时间。
    Set {
        /// 要写入的键名。
        key: String,

        /// 值以 Bytes 保存，允许非 UTF-8 字节。
        value: Bytes,

        /// 可选存活时间；命令行按毫秒解析为 Duration。
        #[arg(value_parser = duration_from_ms_str)]
        expires: Option<Duration>,
    },
    /// 向指定频道发布一条消息。
    Publish {
        /// 频道名；频道表与键值表分开管理。
        channel: String,

        /// 要发布的消息字节。
        message: Bytes,
    },
    /// 让当前连接订阅一个或多个频道。
    Subscribe {
        /// 频道列表；Vec 拥有每一个 String。
        channels: Vec<String>,
    },
}

/// CLI 的程序入口。
///
/// #[tokio::main] 是属性宏：生成同步入口并创建 runtime，随后驱动异步函数体。
/// current_thread 使用当前线程调度异步任务；异步并不等于每个任务各占一个线程。
#[tokio::main(flavor = "current_thread")]
async fn main() -> mini_redis::Result<()> {
    // 初始化日志；? 遇到 Err 时结束 main 并向上返回错误。
    tracing_subscriber::fmt::try_init()?;

    // 调用 clap 的 Parser trait 方法，将命令行参数解析为 Cli。
    let cli = Cli::parse();

    // format! 生成拥有内容的 String，拼出服务器地址。
    let addr = format!("{}:{}", cli.host, cli.port);

    // 等待 TCP 建连；mut 使后续命令可以通过 &mut self 独占这个客户端。
    let mut client = Client::connect(&addr).await?;

    // match 消费命令枚举，按变体取出参数并选择业务操作。
    match cli.command {
        Command::Ping { msg } => {
            let value = client.ping(msg).await?;
            if let Ok(string) = str::from_utf8(&value) {
                println!("\"{string}\"");
            } else {
                println!("{value:?}");
            }
        }
        Command::Get { key } => {
            if let Some(value) = client.get(&key).await? {
                if let Ok(string) = str::from_utf8(&value) {
                    println!("\"{string}\"");
                } else {
                    println!("{value:?}");
                }
            } else {
                println!("(nil)");
            }
        }
        Command::Set {
            key,
            value,
            expires: None,
        } => {
            client.set(&key, value).await?;
            println!("OK");
        }
        Command::Set {
            key,
            value,
            expires: Some(expires),
        } => {
            client.set_expires(&key, value, expires).await?;
            println!("OK");
        }
        Command::Publish { channel, message } => {
            client.publish(&channel, message).await?;
            println!("Publish OK");
        }
        Command::Subscribe { channels } => {
            if channels.is_empty() {
                return Err("channel(s) must be provided".into());
            }
            let mut subscriber = client.subscribe(channels).await?;

            // while let 持续读取 Some(Message)；EOF 的 None 结束循环，Err 由 ? 返回。
            while let Some(msg) = subscriber.next_message().await? {
                println!(
                    "got message from the channel: {}; message = {:?}",
                    msg.channel, msg.content
                );
            }
        }
    }

    Ok(())
}

// 先用 parse::<u64> 解析毫秒数；? 把解析错误交给 clap，成功才构造 Duration。
fn duration_from_ms_str(src: &str) -> Result<Duration, ParseIntError> {
    let ms = src.parse::<u64>()?;
    Ok(Duration::from_millis(ms))
}
