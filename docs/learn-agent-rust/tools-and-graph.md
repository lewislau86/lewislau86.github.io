---
title: "第 2 章：工具注册与图调度"
description: "从先列目录、再读 README 的任务出发，用同一份注册表和消息状态核对显式循环与 graph-flow 的执行结果。"
pageClass: learn-agent-rust-course
prev:
  text: 第 1 章 · 最小 Agent 循环
  link: /learn-agent-rust/agent-loop
next:
  text: 第 3 章 · 工具权限与审批
  link: /learn-agent-rust/permissions
---

# 第 2 章：工具注册与图调度

[课程总览](./index.md) · [上一章：最小 Agent 循环](./agent-loop.md) · [下一章：工具权限与审批](./permissions.md)

::: tip 本章学习目标
- 给文件读取增加列目录工具，让描述和执行入口来自同一份注册表。
- 沿消息历史解释工具名称、参数和调用 ID 各自的用途。
- 将显式循环映射为两个图节点，用相同用例核对完整状态。

**前置：** 读过[第 0 章](./architecture-and-setup.md)与[第 1 章](./agent-loop.md)，理解模型请求、程序执行和结果回传的区别；能看懂结构体、枚举、`Result` 和基本 `async/await`。本章工程自带完整循环，可独立运行。

**实践方式：** 下载 <a href="/learn-agent-rust/tools-and-graph.zip" download>本章 Rust 工程</a>，按[环境准备](./setup.md)安装工具后运行。工程固定 Rust 1.99.1，以及 `langchain-rust 8.0.0`、`graph-flow 0.8.1` 的具体 Git revision；首次获取依赖需要网络，运行实验无需模型密钥和数据库。
:::

前面从“读取 README，告诉我如何启动项目”认识了一次工具往返。现在把要求稍微改一下：

> 先列出练习目录，再读取 README.md，告诉我如何启动项目。

文件名已经写在问题里，为什么还要列目录？这里刻意多走一步：让同一个助手使用两种工具，观察代码会在哪里变复杂。实际任务也常常先查看目录，再决定读取哪份说明。

如果每加一个工具，就去模型循环里补一段名称判断，循环很快会同时负责模型请求、参数解析、文件操作和停止判断。本章先把“有哪些工具、怎样分发”收进注册表，再把“下一步运行什么”交给图调度。两次调整都围绕这条短任务展开。

<LearnAgentRustMap active="tools-and-graph" />

<!-- experiment-library:start -->

全书实验可从[统一代码库](./experiments.md#tools-and-graph)下载；解压后进入 `chapters/tools-and-graph/`，或在代码库根目录运行 `python3 run.py run R02`。

<!-- experiment-library:end -->

## 1. 先预测这次任务需要几轮

练习工程会自行创建临时目录，放入 `Cargo.toml` 和 `README.md`。README 中写着启动命令 `cargo run`。模型每次只能看到传入的消息；要获得文件内容，必须先提出工具请求，再由程序执行。

默认脚本模型按下面的规则推进：

| 已经看到的结果 | 本轮模型返回 | 程序接着做什么 |
| --- | --- | --- |
| 只有用户问题 | `list_files`，参数 `path="."` | 列出临时目录，回传名称列表。 |
| 已有目录列表 | `read_file`，参数 `path="README.md"` | 读取文件，回传正文。 |
| 已有 README 内容 | 核对实际返回的启动命令，给出回答 | 停止。 |

先猜一下：工具执行两次，模型应该调用几次？

答案是三次。前两次请求动作，最后一次读取工具结果并形成回答。模型轮次和工具次数从这里就开始不同；后面引入预算时，需要先说清限制的是哪一种。

::: info 源码、输出和实验范围
本章代码只有一份：<a href="/learn-agent-rust/code/tools-and-graph/src/main.rs" download>完整 Rust 源码</a> · <a href="/learn-agent-rust/tools-and-graph.zip" download>下载独立 Cargo 工程</a> · [GitHub 源码](https://github.com/lewislau86/lewislau86.github.io/blob/main/docs/public/learn-agent-rust/code/tools-and-graph/src/main.rs)。下文 Rust 片段直接导入该文件。

脚本模型实现固定版本 `langchain-rust` 的 `LLM` trait，按确定性规则返回结构化结果；文件工具真实访问程序自建的临时目录，图版真实调用 `graph-flow`。本实验验证接口接线与控制流，真实模型的选工具能力、HTTP 协议和恢复能力需要分别验收。
:::

## 2. 一份工具定义，连接描述与执行

先看模型会接触到的两个名称：

| 工具 | 参数约定 | 成功结果 |
| --- | --- | --- |
| `list_files` | `path` 必须为字符串 `"."` | `data.entries`：排序后的直接子项名称。 |
| `read_file` | `path` 必须为字符串 `"README.md"` | `data.text`：读取到的 UTF-8 正文。 |

工具需要两类信息。一类是供模型使用的名称、说明和参数 schema，让模型知道该提出什么请求；另一类是程序自己的处理函数，让请求到达以后有实际代码可以运行。

![工具注册表向模型提供名称、说明和参数约定，同时按名称把调用分发到同一条目中的处理函数。](/learn-agent-rust/figures/r02-tool-registry.svg)

顺着上方箭头看，`definitions()` 从注册表导出描述。顺着下方箭头看，`dispatch()` 用模型返回的名称查找同一份表。两条路径共用注册条目，增加工具时不必再修改循环。

<<< @/public/learn-agent-rust/code/tools-and-graph/src/main.rs#registry

`BTreeMap` 的键是工具名，值 `Tool` 把参数约定与处理函数放在一起。`handler` 是函数指针：两个工具都接收工作区路径和 JSON 参数，返回 JSON 数据或稳定的错误码。等到工具需要异步访问网络、持有连接或配置时，可以在这里引入带状态的 trait；本章先用较少的机制看清分工。

`definitions()` 采用 function tool 的描述形状。本例把描述交给脚本模型保存，用来检查配置接线；真实模型适配器还要把描述放进对应服务的工具字段，并验证返回协议。仅在内存里生成 schema，还没有发生外部模型请求。

### schema 写了约束，执行时还要做什么？

注意 `dispatch()` 的顺序：先查名称，再把原始参数字符串解析为 JSON，最后调用处理函数。未知名称返回 `unknown_tool`；JSON 格式损坏返回 `invalid_json`。

JSON 能解析，只说明它是合法 JSON。例如 `path` 的值是数字，仍然违反本章约定。因此处理函数还要检查参数：

<<< @/public/learn-agent-rust/code/tools-and-graph/src/main.rs#tools

这里没有通用 JSON Schema 校验器。真正生效的是 `PathArgs`、`deny_unknown_fields` 和处理函数里的值检查：缺少字段、类型不对、多余字段和不允许的路径都返回 `invalid_arguments`。注册表里的 schema 用于描述，应用负责让执行检查与描述一致。

`read_file` 限制返回大小，`list_files` 限制条目数并排序。排序使文件系统的枚举顺序不会改变本例输出。`canonicalize()` 检查读取目标是否仍在练习目录中；本实验面向程序自己创建的可信目录，不覆盖其他进程竞争替换文件的完整沙箱问题。

成功和失败使用同一结果外壳：`ok=true` 时读取 `data`，`ok=false` 时读取 `error`。失败也能作为明确的观察结果交回模型。这些错误码由应用定义，可以直接在源码中找到来源。

## 3. 工具名负责选择，调用 ID 负责配对

模型请求 `read_file` 时，至少需要保留三个字段：

| 字段 | 本例中的值 | 回答什么问题 |
| --- | --- | --- |
| `name` | `read_file` | 该找哪个处理函数？ |
| `arguments` | 编码为字符串的 JSON 对象 | 这次要读取什么？ |
| `id` | `read-1` | 返回结果属于哪次请求？ |

同一会话可以多次调用同名工具。只按工具名配对，就无法区分先后两次读取。执行端必须原样带回调用 ID，消息历史才能保留每次请求与结果的关系。

![默认用例中三轮模型调用穿插两条工具结果，list-1 和 read-1 各自连接请求与回传。](/learn-agent-rust/figures/r02-message-history.svg)

从上往下读。每条请求属于一条 assistant 消息，每条工具结果保留对应 ID；目录结果出现后才请求读取，读取结果出现后才产生最终回答。图中的轮次、消息顺序与调用 ID 均取自本章实际运行记录。

为了让显式版和图版保存同样的信息，先定义应用状态：

<<< @/public/learn-agent-rust/code/tools-and-graph/src/main.rs#state

`messages` 是模型能看到的有序历史，`pending` 是这轮尚待执行的调用，`seen_ids` 用于拒绝空 ID 或重复 ID。`model_turns` 和 `max_turns` 管理模型轮次，`stop` 保存应用停止原因。

`tool_dispatches` 统计进入注册表的分发尝试，包括返回错误的请求。例如未知工具也记一次分发；它并不表示处理函数执行成功，更不表示文件读取成功。

这些字段共同回答“看到了什么、还有什么待做、还能否继续”。把它们放进结构体后，图节点之间就不需要靠隐含的局部变量传递进度。

## 4. 把循环拆成两个能解释的步骤

### 第一步：调用模型，记录请求或答案

<<< @/public/learn-agent-rust/code/tools-and-graph/src/main.rs#model-turn

先检查预算，允许调用时再增加轮次。这里使用 `LLM::generate()`，因为本章需要读取结构化 `tool_calls`；只拿回答字符串会丢掉这一层信息。

返回一批调用时，先检查整批 ID，再记录 assistant 消息和 `pending`。检查使用 `seen_ids` 的副本：只要有一个 ID 无效，本批就不进入历史，也不执行其中任何工具。本章约定调用 ID 在整个会话内唯一。

返回最终文字时，追加 assistant 消息并记录停止原因。脚本模型看到错误结果后报告任务未完成，应用相应记录 `tool_error`；正常用例还会在验收中核对回答。本章先采用“任一工具错误则本次任务失败”的简单策略，后续[错误恢复](./error-recovery.md)再讨论哪些错误值得修正后继续。

### 第二步：按顺序执行待处理调用

<<< @/public/learn-agent-rust/code/tools-and-graph/src/main.rs#execute-tools

`std::mem::take()` 取走待执行列表，同时把状态中的列表留空。之后逐项分发，每项追加一条带原调用 ID 的工具消息。下一次调用模型时，就能看到这一批的全部结果。

这里的 `for` 是顺序执行。同轮出现多个调用，意味着模型在同一条 assistant 消息里提出多个动作；是否并发，仍由执行端决定。

两步合起来，显式循环只有下面这些代码：

<<< @/public/learn-agent-rust/code/tools-and-graph/src/main.rs#explicit-loop

先运行模型步骤；已有停止原因就返回，否则执行工具，再回到模型。增加第二个工具后，这段循环不需要知道 `list_files` 的名称和参数。工具扩展的变化已经留在注册表中。

## 5. 将相同的两步放进图节点

现在把视线从“用哪个工具”移到“下一步运行哪段程序”。工具注册表根据工具名称选择处理函数，图执行器根据节点结果和边选择下一节点。二者处于不同层次。

![ModelTurn 有工具请求时经 Continue 暂停并指向 ExecuteTools，工具节点完成后回到模型，出现停止原因则 End。](/learn-agent-rust/figures/r02-graph-routing.svg)

沿蓝色边走一圈：模型节点记录调用，工具节点追加结果，再回到模型。橙色分支表示模型节点已写入停止原因。每个 `Continue` 都把控制权交回本章外层驱动器，再由它推进下一个节点。

### 节点保留业务步骤，只适配图接口

<<< @/public/learn-agent-rust/code/tools-and-graph/src/main.rs#graph-nodes

两个节点都实现 `graph_flow::Task`，并调用上一节已有的函数。进入时从 `Context` 的 `agent` 键反序列化 `State`，退出前再写回。编译后的工具处理函数和模型对象仍由节点持有。

`ModelTurn` 有停止原因就返回 `End`，否则返回 `Continue`。`ExecuteTools` 执行后返回 `Continue`。节点数量始终为两个；工具从一个增加到两个，不需要再增加“读取节点”和“列目录节点”。

本章没有把工具历史写进 `Context` 的简化聊天辅助接口。应用直接序列化完整 `State`，因此 `Message.tool_calls`、工具消息 ID 和预算会一起保留。

### 建图以后，谁来继续运行？

<<< @/public/learn-agent-rust/code/tools-and-graph/src/main.rs#graph-runner

`GraphBuilder` 注册节点、连接双向边并选择起点。`Session` 保存当前位置和 `Context`；`execute_session()` 运行当前位置的节点，读取 `NextAction` 后更新推进位置。

固定版本中的几个返回值需要分清：

| 节点返回值 | 本次 `execute_session()` 的行为 | 本章用法 |
| --- | --- | --- |
| `Continue` | 找到下一节点，更新位置，返回 `Paused`。 | 外层循环再次调用。 |
| `ContinueAndExecute` | 沿边直接继续运行下一节点。 | 本章选择逐节点推进，便于观察边界。 |
| `GoTo(id)` | 将位置改到指定节点，返回 `Paused`。 | 未使用。 |
| `End` | 返回 `Completed`。 | 外层驱动器退出。 |
| `WaitForInput` | 返回 `WaitingForInput`，等待外部输入。 | 后续审批章节再讨论。 |

这些语义对应[固定 revision 的图执行源码](https://github.com/a-agmon/rs-graph-llm/blob/9bbca193f20a8c4ba23289621549ecb3d35fee64/graph-flow/src/graph.rs#L54-L148)。本章驱动器只接受预期的 `Paused` 和 `Completed`，其他状态作为错误返回。

图边在这里是固定的，是否执行工具仍由模型步骤的结构化返回决定：有工具请求走工具节点，有停止状态直接 `End`。图描述推进规则，脚本模型提供本次实验的动作请求。

### 状态保存到哪里了？

模型、节点、注册表、`Session` 和 `Context` 都在同一个 Rust 进程里，节点之间是方法调用。工具访问临时目录；退出后，`TempDir` 回收文件，内存状态随进程结束。

代码没有调用 `SessionStorage`，这里的“写回 Context”只表示进程内状态更新。跨进程恢复以及工具成功但保存失败的窗口，分别在[检查点专题](./postgres-checkpoints.md)与[外部操作可靠性](./side-effect-reliability.md)中验证。

## 6. 动手实验：核对两条路径

下载并解压<a href="/learn-agent-rust/tools-and-graph.zip" download>本章工程</a>，在解压后的 `tools-and-graph` 目录执行：

```sh
cargo run --locked
```

`rust-toolchain.toml` 固定工具链，Cargo 按 `Cargo.toml` 获取两库的 Git revision，按 `Cargo.lock` 解析传递依赖。工程没有作者电脑上的相邻仓库路径；依赖已下载并编译后，可以加 `--offline` 重跑。

本次验证环境为 macOS / Apple Silicon，Rust 1.99.1；使用 CPU 和确定性脚本模型。以下内容直接导入验证脚本保存的 stdout：

<<< @/public/learn-agent-rust/outputs/r02-summary.txt

先读正常用例：三次模型调用、两次分发、六条消息，图经过五个节点。再读 `batch`：同轮提出两个请求，模型只需两轮，消息为五条，工具仍分发两次。少掉的是一次中间模型请求与对应 assistant 消息。

`batch` 能成立，因为用户问题已经给出 README 文件名，两次调用的参数都可预先确定。如果第二个工具的参数必须从第一个结果推导，就要等结果进入上下文后再发起下一轮。

### `equal=true` 到底比较了什么？

两个驱动器分别从新的 `State` 开始，使用相同模型规则、工具定义和练习目录。`compare()` 将最终状态序列化为 JSON，逐字段比较：

- 每条消息的角色、内容、调用列表和工具结果 ID。
- 待执行列表、已经使用的 ID 集合和模型预算。
- 模型轮次、工具分发次数和应用停止原因。

此外，`check_pairs()` 检查每个请求恰有对应结果，下一条 assistant 消息出现前已补齐工具结果；用例断言核对预期轮次、消息数和停止原因。正常用例必须从真实读取结果中得到指定启动命令。这样，两个实现同时犯下相同错误时，还有固定用例契约可以拦截。

图节点轨迹单独记录，不加入相等比较。显式版没有图节点；比较的是两种推进方式对同一应用状态产生的结果。

查看完整消息：

```sh
cargo run --locked -- --json normal
cargo run --locked -- --json batch
cargo run --locked -- --json invalid-json
```

也可以查看本站保存的[正常用例 JSON](/learn-agent-rust/outputs/r02-normal.json)、[同轮双工具 JSON](/learn-agent-rust/outputs/r02-batch.json)和[坏参数 JSON](/learn-agent-rust/outputs/r02-invalid-args.json)。其中 `human` / `ai` 是该版本 `MessageType` 的序列化名称，分别对应正文里的用户 / assistant 角色。

### 从失败用例看清运行边界

| 用例 | 应看到什么 | 验证了什么 |
| --- | --- | --- |
| `unknown-tool` | 结果包含 `unknown_tool`。 | 未注册名称找不到处理函数。 |
| `invalid-json` | 结果包含 `invalid_json`。 | 参数损坏时不进入处理函数。 |
| `invalid-args` | 结果包含 `invalid_arguments`。 | 合法 JSON 仍需类型与值检查。 |
| `missing-file` | 列目录成功，读取返回 `file_unavailable`。 | 文件错误带着调用 ID 回传，最终为 `tool_error`。 |
| `duplicate-id` | 模型调用一轮，本批分发为零。 | 整批 ID 检查发生在记录请求与执行之前。 |
| `zero-budget` | 模型调用与分发均为零。 | 预算检查发生在请求模型之前。 |
| `turn-limit` | 目录工具完成，第二次模型请求被阻止。 | 停止时已完成消息配对，但尚未得到答案。 |

图返回 `Completed` 表示执行到 `End`；应用状态还要区分 `completed`、`tool_error`、`turn_limit` 和 `invalid_call_id`。即使预算耗尽，本章的图也会正常终止，业务结果仍是未完成。

本地检查命令：

```sh
cargo fmt --check
cargo test --locked
cargo clippy --locked --all-targets -- -D warnings
```

网站维护者运行 `python3 scripts/verify-learn-agent-rust-r02.py`，会先生成下载包，再在临时解压目录执行这些检查和全部用例，保存输出与带源码校验值的证据；加 `--check` 可检查产物是否过期。配图的数据图部分也核对这份证据。

## 7. 对照参考课程

![参考课程将工具描述和名称分发放进共同的工具注册结构。](/learn-agent-rust/figures/upstream/r02-tool-dispatch.svg)

这张原图展示参考课程的 Python/Claude 实现。先看名称如何进入描述，再看执行端如何按名称分发，与本章 `definitions()` 和 `dispatch()` 对照。[参考章节](https://learn.shareai.run/zh/s02/) · [原图](https://learn.shareai.run/course-assets/s02_tool_use/tool-dispatch.svg)。

![参考课程用时间线比较顺序执行与并发执行多个工具的差别。](/learn-agent-rust/figures/upstream/r02-concurrency-comparison.svg)

先看模型一次提出几项，再看执行端是否同时启动工作。图中时间数字属于上游图示，不是本章 Rust 的性能测量；本章仍按顺序执行，没有据此得出加速结论。[参考章节](https://learn.shareai.run/zh/s02/) · [原图](https://learn.shareai.run/course-assets/s02_tool_use/concurrency-comparison.svg)。

原图原样保留，来源、版本校验值与许可见[课程架构中的来源说明](./architecture.md#reference-assets)。本章自制图由本站脚本生成，顺序与计数来自本章实验。

::: warning 常见误区
- schema 是参数约定，执行入口仍需检查输入；图节点也不会替应用补上工具权限。
- 一条 assistant 消息可以含多个调用；本章逐个运行，未测量并发加速。
- 调用 ID 关联请求和结果，不能据此推断业务动作具有幂等性。
- Context 中的状态、图的 Completed、业务成功与跨进程恢复，需要分别观察。本章只验证内存中的脚本模型与两库接线。
:::

<!-- transfer-thinking:start -->

## 迁移思考：比较语义而非画法

显式版与图版都得到相同答案，足以认定行为等价吗？先给出你的判断，再展开下面的推演。

<details><summary>推演与应用</summary>

还要比较消息顺序、调用身份、累计预算与错误终态。最终文字相同可能掩盖一次重复执行。

换框架时先保留行为契约与故障样例，再替换调度机制。

</details>

这是一道迁移练习，推演不代表新增实验已通过。对照[全书审查中的证据层次](./course-review.md#evidence-layers)，说明你的判断还需要哪一级证据。

<!-- transfer-thinking:end -->

## 本章结论

从列目录再读 README 的任务出发，我们把循环中的两种选择拆清楚了：注册表按名称选择处理函数，图按节点结果推进下一步。工具描述与入口放在同一条目中，消息与预算放在同一个 `State` 中，显式版与图版复用同样的模型步骤和工具步骤。

本章在固定九种用例上核对完整状态，并保留真实文件结果、调用配对和停止原因。后续增加权限与审批时，重点就落在分发之前：收到请求以后，应用还需要判断这次动作是否可以执行。

## 从两个循环节点走向完整编排

本章把工具循环映射成 ModelTurn 与 ExecuteTools，是模型交互与图调度的接线起点。后续[第 5–7 章](./graph-orchestration.md)单独学习图编排：定义业务状态，设置条件与修复回路，保存等待中的会话，再引入并行检查、显式归并和子图边界。图节点也可以只做普通业务处理。

## 检查理解

1. 增加一个 `search_text` 工具，需要给图增加第三个节点吗？

   <details><summary>参考答案</summary>

   本章结构中，只需给注册表增加名称、参数约定和处理函数，仍由 ExecuteTools 统一分发。新能力需要独立的等待、恢复或调度边界时，再考虑新节点。工具数量与节点数量没有一一对应关系。

   </details>

2. schema 要求 `path` 是字符串，为什么处理函数仍要检查？

   <details><summary>参考答案</summary>

   schema 描述模型应该返回什么，收到的输入仍需验证。本章没有自动执行 schema 校验，由 PathArgs、deny_unknown_fields 和路径值检查决定接受哪些参数。JSON 解析成功后，类型、字段和允许值仍可能不符合约定。

   </details>

3. `Continue` 返回后，下一节点已经执行了吗？工具节点忘记添加出边又会怎样？

   <details><summary>参考答案</summary>

   固定版本中，Continue 更新下一节点位置并返回 Paused，外层驱动器再次调用后才执行下一节点。缺少出边时，框架暂停在当前节点；正常实验没有这条缺边路径，不能把 Paused 当成完成。应保留节点轨迹，并按图契约检查边和停止状态。

   </details>

4. `batch` 少用一轮模型调用，能说并发更快吗？

   <details><summary>参考答案</summary>

   只能说明同轮发出两个已知参数的请求，省去一次中间模型调用。两种用例的工具都顺序执行，本章没有测量耗时，也没有并发实验。后一个请求依赖前一个结果时，通常仍需要另一轮模型调用。

   </details>

5. 图返回 Completed，应用记录 turn_limit，是否矛盾？

   <details><summary>参考答案</summary>

   不矛盾。图已经按 End 正常终止；应用因轮次上限停止，业务问题仍未回答。图执行完成描述推进状态，任务成功需要相应的输出和行为断言。

   </details>

## 参考资料

- <a href="/learn-agent-rust/code/tools-and-graph/README.md" download>本章工程 README（下载）</a>与 <a href="/learn-agent-rust/code/tools-and-graph/Cargo.toml" download>Cargo.toml</a>：工具链、依赖与复现命令。
- 固定 revision 的 [`LLM` trait](https://github.com/Abraxas-365/langchain-rust/blob/5fc3f5aca4380da48829f95d6e2fd0217b1f2013/src/language_models/llm.rs)、[GenerateResult](https://github.com/Abraxas-365/langchain-rust/blob/5fc3f5aca4380da48829f95d6e2fd0217b1f2013/src/language_models/mod.rs)、[ToolCall](https://github.com/Abraxas-365/langchain-rust/blob/5fc3f5aca4380da48829f95d6e2fd0217b1f2013/src/schemas/tool_call.rs)与 [Message](https://github.com/Abraxas-365/langchain-rust/blob/5fc3f5aca4380da48829f95d6e2fd0217b1f2013/src/schemas/messages.rs)。
- 固定 revision 的 [`Task / NextAction`](https://github.com/a-agmon/rs-graph-llm/blob/9bbca193f20a8c4ba23289621549ecb3d35fee64/graph-flow/src/task.rs)、[GraphBuilder / execute_session](https://github.com/a-agmon/rs-graph-llm/blob/9bbca193f20a8c4ba23289621549ecb3d35fee64/graph-flow/src/graph.rs)与 [Session](https://github.com/a-agmon/rs-graph-llm/blob/9bbca193f20a8c4ba23289621549ecb3d35fee64/graph-flow/src/storage.rs)。
- [Serde：deny_unknown_fields](https://serde.rs/container-attrs.html#deny_unknown_fields)。
- [参考课程：工具使用](https://learn.shareai.run/zh/s02/)。

下一章：[第 3 章：工具权限与审批](./permissions.md)。把“请求了什么”和“允许做什么”接到同一个执行入口前。
