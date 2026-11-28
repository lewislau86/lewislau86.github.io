---
title: "第 19 章：规划、执行与动态重规划"
description: "用 ADK-Rust 3.0 的 LoopAgent 让规划者和执行者轮流工作：计划由应用保管、修订号与已完成步骤受检查，读到新成员就重规划；再用 adk-harness 的计划模式看计划怎样在动手之前被人批准。"
pageClass: learn-agent-rust-course
prev:
  text: 第 18 章 · 并行分解与结果归并
  link: /learn-agent-rust/parallel-decomposition
next:
  text: 第 20 章 · 协调者、工作者与任务交接
  link: /learn-agent-rust/orchestrator-workers-handoffs
---

# 第 19 章：规划、执行与动态重规划

[课程总览](./index.md) · [上一章](./parallel-decomposition.md) · [本部分导读](./agent-design-patterns.md) · [学习路径](./learning-path.md#d04) · [下一章](./orchestrator-workers-handoffs.md)

::: tip 本章学习目标
- 说清一份计划从哪里来：谁提出、谁检查、谁批准、谁执行，以及计划改了以后，已经做完的事怎么办。
- 用 `LoopAgent` 让规划者和执行者轮流工作，读到新情况就重规划，同时保住已完成的步骤和结果账本。
- 用计划模式（adk-harness）把“先调研、提交计划、人批准、再动手”变成框架强制的流程。

**前置：** [第 8 章：可见的任务清单](./todo-planning.md)、[第 9 章：子 Agent 与上下文隔离](./subagents.md)、[第 17 章：提示链与条件路由](./prompt-chaining-routing.md)。

**实践方式：** 下载<a href="/learn-agent-rust/plan-execute-replan.zip" download>完整 plan-execute-replan.zip</a>，按[第 1 节](#hands-on)取一次 ADK-Rust 源码后运行；无需模型密钥。
:::

::: info 本章已迁移到 ADK-Rust 3.0
旧版用 graph-flow 的节点手写计划校验、执行与重规划，检查动作是内存夹具，可从 git 标签 `learn-agent-rust-v1` 取得。新版用 `LoopAgent` 组织规划者与执行者，文件真实读取；另新增计划模式一节（adk-harness，Beta）。[对应表](#old-scenarios)列出了场景的变化。
:::

第 8 章的任务清单回答了“计划写下来以后怎么推进”。这一章往前退一步：计划本身是怎样来的？

工作区助手要检查一次升级要读哪些 README。动手之前它只知道根 README；读了根 README 才知道有成员 member，读了 member 的 README 又发现还要看 plugin。一开始就列出全部步骤是做不到的，计划只能边做边补。

这就是“规划—执行—重规划”：先写一份当下能写的计划，执行一步，看结果，必要时修订剩下的步骤。修订时有两条底线：已经做完的步骤不能从计划里消失，已经拿到的结果不能丢。

还有一种更谨慎的做法：动手之前先只读调查，把计划交给人看，批准了才允许改文件。这就是“计划模式”。

<LearnAgentRustMap active="plan-execute-replan" />

<!-- experiment-library:start -->

全书实验可从[统一代码库](./experiments.md#plan-execute-replan)下载；解压后进入 `chapters/plan-execute-replan/`，或在代码库根目录运行 `python3 run.py run D04`。

<!-- experiment-library:end -->

::: info 本章实验状态
`LoopAgent`、`LlmAgent`、`CustomAgent`、`exit_loop`，以及 adk-harness 的计划模式与 `exit_plan_mode`，都是 ADK-Rust 的真实实现；README 和写出的文件真实存在于临时目录里。规划者和“人”都是按规则回复的替身：规划者按账本里读到的“成员：”“另见：”补步骤，“人”按场景批准或拒绝。真实模型写出的计划质量没有测试。adk-harness 在 ADK-Rust 3.0 里是 Beta。
:::

## 1. 先运行：七个场景 {#hands-on}

下载并解压工程，先取一次 ADK-Rust 源码再运行：

```sh
cd plan-execute-replan
python3 fetch-adk-rust.py ../adk-rust    # 需要 git 与 GitHub 访问；不行时加 --method cdn
cargo run --locked
```

编译时会看到 adk-core 的 3 条弃用警告（上游固定 Rust 1.95.0，本课程用 1.99.1），不影响运行和检查。

<<< @/public/learn-agent-rust/outputs/d04-summary.txt

前四个场景是规划—执行循环：`revisions` 是被接受的计划修订号，`rejected` 是被拒绝的计划及原因，`executed` 是账本里按顺序执行过的文件，`iterations` 是执行者运行的轮数，`planner_saw` 是规划者每次调用模型时、系统消息里看到的计划修订号（0 表示还没有计划，第 3 节解释它为什么成对出现），`stop` 是循环怎样结束。后三个场景是计划模式：`tools` 是按顺序的工具结果，`asked` 是“人”被问了什么、怎样回答，`file_written` 是最后有没有写出文件。

## 2. 计划从哪里来

一份计划经过四个角色：

| 角色 | 本章由谁担任 | 做什么 |
| --- | --- | --- |
| 提出 | 规划者（`LlmAgent`） | 根据任务和账本写出完整的新计划 |
| 检查 | 应用（`write_plan` 工具） | 修订号必须是当前加一，已完成的步骤一个不能少、文件不能改，步骤 id 不能重复 |
| 批准 | 人（计划模式里） | 看过计划才允许动手；第一部分的循环里没有这一步 |
| 执行 | 执行者（`CustomAgent`） | 由代码执行下一个待办步骤，结果记进账本 |

模型只负责提出。计划存在应用手里，模型改不了它，只能提交一份新的、由应用决定接不接受：

<<< @/public/learn-agent-rust/code/plan-execute-replan/src/main.rs#plan

## 3. 规划者与执行者轮流工作

<<< @/public/learn-agent-rust/code/plan-execute-replan/src/main.rs#loop

`LoopAgent` 每一轮按顺序运行两个子 Agent：先规划者，再执行者。规划者的指令里有 `{plan?}` 和 `{ledger?}` 两个模板。模板在规划者**每次运行开始时**按最新的会话状态渲染一次，所以每一轮它都能看到上一轮执行的结果；但在同一次运行里，它调用 `write_plan` 之后再次调用模型，系统消息仍是这次运行开始时渲染的旧计划。`discover` 的 `planner_saw=[0,0,1,1,2,2,3]` 就是这样来的：每轮两次模型调用看到同一个修订号，新修订要到下一轮才出现在指令里。规划者想知道刚提交的计划有没有被接受，要看 `write_plan` 的返回结果，而不是指令。

执行者把计划和账本镜像进会话状态：

<<< @/public/learn-agent-rust/code/plan-execute-replan/src/main.rs#executor

规划者做三种决定：计划里还有待办步骤，就把这一轮交给执行者；账本里提到了计划里没有的文件，就提交一份修订后的计划；什么都做完了，就调用 `exit_loop` 收工。

<<< @/public/learn-agent-rust/outputs/d04-discover.txt

`discover` 从只有根 README 的 r1 开始：读完根 README 看到“成员：member”，提交 r2；读完 member 看到“另见：plugin/README.md”，提交 r3；三个都读完，`exit_loop` 结束循环。每份新计划都把已完成的步骤原样带上，账本里的三条结果一条没丢。

## 4. 守住计划的边界

- **`drops-done`**：替身规划者每次重规划，第一次提交都只写了新步骤，把已完成的 s1 丢了（r2、r3 各被拒一次，所以 `rejected` 里有两条）。`write_plan` 拒绝（`done_step_removed:s1`），规划者看到错误后补上 s1 重新提交，循环照常完成。“已经做过的事”留在计划和账本里，重规划只改将来的步骤。
- **`missing-file`**：member 的 README 不存在。执行者把失败记进账本，并把事件标成 escalate（上报），`LoopAgent` 立刻停下，`stop=step_failed`。
- **`stuck`**：什么都做完了，替身规划者却不肯调用 `exit_loop`。`LoopAgent` 跑满 `max_iterations`（这里设为 6 轮；不设时默认 1000 轮）就结束，**不报错**；这和 `LlmAgent` 的 `max_iterations` 不同，后者超过上限会以错误结束（第 16 章）。所以循环结束以后，应用要自己判断：是 `exit_loop` 收的工，还是轮数用完了。

<<< @/public/learn-agent-rust/outputs/d04-drops-done.txt

## 5. 计划模式：先批准，再动手

上面的循环里，计划一写好就开始执行。改文件、发消息这类有后果的动作，往往希望先让人看过计划。adk-harness 的计划模式把这件事做成了框架规则：

| 模式 | 读文件 | 改文件 | 提交计划（`exit_plan_mode`） |
| --- | --- | --- | --- |
| 计划模式 | 放行 | 拒绝 | 每次都问人，不能被“记住”免掉 |
| 询问模式 | 放行 | 问人 | 拒绝 |
| 自动模式 | 放行 | 放行 | 拒绝 |

表里只列了本章用到的三类工具和三种模式。adk-harness 还有更严的只读模式（改文件、提交计划都拒绝），shell、联网、写记忆等其他工具在各模式下另有规则，见源码里的 `MODE_TABLE`。

<<< @/public/learn-agent-rust/code/plan-execute-replan/src/main.rs#plan_mode

<<< @/public/learn-agent-rust/outputs/d04-plan-mode-approved.txt

第一轮会话在计划模式里：模型读了 README（放行），想提前写 `UPGRADE.md`（被拒绝：计划模式不允许改文件），然后调用 `exit_plan_mode` 提交计划和两个步骤。框架先问人，人批准、步骤检查也通过后，会话模式改成下一个模式：模型可以在参数里提议 `ask` 或 `auto`，不提议时默认询问模式（`ask`），框架从不默认进自动模式，批准的人还可以改掉模型的提议。新模式**从下一轮对话（下一次 `send`）起生效**，这一轮随即结束。计划和它的指纹记进会话状态 `harness:plan`，轨迹里的 `[state]` 一行就是在第二轮开始前从会话里读出来的。第二轮用户说“开始执行”，模型写文件，这次是询问模式，框架又问了一次人，批准后文件写了出来。

- `plan-mode-rejected`：人拒绝了计划，会话仍在计划模式，第二轮写文件照样被拒绝，没有文件。
- `plan-mode-invalid`：计划里的步骤 2 依赖一个不存在的步骤 9。人先被问到并批准了，`exit_plan_mode` 执行时才检查出 `harness.plan.invalid`，模式没有改变，第二轮写文件仍被拒绝。问人在前、工具检查在后，人看到的可能是一份不合格的计划。

计划模式把“谁来批准计划”交给了人，把“批准之前不能动手”交给了框架。计划的步骤还能编译成 harness 的计划图（需要 `graph` 特性，并在构建时打开计划图），那时还会检查步骤依赖有没有环；本章的工程关掉了默认特性、只开 `runner`，没有使用。

![左边是规划—执行循环：规划者提出计划、应用检查、执行者执行并记账，读到新文件就重规划；右边是计划模式：只读调查、提交计划、人批准、步骤检查通过后，下一轮对话切到询问模式，改文件时再问一次人。](/learn-agent-rust/figures/d04-pattern-flow.svg)

左右两半分别是两种做法；底部两行是本章场景的实际结果：规划—执行循环怎样结束，计划模式下有没有写出文件。

### 全部场景的实际结果

<!-- d04-results:start -->

| 场景 | 计划修订 | 被拒计划 | 执行过的文件 | 循环结束 | 计划模式的工具结果 | 问人 | 写出文件 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `discover` | `[1,2,3]` | `[]` | `[README.md,member/README.md,plugin/README.md]` | `completed` | — | — | — |
| `drops-done` | `[1,2,3]` | `[done_step_removed:s1,done_step_removed:s1]` | `[README.md,member/README.md,plugin/README.md]` | `completed` | — | — | — |
| `missing-file` | `[1,2]` | `[]` | `[README.md,member/README.md(missing)]` | `step_failed` | — | — | — |
| `stuck` | `[1,2,3]` | `[]` | `[README.md,member/README.md,plugin/README.md]` | `loop_limit` | — | — | — |
| `plan-mode-approved` | — | — | — | — | `[read_file:ok,write_file:refused,exit_plan_mode:ok,write_file:ok]` | `[exit_plan_mode@plan:approve,write_file@ask:approve]` | `yes` |
| `plan-mode-rejected` | — | — | — | — | `[read_file:ok,write_file:refused,exit_plan_mode:refused,write_file:refused]` | `[exit_plan_mode@plan:deny]` | `no` |
| `plan-mode-invalid` | — | — | — | — | `[read_file:ok,write_file:refused,exit_plan_mode:failed(harness.plan.invalid),write_file:refused]` | `[exit_plan_mode@plan:approve]` | `no` |

<!-- d04-results:end -->

### 与旧版场景的对应 {#old-scenarios}

| 旧版（graph-flow 夹具） | 新版（ADK-Rust） | 变化 |
| --- | --- | --- |
| `normal`、`discover` | `discover` | 规划者与执行者由 `LoopAgent` 轮流运行，真实读文件。 |
| `cycle`、`unknown` | `plan-mode-invalid` | 依赖检查改由 `exit_plan_mode` 做；本章只演示未知依赖，环检查要等计划编译成计划图（`graph` 特性）时才做。 |
| `repeat` | `stuck` | 规划者不收工时由 `LoopAgent` 的轮数上限结束。 |
| `budget` | `stuck` | 同上。 |
| （无） | `drops-done`、`missing-file` | 重规划丢掉已完成步骤、执行失败。 |
| （无） | `plan-mode-approved`、`plan-mode-rejected` | 计划模式。 |
| 6 个场景、4 项测试 | 7 个场景、4 项测试 | — |

验证脚本把工程打包后在临时目录解压，在旁边放好 ADK-Rust 源码，运行格式、Clippy、4 项 Rust 测试和离线构建；摘要和几条详细轨迹各连跑两次必须逐字节相同，并把结果表写回正文。维护者在网站仓库根目录执行：

```sh
python3 scripts/fetch-adk-rust.py .cache/adk-rust    # 只需一次；或设 ADK_RUST_SRC
python3 scripts/verify-agent-patterns-adk.py --lesson D04
python3 scripts/generate-learn-agent-rust-figures.py --lesson D04
python3 scripts/verify-agent-patterns-adk.py --lesson D04 --check
```

## 框架替你做了什么、没做什么

| 框架做了 | 仍归应用 |
| --- | --- |
| `LoopAgent` 每轮按顺序运行子 Agent；`exit_loop` 或上报就停，轮数用完也停（不报错）。 | 判断循环是收工还是轮数用完；决定执行失败时怎么办。 |
| 每轮子 Agent 开始时重新渲染 `{键}` 模板。 | 保管计划；检查修订号与已完成步骤；维护结果账本。 |
| 计划模式：只读、提交计划要问人、批准后下一轮对话切换模式；不提议时默认进询问模式。 | 决定给人看什么、怎样问；批准时确认或改掉模型提议的下一个模式。 |
| `exit_plan_mode` 检查步骤 id 唯一、依赖存在（编译成计划图时还查环）。 | 检查计划内容本身是否合理。 |

<!-- adk-refs:start -->

## 在 ADK-Rust 源码里

本章的规划—执行循环与计划模式，在 ADK-Rust 里分布在这几处：

| 本章内容 | 源码位置 | 对照要点 |
| --- | --- | --- |
| 轮流运行的循环 | [`adk-agent/src/workflow/loop_agent.rs` 第 662 行](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-agent/src/workflow/loop_agent.rs#L662) | 每轮按顺序运行子 Agent；上报就提前结束，轮数用完就安静地结束，不报错 |
| 收工的工具 | [`adk-tool/src/builtin/exit_loop.rs` · `ExitLoopTool`](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-tool/src/builtin/exit_loop.rs#L8) | 把事件标成 escalate，`LoopAgent` 在这个子 Agent 之后结束 |
| 提交计划 | [`adk-harness/src/tools/plan.rs` · `ExitPlanModeTool`](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-harness/src/tools/plan.rs#L116-L121) | 只在计划模式下有效；批准后写入新模式、把计划与指纹镜像进 `harness:plan`，并结束这一轮 |
| 计划步骤的检查 | [`adk-harness/src/tools/plan.rs` 第 220 行](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-harness/src/tools/plan.rs#L220) | 步骤 id 要唯一、依赖要存在；不合格就拒绝，模式不变 |
| 从下一轮起生效 | [`adk-harness/src/tools/plan.rs` 第 280 行](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-harness/src/tools/plan.rs#L280) | 批准计划的这一轮仍在计划模式，所以就此结束 |
| 计划模式的规则 | [`adk-harness/src/policy.rs` 第 818 行](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-harness/src/policy.rs#L818) | 这一行与下一行：提交计划只在计划模式下放行且每次问人；改文件在计划模式下拒绝、询问模式问人、自动模式放行 |

源码固定在 ADK-Rust `98515241133d`（3.0.0，2026-11-26，尚未发布到 crates.io）。本节由 `scripts/learn-agent-rust-adk-refs.py` 生成。

<!-- adk-refs:end -->

::: warning 常见误区
- **把模型写的计划直接当成计划。** 计划由应用保管，模型只能提交，接不接受由应用检查。
- **重规划时从头再来。** 已完成的步骤和账本要原样保留，重规划只改将来的步骤。
- **以为 `LoopAgent` 轮数用完会报错。** 它安静地结束；要靠应用检查计划是否真的做完。
- **以为批准了计划，这一轮就能动手。** 模式切换从下一轮对话起生效。
- **以为规划者调用 `write_plan` 后，指令里马上是新计划。** 模板每次运行只渲染一次，同一次运行里要看工具结果。
- **以为人批准的一定是合格的计划。** 问人在前，`exit_plan_mode` 的检查在后。
:::

<!-- transfer-thinking:start -->

## 迁移思考：重规划保留结果账本

新发现一个 workspace 成员后，为什么不重跑整个计划？先给出你的判断，再展开下面的推演。

<details><summary>推演与应用</summary>

已经读过的根 README 结果仍然有效，新成员只影响还没做的部分。重跑整个计划会重复已经做过的动作；如果那些动作有副作用（写文件、发消息），重复就是事故。所以重规划只修订待办步骤，已完成的步骤和账本原样保留，`write_plan` 用 `done_step_removed` 把这条底线交给代码守住。

数据管道新增分区时也一样：已经确认的产物留着，只为新分区补步骤。

</details>

这是一道迁移练习，推演不代表新增实验已通过。对照[全书审查中的证据层次](./course-review.md#evidence-layers)，说明你的判断还需要哪一级证据。

<!-- transfer-thinking:end -->

## 本章结论

计划由模型提出，由应用检查，必要时由人批准，由执行者照着做。步骤无法一开始列全时，让规划者和执行者在 `LoopAgent` 里轮流工作，读到新情况就提交修订后的计划；应用守住修订号和已完成的步骤，账本只增不减。有后果的动作之前，用计划模式把“先批准、再动手”交给框架强制执行。

## 检查理解

1. `discover` 为什么提交了三次计划，而不是一开始就列出三个文件？

   <details><summary>参考答案</summary>

   一开始只知道根 README。读了根 README 才知道有 member，读了 member 才知道要看 plugin。每次读到新情况，规划者才提交修订后的计划。

   </details>

2. `drops-done` 的第一份重规划为什么被拒绝？拒绝以后怎样了？

   <details><summary>参考答案</summary>

   它只写了新步骤，丢掉了已完成的 s1。`write_plan` 要求已完成的步骤一个不能少，返回 `done_step_removed:s1`。规划者看到错误后补上 s1 重新提交，被接受，循环照常完成。

   </details>

3. `stuck` 跑满了 6 轮，为什么没有报错？应用怎样知道出了问题？

   <details><summary>参考答案</summary>

   `LoopAgent` 轮数用完就安静地结束，不报错。应用要自己区分循环为什么结束：本章看有没有收到上报、上报来自谁——规划者调用 `exit_loop` 记为 `completed`，执行者上报失败记为 `step_failed`，一直没有上报记为 `loop_limit`。`stuck` 属于最后一种。更稳妥的应用还会再对一次计划：所有步骤都已完成，才算真的做完。

   </details>

4. `plan-mode-approved` 里，计划批准以后，为什么这一轮没有接着写文件？

   <details><summary>参考答案</summary>

   批准的模式从下一轮对话起生效，`exit_plan_mode` 批准后这一轮就结束了，这一轮里仍是计划模式。用户下一次说“开始执行”，会话已是询问模式，写文件时又问了一次人。

   </details>

5. `plan-mode-invalid` 里人已经批准了，为什么模式没有改变？

   <details><summary>参考答案</summary>

   问人在工具执行之前。人批准以后，`exit_plan_mode` 执行时才检查出步骤 2 依赖不存在的步骤 9，返回 `harness.plan.invalid`，模式没有改变。

   </details>

## 参考资料

- [Plan-and-Solve Prompting](https://arxiv.org/abs/2305.04091)：先规划再执行的提示方法。
- [ADK-Rust 固定源码](https://github.com/zavora-ai/adk-rust/tree/98515241133d24f7e41f8fd272649035416a142f)：`LoopAgent` 与 adk-harness 计划模式的实现。

下一章：[第 20 章 · 协调者、工作者与任务交接](./orchestrator-workers-handoffs.md)。回到[本部分导读](./agent-design-patterns.md)比较模式。
