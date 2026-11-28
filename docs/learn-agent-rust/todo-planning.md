---
title: "第 8 章：可见的任务清单"
description: "用 ADK-Rust 3.0 把待办清单放进会话状态：自写 todo_write 工具整批校验并经 state_delta 写回，before_model 回调让每次请求都看到最新清单，再用执行证据核对任务结果。"
pageClass: learn-agent-rust-course
prev:
  text: 第 7 章 · 图并行、归并与子图
  link: /learn-agent-rust/graph-parallel-subgraphs
next:
  text: 第 9 章 · 子 Agent 与上下文隔离
  link: /learn-agent-rust/subagents
---

# 第 8 章：可见的任务清单

[课程总览](./index.md) · [上一章：图并行、归并与子图](./graph-parallel-subgraphs.md) · [下一章：子 Agent 与上下文隔离](./subagents.md)

::: tip 本章学习目标
- 把目标拆成带 ID 和状态的步骤，保存在会话状态里，让每次模型请求都能看到最新清单。
- 校验状态迁移、版本和整批更新，拒绝会破坏现有记录的候选清单。
- 用真实读取与失败对照，区分清单完成、运行停止和任务验收。

**前置：** [第 2 章 · 工具注册与图调度](./tools-and-graph.md)、[第 3 章 · 工具权限与审批](./permissions.md)、[第 4 章 · 生命周期与 Hooks](./hooks.md)；理解 Rust 的枚举、`Result` 和 JSON。

**实践方式：** 下载[本章独立工程](/learn-agent-rust/todo-planning.zip)，按[动手实验](#hands-on)取一次 ADK-Rust 源码后运行；无需模型密钥和数据库。
:::

::: info 本章已迁移到 ADK-Rust 3.0
本章实验基于 ADK-Rust 3.0 发布候选版（固定提交，尚未发布到 crates.io）。旧版本章用标准库自写运行时，清单放在 `Runtime` 结构体里，可从 git 标签 `learn-agent-rust-v1` 取得。新版把清单放进框架的会话状态，校验规则原样保留；变化最大的是“模型怎样看到最新清单”，见第 4 节。[对应表](#old-scenarios)列出了场景的变化。
:::

沿用前面的工作区助手。这次用户说：“读取 README，整理启动说明。”助手准备先读文件，再整理说明，最后核对原文。一次文件读取很短，但这个例子能把长任务中容易混在一起的三件事拆开：原来的目标是什么，现在推进哪一步，还有什么没有完成。

假设工具已经读到了 README，助手的清单却仍显示“读取 README：进行中”。程序应该自动把它改成完成吗？再换一种情况：助手把三项都标成完成，却一次也没读文件。用户应该接受这个结果吗？本章用同一份可运行代码检查这两种情况。

<LearnAgentRustMap active="todo-planning" />

<!-- experiment-library:start -->

全书实验可从[统一代码库](./experiments.md#todo-planning)下载；解压后进入 `chapters/todo-planning/`，或在代码库根目录运行 `python3 run.py run R05`。

<!-- experiment-library:end -->

## 1. 先把步骤从对话里拿出来

只有消息历史时，计划可能夹在用户请求、模型回答和工具结果之间。我们给会话增加一份明确的清单，模型通过 `todo_write` 提交新快照，通过 `todo_read` 查看。

| 条目 ID | 内容 | 建单时状态 |
| --- | --- | --- |
| `read` | 读取 README | `pending` |
| `summarize` | 整理启动说明 | `pending` |
| `check` | 核对说明与原文 | `pending` |

条目 ID 用来判断“这还是原来的步骤吗”；内容给模型和读者看；状态说明推进位置。`goal` 保存用户目标，清单更新接口没有修改它的参数。

::: info 源码与实验范围
本文 Rust 片段均引用 <a href="/learn-agent-rust/code/todo-planning/src/main.rs" download>完整 main.rs</a>，也可在 [GitHub 查看工程](https://github.com/lewislau86/lewislau86.github.io/tree/master/docs/public/learn-agent-rust/code/todo-planning)。[下载包](/learn-agent-rust/todo-planning.zip)包含源码、锁文件、工具链配置和运行说明。

Runner、LlmAgent、会话状态、before_model 回调和应用策略都是 ADK-Rust 的真实实现；文件工具真实读取临时目录。模型是按规则回复的 `PlanLlm`，它只能看到请求内容；会话服务在内存里，验证的是单进程内的清单机制。
:::

<<< @/public/learn-agent-rust/code/todo-planning/src/main.rs#types

`Status` 是枚举，JSON 中对应 `pending`、`in_progress`、`completed`。`done` 这样的拼写会在反序列化时失败。`deny_unknown_fields` 让多出的参数也返回错误，避免模型发送 `force: true` 后误以为应用执行了某种强制更新。[Serde 官方说明](https://serde.rs/container-attrs.html)解释了这两个属性。

`Plan.revision` 是清单版本，从 `0` 开始。模型提交的是 `expected_revision` 加上**完整候选列表**，而不是“把第二行改一下”的模糊文字。接受一次更新，版本加一；读文件、读清单和拒绝更新都不会增加版本。

## 2. 三个状态，先约定哪些路能走

先预测：`pending` 能否直接变成 `completed`？两个步骤能否同时是 `in_progress`？

本章选择一套便于观察的串行规划规则：新步骤从待开始进入，开始后才能完成；当前步骤可以暂时让出，回到待开始。每份清单最多有一个进行中的条目，也允许暂时没有进行中的条目。

![待开始可以进入进行中，进行中可以完成或让出；整份清单校验后才提交。](/learn-agent-rust/figures/r05-state-transitions.svg)

先顺着上方箭头读正常推进，再沿回程箭头看重新规划。已完成是终态；如果发现还需补查，新增一项待办并保留原来的完成记录。每个状态也允许保持原状，这样更新当前步骤时可以原样带上其他条目。

<<< @/public/learn-agent-rust/code/todo-planning/src/main.rs#transition

这套规则属于教学应用的选择。其他产品可以允许多个进行中、撤销完成或跳过步骤，但必须明确相应语义。这里限制一个进行中，是为了显示“当前关注点”，并没有实现锁、任务领取或并行调度。

除了迁移，我们还固定以下输入约束：

| 检查 | 本章规则 | 解决的问题 |
| --- | --- | --- |
| 列表大小 | 1–8 项 | 保持练习清单有界。 |
| ID | 1–24 个小写 ASCII 字母、数字或连字符，且不重复 | 稳定识别条目。 |
| 内容 | 去掉首尾空白后非空，原始内容最多 120 个 Unicode 字符 | 避免空任务和过长说明。 |
| 已有条目 | 保留 ID 和原内容，允许调整顺序 | 避免把旧步骤悄悄改成另一件事。 |
| 新增条目 | 初始状态必须是 `pending` | 让新增工作先进入计划。 |
| 版本 | 与当前清单版本一致 | 拒绝根据旧快照提交的替换。 |

8、24、120 都是本章选定的应用上限，不是性能测试得到的最佳值。

## 3. 整份先检查，再一次替换

假设候选快照的第一项合法地变成进行中，第三项却是空内容。如果边遍历边修改，发现第三项错误时，第一项可能已经变了。调用者收到“更新失败”，实际状态却只改了一半。

我们的做法是：先检查整份候选列表，直到所有规则都通过，才替换。

<<< @/public/learn-agent-rust/code/todo-planning/src/main.rs#validate

函数末尾的两行是唯一的提交位置；前面任何 `return Err(...)` 都会留下原清单和原版本。`expected_revision` 解决另一种问题：模型看到版本 1，清单已经被推进到版本 2，这时模型仍提交“基于版本 1”的候选列表，函数首先返回 `todo.revision_conflict`，模型应读取最新状态再重新组织更新。

即使同一候选列表连续提交，接受第一次后版本也会改变，第二次携带旧版本就会冲突——前提是第二次提交时能读到第一次的结果。第 4 节会看到，同一批工具调用里这一点并不自动成立。本章没有把更新设计成幂等重放接口；需要重放与存储时，要额外设计请求身份和提交语义。

## 4. 清单放在哪里，模型怎样看见

ADK-Rust 的会话（session）除了事件历史，还有一份**会话状态**（session state）：键值对，随会话保存。改状态的正规途径不是直接写，而是在事件上附一份 `state_delta`；框架把事件追加进会话时，把其中的键合并进状态。工具通过 `ctx.actions()` / `ctx.set_actions()` 修改自己这次调用的事件动作：

<<< @/public/learn-agent-rust/code/todo-planning/src/main.rs#tools

`todo_write` 从 `ctx.session()` 读出当前清单，调用上一节的校验，通过后把新清单放进 `state_delta`，返回值也是新清单。这次调用的事件产出时，Runner 把 `state_delta` 合并进会话状态，之后的读取就能看到。校验失败时返回 `InvalidInput` 类错误，错误码是 `todo.*`；按[第 1 章](./agent-loop.md)讲过的规则，这一类错误会把消息带给模型。轨迹里每次成功的 `todo_write` 后面都跟着一行 `state   plan = {...}`，就是这次调用事件上的 `state_delta`。

这里有一个容易漏掉的时间差：模型一次回复里可以有多个工具调用，框架把这一批全部执行完才产出它们的事件。也就是说，同一批里第二个 `todo_write` 读会话状态时，第一个的写入还没合并。`same-batch-naive` 场景里，一次回复带两个基于版本 1 的 `todo_write`（一个开始读取，一个新增步骤），两个都被接受，最终清单版本是 2，“开始读取”这一改动被第二次写入覆盖掉了，版本检查没有起作用。所以 `todo_write` 按本次运行记下自己刚写的清单，同一批里后面的调用读它；`same-batch` 场景里第二个调用因此得到 `todo.revision_conflict`，“开始读取”保留了下来。harness 的清单工具也是这样处理的（见本章末尾）。

清单写进了会话状态，模型下一次请求时能看到吗？这里有一个实测出来的关键细节。LlmAgent 的 `instruction` 支持 `{键}` 模板，按会话状态替换，看起来正好用来放清单。但**模板只在每次运行开始时渲染一次**：同一次运行里，工具写进状态的新清单，不会出现在后面几次请求的 instruction 里。`template-only` 场景只用模板，结果是这样：

<<< @/public/learn-agent-rust/outputs/r05-template-only.txt

三次请求里，instruction 带的清单一直是“未建单”。其实第二次请求的历史里已经有第一次 `todo_write` 的结果（版本 1）：请求里同时出现了两份互相矛盾的清单。`PlanLlm` 被设计成只信 system 内容里的清单，所以它以为还没建单，又按版本 0 提交，被 `todo.revision_conflict` 拒绝；真实模型面对这种矛盾可能选对，也可能选错，这正是每次请求都要放入最新清单的理由。版本检查在这里起了作用：模型的视图过期时，更新不会覆盖真实清单。摘要里的 `next_run_first_seen=1` 说明模板并非不会更新：同一会话的下一次运行开始时重新渲染，就看到了版本 1。

要让每次请求都带上最新清单，本章用 before_model 回调：

<<< @/public/learn-agent-rust/code/todo-planning/src/main.rs#visibility

回调在每次请求模型之前运行，`ctx.state()` 读到的是会话当前的状态，上一轮工具写入的清单已经在里面；回调把它作为一条 system 内容插到请求里。模型是这样读清单的：

<<< @/public/learn-agent-rust/code/todo-planning/src/main.rs#model

`PlanLlm` 拿不到运行时的任何内部对象，只从请求的 system 内容里找最后一处“当前清单：”，读后面的清单。轨迹里记录的“request N: revision=…”就是它每次请求实际读到的版本。

![会话状态里的清单由 before_model 回调放进每次请求，PlanLlm 提出调用，Runner 经过策略执行工具，todo_write 校验后经 state_delta 写回；下方是正常读取与只改完成标记两次运行的对照。](/learn-agent-rust/figures/r05-visible-loop.svg)

本实验的四个工具和应用策略这样接起来：`todo_write`、`todo_read`、`read_file` 允许，`write_file` 拒绝。

<<< @/public/learn-agent-rust/code/todo-planning/src/main.rs#wiring

因此，计划里出现“写入 summary.txt”只表示有这样一项待办。是否允许写入，仍由应用策略判断（[第 3 章](./permissions.md)）。`write_file` 是一个真的会写文件的工具，策略拒绝它，它就不执行。

## 5. 沿一次真实读取，看清计划如何推进 {#hands-on}

下载并解压独立工程，先取一次 ADK-Rust 源码再运行：

```sh
cd todo-planning
python3 fetch-adk-rust.py ../adk-rust    # 需要 git 与 GitHub 访问；不行时加 --method cdn
cargo run --locked                      # 24 个场景的摘要
cargo run --locked -- normal            # 正常流程的完整轨迹
cargo run --locked -- claims-only
cargo test --locked
```

编译时会看到 adk-core 的 3 条弃用警告（上游固定 Rust 1.95.0），不影响运行和检查。先猜三件事：只把清单改完，验收会通过吗？读取第三轮结束时耗尽预算，清单会自动补完吗？新建会话会继承上一份计划吗？

`PlanLlm` 按请求次数推进：建单、开始读取、调用文件工具、推进整理、推进核对、完成核对，最后生成回答。它从请求里的清单构造候选列表，回答则从历史里的文件读取结果取内容。这能稳定检验接线和状态规则；它没有测量真实模型会不会主动列计划、何时决定更新。

![七次模型请求里看到的清单版本依次为 0、1、2、2、3、4、5，读取文件不会自动更新清单。](/learn-agent-rust/figures/r05-plan-snapshots.svg)

逐行看三个条目：第一次请求时尚未建单；第二次看见版本 1 的三个待开始步骤。第三次请求时模型读取文件，第四次请求看到的版本仍为 2，因为文件工具只返回内容、不改清单。第四次提交“读取完成、整理进行中”，整批通过后，第五次请求才看见版本 3。完整轨迹：

<<< @/public/learn-agent-rust/outputs/r05-normal.txt

本任务的独立验收很窄：成功调用文件读取一次，且最终答案等于“启动说明”加读取到的 README 全文。它检验回答确实经过工具结果，而不是评估开放式摘要质量。测试会把 README 换成 `启动命令：just dev`，核对回答随文件变化。

## 动手实验：先预测，再核对

以下是全部 24 个场景的实际摘要：

<<< @/public/learn-agent-rust/outputs/r05-summary.txt

### 对照一：清单全完成，但没有读文件

`claims-only` 只将正常流程的第三次请求从 `read_file` 换成 `todo_read`，其余建单和状态更新相同。因此，两次运行都是 7 次模型请求、清单版本 5，三个步骤都标成完成。

区别在文件证据：正常流程成功读取 1 次，并生成基于文件内容的回答；对照读取 0 次，最终明确返回“缺少 README 读取证据”，`goal_verified=false`。<a href="/learn-agent-rust/outputs/r05-claims-only.txt" download>下载 claims-only 完整轨迹</a>。

**迁移校验只能证明状态变化符合规则，无法证明步骤内容已经执行。** 真实应用应按任务类型建立验收条件，例如修改后运行相应测试、生成报告后核对交付物。不能把模型自己填写的 `completed` 作为唯一依据。

### 对照二：文件错误与预算耗尽

| 场景 | 真实读取次数 | 清单版本 | 当前步骤 | 停止原因 |
| --- | --- | --- | --- | --- |
| `read-error` | 0 | 2 | 读取 README：进行中 | 模型看到 `file.missing` 后如实回答“任务未完成” |
| `budget-stop` | 1 | 2 | 读取 README：进行中 | `max_iterations(3)` 用完，运行以错误结束（错误码 `agent.legacy`） |

`read-error` 的临时工作区没有创建 README。读取失败的结果交回模型，模型不再推进，回答“任务未完成：file.missing”；原清单保留。和旧版不同，框架不会因为一次工具失败就停止运行，停不停由模型（以及第 1 章讲过的预算）决定。

`budget-stop` 给 LlmAgent 设了 `max_iterations(3)`：文件读取已经成功，但还没轮到模型提交完成状态或生成答案。`agent.legacy` 是框架很多 Agent 错误共用的笼统代码，能说明原因的是错误消息里的“Max iterations (3) exceeded”；第 1 章的 `loop-limit` 场景有同样的结果。停止时应同时展示原因、当前计划和已有证据；清单这时仍在会话状态里，版本 2。

### 对照三：非法输入整批拒绝，合理变更保留记录

`two-active`、`skip-completion`、`duplicate-id` 等场景各自先在会话状态里放好一份合法清单（创建会话时给出初始状态），再让脚本模型提交一次候选。摘要中的 `unchanged=true` 比较了运行前后会话状态里的整个清单，包括目标、版本和全部条目。

`append-step` 在三个原步骤后新增“补查环境要求”，原条目保留，新项从 `pending` 开始；`yield-step` 把正在读取的步骤退回 `pending`，同时把整理步骤切到 `in_progress`。两次整批更新均成功，说明重新规划也可以走同一个接口。

本章选择保留历史、内容不可改，所以暂时无法表达“取消一项已不需要的工作”。需要这种能力时应显式增加 `cancelled` 及原因、迁移规则和测试；不要用虚假的完成状态隐藏被取消的工作。

`permission-denied` 的清单里已经有“写入 summary.txt”待办，脚本模型再请求 `write_file`。应用策略拒绝，结果是 `refused`，工具没有执行，目录里没有产生摘要文件，清单不变。

### 对照四：同一会话的下一次运行与新会话

| 场景 | 观察 | 说明 |
| --- | --- | --- |
| `next-run` | 同一会话再运行一次，第一次请求就看到版本 5 | 会话状态随会话保存，跨运行可见。 |
| `fresh-session` | 新会话 `s2` 没有清单 | 状态属于会话，不是全局列表。 |

旧版的清单活在 `Runtime` 对象里，新建一个对象就从零开始；新版的清单属于会话，同一会话的下一次运行还在。键名前缀决定作用范围：不带前缀的键属于这个会话，`user:` 开头的键由同一用户的所有会话共享，`app:` 开头的由整个应用共享，`temp:` 开头的只在本次运行里可见、不保存。本章用内存会话服务，进程退出后一切都没有了；换成 SQLite 或 PostgreSQL 会话服务，清单就随会话持久保存，但那时还要考虑多个进程同时写同一会话、恢复时清单与事件的一致性等问题。

| 本章会话内清单 | 后续持久化任务系统需要补充 |
| --- | --- |
| 目标、条目、状态、清单版本 | 持久化的任务身份、依赖与查询。 |
| 当前模型请求中的关注点 | 执行者领取、租约与接管。 |
| 单个会话内的整批校验 | 跨会话、跨进程的并发冲突处理。 |

因此，清单适合把当前工作说清楚。[第 25 章的持久化任务系统](./task-system.md)再处理退出、领取和依赖等生命周期问题。

### 与旧版场景的对应 {#old-scenarios}

| 旧版（标准库 Runtime） | 新版（ADK-Rust） | 变化 |
| --- | --- | --- |
| `Plan` 在 `Runtime` 结构体里 | `plan` 在会话状态里，经 `state_delta` 写入 | 同一会话跨运行可见。 |
| `model_input()` 每轮复制清单 | before_model 回调每次请求前插入清单 | 新增 `template-only`：instruction 模板一次运行只渲染一次。 |
| 自写派发器 + 固定只读策略 | Runner + `DeclarativePolicy` | `permission-denied` 的结果从自定义码变为框架的 `refused`。 |
| `read-error`：`tool_error` 立即停止 | 模型看到错误后回答未完成 | 工具失败不再自动停止运行。 |
| `budget-stop`：`turn_limit` | `max_iterations(3)`，`agent.legacy` | 预算由框架执行。 |
| `fresh-session`：新 `Runtime` | 新会话；另加 `next-run` | 区分“新会话”与“同一会话的下一次运行”。 |
| `invalid-json`（参数不是合法 JSON） | `wrong-type`（版本号是字符串） | 模型给的参数在进入工具前已经是 JSON 值，坏 JSON 由模型接口层处理。 |
| 其余 13 个校验场景 | 同名场景 | 错误码加上 `todo.` 前缀；经过真实 Runner 执行。 |
| （无） | `same-batch-naive`、`same-batch` | 一次回复里两个写入：同一批的事件晚于执行才产出。 |
| 6 项测试 | 8 项测试 | 新增“每次请求看到最新清单”“模板一次运行只渲染一次”“同一批的第二次写入看得到第一次”。 |

### 实验怎样复核

网站仓库中的验收命令会先生成下载 zip，再解压到临时目录，在旁边放好 ADK-Rust 源码，运行格式检查、Clippy、8 项 Rust 测试和离线构建；摘要与三条详细轨迹各连跑两次必须逐字节相同：

```sh
python3 scripts/verify-learn-agent-rust-r05.py
python3 scripts/verify-learn-agent-rust-r05.py --check
python3 scripts/generate-learn-agent-rust-figures.py --lesson R05
```

证据汇总保存在仓库的 `scripts/data/learn-agent-rust/r05-results.json`，自制图从这份记录读取数据，并校验源码摘要。

## 与参考课程和 harness 对照

![参考课程的原图展示 todo_write 将计划状态放回工具循环。](/learn-agent-rust/figures/upstream/r05-todo-overview.svg)

这张原图原样保留自 [TodoWrite 参考章节](https://learn.shareai.run/zh/s05/)，图源为[课程原图](https://learn.shareai.run/course-assets/s05_todo_write/todo-overview.svg)。图中的 Python/Claude 接口、工具数量和编号属于参考实现。参考实现还演示了连续若干轮未更新时注入提醒的策略，本章没有实现提醒计数器。原图许可与来源版本见[参考资料说明](./architecture.md#reference-assets)。

ADK-Rust 的 `adk-harness`（Beta 层）自带 `write_todos` / `update_todo` 两个工具，清单同样存在会话状态（键 `harness:todos`）。和本章的自写工具比，它的取舍不同：`write_todos` 不检查状态迁移和版本，每次写入版本直接加一，有 `cancelled` 状态，上限是 50 项、每项 500 字符；同一批里多个调用的问题，它用同样的办法处理：按运行记下刚写的清单，后面的调用读它。本章没有运行 harness，计划中的第十一部分再展开。

::: warning 常见误区
- **把状态当成执行凭证。** 清单展示自报进度，任务完成还需要检查结果与交付物。
- **把版本号当成轮次。** 只有接受清单更新才增加版本，文件读取和模型请求另行计数。
- **以为 instruction 模板每轮都会刷新。** `{键}` 模板只在每次运行开始时渲染；同一次运行里要看到工具刚写的状态，需要在 before_model 回调里读取。
- **直接改状态。** 状态通过事件上的 `state_delta` 合并；工具里只改 `ctx.actions()`，不要另找途径写会话。
- **在清单里写下动作，就认为获得权限。** 实际文件操作仍经过应用策略判断。
- **把内存会话当成持久化。** 同一进程里同一会话的下一次运行能看到清单，进程退出后就没有了。
:::

<!-- transfer-thinking:start -->

## 迁移思考：计划不是完成证据

把所有待办标成 completed，报告一定存在吗？先给出你的判断，再展开下面的推演。

<details><summary>推演与应用</summary>

对照计划状态与真实文件。状态迁移合法只证明清单一致，仍需独立产物验收。

把“记录工作”和“接受交付”交给不同契约，可减少自报进度造成的误判。

</details>

这是一道迁移练习，推演不代表新增实验已通过。对照[全书审查中的证据层次](./course-review.md#evidence-layers)，说明你的判断还需要哪一级证据。

<!-- transfer-thinking:end -->

## 框架替你做了什么、没做什么

| 框架做了 | 仍归应用 |
| --- | --- |
| 会话状态随会话保存；事件上的 `state_delta` 在事件产出时合并进状态。 | 决定清单存在哪个键、什么格式；整批校验与版本检查（本章自写）；同一批多个写入时自己记住刚写的值。 |
| before_model 回调每次请求前运行，能读到会话的当前状态。 | 把最新清单放进请求；instruction 模板只在运行开始时渲染一次。 |
| 工具调用经过应用策略；被拒绝的工具不执行。 | 写策略：清单里的待办不赋予任何权限。 |
| `max_iterations` 限制模型请求次数，到达上限时以错误结束运行。 | 停止时展示原因、当前计划和已有证据；独立验收任务结果。 |

<!-- adk-refs:start -->

## 在 ADK-Rust 源码里

本章的会话状态、清单可见性与运行上限，在 ADK-Rust 里分布在这几处：

| 本章内容 | 源码位置 | 对照要点 |
| --- | --- | --- |
| 事件上的状态变更 | [`adk-core/src/event.rs` · `EventActions`](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-core/src/event.rs#L75-L135) | `state_delta` 随事件一起保存；工具通过 `ctx.actions()` / `ctx.set_actions()` 修改自己这次调用的动作 |
| 追加事件时合并状态 | [`adk-session/src/inmemory.rs` 第 101 行](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-session/src/inmemory.rs#L101) | `temp:` 开头的键丢弃；`app:` / `user:` 开头的写到应用级、用户级状态；其余写进这个会话 |
| 工具读会话 | [`adk-core/src/tool.rs` 第 519 行](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-core/src/tool.rs#L519) | `todo_write` 从这里读出当前清单；默认返回 `None`，Runner 提供的工具上下文会给出会话 |
| instruction 模板 | [`adk-core/src/instruction_template.rs` · `inject_session_state`](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-core/src/instruction_template.rs#L207-L227) | `{键}` 按会话状态替换，`{键?}` 缺失时留空 |
| 模板在哪里渲染 | [`adk-agent/src/llm_agent.rs` 第 4097 行](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-agent/src/llm_agent.rs#L4097) | 每次运行开始时调用一次，之后的循环不再重新渲染（`template-only` 场景） |
| 每次请求前的回调 | [`adk-agent/src/llm_agent.rs` 第 4632 行](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-agent/src/llm_agent.rs#L4632) | 在循环里、每次请求模型之前运行，可以修改请求；本章在这里插入最新清单 |
| harness 的清单工具 | [`adk-harness/src/tools/todos.rs` · `WriteTodosTool`](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-harness/src/tools/todos.rs#L228-L230) | Beta 层：整份替换、版本每次加一，不检查状态迁移和版本；清单存在 `harness:todos` |

源码固定在 ADK-Rust `98515241133d`（3.0.0，2026-11-26，尚未发布到 crates.io）。本节由 `scripts/learn-agent-rust-adk-refs.py` 生成。

<!-- adk-refs:end -->

## 本章结论：把计划变成可检查的会话状态

本章把目标和清单放进会话状态，用 `todo_write` 提交完整候选快照，经过版本、身份和迁移检查后再经 `state_delta` 一次写回；before_model 回调让每次模型请求都带上最新清单。instruction 模板只在运行开始时渲染一次，这一点由 `template-only` 场景实测，版本检查挡住了模型过期视图带来的覆盖；同一批里的多个写入还要工具自己记住刚写的值，否则版本检查会被绕过（`same-batch-naive`）。

这个机制让计划变化可以观察、拒绝和复核。实验也把验收边界固定下来：清单全完成、运行已停止、用户目标已满足，需要分别判断。

## 检查理解

1. 版本 2 的清单里，“读取 README”正在进行。文件工具成功返回后，清单自动变成版本 3 吗？

   <details><summary>参考答案</summary>

   不会。文件工具只返回内容，它的事件上没有 `state_delta`。随后模型提出合法的 `todo_write`，把读取改成完成并提交版本 2 的候选快照，工具校验通过、写入 `state_delta` 后才进入版本 3。

   </details>

2. 一个候选列表第一项合法、最后一项为空，为什么最终状态应完全不变？

   <details><summary>参考答案</summary>

   校验阶段只检查候选列表，尚未替换当前清单。函数最后才替换条目、递增版本；前面返回错误时，工具也不会写 `state_delta`，会话状态里的原条目和原版本全部保留。

   </details>

3. 把清单写进 instruction 的 `{plan?}` 模板，为什么 `template-only` 的第二次 `todo_write` 被拒绝？

   <details><summary>参考答案</summary>

   模板只在这次运行开始时渲染一次，那时还没有清单。第一次 `todo_write` 已经把版本推进到 1，但后面的请求里模型看到的仍是“未建单、版本 0”，于是按版本 0 再次提交，版本检查返回 `todo.revision_conflict`。要每次请求都看到最新状态，需要在 before_model 回调里读取会话状态。

   </details>

4. `claims-only` 已经过合法的状态迁移，为什么 `goal_verified` 仍为 `false`？

   <details><summary>参考答案</summary>

   状态规则检查的是提交内容是否符合应用约定。这个对照没有读取 README，历史里没有文件证据，也没有据此产生启动说明。任务验收独立检查工具执行与最终答案。

   </details>

5. 清单已经在会话状态里了，为什么仍需单独设计持久化任务？

   <details><summary>参考答案</summary>

   会话状态提供了数据位置，换成持久的会话服务后也能跨进程保存。但任务领取、依赖、租约与接管需要各自的协议，多个执行者同时写同一份清单也要并发控制；会话状态只是一组键值对。本实验只验证单进程、单会话内的清单机制。

   </details>

## 参考资料

- [Serde：容器属性](https://serde.rs/container-attrs.html)，`rename_all` 和 `deny_unknown_fields` 的语义。
- [Learn Claude Code：TodoWrite](https://learn.shareai.run/zh/s05/)，计划可见性与提醒机制的参考实现。
- [ADK-Rust 固定源码](https://github.com/zavora-ai/adk-rust/tree/98515241133d24f7e41f8fd272649035416a142f)：本课程真实运行的接口与语义基线。
- [本章独立工程](/learn-agent-rust/todo-planning.zip)与[正常流程完整轨迹](/learn-agent-rust/outputs/r05-normal.txt)。

下一章进入[子 Agent 与上下文隔离](./subagents.md)：当一个步骤需要独立处理时，怎样给它一份单独的目标与消息历史，再把结果带回当前任务。
