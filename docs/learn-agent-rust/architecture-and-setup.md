---
title: "第 0 章：整体架构与环境"
description: "沿一次读取 README 的任务，用 ADK-Rust 3.0 看清模型请求、应用策略、工具执行、消息历史、Runner 与会话分别负责什么。"
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
- 沿一次“读取 README”的任务，指出谁提出动作、谁决定能不能做、谁执行、结果交给谁。
- 把模型、工具、Agent、应用策略、Runner 和会话放回同一张架构图，知道它们各在 ADK-Rust 的哪个 crate 里。
- 运行一个 ADK-Rust 接线实验，用正常、拒绝和文件缺失三条路径检查理解。

**前置：** 完成[环境准备](./setup.md)，能在终端运行 `cargo`。结构体、`Arc` 和 `async/await` 只需先看懂用途。

**实践方式：** 下载 <a href="/learn-agent-rust/architecture-and-setup.zip" download>本章 Rust 工程</a>，按[第 2 节](#run-once)取一次 ADK-Rust 源码后运行。不需要模型密钥或数据库。
:::

::: info 本章已迁移到 ADK-Rust 3.0
本章实验基于 ADK-Rust 3.0 的发布候选版本（固定提交，尚未发布到 crates.io）。旧版本章只用标准库手写了一次往返，可从 git 标签 `learn-agent-rust-v1` 取得；旧版的三种模式（正常、拒绝、文件缺失）全部保留。
:::

打开一个陌生项目，你对助手说：

> 读取 README.md，告诉我如何启动项目。

这句话看起来只需要一个回答，却至少藏着三个问题：模型怎样知道文件的内容？谁有权打开文件？文件不存在时，助手应该继续编一个启动方式，还是如实告诉你没有读到？

后面的章节会逐个增加能力。第 0 章先把一次最短的往返走完：看见请求、看见执行、看见结果怎样回到上下文，再把每一段对上全书的架构位置。暂时不需要记住所有 trait 和 API。

<LearnAgentRustMap active="architecture-and-setup" />

<!-- experiment-library:start -->

全书实验可从[统一代码库](./experiments.md#architecture-and-setup)下载；解压后进入 `chapters/architecture-and-setup/`，或在代码库根目录运行 `python3 run.py run R00`。

<!-- experiment-library:end -->

## 1. 模型说“读取文件”，文件就被读取了吗？

先猜一下：模型返回 `read_file("README.md")` 时，文件是否已经打开？

还没有。这里的 `read_file` 是应用提供的工具名称，`README.md` 是参数。模型返回的是一个行动请求。程序需要识别请求，检查是否允许，找到对应的执行函数，再让操作系统读取文件。

![用户目标先变成模型提出的工具请求，应用检查策略后由工具读取文件，再把文件内容或错误送回模型。](/learn-agent-rust/figures/r00-request-and-action.svg)

怎么读这张图：左边是“提出动作”，右边是“执行动作”。从左到右跨过的这一步，是应用程序必须负责的边界。下面的回路同样重要：工具结果回到消息历史，模型才获得刚才没有的事实。

因此，先把一件事分清：<strong>工具调用请求是一份待执行的说明，工具结果才是执行之后获得的观察。</strong>即使两者都装在同一种消息结构里，它们的来源和作用也不同。

<details><summary>对照参考课程：原始循环图</summary>

![参考课程在调用模型、执行工具与回传结果之间循环，直到模型结束本轮。](/learn-agent-rust/figures/upstream/r01-agent-loop.svg)

原图保留了参考课程的 Claude 接口与 `stop_reason` 语境。沿“请求模型 → 检查是否需要工具 → 执行 → 回传”的箭头阅读即可。[原始章节](https://learn.shareai.run/zh/s01/) · [原图与许可说明](./architecture.md#reference-assets)。

</details>

## 2. 先把一次往返跑起来 {#run-once}

本章用 ADK-Rust 自带的 `ScriptedLlm` 代替外部模型：它按预先写好的脚本逐条回复，第一次请求读取，第二次给出回答。这样每次运行都走到相同的位置，方便检查接线。

::: info 本章代码从哪里来
所有 Rust 代码只维护在<a href="/learn-agent-rust/code/architecture-and-setup/src/main.rs" download>完整源码</a>里，正文片段从这个文件直接导入。运行时请下载<a href="/learn-agent-rust/architecture-and-setup.zip" download>本章工程</a>。程序不读取模型凭据，不访问外部服务。
:::

ADK-Rust 3.0 还没有发布到 crates.io。工程里的 `.cargo/config.toml` 把 ADK 依赖指向本目录旁边的 `adk-rust/`，所以先取一次固定提交的源码（需要 git 与 GitHub 访问，不行时加 `--method cdn`），再运行：

```sh
cd architecture-and-setup
python3 fetch-adk-rust.py ../adk-rust
cargo run --locked
```

cargo 只读取当前目录及上级目录里的 `.cargo/config.toml`，所以命令要在工程目录里运行。编译时会看到 adk-core 的 3 条弃用警告（上游固定 Rust 1.95.0），不影响运行和检查。程序会在自己的临时目录创建一份练习 README，结束时清理；它读取的是这份练习文件，文件里的 `cargo run` 只是被读取的文本，程序不会执行它。

下面是实际运行输出：

<<< @/public/learn-agent-rust/outputs/r00-normal.txt

先看四行轨迹：模型的工具请求（`call`）与工具结果（`result`）共享同一个调用 ID；结果之后才是交给用户的回答（`text`）。再看两行 `request`：这是模型实际收到的两次请求里每条消息的角色。第一次只有 `system`（Agent 的指令）和 `user`（问题）；第二次多了 `model`（模型自己提出的调用）和 `function`（工具结果）。

**验证记录：** 本章输出与后面的计数图来自 Linux / aarch64、Rust 1.99.1 下的实际运行。正常读取、策略拒绝和文件缺失分别验证；没有请求真实模型服务。

## 3. 消息历史怎样长出来

刚收到问题时，会话里只有用户的那一句话。模型提出工具请求后，历史增加一条；读取结束后，再加入一条工具结果；最后才加入回答。统计里的 `session_events=4` 就是这四条。

![会话里依次出现用户问题、模型请求、工具结果和模型回答；对照场景显示拒绝读取时工具没有尝试读取文件。](/learn-agent-rust/figures/r00-message-trace.svg)

怎么读这张图：上半部按发生顺序排列消息，下半部来自同一份程序的三次运行。先沿消息往下走，再比较“读取尝试”和“读取成功”：发出工具请求，并不保证真的尝试读取，更不保证读取成功。

<strong>这一次变得更多的是上下文，而不是模型参数。</strong>本章没有训练步骤。第二次请求里多出来的 `model`、`function` 两条，就是新增的上下文；换成真实模型时，框架同样把它们组装进下一次请求。

这些消息在 ADK-Rust 里用 `Content` 和 `Part` 表示：模型的调用是 `FunctionCall`，工具结果是 `FunctionResponse`，回答是 `Text`。[第 1 章](./agent-loop.md)会逐一拆开。

## 4. ADK-Rust 的各部分放在哪里？

现在已经看到一次接线，才需要给整套程序分工。

![应用的策略与验收在最外层；Runner 管理会话并装入策略和预算；LlmAgent 与图运行模型和工具的循环，在行动前检查策略和预算；Llm trait 连接模型提供方，FunctionTool 操作限定工作区，会话与账本由 adk-session 保存。](/learn-agent-rust/figures/runtime-architecture.svg)

怎么读这张图：从上往下是一次请求经过的层次，向右是跨出进程或跨到存储的边界。本图是全书逐步搭建的目标结构；本章只用到其中一部分：脚本模型、一个工具、允许或拒绝的策略、内存会话。

本章的组装代码就是这张图的缩影：

<<< @/public/learn-agent-rust/code/architecture-and-setup/src/main.rs#wiring

| 一次往返里的工作 | 谁负责 | 在哪个 crate | 本章看到了什么 |
| --- | --- | --- | --- |
| 接收问题、决定允许哪些动作、判断任务是否完成 | 应用 | 你自己的代码 + `adk-core` 的策略类型 | `DeclarativePolicy` 允许或拒绝 `read_file`；`outcome` 由应用计算 |
| 向模型传入消息，接收回复 | 模型 | `adk-core` 的 `Llm` trait；`adk-model` 提供实现 | `ScriptedLlm` 按脚本回复 |
| 运行“模型 → 工具 → 模型”的循环，行动前检查策略与预算 | Agent | `adk-agent` 的 `LlmAgent` | 两次模型调用夹着一次工具执行 |
| 执行工具、校验参数 | 工具 | `adk-tool` 的 `FunctionTool` | `read_file` 读取临时目录 |
| 加载会话、装入策略与预算、逐条保存事件 | Runner | `adk-runner` | `Runner::builder()…build()` |
| 保存会话事件 | 会话服务 | `adk-session` | `InMemorySessionService`，只在内存里 |
| 调度多个 Agent 或业务步骤 | 图 | `adk-graph` | 本章不用，[第 2 章](./tools-and-graph.md)起使用 |

### 一次调用会跨过哪些边界？

`Runner`、`LlmAgent`、`ScriptedLlm`、`FunctionTool` 之间都是同一个 Rust 进程里的方法调用。工具处理函数里的 `std::fs::read_to_string` 才访问操作系统文件系统。

改用远端模型时，模型客户端会通过 HTTP 发送组装好的请求；远端模型看到的是被发送的内容，不会仅凭一个本地路径就获得文件读取能力。会话换成 SQLite 或 PostgreSQL 时，保存操作又跨到文件或独立的数据库进程。方法调用、模型网络请求、文件访问与数据库保存，需要分别观察。

## 5. 文件读不到时，应该发生什么？

成功路径容易让人忽略策略和错误。先猜两个结果：如果应用拒绝读取，文件读取次数应该是多少？如果文件不存在，助手应该回答什么？

工具的处理函数：

<<< @/public/learn-agent-rust/code/architecture-and-setup/src/main.rs#tool

处理函数先检查路径，再计一次读取尝试，最后读取文件。成功和失败都产生一条结果，交回同一条消息路径。

### 实验 A：应用拒绝读取

```sh
cargo run --locked -- --deny
```

<<< @/public/learn-agent-rust/outputs/r00-deny.txt

模型照样提出了请求，结果却是 `status=refused`：策略装在 Runner 上（`DeclarativePolicy` 本来就是“没有规则命中就拒绝”，代码里那条 `.deny` 规则只是为了写明拒绝理由），`LlmAgent` 在执行工具之前检查它，这次调用被拒绝，没有到达工具。`refused` 这个状态就是证据；`read_attempts=0` 与它一致（单看计数不够，因为处理函数里路径检查失败时计数也是 0）。拒绝的原因作为工具结果交回模型，模型据此报告未完成。完整的允许、拒绝与审批规则在 [第 3 章](./permissions.md)展开。

### 实验 B：练习目录里没有 README

```sh
cargo run --locked -- --missing-file
```

<<< @/public/learn-agent-rust/outputs/r00-missing-file.txt

此时 `read_attempts=1`，`read_successes=0`。程序确实尝试了读取，文件不存在，工具以 `file.missing` 失败，最后的回答保留了这个事实。结果里写的是 `tool.not_found (file.missing)`：前半段是错误类别（文件找不到属于 `NotFound`），括号里是工具自己给的错误码；它和“工具不存在”是两回事，后者是框架在执行前给的 `not_run`（第 1 章 `unknown-tool`）。

三种模式的程序都以退出码 0 结束，但任务结果分别是 `completed`、`denied` 与 `missing_file`。判断助手有没有完成任务，要看任务结果和观察，不能只看进程退出码，也不能只看模型有没有给出回答。

## 6. 消息在内存里，退出后还能继续吗？

把会话交给一个服务对象，能让代码更清楚，却没有自动获得恢复能力。

![消息历史记录看过的内容，运行状态记录控制进度，持久化检查点保存恢复所需的信息；本章的内存会话会随进程结束而丢失。](/learn-agent-rust/figures/r00-state-lifetimes.svg)

怎么读这张图：上面三列回答不同的问题；横线表示进程结束。左边两列在本章都只放在内存。右边是后续课程要实现和验证的保存边界。

| 概念 | 回答什么问题 | 本章对应 |
| --- | --- | --- |
| 消息历史 | 用户、模型和工具已经交换了什么？ | 会话里的四条事件 |
| 运行控制状态 | 调用了几次？能否继续？是否允许动作？ | 策略、读取计数；预算在[第 1 章](./agent-loop.md) |
| 图的执行位置 | 哪个图、当前处于哪个节点？ | 尚未使用；[第 5–7 章](./graph-orchestration.md) |
| 持久化检查点 | 退出后，凭什么恢复到一个明确位置？ | 尚未保存；[第 6 章](./graph-pause-resume.md)与[专题 1](./postgres-checkpoints.md) |
| 长期记忆 | 换一个会话后，仍应召回哪些事实？ | 后续 [第 13 章](./memory.md) |

本章用的是 `InMemorySessionService`，每次运行都新建会话，再次运行会从第一条用户消息开始。ADK-Rust 还提供 SQLite、PostgreSQL 等会话服务，但换一个服务名不等于获得恢复能力：要核对保存到了哪里、保存是否成功、恢复时读回哪些内容，这些实验放到后面的章节。

## 7. 画成图，就成了 Agent 吗？

假设一段程序总是“读取 README → 抽取启动命令 → 返回结果”，它已经能完成当前任务。但下一次用户说“搜索日志，找出启动失败原因”时，这条固定路径就不够用了。

Agent 循环要让模型参与选择下一步：继续请求一个工具，还是给出最终回答。框架负责解释这种选择、执行工具，并在有上限的循环中推进；应用负责决定哪些动作允许做、任务算不算完成。

![上方为固定流程，下方为 Agent 循环：LlmAgent 根据模型的结构化回复决定是否执行工具，策略检查执行条件。](/learn-agent-rust/figures/r00-workflow-and-agent.svg)

怎么读这张图：上面每次经过同一条路线；下面模型结果会影响下一步，工具执行后又回到上下文。图可以承载这两种程序。是不是具有模型参与的行动选择，要看节点做了什么、分支依据是什么。

本章的脚本只走一次往返。下一章会让循环真正有选择和上限，并用更多输入检查调用与结果的配对。

## 框架替你做了什么、没做什么

| 框架做了 | 仍归应用 |
| --- | --- |
| 把模型的工具请求交给对应的工具，结果带原调用 ID 交回模型。 | 提供工具，并在处理函数里检查参数取值（本章只允许 `README.md`）。 |
| 在执行工具之前检查装在 Runner 上的策略，被拒绝的调用得到 `refused` 结果。 | 决定策略内容：允许什么、拒绝什么。 |
| 逐条保存会话事件，下一次请求自动带上历史（3.0 默认会在接近上下文窗口时自动压缩，本章关掉了）。 | 选择会话放在哪里（内存还是数据库），并验证恢复。 |
| — | 判断任务是否完成：本章的 `outcome` 由应用根据读取计数、工具结果的状态和回答计算。 |

<!-- adk-refs:start -->

## 在 ADK-Rust 源码里

本章接线用到的几个部件，在 ADK-Rust 里的位置：

| 本章内容 | 源码位置 | 对照要点 |
| --- | --- | --- |
| 脚本模型 | [`adk-model/src/scripted.rs` 第 302 行](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-model/src/scripted.rs#L302) | 每次调用模型时先记下收到的请求，再取出下一条预先写好的回复；脚本用完就报错 |
| 工具 | [`adk-tool/src/function_tool.rs` · `FunctionTool::new`](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-tool/src/function_tool.rs#L59-L79) | 名字、说明和处理函数组成一个工具 |
| Agent | [`adk-agent/src/llm_agent.rs` · `LlmAgentBuilder::build`](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-agent/src/llm_agent.rs#L1940-L2033) | 把模型、指令和工具组装成 `LlmAgent` |
| 应用策略 | [`adk-core/src/policy.rs` · `DeclarativePolicy`](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-core/src/policy.rs#L740-L744) | 规则按顺序匹配，第一条命中的规则决定允许、拒绝还是等待审批；都不命中就拒绝（见结构体上方的说明） |
| 内存会话 | [`adk-session/src/inmemory.rs` · `InMemorySessionService`](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-session/src/inmemory.rs#L37-L41) | 会话事件只放在进程内存里 |
| 运行入口 | [`adk-runner/src/runner.rs` · `Runner::run_with_config`](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-runner/src/runner.rs#L989-L1000) | 加载会话、运行 Agent、逐条保存事件 |

源码固定在 ADK-Rust `98515241133d`（3.0.0，2026-11-26，尚未发布到 crates.io）。本节由 `scripts/learn-agent-rust-adk-refs.py` 生成。

<!-- adk-refs:end -->

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

一次最短的任务可以拆成：**用户提出目标 → 模型请求工具 → 应用策略允许 → 工具执行 → 结果进入历史 → 模型生成回答**。在 ADK-Rust 里，模型、工具、Agent、Runner、会话分别承接其中一段，应用握着策略和验收。

本章先用脚本模型和确定的练习文件把边界看清。后续沿同一条数据流，逐步加上循环上限、更多工具、图、权限、上下文、任务和恢复。每增加一层，都要能指出输入、输出、状态和失败位置。

::: warning 常见误区
- 工具请求中出现了文件名，不表示文件已经读取；策略检查与执行发生在请求之后。
- 脚本模型通过，证明的是本例接线与失败分支；真实模型的工具协议需要单独验证。
- 本例只访问自己创建的练习文件；一条允许或拒绝的策略并不是通用文件系统沙箱。
- 会话交给一个服务对象、画出图节点，都不会自动产生持久化或跨进程恢复能力。
:::

## 检查理解

1. 轨迹里有一行 `call` 和一行 `text`，它们分别是模型在做什么？

   <details><summary>参考答案</summary>

   `call` 是模型第一次回复：请求读取文件；`text` 是第二次回复：根据工具结果形成回答。中间的文件读取由工具的处理函数完成；本例的两次模型回复都来自固定脚本。

   </details>

2. `--deny` 时，为什么还会有一条 `result`？

   <details><summary>参考答案</summary>

   它把拒绝执行的原因交回模型。工具结果表达的是一次请求的观察，可以是内容、拒绝或错误。状态 `refused` 说明调用在到达工具之前被拒绝（本章里是策略；护栏、审批人拒绝也会给出这个状态），`read_attempts=0` 与此一致。

   </details>

3. 把 `InMemorySessionService` 换成一个叫 `SqliteSessionService` 的服务，再启动程序，就能继续上次的消息吗？

   <details><summary>参考答案</summary>

   不一定。要确认会话真的写进了文件、下次启动用的是同一个会话 ID、恢复时读回了哪些事件，并用独立进程的实验验证。改名或换服务本身不改变“能不能恢复”这个事实。

   </details>

4. 后续把 `ScriptedLlm` 换成真实模型客户端，工具读取代码需要搬到远端吗？

   <details><summary>参考答案</summary>

   不需要。客户端通过网络发送消息与工具描述，收到结构化的调用请求；框架在本地执行工具，再把结果组装进下一次请求。模型服务与本地文件系统是两个边界。

   </details>

5. 一个图只有“读取 README”和“整理输出”两个固定节点，是否已经验证了模型自主选择工具？

   <details><summary>参考答案</summary>

   它验证的是固定工作流。要检查模型参与的选择，需要观察模型返回的结构化回复怎样影响下一步，并验证工具请求、最终回答与停止条件等分支。

   </details>

## 参考资料

- [环境准备与基础自检](./setup.md)；[课程架构与框架分工](./architecture.md)。
- ADK-Rust（固定提交）：[仓库 README](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/README.md)、[Runner](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-runner/README.md)、[稳定度分层](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/STABILITY.md)。
- [Learn Claude Code：Agent 循环](https://learn.shareai.run/zh/s01/)；参考原图的[来源与许可](./architecture.md#reference-assets)。

下一章预告：[第 1 章 · 最小 Agent 循环](./agent-loop.md)，看清循环的每一步，并给它加上预算与停止条件。也可以回到[学习路径](./learning-path.md)查看后续能力的位置。
