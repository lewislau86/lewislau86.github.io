use crate::Frame;

use bytes::Bytes;
use std::{fmt, str, vec};

/// 从命令数组中逐项取参数。
///
/// Frame 解决字节边界，Parse 解决参数类型与读取顺序。Command 已先读掉命令名，
/// 具体命令的 parse_frames 从剩余项读取字段；最后由 Command 调用 finish 检查多余参数。
#[derive(Debug)]
pub(crate) struct Parse {
    /// 拥有数组元素的迭代器；into_iter 移入 Vec，每次 next 移出一个 Frame。
    parts: vec::IntoIter<Frame>,
}

/// 参数读取失败的分类。
///
/// EndOfStream 是否正常由具体命令决定：缺必需 key 是错误，没有可选 TTL 可以正常。
/// 未被命令处理的错误经 ? 到达 Handler，结束该连接，不会自动写 Error 帧。
#[derive(Debug)]
pub(crate) enum ParseError {
    /// 迭代器已耗尽，无法再取得一个参数。
    EndOfStream,

    /// 参数类型、编码等其他错误。
    Other(crate::Error),
}

impl Parse {
    /// 接管 Frame；仅 Array 可以成为命令参数列表，其他变体返回 Err。
    pub(crate) fn new(frame: Frame) -> Result<Parse, ParseError> {
        let array = match frame {
            Frame::Array(array) => array,
            frame => return Err(format!("protocol error; expected array, got {frame:?}").into()),
        };

        Ok(Parse {
            parts: array.into_iter(),
        })
    }

    /// 消费并返回下一项；ok_or 将 Option::None 转换为 EndOfStream。
    fn next(&mut self) -> Result<Frame, ParseError> {
        self.parts.next().ok_or(ParseError::EndOfStream)
    }

    /// 读取文本参数；Bulk 必须是 UTF-8，类型不符或编码失败返回 Err。
    pub(crate) fn next_string(&mut self) -> Result<String, ParseError> {
        match self.next()? {
            // Simple 已持有 String；Bulk 验证 UTF-8 后生成 String。
            // Error 虽然也包含文本，但属于错误响应，不能当作普通字符串参数。
            Frame::Simple(s) => Ok(s),
            Frame::Bulk(data) => str::from_utf8(&data[..])
                .map(|s| s.to_string())
                .map_err(|_| "protocol error; invalid string".into()),
            frame => Err(format!(
                "protocol error; expected simple frame or bulk frame, got {frame:?}"
            )
            .into()),
        }
    }

    /// 读取原始字节参数；SET 值和发布内容不要求 UTF-8。
    pub(crate) fn next_bytes(&mut self) -> Result<Bytes, ParseError> {
        match self.next()? {
            // Simple 消费 String 并转换为字节；Bulk 直接交出 Bytes。
            // 不把 Error 变体的文本误当成正常参数。
            Frame::Simple(s) => Ok(Bytes::from(s.into_bytes())),
            Frame::Bulk(data) => Ok(data),
            frame => Err(format!(
                "protocol error; expected simple frame or bulk frame, got {frame:?}"
            )
            .into()),
        }
    }

    /// 读取 u64；接受 Integer 或可解析的 Simple/Bulk，无法转换就返回 Err。
    pub(crate) fn next_int(&mut self) -> Result<u64, ParseError> {
        use atoi::atoi;

        const MSG: &str = "protocol error; invalid number";

        match self.next()? {
            // Integer 已经携带 u64，可以直接移动出来。
            Frame::Integer(v) => Ok(v),
            // atoi::<u64> 用 turbofish 明确泛型结果类型。
            // ok_or_else 的闭包只在解析得到 None 时构造错误。
            Frame::Simple(data) => atoi::<u64>(data.as_bytes()).ok_or_else(|| MSG.into()),
            Frame::Bulk(data) => atoi::<u64>(&data).ok_or_else(|| MSG.into()),
            frame => Err(format!("protocol error; expected int frame but got {frame:?}").into()),
        }
    }

    /// 消费性地尝试再取一项；仍有内容就拒绝多余参数。
    pub(crate) fn finish(&mut self) -> Result<(), ParseError> {
        if self.parts.next().is_none() {
            Ok(())
        } else {
            Err("protocol error; expected end of frame, but there was more".into())
        }
    }
}

// trait 实现集中定义转换；into() 的目标由返回类型或赋值位置推断。
impl From<String> for ParseError {
    fn from(src: String) -> ParseError {
        ParseError::Other(src.into())
    }
}

impl From<&str> for ParseError {
    fn from(src: &str) -> ParseError {
        src.to_string().into()
    }
}

impl fmt::Display for ParseError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            ParseError::EndOfStream => "protocol error; unexpected end of stream".fmt(f),
            ParseError::Other(err) => err.fmt(f),
        }
    }
}

impl std::error::Error for ParseError {}
