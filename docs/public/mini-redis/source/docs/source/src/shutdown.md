# src/shutdown.rs：让一个连接记住停止通知

<!-- analyzes: src/shutdown.rs -->

[打开对应源码](../../../src/shutdown.rs) · [源码文章索引](../README.md) · [总目录](../../README.md)

Shutdown 封装一个 broadcast Receiver 和布尔标记。它只解释停止通知，不关闭 listener、不等待所有任务，也不直接销毁 socket。调用者收到结果后必须自己返回。

## 它和哪些代码交互

```text
Listener 构造 Handler → Shutdown::new(receiver)
Handler::run / Subscribe::apply → select 中 Shutdown::recv
server::run drop Sender → recv 完成 → is_shutdown=true
调用者 return → Handler 释放 → 完成通道 Sender 释放
```

## new、查询与等待的关系

<!-- source: src/shutdown.rs:21-49; comments omitted -->
```rust
impl Shutdown {
    pub(crate) fn new(notify: broadcast::Receiver<()>) -> Shutdown {
        Shutdown {
            is_shutdown: false,
            notify,
        }
    }

    pub(crate) fn is_shutdown(&self) -> bool {
        self.is_shutdown
    }

    pub(crate) async fn recv(&mut self) {
        if self.is_shutdown {
            return;
        }

        let _ = self.notify.recv().await;

        self.is_shutdown = true;
    }
}
```

new 初始化 false；is_shutdown 是立即返回的查询，不等待网络或信号；recv 首次等待，之后用布尔标记快速返回。这里忽略底层 recv 的具体结果，所以关闭发送端也能触发停止，不要求服务器先发送一条消息。

## 真正释放资源的是谁

Handler 的 select 停止分支返回 Ok，回到 spawn 闭包后 Handler 随任务结束释放。Subscribe::apply 有自己的停止分支，因为外层 Handler 正 await 它，不能同时再读一遍 shutdown。

如果只是调用 is_shutdown 却从未等到 recv，标记不会神奇地跟着发送端变化；如果代码卡在 select 外的响应写 await，这个方法也不能抢占它。该文件提供协作信号，停机时限与任务完成统计在其他层。

## 改动会影响什么

多留一个 broadcast Sender 会延迟所有接收者观察关闭；误把 recv 的通道关闭当作可忽略并继续无限等待，会破坏主流程退出。应在空闲普通连接、订阅连接和已开始写响应三种位置分别检查停机路径。

## 读完后沿哪里继续

[src/server.rs](server.md) → [src/cmd/subscribe.rs](cmd/subscribe.md) → [src/db.rs](db.md)。

跨文件串读：[第 10 章：通知与完成](../../10-shutdown-and-tests.md)。
