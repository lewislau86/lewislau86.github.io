use tokio::sync::broadcast;

/// 封装当前连接的停止接收器与已停止标记。
///
/// server::run 通过释放最后一个 broadcast Sender 关闭通道；recv 因关闭而完成即可触发停止。
/// 调用者仍需从 Handler 或 Subscribe 循环返回，才会释放连接。这里不负责等待所有任务退出。
#[derive(Debug)]
pub(crate) struct Shutdown {
    /// 只有 recv 观察到停止后才设为 true；不是自动跟随通道变化的变量。
    is_shutdown: bool,

    /// 停止通道的接收端；() 是单元类型，本项目主要使用通道关闭这一事件。
    notify: broadcast::Receiver<()>,
}

impl Shutdown {
    /// 接管 Receiver 的所有权，为一个连接建立停止状态。
    pub(crate) fn new(notify: broadcast::Receiver<()>) -> Shutdown {
        Shutdown {
            is_shutdown: false,
            notify,
        }
    }

    /// 同步查询本地标记，不会等待或主动读取通知。
    pub(crate) fn is_shutdown(&self) -> bool {
        self.is_shutdown
    }

    /// 首次调用等待停止；一旦记住停止，后续调用立即返回。
    pub(crate) async fn recv(&mut self) {
        // 已观察到停止就直接返回，避免重复等待。
        if self.is_shutdown {
            return;
        }

        // 故意忽略 recv 的 Result：收到值或通道关闭都按停止处理。
        // 当前服务通过关闭发送端通知，不依赖发送一条 ()。
        let _ = self.notify.recv().await;

        // 记录停止状态，供 Handler 循环的下一次判断使用。
        self.is_shutdown = true;
    }
}
