---
title: "第 38 章：LLM 和 Agent 的交互"
description: "Agent 怎样把对话、工具说明、工具结果和记忆组装成提示词交给模型，又怎样从模型输出里解析出下一步动作：对话模板、工具调用、Agent 循环、上下文预算与外部记忆。"
pageClass: tinyllm-course
---

# 第 38 章：LLM 和 Agent 的交互

[课程总览](./index.md) · [上一章](./preference-alignment.md)

::: info 本章状态：规划中
正文与 notebook 尚未完成。计划覆盖：Agent 发出的消息怎样经过对话模板变成 token；模型怎样按约定格式发起工具调用，Agent 怎样解析、校验、执行并把结果送回；“调用模型 → 执行工具 → 再调用模型”的循环及其终止条件；上下文预算；在模型外保存与检索跨会话记忆。原“Agent 记忆与检索”一章已并入本章第 6 节。
:::

<TinyLLMMap active="llm-agent-interaction" />

到第 37 章为止，模型只做一件事：读入一串 token，输出下一个 token 的概率分布。Agent 是包在模型外面的一段普通程序：它决定这一次把什么放进上下文，读模型写出来的文字，再判断是直接回答用户、调用一个工具，还是带着新信息再问一次模型。模型本身不会“调用工具”，也不会“记住用户”；这些本事来自<strong>Agent 和模型之间约定的文本格式</strong>，以及 Agent 在两次调用之间做的事。[第 1 章](./first-run.md)用一个查日志的例子粗略走过这条循环，本章把其中每一环拆开。

## 本章主线选择（待实验验证）

Agent 与模型之间只通过<strong>文本消息</strong>交互：用与[第 34 章](./instruction-finetuning.md) SFT 相同的对话模板渲染 system、user、assistant、tool 四种角色；工具调用写成一行 JSON（工具名加参数），Agent 解析失败或参数不合法时，把错误作为 tool 消息送回模型，而不是静默重试；循环设步数上限。跨会话事实以<strong>带来源、时间和更新状态的文本记录</strong>保存在模型外，新问题到来时检索相关证据，放回当前上下文。

TinyLLM 很小，计划在一个合成任务上验证这条主线：例如必须借助计算器才能答对的算术题，用 SFT 教模型按格式发起调用，比较“直接回答”“工具调用”“工具调用加[第 26 章](./generation.md)的约束解码”三种做法的答案正确率和格式错误率。这组实验尚未实现。

## 1. 一次交互的完整链路 {#one-round-trip}

用户问：“北京现在几度？”模型的参数里不可能有“现在”的气温，Agent 要替它去查。一次完整的交互大致是：

1. Agent 组装消息列表：system 指令、可用工具的说明、之前的对话、这次的问题。
2. 对话模板把消息列表渲染成一串带特殊标记的文本，经[第 4 章](./tokenization.md)的 tokenizer 编码，模型做 prefill（[第 27 章](./inference-efficiency.md)）。
3. 模型没有直接回答，而是按约定格式写出一段工具调用，例如 `{"name": "get_weather", "arguments": {"city": "北京"}}`，接着写出结束标记。
4. Agent 认出这是一次调用，解析 JSON、检查参数，真的去查天气。
5. Agent 把查询结果作为一条 tool 消息追加到对话末尾，再调用一次模型。
6. 模型读到结果，写出给用户的回答。

模型在第 3 步和第 6 步做的是同一件事：接着上下文往下写 token。哪些事归模型、哪些归 Agent，可以这样分：

| 环节 | 由谁完成 | 出错时的样子 |
| --- | --- | --- |
| 把消息渲染成对话模板 | Agent（或推理框架） | 模板与训练时不一致，模型输出格式错乱或停不下来 |
| 决定调哪个工具、填什么参数 | 模型生成的文本 | 调用不存在的工具，参数类型不对 |
| 解析、校验、执行工具 | Agent | 解析失败，工具超时，越权操作 |
| 决定是否继续循环 | Agent | 无限循环，或过早停下 |
| 挑选放进上下文的历史与记忆 | Agent | 漏掉关键事实，或塞满无关内容 |

## 2. 对话模板：消息怎样变成 token {#chat-template}

Agent 手里是一组带角色的消息，模型只认一串 token。对话模板负责把前者变成后者：在每条消息前后插入标记角色边界的特殊 token（[第 4 章](./tokenization.md)），最后留一个“轮到助手说话”的开头，让模型从那里接着写。以 Qwen 等模型采用的 ChatML 风格为例（示意）：

<!-- output-check: skip -->
```text
<|im_start|>system
你是一个助手，可以调用 get_weather 工具。<|im_end|>
<|im_start|>user
北京现在几度？<|im_end|>
<|im_start|>assistant
```

模型在 SFT 阶段（[第 34 章](./instruction-finetuning.md)）见过的就是这种排布，它学会了在 `<|im_start|>assistant` 之后写回答、写完输出 `<|im_end|>`。推理时模板只要差一点，比如换了角色名、漏了换行或结束标记，模型就面对一种训练时没见过的输入。[Hugging Face 的对话模板文档](https://huggingface.co/docs/transformers/main/en/chat_templating)把模板存在 tokenizer 配置里，由 `apply_chat_template` 渲染，目的就是让训练和推理用同一份模板。

## 3. 工具调用：模型写出一段约定格式的文字 {#tool-calling}

工具的名字、用途和参数的 JSON Schema 也是文本，随模板一起放进上下文。模型在训练数据里见过“看到这类说明、遇到这类问题时，写出这样一段调用”，于是会在合适的时候写出调用。商用 API 把调用作为结构化字段返回，但在服务端，这段调用同样是模型逐 token 生成、再被解析出来的。[Toolformer](https://arxiv.org/abs/2302.04761) 用自监督数据教模型自己决定在哪里插入 API 调用，是这条思路的早期代表。

格式靠训练学到，也就可能写错：括号不配对、字段名拼错、参数类型不符。有两道防线：

- 生成时用[第 26 章](./generation.md)的约束解码，把“此刻不合格式的 token”的 logits 置为负无穷，保证写出来的 JSON 一定能解析；它保证格式，不保证内容对。
- 执行前由 Agent 校验：工具是否存在、参数是否符合 Schema、这次调用是否在允许范围内。校验失败时把错误原文作为 tool 消息送回，模型往往能在下一轮自己改正。

[MCP（Model Context Protocol）](https://modelcontextprotocol.io/)规定的是 Agent 一侧怎样发现、调用外部工具和数据源，让同一个工具服务可以接到不同的 Agent 上；对模型来说，工具仍然是上下文里的一段说明。

## 4. Agent 循环 {#agent-loop}

把第 1 节的六步写成循环，就是最常见的 Agent 骨架。[ReAct](https://arxiv.org/abs/2210.03629) 让模型交替写出“思考”和“动作”，把动作的结果作为观察写回上下文，再继续推理。下面是示意代码，本章的完整脚本尚未完成：

```python
# 示意：说明循环结构，不是可运行脚本
messages = [system_msg, user_msg]
for step in range(max_steps):
    reply = model.generate(render(messages, tools))
    call = parse_tool_call(reply)
    if call is None:
        return reply                    # 没有调用：这就是最终回答
    result = run_tool(call)             # 校验参数、执行、捕获错误
    messages += [assistant(reply), tool(result)]
return "达到步数上限，停止"
```

每转一圈，整段对话都要重新交给模型。若不复用缓存，第 k 圈要对前面所有 token 重新 prefill，总计算量随圈数近似平方增长；[第 32 章](./kv-memory.md)的前缀缓存能让不变的前缀直接复用 KV cache。步数上限和“工具连续失败几次就停”这类规则，都写在 Agent 里，模型并不知道自己转了几圈。

当任务需要分支、并行、等人审批、或中途崩溃后从断点继续时，固定的 `for` 循环就不够了，控制流会变成一张带状态的图，这正是 [LangGraph](https://github.com/langchain-ai/langgraph) 这类编排框架做的事。它们改变的是 Agent 一侧的控制流；模型这一侧的接口仍然是“读一段上下文，写一段文字”。

## 5. 上下文预算 {#context-budget}

上下文里同时挤着 system 指令、工具说明、对话历史、工具返回的结果和检索到的记忆。每多一个 token，prefill 就多一份计算，KV cache 就多一份显存（[第 27 章](./inference-efficiency.md)）；上下文还有长度上限。Agent 常用的办法是截掉早期轮次、把旧对话压成摘要、只保留工具结果里有用的部分。被挤出上下文、以后又可能用到的信息，就要存到模型外面，这就是下一节的外部记忆。

## 6. 外部记忆与检索 {#external-memory}

模型刚回答完一个问题，用户隔天再问“我上次决定用什么方案”，模型参数没有因为那次对话自动更新，昨天的 KV cache 通常也已经释放。若 Agent 想找回这个决定，就需要在模型外保存信息，在新一轮对话中把相关证据重新交给模型。这就是本章所说的<strong>外部记忆</strong>。

模型内部的 token embedding 与检索文本用的 embedding 的区别见 [第 5 章](embeddings-and-output.md)；KV cache 的计算与内存开销见 [第 27 章](inference-efficiency.md)。

### 四种常被叫作“记忆”的东西 {#four-kinds-of-memory}

问“模型记得什么”之前，先问<strong>信息保存在哪里、何时失效、能否跨会话复用</strong>：

| 保存位置 | 保存什么 | 生命周期 | 在推理中做什么 |
| --- | --- | --- | --- |
| 模型参数（含词嵌入） | 训练形成的权重 | 持续到换权重或训练更新 | 决定模型如何处理输入；通常不保存某次对话的原文 |
| 当前上下文 | 本次送入模型的 token | 随请求或上下文管理改变 | 提供当前可见的指令、问题与证据 |
| KV cache | 当前前缀在各注意力层算出的 K/V 张量 | 通常随生成请求结束；服务系统可在条件满足时复用前缀 | 避免每生成一个 token 就重算相同前缀的 K/V，占用推理内存 |
| Agent 外部记忆 | 历史文本、提取的事实及来源等 | 可跨请求保存，直到更新或删除 | 检索相关内容，并把可读文本放回当前上下文 |

一轮对话可能经过 <strong>外部记忆检索 → 组装上下文 → tokenizer → 模型前向计算与 KV cache → 逐 token 生成</strong>。KV cache 存的是计算结果，不会自动判断哪些事实值得长期保留；外部记忆即使保存在向量库里，也要先检索并进入上下文，模型才能在这一轮使用。KV cache 的开销见[第 27 章](inference-efficiency.md)。

### 一条记忆怎样影响下一次回答

假设用户说：“项目的图表以后统一用 Plotly。”Agent 可以保留原句、时间、来源和所属项目，也可以抽取“该项目图表库 = Plotly”这一事实。下次用户问“画图用什么库”，系统先找回这条信息，再把证据文本放进当前提示词。模型读取的是<strong>新上下文里的文本</strong>；向量索引中的数值向量只是帮助找到它，不会直接变成模型的参数或 KV cache。

这条链路可写为：<strong>对话 → 选择/写入记忆 → 建立检索索引 → 新问题 → 检索并核对有效性 → 将证据放入上下文 → 模型生成</strong>。若用户后来改成“这个项目改用另一套图库”，系统要处理新旧事实的关系；只按相似度找出两条句子并不能自动判断哪条生效。[LongMemEval](https://arxiv.org/abs/2410.10813) 因此把信息提取、跨会话推理、时间推理、知识更新和证据不足时拒答分别评测。

### 从最小实现开始

第一版可以保存原始文本及来源、时间和所属用户/项目，用文本块与关键词检索作为基线。随后再加入文本 embedding 的语义检索，比较是否真的多找回了相关证据；若需要跟踪实体、事件和事实变更，再尝试结构化事实或时间图谱。写入前应区分短暂闲聊与可复用信息，读取时要控制可见范围，保留更正和删除入口。把全部历史都塞进上下文可以作为小样本对照，但长历史会增加 prefill、上下文占用及成本。[MemGPT](https://arxiv.org/abs/2310.08560) 将不同层级的记忆管理作为 Agent 系统问题；[MemEval](https://github.com/ProsusAI/MemEval) 提供在相同条件下比较多种记忆系统的开源评测框架。

实验将准备几段跨会话对话，包含事实更新、日期变化、无答案问题以及相似但属于不同项目的事实。分别比较“无记忆”“全历史上下文”“关键词检索”“向量检索”，记录证据是否找对、答案是否正确、是否能承认不知道、输入 token 数和延迟。先找出最简单方案的失败案例，再决定是否引入 [Mem0](https://github.com/mem0ai/mem0)、[Letta](https://github.com/letta-ai/letta) 或 [Graphiti](https://github.com/getzep/graphiti) 等框架。本项目目前尚未实现或运行这组 Agent 记忆实验。

### 两种 embedding：模型内部的词嵌入与检索向量 {#two-kinds-of-embedding}

[第 5 章](./embeddings-and-output.md)学的 $E_i$ 是语言模型内部、按 token ID 读取的参数表。Agent 的记忆检索常把<strong>一段完整文本</strong>编码成一个向量，用相似度查找历史内容；检索出的文本进入当前提示词，再经过 tokenizer 和模型内部嵌入层。它一般属于独立的检索系统，不会因为语言模型在本章调用 `backward()` 而自动更新。

| 问题 | 模型内部嵌入 | Agent 记忆检索向量 |
| --- | --- | --- |
| 输入与输出 | 单个 token ID → 一个可训练向量 | 一段文本 → 一个用于比较的向量 |
| 更新 | 随语言模型损失训练 | 通常由独立编码器生成，历史记录需按版本管理 |
| 用途 | 参与模型前向计算 | 帮助找回证据，再把证据放回上下文 |

向量相近不等于记忆仍有效。“去年住上海”和“现在住北京”都可能被找到；还要保存来源、时间和更新关系，并评价最终回答能否使用正确证据。

#### 为什么通常使用单独的文本编码模型

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

实验时要固定模型版本、查询/材料前缀、池化方式和归一化规则。还要在中文、多项目同名事实、事实更新与无答案问题上测检索命中和最终回答；单次余弦分数不能证明记忆系统可靠。上面“从最小实现开始”给出了完整评测路线。
