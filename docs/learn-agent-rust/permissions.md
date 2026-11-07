---
title: "第 3 章：工具权限与审批"
description: "用独立 Rust 实验区分允许、拒绝和等待审批，把批准绑定到具体动作。"
prev:
  text: 第 2 章 · 工具注册与图调度
  link: /learn-agent-rust/tools-and-graph
next: false
pageClass: learn-agent-rust-course
---

# 第 3 章：工具权限与审批

[课程总览](./index.md) · [上一章：工具注册与图调度](./tools-and-graph.md) · [下一章：生命周期与 Hooks（规划中）](./hooks.md)

::: tip 本章学习目标
- 把工具请求分成允许、拒绝和等待审批三条路径。
- 保存待审批动作，核对批准后执行的工具、参数与调用 ID。
- 用文件计数验证拒绝与等待没有写入，批准只执行指定动作一次。

**前置：** Rust 的枚举、`match`、`Option`、所有权与 `Result`；先理解[整体架构](./architecture-and-setup.md)中模型与工具的分工，以及[第 2 章](./tools-and-graph.md)的工具派发边界。本章另提供独立入口，可以单独运行实验。

**实践方式：** 下载[本章学习包](/learn-agent-rust/permissions-lab.zip)，解压后使用支持 edition 2024 的 Rust 工具链编译。只依赖标准库，无需模型密钥、数据库或其他课程工程。
:::

给工作区助手一个任务：“读取项目说明，把启动命令写进一份摘要。”

读取与写入都表现为工具调用，但它们对工作区的影响不同：读错文件可能泄露内容，写错文件可能覆盖已有工作。模型给出工具名称与参数后，应用还需要回答：**这一次具体动作，当前是否允许执行？**

本章先把问题缩小：程序自己创建一份 README 和一个空的 `notes` 目录，只允许读取这份 README；写摘要需要人工批准；其他动作直接拒绝。先猜一下：程序打印“等待审批”后，磁盘上应该已经有摘要文件了吗？

<LearnAgentRustMap active="permissions" />

## 1. 同一份请求，先走权限分支

练习工作区中的 `README.md` 只有一行：“启动命令：cargo run”。请求来源固定提出两个结构化动作：先读取 README，再把同一行写入 `notes/summary.txt`。我们用固定输入观察运行时行为，把注意力放在权限和审批上。

| 请求 | 决策 | 后续行为 |
| --- | --- | --- |
| 读取 `README.md` | `Allow` | 立即调用文件工具。 |
| 写入 `notes/summary.txt`，内容不超过 1024 字节 | `AskApproval` | 保存动作，向可信入口返回审批请求。 |
| 其他读取、其他写入、未知工具或超长内容 | `Deny` | 返回拒绝结果。 |

1024 是应用选择的字节上限，`String::len()` 按 UTF-8 字节计数；它不是性能实验得到的阈值。中文字符通常占多个字节，不能把它读成“1024 个汉字”。

![工具调用在执行前进入允许、等待审批或拒绝分支，等待分支保存请求而不写入文件。](/learn-agent-rust/figures/r03-permission-routes.svg)

沿中间分支读：`AskApproval` 的输出是待处理请求，应用此时把控制权交还给入口。沿右侧分支读：`Deny` 直接生成工具结果，向后续模型说明拒绝原因。两者的写入次数都应为零，但控制状态不同。

::: info 源码与实验范围
本文 Rust 片段直接引用同一个完整文件：<a href="/learn-agent-rust/code/permissions.rs" download>下载 permissions.rs</a>；也可在 [GitHub 查看源码](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/learn-agent-rust/code/permissions.rs)。[学习包](/learn-agent-rust/permissions-lab.zip)包含源码、运行说明、实际输出和证据文件。

本章用固定工具请求和模拟人工回复，实际调用 `std::fs` 读写临时文件。实验验证同步、单进程的权限控制流；模型 HTTP、`langchain-rust` / `graph-flow` 集成与跨进程恢复分别在后续课程验收。
:::

<<< @/public/learn-agent-rust/code/permissions.rs#calls

`Action` 把工具类型与参数放在一起：读取需要路径，写入还需要内容。`ToolCall` 再加上 `call_id`，供请求与结果配对。

`check_permission` 只分类，不做文件 I/O。它精确比较允许的文件名，所有未匹配输入都落到最后的拒绝分支。即使输入是 `notes/../README.md`，也不会因为“看起来在 notes 里”而得到许可。

如果以后允许用户选择任意子目录，就要重新设计路径解析、符号链接处理和文件访问边界。本章选择两个固定路径，先把审批控制流程讲清。

## 2. 等待审批，应该保存什么

假设用户看到的是“向摘要写入 cargo run”，点击批准后执行的内容却变成另一段文字。虽然工具名仍叫写文件，这次批准已经失去了原来的含义。因此，我们保存完整请求：

<<< @/public/learn-agent-rust/code/permissions.rs#states

这里有三种身份：

| 字段 | 用途 |
| --- | --- |
| `ApprovalId.scope` | 这份审批属于哪个运行实例的工作区？ |
| `ApprovalId.sequence` | 这个实例里是第几份审批请求？ |
| `ToolCall.call_id` | 这份结果对应哪一次工具请求？ |

`ApprovalRequest` 还保存 `Action`，所以工具类型、路径和内容都在快照里。`PartialEq` / `Eq` 让比较覆盖全部字段。

本实验用独占创建的临时工作区路径区分实例。序号和路径用于关联请求；真实服务还需要在入口验证登录身份与审批权限。**知道审批 ID，只解决“对应哪份请求”，不会自动赋予批准资格。**

`Step` 区分三个出口：

- `ToolResult`：请求已有结果，包括成功、策略拒绝、人工拒绝和工具错误。
- `AwaitingApproval`：请求尚未执行完，入口需要展示待审批内容。
- `RejectedInput`：输入违反运行时协议，例如回复了另一份审批。它是入口错误，不会为原工具调用制造新结果。

接着看接收请求的入口：

<<< @/public/learn-agent-rust/code/permissions.rs#submit

`submit` 先检查是否正在等待。教学运行时一次只处理一个待审批动作，等待期间的新请求返回 `approval_pending`，调用者应先处理已有审批。

随后检查 `call_id` 是否用过。允许、拒绝和进入等待都会登记本次 ID；相同 ID 再提交会被拒绝，避免同一调用在当前实例中重复派发。

`AskApproval` 把请求放进 `pending`，返回一份快照给入口。此时尚未调用 `execute`，也没有生成写入工具结果。入口应暂停推进模型循环，等人工处理。`Option<ApprovalRequest>` 表示“没有等待”或“有一份等待”，只保留本章需要的状态。

## 3. 批准后，执行保存的原始动作

入口展示工作区、路径和完整写入内容，拿到人工决定后调用 `resume`。本实验用 `main` 中的固定场景模拟可信入口；审批方法没有注册成模型可以调用的工具。

![待审批快照与人工回复逐字段比较，匹配后先消耗审批，再拒绝或执行原始动作。](/learn-agent-rust/figures/r03-approval-binding.svg)

先看左右两框：回复必须对应保存的快照。再看下方：人工拒绝与批准都会移走 `pending`，批准路径执行保存的调用。

<<< @/public/learn-agent-rust/code/permissions.rs#resume

三个细节值得停下来核对。

第一，回复不匹配时返回 `approval_mismatch`，原始 `pending` 继续保留。用户可以重新处理正确请求，被替换的参数不会流入工具。

第二，`take()` 在执行前发生。它取出保存的值，并把原位置变成 `None`。同一份回复第二次到达时，会得到 `no_pending_approval`。

第三，批准分支执行 `saved.call`。入口快照用于比较，执行数据仍来自运行时保存的原始请求：审批针对的是已展示的那个动作。

如果写入失败，审批也已经消耗。若决定重试，应生成新的调用与审批请求，重新判断。本章把这条规则固定下来，便于观察状态。

## 4. 授权通过，工具仍可能失败

`Allow` 与人工批准最终汇合到同一个文件执行器：

<<< @/public/learn-agent-rust/code/permissions.rs#execute

读取与写入都访问当前实例的工作区。计数紧挨真实文件调用：调用 `fs::write` 前增加 `write_attempts`，只有成功返回才增加 `write_successes`。

结果保留原 `call_id`。策略拒绝使用 `denied`，人工拒绝使用 `declined`，文件失败使用 `tool_error`。上层拿到这些状态后，才能分别解释“没有得到许可”与“得到许可但执行失败”。

为构造确定的失败，`write-error` 先在摘要路径创建一个目录。随后写文件会真实失败，返回稳定的教学错误名。程序省略不同操作系统的错误文案，方便核对同一控制流。

接入完整循环时，权限检查应位于实际工具派发之前。映射到课程目标架构，可以放在 `ExecuteTools` 的执行边界：许可就执行，拒绝就写回配对结果，等待就返回应用。审批恢复时也回到这一边界。图路由怎样调用入口与保存状态，仍需要框架工程的独立验证。

## 5. 动手：先看等待，再看批准

在学习包解压后的目录运行以下终端命令。源码使用 edition 2024，至少需要 Rust 1.85。本文证据环境为 macOS arm64、`rustc 1.99.1`，完整版本保存在包内 `evidence.json`。

```sh
rustc --edition=2024 -D warnings permissions.rs -o permissions
./permissions wait
./permissions approve
```

Windows 原生终端将 `./permissions` 换成 `.\permissions.exe`。每次运行创建独立临时工作区，退出时清理；程序不读取当前目录的 README。

先打开[等待场景的完整输出](/learn-agent-rust/outputs/r03-wait.txt)：

<<< @/public/learn-agent-rust/outputs/r03-wait.txt

此时只有读取的工具结果，`pending=true`，写入尝试为零。回到开场的问题：打印等待时，摘要文件还没有产生。

再打开[批准场景的完整输出](/learn-agent-rust/outputs/r03-approve.txt)：

<<< @/public/learn-agent-rust/outputs/r03-approve.txt

`awaiting_approval` 与写入结果之间，`main` 用固定 `Approve` 模拟用户点击批准。实验没有读取键盘，也没有把自然语言“同意”交给模型判断。

注意：两条命令分别创建新会话。`approve` 在同一进程内完成“提出请求 → 等待 → 模拟批准 → 执行”，没有恢复上一条 `wait` 命令退出前的状态。

### 改一个条件，核对动作次数

继续运行：

```sh
./permissions deny
./permissions invalid-path
./permissions unknown
./permissions decline
./permissions tamper
./permissions replay
./permissions write-error
```

每个场景先读一次 README，随后改变写入请求或人工回复。先预测 `tamper` 与 `replay` 的写入次数，再看下图。

![十个真实运行场景中，拒绝、等待和参数替换没有写入，重复批准也只产生一次写入。](/learn-agent-rust/figures/r03-permission-results.svg)

“工具结果数”包含已经成功的 README 读取，所以等待时是 1。`tamper` 替换写入内容，回复不匹配，继续等待。`replay` 先正常批准，再重复回复，累计只写一次。`write-error` 已尝试写入，成功次数却为零。

可打开[参数替换记录](/learn-agent-rust/outputs/r03-tamper.txt)、[重复批准记录](/learn-agent-rust/outputs/r03-replay.txt)和[写入失败记录](/learn-agent-rust/outputs/r03-write-error.txt)核对原因。程序还会检查 README 保持原样，并读取最终摘要核对内容；写入成功数来自文件执行结果。

### 自动验证哪些边界

在解压目录运行 Rust 回归测试：

```sh
rustc --edition=2024 -D warnings --test permissions.rs -o permission-tests
./permission-tests
```

六个测试覆盖：未许可路径与未知工具在 I/O 前拒绝；等待期间不派发新工具；审批每个字段的绑定；其他会话的同序号审批无法混用；人工拒绝不写入；写入失败后审批不可重放。

维护者在网站仓库中重跑实验、打包和检查证据：

```sh
python3 scripts/verify-agent-permissions.py
python3 scripts/generate-learn-agent-rust-figures.py --lesson R03
python3 scripts/verify-agent-permissions.py --check
```

验证器从仓库外的临时目录运行 10 个场景和 6 个测试，保存源码哈希、文件计数和输出校验值；再独立解压下载包，重新编译并核对批准输出。正文导入保存的输出，配图读取同一份实验数据。

## 6. 谁持有哪份状态

现在沿一次写入串起职责：

| 持有者 | 输入与输出 | 本章状态生命周期 |
| --- | --- | --- |
| 请求来源 | 提出 `ToolCall` | 固定代码生成；真实模型适配后续接入。 |
| 应用策略 | 分类为允许、拒绝或审批 | 固定规则随当前程序版本生效。 |
| 运行时 | `pending`、已用调用 ID 与计数 | 保存在当前 `Runtime` 内存中。 |
| 可信入口 | 展示请求，提交人工决定 | 本实验在同进程内模拟；认证由真实入口实现。 |
| 文件工具 | 执行授权动作，返回结果 | 操作本次新建工作区；退出后清理。 |

待审批动作属于运行控制状态。模型上下文可以包含“程序正在等待人工处理”的说明，但这段文字不会创建批准资格。可信入口送回匹配回复后，`resume` 才推进状态。

单进程中“用过一次审批”只覆盖内存生命周期。退出后继续，需要保存请求身份、策略版本、待审批动作、可信决定和恢复位置。文件已写入而保存失败时，还要检查重复动作。[PostgreSQL 检查点](./postgres-checkpoints.md)与[外部操作的可靠性](./side-effect-reliability.md)会分别讨论。

::: warning 常见误区
- 把工具注册或提示词里的“请先询问”当成权限控制。策略必须覆盖文件调用前的执行路径；示例 `execute` 是模块内实现，真实应用应通过封装收紧它的调用入口。
- 把 `call_id` 或审批序号当成凭据。入口需要确认审批身份与权限，并展示完整路径和内容。
- 把等待当成成功结果。人工处理后才产生本次动作的工具结果。
- 把批准当成执行成功。批准后仍可能得到 `tool_error`，示例会消耗审批并返回错误。
- 把固定路径规则当成通用沙箱。本实验使用自己管理的新建工作区，没有验证恶意进程并发替换路径、符号链接竞态或任意 shell 命令隔离。
- 把进程内去重当成跨进程恰好执行一次。本章没有数据库、远程授权服务或故障恢复，测试结论限于当前实例。
:::

## 本章结论

工具执行前增加应用决策：立即允许、明确拒绝，或保存完整动作等待人工处理。等待时工具尚未派发；批准后先消耗审批，再执行保存的原始动作，结果继续携带原 `call_id`。

本章用文件调用计数、最终内容和失败测试核对这些行为。接入循环或图调度时，保留同样的检查边界，并单独验证框架的暂停与恢复。

## 检查理解

1. 用户批准了一次写文件，为什么不能允许后续所有写文件请求？

   <details><summary>参考答案</summary>

   不同调用的路径和内容可能不同。批准绑定到当前实例、审批序号、`call_id` 和完整动作；新动作重新判断权限。本章实现的是一次动作审批。

   </details>

2. `wait` 有一条工具结果，为什么写入次数为零？

   <details><summary>参考答案</summary>

   结果来自先前的 README 读取。写入返回 `AwaitingApproval`，保存在 `pending` 中，尚未派发文件工具，也没有对应写入结果。

   </details>

3. 审批回复换了内容，原请求还能批准吗？

   <details><summary>参考答案</summary>

   比较失败返回 `approval_mismatch`，不执行工具，也不移走 `pending`。可信入口仍可提交匹配原快照的回复，测试覆盖这一过程。

   </details>

4. 为什么写入失败后，同一个批准会被拒绝？

   <details><summary>参考答案</summary>

   `take()` 在文件调用前已移走待审批状态，失败也不会放回。重复回复得到 `no_pending_approval`。需要重试时，使用新的调用身份重新处理；跨进程重放还需持久化和幂等设计。

   </details>

5. 想关闭程序第二天再批准，保存一个 `bool approved` 够吗？

   <details><summary>参考答案</summary>

   还要保存完整动作、会话与调用身份、策略版本和恢复位置，验证审批者身份，并处理执行成功而状态保存失败的窗口。布尔值无法说明批准了哪个动作，这些能力需要独立恢复实验。

   </details>

## 参考资料

- <a href="/learn-agent-rust/code/permissions.rs" download>本章源码</a>、[学习包](/learn-agent-rust/permissions-lab.zip)与[实际批准输出](/learn-agent-rust/outputs/r03-approve.txt)。
- [Rust：枚举与模式匹配](https://doc.rust-lang.org/book/ch06-00-enums.html)。
- [Rust：Option::take](https://doc.rust-lang.org/std/option/enum.Option.html#method.take)。
- [Learn Claude Code：权限与审批](https://learn.shareai.run/zh/s03/)。下方保留原图作为对照，本章 Rust 实现与实验独立提供。

<details><summary>参考课程原图与来源</summary>

以下图片原样保留自参考课程，展示其 Python/Claude 教学实现。图中接口、编号和统计按原图理解，不作为 Rust 实验的验证结果。

![参考课程原图把工具请求、应用权限判断与人工审批分开表达。](/learn-agent-rust/figures/upstream/r03-permission-overview.svg)

图源：[参考章节](https://learn.shareai.run/zh/s03/) · [原图](https://learn.shareai.run/course-assets/s03_permission/permission-overview.svg)。关注请求与执行之间的决策位置，再对照本章的三条分支。

![参考课程原图展示权限检查管线，帮助定位执行前的判断步骤。](/learn-agent-rust/figures/upstream/r03-permission-pipeline.svg)

图源：[参考章节](https://learn.shareai.run/zh/s03/) · [原图](https://learn.shareai.run/course-assets/s03_permission/permission-pipeline.svg)。关注检查的先后关系，具体类型与规则以本章源码为准。

来源版本与许可见[课程架构中的参考资料说明](./architecture.md#reference-assets)。

</details>

下一章：[第 4 章 · 生命周期与 Hooks](./hooks.md)（规划中），把执行前检查、执行后记录与停止处理放到清晰的扩展点中。
