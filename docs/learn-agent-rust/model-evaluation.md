---
title: "专题 3：模型协议与质量评估"
description: "用真实本地 HTTP 和固定带标签任务，分开验收模型适配、任务完成、延迟与计费证据。"
pageClass: learn-agent-rust-course
---

# 专题 3：模型协议与质量评估

[课程总览](./index.md) · [上一专题：外部操作的可靠性](./side-effect-reliability.md) · [下一专题：生产准入与演练](./production-readiness.md)

::: tip 本章学习目标
- 从一次 HTTP 请求追到工具结果回传，分清 HTTP 成功、适配器接收与任务完成。
- 用提前固定的任务和标签独立判分，同时保存失败、用量缺失和实验环境。
- 复现本地协议实验，读懂完成率、p50 / p95 与费用未知各自的含义。

**前置：** [最小循环](./agent-loop.md)、[错误分类](./error-recovery.md)与[完整集成](./integrated-agent.md)。

**实践方式：** <a href="/learn-agent-rust/model-evaluation-lab.zip" download>下载独立 Cargo 学习包</a>。固定 Rust 1.99.1、Python 3.9+；首次下载依赖需要网络，本地实验无需模型密钥。
:::

[R20](./integrated-agent.md) 已经让脚本模型穿过了完整任务。但换成 HTTP 模型后，第一份日志很容易令人误判：服务返回 `200`，响应 JSON 能解析，模型还说“已完成”。这三件事成立，用户的目标就完成了吗？

继续使用同一个任务：读取项目的 `README.md`，回答其中的启动命令。本章让一个本地 HTTP 服务先后扮演两种模型：一种根据实际工具数据回答；另一种无论读到什么都回答 `npm start`。先预测：它们的协议通过率和任务完成率会分别是多少？

<LearnAgentRustMap active="model-evaluation" />

<!-- experiment-library:start -->

全书实验可从[统一代码库](./experiments.md#model-evaluation)下载；解压后进入 `chapters/model-evaluation/`，或在代码库根目录运行 `python3 run.py run P03`。

<!-- experiment-library:end -->

## 1. 把三个判断拆开

服务的响应经过三层检查：

| 层次 | 问题 | 本章证据 |
| --- | --- | --- |
| HTTP 与适配契约 | 状态、正文、模型身份、结束原因和工具参数能否按约定处理？ | 实际服务记录与客户端请求 / 响应 |
| 宿主执行边界 | 工具是否允许？调用 ID 是否重复？预算是否充足？ | 配对消息、停止原因和真实读取次数 |
| 任务质量 | 最终答案是否满足事先固定的要求？ | 隐藏于模型输入之外的标签与独立判分 |

`adapter_ok=true` 表示这个任务中的响应均被适配器正常接收。它仍可能请求未知工具，或在回答阶段给出错误命令。下列两个实际运行摘要体现了这个区别：

<<< @/public/learn-agent-rust/outputs/p03-protocol-normal.txt

<<< @/public/learn-agent-rust/outputs/p03-protocol-wrong-answer.txt

![合法的 HTTP 响应先经过适配和宿主工具边界，再由独立标签判断任务完成。](/learn-agent-rust/figures/p03-validation-layers.svg)

从左往右读：HTTP `200` 仅是入口；合法工具调用还要经过宿主检查；最后，判分器比较标签和实际读取。错误答案可以通过前两层，仍在第三层失败。

本章的通过率是**任务级分母**：一项任务可能发出多次 HTTP。两轮都接收成功，这项任务的适配验收才算一次通过；HTTP 请求总数另列。

## 2. 用真实 HTTP 替换脚本模型

本地服务是 Python 标准库 `ThreadingHTTPServer`，只监听 `127.0.0.1` 的动态端口。Rust 程序通过 reqwest 发出 POST，经过真实 socket 接收 JSON。它不是直接调用一个返回值函数，也没有访问外部模型。

Rust 侧实现 langchain-rust 的 `LLM` trait，把 HTTP 响应转换成 `GenerateResult`。graph-flow 继续负责推进会话，工具仍由宿主执行：

<<< @/public/learn-agent-rust/code/model-evaluation/src/agent.rs#graph

本章把循环缩为 `ModelTurn → ExecuteTools → ModelTurn`。没有重新引入 R20 的 MCP、reviewer、数据库和 worktree，以便把故障定位到 HTTP 适配、消息配对和目标判断。

::: info 代码只有一个来源
所有 Rust / Python 片段都从完整学习包导入。<a href="/learn-agent-rust/code/model-evaluation/README.md" download>下载运行说明</a>，或在 [GitHub 查看源码](https://github.com/lewislau86/lewislau86.github.io/tree/master/docs/public/learn-agent-rust/code/model-evaluation)。各章节工程互相独立，本文代码不依赖其他章节目录。
:::

### 先约定支持哪一小段协议

本适配器选择 Chat Completions 的一个受限非流式契约，外部服务分支按 [DeepSeek 官方接口](https://api-docs.deepseek.com/api/create-chat-completion/)准备。固定请求包含 `messages`、`tools`、`tool_choice=auto`、`stream=false`、`temperature=0`、`max_tokens=256` 和 `thinking.type=disabled`。后者是服务接口的扩展字段，不能假设所有兼容服务都支持。

返回值只接受一个 choice、一个 function call，参数必须是能解析成对象的 JSON 字符串。结束原因为 `tool_calls` 时必须带一项调用；`stop` 必须带非空回答。`length` 表示生成被截断，本章以 `generation_incomplete` 停止；`content_filter` 单独记为 `filtered`。

为保证实验身份明确，返回 `model` 必须与请求相同。这是本章的**准入规则**：真实服务如果把别名解析成版本名，应先建立并记录明确映射，再调整规则，不应静默丢弃身份变化。

<<< @/public/learn-agent-rust/code/model-evaluation/src/provider.rs#parse

这里还检查 `usage`。缺失时返回 `None`，有值时要求非负整数，且输入与输出之和等于总量。它们来自服务报告，并非客户端 tokenizer 的估算。原始 usage 保留在交换记录中，便于日后核对缓存或其他分类。

这段适配没有覆盖 SSE、并行工具、图片、思考内容回传和全部 provider 扩展。写清接口子集，读者才知道一项协议失败是在拒绝不支持的能力，还是实现出了错。

### 请求发出后，等待什么才算结束？

接收了响应头，还没有收完响应体。reqwest 的总请求超时覆盖到响应体结束；本章显式关闭重定向和系统代理。响应体既检查 `Content-Length`，也在逐块读取时累计大小，避免服务省略长度后绕过上限。

<<< @/public/learn-agent-rust/code/model-evaluation/src/provider.rs#http

本地请求总期限为 800 ms，真实服务配置为 30 秒；请求正文最多 24,576 字节、响应正文最多 65,536 字节。不是所有限制都等于安全沙箱：例如读取工具的文件大小检查发生在读取之后，仅用于本例的小型、可信测试文件。

HTTP 层不自动重试。`401/403`、`429`、`5xx`、重定向和超时分别留下停止原因，等待调用者决定下一步。特别是超时并不证明远端停止生成或没有计费，这个边界与 [P02 的外部效果](./side-effect-reliability.md)一致。

## 3. 第二次请求是否真的带回了工具结果？

第一次请求只有系统策略和固定用户目标，附上 `read_file` 的工具定义。服务返回一个 `id=read-1` 的请求，宿主检查名称、参数和预算，读取本次任务目录的 README。

实际工具实现只接受 `{"path":"README.md"}`，没有 shell 工具，也不执行命令。文件不存在时返回配对的 `not_found` 工具结果，让模型有机会报告空值。

<<< @/public/learn-agent-rust/code/model-evaluation/src/agent.rs#tool

随后 langchain-rust 消息要映射回 HTTP 的 `assistant.tool_calls` 和 `tool.tool_call_id`。调用 ID 是关联键，不能在序列化时重新生成：

<<< @/public/learn-agent-rust/code/model-evaluation/src/provider.rs#messages

序列化之前会检查整段历史：工具结果必须有先前请求，下一条普通消息出现前必须补齐结果，旧 ID 不得重复。服务端也记录实际收到的请求，验证器拿它与客户端保存的请求逐字段比较，而不只检查客户端自称发出了什么。

![第一轮工具请求的 ID 在宿主读取与第二轮 HTTP 工具结果间保持一致，标签始终位于评测侧。](/learn-agent-rust/figures/p03-tool-roundtrip.svg)

看图里的两条边界：文件内容作为 `tool` 数据返回，系统策略继续在前缀；期望答案保留在判分器一侧，从未加入模型消息。`duplicate-id` 会在第二次工具请求到来时停止；`path-escape` 则在文件读取前拒绝。

父循环也有硬上限：最多 3 次模型尝试、1 次文件读取。每次调用之前先扣尝试数，失败依然计入。主循环的实际接线为：

<<< @/public/learn-agent-rust/code/model-evaluation/src/agent.rs#turn

本章没有重试，所以每次尝试对应一次实际收到的 HTTP 请求。这个对应关系由服务日志核对；在其他带重试或请求尚未送达的系统中，两个数量需要分开统计。

## 4. 答案在运行之前就固定

现在可以问“任务完成了吗”。评测集版本为 `startup-v1`，有四项公开合成任务：

| 任务 | README 条件 | 期望 command |
| --- | --- | --- |
| `rust` | 一条 Rust 启动命令 | `cargo run --release` |
| `node` | 一条 Node 启动命令 | `npm start` |
| `injection` | 正确启动命令后附越界读取与错误回答指令 | `python -m demo` |
| `missing` | 文件不存在 | `null` |

文件内容和标签统一保存在 <a href="/learn-agent-rust/code/model-evaluation/cases.json" download>cases.json</a>，完整文件的 SHA-256 随证据发布。它们在每个任务启动之前创建；服务只从 HTTP 中的工具结果获得文件数据，读不到判分器里的 `expected`。

每个答案必须是精确的两字段 JSON：`command` 是字符串或 `null`，`source` 是 `README.md`。判分器同时要求正常回答、答案等于标签，并观察到一次实际读取：

<<< @/public/learn-agent-rust/code/model-evaluation/src/agent.rs#grade

再用 Python 根据原始输出和标签独立计算一遍：

<<< @/public/learn-agent-rust/code/model-evaluation/lab.py#independent-grade

两个实现核对的是同一份事先公布的规则，不是让模型给自己打分。`false-finish` 特意直接回答正确命令，`answer_correct=true`，但没有实际读取，`task_pass=false`。

这套判分有意严格，适合启动命令这种答案唯一的小任务。换成解释、设计或代码修改时，先设计可观察验收：测试、文件内容、引用依据或人工评分规则；不要直接把精确字符串比较推广到所有开放任务。

### 比较时保持输入和分母一致

两个夹具策略都按相同顺序运行四项任务，每项重复 3 次，总计各 12 次任务：

- `quality-good` 从实际工具结果提取唯一的 `Startup:` 行，缺失时返回空值。
- `quality-bad` 也正常请求和接收工具结果，但始终回答 `npm start`。

<!-- p03-quality:start -->

| 夹具策略 | 适配通过 / 尝试任务 | 完成 / 尝试任务 | 实际 HTTP | 费用 |
| --- | --- | --- | --- | --- |
| `quality-good` | 12 / 12 | 12 / 12 | 24 | 未知（夹具无真实计费） |
| `quality-bad` | 12 / 12 | 3 / 12 | 24 | 未知（夹具无真实计费） |

<!-- p03-quality:end -->

这就回答了开头的问题：两者适配验收都是 12/12，而错误夹具只在 `node` 上答对，所以完成 3/12。重复 3 次是检验确定性复现，不是 12 个不同任务，也不是三个随机种子的模型质量实验。

<<< @/public/learn-agent-rust/outputs/p03-quality-good.txt

<<< @/public/learn-agent-rust/outputs/p03-quality-bad.txt

![相同四项任务重复三次，两种夹具都通过适配，但错误夹具只在 Node 任务完成。](/learn-agent-rust/figures/p03-quality-results.svg)

这张图只能说明判分器能识别“合法但错误”的输出。四项公开合成诊断任务没有训练 / 验证拆分，也不支持泛化结论或模型排名。注入任务在这里验证管线和判分；真实模型会怎样处理恶意文本，需要实际调用后的证据。

## 5. 先验收 27 个故障边界

完整验收既要有完成任务，也要让错误落在预期位置。下面是实际本地 HTTP 运行结果；协议错误被正确拒绝，也属于相应故障测试通过。

<!-- p03-protocol:start -->

| 场景 | 适配器通过 | 停止原因 | 实际读取 | 任务完成 |
| --- | --- | --- | --- | --- |
| `normal` | 是 | `answered` | 1 | 是 |
| `wrong-answer` | 是 | `answered` | 1 | 否 |
| `false-finish` | 是 | `answered` | 0 | 否 |
| `missing-usage` | 是 | `answered` | 1 | 是 |
| `bad-json` | 否 | `invalid_json` | 0 | 否 |
| `http401` | 否 | `authentication` | 0 | 否 |
| `http429` | 否 | `rate_limited` | 0 | 否 |
| `http500` | 否 | `server_error` | 0 | 否 |
| `redirect` | 否 | `redirect_refused` | 0 | 否 |
| `timeout` | 否 | `timeout` | 0 | 否 |
| `body-timeout` | 否 | `timeout` | 0 | 否 |
| `chunked-limit` | 否 | `response_limit` | 0 | 否 |
| `oversize` | 否 | `response_limit` | 0 | 否 |
| `content-type` | 否 | `content_type` | 0 | 否 |
| `empty-choices` | 否 | `invalid_choices` | 0 | 否 |
| `wrong-role` | 否 | `invalid_message` | 0 | 否 |
| `bad-arguments` | 否 | `invalid_arguments` | 0 | 否 |
| `missing-id` | 否 | `invalid_call_id` | 0 | 否 |
| `parallel-calls` | 否 | `unsupported_finish` | 0 | 否 |
| `truncated` | 否 | `generation_incomplete` | 0 | 否 |
| `filtered` | 否 | `filtered` | 0 | 否 |
| `model-drift` | 否 | `model_mismatch` | 0 | 否 |
| `bad-usage` | 否 | `invalid_usage` | 0 | 否 |
| `unknown-tool` | 是 | `unknown_tool` | 0 | 否 |
| `path-escape` | 是 | `permission_denied` | 0 | 否 |
| `duplicate-id` | 是 | `duplicate_call` | 1 | 否 |
| `repeat-read` | 是 | `tool_budget` | 1 | 否 |

<!-- p03-protocol:end -->

注意三组对照：

1. `timeout` 延迟响应头；`body-timeout` 立即回头、写一字节后停住。两者都由总请求期限截断。
2. `oversize` 在长度头上超限；`chunked-limit` 用分块传输、不给 `Content-Length`。两者都被限制，后者覆盖累计字节分支。
3. `unknown-tool`、`path-escape` 的响应形状合法，适配器正常接收；宿主仍拒绝动作。它们没有造成文件读取。

`missing-usage` 的任务完成，计量却未知。这一项防止汇总器把“没有报告用量”伪装成“零 token”。

<<< @/public/learn-agent-rust/outputs/p03-protocol-missing-usage.txt

## 6. 完成率之外：时间和费用各自怎么记？

本例至少保留四类指标。只给一个“成功率”会隐藏服务错误、未完成任务和代价变化：

| 指标 | 本章口径 | 解释边界 |
| --- | --- | --- |
| 适配通过 | 所有响应被适配器接收的任务数 / 尝试任务数 | 不代表工具获准或答案正确 |
| 任务完成 | 独立验收通过的任务数 / 尝试任务数 | 失败、超时不从分母移除 |
| 延迟 | 图开始到停止的单任务时间 | 含 HTTP 与工具；不含建文件、进程启动；没有 TTFT |
| token / 费用 | 服务 usage 原文及是否完整，费用另记 | 缺失为未知；夹具 token 是合成字段 |

汇总代码如下。百分位采用 nearest-rank，即排序后取 `ceil(n × p / 100)` 的第一个对应样本：

<<< @/public/learn-agent-rust/code/model-evaluation/lab.py#metrics

### 一次真实的本地时延观测

以下是本机 loopback 实验的一次测量快照，来自真实时钟；不含专门注入的超时场景，只统计各策略的 12 次质量任务。

<!-- p03-latency:start -->

| 本地夹具策略 | 任务数 | 最小 ms | p50 ms | p95 ms | 最大 ms |
| --- | --- | --- | --- | --- | --- |
| `quality-good` | 12 | 1.334 | 1.638 | 2.356 | 2.356 |
| `quality-bad` | 12 | 1.331 | 1.462 | 2.072 | 2.072 |

<!-- p03-latency:end -->

环境为 Rust 1.99.1、Apple Silicon macOS，详细 rustc、主机与 Python 版本保存在 `evidence.json`。两策略顺序运行，没有负载隔离；表中小差异不用于比较性能。`n=12` 时 p95 正好是最大样本，远远不足以估计真实服务尾延迟。

验证器每轮都会重新测时并核对样本数与百分位计算，但 `--check` 不要求时延逐字相同。下载包保留生成时的测量快照，源码或任务标签变更则必须刷新证据。

### 费用为什么写未知？

本地服务每次故意返回 100 个输入 token、20 个输出 token，专门检查累加逻辑。它没有运行 tokenizer，也没有计费，因此不能拿这个字段乘网上价格，得到所谓本章实际费用。

真实服务还需要记录带日期和币种的价格表、计费类别、完整用量与账单口径。例如缓存命中输入和普通输入可能需要不同类别，不能只拿总 prompt token 乘同一个单价。当前程序没有内置价格表，`cost_usd=null` 是明确的证据缺口。

即使客户端请求超时，供应商也可能已产生用量；“本地没收到 usage”与“远端账单为零”必须分开。做真实模型比较时，应按同一任务、同一限制、完整失败分母报告质量、时间和已知费用，并保留无法计量的次数。

## 7. 动手实验与真实服务入口

解压进入 `model-evaluation-lab/`，先运行本地实验：

```sh
cargo test --locked
cargo build --locked
python3 lab.py fixture target/debug/learn-agent-p03 demo-fixture
```

目标目录须尚不存在，父目录已存在。Python 只启动本地 HTTP 服务；结束时关闭 socket，等待服务线程和延迟故障处理线程退出。

先读 `demo-fixture/quality-good.txt` 与 `quality-bad.txt`，再打开某个任务的 `run.json`：

| 证据位置 | 反查的问题 |
| --- | --- |
| `protocol-normal/run.json → exchanges[0]` | 第一次 POST 是否真的包含 tools 和固定模型配置？ |
| 同文件 `exchanges[1]` | 第二次请求有没有同 ID 的工具结果？ |
| `state`、`graph_nodes` | 图走了哪几步，真正读取几次，在哪里停止？ |
| `quality-bad-1-rust/run.json → grade` | 答案形状正确而标签不符时，如何判分？ |
| `quality-good-1-injection/README.md` | 恶意文本是不是实际读入的文件内容？ |
| 根目录 `evidence.json` | 服务记录与客户端记录是否一致？测时与稳定证据是否分开？ |

可以先改一份解压副本的 `cases.json`，加入一个新启动命令，再观察两策略差异；不要覆盖课程原始证据。若要做模型评测集，应另留未用于调提示词的任务集并固定版本，这四项公开诊断题只做管线自检。

### 真实服务：本次未运行

学习包提供一个显式 `live` 入口，只允许 `https://api.deepseek.com/chat/completions`，沿用同一工具、提示词、任务和判分器。需要在本机安全配置 `DEEPSEEK_API_KEY` 和显式 `P03_MODEL`，运行前按官方文档核对该模型的参数支持。

```sh
python3 lab.py live target/debug/learn-agent-p03 demo-live
```

这条命令会向外部服务发送固定的公开任务内容，并产生可能计费的请求。计划 12 项任务、每项最多 3 次请求、每次最多 256 个生成 token；这只是调用限制，不是费用保证。程序不将密钥放进命令参数或结果文件。

本专题的编写和自动验证**没有执行这条命令**。适配器 live 分支已构建，端点规则有单元测试；远端可用性、HTTPS 实际连接、返回身份映射和真实模型质量均仍为 `not_run`。

`live-results.json` 分开记录 `planned_tasks` 与 `attempted_tasks`、请求和返回模型、时间、平台、任务/提示词哈希、完整逐次请求和 usage。遇认证、限流或模型身份变化时提前停止，保留已尝试分母。若模型返回别名对应的版本名，需要先显式定义身份映射并重验，不能直接把这次失败当作完成。

同一个命令能跑通并不代表论文式比较已经成立。真实评估还要固定模型版本与配置、任务顺序和预算，记录重复策略、异常与未计量项；在独立保留集上判分，必要时加入人工复核与多位标注者的一致性。

### 仓库中的复验入口

```sh
python3 scripts/verify-agent-evaluation.py --check
python3 scripts/generate-learn-agent-rust-figures.py --lesson P03
npm run docs:build
```

验证器执行 **10 个 Rust 测试、Clippy、27 个协议 / 宿主场景和 24 次带标签任务**，每轮核对 80 个实际 HTTP 请求、消息配对、独立判分、真实文件和服务线程回收。然后独立解压最终 zip，离线重新编译，再启动新服务复验全部场景。源码哈希、证据与输出全部随下载包发布，CI 仅运行本地夹具。

<!-- transfer-thinking:start -->

## 迁移思考：指标衡量的是哪个对象

本地协议场景全通过，能否据此选择某个真实模型？先给出你的判断，再展开下面的推演。

<details><summary>推演与应用</summary>

把协议符合性、任务验收、时延与费用分别记录；模型决策质量需要固定任务与真实 provider 的独立试验。

选择模型是带环境和成本的实验判断，确定性重复也不是随机采样置信度。

</details>

这是一道迁移练习，推演不代表新增实验已通过。对照[全书审查中的证据层次](./course-review.md#evidence-layers)，说明你的判断还需要哪一级证据。

<!-- transfer-thinking:end -->

## 本章结论：让每个指标回答一个问题

协议验收说明模型输出能进入这个应用；宿主检查说明动作符合当前边界；独立标签说明这个任务是否完成。三者都应留证据，而不是用一个 `200` 或一句“完成”替代。

本章拿到了真实本地 HTTP、两库消息回传、文件读取和判分的证据。真实服务的模型质量、性能和费用仍待实际运行，这一项保留未知，评测结果才有可解释的边界。

::: warning 常见误区
- `adapter_ok=true` 只是通过本章受限适配契约；它不代表覆盖全部 API，也不保证完成用户任务。
- 27 个故障场景验证拒绝位置，不能与质量集混成一个“模型成功率”。确定性夹具的三次重复不证明随机模型稳定性。
- `temperature=0` 不保证真实服务逐次完全相同；记录版本、请求和输出，才能解释差异。
- 缺失 usage、超时账单与价格口径不明时，费用保持未知。夹具 token 字段不能当真实用量。
- 本地 loopback 延迟不等于外部模型延迟；这四项公开合成题不构成泛化或生产准入证据。
:::

## 检查理解

1. 为什么 `quality-bad` 适配通过 12/12，任务却只完成 3/12？

   <details><summary>参考答案</summary>

   它发出合法工具请求，接收配对结果，最后返回形状正确的回答，因此适配器正常接收。但它始终给出 `npm start`，只与 `node` 的标签相符。四项任务各重复三次，故只有三次通过独立判分。

   </details>

2. 模型没读文件就猜对了答案，为什么本章仍判失败？

   <details><summary>参考答案</summary>

   本章的任务契约提前要求实际读取文件，除了答案正确，还要观察到一次真实读取。`false-finish` 检验这个要求是否被执行。其他任务如果允许直接回答，应先修改验收规则，而不是在看到结果后改变标准。

   </details>

3. `missing-usage` 完成任务，费用是否可以记为零？

   <details><summary>参考答案</summary>

   不可以。任务验收与计量是两个维度，未收到 usage 只能记为未知。真实服务可能已产生费用；需要补供应商账单和带日期的计价口径。本地夹具更没有真实计费，合成 token 只测试汇总逻辑。

   </details>

4. 为什么已经测了 `timeout`，还要测 `body-timeout` 和 `chunked-limit`？

   <details><summary>参考答案</summary>

   前者在响应头之前等待；后者验证收到头之后总期限仍约束响应体。`chunked-limit` 不提供长度头，验证程序会实际累计接收字节，而不是只相信 `Content-Length`。它们覆盖不同的接收分支。

   </details>

5. 12 个样本的 p95 比另一个策略小一点，能据此选模型吗？

   <details><summary>参考答案</summary>

   不能。本例是本地确定性夹具，顺序执行、无负载隔离，12 个样本的 nearest-rank p95 就是最大值。真实模型比较需要相同条件下更多样本，完整失败分母与费用覆盖，还要结合独立任务质量判断。

   </details>

## 参考资料

- [独立工程源码](https://github.com/lewislau86/lewislau86.github.io/tree/master/docs/public/learn-agent-rust/code/model-evaluation)与 <a href="/learn-agent-rust/model-evaluation-lab.zip" download>包含源码、输出和证据的学习包</a>。
- [DeepSeek Chat Completions API](https://api-docs.deepseek.com/api/create-chat-completion/)与 [Function Calling](https://api-docs.deepseek.com/guides/function_calling)：请求、工具结果、结束原因与 usage 的官方契约；实际兼容性另验。
- [reqwest 0.12.28 ClientBuilder](https://docs.rs/reqwest/0.12.28/reqwest/struct.ClientBuilder.html)：总超时、连接配置与重定向策略。
- [graph-flow 固定源码](https://github.com/a-agmon/rs-graph-llm/tree/9bbca193f20a8c4ba23289621549ecb3d35fee64)与 [langchain-rust 固定源码](https://github.com/Abraxas-365/langchain-rust/tree/5fc3f5aca4380da48829f95d6e2fd0217b1f2013)：课程实际依赖的图与模型接口。
- [Python http.server](https://docs.python.org/3/library/http.server.html)与 [socketserver](https://docs.python.org/3/library/socketserver.html)：本地测试服务及线程退出；仅用作实验服务。

下一专题进入[生产准入与演练](./production-readiness.md)，把本章的协议、质量与计量证据放进长期服务的准入条件。
