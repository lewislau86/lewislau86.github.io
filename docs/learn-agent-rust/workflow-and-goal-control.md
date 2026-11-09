---
title: "专题 5：固定工作流与目标控制"
description: "固定业务编排与自主循环怎样结合，目标何时算完成？"
pageClass: learn-agent-rust-course
---

# 专题 5：固定工作流与目标控制

[课程总览](./index.md) · [学习路径](./learning-path.md) · [课程架构](./architecture.md)

::: tip 本章学习目标
- 划清固定业务步骤与内部执行循环的责任，给目标写出可检查的完成条件。
- 分别记录正常返回、产物达标和运行终态，以真实文件决定能否完成。
- 给继续执行设置累计预算与停滞上限，留下可检查的人工交接记录。

**前置：** [第 15 章：错误分类与恢复](./error-recovery.md)、[第 24 章：完整 Agent 集成](./integrated-agent.md)、[专题 3：模型协议与质量评估](./model-evaluation.md)。本章直接解释所需的验收与预算概念，实验工程独立运行。

**实践方式：** [下载 Rust 学习包](/learn-agent-rust/workflow-and-goal-control-lab.zip)。需要 Rust / Cargo 和 Python 3.9+；实验无需模型密钥或数据库服务。
:::

让一个执行者读取库存文件，生成核对表。它返回“已经完成”，程序也没有抛异常。打开目录，却只有苹果和梨的数量，没有总计。

这次运行结束了，用户的目标还没有完成。直接结束会交付残缺结果；把“继续直到完成”写进无限循环，又可能让执行者反复生成同一份表。

本章把这两件事接起来：业务流程固定准备、验收和交接步骤，把有边界的动作选择留在内部循环；每次回来，都用实际产物决定完成、补做还是转人工。

<LearnAgentRustMap active="workflow-and-goal-control" />

<!-- experiment-library:start -->

全书实验可从[统一代码库](./experiments.md#workflow-and-goal-control)下载；解压后进入 `chapters/workflow-and-goal-control/`，或在代码库根目录运行 `python3 run.py run P05`。

<!-- experiment-library:end -->

## 1. 先给“库存核对完成”写一份合同

输入文件 source.txt 有两行：苹果 7 件、梨 11 件。我们希望 report.txt 包含 apples、pears、total 三个唯一字段，分别与输入数量及其总和相等。

完成条件在执行前确定，执行者不能通过修改自己的答案来重写条件。准备步骤读取输入，冻结本次期望值；验收时还检查原输入没有变化。这个合同只回答数量核对问题，不评判自然语言报告的表达质量。

| 观察到的情况 | 产物判断 | 流程选择 |
| --- | --- | --- |
| 三个字段正确且源文件未变 | satisfied | 内部轮次正常返回后，可以完成。 |
| 缺文件、缺字段、数量错误或格式非法 | repairable | 检查预算和进度，决定是否补做。 |
| 输入缺失、输入非法或执行期间变化 | blocked | 交给人补输入或确认目标。 |

这里的 repairable 只表示合同尚可尝试满足，不保证执行者下一次能修好。输入发生变化时，本例选择交接，由人决定采用哪个版本。

::: info 源码与实验范围
本章片段直接引用 <a href="/learn-agent-rust/code/workflow-and-goal-control/src/controller.rs" download>controller.rs</a>、<a href="/learn-agent-rust/code/workflow-and-goal-control/src/goal.rs" download>goal.rs</a> 和 <a href="/learn-agent-rust/code/workflow-and-goal-control/src/fixture.rs" download>fixture.rs</a>。完整工程、锁定依赖、验证器和逐场景输出在[学习包](/learn-agent-rust/workflow-and-goal-control-lab.zip)中，也可查看 [GitHub 源码](https://github.com/lewislau86/lewislau86.github.io/tree/master/docs/public/learn-agent-rust/code/workflow-and-goal-control)。

本次使用 Rust 1.99.1。执行者采用确定性脚本，文件读取、替换和交接记录写入真实发生。实验验证单进程控制逻辑，未接入真实模型、graph-flow、langchain-rust 或持久化恢复。
:::

<<< @/public/learn-agent-rust/code/workflow-and-goal-control/src/goal.rs#contract

数量合同最多有三个正确字段，因此可以用正确字段数记录这项任务的进度。字段顺序无关；重复字段、未知字段、负数和超大数都拒绝。单项最多 1,000,000，总计最多 2,000,000，源文件与报告各最多读取 512 字节。

## 2. 哪些步骤固定，哪些步骤交给循环？

固定流程负责目标和控制权：准备合同、预检查、启动一段执行、重新验收，然后完成、继续或交接。内部执行者只能提出读取、写报告、返回答案或请求人工处理。

![固定流程包住内部动作循环，独立验收后才选择完成、继续或交接。](/learn-agent-rust/figures/p05-workflow-boundary.svg)

沿主线看：Final 只把控制权交还外层，不能跳过验收直接通往完成。继续箭头回到同一份控制状态，沿用已经消耗的预算。

<<< @/public/learn-agent-rust/code/workflow-and-goal-control/src/fixture.rs#proposals

本例内部每次调用脚本模型只得到一个类型化提案。ReadSource 读取固定输入，Write 必须指向 report.txt，Final 表示本段正常返回。只有两个本地工具；任务文字没有被当作 shell 命令执行。

<<< @/public/learn-agent-rust/code/workflow-and-goal-control/src/controller.rs#episode

一次从启动到 Final 的内部运行称为一个 **episode**。它可以包含多次提案和工具调用；外层“再给一次机会”会启动下一个 episode。模型调用次数与 episode 数分别计量，避免把一个长循环算成一次调用。

这类分工与 [Anthropic 对工作流和 Agent 的区分](https://www.anthropic.com/research/building-effective-agents)一致：固定部分用预先定义的路径推进，内部再根据当前结果选择动作。本例把 Agent 接口替换为脚本，先验证控制合同，再考虑接入真实模型。

接入[第 24 章](./integrated-agent.md)时，可把它的完整循环包装成一次 episode，把本章的 Goal 保持在驱动器外。图执行器报告 Completed 时，应用还要检查该轮停止原因和业务验收结果；本实验没有替两库增加或验证这层接线。

## 3. 正常返回以后，再读一次真实文件

先预测 false-final：执行者连续声称“目标完成，验收通过”，但没有调用写入。外层应该记录正常返回，还是记录目标完成？

<<< @/public/learn-agent-rust/outputs/p05-false-final.txt

正常返回次数是 2，goal_verified 仍为 false。报告没有落地，验收没有受到答案中的“通过”影响。两次都没有进展，最终保存交接记录。

判断器只接受准备时冻结的合同与文件系统观察，不接收执行者的自评分：

<<< @/public/learn-agent-rust/code/workflow-and-goal-control/src/goal.rs#verify

它先核对源文件，再读取 report.txt，解析唯一字段并逐项比较。只有总和正确也不够：把苹果写成 8、梨写成 10，即使 total 仍是 18，也不能通过。

![同样正常返回，缺少文件的声明无法达标；写入与输入一致的文件后才通过。](/learn-agent-rust/figures/p05-return-and-goal.svg)

看图中两项记录：normal_returns 描述执行过程，goal_verified 描述当前产物。它们回答不同的问题，应该同时保留。

### 产物正确，也可能需要人工确认

valid-then-model-error 先成功写入完整报告，随后脚本模型返回错误。验收能看到合格文件，流程仍按异常路径交接：

<<< @/public/learn-agent-rust/outputs/p05-valid-then-model-error.txt

此时 goal_verified=true、status=needs_human。本例要求“内部轮次正常返回 + 产物达标”才进入完成终态；若希望某类工具完成后就能结束，应预先把它写成另一条明确策略。

同样，CLI 退出码 0 只表示实验完成并保存了控制结果。目标未达标、成功写出交接记录时也会退出 0。调用方应读取 result.json 的 status、reason 和 verdict。

## 4. 怎样继续一次，而不是无限重来？

continue-success 第一段读取源文件，写出苹果和梨，漏掉总计。验收产生 missing:total；下一段脚本收到这项反馈，使用已读到的数量补齐报告：

<<< @/public/learn-agent-rust/outputs/p05-continue-success.txt

第一次 score=2，第二次 score=3。两段合计 5 次脚本调用、3 次工具尝试；第二段没有重新读取输入，沿用同一运行中的观察。wrong-total 用相同路径先写错总计，收到 wrong:total 后纠正。

本例脚本明确检查反馈内容后才修复，所以验证器同时核对了“第一次反馈是什么”和“第二次文件是什么”。它证明反馈传递与控制路由正确，不证明真实模型有相同修复率。

外层的继续策略如下：

<<< @/public/learn-agent-rust/code/workflow-and-goal-control/src/controller.rs#control

控制顺序是：执行后始终验收；内部异常先交接；正常返回且达标才完成；输入冲突则交接；其余情况检查进度和轮数，再把具体反馈送回去。已存在合格文件时，预检查可以直接完成，already-satisfied 场景不消耗模型或工具额度。

### 重写文件不一定有进展

no-progress 连续三段都写入同样的两个正确字段。正确字段数始终为 2：第一次从 0 提升到 2，随后连续两次没有超过历史最好值，触发 no_progress。

![连续执行沿用同一账本，正确字段数停在二时，连续两次无提升就转人工。](/learn-agent-rust/figures/p05-bounded-continuation.svg)

按时间看三次验收，而不是文件写入次数。修改时间变新、答案变长或重新写同一份内容，都不会提高这里的进度。进度指标应按具体业务设计；这套“三个字段”的指标不适用于所有开放式任务。

## 5. 预算在调用前扣，继续时不清零

如果给每个 episode 重新分配 12 次模型调用，“最多继续四段”就可能把原预算放大。本例只在 run 开始时创建一份 Usage，内部调用、工具执行和外层续跑共用它。

<<< @/public/learn-agent-rust/code/workflow-and-goal-control/src/controller.rs#budget

预留恰好等于上限时允许，超过上限前拒绝，整数溢出也拒绝。exact-budget 将上限设成刚好完成所需的 1 段、3 次脚本调用、2 次工具尝试及报告字节数，验证等号边界。

| 额度 | 默认上限 | 计数时机与口径 |
| --- | --- | --- |
| episodes | 4 | 启动内部一段运行前预留；即使首个调用无额度，本段仍计入已启动数。 |
| model_calls | 12 | 获取提案前预留；正常答案、错误与主动交接都计数。 |
| tools | 8 | 进入工具执行前预留；策略拒绝与写入失败也计入尝试。 |
| write_bytes | 256 | 路径允许后、真正写入前预留；写入失败不返还。 |
| stagnant | 2 | 连续多少段没有超过历史最佳正确字段数。 |

这些是实验中的逻辑额度。准备、验收和交接所需的文件读取写入另有开销，不计入内部工具额度；模型调用数不等于 token、费用或运行时长。

model-budget 用完第一段的 3 次调用后，第二段在调用前停止。tool-budget 和 byte-budget 则在第二段写入前停止，保留第一段的部分文件。验证器会检查累计计数、原文件内容和没有额外动作。

![成功修复累计五次调用，而调用额度三次的场景在下一段行动前停止；交接保留原合同与原账本。](/learn-agent-rust/figures/p05-shared-budget.svg)

对照左右两列：区别在预设的调用额度，第二段不会重新获得一份额度。下方的交接内容让人知道已经做过什么、为什么停下。

工具执行边界也集中在程序里：

<<< @/public/learn-agent-rust/code/workflow-and-goal-control/src/controller.rs#execute

先检查工具额度，再检查固定路径和字节额度。写入先用临时文件，再替换 report.txt；失败会清理临时文件，累计预留仍保留。临时文件替换解决本例的半份写入问题，跨进程恢复与断电耐久性仍需[专题 1](./postgres-checkpoints.md)的检查点方案。

## 6. 什么时候停下来交接？

只有可以继续补做且仍有额度时，控制器才进入下一段。其他情况留下明确的原因：

| 条件 | 本例的停止原因 | 交接者需要判断什么？ |
| --- | --- | --- |
| 输入缺失或非法 | input_blocked | 补齐或修正源数据。 |
| 执行期间源数据改变 | goal_blocked | 采用哪份输入、是否重新验收。 |
| 重复部分结果、轮数或额度用完 | no_progress / episode_limit / 各类 budget | 保留当前结果，审核是否值得追加尝试。 |
| 执行者主动请求人工 | explicit_handoff | 补充信息或处理超出授权的步骤。 |
| 取消、路径拒绝、工具或模型错误 | 对应明确原因 | 先查已有产物与动作，再决定是否重做。 |

cancelled-after-read 在第一次读取后注入取消标记，下一次脚本调用前停止，写入次数为 0。这里验证的是协作检查点，不会强行中断已经开始的 I/O。

denied-path 请求写 ../escape.txt，实际写入被拒绝，工作区外没有新文件。每次 CLI 运行都要求全新的专用目录，验证器还检查已有目录会被拒绝且原文件不变。这是固定工具与可信工作区实验，文件访问的并发对抗边界见[第 3 章](./permissions.md)。

<<< @/public/learn-agent-rust/code/workflow-and-goal-control/src/controller.rs#handoff

handoff.json 保存目标说明、冻结的输入与期望值、停止原因、累计用量、额度和最近验收结果。输入变化时，人仍能对照原合同。它是可检查的交接记录，不自动发送通知。本章没有实现“恢复命令”，交接也不会自动重置预算或授予执行权限。

如果要接回长期服务，先从[第 15 章](./error-recovery.md)确认错误分类，再用[专题 1](./postgres-checkpoints.md)保存合同、源版本、历史最好进度和累计账本。已有外部业务动作还需[专题 2](./side-effect-reliability.md)的身份与对账；只保存继续次数不能解决重放。

## 7. 动手实验与验证记录

解压学习包，进入 workflow-and-goal-control-lab。为每次运行指定一个尚不存在的目录：

```sh
cargo test --locked
cargo run --locked -- continue-success /tmp/p05-continue-demo
cargo run --locked -- false-final /tmp/p05-false-demo
cargo run --locked -- valid-then-model-error /tmp/p05-error-demo
cargo build --locked
python3 lab.py --binary target/debug/learn-agent-p05 --output /tmp/p05-verified
```

单次运行目录会保留源文件、产物和 result.json，未完成时还有 handoff.json。若目录已经存在，请换一个新名字；程序会拒绝复用。全场景 lab.py 则自动清理自己的临时工作区，把核对后的输出保存在指定输出目录。

本轮有 22 个控制场景，另有“已有目录”和“未知场景”两项 CLI 拒绝检查，共启动 24 个独立 CLI 进程。每个控制场景的多个 episode 都在同一进程中；这不是跨进程续跑实验。

<!-- p05-results:start -->

| 场景 | 正常返回次数 | 产物达标 | 最终原因 | episode / 调用 |
| --- | --- | --- | --- | --- |
| `normal` | 1 | 是 | `goal_satisfied` | 1 / 3 |
| `false-final` | 2 | 否 | `no_progress` | 2 / 2 |
| `continue-success` | 2 | 是 | `goal_satisfied` | 2 / 5 |
| `wrong-total` | 2 | 是 | `goal_satisfied` | 2 / 5 |
| `no-progress` | 3 | 否 | `no_progress` | 3 / 7 |
| `episode-limit` | 2 | 否 | `episode_limit` | 2 / 5 |
| `model-budget` | 1 | 否 | `model_budget` | 2 / 3 |
| `tool-budget` | 1 | 否 | `tool_budget` | 2 / 4 |
| `byte-budget` | 1 | 否 | `byte_budget` | 2 / 4 |
| `cancelled-after-read` | 0 | 否 | `cancelled` | 1 / 1 |
| `explicit-handoff` | 0 | 否 | `explicit_handoff` | 1 / 2 |
| `missing-source` | 0 | 否 | `input_blocked` | 0 / 0 |
| `malformed-source` | 0 | 否 | `input_blocked` | 0 / 0 |
| `denied-path` | 0 | 否 | `policy_denied` | 1 / 2 |
| `tool-write-failed` | 0 | 否 | `tool_write_failed` | 1 / 2 |
| `model-error` | 0 | 否 | `model_error` | 1 / 2 |
| `valid-then-model-error` | 0 | 是 | `model_error` | 1 / 3 |
| `invalid-report` | 2 | 否 | `no_progress` | 2 / 5 |
| `changed-source` | 1 | 否 | `goal_blocked` | 1 / 3 |
| `already-satisfied` | 0 | 是 | `already_satisfied` | 0 / 0 |
| `missing-final` | 0 | 是 | `invalid_response` | 1 / 3 |
| `exact-budget` | 1 | 是 | `goal_satisfied` | 1 / 3 |

<!-- p05-results:end -->

上表由验证器生成。11 个 Rust 单元测试另行覆盖重复字段、错误分项但正确总计、输入上限、语义进度及额度边界。Python 验证器直接检查实际文件、反馈、事件顺序、累计计数和交接内容，再把最终下载包解压到另一目录，离线重新编译并复验所有场景。

仓库内更新与复验：

```sh
python3 scripts/verify-agent-goals.py
python3 scripts/verify-agent-goals.py --check
python3 scripts/generate-learn-agent-rust-figures.py --lesson P05
npm run docs:build
```

源码摘要、实际控制轨迹和断言后的结果保存在 scripts/data/learn-agent-rust/p05-results.json；配图读取这份记录并检查源码校验值。这里只报告控制逻辑的实验结果，真实模型完成率、token、费用与延迟应另按[专题 3](./model-evaluation.md)测量。

::: warning 常见误区
- Final、进程退出 0、图执行 Completed 都是过程信号；本章用独立验收和异常策略决定业务终态。
- 继续不会清零账本；提高额度、改变目标或重启服务都需要另行处理，不能偷偷当作同一次尝试。
- 判断器只适用于这份可精确验证的数量合同。开放问题需要可审计的标准、证据与必要的人工判断，另一个模型的“通过”也需要评估。
- 本例脚本没有真实 provider、两库接线、网络动作、持久化恢复或多执行者竞争。可信专用目录也不提供进程沙箱；取消检查不等于强制中止。
:::

<!-- transfer-thinking:start -->

## 迁移思考：继续必须消耗有限资源

把最大轮次调得无限大，就能保证最终完成吗？先给出你的判断，再展开下面的推演。

<details><summary>推演与应用</summary>

给不可完成与无进展任务设置累计预算和停滞上限；输出可接手的状态，比无限重演更有用。

把目标达标、执行状态与资源消耗分开记录，才能设计有边界的自治。

</details>

这是一道迁移练习，推演不代表新增实验已通过。对照[全书审查中的证据层次](./course-review.md#evidence-layers)，说明你的判断还需要哪一级证据。

<!-- transfer-thinking:end -->

## 本章结论：把“继续”的权力留在外层

固定工作流守住准备、验收与交接，内部执行者在授权范围内提出动作。正常返回把控制权交回外层，真实产物和运行策略共同决定能否完成。

继续应携带具体反馈、沿用累计账本，并在无进展、缺少条件或遇到异常时留下交接记录。这样一次未完成的运行仍有明确结果，接管者能据此判断下一步。

## 检查理解

1. false-final 正常返回两次，为什么没有完成？

   <details><summary>参考答案</summary>

   正常返回只说明本段执行交回了控制权。验收器读取 report.txt，发现文件没有产生，不受“验收通过”的答案影响。连续两段没有提高正确字段数，触发 no_progress 并保存交接记录。

   </details>

2. 为什么 valid-then-model-error 的 goal_verified=true，却仍然交接？

   <details><summary>参考答案</summary>

   文件满足数量合同，但内部执行以模型错误结束。本例预先规定异常路径先交接，完成终态要求正常返回与产物达标。交接记录同时保留合格产物，供人确认是否可以直接采用，而不是盲目重写。

   </details>

3. 每次继续都重置模型调用额度，会发生什么？

   <details><summary>参考答案</summary>

   外层续跑会放大原定累计预算。本例 Usage 在整个 run 中只创建一次，episode、调用、工具和字节预留共同累计。model-budget 第二段没有新调用额度，执行前就停止，已有产物保留。

   </details>

4. 三次写文件是否证明有三次进展？

   <details><summary>参考答案</summary>

   写入次数说明动作发生过，不代表离目标更近。no-progress 三次都得到两个正确字段，第一次提升以后连续两次没超过历史最好分数，因此停止。其他业务应设计自己的可观察进度指标。

   </details>

5. handoff.json 是否足以安全地自动恢复？

   <details><summary>参考答案</summary>

   本例只保存待人工处理的记录，没有自动恢复协议。恢复需要核对合同、输入版本、已有产物、异常原因和原累计预算；外部动作还要对账。本例重新启动 CLI 只接受新目录，不能当作同一运行的恢复。

   </details>

## 参考资料

- [Anthropic：Building effective agents](https://www.anthropic.com/research/building-effective-agents)：工作流、Agent 与评估反馈循环的架构区分。
- [Rust std::fs](https://doc.rust-lang.org/std/fs/)：本例真实文件读取、写入与重命名的标准库接口。
- [第 24 章：完整 Agent 集成](./integrated-agent.md)、[专题 3：模型协议与质量评估](./model-evaluation.md)：内部循环与独立评估的衔接。
- [本章学习包](/learn-agent-rust/workflow-and-goal-control-lab.zip)：可运行工程、完整验证器、实际输出和源码摘要。

完成本章后继续实践时，可回到[第 24 章](./integrated-agent.md)选择一个集成入口，再按[专题 4：生产准入与演练](./production-readiness.md)明确服务环境和所需证据。

下一专题：[Agent RSI 与受控自我改进](./agent-rsi.md)，把本次目标内的继续，扩展为对跨版本改进的独立验收。
