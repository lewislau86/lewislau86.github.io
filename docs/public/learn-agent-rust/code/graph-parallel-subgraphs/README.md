# G03 · 图并行、归并与子图（ADK-Rust 3.0 / adk-graph）

教程：https://lewislau86.github.io/learn-agent-rust/graph-parallel-subgraphs

发布前的两项检查（安全、许可证）并行运行，归并节点等两项都到齐后给出结论：都通过是 `ready`，
有一项不通过是 `blocked`，缺了一项是 `incomplete`。节点是确定性规则，不调用模型。

## 准备 ADK-Rust 源码

```sh
python3 fetch-adk-rust.py ../adk-rust     # 需要 git 与 GitHub 访问；不行时加 --method cdn
```

下面的命令都要在本目录里运行。

## 运行

```sh
cargo run --locked -- normal      # 两项检查在同一个超步里运行，merge 只运行一次
cargo run --locked -- failure     # 安全检查第一次失败：已完成的许可证检查保留，恢复时只重跑失败的节点
cargo run --locked -- collision   # 两个并行节点写同一个覆盖通道：丢了一次更新；换成计数通道就不丢
cargo run --locked -- subgraph    # 隔离的子图只交出声明的通道；写错通道名在父图编译时就被拒绝
cargo run --locked -- timeout     # 节点超时：失败，或者跳过后由 merge 判为 incomplete
cargo test --locked
cargo fmt --check
cargo clippy --locked --all-targets -- -D warnings
```

`rust-toolchain.toml` 固定 Rust 1.99.1；`Cargo.lock` 固定全部依赖。编译时会看到 adk-core 的
3 条 `fetch_update` 弃用警告（上游固定 1.95.0），不影响本章代码的检查。

## 实验边界

- 检查结果是固定夹具；“并行”指同一个超步里一起调度，本章没有测量耗时。
- 失败后的恢复用内存检查点（`MemoryCheckpointer`），在同一个进程里完成；跨进程恢复见 G02。
- 超时用 50 毫秒上限对一个睡眠 300 毫秒的节点，只验证框架的超时路径，不代表真实服务的时延。
