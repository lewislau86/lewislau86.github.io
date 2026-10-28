---
title: "第 29 章：Agent 记忆与检索"
description: "Agent 怎样在模型之外保存、检索并送回跨会话的事实；与参数、上下文和 KV cache 的边界。"
pageClass: tinyllm-course
---

# 第 29 章：Agent 记忆与检索

[课程总览](./index.md) · [上一章](./preference-alignment.md)

::: info 本章状态：规划中
正文与实验尚未完成。下面先把系统边界说清楚，再逐步实现可复现的小例子。
:::

<TinyLLMMap active="agent-memory" />

模型刚回答完一个问题，用户隔天再问“我上次决定用什么方案”，模型参数没有因为那次对话自动更新，昨天的 KV cache 通常也已经释放。若 Agent 想找回这个决定，就需要在模型外保存信息，在新一轮对话中把相关证据重新交给模型。这就是本章所说的<strong>外部记忆</strong>。

模型内部的 token embedding 与检索文本用的 embedding 的区别见 [第 4 章](embeddings-and-output.md)；KV cache 的计算与内存开销见 [第 24 章](inference-efficiency.md)。

## 四种常被叫作“记忆”的东西 {#four-kinds-of-memory}

问“模型记得什么”之前，先问<strong>信息保存在哪里、何时失效、能否跨会话复用</strong>：

| 保存位置 | 保存什么 | 生命周期 | 在推理中做什么 |
| --- | --- | --- | --- |
| 模型参数（含词嵌入） | 训练形成的权重 | 持续到换权重或训练更新 | 决定模型如何处理输入；通常不保存某次对话的原文 |
| 当前上下文 | 本次送入模型的 token | 随请求或上下文管理改变 | 提供当前可见的指令、问题与证据 |
| KV cache | 当前前缀在各注意力层算出的 K/V 张量 | 通常随生成请求结束；服务系统可在条件满足时复用前缀 | 避免每生成一个 token 就重算相同前缀的 K/V，占用推理内存 |
| Agent 外部记忆 | 历史文本、提取的事实及来源等 | 可跨请求保存，直到更新或删除 | 检索相关内容，并把可读文本放回当前上下文 |

一轮对话可能经过 <strong>外部记忆检索 → 组装上下文 → tokenizer → 模型前向计算与 KV cache → 逐 token 生成</strong>。KV cache 存的是计算结果，不会自动判断哪些事实值得长期保留；外部记忆即使保存在向量库里，也要先检索并进入上下文，模型才能在这一轮使用。KV cache 的开销见[第 24 章](inference-efficiency.md)。

## 本章主线选择（待实验验证）

跨会话事实先以<strong>带来源、时间和更新状态的文本记录</strong>保存在模型外，新问题到来时检索相关证据并放回当前上下文。小规模样例可先用关键词和元数据过滤；语料增大、同义表达增多时再比较向量检索与混合检索。这个选择让事实可检查、可更正；模型参数和 KV cache 都不会自动承担同一职责。

## 一条记忆怎样影响下一次回答

假设用户说：“项目的图表以后统一用 Plotly。”Agent 可以保留原句、时间、来源和所属项目，也可以抽取“该项目图表库 = Plotly”这一事实。下次用户问“画图用什么库”，系统先找回这条信息，再把证据文本放进当前提示词。模型读取的是<strong>新上下文里的文本</strong>；向量索引中的数值向量只是帮助找到它，不会直接变成模型的参数或 KV cache。

这条链路可写为：<strong>对话 → 选择/写入记忆 → 建立检索索引 → 新问题 → 检索并核对有效性 → 将证据放入上下文 → 模型生成</strong>。若用户后来改成“这个项目改用另一套图库”，系统要处理新旧事实的关系；只按相似度找出两条句子并不能自动判断哪条生效。[LongMemEval](https://arxiv.org/abs/2410.10813) 因此把信息提取、跨会话推理、时间推理、知识更新和证据不足时拒答分别评测。

## 从最小实现开始

第一版可以保存原始文本及来源、时间和所属用户/项目，用文本块与关键词检索作为基线。随后再加入文本 embedding 的语义检索，比较是否真的多找回了相关证据；若需要跟踪实体、事件和事实变更，再尝试结构化事实或时间图谱。写入前应区分短暂闲聊与可复用信息，读取时要控制可见范围，保留更正和删除入口。把全部历史都塞进上下文可以作为小样本对照，但长历史会增加 prefill、上下文占用及成本。[MemGPT](https://arxiv.org/abs/2310.08560) 将不同层级的记忆管理作为 Agent 系统问题；[MemEval](https://github.com/ProsusAI/MemEval) 提供在相同条件下比较多种记忆系统的开源评测框架。

实验将准备几段跨会话对话，包含事实更新、日期变化、无答案问题以及相似但属于不同项目的事实。分别比较“无记忆”“全历史上下文”“关键词检索”“向量检索”，记录证据是否找对、答案是否正确、是否能承认不知道、输入 token 数和延迟。先找出最简单方案的失败案例，再决定是否引入 [Mem0](https://github.com/mem0ai/mem0)、[Letta](https://github.com/letta-ai/letta) 或 [Graphiti](https://github.com/getzep/graphiti) 等框架。本项目目前尚未实现或运行这组 Agent 记忆实验。

## 两种 embedding：模型内部的词嵌入与检索向量 {#two-kinds-of-embedding}

[第 4 章](./embeddings-and-output.md)学的 $E_i$ 是语言模型内部、按 token ID 读取的参数表。Agent 的记忆检索常把<strong>一段完整文本</strong>编码成一个向量，用相似度查找历史内容；检索出的文本进入当前提示词，再经过 tokenizer 和模型内部嵌入层。它一般属于独立的检索系统，不会因为语言模型在本章调用 `backward()` 而自动更新。

| 问题 | 模型内部嵌入 | Agent 记忆检索向量 |
| --- | --- | --- |
| 输入与输出 | 单个 token ID → 一个可训练向量 | 一段文本 → 一个用于比较的向量 |
| 更新 | 随语言模型损失训练 | 通常由独立编码器生成，历史记录需按版本管理 |
| 用途 | 参与模型前向计算 | 帮助找回证据，再把证据放回上下文 |

向量相近不等于记忆仍有效。“去年住上海”和“现在住北京”都可能被找到；还要保存来源、时间和更新关系，并评价最终回答能否使用正确证据。

### 为什么通常使用单独的文本编码模型

若 Agent 有十万条历史，它需要<strong>提前</strong>把每条记忆编码、存入索引；新问题到来时，只编码问题，再从索引中找候选。常见的双塔检索模型把问题与文档分别编码为固定维度向量 $e_q$、$e_m$，用余弦相似度或内积排序：

$$
\operatorname{cos}(e_q,e_m)=\frac{e_q\cdot e_m}{\|e_q\|\,\|e_m\|}.
$$

同一个记忆向量要能与许多未来的问题比较。这要求模型学习<strong>跨文本、可复用的向量空间</strong>，通常还要把整段文本的多个 token 表示汇成一个向量，并用相关/不相关的文本对训练。检索模型内部也可能使用 Transformer 和 Q/K/V 注意力；不同之处主要是<strong>最终取出的表示和训练目标</strong>。生成模型的 Q/K/V 服务于每层、每头、当前上下文内的下一 token 计算；其形状、位置依赖、生命周期和训练目标都不同。仅把生成模型某层的 K 或词嵌入行拿出来求余弦，没有理由保证它能找回相关记忆。这是<strong>目标与接口不匹配</strong>，并非注意力点积本身不能表达相似性。

[Hugging Face 上的多语言 MiniLM](https://huggingface.co/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2)展示了一个具体实现：Transformer 先生成每个 token 的上下文化表示，再按 attention mask 做平均池化，得到一个 384 维句子向量。[multilingual-e5-small 的模型卡](https://huggingface.co/intfloat/multilingual-e5-small?library=sentence-transformers)把查询与材料分别加上 `query:`、`passage:` 前缀；[BGE-M3](https://huggingface.co/BAAI/bge-m3)同时支持稠密向量、稀疏检索和多向量检索。较新的 [Qwen3-Embedding-0.6B](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B) 则展示了另一种做法：在其示例中读取最后一个有效位置的隐藏状态，查询还可使用任务指令。<strong>文本级向量不一定都靠平均池化</strong>；要遵守对应模型卡的取向量与输入格式约定。这些是有不同训练与输出接口的检索模型例子，不是 TinyLLM 当前使用的依赖，也不能只按维度或模型大小选“最好”的一个。

真实系统也并非绝对不能复用生成模型：可以对它的隐藏状态做池化、指定提示格式，再用检索数据微调或蒸馏成文本 embedding 模型。但这已经增加了文本级表示和检索训练目标，而不是直接复用现成 Q/K/V 的一行缓存。选择独立模型的实际好处是记忆可离线建索引、问题可快速检索；代价是多一套模型、存储与版本管理。替换编码器或改变池化/前缀规则后，旧索引向量往往要重算。检索返回的仍是<strong>原始记忆文本</strong>，随后它作为新提示词进入语言模型并产生新的 token 嵌入、Q/K/V 和 KV cache。

可以在 Hugging Face 模型卡所列的环境里用下面的流程试验；首次运行会下载模型，本章 notebook 默认不执行这一段：

```python
# 示意代码：需要先 pip install sentence-transformers 并下载模型，本课程脚本默认不运行
from sentence_transformers import SentenceTransformer

retriever = SentenceTransformer("intfloat/multilingual-e5-small")
query_vec = retriever.encode(["query: 这个项目的图表库是什么？"], normalize_embeddings=True)
memory_vecs = retriever.encode(
    ["passage: 本项目统一使用 Plotly 画图。", "passage: 模型使用 PyTorch。"],
    normalize_embeddings=True,
)
scores = query_vec @ memory_vecs.T
print(scores)  # 两段材料各一个检索分数；仍须检查来源和事实是否有效
```

实验时要固定模型版本、查询/材料前缀、池化方式和归一化规则。还要在中文、多项目同名事实、事实更新与无答案问题上测检索命中和最终回答；单次余弦分数不能证明记忆系统可靠。本章开头的实验计划给出完整评测路线。
