---
title: "第 32 章：完整 Agent 集成"
description: "让同一个任务经过提示词、共享预算、私有审查、MCP 与工作区，在真实效果和持久化状态之间验收完成。"
pageClass: learn-agent-rust-course
prev:
  text: 第 31 章 · MCP 外部工具
  link: /learn-agent-rust/mcp-tools
next:
  text: 专题 1 · PostgreSQL 检查点
  link: /learn-agent-rust/postgres-checkpoints
---

# 第 32 章：完整 Agent 集成

[课程总览](./index.md) · [上一章：MCP 外部工具](./mcp-tools.md) · [下一章：PostgreSQL 检查点](./postgres-checkpoints.md)

::: tip 本章学习目标
- 沿一条真实任务路径，说明 graph-flow、langchain-rust 和宿主策略各自负责什么。
- 把任务、工具调用、审查回执和共享预算关联起来，辨认“工具成功”“目标通过”“终态提交”三个时刻。
- 运行独立学习包，用 SQLite、Git、协议帧和文件交叉验收正常与故障路径。

**前置：** [图调度](./tools-and-graph.md)、[权限](./permissions.md)、[提示词组装](./system-prompts.md)、[错误恢复](./error-recovery.md)、[Agent 团队](./agent-teams.md)、[工作区隔离](./worktree-isolation.md)与[上一章 MCP](./mcp-tools.md)。其他机制在用到时回链。

**实践方式：** <a href="/learn-agent-rust/integrated-agent.zip" download>下载独立 Cargo 工程</a>。Rust 1.99.1、Git、macOS / Linux；SQLite 随依赖构建。首次安装需要网络，实验无需模型密钥或数据库服务。
:::

上一章把外部服务接到了工具入口。现在交给 Agent 一个稍长的目标：**读出项目的启动命令，请一位审查者核对，然后把结果写进 `report.txt`。**

每个零件单独看都很简单。真正的问题出现在接缝处：审查者会不会另开一份预算？压缩历史后还认得已经读过的文件吗？写入已经发生，Hook 却失败了，任务该怎样结束？模型说“完成”，持久化记录是否也完成了？

本章用同一条任务回答这些问题。父 Agent 与审查者使用确定性脚本模型，图执行、消息类型、stdio MCP 子进程、SQLite、Git worktree 与文件操作实际运行。这样可以逐次复核接线和故障效果，再把真实模型接入留作独立验收。

<LearnAgentRustMap active="integrated-agent" />

<!-- experiment-library:start -->

全书实验可从[统一代码库](./experiments.md#integrated-agent)下载；解压后进入 `chapters/integrated-agent/`，或在代码库根目录运行 `python3 run.py run R20`。

<!-- experiment-library:end -->

::: info 技术版本与复现基线
本章 MCP 接线沿用 R19 的 **2025-11-25** 协议基线。当前规范与迁移验收要求见[技术跟踪](./technology-radar.md#mcp-migration)；本章通过不代表新版 MCP 或真实模型生产集成通过。
:::

## 1. 先预测：这份报告需要多少次调用？

练习仓库的 `README.md` 只有两行。下面是实验夹具的原文，程序会实际创建并读取这个文件：

```text
Project: Rust Agent
Startup: cargo run --release
```

期望的报告也只有两行：

```text
Startup: cargo run --release
Review: README verified
```

父 Agent 先请求 MCP 读取，再启动审查、等待回执、请求写入，最后给出回答。审查者自己经历“模型请求读取 → 宿主读取 → 模型判断”两轮。

先预测一下：把父子都计入同一账本，需要几次模型调用、几次工具尝试？等待审查也算一个工具入口；MCP 握手和发现作为基础设施记录，不算模型发起的工具尝试。

实际正常输出为：

<<< @/public/learn-agent-rust/outputs/r20-normal.txt

答案是 **7 次模型调用、5 次工具尝试**。父 Agent 有 5 轮生成、4 个工具请求；审查者有 2 轮生成、1 次本地读取。`spawned=1 joined=1` 表示后台句柄已等待回收；`workspace=retained` 表示报告仍在练习工作区里供检查。

![同一个任务从 SQLite 领取，经过三节点循环、MCP 和私有审查，再验收报告与提交终态。](/learn-agent-rust/figures/r20-integration-path.svg)

读图时先沿中间的三节点循环走一圈，再看两侧：MCP 服务在另一个进程，reviewer 在同一个 Tokio runtime 的另一项任务中。它们使用的文件都绑定到本次 worktree。图中的调用数来自本章正常运行记录。

## 2. 完整的是一条任务路径

这里的“完整”指从到期任务入口走到可核对的结束状态。前面章节有更丰富的模块实验，本章选择其中一个最小契约接入循环。两者分别验收，避免把已有模块的全部能力都算成集成通过。

| 机制与前章 | 本章实际接入 | 仍由前章或后续单独验收 |
| --- | --- | --- |
| [R02 图与消息](./tools-and-graph.md) | 固定提交的 graph-flow、langchain-rust 接口 | 真实 provider、开放式规划质量 |
| [R04 Hooks](./hooks.md)、[R03 权限](./permissions.md) | pre/post 边界，绑定完整调用的固定批准记录 | 交互审批界面、任意插件链 |
| [R05 清单](./todo-planning.md) | read / review / report 三项宿主证据 | 模型自由修改的 Todo 工具 |
| [R07 技能](./skill-loading.md)、[R09 记忆](./memory.md)、[R10 提示词](./system-prompts.md) | 两个真实 JSON 来源、哈希校验、资料分层；成功后发布一条记忆 | 技能目录、语义检索、记忆冲突与遗忘 |
| [R08 压缩](./context-compaction.md) | 一整组调用与结果精确存档、哈希回执替换 | LLM 摘要质量、自动选择摘要策略 |
| [R11 恢复](./error-recovery.md) | 分类停止，只读瞬时错误有界重试 | 跨进程恢复与写入对账 |
| [R12 任务](./task-system.md)、[R14 调度](./scheduling.md) | 固定到期身份去重、SQLite CAS 领取和终态 | 时区规则、守护调度、租约接管 |
| [R06 子任务](./subagents.md)、[R13 后台任务](./background-tasks.md)、[R15 团队](./agent-teams.md)、[R16 协议](./team-protocols.md) | 单 reviewer 的私有消息、请求/回执、受控取消和 join | 通用邮箱、协商协议、团队恢复 |
| [R18 工作区](./worktree-isolation.md) | 真实 linked worktree，写前绑定检查、清洁移除或保留报告 | 合并发布流程、恶意代码隔离 |
| [R19 MCP](./mcp-tools.md) | 一个固定本地服务，真实握手、发现、调用与回收 | 通用 schema 注册器、HTTP、任意服务 |

学习包拥有独立入口和 `Cargo.lock`，不依赖其他章节目录。`connection.rs` 从本站 R19 的有界管道中继与关闭逻辑适配，其余文件围绕这一条任务组织。

::: info 代码只有一个来源
下文 Rust 代码均从 <a href="/learn-agent-rust/code/integrated-agent/README.md" download>工程说明</a>所列的完整工程导入。
可在 [GitHub 查看源码](https://github.com/lewislau86/lewislau86.github.io/tree/master/docs/public/learn-agent-rust/code/integrated-agent)，或使用章首 zip。命令在解压后的 `integrated-agent/` 目录运行。
:::

## 3. 先领取任务，再给它一个工作区

触发器提供固定到期身份 `startup@2026-11-08T08:00:00+08:00`，对应任务 `startup-1`。这是测试时钟给出的输入；本章不运行长期调度器。

同一触发器故意提交两次。SQLite 的主键让第二次插入数为零，之后只允许把 `queued` 的任务改为 `running`。只有比较条件仍成立，领取才成功：

<<< @/public/learn-agent-rust/code/integrated-agent/src/store.rs#intake

`owner=lead, epoch=1` 是本次执行的归属。程序在用户指定的全新实验目录里建立 `repository/`，再从 `main` 建立 `codex/r20-startup-a1` 的 linked worktree。所有报告写入都针对 `workspace/`，主检出的 README 保持原样。

写入前再次核对数据库归属、当前分支和工作区根目录：

<<< @/public/learn-agent-rust/code/integrated-agent/src/runtime.rs#context

这里把来源校验也放在同一处：每轮读取 `sources/skill.json` 与 `sources/memory.json`，对照初始化时保存的 SHA-256。`source-stale` 修改实际来源文件，因此在首次模型调用之前就停止。

分支和根目录检查解决的是可信宿主内的误绑定。它们与 SQLite 检查之间没有跨进程原子锁，不能据此宣称完成了对任意并发写者的 fencing，更不等于操作系统沙箱。

## 4. 仍然只有一个父循环

图没有为每个功能增加一条主循环。三种节点各有一个职责：

- `Prepare`：校验资料、整理历史、注入当前证据、检查上下文字节预算。
- `ModelTurn`：在共享账本扣款，通过 `LLM::generate` 获得回答或工具请求。
- `ExecuteTools`：核对调用、执行动作、追加同 ID 的工具结果；错误转换成明确停止原因。

实际图与会话驱动如下：

<<< @/public/learn-agent-rust/code/integrated-agent/src/agent.rs#graph

graph-flow 推进 `Session`；应用状态放在 `session.context` 中。父模型实现 langchain-rust 的 `LLM` trait，返回真实的 `GenerateResult` 和 `ToolCall`。工具定义作为模型可见资料一并传入，宿主仍对实际请求做精确检查。这里采用脚本生成固定步骤，真实 provider 的工具绑定和质量需要另验。

宿主执行完一项请求，把结果放回历史：

<<< @/public/learn-agent-rust/code/integrated-agent/src/agent.rs#tools

注意 `call.id`：它从模型请求一路带到结果。请求失败也产生一条配对结果，随后停止；模型重复使用旧 ID 时，在追加请求之前拒绝，从而避免给一组调用补两条结果。

### 来源与历史各就各位

系统消息只放应用策略。技能、旧记忆和工具描述属于 `human` 角色中的 `reference_data`；用户目标、已有调用结果和最后一条 `runtime_view` 组成其他输入。`runtime_view` 把宿主已核对的读取、回执和清单交给下一轮。

当审查结束、准备写入时，历史里的第一次 README 读取已经可以归档。程序保存完整的 assistant/tool 二元组，用带哈希的归档回执替换，原始读取证据继续保存在 `State.read_text`。随后验证整段历史中每个工具请求都有且只有一个结果。

<<< @/public/learn-agent-rust/code/integrated-agent/src/agent.rs#prepare

本例按序列化消息字节计数，正常上限为 24,576 字节；这不是 provider token 用量。精确归档是确定性压缩，保存输入快照只是为教学审计，不代表长任务可以无限保存所有历史。

`knowledge-injection` 会把恶意文字写进真实记忆文件并更新其来源哈希，再强制脚本模型提出 `../../outside.txt` 写入请求。结果在宿主参数/批准边界被拒绝。它检验“即使模型提出了错误动作，宿主是否拦住”，没有测量真实模型抵抗注入的能力。

## 5. 私有审查，共享账本

父 Agent 请求 `start_review` 后，宿主创建 Tokio 任务，立即返回 `accepted`。审查者拥有自己的 system 消息和小任务，不复制父历史、技能和记忆。

本例为可重复验收设置一个 gate：`wait_review` 才释放审查任务继续；`cancel-review` 在 gate 上发送取消。审查者实际调用两次脚本 LLM：第一次得到 `read_file` 请求，宿主只允许读取绑定的 README；第二次根据配对结果形成结论。

<<< @/public/learn-agent-rust/code/integrated-agent/src/agent.rs#reviewer

父 Agent 收到的是一张回执：`request_id=review-1`、`from=reviewer`、`to=lead`、`status=completed`、来源哈希与核对结论。宿主对照请求和读取内容后，才把 `review:running` 改为 `review:verified`。这一张回执不会赋予写入权限。

父子上下文分开，消耗却汇入同一个 `Arc<Mutex<Book>>`。扣款发生在调用之前，超额就拒绝派发：

<<< @/public/learn-agent-rust/code/integrated-agent/src/runtime.rs#ledger

![父子模型和工具尝试汇入共享预算，运行事件用序号、执行者和调用 ID 关联，数据库另记任务身份。](/learn-agent-rust/figures/r20-identity-and-budget.svg)

读图时区分四种身份：`startup-1` 是持久任务；`task-1-c1` 是父 Agent 的逻辑调用；MCP 的 JSON-RPC ID 属于协议请求；`review-1` 是私有审查请求。它们有明确映射，却不能混用。

### 只读重试仍然消费预算

`read-retry` 的服务第一次真实收到请求后返回 `transient_read`，第二次读取成功。宿主允许最多两次尝试，保持同一个应用 `call_id`，每次尝试都扣工具预算。MCP 的两次请求有各自协议 ID，父历史最后只追加一条逻辑工具结果。

<<< @/public/learn-agent-rust/code/integrated-agent/src/runtime.rs#read-retry

实际结果与正常路径相比，模型仍是 7 次，工具尝试变为 6 次：

<<< @/public/learn-agent-rust/outputs/r20-read-retry.txt

连接初始化上限 2 秒，MCP 调用上限 250 毫秒；单帧上限 65,536 字节，读取文本上限 1,024 字节。本章固定单工具服务，不借此推断任意服务的输入输出边界。

## 6. 写成功、目标通过、终态提交

现在，README 和审查都已通过。模型请求写入 `report.txt`，宿主仍要检查固定批准记录：调用 ID 必须是 `task-1-c4`，文件名和**完整内容**都必须相同。`approval-denied` 关闭这条模拟批准记录。

<<< @/public/learn-agent-rust/code/integrated-agent/src/runtime.rs#write

`create_new(true)` 避免覆盖现有报告；写入后同步文件，记录实际效果。pre Hook 在写前拦截，post Hook 则可能在效果发生后失败。两者的错误位置不同，恢复动作也必须不同。

### 模型的回答只是待验收信号

当模型不再请求工具，循环以 `answered` 停止。宿主还要检查读取、回执、写入证据、报告实际字节和任务归属：

<<< @/public/learn-agent-rust/code/integrated-agent/src/agent.rs#goal

所以 `false-finish` 虽然回答了 `done`，目标依然不通过。正常情况下，目标通过后先回收资源：等待 reviewer、关闭 MCP 协议任务、等待或终止并回收直属子进程、回收中继任务。诊断移到实验根目录后，清洁 worktree 移除，有报告的 worktree 保留。

最后才提交任务终态、终态事件与新记忆。三者属于同一个 SQLite 事务：

<<< @/public/learn-agent-rust/code/integrated-agent/src/store.rs#terminal

`completed` 对外只在“目标通过，而且数据库也已提交完成”时为真。程序重新打开 SQLite 核对状态，验证器再通过 Python 的独立连接读取实际表。

![写入效果、宿主目标验收和 SQLite 事务分成三个时刻，故障后可保留报告而没有完成状态。](/learn-agent-rust/figures/r20-effect-and-terminal.svg)

看图中三条故障分支：`post-hook` 与 `write-unknown` 都留下实际报告，但没有通过目标验收；`terminal-save-failed` 已通过目标验收，终态事务却回滚。文件系统和 SQLite 是两个资源，这个顺序没有给它们提供共同事务。

终态保存失败的实际输出：

<<< @/public/learn-agent-rust/outputs/r20-terminal-save-failed.txt

此时需要保留工作区和证据，后续核对已有报告再决定恢复。直接把整个任务从头重跑，会再次遇到写入；本章没有实现这条恢复路径，后续 [P01 检查点](./postgres-checkpoints.md)和 [P02 工具副作用可靠性](./side-effect-reliability.md)接着处理。

## 7. 动手实验：从报告反查每一层

解压学习包后先执行：

```sh
cargo test --locked
cargo run --locked -- normal demo-normal
cargo run --locked -- read-retry demo-retry
cargo run --locked -- approval-denied demo-denied
cargo run --locked -- post-hook demo-post
cargo run --locked -- terminal-save-failed demo-save
```

每次的目标目录必须尚不存在，且父目录已存在。实验只在这些新目录里建仓库；程序拒绝覆盖上次运行。CLI 默认打印摘要，加 `--json` 可打印完整记录，例如：

```sh
cargo run --locked -- --json normal demo-json
```

先打开 `demo-normal/workspace/report.txt`，再用下面的映射检查来源。无需相信一条 `completed=true` 日志：

| 证据文件 / 字段 | 核对什么 |
| --- | --- |
| `run.json → graph_nodes` | 三节点循环的实际执行顺序 |
| `run.json → state.inputs`、`state.history` | 每轮实际模型输入、调用与结果配对 |
| `run.json → review_history` | reviewer 私有消息与只读工具调用 |
| `run.json → events`、`usage` | 单调运行事件、父子模型/工具扣款与重试 |
| `run.json → wire`、`mcp-calls.jsonl` | 协议请求与真实服务执行次数一致 |
| `history-archive.json` | 完整归档组；哈希与历史里的回执一致 |
| `sources/` | 真正加载的技能与旧记忆文件 |
| `tasks.sqlite` | 到期身份、任务归属、终态事件与新记忆 |
| `repository/`、`workspace/` | 主检出未改，报告 worktree 留存或清洁移除 |

然后比较 `demo-denied`、`demo-post` 和 `demo-save`：预测报告是否存在、任务是什么状态、记忆是否发布，再打开实际目录核对。写前被拒绝的清洁工作区可能已移除，诊断仍在实验根目录。

### 18 个场景的实际结果

下表由 `scripts/verify-agent-integration.py` 运行独立工程后生成。模型 / 工具尝试均含 reviewer；被权限或预算拒绝而未派发的动作不计工具尝试。

<!-- r20-results:start -->

| 场景 | 停止原因 | 模型 / 工具尝试 | 报告存在 | SQLite 终态 |
| --- | --- | --- | --- | --- |
| `normal` | `answered` | 7 / 5 | 是 | `completed` |
| `read-retry` | `answered` | 7 / 6 | 是 | `completed` |
| `approval-denied` | `approval_required` | 6 / 4 | 否 | `failed` |
| `pre-hook` | `pre_hook_blocked` | 6 / 4 | 否 | `failed` |
| `post-hook` | `post_hook_failed` | 6 / 5 | 是 | `failed` |
| `write-unknown` | `write_outcome_unknown` | 6 / 5 | 是 | `failed` |
| `model-budget` | `model_budget` | 2 / 2 | 否 | `failed` |
| `tool-budget` | `tool_budget` | 3 / 2 | 否 | `failed` |
| `context-budget` | `context_budget` | 0 / 0 | 否 | `failed` |
| `source-stale` | `source_stale` | 0 / 0 | 否 | `failed` |
| `knowledge-injection` | `approval_required` | 1 / 0 | 否 | `failed` |
| `false-finish` | `answered` | 1 / 0 | 否 | `failed` |
| `duplicate-call` | `invalid_call_id` | 2 / 1 | 否 | `failed` |
| `model-error` | `model_error` | 1 / 0 | 否 | `failed` |
| `review-failed` | `review_failed` | 4 / 4 | 否 | `failed` |
| `cancel-review` | `cancelled` | 3 / 3 | 否 | `failed` |
| `stale-owner` | `stale_owner_or_workspace` | 6 / 4 | 否 | `running` |
| `terminal-save-failed` | `answered` | 7 / 5 | 是 | `running` |

<!-- r20-results:end -->

`stale-owner` 在写前把实际数据库归属替换为 `replacement, epoch=2`。旧执行者拒绝写入，终态 CAS 也拒绝提交，任务保持 `running`。这是受控归属变化实验，尚未实现完整租约接管。

`model-budget`、`tool-budget` 在 reviewer 已启动但 gate 尚未释放时耗尽预算，清理路径发送取消并 join；`cancel-review` 则在等待节点主动取消。三者都验证句柄回收，尚未覆盖任意时间点的中断。

### 怎样复验本章

在网站仓库根目录运行：

```sh
python3 scripts/verify-agent-integration.py --check
python3 scripts/generate-learn-agent-rust-figures.py --lesson R20
npm run docs:build
```

验证器运行 **10 个 Rust 测试和 Clippy**，逐场检查实际 SQLite、文件字节、Git 工作区、归档、消息角色和配对、MCP 请求/响应及服务日志；还在现场检查服务 PID 已消失。随后独立解压最终下载包，离线重新编译并复验全部场景。JSON CLI 也单独执行一次。

记录环境为 Rust 1.99.1 / Apple Silicon macOS，完整 Git 与 rustc 版本保存在下载包的 `evidence.json`。CI 配置在 Ubuntu 上执行同一套 `--check`；本地结果和 CI 是否运行是两项记录。源码哈希、逐场完整证据及输出随学习包提供。

运行事件先存在共享内存，结束时再导入 SQLite；这份证据用于复核正常退出与受控故障退出。它不是逐节点持久检查点，不能据此声称进程被杀后可以恢复。

## 8. 与参考课程架构对照

![参考课程把上下文、策略、任务、团队和外部工具放在同一 Agent 系统中。](/learn-agent-rust/figures/upstream/r20-system-architecture.svg)

图源：[参考章节](https://learn.shareai.run/zh/s20/) · [原图](https://learn.shareai.run/course-assets/s20_comprehensive/system-architecture.svg)。原图原样保留，展示 Python / Claude 教学实现；接口、编号和数量沿用原图，不是本章 Rust 运行统计。来源版本与许可见[课程架构](./architecture.md#reference-assets)。

对照时关注共同问题：谁拥有循环、谁批准动作、谁保存状态。Rust 学习包的具体接线与已验证范围以本章代码、范围表和运行证据为准。

::: warning 常见误区
- 各章模块通过后，仍需验证共享状态与错误传播。本章只接入范围表中的最小契约。
- 脚本模型让故障可复现；它验证框架接口和宿主边界，真实 provider、开放任务质量与协作质量还要单独测。
- `accepted` 只表示审查已受理；`answered` 只表示模型停止请求工具。目标验收与数据库提交各有检查。
- 写后错误可能留下真实文件；关闭连接、取消任务或回滚 SQLite 不会撤销这份文件。不要盲目重放写入。
- 工作区检查和 MCP 进程管理针对可信练习程序。任意服务权限、子孙进程、启动失败、SIGKILL 和物理断电均不在这 18 个场景的通过范围内。
:::

<!-- transfer-thinking:start -->

## 迁移思考：接缝是新的故障位置

各模块单测都通过，为什么完整循环仍可能重复写入？先给出你的判断，再展开下面的推演。

<details><summary>推演与应用</summary>

沿写入成功、结果保存、终态提交逐段注入故障，核对原预算、操作身份与实际产物。

集成验收应沿用户目标跨模块追踪，而不是把模块通过率相加。

</details>

这是一道迁移练习，推演不代表新增实验已通过。对照[全书审查中的证据层次](./course-review.md#evidence-layers)，说明你的判断还需要哪一级证据。

<!-- transfer-thinking:end -->

## 本章结论：把接缝变成可检查的契约

本章保留三节点父循环，把来源、共享预算、审查回执、MCP 与工作区接到同一任务。它们通过明确的身份与宿主证据联系起来：压缩保留有效调用组，子任务归入同一账本，动作效果独立核对，成功记忆只随终态事务发布。

集成验收最有价值的产物，是知道故障发生后**哪些事实已经成立**。报告存在、目标通过、数据库完成可以处于不同阶段；保存这些差别，才有下一步恢复的依据。

## 检查理解

1. 正常任务为什么是 7 次模型调用、5 次工具尝试？

   <details><summary>参考答案</summary>

   父 Agent 生成 5 次，分别请求读、启动审查、等待审查、写报告和最终回答；reviewer 生成 2 次。父工具入口调用 4 次，reviewer 本地读取 1 次。握手和工具发现记录为基础设施，不计模型工具尝试。

   </details>

2. 为什么 reviewer 私有历史不代表它拥有独立预算？

   <details><summary>参考答案</summary>

   历史决定模型能看到什么，预算决定系统可以消费多少资源。reviewer 只持有自己的消息，但与父 Agent 共享同一个 `Book`，在生成和读取之前扣款。预算耗尽后，退出路径还要取消并等待后台句柄。

   </details>

3. 压缩为什么要同时移走 assistant 请求和 tool 结果？

   <details><summary>参考答案</summary>

   只移走一边会留下没有结果的调用或没有请求的工具消息。本例把完整二元组写入归档，用哈希回执替代，并将已验证读取保留在宿主状态；下一轮组装后重新检查历史配对。

   </details>

4. `write-unknown` 已有报告，为什么不能直接算完成或自动重试？

   <details><summary>参考答案</summary>

   该场景在效果后返回结果不明，宿主没有得到正常成功路径的写入回执，目标验收不通过。文件可能已完整，也可能在其他真实故障中只写了一部分。先读实际字节并对账，再选择恢复；直接重放可能重复副作用。

   </details>

5. `terminal-save-failed` 中 `goal_verified=true`，`completed=false` 是否矛盾？

   <details><summary>参考答案</summary>

   两者检查不同事实：目标验收核对文件、读取和审查；完成还要求 SQLite 终态提交。故障注入让终态、记忆和终态事件一起回滚，实际文件仍保留，任务还是 `running`。这正是后续检查点与副作用对账需要处理的窗口。

   </details>

## 参考资料

- [本章独立工程源码](https://github.com/lewislau86/lewislau86.github.io/tree/master/docs/public/learn-agent-rust/code/integrated-agent)与 <a href="/learn-agent-rust/integrated-agent.zip" download>含证据的学习包</a>。
- [graph-flow 固定提交](https://github.com/a-agmon/rs-graph-llm/tree/9bbca193f20a8c4ba23289621549ecb3d35fee64)：`GraphBuilder`、`Task`、`Session` 的实际依赖版本。
- [langchain-rust 固定提交](https://github.com/Abraxas-365/langchain-rust/tree/5fc3f5aca4380da48829f95d6e2fd0217b1f2013)：`LLM`、`GenerateResult`、`Message` 与 `ToolCall`。
- [rmcp 3.9.0](https://docs.rs/rmcp/3.9.0/rmcp/)与 [MCP 2025-11-25 生命周期](https://modelcontextprotocol.io/specification/2025-11-25/basic/lifecycle)：固定 stdio 接线与初始化顺序。
- [SQLite 事务](https://www.sqlite.org/lang_transaction.html)、[rusqlite 0.37.0 Transaction](https://docs.rs/rusqlite/0.37.0/rusqlite/struct.Transaction.html)与 [Git worktree](https://git-scm.com/docs/git-worktree)：持久化和工作区的底层边界。

下一章进入 [P01：PostgreSQL 检查点](./postgres-checkpoints.md)，继续处理进程退出后，循环状态怎样被重新加载。
