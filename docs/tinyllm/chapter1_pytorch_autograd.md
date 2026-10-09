# Chapter 1：PyTorch 张量与自动求导

上一章里，我们看到归一化层接收一串数字，又输出一串数字。真正写模型时，程序还要回答两个问题：<strong>这些数字怎样排在一起？模型怎样知道哪些参数需要调整？</strong>前一个问题靠张量和形状回答，后一个问题靠自动求导回答。本章沿着一次小模型计算，把它们串起来。

可以边读边运行 <a href="/tinyllm/chapter1_PyTorch_Autograd/ch1.ipynb" download>ch1.ipynb</a>。先用 CPU 即可；每遇到一个形状或结果，先自己猜，再运行代码核对。本文中的“token”暂时理解为文本中的一个编号；词元化的细节留到 Chapter 4。

## 从一批 token 到隐藏向量

假设有两句话，每句话都取三个 token。用整数给它们编号：

```python
import torch

token_ids = torch.tensor([[1, 2, 3], [4, 5, 6]], dtype=torch.long)
print(token_ids.shape)  # torch.Size([2, 3])
```

外层有两行，表示两句话；每行有三个数，表示三个 token。所以形状 `[2, 3]` 的两个位置分别是<strong>样本数</strong>和<strong>每条样本的 token 数</strong>，常记作 `[batch, seq]`。形状是张量的“尺寸说明”；轴名是我们根据用途给它的解释，PyTorch 并不知道第二轴一定是句子长度。

token 编号只是索引，不能直接告诉模型“这个词有什么特征”。假设后续步骤把每个编号变成四个浮点数，那么一批隐藏向量就有三个轴：

```python
hidden = torch.arange(24, dtype=torch.float32).reshape(2, 3, 4)
print(hidden.shape)       # torch.Size([2, 3, 4])
print(hidden[0, 1, :])    # tensor([4., 5., 6., 7.])
```

`[2, 3, 4]` 读作：<strong>2 条样本 × 每条 3 个 token × 每个 token 4 个特征</strong>，简写为 `[batch, seq, hidden]`。`hidden[0, 1, :]` 选中第一条样本的第二个 token；最后的 `:` 表示取它的全部四个特征。索引从 0 开始。`torch.arange(24)` 只是为演示形状填入 0 到 23，真实隐藏向量来自模型计算。

看张量时再留意三个属性：`ndim` 是轴数，`dtype` 是每个数的类型，`device` 是它存放和计算的位置。上面的 `token_ids` 是整数；`hidden` 是浮点数。可训练参数通常也是浮点数。`torch.tensor(...)` 用现有数据创建张量，`torch.zeros(...)` 创建全零张量，`torch.randn(...)` 创建随机张量；模型参数该怎样初始化要在 [Chapter 2](chapter2_initialization_residuals.md) 再讨论。

## 改变形状，还是交换轴？

原来的 `[2, 3, 4]` 一共有 $2\times3\times4=24$ 个数。`reshape(2, 12)` 把每条样本的 `3×4` 个位置合在一轴，数字总数不变：

```python
flat = hidden.reshape(2, 12)
print(flat.shape)  # torch.Size([2, 12])
```

`transpose` 做的是另一件事：<strong>交换轴</strong>。`hidden.transpose(1, 2)` 得到 `[2, 4, 3]`。原来第二轴代表 token、第三轴代表特征；交换后，第二轴代表特征、第三轴代表 token。不能仅凭数字总数相同，就把 `reshape` 和 `transpose` 当成同一种操作。

这一章先把形状和轴的含义看清即可。需要注意内存时再记住：`reshape()` 可能返回共享数据的视图，也可能复制；`view()` 对内存布局要求更严格；如果确实需要独立副本，请明确使用 `clone()`。[PyTorch 的 reshape 文档](https://docs.pytorch.org/docs/stable/generated/torch.reshape.html)说明了这一点。

## 给每个 token 做同一笔计算

假设希望四个特征分别加上 1、2、3、4。不必写循环逐个处理 token，可以把长度为 4 的向量加到整个 `hidden` 上：

```python
bias = torch.tensor([1., 2., 3., 4.])
shifted = hidden + bias
print(shifted.shape)       # torch.Size([2, 3, 4])
print(shifted[0, 1, :])    # tensor([5., 7., 9., 11.])
```

`bias` 对准最后一轴的四个特征；两条样本中的每个 token 都加同一组数。这叫<strong>广播</strong>。判断能否广播时，从形状最右边开始比较：两轴长度相等，或其中一轴为 1，才可以配对；缺少的左侧轴可看作长度为 1。`[2, 3, 4] + [4]` 可以，`[2, 3, 4] + [3]` 不可以，因为最后一轴的 4 和 3 对不上。[PyTorch 广播规则](https://docs.pytorch.org/docs/stable/notes/broadcasting.html)给出了完整定义。

加法和 `*` 都是逐位置运算。如果要把一个 token 的<strong>四个旧特征组合成六个新特征</strong>，则要用矩阵乘法。设权重形状为 `[4, 6]`：

```python
weight = torch.ones(4, 6)
out = hidden @ weight
print(out.shape)          # torch.Size([2, 3, 6])
print(out[0, 1, :])       # tensor([22., 22., 22., 22., 22., 22.])
```

`@` 在每个 token 上做一遍“长度 4 的向量 × 4 行 6 列的矩阵”。前两轴仍是 2 和 3，最后一轴变成 6。比如 `hidden[0, 1, :]` 是 `[4, 5, 6, 7]`，这里权重全为 1，因此六个输出都是 $4+5+6+7=22$。真实权重会在训练中改变，让模型学习不同的特征组合。

PyTorch 用 `nn.Linear(4, 6)` 封装这类计算。它内部存储的 `weight` 是 `[6, 4]`，计算时会转置权重，再加一个长度为 6 的偏置。因此输入 `[2, 3, 4]`，输出仍是 `[2, 3, 6]`：

```python
linear = torch.nn.Linear(4, 6)
print(linear.weight.shape)   # torch.Size([6, 4])
print(linear(hidden).shape)  # torch.Size([2, 3, 6])
```

到这里，张量已经能从输入走到输出。但权重一开始并不知道怎样产生“好”的输出。为了看清训练的原理，我们暂时把许多权重缩成<strong>一个参数</strong>。

## 一个参数怎样知道该往哪边走

给模型输入 $x=3$，希望它预测目标 $t=1$。模型只做一件事：用参数 $w$ 乘输入，预测值是 $wx$。如果从 $w=2$ 开始，预测是 6，离目标 1 很远。用平方误差衡量差距：

$$
p=wx,\qquad L=(p-t)^2
$$

此时 $L=(2\times3-1)^2=25$。$L$ 叫<strong>损失</strong>，数值越小表示这次预测越接近目标。模型要知道把 $w$ 往哪个方向调，先得知道：$w$ 增大一点，损失会怎样变化。这个变化率就是损失对 $w$ 的<strong>梯度</strong>。

我们先让 PyTorch 自己回答“梯度是多少”，暂时不写求导公式。把 $w$ 标记为需要学习的参数，再照平常写出预测和损失：

```python
w = torch.nn.Parameter(torch.tensor(2.0))
x = torch.tensor(3.0)
target = torch.tensor(1.0)

prediction = w * x
loss = (prediction - target).square()

print(w.requires_grad)           # True：需要计算 w 的梯度
print(x.requires_grad)           # False：不需要计算输入 x 的梯度
print(w.grad)                    # None：此时还没有反向计算
print(prediction.grad_fn is not None)  # True：乘法被记录下来
print(loss.grad_fn is not None)        # True：损失也连在计算图上

loss.backward()

print(prediction.item())  # 6.0
print(loss.item())        # 25.0
print(w.grad.item())      # 30.0
```

这段代码没有写任何导数公式，却得到了 30。发生了什么？前向计算时，PyTorch 一面算数值，一面把依赖关系记下来：`w → 乘以 x → prediction → 减去 target → 平方 → loss`。`grad_fn` 不为空，说明结果知道自己由什么运算产生。调用 `loss.backward()` 后，自动求导从损失沿这些运算往回走，用各运算自带的求导规则和链式法则算到 `w`；结果保存在 `w.grad`。`x` 没有要求梯度，所以它的 `.grad` 仍是 `None`。这条从本次前向计算建立的关系叫<strong>计算图</strong>；下一次重新前向，会建立新的图。

现在才用手算核对自动求导的答案。把计算拆成 $p=wx$ 和 $L=(p-t)^2$ 两步：$p$ 每增加一点，损失的变化率是 $2(p-t)$；$w$ 每增加一点，$p$ 的变化率是 $x$。两段影响相乘，得到

$$
\frac{\partial L}{\partial w}
=\frac{\partial L}{\partial p}\frac{\partial p}{\partial w}
=2(p-t)x=2(wx-t)x=30.
$$

手算是检查工具；模型真正训练时，代码只需定义前向计算和损失，自动求导负责沿图传回梯度。这里的梯度为正，说明在当前位置把 $w$ 调大，损失会增大；想降低损失，就应把 $w$ 往小的方向调。梯度只描述<strong>当前位置附近</strong>的变化，不保证一步就能找到最好的参数。

模型也不会只有一个参数。下面给预测再加一个可学习偏置 $b$。我们没有手写 $b$ 的求导规则，`backward()` 仍会分别把梯度交给两个参数：

```python
w2 = torch.nn.Parameter(torch.tensor(2.0))
b2 = torch.nn.Parameter(torch.tensor(0.0))
prediction2 = w2 * x + b2
loss2 = (prediction2 - target).square()
loss2.backward()
print(w2.grad.item(), b2.grad.item())  # 30.0 10.0
print(x.grad)                           # None
```

两条路径都通向同一个损失：$w_2$ 经过乘法和加法，$b_2$ 经过加法。自动求导会沿各自的路径回传。只看结果也能理解差别：在当前点稍微改变 $b_2$，预测值等量改变，因此它的梯度是 10；稍微改变 $w_2$，预测值会改变输入 $x=3$ 倍，所以梯度是 30。参数一多，自动求导的价值就更明显了。`loss` 是标量，因此能直接调用 `backward()`；若结果是向量，通常先汇总成标量损失。[PyTorch 自动求导入门](https://docs.pytorch.org/tutorials/beginner/basics/autogradqs_tutorial.html)展示了相同的计算图机制。

## 算出梯度后，真正更新一次

可以按“旧参数减去学习率乘梯度”走一小步。学习率取 `0.01`，$w$ 从 2 变为 $2-0.01\times30=1.7$；同一个输入的预测从 6 降到 5.1，损失从 25 降到 $(5.1-1)^2=16.81$：

```python
with torch.no_grad():
    w -= 0.01 * w.grad

new_loss = (w * x - target).square()
print(w.item())         # 约 1.7
print(new_loss.item())  # 约 16.81
```

`torch.no_grad()` 使这次手动更新不进入求导记录。真实训练通常用优化器执行参数更新；这里手动写出，是为了看清梯度的作用。

还有一个容易踩的坑：`backward()` 会把新梯度<strong>加到</strong> `.grad` 上。如果在更新前重新前向计算并反传同样的损失，却没有清空旧梯度，30 会累加为 60。准备下一步训练时，先清空：

```python
w.grad = None
loss = (w * x - target).square()
loss.backward()
print(w.grad.item())  # 对应更新后的 w，约为 24.6
```

这里得到 $2\times(1.7\times3-1)\times3=24.6$，因为参数已经改变。如果想观察 <strong>30 变 60</strong>，应在更新前连续做两次独立前向与反传。实际训练循环通常在每步开头调用 `optimizer.zero_grad(set_to_none=True)`；有意累积多个小批次的梯度是 [Chapter 16](chapter16_gradient_stability.md) 要讲的策略。

现在把全章连起来看：**张量装输入 → 运算得到预测 → 与目标比较得到损失 → `backward()` 算梯度 → 更新参数 → 再次预测。**语言模型的运算更复杂、参数更多，但训练的骨架就是这一串。

## 用 notebook 检查几个常见问题

前面的主线足够理解本章。配套 notebook 还安排了几组实验，帮助你读后面的模型代码：

1. <strong>轴交换。</strong>注意力里的 Q、K 通常有 `[batch, heads, seq, head_dim]` 四个轴。`q @ k.transpose(-2, -1)` 交换 K 的最后两轴，得到 `[batch, heads, query_len, key_len]` 的分数。先能解释前三轴为何保留，再读这行代码；完整注意力机制留到 Chapter 7。
2. <strong>梯度核对。</strong>把 $w$ 分别改为 $w+h$ 和 $w-h$，用 $[L(w+h)-L(w-h)]/(2h)$ 估计梯度。这叫中心差分，是近似值；在适当的 $h$ 和 `float64` 下，应接近手算与自动求导得到的 30。
3. <strong>停止记录梯度。</strong>`no_grad()` 阻止代码块中的新运算进入求导图；`detach()` 使已有结果脱离原图；`model.eval()` 只改变某些层（如 Dropout）的运行方式，本身不会关闭梯度记录。
4. <strong>计算设备。</strong>CPU 足够运行本章。若把模型放在 CUDA 或 MPS 上，输入也要放在同一设备。notebook 的可选实验只检查小型前向和反向能否运行。MLX 是另一套框架，`mx.grad` 与 PyTorch 的 `backward()` 不能混用。

读完后，试着不看代码回答三件事：`[2, 3, 4]` 的三轴各表示什么？`[4]` 的偏置为什么能加到它上面？$w=2,x=3,t=1$ 时，梯度为什么是 30？如果能把这三个答案串成一段话，就已经抓住本章主线。

本文参考 [PyTorch《通过实例学习 PyTorch》中的“张量”和“张量与自动求导”两节](https://docs.pytorch.ac.cn/tutorials/beginner/pytorch_with_examples.html)的学习顺序，并换成 TinyLLM 的形状和一个可手算的参数示例。下一章看 [初始化与残差路径](chapter2_initialization_residuals.md)：参数从哪里开始，以及信息怎样经过更深的网络。返回 [课程总目录](index.md#课程路线规划)。
