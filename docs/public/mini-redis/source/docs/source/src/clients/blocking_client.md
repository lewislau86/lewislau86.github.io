# src/clients/blocking_client.rs：把异步 Client 接到同步程序

<!-- analyzes: src/clients/blocking_client.rs -->

[打开对应源码](../../../../src/clients/blocking_client.rs) · [源码文章索引](../../README.md) · [总目录](../../../README.md)

这个适配器让同步程序直接调用 get/set 而不写 await。它没有重写 RESP 协议，而是自己持有 Tokio Runtime，每次使用 block_on 驱动内部 Client。

## 它和哪些代码交互

```text
同步调用者 → BlockingClient 方法
 → Runtime::block_on → Client 异步方法 → Connection
 subscribe(self) → BlockingSubscriber
 into_iter(self) → SubscriberIterator::next → next_message
```

## 连接时创建并保留 runtime

<!-- source: src/clients/blocking_client.rs:71-79; comments omitted -->
```rust
pub fn connect<T: ToSocketAddrs>(addr: T) -> crate::Result<BlockingClient> {
    let rt = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()?;

    let inner = rt.block_on(crate::clients::Client::connect(addr))?;

    Ok(BlockingClient { inner, rt })
}
```

current_thread 调度器在调用 block_on 的线程上运行；enable_all 启用 I/O 和时间驱动。连接成功后，Client 和 Runtime 一起保存。以后每个同步方法都借用这个 runtime 来驱动异步操作，而不是每次重建 TCP 连接。

## 薄包装仍有执行上下文约束

<!-- source: src/clients/blocking_client.rs:97-99; comments omitted -->
```rust
pub fn get(&mut self, key: &str) -> crate::Result<Option<Bytes>> {
    self.rt.block_on(self.inner.get(key))
}
```

set、set_expires、publish 同样把参数交给内部 Client 并 block_on。同步线程会等待返回；这并不是非阻塞 API。不要把这些方法直接塞进已有异步任务里期待无阻塞行为；已有 Tokio 上下文通常应使用异步 Client，避免嵌套运行 runtime。

## 订阅时把 runtime 一起搬走

<!-- source: src/clients/blocking_client.rs:205-211; comments omitted -->
```rust
pub fn subscribe(self, channels: Vec<String>) -> crate::Result<BlockingSubscriber> {
    let subscriber = self.rt.block_on(self.inner.subscribe(channels))?;
    Ok(BlockingSubscriber {
        inner: subscriber,
        rt: self.rt,
    })
}
```

self 被消费，内部 Subscriber 与原 runtime 组成 BlockingSubscriber。get_subscribed 只查询本地记录；next_message、subscribe、unsubscribe 仍通过 block_on 工作。into_iter 又消费这个包装，将两份资源移进迭代器。

## Iterator 把网络结束转成迭代结束

<!-- source: src/clients/blocking_client.rs:248-254; comments omitted -->
```rust
impl Iterator for SubscriberIterator {
    type Item = crate::Result<Message>;

    fn next(&mut self) -> Option<crate::Result<Message>> {
        self.rt.block_on(self.inner.next_message()).transpose()
    }
}
```

transpose 将 Result<Option<Message>> 变成 Option<Result<Message>>：有消息是 Some(Ok)，EOF 是 None，读取错误是 Some(Err)。所以 for 循环中的元素仍要处理错误，不能以为同步接口消除了网络失败。

此文件的变更主要影响同步调用者的线程占用和生命周期；协议、订阅确认交错、二进制消息等行为仍继承 client.rs。当前仓库没有对应独立的 blocking_client 集成测试文件，不能从别的客户端测试通过直接推出此适配器已完整验证。

## 读完后沿哪里继续

[src/clients/client.rs](client.md) → [src/clients/mod.rs](mod.md)。

跨文件串读：[第 09 章：客户端边界](../../../09-clients.md)。
