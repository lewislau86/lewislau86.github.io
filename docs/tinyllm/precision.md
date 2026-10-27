---
title: "第 17 章：数值精度与混合精度"
description: "FP32、FP16、BF16 各能表示什么；舍入、溢出与下溢从哪里来；混合精度与 autocast 怎样工作。"
pageClass: tinyllm-course
next: false
---

# 第 17 章：数值精度与混合精度

[课程总览](./index.md) · [上一章](./regularization.md) · [下一章](./gradient-stability.md)

::: tip 本章学习目标
区分“范围太窄导致溢出/下溢”和“刻度太粗导致舍入”；说明输入、中间累加和输出为何可能使用不同精度；读懂 `torch.autocast` 的基本用法。

**前置：** 张量与矩阵乘法；[第 4 章](./normalization.md)的归一化。

**实践方式：** <a href="/tinyllm/notebooks/precision.ipynb" download>precision.ipynb</a>，基础实验只需 CPU；有 CUDA、MPS 或 MLX 时可运行加速实验。
:::

本章回答三个问题：<strong>What：浮点数到底能表示什么？How：计算误差从哪里来，混合精度怎样工作？Do：如何用代码观察并检查这些现象？</strong>配套实验见 <a href="/tinyllm/notebooks/precision.ipynb" download>precision.ipynb</a>。只需了解张量、矩阵乘法和 [第 4 章的归一化](normalization.md)。基础实验可在 PyTorch CPU 运行；有 CUDA、PyTorch MPS 或 MLX 时还可运行对应的加速实验。

学完后，你应能区分“范围太窄导致溢出/下溢”和“刻度太粗导致舍入”，说明为何输入、计算中间值和输出可能使用不同精度，并能读懂 `torch.autocast` 的基本用法。这里聚焦前向数值和混合精度；梯度裁剪、FP16 Loss Scaling 与训练循环放在规划中的 第 18～19 章。

<TinyLLMMap active="precision" />

## What：浮点数是什么？

### 1. 科学计数法，但可用位数有限

把浮点数想成二进制科学计数法：符号决定正负，<strong>指数</strong>决定数值能覆盖多大的范围，<strong>尾数</strong>决定相近的数能分得多细。下面是常见格式的位数（不含隐藏的有效位）；较宽的指数意味着较大的动态范围，较多的尾数位意味着较密的刻度。

| 格式                     | 总位数 | 符号/指数/尾数位  | 直观取舍                     |
| ---------------------- | --: | ---------- | ------------------------ |
| FP32（`torch.float32`）  |  32 | 1 / 8 / 23 | 范围较宽，刻度较细；本章数值参照         |
| FP16（`torch.float16`）  |  16 | 1 / 5 / 10 | 比 BF16 刻度细，但范围窄，易遇到溢出或下溢 |
| BF16（`torch.bfloat16`） |  16 | 1 / 8 / 7  | 范围接近 FP32，但刻度比 FP16 粗    |

三个重要数字可由 `torch.finfo(dtype)` 查询：`eps` 是 <strong>1 与下一个可表示数的距离</strong>，`tiny` 是最小<strong>正规</strong>正数，`max` 是最大有限数。`tiny` 不是最小非零数：有些设备/运算还能表示更小的非正规数。`torch.finfo(dtype).eps` 也不是 `nn.LayerNorm(eps=...)` 中为防止除零而设置的超参数。[PyTorch 类型信息](https://docs.pytorch.org/docs/stable/type_info.html)

```python
import torch
for dtype in (torch.float32, torch.float16, torch.bfloat16):
    info = torch.finfo(dtype)
    print(dtype, info.eps, info.tiny, info.max)
```

<strong>舍入</strong>：实数落在两条刻度之间，只能存为附近的可表示数。例如 `1000` 与 `1001` 转成 BF16 后可能相同，而 FP16 仍能区分它们。<strong>溢出</strong>：结果大到超出范围，可能得到 `inf`；<strong>下溢</strong>：非零小数太小，在特定运算路径中可能变为零。`NaN` 表示无效数值结果，例如 `inf / inf`。具体舍入、非正规数和中间计算行为可能随硬件与算子而变。

### 2. 什么叫“数值稳定”？

数学上等价的写法，在有限精度的计算机里未必同样可靠。例如数学上 `softmax([1000,1001,1002])` 没问题；直接计算 `exp(1000)` 会溢出。先减去最大值，再求指数，数学结果不变，却让参与 `exp` 的数不大于 0：

$$
\mathrm{softmax}(x_i)=\frac{\exp(x_i-m)}{\sum_j\exp(x_j-m)},\qquad m=\max_j x_j.
$$

这里“稳定”是<strong>改写计算路径，让中间值更容易保持有限</strong>，不是给浮点格式增加有效位。PyTorch 的 `torch.softmax` 可直接调用；教学实验中的“直接 `exp`”只用于展示风险。即使结果有限，仍要与高精度参考比较误差。<strong>减最大值只避免指数溢出，不能解决注意力分数差距过大造成的 softmax 饱和</strong>：此时输出仍有限，但概率可能接近 0 或 1。[PyTorch 数值精度说明](https://docs.pytorch.org/docs/stable/notes/numerical_accuracy.html)

### 2.1 精度问题在其他章节出现在哪里？

第 17 章讲的是贯穿各处的<strong>有限精度计算规则</strong>。下面按数据经过模型、产生梯度、更新参数的顺序看它与课程主题的关系。表中的“对应章节”指课程目录；尚未完成的章节是后续要展开的主题。

| 位置与现象                 | 精度问题是什么                                                            | 对应章节要讲什么                                                                                                                                                              |
| --------------------- | ------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 初始化和深层残差：激活逐层变大或变小    | FP16 中间结果可能溢出或下溢；即使保持有限，也可能有舍入误差                                   | [第 3 章](initialization-and-residuals.md)与[第 25 章](large-model-stability.md)分别讲初始化/残差缩放及更深网络的稳定结构；本章提供判断数值范围的方法。                                                                                                     |
| 归一化：计算均值、方差或均方根       | 平方、求和、减均值也受 dtype 影响；归一化只能控制所在位置及后续的尺度                             | [第 4 章](normalization.md) 讲算法和位置；本章解释 FP16/BF16 的表示范围与中间精度。                                    |
| 注意力：Q/K 点积进入 softmax  | 点积可能过大；即使减最大值防止 `exp` 溢出，分数差距很大时概率仍可接近 0/1                         | 第 9 章讲缩放点积、mask 和 softmax；[第 9 章的 QK Norm](self-attention.md#qk-norm) 讲怎样在点积前控制 Q/K 尺度。 |
| 语言模型损失：用 logits 计算交叉熵 | 直接先算概率、再取对数可能产生 `log(0)`；稳定的 log-sum-exp 计算路径更合适                   | 第 13 章讲交叉熵和 loss mask；本章的 softmax 实验提供数值直觉。                                                                                                                      |
| 反向传播：梯度很小或很大          | FP16 小梯度可能下溢；大梯度或中间反向值可能溢出。Loss Scaling 主要处理前者，梯度裁剪用于限制梯度范数，两者目的不同 | 第 18 章讲 `GradScaler`、裁剪与梯度累积；本章只讲浮点格式为何会遇到这些问题。                                                                                                                  |
| 优化器与训练循环：更新量很小        | 低精度舍入可能使很小的更新难以反映在参数中；前向的 `NaN/inf` 也会传到损失和梯度                      | 第 14 章讲参数更新，第 19 章讲 autocast、backward 和 step 的调用顺序，第 20 章讲监测 loss、梯度与非有限值。                                                                             |

<strong>读表时分清三类“稳定”：</strong>数值稳定关注 `inf/NaN` 与误差；训练稳定关注梯度、损失和参数更新是否可持续；泛化关注模型在未见数据上的表现。它们有关联，但不能用“没有 `NaN`”证明训练会收敛，也不能用“训练 loss 下降”证明所有数值运算都准确。

## How：精度怎样影响 LLM 计算？

### 3. 输入、累加、输出是三个不同环节

看 `a @ b` 时至少问三件事：输入张量存为哪种 dtype？乘积与累加使用哪种精度？结果存为哪种 dtype？只看输入或输出的 `dtype`，无法推出内核所有中间值的精度。点积、注意力分数和归一化统计量都有求和过程；乘法单项可表示，也不保证和仍能表示。PyTorch 说明不同后端的算法与累加策略可能不同，因此数值实验要记录设备、版本和 dtype。[PyTorch 数值精度说明](https://docs.pytorch.org/docs/stable/notes/numerical_accuracy.html)

两个典型误区：

* <strong>“BF16 范围宽，所以一定更准确。”</strong>在较大的数附近，BF16 可能比 FP16 更早丢失微小差异。
* **“算出 `inf` 后转 FP32 就能修复。”类型转换不会找回已经溢出或舍入的信息；应在敏感运算之前**安排合适的范围和计算 dtype。

### 4. 归一化能帮什么，不能帮什么？ {#normalization-and-precision}

把 FP16 想成一把**刻度有限、量程也有限**的尺子。归一化不会给这把尺子增加刻度，它改变的是送进**后续运算**的数值大小。以 RMSNorm 为例，一个向量除以自己的均方根后，均方根约为 1（忽略 `eps` 和可学习缩放）；后续的矩阵乘法、平方或注意力点积遇到极大数值而溢出的机会就小了。这是“控制数值范围”，不是“提高格式精度”。

例如，FP16 能存下 `1000`，却存不下 `1000 × 1000`。若先在安全的计算路径中把一组约为 `1000` 的激活归一化到约为 1，再转成 FP16 去平方，结果就能保持有限。**顺序很重要**：如果归一化内部已经用低精度算出了 `inf`，或者输入在转换时已经丢掉了小差异，事后归一化都修不回来。

归一化也不是低精度的安全保证：

- 除以很小的 RMS 或标准差会放大噪声，所以公式里必须有 `eps`；
- 可学习缩放、后面的线性层和残差相加又可能把数值重新放大；
- BF16 范围宽但刻度粗，较大基数上的微小差异可能在输入转换时就消失，这对需要先减均值的 LayerNorm 影响尤其明显。

| dtype | 主要特点 | 归一化中的典型风险 |
| --- | --- | --- |
| FP32 | 范围和有效精度都较高 | 作为数值参考，不同内核仍可能有细微差异 |
| FP16 | 有效精度比 BF16 高，但范围窄 | 很小的数下溢或舍入为 0；平方和累加可能溢出 |
| BF16 | 指数范围接近 FP32，有效精度更低 | 较大基数上的小差异在转换时消失 |

框架内置的 `nn.LayerNorm`、`nn.RMSNorm` 通常会在内部用更高精度计算统计量。自己手写归一化时，可以显式用 `x.float()` 算平方均值和除法，再转回输入 dtype；这只保护转换之后的计算，不能弥补已经发生的输入舍入。判断效果时分别看三件事：激活是否有限、离 FP32 参考有多远、训练是否收敛。不能只凭“归一化后约为 1”就认为整个网络在低精度下都安全。

<a href="/tinyllm/notebooks/normalization.ipynb" download>normalization.ipynb</a> 的低精度单元格演示了三种情况：FP16 对微小值的舍入或下溢、BF16 在较大基数上丢失小差异、先低精度平方与先转 FP32 再平方的差别，最后比较 `nn.LayerNorm`、`nn.RMSNorm` 在 FP32/FP16/BF16 输入上的输出误差。

### 5. 混合精度与 `autocast`

全部使用 FP32 简单，但显存和计算成本可能较高。混合精度让框架按<strong>算子</strong>选择执行 dtype：例如某些矩阵乘法适合低精度，而某些求和、归一化或损失计算可能采用更高精度路径。`torch.autocast` 会按设备和算子策略自动选择；<strong>并非所有算子都会转为同一种 dtype</strong>，具体策略可随设备和 PyTorch 版本变化。[PyTorch AMP 文档](https://docs.pytorch.org/docs/stable/amp.html)

```python
# model 保持 FP32 参数；输入也从 FP32 开始。
# CUDA/MPS 上先试 FP16；CPU 示例使用 BF16。
device = torch.device("cuda" if torch.cuda.is_available() else
                      "mps" if torch.backends.mps.is_available() else "cpu")
amp_dtype = torch.float16 if device.type in ("cuda", "mps") else torch.bfloat16
model = torch.nn.Sequential(torch.nn.Linear(4, 4), torch.nn.LayerNorm(4))
x = torch.randn(2, 4)
model, x = model.to(device), x.to(device)
with torch.autocast(device_type=device.type, dtype=amp_dtype):
    y = model(x)
print(y.dtype)  # 这是最终输出 dtype，不代表所有内部算子的 dtype
```

`autocast` <strong>不是</strong>把模型整体调用 `.half()` 或 `.bfloat16()`：后者直接改变参数/输入的存储 dtype，还可能使敏感运算失去 FP32 输入。本章 notebook 用固定矩阵比较 FP32 与手动转换后的误差，再用同一小模型比较 FP32 与 autocast；CUDA/MPS 可用时还会计时。MPS 的算子策略可能与 CUDA 不同，须打印实际输出 dtype。<strong>不预设低精度必定更快或占用更少内存</strong>；框架还可能为转换、临时缓冲区和缓存额外分配内存。

### 6. PyTorch MPS 与 MLX

Apple silicon 上有两条独立路径：PyTorch 的 `device="mps"` 仍使用 PyTorch 张量与 `torch.autocast`；[MLX](https://ml-explore.github.io/mlx/build/html/) 使用 `mlx.core`/`mlx.nn` 自己的数组与模块。<strong>MLX 不是 PyTorch 的一个 device 字符串</strong>，不能把 `torch.Tensor.to("mlx")` 当作调用方式。notebook 的 MLX 可选实验分别使用 `mx.array`、`mx.finfo`、`mlx.nn.LayerNorm` 和 `mx.eval`，与 PyTorch 实验观察同样的舍入、尺度及有限值问题。MLX 惰性求值，计时时必须 `mx.eval`。安装方式和平台要求见 [MLX 官方安装文档](https://ml-explore.github.io/mlx/build/html/install.html)。

FP16 训练中的 `torch.amp.GradScaler` 用来降低小梯度下溢风险；它不修复前向计算中的溢出，也不是 BF16 一定需要的步骤。梯度缩放、反向传播以及裁剪顺序留给 第 18 章。[PyTorch AMP 示例](https://docs.pytorch.org/docs/stable/notes/amp_examples.html)

## Do：运行并解释实验

打开 <a href="/tinyllm/notebooks/precision.ipynb" download>precision.ipynb</a>，从上往下运行：

| 实验                 | 主要 PyTorch 调用                                      | 该看什么                                                  |
| ------------------ | -------------------------------------------------- | ----------------------------------------------------- |
| 1. 刻度与范围           | `torch.finfo`、`Tensor.to(dtype)`                   | `eps/tiny/max`；1000 附近的舍入                             |
| 2. 下溢与溢出           | `Tensor.square`、`torch.isfinite`                   | 输入有限时，中间值是否仍有限                                        |
| 3. 稳定 softmax      | `torch.exp`、`torch.softmax`                        | 同一数学目标的不同计算路径                                         |
| 4. 矩阵乘法误差          | `@`、`.double()`、`.float()`                         | 用 FP64 参考，比较绝对误差；不把一次结果推广到所有硬件                        |
| 5. autocast        | `torch.autocast`、`nn.Linear`、`nn.LayerNorm`        | 记录各阶段输出 dtype；区分参数存储与算子输出                             |
| 6. CUDA/MPS 性能（可选） | `torch.cuda.synchronize` / `torch.mps.synchronize` | 同一 PyTorch 模型的耗时；CUDA 记录峰值已分配显存，MPS 记录驱动当前分配量；CPU 会跳过 |
| 7. MLX（可选）         | `mx.array`、`mx.finfo`、`mlx.nn.LayerNorm`、`mx.eval` | Apple silicon 上原生验证舍入、归一化及矩阵运算；未安装时提示并跳过              |

<strong>如何看误差：</strong>绝对误差是 `abs(结果 - 参考)`；当参考值接近零时，相对误差会被分母放大，不能单看百分比。本章同时观察最大/平均绝对误差和有限值。FP64 也不是“真实数学值”，只是这里更高精度的数值参照。CUDA 显存峰值与 MPS 驱动分配量口径不同，MLX 计时又是单个矩阵乘法；这些数字只供各自环境内观察，不能直接横向排名。

<strong>练习：</strong>把 softmax 的 logits 从 `[1000,1001,1002]` 改成 `[-1000,-999,-998]`，预测直接 `exp` 的结果；再把矩阵乘法的输入整体乘以 `1000`，观察 FP16 结果是否仍有限。notebook 末尾给出解释。

## 本章结论：TinyLLM 的选择 {#tinyllm-choice}

硬件和 PyTorch 算子支持时，训练优先试 <strong>BF16 autocast</strong>，因为它与 FP32 有相近的指数范围，可减少 FP16 常见的溢出/下溢风险；归一化、softmax 和损失等归约仍交给稳定实现处理，并监测有限值。CPU 教学或硬件不支持时用 FP32；只支持 FP16 加速时用 FP16 autocast 并在反向传播中配 `GradScaler`。BF16 的尾数更短，不能因此说它处处比 FP16 准确。[PyTorch AMP 文档](https://docs.pytorch.org/docs/stable/amp.html)给出设备与 dtype 的用法。

## 参考资料

* [PyTorch：数值精度](https://docs.pytorch.org/docs/stable/notes/numerical_accuracy.html)
* [PyTorch：AMP/autocast](https://docs.pytorch.org/docs/stable/amp.html)
* [PyTorch：AMP 示例与梯度缩放](https://docs.pytorch.org/docs/stable/notes/amp_examples.html)
* [PyTorch：`torch.finfo` 类型信息](https://docs.pytorch.org/docs/stable/type_info.html)
* [MLX：设备与同步](https://ml-explore.github.io/mlx/build/html/python/devices_and_streams.html)

这是目前已成文的最后一章。回到[课程总览](./index.md)查看后续规划。
