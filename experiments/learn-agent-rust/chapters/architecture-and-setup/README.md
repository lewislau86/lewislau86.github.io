# R00：整体架构与环境（ADK-Rust 3.0）

课程正文：https://lewislau86.github.io/learn-agent-rust/architecture-and-setup

一次“读取 README.md，告诉我如何启动项目”的完整往返：ADK-Rust 的 `ScriptedLlm` 按固定脚本提出读取请求并回答，
`FunctionTool` 真实读取程序自建的临时目录，`DeclarativePolicy` 决定允许还是拒绝，`Runner` 把它们接起来，
会话放在内存里。程序不读取模型凭据，不访问外部服务。

## 准备 ADK-Rust 源码

ADK-Rust 3.0 还没有发布到 crates.io。`.cargo/config.toml` 用 path patch 指向本目录旁边的 `adk-rust/`：

```sh
python3 fetch-adk-rust.py ../adk-rust     # 需要 git 与 GitHub 访问；不行时加 --method cdn
```

cargo 只读取当前目录及上级目录里的 `.cargo/config.toml`，下面的命令都要在本目录里运行。

## 运行

```sh
cargo run --locked                    # 正常：读取并回答
cargo run --locked -- --deny          # 应用策略拒绝读取
cargo run --locked -- --missing-file  # 练习目录里没有 README
cargo test --locked
cargo fmt --check
cargo clippy --locked --all-targets -- -D warnings
```

`rust-toolchain.toml` 固定 Rust 1.99.1；`Cargo.lock` 固定全部依赖。编译时会看到 adk-core 的
3 条 `fetch_update` 弃用警告（上游固定 1.95.0），不影响本章代码的检查。

## 实验边界

- 模型回复来自固定脚本，只验证接线与失败分支，不代表真实模型的能力。
- 策略只有“允许 / 拒绝 read_file”两种；工具只接受 `README.md`。这不是通用沙箱。
- 会话只在内存里，进程退出后不保留；三种模式进程都以退出码 0 结束，任务结果看 `outcome`。

网站维护者在仓库根目录运行 `python3 scripts/verify-learn-agent-rust.py`，`--check` 检查产物是否过期。
