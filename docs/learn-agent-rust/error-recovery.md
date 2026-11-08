---
title: "第 15 章：错误分类与恢复"
description: "沿一次读取失败，建立类型化错误、有限退避和累计预算，再检查暂停续跑与写入结果不明的边界。"
pageClass: learn-agent-rust-course
prev:
  text: 第 14 章 · 系统提示词组装
  link: /learn-agent-rust/system-prompts
next:
  text: 第 16 章 · 持久化任务系统
  link: /learn-agent-rust/task-system
---

# 第 15 章：错误分类与恢复

[课程总览](./index.md) · [上一章：系统提示词组装](./system-prompts.md) · [下一章：持久化任务系统](./task-system.md)

::: tip 本章学习目标
- 按错误类型和操作语义选择重试、反馈或停止。
- 用次数、累计调用、等待额度和截止时间约束重试，并读懂退避轨迹。
- 验证暂停续跑保留预算；写入结果不明时保留事实并停止重放。

**前置：** [第 2 章](./tools-and-graph.md)的工具调用、调用 ID 与状态；Rust 的枚举、`Result`、模式匹配和所有权。另可对照[第 12 章：上下文压缩](./context-compaction.md)阅读模型历史与运行时控制状态的分工；本章独立实验可直接运行。

**实践方式：** 下载[本章学习包](/learn-agent-rust/error-recovery-lab.zip)，用 Rust 1.85 或更新版本编译。只依赖标准库，无需模型密钥、数据库或其他章节源码。
:::

工作区助手正在读取 `README.md`，准备告诉用户如何启动项目。第一次读取失败了。再读一次，也许就能成功。

于是我们很容易写出一个想法：“出错就重新执行。”但接下来有三个问题：文件根本不存在时，重复读有什么用？已经失败三次，是否还该继续？如果工具正在追加日志，文件写好了，返回结果却丢失了，再执行会不会多写一行？

本章沿这个任务建立恢复控制：先判断失败意味着什么，再判断是否允许下一次尝试。**恢复是带状态和额度的决策过程。**

先预测：第一次尝试在虚拟时间 `0 ms` 开始，每次尝试记作 `10 ms`，两次失败后分别等待 `100 ms`、`200 ms`。第三次尝试什么时候开始？先记下答案，运行后再核对。

<LearnAgentRustMap active="error-recovery" />

<!-- experiment-library:start -->

全书实验可从[统一代码库](./experiments.md#error-recovery)下载；解压后进入 `chapters/error-recovery/`，或在代码库根目录运行 `python3 run.py run R11`。

<!-- experiment-library:end -->

## 1. 把一次调用与多次尝试分开

用户提出“读取项目说明”，模型给出一个工具请求，应用为它保留 `call_id=read-1`。读取临时失败后，运行时可以在内部尝试多次。这个过程中，逻辑请求仍是同一个；变化的是 `attempt`。

| 身份或记录 | 代表什么 | 恢复时如何处理 |
| --- | --- | --- |
| `call_id` | 一次逻辑工具调用 | 内部重试沿用原 ID，参数保持不变。 |
| `attempt` | 对该调用的第几次实际派发 | 每次派发递增，首次也算一次。 |
| 任务账本 | 整个任务已用的调用与等待额度 | 多个调用与恢复入口共用。 |
| 终态结果 | 交回上层的这次调用结果 | 内部重试结束后只生成一次。 |

这样，模型不会因为一次读取内部失败两次，就收到三条互相矛盾的工具结果。实验的 `trace` 是运行时诊断日志，`result` 才表示逻辑调用结束。本章验证结果计数和 ID；接入第 2 章消息与图节点时，再把终态转换成配对的工具消息。

![恢复分支先检查输入与权限，再将临时只读失败、永久错误和写入结果不明分别送往重试、停止与核对。](/learn-agent-rust/figures/r11-recovery-routes.svg)

从上往下读：只有“错误值得再试”和“操作允许安全再做”同时成立，才进入退避。右侧的写入结果不明直接要求核对，左侧重试仍要经过次数和预算检查。

::: info 源码与实验范围
全文 Rust 片段直接导入同一份源码：<a href="/learn-agent-rust/code/error-recovery.rs" download>下载 error-recovery.rs</a> · [GitHub 源码](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/learn-agent-rust/code/error-recovery.rs) · [完整学习包](/learn-agent-rust/error-recovery-lab.zip)。

工具请求与故障序列由程序固定提供；成功读取、缺文件错误和日志追加是真实文件操作。尝试耗时、退避和 `Retry-After` 数值使用注入的虚拟时间，程序不会实际 `sleep`。暂停续跑发生在同一进程内，本章没有接入真实模型或 `graph-flow`。
:::

## 2. 先跑一次：失败两次，第三次成功

解压学习包，进入其中的 `error-recovery-lab` 目录。以下是运行命令，教程实现见导入的完整源码：

```sh
rustc --edition=2024 -D warnings error-recovery.rs -o recovery
./recovery backoff
```

Windows 使用相应的 `recovery.exe`。实际输出：

<<< @/public/learn-agent-rust/outputs/r11-backoff.txt

三个开始时间是 `0`、`110`、`320 ms`。第三次开始前，前两次尝试占 `20 ms`，两段退避占 `300 ms`；第三次完成后，虚拟时钟来到 `330 ms`。

![backoff 场景的三次尝试分别在虚拟时间 0、110、320 毫秒开始，两次等待累计三百毫秒。](/learn-agent-rust/figures/r11-backoff-timeline.svg)

从左往右读，每个框是一次派发，框间的标注是等待时间。底部账本把尝试数、累计等待和当前时间放在一起。这张图来自实验记录，时间是用于验证控制流的设定值。

注意输出中的 `last_failure`：成功后仍保留最近一次失败，便于诊断；最终结论读取 `stop=completed`。最后一行还记录 `reads=1`，因为前两次在故障注入层返回错误，只有第三次真正读取文件。

## 3. 用类型表达错误的含义

恢复代码需要分支，错误就应携带可供分支使用的信息：

<<< @/public/learn-agent-rust/code/error-recovery.rs#failure-types

`Failure` 是本章应用层的错误分类。`read_error` 将标准库的 `io::ErrorKind` 映射到这个分类，`match` 的兜底分支采取保守策略，把其余读取错误视为永久错误。`ErrorKind` 的定义与含义见 [Rust 标准库文档](https://doc.rust-lang.org/std/io/enum.ErrorKind.html)。

| 分类 | 在当前请求下意味着什么 | 本章处理 |
| --- | --- | --- |
| `Transient` | 可能随时间消失的失败，可带建议等待值 | 只读操作进入有限重试。 |
| `InvalidInput` | 请求路径或数据不符合约定 | 结束调用，由上层修正。 |
| `PermissionDenied` | 当前动作不允许执行 | 结束调用，返回拒绝原因。 |
| `Permanent` | 相同请求继续等待也没有已知改善途径 | 结束调用。 |
| `OutcomeUnknown` | 操作可能已经产生效果，结果无法确认 | 返回 `NeedsReconciliation`，等待核对。 |

“永久”是针对当前请求与本章策略说的。例如 `README.md` 不存在，本章立即反馈。若另一个任务明确负责生成它，可以设计有期限的轮询；那需要增加“等待哪个条件”的业务契约。

`InvalidInput` 之后，模型也许会提出修正后的新请求。新参数应有新的逻辑调用身份，并重新检查权限，仍使用任务总账。它和内部重试原请求是两种动作。

同样，`Transient` 只说明失败类别。本实验还要求操作为 `Read`；追加文件即使拿到一个临时错误标签，也进入核对分支。是否安全重试，必须结合操作语义判断。

生产适配器还应保留原始错误链、来源和请求标识供诊断；这里用小枚举突出控制流。不要靠模型生成的文字或错误字符串里是否含有 “timeout” 来授权重试。

## 4. 让每一次重试都经过同一本账

实验有两组约束：

| 所属范围 | 默认设置 | 计数口径 |
| --- | --- | --- |
| 单个逻辑调用 | `max_attempts=3` | 包含第一次，最多再试两次。 |
| 整个任务 | `calls=6` | 每次实际派发都消耗一次，失败也收费。 |
| 整个任务 | `wait_ms=600` | 累计由恢复驱动器执行的退避等待。 |
| 整个任务 | `deadline_ms=2000` | 相对任务起点的虚拟截止时间，限制下一次尝试准入。 |

`attempts` 限制“同一个请求试几次”；`calls` 限制“整个任务派发几次”。分开后，模型换一个 `call_id`、上层再次进入驱动器，都无法获得新的任务额度。

### 先收费，再派发

账本的两个入口如下：

<<< @/public/learn-agent-rust/code/error-recovery.rs#ledger

`admit` 先检查截止时间与累计调用额度，再增加计数。执行失败后，已经使用的调用次数照样保留。这里每次派发额外推进 `10 ms`，便于检查时间关系。

`wait_until` 接收绝对到期点。若预计等完已经到达截止时间，直接停止；若剩余等待超过可用额度，也停止。它通过检查后才一次性记账，因此不会先花掉一部分等待额度再发现不够。

`wait_ms` 的口径是驱动器实际推进的退避时间。调度器已经耗去的暂停时间体现在 `now_ms` 与截止时间中，恢复只补等剩余部分。

这里的 `calls` 统计工具尝试次数。真实模型接入需要另外记录模型请求数、实际 token 用量和费用；扩大输出上限、生成摘要或切换模型时，这些账也要持续累计。

### 截止时间与单次超时分别负责什么

本实验的截止时间负责回答：“现在还能开始下一次尝试吗？”同步文件调用发出后，它不会被这个虚拟时钟中断。

真实服务还需要在客户端设置连接、读取和请求超时，并让单次超时受任务剩余时间限制。等待期间也要支持取消。这部分依赖具体客户端；本章只验证准入逻辑。超时配置的范围和重试层次可参考 [AWS 的超时与重试说明](https://aws.amazon.com/builders-library/timeouts-retries-and-backoff-with-jitter/)。

## 5. 退避：给恢复留时间，也给任务留终点

第 `k` 次失败后的基础等待为：

$$
b_k = \min\left(b_0 \cdot 2^{k-1}, b_{\mathrm{cap}}\right)
$$

本章 `k` 从 `1` 开始，`b_0=100 ms`，`b_cap=400 ms`。因为最多尝试三次，普通运行只会用到前两次等待；测试另外检查封顶和很大次数下的整数溢出处理。

<<< @/public/learn-agent-rust/code/error-recovery.rs#policy

本章把服务端建议等待解释为一个最小值：`delay=max(backoff, retry_after)`。建议值大于退避上限时仍然保留它，随后由任务截止时间和等待预算决定是否还能等。它不是让程序忽略总预算的通行证。

例如：

- `retry-after` 注入 `250 ms` 建议值，实际等待 `250 ms` 后读取成功。
- `retry-after-too-long` 注入 `2000 ms`，下一次尝试会越过任务截止时间，因此只尝试一次后停止。

源码接收的是已解析的毫秒数。HTTP 适配器还需要按 [RFC 9110 的 `Retry-After` 定义](https://www.rfc-editor.org/rfc/rfc9110.html#section-10.2.3)解析秒数或日期形式，检查无效值，再转换成内部时间表示；本实验没有解析 HTTP 响应头。

在多个客户端同时重试时，可以引入随机抖动分散到达时间，参见 [AWS 关于退避与抖动的说明](https://aws.amazon.com/blogs/architecture/exponential-backoff-and-jitter/)。本实验关闭抖动，以便逐行复现时间轨迹。接入随机等待后，要对最终采样出的等待值继续执行同样的预算检查，并遵守服务端等待下界。

### 重试分支放在哪里

驱动器先检查取消、参数和授权，再核对次数与任务总账，通过后处理尚未完成的等待，最后申请下一次派发：

<<< @/public/learn-agent-rust/code/error-recovery.rs#admission

这里的授权来自固定可信测试入口。`revoked-backoff` 会在暂停后撤销它，验证恢复后先检查权限、再等待和执行。完整的审批身份与参数绑定见[第 3 章](./permissions.md)。

工具返回错误后，按类型选择恢复路径：

<<< @/public/learn-agent-rust/code/error-recovery.rs#retry

最后一次允许的尝试失败后，直接报告 `AttemptLimit`；任务调用额度已用完时，直接报告 `CallBudget`。两种情况下都不再安排一次无用的等待。

接入已有 SDK 时，先核对它自己的重试设置。若 SDK 内部试三次，外层再试三次，实际调用量可能叠乘。应明确哪一层负责重试，并让底层实际尝试进入同一预算口径。

## 6. 暂停之后，哪些东西必须带回来

一次失败后，程序安排 `due_ms=110`，然后把控制权还给调度器。接下来重新进入恢复入口时，需要哪些状态？

<<< @/public/learn-agent-rust/code/error-recovery.rs#state

`Recovery` 保存逻辑调用、已用次数、尚未到期的等待、最近失败、终态与结果。`Ledger` 则由整个任务持有。两者的生命周期覆盖重试过程。

`finish` 只在第一次进入终态时生成结果，之后重复进入驱动器会直接返回。这个约束让内部重试日志与最终工具结果保持清楚的关系。

实验用所有权转移模拟同一进程内把调用交还调度器，再继续执行：

<<< @/public/learn-agent-rust/code/error-recovery.rs#resume

这里移动原来的 `state`，继续借用原来的 `ledger`；调用本身、次数、到期点和已用额度都保留下来。输出：

<<< @/public/learn-agent-rust/outputs/r11-resume-budget.txt

暂停时已用一次调用。恢复后第二次仍失败，任务额度恰好用完，于是 `stop=call_budget`。重新进入函数并没有给它第三次机会。

还有三个值得核对的场景：

| 场景 | 暂停期间发生什么 | 结果 |
| --- | --- | --- |
| `resume-cooldown` | 立即恢复，等待尚未完成 | 等到原有到期点，再尝试成功。 |
| `resume-expired` | 注入时钟推进，已经超过截止时间 | 保持一次尝试，直接停止。 |
| `shared-budget` | 第一个调用用三次尝试成功，第二个调用接着进入 | 第二个调用尝试数为零，任务总调用数仍为三。 |

测试还会把虚拟时钟先推进一部分，确认恢复只补等剩余时间；另让第二个调用在暂停期间用完共享额度，确认第一个调用恢复后直接停止，累计等待仍为零。

错误恢复状态和累计额度属于运行时控制状态。第 12 章处理模型可见的历史；裁剪历史或生成摘要时，应继续保留这里的账本。跨进程恢复需要把状态、时间语义和保存边界持久化，见[第 16 章](./task-system.md)与[检查点专题](./postgres-checkpoints.md)。

## 7. 最容易误判的失败：写好了，却没收到成功

现在将工具换成“往 `events.log` 追加一条启动记录”。`append-unknown` 先真实写入，再注入 `LoseReply`，模拟返回成功前结果丢失：

<<< @/public/learn-agent-rust/code/error-recovery.rs#tool

追加工具发生 I/O 错误时，本章保守地返回 `OutcomeUnknown`，因为执行途中可能已经写入部分内容。没有额外的业务核对能力时，恢复器应保留不确定性。

实际输出：

<<< @/public/learn-agent-rust/outputs/r11-append-unknown.txt

`appends=1` 且 `lines=1`，而停止原因是 `needs_reconciliation`。两者同时成立：文件确实改变了，调用方却没有可以确认成功的正常结果。

为了直接看文件，可以让实验保留一个新建工作区：

```sh
./recovery append-unknown ./inspect-unknown
cat ./inspect-unknown/events.log
```

目录必须尚不存在；程序会保留它供检查。预期文件内容：

```text
startup=cargo run
```

这行来自真实追加。验证器会独立读取保留目录，核对字节和行数，同时确认输入文件未被改动。现有目录会被拒绝，验证器也检查其中的哨兵文件保持完整。

下一步应根据业务操作身份查询结果或对账。若外部接口提供幂等键，需要确认重复请求怎样识别、参数是否绑定同一操作、服务端记录能保留多久。本实验只到“停止自动重放并要求核对”，具体实现放在[外部操作可靠性专题](./side-effect-reliability.md)。`call_id` 本身不会自动赋予外部服务幂等性。

## 8. 把规则带回模型调用边界

前面的 Rust 实验选择文件工具，是为了能独立核对最终效果。同一套“分类、状态、额度”的思路也适用于模型请求，但模型错误还涉及输出完整性和上下文改变。

[参考课程的 s11](https://learn.shareai.run/zh/s11/)围绕输出截断、上下文超限和临时 API 故障展开。本章保留这个问题划分；下表是接入模型时的设计接口，**尚未在本实验中实现或验证**。

| 触发 | 恢复动作 | 必须保留的状态与停止条件 |
| --- | --- | --- |
| 输出截断 | 在提供方支持范围内调整输出上限，或将任务拆小后有界续写 | 已升级标志、续写次数、总请求与用量；达到上限则返回不完整状态。 |
| 上下文超限 | 交给上下文模块执行一次明确的压缩，再重新组装请求 | 压缩已用标志、保留事实与工具配对；再次超限则停止或交回上层。 |
| 限流、过载或可恢复连接故障 | 适配器生成类型化临时错误，有限退避 | provider、请求身份、尝试数、建议等待、总额度；错误码按提供方契约解释。 |
| 认证、参数或协议错误 | 反馈配置或协议问题 | 保存来源和原始诊断；同一请求直接结束。 |
| 允许使用的备用模型可用 | 经应用策略检查后重新组装兼容请求 | 当前模型、切换次数、能力与费用；切换继续使用任务总账。 |

截断需要特别谨慎：一段不完整的工具参数还没有成为合法动作，应完成结构化解析与校验后再决定是否执行。已经成功执行过的工具也要保留调用与结果记录，避免模型重试或切换时重放。

压缩、续写与模型切换都可能改变下一次请求。应分别记录“发生了哪种恢复”和“为它花了多少请求与 token”，并限制恢复动作自身的次数。每次 `continue` 都重新建立全部计数，会让外层循环变成无限续跑。

模型的协议成功，也只说明这次返回符合接口。业务任务是否完成还需核对目标；`Completed` 在本实验里表示工具调用成功，不能直接当作整个 Agent 的任务验收。

<details><summary>对照参考课程原图</summary>

![上游示意图将输出截断、上下文超限和临时服务故障分别送往升级、压缩与退避。](/learn-agent-rust/figures/upstream/r11-error-recovery-overview.svg)

按三条恢复路径阅读。该图原样保留自参考课程，图中的 Python/Claude 接口与参数属于原图语境；本章 Rust 实验及其范围见前文。原图参数不作为跨提供方的通用默认值。

图源：[参考章节](https://learn.shareai.run/zh/s11/) · [原图](https://learn.shareai.run/course-assets/s11_error_recovery/error-recovery-overview.svg)。版本与许可见[参考资料说明](./architecture.md#reference-assets)。

</details>

## 9. 核对全部实验与验收范围

![实际运行结果显示重试会受次数、累计额度、截止时间与取消限制，写入结果不明时只追加一次。](/learn-agent-rust/figures/r11-recovery-results.svg)

先看 `resume-budget` 与 `call-budget`：恢复入口变化了，停止额度相同。再看 `shared-budget`：新增逻辑调用仍然使用旧账。最后看 `append-unknown`：停止原因和文件结果分开记录。

以下表格逐项对应实验输出。`调用` 为整个任务的实际派发次数，`等待` 为虚拟退避累计毫秒，`日志行` 由验证器读取文件核对；完整输出随学习包提供。

<!-- r11-results:start -->
| 场景 | 停止原因 | 调用 | 等待 ms | 日志行 |
| --- | --- | --- | --- | --- |
| `normal` | `completed` | 1 | 0 | 0 |
| `transient` | `completed` | 2 | 100 | 0 |
| `backoff` | `completed` | 3 | 300 | 0 |
| `attempt-limit` | `attempt_limit` | 3 | 300 | 0 |
| `call-budget` | `call_budget` | 2 | 100 | 0 |
| `wait-budget` | `wait_budget` | 2 | 100 | 0 |
| `deadline` | `deadline` | 1 | 0 | 0 |
| `retry-after` | `completed` | 2 | 250 | 0 |
| `retry-after-too-long` | `deadline` | 1 | 0 | 0 |
| `permission-denied` | `failed` | 0 | 0 | 0 |
| `invalid-input` | `failed` | 0 | 0 | 0 |
| `missing-file` | `failed` | 1 | 0 | 0 |
| `permanent` | `failed` | 1 | 0 | 0 |
| `append-ok` | `completed` | 1 | 0 | 1 |
| `append-unknown` | `needs_reconciliation` | 1 | 0 | 1 |
| `resume-budget` | `call_budget` | 2 | 100 | 0 |
| `resume-cooldown` | `completed` | 2 | 100 | 0 |
| `resume-expired` | `deadline` | 1 | 0 | 0 |
| `cancelled-backoff` | `cancelled` | 1 | 0 | 0 |
| `revoked-backoff` | `failed` | 1 | 0 | 0 |
| `shared-budget` | `call_budget` | 3 | 300 | 0 |
<!-- r11-results:end -->

本地验证使用 macOS arm64、Rust 1.99.1，并用 Rust 1.85.0 重新编译与核对。`--check` 会重跑 21 个场景和 13 个 Rust 测试，独立读取实际文件，检查记录、源码校验值和输出是否过期，再解压网站提供的 zip，编译后重跑全部场景。

在解压的学习包中运行 Rust 测试：

```sh
rustc --edition=2024 -D warnings --test error-recovery.rs -o recovery-tests
./recovery-tests
```

在网站仓库中刷新或核对产物：

```sh
python3 scripts/verify-agent-recovery.py
python3 scripts/verify-agent-recovery.py --check
python3 scripts/generate-learn-agent-rust-figures.py --lesson R11
```

测试重点包括退避封顶与溢出、次数口径、失败计费、等待额度、截止时间相等、永久错误、恢复到期点、取消和撤权、结果不明的追加、新调用共享总账，以及暂停期间共享额度耗尽后的立即停止。源码、输出和证据打包在[学习包](/learn-agent-rust/error-recovery-lab.zip)中。

::: warning 常见误区
- 将“临时失败”直接等同于“可以重做”。同时检查副作用、参数身份与业务幂等条件。
- 在恢复函数里重建计数器。单调用状态和任务账本都要覆盖整个恢复过程。
- 让 `Retry-After` 绕过总预算，或在额度用完后仍睡眠一次。先核对是否还有下一次派发机会。
- 把诊断日志当作多条最终工具消息。内部尝试应汇总成一次逻辑调用结果。
- 将虚拟时钟当实测延迟，将进程内续跑当作重启恢复。这里的文件效果真实；故障、时间和暂停由程序控制。
- 用这份实验推断真实模型压缩、切换、网络超时或数据库恢复已经通过。它们需要各自的适配与验证。
:::

<!-- transfer-thinking:start -->

## 迁移思考：未知结果需要对账

写操作返回超时，能否按网络错误直接重试？先给出你的判断，再展开下面的推演。

<details><summary>推演与应用</summary>

先问请求是否到达与效果是否已发生；有幂等身份则按合同重放，否则进入查询或人工确认。

把“失败”和“结果未知”分开，恢复策略才不会制造第二笔业务。

</details>

这是一道迁移练习，推演不代表新增实验已通过。对照[全书审查中的证据层次](./course-review.md#evidence-layers)，说明你的判断还需要哪一级证据。

<!-- transfer-thinking:end -->

## 本章结论

一次可控的恢复需要三份信息：这次失败的类型、这个操作能否安全再做、任务还剩多少额度。

本章用 `Recovery` 保留调用与尝试状态，用 `Ledger` 累计整个任务的消耗。临时只读失败经过有限退避；输入、权限与永久错误交回上层；写入结果不明时保留文件事实，停止自动重放。暂停、换调用 ID 和再次进入函数，都不会重新获得预算。

## 检查理解

### 1. `max_attempts=3`，意味着最多重试几次？

<details><summary>参考答案</summary>

最多重试两次。第一次执行已经计入 `attempts`；三次派发都失败后返回 `AttemptLimit`，不再安排下一段等待。

</details>

### 2. 第一次失败后暂停，恢复时重新建立 `Ledger` 会怎样？

<details><summary>参考答案</summary>

已经消耗的调用和等待额度会被遗忘，截止时间也可能被重新开始。反复恢复就能越过任务上限。应移动或保留原 `Recovery`，并复用任务级账本。

</details>

### 3. `Retry-After` 建议等待两秒，而任务还剩不到两秒，应该怎样处理？

<details><summary>参考答案</summary>

停止这次恢复并报告截止时间限制。服务端建议表达可再次尝试的时间下界；应用仍需遵守自己的时间与资源额度。缩短到低于建议值后提前重试，也不符合本章契约。

</details>

### 4. `append-unknown` 为什么不是简单的“工具失败，没有写入”？

<details><summary>参考答案</summary>

实验先真实追加一行，再模拟丢失回复，所以调用方无法确认成功时，文件已经发生变化。应该返回结果不明、保留操作身份，并核对实际结果。直接重做可能多写一行。

</details>

### 5. 压缩模型历史以后，能否同时清空重试次数与累计用量？

<details><summary>参考答案</summary>

不能。模型可见上下文和运行时控制状态有不同用途。摘要可以改变历史的表达方式；恢复次数、调用身份、工具执行记录和预算应继续由运行时维护。否则压缩本身会成为绕过限制的入口。

</details>

## 参考资料

- [Rust：`std::io::ErrorKind`](https://doc.rust-lang.org/std/io/enum.ErrorKind.html)与 [`Result`](https://doc.rust-lang.org/std/result/enum.Result.html)：本章错误分类与返回值的基础。
- [AWS：Timeouts, retries, and backoff with jitter](https://aws.amazon.com/builders-library/timeouts-retries-and-backoff-with-jitter/)：超时范围、重试层次与副作用条件。
- [AWS：Making retries safe with idempotent APIs](https://aws.amazon.com/builders-library/making-retries-safe-with-idempotent-APIs/)：带业务身份的幂等请求。
- [参考课程 s11](https://learn.shareai.run/zh/s11/)：模型调用边界的三类恢复问题；其参数与实现语境和本章实验分别说明。

下一章是[第 16 章：持久化任务系统](./task-system.md)。它把任务身份、依赖和状态保存下来，通过独立进程验证任务板恢复；完整运行账本与检查点仍需单独设计。
