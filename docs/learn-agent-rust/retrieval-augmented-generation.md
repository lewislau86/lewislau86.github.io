---
title: "第 11 章：RAG：检索、证据与回答"
description: "用独立 Rust 实验学习真实文档切块、BM25、范围过滤、上下文预算、引用校验和索引更新，并区分检索指标与生成质量。"
pageClass: learn-agent-rust-course
prev:
  text: 第 10 章 · 按需加载技能
  link: /learn-agent-rust/skill-loading
next:
  text: 第 12 章 · 上下文压缩
  link: /learn-agent-rust/context-compaction
---

# 第 11 章：RAG：检索、证据与回答

[课程总览](./index.md) · [上一章](./skill-loading.md) · [学习路径](./learning-path.md#k01) · [下一章](./context-compaction.md)

::: tip 本章学习目标
- 从一个升级问题出发，解释文档、chunk、索引、检索和生成各自的职责。
- 运行真实词法检索，核对范围、来源行号、上下文预算和资料更新。
- 分开评价候选命中、引用有效和答案正确，并解释何时需要语义检索与重排。

**前置：** [工具注册与图调度](./tools-and-graph.md)、[工具权限](./permissions.md)、[按需加载技能](./skill-loading.md)。概念区别先看[关系导读](./knowledge-and-capabilities.md)。

**实践方式：** 下载<a href="/learn-agent-rust/retrieval-augmented-generation.zip" download>独立 RAG 工程</a>，Rust 1.99.1，仅标准库；无需密钥、网络或数据库。本章为主线第 11 章；统一实验包保留稳定标识 K01，供原命令与证据定位。
:::

上一章让助手按需读取“怎样做升级审查”。现在它要回答一个具体问题：“升级到 v2 要求哪个 Rust 版本？”技能可以要求每项结论附来源，但实际版本必须从项目资料中找到。

我们准备四份小型 Markdown 资料：当前发布说明、运维步骤、一条含恶意指令的导入工单，以及另一个项目范围的私有说明。目标是从正确范围里取出相关段落，把它交给回答环节，最后核对引用。

<LearnAgentRustMap active="retrieval-augmented-generation" />

<!-- experiment-library:start -->

全书实验可从[统一代码库](./experiments.md#retrieval-augmented-generation)下载；解压后进入 `chapters/retrieval-augmented-generation/`，或在代码库根目录运行 `python3 run.py run K01`。

<!-- experiment-library:end -->

::: info 实验范围与代码来源
完整工程位于 `docs/public/learn-agent-rust/code/retrieval-augmented-generation/`，下文片段均从<a href="/learn-agent-rust/code/retrieval-augmented-generation/src/main.rs" download>完整 main.rs</a>导入；<a href="/learn-agent-rust/code/retrieval-augmented-generation/README.md" download>运行说明</a>随 zip 提供。

切块、BM25、范围过滤、磁盘读写、过期检查和引用校验真实执行。生成器是“摘录第一条证据”的确定性夹具，用于检查接口；没有调用神经模型、embedding 模型或向量数据库，也尚未接入两库主循环或 MCP。本文给出替换这些边界的路径，未运行的部分明确列出。
:::

## 1. 先找证据，再组织答案

RAG 的全称是 Retrieval-Augmented Generation。原始论文将生成模型与可检索的外部知识结合；本文从工程上拆成“查到哪些证据”和“如何据此回答”两段。论文的具体实现使用密集索引和神经检索器，本实验先用可检查的词法基线理解数据流。见 [Lewis 等，2020](https://arxiv.org/abs/2005.11401)。

假设发布说明有一句：“Upgrade v2 requires Rust 1.99.1.” 要回答版本要求，至少需要三种可观察结果：

| 结果 | 要核对的对象 | 出错时的例子 |
| --- | --- | --- |
| 证据候选 | 当前可访问的正确段落 | 取到了另一个项目的私有发布说明。 |
| 生成输入 | 实际交给回答环节的片段与来源 | 检索命中后因预算被丢弃，模型没有看到它。 |
| 输出依据 | 引用及其支持的结论 | 引用存在，但答案把 1.99.1 写成了 1.90。 |

仅仅把资料放进数据库还没有完成这三步。我们沿一条问题链路逐一验证。

![真实资料先切块并按范围检索，再检查来源和预算，最后由固定摘录夹具生成带引用的输出并独立核对。](/learn-agent-rust/figures/k01-rag-pipeline.svg)

从上往下读：上层决定证据从哪里来，中层决定证据是否还能使用，下层才处理回答。右下角的校验由宿主执行。

## 2. 文档怎样变成可检索的 chunk

整份文件可能包含版本要求、回滚和发布检查。直接把它当作一个检索单元，短问题可能带入大量无关内容。我们按段落切块，标题作为元数据；每块保留原文件的起止行号和完整来源快照。

<<< @/public/learn-agent-rust/code/retrieval-augmented-generation/src/main.rs#records

`Chunk` 是一个可独立引用的片段。`Hit` 在片段上增加查询相关度；`Claim` 记录回答环节声明的摘录与引用。三者分开后，检索结果不必直接成为最终答案。

<<< @/public/learn-agent-rust/code/retrieval-augmented-generation/src/main.rs#chunking

`release.md` 的第 3 行形成版本要求块，第 5 行形成回滚块。若一段跨多行，引用保留整个范围。标题中的 `v2` 随证据输出；显示指纹随整个文件变化，让新旧来源容易区分。

这里使用 FNV 作为显示指纹。它不用于防篡改，过期判断直接比较完整来源文本；下载包和验证证据使用 SHA-256。索引只保存在当前进程的 `Vec<Chunk>` 中，每次 `query` 重新读文件。

段落切块适合这个短小语料。真实手册可以按标题层级、token 长度或代码结构切分，并保留适当重叠。切得太小，条件与结论可能分离；切得太大，检索相关度和上下文预算容易被无关内容稀释。选择时应观察带标签查询上的召回及最终证据长度。

## 3. 用 BM25 建立能解释的基线

先预测：`upgrade Rust` 应该召回哪个段落？另一个范围 B 的文档也含 `upgrade`，它应当有机会参与排序吗？

本例先根据宿主给定的 `scope` 过滤，再计算 BM25 词频统计和得分，最后取前两名。算法代码采用常见的正值 IDF 形式，参数固定为 $k_1=1.2$、$b=0.75$；正值 IDF、参数含义与同样的默认参数见 [Lucene 9.12.1 的 BM25 文档](https://lucene.apache.org/core/9_12_1/core/org/apache/lucene/search/similarities/BM25Similarity.html)。

$$
\operatorname{score}(q,d)=\sum_{t\in q}
\log\left(1+\frac{N-\mathrm{df}(t)+0.5}{\mathrm{df}(t)+0.5}\right)
\frac{\mathrm{tf}(t,d)(k_1+1)}{\mathrm{tf}(t,d)+k_1(1-b+b|d|/\mathrm{avgdl})}
$$

| 符号 | 本例中的含义 |
| --- | --- |
| $N$ | 当前范围可见的 chunk 数。 |
| $\mathrm{df}(t)$ | 可见片段中包含查询词 $t$ 的片段数。 |
| $\mathrm{tf}(t,d)$ | 该词在片段 $d$ 中出现的次数。 |
| $|d|$、$\mathrm{avgdl}$ | 片段词数与当前可见片段的平均词数。 |

直觉上，少见词更能区分文档，同一个词重复很多次的收益会逐步变小，长段落也会做归一化。本例对查询词去重，同分按稳定的引用 ID 排序；零分候选直接排除。

<<< @/public/learn-agent-rust/code/retrieval-augmented-generation/src/main.rs#retrieval

为什么过滤放在排序前？这样另一个范围的文档既不能进入返回结果，也不会改变当前范围的词频和得分。本例的范围 A/B 是宿主已确定身份的模拟输入；真实服务必须从认证会话解析范围，不能接受模型自行声明身份。

本例只实现英文 ASCII 分词，没有中文分词、停用词或词形还原。请保留这个边界：这是一个检索教学基线，其零分规则也只是本例规则，不是可以直接迁移到任意 embedding 得分上的阈值。

## 4. 相关候选怎样成为本轮证据

相关度排序之后，还有两个问题：资料是否仍是当前版本？本轮能放下多少内容？

代码逐条重新读取命中的来源文件，与建索引时的完整快照比较。文件变了就返回 `stale_index`，被删除就返回 `source_missing`。通过以后才按排名装入预算；一个片段放不下就跳过，继续尝试后面的片段。

<<< @/public/learn-agent-rust/code/retrieval-augmented-generation/src/main.rs#context

这个预算统计序列化证据块的 Unicode 字符数，包含引用和标题等包装；它没有计算整个模型请求，也不是模型 tokenizer 的 token 数。接入模型以后，应给系统策略、历史、工具 schema 和预期输出留出预算，再用实际 tokenizer 计算证据额度。历史裁剪与摘要的完整实验见[下一章](./context-compaction.md)。

`generate_fixture` 是替换边界：它从最终上下文摘录第一条证据，不会猜答案。`validate_claim` 独立核对引用属于本轮集合、摘录非空且确实出现在对应原文。没有片段可用时，返回 `abstain=no_evidence`。

这套检查适用于本例的逐字摘录契约。真实模型通常会改写或综合多个来源：引用有效只能证明来源存在，还要评估事实支持、多来源冲突和任务完成。不能把这里的子串检查直接当作任意自然语言结论的事实判定器。

## 5. 动手：观察正常、无证据与资料过期

解压独立工程后运行：

```sh
cargo test --locked --offline
cargo clippy --locked --offline -- -D warnings
cargo run --locked --offline -- query corpus A 'upgrade Rust'
cargo run --locked --offline -- suite /tmp/my-rag-lab
```

`suite` 要求目标目录尚不存在，并保留它供检查。它创建教学资料，读入索引，在同一进程中修改再删除发布说明，真实制造索引过期。不要将已有资料目录作为套件目标。`query` 只读工程自带的 `corpus`。

正常查询的实际输出：

<<< @/public/learn-agent-rust/outputs/k01-query.txt

引用中的 `A` 是范围，`release.md` 是文件，`L3-L3` 是来源行，末尾是显示指纹。下面是整套实验的实际轨迹：

<<< @/public/learn-agent-rust/outputs/k01-suite.txt

| 场景 | 实际观察 | 解释 |
| --- | --- | --- |
| normal | 摘录 Rust 1.99.1 要求并带引用 | 证据选取与输出契约通过。 |
| no-hit / budget | 返回无证据 | 分别是未命中和候选装不下。 |
| scope | 当前范围没有私有内容泄漏 | 先过滤，再评分与装入上下文。 |
| injection | 恶意文字只作为数据摘录，动作数为零 | 固定夹具没有动作接口；真实模型注入抵抗尚未验证。 |
| bad-citation | 拒绝伪造来源和不在原文的摘录 | 校验与生成分离。 |
| stale / updated | 旧索引拒绝；重建后读到替换文本 | 资料更新必须进入索引生命周期。 |
| deleted | 旧候选拒绝；重建后没有结果 | 删除也会影响证据有效性。 |

更新场景的 `Rust 2.00.0` 是合成替换文本，只用来观察数据更新，不表示真实版本或升级建议。

验证器实际检查源码与解压后的 zip，两边独立编译、执行并比较输出，同时核对文件确实被删除、其他资料保持原内容、已有目录被拒绝且内容保留。Rust 的 8 项测试覆盖排序、范围与统计隔离、稳定排序、空查询、引用、行号、预算边界和来源过期。<a href="/learn-agent-rust/outputs/k01-suite.txt" download>下载轨迹</a>；仓库维护命令为 `python3 scripts/verify-agent-rag.py --check`。

## 6. 分开评估检索与回答

我们公开四道小型教学查询及其相关块：版本要求、数据库备份、回滚，以及词面不重合的 `revert disaster`。最后一题的目标块含 `Rollback`，当前分词器找不到它。完整标签和评估逻辑也在唯一源码中：

<<< @/public/learn-agent-rust/code/retrieval-augmented-generation/src/main.rs#evaluation

每题只有一个标注相关块。Recall@2 表示它进入前两名的查询比例；MRR@2 对前两名中的首个相关位置取倒数，再对所有查询平均，未命中记零。本例三题都排第一，一题未命中，所以两项均为 0.75。

![四道公开教学查询的 Recall@2 和 MRR@2 均为 0.75，其中同义表达查询未召回，指标只描述本次词法检索。](/learn-agent-rust/figures/k01-retrieval-results.svg)

左边读实际检索指标，右边读被保留的失败。语料和标签都公开、规模很小，没有独立隐藏测试；这个数值用于检查教学链路，不能据此判断生产检索或真实模型质量。

真实系统可以按下面的层次单独记录结果：

| 层次 | 可用指标或检查 | 需要的独立信息 |
| --- | --- | --- |
| 检索 | Recall@k、MRR@k、范围泄漏、来源时效 | 预先标注的相关证据集合。 |
| 上下文 | 相关证据是否实际装入、长度与冗余 | 最终请求中的证据记录。 |
| 回答 | 引用有效率、结论支持度、任务正确率、适当拒答 | 人工或独立评估标签。 |
| 运行 | 延迟、费用、更新延迟和失败恢复 | 真实请求与索引维护记录。 |

## 7. 同义表达失败以后：向量、混合检索与重排

下一步可以保持语料、标签和预算固定，只替换检索方式。每种方法解决的问题应先说清楚：

| 方法 | 工作方式 | 需要补做的证据 |
| --- | --- | --- |
| 词法检索 | 按词面及统计相关度排序 | 中文分词、缩写、代码符号与业务词表上的失败。 |
| 密集向量检索 | 用 embedding 模型把查询、片段编码到同一检索空间，按相似度找邻居 | 模型与 revision、查询/文档前缀、归一化、领域和语言上的召回。 |
| 混合检索 | 合并词法与向量候选，可用 RRF 按名次融合 | 同一查询集上的增益、额外延迟与丢失的精确匹配。 |
| 重排 | 对已召回的查询与片段对进一步评分 | 在候选固定时是否改善排序，以及时间预算。 |

以归一化向量为例，余弦相似度衡量两个向量的方向接近程度。向量来自经过训练的编码器，质量取决于模型与任务；手写几组数字可以解释几何，却不能证明语义召回。短问题匹配长文档属于非对称检索，要核对模型要求的查询与文档编码方式。见 [Sentence Transformers 的语义检索说明](https://sbert.net/examples/sentence_transformer/applications/semantic-search/README.html)。

RRF 的一个常见形式是将每个候选在不同列表中的 $1/(c+\mathrm{rank})$ 相加。它按名次合并，避免直接相加两种不同尺度的分数；常数和候选数量应在开发集选择。重排则在较小候选集上使用更精细的相关度模型，参见官方 [Retrieve & Re-Rank](https://sbert.net/examples/sentence_transformer/applications/retrieve_rerank/README.html)。本实验没有实现或测量这三种扩展。

接入向量库时还要保留 chunk 与来源版本的对应、更新/删除策略和范围过滤。索引参数变了、embedding 模型变了或切块策略变了，都应产生新索引版本；不能把旧文档向量和新查询编码器混用后继续沿用原指标。

## 8. 在 Agent 里放在哪里

将本例接到已有循环时，可以注册一个 `search_docs(query)` 工具：范围来自宿主，工具返回片段 ID、来源、版本、正文和分数；模型从工具结果继续回答。也可以由宿主在调用模型前固定检索，此时问题改写与检索次数由应用编排控制。

两种方式都需要保留最终证据集合。如果模型自主决定检索，还应增加查询次数、反复改写、超时与停止上限。工具通过本地函数还是 MCP 暴露，是连接选择；检索质量和引用依据仍由相同契约验收。外部连接的真实实验见 [R19](./mcp-tools.md)。

与其他输入的关系可以沿[概念导读](./knowledge-and-capabilities.md)复查：Skills 提供做事方法，RAG 提供这次问题的资料，Memory 提供历史事实，[R10](./system-prompts.md)负责把来源清楚地放入每轮请求。新检索工具与 R20 的组合尚未实现；不能将本章通过计入 R20 的既有集成证据。

::: warning 常见误区
- 检索得分高只说明算法相关度，引用存在也只证明来源可定位。结论是否被支持仍需检查。
- 证据包装与角色提示可以帮助模型理解来源，但不能代替宿主的权限控制；固定夹具没有验证真实模型的注入抵抗。
- 本例当前性检查只覆盖组装时的本地文件，没有锁住外部世界。高风险动作前可能还需重新确认版本与业务状态。
- 字符预算、英文分词、内存全扫描和读取完整快照适合小型教学资料；生产方案需独立测量与设计。
:::

## 本章结论

先把证据生命周期做成可以检查的链路：切块保留来源，按范围检索，核对当前版本，在预算内组装，再独立检查回答依据。本章用 BM25 和固定摘录建立基线，保留同义表达失败；后续替换 embedding、重排或生成模型时，继续沿同一组可观察边界验收。

## 迁移思考：检索命中与回答有据分开验收

相关文档排在第一位，是否足以接受模型给出的升级结论？

<details><summary>参考推演</summary>

先核对当前可访问的文档版本、引用与原文，再核对结论是否由证据支持；召回率只评价候选集合。

换成售后知识库时，同样要把订单访问范围、政策时效与答案依据分别检查。

这是迁移推演，不是新增运行结果。

</details>

## 检查理解

1. 为什么不能先从全库取 top-2，再删除另一个范围的结果？

   <details><summary>参考答案</summary>

   无权访问的片段会占用候选名额，词频统计也受它影响。本例在排序前过滤，并用测试确认加入 B 范围文档不会改变 A 范围得分。

   </details>

2. 检索已经命中，为什么预算场景仍拒答？

   <details><summary>参考答案</summary>

   检索候选和最终上下文是两个集合。一个字符的预算装不下完整证据包装，生成器收到空集合，所以返回无证据。

   </details>

3. 文档更新后，旧索引里的引用还保留原文，为什么要拒绝？

   <details><summary>参考答案</summary>

   当前问题要求最新资料。本例比较完整来源快照，发现变化后要求重建。若业务要回答历史版本，应显式选择历史快照，并标明时间口径。

   </details>

4. 引用 ID 正确、原文里也有“Rust”，能证明任意含 Rust 的结论吗？

   <details><summary>参考答案</summary>

   不能。本例只接受逐字摘录，校验整个摘录是否属于指定片段。改写、否定关系、数字变动与跨文档推断需要更完整的事实支持评估。

   </details>

5. 怎样公平比较 BM25 与新 embedding 模型？

   <details><summary>参考答案</summary>

   固定语料版本、切块、范围、查询集、相关标签、top-k 和上下文预算；在开发集选择参数，再用独立测试集比较召回、排序和运行代价，最后单独评估生成质量。

   </details>

## 参考资料

- [Lewis 等：Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks](https://arxiv.org/abs/2005.11401)，2020：RAG 原始论文，具体神经结构与本文基线范围不同。
- [Lucene 9.12.1：BM25Similarity](https://lucene.apache.org/core/9_12_1/core/org/apache/lucene/search/similarities/BM25Similarity.html)：IDF、词频饱和、长度归一化与默认参数。
- [Sentence Transformers：Semantic Search](https://sbert.net/examples/sentence_transformer/applications/semantic-search/README.html)：非对称检索与查询/文档编码。
- [Sentence Transformers：Retrieve & Re-Rank](https://sbert.net/examples/sentence_transformer/applications/retrieve_rerank/README.html)：候选召回与重排的职责。

资料查阅：2026-11-08。接下来进入[第 12 章：上下文压缩](./context-compaction.md)，处理方法、证据和历史不断累积时的输入预算。
