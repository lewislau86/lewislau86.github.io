---
editLink: false
---

# examples/hello_world.rs：从业务入口走进 SET/GET

<!-- analyzes: examples/hello_world.rs -->

[打开对应源码](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/mini-redis/source/examples/hello_world.rs) · [源码文章索引](/mini-redis/source/index.md) · [总目录](/mini-redis/index.md)

这是最短的异步客户端示例。虽然文件顶部注释称它为 server，实际 main 只连接已有服务，不创建监听器。阅读时以执行代码为准。

## 它和哪些代码交互

```text
cargo run --example hello_world → Tokio main
 → Client::connect(127.0.0.1:6379) → set(hello, world) → get(hello)
 ← Option<Bytes> → 打印 is_some → 返回并释放连接
```

## 完整入口里有三次网络等待

<!-- source: examples/hello_world.rs:18-32; comments omitted -->
```rust
#[tokio::main]
pub async fn main() -> Result<()> {
    let mut client = Client::connect("127.0.0.1:6379").await?;

    client.set("hello", "world".into()).await?;

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

## 读完后沿哪里继续

[src/clients/client.rs](/mini-redis/source/src/clients/client.md) → [src/cmd/set.rs](/mini-redis/source/src/cmd/set.md) → [src/cmd/get.rs](/mini-redis/source/src/cmd/get.md) → [tests/client.rs](/mini-redis/source/tests/client.md)。

跨文件串读：[第 03 章：沿着 SET/GET 走一遍](/mini-redis/03-request-path.md)。
