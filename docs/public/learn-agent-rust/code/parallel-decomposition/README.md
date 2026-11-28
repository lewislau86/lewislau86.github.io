# D03 · 并行分解与结果归并（ADK-Rust 3.0）

教程：https://lewislau86.github.io/learn-agent-rust/parallel-decomposition

升级审查同时检查三件互不依赖的事：文档（docs）、依赖（deps）、配置（config）。

- `ParallelAgent` 同时运行三个检查者（`LlmAgent`），每个用 `output_key` 把发现写进自己的状态键；
- 外层 `SequentialAgent` 再运行归并（`CustomAgent`）：成员齐全、修订一致，才按成员顺序写出报告，否则把事件标成 escalate（上报）。

模型是按规则回复的替身：每次请求先停 30–110 毫秒（让三个分支真正重叠），再回一个 JSON 发现；它同时记录同一时刻有几次请求在进行。
程序使用暂停的 Tokio 时钟（`start_paused`）：停顿按到期先后推进，完成顺序在任何机器上都一样。

## 准备 ADK-Rust 源码

```sh
python3 fetch-adk-rust.py ../adk-rust     # 需要 git 与 GitHub 访问；不行时加 --method cdn
```

下面的命令都要在本目录里运行（cargo 只读取当前目录及上级目录的 `.cargo/config.toml`）。

## 运行

```sh
cargo run --locked                    # 全部 7 个场景的摘要
cargo run --locked -- failure         # 某个场景的完整轨迹
cargo test --locked
cargo fmt --check
cargo clippy --locked --all-targets -- -D warnings
```

`rust-toolchain.toml` 固定 Rust 1.99.1；`Cargo.lock` 固定全部依赖。
编译时会看到 adk-core 的 3 条 `fetch_update` 弃用警告（上游固定 1.95.0），不影响本章代码的检查。

## 实验边界

- 停顿只是为了让分支重叠，不代表真实服务的耗时，也不用来推算加速比。
- 停顿在暂停的时钟上推进，不消耗真实时间；完成顺序只由停顿长短决定。
