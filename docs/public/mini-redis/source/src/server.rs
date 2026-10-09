//! 服务生命周期的协调入口。
//!
//! server::run 管理监听与退出，Listener::run 接入连接，Handler::run 处理一条连接。
//! 三个 run 分属模块或不同 impl，不是一个函数；每连接任务共享同一 Db。

use crate::{Command, Connection, Db, DbDropGuard, Shutdown};

use std::future::Future;
use std::sync::Arc;
use tokio::net::{TcpListener, TcpStream};
use tokio::sync::{broadcast, mpsc, Semaphore};
use tokio::time::{self, Duration};
use tracing::{debug, error, info, instrument};

/// 接入循环的状态，由模块级 run 构造。字段持有资源，方法负责驱动生命周期。
#[derive(Debug)]
struct Listener {
    /// 共享数据库的守卫；db() 克隆 Arc 句柄给各 Handler，守卫析构时通知过期任务停止。
    db_holder: DbDropGuard,

    /// 从 binary 或测试传入的监听器；绑定地址在调用方决定。
    listener: TcpListener,

    /// 连接配额；accept 之前等待许可，连接任务结束时释放许可。
    /// Arc 允许 owned permit 与接入循环共享同一个 Semaphore。
    limit_connections: Arc<Semaphore>,

    /// 停止广播的发送端。外部 Future 完成后，run 通过 drop 此 Sender 关闭通道，
    /// 各 Handler 的 Shutdown::recv 因通道关闭而醒来；此实现没有发送一条 ()。
    notify_shutdown: broadcast::Sender<()>,

    /// 用于等待所有连接任务释放资源的完成通道。
    /// 不发送业务消息，只由每个 Handler 保留 Sender 克隆；最后一个 Sender 释放后 recv 得到 None。
    shutdown_complete_tx: mpsc::Sender<()>,
}

/// 每条连接的状态：循环读 Frame，再分派命令；错误只结束这条连接的任务。
#[derive(Debug)]
struct Handler {
    /// 共享数据库访问句柄；GET/SET 使用它，PING 等命令不一定访问 Db。
    db: Db,

    /// 独占当前 socket 与读写缓冲；在帧层处理请求，不在这里手写字节解析。
    connection: Connection,

    /// 该连接的停止接收器；普通读循环与订阅循环分别等待它。
    /// 当前已开始的响应写不处于外层 select 内，所以停机并没有统一时限保证。
    shutdown: Shutdown,

    /// 字段名的前导下划线只抑制未使用警告，值仍真实存活。
    /// Handler 析构时它被释放；若写成临时 _ 直接丢弃，就无法跟踪连接完成。
    _shutdown_complete: mpsc::Sender<()>,
}

/// 硬编码的连接配额上限；达到上限后暂停 accept，直到已有任务归还许可。
/// 实际服务可做成配置，但此值不是吞吐或性能保证。
const MAX_CONNECTIONS: usize = 250;

/// 运行服务，直到接入循环失败或 shutdown Future 完成，再通知并等待连接结束。
///
/// impl Future 接受具体类型由调用方决定的 Future，例如 ctrl_c 或受控停止信号。
/// 这里不约束 Future::Output，select 的 _ 会忽略其结果，所以完成不必等于成功。
pub async fn run(listener: TcpListener, shutdown: impl Future) {
    // 创建停止广播并丢弃初始 Receiver；每个 Handler 用 subscribe 创建自己的接收端。
    // mpsc 是另一条完成通道，不要把“通知退出”和“确认全部退出”混为一谈。
    let (notify_shutdown, _) = broadcast::channel(1);
    let (shutdown_complete_tx, mut shutdown_complete_rx) = mpsc::channel(1);

    // 字段简写 listener 等同于 listener: listener，资源所有权移入 Listener。
    let mut server = Listener {
        listener,
        db_holder: DbDropGuard::new(),
        limit_connections: Arc::new(Semaphore::new(MAX_CONNECTIONS)),
        notify_shutdown,
        shutdown_complete_tx,
    };

    // select 在当前任务中并发轮询接入循环与停止 Future；一个分支完成后执行其分支体。
    // 另一个等待 Future 被丢弃，不代表它此前的副作用被回滚。
    // 写法为：结果模式 = 异步表达式 => 分支体；并发等待不等于创建两个线程。
    tokio::select! {
        res = server.run() => {
            // 这里只接收连续 accept 失败；独立 Handler 的错误已在 spawn 闭包里记录，不会冒泡到这里。
            if let Err(err) = res {
                error!(cause = %err, "failed to accept");
            }
        }
        _ = shutdown => {
            // 停止 Future 已完成；其输出被 _ 丢弃，包括可能的信号注册错误。
            info!("shutting down");
        }
    }

    // 解构并移出两个 Sender，.. 忽略其余字段。
    // 显式释放本地 Sender，避免下面把自己也算作尚未完成的持有者而一直等待。
    let Listener {
        shutdown_complete_tx,
        notify_shutdown,
        ..
    } = server;

    // 关闭广播，所有现有 Receiver 的 recv 将完成并触发各连接停止。
    drop(notify_shutdown);
    // 释放接入方的完成 Sender，剩余克隆由 Handler 持有。
    drop(shutdown_complete_tx);

    // 等待所有 Handler 释放完成 Sender，随后 recv 返回 None。
    // 这不包含显式 join 过期清理任务，后者由 DbDropGuard 另行通知。
    let _ = shutdown_complete_rx.recv().await;
}

impl Listener {
    /// 持续接入连接，每条连接 spawn 一个任务。
    ///
    /// # 错误
    ///
    /// accept 的临时失败先做指数退避，重试仍失败时返回 Err 到外层服务协调者。
    async fn run(&mut self) -> crate::Result<()> {
        info!("accepting inbound connections");

        loop {
            // acquire_owned 等待一个拥有自身生命周期的许可，适合移入 spawn。
            // 许可 Drop 时归还；这里从不 close 信号量，因此 unwrap 依赖这一约定。
            let permit = self
                .limit_connections
                .clone()
                .acquire_owned()
                .await
                .unwrap();

            // accept 内部已退避重试；返回 Err 时退出接入循环。
            let socket = self.accept().await?;

            // 为新连接构造独立状态，但数据库仍指向同一份 Arc。
            let mut handler = Handler {
                // 从守卫克隆共享 Db 句柄。
                db: self.db_holder.db(),

                // 把 socket 移进 Connection，创建此连接专属缓冲。
                connection: Connection::new(socket),

                // 从同一停止 Sender 派生独立 Receiver。
                shutdown: Shutdown::new(self.notify_shutdown.subscribe()),

                // 保留完成 Sender 克隆，作为连接仍未结束的标记。
                _shutdown_complete: self.shutdown_complete_tx.clone(),
            };

            // async move 将 handler 与 permit 捕获到 Future 中，spawn 将它交给 runtime。
            // 任务可能在线程间调度，因此持有的跨等待状态须满足 Send；不能借用短命局部变量。
            tokio::spawn(async move {
                // Handler 返回后只记录本连接错误，其他连接仍可继续。
                if let Err(err) = handler.run().await {
                    error!(cause = ?err, "connection error");
                }
                // 显式释放许可；它必须活到 handler.run 完成，才能准确限制连接数量。
                drop(permit);
            });
        }
    }

    /// 接入失败按 1、2、4、8、16、32、64 秒等待后重试。
    /// 随后再失败时 backoff 已大于 64，返回错误；不把每次网络故障立刻当全局退出。
    async fn accept(&mut self) -> crate::Result<TcpStream> {
        let mut backoff = 1;

        // 循环重试；只有接受成功或退避耗尽才返回。
        loop {
            // accept 返回 (socket, 对端地址)，_ 表示本实现不使用地址。
            match self.listener.accept().await {
                Ok((socket, _)) => return Ok(socket),
                Err(err) => {
                    if backoff > 64 {
                        // 退避次数耗尽，将 I/O 错误转换为库错误并返回。
                        return Err(err.into());
                    }
                }
            }

            // 异步 sleep 让出当前任务，不阻塞 runtime 线程等待计时。
            time::sleep(Duration::from_secs(backoff)).await;

            // 下次失败等待时间加倍。
            backoff *= 2;
        }
    }
}

impl Handler {
    /// 处理一条连接：读帧、解析命令、执行并写响应，然后继续读取。
    ///
    /// 本实现逐条执行；客户端可以连续发送请求，缓冲会保留后续帧，但此处没有并行执行命令。
    /// 订阅 apply 会接管连接读取。普通命令执行期间的写等待不受下面读帧 select 直接取消。
    #[instrument(skip(self))]
    async fn run(&mut self) -> crate::Result<()> {
        // 只在未观察到停止时尝试读取下一条请求。
        while !self.shutdown.is_shutdown() {
            // 同时等待完整帧与停止通知；? 使读取错误直接返回当前 Handler。
            let maybe_frame = tokio::select! {
                res = self.connection.read_frame() => res?,
                _ = self.shutdown.recv() => {
                    // 返回到 spawn 闭包，随后释放 Handler 及其完成 Sender。
                    return Ok(());
                }
            };

            // read_frame 的 None 表示正常 EOF，没有下一条请求；与 GET 空值 Frame::Null 不同。
            let frame = match maybe_frame {
                Some(frame) => frame,
                None => return Ok(()),
            };

            // 已知命令参数非法会 Err；未知命令则被包装为 Unknown，执行时写 Error 帧。
            let cmd = Command::from_frame(frame)?;

            // tracing 的 ?cmd 用 Debug 格式记录名为 cmd 的结构化字段。
            debug!(?cmd);

            // 把 Db 的共享借用、当前 Connection/Shutdown 的可变借用交给命令。
            // apply 可能更新内存并写回复；Subscribe 会持续推送多帧，而非马上返回外层循环。
            cmd.apply(&self.db, &mut self.connection, &mut self.shutdown)
                .await?;
        }

        Ok(())
    }
}
