---
title: "第 9 章：子 Agent 与上下文隔离"
description: "用 ADK-Rust 3.0 的 AgentTool 把子 Agent 当成工具：新会话、父模型只收到最终回答；对照 transfer_to_agent 交接控制权，并验证共享预算、执行权限与取消。"
pageClass: learn-agent-rust-course
prev:
  text: 第 8 章 · 可见的任务清单
  link: /learn-agent-rust/todo-planning
next:
  text: 第 10 章 · 按需加载技能
  link: /learn-agent-rust/skill-loading
---

# 第 9 章：子 Agent 与上下文隔离

[课程总览](./index.md) · [上一章：可见的任务清单](./todo-planning.md) · [学习路径](./learning-path.md) · [下一章：按需加载技能](./skill-loading.md)

::: tip 本章学习目标
- 为一次子任务建立独立的会话，解释父 Agent 交出什么、收回什么。
- 区分“把子 Agent 当工具调用”和“把控制权交给子 Agent”。
- 核对父子共用的预算、子 Agent 的工具边界，以及取消请求在委派中途的结果。

**前置：** [第 2 章：工具注册与图调度](./tools-and-graph.md)中的消息与工具边界，以及[第 3 章：工具权限与审批](./permissions.md)中的执行前策略；[第 1 章](./agent-loop.md)的运行预算。

**实践方式：** 下载[本章独立工程](/learn-agent-rust/subagents.zip)，按[第 1 节](#hands-on)取一次 ADK-Rust 源码后运行；无需模型密钥或数据库。
:::

::: info 本章已迁移到 ADK-Rust 3.0
本章实验基于 ADK-Rust 3.0 发布候选版（固定提交，尚未发布到 crates.io）。旧版本章只用标准库，在一个线程里手写子循环、共享总账和取消握手，可从 git 标签 `learn-agent-rust-v1` 取得。新版的子会话、结果回传、共享预算和取消传递都由框架提供；任务与回传的长度契约仍由宿主自己写。[对应表](#old-scenarios)列出了场景的变化。
:::

给助手一个任务：“读取 README，告诉我项目启动命令。”父 Agent 可以自己完成，也可以把“从 README 提取启动命令”交给一个子 Agent。

先想一想：如果把父会话的全部消息复制给子 Agent，等它结束后又把全部过程粘回来，父会话会更短吗？我们希望父会话保留任务主线，而文件读取的中间过程留在子会话里。因此，本章关心的是：**明确传入子任务，建立新的历史，只把约定的结果送回父模型。**

<LearnAgentRustMap active="subagents" />

<!-- experiment-library:start -->

全书实验可从[统一代码库](./experiments.md#subagents)下载；解压后进入 `chapters/subagents/`，或在代码库根目录运行 `python3 run.py run R06`。

<!-- experiment-library:end -->

::: info 代码与输出只有一个来源
本文 Rust 片段直接导入<a href="/learn-agent-rust/code/subagents/src/main.rs" download>完整 main.rs</a>。Runner、LlmAgent、AgentTool、transfer_to_agent、运行预算和取消都是 ADK-Rust 的真实实现；父子模型都是按规则回复的 `RuleLlm`，各自只看得到自己的请求；文件工具真实读取临时目录。
:::

## 1. 先运行：父模型最后看到了什么？ {#hands-on}

下载并解压独立工程，先取一次 ADK-Rust 源码再运行：

```sh
cd subagents
python3 fetch-adk-rust.py ../adk-rust    # 需要 git 与 GitHub 访问；不行时加 --method cdn
cargo run --locked -- normal
```

编译时会看到 adk-core 的 3 条弃用警告（上游固定 Rust 1.95.0），不影响运行和检查。每次运行都会创建自己的临时工作区，里面有 README 和一份不允许子任务读取的 `private.txt`。

先预测：父、子模型各被请求几次？每次请求里有哪些消息？然后查看实际输出：

<<< @/public/learn-agent-rust/outputs/r06-normal.txt

`[coordinator]` 是父 Agent 的事件，`[reader]` 是子 Agent 的事件。父 Agent 提出 `parent/delegate-1` 这次委派；子 Agent 从自己的系统说明和任务开始，提出 `child-1/read-1` 读取，看到文件内容后提取启动命令；父 Agent 收到 `{"response":"启动命令：cargo run"}`，再给用户回答。

输出末尾是父子模型各自收到的请求：父模型两次请求的消息是 `system,user` 和 `system,user,model,function`，子模型的也一样，两份历史各自从头开始。两个公开的测试标记用来检查数据流：

- `PARENT_ONLY_NOTE` 写在用户发给父 Agent 的问题里，用来检查父会话的内容是否被带进子模型的请求。（instruction 不进会话历史，把标记放在那里检查不出任何东西。）
- `CHILD_RAW_ONLY` 写在练习 README 里，用来检查原始文件内容是否被带回父模型的请求。

程序在父子模型收到的全部请求里查找这两个标记，结果是 `parent_saw_child_raw=false`、`child_saw_parent_note=false`；输出里的 `request 0 user text` 也显示，子模型收到的用户消息就是父模型写的任务说明。轨迹里能看到 `CHILD_RAW_ONLY`，是因为子 Agent 的事件被转发出来供宿主诊断：这些事件带着自己的分支保存在父会话里，只是不进父模型的历史。这两个标记只检查本实验的数据流，内容本身没有保密价值。

![父 Agent 的请求只包含委派和子 Agent 的最终回答，子 Agent 的请求从自己的说明和任务开始，文件原文只出现在子 Agent 的历史和转发给宿主诊断的事件里。](/learn-agent-rust/figures/r06-context-boundary.svg)

## 2. 两种把工作交出去的方式

ADK-Rust 有两种让另一个 Agent 接手的方式，本章两种都运行：

| | 当工具调用：`AgentTool` | 交接控制权：`transfer_to_agent` |
| --- | --- | --- |
| 怎么接 | 父 Agent 的工具列表里多一个以子 Agent 命名的工具 | 子 Agent 登记为父 Agent 的 `sub_agent`，父模型多一个 `transfer_to_agent` 工具 |
| 子 Agent 看到什么 | 新的空会话：自己的说明 + 父模型给的任务文字 | 同一个会话里用户的话（以及它自己的轮次） |
| 谁回答用户 | 子 Agent 的最终回答作为工具结果回到父 Agent，父 Agent 再回答 | 子 Agent 直接回答用户，父 Agent 不再继续 |
| 适合 | 父 Agent 需要拿结果继续工作 | 把整段对话交给更合适的专家 |

![左列：父模型调用 reader 工具，reader 在新会话里运行，最终回答作为工具结果返回父 Agent；右列：父模型调用 transfer_to_agent，reader 在同一个会话里接手并直接回答用户。](/learn-agent-rust/figures/r06-transfer-vs-tool.svg)

本章主线是第一种。第二种在第 8 节对照。

## 3. AgentTool：新会话，父模型只收到最终回答

两边的模型都是按规则回复的替身：父模型先委派，看到结果后回答；子模型先读文件，看到结果后提取启动命令。它们只能看到各自收到的请求：

<<< @/public/learn-agent-rust/code/subagents/src/main.rs#model

接线时，子 Agent 是一个普通的 LlmAgent，只有 `read_file` 一个工具；`AgentTool::new(reader)` 把它变成父 Agent 的一个工具：

<<< @/public/learn-agent-rust/code/subagents/src/main.rs#wiring

`AgentTool` 执行时做这几件事：

- **新的会话。** 默认的 `AgentToolSessionSnapshot::Isolated` 让每次委派从空的历史和空的状态开始；子模型收到的只有自己的 instruction 和父模型给的 `request` 文字。按源码，另一个选项 `Parent` 会把父会话的历史和状态复制进去，本章没有运行。
- **父模型只收到最终回答。** 子 Agent 的最终文字变成 `{"response": ...}`，作为这次工具调用的结果交回父模型；中间的读取请求和文件原文不进父模型的历史。但交回来的不止这一项：子 Agent 写的会话状态和产物（artifact）会合并进父会话，默认还共享产物和并行共享状态（`forward_artifacts`、`forward_shared_state`）。
- **事件转发只为观察。** `forward_events(true)` 让子 Agent 的事件也出现在运行的事件流里，带着自己的分支保存进父会话，宿主可以诊断；父模型的历史不包含它们。所以文件原文虽然不给父模型看，却存进了父会话的存储。不打开时，子 Agent 的事件只在它那个临时会话里。
- **失败也作为结果。** 子 Agent 运行出错时，默认返回 `{"agent": ..., "error": "agent execution failed: ..."}` 这样的结果，父模型看得到失败，但错误消息原文默认不带（只有类别和错误码）。

### 子 Agent 一定要运行在独立进程吗？

`AgentTool` 在父 Agent 的同一个进程、同一个 Tokio 运行时里运行子 Agent：框架把每次委派放到一个单独的异步任务上，这次调用被取消或超时，任务随之中止。新会话控制的是模型看见什么，不是操作系统权限：子 Agent 的工具能读写什么，仍由工具本身和应用策略决定。拆成独立进程、容器或远端服务，是另一层执行与隔离设计；后续[后台任务](./background-tasks.md)、[Agent 团队](./agent-teams.md)和[工作区隔离](./worktree-isolation.md)分别展开。

## 4. 宿主的委派契约

框架不限制任务说明和回传结果的长度。本章在 `AgentTool` 外面包一层 `Delegate`：任务说明必须非空且不超过 256 字节，回传超过 160 字节就不交给父模型：

<<< @/public/learn-agent-rust/code/subagents/src/main.rs#contract

`invalid-task` 场景里父模型给了空任务，子 Agent 根本没有运行（子模型请求 0 次）；`oversized-result` 场景里子 Agent 正常完成，但回传超过上限，父模型收到的是 `delegate.output_limit` 错误。两个数字都是本教学应用选择的接口约束，不是性能实验结论。

包装时，名字、参数 schema、“这是一次委派”的标记和超时设置都原样转给 `AgentTool`，框架仍然按委派来对待它：放到单独的任务上运行，用委派自己的超时代替普通工具的超时，打开 `parallelize_agent_delegations` 时连续的委派可以并行。漏转这些方法，包装后的工具就会被当成普通工具。

## 5. 子 Agent 的工具仍经过检查

<<< @/public/learn-agent-rust/code/subagents/src/main.rs#tool

`forbidden-path` 场景里子模型提出读取 `private.txt`，工具检查路径后拒绝（`path.not_allowed`）：读取请求记 1 次，成功 0 次，文件没有被打开。`recursive` 场景里子模型想再委派一次，调用 `reader`，但子 Agent 的工具列表里没有它，框架直接返回 `not_run`（`Tool reader not found`）：子 Agent 没有再往下创建执行者的入口。需要多层委派时，`AgentTool` 还有 `max_delegation_depth` 限制层数，本章没有用到。

应用策略对父子都生效：`AgentTool` 的文档写明，子 Agent 与调用者共用预算、治理、工具策略、审批、账本和审计。本章的策略允许 `reader` 与 `read_file`；未来若允许子 Agent 写文件，需要接入[第 3 章](./permissions.md)的审批，而且子 Agent 等待审批时，父 Agent 的这次调用也会一起挂起。

## 6. 子任务没有自己的一份新预算

先算一算正常路径的用量：父模型两次请求（委派、回答），子模型两次请求（读取、提取）；工具调用是父侧一次委派、子侧一次读取。

[第 1 章](./agent-loop.md)的运行预算装在 Runner 上。`AgentTool` 执行的子 Agent 与父 Agent 共用同一份预算：

| 场景 | 设置 | 实际 |
| --- | --- | --- |
| `global-model-budget` | 整次运行最多 2 次模型请求 | 父 1 次、子 1 次后用完；子 Agent 第二次请求被拒，委派以 `budget.model_calls` 失败，父 Agent 接下来的请求也被拒，运行结束 |
| `parent-answer-budget` | 最多 3 次 | 子 Agent 完成了（父 1 + 子 2），父 Agent 收到了报告，但没有额度生成最终回答 |
| `global-tool-budget` | 整次运行最多 1 次工具调用 | 父侧的委派用掉了这 1 次，子 Agent 的读取 `not_run`（`budget.tool_calls`），委派失败，父 Agent 如实回答未完成 |
| `child-loop-limit` | 子 Agent 自己 `max_iterations(1)` | 子 Agent 读了文件，但没有机会再请求模型提取命令，委派以错误结束；父模型收到的是笼统的 `agent.internal (agent.legacy)`，分不出这是循环上限还是别的内部错误 |

`parent-answer-budget` 的实际轨迹：

<<< @/public/learn-agent-rust/outputs/r06-parent-answer-budget.txt

子 Agent 的成功只是父流程中的一步。前三行之所以要分开看，是因为预算是父子共用的总账：委派一次子任务不会重新得到额度。需要给子 Agent 一个局部上限时，用它自己的 `max_iterations`（`child-loop-limit`）；这只限制它的循环轮数，不是一份独立的预算。

![正常路径父子各两次模型请求、各一次工具调用，全部记在同一份运行预算上；总额度为 3 时子 Agent 完成，父 Agent 的回答被拦下。](/learn-agent-rust/figures/r06-shared-budget.svg)

## 7. 取消请求发出以后

Runner 可以带一个取消令牌（`cancellation_token`）；每次运行从它派生，子 Agent 的上下文直接看父 Agent 的取消状态。`cancel` 场景里，子模型正在生成“读取 README”这条回复时，宿主请求取消：

<<< @/public/learn-agent-rust/outputs/r06-cancel.txt

框架看到取消，就不再读这条回复：读取请求被丢弃，根本没有进入工具分派，所以轨迹里连 `[reader] call` 都没有，读取 0 次，运行随即结束。父 Agent 这一侧，这次委派的结果是 `outcome_unknown`：“运行在 reader 进行中被取消，调用可能已经生效，再调用前先核对”。框架不知道子 Agent 走到了哪一步，所以不说成功也不说失败；这和[专题 2](./side-effect-reliability.md)里“结果未知”的处理是同一个思路。`cancel-before-start` 在运行开始前就取消，父模型一次都没被请求。

这里的取消是协作式的：框架在约定的位置检查取消状态。已经开始的文件读取无法撤销，阻塞中的任意函数也不会被强行终止；接入真实模型和慢工具时，需要各自的超时与中断协议。旧版本章要自己写线程句柄、等待退出和清理临时目录；现在子 Agent 的任务由框架管理，调用被取消时任务随之中止，应用里没有需要自己 `join` 的线程。

## 8. 对照：交接控制权

`transfer` 场景把 reader 登记为 coordinator 的子 Agent，父模型调用 `transfer_to_agent`：

<<< @/public/learn-agent-rust/outputs/r06-transfer.txt

几处与 `AgentTool` 不同：

- 回答用户的是 reader（`answered_by=reader`），父 Agent 只被请求了一次，再也没有拿回控制权。
- 子模型的请求里是用户原话“项目怎么启动？（PARENT_ONLY_NOTE）”，不是父模型写的任务说明，所以 `child_saw_parent_note=true`：交接时，会话里的内容跟着过去了。子模型的请求里还多了一条框架加的说明，告诉它可以把对话再交回 coordinator（`transfer_to_agent` 也出现在它的工具列表里，`disallow_transfer_to_parent` 可以把两者一起关掉）；父模型的请求里同样有一条框架加的交接说明（`roles=system,system,user`）。
- 两者都在同一个会话里：reader 的读取和回答成为会话历史的一部分，下一次运行谁接手，由会话里的记录决定。

所以，需要拿结果继续工作时用 `AgentTool`；要把这段对话整个交给更合适的专家时用交接。

## 9. 结果表与复现范围

下表由验证脚本实际运行后生成。验证脚本还核对了两个标记：所有场景里父模型都没看到 `CHILD_RAW_ONLY`；`PARENT_ONLY_NOTE` 只在 `transfer` 里出现在子模型的请求中。“读取尝试”包括被路径检查拒绝的那一次。

<!-- r06-results:start -->

| 场景 | 父 / 子模型请求 | 读取尝试 / 成功 | 停止 | 回答者 | 练习目标达成 |
| --- | --- | --- | --- | --- | --- |
| `normal` | 2 / 2 | 1 / 1 | `final_answer` | `coordinator` | 是 |
| `changed-readme` | 2 / 2 | 1 / 1 | `final_answer` | `coordinator` | 是 |
| `missing-file` | 2 / 2 | 1 / 0 | `final_answer` | `coordinator` | 否 |
| `child-loop-limit` | 2 / 1 | 1 / 1 | `final_answer` | `coordinator` | 否 |
| `global-model-budget` | 1 / 1 | 1 / 1 | `budget.model_calls` | — | 否 |
| `global-tool-budget` | 2 / 1 | 0 / 0 | `final_answer` | `coordinator` | 否 |
| `parent-answer-budget` | 1 / 2 | 1 / 1 | `budget.model_calls` | — | 否 |
| `cancel` | 1 / 1 | 0 / 0 | `ended` | — | 否 |
| `cancel-before-start` | 0 / 0 | 0 / 0 | `ended` | — | 否 |
| `forbidden-path` | 2 / 2 | 1 / 0 | `final_answer` | `coordinator` | 否 |
| `recursive` | 2 / 2 | 0 / 0 | `final_answer` | `coordinator` | 否 |
| `invalid-task` | 2 / 0 | 0 / 0 | `final_answer` | `coordinator` | 否 |
| `oversized-result` | 2 / 2 | 1 / 1 | `final_answer` | `coordinator` | 否 |
| `model-error` | 2 / 1 | 0 / 0 | `final_answer` | `coordinator` | 否 |
| `transfer` | 1 / 2 | 1 / 1 | `final_answer` | `reader` | 是 |

<!-- r06-results:end -->

`goal_met` 只在“真的读到了 README，并且最终回答里的命令与文件一致”时为真。<a href="/learn-agent-rust/outputs/r06-summary.txt" download>下载全部场景的摘要</a>。

### 与旧版场景的对应 {#old-scenarios}

| 旧版（标准库线程） | 新版（ADK-Rust） | 变化 |
| --- | --- | --- |
| `ChildTask` / `ChildReport` 自定义结构 | `AgentTool` 的 `{"request"}` / `{"response"}` | 用量不再随报告回传，记在共享预算里。 |
| 子循环新建 `Vec<Message>` | `AgentToolSessionSnapshot::Isolated` 新会话 | 由框架建立。 |
| `ChildRun.history` 给宿主诊断 | `forward_events(true)` 转发子事件 | 带分支，父模型历史不含它们。 |
| `SharedBudget` 局部 + 总额度 | Runner 的 `RunBudget` 父子共用；子 Agent 的 `max_iterations` | `child-model-budget` 改为 `child-loop-limit`；`child-tool-budget` 删除（框架没有子 Agent 专用的工具额度）。 |
| `cancel` / `gate-closed`（通道握手） | `cancel`（取消令牌） | 父侧结果为 `outcome_unknown`；没有线程需要 `join`，`gate-closed` 删除。 |
| `forbidden-path`、`recursive` | 同名场景 | 递归调用由框架返回 `not_run`。 |
| `invalid-task`、`oversized-result` | 同名场景 | 由宿主的 `Delegate` 契约实现。 |
| `normal`、`changed-readme`、`missing-file`、`cancel-before-start`、`model-error` | 同名场景 | 含义不变。 |
| （无） | `transfer` | 交接控制权的对照。 |
| 16 个场景、9 项测试 | 15 个场景、7 项测试 | 线程与通道相关的场景和测试不再需要。 |

验证脚本把工程打包后在临时目录解压，在旁边放好 ADK-Rust 源码，运行格式、Clippy、7 项 Rust 测试和离线构建；摘要和几条详细轨迹各连跑两次必须逐字节相同，并把上面的结果表写回正文。维护者在网站仓库根目录执行：

```sh
python3 scripts/fetch-adk-rust.py .cache/adk-rust    # 只需一次；或设 ADK_RUST_SRC
python3 scripts/verify-agent-subagents.py
python3 scripts/generate-learn-agent-rust-figures.py --lesson R06
python3 scripts/verify-agent-subagents.py --check
```

## 框架替你做了什么、没做什么

| 框架做了 | 仍归应用 |
| --- | --- |
| `AgentTool` 为每次委派建新会话，父模型只收到最终回答；子 Agent 写的状态与产物合并回父会话；失败也作为结果返回。 | 决定交给子 Agent 什么任务文字；限制任务与回传的大小（本章的 `Delegate`）。 |
| 子 Agent 与父 Agent 共用预算、策略、审批与审计。 | 设定总预算；需要局部上限时给子 Agent 设 `max_iterations`。 |
| 子 Agent 只能用自己登记的工具；`max_delegation_depth` 可限制委派层数。 | 给子 Agent 最小的工具集，工具自己检查参数。 |
| 取消状态传到子 Agent；委派中途取消时父侧结果为 `outcome_unknown`。 | 处理“结果未知”：再调用前核对；慢工具自己的中断协议。 |
| `transfer_to_agent` 交接控制权，并给子 Agent 加上可交回的说明。 | 选择交接还是当工具调用；需要时禁止交回父 Agent。 |

<!-- adk-refs:start -->

## 在 ADK-Rust 源码里

本章的委派、上下文隔离、共用预算、取消与交接，在 ADK-Rust 里分布在这几处：

| 本章内容 | 源码位置 | 对照要点 |
| --- | --- | --- |
| 把 Agent 当成工具 | [`adk-tool/src/agent_tool.rs` · `AgentTool`](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-tool/src/agent_tool.rs#L371-L375) | 结构体上方的说明：子 Agent 与调用者共用预算、治理、工具策略、审批、账本与审计，但不继承交接目标 |
| 子会话从哪里开始 | [`adk-tool/src/agent_tool.rs` · `AgentToolSessionSnapshot`](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-tool/src/agent_tool.rs#L48-L54) | 默认 `Isolated`：每次委派从空的历史和状态开始；`Parent` 复制父会话 |
| 父模型给的任务成为子 Agent 的用户消息 | [`adk-tool/src/agent_tool.rs` 第 980 行](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-tool/src/agent_tool.rs#L980) | `request` 参数的文字就是子模型看到的全部任务 |
| 子 Agent 的取消状态 | [`adk-tool/src/agent_tool.rs` 第 1587 行](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-tool/src/agent_tool.rs#L1587) | 子 Agent 上下文的取消状态直接取自父 Agent；运行开始前已取消时，委派还会在执行前直接失败 |
| 只回传最终回答 | [`adk-tool/src/agent_tool.rs` 第 786 行](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-tool/src/agent_tool.rs#L786) | 子 Agent 的最终文字包成 `{"response": ...}`，作为工具结果交回 |
| 哪些运行设置传给子 Agent | [`adk-tool/src/agent_tool.rs` · `delegated_run_config`](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-tool/src/agent_tool.rs#L217-L312) | 逐个字段决定共享还是不共享；`budget` / `budget_tracker` 原样共享，所以父子共用一份预算 |
| 转发子事件 | [`adk-tool/src/agent_tool.rs` · `AgentTool::forward_events`](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-tool/src/agent_tool.rs#L468-L471) | 转发的事件带着自己的分支，父模型的历史不包含它们 |
| 运行中断时的进行中调用 | [`adk-runner/src/runner.rs` 第 140 行](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-runner/src/runner.rs#L140) | 取消时，每个还在进行的调用都得到 `outcome_unknown` 结果（`cancel` 场景里的 reader） |
| 交接工具的声明 | [`adk-agent/src/llm_agent.rs` 第 720 行](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-agent/src/llm_agent.rs#L720) | 有子 Agent 或可交接目标时，模型的工具列表里多一个 `transfer_to_agent` |
| 接手者看到的历史 | [`adk-agent/src/llm_agent.rs` 第 450 行](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-agent/src/llm_agent.rs#L450) | 交接来的 Agent 只看到用户的话和它自己的轮次 |

源码固定在 ADK-Rust `98515241133d`（3.0.0，2026-11-26，尚未发布到 crates.io）。本节由 `scripts/learn-agent-rust-adk-refs.py` 生成。

<!-- adk-refs:end -->

::: warning 常见误区
- **复制全部父历史再称为干净上下文。** 子任务输入要按目标明确选择；本章只传任务说明（`Isolated`）。
- **把上下文分离当成权限隔离。** 新会话只控制模型看见什么；同一进程里的工具仍需执行前检查。
- **以为每个子任务有一份新预算。** `AgentTool` 的子 Agent 与父 Agent 共用运行预算；子任务完成后父侧仍可能没有回答额度。
- **把子 Agent 的返回当成任务成功。** 返回可能是失败说明或错误对象；父 Agent 要如实处理。
- **把取消当成回滚。** 委派中途取消，父侧只知道“结果未知”；已经发生的效果不会撤销。
- **把交接和工具调用混为一谈。** 交接之后回答用户的是子 Agent，父 Agent 拿不到结果继续工作。
:::

<!-- transfer-thinking:start -->

## 迁移思考：隔离信息与回收执行者

父会话看不到子会话历史，子任务就无法影响父任务了吗？先给出你的判断，再展开下面的推演。

<details><summary>推演与应用</summary>

检查共享预算、允许工具、结果大小与取消后的句柄。独立历史仍可能共享文件和额度。

审查隔离方案时列出所有共享资源，不只看消息列表。

</details>

这是一道迁移练习，推演不代表新增实验已通过。对照[全书审查中的证据层次](./course-review.md#evidence-layers)，说明你的判断还需要哪一级证据。

<!-- transfer-thinking:end -->

## 本章结论

一次子任务拥有自己的会话和输入。`AgentTool` 让父 Agent 把工作交出去、只收回最终回答，子 Agent 的中间过程留在它自己的会话和宿主的诊断轨迹里；`transfer_to_agent` 则把整段对话交给子 Agent。

隔离的只是模型看到的内容：预算、策略、审批和取消状态贯穿父子执行，文件系统也是共享的。任务与回传的契约、“结果未知”的处理，仍由应用负责。

## 检查理解

1. 父模型收到的 `{"response": ...}` 和转发出来的子事件，分别给谁用？

   <details><summary>参考答案</summary>

   `{"response": ...}` 是这次工具调用的结果，进入父模型的历史，是父 Agent 继续工作的输入。转发的子事件带着自己的分支，出现在运行的事件流里、也保存在父会话里给宿主诊断，但父模型的历史不包含它们。

   </details>

2. 正常路径为什么父子各被请求两次模型？

   <details><summary>参考答案</summary>

   父模型提出委派、生成最终回答，共 2 次；子模型提出读取、提取启动命令，共 2 次。四次请求记在同一份运行预算上。

   </details>

3. `global-model-budget` 里子 Agent 自己的循环上限还远没到，为什么第二次请求被拒？

   <details><summary>参考答案</summary>

   运行预算是父子共用的：父 Agent 的第一次请求和子 Agent 的第一次请求已经用完 2 次额度。`max_iterations` 只限制子 Agent 自己的循环轮数，不是一份独立的预算。

   </details>

4. `parent-answer-budget` 中子任务已完成，为什么练习目标为 `false`？

   <details><summary>参考答案</summary>

   子任务完成后，父 Agent 已经收到报告，但生成最终回答需要第四次模型请求。总额度只有 3，父侧在请求前停止，尚未向用户给出答案。

   </details>

5. `cancel` 场景里父侧的结果为什么是 `outcome_unknown`，而不是失败？

   <details><summary>参考答案</summary>

   取消发生在委派进行中，框架不知道子 Agent 走到了哪一步、有没有产生效果，所以只说“可能已经生效，再调用前先核对”。本场景里读取确实没有执行，但父侧不能从结果里得知这一点。

   </details>

6. 什么时候用 `AgentTool`，什么时候用 `transfer_to_agent`？

   <details><summary>参考答案</summary>

   父 Agent 需要拿子任务的结果继续工作时，用 `AgentTool`：子 Agent 在新会话里运行，只回传最终回答。要把这段对话整个交给更合适的专家、由它直接回答用户时，用交接：子 Agent 看到用户原话，父 Agent 不再继续。

   </details>

## 参考资料

- [Learn Claude Code：s06 Subagent](https://learn.shareai.run/zh/s06/)：参考课程的独立历史、子工具范围与摘要回传。
- [ADK-Rust 固定源码](https://github.com/zavora-ai/adk-rust/tree/98515241133d24f7e41f8fd272649035416a142f)：本课程真实运行的接口与语义基线。

参考课程的[原始子 Agent 图](/learn-agent-rust/figures/upstream/r06-subagent-overview.svg)原样保留，图中的 Python/Claude 接口按原语境理解；来源与许可见[课程架构](./architecture.md#reference-assets)。正文中的 Rust 图由本站脚本生成。

下一章：[第 10 章：按需加载技能](./skill-loading.md)。子任务可以选择自己的输入，专业说明也可以按当前目标加载；下一章区分知识注入与执行权限。
