# Learn Agent by Rust · ADK-Rust 3.0 全书迁移计划

> 本文件是 `docs/learn-agent-rust/` 与 `docs/public/learn-agent-rust/code/` 迁移到 ADK-Rust 3.0 的工作计划和进度记录。
> 它不是网站页面（VitePress `srcDir` 是 `docs/`，根目录文件不会发布）。仓库通用约束仍以 [AGENTS.md](./AGENTS.md) 与 `docs/guide/course-conventions.md` 为准；两者冲突时，以它们为准并回来修改本计划。
>
> **怎样维护本文件：** 每完成一项工作，更新第 9 节状态表；每做出一个取舍，追加到第 10 节决策记录；每次查阅上游，更新第 2 节基线并在第 11 节记一笔。不要删除旧决策，改判时写新条目并注明替代了哪一条。

- 创建日期：2026-11-27
- 当前阶段：阶段 2 完成（6.2 节），下一步阶段 3（R05、R06、R07、K01、R08、R09、R10）。已迁移：第 0–7 章（R00–R04、G01–G03）与专题 2（P02，按 D-10 在阶段 6 整章重写）
- 上游基线：adk-rust `main` @ `98515241133d24f7e41f8fd272649035416a142f`（2026-11-26，workspace 版本 3.0.0，未发布）；唯一登记处是 `scripts/learn-agent-rust-adk.json`

---

## 1. 目标与原则

**目标：** 全书 39 个学习节点的实验全部改用 ADK-Rust 3.0，移除 `graph-flow` 与 `langchain-rust`；同时借助 3.0 新增能力补写沙盒、浏览器、Computer Use、Agent 间协议、常驻运行与编码 Harness 等章节。理念是“为未来而写”：读者学到的 API 和机制，应当是未来一两年里生产 Rust Agent 真会用到的。

迁移时必须守住的原则：

1. **机制优先，框架其次。** 每章仍围绕“一个具体问题 → 预测 → 观察轨迹 → 破坏条件 → 迁移思考”。框架替我们做的事，要用事件流、`ScriptedLlm::requests()`、存储内容或源码引用让读者看见，不能只写成配置说明。每章新增“框架替你做了什么、没做什么”一节。
2. **证据制度不变。** 每章仍有独立 Cargo 工程、锁文件、验证器、`outputs/`、`evidence.json`、章节 zip、解压复验。evidence 额外记录 adk-rust 版本 / 提交、启用的 feature 与工具链。
3. **旧实验的场景清单就是新实验的需求清单。** 每个旧场景在新版里必须标注：保留（用 adk 实现）、由框架提供（写明对应 API 与验证方式）、或删除（写明理由）。不允许静默丢掉故障场景。
4. **默认离线、确定性。** 所有默认实验用 `adk_model::ScriptedLlm`（不需要 feature、不读凭据）、内存或 SQLite 存储、`ManualClock` 等注入时间。真实 provider、WebDriver、真实桌面等只放在单独标注的 live 小节，默认验证不运行。
5. **按稳定度写作。** Stable crate 先写；Beta crate（harness、kernel、computer-use、devtools、acp、surface）的章节最后写，并在章内标明层级；Experimental crate 不进正文。
6. **网站仍是唯一来源。** 不从 adk-rust 仓库复制文档进来；源码引用指向固定提交的行号。

## 2. 上游基线与版本策略

### 2.1 已核实事实（2026-11-27）

| 项目 | 事实 | 来源 |
| --- | --- | --- |
| 发布状态 | crates.io 最新 `adk-rust 2.3.0`（2026-10-09）；`main` 是 3.0.0 RC，README 标明 “unpublished”；CHANGELOG 的 `[3.0.0] - 2026-10-10` 小节为空，条目在 `changelog.d/` | crates.io API；`README.md`；`CHANGELOG.md` |
| 版本历史 | 0.1.0 2025-11-30 → 1.0.0 2026-06-07 → 2.0.0 2026-08-09 → 2.3.0 2026-10-09 | crates.io API |
| 工具链 | workspace `rust-version = "1.95"`，仓库 `rust-toolchain.toml` 为 `1.95.0`；edition 2024；SQLx 0.9 | `Cargo.toml` |
| 许可 | Apache-2.0（`adk-vision-sam-codec` 例外，为 SAM License，不使用） | `README.md`、`STABILITY.md` |
| 3.0 发布条件 | `STABILITY.md` 中 semver 清单、迁移指南、供应链、发布记账四项仍为 Open | `STABILITY.md` |
| 依赖 3.0 的方式 | 官方文档写法：克隆仓库，在项目里用 `[patch.crates-io] adk-rust = { path = ".../adk-rust" }`，每个直接依赖的 `adk-*` crate 各写一行。git + rev 依赖未写进文档，需阶段 0 实测 | `docs/official_docs/quickstart.md` |
| Linux 链接器 | 仓库 `.cargo/config.toml` 在 Linux 上使用 clang + wild，只影响在克隆目录内构建；下游工程按 Cargo 规则不读依赖的配置（推断，阶段 0 实测） | `quickstart.md` |

### 2.2 稳定度分层（摘自 `STABILITY.md`）

| 层级 | 本书会用到的 crate |
| --- | --- |
| Stable | core、agent、model、tool、runner、session、graph、memory、skill、rag、eval、guardrail、plugin、retry-reflect、telemetry、auth、server（含 A2A）、browser、code、sandbox、rust-macros、cli、anthropic、rust（伞 crate） |
| Beta | harness、kernel、computer-use、devtools、acp、surface（3.x 小版本可能有破坏性变化，附迁移指南；harness 计划在 3.2.0 评审转 Stable） |
| Experimental（不用） | managed、enterprise、codeact-monty、site、drivers、vision、vision-sam-codec、website |

### 2.3 版本策略

1. **RC 期间：** 全书锁定同一个 `main` 提交（当前 `98515241…`，登记在 `scripts/learn-agent-rust-adk.json`）。各章 `Cargo.toml` 写正式版本号 `3.0.0`、不带 `[patch]`；章节目录里的 `.cargo/config.toml` 用 path patch 指向 `../adk-rust/<crate>`，即源码放在章节目录旁边（D-3）。更换基线提交时全书一起换，不允许各章各锁一个提交。
2. **3.0.0 发布后：** 删除各章 `.cargo/config.toml`，依赖改成 crates.io `=3.0.0` 并重新生成锁文件（这时锁文件才会带上 crates.io 来源与校验和），全书重跑验证器，技术跟踪页记录 RC → 正式版的差异。
3. **3.x 小版本：** Stable 章节按需升级；Beta 章节每次升级都要读该 crate 的迁移说明，并重跑对应章。
4. **课程工具链：** 暂定继续用 Rust 1.99.1（≥ MSRV 1.95）。阶段 0 确认 adk 在 1.99.1 下 `clippy -D warnings` 不出问题（见决策 D-7）。

## 3. 3.0 对教学最重要的变化（写作时必须处理）

以下来自 `docs/official_docs/migration/2.x-to-3.0.md` 等文档，每条都会影响某几章的讲法或确定性：

| 变化 | 影响章节 | 处理方式 |
| --- | --- | --- |
| 所有工具调用经过 `adk_core::authorize_tool_call` 一条受控路径；顺序为 budget → plugins → callbacks → circuit breaker →（kill switch → consent → resume binding → egress → `ToolPolicy` → guardrails → confirmation）→ action ledger → execute → after-hooks | R03、R04、R11、P02 | 第 4 章画出这条顺序并用实验逐段验证；第 3 章只讲 policy 与 confirmation 两段 |
| `ToolEffect` 决定重试：只有 `ReadOnly` / `Idempotent` 会重试；未声明的工具视为 `NonIdempotent`，只执行一次 | R02、R11、P02 | 第 2 章引入 `#[tool(read_only)]` / `#[tool(idempotent)]`；第 23 章与 P02 用它讲重试边界 |
| 非幂等调用超时、panic、取消后返回 `outcome_unknown`；`ActionLedger` 保证同一幂等键最多执行一次 | R11、P02 | P02 核心；已知限制“模型在 `outcome_unknown` 后重发会得到新键、不去重”正好做成故障场景 |
| 审批指纹包含执行 Agent 与工具来源；`tool_call_fingerprint(name,args)` 不再匹配；无处理器时调用被挂起为 `confirmation_pending`，同轮其他调用照常执行；`tool_confirmation_timeout` 默认 5 分钟 | R03、G02、D07 | 实验必须显式设置超时或 `ManualClock`，避免墙钟依赖 |
| 自动上下文压缩默认开启（`without_intra_compaction()` 关闭） | 全书 | **除 R08 外，所有章节显式关闭**，否则长场景输出不确定；R08 专门讲开启后的行为 |
| 工具错误信息默认不交给模型（`expose_tool_error_messages(true)` 打开） | R02、R11 | 第 2 章作为“模型看到什么”的观察点 |
| `#[tool]`、`FunctionTool` 按 schema 校验参数（`tool.invalid_arguments`）；重名工具构建失败；无 ID 的调用生成 `adk-call-…` | R01、R02 | 第 1–2 章的故障场景 |
| 指令以 `system` 角色发送；`LlmRequest::tools` 改为保留声明顺序的 `ToolDeclarations` | R10 | 用 `ScriptedLlm::requests()` 断言完整请求 |
| 模型拒答使运行失败（`model.refusal`），空回复失败（`model.empty_response`） | R01、R11 | 故障场景 |
| `skills` 不再是 adk-agent / adk-runner 的默认 feature | R07 | Cargo.toml 显式启用 |
| `adk_runner::Callbacks` 已删除；Runner 插件的 before 钩子先于 Agent 自己的钩子运行 | R04 | 以 3.0 顺序为准，旧资料不要照搬 |
| `RunConfig` 新增约 25 个字段；`RunnerConfig` 只能由 `Runner::builder()`（typestate）构建 | 全书 | 片段统一使用 builder 与 `..Default::default()` |
| `RunBudget`（模型调用、工具调用、费用、墙钟、单位）超限以 `budget.*` 结束 | R06、R11、R15、P05 | 替代各章自建的预算账本，但保留“共享累计预算”的教学问题 |

`ScriptedLlm`（`adk-model/src/scripted.rs`，始终编译）是离线实验的基石：每次 `generate_content` 消费一条脚本回复，可脚本化单个或多个工具调用、流式分片、流中断与调用失败；没有 ID 的调用分配 `scripted_tc_{call}_{index}`；脚本用尽以 `model.scripted.exhausted` 失败；`requests()` / `last_request()` 返回模型实际收到的全部请求。`MockLlm` 每次重放同一列表，不适合多轮，本书不用。

## 4. 新的全书结构

保留现有十个部分、章号与主题网址（`docs/learn-agent-rust/<slug>`），实验标识（R/G/K/D/P）不变；新增第十一部分，暂用 X 标识（见决策 D-5）。

### 4.1 现有 39 章的迁移映射

“层级”指主要依赖的最低稳定度。“阶段”对应第 6 节。

| ID | 章 | 主题（slug） | 现在的依赖 | ADK-Rust 3.0 落点 | 教学重点与注意事项 | 层级 | 阶段 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| R00 | 0 | architecture-and-setup | 标准库 | 伞 crate feature 分层、`Agent` / `Tool` / `Llm` / `Runner` / `Session` / `Event` 全景；环境改为固定 adk 提交 | 重画架构图：应用策略 / Runner / 受控工具路径 / 存储；说明 Stable 与 Beta | Stable | 2 |
| R01 | 1 | agent-loop | 标准库 | `LlmAgentBuilder` + `Runner` + `ScriptedLlm`；从事件流 `tool_calls()` / `tool_results()` 和 `requests()` 还原每次往返；`max_iterations` | Runner 拥有循环、没有单步 API，所以必须靠事件与请求记录“看见循环”；按 D-2 不保留手写循环，源码引用要指到 Runner / LlmAgent 执行这几步的位置 | Stable | 2 |
| R02 | 2 | tools-and-graph | graph-flow + langchain-rust | `#[tool]` / `FunctionTool`、`ToolEffect`、schema 校验、`tool_execution_strategy`；图部分用 `adk-graph` 的 `AgentNode` | **试点章，已完成**；对照改为 `Runner(LlmAgent)` 与 `Runner(GraphAgent 包同一个 Agent)`，图节点 `assistant` + `check_answer` | Stable | 1 |
| R03 | 3 | permissions | 标准库 | `DeclarativePolicy`（先匹配、默认拒绝）、`PolicyRule` + `ArgPredicate`、`require_approval`、`ApprovalStore`（取用即消费：一次批准一次执行）、`ToolResultStatus` | 指纹绑定执行 Agent 与来源；宿主仍是最终决策者 | Stable | 2 |
| R04 | 4 | hooks | 标准库 | 8 种回调（before/after agent、model、tool，after_tool_full，on_tool_error）+ Runner 插件（`EnhancedPlugin`）+ guardrail | 用实验验证 `authorize_tool_call` 的完整顺序 | Stable | 2 |
| G01 | 5 | graph-state-routing | graph-flow | `StateGraph` / `StateSchema` reducer（覆盖、追加、Sum、Custom）、`add_conditional_edges`、`Router::by_field`、`with_goto`、`with_recursion_limit` | 导读改为 LangGraph ↔ adk-graph 对照，比 graph-flow 更直接 | Stable | 2 |
| G02 | 6 | graph-pause-resume | graph-flow + rusqlite | `with_interrupt_before/after`、`interrupt_with_data`、`SqliteCheckpointer`、新进程只共享数据库即可恢复、`Checkpoint::with_version` 必须递增、`session_thread_id` | 保留“修订绑定、版本冲突、终态保护”三类故障；**试点候选** | Stable | 2 |
| G03 | 7 | graph-parallel-subgraphs | graph-flow | 多入边自动延迟汇合、`DeferredNodeConfig{min_predecessors}`、`run_node_with`（类似 `Send`）、`with_max_concurrency`、`SubgraphNode`（编译期通道检查）、节点重试与超时 | 旧版“父子持久恢复未实现”的边界需重新验证 | Stable | 2 |
| R05 | 8 | todo-planning | serde + tempfile | 主线：会话 state（`EventActions.state_delta`）+ 自定义清单工具；对照：harness todos | 清单写入 state 的可见性与恢复 | Stable（对照 Beta） | 3 |
| R06 | 9 | subagents | 标准库 | `sub_agent` + `transfer_to_agent`、`AgentTool`（独立上下文）、`allows_transfer_to_parent/peers`、共享 `RunBudget` | 区分“交接控制权”与“当工具调用” | Stable | 3 |
| R07 | 10 | skill-loading | 两库 + serde_yaml | `adk-skill`：`load_skill_index`、`select_skills`、`SkillInjector`、`SkillToolset`（list / load / load_resource 渐进披露） | 显式启用 `skills` feature；宿主执行权仍单独授权 | Stable | 3 |
| K01 | 11 | retrieval-augmented-generation | 标准库 | `adk-rag`（切块、embedding、向量检索、rerank） | 离线需要确定性 embedder：阶段 3 先验证能否注入自定义 embedder 与内存后端（D-8）；BM25 基线可作为对照保留 | Stable | 3 |
| R08 | 12 | context-compaction | 两库 | `EventsCompactionConfig` + `LlmEventSummarizer`（调用间）、`IntraCompactionConfig`（调用内，3.0 默认开）、`RunConfig::history_max_events`、`Llm::context_window` | 摘要器同样用 `ScriptedLlm`；保留“配对不被切断、事实不丢、回滚”场景 | Stable | 3 |
| R09 | 13 | memory | serde | `MemoryService`（`add_session` / `search` / `delete_user`）、SQLite 后端、app / user / project 隔离 | 跨进程写入与召回；双时态知识图谱只作延伸阅读 | Stable | 3 |
| R10 | 14 | system-prompts | 两库 | `instruction`（system 角色）、`ToolDeclarations` 顺序、技能与 AGENTS.md 注入来源 | 用 `requests()` 断言模型收到的完整输入与前缀稳定性 | Stable | 3 |
| D01 | 15 | pattern-selection | graph-flow | 单次调用 vs `SequentialAgent` vs 自主 `LlmAgent` | 6 个固定输入场景逐个映射 | Stable | 4 |
| D02 | 16 | prompt-chaining-routing | graph-flow | `SequentialAgent`、`ConditionalAgent`、`LlmConditionalAgent`、graph 条件边 | 两种 API（workflow agents 与 graph）何时用哪个 | Stable | 4 |
| D03 | 17 | parallel-decomposition | graph-flow | `ParallelAgent`、graph 扇出与 reducer 归并 | 局部失败与归并冲突 | Stable | 4 |
| D04 | 18 | plan-execute-replan | graph-flow | graph 动态节点（`run_node_with`）；对照：harness plan graph（`compile_plan`、`step:<id>`） | 主线用 Stable 的 graph | Stable（对照 Beta） | 4 |
| D05 | 19 | orchestrator-workers-handoffs | graph-flow | `TeamSpec`（Handoff / Delegate）→ `CompiledTeam`（预算、回执、恢复计划） | 交接回执作为证据 | Stable | 4 |
| D06 | 20 | evaluator-reflection | graph-flow | `LoopAgent`（`with_max_iterations`、`ExitLoopTool`）、`adk-retry-reflect` | 有界修复，评估依据必须可检查 | Stable | 4 |
| D07 | 21 | human-in-the-loop | graph-flow | 跨运行挂起的审批、`confirmation_pending`、workflow agent 在挂起的子 Agent 处恢复、graph interrupt | 跨 CLI 编辑后必须重新批准（指纹变化） | Stable | 4 |
| D08 | 22 | pattern-composition | graph-flow | 组合以上；`model_compare` 用 OpenAI 兼容客户端（`OpenAIConfig::compatible`） | 默认仍只跑 fixture；live 由读者配置 | Stable | 4 |
| R11 | 23 | error-recovery | 标准库 | `ToolEffect` 与重试、`RetryBudget`、`circuit_breaker_threshold`、`outcome_unknown`、`ErrorCategory`（含 `Conflict`、`ResourceExhausted`）、`model.refusal` / `model.empty_response` | 保留“什么错误值得重试”的分类表 | Stable | 5 |
| R12 | 24 | task-system | serde | 业务任务仍由应用建模；运行由 `DurableRunStore`（`NewRun` 幂等键、并发键、`OnConflict`）承载 | 讲清业务任务、durable run、图节点三者区别 | Stable | 5 |
| R13 | 25 | background-tasks | 标准库 | `adk_server::background::DurableWorker`（feature `background`）、后台运行、持久取消、`Runner::close` | 可查询、可取消 | Stable | 5 |
| R14 | 26 | scheduling | chrono + rusqlite | `ScheduleStore`、`ScheduleSpec::{Cron, At, Every}`、`MissedFirePolicy::{Skip, FireOnce, CatchUp(n)}`、`ManualClock`、`DurableScheduler` | adk-core 需启用 `cron` feature；kernel 留到 X05 | Stable | 5 |
| R15 | 27 | agent-teams | 两库 | `TeamSpec` / `CompiledTeam`、`ParallelAgent`、共享 `RunBudget` | 私有历史与共享预算 | Stable | 5 |
| R16 | 28 | team-protocols | tokio | `TeamSpec` 的策略与回执；批准 / 拒绝 / 关闭握手中框架未覆盖的部分在 adk 之上自建 | 写清哪些协议由框架提供、哪些仍是应用契约 | Stable | 5 |
| R17 | 29 | autonomous-workers | rusqlite | `LeaseStore`（按 epoch 设栅栏，旧写入 `run_store.stale_epoch`）、过期接管 | 旧代次拒写场景直接对应 | Stable | 5 |
| R18 | 30 | worktree-isolation | 标准库 | `adk-devtools` 的 `Workspace` / `DevToolset` + git worktree；harness 团队成员作对照 | Beta，最后写本部分时再定深度 | Beta | 5 |
| R19 | 31 | mcp-tools | rmcp 3.9.0 | `McpToolset` over `rmcp` 3.9（与现有基线同一 SDK）、stdio `TokioChildProcess`、HTTP；`ClientLifecycleMode::Discover` 支持 2026-07-28 | 顺带完成技术跟踪页里“MCP 2026-07-28 迁移尚未实现”的那一项 | Stable | 6 |
| R20 | 32 | integrated-agent | 两库 + rmcp + rusqlite | 主线：用 `Runner::builder()` 组装前面验证过的部件；HarnessAgent 留到 X06 | 验收范围按旧版口径逐项对照；K01 这次接入 | Stable | 6 |
| P01 | 专题 1 | postgres-checkpoints | postgres | `PostgresCheckpointer::from_pool`、Postgres 会话 / run / ledger store、`migrate()`、`adk-core` 的 `conformance` 测试套件 | 仍需 PostgreSQL 18 临时集群 | Stable | 6 |
| P02 | 专题 2 | side-effect-reliability | rusqlite | `SqliteActionLedger`、`Runner::recover_unanswered_calls`（`already_succeeded` / `already_failed` / `outcome_unknown`）、`InMemoryActionLedger` 重启后不保留 | **试点章**；Outbox 与对账仍是应用职责，继续自建 | Stable | 1 |
| P03 | 专题 3 | model-evaluation | 两库 + reqwest | `adk-eval`：`Evaluator`、`.test.json`、轨迹匹配、rubric、LLM judge、A/B（Wilcoxon）、`cargo adk eval`；本地 HTTP fixture 走 OpenAI 兼容客户端 | 协议正确与任务完成仍分开报告 | Stable | 6 |
| P04 | 专题 4 | production-readiness | postgres | `adk-telemetry`（OpenTelemetry）、签名审计日志（`AuditFailureMode::Block`）、`GovernanceControl` 冻结、`RunBudget` / `SpendLedger`、server 默认只绑 127.0.0.1 | 迁移、回滚、容量与接管演练保留 | Stable | 6 |
| P05 | 专题 5 | workflow-and-goal-control | serde | 主线：graph + `LoopAgent` 固定流程与独立验收；对照：harness `GoalSpec`（`with_until`、`with_rubric`、`with_max_iterations`）与 `GoalEngine` | 目标完成仍由独立验收判定 | Stable（对照 Beta） | 6 |
| P06 | 专题 6 | agent-rsi | 标准库 | `adk-eval` 的基线与 A/B 作发布门控；策略搜索保持自建 | 结论边界不变 | Stable | 6 |

### 4.2 第十一部分（新增）：受控的外部行动与常驻运行

这些主题在旧技术栈下要么写不了，要么要从零搭一大套；3.0 提供了可学习的实现。每章先回答“风险在哪、框架怎样约束它”，再动手。

| 暂定 ID | 主题 | 依赖 | 离线可验证的部分 | live 部分（单独标注，默认不跑） | 层级 |
| --- | --- | --- | --- | --- | --- |
| X01 | 沙盒与代码执行 | `adk-sandbox`（`ProcessBackend`、`WasmBackend`、`sandbox-native` 的 Seatbelt / bubblewrap）、`adk-code` | 子进程与 WASM 后端全部离线；OS 级限制在 macOS / Linux 实测 | Docker 后端 | Stable |
| X02 | 浏览器操作 | `adk-browser`（WebDriver） | 本地静态测试页；需 `with_private_network_access(true)` 才能访问回环地址 | 需要本机 chromedriver / Selenium | Stable |
| X03 | Computer Use：受控桌面操作 | `adk-computer-use` | `build_reference_graph` + 进程内 `ComputerUseRuntime`（官方 `minimal_graph` 示例无需任何外部依赖）；`ComputerUseToolset` + 自写假桌面 `ComputerActuator` | `McpComputerActuator` over `npx @zavora-ai/computer-use-mcp`，读者本机运行 | Beta |
| X04 | Agent 间协议：A2A 与 ACP | `adk-server`（A2A v1）、`adk-acp` | 回环地址上的两个进程互调 | 接入外部编辑器 | Stable / Beta |
| X05 | 常驻 Agent：Kernel、唤醒与引导 | `adk-kernel`、`Runner::steer`、`GovernanceControl` | `Kernel::builder()` 全内存运行；`InMemoryQueueSource`、`ManualClock`；webhook 用本地 HMAC | `adk-rust up` 长驻 | Beta |
| X06 | 编码 Agent Harness（全书收官） | `adk-harness`、`adk-devtools` | `HarnessAgent` + `ScriptedLlm`：模式（read_only / plan / ask / auto）、常设批准、沙盒 bash、AGENTS.md 信任、plan graph、持久目标、`/rewind` | 真实模型完成编码任务 | Beta |

X03 的教学要点（来自 `docs/official_docs/computer-use/index.md`）：观察 → 预览 → 绑定 `args_digest` 的审批中断 → 只执行一次 → 验证；执行前重新校验信封、租约和预约；`VerificationOutcome` 区分 `Verified`、`CommittedUnverified`、`Failed`（“动作已执行”不等于“效果已达成”，和 P02 一脉相承）；坐标空间与设备像素比；租约预算与边界。**限制：** 目前没有已发布的 `computer-use-mcp` 提供参考图需要的受控工具（`preview_action`、`execute_action` 等），所以参考图只能跑进程内 runtime，真实桌面只能走 `ComputerUseToolset` 路线。

暂不纳入：实时语音视频（Stable，但离线无法验证，只作延伸阅读候选）；支付、AWP、网站、视觉（Experimental 或偏离主题）；Gemini Enterprise / Agent Engine 部署（云厂商绑定）。

## 5. 每章的交付清单（Definition of Done）

一章标为完成，必须全部满足：

- [ ] **场景映射表：** 旧版每个场景标注保留 / 框架提供 / 删除及理由，写进章节 README 与 evidence。
- [ ] **工程：** `docs/public/learn-agent-rust/code/<slug>/` 下有 `Cargo.toml`（adk 依赖与 feature 最小化，`default-features = false` 起步）、`Cargo.lock`、`rust-toolchain.toml`、`README.md`、`src/`；`cargo fmt --check`、`cargo clippy --all-targets -D warnings`、`cargo test --locked` 通过。
- [ ] **确定性：** 默认运行只用 `ScriptedLlm`；除 R08 外关闭自动压缩；时间用注入时钟；不读任何凭据。
- [ ] **验证器：** `scripts/verify-agent-*.py`（或新命名）生成 `outputs/`、`evidence.json`、章节 zip；`--check` 重跑并解压复验。evidence 记录 adk 提交、feature、工具链。
- [ ] **正文：** 符合规范第 4 节章节结构；代码只用片段导入，不手抄；新增“框架替你做了什么、没做什么”一节和“在 ADK-Rust 源码里”一节（由 `scripts/learn-agent-rust-adk-refs.py` 生成，见阶段 0）。
- [ ] **配图：** 由 `scripts/generate-learn-agent-rust-figures.py --lesson <ID>` 重新生成，删除 graph-flow / langchain-rust 字样。
- [ ] **登记：** `scripts/learn-agent-rust-lessons.json`、`scripts/learn-agent-rust-experiments.json`、`scripts/data/learn-agent-rust/review-prompts.json` 同步；`.github/workflows/check-agent-*.yml` 更新。
- [ ] **全书检查：** `python3 scripts/sync-learn-agent-rust-course.py --check`、`python3 scripts/review-learn-agent-rust.py --check`、`python3 scripts/package-agent-experiments.py --check`、`npm run docs:build` 通过。
- [ ] **本文件：** 第 9 节状态表更新。

## 6. 阶段计划

### 阶段 0 · 基建（先于任何章节）

1. lewislau 在仓库打标签 `learn-agent-rust-v1`，冻结旧版全部工程和 zip（D-4）。
2. 在 Mac 上克隆 adk-rust 并检出基线提交；分别实测 `[patch.crates-io]` 的 path 方式与 git + rev 方式，记录哪种能让读者“解压即构建”（D-3）。
3. 用最小 feature 组合（`adk-core`、`adk-agent`、`adk-runner`、`adk-model` 关闭默认 feature、`adk-session`、`adk-tool`）建一个空工程，记录：冷编译耗时、`target/` 大小、依赖数量、Rust 1.99.1 下的 clippy 结果。这些数字写进 `setup.md`。
4. 写共享片段 `scripts/snippets/adk-trace.rs`：把事件流打印成统一的轨迹格式（调用 ID、工具名、参数摘要、结果状态、state_delta）。各章原样复制，检查脚本核对一致（参照 TinyLLM 的 corpus 片段做法）。
5. 写 `scripts/learn-agent-rust-adk-refs.py`：按 SPEC 为每章生成“在 ADK-Rust 源码里”一节，指向固定提交的文件与行号；支持 `--fetch`、`--check`（参照 `scripts/tinyllm-real-model-refs.py`）。
6. `learn-agent-rust-lessons.json` 每章增加 `stack` 字段（`v1` / `adk3`），课程地图与总览显示迁移状态；改 `sync-learn-agent-rust-course.py` 与 `LearnAgentRustMap.vue`。按 D-9 这一步必须在第一章上线前完成。
7. 抽一个验证器模板（参照现有 `verify-agent-*.py`），统一 evidence 里的 adk 版本字段。

**完成标准：** 空工程在 Mac 与 CI（Linux）上都能离线复建；两个新脚本有 `--check`；`npm run docs:build` 通过。

### 6.0 阶段 0 的执行记录（2026-11-27）

**已完成（沙盒，aarch64 Linux，4 核 / 3 GB 内存）：**

| 步骤 | 产物 | 结果 |
| --- | --- | --- |
| 2. 取源码、定依赖方式 | `scripts/learn-agent-rust-adk.json`（基线）、`scripts/fetch-adk-rust.py`（`git` 浅取指定提交；`cdn` 按文件从 jsDelivr 下载，可续传；`--check`） | 沙盒访问不了 GitHub git，用 `--method cdn` 取到全部 2981 个构建所需文件，`--check` 通过。实测 path patch 写在章节 `.cargo/config.toml`、路径 `../adk-rust/<crate>` 可用，锁文件与把 patch 写在 Cargo.toml 时逐字节相同；git 与 path 两种 patch 不能叠加（cargo 报 `specification is ambiguous`），见 D-3 |
| 3. 最小工程测量 | 探针工程（`adk-core`、`adk-agent`、`adk-model`、`adk-runner`、`adk-session`、`adk-tool`，ADK 依赖全部 `default-features = false`；未入库） | 锁定 181 个包，解析后 194 个；冷编译 17 秒、峰值内存约 0.8 GB；`target/` 1.6 GB（debug）；连跑 3 次输出逐字节相同；`cargo clippy --all-targets -- -D warnings` 通过 |
| 4. 共享轨迹片段 | `scripts/snippets/adk-trace.rs`（`event_lines`、`request_lines`） | 在探针中编译、运行通过，样例轨迹见下 |
| 5. 源码引用脚本 | `scripts/learn-agent-rust-adk-refs.py`（`--check`、`--src`；标记 `<!-- adk-refs:start/end -->`） | 已为 R02 写好 6 条 SPEC，全部定位成功；只对 `stack: adk3` 的章节写正文 |
| 6. 迁移状态字段 | `lessons.json` 全部 39 章加 `"stack": "v1"`；`sync-learn-agent-rust-course.py` 校验该字段；`LearnAgentRustMap.vue` 标注 | 只要还没有一章是 `adk3`，站点输出与原来完全相同（`--check` 0 个文件过期）；临时把一章改成 `adk3` 后，总览目录、学习路径、课程地图都出现对应标注，VitePress 构建通过 |
| 7. 验证器公共部分 | `scripts/learn_agent_rust_adk.py`（打包、解压后在旁边放 `adk-rust/`、按实际依赖生成最小 patch 列表、fmt / clippy / test / 离线构建、3 次重复比对、证据头）；`scripts/check-learn-agent-rust-snippets.py`（检查 trace 片段、patch 配置、版本号、工具链；`--sync SLUG` 重写） | 最小 patch 列表在探针上算出 9 个 crate（比直接依赖多出 `adk-rust-macros`、`adk-sandbox`、`adk-telemetry`） |

探针用 `ScriptedLlm` 脚本化“调用 `read_readme` → 回答”两步，得到的轨迹：

<!-- output-check: skip -->
```text
[assistant] call    id=scripted_tc_0_0 read_readme {}
[assistant] result  id=scripted_tc_0_0 read_readme status=ok {"content":"运行：cargo run","path":"README.md"}
[assistant] text    "项目用 cargo run 运行。"
[assistant] final
request 0: roles=system,user tools=[read_readme]
request 1: roles=system,user,model,function tools=[read_readme]
```

两点观察会进入正文：指令以 `system` 角色出现在请求内容里；工具结果以 `function` 角色回传，调用 ID 由 `ScriptedLlm` 按 `scripted_tc_{第几次调用}_{第几个}` 分配。

**注意：** 用 Rust 1.99.1 编译时，adk-core 有 3 条 `fetch_update` 弃用警告（上游固定 1.95.0）。path 依赖属于本地包，警告会显示在 cargo 输出里，但不影响本章代码的 `clippy -D warnings`。验证器只在失败时打印 cargo 输出，读者手动编译时会看到，`setup.md` 要说明。

**lewislau 在本机完成的部分：**

1. 已完成：标签 `learn-agent-rust-v1` 指向 `e8707197ad15…`（迁移前最后一个提交）。
2. 已完成：Mac 上用 git 方式取到 `.cache/adk-rust`，`fetch-adk-rust.py --check` 输出 `ok: git checkout at 98515241133d`。阶段 1 的验证器默认从这里取源码。
3. 待做：记录 Mac 上的冷编译时间和 `target/` 大小，回填本节（阶段 1 第一个工程编译时顺便记录）。

**未完成、移到阶段 1：** CI 工作流（`.github/workflows/check-agent-*.yml`）需要先取 adk 源码再编译，等试点章的验证器定型后一起改；`setup.md` 改写随 R00 进行。

### 阶段 1 · 试点：R02 + P02

R02 检验 Stable 层能否撑起“先看清循环，再映射到图”；P02 检验 3.0 的 action ledger 能否复现书里的故障窗口。

**继续推进的条件（全部满足）：**

1. `ScriptedLlm` 驱动的轨迹逐字节可复现（连跑 3 次一致）。
2. R02 旧版全部场景都能完成映射，且“显式循环 vs 图执行状态一致”的对照仍成立。
3. P02 能在“工具已成功、检查点 / 回答未保存”之间注入进程终止（参照上游 `crash_mid_payment` 的 SIGKILL 门禁），并观察到 `recover_unanswered_calls` 不重复执行。
4. P02 能复现“`outcome_unknown` 后模型重发得到新键、不去重”的已知限制，正文能讲清应用要补什么。
5. 单章冷编译时间与 zip 体积在可接受范围（阈值在阶段 0 测完后定，写进决策记录）。

任一条不满足：回到本文件记录原因，评估是否改为“框架章 + 机制章”混合方案。

### 6.1 阶段 1 的执行记录（2026-11-27）

**结论：5 条全部满足，继续推进（GO）。** 逐条证据：

| 条件 | 结果 | 证据 |
| --- | --- | --- |
| 1. 轨迹可复现 | 满足 | R02 默认演示连跑 3 次逐字节相同；P02 ADK 部分 6 个场景整套连跑 2 次逐字节相同（验证器内强制检查） |
| 2. R02 场景映射与对照 | 满足 | 旧版 9 个场景全部保留或拆细为 14 个；`Runner(LlmAgent)` 与 `Runner(GraphAgent 包同一个 Agent)` 在 14 个场景上事件轨迹、请求、计数、停止原因全部一致；结论变化的只有 `duplicate-id`（旧版应用拒绝，3.0 框架不检查） |
| 3. 崩溃窗口与恢复 | 满足 | 真实进程退出：工具内退出（外部已写、账本无结果）→ `recover_unanswered_calls` 回答 `outcome_unknown`；工具后退出（账本已有结果、会话未保存）→ `already_succeeded`；两者都不重复执行，外部工单数保持 1 |
| 4. 新键不去重的限制 | 满足 | 恢复后新一轮运行里模型重发同一调用：幂等键按“应用/用户/会话/本次运行/调用 ID”组成，换了运行就换了键，外部工单变成 2 张；工具改用业务身份（会话 + 标题的摘要）后，外部服务去重，工单仍是 1 张。这正是专题 2 要讲的“框架账本管同一次调用，业务身份管同一件事” |
| 5. 编译与体积 | 满足 | 沙盒（aarch64，4 核）冷编译 R02 约 16 秒；章节 zip 约 26 KB（不含第三方源码）；关掉调试信息与增量编译后 target 约 0.7 GB。阈值暂定：冷编译 ≤ 2 分钟、zip ≤ 200 KB。Mac 实测待回填 |

**R02 已完成并按 D-9 上线状态：** 工程、验证器、输出、证据、zip、三张配图、正文重写、源码引用一节、`lessons.json` 标为 `adk3`、全书代码库（`run.py` 新增 `fetch-adk`，下载检查脚本会先取或链接 adk 源码）、四个导读页加“正在迁移”说明。独立审查子代理找出 3 个必改、8 个应改问题，已全部修正（最重要的两条：schema 校验是 `FunctionTool` 做的，不是 `LlmAgent`；“JSON 损坏”在 3.0 里是 `not_run`，与类型不对的 `failed` 不同，因此新增 `invalid-json` 场景）。

**P02 已迁移（按 D-10 方案 a）：** 原 29 个场景的业务协议实验只依赖 rusqlite，原样保留为第 1–8 节；新增第 9 节“放进 ADK-Rust：动作账本管同一次调用，业务身份管同一件事”，工程在章节目录的 `adk/` 子目录（`code/side-effect-reliability/adk/`，`.cargo/config.toml` 用 `../../adk-rust`），验证器 `scripts/verify-agent-effects-adk.py`（由 `verify-agent-effects.py` 先调用），输出 `outputs/p02adk-summary.txt`，证据 `scripts/data/learn-agent-rust/p02adk-results.json`。6 个场景（含基线）记录外部服务被调用次数与工单数，证明恢复不再执行工具。章节 zip 与全书代码库都包含 `adk/`，`run.py test P02` 会检查并构建子工程。独立审查子代理找出 2 个必改、5 个应改问题，已全部修正（最重要：“会话 + 标题”的业务身份与第 3 节矛盾，改为明确标注为演示简化并给出可靠做法；`already_succeeded` 只带结果哈希、不带工单号，只补上第 6 节窗口的一半；恢复要由应用在重启后显式调用）。

**迁移中新确认的框架事实（写其他章时用得上）：**

- 参数 schema 校验由 `FunctionTool` 完成（对象 schema 默认封闭），`with_lenient_args(true)` 可关；手写 `Tool` 实现没有这项检查。
- 参数不是合法 JSON：模型适配器用 `adk_core::invalid_tool_arguments` 的标记对象代替参数，`LlmAgent` 回答 `not_run`、不运行工具。
- 工具错误交给模型多少由 `ErrorCategory` 决定：拒绝类（InvalidInput、Forbidden、NotFound、Unsupported、Conflict、ResourceExhausted）带消息，其余默认只给类别和错误码；`expose_tool_error_messages(true)` 打开后文字里不再有错误码，错误码始终在结果注解 `adk.tool_result.error_code`。
- 框架不检查调用 ID 重复；幂等键由调用 ID 组成，重复 ID 会得到相同幂等键。
- `max_iterations` 默认 100 轮，超限错误码是笼统的 `agent.legacy`；`RunBudget::max_model_calls` 在调用模型前检查，错误码 `budget.model_calls`。
- `recover_unanswered_calls` 只补答案、不调用模型、不执行工具；`InMemoryActionLedger` 进程退出即丢，同样的“工具后崩溃”会从 `already_succeeded` 变成 `outcome_unknown`。
- `after_tool_callback` 里退出进程，可以稳定制造“账本已记结果、会话未保存”的窗口。
- `GraphAgent` 的 `output_mapper` 产出的事件由框架补上作者（图名）和 invocation_id；`AgentNode` 出错时图停在该节点，后续节点不运行。
- 用户输入事件的 `is_final_response()` 也为真，轨迹片段只给非 `user` 作者标 `final`。

**沙盒构建要点：** 设 `CARGO_PROFILE_DEV_DEBUG=0 CARGO_PROFILE_TEST_DEBUG=0 CARGO_INCREMENTAL=0`，所有工程共用一个 target 目录（`$HOME/.cache/lar/dev`，验证器的 target 名用符号链接指过去），否则 /sessions 的 9.8 GB 很快写满；不要在仓库目录里创建或删除临时文件（`--sync` 已改为在临时副本里运行 cargo）。

### 阶段 2 · 第一、二部分（R00、R01、R03、R04、G01–G03）

同步改写 `index.md`、`architecture.md`、`setup.md`、`graph-orchestration.md`（改为 LangGraph ↔ adk-graph 导读）。

### 6.2 阶段 2 的执行记录（2026-11-27）

R00、R01、R03、R04、G01–G03 全部迁移上线，`graph-orchestration.md` 改写为 LangGraph ↔ adk-graph 导读。每章都经过独立审查子代理复核并修正（G01–G03 一轮：2 处高、6 处中、若干低）。

**adk-graph 实测事实（写阶段 4 设计模式章、阶段 6 P01 时直接用）：**

- 按超步执行：一步运行全部就绪节点，按节点名 + 通道名排序后应用更新。`stream(…, StreamMode::Updates)` 才有 `StepComplete`，`Values` 模式没有；返回的流要 `Box::pin`。
- 归并规则：`channel` 覆盖、`list_channel` 追加（写数组逐项追加）、`counter_channel` 按 **f64** 求和（写 1 读回 1.0）。未声明的通道默认按覆盖收下；`with_strict_channels()` 在应用更新时以 `UndeclaredChannel` 失败。
- 路由：条件边未映射的键、`with_goto` 的未知目标都是运行时 `UnknownRouteTarget`；悬空边、缺 START 在编译时拒绝；`with_goto` 替代节点声明的出边；两条普通出边 = 并行。
- `with_recursion_limit(n)`（默认 100）数的是一次运行从头的步数，暂停 / 失败后恢复接着累计；超出后检查点保留已走到的状态。
- 检查点：`SqliteCheckpointer::new("sqlite:path?mode=rwc")`（特性 `sqlite`，表 `graph_checkpoints`，不建父目录）；默认 `Durability::Sync`；版本只增不减，并发保存后到者 `CheckpointConflict`；已完成线程再调用直接返回最终状态。**框架不核对图版本**：节点改名后恢复会静默完成、什么都不跑，宿主要自己存 `graph_version`。
- 暂停：`NodeOutput::interrupt_with_data(..).with_response_schema(..)`；ID = hash(线程, 步号, 节点, 问题, 数据, 格式)；`strict_resume()` 只认当前挂起的 ID，答案先按 schema 校验，失败为 `ResumeRejected` 且不运行节点；恢复时暂停节点整段重跑，`ctx.resume_value()` 只在恢复那一步有值。
- 失败：同一步已完成的兄弟节点作为 pending writes 存进检查点，恢复只重跑失败节点。超时用 `NodeDefaults::with_timeout(TimeoutPolicy{..})`，`OnTimeout::Skip` 以空输出继续。
- 汇合：多条**无条件**入边的节点编译时自动标为 deferred，到齐后只运行一次（条件边不计）。
- 子图：`SubgraphNode::new(..).isolated().with_input(父, 子).with_output(子, 父)`；映射每端须在其所属一侧声明，否则父图编译时 `SubgraphChannelMismatch`；子图线程为 `父线程/节点@步号`；声明了暂停关口却无检查点的子图在父图编译时被拒。

**CI：** 阶段 0 移来的 CI 待办在本阶段完成：`check-agent-permissions.yml`、`check-agent-hooks.yml`、`check-agent-orchestration.yml` 改用 Rust 1.99.1 + rustfmt/clippy，缓存并 `fetch-adk-rust.py .cache/adk-rust` 后再跑验证器，路径过滤改成迁移后的目录与 zip 名。R00–R02 没有单章工作流，由 `check-agent-experiments.yml` 的下载包检查覆盖。P02 的 `verify-agent-effects-adk.py` 尚未进 CI，阶段 6 重写时一起加。

**给 lewislau 的提示：** 仓库里 8 个旧章节目录下有 11 月 7–8 日留下的 `target/`（git 已忽略，共约 1.5 GB，如 `code/mcp-tools/target`），本机 `npm run docs:build` 会把它们复制进站点产物，建议删除。

### 阶段 3 · 第三、四部分（R05、R06、R07、K01、R08、R09、R10）

先做 K01 的离线 embedder 可行性验证（D-8）。同步改写 `knowledge-and-capabilities.md`。

### 阶段 4 · 第五部分（D01–D08）

八章共用一个验证器 `verify-agent-patterns.py`，可一起迁移。同步改写 `agent-design-patterns.md`，加一节“workflow agents 与 graph 两套 API 怎样选”。

### 阶段 5 · 第六、七部分（R11–R18）

R18 依赖 Beta 的 devtools，放在本阶段最后。

### 阶段 6 · 第八、九、十部分（R19、R20、P01–P06）

P02 按 D-10 整章重写，和 P01 一起设计持久存储布局。

R19 同时完成 MCP 2026-07-28 迁移，更新 `technology-radar.md` 第 2 节。R20 接入 K01。

### 阶段 7 · 第十一部分新章（X01–X06）

建议顺序：X01 → X02 → X04 → X03 → X05 → X06。Beta 章节动笔前重新查看对应 crate 的稳定度和迁移说明。

### 阶段 8 · 切换到 3.0.0 正式版

去掉全部 `[patch.crates-io]`，改 crates.io `=3.0.0`；全书运行 `verify-agent-experiments.py` 与 `check-agent-experiment-download.py`；技术跟踪页记录 RC → 正式版差异。若 3.0.0 发布时阶段 2–7 尚未完成，也立即切换，后续章节直接基于正式版。

### 阶段 9 · 收尾

全站搜索并清除 `graph-flow`、`langchain-rust`、`FanOutTask`、`AgentExecutor` 等旧字样（历史对照段落除外）；更新 `course-review.md`、`learning-path.md`、`experiments.md`、`technology-radar.md`、AGENTS.md 中的课程描述；重新打包全书实验代码库。

## 7. 风险与对策

| 风险 | 对策 |
| --- | --- |
| RC 期间 API 继续变化 | 全书锁同一提交；每次换基线前读 `changelog.d/` 与迁移指南，记入第 11 节 |
| Beta crate 在 3.x 小版本破坏 | Beta 章节最后写；正文标层级；升级时只重跑相关章 |
| 框架拥有循环，机制被藏起来 | 事件轨迹片段 + `requests()` 断言 + 源码引用；每章“框架没做什么”一节 |
| 默认开启的自动压缩、5 分钟审批超时等破坏确定性 | DoD 中强制显式配置；验证器连跑 3 次比对 |
| 工作区大（3.0 共 51 个可发布 crate），编译慢、zip 大 | 最小 feature；阶段 0 测量并定阈值；zip 不含 target 与第三方源码（与现状一致） |
| 本协作环境的沙盒单次命令约 180 秒、访问 GitHub 不稳定 | Claude 负责写代码、脚本、正文与检查；首次编译、生成证据、PostgreSQL 实验在你的 Mac 上运行，结果回填 |
| K01 离线 embedding 不可行 | 保留自实现 BM25 作为离线主线，adk-rag 作 live 对照 |
| 上游项目由单一组织主导 | 技术跟踪页定期记录维护状态；源码引用固定提交，日后即使上游变化书也能自洽 |

## 8. 协作分工

| 工作 | 负责 |
| --- | --- |
| 方案、正文、Rust 工程、验证器与生成脚本 | Claude（在本仓库内编写） |
| 首次 `cargo fetch` / 编译、运行验证器、PostgreSQL 与 live 实验 | lewislau（本机 macOS），把输出与报错贴回 |
| 取舍拍板（第 10 节“待决”条目） | lewislau |
| 每个阶段结束后的复核 | Claude 起草检查清单，双方确认后更新本文件 |

## 9. 进度状态

状态取值：`—` 未开始 · `进行中` · `完成` · `不适用`。

| ID | 场景映射 | 工程 | 验证器 / 证据 | 正文 | 配图 | 登记与检查 |
| --- | --- | --- | --- | --- | --- | --- |
| 阶段 0 基建 | 不适用 | 完成 | 完成（公共模块） | 不适用 | 不适用 | 完成（标签、Mac 取源码已验证）；CI 在阶段 2 补上（见 6.2 节） |
| R00 | 完成（3 种模式保留） | 完成 | 完成（3 模式 × 2 次一致、3 测试） | 完成（已审查并修正） | 完成 | 完成（`adk3`） |
| R01 | 完成（13 → 14，新增 `loop-limit`） | 完成 | 完成（14 场景 × 2 次一致、7 测试） | 完成（已审查并修正） | 完成 | 完成（`adk3`） |
| R02 | 完成（9 → 14） | 完成 | 完成（14 场景、9 测试、3 次重复） | 完成（已审查并修正） | 完成（3 张） | 完成（`adk3`、代码库、导读说明） |
| R03 | 完成（10 场景，口径变化见正文对应表） | 完成 | 完成（10 场景 × 2 次一致、6 测试） | 完成（已审查并修正） | 完成 | 完成（`adk3`） |
| R04 | 完成（14 → 15，见正文对应表） | 完成 | 完成（15 场景 × 2 次一致、7 测试） | 完成（已审查并修正） | 完成 | 完成（`adk3`） |
| G01 | 完成（`direct` 删除，新增 `runaway` 超步上限；探针 11 项） | 完成 | 完成（4 场景 × 2 次一致、4 测试） | 完成（已审查并修正） | 完成 | 完成（`adk3`、CI） |
| G02 | 完成（6 个多进程流程，见正文对应表） | 完成（SQLite 检查点） | 完成（6 流程 × 2 次一致、3 测试） | 完成（已审查并修正；第 6 章改名“图暂停、检查点与恢复”） | 完成 | 完成（`adk3`、CI） |
| G03 | 完成（5 场景，失败场景新增“恢复只重跑失败节点”） | 完成 | 完成（5 场景 × 2 次一致、5 测试） | 完成（已审查并修正） | 完成 | 完成（`adk3`、CI） |
| R05 | — | — | — | — | — | — |
| R06 | — | — | — | — | — | — |
| R07 | — | — | — | — | — | — |
| K01 | — | — | — | — | — | — |
| R08 | — | — | — | — | — | — |
| R09 | — | — | — | — | — | — |
| R10 | — | — | — | — | — | — |
| D01 | — | — | — | — | — | — |
| D02 | — | — | — | — | — | — |
| D03 | — | — | — | — | — | — |
| D04 | — | — | — | — | — | — |
| D05 | — | — | — | — | — | — |
| D06 | — | — | — | — | — | — |
| D07 | — | — | — | — | — | — |
| D08 | — | — | — | — | — | — |
| R11 | — | — | — | — | — | — |
| R12 | — | — | — | — | — | — |
| R13 | — | — | — | — | — | — |
| R14 | — | — | — | — | — | — |
| R15 | — | — | — | — | — | — |
| R16 | — | — | — | — | — | — |
| R17 | — | — | — | — | — | — |
| R18 | — | — | — | — | — | — |
| R19 | — | — | — | — | — | — |
| R20 | — | — | — | — | — | — |
| P01 | — | — | — | — | — | — |
| P02 | 过渡完成（原 29 保留 + ADK 6）；按 D-10 阶段 6 整章重写 | 完成（`adk/` 子工程） | 完成（29 + 6 场景，ADK 部分 2 次一致） | 完成（新增第 9 节，已审查并修正） | 原有 2 张不变 | 完成（`adk3`、代码库、导读说明） |
| P03 | — | — | — | — | — | — |
| P04 | — | — | — | — | — | — |
| P05 | — | — | — | — | — | — |
| P06 | — | — | — | — | — | — |
| X01 | 不适用 | — | — | — | — | — |
| X02 | 不适用 | — | — | — | — | — |
| X03 | 不适用 | — | — | — | — | — |
| X04 | 不适用 | — | — | — | — | — |
| X05 | 不适用 | — | — | — | — | — |
| X06 | 不适用 | — | — | — | — | — |
| 导读与总览页 | 不适用 | 不适用 | 不适用 | — | — | — |
| 切换 3.0.0 正式版 | 不适用 | — | — | — | 不适用 | — |

## 10. 决策记录

### 已定

- **D-0（2026-11-27）全书迁移到 ADK-Rust 3.0，移除 graph-flow 与 langchain-rust。** 理由：langchain-rust 用户与生态偏弱（crates.io 近 90 天下载约 1.25 万，adk-rust 主 crate 约 2.45 万，另有 60 余个子 crate）；graph-flow 单人维护、约 1.3k 行；adk 3.0 新增的受控工具路径、持久运行、跨重启审批、action ledger、预算、harness、kernel 与本书后半部分主题高度重合。目标版本直接选 3.0（RC 期间锁提交，发布后切正式版），不先写 2.3 再升级。
- **D-1（2026-11-27）计划文件放在仓库根目录 `agent.md`。** 根目录不在 VitePress `srcDir` 内，不会发布；与 `AGENTS.md`（仓库协作约束）分开维护。

- **D-2（2026-11-27）全书纯 adk，不保留手写循环对照。** R00 / R01 也直接从 `LlmAgent` + `ScriptedLlm` 讲起。由此带来的要求：第 1 章必须用事件流轨迹和 `ScriptedLlm::requests()` 把“请求 → 工具调用 → 结果回传 → 再请求”的每一步完整展示出来，并配源码引用说明 Runner 在哪里执行这几步，替代原来手写循环承担的教学作用。
- **D-4（2026-11-27）旧版归档：git 标签 `learn-agent-rust-v1` + `experiments.md` 留归档说明。** 标签由 lewislau 在迁移改动提交前打在当前 HEAD；旧版不再维护。
- **D-9（2026-11-27）逐章合并上线。** 迁完一章上线一章，站点在迁移期间新旧混排。由此 `lessons.json` 的 `stack` 字段（阶段 0 第 6 步）成为必需：课程地图、总览目录与各章顶部必须显示该章基于 v1 还是 ADK-Rust 3.0；全书导读页（index、architecture、setup）在第一章迁移上线时就要改写成“迁移进行中”的口径，不能继续声称全书基于 graph-flow。

- **D-3（2026-11-27）读者工程用 path patch，ADK-Rust 源码放在章节目录旁边。** 每章 `.cargo/config.toml` 写 `../adk-rust/<crate>`，Cargo.toml 不带 `[patch]`。理由（阶段 0 实测）：git + rev patch 的锁文件记录 git 来源，各机器不一致，`--locked` 会失败；git 与 path 两种 patch 不能叠加；path patch 的锁文件不记录路径，任何机器都相同。代价是读者先运行一次 `fetch-adk-rust.py`（全书代码库的 `run.py doctor` 代办）。替代了阶段 0 之前“建议 git + rev”的意见。
- **D-7（2026-11-27）课程工具链继续用 Rust 1.99.1。** 实测能编译、clippy 通过；上游 3 条 `fetch_update` 弃用警告会出现在 cargo 输出里，`setup.md` 要说明。

- **D-2 补充（2026-11-27）第 1 章用自写的规则模型 `RuleLlm`，不用 `ScriptedLlm`。** 理由：第 1 章要证明“回答来自真实读到的内容”（`changed-readme` 场景改了 README，回答跟着变），固定脚本做不到；`RuleLlm` 同样实现 `Llm` trait，并自己记录收到的每次请求，起到 `requests()` 的作用。其余章节默认仍用 `ScriptedLlm`。
- **D-10（2026-11-27）专题 2 整章用 ADK-Rust 重写（方案 b）。** 替代此前先行实现的方案 a（保留原实验 + 第 9 节）。现状保留到重写完成：站点上的专题 2 仍是“原 29 场景 + 第 9 节 ADK 部分”，能正常构建和下载。重写安排在阶段 6，与 P01 一起做：两章都用到 ADK 的持久存储（会话、动作账本、检查点、run store），一起设计可以共用同一套 SQLite / PostgreSQL 布局。重写要求：原 29 个故障窗口逐个映射到“经过 Runner 的工具调用”，第 9 节的 6 个场景并入；Outbox、对账、幂等保留期等应用合同仍要有可运行的实验，不能因为换成框架而丢掉。

### 待决（需要 lewislau 拍板）


- **D-5 新章编号与位置：** 暂用 X01–X06 作第十一部分；X06 是否作为全书收官放在 P06 之后。
- **D-6 Beta 章节的时机：** 现在就基于 RC 写，还是等 harness 在 3.2.0 评审转 Stable。建议先写 Stable 部分，Beta 章节排在阶段 7，动笔前再评估。
- **D-8 K01 是否能完全离线使用 adk-rag：** 阶段 3 验证。

## 11. 更新日志

- **2026-11-27** 创建本计划。核对 adk-rust `main` @ `98515241…`（2026-11-26）的 `README.md`、`STABILITY.md`、`docs/official_docs/migration/2.x-to-3.0.md`、`core/durable-runtime.md`、`security/tool-authorization.md`、`harness/`、`kernel/`、`computer-use/index.md`、`quickstart.md`，以及 `adk-model/src/scripted.rs`；crates.io 上 adk-rust、graph-flow、langchain-rust 的版本与下载数据。部分细节由子代理阅读源码文档后汇总，标注“推断”的条目需在阶段 0 实测。
- **2026-11-27** 记录 D-2（全书纯 adk）、D-4（标签 + 归档链接）、D-9（逐章合并）。开始阶段 0：在沙盒装好 Rust 1.99.1，按文件取到基线源码，探针工程编译运行通过（测量见 6.0 节）；新增 `learn-agent-rust-adk.json`、`fetch-adk-rust.py`、`learn_agent_rust_adk.py`、`check-learn-agent-rust-snippets.py`、`learn-agent-rust-adk-refs.py`、`snippets/adk-trace.rs`；`lessons.json` 加 `stack` 字段并接入同步脚本与课程地图。实测推翻了阶段 0 之前对 D-3 的建议（git + rev 改为 path patch），D-3 与 D-7 更新了建议，等待拍板。
- **2026-11-27** lewislau 确认 D-3（path patch）与 D-7（Rust 1.99.1），已移到“已定”。核对：标签 `learn-agent-rust-v1` → `e8707197ad15`；Mac 上 `.cache/adk-rust` 为 git 检出的基线提交，`--check` 通过。阶段 0 完成。
- **2026-11-27** 阶段 1 试点。R02 全部迁移上线（工程、验证器、正文、配图、源码引用、全书代码库、导读页迁移说明），独立审查后修正 11 处；P02 ADK 部分工程与验证器完成，未接入正文。5 条继续条件全部满足，结论 GO（6.1 节）。脚本改动：`check-learn-agent-rust-snippets.py --sync` 改为在临时副本里运行 cargo 并写回锁文件；轨迹片段加 `#![allow(dead_code)]`、错误码、只给非 user 作者标 final；`verify-agent-experiments.py --lesson ID` 只重跑并更新指定章的检查记录（逐章上线用）；`templates/agent-experiments-run.py` 新增 `fetch-adk`、为 `adk3` 章节在临时目录旁链接源码；`package-agent-experiments.py` 打包 `fetch-adk-rust.py` 与基线文件、标注 ADK 章节、实验页加迁移与 v1 归档说明；`check-agent-experiment-download.py` 先取或链接 adk 源码；CI 缓存键加入基线文件。新增待决 D-10。
- **2026-11-27** 按 D-10 方案（a）完成 P02：ADK 工程移到 `code/side-effect-reliability/adk/`，`patch_config` 支持子目录深度，`check-learn-agent-rust-snippets.py` 检查章节内所有带 `.cargo/config.toml` 的工程，`run.py` 会检查并构建章节内的 ADK 子工程，P02 主验证器打包 `adk/` 与取源码脚本并先调用 ADK 验证器；P02 标为 `adk3`，导读页迁移说明加上专题 2。专题 2 正文新增第 9 节、目标、常见误区、结论与第 6 道检查题，审查后修正 7 处。阶段 1 完成。

- **2026-11-27** 阶段 2 进行中。R00、R01、R03、R04 已迁移（工程、验证器、正文、配图、源码引用、全书代码库），本次在沙盒（Linux）里把 R00–R04、R02、P02 的验证器全部 `--check` 复跑通过，证明 Mac 上生成的产物跨平台逐字节一致。两个审查子代理对 R00/R01、R03/R04 找出必改 7 处、应改 22 处，已修正：R01 源码引用补全循环各步位置、新增 `loop-limit` 场景与 `--max-iterations`、补旧版场景对应表、说明自动压缩与两份历史；R03 改正“批准绑定调用 ID”的错误（指纹不含调用 ID）、补“多出的决定等于预先批准”、补对应表；R04 引用文档给出扣下结果的理由、修正 `after_tool` / `after_agent` 运行条件、panic 保护只覆盖 `before_tool`、补对应表；R00 说明 `tool.not_found (file.missing)`。`architecture.md` 按 ADK-Rust 重写，`setup.md` 新增第 4 节“准备 ADK-Rust 3.0 源码”，总览页实践状态表与迁移说明更新。剩余：G01–G03 与图编排导读。
- **2026-11-27** 阶段 2 完成。G01–G03 迁移到 adk-graph：三个工程（`graph-state-lab`、`graph-resume-lab`、`graph-parallel-lab`）、验证器 `verify-agent-orchestration.py` 重写（`--lab`，G02 每条命令一个独立进程）、三章正文重写（保留迁移思考原文，G02 问题里的 CAS 改为 CheckpointConflict）、四张配图、源码引用（`learn-agent-rust-adk-refs.py` 新增三章 SPEC，共 9 章）、`lessons.json` / `experiments.json` / `review-prompts.json` 登记、全书代码库重新打包。`graph-orchestration.md` 改写为 LangGraph ↔ adk-graph 导读；第 6 章改名“图暂停、检查点与恢复”。审查后修正：递归上限按整次运行累计、“整步重跑”只在崩溃时成立、汇合只看无条件入边、`typo_channel` 探针改为只写错名字、路由函数不再比较 `Option`、G02 README 与正文补可直接复制的运行命令、冲突实验屏障的注释、子图映射与检查点要求。CI 三个工作流补取 adk 源码（6.2 节）。`course-conventions.md` 的 G01–G03、R04 段落更新。验证：三实验 `--check`、`verify-agent-experiments.py --lesson G01/G02/G03`、`package --check`、下载包逐章 `--offline` 测试、sync / review / snippets / refs `--check`、站点构建全部通过。

## 12. 资料来源

- ADK-Rust 仓库与 README：https://github.com/zavora-ai/adk-rust
- 稳定度与弃用政策：https://github.com/zavora-ai/adk-rust/blob/main/STABILITY.md
- 2.x → 3.0 迁移指南：https://github.com/zavora-ai/adk-rust/blob/main/docs/official_docs/migration/2.x-to-3.0.md
- 3.0 新特性：https://github.com/zavora-ai/adk-rust/blob/main/docs/official_docs/whats-new-3.0.md
- 持久运行：https://github.com/zavora-ai/adk-rust/blob/main/docs/official_docs/core/durable-runtime.md
- 工具授权：https://github.com/zavora-ai/adk-rust/blob/main/docs/official_docs/security/tool-authorization.md
- Computer Use：https://github.com/zavora-ai/adk-rust/blob/main/docs/official_docs/computer-use/index.md
- `ScriptedLlm` 源码：https://github.com/zavora-ai/adk-rust/blob/main/adk-model/src/scripted.rs
- 官网文档（截至 2026-11-27 仍对应 2.1）：https://adk-rust.com/zh-CN/docs
- crates.io：https://crates.io/crates/adk-rust · https://crates.io/crates/graph-flow · https://crates.io/crates/langchain-rust
