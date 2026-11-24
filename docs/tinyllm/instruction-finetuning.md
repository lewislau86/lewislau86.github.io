---
title: "第 38 章：指令微调"
description: "在预训练的基座上做监督微调（SFT）：对话模板怎样拼，为什么只在回答上算损失，<eos> 为什么必须学，推理时模板对不上会怎样；用程序判分看模型到底照没照做，以及 SFT 让原来的语言能力掉了多少。"
pageClass: tinyllm-course
---

# 第 38 章：指令微调

[课程总览](./index.md) · [上一章](./continued-pretraining.md) · [下一章](./lora-finetuning.md)

::: tip 本章学习目标
能说清预训练出来的基座为什么不会“照指令做事”，监督微调（SFT）又改变了什么；能写出一个对话模板，把“指令—回答”拼成训练样本，并只在回答（连同结束符）上算损失；能用程序判分的指令集评估模型照没照做，而不只看损失；能说清在全部 token 上算损失、训练时漏掉结束符、推理时模板对不上，各会出什么问题；知道 SFT 会让原来的语言建模能力掉一点，要一起看。

**前置：** [第 15 章](./language-model-loss.md)的交叉熵与掩码，[第 17 章](./learning-rate.md)的代理模型与 WSD，[第 27 章](./generation.md)的采样与停止条件，[第 4 章](./tokenization.md)的特殊 token。

**实践方式：** [instruction-finetuning.ipynb](/tinyllm/notebooks/instruction-finetuning)（也可以直接运行 <a href="/tinyllm/code/instruction-finetuning.py" download>instruction-finetuning.py</a>），CPU 约两分钟，需要 PyTorch 和 `tokenizers`。
:::

<TinyLLMMap active="instruction-finetuning" />

## 问题：基座只会续写

前面所有章节训练的都是**基座模型**（base model）：给它一段文字，它接着往下写。你对它说“写一首五言绝句，用‘春’字开头”，它不会把这当成要求，只会把这句话当成一段文本的开头，接着往下续。它从来没见过“有人提要求、另一个人照做”这种文本。

把基座变成“会照指令做事”的模型，第一步是**监督微调**（supervised fine-tuning，SFT），也叫指令微调：准备大量“指令—回答”对，按固定的格式拼起来，继续训练下一个 token 的预测，但只要求模型学会写回答。[FLAN](https://arxiv.org/abs/2109.01652)用 60 多个改写成指令的 NLP 数据集（分成 12 类任务）微调 137B 的模型，在没见过的任务上零样本效果大幅提高；[InstructGPT](https://arxiv.org/abs/2203.02155)把 SFT 当作 RLHF 的第一步（第 41 章）；[LIMA](https://arxiv.org/abs/2305.11206)发现 65B 的 LLaMA 只用 1000 条精选的指令—回答做 SFT，就能学会按要求的格式回答。

这一章在唐诗上把 SFT 完整做一遍。为了能用程序判断“照没照做”，指令只有两类要求：**体裁**（绝句四句、律诗八句）和**首字**（用某个字开头）。第八部分的后面几章（LoRA、蒸馏、RLHF、DPO、GRPO）都从这一章的基座和 SFT 出发。

::: info 本章代码从哪里来
本章所有代码都在一个文件里：<a href="/tinyllm/code/instruction-finetuning.py" download>instruction-finetuning.py</a>（[在 GitHub 上查看](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/tinyllm/code/instruction-finetuning.py)）。下面的代码块都是从这个文件里直接截取的片段，所以单独复制一段可能缺少 `import` 或前面定义的变量；想自己运行，请下载完整文件，`python instruction-finetuning.py` 从头跑到尾即可。notebook 版本也由同一个文件生成，可以[在线查看](/tinyllm/notebooks/instruction-finetuning)，或[在 Colab 中直接运行](https://colab.research.google.com/github/lewislau86/lewislau86.github.io/blob/master/docs/public/tinyllm/notebooks/instruction-finetuning.ipynb)。正文引用的输出来自 torch 2.14.1+cpu、tokenizers 0.23.3；以“[计时，本机]”开头的输出和机器有关，正文只引用它们的大致数值。
:::

## 1. 模型、数据和分词器

模型是第 17 章的代理模型：词表 1024、宽度 64、2 层、4 个头。上下文放到 128 个 token，一条“指令 + 律诗”放得下。第八部分每一章都要从头训一遍基座和 SFT，原尺寸太慢；损失和合格率的绝对值只在第八部分内部比较。

<<< @/public/tinyllm/code/instruction-finetuning.py#proxy

分词器多了两个特殊 token：`<user>` 和 `<assistant>`，用来标出“谁在说话”（第 4 章）。它们和 `<eos>` 一样，在分词器里是一个不可拆分的整体，普通文本永远不会被切成它们。

<<< @/public/tinyllm/code/instruction-finetuning.py#tokenizer

数据分三份，互不重叠：统一语料前 6000 首预训练基座，第 6001～12000 首里的训练集造 SFT 数据，同一段里的验证集、测试集造评估用的指令。

<<< @/public/tinyllm/code/instruction-finetuning.py#data

```text
预训练：5419 首 296,428 个 token；SFT 素材 5429 首；评估素材 571 首
```

## 2. 指令从哪里来，怎样判分

真实的 SFT 数据要么由人写，要么由更强的模型生成（第 40 章）。这里用一个省事的办法：**从诗反推指令**。一首诗是律诗，就配“写一首五言律诗”；六成的诗再加一句“用‘X’字开头”，X 就是这首诗的第一个字。这样每条回答都一定满足它的指令。

判分完全交给程序，不靠人看：每句是不是五个字、标点对不对，句数和体裁是否一致，有首字要求时第一个字对不对，回答有没有以 `<eos>` 结束。四项都满足才算“全部照做”。

<<< @/public/tinyllm/code/instruction-finetuning.py#instructions

## 3. 对话模板与损失掩码

![SFT 样本的模板与损失掩码：一条样本由 user、指令、assistant、回答和 eos 拼成，前三段不算损失，回答和 eos 算损失；推理时拼到 assistant 为止，模型从那里开始生成](/tinyllm/figures/sft-template.svg)

怎么读这张图：上面一行是一条训练样本，灰线上方的格子不算损失，橙线上方的格子算损失；下面一行是推理时交给模型的提示。

模板就是一个固定的拼法：`<user>指令<assistant>回答<eos>`。`encode_chat` 同时返回一个掩码，指令部分是 0，回答和 `<eos>` 是 1。只给指令时，它拼到 `<assistant>` 为止，这就是推理时的提示：

<<< @/public/tinyllm/code/instruction-finetuning.py#chat-template

打印一条样本看看：

<<< @/public/tinyllm/code/instruction-finetuning.py#show-example

```text
共 87 个 token，其中 63 个算损失
不算损失： <user>写一首五言律诗，用“愁”字开头。<assistant>
算损失：   愁人待晓鸡，秋雨暗凄凄。度烛萤时灭，传书鴈渐低。客来知计误，梦里泣津迷。无以逃悲思，寒螀处处啼。<eos>
```

为什么指令部分不算损失？指令是用户给的，模型不需要学会“写指令”，只需要学会在看到指令之后写回答。算上它，一部分梯度就花在预测这些高度重复的模板句子上了。`<eos>` 一定要算：模型必须学会“写完了就停”，否则推理时它会一直往下写。第 6 节分别验证这两点。

## 4. 预训练基座

基座用第 17 章的 WSD 训 2000 步，每步 8 行、每行 128 个 token。

<<< @/public/tinyllm/code/instruction-finetuning.py#pretrain

```text
[计时，本机] 预训练 2000 步 20.9 秒；预训练验证损失 4.305
```

把同样的模板交给基座：

<<< @/public/tinyllm/code/instruction-finetuning.py#generate

<<< @/public/tinyllm/code/instruction-finetuning.py#base-eval

```text
基座（未微调）          每句五字 0.00  句数对 0.00  首字对 0.00  按时停下 1.00  │ 全部照做 0.00
写一首五言律诗，用“池”字开头。 → 君应顾意，无令除思归。
写一首五言律诗。 → 欲谒堪步，翩阳印万重。
```

基座一条都不合格。它没见过 `<user>`、`<assistant>`，在 `<assistant>` 后面写了一两句不成形的诗就生成了 `<eos>`（预训练数据里每首诗后面都是 `<eos>`，所以“按时停下”是 1.00，但这只是因为它写得短）。

## 5. SFT：只在回答上算损失

从同一个基座复制一份，SFT 1500 步：每步随机取 16 条，右侧补 `<pad>`，只在掩码为 1 的位置算交叉熵；学习率 warmup 10 步到 3e-3，再线性降到 0。

<<< @/public/tinyllm/code/instruction-finetuning.py#sft

换 3 个种子（只决定抽样顺序，基座相同），种子 0 另在第 500、1000 步各存一份：

<<< @/public/tinyllm/code/instruction-finetuning.py#sft-run

```text
[计时，本机] 3 个种子各 SFT 1500 步，共 57.4 秒
SFT 种子 0         每句五字 0.92  句数对 0.91  首字对 0.39  按时停下 1.00  │ 全部照做 0.58
SFT 种子 1         每句五字 0.88  句数对 0.86  首字对 0.34  按时停下 1.00  │ 全部照做 0.52
SFT 种子 2         每句五字 0.81  句数对 0.80  首字对 0.45  按时停下 1.00  │ 全部照做 0.56
种子 0 第 500 步     每句五字 0.80  句数对 0.77  首字对 0.03  按时停下 1.00  │ 全部照做 0.36
种子 0 第 1000 步    每句五字 0.84  句数对 0.84  首字对 0.26  按时停下 1.00  │ 全部照做 0.50
预训练验证损失：基座 4.305  SFT 后 4.640 4.643 4.626
写一首五言律诗，用“池”字开头。 → 风飞空寂寞，高除思先生。兼歌遫石鞭，寒歌报匡寒。砌箫动明月，柔叶下寒溪。东观非流日，天晓见云楼。
写一首五言律诗。 → 欲谪寻龙树，诤印万物多。化亭东海远，尘外竹林寒。荷客已锡云，青云隔水秋。唯余天上山，应待雪中时。
写一首五言律诗，用“南”字开头。 → 南游九家子，遗讲不掩神。云满南方至，漾人复此生。断虽西北望，鹤随千里余。千轺一琴日，何曾讲世难。
```

![指令微调的结果：左图是基座、SFT、两个对照的各项合格率；中图是种子 0 随 SFT 步数的变化；右图是推理时换模板的影响](/tinyllm/figures/sft-results.svg)

怎么读这张图：左图每组柱子是一项指标，灰色是基座，蓝色是 SFT（3 个种子的平均，竖线是范围），橙色、红色是第 6 节的两个对照（红色的“没有 `<eos>`”只训了 500 步，它的每句五字低，部分是因为回答一直写到 80 个 token 的上限）；中图横轴是 SFT 步数；右图对应第 7 节。

三点：

- **格式和体裁学得很快。** 每句五字、句数对在 0.80～0.92 之间，第 500 步就到了 0.77。“律诗八句、绝句四句”只需要把指令里的一个词和回答的长度对应起来，SFT 很快就学会了。
- **首字学得慢，也学得不全。** 第 500 步只有 0.03，第 1000 步 0.26，第 1500 步 0.34～0.45（500、1000 步是同一次 1500 步训练中途的快照，那时学习率还没降下来，所以这条曲线混着“步数”和“学习率衰减”两个因素）。用某个字开头，要求模型在第一个位置把指令里的那个字“抄”过来，这需要注意力专门去找指令里引号中的字。一个可能的解释是：基座在预训练时很少需要“抄”，这个能力要训到一定步数才冒出来。大模型在预训练里见过海量的重复和引用，这种能力早就有了，所以 SFT 对它们来说主要是学格式（LIMA 的结论）；小模型得在 SFT 里现学。
- **代价是原来的语言能力掉了一点。** 预训练验证集上的损失从 4.305 升到 4.63～4.64。SFT 的数据全是指令格式，模型的分布往这边偏了（第 37 章的遗忘）。真实的 SFT 数据量大得多、种类多得多，通常还会混入一部分预训练数据。

## 6. 两个对照：全部 token 都算损失；训练时没有 `<eos>`

第一个对照和种子 0 的设置完全相同，只是指令部分也算损失。第二个对照把每条回答末尾的 `<eos>` 去掉，只为看“停不停得下来”，训 500 步。

<<< @/public/tinyllm/code/instruction-finetuning.py#ablations

```text
[计时，本机] 两个对照（1500 步、500 步）共 26.5 秒
只算回答（种子 0）       每句五字 0.92  句数对 0.91  首字对 0.39  按时停下 1.00  │ 全部照做 0.58
全部 token 都算      每句五字 0.92  句数对 0.91  首字对 0.24  按时停下 1.00  │ 全部照做 0.53
训练时没有 <eos>      每句五字 0.05  句数对 0.02  首字对 0.08  按时停下 0.02  │ 全部照做 0.02
预训练验证损失：只算回答 4.640  全部 token 4.928
没有 <eos> 的模型： 山亭上山步，山川白露重。长安真化出，征夫晓樵多。繁愁已不死，闲且自能年。离离明月月，春来荡陋改。何年留代烛，犹怜八月明。 …
```

- **全部 token 都算：格式一样，首字和语言能力都差一些。** 首字对从 0.39 降到 0.24，预训练验证损失从 4.640 升到 4.928。两个可能的解释：一是指令只有寥寥几种说法，模型很容易把它们背下来，可这部分梯度把参数往“写指令”的方向推，离原来的诗更远了；二是损失按算损失的 token 数平均，指令 token 也算进来以后，回答 token 在每一步梯度里的份量变小了。一个种子分不清是哪一个，按回答 token 数归一化再做一次对照才能分开。这只是一个种子的结果；也有研究发现，指令很长、回答很短、数据很少时，在指令上也算损失反而有帮助（[Shi 等，2024](https://arxiv.org/abs/2405.14394)），所以这不是铁律，要按数据来定。
- **没有 `<eos>`：模型停不下来。** 只有 2% 的回答按时停下，其余一直写到 80 个 token 的上限，律诗写完了还接着写第九句、第十句。格式判分因此几乎全不合格。推理时停止全靠模型生成 `<eos>`（第 27 章），这一个 token 必须在训练数据里，而且必须算损失。

## 7. 推理时模板对不上

训练时的模板是 `<user>指令<assistant>`。推理时如果少了 `<assistant>`，或者把指令换成训练时没见过的说法（“请作一首……，以‘X’字开头”），会怎样？

<<< @/public/tinyllm/code/instruction-finetuning.py#template-mismatch

```text
训练时的模板           每句五字 0.92  句数对 0.91  首字对 0.39  按时停下 1.00  │ 全部照做 0.58
少了 <assistant>   每句五字 0.91  句数对 0.88  首字对 0.00  按时停下 1.00  │ 全部照做 0.38
换一种说法            每句五字 0.94  句数对 0.91  首字对 0.21  按时停下 1.00  │ 全部照做 0.50
```

两种情况下，格式和句数都几乎不受影响，首字却明显下降：少了 `<assistant>` 时首字对是 0。每句五字仍有 0.91，说明模型还是马上就开始作诗，只是不再去指令里抄那个字。“第一个字去指令里找”这个行为，是和 `<assistant>` 这个位置绑在一起学会的；少了它，模型照样能写诗，抄字却不会了。换一种说法时，引号里的字还在，但前后的词变了，“抄字”的那套注意力只找回了一半。

真实模型的模板比这复杂得多（系统提示、多轮对话、工具调用，第 44 章），而且每个模型都不一样。推理时必须用和训练时**一字不差**的模板，所以模板现在和分词器保存在一起，推理框架直接读取（见下面“在真实模型里”）。

## 动手实验

1. **更多首字数据。** 把 `make_instruction` 里要求首字的比例从六成改成十成。首字对会更早出现吗？体裁会不会变差？
2. **混入预训练数据。** 在 `sft` 的每个 batch 里，混入四分之一普通的诗（整行都算损失）。预训练验证损失还会升到 4.6 吗？首字对有没有代价？
3. **多种说法。** 造指令时随机用两三种说法（“写一首”“请作一首”“来一首”）。训练后，第 7 节“换一种说法”的首字对能恢复吗？
4. **新的指令类型。** 加一类指令“第一句是‘……’”，要求回答原样以这五个字开头。小模型能学会抄五个字吗？

<!-- real-model:start -->

## 在真实模型里

真实模型的对话模板写在分词器里（一段 Jinja 模板），SFT 一般用 TRL 的 `SFTTrainer`；本章的模板、掩码和补齐在那里都有对应。下表的链接都指向 Hugging Face transformers 的固定版本 `v5.21`、trl 的固定版本 `v1.18.2`，精确到行。读代码时可以先跳过缓存、掩码、并行这些工程细节，只看和本章对应的那几行。

| 本章的零件 | 真实代码 | 对照要点 |
| --- | --- | --- |
| 对话模板 | [`PreTrainedTokenizerBase.apply_chat_template`](https://github.com/huggingface/transformers/blob/v5.21/src/transformers/tokenization_utils_base.py#L3021-L3237) | 按模型自带的模板把 `messages` 拼成文本再分词；`add_generation_prompt=True` 在末尾补上助手回合的开头（相当于本章的 `<assistant>`），`return_assistant_tokens_mask=True` 返回哪些 token 属于助手的回答，就是本章的 loss 掩码 |
| 只在回答上算损失 | [`SFTConfig`](https://github.com/huggingface/trl/blob/v1.18.2/trl/trainer/sft_config.py#L23-L343) | `completion_only_loss` 默认按数据格式决定：“提示—回答”格式的数据只在回答上算；对话数据要打开 `assistant_only_loss`，只在助手说的话上算 |
| 补齐与标签 | [`DataCollatorForLanguageModeling.torch_call`](https://github.com/huggingface/trl/blob/v1.18.2/trl/trainer/sft_trainer.py#L170-L229) | 右侧补 pad，标签里补齐的位置和不算损失的位置都是 -100（交叉熵忽略这些位置），等价于本章的掩码；`padding_free=True` 时把一个 batch 首尾相接成一行，用 position_ids 分开（第 14 章的打包） |

想在本机看源码，可以先 `pip install transformers trl`，再用 `python -m inspect trl.trainer.sft_config:SFTConfig` 这样的命令打印出任意一个类。

<!-- real-model:end -->

## 本章结论：TinyLLM 的选择 {#tinyllm-choice}

TinyLLM 的 SFT 用<strong>本章的选择</strong>：对话模板固定为 `<user>指令<assistant>回答<eos>`，`<user>`、`<assistant>` 是分词器里的特殊 token；只在回答和 `<eos>` 上算损失；从预训练基座复制一份，学习率 warmup 后从 3e-3 线性降到 0，训练 1500 步；推理时用同一个模板拼到 `<assistant>` 为止，生成到 `<eos>` 停下；评估用程序判分的指令集，同时看预训练验证损失。后面几章都从这个 SFT 模型出发。

为什么：在第 17 章的代理模型上，基座对指令一条都不合格；SFT 后（3 个种子）每句五字、句数对约 0.8～0.9，首字对 0.34～0.45，全部照做 0.52～0.58。只在回答上算损失比全部 token 都算的首字对高（0.39 对 0.24，一个种子），预训练验证损失也低得多（4.640 对 4.928）。训练时去掉 `<eos>`，98% 的回答停不下来。推理时少了 `<assistant>`，首字对降到 0。

实验边界：模型只有 2 层、宽 64，学不会更难的指令（写这一章时试过要求“诗里要有某个字”“第一句是某五个字”，同样的训练量下几乎学不会，这两组没有放进脚本），首字这种需要“抄”的能力也要训到 1000 步以上才出现；指令只有两种说法、两类要求，远不如真实的 SFT 数据多样；评估只有 64 条指令（首字只在其中要求了首字的 38 条上算），相差几个百分点不能当真；全部 token 的对照和去掉 `<eos>` 的对照只跑了一个种子；SFT 让预训练验证损失升了约 0.33，这里没有试混入预训练数据。什么情况下要换：模型大、预训练充分时，SFT 的步数和数据可以少得多（LIMA 用了 1000 条）；指令很长而回答很短、数据很少时，可以试在指令上也算损失；显存不够做全参数微调时，见第 39 章的 LoRA。

::: warning 常见误区
- **基座看到指令就会照做。** 它只会续写；指令和回答之间的对应关系，要靠 SFT 教给它。
- **指令也该算损失，数据利用得更充分。** 在本章的设定下（一个种子），这让首字对和原来的语言能力都变差了；要不要算，取决于指令和回答的长短与数据量。
- **`<eos>` 可有可无，推理时设个长度上限就行。** 模型不知道什么时候该停，会一直写下去；长度上限只能截断，不能让它在该停的地方停。
- **模板差一点没关系。** 本章少了 `<assistant>`，首字对就从 0.39 掉到 0；推理时必须用训练时的模板。
- **SFT 后只看合格率。** 还要看原来的能力掉了多少；本章 SFT 后预训练验证损失升了 0.33。
- **只看训练损失判断 SFT 好不好。** 损失只说明模型更像训练数据了，不说明每条指令都照做了：第 500 步每句五字已有 0.80，首字对却只有 0.03；照没照做要用任务本身来评。
:::

## 检查理解

1. 一条样本 87 个 token，只有 63 个算损失。如果把 batch 里所有样本的损失按 token 平均，指令很长的样本和指令很短的样本，谁对梯度的贡献更大？

   <details><summary>参考答案</summary>

   按 token 平均时，每个算损失的 token 权重相同，所以回答长的样本贡献大，指令长短本身不影响（指令部分不算损失）。本章的律诗回答比绝句长一倍，律诗样本的梯度权重也大约是绝句的两倍。如果希望每条样本权重相同，要先在每条样本内平均，再在样本之间平均。

   </details>

2. 为什么基座的“按时停下”是 1.00，却一条都不合格？这说明评估时要注意什么？

   <details><summary>参考答案</summary>

   基座在 `<assistant>` 后面写了一两句就生成了 `<eos>`：预训练数据里每首诗都以 `<eos>` 结尾，它很容易在短短几个字后就“以为一首诗结束了”。所以“停下”这一项单看是满分，其实是写得太短。单项指标可能有误导，要和其他指标一起看，最好再看几个样例。

   </details>

3. 推理时少了 `<assistant>`，为什么句数几乎不变，首字却掉到 0？

   <details><summary>参考答案</summary>

   句数由指令里的“绝句”“律诗”决定，模型在整首诗的生成过程中一直能看到这个词，起点挪了一个位置也不影响。首字是在紧跟 `<assistant>` 的那个位置学会的：模型在那里去指令里找引号中的字抄过来。少了 `<assistant>`，第一个生成位置的上下文变了。每句五字还有 0.91，说明模型并没有多写什么，而是直接开始作诗；只是这个位置不再触发“抄字”，第一个字就随便写了。

   </details>

4. 你要给一个已有的开源对话模型做 SFT，数据是自己写的“问题—回答”。按本章的结论，最容易出错的三个地方是什么？

   <details><summary>参考答案</summary>

   一是模板：必须用这个模型自带的对话模板（分词器里的 chat template）拼数据，推理时也用同一个；二是掩码：只在助手的回答上算损失，用户的话和系统提示不算；三是结束符：每条回答后面要有模型自己的结束 token，而且要算损失。此外要留一份原来能力的评测，看 SFT 有没有把它训坏。

   </details>

## 参考资料

- [Finetuned Language Models Are Zero-Shot Learners（FLAN），Wei 等，2021](https://arxiv.org/abs/2109.01652)
- [Training language models to follow instructions with human feedback（InstructGPT），Ouyang 等，2022](https://arxiv.org/abs/2203.02155)
- [LIMA: Less Is More for Alignment，Zhou 等，2023](https://arxiv.org/abs/2305.11206)
- [Instruction Tuning With Loss Over Instructions，Shi 等，2024](https://arxiv.org/abs/2405.14394)
- [transformers 文档：Chat templates](https://github.com/huggingface/transformers/blob/v5.21/docs/source/en/chat_templating.md) · [TRL 文档：SFT Trainer](https://github.com/huggingface/trl/blob/v1.18.2/docs/source/sft_trainer.md)

这一章做的是全参数微调：模型的每个参数都在动，优化器为每个参数存两份动量。下一章看另一种做法：冻住原模型，只训练一小组低秩的增量。[第 39 章：参数高效微调（LoRA）](./lora-finetuning.md)。
