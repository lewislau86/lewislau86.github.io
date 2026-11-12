---
title: "第 12 章：上下文压缩"
description: "沿一次连续代码审查，使用真实归档、结构化摘要和图节点，验证预算、事实保留、工具配对与压缩后的技能重载。"
pageClass: learn-agent-rust-course
prev:
  text: 第 11 章 · RAG：检索、证据与回答
  link: /learn-agent-rust/retrieval-augmented-generation
next:
  text: 第 13 章 · 跨会话记忆
  link: /learn-agent-rust/memory
---

# 第 12 章：上下文压缩

[课程总览](./index.md) · [上一章](./retrieval-augmented-generation.md) · [学习路径](./learning-path.md#r08) · [下一章](./memory.md)

::: tip 本章学习目标
- 区分旧结果占位、大结果落盘和历史摘要，解释每一步保留了什么。
- 在模型调用前控制上下文预算，保持工具请求与结果完整配对。
- 用有来源的事实清单检查摘要，并观察失败回滚、归档读取和技能重新加载。

**前置：** [第 1 章：最小 Agent 循环](./agent-loop.md)、[第 10 章：按需加载技能](./skill-loading.md)，以及[两库环境准备](./setup.md#install-frameworks)。

**实践方式：** 下载<a href="/learn-agent-rust/context-compaction.zip" download>完整 context-compaction.zip</a>，进入解压后的 `context-compaction` 执行 `cargo run --locked`。固定 Rust 1.99.1，沿用 R02、R07 的 graph-flow 与 langchain-rust Git revisions；首次获取依赖需要网络。
:::

前面的技能章节把审查方法按需放进消息历史，紧接着的 [RAG 专题](./retrieval-augmented-generation.md)解释如何选取当前证据。本章沿用技能审查实验，观察助手又读了几份文档、记下调查过程后怎样继续；RAG 工具与本章两库工程的接线需要单独验收。此时，每一轮请求都会携带这些旧内容；新读一份文件，还会继续增加输入。

我们延续一个具体任务：审查 `src/first.rs`，确认空输入会发生什么。用户明确要求：禁止修改文件；没有运行测试，就要说明“未运行测试”。旧工具结果里已经出现了目标路径和 `values[0]`，但最近几条消息只是在整理文档目录。

现在需要腾出空间。先猜一猜：只留下最近几条消息，助手还能知道该读哪个文件吗？如果摘要写着“测试通过”，我们又靠什么发现它没有依据？

<LearnAgentRustMap active="context-compaction" />

<!-- experiment-library:start -->

全书实验可从[统一代码库](./experiments.md#context-compaction)下载；解压后进入 `chapters/context-compaction/`，或在代码库根目录运行 `python3 run.py run R08`。

<!-- experiment-library:end -->

::: info 本章实验状态
Agent 与摘要器都实现固定版本 `langchain-rust` 的 `LLM` trait，`graph-flow` 实际推进三个节点。程序真实创建、读取练习文件与归档，脚本模型根据收到的消息继续行动；不请求外部模型服务。

实验验证确定性的压缩机制、协议结构和故障处理。事实清单针对这个固定审查任务定义，校验器检查其值与来源是否保留；它没有自动评判任意自然语言摘要的真实性。真实模型的摘要质量需要另做[质量评估](./model-evaluation.md)。
:::

## 1. 先运行：压缩之后还要能继续做事

::: info 代码与输出只有一个来源
完整工程在 `docs/public/learn-agent-rust/code/context-compaction/`，包含 `main.rs`、`compact.rs`、`tests.rs`、工具链与锁文件。下文片段直接导入工程，输出来自实际运行。

[下载工程](/learn-agent-rust/context-compaction.zip) · <a href="/learn-agent-rust/code/context-compaction/README.md" download>运行说明</a> · [GitHub 源码](https://github.com/lewislau86/lewislau86.github.io/tree/master/docs/public/learn-agent-rust/code/context-compaction)
:::

```sh
cargo run --locked
```

<<< @/public/learn-agent-rust/outputs/r08-normal.txt

读输出时先找 `prepare[1]`，再看最后的回答。首次模型输入经过大结果落盘、旧结果占位和摘要三步缩短，最后仍能定位 `src/first.rs`，重新读取文件，给出空输入越界的结论，并明确说“未运行测试”。

`summary_calls=1` 与 `agent_calls=3` 分开计数：摘要也需要一次模型调用。模型没有靠私下访问事实表来回答；Agent 的 `generate` 只接收处理后的消息，目标路径来自其中的摘要或工具结果。

种子历史是程序从真实临时文件读取后，按固定步骤构造的一段已结束对话；其中一次 assistant 消息同时包含两个工具调用。这样每次实验具有相同的起点，能够专门观察压缩。临时目录在退出时清理，输出中的归档 ID 只在同次运行内有效。

## 2. 把压缩放在每次模型调用之前

每一轮依次检查历史结构、归档原始记录、缩短工具结果；如果仍超过触发线，再尝试摘要。成功后才把候选历史交给下一节点。

![应用先保存原始记录，再缩短工具结果、验证摘要和预算，成功后才向模型提供新上下文。](/learn-agent-rust/figures/r08-compaction-pipeline.svg)

沿上方流程阅读：大结果先保存，随后才允许替换文字。下方的返回路径表示压缩后的请求仍要重新加载技能、读取源码，再得到最终回答。

| 操作 | 改动的位置 | 留下什么 | 本例是否调用摘要模型 |
| --- | --- | --- | --- |
| 大结果落盘 | 超过 1200 字节的工具正文 | 注册 ID、大小、SHA-256、64 字符预览 | 否 |
| 旧结果占位 | 最近两份工具结果之前、超过 180 字节的正文 | 原消息键、SHA-256、原工具调用 ID | 否 |
| 历史摘要 | 较早的完整消息组 | 首条 system、用户消息、事实摘要与最近两个完整组 | 是 |

这些阈值是课程示例参数。原始记录已经写入 JSONL，所以旧结果占位虽然只留下提示，仍有对应的原消息可供追查。大结果的专用归档引用会继续保留，便于通过工具分段读取。

### 字节预算怎样算？

先看类型与计算函数：

<<< @/public/learn-agent-rust/code/context-compaction/src/compact.rs#types

`Item.key` 是应用给消息分配的稳定身份，用来标记事实来源。它不会加入模型输入；`wire` 只取 `Message`，`bytes` 对这份消息数组做 JSON 序列化后计数。因此归档中还包含消息键，其大小会比模型输入多一些。

本例使用两条线：

- `messages_bytes + reserve > trigger` 时准备压缩，默认触发线为 5200 字节。
- 每次交给 Agent 模型之前，要求 `messages_bytes + reserve <= hard`，默认上限为 7500 字节，预留 1024 字节。

预留量用于演示给后续输出和工具描述留空间。它是教学预算，**没有换算成 token，也没有计算真实 HTTP 请求或账单**。接入 provider 时，要按它的 tokenizer 或计数接口统计包含工具定义、system、图像等内容的实际请求，再按模型窗口与输出上限分配额度。可对照 [token counting 官方说明](https://platform.claude.com/docs/en/build-with-claude/token-counting)。

## 3. 工具调用与结果要一起移动

初始历史中，`old-skill` 与 `old-source` 来自同一条 assistant 消息，随后才有两条工具结果。直接按数组下标切开，可能只留下结果，或者删掉一半结果。

![同一 assistant 中的两个工具调用及其全部结果构成一个整体，摘要切口放在完整组边界。](/learn-agent-rust/figures/r08-message-groups.svg)

左边的三个框属于一个消息组；即使两份结果返回顺序不同，也要等它们都出现后才能结束这一组。右边表示 normal 场景留下最近两个完整组，较早历史才进入摘要范围。

<<< @/public/learn-agent-rust/code/context-compaction/src/compact.rs#groups

`groups` 检查消息键和调用 ID 是否重复，用待完成集合接收对应工具结果。它直接反序列化 `tool_calls`；格式不合法会报错，避免把解析失败误认为“没有调用”。

两种停止原因值得区分：

| 情况 | 处理 |
| --- | --- |
| 请求后还缺工具结果 | `pending_tools`，先结束这一批工具再压缩 |
| 结果找不到请求、结果重复或调用 ID 被重用 | `invalid_history`，修复协议结构 |

实验只支持纯文本与结构化工具调用，遇到图像或 thinking 内容返回 `unsupported_content`。它没有把其他 provider 的多模态、签名或缓存规则当成普通文本删掉。

## 4. 大结果先落盘，再缩短正文

`Store` 用程序自己创建的临时归档目录，按 `a1`、`a2` 这样的注册 ID 保存内容。模型不能传入任意本地路径。

<<< @/public/learn-agent-rust/code/context-compaction/src/compact.rs#archive

`transcript` 将压缩前的 `Item` 逐行写入 JSONL；每份归档记录大小和 SHA-256。实验会重新读取 transcript，恢复原消息并比较，确认归档不是只有文件名的空引用。

接下来才修改候选副本里的工具正文：

<<< @/public/learn-agent-rust/code/context-compaction/src/compact.rs#result-budget

这段代码保留工具消息的角色与调用 ID，只替换 `content`。已经外置的大结果继续保有专用引用，旧结果占位则指向其原消息键和摘要。每份归档最多 65536 字节，最多 24 份，超限停止；这些都是本例的应用限制。

读取时，程序核对注册 ID、文件类型、大小和内容摘要。`artifact-tamper` 在读取前故意用同样大小的内容替换文件，仍会触发 `stale_artifact`，说明只检查大小还不够。

### 摘要之后怎样找回原文？

运行：

```sh
cargo run --locked -- retrieve
```

<<< @/public/learn-agent-rust/outputs/r08-retrieve.txt

这个场景根据摘要附带的归档清单，调用 `read_artifact` 读取旧大结果的一小段。返回量按字符限制为最多 128 个字符，避免取回全文后立刻重新填满上下文。

<<< @/public/learn-agent-rust/code/context-compaction/src/compact.rs#retrieve

偏移和长度都按 Unicode 字符处理，避免切在中文 UTF-8 字节中间。这里取回的是当时保存的结果快照；要知道工作区文件现在的内容，仍然要重新执行 `read_file`。

## 5. 摘要保留什么，由谁检查？

对这次审查，应用要求保留四项信息：

| 事实键 | 值 | 来源 |
| --- | --- | --- |
| `target` | `src/first.rs` | `m4`：真实源码读取结果 |
| `finding` | `values[0]` 在空输入时索引越界 | `m4`：真实源码读取结果 |
| `test_status` | 未运行测试 | `m9`：最近工作状态 |
| `skill_handle` | `rust-review@1.0.0` | `m3`：技能读取结果 |

事实清单是本例为固定任务定义的应用记录。文件路径、代码和技能来自实际临时文件；程序也确实没有执行被审查函数的测试。每项事实附带来源消息键和该消息正文的 SHA-256。

摘要器收到待压缩历史和这份清单，返回 `version` 与 `facts` 的 JSON。脚本模型在正常场景复制候选事实，在故障场景删掉目标或把测试状态改为“通过”。这种做法让我们能确定地检查防线。

<<< @/public/learn-agent-rust/code/context-compaction/src/compact.rs#validate-summary

检查器要求版本、事实顺序、内容和来源与应用记录完全一致，再独立核对来源摘要。缺少字段、未知字段、无效 JSON、正文超过 2048 字节，或附带工具调用，都不能进入历史。

**它检查的是已知事实有没有被保留或改写。** 挑选哪些事实重要、识别任意自然语言之间是否矛盾，是另外的问题。真实任务需要维护更完整的事实记录，并用任务集测试摘要后的回答质量；仅有 JSON schema 或 SHA-256 不会自动解决这些问题。

### 摘要模型也有自己的预算

<<< @/public/learn-agent-rust/code/context-compaction/src/compact.rs#summarize

用于摘要的请求有独立的 30000 字节上限。normal 场景把原始待压缩段和事实清单发给摘要器，所以它的输入比随后给 Agent 的输入大；不能只看缩短后的 Agent 请求，忽略摘要成本。

本次运行最多允许两次摘要调用，单次失败立即返回，没有自动重试。遇到上游服务拒绝请求时的退避与重试策略，留给[第 23 章](./error-recovery.md)。

## 6. 验证成功后，才替换当前历史

摘要放入一条带 `kind=history_summary` 和 `trust=historical_data` 的 human 消息；首条 system 与用户消息保留原样。较早历史中的后续用户消息也逐条原样保留，防止用户中途增加的约束随摘要丢失。

<<< @/public/learn-agent-rust/code/context-compaction/src/compact.rs#replace

`summary-` 消息键由应用创建，用来识别可以被下一份摘要替代的旧摘要。练习里的用户输入只提供正文，不提供消息键。随着用户消息增加，如果保留这些内容后仍超出硬上限，程序返回 `context_budget`，不会继续强行删约束。

`prepare` 始终先处理克隆副本，最后检查结构和硬预算，全部通过才返回候选历史。图节点负责提交：

<<< @/public/learn-agent-rust/code/context-compaction/src/main.rs#prepare-node

失败时 `State.items` 没有被替换，下一次 Agent 模型调用也不会发生。已经成功写入的归档可能继续作为诊断记录保留，直到本次临时目录清理；这里的回滚指消息历史没有半改成功，不表示撤销诊断文件。

### 第七章的 loaded 标记也要跟着检查

`resident_skill` 表示技能正文是否仍在活跃上下文中。压缩成功后，从保留下来的消息重新计算它；仅有摘要中的技能名称、版本，不代表正文仍然存在。

normal 场景中，原技能结果先被占位、随后被摘要替代。下一轮脚本模型看不到审查说明，就提出新的 `load_skill` 请求。工具重新读取本地技能文件，以新的调用 ID 送回正文，之后才重新读取目标代码。因此输出中 `reloads=1`。

本章使用单份固定技能演示这条状态联动。第七章的目录发现、版本快照与完整加载器没有合并进本工程；整套机制的统一验收放在[完整集成](./integrated-agent.md)。本例的 `World.allow_write` 仍由应用设置，摘要文字没有修改它的入口。

### 三个节点各自负责什么？

<<< @/public/learn-agent-rust/code/context-compaction/src/main.rs#graph

`PrepareContext` 管理输入，`ModelTurn` 请求行动，`ExecuteTools` 执行后再回到压缩入口。`graph-flow` 推进节点，`langchain-rust` 提供消息和模型接口；预算、归档、摘要校验都是应用逻辑。

## 7. 动手对照：更短的历史也可能更差

先执行只裁剪最近历史的对照：

```sh
cargo run --locked -- naive-trim
```

<<< @/public/learn-agent-rust/outputs/r08-naive-trim.txt

这个场景仍按完整消息组保留尾部，工具配对也正确，但它把记录目标的旧组删掉了。结果是 `missing_evidence`：脚本模型只知道用户要继续审查，却不知道该读取哪个文件。对照实现有意绕过事实保留检查，用于暴露这个缺陷。

![normal 经三步压缩后仍能重新读取目标，而只保留最近历史虽然更短，却丢失了目标路径。](/learn-agent-rust/figures/r08-context-bytes.svg)

上半部分比较同一 normal 历史在三个阶段的字节数；下方对照提醒我们，体积更小不代表任务能够继续。数据来自固定脚本模型与同一份初始历史，不是不同真实模型之间的质量或速度比较。

再看摘要遗漏的失败路径：

```sh
cargo run --locked -- omit-fact
cargo run --locked -- invent-fact
```

<<< @/public/learn-agent-rust/outputs/r08-omit-fact.txt

![应用逐项核对摘要事实和来源，遗漏或虚构会保留原历史并停止，全部通过后才提交。](/learn-agent-rust/figures/r08-summary-gate.svg)

重点看失败分支：摘要模型已经被调用，但后续 Agent 模型调用数为零。`rollback=true` 表示消息历史未改变；这与“先提交错误摘要，再尝试修复”具有不同的行为。

### 全部场景的实际结果

<!-- r08-results:start -->

| 场景 | 摘要调用 | Agent 调用 | 技能重载 / 源码重读 | 停止原因 |
| --- | --- | --- | --- | --- |
| `normal` | 1 | 3 | 1 / 1 | `completed` |
| `small` | 0 | 2 | 0 / 1 | `completed` |
| `manual` | 1 | 3 | 1 / 1 | `completed` |
| `micro-only` | 0 | 3 | 1 / 1 | `completed` |
| `naive-trim` | 0 | 1 | 0 / 0 | `missing_evidence` |
| `omit-fact` | 1 | 0 | 0 / 0 | `summary_facts` |
| `invent-fact` | 1 | 0 | 0 / 0 | `summary_facts` |
| `bad-json` | 1 | 0 | 0 / 0 | `summary_schema` |
| `summary-error` | 1 | 0 | 0 / 0 | `summary_error` |
| `summary-large` | 1 | 0 | 0 / 0 | `summary_size` |
| `summary-input-budget` | 0 | 0 | 0 / 0 | `summary_input_budget` |
| `archive-error` | 0 | 0 | 0 / 0 | `archive_error` |
| `hard-budget` | 1 | 0 | 0 / 0 | `context_budget` |
| `orphan` | 0 | 0 | 0 / 0 | `invalid_history` |
| `pending` | 0 | 0 | 0 / 0 | `pending_tools` |
| `retrieve` | 1 | 4 | 1 / 1 | `completed` |
| `artifact-tamper` | 1 | 3 | 1 / 0 | `tool_error` |

<!-- r08-results:end -->

`small` 在触发线以内，跳过归档与摘要；`micro-only` 只靠落盘和占位就能继续；`manual` 在较高触发线下仍显式请求摘要。`hard-budget` 放大不可裁剪的用户约束，验证摘要成功后仍可能因为容量不足而拒绝提交。

`orphan` 与 `pending` 刻意提供坏历史，输出中的 `pairs=false` 是故障本身，验证程序要求它们在归档与模型调用前停止。`archive-error` 注入存储失败；`summary-input-budget` 则在调用摘要器之前发现摘要请求超限。

### 如何复现检查？

在解压的工程中：

```sh
cargo test --locked
cargo clippy --locked --all-targets -- -D warnings
```

在网站仓库根目录中，维护者执行：

```sh
python3 scripts/verify-agent-compaction.py --check
python3 scripts/generate-learn-agent-rust-figures.py --lesson R08
npm run docs:build
```

验证脚本在临时解压目录运行 17 个场景和 Rust 测试，核对配对、事实、预算、图节点、回滚和归档损坏；再独立解压最终下载包，离线运行并比较输出。证据保存在 `scripts/data/learn-agent-rust/r08-results.json`，下载包附带相同证据。首次安装工具链与依赖仍需网络。

::: warning 常见误区
- 序列化消息字节能用于这个实验的容量控制，不能直接解释为 token、费用或 provider 的上下文窗口。
- 摘要保留的是声明过的任务事实；未列入清单的细节可能消失。最终质量仍要看压缩后的任务能否完成。
- 归档和哈希用于保存、定位与核对快照，不认证内容作者。静态目录检查没有处理外部进程并发替换文件的竞争。
- 本实验的归档注册表与会话都在本次进程中，退出后清理；跨会话记忆、崩溃恢复和数据库检查点需要分别实现。
- 保留用户消息会持续占用空间，摘要也可能失败。本例会有界停止，要求应用调整任务或输入。
:::

<!-- transfer-thinking:start -->

## 迁移思考：压缩优化的是充分信息

摘要缩短一半，却遗漏一次写入的 operation_id，会更好吗？先给出你的判断，再展开下面的推演。

<details><summary>推演与应用</summary>

比较后续能否正确判断已执行动作，而不只比较字节数；关键身份必须留在结构化状态或可追溯归档中。

压缩、缓存和检索都应围绕下一步决策所需信息定义保真指标。

</details>

这是一道迁移练习，推演不代表新增实验已通过。对照[全书审查中的证据层次](./course-review.md#evidence-layers)，说明你的判断还需要哪一级证据。

<!-- transfer-thinking:end -->

## 本章结论

这次审查能够继续，是因为压缩同时保留了目标路径、源码发现、测试状态和技能线索，随后又真实重读源码。完整消息组保护协议结构，原始归档保留追查入口，提交前检查保证失败时仍有完整历史。

主线选择是：在模型请求前先处理工具结果，必要时生成有来源的事实摘要；把用户约束和执行权限留在应用可控的位置。下一步再考虑哪些经过确认的事实值得带到新会话。

## 检查理解

1. 为什么只保留最近几条消息，即使工具配对正确，仍可能无法继续任务？

   <details><summary>参考答案</summary>

   结构正确只能说明请求与结果对应。目标路径、旧发现或用户的中途约束可能位于更早的历史里。naive-trim 场景丢失了路径，因此停止于 `missing_evidence`。

   </details>

2. 为什么要先归档大结果，再做占位或摘要？

   <details><summary>参考答案</summary>

   后两步会移除原始正文。先保存完整记录，才能追查事实来源、核对内容，并在需要时分段读取。归档失败时，本例保留原历史并停止后续 Agent 调用。

   </details>

3. 本例能发现“测试通过”是虚构的，是否证明它能检查任意摘要的真假？

   <details><summary>参考答案</summary>

   只能证明它拒绝了对应用已知事实的篡改。固定任务清单声明了“未运行测试”，校验器要求候选事实保持一致。怎样从任意历史选择正确事实、理解语义和处理冲突，需要另外的设计与评估。

   </details>

4. 摘要还保留技能名称与版本，为什么下一轮要重新加载？

   <details><summary>参考答案</summary>

   名称与版本是找到技能的线索，具体方法在正文里。原始 `load_skill` 结果被移除后，`resident_skill` 重新计算为 false，因此允许新的请求把正文送回上下文。

   </details>

5. 压缩失败后，为什么可能留下归档，却仍然说消息回滚成功？

   <details><summary>参考答案</summary>

   压缩在候选副本上执行，失败时没有提交 `State.items`。归档是提前保存的诊断记录，可以继续保留到临时目录清理。消息状态没有半改成功，与撤销所有文件操作是两种不同的保证。

   </details>

## 参考资料

- [参考课程：s08 Context Compact](https://learn.shareai.run/zh/s08/)，用于对照分层处理的思路和下方原图。
- [Claude 官方 Context editing](https://platform.claude.com/docs/en/build-with-claude/context-editing)：旧工具结果清理与 SDK 摘要的不同职责。本章执行的是自己的应用逻辑。
- [Claude 官方 Token counting](https://platform.claude.com/docs/en/build-with-claude/token-counting)：真实请求的 token 统计。
- [langchain-rust 固定版 Message 源码](https://github.com/Abraxas-365/langchain-rust/blob/5fc3f5aca4380da48829f95d6e2fd0217b1f2013/src/schemas/messages.rs)、[graph-flow 固定版执行接口](https://github.com/a-agmon/rs-graph-llm/blob/9bbca193f20a8c4ba23289621549ecb3d35fee64/graph-flow/src/graph.rs)。
- [Serde：deny_unknown_fields](https://serde.rs/container-attrs.html#deny_unknown_fields)，本例摘要结构的严格字段检查。

## 保留的参考原图

以下图片原样保留自参考课程，展示其 Python/Claude 教学实现；图中接口、编号和统计沿用原图。下面用来对照压缩位置与执行顺序；本章的 Rust 数据以自制图和实验记录为准。

![上下文压缩通过分层处理历史和工具结果控制请求大小。](/learn-agent-rust/figures/upstream/r08-compact-overview.svg)

图源：[参考章节](https://learn.shareai.run/zh/s08/) · [原图](https://learn.shareai.run/course-assets/s08_context_compact/compact-overview.svg)。按图辨认压缩发生的位置，本章 Rust 实验另外验证事实保留与工具消息配对。

![上下文压缩通过分层处理历史和工具结果控制请求大小。](/learn-agent-rust/figures/upstream/r08-compaction-layers.svg)

图源：[参考章节](https://learn.shareai.run/zh/s08/) · [原图](https://learn.shareai.run/course-assets/s08_context_compact/compaction-layers.svg)。按图辨认压缩发生的位置，本章 Rust 实验另外验证事实保留与工具消息配对。

![上下文压缩通过分层处理历史和工具结果控制请求大小。](/learn-agent-rust/figures/upstream/r08-micro-compact.svg)

图源：[参考章节](https://learn.shareai.run/zh/s08/) · [原图](https://learn.shareai.run/course-assets/s08_context_compact/micro-compact.svg)。按图辨认压缩发生的位置，本章 Rust 实验另外验证事实保留与工具消息配对。

![上下文压缩通过分层处理历史和工具结果控制请求大小。](/learn-agent-rust/figures/upstream/r08-layer1-budget.svg)

图源：[参考章节](https://learn.shareai.run/zh/s08/) · [原图](https://learn.shareai.run/course-assets/s08_context_compact/layer1-budget.svg)。按图辨认压缩发生的位置，本章 Rust 实验另外验证事实保留与工具消息配对。

![上下文压缩通过分层处理历史和工具结果控制请求大小。](/learn-agent-rust/figures/upstream/r08-auto-compact.svg)

图源：[参考章节](https://learn.shareai.run/zh/s08/) · [原图](https://learn.shareai.run/course-assets/s08_context_compact/auto-compact.svg)。按图辨认压缩发生的位置，本章 Rust 实验另外验证事实保留与工具消息配对。

来源版本和许可见[课程架构中的参考资料说明](./architecture.md#reference-assets)。

下一章：[跨会话记忆](./memory.md)。把“本轮还能继续行动”的上下文，推进到“新会话能按来源召回”的事实记录。
