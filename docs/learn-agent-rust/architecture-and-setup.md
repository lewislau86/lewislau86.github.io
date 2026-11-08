---
title: "第 0 章：整体架构与环境"
description: "沿一次读取 README 的任务，看清模型请求、工具执行、消息历史、图调度与存储分别负责什么。"
pageClass: learn-agent-rust-course
prev:
  text: 环境准备
  link: /learn-agent-rust/setup
next:
  text: 第 1 章 · 最小 Agent 循环
  link: /learn-agent-rust/agent-loop
---

# 第 0 章：整体架构与环境

[课程总览](./index.md) · [环境准备](./setup.md) · [下一章预告：最小 Agent 循环](./agent-loop.md)

::: tip 本章学习目标
- 沿一次“读取 README”的任务，指出谁提出动作、谁执行动作、结果交给谁。
- 把模型接口、工具、消息、应用策略、图执行器和存储放回同一张架构图。
- 运行一个 Rust 接线实验，用正常、拒绝和文件缺失三条路径检查理解。

**前置：** 完成[环境准备](./setup.md)，能在终端运行 Rust 编译器。结构体、`Vec` 和 `Result` 只需先看懂用途。

**实践方式：** 下载完整的 <a href="/learn-agent-rust/code/architecture-and-setup.rs" download>architecture-and-setup.rs</a>。本章只用 Rust 标准库，不需要模型密钥、数据库或第三方 crate。
:::

打开一个陌生项目，你对助手说：

> 读取 README.md，告诉我如何启动项目。

这句话看起来只需要一个回答，却至少藏着三个问题：模型怎样知道文件的内容？谁有权打开文件？文件不存在时，助手应该继续编一个启动方式，还是如实告诉你没有读到？

后面的章节会逐个增加能力。第 0 章先把一次最短的往返走完：看见请求、看见执行、看见结果怎样回到上下文，再把每一段对上全书的架构位置。暂时不需要记住所有 trait 和框架 API。

<LearnAgentRustMap active="architecture-and-setup" />

<!-- experiment-library:start -->

全书实验可从[统一代码库](./experiments.md#architecture-and-setup)下载；解压后进入 `chapters/architecture-and-setup/`，或在代码库根目录运行 `python3 run.py run R00`。

<!-- experiment-library:end -->

## 1. 模型说“读取文件”，文件就被读取了吗？

先猜一下：模型返回 `read_file("README.md")` 时，文件是否已经打开？

还没有。这里的 `read_file` 是应用提供的工具名称，`README.md` 是参数。模型返回的是一个行动请求。程序需要识别请求，检查是否允许，找到对应的执行函数，再让操作系统读取文件。

![用户目标先变成模型提出的工具请求，应用检查并执行读取，再把文件内容或错误送回模型。](/learn-agent-rust/figures/r00-request-and-action.svg)

怎么读这张图：左边是“提出动作”，右边是“执行动作”。从左到右跨过的这一步，就是应用程序必须负责的边界。下面的回路同样重要：工具结果回到消息历史，模型才获得刚才没有的事实。

因此，先把一件事分清：<strong>工具调用请求是一份待执行的说明，工具结果才是执行之后获得的观察。</strong>即使两者都装在一段 JSON 里，它们的来源和作用也不同。

<details><summary>对照参考课程：原始循环图</summary>

![参考课程在调用模型、执行工具与回传结果之间循环，直到模型结束本轮。](/learn-agent-rust/figures/upstream/r01-agent-loop.svg)

原图保留了参考课程的 Claude 接口与 `stop_reason` 语境。沿“请求模型 → 检查是否需要工具 → 执行 → 回传”的箭头阅读即可。Rust 版的内部类型与循环停止条件会逐步实现。[原始章节](https://learn.shareai.run/zh/s01/) · [原图与许可说明](./architecture.md#reference-assets)。

</details>

## 2. 先把一次往返跑起来

本章用一个**脚本模型**代替外部模型：第一次按固定规则提出读取请求，第二次从工具结果中寻找“启动命令”这一行。这样每次运行都能走到相同的位置，方便检查接线。

::: info 本章代码从哪里来
所有 Rust 代码只维护在 <a href="/learn-agent-rust/code/architecture-and-setup.rs" download>architecture-and-setup.rs</a>。正文片段从这个文件直接导入，运行时请下载完整文件。本章的模型响应由普通 Rust 函数生成，尚未调用 `langchain-rust`、`graph-flow` 或外部模型服务。
:::

在保存源码的目录执行：

```sh
rustc --edition=2024 architecture-and-setup.rs -o agent-r00
./agent-r00
```

程序会在自己的临时目录创建一份练习 README，结束时清理目录。它读取的是这份练习文件，不会寻找你当前项目的 README；文件里的 `cargo run` 仅作为被读取的文本，程序不会执行它。

下面是实际运行输出：

<<< @/public/learn-agent-rust/outputs/r00-normal.txt

先看中间的四条消息，最后再看统计。用户问题排在最前；模型的工具请求与工具结果共享 `read-1`；最后一条才是交给用户的回答。

这里的 `assistant` 表示模型侧的消息，`tool` 表示程序执行工具后填入的消息。调用 ID 的作用是把“这次请求”和“这次结果”对应起来。本章使用内部结构体表达关系，具体服务的 HTTP 消息格式留到后续协议实验。

**验证记录：** 本章输出与后面的计数图来自 macOS arm64、Rust 1.99.1 下的实际运行。正常读取、策略拒绝和文件缺失分别验证；没有请求真实模型服务。

## 3. 消息历史怎样长出来

刚收到问题时，消息历史里只有用户的那一句话。模型提出工具请求后，历史增加一条；读取结束后，再加入一条工具结果；最后才加入回答。

![真实运行记录包含 user、assistant 工具请求、tool 结果和 assistant 回答；对照场景显示拒绝读取时没有调用文件读取函数。](/learn-agent-rust/figures/r00-message-trace.svg)

怎么读这张图：上半部按发生顺序排列消息，下半部来自同一份程序的三次运行。先沿消息往下走，再比较“读取尝试”和“读取成功”：发出工具请求，并不保证应用真的尝试读取，更不保证读取成功。

程序怎样记住这些东西？本章先用几个小结构体：

<<< @/public/learn-agent-rust/code/architecture-and-setup.rs#messages

`Message` 保存“谁说了什么”；`ToolCall` 保存一个待执行请求；`RunState` 把消息与运行计数放在一起。这里的 `role`、`content` 和调用 ID 是教学用内部表示，还不是对某个供应商协议的完整实现。

再看把它们接起来的函数。现在不必逐行理解 Rust，按四次 `messages.push` 读下去即可：

<<< @/public/learn-agent-rust/code/architecture-and-setup.rs#wiring

中间有一个值得停下来的细节：`scripted_request` 返回请求后，程序先把请求记入历史，再执行工具，随后把结果记入历史。第二次脚本模型调用收到的就是增长后的消息列表。

<strong>这一次变得更多的是上下文，而不是模型参数。</strong>本章没有训练步骤。后续换成真实模型时，程序依然需要把新增的观察组装成下一轮请求。

<details><summary>脚本模型究竟怎样生成这两次响应？</summary>

<<< @/public/learn-agent-rust/code/architecture-and-setup.rs#model

第一次响应固定返回 `read_file`。第二次用 `strip_prefix` 寻找“启动命令”，找不到就报告任务未完成。这段规则只是为观察数据流提供确定的输入输出；它没有语言理解能力，也没有验证真实模型会正确选择工具。

</details>

## 4. `langchain-rust` 和 `graph-flow` 放在哪里？

现在已经看到一次接线，才需要给整套程序分工。

随着工具增多、任务变长，入口不能一直包揽所有事情。我们会把“调用模型”和“执行工具”拆成明确的步骤，让应用策略判断能否执行，让图调度选择接下来运行哪个步骤，再让存储保存恢复所需的状态。

![课程目标架构中，应用策略与 graph-flow 推进应用节点；langchain-rust 连接模型，工具执行器访问工作区，会话存储单独保存状态。](/learn-agent-rust/figures/runtime-architecture.svg)

怎么读这张图：先沿中间的应用节点往下看模型接口与工具，再看右边的工作区和存储。本图是课程逐步搭建的目标结构。当前小实验是同步的标准库程序；图中的 Tokio、两库适配和会话保存将在后续工程中接入。

| 一次往返里的工作 | 谁负责 | 本章看到了什么 |
| --- | --- | --- |
| 接收问题、选择允许的能力 | 应用入口与策略 | `main` 选择实验模式，读取前检查策略。 |
| 向模型传入消息，接收响应 | 模型适配层；后续接 `langchain-rust` | 两个脚本函数提供固定的响应。 |
| 把结构化工具请求交给执行函数 | 应用自己的消息与工具适配 | `ToolCall`、调用 ID 和 `execute_read`。 |
| 执行当前节点、选择后继节点 | 后续由 `graph-flow` 承载图路由 | 本章在 `run` 里显式写出顺序。 |
| 保存消息、控制状态与恢复位置 | 应用状态及相应存储实现 | 当前只有进程内的 `RunState`。 |

两库通过应用编写的节点连接。一个节点可以调用 `langchain-rust` 的模型接口，另一个节点可以调用工具执行函数；`graph-flow` 负责推进这些节点。对照固定源码，可以先认出几个位置：

| 位置 | 固定源码入口 | 先看什么 |
| --- | --- | --- |
| 模型接口 | [`LLM::generate`](https://github.com/Abraxas-365/langchain-rust/blob/5fc3f5aca4380da48829f95d6e2fd0217b1f2013/src/language_models/llm.rs) | 输入消息列表，返回模型调用结果。 |
| 模型结果 | [`GenerateResult`](https://github.com/Abraxas-365/langchain-rust/blob/5fc3f5aca4380da48829f95d6e2fd0217b1f2013/src/language_models/mod.rs) | 文本与结构化 `tool_calls` 如何表达。 |
| 图节点 | [`Task` / `TaskResult`](https://github.com/a-agmon/rs-graph-llm/blob/9bbca193f20a8c4ba23289621549ecb3d35fee64/graph-flow/src/task.rs) | 节点运行后怎样说明下一步。 |
| 图推进与保存 | [`FlowRunner::run`](https://github.com/a-agmon/rs-graph-llm/blob/9bbca193f20a8c4ba23289621549ecb3d35fee64/graph-flow/src/runner.rs) | 读取会话、执行当前步骤，再保存更新后的状态。 |

这些入口来自课程设计所固定的源码版本，是后续接线的阅读位置。本章实验只编译上面的标准库程序，两库联合编译与工具协议由 R01–R02 的工程另行验证。

### 一次调用会跨过哪些边界？

`run → scripted_request`、`run → execute_read` 都是当前 Rust 进程内的函数调用。`execute_read → std::fs::read_to_string` 才访问操作系统文件系统。

后续改用远端模型时，模型客户端会通过 HTTP 发送组装好的请求；远端模型看到的是被发送的内容，不会仅凭一个本地路径就获得文件读取能力。接入 PostgreSQL 时，保存操作又跨到独立的数据库进程。两库之间的方法调用、模型网络请求、文件访问与数据库保存，需要分别观察。

## 5. 文件读不到时，应该发生什么？

成功路径容易让人忽略策略和错误。现在先猜两个结果：如果应用拒绝读取，文件读取次数应该是多少？如果文件不存在，助手应该回答什么？

本章工具的执行入口如下：

<<< @/public/learn-agent-rust/code/architecture-and-setup.rs#tool

顺序很直接：先检查策略，再计一次读取尝试，最后读取文件。读取成功与读取失败分别产生观察，交回同一条消息路径。

### 实验 A：应用拒绝读取

```sh
./agent-r00 --deny
```

<<< @/public/learn-agent-rust/outputs/r00-deny.txt

这里仍有模型提出的请求，工具结果却是“拒绝”。重点核对 `read_attempts=0`：程序在文件读取前停止了动作，然后把拒绝原因交给脚本模型。这里验证的只是本例的读取开关；完整审批与工作区权限留到 [R03](./permissions.md)。

### 实验 B：练习目录里没有 README

```sh
./agent-r00 --missing-file
```

<<< @/public/learn-agent-rust/outputs/r00-missing-file.txt

此时 `read_attempts=1`，`read_successes=0`。程序确实尝试了读取，操作系统报告文件不存在，最后的回答保留了这个事实。

三种模式的演示程序都能正常结束，但任务结果分别是 `completed`、`denied` 与 `missing_file`。判断助手有没有完成任务，要查看任务结果和观察，不能只看进程退出码。

## 6. 消息在内存里，退出后还能继续吗？

把所有东西放进一个结构体，能让代码更容易传参，却没有自动获得恢复能力。

![消息历史记录看过的内容，运行状态记录控制进度，持久化检查点保存恢复所需的信息；本章的内存状态会随进程结束而丢失。](/learn-agent-rust/figures/r00-state-lifetimes.svg)

怎么读这张图：上面三列回答不同的问题；横线表示进程结束。左边两列在本章都只放在内存。右边是后续课程要实现和验证的保存边界，当前没有执行。

| 概念 | 回答什么问题 | 本章对应 |
| --- | --- | --- |
| 消息历史 | 用户、模型和工具已经交换了什么？ | `messages` 里的四条消息。 |
| 运行控制状态 | 调用了几轮？能否继续？是否允许动作？ | 模型轮数、读取计数与读取开关。 |
| 图会话 | 哪个图、哪个会话，当前处于哪个节点？ | 尚未接入；后续映射到图执行器。 |
| 持久化检查点 | 退出后，凭什么恢复到一个明确位置？ | 尚未保存，需要存储、版本与恢复规则。 |
| 长期记忆 | 换一个会话后，仍应召回哪些事实？ | 后续 [R09](./memory.md)单独设计。 |

本章每次运行都新建练习环境与消息历史。再次运行会从第一条用户消息开始。即使未来调用一个叫 `save` 的方法，也需要核对它保存到了哪里、保存是否成功，以及恢复时读回哪些内容；这些实验放到检查点专题继续展开。

## 7. 画成图，就成了 Agent 吗？

假设一段程序总是“读取 README → 抽取启动命令 → 返回结果”，它已经能完成当前任务。但下一次用户说“搜索日志，找出启动失败原因”时，这条固定路径就不够用了。

Agent 循环要让模型参与选择下一步：继续请求一个工具，还是给出最终回答。程序负责解释这种选择，检查执行条件，并在有上限的循环中推进。

![固定工作流按预先指定的动作前进；目标 Agent 循环根据模型返回的工具请求或最终回答分支，工具结果会追加回上下文。](/learn-agent-rust/figures/r00-workflow-and-agent.svg)

怎么读这张图：上面每次经过同一条路线；下面模型结果会影响路由，工具执行后又回到上下文。图执行器可以承载这两种程序。是不是具有模型参与的行动选择，要看节点做了什么、分支依据是什么。

本章 `run` 把两次模型响应与一次读取显式接在一起，属于固定的教学路线。下一章才会把这段接线变成真正有停止条件的循环，并用更多输入检查消息与工具契约。之后再把同一行为映射到图节点，方便对照显式循环与框架执行。

<!-- transfer-thinking:start -->

## 迁移思考：接线正确与推理有效

把脚本模型换成总说“读到了”的模型，工具往返还能算完成吗？先给出你的判断，再展开下面的推演。

<details><summary>推演与应用</summary>

核对真实 read_file 调用、对应结果与最终引用。没有读取证据时，只能确认模型返回了文字。

换成客服系统后，同样要把“口头承诺”与真实订单查询分开。

</details>

这是一道迁移练习，推演不代表新增实验已通过。对照[全书审查中的证据层次](./course-review.md#evidence-layers)，说明你的判断还需要哪一级证据。

<!-- transfer-thinking:end -->

## 本章结论：先看清往返，再增加能力

一次最短的任务可以拆成：**用户提出目标 → 模型请求工具 → 应用检查并执行 → 结果进入历史 → 模型生成回答**。模型接口、应用策略、工具执行、图调度与存储分别承接其中一段工作。

本章先用同步 Rust 函数和确定的练习文件把边界看清。后续沿同一条数据流，逐步替换模型、增加循环与图节点，再加入权限、上下文、任务和恢复。每增加一层，都要能指出输入、输出、状态和失败位置。

::: warning 常见误区
- 工具请求中出现了文件名，不表示文件已经读取；应用检查与执行发生在请求之后。
- 脚本模型通过，证明的是本例接线与失败分支；真实模型的工具协议需要单独验证。
- 本例只访问自己创建的练习文件；一个读取开关并不是通用文件系统沙箱。
- 消息写进 `Vec`、画出图节点，都不会自动产生持久化或跨进程恢复能力。
:::

## 检查理解

1. 输出中有两个 `assistant`，它们分别做了什么？

   <details><summary>参考答案</summary>

   第一个提出 `read_file` 请求，第二个根据工具观察形成回答。中间的文件读取由应用工具函数完成；本例的两次模型响应都由固定规则生成。

   </details>

2. `--deny` 时，为什么还保留一条 `tool` 消息？

   <details><summary>参考答案</summary>

   它把应用拒绝执行的原因传回模型。工具消息表达的是一次请求的观察结果，可以是内容、拒绝或错误。读取尝试为零，说明拒绝发生在读取前。

   </details>

3. 把 `RunState` 改名为 `Session`，再启动程序，能否继续上次的消息？

   <details><summary>参考答案</summary>

   改名不会改变状态的生命周期。本例没有保存和加载状态，再次运行会从头开始。恢复需要明确的存储、恢复位置和状态契约，并通过独立进程实验验证。

   </details>

4. 后续将 `scripted_request` 换成真实模型客户端，工具读取代码需要搬到远端吗？

   <details><summary>参考答案</summary>

   可以继续在本地执行。客户端通过网络发送消息与工具描述，收到结构化请求；应用检查并执行本地工具，再把结果组装进下一次请求。模型服务与本地文件系统是两个边界。

   </details>

5. 一个图只有“读取 README”和“整理输出”两个固定节点，是否已经验证了模型自主选择工具？

   <details><summary>参考答案</summary>

   它验证的是固定工作流。要检查模型参与的选择，需要观察模型返回的结构化结果怎样影响路由，并验证工具请求、最终回答与停止条件等分支。

   </details>

## 参考资料

- [环境准备与基础自检](./setup.md)；[课程架构与框架分工](./architecture.md)。
- [Rust：结构体](https://doc.rust-lang.org/book/ch05-01-defining-structs.html)、[`Vec`](https://doc.rust-lang.org/std/vec/struct.Vec.html) 与 [`std::fs::read_to_string`](https://doc.rust-lang.org/std/fs/fn.read_to_string.html)。
- 模型与图节点的固定源码入口见本章第 4 节；正式工程的联合验证将随章节提供。
- [Learn Claude Code：Agent 循环](https://learn.shareai.run/zh/s01/)；参考原图的[来源与许可](./architecture.md#reference-assets)。

下一章预告：[第 1 章 · 最小 Agent 循环](./agent-loop.md)，把本章固定的接线改成有预算与停止条件的循环。当前也可以回到[学习路径](./learning-path.md)查看后续能力的位置。
