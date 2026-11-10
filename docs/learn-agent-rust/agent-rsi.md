---
title: "专题 6：Agent RSI 与受控自我改进"
description: "从开发集过拟合到候选晋升、发布与回滚，区分任务策略搜索与递归元改进。"
next: false
pageClass: learn-agent-rust-course
prev:
  text: 专题 5 · 固定工作流与目标控制
  link: /learn-agent-rust/workflow-and-goal-control
---

# 专题 6：Agent RSI 与受控自我改进

[课程总览](./index.md) · [上一专题：固定工作流与目标控制](./workflow-and-goal-control.md) · [技术跟踪](./technology-radar.md)

::: tip 本章学习目标
- 区分反馈修复、持久化策略改进与 Recursive Self-Improvement（RSI，递归自我改进）。
- 用独立数据分区与固定门控，识别开发集过拟合、越权和无效候选。
- 运行 Rust 有界策略搜索，检查预算、版本父子关系、发布指针与回滚。

**前置：** [R18 工作区隔离](./worktree-isolation.md)、[P03 独立评估](./model-evaluation.md)、[P04 准入与恢复](./production-readiness.md)、[P05 目标控制](./workflow-and-goal-control.md)。

**实践方式：** [下载完整 Rust 学习包](/learn-agent-rust/agent-rsi-lab.zip)，Rust 1.99.1，标准库，无需密钥或数据库。研究资料核对到 **2026-11-08**。
:::

一个库存助手在四道练习题上全部答对。它把新策略存下来，说：“我已经学会处理库存了。”换成带空格、非法字段或整数溢出的新输入，结果却错了。

如果助手还能修改自己的测试，让所有答案都被判为正确，分数会更漂亮。我们真正想改善的是完成任务的能力；分数只是观察这种能力的一个窗口。本章从这个矛盾出发，追问：谁提出改进、谁检查改进、谁允许它成为下次运行的默认版本？

<LearnAgentRustMap active="agent-rsi" />

<!-- experiment-library:start -->

全书实验可从[统一代码库](./experiments.md#agent-rsi)下载；解压后进入 `chapters/agent-rsi/`，或在代码库根目录运行 `python3 run.py run P06`。

<!-- experiment-library:end -->

## 1. 先分清：这次修好，还是以后更会改？

[P05](./workflow-and-goal-control.md)让一次未完成的工作在额度内继续。P06 讨论的是把新的行为版本留下来，影响以后的任务。再向上一层，RSI 还要求产生改进的方法本身也能改变。

| 层次 | 库存助手中的例子 | 需要看到的证据 |
| --- | --- | --- |
| 当前任务的反馈修复 | 补写这次报告缺失的 total | 这次产物符合合同。 |
| 持久化任务策略改进 | 以后解析字段时先 trim，并检查溢出 | 新版本在固定验收上更好，原能力没有被破坏。 |
| 元改进 | 改写选择候选、分配试验额度或诊断失败的方法 | 在等预算、多个未参与调优的改进任务上，产生有效改进的能力提高。 |
| 递归元改进 | 改进程序也能用其改进程序生成新版本，并积累经验 | 完整版本谱系、外部验收与跨轮对照；不能只看一次最终任务分数。 |

![任务策略的改进循环位于内层，元改进改变产生候选的过程，固定验收和发布边界包住两者。](/learn-agent-rust/figures/p06-improvement-levels.svg)

先看内层：候选改变的是“怎样做任务”。再看外层：候选改变的是“怎样找出更好的做法”。本章 Rust 实验只实现内层的有限候选选择与发布保护；图中外层是研究概念，并非已运行能力。

更长的回答、写下反思、增加记忆条目或重复一次循环，都可能有用，但要用对应层次的证据说明收益。它们本身不构成递归元改进。

## 2. 最近的研究把什么变成可修改对象？

[AlphaEvolve](https://deepmind.google/blog/alphaevolve-a-gemini-powered-coding-agent-for-designing-advanced-algorithms/)（2025-05-14）用模型提出算法程序，让自动评估器筛选并演化候选。启发是先寻找能够执行验证的目标；算法更好并不自动说明优化过程自身更好。

[Darwin Gödel Machine，v3](https://arxiv.org/abs/2505.22954v3)（修订于 2026-03-12）把 Agent 自身代码纳入搜索对象，并保存候选档案。论文使用编程评估经验判断收益；它没有把每个改动的收益化为数学证明。

[Hyperagents，v2](https://arxiv.org/abs/2603.19461v2)（2026-11-01）进一步把任务 Agent 与元 Agent 整合进可编辑程序，元 Agent 的修改过程也可以演化。阅读它时，除了最终任务表现，还要追问作者如何观察“产生改进的能力”及其迁移。

[Skill∞，v1](https://arxiv.org/abs/2610.35434v1)（2026-10-26）把优化任务技能的方法也表达为元技能，研究同一优化过程怎样作用于两个层次。它与 [R07 技能加载](./skill-loading.md)的联系，是被版本化的对象可以包含指令与资源；加载机制和证明改进有效仍是两件事。

以上是原论文与官方报告的机制概述。本站没有独立复现这些系统；近期预印本中的结果应按作者的任务、模型与预算解释。完整来源版本表见[技术跟踪](./technology-radar.md#rsi-research)。

## 3. 把研究问题缩成可检查的 Rust 实验

先只做一件事：对逗号分隔的 i32 数量求和。允许字段两侧空格；空字段、非法整数或中间累加溢出都返回 ERR。例如 `" 2,3 "` 应得到 `5`，`"2,,3"` 应得到 ERR。

我们预先写好四种策略，让学习重点集中在验收，而不是模型生成代码的偶然表现。

| 策略 | 做法 | 想暴露的问题 |
| --- | --- | --- |
| Baseline | 解析失败当作零，使用 wrapping_add | 安静吞掉坏数据。 |
| Trim | 加上 trim，其余同上 | 局部修复仍保留原缺陷。 |
| Memorize | 硬编码四道开发题的答案，其他返回零 | 开发集满分但没有学会规则。 |
| Robust | trim、严格解析、checked_add | 在当前合同下处理非法输入和溢出。 |

::: info 源码与复现范围
正文直接引用 <a href="/learn-agent-rust/code/agent-rsi/src/main.rs" download>src/main.rs</a>；[完整学习包](/learn-agent-rust/agent-rsi-lab.zip)含 Cargo.toml、Cargo.lock、工具链与 README，也可查看 [GitHub 源码](https://github.com/lewislau86/lewislau86.github.io/tree/master/docs/public/learn-agent-rust/code/agent-rsi)。

运行采用确定性有限策略夹具，没有 LLM、任意代码生成、权重训练或元改进。提案中的标志位用于验证拒绝路径，不具备检测恶意程序的能力。
:::

<<< @/public/learn-agent-rust/code/agent-rsi/src/main.rs#task-policy

开发集有四题，供诊断和提出候选；验证集有另外四题，供选择；最终测试集有六题，只在选择结束后审计一次。候选接口只拿到输入字符串，门控不读取最终测试分数。

**所有题目都公开在下载源码里。** 这是按调用路径隔开的模拟留出实验，不是对能读仓库的 Agent 保密的评估。验证集被重复用于挑选，实际上也是调优集；六道手选题只验证这些边界，无法证明一般化能力。真实系统需要评估服务持有独立数据、轮换题目并限制反馈泄漏。

## 4. 先预测：开发集满分的 Memorize 会晋升吗？

基线在开发集是 2/4，验证集是 1/4。Memorize 在开发集达到 4/4，但验证集仍是 1/4。若只按开发集筛选，就会把“记答案”发布出去。

本例的晋升条件是：开发集不退步，验证集严格提高，同时满足父版本、权限、评分器和额度约束。它是一个有意简化的确定性规则；真实 noisy 评估还需要重复采样、回归题与不确定性分析。

![Memorize 的开发集满分而验证集无增益；Robust 在两区都通过，说明选择不能只看开发分数。](/learn-agent-rust/figures/p06-candidate-scores.svg)

每一行来自正常场景的实际候选评估。分母相同才能横向比较；图中没有把最终测试成绩提前喂给选择器。完整输出如下：

<<< @/public/learn-agent-rust/outputs/p06-overfit.txt

候选被拒绝仍消耗一次搜索机会。否则系统可以把失败尝试宣布为“没有正式运行”，反复免费试探验证集。是否完成晋升，与是否消耗资源要分开记录。

## 5. 什么必须留在候选可改范围之外？

候选提案包含策略、父修订、是否改变评分器、是否扩大权限以及固定成本。受信任的宿主先检查这些字段，再执行评估。

![提案先经过版本、评分器、权限与额度检查，才运行评估；通过后写入新版本与发布指针。](/learn-agent-rust/figures/p06-promotion-gates.svg)

按箭头读：前三种结构性拒绝发生在评分前；合法但没有提高的候选发生在评分后。一个候选不能通过修改判断自己的程序，变成“成功”的候选。

<<< @/public/learn-agent-rust/code/agent-rsi/src/main.rs#promotion-gate

`parent` 防止根据旧版本生成的提案覆盖较新的已接受改进。它在这里是单进程修订检查；真正并行的候选还需要存储事务或 CAS。`evaluator_changed` 与 `extra_permission` 是受控测试标志；实际执行生成代码时必须在另一个边界检查差异和能力，并隔离文件、进程、网络与凭据。

本例每次候选评估消耗一单位搜索额度，最多三次。`candidate_case_evaluations` 只数候选在开发与验证集的调用：每次 8 次；它不包括基线重评分、最终审计，也不是 token 或完整算力账本。真实系统应把生成、编译、评估与审查的消耗一起计量。

<<< @/public/learn-agent-rust/outputs/p06-evaluator-tamper.txt

这里调用次数为零，说明篡改评分器的提案在评估前被拒。评分器升级若确实必要，应走独立维护流程，在共同题集上校准并开启新的评估版本；不能把新旧评分器的分数直接接成一条改善曲线。

## 6. 好候选也要经过发布，坏发布还要能回退

正常场景先接受 Trim，拒绝 Memorize，再接受 Robust。最终才读取六道测试题作审计，基线为 2/6，发布版本为 6/6。它说明当前边界题通过，不说明未来任务都会通过。

<<< @/public/learn-agent-rust/outputs/p06-normal.txt

发布用 `create_new` 写出不可覆盖的修订文件，再用 rename 替换 CURRENT。运行时通过 CURRENT 重新读取策略；实验核对基线文件保留，指针解析与实际执行版本一致。

<<< @/public/learn-agent-rust/code/agent-rsi/src/main.rs#release

![改进版发布后出现注入告警，CURRENT 回到基线修订；最终审计会如实暴露回退后的能力下降。](/learn-agent-rust/figures/p06-release-rollback.svg)

看图中最后一格：回滚意味着回到已知版本，不意味着分数一定更高。基线依然只有 2/6；需要记录恢复行为与恢复后的能力，而不是只打印 rollback_success。

<<< @/public/learn-agent-rust/outputs/p06-rollback.txt

告警是受信任测试程序注入的运行告警，并非模型自动发现缺陷。rename 只用于单进程本地指针替换，本实验没有验证 fsync 断电耐久性、并发发布或真实流量切换。恢复旧代码也不会撤销已经发出的外部业务动作；这部分仍遵循 [P02](./side-effect-reliability.md) 的对账合同。

## 7. 动手：先复验，再设计下一层

解压学习包后进入 agent-rsi 目录，使用一个父目录存在、目标目录尚不存在的临时路径：

```sh
cargo test --locked --offline
cargo clippy --locked --offline -- -D warnings
cargo run --locked --offline -- normal /tmp/rsi-course-run 1
cargo run --locked --offline -- overfit /tmp/rsi-course-run 1
cargo run --locked --offline -- rollback /tmp/rsi-course-run 1
```

每轮成功运行后清理自己的实验目录；已有目录会被拒绝且保留。Windows 请将临时路径替换成本机可写位置。源码命令独立运行，不依赖网站仓库；首次使用指定工具链时需先由 rustup 安装。

| 场景 | 观察对象 | 本次实际结果 |
| --- | --- | --- |
| normal | 候选选择与最终审计 | Trim、Robust 晋升；Memorize 拒绝；发布 Robust。 |
| overfit | 开发分数与验证分数分离 | 开发 4/4 仍被拒，保留 Baseline。 |
| evaluator-tamper | 评分器边界 | 评估前拒绝，零候选评分。 |
| permission-escalation | 能力边界 | 评估前拒绝，零候选评分。 |
| budget | 额度不足 | 评估前拒绝，零候选评分。 |
| stale-parent | 父修订一致性 | Trim 晋升后，旧父修订的 Robust 被拒。 |
| rollback | 发布指针与实际执行版本 | 回到 Baseline，测试如实恢复为 2/6。 |

验证脚本 `python3 scripts/verify-agent-rsi.py --check` 重跑 4 项 Rust 测试、Clippy、七类场景，正常场景补充顺序种子 2、3，总计九次运行及两个 CLI 拒绝检查；还实际解压最终 zip，独立构建并复验整组。种子只选择奇数/偶数两种预定顺序，**三个种子不是三个独立模型样本**。改变顺序后这里最终仍选到 Robust，只是这组有限候选的观察。

### 后续研究练习：怎样知道“改进器变好了”？

保持本章受信任门控，另外实现两个候选产生器：一个按固定顺序提案，一个依据失败类型选择提案。冻结两者、给相同总额度，在没有参与改写产生器的新任务集上比较找到合格候选的比例、耗费与回归失败。再考虑让系统提出对产生器的修改。

这项练习尚未实现。仅把固定序列换成一次 LLM 调用，还没有验证元改进；只在原来四道题上继续挑选，也没有验证跨任务迁移。读 Hyperagents 或 Skill∞ 时，可以用同一问题检查作者的对照与证据。

## 迁移思考：把分数变成目标，会失去什么？

如果新策略在验收题上更好，却开始读取私人目录、延长执行时间或删除失败日志，你会接受它吗？

<details><summary>推演与应用</summary>

先把允许的资源、数据与执行行为写成约束，再在约束内比较任务质量。单个分数通常不足以表达这些要求。受信任的评分与发布程序也需要版本和审计；候选越能改自己的工具，越需要清楚说明哪些边界仍由宿主掌握。

教育、运维和交易中的自动优化同样如此：让反馈帮助改进，不让被优化对象自行改写“成功”的定义。能解释收益来自哪里，也能解释何时必须停止，是比展示一条上涨曲线更重要的能力。

</details>

::: warning 常见误区
- 本章是有界策略搜索与发布保护实验，未实现自由生成代码或递归元改进；公开小题集不构成泛化证据。
- 策略改变、技能改变与模型权重训练是不同对象；一次成功改动不能推导出无限自我提升。
- 提案标志位与 worktree 都不构成恶意代码沙箱；真实自修改需要另外设计执行隔离与凭据边界。
- 回滚指针不会撤销业务副作用；恢复旧版后仍要验收产物与能力。
:::

## 本章结论：允许改进，保留判断改进的独立性

把失败反馈变成下一次更好的行为，需要可保存的候选、可重复的验收和受控发布。RSI 再把产生改进的机制纳入演化；这扩大了搜索空间，也提高了保持评估可信的难度。

本实验把“开发满分却不晋升”和“回滚成功却能力下降”真实跑出来。学完应能指出每项观察支持什么结论，再用这个习惯阅读更大的自改进系统。

## 检查理解

1. Memorize 在开发集满分，为何不晋升？

   <details><summary>参考答案</summary>

   验证集没有比当前版本提高，违反固定门控。开发满分可以来自硬编码答案，而非规则改进。

   </details>

2. 最终测试在选择后运行一次，为什么仍不能说它是隐藏测试？

   <details><summary>参考答案</summary>

   所有数据都公开在源码里。调用路径没有直接使用测试分数，但能读仓库的提案者仍可能看到题目；真正独立评估需要额外的数据访问边界。

   </details>

3. 为什么失败的候选也扣搜索额度？

   <details><summary>参考答案</summary>

   生成与评估已经消耗资源，且反馈可以被用于下一次选择。不扣除会允许无限试探，掩盖改进的真实成本。本例只对候选评分计数，完整系统还要记录其他消耗。

   </details>

4. Robust 全通过，是否证明本实验实现了 RSI？

   <details><summary>参考答案</summary>

   没有。四种策略均预先写好，候选产生方法没有改变，更没有比较改进方法在新任务上的收益；它只验证有限策略的筛选与发布保护。

   </details>

5. 修改评分器可能是合理改进吗？为什么候选仍不能自行修改？

   <details><summary>参考答案</summary>

   评分器可能有缺陷，需要独立维护与校准。允许当前被评候选同时重写判分会破坏可比性。应固定一轮搜索的评分合同，升级时保留旧版、共同题集和外部审查。

   </details>

6. 回滚后测试由 6/6 回到 2/6，回滚是否失败？

   <details><summary>参考答案</summary>

   指针回到指定版本说明回退动作成功，2/6 说明该版本的任务能力有限。两个事实同时成立；后续是否继续服务应由预先约定的准入与业务风险条件决定。

   </details>

## 参考资料

- [AlphaEvolve 官方介绍](https://deepmind.google/blog/alphaevolve-a-gemini-powered-coding-agent-for-designing-advanced-algorithms/)，2025-05-14。
- [Darwin Gödel Machine v3](https://arxiv.org/abs/2505.22954v3)，2026-03-12。
- [Hyperagents v2](https://arxiv.org/abs/2603.19461v2)，2026-11-01。
- [Skill∞ v1](https://arxiv.org/abs/2610.35434v1)，2026-10-26，近期预印本。
- [Agent Skills 规范](https://agentskills.io/specification)；[Agent 评估实践](https://www.anthropic.com/research/demystifying-evals-for-ai-agents)。

继续阅读[技术跟踪与迁移边界](./technology-radar.md)，或回到[学习路径](./learning-path.md#p06)，选一项尚未验证的能力设计你的下一次实验。
