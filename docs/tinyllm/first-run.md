---
title: "第 1 章：先跑通一个最小 TinyLLM"
description: "不讲原理，先用不到 100 行 PyTorch 把“文本 → 编号 → 模型 → 损失 → 更新 → 生成”整条流水线跑一遍。"
pageClass: tinyllm-course
---

# 第 1 章：先跑通一个最小 TinyLLM

[课程总览](./index.md) · [下一章](./tensors-and-autograd.md)

::: tip 本章学习目标
知道 LLM 从翻译模型到 GPT 的来历，理解它的核心只是“预测下一个 token”；在自己的电脑上训练一个能“写诗”的小语言模型，亲眼看到损失下降、输出从乱码变成诗句；能指着代码说出每一段对应总图里的哪个零件、由后面哪一章详细讲。

**前置：** 会运行 Python，按[实验环境](./setup.md)装好 PyTorch、下载好代码。不需要懂任何深度学习。

**实践方式：** [first-run.ipynb](/tinyllm/notebooks/first-run)（也可以直接运行 <a href="/tinyllm/code/first-run.py" download>first-run.py</a>），CPU 约半分钟。
:::

后面的章节会把语言模型拆成零件，一件件讲清楚。拆开之前，先把整台机器开起来看看它在做什么。这一章的代码**故意不解释原理**：遇到看不懂的地方，记下它属于总图里的哪个零件就够了，后面会有专门的章节回答。

<TinyLLMMap active="first-run" />

## 先补一段背景：LLM 是从翻译模型变来的

动手之前，先弄清楚一件事：今天的大语言模型（LLM）最核心的能力是什么。

2017 年的 Transformer 是为机器翻译设计的：编码器读完整句原文，解码器一个词一个词地写译文，训练要用“原文 → 译文”的配对数据。2018 年的 GPT 把编码器整个去掉，只留下解码器，在普通文本上反复练习“看前面，猜下一个词”。这一减法打开了一扇门：任何文字都能当训练数据，不需要人工标注。之后的 GPT-2、GPT-3 结构大体不变，变的是规模：参数从 1 亿多涨到 1750 亿，语料从几千本书涨到几千亿个 token。到 2026 年，最强的开放模型之一 Kimi K3 有 2.8 万亿个参数、一次能读 100 万个 token，零件换了不少，“只有解码器、预测下一个 token”的骨架没有变。这段历史的细节和每一代改了什么，放在[第 3 章：架构演进](./architecture-evolution.md)。

把这段历史压成一句话：

> **LLM 的核心只有一件事：预测下一个 token。它能做到多少，主要取决于规模：读了多少语料、模型有多大、花了多少算力。**

这门课要亲手搭的 TinyLLM，正是 GPT 这种“只有解码器”的结构，也就是上面那张总图。这一章我们先用最小的规模把它跑起来：语料只有 39 首唐诗，你会亲眼看到，规模太小的时候，“预测下一个字”会变成什么样子。

## 1. 准备语料：39 首五言唐诗

::: info 本章代码从哪里来
本章所有代码都在一个文件里：<a href="/tinyllm/code/first-run.py" download>first-run.py</a>（[在 GitHub 上查看](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/tinyllm/code/first-run.py)）。下面的代码块都是从这个文件里直接截取的片段，所以单独复制一段可能缺少 `import` 或前面定义的变量；想自己运行，请下载完整文件，`python first-run.py` 从头跑到尾即可。notebook 版本也由同一个文件生成，可以[在线查看](/tinyllm/notebooks/first-run)，或[在 Colab 中直接运行](https://colab.research.google.com/github/lewislau86/lewislau86.github.io/blob/master/docs/public/tinyllm/notebooks/first-run.ipynb)。
:::

语言模型要从文本里学规律，所以先准备文本。这里用 39 首五言唐诗，每首一行，一共一千多个字。前 35 首用来训练，最后 4 首**不给模型看**，留着检查它是不是真学会了：

<<< @/public/tinyllm/code/first-run.py#split

这点数据对语言模型来说少得可怜，后面我们会看到它带来的后果。

## 2. 把文字变成编号

模型只会处理数字。最简单的办法是给每个不同的字分配一个编号：

<<< @/public/tinyllm/code/first-run.py#tokenizer

运行后，“床前明月光”变成 `[169, 65, 237, 253, 45]`，`decode` 能把它原样还原。这 556 个字（包括标点和换行符）就是模型的**词表**。真实模型不会一个字一个号，而是用 BPE 这类分词器，见[第 4 章](./tokenization.md)。

## 3. 训练样本：看前面，猜下一个

语言模型只学一件事：<strong>根据前面的字，预测下一个字。</strong>从语料里随机截一段 24 个字作为输入 `x`，再把它整体往后挪一位作为目标 `y`：

| 位置 | 0 | 1 | 2 | 3 | 4 | … |
| --- | --- | --- | --- | --- | --- | --- |
| 输入 `x` | 床 | 前 | 明 | 月 | 光 | … |
| 目标 `y` | 前 | 明 | 月 | 光 | ， | … |

看到“床”要猜“前”，看到“床前”要猜“明”，看到“床前明”要猜“月”……一段 24 个字的样本，同时提供了 24 道练习题。一次取 32 段，就得到形状为 `[32, 24]` 的 `x` 和 `y`。这个“错开一位”的目标在[第 15 章](./language-model-loss.md)细讲。

截取样本的代码只有几行：

<<< @/public/tinyllm/code/first-run.py#batch

## 4. 模型：一个很小的 Transformer

下面就是全部模型代码。现在不需要看懂每一行，只要把注释里的章节号和上面总图对上：

<<< @/public/tinyllm/code/first-run.py#model

从 `forward` 往下读，正好是总图从上到下的顺序：编号查表变成向量，加上位置信息，穿过 3 个 Block，最后归一化，再变回词表上每个字的分数（logits）。整个模型约 39 万个参数，而今天的大模型有几百亿甚至上万亿个。

![第 1 章模型的形状流：32 段、每段 24 个字的编号查表变成 [32, 24, 96]，穿过 3 个 Block 形状不变，最后乘字表的转置得到 [32, 24, 556]；训练时和错位的目标算交叉熵，生成时只取最后一个位置](/tinyllm/figures/first-run-shapes.svg)

怎么读这张图：左边一列是一次前向，方括号是张量形状。`[32, 24]` 是 32 段文字、每段 24 个字；查表以后每个字变成 96 个数；3 个 Block 只改数值、不改形状；最后每个位置都给 556 个字各打一个分。橙色虚线表示输出层用的就是最上面那张字表。右边是这些分数的两种用法：训练时和“往后错一位”的目标比，生成时只看最后一个位置。

## 5. 训练之前，先让它写一首

生成的办法也很直接：把已有的字送进模型，取最后一个位置的分数，按概率抽一个字接在后面，重复下去，遇到换行就停。

<<< @/public/tinyllm/code/first-run.py#generate

参数还是随机的，以“春”开头写出来是这样：

```text
训练前： 春问巾兹戎除至细车秀无孙除秦蓬宦胜胜俱浑戍除短有入鱼五醅就杯杯怜乾桑地厌适适适歇歇戍适名王杯适适幽
```

全是随机挑的字，连标点都没有。温度、采样这些细节在[第 27 章](./generation.md)讲。

把这 48 步放慢来看。每一步，模型都给词表里所有 556 个字各算出一个概率，再按概率抽一个接在后面。点“播放”或拖动滑块：

<NextTokenPlayer stage="before" />

参数是随机的，概率最高的字也只有百分之几，抽中的字常常排在第几十、几百名，所以写出来是一串乱码。后半段反复出现“适”“歇”“杯”：输入和输出共用一张词表（[第 5 章](./embeddings-and-output.md)），随机的模型容易给刚出现过的字打高分。

## 6. 训练：同一个骨架重复 600 次

先定义损失：把每个位置的 logits 和目标字做交叉熵，再取平均。

<<< @/public/tinyllm/code/first-run.py#loss

训练循环的核心是中间四行，每一步都一样：取一批样本，前向算损失，清空旧梯度，`backward()` 求梯度，`optimizer.step()` 更新参数。其余几行只是在记录损失、定期打印：

<<< @/public/tinyllm/code/first-run.py#train

**损失**衡量模型猜得有多差，越小越好。`backward()` 算出每个参数该往哪个方向调，`optimizer.step()` 真的去调一小步。每隔 10 步，我们再用那 4 首没训练过的诗算一次损失，叫**验证损失**，只看不调。

![训练损失从约 6.7 迅速降到约 0.1；验证损失只在开头略降，随后上升到约 8.1，超过完全乱猜的水平](/tinyllm/figures/first-run-loss.svg)

这张图值得多看一会儿：

- **起点约等于“完全乱猜”。** 刚开始训练损失是 6.67，很接近橙色虚线 $\ln 556\approx6.32$：如果模型对 556 个字一视同仁，每个字的概率都是 $1/556$，交叉熵正好是 $\ln 556$。这是检查代码有没有写错的第一个信号。
- **训练损失降得很快。** 200 步左右就降到 0.2 以下，说明模型几乎能准确说出训练集里每个字后面是什么。
- **验证损失却在上升。** 它只在最开始稍降，随后一路涨到 8 以上，比乱猜还差。模型没有学到“怎么写诗”，而是把 35 首诗**背了下来**；碰到没见过的诗，它反而更自信地猜错。这叫**过拟合**。数据只有一千多字，这几乎是必然的结果。

## 7. 训练之后，再写几首

用同样的开头再生成一次：

```text
春乃发生。随风潜入夜，润物细无声。野径云俱黑，江船火独明。晓看红湿处，花重锦官城。
月是故乡明。有弟皆分散，无家问死生。寄书长不达，况乃未休兵。
山中相送罢，日暮掩柴扉。春草明年绿，王孙归不归。
孤舟。戎马关山北，凭轩涕泗流。
```

还是同一个过程：算概率，抽一个字，接上，再算下一步。切到“训练 600 步之后”再播放一遍：

<NextTokenPlayer stage="after" />

只有第 1 步还有点悬念：“春”后面接“乃”的概率是 36%，“涧”“山”“入”“风”各有约 10%，因为好几首诗里“春”后面跟着不同的字。一旦抽中“乃”，后面 40 步（包括最后的换行）每一步的概率都在 98% 以上，模型几乎没有在“选”，只是把记住的那首《春夜喜雨》接着往下写。

格式完全对了：五个字一顿，逗号句号交替，一首诗以换行结束。但仔细看，每一句都是训练集里的原句：“春乃发生”接的是《春夜喜雨》的“当春乃发生”，“孤舟”后面接的是《登岳阳楼》里紧跟在“老病有孤舟”之后的那一句。这和验证损失讲的是同一件事：**训练损失低，不等于学会了。**

你的输出应该和上面一致：代码固定了随机种子，CPU 上的结果可以复现。换一台机器或另一个 PyTorch 版本，个别字可能不同，但趋势相同。

## 8. ChatGPT 也是这样“学会”的吗？

是的，做的是同一件事：**看前面的字，猜下一个字**。区别只在规模：我们的语料是一千多个字、模型有 39 万个参数；大模型读的是几万亿个 token、参数有几百亿到上万亿个。语料多到背不下来，模型只能去抓文字背后反复出现的规律，回答问题时看起来聪明，靠的就是这些压缩进参数里的规律。

规模再大，有两件事不会变：模型永远只是“接着往下写”；它知道的东西停在训练结束那天，没读过的内容只能照着规律编，这就是“幻觉”。今天的 AI 助手能回答最新的问题、能读你的文件，是因为模型外面多了一层 **Agent**：一段普通程序，先替模型去搜索、读文件、调工具，把结果放进上下文，再让同一个模型接着写。

![上下文交给模型，模型预测出一段描述下一步动作的文字，例如读取某个文件；Agent 真的执行这个动作，把文件内容、搜索结果或报错信息追加进上下文；模型读到新资料后判断是否足够，够了就写最终回答，不够就再转一圈](/tinyllm/figures/agent-loop.svg)

怎么读这张图：模型写出一段“下一步做什么”的文字，比如 `read_file("test.log")`，对它来说这只是又一串 token；Agent 认出这是一个动作，真的去执行，把结果追加到上下文末尾，再交回模型。转几圈、资料够了，模型写出最终回答。模型参数一个都没改，变的只是上下文。所以让模型更“懂”有两条路：

| 改哪里 | 怎么做 | 什么时候生效 | 本课章节 |
| --- | --- | --- | --- |
| 改参数 | 用新数据继续训练、微调 | 训练完以后；代价大，要重新跑训练 | [第 38 章 · 指令微调](./instruction-finetuning.md) |
| 改上下文 | 检索资料、调用工具、读取记忆，放进提示词 | 这一次回答立刻生效 | [第 44 章 · LLM 和 Agent 的交互](./llm-agent-interaction.md) |

这本书前 43 章都在“改参数”这一行，从零把模型训出来；最后一章回到这张图，把它拆开：消息怎样经过对话模板变成 token、工具调用的格式、循环何时停下、上下文装不下时怎样存取记忆（[第 44 章](./llm-agent-interaction.md)）。

## 9. 这一章故意省略了什么

为了让代码短到能一眼看完，这个模型在很多地方用了最简单的做法。后面的章节会一个个换掉：

| 这一章的做法 | 问题 | 由哪一章改进 |
| --- | --- | --- |
| 一个字一个编号 | 遇到没见过的字就无法编码；英文、代码很低效 | [第 4 章 · 分词](./tokenization.md) |
| 可学习的绝对位置向量 | 超过 24 个字就没有位置可用 | [第 7 章 · 位置表示](./position-encoding.md) |
| 只有一千多字的语料 | 只能背诵，无法泛化 | [第 14 章 · 数据](./data-pipeline.md)、[第 18 章 · 正则化](./regularization.md) |
| 固定学习率、不裁剪梯度 | 模型一大，训练容易不稳 | [第 17 章 · 学习率](./learning-rate.md)、[第 20 章 · 梯度](./gradient-stability.md) |
| 全程 FP32 | 大模型显存和速度吃不消 | [第 19 章 · 精度](./precision.md) |
| 只看损失曲线 | 不知道问题出在哪里 | [第 22 章 · 诊断与评估](./training-evaluation.md) |
| 每生成一个字都把整段重算一遍 | 文本一长就很慢 | [第 28 章 · 推理效率](./inference-efficiency.md) |

<!-- real-model:start -->

## 在真实模型里

第 1 章那个不到 100 行的模型，在真实代码里分散在几个类中，但流水线完全一样。下表的链接都指向 Hugging Face transformers 的固定版本 `v5.21`，精确到行。读代码时可以先跳过缓存、掩码、并行这些工程细节，只看和本章对应的那几行。

| 本章的零件 | 真实代码 | 对照要点 |
| --- | --- | --- |
| 整个模型：嵌入 → N 个 Block → 归一化 → 输出层 | [`LlamaForCausalLM`](https://github.com/huggingface/transformers/blob/v5.21/src/transformers/models/llama/modeling_llama.py#L410-L480) | `self.model` 就是 `LlamaModel`，后面接 `lm_head`；传入 `labels` 时顺便算损失 |
| 主干的前向计算 | [`LlamaModel.forward`](https://github.com/huggingface/transformers/blob/v5.21/src/transformers/models/llama/modeling_llama.py#L356-L406) | 查表、逐层调用 Block、最后一次 RMSNorm；多出来的是缓存和注意力掩码的准备 |
| 逐个生成 token | [`GenerationMixin._sample`](https://github.com/huggingface/transformers/blob/v5.21/src/transformers/generation/utils.py#L3115-L3332) | 每一步取最后一个位置的 logits、按概率抽一个、接到末尾，和第 1 章的 `generate` 一样，只是多了停止条件和缓存 |
| 一步训练 | [`Trainer.training_step`](https://github.com/huggingface/transformers/blob/v5.21/src/transformers/trainer.py#L2023-L2100) | 前向算损失、反向求梯度；优化器的 `step()` 在外层训练循环里 |

想在本机看源码，可以先 `pip install transformers`，再用 `python -m inspect transformers.models.llama.modeling_llama:LlamaMLP` 这样的命令打印出任意一个类。

<!-- real-model:end -->

## 本章结论 {#tinyllm-choice}

一个语言模型的完整生命周期就是这条流水线：**文本 → 编号 → 模型 → 下一个字的分数 → 损失 → 梯度 → 更新参数**，训练好以后再用“预测一个字、接上去、再预测”的方式生成。后面所有章节都是在这条流水线的某一段上做文章。大模型和 AI 助手也没有离开这条流水线：大模型是同一个训练目标放大了规模，知识在训练结束时定格；Agent 不改模型，而是一轮轮地查资料、执行动作，把结果写回上下文，让同一个模型能回答新问题、完成多步任务。

::: warning 常见误区
- **损失降下来了，模型就学会了写诗。** 这一章只有 39 首诗，训练损失下降主要是在背这些诗；能不能写出没见过的诗，要看验证集上的损失（第 12 章起才有）。
- **模型一次输出一整句。** 模型每次只给下一个字打分，句子是“预测一个字、接到末尾、再预测”一步步拼出来的。
- **生成时模型还在学习。** 生成只做前向，参数不变；只有训练时的 backward 和优化器更新才改参数。
- **温度、采样是模型的一部分。** 它们在模型输出分数之后才起作用，换一种采样方式不用重新训练（第 27 章）。
:::

## 检查理解

1. 训练刚开始时损失约为 6.67，为什么说这是“正常”的？

   <details><summary>参考答案</summary>

   随机参数下模型对 556 个字的预测接近均匀分布，交叉熵约为 $\ln 556\approx6.32$。如果起点远高于这个数（比如几十），通常说明初始化或输出层有问题。

   </details>

2. 一段长度为 24 的样本 `x`，为什么能提供 24 道“猜下一个字”的练习？

   <details><summary>参考答案</summary>

   目标 `y` 是 `x` 后移一位，位置 $t$ 的目标是第 $t+1$ 个字。因果注意力让每个位置只能看到自己和前面的字，所以 24 个位置各自是一道独立的题。

   </details>

3. 训练损失 0.1、验证损失 8.1，说明了什么？要改善它，第一件该做的事是什么？

   <details><summary>参考答案</summary>

   模型记住了训练集，却没有学到能推广到新诗的规律（过拟合）。最直接的办法是增加数据量；其次才是正则化、减小模型、提前停止等手段。

   </details>

4. 在总图里找出 `self.head.weight = self.tok.weight` 这一行连接的两个零件。

   <details><summary>参考答案</summary>

   “词嵌入”和“输出层”。两者共用同一张 `[词表大小, d]` 的表，见第 5 章。

   </details>

5. 2017 年的 Transformer 和 GPT 在结构和训练数据上各有什么不同？为什么说这个改动让“规模”成了关键？

   <details><summary>参考答案</summary>

   Transformer 有编码器和解码器，用成对的“原文 → 译文”训练；GPT 只保留解码器，在普通文本上预测下一个 token。不再需要配对数据，任何文字都能拿来训练，于是语料、参数和算力可以一起放大，能力主要随规模增长。

   </details>

6. 一个大模型的训练语料截止到去年。今天你问它“昨天的比赛谁赢了”，为什么它可能给出一个读起来很像样、但完全错误的答案？Agent 怎样解决这个问题？

   <details><summary>参考答案</summary>

   模型的参数里没有昨天的信息，它只会按见过的规律接出最像“比赛结果”的文字，于是可能编造。Agent 先去搜索当天的新闻，把结果放进上下文，模型再根据这段资料往下写；模型本身没有改变。

   </details>

## 参考资料

- [Attention Is All You Need，Vaswani 等，2017](https://arxiv.org/abs/1706.03762)（Transformer）
- [Improving Language Understanding by Generative Pre-Training，Radford 等，2018](https://cdn.openai.com/research-covers/language-unsupervised/language_understanding_paper.pdf)（GPT-1）
- [Language Models are Unsupervised Multitask Learners，Radford 等，2019](https://cdn.openai.com/better-language-models/language_models_are_unsupervised_multitask_learners.pdf)（GPT-2）
- [Language Models are Few-Shot Learners，Brown 等，2020](https://arxiv.org/abs/2005.14165)（GPT-3）
- [Scaling Laws for Neural Language Models，Kaplan 等，2020](https://arxiv.org/abs/2001.08361)（缩放定律）
- [Training language models to follow instructions with human feedback，Ouyang 等，2022](https://arxiv.org/abs/2203.02155)（指令微调与人类反馈）
- [Kimi K3 技术报告，Kimi Team，2026](https://arxiv.org/abs/2607.24653) · [Kimi K3 模型卡](https://huggingface.co/moonshotai/Kimi-K3)
- [DeepSeek-V4 技术报告与模型卡，DeepSeek-AI，2026](https://huggingface.co/deepseek-ai/DeepSeek-V4-Pro)
- [Qwen3.5-397B-A17B 模型卡](https://huggingface.co/Qwen/Qwen3.5-397B-A17B) · [Qwen3.5-2B 模型卡](https://huggingface.co/Qwen/Qwen3.5-2B)（资料核对日期：2026-10-27）

下一章从最底层的工具开始：[第 2 章：张量与自动求导](./tensors-and-autograd.md)，回答 `loss.backward()` 到底做了什么。
