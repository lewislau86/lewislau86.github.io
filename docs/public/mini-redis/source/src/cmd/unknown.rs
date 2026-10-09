use crate::{Connection, Frame};

use tracing::{debug, instrument};

/// 未知或当前模式不允许的命令表示；不是一个真实 Redis 命令名。
#[derive(Debug)]
pub struct Unknown {
    command_name: String,
}

impl Unknown {
    /// 保存原命令名，等待 apply 生成错误响应。
    pub(crate) fn new(key: impl ToString) -> Unknown {
        Unknown {
            command_name: key.to_string(),
        }
    }

    /// 借用命令名称，用于统一分派日志等场景。
    pub(crate) fn get_name(&self) -> &str {
        &self.command_name
    }

    /// 写一个 Error 帧说明不识别该操作。
    /// 成功写出后返回 Ok，使服务端可继续读；客户端收到 Error 帧再转为自己的 Err。
    #[instrument(skip(self, dst))]
    pub(crate) async fn apply(self, dst: &mut Connection) -> crate::Result<()> {
        let response = Frame::Error(format!("ERR unknown command '{}'", self.command_name));

        debug!(?response);

        dst.write_frame(&response).await?;
        Ok(())
    }
}
