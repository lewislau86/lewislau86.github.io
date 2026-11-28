# D06 · 评估、反思与有界修复（ADK-Rust 3.0）

教程：https://lewislau86.github.io/learn-agent-rust/evaluator-reflection

两部分：

1. **生成—评估—修复**：`LoopAgent` 每一轮先运行写作者（`LlmAgent`，最终回答经 `output_key` 写进状态 `draft`），
   再运行评估者（`CustomAgent`，按三条固定规则检查，把反馈写进状态 `feedback`，第一稿另存为 `baseline`）。
   全部通过或没有进展就上报（escalate）停下；最多 3 轮。
2. **工具失败的反思**：adk-retry-reflect 插件在 `read_file` 失败时，把结果换成一段反思提示；
   同一参数最多 2 次，整次运行最多 3 次，超过后原始错误交给模型。

写作者和读文件的模型都是按规则回复的替身。

## 准备 ADK-Rust 源码

```sh
python3 fetch-adk-rust.py ../adk-rust     # 需要 git 与 GitHub 访问；不行时加 --method cdn
```

下面的命令都要在本目录里运行（cargo 只读取当前目录及上级目录的 `.cargo/config.toml`）。

## 运行

```sh
cargo run --locked                    # 全部 8 个场景的摘要
cargo run --locked -- new-error       # 某个场景的完整轨迹
cargo test --locked
cargo fmt --check
cargo clippy --locked --all-targets -- -D warnings
```

`rust-toolchain.toml` 固定 Rust 1.99.1；`Cargo.lock` 固定全部依赖。
编译时会看到 adk-core 的 3 条 `fetch_update` 弃用警告（上游固定 1.95.0），不影响本章代码的检查。

## 实验边界

- 评估规则只有三条，用来检验修复机制，不代表对真实报告的全面评分。
- 写作者与读文件的模型按规则回复；真实模型的修复质量没有测试。
