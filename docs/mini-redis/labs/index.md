---
editLink: false
---

# 配套实验

[返回笔记目录](/mini-redis/index.md)

所有命令从仓库根目录执行。此目录是独立 Cargo package，通过路径依赖使用当前仓库源码；不修改主项目的依赖、生产代码或原有测试。实验使用独立 Cargo.lock，直接依赖的 Tokio 1.32.0、bytes 1.5.0 与本次根锁文件对应版本一致。

先按[第 01 章](/mini-redis/01-first-run.md)启动 16379 上的服务，再运行最小客户端：

```sh
cargo run --locked --manifest-path docs/labs/Cargo.toml --bin hello_tokio
# 若服务选用了另一个端口，在命令末尾传入地址：
# -- 127.0.0.1:新端口
```

下面五个实验不需要提前启动服务：

```sh
cargo run --locked --manifest-path docs/labs/Cargo.toml --bin ownership
cargo run --locked --manifest-path docs/labs/Cargo.toml --bin frames
cargo run --locked --manifest-path docs/labs/Cargo.toml --bin async_basics
cargo run --locked --manifest-path docs/labs/Cargo.toml --bin roundtrip
cargo run --locked --manifest-path docs/labs/Cargo.toml --bin multiplex
```

| 程序 | 需要先启动服务吗 | 观察点 |
| --- | --- | --- |
| [hello_tokio](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/mini-redis/source/docs/labs/src/bin/hello_tokio.rs) | 需要，默认连接 16379；可传入地址 | 用自己的 Rust 客户端完成连接、SET、GET |
| [ownership](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/mini-redis/source/docs/labs/src/bin/ownership.rs) | 不需要 | 移动、借用、字节句柄、共享所有权、锁作用域 |
| [frames](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/mini-redis/source/docs/labs/src/bin/frames.rs) | 不需要 | 每个不完整前缀、Null、非法 Bulk 长度、帧消费边界 |
| [async_basics](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/mini-redis/source/docs/labs/src/bin/async_basics.rs) | 不需要 | Future 惰性执行、依次 await、显式 runtime 与计时器 |
| [roundtrip](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/mini-redis/source/docs/labs/src/bin/roundtrip.rs) | 不需要，自建临时服务 | SET/GET、二进制值、TTL、覆盖、Pub/Sub、连续请求、停机 |
| [multiplex](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/mini-redis/source/docs/labs/src/bin/multiplex.rs) | 不需要，自建临时服务 | 8 个任务通过 BufferedClient 共享一个连接 |

hello_tokio 验证返回值后打印 `course = Some(b"rust")`，其余程序打印 `... OK`。roundtrip、multiplex 自建服务，监听本地临时端口并设置等待上界；hello_tokio 连接外部已启动的服务，保持入门示例的简短写法，没有额外设置超时。通过只代表对应行为在这次运行中成立，不构成协议全面验证、吞吐量测试或极端并发证明。

async_basics 的预期顺序是“两个 Future 已创建 → 执行 SET → SET 完成 → 执行 GET → OK”，其中 SET/GET 只是阶段名，没有发送网络命令。被创建后直接丢弃的那个阶段不应出现在输出里。

`src/lib.rs` 的 Server 只是实验公共辅助代码，核心算法仍来自主项目。`roundtrip` 的二进制断言只针对 GET/SET，订阅实验使用 UTF-8 文本。

## 故意失败的编译实验

```sh
rustc --edition=2018 --emit=metadata -o /tmp/mini-redis-moved.rmeta docs/labs/compile_fail/moved_value.rs
rustc --edition=2018 --emit=metadata -o /tmp/mini-redis-borrow.rmeta docs/labs/compile_fail/overlapping_borrow.rs
```

预期分别出现 E0382 与 E0502；这两条命令返回非零是学习预期，不是实验代码损坏。它们位于 Cargo 目标之外，不影响六个可运行程序。

阅读编译器指出的“值在这里移动”“借用在这里仍被使用”，然后在临时副本中尝试三种调整：借用而非移动、确实需要独立数据时 clone、让读取结束后再修改。每次都解释语义变化，不要仅为消除报错而到处 clone。

## 检查与排错

```sh
cargo fmt --manifest-path docs/labs/Cargo.toml --check
cargo check --locked --manifest-path docs/labs/Cargo.toml --bins
```

本次机器默认 stable 缺少 rustfmt，实际格式检查使用已有工具链：`cargo +1.98.1 fmt --manifest-path docs/labs/Cargo.toml --check`。一般环境若已安装 rustfmt，直接运行上面的命令即可。

依赖下载失败时先处理网络或本机缓存；不要因为锁文件限制而随意删掉锁文件。实验出现超时则查看是哪一步没有完成，结合对应源码与[验证记录](/mini-redis/validation.md)判断，不能仅增加等待时间就认为问题解决。
