---
editLink: false
---

# src/cmd/subscribe.rs：接管连接并复用多个频道流

<!-- analyzes: src/cmd/subscribe.rs -->

[打开对应源码](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/mini-redis/source/src/cmd/subscribe.rs) · [源码文章索引](/mini-redis/source/index.md) · [总目录](/mini-redis/index.md)

这个文件同时定义 Subscribe 和 Unsubscribe。进入订阅后，连接不再按普通 Handler 的一次请求一次响应循环工作，而由 Subscribe::apply 同时处理频道消息、后续订阅命令和停止通知。

## 它和哪些代码交互

```text
Handler → Command::apply → Subscribe::apply
 → subscribe_to_channel → Db::subscribe → broadcast Receiver
 → StreamMap 多频道合流 → message Frame → 同一 socket
 ← socket 新命令 → handle_command → 增加 / 取消订阅
 ← Shutdown::recv → 返回 → Handler 退出
```

## 先解析频道列表，再进入长循环

Subscribe::parse_frames 先强制读取一个频道，再循环读到 EndOfStream；Unsubscribe::parse_frames 允许零个频道，表示取消当前全部频道。into_frame 分别构造 subscribe/unsubscribe 数组。服务端 StreamMap 以频道 String 为键，故相同频道不会建立多个并列条目；这与客户端 Vec 中可能保存重复项不同。

## 三个输入源在同一个任务里竞争

<!-- source: src/cmd/subscribe.rs:115-154; comments omitted -->
```rust
let mut subscriptions = StreamMap::new();

    loop {
        for channel_name in self.channels.drain(..) {
            subscribe_to_channel(channel_name, &mut subscriptions, db, dst).await?;
        }

        select! {
            Some((channel_name, msg)) = subscriptions.next() => {
                dst.write_frame(&make_message_frame(channel_name, msg)).await?;
            }
            res = dst.read_frame() => {
                let frame = match res? {
                    Some(frame) => frame,
                    None => return Ok(())
                };

                handle_command(
                    frame,
                    &mut self.channels,
                    &mut subscriptions,
                    dst,
                ).await?;
            }
            _ = shutdown.recv() => {
                return Ok(());
            }
        };
    }
}
```

每轮先 drain 尚未建立的频道并逐个发送确认，再 select 等待频道消息、连接输入或停止。频道消息分支拿到的是 (channel_name, Bytes)，写成 message 数组。连接 EOF 返回 Ok；解析或写入错误经 `?` 返回 Err。二者都会让外层任务释放连接和订阅流。

write_frame 在选中分支内部 await；写回阻塞时，此任务不会同时执行另外两个分支。所以 select 出现了 shutdown，并不意味着每个网络写等待都能立即响应停止。

## Receiver 被适配成 Stream

<!-- source: src/cmd/subscribe.rs:170-198; comments omitted -->
```rust
async fn subscribe_to_channel(
    channel_name: String,
    subscriptions: &mut StreamMap<String, Messages>,
    db: &Db,
    dst: &mut Connection,
) -> crate::Result<()> {
    let mut rx = db.subscribe(channel_name.clone());

    let rx = Box::pin(async_stream::stream! {
        loop {
            match rx.recv().await {
                Ok(msg) => yield msg,
                Err(broadcast::error::RecvError::Lagged(_)) => {}
                Err(_) => break,
            }
        }
    });

    subscriptions.insert(channel_name.clone(), rx);

    let response = make_subscribe_frame(channel_name, subscriptions.len());
    dst.write_frame(&response).await?;

    Ok(())
}
```

Pin&lt;Box&lt;dyn Stream&lt;Item = Bytes> + Send>> 把不同异步流统一成可存放的类型；Box 持有它，dyn 隐藏具体类型，Pin 满足异步流的固定位置要求。broadcast 的 Lagged 在这里被忽略，意味着慢订阅可能无提示地丢消息。插入 StreamMap 后再回确认，确认中的计数是该连接当前订阅数。

## handle_command 决定订阅模式允许做什么

新 Subscribe 将频道加入待处理列表，下一轮循环建立流；Unsubscribe 无参数时先列出当前 keys，再逐一 remove 并回取消确认。GET/SET/PUBLISH 等其他命令改走 Unknown::apply，得到错误帧，连接仍处于订阅循环。

删除 StreamMap 条目会释放 Receiver，但不会删除 Db 的频道 Sender。最后一个频道取消后，apply 也没有返回普通 Handler 的分支：它继续等待 socket 命令或停止。不能把当前实现讲成完整 Redis 的订阅状态切换。

## 三个响应构造函数是协议契约

make_subscribe_frame / make_unsubscribe_frame 返回 [标记, 频道, 当前数量]，make_message_frame 返回 [message, 频道, 内容]。Client::subscribe_cmd、Subscriber::unsubscribe 和 next_message 分别依赖它们。若新增确认字段、改变内容编码或支持交错响应，必须同时检查客户端匹配规则。

优化可以从保留二进制字节、确认与推送统一分发、重复频道去重、慢订阅策略以及取消后状态转换入手；每项都涉及两端行为，不能当作一个局部 StreamMap 替换。

## 读完后沿哪里继续

[src/db.rs](/mini-redis/source/src/db.md) → [src/clients/client.rs](/mini-redis/source/src/clients/client.md) → [src/cmd/mod.rs](/mini-redis/source/src/cmd/mod.md) → [src/shutdown.rs](/mini-redis/source/src/shutdown.md) → [tests/server.rs](/mini-redis/source/tests/server.md)。

跨文件串读：[第 08 章：连接模式变化](/mini-redis/08-pubsub.md)。
