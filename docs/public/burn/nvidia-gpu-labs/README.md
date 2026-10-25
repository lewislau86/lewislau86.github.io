# NVIDIA Rust GPU 小型学习包

配合 Burn 教程第 6 / 18 章，主机与设备端均使用 Rust。

**当前验证范围：** Rustfmt 检查、Cargo 依赖解析与锁文件生成已完成。本地是 macOS arm64，未编译 CUDA 代码或执行 GPU。下面命令是面向具备环境的 Linux 主机的验收步骤，不是本机通过记录。

## 环境与版本

- NVIDIA/cuda-rust 固定提交：`fc747196f2d46dce41bd844e3f5b1c5882751f2b`。
- 本包使用 `cutile-rs`，对应官方工作区工具链 Rust **1.98.0**；不是 cuda-oxide 的 1.99.1 工具链。
- Linux（上游测试 Ubuntu 24.04）、NVIDIA GPU、相容驱动与 CUDA Toolkit；上游推荐 **13.3**。Clang / libclang 等构建依赖依官方安装页配置。
- 设备与操作需满足 Tile IR 版本：[固定提交的兼容表](https://github.com/NVIDIA/cuda-rust/blob/fc747196f2d46dce41bd844e3f5b1c5882751f2b/cutile-rs/cutile-book/reference/compatibility.md)。Hopper sm_90 要求 13.3，sm_107 要求 13.4。
- 必要时设置 `CUDA_TOOLKIT_PATH`；`CUTILE_TILEIRAS_PATH` 可覆盖 assembler 路径。
- 不依赖 Python、PyTorch、Burn 或 Candle。CUDA 工具链仍是独立的系统依赖。

依赖与宏、编译器、主机运行时固定为同一 git 提交；Cargo.lock 固定解析，不固定系统驱动和 Toolkit。

## 运行

在当前目录执行：

```sh
rustup toolchain install 1.98.0 --profile minimal
cargo +1.98.0 run --locked --bin tile_add
cargo +1.98.0 run --locked --bin tile_softmax
cargo +1.98.0 run --locked --bin tile_matmul
```

每个程序读回后检查全部输出，只有断言通过才打印 `PASS`；设备或编译错误返回失败，不以静默 SKIP 表示通过。

| 程序 | 输入 / tile | 检查 |
| --- | --- | --- |
| tile_add | N=1024 / B=128 | arange + 1，逐元素精确比较 |
| tile_softmax | 4×8 / 2×8 | Rust f64 稳定 Softmax、逐元素误差、有限值与行和 |
| tile_matmul | 32×16 @ 16×32 / 16×16×8 | 非均匀输入，与 Rust f64 点积逐元素比较 |

三个程序仅支持这里演示的固定形状、连续 f32 数据与设备 0。不提供任意 shape、非整除 K、空 grid、转置、广播、梯度或 Burn 集成。小矩阵便于排错，不是性能基准；调用 `mma` 不保证某种硬件指令选择。

## 来源与修改

源自 [NVIDIA/cuda-rust](https://github.com/NVIDIA/cuda-rust/tree/fc747196f2d46dce41bd844e3f5b1c5882751f2b) 的以下文件（Apache-2.0，原始版权标记保留于源码）：

- `README.md`、`cutile-rs/cutile-examples/examples/async_add.rs`：改为显式 stream、一次加法、全量输出检查。
- `cutile-rs/cutile-examples/examples/softmax.rs`：保留 tile 归约，输出改为零初始化，并补 f64 逐值参考、有限值与行和检查。
- `cutile-rs/cutile-examples/examples/gemm.rs`：固定为 f32，缩小矩阵、改用非均匀输入、补长度与全部输出断言。仍限定整除分块。

`LICENSE` 随包保留。`cuda-oxide` SIMT、CuTe Rust 预览与此包使用不同入口，不能混用编译命令。
