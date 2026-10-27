---
title: "第 9 章：客户端为什么有三种形态"
description: "多个调用者能安全共用一个连接吗？"
pageClass: mini-redis-course
---

# 第 9 章：客户端为什么有三种形态

[课程总览](/mini-redis/index.md) · [上一章](/mini-redis/pubsub.md) · [下一章](/mini-redis/shutdown-and-tests.md)

::: tip 本章学习目标
**要解决的问题：** 多个调用者能安全共用一个连接吗？

**顺路学到的 Rust：** mpsc、oneshot、迭代器、同步与异步边界

**对应源码：** [src/clients/mod.rs](/mini-redis/source/src/clients/mod.md)、[src/clients/client.rs](/mini-redis/source/src/clients/client.md)、[src/clients/buffered_client.rs](/mini-redis/source/src/clients/buffered_client.md)、[src/clients/blocking_client.rs](/mini-redis/source/src/clients/blocking_client.md)、[tests/buffered_client.rs](/mini-redis/source/tests/buffered_client.md)。完整的一一对应关系见 [源码文章索引](/mini-redis/source/index.md)。
:::

<MiniRedisMap active="clients" />

服务端承担并发，客户端也有自己的并发问题。如果两个任务共用一个 TCP 连接，各自发请求、各自读响应，谁能保证它们不会读走对方的结果？本项目的三种客户端展示了不同边界上的处理方式。

## 三种 API 最后都到哪里

![Client::get 直接使用；BufferedClient 经 mpsc 交给后台 run 任务；BlockingClient 经 runtime.block_on；三者最终都通过 Client 和 Connection 访问 TCP](/mini-redis/figures/client-forms.svg)

三种接口改变的是客户端进程内的调用组织方式，服务端看到的始终是同一种协议。BufferedClient 的内部 Command 只有 Get/Set，它是队列消息类型，与 `src/cmd/mod.rs` 中负责 RESP 命令分发的 Command 只是同名。

## 基础 Client：独占完成一次往返

[Client](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/mini-redis/source/src/clients/client.rs) 持有一个 Connection。`get`、`set` 等方法需要 `&mut self`，一次调用从发出帧持续到读取对应响应。

这个签名保证同一时刻只有一个调用者借用这个 Client，完整做完一个请求后才轮到下一个。它没有请求 ID，也没有把多个在途请求与响应配对的机制。

`subscribe(mut self, ...) -> Result<Subscriber>` 消费 Client。返回的 Subscriber 内部仍持有原连接，但是对外暴露订阅 API。类型变化提示调用者：接下来读取的是可能主动到来的消息，使用方式已经不同。

## BufferedClient：一个任务拥有连接

[buffered_client.rs](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/mini-redis/source/src/clients/buffered_client.rs) 把基础 Client 移进后台任务，其他调用者只持有可克隆的 mpsc Sender：

![调用者 A、B、C 把命令和 oneshot 回信地址发进同一个有界 mpsc；后台 run 持有唯一的 Client 顺序执行，再经各自的 oneshot 回复](/mini-redis/figures/buffered-client.svg)

先看谁创建后台任务。[BufferedClient::buffer](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/mini-redis/source/src/clients/buffered_client.rs) 由业务初始化代码调用，例如 [multiplex 实验](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/mini-redis/source/docs/labs/src/bin/multiplex.rs)：

<!-- source: src/clients/buffered_client.rs:46-55; comments included -->
```rust
pub fn buffer(client: Client) -> BufferedClient {
    // 容量 32 限制待处理消息；满时 send().await 等待，形成背压。
    let (tx, rx) = channel(32);

    // async move 接管 client 和 rx；spawn 要求捕获状态不借用即将失效的调用者局部变量。
    tokio::spawn(async move { run(client, rx).await });

    // 只把 Sender 交给业务调用者，Receiver 和 Client 留在后台。
    BufferedClient { tx }
}
```

Client 被 move 到 run 任务后，外面的 BufferedClient 只留下发送端。调用者 clone BufferedClient 只会得到另一个队列入口，并没有增加 TcpStream。

跟踪一个具体 GET，调用者执行的是 [BufferedClient::get](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/mini-redis/source/src/clients/buffered_client.rs)：

<!-- source: src/clients/buffered_client.rs:58-73; comments included -->
```rust
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
```

两次等待对应两位交互对象：`self.tx.send(...).await` 等请求进入共享队列；`rx.await` 等本次私有 oneshot 的回复。入队成功只说明后台有机会处理，还不意味着服务端已经执行 GET。

后台唯一的接收者运行以下 [run](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/mini-redis/source/src/clients/buffered_client.rs)：

<!-- source: src/clients/buffered_client.rs:20-33; comments included -->
```rust
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

调用者等待 `rx.await` 得到嵌套结果：外层表示 oneshot 是否正常收到回复，内层表示命令本身是否成功。因此“回信通道断了”与“服务器拒绝命令”是两种不同的错误。

后台使用 `let _ = tx.send(response)` 忽略回复失败：若调用者取消等待，执行任务仍能继续服务其他请求，已经执行的 SET 照样生效；这一点在任何带外部效果的异步 API 中都值得检查。

BufferedClient clone 的是发送句柄，所有克隆仍共享一个后台 Client 和一条连接。它是排队复用：命令在这条连接上逐个顺序执行。这个包装层只暴露 Get/Set，其他能力仍要通过基础 Client 使用。

## BlockingClient：为同步调用者驱动 runtime

[blocking_client.rs](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/mini-redis/source/src/clients/blocking_client.rs) 内部保存异步 Client 与一个 current-thread runtime，通过 `rt.block_on(...)` 驱动对应异步操作，直到得到结果。

这正是第 5 章显式 Builder 实验中的同步/异步边界：普通函数创建或持有 runtime，由 block_on 驱动 Future。区别在于这里把 runtime 存入客户端结构体，多个方法复用它，不必每调用一次 get 就重新创建运行环境。

先看 [BlockingClient::connect](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/mini-redis/source/src/clients/blocking_client.rs) 如何构造对象，再看它的 get 如何复用对象：

<!-- source: src/clients/blocking_client.rs:57-65; comments included -->
```rust
pub fn connect<T: ToSocketAddrs>(addr: T) -> crate::Result<BlockingClient> {
    let rt = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()?;

    let inner = rt.block_on(crate::clients::Client::connect(addr))?;

    Ok(BlockingClient { inner, rt })
}
```

<!-- source: src/clients/blocking_client.rs:79-81; comments included -->
```rust
pub fn get(&mut self, key: &str) -> crate::Result<Option<Bytes>> {
    self.rt.block_on(self.inner.get(key))
}
```

普通函数的调用者被 block_on 阻塞到结果返回；网络语义仍由 inner.get 决定。因此给 Client::get 增加响应检查，会同时影响 BlockingClient 和 BufferedClient 经它读取的结果；单改 BufferedClient 的队列容量则不会改变另外两种接口。


同步业务代码可以调用阻塞式 `get`，代价是当前调用线程等待完成。网络逻辑仍复用异步 Client。current-thread runtime 只在 block_on 期间被驱动，离开 block_on 后没有工作线程替你执行任务。

异步路径直接用 Client；在必须接同步代码时再清楚地安排边界。

BlockingSubscriber 还能转成普通 Iterator。它的 `next` 把 `Result<Option<Message>>` 用 `.transpose()` 变成 `Option<Result<Message>>`：

| 原结果 | Iterator 需要的结果 |
| --- | --- |
| `Ok(Some(message))` | `Some(Ok(message))` |
| `Ok(None)` | `None`，迭代结束 |
| `Err(error)` | `Some(Err(error))`，本轮出错 |

`impl Iterator` 中的 `type Item = ...` 是关联类型；每个实现指定它迭代出什么。它与第 8 章 `Stream<Item = Bytes>` 是相同的类型表达方式，只是同步与异步迭代机制不同。

## 选择哪一个

| 调用环境 | 选择 | 需要记住的限制 |
| --- | --- | --- |
| 已在 async 中，独占连接 | Client | 一次往返需要可变借用 |
| 多任务共享一条连接，做 Get/Set | BufferedClient | 32 容量队列，后台顺序执行 |
| 同步函数里使用 | BlockingClient | 阻塞当前线程并驱动内部 runtime |
| 持续接收推送 | Subscriber / BlockingSubscriber | 与普通查询连接区分 |

运行 [multiplex 实验](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/mini-redis/source/docs/labs/src/bin/multiplex.rs)，多个任务各自持有 BufferedClient 克隆，并使用不同的键完成读写：

```sh
cargo run --locked --manifest-path docs/labs/Cargo.toml --bin multiplex
```

::: warning 常见误区
- **BufferedClient 的 Command 不是 RESP 命令。** 它只是进程内的队列消息类型，与 `src/cmd/mod.rs` 的 Command 同名；队列消息不能直接发给服务端。
- **服务器能接收相邻帧，不等于 Client 实现了 pipeline。** 基础 Client 没有请求 ID，一次只完成一个往返。
- **BufferedClient 不是连接池。** clone 只增加队列入口，所有请求仍在同一条连接上顺序执行。
- **取消等待不等于撤销 SET。** 调用者放弃 oneshot 回复后，已入队或已执行的写操作照样生效。
- **不要在已运行的异步 runtime 内调用 BlockingClient。** 这会让 runtime 嵌套阻塞；异步代码应直接使用 Client。
:::

## 本章结论 {#summary}

三种客户端共用同一个基础 Client 和同一套协议，区别只在调用者如何组织对连接的访问：Client 用 `&mut self` 让一次往返独占连接；BufferedClient 把 Client 移进后台任务，调用者经有界 mpsc 入队、经各自的 oneshot 取回结果；BlockingClient 在结构体里保存 current-thread runtime，用 block_on 为同步代码驱动异步操作。

无论哪种形态，一条连接上的命令都按顺序逐个完成。需要多条命令整体原子时，要靠服务端的原子命令或事务，客户端的排队方式解决不了。

## 检查理解

1. 为什么这个例子用不同的键，而不是让每个任务都 GET counter、加一、SET counter？

   <details><summary>参考答案</summary>

   队列保证单个命令顺序执行，不保证某个调用者的两个命令之间不穿插其他命令。GET 后再 SET 是复合操作，会有丢失更新的可能。若要计数，需要设计服务端的原子命令，或使用支持相应语义的事务机制。

   </details>

2. `BufferedClient::get` 里有哪两处 await，各自在等什么？

   <details><summary>参考答案</summary>

   `self.tx.send(...).await` 等请求进入共享的 mpsc 队列，队列满时形成背压；`rx.await` 等本次私有 oneshot 送回结果。入队成功只说明后台有机会处理，服务端还未必执行了 GET。

   </details>

3. 调用者从 `rx.await` 得到的是嵌套结果，外层和内层分别表示什么？

   <details><summary>参考答案</summary>

   外层表示 oneshot 是否正常收到回复（回信通道是否断开），内层表示命令本身是否成功（例如服务器拒绝命令或网络错误）。

   </details>

4. 给 `Client::get` 增加响应检查，会影响哪些客户端？只改 BufferedClient 的队列容量呢？

   <details><summary>参考答案</summary>

   改 `Client::get` 会同时影响三种客户端，因为 BlockingClient 和 BufferedClient 最终都经它读取结果；改队列容量只影响 BufferedClient 的排队与背压行为。

   </details>

下一章回到服务端，看服务器怎样通知退出、又怎样确认已经退出：[第 10 章：如何停机与验证行为](/mini-redis/shutdown-and-tests.md)。
