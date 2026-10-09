# 09 客户端为什么有三种形态

[上一章](08-pubsub.md) · [目录](README.md) · [下一章](10-shutdown-and-tests.md)

服务端承担并发，客户端也有自己的并发问题。如果两个任务共用一个 TCP 连接，各自发请求、各自读响应，谁能保证它们不会读走对方的结果？本项目的三种客户端展示了不同边界上的处理方式。

## 三种 API 最后都到哪里

```text
异步业务 → Client::get ──────────────────┐
多任务业务 → BufferedClient::get         │
              → mpsc → 后台 run         ├→ Client → Connection → TCP → 服务端
                         → Client::get ─┤
同步业务 → BlockingClient::get          │
              → runtime.block_on        │
                         → Client::get ─┘
```

三种接口改变的是客户端进程内的调用组织方式，不是三种服务端协议。BufferedClient 的内部 Command 只有 Get/Set，它是队列消息类型；不是 `src/cmd/mod.rs` 中负责 RESP 命令分发的 Command。混淆这两个类型，就会误以为队列消息能直接发给服务端。

## 基础 Client：独占完成一次往返

[Client](../src/clients/client.rs) 持有一个 Connection。`get`、`set` 等方法需要 `&mut self`，一次调用从发出帧持续到读取对应响应。

这个签名让普通调用者不能同时借用同一个 Client 去做两个完整请求。它没有请求 ID，也没有把多个在途请求与响应配对的机制。底层服务器能接收相邻帧，不等于这个客户端实现了 pipeline。

`subscribe(mut self, ...) -> Result<Subscriber>` 消费 Client。返回的 Subscriber 内部仍持有原连接，但是对外暴露订阅 API。类型变化提示调用者：接下来读取的是可能主动到来的消息，使用方式已经不同。

## BufferedClient：一个任务拥有连接

[buffered_client.rs](../src/clients/buffered_client.rs) 把基础 Client 移进后台任务，其他调用者只持有可克隆的 mpsc Sender：

```text
调用者 A ── (Get, 回信地址 A) ─┐
调用者 B ── (Set, 回信地址 B) ─┼─→ 有界 mpsc → run(client, rx)
调用者 C ── (Get, 回信地址 C) ─┘                    │
           ▲                                        │ 顺序执行请求
           └──────── 各自的 oneshot 回复 ────────────┘
```

先看谁创建后台任务。[BufferedClient::buffer](../src/clients/buffered_client.rs) 由业务初始化代码调用，例如 [multiplex 实验](labs/src/bin/multiplex.rs)：

<!-- source: src/clients/buffered_client.rs:67-77; comments omitted -->
```rust
pub fn buffer(client: Client) -> BufferedClient {
    let (tx, rx) = channel(32);

    tokio::spawn(async move { run(client, rx).await });

    BufferedClient { tx }
}
```

Client 被 move 到 run 任务后，外面的 BufferedClient 只留下发送端。调用者 clone BufferedClient 只会得到另一个队列入口，并没有增加 TcpStream。

跟踪一个具体 GET，调用者执行的是 [BufferedClient::get](../src/clients/buffered_client.rs)：

<!-- source: src/clients/buffered_client.rs:83-98; comments omitted -->
```rust
pub async fn get(&mut self, key: &str) -> Result<Option<Bytes>> {
    let get = Command::Get(key.into());

    let (tx, rx) = oneshot::channel();

    self.tx.send((get, tx)).await?;

    match rx.await {
        Ok(res) => res,
        Err(err) => Err(err.into()),
    }
}
```

两次等待对应两位交互对象：`self.tx.send(...).await` 等请求进入共享队列；`rx.await` 等本次私有 oneshot 的回复。入队成功只说明后台有机会处理，还不意味着服务端已经执行 GET。

后台唯一的接收者运行以下 [run](../src/clients/buffered_client.rs)：

<!-- source: src/clients/buffered_client.rs:26-43; comments omitted -->
```rust
async fn run(mut client: Client, mut rx: Receiver<Message>) {
    while let Some((cmd, tx)) = rx.recv().await {
        let response = match cmd {
            Command::Get(key) => client.get(&key).await,
            Command::Set(key, value) => client.set(&key, value).await.map(|_| None),
        };

        let _ = tx.send(response);
    }
}
```

这三段连起来才是一个完整请求：业务调用 → 入队 → 后台取出 → 真正 Client 网络往返 → oneshot 回信 → 业务得到结果。run 在一个命令 await 完后才取下一个，所以一条连接上仍是顺序处理。

| 失败/等待位置 | 谁看到它 | 后续影响 |
| --- | --- | --- |
| mpsc 队列满 | 当前 BufferedClient 调用等待 | 不自动扩容为更多 TCP 连接；其他已入队请求仍处理 |
| mpsc 接收端已关闭 | send 返回 Err，`?` 交给调用者 | 这次命令未通过这个入口成功入队 |
| Client::get/set 返回 Err | run 将这个 Result 发回 oneshot | 后台代码仍继续下一轮；没有自动修复/重连 Client |
| 调用者取消等待回复 | 后台 tx.send 可能失败并被忽略 | 已入队/已执行的写操作不会被撤销 |
| 所有 BufferedClient Sender 释放 | run 排空已有队列后 recv 返回 None | 后台函数结束，Client/socket 随之释放 |


mpsc 是多生产者、单消费者：许多 Sender 可以发消息，唯一 Receiver 顺序处理。这里容量为 32，队列满时 `send(...).await` 等待空间，形成背压。若队列无界，调用者快于服务端就可能不断积累内存。

每条消息携带一个 oneshot Sender，像附带回信地址。后台任务得到结果后只给这位调用者回复一次。类型定义是：

```rust
type Message = (Command, oneshot::Sender<Result<Option<Bytes>>>);
```

GET 需要 `Option<Bytes>`，SET 只需要 `()`；后台把成功的 SET 映射为 None，用统一 Message 返回类型承载，外层 `set` 再把结果映射回 `()`。

调用者等待 `rx.await` 得到嵌套结果：外层表示 oneshot 是否正常收到回复，内层表示命令本身是否成功。因此“回信通道断了”与“服务器拒绝命令”不是同一种错误。

后台使用 `let _ = tx.send(response)` 忽略回复失败：若调用者取消等待，执行任务仍能继续服务其他请求。但取消等待不等于撤销已经执行的 SET；这一点在任何带外部效果的异步 API 中都值得检查。

BufferedClient clone 的是发送句柄，所有克隆仍共享一个后台 Client 和一条连接。它是排队复用，不是连接池，也没有在这条连接上并行执行多个命令。只有 Get/Set 被这个包装层暴露，不会自动拥有基础 Client 的全部能力。

## BlockingClient：为同步调用者驱动 runtime

[blocking_client.rs](../src/clients/blocking_client.rs) 内部保存异步 Client 与一个 current-thread runtime，通过 `rt.block_on(...)` 驱动对应异步操作，直到得到结果。

这正是第 05 章显式 Builder 实验中的同步/异步边界：普通函数创建或持有 runtime，由 block_on 驱动 Future。区别在于这里把 runtime 存入客户端结构体，多个方法复用它，而不是每调用一次 get 就重新创建运行环境。

先看 [BlockingClient::connect](../src/clients/blocking_client.rs) 如何构造对象，再看它的 get 如何复用对象：

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

<!-- source: src/clients/blocking_client.rs:97-99; comments omitted -->
```rust
pub fn get(&mut self, key: &str) -> crate::Result<Option<Bytes>> {
    self.rt.block_on(self.inner.get(key))
}
```

普通函数的调用者被 block_on 阻塞到结果返回；网络语义仍由 inner.get 决定。因此给 Client::get 增加响应检查，会同时影响 BlockingClient 和 BufferedClient 经它读取的结果；单改 BufferedClient 的队列容量则不会改变另外两种接口。


同步业务代码可以调用阻塞式 `get`，代价是当前调用线程等待完成。这一层并没有把网络重新实现一遍。current-thread runtime 在 block_on 期间被驱动，不能假设它离开 block_on 后仍有工作线程替你执行任务。

不要在已经运行的异步 runtime 内随意调用这个包装，让 runtime 嵌套阻塞。异步路径直接用 Client；在必须接同步代码时再清楚地安排边界。

BlockingSubscriber 还能转成普通 Iterator。它的 `next` 把 `Result<Option<Message>>` 用 `.transpose()` 变成 `Option<Result<Message>>`：

| 原结果 | Iterator 需要的结果 |
| --- | --- |
| `Ok(Some(message))` | `Some(Ok(message))` |
| `Ok(None)` | `None`，迭代结束 |
| `Err(error)` | `Some(Err(error))`，本轮出错 |

`impl Iterator` 中的 `type Item = ...` 是关联类型；每个实现指定它迭代出什么。它与第 08 章 `Stream<Item = Bytes>` 是相同的类型表达方式，只是同步与异步迭代机制不同。

## 选择哪一个

| 调用环境 | 选择 | 需要记住的限制 |
| --- | --- | --- |
| 已在 async 中，独占连接 | Client | 一次往返需要可变借用 |
| 多任务共享一条连接，做 Get/Set | BufferedClient | 32 容量队列，后台顺序执行 |
| 同步函数里使用 | BlockingClient | 阻塞当前线程并驱动内部 runtime |
| 持续接收推送 | Subscriber / BlockingSubscriber | 与普通查询连接区分 |

运行 [multiplex 实验](labs/src/bin/multiplex.rs)，多个任务各自持有 BufferedClient 克隆，并使用不同的键完成读写：

```sh
cargo run --locked --manifest-path docs/labs/Cargo.toml --bin multiplex
```

为什么这个例子用不同的键，而不是让每个任务都 GET counter、加一、SET counter？

<details>
<summary>参考答案</summary>

队列保证单个命令顺序执行，不保证某个调用者的两个命令之间不穿插其他命令。GET 后再 SET 是复合操作，会有丢失更新的可能。若要计数，需要设计服务端的原子命令，或使用支持相应语义的事务机制。

</details>
