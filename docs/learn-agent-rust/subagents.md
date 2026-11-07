---
title: "第 6 章：子 Agent 与上下文隔离"
description: "用独立 Rust 实验拆分父子消息历史，只回传子任务报告，并验证共享预算、执行权限与取消清理。"
pageClass: learn-agent-rust-course
prev:
  text: 第 5 章 · 可见的任务清单
  link: /learn-agent-rust/todo-planning
next:
  text: 第 7 章 · 按需加载技能
  link: /learn-agent-rust/skill-loading
---

# 第 6 章：子 Agent 与上下文隔离

[课程总览](./index.md) · [上一章：可见的任务清单](./todo-planning.md) · [学习路径](./learning-path.md) · [下一章：按需加载技能](./skill-loading.md)

::: tip 本章学习目标
- 为一次子任务建立独立的消息历史，解释父会话交出什么、收回什么。
- 同时限制子任务用量和父子总用量，核对失败、拒绝和已完成任务的计费口径。
- 发出取消请求后，等待子执行者退出，再检查临时资源清理。

**前置：** [第 2 章：工具注册与图调度](./tools-and-graph.md)中的消息与工具边界，以及[第 3 章：工具权限与审批](./permissions.md)中的执行前策略。第 4–5 章的 Hooks 与待办机制不是本实验的前提。

**实践方式：** 下载[本章独立学习包](/learn-agent-rust/subagents-lab.zip)，解压后用支持 edition 2024 的 Rust 工具链编译。只有标准库依赖，无需模型密钥、数据库或其他课程工程。
:::

给助手一个任务：“读取 README，告诉我项目启动命令。”父 Agent 可以自己完成，也可以把“从 README 提取启动命令”交给一个子 Agent。

先想一想：如果把父会话的全部消息复制给子 Agent，等它结束后又把全部过程粘回来，父会话会更短吗？我们希望父会话保留任务主线，而文件读取的中间过程留在子会话里。因此，本章新增的机制是：**明确传入子任务，建立新的历史，只把约定的结果送回父模型。**

本章沿用前两章的消息与权限思路，提供一个新的独立入口。父子都用固定规则的脚本模型；文件读取和子线程创建实际发生。先把接口和资源生命周期跑清楚，再讨论真实模型与框架接入。

<LearnAgentRustMap active="subagents" />

## 1. 先运行：父模型最后看到了什么？

解压学习包，在其中打开终端。先编译，再运行正常场景：

```sh
rustc --edition=2024 -D warnings subagents.rs -o subagents
./subagents normal
```

Windows 原生终端运行 `./subagents.exe normal`。每次运行都会创建自己的临时工作区，其中有 README 和一份未授权给子任务的 `private.txt`；运行结束后清理。

::: info 代码与输出只有一个来源
本文 Rust 片段直接导入完整源码：<a href="/learn-agent-rust/code/subagents.rs" download>下载 subagents.rs</a> · [GitHub 源码](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/learn-agent-rust/code/subagents.rs)。[学习包](/learn-agent-rust/subagents-lab.zip)还包含运行说明、全部场景输出、环境记录和验证证据。

终端输出分为“父模型上下文”与“宿主诊断中的子上下文”。两部分一起打印供读者核对；程序只把子任务报告放进父模型消息，完整子历史由宿主保留作诊断。
:::

先预测：父、子分别会有几条消息？然后查看实际输出：

<<< @/public/learn-agent-rust/outputs/r06-normal.txt

父会话先提出 `parent/delegate-1` 这次委派。子会话从自己的系统规则和任务开始，提出 `child-1/read-1` 文件读取请求，看到文件内容后提取启动命令。父模型收到子任务报告，再给用户回答。

输出中故意放了两个公开的测试标记：

- `PARENT_ONLY_NOTE` 出现在父系统消息中，用来检查这条消息是否被传给子模型。
- `CHILD_RAW_ONLY` 写在练习 README 中，用来检查原始文件内容是否被整段送回父模型。

子诊断里能看到第二个标记，说明子任务实际拿到了文件内容；父模型的工具结果中只有状态、启动命令摘要和子任务用量。这两个标记用于检查数据流，内容本身没有保密价值。

![父会话和子会话各自保存消息，父会话只接收子任务报告，子会话的文件原文留在诊断历史中。](/learn-agent-rust/figures/r06-context-boundary.svg)

先分别沿左右两列读消息，再看中间的任务与报告箭头。正常实验中父子各有 5 条消息，但两份历史的内容和用途不同；这里检查的是消息边界，尚未测量 token 节省或任务质量提升。

## 2. 先定义子任务，再创建新的历史

一个子任务至少要说清三件事：做什么、允许用多少资源、返回什么。本文把输入和输出分成两种结构：

<<< @/public/learn-agent-rust/code/subagents.rs#contract

`ChildTask` 只包含会话 ID、任务说明和局部额度。创建子任务时，父会话自行挑选这次需要的输入；完整父历史没有传给工作线程。

`ChildReport` 是返回契约：

| 字段 | 回答的问题 |
| --- | --- |
| `session_id` | 这份报告来自哪次子任务？ |
| `stop` | 子任务正常完成，还是遇到预算、权限、取消或模型错误？ |
| `summary` | 有可返回的任务结论吗？ |
| `usage` | 子任务实际消耗了几轮模型、几次工具执行尝试？ |

`ChildRun` 额外保留完整子历史，供宿主诊断。父模型收到的文本由 `ChildReport::for_parent()` 产生；宿主并没有把 `ChildRun.history` 作为工具结果追加给它。

### 新历史从哪里开始？

本章的消息类型沿用“系统说明、用户任务、模型请求、工具结果、最终回答”的顺序：

<<< @/public/learn-agent-rust/code/subagents.rs#messages

子循环创建一个新的 `Vec<Message>`，最初只有两条：子系统规则和本次任务。它不会继承父会话中的其他请求、诊断笔记或往返历史。

任务说明限制为非空且不超过 256 个 UTF-8 字节；摘要上限为 160 个 UTF-8 字节。两个数字都是本教学应用选择的接口约束，并非性能实验结论。摘要过长时返回 `OutputLimit`，不把超长内容继续送入父模型。

### 子 Agent 一定要运行在独立进程吗？

本章把子任务放进同一进程的一个 Rust 线程。它拥有独立的消息向量和局部用量，通过应用传入的能力读取工作区。线程共享进程的地址空间和操作系统权限，创建新历史不会自动形成文件系统沙箱。

是否拆成独立进程、容器或远端服务，是另一层执行与隔离设计。本章先验证模型上下文的分离，以及宿主如何管理一次子执行的生命周期；后续[后台任务](./background-tasks.md)、[Agent 团队](./agent-teams.md)和[工作区隔离](./worktree-isolation.md)分别扩展这些能力。

## 3. 子循环继续经过工具权限检查

子模型看到自己的历史后，第一次返回读取请求，第二次从工具结果中提取启动命令：

<<< @/public/learn-agent-rust/code/subagents.rs#model

这是固定规则替身：它按消息类型返回预设行动，从文件文本寻找“启动命令：”这一行。`changed-readme` 会让答案跟随文件内容变化；`model-error` 等分支用于验证失败路径。它没有调用真实语言模型。

父模型也由固定代码模拟：先生成委派请求，再根据报告生成最终文本。脚本模型让输入和控制流稳定，便于判断宿主是否正确传递数据和停止。

### 新会话使用哪些工具？

本章子任务只有 `read_file`，参数精确限制为 `README.md`。实际文件调用之前还会检查一次名称和路径：

<<< @/public/learn-agent-rust/code/subagents.rs#tool

即使替身提出 `read_file("private.txt")`，执行器也会返回拒绝，文件读取计数保持为零。如果提出 `delegate`，同样被拒绝。子循环中没有再创建下一层执行者的分派入口。

因此，工具能力同时体现在暴露给模型的接口和真正执行时的检查上。未来若允许子 Agent 写文件，需要重新接入第 3 章的动作权限与审批契约，明确哪些决定必须回到可信入口。

本例父子都能访问同一个练习根目录的路径对象；真正限制子工具的是上述执行器。若允许任意文件路径，还需要处理路径解析、符号链接、大小限制和竞态。本实验只读取程序创建的固定小文件。

## 4. 子任务有局部额度，父子共用总账

先算一算正常路径的用量。父模型需要“提出委派”和“最终回答”两轮；子模型需要“提出读取”和“提取命令”两轮。工具执行包括父侧的委派与子侧的文件读取。

因此，正常路径累计是 4 轮模型、2 次工具执行尝试，其中子任务占 2 轮模型、1 次工具执行尝试。下面的预算实现同时检查这两层上限：

<<< @/public/learn-agent-rust/code/subagents.rs#budget

`SharedBudget` 让父子引用同一份 `Budget`。`Arc` 共享所有权，`Mutex` 保护总用量的检查和增加；子任务另外持有自己的 `Usage`，避免一个子任务用完整个会话的额度。

`charge_child` 的顺序是：先检查局部额度，再在锁内检查并扣除总额度，最后增加子用量。局部额度不足时不扣总账；总额度不足时也不增加子用量。锁不会跨越模型或文件调用持有。

![正常路径的总用量由父侧两轮模型和一次委派、子侧两轮模型和一次读取组成；子任务完成后父回答仍要检查总额度。](/learn-agent-rust/figures/r06-shared-budget.svg)

先看正常路径的父、子分项，再看右侧额度只剩 3 轮模型的场景：子任务能够完成，父模型却没有额度组织最终回答。共享总账随当前会话存在，创建新子任务不会重置它。

### 失败和拒绝怎样计数？

本章模型预算计调用尝试，工具预算计分派尝试。已开始的调用即使报错，也消耗额度；名称或权限拒绝也计入子工具尝试。被预算入口拦下的动作尚未分派，不增加用量。

`reads` 只在权限通过、准备调用 `fs::read_to_string` 时增加；`successes` 只在成功读出时增加。父侧的 `delegate` 消耗一次工具额度，但本身不增加文件读取次数。

这份总账只包含模型和工具的次数。token、费用、经过时间、递归深度与多子任务并发上限，还要在扩展执行器时另行定义。当前程序只创建一个子线程，并在继续父回答前等待它结束。

## 5. 子循环何时停，结果怎样回到父会话？

有了输入、消息、权限和预算，子循环可以完整写出来：

<<< @/public/learn-agent-rust/code/subagents.rs#child-loop

第一次阅读只沿正常路径走：建立两条初始消息，检查取消与模型额度，记录读取请求，经过控制点和工具额度检查，实际读取并追加结果，再进入下一轮模型。得到长度合规的摘要后返回 `Completed`。

第二次阅读关注退出位置：

- 模型或工具额度不足，返回对应的局部或全局预算状态。
- 取消标记已设置，或父侧控制通道断开，返回 `Cancelled`。
- 文件、权限或模型失败，保留已经发生的历史和用量，返回失败状态。
- 摘要超长，返回 `OutputLimit`，`summary` 保持为空。

这个替身每次只产生一轮工具请求。读取前的通道握手是本章的实验控制点，用于确定取消顺序；它不是给任意远程模型使用的通用多轮调度协议。

父侧驱动器随后把报告变成原委派调用的工具结果，再检查总模型额度，生成回答：

<<< @/public/learn-agent-rust/code/subagents.rs#parent

注意两组身份：父结果继续关联 `parent/delegate-1`；子文件结果关联 `child-1/read-1`。二者分别属于各自的消息历史。子报告里的会话 ID 用于识别子任务，也不代替父工具调用 ID。

父工具消息外层的 `status=ok` 表示宿主成功取得报告。报告内部的 `status=MissingFile` 等状态才说明子任务的业务结果。正常与失败报告都要送回父模型，让它依据实际情况继续。

`parent_stop=Completed` 表示父侧生成了最终响应，响应也可能是失败说明。练习目标另用 `fixture_goal_met` 核对：实际读取成功，且父回答包含练习文件中约定的启动命令，才为 `true`。

## 6. 取消请求发出以后，资源由谁清理？

先预测：父会话丢弃一个普通 `JoinHandle`，子线程会立即停止吗？Rust 标准库规定，丢弃它会让线程脱离句柄继续运行；要等待线程终止，需要调用 `join()`。这两种行为见 [JoinHandle 文档](https://doc.rust-lang.org/std/thread/struct.JoinHandle.html)。

本章用 `ChildHandle` 同时持有取消标记、控制通道和线程句柄。正常结束时等待报告；所有者提前退出时，请求取消、关闭通道，再等待线程退出：

<<< @/public/learn-agent-rust/code/subagents.rs#child-handle

`finish` 先等子任务到达读取前的控制点；若子任务在额度或输入检查阶段已经返回，发送端断开也会让等待结束。正常场景放行，`cancel` 场景先设置标记再放行，`gate-closed` 则直接关闭通道。

控制通道使用有界的 `sync_channel(1)`。接收端在等待消息时阻塞，发送端断开时会得到错误；这些规则来自 [Rust 标准库文档](https://doc.rust-lang.org/std/sync/mpsc/fn.sync_channel.html)。子任务据此把父控制入口消失视为取消。

![取消场景先请求取消，再唤醒子线程；子线程退出作用域清理临时资源，父侧 join 后才删除根工作区。](/learn-agent-rust/figures/r06-cancel-lifecycle.svg)

沿图从上往下看。取消标记只提出要求，退出和清理发生在子线程观察到要求之后。最后两个验证点分别是工作线程已被 `join`、临时目录实际不存在。

### 临时资源跟随谁的作用域？

子线程建立一个自己的 `child-scratch` 目录，并用 `ChildResources` 持有。正常返回、预算停止、模型失败或取消，都会离开该作用域：

<<< @/public/learn-agent-rust/code/subagents.rs#cleanup

`Drop` 尝试删除子临时目录并减少资源计数。父侧在 `join` 后检查子目录不存在，再删除整个练习工作区并核对结果。清理调用本身可能失败，因此验证器检查实际目录状态，而不只检查“调用过清理”。

这里是协作取消：程序在约定边界观察标记。取消无法撤销已经完成的文件读取，也无法强制终止任意阻塞函数；接入真实模型和慢工具时，需要支持请求中断、超时、资源关闭和退出等待。本章取消实验固定在文件调用之前，不把这一结果外推到任意执行时刻。

## 7. 动手：每次改变一个条件

### 实验 A：文件内容变化，父回答跟着变吗？

```sh
./subagents changed-readme
```

该场景只把练习 README 中的启动命令改为 `cargo run --release`。子提取规则、报告字段和父回答逻辑保持相同。完整记录见[改变 README 的输出](/learn-agent-rust/outputs/r06-changed-readme.txt)。检查父回答变化，同时确认 `CHILD_RAW_ONLY` 仍只留在子诊断里。

### 实验 B：子任务完成后，父侧还可能停住吗？

```sh
./subagents parent-answer-budget
```

<<< @/public/learn-agent-rust/outputs/r06-parent-answer-budget.txt

子任务状态为 `Completed`，父历史已经收到报告，但总模型用量达到 3，第四轮无法开始。父消息数停在 4，目标断言为 `false`。这个实验说明子任务自己的成功只是父流程中的一步。

再分别运行 `child-model-budget`、`child-tool-budget`、`global-model-budget` 和 `global-tool-budget`，先猜哪一次调用会被阻止，再看下方结果表。局部额度与总额度保护不同的边界，消耗过的总额度不会因子任务失败退回。

### 实验 C：在文件读取前取消

```sh
./subagents cancel
```

<<< @/public/learn-agent-rust/outputs/r06-cancel.txt

子模型已经提出读取请求，父侧收到控制点通知后设置取消标记，再让子侧继续。子历史为该请求补上取消结果，真实读取次数为 0；父侧等待线程退出后检查资源。

再运行 `cancel-before-start` 和 `gate-closed`。前者在子模型第一轮之前就设置标记，后者在控制点关闭通道；它们都应返回 `Cancelled`，但子模型用量不同。

### 实验 D：子任务能否越过权限或继续委派？

```sh
./subagents forbidden-path
./subagents recursive
```

这两个场景分别提出读取 `private.txt` 和调用 `delegate`。应用返回 `Denied`，读取尝试为 0。没有创建第二层子线程，也没有访问未授权文件。可对照[路径拒绝记录](/learn-agent-rust/outputs/r06-forbidden-path.txt)与[递归拒绝记录](/learn-agent-rust/outputs/r06-recursive.txt)。

### 实验 E：失败结果是否会伪装成完成？

运行 `missing-file`、`invalid-task`、`oversized-result` 和 `model-error`。它们依次模拟缺失文件、空任务、超长摘要和模型接口失败。看子报告的停止原因，再看父侧是否如实生成“任务未完成”的说明。

## 8. 结果表与复现范围

下表由验证脚本实际运行后生成。模型次数包含父子固定替身的调用尝试；工具次数包含父委派和子工具分派。所有场景都检查父子标记分离、已接受调用的结果配对，以及线程退出后的资源状态。

<!-- r06-results:start -->

| 场景 | 子模型 / 工具 | 总模型 / 工具 | 读取尝试 / 成功 | 子停止原因 | 练习目标达成 |
| --- | --- | --- | --- | --- | --- |
| `normal` | 2 / 1 | 4 / 2 | 1 / 1 | `Completed` | 是 |
| `changed-readme` | 2 / 1 | 4 / 2 | 1 / 1 | `Completed` | 是 |
| `missing-file` | 2 / 1 | 4 / 2 | 1 / 0 | `MissingFile` | 否 |
| `child-model-budget` | 1 / 1 | 3 / 2 | 1 / 1 | `ChildModelBudget` | 否 |
| `child-tool-budget` | 1 / 0 | 3 / 1 | 0 / 0 | `ChildToolBudget` | 否 |
| `global-model-budget` | 1 / 1 | 2 / 2 | 1 / 1 | `GlobalModelBudget` | 否 |
| `global-tool-budget` | 1 / 0 | 3 / 1 | 0 / 0 | `GlobalToolBudget` | 否 |
| `parent-answer-budget` | 2 / 1 | 3 / 2 | 1 / 1 | `Completed` | 否 |
| `cancel` | 1 / 0 | 3 / 1 | 0 / 0 | `Cancelled` | 否 |
| `cancel-before-start` | 0 / 0 | 2 / 1 | 0 / 0 | `Cancelled` | 否 |
| `gate-closed` | 1 / 0 | 3 / 1 | 0 / 0 | `Cancelled` | 否 |
| `forbidden-path` | 2 / 1 | 4 / 2 | 0 / 0 | `Denied` | 否 |
| `recursive` | 2 / 1 | 4 / 2 | 0 / 0 | `Denied` | 否 |
| `invalid-task` | 0 / 0 | 2 / 1 | 0 / 0 | `InvalidTask` | 否 |
| `oversized-result` | 2 / 1 | 4 / 2 | 1 / 1 | `OutputLimit` | 否 |
| `model-error` | 2 / 1 | 4 / 2 | 1 / 1 | `ModelError` | 否 |

<!-- r06-results:end -->

完整环境见 <a href="/learn-agent-rust/outputs/r06-environment.txt" download>R06 实验环境记录</a>，学习包内的 `evidence.json` 记录源码 SHA-256、每个场景的统计与输出校验值。验证范围是标准库、固定模型替身、临时文件和单个子线程；本章没有调用 HTTP 模型、`langchain-rust`、`graph-flow` 或数据库。

独立学习包还可以运行内置 Rust 测试：

```sh
rustc --edition=2024 -D warnings --test subagents.rs -o subagents-tests
./subagents-tests
```

9 个测试覆盖历史分离、取消与断连、丢弃所有者时的等待清理、连续子任务累计总账、额度拒绝时不误扣、子成功后的父额度检查、权限与递归拒绝、UTF-8 摘要字节上限，以及模型和文件失败。

维护者在网站仓库根目录执行：

```sh
python3 scripts/verify-agent-subagents.py
python3 scripts/generate-learn-agent-rust-figures.py --lesson R06
python3 scripts/verify-agent-subagents.py --check
```

验证器把源码复制到仓库外编译，运行 16 个场景、9 个 Rust 测试和 2 个错误参数用例，核对正文结果表、源码片段与输出。生成学习包后，再在另一目录独立解压，重新编译并复现正常与取消记录。

程序退出码 0 表示所选实验已经运行完毕；任务成功看目标断言。错误参数、编译失败等属于运行入口失败。跨进程恢复、任意时刻强制取消和真实模型的子任务质量还需要后续验证。

::: warning 常见误区
- **复制全部父历史再称为干净上下文。** 子任务输入要按目标明确选择；本章只传任务说明。
- **把上下文分离当成权限隔离。** 新消息向量只控制模型看见什么；同进程线程仍需执行前的工具检查。
- **只给每个子任务一份新预算。** 每个任务都有限额，也可能累计超出整个会话；总账要跨子任务保留。
- **把返回报告当成任务成功。** 报告可以说明预算、权限或模型错误；子成功后父侧仍可能缺少回答额度。
- **发出取消就立即删除工作区。** 子任务可能还持有资源，应先让它退出并等待，再检查清理结果。
- **把测试标记检查当作通用防泄漏机制。** 本章验证特定数据流；真实模型可能在摘要中复述内容，任务输入选择与返回内容策略仍需独立设计。
:::

## 本章结论

一次子任务拥有自己的输入、消息历史和局部用量。父侧将工作交出去，收回状态、摘要与用量，再把报告作为原委派调用的工具结果继续处理。子任务的中间历史留在宿主诊断中。

总预算、工具权限和取消控制属于应用运行时，贯穿父子执行。结束时等待线程退出并核对资源状态，才算完成本章的执行生命周期。

## 检查理解

1. 本章为什么同时保存 `ChildReport` 和 `ChildRun.history`？

   <details><summary>参考答案</summary>

   报告是父模型的输入契约，包含状态、可用摘要和用量；历史是宿主诊断数据。宿主能保留过程供排查，同时只把报告追加到父模型上下文。

   </details>

2. 正常路径为什么总共消耗 4 轮模型、2 次工具执行尝试？

   <details><summary>参考答案</summary>

   父模型提出委派、生成最终回答，共 2 轮；子模型提出读取、提取启动命令，共 2 轮。工具执行尝试包括父侧的 1 次委派和子侧的 1 次文件读取；真实文件读取只有 1 次。

   </details>

3. 子任务的局部额度充足，总模型额度不足时，能否继续调用？

   <details><summary>参考答案</summary>

   每次子调用要同时通过局部与总额度检查。总额度不足时返回 `GlobalModelBudget`，子用量不会增加。连续创建子任务仍引用同一总账，不会重新得到额度。

   </details>

4. `parent-answer-budget` 中子任务已完成，为什么练习目标为 `false`？

   <details><summary>参考答案</summary>

   子任务完成后，父会话已经收到报告，但生成最终回答需要第四轮模型。总额度只有 3，父侧在调用前停止，尚未向用户给出约定答案。

   </details>

5. 为什么 `ChildHandle::drop` 先关闭通道，再 `join`？

   <details><summary>参考答案</summary>

   子任务可能正阻塞在等待放行的 `recv()`。设置标记并关闭发送端会让等待结束，子侧返回取消并离开资源作用域；随后 `join` 才能等到它退出。仅丢弃普通线程句柄会让线程脱离句柄继续运行。

   </details>

6. 本章有没有验证取消能够中断任意文件读取或 HTTP 请求？

   <details><summary>参考答案</summary>

   验证发生在文件读取之前的确定控制点，靠协作检查取消标记。实际读取一旦开始，标记不能撤销它。慢工具和真实请求要有各自的超时、中断与资源关闭协议。

   </details>

## 参考资料

- [Learn Claude Code：s06 Subagent](https://learn.shareai.run/zh/s06/)：参考课程的独立历史、子工具范围与摘要回传；本站 Rust 实验另行验证预算和取消生命周期。
- [Rust Book：Using Threads](https://doc.rust-lang.org/book/ch16-01-threads.html)：线程创建、所有权与等待结束。
- [Rust 标准库：JoinHandle](https://doc.rust-lang.org/std/thread/struct.JoinHandle.html)：`join` 与丢弃句柄的行为。
- [Rust 标准库：sync_channel](https://doc.rust-lang.org/std/sync/mpsc/fn.sync_channel.html)：有界通道、阻塞与断开。
- [Rust Book：Shared-State Concurrency](https://doc.rust-lang.org/book/ch16-03-shared-state.html)：用 `Arc<Mutex<_>>` 共享并保护状态。
- [Rust 标准库：Drop](https://doc.rust-lang.org/std/ops/trait.Drop.html)：值离开作用域时的资源释放。

参考课程的[原始子 Agent 图](/learn-agent-rust/figures/upstream/r06-subagent-overview.svg)原样保留，图中的 Python/Claude 接口按原语境理解；来源与许可见[课程架构](./architecture.md#reference-assets)。正文中的 Rust 图由本站脚本生成。

下一章：[第 7 章：按需加载技能](./skill-loading.md)。子任务可以选择自己的输入，专业说明也可以按当前目标加载；下一章区分知识注入与执行权限。
