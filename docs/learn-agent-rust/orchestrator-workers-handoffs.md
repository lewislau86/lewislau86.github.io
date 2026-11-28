---
title: "第 20 章：协调者、工作者与任务交接"
description: "用 ADK-Rust 3.0 的 TeamSpec 把协调者、工作者和专员写成数据：委派把工作者当工具调用、结果交回协调者；交接把控制权交给专员，下一轮也由它回答。再看执行回执怎样记下失败、预算与中断。"
pageClass: learn-agent-rust-course
prev:
  text: 第 19 章 · 规划、执行与动态重规划
  link: /learn-agent-rust/plan-execute-replan
next:
  text: 第 21 章 · 评估、反思与有界修复
  link: /learn-agent-rust/evaluator-reflection
---

# 第 20 章：协调者、工作者与任务交接

[课程总览](./index.md) · [上一章](./plan-execute-replan.md) · [本部分导读](./agent-design-patterns.md) · [学习路径](./learning-path.md#d05) · [下一章](./evaluator-reflection.md)

::: tip 本章学习目标
- 区分两种分工：**委派**（把工作者当工具调用，结果交回，协调者接着说话）和**交接**（把控制权交给专员，协调者不再接着说话）。
- 用 `TeamSpec` 声明成员、关系和策略，看框架怎样限制并发、隔离上下文、拒绝没有声明的交接。
- 读懂执行回执：每次委派与交接都记在里面，失败、预算用完和中断各留下什么痕迹。

**前置：** [第 9 章：子 Agent 与上下文隔离](./subagents.md)、[第 18 章：并行分解与结果归并](./parallel-decomposition.md)、[第 19 章：规划、执行与动态重规划](./plan-execute-replan.md)。

**实践方式：** 下载<a href="/learn-agent-rust/orchestrator-workers-handoffs.zip" download>完整 orchestrator-workers-handoffs.zip</a>，按[第 1 节](#hands-on)取一次 ADK-Rust 源码后运行；无需模型密钥。
:::

::: info 本章已迁移到 ADK-Rust 3.0
旧版用 graph-flow 的节点手写分派、`JoinSet` 收集、交接对象与“归还控制”，可从 git 标签 `learn-agent-rust-v1` 取得。新版用 ADK-Rust 的 `TeamSpec` 声明团队、`CompiledTeam` 运行，三个成员都是 `LlmAgent`。新版里控制权不能“归还”：团队的关系图不允许有环。[对应表](#old-scenarios)列出了场景的变化。
:::

第 18 章的三个检查者是固定的，第 19 章的步骤由规划者一条条补。这一章的任务介于两者之间：要检查几个工作区成员，读了清单才知道；每个成员的检查互不相关，交给同一种工作者去做就行，做完把结果交回来汇总。这是“协调者—工作者”。

检查中发现某个成员引入了 GPL-3.0 依赖。这件事不是再派一个工作者查一查就完了：后面怎么办，要由懂许可证的专员和用户继续谈。这时协调者不该只拿回一个结果，而是把对话交出去。这是“交接”。

两种做法都让另一个 Agent 干活，区别在于：干完以后，谁接着说话。

<LearnAgentRustMap active="orchestrator-workers-handoffs" />

<!-- experiment-library:start -->

全书实验可从[统一代码库](./experiments.md#orchestrator-workers-handoffs)下载；解压后进入 `chapters/orchestrator-workers-handoffs/`，或在代码库根目录运行 `python3 run.py run D05`。

<!-- experiment-library:end -->

::: info 本章实验状态
`TeamSpec`、`CompiledTeam`、委派（降为 `AgentTool`）、交接（`transfer_to_agent`）、团队预算、执行回执与恢复计划，都是 ADK-Rust 的真实实现。三个成员的模型是按规则回复的替身：协调者按清单派工、看到 GPL-3.0 就交接，工作者回固定的 JSON 发现。程序使用暂停的 Tokio 时钟，工作者的停顿只为让委派真正重叠，不代表耗时。真实模型怎样分工、交接得好不好没有测试。
:::

## 1. 先运行：十个场景 {#hands-on}

下载并解压工程，先取一次 ADK-Rust 源码再运行：

```sh
cd orchestrator-workers-handoffs
python3 fetch-adk-rust.py ../adk-rust    # 需要 git 与 GitHub 访问；不行时加 --method cdn
cargo run --locked
```

编译时会看到 adk-core 的 3 条弃用警告（上游固定 Rust 1.95.0，本课程用 1.99.1），不影响运行和检查。

<<< @/public/learn-agent-rust/outputs/d05-summary.txt

每行的字段如下：

- `workers`：工作者被派去检查的成员，按开始的先后排列。
- `peak`：同一时刻最多有几个工作者在进行。
- `worker_saw`：工作者能不能看到协调者会话里的一条备忘（`note` 表示看得到，`-` 表示看不到）。
- `edges`：执行回执里按开始先后记下的每次委派（`delegate`）与交接（`handoff`）及其状态。
- `turn1`、`turn2`：第一轮、第二轮用户消息各由谁回答。
- `license_knew`：交接以后，license 第一次回答时知不知道是什么许可证问题。
- `coverage`：声明过的关系里，这次运行实际走过的比例。
- `stop`：运行没有正常结束时的原因。

## 2. 团队是一份数据

<<< @/public/learn-agent-rust/code/orchestrator-workers-handoffs/src/main.rs#spec

`TeamSpec` 不含任何代码：成员的名字、谁是协调者、成员之间有哪些关系、团队策略。本章把它写成 JSON 再反序列化，同一份定义可以存进配置、交给设计工具或在别的进程里编译。两种关系的区别：

| | 委派（`delegate`） | 交接（`handoff`） |
| --- | --- | --- |
| 怎样发生 | 框架把目标成员包装成一个工具（`AgentTool`），协调者的模型调用它 | 协调者的模型调用 `transfer_to_agent` |
| 干完以后 | 结果作为工具结果交回，协调者接着说话 | 控制权留在目标成员，协调者不再接着说话 |
| 上下文 | 按策略：`isolated` 只给委派请求，不给状态和历史；`shared` 复制协调者的会话状态与历史 | 同一个会话，但接手者只看得到用户的话、自己的回答和会话状态 |
| 本章 | lead → member_check | lead → license |

交接边没有写 `policy`：上下文、超时、失败策略这些设置只对委派边有效，写在交接边上会被拒绝。`maxTransferDepth` 限制一次运行里最多交接几次，`maxDelegationDepth: 1` 让工作者不能再往下委派，本章都没有触到上限。

`compile` 按名字把三个现成的 `LlmAgent` 绑到声明的成员上：

<<< @/public/learn-agent-rust/code/orchestrator-workers-handoffs/src/main.rs#team

编译时框架会检查：成员名不重复、关系两端都是成员、从协调者出发每个成员都可达、关系图没有环。

## 3. 协调者按清单派工

<<< @/public/learn-agent-rust/outputs/d05-two.txt

lead 的模型在一次回复里发出两个 `member_check` 调用，每个成员一个。派几个工作者由清单决定：`three` 的清单有三个成员，就派三个。

这些调用能同时进行，靠两处设置：lead 的 `tool_execution_strategy(Parallel)` 让同一次回复里的工具调用并发执行（默认是一个接一个）；团队策略的 `maxConcurrentDelegations: 2` 规定一个成员同时进行的委派不超过 2 个，多出来的排队。`three` 的 `peak=2` 就是这个上限，它的轨迹里记下了三个工作者开始的时刻：

```text
[workers] 开始时刻（毫秒）：[0, 0, 30]
```

api 和 cli 同时开始，core 等 api 在 30 毫秒时完成才开始（时刻在暂停的时钟上，只表示先后）。

工作者干完，结果作为 `member_check` 的工具结果回到 lead 的对话里，lead 接着汇总。第二轮用户问“接下来呢”，回答的还是 lead。

## 4. 工作者看到什么

会话一开始放了一条只给 lead 看的备忘（状态键 `audit_note`），工作者的指令里引用了它（`{audit_note?}`）。

- `two` 的委派边设为 `isolated`：工作者的会话从空开始，没有状态也没有历史，`worker_saw=[-,-]`。
- `shared-context` 改成 `shared`：框架复制了 lead 的会话状态，工作者的指令里渲染出了备忘，`worker_saw=[note,note]`。

`shared` 还会复制对话历史、转发记忆与制品。但在本章第一轮，lead 发出的委派调用还没有结果，不会被复制；复制来的历史里只剩用户那一条消息，又被委派请求替换掉了。轨迹里 `[workers] 每次请求除系统消息外的消息数：[1, 1]` 说明，两种策略下工作者看到的对话都只有自己的请求，差别在状态上。要注意，团队策略不写 `context` 时默认是 `shared`：委派给谁，就把协调者知道的全部状态交给谁。本章在团队层面设成 `isolated`，只在需要的边上放开。

## 5. 交接：控制权留在接手者

<<< @/public/learn-agent-rust/outputs/d05-handoff.txt

`handoff` 里 core 引入了 GPL-3.0。lead 拿到三个结果后调用 `transfer_to_agent` 交给 license，这一轮由 license 回答。第二轮用户再问，Runner 把消息交给会话里最后一个回答的 Agent，也就是 license，lead 没有再出现。回执里多了一条 `lead→license handoff`，两条声明过的关系都走到了，`coverage=100%`。

但 license 的回答是“不知道是哪个许可证问题”（`license_knew=no`）：替身模型在 license 收到的全部消息里找 GPL-3.0，没有找到。经交接拿到控制权的 Agent，从会话里只看得到用户的话和它自己的回答；lead 的工具调用、工作者交回的结果，它都看不到。交接本身不带任何载荷。

`handoff-note` 补上了这一步：lead 交接之前先调用应用提供的 `handoff_note` 工具，把问题和证据来源写进会话状态；license 的指令里引用了它（`{handoff_note?}`），开口就知道是 core 的 GPL-3.0 依赖（`license_knew=yes`）。

<<< @/public/learn-agent-rust/code/orchestrator-workers-handoffs/src/main.rs#note

交接说明写什么、写到哪里、接手者怎样读，都是应用的事。说明只写结论和出处，不要把工作者的原始输出整段转过去。

交接以后怎样回到 lead？不能再声明一条 license → lead 的交接：`cycle` 加了这条边，团队在编译时就被拒绝（`CyclicTopology`）。团队的关系图必须从协调者出发、无环。要让 lead 重新主导，得由应用决定，比如开一个新会话。所以交接是一个分量很重的决定：只有确实需要专员持续和用户谈下去时才用，只要一个结果就用委派。

`undeclared` 里，lead 想把控制权交给 member_check。member_check 是团队成员，但 lead 和它之间只有委派边，没有交接边。框架没有执行这次交接，而是把错误作为工具结果还给模型：

```text
Agent 'member_check' not found. Available agents: ["license"]
```

模型看到以后自己收场，控制权留在 lead。成员身份不等于可以接手对话；能交给谁，只看声明过的交接边。

## 6. 执行回执

`CompiledTeam` 为每次运行维护一份执行回执（`TeamExecutionSnapshot`）：每次委派和交接是一条记录，带来源、目标、种类、状态和起止时间，同时镜像进会话状态 `__adk_team_execution_v1`。本章把它压成一行：

<<< @/public/learn-agent-rust/code/orchestrator-workers-handoffs/src/main.rs#receipt

`analyze_execution` 再拿回执对照 `TeamSpec`，算出走过了哪些关系、哪些没走过。`two` 的分析结果里 `uncovered: ["lead -Handoff-> license"]`：交接这条路这次没被走到。拿它检查测试集有没有覆盖每条关系，比只看最后的回答可靠。

三种不顺利的情况：

- **`worker-failed`**：cli 的工作者调用模型失败。委派边的失败策略是 `returnError`，失败作为工具结果交回 lead（`{"agent":"member_check","error":"model.unavailable: ..."}`），lead 在汇总里写明检查失败及原因。轨迹里这次工具调用显示 `status=ok`：调用本身算完成，失败写在结果内容里；回执里那条委派记为 `failed`。
- **`budget`**：团队预算 `maxDelegations: 2`，清单却有三个成员。第三个委派一开始就超出预算，整个运行以错误结束（`agent.team.budget_exceeded`），`returnError` 管不到它：它只处理工作者执行时的失败。回执里留下的样子值得注意：第二个委派在运行结束时还没完成，停在 `running`；第三个委派根本没执行，也停在 `running`，因为框架先把它记进回执、再检查预算。
- **`interrupted`**：第一个工作者的结果刚出来，宿主就丢下了事件流，好比进程在这里崩溃。回执里 api 的委派已完成，cli 和 core 的还停在 `running`。`resume_plan` 看回执里最后一条 `running` 的关系（core 那一条），给出的是 `UnsafeDelegate`：

```text
UnsafeDelegate { edge_id: "check-core", target: "member_check", reason: "the edge is fail-closed and has no checkpoint resume contract" }
```

框架不会自动重放一个可能已经执行了一半的委派。委派边默认是 `failClosed`；要能恢复，得改成 `requireCheckpoint` 并让目标成员支持从检查点继续，由持久化的宿主拿着回执恢复。这和[专题 2](./side-effect-reliability.md) 里“结果未知的工具调用不重放”是同一个道理。

![左边是委派：lead 按清单派出工作者，结果交回 lead 汇总，每次委派记进执行回执；右边是交接：lead 先把交接说明写进会话状态，再把控制权交给 license，下一轮也由 license 回答，license 不能再交回 lead。](/learn-agent-rust/figures/d05-pattern-flow.svg)

左右两半分别是委派和交接；底部两行是本章场景的实际结果。

### 全部场景的实际结果

<!-- d05-results:start -->

| 场景 | 派出的工作者 | 同时进行 | 工作者看到备忘 | 执行回执 | 第一轮回答 | 第二轮回答 | license 知道问题 | 关系覆盖 | 异常结束 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `two` | `[api,cli]` | `2` | `[-,-]` | `[delegate:completed,delegate:completed]` | `lead` | `lead` | — | `50%` | — |
| `three` | `[api,cli,core]` | `2` | `[-,-,-]` | `[delegate:completed,delegate:completed,delegate:completed]` | `lead` | `lead` | — | `50%` | — |
| `shared-context` | `[api,cli]` | `2` | `[note,note]` | `[delegate:completed,delegate:completed]` | `lead` | `lead` | — | `50%` | — |
| `handoff` | `[api,cli,core]` | `2` | `[-,-,-]` | `[delegate:completed,delegate:completed,delegate:completed,handoff:completed]` | `license` | `license` | `no` | `100%` | — |
| `handoff-note` | `[api,cli,core]` | `2` | `[-,-,-]` | `[delegate:completed,delegate:completed,delegate:completed,handoff:completed]` | `license` | `license` | `yes` | `100%` | — |
| `undeclared` | `[api,cli,core]` | `2` | `[-,-,-]` | `[delegate:completed,delegate:completed,delegate:completed]` | `lead` | `lead` | — | `50%` | — |
| `worker-failed` | `[api,cli]` | `2` | `[-,-]` | `[delegate:completed,delegate:failed]` | `lead` | `lead` | — | `50%` | — |
| `budget` | `[api,cli]` | `2` | `[-,-]` | `[delegate:completed,delegate:running,delegate:running]` | — | — | — | — | `error:agent.team.budget_exceeded` |
| `cycle` | — | — | — | — | — | — | — | — | `invalid_spec:CyclicTopology` |
| `interrupted` | `[api,cli,core]` | `2` | `[-,-,-]` | `[delegate:completed,delegate:running,delegate:running]` | — | — | — | — | `interrupted:UnsafeDelegate` |

<!-- d05-results:end -->

### 与旧版场景的对应 {#old-scenarios}

| 旧版（graph-flow 夹具） | 新版（ADK-Rust） | 变化 |
| --- | --- | --- |
| `normal` | `handoff` | 交接后不再“归还控制”：团队关系图不允许环，下一轮仍由 license 回答。 |
| `three` | `three` | 工作者由 `AgentTool` 运行，并发上限由团队策略给出。 |
| `failed_worker` | `worker-failed` | 失败按委派边的 `returnError` 交回协调者，记进回执。 |
| `invalid_role` | `undeclared` | 交接目标由声明过的交接边决定，没有声明就作为工具错误还给模型。 |
| `stale` | （无） | 交接载荷的修订号检查属于应用，本章不演示。 |
| `depth` | （无） | `maxDelegationDepth` 设为 1，本章的工作者不再往下委派，没有单独演示。 |
| `budget` | `budget` | 团队预算 `maxDelegations`。 |
| （无） | `two`、`shared-context`、`handoff-note`、`cycle`、`interrupted` | 清单决定工作者数量、上下文策略、交接说明、环被拒绝、中断后的恢复计划。 |
| 7 个场景、4 项测试 | 10 个场景、4 项测试 | — |

验证脚本把工程打包后在临时目录解压，在旁边放好 ADK-Rust 源码，运行格式、Clippy、4 项 Rust 测试和离线构建；摘要和 10 条详细轨迹各连跑两次必须逐字节相同，并把结果表写回正文。维护者在网站仓库根目录执行：

```sh
python3 scripts/fetch-adk-rust.py .cache/adk-rust    # 只需一次；或设 ADK_RUST_SRC
python3 scripts/verify-agent-patterns-adk.py --lesson D05
python3 scripts/generate-learn-agent-rust-figures.py --lesson D05
python3 scripts/verify-agent-patterns-adk.py --lesson D05 --check
```

## 框架替你做了什么、没做什么

| 框架做了 | 仍归应用 |
| --- | --- |
| 编译时检查团队：成员、关系、可达、无环。 | 决定哪些事用委派、哪些事用交接。 |
| 委派降为工具；按策略隔离或共享上下文；限制同时进行的委派数。 | 选上下文策略（默认 `shared` 会交出全部状态）；让协调者的工具调用并发执行。 |
| 交接只能走声明过的边；下一轮交给最后回答的成员。 | 交接时把接手者需要的信息写进会话状态；交接以后怎样回到协调者。 |
| 执行回执、关系覆盖分析、恢复计划；不自动重放未完成的委派。 | 持久保存回执；中断后决定怎样处理停在 `running` 的委派（包括因预算被拒、根本没执行的那一条）。 |

<!-- adk-refs:start -->

## 在 ADK-Rust 源码里

本章的团队定义、委派、交接与执行回执，在 ADK-Rust 里分布在这几处：

| 本章内容 | 源码位置 | 对照要点 |
| --- | --- | --- |
| 团队定义 | [`adk-agent/src/team.rs` · `TeamSpec`](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-agent/src/team.rs#L64-L80) | 成员、协调者、关系与策略都是数据，可以从 JSON 反序列化；编译时按名字绑定到现成的 Agent |
| 两种关系 | [`adk-agent/src/team.rs` 第 307 行](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-agent/src/team.rs#L307) | 这一行与上面两行：委派把对方当工具调用、拿回结果接着说话；交接把控制权交出去，调用者不再接着说话 |
| 团队不许有环 | [`adk-agent/src/team.rs` 第 835 行](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-agent/src/team.rs#L835) | 关系图从协调者出发必须无环、每个成员都可达；“交回”协调者的边会让编译失败 |
| 委派降为 AgentTool | [`adk-agent/src/team.rs` 第 1651 行](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-agent/src/team.rs#L1651) | 按上下文策略决定是否复制协调者的会话状态与历史；`returnError` 把失败作为结果交回 |
| 同时进行的委派 | [`adk-agent/src/team.rs` 第 1632 行](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-agent/src/team.rs#L1632) | 一个成员同时进行的委派不超过 `maxConcurrentDelegations`，其余的排队 |
| 交接只走声明过的边 | [`adk-agent/src/team.rs` 第 1414 行](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-agent/src/team.rs#L1414) | 模型能选的交接目标只有声明过的 Handoff 边；只有委派边的成员不能被交接过去 |
| 接手者看到什么 | [`adk-agent/src/llm_agent.rs` 第 450 行](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-agent/src/llm_agent.rs#L450) | 经交接拿到控制权的 Agent 只看用户的话和自己的回答，看不到协调者的工具调用和工作者的结果 |
| 回执先记边、再查预算 | [`adk-agent/src/team/runtime.rs` · `start_edge`](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-agent/src/team/runtime.rs#L406-L440) | 超出 `maxDelegations` 的那次委派先被记进回执再报错，状态停在 running |
| 恢复计划 | [`adk-agent/src/team.rs` · `CompiledTeam::resume_plan`](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-agent/src/team.rs#L1266-L1303) | 有未完成的委派就给出 `UnsafeDelegate`，不会自动重放 |
| 下一轮由谁回答 | [`adk-runner/src/runner.rs` · `find_agent_to_run`](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-runner/src/runner.rs#L2783-L2814) | 新一轮用户消息交给会话里最后一个回答的 Agent；交接以后就是接手者 |

源码固定在 ADK-Rust `98515241133d`（3.0.0，2026-11-26，尚未发布到 crates.io）。本节由 `scripts/learn-agent-rust-adk-refs.py` 生成。

<!-- adk-refs:end -->

::: warning 常见误区
- **把交接当成“叫别人干活”。** 交接以后控制权不会自动回来；只要一个结果，用委派。
- **以为交接会把前面的结果一起交过去。** 接手者看不到协调者的工具调用和工作者的结果，要靠应用写交接说明。
- **以为团队成员都能互相交接。** 只有声明过的交接边才行，委派边不算。
- **以为委派默认是隔离的。** 团队策略不写 `context` 时是 `shared`。
- **以为回执里 `running` 的委派一定执行过。** 因预算被拒的委派也停在 `running`。
- **中断以后把委派再跑一遍。** 它可能已经执行了一半；恢复计划给的是 `UnsafeDelegate`，不是“重试”。
:::

<!-- transfer-thinking:start -->

## 迁移思考：返回结果与移交控制分开

工作者检查完一个成员以后，为什么不让它接着和用户对话？先给出你的判断，再展开下面的推演。

<details><summary>推演与应用</summary>

工作者的结果要交回协调者汇总，所以用委派：结果返回，协调者接着说话。交接不同：控制权交给接手者，下一轮用户消息也由它回答，团队里又不允许再“交回”协调者。只有确实需要专员持续主导时才交接。

技术客服把账单问题转给账单客服时，应明确交接；后台检索完成以后通常只返回数据。

</details>

这是一道迁移练习，推演不代表新增实验已通过。对照[全书审查中的证据层次](./course-review.md#evidence-layers)，说明你的判断还需要哪一级证据。

<!-- transfer-thinking:end -->

## 本章结论

协调者—工作者和交接都让别的 Agent 干活，差别在干完以后谁说话。委派把工作者当工具调用，结果交回协调者，派几个由输入决定，并发和上下文由团队策略限定；交接把控制权交给专员，后续对话都由它回答，团队里也不能再交回去，专员需要知道的事要由应用写成交接说明。`TeamSpec` 把这些关系写成可检查的数据，执行回执把每次委派与交接记下来，用来检查覆盖、排查失败，并在中断后拒绝盲目重放。

## 检查理解

1. `three` 派了三个工作者，为什么 `peak` 是 2？

   <details><summary>参考答案</summary>

   lead 用 `Parallel` 让同一次回复里的三个调用并发执行，但团队策略 `maxConcurrentDelegations` 是 2，第三个委派要等前面有一个完成才开始。

   </details>

2. `shared-context` 里工作者为什么能看到备忘？换成 `isolated` 呢？

   <details><summary>参考答案</summary>

   `shared` 把 lead 的会话状态复制给工作者，指令模板 `{audit_note?}` 渲染出了备忘。`isolated` 下工作者的会话从空开始，模板渲染为空。

   </details>

3. `handoff` 里 license 为什么不知道是什么问题？`handoff-note` 改了什么？

   <details><summary>参考答案</summary>

   经交接拿到控制权的 Agent 只看得到用户的话和自己的回答，看不到 lead 的工具调用和工作者的结果。`handoff-note` 让 lead 交接前把问题写进会话状态，license 的指令模板读到了它。

   </details>

4. `handoff` 的第二轮为什么由 license 回答？怎样让 lead 重新主导？

   <details><summary>参考答案</summary>

   新一轮用户消息交给会话里最后一个回答的 Agent，交接以后就是 license。团队里不能声明 license → lead 的交接（会成环，编译被拒），要让 lead 重新主导只能由应用另作安排，比如开一个新会话。

   </details>

5. `undeclared` 里 member_check 明明是团队成员，为什么交接被拒绝？

   <details><summary>参考答案</summary>

   lead 和 member_check 之间只有委派边。能交接给谁只看声明过的交接边，这里只有 license。框架把错误作为工具结果还给模型，控制权留在 lead。

   </details>

6. `interrupted` 的恢复计划为什么不是“重新执行那几个委派”？

   <details><summary>参考答案</summary>

   回执里的委派停在 `running`，可能已经执行了一半。委派边默认 `failClosed`，框架给出 `UnsafeDelegate`，交给运维或支持检查点的宿主决定，不自动重放。

   </details>

## 参考资料

- [Building effective agents](https://www.anthropic.com/research/building-effective-agents)：协调者—工作者等工作流模式的工程导读。
- [ADK-Rust 固定源码](https://github.com/zavora-ai/adk-rust/tree/98515241133d24f7e41f8fd272649035416a142f)：`TeamSpec`、`CompiledTeam` 与执行回执的实现。

下一章：[第 21 章 · 评估、反思与有界修复](./evaluator-reflection.md)。回到[本部分导读](./agent-design-patterns.md)比较模式。
