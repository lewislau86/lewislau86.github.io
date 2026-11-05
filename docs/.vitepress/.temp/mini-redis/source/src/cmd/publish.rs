use crate::{Connection, Db, Frame, Parse};

use bytes::Bytes;

/// 向频道广播一条消息，发布者不直接持有各订阅者连接。
/// 频道与键值表是不同命名空间：PUBLISH foo 不会覆盖 SET foo 的值。
#[derive(Debug)]
pub struct Publish {
    /// 拥有频道名，独立于请求帧的存活时间。
    channel: String,

    /// 消息可以是任意字节；具体客户端接收实现仍需检查是否无损。
    message: Bytes,
}

impl Publish {
    /// 接收可转字符串的频道名，拥有 message，构造发布命令。
    pub(crate) fn new(channel: impl ToString, message: Bytes) -> Publish {
        Publish {
            channel: channel.to_string(),
            message,
        }
    }

    /// 命令名已消费，从 Parse 读取频道及消息，缺失或类型错误返回 Err。
    /// 完整格式如下；剩余参数由外层 finish 校验。
    ///
    /// ```text
    /// PUBLISH channel message
    /// ```
    pub(crate) fn parse_frames(parse: &mut Parse) -> crate::Result<Publish> {
        // 频道要求合法文本，读取失败则不继续发布。
        let channel = parse.next_string()?;

        // 消息用 next_bytes 读取，不强制 UTF-8。
        let message = parse.next_bytes()?;

        Ok(Publish { channel, message })
    }

    /// 服务端执行发布，向发布者回复 Integer 数量；订阅消息由其他连接任务自行发送。
    pub(crate) async fn apply(self, db: &Db, dst: &mut Connection) -> crate::Result<()> {
        // Db 向 broadcast Sender 同步发送，得到当前接收者数量。
        // 接收者可能随后断开或落后丢消息，因此数量不是投递完成或消费确认。
        let num_subscribers = db.publish(&self.channel, self.message);

        // 把数量转换为协议 Integer，交回发布者。
        let response = Frame::Integer(num_subscribers as u64);

        // 写发布结果；即使这里失败，之前的广播也不会撤销。
        dst.write_frame(&response).await?;

        Ok(())
    }

    /// 客户端编码 [publish, channel, message]，此处不执行广播。
    pub(crate) fn into_frame(self) -> Frame {
        let mut frame = Frame::array();
        frame.push_bulk(Bytes::from("publish".as_bytes()));
        frame.push_bulk(Bytes::from(self.channel.into_bytes()));
        frame.push_bulk(self.message);

        frame
    }
}
