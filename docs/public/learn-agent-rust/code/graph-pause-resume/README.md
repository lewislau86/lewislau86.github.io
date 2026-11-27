# G02 · 图暂停、检查点存储与跨进程恢复（ADK-Rust 3.0 / adk-graph）

教程：https://lewislau86.github.io/learn-agent-rust/graph-pause-resume

升级审查：`draft` 写提案 → `approve` 暂停等人决定 → `render` 生成报告，或 `reject`，或 `revise` 回到 `draft`。
每条命令都是一个独立进程，状态只在 SQLite 检查点文件（adk-graph 的 `SqliteCheckpointer`）里。节点是确定性规则，不调用模型。

## 准备 ADK-Rust 源码

```sh
python3 fetch-adk-rust.py ../adk-rust     # 需要 git 与 GitHub 访问；不行时加 --method cdn
```

下面的命令都要在本目录里运行（cargo 只读取当前目录及上级目录的 `.cargo/config.toml`）。

## 运行

```sh
cargo build --locked
B=${CARGO_TARGET_DIR:-target}/debug/graph-resume-lab
mkdir -p /tmp/g02 && rm -f /tmp/g02/review.db /tmp/g02/runs.log   # SQLite 不会自动建目录；重跑前清掉旧线程
$B /tmp/g02/review.db init                     # 停在 approve，打印暂停 ID
$B /tmp/g02/review.db show                     # 重新进入 approve，同一个暂停 ID
$B /tmp/g02/review.db answer <暂停ID> approve  # 严格恢复：只认这个暂停的 ID
$B /tmp/g02/review.db show                     # 已完成的线程：直接返回最终状态，不再运行节点
cargo test --locked
cargo fmt --check
cargo clippy --locked --all-targets -- -D warnings
```

其他命令：`answer <ID> reject|revise`、`answer-loose approve`（按节点名回答，用于对照）、
`conflict <ID>`（两个写入者同时恢复同一个暂停）、`tamper corrupt|rename|rename-unchecked`（改坏检查点或换一版图）。
每条命令最后一行 `node_runs` 来自同目录的 `runs.log`，记录每个节点真正执行了几次。

`rust-toolchain.toml` 固定 Rust 1.99.1；`Cargo.lock` 固定全部依赖；SQLite 随依赖编译，需要 C 编译工具。
编译时会看到 adk-core 的 3 条 `fetch_update` 弃用警告（上游固定 1.95.0），不影响本章代码的检查。

## 实验边界

- 审批人的回答由命令行给出，没有身份认证；只有一个业务执行者。
- 冲突实验在一个进程里用两张图对象模拟两个写入者，共用同一个 SQLite 文件。
- 版本检查（`graph_version`）是本章宿主代码做的，框架本身不检查。
