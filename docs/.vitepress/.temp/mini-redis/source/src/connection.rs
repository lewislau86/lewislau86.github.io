use crate::frame::{self, Frame};

use bytes::{Buf, BytesMut};
use std::io::{self, Cursor};
use tokio::io::{AsyncReadExt, AsyncWriteExt, BufWriter};
use tokio::net::TcpStream;

/// 在一条 TCP 连接上收发完整 Frame。
///
/// TCP 只提供字节流，一次 read 不对应一条命令。读缓冲保留半帧和多帧中的剩余字节；
/// 完整帧才交给 Handler 或 Client。发送时先编码到 BufWriter，最后 flush 到 socket。
#[derive(Debug)]
pub struct Connection {
    // TcpStream 由当前 Connection 独占；BufWriter 合并小块写入，读操作仍访问底层流。
    stream: BufWriter<TcpStream>,

    // 可增长的读缓冲；BytesMut 允许追加并消费字节。
    buffer: BytesMut,
}

impl Connection {
    /// 接管 socket 并创建缓冲；按值传参意味着原调用者不能再直接使用该 socket。
    pub fn new(socket: TcpStream) -> Connection {
        Connection {
            stream: BufWriter::new(socket),
            // 初始分配 4 KiB，不是输入最大长度；实际容量可随 read_buf 增长。
            // 调整容量需测量分配与吞吐，不能仅凭容量越大就推导性能更好。
            buffer: BytesMut::with_capacity(4 * 1024),
        }
    }

    /// 等待并返回一帧，后续帧的字节留给下一次调用。
    ///
    /// # 返回值
    ///
    /// Ok(Some(frame)) 是一帧；Ok(None) 是无残余字节的 EOF；
    /// 半帧期间断开或其他读/解析失败为 Err。这与协议中的 Frame::Null 不同。
    pub async fn read_frame(&mut self) -> crate::Result<Option<Frame>> {
        loop {
            // 优先消费已缓存的数据；? 先处理 Result，if let 再处理 Option。
            if let Some(frame) = self.parse_frame()? {
                return Ok(Some(frame));
            }

            // 当前不足一帧，再异步追加字节；read_buf 返回 0 表示 EOF。
            // await 等待期间让出任务执行机会，不是创建一个新线程。
            if 0 == self.stream.read_buf(&mut self.buffer).await? {
                // 对端关闭时缓冲必须为空才算正常 EOF；残留半帧说明请求被截断。
                if self.buffer.is_empty() {
                    return Ok(None);
                } else {
                    return Err("connection reset by peer".into());
                }
            }
        }
    }

    /// 只尝试解析现有缓冲，不访问网络。完整时消费一帧；不足时 Ok(None)，非法时 Err。
    fn parse_frame(&mut self) -> crate::Result<Option<Frame>> {
        use frame::Error::Incomplete;

        // Cursor 包装字节切片借用并记录位置；Buf trait 提供 advance、remaining 等方法。
        let mut buf = Cursor::new(&self.buffer[..]);

        // 先 check 确认边界，避免半帧时反复创建完整 Frame 的 String/Vec。
        match Frame::check(&mut buf) {
            Ok(_) => {
                // check 从零推进到帧尾，所以当前位置就是这帧消费的字节数。
                let len = buf.position() as usize;

                // parse 必须从起点重新读取，不可沿用 check 留下的帧尾位置。
                buf.set_position(0);

                // 解析出拥有数据的 Frame；失败传播到当前连接的调用者，不会自动停止其他连接。
                let frame = Frame::parse(&mut buf)?;

                // 只消费已经解析的 len 字节，保留同次读取的后续帧。
                // BytesMut 负责底层存储管理，不应在这里把整个缓冲清空。
                self.buffer.advance(len);

                // 将 Frame 交给调用者；返回值不借用 self.buffer。
                Ok(Some(frame))
            }
            // 半帧是 TCP 正常现象，转为 Ok(None)，让 read_frame 循环继续读取。
            Err(Incomplete) => Ok(None),
            // 真正格式错误通过 Into 转为统一错误，最终可使当前 Handler 返回。
            Err(e) => Err(e.into()),
        }
    }

    /// 把 Frame 编码并刷新到 TCP。
    ///
    /// AsyncWriteExt 为 writer 增加 write_all 等便利方法；BufWriter 合并多次小写入。
    /// 成功仅表示本次写入接口完成，不证明对端业务已经处理，更不证明数据持久化。
    pub async fn write_frame(&mut self, frame: &Frame) -> io::Result<()> {
        // 顶层数组先写头，再写每个子值；当前实现不支持编码嵌套数组。
        match frame {
            Frame::Array(val) => {
                // b'*' 是一个字节字面量，表示 RESP 数组前缀。
                self.stream.write_u8(b'*').await?;

                // 写元素个数而非总字节长度。
                self.write_decimal(val.len() as u64).await?;

                // val 是 &Vec<Frame>；&**val 借用其切片，逐项得到 &Frame，不移动元素。
                for entry in &**val {
                    self.write_value(entry).await?;
                }
            }
            // 其他变体直接交给单值编码器。
            _ => self.write_value(frame).await?,
        }

        // flush 将尚在写缓冲中的字节送到 socket；省略可能使调用者一直等响应。
        self.stream.flush().await
    }

    /// 编码非数组帧；&Frame 只借用，调用者仍持有帧。
    async fn write_value(&mut self, frame: &Frame) -> io::Result<()> {
        match frame {
            Frame::Simple(val) => {
                self.stream.write_u8(b'+').await?;
                self.stream.write_all(val.as_bytes()).await?;
                self.stream.write_all(b"\r\n").await?;
            }
            Frame::Error(val) => {
                self.stream.write_u8(b'-').await?;
                self.stream.write_all(val.as_bytes()).await?;
                self.stream.write_all(b"\r\n").await?;
            }
            Frame::Integer(val) => {
                self.stream.write_u8(b':').await?;
                self.write_decimal(*val).await?;
            }
            Frame::Null => {
                self.stream.write_all(b"$-1\r\n").await?;
            }
            Frame::Bulk(val) => {
                let len = val.len();

                self.stream.write_u8(b'$').await?;
                self.write_decimal(len as u64).await?;
                self.stream.write_all(val).await?;
                self.stream.write_all(b"\r\n").await?;
            }
            // 这里尚未实现嵌套数组，遇到它会 panic。
            // 异步递归需要 Box/Pin 等间接层避免无限大小 Future；不是 Rust 永远不能异步递归。
            Frame::Array(_val) => unreachable!(),
        }

        Ok(())
    }

    /// 将 u64 编码为十进制文本，并追加 CRLF。
    async fn write_decimal(&mut self, val: u64) -> io::Result<()> {
        use std::io::Write;

        // u64 最多 20 位十进制数字，使用栈数组和 Cursor 格式化，避免额外 String 分配。
        let mut buf = [0u8; 20];
        let mut buf = Cursor::new(&mut buf[..]);
        write!(&mut buf, "{val}")?;

        let pos = buf.position() as usize;
        self.stream.write_all(&buf.get_ref()[..pos]).await?;
        self.stream.write_all(b"\r\n").await?;

        Ok(())
    }
}
