# D02 · 提示链与条件路由（ADK-Rust 3.0）

教程：https://lewislau86.github.io/learn-agent-rust/prompt-chaining-routing

用户交来一个文件（第一行写“文件：名字 修订：rN”）。先按类型路由到对应的处理链，链里依次“抽取 → 质量门 → 写报告”：

- 路由有三种：`LlmConditionalAgent`（模型回一个标签）、`ConditionalAgent`（代码按文件名判断）、
  `DecisionAgent`（模型在列出的选项里选，并给出置信度，低于门槛走兜底）；
- 抽取是带 `output_schema` 的 `LlmAgent`，不合格就带着纠正提示重试，重试用完以错误结束；
- 质量门是一个 `CustomAgent`：产物必须属于这次输入的文件和修订、类别与本链一致，否则把事件标成 escalate（上报），写报告那一步不再运行。

模型是按规则回复的替身，只看自己收到的请求。

## 准备 ADK-Rust 源码

```sh
python3 fetch-adk-rust.py ../adk-rust     # 需要 git 与 GitHub 访问；不行时加 --method cdn
```

下面的命令都要在本目录里运行（cargo 只读取当前目录及上级目录的 `.cargo/config.toml`）。

## 运行

```sh
cargo run --locked                    # 全部 10 个场景的摘要
cargo run --locked -- stale           # 某个场景的完整轨迹
cargo test --locked
cargo fmt --check
cargo clippy --locked --all-targets -- -D warnings
```

`rust-toolchain.toml` 固定 Rust 1.99.1；`Cargo.lock` 固定全部依赖。
编译时会看到 adk-core 的 3 条 `fetch_update` 弃用警告（上游固定 1.95.0），不影响本章代码的检查。

## 实验边界

- 分类、决定和抽取都由替身模型按规则给出；真实模型的分类准确率没有测试。
- 置信度是模型自报的数字，不是校准过的概率。
