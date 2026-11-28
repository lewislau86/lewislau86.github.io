---
title: "第 2 章：工具注册与图调度"
description: "从先列目录、再读 README 的任务出发，用 ADK-Rust 3.0 注册工具、观察调用 ID 配对，再把同一个 Agent 放进图里，用 14 个场景核对两条路径。"
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
- 用 `FunctionTool` 注册两个工具，让工具描述、参数 schema 和处理函数来自同一处定义。
- 沿事件轨迹解释工具名称、参数和调用 ID 各自的用途，分清哪些检查由框架完成、哪些仍归应用。
- 把同一个 Agent 放进 adk-graph 的图节点，用 14 个场景核对两条路径的行为。

**前置：** 读过[第 0 章](./architecture-and-setup.md)与[第 1 章](./agent-loop.md)，理解模型请求、程序执行和结果回传的区别；能看懂结构体、枚举、`Result` 和基本 `async/await`。

**实践方式：** 下载 <a href="/learn-agent-rust/tools-and-graph.zip" download>本章 Rust 工程</a>。工程固定 Rust 1.99.1 与 ADK-Rust 3.0 的一个固定提交（3.0 尚未发布到 crates.io，见[第 6 节](#hands-on)的准备步骤）；首次获取依赖需要网络，运行实验无需模型密钥和数据库。
:::

::: info 本章已迁移到 ADK-Rust 3.0
本章实验基于 ADK-Rust 3.0 的发布候选版本。全书正在逐章迁移，尚未迁移的章节仍使用旧版实验（graph-flow 与 langchain-rust），课程地图会标出每章的版本。旧版本章可从 git 标签 `learn-agent-rust-v1` 取得。
:::

前面从“读取 README，告诉我如何启动项目”认识了一次工具往返。现在把要求稍微改一下：

> 先列出练习目录，再读取 README.md，告诉我如何启动项目。

文件名已经写在问题里，为什么还要列目录？这里刻意多走一步：让同一个助手使用两种工具，观察代码会在哪里变复杂。实际任务也常常先查看目录，再决定读取哪份说明。

上一章的循环由 ADK-Rust 的 `Runner` 和 `LlmAgent` 执行：模型提出调用，框架找到工具、执行、把结果交回模型，直到模型给出回答。工具变成两个以后，要回答三个问题：工具的描述和执行入口怎样保持一致？多次调用的结果怎样不串？循环之外的步骤（比如核对回答）放在哪里？本章分别用工具注册、调用 ID 和图调度回答。

<LearnAgentRustMap active="tools-and-graph" />

<!-- experiment-library:start -->

全书实验可从[统一代码库](./experiments.md#tools-and-graph)下载；解压后进入 `chapters/tools-and-graph/`，或在代码库根目录运行 `python3 run.py run R02`。

<!-- experiment-library:end -->

## 1. 先预测这次任务需要几轮

练习工程会自行创建临时目录，放入 `Cargo.toml` 和 `README.md`。README 中写着启动命令 `cargo run`。模型每次只能看到传入的消息；要获得文件内容，必须先提出工具请求，再由程序执行。

本章的模型是 ADK-Rust 自带的 `ScriptedLlm`：每次被调用时按顺序取出下一条预先写好的回复。正常场景的脚本是：

| 第几次调用模型 | 脚本里的回复 | 框架接着做什么 |
| --- | --- | --- |
| 1 | 调用 `list_files`，参数 `{"path": "."}` | 列出临时目录，把名称列表交回模型。 |
| 2 | 调用 `read_file`，参数 `{"path": "README.md"}` | 读取文件，把正文交回模型。 |
| 3 | 文本回答“README 里的启动命令是：cargo run” | 这是最终回答，本轮结束。 |

先猜一下：工具执行两次，模型被调用几次？

答案是三次。前两次请求动作，最后一次读取工具结果并形成回答。模型调用次数和工具执行次数从这里就开始不同；后面设置上限时，需要先说清限制的是哪一种。

脚本是固定的，但工具结果不是：文件真实读取，回答是否正确由程序对照真实读到的 README 检查（`verified`）。另外，`ScriptedLlm` 会记录模型实际收到的每一次请求，我们用它来核对“模型看到了什么”。

::: info 源码、输出和实验范围
本章代码只有一份：<a href="/learn-agent-rust/code/tools-and-graph/src/main.rs" download>完整 Rust 源码</a> · <a href="/learn-agent-rust/tools-and-graph.zip" download>下载独立 Cargo 工程</a> · [GitHub 源码](https://github.com/lewislau86/lewislau86.github.io/blob/main/docs/public/learn-agent-rust/code/tools-and-graph/src/main.rs)。下文 Rust 片段直接导入该文件。

模型回复来自固定脚本，文件工具真实访问程序自建的临时目录，Runner、LlmAgent 和图都是 ADK-Rust 的真实实现。本实验验证工具接线与控制流；真实模型的选工具能力、HTTP 协议和恢复能力需要分别验收。
:::

## 2. 一份工具定义，连接描述与执行

先看模型会接触到的两个名称：

| 工具 | 参数约定 | 成功结果 |
| --- | --- | --- |
| `list_files` | `path` 是字符串，只接受 `"."` | `entries`：排序后的直接子项名称。 |
| `read_file` | `path` 是字符串，只接受 `"README.md"` | `text`：读取到的 UTF-8 正文。 |

工具需要两类信息。一类给模型看：名称、说明和参数 schema，让模型知道该提出什么请求。另一类给程序用：处理函数，让请求到达以后有实际代码可以运行。在 ADK-Rust 里，两类信息放进同一个 `FunctionTool`：

![FunctionTool 把名称、说明、参数 schema 和处理函数放在一起；LlmAgent 向模型声明前三者，收到调用后由 FunctionTool 先按 schema 校验，再运行处理函数。](/learn-agent-rust/figures/r02-tool-registry.svg)

顺着上方箭头看，`LlmAgent` 把每个工具的名称、说明和 schema 声明给模型。顺着下方箭头看，模型返回调用以后，框架按名称找到同一个工具，`FunctionTool` 先校验参数，再运行处理函数。两条路径共用一份定义，增加工具时只是多注册一个 `FunctionTool`。

参数 schema 由 Rust 类型生成：

<<< @/public/learn-agent-rust/code/tools-and-graph/src/main.rs#schema

两个工具本身：

<<< @/public/learn-agent-rust/code/tools-and-graph/src/main.rs#tools

几处值得注意：

- `with_parameters_schema::<PathArgs>()` 用 `schemars` 从 `PathArgs` 生成 JSON Schema。它既是给模型的说明，也是 `FunctionTool` 在执行前做校验的依据。处理函数再把参数解析成 `PathArgs`，用 Rust 类型读取字段。
- `with_effect(ToolEffect::ReadOnly)` 声明工具只读。默认不重试；配置了重试预算（`RetryBudget`）以后，ADK-Rust 3.0 也只重试声明为只读或幂等、且错误可重试的调用，没有声明的工具按“非幂等”只执行一次。本章不涉及重试，[第 24 章](./error-recovery.md)和[专题 2](./side-effect-reliability.md)会用到这项声明。
- 处理函数返回 `adk_core::Result<Value>`。失败时用 `AdkError` 带上错误类别和稳定的错误码（如 `file.missing`），框架把它变成一条失败的工具结果交回模型。

`list_files` 限制条目数并排序，排序使文件系统的枚举顺序不会改变输出。`read_file` 限制返回大小，并用 `canonicalize()` 检查读取目标仍在练习目录中。这个检查面向程序自己创建的可信目录，不覆盖其他进程竞争替换文件的完整沙箱问题。

### schema 写了约束，执行时还要做什么？

`FunctionTool` 会在调用处理函数之前，按 schema 检查模型给出的参数（对象 schema 默认封闭，多余字段也算错）。这是 `FunctionTool` 的行为：用 `with_lenient_args(true)` 可以关掉，自己手写 `Tool` 实现则没有这项检查。下面三个场景都没有进入处理函数：

| 场景 | 模型给的参数 | 模型收到的结果 |
| --- | --- | --- |
| `invalid-args` | `{"path": 42}` | `failed`：`/path: 42 is not of type "string"` |
| `extra-field` | `{"path": "README.md", "mode": "raw"}` | `failed`：`Additional properties are not allowed ('mode' was unexpected)` |
| `not-an-object` | 一个 JSON 字符串，而不是对象 | `failed`：`... is not of type "object"` |

模型读到的文字以 `tool.invalid_input` 开头，说明哪里不符合 schema，并附上“按 schema 改正后重试”的提示，模型可以据此修正。稳定的错误码 `tool.invalid_arguments` 记在结果的注解里（轨迹里的 `code=`），供程序判断，不一定出现在模型读到的文字中。

还有一种更早的失败：参数根本不是合法 JSON。真实服务返回的参数是一段文本，模型适配器解析不了时不会让这一轮失败，而是用一个标记对象代替参数；`LlmAgent` 见到这个标记就不运行工具，直接回答 `not_run`：“tool 'read_file' was not run: arguments are not valid JSON …”。`invalid-json` 场景用 `adk_core::invalid_tool_arguments` 在脚本里构造这个标记。它和 `not-an-object` 不同：后者是合法 JSON、只是类型不对，走的是 schema 校验，结果是 `failed`。

schema 只管类型和形状。“`read_file` 只能读 `README.md`”这种取值规则写在处理函数里（上面的 `allowed_path`）。`outside-path` 场景让模型请求 `../secret.txt`：它是合法字符串，通过了 schema，再被处理函数以 `path.not_allowed` 拒绝。

| 检查 | 由谁负责 | 本章场景 |
| --- | --- | --- |
| 有没有这个工具 | 框架（LlmAgent） | `unknown-tool` |
| 参数能不能解码成 JSON | 模型适配器与 LlmAgent | `invalid-json` |
| 参数类型、必填字段、多余字段 | `FunctionTool`（按 schema） | `invalid-args`、`extra-field`、`not-an-object` |
| 参数取值是否允许 | 应用（处理函数） | `outside-path` |
| 动作该不该执行 | 应用策略（第 3 章） | — |

### 失败结果里，模型能看到多少？

工具失败时，交给模型的内容由错误类别决定。拒绝类错误（`InvalidInput`、`Forbidden`、`NotFound`、`Unsupported`、`Conflict`、`ResourceExhausted`）的消息是模型改正请求需要的信息，会交给模型；下游故障类错误（`Unavailable`、`Internal` 等）的消息可能含有内部主机名、路径或凭据，默认只交出类别和错误码。

| 场景 | 练习目录里的 README | 模型收到的结果 |
| --- | --- | --- |
| `missing-file` | 不存在 | `tool.not_found (file.missing): README.md does not exist` |
| `unreadable-file` | 同名目录，读取时报 I/O 错误 | `tool.unavailable (file.unreadable)`，没有消息 |
| `unreadable-file-exposed` | 同上，Agent 设置了 `expose_tool_error_messages(true)` | `tool.unavailable: read README.md: Is a directory (os error 21)` |

工具结果会发给模型服务、写进会话，所以默认隐藏是更安全的选择。需要让模型看到详细原因时，再显式打开。注意打开以后，模型读到的文字只剩类别和原文，不再带 `(file.unreadable)` 这样的错误码；错误码仍在结果注解里，轨迹中的 `code=file.unreadable` 就是从注解读出的。

## 3. 工具名负责选择，调用 ID 负责配对

模型请求 `read_file` 时，一条调用带三项信息：

| 字段 | 本例中的值 | 回答什么问题 |
| --- | --- | --- |
| `name` | `read_file` | 该找哪个工具？ |
| `args` | `{"path": "README.md"}` | 这次要读取什么？ |
| `id` | `scripted_tc_1_0` | 返回结果属于哪次请求？ |

同一会话可以多次调用同名工具。只按工具名配对，就无法区分先后两次读取。框架执行完工具，会把原调用 ID 写进结果，模型据此知道哪条结果回答了哪次请求。多数模型服务会给每个调用分配 ID；不给 ID 的服务（例如 Gemini），框架会生成 `adk-call-…` 形式的 ID。`ScriptedLlm` 在脚本没写 ID 时按“第几次模型调用、第几个调用”编号，所以第二次模型调用里的第一个调用是 `scripted_tc_1_0`。

正常场景的事件轨迹（由各章共用的轨迹片段打印，不含事件 ID、时间戳等每次运行都会变的字段）：

<!-- output-check: skip -->
```text
[assistant] call    id=scripted_tc_0_0 list_files {"path":"."}
[assistant] result  id=scripted_tc_0_0 list_files status=ok {"entries":["Cargo.toml","README.md"]}
[assistant] call    id=scripted_tc_1_0 read_file {"path":"README.md"}
[assistant] result  id=scripted_tc_1_0 read_file status=ok {"text":"# Demo\n启动命令：cargo run\n"}
[assistant] text    "README 里的启动命令是：cargo run"
[assistant] final
```

`ScriptedLlm` 记下的三次请求，按顺序列出请求里每条消息的角色：

<!-- output-check: skip -->
```text
request 0: roles=system,user tools=[read_file,list_files]
request 1: roles=system,user,model,function tools=[read_file,list_files]
request 2: roles=system,user,model,function,model,function tools=[read_file,list_files]
```

![正常场景中三次模型调用之间穿插两条工具结果，scripted_tc_0_0 和 scripted_tc_1_0 各自连接请求与结果。](/learn-agent-rust/figures/r02-message-history.svg)

`tools=[...]` 的顺序就是代码里注册工具的顺序（先 `read_file`，后 `list_files`），框架不按字母重排。从上往下读。`system` 是 Agent 的指令，`user` 是用户问题，`model` 是模型提出调用的那条消息，`function` 是框架交回的工具结果。每次请求都带着之前的全部历史，所以第三次请求能看到两次工具结果。图中的消息顺序、调用 ID 与计数均取自本章实际运行记录。

### 框架会替你检查 ID 吗？

`duplicate-id` 场景让模型在同一条回复里给两个调用写了相同的 ID `call-1`：

<!-- output-check: skip -->
```text
[assistant] call    id=call-1 list_files {"path":"."}
[assistant] call    id=call-1 read_file {"path":"README.md"}
[assistant] result  id=call-1 list_files status=ok {"entries":["Cargo.toml","README.md"]}
[assistant] result  id=call-1 read_file status=ok {"text":"# Demo\n启动命令：cargo run\n"}
```

框架照常执行了两个工具，两条结果带着同一个 ID，只能靠工具名区分。换成两次调用同一个工具，结果就无法对应。旧版本章的应用代码会在执行前拒绝整批重复 ID；ADK-Rust 3.0 不做这项检查。调用 ID 在框架里不只用于配对：每次调用的幂等键也由它组成（应用名 / 用户 / 会话 / 本次运行 / 调用 ID，[专题 2](./side-effect-reliability.md)会用到），重复 ID 会让两次调用得到相同的幂等键。如果要防御，可以在模型回复之后、工具执行之前加一道检查，[第 4 章](./hooks.md)讲这些检查点。

## 4. 循环在哪里：LlmAgent 与 Runner

工具注册好以后，交给 `LlmAgent`：

<<< @/public/learn-agent-rust/code/tools-and-graph/src/main.rs#agent

`LlmAgent` 负责“调用模型 → 执行工具 → 再调用模型”的循环，直到模型给出不含调用的回答，或者达到 `max_iterations`（默认 100 轮，每轮调用一次模型）。同一条回复里有多个调用时，默认策略是按模型给出的顺序逐个执行（`ToolExecutionStrategy::Sequential`）。

`Runner` 在外面再包一层：

<<< @/public/learn-agent-rust/code/tools-and-graph/src/main.rs#runner

它加载会话、运行 Agent、逐条保存事件，并把预算等运行规则装进这次运行（检查发生在 `LlmAgent` 行动之前）。`without_intra_compaction()` 关掉 3.0 默认开启的自动上下文压缩：压缩会调用模型写摘要，会消耗脚本里的回复、改变请求记录。压缩在[第 13 章](./context-compaction.md)专门讨论。

我们没有办法让框架“只走一步”，但可以完整观察它走了哪些步：

<<< @/public/learn-agent-rust/code/tools-and-graph/src/main.rs#events

每个事件可能带模型提出的调用（`tool_calls()`）、工具结果（`tool_results()`）或最终回答（`is_final_response()`）。把事件流和 `ScriptedLlm` 记下的请求放在一起，就能还原循环里的每一步。

### 两种上限，停在不同的位置

| 场景 | 设置 | 结果 |
| --- | --- | --- |
| `zero-budget` | `RunBudget::new().max_model_calls(0)` | 一次模型都没调用，运行以 `budget.model_calls` 结束。 |
| `turn-limit` | `max_iterations(1)` | 第一次模型调用提出 `list_files`，工具执行并留下结果；准备第二次调用时超限，运行以错误结束，没有回答。 |

`RunBudget` 是 Runner 管的整次运行预算，可以限制模型调用、工具调用、费用和时间；`max_iterations` 是这个 Agent 自己的循环上限。`turn-limit` 的错误码是 `agent.legacy`，这是框架给“未分类的 Agent 错误”的通用码，不如预算错误那样具体。两种情况下业务问题都没有得到回答。预算停止时，框架还会往会话里写一条只带错误码的停止事件（第 1 章有详细说明）；直接运行时它的作者是 `assistant`，放进图里时作者是图本身（`r02_graph`），所以本章对照轨迹时把它统一记作 `[run] stop`。

## 5. 把同一个 Agent 放进图节点

现在把视线从“用哪个工具”移到“下一步运行哪段程序”。工具按名称选择处理函数；图按边和节点结果选择下一个节点。两者处在不同层次。

在 ADK-Rust 里，模型和工具的往返留在 `LlmAgent` 内部。图调度的单位是更大的步骤：一个 Agent，或者一段普通的业务处理。本章的图有两个节点：

<<< @/public/learn-agent-rust/code/tools-and-graph/src/main.rs#graph

![图从 START 进入 assistant 节点，节点内部是 LlmAgent 完整的模型与工具往返；结束后进入 check_answer 函数节点核对回答，再到 END。](/learn-agent-rust/figures/r02-graph-routing.svg)

- `AgentNode::new(agent)` 把整个 `LlmAgent` 变成名为 `assistant` 的节点。`with_output_mapper` 从 Agent 的事件里取出最终回答和 README 正文，写进图状态的 `answer`、`readme` 两个通道。
- `check_answer` 是普通函数节点，不调用模型，只读图状态，判断回答里的命令和真实读到的 README 一致，把结论写进 `verified`。
- `GraphAgent` 本身也是一个 Agent，所以照样交给 `Runner` 运行。`output_mapper` 把图的结论变成一条事件交回 Runner；状态里没有 `verified`（`check_answer` 没有运行）时写 `verified=none`。

旧版本章把循环拆成 ModelTurn、ExecuteTools 两个图节点，由外层驱动器逐个推进。换成 ADK-Rust 后，这两步已经由 `LlmAgent` 实现，图不再介入单次工具往返。图适合的是 Agent 之外的步骤：调用前的准备、调用后的核对、分支、等待人工批准、并行检查。[第 5–7 章](./graph-orchestration.md)沿这条线展开。

`assistant` 节点在 Agent 出错时会让图失败（`turn-limit`、`zero-budget`），这时图停在 `assistant`，`check_answer` 不会运行，所以这两个场景的 `graph_check` 是 `none`。

## 6. 动手实验：核对两条路径 {#hands-on}

下载并解压<a href="/learn-agent-rust/tools-and-graph.zip" download>本章工程</a>。ADK-Rust 3.0 还没有发布到 crates.io，工程里的 `.cargo/config.toml` 把 ADK 依赖指向本目录旁边的 `adk-rust/`，所以先取一次固定提交的源码，再运行：

```sh
cd tools-and-graph
python3 fetch-adk-rust.py ../adk-rust    # 一次即可；需要 git 与 GitHub 访问
cargo run --locked
```

cargo 只读取当前目录及上级目录里的 `.cargo/config.toml`，所以命令要在 `tools-and-graph` 目录里运行。`rust-toolchain.toml` 固定工具链，`Cargo.lock` 固定全部依赖。编译时会看到 adk-core 的 3 条弃用警告（上游固定 Rust 1.95.0），不影响运行和检查。

本次验证环境为 Linux / aarch64，Rust 1.99.1，CPU 与固定脚本模型。以下内容直接导入验证脚本保存的 stdout：

<<< @/public/learn-agent-rust/outputs/r02-summary.txt

每个场景跑两遍：一遍让 `Runner` 直接运行 `LlmAgent`，一遍运行包着同一个 Agent 的 `GraphAgent`。先读正常场景：三次模型调用、两条工具结果、回答通过检查，图里的 `check_answer` 也得出同样结论。再读 `batch`：模型在同一条回复里提出两个调用，只用了两次模型调用。少掉的是一次中间请求。`graph_check=false` 表示 `check_answer` 运行了、判定回答不对；`none` 表示图没有走到这个节点。

`batch` 能成立，是因为用户问题已经给出 README 文件名，两次调用的参数都能预先确定。如果第二个工具的参数要从第一个结果里推出来，就得等结果进入上下文以后再发起下一次请求。

### `equal=true` 到底比较了什么？

两条路径各自从新会话、新的临时目录开始，使用相同的脚本和工具。比较的是：

- 事件轨迹：每个调用和结果的调用 ID、工具名、参数、状态和内容，以及最终回答。
- 模型收到的每一次请求的消息角色序列和工具声明。
- 模型调用次数、工具结果条数、停止原因，以及回答是否通过检查。

图自己的事件（作者是 `r02_graph`）不进入比较；比较的是两种运行方式下 Agent 的行为。验证脚本还逐场景检查固定契约：预期的调用次数、结果条数、停止原因、轨迹里必须出现的片段，以及调用和结果的 ID 按顺序一一对应（`duplicate-id` 里两条 ID 相同，这项检查区分不出来，要靠工具名）。两条路径同时犯同样的错误时，这些契约仍能拦下。

查看单个场景：

```sh
cargo run --locked -- --trace normal       # 事件轨迹与模型请求
cargo run --locked -- --json batch         # 两条路径的完整对照
```

也可以查看本站保存的[正常场景 JSON](/learn-agent-rust/outputs/r02-normal.json)、[同轮双调用 JSON](/learn-agent-rust/outputs/r02-batch.json)和[重复 ID JSON](/learn-agent-rust/outputs/r02-duplicate-id.json)。

### 全部场景与旧版的对应

旧版本章有 9 个场景，迁移后全部保留或拆细，共 14 个：

| 场景 | 应看到什么 | 验证了什么 | 与旧版的关系 |
| --- | --- | --- | --- |
| `normal` | 3 次模型调用，2 条结果，回答通过检查。 | 基本往返与调用 ID 配对。 | 保留 |
| `batch` | 2 次模型调用，同一回复里两个调用。 | 一条回复可以含多个调用，省去一次中间请求。 | 保留 |
| `unknown-tool` | `not_run`：`Tool search_files not found`。 | 未注册的名称由框架拒绝。 | 保留，改由框架检查 |
| `invalid-args` | `failed`，`code=tool.invalid_arguments`。 | schema 的类型检查在处理函数之前。 | 保留，改由 `FunctionTool` 检查 |
| `extra-field` | `failed`，多余字段被拒。 | 旧版靠 `deny_unknown_fields`；现在 `FunctionTool` 的对象 schema 默认封闭。 | 从 `invalid-args` 拆出 |
| `invalid-json` | `not_run`：参数不是合法 JSON，工具没有运行。 | 解码失败由适配器与 `LlmAgent` 处理，不进入 schema 校验。 | 保留 |
| `not-an-object` | `failed`，参数是 JSON 但不是对象。 | 走 schema 校验，与 `invalid-json` 结果不同。 | 新增 |
| `outside-path` | `failed`，`path.not_allowed`。 | 取值规则仍归应用。 | 从 `invalid-args` 拆出 |
| `missing-file` | 列目录成功，读取返回 `file.missing` 及原因。 | 拒绝类错误的消息交给模型。 | 保留 |
| `unreadable-file` | 读取返回 `file.unreadable`，没有消息。 | 下游故障类错误默认隐藏消息。 | 新增 |
| `unreadable-file-exposed` | 同上，带 I/O 错误原文。 | `expose_tool_error_messages(true)` 的效果。 | 新增 |
| `duplicate-id` | 两条结果带同一个 ID。 | 框架不检查 ID 重复。 | 保留，结论相反：旧版应用会拒绝 |
| `zero-budget` | 0 次模型调用，`budget.model_calls`。 | 预算在调用模型之前检查。 | 保留，改用 `RunBudget` |
| `turn-limit` | 1 次模型调用、1 条结果后以错误结束。 | 循环上限在下一次调用模型之前检查。 | 保留，改用 `max_iterations` |

本地检查命令：

```sh
cargo fmt --check
cargo test --locked
cargo clippy --locked --all-targets -- -D warnings
```

网站维护者运行 `python3 scripts/verify-learn-agent-rust-r02.py`。它先生成下载包，在临时目录解压、旁边放好 `adk-rust/`，执行上面的检查，把默认演示连跑 3 次确认输出逐字节相同，再逐个场景生成对照并检查契约，保存输出与带源码校验值的证据；加 `--check` 检查产物是否过期。

## 框架替你做了什么、没做什么

| 框架做了 | 仍归应用 |
| --- | --- |
| 把工具的名称、说明、schema 声明给模型，并保持注册顺序（请求记录可见）。 | 写清楚工具说明，让模型知道什么时候该用。 |
| 按名称找到工具；找不到时返回 `not_run`。 | 决定提供哪些工具。 |
| `FunctionTool` 在执行前按 schema 校验参数；参数不是合法 JSON 时不运行工具。 | 参数取值是否允许（路径、范围、对象归属）。 |
| 把结果连同原调用 ID 交回模型，并按错误类别决定交出多少细节。 | 给错误选对类别和稳定的错误码。 |
| 运行“模型 → 工具 → 模型”的循环，执行循环上限和运行预算。 | 选择合适的上限；判断回答是否真的完成了任务。 |
| — | 检查调用 ID 是否重复。 |
| — | 决定一个动作该不该执行（第 3 章）。 |

<!-- adk-refs:start -->

## 在 ADK-Rust 源码里

本章用到的工具注册、调用 ID 配对和循环上限，在 ADK-Rust 里分布在这几处：

| 本章内容 | 源码位置 | 对照要点 |
| --- | --- | --- |
| 把普通异步函数注册成工具 | [`adk-tool/src/function_tool.rs` · `FunctionTool::new`](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-tool/src/function_tool.rs#L59-L79) | 名字、描述和处理函数组成一个 `Tool`；参数 schema 由 `with_parameters_schema` 另行声明 |
| 工具的副作用声明 | [`adk-core/src/tool.rs` · `ToolEffect`](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-core/src/tool.rs#L668-L677) | 只有 `ReadOnly` / `Idempotent` 会被重试；未声明的工具按 `NonIdempotent` 只执行一次 |
| 同一轮多个调用怎样执行 | [`adk-core/src/tool.rs` · `ToolExecutionStrategy`](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-core/src/tool.rs#L816-L830) | 默认 `Sequential` 按模型给出的顺序逐个执行；`Auto` 只重叠相邻的只读且可并发的调用 |
| 模型往返的次数上限 | [`adk-agent/src/llm_agent.rs` · `LlmAgentBuilder::max_iterations`](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-agent/src/llm_agent.rs#L1466-L1469) | 对应本章循环的停止条件；默认 100 |
| 每次工具调用都经过的一条受控路径 | [`adk-core/src/governance.rs` · `authorize_tool_call`](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-core/src/governance.rs#L2286-L2605) | 策略、审批、预算都在这里依次检查，第 3、4 章展开 |
| 从用户输入开始一次运行 | [`adk-runner/src/runner.rs` · `Runner::run`](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-runner/src/runner.rs#L822-L829) | 运行入口（再交给 `run_with_config`）：加载会话、运行 Agent、逐条保存事件；本章的轨迹就是它产出的事件流 |
| 工具失败时交给模型多少细节 | [`adk-core/src/tool_response.rs` · `tool_error_response`](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-core/src/tool_response.rs#L368-L381) | 参数错误和拒绝类错误带消息；其余默认只给类别和错误码，`expose_message` 为真时才带原文 |
| 把 Agent 变成图节点 | [`adk-graph/src/node.rs` · `AgentNode::new`](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-graph/src/node.rs#L927-L936) | 默认从 `messages` / `input` 取输入；本章用 `with_output_mapper` 把回答写进图状态 |

源码固定在 ADK-Rust `98515241133d`（3.0.0，2026-11-26，尚未发布到 crates.io）。本节由 `scripts/learn-agent-rust-adk-refs.py` 生成。

<!-- adk-refs:end -->

## 7. 对照参考课程

![参考课程将工具描述和名称分发放进共同的工具注册结构。](/learn-agent-rust/figures/upstream/r02-tool-dispatch.svg)

这张原图展示参考课程的 Python/Claude 实现。先看名称如何进入描述，再看执行端如何按名称分发，与本章 `FunctionTool` 把描述、schema 和处理函数放在一起对照。[参考章节](https://learn.shareai.run/zh/s02/) · [原图](https://learn.shareai.run/course-assets/s02_tool_use/tool-dispatch.svg)。

![参考课程用时间线比较顺序执行与并发执行多个工具的差别。](/learn-agent-rust/figures/upstream/r02-concurrency-comparison.svg)

先看模型一次提出几项，再看执行端是否同时启动工作。图中时间数字属于上游图示，不是本章 Rust 的性能测量。ADK-Rust 默认顺序执行；`ToolExecutionStrategy::Auto` 只让相邻的、声明为只读且可并发的调用重叠执行，`Parallel` 则无条件并发。本章没有测量耗时，不据此得出加速结论。[参考章节](https://learn.shareai.run/zh/s02/) · [原图](https://learn.shareai.run/course-assets/s02_tool_use/concurrency-comparison.svg)。

原图原样保留，来源、版本校验值与许可见[课程架构中的来源说明](./architecture.md#reference-assets)。本章自制图由本站脚本生成，顺序与计数来自本章实验。

::: warning 常见误区
- schema 校验只管类型和形状；取值是否允许、动作该不该执行，仍要应用自己判断。
- 一条回复可以含多个调用；默认逐个执行，本章没有测量并发加速。
- 调用 ID 关联请求和结果，框架不保证它不重复，也不能据此推断业务动作是幂等的。
- 图运行完成、Agent 给出回答、回答正确，是三件事。本章用 `verified` 单独检查第三件。
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

本章自己就是一次“换框架”：旧版的 9 个场景先被列成契约，再逐个在 ADK-Rust 上重做，见第 6 节的对应表。其中 `duplicate-id` 的结论变了，说明替换调度机制时，故障样例比正常路径更容易暴露差别。

## 本章结论

从列目录再读 README 的任务出发，我们把三件事分清楚了：`FunctionTool` 把工具的描述、schema 和处理函数放在一起；调用 ID 让每条结果对应到它的请求；图调度的是 Agent 和普通业务步骤，模型与工具的往返留在 `LlmAgent` 里。

ADK-Rust 3.0 接手了不少原来由应用写的检查：工具是否存在、参数是否符合 schema、错误细节交给模型多少、循环和预算上限。没有接手的部分同样清楚：参数取值、调用 ID 是否重复、回答是否真的正确。下一章把注意力放在执行之前：收到请求以后，应用还要判断这次动作能不能做。

## 从 Agent 节点走向完整编排

本章的图只有 `assistant` 和 `check_answer` 两个节点，是 Agent 与图调度的接线起点。后续[第 5–7 章](./graph-orchestration.md)单独学习图编排：定义业务状态，设置条件与修复回路，保存等待中的会话，再引入并行检查、归并和子图边界。

## 检查理解

1. 增加一个 `search_text` 工具，需要给图增加第三个节点吗？

   <details><summary>参考答案</summary>

   不需要。再注册一个 `FunctionTool` 交给同一个 `LlmAgent` 即可，模型和工具的往返都在 `assistant` 节点内部完成。只有当新步骤需要在 Agent 之外单独调度（比如等待批准、并行检查、独立核对）时，才考虑新节点。工具数量与节点数量没有对应关系。

   </details>

2. schema 已经由框架校验，为什么 `read_file` 的处理函数里还要检查路径？

   <details><summary>参考答案</summary>

   schema 只描述类型和形状：`path` 是字符串、没有多余字段。`"../secret.txt"` 是合法字符串，能通过 schema。“只能读 README.md”是取值规则，要由处理函数检查，`outside-path` 场景验证了这一点。

   </details>

3. `unreadable-file` 里模型只看到 `tool.unavailable (file.unreadable)`，为什么框架不把 I/O 错误原文交给模型？

   <details><summary>参考答案</summary>

   工具结果会发给模型服务并写进会话，下游故障的原文可能含有内部路径、主机名或凭据。所以框架对 `Unavailable`、`Internal` 这类错误默认只交出类别和错误码；`NotFound`、`Forbidden`、`ResourceExhausted` 这类拒绝错误的消息是模型改正请求需要的，会交出（本章的 `dir.too_large`、`file.too_large` 也属于这一类）。确实需要时，用 `expose_tool_error_messages(true)` 打开。

   </details>

4. `batch` 少用一次模型调用，能说并发更快吗？

   <details><summary>参考答案</summary>

   只能说明一条回复里提出了两个参数已知的调用，省去一次中间请求。两个工具仍按默认策略顺序执行，本章没有测量耗时。后一个调用依赖前一个结果时，通常仍需要再请求一次模型。

   </details>

5. `turn-limit` 场景里图失败了，`zero-budget` 场景里也失败了。两者停在什么位置，留下了什么？

   <details><summary>参考答案</summary>

   `zero-budget` 在第一次调用模型之前就被预算拦下，没有任何调用和结果。`turn-limit` 完成了第一次模型调用和 `list_files`，结果已经交回，在准备第二次调用时超限。两者都没有回答，图都停在 `assistant` 节点，`check_answer` 没有运行。区分“停在哪里、留下了什么”，是后面恢复和重试的前提。

   </details>

## 参考资料

- <a href="/learn-agent-rust/code/tools-and-graph/README.md" download>本章工程 README（下载）</a>与 <a href="/learn-agent-rust/code/tools-and-graph/Cargo.toml" download>Cargo.toml</a>：工具链、依赖与复现命令。
- ADK-Rust 文档：[函数工具](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-tool/README.md)、[Runner](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-runner/README.md)、[adk-graph](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-graph/README.md)、[2.x → 3.0 迁移指南](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/docs/official_docs/migration/2.x-to-3.0.md)（均为固定提交）。
- [`ScriptedLlm` 源码](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-model/src/scripted.rs)。
- [schemars](https://docs.rs/schemars/1)：从 Rust 类型生成 JSON Schema。
- [参考课程：工具使用](https://learn.shareai.run/zh/s02/)。

下一章：[第 3 章：工具权限与审批](./permissions.md)。把“请求了什么”和“允许做什么”接到同一个执行入口前。
