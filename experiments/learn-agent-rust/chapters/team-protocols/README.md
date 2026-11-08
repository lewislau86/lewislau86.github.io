# R16：团队协作协议

这是 Learn Agent by Rust 第十六章的独立协议实验。网站正文是教学内容的唯一来源。

## 运行

需要 Rust 1.99.1（`rust-toolchain.toml` 会选择该版本）。保留 Cargo.lock。

```sh
cargo fetch --locked
cargo run --locked
cargo run --locked -- resubmit
cargo run --locked -- shutdown-timeout
cargo run --locked -- --json normal
cargo test --locked
cargo clippy --locked --all-targets -- -D warnings
```

依赖下载齐后可以添加 `--offline`。不需要 API Key、GPU、数据库、graph-flow 或 langchain-rust。只需 Tokio、Serde、SHA-256 和 tempfile；首次获取依赖需要网络。这是独立的协议内核，承接 R15 的有界邮箱与成员生命周期设计，没有复制 R15 的模型循环或私有历史。

默认运行创建两个 current-thread Tokio 异步队友，让 core 提交计划，Lead 批准，执行端检查原计划摘要和工具权限后创建临时 review.txt，随后对两位队友发起关闭握手并等待所有句柄。命令不修改当前目录的项目文件；所有文件位于程序自建的临时目录。

## 28 个场景

normal、unapproved、rejected、resubmit、wrong-sender、wrong-recipient、wrong-kind、unknown-request、duplicate-request、duplicate-response、late-response、expired-grant、changed-plan、replay-write、forbidden-path、progress-injection、cancel-request、shutdown-rejected、shutdown-timeout、shutdown-panic、ack-without-exit、abort-fallback、shutdown-freeze、mailbox-full、schema-errors、request-limit、clock-regression、write-failed。

`shutdown-panic` 故意让 core panic；stderr 的 panic 信息是预期输入，主程序捕获 JoinError，报告该请求 Failed 并继续回收队友。`abort-fallback` 故意让异步任务忽略协作取消，100ms 后 abort 并 await。其余场景不应发生 abort。

## 文件与状态边界

- `protocol.rs`：五种类型化消息、关联身份、请求状态、计划摘要、期限与写入门控。
- `runtime.rs`：绑定发送者的 Endpoint、容量为 2 的成员邮箱、容量为 64 的上行事件通道、唯一 Lead 消费入口、watch 取消和 JoinHandle。
- `main.rs`：确定性控制器、28 个实验场景、文件证据和稳定输出。
- `tests.rs`：15 项行为测试，包括修改实际写入内容、现有文件保护、满邮箱回滚、关闭与异常回收。

期限采用控制器注入的单调逻辑 tick，默认 ttl=10，tick 没有秒的含义；控制器负责在消息处理与执行前更新时钟。`shutdown-timeout` 还实际执行一次 20ms 接收超时，随后把协议时钟推进到期限。两项检查分别证明状态机到期与异步等待超时，不是生产环境的自动计时服务。

计划摘要是对 Serde 生成的 Plan JSON 字节计算 SHA-256，绑定 revision/path/content，仅供本 Rust 实现内一致性校验，不是签名或跨语言规范化编码。审批只允许 core 在工具白名单内用 create_new 创建 review.txt；未经批准、计划变化、超期和重放都被拒绝。文件操作是同步的小型本地实验：进入 Executing 后遇到 I/O 错误标为 Failed，不自动重试；没有通用回滚、断电耐久性或分布式 exactly-once 保证。

关闭请求入队即冻结该成员的新计划并撤销未执行批准；拒绝关闭后恢复接收，但旧计划须换新 ID 重提。Approved 只记回复结果；真正退出以 JoinHandle 为准。清理阶段还会取消未完成请求，最后才删除临时目录。

所有协议记录和去重 ID 仅在内存中；每次运行最多 16 条记录，终态仍占额度。事件日志供这 28 个有限实验使用，不是无上限服务的留存方案。Endpoint 由可信应用创建，不提供外部身份认证、进程沙箱或真实模型抗注入保证。

在网站仓库运行 `python3 scripts/verify-agent-protocols.py --check` 可复验输出、源码摘要、15 项测试、Clippy、离线运行与最终下载包。配图由 `python3 scripts/generate-learn-agent-rust-figures.py --lesson R16` 生成。
