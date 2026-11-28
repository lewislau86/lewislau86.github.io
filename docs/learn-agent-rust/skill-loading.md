---
title: "第 10 章：按需加载技能"
description: "用 ADK-Rust 3.0 的 adk-skill 建技能索引，通过 SkillToolset 让模型先看目录、再按需加载正文与资源，并验证技能能让工具可见、却不能让工具获准执行。"
pageClass: learn-agent-rust-course
prev:
  text: 第 9 章 · 子 Agent 与上下文隔离
  link: /learn-agent-rust/subagents
next:
  text: 第 11 章 · RAG：检索、证据与回答
  link: /learn-agent-rust/retrieval-augmented-generation
---

# 第 10 章：按需加载技能

[课程总览](./index.md) · [上一章](./subagents.md) · [学习路径](./learning-path.md#r07) · [下一章](./retrieval-augmented-generation.md)

::: tip 本章学习目标
- 说明技能目录、技能正文和辅助资源为什么分开加载。
- 沿一次 `load_skill` 调用，追踪正文什么时候、以什么形式进入会话。
- 验证文件变化、截断、资源访问和 `allowed-tools`，区分“工具可见”与“工具获准执行”。

**前置：** [第 2 章：工具注册与图调度](./tools-and-graph.md)、[第 3 章：工具权限与审批](./permissions.md)。本章可独立运行，不要求先完成子 Agent 实验。

**实践方式：** 下载<a href="/learn-agent-rust/skill-loading.zip" download>完整 skill-loading.zip</a>，按[第 1 节](#hands-on)取一次 ADK-Rust 源码后运行；无需模型密钥或数据库。
:::

::: info 本章已迁移到 ADK-Rust 3.0
本章实验基于 ADK-Rust 3.0 发布候选版的 adk-skill（固定提交，尚未发布到 crates.io）。旧版本章自写了技能解析、版本核对、去重和注入预算，可从 git 标签 `learn-agent-rust-v1` 取得。新版的发现、索引、加载工具和 `allowed-tools` 绑定都由框架提供，几处语义与旧版不同（文件变化、重复加载、超长正文），第 8 节的对应表逐一列出。
:::

现在工作区助手能够调用工具，也能把子任务交给子 Agent。新的问题是：它接到“审查一个 Rust 函数”时，怎样知道项目约定的审查方法？

假设我们同时维护 Rust 审查规范和 SQL 查询规范。每次请求都塞入两份全文，当然能把资料送到模型面前，但这次没有数据库任务，SQL 正文也会占用输入。更合适的做法是让模型先看到一张目录，需要审查时再取出那一份方法。

这一章沿一个具体任务推进：审查 `src/lib.rs`，指出空输入时的行为。目标函数直接读取 `values[0]`。我们准备一个 `rust-review` 技能，要求“先给结论，再列证据”；另一个 `sql-style` 技能留在目录中。

<LearnAgentRustMap active="skill-loading" />

<!-- experiment-library:start -->

全书实验可从[统一代码库](./experiments.md#skill-loading)下载；解压后进入 `chapters/skill-loading/`，或在代码库根目录运行 `python3 run.py run R07`。

<!-- experiment-library:end -->

::: info 技术版本与复现基线
截至 2026-11-27 查阅的 [Agent Skills 规范](https://agentskills.io/specification)采用元数据、正文与资源渐进加载，并把 `allowed-tools` 标为实验字段。adk-skill 按这份规范解析技能，它对 `allowed-tools` 的解释见第 5 节；见[技术跟踪](./technology-radar.md)。
:::

::: info 本章实验状态
索引、`list_skills` / `load_skill` / `load_skill_resource` 三个工具、`allowed-tools` 绑定、自动注入和应用策略都是 ADK-Rust 的真实实现；技能文件和被审查的源码真实读写。模型是按规则回复的 `RuleLlm`：它按预设步骤选择工具，并根据实际工具结果决定回答格式。真实模型能否准确选中技能、理解说明，需要在[模型评估专题](./model-evaluation.md)另外测量。
:::

## 方法与事实分别从哪里来

本章技能告诉助手“怎样审查”，具体的项目版本、API 行为或发布条件仍要从资料中找证据。下一篇 [RAG](./retrieval-augmented-generation.md) 验证这个证据入口；[跨会话记忆](./memory.md)保存过去确认的事实，[MCP](./mcp-tools.md)连接外部服务。四种职责可以组合，先看[关系导读](./knowledge-and-capabilities.md)。

## 1. 先跑一次：模型什么时候才看到全文？ {#hands-on}

下载并解压工程，先取一次 ADK-Rust 源码再运行：

```sh
cd skill-loading
python3 fetch-adk-rust.py ../adk-rust    # 需要 git 与 GitHub 访问；不行时加 --method cdn
cargo run --locked -- normal
```

编译时会看到 adk-core 的 3 条弃用警告（上游固定 Rust 1.95.0），不影响运行和检查。每个场景都会创建自己的临时工作区，把随包的两份技能写进其中的 `.skills/`；程序不会扫描你主目录里的技能。

先预测：模型第一次请求时能看到 `rust-review` 的正文吗？再看实际输出：

<<< @/public/learn-agent-rust/outputs/r07-normal.txt

顺着调用 ID 阅读：`call-1` 调用 `list_skills`，得到两份技能的名称、说明和摘要（L1）；`call-2` 调用 `load_skill`，结果里才有 `rust-review` 的正文（L2），同时事件上多了一条 `skill:active:reviewer` 状态，记下“这个 Agent 激活了哪份技能、内容摘要是什么”；`call-3` 读取 `src/lib.rs`；最后回答使用了技能里的“先给结论”格式。SQL 技能只出现在目录里，正文没有进入会话。

还要注意 `list_skills` 和 `load_skill` 的结果里带着每份技能文件在本机的**绝对路径**和**修改时间**（轨迹里换成了 `$WORKSPACE`、`$MTIME` 占位符，否则两次运行不会逐字节相同）。这两项会原样进入发给模型服务的请求，也随工具结果保存在会话里：技能目录如果在用户主目录或公司内部路径下，路径本身就是要考虑的信息。

输出末尾是模型每次收到的请求：消息角色是 `user,system,user,...`，最前面那条 `user` 是 `SkillToolset` 在每次请求前加上的技能使用说明（不保存进会话）；四次请求的工具列表都是 `read_file` 加三个技能工具。

![启动时扫描 .skills 建成索引；模型先用 list_skills 看目录，再用 load_skill 取 rust-review 正文，正文作为工具结果进入会话，随后读取代码。](/learn-agent-rust/figures/r07-progressive-loading.svg)

## 2. 一个技能里装什么？

本例使用 Agent Skills 的目录与文档形式：一个技能一个目录，以 `SKILL.md` 保存 YAML 元信息和 Markdown 说明，旁边可以放 `references/`、`assets/`、`scripts/`。下面就是随包提供的文件：

<<< @/public/learn-agent-rust/code/skill-loading/skills/rust-review/SKILL.md

`name` 用于查找，`description` 帮助判断什么时候相关，分隔线之后的正文说明具体做法。`metadata.version` 是课程自己加的约定，规范并不要求；adk-skill 另外给每份技能算一个内容摘要（整份文件的 SHA-256），技能 ID 由名称加摘要前 12 位组成。

| 内容 | adk-skill 什么时候读 | 什么时候放进模型输入 |
| --- | --- | --- |
| `name`、`description` 等元信息 | 启动建索引时 | 模型调用 `list_skills` 时，作为工具结果。 |
| Markdown 正文 | 启动建索引时（索引里保存全文） | 模型调用 `load_skill` 时，作为工具结果。 |
| `references/` 等辅助资源 | 模型调用 `load_skill_resource` 时才读文件 | 作为工具结果；路径必须在技能目录里。 |

注意这里区分了**读文件**与**进入模型上下文**：索引在启动时就读了全文，按需的是正文进入会话的时机。

## 3. 先发现，再按名称加载

<<< @/public/learn-agent-rust/code/skill-loading/src/main.rs#workspace

`load_skill_index(root)` 扫描 `root/.skills/` 与 `root/.claude/skills/` 下的 Markdown 文件，还会在项目里找 `AGENTS.md`、`CLAUDE.md` 这类约定文件。和旧版相比有几处差别：

- **坏文件被跳过，不是停止启动。** `broken-skill` 场景加了一份缺少 `description` 的技能，索引照常建好，目录里仍是 2 份（框架只记一条警告）。如果你需要“技能有问题就拒绝启动”，要自己在建索引后核对数量或名单。
- **扫描范围比 `SKILL.md` 宽。** `.skills/` 下的每个 `.md` 文件都会被尝试解析（`references/`、`scripts/` 里的除外，`assets/` 里的不除外）；`AGENTS.md`、`CLAUDE.md` 这类约定文件在整个项目树里都会被找到，没有 frontmatter 也能进目录（名字是 `agents`、`claude` 这样）。把 `load_skill_index` 指向一个真实仓库之前，先看看它会把什么放进目录。
- **名称只用来查表。** `load_skill` 按名称在索引里找，`invalid-name` 传入 `../outside` 也只是“找不到这个名字”，不会被拼成路径；`unknown`、`empty-catalog` 同理。

<<< @/public/learn-agent-rust/code/skill-loading/src/main.rs#wiring

接线只有两步：建索引，把 `SkillToolset::new(索引, 工具表, 配置)` 作为一个工具集交给 LlmAgent。`SkillToolsetConfig` 的默认值是：最多同时激活 8 份技能，`load_skill` 返回的正文最多 8000 个字符，资源最多 16000 个字符，读资源前必须先加载技能（`ActivatedOnly`）。本章把 `expose_tool_error_messages` 打开：技能工具的错误属于内部错误类，默认只把类别和错误码交给模型，打开以后读者和模型都能看到“找不到这个技能”这样的原因。

## 4. 正文进了会话以后

### 索引是启动时的快照

`changed` 场景在建索引之后改写 `SKILL.md`（版本号不变，正文改成“只列证据，不给结论”）：

<<< @/public/learn-agent-rust/outputs/r07-changed.txt

`load_skill` 返回的仍是建索引时的正文，新内容根本没出现。旧版在加载时重新读文件、比对摘要，发现变化就拒绝（`stale_skill`）；adk-skill 从内存里的索引取正文，磁盘上的修改要等重新建索引（新进程）才生效。两种做法各有道理：快照保证同一次会话前后一致，代价是改了技能必须重建索引才能用上。激活记录里存了内容摘要，重建索引后摘要不符的旧激活会被丢弃，不会带着旧技能的工具继续工作。

### 重复加载，正文会再来一份

```sh
cargo run --locked -- repeat
```

<<< @/public/learn-agent-rust/outputs/r07-repeat.txt

第二次 `load_skill` 照样返回完整正文：进入会话的技能文字从 276 字节变成 552 字节。激活记录没有重复（同一份技能只记一次），但工具结果里的正文不去重。旧版返回 `already_loaded=true` 省掉正文；在 adk-skill 上，重复加载的代价要靠模型自己避免，或者在应用里拦截。

### 超长正文被截断，不是被拒绝

`truncated` 场景把 `max_instruction_chars` 调到 12：

<<< @/public/learn-agent-rust/outputs/r07-truncated.txt

`load_skill` 成功了，但正文只剩开头 12 个字符加 `[... truncated]`（这只是正文末尾的一段文字，结果里没有单独的“已截断”字段）。“先给结论”这句话没进来，规则模型于是按“没有审查说明”回答。旧版超出预算就整份拒绝；截断的风险是模型拿到半份说明，却以为自己加载成功。截断标记写在结果里，宿主可以检查它。

![normal 与 repeat 进入会话的技能正文字节，truncated 被截断后的字节，以及自动注入方式放进用户消息的字节。](/learn-agent-rust/figures/r07-context-bytes.svg)

正文一旦加入历史，就会随后续请求继续发送。如何压缩历史，由[第 13 章](./context-compaction.md)继续处理。

## 5. 技能能让工具出现，不能让工具获准

Agent Skills 规范的 `allowed-tools` 是实验字段，各家解释不同。adk-skill 的解释是：技能激活之后，它点名的工具从宿主的 `ToolRegistry` 里取出来，**加进模型可见的工具列表**。工具表由宿主提供，技能只能点名表里有的工具：

<<< @/public/learn-agent-rust/code/skill-loading/src/main.rs#tools

`permission` 场景在技能里加了 `allowed-tools: write_file`，正文要求把结论写进文件：

```sh
cargo run --locked -- permission
```

<<< @/public/learn-agent-rust/outputs/r07-permission.txt

对照请求列表：第 0、1 次请求的工具里没有 `write_file`；`load_skill` 之后的第 2 次请求起，`write_file` 出现了。模型随后调用它，应用策略拒绝（`refused`），写入次数为 0，没有生成 `review.txt`。

![技能激活后 write_file 出现在模型的工具列表里；模型调用它时，应用策略拒绝，实际写入为零。](/learn-agent-rust/figures/r07-permission-boundary.svg)

所以要分开两件事：**可见**由技能和工具表决定，**获准**由应用策略决定。还有几处边界情况：默认的 `ValidationMode::Strict` 下，技能点名的工具在工具表里找不到，`load_skill` 直接失败；工具表之后删掉了某个工具，下一次计算工具列表会出错，整个技能工具集（连同三个技能工具）在那一轮里都会消失；技能点名的工具如果和 Agent 的固定工具同名，运行会因“工具重名”失败。宿主想让技能完全不能带出某个工具，就不要把它放进工具表；放进去了，执行时仍要过[第 3 章](./permissions.md)的策略与审批。这一节验证的是本应用的执行路径，不是对所有提示注入的防护证明。

## 6. 辅助资源与激活检查

`load_skill_resource` 读技能目录里的辅助文件。路径要过两道检查：先看字面，必须是 `references/`、`assets/` 或 `scripts/` 开头的相对路径、不能含 `..`（`resource-escape` 用 `../../src/lib.rs`，在这一道就被拒绝；这个场景用 `GoogleCompatible`，否则会先被下面的激活检查挡住）；再解析真实路径，不能跑出技能目录（挡住指向外面的符号链接，本章没有单独测这一道）。`scripts/` 里的脚本只能读，adk-skill 不执行它们。

默认的 `ActivatedOnly` 要求先 `load_skill` 再读资源。`resource` 场景先直接读（应被拒绝），再加载技能，再读一次：

<<< @/public/learn-agent-rust/outputs/r07-resource.txt

第二次读取**仍被拒绝**，错误一样是“必须先加载”。这是在固定提交里实测到的行为：激活记录存在会话状态里，SkillToolset 用 `ctx.state()` 读它；而 LlmAgent 执行工具时给的上下文没有提供 `state()`（取默认的 `None`），所以检查永远认为没有激活。同一份激活记录在另一处是看得到的：每次请求前计算工具列表时，框架给 SkillToolset 的是运行的调用上下文，那里有会话状态，这就是第 5 节里 `write_file` 能出现的原因。

同一个原因的另一个后果：`load_skill` 每次都从空列表重新计算激活记录，`two-skills` 场景先后加载两份技能，第二条 `state` 行里只剩 `sql-style`。后加载的技能会让先加载的那份失去激活，它带出来的工具也从列表里消失；`max_active_skills` 这个上限实际上永远碰不到。

<<< @/public/learn-agent-rust/outputs/r07-two-skills.txt

`resource-compatible` 场景改用 `ResourceAccessPolicy::GoogleCompatible`（不要求先加载），资源就能读到，代价是“没加载技能也能读它的资源”。另外两条路：上游只需让工具上下文转交会话状态（adk-harness 自己的工具上下文就是这样做的，一行代码）；或者在应用里包一层工具，把 `ctx.session()` 的状态转交进去。这类问题值得报告给上游。

这个发现也说明了本课程固定版本、逐项实测的价值：框架文档描述的是设计意图，实际行为要以运行结果为准。

## 7. 对照：按问题自动注入

adk-skill 还有一种不需要工具的用法：LlmAgent 的 `with_skills(索引)`。每次运行开始时，框架用词法打分从索引里挑出最相关的一份（默认取 1 份、最低 1 分），把它的正文放到用户消息前面：

<<< @/public/learn-agent-rust/outputs/r07-auto-inject.txt

模型第一次请求就带着 `rust-review` 的正文（307 字节，含包装），没有调用任何技能工具，工具列表里也只有 `read_file`。打分是词法的：英文按单词切，中文每个字算一个词，得分再除以正文词数的平方根。所以中文问题也能选中，风险反而在另一面：只凭“的”“审”“查”这类单字重合，不相关的技能也可能过线。注入的正文最多 2000 个字符，超出时直接截断、不加标记；它只放进这次请求的副本，不写进会话。

| | `SkillToolset`（主线） | `with_skills` 自动注入 |
| --- | --- | --- |
| 谁决定加载 | 模型，通过工具 | 框架，按问题文字打分 |
| 正文在哪 | `load_skill` 的工具结果 | 用户消息前面 |
| 目录可见 | `list_skills` | 模型看不到目录 |
| `allowed-tools`、资源 | 支持 | 不涉及 |
| 超长正文 | 截断并加标记（默认 8000 字符） | 截断、不加标记（默认 2000 字符） |
| 是否写进会话 | 是（工具结果） | 否（只在请求副本里） |

## 8. 动手实验与结果表

以下表格由验证脚本从真实运行结果生成。

<!-- r07-results:start -->

| 场景 | load_skill 次数 | 进入会话的正文字节 | 读 / 写 | 审查格式 | 错误 |
| --- | --- | --- | --- | --- | --- |
| `normal` | 1 | 276 | 1 / 0 | 是 | — |
| `no-skill` | 0 | 0 | 1 / 0 | 否 | — |
| `repeat` | 2 | 552 | 1 / 0 | 是 | — |
| `two-skills` | 2 | 671 | 1 / 0 | 是 | — |
| `unknown` | 1 | 0 | 0 / 0 | 否 | 1 |
| `invalid-name` | 1 | 0 | 0 / 0 | 否 | 1 |
| `changed` | 1 | 276 | 1 / 0 | 是 | — |
| `broken-skill` | 1 | 276 | 1 / 0 | 是 | — |
| `truncated` | 1 | 36 | 1 / 0 | 否 | — |
| `permission` | 1 | 341 | 1 / 0 | 是 | 1 |
| `resource` | 1 | 276 | 1 / 0 | 是 | 2 |
| `resource-compatible` | 0 | 0 | 1 / 0 | 否 | — |
| `resource-escape` | 0 | 0 | 0 / 0 | 否 | 1 |
| `empty-catalog` | 1 | 0 | 0 / 0 | 否 | 1 |
| `auto-inject` | 0 | 307 | 1 / 0 | 是 | — |

<!-- r07-results:end -->

“进入会话的正文字节”统计的是 UTF-8 字节，不是 token 数，也不是模型费用。<a href="/learn-agent-rust/outputs/r07-summary.txt" download>下载全部场景的摘要</a>。

### 与旧版场景的对应 {#old-scenarios}

| 旧版（自写加载器 + 两库） | 新版（adk-skill） | 变化 |
| --- | --- | --- |
| 目录放在初始 system 消息里 | 模型调用 `list_skills` | 目录也是一次工具往返。 |
| `normal`、`no-skill` | 同名场景 | — |
| `repeat`：`already_loaded=true`，不重复注入 | `repeat`：正文再返回一次 | 框架不去重正文。 |
| `changed`：`stale_skill` 拒绝 | `changed`：返回建索引时的正文 | 索引是快照。 |
| `budget`：超出注入额度整份拒绝 | `truncated`：截断并加标记 | 部分正文进入会话。 |
| `oversize`、`missing`、`version-two` | 删除 | 都依赖“加载时重读文件”，adk-skill 不重读。 |
| 启动时坏文件停止启动 | `broken-skill`：跳过 | 坏技能不进目录。 |
| `permission`：技能文字不改变 `allow_write` | `permission`：技能让 `write_file` 可见，策略拒绝 | 区分“可见”与“获准”。 |
| `unknown`、`invalid-name`、`empty-catalog` | 同名场景 | — |
| （无） | `resource`、`resource-compatible`、`resource-escape`、`auto-inject` | 辅助资源与自动注入。 |
| 测试含 Unix 符号链接检查 | 8 项测试 | 路径检查由框架的资源读取负责；符号链接那一道本章没有单独测。 |
| （无） | `two-skills` | 实测激活记录被后一份覆盖。 |

验证脚本把工程打包后在临时目录解压，在旁边放好 ADK-Rust 源码，运行格式、Clippy、8 项 Rust 测试和离线构建；摘要和几条详细轨迹各连跑两次必须逐字节相同，并把上面的结果表写回正文。维护者在网站仓库根目录执行：

```sh
python3 scripts/fetch-adk-rust.py .cache/adk-rust    # 只需一次；或设 ADK_RUST_SRC
python3 scripts/verify-agent-skills.py
python3 scripts/generate-learn-agent-rust-figures.py --lesson R07
python3 scripts/verify-agent-skills.py --check
```

## 框架替你做了什么、没做什么

| 框架做了 | 仍归应用 |
| --- | --- |
| 扫描 `.skills/` 建索引，解析 frontmatter，算内容摘要；坏文件跳过。 | 选择可信的技能来源；需要时核对索引里的名单。 |
| `list_skills` / `load_skill` / `load_skill_resource` 三层加载；名称查表，资源路径不出技能目录。 | 改了技能要重建索引；避免重复加载带来的重复正文。 |
| `load_skill` 正文超长时截断并标记。 | 检查截断标记，决定是否接受半份说明。 |
| `allowed-tools` 只从宿主的工具表取工具，激活后加进工具列表。 | 决定工具表里放什么；执行仍由应用策略和审批把关。 |
| 记录激活了哪份技能、内容摘要是什么。 | 在固定提交里，激活记录在工具执行时读不到：读资源的检查总失败、后加载的技能覆盖先加载的；需要时改用 `GoogleCompatible` 或自己转交状态。 |

<!-- adk-refs:start -->

## 在 ADK-Rust 源码里

本章的技能索引、三层加载、allowed-tools 与自动注入，在 ADK-Rust 里分布在这几处：

| 本章内容 | 源码位置 | 对照要点 |
| --- | --- | --- |
| 建索引 | [`adk-skill/src/index.rs` · `load_skill_index`](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-skill/src/index.rs#L53-L82) | 扫描 `.skills/`、`.claude/skills/` 与约定文件；解析失败的文件只记警告并跳过 |
| 内容摘要与技能 ID | [`adk-skill/src/index.rs` · `build_document`](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-skill/src/index.rs#L15-L47) | 整份文件的 SHA-256；ID 是名称加摘要前 12 位。索引在内存里保存正文，之后不再读文件 |
| 三个技能工具 | [`adk-skill/src/progressive.rs` · `SkillToolset::core_tools`](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-skill/src/progressive.rs#L421-L427) | `list_skills`、`load_skill`、`load_skill_resource`；工具表解析出错时，整个工具集连同它们在那一轮都会消失 |
| 加载正文 | [`adk-skill/src/progressive.rs` 第 761 行](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-skill/src/progressive.rs#L761) | 正文超过 `max_instruction_chars` 时截断并加 `[... truncated]`；每次加载都返回完整正文 |
| 激活记录 | [`adk-skill/src/progressive.rs` · `SkillToolset::activate`](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-skill/src/progressive.rs#L530-L566) | 从 `ctx.state()` 读出已有激活再追加，写进 `state_delta`；工具上下文里 `state()` 为空，所以每次都从空列表开始 |
| 资源路径检查 | [`adk-skill/src/progressive.rs` · `SkillToolset::validate_resource_path`](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-skill/src/progressive.rs#L605-L621) | 只接受 `references/`、`assets/`、`scripts/` 下的相对路径；解析后不能跑出技能目录 |
| allowed-tools 变成可见工具 | [`adk-skill/src/progressive.rs` · `SkillToolset::resolve_business_tools`](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-skill/src/progressive.rs#L632-L662) | 按激活记录从宿主的 `ToolRegistry` 取工具，加进下一次请求的工具列表；执行仍经过策略 |
| 工具上下文的 state() | [`adk-agent/src/llm_agent.rs` 第 2292 行](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-agent/src/llm_agent.rs#L2292) | 这个实现没有提供 `state()`，取默认的 `None`：`resource` 场景里激活检查失败的原因 |
| 自动注入 | [`adk-skill/src/injector.rs` · `apply_skill_injection`](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-skill/src/injector.rs#L166-L194) | 按问题文字打分选出最相关的技能，把正文放到用户消息前面 |

源码固定在 ADK-Rust `98515241133d`（3.0.0，2026-11-26，尚未发布到 crates.io）。本节由 `scripts/learn-agent-rust-adk-refs.py` 生成。

<!-- adk-refs:end -->

::: warning 常见误区
- **把技能加载等同于获得权限。** `allowed-tools` 最多让工具出现在列表里；能否执行仍由应用策略决定。
- **以为改了技能文件马上生效。** 索引是启动时的快照，要重建索引才会用上新内容。
- **把截断当成成功。** `load_skill` 成功不代表正文完整，看结果里有没有截断标记。
- **把重复加载理解为零开销。** 每次 `load_skill` 都会再送一份完整正文进会话。
- **只看文档，不看运行结果。** 激活检查在固定提交里的实际行为与设计意图不同，本章用实验记录了下来。
- **以为自动注入只在英文下工作。** 中文每个字都算一个词，单字重合也可能让不相关的技能被注入。
:::

<!-- transfer-thinking:start -->

## 迁移思考：知识不携带执行权

技能写着“可删除整个仓库”，加载成功以后是否就能删除？先给出你的判断，再展开下面的推演。

<details><summary>推演与应用</summary>

保持权限策略不变，只替换技能文本；执行门仍应按原来的范围判断。

把技能当成版本化知识包，发布新知识不自动扩大宿主权限。

</details>

这是一道迁移练习，推演不代表新增实验已通过。对照[全书审查中的证据层次](./course-review.md#evidence-layers)，说明你的判断还需要哪一级证据。

<!-- transfer-thinking:end -->

## 本章结论：目录先出现，正文按需进入会话

adk-skill 把技能变成工具循环里的一个知识入口：启动时建索引，模型先看目录，需要时加载正文和资源，正文作为工具结果进入会话。技能可以通过 `allowed-tools` 让宿主工具表里的工具出现在列表里，但执行仍要经过应用策略。

和旧版自写的加载器相比，索引快照、正文不去重、超长截断是框架的取舍，应用要知道它们；读资源的激活检查则是实测到的问题，需要绕开。技能正文加载后仍会积累在历史里，下一步要处理的就是压缩上下文。

## 检查理解

1. 启动时索引已经读过技能全文，为什么仍称为按需加载？

   <details><summary>参考答案</summary>

   按需指的是正文进入模型上下文的时机。索引在启动时读了全文、算了摘要，但模型一开始只能通过 `list_skills` 看到元信息；正文在 `load_skill` 成功后才作为工具结果进入会话。

   </details>

2. `changed` 场景里文件已经改了，为什么 `load_skill` 返回旧内容？

   <details><summary>参考答案</summary>

   adk-skill 从启动时建好的索引里取正文，不重新读文件。索引是快照，磁盘上的修改要等重建索引才会出现；`SkillToolset` 持有建好的那份索引，所以重新调用 `load_skill_index` 之后还要用新索引重建工具集和 Agent。

   </details>

3. 技能声明了 `allowed-tools: write_file`，为什么 `writes=0`？

   <details><summary>参考答案</summary>

   激活后 `write_file` 从宿主的工具表里取出、出现在模型的工具列表里，模型也调用了它；但应用策略拒绝 `write_file`，工具没有执行。技能决定的是可见，策略决定的是获准。

   </details>

4. `truncated` 场景的 `load_skill` 是成功的，为什么回答没有用审查格式？

   <details><summary>参考答案</summary>

   正文超过 `max_instruction_chars`，被截成开头 12 个字符加截断标记，“先给结论”这条要求没有进入会话。工具调用成功不代表说明完整。

   </details>

5. 为什么 `resource` 场景里加载了技能之后，读资源仍被拒绝？

   <details><summary>参考答案</summary>

   激活记录保存在会话状态里，而在这个固定提交里，执行工具时的上下文拿不到会话状态，激活检查因此总认为没有加载。这是实测到的框架行为；需要读资源时可以改用 `GoogleCompatible`（代价是不再要求先加载），或者让工具上下文转交会话状态。

   </details>

## 参考资料

- [Learn Claude Code：s07 Skills](https://learn.shareai.run/zh/s07/)：参考目录与全文分离、通过工具结果加载说明的教学主线。
- [Agent Skills 格式规范](https://agentskills.io/specification)：目录、frontmatter、辅助资源与实验性 `allowed-tools` 字段。
- [为 Agent 添加 Skills 支持](https://agentskills.io/client-implementation/adding-skills-support)：发现、目录展示、激活、去重和上下文生命周期。
- [adk-skill 固定源码](https://github.com/zavora-ai/adk-rust/tree/98515241133d24f7e41f8fd272649035416a142f/adk-skill/src)：本课程真实运行的接口与语义基线。

## 保留的参考原图

![参考课程将技能元信息放在启动目录中，再通过 load_skill 将完整说明作为工具结果加入会话。](/learn-agent-rust/figures/upstream/r07-skill-overview.svg)

这张图原样保留参考课程的 Python/Claude 语境、接口和编号。本章在相同教学主线上换成 adk-skill 的三层加载工具，并补充快照、截断、资源与权限实验。图中统计不作为本章 Rust 的运行数据。

图源：[参考章节](https://learn.shareai.run/zh/s07/) · [原图](https://learn.shareai.run/course-assets/s07_skill_loading/skill-overview.svg)。来源版本与许可见[课程架构](./architecture.md#reference-assets)。

下一篇：[第 11 章：RAG](./retrieval-augmented-generation.md)，为技能要求的结论找出当前资料与来源；随后在[第 13 章](./context-compaction.md)处理历史增长。
