use crate::cmd::{Parse, ParseError};
use crate::{Connection, Db, Frame};

use bytes::Bytes;
use std::time::Duration;
use tracing::{debug, instrument};

/// 覆盖键值并替换旧 TTL。值为 Bytes，可以保存非 UTF-8 内容。
///
/// # 支持的选项
///
/// * EX 秒数：按秒指定相对过期时间。
/// * PX 毫秒数：按毫秒指定相对过期时间。
///
/// 未实现完整 Redis 的 NX/XX 等选项；这些限制以 parse_frames 为准。
#[derive(Debug)]
pub struct Set {
    /// 拥有的键名。
    key: String,

    /// 要写入的 Bytes；移动句柄不等于复制所有字节。
    value: Bytes,

    /// 可选相对时长；绝对 Instant 在 Db::set 中计算。
    expire: Option<Duration>,
}

impl Set {
    /// 构造拥有参数的 Set；impl ToString 是参数位置的 trait 约束。
    /// Some(Duration) 附带 TTL，None 表示本次写入没有 TTL。
    pub fn new(key: impl ToString, value: Bytes, expire: Option<Duration>) -> Set {
        Set {
            key: key.to_string(),
            value,
            expire,
        }
    }

    /// 借用 key 的 str 视图，避免复制 String。
    pub fn key(&self) -> &str {
        &self.key
    }

    /// 借用 Bytes 句柄，不移出命令的值。
    pub fn value(&self) -> &Bytes {
        &self.value
    }

    /// `Option<Duration>` 实现 Copy，可以按值返回而不移动 self。
    pub fn expire(&self) -> Option<Duration> {
        self.expire
    }

    /// 服务端参数解析入口；SET 名称已经由 Command 取走。
    /// 先读取必需 key/value，再尝试读取可选 EX/PX；外层 finish 检查剩余项。
    /// 完整请求格式如下。
    ///
    /// ```text
    /// SET key value [EX seconds|PX milliseconds]
    /// ```
    pub(crate) fn parse_frames(parse: &mut Parse) -> crate::Result<Set> {
        use ParseError::EndOfStream;

        // 必需键名；参数缺失和非 UTF-8 都使解析失败。
        let key = parse.next_string()?;

        // 必需值，按原始字节读取。
        let value = parse.next_bytes()?;

        // 缺省无 TTL；类型可从后面的 Some(Duration) 推断出来。
        let mut expire = None;

        // 尝试读取选项名；match 分别处理成功、合法结束和真正错误。
        match parse.next_string() {
            Ok(s) if s.to_uppercase() == "EX" => {
                // 匹配 EX 后必须再读整数，转换为秒时长。
                let secs = parse.next_int()?;
                expire = Some(Duration::from_secs(secs));
            }
            Ok(s) if s.to_uppercase() == "PX" => {
                // 匹配 PX 后必须再读整数，转换为毫秒时长。
                let ms = parse.next_int()?;
                expire = Some(Duration::from_millis(ms));
            }
            // 其他选项尚未实现；Err 经 Handler 传播会结束此连接，其他连接不受影响。
            Ok(_) => return Err("currently `SET` only supports the expiration option".into()),
            // 仅在可选项起点，EndOfStream 表示没有选项；空块表示正常继续。
            Err(EndOfStream) => {}
            // 保留真实错误，Into 将 ParseError 转换为库统一错误类型。
            Err(err) => return Err(err.into()),
        }

        Ok(Set { key, value, expire })
    }

    /// 服务端执行入口：先更新 Db，再写 OK；两者不是一个可回滚事务。
    /// instrument 是 tracing 属性宏，skip 避免自动记录这些参数。
    #[instrument(skip(self, db, dst))]
    pub(crate) async fn apply(self, db: &Db, dst: &mut Connection) -> crate::Result<()> {
        // self 按值传入，因此可把 key/value 移入 Db；返回时写入已发生。
        db.set(self.key, self.value, self.expire);

        // 构造 Simple OK 后 await 写回；失败不会撤销前面的数据库更新。
        let response = Frame::Simple("OK".to_string());
        debug!(?response);
        dst.write_frame(&response).await?;

        Ok(())
    }

    /// 客户端编码方向：消费 Set，产生 [set, key, value, 可选 px, 毫秒数]。
    pub(crate) fn into_frame(self) -> Frame {
        let mut frame = Frame::array();
        frame.push_bulk(Bytes::from("set".as_bytes()));
        frame.push_bulk(Bytes::from(self.key.into_bytes()));
        frame.push_bulk(self.value);
        if let Some(ms) = self.expire {
            // 协议接受 EX 秒和 PX 毫秒；客户端统一选择 PX。
            // as_millis 返回整数毫秒，不足一毫秒的部分会被舍去。
            frame.push_bulk(Bytes::from("px".as_bytes()));
            frame.push_bulk(Bytes::from(ms.as_millis().to_string()));
        }
        frame
    }
}
