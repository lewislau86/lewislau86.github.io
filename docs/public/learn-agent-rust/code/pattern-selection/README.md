# D01 · 模式选择：单次调用、固定工作流与自主循环（ADK-Rust 3.0）

教程：https://lewislau86.github.io/learn-agent-rust/pattern-selection

同一个任务：根据工作区里的 README 写一份升级报告，并列出依据的文件。三种结构：

- **单次调用**：一个没有工具的 `LlmAgent`，资料随问题一起给出；
- **固定工作流**：`SequentialAgent` 串起两个由代码读文件的 `CustomAgent` 和一个写报告的 `LlmAgent`，
  步骤之间靠会话状态传递，读不到文件就把事件标成 escalate（上报）让整个工作流停下；
- **自主循环**：一个带 `read_file` 工具的 `LlmAgent`，读什么、读几次由模型决定，`max_iterations` 限制模型调用次数。

模型是按规则回复的替身；文件真实写在临时目录里。最后由应用验收：报告必须引用根 README“成员：”一行列出的每个成员。

## 准备 ADK-Rust 源码

```sh
python3 fetch-adk-rust.py ../adk-rust     # 需要 git 与 GitHub 访问；不行时加 --method cdn
```

下面的命令都要在本目录里运行（cargo 只读取当前目录及上级目录的 `.cargo/config.toml`）。

## 运行

```sh
cargo run --locked                    # 全部 9 个场景的摘要
cargo run --locked -- adaptive        # 某个场景的完整轨迹
cargo test --locked
cargo fmt --check
cargo clippy --locked --all-targets -- -D warnings
```

`rust-toolchain.toml` 固定 Rust 1.99.1；`Cargo.lock` 固定全部依赖。
编译时会看到 adk-core 的 3 条 `fetch_update` 弃用警告（上游固定 1.95.0），不影响本章代码的检查。

## 实验边界

- 模型调用次数来自替身模型，用来比较结构，不代表真实模型的成本或质量。
- 三种结构用的输入不完全相同（单次调用的资料由用户给出），比较的是“哪种结构能完成哪种输入”，不是谁更省。
