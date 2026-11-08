---
title: "第 10 章：按需加载技能"
description: "用真实技能文件、langchain-rust 消息和 graph-flow 图执行，验证目录发现、按需注入、版本核对与权限边界。"
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
- 沿一次 `load_skill` 调用，追踪版本、内容摘要、调用 ID 和正文进入上下文的位置。
- 验证重复加载、文件变化和预算拒绝，并证明技能文字不会自动改变本例的工具权限。

**前置：** [第 2 章：工具注册与图调度](./tools-and-graph.md)、[第 3 章：工具权限与审批](./permissions.md)；已经完成[两库环境准备](./setup.md#install-frameworks)。本章可独立运行，不要求先完成子 Agent 实验。

**实践方式：** 下载<a href="/learn-agent-rust/skill-loading.zip" download>完整 skill-loading.zip</a>，进入解压后的 `skill-loading` 目录执行 `cargo run --locked`。固定 Rust 1.99.1，沿用 R02 的两库 Git revisions；首次下载依赖需要网络。
:::

现在工作区助手能够调用工具，也能把子任务放进独立历史。新的问题是：它接到“审查一个 Rust 函数”时，怎样知道项目约定的审查方法？

假设我们同时维护 Rust 审查规范和 SQL 查询规范。每次请求都塞入两份全文，当然能把资料送到模型面前，但这次没有数据库任务，SQL 正文也会占用输入。更合适的起点是让模型先看到一张目录，需要审查时再取出那一份方法。

这一章沿一个具体任务推进：

> 审查 `src/lib.rs`，指出空输入时的行为。

目标函数直接读取 `values[0]`。我们准备一个 `rust-review` 技能，要求“先给结论，再列证据”，并提醒说明是否执行了测试；另一个 `sql-style` 技能留在目录中。

<LearnAgentRustMap active="skill-loading" />

<!-- experiment-library:start -->

全书实验可从[统一代码库](./experiments.md#skill-loading)下载；解压后进入 `chapters/skill-loading/`，或在代码库根目录运行 `python3 run.py run R07`。

<!-- experiment-library:end -->

::: info 技术版本与复现基线
截至 2026-11-08 查阅的 [Agent Skills 规范](https://agentskills.io/specification)继续采用元数据、正文与资源渐进加载，并把 allowed-tools 标为实验字段。宿主对格式与权限的支持需单独核对；见[技术跟踪](./technology-radar.md)。
:::

::: info 本章实验状态
程序实际读取临时目录中的 `SKILL.md`，脚本模型实现固定版本 `langchain-rust` 的 `LLM` trait，`graph-flow` 实际推进 `ModelTurn` 与 `ExecuteTools`。源码、12 个场景、输出和下载包均由验证脚本核对。

模型决策是确定性规则：它按预设步骤选择工具，并根据实际工具结果决定回答格式。本实验验证接口接线、内容进入上下文的位置和应用策略；真实模型能否准确选中技能、理解说明或提高审查质量，需要在[模型评估专题](./model-evaluation.md)另外测量。
:::

## 方法与事实分别从哪里来

本章技能告诉助手“怎样审查”，具体的项目版本、API 行为或发布条件仍要从资料中找证据。下一篇 [K01：RAG](./retrieval-augmented-generation.md)验证这个证据入口；[跨会话记忆](./memory.md)保存过去确认的事实，[MCP](./mcp-tools.md)连接外部服务。四种职责可以组合，先看[关系导读](./knowledge-and-capabilities.md)。

## 1. 先跑一次：模型什么时候才看到全文？

::: info 代码与输出只有一个来源
完整工程位于网站的 `docs/public/learn-agent-rust/code/skill-loading/`，包含两个 Rust 源文件、两份技能示例、工具链和锁文件。下文代码片段直接从工程导入，输出来自实际运行记录。

<a href="/learn-agent-rust/skill-loading.zip" download>下载完整工程与实验记录</a> · [在 GitHub 查看源码](https://github.com/lewislau86/lewislau86.github.io/tree/master/docs/public/learn-agent-rust/code/skill-loading)
:::

在解压后的工程目录执行：

```sh
cargo fetch --locked
cargo run --locked
```

每次启动都会创建自己的临时技能目录和练习工作区，将随包示例写入其中，退出时由 `TempDir` 回收。程序不会扫描你安装在主目录中的全局 skills。

先预测：启动目录里会有几个技能？完整正文会加载几份？再看实际输出：

<<< @/public/learn-agent-rust/outputs/r07-normal.txt

顺着 `call_id` 阅读：`call-1` 请求 `rust-review`，同 ID 的工具结果带回来源和正文；下一轮才请求读取 `src/lib.rs`。最后回答同时使用文件里的 `values[0]` 和技能里的格式约定。SQL 的名称、说明留在目录中，全文没有进入消息历史。

![启动只展示技能目录，模型请求后才把 rust-review 正文作为工具结果加入会话，随后读取目标代码。](/learn-agent-rust/figures/r07-progressive-loading.svg)

先读左上角的目录，再沿箭头走到右下角的工具结果。加载技能本身也是一次工具往返，循环和调用 ID 配对规则继续沿用第 2 章。

## 2. 一个技能里装什么？

本例使用 Agent Skills 的目录与文档形式：一个技能一个目录，以 `SKILL.md` 保存 YAML 元信息和 Markdown 说明。下面就是随包提供的文件：

<<< @/public/learn-agent-rust/code/skill-loading/skills/rust-review/SKILL.md

`name` 用于查找，`description` 帮助判断什么时候相关，分隔线之后的正文说明具体做法。Agent Skills 还允许 `references/`、`scripts/` 和 `assets/` 等辅助资源；本章只实现元信息与正文两层，辅助资源的读取和脚本执行继续走各自的工具与权限入口。

这里的 `metadata.version` 是**课程应用增加的必填约定**，标准并不要求每个技能都带版本号。我们用它告诉读者当前拿到哪份说明，再用整份文件的 SHA-256 检测内容是否在发现之后发生变化。

| 内容 | 本章什么时候读到 | 什么时候放进模型输入 |
| --- | --- | --- |
| `name`、`description`、`metadata.version` | 启动发现时 | 组成目录，放入初始 system 消息。 |
| Markdown 正文 | 启动校验文件时会读到；加载时重新读取并核对 | 成功执行 `load_skill` 后，作为工具结果加入当前会话。 |
| 辅助参考、脚本、模板 | 本章不自动读取或执行 | 后续明确需要时，经相应工具单独处理。 |

注意这里区分了**文件读取**与**模型上下文**。本例启动时会有界读取整份小文件，解析元信息并计算摘要；节省的是没有提前发送的正文，不是声称启动时完全没有读过这些字节。

## 3. 先发现，再按注册名称加载

加载器的类型把职责分开：`Entry` 保存元信息、摘要和本地位置，`SkillStore` 持有一个目录；`Loaded` 才是加载成功后送回会话的正文及来源。

<<< @/public/learn-agent-rust/code/skill-loading/src/skills.rs#manifest

### 发现阶段建立一份会话快照

<<< @/public/learn-agent-rust/code/skill-loading/src/skills.rs#discover

启动时只扫描指定根目录的直接子目录，按顺序检查 `SKILL.md`。本例要求目录名与技能名一致；最多检查 32 个根目录条目，每份文档最多 8192 字节。这两个数是示例的应用限制，不是 Agent Skills 标准的限制。

`parse` 使用 YAML 解析器处理 frontmatter，支持示例中的嵌套 `metadata`，也支持折行说明。缺少必需字段、重复 YAML 字段和类型不符都报错：

<<< @/public/learn-agent-rust/code/skill-loading/src/skills.rs#parse

这份教学实现选择<strong>发现异常就停止启动。</strong>读者应先修复技能文件，再建立新会话。成熟客户端也可以选择跳过坏文件并给出诊断，但要明确哪些技能最终进入目录。

### 加载时，名称用于查表

`load_skill` 接收的是注册名称。模型传入 `../outside` 时，不会把它拼接成一个待读取的路径：

<<< @/public/learn-agent-rust/code/skill-loading/src/skills.rs#load

查到条目后，加载器核对路径、文件大小和 SHA-256。文件删除返回 `missing_manifest`；同版本下替换正文也会返回 `stale_skill`。成功时携带名称、版本和内容摘要，便于定位这份说明的来源。

摘要只能证明“与启动时看到的字节相同”。可信的技能来源仍需要由应用选择，SHA-256 本身不认证作者。这里的路径检查针对程序自建的静态目录；它没有解决其他进程并发替换文件时的竞争问题。

## 4. 加载成功，正文放到哪里？

先看会话中增加了哪些状态：

<<< @/public/learn-agent-rust/code/skill-loading/src/main.rs#context

`messages` 仍保存模型与工具历史；新增的 `loaded` 记录已经注入过的技能与摘要，`injected_bytes` 记录成功注入的正文体积。初始 system 消息只有目录和应用给出的使用原则。

接着看激活逻辑：

<<< @/public/learn-agent-rust/code/skill-loading/src/main.rs#activation

顺序是：重新读取并验证版本快照，检查是否已加载，再检查剩余正文额度，最后才更新状态并返回内容。额度不足时，正文和 `loaded` 都保持原样，因此不会出现“标记加载成功，但模型没收到正文”的状态。

`activate` 返回的 JSON 交给 `ExecuteTools`，通过 `Message::new_tool_message(output, call.id)` 追加到历史。它沿用第 2 章的工具结果类别，下一轮模型调用才能看到；应用没有把返回文本改写成新的 system 消息。

本例正常路径依次执行 `ModelTurn → ExecuteTools → ModelTurn → ExecuteTools → ModelTurn`。`graph-flow` 负责推进节点，`langchain-rust` 提供 `LLM` 和消息类型；技能解析、版本检查、去重与限额是课程应用写在 `SkillStore` 和 `World` 中的逻辑。

### 重复加载，还要再放一份吗？

执行：

```sh
cargo run --locked -- repeat
```

<<< @/public/learn-agent-rust/outputs/r07-repeat.txt

第二次使用新的调用 ID，但返回 `already_loaded=true`，不重复携带正文。这样每个调用都有对应结果，同时同一会话只保留一次正文注入。

![实际测得目录文本为 170 字节，两份全文为 671 字节；normal 与 repeat 的正文累计注入都为 276 字节。](/learn-agent-rust/figures/r07-context-bytes.svg)

看后两条柱的长度：加载请求从 1 次变成 2 次，累计正文仍为 276 字节。重复请求仍增加工具消息和调用开销，因此完整上下文从输出中的 1845 字节变成 2263 字节。这里统计的是 UTF-8 或 JSON 序列化字节，**不是 token 数，也不是模型费用**。

正文一旦加入历史，就会随后续请求继续发送。本章没有自动撤回或遗忘它；`loaded` 也只在本次内存会话内生效。如何压缩历史、同时维护已加载状态，由[第 12 章](./context-compaction.md)继续处理。下一章先加入[RAG 检索证据](./retrieval-augmented-generation.md)。

## 5. 技能说“允许写入”，应用就会允许吗？

先看动作分派的执行入口：

<<< @/public/learn-agent-rust/code/skill-loading/src/main.rs#dispatch

`write_file` 要先检查应用创建 `World` 时给出的 `allow_write`。加载技能的代码只修改会话中的加载记录和正文统计，没有修改这个策略字段。

现在运行一个故障场景：它在技能 frontmatter 中加入 `allowed-tools: write_file`，再在正文追加写入要求。脚本模型会故意提出写文件请求，便于观察执行边界：

```sh
cargo run --locked -- permission
```

<<< @/public/learn-agent-rust/outputs/r07-permission.txt

这段要求是故障注入数据。观察两个不同结果：技能加载成功；后续写入被拒绝。最终写入尝试为 0，没有生成 `review.txt`，被审查源码的摘要也保持不变。

![技能加载成功后提出写入请求，但应用检查 allow_write=false，按调用 ID 返回 permission_denied，未发生文件写入。](/learn-agent-rust/figures/r07-permission-boundary.svg)

沿图向下看：文字在上方进入上下文，动作仍要经过中间的策略入口。我们验证的是本应用的这条执行路径；它不是对所有提示注入的防护证明。

Agent Skills 标准将 `allowed-tools` 列为实验字段，具体客户端可以赋予它不同含义。本教学应用明确不解释它，也不从技能内容授予权限。要支持自动允许列表，必须在可信应用策略中另行定义范围，并与[审批规则](./permissions.md)一起验收。

## 6. 动手实验：改变一个条件，观察拒绝在哪发生

前面的 `normal`、`repeat` 和 `permission` 已展示主路径。下面几个实验各自改变一个条件，所有修改都发生在程序自建的临时目录。

### 实验 A：完全不加载技能

```sh
cargo run --locked -- no-skill
```

程序仍能读取同一个目标函数，但回答使用另一条固定规则，明确说明没有加载审查说明。把它与 `normal` 对比，可以确认正文是否影响了这个测试替身的数据流；它没有测量真实模型的回答质量。

### 实验 B：目录建立后，文件被改写

```sh
cargo run --locked -- changed
```

<<< @/public/learn-agent-rust/outputs/r07-changed.txt

场景保留 `1.0.0` 这个版本标签，只改变正文。加载器仍以 `stale_skill` 拒绝。本例要求在新会话重新发现技能；`version-two` 场景则在发现前将版本改成 `2.0.0`，输出会记录新的版本和摘要。

### 实验 C：正文超过注入额度

```sh
cargo run --locked -- budget
```

<<< @/public/learn-agent-rust/outputs/r07-budget.txt

该场景把累计正文额度从 2048 字节改为 16 字节。拒绝发生在注入前，`unique=0`、`injected=0`，工具错误仍与请求配对。文件大小上限负责限制单次读取，正文额度负责限制成功注入的累计体积；两者都不能替代模型总上下文管理。

### 统一核对所有场景

以下表格由验证脚本从真实运行报告生成。“错误”是工具返回的稳定错误码；出现错误后，脚本模型会说明任务未完成。

<!-- r07-results:start -->

| 场景 | 加载请求 | 正文份数 | 注入字节 | 读 / 写尝试 | 错误 |
| --- | --- | --- | --- | --- | --- |
| `normal` | 1 | 1 | 276 | 1 / 0 | — |
| `no-skill` | 0 | 0 | 0 | 1 / 0 | — |
| `repeat` | 2 | 1 | 276 | 1 / 0 | — |
| `unknown` | 1 | 0 | 0 | 0 / 0 | `unknown_skill` |
| `invalid-name` | 1 | 0 | 0 | 0 / 0 | `invalid_skill_name` |
| `changed` | 1 | 0 | 0 | 0 / 0 | `stale_skill` |
| `missing` | 1 | 0 | 0 | 0 / 0 | `missing_manifest` |
| `oversize` | 1 | 0 | 0 | 0 / 0 | `file_too_large` |
| `budget` | 1 | 0 | 0 | 0 / 0 | `context_budget` |
| `permission` | 1 | 1 | 332 | 0 / 0 | `permission_denied` |
| `version-two` | 1 | 1 | 276 | 1 / 0 | — |
| `empty-catalog` | 1 | 0 | 0 | 0 / 0 | `unknown_skill` |

<!-- r07-results:end -->

`empty-catalog` 会在发现前移除两份练习技能，目录为空；模型仍尝试加载时，应用明确返回 `unknown_skill`。`invalid-name` 检查名称输入，`missing` 检查已登记文件消失，`oversize` 检查加载时文件长大，它们在正文进入历史前就失败。

## 7. 复现与验证范围

在解压后的工程内，可以运行测试和静态检查：

```sh
cargo test --locked
cargo fmt --check
cargo clippy --locked --all-targets -- -D warnings
cargo run --locked --offline
```

依赖和工具链要先下载完整，才能离线运行。测试覆盖元信息与正文分离、名称和路径、同版本替换、文件大小、YAML 错误、版本约定、多行说明、文件删除，以及重复注入和权限边界；Unix 平台另外验证目录被替换成符号链接时的拒绝行为。

网站维护者在仓库根目录运行：

```sh
python3 scripts/verify-agent-skills.py
python3 scripts/generate-learn-agent-rust-figures.py --lesson R07
python3 scripts/verify-agent-skills.py --check
```

脚本在独立解压目录编译运行，核对 12 个场景的消息配对、图节点顺序、正文统计和实际文件结果，再解压最终下载包验证输出。证据记录工具链、源码 SHA-256 和各场景报告；配图只读取这份证据。CI 用相同检查重新验证。

本章保留的边界是：单进程、内存会话、可信静态技能目录；没有远程安装、热更新、辅助脚本执行、真实模型或跨进程恢复。正文预算只统计技能文本，总轮次与工具分派分别另有限额。

::: warning 常见误区
- **把技能加载等同于增加工具。** 加载器提供专业说明；能调用哪些工具、怎样执行仍由应用入口决定。
- **只看版本标签。** 文件同样写着 `1.0.0`，正文也可能已经不同。本例核对完整文件摘要。
- **把重复加载理解为零开销。** 正文没有重复注入，但调用、工具结果和摘要仍占用历史。
- **把 `allowed-tools` 当作所有客户端都接受的授权。** 这个实验字段的解释依赖具体实现，本章应用不从它授予权限。
- **把加载记录当成跨会话记忆。** 新会话要重新发现；压缩历史后也需要重新考虑正文与加载标记的一致性。
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

本章让技能成为现有工具循环中的一个知识入口：启动时发现目录，调用时核对来源和预算，再把正文作为工具结果写入历史。同一会话按内容快照去重，文件变化与加载失败有明确结果，后续动作继续经过应用权限检查。

这个分层解决了“所有知识提前塞进输入”的问题。技能正文加载后仍会积累在历史里，下一步要处理的就是怎样在保留事实和消息契约的前提下压缩上下文。

## 检查理解

1. 启动时已经读过技能文件，为什么仍称为按需加载？

   <details><summary>参考答案</summary>

   这里的按需指正文进入模型上下文的时机。本例启动时有界读取文件以校验格式和计算摘要，初始 system 消息只放元信息目录。正文在 `load_skill` 成功后才随工具结果进入历史。

   </details>

2. 第二次加载相同技能，为什么仍要返回工具结果？

   <details><summary>参考答案</summary>

   新请求有新的调用 ID，仍需要匹配结果。本例返回 `already_loaded=true` 和内容摘要，省略已经在历史里的正文；它仍有往返和元信息开销。

   </details>

3. 文件版本仍是 `1.0.0`，为什么可能返回 `stale_skill`？

   <details><summary>参考答案</summary>

   版本标签相同不能保证内容相同。本例比较完整文件的 SHA-256 与发现时记录的摘要，变化后要求重新建立会话快照。这个摘要不负责认证作者。

   </details>

4. 技能含有写入要求，为什么 `write_attempts` 仍为 0？

   <details><summary>参考答案</summary>

   应用没有把技能文字或 `allowed-tools` 映射成授权。`write_file` 在实际文件调用前检查 `allow_write`，该场景为 `false`，因此返回拒绝结果而没有触及写入函数。

   </details>

5. 假如压缩历史时丢掉了技能正文，却保留 `loaded`，会出现什么问题？

   <details><summary>参考答案</summary>

   再次加载可能只得到“已加载”，但模型上下文里已经没有说明。压缩历史时必须让加载标记与实际保留的正文一致，或允许重新注入。这不是本章当前内存实验已经解决的能力。

   </details>

## 参考资料

- [Learn Claude Code：s07 Skills](https://learn.shareai.run/zh/s07/)：参考目录与全文分离、通过工具结果加载说明的教学主线。
- [Agent Skills 格式规范](https://agentskills.io/specification)：目录、frontmatter、辅助资源与实验性 `allowed-tools` 字段。
- [为 Agent 添加 Skills 支持](https://agentskills.io/client-implementation/adding-skills-support)：发现、目录展示、激活、去重和上下文生命周期。
- [serde_yaml_ng 0.10.0](https://docs.rs/serde_yaml_ng/0.10.0/serde_yaml_ng/)：本例使用的 YAML 解析器。
- [Rust：canonicalize](https://doc.rust-lang.org/std/fs/fn.canonicalize.html) 与 [sha2 0.10.9](https://docs.rs/sha2/0.10.9/sha2/)：路径解析与内容摘要。

## 保留的参考原图

![参考课程将技能元信息放在启动目录中，再通过 load_skill 将完整说明作为工具结果加入会话。](/learn-agent-rust/figures/upstream/r07-skill-overview.svg)

这张图原样保留参考课程的 Python/Claude 语境、接口和编号。先看目录，再看工具结果；本章在相同教学主线上补充 Rust 两库接线、版本快照、限额、去重与权限实验。图中统计不作为本章 Rust 的运行数据。

图源：[参考章节](https://learn.shareai.run/zh/s07/) · [原图](https://learn.shareai.run/course-assets/s07_skill_loading/skill-overview.svg)。来源版本与许可见[课程架构](./architecture.md#reference-assets)。

下一篇：[第 11 章：RAG](./retrieval-augmented-generation.md)，为技能要求的结论找出当前资料与来源；随后在[第 12 章](./context-compaction.md)处理历史增长和技能重载。
