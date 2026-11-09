---
title: "第 23 章：MCP 外部工具"
description: "用固定版本的官方 Rust SDK 连接真实 stdio 服务，把工具发现、参数校验、权限与连接退出接入统一入口。"
pageClass: learn-agent-rust-course
prev:
  text: 第 22 章 · 工作区隔离
  link: /learn-agent-rust/worktree-isolation
next:
  text: 第 24 章 · 完整 Agent 集成
  link: /learn-agent-rust/integrated-agent
---

# 第 23 章：MCP 外部工具

[课程总览](./index.md) · [上一章：工作区隔离](./worktree-isolation.md) · [下一章：完整 Agent 集成](./integrated-agent.md)

::: tip 本章学习目标
- 追踪工具发现、命名空间映射和一次跨进程调用，分清应用调用 ID 与协议请求 ID。
- 把远端 schema、调用前权限与工具结果接入统一入口，并拒绝不支持的描述。
- 用真实本地服务验证超时、断连、写入结果不明与子进程回收。

**前置：** [第 2 章：工具注册与图调度](./tools-and-graph.md)、[第 3 章：工具权限与审批](./permissions.md)、[第 15 章：错误分类与恢复](./error-recovery.md)。不需要先完成其他平台章节。

**实践方式：** [下载独立 Cargo 学习包](/learn-agent-rust/mcp-tools-lab.zip)。固定 Rust 1.99.1、官方 SDK `rmcp = 3.9.0` 和 MCP `2025-11-25` 协议；其他依赖由 `Cargo.lock` 固定。首次获取工具链与依赖需要网络，实验运行无需模型密钥、数据库或第三方 MCP 服务。
:::

工作区助手已经会调用宿主里的 `read_file`。现在项目笔记放到独立服务里，助手仍需要读取说明，必要时追加一条笔记。若为每个服务都重写一套循环，参数、权限和结果很快就会出现不同规则。

我们希望保持第 2 章的统一入口：循环仍然读取工具描述、提交结构化调用、接收配对结果。新增的是一个适配器，把一部分调用送到独立 MCP 服务。

先预测：服务报告 `append_note` 带有 `readOnlyHint=true`，宿主可以直接允许写入吗？如果调用超时，但文件已经增加一行，程序可以马上再调一次吗？本章用两个真实文件实验回答。

<LearnAgentRustMap active="mcp-tools" />

<!-- experiment-library:start -->

全书实验可从[统一代码库](./experiments.md#mcp-tools)下载；解压后进入 `chapters/mcp-tools/`，或在代码库根目录运行 `python3 run.py run R19`。

<!-- experiment-library:end -->

::: info 技术版本与复现基线
本章代码与 initialize 讲解固定对应 MCP **2025-11-25**、rmcp 3.9.0。核对于 2026-11-08 的官方当前规范是 **2026-07-28**，已改为请求携带版本与能力，并改变发现、结果和通知机制。新版实验尚未验收；先看[迁移对照](./technology-radar.md#mcp-migration)，再决定采用哪个合同。
:::

::: info 源码与验证范围
Rust 片段直接导入[完整工程源码](https://github.com/lewislau86/lewislau86.github.io/tree/master/docs/public/learn-agent-rust/code/mcp-tools)；[下载工程、输出与证据](/learn-agent-rust/mcp-tools-lab.zip)。`server.rs` 提供服务，`connection.rs` 管连接，`adapter.rs` 管注册与分发，`schema.rs` 管受限参数规则，`lab.rs` 编排场景。

本章使用官方 `rmcp` 的真实客户端与服务端，跨真实子进程的 stdio 管道通信，真实读写文件。调用请求由固定脚本提供，写入批准也是模拟的可信输入。本章尚未接入真实模型、`langchain-rust` 或 `graph-flow`；统一入口的端到端 Agent 集成留到第 24 章。
:::

## MCP 在方法与知识链路中的位置

MCP 把外部能力接到宿主；[Skills](./skill-loading.md)给出工作方法，[RAG](./retrieval-augmented-generation.md)选择当前证据，[Memory](./memory.md)保留历史事实。服务器可以把检索实现暴露为搜索工具，技能也可以要求调用该工具，但协议接通后仍要分别检查证据和授权。本章验证外部工具与连接契约，K01 的搜索尚未作为 MCP 工具集成。整体关系见[概念导读](./knowledge-and-capabilities.md)。

## 1. 从进程内函数，走到独立工具服务

MCP 在本章负责发现和调用协议。模型决定提出哪个工具请求，宿主决定是否允许，服务实现具体工作。服务成功启动、工具被发现、实际调用完成，是三个不同阶段。

![宿主统一入口把本地调用送入函数，把远端调用映射后经真实管道送入 MCP 子进程。](/learn-agent-rust/figures/r19-mcp-routing.svg)

上方是共同入口。左侧直接调用宿主函数，右侧先把 `mcp_notes__read_note` 还原为服务 `notes` 上的 `read_note`，再经管道派发。结果带回应用层调用 ID；协议内部还使用自己的请求 ID。

| 对象 | 本章实例 | 谁负责 |
| --- | --- | --- |
| 工具宿主 | `learn-agent-r19 normal ...` | 进程配置、策略、预算、结果回传和回收。 |
| MCP 客户端 | 宿主内的 `rmcp` 会话 | 序列化请求、匹配响应、推进协议。 |
| MCP 服务 | 同一二进制的 `server` 子命令 | 声明工具、校验服务输入、执行文件操作。 |
| 统一注册表 | 本地 `local_status` 与远端别名 | 导出共同工具描述，保存路由信息。 |

宿主启动服务需要执行路径、参数和环境，这些来自可信配置。本例使用当前二进制的绝对路径，通过 `Command` 直接传参数，不经过 shell；子进程环境清空，工作目录固定为新建练习目录。**启动权限属于宿主。** 工具描述不能要求宿主临时执行任意安装命令。

## 2. 先运行，看看协议实际传了什么

解压后进入 `mcp-tools-lab`：

```sh
cargo test --locked
cargo run --locked -- normal demo-normal
```

最后一个参数必须是不存在的目录；程序拒绝覆盖已有练习数据。`normal` 创建 `notes/README.md`，启动服务，先调用本地状态工具，再读取远端笔记，最后关闭连接并等待子进程退出。

CLI 标准输出是完整 JSON，包括工具描述、结果、协议帧和退出记录。下面的**实验摘要由验证器从实际 JSON 与磁盘核对生成**，后文采用相同口径；它不是原始 stdout。原始协议帧见学习包 `evidence.json`。

<<< @/public/learn-agent-rust/outputs/r19-normal.txt

这里注册了 8 项：1 项本地工具、7 项服务工具。分页发现发生两次，真实远端调用只有一次。`read_text` 与验证器直接读到的 `README.md` 字节内容一致。

`application_call_id=call-1` 是固定调用脚本给的身份；`wire_call_id=3` 是这次协议会话里的 JSON-RPC ID。前面的初始化和发现请求也占用协议 ID，因此两者没有必要相同。模型工具消息按应用调用 ID 配对，协议响应由 SDK 按协议 ID 配对。

### 为什么显式固定协议版本？

本章固定 `2025-11-25`，选择该版本的 `initialize → initialized → 正常请求` 生命周期；`rmcp 3.9.0` 同时认识其他协议版本，所以客户端和服务端都显式设置本章版本，连接后再次检查协商结果与工具能力。这里的日期是**协议版本**，不表示它是最新协议。

升级 SDK 或协议时，应重新检查生命周期、能力与结果类型，重跑本章线协议验证。API 细节以固定 SDK 源码和 [2025-11-25 生命周期规范](https://modelcontextprotocol.io/specification/2025-11-25/basic/lifecycle)为准。

## 3. 先建立会话，再发现完整工具目录

<<< @/public/learn-agent-rust/code/mcp-tools/src/connection.rs#connect

`spawn` 同时持有直属子进程和协议任务。服务 stdout 只传协议，诊断写 stderr。初始化上限为 `2000 ms`；完成后检查协议版本和 `tools` 能力，再把连接标记为可用。

代码中的两个 `duplex` 与中继把真实子进程管道交给 SDK，同时记录逐行 JSON 帧。中继在交给解码器前限制单帧为 65,536 字节、记录总数为 128；这让实验能独立核对请求顺序，也限制故障服务的输入规模。它是教学用记录与边界层，协议编解码仍由 SDK 完成。

![实际请求先初始化，再发两页 tools/list，最后才 tools/call。](/learn-agent-rust/figures/r19-discovery-lifecycle.svg)

图中的顺序来自 `normal` 记录的出站帧。第一轮 `tools/list` 返回 `nextCursor=second`，宿主继续取第二页，直到没有游标才发布完整注册结果。这里没有把第一页误当成全部工具。

<<< @/public/learn-agent-rust/code/mcp-tools/src/adapter.rs#discovery

发现过程先克隆候选注册表；每项工具通过检查、所有页都取完，才用候选替换正式表。因此后页重复、schema 不支持或游标成环时，已经取到的工具也不会部分发布。

本例限制每次发现最多 3 页、整个注册表最多 24 项（包含本地工具）、游标最多 128 字节，每页请求上限 `250 ms`。工具名称映射后重复就拒绝；游标重复也拒绝。通用 MCP 工具列表的分页和 schema 契约见[固定版本工具规范](https://modelcontextprotocol.io/specification/2025-11-25/server/tools)。

这是一次连接的初始发现。工具目录动态更新时，应把变更通知、重新发现、旧条目撤销和在途调用设计成完整流程；当前实验不处理热更新。

## 4. 命名空间解决同名，映射表保留原名

两台服务可能都叫自己的工具 `read_note`。直接合并就会让后注册的条目覆盖前一个。我们给**宿主可见名字**加固定服务命名空间，并保留原始名称：

| 对模型或调用者导出的名字 | 宿主路由 | 发送给服务的名字 |
| --- | --- | --- |
| `mcp_notes__read_note` | `notes` 连接 | `read_note` |
| `mcp_other__read_note` | `other` 连接 | `read_note` |
| `local_status` | 宿主本地函数 | 无远端请求 |

名称只接受本例约定的 ASCII 字符，服务命名空间最多 16 字节，远端名称最多 40 字节。不支持的名字直接拒绝，不通过删除标点“修好”，避免不同原名变成同一个别名。模型接口的名称长度限制也应在最终提供方接线时核对。

导出共同描述的边界如下：

<<< @/public/learn-agent-rust/code/mcp-tools/src/adapter.rs#definitions

`inputSchema` 映射为共同描述里的 `function.parameters`。调用时根据 `Entry` 中保存的连接和原名路由，不靠拆别名字符串猜目的地。`invalidate` 在关闭时移除指定服务的条目，其他服务与本地工具保留。

运行两个真实服务：

```sh
cargo run --locked -- dual-server demo-dual
```

<<< @/public/learn-agent-rust/outputs/r19-dual-server.txt

共注册 15 项，因为本地工具只有一项，两个服务各提供 7 项。验证器分别核对两个进程读出的 README，并检查线上请求使用原名 `read_note`。

## 5. schema 映射之后，参数仍要检查

远端描述进入共同格式，并不意味着所有模型提供方都能接受相同 schema 方言。本章先把可支持范围缩小，并同时用于注册与调用检查：

<<< @/public/learn-agent-rust/code/mcp-tools/src/schema.rs#schema

当前只接受对象、显式 `required`、`additionalProperties:false`，属性只支持字符串与 `maxLength`。每个属性都必填，长度按 Unicode 字符数量计算；对象最多 8 个属性。`$ref`、组合关键字和 `outputSchema` 等当前未实现的契约会让发现失败，避免把约束悄悄丢掉。

调用参数需要对象形状、字段数、字符串类型和长度都符合约定，才进入权限与派发。这个校验器是受限教学子集；扩展为通用客户端时，应使用完整校验实现，并对目标模型接口做兼容性验证。

`invalid-arguments` 把数字传给字符串 `path`，宿主拦截，服务日志中的调用次数为零。`discovery-schema` 则在服务描述中提供 `$ref`：

<<< @/public/learn-agent-rust/outputs/r19-discovery-schema.txt

`registered=1` 表示只剩本地工具，远端目录没有部分生效。服务自己也再次校验参数；客户端检查用于尽早反馈，不能替代服务端的输入契约。

## 6. 发现只是目录，权限仍由宿主决定

服务中的 `append_note` 故意声明 `readOnlyHint=true`。这是一个用于检查信任边界的误导性 fixture：宿主策略仍把它视为写入，要求绑定完整调用的批准。

| 场景 | 可信输入 | 实际效果 |
| --- | --- | --- |
| `denied-write` | 无批准 | 返回 `approval_required`，没有远端调用。 |
| `approved-write` | 完整匹配调用 ID、别名与参数 | 真实追加一行。 |
| `approval-mismatch` | 批准文字与当前文字不同 | 返回 `approval_required`，没有写入。 |

工具 annotations 是提示，不能提升执行权限；这也符合[工具规范的信任说明](https://modelcontextprotocol.io/specification/2025-11-25/server/tools)。宿主根据可信配置里的服务身份和动作语义判断权限，不能只凭描述、工具名字包含 “read” 或服务自报只读来放行。

本例 `Approval` 持有完整调用，分发时按值消耗；实际批准由场景脚本提供，**没有实现人工审批 UI 或可信用户身份验证**。接入应用时复用第 3 章的等待、展示、身份验证和回复绑定流程。来源、会话和连接代次也需要纳入真实授权域。

## 7. 一次调用，保留不同层次的结果

<<< @/public/learn-agent-rust/code/mcp-tools/src/adapter.rs#dispatch

分发顺序为：按别名找条目 → 参数校验 → 权限检查 → 额度与重复调用检查 → 找可用连接 → 先计数 → `tools/call` → 处理结果。失败也占远端尝试额度，每轮最多 8 次远端派发。

本章内部结果信封使用 `role=tool` 和 `tool_call_id` 表达应用配对关系；实际提供方消息格式还要转换。重复调用场景会输出第二条诊断结果供实验检查，真实历史不得把它直接追加成同一 ID 的第二条工具消息。

| 失败位置 | 调用者看到什么 | 应用如何理解 |
| --- | --- | --- |
| 宿主参数或权限检查 | `invalid_arguments`、`approval_required` | 服务没有执行，先修正输入或取得批准。 |
| 服务返回工具失败 | `ok=false`，保留 `isError=true` 与 content | 协议往返完成，业务工具报告失败。 |
| JSON-RPC 错误 | `protocol_error` | 请求或协议层失败；保留类型分支，不伪装为成功内容。 |
| 管道关闭或服务退出 | `transport_error` | 连接不可用，停止后续派发。 |
| 等待超过上限 | `timeout` 或 `outcome_unknown` | 未取得终态；结合动作语义核对效果。 |
| 解码后结果过长 | `result_limit` | 结果不进入后续模型上下文。 |

成功时保留 `content` 和 `structuredContent`，不把二者都压成一段不可区分的字符串。当前没有实现输出 schema 校验，因此带 `outputSchema` 的目录项在注册阶段拒绝。结果序列化后超过 4096 字节会拒收；线帧限制发生在更早的传输边界，二者负责不同层次。

工具输出与描述都是带来源的数据。接到真实模型时，应放进对应工具消息，保留来源和调用身份；远端文字不能直接变成宿主的系统指令或权限规则。本章不衡量模型的抗注入能力。

## 8. 超时会结束等待，不会撤销写入

运行一次写入后不回复的服务：

```sh
cargo run --locked -- write-timeout demo-timeout
```

服务实际追加 `one line` 并同步文件，然后等待取消而不返回成功。宿主在 `250 ms` 请求上限后返回：

<<< @/public/learn-agent-rust/outputs/r19-write-timeout.txt

`note_lines=1` 来自验证器直接读取 `notes.txt`；`remote_calls=1` 同时由服务事件文件与线上 `tools/call` 帧核对。后续读取也不再通过这条连接派发，返回 `connection_unavailable`。

![未批准写入没有调用，已批准写入追加一行，写入超时也保留一行并返回结果不明。](/learn-agent-rust/figures/r19-mcp-results.svg)

先看 `denied-write` 与 `approved-write` 的调用数，再看 `write-timeout`：虽然没有成功回复，文件效果已经存在。图中调用数和行数都是实测值，不能从错误类别推断没有发生动作。

SDK 取消、关闭协议任务或终止服务只能约束后续生命周期，无法把已经写出的内容倒回去。当前策略把超时或断连的连接标为不可用，保留结果不明，不自动重试；重新连接也不能消除重复写入风险。外部动作需要业务幂等和核对机制，见[可靠性专题](./side-effect-reliability.md)。

## 9. 关闭需要等到资源真正回收

<<< @/public/learn-agent-rust/code/mcp-tools/src/connection.rs#shutdown

关闭时先撤销该服务的注册条目并标记连接不可用，再关闭 SDK 会话，等直属子进程退出；超出宽限就终止，并调用 `wait` 回收，最后中止并等待中继任务。代码保留同一个关闭 future 跨越宽限边界，避免丢掉清理工作的等待关系。

初始化失败也保留进程句柄，进入相同关闭流程。实验逐个验证返回的子进程 PID 已不存在，同时检查 stderr 诊断没有混进 stdout。`dirty-stdout` 向 stdout 写普通日志，会被中继判为无效协议帧并导致初始化失败。

这套代码管理直属服务，不管理它可能继续产生的整棵子进程树；固定 cwd 和清空环境也不构成文件、网络或权限沙箱。任意第三方服务的运行隔离、HTTP 连接、OAuth 和凭据管理需要独立设计。本章只验收受控本地 fixture 服务。

## 10. 实验结果与复验

已验证 **25 个场景和 8 个 Rust 测试**，每轮共启动并核对回收 **26 个真实 MCP 子进程**。验证器检查协议版本、初始化顺序、分页、名称还原、schema 完整映射、请求响应 ID、服务调用日志与磁盘效果；随后实际解压最终下载包，离线重新编译并复跑全场景。

<!-- r19-results:start -->

| 场景 | 远端调用 | 写入行数 | 验证结果 |
| --- | --- | --- | --- |
| `normal` | 1 | 0 | `ok,ok` |
| `dual-server` | 2 | 0 | `ok,ok` |
| `denied-write` | 0 | 0 | `approval_required` |
| `approved-write` | 1 | 1 | `ok` |
| `approval-mismatch` | 0 | 0 | `approval_required` |
| `invalid-arguments` | 0 | 0 | `invalid_arguments` |
| `unknown-tool` | 0 | 0 | `unknown_tool` |
| `duplicate-call` | 1 | 0 | `ok,duplicate_call` |
| `tool-error` | 1 | 0 | `tool_error` |
| `protocol-error` | 1 | 0 | `protocol_error` |
| `timeout` | 1 | 0 | `timeout,connection_unavailable` |
| `write-timeout` | 1 | 1 | `outcome_unknown,connection_unavailable` |
| `server-crash` | 1 | 0 | `transport_error,connection_unavailable` |
| `discovery-duplicate` | 0 | 0 | `duplicate_alias` |
| `discovery-schema` | 0 | 0 | `unsupported_schema` |
| `discovery-name` | 0 | 0 | `unsupported_name` |
| `cursor-loop` | 0 | 0 | `cursor_loop` |
| `missing-capability` | 0 | 0 | `capability_or_version` |
| `startup-exit` | 0 | 0 | `handshake_failed` |
| `startup-timeout` | 0 | 0 | `startup_timeout` |
| `dirty-stdout` | 0 | 0 | `handshake_failed` |
| `list-timeout` | 0 | 0 | `discovery_failed` |
| `result-limit` | 1 | 0 | `result_limit` |
| `closed-registry` | 0 | 0 | `unknown_tool` |
| `call-budget` | 8 | 0 | `ok,ok,ok,ok,ok,ok,ok,ok,call_budget` |

<!-- r19-results:end -->

完整协议帧、工具定义与文件核对记录见学习包 `evidence.json`。为让结果可重复比较，证据省略 PID、退出耗时和平台信号细节，并过滤可选的取消通知；现场仍独立检查每个 PID 已退出。取消是否送达不作为业务效果已撤销的证据。

在网站仓库复验：

```sh
python3 scripts/verify-agent-mcp.py --check
python3 scripts/generate-learn-agent-rust-figures.py --lesson R19
python3 scripts/sync-learn-agent-rust-course.py --check
npm run docs:build
```

本地环境是 macOS arm64、Rust 1.99.1。请求上限使用真实 Tokio 时钟，故障由固定 fixture 注入；这些是控制流实验，不是网络延迟或吞吐性能测试。Ubuntu CI 已配置，结果以其实际运行记录为准；Windows、真实模型、框架接线和第三方服务兼容性尚未验收。

::: warning 常见误区
- **发现工具就自动授权。** 发现建立目录，执行权限由可信宿主策略决定，annotations 也不能授权。
- **给远端工具加前缀后，直接把前缀发回服务。** 别名只供宿主识别，线上请求使用保存的原名。
- **JSON Schema 直接复制就一定兼容模型接口。** 明确支持范围，不能识别的约束拒绝注册，最终提供方仍需验证。
- **超时表示没有执行。** 写入后回复丢失会留下真实效果；先核对，避免重放。
- **关闭客户端对象就完成清理。** 显式等待协议任务、直属子进程和中继；服务进程的更强隔离需要额外机制。
:::

<!-- transfer-thinking:start -->

## 迁移思考：协议兼容与业务可靠性

服务返回符合 schema 的成功文本，是否代表效果可确认且可重放？先给出你的判断，再展开下面的推演。

<details><summary>推演与应用</summary>

核对真实文件或业务回执，再按操作身份判断重试；MCP 调用身份与业务幂等身份分别管理。

升级协议先验生命周期与错误路径；新规范差异见技术跟踪页。

</details>

这是一道迁移练习，推演不代表新增实验已通过。对照[全书审查中的证据层次](./course-review.md#evidence-layers)，说明你的判断还需要哪一级证据。

<!-- transfer-thinking:end -->

## 本章结论

本章保留统一工具入口，把远端部分交给显式连接与命名空间映射。目录先完整校验再发布，调用先检查参数和权限，再通过官方 SDK 发往服务；结果仍保留应用身份与协议含义。

真实进程实验还验证了两个关键边界：写入超时可以留下文件效果；请求结束之后仍要管理连接和子进程。完整 Agent 集成需要把这些规则接回模型消息、图节点与累计预算，并重新做端到端验收。

## 检查理解

### 1. 两台服务都有 read_note，为什么不直接用相同名称注册？

<details><summary>参考答案</summary>

相同名称可能覆盖或误路由。宿主分别导出带服务命名空间的别名，条目同时保存原始名称和连接；派发时发原名给正确服务，避免靠字符串猜路由。

</details>

### 2. application_call_id 与 JSON-RPC ID 为什么不同？

<details><summary>参考答案</summary>

前者配对 Agent 的逻辑工具请求与消息结果；后者由协议会话用于匹配网络或管道请求响应。初始化和发现也需要协议请求 ID，所以两个身份不应混用。

</details>

### 3. append_note 自报 readOnlyHint=true，可以直接调用吗？

<details><summary>参考答案</summary>

不能仅据此授权。服务声明是来源数据，宿主仍按可信配置认定它会写入。本例要求批准与调用 ID、别名和完整参数一致；实际应用还需可信用户身份与会话绑定。

</details>

### 4. write-timeout 只调用一次，却写出了一行，下一步做什么？

<details><summary>参考答案</summary>

保留文件效果与结果不明，停止自动重放，核对实际业务状态。取消或重连不撤销已经发生的写入；若需要重试，应有可验证的幂等契约。

</details>

### 5. 第一页发现正常，第二页出现重复名，应保留第一页吗？

<details><summary>参考答案</summary>

本章采用一次性候选发布，因此整次发现失败，正式表保持原样。这样调用者不会基于一个不完整目录执行。动态更新与在途调用需要额外的版本与撤销策略。

</details>

## 参考资料

- [MCP 2025-11-25 生命周期](https://modelcontextprotocol.io/specification/2025-11-25/basic/lifecycle)、[工具](https://modelcontextprotocol.io/specification/2025-11-25/server/tools)、[传输](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports)：本章固定协议的原始契约。
- [官方 Rust SDK](https://github.com/modelcontextprotocol/rust-sdk)、[rmcp 3.9.0 源码与 API](https://docs.rs/rmcp/3.9.0/rmcp/)：固定 SDK 的能力与生命周期实现。
- [本章工程与证据](/learn-agent-rust/mcp-tools-lab.zip)、[第 3 章权限](./permissions.md)、[第 15 章恢复](./error-recovery.md)：调用前与调用后策略。
- [参考课程 S19](https://learn.shareai.run/zh/s19/)：外部工具进入共同工具池的思路；接口与运行统计按各自实现分别说明。

<details><summary>对照参考课程原图</summary>

以下原图展示参考课程的 Python/Claude 语境，接口、编号与统计沿用原图，不作为本章 Rust 实验的验证证据。

![参考课程把 MCP 服务发现的工具经适配接入统一工具池。](/learn-agent-rust/figures/upstream/r19-mcp-architecture.svg)

图源：[参考章节](https://learn.shareai.run/zh/s19/) · [原图](https://learn.shareai.run/course-assets/s19_mcp_plugin/mcp-architecture.svg)。来源版本和许可见[参考资料说明](./architecture.md#reference-assets)。

</details>

下一章进入[第 24 章：完整 Agent 集成](./integrated-agent.md)，沿同一任务核对已实现的模型、策略、工具、上下文和任务契约，明确模块通过与集成通过的区别。
