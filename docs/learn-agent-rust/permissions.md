---
title: "第 3 章：工具权限与审批"
description: "用 ADK-Rust 3.0 的工具策略与审批记录，区分允许、拒绝和等待批准，并验证批准只放行原来那一次调用。"
pageClass: learn-agent-rust-course
prev:
  text: 第 2 章 · 工具注册与图调度
  link: /learn-agent-rust/tools-and-graph
next:
  text: 第 4 章 · 生命周期与 Hooks
  link: /learn-agent-rust/hooks
---

# 第 3 章：工具权限与审批

[课程总览](./index.md) · [上一章](./tools-and-graph.md) · [学习路径](./learning-path.md) · [下一章](./hooks.md)

::: tip 本章学习目标
- 写一个应用自己的工具策略，把同一类请求分成允许、拒绝、等待批准三条路径。
- 观察等待批准时框架做了什么：调用被挂起、请求记进审批记录、本次运行结束，工具没有执行。
- 验证批准绑定的是原来那一次调用：参数变了不算、用过一次就失效、执行失败也不退回。

**前置：** 读过[第 1 章](./agent-loop.md)与[第 2 章](./tools-and-graph.md)，知道调用 ID、工具结果状态和 `Runner` 的作用；能读懂 trait 实现和 `match`。

**实践方式：** 下载 <a href="/learn-agent-rust/permissions.zip" download>本章 Rust 工程</a>，按[第 5 节](#hands-on)取一次 ADK-Rust 源码后运行。不需要模型密钥或数据库。
:::

::: info 本章已迁移到 ADK-Rust 3.0
本章实验基于 ADK-Rust 3.0 的发布候选版本（固定提交，尚未发布到 crates.io）。旧版本章用标准库手写了权限判断、等待与批准，可从 git 标签 `learn-agent-rust-v1` 取得。新版里，判断规则仍由应用写，挂起、记录与恢复交给框架。
:::

上一章的助手只读文件。现在让它多做一步：

> 读一下 README，把一句话摘要写进 notes/summary.txt。

读文件没什么风险；写文件不一样，写错了位置、写进了不该写的内容，都会留下后果。我们希望读直接放行，写摘要先问人，其他写入一律拒绝。先猜一个问题：程序打印出“等待批准”的时候，摘要文件已经存在了吗？

<LearnAgentRustMap active="permissions" />

<!-- experiment-library:start -->

全书实验可从[统一代码库](./experiments.md#permissions)下载；解压后进入 `chapters/permissions/`，或在代码库根目录运行 `python3 run.py run R03`。

<!-- experiment-library:end -->

## 1. 同一份请求，先走权限分支

模型提出的每一次工具调用，在执行之前都要先过策略这一关。策略回答三种之一：

| 请求 | 决定 | 之后发生什么 |
| --- | --- | --- |
| `read_file`，路径是 `README.md` | 允许 | 直接执行 |
| `write_summary`，路径是 `notes/summary.txt`，内容不超过 1024 字节 | 需要批准 | 调用被挂起，等人决定 |
| 其他已注册工具的请求（写 README、写到目录外、超长内容） | 拒绝 | 不执行，结果状态 `refused` |
| 未注册的工具（例如 `bash`） | 轮不到策略 | 框架先拦下，结果状态 `not_run` |

![模型的工具调用先交给应用的策略判断：读 README 直接执行，写摘要挂起等待批准，其余拒绝；挂起期间工具没有执行。](/learn-agent-rust/figures/r03-permission-routes.svg)

在 ADK-Rust 里，策略是任何实现了 `ToolPolicy` 的类型，只需实现一个方法 `evaluate`：给它一个请求（工具名、参数、执行的 Agent 等），它回答 `PolicyDecision::Allow`、`Deny` 或 `RequireApproval`。（trait 里另有带默认实现的 `evaluate_call` 等方法，受控路径实际调用的是 `evaluate_call`，默认转给 `evaluate`。）本章的策略：

<<< @/public/learn-agent-rust/code/permissions/src/main.rs#policy

几点值得注意：

- **策略只看请求，不做 I/O。** 它不读文件、不检查磁盘，只根据工具名和参数分类。这样它可以在任何动作发生之前运行，也容易测试。
- **默认拒绝是本章策略自己的选择。** 没有被明确允许或要求批准的请求，最后一个分支一律 `deny`。新加一个工具，如果忘了写规则，它就用不了，而不是没人管。注意框架本身不是这样：`Runner` 上不装策略时，所有工具调用都放行；框架自带的 `DeclarativePolicy` 才是“没匹配到规则就拒绝”。
- **路径按原样比较。** `notes/../README.md` 和 `notes/summary.txt` 不相等，会被拒绝；这里没有做路径规范化，靠的是“只接受一个确切的值”。

策略装在 `Runner` 上：

<<< @/public/learn-agent-rust/code/permissions/src/main.rs#wiring

每次工具调用都要经过框架的受控路径（`authorize_tool_call`），策略是其中一站；`LlmAgent` 在执行工具之前调用它。处理函数被调用时，已经通过了策略和审批两关，所以写摘要的处理函数只管写：

<<< @/public/learn-agent-rust/code/permissions/src/main.rs#tools

## 2. 等待批准时，框架做了什么

运行 `wait` 场景（准备步骤见[第 5 节](#hands-on)）：

```sh
cargo run --locked -- wait
```

<<< @/public/learn-agent-rust/outputs/r03-wait.txt

逐行看：

1. 读 README，允许，`status=ok`。
2. 模型请求写摘要，策略要求批准。框架没有执行工具，而是给这次调用一条 `status=held` 的结果，内容是“requires confirmation: 写入摘要需要人工批准”。
3. 接着出现一行文本 “Tool confirmation required…”。它不是模型说的，是框架在挂起后补的一条提示，随后本次运行结束。按 ADK-Rust 的说明，这条提示不会发给模型。
4. `pending …` 行来自审批记录：框架把完整请求（调用 ID、工具名、参数）记进了 `InMemoryApprovalStore`，等人来决定。

所以开头那个问题的答案是：没有。`write_attempts=0`，摘要文件不存在。等待不是结果，挂起的调用也不会在后台偷偷执行。

## 3. 批准之后，执行原来那次调用

`approve` 场景在 `wait` 之后，让审批人批准，再运行一次：

<<< @/public/learn-agent-rust/code/permissions/src/main.rs#approve

审批人从审批记录里取出等待中的请求，按请求的**指纹**记下决定。然后应用发起第二次运行，用户消息是空文本，意思是“只为处理等待中的调用而运行”：

<<< @/public/learn-agent-rust/outputs/r03-approve.txt

第二次运行开始时、调用模型之前，`LlmAgent` 先从会话里找出挂起的调用，到审批记录里查有没有决定。有批准，就执行原来那次调用：同一个调用 ID（`scripted_tc_1_0`）、同一份参数，结果 `status=ok`，然后才请求模型。模型没有被要求重新提出这次调用。

指纹由这几部分合成：执行的 Agent、工具的来源与声明、工具名、规范化后的参数。任何一项变了，指纹就变。**调用 ID 不在其中**：同一个 Agent 换一个调用 ID、用同样的参数再请求一次，指纹相同。恢复时执行的仍是原来那个调用 ID，那是因为框架恢复的是会话里挂起的那条调用，不是因为批准绑定了调用 ID。

![审批记录保存完整请求并合成指纹；决定按指纹记录，下一次运行取走决定后拒绝或执行原来那次调用；两条分支都用掉这次决定。](/learn-agent-rust/figures/r03-approval-binding.svg)

## 4. 批准绑定的是动作，而且只用一次

三个场景检验“批准”的边界。

**改了内容的批准不算数（`tamper`）。** 审批人批准的请求和等待中的不一样：内容被改成了“改过的摘要”。指纹对不上，这个决定放行不了等待中的调用：

```sh
cargo run --locked -- tamper
```

<<< @/public/learn-agent-rust/outputs/r03-tamper.txt

第二次运行里，挂起的调用还在等待（最后仍有一条 `pending`），工具没有执行；模型看到的仍是“需要确认”的结果。审批记录接受了这条决定，但它对应的是另一个指纹，不会被等待中的那次调用取走。

这里有一个容易忽略的后果：审批记录不要求决定对应一条等待中的请求，而框架在一次调用**第一次**需要批准时就会先查审批记录。所以这条多出来的批准会留在那里，变成一张预先批准：如果模型之后真的请求写入“改过的摘要”，它会直接执行，不再问任何人。审批界面只应对从 `pending()` 里取出的指纹做决定。

**一次批准，一次执行（`replay`）。** 批准、恢复、写入成功以后，第三次运行里模型又提出同一个写入。它的指纹和第一次相同，但那条决定在恢复时已经被取走，审批记录里没有可用的决定，于是又挂起等待：

<<< @/public/learn-agent-rust/outputs/r03-replay.txt

审批记录里的决定在恢复时已经被取走，所以 `write_successes=1`，又多了一条等待。

**执行失败，批准也不退回（`write-error`）。** 目标位置事先放了一个同名目录。批准以后执行，写入失败，`status=failed code=file.write_failed`；第三次运行再提出同一写入，又要等待。批准只说明“允许做”，不保证“做成了”；做失败了，重试需要新的批准。完整输出见[实验输出](/learn-agent-rust/outputs/r03-write-error.txt)。

还有拒绝：`decline` 场景审批人拒绝，恢复时这次调用得到 `refused` 结果（“execution denied by confirmation policy”），工具没有执行，模型可以据此换个做法。恢复的调用会重新走一遍完整的受控路径，包括再问一次策略；本章策略对同一请求的回答不变，所以只是又走到审批这一站。

## 5. 动手实验 {#hands-on}

下载并解压<a href="/learn-agent-rust/permissions.zip" download>本章工程</a>，先取一次 ADK-Rust 源码，再运行：

```sh
cd permissions
python3 fetch-adk-rust.py ../adk-rust    # 需要 git 与 GitHub 访问；不行时加 --method cdn
cargo run --locked                       # 默认 approve
cargo run --locked -- wait
cargo run --locked -- tamper
cargo run --locked -- replay
```

命令要在 `permissions` 目录里运行。编译时会看到 adk-core 的 3 条弃用警告（上游固定 Rust 1.95.0），不影响运行和检查。

![十个场景中，等待、拒绝和改了内容的批准都没有写入尝试；批准只写一次，再次提出同一写入又要等待；写入失败计一次尝试零次成功。](/learn-agent-rust/figures/r03-permission-results.svg)

| 场景 | 做了什么 | 写入尝试 / 成功 | 写入调用最后的状态 | 仍在等待 |
| --- | --- | --- | --- | --- |
| `read` | 只读 README | 0 / 0 | — | 0 |
| `deny` | 写 README.md | 0 / 0 | `refused` | 0 |
| `invalid-path` | 写 `../outside.txt` | 0 / 0 | `refused` | 0 |
| `unknown` | 调用不存在的 `bash` | 0 / 0 | `not_run` | 0 |
| `wait` | 写摘要，没人决定 | 0 / 0 | `held` | 1 |
| `approve` | 批准后恢复 | 1 / 1 | `ok` | 0 |
| `decline` | 拒绝后恢复 | 0 / 0 | `refused` | 0 |
| `tamper` | 批准了改过的请求 | 0 / 0 | `held` | 1 |
| `replay` | 批准、写入，再提出同一写入 | 1 / 1 | `held`（新的一次） | 1 |
| `write-error` | 批准，但写入失败，再提出同一写入 | 1 / 0 | `held`（新的一次） | 1 |

### 与旧版场景的对应

旧版本章的 10 个场景名称全部保留，但有几处含义变了：

| 场景 | 旧版 | 新版 | 说明 |
| --- | --- | --- | --- |
| `unknown` | 策略拒绝 | 框架先拦下，`not_run` | 不存在的工具在策略之前就被拦下（“Tool bash not found”），结果一样，没有执行任何动作。 |
| `wait` | 工具结果 1 条 | 2 条 | 新版把挂起的写入也算作一条结果（`held`）。 |
| `replay` | 同一个批准回复两次 | 批准用掉后，模型再提出同一写入 | 测的不是同一件事：旧版测“重复回复不重复执行”，新版测“决定取走即用掉”。 |
| 其他会话的审批不能混用 | 有单独的测试 | 删除 | 由框架提供：审批记录按会话范围（`ApprovalScope`：应用 / 用户 / 会话）分开存放。 |
| 超长内容 | 有场景覆盖 | 只在策略里保留规则 | 本章没有场景单独测试这条规则。 |

`approve`、`decline`、`deny`、`invalid-path`、`read`、`tamper`、`write-error` 含义不变。

网站维护者运行 `python3 scripts/verify-agent-permissions.py`：它打包章节、在临时目录解压并在旁边放好 `adk-rust/`，执行格式检查、Clippy 和 6 个 Rust 测试；10 个场景各连跑两次必须逐字节相同；逐个核对读写计数、等待数、写入调用的最后状态，以及恢复时执行的确实是原来那个调用 ID。加 `--check` 检查产物是否过期。

## 6. 谁持有哪份状态

| 状态 | 谁持有 | 本章放在哪里 |
| --- | --- | --- |
| 允许什么、拒绝什么 | 应用（`SummaryPolicy`） | 代码里的规则 |
| 挂起的调用 | 会话事件里那条 `held` 结果 | `InMemorySessionService` |
| 等待中的请求与决定 | 审批记录 | `InMemoryApprovalStore` |
| 审批人是谁、有没有资格批准 | 应用外层（界面、身份系统） | 本章没有实现，决定由程序直接写入 |
| 文件内容 | 工具与文件系统 | 程序自建的临时目录 |

审批记录和会话都只在内存里，进程退出就没了。ADK-Rust 提供 `SqliteApprovalStore`、`PostgresApprovalStore` 等持久版本，同一个决定可以跨进程、跨重启使用；跨进程挂起与恢复在[第 6 章](./graph-pause-resume.md)和[第 21 章](./human-in-the-loop.md)验证。

## 框架替你做了什么、没做什么

| 框架做了 | 仍归应用 |
| --- | --- |
| 装了策略时，每次工具调用都在执行前询问它；拒绝就不执行，结果 `refused`。 | 写策略：允许什么、拒绝什么、什么要批准；不装策略就全部放行。 |
| 需要批准时挂起调用、记录请求、结束本次运行，工具不执行。 | 把等待中的请求展示给有资格的人。 |
| 按指纹匹配决定：参数、Agent、工具来源变了都不算同一次；调用 ID 不参与。 | 确认审批人的身份和权限（本章没有实现）；只对等待中的请求做决定，避免留下预先批准。 |
| 下次运行开始时恢复有决定的调用，执行原来那次调用；决定取走即用掉。 | 决定执行失败后要不要重试，重试需要新的批准。 |
| 不存在的工具直接 `not_run`。 | 选择审批记录放在哪里，并验证跨进程恢复。 |

<!-- adk-refs:start -->

## 在 ADK-Rust 源码里

本章的策略、挂起与审批，在 ADK-Rust 里分布在这几处：

| 本章内容 | 源码位置 | 对照要点 |
| --- | --- | --- |
| 应用的策略接口 | [`adk-core/src/policy.rs` · `ToolPolicy`](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-core/src/policy.rs#L309-L375) | 只需实现 `evaluate`：给一个请求，回答允许、拒绝或需要批准；受控路径调用的 `evaluate_call` 默认转给它 |
| 三种决定 | [`adk-core/src/policy.rs` · `PolicyDecision`](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-core/src/policy.rs#L31-L44) | `Allow` / `Deny` / `RequireApproval`，后两种带理由 |
| 每次工具调用都经过的受控路径 | [`adk-core/src/governance.rs` · `authorize_tool_call`](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-core/src/governance.rs#L2286-L2605) | 熔断器在它之前；它内部依次检查总开关、同意、恢复绑定、出口、策略、护栏、确认（审批），没通过就不执行 |
| 请求的指纹 | [`adk-core/src/context.rs` · `ToolConfirmationRequest::fingerprint`](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-core/src/context.rs#L1385-L1413) | 由执行的 Agent、工具来源与声明、工具名和规范化参数合成；参数变了，指纹就变 |
| 审批记录的接口 | [`adk-core/src/governance.rs` · `ApprovalStore`](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-core/src/governance.rs#L1040-L1182) | 记下等待的请求、按指纹记录决定、取走决定（取走即用掉） |
| 找出等待中的调用 | [`adk-core/src/governance.rs` · `held_tool_calls`](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-core/src/governance.rs#L3536-L3538) | 每次运行开始时，从会话事件里找出挂起的调用，有决定的就恢复 |
| 需要批准时先查审批记录 | [`adk-core/src/governance.rs` · `resolve_confirmation`](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-core/src/governance.rs#L3135-L3255) | 调用第一次需要批准时就先取审批记录里的决定，所以预先写入的决定会直接生效 |

源码固定在 ADK-Rust `98515241133d`（3.0.0，2026-11-26，尚未发布到 crates.io）。本节由 `scripts/learn-agent-rust-adk-refs.py` 生成。

<!-- adk-refs:end -->

::: warning 常见误区
- 把“注册了这个工具”或“提示词里说要先问”当成权限控制。权限来自执行前的策略检查。
- 把调用 ID 当作凭证。审批按指纹绑定完整请求，调用 ID 不在指纹里，知道一个调用 ID 不等于能批准它。
- 对没有在等待的请求写下批准。框架第一次遇到需要批准的调用就会查审批记录，多出来的批准等于预先批准。
- 把等待当成成功。挂起的调用没有执行，摘要文件不存在。
- 把批准当成执行成功。`write-error` 里批准了，写入照样失败。
- 把固定的路径规则当成通用沙箱。本章只比较确切的路径字符串。
- 以为批准能反复用。决定被取走以后，同样的写入要重新批准。
:::

<!-- transfer-thinking:start -->

## 迁移思考：授权绑定的是动作

用户批准写 report.txt 后，模型把路径换成配置文件，批准还有效吗？先给出你的判断，再展开下面的推演。

<details><summary>推演与应用</summary>

把批准绑定到规范化路径、内容摘要与计划修订；任一关键字段变化都应重新判断。

付款、发邮件和发布内容同样需要批准具体对象与数量，而非一个泛化的“同意”。

</details>

这是一道迁移练习，推演不代表新增实验已通过。对照[全书审查中的证据层次](./course-review.md#evidence-layers)，说明你的判断还需要哪一级证据。

<!-- transfer-thinking:end -->

## 本章结论

同一份工具请求，在执行之前先由应用的策略分成三条路：允许、拒绝、等待批准。ADK-Rust 负责把策略放在每次调用的必经之路上，负责挂起、记录和恢复；应用负责写规则、展示请求、确认审批人。

批准绑定的是原来那一次调用：参数变了就不算，用过一次就失效，执行失败也不退回。下一章把“执行前检查、执行后记录、结束时收尾”放到清晰的扩展点里。

## 检查理解

1. 一次写摘要被批准了，为什么后面的写入不能沿用？

   <details><summary>参考答案</summary>

   决定按指纹记在审批记录里，恢复时被取走、用掉。后面的写入即使参数完全相同、指纹也相同，审批记录里已经没有可用的决定，所以要重新批准，`replay` 场景就是这样。如果想让一类写入长期放行，应该改策略，或者使用框架的常设批准（`RunConfig::tool_approvals`，在一次运行内覆盖所有指纹相同的调用），而不是复用一次批准。

   </details>

2. `wait` 场景有两条工具结果，为什么写入次数是 0？

   <details><summary>参考答案</summary>

   第一条是读 README 的结果；第二条是写摘要的 `held` 结果，它表示“这次调用在等待”，不是执行结果。工具没有被调用，所以写入尝试为 0，摘要文件不存在。

   </details>

3. 审批人批准了改过内容的请求，原来那次调用还能被批准吗？

   <details><summary>参考答案</summary>

   能。改过内容的请求指纹不同，那个决定放行不了原来的调用，原来的调用仍在等待（`tamper` 场景最后仍有一条 `pending`）。审批人可以再按原来的指纹批准或拒绝它。

   </details>

4. 写入失败以后，为什么同一个批准不能再用一次？

   <details><summary>参考答案</summary>

   决定在恢复时就被取走了，执行失败也不会退回。批准表示“允许做这一次”，不保证做成；做失败了要不要重试、重试是否安全，应由人重新判断，所以需要新的批准。

   </details>

5. 想让人第二天再批准，只保存一个 `approved = true` 够吗？

   <details><summary>参考答案</summary>

   不够。至少要保存：完整的请求（工具、参数）、它属于哪个会话和哪次调用、按什么策略要求批准、恢复时从哪里继续、审批人是谁。ADK-Rust 的审批记录保存了请求和指纹，会话里保存了挂起的调用；审批人的身份、策略版本仍要应用自己管。另外还要考虑“写入成功了、保存状态失败了”的窗口，见[专题 2](./side-effect-reliability.md)。

   </details>

## 参考资料

- <a href="/learn-agent-rust/code/permissions/README.md" download>本章工程 README（下载）</a>与[实际批准输出](/learn-agent-rust/outputs/r03-approve.txt)。
- ADK-Rust（固定提交）：[工具授权文档](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/docs/official_docs/security/tool-authorization.md)（策略、挂起与恢复、审批记录、指纹）。
- [Learn Claude Code：权限与审批](https://learn.shareai.run/zh/s03/)。下方保留原图作为对照，本章 Rust 实现与实验独立提供。

<details><summary>参考课程原图与来源</summary>

以下图片原样保留自参考课程，展示其 Python/Claude 教学实现。图中接口、编号和统计按原图理解，不作为 Rust 实验的验证结果。

![参考课程原图把工具请求、应用权限判断与人工审批分开表达。](/learn-agent-rust/figures/upstream/r03-permission-overview.svg)

图源：[参考章节](https://learn.shareai.run/zh/s03/) · [原图](https://learn.shareai.run/course-assets/s03_permission/permission-overview.svg)。关注请求与执行之间的决策位置，再对照本章的三条分支。

![参考课程原图展示权限检查管线，帮助定位执行前的判断步骤。](/learn-agent-rust/figures/upstream/r03-permission-pipeline.svg)

图源：[参考章节](https://learn.shareai.run/zh/s03/) · [原图](https://learn.shareai.run/course-assets/s03_permission/permission-pipeline.svg)。关注检查的先后关系，具体类型与规则以本章源码为准。

来源版本与许可见[课程架构中的参考资料说明](./architecture.md#reference-assets)。

</details>

下一章：[第 4 章 · 生命周期与 Hooks](./hooks.md)，把执行前检查、执行后记录与停止处理放到清晰的扩展点中。
