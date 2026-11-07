---
title: "第 15 章：语言模型目标函数"
description: "拆开第 12 章的验证损失 5.579：错位出题、整首诗的概率与下溢、log-softmax 的数值稳定、nats/比特/困惑度的换算、padding 与梯度累积的分母、<eos> 的监督、按题型拆损失、校准，以及 label smoothing 与 z-loss。"
pageClass: tinyllm-course
---

# 第 15 章：语言模型目标函数

[课程总览](./index.md) · [上一章](./data-pipeline.md) · [下一章](./optimizers.md)

::: tip 本章学习目标
能从“整首诗的概率”推出每 token 的交叉熵，说清为什么要在对数域里算、为什么不能先 softmax 再取对数；能把同一个损失换算成比特/token、比特/字和困惑度，并知道哪种可以跨分词器比较；能写对 padding 和梯度累积时的分母，判断哪些位置该算损失；会把平均损失按题型拆开，用可靠性图检查模型给的概率可不可信。

**前置：** [第 5 章](./embeddings-and-output.md)的 logits 与交叉熵，[第 12 章](./tinyllm-model.md)的基线与评估口径；[第 14 章](./data-pipeline.md)的逐首补齐与拼接成流。

**实践方式：** [language-model-loss.ipynb](/tinyllm/notebooks/language-model-loss)（也可以直接运行 <a href="/tinyllm/code/language-model-loss.py" download>language-model-loss.py</a>），CPU 约两分钟，需要 PyTorch 和 `tokenizers`。
:::

<TinyLLMMap active="language-model-loss" />

## 问题：5.579 到底是什么

[第 12 章](./tinyllm-model.md)训练完基线，打印了一行：`step 300  验证损失 5.579  (7.68 比特/字)`。后面每一章都拿自己的结果和这个数比。可它本身是什么意思？5.579 算好还是算差？它是怎么从模型的输出算出来的？如果算的时候分母放错了、该算的位置漏了，这个数会偏到哪里去？

[第 5 章](./embeddings-and-output.md)用一个六个词的玩具例子讲过 logits、交叉熵和它的梯度，并且说过“这个训练目标在第 15 章进一步展开”。本章就来展开。做法是把第 12 章的基线原样训练出来，再把 5.579 一层层拆开：它从哪些题目来，每道题怎么算，平均时的分母是什么，平均数又掩盖了什么。

::: info 本章代码从哪里来
本章所有代码都在一个文件里：<a href="/tinyllm/code/language-model-loss.py" download>language-model-loss.py</a>（[在 GitHub 上查看](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/tinyllm/code/language-model-loss.py)）。下面的代码块都是从这个文件里直接截取的片段，所以单独复制一段可能缺少 `import` 或前面定义的变量；想自己运行，请下载完整文件，`python language-model-loss.py` 从头跑到尾即可。notebook 版本也由同一个文件生成，可以[在线查看](/tinyllm/notebooks/language-model-loss)，或[在 Colab 中直接运行](https://colab.research.google.com/github/lewislau86/lewislau86.github.io/blob/master/docs/public/tinyllm/notebooks/language-model-loss.ipynb)。正文引用的输出来自 torch 2.14.1+cpu、tokenizers 0.23.3。
:::

脚本开头把第 12 章的配置、数据、分词器、模型、评估口径和训练循环一字不改地复制过来（这里不再展示，见[第 12 章](./tinyllm-model.md)）。随机种子和 batch 计划都相同，所以训练日志也和第 12 章逐位相同：

```text
step   0  验证损失 8.750  (12.05 比特/字)
step 300  验证损失 5.579  (7.68 比特/字)
```

下面就从这个训练好的模型出发。

## 1. 错位：一段 65 个 token，出 64 道题

语言模型的训练目标只有一句话：**看前面，猜下一个**。训练时从 token 流里切一段，输入是前 64 个，目标是往后错一位的 64 个。看第一首验证诗的开头：

<<< @/public/tinyllm/code/language-model-loss.py#shift

```text
输入 x： 久 为 簪 � � 累 ， 幸
目标 y： 为 簪 � � 累 ， 幸 此
```

上下两行对齐着读：看见“久”，要猜“为”；看见“久为”，要猜“簪”；依此类推。两个 `�` 是“组”字被字节级 BPE 拆成的两个字节 token（[第 4 章](./tokenization.md)），单独解码出来不是完整的字。

这 8 个位置是 8 道题，一段 64 个 token 的窗口就是 64 道题。它们在一次前向计算里同时算完：因果掩码（[第 6 章](./self-attention.md)）保证第 $t$ 个位置只看得到前 $t$ 个 token，看不到自己要猜的答案。训练时每道题的“前文”都是真实文本，而不是模型自己前一步猜的结果，这种做法叫 **teacher forcing**。生成时（[第 26 章](./generation.md)）就没有这个待遇了，模型只能接着自己写出来的字往下猜。

## 2. 从“整首诗的概率”到“每 token 的平均损失”

先换个角度看这 64 道题。一个语言模型其实是在给**整段文本**打一个概率。按概率的链式法则，一首诗的概率可以拆成每一步“猜中下一个 token”的条件概率连乘：

$$
p(x_1, x_2, \dots, x_n) = p(x_1)\, p(x_2 \mid x_1)\, p(x_3 \mid x_1, x_2) \cdots p(x_n \mid x_1, \dots, x_{n-1})
$$

右边每一项，正是模型在一个位置上给正确答案的概率。拿第一首验证诗，从 `<eos>`（上一首刚结束）开始逐个 token 算一遍。生僻字被拆成了几个 token，这里按字合并：一个字的概率是它几个 token 概率的乘积，取负对数后就是几个 token 的损失相加。

<<< @/public/tinyllm/code/language-model-loss.py#poem-prob

```text
久为簪组累，幸此南夷谪。闲依农圃邻，偶似山林客。晓耕翻露草，夜榜响溪石。来往不逢人，长歌楚天碧。
久 5.99  为 5.21  簪 8.26  组* 9.33  累 8.38  ， 0.00  幸 8.90  此 5.09  南 7.30  夷 8.95  谪 10.45  。 0.00  闲 6.14
46 个字（含 <eos>），48 个 token；带 * 的字被拆成了几个 token
```

每个数是 $-\ln p$，单位叫 **nats**（以 $e$ 为底的对数）。$-\ln p = 5.99$ 对应 $p = e^{-5.99} \approx 0.0025$：模型觉得诗的第一个字是“久”的可能性只有千分之二点五。逗号、句号几乎是 0，模型对“五个字后面跟一个标点”非常有把握。

![第一首验证诗逐字的损失：逗号、句号和结束符几乎是 0，字都在 4 到 12 之间，句首的字普遍更高；全诗合计 270.5 nats，48 个 token 平均每个 5.64](/tinyllm/figures/lm-loss-poem.svg)

怎么读这张图：每根柱子是一个字的 $-\ln p$，柱子越高，模型越没料到这个字。橙色是每句的第一个字，蓝色是句中的字，青色的标点矮到只剩一条线。全诗 48 个 token 的损失加起来是 270.5 nats。

整首诗的概率就是这 48 个概率连乘。先猜一下：用 float32 乘出来是多少？

<<< @/public/tinyllm/code/language-model-loss.py#underflow

```text
float32 连乘： 0.0
float64 连乘： 3.184940721417237e-118
对数相加：     -270.546630859375 （以 e 为底）
每 token 平均： 5.636388301849365
```

float32 能表示的最小正数约为 $10^{-45}$，整首诗的概率是 $10^{-118}$，乘到一半就变成了 0（**下溢**）。float64 勉强撑住了，但再长几首诗也会归零。取对数以后，连乘变成连加，$-270.5$ 是个再普通不过的数。这是语言模型总在**对数域**里算概率的第一个原因。

最后一行就是这首诗的“损失”：把整首诗的负对数概率除以 token 数，得到每 token 的平均。第 12 章的验证损失，就是把整个验证集当成一段长文本，做同样的事。

## 3. 交叉熵内部：log-softmax，再取正确答案那一项

模型输出的是 logits $z$，不是概率。正确答案 $y$ 的损失是：

$$
\ell = -\ln \operatorname{softmax}(z)_y = -\ln \frac{e^{z_y}}{\sum_j e^{z_j}} = \underbrace{\ln \sum_j e^{z_j}}_{\text{log-sum-exp}} - z_y
$$

照中间那个式子写代码，先 softmax 再取对数，看起来没问题。拿三个候选、logits 很大的情况试一试：

<<< @/public/tinyllm/code/language-model-loss.py#naive-softmax

```text
先 softmax 再取 log： nan
log-sum-exp 写法：    0.0
F.cross_entropy：      0.0
```

$e^{1000}$ 超出了 float32 的范围，变成 `inf`，`inf / inf` 得到 `nan`。正确答案的 logit 比别的高出 1000，模型几乎百分之百确定，损失应该是 0，朴素写法却算出了 `nan`。

最右边那种写法不会溢出：算 log-sum-exp 时先减去最大的 logit，$\ln \sum_j e^{z_j} = m + \ln \sum_j e^{z_j - m}$，其中 $m = \max_j z_j$，指数里最大的数是 0。PyTorch 的 `torch.logsumexp` 和 `F.cross_entropy` 内部都是这样算的。这是在对数域里算的第二个原因，也是[第 5 章](./embeddings-and-output.md)说“`cross_entropy` 要的是原始 logits”的原因：它要自己做这一步。

照最右边的式子，在整个验证集上手算一遍，和第 12 章的 `evaluate` 对一对：

<<< @/public/tinyllm/code/language-model-loss.py#manual-ce

```text
手算：     5.579025745391846
evaluate： 5.57902518866574
一共 12224 道题，总损失 68198.0 nats
```

两者在第七位小数上才有差别（求和顺序不同带来的浮点误差）。现在可以给 5.579 一个完整的定义：**验证集被切成 191 个 64-token 的窗口，共 12,224 道“猜下一个 token”的题；每道题的 $-\ln p(\text{正确答案})$ 加起来是 68,198 nats，除以 12,224 就是 5.579。**（验证流一共 12,256 个 token，末尾凑不满一个窗口的 32 个没有算进去。）

梯度也很简单。对 logits 求导，结果是“softmax 概率减去正确答案的独热向量”，再除以题数：

$$
\frac{\partial \ell}{\partial z_j} = \operatorname{softmax}(z)_j - [j = y]
$$

用 autograd 核对两道题：

<<< @/public/tinyllm/code/language-model-loss.py#grad-check

```text
autograd 与公式的最大差： 1.3969838619232178e-09
正确答案那一格的梯度： -0.49950629472732544   其余 4095 格加起来： 0.49950656294822693
```

正确答案那一格的梯度是负的，梯度下降会把它的 logit 往上推；其余 4095 格的梯度都是正的，按各自的概率分摊，加起来正好和正确答案那一格抵消。正确答案的概率只有千分之一左右，所以它的梯度接近 $-1$（这里除以了 2 道题，所以是 $-0.4995$）。模型猜得越准，这个梯度越接近 0，推力也就越小。

## 4. 同一个数的几种读法

5.579 nats/token 不太直观。它还有几种常见的读法：

<<< @/public/tinyllm/code/language-model-loss.py#units

```text
每 token  5.579 nats   = 8.05 比特
每字      5.324 nats   = 7.68 比特（每字 0.954 个 token）
困惑度    e^5.579 = 265（每个 token）；每字 2^7.68 = 205
均匀乱猜  ln 4096 = 8.318 nats，困惑度 4096
正确答案的平均概率 0.181，几何平均 0.0038
```

![一个数四种读法：5.579 nats/token 除以 ln2 是 8.05 比特/token；取 e 的指数是困惑度 265；乘以每字 0.954 个 token 再除以 ln2 是 7.68 比特/字；对照均匀乱猜 4096 个 token 是 8.318 nats](/tinyllm/figures/lm-loss-units.svg)

- **比特。** 把自然对数换成以 2 为底，除以 $\ln 2$。8.05 比特/token 的意思是：如果用这个模型做压缩，平均每个 token 要 8.05 个二进制位。
- **困惑度（perplexity）。** $e^{5.579} \approx 265$。直观地说，模型每一步的为难程度，相当于在 265 个候选里均匀地乱猜。均匀乱猜 4096 个 token 的困惑度是 4096，完美预测是 1。
- **比特/字。** 第 12 章报的就是它：每 token 的损失乘以“每个字平均几个 token”，再换成比特。词表变了，每 token 损失不能直接比，比特/字可以（第 12 章的常见误区讲过）。

最后一行值得多看一眼：正确答案的**算术平均**概率是 0.181，**几何平均**却只有 0.0038，差了将近 50 倍。困惑度对应的是几何平均（$e^{-5.579} = 0.0038$，倒数就是 265）。几何平均对“猜得极差”的题很敏感：只要有一道题给正确答案 $10^{-6}$ 的概率，就会把平均损失拉高一截。算术平均 0.181 主要来自那些几乎必中的标点。这是平均数掩盖细节的第一个例子，第 7 节再细看。

## 5. 平均的分母

5.579 是“总损失 ÷ 题数”。总损失好算，**题数**却不是每次都那么明白。第 12 章把诗拼成流，每个位置都是真题。改成逐首补齐（[第 14 章](./data-pipeline.md)）时，batch 里就会有 `<pad>`。取 4 首绝句、4 首律诗（都是验证诗，长短交替排列），补齐成一个 batch，用三种方式求平均：

<<< @/public/tinyllm/code/language-model-loss.py#padding

```text
每首的 token 数： [24, 48, 27, 45, 26, 48, 22, 48]   <pad> 占 25%
① 只算真题、按 token 平均（ignore_index）：5.502
② <pad> 也当题目算进去：                 8.029
③ 先每首平均，再 8 首平均：              5.498
```

- **① 是对的。** 把 `<pad>` 位置的目标设成 -100，`F.cross_entropy` 默认的 `ignore_index=-100` 会跳过它们，分子分母都不算。
- **② 把补齐位置也当成了题目。** 这里的模型从没在 `<pad>` 上训练过，猜不中，所以损失被拉高到 8.029。如果训练时一直这样算，情况会反过来：模型很快学会“`<eos>` 之后全是 `<pad>`”，这些送分题的损失接近 0，报出来的平均损失会**偏低**，大约是真值乘以真题的比例（这里是 75%）。同时还有四分之一的梯度花在学“补齐”上。
- **③ 改变的是权重。** 先每首平均再平均，每首诗的权重一样，一首 22 个 token 的绝句里每道题的权重，是一首 48 个 token 的律诗里每道题的两倍多。这里绝句和律诗的平均损失恰好差不多，所以 ③ 和 ① 很接近；但两种平均回答的是不同的问题：①问“平均每个 token 猜得怎样”，③问“平均每首诗猜得怎样”。后半本书一律用 ①。

分母最容易放错的地方是**梯度累积**（[第 13 章](./gpu-training.md)用过）：显存放不下一个大 batch，就拆成几个 micro-batch 依次算，梯度累加起来再更新。常见的写法是每个 micro-batch 照常算平均损失、除以 micro-batch 的个数、再 `backward()`。这和一次算完整个 batch 一样吗？把这 8 首拆成 4 个 micro-batch 试试：

<<< @/public/tinyllm/code/language-model-loss.py#accumulation

```text
原顺序：每个 micro-batch 的真题数 [72, 72, 74, 70]，每道题的权重是一起算时的 [1.0, 1.0, 0.97, 1.03] 倍
  各自平均再平均   与一起算的梯度：余弦 0.9998，范数之比 1.002
  各自求和再除总数 与一起算的梯度：最大差 1.2e-08
按长度排序后再分：每个 micro-batch 的真题数 [46, 53, 93, 96]，每道题的权重是一起算时的 [1.57, 1.36, 0.77, 0.75] 倍
  各自平均再平均   与一起算的梯度：余弦 0.9389，范数之比 1.078
  各自求和再除总数 与一起算的梯度：最大差 1.0e-08
```

![梯度累积时分母放在哪：8 首诗按长度排序后分成 4 个 micro-batch，真题数 46、53、93、96；各自平均再除以 4 时，短诗组每道题的权重放大到 1.57 倍、长诗组缩到 0.75 倍，梯度方向的余弦相似度只有 0.939；各自求和、最后除以总题数 288，结果和一起算完全相同](/tinyllm/figures/lm-loss-denominator.svg)

怎么读这组结果：

- **长短交替时，几乎没有差别。** 每个 micro-batch 都是一首绝句加一首律诗，真题数差不多，每道题的权重都接近 1，梯度和一起算几乎一样。
- **按长度分组时，差别出来了。** 这正是[第 14 章](./data-pipeline.md)说的“按长度分桶”会造成的局面：短诗都在前两个 micro-batch，每道题的权重被放大到 1.57 倍和 1.36 倍，长诗的题被缩小到 0.75 倍。梯度方向偏了（余弦 0.939），大小也变了。
- **正确的做法**是每个 micro-batch 只求和（`reduction="sum"`），最后除以整个累积批次的真题总数。这样结果和一次算完相同，差别只剩浮点误差。

这不是纸上谈兵。2024 年 10 月，有人发现 transformers 的 Trainer 在梯度累积时用的正是“各自平均再平均”，样本长短差别大时，累积 4 步和直接用 4 倍 batch 训练出来的损失曲线明显不同；修复办法就是上面的“先求和、最后除以总题数”（[Hugging Face，2024](https://huggingface.co/blog/gradient_accumulation)）。多卡数据并行时也是同一个问题：每张卡的题数不同，就不能简单地把各卡的平均损失再平均。

## 6. 哪些位置该算：`<eos>` 一定要算

![错位出题与损失掩码：输入 x 是窗口的前 64 个 token、目标 y 往后错一位；指令微调样本里提问和补齐标为 -100 不算，回答和 eos 算](/tinyllm/figures/lm-targets-mask.svg)

怎么读这张图：上半是第 1 节的错位，换成一句熟悉的诗来画：每一列是一道题，看上面一行的前若干个字，猜下面那个字。下半是同一条规则在指令微调数据上的样子：哪些位置的目标标成 -100，哪些算进损失。预训练的拼接流里所有位置都算，`<eos>` 在两种情况下都要算，原因见下文。

第 12 章把每首诗后面接一个 `<eos>`，它也是一道题：读完一首诗，猜“该结束了”。验证集里有多少这样的题，模型猜得怎样？

<<< @/public/tinyllm/code/language-model-loss.py#eos

```text
<eos> 题目 290 道，平均损失 0.507
句号之后：真结束时给 <eos> 的平均概率 0.687，没结束时 0.231
```

290 道 `<eos>` 题的平均损失只有 0.507，比字容易得多：它只会出现在句号之后。难的是“这个句号之后结不结束”：绝句写完 4 句可以结束，也可能接着写成 8 句的律诗。模型在真该结束的地方平均给出 0.687 的概率，在不该结束的句号后面也给了 0.231。

如果把 `<eos>` 当成补齐一样用 -100 屏蔽掉，模型就从来没有被要求预测“结束”，生成时就不会自己停下来，只能靠最大长度截断（[第 26 章](./generation.md)的停止条件）。所以 `<eos>` 必须算在损失里。

反过来，有些位置**不该**算。[第 34 章](./instruction-finetuning.md)的指令微调里，一条样本是“用户的问题 + 助手的回答”，通常只在回答部分算损失，把问题部分的目标设成 -100：模型要学的是怎么回答，而不是怎么提问。机制和 padding 完全一样，只是被屏蔽的位置换了。

## 7. 平均数掩盖了什么

回到验证集的 12,224 道题。它们难度差别很大，按目标分成四类：标点（逗号、句号）、`<eos>`、每句的第一个字（前一个 token 是标点或 `<eos>`）、句中的字。

<<< @/public/tinyllm/code/language-model-loss.py#breakdown

```text
标点     占题目 17.1%   平均损失 0.089   占总损失  0.3%
<eos>  占题目  2.4%   平均损失 0.507   占总损失  0.2%
句首的字   占题目 17.1%   平均损失 7.587   占总损失 23.2%
句中的字   占题目 63.5%   平均损失 6.704   占总损失 76.3%
去掉标点和 <eos>，只看字：6.891
```

![四类题目占题目数与占总损失的比例：标点占题目的 17%、几乎不占损失；句首的字占题目的 17%、占损失的 23%；句中的字占题目的 63%、占损失的 76%](/tinyllm/figures/lm-loss-breakdown.svg)

怎么读这张图：上面一条是题目的构成，下面一条是损失的构成。标点占了六分之一的题，却几乎不贡献损失，模型早就学会了“五字一标点”。剩下的损失几乎全来自字：句首的字最难（7.59），因为它前面只有一个标点，几乎没有可用的上下文；句中的字有前面几个字作提示，略容易一些（6.70）。

这说明两件事。第一，5.579 是“容易的标点”和“很难的字”平均出来的；只看字，平均损失是 6.891，困惑度约 980。第二，后面各章比较改动时，如果某个改动让 5.579 降了 0.05，它可能是让模型更会猜字了，也可能只是让标点的损失从 0.09 降到了 0.05——后一种对写诗几乎没有帮助。需要时，把损失按题型拆开看。[第 26 章](./generation.md)会从采样的角度再看同一件事：标点位置的熵很低，句子刚起头的位置熵很高。

## 8. 模型给的概率可信吗

交叉熵惩罚的是“给正确答案的概率太低”。它还有一个不那么显眼的性质：在所有给分布打分的方法里，它属于**严格适当的评分规则**（strictly proper scoring rule），只有当模型报出的概率等于真实的频率时，期望损失才最小（[Gneiting 与 Raftery，2007](https://doi.org/10.1198/016214506000001437)）。换句话说，用交叉熵训练，是在鼓励模型“说 30% 的事，真的有 30% 会发生”。这叫**校准**。

基线模型校准得怎样？把验证集每道题按“模型最有把握的那个答案的概率”分组，看每组实际猜中了多少：

<<< @/public/tinyllm/code/language-model-loss.py#calibration

```text
把握 0.0～0.1： 9074 道   平均把握 0.02   实际猜中 0.02
把握 0.1～0.2：  282 道   平均把握 0.15   实际猜中 0.12
把握 0.2～0.3：  215 道   平均把握 0.24   实际猜中 0.18
把握 0.3～0.4：  161 道   平均把握 0.34   实际猜中 0.26
把握 0.4～0.5：  102 道   平均把握 0.44   实际猜中 0.32
把握 0.5～0.6：  131 道   平均把握 0.54   实际猜中 0.33
把握 0.6～0.7：   76 道   平均把握 0.65   实际猜中 0.49
把握 0.7～0.8：   78 道   平均把握 0.75   实际猜中 0.68
把握 0.8～0.9：   89 道   平均把握 0.85   实际猜中 0.76
把握 0.9～1.0： 2016 道   平均把握 0.99   实际猜中 0.99
总体猜中 20.5%；按题数加权的平均偏差（ECE）0.013
```

![基线模型的可靠性图：两端贴着对角线，把握不到 0.1 的九千多道题和把握 0.9 以上的两千道题都很准；中间几组落在对角线下方，例如平均把握 0.54 的一组只猜中 0.33](/tinyllm/figures/lm-loss-calibration.svg)

怎么读这张图：横轴是模型说的把握，纵轴是实际猜中的比例，对角线是完美校准，点越大表示这一组的题越多。

- **两头很准。** 九千多道题模型的把握不到 0.1，实际也只猜中 2%：它知道自己不知道。两千道题把握在 0.9 以上（几乎都是标点），实际猜中 99%。
- **中间偏自信。** 把握在 0.3～0.7 的几组都在对角线下方，平均把握 0.54 的那组只猜中 33%。这些题不多（加起来几百道），所以按题数加权的平均偏差（ECE）只有 0.013。
- **总体猜中率只有 20.5%**，而且主要来自标点。对语言模型来说，“猜中率”不是好指标：下一个字往往有很多种合理的写法，交叉熵衡量的是整个分布给得好不好，而不只是第一名对不对。

这个模型只训练了 300 步，还在学，中间段偏自信可能随训练变化，本章没有追踪。大模型在预训练之后通常校准得不错，经过对齐训练后反而可能变差（[OpenAI，2023](https://arxiv.org/abs/2303.08774) 的 GPT-4 技术报告里有对比）。

### 两种常见的改法：label smoothing 与 z-loss

交叉熵有两个常见的“变体”，本课的基线都没有用，但读论文和源码时会经常碰到：

- **label smoothing**：目标不再是“正确答案 1、其余 0”，而是“正确答案 $1-\varepsilon$，其余平分 $\varepsilon$”。它最早用在图像分类上，防止模型对训练标签过分自信（[Szegedy 等，2016](https://arxiv.org/abs/1512.00567)）。
- **z-loss**：在交叉熵之外加一项 $10^{-4} \cdot (\ln \sum_j e^{z_j})^2$，惩罚 log-sum-exp 远离 0，防止 logits 整体越漂越大、在低精度下溢出。PaLM 用它来稳定大规模训练（[Chowdhery 等，2022](https://arxiv.org/abs/2204.02311)）。

它们各会把损失变成什么样？在基线上算一下：

<<< @/public/tinyllm/code/language-model-loss.py#variants

```text
label smoothing ε=0.1：完美模型的损失下限 1.157（不平滑时是 0）
基线在验证集上：普通交叉熵 5.579，按 ε=0.1 平滑算 6.109
log-sum-exp：平均 9.92，最大 15.08；z-loss（系数 1e-4）= 0.0102
```

- **label smoothing 改变了“最好”的定义。** 平滑后的目标本身就有不确定性，即使模型完美，损失也降不到 1.157 以下；模型被要求给每个错误答案都留一点概率。对语言模型来说，“下一个 token 的概率”本身就是我们想要的东西，被人为抹平以后，困惑度和校准都不再对应真实的数据分布。所以 GPT、Llama 这类预训练一般不用 label smoothing。用了平滑训练的模型，验证时也要用普通交叉熵来报损失，否则数字没法和别人比。
- **z-loss 的量级很小。** 基线的 log-sum-exp 平均约 9.9，z-loss 只有 0.01，和 5.579 比可以忽略，不会改变训练的目标，只是给 logits 的整体大小加了一根“橡皮筋”。131 万参数、FP32 训练的 TinyLLM 用不上它；放大模型、换成 BF16 以后才值得考虑（[第 24 章](./large-model-stability.md)）。

## 动手实验

1. **算一首你熟悉的诗。** 把 `poem` 换成“床前明月光，疑是地上霜。举头望明月，低头思故乡。”（它在训练集里），每个字的损失和验证诗比有什么不同？模型“背过”一首诗，损失图会变成什么样？
2. **不屏蔽 `<pad>` 训练。** 把第 12 章的训练改成逐首补齐、不设 `ignore_index`，训练 300 步。报出来的训练损失和验证损失（用第 12 章的 `evaluate`，不受补齐影响）各是多少？至少跑 3 个种子。
3. **屏蔽 `<eos>` 训练。** 训练时把目标里的 `<eos>` 改成 -100，再用第 12 章的 `generate` 写几首。它还会自己停下来吗？
4. **label smoothing。** 训练时用 `F.cross_entropy(..., label_smoothing=0.1)`，验证时仍用普通交叉熵。验证损失和可靠性图有什么变化？

<!-- real-model:start -->

## 在真实模型里

transformers 里因果语言模型的损失只有几十行，本章讲的错位、忽略位置和分母都在里面。下表的链接都指向 Hugging Face transformers 的固定版本 `v5.21`，精确到行。读代码时可以先跳过缓存、掩码、并行这些工程细节，只看和本章对应的那几行。

| 本章的零件 | 真实代码 | 对照要点 |
| --- | --- | --- |
| 错位与忽略位置 | [`ForCausalLMLoss`](https://github.com/huggingface/transformers/blob/v5.21/src/transformers/loss/loss_utils.py#L51-L73) | 先 `logits.float()` 转成 FP32；把 `labels` 末尾补一个 -100 再整体左移一位，就是本章第 1 节的错位；-100 的位置不算损失 |
| 分母放在哪 | [`fixed_cross_entropy`](https://github.com/huggingface/transformers/blob/v5.21/src/transformers/loss/loss_utils.py#L34-L48) | 传入 `num_items_in_batch` 时先按 `sum` 求和，再除以整个累积批次的有效题数，正是本章第 5 节“各自求和、最后除以总题数”的做法 |
| 统计有效题数 | [`Trainer._get_num_items_in_batch`](https://github.com/huggingface/transformers/blob/v5.21/src/transformers/trainer.py#L2278-L2339) | 把梯度累积要用的全部 micro-batch 的标签（错位后）里不是 -100 的位置加起来，作为 `num_items_in_batch`；多卡时还会把各卡的数加总 |
| label smoothing | [`LabelSmoother`](https://github.com/huggingface/transformers/blob/v5.21/src/transformers/trainer_pt_utils.py#L435-L481) | `label_smoothing_factor` 不为 0 时启用：普通负对数似然和“对所有候选取平均”的那一项按 ε 混合 |

想在本机看源码，可以先 `pip install transformers`，再用 `python -m inspect transformers.models.llama.modeling_llama:LlamaMLP` 这样的命令打印出任意一个类。

<!-- real-model:end -->

## 本章结论：TinyLLM 的选择 {#tinyllm-choice}

TinyLLM 的训练目标是**下一个 token 的交叉熵**：输入和目标错开一位，每个有效位置算 $-\ln p(\text{正确答案})$，用 `F.cross_entropy` 直接从原始 logits 计算（内部是数值稳定的 log-sum-exp），**按有效 token 数平均**。`<eos>` 算在损失里，模型才学得会停；`<pad>` 和以后指令微调里的提问部分，用 `ignore_index=-100` 屏蔽。梯度累积时每个 micro-batch 只求和，最后除以整个累积批次的有效 token 数。不用 label smoothing，暂不加 z-loss。

第 12 章的验证损失 5.579，是验证集 12,224 道题的 $-\ln p$ 平均。它等于 8.05 比特/token、7.68 比特/字、困惑度 265。其中标点几乎不贡献损失，只看字是 6.891。模型给的概率在两端校准得很好，中间几组偏自信（单个模型、单个种子，训练 300 步）。

这些选择在什么情况下要换：样本长短差别大、又用梯度累积或多卡训练时，一定要检查分母；指令微调只在回答部分算损失（[第 34 章](./instruction-finetuning.md)）；模型放大、换低精度以后 logits 漂移，再考虑 z-loss（[第 24 章](./large-model-stability.md)）。

::: warning 常见误区
- **先 softmax 再取 log。** logits 一大就会得到 `inf` 或 `nan`。把原始 logits 交给 `F.cross_entropy` 或 `F.log_softmax`。
- **困惑度越低越好，所以可以随便比。** 不同分词器、不同验证集的困惑度不能直接比。换成比特/字（或比特/字节），并且在同一份验证集上比。
- **平均损失降了，模型就更会写诗了。** 损失里有六分之一的题是几乎白送的标点。需要时按题型拆开看。
- **梯度累积只是把 batch 拆开，结果一样。** 只有每个 micro-batch 的有效 token 数相同时才一样。样本长短不一时，要先求和、最后除以总的有效 token 数。
- **`<eos>` 和 `<pad>` 一样，都是“特殊 token”，都屏蔽掉。** `<pad>` 要屏蔽，`<eos>` 必须算：模型要学会什么时候停。
- **猜中率比交叉熵直观，可以替代它。** 下一个字往往有很多合理的选择，猜中率只看第一名，交叉熵看整个分布。
:::

## 检查理解

1. 模型对某道题给正确答案的概率是 0.5，损失是多少 nats？如果是 0.001 呢？为什么说交叉熵对“猜得很差”的题特别敏感？

   <details><summary>参考答案</summary>

   $-\ln 0.5 \approx 0.69$，$-\ln 0.001 \approx 6.91$。概率从 0.5 降到 0.25，损失只增加 0.69；从 0.001 降到 0.0001，损失却增加 2.3。对数在接近 0 的地方变化极快，所以平均损失会被少数“几乎没料到”的题拉高。这也是困惑度对应几何平均而不是算术平均的原因：第 4 节里，正确答案的算术平均概率是 0.181，几何平均只有 0.0038。

   </details>

2. 第 3 节说，正确答案那一格的梯度是 $p_y - 1$，其余每格是 $p_j$。如果模型已经给正确答案 0.99 的概率，梯度会是什么样？这对训练意味着什么？

   <details><summary>参考答案</summary>

   正确答案那一格的梯度是 $0.99 - 1 = -0.01$，其余格子的梯度加起来是 0.01，都很小。已经猜得很准的题几乎不再推动参数，训练的力气自动花在还猜不准的题上。这也解释了第 7 节：标点早就学会了，它们占了六分之一的题，却几乎不贡献梯度。

   </details>

3. 某次训练用了梯度累积 4 步，每个 micro-batch 里的样本是按长度排好序的。你发现它和不用累积、batch 放大 4 倍的训练曲线对不上。最可能是什么原因？怎么改？

   <details><summary>参考答案</summary>

   最可能是每个 micro-batch 各自求了平均，再除以 4。按长度排序后，各 micro-batch 的有效 token 数差别很大，短样本组里每个 token 的权重被放大、长样本组被缩小，梯度和一次算完不同（第 5 节里余弦相似度只有 0.939）。改法：每个 micro-batch 用 `reduction="sum"` 求和，最后除以 4 个 micro-batch 有效 token 的总数；transformers 里就是 `num_items_in_batch` 这个参数。

   </details>

4. 用 label smoothing（ε=0.1）训练的模型报告“验证损失 2.3”，没用平滑的模型报告“验证损失 2.5”。能说前者更好吗？

   <details><summary>参考答案</summary>

   不能直接比。如果前者的 2.3 是按平滑后的目标算的，它和普通交叉熵不是同一个量：平滑损失有一个大于 0 的下限，而且对同一个模型通常比普通交叉熵更高（第 8 节里基线是 6.109 对 5.579）。要比较，两个模型都要在同一份验证集上用**普通交叉熵**（不平滑）计算，最好再换成比特/字。

   </details>

## 参考资料

- [PyTorch：`torch.nn.functional.cross_entropy`](https://docs.pytorch.org/docs/stable/generated/torch.nn.functional.cross_entropy.html)（`ignore_index`、`reduction`、`label_smoothing` 参数）
- [Fixing Gradient Accumulation，Hugging Face，2024](https://huggingface.co/blog/gradient_accumulation)（梯度累积时损失归一化的问题与修复）
- [Strictly Proper Scoring Rules, Prediction, and Estimation，Gneiting 与 Raftery，2007](https://doi.org/10.1198/016214506000001437)（对数评分是严格适当的评分规则）
- [On Calibration of Modern Neural Networks，Guo 等，2017](https://arxiv.org/abs/1706.04599)（可靠性图与 ECE）
- [Rethinking the Inception Architecture for Computer Vision，Szegedy 等，2016](https://arxiv.org/abs/1512.00567)（label smoothing 的出处）
- [When Does Label Smoothing Help?，Müller 等，2019](https://arxiv.org/abs/1906.02629)（label smoothing 对校准和表示的影响）
- [PaLM: Scaling Language Modeling with Pathways，Chowdhery 等，2022](https://arxiv.org/abs/2204.02311)（z-loss）
- [GPT-4 Technical Report，OpenAI，2023](https://arxiv.org/abs/2303.08774)（预训练模型与对齐后模型的校准对比）

损失定义清楚了，下一步是怎样让它降下去：[第 16 章：优化器](./optimizers.md)。
