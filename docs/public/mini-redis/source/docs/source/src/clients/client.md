# src/clients/client.rs：一条连接上的请求与响应

<!-- analyzes: src/clients/client.rs -->

[打开对应源码](../../../../src/clients/client.rs) · [源码文章索引](../../README.md) · [总目录](../../../README.md)

Client 持有一条 Connection。CLI、示例和另外两种客户端都通过它访问服务。普通命令先编码、写入，再读一条响应；因此理解它，就能将业务调用和线上字节接起来。

## 它和哪些代码交互

```text
CLI / 示例 / BufferedClient / BlockingClient
 → connect → TcpStream → Connection → Client
 → get / set / publish → 命令 into_frame → write_frame
 ← 业务返回值 ← 响应校验 ← read_response ← read_frame
 subscribe(self) → Subscriber → 推送消息读取
```

## 连接建立与可变借用

connect 接受实现 ToSocketAddrs 的地址，await TcpStream::connect 后封装 Connection。Client 本身不是连接池。get/set 等方法要求 `&mut self`，意味着一次调用期间独占这份客户端；若要让多任务共用它，需要上层排队，不能让两条调用随意抢下一条响应。

## GET 将协议结果翻译成业务类型

<!-- source: src/clients/client.rs:113-129; comments included -->
```rust
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
```

Get::new 与 into_frame 在 cmd/get.rs，写出的数组包含命令名与 key。返回值 Some(Bytes) 表示有值，None 对应 Null。read_response 先把 Error 帧转成 Rust Err，所以这里匹配的是正常响应；不合预期的帧通过 to_error 报错。`?` 将失败直接返回给调用者，后面的步骤不会继续执行。

## 两个 SET 入口共用一个响应校验点

<!-- source: src/clients/client.rs:197-211; comments included -->
```rust
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
```

set 传 None，set_expires 传 Some(Duration)，二者都交给 set_cmd。Set::into_frame 决定是否附带 PX 参数；只有 Simple OK 才表示此调用成功。服务端先修改 Db 再发送 OK，故客户端读响应失败时，不能推导写入一定没有发生，也不能把自动重试当成无条件安全。

## 订阅消耗 Client，改变接收方式

<!-- source: src/clients/client.rs:249-258; comments included -->
```rust
pub async fn subscribe(mut self, channels: Vec<String>) -> crate::Result<Subscriber> {
    // 等待每个初始频道的订阅确认，再建立本地订阅状态。
    self.subscribe_cmd(&channels).await?;

    // 把 Client 和频道 Vec 移入返回值；并没有重新建立 TCP 连接。
    Ok(Subscriber {
        client: self,
        subscribed_channels: channels,
    })
}
```

这里接收 self 的所有权，成功后把 Client 移进 Subscriber。普通调用者不能再用原变量发 GET；这个类型变化表达了连接状态变化。subscribe_cmd 会等待每个频道的确认帧，然后保存本地频道列表；它没有请求编号，也没有一个统一分发确认与推送的接收任务。

## 消息、确认和字节完整性

Subscriber::next_message 期待 message 数组三元组，EOF 返回 None。into_stream 用 try_stream 将反复 next_message 包装成 Stream，读取错误会终止流。当前 next_message 使用 content.to_string 再构造 Bytes；Display 遇到非 UTF-8 时的转换可能改变消息字节，GET 的 Bulk 直接返回则没有这一步。

Subscriber::subscribe 先读确认再扩展本地列表；unsubscribe 根据参数数量或当前列表长度读取确认并更新列表。并发发布的消息可能插在确认之间，重复订阅又可能使客户端列表与服务端去重后的 StreamMap 不一致。修改订阅可靠性，要连同确认/消息分发及去重策略一起考虑。

## 其他入口与错误边界

ping 接受可选 Bytes，校验 PONG 或回显；publish 返回 Integer 中的接收者数量。read_response 将对端 EOF 转为 ConnectionReset，将 Error 帧转为 Err；Subscriber::next_message 则把正常 EOF 表达为 Ok(None)。同样的网络关闭，在两种使用场景中有不同 API 含义。

这个文件不负责服务端的键值保存，也不自动重连。验证改动应同时覆盖调用返回类型、实际编码、意外响应、EOF，以及订阅确认与消息交错。

## 这里的 Rust 写法：Client 到 Subscriber 是一次所有权转移

get/set 的 &mut self 是暂时独占，调用结束后可以继续用 Client。subscribe 的 mut self 却消费整个值，再把它移进 Subscriber；mut 只是允许函数内部修改自己持有的值。返回流的 impl Stream 隐藏具体流类型，而切片模式 `[message, channel, content]` 会检查数组形状。`ref frame` 在本实现中保留对数组的借用，避免直接移走它。

需要拆开语法时，接着读 [Rust 阅读说明的对应小节](../../../rust-reading-guide.md#receivers)。

## 读完后沿哪里继续

[src/cmd/get.rs](../cmd/get.md) → [src/cmd/set.rs](../cmd/set.md) → [src/connection.rs](../connection.md) → [src/clients/buffered_client.rs](buffered_client.md) → [tests/client.rs](../../tests/client.md)。

跨文件串读：[第 03 章：SET/GET 完整调用链](../../../03-request-path.md)。
