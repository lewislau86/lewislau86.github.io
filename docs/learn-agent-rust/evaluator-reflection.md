---
title: "第 21 章：评估、反思与有界修复"
description: "用 ADK-Rust 3.0 的 LoopAgent 让写作者与按固定规则检查的评估者轮流工作，每轮重验全部规则，在通过、无进展或轮数用完时停下；再看 adk-retry-reflect 怎样在工具失败后给模型一段有上限的反思提示。"
pageClass: learn-agent-rust-course
prev:
  text: 第 20 章 · 协调者、工作者与任务交接
  link: /learn-agent-rust/orchestrator-workers-handoffs
next:
  text: 第 22 章 · 人工介入与审批恢复
  link: /learn-agent-rust/human-in-the-loop
---

# 第 21 章：评估、反思与有界修复

[课程总览](./index.md) · [上一章](./orchestrator-workers-handoffs.md) · [本部分导读](./agent-design-patterns.md) · [学习路径](./learning-path.md#d06) · [下一章](./human-in-the-loop.md)

::: tip 本章学习目标
- 把“写得好不好”缩成几条可以检查的规则，让评估和生成分开，反馈指向具体缺陷。
- 用 `LoopAgent` 组织“生成—评估—修复”，每轮重验全部规则，并说清循环在哪三种情况下停下。
- 看懂框架提供的另一种“反思”：工具失败后，adk-retry-reflect 给模型一段有次数上限的提示。

**前置：** [第 17 章：提示链与条件路由](./prompt-chaining-routing.md)、[第 19 章：规划、执行与动态重规划](./plan-execute-replan.md)。

**实践方式：** 下载<a href="/learn-agent-rust/evaluator-reflection.zip" download>完整 evaluator-reflection.zip</a>，按[第 1 节](#hands-on)取一次 ADK-Rust 源码后运行；无需模型密钥。
:::

::: info 本章已迁移到 ADK-Rust 3.0
旧版用 graph-flow 的节点手写生成、评估、修复和跳转，可从 git 标签 `learn-agent-rust-v1` 取得。新版用 `LoopAgent` 让写作者（`LlmAgent`）和评估者（`CustomAgent`）轮流运行，另加一节 adk-retry-reflect 插件。[对应表](#old-scenarios)列出了场景的变化。
:::

写作者交出一段升级摘要，结论没有来源。让它“再想想”是不够的：同一个模型说自己“已自查，没有问题”，并不说明什么。能推动修复的，是一条说得清的缺陷：缺来源、来源没读过、正文是空的。

这一章的做法是把生成和评估分开。写作者写稿；评估者按固定规则逐条检查，把没通过的规则写成反馈；写作者照着反馈改，评估者再查一遍全部规则。循环必须有尽头：通过了就收工，改了等于没改就停下，轮数用完也停下。

<LearnAgentRustMap active="evaluator-reflection" />

<!-- experiment-library:start -->

全书实验可从[统一代码库](./experiments.md#evaluator-reflection)下载；解压后进入 `chapters/evaluator-reflection/`，或在代码库根目录运行 `python3 run.py run D06`。

<!-- experiment-library:end -->

::: info 本章实验状态
`LoopAgent`、`LlmAgent`、`CustomAgent`、`output_key`、指令模板和 adk-retry-reflect 插件都是 ADK-Rust 的真实实现。写作者和读文件的模型是按规则回复的替身：写作者按场景写出缺来源、丢正文或原样重复的稿子，读文件的模型按场景改正或不改正路径。评估规则只有三条，用来检验修复机制，不代表对真实报告的全面评分；真实模型的修复质量没有测试。
:::

## 1. 先运行：八个场景 {#hands-on}

下载并解压工程，先取一次 ADK-Rust 源码再运行：

```sh
cd evaluator-reflection
python3 fetch-adk-rust.py ../adk-rust    # 需要 git 与 GitHub 访问；不行时加 --method cdn
cargo run --locked
```

编译时会看到 adk-core 的 3 条弃用警告（上游固定 Rust 1.95.0，本课程用 1.99.1），不影响运行和检查。

<<< @/public/learn-agent-rust/outputs/d06-summary.txt

前五个场景是修复循环：`checks` 是每一稿的检查结果（`r2:empty_text` 表示第 2 稿没通过“正文非空”），`iterations` 是评估了几轮，`baseline` 是留作基线的那一稿，`stop` 是循环怎样结束。后三个场景是工具失败的反思：`calls` 是每次调用 `read_file` 用的路径和得到的结果（`reflection` 表示结果被换成了反思提示），`outcome` 是模型最后读到了文件还是放弃，`stop=answered` 表示运行以模型的回答正常结束（出错时会是 `error:<错误码>`）。

## 2. 生成与评估分开

写作者是一个 `LlmAgent`，最终回答通过 `output_key` 写进会话状态 `draft`。它的指令里有两个模板：

<<< @/public/learn-agent-rust/code/evaluator-reflection/src/main.rs#loop

`{draft?}` 和 `{feedback?}` 在写作者每次运行开始时按会话状态渲染，所以每一轮它都读得到上一稿和最新的反馈。替身写作者只按反馈里没通过的规则改稿：缺来源就补来源，正文空了就补正文；详细轨迹的最后有一行“每一稿依据的反馈”，记下它每次读到了什么。评估者是代码，不是模型：

<<< @/public/learn-agent-rust/code/evaluator-reflection/src/main.rs#evaluator

三条规则都只看稿子本身：正文不能为空，至少有一个来源，来源必须在允许列表里（本例用它代表工作区里读过的两个文件）。反馈带着被检查那一稿的修订号写进状态 `feedback`，写作者只采用修订号和上一稿对得上的反馈。在本章的循环里评估者总是紧跟写作者运行，两者总对得上，所以这道检查没有被触发过。第一次评估时，那一稿另存为基线 `baseline`，以后要比较修复前后，就拿它对照。

轨迹里写作者每一轮有两行 `final`：一行跟着回答，一行跟着 `output_key` 写状态的事件。

`normal` 的第一稿结论正确，也写着“已自查，没有问题”，但没有来源。评估者不看这句自查，`missing_source` 照样不通过；第二稿补上 `README.md`，三条全过，评估者把事件标成 escalate（上报），`LoopAgent` 在它之后结束。`already-good` 第一稿就通过，只评估了一轮。

## 3. 修复以后，重验全部规则

<<< @/public/learn-agent-rust/outputs/d06-new-error.txt

`new-error` 的第二稿按反馈补上了来源，却把正文弄丢了。如果评估者只复查上一轮没通过的那一条，第二稿就“修好了”。它每一轮都重验全部规则，所以 `empty_text` 被抓住，写作者再改一轮，第三稿才通过：`checks=[r1:missing_source,r2:empty_text,r3:pass]`。

修复只能改变候选稿，不能改变验收规则。“上次缺的来源已经补上了”不是通过的理由。

## 4. 三种结束

| 结束方式 | 场景 | 怎样发生 |
| --- | --- | --- |
| `accepted` | `normal`、`already-good`、`new-error` | 全部规则通过，评估者上报 |
| `no_progress` | `no-progress` | 第二稿和第一稿的正文、来源完全一样，评估者上报停下 |
| `loop_limit` | `never-good` | 第一稿缺来源，之后每稿换一个说法，引用的却总是不在允许列表里的网页；3 轮用完，循环安静地结束 |

<<< @/public/learn-agent-rust/outputs/d06-never-good.txt

`never-good` 的稿子每轮都在变，所以“没有进展”的检查拦不住它；它也从来没通过。拦住它的是 `with_max_iterations(3)`。`LoopAgent` 轮数用完不报错，不设上限时默认是 1000 轮。所以循环结束后，应用要看是谁、为什么结束的：只有评估者以 `accepted` 上报，这一稿才能交出去。另两种结束都要按“没有合格结果”处理，基线和最后一稿都留在状态里，供人对照。

“没有进展”本章只比较正文和来源有没有变化。复杂任务需要事先定义独立的进展指标，比如没通过的规则数有没有下降。

## 5. 工具失败后的反思

上面的反馈来自应用自己写的评估者。框架还提供一种针对工具失败的“反思”：adk-retry-reflect 插件。工具返回错误时，它把结果换成一段提示，列出错误、原来的参数，请模型改参数重试。

<<< @/public/learn-agent-rust/code/evaluator-reflection/src/main.rs#reflect

<<< @/public/learn-agent-rust/outputs/d06-tool-retry.txt

`tool-retry` 里模型把 `README.md` 写成了 `READMe.md`。工具报 `tool.file_not_found`，插件把结果换成 `{"reflection": "[RETRY GUIDANCE - Attempt 1/2] ..."}`，模型改正路径，第二次读到了。

要注意两点：

- **提示替换了原来的结果。** 轨迹里这一次的状态是 `status=ok`，结构化的失败状态和错误码都不再保留，只在提示文字里转述。按工具状态统计失败次数的应用，会把这几次失败漏掉。
- **次数按“工具 + 参数”分别计。** `tool-retry-exhausted` 一直用同一个错路径：前两次有提示（`Attempt 1/2`、`2/2`），第三次时 2 次已经用满，原始错误（`status=failed code=tool.file_not_found`）直接交给模型，模型放弃。`tool-retry-wandering` 每次换一个错路径，每个路径都只失败一次，单次上限永远到不了；拦住它的是 `global_limit(3)`：整次运行给过 3 次提示以后，第 4 次失败原样交给模型。

<<< @/public/learn-agent-rust/outputs/d06-tool-retry-wandering.txt

插件只管“工具调用失败”这一种反馈。授权被拒、非幂等工具超时（可能已经执行了）它都原样放过，不建议重试。结果写得好不好，它不评估，那仍然是第 2–4 节评估者的事。

![左边是 LoopAgent 里的生成—评估—修复：写作者写稿，评估者按固定规则检查，通过或没有进展就上报，最多 3 轮；右边是 adk-retry-reflect：工具失败时用反思提示替换结果，同一参数最多 2 次、整次运行最多 3 次，超过后原始错误交给模型。](/learn-agent-rust/figures/d06-pattern-flow.svg)

左右两半分别是修复循环和工具失败的反思；底部两行是本章场景的实际结果。

### 全部场景的实际结果

<!-- d06-results:start -->

| 场景 | 每一稿的检查结果 | 轮数 | 结束方式 | 读文件的尝试 | 结果 |
| --- | --- | --- | --- | --- | --- |
| `normal` | `[r1:missing_source,r2:pass]` | `2` | `accepted` | — | — |
| `already-good` | `[r1:pass]` | `1` | `accepted` | — | — |
| `new-error` | `[r1:missing_source,r2:empty_text,r3:pass]` | `3` | `accepted` | — | — |
| `no-progress` | `[r1:missing_source,r2:missing_source]` | `2` | `no_progress` | — | — |
| `never-good` | `[r1:missing_source,r2:unread_source,r3:unread_source]` | `3` | `loop_limit` | — | — |
| `tool-retry` | — | — | `answered` | `[READMe.md:reflection,README.md:ok]` | `read` |
| `tool-retry-exhausted` | — | — | `answered` | `[READMe.md:reflection,READMe.md:reflection,READMe.md:error]` | `gave_up` |
| `tool-retry-wandering` | — | — | `answered` | `[READMe.md:reflection,readme.md:reflection,Readme.md:reflection,README.txt:error]` | `gave_up` |

<!-- d06-results:end -->

### 与旧版场景的对应 {#old-scenarios}

| 旧版（graph-flow 夹具） | 新版（ADK-Rust） | 变化 |
| --- | --- | --- |
| `normal` | `normal` | 写作者与评估者由 `LoopAgent` 轮流运行，第一稿附带“已自查”。 |
| `already_good` | `already-good` | — |
| `new_error` | `new-error` | 旧版以无进展结束；新版再修一轮，第三稿通过。 |
| `no_progress` | `no-progress` | — |
| `budget` | `never-good` | 由 `LoopAgent` 的轮数上限结束。 |
| `stale` | （无） | 写作者只采用修订号对得上的反馈；评估者总是紧跟写作者运行，本章的循环里不会出现过期反馈，没有单独演示。 |
| `malformed` | （无） | 反馈由代码写出，不会格式错误；写作者的稿子不是 JSON 时，评估者读不出内容，按“正文为空、缺来源”不通过。要让模型输出先过结构校验，可用[第 17 章](./prompt-chaining-routing.md)的 `output_schema`。 |
| （无） | `tool-retry`、`tool-retry-exhausted`、`tool-retry-wandering` | adk-retry-reflect 插件。 |
| 7 个场景、4 项测试 | 8 个场景、4 项测试 | — |

验证脚本把工程打包后在临时目录解压，在旁边放好 ADK-Rust 源码，运行格式、Clippy、4 项 Rust 测试和离线构建；摘要和 7 条详细轨迹各连跑两次必须逐字节相同，并把结果表写回正文。维护者在网站仓库根目录执行：

```sh
python3 scripts/fetch-adk-rust.py .cache/adk-rust    # 只需一次；或设 ADK_RUST_SRC
python3 scripts/verify-agent-patterns-adk.py --lesson D06
python3 scripts/generate-learn-agent-rust-figures.py --lesson D06
python3 scripts/verify-agent-patterns-adk.py --lesson D06 --check
```

## 框架替你做了什么、没做什么

| 框架做了 | 仍归应用 |
| --- | --- |
| `LoopAgent` 每轮按顺序运行写作者和评估者；上报就停，轮数用完也停（不报错）。 | 定义可检查的规则；判断循环是通过、无进展还是轮数用完。 |
| 指令模板每次运行渲染最新状态；`output_key` 把最终回答写进状态。 | 反馈的格式和修订号核对；保留基线；定义“没有进展”。 |
| adk-retry-reflect：工具失败时换成反思提示，按参数和整次运行限次。 | 统计真实失败次数（提示会把失败状态盖掉）；评估结果本身的质量。 |

<!-- adk-refs:start -->

## 在 ADK-Rust 源码里

本章的修复循环与工具失败的反思提示，在 ADK-Rust 里分布在这几处：

| 本章内容 | 源码位置 | 对照要点 |
| --- | --- | --- |
| 轮数上限 | [`adk-agent/src/workflow/loop_agent.rs` 第 15 行](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-agent/src/workflow/loop_agent.rs#L15) | 不设 `with_max_iterations` 时最多 1000 轮；用完就安静地结束，不报错 |
| 每轮重新渲染指令 | [`adk-agent/src/llm_agent.rs` 第 426 行](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-agent/src/llm_agent.rs#L426) | 写作者每次运行开始时按会话状态渲染 `{draft?}`、`{feedback?}`，所以总能读到上一轮的稿子和反馈 |
| 反思插件 | [`adk-retry-reflect/src/plugin.rs` · `after_tool_call`](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-retry-reflect/src/plugin.rs#L128-L285) | 工具结果是失败（带 `error` 键、`isError: true` 或以 `Error:` 开头）时换成一段反思提示；授权拒绝、非幂等工具超时原样放过 |
| 按参数计数 | [`adk-retry-reflect/src/plugin.rs` 第 201 行](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-retry-reflect/src/plugin.rs#L201) | 次数按“工具 + 参数”分别计；换个参数就重新计数，所以还要 `global_limit` |
| 次数用完 | [`adk-retry-reflect/src/plugin.rs` 第 215 行](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-retry-reflect/src/plugin.rs#L215) | 超过上限就不再给提示，原始错误交给模型 |
| 提示替换了结果 | [`adk-agent/src/llm_agent.rs` 第 3881 行](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-agent/src/llm_agent.rs#L3881) | 插件改过的结果按新结果交给模型，失败状态和错误码不再保留 |

源码固定在 ADK-Rust `98515241133d`（3.0.0，2026-11-26，尚未发布到 crates.io）。本节由 `scripts/learn-agent-rust-adk-refs.py` 生成。

<!-- adk-refs:end -->

::: warning 常见误区
- **把模型的“已自查”当成通过。** 通过只看评估者的规则。
- **修复后只复查上一条。** 修复可能引入新错误，每轮都要重验全部规则。
- **以为循环结束就是做完了。** 轮数用完和无进展都会结束循环，都没有合格结果。
- **以为反思提示是在评估结果质量。** adk-retry-reflect 只处理工具调用失败。
- **只设单次重试上限。** 模型每次换个参数就能绕过，要同时设整次运行的上限。
:::

<!-- transfer-thinking:start -->

## 迁移思考：修复后重验完整合同

补充来源时把正文删空，为什么不能接受？先给出你的判断，再展开下面的推演。

<details><summary>推演与应用</summary>

修复只能改变候选稿，不能改变验收规则。评估者每一轮都重验全部规则：补上来源的同时把正文弄丢了，`empty_text` 照样不通过，要再修一轮。写作者自己说“已自查”，也不算通过。

自动修代码以后也要重跑全部相关检查，不能只看原来那一条失败消失了。

</details>

这是一道迁移练习，推演不代表新增实验已通过。对照[全书审查中的证据层次](./course-review.md#evidence-layers)，说明你的判断还需要哪一级证据。

<!-- transfer-thinking:end -->

## 本章结论

先把质量要求缩成可检查的规则，再让评估和生成分开：写作者照反馈改，评估者每轮重验全部规则，第一稿留作基线。循环有三种结束，只有“全部通过”才交出结果；无进展和轮数用完都要按失败处理。框架内置的反思针对工具失败，用有上限的提示帮模型改参数，它不评估结果，还会盖掉失败状态。规则通过只说明产物符合这几条规则，不说明真实模型写得更好。

## 检查理解

1. `normal` 的第一稿写着“已自查，没有问题”，为什么还要修？

   <details><summary>参考答案</summary>

   评估者只按规则检查，不看写作者的自我评价。第一稿没有来源，`missing_source` 不通过。

   </details>

2. `new-error` 为什么需要三轮？

   <details><summary>参考答案</summary>

   第二稿补了来源却把正文弄丢了。评估者每轮重验全部规则，抓住了 `empty_text`，第三稿才通过。

   </details>

3. `never-good` 每稿都不一样，为什么“没有进展”的检查拦不住它？最后是什么拦住的？

   <details><summary>参考答案</summary>

   本章的进展检查只看正文和来源有没有变化，`never-good` 从第二稿起每稿都换了说法。拦住它的是 `LoopAgent` 的 3 轮上限；循环安静地结束，应用要把它当作没有合格结果。

   </details>

4. 为什么 `tool-retry-wandering` 需要 `global_limit`？

   <details><summary>参考答案</summary>

   `max_retries` 按“工具 + 参数”分别计数，模型每次换一个路径，每个路径都只失败一次。`global_limit(3)` 限制整次运行的提示总数，第 4 次失败原样交给模型。

   </details>

5. 用 adk-retry-reflect 以后，按工具结果的状态统计失败次数还准吗？

   <details><summary>参考答案</summary>

   不准。插件把失败结果换成提示后，状态变成 `ok`，结构化的错误码也不再保留。要统计失败，可以用 `after_tool_callback` 记录（它在插件之前运行），或者看插件的日志事件 `retry_reflect.retry`、`retry_reflect.exhausted`、`retry_reflect.global_limit_exhausted`。

   </details>

## 参考资料

- [Building effective agents](https://www.anthropic.com/research/building-effective-agents)：评估者—优化者等工作流模式的工程导读。
- [Reflexion](https://arxiv.org/abs/2303.11366)：跨尝试的语言反馈与反思记忆，区别于本章的单次结果修复。
- [ADK-Rust 固定源码](https://github.com/zavora-ai/adk-rust/tree/98515241133d24f7e41f8fd272649035416a142f)：`LoopAgent` 与 adk-retry-reflect 的实现。

下一章：[第 22 章 · 人工介入与审批恢复](./human-in-the-loop.md)。回到[本部分导读](./agent-design-patterns.md)比较模式。
