# Learn Agent by Rust · 全书实验代码库

本目录由网站唯一实验源码和通过检查的章节包生成，可以单独复制或下载使用。
教程正文：https://lewislau86.github.io/learn-agent-rust/ 。章节目录按主题命名，章号与实验标识的对应关系见下表和 manifest.json。
主线章号按阅读顺序排列；R/G/K/P 是稳定实验标识，命令保留原标识。例如第 11 章 RAG 仍用 K01 运行。

## 先运行一章

需要 Python 3.9+（仅标准库）、Rust 1.99.1、rustfmt、Clippy、Git 与系统 C 编译工具。
已实际检查 macOS；自动检查配置使用 Linux。建议 Windows 读者使用 WSL。

```sh
rustup toolchain install 1.99.1 --profile minimal --component rustfmt --component clippy
python3 run.py list
python3 run.py doctor
python3 run.py integrity
python3 run.py run R01
python3 run.py test R01
python3 run.py run R20 --keep ./my-results
```

`run` 编译并运行表中的演示；`test` 还运行格式检查、Rust 测试和 Cargo 工程的 Clippy。
每次复制章节到临时目录运行，退出清理；`--keep` 保存演示的数据与证据，拒绝覆盖同名结果。
修改 chapters 中的源码后也可重跑。编译缓存与最近一次结果保存在 .cache/，无需网站、Node.js、VitePress 或其他项目。

## 全书检查

```sh
python3 run.py test --all
# 依赖和固定工具链已下载后：
python3 run.py test --all --offline
# 未安装 PostgreSQL 时明确跳过两章，汇总会列出 skipped：
python3 run.py test --all --skip-postgres
```

首次获取 Rust 工具链和 Cargo 依赖需要网络；zip 不附带第三方 crate 或编译器。
P01、P04 需要 PostgreSQL 18 服务端全套工具，以普通 Unix 用户运行；不使用现有数据库。工具不在 PATH 时设置：

```sh
# 改成自己的安装路径；Linux 常见 /usr/lib/postgresql/18/bin
export P01_PG_BIN=/opt/homebrew/opt/postgresql@18/bin
export P04_PG_BIN=$P01_PG_BIN
python3 run.py test P01
python3 run.py test P04
```

## 章节对应

| 编号 | 教程 | 实验目录 | 统一入口运行内容 |
| --- | --- | --- | --- |
| R00 | [第 0 章 · 整体架构与环境](https://lewislau86.github.io/learn-agent-rust/architecture-and-setup) | [chapters/architecture-and-setup](chapters/architecture-and-setup/README.md) | 本章正常路径演示 |
| R01 | [第 1 章 · 最小 Agent 循环](https://lewislau86.github.io/learn-agent-rust/agent-loop) | [chapters/agent-loop](chapters/agent-loop/README.md) | 本章正常路径演示 |
| R02 | [第 2 章 · 工具注册与图调度](https://lewislau86.github.io/learn-agent-rust/tools-and-graph) | [chapters/tools-and-graph](chapters/tools-and-graph/README.md) | 本章正常路径演示 |
| R03 | [第 3 章 · 工具权限与审批](https://lewislau86.github.io/learn-agent-rust/permissions) | [chapters/permissions](chapters/permissions/README.md) | 本章正常路径演示 |
| R04 | [第 4 章 · 生命周期与 Hooks](https://lewislau86.github.io/learn-agent-rust/hooks) | [chapters/hooks](chapters/hooks/README.md) | 本章正常路径演示 |
| G01 | [第 5 章 · 图状态、条件路由与有界循环](https://lewislau86.github.io/learn-agent-rust/graph-state-routing) | [chapters/graph-state-routing](chapters/graph-state-routing/README.md) | 4 组路由与循环演示 |
| G02 | [第 6 章 · 图暂停、会话存储与恢复](https://lewislau86.github.io/learn-agent-rust/graph-pause-resume) | [chapters/graph-pause-resume](chapters/graph-pause-resume/README.md) | 跨进程批准、恢复与终态保护演示 |
| G03 | [第 7 章 · 图并行、归并与子图](https://lewislau86.github.io/learn-agent-rust/graph-parallel-subgraphs) | [chapters/graph-parallel-subgraphs](chapters/graph-parallel-subgraphs/README.md) | 5 组并行、失败、子图与超时演示 |
| R05 | [第 8 章 · 可见的任务清单](https://lewislau86.github.io/learn-agent-rust/todo-planning) | [chapters/todo-planning](chapters/todo-planning/README.md) | 本章正常路径演示 |
| R06 | [第 9 章 · 子 Agent 与上下文隔离](https://lewislau86.github.io/learn-agent-rust/subagents) | [chapters/subagents](chapters/subagents/README.md) | 本章正常路径演示 |
| R07 | [第 10 章 · 按需加载技能](https://lewislau86.github.io/learn-agent-rust/skill-loading) | [chapters/skill-loading](chapters/skill-loading/README.md) | 本章正常路径演示 |
| K01 | [第 11 章 · RAG：检索、证据与回答](https://lewislau86.github.io/learn-agent-rust/retrieval-augmented-generation) | [chapters/retrieval-augmented-generation](chapters/retrieval-augmented-generation/README.md) | 11 个检索与证据场景 |
| R08 | [第 12 章 · 上下文压缩](https://lewislau86.github.io/learn-agent-rust/context-compaction) | [chapters/context-compaction](chapters/context-compaction/README.md) | 本章正常路径演示 |
| R09 | [第 13 章 · 跨会话记忆](https://lewislau86.github.io/learn-agent-rust/memory) | [chapters/memory](chapters/memory/README.md) | 跨进程写入与召回演示 |
| R10 | [第 14 章 · 系统提示词组装](https://lewislau86.github.io/learn-agent-rust/system-prompts) | [chapters/system-prompts](chapters/system-prompts/README.md) | 本章正常路径演示 |
| R11 | [第 15 章 · 错误分类与恢复](https://lewislau86.github.io/learn-agent-rust/error-recovery) | [chapters/error-recovery](chapters/error-recovery/README.md) | 本章正常路径演示 |
| R12 | [第 16 章 · 持久化任务系统](https://lewislau86.github.io/learn-agent-rust/task-system) | [chapters/task-system](chapters/task-system/README.md) | 多步持久状态演示 |
| R13 | [第 17 章 · 后台任务](https://lewislau86.github.io/learn-agent-rust/background-tasks) | [chapters/background-tasks](chapters/background-tasks/README.md) | 本章正常路径演示 |
| R14 | [第 18 章 · 定时调度](https://lewislau86.github.io/learn-agent-rust/scheduling) | [chapters/scheduling](chapters/scheduling/README.md) | 多步持久状态演示 |
| R15 | [第 19 章 · Agent 团队](https://lewislau86.github.io/learn-agent-rust/agent-teams) | [chapters/agent-teams](chapters/agent-teams/README.md) | 本章正常路径演示 |
| R16 | [第 20 章 · 团队协作协议](https://lewislau86.github.io/learn-agent-rust/team-protocols) | [chapters/team-protocols](chapters/team-protocols/README.md) | 本章正常路径演示 |
| R17 | [第 21 章 · 自主任务领取](https://lewislau86.github.io/learn-agent-rust/autonomous-workers) | [chapters/autonomous-workers](chapters/autonomous-workers/README.md) | 多步持久状态演示 |
| R18 | [第 22 章 · 工作区隔离](https://lewislau86.github.io/learn-agent-rust/worktree-isolation) | [chapters/worktree-isolation](chapters/worktree-isolation/README.md) | 本章正常路径演示 |
| R19 | [第 23 章 · MCP 外部工具](https://lewislau86.github.io/learn-agent-rust/mcp-tools) | [chapters/mcp-tools](chapters/mcp-tools/README.md) | 本章正常路径演示 |
| R20 | [第 24 章 · 完整 Agent 集成](https://lewislau86.github.io/learn-agent-rust/integrated-agent) | [chapters/integrated-agent](chapters/integrated-agent/README.md) | 本章正常路径演示 |
| P01 | [专题 1 · PostgreSQL 检查点](https://lewislau86.github.io/learn-agent-rust/postgres-checkpoints) | [chapters/postgres-checkpoints](chapters/postgres-checkpoints/README.md) | 完整本地 Python 套件 |
| P02 | [专题 2 · 外部操作的可靠性](https://lewislau86.github.io/learn-agent-rust/side-effect-reliability) | [chapters/side-effect-reliability](chapters/side-effect-reliability/README.md) | 本章正常路径演示 |
| P03 | [专题 3 · 模型协议与质量评估](https://lewislau86.github.io/learn-agent-rust/model-evaluation) | [chapters/model-evaluation](chapters/model-evaluation/README.md) | 完整本地 Python 套件 |
| P04 | [专题 4 · 生产准入与演练](https://lewislau86.github.io/learn-agent-rust/production-readiness) | [chapters/production-readiness](chapters/production-readiness/README.md) | 完整本地 Python 套件 |
| P05 | [专题 5 · 固定工作流与目标控制](https://lewislau86.github.io/learn-agent-rust/workflow-and-goal-control) | [chapters/workflow-and-goal-control](chapters/workflow-and-goal-control/README.md) | 完整本地 Python 套件 |
| P06 | [专题 6 · Agent RSI 与受控自我改进](https://lewislau86.github.io/learn-agent-rust/agent-rsi) | [chapters/agent-rsi](chapters/agent-rsi/README.md) | 三种策略发布/拒绝/回滚演示 |

## 检查证据与范围

发布前逐章原验证器：31/31 通过，记录见 [audit.json](audit.json)。
原验证器检查正文引用、故障场景、实际产物及章节下载包；本代码库的 `test --all` 检查 Rust 测试、格式、Clippy 与运行表中的演示。两种检查分别记录。
P01/P03/P04/P05 的统一入口运行章节 lab.py 完整本地套件；其余章节的更多故障场景见各章 README 和源码。
各章 outputs/ 与 evidence.json 是发布时的记录，包含源码摘要与实验边界。时延、PID、平台路径等现场值不能逐字比较。
默认入口只调用确定性模型/输入夹具；P03 真实启动本地 HTTP，R19/R20 真实运行 stdio 子进程，数据库和文件效果按章实测。
P03 的可选 live 命令需要读者自行配置模型服务；统一入口和自动检查始终使用 fixture，不读取模型凭据。
P06 是有限策略搜索与发布门控实验。数据公开，顺序种子只有两种固定排列，结论不延伸为真实 RSI 或泛化质量。

## 维护与来源

网站源码：https://github.com/lewislau86/lewislau86.github.io 。
不要在生成目录维护第二份课程源码。维护者在网站仓库修改 docs/public/learn-agent-rust/code/，
更新相应章节验证产物，执行 `python3 scripts/verify-agent-experiments.py`，再执行 `python3 scripts/package-agent-experiments.py`。
`checksums.json` 核对下载包的文件内容，`manifest.json` 保存编号、目录、依赖和运行步骤。
