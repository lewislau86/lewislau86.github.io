---
title: "第 16 章：模式选择：单次调用、工作流与自主循环"
description: "同一个升级报告任务分别用一次模型调用、ADK-Rust 3.0 的 SequentialAgent 固定工作流和 LlmAgent 工具循环完成，比较每种结构能完成什么输入、在哪里失败、由谁决定下一步。"
pageClass: learn-agent-rust-course
prev:
  text: 第 15 章 · 系统提示词组装
  link: /learn-agent-rust/system-prompts
next:
  text: 第 17 章 · 提示链与条件路由
  link: /learn-agent-rust/prompt-chaining-routing
---

# 第 16 章：模式选择：单次调用、工作流与自主循环

[课程总览](./index.md) · [上一章](./system-prompts.md) · [本部分导读](./agent-design-patterns.md) · [学习路径](./learning-path.md#d01) · [下一章](./prompt-chaining-routing.md)

::: tip 本章学习目标
- 根据输入是否齐全、步骤是否事先已知、下一步是否取决于刚读到的内容，在单次调用、固定工作流和自主循环之间做选择。
- 看懂 ADK-Rust 怎样表达这三种结构：一个 `LlmAgent`、一个 `SequentialAgent`、一个带工具的 `LlmAgent`，以及各自的停止方式。
- 用应用自己的验收判断结果，而不是用“跑完了”“调用少”当作成功。

**前置：** [第 1 章：最小 Agent 循环](./agent-loop.md)、[第 5 章：图状态、条件路由与有界循环](./graph-state-routing.md)、[第 8 章：可见的任务清单](./todo-planning.md)（会话状态与 `{键}` 模板）。

**实践方式：** 下载<a href="/learn-agent-rust/pattern-selection.zip" download>完整 pattern-selection.zip</a>，按[第 1 节](#hands-on)取一次 ADK-Rust 源码后运行；无需模型密钥。
:::

::: info 本章已迁移到 ADK-Rust 3.0
旧版用 graph-flow 的节点和跳转模拟三种结构，读取与决策都是内存夹具，可从 git 标签 `learn-agent-rust-v1` 取得。新版用 ADK-Rust 的真实结构：`SequentialAgent` 串起固定步骤，`LlmAgent` 的工具循环由模型决定下一步；文件真实写在临时目录里。[对应表](#old-scenarios)列出了场景的变化。
:::

工作区助手接到任务：“根据工作区的 README 写一份升级报告，列出依据的文件。”根 README 写着升级要求，还有一行“成员：member”，每个成员目录下各有一份 README。

这件事可以有三种做法：用户把 README 内容直接贴进问题，模型一次写完；程序按固定步骤先读根 README、再读 member 的 README，最后让模型写；或者给模型一个读文件的工具，读什么、读几次由它决定。

先猜一猜：哪种做法调用模型最少？如果工作区里多了一个成员 plugin，哪种做法还能写出完整的报告？

<LearnAgentRustMap active="pattern-selection" />

<!-- experiment-library:start -->

全书实验可从[统一代码库](./experiments.md#pattern-selection)下载；解压后进入 `chapters/pattern-selection/`，或在代码库根目录运行 `python3 run.py run D01`。

<!-- experiment-library:end -->

::: info 本章实验状态
`LlmAgent`、`SequentialAgent`、`CustomAgent`、会话状态与 `max_iterations` 都是 ADK-Rust 的真实实现；README 真实写在临时目录里。模型是按规则回复的替身：没有工具时按请求里出现的资料写报告；有读文件工具时，先读根 README，再按“成员：”一行补读。模型调用次数来自替身，只用来比较结构，不代表真实模型的成本或质量。
:::

## 1. 先运行：三种结构的摘要 {#hands-on}

下载并解压工程，先取一次 ADK-Rust 源码再运行：

```sh
cd pattern-selection
python3 fetch-adk-rust.py ../adk-rust    # 需要 git 与 GitHub 访问；不行时加 --method cdn
cargo run --locked
```

编译时会看到 adk-core 的 3 条弃用警告（上游固定 Rust 1.95.0，本课程用 1.99.1），不影响运行和检查。

<<< @/public/learn-agent-rust/outputs/d01-summary.txt

每行是一个场景：`structure` 是结构，`agents` 是事件里出现过的 Agent，`model_calls` 是模型被调用的次数，`reads` 是实际读过的文件，`verdict` 是应用的验收结果。验收只看一件事：报告最后一行“依据：”必须列出根 README 和“成员：”里的每一个成员的 README。

<<< @/public/learn-agent-rust/code/pattern-selection/src/main.rs#acceptance

## 2. 单次调用：输入齐全时就够了

`single` 场景里，用户把根 README 和 member 的 README 都贴进了问题。一个没有工具的 `LlmAgent` 调用一次模型就写完了，验收通过。

`single-partial` 只贴了根 README：模型同样调用一次，写出的报告只能依据它看到的资料，验收报告缺 `member/README.md`。

<<< @/public/learn-agent-rust/outputs/d01-single-partial.txt

单次调用省掉的不是“能力”，而是读取步骤：资料由用户负责给全。输入不全时，它没有办法自己补。

## 3. 固定工作流：步骤由代码决定

步骤事先已知时，用 `SequentialAgent` 把它们串起来：读根 README → 读 member 的 README → 写报告。前两步是 `CustomAgent`，由代码读文件，把内容写进会话状态；写报告的 `LlmAgent` 用 `{root_readme}`、`{member_readme}` 模板读出这两份内容：

<<< @/public/learn-agent-rust/code/pattern-selection/src/main.rs#workflow

<<< @/public/learn-agent-rust/outputs/d01-workflow.txt

`[read_root] state root_readme = …` 一行就是第一步写进状态的内容。整个工作流只调用了一次模型，读文件的两步不经过模型。

固定步骤的代价在 `workflow-new-member`：根 README 多了一个成员 plugin，可工作流只会读写死的两个文件，报告验收缺 `plugin/README.md`。

<<< @/public/learn-agent-rust/outputs/d01-workflow-new-member.txt

`workflow-missing` 是另一种失败：member 的 README 不存在。读文件的步骤把事件标成 `escalate`（上报：告诉外层的工作流“到此为止”），`SequentialAgent` 立刻停下，写报告的那一步没有运行（`agents` 里没有 `writer`，`model_calls=0`）。

<<< @/public/learn-agent-rust/outputs/d01-workflow-missing.txt

如果这一步不上报会怎样？`workflow-silent` 用同一个缺文件的工作区，读文件的步骤只写了一个空字符串、照常往下走：

<<< @/public/learn-agent-rust/outputs/d01-workflow-silent.txt

`SequentialAgent` 照常运行了写报告的一步，报告只依据根 README，验收才发现缺了 member。子 Agent 出了问题，只要它不报错、也不上报，工作流就不知道。（如果这一步干脆不写状态，写报告的 `{member_readme}` 模板会因为缺键而报错，运行也会停下；写成 `{member_readme?}` 或写空字符串，才会这样悄悄往下走。）

`SequentialAgent` 在源码里就是迭代一次的 `LoopAgent`：按顺序运行每个子 Agent，遇到 escalate 就提前结束，子 Agent 的错误会结束整个工作流。

## 4. 自主循环：下一步由模型决定

成员可能变化，读什么只有读了根 README 才知道，这时把读文件交给模型：

<<< @/public/learn-agent-rust/code/pattern-selection/src/main.rs#adaptive

读文件的工具自己检查路径：

<<< @/public/learn-agent-rust/code/pattern-selection/src/main.rs#tools

<<< @/public/learn-agent-rust/outputs/d01-adaptive.txt

模型先读根 README，看到“成员：member, plugin”，再逐个补读，最后写报告：4 次模型调用、3 次读取，验收通过。同样多了一个成员，固定工作流失败了，循环能跟上。

代价是控制权交给了模型，宿主要守住边界：

- `forbidden` 场景里，替身模型读完根 README 后想去读 `../secret.txt`。工具检查路径，返回 `read.outside_workspace`，什么也没读到。替身的规则是遇到工具错误就收手，于是没写出报告，验收 `no_report`；真实模型也许会重试别的路径，每次都会被同样的检查挡住。这里的检查只看路径文字（不许 `..` 和空段），没有处理符号链接，生产代码要先解析成真实路径再比较。
- `budget` 场景把 `max_iterations` 设成 2：读完根 README 和 member 之后，第三次调用模型被框架拒绝，运行以错误结束，验收 `max_iterations`：

<<< @/public/learn-agent-rust/outputs/d01-budget.txt

<<< @/public/learn-agent-rust/outputs/d01-forbidden.txt

工具里的路径检查和 `max_iterations` 都不依赖模型是否“自觉”：前者在每次执行时检查参数，后者在每次请求模型之前检查次数。

![同一个任务的三种结构：单次调用一次请求、资料由用户给全；固定工作流按代码写好的步骤读文件，多出的成员读不到；自主循环由模型按读到的内容补读，路径检查和调用上限由宿主守住。](/learn-agent-rust/figures/d01-pattern-flow.svg)

从左往右对照三列：每列最上面是结构，下面是这种结构的几个场景，各自写着模型调用次数、读了几个文件和验收结果。

## 5. 怎样选

| 输入与步骤 | 先选 | 本章的证据 |
| --- | --- | --- |
| 资料由调用方给全，一次变换就能验收 | 单次调用 | `single` 通过；`single-partial` 缺成员 |
| 步骤事先已知，资料位置固定 | 固定工作流 | `workflow` 通过、只调用一次模型；`workflow-new-member` 缺新成员；`workflow-silent` 不上报就悄悄往下走 |
| 下一步取决于刚读到的内容 | 自主循环，加上工具检查与调用上限 | `adaptive` 通过；`forbidden`、`budget` 被宿主拦住 |

三者可以嵌套：固定工作流里的某一步可以是一个自主循环，自主循环的工具也可以是一个固定工作流。“循环更多”“Agent 更多”都不是改进的证据；只有简单结构在明确的输入上验收失败，才有理由加结构。

### 全部场景的实际结果

<!-- d01-results:start -->

| 场景 | 结构 | 经过的 Agent | 模型调用 | 读过的文件 | 应用验收 |
| --- | --- | --- | --- | --- | --- |
| `single` | `single` | `[writer]` | `1` | `[]` | `accepted` |
| `single-partial` | `single` | `[writer]` | `1` | `[]` | `rejected:missing:member/README.md` |
| `workflow` | `workflow` | `[read_root,read_member,writer]` | `1` | `[README.md,member/README.md]` | `accepted` |
| `workflow-new-member` | `workflow` | `[read_root,read_member,writer]` | `1` | `[README.md,member/README.md]` | `rejected:missing:plugin/README.md` |
| `workflow-missing` | `workflow` | `[read_root,read_member]` | `0` | `[README.md]` | `rejected:escalated` |
| `workflow-silent` | `workflow` | `[read_root,read_member,writer]` | `1` | `[README.md]` | `rejected:missing:member/README.md` |
| `adaptive` | `adaptive` | `[explorer]` | `4` | `[README.md,member/README.md,plugin/README.md]` | `accepted` |
| `forbidden` | `adaptive` | `[explorer]` | `3` | `[README.md]` | `rejected:no_report` |
| `budget` | `adaptive` | `[explorer]` | `2` | `[README.md,member/README.md]` | `rejected:max_iterations` |

<!-- d01-results:end -->

### 与旧版场景的对应 {#old-scenarios}

| 旧版（graph-flow 夹具） | 新版（ADK-Rust） | 变化 |
| --- | --- | --- |
| `single` | `single`、`single-partial` | 新增“输入不全”的对照。 |
| `workflow` | `workflow`、`workflow-new-member` | 固定步骤改为 `SequentialAgent`；新增多出成员的对照。 |
| `adaptive` | `adaptive` | 改为 `LlmAgent` 工具循环，真实读文件。 |
| `missing` | `workflow-missing`、`workflow-silent` | 读不到文件时 escalate，工作流停下；新增不上报的对照。 |
| `forbidden` | `forbidden` | 由工具检查路径，返回错误码。 |
| `budget` | `budget` | 改用 `max_iterations`。 |
| 6 个场景、4 项测试 | 9 个场景、4 项测试 | — |

验证脚本把工程打包后在临时目录解压，在旁边放好 ADK-Rust 源码，运行格式、Clippy、4 项 Rust 测试和离线构建；摘要和几条详细轨迹各连跑两次必须逐字节相同，并把结果表写回正文。维护者在网站仓库根目录执行：

```sh
python3 scripts/fetch-adk-rust.py .cache/adk-rust    # 只需一次；或设 ADK_RUST_SRC
python3 scripts/verify-agent-patterns-adk.py --lesson D01
python3 scripts/generate-learn-agent-rust-figures.py --lesson D01
python3 scripts/verify-agent-patterns-adk.py --lesson D01 --check
```

## 框架替你做了什么、没做什么

| 框架做了 | 仍归应用 |
| --- | --- |
| `SequentialAgent` 按顺序运行子 Agent，遇到 escalate 或错误就停。 | 决定哪一步失败时要 escalate；不 escalate 的失败，工作流不知道。 |
| 子 Agent 写进会话状态的内容，后面的 `LlmAgent` 用 `{键}` 模板读到。 | 决定每一步写什么、后一步读什么。 |
| `LlmAgent` 的工具循环；`max_iterations` 限制模型调用次数。 | 工具里检查参数（例如路径不能跳出工作区）。 |
| — | 验收结果：报告是否覆盖了该覆盖的内容。 |

<!-- adk-refs:start -->

## 在 ADK-Rust 源码里

本章的三种结构，在 ADK-Rust 里分布在这几处：

| 本章内容 | 源码位置 | 对照要点 |
| --- | --- | --- |
| 固定工作流 | [`adk-agent/src/workflow/sequential_agent.rs` · `SequentialAgent`](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-agent/src/workflow/sequential_agent.rs#L11-L13) | 内部就是 `max_iterations(1)` 的 `LoopAgent`：按顺序把每个子 Agent 运行一次 |
| 子 Agent 依次运行与提前结束 | [`adk-agent/src/workflow/loop_agent.rs` 第 680 行](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-agent/src/workflow/loop_agent.rs#L680) | 事件标了 escalate 就在这个子 Agent 之后结束；子 Agent 返回错误则整个工作流以错误结束 |
| 由代码写的一步 | [`adk-agent/src/custom_agent.rs` · `CustomAgent`](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-agent/src/custom_agent.rs#L27-L34) | 不经过模型，自己产出事件；事件上的 `state_delta` 写进会话状态，`escalate` 让外层停下 |
| 后一步读前一步的结果 | [`adk-core/src/instruction_template.rs` · `inject_session_state`](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-core/src/instruction_template.rs#L207-L227) | `{键}` 模板在子 Agent 开始运行时读会话状态 |
| 自主循环的调用上限 | [`adk-agent/src/llm_agent.rs` · `LlmAgentBuilder::max_iterations`](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-agent/src/llm_agent.rs#L1466-L1469) | 限制一次运行里模型调用的次数 |
| 超过上限 | [`adk-agent/src/llm_agent.rs` 第 4466 行](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-agent/src/llm_agent.rs#L4466) | 每次请求模型之前检查次数，超过就以错误结束，不再调用模型 |

源码固定在 ADK-Rust `98515241133d`（3.0.0，2026-11-26，尚未发布到 crates.io）。本节由 `scripts/learn-agent-rust-adk-refs.py` 生成。

<!-- adk-refs:end -->

::: warning 常见误区
- **把调用次数当成能力。** 单次调用最省，前提是输入已经给全；固定工作流省掉的是由模型决定读什么。
- **以为工作流会自己停在失败的步骤。** 子 Agent 不报错、也不上报（escalate），`SequentialAgent` 就继续往下跑（`workflow-silent`）。
- **把模型说“完成”当作完成。** 验收由应用按报告内容判断。
- **以为自主循环天然更好。** 它能跟上变化，也把下一步交给了模型；路径检查和调用上限要由宿主守住。
:::

<!-- transfer-thinking:start -->

## 迁移思考：输入合同决定最小结构

资料已齐全，却仍让循环反复补读，会增加什么？先给出你的判断，再展开下面的推演。

<details><summary>推演与应用</summary>

增加调用与失败位置，却未增加必要信息。先对照输入合同和最终验收，而非把轨迹长短当能力。

在报表生成中，完整表格可以直接转换；未知数据源才需要逐步发现。

</details>

这是一道迁移练习，推演不代表新增实验已通过。对照[全书审查中的证据层次](./course-review.md#evidence-layers)，说明你的判断还需要哪一级证据。

<!-- transfer-thinking:end -->

## 本章结论

先看输入，再决定谁选择下一步。资料由调用方给全，单次调用就够；步骤事先已知，用 `SequentialAgent` 把它们写成代码；下一步取决于刚读到的内容，才把选择交给模型，同时由工具检查参数、由 `max_iterations` 限制次数。三种结构最后都要经过同一个验收。

## 检查理解

1. `single` 和 `single-partial` 都只调用一次模型，为什么一个通过、一个不通过？

   <details><summary>参考答案</summary>

   单次调用只能依据请求里的资料。`single` 的用户贴了两份 README，`single-partial` 只贴了根 README，报告自然缺 member。差别在输入，不在结构。

   </details>

2. `workflow-new-member` 为什么失败？改哪里能让它通过？

   <details><summary>参考答案</summary>

   固定工作流只读代码里写死的两个文件，读不到新成员 plugin。可以在代码里加一步读 plugin（成员变化就要改代码），或者把“按成员列表补读”交给一个自主循环。

   </details>

3. `workflow-missing` 里，写报告的那一步为什么没有运行？如果读文件的步骤不 escalate 会怎样？

   <details><summary>参考答案</summary>

   读不到文件时，那一步把事件标成 escalate，`SequentialAgent` 立刻结束。如果不上报、只写一个空字符串（`workflow-silent`），工作流会照常运行写报告的一步，报告只依据根 README，要靠应用的验收才发现缺了 member。

   </details>

4. `forbidden` 里，模型想读 `../secret.txt`，是谁拦住的？

   <details><summary>参考答案</summary>

   读文件工具自己：每次执行都检查路径，跳出工作区就返回 `read.outside_workspace`，不读任何内容。这一步不依赖模型是否遵守指令。

   </details>

5. 本章的调用次数能证明哪种结构最好吗？

   <details><summary>参考答案</summary>

   不能。三种结构的输入不同，模型是替身。公平比较要在同一任务、同一工具、同一总预算下，用真实模型分别验收，见第 23 章的[模型对照入口](./pattern-composition.md#model-comparison)。

   </details>

## 参考资料

- [Building effective agents](https://www.anthropic.com/research/building-effective-agents)：工作流与 Agent 的划分，以及先用最简单方案的建议。
- [ADK-Rust 固定源码](https://github.com/zavora-ai/adk-rust/tree/98515241133d24f7e41f8fd272649035416a142f)：`SequentialAgent`、`LoopAgent`、`CustomAgent` 的实现。
- [ReAct](https://arxiv.org/abs/2210.03629)：观察、行动与推理交替的研究入口。

下一章：[第 17 章 · 提示链与条件路由](./prompt-chaining-routing.md)。回到[本部分导读](./agent-design-patterns.md)比较模式。
