mod get;
pub use get::Get;

mod publish;
pub use publish::Publish;

mod set;
pub use set::Set;

mod subscribe;
pub use subscribe::{Subscribe, Unsubscribe};

mod ping;
pub use ping::Ping;

mod unknown;
pub use unknown::Unknown;

use crate::{Connection, Db, Frame, Parse, ParseError, Shutdown};

/// 统一的命令枚举；每个变体携带对应命令结构体。
/// 分派器只选择路径，具体参数规则与副作用留在各命令文件。
#[derive(Debug)]
pub enum Command {
    Get(Get),
    Publish(Publish),
    Set(Set),
    Subscribe(Subscribe),
    Unsubscribe(Unsubscribe),
    Ping(Ping),
    Unknown(Unknown),
}

impl Command {
    /// 从顶层 Array 解析命令。
    /// 成功返回具体变体；已知命令格式错误返回 Err，未知名称返回 Unknown 变体。
    pub fn from_frame(frame: Frame) -> crate::Result<Command> {
        // Parse::new 消费帧并持有数组迭代器；非 Array 立即返回错误。
        let mut parse = Parse::new(frame)?;

        // 先读取命令名并转小写，使 GET/get 等大小写写法走同一分支。
        let command_name = parse.next_string()?.to_lowercase();

        // 借用命令名的 str 切片匹配，再委托具体 parse_frames 读取剩余参数。
        let command = match &command_name[..] {
            "get" => Command::Get(Get::parse_frames(&mut parse)?),
            "publish" => Command::Publish(Publish::parse_frames(&mut parse)?),
            "set" => Command::Set(Set::parse_frames(&mut parse)?),
            "subscribe" => Command::Subscribe(Subscribe::parse_frames(&mut parse)?),
            "unsubscribe" => Command::Unsubscribe(Unsubscribe::parse_frames(&mut parse)?),
            "ping" => Command::Ping(Ping::parse_frames(&mut parse)?),
            _ => {
                // 未知名称提前返回，不检查未消费的参数；Unknown::apply 稍后负责写错误响应。
                return Ok(Command::Unknown(Unknown::new(command_name)));
            }
        };

        // 已知命令必须恰好消费参数；剩余项意味着不支持的格式。
        parse.finish()?;

        // 返回拥有各参数的命令值，交给 Handler 执行。
        Ok(command)
    }

    /// 消费 Command 并分派 apply；Db 是共享借用，Connection 和 Shutdown 是当前任务的可变借用。
    pub(crate) async fn apply(
        self,
        db: &Db,
        dst: &mut Connection,
        shutdown: &mut Shutdown,
    ) -> crate::Result<()> {
        use Command::*;

        match self {
            Get(cmd) => cmd.apply(db, dst).await,
            Publish(cmd) => cmd.apply(db, dst).await,
            Set(cmd) => cmd.apply(db, dst).await,
            Subscribe(cmd) => cmd.apply(db, dst, shutdown).await,
            Ping(cmd) => cmd.apply(dst).await,
            Unknown(cmd) => cmd.apply(dst).await,
            // 普通模式不接受 Unsubscribe；进入 Subscribe::apply 后由其内部循环处理取消。
            Unsubscribe(_) => Err("`Unsubscribe` is unsupported in this context".into()),
        }
    }

    /// 借用命令名称，供日志或订阅模式下的错误响应使用。
    pub(crate) fn get_name(&self) -> &str {
        match self {
            Command::Get(_) => "get",
            Command::Publish(_) => "publish",
            Command::Set(_) => "set",
            Command::Subscribe(_) => "subscribe",
            Command::Unsubscribe(_) => "unsubscribe",
            Command::Ping(_) => "ping",
            Command::Unknown(cmd) => cmd.get_name(),
        }
    }
}
