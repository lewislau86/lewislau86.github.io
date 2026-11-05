---
title: "第 17 章：学习率策略"
description: "第 12 章的学习率固定为 3e-3，第 13 章换成了先升后降的 lr_at。用 17 次对照训练回答：固定学习率取多大、衰减有没有用、峰值要不要跟着调、warmup 起什么作用，以及 WSD 和余弦怎么选。"
pageClass: tinyllm-course
---

# 第 17 章：学习率策略

[课程总览](./index.md) · [上一章](./optimizers.md) · [下一章](./regularization.md)

::: tip 本章学习目标
能把学习率调度写成“给步数、返回学习率”的函数，并在训练循环里每个优化器步之前设置它；能说清 warmup、余弦衰减、WSD、线性衰减各自的形状和用途；能用多种子对照判断一个调度是否真的更好，并理解为什么“加衰减”和“提高峰值”要一起调。

**前置：** [第 12 章](./tinyllm-model.md)的基线与评估口径，[第 16 章](./optimizers.md)的 AdamW；[第 13 章](./gpu-training.md)的 `lr_at` 可以对照着看。

**实践方式：** [learning-rate.ipynb](/tinyllm/notebooks/learning-rate)（也可以直接运行 <a href="/tinyllm/code/learning-rate.py" download>learning-rate.py</a>），CPU 约两分钟，需要 PyTorch 和 `tokenizers`。
:::

<TinyLLMMap active="learning-rate" />

## 问题：3e-3 是怎么来的，要不要变

[第 12 章](./tinyllm-model.md)的基线用 AdamW，学习率从头到尾固定为 3e-3。[第 16 章](./optimizers.md)讲了优化器怎样决定每一步往哪走、各方向走多远，但“整体步子迈多大”这个数还是我们自己给的。[第 13 章](./gpu-training.md)把模型搬上 GPU 时，悄悄换了一种做法：

<<< @/public/tinyllm/code/gpu-training.py#lr-at

学习率先从接近 0 线性升上去，再沿余弦曲线降到峰值的 10%。为什么要这样？固定的 3e-3 不行吗？升多久、峰值取多大、降到哪里？本章用一组对照实验来回答。

::: info 本章代码从哪里来
本章所有代码都在一个文件里：<a href="/tinyllm/code/learning-rate.py" download>learning-rate.py</a>（[在 GitHub 上查看](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/tinyllm/code/learning-rate.py)）。下面的代码块都是从这个文件里直接截取的片段，所以单独复制一段可能缺少 `import` 或前面定义的变量；想自己运行，请下载完整文件，`python learning-rate.py` 从头跑到尾即可。notebook 版本也由同一个文件生成，可以[在线查看](/tinyllm/notebooks/learning-rate)，或[在 Colab 中直接运行](https://colab.research.google.com/github/lewislau86/lewislau86.github.io/blob/master/docs/public/tinyllm/notebooks/learning-rate.ipynb)。正文引用的输出来自 torch 2.14.1+cpu、tokenizers 0.23.3。
:::

## 0. 实验对象：一个缩小的代理模型

学习率的问题只能靠训练来回答，而且要训练很多次：几个学习率、几种调度，每种还要 3 个种子。第 12 章的原尺寸模型在 CPU 上训练一次要一分半，十几次就是半个小时。所以本章的模型代码、数据划分、评估口径都从第 12 章原样复制，只把三个尺寸缩小：

<<< @/public/tinyllm/code/learning-rate.py#proxy

```text
TinyConfig(vocab_size=1024, d_model=64, n_layers=2, n_heads=4, context=64, rope_base=10000.0)
训练流 296250 个 token；验证流 15892 个 token；参数 163904
```

16 万参数，每步 16 段、每段 64 个 token，训练 240 步，一次约 8 秒。词表从 4096 换成了 1024，同一段文字切出的 token 更多，**所以本章的损失不能和第 12 章的 5.579 直接比**，只在本章内部比较。

这样做的代价是：结论来自一个小模型、一个很短的训练预算。小模型上找到的最佳学习率，不能直接搬到大模型上用（第 7 节会讲为什么）；但“哪些因素会影响结果、该怎么比较”这类规律，在小模型上同样看得清楚。

训练循环和第 12 章一样，只多了一行：每个优化器步之前，按 `schedule(step)` 设置学习率。batch 计划由单独的随机数生成器排好，所有对照共用，`seed` 只决定初始参数：

<<< @/public/tinyllm/code/learning-rate.py#run

## 1. 先扫一遍固定学习率

不加任何调度，学习率取 1e-3、3e-3、1e-2 三个值，各训练一次。先猜一下：哪个最好？

<<< @/public/tinyllm/code/learning-rate.py#sweep

```text
固定 1e-03：最终验证损失 5.074
固定 3e-03：最终验证损失 4.797
固定 1e-02：最终验证损失 4.944
每次训练约 8.3 秒
```

3e-3 最好，两边都更差，形成一个 U 形。学习率太小，240 步走不了多远，损失还在高处；太大，每一步都迈过了头，在谷底附近来回震荡，降不下去。第 12 章选的 3e-3，在这个代理模型上恰好也是三者里最好的。

这里只跑了一个种子，用来看大致的范围。真正下结论的对比在第 3 节，每种设置 3 个种子。

## 2. 调度的几种形状

“学习率调度”就是让学习率随步数变化。最常见的几种，都可以写成“给步数、返回学习率”的小函数：

<<< @/public/tinyllm/code/learning-rate.py#schedules

```text
固定          0步 0.0100   15步 0.0100   29步 0.0100  120步 0.0100  191步 0.0100  215步 0.0100  239步 0.0100
warmup+余弦   0步 0.0003   15步 0.0053   29步 0.0100  120步 0.0065  191步 0.0022  215步 0.0013  239步 0.0010
WSD         0步 0.0003   15步 0.0053   29步 0.0100  120步 0.0100  191步 0.0100  215步 0.0052  239步 0.0002
warmup+线性   0步 0.0003   15步 0.0053   29步 0.0100  120步 0.0057  191步 0.0023  215步 0.0012  239步 0.0000
```

![四种学习率调度的形状：峰值都是 1e-2、共 240 步；固定学习率是一条水平线；另外三种都先用 30 步从接近 0 线性升到峰值；余弦随后平滑降到峰值的 10%，线性一路降到 0，WSD 保持峰值直到最后 20% 的步数才线性降到 0](/tinyllm/figures/lr-schedules.svg)

怎么读这张图：三种调度的前 30 步完全一样，都是 **warmup**，从接近 0 线性升到峰值。之后各走各的：

- **warmup + 余弦**（第 13 章的 `lr_at`）：沿半个余弦周期平滑下降，开头降得慢、中间快、结尾又慢，停在峰值的 10%。
- **warmup + 线性**：直线降到 0。
- **WSD**（warmup-stable-decay）：升上去以后**保持**峰值，直到最后 20% 的步数才快速降到 0。它是近两年大模型预训练里常见的做法（[Hu 等，2024](https://arxiv.org/abs/2404.06395)）。

PyTorch 自带的 `torch.optim.lr_scheduler.LambdaLR` 做的是同一件事：每次调用 `scheduler.step()`，把学习率设成“初始学习率 × 函数值”。核对一下两种写法给出的学习率完全一样：

<<< @/public/tinyllm/code/learning-rate.py#lambda-lr

```text
和 wsd() 的最大差： 8.673617379884035e-19
```

用调度器时有两个常见的坑。第一，`scheduler.step()` 要在 `optimizer.step()` **之后**调用，每个优化器步一次；用了梯度累积（[第 13 章](./gpu-training.md)）时，是每次真正更新参数才调一次，不是每个 micro-batch 调一次。第二，余弦和线性衰减都要事先知道总步数，训练中途改总步数，整条曲线就变了。本章自己写函数、每步直接设置 `group["lr"]`，两种写法等价，选一种用就好。

## 3. 对照：衰减本身有用吗？

现在可以做第一个对照了。第 1 节说 3e-3 是最好的固定学习率。直觉上，训练后期把学习率降下来，让模型在谷底附近走得更稳，损失应该更低。那么在 3e-3 上加一个 warmup + 余弦，会更好吗？

每种设置都训练 3 个种子（0、1、2），用同一份 batch 计划：

<<< @/public/tinyllm/code/learning-rate.py#compare

```text
固定 3e-3            平均 4.805  范围 4.797～4.810
warmup+余弦，峰值 3e-3  平均 4.987  范围 4.970～5.014
warmup+余弦，峰值 1e-2  平均 4.801  范围 4.788～4.821
WSD，峰值 1e-2        平均 4.748  范围 4.733～4.757
```

![左：固定学习率 1e-3、3e-3、1e-2 各训练一次，3e-3 最好，两边都更差。右：每种设置 3 个种子。在 3e-3 上加 warmup+余弦反而更差（4.987）；峰值提到 1e-2 后余弦追平固定 3e-3（4.801 对 4.805），WSD 最好（4.748），去掉 warmup 的 WSD 变差（4.884）](/tinyllm/figures/lr-compare.svg)

结果和直觉相反。一行一行看：

- **在 3e-3 上加余弦，反而差了不少**（4.987 对 4.805，3 个种子的范围完全不重叠）。原因是这个预算太短：240 步结束时，模型还在快速学习的阶段，远没到“在谷底附近震荡”的时候。余弦从第 30 步就开始降，后半段的学习率只有 3e-3 的一小部分，等于白白少走了很多路。
- **把峰值提到 1e-2，余弦就追平了最好的固定学习率**（4.801 对 4.805，范围重叠，算打平）。第 1 节里，固定 1e-2 太大了（4.944）；但配上衰减以后，前期用大步子快速下降，后期步子变小、不再震荡，大学习率的好处保住了，坏处被衰减抵消了。
- **WSD 最好**（4.748，范围 4.733～4.757，和其他三种都不重叠）。它在峰值上停留得更久，多数时间都在用大步子前进，只在最后 20% 快速降下来。

这组对照最重要的结论是：**衰减和峰值要一起调**。“在现有的学习率上加个调度”不一定有用，甚至可能变差；加了衰减以后，最佳峰值通常会变大。比较两种调度时，各自都要配上自己合适的峰值，否则比的只是“哪种调度恰好适合这个峰值”。

实验的边界：代理模型、240 步、每种设置 3 个种子；峰值只试了 3e-3 和 1e-2 两个值，没有为每种调度单独扫出最佳峰值。所以“WSD 比余弦好”只在这个设定下成立。更系统的比较（更大的模型、更长的训练）发现，WSD 配上合适长度的衰减段，一般能做到和余弦相当（[Hägele 等，2024](https://arxiv.org/abs/2405.18392)）；两者的主要区别在第 5 节讲的使用方式上。

## 4. 对照：去掉 warmup

warmup 有什么用？同样是峰值 1e-2 的 WSD，把 warmup 从 30 步改成 1 步，也就是第一步就用满学习率：

<<< @/public/tinyllm/code/learning-rate.py#warmup

```text
无 warmup：平均 4.884  范围 4.836～4.915
有 warmup（种子 0）前 30 步训练损失：第 1 步 7.43，第 10 步 6.47，第 30 步 6.05
无 warmup（种子 0）前 30 步训练损失：第 1 步 7.43，第 10 步 6.09，第 30 步 5.94
```

![峰值 1e-2 的 WSD：去掉 warmup 后，前一百步左右的训练损失反而更低；大约第 120 步两条线交叉，之后有 warmup 的一路领先，最终验证损失也更低](/tinyllm/figures/lr-warmup.svg)

去掉 warmup，最终验证损失从 4.748 变成 4.884，3 个种子的范围不重叠。有意思的是开头：**没有 warmup 的反而降得更快**，第 10 步就到了 6.09，有 warmup 的还在 6.47。它一上来就用大步子，前期当然快。但大约第 120 步，两条线交叉了，之后有 warmup 的一直领先。

为什么开头冲得快，最后反而差？一个常见的解释和 Adam 有关（[第 16 章](./optimizers.md)）：Adam 用梯度平方的滑动平均来决定每个参数的步长，训练刚开始时，这个平均只见过几个 batch，估得很不准，个别参数会被迈出很大的一步（[Liu 等，2020](https://arxiv.org/abs/1908.03265)）。再加上初始参数是随机的，前几步的梯度方向本身也不可靠。这时候大步子会把参数推到一个不太好的区域，后面要花很多步才能找回来，有时就再也找不回来了。warmup 的作用是在这段“看不清路”的时间里先走小步，等优化器的状态和模型都稳定一些，再放开步子。

warmup 要多长？没有通用的答案。本章用了 30 步，约占总步数的 12%。大模型预训练常用几百到几千步，占总步数的比例很小（第 13 章的 GPU 配置是 6000 步里的 300 步）。warmup 太长也有代价：这段时间学习率偏小，等于浪费了预算。训练很短时尤其要注意这一点。

## 5. WSD 和余弦怎么选

两种调度的区别，在损失曲线上看得最清楚。把种子 0 的验证损失每 30 步打印一次：

<<< @/public/tinyllm/code/learning-rate.py#curves

```text
步数     30     60     90    120    150    180    210    240
固定 3e-3  6.00   5.78   5.30   5.13   5.00   4.92   4.84   4.80
余弦 1e-2  6.05   5.56   5.26   5.10   4.97   4.89   4.83   4.80
WSD 1e-2 6.05   5.56   5.28   5.12   4.98   4.92   4.82   4.73
```

![上：种子 0 的验证损失，每 30 步一次。WSD 在峰值 1e-2 保持时和余弦差不多，进入最后 20% 的衰减段后从 4.92 降到 4.73，一下拉开差距；固定 3e-3 一直平稳下降。下：对应的学习率](/tinyllm/figures/lr-curves.svg)

怎么读这张图：

- **前 180 步，WSD 并不占优。** 它一直在峰值 1e-2 上，第 180 步时损失 4.92，比余弦的 4.89 还略高。大学习率下，模型在谷底附近来回震荡，损失降不下去。
- **最后 20% 的衰减段，WSD 一下拉开了差距。** 学习率从 1e-2 降到 0，损失从 4.92 掉到 4.73，比前面任何一段 60 步都掉得多。学习率一降，原来在谷壁之间来回弹的参数，就落进了谷底。很多大模型的训练日志里，都能看到这种“学习率一降，损失就下一个台阶”的现象。
- **余弦的下降是平滑的。** 它从一开始就在慢慢降学习率，没有明显的台阶。

这个“下台阶”带来了 WSD 最大的实际好处：**不用事先定死总步数**。余弦的形状取决于总步数，训练到一半想延长，整条曲线都要重画，前面的检查点也就不在新曲线上了。WSD 的大部分时间都在峰值上，可以从峰值阶段的任何一个检查点出发，接一段衰减，就得到一个“训练完成”的模型；想多训练，就从衰减之前的检查点接着在峰值上跑。同一次训练可以产出好几个不同预算的模型，这正是 MiniCPM 提出它的动机（[Hu 等，2024](https://arxiv.org/abs/2404.06395)）。

余弦的好处是简单、被研究得透：总步数确定、只训练一次时，它是一个可靠的默认选择。Chinchilla 的实验也提醒过，余弦的周期要和实际训练步数对齐，周期设得比训练长，结果会变差（[Hoffmann 等，2022](https://arxiv.org/abs/2203.15556)）。

## 6. 读学习率相关的训练曲线

把前面看到的现象整理一下，训练时看到下面这些曲线，可以先怀疑学习率：

| 现象 | 可能的原因 | 先试什么 |
| --- | --- | --- |
| 损失降得很慢，几百步后还很高 | 学习率太小，或衰减开始得太早 | 提高峰值；推迟或缩短衰减 |
| 损失早早停在一个平台上，抖动明显 | 学习率太大，在谷底附近震荡 | 加衰减；或降低峰值 |
| 训练初期损失突然飙升，甚至出现 `nan` | 前几步步子太大 | 加长 warmup；检查梯度裁剪（[第 20 章](./gradient-stability.md)） |
| 衰减段损失明显下一个台阶 | 正常现象，说明峰值阶段一直在震荡 | 不用改；比较时要看衰减结束后的损失 |
| 改了调度，结果好了一点 | 可能只是运气 | 至少 3 个种子，看范围是否重叠 |

最后一行特别重要。第 3 节里，余弦 1e-2 和固定 3e-3 只差 0.004，3 个种子的范围是重叠的；如果只跑一个种子，完全可能得出“余弦更好”或“余弦更差”的结论。另外，比较 WSD 和别的调度时，要在衰减**结束以后**比；衰减之前，WSD 的损失往往还更高。

## 7. 学习率和 batch 大小、模型宽度

本章的最佳学习率，只对这个代理模型、这个 batch 大小成立。另外两个量变了，学习率通常也要跟着变：

- **batch 大小。** batch 越大，梯度的噪声越小，每一步可以迈得更大。用 SGD 训练图像模型时，常见的经验是 batch 扩大 $k$ 倍，学习率也扩大 $k$ 倍，配合 warmup（[Goyal 等，2017](https://arxiv.org/abs/1706.02677)）；对 Adam 一类的优化器，学习率随 batch 增长得更慢，理论分析给出的是平方根关系（[Malladi 等，2022](https://arxiv.org/abs/2205.10287)），实际中常拿它作为起点再扫。batch 大到一定程度（所谓临界 batch 大小）以后，再增大 batch，每步的收益就越来越小了（[McCandlish 等，2018](https://arxiv.org/abs/1812.06162)）。
- **模型宽度。** 用标准的参数化和初始化，模型越宽，最佳学习率通常越小；小模型上调好的学习率，直接用到大模型上往往会发散。[第 13 章](./gpu-training.md)的 GPU 配置宽得多（d=512 和 768），峰值也从第 12 章的 3e-3 降到了 1e-3 和 6e-4。μP（maximal update parametrization）调整了初始化和每一层的学习率缩放，让最佳学习率在不同宽度之间基本不变，于是可以先在小模型上扫学习率，再直接用到大模型上（[Yang 等，2022](https://arxiv.org/abs/2203.03466)）。[第 24 章](./large-model-stability.md)会回到这个话题。

所以本章的代理实验能告诉我们“衰减要配更高的峰值”“warmup 不能省”这类规律；具体的数字（比如 1e-2），换了模型尺寸或 batch 大小，要重新扫。

## 动手实验

1. **把预算加长。** 把 `STEPS` 改成 600，重跑第 3 节的四种设置。余弦和 WSD 的差距变大还是变小？固定 3e-3 还能追平余弦吗？
2. **为每种调度单独扫峰值。** 对余弦和 WSD 各试 5e-3、1e-2、2e-2（各 3 个种子），各自取最好的峰值再比较。结论和第 3 节一样吗？
3. **warmup 的长度。** 把 WSD 的 warmup 改成 5、15、60 步，最终验证损失怎么变？画出“warmup 步数 - 最终损失”的曲线。
4. **用回第 12 章的原尺寸模型。** 把 `cfg` 改回 `TinyConfig()`，`STEPS, BATCH` 改回第 12 章的 300、32，用 WSD、峰值 1e-2 训练一次，和第 12 章的 5.579 比较。这是单个种子，差别要大于零点零几才值得认真看（约两分钟）。

<!-- real-model:start -->

## 在真实模型里

transformers 的学习率调度都是“给步数、返回倍数”的函数，再包进 PyTorch 的 `LambdaLR`，和本章的写法一样。下表的链接都指向 Hugging Face transformers 的固定版本 `v5.21`，精确到行。读代码时可以先跳过缓存、掩码、并行这些工程细节，只看和本章对应的那几行。

| 本章的零件 | 真实代码 | 对照要点 |
| --- | --- | --- |
| warmup + 余弦 | [`get_cosine_schedule_with_warmup`](https://github.com/huggingface/transformers/blob/v5.21/src/transformers/optimization.py#L143-L174) | 先线性升到峰值，再按余弦降；默认一直降到 0，本章（和第 13 章的 `lr_at`）停在峰值的 10% |
| WSD | [`_get_wsd_scheduler_lambda`](https://github.com/huggingface/transformers/blob/v5.21/src/transformers/optimization.py#L470-L505) | warmup、保持、衰减三段；衰减段可选线性、余弦或 1-sqrt，并可设最低学习率比例 `min_lr_ratio` |
| 按名字选调度器 | [`get_scheduler`](https://github.com/huggingface/transformers/blob/v5.21/src/transformers/optimization.py#L960-L1054) | `lr_scheduler_type` 是 `"cosine"`、`"linear"`、`"warmup_stable_decay"` 等字符串，在这里映射到具体函数 |
| Trainer 何时创建 | [`Trainer.create_scheduler`](https://github.com/huggingface/transformers/blob/v5.21/src/transformers/trainer.py#L1344-L1372) | 知道总步数以后才创建调度器；`warmup_steps` 不小于 1 时是步数，小于 1 时按总步数的比例换算 |

想在本机看源码，可以先 `pip install transformers`，再用 `python -m inspect transformers.models.llama.modeling_llama:LlamaMLP` 这样的命令打印出任意一个类。

<!-- real-model:end -->

## 本章结论：TinyLLM 的选择 {#tinyllm-choice}

TinyLLM 的学习率按**优化器步**调度：先用一段**线性 warmup** 从接近 0 升到峰值，再衰减。默认用**WSD**（保持峰值，最后约 20% 的步数线性降到 0）；总步数事先确定、只训练一次时，warmup + 余弦（降到峰值的 10%，即第 13 章的 `lr_at`）也是可靠的选择。加了衰减以后，**峰值要重新调，通常比最佳的固定学习率更大**。

在本章的代理模型上（16 万参数、240 步、3 个种子）：最佳固定学习率 3e-3 的验证损失是 4.805；直接给它加余弦反而变差到 4.987；峰值提到 1e-2 后，余弦追平（4.801），WSD 最好（4.748）；去掉 warmup，WSD 变差到 4.884。

第 12 章的基线仍保持固定 3e-3 不变，这样后面各章的对照都有同一个起点；第 13 章的 GPU 训练和以后的完整训练用带 warmup 的调度。这些选择在什么情况下要换：训练很短时，warmup 要短，衰减不能开始得太早；换了 batch 大小或模型宽度，峰值要重新扫；需要从检查点继续训练、或者一次训练产出多个预算的模型时，优先用 WSD。

::: warning 常见误区
- **加调度一定会更好。** 在原来的学习率上直接加余弦，本章反而变差了。衰减要配上更高的峰值，两者一起调。
- **没有 warmup，开头降得快，说明不需要 warmup。** 本章里不加 warmup 的前一百步确实更低，但约 120 步后被反超，最终更差。看最终的验证损失，不要只看开头。
- **WSD 在衰减前的损失更高，说明它不好。** 它的好处集中在衰减段。比较调度要在衰减结束后比。
- **小模型上调好的学习率可以直接用到大模型上。** 模型变宽、batch 变大，最佳学习率都会变。除非用了 μP 这类参数化，否则要重新扫。
- **`scheduler.step()` 每个 batch 调一次。** 应该是每个优化器步调一次；梯度累积时，几个 micro-batch 才算一步。
:::

## 检查理解

1. 第 3 节里，为什么在固定 3e-3 上加 warmup + 余弦反而变差，而把峰值提到 1e-2 之后，余弦就能追平？

   <details><summary>参考答案</summary>

   240 步的预算很短，结束时模型还在快速学习。在 3e-3 上加余弦，等于从第 30 步起就不断把学习率降到 3e-3 以下，后半段每一步都走得比固定学习率短，总的进展变少了。把峰值提到 1e-2，前期每一步走得比 3e-3 远，下降得更快；虽然固定 1e-2 会在谷底附近震荡，但余弦在后期把学习率降下来，震荡被消除了。两者相抵，正好追平最好的固定学习率。这说明衰减的作用是“让你用得起更大的峰值”，而不是单独加上去就有好处。

   </details>

2. 有人用 WSD 训练，第 180 步的验证损失（4.92）比余弦（4.89）还高，就认为 WSD 更差，停止了实验。错在哪里？

   <details><summary>参考答案</summary>

   WSD 在第 180 步时还处在峰值阶段，学习率是 1e-2，模型在谷底附近震荡，损失偏高是正常的；它的好处集中在最后 20% 的衰减段（本章种子 0 从 4.92 降到 4.73）。比较不同调度，要在各自衰减结束后、用同样的总步数比较，最好再用 3 个以上的种子。

   </details>

3. 你打算先训练 1000 步看看效果，如果不错再继续训练到 3000 步。用余弦还是 WSD 更方便？为什么？

   <details><summary>参考答案</summary>

   WSD 更方便。余弦的形状由总步数决定：按 1000 步设计的余弦，到第 1000 步学习率已经降到底了，想接着训练到 3000 步，要么重新升高学习率（训练会受到扰动），要么从头按 3000 步重训。WSD 大部分时间都在峰值上：第一次可以从峰值阶段（比如第 800 步）的检查点接一段衰减，得到一个 1000 步的模型；想继续，就从第 800 步的检查点接着在峰值上训练，到 2400 步左右再开始衰减。

   </details>

4. 把 batch 从 16 段增大到 64 段，其他不变，本章的最佳峰值学习率会变大还是变小？只靠这一章的实验能确定具体是多少吗？

   <details><summary>参考答案</summary>

   通常会变大：batch 越大，梯度的噪声越小，可以迈更大的步子。但变多少没有固定的公式：SGD 常用线性放大，Adam 一类常用平方根作为起点，而且 batch 超过临界大小以后，收益会变小。本章只用了一个 batch 大小，不能确定具体的数字，要在新的 batch 下重新扫峰值（至少几个值、每个 3 个种子）。

   </details>

## 参考资料

- [PyTorch：`torch.optim.lr_scheduler`](https://docs.pytorch.org/docs/stable/optim.html#how-to-adjust-learning-rate)（`LambdaLR` 等调度器，以及 `scheduler.step()` 的调用时机）
- [SGDR: Stochastic Gradient Descent with Warm Restarts，Loshchilov 与 Hutter，2017](https://arxiv.org/abs/1608.03983)（余弦衰减）
- [Accurate, Large Minibatch SGD: Training ImageNet in 1 Hour，Goyal 等，2017](https://arxiv.org/abs/1706.02677)（warmup 与学习率随 batch 线性放大）
- [On the Variance of the Adaptive Learning Rate and Beyond，Liu 等，2020](https://arxiv.org/abs/1908.03265)（Adam 训练初期的方差问题与 warmup）
- [MiniCPM: Unveiling the Potential of Small Language Models with Scalable Training Strategies，Hu 等，2024](https://arxiv.org/abs/2404.06395)（WSD 调度）
- [Scaling Laws and Compute-Optimal Training Beyond Fixed Training Durations，Hägele 等，2024](https://arxiv.org/abs/2405.18392)（WSD 与余弦的系统比较）
- [Training Compute-Optimal Large Language Models，Hoffmann 等，2022](https://arxiv.org/abs/2203.15556)（余弦周期要与训练步数对齐）
- [An Empirical Model of Large-Batch Training，McCandlish 等，2018](https://arxiv.org/abs/1812.06162)（临界 batch 大小）
- [On the SDEs and Scaling Rules for Adaptive Gradient Algorithms，Malladi 等，2022](https://arxiv.org/abs/2205.10287)（Adam 类优化器的学习率随 batch 按平方根缩放）
- [Tensor Programs V: Tuning Large Neural Networks via Zero-Shot Hyperparameter Transfer，Yang 等，2022](https://arxiv.org/abs/2203.03466)（μP 与学习率迁移）

学习率决定了每一步走多远；走得太远会过拟合训练集，这就需要正则化：[第 18 章：正则化与泛化](./regularization.md)。
