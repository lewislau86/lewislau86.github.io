---
title: "第 17 章：数值精度与混合精度"
description: "FP32、FP16、BF16 各能表示什么；舍入、溢出与下溢从哪里来；混合精度与 autocast 怎样工作。"
pageClass: tinyllm-course
next: false
---

# 第 17 章：数值精度与混合精度

[课程总览](./index.md) · [上一章](./regularization.md) · [下一章](./gradient-stability.md)

::: tip 本章学习目标
区分“范围太窄导致溢出/下溢”和“刻度太粗导致舍入”，并能用 `torch.finfo` 查出三种格式的界限；说明输入、中间累加和输出为何可能使用不同精度；读懂 `torch.autocast` 的基本用法，知道什么时候需要 `GradScaler`。

**前置：** 张量与矩阵乘法；[第 4 章](./normalization.md)的归一化。

**实践方式：** <a href="/tinyllm/notebooks/precision.ipynb" download>precision.ipynb</a>，基础实验只需 CPU；有 CUDA、MPS 或 MLX 时可运行加速实验。
:::

<TinyLLMMap active="precision" />

## 问题：1001 去哪儿了？

先猜下面三行的输出：

```python
import torch
print(torch.tensor([1000., 1001.]).to(torch.bfloat16))
print(torch.tensor([1000., 1001.]).to(torch.float16))
print(torch.tensor(300., dtype=torch.float16).square())
```

实际结果（PyTorch CPU）：

```text
tensor([1000., 1000.], dtype=torch.bfloat16)
tensor([1000., 1001.], dtype=torch.float16)
tensor(inf, dtype=torch.float16)
```

同样占 16 位，BF16 把 1000 和 1001 存成了同一个数，FP16 却分得清；可 FP16 连 $300^2=90000$ 都存不下，直接变成 `inf`。两种格式各有一种失败方式：一种是<strong>刻度太粗</strong>，相近的数被舍入成同一个；另一种是<strong>范围太窄</strong>，大数溢出。训练大模型时为了省显存、提速，常用这两种 16 位格式，所以要先弄清它们各自在哪里出错。

本章聚焦前向数值和混合精度；梯度裁剪、FP16 Loss Scaling 与训练循环放在规划中的第 18～19 章。

## 1. 浮点数：位数有限的科学计数法

把浮点数想成二进制科学计数法 $\pm\,1.xxx\times2^{e}$：符号位决定正负，<strong>指数</strong>决定能覆盖多大的范围，<strong>尾数</strong>决定相近的数能分得多细。三种常见格式把 16 或 32 位分给这三部分的方式不同：

![FP32 为 1 位符号、8 位指数、23 位尾数，eps 约 1.19e-7，最大约 3.4e38；FP16 为 1/5/10，eps 约 9.8e-4，最大 65504；BF16 为 1/8/7，eps 约 7.8e-3，最大约 3.4e38](/tinyllm/figures/float-formats.svg)

横着比位宽。BF16 和 FP32 有同样的 8 位指数，所以最大值都约为 $3.4\times10^{38}$；代价是尾数只剩 7 位，1 附近的刻度间隔 `eps` 约 $7.8\times10^{-3}$。FP16 把位数更多地给了尾数（10 位），`eps` 约 $9.8\times10^{-4}$，刻度比 BF16 细 8 倍；但指数只有 5 位，最大有限数是 65504。

| 格式                     | 总位数 | 符号/指数/尾数位  | 直观取舍                     |
| ---------------------- | --: | ---------- | ------------------------ |
| FP32（`torch.float32`）  |  32 | 1 / 8 / 23 | 范围较宽，刻度较细；本章数值参照         |
| FP16（`torch.float16`）  |  16 | 1 / 5 / 10 | 比 BF16 刻度细，但范围窄，易遇到溢出或下溢 |
| BF16（`torch.bfloat16`） |  16 | 1 / 8 / 7  | 范围接近 FP32，但刻度比 FP16 粗    |

这些界限都可以用 `torch.finfo(dtype)` 查询：`eps` 是 <strong>1 与下一个可表示数的距离</strong>，`tiny` 是最小<strong>正规</strong>正数，`max` 是最大有限数。有些设备和运算还能表示比 `tiny` 更小的非正规数。[PyTorch 类型信息](https://docs.pytorch.org/docs/stable/type_info.html)

```python
import torch
for dtype in (torch.float32, torch.float16, torch.bfloat16):
    info = torch.finfo(dtype)
    print(dtype, info.eps, info.tiny, info.max)
```

## 2. 刻度随数值变大：舍入、溢出与下溢

`eps` 只描述 1 附近的刻度。浮点数的尾数位数固定，指数每加 1，相邻两个可表示数的间隔就翻一倍：

![相邻可表示数的间隔随数值大小成比例增长（对数坐标）；同一量级上 BF16 的间隔是 FP16 的 8 倍；在 1000 附近 BF16 的间隔是 4，1000 与 1001 被存成同一个数；FP16 在 65504 以上没有有限值](/tinyllm/figures/float-spacing.svg)

三条线都是斜着向上的阶梯：数越大，刻度越稀。同一量级上 BF16 的间隔是 FP16 的 8 倍（尾数少 3 位）。看 1000 附近：BF16 的间隔是 4，能存的数是 …996、1000、1004…，1001 只能舍入到 1000，这就是开头第一行的结果；FP16 在这里的间隔是 0.5，1001 能精确存下。FP16 的线在 65504 处截止，再往上没有有限值，所以 90000 变成了 `inf`。

把三种现象分开：

- <strong>舍入</strong>：实数落在两条刻度之间，只能存为附近的可表示数，例如 BF16 里的 1001。
- <strong>溢出</strong>：结果大到超出范围，得到 `inf`，例如 FP16 里的 $300^2$。
- <strong>下溢</strong>：非零小数太小，在特定运算路径中变为零。FP16 的指数位少，小数一侧也最先遇到它。

`NaN` 表示无效的数值结果，例如 `inf / inf`。具体的舍入方式、非正规数处理和中间计算行为可能随硬件与算子而变。

## 3. 数值稳定：同一个公式，换一条计算路径

数学上等价的写法，在有限精度里未必同样可靠。`softmax([1000,1001,1002])` 的数学结果完全正常，但直接计算 `exp(1000)` 在 FP32 里就溢出了。先减去最大值再求指数，数学结果不变，参与 `exp` 的数却都不大于 0：

$$
\mathrm{softmax}(x_i)=\frac{\exp(x_i-m)}{\sum_j\exp(x_j-m)},\qquad m=\max_j x_j.
$$

这里的“稳定”指<strong>改写计算路径，让中间值保持在可表示范围内</strong>，浮点格式本身的位数没有变。PyTorch 的 `torch.softmax` 内部已经这样做；教学实验里的“直接 `exp`”只用来展示风险。结果有限之后，仍要和高精度参考比较误差。减最大值解决的是指数溢出；注意力分数差距过大时，softmax 输出虽然有限，概率仍可能贴近 0 或 1（饱和），这要靠[第 9 章](self-attention.md#qk-norm)的缩放和 QK Norm 处理。[PyTorch 数值精度说明](https://docs.pytorch.org/docs/stable/notes/numerical_accuracy.html)

## 4. 输入、累加、输出是三个不同环节

看 `a @ b` 时要问三件事：输入张量存为哪种 dtype？乘积与累加用哪种精度？结果存为哪种 dtype？张量的 `dtype` 只告诉你输入和输出，内核中间值的精度要看具体实现。点积、注意力分数和归一化统计量都有求和过程：每个乘积单项都能表示，加起来的和仍可能溢出或丢失精度。不同后端的算法与累加策略也不同，因此数值实验要记录设备、版本和 dtype。[PyTorch 数值精度说明](https://docs.pytorch.org/docs/stable/notes/numerical_accuracy.html)

回到开头：$300^2$ 的溢出发生在 FP16 的平方这一步。若在 FP32 里算平方、求和，再把结果按需要转回去，就能避开它。<strong>精度安排要放在敏感运算之前</strong>，已经溢出或舍入的信息，事后转回 FP32 也找不回来。

## 5. 归一化能帮什么，不能帮什么？ {#normalization-and-precision}

把 FP16 想成一把**刻度有限、量程也有限**的尺子。归一化改变的是送进**后续运算**的数值大小，尺子本身的刻度不变。以 RMSNorm 为例，一个向量除以自己的均方根后，均方根约为 1（忽略 `eps` 和可学习缩放）；后续的矩阵乘法、平方或注意力点积就很少遇到极大数值。这是“控制数值范围”。

例如，FP16 能存下 `1000`，却存不下 `1000 × 1000`。若先在安全的计算路径中把一组约为 `1000` 的激活归一化到约为 1，再转成 FP16 去平方，结果就能保持有限。**顺序很重要**：如果归一化内部已经用低精度算出了 `inf`，或者输入在转换时已经丢掉了小差异，事后归一化都修不回来。

归一化之后仍要留意三件事：

- 除以很小的 RMS 或标准差会放大噪声，所以公式里必须有 `eps`；
- 可学习缩放、后面的线性层和残差相加，可能把数值重新放大；
- BF16 范围宽但刻度粗，较大基数上的微小差异可能在输入转换时就消失（正如 1000 和 1001），这对需要先减均值的 LayerNorm 影响尤其明显。

| dtype | 主要特点 | 归一化中的典型风险 |
| --- | --- | --- |
| FP32 | 范围和有效精度都较高 | 作为数值参考，不同内核仍可能有细微差异 |
| FP16 | 有效精度比 BF16 高，但范围窄 | 很小的数下溢或舍入为 0；平方和累加可能溢出 |
| BF16 | 指数范围接近 FP32，有效精度更低 | 较大基数上的小差异在转换时消失 |

框架内置的 `nn.LayerNorm`、`nn.RMSNorm` 通常在内部用更高精度计算统计量。自己手写归一化时，可以显式用 `x.float()` 算平方均值和除法，再转回输入 dtype；这保护的是转换之后的计算，已经发生的输入舍入无法弥补。判断效果时分别看三件事：激活是否有限、离 FP32 参考有多远、训练是否收敛。

<a href="/tinyllm/notebooks/normalization.ipynb" download>normalization.ipynb</a> 的低精度单元格演示了三种情况：FP16 对微小值的舍入或下溢、BF16 在较大基数上丢失小差异、先低精度平方与先转 FP32 再平方的差别，最后比较 `nn.LayerNorm`、`nn.RMSNorm` 在 FP32/FP16/BF16 输入上的输出误差。

## 6. 混合精度与 `autocast`

全部使用 FP32 最简单，但显存和计算成本较高。前几节给出了一个分工思路：矩阵乘法量大、对舍入相对宽容，适合低精度；求和、归一化、softmax 和损失对范围和舍入敏感，留在高精度。混合精度就是让框架<strong>按算子</strong>做这种选择：

![参数始终以 FP32 存储；进入 autocast 区域后，matmul、linear、conv 以 FP16/BF16 执行，softmax、layer_norm 和损失以 FP32 执行，其余算子跟随输入 dtype；反向传播把梯度累积到 FP32 参数上；只有 FP16 需要 GradScaler](/tinyllm/figures/autocast-flow.svg)

从左往右读。参数一直以 FP32 存储；进入 `autocast` 区域后，`matmul`、`linear`、`conv` 先把输入转成 FP16/BF16 再算，`softmax`、`layer_norm` 和损失在 FP32 里算，其余算子跟随输入的 dtype。反向传播把梯度累积回 FP32 参数，优化器也在 FP32 上更新。最右边的 `GradScaler` 只在 FP16 时需要。图中的算子名单只是示例，具体策略随设备和 PyTorch 版本变化，以 [PyTorch AMP 文档](https://docs.pytorch.org/docs/stable/amp.html)为准。

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

`autocast` 和对模型调用 `.half()` 或 `.bfloat16()` 是两回事：后者直接改变参数和输入的存储 dtype，敏感运算也随之失去 FP32 输入。本章 notebook 用固定矩阵比较 FP32 与手动转换后的误差，再用同一小模型比较 FP32 与 autocast；CUDA/MPS 可用时还会计时。MPS 的算子策略可能与 CUDA 不同，要打印实际输出 dtype。低精度是否更快、更省内存，要在自己的设备上测；框架还可能为类型转换、临时缓冲区和缓存额外分配内存。

FP16 训练中的 `torch.amp.GradScaler` 先把损失乘一个大数再反传，降低小梯度下溢的风险；它针对的是反向传播里的下溢，前向溢出它管不到。BF16 的指数范围与 FP32 相同，通常不需要这一步。梯度缩放、反向传播以及裁剪顺序留给第 18 章。[PyTorch AMP 示例](https://docs.pytorch.org/docs/stable/notes/amp_examples.html)

## 7. Apple silicon：PyTorch MPS 与 MLX

Apple silicon 上有两条独立路径：PyTorch 的 `device="mps"` 仍使用 PyTorch 张量与 `torch.autocast`；[MLX](https://ml-explore.github.io/mlx/build/html/) 是另一个框架，使用 `mlx.core`/`mlx.nn` 自己的数组与模块，PyTorch 张量没有 `.to("mlx")` 这种用法。notebook 的 MLX 可选实验分别使用 `mx.array`、`mx.finfo`、`mlx.nn.LayerNorm` 和 `mx.eval`，观察与 PyTorch 实验同样的舍入、尺度及有限值问题。MLX 惰性求值，计时时必须调用 `mx.eval`。安装方式和平台要求见 [MLX 官方安装文档](https://ml-explore.github.io/mlx/build/html/install.html)。

## 8. 动手实验

打开 <a href="/tinyllm/notebooks/precision.ipynb" download>precision.ipynb</a>，从上往下运行：

| 实验                 | 主要 PyTorch 调用                                      | 该看什么                                                  |
| ------------------ | -------------------------------------------------- | ----------------------------------------------------- |
| 1. 刻度与范围           | `torch.finfo`、`Tensor.to(dtype)`                   | `eps/tiny/max`；1000 附近的舍入                             |
| 2. 下溢与溢出           | `Tensor.square`、`torch.isfinite`                   | 输入有限时，中间值是否仍有限                                        |
| 3. 稳定 softmax      | `torch.exp`、`torch.softmax`                        | 同一数学目标的不同计算路径                                         |
| 4. 矩阵乘法误差          | `@`、`.double()`、`.float()`                         | 用 FP64 参考，比较绝对误差；一次结果只代表当前硬件                        |
| 5. autocast        | `torch.autocast`、`nn.Linear`、`nn.LayerNorm`        | 记录各阶段输出 dtype；区分参数存储与算子输出                             |
| 6. CUDA/MPS 性能（可选） | `torch.cuda.synchronize` / `torch.mps.synchronize` | 同一 PyTorch 模型的耗时；CUDA 记录峰值已分配显存，MPS 记录驱动当前分配量；CPU 会跳过 |
| 7. MLX（可选）         | `mx.array`、`mx.finfo`、`mlx.nn.LayerNorm`、`mx.eval` | Apple silicon 上原生验证舍入、归一化及矩阵运算；未安装时提示并跳过              |

<strong>如何看误差：</strong>绝对误差是 `abs(结果 - 参考)`；参考值接近零时，相对误差会被分母放大，所以本章同时看最大/平均绝对误差和有限值。FP64 是这里更高精度的数值参照，本身也有舍入。CUDA 显存峰值与 MPS 驱动分配量口径不同，MLX 计时又是单个矩阵乘法；这些数字只在各自环境内比较。

<strong>练习：</strong>把 softmax 的 logits 从 `[1000,1001,1002]` 改成 `[-1000,-999,-998]`，预测直接 `exp` 的结果；再把矩阵乘法的输入整体乘以 `1000`，观察 FP16 结果是否仍有限。notebook 末尾给出解释。

## 9. 延伸：精度问题在其他章节出现在哪里

本章讲的是贯穿各处的有限精度计算规则。下面按数据经过模型、产生梯度、更新参数的顺序，看它和其他章节的关系；尚未完成的章节是后续要展开的主题。

| 位置与现象                 | 精度问题是什么                                                            | 对应章节要讲什么                                                                                                                                                              |
| --------------------- | ------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 初始化和深层残差：激活逐层变大或变小    | FP16 中间结果可能溢出或下溢；即使保持有限，也可能有舍入误差                                   | [第 3 章](initialization-and-residuals.md)与[第 25 章](large-model-stability.md)分别讲初始化/残差缩放及更深网络的稳定结构；本章提供判断数值范围的方法。                                                                                                     |
| 归一化：计算均值、方差或均方根       | 平方、求和、减均值也受 dtype 影响；归一化只控制所在位置及后续的尺度                             | [第 4 章](normalization.md) 讲算法和位置；本章解释 FP16/BF16 的表示范围与中间精度。                                    |
| 注意力：Q/K 点积进入 softmax  | 点积可能过大；即使减最大值防止 `exp` 溢出，分数差距很大时概率仍可接近 0/1                         | 第 9 章讲缩放点积、mask 和 softmax；[第 9 章的 QK Norm](self-attention.md#qk-norm) 讲怎样在点积前控制 Q/K 尺度。 |
| 语言模型损失：用 logits 计算交叉熵 | 先算概率、再取对数可能产生 `log(0)`；稳定的 log-sum-exp 计算路径更合适                   | 第 13 章讲交叉熵和 loss mask；本章的 softmax 实验提供数值直觉。                                                                                                                      |
| 反向传播：梯度很小或很大          | FP16 小梯度可能下溢；大梯度或中间反向值可能溢出。Loss Scaling 主要处理前者，梯度裁剪用于限制梯度范数，两者目的不同 | 第 18 章讲 `GradScaler`、裁剪与梯度累积；本章只讲浮点格式为何会遇到这些问题。                                                                                                                  |
| 优化器与训练循环：更新量很小        | 低精度舍入可能使很小的更新难以反映在参数中；前向的 `NaN/inf` 也会传到损失和梯度                      | [第 14 章](optimizers.md)讲参数更新，第 19 章讲 autocast、backward 和 step 的调用顺序，第 20 章讲监测 loss、梯度与非有限值。                                                                             |

读表时分清三类“稳定”：数值稳定关注 `inf/NaN` 与误差；训练稳定关注梯度、损失和参数更新能否持续；泛化关注模型在未见数据上的表现。三者相关，但各自要单独检查。

## 本章结论：TinyLLM 的选择 {#tinyllm-choice}

**硬件和 PyTorch 算子支持时，训练优先试 BF16 autocast。**

理由：BF16 与 FP32 有相同的 8 位指数，范围同样到约 $3.4\times10^{38}$，能避开 FP16 常见的溢出/下溢，也省掉 `GradScaler`；归一化、softmax 和损失等归约交给框架的稳定实现，并监测有限值。BF16 的尾数更短，刻度比 FP16 粗 8 倍，需要细刻度的地方留在 FP32。

什么时候改：CPU 教学或硬件不支持时用 FP32；只支持 FP16 加速时用 FP16 autocast，并在反向传播中配 `GradScaler`。[PyTorch AMP 文档](https://docs.pytorch.org/docs/stable/amp.html)给出各设备与 dtype 的用法。

::: warning 常见误区
- **“BF16 范围宽，所以更准确。”** 范围和刻度是两回事。在 1000 附近 BF16 的间隔是 4，FP16 是 0.5，BF16 更早丢失微小差异。
- **“算出 `inf` 后转 FP32 就能修复。”** 类型转换找不回已经溢出或舍入的信息，要在敏感运算之前安排合适的范围和计算 dtype。
- **`torch.finfo(dtype).eps` 不是 `nn.LayerNorm(eps=...)`。** 前者是 1 附近的刻度间隔，后者是加在分母里防止除零的超参数；`tiny` 也不是最小非零数。
- **`autocast` 不等于 `.half()`。** `autocast` 按算子选择 dtype，参数仍存为 FP32；`.half()` 把参数和输入整体改成 FP16。
- **归一化之后约为 1，不代表全网安全。** 归一化控制的是范围，可学习缩放、线性层和残差还会放大数值；“没有 `NaN`”也证明不了训练会收敛。
- **`GradScaler` 不是 BF16 的必需步骤。** 它处理 FP16 反向传播中的小梯度下溢，前向溢出它管不到。
:::

## 检查理解

1. 为什么 BF16 把 1001 存成 1000，FP16 却能存下？

   <details><summary>参考答案</summary>

   BF16 只有 7 位尾数，在 512～1024 之间相邻可表示数的间隔是 4，1001 舍入到 1000；FP16 有 10 位尾数，这里的间隔是 0.5。

   </details>

2. `torch.tensor(300., dtype=torch.float16).square()` 为什么得到 `inf`？换成 BF16 呢？

   <details><summary>参考答案</summary>

   90000 超过了 FP16 的最大有限数 65504，发生溢出。BF16 的最大值约 3.4e38，能存下，但会舍入到最近的刻度（这里正好是 90112）。

   </details>

3. 稳定 softmax 先减最大值，解决了什么问题？还剩下什么问题？

   <details><summary>参考答案</summary>

   它让参与 `exp` 的数都不大于 0，避免指数溢出；分数差距很大时 softmax 仍会饱和，概率贴近 0 或 1，这需要在点积前控制尺度。

   </details>

4. 在 `autocast` 区域内，参数、`linear` 的计算、`layer_norm` 的计算分别是什么 dtype？

   <details><summary>参考答案</summary>

   参数仍存为 FP32；`linear` 以 FP16/BF16 执行；`layer_norm` 通常以 FP32 执行。具体名单随设备和版本变化，要打印实际 dtype 核对。

   </details>

5. 为什么 TinyLLM 用 BF16 autocast 时不需要 `GradScaler`，用 FP16 时却需要？

   <details><summary>参考答案</summary>

   `GradScaler` 通过放大损失来避免小梯度下溢；FP16 只有 5 位指数，小梯度容易下溢，BF16 的指数范围与 FP32 相同，这个问题基本不出现。

   </details>

## 参考资料

* [PyTorch：数值精度](https://docs.pytorch.org/docs/stable/notes/numerical_accuracy.html)
* [PyTorch：AMP/autocast](https://docs.pytorch.org/docs/stable/amp.html)
* [PyTorch：AMP 示例与梯度缩放](https://docs.pytorch.org/docs/stable/notes/amp_examples.html)
* [PyTorch：`torch.finfo` 类型信息](https://docs.pytorch.org/docs/stable/type_info.html)
* [MLX：设备与同步](https://ml-explore.github.io/mlx/build/html/python/devices_and_streams.html)
* [MLX：文档首页](https://ml-explore.github.io/mlx/build/html/) · [安装](https://ml-explore.github.io/mlx/build/html/install.html)

这是目前已成文的最后一章。回到[课程总览](./index.md)查看后续规划。
