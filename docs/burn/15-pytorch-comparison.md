# 第 15 章：用 PyTorch 对照学习 Burn

[学习总览](./index.md) · [上一章：实验路线](./14-learning-labs.md)

到这里，我们已经从手算走到了后端、梯度和扩展。现在用同一组输入、同一个公式，把这些认识放到 PyTorch 和 Burn 中逐项对照。目的在于借助 PyTorch 丰富的资料理解共同原理，并看清哪些写法不能直接照搬。

读过第 3、4、6、7  章，就可以先完成本章的前向、模型和梯度部分；后端、融合和扩展对照可以等第 5、8、10、12  章之后再读。

::: info 版本与验证
Burn 固定 **0.22.1**。本章完整例子在 Windows、Python **3.13.5**、PyTorch **2.12.1+cpu**、Rust/Cargo **1.98.1** 上验证。PyTorch 在线 `stable` 在本次核对时指向 2.14，因此正文的重要语义链接尽量固定到与实验对应的 2.12 文档。后文的 GPU、编译和扩展对照是机制说明，没有进行速度比较或 GPU 实验。
:::

## 15.1 先对齐问题，再对齐代码

两套框架都处理张量、组织模型、计算梯度，并把数值工作交给具体实现。语言和接口不同，数学目标可以完全相同。

```text
输入 X = [[1,2]]                  shape [1,2]
权重 W = [[1,-1],[2,1]]           shape [2,2]
偏置 b = [[0,1]]                 shape [1,2]
H = ReLU(XW+b) = [[5,2]]         shape [1,2]
```

比较前明确输入、权重方向、bias 广播、dtype 和设备。否则两个程序可能都成功运行，却计算了不同的函数。

Python 代码简短，不表示矩乘是在 Python 的逐元素循环中完成；张量运算会进入框架的底层实现。Rust 程序先编译成可执行文件，也不表示每个张量的全部尺寸、设备工作和模型计算图都在 Rust 编译时固定。

## 15.2 同一次前向，用两种语言表达

下面两个片段都可独立表达主线前向。完整版本和断言见本章最后的学习包。

**PyTorch：**

```python
import torch

x = torch.tensor([[1.0, 2.0]], dtype=torch.float32, device="cpu")
w = torch.tensor([[1.0, -1.0], [2.0, 1.0]], dtype=torch.float32)
b = torch.tensor([[0.0, 1.0]], dtype=torch.float32)
h = torch.relu(x @ w + b)
print(h.tolist())  # [[5.0, 2.0]]
```

**Burn：**

```rust
use burn::tensor::{Device, Tensor, activation::relu};

fn main() {
    let device = Device::flex();
    let x = Tensor::<2>::from_floats([[1.0, 2.0]], &device);
    let w = Tensor::<2>::from_floats([[1.0, -1.0], [2.0, 1.0]], &device);
    let b = Tensor::<2>::from_floats([[0.0, 1.0]], &device);
    let h = relu(x.matmul(w) + b);
    assert_eq!(h.dims(), [1, 2]);
    println!("{:?}", h.into_data().try_to_vec::<f32>().unwrap());
}
```

PyTorch 的 `@` 与这里的 `matmul` 都表示矩乘，`*` 表示逐元素乘法。Burn 的结果在这里被展平为 `[5,2]`，所以要连同 `[1,2]` 的形状一起比较；打印形式不同不表示计算结果不同。

## 15.3 类型、形状、设备：各自在哪儿检查

| 问题 | PyTorch 的常见入口 | 本书的 Burn 入口 | 学习时的重点 |
| --- | --- | --- | --- |
| 有几条轴 | `x.ndim` | `Tensor<D>` 的 D、`x.dims().len()` | Burn 把阶数写进类型，具体轴长度仍在运行时 |
| 每条轴多长 | `x.shape` | `x.dims()` | 两个二阶张量不一定能矩乘 |
| 实际元素精度 | `x.dtype` | `x.dtype()` | “浮点类别”与具体 F32/F16 分开 |
| 放在什么资源上 | `x.device`、创建参数 `device=` | `Device`、`x.device()` | 类型名字本身不能证明使用某块 GPU |
| 变换维度 | `reshape`、`transpose` | `reshape`、转置相关接口 | 先判断元素排列和布局，再判断是否需要拷贝 |
| 搬运数据 | 张量 `.to(...)` | 张量 `.to_device(...)` | 输入与参数要相容；改变量名不等于搬运 |

Python 的一个变量可以先指向二阶张量，再指向三阶张量。Rust 的 `Tensor<2>` 与 `Tensor<3>` 是不同类型。Burn 能提前排除一部分阶数错误，形状 `[2,3] × [4,2]` 这样的尺寸错误仍需要算子检查。[PyTorch 张量属性](https://docs.pytorch.org/docs/2.12/tensor_attributes.html)、[Burn 张量定义](https://github.com/tracel-ai/burn/blob/v0.22.1/crates/burn-tensor/src/tensor/api/base.rs)。

## 15.4 最容易忽略的差别：Linear 权重要转置

先区分**我们在公式里命名的 W**和**框架保存在 Linear 内的 weight**：

| 实现 | 保存的 weight 形状 | 前向公式 |
| --- | --- | --- |
| Burn Linear | `[in_features,out_features]` | `XW+b` |
| PyTorch `nn.Linear` | `[out_features,in_features]` | `XAᵀ+b` |

要表示相同函数，必须令 `A=Wᵀ`。主线矩阵恰好是方阵，形状检查抓不住方向错误；数值仍然会变。若把 W 原样写进 PyTorch Linear，会得到 `XWᵀ+b=[[-1,5]]`，ReLU 后为 `[[0,5]]`。

因此完整 Python 例子这样写入参数：

```python
linear = torch.nn.Linear(2, 2)
with torch.no_grad():
    linear.weight.copy_(w.detach().T)
    linear.bias.copy_(b.detach().reshape(2))
linear.eval()
with torch.no_grad():
    h_from_layer = torch.relu(linear(x.detach()))
```

`copy_` 表示写入已有参数；这里放在 `no_grad` 中，是初始化教学权重，不是在记录一次可微更新。不要为了调整参数值直接破坏模型的参数注册关系。[PyTorch Linear 公式和权重约定](https://docs.pytorch.org/docs/2.12/generated/torch.nn.Linear.html)、[Burn Linear 源码](https://github.com/tracel-ai/burn/blob/v0.22.1/crates/burn-nn/src/modules/linear.rs)。

可以再做一个未附独立程序的练习：把 Burn 的 W 改成 `[[1,-1,0],[2,1,3]]`、bias 改为 `[0,1,-1]`。预期输出 `[5,2,5]`，Burn weight 是 `[2,3]`，对应 PyTorch Linear weight 则是 `[3,2]`。这次方向错误连形状都对不上。

## 15.5 模型定义：共同职责与不同组织方式

PyTorch 常继承 `torch.nn.Module`，在初始化方法中登记层和参数，再写 `forward`。Burn 常用 Rust 结构体保存层，用 `#[derive(Module)]` 生成状态管理实现，再自己写 `forward`。

两者都要回答：“模型有哪些状态？输入怎样经过这些部件？”Module 管理状态，不会凭层的声明自动推断你想要的任意前向顺序。

PyTorch 通常通过 `model(x)` 调用模型，框架还会处理 hooks 等约定；本书 Burn 例子直接调用自行定义的 `model.forward(x)`。不要因为都叫 Module，就假定调用机制和继承规则相同。[PyTorch Module](https://docs.pytorch.org/docs/2.12/generated/torch.nn.Module.html)、[Burn Module](https://github.com/tracel-ai/burn/blob/v0.22.1/burn-book/src/building-blocks/module.md)。

## 15.6 梯度：先统一损失，才有可比结果

求“张量的梯度”之前，要先说清楚哪个目标相对哪个变量求导。对主线取 `L=sum(H)`，ReLU 前的两个元素都大于零，手算得到：

```text
dL/dH = [[1,1]]
dL/dX = [[0,3]]
dL/dW = [[1,1],[2,2]]
dL/db = [[1,1]]
```

本章两个完整程序都验证了这些值。这里的 b 使用 `[1,2]` 便于对齐公共 Tensor；模型层中保存 `[2]` 的共享 bias 时，梯度形状应与该参数一致。

再对照第 12 章的 `y=x²+x`：

```python
x = torch.tensor([-2.0, 0.0, 3.0], requires_grad=True)
g = torch.tensor([2.0, -1.0, 0.5])
((x * x + x) * g).sum().backward()
print(x.grad.tolist())  # [-6.0, -1.0, 3.5]
```

Burn 的相同计算需要先用 `Device::flex().autodiff()` 创建设备上下文，再在源输入上 `.require_grad()`。主要取值方式不同：

```rust
let gradients = loss.backward();
let dx = x.grad(&gradients).unwrap();
```

PyTorch 的 `backward()` 通常把梯度累加到叶子的 `.grad`；训练时要安排清空或置为 `None`。Burn 返回本次反向的梯度容器，由调用者取值或交给参数梯度映射。不要把 PyTorch 的 `.grad` 字段积累规则原样套进 Burn。[PyTorch backward](https://docs.pytorch.org/docs/2.12/generated/torch.Tensor.backward.html)、[Burn 自动微分接口](https://github.com/tracel-ai/burn/blob/v0.22.1/crates/burn-tensor/src/tensor/api/autodiff.rs)。

两边都要注意反向中间状态的生命周期。PyTorch 提供 `retain_graph` 等选项；本书固定的 Burn 接口没有同名保图能力。同一已消耗的中间图不能靠 clone 再求一次，最容易解释的做法是合并损失，或分别重新执行前向。

## 15.7 一次更新：backward 不会自己训练模型

把问题缩成一个权重 w：输入为 2，目标为 4，预测 `p=2w`，损失 `L=(p-4)²`。从 `w=0` 开始：

```text
p = 0，L = 16
dL/dw = 2(2w-4)×2 = -16
学习率 η = 0.1
w_new = w - η×dL/dw = 1.6
新预测 = 3.2，新损失 = 0.64
```

两个完整程序都做了这一次**手动 SGD 数学更新**。这说明求导结果怎样用于更新；没有使用框架优化器 API，也不是完整数据集上的训练收敛实验。

真实训练循环还要管理 mini-batch、参数标识、优化器状态和验证集。PyTorch 常见 `zero_grad → forward → loss → backward → step`；Burn 在反向后还需把张量梯度映射成参数梯度，再由优化器更新模型。过程与状态见[第 7 章](./07-training-to-inference.md)。

## 15.8 推理模式：相似目标不等于同名 API

PyTorch 通常同时处理两件事：

```python
model.eval()                  # 切换有训练/评估差异的层
with torch.no_grad():         # 该代码块不记录反向计算
    output = model(inputs)
```

`eval()` 本身不关闭求导；`no_grad()` 本身不切换 Dropout、BatchNorm 的层行为。`inference_mode()` 还有额外约束，初学时先理解这两种职责即可。[PyTorch 自动微分模式说明](https://docs.pytorch.org/docs/2.12/notes/autograd.html)。

Burn 0.22.1 的 `model.valid()` 返回用于验证/推理的同类型副本，移除模型张量的自动微分关联并关闭模块训练标志；要使用返回的模型。它不能机械翻译成一个全局 `no_grad` 代码块。若输入也携带自动微分关系，还应明确本次前向是否要追踪输入梯度。[Burn 模块转换实现](https://github.com/tracel-ai/burn/blob/v0.22.1/crates/burn-core/src/module/base.rs)。

## 15.9 clone、detach 与赋值，名字相似但语义不同

| 操作 | 应怎样理解 |
| --- | --- |
| Python `other = x` | 给同一个 Python 对象增加一个引用入口 |
| PyTorch `x.clone()` | 复制张量数据，并可继续保留与 x 的自动微分关系 |
| PyTorch `x.detach()` | 切断求导关系，仍共享原数据存储；不等于独立副本 |
| Rust `let other = x` | 对不隐式复制的张量句柄转移所有权，旧变量不能继续使用 |
| Burn `x.clone()` | 克隆张量句柄；不能据此推断整块数据深复制，也不能复制一份独立反向历史 |
| Burn `x.detach()` | 切断此前求导关系；具体存储行为仍需看实现 |

因此，把 Python 的每个变量赋值都翻译成 Burn clone，或者认为两边 clone 的内存成本相同，都会产生误解。先问“对象身份、数值存储、求导关系”这三个问题。[PyTorch clone](https://docs.pytorch.org/docs/2.12/generated/torch.clone.html)、[PyTorch detach](https://docs.pytorch.org/docs/2.12/generated/torch.Tensor.detach.html)。

## 15.10 后端、计算图和编译：按职责比较

这一节是进阶对照，第一遍读到“共同解决什么问题”即可。

| 共同问题 | PyTorch 中可查的主题 | Burn 中对应的学习位置 |
| --- | --- | --- |
| 同一操作使用不同设备实现 | dispatcher、设备实现与后端扩展 | Bridge、Dispatch、Backend，第 5 章 |
| 为反向保存关系与中间状态 | autograd、saved tensors | Autodiff、检查点策略，第 6 章 |
| 提取并优化部分计算 | `torch.compile` 及其编译后端 | Fusion、CubeCL 内核与运行时，第 8～10 章 |
| 新操作与独立设备实现 | 自定义算子注册、autograd 规则 | backend_extension、具体 impl、反向接入，第 12 章 |
| 保存与跨框架复用 | `state_dict`、导出与格式转换 | Module 状态、burnpack、ONNX 导入，第 11 章 |

这张表对应的是职责，不是一一等价的类名。尤其不要把 `torch.compile` 与 `Fusion<B>` 当成同一个组件：前者涉及捕获和编译函数/模块的执行，后者是 Burn 后端体系中的延迟记录与优化层。它们支持的操作、边界和回退行为要分别查证。[torch.compile](https://docs.pytorch.org/docs/2.12/generated/torch.compile.html)、[Burn Fusion](https://github.com/tracel-ai/burn/tree/v0.22.1/crates/burn-fusion)。

“计算图”也要带上用途：求导关系图、编译捕获的图、延迟融合记录、可重放的设备启动序列，记录的对象不同。Rust 的静态类型检查、PyTorch 的动态图和 GPU 的异步执行，还分属不同维度。

自定义操作方面，能够把一个函数放进模型、能够执行专用内核、能够训练、能够被编译或融合，分别需要相应支持。不要因为 PyTorch 中某个注册工具支持某条路径，就假定 Burn 的宏具有相同能力，反过来也一样。[PyTorch 扩展指南](https://docs.pytorch.org/docs/2.12/notes/extending.html)。

## 15.11 从 PyTorch 资料迁移知识的步骤

拿到一篇教程，先抄下公式、输入输出 shape、dtype、状态和预期值，再寻找 Burn 中承担同一职责的接口。首先比较前向，再比较梯度和状态，最后才研究设备与性能。

| 如果你要学 | 先看 PyTorch 官方资料 | 再回到 Burn |
| --- | --- | --- |
| 张量、广播与布局 | [Tensor 基础](https://docs.pytorch.org/tutorials/beginner/basics/tensorqs_tutorial.html) | 第 1、3 章 |
| 模型和参数 | [Build the Neural Network](https://docs.pytorch.org/tutorials/beginner/basics/buildmodel_tutorial.html) | 第 4 章 |
| 梯度与链式法则 | [Automatic Differentiation](https://docs.pytorch.org/tutorials/beginner/basics/autogradqs_tutorial.html) | 第 6 章 |
| 训练循环 | [Optimizing Model Parameters](https://docs.pytorch.org/tutorials/beginner/basics/optimization_tutorial.html) | 第 7 章 |
| 保存状态 | [Serialization semantics](https://docs.pytorch.org/docs/2.12/notes/serialization.html) | 第 11 章 |

首次阅读不需要搜索“哪个框架更快”。先能把同一函数的形状、数值、梯度和状态讲清，后续性能比较才有共同基础。

## 本章实验：运行完整对照实验

下载[更新后的 CPU 学习包](/burn/first-inference.zip)，在项目目录分别运行：

```sh
cargo run --locked --bin comparison
python pytorch_compare.py
```

Rust 项目依赖已经锁定。Python 程序需要可导入 PyTorch 的环境；它不随 Cargo 安装。先执行 `python -c "import torch; print(torch.__version__)"` 检查当前解释器，没有安装时按 [PyTorch 官方安装选择器](https://pytorch.org/get-started/locally/)配置对应平台的 CPU 环境。

本次核对的结果如下；Rust 输出将张量展平，Python 保留列表层次。单步更新以 `1e-5` 的容差检查，最后几位浮点打印可能不同。

| 检查项 | 两边的数学结果 |
| --- | --- |
| 主线前向 | `H=[[5,2]]`，shape `[1,2]` |
| 主线梯度 | `dX=[[0,3]]`，`dW=[[1,1],[2,2]]`，`db=[[1,1]]` |
| 非全 1 上游梯度 | `[-6,-1,3.5]` |
| 手动 SGD 单步 | `w=1.6`，新损失约 `0.64` |
| PyTorch Linear 参数转换 | 转置 W 后得到相同主线输出 |

也可分别下载<a href="/burn/first-inference/src/bin/comparison.rs" download>Burn 完整程序</a>和<a href="/burn/first-inference/pytorch_compare.py" download>PyTorch 完整程序</a>。它们各自对照同一组手算值，未实现两个运行时之间直接传输张量；本次通过不代表任意模型已经完成跨框架迁移。

## 自测与答案

1. 两个 Linear 的权重 shape 都是 `[2,2]`，能直接拷贝吗？**不能据此判断。要核对公式和轴含义，本例需转置。**
2. PyTorch `eval()` 等于关闭求导吗？**不等于。层行为与梯度记录要分别处理。**
3. Burn `Tensor<2>` 是否比 Python 提前知道所有矩阵尺寸？**没有，它只提前约束阶数。**
4. 两边的 `clone()` 能按同样内存成本理解吗？**不能。对象引用、句柄、数据副本和求导关系要分别看。**
5. 单步损失下降证明模型已学会任务吗？**不能。它只验证这一步公式与实现；完整训练还需数据和独立评估。**

回到[学习总览](./index.md)，按当前卡住的问题选择章节；需要继续做实验时，使用[第 14 章](./14-learning-labs.md)的验证路线。
