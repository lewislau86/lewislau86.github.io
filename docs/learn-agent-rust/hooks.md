---
title: "第 4 章：生命周期与 Hooks"
description: "沿一次已批准的文件写入，建立执行前、执行后与停止阶段的扩展点，验证拒绝、失败和超时。"
prev:
  text: 第 3 章 · 工具权限与审批
  link: /learn-agent-rust/permissions
next:
  text: 第 5 章 · 可见的任务清单
  link: /learn-agent-rust/todo-planning
pageClass: learn-agent-rust-course
---

# 第 4 章：生命周期与 Hooks

[课程总览](./index.md) · [上一章：工具权限与审批](./permissions.md) · [下一章：可见的任务清单](./todo-planning.md)

::: tip 本章学习目标
- 沿一次工具轮次，解释输入提交、执行前、执行后和停止四个扩展点。
- 按注册顺序运行回调，明确阻止与失败如何结束当前回调链。
- 核对失败发生时文件已经产生什么结果，并终止、回收超时实验的直属子进程。

**前置：** [第 3 章](./permissions.md)的“批准绑定具体动作”，Rust 的 `trait`、枚举、借用、`Result` 和 `Vec`。本章补充 `Box<dyn Hook>` 的用途。

**实践方式：** 下载[本章学习包](/learn-agent-rust/hooks-lab.zip)，使用 Rust 1.85 或更新版本编译。标准库独立实验，无需模型密钥、数据库或其他章节源码。
:::

上一章已经能确认：“这份摘要得到批准后，才能写入。”

现在，工作区助手还要在写入前记录调用，在写入后检查结果，任务结束时整理停止原因。如果每增加一个要求，都往文件执行函数里塞一段代码，权限、日志、文件操作与收尾就会混在一起。

我们先保留同一个小任务：把“启动命令：cargo run”写入 `notes/summary.txt`。本章把额外行为挂到明确的边界上，这些回调就叫 **Hook**。

先猜一个结果：文件写入成功后，负责记录结果的 Hook 报错了，文件还在吗？程序应该说“文件没写进去”，还是保留真实结果并报告检查失败？

<LearnAgentRustMap active="hooks" />

<!-- experiment-library:start -->

全书实验可从[统一代码库](./experiments.md#hooks)下载；解压后进入 `chapters/hooks/`，或在代码库根目录运行 `python3 run.py run R04`。

<!-- experiment-library:end -->

## 1. 沿一次写入找到四个位置

Hook 首先是一份调用约定：到达某个位置时，运行时提供什么信息，按什么顺序调用回调，如何解释返回值。

本章选择四个事件：

| 事件 | 触发位置 | 回调能看到什么 | 本章用途 |
| --- | --- | --- | --- |
| `UserPromptSubmit` | 收到输入之后、生成工具请求之前 | 输入文本 | 输入记录与拦截。 |
| `PreToolUse` | 核对授权之后、真正调用工具之前 | 输入与完整动作 | 追加执行前检查。 |
| `PostToolUse` | 工具返回成功或错误之后 | 原始动作与配对结果 | 观察结果与后置检查。 |
| `Stop` | 本次任务准备返回时 | 已有结果与停止原因 | 收尾记录。 |

![真实正常运行按输入提交、执行前、执行后与停止的顺序触发四个事件。](/learn-agent-rust/figures/r04-lifecycle-order.svg)

从上往下读，在 `PreToolUse` 与 `PostToolUse` 之间发生真实文件写入。同一事件有两个回调时，按注册先后执行。`Stop` 汇集本章控制流中各条返回路径，包括输入被挡住、权限拒绝、工具失败和正常完成。

这里的“生命周期”指一次任务从输入到返回的推进过程；本章重点是回调触发位置，Rust 的借用规则帮助约束回调能访问的状态。

::: info 源码与实验范围
完整代码只有一份：<a href="/learn-agent-rust/code/hooks.rs" download>下载 hooks.rs</a> · [GitHub 源码](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/learn-agent-rust/code/hooks.rs) · [学习包](/learn-agent-rust/hooks-lab.zip)。下文 Rust 片段直接从源码导入。

实验覆盖一个固定工具轮次与收尾：输入和工具请求由程序生成，可信测试入口提供一份已批准动作，文件由 `std::fs` 真实写入。它位于上一章审批恢复后的执行边界，省略审批交互；没有在本章接入真实模型或 `graph-flow`。
:::

## 2. 让回调读到恰当的上下文

先看事件、上下文与回调契约：

<<< @/public/learn-agent-rust/code/hooks.rs#contracts

`HookContext` 保存借用：执行前有 `call`，执行后增加 `result`，停止时增加 `stop_reason`。`Option` 让“这个阶段还没有工具结果”在类型里表达出来。

`Hook::call` 获得的是只读引用。回调可以检查已批准动作，却不能通过这份上下文替换路径或写入内容。这样，上一章“批准对应原始动作”的约束继续保留。

`Decision` 表示业务决定：继续，或阻止。`HookError` 则表示回调没有完成约定，例如主动返回错误、子进程异常退出、超时后已回收，或者在不允许阻止的阶段返回了 `Block`。

两者要分开理解。一个检查正常运行后发现输入不符合要求，可以返回 `Block`；检查本身出错，则返回 `Err`。程序保留两种原因，便于后续解释与排查。

`Box<dyn Hook>` 把不同回调放进同一列表：它们的实现可以不同，只要都提供 `name`、`event` 和 `call`。`dyn Hook` 表示调用时根据具体对象选择实现，`Box` 则让列表中的每一项具有确定的存放方式。

普通回调在 Agent 进程内运行，因此它们仍属于受信任的应用代码。只读上下文约束这份接口，并不会限制回调自行访问文件或网络。

## 3. 注册顺序，就是执行顺序

本实验给四个位置注册回调。正常情况下它们只返回 `Continue`；切换场景时，让一个回调阻止、报错或进入故障 worker：

<<< @/public/learn-agent-rust/code/hooks.rs#registration

例如 `before-check` 先于 `before-log` 注册。若前一个回调阻止动作，后一个就不运行。我们把回调链固定为**遇到第一个阻止或错误，就结束当前事件的分发**。

分发器集中实现这份约定：

<<< @/public/learn-agent-rust/code/hooks.rs#dispatch

`dispatch` 先按事件筛选，再按列表顺序调用。每次调用的名称与结果都进入 `trace`，运行输出因此能直接核对顺序。

为什么 `PostToolUse` 和 `Stop` 返回 `Block` 会变成 `InvalidDecision`？前者触发时，文件工具已经结束；后者负责收尾。本章不赋予这两个位置撤销动作或强制续跑的含义，返回值不符合本章契约时就报告协议错误。

这只是本实验选择的明确语义。接入别的 Hook 系统前，需要重新核对它的事件、允许的返回值与失败处理。

### 权限判断继续是必经步骤

可选回调适合扩展检查，但工具仍应保留必经的授权边界：

<<< @/public/learn-agent-rust/code/hooks.rs#authorize

测试入口给出 `approved`，表示上一章已经确认的完整动作。这里比较 `call_id`、路径与内容，并再次限制固定目标与字节上限。缺少匹配批准时返回权限拒绝，省略了重新发起审批的流程。

回调注册表为空时，这份检查仍然存在。对应测试会先移除所有 Hook，确认没有批准就不会写入；再提供匹配批准，确认工具可以执行。Hook 可以追加限制，移除 Hook 不会移除这条授权边界。

## 4. 执行前失败，文件工具不会收到调用

先看授权检查到 `PreToolUse` 的这一段：

<<< @/public/learn-agent-rust/code/hooks.rs#before_tool

授权未通过，返回 `permission_denied`。授权通过后，才进入执行前回调链：

- 回调正常放行，继续走向文件工具。
- 回调返回 `Block`，生成 `hook_blocked` 工具结果。
- 回调报错或超时，生成 `hook_error` 工具结果。

后两条路径都会保留原 `call_id`，然后进入统一收尾。文件执行函数没有运行，因此不会触发 `PostToolUse`。

输入提交阶段还要更早：若 `UserPromptSubmit` 阻止输入，程序尚未生成工具请求，也就没有工具结果。本章的 `prompt-block` 场景会输出 `result none`，不会凭空创建一次工具调用。

## 5. 执行后失败，保留已经发生的事实

真正写入后，运行时先保存工具结果，再分发后置回调：

<<< @/public/learn-agent-rust/code/hooks.rs#after_tool

`write_attempts` 紧挨 `fs::write` 增加；成功返回后才增加 `write_successes`。无论文件操作成功还是失败，都有一个实际工具结果，再交给 `PostToolUse`。

如果后置检查报错，`stop_reason` 变成 `post_hook_failed`，但原工具结果保持原样。成功写入仍然是 `ok`，写入失败仍然是 `tool_error`。

程序还会读取最终摘要核对内容。因此开场问题可以用文件检查回答：后置 Hook 失败时，成功写入的文件仍在。本次运行应同时报告“工具成功”和“后续检查失败”。

![实测计数显示执行前阻止不会写入，执行后和停止回调失败则保留已经成功的写入。](/learn-agent-rust/figures/r04-failure-results.svg)

先比较 `pre-timeout` 与 `post-timeout`：同样是超时，写入次数分别为零和一次。再看 `stop-error`：工具结果是 `ok`，任务通过检查却为“否”。失败位置决定了动作已经推进到哪里。

### 所有受控返回，都汇合到一次 Stop

<<< @/public/learn-agent-rust/code/hooks.rs#finish

`finish` 接收已经确定的停止原因，触发一次 `Stop` 后返回。停止回调出错时，错误进入 `failures`；程序不会再次触发 `Stop`，也不会悄悄启动下一轮。

因此 `stop-error` 中 `stop_reason=completed` 表示执行流程原本到达完成位置；`task_ok=false` 则表示加上收尾检查后，本次运行没有全部通过。最终判定同时检查停止原因与回调错误列表。

这里的统一出口覆盖本程序显式处理的业务返回。进程被强制终止、内联回调发生未处理 panic 或程序崩溃时，无法依赖普通 `Stop` 回调完成清理。

## 6. 超时之后，还要结束和回收回调

仅仅把“超时”写进结果里，阻塞回调可能仍在后台运行。对普通同步 Rust 函数，外层计时也无法自动抢占正在执行的函数。

本章专门把两个故障回调放到直属子进程：

| worker 模式 | 实际行为 | 父进程如何观察 |
| --- | --- | --- |
| `panic` | 执行真实 `panic!` 并异常退出 | 映射为 `WorkerExited`。 |
| `hang` | 持续等待 | 达到预算后终止并等待回收，映射为 `TimeoutReaped`。 |

普通记录、阻止与返回错误的回调仍在进程内。worker 是本程序的固定故障入口，不接受模型提供的任意命令。

![父进程检测固定 worker 的退出与预算，超时后先终止再等待回收，最后返回错误。](/learn-agent-rust/figures/r04-worker-timeout.svg)

沿图中父进程读：先启动 worker，再用 `try_wait` 检查退出；达到预算后，调用 `kill` 和 `wait`。只有等待成功，程序才返回 `TimeoutReaped`。

<<< @/public/learn-agent-rust/code/hooks.rs#worker

`kill` 与 `wait` 负责不同事情：前者请求终止，后者等待子进程结束并回收相关资源。Rust 的 `Child` 不会在被丢弃时自动替我们完成这一生命周期，详细约定见 [Child 官方文档](https://doc.rust-lang.org/std/process/struct.Child.html)。

完整源码中的 `OwnedWorker` 还为提前返回的 I/O 错误提供尽力清理。实验没有创建 worker 的后代进程，因此这里验证的是直属子进程回收。

故障场景使用 40 毫秒预算、2 毫秒轮询间隔；panic 场景给出 5 秒预算，避免把正常启动开销当作 panic。这些是教学配置，预算从 `spawn` 返回后开始计时，调度和回收仍有额外开销。实验不报告毫秒级性能结论，也不把它描述成实时终止保证。

## 7. 动手：从一条正常轨迹开始

在学习包解压后的目录运行：

```sh
rustc --edition=2024 -D warnings hooks.rs -o hooks
./hooks normal
```

Windows 原生终端把 `./hooks` 换成 `.\hooks.exe`。每次运行新建临时工作区，退出时清理。本文输出记录的环境为 macOS arm64、`rustc 1.99.1`；同时使用 Rust 1.85.0 复核。完整环境保存在包内 `evidence.json`。

[正常场景的完整输出](/learn-agent-rust/outputs/r04-normal.txt)如下：

<<< @/public/learn-agent-rust/outputs/r04-normal.txt

沿编号核对：授权检查在执行前回调之前；两个前置回调结束后才写文件；得到工具结果后运行两个后置回调；最后触发一次 `Stop`。

再比较三个失败位置：

```sh
./hooks pre-timeout
./hooks post-error
./hooks stop-timeout
```

先预测每个场景的写入次数，再看[前置超时输出](/learn-agent-rust/outputs/r04-pre-timeout.txt)：

<<< @/public/learn-agent-rust/outputs/r04-pre-timeout.txt

`before-check` 超时后，`before-log` 被短路，工具没有执行，后置事件也没有出现；`Stop` 仍然触发一次。

打开[后置错误输出](/learn-agent-rust/outputs/r04-post-error.txt)和[停止超时输出](/learn-agent-rust/outputs/r04-stop-timeout.txt)，会看到摘要已匹配、工具仍为 `ok`，同时存在回调错误。它们印证了“真实执行结果”和“完整运行通过”需要分别记录。

### 把剩余路径也跑一遍

```sh
./hooks prompt-block
./hooks permission-deny
./hooks pre-block
./hooks pre-error
./hooks pre-panic
./hooks post-timeout
./hooks post-block
./hooks tool-error
./hooks stop-error
./hooks stop-block
rustc --edition=2024 -D warnings --test hooks.rs -o hook-tests
./hook-tests
```

`tool-error` 先在摘要路径创建目录，让文件写入真实失败；仍然会触发后置与停止事件。`post-block` 和 `stop-block` 故意违反返回值契约，验证 `InvalidDecision`。`pre-panic` 使用异常退出的子进程，验证主进程能得到失败结果并继续收尾；它没有证明所有内联 Rust panic 都会被隔离。

八个 Rust 测试覆盖注册顺序、只读上下文、无 Hook 时的授权边界、输入拦截、前置短路、后置错误保留文件、文件失败后的事件、停止错误与非法后置决定。

维护者在网站仓库中重建与检查产物：

```sh
python3 scripts/verify-agent-hooks.py
python3 scripts/generate-learn-agent-rust-figures.py --lesson R04
python3 scripts/verify-agent-hooks.py --check
```

验证器在仓库外运行 14 个场景和 8 个测试，核对事件次序、结果关联、文件计数、错误类型与停止次数。它还会独立解压学习包，重新编译并运行正常、前置超时、后置错误和停止超时场景。

## 8. 接回循环时，哪些约定要保持

本章把 Hook 放到应用运行时的边界。在第 2 章的目标结构中，输入事件位于进入循环之前，前置与后置事件围绕 `ExecuteTools` 的真实派发，停止事件由外层根据停止原因统一触发。

接入 `graph-flow` 时，要用相同用例重新验证顺序与返回状态。图节点正常返回或暂停，并不自动对应这里的业务 `Stop`；每个工具也必须继续携带自己的 `call_id`。本章标准库实验的通过不能代替这项集成验收。

想给新检查增加一个实现时，先确定它属于哪个事件，再决定允许的返回值和失败策略。日志回调如果只是内存记录，就按内存记录理解；若业务要求审计记录必须可靠保存，还要引入存储与保存失败的处理。

::: warning 常见误区
- 把 Hook 当成权限来源。它可以追加检查，必经授权与审批绑定仍由应用保证。
- 以为所有回调都会执行。本章遇到第一个阻止或错误就结束当前事件的链；统一收尾另行执行。
- 在后置 Hook 出错时改写真实工具结果。文件可能已经写入，应保留工具结果并另外记录检查失败。
- 把 `Stop` 当成目标完成。本章停止事件负责通知，`task_ok` 还要结合错误；强制续跑属于[目标控制专题](./workflow-and-goal-control.md)。
- 以为 timeout 会停止任意内联代码。本章故障回调使用直属子进程，验证其终止与回收，不提供通用沙箱或进程树管理。
- 依赖 Stop 完成所有资源清理。显式收尾只覆盖受控返回，资源本身仍应管理所有权与退出清理。
:::

<!-- transfer-thinking:start -->

## 迁移思考：观察者也会成为故障源

日志 Hook 在写入成功后抛错，重跑整轮会发生什么？先给出你的判断，再展开下面的推演。

<details><summary>推演与应用</summary>

先确认写入效果，再分别记录动作状态与观察状态；后置回调失败不自动抹掉既有动作。

监控与审计应有明确失败策略，否则观察机制会改变业务语义。

</details>

这是一道迁移练习，推演不代表新增实验已通过。对照[全书审查中的证据层次](./course-review.md#evidence-layers)，说明你的判断还需要哪一级证据。

<!-- transfer-thinking:end -->

## 本章结论

Hook 为稳定的执行流程提供扩展位置：运行时决定何时触发、传入什么上下文和怎样解释结果，回调实现具体检查或记录。

本章保留强制授权，按注册顺序运行回调；前置失败阻止工具派发，后置失败保留真实结果，统一 Stop 只执行一次。超时实验通过直属子进程验证终止与回收。将来接入图调度或可靠存储时，继续用这些正常与失败路径核对边界。

## 检查理解

1. `PreToolUse` 注册了检查和日志两个回调，检查返回 `Block`，日志还会运行吗？

   <details><summary>参考答案</summary>

   不会。本章回调链遇到阻止或错误就短路，工具也不会执行；程序产生配对的阻止结果，然后进入统一 Stop。若需要记录所有拒绝，应该设计明确的拒绝事件或在统一结果处记录，而不是假设后续回调一定执行。

   </details>

2. 为什么移除所有 Hook 后，未批准动作仍然不能写入？

   <details><summary>参考答案</summary>

   `authorized` 是实际派发前的必经步骤，独立于可选回调。它验证固定路径、内容上限与完整批准快照。对应 Rust 测试会移除注册表并检查文件没有产生。

   </details>

3. 文件成功写入，后置 Hook 超时，应该怎样记录？

   <details><summary>参考答案</summary>

   保留原 `ok` 工具结果和 `call_id`，同时记录 `TimeoutReaped` 与 `post_hook_failed`，任务通过检查为假。超时后的回调终止不会撤销已经写入的文件。

   </details>

4. 为什么超时处理既有 `kill` 又有 `wait`？

   <details><summary>参考答案</summary>

   终止请求与进程回收是两个步骤。父进程等待直属 worker 结束并回收后，才返回本实验的 `TimeoutReaped`。本例没有创建后代进程，因此不能扩展为任意进程树回收的结论。

   </details>

5. `Stop` 回调报错后，为什么不再触发一次 Stop？

   <details><summary>参考答案</summary>

   Stop 已经在处理收尾。如果报错后递归调用同一收尾，可能无限重复。本章把错误追加到失败列表，保留原工具结果与停止原因，然后直接返回；后续是否继续需要独立的目标控制策略。

   </details>

## 参考资料

- <a href="/learn-agent-rust/code/hooks.rs" download>本章完整源码</a>、[学习包](/learn-agent-rust/hooks-lab.zip)和[正常运行记录](/learn-agent-rust/outputs/r04-normal.txt)。
- [Rust：使用 trait 对象](https://doc.rust-lang.org/book/ch18-02-trait-objects.html)，理解 `Box<dyn Hook>`。
- [Rust：Child](https://doc.rust-lang.org/std/process/struct.Child.html)，核对 `try_wait`、`kill`、`wait` 与资源生命周期。
- [Learn Claude Code：Hooks](https://learn.shareai.run/zh/s04/)，参考事件位置；本章采用独立的返回值契约与 Rust 实验。

<details><summary>保留的参考原图与来源</summary>

以下原图来自参考课程的 Python/Claude 教学实现，接口、事件语义和编号按原图理解，不作为本章 Rust 实验结果。

![参考课程原图展示围绕模型与工具轮次设置的生命周期扩展位置。](/learn-agent-rust/figures/upstream/r04-hooks-overview.svg)

图源：[参考章节](https://learn.shareai.run/zh/s04/) · [原图](https://learn.shareai.run/course-assets/s04_hooks/hooks-overview.svg)。先关注扩展点的位置，再对照本章源码中的短路和失败规则；本章 Stop 只通知一次。

来源版本与许可见[课程架构中的参考资料说明](./architecture.md#reference-assets)。

</details>

下一章：[第 5 章 · 可见的任务清单](./todo-planning.md)，把长任务的步骤与当前进度显式记录下来。
