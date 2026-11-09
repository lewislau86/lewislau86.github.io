# R15：Agent 团队

正文唯一来源是网站 `docs/learn-agent-rust/agent-teams.md`。本目录是可独立解压运行的配套实验。

## 环境与运行

固定 Rust 1.99.1（rustfmt、clippy），沿用 R02 / R07 的两库 Git revisions。Tokio features 增加 `sync`、`time`；Cargo.lock 固定 Tokio 1.54.1 和其余传递依赖。

```sh
cargo fetch --locked
cargo run --locked
cargo run --locked -- persistent
cargo run --locked -- peer-message
cargo run --locked -- mailbox-full
cargo run --locked -- cancel-busy
cargo test --locked
cargo clippy --locked --all-targets -- -D warnings
```

首次下载工具链与依赖需要网络；缓存后可 `cargo run --locked --offline`。Debian / Ubuntu 如遇 openssl-sys 构建问题，需系统编译工具和 `pkg-config libssl-dev`。完整安装见网站 `/learn-agent-rust/setup`。运行时不需要 API key、数据库、GPU 或外部模型服务。

## 文件

- `team.rs`：成员注册、绑定身份的 Endpoint、有界 mpsc 邮箱、oneshot 回执、团队累计预算、watch 取消与 join。
- `worker.rs`：队友常驻循环、私有历史、真实 graph-flow / langchain-rust 接线、只读工具。
- `main.rs`：确定性 Lead 编排、临时源码/配置、22 个场景与结构化报告。
- `tests.rs`：持久历史、真实文件变化、满邮箱重投与关闭、两个等待中的模型并发、身份/权限和资源回收。

CLI 场景：`normal persistent peer-message mailbox-full unknown-member duplicate-member duplicate-message oversized-message message-budget model-budget tool-budget forbidden-path write-denied missing-file model-error context-budget turn-budget cancel-idle cancel-busy receiver-closed member-limit note-injection`。

加 `--json` 输出完整证据，例如 `cargo run --locked -- --json normal`。预期故障写在 `errors` / `receipt.status` 中，进程仍成功返回报告；非法命令行参数返回非零状态。

## 验证口径

一个 Rust 进程、一个 current-thread Tokio runtime。两个队友是并发异步任务；不宣称 CPU 多核并行。每个队友保留自己的消息历史，每次 Work 使用一个图驱动器推进该历史；底层 graph Session 按投递新建，不提供跨进程恢复。

Lead 是固定应用编排，队友 LLM 是确定性 fixture。它们真实调用临时目录的读取工具，汇报基于真实读取的文字；被审查文件的函数不会被执行，示例也不运行项目测试。跨成员通信只注入明确发送的 Note，队友全文历史不会被复制。

Endpoint 身份由可信应用绑定，API 本身可由可信应用为成员创建；它不是面对不可信客户端的身份认证。内容中自称 lead / system 不改变信封来源或写入权限。`note-injection` 只验证本例的角色和策略路径，不评估真实模型的抗注入质量。

邮箱容量为每位队友 2 条，消息正文序列化后不超过 512 字节，累计消息 16、模型尝试 16、工具尝试 8；每次 Work 最多 3 次模型尝试，每次模型输入消息 JSON 不超过 16000 字节。字节上限不是 provider token 或账单。满队列用 try_send 明确拒绝，不自动重投；消息 ID 只在成功入队后登记。去重仅在这次运行内有效。

取消独立于数据邮箱，可打断等待中的 async 模型。关闭时停止新投递，当前等待的工作返回 cancelled，未开始的队列项返回 cancelled_queued，再 join 全部句柄；2 秒内未退出才 abort 并等待。所有场景预期都不需要强制 abort。同步文件读取有大小限制，但不能被 watch 抢占；生产服务仍需单独设计阻塞 I/O、子进程与 deadline。

临时工作区由两个成员共享，应用工具各有固定读路径；这不是 OS 文件沙箱。退出时先 join，再关闭删除自建目录。本次进程退出后，邮箱、消息去重、历史与预算均不保存。
