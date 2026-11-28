# D05 · 协调者、工作者与任务交接（ADK-Rust 3.0）

教程：https://lewislau86.github.io/learn-agent-rust/orchestrator-workers-handoffs

升级审查团队用 `TeamSpec`（写成 JSON）声明三个成员：协调者 lead、工作者 member_check、许可证专员 license。

- lead → member_check 是**委派**：框架把 member_check 包装成工具，lead 按成员清单一次发出几个调用，结果交回 lead 汇总；
- lead → license 是**交接**：lead 调用 `transfer_to_agent`，控制权留在 license，下一轮也由它回答；
- `CompiledTeam` 为每次运行记一份执行回执，可以做关系覆盖分析，中断后给出恢复计划。

三个成员都是 `LlmAgent`，模型是按规则回复的替身；工作者每次请求先停一小会儿，让委派真正重叠。
程序使用暂停的 Tokio 时钟（`start_paused`）：停顿按到期先后推进，完成顺序在任何机器上都一样。

## 准备 ADK-Rust 源码

```sh
python3 fetch-adk-rust.py ../adk-rust     # 需要 git 与 GitHub 访问；不行时加 --method cdn
```

下面的命令都要在本目录里运行（cargo 只读取当前目录及上级目录的 `.cargo/config.toml`）。

## 运行

```sh
cargo run --locked                    # 全部 10 个场景的摘要
cargo run --locked -- handoff         # 某个场景的完整轨迹
cargo test --locked
cargo fmt --check
cargo clippy --locked --all-targets -- -D warnings
```

`rust-toolchain.toml` 固定 Rust 1.99.1；`Cargo.lock` 固定全部依赖。
编译时会看到 adk-core 的 3 条 `fetch_update` 弃用警告（上游固定 1.95.0），不影响本章代码的检查。

## 实验边界

- 分工与交接的决定由替身模型按规则做出；真实模型怎样分工、交接得好不好没有测试。
- 停顿在暂停的时钟上推进，不消耗真实时间，也不代表真实服务的耗时。
