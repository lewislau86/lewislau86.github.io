---
title: "第 17 章：提示链与条件路由"
description: "用 ADK-Rust 3.0 把“抽取 → 质量门 → 写报告”串成提示链，并比较三种路由：模型给标签的 LlmConditionalAgent、代码判断的 ConditionalAgent、带置信度的 DecisionAgent；用 output_schema 和修订门挡住不合格或过期的中间产物。"
pageClass: learn-agent-rust-course
prev:
  text: 第 16 章 · 模式选择：单次调用、工作流与自主循环
  link: /learn-agent-rust/pattern-selection
next:
  text: 第 18 章 · 并行分解与结果归并
  link: /learn-agent-rust/parallel-decomposition
---

# 第 17 章：提示链与条件路由

[课程总览](./index.md) · [上一章](./pattern-selection.md) · [本部分导读](./agent-design-patterns.md) · [学习路径](./learning-path.md#d02) · [下一章](./parallel-decomposition.md)

::: tip 本章学习目标
- 把一个任务拆成“抽取 → 质量门 → 写报告”的提示链，让每一步只消费检查过的中间产物。
- 比较三种路由：模型给标签、代码判断、模型做带置信度的类型化决定，知道各自在哪里出错、怎样兜底。
- 用 `output_schema` 约束中间产物的格式，用修订门挡住“格式对、但属于上一版”的产物。

**前置：** [第 16 章：模式选择](./pattern-selection.md)、[第 5 章：图状态、条件路由与有界循环](./graph-state-routing.md)。

**实践方式：** 下载<a href="/learn-agent-rust/prompt-chaining-routing.zip" download>完整 prompt-chaining-routing.zip</a>，按[第 1 节](#hands-on)取一次 ADK-Rust 源码后运行；无需模型密钥。
:::

::: info 本章已迁移到 ADK-Rust 3.0
旧版用 graph-flow 的节点手写路由与产物门，分类和抽取都是夹具，可从 git 标签 `learn-agent-rust-v1` 取得。新版用 ADK-Rust 的 `SequentialAgent` 串链，路由换成框架自带的三种路由 Agent，抽取用 `output_schema` 约束。[对应表](#old-scenarios)列出了场景的变化。
:::

升级报告要用到项目里的不同文件：README 里写着目标版本，Cargo.toml 里写着测试命令。用户每次交来一个文件，第一行写着“文件：名字 修订：rN”，后面是内容。

处理一个文件有固定的步骤：先把需要的字段抽成结构化的产物，检查产物，再写一句报告。不同类型的文件抽取方法不同，所以入口先按类型分流。不认识的文件不进任何处理链，请用户补交。

先猜两件事：模型分类时多说了几个字，例如“不是 readme，是 license”，会被分到哪里？同一个会话里第二次交文件，抽取那一步照抄了上一次的修订号，后面还会照常写报告吗？

<LearnAgentRustMap active="prompt-chaining-routing" />

<!-- experiment-library:start -->

全书实验可从[统一代码库](./experiments.md#prompt-chaining-routing)下载；解压后进入 `chapters/prompt-chaining-routing/`，或在代码库根目录运行 `python3 run.py run D02`。

<!-- experiment-library:end -->

::: info 本章实验状态
三种路由 Agent、`SequentialAgent`、`output_schema` 的校验与重试、`CustomAgent` 的 escalate 都是 ADK-Rust 的真实实现。分类、决定、抽取和写报告都由按规则回复的替身模型完成，只看自己收到的请求；真实模型的分类准确率没有测试。
:::

## 1. 先运行：十个场景 {#hands-on}

下载并解压工程，先取一次 ADK-Rust 源码再运行：

```sh
cd prompt-chaining-routing
python3 fetch-adk-rust.py ../adk-rust    # 需要 git 与 GitHub 访问；不行时加 --method cdn
cargo run --locked
```

编译时会看到 adk-core 的 3 条弃用警告（上游固定 Rust 1.95.0，本课程用 1.99.1），不影响运行和检查。

<<< @/public/learn-agent-rust/outputs/d02-summary.txt

`router` 是路由方式，`route` 是实际进入的分支，`agents` 是事件里出现过的 Agent，`model_calls` 按顺序列出每次模型调用在做什么（`route` 分类、`decide` 决定、`extract` 抽取、`render` 写报告），`gate` 是质量门的结论，`outcome` 是这次的结果。

## 2. 一条提示链：抽取 → 质量门 → 写报告

<<< @/public/learn-agent-rust/code/prompt-chaining-routing/src/main.rs#chain

三步用 `SequentialAgent` 串起来，靠会话状态传递产物：

1. **抽取**：带 `output_schema` 的 `LlmAgent`，把文件抽成 JSON（来源、修订、类别、值），用 `output_key` 写进状态里的 `artifact`。
2. **质量门**：一个由代码写的 `CustomAgent`。产物的修订号不是这次输入的，或者来源文件、类别对不上这条链，就把事件标成 escalate（上报：告诉外层“到此为止”），链立刻停下。
3. **写报告**：`LlmAgent` 用 `{artifact}` 模板读产物，写一句报告。

`readme` 和 `cargo` 两个场景走完整条链：分类、抽取、写报告各调用一次模型，质量门通过。

### `output_schema`：格式不对就重试

抽取的回复必须符合 schema，四个字段一个不能少。不符合时，框架在这次运行的请求里追加一条纠正提示（“Your output did not match the required schema …”）让模型重写；这条提示不写进会话事件，不合格的那次回复却会作为一条事件留在历史里。重写 `output_max_retries` 次之后仍不符合，就以错误结束这次运行。框架只在校验通过后才写 `output_key`，不合格的回复不会进状态。

- `schema-retry`：替身第一次漏写了 `value`，收到纠正提示后补上，`model_calls` 里有两次 `extract`，之后照常写报告。
- `missing-field`：README 里根本没写目标版本，重写一次还是没有，运行以 `output schema validation failed after 1 attempts` 结束，质量门和写报告都没有运行。错误里的 1 是重试次数，算上第一次一共调用了两次模型。

<<< @/public/learn-agent-rust/outputs/d02-missing-field.txt

### 修订门：格式对，但属于上一版

`stale` 场景在同一个会话里先交 r1，再交 r2。第二次抽取时，替身模型照抄了历史里第一次出现的修订号 r1：

<<< @/public/learn-agent-rust/outputs/d02-stale.txt

这个产物完全符合 schema，`output_key` 照常写进了状态。挡住它的是质量门：它比对产物的修订号和这次输入的修订号，发现是 r1，返回 `stale_artifact:r1` 并 escalate，写报告的那一步没有运行。字段齐全和属于当前版本是两个条件，schema 只管前一个。

还有一种更隐蔽的情况：抽取失败时这次运行已经报错结束，会话状态里留着的却是上一次运行的产物。下一次运行如果跳过了抽取，旧产物就会被当成新的。质量门比对修订号，正是为了不信任状态里“碰巧有”的东西。

## 3. 三种路由

<<< @/public/learn-agent-rust/code/prompt-chaining-routing/src/main.rs#routers

| 路由 | 谁来判断 | 出错时 | 本章场景 |
| --- | --- | --- | --- |
| `LlmConditionalAgent` | 模型回一段文字，框架去掉首尾空白、转成小写后按标签匹配 | 先找完全相同的标签，找不到就看回复里**包含**哪个标签（长的优先）；都没有走默认分支；连默认分支也没有，只产出一条说明文字，不报错 | `readme`、`cargo`、`unknown`、`substring-trap` |
| `ConditionalAgent` | 代码里的一个判断函数 | 只有两个分支，三路就嵌套一层；判断写死在代码里 | `rule-router`、`rule-router-other` |
| `DecisionAgent` | 模型在列出的选项里选一个，并给理由和置信度 | 选项以外的回答是错误；置信度低于门槛走兜底，没设兜底就以错误结束；回复里缺置信度按 0 算 | `low-confidence` |

因为转成了小写，标签本身要写成小写，否则永远匹配不上。

**包含匹配的坑**：`substring-trap` 交的是 LICENSE，替身模型回答“不是 readme，是 license”。这段话不等于任何标签，但包含 `readme`，于是被分进了 README 处理链：

<<< @/public/learn-agent-rust/outputs/d02-substring-trap.txt

这次是下游的 schema 兜住了：LICENSE 里抽不出目标版本，运行以错误结束，没有写出报告。但这是碰巧：如果 LICENSE 里恰好有一行“目标版本：”，抽取就会成功。所以质量门还比对产物的来源文件和类别（这条链只收 README），路由错了，下游也能认出来。另外留意，用户得到的是一个错误，而不是“请补交文件”。

**代码路由**：`rule-router` 按文件名判断，`model_calls` 里没有 `route`，分类不花一次模型调用。`ConditionalAgent` 只有两个分支，所以嵌套了一层：Cargo.toml 走 cargo 链，否则再看是不是 README.md，其余走兜底。`rule-router-other` 交的 LICENSE 就进了兜底，一次模型都没调用。代价是只能处理代码里写到的文件名。

**类型化决定**：`low-confidence` 交的是 notes.md，替身模型选了 readme，但置信度只有 0.3，低于 0.6 的门槛，走兜底分支请用户补交。决定的结果连同理由、置信度和“是否采纳”写进了状态里的 `route`：

<<< @/public/learn-agent-rust/outputs/d02-low-confidence.txt

置信度是模型自报的数字，不是校准过的概率；门槛要用真实样本另外定。

分类和决定的那次模型调用不属于任何一个 `LlmAgent`，不算进 `max_iterations`（第 16 章），而是计入整次运行的预算（如果在运行配置里设了预算）；schema 的重写则算在抽取那个 `LlmAgent` 的 `max_iterations` 里。

![文件先经路由进入对应的处理链：模型标签按包含匹配、代码按文件名、类型化决定带置信度门槛；链里抽取受 schema 约束，质量门比对修订号，通过才写报告。](/learn-agent-rust/figures/d02-pattern-flow.svg)

上面一行是三种路由，它们都把文件交给处理链的第一步（或兜底）；下面一行是一条处理链的三步，每格写着在这一步停下的场景。

### 全部场景的实际结果

<!-- d02-results:start -->

| 场景 | 路由 | 进入的分支 | 模型调用 | 质量门 | 结果 |
| --- | --- | --- | --- | --- | --- |
| `readme` | `llm` | `readme` | `[route,extract,render]` | `passed` | `report` |
| `cargo` | `llm` | `cargo` | `[route,extract,render]` | `passed` | `report` |
| `unknown` | `llm` | `needs_input` | `[route]` | `-` | `needs_input` |
| `substring-trap` | `llm` | `readme` | `[route,extract,extract]` | `-` | `error` |
| `rule-router` | `rule` | `cargo` | `[extract,render]` | `passed` | `report` |
| `rule-router-other` | `rule` | `needs_input` | `[]` | `-` | `needs_input` |
| `low-confidence` | `decision` | `needs_input` | `[decide]` | `-` | `needs_input` |
| `missing-field` | `llm` | `readme` | `[route,extract,extract]` | `-` | `error` |
| `schema-retry` | `llm` | `readme` | `[route,extract,extract,render]` | `passed` | `report` |
| `stale` | `llm` | `readme` | `[route,extract,render,route,extract]` | `stale_artifact:r1` | `stopped` |

<!-- d02-results:end -->

### 与旧版场景的对应 {#old-scenarios}

| 旧版（graph-flow 夹具） | 新版（ADK-Rust） | 变化 |
| --- | --- | --- |
| `readme`、`cargo` | `readme`、`cargo` | 链改为 `SequentialAgent`，路由改为 `LlmConditionalAgent`。 |
| `unknown` | `unknown` | 走默认分支 `needs_input`。 |
| `missing` | `missing-field`、`schema-retry` | 字段检查交给 `output_schema`，新增“重试后补上”的对照。 |
| `stale` | `stale` | 修订门由 `CustomAgent` 做，escalate 停链。 |
| `budget` | 删除 | 调用上限见第 16 章的 `max_iterations`。 |
| （无） | `substring-trap`、`rule-router`、`rule-router-other`、`low-confidence` | 三种路由的差别。 |
| 6 个场景、4 项测试 | 10 个场景、4 项测试 | — |

验证脚本把工程打包后在临时目录解压，在旁边放好 ADK-Rust 源码，运行格式、Clippy、4 项 Rust 测试和离线构建；摘要和几条详细轨迹各连跑两次必须逐字节相同，并把结果表写回正文。维护者在网站仓库根目录执行：

```sh
python3 scripts/fetch-adk-rust.py .cache/adk-rust    # 只需一次；或设 ADK_RUST_SRC
python3 scripts/verify-agent-patterns-adk.py --lesson D02
python3 scripts/generate-learn-agent-rust-figures.py --lesson D02
python3 scripts/verify-agent-patterns-adk.py --lesson D02 --check
```

## 框架替你做了什么、没做什么

| 框架做了 | 仍归应用 |
| --- | --- |
| 三种路由 Agent；模型分类与决定的调用计入运行预算（设了的话）。 | 选哪种路由；给模型路由设兜底分支。 |
| `output_schema` 校验、带纠正提示重试、通过后才写 `output_key`。 | 写 schema；重试用完时决定怎样告诉用户。 |
| `SequentialAgent` 按顺序运行，escalate 就停。 | 质量门：检查产物是否属于这次输入（文件、修订、类别）。 |
| `DecisionAgent` 把决定、理由、置信度写进状态。 | 定置信度门槛，并用真实样本检验。 |

<!-- adk-refs:start -->

## 在 ADK-Rust 源码里

本章的三种路由、schema 约束与链的停止，在 ADK-Rust 里分布在这几处：

| 本章内容 | 源码位置 | 对照要点 |
| --- | --- | --- |
| 模型给标签的路由 | [`adk-agent/src/workflow/llm_conditional_agent.rs` 第 356 行](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-agent/src/workflow/llm_conditional_agent.rs#L356) | 单独调用一次模型分类，计入运行预算；只看这一轮用户输入，不带历史 |
| 标签怎样匹配分支 | [`adk-agent/src/workflow/llm_conditional_agent.rs` · `resolve_route`](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-agent/src/workflow/llm_conditional_agent.rs#L229-L244) | 先找完全相同的标签，找不到就按标签长度从长到短看回复里包含哪一个 |
| 没有分支可去 | [`adk-agent/src/workflow/llm_conditional_agent.rs` 第 440 行](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-agent/src/workflow/llm_conditional_agent.rs#L440) | 没匹配到又没设默认分支时，只产出一条说明文字，不报错 |
| 代码判断的路由 | [`adk-agent/src/workflow/conditional_agent.rs` · `ConditionalAgent`](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-agent/src/workflow/conditional_agent.rs#L58-L71) | 同步的判断函数决定走 if 分支还是 else 分支，不调用模型 |
| 类型化决定 | [`adk-agent/src/workflow/decision_agent.rs` 第 353 行](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-agent/src/workflow/decision_agent.rs#L353) | 模型只能在列出的选项里选，并给理由和置信度；低于门槛走兜底，决定写进 `output_key` |
| 决定的请求与校验 | [`adk-core/src/decision.rs` · `Decider::decide_among`](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-core/src/decision.rs#L287-L333) | 请求带 JSON schema，选项以外的回答是错误，不会猜一个 |
| output_schema 校验与重试 | [`adk-agent/src/llm_agent.rs` 第 5364 行](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-agent/src/llm_agent.rs#L5364) | 不合格就追加纠正提示重写，`output_max_retries` 次后以错误结束 |
| 通过后才写 output_key | [`adk-agent/src/llm_agent.rs` 第 5375 行](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-agent/src/llm_agent.rs#L5375) | 校验通过的回复才写进状态；纠正提示只加在这次运行的请求里，不写进会话 |

源码固定在 ADK-Rust `98515241133d`（3.0.0，2026-11-26，尚未发布到 crates.io）。本节由 `scripts/learn-agent-rust-adk-refs.py` 生成。

<!-- adk-refs:end -->

::: warning 常见误区
- **以为模型路由会严格匹配标签。** `LlmConditionalAgent` 找不到完全相同的标签时，会看回复里包含哪个标签。
- **以为通过了 schema 就能用。** 格式对的产物也可能属于上一版；版本要另外检查。
- **以为没有分支可去时会报错。** `LlmConditionalAgent` 既没匹配到、又没设默认分支时，只产出一条说明文字，运行照常结束。
- **把置信度当概率。** 它是模型自报的数字，门槛要用真实样本定。
:::

<!-- transfer-thinking:start -->

## 迁移思考：中间成功也需要版本

抽取正确但属于上一版文件，能继续生成报告吗？先给出你的判断，再展开下面的推演。

<details><summary>推演与应用</summary>

不能。先核对来源修订，再让下游消费；字段正确和证据当前有效是两个条件。

订单核验中的旧库存、旧价格也需要同样的版本门。

</details>

这是一道迁移练习，推演不代表新增实验已通过。对照[全书审查中的证据层次](./course-review.md#evidence-layers)，说明你的判断还需要哪一级证据。

<!-- transfer-thinking:end -->

## 本章结论

提示链把一个任务拆成几步，每一步的产物都要先检查再交给下一步：`output_schema` 管格式，质量门管版本，escalate 让链在出问题的地方停下。路由决定走哪条链：代码判断最可预测，模型给标签最灵活但要提防包含匹配，类型化决定把选项和置信度摆到明处。无论哪种，都要有兜底分支和下游的检查。

## 检查理解

1. `substring-trap` 的回复不是任何一个标签，为什么还是进了 README 处理链？

   <details><summary>参考答案</summary>

   `LlmConditionalAgent` 找不到完全相同的标签时，会按标签长度从长到短，看回复里包含哪一个。“不是 readme，是 license”包含 `readme`，于是被路由到 README 处理链。

   </details>

2. `missing-field` 和 `schema-retry` 都有两次 `extract`，为什么结果不同？

   <details><summary>参考答案</summary>

   两次都是“第一次不合格、带纠正提示重写一次”。`schema-retry` 第二次补上了字段，通过校验；`missing-field` 的 README 里根本没有目标版本，重写后仍不合格，重试用完，运行以错误结束。

   </details>

3. `stale` 的产物符合 schema，也写进了状态，为什么没有写报告？

   <details><summary>参考答案</summary>

   质量门比对了修订号：产物写着 r1，这次输入是 r2。它 escalate，`SequentialAgent` 停下，写报告的一步没有运行。schema 只管格式，管不了版本。

   </details>

4. `rule-router` 为什么少一次模型调用？它的代价是什么？

   <details><summary>参考答案</summary>

   路由由代码按文件名判断，不调用模型。代价是只能处理代码里写到的情况，新类型的文件要改代码。

   </details>

5. `low-confidence` 的模型选了 readme，为什么没有进 README 处理链？

   <details><summary>参考答案</summary>

   `DecisionAgent` 设了 0.6 的置信度门槛，模型自报 0.3，低于门槛，按设定走兜底分支；决定、理由和“没有采纳”都记进了状态。

   </details>

## 参考资料

- [Building effective agents](https://www.anthropic.com/research/building-effective-agents)：提示链与路由两种工作流的说明。
- [ADK-Rust 固定源码](https://github.com/zavora-ai/adk-rust/tree/98515241133d24f7e41f8fd272649035416a142f)：三种路由 Agent 与 `output_schema` 校验的实现。

下一章：[第 18 章 · 并行分解与结果归并](./parallel-decomposition.md)。回到[本部分导读](./agent-design-patterns.md)比较模式。
