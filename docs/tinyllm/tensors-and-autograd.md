---
title: "第 2 章：张量与自动求导"
description: "数字怎样排成张量，形状怎么读；loss.backward() 怎样沿计算图算出每个参数的梯度。"
pageClass: tinyllm-course
---

# 第 2 章：张量与自动求导

[课程总览](./index.md) · [上一章](./first-run.md) · [下一章](./tokenization.md)

::: tip 本章学习目标
能读出 `[batch, seq, hidden]` 形状每一轴的含义，判断两个形状能否广播；能手算一个单参数例子的梯度，并解释 `loss.backward()` 和 `optimizer.step()` 各做了什么；说清楚为什么参数再多，一次反向传播也能拿到全部梯度。

**前置：** [第 1 章](./first-run.md)跑通的流水线；高中导数。

**实践方式：** [tensors-and-autograd.ipynb](/tinyllm/notebooks/tensors-and-autograd)（也可以直接运行 <a href="/tinyllm/code/tensors-and-autograd.py" download>tensors-and-autograd.py</a>），CPU 即可。每遇到一个形状或结果，先自己猜，再运行代码核对。
:::

[第 1 章](./first-run.md)的训练循环里有两行我们没有解释：模型输入的 `x` 是形状为 `[32, 24]` 的一堆数字，`loss.backward()` 之后参数就知道往哪边调了。这引出两个问题：<strong>这些数字怎样排在一起？模型怎样知道哪些参数需要调整？</strong>前一个靠张量和形状回答，后一个靠自动求导回答。本章沿着一次小模型计算，把它们串起来。

<TinyLLMMap active="tensors-and-autograd" />

本文中的“token”暂时理解为文本中的一个编号，就像第 1 章里每个字的编号；分词的细节留到[第 3 章](./tokenization.md)。

## 从一批 token 到隐藏向量

::: info 本章代码从哪里来
本章所有代码都在一个文件里：<a href="/tinyllm/code/tensors-and-autograd.py" download>tensors-and-autograd.py</a>（[在 GitHub 上查看](https://github.com/lewislau86/lewislau86.github.io/blob/master/docs/public/tinyllm/code/tensors-and-autograd.py)）。下面的代码块都是从这个文件里直接截取的片段，所以单独复制一段可能缺少 `import` 或前面定义的变量；想自己运行，请下载完整文件，`python tensors-and-autograd.py` 从头跑到尾即可。notebook 版本也由同一个文件生成，可以[在线查看](/tinyllm/notebooks/tensors-and-autograd)，或[在 Colab 中直接运行](https://colab.research.google.com/github/lewislau86/lewislau86.github.io/blob/master/docs/public/tinyllm/notebooks/tensors-and-autograd.ipynb)。
:::

假设有两句话，每句话都取三个 token。用整数给它们编号：

<<< @/public/tinyllm/code/tensors-and-autograd.py#token-ids

外层有两行，表示两句话；每行有三个数，表示三个 token。所以形状 `[2, 3]` 的两个位置分别是<strong>样本数</strong>和<strong>每条样本的 token 数</strong>，常记作 `[batch, seq]`。形状是张量的“尺寸说明”；轴名是我们根据用途给它的解释，PyTorch 并不知道第二轴一定是句子长度。

token 编号只是索引，不能直接告诉模型“这个词有什么特征”。假设后续步骤把每个编号变成四个浮点数，那么一批隐藏向量就有三个轴：

<<< @/public/tinyllm/code/tensors-and-autograd.py#hidden

`[2, 3, 4]` 读作：<strong>2 条样本 × 每条 3 个 token × 每个 token 4 个特征</strong>，简写为 `[batch, seq, hidden]`。`hidden[0, 1, :]` 选中第一条样本的第二个 token；最后的 `:` 表示取它的全部四个特征。索引从 0 开始。`torch.arange(24)` 只是为演示形状填入 0 到 23，真实隐藏向量来自模型计算。

![两张 3 行 4 列的表分别代表两条样本，每行是一个 token 的 4 个特征；第 0 张表第 1 行被高亮，值为 4、5、6、7](/tinyllm/figures/tensor-shape.svg)

看张量时再留意三个属性：`ndim` 是轴数，`dtype` 是每个数的类型，`device` 是它存放和计算的位置。上面的 `token_ids` 是整数；`hidden` 是浮点数。可训练参数通常也是浮点数。`torch.tensor(...)` 用现有数据创建张量，`torch.zeros(...)` 创建全零张量，`torch.randn(...)` 创建随机张量；模型参数该怎样初始化要在 [第 9 章](initialization-and-residuals.md) 再讨论。

## 改变形状，还是交换轴？

原来的 `[2, 3, 4]` 一共有 $2\times3\times4=24$ 个数。`reshape(2, 12)` 把每条样本的 `3×4` 个位置合在一轴，数字总数不变：

<<< @/public/tinyllm/code/tensors-and-autograd.py#reshape

`transpose` 做的是另一件事：<strong>交换轴</strong>。`hidden.transpose(1, 2)` 得到 `[2, 4, 3]`。原来第二轴代表 token、第三轴代表特征；交换后，第二轴代表特征、第三轴代表 token。不能仅凭数字总数相同，就把 `reshape` 和 `transpose` 当成同一种操作。

这一章先把形状和轴的含义看清即可。需要注意内存时再记住：`reshape()` 可能返回共享数据的视图，也可能复制；`view()` 对内存布局要求更严格；如果确实需要独立副本，请明确使用 `clone()`。[PyTorch 的 reshape 文档](https://docs.pytorch.org/docs/stable/generated/torch.reshape.html)说明了这一点。

## 给每个 token 做同一笔计算

假设希望四个特征分别加上 1、2、3、4。不必写循环逐个处理 token，可以把长度为 4 的向量加到整个 `hidden` 上：

<<< @/public/tinyllm/code/tensors-and-autograd.py#broadcast

`bias` 对准最后一轴的四个特征；两条样本中的每个 token 都加同一组数。这叫<strong>广播</strong>。判断能否广播时，从形状最右边开始比较：两轴长度相等，或其中一轴为 1，才可以配对；缺少的左侧轴可看作长度为 1。`[2, 3, 4] + [4]` 可以，`[2, 3, 4] + [3]` 不可以，因为最后一轴的 4 和 3 对不上。[PyTorch 广播规则](https://docs.pytorch.org/docs/stable/notes/broadcasting.html)给出了完整定义。

![3 行 4 列的隐藏向量加上长度为 4 的偏置：偏置被看作一行并复制到三行，逐格相加得到同形状结果](/tinyllm/figures/broadcast.svg)

加法和 `*` 都是逐位置运算。如果要把一个 token 的<strong>四个旧特征组合成六个新特征</strong>，则要用矩阵乘法。设权重形状为 `[4, 6]`：

<<< @/public/tinyllm/code/tensors-and-autograd.py#matmul

`@` 在每个 token 上做一遍“长度 4 的向量 × 4 行 6 列的矩阵”。前两轴仍是 2 和 3，最后一轴变成 6。比如 `hidden[0, 1, :]` 是 `[4, 5, 6, 7]`，这里权重全为 1，因此六个输出都是 $4+5+6+7=22$。真实权重会在训练中改变，让模型学习不同的特征组合。

PyTorch 用 `nn.Linear(4, 6)` 封装这类计算。它内部存储的 `weight` 是 `[6, 4]`，计算时会转置权重，再加一个长度为 6 的偏置。因此输入 `[2, 3, 4]`，输出仍是 `[2, 3, 6]`：

<<< @/public/tinyllm/code/tensors-and-autograd.py#linear

到这里，张量已经能从输入走到输出。但权重一开始并不知道怎样产生“好”的输出。为了看清训练的原理，我们暂时把许多权重缩成<strong>一个参数</strong>。

## 一个参数怎样知道该往哪边走

给模型输入 $x=3$，希望它预测目标 $t=1$。模型只做一件事：用参数 $w$ 乘输入，预测值是 $wx$。如果从 $w=2$ 开始，预测是 6，离目标 1 很远。用平方误差衡量差距：

$$
p=wx,\qquad L=(p-t)^2
$$

此时 $L=(2\times3-1)^2=25$。$L$ 叫<strong>损失</strong>，数值越小表示这次预测越接近目标。模型要知道把 $w$ 往哪个方向调，先得知道：$w$ 增大一点，损失会怎样变化。这个变化率就是损失对 $w$ 的<strong>梯度</strong>。

我们先让 PyTorch 自己回答“梯度是多少”，暂时不写求导公式。把 $w$ 标记为需要学习的参数，再照平常写出预测和损失：

<<< @/public/tinyllm/code/tensors-and-autograd.py#autograd

这段代码没有写任何导数公式，却得到了 30。发生了什么？前向计算时，PyTorch 一面算数值，一面把依赖关系记下来：`w → 乘以 x → prediction → 减去 target → 平方 → loss`。`grad_fn` 不为空，说明结果知道自己由什么运算产生。调用 `loss.backward()` 后，自动求导从损失沿这些运算往回走，用各运算自带的求导规则和链式法则算到 `w`；结果保存在 `w.grad`。`x` 没有要求梯度，所以它的 `.grad` 仍是 `None`。这条从本次前向计算建立的关系叫<strong>计算图</strong>；下一次重新前向，会建立新的图。

把这个过程放慢来看。点“播放”：先从左往右算出数值（绿色），再从损失出发往左走，每经过一个运算就乘上它的局部导数（橙色），最后用梯度把 $w$ 更新一步：

<BackpropFlow />

现在才用手算核对自动求导的答案。把计算拆成 $p=wx$ 和 $L=(p-t)^2$ 两步：$p$ 每增加一点，损失的变化率是 $2(p-t)$；$w$ 每增加一点，$p$ 的变化率是 $x$。两段影响相乘，得到

$$
\frac{\partial L}{\partial w}
=\frac{\partial L}{\partial p}\frac{\partial p}{\partial w}
=2(p-t)x=2(wx-t)x=30.
$$

手算是检查工具；模型真正训练时，代码只需定义前向计算和损失，自动求导负责沿图传回梯度。这里的梯度为正，说明在当前位置把 $w$ 调大，损失会增大；想降低损失，就应把 $w$ 往小的方向调。梯度只描述<strong>当前位置附近</strong>的变化，不保证一步就能找到最好的参数。

模型也不会只有一个参数。下面给预测再加一个可学习偏置 $b$。我们没有手写 $b$ 的求导规则，`backward()` 仍会分别把梯度交给两个参数：

<<< @/public/tinyllm/code/tensors-and-autograd.py#two-params

两条路径都通向同一个损失：$w_2$ 经过乘法和加法，$b_2$ 经过加法。自动求导会沿各自的路径回传。只看结果也能理解差别：在当前点稍微改变 $b_2$，预测值等量改变，因此它的梯度是 10；稍微改变 $w_2$，预测值会改变输入 $x=3$ 倍，所以梯度是 30。参数一多，自动求导的价值就更明显了。`loss` 是标量，因此能直接调用 `backward()`；若结果是向量，通常先汇总成标量损失。[PyTorch 自动求导入门](https://docs.pytorch.org/tutorials/beginner/basics/autogradqs_tutorial.html)展示了相同的计算图机制。

## 算出梯度后，真正更新一次

可以按“旧参数减去学习率乘梯度”走一小步。学习率取 `0.01`，$w$ 从 2 变为 $2-0.01\times30=1.7$；同一个输入的预测从 6 降到 5.1，损失从 25 降到 $(5.1-1)^2=16.81$：

![损失曲线 (3w-1)^2 上，w=2 处切线斜率为 30；以学习率 0.01 更新到 w=1.7，损失从 25 降到 16.81](/tinyllm/figures/gradient-step.svg)

图里的橙色虚线是 $w=2$ 处的切线，斜率就是梯度 30。沿着让损失变小的方向（这里是向左）走一小步，就从 25 降到了 16.81。学习率决定这一步迈多大：太小走得慢，太大可能直接跨过谷底。

<<< @/public/tinyllm/code/tensors-and-autograd.py#update

`torch.no_grad()` 使这次手动更新不进入求导记录。真实训练通常用优化器执行参数更新；这里手动写出，是为了看清梯度的作用。

还有一个容易踩的坑：`backward()` 会把新梯度<strong>加到</strong> `.grad` 上。如果在更新前重新前向计算并反传同样的损失，却没有清空旧梯度，30 会累加为 60。准备下一步训练时，先清空：

<<< @/public/tinyllm/code/tensors-and-autograd.py#zero-grad

这里得到 $2\times(1.7\times3-1)\times3=24.6$，因为参数已经改变。如果想观察 <strong>30 变 60</strong>，应在更新前连续做两次独立前向与反传。实际训练循环通常在每步开头调用 `optimizer.zero_grad(set_to_none=True)`；有意累积多个小批次的梯度是 [第 18 章](gradient-stability.md) 要讲的策略。

## 从 1 个参数到几十万个：自动求导真正省下了什么

到这里，我们的例子只有一个、两个参数，手算比写代码还快。自动求导的价值要在参数多的时候才看得出来：[第 1 章](./first-run.md)那个会写诗的小模型有 39 万个参数，GPT-3 有 1750 亿个。训练的每一步，都要知道损失对**每一个**参数的偏导数，也就是在几十万、几千亿个方向上各问一次：“这个参数往大调一点点，损失会怎么变？”

### 笨办法：一个方向一个方向地试

最直接的做法，是把参数一个个挪一点点，重新算一次损失，看损失变了多少，这叫**数值差分**。有 $N$ 个参数，就要做 $N+1$ 次前向计算：1 次算原来的损失，再每个参数各 1 次。

下面在一个只有 144 个参数的小网络上，真的用这个笨办法把梯度算一遍，再和 autograd 一次 `backward()` 的结果对照：

<<< @/public/tinyllm/code/tensors-and-autograd.py#finite-diff

差分做了 145 次前向，和 autograd 的结果最多只差约 $10^{-7}$，说明两者算的是同一个东西。区别在代价：144 个参数要 145 次前向，39 万个参数就要约 39 万次前向，而这只是训练的一步。

### 反向传播：一次就拿到所有方向

autograd 用的是**反向模式**：从损失这一个数出发，沿计算图往回走一遍，每经过一个运算就乘上它的局部导数，走完一遍，所有参数的梯度同时得到。下面这个 13 万参数的网络，一次 `backward()` 之后，每个参数都有了梯度：

<<< @/public/tinyllm/code/tensors-and-autograd.py#many-params

我在 CPU 上把参数量从 40 个一路加到约 210 万个，量了两种做法各要多少时间，都换算成“相当于几次前向”：

![参数从 40 个增加到约 210 万个：逐个参数做差分需要 N+1 次前向，随参数量线性增长，第 1 章 39 万参数的模型要约 39 万次；一次前向加反向传播实测始终只相当于 3 到 7 次前向，与参数量无关](/tinyllm/figures/autograd-cost.svg)

橙色那条线随参数量一路往上，参数多 10 倍，差分就要多做 10 倍的前向。绿色那条线几乎是平的：不管参数是 40 个还是 210 万个，一次前向加反向只相当于 3～7 次前向的时间，模型越大越接近 3 次（210 万参数时是 3.5 次）。小模型那几个点偏高，是因为计算量太小，Python 调用本身的开销占了大头。这条平线，就是神经网络能训练到几千亿参数的前提。

### 为什么一次就够：只有一个出口

关键在于损失只是**一个数**。从一个出口往回走，沿途每个参数都能分到“自己对这个数的影响”，一趟就分完了。反过来，如果从输入出发往前推（前向模式），每次只能跟踪一个输入方向，有多少个参数就要推多少遍，又回到了和差分一样的次数。深度学习里输入方向（参数）多、输出只有一个损失，所以选反向模式；这就是常说的**反向传播**（backpropagation）。

### 每一步也不做多余的事：不构造雅可比矩阵

往回走的每一步，按教科书写法是“上游梯度乘这个运算的雅可比矩阵”。但雅可比矩阵本身可能大得吓人，PyTorch 从来不把它算出来，而是让每个算子直接给出“上游梯度乘雅可比”的结果：

![前向 y = x @ W；反向已知 g = dL/dy，直接算 dL/dW = xᵀg 和 dL/dx = gWᵀ，两次矩阵乘法的计算量与前向同一量级。若先构造完整雅可比矩阵 dy/dW，在 d_in = d_out = 4096 时就有约 687 亿个数，FP32 下约 275 GB](/tinyllm/figures/vjp-matmul.svg)

以矩阵乘法 `y = x @ W` 为例，反向时只需要 `x.T @ g` 和 `g @ W.T` 两次矩阵乘法，计算量和前向是同一个量级。小例子里可以把完整的雅可比矩阵真的算出来对比一下：

<<< @/public/tinyllm/code/tensors-and-autograd.py#vjp

`W` 只有 12 个数，它的雅可比矩阵已经有 96 个数；矩阵一大，这个比例会爆炸。这种“直接算上游梯度乘雅可比”的运算叫**向量-雅可比积**（VJP），PyTorch 里几乎每个算子都配了一个，`backward()` 就是把它们沿计算图串起来。

### 代价：用内存换时间

反向传播也有代价。往回走时要用到前向时的中间结果，比如上面的 `x.T @ g` 就需要前向时的 `x`。所以前向过程中，每一层的输出都要先存着，等反向用完才能释放。模型越深、batch 越大，这部分内存越多；训练比推理吃显存，主要就是这个原因。显存不够时可以少存一些、反向时再重算一遍（gradient checkpointing），用时间换回内存，这在[第 19 章](./training-loop.md)和[第 21 章](./large-model-stability.md)再展开。

现在把全章连起来看：<strong>张量装输入 → 运算得到预测 → 与目标比较得到损失 → <code>backward()</code> 算梯度 → 更新参数 → 再次预测。</strong>语言模型的运算更复杂、参数更多，但训练的骨架就是这一串。

## 用 notebook 检查几个常见问题

前面的主线足够理解本章。配套 notebook 还安排了几组实验，帮助你读后面的模型代码：

1. <strong>轴交换。</strong>注意力里的 Q、K 通常有 `[batch, heads, seq, head_dim]` 四个轴。`q @ k.transpose(-2, -1)` 交换 K 的最后两轴，得到 `[batch, heads, query_len, key_len]` 的分数。先能解释前三轴为何保留，再读这行代码；完整注意力机制留到 第 5 章。
2. <strong>梯度核对。</strong>把 $w$ 分别改为 $w+h$ 和 $w-h$，用 $[L(w+h)-L(w-h)]/(2h)$ 估计梯度。这叫中心差分，是近似值；在适当的 $h$ 和 `float64` 下，应接近手算与自动求导得到的 30。
3. <strong>停止记录梯度。</strong>`no_grad()` 阻止代码块中的新运算进入求导图；`detach()` 使已有结果脱离原图；`model.eval()` 只改变某些层（如 Dropout）的运行方式，本身不会关闭梯度记录。
4. <strong>计算设备。</strong>CPU 足够运行本章。若把模型放在 CUDA 或 MPS 上，输入也要放在同一设备。notebook 的可选实验只检查小型前向和反向能否运行。MLX 是另一套框架，`mx.grad` 与 PyTorch 的 `backward()` 不能混用。

## 本章结论：TinyLLM 的选择 {#tinyllm-choice}

训练时用 <strong>PyTorch autograd</strong> 管理计算图，手算和有限差分只用于核验小例子。这样可以在更换归一化、注意力或门控结构时保留正确的链式求导；若出现梯度异常，先检查张量形状、原地操作和图是否被意外断开。后续章节的架构选择见 [课程总览](index.md#mainline-choices)。

## 检查理解

1. `[2, 3, 4]` 的三轴各表示什么？

   <details><summary>参考答案</summary>

   2 条样本（batch）× 每条 3 个 token（seq）× 每个 token 4 个特征（hidden）。

   </details>

2. 形状为 `[4]` 的偏置为什么能加到 `[2, 3, 4]` 上？`[3]` 为什么不行？

   <details><summary>参考答案</summary>

   从最右一轴对齐：4 对 4 相等，左边缺的两轴当作 1 并沿它们复制。`[3]` 的最右轴是 3，与 4 不等也不为 1，无法配对。

   </details>

3. $w=2,x=3,t=1$ 时，梯度为什么是 30？

   <details><summary>参考答案</summary>

   $p=wx=6$，$\partial L/\partial p=2(p-t)=10$，$\partial p/\partial w=x=3$，链式法则相乘得 30。

   </details>

4. 在更新参数前连续做两次前向和 `backward()`，`w.grad` 是多少？为什么？

   <details><summary>参考答案</summary>

   60。`backward()` 把新梯度加到 `.grad` 上而不是覆盖，所以训练循环每步都要先清空梯度。

   </details>

5. 一个模型有 100 万个参数。用数值差分求全部梯度大约要几次前向？用一次 `backward()` 呢？为什么差这么多？

   <details><summary>参考答案</summary>

   差分约要 100 万零 1 次前向，每个参数一次。`backward()` 实测只相当于 3 次左右前向：损失只有一个数，从它出发沿计算图往回走一遍，就能把影响分到所有参数上；每个算子还直接计算“上游梯度乘雅可比”，不构造雅可比矩阵。

   </details>

## 参考资料

- [PyTorch《通过实例学习 PyTorch》：张量与自动求导](https://docs.pytorch.ac.cn/tutorials/beginner/pytorch_with_examples.html)（本章沿用它的学习顺序，换成 TinyLLM 的形状和可手算的例子）
- [PyTorch 广播规则](https://docs.pytorch.org/docs/stable/notes/broadcasting.html) · [自动求导入门](https://docs.pytorch.org/tutorials/beginner/basics/autogradqs_tutorial.html)

工具备齐了。下一章开始沿着总图从上往下搭模型，第一步是把文字变成编号：[第 3 章：文本与词元化](./tokenization.md)。
