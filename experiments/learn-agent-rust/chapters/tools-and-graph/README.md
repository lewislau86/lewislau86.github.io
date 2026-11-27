# R02：工具注册与图调度（ADK-Rust 3.0）

课程正文：https://lewislau86.github.io/learn-agent-rust/tools-and-graph

本目录是独立 Cargo 工程。模型是 ADK-Rust 的 `ScriptedLlm`（按固定脚本回复，不读凭据、不联网），
文件工具读取程序自己创建的临时目录。每个场景跑两遍：一遍用 `Runner` 直接运行 `LlmAgent`，
一遍把同一个 Agent 放进 adk-graph 的图（`assistant` → `check_answer`），比较两遍的事件轨迹、
模型收到的请求和停止原因。

## 准备 ADK-Rust 源码

ADK-Rust 3.0 还没有发布到 crates.io。`.cargo/config.toml` 用 path patch 指向本目录旁边的
`adk-rust/`，所以先把固定提交的源码取到那里（全书代码库的 `python3 run.py doctor` 会代办）：

```sh
python3 fetch-adk-rust.py ../adk-rust     # 脚本在网站仓库 scripts/ 下，也随全书代码库提供
```

cargo 只读取当前目录及上级目录里的 `.cargo/config.toml`，所以下面的命令都要在本目录里运行。

## 运行

```sh
cargo run --locked                         # 14 个场景的摘要，外加正常场景的完整轨迹
cargo run --locked -- --trace normal       # 一个场景的事件轨迹和模型请求
cargo run --locked -- --json batch         # 一个场景两条路径的完整对照（JSON）
cargo test --locked
cargo fmt --check
cargo clippy --locked --all-targets -- -D warnings
```

场景名：normal、batch、unknown-tool、invalid-args、extra-field、invalid-json、not-an-object、outside-path、
missing-file、unreadable-file、unreadable-file-exposed、duplicate-id、zero-budget、turn-limit。

`rust-toolchain.toml` 固定 Rust 1.99.1；`Cargo.lock` 固定全部依赖。编译时会看到 adk-core 的
3 条 `fetch_update` 弃用警告（上游固定 1.95.0），不影响本章代码的检查。

## 实验边界

- 工具调用来自固定脚本，没有测量真实模型选工具的能力。
- 同轮多个调用由框架按默认策略（Sequential）执行；本章没有测量并发耗时。
- 会话只在内存里（`InMemorySessionService`），没有持久化与跨进程恢复。
- 工具只接受 `.` 和 `README.md`；canonicalize 检查面向程序自建的可信临时目录，
  不是防止外部进程竞争修改文件的完整沙箱。
- `verified` 只检查本例回答里的命令与真实读到的 README 一致。

网站维护者在仓库根目录运行 `python3 scripts/verify-learn-agent-rust-r02.py`，会在临时解压目录
（旁边放好 `adk-rust/`）构建、测试并生成输出、证据与下载包；`--check` 重新执行并检查产物是否过期。
