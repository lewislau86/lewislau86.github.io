---
title: "第 6 章：Rust GPU 编程与 CubeCL"
description: "区分 Rust 主机接口、SIMT、Tile 与 Burn 的 CubeCL 路径。"
pageClass: burn-course
---

# 第 6 章：Rust GPU 编程与 CubeCL

[课程总览](./index.md) · [上一章](./gpu-programming.md) · [下一章](./first-burn-inference.md) · [资料与版本](./references.md)

::: tip 本章学习目标
区分 Rust 主机接口、SIMT、Tile 与 Burn 的 CubeCL 路径。

**实践方式：** NVIDIA Rust SIMT / Tile 源码、三个小型 Tile 程序与 Rust CPU 参考。GPU 编译和运行待验证，详见[实验索引](./learning-labs.md#rust-cuda-labs)。
:::

学完向量加法的索引和数据流，接下来可以问：同一个 kernel 能否用 Rust 表达？可以，但先要区分“主机用 Rust 调用 CUDA”“设备上的 kernel 用 Rust 编写”和“Rust 深度学习框架管理整条计算”三个层次。

本页于 **2026-10-25** 对照 NVIDIA 仓库的实际源码核对。GPU 实践使用 Rust，learn-cuda 的 C++/Python 用于比较算法与上游实现。本站 Rust CPU 数学参考已运行；本机为 Apple Silicon，没有编译 NVIDIA 设备代码、运行 CUDA kernel 或验证与 Burn 的互操作。

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

为了接上 learn-cuda，先读 SIMT 向量加法，再运行 Tile 加法、Softmax 和小矩阵乘法。SIMT 这条路径提前生成 PTX，驱动可在加载时进一步 JIT；Tile 在首次使用特化配置时生成 Tile IR 并经 `tileiras` 得到 cubin。两者都可能有首次编译或加载开销。

### 工具链跟随项目版本 {#工具链跟随项目版本}

以下均针对提交 `fc747196f2d46dce41bd844e3f5b1c5882751f2b`，不能把“都用 stable Rust”理解为任意工具链都能互换：

| 条件 | cuda-oxide / SIMT | cutile-rs / Tile |
| --- | --- | --- |
| 主机环境 | Linux，官方安装页测试 Ubuntu 24.04 | Linux，官方示例测试 Ubuntu 24.04 |
| Rust | 固定 **1.99.1**，还需 rust-src、rustc-dev、llvm-tools 等组件 | 工作区固定 **1.98.0**；包声明最低 1.89 |
| CUDA 与编译 | Toolkit **13.0+**；LLVM NVPTX 21+ 可用工具及 Clang 开发依赖按安装页检查 | 推荐 Toolkit **13.3**，需要匹配的 Tile IR assembler |
| 设备 | Ampere / sm_80 起，具体 kernel 可能要求更新架构 | 需要同时满足目标架构、Tile IR 版本与算子限制 |

SIMT 安装页的驱动 580+ 是 CUDA 13.x 基线，不能据此保证所有新版工具生成的 PTX 都能由旧驱动 JIT。先运行 `cargo oxide doctor`，再核对实际 PTX / Toolkit / 驱动组合。[SIMT 安装说明](https://github.com/NVIDIA/cuda-rust/blob/fc747196f2d46dce41bd844e3f5b1c5882751f2b/cuda-oxide/cuda-oxide-book/getting-started/installation.md)。

Tile 的基线操作与多个 Ampere、Ada、Blackwell 目标可用 Tile IR 13.2；**Hopper sm_90 要求 13.3，sm_107 要求 13.4**。FP4、block-scaled MMA 还有自己的版本、dtype 与架构条件。`CUDA_TOOLKIT_PATH` 选择 Toolkit，`CUTILE_TILEIRAS_PATH` 可单独选择 assembler；不能只看 `nvidia-smi` 显示的版本。[固定版本兼容表](https://github.com/NVIDIA/cuda-rust/blob/fc747196f2d46dce41bd844e3f5b1c5882751f2b/cutile-rs/cutile-book/reference/compatibility.md)。

社区 Rust-CUDA 是独立项目，本次核对的[工具链文件](https://github.com/Rust-GPU/rust-cuda/blob/main/rust-toolchain.toml)固定了自己的 nightly。它的安装步骤不能与 NVIDIA 的 `cuda-oxide` 混用。

阅读与安装入口分别是 [cuda-oxide Book](https://nvidia.github.io/cuda-rust/cuda-oxide/) 和 [cuTile Rust 文档](https://nvidia.github.io/cuda-rust/cutile/)。真正复现实验时另记源码提交、Rust 工具链、CUDA Toolkit、驱动、GPU 和计算能力；本书 Flex 学习包的版本锁定不覆盖这些外部项目。

## 用 cuda-oxide 写同一个向量加法 {#nvidia-simt}

先按上述安装页准备 Linux CUDA 环境，再固定源码。以下命令按仓库配置核对，本次未在 GPU 机器执行：

```sh
git clone https://github.com/NVIDIA/cuda-rust.git
cd cuda-rust
git checkout --detach fc747196f2d46dce41bd844e3f5b1c5882751f2b
cd cuda-oxide
cargo oxide doctor
cargo oxide list
cargo oxide run vecadd
cargo oxide inspect vecadd
```

这里的 `cargo oxide` 是工作区的 Cargo alias，运行仓库内的构建工具。实际例子位于 [vecadd/src/main.rs](https://github.com/NVIDIA/cuda-rust/blob/fc747196f2d46dce41bd844e3f5b1c5882751f2b/cuda-oxide/crates/rustc-codegen-cuda/examples/vecadd/src/main.rs)，不是仓库根目录的 examples。

设备端核心如下，保留了官方示例的接口。这是单个模块的阅读片段，完整 host 与依赖使用上面的官方例子：

```rust
use cuda_device::{DisjointSlice, cuda_module, kernel, thread};

#[cuda_module]
mod kernels {
    use super::*;

    #[kernel]
    pub fn vecadd(a: &[f32], b: &[f32], mut c: DisjointSlice<f32>) {
        let idx = thread::index_1d();
        if let Some(out) = c.get_mut(idx) {
            let i = idx.get();
            *out = a[i] + b[i];
        }
    }
}
```

`thread::index_1d()` 对应上一章的全局线性编号；`DisjointSlice` 用线程索引表达互不重叠的输出访问。输出边界保护仍不足以证明输入长度正确，host 必须保证 `a.len() == b.len() == c.len()`。

host 的职责依次是：

| Rust 调用 | 数据与生命周期 |
| --- | --- |
| `CudaContext::new(0)`、`default_stream()` | 选择设备，取得执行流 |
| `DeviceBuffer::from_host`、`zeroed` | 上传两个输入，创建输出；所有对象覆盖设备访问期间 |
| `kernels::load` | 加载随程序嵌入的设备产物 |
| `module.vecadd` | 传入流、launch 配置与缓冲区借用 |
| `c_dev.to_host_vec(&stream)` | 按该 API 的完成约定读回，再逐元素核对 |

此版本的官方 `vecadd` 使用未声明 launch contract 的 **unsafe 启动**，由调用者保证形状、覆盖范围与访问条件。官方 [Hello GPU](https://github.com/NVIDIA/cuda-rust/blob/fc747196f2d46dce41bd844e3f5b1c5882751f2b/cuda-oxide/cuda-oxide-book/getting-started/hello-gpu.md)另演示 `#[launch_contract(...)]`、`LaunchConfig1D` 与 `prepare_vecadd`：先验证配置，再调用 typed launch。两种示例的 unsafe 边界不同，不能拼接成另一套签名；prepared launch 也不会替你证明所有输入的数学契约。

官方向量例子默认 N=1024。下一步可改为 1000，确认尾部覆盖；空输入要先由 host 返回，避免启动零 grid。不要只检查前五个打印值，要检查全部结果。

## 用 cutile-rs 表达数据块 {#nvidia-tile}

Tile 示例不从单线程索引开始。输出按 `[128]` 分区，每个程序拿到自己的一块输出，两个只读输入按同一位置加载：

```rust
use cutile::prelude::*;

#[cutile::module]
mod kernels {
    use cutile::core::*;

    #[cutile::entry()]
    fn add<const B: i32>(
        z: &mut Tensor<f32, { [B] }>,
        x: &Tensor<f32, { [-1] }>,
        y: &Tensor<f32, { [-1] }>,
    ) {
        let tx = x.load_like(z);
        let ty = y.load_like(z);
        z.store(tx + ty);
    }
}

fn main() -> Result<(), Error> {
    let device = Device::new(0)?;
    let stream = device.new_stream()?;
    let x = api::arange::<f32>(1024);
    let y = api::ones::<f32>(&[1024]);
    let z = api::zeros::<f32>(&[1024]).partition([128]);
    let out: Vec<f32> = kernels::add(z, x, y)
        .first().unpartition().to_host_vec().sync_on(&stream)?;
    assert_eq!(out.len(), 1024);
    for (i, value) in out.iter().enumerate() {
        assert_eq!(*value, i as f32 + 1.0);
    }
    Ok(())
}
```

这是本站 `tile_add.rs` 的完整程序逻辑；依赖见下面的学习包。`[-1]` 表示动态轴，`[B]` 是这次输出 tile 的形状。`Tensor` 属于 cutile，不能直接替换 Burn 的同名类型。

`api::arange` 等创建可组合的 DeviceOperation；`.sync_on(&stream)` 执行这条操作链并等待结果。异步例子用 `.await` 等待，同样需要维护执行期资源；Rust 的 future 不是 CPU 上代算 kernel。`.first()` 选择返回元组中的输出，`unpartition` 恢复整体张量视图。

### 三个小型 Rust GPU 程序 {#rust-gpu-package}

下载 [NVIDIA Rust GPU 学习包](/burn/nvidia-gpu-labs.zip)。它与 Burn Flex 包独立，直接依赖固定提交的 `cutile`、`cuda-async`、`cuda-core`，附带 Cargo.lock、源码来源、修改说明和 Apache-2.0 许可证。**三个程序仅完成源码接口核对与 Rust 格式检查，尚未编译或在 GPU 执行。**

在符合前述条件的 Linux CUDA 机器解压，从 `nvidia-gpu-labs` 目录运行；按官方工具链先安装 Rust 1.98.0：

```sh
cargo +1.98.0 run --locked --bin tile_add
cargo +1.98.0 run --locked --bin tile_softmax
cargo +1.98.0 run --locked --bin tile_matmul
```

| 程序 | 固定规模与计算 | 验收代码 |
| --- | --- | --- |
| `tile_add` | 1024 个 f32，128 元素一块，arange + 1 | 检查长度与全部输出 |
| `tile_softmax` | 4×8，2×8 的 tile，每行减最大值后 exp / sum | Rust f64 参考逐值比较、有限值与行和 |
| `tile_matmul` | 32×16 乘 16×32，16×16×8 分块 | 非均匀输入，全部输出与 Rust f64 点积比较 |

矩乘 kernel 按 K/BK 循环，这个例子只使用整除尺寸。它没有任意 K 尾块、广播、转置、causal mask 或反向支持；这些是下一步需要分别增加的契约。使用 f32 的 `mma` 也不能仅凭函数名断言一定生成某条 Tensor Core 指令，要看编译产物和实际目标。

也可直接运行 NVIDIA 的官方例子：从克隆仓库的 `cuda-oxide` 返回上一级，再进入 `cutile-rs` 工作区：

```sh
cd ../cutile-rs
cargo run -p cutile-examples --example hello_world
cargo run -p cutile-examples --example async_add
cargo run -p cutile-examples --example softmax
cargo run -p cutile-examples --features reference-cpu --example flash_attention
```

官方 `gemm` / `gemm_static` 默认规模很大，且主要打印前十项，本书先用小矩阵并逐值断言。`flash_attention` 的 CPU 对照使用 Candle，需显式开启 `reference-cpu`；在 aarch64 上按上游说明配置本机 CPU 特征。部分官方例子的能力检查会打印 **SKIP** 后正常退出，不能把退出码 0 当成 GPU 已运行或数值已通过。

### 继续读 NVIDIA 的进阶 Rust 源码

| 主题 | 固定提交下的真实位置 | 与 learn-cuda 的关系 |
| --- | --- | --- |
| Tile Softmax / Attention | [softmax.rs](https://github.com/NVIDIA/cuda-rust/blob/fc747196f2d46dce41bd844e3f5b1c5882751f2b/cutile-rs/cutile-examples/examples/softmax.rs)、[flash_attention.rs](https://github.com/NVIDIA/cuda-rust/blob/fc747196f2d46dce41bd844e3f5b1c5882751f2b/cutile-rs/cutile-examples/examples/flash_attention.rs) | 比较 reduce、online 状态与 tile 数据流 |
| 持久化矩乘 | [persistent_gemm.rs](https://github.com/NVIDIA/cuda-rust/blob/fc747196f2d46dce41bd844e3f5b1c5882751f2b/cutile-rs/cutile-examples/examples/persistent_gemm.rs) | 对照任务复用、grid 与资源占用 |
| SM100 / SM120 Attention | [sm100_fmha_prefill_cute](https://github.com/NVIDIA/cuda-rust/tree/fc747196f2d46dce41bd844e3f5b1c5882751f2b/cuda-oxide/cute-rs-preview/examples/sm100_fmha_prefill_cute)、[fmha_decode_sm120a_cute](https://github.com/NVIDIA/cuda-rust/tree/fc747196f2d46dce41bd844e3f5b1c5882751f2b/cuda-oxide/cute-rs-preview/examples/fmha_decode_sm120a_cute) | 对照架构专用流水线、prefill 与 decode |
| 低精度 GEMV / MLP | [nvfp4_gemv_cute](https://github.com/NVIDIA/cuda-rust/tree/fc747196f2d46dce41bd844e3f5b1c5882751f2b/cuda-oxide/cute-rs-preview/examples/nvfp4_gemv_cute)、[ffn_cute](https://github.com/NVIDIA/cuda-rust/tree/fc747196f2d46dce41bd844e3f5b1c5882751f2b/cuda-oxide/cute-rs-preview/examples/ffn_cute) | 比较带宽、量化尺度与融合边界 |

`cute-rs-preview` 是基于 cuda-oxide 的 **CuTe Rust 预览**，要遵守各例子的架构、依赖与启动说明，不能直接当作 cutile-rs 的示例运行。NVFP4 也不等于 learn-cuda 的 E3M2 FP6。归约、Box Blur、FP6、P2P 与 Megakernel 的完整 Rust GPU 对应实现仍需逐项编写和验证；CPU 数学参考只覆盖其中的数学部分。AMD CDNA3 要使用另一套 HIP/ROCm 工具链。

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
2. 按本章 NVIDIA 路线比较 SIMT / Tile，用 Rust 参考和三个小型程序逐项验收。
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

## 把 learn-cuda 的问题映射到 Rust {#cuda-rust-mapping}

迁移时先固定数学与数据契约，再选 API。以下是职责清单，不是声称已经实现的 Rust 移植包。

| learn-cuda 主题 | Rust SIMT 路径中应表达什么 | CubeCL / Burn 中继续检查 |
| --- | --- | --- |
| 向量加法 | buffer、长度、索引、尾块与 launch | 输出所有权、读回与目标运行时 |
| 归约 / Softmax | 局部和、协作组、屏障、shuffle/原子 | reduction 支持、浮点容差与 scratch 生命周期 |
| SIMT 矩乘 | 多层 tile、共享块、寄存器累加器 | 使用已有矩乘实现还是独立 kernel |
| 硬件矩阵指令 | 所选 Rust 工具链是否暴露对应指令与布局 | 目标编译器/运行时是否支持，是否需回退 |
| FP6 | 数值编码与 packed layout、非法输入策略 | 是否存在相应 dtype/存储/算子支持 |
| Box Blur | 二维索引、边界约定、两次扫描 | 张量 stride、中间缓冲与组合算子语义 |
| Attention | m/l/u 状态、mask、累加精度 | 后端能力、训练反向和模型调用契约 |
| Row-scaled MM | 低精度输入、scale 广播、epilogue | 输出元数据和求导语义 |
| P2P / Megakernel | IPC、跨块/跨设备顺序与资源所有权 | 通用可移植层是否有此能力，专用实现如何隔离 |

### 一个向量加法需要的完整契约

```text
host：
  验证长度相同、dtype/设备兼容
  长度为零时直接返回空输出
  保持输入、输出和执行流存活
  启动覆盖全部元素的 grid
device：
  计算线性索引，越界线程不访问
  每个有效输出只由规定的写入者写
host：
  按运行时约定等待，再读回与参考比较
  所有设备访问结束后，才释放或复用缓冲区
```

语言换成 Rust 后，这些责任不会消失。异步启动返回的 token、事件或流对象能提供哪些生命周期保证，应读所选库的真实签名；不能把 host 的借用检查自动等同于跨设备执行顺序证明。

### 高级实现仍要逐项验证

SM80、SM100、SM120、CDNA3 的实现使用不同指令与资源模型。一个 Rust 库能编译基础 SIMT，不代表它当前版本支持 TMA、tcgen05、动态寄存器分配、HIP MFMA 或 CUDA IPC 的全部接口。

可移植目标先保留同一数学和检查数据，优先使用工具支持的 block/tile 操作；目标专用优化另列设备条件与回退。Tile 编程可以交给编译器更多布局决策，仍需核对支持的 shape、dtype、硬件和生成代码。若接口尚不存在，应明确停在阅读或设计状态，避免拼出一份未经编译的“完整移植”。


## 后续实验怎样验收 {#五、后续实验怎样验收}

下面是推进顺序。Rust CPU 参考已运行，三个 Tile 学习程序与 NVIDIA 官方例子提供了具体入口；GPU 编译、设备数值和性能仍待有对应环境时验收。

| 步骤 | 最小对象 | 验收方式 |
| --- | --- | --- |
| 独立 Rust CUDA | 向量加法 | 与 CPU 参考比较；覆盖空输入的主机处理、尾块和非整倍数长度 |
| 内存与协作 | 小规模求和 | 检查局部结果、同步与合并过程，记录浮点误差 |
| 数据复用 | 小矩阵乘法 | 从朴素版本开始，核对非整齐尺寸，再比较分块 |
| Burn 扩展 | 先用已有乘加表达的操作 | 先验证前向，再验证非全 1 的上游梯度 |
| Burn 专用 kernel | 替换已有可信的组合实现 | 比较 shape、dtype、布局、设备、误差与梯度，最后测性能 |

没有 NVIDIA GPU 时，可以先完成第 5～6 章的阅读任务和 Burn 的 Flex CPU 实验。Apple Silicon 的 WGPU/Metal 可以作为后续 CubeCL 实验方向，但具体环境与结果需要另行验证。
