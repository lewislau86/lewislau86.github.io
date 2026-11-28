---
title: "第 23 章：模式组合与选型实战"
description: "用 ADK-Rust 3.0 把并行检查、归并、修复循环和需批准的发布串成一条流程，找出组合后才出现的接缝问题并用接缝合同修好；再把同一流程换成 OpenAI 兼容服务，以及用公开诊断集比较九种结构。"
pageClass: learn-agent-rust-course
prev:
  text: 第 22 章 · 人工介入与审批恢复
  link: /learn-agent-rust/human-in-the-loop
next:
  text: 第 24 章 · 错误分类与恢复
  link: /learn-agent-rust/error-recovery
---

# 第 23 章：模式组合与选型实战

[课程总览](./index.md) · [上一章](./human-in-the-loop.md) · [本部分导读](./agent-design-patterns.md) · [学习路径](./learning-path.md#d08) · [下一章](./error-recovery.md)

::: tip 本章学习目标
- 从任务出发选出必要的模式，用 workflow agents 把它们串成一条流程，而不是把所有模式都堆上去。
- 找出组合以后才出现的接缝问题：每个模式单独都对，放在一起却出错；用接缝合同修好它。
- 用一个预算管住整条流程；把替身换成 OpenAI 兼容服务时，流程一行不改。

**前置：** [第 18 章：并行分解与结果归并](./parallel-decomposition.md)、[第 21 章：评估、反思与有界修复](./evaluator-reflection.md)、[第 22 章：人工介入与审批恢复](./human-in-the-loop.md)。

**实践方式：** 下载<a href="/learn-agent-rust/pattern-composition.zip" download>完整 pattern-composition.zip</a>，按[第 1 节](#hands-on)取一次 ADK-Rust 源码后运行；无需模型密钥。
:::

::: info 本章已迁移到 ADK-Rust 3.0
旧版在一张 graph-flow 图里手写路由、规划、并发、归并、修复和批准，可从 git 标签 `learn-agent-rust-v1` 取得。新版用 `SequentialAgent` 组合 `ParallelAgent`、`CustomAgent`、`LoopAgent` 和需批准的发布者，并新增 `live` 子命令，经 adk-model 的 `OpenAIClient::compatible` 接真实服务。模式对照驱动器 `model_compare.py` 保持不变。[对应表](#old-scenarios)列出了场景的变化。
:::

前面七章各讲一个模式，每章的实验都只验证那一个模式。真实任务往往要几个一起用：升级发布要先并行检查依赖和文档，核对结果，写说明、按反馈修，最后经人批准再发布。

先问每一步为什么需要：两项检查互不依赖，所以并行（第 18 章）；检查结果可能过期或缺项，所以要归并核对；说明要有来源，所以要评估和修复（第 21 章）；发布有后果，所以要人批准（第 22 章）。路由、动态重规划、交接这次用不上，就不加。

组合以后要验收的，是模式之间的接缝：一个模式交出的东西，下一个模式接不接得住；一个模式内部的信号，会不会漏到外面。

<LearnAgentRustMap active="pattern-composition" />

<!-- experiment-library:start -->

全书实验可从[统一代码库](./experiments.md#pattern-composition)下载；解压后进入 `chapters/pattern-composition/`，或在代码库根目录运行 `python3 run.py run D08`。

<!-- experiment-library:end -->

::: info 本章实验状态
workflow agents、审批记录、`RunBudget` 和 `OpenAIClient::compatible` 都是 ADK-Rust 的真实实现；发布写的是临时目录里的真实文件。默认模型是按规则回复的替身，审批人的决定由程序给出。`live` 子命令的验证用的是本地 fixture 服务，按同样的规则回答；真实服务没有运行，没有模型质量结论。
:::

## 1. 先运行：七个场景 {#hands-on}

下载并解压工程，先取一次 ADK-Rust 源码再运行：

```sh
cd pattern-composition
python3 fetch-adk-rust.py ../adk-rust    # 需要 git 与 GitHub 访问；不行时加 --method cdn
cargo run --locked
```

编译时会看到 adk-core 的 3 条弃用警告（上游固定 Rust 1.95.0，本课程用 1.99.1），不影响运行和检查。

<<< @/public/learn-agent-rust/outputs/d08-summary.txt

`model_calls` 是模型调用总数（第一次运行和批准后的恢复合计），`checkers`、`writer`、`publisher` 是其中各角色的调用数；`steps` 是运行步骤（`run:held` 表示第一次运行结束时发布在等批准，之后 `approve`、`resume`）；`published` 是最后有没有发布；`stop` 是流程怎样结束：`completed` 是正常走完，`escalated_by:evaluator` 是评估者的上报让流程结束，`merge:…`、`refine:…` 是这两步上报的原因，`error:…` 是运行出错的错误码。

## 2. 组合起来的流程

<<< @/public/learn-agent-rust/code/pattern-composition/src/main.rs#pipeline

四步各来自一章：

<<< @/public/learn-agent-rust/code/pattern-composition/src/main.rs#stages

- **checks**：两个检查者同时运行，各写自己的状态键。
- **merge**：两项发现都在、成员对得上、修订都是 r2，才把证据写进状态 `evidence`；否则上报，整个流程停下。`stale-branch` 里依赖检查交回了旧修订 r1，流程停在这里，写作者一次都没运行；`branch-failed` 里依赖检查出错，`ParallelAgent` 把错误交给外层，运行以错误结束。
- **refine**：写作者读证据写稿，评估者检查来源，通过就上报，最多 3 轮。
- **publisher**：调用 `publish_report`，策略要求人批准；挂起、批准、恢复的做法和第 22 章一样。

## 3. 接缝：内层的“收工”让外层也收工

<<< @/public/learn-agent-rust/outputs/d08-naive.txt

`naive` 把第 21 章的修复循环原样放进流程。循环本身完全正确：第一稿缺来源，第二稿补上，评估者通过、上报收工。但发布者一次都没有运行（`publisher=0`），运行也没有报错，只是在评估者之后结束了。

原因是 escalate 不只对内层有效。`LoopAgent` 把子 Agent 的事件原样交给外层，`SequentialAgent` 本身就是只跑一轮的 `LoopAgent`，它在事件里看到同一个 escalate，于是在当前子 Agent（整个修复循环）之后结束。内层用来表示“通过”的信号，在外层的意思变成了“停下”。每个模式单独测都对，组合起来，接缝错了。

修法是给接缝写一个合同：修复循环对外只交出“有合格的稿子”或“没有”。

<<< @/public/learn-agent-rust/code/pattern-composition/src/main.rs#boundary

适配器把内层的 escalate 全部清掉，自己记下评估者有没有通过。它只认名为 `evaluator` 的 Agent 的上报；内层出错时错误照常交给外层，不再补结论。通过了，外层继续走到发布者；`never-accepted` 那样 3 轮都没有合格稿，适配器就自己上报一次（`refine:no_accepted_draft`），外层在发布前停下。`normal` 加了适配器，走完了全程：

<<< @/public/learn-agent-rust/outputs/d08-normal.txt

## 4. 一个预算管住整条流程

一次运行用一个 `RunBudget`，检查者、写作者、发布者的模型调用都从同一个计数器扣。`budget` 只给 4 次：两个检查者、两稿写作正好用完，修复循环也通过了，但发布者的第 5 次调用在开始前被拒，运行以 `budget.model_calls` 结束，没有发布。轨迹里那条停止说明署名是评估者：框架把它记在最后一个发出事件的 Agent 名下，发布者还没来得及发出任何事件就被拒了。

<<< @/public/learn-agent-rust/outputs/d08-budget.txt

修复循环自己有 3 轮的上限，那只管它自己；一次运行的预算管所有子结构加起来。局部的上限不能代替全局的预算。

要注意，预算按运行计。`budget-resume` 给 5 次：第一次运行用满 5 次（两个检查者、两稿写作、发布者提出发布）后挂起；批准后的恢复是一次新的运行，计数器从零开始，发布者再调用一次，照样发布，合计 6 次。每一轮“挂起—批准—恢复”都会拿到一份新预算；要限制整件事的总花费，得由应用跨运行记账，或者共用同一个 `budget_tracker`。

## 5. 换成真实服务：`live`

<<< @/public/learn-agent-rust/code/pattern-composition/src/main.rs#live

替身和真实服务都实现同一个 `Llm` 接口，`live` 子命令只是把 `RuleLlm` 换成 `OpenAIClient::compatible(密钥, 地址, 模型)`，流程、策略、审批一行不改。服务地址、模型和密钥只从环境变量读：

```sh
# 请先在本机环境配置服务地址（含 /v1）、模型和密钥；不要写入仓库。
cargo run --locked -- live
```

没有服务也能检查接线。`live_fixture.py` 在本机起一个只认非流式 `/v1/chat/completions` 的服务，按和替身相同的规则回答（发布者那一步回的是标准的 `tool_calls`），再把环境变量指向它：

```sh
python3 live_fixture.py -- cargo run --locked -- live
```

验证脚本保存的结果：

<<< @/public/learn-agent-rust/outputs/d08-live.txt

经过真实的 HTTP 客户端，同一条流程照样挂起、批准、恢复、发布，一共 6 次请求。这只说明接线正确。换成真实模型以后，检查者和写作者不一定交出合格的 JSON，那时归并、评估者和接缝适配器会让流程停在发布之前，这正是它们的用处。发布者也可能只回一句话、不调用工具，那样运行会以 `stop=completed`、`published=no` 结束；应用要把“走完了但没发布”当作失败处理，不能只看运行有没有报错。

![左边是组合起来的发布流程：并行检查、归并、带接缝适配的修复循环、需批准的发布，整次运行共用一个预算；右边是各场景停在哪里，不加适配时评估者的上报让整个流程在发布前结束。](/learn-agent-rust/figures/d08-pattern-flow.svg)

左边是流程，右边是主要场景的实际结束原因（`budget-resume` 和 `normal` 一样走完全程）。

### 全部场景的实际结果

<!-- d08-results:start -->

| 场景 | 模型调用 | 检查者 | 写作者 | 发布者 | 步骤 | 发布 | 结束原因 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `naive` | `4` | `2` | `2` | `0` | `[run]` | `no` | `escalated_by:evaluator` |
| `normal` | `6` | `2` | `2` | `2` | `[run:held,approve,resume]` | `yes` | `completed` |
| `stale-branch` | `2` | `2` | `0` | `0` | `[run]` | `no` | `merge:stale_result:deps@r1` |
| `branch-failed` | `2` | `2` | `0` | `0` | `[run]` | `no` | `error:model.unavailable` |
| `never-accepted` | `5` | `2` | `3` | `0` | `[run]` | `no` | `refine:no_accepted_draft` |
| `budget` | `4` | `2` | `2` | `0` | `[run]` | `no` | `error:budget.model_calls` |
| `budget-resume` | `6` | `2` | `2` | `2` | `[run:held,approve,resume]` | `yes` | `completed` |

<!-- d08-results:end -->

### 与旧版场景的对应 {#old-scenarios}

| 旧版（graph-flow 夹具） | 新版（ADK-Rust） | 变化 |
| --- | --- | --- |
| `normal`、`discover` | `normal` | 流程由 workflow agents 组合；动态发现成员见第 19 章，这里不再组合。 |
| `branch_failed` | `branch-failed` | `ParallelAgent` 把分支错误交给外层。 |
| `stale_branch`、`missing_branch` | `stale-branch` | 归并核对成员与修订；缺项走 `missing:` 分支，本章没有单独场景。 |
| `stale_approval`、`denied` | （见第 22 章） | 批准的绑定与撤回在第 22 章演示。 |
| `no_progress` | `never-accepted` | 修复循环没有合格稿，接缝适配器上报。 |
| `budget` | `budget`、`budget-resume` | 每次运行一个 `RunBudget`；恢复运行重新计数。 |
| （无） | `naive` | 组合后才出现的接缝问题。 |
| 9 个场景、4 项测试 | 7 个场景、4 项测试，另有 `live` 与模式对照自检 | — |

验证脚本把工程打包后在临时目录解压，在旁边放好 ADK-Rust 源码，运行格式、Clippy、4 项 Rust 测试和离线构建；摘要和 6 条详细轨迹各连跑两次必须逐字节相同；再用本地 fixture 跑一遍 `live`，并运行 `model_compare.py self-test`。维护者在网站仓库根目录执行：

```sh
python3 scripts/fetch-adk-rust.py .cache/adk-rust    # 只需一次；或设 ADK_RUST_SRC
python3 scripts/verify-agent-patterns-adk.py --lesson D08
python3 scripts/generate-learn-agent-rust-figures.py --lesson D08
python3 scripts/verify-agent-patterns-adk.py --lesson D08 --check
```

## 6. 模式对照：同一题，九种结构 {#model-comparison}

独立工程带有 `model_compare.py` 和公开的 `model-cases.json`，只用 Python 标准库。先运行本地 HTTP 自检：

```sh
python3 model_compare.py self-test ./fixture-run
```

它启动真实 loopback HTTP 服务，用固定响应跑 9 种结构、每种 4 道题，共 36 项任务。全通过只表示驱动器正常，fixture 的 token 是合成数据，不能当模型用量或费用。

你可以在本机设置 `OPENAI_BASE_URL`（例如服务地址加 `/v1`）、`OPENAI_MODEL` 和服务需要的 `OPENAI_API_KEY`，然后运行：

```sh
# 请先在本机环境配置服务地址、模型和密钥；不要写入仓库。
python3 model_compare.py live ./live-run --repeats 3
# 也可先比较最小基线与组合：
python3 model_compare.py live ./live-pair --repeats 3 --variants single composed
```

HTTP 适配器发送标准非流式 chat/completions 请求，显式设置 temperature=0、max_tokens=512；服务若不支持这些字段，会记录失败而不是自动改变配方。允许 HTTPS 或本机 HTTP，禁止重定向和系统代理。模型凭据不写入结果。

<<< @/public/learn-agent-rust/code/pattern-composition/model_compare.py#http

九种变体有真实不同的控制路径：single 一次生成，chain 先抽取再生成，routing 先选 README，parallel 限并发抽取，replan 观察清单后修订读取计划，workers 由模型提出白名单任务，repair 在公开结构与来源检查失败时有限修复，human 为候选绑定脚本批准，composed 组合动态分派、并行、修复与批准。这里的 `composed` 是对照驱动器里另写的 Python 组合，不是第 2–4 节的 Rust 流程（Rust 流程没有动态分派）。

<<< @/public/learn-agent-rust/code/pattern-composition/model_compare.py#patterns

**比较口径。** 同一四题公开合成诊断集，覆盖单项目、workspace、含恶意指令资料和缺失文件；每种变体重复 3 次，固定顺序随机化种子 1729。重复是推理试验，不是训练种子；temperature=0 也不保证服务完全确定。每个任务最多 8 次 HTTP 请求，派发最多并发 2 个，每次最多生成 512 token，无自动重试。全九种共计划 108 项任务、上限 864 次请求；single/composed 共 24 项任务、上限 192 次请求。各结构实际调用数不同，需与成功率一起报告。 这是方案级比较：组合同时改变分解、筛选、并行与反馈，结果差异不能单独归因给其中一个模式；需要归因时，再逐个关闭组件做同输入消融。

评分器对照独立标签检查每个 member 的精确启动命令、null 缺失值和来源列表。标签不进入模型请求；修复反馈只检查公开的结构、成员和来源，不把正确命令直接告诉模型。批准为脚本输入，不测人工决策质量；没有执行真实发布操作。

`attempts.json` 保存每个尝试、答案、失败、调用数、服务原始 usage 和耗时；`report.json` 保存任务、策略、驱动器哈希、请求与响应模型、每次重复成功率及平均和范围。失败留在计划分母内；认证或限流时提前停止并记录 attempted/planned。缺 usage 保持 null，费用未知，不填零。请求耗时和任务耗时分别记录；p95 在小样本中不稳定。

**当前状态：真实服务未运行。** 本节提供可复现的评估入口，不预填质量提升数字。这个对照驱动器是独立的 Python 程序，和第 5 节的 `live` 子命令是两个入口：`live` 检查 ADK-Rust 流程换成真实服务后能不能跑通，对照驱动器比较不同结构的答题质量。四题都是公开诊断样例，不构成独立泛化测试、供应商排名或生产质量保证。

## 框架替你做了什么、没做什么

| 框架做了 | 仍归应用 |
| --- | --- |
| workflow agents 按顺序、并行、循环运行子 Agent；escalate 让所在的工作流停下。 | 选哪些模式；给子结构之间的接缝写合同（交出什么、什么信号不能外漏）。 |
| `RunBudget` 让一次运行的所有模型调用共用一个计数器。 | 定预算；分清局部上限和全局预算；跨运行（挂起后恢复）的总花费自己记账。 |
| 挂起、批准、恢复；`OpenAIClient::compatible` 接 OpenAI 兼容服务。 | 验收真实服务的输出；分别报告流程正确和模型质量。 |

<!-- adk-refs:start -->

## 在 ADK-Rust 源码里

本章的组合、接缝与真实服务接线，在 ADK-Rust 里分布在这几处：

| 本章内容 | 源码位置 | 对照要点 |
| --- | --- | --- |
| 顺序流程就是只跑一轮的循环 | [`adk-agent/src/workflow/sequential_agent.rs` 第 18 行](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-agent/src/workflow/sequential_agent.rs#L18) | 所以它对 escalate 的处理和 `LoopAgent` 一样：看到就在当前子 Agent 之后结束 |
| escalate 一路向外传 | [`adk-agent/src/workflow/loop_agent.rs` 第 681 行](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-agent/src/workflow/loop_agent.rs#L681) | 子 Agent 的事件原样交给外层；内层循环“通过收工”的 escalate，外层同样看得见、同样会停 |
| 整次运行一个预算 | [`adk-core/src/context.rs` 第 1779 行](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-core/src/context.rs#L1779) | 每次运行开始时按 `RunBudget` 建一个计数器，所有子 Agent 的模型调用都从这里扣；恢复运行重新计数 |
| OpenAI 兼容服务 | [`adk-model/src/openai/client.rs` 第 146 行](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-model/src/openai/client.rs#L146) | `OpenAIClient::compatible(密钥, 地址, 模型)`，实现同一个 `Llm` 接口，换掉替身不用改流程 |
| 请求走 Chat Completions | [`adk-model/src/openai/client.rs` 第 15 行](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-model/src/openai/client.rs#L15) | 发往 `/chat/completions`；本章的本地 fixture 只实现了非流式的这一个端点 |

源码固定在 ADK-Rust `98515241133d`（3.0.0，2026-11-26，尚未发布到 crates.io）。本节由 `scripts/learn-agent-rust-adk-refs.py` 生成。

<!-- adk-refs:end -->

::: warning 常见误区
- **每个模式单独测过，组合就没问题。** `naive` 里每个模式都对，接缝错了。
- **用内部控制信号表示“完成”。** escalate 会一路传到外层；对外要交出明确的结果。
- **子结构有自己的上限就够了。** 还需要一个全局预算；而且它按运行计，恢复会重新计数。
- **`live` 跑通了就说明模型好用。** fixture 只验证接线；真实模型的质量要另做对照。
- **把所有模式都堆上去。** 先问每一步为什么需要，用不上的模式不加。
:::

<!-- transfer-thinking:start -->

## 迁移思考：组合验证接缝

修复循环单独测试时“通过就上报收工”完全正确，放进发布流程以后，为什么发布者一次都没有运行？先给出你的判断，再展开下面的推演。

<details><summary>推演与应用</summary>

escalate 不只结束内层的 LoopAgent，它随事件一路传到外层的 SequentialAgent，外层也就此结束。每个模式单独都对，组合起来的接缝却错了。接缝要写成合同：子结构对外交出“有合格结果 / 没有”，而不是把内部的控制信号原样漏出去。

跨服务的业务流程也一样：一个服务内部的“完成”信号不能直接当作整个流程的结束条件，接缝处要有明确的结果类型。

</details>

这是一道迁移练习，推演不代表新增实验已通过。对照[全书审查中的证据层次](./course-review.md#evidence-layers)，说明你的判断还需要哪一级证据。

<!-- transfer-thinking:end -->

## 本章结论

组合从任务出发：每加一个模式，都要说得出它解决什么问题。组合以后，验收的重点是接缝：`naive` 说明内层的控制信号会漏到外层，让流程在没人注意时提前结束；接缝适配器把它改成明确的结果。一次运行一个预算管住所有子结构（恢复会重新计数）；替身换成真实服务时流程不变，但流程正确和模型质量要分开验证、分开报告。

## 检查理解

1. `naive` 的修复循环明明通过了，为什么没有发布？

   <details><summary>参考答案</summary>

   评估者用 escalate 表示通过。这个事件也被外层的 `SequentialAgent` 看到，它在修复循环之后结束，发布者没有运行。

   </details>

2. 接缝适配器做了什么？

   <details><summary>参考答案</summary>

   清掉内层所有的 escalate，让外层继续；记下评估者有没有通过，没有合格稿时自己上报一次，让外层在发布前停下。

   </details>

3. `budget` 里修复循环已经通过了，为什么没有发布？

   <details><summary>参考答案</summary>

   这次运行的 `RunBudget` 只有 4 次模型调用，两个检查者和两稿写作用完了，发布者的调用在开始前被拒。修复循环的 3 轮上限和整次运行的预算各管各的。

   </details>

4. `live` 用 fixture 跑通说明什么？

   <details><summary>参考答案</summary>

   说明同一条流程经过真实的 OpenAI 兼容客户端和 HTTP 请求也能挂起、批准、恢复、发布。回答由 fixture 按规则给出，不代表真实模型的效果。

   </details>

5. 真实服务配置后，怎样解释模式对照的成功率？

   <details><summary>参考答案</summary>

   在公开四题诊断集、固定的每任务请求上限下报告各变体每次重复和平均范围，失败保留分母；不能据此推断泛化或模型排名。

   </details>

## 参考资料

- [Building effective agents](https://www.anthropic.com/research/building-effective-agents)：工作流与 Agent 模式的工程导读，强调从最简单的方案开始、按需组合。
- [ADK-Rust 固定源码](https://github.com/zavora-ai/adk-rust/tree/98515241133d24f7e41f8fd272649035416a142f)：workflow agents、`RunBudget` 与 OpenAI 兼容客户端的实现。

下一章：[第 24 章 · 错误分类与恢复](./error-recovery.md)。回到[本部分导读](./agent-design-patterns.md)比较模式。
