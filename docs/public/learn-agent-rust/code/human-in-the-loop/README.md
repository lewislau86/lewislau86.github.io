# D07 · 人工介入与审批恢复（ADK-Rust 3.0）

教程：https://lewislau86.github.io/learn-agent-rust/human-in-the-loop

发布流程是一个 `SequentialAgent`：写作者（`LlmAgent`）→ 版本检查（`CustomAgent`）→ 发布者（`LlmAgent`，调用 `publish_report`）。
应用策略要求每次发布都先经人批准：调用被挂起，运行结束。会话（`SqliteSessionService`）和审批记录（`SqliteApprovalStore`）
放在同一个 SQLite 文件里，下一步（或下一个进程）读出等待中的请求、记下决定，再恢复运行。

模型是按规则回复的替身；发布写的是工作目录里的真实文件。

## 准备 ADK-Rust 源码

```sh
python3 fetch-adk-rust.py ../adk-rust     # 需要 git 与 GitHub 访问；不行时加 --method cdn
```

下面的命令都要在本目录里运行（cargo 只读取当前目录及上级目录的 `.cargo/config.toml`）。

## 运行

```sh
cargo run --locked                    # 全部 8 个场景的摘要
cargo run --locked -- changed-mind    # 某个场景的完整轨迹
cargo test --locked
cargo fmt --check
cargo clippy --locked --all-targets -- -D warnings
```

每条命令一个进程（状态只在 `/tmp/d07` 里的 SQLite 文件中）：

```sh
cargo run --locked -- disk /tmp/d07 start "写 3.0 的升级说明并发布"
cargo run --locked -- disk /tmp/d07 pending
cargo run --locked -- disk /tmp/d07 edit "升级到 3.0：把 member 的启动命令改成 serve，并更新 CI 脚本。"
cargo run --locked -- disk /tmp/d07 resume
cargo run --locked -- disk /tmp/d07 show
```

其他审批动作：`approve`、`deny 理由`、`edit-target 路径`、`revoke 理由`；用户消息：`say 消息`。

`rust-toolchain.toml` 固定 Rust 1.99.1；`Cargo.lock` 固定全部依赖。
编译时会看到 adk-core 的 3 条 `fetch_update` 弃用警告（上游固定 1.95.0），不影响本章代码的检查。

## 实验边界

- 没有用户认证：谁在审批由命令行决定；真实应用要先确认审批人的身份与权限。
- 同一时间只有一个写者；没有外部发布服务，发布只写本地文件。
