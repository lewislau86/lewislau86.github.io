---
title: "第 5 章：可见的任务清单"
description: "用 Rust 实现会话内待办、整批校验和版本检查，让计划变化可见，并用执行证据核对任务结果。"
pageClass: learn-agent-rust-course
---

# 第 5 章：可见的任务清单

[课程总览](./index.md) · [上一章：生命周期与 Hooks](./hooks.md) · [下一章：子 Agent 与上下文隔离](./subagents.md)

::: tip 本章学习目标
- 把目标拆成带 ID 和状态的步骤，让每轮模型输入都能看到最新清单。
- 校验状态迁移、版本和整批更新，拒绝会破坏现有记录的候选清单。
- 用真实读取与失败对照，区分清单完成、循环停止和任务验收。

**前置：** [第 2 章 · 工具注册与图调度](./tools-and-graph.md)、[第 3 章 · 工具权限与审批](./permissions.md)；理解 Rust 的枚举、`Result`、可变借用和 JSON。第 4 章的 Hook 机制可结合阅读，本实验可独立运行。

**实践方式：** 下载[本章独立工程](/learn-agent-rust/todo-planning.zip)，使用固定的 Rust 1.99.1 工具链。首次构建需要下载 Cargo 依赖；运行实验无需模型密钥和数据库。
:::

沿用前面的工作区助手。这次用户说：“读取 README，整理启动说明。”助手准备先读文件，再整理说明，最后核对原文。一次文件读取很短，但这个例子能把长任务中容易混在一起的三件事拆开：原来的目标是什么，现在推进哪一步，还有什么没有完成。

假设工具已经读到了 README，助手的清单却仍显示“读取 README：进行中”。程序应该自动把它改成完成吗？再换一种情况：助手把三项都标成完成，却一次也没读文件。用户应该接受这个结果吗？本章用同一份可运行代码检查这两种情况。

<LearnAgentRustMap active="todo-planning" />

<!-- experiment-library:start -->

全书实验可从[统一代码库](./experiments.md#todo-planning)下载；解压后进入 `chapters/todo-planning/`，或在代码库根目录运行 `python3 run.py run R05`。

<!-- experiment-library:end -->

## 1. 先把步骤从对话里拿出来

只有消息历史时，计划可能夹在用户请求、模型回答和工具结果之间。我们给会话增加一份明确的 `Plan`，由运行时保存；模型通过 `todo_read` 查看，通过 `todo_write` 提交新快照。

| 条目 ID | 内容 | 建单时状态 |
| --- | --- | --- |
| `read` | 读取 README | `pending` |
| `summarize` | 整理启动说明 | `pending` |
| `check` | 核对说明与原文 | `pending` |

条目 ID 用来判断“这还是原来的步骤吗”；内容给模型和读者看；状态说明推进位置。`goal` 保存用户目标，只有应用创建清单时设置，清单更新接口没有修改它的参数。

::: info 源码与实验范围
本文 Rust 片段均引用 <a href="/learn-agent-rust/code/todo-planning/src/main.rs" download>完整 main.rs</a>，也可在 [GitHub 查看工程](https://github.com/lewislau86/lewislau86.github.io/tree/master/docs/public/learn-agent-rust/code/todo-planning)。[下载包](/learn-agent-rust/todo-planning.zip)包含源码、锁文件、工具链配置和运行说明。

实验使用固定脚本模型产生工具调用，清单工具接收真实 JSON 参数；文件工具通过 `std::fs` 读取实际的临时 README。它验证单进程、内存内的清单机制。本章没有新增 `langchain-rust` / `graph-flow` 集成测试；两库接线以第 2 章实验为准。
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

这套规则属于教学应用的选择。其他产品可以允许多个进行中、撤销完成或跳过步骤，但必须明确相应语义。这里限制一个进行中，是为了显示“当前关注点”，并没有实现线程锁、任务领取或并行调度。

除了迁移，我们还固定以下输入约束：

| 检查 | 本章规则 | 解决的问题 |
| --- | --- | --- |
| 列表大小 | 1–8 项 | 保持练习清单有界。 |
| ID | 1–24 个小写 ASCII 字母、数字或连字符，且不重复 | 稳定识别条目。 |
| 内容 | 去掉首尾空白后非空，原始内容最多 120 个 Unicode 字符 | 避免空任务和过长说明。 |
| 已有条目 | 保留 ID 和原内容，允许调整顺序 | 避免把旧步骤悄悄改成另一件事。 |
| 新增条目 | 初始状态必须是 `pending` | 让新增工作先进入计划。 |
| 版本 | 与运行时当前版本一致 | 拒绝根据旧快照提交的替换。 |

8、24、120 都是本章选定的应用上限，不是性能测试得到的最佳值。这里用 `chars().count()` 计内容长度；ID 只接受 ASCII，因此字节长度与字符数一致。

## 3. 整份先检查，再一次替换

假设候选快照的第一项合法地变成进行中，第三项却是空内容。如果边遍历边修改运行时，发现第三项错误时，第一项可能已经变了。调用者收到“更新失败”，实际状态却只改了一半。

我们的做法是：先检查 `args.items`，直到所有规则都通过，才替换 `self.items`。

<<< @/public/learn-agent-rust/code/todo-planning/src/main.rs#validate

注意函数末尾的两行。它们是唯一的提交位置；前面任何 `return Err(...)` 都会留下原清单和原版本。Rust 的 `&mut self` 让这次同步调用独占访问当前 `Plan`；这里说的整批更新只覆盖这个内存对象，没有数据库事务或跨进程并发控制。

`expected_revision` 解决另一种问题：模型看到版本 1，其他动作已经把清单推进到版本 2，这时模型仍提交“基于版本 1”的候选列表。函数首先返回 `revision_conflict`，调用者应读取最新状态，再重新组织更新。

即使同一候选列表连续提交，接受第一次后版本也会改变，第二次携带旧版本就会冲突。本章没有把更新设计成幂等重放接口；需要重放与存储时，要额外设计请求身份和提交语义。

## 4. 更新以后，下一轮怎样看见

把清单打印到终端，只能让人看见。要让模型继续利用它，运行时还要在每次模型调用前构造包含最新状态的输入。

<<< @/public/learn-agent-rust/code/todo-planning/src/main.rs#messages

`Runtime` 拥有当前清单、消息历史和成功文件读取计数。`model_input()` 每轮从它复制一份输入快照；快照用于观察，后续更新仍然作用于运行时保存的 `Plan`。每次派发都记录模型调用及其对应的工具结果，结果沿用原 `call_id`。

![运行时每轮提供最新计划与历史，工具返回结果；清单完成和实际任务验收分别判断。](/learn-agent-rust/figures/r05-visible-loop.svg)

沿上半图的回路看：请求进入派发器，结果写回历史，然后构造下一轮输入。下方是两次实际运行的对照，说明“模型声称完成”仍需执行证据支持。

本实验的派发器把清单和文件工具放在同一个入口：

<<< @/public/learn-agent-rust/code/todo-planning/src/main.rs#dispatch

`todo_write` 先解析 JSON，再调用刚才的整批校验。成功结果带回已接受的清单；失败结果包含稳定的错误码。`todo_read` 接收空对象，返回当前清单。`read_file` 只允许精确路径 `README.md`，通过后才读取文件；其他路径和所有 `write_file` 请求都被拒绝。

因此，计划里出现“写入 summary.txt”只表示有这样一项待办。是否允许写入，仍要经过执行器的权限策略。在[第 3 章](./permissions.md)中，需要批准的动作会保存审批快照；本章为聚焦清单，直接采用固定只读策略。

要接回第 2 章的图，接线位置也明确：在应用的 `State` 中增加 `Plan`，`ModelTurn` 组装输入时读取最新计划，`ExecuteTools` 的注册表派发 `todo_read` 与 `todo_write`，然后保存更新后的状态。清单条目属于应用数据，不需要为每个条目建立一个图节点。这是接入方向，本章发布包验证的是上面的独立运行时。

## 5. 沿一次真实读取，看清计划如何推进

为了复现每个分支，脚本模型按轮次产生固定请求：建单、开始读取、调用文件工具、推进整理、推进核对、完成核对，最后生成回答。它通过本轮输入中的清单建立候选列表，回答则从历史里的文件读取结果取内容。

这一选择能稳定检验接线和状态规则。它没有测量真实模型会不会主动列计划、何时决定更新，或是否更擅长完成长任务。

![七轮模型输入中的清单版本依次为 0、1、2、2、3、4、5，读取文件不会自动更新清单。](/learn-agent-rust/figures/r05-plan-snapshots.svg)

逐行看三个条目：第一轮输入尚未建单；第二轮看见版本 1 的三个待开始步骤。第三轮读取文件后，第四轮输入的版本仍为 2，因为文件工具只返回内容。第四轮提交“读取完成、整理进行中”，整批通过后，下一轮才看见版本 3。

真正驱动循环的是下面这段代码：

<<< @/public/learn-agent-rust/code/todo-planning/src/main.rs#loop

`inputs` 保留每轮调用前的快照。`stop` 记录为什么停下：得到回答、工具错误或轮次耗尽。最后分别计算 `all_completed` 与 `goal_verified`。

本任务的独立验收很窄：成功调用文件读取一次，且最终答案等于“启动说明”加读取到的 README 全文。它用于检验回答确实经过工具结果，而不是评估开放式摘要质量。测试会把 README 换成 `启动命令：just dev`，核对回答随文件变化。

## 动手实验：先预测，再核对

解压下载包，进入 `todo-planning` 目录：

```sh
cargo run --locked
cargo run --locked -- --json normal
cargo run --locked -- --json claims-only
cargo test --locked
```

默认命令运行全部场景并执行断言。`--json normal` 会展开最终计划、逐轮输入和完整调用历史。先猜三件事：只把清单改完，验收会通过吗？读取第三轮结束时耗尽预算，清单会自动补完吗？新建会话会继承上一份计划吗？

以下是 Rust 1.99.1 下实际运行的完整摘要，直接从生成文件导入：

<<< @/public/learn-agent-rust/outputs/r05-summary.txt

### 对照一：清单全完成，但没有读文件

`claims-only` 只将正常流程的第三轮 `read_file` 换成 `todo_read`，其余建单和状态更新相同。因此，两次运行都是 7 轮输入、6 次工具调用、清单版本 5，三个步骤都标成完成。

区别在文件证据：正常流程成功读取 1 次，并生成基于文件内容的回答；对照读取 0 次，最终明确返回“缺少 README 读取证据”，`goal_verified=false`。

**迁移校验只能证明状态变化符合规则，无法证明步骤内容已经执行。** 真实应用应按任务类型建立验收条件，例如修改后运行相应测试、生成报告后核对交付物。不能把模型自己填写的 `completed` 作为唯一依据。

### 对照二：文件错误与预算耗尽

| 场景 | 真实读取次数 | 清单版本 | 当前步骤 | 停止原因 |
| --- | --- | --- | --- | --- |
| `read-error` | 0 | 2 | 读取 README：进行中 | `tool_error` |
| `budget-stop` | 1 | 2 | 读取 README：进行中 | `turn_limit` |

`read-error` 的临时工作区没有创建 README。读取返回 `read_error`，练习循环立即停止；错误仍进入调用历史，原清单保留。这个停止策略属于本章驱动器，后续可以基于[错误分类与恢复](./error-recovery.md)决定如何继续。

`budget-stop` 允许三轮，所以文件读取已经成功，但还没轮到模型提交完成状态或生成答案。它说明停止时应同时展示原因、当前计划和已有证据；运行时可以保存这份快照供当前进程里的调用者查看。本实验结束后就会丢弃它。

### 对照三：非法输入整批拒绝，合理变更保留记录

`two-active`、`skip-completion`、`duplicate-id` 等场景各自从一份合法清单开始，只改变待测条件。摘要中的 `unchanged=true` 比较了整个 `Plan`，包括目标、版本和全部条目。

`append-step` 在三个原步骤后新增“补查环境要求”，原条目保留，新项从 `pending` 开始；`yield-step` 把正在读取的步骤退回 `pending`，同时把整理步骤切到 `in_progress`。两次整批更新均成功，说明重新规划也可以走同一个接口。

本章选择保留历史、内容不可改，所以暂时无法表达“取消一项已不需要的工作”。需要这种能力时应显式增加 `cancelled` 及原因、迁移规则和测试；不要用虚假的完成状态隐藏被取消的工作。

`permission-denied` 则先成功加入“写入 summary.txt”待办，再提交写文件请求。返回仍为 `permission_denied`，清单不变，目录里没有产生摘要文件。

### 对照四：新的会话从零开始

`fresh-session` 先完成一份版本 5 的计划，再创建新的 `Runtime`。新实例的版本为 0，条目为空。这份清单的生命周期属于当前运行时实例；没有共享全局列表、数据库或进程退出后的恢复。

| 本章会话内清单 | 后续持久化任务系统需要补充 |
| --- | --- |
| 目标、条目、状态、清单版本 | 持久化的任务身份、依赖与查询。 |
| 当前模型输入中的关注点 | 执行者领取、租约与接管。 |
| 当前进程内的整批校验 | 存储提交、重启恢复与并发冲突处理。 |

因此，清单适合把当前工作说清楚。[第 12 章的持久化任务系统](./task-system.md)再处理退出、领取和依赖等生命周期问题。

### 实验怎样复核

六个 Rust 测试覆盖三种状态的完整迁移矩阵、候选列表后段失败时的整批拒绝、全部场景断言、每轮输入和调用 ID 配对、更换 README 后的回答，以及输入长度和格式边界。

网站仓库中的验收命令会**先生成下载 zip，再解压到临时目录**，在解压出的工程里运行格式检查、Rust 测试、Clippy 和全部场景，随后保存输出、源码 SHA-256 与下载包校验值：

```sh
python3 scripts/verify-learn-agent-rust-r05.py
python3 scripts/verify-learn-agent-rust-r05.py --check
python3 scripts/generate-learn-agent-rust-figures.py --lesson R05
```

`--check` 重新执行并逐字节检查产物是否过期；CI 也运行同一检查。可下载[正常流程完整记录](/learn-agent-rust/outputs/r05-normal.json)、[仅改标记的对照](/learn-agent-rust/outputs/r05-claims-only.json)与[实际输出摘要](/learn-agent-rust/outputs/r05-summary.txt)。证据汇总保存在仓库的 `scripts/data/learn-agent-rust/r05-results.json`，自制图从这份记录读取数据，并校验源码摘要。

## 与参考课程对照

![参考课程的原图展示 todo_write 将计划状态放回工具循环。](/learn-agent-rust/figures/upstream/r05-todo-overview.svg)

这张原图原样保留自 [TodoWrite 参考章节](https://learn.shareai.run/zh/s05/)，图源为[课程原图](https://learn.shareai.run/course-assets/s05_todo_write/todo-overview.svg)。沿计划与循环之间的连接阅读即可；图中的 Python/Claude 接口、工具数量和编号属于参考实现。

参考实现通过 `todo_write` 保存并显示清单，还演示了连续若干轮未更新时注入提醒的策略。本章改用每轮提供最新清单的方式，并增加整批校验与版本检查，尚未实现提醒计数器。两者都是让计划保持可见的教学设计，不能据此推断某个商业 Agent 的内部实现。原图许可与来源版本见[参考资料说明](./architecture.md#reference-assets)。

::: warning 常见误区
- **把状态当成执行凭证。** 清单展示自报进度，任务完成还需要检查结果与交付物。
- **把版本号当成轮次。** 只有接受清单更新才增加版本，文件读取和模型调用另行计数。
- **在清单里写下动作，就认为获得权限。** 实际文件操作仍经过独立策略判断。
- **用一个进行中条目代替并发控制。** 这里没有执行者、锁或租约，也没有跨进程协调。
- **把新实例误当成恢复。** 当前计划在运行时内存中；下载包验证了独立运行，没有验证重启续跑。
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

## 本章结论：把计划变成可检查的会话状态

本章选择由运行时保存目标和清单，用 `todo_write` 提交完整候选快照，经过版本、身份和迁移检查后再一次替换。每轮模型输入读取最新状态，工具结果继续沿调用 ID 回到历史。

这个机制让计划变化可以观察、拒绝和复核。实验也把验收边界固定下来：清单全完成、循环已停止、用户目标已满足，需要分别判断。

## 检查理解

1. 版本 2 的清单里，“读取 README”正在进行。文件工具成功返回后，清单自动变成版本 3 吗？

   <details><summary>参考答案</summary>

   不会。文件工具只写回执行结果。随后模型提出合法的 `todo_write`，把读取改成完成并提交版本 2 的候选快照，运行时接受后才进入版本 3。

   </details>

2. 一个候选列表第一项合法、最后一项为空，为什么最终状态应完全不变？

   <details><summary>参考答案</summary>

   校验阶段只检查候选列表，尚未替换当前清单。函数最后才执行 `self.items = args.items` 和版本递增；前面返回错误时，原条目和原版本全部保留。

   </details>

3. `claims-only` 已经过合法的状态迁移，为什么 `goal_verified` 仍为 `false`？

   <details><summary>参考答案</summary>

   状态规则检查的是提交内容是否符合应用约定。这个对照没有读取 README，历史里没有文件证据，也没有据此产生启动说明。任务验收独立检查工具执行与最终答案。

   </details>

4. 完成一项工作后发现还需要补查环境，应重开完成项，还是新增步骤？如果旧步骤已不需要呢？

   <details><summary>参考答案</summary>

   按本章规则，已完成条目保留，新增一项 `pending` 的补查步骤。若旧步骤需要取消，现有三态模型无法准确表示；应扩展取消状态及原因，而不是把未做的步骤标成完成。

   </details>

5. 为什么把清单加进 `graph-flow` 的状态后，仍需单独设计持久化任务？

   <details><summary>参考答案</summary>

   图状态提供运行时的数据位置，但恢复还取决于是否保存、何时提交以及如何加载。任务领取、依赖、租约与接管也需要各自的协议。本实验只验证当前实例内的清单机制。

   </details>

## 参考资料

- [Serde：容器属性](https://serde.rs/container-attrs.html)，`rename_all` 和 `deny_unknown_fields` 的语义。
- [Rust：std::fs::read_to_string](https://doc.rust-lang.org/std/fs/fn.read_to_string.html)，实验实际文件读取入口与错误条件。
- [Learn Claude Code：TodoWrite](https://learn.shareai.run/zh/s05/)，计划可见性与提醒机制的参考实现。
- [本章独立工程](/learn-agent-rust/todo-planning.zip)与[完整运行记录](/learn-agent-rust/outputs/r05-normal.json)。

下一章进入[子 Agent 与上下文隔离](./subagents.md)：当一个步骤需要独立处理时，怎样给它一份单独的目标与消息历史，再把结果带回当前任务。
