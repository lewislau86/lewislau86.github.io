# Chapter 5：词嵌入与输出层

本章教案与实验尚在规划中。主线将覆盖 token ID 到向量、logits、输出投影、Weight Tying（输入输出权重共享）。在学习模型内部的词嵌入前，先分清另一个常被叫作 embedding 的模块。

## 两种 embedding，处在不同的位置

如果以后给 TinyLLM 加一个能检索历史对话或资料的 Agent，系统里可能同时出现两种向量：

| | 模型内部的词嵌入 | Agent 记忆检索用的 embedding |
| --- | --- | --- |
| 输入 | 一个个 token ID | 一段文本，例如一条记忆或一个文档片段 |
| 输出 | 每个 token 一个向量，形状通常为 `[batch, seq, hidden]` | 每段文本一个用于检索的向量 |
| 常见实现 | `nn.Embedding` 按 ID 查可训练的参数表 | 独立的文本向量模型编码，再在向量索引中查相近内容 |
| 主要用途 | 为语言模型后续的 Transformer 计算提供输入 | 找到与当前问题相关的旧信息，再把检索出的<strong>文本</strong>放进模型上下文 |
| 更新方式 | 随语言模型的训练损失更新 | 通常使用预训练编码器；更换编码器时需要重新编码已有记忆 |

两者的共同点是<strong>把离散内容表示成数值向量</strong>，但不能把两套向量直接当成同一种东西。模型内部的词嵌入是一张按 token ID 查找的表；同一个 ID 查到同一行初始向量，后续 Transformer 层才结合上下文处理它。记忆 embedding 则要概括整段文本的含义，方便把问题向量与记忆向量比较相似度。它通常不在生成模型的前向计算图中，也不会因为调用生成模型的 `backward()` 就更新。

一条记忆的路径可以读作：<strong>历史文本 → 编码成检索向量并保存 → 新问题编码成查询向量 → 找到相关历史文本 → 将文本加入提示词 → 重新分词 → 模型内部词嵌入 → 生成回答</strong>。检索出的向量本身一般不直接塞进生成模型的 token embedding 层。这里描述的是一种常见的检索式记忆设计，并不表示本项目已经实现 Agent 记忆模块。

后续补充本章实验时，将先动手观察 `nn.Embedding` 的查表、形状和梯度，再用一个独立的小例子展示文本向量检索的输入输出边界。`nn.Embedding` 的接口可查 [PyTorch 文档](https://docs.pytorch.org/docs/stable/generated/torch.nn.Embedding.html)；文本向量用于语义检索的流程可查 [LangChain Embedding 模型文档](https://docs.langchain.com/oss/python/integrations/embeddings)。

## 设计记忆时，先决定什么值得记

模型内部的词表与嵌入矩阵必须一一对应：改变 token ID 的含义，就要同步处理模型的输入嵌入与输出层。Agent 记忆则是可增删的外部数据。它的难点不只在选一个编码器，更在于决定<strong>写入什么、何时更新、怎样找回、何时不用记忆</strong>。

最简单的练习是把每轮对话都切成文本块并编码；但“去年住上海”和“现在住北京”可能都被找出，仅凭向量相似度无法判断哪个事实仍有效。更稳妥的起点是保留原文、来源、时间、用户或会话边界，抽取可核对的事实；查询时把语义相似度与关键词、时间及实体过滤结合，最后让模型依据找回的文本回答。遇到证据不足，应允许回答“不知道”，也要支持用户更正和删除。这里的结构化字段是设计建议，不是 embedding 模型自动提供的能力。[LongMemEval](https://arxiv.org/abs/2410.10813) 把跨会话、时间、知识更新和拒答都列为独立的记忆能力。

开源实现提供了不同路线：[Mem0](https://github.com/mem0ai/mem0) 偏向抽取事实并检索，[Letta](https://github.com/letta-ai/letta) 让有状态 Agent 管理可编辑记忆，[Graphiti](https://github.com/getzep/graphiti) 用带时间信息的知识图谱表示实体和关系，[LangMem](https://github.com/langchain-ai/langmem) 提供与 LangGraph 存储结合的记忆工具。它们都不等于“换一个更好的 embedding 模型”；写入策略和读取策略同样影响答案。

怎么比较？先做“全历史放入上下文”“简单文本块检索”两个基线，再在同一生成模型、编码器、数据集和提示词下比较系统。至少分别记录检索命中、最终回答正确率、时间/事实更新、拒答、写入与查询的 token 成本和延迟。[LoCoMo](https://aclanthology.org/2024.acl-long.747/) 测长对话，[LongMemEval](https://arxiv.org/abs/2410.10813) 测长期交互记忆；开源的 [MemEval 评测框架](https://github.com/ProsusAI/MemEval) 把多个系统放进统一设置，并显示不同方案的质量与成本差别。其公开分数依赖特定模型、样本和评分器，不能直接当成 TinyLLM 上的排名。本项目尚未运行这些评测。

目前研究还在从“记住并找回一句话”走向更难的能力：[LoCoMo-Plus](https://aclanthology.org/2026.acl-long.1150/) 检查隐含约束能否在后续对话中被正确应用；[LongMemEval-V2](https://arxiv.org/abs/2605.12493) 把环境状态、工作流程和过去踩过的坑纳入评测。后续若实现 Agent 记忆，应先用一个小型、可复现的测试集验证写入、更新、删除和检索，再决定是否引入复杂框架。

返回 [课程总目录](index.md#课程路线规划)。
