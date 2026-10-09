//! RESP 帧类型、字节检查与解析工具。
//!
//! Connection 先 check 再 parse；Frame 不持有 socket，写入编码位于 connection.rs。

use bytes::{Buf, Bytes};
use std::convert::TryInto;
use std::fmt;
use std::io::Cursor;
use std::num::TryFromIntError;
use std::string::FromUtf8Error;

/// 协议帧的带数据枚举；match 必须处理所需变体，Array 通过 Vec 间接递归。
/// Integer 当前使用 u64，因此不能据此推导完整 RESP 整数兼容性。
#[derive(Clone, Debug)]
pub enum Frame {
    Simple(String),
    Error(String),
    Integer(u64),
    Bulk(Bytes),
    Null,
    Array(Vec<Frame>),
}

#[derive(Debug)]
pub enum Error {
    /// 当前字节不够一帧；Connection 将继续读，不能当成致命格式错误。
    Incomplete,

    /// 格式、数值转换或文本编码等错误。
    Other(crate::Error),
}

impl Frame {
    /// 构造空 Array；pub(crate) 将此辅助方法限制在当前库 crate 内。
    pub(crate) fn array() -> Frame {
        Frame::Array(vec![])
    }

    /// 向 Array 追加 Bulk，并移动 Bytes 句柄。
    ///
    /// # 发生 panic 的条件
    ///
    /// self 不是 Array 时触发 panic；调用方必须先建立数组。
    pub(crate) fn push_bulk(&mut self, bytes: Bytes) {
        match self {
            Frame::Array(vec) => {
                vec.push(Frame::Bulk(bytes));
            }
            _ => panic!("not an array frame"),
        }
    }

    /// 向 Array 追加 Integer。
    ///
    /// # 发生 panic 的条件
    ///
    /// self 不是 Array 时触发 panic。
    pub(crate) fn push_int(&mut self, value: u64) {
        match self {
            Frame::Array(vec) => {
                vec.push(Frame::Integer(value));
            }
            _ => panic!("not an array frame"),
        }
    }

    /// 推进临时游标，检查是否有一帧可供解析；不会构造完整 Frame。
    /// 当前检查不包含统一尺寸/嵌套深度上限或 Bulk 尾部 CRLF 的逐字节验证。
    pub fn check(src: &mut Cursor<&[u8]>) -> Result<(), Error> {
        match get_u8(src)? {
            b'+' => {
                get_line(src)?;
                Ok(())
            }
            b'-' => {
                get_line(src)?;
                Ok(())
            }
            b':' => {
                let _ = get_decimal(src)?;
                Ok(())
            }
            b'$' => {
                // Bulk 格式为 $<长度>\r\n<正文>\r\n。
                // $-1\r\n 表示 Null；其他负长度必须作为非法帧拒绝。
                if b'-' == peek_u8(src)? {
                    let line = get_line(src)?;
                    if line != b"-1" {
                        return Err("protocol error; invalid frame format".into());
                    }
                    Ok(())
                } else {
                    // try_into 将 u64 转为平台 usize，转换失败经 ? 返回。
                    let len: usize = get_decimal(src)?.try_into()?;

                    // 跳过正文长度再加两个尾部字节；此处只验证余量，不核验尾部字节内容。
                    skip(src, len + 2)
                }
            }
            b'*' => {
                let len = get_decimal(src)?;

                for _ in 0..len {
                    Frame::check(src)?;
                }

                Ok(())
            }
            actual => Err(format!("protocol error; invalid frame type byte `{actual}`").into()),
        }
    }

    /// 按游标构造 Frame；正常调用约定是先通过 check，再把游标归零。
    /// 未知类型分支仍为 unimplemented，不能把此方法当作任意输入的完整验证器。
    pub fn parse(src: &mut Cursor<&[u8]>) -> Result<Frame, Error> {
        match get_u8(src)? {
            b'+' => {
                // 借用一行，再复制到拥有内容的 Vec<u8>。
                let line = get_line(src)?.to_vec();

                // 验证 UTF-8 并接管 Vec；失败时 From 实现将错误转换为帧错误。
                let string = String::from_utf8(line)?;

                Ok(Frame::Simple(string))
            }
            b'-' => {
                // 读取错误响应的一行，复制为 Vec<u8>。
                let line = get_line(src)?.to_vec();

                // 把错误响应正文转换为合法 UTF-8 String。
                let string = String::from_utf8(line)?;

                Ok(Frame::Error(string))
            }
            b':' => {
                let len = get_decimal(src)?;
                Ok(Frame::Integer(len))
            }
            b'$' => {
                if b'-' == peek_u8(src)? {
                    let line = get_line(src)?;

                    if line != b"-1" {
                        return Err("protocol error; invalid frame format".into());
                    }

                    Ok(Frame::Null)
                } else {
                    // 解析长度并检查正文及尾部字节是否完整。
                    let len = get_decimal(src)?.try_into()?;
                    let n = len + 2;

                    if src.remaining() < n {
                        return Err(Error::Incomplete);
                    }

                    let data = Bytes::copy_from_slice(&src.chunk()[..len]);

                    // 推进正文与尾部两字节；返回的 Bytes 已单独持有复制的数据。
                    skip(src, n)?;

                    Ok(Frame::Bulk(data))
                }
            }
            b'*' => {
                let len = get_decimal(src)?.try_into()?;
                let mut out = Vec::with_capacity(len);

                for _ in 0..len {
                    out.push(Frame::parse(src)?);
                }

                Ok(Frame::Array(out))
            }
            _ => unimplemented!(),
        }
    }

    /// 将意外响应格式化成错误；不会向网络写入 Error 帧。
    pub(crate) fn to_error(&self) -> crate::Error {
        format!("unexpected frame: {self}").into()
    }
}

// 为 Frame 实现与 &str 的相等比较，供客户端识别 OK、subscribe 等协议标记。
// trait 要求 other: &Rhs；Rhs 本身是 &str，所以这里出现 &&str。
impl PartialEq<&str> for Frame {
    fn eq(&self, other: &&str) -> bool {
        match self {
            Frame::Simple(s) => s.eq(other),
            Frame::Bulk(s) => s.eq(other),
            _ => false,
        }
    }
}

// Display 用于可读展示；不等同于 Connection 的 RESP 编码。
// Subscriber 当前依赖 to_string 转内容，因此更改展示也可能影响消息数据。
impl fmt::Display for Frame {
    fn fmt(&self, fmt: &mut fmt::Formatter) -> fmt::Result {
        use std::str;

        match self {
            Frame::Simple(response) => response.fmt(fmt),
            Frame::Error(msg) => write!(fmt, "error: {msg}"),
            Frame::Integer(num) => num.fmt(fmt),
            Frame::Bulk(msg) => match str::from_utf8(msg) {
                Ok(string) => string.fmt(fmt),
                Err(_) => write!(fmt, "{msg:?}"),
            },
            Frame::Null => "(nil)".fmt(fmt),
            Frame::Array(parts) => {
                for (i, part) in parts.iter().enumerate() {
                    if i > 0 {
                        // 仅为可读展示在数组元素间加入空格，不是 RESP 编码。
                        write!(fmt, " ")?;
                    }

                    part.fmt(fmt)?;
                }

                Ok(())
            }
        }
    }
}

fn peek_u8(src: &mut Cursor<&[u8]>) -> Result<u8, Error> {
    if !src.has_remaining() {
        return Err(Error::Incomplete);
    }

    Ok(src.chunk()[0])
}

fn get_u8(src: &mut Cursor<&[u8]>) -> Result<u8, Error> {
    if !src.has_remaining() {
        return Err(Error::Incomplete);
    }

    Ok(src.get_u8())
}

fn skip(src: &mut Cursor<&[u8]>, n: usize) -> Result<(), Error> {
    if src.remaining() < n {
        return Err(Error::Incomplete);
    }

    src.advance(n);
    Ok(())
}

/// 读取 CRLF 结束的十进制文本，通过 atoi 转为 u64。
fn get_decimal(src: &mut Cursor<&[u8]>) -> Result<u64, Error> {
    use atoi::atoi;

    let line = get_line(src)?;

    atoi::<u64>(line).ok_or_else(|| "protocol error; invalid frame format".into())
}

/// 返回原输入中的一段借用；生命周期 a 关联输入字节与返回切片，不延长实际存活时间。
fn get_line<'a>(src: &mut Cursor<&'a [u8]>) -> Result<&'a [u8], Error> {
    // 从游标当前位置直接扫描输入切片，不分配新字符串。
    let start = src.position() as usize;
    // 扫描到倒数第二字节，给后面的 i + 1 留出位置。
    let end = src.get_ref().len() - 1;

    for i in start..end {
        if src.get_ref()[i] == b'\r' && src.get_ref()[i + 1] == b'\n' {
            // 找到 CRLF 后，把游标推进到下一段内容的起点。
            src.set_position((i + 2) as u64);

            // 返回正文切片，排除 CRLF；切片仍引用原输入数据。
            return Ok(&src.get_ref()[start..i]);
        }
    }

    Err(Error::Incomplete)
}

// From 定义错误转换，让调用处的 .into() 和 ? 能接入统一返回类型。
impl From<String> for Error {
    fn from(src: String) -> Error {
        Error::Other(src.into())
    }
}

impl From<&str> for Error {
    fn from(src: &str) -> Error {
        src.to_string().into()
    }
}

impl From<FromUtf8Error> for Error {
    fn from(_src: FromUtf8Error) -> Error {
        "protocol error; invalid frame format".into()
    }
}

impl From<TryFromIntError> for Error {
    fn from(_src: TryFromIntError) -> Error {
        "protocol error; invalid frame format".into()
    }
}

impl std::error::Error for Error {}

impl fmt::Display for Error {
    fn fmt(&self, fmt: &mut fmt::Formatter) -> fmt::Result {
        match self {
            Error::Incomplete => "stream ended early".fmt(fmt),
            Error::Other(err) => err.fmt(fmt),
        }
    }
}
