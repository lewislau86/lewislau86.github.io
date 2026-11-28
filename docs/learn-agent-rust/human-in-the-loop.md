---
title: "第 22 章：人工介入与审批恢复"
description: "用 ADK-Rust 3.0 把发布调用挂起等人批准：会话与审批记录存在 SQLite 文件里，每一步都可以是独立进程；看批准、拒绝、改参数批准、澄清各自怎样恢复，以及需求变了时为什么要先撤回旧批准。"
pageClass: learn-agent-rust-course
prev:
  text: 第 21 章 · 评估、反思与有界修复
  link: /learn-agent-rust/evaluator-reflection
next:
  text: 第 23 章 · 模式组合与选型实战
  link: /learn-agent-rust/pattern-composition
---

# 第 22 章：人工介入与审批恢复

[课程总览](./index.md) · [上一章](./evaluator-reflection.md) · [本部分导读](./agent-design-patterns.md) · [学习路径](./learning-path.md#d07) · [下一章](./pattern-composition.md)

::: tip 本章学习目标
- 区分三种人工介入：补充信息（澄清）、做决定（批准或拒绝）、改内容（改参数批准），以及它们各自让工作流从哪里继续。
- 让等待人的调用跨进程保留：会话与审批记录都放进 SQLite 文件，每一步都可以是新进程。
- 说清批准绑定的是什么：一次具体的调用，而不是用户的意图；需求变了，要先撤回还没用掉的批准。

**前置：** [第 3 章：工具权限与审批](./permissions.md)、[第 6 章：图暂停、检查点与恢复](./graph-pause-resume.md)、[第 17 章：提示链与条件路由](./prompt-chaining-routing.md)。

**实践方式：** 下载<a href="/learn-agent-rust/human-in-the-loop.zip" download>完整 human-in-the-loop.zip</a>，按[第 1 节](#hands-on)取一次 ADK-Rust 源码后运行；无需模型密钥。
:::

::: info 本章已迁移到 ADK-Rust 3.0
旧版用 graph-flow 的节点手写等待记录、修订号和批准状态，跨进程靠自己写 JSON 文件，可从 git 标签 `learn-agent-rust-v1` 取得。新版用 ADK-Rust 的工具策略挂起发布调用，审批记录和会话都存进 SQLite（`SqliteApprovalStore`、`SqliteSessionService`），发布流程是一个 `SequentialAgent`。[对应表](#old-scenarios)列出了场景的变化。
:::

[第 3 章](./permissions.md)讲过审批的基本做法：策略要求批准，调用挂起；审批人按指纹记下决定；下一次运行恢复，决定被取走、用掉。那一章的一切都在一个进程里。

真实的人工介入很少这么快。助手写好升级说明、提出发布，编辑可能明天才看到；看的时候也许会改一句话，也许发现版本没写清楚，也许干脆改了主意。这一章把三个问题放在一起：等待能不能跨进程保留？人的不同回应让流程从哪里继续？批准以后情况变了怎么办？

<LearnAgentRustMap active="human-in-the-loop" />

<!-- experiment-library:start -->

全书实验可从[统一代码库](./experiments.md#human-in-the-loop)下载；解压后进入 `chapters/human-in-the-loop/`，或在代码库根目录运行 `python3 run.py run D07`。

<!-- experiment-library:end -->

::: info 本章实验状态
工具策略、挂起与恢复、`SqliteSessionService`、`SqliteApprovalStore`、改参数批准、`SequentialAgent` 的恢复位置，都是 ADK-Rust 的真实实现；发布写的是临时目录里的真实文件。写作者与发布者的模型是按规则回复的替身，审批人的决定由场景给出。场景里每一步都重新打开 SQLite 文件；另有一段由验证脚本用独立进程逐条运行的记录。没有用户认证，也没有外部发布服务；同一时间只有一个写者。
:::

## 1. 先运行：八个场景 {#hands-on}

下载并解压工程，先取一次 ADK-Rust 源码再运行：

```sh
cd human-in-the-loop
python3 fetch-adk-rust.py ../adk-rust    # 需要 git 与 GitHub 访问；不行时加 --method cdn
cargo run --locked
```

编译时会看到 adk-core 的 3 条弃用警告（上游固定 Rust 1.95.0，本课程用 1.99.1），不影响运行和检查。

<<< @/public/learn-agent-rust/outputs/d07-summary.txt

`steps` 是按顺序执行的步骤：`start` 和 `say` 是用户发来的消息，`resume` 是只为恢复等待中的调用而发起的运行（用户这一轮为空），`approve`、`deny`、`edit`、`edit-target`、`revoke` 是审批人的动作；后缀 `:held` 表示这一步之后，审批记录里还有没做决定的请求。`writer_runs` 是写作者一共运行了几次，`published` 是 `releases/` 下最后有哪些文件（`(edited)` 表示内容是审批人改过的），`pending` 是最后仍在等待的调用数。

## 2. 发布流程与挂起

发布流程是一个 `SequentialAgent`：写作者写一句升级说明（`output_key` 写进状态 `report`），版本检查看稿子里是否标着“目标版本待确认”，发布者调用 `publish_report`：

<<< @/public/learn-agent-rust/code/human-in-the-loop/src/main.rs#workflow

应用策略要求每次发布都先经人批准，改过的参数也要再过一遍这里：

<<< @/public/learn-agent-rust/code/human-in-the-loop/src/main.rs#policy

会话和审批记录放在同一个 SQLite 文件里。场景的每一步都从这个文件重新打开两者，和一个新进程看到的一样：

<<< @/public/learn-agent-rust/code/human-in-the-loop/src/main.rs#stores

<<< @/public/learn-agent-rust/outputs/d07-approve.txt

第一步，发布调用被挂起：工具结果的状态是 `held`，内容是 `confirmation_pending`；框架替发布者写下一句固定的回答（“Tool confirmation required…”），这次运行就结束了。等待中的请求记进了 SQLite 里的审批记录，`[pending]` 一行是这一步结束时从审批记录里列出来的；第 5 节的记录里，另一个进程同样读得到它。审批人批准以后，`resume` 发起一次用户这一轮为空的运行。

恢复从哪里开始？`SequentialAgent` 在挂起的事件上记下了自己停在哪个子 Agent，恢复时直接从发布者继续：写作者和版本检查没有再运行（`writer_runs=1`），发布者取走批准，写出 `releases/3.0.md`。`no-decision` 在没有决定时就恢复：调用仍然挂着，发布者回答“没有发布：Tool 'publish_report' requires confirmation…”，`pending=1`。

## 3. 人的几种回应

| 回应 | 场景 | 框架怎样处理 | 流程从哪里继续 |
| --- | --- | --- | --- |
| 批准 | `approve` | 恢复时取走决定，按原参数执行 | 挂起的发布者 |
| 拒绝 | `deny` | 带上拒绝理由，作为工具结果告诉模型（`refused`） | 挂起的发布者，发布者说明没有发布 |
| 改参数批准 | `edit`、`edit-forbidden` | 用审批人改过的参数执行，执行前再过一遍策略 | 挂起的发布者 |
| 补充信息 | `clarify` | 没有调用挂起；版本检查上报（escalate），工作流停下，提问交给人 | 下一条消息让工作流**从头**再来 |

`edit` 里审批人把正文补了一句“并更新 CI 脚本”再批准，发布出去的是改过的内容。`edit-forbidden` 里审批人把目标改成了 `../outside.md`，策略重新检查时拒绝，什么都没写：

```text
Tool 'publish_report' with the approver's edited arguments denied by policy: publish_outside_policy
```

审批人也受策略约束。改参数批准不是绕过策略的后门。

`clarify` 的第一条消息没写版本，写作者的稿子里标着“目标版本待确认”，版本检查上报停下，提出问题。这里没有挂起的调用，所以下一条消息“目标版本是 3.0”让工作流从头开始：写作者带着新信息重写（`writer_runs=2`），之后才走到发布与批准。补充信息改变的是输入，要重新生成；批准只决定一个已经提出的调用，从挂起处继续。

## 4. 批准以后，需求变了

<<< @/public/learn-agent-rust/outputs/d07-changed-mind.txt

`changed-mind` 里编辑批准了发布 3.0，恢复之前用户又说“改成 3.1 再发”。下一次运行发生的事是：工作流仍从挂起的发布者继续，框架先取走那条批准、按原参数执行了发布，然后才调用发布者的模型；写作者根本没有运行。这不是替身模型的选择：轨迹里 `--- say` 之后的第一行就是发布成功的工具结果，前面没有新的调用，模型没有机会拦下它。用户的新消息没有改变挂起的调用，也没有让批准失效；这一轮里 3.1 的要求也没人处理（替身的回答没有提它，真实模型也许会提一句，但发布已经发生了）。

原因在于批准绑定的是什么：决定按调用的指纹记下，指纹由执行的 Agent、工具和参数组成，和用户之后说了什么无关。只要调用还挂着、挂起它的发布者之后没有再运行过，下一次运行就先回到发布者，不管用户这次说了什么。

所以需求变化时，应用要先撤回还没用掉的批准。`changed-mind-revoked` 的做法：

1. 对同一个指纹再记一次决定，改成拒绝（`revoke`，理由是“需求变了：改发 3.1”）；应用自己记下了每次决定的指纹，所以找得到它。撤回之前，代码先确认那次调用还挂着：批准已经用掉时再记一条拒绝，它会变成预先的拒绝，以后同样的发布不问人就被拒（[第 3 章](./permissions.md)说过，只应对还在等待的请求做决定）。
2. 发起一次 `resume`，让挂起的发布者取走这条拒绝、说明没有发布，了结这一步。
3. 再处理用户的新要求：没有挂起的调用了，工作流从头开始，写作者写出 3.1，发布再次挂起，重新批准后才发布 `releases/3.1.md`。

<<< @/public/learn-agent-rust/outputs/d07-changed-mind-revoked.txt

## 5. 每一步一个进程

场景里的“每一步重新打开文件”还在一个进程里。验证脚本另外用独立进程逐条运行 `disk` 子命令，状态只存在于临时目录的 SQLite 文件里：

<<< @/public/learn-agent-rust/outputs/d07-disk.txt

开始、读出等待中的请求、改参数批准、恢复、查看文件，每条命令都是一个新进程，状态全靠那个 SQLite 文件传下去。最后一条在发布之后想撤回批准：调用已经不再挂着，代码拒绝了这次撤回，没有留下一条预先的拒绝。

![左边是三个进程：第一个运行到发布并挂起，第二个读出等待中的请求并记下决定，第三个从发布这一步恢复，写作者不再运行；右边是批准以后需求变了：不撤回时旧批准被用掉、发布旧内容，先撤回再重新请求才发布新内容。](/learn-agent-rust/figures/d07-pattern-flow.svg)

左右两半分别是挂起与恢复（每一步都可以是独立进程，图里只画了三步）、需求变化时的两种做法；每半底部两行是本章场景的实际结果。

### 全部场景的实际结果

<!-- d07-results:start -->

| 场景 | 步骤（:held 表示之后有调用在等批准） | 写作者运行次数 | 发布的文件 | 最后仍在等待 |
| --- | --- | --- | --- | --- |
| `approve` | `[start:held,approve,resume]` | `1` | `[3.0.md]` | `0` |
| `no-decision` | `[start:held,resume:held]` | `1` | `[]` | `1` |
| `deny` | `[start:held,deny,resume]` | `1` | `[]` | `0` |
| `edit` | `[start:held,edit,resume]` | `1` | `[3.0.md(edited)]` | `0` |
| `edit-forbidden` | `[start:held,edit-target,resume]` | `1` | `[]` | `0` |
| `clarify` | `[start,say:held,approve,resume]` | `2` | `[3.0.md]` | `0` |
| `changed-mind` | `[start:held,approve,say]` | `1` | `[3.0.md]` | `0` |
| `changed-mind-revoked` | `[start:held,approve,revoke,resume,say:held,approve,resume]` | `2` | `[3.1.md]` | `0` |

<!-- d07-results:end -->

### 与旧版场景的对应 {#old-scenarios}

| 旧版（graph-flow 夹具） | 新版（ADK-Rust） | 变化 |
| --- | --- | --- |
| `approve` | `approve` | 挂起与恢复由框架完成，状态存在 SQLite。 |
| `clarify` | `clarify` | 版本检查上报停下；补充信息让工作流从头再来。 |
| `edit` | `edit`、`changed-mind`、`changed-mind-revoked` | 审批人改参数批准；批准后需求变化要先撤回旧批准。 |
| `deny` | `deny` | 拒绝理由作为工具结果告诉模型。 |
| `stale` | `changed-mind` | 旧版由应用比对修订号拒绝旧批准。新版里挂起的调用没有变（写作者没有重新运行），旧批准就被用掉了；撤回是应用的事。 |
| `duplicate` | （见第 3 章 `replay`） | 一次批准只放行一次，第 3 章已经演示；本章 `d07-disk.txt` 的最后一条演示批准用掉以后不能再撤回。 |
| `budget` | （无） | 预算与本章无关，见第 16 章与第 24 章。 |
| （无） | `no-decision`、`edit-forbidden`、`changed-mind-revoked` | 没有决定就恢复；改过的参数被策略拒绝；先撤回再处理新要求。 |
| 7 个场景、4 项测试 | 8 个场景、4 项测试 | — |

验证脚本把工程打包后在临时目录解压，在旁边放好 ADK-Rust 源码，运行格式、Clippy、4 项 Rust 测试和离线构建；摘要和 8 条详细轨迹各连跑两次必须逐字节相同，`disk` 记录由独立进程生成，并把结果表写回正文。维护者在网站仓库根目录执行：

```sh
python3 scripts/fetch-adk-rust.py .cache/adk-rust    # 只需一次；或设 ADK_RUST_SRC
python3 scripts/verify-agent-patterns-adk.py --lesson D07
python3 scripts/generate-learn-agent-rust-figures.py --lesson D07
python3 scripts/verify-agent-patterns-adk.py --lesson D07 --check
```

## 框架替你做了什么、没做什么

| 框架做了 | 仍归应用 |
| --- | --- |
| 策略要求批准时挂起调用，记进审批记录；SQLite 实现让它跨进程保留。 | 决定哪些调用要人批准；把等待中的请求展示给对的人。 |
| 决定按指纹匹配，取走即用掉；改过的参数再过一遍策略。 | 认证审批人；记下自己做过哪些决定。 |
| 工作流在挂起处停下，下一次运行从那个子 Agent 继续。 | 需求变化时撤回还没用掉的批准，并了结挂起的那一步。 |
| 拒绝理由作为工具结果告诉模型。 | 补充信息的提问与重来（本章用版本检查上报实现）。 |

<!-- adk-refs:start -->

## 在 ADK-Rust 源码里

本章的挂起、审批、恢复与工作流的恢复位置，在 ADK-Rust 里分布在这几处：

| 本章内容 | 源码位置 | 对照要点 |
| --- | --- | --- |
| 挂起后这一轮的回答 | [`adk-agent/src/llm_agent.rs` 第 292 行](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-agent/src/llm_agent.rs#L292) | 调用被挂起时框架写下的固定回答；运行到此结束，调用记在审批记录里 |
| 审批记录 | [`adk-core/src/governance.rs` 第 997 行](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-core/src/governance.rs#L997) | 决定按调用指纹（Agent、工具、参数）记下；下一次同样的调用取走它，一次批准只放行一次 |
| 改参数批准 | [`adk-core/src/governance.rs` 第 884 行](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-core/src/governance.rs#L884) | 批准人改过的参数会再过一遍应用策略和工具检查，然后用它执行 |
| SQLite 审批记录 | [`adk-session/src/approval.rs` 第 579 行](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-session/src/approval.rs#L579) | 和会话放在同一个 SQLite 文件里，进程退出后等待中的请求与决定都还在 |
| 工作流停在挂起处 | [`adk-agent/src/workflow/loop_agent.rs` 第 692 行](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-agent/src/workflow/loop_agent.rs#L692) | 挂起的调用让工作流停下，后面的子 Agent 不运行 |
| 从挂起处恢复 | [`adk-core/src/governance.rs` · `workflow_resume_positions`](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-core/src/governance.rs#L3757-L3796) | 调用还挂着、挂起它的子 Agent 之后没再运行过，下一次运行就从它开始，不管用户这次说了什么；前面已完成的子 Agent 不再运行 |

源码固定在 ADK-Rust `98515241133d`（3.0.0，2026-11-26，尚未发布到 crates.io）。本节由 `scripts/learn-agent-rust-adk-refs.py` 生成。

<!-- adk-refs:end -->

::: warning 常见误区
- **以为用户的新消息会让挂起的调用作废。** 只要调用还挂着，下一次运行先回到它，已批准就照原参数执行。
- **把补充信息当成批准。** 补充信息改变输入，工作流要从头再来；批准只决定一个已经提出的调用。
- **以为审批人改参数可以绕过策略。** 改过的参数会再检查一遍。
- **以为恢复会把整个工作流重跑一遍。** 只从挂起的子 Agent 继续，前面的步骤不再运行。
- **批准用掉以后再“撤回”。** 那会留下一条预先的拒绝；撤回前先确认调用还挂着。
:::

<!-- transfer-thinking:start -->

## 迁移思考：需求变了，先撤回旧批准

发布调用已经批准、还没恢复，用户又说“改成 3.1 再发”，下一次运行会发生什么？先给出你的判断，再展开下面的推演。

<details><summary>推演与应用</summary>

批准按调用的指纹（工具与参数）记下，不按用户的意图。挂起的调用让工作流停在发布这一步，下一次运行先恢复它：用掉那条批准，发布 3.0 的旧内容，写作者根本不会重写。所以应用在需求变化时，要先把还没用掉的批准改成拒绝，了结挂起的那一步，再处理新要求。

付款、发邮件、改配置都一样：授权绑定具体内容，内容或意图变了，就撤回旧授权再重新请求。

</details>

这是一道迁移练习，推演不代表新增实验已通过。对照[全书审查中的证据层次](./course-review.md#evidence-layers)，说明你的判断还需要哪一级证据。

<!-- transfer-thinking:end -->

## 本章结论

人工介入分三种：补充信息让流程带着新输入重来，批准或拒绝决定一个已经提出的调用，改参数批准用审批人的版本执行、但仍受策略约束。ADK-Rust 把等待中的调用和决定记进审批记录，SQLite 实现让它们跨进程保留，工作流从挂起处继续。批准绑定的是一次具体调用，不是用户的意图：需求变了，应用要先撤回还没用掉的批准，了结挂起的那一步，再处理新要求。

## 检查理解

1. `approve` 恢复时，写作者为什么没有再运行？

   <details><summary>参考答案</summary>

   `SequentialAgent` 在挂起的事件上记下了停在哪个子 Agent，下一次运行直接从发布者继续，前面已完成的写作者和版本检查不再运行。

   </details>

2. `clarify` 和 `approve` 都等了人，为什么一个从头再来、一个从中间继续？

   <details><summary>参考答案</summary>

   `clarify` 没有挂起的调用，版本检查只是上报停下，下一条消息让工作流从头运行，写作者带着新信息重写。`approve` 有挂起的调用，工作流从挂起处继续。

   </details>

3. `edit-forbidden` 里审批人已经批准了，为什么没有发布？

   <details><summary>参考答案</summary>

   改过的参数要再过一遍应用策略。目标 `../outside.md` 不在 `releases/` 下，策略拒绝。

   </details>

4. `changed-mind` 里用户已经说了“改成 3.1”，为什么发布的还是 3.0？

   <details><summary>参考答案</summary>

   批准按调用的指纹记下，与用户之后说的话无关；挂起的调用又让下一次运行先从发布者继续，于是取走批准、按原参数发布了 3.0，写作者没有运行。

   </details>

5. 撤回旧批准以后，为什么还要先 `resume` 一次，再处理新要求？

   <details><summary>参考答案</summary>

   调用还挂着、发布者之后又没运行过，下一次运行就会先回到发布者。先用一次 `resume` 让发布者取走拒绝、说明没有发布，了结这一步；之后用户的新要求才会让工作流从头开始。

   </details>

## 参考资料

- [LangGraph：Interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts)：暂停与恢复的设计问题，可与本章和第 6 章对照。
- [ADK-Rust 固定源码](https://github.com/zavora-ai/adk-rust/tree/98515241133d24f7e41f8fd272649035416a142f)：审批记录、SQLite 存储与工作流恢复位置的实现。

下一章：[第 23 章 · 模式组合与选型实战](./pattern-composition.md)。回到[本部分导读](./agent-design-patterns.md)比较模式。
