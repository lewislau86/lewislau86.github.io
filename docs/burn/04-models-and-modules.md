# 第 4 章：模型、参数与 Module

[学习总览](./index.md) · [上一章：第一次推理](./03-first-inference.md) · [下一章：Backend 与执行路径](./05-backends-and-dispatch.md)

[返回目录](./index.md) · [上一章：第一次推理](./03-first-inference.md) · [下一章：Backend 与执行路径](./05-backends-and-dispatch.md)

上章把权重和运算直接写在 `main` 里。层数增加后，我们需要把相关参数放在一起，还要统一移动设备、保存权重和切换训练状态。Burn 的 `Module` 为这些工作提供共同接口。

Rust 的 module 组织代码命名空间，深度学习的 Module 组织模型状态与计算部件。同一个英文词在两个层次使用：`use burn::module::Module` 的小写 `module` 是代码路径，大写 `Module` 是我们要使用的模型管理 trait。

本章是首版导读，配套 CPU 例子见[第 13 章](./13-learning-labs.md)。所有代码使用[固定版本](./references.md)，模型的公开类型不再需要后端泛型。

前置知识是第 3 章那条固定参数的计算，以及第 2 章的 `struct`、`impl`、`&self`。本章读完应能把“模型结构”“参数值”“模块管理”和“前向方法”分别指出来。自动微分的具体计算留到第 6 章；这里先理解状态如何被组织。

## 公式没有变，只是把责任组织起来

```text
TinyModel
└─ Linear
   ├─ weight: [2, 2]
   └─ bias:   [2]

forward(x): Linear(x) → ReLU → 输出
```

线性层实现 `XW + b`。我们的模型再对结果执行 ReLU。数学过程仍是 `[[1, 2]] → [[5, 2]]`，代码组织改变并不会自动改变权重或学习出规律。

特别注意 Burn 线性层的权重约定为 `[输入特征数, 输出特征数]`，公式是 `XW + b`。不要把其他库的权重存储方向直接套过来。参考[固定版本 Linear 源码](https://github.com/tracel-ai/burn/blob/v0.22.1/crates/burn-nn/src/modules/linear.rs)。

### 为什么“放进 struct”还需要 Module

单纯把两个张量放在一个结构体里，已经能够写出一次前向。但是模型越大，越需要统一回答：哪些字段是参数，子模块里还有哪些参数，它们应怎样移动设备、形成记录或调整运行状态。如果每个模型都自己遍历全部字段，这些管理代码很容易遗漏。

`Module` 为这些管理工作提供共同规则。模型可以包含子模块，子模块继续包含参数，形成一棵结构树；框架可以沿树访问相关状态。**结构树与前向依赖图不是同一件事**：同一个层可以在一次前向里调用多次，也可能有条件分支。先有参数组织，再由 `forward` 决定这一轮实际执行哪些操作。

## 先读模型的骨架

下面是阅读片段，完整初始化与断言在下载包的 `src/bin/module.rs`：

```rust
use burn::{
    module::Module,
    nn::{Linear, LinearConfig},
    tensor::{Device, Tensor, activation::relu},
};

#[derive(Module, Debug)]
struct TinyModel {
    linear: Linear,
}

impl TinyModel {
    fn new(device: &Device) -> Self {
        Self { linear: LinearConfig::new(2, 2).init(device) }
    }

    fn forward(&self, x: Tensor<2>) -> Tensor<2> {
        relu(self.linear.forward(x))
    }
}
```

`LinearConfig::new(2, 2)` 说明输入和输出特征数。`init(device)` 创建参数；默认初始化不是本书手算的那组值，所以只运行这段初始化，不能期待一定输出 `[5, 2]`。

`#[derive(Module, Debug)]` 为模型生成模块管理与调试显示相关实现。它不会替我们决定网络的计算顺序。`forward` 是这里自己写的普通方法；其参数、返回值和内部流程由模型作者定义。

顺着代码读一遍：`TinyModel` 保存一个 Linear；`new` 根据配置初始化它；`forward` 借用模型，通过 `self.linear.forward(x)` 读取该层的参数并计算，再将结果交给 ReLU。`&self` 让同一个模型可以继续用于下一批输入，而按值传入的 x 由这一轮计算使用。

## Config、Module、Param 各保存什么

| 对象 | 例子 | 作用 |
| --- | --- | --- |
| 配置 Config | 输入 2 个特征、输出 2 个特征、是否加偏置 | 描述怎样创建模型 |
| 模型 Module | 一层 Linear，加上手写的 forward | 组织状态与计算部件 |
| 参数 Param | 权重矩阵和偏置向量 | 为状态提供标识，支持遍历、优化与记录 |
| 输入 Tensor | `[[1, 2]]` | 本次前向的数据 |

输入通常随请求变化，参数通常在多次请求中复用。训练会更新参数，普通推理则读取已确定的参数。

`Param<Tensor<2>>` 给权重增加参数身份。它不只是一层漂亮的包装：优化器要把梯度与参数对应，存储要识别模型状态。一个普通 `Tensor` 字段不能被想当然地当作同样参与保存的模型参数。

参数身份也不表示“每个参数都必须训练”。冻结权重、运行统计等状态有各自行为；保存与优化是相关但不同的工作。详见[Module 文档](https://github.com/tracel-ai/burn/blob/v0.22.1/burn-book/src/building-blocks/module.md)。

这里的参数数量数的是**标量元素**，不是字段个数。一个权重字段装了四个数，偏置字段装了两个数，所以共有六个参数。把 batch 从 1 改成 100，会增加这一轮输入与中间结果的数据量，不会把这层的参数量从 6 变成 600。

## 固定权重后与手算比较

学习包中先创建 Linear，再使用 `Param::from_tensor(...)` 写入固定权重与偏置。这个覆盖过程是为了教学验证，实际模型通常从训练或权重文件取得值。

```text
weight = [[1, -1], [2, 1]]   共 4 个参数
bias   = [0, 1]              共 2 个参数
参数总数 = 6
```

解压[学习包](/burn/first-inference.zip)后，在项目目录运行：

```sh
cargo run --locked --bin module
```

预期输出：

```text
Module H = [5.0, 2.0]; parameters = 6
```

这里同时检查输出和参数量，建立“手算公式、参数结构、实际执行”之间的对应关系。这个网络没有 Dropout，但仍显式使用 `model.valid()`，为后续加入有训练状态的层保留清晰约定。

## 同样的类型不代表同样的运行状态

在 0.22.1，`model.valid()` 返回用于验证/推理的同类型副本，关闭参数的自动微分及模块训练标志。`model.train()` 则恢复相应训练配置。类型名没变，内部上下文和状态可以变。

要使用转换方法的返回值，例如 `let inference_model = model.valid()`。训练流程可保留原训练模型，验证时使用推理副本；也不要把一次 `train()` 转换理解为自动恢复此前刻意冻结的参数选择。具体状态约定在第 7 章说明。

不要用“没有调用 backward”代替完整的推理模式切换。Dropout 和 BatchNorm 这样的层除了求梯度，还有训练时与验证时的行为差异。第 7 章将单独把这些状态连起来。

先知道两种背景即可：Dropout 在训练时随机屏蔽部分激活，普通推理时不再按训练方式随机屏蔽；BatchNorm 在常见配置下，训练时使用当前批次统计并更新运行统计，评估时使用保存的统计。它们说明模型可能保存“权重以外的状态”，也说明相同输入和参数并不足以概括所有层的运行条件。可以先读 PyTorch 的 [Dropout](https://docs.pytorch.org/docs/stable/generated/torch.nn.Dropout.html) 与 [BatchNorm](https://docs.pytorch.org/docs/stable/generated/torch.nn.BatchNorm1d.html) 说明建立背景，Burn 的模式衔接在第 7 章展开。

本章例子没有这两层，因此 `valid()` 不改变手算得到的 `[5, 2]`。等加入有状态层时，才会观察到模式切换对行为的实际作用；不要为看不到数值变化而把这个约定删掉。

## 模型边界要写清楚

`forward(&self, x: Tensor<2>) -> Tensor<2>` 只表达输入输出有两条轴，不保证第二条轴一定长为 2。模型作者仍应说明形状契约，并检查特征轴。Burn 的 Linear 会对输入特征维做相应检查。

先写出 `[batch, input_features] → [batch, output_features]`，再写代码，往往比碰到矩乘错误后从底层倒推更容易理解。`batch` 表示一次一起处理的样本数，不是层数。

## 与 PyTorch 对照：层相似，权重方向不同

PyTorch 的 `nn.Module` 同样用于组织子模块和参数，模型作者定义 `forward`。通常用 `model(x)` 调用 PyTorch 模块，以经过其调用机制和 hooks；本书 Burn 示例则显式调用 `model.forward(x)`。不要仅根据两个方法都叫 forward，就假定模块调用机制相同。[PyTorch Module](https://docs.pytorch.org/docs/stable/generated/torch.nn.Module.html)

最需要核对的是 Linear。令输入特征数为 2、输出特征数为 3，两个库的参数形状已经不同：

| 项目 | Burn 0.22.1 Linear | PyTorch `nn.Linear` |
| --- | --- | --- |
| 配置含义 | `LinearConfig::new(2, 3)` | `nn.Linear(2, 3)` |
| 权重形状 | `[2, 3]` | `[3, 2]` |
| 前向公式 | `XW + b` | `XAᵀ + b` |
| 偏置形状 | `[3]` | `[3]` |
| 相同数学参数的对应 | 本书 W | `A = Wᵀ` |

PyTorch 的方向约定见[官方 Linear 文档](https://docs.pytorch.org/docs/stable/generated/torch.nn.Linear.html)。回到本书的 2→2 例子，两边的权重形状恰好都是 `[2, 2]`，但元素仍要转置；只检查形状发现不了这类错误。

下面的 PyTorch 片段与 Burn 固定权重对应，已在 PyTorch 2.12.1+cpu 上独立核对输出；第 14 章也把同样的权重转换放进了完整对照程序：

```python
import torch
from torch import nn

layer = nn.Linear(2, 2)
with torch.no_grad():
    # Burn W = [[1, -1], [2, 1]]，此处保存 W 的转置。
    layer.weight.copy_(torch.tensor([[1.0, 2.0], [-1.0, 1.0]]))
    layer.bias.copy_(torch.tensor([0.0, 1.0]))

layer.eval()
with torch.no_grad():
    h = torch.relu(layer(torch.tensor([[1.0, 2.0]])))
assert h.tolist() == [[5.0, 2.0]]
```

若误把 Burn 的 W 原样写入 `layer.weight`，这里算的是 `XWᵀ+b`，ReLU 后会得到 `[0, 5]`，并不是我们的 `[5, 2]`。这也是迁移时应该保留小型确定性算例的原因。

还要区分模式：PyTorch `eval()` 调整受模式影响的层，[`no_grad()`](https://docs.pytorch.org/docs/stable/generated/torch.no_grad.html) 暂停相应区域的梯度记录；前者并不自动完成后者。Burn 本版的 `valid()` 同时处理模块训练标志和参数自动微分配置，不能把两端调用按名字一对一替换。完整训练/推理对照放在[第 7 章](./07-training-to-inference.md)。

## 自测

1. `derive(Module)` 会自动生成本书的 ReLU 前向吗？**不会。** 计算流程仍由 `forward` 定义。
2. 为什么配置中写“2→2”不足以重现结果？**它只描述结构，没有给出具体参数值。**
3. 六个参数是否包括输入的两个数？**不包括。** 输入是本次数据，参数是模型状态。
4. Burn 与 PyTorch 的 2→2 Linear 权重形状相同，能否直接复制元素而不转置？**不能。** 形状相同掩盖了两端公式的方向差异，应保持 `A = Wᵀ` 的对应。
5. batch 从 1 变成 10，参数量会增加吗？**本层不会。** 多个样本共享同一组权重与偏置，改变的是本轮数据量。

接下来读[第 5 章：Backend 与执行路径](./05-backends-and-dispatch.md)，跟踪这些层调用的张量运算怎样到达具体实现。
