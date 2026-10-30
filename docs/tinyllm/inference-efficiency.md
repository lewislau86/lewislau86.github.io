---
title: "第 26 章：推理效率：prefill、decode 与 KV cache"
description: "把一次生成拆成 prefill 和 decode 两段：KV cache 省掉多少重复投影、缓存要占多少显存、decode 为什么卡在带宽，以及 TTFT、TPOT、ITL、E2EL 与 goodput 怎么量。"
pageClass: tinyllm-course
---

# 第 26 章：推理效率：prefill、decode 与 KV cache

[课程总览](./index.md) · [上一章](./generation.md) · [下一章](./attention-kernels.md)

::: tip 本章学习目标
能把一次生成拆成 prefill 与 decode 两段，并说清两段各自卡在算力还是带宽；能算出 KV cache 的大小、数出缓存省下多少行投影；能分别测出首字延迟、每 token 延迟和端到端延迟，并解释为什么只看吞吐会误判。

**前置：** [第 6 章](./self-attention.md)的 Q/K/V 与[第 12 章](./tinyllm-model.md)训好的基线模型，[第 25 章](./generation.md)的生成循环。

**实践方式：** [inference-efficiency.ipynb](/tinyllm/notebooks/inference-efficiency)（也可以直接运行 <a href="/tinyllm/code/inference-efficiency.py" download>inference-efficiency.py</a>），CPU 约一分钟（大部分是训基线模型），需要 PyTorch 和 `tokenizers`。
:::

<TinyLLMMap active="inference-efficiency" />

## 问题：一次前向，两种完全不同的工作

[第 25 章](./generation.md)的生成循环每写一个字就调用一次模型。可“调用一次模型”并不总是同一件事：

- 读入提示词时，十几个 token 一起进去，可以并行处理；
- 之后每多写一个字，只有一个新位置，却还是要把整个模型跑一遍。

同样是“跑一遍模型”，前者处理 10 个位置，后者处理 1 个。如果两者的耗时差不多（下面会看到，确实差不多），那么单位位置上后者要贵十倍。这个差距从哪里来、能省掉多少、代价是什么，是本章的全部内容。

::: info 本章代码从哪里来
本章所有代码都在一个文件里：<a href="/tinyllm/code/inference-efficiency.py" download>inference-efficiency.py</a>（[在 GitHub 上查看](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/tinyllm/code/inference-efficiency.py)）。下面的代码块都是从这个文件里直接截取的片段，所以单独复制一段可能缺少 `import` 或前面定义的变量；想自己运行，请下载完整文件，`python inference-efficiency.py` 从头跑到尾即可。notebook 版本也由同一个文件生成，可以[在线查看](/tinyllm/notebooks/inference-efficiency)，或[在 Colab 中直接运行](https://colab.research.google.com/github/lewislau86/lewislau86.github.io/blob/master/docs/public/tinyllm/notebooks/inference-efficiency.ipynb)。正文引用的输出来自 torch 2.14.1+cpu、tokenizers 0.23.3，单线程运行。
:::

## 1. 研究对象：第 12 章的基线模型

后面所有的量都在同一个模型上测：[第 12 章](./tinyllm-model.md)的配置和同样的 300 步训练。推理效率与模型写得好不好无关，只需要一个尺寸确定、参数已知的模型。

<<< @/public/tinyllm/code/inference-efficiency.py#train

```text
参数 1,311,360 个，权重占 5.0 MiB（FP32）
词表 4096，上下文 64，4 层，4 个头，每头 32 维
```

5.0 MiB 这个数后面要用两次：一次算 decode 的带宽上限，一次和 KV cache 的大小做对比。

## 2. 两段：prefill 与 decode

提示词的每个 token 在生成之前就已经全部到齐，可以一次性并行送进模型，这段叫 **prefill**。之后每步只多出一个 token，却要再走一遍完整的模型，每步叫一次 **decode**。

两段算的东西不一样：prefill 一次处理 $T$ 个位置，矩阵乘法的行数是 $T$，算力用满，**卡在计算**；decode 一次只处理 1 个位置，矩阵乘法的行数是 1，但每步都要把全部权重从内存读一遍，**卡在带宽**。

<<< @/public/tinyllm/code/inference-efficiency.py#phases

脚本会打印两行。第一行是两段的绝对耗时：在这台机器上，10 个 token 的 prefill 和之后每步 decode 都落在 1.2～1.3 ms 之间。第二行把耗时摊到位置上：**decode 处理一个位置的代价，是 prefill 处理一个位置的九到十倍。**

绝对耗时每次运行都会有一两成的浮动，所以这里不给出固定数字；那九到十倍的比例是稳定的，它来自两段工作的性质差别。

为什么会这样？上面算过权重只有 5.0 MiB。读取这 5.0 MiB 的时间是固定的：分摊给 10 个位置还是 1 个位置，读的量不变。decode 慢，不是因为算得多，而是因为**每做一丁点计算，就要等一次完整的权重读取**。

## 3. 不缓存，每一步都重算整段前缀

decode 里每步都把整段前缀重新送进模型。可是旧位置的 K、V 只取决于旧 token，不会因为后面新来了一个字就改变。把它们存下来，就是 **KV cache**。

先用第 5 章的六项教学词表把“一次算完”和“逐步缓存”并排放好，确认结果一致：

<<< @/public/tinyllm/code/inference-efficiency.py#setup

<<< @/public/tinyllm/code/inference-efficiency.py#kv-cache

```text
context 形状: (3, 4)
一次性计算与逐步缓存的最大误差: 2.9802322387695312e-08
缓存了 3 个位置的 K 和 V；缓存的是 K/V，不是注意力分数
```

![KV cache 的两个阶段：prefill 一次算出提示词所有位置的 K/V；之后每个解码步只为新 token 计算 K/V 并追加到缓存，新 token 的 Q 与缓存中全部 K 打分，再对全部 V 加权求和](/tinyllm/figures/kv-cache.svg)

怎么读这张图：左边 prefill 一次把提示词的 K、V 全算出来；右边每个 decode 步只算新来的一个位置。橙色是这一步新算的，灰色是从缓存直接读的。**缓存里没有注意力权重**——权重取决于新来的 Q，每一步都得重算。这一点常被记错，而它决定了缓存能省什么、不能省什么。

## 4. 数一数：不缓存要多算多少行

把位置加到 12 个，数每一步实际投影了几行 K、V。这一步与硬件无关，在任何机器上都是这个结果。

<<< @/public/tinyllm/code/inference-efficiency.py#count

```text
不缓存，每步重算的 K/V 行数: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12] 合计 78
KV cache，每步新算的 K/V 行数: [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1] 合计 12
生成 12 个字：不缓存 78 行 = 12 × 13 / 2，有缓存 12 行 = 12
```

不缓存时第 $t$ 步要重算 $t$ 行，生成 $n$ 个字一共 $n(n+1)/2$ 行，随长度平方增长；有缓存时每步只算 1 行，一共 $n$ 行。两种做法并排播放：

<KVCacheRace />

省下的只是 K、V 的**投影**。新 Q 仍然要和缓存里所有的 K 打分，这部分计算随上下文变长而增加——所以缓存把平方增长的那部分砍掉了，但注意力本身的时间仍然随长度增长。

## 5. 缓存有多大：一条公式和一张表

对普通全注意力 Decoder，每层为每个 token 存一组 K 和一组 V：

$$
\text{缓存字节} = 2 \times \text{层数} \times \text{token 数} \times \text{KV 头数} \times \text{每头维度} \times \text{每元素字节}
$$

最前面的 2 对应 K 和 V；乘以并发请求数就是这一批请求的总量。

<<< @/public/tinyllm/code/inference-efficiency.py#cache-size

```text
TinyLLM（4 层，4 个 KV 头，每头 32 维）
     64 个 token：FP32    0.25 MiB   FP16    0.12 MiB
    256 个 token：FP32    1.00 MiB   FP16    0.50 MiB
   1024 个 token：FP32    4.00 MiB   FP16    2.00 MiB
  上下文 64、8 个请求并发（FP32）：2.00 MiB
Llama 3 8B（32 层，8 个 KV 头，每头 128 维，FP16）
    1024 个 token：  0.12 GiB
    8192 个 token：  1.00 GiB
   32768 个 token：  4.00 GiB
  每个 token 128 KiB；权重 FP16 约 16 GiB，80 GiB 的卡上留给缓存的空间约 64 GiB，理论上限约 64 条 8K 序列
```

![KV cache 的大小：横轴是上下文长度（对数），两条线分别是 TinyLLM 与 Llama 3 8B 的单请求缓存；右侧条形图是同一条 80 GiB 卡上权重与缓存的空间分配](/tinyllm/figures/kv-cache-size.svg)

怎么读这张图：**缓存随 token 数线性增长，而权重是常数。** 小模型上权重占大头，大模型上缓存会先撑满显存——Llama 3 8B 每条 8K 序列要 1 GiB，一张 80 GiB 卡把 16 GiB 留给权重之后，剩下只够约 64 条并发序列。这就是“能同时服务多少用户，往往先卡在缓存而不是权重”的来源。

这张表还解释了 [GQA](./self-attention.md) 为什么省缓存：缓存里的 `KV 头数` 因子决定了它。Llama 3 8B 的 8 个 KV 头是从 32 个 Q 头共享来的，如果每个 Q 头各留一组 K、V，这张表里的每个数都要乘 4。

## 6. decode 为什么慢：每步都要搬一遍权重

一次 decode 只做一行矩阵乘法，却要把全部权重读进来。权重 $W$ 字节，内存带宽 $B$ 字节每秒，每秒最多前向 $B / W$ 次——这是带宽给出的上限，与算力无关。

<<< @/public/tinyllm/code/inference-efficiency.py#bandwidth

```text
TinyLLM（FP32）：权重 0.01 GB，若带宽 200 GB/s，每秒最多前向 38,128 次 → 单请求上限 38,128 token/s
Llama 3 8B（FP16）：权重 16.06 GB，若带宽 3350 GB/s，每秒最多前向 209 次 → 单请求上限 209 token/s
H100 的 3.35 TB/s 是公布值；200 GB/s 是台式机内存的常见量级，不是实测。
```

Llama 3 8B 在 H100 上的单请求上限是每秒 209 个 token，和实践中单请求 decode 的速度在同一量级。TinyLLM 的理论上限高得离谱，因为它的权重只有 5 MiB，全部塞在缓存里，带宽约束根本不起作用——**小模型上看不到 decode 的瓶颈，这是本章所有 CPU 实验的共同边界**。

这条估算也说明了批处理为什么有效：一次读进权重，可以同时伺候多个请求。把这份读取代价摊薄是[第 30 章](./batching.md)的主题。

## 7. 指标：TTFT、TPOT、ITL、E2EL

一次请求的延迟由几个时间段拼成，名字要分开记：

- **TTFT**（Time to First Token）：请求发出到第一个字出现，主要由 prefill 决定；
- **ITL**（Inter-Token Latency）：相邻两个字之间的间隔；
- **TPOT**（Time per Output Token）：$\text{TPOT} = \dfrac{\text{E2EL} - \text{TTFT}}{n - 1}$，$n$ 是生成的字数；
- **E2EL**（End-to-End Latency）：$\text{E2EL} = \text{TTFT} + (n-1) \times \text{平均 ITL}$。

<<< @/public/tinyllm/code/inference-efficiency.py#metrics

8 条请求、各生成 16 个字，脚本打印三个指标的中位数与最慢值。在这台机器上分别是：TTFT 约 1.2 ms、TPOT 约 1.3 ms、E2EL 约 21 ms；最慢的那条比中位数慢一到三成。三个数每次运行都会浮动，比例关系不变：**TTFT 只占 E2EL 的一小部分，绝大部分时间花在 15 段 decode 上。**

![延迟指标的时间线：请求发出后先做 prefill（红色括号是 TTFT），之后每生成一个字做一次 decode（浅绿块），块与块之间的间隔是 ITL；decode 段的总时间除以字数减一是 TPOT，全程是 E2EL](/tinyllm/figures/latency-metrics.svg)

怎么读这张图：TTFT 只覆盖 prefill，E2EL 覆盖全程，TPOT 是 decode 段的平均值。一个系统可以 TTFT 很快、TPOT 很慢，也可以反过来，所以三个数必须一起报。

单条请求上，平均 ITL 就等于 TPOT。多条请求上要小心口径：**按请求平均的 TPOT** 给每个请求同样的权重，**按 token 平均的 ITL** 给长回答更多权重。看别人的基准报告时先确认它用的是哪个，否则同一个系统能读出两个不同的数。

还有一件事：这里报的是中位数和最慢值，不是平均。8 条请求里有 1 条慢，平均只动一点，但那条慢请求的用户体验很差。生产上常报 P50 与 P99。

## 8. goodput：只有达标的那部分吞吐才算数

吞吐（每秒完成多少请求、每秒生成多少 token）单独看会骗人：把 batch 开大，吞吐上去了，但每个请求都变慢了。于是有了 **goodput**——在满足时延目标（SLO）的前提下，每秒完成了多少请求。

<<< @/public/tinyllm/code/inference-efficiency.py#goodput

脚本用这一批请求自己的分位数定出三档 SLO，所以达标条数一定是 8、4、2——脚本打印的三行正是“goodput 是吞吐的 100%、50%、25%”。**吞吐一个数没变，goodput 掉到一半、再掉到四分之一。**

这就是为什么只看吞吐会误判：系统什么都没改，只是要求变严了，“每秒能完成多少有用的请求”就少了一大半。生产上的 SLO 由用户需求决定，不由系统自身决定。

## 9. chunked prefill：长提示词不再把别人堵住

线上不会只有一条请求。一个长提示词的 prefill 会占住整个前向，正在 decode 的请求只能在旁边等——用户看到的是“输出卡住了一下”。把提示词切成几块、分几次前向，每块之间让 decode 插进来，就叫 **chunked prefill**。

分块不改变数学结果：后面的块通过 KV cache 看到前面的块，等价于一次算完。这一点可以直接证明。

<<< @/public/tinyllm/code/inference-efficiency.py#chunked

```text
提示词切成 3 块（每块最多 8 个 token），共 21 个位置
一次算完与分块计算的最大误差: 0.0
```

误差是 0.0，说明分块只是在调度上把一次大的前向切成几次小的，算术上完全等价。有一个细节必须做对：**RoPE 要按全局位置转**。第三块的第 1 个位置是整段里的第 17 个位置，如果每块都从 0 开始编号，位置信息就错了——上面这个函数里 `base` 就是干这件事的。

chunked prefill 的收益是**别的请求不必等这一次长前向做完**；代价是调度更复杂，小块要反复读 KV cache，反而可能变慢。块大小没有通用最优值，要看提示词长度分布和并发量。

## 动手实验

1. **缓存省了多少时间。** 用第 4 节的 12 个位置，分别测“每步重算前缀”和“逐步缓存”的实际耗时（各跑 50 次取平均）。在 TinyLLM 这个尺寸上，缓存省的时间占多少？如果换成 Llama 3 8B 的尺寸（权重 16 GiB），这个比例会怎么变？
2. **GQA 省多少缓存。** 把 `H`（KV 头数）改成 1，其余不变，按第 5 节的公式算上下文 64 时的缓存大小，和原来比一比。注意模型的 Q 头数没有变，所以这需要改注意力里 K、V 的投影宽度，不是只改一个常数。
3. **SLO 与并发。** 现在的 8 条请求是串行跑的。把 batch 改成一次 4 条（一次前向处理 4 个请求），吞吐会涨、TPOT 也会涨。在什么 SLO 下，加 batch 仍然划算？

## 在真实模型里

KV cache 在真实代码里由缓存类管理，注意力每一层把新的 K、V 交给它。下表的链接都指向 Hugging Face transformers 的固定版本 `v5.21`，精确到行。读代码时可以先跳过缓存、掩码、并行这些工程细节，只看和本章对应的那几行。

| 本章的零件 | 真实代码 | 对照要点 |
| --- | --- | --- |
| 创建缓存 | [`modeling_llama.py 第 373 行`](https://github.com/huggingface/transformers/blob/v5.21/src/transformers/models/llama/modeling_llama.py#L373) | `use_cache=True` 且没有传入缓存时新建一个 |
| 每层写入缓存 | [`modeling_llama.py 第 251 行`](https://github.com/huggingface/transformers/blob/v5.21/src/transformers/models/llama/modeling_llama.py#L251) | 拿到这一层新 token 的 K、V 后交给缓存，换回包含全部历史的 K、V |
| 追加到末尾 | [`DynamicLayer.update`](https://github.com/huggingface/transformers/blob/v5.21/src/transformers/cache_utils.py#L118-L137) | `torch.cat([self.keys, key_states], dim=-2)`：沿序列维拼接，和本章逐步缓存的写法一样 |

想在本机看源码，可以先 `pip install transformers`，再用 `python -m inspect transformers.models.llama.modeling_llama:LlamaMLP` 这样的命令打印出任意一个类。

## 本章结论：TinyLLM 的选择 {#tinyllm-choice}

TinyLLM 的推理分两段看：**prefill** 和 **decode**。逐 token 生成时默认复用 **KV cache**，并且分别测首字延迟和每 token 延迟，不把两者合成一个“生成速度”来报。

本章固定下来的几件事：缓存字节数用 $2 \times$ 层数 $\times$ token 数 $\times$ KV 头数 $\times$ 每头维度 $\times$ 每元素字节 估，再乘并发数；注意力用 PyTorch 的缩放点积注意力接口，让框架去选高效内核（[第 27 章](./attention-kernels.md)讲它省了什么）；长提示词分块送入，并验证分块与一次算完逐元素一致。

这些选择在什么情况下要换：上下文和并发变大时，缓存会成为显存瓶颈，那时要靠 GQA、KV 量化（[第 28 章](./quantization.md)）或分页管理（[第 31 章](./kv-memory.md)）；请求变多时要靠批处理摊薄权重读取（[第 30 章](./batching.md)）。缓存始终只存**本次推理的计算结果**，不是替 Agent 保存用户事实的长期记忆，后者见[第 37 章](./agent-memory.md)。

::: warning 常见误区
- **KV cache 存了注意力权重。** 缓存只有各层各头的 K 和 V。权重取决于新来的 Q，每步都要重算。
- **缓存省下的是全部注意力计算。** 省下的是旧位置的 K、V 投影；新 Q 与全部 K 的打分仍随上下文长度线性增长。
- **训练时也用得上 KV cache。** 训练把整段序列一次并行算完，缓存只在逐 token 生成时有意义。
- **吞吐高就是系统好。** 吞吐不看时延目标。同一批请求，SLO 收紧一点，goodput 就能掉一半（第 8 节）。
- **缓存和 Agent 的长期记忆是一回事。** 缓存随请求结束就消失，也不按语义检索。跨会话的事实要放在模型外的存储里。
:::

## 检查理解

1. 一条请求的提示词有 500 个 token，生成 20 个字。TTFT 主要由哪一段决定？如果想把 TTFT 减半，可以动哪些东西？

   <details><summary>参考答案</summary>

   TTFT 由 prefill 决定，也就是那 500 个 token 的一次前向。可以缩短提示词、把小批量提示词分块并与其他请求拼批（chunked prefill 主要改善别人的 ITL，对这条请求自己的 TTFT 往往是增加）、换更强的算力或用更高效的内核。生成 20 个字只影响，因为 TPOT 覆盖的是后续 decode。

   </details>

2. Llama 3 8B（32 层、8 个 KV 头、每头 128 维、FP16）在 8K 上下文时，一条序列的 KV cache 有多大？如果把 KV 头改成 32 个（MHA），变成多少？

   <details><summary>参考答案</summary>

   $2 \times 32 \times 8192 \times 8 \times 128 \times 2 = 1{,}073{,}741{,}824$ 字节，正好 1 GiB。改成 32 个 KV 头，多乘 4，变成 4 GiB。同一张卡能容纳的并发序列数相应从约 64 条降到约 16 条——这就是 GQA 在长上下文上的实际价值。

   </details>

3. 第 8 节的 goodput 在“中”档 SLO 下是一半，“紧”档是四分之一。为什么不同时报一个“平均吞吐”代替？

   <details><summary>参考答案</summary>

   平均吞吐不包含任何时延约束，两次运行如果吞吐一样但达标率不同，平均值看不出区别。goodput 的价值恰恰在于它把“时延目标”和“完成量”绑在一起：同一批请求、同一个系统，SLO 一变，goodput 就变，而吞吐不变。所以报吞吐必须同时报 SLO，否则这个数没有可比性。

   </details>

## 参考资料

- [Hugging Face：注意力与缓存说明](https://huggingface.co/docs/transformers/main/cache_explanation) · [KV cache 文档](https://huggingface.co/docs/transformers/kv_cache)
- [vLLM 前缀缓存](https://docs.vllm.ai/en/stable/design/prefix_caching/) · [PagedAttention，Kwon 等，2023](https://arxiv.org/abs/2309.06180)
- [SARATHI：chunked prefill 与 decode-maximal batching，Agrawal 等，2023](https://arxiv.org/abs/2308.16369)
- [DistServe：goodput 优化的推理系统，Zhong 等，2024](https://arxiv.org/abs/2401.09670)
- [Llama 3 的模型规模与架构，Grattafiori 等，2024](https://arxiv.org/abs/2407.21783)

KV cache 把重复计算砍掉了，可每一次前向内部还有一个大头没动：注意力要读写一张随长度平方增长的分数表。下一章把这次计算本身拆开看：[第 27 章：注意力内核与算子融合](./attention-kernels.md)。
