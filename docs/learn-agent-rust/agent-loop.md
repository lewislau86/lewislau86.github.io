---
title: "第 1 章：最小 Agent 循环"
description: "用 ADK-Rust 3.0 让模型提出文件读取请求、看到真实结果后回答，从事件和请求记录里看清循环的每一步，并验证调用配对与预算停止。"
pageClass: learn-agent-rust-course
prev:
  text: 第 0 章 · 整体架构与环境
  link: /learn-agent-rust/architecture-and-setup
next:
  text: 第 2 章 · 工具注册与图调度
  link: /learn-agent-rust/tools-and-graph
---

# 第 1 章：最小 Agent 循环

[课程总览](./index.md) · [上一章](./architecture-and-setup.md) · [学习路径](./learning-path.md) · [下一章](./tools-and-graph.md)

::: tip 本章学习目标
- 沿一次文件读取，说明模型请求、工具执行、结果回传与再次调用的顺序。
- 认识 ADK-Rust 里表达这些步骤的类型：模型回复里的调用与文本、工具结果、调用 ID，以及模型的边界 `Llm` trait。
- 运行正常、工具失败和预算耗尽实验，区分“循环结束”与“练习目标达成”。

**前置：** 完成[环境准备](./setup.md)和[第 0 章](./architecture-and-setup.md)；能阅读结构体、枚举、`match`、`Vec`、`Result` 和基本 `async/await`。

**实践方式：** 下载 <a href="/learn-agent-rust/agent-loop.zip" download>本章 Rust 工程</a>，按[第 5 节](#hands-on)取一次 ADK-Rust 源码后运行。固定 Rust 1.99.1 与 ADK-Rust 3.0 的一个固定提交；运行时无需模型密钥、GPU 或数据库。
:::

::: info 本章已迁移到 ADK-Rust 3.0
本章实验基于 ADK-Rust 3.0 的发布候选版本（固定提交，尚未发布到 crates.io）。旧版本章用标准库手写了整个循环，可从 git 标签 `learn-agent-rust-v1` 取得；新版不再手写循环，改为从框架的事件和请求记录里把每一步看清楚。和旧版相比，有一处结论变了：旧版的应用会拒绝重复的调用 ID，ADK-Rust 不检查（第 2 节）。
:::

上一章把模型、工具、应用策略和会话放在了一张架构图中。现在让它们围绕一个问题真正往返一次：

> 读取 README.md，告诉我如何启动项目。

如果程序只把问题交给模型，再打印模型的回答，文件读取发生在哪里？在 ADK-Rust 里，这段往返由 `LlmAgent` 在 `Runner` 里完成：模型先提出行动请求，框架执行工具，把结果写进历史，再次调用模型。等模型给出最终回答，或者触及运行上限，循环才停止。框架没有“只走一步”的接口，所以本章换一种方式看清它：记下框架产生的每一个事件，以及模型收到的每一次请求。

<LearnAgentRustMap active="agent-loop" />

<!-- experiment-library:start -->

全书实验可从[统一代码库](./experiments.md#agent-loop)下载；解压后进入 `chapters/agent-loop/`，或在代码库根目录运行 `python3 run.py run R01`。

<!-- experiment-library:end -->

::: info 本章实验状态
正文与独立 Rust 实验已完成。模型是本章自己写的 `RuleLlm`：它实现 ADK-Rust 的 `Llm` trait，只根据收到的请求内容按固定规则回复；文件工具实际读取程序新建的临时目录。验证脚本核对全部 14 个场景的输出、计数和停止原因。后续章节多用 ADK-Rust 自带的 `ScriptedLlm`；本章写规则模型的原因见第 3 节。
:::

## 1. 先跑一次：为什么只有一次读取，却有两次模型调用？

在解压后的 `agent-loop` 目录里运行（准备步骤见[第 5 节](#hands-on)）：

```sh
cargo run --locked
```

<<< @/public/learn-agent-rust/outputs/r01-normal.txt

先看前四行轨迹：

1. `call id=read-1 read_file {"path":"README.md"}`：第一次调用模型，它没有回答，而是请求读取文件。
2. `result id=read-1 read_file status=ok …`：框架执行工具，把文件内容作为结果记下，带着同一个调用 ID。
3. `text "README 里的启动命令是：cargo run"`：第二次调用模型，它看到了文件内容，给出回答。
4. `final`：这是最终回答，循环结束。

轨迹里的 `status=ok` 是本书轨迹片段在结果没有状态注解时写的标签；失败、未执行等情况，框架会在结果上注明状态（`failed`、`not_run` 等）。

再看最后两行 `request`：这是模型实际收到的两次请求，按顺序列出请求里每条消息的角色。第一次只有 `system`（Agent 的指令）和 `user`（问题）；第二次多了 `model`（它自己上次提出的调用）和 `function`（工具结果）。工具执行发生在两次模型调用之间，它本身不算一次模型调用。所以一次读取对应两次模型调用：一次提出请求，一次读结果回答。

统计里的 `session_events=4` 是会话里保存的事件数：用户问题、调用、结果、回答。

## 2. 模型返回的究竟是什么？

ADK-Rust 用同一个类型 `Content` 表示一条消息，它由若干 `Part` 组成。和本章有关的有三种：

| Part | 谁产生 | 含义 |
| --- | --- | --- |
| `FunctionCall { name, args, id }` | 模型 | 请求调用某个工具，`id` 是这次调用的标识 |
| `FunctionResponse { function_response, id }` | 框架执行工具后 | 工具结果，带回原调用的 `id` |
| `Text { text }` | 模型 | 文本；不含调用的文本回复就是最终回答 |

模型的一次回复可以只有文本（回答），也可以有一个或多个 `FunctionCall`（行动请求）。消息条数和调用次数因此不同：`two-tools` 场景里，一条模型回复带了两个调用。

### 调用 ID 关联哪两件事？

工具名说明调用哪种能力，调用 ID 说明是哪一次请求。同一个工具可以在同一轮或不同轮出现多次，结果靠 ID 对应到具体请求。框架执行工具时，把原调用的 ID 原样写进结果；后面的预算实验会看到，即使工具没有执行，框架也为每个调用写一条带原 ID 的结果。

ADK-Rust 3.0 不检查 ID 是否重复。`duplicate-id` 场景里，模型第二轮又用了 `read-1`，框架照常执行了第二次读取：

<<< @/public/learn-agent-rust/outputs/r01-duplicate-id.txt

这项检查不在框架里。真实模型服务通常保证 ID 唯一；需要防御时，可以在模型回复之后、工具执行之前加检查（[第 4 章](./hooks.md)）。

### 这些类型和模型服务的 JSON 是什么关系？

`Content` 和 `Part` 是框架内部的类型，与具体模型服务无关。接真实服务时，`adk-model` 里的适配器负责转换：例如 Anthropic 的 `tool_use` / `tool_result` 块、OpenAI 的 `tool_calls` / `tool` 消息，都映射到 `FunctionCall` / `FunctionResponse`。请求记录里的 `model`、`function` 角色也是框架的内部叫法。本章不验证任何真实服务的协议，那是[专题 3](./model-evaluation.md)的内容。

## 3. 把模型与工具各写成一个可观察的边界

### 模型：只能看到请求

ADK-Rust 里，模型就是任何实现了 `Llm` trait 的类型。必需的方法只有两个：返回名字的 `name`，以及根据一个 `LlmRequest` 生成回复的 `generate_content`。本章自己写了一个：

<<< @/public/learn-agent-rust/code/agent-loop/src/main.rs#model

`RuleLlm` 不联网，也不读文件。它只能从 `LlmRequest` 里看到历史消息：还没有工具结果，就请求读取；已经有结果，就从最后一条结果里找“启动命令：”那一行来回答，找不到就报告未完成。所以 `changed-readme` 场景把 README 改成 `cargo run --release` 以后，回答跟着变，这说明回答来自真实读到的内容：

<<< @/public/learn-agent-rust/outputs/r01-changed-readme.txt

真实模型也是同样的边界：它看不到磁盘，看到的只是框架交给它的请求。后续章节多用 ADK-Rust 自带的 `ScriptedLlm`（按预先写好的脚本逐条回复），本章写一个规则模型，是为了看清这个边界。

### 文件读取在哪里真正发生？

<<< @/public/learn-agent-rust/code/agent-loop/src/main.rs#tool

处理函数只接受 `README.md`，并自己记两个计数。它们和框架的事件分开记录，用来核对“请求了”“尝试读了”“读成功了”是三件不同的事：

| 计数 | 含义 | 例子 |
| --- | --- | --- |
| `tool_results` | 事件流里出现了几条工具结果（含失败和未执行的） | `unknown-tool` 为 1，但工具没有运行 |
| `read_attempts` | 处理函数真的去读了几次 | `invalid-path` 为 0：路径检查先拒绝了 |
| `read_successes` | 读成功了几次 | `missing-file` 为 0：尝试了，文件不存在 |

工具在同一个进程里运行，读取的是程序用 `tempfile` 新建的临时目录，进程结束时自动删除。限制路径的规则来自应用，第 3 章再讲谁有权决定一个动作能不能执行。

## 4. 将这些步骤接成一个循环

把模型、工具交给 `LlmAgent`，再交给 `Runner`：

<<< @/public/learn-agent-rust/code/agent-loop/src/main.rs#wiring

循环本身在 `LlmAgent` 里。`Runner` 负责会话，并把预算、策略这些运行规则装进这次运行；真正在行动之前检查它们的是 `LlmAgent`。从实验结果和源码（见本章“在 ADK-Rust 源码里”一节）可以确认这几条顺序：

- **每次调用模型之前先检查上限。** 循环上限 `max_iterations`（默认 100 轮，每轮调用一次模型）和运行预算 `RunBudget` 的模型调用次数，都在请求模型之前检查；超了就不再调用。
- **一条回复里的工具调用按整批放行。** 这一批要多少次工具调用额度就一次申请多少；不够就一个都不执行，每个调用都得到一条 `not_run` 结果，然后运行停止。
- **整批结果都写进历史以后，才发下一次请求。** `two-tools` 场景的第二次请求里，两条 `function` 结果都已经在了。
- **四种停止方式：** 模型给出不含调用的回复（最终回答）、触及循环上限（实验 F）、预算用完（实验 C、D、E）、模型出错（只在 Rust 测试里覆盖）。后三种运行以错误结束，错误码就是停止原因；其中循环上限的错误码是笼统的 `agent.legacy`，不如预算的 `budget.*` 具体。框架还有别的结束方式（取消、等待审批、交接给其他 Agent），它们不以错误结束，后面的章节再讲。本章只有看到 `assistant` 的最终文本才记作 `final_answer`。

`wiring` 片段里还有一行 `without_intra_compaction()`：ADK-Rust 3.0 默认会在请求快接近模型上下文窗口时自动压缩历史，本章把它关掉，保证每次请求都带上未经删减的完整历史，输出也可重复。压缩在[第 13 章](./context-compaction.md)专门讨论。

预算装在 `Runner` 上：

<<< @/public/learn-agent-rust/code/agent-loop/src/main.rs#limits

读取事件流时，正常事件进轨迹，错误码作为停止原因：

<<< @/public/learn-agent-rust/code/agent-loop/src/main.rs#events

预算用完时，框架还会往会话里写一条没有正文的事件，带着错误码、错误说明和触及的是哪项限制，说明为什么停（轨迹里的 `stop code=…` 行）。`zero-model-budget` 的 `session_events=2`（用户问题加这条事件）可以印证它确实进了会话。保存这条事件是尽力而为：保存失败时框架只记一条警告，不会让运行失败。

### 什么东西会活到下一轮？

模型每次收到的是完整的历史：系统指令、用户问题，加上此前所有的调用和结果，请求记录里的角色序列一次比一次长。这里有两份历史：一次运行开始时，`LlmAgent` 从会话里取出历史，之后在内存里自己维护一份，每次请求都用它；同时，`Runner` 把每个事件写进会话。所以同一次运行里的下一次请求来自 `LlmAgent` 内存里的那份，下一次运行（例如用户再问一句）才从会话里重新读取。本章的会话用的是 `InMemorySessionService`，进程退出就没了。跨进程保存与恢复在[第 6 章](./graph-pause-resume.md)和[专题 1](./postgres-checkpoints.md)讨论，工具已经执行、结果却没保存的窗口在[专题 2](./side-effect-reliability.md)讨论。

## 5. 动手实验 {#hands-on}

下载并解压<a href="/learn-agent-rust/agent-loop.zip" download>本章工程</a>。ADK-Rust 3.0 还没有发布到 crates.io，工程里的 `.cargo/config.toml` 把 ADK 依赖指向本目录旁边的 `adk-rust/`，先取一次固定提交的源码：

```sh
cd agent-loop
python3 fetch-adk-rust.py ../adk-rust    # 需要 git 与 GitHub 访问；不行时加 --method cdn
cargo run --locked
```

命令要在 `agent-loop` 目录里运行。编译时会看到 adk-core 的 3 条弃用警告（上游固定 Rust 1.95.0），不影响运行和检查。

### 实验 A：答案来自读到的文件

```sh
cargo run --locked -- --scenario changed-readme
```

输出见第 3 节。改了 README，回答跟着变。

### 实验 B：读取失败，循环照样结束

```sh
cargo run --locked -- --scenario missing-file
```

<<< @/public/learn-agent-rust/outputs/r01-missing-file.txt

工具失败了，结果仍然带着 `read-1` 交回模型，模型据此报告“任务未完成”。停止原因是 `final_answer`，`fixture_goal_met=false`：循环正常结束，不等于练习目标达成。

### 实验 C：只给一次模型调用

```sh
cargo run --locked -- --max-model-calls 1
```

<<< @/public/learn-agent-rust/outputs/r01-model-budget.txt

第一次调用提出读取，工具执行并留下结果；准备第二次调用时预算用完，运行以 `budget.model_calls` 结束。文件已经读出来了，但没有人根据它回答，目标未达成。预算拦住的是下一次模型调用，已经放行的工具照常执行。

### 实验 D：模型一直请求，靠什么停下？

`repeat` 场景的模型不管看到什么都再读一次。给它两次工具调用额度：

```sh
cargo run --locked -- --scenario repeat --max-tool-calls 2
```

<<< @/public/learn-agent-rust/outputs/r01-repeat.txt

前两次读取成功，额度正好用完。注意框架还是发起了第三次模型调用：调用模型前只在工具调用“已经超出”上限时才拒绝，“刚好用完”不拦。第三次回复里的 `read-3` 申请额度时被拒绝，得到 `not_run`，运行以 `budget.tool_calls` 结束。每一次读取都合法，整段执行却没有进展，所以需要累计的上限。只设 `--max-model-calls 2` 的话，就由模型调用预算在第三次调用前停下（`repeat-model-budget`）。

### 实验 E：一轮两个调用，只剩一次额度

```sh
cargo run --locked -- --scenario two-tools
cargo run --locked -- --scenario two-tools --max-tool-calls 1
```

<<< @/public/learn-agent-rust/outputs/r01-two-tools.txt

<<< @/public/learn-agent-rust/outputs/r01-batch-budget.txt

额度充足时，一条回复里的 `read-1`、`read-2` 都执行，第二次请求的角色序列里有两条 `function`，两条结果都在。只剩一次额度时，整批一个都不执行，两个调用各得到一条带原 ID 的 `not_run` 结果，读取次数为 0。会话事件数也不同：执行了的两个结果各写一个事件（`two-tools` 共 5 个），整批拒绝时两条 `not_run` 结果合在一个事件里（`batch-budget` 加上停止事件共 4 个）。

### 实验 F：不设预算，循环上限怎样停下？

`repeat` 场景如果什么限制都不加，会一直读到默认的 100 轮上限。把循环上限设成 3：

```sh
cargo run --locked -- --scenario repeat --max-iterations 3
```

<<< @/public/learn-agent-rust/outputs/r01-loop-limit.txt

三轮各调用一次模型、各读一次文件；准备第四次调用模型时超限，运行以 `agent.legacy` 结束。和预算不同，这种停止不会往会话里写停止事件（轨迹里没有 `stop code=…` 行，会话事件 7 个：用户问题加三对调用和结果）。循环上限是 Agent 自己的设置，预算是整次运行的规则；后者更具体，也能限制工具、费用和时间。

![左侧额度充足，两个调用各自读取一次；右侧只剩一次额度，整批不执行，两条结果都保留原调用 ID。](/learn-agent-rust/figures/r01-call-pairing.svg)

## 6. 核对实验记录与验证范围

![正常路径中用户问题、模型请求、工具结果和模型回答依次出现，共两次模型调用、一条工具结果、四条会话事件。](/learn-agent-rust/figures/r01-message-cycle.svg)

![LlmAgent 在每次调用模型前检查循环上限和预算，工具调用按整批申请额度，结果写回后进入下一次请求。](/learn-agent-rust/figures/r01-loop-control.svg)

全部场景的实际记录（由验证脚本生成）：

<!-- r01-results:start -->

| 场景 | 参数 | 模型调用 | 工具结果 | 读取尝试 / 成功 | 会话事件 | 停止原因 | 练习目标 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `normal` | `—` | 2 | 1 | 1 / 1 | 4 | `final_answer` | 达成 |
| `changed-readme` | `--scenario changed-readme` | 2 | 1 | 1 / 1 | 4 | `final_answer` | 达成 |
| `missing-file` | `--scenario missing-file` | 2 | 1 | 1 / 0 | 4 | `final_answer` | 未达成 |
| `model-budget` | `--max-model-calls 1` | 1 | 1 | 1 / 1 | 4 | `budget.model_calls` | 未达成 |
| `zero-model-budget` | `--max-model-calls 0` | 0 | 0 | 0 / 0 | 2 | `budget.model_calls` | 未达成 |
| `tool-budget` | `--max-tool-calls 0` | 1 | 1 | 0 / 0 | 4 | `budget.tool_calls` | 未达成 |
| `repeat` | `--scenario repeat --max-tool-calls 2` | 3 | 3 | 2 / 2 | 8 | `budget.tool_calls` | 未达成 |
| `repeat-model-budget` | `--scenario repeat --max-model-calls 2` | 2 | 2 | 2 / 2 | 6 | `budget.model_calls` | 未达成 |
| `loop-limit` | `--scenario repeat --max-iterations 3` | 3 | 3 | 3 / 3 | 7 | `agent.legacy` | 未达成 |
| `two-tools` | `--scenario two-tools` | 2 | 2 | 2 / 2 | 5 | `final_answer` | 达成 |
| `batch-budget` | `--scenario two-tools --max-tool-calls 1` | 1 | 2 | 0 / 0 | 4 | `budget.tool_calls` | 未达成 |
| `duplicate-id` | `--scenario duplicate-id` | 3 | 2 | 2 / 2 | 6 | `final_answer` | 达成 |
| `unknown-tool` | `--scenario unknown-tool` | 2 | 1 | 0 / 0 | 4 | `final_answer` | 未达成 |
| `invalid-path` | `--scenario invalid-path` | 2 | 1 | 0 / 0 | 4 | `final_answer` | 未达成 |

<!-- r01-results:end -->

“工具结果”包括失败和未执行的结果；“练习目标”要求真的读到了文件，并且最终回答和读到的启动命令一致。

网站维护者运行 `python3 scripts/verify-learn-agent-rust-loop.py`：它打包章节、在临时目录解压并在旁边放好 `adk-rust/`，执行 `cargo fmt --check`、`cargo clippy -D warnings`、`cargo test`；14 个场景各连跑两次，输出必须逐字节相同；逐个核对计数、停止原因、调用与结果的 ID 一一对应、预算停止事件（以及循环上限不写停止事件）；三种非法参数必须以退出码 2 结束；最后生成上面的表。7 个 Rust 测试分别检查：零模型预算不调用模型、整批超额一个都不执行、重复 ID 会被再次执行、回答来自读到的文件、最终回答不等于目标达成、循环上限在下一次调用模型前停下、模型出错时停止且不执行工具。加 `--check` 检查产物是否过期。

### 与旧版场景的对应

旧版（标准库手写循环）有 13 个场景，外加一份记录编译环境的 `environment` 输出（现在环境信息记在证据文件里）。新版保留这 13 个场景名，另加 `loop-limit`，有几处口径变了：

| 变化 | 旧版 | 新版 | 原因 |
| --- | --- | --- | --- |
| 计数口径 | “工具执行尝试” | “工具结果”（含失败与未执行） | 框架为每个调用都写结果，未执行的也有；`tool-budget` 因此从 0 变成 1，`batch-budget` 从 0 变成 2，`repeat` 从 2 变成 3。实际读取次数另由 `read_attempts` 记录。 |
| 默认上限 | 3 次模型调用、2 次工具调用 | 不设预算 | 框架默认没有运行预算；`repeat` 需要显式加 `--max-tool-calls 2`。 |
| 参数名 | `--max-model-turns` | `--max-model-calls` | 与框架的 `RunBudget` 用词一致。 |
| 停止原因 `invalid_call_id` | 应用拒绝重复或空的调用 ID | 删除 | 框架不检查重复 ID（`duplicate-id` 结论相反）；空 ID 由框架自动补上 `adk-call-…`。 |
| 循环上限 | 手写的轮次上限 | 新增 `loop-limit` | 由 `LlmAgent` 的 `max_iterations` 提供。 |
| 测试“提前给出最终回答不会触发读取” | 有 | 删除 | 规则模型的回复只取决于请求内容，`missing-file` 等场景已覆盖“回答不等于目标”。 |

## 框架替你做了什么、没做什么

| 框架做了 | 仍归应用 |
| --- | --- |
| 运行“调用模型 → 执行工具 → 结果写回 → 再调用”的循环，每次请求都带上历史（默认会自动压缩，本章关掉了）。 | 写清楚 Agent 指令和工具说明。 |
| 每个调用的结果都带原调用 ID，包括未执行的。 | 检查调用 ID 是否重复（框架不查）。 |
| 循环上限、模型调用预算、工具调用预算；工具按整批放行。 | 选合适的上限；判断模型给出的回答是否真的完成了任务。 |
| 用错误码报告停止原因，并把预算停止写进会话。 | 区分“循环结束”和“目标达成”，给任务结果单独的判断。 |
| — | 决定一个动作该不该执行（第 3 章）。 |

<!-- adk-refs:start -->

## 在 ADK-Rust 源码里

本章观察到的循环，在 ADK-Rust 里分布在这几处（按一次运行的先后）：

| 本章内容 | 源码位置 | 对照要点 |
| --- | --- | --- |
| 运行入口 | [`adk-runner/src/runner.rs` · `Runner::run_with_config`](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-runner/src/runner.rs#L989-L1000) | 加载会话、交给 Agent 运行，并把 Agent 产生的每个事件逐条写进会话 |
| 从会话取出历史 | [`adk-agent/src/llm_agent.rs` · `prepare_conversation`](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-agent/src/llm_agent.rs#L406-L578) | 运行开始时把会话事件整理成本次运行在内存里维护的对话历史 |
| 循环本身 | [`adk-agent/src/llm_agent.rs` 第 4451 行](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-agent/src/llm_agent.rs#L4451) | 每一轮：检查上限与预算 → 组装请求 → 调用模型 → 执行工具 → 结果写回历史 |
| 循环上限 | [`adk-agent/src/llm_agent.rs` 第 4464 行](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-agent/src/llm_agent.rs#L4464) | 每次调用模型前先加一，超过 `max_iterations` 就以错误结束（`agent.legacy`） |
| 组装一次请求 | [`adk-agent/src/llm_agent.rs` 第 4577 行](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-agent/src/llm_agent.rs#L4577) | 把对话历史和工具声明放进 `LlmRequest`；本章记录的 `request` 行就是它 |
| 模型的回复写进历史 | [`adk-agent/src/llm_agent.rs` 第 5304 行](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-agent/src/llm_agent.rs#L5304) | 带调用的回复先写进历史，下一次请求里的 `model` 角色就是它 |
| 执行这一批调用 | [`adk-agent/src/llm_agent.rs` 第 5642 行](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-agent/src/llm_agent.rs#L5642) | 按策略执行同一条回复里的全部调用 |
| 工具结果写回历史 | [`adk-agent/src/llm_agent.rs` 第 5700 行](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-agent/src/llm_agent.rs#L5700) | 结果带原调用 ID 写回历史，下一次请求里的 `function` 角色就是它 |
| 模型的边界 | [`adk-core/src/model.rs` 第 20 行](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-core/src/model.rs#L20) | 必需的只有 `name` 和这个 `generate_content`；本章的 RuleLlm 就实现它 |
| 模型调用预算 | [`adk-core/src/budget.rs` · `BudgetTracker::begin_model_call`](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-core/src/budget.rs#L711-L727) | 在请求模型之前计数；用完就返回 `budget.model_calls` |
| 整批申请工具额度 | [`adk-core/src/budget.rs` · `BudgetTracker::begin_tool_calls`](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-core/src/budget.rs#L845-L851) | 一条回复里的全部调用一起申请：要么全部计入，要么一个都不计入，不够时每个调用得到 `not_run` |

源码固定在 ADK-Rust `98515241133d`（3.0.0，2026-11-26，尚未发布到 crates.io）。本节由 `scripts/learn-agent-rust-adk-refs.py` 生成。

<!-- adk-refs:end -->

::: warning 常见误区
- 把工具请求当作执行证据：模型提出了 `read_file`，不等于文件被读了，要看结果和计数。
- 只看最终回答：会话里的调用和结果才说明回答从哪来。
- 把 `final_answer` 当作任务成功：`missing-file` 正常结束，目标未达成。
- 把调用 ID 当作业务幂等键：它只用来配对；框架甚至不检查它是否重复。
- 把规则模型的实验当作真实模型验证：这里只证明循环、计数、配对和停止条件。
:::

<!-- transfer-thinking:start -->

## 迁移思考：终止性是一种业务约束

模型每次都提出合法读取，是否应让它一直运行？先给出你的判断，再展开下面的推演。

<details><summary>推演与应用</summary>

让重复读取先耗尽累计额度，再观察停止原因；每个动作合法，整段执行仍可能没有进展。

循环需要同时回答动作能否执行、何时应交回控制权；继续策略见专题 5。

</details>

这是一道迁移练习，推演不代表新增实验已通过。对照[全书审查中的证据层次](./course-review.md#evidence-layers)，说明你的判断还需要哪一级证据。

<!-- transfer-thinking:end -->

## 本章结论：循环在框架里，证据在事件里

本章形成了一个可观察的往返：模型返回结构化的调用，框架执行工具，结果按调用 ID 写回历史，再由模型生成下一份回复。循环由 `LlmAgent` 运行；预算装在 `Runner` 上，由 `LlmAgent` 在行动之前检查；停止原因以错误码报告，预算停止还会写进会话。

框架接手了循环，判断任务是否完成仍是应用的事：本章用 `fixture_goal_met` 单独检查。下一章增加第二个工具，看工具描述和执行入口怎样保持一致，再把同一个 Agent 放进图里调度。

## 检查理解

1. 正常实验中，为什么 1 次工具读取需要 2 次模型调用？

   <details><summary>参考答案</summary>

   第一次调用模型产生读取请求。框架执行工具后才有文件内容；第二次调用时模型在请求里看到工具结果，据此生成最终回答。工具执行本身不算一次模型调用。

   </details>

2. 两个请求都叫 `read_file`，结果为什么还要带调用 ID？

   <details><summary>参考答案</summary>

   工具名说明调用哪种能力，调用 ID 标识哪一次请求。相同工具可以在同一轮或不同轮出现多次，结果要靠 ID 对应到具体请求。框架会把原 ID 写进结果，但不检查 ID 是否重复，`duplicate-id` 场景里重复的 ID 照样被执行。

   </details>

3. 只给 1 次模型调用预算，文件已经读出，为什么练习目标仍未达成？

   <details><summary>参考答案</summary>

   第一次调用的请求和工具结果已经写入历史，但框架在下一次调用模型之前因预算停止，没有人根据结果生成最终回答。练习目标要求成功读取并给出对应的启动命令。

   </details>

4. 模型同一轮提出两个请求，只剩一次工具额度，执行几个？怎样记录结果？

   <details><summary>参考答案</summary>

   执行 0 个。框架按整批申请额度，不够就整批不执行，两个调用各得到一条带原 ID 的 `not_run` 结果，运行以 `budget.tool_calls` 停止。读取计数不增加。

   </details>

5. `missing-file` 的停止原因是 `final_answer`，这项实验验证了什么？

   <details><summary>参考答案</summary>

   它验证读取失败后仍有一条带原 ID 的工具结果交回模型，模型据此报告失败。循环正常结束，但读取任务没完成，所以目标为 `false`。它没有验证真实模型面对错误时会怎样做。

   </details>

## 参考资料

- <a href="/learn-agent-rust/code/agent-loop/README.md" download>本章工程 README（下载）</a>：运行命令与实验边界。
- ADK-Rust（固定提交）：[LlmAgent 与 Runner](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-runner/README.md)、[2.x → 3.0 迁移指南](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/docs/official_docs/migration/2.x-to-3.0.md)。
- [Learn Claude Code：s01 Agent Loop](https://learn.shareai.run/zh/s01/)：参考课程的模型、工具与结果回传主线；本章 Rust 实现、实验及预算策略由本站维护。
- [Claude 官方文档：Handle tool calls](https://platform.claude.com/docs/en/agents-and-tools/tool-use/handle-tool-calls)：真实服务的工具请求、关联 ID 与结果消息格式。

参考课程的[原始循环图](/learn-agent-rust/figures/upstream/r01-agent-loop.svg)继续保留，图中使用其 Python/Claude 语境；来源版本与许可见[课程架构](./architecture.md#reference-assets)。本章正文中的图由本站脚本生成。

下一章：[第 2 章：工具注册与图调度](./tools-and-graph.md)。增加第二个工具，再把同一个 Agent 放进图里调度。
