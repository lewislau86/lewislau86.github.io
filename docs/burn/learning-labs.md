---
title: "第 18 章：实验索引与后续路线"
description: "按检查点回顾学习结果，区分已验证实验和后续计划。"
pageClass: burn-course
---

# 第 18 章：实验索引与后续路线

[课程总览](./index.md) · [上一章](./source-reading.md) · [资料与版本](./references.md)

::: tip 本章学习目标
按检查点回顾学习结果，区分已验证实验和后续计划。

**实践方式：** A–O Burn 实验、R01–R06 NVIDIA Rust GPU 路线、C01–C15 上游主题与 Rust CPU 数学参考。
:::

原理要靠小实验建立联系。这份路线先让每个结果都能手算，再逐步增加训练、设备迁移和性能分析。不要从“大模型能不能跑”开始，否则一旦出错，很难判断是数据、模型、依赖还是后端的问题。

## 本章实验 {#本章实验}

本章不是单个程序，而是全部实验的索引：先按阶段做 A/B，再按章节进入对应实验。每个实验都给出了命令、检查点和“不能证明什么”；没有 GPU 时全部走 CPU 路径。

## 当前已验证的内容 {#当前已验证的内容}

A–F 的验证日期为 **2026-10-23**，环境是 **Windows、Rust 1.98.1、Cargo 1.98.1、Burn 0.22.1、Flex CPU**。G–O 于 **2026-10-24** 在 **macOS aarch64、Rust 1.99.0、Cargo 1.99.0、Burn 0.22.1、Flex CPU** 上运行或复跑。程序在开发构建模式执行，目的是核对基础正确性，不是性能测试。学习包使用锁文件；Burn 本体声明最低 Rust 1.95，较旧工具链未在本次验证。

下载[完整 CPU 学习包](/burn/first-inference.zip)，解压后在项目目录运行下面这些程序。数值实验按程序中的断言检查结果；优化器轨迹和计时示例还需要人工核对输出，不能仅凭正常退出判断数值或性能正确。

| 实验 | 命令 | 检查与结果 | 状态 |
| --- | --- | --- | --- |
| A：固定参数前向 | `cargo run --locked --bin burn-first-inference` | `H = [5.0, 2.0]`，形状 `[1, 2]` | 本次通过 |
| B：封装为 Module | `cargo run --locked --bin module` | 输出 `[5.0, 2.0]`，参数总数 6 | 本次通过 |
| C：自动微分 | `cargo run --locked --bin autodiff` | `y=x²+x` 在 `x=3` 处梯度为 `[7.0]` | 本次通过 |
| D：后端扩展 | `cargo run --locked --bin backend_extension` | 一维前向 `[2,0,12]`；二维形状 `[2,3]`；求和梯度 `[-3,1,7]`；加权求和梯度 `[-6,-1,3.5]` | 本次通过 |

第 16 章另外增加了两份可对照的完整程序。本次 Python 环境为 **3.13.5、PyTorch 2.12.1+cpu**，它与 Cargo 项目的依赖分别管理。

第 7、8、10 章内独立的 PyTorch 片段也在同一环境执行过，分别核对了直接张量前向、Linear 权重转换后的输出，以及 `x=3` 时梯度 `[7.0]`。其他缺少上下文的片段仍按正文标为阅读示意。

| 实验 | 命令 | 检查与结果 | 状态 |
| --- | --- | --- | --- |
| E：Burn 对照基准 | `cargo run --locked --bin comparison` | 主线前向、X/W/b 梯度、加权梯度，以及手动 SGD 单步 `w=1.6`、新损失约 `0.64` | 本次通过 |
| F：PyTorch 同公式 | `python pytorch_compare.py` | 同一组手算结果；另验证转置权重后 `nn.Linear` 与 Burn 主线一致 | 本次通过 |
| G：训练与保存 | `cargo run --locked --bin regression_train -- artifacts/regression` | 400 步后 `weights=[2.0000002]`、`bias=[0.9999994]`；8 个预测与 `2x+1` 一致；写出 `model_config.json`、`model.bpk`、`baseline.txt` | 本次通过 |
| H：新进程加载 | `cargo run --locked --bin regression_verify -- artifacts/regression` | 加载后与保存前的最大差为 `0.000000`；与 `2x+1` 的最大差为 `0.000001`；输出 `OK` | 本次通过 |
| I：张量形状与内存 | `cargo run --locked --bin tensors` | `A @ B = [22, 28, 49, 64]`；reshape 与 transpose 的元素顺序不同 | 本次通过 |
| J：Rust 基础 | `cargo run --locked --bin rust_basics` | 移动、clone、trait、Option/Result 的断言全部通过 | 本次通过 |
| K：设备与 dtype | `cargo run --locked --bin dispatch_path` | `dtype = F32`、`Device<Flex(Cpu)>` | 本次通过 |
| L：优化器轨迹 | `cargo run --locked --bin optimizers` | SGD 收敛到 3；AdamW 因解耦衰减停在约 2.74 | 本次通过 |
| M：提交与读回 | `cargo run --locked --bin execution_trace` | 打印 submit/readback 中位数与近似 GFLOPS；具体数值随机型变化 | 本次通过 |
| N：并行工作项 | `cargo run --locked --bin gpu_probe` | 打印单线程与四线程耗时及实际加速比（CPU 模拟，非 GPU 基准） | 本次通过 |
| O：融合对照 | `cargo run --locked --bin fusion_measure` | 打印 eager 与手工融合的 ms/iter；受内存带宽影响 | 本次通过 |

这些实验覆盖一次推理、张量形状、Rust 基础、参数组织、设备与 dtype、源张量求导、优化器轨迹、提交/读回、并行工作项、融合对照、后端扩展、跨框架对照，以及训练 → 保存 → 新进程加载的完整往返。D 使用已有乘加原语，没有创建专用 kernel；E/F 只做手动 SGD 数学更新；G 使用 Burn 的 `SgdConfig` 验证优化器 API 与小模型收敛，但不保存优化器状态，因此不能精确恢复中断的训练。GPU、Fusion、外部权重导入、浏览器与后端速度排名也尚未验证。

代码可单独下载：<a href="/burn/first-inference/src/main.rs" download>主程序</a>、<a href="/burn/first-inference/src/bin/module.rs" download>Module 例子</a>、<a href="/burn/first-inference/src/bin/autodiff.rs" download>求导例子</a>、<a href="/burn/first-inference/src/bin/backend_extension.rs" download>后端扩展例子</a>、<a href="/burn/first-inference/src/bin/tensors.rs" download>张量例子</a>、<a href="/burn/first-inference/src/bin/rust_basics.rs" download>Rust 基础</a>、<a href="/burn/first-inference/src/bin/dispatch_path.rs" download>设备路径</a>、<a href="/burn/first-inference/src/bin/optimizers.rs" download>优化器</a>、<a href="/burn/first-inference/src/bin/execution_trace.rs" download>执行时间线</a>、<a href="/burn/first-inference/src/bin/gpu_probe.rs" download>并行工作项</a>、<a href="/burn/first-inference/src/bin/fusion_measure.rs" download>融合对照</a>、<a href="/burn/first-inference/src/bin/regression_train.rs" download>回归训练</a>、<a href="/burn/first-inference/src/bin/regression_verify.rs" download>回归加载</a>、<a href="/burn/first-inference/Cargo.toml" download>项目配置</a>、<a href="/burn/first-inference/Cargo.lock" download>锁文件</a>。学习时优先下载完整包，保持目录结构。

对照程序：<a href="/burn/first-inference/src/bin/comparison.rs" download>Burn comparison.rs</a>、<a href="/burn/first-inference/pytorch_compare.py" download>PyTorch pytorch_compare.py</a>。解释与环境检查步骤见[第 16 章](./pytorch-comparison.md)。

## learn-cuda 实验：从数学参考到设备验收 {#cuda-labs}

这里补齐固定提交的 15 个主题；已有 CPU/Burn 实验 A–O 保留原编号。下面另用 C01–C15 表示 learn-cuda 主题，**其 CUDA/HIP 运行状态均为未验证**，不会用文档构建或 CPU 参考代替设备验收。

### 不依赖 GPU 的完整数学参考

下载 <a href="/burn/learn-cuda-reference.rs" download>learn-cuda-reference.rs</a>，仅使用 Rust 标准库，不需要 Cargo 依赖或 Python：

```sh
rustc --edition=2021 -D warnings learn-cuda-reference.rs -o learn-cuda-reference
./learn-cuda-reference
```

本轮在 **macOS arm64、Rust 1.99.0** 上编译执行，八组检查全部通过。Windows 下把输出文件名改为 `learn-cuda-reference.exe`，然后运行该文件。程序使用普通 `assert!` / `assert_eq!`，发布优化也保留这些检查。

| 检查组 | 实际检查的内容 |
| --- | --- |
| 向量加法 | 固定结果、空输入、长度不匹配拒绝 |
| 矩乘 | 手算结果、非方阵、多种 tile 和尾块 |
| 归约 | 空和、奇数长度、树形归约与 f64 顺序求和比较 |
| Softmax | 大值稳定性、平移不变性、分块状态合并 |
| Attention | dense 与分块 m/l/u、不同序列长度、causal 数学参考 |
| Box Blur | 零填充边角、二维直接计算与可分离滑动窗口 |
| FP6 | 全部 64 编码、正负零、中点取偶、固定字节布局与非法值 |
| 缩放矩乘 / GEMV | 缩放轴、广播与固定数值 |

程序使用 Rust f64 做独立数学参考，没有模拟 BF16/FP8 舍入、Tensor Core 指令、GPU 屏障、原子操作或真实缓存。它额外演示 causal 数学与更宽的滤波输入范围，不表示上游 kernel 支持这些扩展。

### NVIDIA Rust GPU 实验入口 {#rust-cuda-labs}

GPU 实践使用 [NVIDIA/cuda-rust 固定提交](https://github.com/NVIDIA/cuda-rust/tree/fc747196f2d46dce41bd844e3f5b1c5882751f2b)，先按[第 6 章](./rust-gpu.md#工具链跟随项目版本)配置 Linux、Rust、Toolkit、驱动与设备。以下项目没有 Python 运行依赖；**本次仅核对源码和接口，未完成 GPU 编译或运行**。

下载 [三个小型 Tile 程序](/burn/nvidia-gpu-labs.zip)，在解压目录运行 R02～R04。R01 与 R05～R06 在 NVIDIA 克隆仓库各自工作区运行，切勿把两套 Cargo 命令混在同一个目录。

| 编号 | 工作目录与命令 | 验收条件 |
| --- | --- | --- |
| R01 · SIMT 加法 | NVIDIA `cuda-oxide`：`cargo oxide doctor`，然后 `cargo oxide run vecadd` | 全部 1024 项通过；修改例子后另检尾块与空输入 host 路径 |
| R02 · Tile 加法 | 本站 `nvidia-gpu-labs`：`cargo +1.98.0 run --locked --bin tile_add` | 全部 1024 项，与 arange + 1 一致 |
| R03 · Tile Softmax | 同上：`cargo +1.98.0 run --locked --bin tile_softmax` | 4×8 输出逐值比较、有限值、每行和 |
| R04 · Tile 矩乘 | 同上：`cargo +1.98.0 run --locked --bin tile_matmul` | 32×16 乘 16×32，全输出与 f64 点积参考比较 |
| R05 · Attention | NVIDIA `cutile-rs`：`cargo run -p cutile-examples --features reference-cpu --example flash_attention` | GPU 路径确实执行、与 Rust Candle 参考比较；不接受 SKIP 作为通过 |
| R06 · 错误检查 | NVIDIA `cuda-oxide`：`cargo oxide sanitize vecadd --tool memcheck` | 保留数值检查，阅读 sanitizer 报告；再分别运行 racecheck / synccheck / initcheck |

本站三个 GPU 程序的直接依赖固定同一 git 提交，Cargo.lock 固定其余解析；附带来源与修改说明。Rustfmt 与依赖解析通过不等于 CUDA 编译通过，程序中写有断言也不表示本机已执行这些设备检查。性能采集见[第 13 章](./fusion-and-performance.md#cuda-profiling)。

### C01–C15 的上游源码对照与验收

这一表保留 learn-cuda 的真实源文件名，便于逐项对照 `afcb20b1bd89065c31a1575c276aba686fc4dfce`；它们是原仓库的 C++ / Python 入口。本站实践主线使用上面的 Rust 程序，不要求先安装这些 Python 依赖。若额外复现原仓库，需单独记录 PyTorch、Triton、CuTe DSL 等版本；其 pyproject.toml 只有 Ruff 配置，没有统一锁定的运行环境。CDNA3 另需 ROCm/HIP 与 gfx942。

| 编号 / 目录 | 源码核对的入口 | 应验收什么 |
| --- | --- | --- |
| C01 · 01_vector_addition | `main.py` → `add.cu` | 扩展加载与 assert_close；另补空输入 host 处理和尾块；Rust 先做 R01/R02 |
| C02 · 02_matmul_simt | `main.py` → `matmul.cu` | v1～v6b、Triton 与参考；快速路径的布局/整除条件；Rust tile 起点 R04 |
| C03 · 02_matmul_sm80 | `main.py` / `matmul_v*.cu` | 当前默认列表并非包含所有历史版本；按 get_kernel/列表选择并逐版比较 |
| C04 · 02_matmul_sm100 | `main.py` 的 Modal benchmark 分支 | 配套 Modal/B200 环境、各版数值与耗时；云端执行条件按上游配置 |
| C05 · 02_matmul_sm120 | `main.py` / `matmul_v*.cu` | BF16/INT8、v0～v3；不能只复现 README 到 v2 的表 |
| C06 · 02_matmul_cdna3 | `main.py` / HIP kernel | gfx942/ROCm；补回被注释的逐元素正确性比较 |
| C07 · 03_sum | `main.py` → `sum.cpp` / `sum.cu` | 所有版本、输出初始化、误差与不整倍数 N；Rust GPU 独立归约待补 |
| C08 · 04_softmax | `main.py` / `softmax.cu` | 四种路径；分母、行和、workspace 与形状变化；Rust 先做 R03 |
| C09 · 05_fp6 | fp6.cu；无独立 main.py | 先补 schema/加载包装，再核对编码、舍入、packed shape 与非法值策略 |
| C10 · 06_box_blur | `main.py` / `box_blur.cu` | v1/v2 对照、固定分母、边角与窗口条件；Rust GPU 待补 |
| C11 · 07_attention | `main.py` / `attention_v*` | v1～v6 与 SDPA；为 v6 补数值比较；Rust 从 R05 继续 |
| C12 · 08_row_scaled_mm | `main.py` 的 int8 / fp8 分支 | 相同量化输入/scales 的数值；另测量化损失 |
| C13 · 10_p2p | `main.py` / `p2p.cu` | 两卡可达性、每 rank 的 [0,1]、子进程状态与 IPC 清理；Rust GPU 待补 |
| C14 · 11_gemv | `main.py` 的 shape 参数 / `cuda_v1.cu` | 支持的 K、M=1、权重布局和输入轮换条件 |
| C15 · 12_megakernel | `mlp_main.py` / `attn_main.py` | 子模块输出和 KV cache；模型级另读 chat.py/model_triton.py |

每行入口不等于完整能力证明。例如 profile 分支可能只启动不比较，benchmark 也可能只选部分版本；阅读入口后应核对实际执行路径。P2P 父进程正常结束还不足以证明每个子进程成功。C15 的交互聊天会下载模型，不必作为第一个检查点，先验证独立子模块。

### 所有设备实验保留同一份记录

```text
主题 / 源码提交 / kernel 版本：
设备 / 驱动 / Toolkit 或 ROCm / Rust 工具链 / Cargo.lock：
若额外运行原仓库：Python / PyTorch / 其他依赖：
shape / dtype / stride / scale 或 mask：
参考实现 / atol / rtol / 最大误差 / 有限值检查：
支持、拒绝或回退的边界输入：
内存与同步工具的结果：
冷启动 / 预热 / 重复次数 / 同步与计时范围：
中位耗时 / 波动 / 缓存与输入轮换条件：
尚未覆盖的条件：
```

先数值、再检查内存和同步、最后性能。对 Attention 还记录 causal/dropout/head_dim；对 FP6 记录格式约定与 packed layout；对 P2P 记录拓扑、每个 rank 的状态和资源结束顺序。

### 当前完整度怎样理解

**15/15 个主题已有对应正文、源码入口、主要演进与验收条件**；Rust CPU 数学参考八组已通过，三个 Rust Tile 学习程序已提供。硬件 kernel 逐版运行、CUDA/HIP 性能复现、15 个主题的完整 Rust GPU 移植、Burn 专用接入仍待完成；数学参考与入门程序不代替这些工作。

机器可读的 <a href="/burn/learn-cuda-coverage.json" download>覆盖清单</a>记录所有主题、固定源码路径、正文位置和运行状态，便于后续逐项更新；主题讲解覆盖与设备验证分开计数。


## 第一阶段：每一步都能手算 {#第一阶段-每一步都能手算}

读完第 2、3、4、7、8 章后做 A、B、I、J；读完第 9 章后做 K。先写下每个张量的形状，再运行代码；每次只改一个输入或一个参数。

建议做两项练习，尚未作为独立实验程序提供：

1. 把偏置改为 `[0, -3]`，预期输出 `[5, 0]`，解释负数在哪一步变成零。
2. 先恢复默认偏置 `[0, 1]`，用两行输入 `[[1, 2], [0, 1]]`，预期输出 `[[5, 2], [2, 2]]`，解释同一组参数怎样服务多个样本。

本阶段验收标准：可以在不运行代码时算出结果；能够指出输入、参数、算子和模型各在哪里；知道 `Tensor<2>` 与形状 `[1, 2]` 不是同一件事。

## 第二阶段：知道梯度为什么是这个数 {#第二阶段-知道梯度为什么是这个数}

先运行实验 C 和 L，手算 `2x+1`，观察 SGD、Momentum、Adam、AdamW 的轨迹。读到第 15 章后运行实验 D：向量输入 `[-2, 0, 3]` 配合求和目标，梯度为 `[-3, 1, 7]`；再乘上常量上游梯度 `[2,-1,0.5]`，得到 `[-6,-1,3.5]`。

下一步实现有限差分检查，分别观察 ε 过大和过小会怎样影响误差。这里的目标是理解梯度检查，不是选择“永远正确”的固定 ε。

然后运行 E/F 和 M（M 用来观察提交与读回的时间边界），把标量导数推广到主线矩阵的 X/W/b 梯度，再观察一次手动更新怎样使损失从 16 降到约 0.64。能解释这个例子后，再进入完整训练循环。

本阶段验收标准：能区分设备允许自动微分、源输入保留梯度、执行 backward 和优化器更新；知道 clone 句柄不能用来恢复已经消耗的反向步骤。

## 第三阶段：完成一个训练与保存闭环 {#第三阶段-完成一个训练与保存闭环}

这条闭环已经由 G/H 两个程序验证，不再是待办计划。训练数据是 `x = -2, -1, 0, 1, 2, 3, 4, 5` 八个样本，目标是 `y = 2x + 1`；每次用全部样本计算平均 MSE，SGD 学习率 `0.05`，训练 400 步。训练程序在固定输入上保存基线预测，验证程序在另一个进程中只读文件重建模型。

| 步骤 | 实现 | 结果与验收 |
| --- | --- | --- |
| 构造数据 | 8 个一维样本，目标 `2x+1` | 输入、目标形状都是 `[8, 1]` |
| 训练 | 全批量前向、MSE、`backward`、`SgdConfig` 更新 | 400 步后 loss 小于 `1e-4`，`weights=[2.0000002]`、`bias=[0.9999994]` |
| 验证 | 切到 `valid()` 后在固定输入上预测 | 8 个预测与 `2x+1` 的误差小于 `1e-3` |
| 保存 | `model_config.json`、`model.bpk`、`baseline.txt` | 能说明结构、参数、基线各自的职责 |
| 恢复 | 新进程读取配置、创建模型、加载参数 | 加载后与保存前的最大差为 `0.000000` |
| 训练恢复 | **未实现**：没有保存优化器、调度器、随机状态和数据位置 | 不声称能精确接续中断的训练 |

这个实验只验证**推理恢复**，不验证跨 Burn 版本、跨后端或跨精度的误差一致性。要精确恢复训练，还需要保存优化器状态、学习率调度器、随机数状态和数据迭代位置；这也是第 11 章“继续训练需要更多状态”一节的内容。

应先完成原生 Burn 模型的保存加载，再加入外部模型格式。这样更容易把“文件往返”与“框架之间语义转换”分开排错。

## 第四阶段：比较 CPU 和 GPU {#第四阶段-比较-cpu-和-gpu}

完成第 5、12、13 章后，运行 N（并行工作项）和 O（融合对照），再给学习包增加可选的 WGPU 等后端。开始时使用同样的固定小数据比较正确性；性能测试则需要扩大矩阵并记录规模。

计划按下面顺序验证：先确认设备能初始化，再验证输出形状和数值，然后区分冷启动、稳态前向、上传与读回，最后观察融合开关是否改变耗时。每次比较都保留版本、features、设备、shape、dtype、同步位置和误差记录。

本阶段验收标准：能够解释小模型在 GPU 上可能更慢的原因；不会把异步请求提交时间当作完整推理时间；不会在没有测量时宣称某条公式一定融合为一个 kernel。

## 第五阶段：导入与扩展 {#第五阶段-导入与扩展}

读完第 15 章，先完成已经提供的实验 D，解释 trait、具体 impl、宏路由和公共 Tensor 函数各自做什么。再分别选择一个外部模型和一个专用内核继续实验。

| 计划实验 | 首个合适对象 | 应检查什么 |
| --- | --- | --- |
| 权重导入 | 结构已知的小型线性网络 | 参数键名、权重方向、预处理、逐层误差 |
| ONNX 导入 | 只使用已支持算子的简单网络 | 算子支持、生成代码、动态维度与输出一致性 |
| 后端扩展的下一步 | 在已验证的 `y=x²+x` 上增加随机输入、更多布局和有限差分 | 对照组合参考的前向与梯度 |
| Fusion 接入 | 同一个公式，先明确采用哪一种方法注解 | 元数据与真实结果一致，普通返回字段可提前确定 |
| 专用 kernel | 与组合算子相同的公式 | 边界、布局、dtype、误差、耗时 |
| 浏览器部署 | 先选足够小的模型 | 目标编译、资源加载、异步接口、可用设备 |

这些是实验计划，首版没有提供已经验证完成的导入产物或 GPU 内核。自定义算子应先有可信的组合参考实现，再写底层优化。

## 读源码时留下什么记录 {#读源码时留下什么记录}

每次只追一个问题，例如“Linear 的偏置在哪里加”。记录入口函数、下一层调用、张量形状、涉及的设备与上下文，最后用两三句话解释职责。不要只抄一长串文件名。

建议采用以下笔记格式：

```text
问题：
版本 / 提交：
最小算例与预期：
源码入口与调用路径：
我现在能解释的行为：
仍未验证的假设：
实际运行结果与环境：
```

## 后续内容的补充顺序 {#后续内容的补充顺序}

训练与保存加载已由 G/H 完成；下一步补梯度检查（有限差分），再补 CPU/GPU 对照和融合测量；随后完成一个小模型导入与一个自定义 kernel；最后扩展到 Transformer 推理、量化、内存规划和服务调度。

这些扩展会沿用本书的方法：先定义数学和输入输出，再检查实现与误差，最后讨论性能。遇到不懂的源码名词，回到它为哪一个具体计算问题服务，就更容易找到阅读方向。

返回[学习总览](./index.md)，或按[源码阅读地图](./source-reading.md)开始第一次源码追踪。参考版本统一记录在[资料页](./references.md)。

需要复习同一组公式、形状、参数和梯度时，返回[第 16 章：PyTorch 对照](./pytorch-comparison.md)；继续研究时按本章后续实验逐项验证。
