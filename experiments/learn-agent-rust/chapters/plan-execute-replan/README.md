# D04 · 规划、执行与动态重规划，以及计划模式（ADK-Rust 3.0）

教程：https://lewislau86.github.io/learn-agent-rust/plan-execute-replan

两部分：

1. **规划—执行—重规划**（Stable）：`LoopAgent` 每一轮先运行规划者（`LlmAgent`，用 `write_plan` 写计划、用 `exit_loop` 收工），
   再运行执行者（`CustomAgent`，执行计划里下一个待办步骤，结果记进账本）。计划由应用保管，`write_plan` 检查修订号、不许删改已完成的步骤。
2. **计划模式**（Beta，adk-harness）：会话从计划模式开始，只能读、不能改；模型调用 `exit_plan_mode` 提交计划，
   人批准后从下一轮起切到询问模式，改文件时再问一次人。

模型和“人”都是按规则回复的替身；README 与写出的文件真实存在于临时目录里。

## 准备 ADK-Rust 源码

```sh
python3 fetch-adk-rust.py ../adk-rust     # 需要 git 与 GitHub 访问；不行时加 --method cdn
```

下面的命令都要在本目录里运行（cargo 只读取当前目录及上级目录的 `.cargo/config.toml`）。

## 运行

```sh
cargo run --locked                         # 全部 7 个场景的摘要
cargo run --locked -- discover             # 某个场景的完整轨迹
cargo run --locked -- plan-mode-approved
cargo test --locked
cargo fmt --check
cargo clippy --locked --all-targets -- -D warnings
```

`rust-toolchain.toml` 固定 Rust 1.99.1；`Cargo.lock` 固定全部依赖。
编译时会看到 adk-core 的 3 条 `fetch_update` 弃用警告（上游固定 1.95.0），不影响本章代码的检查。

## 实验边界

- 计划由替身模型按规则写出；真实模型写出的计划质量没有测试。
- adk-harness 在 ADK-Rust 3.0 里是 Beta；计划模式的接口可能在小版本之间变化。
