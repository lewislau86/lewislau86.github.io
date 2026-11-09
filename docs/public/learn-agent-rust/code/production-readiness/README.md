# P04 生产准入与演练

网站正文： https://lewislau86.github.io/learn-agent-rust/production-readiness

本目录是可独立运行的 Rust 工程。需要 Rust 1.99.1（edition 2024）、Python 3.9+ 标准库，以及 PostgreSQL **18** 服务端工具 `postgres/initdb/pg_ctl/psql/pg_dump/pg_restore`。
所有 Rust 依赖由 Cargo.lock 锁定；第一次编译需下载依赖。

```sh
cargo test --locked
cargo clippy --locked --all-targets -- -D warnings
cargo build --locked
python3 lab.py
```

工具不在 PATH 时先设置 `P04_PG_BIN`，例如 macOS Homebrew 安装可用 `export P04_PG_BIN=/opt/homebrew/opt/postgresql@18/bin`；Linux 通常为 `/usr/lib/postgresql/18/bin`。必须以普通用户运行（initdb 不允许 root）。

`lab.py` 只创建本次运行专用的两个 `/tmp/p04-pg-*` 集群，用权限 0700 的 Unix socket、本地 trust 与禁用 TCP 的配置；同端口但不同 socket 目录，互不连接。它不会连接现有数据库，也不会使用调用环境中已有的 P04_DATABASE_URL。退出时清理本次集群与子进程。专用 PostgreSQL 角色是演练管理员，不是生产权限配置。

结果在 `results/results.json`；时延的当次观测在 `results/measurements.json`，备份文件也只在本地 results。仓库发布的 outputs/ 与 evidence.json 是一次观测快照，重新运行结果目录不承诺与其时延相同。

Rust 负责固定身份映射、按租户/角色/审批修订授权、迁移事务、准入计数、租约/epoch 写入和健康检查。Python 负责启动真实 PostgreSQL、并发启动独立 Rust 进程、杀死或阻塞 worker、直接 SQL 断言、pg_dump/pg_restore 以及清理。

24 个场景按实验顺序运行，每轮 62 个独立 Rust CLI 进程，4 个 Rust 单元测试。完整场景见 results.json。负载固定 12 个并发请求、容量 4，所有请求返回后再结束接收的任务；百分位包含成功与拒绝，计时包含 CLI 启动和数据库连接，不是 Agent 或模型延迟。恢复计时只包含 pg_restore 到本地核对后 readiness，不是完整事故 RTO。

注意：fixture-* 是公开测试身份，不是真实认证；settings 的修改来自可信演练操作员。审批绑定已存在的不可变动作 ID 和 revision，不执行真实业务工具。结果账本与租约在同一 PostgreSQL 事务中，不包含远程副作用。负载只是一次容量边界演练；没有长期 daemon、HTTP、连接池、网络分区、跨地域、PITR、真实模型或 langchain-rust/graph-flow 集成。作业状态是实验预留位，不实现完整 Agent 任务调度。单次观测不证明生产容量或模型质量。

恢复使用隔离目标集群，源库已经停机，备份前 active=0 且 recovery=true。恢复后先保持不接单，核对会话、审批、作业与结果账本，再由演练操作员解除 recovery。故意丢失备份后的一次提交，按“1 条提交”报告数据缺口，不声称 RPO=0；没有外部系统对账，因此不能直接套用于真实付款、邮件或其他业务恢复。
