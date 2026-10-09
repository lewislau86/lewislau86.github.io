//! 基础异步客户端，封装一条 TCP 连接上的命令编码与响应解读。
//! 普通命令顺序完成请求/响应，进入订阅后改用 Subscriber 读取推送。

use crate::cmd::{Get, Ping, Publish, Set, Subscribe, Unsubscribe};
use crate::{Connection, Frame};

use async_stream::try_stream;
use bytes::Bytes;
use std::io::{Error, ErrorKind};
use std::time::Duration;
use tokio::net::{TcpStream, ToSocketAddrs};
use tokio_stream::Stream;
use tracing::{debug, instrument};

/// 持有一条已建立连接的客户端，不提供连接池、重连或重试。
/// 通过 [`Client::connect`] 创建；命令方法的 &mut self 保证当前调用独占连接读写。
pub struct Client {
    /// 客户端 connect 得到的 socket 包装为 Connection，协议缓冲由它持有。
    /// Client 操作 Frame，不在每个命令里重新处理 TCP 半帧。
    connection: Connection,
}

/// 订阅状态的客户端。
/// Client::subscribe 消费旧 Client 并返回此类型，用可调用方法集合表达协议状态。
pub struct Subscriber {
    /// 拥有底层 Client，确保 socket 与缓冲随订阅者存活。
    client: Client,

    /// 客户端维护的频道 Vec；当前追加不去重，未必等同服务端 StreamMap 的唯一键集合。
    subscribed_channels: Vec<String>,
}

/// 一条订阅消息，包含频道名与内容；Clone 会克隆 String 和 Bytes 句柄。
#[derive(Debug, Clone)]
pub struct Message {
    pub channel: String,
    pub content: Bytes,
}

impl Client {
    /// 连接 addr；T: ToSocketAddrs 接受 Tokio 支持的地址类型，例如字符串或 SocketAddr。
    /// 泛型 T 在编译时确定，不是动态查找任意对象。
    ///
    /// # 示例
    ///
    /// ```no_run
    /// use mini_redis::clients::Client;
    ///
    /// #[tokio::main]
    /// async fn main() {
    ///     let client = match Client::connect("localhost:6379").await {
    ///         Ok(client) => client,
    ///         Err(_) => panic!("failed to establish connection"),
    ///     };
    /// # drop(client);
    /// }
    /// ```
    pub async fn connect<T: ToSocketAddrs>(addr: T) -> crate::Result<Client> {
        // 由 Tokio 解析地址并尝试建连；域名解析或 TCP 错误都经 await? 返回调用方。
        let socket = TcpStream::connect(addr).await?;

        // 接管 socket，创建协议读取及写入缓冲。
        let connection = Connection::new(socket);

        Ok(Client { connection })
    }

    /// 发送 PING；无参数返回 PONG，有参数返回回显字节。
    /// 这里只检查当前命令往返，不证明数据库全部能力正常。
    ///
    /// # 示例
    ///
    /// ```no_run
    /// use mini_redis::clients::Client;
    ///
    /// #[tokio::main]
    /// async fn main() {
    ///     let mut client = Client::connect("localhost:6379").await.unwrap();
    ///
    ///     let pong = client.ping(None).await.unwrap();
    ///     assert_eq!(b"PONG", &pong[..]);
    /// }
    /// ```
    #[instrument(skip(self))]
    pub async fn ping(&mut self, msg: Option<Bytes>) -> crate::Result<Bytes> {
        let frame = Ping::new(msg).into_frame();
        debug!(request = ?frame);
        self.connection.write_frame(&frame).await?;

        match self.read_response().await? {
            Frame::Simple(value) => Ok(value.into()),
            Frame::Bulk(value) => Ok(value),
            frame => Err(frame.to_error()),
        }
    }

    /// 读取键；Ok(None) 表示服务端回复 Null，Err 才表示命令失败。
    ///
    /// # 示例
    ///
    /// ```no_run
    /// use mini_redis::clients::Client;
    ///
    /// #[tokio::main]
    /// async fn main() {
    ///     let mut client = Client::connect("localhost:6379").await.unwrap();
    ///
    ///     let val = client.get("foo").await.unwrap();
    ///     println!("Got = {:?}", val);
    /// }
    /// ```
    #[instrument(skip(self))]
    pub async fn get(&mut self, key: &str) -> crate::Result<Option<Bytes>> {
        // Get::new 保存 key，再由 into_frame 生成请求数组；此处没有访问服务端 Db。
        let frame = Get::new(key).into_frame();

        debug!(request = ?frame);

        // 完整编码并 flush 请求；&frame 是共享借用，发送期间帧仍归本方法拥有。
        self.connection.write_frame(&frame).await?;

        // 等待一帧并解读业务结果；接受 Simple/Bulk，Null 转为 None，其他帧类型报错。
        match self.read_response().await? {
            Frame::Simple(value) => Ok(Some(value.into())),
            Frame::Bulk(value) => Ok(Some(value)),
            Frame::Null => Ok(None),
            frame => Err(frame.to_error()),
        }
    }

    /// 覆盖键值并移除旧 TTL；成功要求收到服务端 OK。
    /// 响应失败时不能断定写入没有发生，因为服务端先写 Db 再回包。
    ///
    /// # 示例
    ///
    /// ```no_run
    /// use mini_redis::clients::Client;
    ///
    /// #[tokio::main]
    /// async fn main() {
    ///     let mut client = Client::connect("localhost:6379").await.unwrap();
    ///
    ///     client.set("foo", "bar".into()).await.unwrap();
    ///
    ///     // 立即读取通常可以看到刚写入的值；仍取决于 TTL 和调度。
    ///     let val = client.get("foo").await.unwrap().unwrap();
    ///     assert_eq!(val, "bar");
    /// }
    /// ```
    #[instrument(skip(self))]
    pub async fn set(&mut self, key: &str, value: Bytes) -> crate::Result<()> {
        // 不带 TTL 的 Set 交给公共 set_cmd；最后无分号的 await 表达式直接成为返回值。
        self.set_cmd(Set::new(key, value, None)).await
    }

    /// 覆盖键值并设置相对 TTL。
    /// 服务端把时长换成 Instant 并由后台清理；精确时刻的观察受调度影响。
    /// 示例中的 sleep 不是稳定的清理完成屏障，实际验证宜等待有上界的可观察条件。
    ///
    /// # 示例
    ///
    /// ```no_run
    /// use mini_redis::clients::Client;
    /// use tokio::time;
    /// use std::time::Duration;
    ///
    /// #[tokio::main]
    /// async fn main() {
    ///     let ttl = Duration::from_millis(500);
    ///     let mut client = Client::connect("localhost:6379").await.unwrap();
    ///
    ///     client.set_expires("foo", "bar".into(), ttl).await.unwrap();
    ///
    ///     // 立即读取通常可以看到刚写入的值；仍取决于 TTL 和调度。
    ///     let val = client.get("foo").await.unwrap().unwrap();
    ///     assert_eq!(val, "bar");
    ///
    ///     // 等待 TTL；固定 sleep 不保证后台清理已经完成。
    ///     time::sleep(ttl).await;
    ///
    ///     let val = client.get("foo").await.unwrap();
    ///     assert!(val.is_some());
    /// }
    /// ```
    #[instrument(skip(self))]
    pub async fn set_expires(
        &mut self,
        key: &str,
        value: Bytes,
        expiration: Duration,
    ) -> crate::Result<()> {
        // Some(expiration) 表示携带 TTL，编码和响应检查仍由 set_cmd 共用。
        self.set_cmd(Set::new(key, value, Some(expiration))).await
    }

    /// set 与 set_expires 共用的 SET 往返实现。
    async fn set_cmd(&mut self, cmd: Set) -> crate::Result<()> {
        // 消费 cmd 并编码；into_frame 的 self 接收者表示所有权转移。
        let frame = cmd.into_frame();

        debug!(request = ?frame);

        // 写入完整请求，网络错误提前返回；这里没有自动重试。
        self.connection.write_frame(&frame).await?;

        // 只接受 Simple OK；模式守卫 if response == "OK" 进一步限制匹配内容。
        match self.read_response().await? {
            Frame::Simple(response) if response == "OK" => Ok(()),
            frame => Err(frame.to_error()),
        }
    }

    /// 向频道发布消息，返回当前接收者数量。
    /// 订阅者可在收到前断开或因落后丢消息，因此返回数量不是消费成功数。
    ///
    /// # 示例
    ///
    /// ```no_run
    /// use mini_redis::clients::Client;
    ///
    /// #[tokio::main]
    /// async fn main() {
    ///     let mut client = Client::connect("localhost:6379").await.unwrap();
    ///
    ///     let val = client.publish("foo", "bar".into()).await.unwrap();
    ///     println!("Got = {:?}", val);
    /// }
    /// ```
    #[instrument(skip(self))]
    pub async fn publish(&mut self, channel: &str, message: Bytes) -> crate::Result<u64> {
        // 构造发布请求，将 message 移进命令再移进 Frame。
        let frame = Publish::new(channel, message).into_frame();

        debug!(request = ?frame);

        // 发送请求，等待缓冲刷新。
        self.connection.write_frame(&frame).await?;

        // 期待 Integer 数量，意外帧转为错误。
        match self.read_response().await? {
            Frame::Integer(response) => Ok(response),
            frame => Err(frame.to_error()),
        }
    }

    /// 消费 Client 并进入订阅模式，返回 Subscriber 管理频道和消息。
    /// self 按值移动，原 Client 变量之后不能再调用普通命令。
    #[instrument(skip(self))]
    pub async fn subscribe(mut self, channels: Vec<String>) -> crate::Result<Subscriber> {
        // 等待每个初始频道的订阅确认，再建立本地订阅状态。
        self.subscribe_cmd(&channels).await?;

        // 把 Client 和频道 Vec 移入返回值；并没有重新建立 TCP 连接。
        Ok(Subscriber {
            client: self,
            subscribed_channels: channels,
        })
    }

    /// 初始订阅与追加订阅共用的发送/确认流程。
    async fn subscribe_cmd(&mut self, channels: &[String]) -> crate::Result<()> {
        // to_vec 克隆借用切片中的 String，让命令拥有独立频道列表。
        let frame = Subscribe::new(channels.to_vec()).into_frame();

        debug!(request = ?frame);

        // 写出 subscribe 数组。
        self.connection.write_frame(&frame).await?;

        // 每个请求频道应有一条确认；当前逻辑按顺序等待，没有统一分派交错推送。
        for channel in channels {
            // 读取下一帧，Error 响应会先由 read_response 转成 Err。
            let response = self.read_response().await?;

            // 验证 subscribe 标记与频道名；其他格式返回意外帧错误。
            match response {
                Frame::Array(ref frame) => match frame.as_slice() {
                    // 确认数组含 subscribe、频道和订阅数量。
                    // 切片模式的 .. 忽略剩余项，守卫只校验前两项，因此这里没有严格检查第三项计数类型。
                    [subscribe, schannel, ..]
                        if *subscribe == "subscribe" && *schannel == channel => {}
                    _ => return Err(response.to_error()),
                },
                frame => return Err(frame.to_error()),
            };
        }

        Ok(())
    }

    /// 读取命令响应；Error 帧转 Rust Err，EOF 也作为异常返回。
    async fn read_response(&mut self) -> crate::Result<Frame> {
        let response = self.connection.read_frame().await?;

        debug!(?response);

        match response {
            // 服务端能成功写出 Error 帧，但客户端仍应把它解释为失败。
            Some(Frame::Error(msg)) => Err(msg.into()),
            Some(frame) => Ok(frame),
            None => {
                // 等待命令响应期间 EOF 不符合预期，包装为 ConnectionReset；没有生成业务空值。
                let err = Error::new(ErrorKind::ConnectionReset, "connection reset by server");

                Err(err.into())
            }
        }
    }
}

impl Subscriber {
    /// 借用本地频道列表，不去服务端查询。
    pub fn get_subscribed(&self) -> &[String] {
        &self.subscribed_channels
    }

    /// 等待下一条 message；EOF 为 Ok(None)。
    /// 当前内容经过 Frame::to_string 再转 Bytes，非 UTF-8 消息可能改变，不能宣称二进制无损。
    pub async fn next_message(&mut self) -> crate::Result<Option<Message>> {
        match self.client.connection.read_frame().await? {
            Some(mframe) => {
                debug!(?mframe);

                match mframe {
                    Frame::Array(ref frame) => match frame.as_slice() {
                        [message, channel, content] if *message == "message" => Ok(Some(Message {
                            channel: channel.to_string(),
                            // 当前先做 Display 再转字节；二进制内容可能变成调试文本。
                            content: Bytes::from(content.to_string()),
                        })),
                        _ => Err(mframe.to_error()),
                    },
                    frame => Err(frame.to_error()),
                }
            }
            None => Ok(None),
        }
    }

    /// 消费 Subscriber 并返回匿名 Stream，Item 是 `Result<Message>`。
    /// impl Stream 隐藏单一具体实现；通过 async-stream 宏适配，避免在这里手写 poll_next 状态机。
    pub fn into_stream(mut self) -> impl Stream<Item = crate::Result<Message>> {
        // try_stream! 中 yield 产出成功元素，? 将读取错误变成流的错误项并结束流。
        // 创建流并不自动读取，消费者轮询时才推进其中的 await。
        try_stream! {
            while let Some(message) = self.next_message().await? {
                yield message;
            }
        }
    }

    /// 追加频道；需要先收到确认再更新本地记录。
    #[instrument(skip(self))]
    pub async fn subscribe(&mut self, channels: &[String]) -> crate::Result<()> {
        // 复用 Client 的确认流程；若推送插在确认之间，当前匹配可能报错。
        self.client.subscribe_cmd(channels).await?;

        // extend 追加克隆的 String，当前不去重；重复频道可能与服务端计数不一致。
        self.subscribed_channels
            .extend(channels.iter().map(Clone::clone));

        Ok(())
    }

    /// 取消频道，空切片表示取消全部；完成后只更新当前 Subscriber 的本地列表。
    #[instrument(skip(self))]
    pub async fn unsubscribe(&mut self, channels: &[String]) -> crate::Result<()> {
        let frame = Unsubscribe::new(channels).into_frame();

        debug!(request = ?frame);

        // 发送取消请求，仍使用相同 TCP 连接。
        self.client.connection.write_frame(&frame).await?;

        // 空列表时根据本地订阅数量等待确认；非空时按请求频道数量等待。
        let num = if channels.is_empty() {
            self.subscribed_channels.len()
        } else {
            channels.len()
        };

        // 逐条读取预期的取消确认；此流程也没有把交错 message 单独分派出去。
        for _ in 0..num {
            let response = self.client.read_response().await?;

            match response {
                Frame::Array(ref frame) => match frame.as_slice() {
                    [unsubscribe, channel, ..] if *unsubscribe == "unsubscribe" => {
                        let len = self.subscribed_channels.len();

                        if len == 0 {
                            // 在删除本地项之前要求列表非空，避免不合理确认导致计数下溢。
                            return Err(response.to_error());
                        }

                        // retain 删除与确认频道相同的所有本地项；闭包接收每个元素的借用。
                        self.subscribed_channels.retain(|c| *channel != &c[..]);

                        // 期望列表恰好少一项；重复频道记录会使这个假设失败。
                        if self.subscribed_channels.len() != len - 1 {
                            return Err(response.to_error());
                        }
                    }
                    _ => return Err(response.to_error()),
                },
                frame => return Err(frame.to_error()),
            };
        }

        Ok(())
    }
}
