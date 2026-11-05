use crate::{Connection, Db, Frame, Parse};

use bytes::Bytes;
use tracing::{debug, instrument};

/// 读取键值；不存在时返回 Null。
/// 本实现只保存 Bytes，没有其他 Redis 数据类型，也没有这里的类型冲突分支。
#[derive(Debug)]
pub struct Get {
    /// 拥有键名 String，命令不依赖网络读缓冲继续存活。
    key: String,
}

impl Get {
    /// impl ToString 接受任意实现该 trait 的具体类型；to_string 生成命令自己持有的键。
    pub fn new(key: impl ToString) -> Get {
        Get {
            key: key.to_string(),
        }
    }

    /// 返回借用的 &str，不移动或复制内部 String；借用不能超过 self 的有效期。
    pub fn key(&self) -> &str {
        &self.key
    }

    /// 从已收齐的命令数组读取参数。
    /// GET 名称已由 Command 消费，当前位置应是 key；缺失或类型不符返回 Err。
    /// 外层 Command 在成功后调用 finish，拒绝多余参数。下面给出完整请求格式。
    ///
    /// ```text
    /// GET key
    /// ```
    pub(crate) fn parse_frames(parse: &mut Parse) -> crate::Result<Get> {
        // 读取必需的 UTF-8 键名；? 会把参数读取失败返回到分派器。
        let key = parse.next_string()?;

        Ok(Get { key })
    }

    /// 由 Command::apply 调用：读共享 Db，将响应写回当前 Connection。
    /// self 按值传入，执行结束后该命令被消费。
    #[instrument(skip(self, db, dst))]
    pub(crate) async fn apply(self, db: &Db, dst: &mut Connection) -> crate::Result<()> {
        // 取得 Bytes 克隆；Db 的锁在 get 返回时已释放。
        let response = if let Some(value) = db.get(&self.key) {
            // 存在时生成 Bulk，直接持有 Bytes。
            Frame::Bulk(value)
        } else {
            // 不存在时生成协议 Null；这不是连接 EOF。
            Frame::Null
        };

        debug!(?response);

        // await 发送响应期间不持有数据库 MutexGuard。
        dst.write_frame(&response).await?;

        Ok(())
    }

    /// 客户端调用的编码方向：消费 Get，构造 [get, key] 数组。
    /// 它不读数据库；服务端解析后才会执行 apply。
    pub(crate) fn into_frame(self) -> Frame {
        let mut frame = Frame::array();
        frame.push_bulk(Bytes::from("get".as_bytes()));
        frame.push_bulk(Bytes::from(self.key.into_bytes()));
        frame
    }
}
