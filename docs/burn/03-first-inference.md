# 第 3 章：把第一次推理跑起来

[学习总览](./index.md) · [上一章：Rust 基础](./02-rust-for-burn.md) · [下一章：模型与 Module](./04-models-and-modules.md)

[返回目录](./index.md) · [上一章：Rust 阅读准备](./02-rust-for-burn.md) · [下一章：模型与 Module](./04-models-and-modules.md)

这一章只做一件事：让 CPU 算出前两章已经手算过的 `H = [[5, 2]]`。先把结果做对，后面才能判断更复杂的模型和加速路径是否正确。

完整学习包固定 Burn **0.22.1**，使用 **Flex CPU 后端**，不需要配置 GPU。程序中的断言会检查形状和数值，实际验证记录见[第 13 章](./13-learning-labs.md)。

前置知识是第 1 章的二维形状与广播，以及第 2 章的 `use`、函数和按值传参。读完后，你应能把“创建数据 → 调用算子 → 取回数据 → 与手算核对”走通，并说清编译成功、程序跑完和结果正确各验证了什么。

## 先准备什么

需要安装 Rust 与 Cargo。本次用 1.98.1 验证；Burn 0.22.1 本体声明的最低 Rust 版本为 1.95，较旧工具链未在本次验证。打开终端确认：

```sh
rustc --version
cargo --version
```

第一次构建需要联网获取依赖，耗时也会比后续运行长。不要把依赖下载和 Rust 编译的时间当作模型推理耗时。

你可以下载[完整学习包](/burn/first-inference.zip)，解压后进入包含 `Cargo.toml` 的目录。包内还有第 4、6、11、14 章的例子和锁文件。

```sh
cargo run --locked --bin burn-first-inference
```

预期看到：

```text
H = [5.0, 2.0]
```

输出被展平成一维列表，程序已经用 `assert_eq!(h.dims(), [1, 2])` 检查原张量有一行两列。

## 如果你想自己新建项目

```sh
cargo new burn-first-inference
cd burn-first-inference
```

将 `Cargo.toml` 改为：

```toml
[package]
name = "burn-first-inference"
version = "0.1.0"
edition = "2024"

[dependencies]
burn = { version = "=0.22.1", default-features = false, features = ["std", "flex", "autodiff", "extension"] }
```

`std` 表示使用标准库，`flex` 启用这次要用的 CPU 实现。`autodiff` 是为了后面的求导例子，`extension` 用于第 11 章的后端扩展。本章不启用设备的自动微分上下文，所以不会因为编译了该能力就自动求梯度。

接着把下面完整程序写到 `src/main.rs`。这是学习包主程序的同一计算：

```rust
use burn::tensor::{Device, Tensor, activation::relu};

fn main() {
    let device = Device::flex();
    let x = Tensor::<2>::from_floats([[1.0, 2.0]], &device);
    let w = Tensor::<2>::from_floats([[1.0, -1.0], [2.0, 1.0]], &device);
    let b = Tensor::<2>::from_floats([[0.0, 1.0]], &device);

    let h = relu(x.matmul(w) + b);
    assert_eq!(h.dims(), [1, 2]);
    let values = h.into_data().try_to_vec::<f32>().unwrap();
    assert_eq!(values, vec![5.0, 2.0]);
    println!("H = {values:?}");
}
```

自己新建项目时，第一次用 `cargo run` 生成 `Cargo.lock`；以后可用 `cargo run --locked` 保持依赖解析一致。完整学习包已经提供锁文件。

## 逐行看发生了什么

`Device::flex()` 明确选择资源。不要用“CPU 张量都差不多”来猜 API：`Device::cpu()` 对应另一条 CubeCL CPU 路径，本章无需它。

`from_floats` 将 Rust 数组作为张量数据。这里 `x` 的阶数为 2，形状为 `[1, 2]`；`w` 为 `[2, 2]`。`Tensor::<2>` 中的 2 不是“里面有两个数”，也不是“第二块 GPU”。

本章把偏置写为 `[1, 2]`，与矩乘结果阶数一致。模型层通常保存 `[2]` 的偏置，再在内部匹配批次等轴；第 4 章会看到这种写法。

`x.matmul(w)` 计算矩阵乘法，`+ b` 添加偏置，`relu(...)` 逐元素应用激活函数。这行表达数学顺序，没有要求每个后端必须采用同一套底层指令。

`into_data()` 取出可供主机读取的数据，`try_to_vec::<f32>()` 转成 Rust 数组容器。若换成 GPU，这类取数可能涉及等待和数据搬运。因此不要在性能实验的内循环里不断打印完整张量。

`unwrap()` 是教学程序里简化错误处理的写法：失败时直接报错。真正的应用通常要把读取、加载和设备错误传给上层处理。

## 给每一步标上形状与结果

遇到一整行表达式难以理解时，先在纸上拆开：

| 步骤 | 输入形状 | 输出形状 | 这个例子的数值 |
| --- | --- | --- | --- |
| 构造 x、w、b | Rust 数组 | `[1, 2]`、`[2, 2]`、`[1, 2]` | 与第 0 章一致 |
| `x.matmul(w)` | `[1, 2] × [2, 2]` | `[1, 2]` | `[[5, 1]]` |
| 加 b | `[1, 2] + [1, 2]` | `[1, 2]` | `[[5, 2]]` |
| ReLU | `[1, 2]` | `[1, 2]` | `[[5, 2]]` |
| 读为 Vec | `[1, 2]` 的张量数据 | Rust 容器 | `[5.0, 2.0]` |

最后一步的列表丢失了“行和列”的显示方式，所以程序同时检查 `dims()` 和数值。只检查 `[5, 2]` 的列表，不能区分 `[2]`、`[1, 2]` 和 `[2, 1]` 这些不同形状。

如果把每个中间张量都读回主机，可以帮助最初排查数值错误；理解以后应减少这种调试读回。它们是额外的数据观察操作，不是模型公式的一部分。

## 用 PyTorch 表达完全相同的计算

如果你习惯先看 Python，可以用下面的**对照阅读片段**核对数学。这里没有 `nn.Linear`，w 直接采用本书 `XW+b` 的方向，因此两端无需转置参数：

```python
import torch

device = torch.device("cpu")
x = torch.tensor([[1.0, 2.0]], dtype=torch.float32, device=device)
w = torch.tensor([[1.0, -1.0], [2.0, 1.0]], dtype=torch.float32, device=device)
b = torch.tensor([[0.0, 1.0]], dtype=torch.float32, device=device)

h = torch.relu(x @ w + b)
assert list(h.shape) == [1, 2]
assert h.tolist() == [[5.0, 2.0]]
```

共同主线是构造张量、矩乘、相加、ReLU，再核对形状与数据。PyTorch 使用 `@` 表达矩乘，Burn 用 `matmul`；Python 片段没有遇到 Rust 的移动规则。这些写法差异没有改变公式。[PyTorch 官方张量教程](https://docs.pytorch.org/tutorials/beginner/basics/tensorqs_tutorial.html)

本节片段已在 PyTorch 2.12.1+cpu 上独立核对形状与输出；第 14 章及学习包还提供了完整的[对照实验](./14-pytorch-comparison.md)。下一章换成两端各自的 Linear 层时，需要专门处理权重方向，不能把这里的 w 原样复制到 `nn.Linear.weight`。

## 做两个能解释现象的小改动

先把偏置改成 `[[0.0, -3.0]]`。手算 `XW = [[5, 1]]`，所以 `Z = [[5, -2]]`、`H = [[5, 0]]`。同时修改预期断言后再运行，观察 ReLU 怎样改变输出。

先把偏置恢复为 `[[0.0, 1.0]]`，再把输入改成两行 `[[1.0, 2.0], [0.0, 1.0]]`。输出应为 `[[5, 2], [2, 2]]`，形状变为 `[2, 2]`，展平列表为 `[5, 2, 2, 2]`。这次同一行偏置广播到两个样本。

这两个是读者练习；下载包默认保留初始算例。每次先写预期、再改代码，避免只看到“能运行”就认为理解了。

## 遇到问题先查哪里

| 现象 | 先检查 |
| --- | --- |
| 找不到 `Device::flex` | `flex` feature 是否启用，版本是否为 0.22.1 |
| Rust 版本要求不满足 | `rustc --version` 与当前使用的工具链 |
| 多个二进制无法选默认入口 | 使用学习包提供的 `--bin burn-first-inference` |
| 矩阵乘法报形状错误 | 左矩阵最后一轴是否等于右矩阵倒数第二轴 |
| 断言失败 | 是否改了输入，却还在使用旧的预期输出 |

本章学习的是固定参数的一次前向，不需要数据集、优化器或训练界面。随机初始化模型能够执行，也不代表它已经具备预测能力。

## 自测

1. `autodiff` feature 已启用，为什么这个程序仍是推理？**编译能力不等于启用上下文，程序也没有记录所需梯度或执行反向。**
2. 两行输入是否需要复制两份权重？**不需要。** 同一组权重可以处理一个批次中的各行。
3. 为什么先固定这些小数字？**因为能独立手算，排除随机参数给正确性检查带来的困难。**
4. Rust 程序成功编译，是否就能证明公式写对了？**不能。** 编译检查语言规则和一部分类型约束，形状断言与数值断言继续检查实际计算；真实任务还需要验证预处理和业务含义。

API 依据：[Getting started](https://github.com/tracel-ai/burn/blob/v0.22.1/burn-book/src/getting-started.md)、[后端与设备](https://github.com/tracel-ai/burn/blob/v0.22.1/burn-book/src/building-blocks/backend.md)。继续阅读[第 4 章：模型、参数与 Module](./04-models-and-modules.md)。
