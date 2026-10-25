---
title: "第 6 章：Rust GPU 编程与 CubeCL"
description: "区分 Rust 主机接口、SIMT、Tile 与 Burn 的 CubeCL 路径。"
pageClass: burn-course
---

# 第 6 章：Rust GPU 编程与 CubeCL

[课程总览](./index.md) · [上一章](./gpu-programming.md) · [下一章](./first-burn-inference.md) · [资料与版本](./references.md)

::: tip 本章学习目标
区分 Rust 主机接口、SIMT、Tile 与 Burn 的 CubeCL 路径。

**实践方式：** 工具链与源码阅读，GPU 移植待验证。历史验证范围统一见[实验索引](./learning-labs.md)。
:::

学完向量加法的索引和数据流，接下来可以问：同一个 kernel 能否用 Rust 表达？可以，但先要区分“主机用 Rust 调用 CUDA”“设备上的 kernel 用 Rust 编写”和“Rust 深度学习框架管理整条计算”三个层次。

本页于 **2026-10-25** 核对项目资料。这里整理概念和后续实验路径，本次没有编译 Rust CUDA 工具链、运行 GPU kernel 或验证与 Burn 的互操作。

## Rust CUDA 现在有哪些路线 {#一、rust-cuda-现在有哪些路线}

NVIDIA 的当前入口是 [NVIDIA/cuda-rust](https://github.com/NVIDIA/cuda-rust)，同时提供 SIMT、Tile 两种 kernel 编程方式与共享主机运行时。仓库仍将项目定位为早期研究阶段；安装时应以选定提交的工具链和各自手册为准。[本页核对的 README](https://github.com/NVIDIA/cuda-rust/blob/fc747196f2d46dce41bd844e3f5b1c5882751f2b/README.md)。

| 路线 | 主要负责什么 | 与 learn-cuda 的衔接 |
| --- | --- | --- |
| NVIDIA `cuda-oxide` | 用 Rust 表达 SIMT kernel，显式组织线程与块，编译到 PTX | 适合对应向量加法索引、线程协作与共享内存 |
| NVIDIA `cutile-rs` | 用 Rust 表达对数据块的计算，由编译器安排到底层线程的映射 | 适合从分块矩乘理解 Tile 编程模型 |
| 社区 `Rust-GPU/rust-cuda` | 另一套 Rust CUDA 编译与库生态 | 阅读它自己的编译器、设备库和示例，单独管理工具链 |
| `cudarc` | 在 Rust 主机程序中使用 CUDA 的驱动、内存、编译与库接口 | 用来理解加载 kernel、管理设备缓冲区和启动计算 |
| `CubeCL` | Rust 的计算语言扩展、JIT 编译和多后端运行时 | 接到本书 Burn 的 Cube 后端与自定义 kernel |

后三项分别参见[社区 Rust-CUDA](https://github.com/Rust-GPU/rust-cuda)、[cudarc](https://github.com/chelsea0x3b/cudarc) 和 [CubeCL](https://github.com/tracel-ai/cubecl)。名称相近并不表示这些项目共享 API、编译器或设备缓冲区类型。

### 选择 SIMT 还是 Tile {#选择-simt-还是-tile}

SIMT 的第一步是“我这个线程做什么”：计算索引，再读写自己负责的位置。Tile 的第一步是“我这个程序处理哪块数据”：加载、计算并存回数据块，让编译器负责许多线程映射细节。[NVIDIA 的编程模型说明](https://docs.nvidia.com/cuda/cuda-programming-guide/01-introduction/programming-model.html#tile-programming-in-cuda)。

为了接上 learn-cuda，建议先读 SIMT 向量加法，再阅读 Tile 矩乘。不要把 Tile 等同于单纯换成另一种矩阵语法；还要看分区、输出所有权、布局和启动范围分别由谁确定。

### 工具链跟随项目版本 {#工具链跟随项目版本}

本次核对的 NVIDIA README 中，`cuda-oxide` 使用项目固定的 stable Rust，由 `cargo oxide` 管理；`cutile-rs` 使用其手册约定的 stable Rust 环境。旧文章中关于 nightly 的描述需要结合文章日期检查，不能代替当前仓库配置。

社区 Rust-CUDA 是独立项目，本次核对的[工具链文件](https://github.com/Rust-GPU/rust-cuda/blob/main/rust-toolchain.toml)固定了自己的 nightly。它的安装步骤不能与 NVIDIA 的 `cuda-oxide` 混用。

阅读与安装入口分别是 [cuda-oxide Book](https://nvidia.github.io/cuda-rust/cuda-oxide/) 和 [cuTile Rust 文档](https://nvidia.github.io/cuda-rust/cutile/)。真正复现实验时另记源码提交、Rust 工具链、CUDA Toolkit、驱动、GPU 和计算能力；本书 Flex 学习包的版本锁定不覆盖这些外部项目。

## 换成 Rust 后，哪些问题仍然存在 {#二、换成-rust-后-哪些问题仍然存在}

从 CUDA C++ 换到 Rust，仍然要定义数学、分配内存、启动工作并等待结果。下面是职责映射，不是跨库可直接替换的 API 表：

| 已经在 learn-cuda 看到的工作 | Rust 路径中继续追问什么 |
| --- | --- |
| PyTorch 创建输入与输出 | 哪个主机对象拥有设备缓冲区，什么时候释放？ |
| C++ 包装函数传设备指针 | kernel 参数怎样描述长度、布局、可变访问和借用？ |
| 配置 grid/block 或数据块 | 启动规模是否覆盖输入，尾部位置怎样处理？ |
| 线程读写与块内协作 | 哪些访问可并行，哪些依赖需要同步？ |
| 读回并与参考结果比较 | 怎样保证设备工作完成，误差阈值是什么？ |

例如，主机刚提交了一次写入，就立即释放或复用输出缓冲区，会产生生命周期问题。Rust GPU 库需要把设备仍在执行这件事纳入资源管理；具体保证由各自类型与启动接口提供。看到 `&mut` 或“安全接口”，仍要阅读它保证了哪些访问约束，以及哪些同步责任留给调用者。

先保留这些问题，比同时背下几套库的函数名更有助于进入 Burn。

## Burn 与这些工具位于哪一层 {#三、burn-与这些工具位于哪一层}

在本书固定的 **Burn v0.22.1** 中，Cube 后端使用 CubeCL 的 kernel 与运行时。其[后端源码说明](https://github.com/tracel-ai/burn/blob/v0.22.1/crates/burn-cubecl/src/lib.rs)也说明了运行时选择与可选 Fusion 包装。主线可以这样读：

```text
模型：Linear、激活函数、参数与训练逻辑
        ↓
Burn：公共 Tensor → Bridge / Dispatch → 后端
        ↓ 选择 Cube 路径时
Cube 后端：可选 Fusion + 张量操作实现
        ↓
CubeCL：kernel 表达、编译与运行时
        ↓
选定的计算设备
```

这张图只展开 Cube 路径。第一套 CPU 实验用的是 Flex，不能把它的执行过程全部套进 CubeCL。

NVIDIA CUDA Rust 和社区 Rust-CUDA 可以作为独立的底层学习路线。使用它们写出向量加法，并不自动获得 Burn 的 Tensor 接口、梯度、融合元数据或模型集成。若要接入，还需要明确设备缓冲区、布局、dtype、执行流与生命周期怎样衔接，并完成相应的后端接口。

因此，第一遍建议沿着下面的顺序推进：

1. 在 learn-cuda 中理解算子的数学、索引、协作和数据流。
2. 选一条 Rust CUDA 路线，比较同一个问题怎样表达；这一步可先阅读。
3. 进入 Burn，先跑 Flex CPU 主线，再理解后端、求导与融合。
4. 要为 Burn 写专用 GPU kernel 时，从固定版本的 CubeCL 示例与第 15 章扩展接口继续。

## 从模型表达式走到设备 {#从模型表达式走到设备}

先把整个过程看成一条路线：

```text
主机侧 Rust 程序
  → 创建 Device，准备 X、W、b
  → 创建目标设备上的张量
  → Tensor 操作经过 Bridge、Dispatch 路由到底层 backend
  → 运行时准备 buffer、内核及启动参数
  → 提交设备任务
  → 设备读取输入并写入输出
  → 等待完成，按需把结果读回主机
```

**backend（后端）**负责实现张量操作；**runtime（运行时）**负责面向具体设备管理内存、编译与执行等事务。`Dispatch` 是根据张量所属设备选择实现的路由层。初学时先把它们理解成“选择谁来算”和“安排它怎样算”。

Burn v0.22.1 的应用层使用 `Tensor<D>` 和 `Device`。`D` 是维数，例如这里的 `Tensor<2>`；底层实现仍使用 `Backend` 等 trait。旧资料里的 `Tensor<B, D>` 不能直接当作当前公共 API。

下面是公式对应的应用层核心片段；参数必须已经位于兼容设备，完整依赖与实验步骤见[实验路线](./learning-labs.md)。本章未独立编译此片段。

```rust
use burn::tensor::{Tensor, activation};

fn layer(x: Tensor<2>, w: Tensor<2>, b: Tensor<2>) -> Tensor<2> {
    activation::relu(x.matmul(w) + b)
}
```

这段代码表达“要算什么”，没有指定一个 GPU 线程负责哪一格，也没有承诺它只启动一个内核。源码中，公共 `matmul` 会检查形状，再下沉到实现层；CubeCL 后端的 `float_matmul` 会调用矩阵乘法实现。[公共矩阵乘法源码](https://github.com/tracel-ai/burn/blob/v0.22.1/crates/burn-tensor/src/tensor/api/numeric.rs)、[CubeCL 操作实现](https://github.com/tracel-ai/burn/blob/v0.22.1/crates/burn-cubecl/src/ops/tensor.rs)。

## CubeCL、WGPU 与编译：不要混在一起 {#cubecl、wgpu-与编译-不要混在一起}

**CubeCL** 提供编写和编译可移植计算内核的能力。Burn 的 `burn-cubecl` 把张量操作实现为 CubeCL 内核；同一个 `CubeBackend` 可以服务多个运行时，设备决定具体使用哪个运行时。

**wgpu** 提供跨图形 API 的设备计算接口。Burn 的 `burn-wgpu` 是 CubeCL 的一个运行时入口，可通过相关平台 API 执行计算；CubeCL 还支持其他运行时。因此，两者不是互相替代的两个模型框架。[CubeCL 后端说明](https://github.com/tracel-ai/burn/blob/v0.22.1/crates/burn-cubecl/src/lib.rs)、[WGPU 运行时说明](https://github.com/tracel-ai/burn/blob/v0.22.1/crates/burn-wgpu/src/lib.rs)。

这里还有两次不同层次的“编译”：

| 编译 | 什么时候 | 主要产物 |
| --- | --- | --- |
| Cargo / Rust 编译 | 构建 Rust 项目时 | 应用程序与依赖的主机侧代码 |
| JIT（即时编译） | 程序运行、需要特定设备内核时 | 适合当前运行时和计算配置的设备内核 |

JIT 的英文是 Just-In-Time。它并不是每次推理都重新执行 `cargo build`；内核缓存等机制可以复用已准备的结果。首次运行还可能包含设备初始化与 **autotune（自动调优）**，即测量候选内核并选择实现，所以首次耗时不代表稳定推理耗时。

## 把同一个问题带入 Burn {#四、把同一个问题带入-burn}

| GPU 编程学习的问题 | Burn 中继续阅读 | 应留下的解释 |
| --- | --- | --- |
| 谁决定形状与数据含义？ | [第 3 章](./tensors-and-memory.md) | rank、shape、stride、dtype 和设备分别是什么 |
| 公共调用怎样交给具体计算？ | [第 9 章](./backends-and-dispatch.md) | Tensor、Bridge、Dispatch 与具体后端怎样衔接 |
| kernel 跑完，为什么还不能训练？ | [第 10 章](./autodiff.md) | 前向数值与反向规则是不同职责 |
| 线程和内存怎样组织？ | [第 5 章](./gpu-programming.md) | 工作划分、边界、数据复用与同步 |
| 主机返回时设备完成了吗？ | [第 12 章](./execution.md) | 提交、排队、执行、同步与读回的边界 |
| 哪些中间值可以省掉？ | [第 13 章](./fusion-and-performance.md) | 分块、融合和减少搬运各自改变什么 |
| 怎样让框架调用新操作？ | [第 15 章](./custom-operators.md) | 公共包装、实现、求导与融合接入分别补什么 |

## 后续实验怎样验收 {#五、后续实验怎样验收}

下面是后续实施顺序，本次只完成资料与源码阅读；尚未提供经过 GPU 验证的 Rust CUDA 移植包。

| 步骤 | 最小对象 | 验收方式 |
| --- | --- | --- |
| 独立 Rust CUDA | 向量加法 | 与 CPU 参考比较；覆盖空输入的主机处理、尾块和非整倍数长度 |
| 内存与协作 | 小规模求和 | 检查局部结果、同步与合并过程，记录浮点误差 |
| 数据复用 | 小矩阵乘法 | 从朴素版本开始，核对非整齐尺寸，再比较分块 |
| Burn 扩展 | 先用已有乘加表达的操作 | 先验证前向，再验证非全 1 的上游梯度 |
| Burn 专用 kernel | 替换已有可信的组合实现 | 比较 shape、dtype、布局、设备、误差与梯度，最后测性能 |

没有 NVIDIA GPU 时，可以先完成第 5～6 章的阅读任务和 Burn 的 Flex CPU 实验。Apple Silicon 的 WGPU/Metal 可以作为后续 CubeCL 实验方向，但具体环境与结果需要另行验证。
