---
editLink: false
---

# src/bin/cli.rs：将终端参数翻译成客户端调用

<!-- analyzes: src/bin/cli.rs -->

[打开对应源码](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/mini-redis/source/src/bin/cli.rs) · [源码文章索引](/mini-redis/source/index.md) · [总目录](/mini-redis/index.md)

CLI 是使用 Client 的应用程序，不是协议解析器。终端里的 set course rust 先被 clap 解析成这里的 Command 枚举，然后才调用 Client 编码网络请求。

## 它和哪些代码交互

```text
命令行 → Cli::parse → host:port → Client::connect
 → 本文件 Command match → Client API → Connection → TCP
 ← Bytes / Option / 结果 ← 格式化为终端输出
```

## CLI 的 SET 分支有两条路径

<!-- source: src/bin/cli.rs:104-119; comments included -->
```rust
Command::Set {
    key,
    value,
    expires: None,
} => {
    client.set(&key, value).await?;
    println!("OK");
}
Command::Set {
    key,
    value,
    expires: Some(expires),
} => {
    client.set_expires(&key, value, expires).await?;
    println!("OK");
}
```

expires 是可选 Duration，来自最后一个位置参数的毫秒解析。没有它就调 Client::set；有它就调 set_expires。两种路径都必须 await 成功后才打印 OK。这里的 OK 是显示内容，真正的响应校验在 Client::set_cmd。

## GET、发布和订阅返回给用户什么

GET 的 Some 内容先尝试 UTF-8 展示，失败则按字节 Debug 展示；None 显示 (nil)。因此终端外观不是原始 RESP 数据。PUBLISH 丢弃 API 返回的接收者数量，只打印 Publish OK，不能据此判断有人订阅。

SUBSCRIBE 先检查列表非空，再消费 Client 得到 Subscriber，while let 持续读取消息。普通 GET/SET 执行后 main 返回，订阅分支则会长时间停留在循环里。该 CLI 没有单独的 unsubscribe 子命令，库支持这个方法不代表 CLI 必然支持。

## 同名 Command 不能混淆

这里的 Command 是 clap 派生的命令行参数类型；src/cmd/mod.rs 的 Command 是服务端从 Frame 解析出来的业务指令。它们不会通过内存直接互传。新增命令时，若只增加服务端枚举，网络调用可以另外编写，但这个 CLI 不会自动拥有新子命令。

main 使用 current_thread runtime；`duration_from_ms_str` 先 parse u64 再 Duration::from_millis，解析失败由 clap 阻止启动业务调用。连接错误或命令错误经 `?` 返回 main，不会自动重试。

## 这里的 Rust 写法：enum、derive 和 match 怎样接起来

clap 的 derive 宏读取 struct/enum 的声明和辅助属性，生成参数解析实现。`match cli.command` 消费命令枚举，并把 String/Bytes 等字段交给分支。`Some(duration)` 与 None 是 Option 的不同变体，不是两个命令。`&str` 参数临时借用键，value: Bytes 则转移值的所有权。

需要拆开语法时，接着读 [Rust 阅读说明的对应小节](/mini-redis/rust-reading-guide.md#macros)。

## 读完后沿哪里继续

[src/clients/client.rs](/mini-redis/source/src/clients/client.md) → [src/cmd/mod.rs](/mini-redis/source/src/cmd/mod.md) → [src/bin/server.rs](/mini-redis/source/src/bin/server.md)。

跨文件串读：[第 01 章：实际运行](/mini-redis/01-first-run.md)。
