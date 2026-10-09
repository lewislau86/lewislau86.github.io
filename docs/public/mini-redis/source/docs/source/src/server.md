# src/server.rs：接入任务、连接任务与退出协调

<!-- analyzes: src/server.rs -->

[打开对应源码](../../../src/server.rs) · [源码文章索引](../README.md) · [总目录](../../README.md)

这是整个服务的组织中心。它把监听器、共享数据库、连接配额和退出通道组合起来，真正执行命令仍通过 Command::apply 委托出去。阅读时先区分三个 run，避免把某个连接失败理解为整个服务失败。

## 它和哪些代码交互

```text
binary main → server::run
  → select：Listener::run 或外部 shutdown
      → permit → accept → 构造 Handler → spawn Handler::run
          → Connection::read_frame → Command::from_frame → apply
  → 通知停止 → 等待所有 Handler 释放完成 Sender
```

## 三个 run 的影响范围

| 函数 | 直接调用者 | 退出影响 |
| --- | --- | --- |
| server::run | binary、测试启动函数 | 服务实例的协调主流程结束 |
| Listener::run | server::run 的 select | 持续 accept 失败会进入外层停止路径 |
| Handler::run | 每连接的 spawn 闭包 | 结束一个连接，其他 Handler 仍可继续 |

Listener 持有 DbDropGuard，每次构造 Handler 只克隆 Db 句柄。一个连接一个独立 Connection，但访问同一份数据。MAX_CONNECTIONS=250，许可在 accept 前获取；任务结束归还许可。

## Handler 实际怎样驱动请求

<!-- source: src/server.rs:318-369; comments omitted -->
```rust
async fn run(&mut self) -> crate::Result<()> {
    while !self.shutdown.is_shutdown() {
        let maybe_frame = tokio::select! {
            res = self.connection.read_frame() => res?,
            _ = self.shutdown.recv() => {
                return Ok(());
            }
        };

        let frame = match maybe_frame {
            Some(frame) => frame,
            None => return Ok(()),
        };

        let cmd = Command::from_frame(frame)?;

        debug!(?cmd);

        cmd.apply(&self.db, &mut self.connection, &mut self.shutdown)
            .await?;
    }

    Ok(())
}
```

读帧与停止信号一起等，完整帧才进入命令层。from_frame 的 Err 由 `?` 离开 Handler，不会自动生成 Error 帧。apply 执行完成后回到循环，订阅命令则可能长期停在内部的 apply 中。

外层 spawn 用 if let 接住 Handler 的 Err，记录 connection error，然后释放资源；错误不会沿普通函数链返回 Listener。相反，Listener::accept 的持续错误经 `?` 直接离开接入循环，影响整台实例。

## 接入失败与停机不是同一层逻辑

accept 使用指数退避，从 1 秒增加到 64 秒，之后再失败则返回错误。外层 select 一旦决定退出，就 drop 停止广播发送端；每个 Handler 的 Shutdown 会醒来。主流程再等完成 mpsc 的所有发送端释放。

这里没有统一响应写入超时。Handler 已开始的 cmd.apply 不在读帧 select 内，因此慢写可能延迟停机。清理任务由 DbDropGuard 另行通知，没有作为此完成通道中的一个 Handler 等待。

## 改动影响与定位

将 Db::new 挪到每次 accept 会使连接间数据不再共享；把 handler.run().await 放回接入循环、不 spawn，会使接入等该连接结束；保留多余完成 Sender 会使停机等待无法完成。验证这些修改时要分别观察跨连接共享、接入并发和退出完成，而不是只测一次 SET 成功。

## 读完后沿哪里继续

[src/connection.rs](connection.md) → [src/cmd/mod.rs](cmd/mod.md) → [src/db.rs](db.md) → [src/shutdown.rs](shutdown.md)。

跨文件串读：[第 05 章：三个 run 的完整链路](../../05-tokio-server.md)。
