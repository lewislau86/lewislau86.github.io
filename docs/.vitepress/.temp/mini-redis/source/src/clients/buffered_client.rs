use crate::clients::Client;
use crate::Result;

use bytes::Bytes;
use tokio::sync::mpsc::{channel, Receiver, Sender};
use tokio::sync::oneshot;

// 队列内部命令枚举，仅有 Get/Set；不是服务端 cmd::Command。
#[derive(Debug)]
enum Command {
    Get(String),
    Set(String, Bytes),
}

// 队列消息包含工作内容及该请求独享的回复地址。
// oneshot 只发送一次结果；统一 Result<Option<Bytes>> 让 GET 返回值、SET 返回 None。
type Message = (Command, oneshot::Sender<Result<Option<Bytes>>>);

/// 后台唯一拥有 Client 的消费者；逐条执行完整往返，再用 oneshot 回信。
async fn run(mut client: Client, mut rx: Receiver<Message>) {
    // recv 的 None 表示所有 Sender 都释放且队列已耗尽，不会再有新工作。
    while let Some((cmd, tx)) = rx.recv().await {
        // 此处串行 await，避免多个调用者竞争读取同一条连接上的响应。
        let response = match cmd {
            Command::Get(key) => client.get(&key).await,
            Command::Set(key, value) => client.set(&key, value).await.map(|_| None),
        };

        // 调用者取消等待会释放接收端，send 失败属于允许的情况。
        // 忽略回信失败不会撤销已经执行的 SET。
        let _ = tx.send(response);
    }
}

// 自动派生 Clone：克隆字段 Sender，所有句柄仍指向同一队列。
#[derive(Clone)]
pub struct BufferedClient {
    tx: Sender<Message>,
}

impl BufferedClient {
    /// 把 Client 移交给后台任务，返回可克隆的队列入口。
    ///
    /// 基础 Client 的方法需要 &mut self，一次独占完成一个请求/响应。这里用消息传递
    /// 让多个任务安全共享一条连接；Clone 复制的是 Sender 句柄，不是 TCP 连接池。
    pub fn buffer(client: Client) -> BufferedClient {
        // 容量 32 限制待处理消息；满时 send().await 等待，形成背压。
        let (tx, rx) = channel(32);

        // async move 接管 client 和 rx；spawn 要求捕获状态不借用即将失效的调用者局部变量。
        tokio::spawn(async move { run(client, rx).await });

        // 只把 Sender 交给业务调用者，Receiver 和 Client 留在后台。
        BufferedClient { tx }
    }

    /// 入队读取请求，再等待该请求自己的回复；返回类型与 Client::get 一致。
    pub async fn get(&mut self, key: &str) -> Result<Option<Bytes>> {
        // 把借用 key 转成拥有的 String，消息跨任务后不依赖原切片。
        let get = Command::Get(key.into());

        // 每个请求建立独立 oneshot，以区分不同调用者的返回结果。
        let (tx, rx) = oneshot::channel();

        // 第一处等待：将请求和回复 Sender 入队；队列满时等待可用容量。
        self.tx.send((get, tx)).await?;

        // 第二处等待：取得网络操作结果；外层通道错误与内层业务错误要分别处理。
        match rx.await {
            Ok(res) => res,
            Err(err) => Err(err.into()),
        }
    }

    /// 入队写请求并等待执行结果；队列顺序不等于并行请求。
    pub async fn set(&mut self, key: &str, value: Bytes) -> Result<()> {
        // 移入 value 和拥有的 key，调用方不能再使用已移动的 value。
        let set = Command::Set(key.into(), value);

        // 为这次写入建立一个专属回信通道。
        let (tx, rx) = oneshot::channel();

        // 发送工作；成功入队不代表 SET 已成功执行。
        self.tx.send((set, tx)).await?;

        // 等待后台回信；网络错误被保留，成功的统一 None 映射回 unit。
        match rx.await {
            Ok(res) => res.map(|_| ()),
            Err(err) => Err(err.into()),
        }
    }
}
