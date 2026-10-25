---
title: "第 13 章：融合、内存与性能"
description: "分析启动与搬运成本，按正确的计时边界比较实现。"
pageClass: burn-course
---

# 第 13 章：融合、内存与性能

[课程总览](./index.md) · [上一章](./execution.md) · [下一章](./import-and-deploy.md) · [资料与版本](./references.md)

::: tip 本章学习目标
分析启动与搬运成本，按正确的计时边界比较实现。

**实践方式：** fusion_measure：CPU 教学对照。历史验证范围统一见[实验索引](./learning-labs.md)。
:::

> 首版导读，实验状态见[实验路线](./learning-labs.md)。本章依据 Burn **v0.22.1**，固定提交 `907ab111a02c2dea47bc41633754f095c6b2220e`；读写次数是教学估算，本文没有发布本机性能测试结果。

同样的数学公式，可以有不同的执行方式。性能分析的第一步，是分清“计算了多少”“搬运了多少数据”“启动了多少次任务”，再讨论哪一种方式适合你的设备。

阅读顺序是“找到瓶颈 → 算一笔临时张量的账 → 理解融合条件 → 正确计时”。先不读融合器源码，也能掌握这一章的判断方法。第 5 章已经解释设备工作怎样提交，本章进一步解释怎样减少不必要的工作。

## 延迟、吞吐量和瓶颈 {#延迟、吞吐量和瓶颈}

**延迟（latency）**是一次请求从开始到完成的时间；**吞吐量（throughput）**是一段时间完成多少样本。一次处理更多样本叫增大 **batch（批大小）**，可能提高吞吐量，也可能让单次请求等待更久。

**瓶颈**是当前限制整体速度的环节。假设一次预测依次花费：预处理 4 ms、上传 3 ms、计算 2 ms、读回 1 ms，总计 10 ms。即使计算瞬间完成，总时间仍有 8 ms；把计算优化为 1 ms，总时间也只是降到 9 ms。

实际系统可能重叠传输和计算，上面的相加是便于手算的串行模型。它提醒我们：必须先定义测量边界，才知道优化是否改善了用户真正等待的时间。

### 算得慢、搬得慢、启动得多，怎样区分 {#算得慢、搬得慢、启动得多-怎样区分}

| 情况 | 直观理解 | 应优先观察什么 |
| --- | --- | --- |
| 受计算能力限制 | 数据到位了，仍要做很多乘加 | 矩阵规模、内核选择、硬件适用精度 |
| 受内存带宽限制 | 算术很少，却需要读取或写入很多值 | 中间张量、访存布局、可复用数据 |
| 受提交与启动开销限制 | 单次工作太小，安排工作本身占很大比例 | 小算子数量、批大小、融合机会 |
| 受主机流程或传输限制 | 设备在等数据，或者应用在反复等设备 | 预处理、上传读回、同步位置 |

**带宽**是单位时间可以传输的数据量；**计算量**是需要执行的数值操作数量。矩阵乘法的一个输出要执行 K 次乘法并把结果累加，M×N 个输出会产生大量重复工作；分块可让输入读取被复用。逐元素 ReLU 每个位置却只做很少的算术，也要读输入、写输出，因此它的优化重点可能不同。

实际瓶颈还会随形状、batch 和精度变化。小矩阵与大矩阵不能只按同一种经验判断，设备利用率的一个百分比也不足以说明是哪一种瓶颈。先用性能分析工具确定时间分布，再选择优化目标。

## 为什么临时张量会产生开销 {#为什么临时张量会产生开销}

继续使用 `Y = relu(XW + b)`。设 `T = XW` 已经算好，`T` 和展开后的 `b` 各有 `n` 个元素。先只分析加偏置与 ReLU，不计算矩阵乘法内部的访存。

如果两个操作分别执行：

```text
内核 1：读取 T、b → U = T + b → 把临时张量 U 写入设备内存
内核 2：读取 U    → Y = max(U, 0) → 把 Y 写入设备内存
```

**临时张量**是后续操作要用、最终输出不直接需要的中间结果。它既占存储空间，还可能需要分配和读写。

在这个简化模型中，读取 `T`、读取 `b`、写入 `U`、读取 `U`、写入 `Y`，一共 `5n` 次元素访问。若每个元素用 **f32（32 位浮点数）**，每次访问按 4 字节计，`n = 4` 时是 `5 × 4 × 4 = 80` 字节。

如果把两步合成一个内核：

```text
读取 T[i]、b[i]
  → 在线程的局部计算状态中求 u = T[i] + b[i]
  → 直接把 max(u, 0) 写入 Y[i]
```

这时是 `3n` 次元素访问，`n = 4` 时是 48 字节，且少一次独立内核启动。**fusion（融合）**就是把适合一起执行的操作合并，减少这种中间存储与调度开销。

以上数字不是实际显存流量测量值。广播偏置、缓存、内存布局、向量化、寄存器分配及底层实现都会影响实际流量。特别是 `b` 常常只有一行，不应把教学模型直接用作硬件带宽结论。

## 显存占用与参数量为什么不是一回事 {#显存占用与参数量为什么不是一回事}

主线模型只有 6 个参数。若每项均为 f32，单算数值载荷是 `6×4=24` 字节；这不等于程序只需 24 字节内存。框架对象、设备缓冲区对齐、运行时和临时张量都有额外成本。

推广到较大模型时，可以按用途分账：

| 用途 | 什么决定其大小 | 典型生命周期 |
| --- | --- | --- |
| 权重与需要保留的模型状态 | 模型结构、参数 dtype | 多次请求或训练步骤之间复用 |
| 输入与输出 | batch、输入输出形状、dtype | 本次请求或批次 |
| 中间激活和临时缓冲区 | 网络运算、融合、内存复用策略 | 后续使用或反向完成前 |
| 参数梯度 | 哪些参数参与求导 | 反向后到更新或显式累积期间 |
| 优化器状态 | 优化器种类及状态精度 | 多个训练步骤之间 |
| 编译与运行时缓存 | 内核、形状、运行时配置 | 由缓存策略管理 |

推理省去许多梯度相关状态，但仍有中间激活。增大 batch 不会按比例复制共享权重，却通常会增大输入、输出和若干中间量。训练还要为反向保存必要值，第 10 章的梯度检查点正是在这里用重算换内存。

张量句柄已经离开作用域，也不意味着操作系统或驱动观察到的占用立即下降：仍被其他句柄引用的数据不能释放，框架或运行时也可能保留可复用缓冲区。检查内存时，要区分活跃张量的数据需求、分配器保留空间与其他运行时占用，再定位是否存在无意保留的中间结果。

## 融合不会改变公式，但有条件 {#融合不会改变公式-但有条件}

Burn 的 `Fusion<B>` 是一种后端装饰器：包装底层后端 `B`，先记录操作，再寻找可一起执行的组合。**装饰器**的意思是给原实现增加行为，最终仍依靠底层实现算出结果。[Fusion 源码说明](https://github.com/tracel-ai/burn/blob/v0.22.1/crates/burn-fusion/src/lib.rs)。

```text
应用代码：matmul → add → relu
             ↓
记录操作与形状、dtype、数据依赖
             ↓
判断是否存在满足条件的融合方案
             ↓
执行融合内核，或执行部分融合与普通内核
```

**dtype** 是元素的数据类型；**数据依赖**表示某个操作必须使用另一个操作的结果。融合器必须理解这些信息，才能保证执行顺序和输出含义正确。

Burn v0.22.1 的 CubeCL 融合实现既有逐元素融合器，也有矩阵乘法等专门融合器；矩阵乘法融合器会检查后续操作能否加入，不能加入时关闭当前组合。因此，本书的 `matmul → add → relu` 是一个分析例子，不能保证每个设备、形状和精度都变成一个内核。[逐元素融合器](https://github.com/tracel-ai/burn/blob/v0.22.1/crates/burn-cubecl-fusion/src/optim/elemwise/fuser.rs)、[矩阵乘法融合器](https://github.com/tracel-ai/burn/blob/v0.22.1/crates/burn-cubecl-fusion/src/optim/matmul/fuser.rs)。

数学等价也不要求不同实现逐位相同。浮点加法会舍入，改变运算组合或使用不同硬件指令可能造成小误差；比较时应设置合理容差，并检查任务准确率是否受到影响。

### 记录操作与异步执行，是两个不同问题 {#记录操作与异步执行-是两个不同问题}

第 5 章的异步指“设备工作什么时候完成”；这里的延迟记录指“何时把若干操作决定为具体执行计划”。可以先记录再异步提交，也可以不做跨算子记录，直接异步提交普通内核。仅观察 Rust 函数很快返回，无法判断发生了哪种优化。

Burn 自动微分层与融合层也都可能记录依赖，但用途不同：

| 记录 | 记录来做什么 | 常见需要的信息 |
| --- | --- | --- |
| 自动微分的求导图 | 把 loss 的梯度传回输入或参数 | 局部求导规则、父节点、必要中间值 |
| Fusion 的操作记录 | 安排和合并待执行计算 | 操作含义、shape、dtype、数据依赖 |
| 支持捕获的后端启动序列 | 准备相应设备工作的重放 | 该执行机制要求的启动信息 |

这几种记录可以在同一个系统中配合，不能因为都叫“图”就推断功能相同。注册新操作后，求导和融合都需要相应接入；它们不是看到一段任意内核就自动了解其数学含义，详见第 15 章。

## 哪些写法可能让中间结果必须落地 {#哪些写法可能让中间结果必须落地}

这里的“落地”指真正把数值写进设备内存，供后续使用；融合前的某些中间结果可以只是待执行的记录。

- 在中间调用 `into_data`、取标量或把数值打印出来，通常需要先获得实际结果，引入等待或读回。
- 中间张量还被另一条计算路径使用，可能需要保留可供后续读取的值。
- 形状变换和复杂索引可能限制融合器能处理的访存方式。
- 遇到不支持融合的操作、设备限制或候选方案限制，需要回退执行。

**view（视图）**指改变张量的观察方式，例如某些 reshape 或 transpose；它可能只修改形状与步长元数据，也可能因后续需求发生实际整理。不要机械地把所有形状变换都删除，先保证数学含义，再测量。[官方融合实践](https://github.com/tracel-ai/burn/blob/v0.22.1/burn-book/src/performance/good-practices/kernel-fusion.md)。

Rust 的 `clone()` 也不等同于“立即复制整份显存”。张量克隆通常涉及句柄共享；但保留更多中间张量会影响生命周期与优化机会。没有测量证据时，不要把“删除所有 clone”当作通用优化法则。

## 与 PyTorch 对照：从 eager 到 torch.compile {#与-pytorch-对照-从-eager-到-torch-compile}

PyTorch 教学中的 **eager（即时执行）**适合先建立“一步表达式对应一次操作调用”的直觉；GPU 工作依然可以异步执行。`torch.compile` 则跟踪可处理的 PyTorch 计算并交给编译后端生成优化代码，遇到无法继续捕获的部分可能产生 graph break，减少跨边界优化机会。[PyTorch 官方编译教程](https://docs.pytorch.org/tutorials/intermediate/torch_compile_tutorial.html)。

Burn 的 `Fusion<B>` 在张量后端这一层记录操作并寻找融合机会，不需要从 Python 程序捕获同一套语言结构。两者可对照学习“掌握更多相邻操作信息，才能优化临时存储和执行计划”的思想；它们的捕获范围、表示和优化器并不相同。

因此不能只比较“是否使用 Rust”或“是否调用 compile”，就预测谁更快。比较时应让两个系统使用相同任务、匹配的 dtype 与设备，分别说明默认执行和启用优化后的配置，并检查实际输出及误差。框架名称也不能代替某个版本、某个模型的测量结论。

## 怎样避免只测到提交时间 {#怎样避免只测到提交时间}

GPU 往往异步执行：主机发出请求后继续运行，设备稍后完成。下面的流程测量原生环境中一次调用的主机到设备完成延迟，包含调用和调度开销；它不等于纯内核时间。

```text
伪代码；不是可直接复制运行的 Rust 基准程序

创建并复用设备、模型、输入
先检查参考输出与实际输出一致
重复若干次预热：执行 forward，等待完成，并保留输出直到完成

每个测量样本：
    等待之前的设备工作完成
    开始计时
    output = forward(input)       # 测量范围内只做约定的工作
    等待设备完成                 # 原生接口可使用 Device::sync
    停止计时
    在计时外读取并验证 output      # 同时确认异步输出没有失败

报告多次测量的中位数和波动范围
```

**预热（warm-up）**是先运行几次，让设备初始化、JIT 编译、自动调优和缓存准备不混入稳态结果；**冷启动**则是这些首次开销本身。两者都有价值，应分别报告。[异步执行说明](https://github.com/tracel-ai/burn/blob/v0.22.1/burn-book/src/performance/good-practices/asynchronous-execution.md)、[内核选择说明](https://github.com/tracel-ai/burn/blob/v0.22.1/burn-book/src/performance/good-practices/kernel-selection.md)。

计时时仍要保留输出，避免尚未执行、又无人使用的计算被省略。浏览器环境应使用支持的异步等待与读回接口；纯设备耗时应使用适用的 profiling（性能分析）工具。设备同时运行其他任务，也会干扰测量。

不要每个小算子后都同步：这会改变原本允许批处理和重叠执行的工作流。测量边界应放在你真正关心的请求或批次边界。

## 一份有意义的性能记录 {#一份有意义的性能记录}

| 必填项 | 为什么需要 |
| --- | --- |
| Burn 版本、Cargo features、构建模式 | debug 与 release、融合和自动调优配置影响结果 |
| 设备、驱动、backend / runtime | 同一公式在不同实现和硬件上的表现不同 |
| shape、batch、dtype | 小矩阵和大矩阵、f32 和低精度不是同一个任务 |
| 是否预热、重复次数、同步位置 | 区分首次开销、提交开销与完整执行 |
| 是否包含数据上传、结果下载、预处理 | 定义推理耗时的实际边界 |
| 误差容差与正确性结果 | 速度比较必须建立在结果满足要求的前提下 |

可以分别测“输入已在设备上的 forward”和“预处理到取得主机结果的完整请求”。训练与推理也应分别测量：反向传播、梯度保存与优化器更新会增加额外工作。

做框架对比时还要明确是否包含编译冷启动，是否真的启用了相应 GPU 与融合路径，batch 和权重是否相同。若一个版本包含数据上传，另一个版本输入已经在设备上，即使计时数字精确，也不是同一范围的比较。

## 量化为什么不等于自动提速 {#量化为什么不等于自动提速}

**量化（quantization）**用较少位数近似表示数值，往往还能减少权重存储。例如每个权重从 32 位变为 8 位，单看数值载荷约缩为四分之一；实际文件还包含缩放参数、元数据和对齐开销。

把近似数值恢复为可参与计算的表示叫 **反量化（dequantization）**。是否更快，取决于具体操作有没有适配的量化内核、设备支持、形状、反量化开销，以及模型原来受限于计算还是数据搬运。只有存储变小，不能推出端到端时间一定减少。

Burn 的量化能力仍需按版本、后端和具体运算确认；首版不把官方书中的概述扩展为所有硬件的性能承诺。实际部署还要测量精度损失，详见[导入与部署](./import-and-deploy.md)。[本版本量化说明](https://github.com/tracel-ai/burn/blob/v0.22.1/burn-book/src/performance/quantization.md)。

## 共享布局：padding、swizzle 与缓存 {#shared-layout}

第 5 章的分块减少全局读取，接下来还要让共享存储服务好计算阶段。输入按行连续，不代表 ldmatrix 或列方向读取也没有冲突。

用每项 4 字节、32 个 bank 的简化模型，`tile[32][32]` 的第 0 列地址相差 128 字节，32 行的该列都会落在同一 bank。把行距改成 33 项后，相邻行的 bank 编号依次移动。这个 **padding** 示范只解释布局，真实 BF16/ldmatrix 还要满足访问宽度、事务拆分和对齐。

**swizzle** 通过可逆置换改变数据位置，避免额外填充。假设以 16 字节为一组，列组编号 c、行编号 r 都在 `0..7`，可用 `c'=c XOR r` 重新安排组位置；再次异或同一 r 就能恢复。它不改变矩阵数学，但读写双方必须采用同一规则。上游按行距选择具体位运算，不能将这条教学公式套到所有 stride。

还要区别 **threadblock swizzling**：它重新安排 block 对输出 tile 的访问顺序，争取相邻任务复用 L2 数据；shared-memory swizzle 改变的则是块内的数据地址。二者优化的是不同层次。

## SM80：从普通乘加走到 Tensor Core {#sm80}

沿 [SM80 目录](https://github.com/gau-nernst/learn-cuda/tree/afcb20b1bd89065c31a1575c276aba686fc4dfce/02_matmul_sm80)的 main.py → matmul.cpp → matmul_v1.cu / matmul_v5.cu / matmul_v6.cu → common.h 阅读。文件名不与每个版本一一对应，一份源文件可以提供多个入口。

这条路径的 BF16 输入是 A 行主序、B 列主序，输出使用 f32 累加后转换。数学仍是矩乘，但 warp 内各线程持有的不是随意切开的片段，而是指令规定的 fragment。

| 机制 | 负责什么 | 阅读问题 |
| --- | --- | --- |
| inline PTX | 在 CUDA C++ 中表达低层指令 | 输出/输入约束、寄存器类型和 clobber 是否匹配？ |
| cvta / __cvta_generic_to_shared | 转换地址空间表示 | shared 指令需要的是哪一种地址？ |
| ldmatrix | 把共享矩阵片段按 lane 约定加载到寄存器 | 哪个 lane 提供地址，谁获得哪些元素？ |
| mma.sync | warp 协作的矩阵乘加 | shape、dtype、布局与累加器片段怎样对应？ |
| cp.async | 发起 global→shared 异步复制 | 哪一组已提交、完成，何时允许消费者读取？ |

一条 ldmatrix 不是让每线程独立取得一整块矩阵；一次 MMA 也不是单线程执行整个矩乘。应按 [PTX ISA 的矩阵指令规范](https://docs.nvidia.com/cuda/parallel-thread-execution/index.html)画出 lane、地址与 fragment 对应关系。

### 版本推进与两类等待

| 版本 | 相对前一步的重点 | 应检查什么 |
| --- | --- | --- |
| v1 | block/warp 分块、宽加载与 Tensor Core | fragment 和写回位置是否正确？ |
| v2 | cp.async | 复制是否完成才使用共享数据？ |
| v3 | shared padding | bank 分布改善是否值得额外空间？ |
| v4 | shared swizzle | 布局置换是否对读写一致？ |
| v5 | B 使用 ldmatrix.x4，简化地址计算 | 指令数减少是否在当前硬件有效？ |
| v6 | 多阶段加载与计算，更完整的 swizzle | stage 生命周期与预取距离是否正确？ |
| v6b | 输出 tile 调度顺序变化 | L2 复用是否因 shape 改善？ |

cp.async 的完成等待解决“复制结束了吗”，block 屏障解决“参与线程是否到达了可共同使用的位置”。不能只看到一个 wait 就认为所有线程、所有缓冲区都已同步。一个 stage 必须经历：

```text
可写 → 发起加载 → 加载完成 → 计算读取 → 所有读者用完 → 再次可写
```

双缓冲让一块数据计算时预取下一块，但增加共享存储与状态。更多 stage 可能降低驻留数，也可能没有足够计算去隐藏加载；不应把 stage 数越大视为越快。

上游[结果与笔记](https://github.com/gau-nernst/learn-cuda/blob/afcb20b1bd89065c31a1575c276aba686fc4dfce/02_matmul_sm80/README.md)记录了同一改动在 A100 和 5090 上表现不同，v5 在 A100 的回退还列为待研究。这里采用优化理由，不把版本号当作单调提速保证。

## SM100：TMA、Tensor Memory 与 tcgen05 {#sm100}

[SM100 目录](https://github.com/gau-nernst/learn-cuda/tree/afcb20b1bd89065c31a1575c276aba686fc4dfce/02_matmul_sm100)面向对应 Blackwell 数据中心指令路径。它与后面的 SM120 不能只凭同属 Blackwell 就互换。具体目标和指令可用性以所选工具链及 PTX target 规则为准。

与 SM80 路线比较，这里的关键是：

1. host 构造 tensor map，描述全局张量的维度、stride、tile 与支持的布局；
2. **TMA** 按描述符发起块数据搬运，减少逐线程地址与搬运指令；
3. **tcgen05.mma** 使用相应 descriptor 执行矩阵计算；
4. 累加结果进入 **Tensor Memory（TMEM）**，再经读取、转换和 epilogue 写回。

TMEM 是这条硬件路径的专门存储，不能把它理解成“普通 Tensor 对象的内存”，也不能与 global/shared/register 任意交换使用。分配和释放必须配对，访问形状、对齐、lane 分布都受指令约束。

### v0～v7 的演进

| 阶段 | 主要变化 | 新增责任 |
| --- | --- | --- |
| v0 | SM80 风格参考 | 建立同设备上的比较基线 |
| v1a/v1b | 基本 tcgen05，2D/3D TMA 描述 | tensor map、TMEM 与同步先正确 |
| v2a/v2b | 调整 TMA 的搬运布局 | 布局与 swizzle 必须匹配 |
| v3 | 流水线 | 管理多 stage 生命周期 |
| v4 | warp specialization | 区分生产者与计算消费者 |
| v5 | 2-SM 协作 MMA | 增加跨 CTA 协作与启动约束 |
| v6 | persistent 静态调度 | 同一驻留 block 继续处理后续 tile |
| v7a/v7b/v7c | 网格规模和 epilogue 缓存策略微调 | 验证工作量、缓存与写回开销 |

上游 [README](https://github.com/gau-nernst/learn-cuda/blob/afcb20b1bd89065c31a1575c276aba686fc4dfce/02_matmul_sm100/README.md)中的 a/b/c 可能是同一文件导出的变体，不应寻找一个并不存在的 matmul_v7c.cu。

### mbarrier：到达人数与传输完成都要满足

TMA 场景下，一个阶段不仅要知道线程到了没有，还要知道预期字节是否传完。mbarrier 同时管理 arrival 与 transaction 完成条件，循环复用时还要区分 phase/parity。

```text
初始化屏障与可见性
声明本轮预期传输 → 发起 TMA
等待对应 phase 完成 → 消费数据
通知数据已消费 → 允许生产者重用 stage
```

若预期字节错误，可能一直等不到完成；若 phase 对错，可能读到上一轮状态；若缓冲区过早重用，消费者会读到后续 tile。普通 __syncthreads 不能替代所有 TMA/tcgen05 专用的完成与内存顺序规则。源码中的 fence、expect_tx、wait 和 commit 要与规范一起读。

## SM120：同一代名称下也有不同实现 {#sm120}

[SM120 目录](https://github.com/gau-nernst/learn-cuda/tree/afcb20b1bd89065c31a1575c276aba686fc4dfce/02_matmul_sm120)的矩乘使用相应 warp MMA 路径；TMA 用于搬运，不能因此推断它采用了 SM100 的 TMEM/tcgen05 方案。

| 版本 | 实现重点 | 阅读入口 |
| --- | --- | --- |
| v0 | cp.async 加载与计算 | matmul_v0.cu |
| v1 | TMA tensor map 与 mbarrier | matmul_v1.cu、common.h |
| v2 | producer/consumer warp specialization | matmul_v2.cu |
| v3 | persistent 循环、寄存器重分配 | matmul_v3.cu |

**源码已经有 v3**，尽管 README 的结果表只列到 v2，并把部分优化留在 TODO。v3 用 setmaxnreg 调整不同 warp 角色的寄存器额度，持久循环处理输出 tile，且含固定 grid=170。它还注明某些寄存器配置可能挂起，以及 ping-pong 仍为 TODO；不能把固定配置作为所有设备的推荐值。

理解 warp specialization 时，先问搬运 warp 是否需要与计算 warp 一样多的寄存器，再问共享缓冲区如何交接。角色分开不代表依赖消失，错误的资源预算或屏障参与范围会影响正确性与推进。

该目录支持 BF16 与 INT8 路径，输入类型、累加类型和输出类型并不相同。主程序 --profile 分支主要用于定位 kernel，常规 correctness 分支与 benchmark 分支也应分别检查。

## CDNA3：把复用思路带到 AMD {#cdna3}

[CDNA3 目录](https://github.com/gau-nernst/learn-cuda/tree/afcb20b1bd89065c31a1575c276aba686fc4dfce/02_matmul_cdna3)采用 ROCm/HIP、目标 gfx942。文件后缀仍为 .cu，PyTorch API 仍可写 .cuda()，不能据此判断运行的是 NVIDIA CUDA。

| NVIDIA 学习概念 | CDNA3 对应阅读 | 可复用与需重查的内容 |
| --- | --- | --- |
| warp/lane | wavefront/lane | 线程分组思路可复用，不能固定套 32 个 lane |
| shared memory | LDS | 协作缓冲可复用，容量和访问分布另查 |
| MMA | MFMA | 都需理解矩阵片段，fragment 布局并不相同 |
| 流水线 | 寄存器预取与 LDS 交接 | 生产/消费关系相同，指令与等待规则另查 |

硬件参数以 [AMD 官方规格](https://rocm.docs.amd.com/en/latest/reference/gpu-specs.html)和该目录引用的 CDNA3 ISA 为准。上游从 v1a 的基本实现，推进到 v1b padding、v2 swizzle、v3a 寄存器双缓冲、v3b 更宽的 LDS 读取。这里的双缓冲安排结合了寄存器与 LDS 资源，不是照搬 NVIDIA 的共享内存大小。

沿 main.py → torch.ops.hip_matmul → matmul_v*.cu → MFMA 辅助定义追踪。当前 main.py 的 assert_close 被注释，只打印平均绝对差；平均误差可能掩盖局部错误，复现时应补最大误差、逐元素容差与有限值检查，再测性能。该目录未在本书环境运行。

## Attention 版本：分块数学不变，数据路径改变 {#attention-versions}

第 5 章已经推导 m/l/u；这里阅读 [07_attention](https://github.com/gau-nernst/learn-cuda/tree/afcb20b1bd89065c31a1575c276aba686fc4dfce/07_attention)如何安排同一计算。

| 版本 | 主要关注 | 需要画出的数据路径 |
| --- | --- | --- |
| v1 | Tensor Core 的分块 Attention 基础 | Q/K 得分块 → online 状态 → 加权 V |
| v2 | shared swizzle | K/V 存储与 ldmatrix 地址对应 |
| v3 | 两阶段流水线 | 当前计算与下轮预取怎样交错 |
| v4 | 更宽的 ldmatrix 读取与后续多 stage 配置 | 共享块何时可读、可重用 |
| v5 | 调整异步流水线组织 | 寄存器、共享空间与等待成本 |
| v6 | Python CuTe DSL 的 TMA 路径 | attention_v6.py 的 tensor map 与屏障 |

上游 README 保留历史表，又在 **2026-10-03** 单独公布新环境结果，明确旧 v4→v5 的收益没有在新环境延续。教材应保留这个反例：同一数学、同一文件，在工具链、功耗与依赖改变后，最优配置也可能变化。

v6 的实现语言是 Python CuTe DSL，不是 Rust，也不是 C++ .cu；“同一个 CUDA 学习仓库”不表示每个例子使用同一语言。程序还用不同张量布局调用外部 FlashAttention 对照，比较时要核对转置和返回值，不可只比较函数名。

## Triton 与 CuTe DSL：同一问题怎样换一种表达 {#gpu-dsl}

上游不仅有 CUDA C++，SIMT 目录还含 matmul_triton.py，SM80/SM100 含 cutedsl_v*.py，Attention v6 也使用 CuTe DSL。阅读时应比较“哪些决定交给编译器”，而不只比较代码长度。

### Triton 的 program、mask 与自动调优

[matmul_triton.py](https://github.com/gau-nernst/learn-cuda/blob/afcb20b1bd89065c31a1575c276aba686fc4dfce/02_matmul_simt/matmul_triton.py)用 program id 选择输出块，构造 A/B 指针块，沿 K 循环，用 tl.dot 累加，最后按边界 mask 存回。program 处理的是数据块，不是与 CUDA thread 一一对应的标量执行体。

stride 决定逻辑坐标怎样变成地址；load 的 mask 与 other=0 保护尾部并补中性值，store 的 mask 防止写出输出范围。它们是算法的一部分，不能因为换成 DSL 就省略。

autotune 列出 tile、warp 和 stage 的候选配置，M/N/K 变化会触发选择。第一次运行要区分 JIT 与候选测量，稳态比较则固定形状与配置。候选范围本身也会影响调优成本与结果。

源码为 f32 对照显式使用 allow_tf32=False。不同精度模式可能改变容差与性能，不能把较低精度乘法一概称为实现错误；比较双方应采用相同数值契约，并记录模式。

### CuTe 的 layout、copy atom 与 MMA atom

[SM80 cutedsl_v1.py](https://github.com/gau-nernst/learn-cuda/blob/afcb20b1bd89065c31a1575c276aba686fc4dfce/02_matmul_sm80/cutedsl_v1.py)显式组织 layout：thread layout 描述由谁搬，value layout 描述每人搬哪些值，组合后的 tiled copy 覆盖一个数据块；MMA atom 与 tiled MMA 则组织计算片段。

shared layout、swizzle、copy 与 MMA 的分区必须相容，循环仍要管理 pipeline。Python 写法是在构造并编译设备计算，不是让 Python 解释器逐元素执行 GPU 乘法。

这些概念可帮助理解 Rust Tile 编程和 CubeCL，但 Triton、CuTe DSL、cutile-rs、CubeCL 不共享同一 API、编译器或指令支持范围。映射职责后再看各自版本的接口，见[第 6 章](./rust-gpu.md#cuda-rust-mapping)。

## Persistent GEMV：让驻留工作继续取任务 {#persistent-gemv}

[cuda_persistent_v1.cu](https://github.com/gau-nernst/learn-cuda/blob/afcb20b1bd89065c31a1575c276aba686fc4dfce/11_gemv/cuda_persistent_v1.cu)按 SM 数量启动 block，每个 warp 在一轮处理多行输出，循环推进到后续行。与“每输出组启动一个 block”相比，它复用输入片段并改变任务调度。

收益来自减少部分重复加载与改善调度，代价是更多寄存器和更长的工作循环。persistent 不保证权重全部常驻片上，也不表示跨所有请求永久保存一个 kernel。

源码用设备 0 的 SM 数决定 grid，主机分派仅支持若干 K，循环又假设每组输出完整。把它变成多设备、任意 N/K 算子之前，要补设备选择、尾部和不支持形状的显式处理。

上游 main.py 用 cuda-bench，借助 ExternalStream 在基准指定的流里运行，并轮换多份输入。轮换会改变缓存条件；“反复计算同一个缓存内矩阵”和“持续读取新的权重”不能混为一组带宽结论。

## Megakernel：融合扩大后，同步成为核心问题 {#megakernel}

[12_megakernel](https://github.com/gau-nernst/learn-cuda/tree/afcb20b1bd89065c31a1575c276aba686fc4dfce/12_megakernel)从独立 MLP、decode attention 推进到小模型单步解码，目标是减少许多小算子的启动、中间写读和主机调度。

### 从两个子问题读起

MLP 的计算骨架为：

$$
\begin{aligned}
z&=\operatorname{RMSNorm}(x),\\
h&=\operatorname{SiLU}(zW_g)\odot(zW_u),\\
y&=x+hW_d.
\end{aligned}
$$

门控/上投影、激活和下投影之间有真实依赖。先读 reference.py 的数学，再读 mlp_triton_v1.py 的融合与两阶段版本，以及针对小 batch 的 mlp_gemv_triton_v1.py / mlp_gemv_cuda_v1.cu。batch 改变权重复用，不能从 batch=1 的结果推断大 batch 也适合同一 kernel。

decode attention 要追踪 RMSNorm → QKV 投影 → Q/K 归一化与 RoPE → KV cache 更新 → 当前 query 对缓存的注意力 → 输出投影与残差。attn_main.py 不仅比较最终输出，还比较新增的 KV cache 位置，这可以发现“当前步正确、后续步被污染”的错误。

### 整个模型的推进与状态生命周期

model_triton.py 在一个 grid 内推进多层计算，triton_utils.py 用原子 release 通知和 acquire 等待表达跨块依赖。模型每层的旗标、临时输出、KV cache 和 position 是理解主线的关键。

```text
生产块写中间结果 → release 更新完成计数
消费块 acquire 观察到预期计数 → 才读中间结果
本轮所有消费者结束 → 允许复用缓冲区与重置计数
下一 token 使用更新后的 KV cache 和 position
```

这是一种依赖特定网格、驻留资源和内存顺序的实现。若等待的生产块尚未被调度，而所有资源都被等待者占满，普通跨块自旋有无法推进的风险。不能把这种协议当成任意 grid 的通用屏障。计数器的初始值、每步重置与失败后恢复也属于正确性。

当前 model_triton 包装断言 batch_size=1，共享模块级 _FLAG，源码明确写明**非线程安全**；README 的交互入口只声明支持 Qwen3-0.6B。因此，这个原型不能直接解释为支持并发服务、所有 Qwen3 模型或通用训练。

### 怎样判断融合到哪一层

比较独立算子、融合子模块、模型单步三个层次，分别记录启动数、临时存储、寄存器/LDS 或 shared 占用、同步等待和输出误差。融合太大也可能减少并行、增加 spill 或引入复杂等待。

端到端解码还需固定模型、输入 token、上下文长度、采样、KV cache、预填充和计时边界。上游自己将 chat.py 的测速描述为不严格；这里不转述 tok/s 作为可复现承诺，也不据此宣称 Burn 已集成 Megakernel。

## 从正确性工具走到性能定位 {#cuda-profiling}

以下命令用于**具备对应 NVIDIA 环境的机器**，本次未运行。先用 Rust 程序做数值对照，再用工具查错，最后单独做无工具开销的基准。环境与下载包见[第 6 章](./rust-gpu.md#rust-gpu-package)。

### Compute Sanitizer：先排查错误

在 NVIDIA 仓库的 `cuda-oxide` 工作区运行：

```sh
cargo oxide sanitize vecadd --tool memcheck
cargo oxide sanitize vecadd --tool racecheck
cargo oxide sanitize vecadd --tool synccheck
cargo oxide sanitize vecadd --tool initcheck
```

memcheck 查越界/未对齐，racecheck 重点查共享内存访问危险，synccheck 查错误同步用法，initcheck 查未初始化的全局内存读取。它们各有检测范围，全部通过也不证明所有数据竞争、数值问题与跨 GPU 协议都正确。参见 [Compute Sanitizer 官方说明](https://docs.nvidia.com/compute-sanitizer/ComputeSanitizer/index.html)。

`cargo oxide sanitize` 负责构建与启动工具，参数按[固定版本 CLI](https://github.com/NVIDIA/cuda-rust/blob/fc747196f2d46dce41bd844e3f5b1c5882751f2b/cuda-oxide/crates/cargo-oxide/src/main.rs)核对。对本站 Tile 包，可先 `cargo +1.98.0 build --locked --bin tile_softmax`，再用 `compute-sanitizer --tool memcheck --error-exitcode 1 target/debug/tile_softmax`。排错时保持小规模与数值断言；工具下耗时不作基准。

### Nsight Compute：一次回答一个瓶颈问题

以本站 Tile 矩乘为例，在学习包目录构建、普通执行并检查结果后，再让 ncu 采集 Rust 可执行文件：

```sh
cargo +1.98.0 build --locked --release --bin tile_matmul
./target/release/tile_matmul
ncu --set full --target-processes all -o tile-matmul ./target/release/tile_matmul
```

这个程序还会创建输入、初始化输出，先从报告中识别真正的矩乘 kernel，再按实际名称筛选，避免把初始化当成矩乘。固定的小规模用于验证流程，不能代表大矩阵性能。首次 JIT / 缓存开销、预热和稳定计时另记。

要按源码行定位，编译还需相应 line info 与匹配源码；Rust host 的 debug 信息不会自动等于设备 kernel 的行信息。SIMT 可按 `cargo oxide` 的 `--lineinfo` 选项设置，Tile 按该版本编译器调试选项核对。报告可能重放 kernel，采集过程不是普通运行。命令语义见 [Nsight Compute CLI](https://docs.nvidia.com/nsight-compute/NsightComputeCli/index.html)。

| 问题 | 观察证据 | 下一步实验 |
| --- | --- | --- |
| 算术是否已接近主要执行单元瓶颈？ | Compute Workload、指令构成 | 调整计算分块或使用适用的矩阵指令 |
| 是否受数据供给限制？ | Memory Workload、缓存与吞吐 | 改复用、访问宽度或布局 |
| shared 布局是否有问题？ | shared 访问的 excessive wavefront 等指标 | 比较 padding/swizzle |
| 寄存器或共享空间限制了驻留？ | Launch Statistics、Occupancy | 减小 tile/stage 并观察整体耗时 |
| warp 为什么没有可执行工作？ | Scheduler/Warp State 与源码位置 | 验证依赖、等待和预取距离 |

Occupancy 是资源驻留指标，不是性能目标本身。更高 occupancy 可能以减少每线程复用为代价；更低 occupancy 的 kernel 也可能充分利用执行单元。优化结论必须回到正确结果和实际耗时。

### Nsight Systems：看 Rust 主机与 CUDA 时间线

同一 Rust 可执行文件可交给 nsys 观察 CUDA 调用、设备活动和主机空隙：

```sh
nsys profile --trace=cuda,nvtx,osrt -o tile-matmul-timeline ./target/release/tile_matmul
```

时间线回答“设备为什么在等、哪些 kernel 之间有空隙”，ncu 回答“某个 kernel 内部受什么限制”。没有额外 NVTX 标注时不会自动得到 Burn 高层算子名称；先确认实际启动，再统计数量。命令选项按安装版本的 [Nsight Systems User Guide](https://docs.nvidia.com/nsight-systems/UserGuide/index.html)核对。PyTorch 的独立对照入口保留在[第 16 章](./pytorch-comparison.md)。


## 本章实验 {#本章实验}

`fusion_measure` 对同一公式 `(a + b) * c` 比较两种写法：Burn eager 会产生临时张量，手工循环只遍历一次。

```sh
cargo run --locked --bin fusion_measure
```

输出两行 `ms/iter`。两者接近并不奇怪：这个规模可能受内存带宽限制，而不是受临时张量数量限制。把 `N` 改大或改小，观察比例怎样变化；不要用一次结果宣布“融合一定更快”。

## 排错、自测与答案 {#排错、自测与答案}

1. `n = 100` 时，上面的两个逐元素内核共多少次元素访问？**答案：**简化模型为 500 次；融合后为 300 次，不含矩阵乘法和缓存影响。
2. 只在 `forward` 前后读主机时钟，省略同步，有什么问题？**答案：**可能主要测到请求准备与提交，设备还没完成。
3. 首次 100 ms，后续 5 ms，应该只报告哪个？**答案：**分别报告冷启动和稳态，并说明测量边界。
4. 结果变快但误差超出容差，能说优化成功吗？**答案：**不能；需要先满足数值与任务准确率要求。
5. GPU 利用率不高该先做什么？**答案：**先看数据准备、传输、同步和任务规模，再用性能工具定位，不能仅凭利用率断定内核有问题。

下一章把这些测量原则放到[导入与部署](./import-and-deploy.md)中；想理解优化实现时，按[源码阅读路线](./source-reading.md)查看融合器与运行时。完整来源见[参考资料](./references.md)。
