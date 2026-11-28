---
title: "第 18 章：并行分解与结果归并"
description: "用 ADK-Rust 3.0 的 ParallelAgent 同时运行三个互不依赖的检查者，再由归并步骤核对成员与修订；观察分支失败、上报、过期结果、缺成员与状态键冲突各自怎样收场。"
pageClass: learn-agent-rust-course
prev:
  text: 第 17 章 · 提示链与条件路由
  link: /learn-agent-rust/prompt-chaining-routing
next:
  text: 第 19 章 · 规划、执行与动态重规划
  link: /learn-agent-rust/plan-execute-replan
---

# 第 18 章：并行分解与结果归并

[课程总览](./index.md) · [上一章](./prompt-chaining-routing.md) · [本部分导读](./agent-design-patterns.md) · [学习路径](./learning-path.md#d03) · [下一章](./plan-execute-replan.md)

::: tip 本章学习目标
- 判断哪些子任务可以同时做，用 `ParallelAgent` 把它们同时运行，再用一个归并步骤汇总。
- 说清 `ParallelAgent` 遇到分支出错、分支上报（escalate）时分别怎样收场。
- 让归并核对成员身份和资料修订，而不是只数结果的个数。

**前置：** [第 17 章：提示链与条件路由](./prompt-chaining-routing.md)、[第 7 章：图并行、归并与子图](./graph-parallel-subgraphs.md)。

**实践方式：** 下载<a href="/learn-agent-rust/parallel-decomposition.zip" download>完整 parallel-decomposition.zip</a>，按[第 1 节](#hands-on)取一次 ADK-Rust 源码后运行；无需模型密钥。
:::

::: info 本章已迁移到 ADK-Rust 3.0
旧版用 Tokio 的 `JoinSet` 和信号量自己写并发与归并（同时最多两个任务），可从 git 标签 `learn-agent-rust-v1` 取得。新版用 ADK-Rust 的 `ParallelAgent` 同时运行三个 `LlmAgent`，归并是 `SequentialAgent` 里紧跟的一个 `CustomAgent`。`ParallelAgent` 没有并发上限，所以三个分支同时进行，[对应表](#old-scenarios)列出了场景的变化。
:::

升级审查要看三件事：启动文档要不要改、依赖要不要升、配置有没有改名的键。三件事互不依赖，读的是同一个修订 r2。一个接一个地检查，总时间是三者之和；同时检查，总时间接近最慢的那一个。

同时做，就要回答几个新问题：谁先做完是不确定的，报告的顺序怎么定？一个检查者出错了，其他人的结果还要吗？一个检查者发现了必须立刻停下的问题，其他人还在跑怎么办？三份结果都到了，就一定齐全、都是 r2 吗？

<LearnAgentRustMap active="parallel-decomposition" />

<!-- experiment-library:start -->

全书实验可从[统一代码库](./experiments.md#parallel-decomposition)下载；解压后进入 `chapters/parallel-decomposition/`，或在代码库根目录运行 `python3 run.py run D03`。

<!-- experiment-library:end -->

::: info 本章实验状态
`ParallelAgent`、`SequentialAgent`、`CustomAgent`、`output_key` 与 `exit_loop` 都是 ADK-Rust 的真实实现。检查者的模型是按规则回复的替身：每次请求先停 30–110 毫秒，让三个分支真正重叠，再回一个 JSON 发现。程序用暂停的 Tokio 时钟推进这些停顿，完成顺序只由停顿长短决定，在任何机器上都一样；停顿不代表真实服务的耗时，也不用来推算加速比。
:::

## 1. 先运行：七个场景 {#hands-on}

下载并解压工程，先取一次 ADK-Rust 源码再运行：

```sh
cd parallel-decomposition
python3 fetch-adk-rust.py ../adk-rust    # 需要 git 与 GitHub 访问；不行时加 --method cdn
cargo run --locked
```

编译时会看到 adk-core 的 3 条弃用警告（上游固定 Rust 1.95.0，本课程用 1.99.1），不影响运行和检查。

<<< @/public/learn-agent-rust/outputs/d03-summary.txt

`started` 是开始请求模型的检查者，`finished` 是按完成先后排列的检查者，`peak_concurrent` 是同一时刻最多有几次模型请求在进行，`outcome` 是这次的结果，`report_sha` 是报告内容的指纹。

## 2. 同时运行，按成员顺序归并

<<< @/public/learn-agent-rust/code/parallel-decomposition/src/main.rs#fanout

三个检查者各写自己的状态键：`check_config`、`check_deps`、`check_docs`。`ParallelAgent` 把它们放在同一个任务里轮流推进，三个都开始之后才有人完成，所以 `peak_concurrent=3`。它没有并发上限：子 Agent 有几个，就同时跑几个。要限制同时访问外部服务的数量，得在工具或模型客户端里自己限流。

每个分支有自己的分支标识，读历史时看不到兄弟分支刚产出的内容，只看得到分叉之前的对话。（这一点来自源码；本实验每个检查者只调用一次模型，观察不到。）

三个分支在同一个任务里轮流推进：一个分支做阻塞或很耗 CPU 的事，会卡住其他分支。这类工作要放到单独的线程里（例如 `spawn_blocking`）。

<<< @/public/learn-agent-rust/outputs/d03-normal.txt

`normal` 里 config 最快、docs 最慢；`reverse` 把停顿反过来，完成顺序变成 docs、deps、config。两次的 `report_sha` 相同：归并不看谁先到，按成员名的顺序写报告。

<<< @/public/learn-agent-rust/code/parallel-decomposition/src/main.rs#merge

## 3. 一个分支出错

`failure` 里依赖检查的模型服务没有响应：

<<< @/public/learn-agent-rust/outputs/d03-failure.txt

config 和 docs 照常做完，结果也写进了状态（`finished=[config,docs]`）。可等所有分支都结束后，`ParallelAgent` 把出错分支的错误报出来，整次运行以 `model.unavailable` 结束，归并没有运行。几个分支同时出错时，报的是排在最前面的那个子 Agent 的错误，所以结果是确定的。

“一个必要成员失败，就不出报告”是这里的选择。如果允许缺成员出报告，就要在归并里明确写出哪些成员可以缺、缺了怎么标注。

## 4. 一个分支上报，其他分支停下

`escalate` 里配置检查发现了阻断问题，调用 `exit_loop` 工具，把事件标成 escalate：

<<< @/public/learn-agent-rust/outputs/d03-escalate.txt

`ParallelAgent` 收到上报，立刻停下其他分支：deps 和 docs 还在等模型回复，就被丢下了（`finished=[config]`），外层的 `SequentialAgent` 也随之结束，归并没有运行。出错是“等大家做完再报”，上报是“现在就停”。

“丢下”的意思是那个分支停在它正在等待的地方，不再往下执行。如果它已经发出了一个外部请求，请求可能已经生效；有副作用的分支要能承受被半途丢下（[专题 2](./side-effect-reliability.md)讲外部副作用的幂等与对账）。

## 5. 归并核对的是身份和修订

三份结果都到了，不等于能出报告：

- `stale`：deps 的检查者读的是旧修订 r1。归并发现 `deps@r1`，返回 `stale_result` 并上报。
- `missing`：docs 的检查者只回了一句“应该没问题”，没给结构化发现。状态里有一个值，却不是合格的发现，归并报 `member_mismatch:missing=docs`。
- `key-collision`：三个检查者都写同一个状态键 `check`。后写的覆盖先写的，留下来的是最后完成的 docs，config 和 deps 的发现都丢了。分支并行时，每个分支要写自己的键。

<<< @/public/learn-agent-rust/outputs/d03-key-collision.txt

只数结果个数会放过这些情况。归并按成员名逐个核对：成员是谁、修订是不是这一次的。

![三个检查者由 ParallelAgent 同时运行，各写自己的状态键；分支出错时等兄弟分支做完再报错，分支上报时立刻停下其他分支；归并逐个核对成员与修订，按成员顺序写报告。](/learn-agent-rust/figures/d03-pattern-flow.svg)

上面是三个同时运行的检查者，下面是归并；两侧标出了出错和上报两种收场方式，归并框里列出了它拦下的三种情况。

### 全部场景的实际结果

<!-- d03-results:start -->

| 场景 | 完成先后 | 同时进行 | 结果 | 报告指纹 |
| --- | --- | --- | --- | --- |
| `normal` | `[config,deps,docs]` | `3` | `report` | `396f74b4` |
| `reverse` | `[docs,deps,config]` | `3` | `report` | `396f74b4` |
| `failure` | `[config,docs]` | `3` | `error:model.unavailable` | — |
| `escalate` | `[config]` | `3` | `escalated_by:config_checker` | — |
| `stale` | `[config,deps,docs]` | `3` | `stale_result:deps@r1` | — |
| `missing` | `[config,deps,docs]` | `3` | `member_mismatch:missing=docs` | — |
| `key-collision` | `[config,deps,docs]` | `3` | `member_mismatch:missing=config+deps` | — |

<!-- d03-results:end -->

### 与旧版场景的对应 {#old-scenarios}

| 旧版（Tokio JoinSet） | 新版（ADK-Rust） | 变化 |
| --- | --- | --- |
| `normal`、`reverse` | `normal`、`reverse` | 改用 `ParallelAgent`；没有并发上限，峰值从 2 变成 3。 |
| `failure` | `failure` | 出错分支等兄弟分支做完后让整次运行出错。 |
| `cancel` | `escalate` | 改为分支上报，其他分支立刻停下。 |
| `stale` | `stale` | 归并核对修订。 |
| `duplicate`、`missing` | `missing`、`key-collision` | 重复成员改为写同一个状态键的覆盖问题。 |
| `budget` | 删除 | 调用上限见第 16 章。 |
| 8 个场景、4 项测试 | 7 个场景、4 项测试 | — |

验证脚本把工程打包后在临时目录解压，在旁边放好 ADK-Rust 源码，运行格式、Clippy、4 项 Rust 测试和离线构建；摘要和几条详细轨迹各连跑两次必须逐字节相同，并把结果表写回正文。维护者在网站仓库根目录执行：

```sh
python3 scripts/fetch-adk-rust.py .cache/adk-rust    # 只需一次；或设 ADK_RUST_SRC
python3 scripts/verify-agent-patterns-adk.py --lesson D03
python3 scripts/generate-learn-agent-rust-figures.py --lesson D03
python3 scripts/verify-agent-patterns-adk.py --lesson D03 --check
```

## 框架替你做了什么、没做什么

| 框架做了 | 仍归应用 |
| --- | --- |
| 同时运行所有子 Agent（在同一个任务里轮流推进），每个分支有自己的分支标识。 | 并发上限：在工具或模型客户端里限流；阻塞工作放到单独线程。 |
| 分支出错：等其他分支结束后报出排在最前的错误。 | 决定缺了某个成员能不能出报告。 |
| 分支上报：立刻停下其他分支。 | 决定什么情况值得上报；有副作用的分支要能承受被半途丢下。 |
| 每个分支的 `output_key` 写进同一份会话状态。 | 给每个分支起不同的键；归并核对成员与修订。 |

<!-- adk-refs:start -->

## 在 ADK-Rust 源码里

本章的同时运行、出错与上报的收场，在 ADK-Rust 里分布在这几处：

| 本章内容 | 源码位置 | 对照要点 |
| --- | --- | --- |
| 同时运行的工作流 | [`adk-agent/src/workflow/parallel_agent.rs` · `ParallelAgent`](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-agent/src/workflow/parallel_agent.rs#L20-L30) | 全部子 Agent 一起运行，没有并发上限；可选的共享状态只在本次运行内有效 |
| 每个分支一个分支标识 | [`adk-agent/src/workflow/parallel_agent.rs` 第 258 行](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-agent/src/workflow/parallel_agent.rs#L258) | 按分支读历史时看不到兄弟分支的产出，只看得到分叉前的对话 |
| 分支上报，立刻停下 | [`adk-agent/src/workflow/parallel_agent.rs` 第 312 行](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-agent/src/workflow/parallel_agent.rs#L312) | 收到上报就不再推进其他分支，外层工作流随之结束 |
| 分支出错，最后报错 | [`adk-agent/src/workflow/parallel_agent.rs` 第 295 行](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-agent/src/workflow/parallel_agent.rs#L295) | 出错的分支被丢下，其他分支照常做完；最后报出排在最前的那个子 Agent 的错误 |
| 上报的工具 | [`adk-tool/src/builtin/exit_loop.rs` · `ExitLoopTool`](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-tool/src/builtin/exit_loop.rs#L8) | 把这次调用的事件标成 escalate，并跳过工具结果之后的总结 |

源码固定在 ADK-Rust `98515241133d`（3.0.0，2026-11-26，尚未发布到 crates.io）。本节由 `scripts/learn-agent-rust-adk-refs.py` 生成。

<!-- adk-refs:end -->

::: warning 常见误区
- **以为 `ParallelAgent` 会限制并发。** 它同时运行全部子 Agent。
- **以为一个分支出错，其他分支会被取消。** 出错时其他分支照常做完，只是最后整次运行出错；上报才会立刻停下其他分支。
- **用结果个数判断齐全。** 个数对，成员可能重复、缺失或属于旧修订。
- **几个分支写同一个状态键。** 后写的覆盖先写的，谁留下取决于谁最后完成。
:::

<!-- transfer-thinking:start -->

## 迁移思考：归并要验证成员身份

三个分支都完成了，状态里却只剩一个成员的结果，会发生什么？先给出你的判断，再展开下面的推演。

<details><summary>推演与应用</summary>

分支写了同一个键，后写的覆盖先写的；归并按成员逐个核对身份和修订，发现缺成员就拒绝出报告，而不是用剩下的那一份凑数。

批处理、分片搜索和多审查者报告都需要身份、版本和失败合同。

</details>

这是一道迁移练习，推演不代表新增实验已通过。对照[全书审查中的证据层次](./course-review.md#evidence-layers)，说明你的判断还需要哪一级证据。

<!-- transfer-thinking:end -->

## 本章结论

子任务互不依赖时，`ParallelAgent` 让它们同时运行，总时间接近最慢的那一个。并行带来的问题要在归并里解决：按成员顺序而不是完成顺序写报告，逐个核对成员和修订，给每个分支独立的状态键。出错和上报是两种不同的收场：出错等大家做完再报，上报立刻停下其他人。

## 检查理解

1. `normal` 和 `reverse` 的完成顺序相反，为什么报告一字不差？

   <details><summary>参考答案</summary>

   归并按成员名的顺序读各自的状态键写报告，不看谁先完成。两次的 `report_sha` 相同。

   </details>

2. `failure` 里 config 和 docs 都做完了，为什么还是没有报告？

   <details><summary>参考答案</summary>

   `ParallelAgent` 等所有分支结束后，把出错分支的错误报出来，整次运行以错误结束，后面的归并没有运行。本章的选择是必要成员失败就不出报告。

   </details>

3. `escalate` 和 `failure` 的收场有什么不同？

   <details><summary>参考答案</summary>

   出错时其他分支照常做完，最后才报错；上报时 `ParallelAgent` 立刻停下其他分支，它们的结果不会出现。

   </details>

4. `key-collision` 里三个检查者都完成了，为什么归并说缺 config 和 deps？

   <details><summary>参考答案</summary>

   三个检查者写同一个状态键，后写的覆盖先写的。最后完成的是 docs，状态里只剩它的发现。

   </details>

5. 想让三个检查者最多同时调用两次外部服务，该改哪里？

   <details><summary>参考答案</summary>

   `ParallelAgent` 没有并发上限，要在调用外部服务的地方自己限流，例如在工具或模型客户端里用信号量。

   </details>

## 参考资料

- [Building effective agents](https://www.anthropic.com/research/building-effective-agents)：并行化（分段与投票）两种用法。
- [ADK-Rust 固定源码](https://github.com/zavora-ai/adk-rust/tree/98515241133d24f7e41f8fd272649035416a142f)：`ParallelAgent` 的分支、出错与上报处理。

下一章：[第 19 章 · 规划、执行与动态重规划](./plan-execute-replan.md)。回到[本部分导读](./agent-design-patterns.md)比较模式。
