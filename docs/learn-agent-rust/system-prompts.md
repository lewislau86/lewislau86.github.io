---
title: "第 15 章：系统提示词组装"
description: "用 ADK-Rust 3.0 的 static_instruction、instruction 模板和技能注入组装一次模型请求，逐次记录模型实际收到的内容，核对前缀稳定、来源 pin、模板渲染时机与执行权限。"
pageClass: learn-agent-rust-course
prev:
  text: 第 14 章 · 跨会话记忆
  link: /learn-agent-rust/memory
next:
  text: 第 16 章 · 模式选择：单次调用、工作流与自主循环
  link: /learn-agent-rust/pattern-selection
---

# 第 15 章：系统提示词组装

[课程总览](./index.md) · [上一章：跨会话记忆](./memory.md) · [学习路径](./learning-path.md#r10) · [下一章：模式选择](./pattern-selection.md)

::: tip 本章学习目标
- 说出一次模型请求由哪几部分组成、各自放在什么位置、什么时候生成，并能从实际请求里逐条核对。
- 解释为什么把技能放进用户这一轮能让请求开头保持不变，以及 `instruction` 模板为什么在一次运行中途不会更新。
- 用来源 pin 拦住被改过的技能，并用失败实验区分“资料里写了什么”和“执行器允许做什么”。

**前置：** [第 10 章：按需加载技能](./skill-loading.md)、[第 8 章：可见的任务清单](./todo-planning.md)（会话状态与 `before_model` 回调）。本章自带练习工作区，可以直接运行。

**实践方式：** 下载<a href="/learn-agent-rust/system-prompts.zip" download>完整 system-prompts.zip</a>，按[第 1 节](#hands-on)取一次 ADK-Rust 源码后运行；无需模型密钥或数据库。
:::

::: info 本章已迁移到 ADK-Rust 3.0
本章实验基于 ADK-Rust 3.0 发布候选版（固定提交，尚未发布到 crates.io）。旧版本章自己写了一个组装器：读取带版本与摘要的来源文件，自己拼消息、自己检查历史里的工具配对、自己缓存前缀，可从 git 标签 `learn-agent-rust-v1` 取得。

新版的消息由 ADK-Rust 的 `LlmAgent` 组装，历史配对由框架保证；应用只决定每部分交给哪个入口，并保留来源 pin、请求预算和执行策略。[对应表](#old-scenarios)列出了场景的变化。
:::

工作区助手接到任务：“读取 README，解释启动命令与环境要求。”

到这里，工具、权限、技能和记忆都能给模型提供内容。现在要把它们放进同一次模型请求：应用要求只读；AGENTS.md 写着“不要猜命令”；会话状态里记着语言是 `zh-CN`；技能 `startup` 建议先列命令再列环境；工具注册表里有读文件、切换语言和写文件三个工具。

这些内容分别进了哪条消息？第二次请求模型时，开头还和第一次一样吗？技能文件被人改了，下一次运行会不会悄悄用上？技能里写着“已批准写入”，执行器会照办吗？

<LearnAgentRustMap active="system-prompts" />

<!-- experiment-library:start -->

全书实验可从[统一代码库](./experiments.md#system-prompts)下载；解压后进入 `chapters/system-prompts/`，或在代码库根目录运行 `python3 run.py run R10`。

<!-- experiment-library:end -->

::: info 本章实验状态
请求的组装、模板渲染、技能选择与注入、工具声明顺序和执行策略，都是 ADK-Rust 的真实实现；README 和技能文件真实写在临时目录里。模型是按规则回复的替身，它记下每一次收到的完整请求，本章的结论都来自这些记录。替身看到技能里的“写入 summary.txt”就会照做，用来检查执行边界；真实模型会不会受诱导、会不会遵循技能，没有测试。
:::

## 1. 先运行：看模型实际收到了什么 {#hands-on}

下载并解压工程，先取一次 ADK-Rust 源码再运行：

```sh
cd system-prompts
python3 fetch-adk-rust.py ../adk-rust    # 需要 git 与 GitHub 访问；不行时加 --method cdn
cargo run --locked -- normal
```

编译时会看到 adk-core 的 3 条弃用警告（上游固定 Rust 1.95.0），不影响运行和检查。

<<< @/public/learn-agent-rust/outputs/r10-normal.txt

开头几行 `index:` 是技能索引里的三份文件：两份技能，加上 AGENTS.md，它被当成了一份名叫 `agents` 的技能，第 3 节再说。轨迹最后的 `request 0 contents` 是模型第一次收到的三条消息：

1. 第一条 `system`：应用策略，后面接着 AGENTS.md 的原文。
2. 第二条 `system`：环境，`工作区：demo-project；语言：zh-CN；只读：true。`这几个值来自会话状态。
3. `user`：先是 `[skill:startup] … [/skill]` 包着的技能正文，然后才是用户的原话。

再看它上面的 `request N` 行。`request 1` 是读完 README 之后的第二次请求，多了一条 `model`（工具调用）和一条 `function`（工具结果）。两次请求的 `prefix` 相同：`prefix` 是本章给“全部系统消息加工具声明”算的指纹（SHA-256 的前 12 个十六进制字符），它不变，说明请求的开头没有变。

摘要行里的 `session_has_skill=no` 表示技能正文只在发给模型的请求里，会话里保存的仍是用户的原话。

## 2. 一次请求由哪几部分组成

<<< @/public/learn-agent-rust/code/system-prompts/src/main.rs#wiring

`LlmAgent` 每次运行开始时组装消息，顺序是固定的：

| 部分 | 本章的入口 | 放在哪里 | 什么时候生成 |
| --- | --- | --- | --- |
| 应用策略、AGENTS.md | `static_instruction` | 第一条 `system`，原样发送 | 构建 Agent 时就定了 |
| 动态的全局说明 | `global_instruction` / `global_instruction_provider` | 下一条 `system` | 每次运行开始时 |
| 环境 | `instruction` 模板，`{键}` 读会话状态 | 再下一条 `system` | 每次运行开始时 |
| 会话历史 | 会话服务 | `system` 之后，按原顺序 | 每次运行开始时从会话读一次；运行中的模型回复和工具结果由框架在内存里追加 |
| 选中的技能 | `with_skills` | 拼在用户这一轮的原话前面 | 每次运行开始时 |
| 工具声明 | `.tool(...)` | 请求的 `tools` 字段，按注册顺序 | 每次请求模型前 |
| 应用的最后一道检查 | `before_model_callback` | 拿到整份请求，可以改、可以拦下 | 每次请求模型前 |

![应用策略与 AGENTS.md 进第一条系统消息，环境由模板读会话状态进第二条，选中的技能拼进用户这一轮，工具声明按注册顺序附在请求上；最后 before_model 回调可以检查整份请求。](/learn-agent-rust/figures/r10-input-sources.svg)

从上往下读这张图：上面四个入口，各自落到请求里的固定位置；下面的回调最后看一眼整份请求。角色由框架决定：资料里的字符串不能自己变成一条 `system` 消息。下面三节分别看模板、技能和工具。

### 花括号：模板还是原文？

`instruction` 是模板：`{workspace}`、`{locale}` 这样的花括号会被替换成会话状态里的值。一段说明如果本身就带花括号，例如 `调用工具时写成 set_target {window_id}`，放进 `instruction` 会被当成占位符：

<<< @/public/learn-agent-rust/outputs/r10-braces.txt

第一次运行把这段放进 `instruction`，会话状态里没有 `window_id`，组装就失败了，模型一次都没被调用。错误信息给了四种改法：在会话状态里设好这个键；写成 `{window_id?}`，缺了就替换成空；把这段文字移到 `static_instruction`；或者把花括号写两遍、在前面加反斜杠。最后两种写法连同双写的括号或反斜杠原样到达模型，只有 `static_instruction` 能让模型看到一字不差的原文。第二次运行用的就是它，`verbatim=yes` 表示系统消息里原样出现了 `set_target {window_id}`。

这也是本章把策略和 AGENTS.md 放进 `static_instruction` 的原因：这些文字由应用和项目维护者写，不需要读会话状态，原样发送最可靠。

### 模板在一次运行中途不会更新

用户说“先切换到英文，再读取 README”。`set_locale` 工具把会话状态里的 `locale` 改成 `en-US`：

<<< @/public/learn-agent-rust/outputs/r10-state-midrun.txt

第一次运行请求了三次模型，`locale` 一直是 `zh-CN`；`[assistant] state   locale = "en-US"` 这一行说明状态确实已经改了。（回答仍是中文，是因为替身模型按系统消息里的语言回答；真实模型还看得到工具结果里的 `en-US`，未必如此。证据是三次请求的 `locale`。）`instruction` 模板只在一次运行开始时渲染一次，运行中途改了状态，要到下一次运行才生效：第二次运行的两次请求都是 `en-US`，回答变成了英文。

需要在同一次运行里读到最新状态时，不要靠模板，改用 `before_model_callback` 在每次请求前读 `ctx.state()`（[第 8 章](./todo-planning.md)就是这样做的）。代价是：如果把它放进系统消息，请求开头会每次都变（第 3 节）；能放到后面就放到后面。

## 3. 技能放在哪里，前缀才稳定

服务商的前缀缓存（prompt caching）只复用与之前请求完全相同的开头：相同的开头越长，能复用的越多。本章没有调用真实服务，只比较 `prefix` 指纹。`skill-switch` 用两个问题各跑一次：第一个问题选中 `startup`，第二个“按 SQL 代码风格检查查询”选中 `sql-style`。两次的 `prefix` 相同，只有用户这一轮不同。

`skill-in-system` 是对照：同样两个问题，但应用自己挑技能，经 `global_instruction_provider` 放进系统消息：

<<< @/public/learn-agent-rust/outputs/r10-skill-in-system.txt

这次多了一条 `system`，两次运行的 `prefix` 不同：换一个技能，请求开头就变了。ADK-Rust 的 `with_skills` 选择把技能拼进用户这一轮，源码注释给出的理由就是让稳定的说明和历史留在可缓存的开头。`skill-update` 也一样：技能发布了新版本，`prefix` 不变，只有用户这一轮变了。

要注意“历史”只在一次运行之内稳定：技能不写进会话，下一次运行时，上一轮的用户消息从会话里取出来，已经不带技能了（`session_has_skill=no`）。跨运行能保证逐字节不变的，只有系统消息和工具声明。

![两个问题选中不同的技能：技能放在用户这一轮时，系统消息与工具声明组成的前缀相同；放进系统消息时，前缀随技能变化。](/learn-agent-rust/figures/r10-prefix-stability.svg)

左右对照：同样两个问题，只是技能放的位置不同。左边前缀相同，右边不同；下方的新版本发布也只改了用户这一轮。

技能选择本身见[第 10 章](./skill-loading.md)：按问题和技能名称、描述、正文的字词重合打分，取最高的一份。

### AGENTS.md 不该靠“选中”

技能索引扫描工作区时，会把 AGENTS.md、CLAUDE.md 这类约定文件也收进来，当成一份带 `convention` 标签的技能。可它和别的技能一起排名，每次只选一份：`agents-as-skill` 场景里，应用没有把 AGENTS.md 放进系统消息，问题选中了 `startup`，于是 `agents_md_in_request=no`，“不要猜命令”这条项目规则没有到达模型。

项目规则应当每次都在，所以本章由应用读出 AGENTS.md，放进 `static_instruction`，再用选择策略排除 `convention` 标签，免得它又被当成技能注入一遍。

## 4. 来源要能核对

技能文件放在工作区里，谁都可能改。应用发布技能时记下索引里每份文件的 ID，每次建 Agent 之前重新建索引并核对：

<<< @/public/learn-agent-rust/code/system-prompts/src/main.rs#pins

技能 ID 是名称加内容摘要的前 12 位，内容一变 ID 就变。`stale-skill` 改了 `startup` 的正文却没有更新 pin，应用在建 Agent 之前就停下（`agent_built=no`），自然也不会调用模型。文件被删掉时，错误里报的是它原来的 pin。`skill-update` 是正常的发布：改文件，同时更新 pin。

还要记住[第 10 章](./skill-loading.md)的结论：`load_skill_index` 把文件读进内存，交给 `with_skills` 的就是这份快照，之后不再读文件。已经在运行的 Agent 不会看到磁盘上的修改；要换内容，就重新建索引、重新核对、重新建 Agent。本章的 AGENTS.md 也取自这份核对过的索引，不另读文件。

摘要只能证明读到的字节和应用选定的一致，不能证明内容可信。谁有权发布技能、怎样审核，要另外设计。

## 5. 工具声明与执行权限

`tool-change` 不注册 `read_file`，请求里的工具声明少了一个，`prefix` 随之改变；模型读不了 README，答不出启动命令。工具声明是请求的一部分，增删工具就会改变请求开头。

`knowledge-injection` 发布了一份被冒用的技能，正文里混进了假系统标签：

<<< @/public/learn-agent-rust/outputs/r10-knowledge-injection.txt

看 `request 0 contents`：这段文字只出现在 `user` 这一条里（`injected_text_role=user`），没有变成真正的系统消息。可它在文字上已经“跳出”了技能块：正文里自带一个 `[/skill]`，假标签排在后面。所以包装格式只是约定，不是安全边界。

替身模型照着做了，调用 `write_file`。执行器在执行之前按策略拒绝（`status=refused`，原因“工作区只读”），`summary.txt` 没有产生。写文件的工具注册了、也声明给了模型，但声明不等于允许：允许与否由策略决定，资料里写的“已批准”不起作用。策略按顺序匹配规则，没有规则匹配的工具默认拒绝，所以本章要显式允许 `read_file` 和 `set_locale`。交互式审批见[第 3 章](./permissions.md)。

![改语言和增删工具会改变请求开头；技能被改而 pin 未更新、请求超出预算时，模型一次都不调用；技能里的假系统标签留在用户消息里，写文件被策略拒绝，summary.txt 没有产生。](/learn-agent-rust/figures/r10-change-and-permission.svg)

上面四格是会改变请求、或在调用模型前就停下的变化；下面一格是本节的注入实验：文字进了请求，动作没有被执行。

## 6. 请求预算

`before_model_callback` 能看到整份请求。本章用它算 `contents` 序列化后的字节数，超过上限就用 `BeforeModelResult::Skip` 给出一条说明，不调用模型。`budget` 场景把上限设成 300 字节，第一次请求就有 563 字节（`bytes=563`），`model_calls=0`。工具声明不在 `contents` 里，没有算进去。

字节数不是 token 数。按 token 管预算，要用服务商报告的用量，或者框架的估算（[第 13 章](./context-compaction.md)）。

### 全部场景的实际结果

<!-- r10-results:start -->

| 场景 | 结果 |
| --- | --- |
| `normal` | `model_calls=2 skill=startup@user tools=[read_file:ok] answer=中文`<br>`prefix_stable_within_run=yes`<br>`session_has_skill=no` |
| `repeat` | `model_calls=2 skill=startup@user tools=[read_file:ok] answer=中文`<br>`prefix_same=yes user_same=yes`<br>`request_identical=yes` |
| `skill-switch` | `first: model_calls=2 skill=startup@user tools=[read_file:ok] answer=中文`<br>`second: model_calls=1 skill=sql-style@user tools=[] answer=no_command`<br>`prefix_same=yes user_same=no` |
| `skill-in-system` | `first: model_calls=2 skill=startup@system tools=[read_file:ok] answer=中文`<br>`second: model_calls=1 skill=sql-style@system tools=[] answer=no_command`<br>`prefix_same=no user_same=no` |
| `env-change` | `model_calls=2 skill=startup@user tools=[read_file:ok] answer=English`<br>`prefix_same=no user_same=yes` |
| `state-midrun` | `run1: model_calls=3 skill=startup@user tools=[set_locale:ok,read_file:ok] answer=中文 locales=[zh-CN,zh-CN,zh-CN]`<br>`run2: model_calls=2 skill=startup@user tools=[read_file:ok] answer=English locales=[en-US,en-US]` |
| `tool-change` | `model_calls=1 skill=startup@user tools=[] answer=no_command`<br>`prefix_same=no user_same=yes` |
| `braces` | `in_instruction: model_calls=0 skill=- tools=[] answer=error: agent.invalid_input: State variable 'window_id' not found`<br>`in_static: model_calls=2 skill=startup@user tools=[read_file:ok] answer=中文 verbatim=yes` |
| `agents-as-skill` | `model_calls=2 skill=startup@user tools=[read_file:ok] answer=中文`<br>`agents_md_in_request=no` |
| `skill-update` | `model_calls=2 skill=startup@user tools=[read_file:ok] answer=中文`<br>`prefix_same=yes user_same=no` |
| `stale-skill` | `agent_built=no refused=stale_skill: startup` |
| `knowledge-injection` | `model_calls=2 skill=startup@user tools=[write_file:refused] answer=no_command`<br>`injected_text_role=user`<br>`summary_exists=no` |
| `budget` | `model_calls=0 skill=- tools=[] answer=request_budget bytes=563` |

<!-- r10-results:end -->

### 与旧版场景的对应 {#old-scenarios}

| 旧版（自写组装器 + 两库） | 新版（ADK-Rust） | 变化 |
| --- | --- | --- |
| `normal`、`repeat` | `normal`、`repeat` | 消息由 `LlmAgent` 组装；同样的输入，请求逐字节相同。 |
| `memory-update` | `skill-update` | 新版只有技能这一种参考资料；发布新版并更新 pin。 |
| `stale-source`、`missing-source` | `stale-skill` | pin 改为核对技能 ID（名称加内容摘要）。 |
| `environment-change` | `env-change`、`state-midrun` | 环境走 `instruction` 模板；新增运行中途改状态的对照。 |
| `tool-change` | `tool-change` | — |
| `knowledge-injection` | `knowledge-injection` | 写文件改由策略在执行前拒绝。 |
| `budget` | `budget` | 改用 `before_model_callback` 拦下。 |
| `duplicate-source`、`invalid-source` | 删除 | 技能由索引按文件收录，不再有应用自己的来源记录格式。 |
| `history-system`、`orphan-tool` | 删除 | 历史与工具配对由框架维护。 |
| `empty-context` | 删除 | 没有技能被选中时框架不注入，用户这一轮就是原话；本章没有单列场景。 |
| （无） | `skill-switch`、`skill-in-system`、`braces`、`agents-as-skill` | 技能放置与前缀、模板花括号、AGENTS.md 的位置。 |
| 14 个场景、8 项测试 | 13 个场景、6 项测试 | — |

验证脚本把工程打包后在临时目录解压，在旁边放好 ADK-Rust 源码，运行格式、Clippy、6 项 Rust 测试和离线构建；摘要和几条详细轨迹各连跑两次必须逐字节相同，并把结果表写回正文。维护者在网站仓库根目录执行：

```sh
python3 scripts/fetch-adk-rust.py .cache/adk-rust    # 只需一次；或设 ADK_RUST_SRC
python3 scripts/verify-agent-prompts.py
python3 scripts/generate-learn-agent-rust-figures.py --lesson R10
python3 scripts/verify-agent-prompts.py --check
```

## 框架替你做了什么、没做什么

| 框架做了 | 仍归应用 |
| --- | --- |
| 按固定顺序组装系统消息、历史和用户这一轮；角色由框架决定。 | 决定每段内容交给哪个入口。 |
| `instruction` 模板读会话状态，缺键时在调用模型前报错。 | 不需要读状态的文字放进 `static_instruction`。 |
| 按问题选一份技能，拼进用户这一轮，不写进会话。 | 把必须每次都在的项目规则放进系统消息。 |
| 工具声明按注册顺序；策略在执行前拒绝。 | 写策略；判断哪些工具该声明给模型。 |
| `before_model_callback` 能看、能改、能拦下整份请求。 | 请求预算、最后的检查。 |
| 历史里的工具调用与结果配对。 | 核对技能来源（pin），文件改了就重新发布。 |

<!-- adk-refs:start -->

## 在 ADK-Rust 源码里

本章的消息组装顺序、模板、技能注入、工具声明与请求前回调，在 ADK-Rust 里分布在这几处：

| 本章内容 | 源码位置 | 对照要点 |
| --- | --- | --- |
| 组装一次运行的消息 | [`adk-agent/src/llm_agent.rs` · `prepare_conversation`](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-agent/src/llm_agent.rs#L406-L578) | 依次放 `static_instruction`、全局说明、`instruction`、输出格式说明，都是 `system`；再接历史，把选中的技能拼进用户这一轮 |
| 原样发送的说明 | [`adk-agent/src/llm_agent.rs` · `LlmAgentBuilder::static_instruction`](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-agent/src/llm_agent.rs#L1246-L1249) | 不做模板替换、每次请求都一样，适合可缓存的固定说明 |
| 模板说明 | [`adk-agent/src/llm_agent.rs` · `LlmAgentBuilder::instruction`](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-agent/src/llm_agent.rs#L1205-L1208) | `{key}` 读会话状态，缺了报错；`{key?}` 缺了替换成空；`{app:key}`、`{user:key}` 读带前缀的状态 |
| 模板替换 | [`adk-core/src/instruction_template.rs` · `inject_session_state`](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-core/src/instruction_template.rs#L207-L227) | 按模板语法把占位符换成会话状态的值；它本身不管什么时候被调用 |
| 每次运行只组装一次 | [`adk-agent/src/llm_agent.rs` 第 4097 行](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-agent/src/llm_agent.rs#L4097) | 运行开始、进入模型循环之前调用；之后的请求在这份消息列表上追加模型回复和工具结果 |
| 缺键时的错误 | [`adk-core/src/instruction_template.rs` 第 160 行](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-core/src/instruction_template.rs#L160) | 提示四种改法：设好状态、改成 `{key?}`、移到 `static_instruction`，或把花括号写两遍、前面加反斜杠（这两种连同双写的括号或反斜杠原样到达模型） |
| 技能放进用户这一轮 | [`adk-agent/src/llm_agent.rs` · `LlmAgentBuilder::with_skills`](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-agent/src/llm_agent.rs#L1268-L1271) | 注释写明：放在用户这一轮，稳定的说明和历史才能留给前缀缓存 |
| 拼接技能块 | [`adk-skill/src/injector.rs` · `apply_skill_injection`](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-skill/src/injector.rs#L166-L194) | 只处理用户消息；把 `[skill:名称] 正文 [/skill]` 放在原话前面 |
| 选哪一份技能 | [`adk-skill/src/select.rs` · `select_skills`](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-skill/src/select.rs#L10-L44) | 按名称、描述、标签、正文的字词重合打分，按正文长度归一；默认只取最高的一份、最低 1 分 |
| 约定文件也进索引 | [`adk-skill/src/parser.rs` 第 129 行](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-skill/src/parser.rs#L129) | AGENTS.md 成为名叫 `agents`、带 `convention` 标签的技能，和别的技能一起排名 |
| 技能 ID | [`adk-skill/src/index.rs` · `build_document`](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-skill/src/index.rs#L15-L47) | 名称加整份文件 SHA-256 的前 12 位：内容一变 ID 就变 |
| 工具声明的顺序 | [`adk-core/src/model.rs` · `ToolDeclarations`](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-core/src/model.rs#L526-L528) | 按声明顺序保存；本章请求里的工具顺序就是注册顺序 |
| 请求前回调 | [`adk-core/src/callbacks.rs` · `BeforeModelResult`](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-core/src/callbacks.rs#L79-L84) | `Continue` 交出（可能改过的）请求；`Skip` 不调用模型，用给定的回答代替 |
| 策略规则 | [`adk-core/src/policy.rs` · `DeclarativePolicyBuilder::deny`](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-core/src/policy.rs#L806-L808) | 按顺序匹配规则；没有任何规则匹配的工具默认拒绝 |
| 执行前拒绝 | [`adk-core/src/governance.rs` 第 2430 行](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-core/src/governance.rs#L2430) | 工具不执行，模型收到带原因的结果，状态为 `refused` |

源码固定在 ADK-Rust `98515241133d`（3.0.0，2026-11-26，尚未发布到 crates.io）。本节由 `scripts/learn-agent-rust-adk-refs.py` 生成。

<!-- adk-refs:end -->

::: warning 常见误区
- **只看最终字符串，不看每部分从哪来。** 排查时要知道哪条消息来自哪个入口、什么时候生成。
- **以为改了会话状态，这次运行的系统消息就会跟着变。** 模板每次运行只渲染一次。
- **把带花括号的说明放进 `instruction`。** 它会被当成占位符；原样发送用 `static_instruction`。
- **把技能放进系统消息。** 换一个技能，请求开头就变了；前缀缓存按开头匹配。
- **以为 AGENTS.md 一定会被读到。** 它在技能索引里只是一份可选的技能。
- **把包装格式当成抗注入保证。** 正文可以自带结束标记；执行权限由策略决定。
- **把字节预算当成 token 或费用。** 本章统计的是本地序列化长度。
:::

<!-- transfer-thinking:start -->

## 迁移思考：来源决定解释方式

README 中出现“忽略系统限制”，放进 system 角色就更可信吗？先给出你的判断，再展开下面的推演。

<details><summary>推演与应用</summary>

保留每段内容的来源和角色，检查模型实际收到的完整请求，以及执行器的策略；文字放在哪个位置，不能代替应用的授权。

输入组装是一条信任链：每段内容由谁提供、为何进入、何时失效都应可追溯。

</details>

这是一道迁移练习，推演不代表新增实验已通过。对照[全书审查中的证据层次](./course-review.md#evidence-layers)，说明你的判断还需要哪一级证据。

<!-- transfer-thinking:end -->

## 本章结论

一次模型请求由几个入口拼成，每个入口有固定的位置和生成时机：应用策略与 AGENTS.md 原样进第一条系统消息；环境由模板读会话状态，每次运行渲染一次；技能拼进用户这一轮；工具按注册顺序声明。把会变的内容放在后面，请求开头才能保持不变。

模型收到了什么，可以逐次记录、逐条核对。来源有没有被改、请求是否超出预算、动作是否允许，由应用的 pin、回调和策略分别把关；资料里写了什么，不改变执行器允许做什么。

## 检查理解

1. 第二次请求多了工具调用和结果，为什么 `prefix` 没变？

   <details><summary>参考答案</summary>

   `prefix` 只覆盖全部系统消息和工具声明。工具调用与结果是历史，排在系统消息之后；系统消息在一次运行里不重新生成，工具也没增减，所以开头不变。

   </details>

2. `state-midrun` 里状态已经改成 `en-US`，为什么同一次运行的后两次请求仍是 `zh-CN`？

   <details><summary>参考答案</summary>

   `instruction` 模板在每次运行开始时渲染一次，结果用于这次运行的全部请求。状态改了，要到下一次运行才进入系统消息。需要即时生效，用 `before_model_callback` 每次读 `ctx.state()`。

   </details>

3. 把技能放进系统消息有什么代价？

   <details><summary>参考答案</summary>

   换一个技能，系统消息就变，请求开头随之改变，服务商按开头匹配的前缀缓存难以命中（`skill-in-system` 里 `prefix_same=no`）。放在用户这一轮，开头保持不变。

   </details>

4. `stale-skill` 与 `skill-update` 都改了技能文件，为什么一个被拒绝、一个照常运行？

   <details><summary>参考答案</summary>

   技能 ID 含内容摘要，改了文件 ID 就变。`skill-update` 由应用发布新版并更新 pin；`stale-skill` 没有更新 pin，核对不通过，在建 Agent 之前停下。

   </details>

5. 技能正文里的假系统标签没有变成系统消息，是否说明它无害？

   <details><summary>参考答案</summary>

   不能。它留在用户这一轮，但文字上已经跳出了技能块，替身模型也照做了，调用写文件。拦住它的是执行前的策略，不是消息格式。真实模型会不会受诱导，需要另外评估。

   </details>

## 参考资料

- [ADK-Rust 固定源码](https://github.com/zavora-ai/adk-rust/tree/98515241133d24f7e41f8fd272649035416a142f)：本课程真实运行的接口与语义基线。
- [Anthropic：Prompt caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching)：前缀缓存按请求开头匹配的服务商说明。
- [Learn Claude Code：系统提示词](https://learn.shareai.run/zh/s10/)：机制与原图参考。

## 与参考课程对照

![参考课程原图展示系统提示词从多个模块组织输入，并连接模型执行流程。](/learn-agent-rust/figures/upstream/r10-system-prompt-overview.svg)

原图保留自[系统提示词参考章节](https://learn.shareai.run/zh/s10/)，[图源](https://learn.shareai.run/course-assets/s10_system_prompt/system-prompt-overview.svg)。看不同来源怎样进入同一次模型输入；图中的 Python/Claude 接口和章节编号属于参考课程。

本章 Rust 实验逐次记录模型收到的请求，核对每部分的位置、生成时机与前缀变化。它没有复刻商业产品的内部提示词，也没有证明不同服务商对系统消息的处理完全一致。原图版本与许可见[课程架构的参考资料说明](./architecture.md#reference-assets)。

接下来先看[第五部分导读：常见 Agent 设计模式](./agent-design-patterns.md)：根据任务选择提示链、路由、并行、重规划、协调交接与人工介入。第 16–23 章附独立 Rust 工程和故障复验，从[第 16 章 · 模式选择](./pattern-selection.md)开始。

学完模式组合后进入[第 24 章 · 错误分类与恢复](./error-recovery.md)：面对来源变化、工具失败和服务异常，怎样决定是否重试，并保持停止条件和累计预算。
