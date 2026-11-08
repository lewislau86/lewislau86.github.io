# P02：外部操作的可靠性

Learn Agent by Rust 专题 2 的独立 Rust 实验，网站正文是唯一教学来源。

## 一次运行

安装 Rust 1.99.1，解压后进入本目录，保留 Cargo.lock：

```sh
cargo fetch --locked
cargo run --locked
cargo test --locked
cargo clippy --locked --all-targets -- -D warnings
```

依赖下载后可用 `cargo run --locked --offline`。SQLite 通过 rusqlite bundled 编译，无需安装 SQLite 服务，但需要本机 C 编译工具链。无需 API Key、模型、GPU、PostgreSQL、graph-flow 或 langchain-rust。

默认演示创建临时目录，先保存意图和 Outbox，向独立 provider 子进程创建工单，注入服务端提交后退出，再启动一个新客户端进程查询并恢复检查点。最后删除临时目录。输出 JSON 展示两个数据库的最终业务行和检查点。

## 手动复现实验

以下命令在你选择的空实验目录执行，会创建 client.sqlite 与 provider.sqlite。替换二进制路径或使用 `cargo run --locked --` 前缀：

```sh
cargo run --locked -- prepare client.sqlite '{"tenant":"course","operation_id":"review-42","title":"Review Rust timeout handling"}' key 0 none
cargo run --locked -- dispatch client.sqlite provider.sqlite course review-42 1 provider-after-commit
cargo run --locked -- inspect-client client.sqlite
cargo run --locked -- inspect-provider provider.sqlite
cargo run --locked -- recover client.sqlite provider.sqlite course review-42 2 none
```

故障 dispatch 预期返回 exit code 10，JSON error 为 outcome_unknown；provider 子进程以 82 退出。真实工单已经提交，Outbox 为 unknown。recover 按 tenant/operation_id 查询，验证唯一匹配的请求和摘要，存回回执并生成检查点。

CLI 参数：

- `prepare CLIENT_DB REQUEST_JSON key|none TICK FAULT`
- `dispatch CLIENT_DB PROVIDER_DB TENANT OPERATION_ID TICK FAULT`
- `recover CLIENT_DB PROVIDER_DB TENANT OPERATION_ID TICK FAULT`
- `apply PROVIDER_DB REQUEST_JSON key|none TICK FAULT`（直接调用服务，教学反例会绕过客户端保护）
- `query PROVIDER_DB TENANT OPERATION_ID none|hidden|unavailable`
- `expire PROVIDER_DB TICK`
- `inspect-client CLIENT_DB` / `inspect-provider PROVIDER_DB`

## 实验约定

`key` 模式服务将 (tenant, operation_id) 作为幂等键，同键不同参数拒绝；`none` 模式每次 apply 都会创建新行。工单行、回执缓存和幂等键在服务的一个 SQLite 事务内提交。服务缓存期限为首次成功时间 +100 tick；客户端从 prepare 时间起只允许100 tick 内发送，重复 prepare 不延长期限。tick 是确定性故障实验输入，不是秒。生产环境需采用真实 provider 的键作用域、保留期、失败语义与时间来源。

客户端 actions 与 outbox 同事务保存；服务成功后 Outbox 先变 acked，再把检查点、业务状态与 Outbox completed 同事务保存。所有发送先把状态落为 unknown 并增加累计尝试次数，最多 3 次，重启后不重置。unknown 的无幂等操作禁止自动重发；recover 只接受完整查询中唯一且参数匹配的结果。空查询、缺失结果或服务不可用仍保持 unknown，交人工处理；本程序不实现人工决策写入。

服务的所有 `apply` / `query` 由独立进程执行、只读写 provider DB；客户端只读写 client DB，并通过子进程 JSON stdout 获取结果。传输是本机 CLI 进程边界，没有 HTTP、网络超时、认证或第三方服务。`provider-after-commit` 是“服务退出导致没有返回 JSON”，不是实际丢包。查询 hidden/unavailable 是显式故障输入。物理断电、数据库损坏恢复、跨主机部署、完整 Agent 检查点与租约协议均未验证。

Outbox 的本地事务没有覆盖 provider DB；发送与外部业务提交之间仍有窗口。缓存到期后直接重放会生成第二张工单；对账也需要稳定客户引用和可靠服务查询。query 的 `complete` 是本实验契约，不能假定所有真实接口都有此字段或强一致性。回执摘要用于检测错配，不提供密码学认证。

进程退出点：prepare 的 between-local-writes / before-prepare-commit / after-prepare-commit；dispatch 的 before-send / after-response / after-ack / before-checkpoint-commit / after-checkpoint-commit；provider 的 before-commit / after-commit。dispatch 用 provider-before-commit / provider-after-commit 传递给子进程。bad-receipt 返回故意错配的回执供校验。

`committed_apply_calls` 只计 provider 事务已提交的 apply 行；提交前被终止的调用不在该计数中。累计客户端尝试、服务端调用提交、业务工单数量和检查点数量分别报告。

在网站仓库运行 `python3 scripts/verify-agent-effects.py` 会执行 29 个独立进程场景、11 项 Rust 测试、Clippy、独立 SQL 核验与最终下载包复验。`--check` 检查产物是否过期。配图用 `python3 scripts/generate-learn-agent-rust-figures.py --lesson P02` 生成。
