# R20 完整 Agent 集成实验

教程：https://lewislau86.github.io/learn-agent-rust/integrated-agent

固定 Rust 1.99.1、graph-flow 与 langchain-rust 的 Cargo.toml 提交、rmcp 3.9.0、
MCP 2025-11-25，依赖由 Cargo.lock 固定。首次获取工具链与依赖需要网络。
需要 Git（支持 worktree 与 --initial-branch）、macOS 或 Linux；SQLite 使用 bundled，
无需数据库服务或模型密钥。父模型与 reviewer 都是实现 LLM trait 的确定性脚本模型。

```sh
cargo test --locked
cargo run --locked -- normal demo-normal
cargo run --locked -- read-retry demo-retry
cargo run --locked -- post-hook demo-post
cargo run --locked -- terminal-save-failed demo-save
cargo run --locked -- --json normal demo-json
```

最后一个参数必须是不存在的目录，父目录须存在。所有 Git 操作只针对这里新建的练习
repository 和 workspace。默认输出四行摘要，--json 输出完整证据；两种模式均在目录中
保留 run.json、tasks.sqlite、来源文件、协议诊断和可能存在的报告/归档。
清洁 worktree 自动移除，有报告时保留，供人工检查。实验不自动提交报告、合并或推送。
server 是内部 stdio 子命令，无需手动启动；它真实启动直属进程并经过 MCP 协议。

## 本轮集成的契约

| 机制 | 本轮真实执行 | 范围 |
| --- | --- | --- |
| 两库循环 | graph-flow 三节点 + langchain-rust 消息和 LLM trait | 脚本生成动作；未接真实 provider |
| 任务/调度 | 固定到期身份入 SQLite、重复去重、CAS 领取 | 不运行时区调度器、租约接管或重启恢复 |
| 工作区 | 新建 Git repo 和 linked worktree，写前核对 owner/epoch/分支/根目录 | 可信单进程；不是恶意代码沙箱 |
| 来源 | 真实 skill/memory JSON，SHA 校验、human 资料与 system 策略分层 | 固定加载两条；不做检索、动态技能目录或来源更新 |
| 清单 | read/review/report 三项随宿主证据更新 | 不是可由模型任意编辑的 Todo 工具 |
| 压缩 | 完整第一组 assistant/tool 存档，以带哈希回执替代 | 确定性精确归档；未做 LLM 摘要 |
| 审查 | 私有消息、真实 Tokio 任务、请求/回执、取消与 join | 固定单 reviewer，不是通用持久化团队协议 |
| 预算/恢复 | 父子共享模型与工具尝试数；只读瞬时错误最多两次 | 不跨进程恢复账本，不自动重试写入 |
| 权限/Hook | 固定 call_id、文件名、完整内容审批；pre/post 边界 | 模拟审批，不是人工交互界面 |
| MCP | 固定本地 read_startup 服务，stdio 握手、发现、调用和关闭回收 | 可信服务；未实现通用 R19 schema 注册器或 HTTP |
| 完成 | 独立文件/证据验收，终态与记忆同一 SQLite 事务 | 事件事后落盘，无每节点持久检查点 |

完整 18 个场景名见 src/main.rs 的 SCENARIOS。故障由测试模式确定性注入，协议、线程、
SQLite、Git 与文件效果真实。knowledge-injection 强制脚本模型请求越界写入，再检查
宿主拒绝；这不测真实模型理解恶意资料的能力。cancel-review 在受控 gate 取消，
不是任意瞬间强制中断；model-budget/tool-budget 清理仍等待已启动 reviewer 的句柄。

## 故障与证据

post-hook、write-unknown 的报告真实存在，任务失败、不发布记忆。
terminal-save-failed 的文件存在且目标验收通过，但终态事务回滚，任务仍 running。
stale-owner 模拟替换 owner/epoch 后，旧执行者拒绝写入和终态提交，任务留给替代者。
程序不声称文件系统与 SQLite 跨资源原子性，也不自动恢复这些运行中任务。

run.json 的 graph_nodes、state.inputs/history、review_history、events、wire 提供运行链。
父子共用 Book 的单调 seq；SQLite 先记 claimed，结束时导入运行事件，再原子记录 terminal。
因此事件序号有各自域，运行内 seq 不是逐事件持久化检查点。

退出路径回收实际 MCP 子进程、中继任务和 reviewer 句柄；只管理直属子进程。
startup/数据库 I/O 故障、SIGKILL、物理断电、任意子孙进程与真实 provider 另验。

outputs/ 与 evidence.json 由仓库 scripts/verify-agent-integration.py 生成：
检查 SQLite、文件、归档、消息配对、真实协议、Git worktree 和 PID 已回收。
规范化证据省略现场检查过的 PID，保留确定性内容；解压最终下载包后离线编译复验。
