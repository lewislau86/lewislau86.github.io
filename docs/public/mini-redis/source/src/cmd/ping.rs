use crate::{Connection, Frame, Parse, ParseError};
use bytes::Bytes;
use tracing::{debug, instrument};

/// 无参数回复 Simple PONG，有参数回复 Bulk 回显。
/// 可用于检查本次往返，但不能证明数据库其他能力正常。Default 派生使 msg 默认为 None。
#[derive(Debug, Default)]
pub struct Ping {
    /// None 表示无参数；Some(空 Bytes) 仍是有参数，应该回显空内容。
    msg: Option<Bytes>,
}

impl Ping {
    /// 接管可选消息，构造命令值。
    pub fn new(msg: Option<Bytes>) -> Ping {
        Ping { msg }
    }

    /// 解析可选参数：命令名已被消费，参数结束可用默认 Ping，无须报错。
    /// 其他类型错误仍返回；额外参数由外层 finish 拒绝。下面展示请求格式。
    ///
    /// ```text
    /// PING [message]
    /// ```
    pub(crate) fn parse_frames(parse: &mut Parse) -> crate::Result<Ping> {
        match parse.next_bytes() {
            Ok(msg) => Ok(Ping::new(Some(msg))),
            Err(ParseError::EndOfStream) => Ok(Ping::default()),
            Err(e) => Err(e.into()),
        }
    }

    /// 由服务端分派器调用，不访问 Db，只选择 PONG 或回显并发送。
    #[instrument(skip(self, dst))]
    pub(crate) async fn apply(self, dst: &mut Connection) -> crate::Result<()> {
        let response = match self.msg {
            None => Frame::Simple("PONG".to_string()),
            Some(msg) => Frame::Bulk(msg),
        };

        debug!(?response);

        // 写失败经 ? 返回当前 Handler，成功则继续等待下条请求。
        dst.write_frame(&response).await?;

        Ok(())
    }

    /// 客户端将 Ping 消费为数组，只有 Some 时才追加消息参数。
    pub(crate) fn into_frame(self) -> Frame {
        let mut frame = Frame::array();
        frame.push_bulk(Bytes::from("ping".as_bytes()));
        if let Some(msg) = self.msg {
            frame.push_bulk(msg);
        }
        frame
    }
}
