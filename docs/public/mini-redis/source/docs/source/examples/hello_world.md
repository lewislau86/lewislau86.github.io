# examples/hello_world.rs：从业务入口走进 SET/GET

<!-- analyzes: examples/hello_world.rs -->

[打开对应源码](../../../examples/hello_world.rs) · [源码文章索引](../README.md) · [总目录](../../README.md)

这是最短的异步客户端示例。main 只连接已有服务，不创建监听器；中文注释已明确它是客户端入口。

## 它和哪些代码交互

```text
cargo run --example hello_world → Tokio main
 → Client::connect(127.0.0.1:6379) → set(hello, world) → get(hello)
 ← Option<Bytes> → 打印 is_some → 返回并释放连接
```

## 完整入口里有三次网络等待

<!-- source: examples/hello_world.rs:9-23; comments included -->
```rust
#[tokio::main]
pub async fn main() -> Result<()> {
    // 等待建连；Client 需要 mut，后续 set/get 都通过 &mut self 操作同一条连接。
    let mut client = Client::connect("127.0.0.1:6379").await?;

    // 目标参数类型是 Bytes，因此 .into() 将字符串转换为 Bytes。
    client.set("hello", "world".into()).await?;

    // GET 在 SET 成功返回后才执行；下方 is_some 只检查有值，没有断言值一定等于 world。
    let result = client.get("hello").await?;

    println!("got value from the server; success={:?}", result.is_some());

    Ok(())
}
```

main 宏建立 runtime，connect 返回 Client，mut 允许随后借用为 &mut self。字符串 .into() 根据 set 参数类型转换为 Bytes。每次 await 完成后才执行下一句，`?` 失败则提前返回，因此 GET 在 SET 的成功响应之后才发送。

## 在哪里看到真正的数据处理

set/get 的编码在 Client 和 cmd 文件中；此示例不接触 Db。服务端独立进程先监听 6379，再由 Handler 接收请求。运行时可以先在一个终端执行 `cargo run --locked --bin mini-redis-server`，另一个执行 `cargo run --locked --example hello_world`。这是运行方式说明，本轮没有重跑该示例。

示例固定 key 为 hello，连接已有实例会覆盖同名值。打印 success=true 只验证 Option 有值，并不比较是否等于 world；精确字节断言可对照 tests/client.rs。

## 沿它建立第一条完整路径

先进入 Client::set，再读 Set::into_frame、Connection::write_frame；穿过 TCP 后进入服务端 read_frame、Command::from_frame、Set::apply、Db::set。收到 OK 才返回此 main。GET 沿同一通路读取并生成 Bulk/Null，两条调用的服务器交互不在本文件中直接出现。

## 这里的 Rust 写法：从 await? 和 into 开始读调用

Client::connect 返回 Future；await 得到 Result，? 取 Client 或提前退出。字符串 .into() 的目标由 set 的 Bytes 参数推断。main 返回 Result<()>，末尾 Ok(()) 表示执行完成；println 的 is_some 只判断存在性，不替代精确值断言。

需要拆开语法时，接着读 [Rust 阅读说明的对应小节](../../rust-reading-guide.md#results)。

## 读完后沿哪里继续

[src/clients/client.rs](../src/clients/client.md) → [src/cmd/set.rs](../src/cmd/set.md) → [src/cmd/get.rs](../src/cmd/get.md) → [tests/client.rs](../tests/client.md)。

跨文件串读：[第 03 章：沿着 SET/GET 走一遍](../../03-request-path.md)。
