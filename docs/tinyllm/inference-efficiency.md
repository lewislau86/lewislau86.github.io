---
title: "第 25 章：推理效率"
description: "Prefill 与 decode、KV cache、显存开销与批量生成。"
pageClass: tinyllm-course
---

# 第 25 章：推理效率

[课程总览](./index.md) · [上一章](./generation.md) · [下一章](./quantization.md)

::: info 本章状态：规划中
正文与 notebook 尚未完成（“KV cache 保存的是什么”一节已经成文，从第 5 章移来）。预计覆盖：Prefill/decode、KV cache、注意力时间与显存开销、FlashAttention、批量生成。先建立最重要的边界：这里的 cache 是<strong>推理过程中的计算状态</strong>，不是替 Agent 保存用户事实的长期记忆。
:::

<TinyLLMMap active="inference-efficiency" />

## 本章主线选择（待实验验证）

逐 token decode 默认复用 <strong>KV cache</strong>，分别测量 prefill 延迟、每步 decode 延迟和缓存字节数。它避免旧前缀反复投影成 K/V，但上下文和并发增加时会占用显存；若 KV 压力成为瓶颈，再结合 [第 6 章的 GQA](self-attention.md) 或分页缓存管理。缓存绝不替代跨会话事实存储。

## 为什么生成时要缓存 K 和 V

读入提示词时，模型进行 prefill：每层注意力都会为输入 token 计算查询 Q、键 K、值 V。随后进入 decode，每一步生成一个新 token。因果注意力下，旧 token 的 K/V 可以继续使用；如果每一步都从头计算整段前缀，会反复做相同工作。KV cache 保存旧 token 在各层的 K/V，新一步只算新 token 的 K/V，再用它们和已有缓存完成注意力。[vLLM 的前缀缓存说明](https://docs.vllm.ai/en/stable/design/prefix_caching/)展示了服务系统如何复用满足条件的前缀。

::: info 本章代码从哪里来
本章已成文部分的代码都在一个文件里：<a href="/tinyllm/code/inference-efficiency.py" download>inference-efficiency.py</a>（[在 GitHub 上查看](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/tinyllm/code/inference-efficiency.py)）。下面的代码块都是从这个文件里直接截取的片段；想自己运行，请下载完整文件，`python inference-efficiency.py` 从头跑到尾即可。notebook 版本也由同一个文件生成，可以[在线查看](/tinyllm/notebooks/inference-efficiency)。
:::

## KV cache 保存的是什么 {#kv-cache}

生成文本时，模型一次只多出一个 token。每一步都把整段序列重新算一遍显然浪费，KV cache 就是为此准备的：

![KV cache 的两个阶段：prefill 一次算出提示词所有位置的 K/V；之后每个解码步只为新 token 计算 K/V 并追加到缓存，新 token 的 Q 与缓存中全部 K 打分，再对全部 V 加权求和](/tinyllm/figures/kv-cache.svg)

先看左半部分：生成开始时处理整段提示词（prefill），得到每一层、每个注意力头对已有 token 的 K/V，存进缓存。再看右半部分的每个解码步：只为<strong>新位置</strong>计算 Q/K/V，把新 K/V 追加到缓存末尾；新 Q 与缓存中所有 K 做点积，经 softmax 得到权重，再对所有 V 加权求和。缓存复用的是旧位置的 K/V；注意力权重取决于新 Q，所以每一步都重新计算。

用[第 5 章](./embeddings-and-output.md)那个“我 在 学习”的小例子，先一次性算出三个位置的因果注意力输出 `context`：

<<< @/public/tinyllm/code/inference-efficiency.py#setup

再假装在生成：一个位置一个位置地来，每来一个新位置只算它自己的 Q、K、V，把 K、V 追加进缓存。逐步得到的结果应该和一次性计算的 `context` 一致：

<<< @/public/tinyllm/code/inference-efficiency.py#kv-cache

这个等式成立，是因为因果模型中每个位置只看过去：新 token 到来时，旧位置的 K/V 保持原样。实际缓存还要处理多层、多头、批量、位置编码、padding 和服务端的内存管理；训练时通常整段并行计算，用不到逐 token 缓存。缓存是<strong>本次推理内的计算复用</strong>，生命周期随请求结束；前缀复用也要求输入与模型状态满足匹配条件。[Hugging Face KV cache 文档](https://huggingface.co/docs/transformers/kv_cache)介绍了实际框架中的实现策略；缓存占多少显存见下一节。

省下了多少？把位置加到 12 个，数一数每一步实际投影了几行 K、V：

<<< @/public/tinyllm/code/inference-efficiency.py#count

```text
不缓存，每步重算的 K/V 行数: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12] 合计 78
KV cache，每步新算的 K/V 行数: [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1] 合计 12
```

不缓存时第 $t$ 步要重算 $t$ 行，生成 $n$ 个字一共 $n(n+1)/2$ 行，随长度平方增长；有缓存时每步只算 1 行，一共 $n$ 行。两种做法并排播放：

<KVCacheRace />

注意省下的只是 K、V 的投影。新 Q 仍然要和缓存里所有的 K 打分，这部分计算随上下文变长而增加；缓存本身也要占显存。

## KV cache 的代价与复用

缓存不是免费的。对普通全注意力 Decoder，可把占用近似写为 `2 × 层数 × 已缓存 token 数 × KV 头数 × 每头维度 × 每元素字节数`，再乘并发请求数；其中的 2 对应 K 和 V。这是张量数据量的粗略估计，不包含分配、分页或其他运行开销。上下文越长，并发越高，缓存压力越大。GQA/MQA 减少 KV 头数，KV 量化减少每个元素的字节数，分页管理改善缓存分配与复用；这些方法解决的是不同环节。[vLLM PagedAttention](https://arxiv.org/abs/2309.06180) 是缓存管理的代表工作。

还需区分两种“复用”：同一次生成中复用已计算的前缀 K/V，是 KV cache 的基本用途；跨请求复用相同前缀，需要服务系统识别兼容的 token、模型状态和位置等条件。前缀文字改了，旧缓存不能无条件继续用。前缀缓存即使跨请求存在，也不等于 Agent 能按语义检索用户过去说过的话；后者见 [第 31 章](agent-memory.md)。

后续实验将用同一模型、同一提示词和相同输出长度比较“每步重算前缀”与“缓存旧 K/V”，记录生成时间和缓存占用；再改变上下文长度和并发量，观察收益与内存的交换。基准应同时报告 prefill 与 decode，避免只看单个数字。

::: warning 常见误区
- **KV cache 只存 K 和 V。** 注意力权重取决于新 Q，每步重算；缓存也只在本次推理内有效，用户事实要靠其他记忆机制保存。
- **训练时用不到 KV cache。** 训练把整段序列一次并行算完，缓存只在逐个 token 生成时才有意义。
:::

<!-- real-model:start -->

## 在真实模型里

KV cache 在真实代码里由缓存类管理，注意力每一层把新的 K、V 交给它。下表的链接都指向 Hugging Face transformers 的固定版本 `v5.21`，精确到行。读代码时可以先跳过缓存、掩码、并行这些工程细节，只看和本章对应的那几行。

| 本章的零件 | 真实代码 | 对照要点 |
| --- | --- | --- |
| 创建缓存 | [`modeling_llama.py 第 373 行`](https://github.com/huggingface/transformers/blob/v5.21/src/transformers/models/llama/modeling_llama.py#L373) | `use_cache=True` 且没有传入缓存时新建一个 |
| 每层写入缓存 | [`modeling_llama.py 第 251 行`](https://github.com/huggingface/transformers/blob/v5.21/src/transformers/models/llama/modeling_llama.py#L251) | 拿到这一层新 token 的 K、V 后交给缓存，换回包含全部历史的 K、V |
| 追加到末尾 | [`DynamicLayer.update`](https://github.com/huggingface/transformers/blob/v5.21/src/transformers/cache_utils.py#L118-L137) | `torch.cat([self.keys, key_states], dim=-2)`：沿序列维拼接，和本章逐步缓存的写法一样 |

想在本机看源码，可以先 `pip install transformers`，再用 `python -m inspect transformers.models.llama.modeling_llama:LlamaMLP` 这样的命令打印出任意一个类。

<!-- real-model:end -->

## 检查理解

1. KV cache 里有没有上一步的注意力概率？新 Q 到来时哪些量重用、哪些量重算？

   <details><summary>参考答案</summary>

   没有，缓存只存各层各头的 K 和 V。旧位置的 K/V 重用；新位置的 Q/K/V、新 Q 对所有 K 的分数和 softmax 权重、对 V 的加权和每步重算。

   </details>

## 参考资料

- [Hugging Face：注意力与缓存说明](https://huggingface.co/docs/transformers/main/cache_explanation) · [KV cache 文档](https://huggingface.co/docs/transformers/kv_cache)
- [vLLM 前缀缓存](https://docs.vllm.ai/en/stable/design/prefix_caching/) · [PagedAttention，Kwon 等，2023](https://arxiv.org/abs/2309.06180)
