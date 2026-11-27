---
title: "第 11 章案例：Claude Code 为什么用 Markdown 做记忆"
description: "从人工笔记、检索式记忆到模型主动读写，分析长上下文改变了什么，以及 Claude Code、Codex 和 ChatGPT 怎样分配记忆的提取、整理与召回。"
pageClass: tinyllm-course
---

# 第 11 章案例：Claude Code 为什么用 Markdown 做记忆

[全书总览](./index.md) · [上一篇：Agent 记忆的四层结构与实验](./agent-memory.md)

::: tip 本章学习目标
沿着人工交接、外部检索和模型主动读写三条路线，解释为什么同样是 Markdown，产生的效果会不同。读完后，你能判断长上下文何时足以替代一层检索或摘要，以及哪些记忆决策适合交给模型。

**前置**　知道上下文窗口和工具调用的基本概念即可。记忆的四层结构见[第 11 章](./agent-memory.md)，工程实现见 [Learn Agent by Rust 的跨会话记忆](/learn-agent-rust/memory)。

**资料范围**　Claude Code、ChatGPT 和本地 Codex 的产品行为以 2026 年 11 月 27 日核对的官方资料为准。第三方源码解读、Anthropic 的 Managed Agents 实验和本文的设计推论各有适用范围。文中实验数据来自原始资料。
:::

<ThinkingActingMap :active="2" label="案例：Claude Code 记忆" />

## 1. 同一份 Markdown，谁决定下一轮看什么？

设想你和编程 Agent 一起排查过一次 Rust 集成测试。单元测试一直通过，集成测试在连接数据库时失败。你们先怀疑连接池，后来发现测试进程拿到了开发环境的连接串。真正的修复是让测试夹具提供独立的连接串。一个月后，用户只说「CI 又出现连接超时了」，报错已经换了措辞，代码也有几次重构。

让三种记忆系统接手这次任务。把过程追加到 `NOTES.md` 并在启动时全量加载，模型能看到原始细节，代价是每次修文档、改样式也会读到这段历史。把观察切片、入库并按首句检索，模型能很快获得少量候选，但这次的「连接超时」可能把连接池的旧猜测排在已验证的修复前面。给模型一份短索引，它则可以先读本次 CI 输出，再沿着「集成测试环境」打开旧笔记，最后对照当前代码判断旧结论是否适用。第三种路径也会失败，尤其是索引缺了入口，或模型根本没意识到该查历史。

把这个问题理解为「记忆从 Markdown 转向组件，又回到 Markdown」，抓住了不少编程 Agent 的使用体验。**更准确的变化是，谁决定保存什么、何时检索、取到之后该信多少。** 上下文变长，让模型能够并排读配置、历史和测试结果。模型更擅长用工具查找并验证，才让它有机会接手原本由固定流程完成的选择。文件保存了这些选择的结果，下一轮能够重新读到它们。

## 2. 几条路线同时演进

### 2.1 从人工交接到固定加载

项目里的 README、决策记录和交接笔记很容易变成 Agent 的外部记忆。把常用命令、架构约定和已知陷阱写入一个稳定入口，新会话就能少做一遍环境调查。Anthropic 在 2025 年 4 月发布的 Claude Code 实践文章已经介绍了自动读取 `CLAUDE.md`，也介绍了用 Markdown 清单当任务草稿。可从原文看到，当时交接文件既能由人维护，也能随着任务逐步更新。见 [Claude Code 的早期实践](https://www.anthropic.com/research/claude-code-best-practices)。

固定加载适合很短、几乎每次都适用的规则。把全部排查日志也堆进去，维护者却必须提前猜测未来任务需要哪些细节。每次会话都要承担这些猜测的输入开销。更麻烦的是，草稿中的「可能是连接池」和验证后的「测试连接串串用」往往以同样的文本形式出现，长文件会让两条陈述都留在模型可见范围里。

### 2.2 检索和压缩解决的是输入选择

将历史保存在外部，按条件取一小部分，能把记忆库体积和单次输入分开。2020 年的 RAG 论文用稠密向量索引为知识密集型任务取 Wikipedia 段落，回答的是怎样从外部知识库找素材。2023 年的 Generative Agents 把 Agent 自己的经历记成自然语言，检索综合相关性、近因和重要性，再由模型归纳出较高层的反思。同年 MemGPT 用分层存储扩展有限上下文，已经允许模型调用工具管理记忆层之间的信息流动。主动管理记忆的思想当时就存在。见 [RAG](https://arxiv.org/abs/2005.11401)、[Generative Agents](https://arxiv.org/abs/2304.03442)和 [MemGPT](https://arxiv.org/abs/2310.08560)。

后来面向编码 Agent 的插件把这种取舍做成可接入的工程组件。Claude-Mem 用 hook 捕获活动并提炼观察，提供 `search` 找候选、`timeline` 看前后过程和 `get_observations` 取详情。这三个工具让模型自行决定要不要追查。Supermemory 的 OpenCode 集成还可以由插件主动搜索并提供结果，也可以让模型决定是否检索。二者说明，数据库和模型主动权可以共存。区别在于哪一层选择候选、何时占用主会话的上下文，以及落库的内容能否被其他客户端复用。见 [Claude-Mem 检索架构](https://github.com/thedotmack/claude-mem/blob/main/docs/public/architecture/search-architecture.mdx)和 [OpenCode 插件文档](https://github.com/supermemoryai/opencode-supermemory)。

这些事件并非先后淘汰的三个阶段。检索增强早于 Claude Code，自主管理记忆早于今天的长上下文，Markdown 交接也始终在用。真正可以追踪的变化，是模型在同一份外部存储上能承担越来越多的整理与查找工作。

### 2.3 长上下文让模型可以晚一点裁剪

2023 年 5 月，Anthropic 将 Claude 的上下文从 9K 扩展到 100K。2026 年 2 月，Opus 4.6 发布时提供了 1M 上下文的测试版。这些是不同版本的输入容量里程碑。容量增加的直接价值，是模型在知道问题之后，可以读进更完整的原文，在行动前交叉核对。过去必须提前压成一句「更换连接串」，现在有机会保留原始报错、排除过程和后续验证。相同长度限制下，能把这些信息取到的系统也可能表现很不一样。见 [100K 上下文公告](https://www.anthropic.com/news/100k-context-windows)和 [Opus 4.6 发布说明](https://www.anthropic.com/news/claude-opus-4-6)。

把问题拆成三个量，边界就清楚了。第一是**容量**，本轮能放多少。第二是**获取**，信息在哪儿，能否用合适的词、路径或时间范围找到。第三是**适用性**，历史条件在当前环境是否成立。增大窗口直接改善第一项，也允许一次核对更多证据。一个全新会话仍需把上周的资料重新送入窗口。即使资料已经送入，模型也可能忽略关键段落。早期 *Lost in the Middle* 的位置实验提供了这个反例，其结果依赖测试时的模型和任务，不能外推为今天所有模型的准确率。另有 2024 年的长上下文与 RAG 对照发现，在其问答数据集和模型下，资源充足时长上下文的平均表现更好，检索路径的成本更低。见 [Lost in the Middle](https://arxiv.org/abs/2307.03172)和 [RAG or Long-Context LLMs?](https://arxiv.org/abs/2407.16833)。

一个更贴近编程的例子来自 2026 年 10 月的 MemDev-Bench 预印本。作者用 Claude Code 运行 DeepSeek-V4-Flash，关闭自动压缩，并控制历史任务的相关程度。直接提供未经摘要的历史执行轨迹，汇总比较中比五种被测记忆系统少用约 **29%～35% 的行动步数**，同时消耗更多输入。像「先检查哪个文件、哪次尝试失败、最后怎样验证」这样的过程信息，可以省掉重新调查。可是把不相关的历史加进去也会诱发回归，少用几步就可能更快走到错误结论。这里测到的是完整轨迹在一组限定历史的任务中的价值，没有比较 Claude 原生 Markdown 记忆与向量库，也没有独立测量窗口扩大的因果效应。见 [MemDev-Bench 第 3、4 节](https://arxiv.org/html/2610.27524v1)。

因此，可以把长上下文理解为**允许更晚、更有依据地决定丢掉什么**。容易定位、体量适中而且需要保留细节的资料，可以在任务发生后直接读。来源分散、规模大、查找耗时的资料，仍需要索引和过滤。

## 3. Claude Code 怎样把这个选择变成产品？

### 3.1 团队规定与模型经验各走各的路径

`CLAUDE.md` 解决项目和用户怎样长期表达指令。团队共享的构建命令可以提交到仓库，特定路径的细则可以在处理相关文件时加载。Auto memory 则保存 Claude 从交互里学到的经验，例如「本仓库的集成测试曾因测试夹具继承开发连接串而失败」。用户说「把测试流程加到 `CLAUDE.md`」和说「记住这次排查经验」会对应两类不同的写入。前者交由项目维护，后者通常留在本机的项目记忆。公开文档把两者都视为给模型的上下文，强制权限由工具层处理。见 [Claude Code 记忆文档](https://code.claude.com/docs/en/memory#claude-md-vs-auto-memory)。

### 3.2 启动时自动读目录，遇到问题再展开

默认的自动记忆目录为 `~/.claude/projects/<project>/memory/`。同一 Git 仓库的 worktree 共享这个本机记忆目录。启用 auto memory 后，新会话启动时加载 `MEMORY.md` 的前 **200 行或 25 KB，以先达到的限制为准**。索引告诉 Claude 有哪些主题及其位置。主题文件通过标准文件工具按需读取。当前文档还说明，当 Claude 写入过长索引时，运行时会提示缩短或要求改写，超出的内容下次加载时会被截掉。用户可用 `/memory` 查看和编辑。见 [存储位置和加载方式](https://code.claude.com/docs/en/memory#storage-location)。

这个限制是整个设计最值得留意的地方。索引随每个新会话进入上下文，某条线索多占几行，就可能挤掉别的线索。更大的模型窗口也无法让第 201 行通过这条启动路径。Claude Code 给固定注入设置上限，把细节留给模型在具体任务中取用。

设想索引只保留一行「集成测试的数据库隔离与复验方式，见 `integration-db.md`」。主题笔记记下现象、成立条件、曾排除的解释和验证入口。如果当初只写「修好了数据库」，下一轮只能重新调查。如果把几十次失败全写到索引里，其他任务也要承担这笔输入开销。标题和摘要要让未来的模型想得起该打开哪个文件，正文则应让它有办法推翻旧结论。

### 3.3 `/compact` 管住当前会话的工作状态

阅读源码、运行测试和比较结果会持续占用窗口。长会话压缩后，Claude Code 用摘要接续对话，并从磁盘重新注入适用的启动内容，包括项目根的指令和自动记忆。会话摘要要保存当前目的、进度和未解决问题。长期笔记需要判断别的任务还会不会用上这次经验。两者可以使用同一个模型，却有不同的目标和保留期限。见 [Claude Code 的上下文窗口文档](https://code.claude.com/docs/en/context-window#what-survives-compaction)。

《御舆》第 7 章提供了另一个观察入口。作者把所分析版本中可见的操作分为整条消息裁剪、旧工具结果压缩、折叠和自动摘要。把它们放回排查场景，删去第二次输出完全相同的日志，和把「测试只在本地成功」压缩成「测试已通过」，承担的风险显然不同。前者节省空间，后者改变了结论。四级名称和触发顺序属于第三方实现分析，压缩后哪些内容可重新加载以产品文档为准。见 [《御舆》第 7 章](https://lintsinghua.github.io/#ch07)。

## 4. 为什么 Claude Code 可以从文件开始？

### 4.1 代码库本身已经可以查找

编程 Agent 手上已有仓库树、文件搜索、Git 历史和测试工具。对于「某选项的默认值是什么」，读当前分支的定义往往比读几周前生成的记忆更可靠。对于「为何测试环境要单独配置」，代码只给出现在怎样工作，过去被否决的方案、用户的纠正和设计原因才值得留在笔记里。只记无法廉价重建的部分，目录就可以比项目历史小得多。

这也解释了文件工具为什么能承担一部分检索。用户的第一句只有「连接超时」，看不到哪类历史相关。Agent 先从当前失败中识别出集成测试，再搜测试夹具和主题文件，查询就能随证据改变。固定的首轮语义召回更快，也可以作为提前准备的信号。真正的选择在于有没有理由为此多做几步调查。Anthropic 2025 年的工程文章明确把 Claude Code 描述成混合策略，先加载 `CLAUDE.md`，运行中再让模型用 `glob` 和 `grep` 按需查代码。把同样的原则用于项目笔记，是本文对这个设计的解释。见 [Anthropic 的上下文工程文章](https://www.anthropic.com/research/effective-context-engineering-for-ai-agents)。

### 4.2 Markdown 的收益来自接口简单

用普通文本，模型可以沿路径读取一条笔记、直接改其中一句，用户也能打开同一个文件检查。标题、目录和链接让笔记成为可浏览的结构。对已经有文件读写能力的 Agent，这套界面无需为每条笔记建立额外的数据库、嵌入和索引同步流程。需要时，全文搜索也可以直接查到当前磁盘上的文本。

代价随规模变化。目录里只有十几条笔记时，一份简明索引便于导航。几年历史里有数万条事件时，光靠文件名或手写目录，很难稳定回答「哪些同类修复在某次版本迁移后被回滚」。日期和类型过滤、语义候选、访问控制与并发更新，都是换成 SQL 或检索服务的具体理由。它们与模型读写 Markdown 可以处在不同层。团队仍能用文件表达规则，模型仍能决定是否深入追查，事件由数据库提供范围明确的查询。

由此也能解释为什么「更大窗口让向量库失去价值」只在特定条件下成立。当天的本地任务可能有明确文件和足够空间，给每次查询先跑一遍索引收益很小。跨工具、跨项目的记忆即使能塞进窗口，也可能没有成本合理的获取方式。自动注入、模型按需读取和服务检索可以分别负责高频指令、长尾项目经验与大规模历史。

## 5. 主动权可以交给模型到什么程度？

### 5.1 从记下发生过什么，到判断以后什么有用

存一条记忆，其实是在预测未来。Agent 如果只写「连接池排查失败」，未来读到它的模型还得猜失败原因。如果它写下「这次是夹具继承了开发环境配置，切换连接串后测试通过，适用于该夹具仍读取同一配置的情况」，下一轮就有了可验证的假设。它需要综合失败、成功以及用户反馈。固定要求「只记失败」会把证明修复有效的证据排除在外。

Anthropic 的 CL-Bench 数据库任务直接比较了这一点。实验在 Managed Agents 上运行，每道题从新会话开始，模型可通过同一个持久目录复用笔记。Sonnet 4.6 有记忆时的平均奖励为 **0.364**，增加「先读笔记、再验证猜测」的引导后为 **0.641**。在没有这种引导时，Sonnet 5 大约十次里有九次会先读记忆，Sonnet 4.6 则不到一半。另一组实验中，要求只记录失败，削弱了 Opus 5 和 Opus 4.7 原来从记忆获得的收益。见 [Anthropic 原文图 3 和图 5](https://www.anthropic.com/research/components-of-agent-memory)与[第 11 章的读图说明](./agent-memory.md)。

![同一个数据库任务中，显式引导帮助 Sonnet 4.6 使用记忆，而只记失败的规则使几个模型从记忆中得到的收益下降。](/thinking-and-acting/figures/agent-memory-steering.svg)

这组结果比「窗口变长了」更能解释为何现在值得放手。同样有文件可读写，一个模型留下未经验证的猜想，另一个能主动打开笔记、试验假设并记录验明的规则。实验测试的是不同模型与引导的组合，没有把上下文窗口作为独立变量，也没有测量 Claude Code 默认配置的任务表现。它提供的是一条可检验的设计原则：主动读写应由模型在真实任务中的表现来决定，不能只根据支持多少 token 来判断。

### 5.2 模型判断价值，运行时规定边界

| 决策 | 可以让模型判断的部分 | 人或运行时负责的部分 |
| --- | --- | --- |
| 写入 | 从当前任务选择将来可复用的经验，写明条件与证据 | 定义可写作用域，保留用户查看、修改和关闭的入口 |
| 召回 | 判断该查哪个主题，怎样根据新证据修正查询 | 带入必要的启动指令与短索引，限制读取范围和预算 |
| 采用 | 检查旧经验与当前代码、分支和测试是否相符 | 用权限控制必须授权的工具行为 |
| 整理 | 提出合并、补充出处或修正旧结论 | 决定何时重建、共享或正式发布记忆，保留可审查的历史 |

这个分工也解释了为什么「主动权交给模型」不能理解为它独占整个生命周期。模型可以说旧数据库笔记适用于当前任务，工具决定它能不能读取相应目录。模型可以提议把个人偏好写进团队规则，是否共享仍由维护者决定。模型可以把笔记总结成新版本，运行时还要处理范围、预算和并发修改。对可能改变持久行为的决定，这些是可检验的系统约束。

### 5.3 公开行为与内部机制的不同证据

《御舆》第 6 章讨论了 `user`、`feedback`、`project`、`reference` 四类笔记，以及用 fork 复用已有对话来做后台提取。ForceInjection 的分析描述了另一条读取路径，由后台模型从记忆元数据预选相关文件，并讨论了团队目录、`/remember` 和 `autoDream`。这些观察说明「由模型判断相关性」可以发生在主会话，也可以由运行时安排另一轮模型调用。后一种做法仍有调度代码和固定预算，选择时机由运行时掌握。团队目录是否启用、是否同步，预取何时触发、缓存能否复用，取决于具体版本和配置。本文只把官方文档公开的本机目录、索引加载和按需文件访问当作 Claude Code 的可依赖行为。见 [《御舆》第 6 章](https://lintsinghua.github.io/#ch06)和 [ForceInjection 的 Claude Code 源码分析](https://github.com/ForceInjection/AI-fundamentals/blob/main/08_agentic_system/memory/research/case-studies/claude-code-memory-analysis.md)。

## 6. OpenAI 的两条路线：ChatGPT 和 Codex 怎样记忆？ {#openai-memory}

日常说的「GPT 记住了」可能指三件事。ChatGPT 的 Memory 给新聊天提供个人和项目背景，本地 Codex 的 Memories 延续机器上的工作经验，Responses API 的会话状态与压缩则让应用接着处理一条会话。应用用 `previous_response_id` 接续请求，或用 compaction 保留后续轮次所需的状态，仍需另外决定哪些信息值得跨会话保存。下面用 ChatGPT 看长期个人记忆，用本地 Codex 与 Claude Code 做同类比较。见 [OpenAI 的记忆功能说明](https://learn.chatgpt.com/docs/customization/memories)、[会话状态](https://developers.openai.com/api/docs/guides/conversation-state)和[上下文压缩](https://developers.openai.com/api/docs/guides/compaction)。

### 6.1 ChatGPT 从写一条笔记，走到持续修订个人背景

OpenAI 公布过一条可以核对日期的演进线。**2024 年 2 月 13 日**开始小范围测试，**2024 年 4 月**推出 Saved Memories。模型在聊天过程中根据明确请求等强信号保存条目。**2025 年 4 月 10 日**的更新加入对过去聊天的引用。OpenAI 后来披露，这一阶段的后台记忆综合叫 Dreaming V0。**2026 年 6 月 4 日**发布的 Dreaming V3 把跨对话综合放到更核心的位置，并提供可检查和纠正的记忆摘要。摘要展示可能用于个性化的信息要点，部分回复的 Sources 还能指向影响答案的旧聊天等来源。OpenAI 公布的是用户可见的控制和设计目标，公开资料没有给出 ChatGPT 后端的存储格式、索引类型或逐轮召回算法。见 [2024 年公告及 2025 年更新](https://openai.com/index/memory-and-new-controls-for-chatgpt/)、[2026 年 Dreaming 公告](https://openai.com/index/chatgpt-memory-dreaming/)和 [Memory 帮助文档](https://help.openai.com/en/articles/8590148-memory-in-chatgpt)。

这条路线解决的难题是**何时修正一个曾经准确的事实**。OpenAI 用旅行举例：出发前「计划去新加坡」可以帮助做行程，旅行结束后适合当作过去的经历，不能继续拿它回答「我今晚附近有什么」。回到数据库案例，用户先说「这个月先用临时容器跑集成测试」，下个月又说「CI 已迁移到托管测试库」。只保存第一条会留下过期指令，按「集成测试」检索则可能同时命中两条。真正需要综合的是两条说法的时间、范围和关系。即便 ChatGPT 能从过去聊天复原迁移背景，当前仓库到底读哪份配置，仍要由当前证据回答。项目专属记忆可以限制可引用的对话范围，解决的是来源边界。见 [OpenAI 的时效性评估](https://openai.com/index/chatgpt-memory-dreaming/)和 [Projects 文档](https://help.openai.com/en/articles/10169521-projects-in-chatgpt)。

这里还有一个容易混淆的层次。用户纠正了记忆摘要，并不等于改写了旧聊天。如果原始对话仍在历史里，关闭再打开记忆时，系统可能从旧聊天重新生成记忆。摘要是由来源派生的内容，更新展示层与处理原始来源需要各自的控制。OpenAI 的产品评估分开看跨聊天事实、偏好约束和时效性，这三个目标比测试「能不能背出旧句子」更贴近实际使用。见 [Memory 帮助文档](https://help.openai.com/en/articles/8590148-memory-in-chatgpt)和 [Dreaming 评估说明](https://openai.com/index/chatgpt-memory-dreaming/)。

### 6.2 本地 Codex 用 Markdown，也用后台提取和整理

本地 Codex 与 ChatGPT 网页端使用不同的记忆存储。启用本地记忆后，Codex 从符合条件的旧会话提取内容，后台更新记忆文件。写入路径分两步，先把单次会话提取成带来源的记录，再汇总多个会话，生成供未来任务使用的文件。公开的 v1 实现用 SQLite 状态库协调提取和整理任务，用 `memory_summary.md` 提供启动线索，并将可搜索的经验手册 `MEMORY.md` 与 `rollout_summaries/` 中的会话摘要留给模型按需读取。数据库管作业和中间状态，文件给模型提供可读的内容。这两层可以同时存在。见 [本地记忆文档](https://learn.chatgpt.com/docs/customization/memories)和 [Codex 记忆流水线](https://github.com/openai/codex/blob/main/codex-rs/memories/README.md)。

**2026 年 10 月 27 日**，Codex CLI 0.165.0 的发布说明记录了新的默认选择。启用记忆的全新 CLI 配置通常采用 v2，已有 v1 库默认可以继续用 v1，配置也能显式选择版本。v2 继续保留 `memory_summary.md` 与逐会话摘要，但其整理路径不再生成 `raw_memories.md`，也不要求维护 v1 那样的 `MEMORY.md` 手册。其提取逻辑优先保留用户输入等高价值证据，保留任务的时间顺序、来源、作用域与不确定性，读取提示再引导模型为有必要的任务选择性回查历史。团队必须遵循的构建流程仍适合放进 `AGENTS.md` 或受版本控制的文档。见 [0.165.0 发布说明](https://github.com/openai/codex/releases/tag/rust-v0.165.0)、[v2 证据选择](https://github.com/openai/codex/pull/43799)、[逐会话提取变更](https://github.com/openai/codex/pull/43800)和 [v2 整理与读取变更](https://github.com/openai/codex/pull/43813)。

这个改动让「把判断交给模型」更具体。想象旧会话里，用户说「**这次**用临时数据库」，模型却在结束时把它概括为「这个项目应该用临时数据库」。如果第一轮摘要消掉了「这次」，第二轮整理就可能把一句临时要求提升为通用建议。多一层手册确实能让常见问题少翻一次历史，也给过度概括增加了一次机会。v2 的变化可以理解为**少做一层跨任务归纳，保留足够的线索，让接手任务的模型回到合适的历史证据再判断**。逐会话摘要仍可能丢细节，回查还会多消耗读取和推理资源。这个解释依据公开变更，本文没有跨版本性能对照。见 [Codex v2 的提取与整理设计](https://github.com/openai/codex/pull/43800)。

### 6.3 真正的分歧在于什么时候概括

| 路线 | 提前做的工作 | 当前任务还要判断什么 |
| --- | --- | --- |
| Claude Code 原生 auto memory | 会话中写项目经验，维护启动时加载的短索引 | 这个问题有没有旧笔记可读，笔记的验证条件是否仍成立 |
| 本地 Codex v2 | 后台提炼单次会话，综合出短摘要和回查线索 | 是否需要沿会话证据追查，当时的纠正只适用于一次任务还是可以复用 |
| ChatGPT Dreaming | 跨聊天综合个人背景，修正随时间变化的事实 | 哪些背景与眼前问题相关，是否需要回到来源澄清 |

这张表比较的是公开的主要路径。ChatGPT 要在多年聊天里维持个人背景的一致性，提前综合能减少每轮重新推导。Codex 的数据库案例里，决定是否复用修复的证据往往藏在某次测试、某个分支或用户的一句限定中，较早把它写成跨任务规则容易误用。Claude Code 用本地项目笔记处理这类经验，在启动成本与人工可查之间作了另一种取舍。三种产品的共同问题是**先判断该概括到什么程度，再决定什么时候让当前模型回到证据**。上下文更宽、读工具更强，让后一种选择更可行。存储规模、隐私边界和重复查询的成本，仍会影响要把多少工作提前完成。见 [Claude Code 的记忆文档](https://code.claude.com/docs/en/memory)、[Codex Memories](https://learn.chatgpt.com/docs/customization/memories)和 [ChatGPT Dreaming](https://openai.com/index/chatgpt-memory-dreaming/)。

## 7. 什么时候需要更复杂的记忆？

### 7.1 当你要找的是当时怎么验证的

项目笔记应当尽量短，但摘要无法保证保住未来需要的细节。如果那次只在假数据库上运行过测试，下个月换了真实数据库，一句「改连接串有效」就可能让模型误诊。保留可检索的原始轨迹，让模型在需要时回到原始测试命令和结果。Claude-Mem 的时间线便于在大量历史中把怀疑、修改和验证还原到正确顺序。Supermemory 解决的另一类问题是多应用访问同一个记忆服务，扩大了可见范围，同时要决定哪些内容进入服务、哪些客户端有权读取和删除。插件在这里提供的是需要明确成本和作用域的能力。见 [Claude-Mem 系统分析](https://github.com/ForceInjection/AI-fundamentals/blob/main/08_agentic_system/memory/research/case-studies/claude-mem-system-analysis.md)与 [Supermemory 集成分析](https://github.com/ForceInjection/AI-fundamentals/blob/main/08_agentic_system/memory/research/case-studies/supermemory-agent-integration-analysis.md)。

原始轨迹和项目笔记还有不同的留存期。Claude Code 文档说明，本机旧会话记录会随清理设置过期，auto memory 文件不随同一规则清理。给主题笔记写一个会失效的会话引用，时间一长就可能只剩结论。需要长期审查的事实应有能独立复查的来源，例如提交号、仓库里的决策记录或仍可运行的验证。见 [Claude Code 的存储与保留说明](https://code.claude.com/docs/en/memory#storage-location)。

### 7.2 当同一种跨文档调查会反复发生

将经验整理成 wiki，就是提前做一部分将来可能重复的调查。Anthropic 研究中的一组并购问题经常需要跨文档判断或计算，使用 wiki 的得分为 **87%**，只用搜索为 **73%**。另一组法律任务多数条件可在一份文档找到，wiki 没有显示同样收益。这个差异解释了什么时候值得为整理支付成本：反复回答的难点在跨来源连接时，预先组织有机会省掉重复劳动。偶尔查一条明确事实，可以直接定位原文。见 [Anthropic 原文图 11](https://www.anthropic.com/research/components-of-agent-memory)与[第 11 章](./agent-memory.md)。

![Anthropic 的不同任务显示，wiki 的收益随问题需要的跨文档推理与任务类型而变化。](/thinking-and-acting/figures/agent-memory-wiki-when.svg)

自动整理同样有成本。当在场的模型已经相信一条错误笔记，继续让它归纳自己的结论可能会巩固错误。若在独立任务中把笔记拿回去和原始记录对照，就有机会找出冲突。Anthropic 的 Managed Agents **Dreams** 是这种设计的公开实例，异步读取过去会话与现有记忆，产出可审查的新存储。它与第三方分析里提到的 Claude Code `autoDream` 属于不同的证据范围。运行中即时记录负责留下线索，离线整理负责重新判断线索是否还可信。见 [Managed Agents Dreams 文档](https://platform.claude.com/docs/en/managed-agents/dreams)。

## 8. 怎样判断自己的 Agent 该装哪一层？

用开头的数据库问题做一次具体的对照。准备历史会话，包括早期的错误推测、最终验证、一次无关修改，再加一个项目迁移后已不适用的旧修复。新任务从相同提交开始，分别给 Agent 四种条件。

| 条件 | 要检验的问题 |
| --- | --- |
| 只给仓库与当前问题 | 重新调查需要多少步，是否本来就足够准确？ |
| 预先装入相同的原始轨迹 | 更多过程证据是否减少调查，旧猜测是否反而增加误判？ |
| 给短 Markdown 索引，允许按需读主题和轨迹 | 它能否察觉有记忆可用、找到入口并验证旧结论？ |
| 查询同一批历史的全文或语义索引 | 当路径或用词变化时，额外检索能否找回文件方案漏掉的事件？ |

这个对照方案没有在本文中运行。实际比较时，固定模型、工具与同一任务的输入材料，记录输入、工具步数、端到端耗时，以及原本能做对的任务有多少受历史误导。若想单独检验主动权，把索引和候选保持相同，再比较每次自动注入详情和由模型决定何时展开。单看使用了多少 token，很难判断节省的是无关输入，还是一次关键的复验。相关工程实践见 [Learn Agent by Rust 的跨会话记忆](/learn-agent-rust/memory)和[上下文压缩](/learn-agent-rust/context-compaction)。

::: warning 常见误区

- **将能装下等同于会使用。** 原始历史能进窗口，还要看其中的证据能否被找到和正确使用。
- **用召回分数代替适用性。** 旧修复可以和当前故障极为相似，却依赖已经移除的测试夹具。
- **把会话压缩当成跨会话学习。** 继续当前任务的摘要和供未来任务复用的经验，有不同的写入目标。
- **把研究设置套到产品默认行为。** 受控的记忆文件夹实验和源代码解读各有作用，各自能支持的结论取决于任务、版本和运行环境。

:::

## 本章结论

Claude Code 的选择可以从编程的日常需求理解。大多数当前事实已经有可搜索的路径，真正稀缺的是代码无法说明的经验。把这部分经验写成简短、可编辑、能回到证据的文件，再让模型根据当前任务逐步读取，就能复用已有文件工具。启动限额、人维护的指令与工具权限使这项自由有明确边界。

上下文变大，降低了提前切碎和压缩所有信息的必要性。更强的模型则让读什么、写什么和是否相信旧结论这些判断可以推迟到有任务、有证据的时候。两种变化一起解释了为什么原本看起来需要一个复杂记忆组件的问题，今天有时可以用 Markdown 和文件工具解决。若困难在规模、跨应用共享或密集的跨文档关联，外部索引与离线整理仍有明确价值。

OpenAI 的两个例子补上了另一半。ChatGPT 用后台综合持续修订会变化的个人背景，Codex v2 则保留短导航和逐任务来源，把部分概括推迟到读时。设计记忆时可以先问：未来的任务是否有足够证据推翻旧结论？这个问题决定哪些内容适合直接注入，哪些只应留下线索。

## 检查理解

1. 同一个模型的窗口扩大十倍，为什么一个从零开始的新会话仍可能从未读到上个月的笔记？

   <details><summary>参考答案</summary>

   窗口大小决定可装多少输入。持久化、加载规则和读取决策决定笔记是否进入输入。缺失的索引条目或一次没发生的工具调用，都会让笔记继续留在磁盘。

   </details>

2. 为什么 Anthropic 的 Sonnet 4.6 与 Sonnet 5 结果，可以用来讨论模型的记忆主动权，却不能证明长窗口使检索失去价值？

   <details><summary>参考答案</summary>

   实验观察了模型怎样在同一个任务设置中打开文件、写入和验证经验，也改变过提示引导。它没有单独改变窗口大小来测量因果效应，也没有用同一套数据比较所有外部索引方案。

   </details>

3. 模型找到了准确描述旧故障的笔记，仍然改错了当前代码。应该优先检查检索还是记忆的使用？

   <details><summary>参考答案</summary>

   先检查模型是否验证了迁移前后的前提差异。候选已经找对，再提高召回率不会提供这个判断。让笔记保留验证入口，再用当前配置与测试对照，才可能阻断错误复用。

   </details>

4. Codex v2 取消对总手册的要求后，为什么逐会话摘要仍然有意义？

   <details><summary>参考答案</summary>

   它保留某个结论何时、因何而出现，以及当时的问题和范围。启动摘要先帮助 Agent 判断是否值得追查。需要应用旧经验时，再沿着任务来源确认用户说的是「这一次」还是一项长期要求。省下跨任务归纳的同时，也把一部分查证成本留到了当前任务。

   </details>

## 参考资料

- 研究史与对照实验。[RAG（2020）](https://arxiv.org/abs/2005.11401)、[Generative Agents（2023）](https://arxiv.org/abs/2304.03442)、[MemGPT（2023）](https://arxiv.org/abs/2310.08560)、[Lost in the Middle（2023）](https://arxiv.org/abs/2307.03172)、[RAG or Long-Context LLMs?（2024）](https://arxiv.org/abs/2407.16833)、[MemDev-Bench（2026，预印本）](https://arxiv.org/abs/2610.27524)。
- Anthropic 的产品和研究。[早期 Claude Code 实践](https://www.anthropic.com/research/claude-code-best-practices)、[Agent 上下文工程](https://www.anthropic.com/research/effective-context-engineering-for-ai-agents)、[Claude Code 记忆文档](https://code.claude.com/docs/en/memory)、[上下文窗口](https://code.claude.com/docs/en/context-window)、[Agent 记忆的组成部分](https://www.anthropic.com/research/components-of-agent-memory)、[Managed Agents Dreams](https://platform.claude.com/docs/en/managed-agents/dreams)。
- OpenAI 的产品史与官方实现。[ChatGPT 记忆早期公告与更新](https://openai.com/index/memory-and-new-controls-for-chatgpt/)、[Dreaming](https://openai.com/index/chatgpt-memory-dreaming/)、[Memory 帮助文档](https://help.openai.com/en/articles/8590148-memory-in-chatgpt)、[本地 Codex Memories](https://learn.chatgpt.com/docs/customization/memories)、[Codex v2 实现变更](https://github.com/openai/codex/pull/43813)、[Codex CLI 0.165.0 发布说明](https://github.com/openai/codex/releases/tag/rust-v0.165.0)。
- ForceInjection 的三篇案例。[Claude Code Markdown 记忆](https://github.com/ForceInjection/AI-fundamentals/blob/main/08_agentic_system/memory/research/case-studies/claude-code-memory-analysis.md)、[Claude-Mem 系统](https://github.com/ForceInjection/AI-fundamentals/blob/main/08_agentic_system/memory/research/case-studies/claude-mem-system-analysis.md)、[Supermemory Agent 集成](https://github.com/ForceInjection/AI-fundamentals/blob/main/08_agentic_system/memory/research/case-studies/supermemory-agent-integration-analysis.md)。
- 《御舆》的实现分析。[第 6 章 · 长期记忆](https://lintsinghua.github.io/#ch06)、[第 7 章 · 工作记忆](https://lintsinghua.github.io/#ch07)。

[返回全书总览](./index.md) · [回看第 11 章：Agent 记忆的四层结构与实验](./agent-memory.md) · [工程实践：跨会话记忆](/learn-agent-rust/memory)
