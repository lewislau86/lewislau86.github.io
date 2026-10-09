//! 实验辅助设施：临时端口、受控停机与总等待上限。
use std::net::SocketAddr;
use tokio::net::TcpListener;
use tokio::sync::oneshot;
use tokio::task::JoinHandle;
use tokio::time::{timeout, Duration};

pub struct Server {
    pub addr: SocketAddr,
    stop: oneshot::Sender<()>,
    task: JoinHandle<()>,
}

impl Server {
    pub async fn start() -> mini_redis::Result<Self> {
        // 0 让系统分配空闲端口，不接触默认 6379 上的服务。
        let listener = TcpListener::bind("127.0.0.1:0").await?;
        let addr = listener.local_addr()?;
        let (stop, stopped) = oneshot::channel();
        let task = tokio::spawn(async move {
            mini_redis::server::run(listener, async {
                let _ = stopped.await;
            })
            .await;
        });
        Ok(Self { addr, stop, task })
    }

    pub async fn stop(self) -> mini_redis::Result<()> {
        let _ = self.stop.send(());
        timeout(Duration::from_secs(3), self.task).await??;
        Ok(())
    }
}
