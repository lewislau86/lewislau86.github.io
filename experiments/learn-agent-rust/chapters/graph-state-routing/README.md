# G01 · 图状态、条件路由与有界循环（ADK-Rust 3.0 / adk-graph）

教程：https://lewislau86.github.io/learn-agent-rust/graph-state-routing

升级审查：准备初稿 → 检查等级 → 不够就修复再检查；达到要求就接受，修复额度用完就转人工。
节点是确定性的业务规则，不调用模型；图的执行、路由、归并规则、超步上限都是 adk-graph 的真实实现。

## 准备 ADK-Rust 源码

ADK-Rust 3.0 还没有发布到 crates.io。`.cargo/config.toml` 用 path patch 指向本目录旁边的 `adk-rust/`：

```sh
python3 fetch-adk-rust.py ../adk-rust     # 需要 git 与 GitHub 访问；不行时加 --method cdn
```

下面的命令都要在本目录里运行。

## 运行

```sh
cargo run --locked -- normal      # 一次修复后接受，逐个超步打印跑了哪个节点
cargo run --locked -- exhausted   # 修复无效，两次额度用完转人工；图仍然正常结束
cargo run --locked -- runaway     # 忘了计数的 bug：只有超步上限能停下它
cargo run --locked -- probes      # 建图检查与运行时检查各能发现什么
cargo test --locked
cargo fmt --check
cargo clippy --locked --all-targets -- -D warnings
```

`rust-toolchain.toml` 固定 Rust 1.99.1；`Cargo.lock` 固定全部依赖。编译时会看到 adk-core 的
3 条 `fetch_update` 弃用警告（上游固定 1.95.0），不影响本章代码的检查。

## 实验边界

- 等级是整数夹具，只验证编排语义，没有验证模型审查质量。
- 图在一次 `stream` / `invoke` 里跑到结束或出错；检查点只用内存版（`MemoryCheckpointer`），跨进程恢复见 G02。
- 计数通道按浮点数累加，读取时按数值处理。
