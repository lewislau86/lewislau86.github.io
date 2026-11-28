---
title: "第 11 章：RAG：检索、证据与回答"
description: "用 ADK-Rust 3.0 的 adk-rag 实现切块、向量检索与范围隔离，由宿主核对来源时效、上下文预算与引用，再把检索交给 Agent 并检查最终回答的引用。"
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
- 从一个升级问题出发，解释文档、chunk、embedding、向量库、检索和生成各自的职责。
- 用 adk-rag 的 `RagPipeline` 完成切块、向量检索和范围隔离，再由宿主核对来源时效、上下文预算和引用。
- 分开评价候选命中、引用有效和答案正确，并在只换 embedder 的条件下比较两种检索。

**前置：** [工具注册与图调度](./tools-and-graph.md)、[工具权限](./permissions.md)、[按需加载技能](./skill-loading.md)。概念区别先看[关系导读](./knowledge-and-capabilities.md)。

**实践方式：** 下载<a href="/learn-agent-rust/retrieval-augmented-generation.zip" download>独立 RAG 工程</a>，按[第 5 节](#hands-on)取一次 ADK-Rust 源码后运行；运行时不需要密钥、网络服务或数据库。本章为主线第 11 章；统一实验包保留稳定标识 K01，供原命令与证据定位。
:::

::: info 本章已迁移到 ADK-Rust 3.0
本章实验基于 ADK-Rust 3.0 发布候选版的 adk-rag（固定提交，尚未发布到 crates.io）。旧版本章只用标准库，手写了 BM25 检索，可从 git 标签 `learn-agent-rust-v1` 取得。新版的切块入库、向量检索和范围隔离由框架执行，embedding 换成了一个可以逐行读懂的词袋向量；来源时效、预算和摘录校验仍由宿主负责。第 7 节的对应表列出了变化。
:::

上一章让助手按需读取“怎样做升级审查”。现在它要回答一个具体问题：“升级到 v2 要求哪个 Rust 版本？”技能可以要求每项结论附来源，但实际版本必须从项目资料中找到。

我们准备四份小型 Markdown 资料：当前发布说明、运维步骤、一条含恶意指令的导入工单，以及另一个项目范围的私有说明。目标是从正确范围里取出相关段落，把它交给回答环节，最后核对引用。

<LearnAgentRustMap active="retrieval-augmented-generation" />

<!-- experiment-library:start -->

全书实验可从[统一代码库](./experiments.md#retrieval-augmented-generation)下载；解压后进入 `chapters/retrieval-augmented-generation/`，或在代码库根目录运行 `python3 run.py run K01`。

<!-- experiment-library:end -->

::: info 实验范围与代码来源
下文片段均从<a href="/learn-agent-rust/code/retrieval-augmented-generation/src/main.rs" download>完整 main.rs</a>导入；<a href="/learn-agent-rust/code/retrieval-augmented-generation/README.md" download>运行说明</a>随 zip 提供。

切块入库、向量检索、范围隔离、`RagTool` 和 `CitationRequired` 都是 adk-rag 与 adk-agent 的真实实现，向量库在内存里。embedding 是自写的词袋向量，不是神经模型；生成器是“摘录第一条证据”的确定性夹具；Agent 场景的模型是脚本。本文给出替换这些边界的路径，未运行的部分明确列出。
:::

## 1. 先找证据，再组织答案

RAG 的全称是 Retrieval-Augmented Generation。原始论文将生成模型与可检索的外部知识结合；本文从工程上拆成“查到哪些证据”和“如何据此回答”两段。论文使用经过训练的密集检索器，本实验先用可检查的词袋向量理解数据流。见 [Lewis 等，2020](https://arxiv.org/abs/2005.11401)。

假设发布说明有一句：“Upgrade v2 requires Rust 1.99.1.” 要回答版本要求，至少需要三种可观察结果：

| 结果 | 要核对的对象 | 出错时的例子 |
| --- | --- | --- |
| 证据候选 | 当前可访问的正确段落 | 取到了另一个项目的私有发布说明。 |
| 生成输入 | 实际交给回答环节的片段与来源 | 检索命中后因预算被丢弃，模型没有看到它。 |
| 输出依据 | 引用及其支持的结论 | 引用存在，但答案把 1.99.1 写成了 1.90。 |

仅仅把资料放进向量库还没有完成这三步。我们沿一条问题链路逐一验证。

![资料由 RagPipeline 切块、编码并按范围入库；查询在宿主给定的范围内检索；宿主核对来源时效与预算后交给生成环节，最后分别由宿主和 CitationRequired 校验引用。](/learn-agent-rust/figures/k01-rag-pipeline.svg)

从上往下读：上层是 adk-rag 管线做的事，中层是宿主的证据检查，下层是回答与校验。

## 2. 文档怎样变成可检索的 chunk

整份文件可能包含版本要求、回滚和发布检查。直接把它当作一个检索单元，短问题可能带入大量无关内容。adk-rag 用 `Chunker` trait 决定怎样切块，自带按字节长度、递归分隔符和 Markdown 结构的三种切块器。我们需要每块记住原文件的起止行，引用才能指回原文，所以自己实现一个按段落切的：

<<< @/public/learn-agent-rust/code/retrieval-augmented-generation/src/main.rs#chunking

`Chunk::from_document` 让每块继承文档的 ID、元数据和来源；我们再给每块加上带行号的块 ID（`A/release.md:L3-L3`）和来源 URI（`kb://A/release.md#L3-L3`），后者在 Agent 场景里就是模型要引用的链接。`release.md` 的第 3 行形成版本要求块，第 5 行形成回滚块。

切块器只负责切，不负责编码和存储。入库写成 `pipeline.scoped(范围).ingest(集合, 文档)`，依次做三件事：调用切块器，把所有块交给 embedder 编码，再写进这个范围。同一份文档再入库一次时，框架先写入新块（块 ID 相同的直接覆盖），再删除新版本已经没有的块；测试 `reingesting_replaces_a_documents_chunks` 把发布说明改成只剩一段，验证旧的回滚块确实被删掉。

切得太小，条件与结论可能分离；切得太大，相关度和上下文预算容易被无关内容稀释。真实手册可以按标题层级、token 长度或代码结构切分，并保留适当重叠，选择时应观察带标签查询上的召回及最终证据长度。

## 3. 用词袋向量建立能解释的基线

向量检索把查询和每个块都编码成同一空间里的向量，按相似度取最接近的几个。adk-rag 的 `EmbeddingProvider` trait 只要求两件事：把一段文字编码成向量，以及报告向量的维数。只要实现这两个方法，任何编码方式都能接进管线：

<<< @/public/learn-agent-rust/code/retrieval-augmented-generation/src/main.rs#embedding

`HashedWords` 是最朴素的编码：把每个英文单词哈希到 2003 维中的一维，出现几次就记几。内存向量库按余弦相似度排序：

$$
\cos(q,d)=\frac{q\cdot d}{\lVert q\rVert\,\lVert d\rVert}
$$

两段文字共享的词越多、比例越接近，余弦越高；一个共同词都没有就是 0。它和第一版用的 BM25 都是词法方法，区别是 BM25 还按“这个词在全部资料里有多少见”加权，余弦词袋不加权。它能逐行读懂，也同样找不到同义表达，这正是后面要观察的缺口。

几个实测到的细节：

- **维数太小会碰撞。** 不同的词落进同一维，就被当成同一个词。`collision` 场景把维数改成 4，资料里根本没有的 `unicorn` 也得到 0.658 分。本章取质数 2003，并用测试保证这份语料里没有任何两个词碰撞。
- **零分也会被返回。** adk-rag 默认的相似度下限是 0.0，而管线保留 `score >= 下限` 的结果。`zero-score` 场景用默认值查 `unicorn`，两个毫不相关的块以 0.000 分返回（谁排第一只由块 ID 的字母顺序决定），生成夹具随即摘录了数据库备份那句话，引用校验也通过了：引用确实存在，只是和问题毫无关系。本章把下限设为 0.05。
- **分数不受其他文档影响。** 余弦只看查询和这一块，测试 `a_chunks_score_does_not_depend_on_other_documents` 删掉其他三份资料后得分不变；BM25 的 IDF 要统计整个可见语料，所以第一版必须先按范围过滤再统计，否则别的范围的文档会改变本范围的得分。

<<< @/public/learn-agent-rust/code/retrieval-augmented-generation/src/main.rs#retrieval

范围（`Scope`）是 adk-rag 原生的概念：`pipeline.scoped(范围)` 之后的入库、检索、删除都只作用于这个范围。本章用的内存向量库按范围分开存放，检索只在本范围的块里打分和截取 top-k；换成 Qdrant、pgvector 等后端时，范围同样由框架传给后端，打分方式由后端决定。本例的范围 A/B 是宿主给定的模拟输入；真实服务必须从认证会话解析范围，不能接受模型自行声明身份。

## 4. 相关候选怎样成为本轮证据

<<< @/public/learn-agent-rust/code/retrieval-augmented-generation/src/main.rs#index

相关度排序之后，还有两个问题：资料是否仍是当前版本？本轮能放下多少内容？向量库里存的是入库时的文字，它不知道原文件后来改了没有。所以宿主在入库时另存一份来源清单（文件路径与完整原文），使用证据前逐条重新读取原文件比较：

<<< @/public/learn-agent-rust/code/retrieval-augmented-generation/src/main.rs#context

文件变了就返回 `stale_index`，被删除就返回 `source_missing`。通过以后才按排名装入预算；一个片段放不下就跳过，继续尝试后面的片段。这里的预算统计序列化证据块的 Unicode 字符数，不是模型 tokenizer 的 token 数；接入模型以后，应给系统策略、历史、工具 schema 和预期输出留出预算。历史裁剪与摘要见[下一章](./context-compaction.md)。

`generate_fixture` 是替换边界：它从最终上下文摘录第一条证据，不会猜答案。`validate_claim` 独立核对引用属于本轮集合、摘录非空且确实出现在对应原文。没有片段可用时，返回 `abstain=no_evidence`。这套检查只适用于逐字摘录：真实模型通常会改写或综合多个来源，引用有效只能证明来源存在，不能证明结论被支持。

## 5. 动手：观察正常、无证据与资料过期 {#hands-on}

下载并解压独立工程，先取一次 ADK-Rust 源码再运行：

```sh
cd retrieval-augmented-generation
python3 fetch-adk-rust.py ../adk-rust    # 需要 git 与 GitHub 访问；不行时加 --method cdn
cargo test --locked
cargo run --locked -- query corpus A 'upgrade Rust'
cargo run --locked -- suite /tmp/my-rag-lab
```

编译时会看到 adk-core 的 3 条弃用警告（上游固定 Rust 1.95.0），不影响运行和检查。`suite` 要求目标目录尚不存在，并保留它供检查：它创建教学资料，建好索引，在同一进程中修改再删除发布说明，真实制造索引过期。`query` 只读工程自带的 `corpus`。

正常查询的实际输出：

<<< @/public/learn-agent-rust/outputs/k01-query.txt

引用中的 `A` 是范围，`release.md` 是文件，`L3-L3` 是来源行，`@` 后面是来源全文的显示指纹（FNV，只用于区分新旧版本，过期判断比较的是完整原文）。下面是整套实验的实际轨迹：

<<< @/public/learn-agent-rust/outputs/k01-suite.txt

| 场景 | 实际观察 | 解释 |
| --- | --- | --- |
| normal | 摘录 Rust 1.99.1 要求并带引用 | 证据选取与输出契约通过。 |
| no-hit / budget | 返回无证据 | 分别是没有超过相似度下限的块、候选装不下。 |
| zero-score | 下限为 0.0 时返回两个 0 分块，夹具摘录了无关的备份说明 | 框架默认值会把无关内容当成证据，引用校验拦不住。 |
| scope | A 看不到 B 的私有内容，B 只看到自己的文档 | 框架按范围存放与检索。 |
| injection | 恶意文字只作为数据摘录，动作数为零 | 固定夹具没有动作接口；真实模型的注入抵抗尚未验证。 |
| bad-citation | 拒绝伪造来源和不在原文的摘录 | 校验与生成分离。 |
| evaluation / lexical-gap | Recall@2 为 3/4，`revert disaster` 无证据 | 词袋向量不懂同义词。 |
| swap-embedder | 只换 embedder 后 4/4，找到 Rollback | 见第 6 节，同义词表是手写替身。 |
| collision | 4 维时 `unicorn` 也有 0.658 分 | 玩具 embedder 的维数会决定能否区分词。 |
| stale / updated | 旧索引拒绝；重新入库后读到替换文本 | 资料更新必须进入索引生命周期。 |
| deleted | 旧候选拒绝；删除文档的 2 个块后没有结果 | 删除也会影响证据有效性。 |
| agent-cited / agent-uncited | 带链接的回答通过；不带链接的被拦下 | 见第 8 节。 |

更新场景的 `Rust 2.00.0` 是合成替换文本，只用来观察数据更新，不表示真实版本或升级建议。

验证脚本把工程打包后在临时目录解压，在旁边放好 ADK-Rust 源码，运行格式、Clippy、9 项 Rust 测试和离线构建；`suite` 在两个新目录各跑一次必须逐字节相同，并核对目录里的文件确实被修改、删除，其他资料保持原样，已存在的目录被拒绝且一个字节都不动。<a href="/learn-agent-rust/outputs/k01-suite.txt" download>下载轨迹</a>；仓库维护命令为 `python3 scripts/verify-agent-rag.py --check`。

## 6. 分开评估检索与回答

我们公开四道小型教学查询及其相关块：版本要求、数据库备份、回滚，以及词面不重合的 `revert disaster`。最后一题的目标块含 `Rollback`，词袋向量找不到它。完整标签和评估逻辑也在唯一源码中：

<<< @/public/learn-agent-rust/code/retrieval-augmented-generation/src/main.rs#evaluation

每题只有一个标注相关块。Recall@2 表示它进入前两名的查询比例；MRR@2 对前两名中的首个相关位置取倒数，再对所有查询平均，未命中记零。

公平比较两种检索，要固定语料、切块、范围、相似度下限、查询和标签，只换一个部件。`swap-embedder` 场景就是这样做的：管线其余部分不动，只把 embedder 换成 `SynonymWords`，它在编码前把 `revert` 改写成 `rollback`。结果从 3/4 变成 4/4。

![词袋 embedding 的 Recall@2 为 0.75，只换成手写同义词表后为 1.00；同义词表是演示替换边界的替身。](/learn-agent-rust/figures/k01-retrieval-results.svg)

请注意这个结果说明了什么、没说明什么。它说明 embedder 是一个可以单独替换和单独评估的部件；它**没有**说明同义词表是好办法：表是看着这道题手写的，换一个说法（`undo the release`）就又找不到了。真正的语义检索要用经过训练的编码器，adk-rag 的 `onnx` 特性可以在本地运行 sentence-transformer 模型（首次需要下载模型和运行时），也可以接在线 embedding 服务；本实验都没有运行。

语料和标签都公开、规模很小，没有独立隐藏测试；这些数值用于检查教学链路，不能据此判断生产检索或真实模型质量。真实系统可以按下面的层次单独记录结果：

| 层次 | 可用指标或检查 | 需要的独立信息 |
| --- | --- | --- |
| 检索 | Recall@k、MRR@k、范围泄漏、来源时效 | 预先标注的相关证据集合。 |
| 上下文 | 相关证据是否实际装入、长度与冗余 | 最终请求中的证据记录。 |
| 回答 | 引用有效率、结论支持度、任务正确率、适当拒答 | 人工或独立评估标签。 |
| 运行 | 延迟、费用、更新延迟和失败恢复 | 真实请求与索引维护记录。 |

## 7. 语义向量、混合检索与重排

| 方法 | 工作方式 | 在 adk-rag 里的位置 | 需要补做的证据 |
| --- | --- | --- | --- |
| 词法检索 | 按词面及统计相关度排序 | 本章的词袋 embedder；BM25 见旧版 | 中文分词、缩写、代码符号与业务词表上的失败。 |
| 密集向量检索 | 用 embedding 模型把查询、片段编码到同一空间，按相似度找邻居 | 换 `EmbeddingProvider`；向量库可换 Qdrant、LanceDB、pgvector | 模型与 revision、查询/文档前缀、归一化、领域和语言上的召回。 |
| 混合检索 | 合并词法与向量候选，可用 RRF 按名次融合 | 通用管线没有现成实现，需要应用自己合并两路结果；只有 Google 的 Agent Retrieval 后端另有一个 `hybrid_search` 方法，不经过 `RagPipeline` | 同一查询集上的增益、额外延迟与丢失的精确匹配。 |
| 重排 | 对已召回的查询与片段对进一步评分 | `Reranker` trait：只看向量库已经截取的 top-k，相似度下限再作用于重排后的分数 | 在候选固定时是否改善排序，以及时间预算。 |

以归一化向量为例，余弦相似度衡量两个向量的方向接近程度。向量来自经过训练的编码器，质量取决于模型与任务；手写几组数字可以解释几何，却不能证明语义召回。短问题匹配长文档属于非对称检索，要核对模型要求的查询与文档编码方式，见 [Sentence Transformers 的语义检索说明](https://sbert.net/examples/sentence_transformer/applications/semantic-search/README.html)。RRF 的常见形式是将每个候选在不同列表中的 $1/(c+\mathrm{rank})$ 相加；重排则在较小候选集上使用更精细的相关度模型，参见 [Retrieve & Re-Rank](https://sbert.net/examples/sentence_transformer/applications/retrieve_rerank/README.html)。本实验没有实现或测量这些扩展。

索引参数变了、embedding 模型变了或切块策略变了，都应产生新索引版本；不能把旧文档向量和新查询编码器混用后继续沿用原指标。

### 与旧版场景的对应

| 旧版（标准库） | 新版（adk-rag） | 变化 |
| --- | --- | --- |
| 手写段落切块，块存在 `Vec<Chunk>` | 自写 `Chunker` 交给 `RagPipeline`，块存进 `InMemoryVectorStore` | 切块规则不变，存储与编码交给框架。 |
| BM25 排序，零分排除 | 词袋向量 + 余弦，相似度下限 0.05 | 新增 `zero-score`：框架默认下限会返回零分。 |
| 先按 scope 过滤再统计 | `pipeline.scoped(Scope)` | 范围隔离由框架提供；`scope` 场景同时核对 B 只看到自己。 |
| normal、no-hit、budget、injection、bad-citation | 同名场景 | 宿主检查不变。 |
| evaluation、lexical-gap（3/4） | 同名场景（3/4） | 新增 `swap-embedder`、`collision`。 |
| stale、updated（整份重建）、deleted | 同名场景 | 更新改为对这份文档重新入库，删除改为 `delete_document`。 |
| “在 Agent 里放在哪里”只有设计 | `agent-cited`、`agent-uncited` | `RagTool` 与 `CitationRequired` 真实运行。 |
| 8 项测试 | 9 项测试 | BM25 的排序与统计测试换成维数碰撞、阈值、得分独立、重新入库和引用检查测试。 |

## 8. 在 Agent 里放在哪里

前面的检索都由宿主在调用模型之前完成。另一种做法是把检索做成工具，让模型决定什么时候查、查什么。adk-rag 的 `RagTool` 就是这样一个工具：

<<< @/public/learn-agent-rust/code/retrieval-augmented-generation/src/main.rs#agent

几个设计值得注意：

- **范围由宿主决定。** 工具的参数里没有范围这一项，模型只能给查询词和条数。`with_scope` 指定搜哪个范围；不指定时搜 `Scope::single_tenant()`，本章的资料都在 A、B 两个范围里，那样什么也查不到，`CitationRequired` 也会因为“没有检索到来源”而拦下回答。
- **条数由模型给。** 宿主在管线上配的 `top_k(2)` 只是默认值，模型可以在参数里要更多条；需要上限时要在工具外面加检查。
- **检索结果记为本轮来源。** 每个带来源 URI 的结果都写进事件的 `grounding_sources`，轨迹里的 `source` 行就是它。
- **引用检查。** `output_guardrails` 里的 `CitationRequired` 要求最终回答至少引用一个本轮检索到的来源：回答里的 `[标题](来源)` 链接，或者模型服务自己标注的引用（URI 同样要是本轮来源）；本轮什么都没检索到时，默认也拦下。URI 必须逐字相同：`agent-cited` 链接了 `kb://A/release.md#L3-L3`，通过，事件上记下引用；`agent-uncited` 没有链接，运行以 `guardrail.output_blocked` 结束，回答不会交给用户。测试还验证了链接到 `kb://A/release.md`（少了行号）同样被拦下。

`CitationRequired` 检查的是“回答链接了本轮检索到的来源”，不是“回答被来源支持”：把 1.99.1 写成 1.90 再附上正确链接，它照样放行。逐字摘录或事实支持的检查仍要另做，第 4 节的 `validate_claim` 只适用于摘录夹具。另外，`RagTool` 直接把检索结果交给模型，中间没有第 4 节的来源时效和预算检查；需要这些检查时，可以自己写一个检索工具，在返回前调用宿主的检查，再用 `record_grounding_sources` 记录来源。

如果模型自主决定检索，还应限制查询次数、反复改写和超时。工具通过本地函数还是 MCP 暴露，是连接选择；检索质量和引用依据仍由相同契约验收。外部连接的真实实验见 [R19](./mcp-tools.md)。与其他输入的关系可以沿[概念导读](./knowledge-and-capabilities.md)复查：Skills 提供做事方法，RAG 提供这次问题的资料，Memory 提供历史事实，[R10](./system-prompts.md)负责把来源清楚地放入每轮请求。新检索工具与 R20 的组合尚未实现；不能将本章通过计入 R20 的既有集成证据。

## 框架替你做了什么、没做什么

| 框架做了 | 仍归应用 |
| --- | --- |
| `RagPipeline` 把切块、编码、入库串起来；同一文档再入库时替换旧块、删除多余的块。 | 选切块规则（本章自写，保留行号）；决定什么时候重新入库。 |
| 按范围存放和检索，检索只在本范围打分。 | 从认证会话得到范围，不让模型或用户自报身份。 |
| 余弦排序、top-k、相似度下限（内存向量库同分按块 ID 稳定排序）。 | 选 embedder 与维数；把下限设成大于 0（默认 0.0 会返回零分结果）。 |
| `RagTool` 只搜固定的范围和集合，结果记为本轮来源。 | 检查来源是否过期、证据能否装进预算、模型要的条数是否过多（`RagTool` 都不做）。 |
| `CitationRequired` 要求最终回答链接到本轮检索到的来源。 | 检查结论是否真的被来源支持；评估检索与回答质量。 |

<!-- adk-refs:start -->

## 在 ADK-Rust 源码里

本章的切块入库、向量检索、范围隔离与引用检查，在 ADK-Rust 里分布在这几处：

| 本章内容 | 源码位置 | 对照要点 |
| --- | --- | --- |
| 切块器接口 | [`adk-rag/src/chunking.rs` · `Chunker`](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-rag/src/chunking.rs#L76-L82) | 只负责把一份文档切成块；编码和存储由管线接着做 |
| embedding 接口 | [`adk-rag/src/embedding.rs` · `EmbeddingProvider`](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-rag/src/embedding.rs#L24-L43) | 实现 `embed` 与 `dimensions` 即可接入；批量编码默认逐条调用 `embed` |
| 入库：切块 → 编码 → 写入 | [`adk-rag/src/pipeline.rs` · `ScopedRag::ingest`](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-rag/src/pipeline.rs#L241-L307) | 先写入新块，再删除这份文档新版本里已经没有的块；空文档等于删除 |
| 查询：编码 → 检索 → 重排 → 下限 | [`adk-rag/src/pipeline.rs` · `ScopedRag::query_with`](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-rag/src/pipeline.rs#L362-L415) | 相似度下限在 top-k 截取和重排之后才过滤，保留 `score >= 下限` 的结果 |
| 默认相似度下限 | [`adk-rag/src/config.rs` 第 22 行](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-rag/src/config.rs#L22) | 默认 0.0，零分结果也会返回（`zero-score` 场景） |
| 内存向量库的相似度 | [`adk-rag/src/inmemory.rs` · `cosine_similarity`](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-rag/src/inmemory.rs#L63-L71) | 余弦相似度；任何一方是零向量时记 0 |
| 内存向量库的检索 | [`adk-rag/src/inmemory.rs` 第 134 行](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-rag/src/inmemory.rs#L134) | 只取本范围的块打分，同分按块 ID 排序，所以每次运行顺序相同 |
| 检索工具记录来源 | [`adk-rag/src/tool.rs` 第 442 行](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-rag/src/tool.rs#L442) | 每个带来源 URI 的结果写进事件的 `grounding_sources`；范围由 `with_scope` 固定，模型不能指定 |
| 把回答里的链接绑定为引用 | [`adk-core/src/grounding.rs` · `bind_markdown_citations`](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-core/src/grounding.rs#L126-L158) | 只认 `[标题](URI)` 形式，URI 必须与本轮来源逐字相同 |
| 引用检查 | [`adk-guardrail/src/citation.rs` · `CitationRequired`](https://github.com/zavora-ai/adk-rust/blob/98515241133d24f7e41f8fd272649035416a142f/adk-guardrail/src/citation.rs#L64-L69) | 最终回答至少引用 1 个本轮检索到的来源，否则拦下；不检查结论是否被来源支持 |

源码固定在 ADK-Rust `98515241133d`（3.0.0，2026-11-26，尚未发布到 crates.io）。本节由 `scripts/learn-agent-rust-adk-refs.py` 生成。

<!-- adk-refs:end -->

::: warning 常见误区
- 检索得分高只说明相似度高，引用存在也只证明来源可定位。结论是否被支持仍需检查。
- 默认相似度下限是 0.0：不设下限，“什么都没找到”也会返回几条零分结果。
- 向量库里存的是入库时的文字，原文件改了它不知道；时效检查、重新入库都要由应用安排。
- 换 embedder、改维数或改切块方式都要重建索引，再用同一组查询和标签重新评估。
- 本章的词袋向量、英文分词、字符预算和内存向量库适合小型教学资料；生产方案需独立测量与设计。
:::

## 本章结论

先把证据生命周期做成可以检查的链路：切块保留来源，按范围检索，核对当前版本，在预算内组装，再独立检查回答依据。adk-rag 承担了切块入库、向量检索与范围隔离，`RagTool` 和 `CitationRequired` 把检索与引用检查接进 Agent；来源时效、预算和“结论是否被支持”仍是应用的事。后续替换 embedding、重排或生成模型时，继续沿同一组可观察边界验收。

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

   无权访问的片段会占用候选名额，`private` 这类词还可能让别的范围的块排到前面，删掉以后本范围的结果就不够了。adk-rag 的范围在检索之前生效：向量库按范围分开存放，只在本范围里打分和截取 top-k。用 BM25 时还有一层：IDF 统计整个可见语料，别的范围的文档会改变本范围的得分。

   </details>

2. 检索已经命中，为什么预算场景仍拒答？

   <details><summary>参考答案</summary>

   检索候选和最终上下文是两个集合。一个字符的预算装不下完整证据包装，生成器收到空集合，所以返回无证据。

   </details>

3. 文档更新后，向量库里的块还保留原文，为什么要拒绝？

   <details><summary>参考答案</summary>

   当前问题要求最新资料。向量库存的是入库时的文字，宿主比较完整来源快照，发现变化后要求重新入库。若业务要回答历史版本，应显式选择历史快照，并标明时间口径。

   </details>

4. `CitationRequired` 通过了，能证明回答是对的吗？

   <details><summary>参考答案</summary>

   不能。它只检查回答链接了本轮检索到的来源，URI 逐字相同。回答把版本号写错、或者引用了一个并不支持结论的来源，它都放行。结论是否被支持要另行检查，本章的摘录校验只适用于逐字摘录。

   </details>

5. 怎样公平比较词袋向量与新 embedding 模型？

   <details><summary>参考答案</summary>

   固定语料版本、切块、范围、查询集、相关标签、top-k、相似度下限和上下文预算，只换 embedder，并重建索引；在开发集选择参数，再用独立测试集比较召回、排序和运行代价，最后单独评估生成质量。本章的 `swap-embedder` 只做到了“只换一个部件”，它的同义词表是看着题目写的，不能代替独立测试集。

   </details>

## 参考资料

- [Lewis 等：Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks](https://arxiv.org/abs/2005.11401)，2020：RAG 原始论文，具体神经结构与本文基线范围不同。
- [Sentence Transformers：Semantic Search](https://sbert.net/examples/sentence_transformer/applications/semantic-search/README.html)：非对称检索与查询/文档编码。
- [Sentence Transformers：Retrieve & Re-Rank](https://sbert.net/examples/sentence_transformer/applications/retrieve_rerank/README.html)：候选召回与重排的职责。
- [adk-rag 固定源码](https://github.com/zavora-ai/adk-rust/tree/98515241133d24f7e41f8fd272649035416a142f/adk-rag/src)：本课程真实运行的接口与语义基线。

资料查阅：2026-11-27。接下来进入[第 12 章：上下文压缩](./context-compaction.md)，处理方法、证据和历史不断累积时的输入预算。
