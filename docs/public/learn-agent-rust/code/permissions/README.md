# R03：工具权限与审批（ADK-Rust 3.0）

课程正文：https://lewislau86.github.io/learn-agent-rust/permissions

同一份工具请求先过应用策略：允许、拒绝，或等待人批准。策略是文件里的 `SummaryPolicy`（实现 ADK-Rust 的
`ToolPolicy`），装在 `Runner` 上；需要批准的调用被框架挂起，请求记进 `InMemoryApprovalStore`；审批人按请求的指纹
记下决定，下一次运行恢复原来那次调用。模型是 `ScriptedLlm`；文件工具读写程序自建的临时目录；不读取凭据、不联网。

## 准备 ADK-Rust 源码

```sh
python3 fetch-adk-rust.py ../adk-rust     # 需要 git 与 GitHub 访问；不行时加 --method cdn
```

下面的命令都要在本目录里运行（cargo 只读取当前目录及上级目录的 `.cargo/config.toml`）。

## 运行

```sh
cargo run --locked                 # approve：等待 → 批准 → 恢复后写入
cargo run --locked -- wait
cargo run --locked -- tamper
cargo run --locked -- replay
cargo test --locked
cargo fmt --check
cargo clippy --locked --all-targets -- -D warnings
```

场景：read、deny、invalid-path、unknown、wait、approve、decline、tamper、replay、write-error。

`rust-toolchain.toml` 固定 Rust 1.99.1；`Cargo.lock` 固定全部依赖。编译时会看到 adk-core 的
3 条 `fetch_update` 弃用警告（上游固定 1.95.0），不影响本章代码的检查。

## 实验边界

- 模型请求与审批人的决定都是固定输入；没有真实的审批界面或身份认证。
- 审批记录只在内存里（`InMemoryApprovalStore`），进程退出就没了；跨进程恢复见第 6、21 章。
- 路径规则面向程序自建的可信临时目录，不是通用沙箱。

网站维护者在仓库根目录运行 `python3 scripts/verify-agent-permissions.py`，`--check` 检查产物是否过期。
