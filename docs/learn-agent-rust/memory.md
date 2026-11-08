---
title: "第 9 章：跨会话记忆"
description: "用有来源和修订号的事实记录，验证跨进程召回、更新冲突、逻辑遗忘与损坏记录处理。"
pageClass: learn-agent-rust-course
prev:
  text: 第 8 章 · 上下文压缩
  link: /learn-agent-rust/context-compaction
---

# 第 9 章：跨会话记忆

[课程总览](./index.md) · [上一章](./context-compaction.md) · [学习路径](./learning-path.md#r09) · [下一章](./system-prompts.md)

::: tip 本章学习目标
- 从一条明确的用户要求提取事实，保留作用域、来源原话和修订号。
- 结束写入进程，在新进程中只依靠磁盘召回事实，并验证更新与过期写入。
- 区分停止召回、历史删除与会话恢复，观察损坏记录和保存失败的处理。

**前置：** 理解[最小 Agent 循环](./agent-loop.md)中的消息与工具结果，以及[按需加载技能](./skill-loading.md)的来源与内容注入。第 8 章[上下文压缩](./context-compaction.md)解释同一会话怎样保留继续行动的依据；本章使用独立存储实验推进到跨会话层，可以直接运行。

**实践方式：** 下载 [memory-lab.zip](/learn-agent-rust/memory-lab.zip)，进入解压后的 `memory-lab` 执行 `cargo build --locked`。实验使用 Rust edition 2024、锁定的 serde / serde_json；首次获取依赖需要网络，运行时无需模型密钥和数据库。
:::

工作区助手在会话 A 中听到：“请记住，以后用中文回答。”当天它照做了。第二天启动会话 B，旧消息没有传进来，它还能知道这个偏好吗？

要回答这个问题，先让会话 A 的进程真正结束，再启动 B。如果只是保留同一个 Rust 对象、换一个会话名字，我们只能证明变量还在内存里。

这一章只沿着一个事实走：`project-a` 中的 `reply_language=中文`。我们把它写入磁盘，在另一个进程中召回，再把值更新成 `English`，最后要求忘记。每一步都留下可核对的来源。

<LearnAgentRustMap active="memory" />

<!-- experiment-library:start -->

全书实验可从[统一代码库](./experiments.md#memory)下载；解压后进入 `chapters/memory/`，或在代码库根目录运行 `python3 run.py run R09`。

<!-- experiment-library:end -->

::: info 本章实验状态
已验证确定性提取、真实磁盘文件、独立 CLI 进程之间的保存与召回。完整实验包含 22 个场景和 8 个 Rust 测试，下载包会被实际解压、重新编译并复验全部场景。

本章把存储层单独实现为小型 Cargo 工程，未接入 `graph-flow` 或 `langchain-rust`，也没有调用真实模型。提取器只识别明确语法；自动判断“哪些偏好值得长期保留”的质量需要另行评估。
:::

## 与 RAG 的分工

[K01：RAG](./retrieval-augmented-generation.md)按问题检索当前资料；本章保存过去明确确认的事实，再按 `(scope, key)` 精确召回。记忆系统可以在召回阶段采用语义检索，但本实验没有向量索引或相关度排序。无论用哪种召回方式，来源、修订、冲突和忘记仍要独立设计。四种输入与连接的关系见[概念导读](./knowledge-and-capabilities.md)。

## 1. 先结束进程，再问一次

::: info 代码与输出只有一个来源
所有 Rust 片段直接引用 `docs/public/learn-agent-rust/code/memory/src/main.rs`，输出由验证脚本运行同一份源码生成。

[下载完整工程、输出与校验记录](/learn-agent-rust/memory-lab.zip) · <a href="/learn-agent-rust/code/memory/src/main.rs" download>下载 main.rs</a> · [在 GitHub 查看工程](https://github.com/lewislau86/lewislau86.github.io/tree/master/docs/public/learn-agent-rust/code/memory)
:::

进入解压后的目录，准备一条显式记忆要求：

```sh
cargo build --locked
printf '请记住：reply_language=中文\n' > message.txt
cargo run --locked -- apply demo-store project-a session-A 1 0 user --message message.txt
cargo run --locked -- recall demo-store project-a reply_language
```

`apply` 的参数依次为：存储目录、作用域、来源会话、来源轮次、预期修订号、来源角色，以及消息文件。这里预期修订号为 `0`，表示我们认为存储还没有任何事件。

先预测最后一条命令的输入：它没有 `session-A`，没有原始消息文件，也没有那一次进程的 Rust 变量。它只拿到目录、作用域和键。验证器实际得到：

<<< @/public/learn-agent-rust/outputs/r09-new-process.txt

输出中的 `apply` / `recall new-process` 是验证器加的步骤标签；下面各一行 JSON 才是相应 CLI 进程的标准输出。写入子进程退出后，验证器才启动召回子进程，并检查值为 `中文`、来源仍为 `session-A`。

![会话 A 的写入进程退出后，会话 B 的新进程从 memory.json 召回中文偏好，旧消息历史没有被传入。](/learn-agent-rust/figures/r09-process-recall.svg)

沿箭头读这张图：跨越两次进程生命期的是磁盘文件。来源会话只是记录上的标签；真正让信息留下来的是成功保存，以及新进程明确执行的读取。

`demo-store` 是当前目录下的练习目录。程序只访问你指定的目录，不扫描主目录里的 Codex memory 或全局 skills。重复实验时可以换一个新的目录名；已有目录的版本要以 `recall` 返回的 `revision` 为准。

## 2. 从一句话提取什么？

我们先把“值得记住”限定为用户明确要求的一件事。实验识别两种格式：`请记住：键=值`、`请忘记：键`。允许的键只有 `reply_language` 和 `run_command`。

<<< @/public/learn-agent-rust/code/memory/src/main.rs#extract

跟着 `extract` 看三步：先检查来源字段，再识别记忆意图，最后检查允许的键和值。普通的“今天先使用中文”返回 `no_memory_intent`；工具输出中即使包含完整的“请记住”句子，也因角色为 `tool` 而返回 `untrusted_origin`。

这里的“提取”是字符串解析，规则十分刻意：我们希望先证明事实经过了哪些检查。接入真实模型后，模型可以从自然语言提出候选事实，但确认意图、校验键和决定是否保存仍应由应用完成。

有一个关键前提：`role`、`session` 和 `scope` 必须由可信调用方给出。本例的命令行调用者本来就有写目录的能力，能自行填写这些字段。因此来源字段用于追溯，**不承担身份认证**；文件中的原话也不证明它确实出自某个用户。

### 为什么每个事实都带来源？

<<< @/public/learn-agent-rust/code/memory/src/main.rs#records

一个事件把五件事放在一起：

| 字段 | 例子 | 解决的问题 |
| --- | --- | --- |
| `scope` | `project-a` | 这条事实在哪个范围使用？ |
| `key` | `reply_language` | 这条事实回答哪一个问题？ |
| `action` | `set` 与值 `中文` | 这是设置值，还是要求忘记？ |
| `source` | 会话 A、第 1 轮、用户原话 | 为什么记住它，后续怎样核对？ |
| `revision` | `1` | 它在整个存储中第几次被修改？ |

文件最外层还有 `schema=1`，表示数据格式版本。它与 `revision` 的职责不同：修改事实增加修订号；将来改变文件结构，才考虑格式迁移。

本例的作用域采用**完整字符串相等**，没有全局默认值、继承或模糊搜索。在 `project-b` 里查询同一个键，结果就是 `missing`。它解决选取范围的问题；多用户服务仍需在读取之前验证访问资格。

## 3. 更新时，谁覆盖谁？

现在用户明确改变偏好。运行：

```sh
printf '请记住：reply_language=English\n' > message.txt
cargo run --locked -- apply demo-store project-a session-C 1 1 user --message message.txt
cargo run --locked -- recall demo-store project-a reply_language
```

先猜一下：旧的 `中文` 会从文件中消失，还是仍可追溯？

<<< @/public/learn-agent-rust/outputs/r09-update.txt

当前召回值变成 `English`，来源变成会话 C，修订号为 `2`。磁盘仍保留事件 1；读取时按修订顺序重放，构建以 `(scope, key)` 为键的当前事实表，后一次合法设置覆盖前一次。

### 先核对版本，再接受更新

<<< @/public/learn-agent-rust/code/memory/src/main.rs#apply

`apply` 在写者锁内读取现有文件，比较调用方的 `expected` 与当前全局修订号。相等才继续。假设另一个调用方仍认为存储为空，带着 `expected=0` 写入新值：

<<< @/public/learn-agent-rust/outputs/r09-stale.txt

拒绝之后，新进程仍读到 `中文`。验证器还逐字节检查了文件保持不变。遇到冲突应重新读取并判断新事实是否仍应保存；把版本改大后直接重试，会绕过这次核对的意义。

本例修订号属于**整个文件**，并非每个键分别计数。在 `project-b` 写一次也会影响 `project-a` 下一次写入的预期版本。这样容易理解和验证，代价是无关事实之间也会产生版本冲突。

如果新候选与当前值完全相同、版本也匹配，返回 `unchanged`：不追加事件，也不把来源悄悄换成新会话。这是本例的去重选择；需要记录每次确认时，可以另行增加确认事件。

![修订 1 设置中文，修订 2 更新为 English，修订 3 写入遗忘事件；当前事实随重放改变，来源历史保留。](/learn-agent-rust/figures/r09-revision-history.svg)

从上到下读事件，再看右侧的当前视图。原话留在历史中，当前事实只取最后有效状态。图中的修订号来自 `forget` 场景：该实验先设置、再更新、最后遗忘，依次产生 3 个事件。

## 4. 写了一半，下一次还能读吗？

直接覆盖 `memory.json` 时，如果写到一半失败，下一个进程可能只拿到半份 JSON。本例先把完整快照写入同目录的临时文件，再替换正式文件：

<<< @/public/learn-agent-rust/code/memory/src/main.rs#persist

文件名虽然叫事件历史，每次保存仍是**重写一份完整快照**，没有直接向正式文件末尾追加字节。顺序是创建临时文件、写入、`sync_all`、关闭文件，然后 `rename`。

这里选择同目录，是为了让临时文件与正式文件位于同一文件系统；Rust 的 [`rename` 文档](https://doc.rust-lang.org/std/fs/fn.rename.html)明确指出跨挂载点移动会失败。Unix 上还同步目录项。`sync_all` 的具体语义见 [Rust 文件文档](https://doc.rust-lang.org/std/fs/struct.File.html#method.sync_all)。

写者通过 `create_new` 创建 `.memory.lock`，并在读取、版本检查与保存的整个区间持有它。另一个遵循本协议的写者看到已有锁就返回 `store_busy`。`create_new` 的原子创建语义见 [OpenOptions 文档](https://doc.rust-lang.org/std/fs/struct.OpenOptions.html#method.create_new)。本章验证已有锁时拒写，未进行高并发压力测试。

### 在替换前注入一次失败

验证器先保存中文，再尝试更新为 English，在 `rename` 前主动返回错误：

<<< @/public/learn-agent-rust/outputs/r09-save-failure.txt

它同时检查三件事：正式文件字节没有改变；本次创建的临时文件与锁已清理；新进程仍能召回旧值。下载包支持在 `apply` 命令末尾增加 `--fail-before-rename`，复现这一故障。

![写入经过持锁、检查版本、写临时文件和替换正式文件；替换前注入失败时保留旧文件，损坏记录则停止读取和更新。](/learn-agent-rust/figures/r09-storage-boundaries.svg)

图中把失败放在准确位置：`rename` 前失败能够核对旧字节保持不变；`rename` 后若目录同步失败，程序返回 `durability_unknown`，此时修改已经发生，调用方必须重新读取确认。本实验没有制造断电，也未验证网络文件系统和 Windows 的持久性行为。

正常返回和普通错误会由作用域清理移除本次拥有的锁、临时文件；进程被强制终止可能留下它们。程序保留已有锁和临时文件，要求人工先确认写者已经退出、备份并检查文件后再处理，不自动抢锁或删除别的运行留下的文件。

## 5. 损坏文件应当怎么处理？

新进程不能只做 JSON 解析。一个语法正确的文件仍可能带着不支持的格式版本、断开的修订号，或与原话对不上的值：

<<< @/public/learn-agent-rust/code/memory/src/main.rs#replay

`load` 先有界读取文件，再解析并重放全部事件。每个修订号必须恰好等于它的位置加一；提取器根据保存的原话重建候选，核对作用域、键和动作；遗忘事件必须对应一个当时存在的事实。

这一套检查验证**记录内部是否自洽**。如果有人同时篡改值和原话，使它们彼此一致，检查仍可能通过。需要认证来源或抵御篡改时，应在存储访问控制、签名或审计系统中另行解决。

本例对损坏采取整库拒绝：读取报错，更新也报错，不静默跳过坏记录，更不把它当空文件覆盖。例如：

<<< @/public/learn-agent-rust/outputs/r09-forged-record.txt

这个场景只把持久记录的值改成 `English`，保留原话中的 `中文`。验证器确认召回与后续写入都返回 `invalid_record`，损坏文件字节保持原样，方便后续排查与恢复。

文件确实不存在时才得到空存储；无权读取、格式损坏或语义校验失败，都走错误分支。`#[serde(deny_unknown_fields)]` 还会拒绝本版程序不认识的字段，避免新格式被旧程序读入后悄悄丢弃内容再覆盖。该属性的用法见 [Serde 文档](https://serde.rs/container-attrs.html#deny_unknown_fields)。

为了保持实验有界，文件最多 65536 字节、事件最多 64 条、原话最多 512 字节、值最多 160 字节，均按 UTF-8 字节统计。满额后明确拒写；本章没有自动归档或数据迁移。

## 6. 召回后，放回 Agent 的什么位置？

<<< @/public/learn-agent-rust/code/memory/src/main.rs#recall

召回结果带有值、来源、事实修订号，以及当前存储的全局修订号。当前实现只按作用域和键精确查询，因此结果最多一条；没有向量数据库、相关性排序或自动召回全部事实。

将它接入[第 2 章的工具循环](./tools-and-graph.md)时，可以把它作为 `recall_memory` 的工具结果，并沿原调用 ID 放回消息历史。下一轮模型获得“这是先前记录的偏好，以及它的来源”这份资料。具体接线与提示词组织留到[第 10 章](./system-prompts.md)；当前下载包止于 CLI 的 JSON 输出。

特别留意 `run_command`：它的值可以是 `cargo run`，但召回函数只返回字符串，不执行它。后续要运行命令，仍由工具入口检查工作区、权限与审批。来源记录帮助判断资料是否适用，不会自动授予执行能力。

这也说明跨会话记忆与其他状态的区别：

| 状态 | 这份状态回答什么问题？ | 本章是否恢复？ |
| --- | --- | --- |
| 当前消息历史 / 压缩摘要 | 这次对话走到了哪里？ | 不恢复；新进程从空上下文开始。 |
| 技能与方法 | 遇到这类任务按什么步骤做？ | 由[第 7 章](./skill-loading.md)按需加载。 |
| 可长期使用的事实 | 用户明确要求以后记住什么？ | 保存来源并按键召回。 |
| 任务与工具检查点 | 哪个业务步骤已执行，恢复后继续哪里？ | 留给[持久化任务](./task-system.md)与[检查点专题](./postgres-checkpoints.md)。 |

### “请忘记”会把原文抹掉吗？

执行 `请忘记：reply_language` 后，事件历史增加一个 `forget`，当前事实表移除这个键：

<<< @/public/learn-agent-rust/outputs/r09-forget.txt

后续新进程得到 `missing`，历史仍有原先的事件和原话。因此这里是**逻辑遗忘**。真正删除个人资料还要处理历史、备份、日志及已经进入其他会话的内容；删除存储中的一个当前值，也不会撤回已经发送给模型的上下文。本练习只使用示例偏好，不输入个人敏感信息。

## 7. 动手实验：每次只改一个条件

先完成第 1 节的写入，再尝试三个变化：

1. 将召回的 `project-a` 改成 `project-b`。先猜结果，再核对它是否仍返回同一偏好。
2. 用 `session-C` 更新，但继续传 `expected=0`。观察错误后再次召回，检查原值与来源。
3. 正确更新后，把消息改成 `请忘记：reply_language`，使用最新 `revision` 写入。查看 `memory.json` 中的历史与召回结果为何不同。

每次实验可使用新的练习目录，避免把上一次的修订号带进下一次。不要为绕过错误而手改正式文件的版本号。

下面是验证脚本生成的完整结果表。每个 CLI 调用都是独立子进程，前一次退出后才执行下一次。“最后结果”有些是故障后的再次召回，需要结合具体输出阅读；例如 `save-failure` 最后是 `found`，同时前一步的写入错误和原字节保持不变都已核对。

<!-- r09-results:start -->

| 场景 | 独立 CLI 进程 | 最后结果 |
| --- | --- | --- |
| `empty` | 1 | `missing` |
| `new-process` | 2 | `found` |
| `update` | 3 | `found` |
| `stale` | 3 | `found` |
| `repeat` | 2 | `unchanged` |
| `scope` | 5 | `found` |
| `forget` | 7 | `fact_missing` |
| `no-intent` | 1 | `no_memory_intent` |
| `tool-origin` | 1 | `untrusted_origin` |
| `unknown-key` | 1 | `unknown_key` |
| `corrupt` | 3 | `corrupt_store` |
| `truncated` | 3 | `corrupt_store` |
| `schema` | 3 | `unsupported_schema` |
| `revision-gap` | 3 | `invalid_revision` |
| `forged-record` | 3 | `invalid_record` |
| `unknown-field` | 3 | `corrupt_store` |
| `lock` | 2 | `store_busy` |
| `pending` | 2 | `pending_unavailable` |
| `save-failure` | 3 | `found` |
| `size-limit` | 2 | `size_limit` |
| `event-limit` | 2 | `found` |
| `invalid-cli` | 2 | `usage` |

<!-- r09-results:end -->

环境为本机 macOS ARM、Rust 1.99.1，具体 `rustc`、host、源码与输出 SHA-256 见学习包中的 `evidence.json`。这些是确定性正确性测试，不是模型质量或吞吐量基准。`--check` 在运行机器上重测行为，并保留初次生成证据的环境标签。

在网站仓库根目录统一复验：

```sh
python3 scripts/verify-agent-memory.py --check
python3 scripts/generate-learn-agent-rust-figures.py --lesson R09
```

验证器将工程复制到临时目录，运行格式检查、8 个 Rust 测试和全部场景，检查来源、版本、作用域、拒写前后字节与资源清理；随后实际解压生成的 zip，独立重新编译，再复验全部场景。它不会访问用户的个人记忆目录。

::: warning 常见误区
- **把会话名变更当跨进程验证。** 本章每次 CLI 调用都真正启动新进程；持久信息来自同一目录中的文件。
- **把来源字段当认证。** 字段由调用方填写，原话自洽检查也只能发现部分损坏；可信来源与访问控制需要单独实现。
- **把过期事实当指令。** 召回资料需要结合当前用户要求和来源判断，工具动作继续接受权限检查。
- **把逻辑遗忘当物理删除。** `forget` 停止当前召回，历史事件仍保留原文。
- **把一次故障注入当崩溃恢复证明。** 当前验证覆盖替换前主动失败、已有锁与临时文件；断电、强制终止及多机竞争仍需专门演练。
:::

<!-- transfer-thinking:start -->

## 迁移思考：记住的事实有时间和来源

旧会话说项目用 Python，新提交改成 Rust，召回时应信哪一个？先给出你的判断，再展开下面的推演。

<details><summary>推演与应用</summary>

展示来源修订、观察时间与冲突，按明确规则更新；别让召回排序悄悄承担事实裁决。

企业知识库要能解释“根据哪个版本得出”，而不仅是找到相似句子。

</details>

这是一道迁移练习，推演不代表新增实验已通过。对照[全书审查中的证据层次](./course-review.md#evidence-layers)，说明你的判断还需要哪一级证据。

<!-- transfer-thinking:end -->

## 本章结论

工作区助手现在拥有一层可在新进程中读取的事实记录。明确的记忆要求经过提取与校验，保存来源和修订号；更新先核对版本，读取重放记录，损坏时保留证据并停止继续覆盖。

本章的主线选择是小范围、可追溯的事实存储：精确键查询、全局版本、完整快照保存与逻辑遗忘。先把这些行为验证清楚，再扩展自然语言提取、相关性召回和长期存储管理。

## 检查理解

1. 会话 A 结束后，B 能召回偏好，为什么还不能说整个 Agent 会话已经恢复？

   <details><summary>参考答案</summary>

   B 只恢复了选中的事实和来源，没有恢复消息历史、工具调用 ID、审批状态或任务进度。完整会话恢复需要另行保存并验证这些状态。

   </details>

2. 记录的 `schema=1`、当前存储的 `revision=5`，而召回事实的 `revision=2`，这三个数矛盾吗？

   <details><summary>参考答案</summary>

   不矛盾。`schema` 是格式版本；全局修订号 5 表示已有 5 个事件；这条事实最近一次设置发生在事件 2，此后可能只修改了其他键或作用域。

   </details>

3. 用户明确更新成 English，为什么仍可能返回 `revision_conflict`？

   <details><summary>参考答案</summary>

   当前意图决定候选内容，版本核对确认调用方是否基于最新状态做决定。两者职责不同。调用方应读取当前事实与来源，再判断是否保存这次更新。

   </details>

4. JSON 能解析，为什么还要检查修订顺序和原话？

   <details><summary>参考答案</summary>

   语法有效不保证语义有效。修订可能重复或断开，动作也可能与原话不一致。重放校验发现这些内部矛盾；如果值与原话一起被伪造，它不能证明来源真实性。

   </details>

5. `durability_unknown` 出现后，能否按“写入失败、磁盘没变”继续使用旧版本？

   <details><summary>参考答案</summary>

   不能。此错误出现在正式文件已被替换、目录同步失败之后，应重新读取确认当前修订与内容。`--fail-before-rename` 才是本章验证了旧文件字节保持不变的故障点。

   </details>

## 参考资料

- [Rust：OpenOptions::create_new](https://doc.rust-lang.org/std/fs/struct.OpenOptions.html#method.create_new)、[File::sync_all](https://doc.rust-lang.org/std/fs/struct.File.html#method.sync_all)、[fs::rename](https://doc.rust-lang.org/std/fs/fn.rename.html)：对照本章创建锁、同步和替换的实际调用，留意平台差异。
- [Serde：容器属性](https://serde.rs/container-attrs.html)：本例使用 `deny_unknown_fields` 拒绝未知字段，格式迁移需另外设计。
- [参考课程 s09 Memory](https://learn.shareai.run/zh/s09/)：对照文件记忆、提取与按需加载的分工；其 Python/Claude 实现与本章独立 Rust 实验分别验收。

### 保留的参考原图

以下两张图原样保留自参考课程，图中目录、接口与统计属于上游实现。本章 Rust 使用单份 JSON 事件历史，不实现原图中的完整记忆子系统。

![参考实现把记忆文件与索引分开保存，并在后续会话按需载入。](/learn-agent-rust/figures/upstream/r09-memory-overview.svg)

先看存储与召回的分界，再回看本章由 CLI 显式读取的路径。图源：[参考章节](https://learn.shareai.run/zh/s09/) · [原图](https://learn.shareai.run/course-assets/s09_memory/memory-overview.svg)。

![参考实现把跨会话记忆分为不同来源与处理路径，本章只验证显式事实的提取、保存和召回。](/learn-agent-rust/figures/upstream/r09-memory-subsystems.svg)

沿图分辨提取、整理和读取各自的职责；自动整理与语义召回未在本章实现。图源：[参考章节](https://learn.shareai.run/zh/s09/) · [原图](https://learn.shareai.run/course-assets/s09_memory/memory-subsystems.svg)。来源版本和许可见[参考资料说明](./architecture.md#reference-assets)。

下一章：[系统提示词组装](./system-prompts.md)。在工具、技能和记忆都能提供资料之后，继续讨论怎样为一次模型请求标清各部分的来源与职责。
