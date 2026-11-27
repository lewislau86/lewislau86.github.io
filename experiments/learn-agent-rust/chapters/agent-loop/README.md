# R01：最小 Agent 循环（ADK-Rust 3.0）

课程正文：https://lewislau86.github.io/learn-agent-rust/agent-loop

`LlmAgent` 在 `Runner` 里运行“调用模型 → 执行工具 → 把结果交回模型 → 再调用模型”的循环。
本章的模型是文件里的 `RuleLlm`：它实现 ADK-Rust 的 `Llm` trait，只根据收到的请求内容按规则回复，
所以回答只能来自它在请求里看到的工具结果：读到了就照实回答，读不到就转述工具给出的错误。工具读取程序自建的临时目录；会话只在内存里；不读取凭据、不联网。

## 准备 ADK-Rust 源码

ADK-Rust 3.0 还没有发布到 crates.io。`.cargo/config.toml` 用 path patch 指向本目录旁边的 `adk-rust/`：

```sh
python3 fetch-adk-rust.py ../adk-rust     # 需要 git 与 GitHub 访问；不行时加 --method cdn
```

下面的命令都要在本目录里运行（cargo 只读取当前目录及上级目录的 `.cargo/config.toml`）。

## 运行

```sh
cargo run --locked                                             # normal
cargo run --locked -- --scenario changed-readme
cargo run --locked -- --max-model-calls 1
cargo run --locked -- --scenario repeat --max-tool-calls 2
cargo run --locked -- --scenario two-tools --max-tool-calls 1
cargo run --locked -- --scenario repeat --max-iterations 3       # 循环上限
cargo test --locked
cargo fmt --check
cargo clippy --locked --all-targets -- -D warnings
```

场景：normal、changed-readme、missing-file、repeat、two-tools、duplicate-id、unknown-tool、invalid-path
（model-error 只在测试里用，命令行不接受）。预算参数：`--max-model-calls N`、`--max-tool-calls N`；循环上限：`--max-iterations N`。
注意 `repeat` 不加任何限制时会一直读到默认的 100 轮上限，请配合上述参数之一运行。

`rust-toolchain.toml` 固定 Rust 1.99.1；`Cargo.lock` 固定全部依赖。编译时会看到 adk-core 的
3 条 `fetch_update` 弃用警告（上游固定 1.95.0），不影响本章代码的检查。

## 实验边界

- 模型是规则程序，不代表真实模型的选择能力；它只证明循环、计数、配对和停止条件。
- 预算只覆盖模型调用次数与工具调用次数；没有 token、费用、时间预算，也没有并发。
- 会话只在内存里，没有保存与恢复；进程退出码 0 只说明实验跑完，任务结果看“停止”与 `fixture_goal_met`。
- 调用 ID 用来配对请求与结果，不是业务幂等键；框架也不检查它是否重复。

网站维护者在仓库根目录运行 `python3 scripts/verify-learn-agent-rust-loop.py`，`--check` 检查产物是否过期。
