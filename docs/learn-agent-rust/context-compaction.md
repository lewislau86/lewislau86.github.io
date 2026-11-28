---
title: "第 12 章：上下文压缩"
description: "沿一次连续代码审查，用 ADK-Rust 3.0 的运行间压缩与运行内压缩缩短历史，由应用自写的摘要器核对事实清单，验证摘要失败时历史保持不变。"
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
- 区分运行之间的压缩、运行之内的压缩和直接丢弃旧事件，解释各自保留了什么。
- 说明框架怎样保证工具调用与结果不被切开，以及摘要失败时历史怎样保持不变。
- 用有来源的事实清单检查摘要，观察漏写、虚构和格式错误各自的后果。

**前置：** [第 1 章：最小 Agent 循环](./agent-loop.md)、[第 10 章：按需加载技能](./skill-loading.md)。

**实践方式：** 下载<a href="/learn-agent-rust/context-compaction.zip" download>完整 context-compaction.zip</a>，按[第 1 节](#hands-on)取一次 ADK-Rust 源码后运行；无需模型密钥或数据库。
:::

::: info 本章已迁移到 ADK-Rust 3.0
本章实验基于 ADK-Rust 3.0 发布候选版（固定提交，尚未发布到 crates.io）。旧版本章自写了消息分组、大结果落盘归档、旧结果占位、摘要校验与回滚，可从 git 标签 `learn-agent-rust-v1` 取得。新版的分组、切口、替换和失败回退都由框架完成，应用只写摘要器；框架没有提供工具结果落盘归档，这部分在新版里删去，[对应表](#old-scenarios)列出了变化。
:::

前面的技能章节把审查方法按需放进消息历史，[RAG 章](./retrieval-augmented-generation.md)又带来更多资料。每一次模型请求都会携带这些旧内容；新读一份文件，还会继续增加输入。

我们延续一个具体任务：审查 `src/first.rs`，确认空输入会发生什么。用户明确要求：禁止修改文件；没有运行测试，就要说明“未运行测试”。助手先读规范、读目标文件，再读三份很长的资料。下一次运行用户只说了一句“继续，给出结论”。

现在需要腾出空间。先猜一猜：只留下最近几条事件，助手还能知道该读哪个文件吗？如果摘要写着“测试通过”，我们又靠什么发现它没有依据？

<LearnAgentRustMap active="context-compaction" />

<!-- experiment-library:start -->

全书实验可从[统一代码库](./experiments.md#context-compaction)下载；解压后进入 `chapters/context-compaction/`，或在代码库根目录运行 `python3 run.py run R08`。

<!-- experiment-library:end -->

::: info 本章实验状态
压缩的触发、切口、替换与失败回退都是 ADK-Rust 的真实实现；文件工具真实读取临时目录。审查模型和摘要模型都是按规则回复的替身，只看得到各自的请求。事实清单针对这个固定审查任务定义，核对器检查清单里的事实有没有被保留或改写，不自动评判任意自然语言摘要的真实性；真实模型的摘要质量需要另做[质量评估](./model-evaluation.md)。
:::

## 1. 先运行：压缩之后还要能继续做事 {#hands-on}

下载并解压工程，先取一次 ADK-Rust 源码再运行：

```sh
cd context-compaction
python3 fetch-adk-rust.py ../adk-rust    # 需要 git 与 GitHub 访问；不行时加 --method cdn
cargo run --locked -- normal
```

编译时会看到 adk-core 的 3 条弃用警告（上游固定 Rust 1.95.0），不影响运行和检查。

<<< @/public/learn-agent-rust/outputs/r08-normal.txt

读输出时分三段看。第一次运行（`--- run: 审查 ...`）：读规范、读目标、逐份读三份资料，回答“资料已读完”。`[compaction]` 行是第一次运行结束后框架写进会话的摘要：一份事实清单。最后的 `request N` 行是审查模型每次收到的请求：第一次运行的最后一次请求（request 5）估算约 1255 个 token；第二次运行的第一次请求（request 6）只剩约 131 个，消息角色变成 `system,model,user`，中间那条 `model` 就是摘要（角色是本章摘要器自己定的；运行之内的压缩不一样，框架只取摘要文字，包成一条用户角色的“系统通知”）。

第二次运行里，审查模型看不到审查规范的正文了：第一次运行的事件被摘要替换，而摘要只带清单上的事实，规范正文不在其中。于是它重新调用 `load_skill`；它也看不到这一轮读过的源码，于是按摘要里的 `target` 重新读取 `src/first.rs`，再给出结论，并按摘要里的 `test_status` 写明“未运行测试”。

## 2. 三种缩短历史的方式

ADK-Rust 提供了两种压缩，外加一个直接丢弃旧事件的选项：

| 方式 | 什么时候 | 怎样缩短 | 本章场景 |
| --- | --- | --- | --- |
| 运行之间：`EventsCompactionConfig` | 每完成 N 次运行（本章 N=1） | 把会话里的旧事件交给摘要器，写一条压缩事件进会话；之后的运行从摘要开始 | `normal` 等 |
| 运行之内：`IntraCompactionConfig` | 每次请求模型之前，估算超过阈值时（**默认开启**） | 把这次请求的历史交给摘要器，用摘要替换，只留最近几条 | `intra` |
| 只装入最近事件：`RunConfig::history_max_events` | 每次运行开始时 | 只取最近 N 条事件，其余直接不看 | `naive-trim` |

![两种压缩都把旧历史交给摘要器：运行之间的在运行结束后写压缩事件，运行之内的在请求前替换历史；摘要器核对事实清单，通过才替换，不通过就保留原历史。](/learn-agent-rust/figures/r08-compaction-pipeline.svg)

运行之内的压缩默认是开着的：阈值是模型上下文窗口的 80%，模型不报告窗口时是 10 万个估算 token。前面各章的实验都写了 `without_intra_compaction()`，就是为了让轨迹不受它影响（[第 1 章](./agent-loop.md)解释过）。估算按约 4 个 UTF-8 字节 1 个 token 计（一个汉字约 3 字节），**不是任何模型的 tokenizer，也不是费用**；接入真实服务时，应以服务商报告的用量为准，框架在拿到上一次请求的实际用量后也会用它来判断。

<<< @/public/learn-agent-rust/code/context-compaction/src/main.rs#wiring

本章的运行之内压缩把阈值设成 1000，`with_overlap_event_count(0)` 表示不刻意保留最近条目；实际保留了什么，第 3 节会看到。

## 3. 工具调用与结果不会被切开

旧版要自己把“一条 assistant 消息里的工具调用”和“它们的全部结果”分成一组，切口只能落在组的边界。ADK-Rust 的两种压缩都由框架决定切口：切口**永远不会把工具结果和它的调用分开**，等待审批的调用及其之后的内容也会原样保留（这样审批之后还能恢复）。

`intra` 场景在一次运行里读完三份资料后触发压缩：

<<< @/public/learn-agent-rust/outputs/r08-intra.txt

模型逐份读资料。读完第三份后，历史估算已经超过 1000（request 4 是读第三份之前的 879）。下一次请求之前，框架调用摘要器：request 5 只剩 `system,user,model,function`，那条 `user` 是框架放进来的摘要通知，后面的 `model,function` 是读第三份资料的那一对调用与结果，原样保留。用户消息、规范、源码和前两份资料都被摘要替换，摘要只带清单上的事实。之后模型重新加载规范、重新读源码，给出结论。

为什么留下了最后一对？本章设的保留条数是 0，框架算出的切口本来是“整段都压”。但它还要把这次压缩记进会话（结果表里 `intra` 的压缩事件数是 1），为此要在会话事件里找一个能精确定位的切口：第一条保留下来的内容必须能在会话里唯一对上一条事件，所以至少要留一条；切口不能把结果和它的调用分开；切口前后的事件时间戳还要在毫秒上分得开。框架从后往前、在后一半历史里找：只留最后一份结果会和调用分开，于是退到读第三份资料的那次调用之前。

如果这个位置的时间戳撞在同一毫秒，框架会继续往前找（多留几对）；整段都找不到时，才改为把整段交给摘要器、不记进会话。所以切口位置会随机器快慢而变。本章的审查模型每次回复前等待 3 毫秒，回复事件在等待之后才盖上时间戳，前后事件就在毫秒上分得开，轨迹在任何机器上都一样。

## 4. 摘要器是应用的事

框架负责什么时候压、切在哪里、怎样替换，**摘要写什么由摘要器决定**。框架自带的 `LlmEventSummarizer` 用一段通用提示让模型“简洁地总结对话”；它不知道这次审查里哪些事情不能丢。本章换成自己写的摘要器，实现 `BaseEventsSummarizer` 这一个方法：

<<< @/public/learn-agent-rust/code/context-compaction/src/main.rs#summarizer

做法分三步：把要压缩的事件渲染成文字；让摘要模型按应用给出的事实清单写 JSON；核对通过才返回压缩事件。摘要模型的调用经过 `generate_metered`，和框架自带的摘要器一样计入运行的预算。

### 摘要保留什么，由谁检查？

<<< @/public/learn-agent-rust/code/context-compaction/src/main.rs#facts

| 事实键 | 值 | 为什么不能丢 |
| --- | --- | --- |
| `target` | `src/first.rs` | 不知道审查哪个文件，就无法继续。 |
| `finding` | `values[0]` | 问题所在的那一行代码。 |
| `test_status` | 未运行测试 | 用户要求写明；虚构成“测试通过”就是错误结论。 |
| `constraint` | 禁止修改文件 | 用户的约束。 |
| `doc_a`、`doc_b`、`doc_c` | DOC-A、DOC-B、DOC-C | 已经读过的资料，避免重读。 |
| `latest_request` | 被压缩历史里用户最后说的话 | 用户这一轮的请求也会被压进摘要。 |

最后一项值得单独说。ADK-Rust 的压缩把**用户消息也一起交给摘要器**：`intra` 场景里，用户的“读完资料后给出结论”在压缩之后只存在于摘要里。如果清单里没有这一项，模型压缩之后就不知道这一轮要不要给结论（本章开发时就遇到了这个情况，模型停在“资料已读完，等待下一步”）。旧版选择把用户消息原样留在摘要之外；新版要靠清单把它带过去。

清单只包含在这次被压缩的那段历史里出现过的事实：没压进来的内容（例如 `intra` 里第三份资料）原样留在历史里，不需要摘要转述。核对器要求格式和版本正确，事实的顺序、键和值与清单完全一致，并且每个值都能在被压缩的那段历史里找到（来源核对）。**它检查的是已知事实有没有被保留或改写**；挑选哪些事实重要、识别任意自然语言之间是否矛盾，是另外的问题。

## 5. 摘要失败时，历史保持不变

摘要器返回错误时，框架记一条警告，保留原历史继续运行：压缩是一项优化，失败不会让运行停下。几个故障场景都走这条路：

```sh
cargo run --locked -- omit-fact
```

<<< @/public/learn-agent-rust/outputs/r08-omit-fact.txt

摘要模型漏写了 `target`，核对器拒绝（`compaction.summary_facts`），会话里没有压缩事件，第二次运行仍然拿到完整历史，照样给出结论。`invent-fact`（把测试状态写成“测试通过”）、`bad-json`（不是 JSON）、`summary-error`（摘要模型出错）也是一样：没有压缩，历史完整，结论正确，代价是请求没有变短。

如果不核对呢？`omit-unchecked` 用同一个漏写目标的摘要模型，但跳过核对：

<<< @/public/learn-agent-rust/outputs/r08-omit-unchecked.txt

摘要被接受，第二次运行只看到一份不提文件名的摘要，审查模型回答“历史里找不到要审查的文件（missing_evidence）”。请求是变短了，任务却无法继续。

框架自己也有一道检查：摘要不比被替换的内容短，就不用。`not-smaller` 场景的摘要器两次都“接受”了摘要，但摘要后面拖着 2 万个空格，框架判断它没有让历史变短，没有写压缩事件。运行之内的压缩还有一点：一次失败或没有变短之后，要等历史再多出几条（至少 1 条，取保留条数）才会再试，免得每次请求都白付一次摘要的费用；本章的失败场景都在运行之间，没有演示这一点。

![摘要器把事实清单逐项核对：漏写、虚构、格式错误都返回错误，框架保留原历史；不核对时漏写的摘要被接受，后续请求丢了目标。](/learn-agent-rust/figures/r08-summary-gate.svg)

## 6. 直接丢弃旧事件，会丢掉什么

```sh
cargo run --locked -- naive-trim
```

<<< @/public/learn-agent-rust/outputs/r08-naive-trim.txt

第二次运行用 `history_max_events(2)` 只装入最近 2 条事件。它不调用摘要模型，也不保证成对：装入的 2 条是第三份资料的结果和“资料已读完”的回答，结果的调用不在窗口里，框架组装请求时就把这条落单的结果丢掉了，请求里只剩一条 `model` 文本（估算 21）。用户最初的要求和读目标文件的结果都不在窗口里：模型重新加载了规范，却不知道该审查哪个文件。体积更小不代表任务能够继续。

![normal 第一次运行最后一次请求与第二次运行第一次请求的估算 token，intra 压缩前后的估算 token，以及 naive-trim 丢失目标。](/learn-agent-rust/figures/r08-context-bytes.svg)

## 7. 审查模型怎样决定下一步

两个模型都只看请求。审查模型的规则：请求里没有规范正文就加载；找不到目标文件名就报告缺证据；这一轮还没读过目标就去读；资料一次读一份，原文和摘要里都没出现的那份；请求里有“给出结论”才下结论，有“未运行测试”才写明：

<<< @/public/learn-agent-rust/code/context-compaction/src/main.rs#models

这些规则让压缩的效果直接体现在下一步动作上：规范被压掉就会重载，读过的源码被压掉就会重读。它没有测量真实模型在摘要之后的表现。

### 全部场景的实际结果

<!-- r08-results:start -->

| 场景 | 摘要器结果 | 压缩事件 | 审查模型请求 | 技能加载 | 给出结论 |
| --- | --- | --- | --- | --- | --- |
| `normal` | accepted，accepted | 2 | 9 | 2 | 是 |
| `small` | — | 0 | 8 | 1 | 是 |
| `intra` | accepted | 1 | 8 | 2 | 是 |
| `naive-trim` | — | 0 | 8 | 2 | 否 |
| `omit-fact` | rejected compaction.summary_facts，rejected compaction.summary_facts | 0 | 8 | 1 | 是 |
| `omit-unchecked` | accepted，accepted | 2 | 8 | 2 | 否 |
| `invent-fact` | rejected compaction.summary_facts，rejected compaction.summary_facts | 0 | 8 | 1 | 是 |
| `bad-json` | rejected compaction.summary_schema，rejected compaction.summary_schema | 0 | 8 | 1 | 是 |
| `summary-error` | failed model.unavailable，failed model.unavailable | 0 | 8 | 1 | 是 |
| `not-smaller` | accepted，accepted | 0 | 8 | 1 | 是 |

<!-- r08-results:end -->

运行之间的压缩每次运行结束都会做一次，所以 `normal` 的摘要器被调用两次（第二次压的是第二次运行）。`intra` 的压缩事件数是 1：运行之内的压缩也记进了会话；按源码，同一会话的下一次运行会从这份摘要开始，本章没有再运行一次去演示。<a href="/learn-agent-rust/outputs/r08-summary.txt" download>下载全部场景的摘要</a>。

### 与旧版场景的对应 {#old-scenarios}

| 旧版（自写压缩 + 两库） | 新版（ADK-Rust） | 变化 |
| --- | --- | --- |
| 自写消息分组、切口 | 框架决定切口 | `orphan`、`pending`（坏历史）删除：切口由框架保证。 |
| `normal`：落盘 + 占位 + 摘要 | `normal`：运行之间压缩；`intra`：运行之内压缩 | 摘要由应用的摘要器写，替换由框架做。 |
| `small`、`naive-trim` | 同名场景 | `naive-trim` 改用 `history_max_events`。 |
| `omit-fact`、`invent-fact`、`bad-json`、`summary-error` | 同名场景 | 失败时不再停止运行：框架保留原历史继续。 |
| `summary-large`（摘要超长） | `not-smaller` | 框架拒绝不比原文短的摘要。 |
| （无） | `omit-unchecked` | 不核对时，漏写的摘要会被接受。 |
| `micro-only`、`manual`、`retrieve`、`artifact-tamper`、`archive-error` | 删除 | 框架没有工具结果落盘与占位；需要时由应用另做（例如把大结果存成产物、只回传引用）。 |
| `hard-budget`、`summary-input-budget` | 删除 | 硬上限交给模型的上下文窗口；摘要调用计入运行预算。 |
| 17 个场景 | 10 个场景、5 项测试 | — |

验证脚本把工程打包后在临时目录解压，在旁边放好 ADK-Rust 源码，运行格式、Clippy、5 项 Rust 测试和离线构建；摘要和几条详细轨迹各连跑两次必须逐字节相同，并把结果表写回正文。维护者在网站仓库根目录执行：

```sh
python3 scripts/fetch-adk-rust.py .cache/adk-rust    # 只需一次；或设 ADK_RUST_SRC
python3 scripts/verify-agent-compaction.py
python3 scripts/generate-learn-agent-rust-figures.py --lesson R08
python3 scripts/verify-agent-compaction.py --check
```

## 框架替你做了什么、没做什么

| 框架做了 | 仍归应用 |
| --- | --- |
| 运行之间按次数压缩；运行之内按估算 token 压缩（默认开启）。 | 选阈值、保留条数；需要稳定轨迹的测试关掉运行之内压缩。 |
| 切口不分开调用与结果，不越过等待审批的调用。 | — |
| 摘要器出错、摘要不比原文短时，保留原历史继续运行；失败后暂缓重试。 | 写摘要器：决定保留哪些事实，并核对它们。 |
| 摘要调用计入运行预算。 | 把用户这一轮的请求和约束放进事实清单（它们也会被压缩）。 |
| `history_max_events` 只装入最近的事件。 | 判断丢掉的旧事件里有没有继续任务需要的东西。 |

<!-- adk-refs:start -->

## 在 ADK-Rust 源码里

本章的两种压缩、切口、摘要器与失败回退，在 ADK-Rust 里分布在这几处：

| 本章内容 | 源码位置 | 对照要点 |
| --- | --- | --- |
| 运行之间的压缩设置 | [`adk-core/src/callbacks.rs` · `EventsCompactionConfig`](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-core/src/callbacks.rs#L363-L371) | 每完成 `compaction_interval` 次运行压缩一次；`overlap_size` 次最近的运行不压 |
| 摘要器接口 | [`adk-core/src/callbacks.rs` · `BaseEventsSummarizer`](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-core/src/callbacks.rs#L350-L354) | 给一段事件，返回一条带摘要的压缩事件；返回 `None` 表示不压缩 |
| 框架自带的摘要器 | [`adk-core/src/event_summarizer.rs` · `LlmEventSummarizer`](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-core/src/event_summarizer.rs#L45-L48) | 通用提示“简洁地总结对话”；摘要不完整报错，不比原文短就不用 |
| 运行之内的压缩默认开启 | [`adk-core/src/intra_compaction.rs` 第 100 行](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-core/src/intra_compaction.rs#L100) | 阈值为模型窗口的 80%，窗口未知时 10 万估算 token；默认保留最近 10 条 |
| 运行结束后的压缩 | [`adk-runner/src/runner.rs` 第 2131 行](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-runner/src/runner.rs#L2131) | 按运行次数触发；切口不分开调用与结果，不越过等待审批的调用；压缩事件写进会话 |
| 运行之间压缩失败 | [`adk-runner/src/runner.rs` 第 2221 行](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-runner/src/runner.rs#L2221) | 摘要器出错只记警告，会话保持原样 |
| 运行之内压缩失败 | [`adk-runner/src/intra_compaction.rs` 第 474 行](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-runner/src/intra_compaction.rs#L474) | 摘要器出错或返回空，保留这次请求的历史 |
| 不比原文短的摘要 | [`adk-runner/src/intra_compaction.rs` 第 489 行](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-runner/src/intra_compaction.rs#L489) | 框架按估算 token 比较，摘要不更短就不替换 |
| 运行之内压缩的切口 | [`adk-runner/src/intra_compaction.rs` · `session_cut`](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-runner/src/intra_compaction.rs#L1056-L1100) | 为了把压缩记进会话，切口要能在会话事件里精确定位：不分开调用与结果，前后时间戳在毫秒上分得开；找不到就整段压缩、不记录 |
| 失败后暂缓重试 | [`adk-runner/src/intra_compaction.rs` 第 662 行](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-runner/src/intra_compaction.rs#L662) | 一次没压成之后，历史长到一定程度前不再尝试 |
| 只装入最近的事件 | [`adk-core/src/context.rs` 第 1752 行](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-core/src/context.rs#L1752) | 每次运行开始时只取最近 N 条事件，不调用摘要器 |

源码固定在 ADK-Rust `98515241133d`（3.0.0，2026-11-26，尚未发布到 crates.io）。本节由 `scripts/learn-agent-rust-adk-refs.py` 生成。

<!-- adk-refs:end -->

::: warning 常见误区
- 估算 token 能用于这个实验的触发判断，不能直接解释为某个模型的 token、费用或上下文窗口。
- 运行之内压缩默认开启：没有显式关掉时，长任务的历史可能在你不知情时被摘要替换。
- 摘要保留的是清单里声明过的事实；用户的请求和约束也会被压缩，未列入清单的细节可能消失。
- 摘要失败不会让运行停下，只是不压缩；如果请求因此被模型以“超过上下文窗口”拒绝，框架会不管阈值和暂缓、再压缩一次并重发，仍失败才报错。
- 框架自带的摘要器不知道你的任务里什么不能丢；关键任务要自己写摘要器并核对。
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

这次审查能够在压缩之后继续，是因为摘要保留了目标、发现、测试状态、约束和用户这一轮的请求，审查模型随后又真实重读了源码。ADK-Rust 负责什么时候压缩、切在哪里、失败时保留原历史；摘要写什么、怎样核对，是应用的事。

只看体积会被误导：`naive-trim` 和 `omit-unchecked` 都让请求变短了，任务却无法继续。下一步再考虑哪些经过确认的事实值得带到新会话。

## 检查理解

1. 为什么只保留最近几条事件，即使调用与结果配对正确，仍可能无法继续任务？

   <details><summary>参考答案</summary>

   结构正确只能说明调用与结果对应。目标路径、旧发现或用户的约束可能位于更早的历史里。`naive-trim` 只装入最近 2 条事件，丢失了目标文件，模型报告 `missing_evidence`。

   </details>

2. 摘要器核对不通过时，为什么第二次运行仍能给出正确结论？

   <details><summary>参考答案</summary>

   摘要器返回错误，框架不写压缩事件，保留原历史继续运行。第二次运行拿到完整历史，只是请求没有变短。压缩是可选的优化，失败的后果是“没压缩”，而不是“压错了”。

   </details>

3. 本例能发现“测试通过”是虚构的，是否证明它能检查任意摘要的真假？

   <details><summary>参考答案</summary>

   只能证明它拒绝了对应用已知事实的篡改。清单声明了“未运行测试”，核对器要求摘要保持一致。怎样从任意历史选择正确事实、理解语义和处理冲突，需要另外的设计与评估。

   </details>

4. 为什么事实清单里要有 `latest_request`？

   <details><summary>参考答案</summary>

   ADK-Rust 的压缩把用户消息也交给摘要器。运行之内压缩时，用户这一轮“读完资料后给出结论”的请求只存在于摘要里；清单里没有它，模型压缩之后就不知道要给结论。

   </details>

5. 第二次运行开始时，为什么审查模型要重新加载审查规范？

   <details><summary>参考答案</summary>

   第一次运行的事件被摘要替换，摘要只带清单上的事实，规范正文不在其中；具体方法在正文里。模型看不到正文，就重新调用 `load_skill` 把它放回请求。这也是第 10 章“正文进入会话”的另一面：压缩会把它拿走。

   </details>

## 参考资料

- [参考课程：s08 Context Compact](https://learn.shareai.run/zh/s08/)，用于对照分层处理的思路和下方原图。
- [Claude 官方 Context editing](https://platform.claude.com/docs/en/build-with-claude/context-editing)：旧工具结果清理与摘要的不同职责。
- [Claude 官方 Token counting](https://platform.claude.com/docs/en/build-with-claude/token-counting)：真实请求的 token 统计。
- [ADK-Rust 固定源码](https://github.com/zavora-ai/adk-rust/tree/98515241133d24f7e41f8fd272649035416a142f)：本课程真实运行的接口与语义基线。

## 保留的参考原图

以下图片原样保留自参考课程，展示其 Python/Claude 教学实现；图中接口、编号和统计沿用原图。下面用来对照压缩位置与执行顺序；其中的大结果落盘和旧结果占位（micro-compact、layer1-budget）本章新版没有实现。本章的 Rust 数据以自制图和实验记录为准。

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
