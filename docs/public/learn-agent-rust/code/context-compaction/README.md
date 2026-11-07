# R08：上下文压缩

这是网站第 8 章的独立实验工程，正文以 `docs/learn-agent-rust/context-compaction.md` 为准。

## 运行

安装 Rust 1.99.1（含 rustfmt、clippy）。解压后进入本目录：

```sh
cargo fetch --locked
cargo run --locked
cargo run --locked -- naive-trim
cargo run --locked -- retrieve
cargo run --locked -- omit-fact
cargo test --locked
cargo clippy --locked --all-targets -- -D warnings
```

首次获取工具链、crate 和 Git 依赖需要网络。依赖缓存后可用 `cargo run --locked --offline`；Debian / Ubuntu 构建原生 TLS 依赖需要 `pkg-config libssl-dev` 及系统编译工具。完整安装步骤见网站 `/learn-agent-rust/setup`。

Cargo.toml 固定与 R02、R07 相同的 graph-flow / langchain-rust Git revision，Cargo.lock 固定传递依赖。无 API key、HTTP 请求、数据库、GPU 或全局技能扫描。

## 观察

`normal`、`small`、`manual`、`micro-only`、`naive-trim`、`omit-fact`、`invent-fact`、`bad-json`、`summary-error`、`summary-large`、`summary-input-budget`、`archive-error`、`hard-budget`、`orphan`、`pending`、`retrieve`、`artifact-tamper`。

每个场景可加 `--json`：`cargo run --locked -- --json normal`。输出包含压缩阶段、实际传给 LLM 的消息、摘要调用计数、图节点、配对与文件校验。失败场景有意以报告里的 `stop` 表达预期的业务失败；非法 CLI 参数才返回非零进程状态。

- `main.rs`：读取真实临时练习文件，建立已结束的种子历史，实际 graph-flow 节点与 langchain-rust LLM trait。
- `compact.rs`：消息组校验、原始 JSONL 归档、工具结果落盘、旧结果占位、严格摘要候选与提交前预算检查。
- `tests.rs`：消息配对、事实与来源、失败不改历史、技能重新加载、后续用户约束、归档读取和同大小损坏检查。

临时文件由程序创建并在退出时清理。可检索归档只在同次实验有效，输出中的 a1 / a2 是本次运行的注册 ID；zip 内的 `outputs/` 与 `evidence.json` 保存网站实际实验记录。

## 实验口径

Agent 和摘要器都使用确定性脚本模型。预算单位是 `Vec<Message>` JSON 序列化后的 UTF-8 字节，单独预留 1024 字节；不是 provider token 计数或实际 HTTP 请求大小。摘要请求也有独立字节上限与调用上限，失败不重试。

本例事实清单针对固定审查任务预先定义，由应用关联到真实读取结果；严格匹配验证保留与篡改，不自动判断任意文本的语义真实性。原始首条用户消息和后续用户消息保留原样；摘要以历史资料身份进入 human 消息，工具策略位于 World。路径和 SHA-256 检查针对自建静态目录，不提供跨进程文件竞争防护、作者身份认证或进程崩溃后的恢复。
