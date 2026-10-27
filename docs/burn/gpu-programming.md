---
title: "第 5 章：GPU 编程：从向量加法到矩阵乘法"
description: "沿 learn-cuda 理解线程、内存与协作，展开矩乘、归约、Softmax、滤波、FP6、Attention 和 GEMV。"
pageClass: burn-course
---

# 第 5 章：GPU 编程：从向量加法到矩阵乘法

[课程总览](./index.md) · [上一章](./rust-basics.md) · [下一章](./rust-gpu.md) · [资料与版本](./references.md)

::: tip 本章学习目标
沿 learn-cuda 理解线程、内存与协作，展开矩乘、归约、Softmax、滤波、FP6、Attention 和 GEMV。

**实践方式：** Rust CPU 数学参考、NVIDIA Rust CUDA 示例与上游算法对照。历史验证范围统一见[实验索引](./learning-labs.md)。
:::

本章先把一个算子拆成线程、内存访问和协作，用 learn-cuda 比较算法演进，用 NVIDIA/cuda-rust 作为 Rust GPU 实践入口。后面的 Burn 章节会把这些工作重新交给框架管理。

::: info 源码与实验范围
learn-cuda 以提交 [`afcb20b`](https://github.com/gau-nernst/learn-cuda/tree/afcb20b1bd89065c31a1575c276aba686fc4dfce) 为阅读基线，核对日期为 **2026-10-25**。本次未运行 CUDA kernel 或复现上游性能表；本书的 `gpu_probe` 仅用 CPU 演示工作划分。
:::

## 先在纸上算一次 {#先在纸上算一次}

取一个样本的两个特征，输出两个数。这次把主线偏置的第一个值改为 -6，以便观察 ReLU 把负数变成零；其余输入和权重保持主线取值：

```text
X = [[1, 2]]       shape = [1, 2]
W = [[ 1, -1],
     [ 2,  1]]     shape = [2, 2]
b = [[-6, 1]]      shape = [1, 2]
```

`shape` 是每个维度的长度。这里使用二维张量；`XW` 表示矩阵乘法，不是对应位置相乘。

1. 第一个输出：`1 × 1 + 2 × 2 = 5`。
2. 第二个输出：`1 × (-1) + 2 × 1 = 1`。
3. 加偏置：`[5, 1] + [-6, 1] = [-1, 2]`。
4. `ReLU(t) = max(t, 0)`，所以 `Y = [[0, 2]]`。

CPU 或 GPU 运行时都必须遵守这套数学规则。差别在于如何分配工作、如何取数，以及使用什么精度计算。

## CPU、GPU、host、device 分别是什么 {#cpu、gpu、host、device-分别是什么}

| 词语 | 本章中的含义 | 在这个例子里做什么 |
| --- | --- | --- |
| CPU | 擅长控制流程和通用任务的处理器 | 运行 Rust 程序、准备输入、发出计算请求 |
| GPU | 适合同时处理大量相似计算的处理器 | 并行处理许多输出元素或矩阵小块 |
| host（主机侧） | 发起和管理任务的一侧，通常指 CPU 程序及其内存 | 持有待上传的输入、处理最终结果 |
| device（设备侧） | 执行张量计算的目标；也可以选择 CPU 设备 | 持有张量并运行选定运行时的计算 |
| buffer（缓冲区） | 保存一段数据的存储区域 | 存放 `X`、`W`、中间结果或 `Y` 的数值 |
| kernel（计算内核） | 在设备上执行的一段计算程序 | 计算矩阵乘法，或逐元素执行加法与 ReLU |

host/device 是角色称呼，不能简单理解成两台机器。集成 GPU 可能共享物理内存；运行时仍需管理数据可见性、缓冲区与任务依赖。

GPU 也不是“核心越多，小模型就必然越快”。安排任务、启动内核、搬运数据都需要时间；只有几个数字时，这些开销可能超过计算本身。

## 张量数值放在哪里，为什么要搬运 {#张量数值放在哪里-为什么要搬运}

先用常见的独立 GPU 想象：Rust 的 `[[1.0,2.0]]` 最初在主机侧，设备算子需要可访问的设备缓冲区。框架创建张量时安排上传，计算完成后，只有当应用需要打印或处理具体数值时，才需要相应读回。集成 GPU 的物理共享内存会改变搬运细节，但不会免除访问和同步规则。

```text
主机数据 → 上传 X、W、b → 设备缓冲区 → 连续执行多个算子 → 输出缓冲区
                                                               ↓ 按需读回
                                                           主机可读取的数值
```

因此，一个请求里反复“读回中间结果 → 在 CPU 改一点 → 再上传”，可能让 GPU 不断等待。常见做法是让连续的张量操作留在同一设备，模型权重在初始化或加载后复用，输入按请求准备，最后只读回需要的结果。这样做是否更快仍要按第 13 章测量。

还要区分三种存储范围：

| 范围 | 初学时怎样理解 | 与矩阵乘法的关系 |
| --- | --- | --- |
| 全局设备内存 | 大多数张量数值所在的位置，容量较大 | 保存完整的 X、W 和输出 |
| 工作组共享存储 | 同一组工作项可以协作使用的较小区域 | 暂存一块输入，让组内多次使用 |
| 寄存器等局部计算状态 | 某个工作项计算时保留的小量值 | 保存累加中的输出或索引 |

这是典型 GPU 的教学划分，具体容量、可用机制与成本取决于硬件和运行时。不能因 Rust 里变量很小就断言它必然在寄存器，也不能把所有中间值都无条件塞进共享存储。

## 并行时，谁负责哪个元素 {#并行时-谁负责哪个元素}

把输出放大成 `[M, N]`，其中 `M` 是样本行数，`N` 是输出特征数，输入特征数记作 `K`。共享偏置保存为 `[1, N]`，每一行都读取同一行偏置：

```text
Y[row, col] = max(0, sum(k=0..K-1, X[row,k] × W[k,col]) + b[0,col])
```

把矩阵乘法单独写成数学公式，设 $A=X$、$B=W$、$C=AB$：

$$
C_{ij}=\sum_{k=0}^{K-1}A_{ik}B_{kj},
\qquad
Y_{ij}=\max(0,C_{ij}+b_{0j}).
$$

$i$ 选输出的行，$j$ 选输出的列；$k$ 遍历输入特征，把每对相乘的结果相加。$A$ 的形状是 $[M,K]$，$B$ 是 $[K,N]$，因此 $C$ 是 $[M,N]$。这些索引与求和符号可先在[数学预备篇](./math-foundations.md)中练习。

一个容易理解的教学方案，是让一个逻辑线程计算一个输出位置：线程 `(0, 0)` 算左上角，线程 `(0, 1)` 算同一行的下一格。**线程**是参与执行的一份工作；**线程组**把若干线程组织成一组，便于协作与调度。

假设有 `3 × 5 = 15` 个输出，每组安排 8 个逻辑位置，就需要向上取整为 2 组，共安排 16 个位置。最后一个位置没有有效元素，必须检查索引边界并退出，不能随意读写缓冲区。

把“一个工作项负责一个输出”写成索引关系：

$$
\text{total}=\left\lceil\frac{M\cdot N}{B}\right\rceil\cdot B,\qquad
\text{index}=\text{group}\cdot B+\text{lane}
$$

若 `index >= M*N` 就退出；否则 `row = index / N`、`col = index % N`。这里的 $B$ 是一组的工作项数。取整会让最后一组多出空位，所以边界检查不是可选项。

这只是教学分工。高性能矩阵乘法常使用 **tiling（分块）**：一组线程合作处理一个小矩阵块，让已读取的输入被多次利用；一个线程也可能负责多个元素。不要把“一线程一元素”当作所有 GPU 内核的规律。

### 分块为什么可能节省读取 {#分块为什么可能节省读取}

设一组工作项合作算输出的一个 `2×2` 小块。在某个输入位置 k，需要一列 X 中的两个数、一行 W 中的两个数。这四个输入可以组成四次乘法，分别贡献给小块的四个输出；不必让四个输出各自独立读取全部需要的输入。

```text
从 X 取 [a,b]，从 W 取 [c,d]
对输出小块累计：[[a*c, a*d],
               [b*c, b*d]]
接着处理下一个 k，继续加到这些输出上
```

![固定 k 时，读取两个 X 元素和两个 W 元素，复用它们更新输出的一个 2×2 小块](/burn/gpu-tiling.svg)

图中只画固定 $k$ 的一次贡献，并不是整个矩阵乘法已经结束。可以写成一个列向量与行向量相乘：

$$
\begin{bmatrix}C_{00}&C_{01}\\C_{10}&C_{11}\end{bmatrix}
\mathrel{+}=
\begin{bmatrix}a\\b\end{bmatrix}
\begin{bmatrix}c&d\end{bmatrix}
=\begin{bmatrix}ac&ad\\bc&bd\end{bmatrix}.
$$

这里 $a=X_{0k}$、$b=X_{1k}$、$c=W_{k0}$、$d=W_{k1}$；此处小写 $b$ 只是图中的一个输入值，不是前文的偏置张量。`+=` 表示把这次贡献累加到已有的输出值。四个输出如果独立读取，每个都要两个输入值，共读 8 次；在这个理想复用模型里，先读 4 个值就能完成相同的四次乘法。这个次数没有计算缓存、整个 $k$ 循环或输出写回，也不是硬件实测值。

真正的分块内核通常把更大块数据协作加载到快速存储，并重复使用。它还要处理不足一个块的边界、对齐和工作组资源限制。协作读取时，需要保证读者开始使用前数据已准备好；这种组内同步与“CPU 等待整块 GPU 完成”是不同范围的同步。

GPU 工作项也不是给每个元素创建一个操作系统线程。工作项和工作组描述内核的逻辑分工，运行时与硬件把它们调度到执行资源上；模型作者通常不需要自己管理每个工作项。

Burn 的[官方教学内核](https://github.com/tracel-ai/burn/blob/v0.22.1/examples/custom-cubecl-kernel/src/kernel.rs)使用输出行列位置做乘加，并包含边界检查；它适合解释原理，官方书也明确提醒生产矩阵乘法需要更复杂的分块与硬件优化。

## 先学会给工作编号 {#一、先学会给工作编号}

下面是教学伪代码，描述一维 SIMT 加法的分工，不是某个 Rust CUDA 库的 API：

```text
index = block_id * threads_per_block + thread_id
if index < length:
    output[index] = input_a[index] + input_b[index]
```

若 `length=1000`、每块 `256` 个线程，需要 `ceil(1000/256)=4` 个块，共安排 `1024` 个线程位置。最后 `24` 个位置没有对应元素，边界检查让它们不访问数组。

| 概念 | 先回答什么问题 | 容易混淆的地方 |
| --- | --- | --- |
| thread | 这个执行项负责哪些元素？ | 一个线程也可以循环处理多个元素 |
| block | 哪些线程组成一个协作组？ | 块数不等于 GPU 的硬件核心数 |
| grid | 这次启动一共安排哪些块？ | 启动的块不要求全部同时驻留 |
| warp | NVIDIA 怎样把块内线程组织成执行组？ | 一个 warp 含 32 个线程；控制流与同步仍要遵循编程模型 |
| SM | 硬件在哪里调度和执行这些工作？ | 软件编号与硬件资源数量属于不同层次 |

这些概念的准确语义以 [NVIDIA 编程模型](https://docs.nvidia.com/cuda/cuda-programming-guide/01-introduction/programming-model.html)为准。learn-cuda 的笔记适合帮助提出问题；设备代际的资源大小和同步行为需要回到官方文档核对。

## 沿着向量加法读一条完整调用链 {#二、沿着向量加法读一条完整调用链}

主线先看 NVIDIA 的 [Rust vecadd](https://github.com/NVIDIA/cuda-rust/blob/fc747196f2d46dce41bd844e3f5b1c5882751f2b/cuda-oxide/crates/rustc-codegen-cuda/examples/vecadd/src/main.rs)，下一章给出 [SIMT 代码与命令](./rust-gpu.md#nvidia-simt)：

| Rust 调用位置 | 实际职责 | 阅读时记录什么 |
| --- | --- | --- |
| `CudaContext` / stream | 选择设备与执行流 | 谁提交任务，依赖怎样排序 |
| `DeviceBuffer::from_host` / `zeroed` | 准备设备输入与输出 | 元素数量、缓冲区所有者与生命周期 |
| `kernels::load` / `module.vecadd` | 加载设备产物并启动 kernel | 参数类型、grid 与访问契约 |
| `thread::index_1d` / `DisjointSlice::get_mut` | 按索引读输入、写自己的输出 | 尾部保护、输入长度和唯一写入者 |
| `to_host_vec` / 数值断言 | 等待约定的完成条件并核对结果 | 全部元素，而非仅打印前几项 |

主机与设备都写 Rust，不表示它们在同一个处理器执行。Cargo 构建主机程序与设备产物，执行流安排实际设备工作；缓冲区必须保持到访问结束。

::: details 上游对照：learn-cuda 为什么有 Python

learn-cuda 的 [`01_vector_addition/main.py`](https://github.com/gau-nernst/learn-cuda/blob/afcb20b1bd89065c31a1575c276aba686fc4dfce/01_vector_addition/main.py) 和 [`add.cu`](https://github.com/gau-nernst/learn-cuda/blob/afcb20b1bd89065c31a1575c276aba686fc4dfce/01_vector_addition/add.cu)提供另一条实现链。这里用于核对原仓库，实践主线使用上面的 Rust 入口。

| 调用位置 | 实际职责 | 阅读时记录什么 |
| --- | --- | --- |
| Python 的 `torch.utils.cpp_extension.load` | 构建并加载 C++/CUDA 扩展 | 哪些源文件参与编译，首次构建发生在哪里 |
| Python 创建 CUDA 张量 | 准备设备上的输入 | 元素数量、dtype、设备与连续性 |
| `module.add(input1, input2)` | 通过扩展绑定进入 C++ 包装函数 | 传入的是张量，尚未读成主机数组 |
| C++ 的 `add` | 检查部分输入约束、分配输出、计算启动规模 | 谁拥有缓冲区，kernel 收到哪些指针和长度 |
| `add_kernel` | 每个线程按索引读写元素 | 索引计算、越界保护、每个位置的写入者 |
| `torch.testing.assert_close` | 对照 PyTorch 的结果 | 程序跑完与数值正确分别由什么验证 |

这条链涉及主机端 Python/C++ 与设备端 kernel。CUDA 代码编译成设备可执行形式，不表示每次加法都再启动一个操作系统进程；也不能把主机函数返回当成设备已经完成的保证。

学习时先保持上游例子的浮点、一维连续输入，再尝试改长度。扩展到其他 dtype、布局、设备或执行流时，应重新检查包装函数与启动约定。

这个 add 包装只检查部分约束：还应明确 f32、一维、相同设备，以及空输入由 host 直接返回。原始裸 kernel 启动没有显式传入 PyTorch 当前流；要接入自定义流或并发工作，必须重新检查流、device guard、错误检查和资源生命周期，不能把这个最小示例直接当成完整扩展模板。

:::

## learn-cuda 的完整阅读地图 {#三、按问题阅读-而不是一次读完所有目录}

本轮以固定提交的 **15 个主题目录**为范围，把它们分配到现有章节。“覆盖”表示已有原理、实现差异和验收说明；不表示 GPU 程序已在本机运行，也不表示已经逐行翻译每个文件。

| 上游目录 | 本书正文 | 学习结果 |
| --- | --- | --- |
| `01_vector_addition` | 本章前面的完整调用链 | 说明索引、缓冲区和启动范围 |
| `02_matmul_simt` | [SIMT 矩乘](#simt-matmul) | 比较 v1～v6b 的复用层次与输入限制 |
| `02_matmul_sm80` | [第 13 章：SM80](./fusion-and-performance.md#sm80) | 理解 PTX、ldmatrix、mma 与流水线 |
| `02_matmul_sm100` | [第 13 章：SM100](./fusion-and-performance.md#sm100) | 理解 TMA、Tensor Memory、tcgen05 与协作 |
| `02_matmul_sm120` | [第 13 章：SM120](./fusion-and-performance.md#sm120) | 区分 TMA、warp 分工和持久化版本 |
| `02_matmul_cdna3` | [第 13 章：CDNA3](./fusion-and-performance.md#cdna3) | 区分 HIP、wavefront、LDS 与 MFMA |
| `03_sum` | [求和归约](#求和-从互不干扰到必须协作) | 追踪线程、warp、block 和跨块合并 |
| `04_softmax` | [Softmax](#softmax-正确性条件也属于算子设计) | 推导 online 状态与 split-N 的代价 |
| `05_fp6` | [FP6](#fp6) | 解释编码、舍入、次正规数和打包 |
| `06_box_blur` | [Box Blur](#box-blur) | 对齐边界语义，理解可分离滤波和滑动窗口 |
| `07_attention` | [Attention](#attention)与[版本演进](./fusion-and-performance.md#attention-versions) | 区分分块数学与硬件优化 |
| `08_row_scaled_mm` | [第 15 章：缩放矩乘](./custom-operators.md#row-scaled-mm) | 解释低精度累加、缩放和 epilogue |
| `10_p2p` | [第 12 章：P2P](./execution.md#p2p) | 说明进程边界、IPC、同步和资源释放 |
| `11_gemv` | [GEMV](#gemv)与[持久化调度](./fusion-and-performance.md#persistent-gemv) | 解释小 batch 带宽瓶颈和形状特化 |
| `12_megakernel` | [第 13 章：Megakernel](./fusion-and-performance.md#megakernel) | 追踪 MLP、decode attention 与跨块依赖 |

目录与文件均可从[固定版本源码树](https://github.com/gau-nernst/learn-cuda/tree/afcb20b1bd89065c31a1575c276aba686fc4dfce)进入。上游没有 `09_*` 主题目录。实验条件与检查顺序集中在[第 18 章](./learning-labs.md#cuda-labs)。

## 内存访问：连续、复用和协作 {#memory-access}

相邻线程读相邻地址，有机会让硬件合并全局内存访问，叫 **coalescing（合并访存）**。线程 t 读 `base+t`，与读 `base+t*1024` 的分布很不同。实际事务还受对齐、访问宽度、参与线程和缓存影响，不能把“连续”直接等同于固定一次事务。

**向量化访问**让一个线程一次处理多个相邻值，例如 `float4`。它可能减少加载指令和地址计算，但需要满足对齐和尾部条件；它与跨线程的合并访存分别属于两个层次。

**共享内存 bank conflict**则发生在共享存储上。对常见 NVIDIA 32 个 bank、4 字节交错的教学模型，可用 `bank=(字节地址/4)%32` 观察分布：不同地址争用同一 bank 可能被拆成多次服务；读取同一地址还要区别广播。这不是全局访存不连续的同义词。[第 13 章](./fusion-and-performance.md#shared-layout)会用 padding 和 swizzle 改变这种布局。

协作还需要**同步**：生产者写完，消费者才能读；消费者用完，缓冲区才能被覆盖。块内屏障一般需要协作范围内应参与的线程一致到达，不能随意放进只由部分线程执行的分支。`volatile` 也不能替代同步。规则以 [CUDA Best Practices](https://docs.nvidia.com/cuda/cuda-c-best-practices-guide/index.html)和 [PTX ISA](https://docs.nvidia.com/cuda/parallel-thread-execution/index.html)为准。

## SIMT 矩乘：逐级扩大数据复用 {#simt-matmul}

数学始终是 `C[M,N]=A[M,K]B[K,N]`。先读 [matmul.cpp](https://github.com/gau-nernst/learn-cuda/blob/afcb20b1bd89065c31a1575c276aba686fc4dfce/02_matmul_simt/matmul.cpp)的 host 包装，再读 [matmul.cu](https://github.com/gau-nernst/learn-cuda/blob/afcb20b1bd89065c31a1575c276aba686fc4dfce/02_matmul_simt/matmul.cu)，用 [main.py](https://github.com/gau-nernst/learn-cuda/blob/afcb20b1bd89065c31a1575c276aba686fc4dfce/02_matmul_simt/main.py)核对输入与参考。

### v1～v6b 分别改变什么

| 版本 | 线程和存储怎样组织 | 为什么可能改善 | 代价或前提 |
| --- | --- | --- | --- |
| v1 | 一线程计算一个输出，循环 K | 容易建立正确性参考 | 同一输入被不同输出反复读取 |
| v2 | block 协作将 A/B 块放进 shared memory | 多个输出复用同一输入块 | 协作加载和屏障 |
| v3 | thread coarsening，每线程承担更多输出 | 增加每线程的计算量与复用 | 更多局部状态 |
| v4 | 每线程维护二维输出小块与寄存器片段 | 一次取数参与多次乘加 | 累加器可能限制驻留 |
| v5 | block → warp → thread 分层分块 | 明确每层的输出所有权与复用 | 更复杂的索引与布局 |
| v6a | 宽加载，减少边界判断 | 减少加载指令和分支开销 | 对齐、尺寸整除成为前提 |
| v6b | 改变 A 的共享存储布局 | 改变计算阶段的访问模式 | 写入与读取必须遵守同一布局 |

v5 用 `MMA_M/MMA_N` 给小块命名，**这里仍是普通 SIMT 乘加，没有调用 Tensor Core MMA 指令**。变量名不能证明使用了哪类硬件单元。

### 用一块输出计算复用收益 {#矩乘-从计算多少-转向重复读取多少}

设输出块为 `BM×BN`，沿 K 每轮处理 BK。朴素方法为每个输出分别取数，约读 `2*BM*BN*BK` 个元素；合作加载只需 `BM*BK+BK*BN` 个元素，计算量仍约为 `2*BM*BN*BK` FLOP。

例如 `BM=BN=32、BK=8`，合作加载 512 个输入，完成 16,384 FLOP。f32 输入载荷为 2,048 字节，这轮教学算术强度约为 `8 FLOP/byte`，未计输出、缓存、重复加载和同步，不能直接当作实测带宽结论。

```text
每轮 K 分块：
  协作加载 A/B 到共享缓冲区
  等到这轮加载可见
  用共享块更新线程拥有的输出累加器
  等到消费者全部用完，才能覆盖缓冲区
最后把输出小块写回
```

### 快速路径的约束属于接口

上游包装检查 CUDA、连续性和 K 匹配，但没有穷尽验证每版所需的 rank、dtype、同设备、对齐与整除条件。尤其 v6 的无边界路径，不能因为 Python 接受了 shape，就当成支持任意尺寸。

先保持上游默认规模比较；要试 `M=33,N=65,K=17`，先确认尾块保护，或增加安全回退。空输入由 host 明确处理，避免无效启动。验收分别记录非方阵、转置输入和不整除尺寸是“支持”“拒绝”还是“回退”。

## 求和：从互不干扰到必须协作 {#求和-从互不干扰到必须协作}

对 `X[M,N]` 沿最后一维求和，输出 `[M]`。拿 `[1,2,3,4]` 手算：局部和为 3、7，再合成 10。输入多而输出少，重点是组织合并。

源码是 [sum.cu](https://github.com/gau-nernst/learn-cuda/blob/afcb20b1bd89065c31a1575c276aba686fc4dfce/03_sum/sum.cu)、[sum.cpp](https://github.com/gau-nernst/learn-cuda/blob/afcb20b1bd89065c31a1575c276aba686fc4dfce/03_sum/sum.cpp)和 [main.py](https://github.com/gau-nernst/learn-cuda/blob/afcb20b1bd89065c31a1575c276aba686fc4dfce/03_sum/main.py)。

| 版本 | 变化 | 阅读检查点 |
| --- | --- | --- |
| v1 | 每线程串行处理一行 | N 大、M 小时并行度为什么不足？ |
| v2 | block 内共享树形归约，跨块 atomicAdd | 输出是否先清零，屏障是否一致到达？ |
| v3 | 每线程先处理多个输入，再归约 | 怎样减少共享阶段的工作？ |
| v4a | 最后一个 warp 用 volatile 共享访问 | 历史实现需要审查，volatile 本身不提供同步 |
| v4b | warp 内共享访问加入 __syncwarp | 参与者与读写顺序是什么？ |
| v4c | __shfl_down_sync 交换寄存器值 | mask 与活跃线程是否一致？ |
| v5 | Cooperative Groups 表达协作组 | 抽象更明确，不保证自动更快 |
| v6 | 向量化加载再做分层归约 | 对齐、尾部与局部和怎样处理？ |

8 个数的树形合并可看成 `8→4→2→1`。共享内存每轮都要读别人刚写的值；warp shuffle 则直接交换寄存器，减少部分往返。跨 warp 仍需通信，不能用一次 shuffle 代替整个 block 的同步。

多个 block 对同一输出执行 atomicAdd，每次更新不可分割，但加法顺序没有固定。浮点舍入导致串行、树形和原子累加的末位可能不同，应对照高精度参考并设置容差。上游跨块累加路径先清零输出，main.py 为各版做 assert_close。

进一步检查 `N=1`、非整倍数 N、正负抵消与大动态范围。BLOCK_SIZE/TILE_SIZE 还受归约结构约束，不能随意改成任意整数。

## Softmax：正确性条件也属于算子设计 {#softmax-正确性条件也属于算子设计}

对一行 x，稳定形式为：

$$
\begin{aligned}
m&=\max_j x_j,\\
l&=\sum_j e^{x_j-m},\\
p_j&=e^{x_j-m}/l.
\end{aligned}
$$

例如 `[1000,1001]` 不应直接计算巨大的指数。减最大值后变为 `[-1,0]`，概率约为 `[0.268941,0.731059]`；整体加一个常数不改变概率。

### Safe Softmax 与 online normalizer

上游 [softmax.cu](https://github.com/gau-nernst/learn-cuda/blob/afcb20b1bd89065c31a1575c276aba686fc4dfce/04_softmax/softmax.cu)的 naive 路径在一个 block 中依次求最大值、指数和、归一化输出。online 路径把最大值与分母合在一次扫描中维护，但输出阶段仍要再次取得输入。

已有状态为 (m,l)，新值为 x：

$$
\begin{aligned}
m'&=\max(m,x),\\
l'&=l e^{m-m'}+e^{x-m'}.
\end{aligned}
$$

两个分块状态也能合并：

$$
\begin{aligned}
m&=\max(m_a,m_b),\\
l&=l_a e^{m_a-m}+l_b e^{m_b-m}.
\end{aligned}
$$

缩放把分母换到同一个最大值基准。将 `[1,2,3,4]` 切成两段，分别求状态再合并，结果应与整行 safe Softmax 一致。这套状态也会用于 Attention。[原始论文](https://arxiv.org/abs/1805.02867)解释了在线归一化与访存的关系。

实现空状态时必须避免 `-∞-(-∞)`。上游使用有限负哨兵与自身初值约定，不能据此宣称支持空行、全为负无穷的 masked 行、NaN 或正无穷；这些情况需单独定义策略。

### 一行一个 block，还是把长行拆给多块

| 路径 | 组织 | 获益与代价 |
| --- | --- | --- |
| naive | 每行一块，分别完成 max、sum、normalize | 多行自然并行；单行很长时用不满设备 |
| naive split | 沿 N 切块，分阶段合并 max/sum 并归一化 | 增加并行，也增加启动、workspace 和原子访问 |
| online | 每行一块，合并维护 max/sum | 减少扫描，增加指数与状态更新 |
| online split | 分块求状态，用 64 位 atomicCAS 合并状态对 | 成对更新必须一致；竞争重试可能抵消收益 |

atomicCAS 只有在旧值仍等于 expected 时才更新，否则返回变化后的值供重试。`(m,l)` 必须整体合并，不能把一块的新 m 配上另一块的旧 l。浮点最大值用整数位模式实现时还要处理符号顺序，不能对所有 f32 位串直接做有符号整数 max。

上游[结果说明](https://github.com/gau-nernst/learn-cuda/blob/afcb20b1bd89065c31a1575c276aba686fc4dfce/04_softmax/README.md)显示，多行矩阵与单行长向量会得到不同的版本排序。先检查有限输出、每行和约为 1、平移不变性，以及不同分块得到的结果，再测耗时。

## Box Blur：二维索引、边界与滑动窗口 {#box-blur}

输入为 `[batch,height,width]`，每个像素求奇数边长 q 的邻域平均。[box_blur.cu](https://github.com/gau-nernst/learn-cuda/blob/afcb20b1bd89065c31a1575c276aba686fc4dfce/06_box_blur/box_blur.cu)已经有 **v1 与 v2**；根 README 的 TODO 没有完整反映源码。

v1 用 `16×16` 二维线程块，grid 的 z 维选择 batch。每线程遍历 q×q 邻域：越出图像的值不参与求和，但分母仍是 q²，即**零填充且填充计入分母**。例如 `[[1,2],[3,4]]` 配 q=3，四个输出都是 `10/9`；除以有效像素数 4 会改变语义。

v2 先沿行、再沿列做一维平均，每个方向还用移动和：

```text
先建立第一个窗口的和
窗口向右移一步：
  加入右侧新进入的元素
  输出窗口和 / q
  移除左侧即将离开的元素
```

方形均值核可分离，两次除以 q 与一次除以 q² 在实数数学中一致。直接遍历约为 `O(HWq²)`，两遍一维卷积约为 `O(HWq)`；移动窗口初始化后，每步只增减少量元素。

v2 一个线程串行扫描整行/列，又多一次中间张量写读与启动，计算更少不保证小图更快。源码初始化注明窗口小于输入的假设；超大窗口与空尺寸需额外处理。验收先对齐零填充，再分别检查边角、内部和两种版本，不只看平均误差。

## FP6：六位编码和六位存储不是同一件事 {#fp6}

这里讲 [fp6.cu](https://github.com/gau-nernst/learn-cuda/blob/afcb20b1bd89065c31a1575c276aba686fc4dfce/05_fp6/fp6.cu)的 **E3M2、bias=3** 约定，不将所有名为 FP6 的硬件格式视为相同。

编码 `s eee mm` 共六位。正常数与次正规数分别为：

$$
\begin{aligned}
x&=(-1)^s2^{e-3}(1+m/4) && (e>0),\\
x&=(-1)^s2^{-2}(m/4) && (e=0).
\end{aligned}
$$

这个实现把 e=7 也用于有限数，没有为 Inf/NaN 预留编码。最大有限绝对值是 `2^4*1.75=28`，最小正次正规数为 `1/16`，不能沿用“指数全 1 必为无穷”的规则。

| 数值或情况 | 解释 |
| --- | --- |
| 1 | s=0、e=3、m=0，编码 `001100` |
| 1.5 | e=3、m=2，编码 `001110` |
| 1/16 | e=0、m=1，次正规数 |
| 1.125 | 在 1 与 1.25 中间，nearest-even 选择 1 |
| 1.375 | 在 1.25 与 1.5 中间，nearest-even 选择 1.5 |
| abs(x)>=30 或 NaN/Inf | CPU 转换拒绝；设备路径没有相同的抛异常检查 |

最后一项来自 host 源码：CUDA 设备侧不能依靠同样的 C++ 异常路径。移植时需决定 host 预检、饱和还是拒绝，使 CPU/GPU 约定一致。

### 转换与舍入一起阅读

源码有两条思路：拆出符号、指数和尾数再组装；或先在 f32 中用二的幂调整指数，再提取编码并舍入。后者减少部分分支，但仍需检查舍入进位、次正规范围与非法值。FP16/BF16 可先升为 f32，不能只截断低位就声称实现 nearest-even。

### unpacked 与 packed

unpacked 每个编码放在一个 uint8 中，便于调试，但仍占 8 位。packed 把四个编码放进三个字节，才得到 24 位载荷。上游 packed 编码要求二维输入末维为 4 的倍数，解码要求字节末维为 3 的倍数；shape 随之改变。

这个文件只有 **TORCH_LIBRARY_IMPL** 实现登记，没有独立 main.py 与完整 schema。复现还需 schema/加载包装与测试，不能照其他目录直接运行 main.py。本书 CPU 参考检查全部编码、舍入边界与四进三出的位布局。

编码转换不等于 FP6 Tensor Core 矩乘，也不表示 Burn 已支持该存储格式。模型落地还需要缩放、布局、算子支持与任务精度评估。

## Attention：把 Softmax 状态带进分块乘法 {#attention}

单头前向为：

$$
\begin{aligned}
S&=QK^\mathsf{T}/\sqrt d,\\
P&=\operatorname{softmax}(S),\\
O&=PV.
\end{aligned}
$$

Q 为 `[Lq,d]`，K 为 `[Lkv,d]`，V 为 `[Lkv,dv]`，O 为 `[Lq,dv]`。朴素实现将 `Lq×Lkv` 的 S/P 写进全局内存；长序列时中间矩阵会很大。

[FlashAttention](https://arxiv.org/abs/2205.14135)用分块和在线归一化减少中间矩阵写读，保持同一数学目标，浮点执行仍有舍入差异。它没有将标准稠密注意力的两两比较自动变成线性计算量。

### 每个 query 行保存什么

固定一个 query，循环 K/V 分块，维护最大值 m、指数和 l，以及同一基准下未归一化的加权 V 向量 u。对新块分数 s，取新最大值 m'，令 `α=exp(m-m')`：

$$
\begin{aligned}
l'&=\alpha l+\sum_j e^{s_j-m'},\\
u'&=\alpha u+\sum_j e^{s_j-m'}V_j,\\
O&=u/l.
\end{aligned}
$$

旧分母和输出累加器必须**一起缩放**。只更新 m/l 而不缩放 u，会使各块权重不在同一基准。空块跳过；全 mask 行按接口约定处理，避免除以零。

```text
把 Q 的一块留在工作集
循环 K/V 块：
  计算局部分数
  更新每行 m、l
  缩放旧输出累加器，加入当前块的加权 V
完成后除以 l，写回 O
```

### 上游支持范围与检查

[main.py](https://github.com/gau-nernst/learn-cuda/blob/afcb20b1bd89065c31a1575c276aba686fc4dfce/07_attention/main.py)使用 BF16、`[batch,head,length,128]`，参考为 PyTorch SDPA。调用主线没有 dropout、未开启 causal，不能据此推断支持 backward、任意 head_dim、任意 mask 或 GQA。

先在 [attention_v1.cu](https://github.com/gau-nernst/learn-cuda/blob/afcb20b1bd89065c31a1575c276aba686fc4dfce/07_attention/attention_v1.cu)定位上述状态，再到[第 13 章](./fusion-and-performance.md#attention-versions)比较硬件优化。主程序对 C++ v1～v5 做 assert_close，但 Python v6 的最终调用只计时，需要另补断言。

先比较小规模非 causal 前向，再检查 Lq/Lkv 不同、分块边界与输入尺度。causal、全 mask、GQA、backward 都需要对应实现与检查才能声称支持。

## GEMV：小 batch 为什么改变优化目标 {#gemv}

`11_gemv` 计算 `x[1,K]B[K,N]→y[1,N]`。B 以转置视图传入，底层按 `[N,K]` 连续保存，每个输出所需的 K 个权重可以连续读取。

BF16 权重的计算约 `2NK` FLOP，单看权重读取约 `2NK` 字节，教学算术强度约为 `1 FLOP/byte`。batch=1 权重复用少，往往要关注带宽；batch 增大后同一权重服务多个样本，实现选择可能改变。

[cuda_v1.cu](https://github.com/gau-nernst/learn-cuda/blob/afcb20b1bd89065c31a1575c276aba686fc4dfce/11_gemv/cuda_v1.cu)让每个 warp 负责一个输出，宽加载 K 方向数据，在 f32 中局部累加，shuffle 求和后转回 BF16。persistent 版本一次处理更多输出并循环取任务，见[第 13 章](./fusion-and-performance.md#persistent-gemv)。

这是专用 kernel：包装没有完整验证 M=1、BF16、布局和整除条件；K 只分派 `1024/2048/2560/4096/5120`，不支持的值没有通用回退。公共算子必须拒绝非法输入或走参考路径，不能把未写满的 empty 输出当成有效结果。

## 按设备条件选择实验方式 {#四、按设备条件选择实验方式}

### 有 NVIDIA GPU：先运行最小向量加法 {#有-nvidia-gpu-先运行最小向量加法}

按[第 6 章的工具链表](./rust-gpu.md#工具链跟随项目版本)准备 Linux、驱动、Toolkit 与对应 Rust 工具链。NVIDIA Rust 实验不要求安装 PyTorch 或 Python。

先记录环境，以下是预检命令，不会执行学习 kernel：

```sh
nvidia-smi
nvcc --version
rustc --version
cargo --version
```

`nvidia-smi` 检查驱动和设备；`nvcc` 检查 Toolkit 编译器。前者显示的 CUDA 版本不能单独证明 Toolkit 已安装；默认 `rustc` 版本也不能代替项目固定工具链。SIMT 用 `cargo oxide doctor` 继续检查。

满足环境条件后，按固定源码进入第一个例子：

```sh
git clone https://github.com/NVIDIA/cuda-rust.git
cd cuda-rust
git checkout --detach fc747196f2d46dce41bd844e3f5b1c5882751f2b
cd cuda-oxide
cargo oxide doctor
cargo oxide run vecadd
```

验收点是 Rust 主机程序加载设备产物、kernel 完成，且全部输出与参考一致；首次编译耗时另记，不计入 kernel 性能。以上命令已按源码核对，尚未在本次环境执行。偏好 Tile 时，继续下一章的[三个小型 Rust GPU 程序](./rust-gpu.md#rust-gpu-package)。

### Apple Silicon 或没有 NVIDIA GPU：先做阅读与手算 {#apple-silicon-或没有-nvidia-gpu-先做阅读与手算}

Apple Silicon 的 Metal/MPS 不提供这些 CUDA kernel 所需的 NVIDIA 执行环境。可以在本机完成索引手算、调用链阅读和 CPU 数值参考；需要运行原始 `.cu` 文件时，再使用具备 NVIDIA GPU 的远程环境。

先下载 <a href="/burn/learn-cuda-reference.rs" download>Rust CPU 数学参考</a>，按[第 18 章](./learning-labs.md#cuda-labs)编译，核对向量加法、矩乘等八组数学检查。再留下三份笔记：一千个元素怎样分给四个块；四个数怎样逐级归约；一个小矩阵乘法的输入如何被重复使用。随后运行 Flex CPU 学习包，继续理解框架职责。CPU 检查不能验证 GPU 的同步、内存行为或性能。

## 本章实验 {#本章实验}

`gpu_probe` 用 CPU 线程模拟“把一个数组切成多个工作项”，对比单线程与四线程的元素级加法：

```sh
cargo run --locked --bin gpu_probe
```

预期看到 `single-thread`、`multi-thread` 与实际测得的加速比。线程启动、构建模式和内存带宽都会影响结果，不要求接近四倍。它演示的是工作划分，不是 GPU 基准；真正的 GPU 还要考虑启动、内存带宽和同步。没有 GPU 也可以完成本实验。

## 自测与答案 {#自测与答案}

1. 上面的小例子，ReLU 前后分别是什么？**答案：**`[[-1, 2]]` 和 `[[0, 2]]`。
2. GPU 调用返回，能立刻说设备完成了吗？**答案：**不能；需按运行时接口等待，读取结果时也可能发生等待。
3. 15 个输出启动 16 个位置，最后一个怎么办？**答案：**先检查边界，越界位置不参与读写。
4. Cargo 构建完成，为什么首次运行仍可能慢？**答案：**设备初始化、JIT 和自动调优发生在运行阶段。

硬件专用矩乘、Attention 优化和 Megakernel 见[融合与性能](./fusion-and-performance.md)，学习为什么减少中间数据读写可能比少写一行 Rust 更重要；需要对应源码时，按[源码阅读路线](./source-reading.md)继续。来源版本与三份起始资料的关系见[参考资料](./references.md)。
