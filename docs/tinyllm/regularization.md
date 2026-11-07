---
title: "第 18 章：正则化与泛化"
description: "第 12 章的基线还没开始背书，正则化要不要加？只给模型 300 首诗让它过拟合，用 29 次对照训练比较更多数据、提前停止、weight decay、dropout 和 label smoothing，再回到全部数据，看同样的手段为什么反而变差。"
pageClass: tinyllm-course
---

# 第 18 章：正则化与泛化

[课程总览](./index.md) · [上一章](./learning-rate.md) · [下一章](./precision.md)

::: tip 本章学习目标
能从训练损失和验证损失的走势判断模型是在“学”还是在“背”；能用验证集挑出停止的步数和超参数，再用测试集报告一次结果；能说清 weight decay、dropout、label smoothing、提前停止各自怎么起作用，以及为什么它们在数据充足、只过一遍数据的预训练里通常不用加，或者只加一点。

**前置：** [第 12 章](./tinyllm-model.md)的基线与评估口径，[第 16 章](./optimizers.md)的 AdamW 与参数分组，[第 17 章](./learning-rate.md)的代理模型和对照实验写法；[第 15 章](./language-model-loss.md)讲过 label smoothing 会改变损失的下限。

**实践方式：** [regularization.ipynb](/tinyllm/notebooks/regularization)（也可以直接运行 <a href="/tinyllm/code/regularization.py" download>regularization.py</a>），CPU 约两分钟，需要 PyTorch 和 `tokenizers`。
:::

[第 12 章](./tinyllm-model.md)的基线有 5419 首训练诗，300 步只把训练集过了约 2.7 遍。训练结束时，最后 50 步的平均训练损失是 5.539，验证损失是 5.579，两条线几乎贴在一起。模型还在“学”，没有开始“背”。

[30 分钟快速体验](./quickstart.md)和[第 14 章](./data-pipeline.md)的泄漏实验却是另一番景象：训练集只有两三百首，训练损失一路往下掉，验证损失见底以后掉头向上。模型把训练集背了下来，碰到没见过的诗反而更没把握。这叫**过拟合**；让模型在没见过的数据上也表现好，叫**泛化**。

数据不够多的情况并不少见：语料只有某个窄领域、要在小数据上微调、或者干脆把同一份数据多过几遍。这时就需要**正则化**，也就是各种“不让模型把训练集背得太死”的手段。本章故意只给模型 300 首诗，先让它过拟合，再逐个试这些手段，最后回到全部数据，看它们还有没有用。

<TinyLLMMap active="regularization" />

::: info 本章代码从哪里来
本章所有代码都在一个文件里：<a href="/tinyllm/code/regularization.py" download>regularization.py</a>（[在 GitHub 上查看](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/tinyllm/code/regularization.py)）。下面的代码块都是从这个文件里直接截取的片段，所以单独复制一段可能缺少 `import` 或前面定义的变量；想自己运行，请下载完整文件，`python regularization.py` 从头跑到尾即可。notebook 版本也由同一个文件生成，可以[在线查看](/tinyllm/notebooks/regularization)，或[在 Colab 中直接运行](https://colab.research.google.com/github/lewislau86/lewislau86.github.io/blob/master/docs/public/tinyllm/notebooks/regularization.ipynb)。正文引用的输出来自 torch 2.14.1+cpu、tokenizers 0.23.3。
:::

## 0. 实验设定：300 首诗，三份数据

模型用[第 17 章](./learning-rate.md)的代理模型：代码从第 12 章原样复制，词表 1024、宽度 64、2 层，16 万参数。学习率固定为第 12 章的 3e-3，每步 16 段、每段 64 个 token，训练 300 步：

<<< @/public/tinyllm/code/regularization.py#proxy

训练集只取前 300 首训练诗。为了看清“数据多少”的影响，再准备 600 首、1200 首和全部 5419 首三份，分词器统一在全部训练诗上训练，所以各份数据切出的 token 一样：

<<< @/public/tinyllm/code/regularization.py#subsets

```text
训练集  300 首： 15304 个 token，300 步约过 20.1 遍
训练集  600 首： 31809 个 token，300 步约过  9.7 遍
训练集 1200 首： 64840 个 token，300 步约过  4.7 遍
训练集 5419 首：296250 个 token，300 步约过  1.0 遍
验证集 291 首：15892 个 token；测试集 290 首：16094 个 token
```

先猜一下：同样 300 步，只有 300 首诗的模型会把训练集过 20 遍，它的验证损失会怎么走？

这里第一次用到了**测试集**。统一语料按正文哈希分成了训练、验证、测试三份（见[实验环境](./setup.md)），前 6000 首里各有 5419、291、290 首。三份数据分工不同：

- **训练集**：用来算梯度、更新参数。
- **验证集**：用来做选择，比如停在哪一步、weight decay 取多大。被用来挑选过的数，或多或少都偏乐观。
- **测试集**：所有选择都做完以后，只测一次，用来报告结果。

本章比较各种手段时，统一报告**测试损失**：每次训练取验证损失最低的那一步，恢复那一步的参数，再在测试集上测一次。

训练函数和第 17 章一样，只多了三样东西：可以设 `weight_decay`、`dropout` 和 `smoothing`；每 25 步测一次验证损失，同时记下矩阵权重的 L2 范数；训练结束后换回验证损失最低时的参数，在测试集上测一次。batch 计划由单独的随机数生成器排好，所有对照共用，`seed` 只决定初始参数（加了 dropout 时还决定随机掩码）：

<<< @/public/tinyllm/code/regularization.py#run

`stopper` 是下面第 3 节要讲的提前停止工具；`patience` 默认是无穷大，即一直训练到第 300 步，只是记住最好的那一步。

## 1. 过拟合现场

什么正则化都不加（`weight_decay=0`、`dropout=0`），在 300 首诗上训练 300 步。训练集上的损失也用 `model.eval()` 来测，和验证集同一个口径：

<<< @/public/tinyllm/code/regularization.py#overfit

```text
步数    训练    验证   验证-训练
  25   5.834   6.026  +0.192
  50   5.296   5.806  +0.509
 100   4.338   5.541  +1.203
 150   3.824   5.625  +1.801
 200   3.323   5.834  +2.511
 250   2.955   6.082  +3.126
 300   2.647   6.347  +3.701
验证损失最低在第 100 步：5.541；那一步的参数在测试集上 5.514
```

![300 首诗、不加正则化（种子 0）：训练损失从 5.83 一路降到 2.65；验证损失在第 100 步见底（5.541），之后一路回升到 6.35，两者的差从 0.19 拉大到 3.70](/tinyllm/figures/reg-overfit.svg)

怎么读这张图：

- **前 100 步，两条线一起降。** 模型在学所有诗共有的东西：常用字、五字一句、逗号句号交替。这些在验证集上同样成立，所以验证损失也跟着降。
- **第 100 步以后，两条线分道扬镳。** 训练损失接着往下掉，验证损失掉头向上。模型开始记“这 300 首诗里，这个字后面跟的是哪个字”，这些记忆换一首诗就不成立了，而且模型对它们越来越自信，猜错时付出的代价也越来越大。
- **两条线的差叫泛化差距。** 它从 0.19 拉大到 3.70。训练损失低本身不说明问题，要看它和验证损失差多少、差距是不是还在变大。

这就是本章要对付的局面。最好的结果出现在第 100 步，验证损失 5.541；之后再训练 200 步，全是在帮倒忙。

## 2. 第一个办法：更多数据

过拟合的根源是数据太少、训练遍数太多。最直接的办法，是给模型更多的数据。同一个模型、同样 300 步，训练集换成 600 首、1200 首和全部 5419 首：

<<< @/public/tinyllm/code/regularization.py#more-data

```text
无正则化               最好的一步 100/100/100 测试 5.508（5.483～5.526）  第 300 步验证 6.333
600 首              最好的一步 225         测试 5.142                第 300 步验证 5.219
1200 首             最好的一步 300         测试 4.831                第 300 步验证 4.844
5419 首             最好的一步 300/300/300 测试 4.711（4.702～4.723）  第 300 步验证 4.741
```

第一行就是 300 首的情形，3 个种子都在第 100 步见底，测试损失平均 5.508。600 首和 1200 首只跑了一个种子，但差距很大，足以看清趋势：

![同一个模型、同样 300 步，只改训练集大小（种子 0）：300 首在第 100 步见底（5.54）后回升；600 首推迟到第 225 步（5.16）；1200 首和全部 5419 首在 300 步内一直在下降](/tinyllm/figures/reg-data-size.svg)

- **数据翻一倍（600 首），** 最低点推迟到第 225 步，测试损失从 5.508 降到 5.142。
- **翻两番（1200 首），** 300 步内验证损失一直在降，没有出现回升，测试损失 4.831。
- **全部 5419 首，** 300 步只过了一遍数据，训练损失和验证损失贴在一起（第 300 步分别是 4.679 和 4.733），测试损失 4.711。

后面几节会看到，最好的正则化手段，大约只能做到“数据翻一倍”的效果。**能拿到更多数据时，先加数据。**

## 3. 提前停止

不加数据，最省事的办法是在验证损失见底的地方停下来。实际训练时不知道哪里是底，常见的做法是：每隔一段测一次验证损失，连续 `patience` 次没有创新低就停，并把参数换回验证损失最低的那一次。

<<< @/public/tinyllm/code/regularization.py#early-stopping

两个参数的意思：`min_delta` 是“算作进步”的最小降幅，避免验证损失的小抖动被当成进步；`patience` 是能容忍多少次没有进步。验证损失本来就会抖，`patience` 太小，可能在一次偶然的小回升处就停了。

用 `patience=4` 训练一次，也就是连续 100 步没有进步就停：

<<< @/public/tinyllm/code/regularization.py#stop-demo

```text
在第 200 步停下（省下 100 步）；最好的一步是第 100 步，验证 5.541，测试 5.514
```

结果和第 1 节事后挑出的第 100 步完全一样，还省了三分之一的训练。提前停止的代价有两样：一是每次评估要花时间，验证集越大、测得越勤，花得越多；二是要多存一份参数（大模型通常存成检查点文件，见[第 21 章](./training-loop.md)）。

提前停止只是“停在最好的地方”，不会让最好的地方变得更好：300 首诗上，它的上限就是 5.508。要把这个上限往下压，要靠下面几节的手段。

还有一件要注意的事：停在哪一步，是用验证集**挑**出来的，挑选过程用到了验证集，所以验证损失的最低值会偏乐观。挑的次数越多（多少个检查点、多少组超参数），偏得越多。这就是本章在最后要用测试集再测一次的原因。

## 4. weight decay

[第 16 章](./optimizers.md)讲过 AdamW 的 weight decay：每一步先把参数乘以 $1 - \eta\lambda$（$\eta$ 是学习率，$\lambda$ 是 `weight_decay`），再做 Adam 的更新。

$$
\theta \leftarrow (1 - \eta\lambda)\,\theta - \eta \cdot \text{Adam 的更新}
$$

它不断把权重往 0 拉，只有数据的梯度一直在“推”的方向，权重才能保持得住。背诵个别诗句需要的那些特殊方向，梯度只在少数 batch 里出现，推一下、又被拉回来，不容易长大。

第 12 章用的是 `weight_decay=0.1`，学习率 3e-3。先算一下它每步缩多少：

<<< @/public/tinyllm/code/regularization.py#wd-sweep

```text
weight_decay=0.1 ：每步乘 0.9997，300 步累计乘 0.914，时间尺度 1/(lr·wd) ≈ 3333 步
weight_decay=1.0 ：每步乘 0.9970，300 步累计乘 0.406，时间尺度 1/(lr·wd) ≈ 333 步
weight_decay=3.0 ：每步乘 0.9910，300 步累计乘 0.066，时间尺度 1/(lr·wd) ≈ 111 步
weight_decay=10.0：每步乘 0.9700，300 步累计乘 0.000，时间尺度 1/(lr·wd) ≈ 33 步
```

$1/(\eta\lambda)$ 可以理解为“weight decay 的时间尺度”：大约这么多步之前的更新，会被衰减掉大半（乘以约 $1/e$）。`weight_decay=0.1` 的时间尺度是 3333 步，比整个训练（300 步）长十倍，在这么短的训练里它几乎来不及起作用。先猜一下：0.1 能不能挡住第 1 节的过拟合？

各训练一次（种子 0）：

```text
weight_decay 0.1   最好的一步 100         测试 5.494                第 300 步验证 6.234
weight_decay 1     最好的一步 175         测试 5.308                第 300 步验证 5.494
weight_decay 3     最好的一步 300         测试 5.088                第 300 步验证 5.112
weight_decay 10    最好的一步 225         测试 5.298                第 300 步验证 5.315
第 300 步矩阵权重的 L2 范数（种子 0）： 0 → 53.9  0.1 → 50.6  1 → 31.6  3 → 16.4  10 → 7.8
```

![左：300 首诗、种子 0。weight_decay=0 和 0.1 的验证损失几乎重合，第 100 步后一路回升；1 推迟并压低了回升；3 的验证损失一直在降，最好；10 压得太狠，最低点反而比 3 高。右：第 300 步矩阵权重的 L2 范数从 53.9 依次降到 7.8](/tinyllm/figures/reg-weight-decay.svg)

怎么读这张图：

- **0.1 几乎没有作用。** 验证曲线和不加 weight decay 的贴在一起，权重范数也只小了一点（50.6 对 53.9）。这正是时间尺度告诉我们的。
- **1 推迟了回升，3 消除了回升。** `weight_decay=3` 的验证损失在 300 步里一直在降，最好的一步就是最后一步，测试损失 5.088。时间尺度 111 步，比训练短得多，权重被压到了 16.4，不加时是 53.9。
- **10 太强了。** 时间尺度只有 33 步，权重被压到 7.8，模型连该学的东西都学不进去，最低点（5.298）反而比 3 高。weight decay 也有一个 U 形：太小没作用，太大学不动。

所以 weight decay 的强度要看 $\eta\lambda$ 和训练步数，单看 `weight_decay` 这一个数说明不了什么。同样的 `weight_decay=0.1`，学习率大十倍、或者训练长十倍，作用就完全不一样了。[Wang 与 Aitchison（2024）](https://arxiv.org/abs/2405.13698)把 AdamW 的权重看作最近若干步更新的滑动平均，时间尺度就是 $1/(\eta\lambda)$；他们的实验发现，合适的时间尺度大致是训练总步数的一个固定比例，数据越多，最佳的 `weight_decay` 越小。第 7 节会看到，这一点在本章的实验里也成立。

### L2 正则与 L1 正则

还有两种更早的写法，是在损失上加一项惩罚：

- **L2 正则**：损失加上 $\frac{\lambda}{2}\lVert\theta\rVert^2$，梯度多出 $\lambda\theta$。用普通 SGD 时，它和上面的 weight decay 是同一件事；用 Adam 时就不同了，这一项会被 Adam 按每个参数的梯度大小重新缩放，梯度大的参数反而衰减得少。这是 AdamW 把衰减“解耦”出来的原因，[第 16 章](./optimizers.md)用一个算例对照过两者。
- **L1 正则**：损失加上 $\lambda\lVert\theta\rVert_1$，梯度多出 $\lambda\,\text{sign}(\theta)$。它每步减去一个固定的量，而不是按比例缩小，会把很多权重一直推到正好是 0，得到稀疏的权重。线性模型里常用它挑选特征，训练语言模型时很少用。

## 5. dropout

dropout 的做法是：训练时，每次前向都随机把一部分数置零，比例是 $p$；留下的数乘以 $1/(1-p)$，让平均值保持不变（[Srivastava 等，2014](https://jmlr.org/papers/v15/srivastava14a.html)）。模型不能指望某一个神经元一定在，就不容易靠少数几个神经元的特殊组合去记住个别样本。

dropout 放在哪？常见的位置有三处，本章都加上，用同一个比例：

![左：TinyLLM 的三处 dropout。① 注意力权重在 softmax 之后随机丢掉一部分；② 注意力和 SwiGLU 的输出在加回残差流之前各过一次 dropout；③ 词嵌入之后过一次。右：model.train() 时每个数以概率 p 置零，留下的乘 1/(1−p)，p=0.3 时约乘 1.43；model.eval() 时原样通过](/tinyllm/figures/reg-dropout-positions.svg)

代码上的改动很少。配置里多一个字段：

<<< @/public/tinyllm/code/regularization.py#config

注意力里，把 `dropout_p` 传给 `F.scaled_dot_product_attention`，它会在 softmax 之后丢掉一部分注意力权重（位置 ①）。只在训练模式下传，评估时传 0：

<<< @/public/tinyllm/code/regularization.py#attention

Block 里，两个子层的输出在加回残差流之前各过一次 `nn.Dropout`（位置 ②）：

<<< @/public/tinyllm/code/regularization.py#block

模型的 `forward` 第一行改成 `x = self.drop(self.embed(idx))`（位置 ③）。`dropout=0.0` 时，这三处都原样通过，模型和第 12 章完全一样。

### train 模式与 eval 模式

`nn.Dropout` 和 `F.scaled_dot_product_attention` 的 `dropout_p` 都要看模型当前的模式。用同一个 batch 试一下：

<<< @/public/tinyllm/code/regularization.py#dropout-modes

```text
train 模式，连算两次： 7.4904 7.4588
eval 模式，连算两次：  7.4357 7.4357
nn.Dropout(0.3) 作用在 10 万个 1 上：置零的比例 0.299，留下的值都是 1.4286，平均 1.0009
```

train 模式下，同一个输入算两次，损失不一样，因为每次的随机掩码不同；eval 模式下 dropout 不起作用，结果是确定的。最后一行验证了缩放：置零约 30%，留下的乘 $1/0.7 \approx 1.4286$，平均值还是 1。

这带来两个实际的后果。第一，**评估和生成之前要调 `model.eval()`**，评估完再调回 `model.train()`；本章的 `evaluate` 函数开头和结尾就是这么做的。忘了切换，验证损失会偏高，而且每次测都不一样。第二，**训练循环里打印的训练损失是在 train 模式下算的**，带着 dropout 的噪声，会比同一时刻模型的真实水平偏高。要和验证损失比，得像本章这样，在 eval 模式下单独测训练集。

### 效果

在 300 首诗上试 `dropout=0.1` 和 `0.3`（种子 0）：

<<< @/public/tinyllm/code/regularization.py#dropout-sweep

```text
dropout 0.1        最好的一步 125         测试 5.339                第 300 步验证 5.695
dropout 0.3        最好的一步 250         测试 5.251                第 300 步验证 5.336
无正则化       最好的一步（第 100 步）：训练 4.338  验证 5.541  差 +1.203
dropout 0.3 最好的一步（第 250 步）：训练 4.304  验证 5.274  差 +0.970
```

![300 首诗、种子 0。不加 dropout 时验证损失第 100 步见底（5.541）；dropout 0.3 让训练损失降得更慢，验证损失推迟到第 250 步才见底，最低点 5.274 更低，之后的回升也平缓得多](/tinyllm/figures/reg-dropout.svg)

怎么读这张图（实线是验证损失，虚线是在 eval 模式下测的训练损失）：

- **dropout 让训练变慢了。** 三条虚线里，`dropout=0.3` 的训练损失降得最慢。每一步都在一个“残缺”的网络上训练，学同样的东西要更多步。
- **最低点推迟了，也更低了。** `dropout=0.3` 在第 250 步才见底，测试损失 5.251，比不加的 5.508 低了不少。
- **在差不多的训练损失下，泛化差距更小。** 不加 dropout 时，训练损失到 4.338 那一步，验证损失是 5.541，差 1.20；`dropout=0.3` 的训练损失到 4.304 时，验证损失是 5.274，差 0.97。训练集拟合到同样的程度，dropout 的模型背得少一些、学得多一些。

加了 dropout，每一步还要多生成随机掩码，训练也会略慢一点。

## 6. 3 个种子确认

第 4、5 节的扫描都只用了一个种子，用来找大致的范围。下面把要下结论的几种设置各跑 3 个种子：第 12 章用的 `weight_decay=0.1`，扫描里最好的 `weight_decay=3` 和 `dropout=0.3`，再加上 label smoothing。

label smoothing 在[第 15 章](./language-model-loss.md)讲过：训练目标不再是“正确答案概率 1”，而是“正确答案 $1-\varepsilon$，其余候选平分 $\varepsilon$”，模型就不会被逼着对训练集的答案越来越自信。它会改变损失的下限，所以只在训练时用 ε=0.1，验证和测试仍然用普通交叉熵，这样才能和其他设置比较。

<<< @/public/tinyllm/code/regularization.py#confirm

```text
weight_decay 0.1   最好的一步 100/125/100 测试 5.484（5.467～5.494）  第 300 步验证 6.219
weight_decay 3     最好的一步 300/300/300 测试 5.078（5.071～5.088）  第 300 步验证 5.104
dropout 0.3        最好的一步 250/225/225 测试 5.253（5.247～5.262）  第 300 步验证 5.334
label smoothing 0.1 最好的一步 100/125/100 测试 5.484（5.468～5.494）  第 300 步验证 6.159
```

和不加正则化的 5.508（5.483～5.526）比：

- **`weight_decay=0.1` 和 label smoothing 都没有可靠的改善。** 平均都是 5.484，3 个种子的范围和不加正则化的重叠，最好的一步也都还在第 100 步左右。label smoothing 让第 300 步的验证损失低了一些（6.159 对 6.333），也就是回升得慢一点，但最好的那一点没有变。
- **`dropout=0.3` 明显更好：** 5.253，范围不重叠。
- **`weight_decay=3` 最好：** 5.078，范围不重叠，3 个种子的最好一步都是最后一步，说明到第 300 步还没开始过拟合。这和第 2 节“数据翻一倍”（600 首，5.142，单个种子）的效果相当，但比不上“翻两番”（1200 首，4.831）。

实验的边界：代理模型、300 首诗、300 步、学习率固定 3e-3；weight decay 和 dropout 各只扫了几个值，扫描是单个种子；没有试两者的组合。所以“weight decay 比 dropout 好”只在这个设定下成立。[Xue 等（2023）](https://arxiv.org/abs/2305.13230)在更大的语言模型上反复训练同一份数据时，发现 dropout 是最有效的正则化，他们试过的 weight decay 作用不大；两边的结论不能互相推出，用到自己的模型上要重新比。

## 7. 回到全部 5419 首：这些手段还有用吗？

前面在 300 首上有效的手段，用到全部数据上会怎样？全部数据 300 步只过了约一遍，第 2 节已经看到训练和验证损失贴在一起。把 `weight_decay=3` 和更温和的 `dropout=0.1` 用上去，各跑 3 个种子：

<<< @/public/tinyllm/code/regularization.py#full-data

```text
无正则化               测试 4.711（4.702～4.723）
全部 weight_decay 3  最好的一步 300/300/250 测试 4.866（4.851～4.884）  第 300 步验证 4.893
全部 dropout 0.1     最好的一步 300/300/300 测试 4.782（4.764～4.795）  第 300 步验证 4.809
全部数据、无正则化（种子 0）第 300 步：训练 4.679  验证 4.733
```

![左：300 首诗上，3 个种子的测试损失。无正则化 5.508；weight_decay 0.1 与 label smoothing 几乎没变化（都是 5.484）；dropout 0.3 降到 5.253；weight_decay 3 最好，5.078，和训练集换成 600 首（5.142，单种子）相当；换成 1200 首是 4.831。右：全部数据上，无正则化 4.711 最好，dropout 0.1 变差到 4.782，weight_decay 3 变差到 4.866](/tinyllm/figures/reg-compare.svg)

**两种手段都让结果变差了**，3 个种子的范围都不重叠：`dropout=0.1` 从 4.711 变成 4.782，`weight_decay=3` 变成 4.866。

道理不难理解。全部数据只过一遍，模型每一步看到的几乎都是新的诗，训练损失和验证损失本来就贴在一起，没有什么“背”的问题要解决。这时模型的瓶颈是学得不够快、不够多，而正则化做的事情恰恰是拖慢学习：dropout 让每一步只用一个残缺的网络，强 weight decay 不断把学到的东西往回拉。没有过拟合可防，剩下的就只有代价。

这也是近几年大模型预训练的常见做法：数据足够多、通常只过一遍，dropout 设为 0（[Liu 等，2025](https://arxiv.org/abs/2505.24788) 专门比较过，单遍预训练里加 dropout 会让语言模型损失和下游表现都变差；[nanoGPT](https://github.com/karpathy/nanoGPT/blob/master/train.py) 的默认配置也写着预训练用 0、微调时再试 0.1 以上）。weight decay 一般还是保留一个温和的值：[LLaMA](https://arxiv.org/abs/2302.13971) 用 0.1，7B 模型的峰值学习率是 3e-4，按峰值算时间尺度约 3.3 万步，而它总共训练了约 25 万步（1 万亿 token、每步 400 万 token）。第 4 节说过，合适的 `weight_decay` 随数据量增大而变小：300 首上最好的 3，放到 5419 首上就太大了。

反过来，数据有限、需要把同一份数据过很多遍时，过拟合又会回来，正则化重新变得有用。[Muennighoff 等（2023）](https://arxiv.org/abs/2305.16264)发现，同一份数据重复 4 遍以内，效果和换成新数据差不多；再多，收益就迅速变小。

## 8. 先看曲线，再决定加什么

把本章的现象整理成一张表。训练时同时记录训练损失（在 eval 模式下测）和验证损失，按走势决定下一步：

| 现象 | 说明 | 先试什么 |
| --- | --- | --- |
| 训练、验证损失贴在一起，都还在降 | 还在学，没有过拟合 | 不加正则化；加大模型、训练更久（第 17 章调学习率） |
| 训练损失继续降，验证损失见底后回升 | 过拟合 | 先加数据；再用提前停止或保留验证损失最好的检查点 |
| 过拟合，但拿不到更多数据 | 需要正则化 | 按时间尺度 $1/(\eta\lambda)$ 调大 weight decay；试 dropout 0.1～0.3；每种都和不加的比 |
| 加了正则化，训练和验证损失都很高 | 正则化太强，学不进去 | 减小 weight decay 或 dropout |
| 训练损失和验证损失差得多，但验证损失还在降 | 有差距不一定是坏事 | 继续训练；看验证损失本身，不只看差距 |
| 验证损失看起来特别好 | 可能是泄漏，或者挑选次数太多 | 查训练集和验证集的重合（[第 14 章](./data-pipeline.md)）；用测试集复核 |

## 动手实验

1. **组合起来。** `weight_decay=3` 和 `dropout=0.3` 一起用（3 个种子）。比各自单独用好吗？最好的一步在哪里？
2. **验证“时间尺度”。** 把学习率从 3e-3 改成 1e-3，`weight_decay` 分别取 3 和 9。哪一个和本章的 `weight_decay=3`（学习率 3e-3）效果更接近？为什么？
3. **用更小的模型当正则化。** 把 `d_model` 从 64 改成 32，不加任何正则化，在 300 首上训练。过拟合得更早还是更晚？测试损失比本章最好的设置如何？
4. **dropout 只放一处。** 只保留位置 ②（子层输出），去掉 ① 和 ③，用 `dropout=0.3` 跑 3 个种子，和三处都放的 5.253 比较。
5. **patience 的取舍。** 用 `patience=1` 和 `patience=8` 各跑一次提前停止，分别停在哪一步？`patience=1` 会不会停得太早？

<!-- real-model:start -->

## 在真实模型里

transformers 里和本章有关的开关都不大：weight decay 在创建优化器时分组，dropout 写在注意力里，提前停止是一个回调。下表的链接都指向 Hugging Face transformers 的固定版本 `v5.21`，精确到行。读代码时可以先跳过缓存、掩码、并行这些工程细节，只看和本章对应的那几行。

| 本章的零件 | 真实代码 | 对照要点 |
| --- | --- | --- |
| 哪些参数做 weight decay | [`Trainer.get_decay_parameter_names`](https://github.com/huggingface/transformers/blob/v5.21/src/transformers/trainer.py#L1405-L1415) | 名字里带 `bias`、`norm` 的参数不衰减，其余（包括词嵌入）按 `weight_decay` 衰减，和本章 `p.dim() >= 2` 的分法结果相同 |
| weight decay 的默认值 | [`training_args.py 第 816 行`](https://github.com/huggingface/transformers/blob/v5.21/src/transformers/training_args.py#L816) | `TrainingArguments` 默认 `weight_decay=0.0`，要自己设；本章的实验说明合适的值和数据量、学习率、训练步数都有关 |
| 注意力 dropout 只在训练时打开 | [`modeling_llama.py 第 263 行`](https://github.com/huggingface/transformers/blob/v5.21/src/transformers/models/llama/modeling_llama.py#L263) | 评估模式下传 0，和本章 `dropout_p=... if self.training else 0.0` 一样；比例来自配置里的 `attention_dropout` |
| 在注意力权重上丢弃 | [`eager_attention_forward`](https://github.com/huggingface/transformers/blob/v5.21/src/transformers/models/llama/modeling_llama.py#L180-L202) | softmax 之后对注意力权重做 `nn.functional.dropout`，即本章的位置 ①；`LlamaDecoderLayer` 里没有本章的 ② ③ 两处 |
| 提前停止 | [`EarlyStoppingCallback`](https://github.com/huggingface/transformers/blob/v5.21/src/transformers/trainer_callback.py#L711-L784) | `early_stopping_patience` 次评估没有改进就停止训练；配合 `load_best_model_at_end=True` 才会在结束时换回最好的检查点 |
| label smoothing | [`LabelSmoother`](https://github.com/huggingface/transformers/blob/v5.21/src/transformers/trainer_pt_utils.py#L435-L481) | `label_smoothing_factor` 不为 0 时启用；评估指标仍应看普通交叉熵（第 15 章） |

想在本机看源码，可以先 `pip install transformers`，再用 `python -m inspect transformers.models.llama.modeling_llama:LlamaMLP` 这样的命令打印出任意一个类。

<!-- real-model:end -->

## 本章结论：TinyLLM 的选择 {#tinyllm-choice}

TinyLLM 的主线预训练**不加 dropout（`dropout=0`），不用 label smoothing**；AdamW 保留第 12 章的 `weight_decay=0.1`，只作用在矩阵权重上，归一化的权重不衰减。训练时始终同时看训练损失（eval 模式）和验证损失，**按验证损失保留最好的检查点**；最终结果用测试集报告一次。

理由来自本章的两组对照（代理模型、300 步、3 个种子）：

- **只有 300 首诗、过 20 遍时**，不加正则化的测试损失是 5.508；`weight_decay=0.1` 和 label smoothing 都没有可靠的改善（5.484）；`dropout=0.3` 降到 5.253；`weight_decay=3` 最好，5.078，约等于把数据翻一倍（5.142，单种子）；把数据翻两番是 4.831，比任何正则化都好。
- **全部 5419 首、只过一遍时**，不加正则化最好（4.711）；`dropout=0.1` 变差到 4.782，`weight_decay=3` 变差到 4.866。

保留 `weight_decay=0.1` 是为了和第 12 章的基线一致：在学习率 3e-3、几百步的训练里，它的时间尺度是 3333 步，作用很弱，不会拖累学习。这些选择在什么情况下要换：数据有限、要把同一份数据过很多遍，或者在小数据上微调时，先加数据，再按 $1/(\eta\lambda)$ 和训练步数的关系调大 weight decay、试 0.1～0.3 的 dropout，并配合提前停止；每一项都要和“不加”在同一份验证集上比较，用测试集报告。

::: warning 常见误区
- **大模型都这样配，所以照搬。** 正则化要不要加、加多少，取决于数据量和训练遍数。本章同样的 `weight_decay=3`，在 300 首上最好，在全部数据上最差。
- **`weight_decay=0.1` 是一个固定的强度。** 真正决定强度的是 $\eta\lambda$ 和训练步数。学习率 3e-3、300 步时，0.1 几乎不起作用。
- **训练损失很低，说明模型很好。** 300 首诗的训练损失降到 2.65 时，验证损失已经比第 100 步差了 0.8。要看验证损失。
- **用 train 模式下打印的训练损失算泛化差距。** dropout 打开时，这个数带着随机掩码的噪声，偏高。要在 eval 模式下单独测训练集。
- **忘了 `model.eval()`。** 评估和生成时 dropout 还开着，结果偏差、而且每次不同。
- **用验证集挑完超参数，再拿验证损失当最终成绩。** 挑选过的数偏乐观，最终结果用测试集报告，而且只测一次。
:::

## 检查理解

1. 第 1 节里，训练损失在第 100 步到第 300 步之间从 4.34 降到 2.65。这段时间模型在学什么？为什么验证损失反而上升？

   <details><summary>参考答案</summary>

   前 100 步，模型学的主要是所有唐诗共有的规律：常用字、五字一句、标点的位置，这些在验证集上同样成立，所以两条线一起降。之后，它开始记这 300 首诗里具体的字接字关系，也就是背诵。这些记忆在新诗上不成立，而且模型对它们越来越自信，在验证集上猜错时给正确答案的概率越来越低，交叉熵就越来越大。训练损失的下降，全部来自对训练集的记忆。

   </details>

2. 同样是 `weight_decay=0.1`，为什么在本章几乎不起作用？如果要让它起作用，可以改哪些东西？

   <details><summary>参考答案</summary>

   AdamW 每步把权重乘以 $1-\eta\lambda$，起作用的时间尺度约为 $1/(\eta\lambda)$。学习率 3e-3、`weight_decay=0.1` 时是 3333 步，而训练只有 300 步，300 步累计只缩小到 0.914 倍，还来不及把背诵用的权重拉回来。要让它起作用，可以加大 $\lambda$（本章 3 时时间尺度是 111 步）、加大学习率，或者训练得更久；三者一起决定强度。反过来，也说明换了学习率或训练步数，合适的 `weight_decay` 要重新调。

   </details>

3. 有人在训练循环里打印 `loss.item()`，发现加了 `dropout=0.3` 以后，训练损失比验证损失还高，就认为模型“欠拟合，不需要 dropout”。这个推理错在哪里？

   <details><summary>参考答案</summary>

   `loss.item()` 是在 train 模式下算的，dropout 开着，每次随机丢掉 30% 的数，模型是在一个残缺的网络上做预测，损失自然偏高。验证损失是在 eval 模式下测的，用的是完整的网络。两者口径不同，不能直接比。要判断有没有过拟合，应该在 eval 模式下单独测一遍训练集的损失（本章 `evaluate(model, ids[:EVAL_TOKENS])` 的做法），再和验证损失比较。

   </details>

4. 在 300 首诗上，`weight_decay=3` 把测试损失从 5.508 降到 5.078；同样的设置用在全部 5419 首上，却从 4.711 变差到 4.866。怎么解释？如果你的任务是在 2000 首诗上训练 3000 步，你会怎么选正则化？

   <details><summary>参考答案</summary>

   300 首诗过了 20 遍，问题是过拟合，强 weight decay 阻止了权重朝背诵的方向长大，所以有效。全部数据只过一遍，训练和验证损失贴在一起，没有过拟合，瓶颈是学得不够；这时强 weight decay 只会把学到的东西往回拉，于是变差。合适的 weight decay 随数据量增大而减小。

   2000 首、3000 步：每步 1024 个 token，3000 步约 307 万 token；本章 300 首是 15304 个 token，按比例 2000 首约 10 万 token，大约过 30 遍，很可能过拟合。不能直接沿用本章的数，应该先不加正则化训练一次，看验证损失在哪里见底；再用提前停止，并按时间尺度（$1/(\eta\lambda)$ 取训练步数的一个比例）扫几个 weight decay、试 0.1～0.3 的 dropout，每种跑 3 个种子，用验证集挑，用测试集报告。当然，能拿到更多诗，先加数据。

   </details>

## 参考资料

- [PyTorch：`torch.nn.Dropout`](https://docs.pytorch.org/docs/stable/generated/torch.nn.Dropout.html) 与 [`F.scaled_dot_product_attention`](https://docs.pytorch.org/docs/stable/generated/torch.nn.functional.scaled_dot_product_attention.html)（`dropout_p` 参数）
- [PyTorch：`torch.optim.AdamW`](https://docs.pytorch.org/docs/stable/generated/torch.optim.AdamW.html)（解耦的 weight decay）
- [Dropout: A Simple Way to Prevent Neural Networks from Overfitting，Srivastava 等，2014](https://jmlr.org/papers/v15/srivastava14a.html)
- [Decoupled Weight Decay Regularization（AdamW），Loshchilov 与 Hutter，2017](https://arxiv.org/abs/1711.05101)
- [How to set AdamW's weight decay as you scale model and dataset size，Wang 与 Aitchison，2024](https://arxiv.org/abs/2405.13698)（时间尺度 $1/(\eta\lambda)$；最佳 weight decay 随数据量增大而减小）
- [Rethinking the Inception Architecture for Computer Vision，Szegedy 等，2016](https://arxiv.org/abs/1512.00567)（label smoothing 的出处）
- [Deep Learning，Goodfellow、Bengio 与 Courville，第 7 章：正则化](https://www.deeplearningbook.org/contents/regularization.html)（提前停止、参数范数惩罚、dropout 的系统介绍）
- [Drop Dropout on Single-Epoch Language Model Pretraining，Liu 等，2025](https://arxiv.org/abs/2505.24788)（单遍预训练里 dropout 有害）
- [To Repeat or Not To Repeat: Insights from Scaling LLM under Token-Crisis，Xue 等，2023](https://arxiv.org/abs/2305.13230)（多遍训练时的过拟合与 dropout）
- [Scaling Data-Constrained Language Models，Muennighoff 等，2023](https://arxiv.org/abs/2305.16264)（重复数据的收益随遍数递减）
- [LLaMA: Open and Efficient Foundation Language Models，Touvron 等，2023](https://arxiv.org/abs/2302.13971)（预训练用 weight decay 0.1）

正则化决定了模型学什么、不学什么；接下来回到“怎么算得又快又省”：[第 19 章：数值精度与混合精度](./precision.md)。
