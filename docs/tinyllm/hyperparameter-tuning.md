---
title: "第 23 章：超参数与自动化调参"
description: "训练里哪些超参数最要紧、哪些可以放心用默认值？先用 5 个种子量出噪声底线，再逐个排敏感度；在同样的训练预算下比较网格搜索、随机搜索和逐轮淘汰；最后看调参里最常见的两个陷阱：按中间结果挑，以及赢家的成绩偏乐观。"
pageClass: tinyllm-course
---

# 第 23 章：超参数与自动化调参

[课程总览](./index.md) · [上一章](./training-evaluation.md) · [下一章](./scaling-laws.md)

::: tip 本章学习目标
能用同一配置的多个种子量出“噪声底线”，并用它判断一个改动是不是真的有效；能通过“每次只改一个”的扫描给超参数排出敏感度，把预算花在最要紧的几个上；能说清网格搜索、随机搜索、逐轮淘汰各自的适用场合，并避开“按中间结果挑”“把赢家的运气当实力”这两个陷阱。

**前置：** [第 17 章](./learning-rate.md)的代理模型与 WSD，[第 18 章](./regularization.md)的 weight decay 时间尺度，[第 22 章](./training-evaluation.md)的配对比较与评估误差。

**实践方式：** [hyperparameter-tuning.ipynb](/tinyllm/notebooks/hyperparameter-tuning)（也可以直接运行 <a href="/tinyllm/code/hyperparameter-tuning.py" download>hyperparameter-tuning.py</a>），CPU 约两分钟，需要 PyTorch 和 `tokenizers`。
:::

第 16～18 章零散地调过几个超参数：优化器、学习率和调度、weight decay 和 dropout。每一章都用同一套做法：代理模型、固定的 batch 计划、3 个种子、用验证集挑。可是一个真实的训练配置里有十几个超参数，不可能每个都扫一遍。到底该调哪几个？按什么顺序调？调到什么程度就可以停？

本章把前几章的零件放在一起，回答这几个问题。先量一把“尺子”：同一个配置换种子，结果差多少；再用这把尺子给超参数排敏感度；然后在同样的训练预算下比较三种自动化的搜索方法；最后看两个最常见的陷阱。

<TinyLLMMap active="hyperparameter-tuning" />

::: info 本章代码从哪里来
本章所有代码都在一个文件里：<a href="/tinyllm/code/hyperparameter-tuning.py" download>hyperparameter-tuning.py</a>（[在 GitHub 上查看](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/tinyllm/code/hyperparameter-tuning.py)）。下面的代码块都是从这个文件里直接截取的片段，所以单独复制一段可能缺少 `import` 或前面定义的变量；想自己运行，请下载完整文件，`python hyperparameter-tuning.py` 从头跑到尾即可。notebook 版本也由同一个文件生成，可以[在线查看](/tinyllm/notebooks/hyperparameter-tuning)，或[在 Colab 中直接运行](https://colab.research.google.com/github/lewislau86/lewislau86.github.io/blob/master/docs/public/tinyllm/notebooks/hyperparameter-tuning.ipynb)。正文引用的输出来自 torch 2.14.1+cpu、tokenizers 0.23.3。
:::

## 0. 实验对象

模型、数据、评估口径都和[第 17 章](./learning-rate.md)的代理模型相同：

<<< @/public/tinyllm/code/hyperparameter-tuning.py#proxy

本章要训练约 50 次，每次 2～3 秒。和前几章一样，结论只对这个代理模型、这个训练预算成立；哪些规律能搬到大模型上，第 10 节再讲。

## 1. 一次训练：配置是一个字典

把要调的超参数都放进一个字典：峰值学习率、weight decay、warmup 占总步数的比例、Adam 的 $\beta_2$、衰减段占总步数的比例、batch 大小。主线配置 `BASE` 就是第 17 章定下的 WSD（峰值 1e-2）和第 12 章以来的 weight decay 0.1。

<<< @/public/tinyllm/code/hyperparameter-tuning.py#run

两个设计值得注意：

- **token 预算固定。** 主线是 240 步 × 16 段。batch 改成 32，步数就变成 120；改成 8，步数就是 480。这样比较的是“同样多的数据，怎样分成步”，而不是“多训练一会儿”。
- **`Run` 可以分段推进。** `advance(until)` 训练到第 `until` 步；`fork_decay(length)` 从当前状态复制一份，接一小段衰减，测完验证损失就丢掉，原来的训练不受影响。第 5 节的逐轮淘汰要用到它。

## 2. 噪声底线：同一个配置，换 5 个种子

调参就是比较。比较之前，先要知道“什么都不改”时结果会差多少：

<<< @/public/tinyllm/code/hyperparameter-tuning.py#noise

```text
5 个种子的验证损失： 4.7334  4.7581  4.7520  4.7332  4.7125
平均 4.7378，标准差 σ = 0.0180，最大减最小 0.0456
```

同一个配置，只换随机种子，验证损失就在 4.71 到 4.76 之间变动，最大和最小差了 0.046。这个标准差 $\sigma = 0.018$ 就是本章的尺子：**单个种子上，小于 $2\sigma \approx 0.036$ 的差别，不能算作改进。**

[第 22 章](./training-evaluation.md)量过另一种误差：同一个模型，换一批验证诗，验证损失的 95% 区间半宽约 0.019。两种误差差不多大。种子带来的这一种，换更大的验证集也消不掉；要靠多跑几个种子、报告平均和范围。这正是前几章“结论至少 3 个种子”的原因。

## 3. 敏感度：每次只改一个超参数

以主线配置为中心，每次只把一个超参数换成更小或更大的值，其余不动（单个种子，种子 0），看变化有几个 $\sigma$：

<<< @/public/tinyllm/code/hyperparameter-tuning.py#sensitivity

```text
lr      主线 0.01    0.0033 → 4.8204（ +4.8σ）    0.03 → 5.2104（+26.5σ）   最大偏离 26.5σ
batch   主线 16           8 → 4.6892（ -2.5σ）      32 → 5.0272（+16.3σ）   最大偏离 16.3σ
warmup  主线 0.125     0.02 → 4.8563（ +6.8σ）   0.375 → 4.7197（ -0.8σ）   最大偏离  6.8σ
wd      主线 0.1        0.0 → 4.7634（ +1.7σ）     1.0 → 4.8212（ +4.9σ）   最大偏离  4.9σ
beta2   主线 0.999     0.95 → 4.7278（ -0.3σ）    0.99 → 4.7450（ +0.6σ）   最大偏离  0.6σ
decay   主线 0.2        0.1 → 4.7544（ +1.2σ）     0.4 → 4.7400（ +0.4σ）   最大偏离  1.2σ
```

![以主线配置为中心，每次只把一个超参数换成更小（蓝）或更大（橙）的值，单个种子。学习率偏离最大，其次是固定 token 预算下的 batch 大小、过短的 warmup、过大的 weight decay；β2 和衰减段比例的变化都在 ±2σ 的噪声带以内](/tinyllm/figures/hp-sensitivity.svg)

怎么读这张图（灰带是 $\pm 2\sigma$，带子里的变化都算噪声）：

- **学习率最敏感。** 放大 3 倍变差 26.5σ，缩小 3 倍变差 4.8σ。这和[第 17 章](./learning-rate.md)的结论一致：学习率是第一个要调、也最值得花预算的超参数。
- **token 预算固定时，batch 大小很敏感。** batch 8（480 步）比主线好 2.5σ，batch 32（120 步）差了 16σ。同样多的数据，在这个阶段分成更多的小步更划算：这个代理模型的“临界 batch 大小”（[McCandlish 等，2018](https://arxiv.org/abs/1812.06162)）比 16 段还小。下一节会看到，batch 和学习率是绑在一起的。
- **warmup 太短不行，长一点无所谓。** 只 warmup 5 步（2%）变差 6.8σ；warmup 90 步（37.5%）和主线没有区别。这和[第 17 章](./learning-rate.md)“去掉 warmup 变差”是同一回事。
- **weight decay 太大不行，0 和 0.1 差不多。** 1.0 时，衰减的时间尺度 $1/(\eta\lambda)$ 只有 100 步，模型被拉得太狠（[第 18 章](./regularization.md)）；0 和 0.1 的差别在噪声以内。
- **β2 和衰减段比例在这个范围里几乎无所谓。** 全部在 1.2σ 以内。

这张图就是调参预算的分配表：**先把学习率（以及和它绑定的 batch）调好，再看 warmup 和 weight decay；β2、衰减比例用常见的默认值就行。**

“每次只改一个”的扫描有两个局限：它只看主线附近，看不到远处的情况；它也看不到超参数之间的相互作用，换了一个，另一个的最佳值可能跟着变。下一节就是一个例子。

## 4. 耦合：batch 变了，学习率要不要跟着变

上面 batch 32 时，学习率还是 1e-2。[第 17 章](./learning-rate.md)说过，batch 变大时，常拿“学习率放大 $\sqrt{2}$ 倍”当起点。往两个方向都试一下：

<<< @/public/tinyllm/code/hyperparameter-tuning.py#coupling

```text
batch 32，学习率 5.00e-03：验证损失 4.9929（+14.4σ）
batch 32，学习率 1.00e-02：验证损失 5.0272（+16.3σ）
batch 32，学习率 1.41e-02：验证损失 5.0786（+19.2σ）
```

结果和经验方向相反：放大学习率更差，缩小反而好一点。原因是 token 预算固定：batch 32 时只有 120 步，warmup 和衰减都按比例缩短了，大学习率在这么短的训练里来不及“收住”。“batch 加倍、学习率放大 $\sqrt{2}$”假设训练足够长、batch 在临界值以下，这两条在这里都不成立。而且即使学习率调好了，batch 32 仍然比 batch 16 差 14σ：这个阶段，步数比每步的 batch 大小更要紧。

这类耦合到处都是，前几章已经见过两个：

- **峰值学习率和衰减**（[第 17 章](./learning-rate.md)）：加了衰减以后，最佳峰值变大了。
- **学习率、weight decay 和训练步数**（[第 18 章](./regularization.md)）：真正决定衰减强度的是 $\eta\lambda$ 和步数。

应对耦合的一个好办法是**换一组更“互不干扰”的参数来调**。比如 warmup 和衰减写成占总步数的比例（本章就是这样），改总步数时不用跟着改；weight decay 按时间尺度 $1/(\eta\lambda)$ 来想，改学习率时知道该怎么补偿。换不掉的耦合，就只能一起扫。

## 5. 三种搜索方法，同样的预算

手动扫描以后，常常还想“自动”找一个更好的配置。比较三种最常用的方法，每种都只给大约 9 次完整训练的步数。搜索空间是三个维度：学习率、weight decay、$1-\beta_2$，都按对数均匀取：

<<< @/public/tinyllm/code/hyperparameter-tuning.py#space

**网格搜索**：学习率和 weight decay 各取 3 个值，对数等距，一共 9 个组合；$\beta_2$ 只能固定，否则 3 个维度要 27 次。**随机搜索**：9 个随机配置。

<<< @/public/tinyllm/code/hyperparameter-tuning.py#grid-random

```text
网格搜索：9 次 × 240 步，最好 4.7398（lr 5.62e-03  wd 1.00e+00  β2 0.9990）
   试过的学习率： 1.0e-03 5.6e-03 3.2e-02
随机搜索：9 次 × 240 步，最好 4.7145（lr 7.27e-03  wd 5.30e-01  β2 0.9898）
   试过的学习率： 2.3e-03 2.4e-03 2.6e-03 5.0e-03 7.3e-03 1.2e-02 1.4e-02 1.6e-02 1.8e-02
```

网格搜索只试了 3 个学习率，恰好跨过了 1e-2 附近的谷底；随机搜索的 9 个配置有 9 个不同的学习率。这就是随机搜索通常比网格好的原因（[Bergstra 与 Bengio，2012](https://jmlr.org/papers/v13/bergstra12a.html)）：真正要紧的维度往往只有一两个（第 3 节），网格在每个维度上只试几个值，大部分预算都花在了不要紧的维度的组合上；随机搜索在每个维度上的取值都不重复。

**逐轮淘汰**（successive halving，[Jamieson 与 Talwalkar，2016](https://arxiv.org/abs/1502.07943)）换一个思路：与其把每个配置都训练完，不如先多试一些、每个只训练一小段，把明显不好的淘汰掉，剩下的再接着训练。27 个配置先训练到第 32 步，只留最好的三分之一；训练到第 96 步再留三分之一；最后 3 个训练满 240 步。

它的难点是“训练到一半，怎么判断好坏”。WSD 恰好提供了一个办法：峰值阶段的任何一步都可以分叉出一个副本，接一小段衰减再测（[第 17 章](./learning-rate.md)讲过，衰减段会让损失“下台阶”）；原来的训练接着往下走，前面的步数不浪费。

![WSD 的分叉：主干经过 warmup 后一直停在峰值，从三个检查点各接一段线性衰减到 0，得到三个不同预算的训练完成的模型](/tinyllm/figures/wsd-branches.svg)

怎么读这张图（第 17 章已经见过）：主干一直停在峰值上，任何一个检查点都可以复制一份、接一段衰减，得到这个步数下“训完”的模型。逐轮淘汰在每个淘汰点做的就是这件事：分叉、衰减、测验证损失，淘汰差的，好的回到主干上继续训练，分出去的衰减段用完就扔。

<<< @/public/tinyllm/code/hyperparameter-tuning.py#halving

```text
第  32 步：27 个配置，留下 9 个；分叉衰减后的验证损失 5.868 5.919 5.922 5.923 5.955 5.957 5.958 5.958 5.964
第  96 步：9 个配置，留下 3 个；分叉衰减后的验证损失 5.075 5.090 5.130
逐轮淘汰：一共 2205 步（约 9.2 次完整训练），试了 27 个配置，最好 4.7185（lr 1.16e-02  wd 1.57e-02  β2 0.9554）
```

![27 个随机配置先各训练 32 步，按分叉衰减后的验证损失只留最好的 9 个；训练到第 96 步再留 3 个；最后 3 个训练满 240 步，最好的是 4.7185。一共约 9.2 次完整训练的步数](/tinyllm/figures/hp-halving.svg)

怎么读这张图：横轴是训练步数，上方标着每一轮还剩几个配置。在第 32、96 步的淘汰点上，所有还活着的配置都从当前检查点分叉、接一段衰减再测验证损失，只留最好的三分之一继续在峰值上训练。大部分配置只训练了 32 步就被淘汰，预算集中给了少数好的配置。

同样的预算，逐轮淘汰试了 27 个配置，是另外两种的 3 倍。Hyperband（[Li 等，2018](https://arxiv.org/abs/1603.06560)）在它的基础上同时跑几组“淘汰得快慢不同”的版本，ASHA（[Li 等，2020](https://arxiv.org/abs/1810.05934)）让它能在很多台机器上异步进行。

三种方法的最好结果：网格 4.7398，随机 4.7145，逐轮淘汰 4.7185。看起来随机和逐轮淘汰都比主线（种子 0 是 4.7334）好了约 1σ。真的好吗？

![左：网格搜索只试了 3 个学习率，错过了 1e-2 附近的谷底；随机搜索的 9 个配置覆盖了 9 个不同的学习率。右：各方法挑出的配置换两个新种子重训，随机搜索的赢家基本站住，逐轮淘汰的赢家比主线还差；灰带是主线 5 个种子的平均 ±2σ](/tinyllm/figures/hp-search.svg)

怎么读这张图：左半是本节的搜索过程，横轴是峰值学习率，每个点是一次完整训练；网格只有 3 个不同的学习率，随机搜索有 9 个。右半提前给出了第 7 节的复核：红色菱形是挑中时的成绩，蓝点是换两个新种子重训的结果，灰带是主线的噪声范围。先记住“挑出来的最好值，换个种子不一定还是最好”，第 6、7 节解释为什么。

## 6. 陷阱一：按中间的损失排名

逐轮淘汰的前提，是“训练到一半时的好坏”能预示“训练完的好坏”。这个前提有多可靠？网格和随机搜索的 18 次训练，都在第 96 步（还在峰值阶段、没有衰减）测过一次验证损失：

<<< @/public/tinyllm/code/hyperparameter-tuning.py#peek-trap

```text
18 次训练：第 96 步的验证损失和最终验证损失的秩相关 0.69
按第 96 步挑：lr 1.20e-02  wd 4.97e-01  β2 0.9767，最终 4.7546
按最终挑：    lr 7.27e-03  wd 5.30e-01  β2 0.9898，最终 4.7145
逐轮淘汰第一轮：按“分叉衰减后”和按“不衰减直接测”各留 9 个，相同的有 7 个；最终最好的配置在“不衰减直接测”留下的名单里
```

![网格和随机搜索的 18 次训练：横轴是第 96 步（峰值阶段）的验证损失，纵轴是最终验证损失，颜色是学习率。两者大体一致，但不完全一致；按第 96 步挑中的配置最终是 4.7546，按最终挑中的是 4.7145](/tinyllm/figures/hp-peek.svg)

秩相关 0.69：大体一致，但不可靠。按第 96 步挑出来的配置，最终比真正最好的差了 0.04（2.2σ）。中间结果偏向某一类配置：峰值阶段学习率越大，损失在谷底附近震荡得越厉害，看起来越差，可它们在衰减段“下台阶”也最多（[第 17 章](./learning-rate.md)）。只看峰值阶段的损失，就会系统性地低估大学习率。

“分叉衰减再测”就是为了减轻这个偏差。在这次实验里，它和“不衰减直接测”在第一轮只有 2 个配置不同，最终最好的那个两份名单里都有，所以没有造成差别；但两者的分歧会随学习率范围变宽、训练变长而变大。用逐轮淘汰时，评估的口径要尽量接近最终的口径。

## 7. 陷阱二：赢家的成绩偏乐观

每种方法挑出的赢家，都是在**种子 0** 上表现最好的那一个。可是第 2 节说过，同一个配置换种子，结果就会差 0.02 左右。从一堆配置里挑最好的，挑中的往往是“配置不错、种子 0 又恰好走运”的那个。把三个赢家各换两个新种子重新训练，再把挑中的那个模型在测试集上测一次：

<<< @/public/tinyllm/code/hyperparameter-tuning.py#winners-curse

```text
网格   挑中时 4.7398   新种子 4.7354 4.7402（平均 4.7378）   测试集 4.7272
随机   挑中时 4.7145   新种子 4.7134 4.7276（平均 4.7205）   测试集 4.7030
逐轮淘汰 挑中时 4.7185   新种子 4.7611 4.7708（平均 4.7660）   测试集 4.6998
主线配置：5 个种子平均 4.7378，种子 0 的测试集 4.7173
```

- **逐轮淘汰的赢家，换了种子就不行了。** 挑中时 4.7185，新种子平均 4.7660，比主线的平均（4.7378）还差。它试的配置最多（27 个），挑中“幸运种子”的机会也最大。
- **随机搜索的赢家基本站住了。** 新种子平均 4.7205，比主线好 0.017，约 1σ。要确认它真的更好，还要更多种子。
- **网格搜索的赢家就是主线的水平。**

还有一个容易混淆的地方：逐轮淘汰挑中的那个**模型**，在测试集上反而是三个里最好的（4.6998）。这并不矛盾。“这个模型好不好”和“这个配置好不好”是两个问题：测试集回答前者，它告诉我们种子 0 训练出的这个模型确实不错，不是只在验证集上碰巧；换种子重训回答后者，它告诉我们这个配置不能稳定地训练出好模型。调参要回答的是后者。

（测试集上的数普遍比验证集低约 0.02，是因为这批测试诗本身稍容易一些，[第 18 章](./regularization.md)也见过；比较时只在测试集内部比。）

所以本章的最终答案是：**在这个代理模型上，三种搜索方法都没有找到可靠地比主线更好的配置。** 第 17 章靠几次有针对性的对照定下的主线，已经在谷底附近。这并不是说自动搜索没用，而是说：搜索结果要用多个种子复核；主线已经调得不错时，剩下的改进往往在噪声以内。

## 8. 基于模型的搜索与边训练边调

随机搜索每一次都“不看前面的结果”。**基于模型的搜索**则用已经试过的结果拟合一个模型，预测哪里更可能好，下一次就去那里试：

- **高斯过程**（[Snoek 等，2012](https://arxiv.org/abs/1206.2944)）直接拟合“配置 → 验证损失”的函数，并给出不确定度，在“预测好的地方”和“还没试过的地方”之间权衡。
- **TPE**（[Bergstra 等，2011](https://papers.nips.cc/paper/4443-algorithms-for-hyper-parameter-optimization)）把试过的配置分成“好的一批”和“其余”，分别估计它们在每个维度上的分布，下一次在“好的一批更集中”的地方取值。[Optuna](https://arxiv.org/abs/1907.10902) 的默认算法就是它。

这类方法在试验次数较多（几十到几百次）时明显优于随机搜索；只有十来次时，差别往往被噪声淹没。它们也可以和逐轮淘汰组合起来，用模型挑配置、用淘汰省预算。

**PBT**（Population Based Training，[Jaderberg 等，2017](https://arxiv.org/abs/1711.09846)）走得更远：一群模型同时训练，每隔一段时间，差的模型复制好的模型的参数，并在它的超参数上做一点扰动，接着训练。超参数因此可以随训练变化，相当于自动找到一条“调度”。

## 9. 调参的顺序

把本章和前几章的结论整理成一个顺序。思路来自 Google 的调参手册（[Godbole 等，2023](https://github.com/google-research/tuning_playbook)）：每一轮只回答一个问题，把超参数分成三类：

- **要研究的**：这一轮想回答的问题，比如“WSD 和余弦哪个好”。
- **需要跟着调的**：和要研究的超参数耦合、不调就比不公平的，比如比较调度时的峰值学习率（第 17 章）。
- **可以固定的**：在合理范围内影响不大的，比如本章的 $\beta_2$、衰减比例。

一个实用的顺序：

| 步骤 | 做什么 | 本课在哪里做过 |
| --- | --- | --- |
| 1 | 先确认代码没有 bug：初始损失、因果性、单 batch 过拟合 | [第 22 章](./training-evaluation.md) |
| 2 | 量噪声底线：主线配置跑 3～5 个种子 | 本章第 2 节 |
| 3 | 扫学习率（对数网格，3 倍一档），配上调度 | [第 17 章](./learning-rate.md) |
| 4 | 确定 batch 和训练步数（预算），再回头微调学习率 | 本章第 3、4 节 |
| 5 | 看 warmup、weight decay 是否在合理范围 | 本章第 3 节，[第 18 章](./regularization.md) |
| 6 | 预算还有余，再用随机搜索或逐轮淘汰在小范围里找 | 本章第 5 节 |
| 7 | 赢家用新种子复核，最后在测试集上报告一次 | 本章第 7 节 |

## 10. 从小模型到大模型

本章所有的数字都只属于这个 16 万参数、240 步的代理模型。到了大模型上，什么能搬，什么不能？

- **能搬的是规律**：学习率最敏感，warmup 不能太短，衰减要和峰值一起调，搜索结果要用多个种子复核。
- **不能直接搬的是数值**。模型变宽，标准参数化下的最佳学习率会变小（[第 17 章](./learning-rate.md)）；数据变多，最佳 weight decay 会变小（[Wang 与 Aitchison，2024](https://arxiv.org/abs/2405.13698)，[第 18 章](./regularization.md)也看到了）；算力变大，最佳 batch 变大、最佳学习率缓慢变小，DeepSeek 用一系列小规模实验把这两者拟合成了随算力变化的幂律，再外推到 7B 和 67B 的模型（[DeepSeek-AI，2024](https://arxiv.org/abs/2401.02954)）。
- **让数值也能搬**：μP 调整了初始化和每层的学习率缩放，让最佳学习率在不同宽度之间基本不变，于是可以在小模型上调好，直接用到大模型上（[Yang 等，2022](https://arxiv.org/abs/2203.03466)）；MiniCPM 把这种做法叫作在小模型上做“风洞实验”（[Hu 等，2024](https://arxiv.org/abs/2404.06395)）。这是[第 25 章](./large-model-stability.md)的内容。

## 动手实验

1. **用 Optuna 跑 TPE。** `pip install optuna`，用 `optuna.create_study(direction="minimize")` 在本章的搜索空间里跑 9 次，和随机搜索比较。再跑 30 次，差别变大了吗？
2. **把种子放进比较里。** 第 5 节的每个配置都用 3 个种子，预算只够 3 个配置。这时随机搜索还能找到比主线好的配置吗？和“9 个配置 × 1 个种子”比，哪种分配更可靠？
3. **加宽学习率范围。** 把搜索空间的学习率上限改成 1e-1，重做第 6 节。“第 96 步”和“最终”的秩相关变高还是变低？“分叉衰减”和“不衰减直接测”的分歧变大了吗？
4. **batch 和步数分开看。** 第 3 节的 batch 32 只有 120 步。把 token 预算加倍（batch 32、240 步），和 batch 16、240 步比较。这时更大的 batch 还吃亏吗？

<!-- real-model:start -->

## 在真实模型里

transformers 的 Trainer 自带一个超参数搜索的入口，具体的搜索算法交给 Optuna、Ray Tune 等后端。下表的链接都指向 Hugging Face transformers 的固定版本 `v5.21`，精确到行。读代码时可以先跳过缓存、掩码、并行这些工程细节，只看和本章对应的那几行。

| 本章的零件 | 真实代码 | 对照要点 |
| --- | --- | --- |
| 搜索入口 | [`Trainer.hyperparameter_search`](https://github.com/huggingface/transformers/blob/v5.21/src/transformers/trainer.py#L4468-L4547) | 每个 trial 用 `model_init` 重新造一个模型，按 `direction` 取验证指标的最小或最大；算法（TPE、随机、ASHA 等）由所选的后端决定 |
| 默认的搜索空间 | [`default_hp_space_optuna`](https://github.com/huggingface/transformers/blob/v5.21/src/transformers/trainer_utils.py#L452-L462) | 看一下默认都搜哪些量、范围多大；如果随机种子也在里面，挑出来的可能只是一次好运气（本章第 7 节） |

想在本机看源码，可以先 `pip install transformers`，再用 `python -m inspect transformers.models.llama.modeling_llama:LlamaMLP` 这样的命令打印出任意一个类。

<!-- real-model:end -->

## 本章结论：TinyLLM 的选择 {#tinyllm-choice}

TinyLLM 调参时先用主线配置跑 3～5 个种子量出**噪声底线**（本章代理模型上 $\sigma = 0.018$），小于约 $2\sigma$ 的差别不算改进。预算按敏感度分配：**学习率（连同 batch 和训练步数）最先调**，其次确认 warmup 不太短、weight decay 不太大，$\beta_2$ 和衰减比例用常见的默认值。需要自动搜索时用**随机搜索**；配置多、预算紧时用**逐轮淘汰**，在 WSD 的峰值阶段分叉衰减后再比较。**任何搜索的赢家都要换新种子复核**，最后在测试集上报告一次。

理由来自本章的实验（代理模型、240 步）：敏感度扫描里，学习率偏离 26.5σ、batch 16.3σ、过短的 warmup 6.8σ、过大的 weight decay 4.9σ，$\beta_2$ 和衰减比例都在 1.2σ 以内；同样约 9 次训练的预算，随机搜索（4.7145）和逐轮淘汰（4.7185）都好于网格（4.7398），但赢家换种子复核后，随机搜索的平均是 4.7205，只比主线的 4.7378 好约 1σ；逐轮淘汰的平均变成 4.7660，反而差了约 1.6σ。两者都没有可靠地更好。主线配置保持第 17 章的 WSD、峰值 1e-2 不变。

这些选择在什么情况下要换：试验次数能到几十次以上时，用 TPE 等基于模型的方法；模型放大以后，数值要重新扫，或者改用 μP 这类能迁移学习率的参数化（第 25 章）；超参数之间耦合很强时，换一组更互不干扰的参数来调，或者把它们一起扫。

::: warning 常见误区
- **单个种子上好了一点，就是改进。** 本章同一个配置换种子就差 0.046；小于约 2σ 的差别要多跑种子才能下结论。
- **网格搜索更系统、更可靠。** 要紧的维度只有一两个时，网格在这些维度上只试几个值，很容易跨过谷底；同样的预算，随机搜索试到的值多得多。
- **经验公式可以直接用。** “batch 加倍、学习率放大 √2”在本章的设定里方向都是反的。经验公式只是起点，要扫。
- **训练到一半的损失能代表最终结果。** 峰值阶段的损失会低估大学习率；本章按第 96 步挑，比真正最好的差了 2.2σ。
- **搜索挑出的最好配置就是最好的。** 它往往还沾了种子的光；逐轮淘汰的赢家换了种子，比主线还差。
- **模型在测试集上好，配置就好。** 测试集说的是“这个模型”好不好；“这个配置”好不好，要换种子重训才知道。
:::

## 检查理解

1. 为什么要先量噪声底线？本章的 σ = 0.018 是怎么用来判断第 3 节各项变化的？

   <details><summary>参考答案</summary>

   不知道“什么都不改”时结果会波动多少，就无法判断一个变化是改进还是运气。本章把主线配置跑了 5 个种子，标准差 0.018；第 3 节把每个改动造成的变化除以 σ，在 ±2σ 以内的（β2、衰减比例、weight decay 改成 0、warmup 加长）都当作“无法和噪声区分”，远超 2σ 的（学习率、batch、过短的 warmup、过大的 weight decay）才算真的敏感。

   </details>

2. 同样 9 次训练，为什么随机搜索比网格搜索更容易找到好的学习率？在什么情况下网格反而合适？

   <details><summary>参考答案</summary>

   网格在每个维度上只取 3 个值，9 次训练里学习率只有 3 种，其余 6 次都花在 weight decay 的不同组合上；本章的 3 个学习率恰好跨过了 1e-2 附近的谷底。随机搜索每次都取一个新的学习率，9 次训练试了 9 种。当真正要紧的维度只有一两个、而你又不知道是哪几个时，随机搜索更划算。如果只有一个维度、或者确实需要在两个维度上系统地看相互作用（比如画学习率 × weight decay 的热图），网格更直观。

   </details>

3. 逐轮淘汰的赢家在测试集上是 4.6998，三者里最好，换新种子重训却平均 4.7660，比主线还差。这两件事矛盾吗？调参时应该相信哪一个？

   <details><summary>参考答案</summary>

   不矛盾，它们回答的是不同的问题。测试集上的 4.6998 说明种子 0 训练出来的那个模型确实不错，不只是在验证集上碰巧；换种子重训的 4.7660 说明这个配置不能稳定地训练出好模型，种子 0 的好结果有很大的运气成分。调参要选的是“配置”，以后会用它重新训练，所以应该相信换种子重训的结果。它试了 27 个配置，挑中幸运种子的机会也最大。

   </details>

4. 用逐轮淘汰时，为什么不直接比较峰值阶段的验证损失，而要先分叉出一段衰减再测？

   <details><summary>参考答案</summary>

   WSD 的峰值阶段，学习率越大，模型在谷底附近震荡得越厉害，损失看起来越高；可这些配置在衰减段“下台阶”也最多，最终往往更好。直接比峰值阶段的损失，会系统性地低估大学习率，把好配置淘汰掉。本章 18 次训练里，第 96 步和最终损失的秩相关只有 0.69，按第 96 步挑出的配置最终差了 2.2σ。分叉出一小段衰减再测，让中间评估的口径更接近最终的口径；原来的训练接着在峰值阶段往下走，不浪费前面的步数。

   </details>

## 参考资料

经验与方法论：

- [Deep Learning Tuning Playbook，Godbole 等（Google Research），2023](https://github.com/google-research/tuning_playbook)（调参的流程与预算分配）
- [A Recipe for Training Neural Networks，Karpathy，2019](https://karpathy.github.io/2019/04/25/recipe/)
- [Practical Recommendations for Gradient-Based Training of Deep Architectures，Bengio，2012](https://arxiv.org/abs/1206.5533)

搜索算法：

- [Random Search for Hyper-Parameter Optimization，Bergstra 与 Bengio，2012](https://jmlr.org/papers/v13/bergstra12a.html)（随机搜索为什么常比网格好）
- [Algorithms for Hyper-Parameter Optimization，Bergstra 等，2011](https://papers.nips.cc/paper/4443-algorithms-for-hyper-parameter-optimization)（TPE）
- [Practical Bayesian Optimization of Machine Learning Algorithms，Snoek 等，2012](https://arxiv.org/abs/1206.2944)（高斯过程）
- [Non-stochastic Best Arm Identification and Hyperparameter Optimization，Jamieson 与 Talwalkar，2016](https://arxiv.org/abs/1502.07943)（successive halving）
- [Hyperband: A Novel Bandit-Based Approach to Hyperparameter Optimization，Li 等，2018](https://arxiv.org/abs/1603.06560)
- [A System for Massively Parallel Hyperparameter Tuning，Li 等，2020](https://arxiv.org/abs/1810.05934)（ASHA）
- [Population Based Training of Neural Networks，Jaderberg 等，2017](https://arxiv.org/abs/1711.09846)
- [Optuna: A Next-generation Hyperparameter Optimization Framework，Akiba 等，2019](https://arxiv.org/abs/1907.10902)

语言模型的超参数与规模：

- [DeepSeek LLM: Scaling Open-Source Language Models with Longtermism，DeepSeek-AI，2024](https://arxiv.org/abs/2401.02954)（最佳学习率与 batch 大小随算力的幂律）
- [MiniCPM: Unveiling the Potential of Small Language Models with Scalable Training Strategies，Hu 等，2024](https://arxiv.org/abs/2404.06395)（用小模型做“风洞实验”）
- [Tensor Programs V: Tuning Large Neural Networks via Zero-Shot Hyperparameter Transfer，Yang 等，2022](https://arxiv.org/abs/2203.03466)（μP）
- [How to set AdamW's weight decay as you scale model and dataset size，Wang 与 Aitchison，2024](https://arxiv.org/abs/2405.13698)（weight decay 的时间尺度）
- [An Empirical Model of Large-Batch Training，McCandlish 等，2018](https://arxiv.org/abs/1812.06162)（临界 batch 大小）

调参回答的是“给定规模，怎么训”。下一步要问“规模本身怎么定”：同样的算力，模型该多大、该训多少 token？[第 24 章：缩放定律与算力预算](./scaling-laws.md)。小模型上调好的数值怎样搬到大模型上、模型变深变宽以后又会出现哪些不稳定，见[第 25 章：大规模训练稳定性](./large-model-stability.md)。
