---
title: "第 25 章：自回归生成"
description: "从 logits 到屏幕上的一个字：温度、top-k 与 top-p、重复惩罚、随机种子与停止条件，以及把格式写进掩码的约束解码。"
pageClass: tinyllm-course
---

# 第 25 章：自回归生成

[课程总览](./index.md) · [上一章](./mixture-of-experts.md) · [下一章](./inference-efficiency.md)

::: tip 本章学习目标
能说清 logits → 温度 → 截断 → 抽样这条链上每一步改了什么，并用代码算出同一个位置的熵和 top-p 需要几个候选；能用同一批种子复现一段生成，并解释为什么换种子、换温度会让结果不同；能把一个确定的格式写成每步允许的 token 集合，用掩码让格式永远合法。

**前置：** [第 5 章](./embeddings-and-output.md)的 logits 与交叉熵、[第 12 章](./tinyllm-model.md)训好的基线模型。

**实践方式：** [generation.ipynb](/tinyllm/notebooks/generation)（也可以直接运行 <a href="/tinyllm/code/generation.py" download>generation.py</a>），CPU 约一分半，需要 PyTorch 和 `tokenizers`。
:::

<TinyLLMMap active="generation" />

## 问题：模型已经会打分，字还没出来

[第 12 章](./tinyllm-model.md)的模型每次前向输出 `[1, T, 4096]` 的 logits：每个位置对下一个 token 的 4096 个原始打分。最后一节“让它写几首”里，我们已经在用这些打分生成诗了，只是两行带过（示意，完整实现见[第 12 章的脚本](https://lewislau86.github.io/tinyllm/code/tinyllm-model.py)）：

```python
logits = model(idx[:, -cfg.context:])[:, -1, :] / temperature
next_id = torch.multinomial(F.softmax(logits, dim=-1), 1, generator=generator)
```

这两行，是本课程第一次真正“用”模型。本章把它拆开：为什么除以温度、为什么要在抽样前截断、要不要惩罚重复、怎样让同一段输出能复现、怎样让格式永远合法。这些参数在今天每一个推理接口里都有名字，本章要说清它们各自改了什么、没改什么。

::: info 本章代码从哪里来
本章所有代码都在一个文件里：<a href="/tinyllm/code/generation.py" download>generation.py</a>（[在 GitHub 上查看](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/tinyllm/code/generation.py)）。下面的代码块都是从这个文件里直接截取的片段，所以单独复制一段可能缺少 `import` 或前面定义的变量；想自己运行，请下载完整文件，`python generation.py` 从头跑到尾即可。notebook 版本也由同一个文件生成，可以[在线查看](/tinyllm/notebooks/generation)，或[在 Colab 中直接运行](https://colab.research.google.com/github/lewislau86/lewislau86.github.io/blob/master/docs/public/tinyllm/notebooks/generation.ipynb)。正文引用的输出来自 torch 2.14.1+cpu、tokenizers 0.23.3。
:::

## 1. 温度：把打分整体除以一个数

logits 不是概率，要过 softmax。温度 $T$ 的做法是在 softmax 之前把打分除以它：

$$
p_i = \frac{\exp(z_i / T)}{\sum_j \exp(z_j / T)}
$$

拿六个候选、一组手写的打分试三次。同时算两个后面一直要用的量：**熵** $H = -\sum_i p_i \log p_i$，衡量这个分布有多平；以及 **top-p 需要几个候选**——按概率从大到小累加，凑到 0.9 为止用了几个。

<<< @/public/tinyllm/code/generation.py#hand

```text
T=0.5  概率 [0.979, 0.018, 0.002, 0.001, 0.0, 0.0]  熵 0.115  top-p(0.9) 用到 1 个
T=1.0  概率 [0.817, 0.111, 0.041, 0.025, 0.006, 0.002]  熵 0.672  top-p(0.9) 用到 2 个
T=2.0  概率 [0.527, 0.194, 0.118, 0.092, 0.043, 0.026]  熵 1.358  top-p(0.9) 用到 4 个
```

除以一个正数不改变谁大谁小，只改变差距。$T<1$ 把高分推得更高、低分压得更低；$T>1$ 抹平差距。$T \to 0$ 时概率全落到最大那一个，就是贪心解码。

熵这一列值得多看两眼：同一组打分，只换温度，熵从 0.115 走到 1.358。**温度不改模型对下一个字的判断，只改从这份判断里取多宽的样本。**

## 2. top-k 与 top-p：截掉长尾

在整张词表上直接抽样，偶尔会抽到概率极低的字，读起来就是错字。两种截法都先砍掉长尾再重新归一化：top-k 留打分最高的 $k$ 个；top-p 留累计概率刚好达到 $p$ 的最小集合。

<<< @/public/tinyllm/code/generation.py#truncate

```text
尖峰分布：top-k=3 留 3 个，top-p=0.9 留 2 个，熵 0.603
平坦分布：top-k=3 留 3 个，top-p=0.9 留 6 个，熵 1.777
```

![top-k 与 top-p 在两种分布上的区别：左边是六个候选的概率柱，尖峰分布里 top-p 只要 2 个就凑够 90%，平坦分布要 6 个；top-k 不管分布在哪种情况下都留 3 个](/tinyllm/figures/sampling-truncate.svg)

怎么读这张图：横轴是留几个候选，柱高是这一个候选的概率。橙色虚线是 0.9。**top-p 的集合大小随分布变化，top-k 的集合大小是常数**——这是两者的全部差别。诗句里“句末必然是标点”的位置分布很尖，“逗号之后该起什么字”的位置很平，下一节会看到同一个模型上两者差多少。

## 3. 训一个小模型，用真实分布做实验

前两节的数字是手写的。要观察采样参数的实际效果，得有一个真的会写诗的小模型。沿用[第 12 章](./tinyllm-model.md)的配方，把配置缩到 CPU 能在一分多钟内跑完：词表 2048、宽度 128、4 层、4000 首唐诗、1200 步。它写得不好——这正好，本章比较的是采样参数的相对效果，不需要一个好模型。

<<< @/public/tinyllm/code/generation.py#train

```text
1,049,216 个参数，1200 步后验证损失 5.613 nats/token
训练集里不同的字 4229，词表 2048
```

注意最后一行：训练集里有 4229 个不同的字，词表只有 2048。一半以上的字要拆成 2～3 个字节 token。这会在第 7 节变成一个可测的量——温度调高以后，模型更容易抽出“半个字”。

## 4. 同一个模型，每个位置的难度差很多

拿一句熟悉的诗，逐字喂给模型，看每个位置预测下一个字时的熵和 top-p 需要的候选数。

<<< @/public/tinyllm/code/generation.py#difficulty

```text
提示词“春眠不觉晓，”
  “春”之后：熵  4.58  top-p(0.9)  491 个  前三个 。0.34 ，0.07 水0.01
  “眠”之后：熵  4.76  top-p(0.9)  403 个  前三个 。0.28 夜0.03 客0.03
  “不觉”之后：熵  2.13  top-p(0.9)   56 个  前三个 ，0.70 新0.02 。0.01
  “晓”之后：熵  0.25  top-p(0.9)    1 个  前三个 ，0.97 。0.01 霜0.00

提示词“空山不见人，”
  “空山”之后：熵  3.68  top-p(0.9)  259 个  前三个 。0.49 ，0.02 一0.02
  “不见”之后：熵  2.89  top-p(0.9)  120 个  前三个 ，0.54 。0.10 新0.02
  “人”之后：熵  0.81  top-p(0.9)    2 个  前三个 。0.86 ，0.09 归0.00
```

![逐个位置的熵与 top-p 候选数：句末标点位置熵低于 1、只要一两个候选；逗号之后熵在 4 到 5 之间、要四百多个候选才凑够 90%](/tinyllm/figures/sampling-difficulty.svg)

怎么读这张图：横轴是位置，柱子是熵，折线是 top-p(0.9) 需要的候选数（对数坐标）。两条曲线同起同落——**熵高的位置就是需要更多候选的位置**。这也解释了一件事：固定的 top-k 在这条曲线上不可能一直合适，取 50 时句末位置太宽、逗号之后太窄。top-p 跟着分布走，自动变窄变宽。

“晓”之后的熵只有 0.25，说明这个模型非常确定下一字是逗号——它记住的是“五字一标点”这个格式，不是这句诗的意思。

## 5. 温度把整条分布拉开或压扁

挑一个犹豫的位置（逗号之后），把同一个 logits 用不同温度换算，比较熵和候选数。

<<< @/public/tinyllm/code/generation.py#temps

```text
T=0.3  熵  2.36  top-p(0.9) 需要    9 个  前五个 寒0.318  春0.175  明月0.106  秋0.104  翻0.084
T=0.5  熵  4.02  top-p(0.9) 需要   92 个  前五个 寒0.140  春0.098  明月0.073  秋0.072  翻0.063
T=1.0  熵  6.27  top-p(0.9) 需要  657 个  前五个 寒0.025  春0.021  明月0.018  秋0.018  翻0.017
T=1.5  熵  6.94  top-p(0.9) 需要 1051 个  前五个 寒0.009  春0.008  明月0.008  秋0.008  翻0.007
T=2.0  熵  7.21  top-p(0.9) 需要 1259 个  前五个 寒0.005  春0.005  明月0.004  秋0.004  翻0.004
```

同一列“前五个”从头到尾没变过顺序：寒、春、明月、秋、翻。温度只动了它们之间的比例，从 0.318 一路摊到 0.005。**温度不会让模型想到新的候选，只会把已有的候选推得更平或更尖。**

## 6. 抽样、复现与停止条件

生成循环只有四步：前向拿最后一个位置的 logits → 可选地改打分（惩罚、掩码）→ 除以温度、截断、softmax → 按概率抽一个。抽完接到序列末尾，直到遇到 `<eos>` 或到 `max_new_tokens`。

<<< @/public/tinyllm/code/generation.py#sample

```text
贪心               寒色照中秋。
T=0.9，种子 3      愁人见绿波。
T=0.9，种子 3 再跑  愁人见绿波。  ← 与上一行完全相同
T=0.9，种子 4      寒嗣过长沙。  ← 换个种子就不同
```

同一段代码跑两次，种子不变就一个字都不差——因为 `torch.multinomial` 用的随机数流完全由 `generator` 的状态决定。换个种子，“愁人见绿波”变成“寒嗣过长沙”；把 `greedy=True` 打开，输出固定成“寒色照中秋”。

“固定种子”保证的是**同一个随机数流**，不保证跨硬件、跨 batch 完全一致：浮点求和的顺序会随 batch 大小和并行方式变化，同一个种子在大模型上偶尔也会差一个 token。需要严格可复现的评估，就用贪心解码——这是[课程总览](./index.md#mainline-choices)主线里写下的选择。

## 7. 温度调高以后，生僻字变多了

同一个开头、同一批种子，只改温度，各写满 24 个字，数一件事：生成的字里有多少**不在训练集中**。

<<< @/public/tinyllm/code/generation.py#temp-eval

```text
T=0.5  训练集外的字占 0.000  平均每首 22.6 字  例：寒色共秋来。天际一为思，不违千日未。晚帆开一鹤
T=0.9  训练集外的字占 0.011  平均每首 21.8 字  例：斜日共秋来。星桥危落日，独下壑丹青。月影连灯照，
T=1.3  训练集外的字占 0.022  平均每首 22.4 字  例：斜日共秋远。传鳞舞花徧，因臓对西浦。采菊催秋好
T=1.8  训练集外的字占 0.049  平均每首 22.8 字  例：斜曲不知寒。斗鳞舞怀红，因�壑子西臣。采宿故园秋，
```

训练集外的字从 0 一路涨到 4.9%。这些字是几个字节 token 拼出来的：词表只有 2048，生僻字被拆成字节，低温时几乎抽不到，高温时就有机会凑出一个不存在的字。

这就是温度的代价：**它买到的多样性，是从“不出错字”里换来的。** 对这个模型，0.9 附近还算安全；1.8 时已经出现了乱码。

## 8. 重复惩罚：改的不是概率，是打分

生成古诗最常见的问题是同一句反复出现。重复惩罚在抽样之前直接改 logits：已经出现过的 token 打折扣。乘法形式（Hugging Face 接口里的 `repetition_penalty`）把正 logits 除以系数、负 logits 乘以系数。

<<< @/public/tinyllm/code/generation.py#penalty

下面用贪心解码（不受随机性干扰），从同一个开头连写 48 个字，数两字组的多样性。

<<< @/public/tinyllm/code/generation.py#penalty-eval

```text
penalty=1.0  不同两字组占 0.814  空怜白石边。一迳逗霜林，千根碧树平。一窗多雨雪，千佛待月云。一迳逗霜林，三峰不下门。山横
penalty=1.2  不同两字组占 1.000  空怜白石边。一迳逗霜林，千根碧树平。高风闻角韵，寒叶半星芝。野客同谁去，村中见远遥。山深
penalty=1.4  不同两字组占 1.000  空怜白石边。一迳逗霜林，千根碧树平。高风闻角韵，寒叶半星芝。野客同谁去，村中见远遥。山深
penalty=1.6  不同两字组占 1.000  空怜白石边。一迳逗霜林，千根碧树平。高风闻角韵，寒叶半星芝。雨泛清风起，云深隐乱山。因知无远
```

不开惩罚时，“一迳逗霜林”在 48 个字里出现两次，两字组有 18.6% 是重复的。开到 1.2，重复消失，前 30 个字和 1.4 完全一样——说明在 1.2 之后，贪心路径已经不再遇到“该不该惩罚”的分歧。再加到 1.6，前 30 个字仍然一样，后半段才分叉。

注意 1.2 和 1.4 的结果一字不差：**惩罚值不是连续有效的旋钮**，在贪心解码下，它只在某些位置改变次序，其余位置毫无影响。这类参数必须实测，不能照抄别人的推荐值。

## 9. 约束解码：把格式写进掩码

前面几节都在接受模型给出的分布，只在里面挑。如果格式是确定的——五言绝句：四句、每句五字、句末标点——可以在**每一步**只允许合法的 token：其余位置打分设成 $-\infty$，softmax 后概率为 0，采样永远抽不到。

先把格式写成一个函数：给定已经写了几个字符，返回这一步允许的 token 集合。

<<< @/public/tinyllm/code/generation.py#guided

```text
词表 2048 个 token 里，单字 1310 个，逗号 1 个，句号 1 个
不加约束：0/12 首格式合法；加了掩码：12/12 首
不加约束的一首： 之看结庐阜。
加掩码的一首：   之看结庐乌，才子各相关，龙儿好复深。
```

同一批开头、同一批种子，唯一的区别是多传了一个 `allowed`。不加约束时 12 首里 0 首符合“四句五言”，加了掩码 12 首全部符合。

![约束解码的一步：普通采样在 2048 个 token 上算概率，可能抽出标点或半个字；掩码把不合法的位置置成 -inf，softmax 后只剩 1310 个合法单字，再归一化、抽样](/tinyllm/figures/guided-decoding.svg)

怎么读这张图：左边是整张词表，右边是掩码后剩下的合法集合。中间那一步 $-\infty$ 是全部手段——它保证格式永远合法，代价是每步多算一次掩码。

这个方法**不保证内容对**：加掩码的那首读起来并不比不加的好，它只保证了“四句、每句五字、句末标点”。生产系统用有限状态机或文法表示允许集合，支持 JSON、正则等复杂格式，原理与这里一样：**把约束变成每一步的概率掩码。**

## 动手实验

1. **top-p 和 top-k 一起用。** `truncate` 已经支持先 top-k 后 top-p。对第 5 节那个逗号之后的位置，取 `k=50, top_p=0.9` 与只用 `top_p=0.9`，比较留下的候选数。两者会一样吗？什么时候 top-k 才起作用？
2. **惩罚作用在哪些 token 上。** 现在的实现按“出现过的 token ID”惩罚。如果改成按“出现过的字符”惩罚（同一个字的不同字节 token 一起罚），第 8 节的结果会变吗？为什么在字节级 BPE 上这两者不同？
3. **把约束收紧。** 给 `poem_allowed` 加一条：同一个字不许在相邻两句的同一位置重复出现。实现之后重跑第 9 节，格式合法率还是 12/12 吗？内容读起来有变化吗？

## 本章结论：TinyLLM 的选择 {#tinyllm-choice}

TinyLLM 的生成分两种场合。**需要可复现的评估**——比较两个模型、跑固定测试集——用贪心解码：同一个输入永远得到同一个输出，不引入随机性。**开放式交互**提供温度与 top-p，默认取 $T=0.9$、`top_p=0.95`，并显式固定随机种子、`<eos>` 与最大输出长度。

这些默认值的依据是本章测出来的三条：温度越高，训练集外的字越多（第 7 节，0% 到 4.9%）；top-p 留几个候选随位置变化，top-k 不会（第 2、4 节）；重复惩罚在贪心解码下不是连续旋钮（第 8 节）。所以参数不能照抄——换一个模型、换一份语料，这些数都要重测。

格式确定的任务（结构化输出、固定模板、受限 API）不靠提示词祈求，改用约束解码把格式写进掩码；本章第 9 节是最小版本，真实系统用文法或自动机生成允许集合，原理相同。

在什么情况下要换：采样参数随任务走，创意写作可以更宽、事实问答应该更窄；需要大批量生成时，逐 token 的 Python 循环太慢，那属于[第 26 章](./inference-efficiency.md)要处理的事。

::: warning 常见误区
- **温度改了模型的判断。** 温度只是把同一份 logits 除以一个数再取 softmax，候选的排序一点没变；它改的是取样的宽度。把温度调高不会让模型“更有创造力”，只会让低分候选更容易被抽到。
- **固定种子就能完全复现。** 种子固定的是随机数流。浮点求和的顺序随 batch 大小和并行方式变化，跨硬件、跨 batch 的同种子运行仍可能差一两个 token。要严格复现就用贪心。
- **top-k 和 top-p 只是写法不同的同一件事。** top-k 的集合大小固定，top-p 的集合大小随分布变化。句末标点和逗号之后这两种位置，固定的 $k$ 不可能同时合适。
- **加了约束解码，输出就对了。** 掩码只保证格式合法，不改变模型对内容的判断。格式对、内容差，是两件独立的事。
:::

<!-- real-model:start -->

## 在真实模型里

本章的采样步骤在 transformers 里由 `generate()` 调度，真正的取样发生在 `_sample` 里。下表的链接都指向 Hugging Face transformers 的固定版本 `v5.21`，精确到行。读代码时可以先跳过缓存、掩码、并行这些工程细节，只看和本章对应的那几行。

| 本章的零件 | 真实代码 | 对照要点 |
| --- | --- | --- |
| 生成入口 | [`GenerationMixin.generate`](https://github.com/huggingface/transformers/blob/v5.21/src/transformers/generation/utils.py#L2575-L3010) | 准备输入、准备缓存、进入循环；本章的 `generate` 就是这个循环的最小版本 |
| 一步一步生成 | [`GenerationMixin._sample`](https://github.com/huggingface/transformers/blob/v5.21/src/transformers/generation/utils.py#L3115-L3332) | 每步前向、取最后一个位置的 logits、调处理器改打分、抽样、拼接，和本章的四步一样 |
| 温度 | [`TemperatureLogitsWarper`](https://github.com/huggingface/transformers/blob/v5.21/src/transformers/generation/logits_process.py#L238-L303) | `scores / self.temperature` 之后再 softmax，就是本章第 1 节除一下 |
| 重复惩罚 | [`RepetitionPenaltyLogitsProcessor`](https://github.com/huggingface/transformers/blob/v5.21/src/transformers/generation/logits_process.py#L306-L424) | 正负 logits 分开处理：正的除以 penalty、负的乘 penalty，和本章第 8 节逐行对应 |
| top-k | [`TopKLogitsWarper`](https://github.com/huggingface/transformers/blob/v5.21/src/transformers/generation/logits_process.py#L558-L611) | 取 topk 后把其余位置填成 `-inf`，即本章的 `masked_fill` |
| top-p | [`TopPLogitsWarper`](https://github.com/huggingface/transformers/blob/v5.21/src/transformers/generation/logits_process.py#L489-L555) | 排序、累加，把累计概率超过 p 的部分填成 `-inf`，和本章 `truncate` 同一个算法 |
| 约束解码 | [`PrefixConstrainedLogitsProcessor`](https://github.com/huggingface/transformers/blob/v5.21/src/transformers/generation/logits_process.py#L1502-L1574) | 按已生成的前缀查允许列表并填 `-inf`，正是本章第 9 节的做法 |
| 固定随机数流 | [`set_seed`](https://github.com/huggingface/transformers/blob/v5.21/src/transformers/trainer_utils.py#L180-L207) | 同时设置 Python、NumPy 与 torch 的随机种子；本章把 `torch.Generator` 直接传给 `multinomial`，作用相同 |

想在本机看源码，可以先 `pip install transformers`，再用 `python -m inspect transformers.models.llama.modeling_llama:LlamaMLP` 这样的命令打印出任意一个类。

<!-- real-model:end -->

## 检查理解

1. 某个位置上模型的 logits 前两名是 5.0 和 4.5，其余远低。把温度从 1.0 改成 2.0，这两名的概率比会怎么变？改成 0.5 呢？

   <details><summary>参考答案</summary>

   温度只影响两者的指数差。原来比值为 $\exp(5.0 - 4.5) = \exp(0.5) \approx 1.65$。温度 2.0 时比值变成 $\exp(0.25) \approx 1.28$，两者更接近；温度 0.5 时变成 $\exp(1.0) \approx 2.72$，第一名更占优。$T \to 0$ 时比值趋于无穷，第一名拿走全部概率，即贪心。

   </details>

2. 第 4 节里“晓”之后的熵只有 0.25，而“春”之后有 4.58。用同一组 top-k=20 和 top-p=0.9 生成，哪个位置更可能出问题？为什么？

   <details><summary>参考答案</summary>

   问题出在熵高、分布平的位置，也就是“春”之后。top-p=0.9 在那里要四百多个候选，top-k=20 却只留 20 个，把大量本来有意义的候选直接砍掉，输出会变得单调甚至出错。top-p=0.9 在两个位置都合适：熵低时自动缩到一两个候选，熵高时自动放宽到几百个。

   </details>

3. 第 9 节的掩码做法，为什么“每步多算一次掩码”是可以接受的，而“生成完之后再检查格式、不合格就重抽”往往不可接受？

   <details><summary>参考答案</summary>

   重抽的代价是整段重来：一首 24 个字符的诗，格式合格率如果不高，期望要跑好几遍，而每遍都要几百次前向。掩码的代价是每步对一个 2048 维向量做一次赋值，和前向相比可以忽略。更关键的是，重抽不保证能收敛——如果模型强烈偏好某种不合法的写法，可能抽很多次都失败。

   </details>

## 参考资料

- [The Curious Case of Neural Text Degeneration，Holtzman 等，2019](https://arxiv.org/abs/1904.09751)（top-p / nucleus sampling 的出处）
- [Hierarchical Neural Story Generation，Fan 等，2018](https://arxiv.org/abs/1805.04833)（top-k sampling）
- [The Unreasonable Effectiveness of Greedy Search in Neural Machine Translation，Trevett 与 Przystupa，2022](https://aclanthology.org/2022.wngt-1.10/)（贪心在小模型上不输采样的实验）
- [Efficient Guided Generation for Large Language Models，Willard 与 Louf，2023](https://arxiv.org/abs/2307.09702)（Outlines：把正则与文法变成每步的 token 掩码）
- [Hugging Face：生成策略与 logits 处理器](https://huggingface.co/docs/transformers/main_classes/text_generation)

采样参数定好，生成循环也就定好了。但这一版每生成一个字都要把整段前缀重新算一遍——第 12 章那个 64 token 的窗口，生成 40 个字就要算 40 次全量前向。下一章把重复的部分缓存下来：[第 26 章：推理效率](./inference-efficiency.md)。
