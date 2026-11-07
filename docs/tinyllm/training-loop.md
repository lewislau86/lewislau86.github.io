---
title: "第 21 章：训练循环与检查点"
description: "把前几章的零件装成一个可以随时中断、随时恢复的训练循环，用最严格的标准检验检查点：断电后接着训，参数要和一口气训完逐位相同。过程中找出 DataLoader 偷用全局随机数这个坑，再逐项去掉优化器、调度器、数据位置、随机数状态，看各自造成什么偏差。"
pageClass: tinyllm-course
---

# 第 21 章：训练循环与检查点

[课程总览](./index.md) · [上一章](./gradient-stability.md) · [下一章](./training-evaluation.md)

::: tip 本章学习目标
能用 `Dataset`、`Sampler`、`DataLoader` 写出按 epoch 组织、可以从任意一步接着跑的训练循环；能说清一个“能接着训”的检查点要存哪几样东西，缺了每一样分别会怎样；能用“和一口气训完逐位相同”这个标准检验自己的检查点，并知道原子保存、只留最新几个、`weights_only=True` 这些工程细节。

**前置：** [第 16 章](./optimizers.md)的优化器状态，[第 17 章](./learning-rate.md)的 WSD 与 `LambdaLR`，[第 18 章](./regularization.md)的 dropout，[第 20 章](./gradient-stability.md)的梯度裁剪；[第 13 章](./gpu-training.md)存过一个最简单的检查点。

**实践方式：** [training-loop.ipynb](/tinyllm/notebooks/training-loop)（也可以直接运行 <a href="/tinyllm/code/training-loop.py" download>training-loop.py</a>），CPU 约半分钟，需要 PyTorch 和 `tokenizers`。
:::

[第 13 章](./gpu-training.md)在 GPU 上训练时存过一个检查点：模型、优化器、配置和步数。存完立刻读回来，验证损失一模一样，于是我们说“检查点没问题”。

可这只证明了**模型**读回来是对的。检查点真正的用途是**接着训**：训练跑到一半断电了、被抢占了、要换机器了，从最近的检查点恢复，继续往下跑。接着训出来的模型，和一口气训完的模型一样吗？

这一章用最严格的标准回答这个问题：**中断后接着训，最后的参数要和一口气训完逐位相同**，不是“差不多”，是每一个浮点数都相等。为此，我们先把前几章的零件装成一个完整的训练循环，然后让它在第 120 步“断电”，再恢复。结果会有一个意外。

<TinyLLMMap active="training-loop" />

::: info 本章代码从哪里来
本章所有代码都在一个文件里：<a href="/tinyllm/code/training-loop.py" download>training-loop.py</a>（[在 GitHub 上查看](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/tinyllm/code/training-loop.py)）。下面的代码块都是从这个文件里直接截取的片段，所以单独复制一段可能缺少 `import` 或前面定义的变量；想自己运行，请下载完整文件，`python training-loop.py` 从头跑到尾即可。notebook 版本也由同一个文件生成，可以[在线查看](/tinyllm/notebooks/training-loop)，或[在 Colab 中直接运行](https://colab.research.google.com/github/lewislau86/lewislau86.github.io/blob/master/docs/public/tinyllm/notebooks/training-loop.ipynb)。正文引用的输出来自 torch 2.14.1+cpu、tokenizers 0.23.3。
:::

## 0. 实验对象

模型是[第 18 章](./regularization.md)的版本（第 12 章的模型加上 dropout），尺寸是[第 17 章](./learning-rate.md)的代理模型。训练配置用前几章定下的主线：AdamW、第 17 章的 WSD 调度（峰值 1e-2）、第 20 章的梯度裁剪。

<<< @/public/tinyllm/code/training-loop.py#proxy

有两处和主线不同，都是为了让检验更严格：

- **打开了 `dropout=0.1`。** 主线预训练不用 dropout（第 18 章），但这样训练就不会用到全局随机数，“随机数状态有没有存对”也就检验不出来。微调、采样、数据增强都会用到随机数，这个检验是必要的。
- **训练集只取前 1200 首。** 这样 240 步会跨过好几个 epoch，“第几个 epoch、这个 epoch 用到第几个 batch”才真正需要记。

## 1. 数据：Dataset、Sampler、DataLoader

前几章都是事先排好一张 batch 计划表，第几步就取第几行。真实的训练代码更常用 PyTorch 的数据三件套：

- **`Dataset`**：告诉 PyTorch 一共有多少个样本，第 $i$ 个样本是什么。这里把 token 流切成不重叠的窗口，每个窗口是一个样本。
- **`Sampler`**：决定按什么顺序取样本。
- **`DataLoader`**：按 `Sampler` 给的顺序取样本，凑成 batch。

<<< @/public/tinyllm/code/training-loop.py#dataset

```text
1013 个窗口，每个 epoch 63 个 batch；240 步约 3.8 个 epoch
一个 batch： (16, 64) (16, 64) 目标是输入错开一位： True
```

打乱顺序用的是自己写的 `EpochShuffle`，而不是 `DataLoader(shuffle=True)`。区别在于“记住读到哪里”有多容易：

- `shuffle=True` 用一个随机数生成器现场打乱，打乱的结果藏在生成器的状态里。要从中途恢复，得存下这个生成器在 epoch 开始时的状态，再把已经用过的样本一个个跳过去。
- `EpochShuffle` 的顺序只由 `(DATA_SEED, epoch)` 决定，第几个 epoch 就用 `DATA_SEED + epoch` 重新排一遍。恢复时只要知道“第几个 epoch、这个 epoch 用掉了几个 batch”两个整数，`set_epoch(epoch, start)` 就能直接从那个位置开始，不用回放前面的数据。

多卡训练用的 `DistributedSampler` 也是这个思路，每个 epoch 开始时要调用 `set_epoch(epoch)`。

## 2. 构造训练对象

模型、优化器、学习率调度器放在一个函数里构造。恢复训练时也要先调用它，把对象造出来，再往里装状态：

<<< @/public/tinyllm/code/training-loop.py#build

## 3. 训练循环

`progress` 是一个小字典，记着训练进行到哪里：第几步、第几个 epoch、这个 epoch 用掉了几个 batch。循环从 `progress` 接着往下走，一直训练到第 `until` 步：

<<< @/public/tinyllm/code/training-loop.py#loop

![最外面是 progress（step、epoch、batch_in_epoch）。每个 epoch 先 sampler.set_epoch(epoch, start)，跳过这个 epoch 已经用过的样本；每个 batch 依次 zero_grad、前向、backward、裁剪、optimizer.step、scheduler.step，然后推进 progress。每隔若干步取一次 .item() 打印日志、测一次验证损失、保存一次完整检查点；到达 until 就返回，下次从 progress 接着来](/tinyllm/figures/loop-structure.svg)

每一步的六个调用，前几章都分别讲过：

1. `optimizer.zero_grad(set_to_none=True)`：清掉上一步的梯度。PyTorch 的梯度是累加的（[第 20 章](./gradient-stability.md)的梯度累积就靠这一点），不清就会把上一步的梯度带进来。
2. 前向，算损失（[第 15 章](./language-model-loss.md)）。
3. `loss.backward()`：求梯度（[第 2 章](./tensors-and-autograd.md)）。
4. `clip_grad_norm_`：按全局范数裁剪（[第 20 章](./gradient-stability.md)）。
5. `optimizer.step()`：用梯度更新参数（[第 16 章](./optimizers.md)）。
6. `scheduler.step()`：把学习率推进到下一步的值（[第 17 章](./learning-rate.md)）。顺序放反的后果见第 10 节。

还有一个细节：损失先用 `loss.detach()` 存成张量，每 `log_every` 步才 `.item()` 一次。在 GPU 上，`.item()` 要把数从显存拷回内存，CPU 必须停下来等 GPU 把前面的计算全部做完；每步都调用，CPU 就没法提前把下一步的命令发出去。这就是[第 13 章](./gpu-training.md)优化点 ⑦ 说的同步问题。CPU 上没有这个问题，但写法可以一样。

先一口气训练 240 步，作为参照。然后从头再训练一次：要比较“接着训”和“一口气训”，先得确认训练本身是确定的，同样的代码跑两遍，结果逐位相同。

<<< @/public/tinyllm/code/training-loop.py#reference

```text
  step   40  epoch 0  最近 40 步平均损失 6.371  学习率 1.00e-02
  step   80  epoch 1  最近 40 步平均损失 5.709  学习率 1.00e-02
  step  120  epoch 1  最近 40 步平均损失 5.299  学习率 1.00e-02
  step  160  epoch 2  最近 40 步平均损失 5.105  学习率 1.00e-02
  step  200  epoch 3  最近 40 步平均损失 4.997  学习率 8.33e-03
  step  240  epoch 3  最近 40 步平均损失 4.868  学习率 0.00e+00
参照：240 步后验证损失 4.8457
再训练一次：参数最大差 0.0
```

两次的参数最大差是 0.0，每一个浮点数都相等。这个标准在 CPU 上、同一台机器、同一个 PyTorch 版本下是成立的；换成 GPU，有些算子默认不保证确定性，要另外设置（第 11 节）。

## 4. 检查点里存什么

要能“接着训”，检查点要存下继续训练所需的全部状态：

<<< @/public/tinyllm/code/training-loop.py#checkpoint

一样一样看：

- **模型参数**：`model.state_dict()`，模型现在是什么样。
- **优化器状态**：AdamW 为每个参数记着的 $m$、$v$ 和步数（[第 16 章](./optimizers.md)），以及当前的学习率。
- **调度器状态**：调度器走到了第几步。
- **训练进度**：`progress` 里的三个整数，决定下一个 batch 是哪些样本。
- **随机数状态**：dropout 每次随机丢掉哪些数，由全局随机数决定。
- **配置**：新进程要先按配置把模型、优化器造出来，才能往里装状态。分词器单独存成 `tokenizer.json`，和检查点放在同一个目录里（[第 4 章](./tokenization.md)）。

保存用 `save_checkpoint`：先写到 `.tmp` 临时文件，写完再用 `os.replace` 改名覆盖。`os.replace` 是原子操作，目标文件要么还是旧的，要么已经是完整的新文件，不会出现写了一半的状态（第 8 节）。`keep_last` 只保留最新的几个检查点，避免磁盘被占满。

现在从头训练，每 40 步存一次、只留最新 2 个，训练到第 120 步时“断电”：

<<< @/public/tinyllm/code/training-loop.py#crash

```text
目录里剩下： step_000080.pt（1946 KB）, step_000120.pt（1946 KB）, tokenizer.json（55 KB）
```

第 40 步的检查点已经被删掉了。`train_until_crash` 返回以后，模型、优化器、调度器都随函数一起消失，只剩磁盘上的文件，就像进程被杀掉了一样。

## 5. 恢复，接着训练

新进程只有磁盘上的文件：先按存下的配置把对象造出来，再把各自的状态装回去。`parts` 参数后面做对照时用，默认全部恢复：

<<< @/public/tinyllm/code/training-loop.py#resume

`torch.load(..., weights_only=True)` 只读取张量、数字、字符串、列表、字典这些基本类型。`torch.load` 底层用的是 Python 的 pickle，不加这个限制，一个精心构造的文件在读取时就能执行任意代码。从网上下载的检查点尤其要注意这一点。PyTorch 2.6 起这已经是默认值。

模型、优化器、调度器、数据位置、随机数，全部都存了、都恢复了。先猜一下：接着训到 240 步，参数会和参照逐位相同吗？

```text
从 step_000120.pt 恢复：{'step': 120, 'epoch': 1, 'batch_in_epoch': 57}
接着训到 240 步：验证损失 4.8506（参照 4.8457），参数最大差 5.17e-01
第一次和参照不同的是第 121 步：5.192482 对 5.192294
```

**不一样。** 而且恢复后的第一步（第 121 步）就不一样了，差在小数点后第 4 位。差别虽小，但训练是一个混沌的过程，一点点偏差经过 120 步会被放大，最后参数最大差了 0.52。

## 6. 找原因：DataLoader 偷偷用了全局随机数

第 121 步就不一样，说明问题出在恢复之后、第 121 步算完之前。数据位置存对了（`epoch 1`、`batch_in_epoch 57`，batch 是同一个），模型、优化器也是同一个，剩下的只有 dropout 的随机掩码。可是随机数状态明明存了、也恢复了。恢复之后、第 121 步之前，有谁动过全局随机数？

<<< @/public/tinyllm/code/training-loop.py#rng-leak

```text
iter(loader) 之后，全局随机数状态变了： True
换成自己的 generator 之后，变了： False
```

找到了。`for x, y in loader` 一开始会调用 `iter(loader)`，创建迭代器时，`DataLoader` 会从全局随机数里取一个数，给 worker 进程当种子，即使 `num_workers=0`、根本没有 worker 也照取不误。

- 一口气训练时，只在每个 epoch 开头创建迭代器，第 121 步在第 1 个 epoch 的中间，前面没有新建迭代器。
- 恢复训练时，`train` 从第 1 个 epoch 的中间开始，先创建一次迭代器，**多取了一个随机数**，之后 dropout 的掩码就全部错开了一位。

修法是给 `DataLoader` 一个自己的随机数生成器（`generator=...`），它就不再碰全局随机数了。这是一个很隐蔽的坑：没有报错，没有警告，结果只差小数点后第 4 位，看最终损失根本发现不了。只有用“逐位相同”这个标准，才把它揪了出来。

换上新的 `loader`，把参照、训练到第 120 步“断电”、恢复后接着训，全部重跑一遍：

<<< @/public/tinyllm/code/training-loop.py#fixed

```text
参照验证损失 4.8635；恢复后接着训练 4.8635
参数最大差 0.0；240 步的训练损失逐个相同：True
```

**逐位相同了。** 参数最大差 0.0，240 步的训练损失一个不差。参照的验证损失从 4.8457 变成了 4.8635，是因为全局随机数不再被 `DataLoader` 消耗，dropout 的掩码序列整体变了，模型走了另一条同样合理的路线；这是单个种子之间的正常差别，和检查点无关。

## 7. 对照：每次少恢复一样东西

现在有了一个能逐位恢复的检查点，就可以逐项检验：每一样东西如果不恢复，会造成多大的偏差？每次少恢复一样，接着训到 240 步：

<<< @/public/tinyllm/code/training-loop.py#ablation

```text
           第 121 步损失    后 120 步最大损失差       参数最大差      最终验证
参照              5.2027              0.0000       0.00e+00      4.8635
完整恢复          5.2027          0.0000    0.00e+00    4.8635
缺优化器状态        5.2027          0.5461    5.21e-01    4.8560
缺调度器状态        5.2027          0.1003    2.90e-01    4.9149
缺数据位置         5.1531          0.1730    4.16e-01    4.8677
缺随机数状态        5.2102          0.0742    3.27e-01    4.8660
```

![第 120 步存档后恢复、接着训练到第 240 步。完整恢复时每一步的损失都和一口气训完相同。缺优化器状态时，恢复后头几步的损失明显跳高；缺调度器状态时学习率重新 warmup、最后的衰减段没有发生，损失降不下去；缺数据位置、缺随机数状态时，损失从第 121 步起就和参照不同，但走势相近](/tinyllm/figures/ckpt-resume.svg)

怎么读这张表和这张图：

- **缺数据位置、缺随机数状态：第 121 步就不同。** 前者从第 0 个 epoch 的开头重新读数据，第 121 步的 batch 换了；后者 dropout 的掩码换了。之后的损失和参照走势相近，像是换了一个随机种子。但它们已经不是“同一次训练”了：缺数据位置时，数据顺序回到了第 0 个 epoch 的开头，前 120 步看过的 batch 按原来的顺序再看一遍，每个样本被看到的次数也就不再均匀。训练越短、数据越少，这种重复和遗漏越要紧。
- **缺优化器状态：第 121 步的损失相同，之后跳得最高。** 前向只用到模型参数，所以第 121 步的损失一样。但 AdamW 的 $m$、$v$ 从零重新开始，加上偏差修正，头几步对每个参数都迈出接近一整个学习率的一步（[第 20 章](./gradient-stability.md)尖峰后的情形类似），模型被推偏，训练损失跳起 0.55。
- **缺调度器状态：最终验证损失最差。** 新造的调度器从第 0 步开始，又走一遍 warmup，而且到训练结束时它才走到第 120 步，WSD 最后 20% 的衰减段根本没有发生。[第 17 章](./learning-rate.md)讲过，衰减段正是损失“下台阶”的地方。

最终验证损失这一列只是单个种子的结果，0.01 以内的差别不必解读；这一节要看的是“逐位相同”和“偏离了多少”。缺调度器状态的 4.9149 例外，它的原因是确定的：衰减段没有发生。

缺调度器状态时，学习率到底从哪里开始？把恢复后前 4 步实际用的学习率打印出来：

<<< @/public/tinyllm/code/training-loop.py#lr-after-resume

```text
完整恢复     恢复后前 4 步的学习率：1.00e-02  1.00e-02  1.00e-02  1.00e-02   （参照：1.00e-02  1.00e-02  1.00e-02  1.00e-02）
缺调度器状态   恢复后前 4 步的学习率：1.00e-02  6.67e-04  1.00e-03  1.33e-03   （参照：1.00e-02  1.00e-02  1.00e-02  1.00e-02）
```

第一步还是 1e-2：优化器状态里存着当前的学习率，装回去时也一起恢复了。从第二步起，新调度器按自己的进度（第 1 步、第 2 步……）设置学习率，又从 warmup 开头爬起。这种错误很难从损失上察觉，看学习率曲线就一目了然。所以训练日志里一定要记学习率。

把这一节的结果画成检查点的“成分表”：

![检查点由模型参数（646 KB）、优化器状态（1294 KB）、调度器状态、训练进度、随机数状态和配置组成。恢复时缺了优化器状态、调度器状态、数据位置或随机数状态中的任何一样，接着训练的参数都会偏离一口气训完的结果；全部存齐时最大差为 0.0，逐位相同](/tinyllm/figures/ckpt-contents.svg)

## 8. 写到一半断电会怎样

检查点本身也可能在保存的时候坏掉：文件写到一半，进程被杀了。直接往目标文件里写，和先写临时文件再替换，各模拟一次：

<<< @/public/tinyllm/code/training-loop.py#atomic

```text
直接写、写到一半：读取失败（RuntimeError）
原子写、写到一半：目标文件仍可读取，步数 120
```

直接写的那个文件读不出来了。更糟的是，如果直接覆盖的是“最新的检查点”，那么旧的那份也没了。先写 `.tmp`、写完再 `os.replace`，断电时坏掉的只是临时文件，之前的检查点完好无损。再配合“保留最新几个”，即使最新的一个出了问题，还能退回上一个。

## 9. 检查点有多大

把检查点里每一部分单独序列化，看各占多少：

<<< @/public/tinyllm/code/training-loop.py#sizes

```text
model           646.0 KB
optimizer      1293.6 KB
scheduler         1.4 KB
progress          1.3 KB
rng               6.5 KB
config            1.4 KB
train_config      1.3 KB
163904 个参数；模型 4.04 字节/参数，优化器 8.08 字节/参数
```

FP32 的参数每个 4 字节；AdamW 的 $m$ 和 $v$ 各 4 字节，所以优化器状态是模型的两倍。一个能接着训的检查点，每个参数约 12 字节，其他东西加起来可以忽略。按这个比例，70 亿参数的模型，一个检查点约 84 GB；只用来推理的话，只存模型参数（再转成 BF16）就够了，约 14 GB。这也是为什么大模型训练时，“多久存一次”是一个要权衡的问题（第 11 节）。

## 10. 调度器和优化器的先后

最后看一个常见的顺序错误：把 `scheduler.step()` 放到 `optimizer.step()` 之前。

<<< @/public/tinyllm/code/training-loop.py#order

```text
optimizer 先：前 3 步用的学习率 3.33e-04  6.67e-04  1.00e-03
scheduler 先：前 3 步用的学习率 6.67e-04  1.00e-03  1.33e-03；PyTorch 警告：Detected call of `lr_scheduler.step()` before `optimizer.step()`
```

调度器先走，第一步就用上了第二步的学习率，整条曲线提前了一步，WSD 调度的第一个值（3.33e-4）被跳过了。PyTorch 会给出警告。一步之差影响不大，但它常常和别的错误同时出现，比如梯度累积时每个 micro-batch 都调用一次 `scheduler.step()`，整条曲线就会快 accum 倍（第 17 章）。

## 11. 更大的训练还要多管什么

本章的循环在一台机器的 CPU 上做到了逐位恢复。规模变大以后，还有几件事要处理：

- **GPU 的随机数和确定性。** GPU 有自己的随机数状态，每张卡一份，要用 `torch.cuda.get_rng_state_all()` 一起存下来。有些 GPU 算子为了速度，默认不保证每次结果相同（比如用原子加法的归约），要逐位复现得打开 [`torch.use_deterministic_algorithms(True)`](https://docs.pytorch.org/docs/stable/notes/randomness.html)，代价是变慢。换了显卡型号、驱动或 PyTorch 版本，逐位相同一般就做不到了，这时只能要求“统计上一致”。
- **多进程读数据。** `num_workers > 0` 时，每个 worker 进程有自己的随机数，由 `DataLoader` 的生成器派生出种子；用了随机数据增强时，要通过 `worker_init_fn` 和 `generator` 让它可复现。
- **多卡检查点。** 模型和优化器状态切在多张卡上时，每张卡只存自己那一份，恢复时再按同样的切法装回去（PyTorch 的 `torch.distributed.checkpoint`）。这部分放在[第 24 章](./large-model-stability.md)。
- **多久存一次。** 存得太勤，保存本身占用训练时间；存得太稀，崩溃时丢掉的进度多。一个经典的估算是：保存一次要 $C$ 秒，平均每 $M$ 秒出一次故障，最佳间隔约为 $\sqrt{2CM}$（[Young，1974](https://dl.acm.org/doi/10.1145/361147.361115)）。大模型训练还常常把保存放到后台线程里做，训练不用停下来等。

## 动手实验

1. **换成 `shuffle=True`。** 把 `EpochShuffle` 换成 `DataLoader(..., shuffle=True, generator=g)`。要逐位恢复，检查点里要多存什么？恢复时怎样跳过这个 epoch 已经用过的 batch？
2. **在 epoch 边界上断电。** 每个 epoch 有 63 个 batch。让训练在第 126 步（正好两个 epoch 结束）“断电”再恢复，还能逐位相同吗？`progress` 里存的是什么？
3. **加上 `GradScaler`。** 用第 20 章的 FP16 写法训练，检查点还要多存哪一样？不存的话，恢复后会发生什么？
4. **测保存的代价。** 每一步都保存一次检查点，训练时间变成原来的多少倍？每 40 步一次呢？

<!-- real-model:start -->

## 在真实模型里

transformers 的 Trainer 存检查点、续训的做法和本章是同一套思路，只是拆成了几个文件。下表的链接都指向 Hugging Face transformers 的固定版本 `v5.21`，精确到行。读代码时可以先跳过缓存、掩码、并行这些工程细节，只看和本章对应的那几行。

| 本章的零件 | 真实代码 | 对照要点 |
| --- | --- | --- |
| 保存检查点 | [`Trainer._save_checkpoint`](https://github.com/huggingface/transformers/blob/v5.21/src/transformers/trainer.py#L3318-L3385) | 模型、优化器、调度器、随机数状态和训练进度分别存成几个文件，放在同一个 `checkpoint-<步数>` 目录里 |
| 训练进度 | [`TrainerState`](https://github.com/huggingface/transformers/blob/v5.21/src/transformers/trainer_callback.py#L35-L186) | `global_step`、`epoch`、日志历史等，存成 `trainer_state.json`，对应本章的 `progress` |
| 保存随机数状态 | [`Trainer._save_rng_state`](https://github.com/huggingface/transformers/blob/v5.21/src/transformers/trainer.py#L3425-L3474) | Python、NumPy、torch 以及每张 GPU 的随机数状态都存下来，比本章多几种 |
| 恢复随机数状态 | [`Trainer._load_rng_state`](https://github.com/huggingface/transformers/blob/v5.21/src/transformers/trainer.py#L3800-L3843) | 续训时装回去；找不到这个文件时会给出警告，提示结果可能无法逐位复现 |
| 跳过已经用过的 batch | [`trainer.py 第 219 行`](https://github.com/huggingface/transformers/blob/v5.21/src/transformers/trainer.py#L219) | 续训时跳过这个 epoch 已经训练过的 batch，作用和本章 `EpochShuffle` 的 `start` 相同 |
| 只保留最近几个检查点 | [`rotate_checkpoints`](https://github.com/huggingface/transformers/blob/v5.21/src/transformers/trainer_utils.py#L342-L386) | 按 `save_total_limit` 删掉最旧的检查点，但始终保留最新的一个（续训要用）和验证最好的那个 |

想在本机看源码，可以先 `pip install transformers`，再用 `python -m inspect transformers.models.llama.modeling_llama:LlamaMLP` 这样的命令打印出任意一个类。

<!-- real-model:end -->

## 本章结论：TinyLLM 的选择 {#tinyllm-choice}

TinyLLM 的训练循环按 `zero_grad → 前向 → backward → 裁剪 → optimizer.step → scheduler.step` 的顺序执行，用 `progress`（step、epoch、这个 epoch 用掉的 batch 数）记录进度；数据顺序只由 `(DATA_SEED, epoch)` 决定，`DataLoader` 用自己的 `generator`，不碰全局随机数。损失先存成张量，每隔若干步才 `.item()` 一次。

检查点存六样东西：**模型参数、优化器状态、调度器状态、训练进度、随机数状态、配置**，分词器放在同一个目录里。保存时先写临时文件再 `os.replace`，只保留最新几个；读取时用 `weights_only=True`。检验标准是**中断后接着训，参数和一口气训完逐位相同**。

理由来自本章的实验（代理模型、单个种子、在 CPU 上）：完整恢复时参数最大差 0.0、240 步的训练损失逐个相同；少恢复优化器状态、调度器状态、数据位置、随机数状态中的任何一样，参数都会偏离（最大差 0.29～0.52），其中缺调度器状态会让 WSD 的衰减段整个消失。`DataLoader` 不传 `generator` 时会偷用全局随机数，让“完整恢复”也差了 0.52。

这些选择在什么情况下要换：用 GPU 时多存每张卡的随机数状态，需要逐位复现时打开确定性算法；用 FP16 时多存 `GradScaler` 的状态；多卡训练时用分布式检查点；只用来推理或发布时，只存模型参数和配置。

::: warning 常见误区
- **读回来验证损失一样，检查点就没问题。** 那只说明模型参数对了。能不能接着训，要看接着训出来的结果是否和一口气训完相同。
- **只存模型和优化器就够了。** 本章里缺调度器状态的那一次，学习率重新 warmup，衰减段消失，最终结果最差；缺数据位置会重复读一部分数据、漏读另一部分。
- **随机数状态存了，随机性就一定对。** `DataLoader` 每次创建迭代器都会从全局随机数里取一个数；恢复时多建一次迭代器，后面的随机数就全部错开了。给它一个自己的 `generator`。
- **差别只在小数点后第 4 位，可以忽略。** 训练会把微小的差别放大：第 121 步只差 0.0002，到第 240 步参数最大差 0.52。比较时用逐位相同，或者至少比较整条损失曲线。
- **直接覆盖最新的检查点。** 写到一半断电，新的没写成，旧的也被毁了。先写临时文件再替换。
- **`torch.load` 读什么都安全。** 它底层是 pickle，可以执行任意代码；用 `weights_only=True`，只加载可信来源的文件。
:::

## 检查理解

1. 第 5 节里，所有状态都恢复了，第 121 步的损失却和参照不同。为什么第 121 步的 batch 没有错，却还是能断定问题和随机数有关？

   <details><summary>参考答案</summary>

   第 121 步的损失只取决于三样东西：模型参数（从检查点恢复，和参照相同）、这一步的 batch（由 `epoch 1`、`batch_in_epoch 57` 决定，也相同）、这一步 dropout 的随机掩码。前两样都对，剩下的只有掩码，也就是全局随机数。进一步检查发现，恢复后新建 `DataLoader` 迭代器时多取了一个全局随机数，掩码因此错开。给 `DataLoader` 一个自己的 `generator` 以后，恢复就逐位相同了。

   </details>

2. 缺优化器状态时，第 121 步的训练损失和参照完全相同，为什么之后偏差反而最大？

   <details><summary>参考答案</summary>

   第 121 步的损失是前向算出来的，只用到模型参数，和优化器无关，所以相同。但这一步之后的更新要用 AdamW 的 $m$、$v$：它们从零开始，加上偏差修正，头几步的 $m/\sqrt{v}$ 对每个参数都接近 $\pm 1$，每个参数都迈出约一个学习率的一大步，而且方向只由最近一两个 batch 决定。模型被推偏，训练损失随之跳高（本章最大差 0.55），要过一段时间才回到正轨。

   </details>

3. 一个检查点只存了模型、优化器和 `step`，调度器用的是 `LambdaLR(optimizer, wsd)`。恢复后有人在循环开始前写了 `for _ in range(step): scheduler.step()`，想把调度器“快进”到正确位置。这样做能恢复正确的学习率吗？有什么隐患？

   <details><summary>参考答案</summary>

   对 `LambdaLR` 这种只依赖步数的调度器，快进 `step` 次以后，学习率确实能到正确的位置。但有隐患：一是没有 `optimizer.step()` 就调用 `scheduler.step()`，PyTorch 会警告；二是这只对“学习率只由步数决定”的调度器成立，像 `ReduceLROnPlateau` 这种依赖历史指标的调度器就快进不了；三是训练时如果改过学习率（比如手动调低过），快进得到的是原始曲线而不是实际用过的值。直接保存和加载 `scheduler.state_dict()` 最简单可靠。

   </details>

4. 70 亿参数的模型用 AdamW 训练，参数和优化器状态都是 FP32，一个能接着训的检查点大约多大？只用来推理、以 BF16 发布时呢？

   <details><summary>参考答案</summary>

   能接着训：参数 4 字节、$m$ 4 字节、$v$ 4 字节，每个参数约 12 字节，$7\times10^9 \times 12 \approx 84$ GB（再加上很小的调度器、进度、随机数状态）。用混合精度训练、另存 FP32 主权重时还会更大。只用来推理：只存参数，转成 BF16 每个参数 2 字节，约 14 GB。

   </details>

## 参考资料

- [PyTorch：`torch.utils.data`](https://docs.pytorch.org/docs/stable/data.html)（`Dataset`、`Sampler`、`DataLoader`，以及 `generator`、`worker_init_fn` 与随机性）
- [PyTorch：Saving and Loading a General Checkpoint](https://docs.pytorch.org/tutorials/recipes/recipes/saving_and_loading_a_general_checkpoint.html)
- [PyTorch：Reproducibility](https://docs.pytorch.org/docs/stable/notes/randomness.html)（随机种子、确定性算法、DataLoader 的随机性）
- [PyTorch：`torch.load`](https://docs.pytorch.org/docs/stable/generated/torch.load.html)（`weights_only` 与 pickle 的安全问题）
- [PyTorch：`torch.optim`](https://docs.pytorch.org/docs/stable/optim.html#how-to-adjust-learning-rate)（`scheduler.step()` 要在 `optimizer.step()` 之后调用）
- [Python：`os.replace`](https://docs.python.org/3/library/os.html#os.replace)（原子替换）
- [A first order approximation to the optimum checkpoint interval，Young，1974](https://dl.acm.org/doi/10.1145/361147.361115)（检查点间隔的经典估算）

训练循环装好了，能跑、能停、能接着跑。下一章回答“训练得怎么样”：先用过拟合一个小 batch 检查流程，再看验证损失、困惑度和生成样例，[第 22 章：训练诊断与评估](./training-evaluation.md)。
