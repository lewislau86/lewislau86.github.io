---
title: "第 6 章：图暂停、检查点与恢复"
description: "用 adk-graph 的动态暂停与 SQLite 检查点，让升级审批跨进程等待与恢复；验证暂停 ID 绑定、答案格式、写入冲突、图版本与损坏检查点。"
pageClass: learn-agent-rust-course
prev:
  text: 第 5 章 · 图状态、条件路由与有界循环
  link: /learn-agent-rust/graph-state-routing
next:
  text: 第 7 章 · 图并行、归并与子图
  link: /learn-agent-rust/graph-parallel-subgraphs
---

# 第 6 章：图暂停、检查点与恢复

[课程总览](./index.md) · [上一章](./graph-state-routing.md) · [图编排导读](./graph-orchestration.md) · [下一章](./graph-parallel-subgraphs.md)

::: tip 本章学习目标
- 解释一个节点暂停以后，状态存在哪里、下次从哪里继续、哪些节点会再运行一次。
- 用 SQLite 检查点让审批跨进程等待，用暂停 ID 和答案格式约束“回答的是哪一次、回答了什么”。
- 验证写入冲突、旧答案、图版本变化和损坏检查点各自怎样被拒绝。

**前置：** [图状态与路由](./graph-state-routing.md)、[工具权限与审批](./permissions.md)。

**实践方式：** <a href="/learn-agent-rust/graph-pause-resume.zip" download>下载独立工程</a>，按[第 5 节](#hands-on)取一次 ADK-Rust 源码后运行。SQLite 随依赖编译，需要 C 编译工具；无需模型或数据库服务。
:::

::: info 本章已迁移到 ADK-Rust 3.0
本章实验基于 ADK-Rust 3.0 发布候选版的 adk-graph（固定提交，尚未发布到 crates.io）。旧版本章用 graph-flow 自己实现了 SQLite 会话存储与版本检查，可从 git 标签 `learn-agent-rust-v1` 取得。新版的检查点、冲突检测和暂停 ID 由框架提供，图版本检查仍由宿主负责，第 7 节的对应表列出了变化。
:::

升级报告进入批准环节，但审批人明天才回复。今天的进程退出以后，明天的新进程至少要知道三件事：正在批准哪一版提案、当前停在哪里、此前哪些步骤已经完成。

本章沿用升级审查。我们把“等待”变成保存下来的检查点，再逐项验证恢复入口。实验标识 G02 用于命令定位，章节顺序由课程清单决定。

<LearnAgentRustMap active="graph-pause-resume" />

<!-- experiment-library:start -->

全书实验可从[统一代码库](./experiments.md#graph-pause-resume)下载；解压后进入 `chapters/graph-pause-resume/`，或运行 `python3 run.py run G02`。

<!-- experiment-library:end -->

## 1. 先区分线程、图和检查点

| 概念 | 是什么 | 本章里 |
| --- | --- | --- |
| 线程（thread） | 一次审查的身份，检查点按它保存 | `review-42` |
| 图 | 节点、边和通道的定义，每个进程重新编译一份 | `draft → approve → render / reject` |
| 检查点 | 每个超步结束时保存的状态、步号和**待运行节点** | SQLite 文件里的 `graph_checkpoints` 表 |

检查点默认在每个超步应用完更新之后、下一步开始之前保存（`Durability::Sync`；也可以改成后台保存或只在运行退出时保存）。所以恢复时，已经保存过的步骤不会再运行。还没保存的那一步分两种情况：进程在保存之前崩溃，整步重跑；某个节点报错，同一步里已经完成的节点结果会作为待写入保存下来，恢复时只重跑失败的节点（[第 7 章](./graph-parallel-subgraphs.md)验证）。无论哪种，一个节点都可能运行不止一次，这是“至少一次”的执行保证：有外部效果的节点要自己做到幂等，[专题 2](./side-effect-reliability.md)专门讨论这件事。

## 2. 暂停意味着以后重新运行这个节点

<<< @/public/learn-agent-rust/code/graph-pause-resume/src/main.rs#graph

`approve` 节点没有收到回答时，返回 `NodeOutput::interrupt_with_data`：一条问题、待批准的提案，以及答案必须满足的 JSON Schema。框架把这次暂停记进检查点，`invoke` 以 `GraphError::Interrupted` 返回，里面带着暂停 ID。

恢复时，框架**重新运行** `approve`，这一次 `ctx.resume_value()` 里有回答，节点据此用 `with_goto` 走向 `render`、`reject` 或回到 `draft`。所以暂停节点必须能被重复进入：在没有回答时只提问，不做任何外部动作。实验里每个节点真正执行一次就在 `runs.log` 里记一行，用来核对这一点。

暂停 ID 由框架按线程、步号、节点、问题、数据和答案格式计算。同一个暂停在没有回答的情况下重新进入，ID 不变；提案改了一版再暂停，就是新的 ID。

## 3. 每条命令都是一个新进程

![进程 A 运行到 approve 暂停并保存 SQLite 检查点，进程 B 按暂停 ID 回答，宿主先核对图版本，框架校验答案后重新运行 approve。](/learn-agent-rust/figures/g02-resume-boundary.svg)

两个进程之间只通过检查点交换信息：进程 A 退出时，内存里什么都不留下；进程 B 能继续，靠的是检查点里的状态、待运行节点和那次暂停的记录。

<<< @/public/learn-agent-rust/code/graph-pause-resume/src/main.rs#commands

每条命令都重新打开 SQLite 文件、重新编译图，然后 `invoke`。`answer` 用 `strict_resume()` 加 `with_resume_value(暂停ID, 回答)`：严格恢复只接受“正在等待的那个暂停”的 ID，按节点名回答、或者回答一个已经过去的暂停，都会被拒绝（`ResumeRejected`），检查点不变。

## 4. 宿主恢复前还要检查什么

框架会检查答案是否符合格式、暂停 ID 是否仍有效、两个写入者是否冲突；但它不检查“保存检查点的图”和“现在用来恢复的图”是不是同一版。这一项由宿主做：

<<< @/public/learn-agent-rust/code/graph-pause-resume/src/main.rs#resume

`init` 把 `graph_version` 写进状态，之后每次恢复先读出来比较，不一致就不运行任何节点。

## 5. 用多个真实进程走完一次审批 {#hands-on}

下载并解压<a href="/learn-agent-rust/graph-pause-resume.zip" download>本章工程</a>，先取一次 ADK-Rust 源码再编译：

```sh
cd graph-pause-resume
python3 fetch-adk-rust.py ../adk-rust    # 需要 git 与 GitHub 访问；不行时加 --method cdn
cargo build --locked
B=${CARGO_TARGET_DIR:-target}/debug/graph-resume-lab
mkdir -p /tmp/g02                         # SQLite 不会自动建目录
$B /tmp/g02/review.db init                # 打印暂停 ID
$B /tmp/g02/review.db show
$B /tmp/g02/review.db answer <init 打印的暂停 ID> approve
$B /tmp/g02/review.db show
```

重跑之前先删掉 `/tmp/g02/` 里的 `review.db` 和 `runs.log`，否则会接着旧线程继续。其余命令见工程 README。网站的验证脚本按同样的顺序运行独立进程，下面是它保存的输出（`DB` 是临时目录里的数据库文件）：

<<< @/public/learn-agent-rust/outputs/g02-approved.txt

逐条读：

1. `init` 运行 `draft`，在 `approve` 暂停，打印暂停 ID。进程退出，状态只在 SQLite 里。
2. `show` 是另一个进程：它重新进入 `approve`，没有回答，于是以同一个 ID 再次暂停。`approve` 又运行了一次（`approve=2`），`draft` 没有再跑。
3. `answer … approve` 恢复：`approve` 第三次运行，这次带着回答，走向 `render`，生成报告，运行结束。
4. 对已经完成的线程再 `show`，框架直接返回最终状态，不再运行任何节点（计数不变）。
5. 再用同一个 ID 回答一次：这个暂停已经被回答过，严格恢复拒绝它。

拒绝路径：

<<< @/public/learn-agent-rust/outputs/g02-rejected.txt

## 6. 先预测恢复失败，再运行拒绝路径

**提案改了，旧的批准不算数（`revised`）。** 审批人要求修改，`draft` 生成第 2 版提案，`approve` 以新的 ID 暂停。这时用第 1 版的 ID 回答“批准”，被拒绝：

<<< @/public/learn-agent-rust/outputs/g02-revised.txt

旧 ID 被拒绝，是因为它已经不是“正在等待的暂停”：严格恢复只接受当前挂起的那个 ID。新暂停的 ID 不同，是因为参与计算的步号和数据（提案、版本号）都变了。合起来，“批准”只能落在审批人看到的那一版提案上。

**答案格式不对，或者按节点名回答（`loose`）。** 回答 `maybe` 不在答案格式允许的范围里，在任何节点运行之前就被拒绝。最后一条命令不用暂停 ID，而是按节点名 `approve` 回答（非严格恢复）：

<<< @/public/learn-agent-rust/outputs/g02-loose.txt

它批准了第 2 版提案。如果审批人只看过第 1 版，这就是一次没看过内容的批准。按节点名回答分辨不出是哪一次暂停，需要绑定时要用暂停 ID 加严格恢复。

**两个写入者同时恢复（`conflict`）。** 同一个进程里的两张图对象共用一个 SQLite 文件，同时用同一个答案恢复同一个暂停：

<<< @/public/learn-agent-rust/outputs/g02-conflict.txt

两个写入者都重新运行了 `approve`（`approve=3`），但保存检查点时，检查点的版本号必须比已存的大，第二个写入者因此得到 `CheckpointConflict`，没有走到 `render`（`render=1`）。冲突检测阻止了旧快照覆盖新快照，但它发生在**保存**时：如果两个写入者在保存之前都做了外部动作，冲突检测撤销不了已经发出的请求。

**图换了版本，或者检查点损坏了（`tampered`）。**

<<< @/public/learn-agent-rust/outputs/g02-tampered.txt

- `tamper rename` 用一张把 `approve` 改名为 `approve_v2` 的新图恢复。宿主的版本检查发现不一致，拒绝运行。
- `tamper rename-unchecked` 去掉版本检查再试：框架照常运行新图，检查点里等待的节点在新图里不存在，于是没有节点可跑，运行“正常完成”，`outcome=none`。没有任何报错，审批就这样消失了。这正是宿主必须检查图版本的原因。
- `tamper corrupt` 把检查点的状态改成无法解析的内容，恢复以读取错误结束，不会带着坏数据继续。

## 7. 与旧版场景的对应

| 旧版（graph-flow + 自写 SQLite 存储） | 新版（adk-graph） | 说明 |
| --- | --- | --- |
| `approved`：宿主逐步推进，`WaitForInput` 停在审批节点 | `approved` | 一次 `invoke` 跑到暂停或结束；审批节点同样会被重新进入。 |
| `denied` | `rejected` | 保留。 |
| 旧修订的批准被拒绝（应用比较 revision 字段） | `revised` | 改由暂停 ID 加严格恢复提供。 |
| 重复决定被拒绝 | `approved` 的第 5 步 | 改由严格恢复提供。 |
| `conflict`：应用自己的版本比较 | `conflict` | 由检查点的版本规则提供（`CheckpointConflict`）。 |
| 无效快照：图版本、状态 schema、未知游标、行版本、损坏 JSON | `tampered`：图版本（宿主检查）、损坏检查点 | 行版本由框架管理；未知游标在新版表现为“新图里没有这个待运行节点”，被宿主的版本检查拦下。 |
| — | `loose` | 新增：答案格式检查与“按节点名回答”的风险。 |

## 框架替你做了什么、没做什么

| 框架做了 | 仍归应用 |
| --- | --- |
| 每个超步结束时保存检查点：状态、步号、待运行节点。 | 选持久的检查点存储，并让所有进程读同一份。 |
| 暂停、记录暂停 ID，恢复时重新运行暂停的节点并交给它回答。 | 让暂停节点可重复进入：没回答时只提问，不做外部动作。 |
| 严格恢复只认正在等待的暂停 ID；答案按 JSON Schema 校验。 | 用暂停 ID 回答，不用节点名；确认审批人的身份。 |
| 两个写入者保存时版本冲突，后者失败。 | 外部动作发生在保存之前时，自己保证幂等或单一执行者。 |
| 已完成的线程再次运行直接返回最终状态。 | 检查图版本：框架不检查保存检查点的图和恢复它的图是否相同。 |

<!-- adk-refs:start -->

## 在 ADK-Rust 源码里

本章的暂停、检查点与严格恢复，在 adk-graph 里分布在这几处：

| 本章内容 | 源码位置 | 对照要点 |
| --- | --- | --- |
| 节点请求暂停 | [`adk-graph/src/node.rs` · `NodeOutput::interrupt_with_data`](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-graph/src/node.rs#L576-L578) | 带上给审批人看的数据；`with_response_schema` 再声明答案格式 |
| 暂停 ID 怎样算出 | [`adk-graph/src/interrupt.rs` · `interrupt_id`](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-graph/src/interrupt.rs#L121-L134) | 线程、步号、节点、问题、数据、答案格式一起取哈希：同一个问题 ID 不变，问题变了 ID 就变 |
| 严格恢复 | [`adk-graph/src/node.rs` · `ExecutionConfig::strict_resume`](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-graph/src/node.rs#L227-L230) | 只接受按暂停 ID 给出的回答，不接受按节点名回答 |
| 恢复前核对回答 | [`adk-graph/src/executor.rs` · `check_resume_answers`](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-graph/src/executor.rs#L1927-L1979) | ID 对不上或答案不符合格式，报 `ResumeRejected`，任何节点都不运行 |
| 节点读到回答 | [`adk-graph/src/node.rs` · `NodeContext::resume_value`](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-graph/src/node.rs#L317-L319) | 只在恢复的那一步有值；暂停的节点在这一步重新运行 |
| 检查点版本只增不减 | [`adk-graph/src/checkpoint.rs` · `ensure_newer`](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-graph/src/checkpoint.rs#L270-L282) | 同一线程已有不低于本次的版本时报 `CheckpointConflict`；两个写入者只有一个成功 |
| SQLite 检查点 | [`adk-graph/src/checkpoint.rs` · `SqliteCheckpointer`](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-graph/src/checkpoint.rs#L486-L488) | 需要 `sqlite` 特性；表名 `graph_checkpoints`。框架不核对图的版本，这一步由宿主做 |

源码固定在 ADK-Rust `98515241133d`（3.0.0，2026-11-26，尚未发布到 crates.io）。本节由 `scripts/learn-agent-rust-adk-refs.py` 生成。

<!-- adk-refs:end -->

::: warning 常见误区
- 暂停节点恢复时会再运行一次，不是从暂停的那一行接着执行。
- 版本冲突只阻止旧快照覆盖新快照，撤销不了保存之前已经发出的外部请求。
- 按节点名回答分辨不出是哪一次暂停，提案改过之后可能批准了没人看过的版本。
- 换了一版图去恢复旧检查点，框架可能“正常完成”而什么都没做，版本检查要宿主自己做。
:::

## 本章结论

等待被保存成检查点：状态、步号和待运行节点。恢复时，新进程重新编译图、读出检查点，重新运行暂停的节点并把回答交给它。暂停 ID 把回答绑定到具体的一次暂停，答案格式在任何节点运行之前校验，版本规则阻止两个写入者互相覆盖；图版本、外部动作的幂等和审批人身份仍由应用负责。

## 迁移思考：保存冲突与效果重放分别处理

两个执行者都从同一个检查点恢复，后保存者被版本检查拒绝（CheckpointConflict），是否已经避免重复发布？

<details><summary>参考推演</summary>

先检查发布发生在保存之前还是之后；保存冲突只能阻止旧快照覆盖，无法撤销两个执行者已经发出的请求。

迁移到付款审批时，需要把执行所有权、稳定操作身份和业务幂等与检查点版本一起设计。

</details>

## 检查理解

1. `show` 为什么让 `approve` 又运行了一次，却没有让 `draft` 再运行？

   <details><summary>参考答案</summary>

   `draft` 所在的超步已经保存进检查点，不会再运行；检查点里的待运行节点是 `approve`，恢复时从它开始。它没有收到回答，于是以同一个暂停 ID 再次暂停。

   </details>

2. 为什么用第 1 版的暂停 ID 批准第 2 版提案会被拒绝？

   <details><summary>参考答案</summary>

   暂停 ID 由线程、步号、节点、问题、数据（包括提案和版本号）和答案格式计算，改版后在新的一步再次暂停，就是新的 ID。严格恢复只接受正在等待的那个 ID，旧的暂停已经过去，它的 ID 不再被接受。

   </details>

3. 冲突实验里两个写入者都运行了 `approve`，为什么报告只生成了一次？

   <details><summary>参考答案</summary>

   两者都从同一个检查点恢复并运行了 `approve`，但保存这一步时版本号必须比已存的大，后保存的那个失败，没有进入 `render`。如果 `approve` 自己有外部动作，它已经发生了两次。

   </details>

4. 用改名后的新图恢复旧检查点，为什么会“正常完成”？

   <details><summary>参考答案</summary>

   检查点里记着等待的节点是 `approve`，新图里没有这个节点，于是没有节点可运行，运行结束。框架不比较图的版本，所以宿主要在恢复前自己检查。

   </details>

5. 想让审批人第二天批准，只在状态里保存 `approved=true` 够吗？

   <details><summary>参考答案</summary>

   不够。答案写进状态以后会一直留着，后面的暂停都会把它当成已回答。应该通过恢复时的回答交给节点（`resume_value` 只在恢复那一步有效），并用暂停 ID 绑定到具体的一次暂停，同时确认审批人身份。

   </details>

## 参考资料

- ADK-Rust（固定提交）：[Graph Agents 文档的检查点与人工介入部分](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/docs/official_docs/agents/graph-agents.md)、[检查点版本规则](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-graph/src/checkpoint.rs)。
- LangGraph [Interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts)与 [Persistence](https://docs.langchain.com/oss/python/langgraph/persistence)：暂停与持久化的概念对照。

下一章进入[图并行、归并与子图](./graph-parallel-subgraphs.md)。
