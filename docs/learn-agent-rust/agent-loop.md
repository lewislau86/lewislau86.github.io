---
title: "第 1 章：最小 Agent 循环"
description: "用可独立运行的 Rust 程序，让模型提出文件读取请求、看到真实结果后回答，并验证消息配对与预算停止。"
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
- 用 Rust 类型区分最终回答、工具请求和工具结果，并用调用 ID 关联请求与结果。
- 运行正常、工具失败和预算耗尽实验，区分“循环结束”与“练习目标达成”。

**前置：** 完成[环境准备](./setup.md)，读过[课程架构](./architecture.md)；能阅读结构体、枚举、`match`、`Vec` 和 `Result`。

**实践方式：** 下载本章<a href="/learn-agent-rust/code/agent-loop.rs" download>完整 Rust 源码</a>，使用支持 edition 2024 的 Rust 工具链编译。只有标准库依赖，运行时无需模型密钥、GPU 或数据库。
:::

上一章把模型、工具和应用策略放在了一张架构图中。现在让它们围绕一个问题真正往返一次：

> 读取 README.md，告诉我如何启动项目。

如果程序只把问题交给模型，再打印模型的回答，文件读取发生在哪里？这一章把中间的每一步都写出来：模型先提出行动请求，应用执行工具，把工具结果追加到历史，再次调用模型。等模型给出最终回答，或者应用触及执行上限，循环才停止。

<LearnAgentRustMap active="agent-loop" />

::: info 本章实验状态
正文与独立 Rust 实验已完成。脚本模型用固定规则返回工具请求或最终回答，文件工具实际读取程序新建的临时目录；验证脚本会核对全部实验输出。

本章先用标准库显式展开控制流。`langchain-rust`、`graph-flow`、HTTP 工具协议和真实模型尚未接入本章示例；后续接入时要保留这里的消息与停止契约，再分别验收。
:::

## 1. 先跑一次：为什么只有一次读取，却有两轮模型调用？

程序创建一个专用临时目录，向其中的 `README.md` 写入项目名和启动命令。模型收到的是用户问题，文件内容要经工具读取后才进入消息历史。运行结束时，临时目录由 `Workspace` 的 `Drop` 清理。

::: info 代码出处
下文 Rust 代码直接引用同一个源文件，终端输出也从实际运行记录导入。

<a href="/learn-agent-rust/code/agent-loop.rs" download>下载完整 agent-loop.rs</a> · [在 GitHub 上查看](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/learn-agent-rust/code/agent-loop.rs)
:::

把文件下载到一个练习目录，在该目录打开终端。以下是编译和运行命令：

```sh
rustc --edition=2024 -D warnings agent-loop.rs -o agent-r01
./agent-r01
```

Windows 原生终端编译后运行 `./agent-r01.exe`；使用 WSL 时沿用上述命令。

先预测一下：消息历史里应该出现几条消息？模型分别在什么时候被调用？再核对完整输出：

<<< @/public/learn-agent-rust/outputs/r01-normal.txt

第一轮模型只知道用户要读取 README，于是返回 `read_file` 请求。应用读取成功后，第二轮模型才看到文件内容，提取启动命令并回答。**工具执行发生在两轮模型调用之间。**

这里的“脚本模型”是我们编写的确定性替身：它按规则选择返回类型，从工具结果里寻找“启动命令：”这一行。它让每次实验的控制流相同，便于检查程序；真实语言模型的推理与任务质量留到后续实验。

![正常实验中，用户、工具请求、工具结果与最终回答依次进入历史；一次读取需要两轮模型调用。](/learn-agent-rust/figures/r01-message-cycle.svg)

顺着图中的消息顺序阅读。`read-1` 同时出现在请求和结果上；右侧的计数来自本章实际运行，模型轮次、工具执行次数与消息条数分别统计。

## 2. 模型返回的究竟是什么？

看输出中的第二条消息：`read_file(path="README.md")`。这行文字是程序为了展示而格式化出来的日志；运行时持有的是包含 ID、名称和参数的 `ToolCall`。

<<< @/public/learn-agent-rust/code/agent-loop.rs#messages

先看两个枚举，再看历史消息：

- `ModelReply::ToolCalls` 携带一批工具请求，应用接下来要处理这些请求。
- `ModelReply::Final` 携带最终文本，表示模型这一轮决定结束。
- `Message` 记录会话中已经发生的事：用户输入、模型响应、工具结果。

`ToolResult.output` 用 `Result<String, String>` 保存成功内容或错误说明。文件不存在时，也能形成明确的结果，而不用把“失败”混进一段看起来像文件内容的文本中。

注意 `ToolCalls` 里装的是 `Vec<ToolCall>`：同一轮模型可以提出多个请求。一个 assistant 消息可能包含两个调用，因此消息条数与调用次数要分别计算。本章按列表顺序执行它们。

### 调用 ID 关联哪两件事？

同一个工具可以调用很多次。若两次请求都叫 `read_file`，仅靠名称无法判断某份结果属于哪次请求。`id` 标识一次请求，`call_id` 将结果关联回来。

本章约定：同一次运行里，调用 ID 非空且唯一；每个被接受的请求都产生一个同 ID 的结果，成功和失败都要回传。再次调用模型之前，先把这一批的结果全部写回历史。

<<< @/public/learn-agent-rust/code/agent-loop.rs#validation

校验在工具执行前完成。如果模型重复使用旧 ID，应用以 `InvalidCall` 停止；原始异常响应留在本地历史供诊断，也不会再发送给模型。本章没有实现修复这种响应后继续执行的策略。

### 这些类型和模型服务的 JSON 是什么关系？

这是课程应用内部的消息表示。真实服务适配器还要把它们转换成提供方要求的请求与响应格式。例如 Claude 的客户端工具调用使用 `tool_use` 块，以 `tool_use_id` 关联结果，并把 `tool_result` 放在后续的 `user` 消息中。详见官方的 [Handle tool calls](https://platform.claude.com/docs/en/agents-and-tools/tool-use/handle-tool-calls)。

因此，日志中的 `tool` 是本章的内部消息类别。以后对接服务时，既要保留请求与结果的对应关系，也要验证具体的角色、字段和排列规则。

## 3. 把模型与工具各写成一个可观察的边界

现在已经知道模型返回哪两种结果，再来看“调用模型”本身。循环只需要一个能力：给它当前消息历史，取得下一份响应。

<<< @/public/learn-agent-rust/code/agent-loop.rs#model

`Model` trait 是循环依赖的接口，`ScriptedModel` 是本章的实现。它接收不可变的消息切片 `&[Message]`，返回 `ModelReply`；历史的追加由应用完成。

顺着正常路径读这段代码：

1. 最后一条是用户消息，返回 `read-1` 这次读取请求。
2. 最后一条是工具结果，检查 `output`。
3. 读取成功时，从结果中提取启动命令；读取失败时，生成“任务未完成”的说明。

其中 `repeat`、`two-tools` 等分支用于后面的故障实验。模型替身可以故意不断请求工具，让我们验证应用会不会按预算停下来。

### 文件读取在哪里真正发生？

接下来是唯一的文件工具：

<<< @/public/learn-agent-rust/code/agent-loop.rs#tool

`execute` 先检查工具名和路径，再调用 `fs::read_to_string`。其返回类型本身就是 `Result`，文件缺失等错误会进入失败分支；函数行为可对照 [Rust 标准库文档](https://doc.rust-lang.org/std/fs/fn.read_to_string.html)。

这里刻意分开三个计数：

| 计数 | 何时增加 | 用来回答什么问题 |
| --- | --- | --- |
| `tool_calls` | 进入一次工具分派时，名称、路径或读取失败也计入 | 应用实际处理了多少次工具执行尝试？ |
| `read_attempts` | 名称与路径通过检查，准备调用文件读取时 | 有没有触及文件系统读取？ |
| `read_successes` | 文件内容成功读出时 | 实际得到了几次文件内容？ |

本章只接收精确路径 `README.md`，并只读取程序自己创建的小型练习文件。`Workspace` 持有临时目录，工具借用它；读出的 `String` 进入结果，再进入会话历史。

<<< @/public/learn-agent-rust/code/agent-loop.rs#workspace

读取本机文件属于操作系统文件访问。本章的模型接口、循环和工具函数都在同一个 Rust 进程内，调用之间没有网络传输；状态只保存在内存。若要支持任意工作区文件，路径解析、符号链接、大小限制和超时等机制还需要扩展，见[工具权限与审批](./permissions.md)。

## 4. 将这些步骤接成一个循环

在写循环之前，先列出它要持有的东西：消息历史、已用预算、读取计数、停止原因，以及已经使用的调用 ID。

<<< @/public/learn-agent-rust/code/agent-loop.rs#state

`Limits` 是应用配置，`Run` 是本次执行的状态和结果。`StopReason` 让调用者知道循环为什么返回。模型只返回 `ModelReply`，预算与停止策略由应用解释和执行。

现在看完整的显式循环：

<<< @/public/learn-agent-rust/code/agent-loop.rs#agent-loop

第一次阅读只盯住主线：检查模型预算，调用模型，记录响应；如果是最终回答就返回，如果是工具请求就校验、执行、追加结果，然后回到循环顶部。

![显式循环在调用模型前检查轮次，在执行工具前校验调用与工具预算，结果追加到历史后再进入下一轮。](/learn-agent-rust/figures/r01-loop-control.svg)

先沿蓝色主线读一遍，再观察橙色停止分支。箭头回到模型预算检查，意味着每轮都会重新检查剩余额度。图中是本章代码的控制流；后续可以把模型步骤与工具步骤映射到图节点。

第二次阅读，检查顺序为什么这样安排：

1. **先检查模型预算，再增加轮次并调用。** `model_turns` 计的是尝试次数，模型接口报错也消耗一轮。
2. **先记录模型的工具请求，再追加结果。** 下一轮能同时看到“要求做什么”和“实际得到了什么”。
3. **整批检查工具预算。** 同轮两个请求、只剩一次额度时，整批拒绝；两个请求都得到应用生成的 `tool_budget` 错误结果，实际工具调用次数保持不变。
4. **拿齐这一批结果，再返回循环顶部。** 本章顺序执行；还没有加入并发或逐工具检查点。

这里选择整批拒绝，是为了让初版的预算行为容易预测。应用拒绝的结果也带回原调用 ID，但它表示策略决定，没有执行文件工具。以后引入逐工具审批或恢复时，再重新定义批内执行边界。

### 什么东西会活到下一轮？

`run_agent` 持有 `Run` 和 `seen`，直到返回；模型对象和 `Workspace` 由外层创建，再以借用传入。每轮增加的消息保存在同一个 `Vec<Message>` 中，第二轮才能看到第一轮的结果。

函数返回后，调用者可以读取完整 `Run`。程序退出后，内存历史结束，临时文件被清理。本章还没有保存或恢复会话的入口；涉及重启恢复时，需要继续处理[检查点](./postgres-checkpoints.md)与[外部操作重放](./side-effect-reliability.md)。

## 5. 动手实验：改一个条件，看循环在哪一步停下

先做预测，再运行。以下实验复用同一个二进制，每次启动都会创建独立的练习目录。

### 实验 A：答案是否真的来自文件？

```sh
./agent-r01 --scenario changed-readme
```

该场景只将练习文件的启动命令改为 `cargo run --release`，脚本模型的提取规则与循环都相同。

<<< @/public/learn-agent-rust/outputs/r01-changed-readme.txt

观察工具结果和最终回答是否一起变化。答案变化说明这条实验路径使用了实际读取的内容；这项验证针对固定规则替身的数据流。

### 实验 B：文件不存在，循环会怎样回答？

```sh
./agent-r01 --scenario missing-file
```

<<< @/public/learn-agent-rust/outputs/r01-missing-file.txt

读取尝试为 1，成功为 0。错误仍然作为 `read-1` 的结果交给模型，因此第二轮可以说明失败。

特别看最后一行：停止原因是 `FinalAnswer`，练习目标却为 `false`。`FinalAnswer` 只表示模型给出了最终响应；本例的目标断言还要求实际读到文件，并回答练习文件中约定的启动命令。这个 `fixture_goal_met` 是针对本练习的检查规则，后续通用任务评估见[模型协议与质量评估](./model-evaluation.md)。

### 实验 C：只给一轮模型预算

```sh
./agent-r01 --max-model-turns 1
```

<<< @/public/learn-agent-rust/outputs/r01-model-budget.txt

文件已经读出，但模型还没有第二次看到它。历史停在第三条工具消息，停止原因为 `ModelBudget`。按本章规则，模型轮次限制只拦截下一次模型调用；本轮已获工具预算的请求仍然执行。

再试 `--max-model-turns 0`：用户消息会保留，模型和工具都不被调用。

### 实验 D：模型一直要求再读一次

```sh
./agent-r01 --scenario repeat
```

<<< @/public/learn-agent-rust/outputs/r01-repeat.txt

默认允许 3 轮模型调用、2 次工具执行。第三轮还在请求读取时，应用产生带原 ID 的预算拒绝结果，以 `ToolBudget` 停止；实际读取次数保持为 2。

同一个场景再加 `--max-model-turns 2`，会先触及 `ModelBudget`。两个限制保护不同的边界：哪个条件先满足，就从对应位置返回。本章尚未计量 token、费用、总耗时或工具超时。

### 实验 E：同一轮两个调用，ID 怎样配对？

```sh
./agent-r01 --scenario two-tools
./agent-r01 --scenario two-tools --max-tool-calls 1
```

第一条命令中，同一个 assistant 消息携带 `read-1` 和 `read-2`，各自得到结果后才调用第二轮模型。第二条命令额度不足，整批拒绝，两次文件读取都不发生。

![同轮两个工具请求分别通过 read-1 和 read-2 关联结果；额度不足时整批返回预算拒绝，文件读取次数为零。](/learn-agent-rust/figures/r01-call-pairing.svg)

先看同一条 assistant 消息怎样展开为两个结果，再比较左右两种预算条件。消息与调用计数来自 `two-tools` 和 `batch-budget` 的实际运行。

还可以运行 `--scenario duplicate-id`、`--scenario unknown-tool` 和 `--scenario invalid-path`。先猜测各自会不会发生文件读取，再对照下面的统一结果表。

## 6. 核对实验记录与验证范围

以下表格由 `scripts/verify-learn-agent-rust-loop.py` 实际运行后生成。工具执行尝试沿用前文 `tool_calls` 的口径；应用在预算入口拒绝的请求不计入执行尝试。

<!-- r01-results:start -->

| 场景 | 模型轮次 | 工具执行尝试 | 文件读取尝试 / 成功 | 停止原因 | 练习目标达成 |
| --- | --- | --- | --- | --- | --- |
| `normal` | 2 | 1 | 1 / 1 | `FinalAnswer` | 是 |
| `changed-readme` | 2 | 1 | 1 / 1 | `FinalAnswer` | 是 |
| `missing-file` | 2 | 1 | 1 / 0 | `FinalAnswer` | 否 |
| `model-budget` | 1 | 1 | 1 / 1 | `ModelBudget` | 否 |
| `zero-model-budget` | 0 | 0 | 0 / 0 | `ModelBudget` | 否 |
| `tool-budget` | 1 | 0 | 0 / 0 | `ToolBudget` | 否 |
| `repeat` | 3 | 2 | 2 / 2 | `ToolBudget` | 否 |
| `repeat-model-budget` | 2 | 2 | 2 / 2 | `ModelBudget` | 否 |
| `two-tools` | 2 | 2 | 2 / 2 | `FinalAnswer` | 是 |
| `batch-budget` | 1 | 0 | 0 / 0 | `ToolBudget` | 否 |
| `duplicate-id` | 2 | 1 | 1 / 1 | `InvalidCall` | 否 |
| `unknown-tool` | 2 | 1 | 0 / 0 | `FinalAnswer` | 否 |
| `invalid-path` | 2 | 1 | 0 / 0 | `FinalAnswer` | 否 |

<!-- r01-results:end -->

记录的编译器与目标平台见 <a href="/learn-agent-rust/outputs/r01-environment.txt" download>实验环境</a>。所有场景都使用标准库、脚本模型和临时文件，无第三方 crate；首次准备 Rust 工具链是否需要联网，与本章运行时是否请求模型服务分别看待。

在网站仓库根目录，可以重新生成或核对全部证据：

```sh
python3 scripts/verify-learn-agent-rust-loop.py
python3 scripts/verify-learn-agent-rust-loop.py --check
```

验证脚本会把单个源码复制到独立临时目录编译运行，核对统计、调用 ID 配对、完整输出及正文结果表，并运行源码内的 6 个 Rust 契约测试。测试覆盖零轮次、整批工具额度、同批异常 ID、跨轮重复 ID、直接最终回答与模型接口失败；另外检查错误命令行参数会以非零状态退出。

单独下载源码后，也可以运行其内置测试：

```sh
rustc --edition=2024 -D warnings --test agent-loop.rs -o agent-r01-tests
./agent-r01-tests
```

程序正常展示一次失败场景时，进程退出码仍为 0，表示实验执行完毕；具体任务结果看停止原因与目标断言。非法参数、编译失败等才属于运行入口失败。

::: warning 常见误区
- **把工具请求当作执行证据。** 实际是否访问文件，要看执行路径、读取计数与工具结果。
- **只保留工具结果，丢掉 assistant 请求。** 请求、参数和调用 ID 也是下一轮上下文的一部分。
- **把 `FinalAnswer` 当作任务成功。** 文件缺失实验也能正常生成最终响应；本章另用练习目标断言检查结果。
- **把调用 ID 当作业务幂等键。** 本章只在单次内存运行里检查 ID 唯一。跨进程重试和外部副作用仍需专门的恢复契约。
- **把固定规则实验当作真实模型验证。** 本章验证的是控制流、文件数据流和停止行为，真实协议、模型选择工具的能力与任务质量需要后续证据。
:::

## 本章结论：主线采用有界的显式循环

本章形成了一个可观察的往返：模型返回结构化请求，应用校验并执行工具，结果按调用 ID 写回历史，再由模型生成下一份响应。应用持有消息与累计计数，并在调用前检查预算，用类型化原因报告停止。

这一章只提供一个文件工具。下一步增加工具注册表，再将模型步骤和工具步骤映射到图节点。映射后仍要核对相同任务中的消息、调用、结果和停止原因。

## 检查理解

1. 正常实验中，为什么 1 次工具读取需要 2 轮模型调用？

   <details><summary>参考答案</summary>

   第一轮模型产生读取请求。应用执行后才有文件内容；第二轮模型获得工具结果，据此生成最终回答。工具执行本身不计为模型轮次。

   </details>

2. 两个请求都叫 `read_file`，结果为什么还要携带 `call_id`？

   <details><summary>参考答案</summary>

   工具名称说明调用哪种能力，调用 ID 标识哪一次请求。相同工具可以在同轮或不同轮出现多次，结果需用 ID 与具体请求对应。本章还要求单次运行内 ID 非空且唯一。

   </details>

3. 只给 1 轮模型预算，文件已经读出，为什么练习目标仍未达成？

   <details><summary>参考答案</summary>

   第一轮的请求及工具结果已经写入历史，但应用在下一次模型调用前停止，还没有基于结果生成最终回答。本章的目标断言要求成功读取并给出对应启动命令。

   </details>

4. 模型同轮提出两个请求，只剩一次工具额度，本章执行几个？怎样记录结果？

   <details><summary>参考答案</summary>

   执行 0 个。本章在执行前检查整批额度，分别为两个调用 ID 追加 `tool_budget` 错误结果，以 `ToolBudget` 停止。错误结果由应用生成，实际工具计数不增加。

   </details>

5. `missing-file` 的停止原因是 `FinalAnswer`，这项实验验证了什么？

   <details><summary>参考答案</summary>

   它验证读取失败后仍能形成匹配的工具结果，并交给脚本模型生成失败说明。协议流程结束，但读取任务未完成，所以目标断言为 `false`。它没有验证真实服务协议或真实模型面对错误时的行为。

   </details>

## 参考资料

- [Learn Claude Code：s01 Agent Loop](https://learn.shareai.run/zh/s01/)：参考课程的模型、工具与结果回传主线；本章 Rust 实现、实验及预算策略由本站维护。
- [Rust Book：Defining an Enum](https://doc.rust-lang.org/book/ch06-01-defining-an-enum.html)：用枚举表达不同返回类型。
- [Rust Book：Recoverable Errors with Result](https://doc.rust-lang.org/book/ch09-02-recoverable-errors-with-result.html)：成功值与可恢复错误。
- [Rust 标准库：fs::read_to_string](https://doc.rust-lang.org/std/fs/fn.read_to_string.html)：文件读取与错误。
- [Claude 官方文档：Handle tool calls](https://platform.claude.com/docs/en/agents-and-tools/tool-use/handle-tool-calls)：提供方的工具请求、关联 ID 与结果消息格式。

参考课程的[原始循环图](/learn-agent-rust/figures/upstream/r01-agent-loop.svg)继续保留，图中使用其 Python/Claude 语境；来源版本与许可见[课程架构](./architecture.md#reference-assets)。本章正文中的 Rust 图由本站脚本生成。

下一章：[第 2 章：工具注册与图调度](./tools-and-graph.md)。将单工具分派扩展为注册表，再比较显式循环与图执行的行为。
