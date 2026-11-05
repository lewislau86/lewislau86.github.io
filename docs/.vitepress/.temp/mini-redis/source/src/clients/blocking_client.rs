//! 同步客户端适配器：内部保留异步 Client 和 current_thread runtime。
//! 每次 block_on 驱动一次异步调用，同步调用线程会等到结果返回。

use bytes::Bytes;
use std::time::Duration;
use tokio::net::ToSocketAddrs;
use tokio::runtime::Runtime;

pub use crate::clients::Message;

/// 一条已建立的 TCP 连接的同步包装，不提供连接池或自动重试。
/// 由 [`BlockingClient::connect`] 创建；协议实现复用异步 Client。
pub struct BlockingClient {
    /// 底层异步 Client，仍然独占一条 Connection。
    inner: crate::clients::Client,

    /// 当前线程 runtime，供同步方法 block_on 驱动 I/O；不是每次调用重新创建。
    rt: Runtime,
}

/// 订阅状态的同步包装。
/// subscribe 消费 BlockingClient，将内部 Client 转为 Subscriber，并一起移交 runtime。
/// 类型变化限制后续可调用的方法，避免继续调用普通 GET/SET。
pub struct BlockingSubscriber {
    /// 已进入订阅模式的异步客户端。
    inner: crate::clients::Subscriber,

    /// 跟随订阅者持有的 runtime，用于等待消息及确认。
    rt: Runtime,
}

/// BlockingSubscriber::into_iter 返回的具体迭代器类型，对外用 impl Iterator 隐藏。
struct SubscriberIterator {
    /// 迭代器拥有订阅者，保证 next 调用期间连接仍存在。
    inner: crate::clients::Subscriber,

    /// 迭代器保留 runtime；每次 next 同步驱动一次 next_message。
    rt: Runtime,
}

impl BlockingClient {
    /// 建立同步连接。T: ToSocketAddrs 是泛型约束，使用 Tokio 的地址 trait。
    /// Builder 创建 current_thread runtime，enable_all 开启 I/O 和时间驱动。
    /// 不应在已有异步任务中嵌套调用 block_on；异步场景优先使用 Client。
    ///
    /// # 示例
    ///
    /// ```no_run
    /// use mini_redis::clients::BlockingClient;
    ///
    /// let client = match BlockingClient::connect("localhost:6379") {
    ///     Ok(client) => client,
    ///     Err(_) => panic!("failed to establish connection"),
    /// };
    /// # drop(client);
    /// ```
    pub fn connect<T: ToSocketAddrs>(addr: T) -> crate::Result<BlockingClient> {
        let rt = tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .build()?;

        let inner = rt.block_on(crate::clients::Client::connect(addr))?;

        Ok(BlockingClient { inner, rt })
    }

    /// 同步读取键值；Result 说明成败，内部 Option 区分有值与缺失。
    ///
    /// # 示例
    ///
    /// ```no_run
    /// use mini_redis::clients::BlockingClient;
    ///
    /// let mut client = BlockingClient::connect("localhost:6379").unwrap();
    ///
    /// let val = client.get("foo").unwrap();
    /// println!("Got = {val:?}");
    /// ```
    pub fn get(&mut self, key: &str) -> crate::Result<Option<Bytes>> {
        self.rt.block_on(self.inner.get(key))
    }

    /// 同步覆盖键值，并清除旧 TTL；底层复用 Client::set 的编码与确认逻辑。
    ///
    /// # 示例
    ///
    /// ```no_run
    /// use mini_redis::clients::BlockingClient;
    ///
    /// let mut client = BlockingClient::connect("localhost:6379").unwrap();
    ///
    /// client.set("foo", "bar".into()).unwrap();
    ///
    /// // 立即读取通常可以看到刚写入的值；仍取决于 TTL 和调度。
    /// let val = client.get("foo").unwrap().unwrap();
    /// assert_eq!(val, "bar");
    /// ```
    pub fn set(&mut self, key: &str, value: Bytes) -> crate::Result<()> {
        self.rt.block_on(self.inner.set(key, value))
    }

    /// 同步写入并附带 TTL，替换旧值与旧期限。
    /// 示例包含定时等待；网络和调度使精确时刻断言不可靠，不应把 sleep 当作清理完成确认。
    ///
    /// # 示例
    ///
    /// ```no_run
    /// use mini_redis::clients::BlockingClient;
    /// use std::thread;
    /// use std::time::Duration;
    ///
    /// let ttl = Duration::from_millis(500);
    /// let mut client = BlockingClient::connect("localhost:6379").unwrap();
    ///
    /// client.set_expires("foo", "bar".into(), ttl).unwrap();
    ///
    /// // 立即读取通常可以看到刚写入的值；仍取决于 TTL 和调度。
    /// let val = client.get("foo").unwrap().unwrap();
    /// assert_eq!(val, "bar");
    ///
    /// // 等待 TTL；固定 sleep 不保证后台清理已经完成。
    /// thread::sleep(ttl);
    ///
    /// let val = client.get("foo").unwrap();
    /// assert!(val.is_none());
    /// ```
    pub fn set_expires(
        &mut self,
        key: &str,
        value: Bytes,
        expiration: Duration,
    ) -> crate::Result<()> {
        self.rt
            .block_on(self.inner.set_expires(key, value, expiration))
    }

    /// 同步发布，返回当前接收者数量；不保证这些接收者最终完成业务消费。
    ///
    /// # 示例
    ///
    /// ```no_run
    /// use mini_redis::clients::BlockingClient;
    ///
    /// let mut client = BlockingClient::connect("localhost:6379").unwrap();
    ///
    /// let val = client.publish("foo", "bar".into()).unwrap();
    /// println!("Got = {val:?}");
    /// ```
    pub fn publish(&mut self, channel: &str, message: Bytes) -> crate::Result<u64> {
        self.rt.block_on(self.inner.publish(channel, message))
    }

    /// 消费 self 并返回 BlockingSubscriber；Client 和 Runtime 都移交给新包装。
    /// 调用后原 BlockingClient 变量已被移动，不能再次用它执行 GET/SET。
    pub fn subscribe(self, channels: Vec<String>) -> crate::Result<BlockingSubscriber> {
        let subscriber = self.rt.block_on(self.inner.subscribe(channels))?;
        Ok(BlockingSubscriber {
            inner: subscriber,
            rt: self.rt,
        })
    }
}

impl BlockingSubscriber {
    /// 返回本地记录列表的切片借用，不发网络请求。
    pub fn get_subscribed(&self) -> &[String] {
        self.inner.get_subscribed()
    }

    /// 同步等待下一条消息；Ok(None) 表示 EOF，Err 表示读取或格式错误。
    pub fn next_message(&mut self) -> crate::Result<Option<Message>> {
        self.rt.block_on(self.inner.next_message())
    }

    /// 消费订阅者并返回迭代器；impl Iterator 隐藏具体类型，Item 仍是 Result<Message>。
    pub fn into_iter(self) -> impl Iterator<Item = crate::Result<Message>> {
        SubscriberIterator {
            inner: self.inner,
            rt: self.rt,
        }
    }

    /// 追加频道并等待确认，行为继承底层 Subscriber。
    pub fn subscribe(&mut self, channels: &[String]) -> crate::Result<()> {
        self.rt.block_on(self.inner.subscribe(channels))
    }

    /// 取消给定频道；空切片表示全部取消。
    pub fn unsubscribe(&mut self, channels: &[String]) -> crate::Result<()> {
        self.rt.block_on(self.inner.unsubscribe(channels))
    }
}

impl Iterator for SubscriberIterator {
    type Item = crate::Result<Message>;

    fn next(&mut self) -> Option<crate::Result<Message>> {
        // Result<Option<T>, E> → Option<Result<T, E>>：EOF 结束迭代，错误成为一个 Err 元素。
        self.rt.block_on(self.inner.next_message()).transpose()
    }
}
