---
title: "第 4 章：生命周期与 Hooks"
description: "沿一次文件写入，把检查、记录与收尾挂到 ADK-Rust 3.0 的四个回调位置上，验证顺序、拦下、出错、超时与改写的后果。"
pageClass: learn-agent-rust-course
prev:
  text: 第 3 章 · 工具权限与审批
  link: /learn-agent-rust/permissions
next:
  text: 第 5 章 · 图状态、条件路由与有界循环
  link: /learn-agent-rust/graph-state-routing
---

# 第 4 章：生命周期与 Hooks

[课程总览](./index.md) · [上一章](./permissions.md) · [学习路径](./learning-path.md) · [下一章](./graph-state-routing.md)

::: tip 本章学习目标
- 找到一次工具调用经过的四个回调位置，知道它们和策略检查、工具执行的先后。
- 区分回调的三种返回：继续、给出内容（拦下或改写）、出错，以及每种返回在不同位置的后果。
- 验证执行前失败时调用不会执行，执行后失败时文件已经写入、结果被扣下，结束回调失败时运行以错误结束。

**前置：** 读过[第 3 章](./permissions.md)，知道策略在工具执行前检查；能读懂闭包、`Box<dyn Fn>` 和 `async`。

**实践方式：** 下载 <a href="/learn-agent-rust/hooks.zip" download>本章 Rust 工程</a>，按[第 7 节](#hands-on)取一次 ADK-Rust 源码后运行。不需要模型密钥或数据库。
:::

::: info 本章已迁移到 ADK-Rust 3.0
本章实验基于 ADK-Rust 3.0 的发布候选版本（固定提交，尚未发布到 crates.io）。旧版本章用标准库实现了自己的 Hook 机制，可从 git 标签 `learn-agent-rust-v1` 取得。换成框架的回调以后，有几条结论变了：执行前的回调在策略检查之前运行；执行后的回调出错时，真实结果会被扣下而不是原样交给模型；执行后的回调可以改写模型看到的结果；结束回调不是每条路径都会运行。下文逐条验证。
:::

上一章让写摘要先过策略。现在想在这条路上加几件“旁边的事”：收到请求时记一笔，执行前再做一道业务检查，执行后核对结果，结束时汇总。这些事不该写进工具本身，也不该写进策略。

先猜一个问题：写入已经成功了，执行后的检查回调却出错了。摘要文件还在吗？模型会看到什么？

<LearnAgentRustMap active="hooks" />

<!-- experiment-library:start -->

全书实验可从[统一代码库](./experiments.md#hooks)下载；解压后进入 `chapters/hooks/`，或在代码库根目录运行 `python3 run.py run R04`。

<!-- experiment-library:end -->

## 1. 沿一次写入找到四个位置

ADK-Rust 的 `LlmAgent` 提供八种回调，本章用其中四种，它们在一次写入里依次出现：

| 回调 | 什么时候运行 | 本章挂的回调 |
| --- | --- | --- |
| `before_agent` | Agent 开始处理这次输入之前 | `input-log`、`input-check` |
| `before_tool` | 每次工具调用、**策略检查之前** | `before-check`、`before-log` |
| `after_tool` | 工具执行之后（成功或失败），以及工具被 `before_tool` 回调拦下之后；策略拒绝、挂起等待、`before_tool` 回调出错时不运行 | `after-check`、`after-log` |
| `after_agent` | Agent 结束时：正常回答、转交、取消都会运行；以错误结束或有调用挂起等待时不运行 | `stop-log` |

另外四种是 `before_model`、`after_model`（模型调用前后）、`after_tool_full`（拿到工具参数和结果的执行后回调）和 `on_tool_error`（工具失败时）。

![四个位置依次是 before_agent、before_tool、策略检查与执行、after_tool、after_agent；同一位置的多个回调按注册顺序运行。](/learn-agent-rust/figures/r04-lifecycle-order.svg)

## 2. 回调能做什么：继续、给出内容、出错

四种回调的签名相同：拿到一个上下文（能读到会话、用户输入，在工具回调里还能读到工具名和参数），返回 `Result<Option<Content>>`。本章用一个函数生成所有回调，`Behavior` 决定它这次怎么返回：

<<< @/public/learn-agent-rust/code/hooks/src/main.rs#contracts

同一种返回，放在不同位置，后果不同：

| 返回 | `before_agent` | `before_tool` | `after_tool` | `after_agent` |
| --- | --- | --- | --- | --- |
| `Ok(None)` 继续 | 照常 | 照常 | 照常 | 照常 |
| `Ok(Some(内容))` | 替 Agent 回答，不调用模型 | 拦下：工具不执行，内容作为结果 | 改写：模型看到的结果被替换 | 追加一条最终回答 |
| `Err(…)` | 运行以错误结束 | 工具不执行（`not_run`），运行继续 | 结果扣下（`withheld`），运行继续 | 运行以错误结束 |

工具回调出错不会结束运行：框架把它变成这次调用的结果，交给模型。Agent 回调出错会结束运行。

## 3. 注册顺序，就是执行顺序

<<< @/public/learn-agent-rust/code/hooks/src/main.rs#registration

正常场景（准备步骤见[第 7 节](#hands-on)）：

```sh
cargo run --locked
```

<<< @/public/learn-agent-rust/outputs/r04-normal.txt

每个位置的回调按注册顺序运行，各运行一次。（如果还在 `Runner` 上装了插件，同一位置的插件回调先于 Agent 自己的回调运行；本章没有装插件。）同一位置里，只要有一个回调给出内容，后面的同类回调就不再运行：`pre-block` 场景里 `before-check` 拦下了写入，`before-log` 就没有出现。拦下的内容成为这次调用的结果（`status=not_run`），工具没有执行。

### 权限仍来自策略

<<< @/public/learn-agent-rust/code/hooks/src/main.rs#policy

注意顺序：`before_tool` 回调在策略检查**之前**运行。`permission-deny` 场景里，模型要写 README.md，两个 `before_tool` 回调都放行了，随后策略拒绝，结果 `refused`，写入次数为 0：

<<< @/public/learn-agent-rust/outputs/r04-permission-deny.txt

这说明两件事。第一，回调能拦下调用，但放不行被策略拒绝的调用：权限只来自策略。第二，执行前的日志回调会记下最后被拒绝的调用，日志里“出现过”不等于“执行过”。被策略拒绝的调用也不会触发 `after_tool`。要留下拒绝记录，可以给 `Runner` 配审计日志（`audit_log`）：框架会为每次拒绝写一条带策略引用和理由的审计记录；不配审计时，要在策略或结束回调里自己记。

反过来也要小心：`before_tool` 回调如果返回一个工具结果形式的内容，这个结果会保留它自己写的状态，模型可能看到一个“成功”的结果，而工具根本没有执行，也没有经过策略。这不会让动作发生，但能让模型误以为动作发生了，所以执行前的回调同样需要审查。

## 4. 执行前失败：失败即关闭

`before-check` 出错、panic、超时，三个场景的结果相同：工具不执行，结果 `not_run`，运行继续，模型看到“before-tool callback failed”。

```sh
cargo run --locked -- pre-timeout
```

<<< @/public/learn-agent-rust/outputs/r04-pre-timeout.txt

一个坏掉的检查回调不会让本该被检查的动作溜过去，这叫“失败即关闭”。panic 也一样：框架接住 `before_tool` 回调里的 panic，变成 `callback.panicked` 错误（`pre-panic` 场景会在标准错误输出打印一条 panic 信息，那是故意制造的）。注意只有 `before_tool` 回调有这层保护；`after_tool`、`before_agent`、`after_agent` 回调里的 panic，框架不接。出错以后，后面的 `before-log` 和全部 `after_tool` 回调都不运行。

框架不给回调限时。`pre-timeout` 的回调自己用 `tokio::time::timeout` 设了 40 毫秒上限，超时就返回错误，交给框架按“出错”处理。

## 5. 执行后失败：文件已经写了

回到开头的问题。`post-error` 场景里写入成功，`after-check` 出错：

```sh
cargo run --locked -- post-error
```

<<< @/public/learn-agent-rust/outputs/r04-post-error.txt

摘要文件已经写进去了（`summary_written=true`），执行后的回调撤不回已经发生的事。但模型看不到真实结果：这次调用的状态是 `withheld`，模型被告知“工具运行了，但执行后的处理失败了，结果被扣下，不要再调用它”；后面的 `after-log` 也不再运行。任务算失败（`task_ok=false`）。

这一点和旧版本章相反：旧版保留真实结果、另记一笔回调失败；ADK-Rust 选择扣下结果。框架的文档和源码都写了理由：执行后的回调可能是脱敏或筛查的一环，它没有完成，后面的环节就可能拿到未经筛查的结果，所以一处失败就结束整条执行后流水线并扣下结果（[工具授权文档第 10 步](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/docs/official_docs/security/tool-authorization.md)）。动作已经发生、模型却不知道结果，后续要靠应用自己核对（例如重新读取文件），而不是让模型再做一次。

**执行后的回调可以改写结果。** `post-rewrite` 场景里，`after-check` 返回了一段内容，模型看到的结果变成了它，真实的 `{"written": …}` 没有交给模型：

<<< @/public/learn-agent-rust/outputs/r04-post-rewrite.txt

这是过滤和脱敏的正当用法，也意味着执行后的回调和策略一样需要审查：它能决定模型看到什么。顺带一提，轨迹和表格里的 `ok` 是轨迹片段在结果没有状态注解时写的标签，不是框架给的状态；被改写的结果没有注解，所以即使改写的是一次失败，这里也会显示 `ok`。

**工具失败时，执行后的回调照常运行。** `tool-error` 场景里目标位置是一个目录，写入失败（`failed`），两个 `after_tool` 回调都运行了。

### 结束回调：不是每条路径都运行

| 场景 | 发生了什么 | `stop-log` | 停止原因 |
| --- | --- | --- | --- |
| `stop-error` | 回答已经发出，结束回调出错 | 运行，出错 | `hook.failed` |
| `stop-timeout` | 结束回调超时 | 运行，超时 | `hook.timeout` |
| `stop-rewrite` | 结束回调返回内容，多出一条最终回答 | 运行 | `final_answer` |
| `prompt-block` | 输入回调拦下，替 Agent 回答 | 运行 | `final_answer` |
| `prompt-error` | 输入回调出错 | **不运行** | `hook.failed` |

结束回调出错时，最终回答已经发给了调用方，运行却以错误结束：调用方会先看到回答，再看到错误。`prompt-error` 说明结束回调不是“每条路径都会经过”：这里是 `before_agent` 回调出错，Agent 以错误结束，`after_agent` 不运行。调用被挂起等待审批时它也要等到恢复的那次运行才执行。（转交给别的 Agent、被取消时它会运行；调用方中途丢弃事件流时也会运行，但它返回的内容会被丢掉。）所以，必须释放的资源不能只靠结束回调。

![一次工具调用依次经过 before_tool 回调、策略检查、执行、after_tool 回调；每一站失败的后果不同。](/learn-agent-rust/figures/r04-tool-pipeline.svg)

## 6. 超时之后，回调真的停了吗？

`tokio::time::timeout` 只在 `.await` 的地方生效：回调卡在一个 `await` 上（等网络、等锁），超时后这个 future 被丢弃，回调停下。如果回调做的是阻塞线程的同步计算，或者调用了阻塞的系统接口，超时就打断不了它，整个运行会跟着卡住。

所以，对不可信或可能卡死的代码，回调里只做“发起和等待”，真正的工作放到单独的进程里：等待超时就结束并回收那个进程，再返回错误。旧版本章（git 标签 `learn-agent-rust-v1`）用子进程做过这个实验：超时后先 `kill` 再 `wait`，确认子进程已经回收才报告超时。本章不重复这部分。

## 7. 动手实验 {#hands-on}

下载并解压<a href="/learn-agent-rust/hooks.zip" download>本章工程</a>，先取一次 ADK-Rust 源码，再运行：

```sh
cd hooks
python3 fetch-adk-rust.py ../adk-rust    # 需要 git 与 GitHub 访问；不行时加 --method cdn
cargo run --locked                       # normal
cargo run --locked -- pre-timeout
cargo run --locked -- post-error
cargo run --locked -- stop-error
```

命令要在 `hooks` 目录里运行。编译时会看到 adk-core 的 3 条弃用警告（上游固定 Rust 1.95.0），不影响运行和检查。

![九个代表场景中，执行前拦下和超时都没有写入；执行后回调出错时文件已写入但结果被扣下；结束回调出错时运行以错误结束。](/learn-agent-rust/figures/r04-failure-results.svg)

| 场景 | 写入尝试 / 成功 | 结果状态 | 停止原因 | 任务通过 |
| --- | --- | --- | --- | --- |
| `normal` | 1 / 1 | `ok` | `final_answer` | 是 |
| `prompt-block` | 0 / 0 | — | `final_answer` | 否 |
| `prompt-error` | 0 / 0 | — | `hook.failed` | 否 |
| `permission-deny` | 0 / 0 | `refused` | `final_answer` | 否 |
| `pre-block` | 0 / 0 | `not_run` | `final_answer` | 否 |
| `pre-error` / `pre-panic` / `pre-timeout` | 0 / 0 | `not_run` | `final_answer` | 否 |
| `post-error` / `post-timeout` | 1 / 1 | `withheld` | `final_answer` | 否 |
| `post-rewrite` | 1 / 1 | `ok`（内容被改写） | `final_answer` | 是 |
| `tool-error` | 1 / 0 | `failed` | `final_answer` | 否 |
| `stop-error` / `stop-timeout` | 1 / 1 | `ok` | `hook.failed` / `hook.timeout` | 否 |
| `stop-rewrite` | 1 / 1 | `ok` | `final_answer` | 是 |

脚本模型每次都说“摘要已写入”，不管实际发生了什么，所以任务是否通过由程序判断：摘要真的写进去了、得到了最终回答、没有回调失败。

### 与旧版场景的对应

旧版有 14 个场景、8 个测试，新版 15 个场景、7 个测试：

| 旧版场景 | 新版 | 说明 |
| --- | --- | --- |
| `post-block`、`stop-block` | 删除 | 旧版规定“执行后、结束时的回调不能拦下”，返回内容算违规；ADK-Rust 里这两个位置返回内容是合法的改写，所以换成 `post-rewrite`、`stop-rewrite`。 |
| — | 新增 `prompt-error` | 验证 `before_agent` 出错时 `after_agent` 不运行。 |
| `pre-panic` | 保留，机制变了 | 旧版是真实崩溃的子进程；新版是回调里的 panic，被框架的 `guard_callback` 接住。 |
| `pre-timeout`、`post-timeout`、`stop-timeout` | 保留，机制变了 | 旧版超时后结束并回收子进程；新版回调用 `tokio::time::timeout` 自己限时，框架不限时。子进程隔离见第 6 节。 |
| “结束回调只执行一次” | 不再成立 | 旧版保证每次运行结束回调恰好执行一次；ADK-Rust 在出错或挂起时不运行它（见上表）。 |

其余场景（`normal`、`permission-deny`、`prompt-block`、`pre-block`、`pre-error`、`post-error`、`stop-error`、`tool-error`）名称和用意保留，结论按 ADK-Rust 的行为重新核对。

网站维护者运行 `python3 scripts/verify-agent-hooks.py`：它打包章节、在临时目录解压并在旁边放好 `adk-rust/`，执行格式检查、Clippy 和 7 个 Rust 测试；15 个场景各连跑两次输出必须逐字节相同；逐个核对计数、结果状态、停止原因，以及哪些回调必须出现、哪些不能出现；正常场景还核对完整的回调顺序。加 `--check` 检查产物是否过期。

## 框架替你做了什么、没做什么

| 框架做了 | 仍归应用 |
| --- | --- |
| 在四个位置按注册顺序调用回调；有一个给出内容，后面的同类回调不再运行。 | 决定每个位置挂什么、按什么顺序。 |
| 工具前回调出错或 panic 时不执行工具（失败即关闭）。 | 让检查回调本身可靠；给回调设时间上限。 |
| 工具后回调出错时扣下结果，告诉模型不要再调用。 | 核对已经发生的动作（结果被扣下，文件可能已经写了）。 |
| 策略检查始终在执行前运行，回调放行不了被拒绝的调用。 | 不要把权限写进回调。 |
| 配置了审计日志时，为每次拒绝写一条审计记录（策略引用与理由）。 | 不配审计时，自己在策略或结束回调里记录拒绝。 |
| 接住 `before_tool` 回调里的 panic。 | 其他回调里的 panic 框架不接，回调要自己保证不 panic。 |
| — | 必须释放的资源不能只靠结束回调；隔离会卡死的代码要用单独进程。 |

<!-- adk-refs:start -->

## 在 ADK-Rust 源码里

本章观察到的回调顺序与失败后果，在 ADK-Rust 里分布在这几处：

| 本章内容 | 源码位置 | 对照要点 |
| --- | --- | --- |
| 工具前回调的签名 | [`adk-core/src/callbacks.rs` 第 129 行](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-core/src/callbacks.rs#L129) | 返回 `None` 继续，返回内容表示拦下并用它代替结果，返回错误表示回调自己失败 |
| Agent 结束回调的签名 | [`adk-core/src/callbacks.rs` 第 69 行](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-core/src/callbacks.rs#L69) | 返回内容会追加一条最终回答；返回错误会让运行以错误结束 |
| 注册工具前回调 | [`adk-agent/src/llm_agent.rs` · `LlmAgentBuilder::before_tool_callback`](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-agent/src/llm_agent.rs#L1645-L1648) | 可以注册多个，按注册顺序运行；有一个给出内容，后面的同类回调就不再运行 |
| 回调 panic 的处理 | [`adk-core/src/callbacks.rs` · `guard_callback`](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-core/src/callbacks.rs#L35-L57) | 把 panic 变成 `callback.panicked` 错误；只有工具前回调经过它，其他回调里的 panic 框架不接 |
| 执行后流水线失败时交给模型的结果 | [`adk-core/src/tool_response.rs` 第 414 行](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-core/src/tool_response.rs#L414) | 结果被扣下（withheld），并告诉模型不要再调用这个工具 |
| 工具调用的受控路径 | [`adk-core/src/governance.rs` · `authorize_tool_call`](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-core/src/governance.rs#L2286-L2605) | 策略、护栏、审批在这里依次检查；它在工具前回调之后运行 |

源码固定在 ADK-Rust `98515241133d`（3.0.0，2026-11-26，尚未发布到 crates.io）。本节由 `scripts/learn-agent-rust-adk-refs.py` 生成。

<!-- adk-refs:end -->

::: warning 常见误区
- 把回调当作权限来源。回调能拦下，不能放行；权限来自策略。但执行前的回调能伪造一个“成功”的结果给模型看，它本身也要审查。
- 以为每个回调都会运行。同一位置有一个给出内容或出错，后面的就不运行；Agent 出错时结束回调也不运行。
- 以为执行后的回调失败会保留真实结果。ADK-Rust 会扣下结果，模型看到的是 `withheld`。
- 忘了执行后的回调能改写模型看到的结果，它需要和策略一样被审查。
- 以为 `tokio::time::timeout` 能停下任何代码。它只在 `.await` 处生效。
- 把结束回调当作目标完成。是否完成任务要单独判断，继续执行的策略见[专题 5](./workflow-and-goal-control.md)。
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

在 ADK-Rust 里，这道题多了一层：执行后的日志回调出错，框架会把结果扣下，模型不知道写入成功了。如果模型或应用据此“重跑整轮”，非幂等的写入就会再做一次。所以日志、审计这类观察回调，要么保证不出错（出错时自己吞掉并另行报告），要么放到不影响结果的位置。

## 本章结论

ADK-Rust 在一次工具调用的路上留了几个回调位置：Agent 开始前、工具执行前、工具执行后、Agent 结束时。同一位置的回调按注册顺序运行，返回值决定后果：继续、拦下或改写、出错。

执行前出错时调用不执行，执行后出错时动作已经发生、结果被扣下，结束回调出错时运行以错误结束，Agent 本身出错时结束回调不运行。权限始终来自策略。下一章离开单个 Agent，学习用图组织多个步骤。

## 检查理解

1. `before-check` 拦下了写入，`before-log` 还会运行吗？

   <details><summary>参考答案</summary>

   不会。同一位置里有一个回调给出内容，后面的同类回调就不再运行。想记录“被拦下”，可以在拦下它的回调里记，或者在执行后、结束时的回调里记（`pre-block` 场景里 `after_tool` 回调仍然运行）。

   </details>

2. 一个回调都不注册，模型要写 README.md，能写进去吗？

   <details><summary>参考答案</summary>

   不能。权限来自策略：`WritePolicy` 只允许写 `notes/summary.txt`，策略检查在每次工具调用执行前都会运行，和有没有回调无关。

   </details>

3. 写入成功后 `after-check` 超时了，文件、模型看到的结果、任务结果分别是什么？

   <details><summary>参考答案</summary>

   文件已经写入；模型看到的是 `withheld`，被告知结果被扣下、不要再调用；任务未通过（有回调失败）。应用要自己核对文件，而不是让模型再写一次。

   </details>

4. 回调里用了 `tokio::time::timeout`，为什么还说它不一定能停下回调？

   <details><summary>参考答案</summary>

   它只在 `.await` 处取消 future。回调如果在做阻塞线程的同步工作，超时到了也打断不了，运行会一直卡住。对这种代码，要放到单独的进程里，超时后结束并回收进程。

   </details>

5. 结束回调能不能用来保证“每次运行结束都释放资源”？

   <details><summary>参考答案</summary>

   不能完全保证。Agent 以错误结束时 `after_agent` 不运行（`prompt-error`），调用被挂起等待审批时它也要等恢复后才运行。必须释放的资源应该用 Rust 的作用域（`Drop`）或外层的清理逻辑来保证。

   </details>

## 参考资料

- <a href="/learn-agent-rust/code/hooks/README.md" download>本章工程 README（下载）</a>与[正常场景输出](/learn-agent-rust/outputs/r04-normal.txt)。
- ADK-Rust（固定提交）：[回调文档](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/docs/official_docs/callbacks/callbacks.md)、[工具授权文档中的检查顺序](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/docs/official_docs/security/tool-authorization.md#combining-mechanisms)、[插件](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/docs/official_docs/core/plugins.md)。
- [Tokio：time::timeout](https://docs.rs/tokio/latest/tokio/time/fn.timeout.html)。
- [Learn Claude Code：Hooks](https://learn.shareai.run/zh/s04/)。

<details><summary>参考课程原图与来源</summary>

![参考课程原图展示围绕模型与工具轮次设置的生命周期扩展位置。](/learn-agent-rust/figures/upstream/r04-hooks-overview.svg)

图源：[参考章节](https://learn.shareai.run/zh/s04/) · [原图](https://learn.shareai.run/course-assets/s04_hooks/hooks-overview.svg)。先关注扩展点的位置，再对照本章实验里的顺序和失败规则。来源版本与许可见[课程架构中的参考资料说明](./architecture.md#reference-assets)。

</details>

下一章：[第 5 章 · 图状态、条件路由与有界循环](./graph-state-routing.md)。
