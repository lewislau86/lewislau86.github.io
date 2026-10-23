# 第 11 章：后端扩展与自定义算子

[学习总览](./index.md) · [上一章：权重导入与部署](./10-import-and-deploy.md) · [下一章：源码阅读地图](./12-source-reading.md)

第 5 章解释了张量调用怎样交给后端。这一章反过来问：**如果现有接口缺少我需要的操作，怎样让模型像调用普通算子一样使用它？**

这里重点展开你提供的[官方 Backend Extension 文档](https://burn.dev/books/burn/advanced/backend-extension/index.html)，并与[Backend 架构文档](https://burn.dev/books/contributor/project-architecture/backend.html)衔接。实现统一核对 **Burn 0.22.1** 的[固定版本扩展指南](https://github.com/tracel-ai/burn/blob/v0.22.1/burn-book/src/advanced/backend-extension/README.md)。

第一次阅读，先完成“最小扩展 → 实际运行 → 理解梯度”。后面的融合、结构化输入与专用 GPU 内核是继续深入的部分。CPU 扩展已有完整验证；Fusion、GPU 内核部分以原理和源码阅读为主，范围见[第 13 章](./13-learning-labs.md)。

::: tip 分两轮读这一章
第一轮读到“默认实现为什么可以求导，专用内核为什么不一定”，能运行例子并解释输出就达到目标。需要回顾时，分别查[第 2 章的 trait、impl 与泛型](./02-rust-for-burn.md)、[第 5 章的底层张量与分派](./05-backends-and-dispatch.md)、[第 6 章的链式法则](./06-autodiff.md)。

第二轮再从“注册哪些后端”继续：先处理支持范围与条件编译，再理解延迟执行需要的元数据，最后读 GPU 内核与手写反向。`ExtensionType` 面向多张量接口，第一次只做单输入时可以稍后阅读。
:::

## 先定义数学行为，再决定扩展到哪一层

沿用第 6 章的函数，让每个输入元素都计算 `y = x² + x`：

```text
x = [-2, 0, 3]
x² = [4, 0, 9]
y = [2, 0, 12]
```

逐元素运算不合并相邻位置，所以输出与输入形状相同。我们先要求普通浮点输入，输出保持设备与 dtype；这不表示实现自动支持所有设备和所有精度。

“增加一个功能”可以发生在不同位置：

| 做法 | 写什么 | 什么时候合适 |
| --- | --- | --- |
| 应用层组合 | 写一个函数，内部调用已有 Tensor 运算 | 公式能表达，现有性能足够 |
| 后端扩展 | 定义额外的后端操作，注册分派，暴露 Tensor 函数 | 想给同一操作安排不同实现，或接入专用内核 |
| 专用 kernel | 实现设备程序、布局处理和启动代码 | 正确性已建立，测量表明该处值得优化 |
| 新后端实现 | 实现一套底层计算能力并接入框架 | 要支持新的执行体系，工作量远大于一个算子 |

`#[backend_extension]` 用于给受支持的后端增加操作，不是动态注册任意新后端的插件接口。普通组合函数已经能解决问题时，不必为了使用宏而增加一层抽象。

例如下面就是应用层的组合版本，可作为参考公式：

```rust
fn reference<const D: usize>(x: Tensor<D>) -> Tensor<D> {
    x.clone() * x.clone() + x
}
```

它调用已有的乘法与加法。接下来仍使用相同数学规则，但把它放入后端扩展接口，观察需要新增哪些连接。

## 一个最小扩展需要四部分

先看职责，再读代码：

| 部分 | 本例名称 | 回答的问题 |
| --- | --- | --- |
| 后端接口 trait | `SquarePlusInputBackend` | 新操作接收和返回什么底层表示？ |
| 具体实现 impl | 为 Flex、Autodiff 提供实现 | 交给这个后端时怎样执行？ |
| 分派注册 | `#[backend_extension(Autodiff, Flex)]` | 运行时怎样找到已经提供的实现？ |
| 公共函数 | `square_plus_input(Tensor<D>)` | 模型作者怎样调用，不必接触底层表示？ |

![后端扩展从公共接口经过分派到 Flex 或自动微分实现的路线](/burn/backend-extension.svg)

这里的箭头表示调用关系。`into_dispatch()` 和 `from_dispatch()` 用来跨越表示边界，不表示把 GPU 数据下载到 CPU 再上传。

## 配置与核心代码

[CPU 学习包](/burn/first-inference.zip)已经加入完整的 `src/bin/backend_extension.rs`。依赖配置增加 `extension`，其余沿用前面的版本与 CPU 后端：

```toml
burn = { version = "=0.22.1", default-features = false, features = ["std", "flex", "autodiff", "extension"] }
```

`extension` 编译扩展机制，`flex` 编译本例的执行后端，`autodiff` 编译求导支持。编译了某项能力，不等于给所有张量自动启用它。

下面是学习包中完整的接口定义部分；运行入口与断言在包内 `main` 中。也可以单独下载<a href="/burn/first-inference/src/bin/backend_extension.rs" download>完整源文件</a>。

```rust
use burn::{
    backend::{
        Autodiff, Dispatch, Flex,
        autodiff::checkpoint::strategy::CheckpointStrategy,
        backend_extension, tensor::FloatTensor,
    },
    tensor::{Device, Tensor},
};

#[backend_extension(Autodiff, Flex)]
pub trait SquarePlusInputBackend: burn::backend::Backend {
    fn square_plus_input(input: FloatTensor<Self>) -> FloatTensor<Self> {
        let squared = Self::float_mul(input.clone(), input.clone());
        Self::float_add(squared, input)
    }
}

impl SquarePlusInputBackend for Flex {}

impl<B: SquarePlusInputBackend, C: CheckpointStrategy>
    SquarePlusInputBackend for Autodiff<B, C> {}

pub fn square_plus_input<const D: usize>(input: Tensor<D>) -> Tensor<D> {
    Tensor::from_dispatch(Dispatch::square_plus_input(input.into_dispatch()))
}
```

这是一个**复用已有原语的后端扩展**。它验证接口、分派和求导的连接，没有创建专用 CPU/GPU kernel，也不据此宣称加速。

## 逐段读懂代码，而不是记住宏的名字

`trait SquarePlusInputBackend: burn::backend::Backend` 表示：实现新能力的类型，必须先具备 Burn 的基本后端能力。因此默认方法可以使用 `float_mul`、`float_add`。

`FloatTensor<Self>` 是“当前后端的浮点张量底层表示”。`Self` 在 Flex 实现里是 Flex，在自动微分实现里是 `Autodiff<B, C>`。它不是应用层的 `Tensor<D>`，也不等于指定了 f32；具体精度仍需查看 dtype。

把最难的一行拆开读：`impl<B: SquarePlusInputBackend, C: CheckpointStrategy> ... for Autodiff<B, C>` 表示“只要内层后端 B 已支持这个操作，并且 C 是有效的检查点策略，就让包住 B 的自动微分层也支持它”。本例的 B 可以是 Flex；C 决定求反向时保存还是重算哪些中间值。这里的检查点策略不是第 10 章保存到磁盘的训练 checkpoint。

公共函数中的 `const D: usize` 允许同一段包装代码接收不同阶数，例如 `Tensor<1>` 与 `Tensor<2>`。我们能这样写，是因为逐元素公式对每个位置独立成立，并保持原来的 shape；这不是宣称任意新算子都能保留 D。

方法体就是 `x*x+x`，只是改用后端原语表达。这里的 `clone()` 保留多个运算边使用的句柄，不代表三份独立输入，也不承诺发生整块内存复制。

两个空 `impl` 并非“没有实现”。Rust 允许实现者复用 trait 已提供的方法体。Flex 复用普通的乘法和加法；Autodiff 复用会记录求导关系的乘法和加法。

宏生成的是该扩展 trait 在 `Dispatch` 上的路由实现。它不会替我们编写 Flex 内核，也不会阅读任意设备代码后自动推导反向公式。若删掉所需的具体 `impl`，只在宏里列出名字，并不能凭空补齐实现。

最后，公共函数把输入转换为分派表示，调用 `Dispatch::square_plus_input`，再包装回 `Tensor<D>`。调用者只需要传一个 Tensor，底层的后端类型参数留在实现层。

因此有两条具体路径：普通 Flex 输入走 `Dispatch → Flex 的默认乘加`；带自动微分上下文的 Flex 输入走 `Dispatch → Autodiff<Flex,C> 的默认乘加 → 内层数值运算`。第二条在计算数值之外登记反向所需的依赖，等调用 `backward()` 时再使用。注册路由、计算前向和执行反向是不同时间发生的工作。

## 运行，并把每个结果与手算对应

解压最新学习包，在项目目录执行：

```sh
cargo run --locked --bin backend_extension
```

本次在 Windows、Rust/Cargo 1.98.1、Flex CPU 上实际得到：

```text
Flex forward: x=[-2, 0, 3], y=[2.0, 0.0, 12.0]
2D forward: shape=[2, 3], y=[2.0, 0.0, 12.0, 0.0, 2.0, 6.0]
Autodiff sum: dL/dx=[-3.0, 1.0, 7.0]
Autodiff weighted sum: g=[2, -1, 0.5], dL/dx=[-6.0, -1.0, 3.5]
```

第二行检查输入 `[[-2,0,3],[-1,1,2]]` 的二维输出，同时断言形状 `[2,3]` 和设备保持一致。打印成列表不表示计算时丢失了形状。

第三行使用目标 `L=sum(y)`。因为 `dy/dx=2x+1`，在 `[-2,0,3]` 处应得到 `[-3,1,7]`。

第四行使用 `L=sum(y*g)`，`g=[2,-1,0.5]` 是常量。链式法则要求逐元素乘上 g，得到 `[-6,-1,3.5]`。它能检查实现是否只在“上游梯度全是 1”时碰巧正确。

| 输入 x | y=x²+x | 本地导数 2x+1 | 上游梯度 g | 最终梯度 g×(2x+1) |
| --- | --- | --- | --- | --- |
| -2 | 2 | -3 | 2 | -6 |
| 0 | 0 | 1 | -1 | -1 |
| 3 | 12 | 7 | 0.5 | 3.5 |

“上游”指从最终目标 L 沿反向路径传到当前输出 y 的那一侧。在这个例子里 `dL/dy=g`；`dy/dx=2x+1` 是当前操作自己的规则，两者相乘才是 `dL/dx`。

两次反向各自重新建立前向图，没有重复使用已消耗的中间步骤。读结果、形状检查、参数检查都是正确性工作；这些输出没有提供性能结论。

## 默认实现为什么可以求导，专用内核为什么不一定

本例在 `Autodiff<B,C>` 上执行默认方法时，`Self::float_mul` 和 `Self::float_add` 都是自动微分层的原语。它们已有反向规则，因此能记录并连接乘法、加法的梯度。

如果以后把 Flex 或 Cube 的方法改成专用前向内核，情况要分开看：

| 自动微分层的写法 | 训练时发生什么 |
| --- | --- |
| 继续使用本例默认组合 | 在自动微分层执行原有乘法、加法，复用这些运算的导数 |
| 手写自动微分方法 | 可以调用内层专用前向，同时登记与之匹配的反向步骤 |

仅优化具体后端的扩展方法，不会让自动微分默认组合自动改成那个专用前向。若需要训练也使用它，就要明确实现这条连接。

同一类型、同一 trait 不能同时保留两份相互重叠的 `impl`。切换到手写反向时，应修改原来的自动微分实现，而不是在后面再加一份相同实现。

## 注册哪些后端，就需要兑现哪些实现

宏中的名字是**分派选择项**。它描述运行时允许走哪些路，不会自动实现所有硬件。下面列出本章要认识的主要选择项，完整目录以固定版本源码为准。

| 选择项 | 含义与限制 |
| --- | --- |
| `Flex` | 纯 Rust CPU 后端，本例已实现并验证 |
| `Cube` | CubeCL 计算体系，具体运行时由设备等信息决定 |
| `NdArray`、`LibTorch`、`Remote` | 固定版本指南列出的其他执行选择项，使用前需核对依赖和实现 |
| `Autodiff` | 路由到自动微分装饰器，作者仍需提供对应 trait 实现 |
| `Fusion` | 请求生成融合装饰器支持，还需为每个方法选择处理规则 |

`Wgpu`、`Cuda` 是 Cube 体系的门面别名，不是这个宏接受的执行选择项。应注册 `Cube`，再确认自己实现实际适用的运行时。仅把本例输入设备换成未注册的后端会 panic，不能据此认为公共 Tensor API 不可移植。

多输入操作也不会自动搬运设备或替你选择精度。形状、dtype、设备相容性必须由公共包装或后端实现验证。求导上下文会按输入合并：普通输入可作为常量，启用自动微分的输入须满足检查点策略等相容要求。

## 条件编译的 feature 是谁的 feature

后续支持可选 WGPU 时，可以为自己的扩展 crate 建立功能转发。下面是配置关系的阅读片段，不是本 CPU 学习包当前启用的 GPU 配置：

```toml
[features]
wgpu = ["burn/wgpu"]
fusion = ["burn/fusion"]
```

```rust
#[backend_extension(
    Autodiff,
    Flex,
    Cube: cfg(feature = "wgpu"),
    Fusion: cfg(feature = "fusion")
)]
// 此处接扩展 trait；每个 Fusion 方法还需选用下文的一种注解。
```

`cfg(feature="wgpu")` 检查的是**写这段宏的 crate**，不是自动读取依赖 Burn 的 features。上面的 Cargo 转发才把两者连起来。开启相应条件时，也必须确实存在该后端的实现；关闭时则不生成那条路由。

实际配置应保留此前的 `extension`、`std` 等必要能力。不要把这两个片段当作能够独立运行的完整 GPU 工程。

## Fusion 的三种接法，先选对行为

Fusion 可以先记录操作，稍后再执行，所以必须在执行前知道输出怎样表示。官方提供三种方法级处理方式，**每个方法选一种**：

| 注解 | 用于什么 | 你需要提供什么 |
| --- | --- | --- |
| `#[fusion(dtype = input, shape = input)]` | 单个张量输出 | 能提前算出的输出 dtype 和 shape；这里直接沿用输入 |
| `#[fusion(meta = output_meta)]` | 多张量或结构化输出 | 回调描述输出整体结构及各字段元数据 |
| `#[fusion(default)]` | 已有默认方法由普通操作组合 | 复用默认方法，让其中的原有操作走自己的路径 |

例如本例的默认体只是乘加组合，后续扩展 Fusion 支持时可考虑 `default`；如果替换为一个不透明的自定义操作，就需要让延迟注册知道它的输出。这里只解释选择，CPU 包尚未验证 Fusion 路径。

“不透明”表示 Fusion 把这项扩展看作一个整体，不能仅凭操作名知道内部乘加关系。`default` 则直接展开已有默认体，由其中的乘法和加法各自进入原有路径，不为整个扩展另登记一个不透明操作。因此这三个注解是在选择具体行为，并非三个可以叠加的优化等级。

`shape = output_shape(lhs,rhs,bias)` 这类辅助函数接收借用的输入形状，并返回拥有所有权的 `Shape`。它必须落实真实运算规则，例如矩乘内维相等、批次能否广播、bias 允许什么形状。

宏生成的 Fusion 实现负责把操作作为待执行工作登记。它不会生成导数，也不保证自动把该内核和相邻内核合并。需要识别这类操作并进一步融合时，还涉及相应优化器对操作中间表示的处理。若自己手写 `Fusion<B>` 的实现，就不要同时要求宏为同一实现生成代码。

## 为什么元数据必须在读到数值前就正确

把延迟执行理解成预订一份工作：虽然饭还没做好，但你必须先告诉后续步骤“会有几个盘子、每盘多大”。这里的盘子信息就是 shape、dtype 和输出结构。

对 `y=x²+x`，输出形状沿用输入，不用知道元素值。对矩乘，`[M,K]×[K,N]` 的输出是 `[M,N]`，同样能由形状推导。

例如输入规格是 `shape=[2,3]、dtype=f32`：登记调用时，Fusion 就能先返回一个表示“将来有一个 `[2,3]` f32 结果”的张量；后续运算可以继续检查形状和登记依赖。实际数值可以等到执行和回读时才产生。如果此时谎报 `[2,4]`，后续操作会建立在错误规格上，即使最终内核算对了六个数也救不回这条执行关系。**元数据不是可有可无的注释，而是后续计算的依据。**

但“数组中大于零的元素有几个”取决于实际数值，不能在尚未执行时凭输入 shape 得到。

固定版本的生成逻辑还有一个需要认真理解的边界：**结构化输出中的非张量值直接由元数据回调提供，后端稍后返回的对应值会被丢弃，不会自动对照检查。** 输出形状也不会因 debug 构建就自动与执行结果比较。

这不表示所有检查都缺失：debug 构建会检查 dtype 类别、设备及输出 dtype/设备；输出枚举的分支一致性在所有构建中都会检查。它们仍不能替代作者保证 shape 与普通字段正确。

因此，如果输出里有 `count: usize`，它必须在登记时就能够正确确定。如果 count 依赖输入数值，应考虑返回一个承载结果的张量，或手写会等待执行的 Fusion 路径。不能先填 `0`，期待运行时自动用真实 count 覆盖。

## ExtensionType：一组张量怎样一起传进去

实际操作可能一次接收检测框、分数与索引。`ExtensionType` 让后端扩展认识结构体、枚举中保存的张量，而不必把接口拆成很多独立参数。

先用普通 Rust 结构体理解：检测框和分数是两块张量，`count` 是一项普通说明，结构体把它们作为一次调用的数据包。宏需要知道哪些字段藏着张量，才能转换底层表示、寻找后端和传递求导上下文。这就是派生 `ExtensionType` 要补上的知识。

下面是类型定义的阅读片段；完整操作实现仍需另行提供：

```rust
use burn::backend::{Backend, ExtensionType, tensor::FloatTensor};

#[derive(ExtensionType)]
pub struct Detections<B: Backend> {
    pub boxes: FloatTensor<B>,
    pub scores: FloatTensor<B>,
    pub count: usize,
}
```

把它用作扩展操作的输入时，用参数上的 `#[extension_type]` 标明；嵌套的扩展类型字段也需要对应标记。若生成 Fusion 支持，结构体或枚举还需要 `#[extension_type(fusion)]`，并按输出规则提供元数据。

`meta` 回调会收到借用的 `TensorSpec` 或扩展元数据，可以把 `TensorSpec` 理解成“张量的规格说明”。它提供描述输出所需的信息，不会为了回调自动读取整个输入数组。普通返回字段应放进扩展结构中，不能假定任意混合“张量和标量”的元组都能直接作为 Fusion 输出。

分派层从实际存在的张量选择后端，并合并所有张量输入的求导上下文。一个当前处于 `Empty` 分支、不含张量的枚举会继续让后续输入提供路由依据；如果所有输入都没有张量，便无法选择后端，会 panic。

自动微分中浮点字段可以承载梯度，整数索引、布尔值和 `count` 等普通字段不会因此变成可微变量。`derive(ExtensionType)` 负责识别和传递结构，不会自动生成这些字段所对应算法的反向实现。

## 走向专用 kernel：还要增加哪些责任

先用已验证的组合实现作为参考，再编写设备程序。最简单的逐元素内核可以先这样理解：

```text
教学伪代码，不是可直接运行的 CubeCL 或 WGSL

i = 当前工作项的全局索引
如果 i >= 元素总数：退出
value = input[i]
output[i] = value * value + value
```

真正实现还要处理连续性、stride、dtype、输出缓冲区和启动网格。转置张量可能不是连续数组；若直接把 `input[i]` 当作顺序数据读取，公式正确也可能索引错误。

其中“启动网格”决定发出多少工作项，“边界判断”处理元素总数不能整除工作项分组大小的尾部。例如有 10 个元素、每组 4 个工作项，可发出 3 组共 12 个工作项，但最后两个必须退出。输出缓冲区则是承接结果的设备内存；这些责任都不会因为公式只有一行而消失。先回顾[第 8 章](./08-gpu-and-kernels.md)，再把伪代码对应到真正的启动 API。

两份官方教学材料的分工也要看清：

| 教程 | 学什么 | 不能直接推断什么 |
| --- | --- | --- |
| [CubeCL 内核](https://github.com/tracel-ai/burn/blob/v0.22.1/burn-book/src/advanced/backend-extension/custom-cubecl-kernel.md) | 可移植内核表达、启动、Fusion 注册、手写反向 | 所有设备都达到相同速度 |
| [WGPU 内核](https://github.com/tracel-ai/burn/blob/v0.22.1/burn-book/src/advanced/backend-extension/custom-wgpu-kernel.md) | 提交 WGSL 源码的执行路径 | 注册 Cube 后就能在 CUDA 或任意 WGPU 编译路径运行 |

WGSL 是 WebGPU 的着色/计算语言。该 WGPU 示例要求接受 WGSL 的编译路径；选择 SPIR-V 或 MSL 的构建会拒绝这种源码。Cube 选择项能覆盖多种运行时，不会改变具体内核本身的限制。

## 接回主线：matmul、偏置和 ReLU 的手写反向

官方专用内核示例计算的正是 `H=ReLU(XW+b)`。可以把完整实现分为四份读：

| 文件 | 先找什么 |
| --- | --- |
| [`lib.rs`](https://github.com/tracel-ai/burn/blob/v0.22.1/examples/custom-cubecl-kernel/src/lib.rs) | 扩展 trait、Tensor 包装、参考实现、输出形状规则 |
| [`forward.rs`](https://github.com/tracel-ai/burn/blob/v0.22.1/examples/custom-cubecl-kernel/src/forward.rs) | 同设备与 dtype 检查、整理布局、分配输出、提交工作 |
| [`kernel.rs`](https://github.com/tracel-ai/burn/blob/v0.22.1/examples/custom-cubecl-kernel/src/kernel.rs) | 一个工作项如何找到元素，怎样做乘加和边界保护 |
| [`backward.rs`](https://github.com/tracel-ai/burn/blob/v0.22.1/examples/custom-cubecl-kernel/src/backward.rs) | 保存哪些前向信息，怎样返回 X、W、b 的梯度 |

该教学 kernel 要求 bias 与输出完整形状相同。主线的共享偏置 `[N]` 或 `[1,N]` 不能未经处理就当作满足该规则；普通 Tensor 加法的广播能力不能自动赋予自定义内核。

官方公共包装的三个输入都是 `Tensor<3>`，按 `[批次,行,列]` 理解。下方二维公式是去掉批次维后的数学演示；实际调用示例需要增加批次维，并准备与输出完整形状相同的 bias。

先忽略批次广播，令 `G` 为 H 收到的上游梯度，`R=G * ReLU导数`，则可以手算：

这里 `*` 是对应位置逐元素相乘，矩阵乘法单独写成矩阵并置。激活前 `Z=XW+b`，ReLU 在 `Z>0` 的位置导数为 1，在 `Z<0` 的位置为 0；`Z=0` 不可导，需要实现选择一个约定。这样先算 R，就把激活层的影响传回了线性部分。

```text
dX = R Wᵀ
dW = Xᵀ R
db = R                    # bias 与输出一一对应的情形
db = 沿广播轴对 R 求和     # 如果你另行支持共享 bias
```

检查 shape 能帮助理解公式：`X:[M,K]`、`W:[K,N]`、`R:[M,N]`，所以 `R Wᵀ:[M,K]` 与 X 对齐，`Xᵀ R:[K,N]` 与 W 对齐。若偏置在 M 行之间共享，每行都对同一偏置贡献梯度，因此要把这些贡献相加，而不是只取某一行。

在主线 `X=[[1,2]]`、`W=[[1,-1],[2,1]]`、`b=[0,1]` 中，激活前都是正数。取 `L=sum(H)`，所以 `R=[[1,1]]`，得到 `dX=[[0,3]]`、`dW=[[1,1],[2,2]]`、`db=[1,1]`。这是数学检查例子，不是本次已运行的专用 kernel 验证结果。

源码里的 `Backward::prepare` 负责准备父节点与反向登记，`prep.finish` 把输出连接到图。`NodeGuard` 暂时保护输入节点，必须活到子步骤登记结束；不要把 guard 本身存进反向状态或检查点状态。用 `primitive()` 借用底层值，用 `node()` 取得 guard，或用 `into_parts()` 一并移出底层值与 guard；不能照旧代码访问已经私有的字段。

为什么还需要 guard？框架会回收已经没人需要的求导图。构造子操作时，输入张量可能已被移入函数或拆开；在子节点登记完成前，父节点仍必须存在。guard 用临时持有关系保护这个窗口；仅保存节点编号不会延长节点生命。完成登记后，真正需要留给 backward 的数值与状态应由反向步骤及检查点机制保存。

更深的状态保存与重计算选择可以在理解本例以后继续读。先确保知道“前向要算什么、反向要用什么、何时连接节点”，再研究这些结构的每个字段。

## 排错与验证顺序

| 现象或测试 | 先检查什么 |
| --- | --- |
| 注册了选择项却编译失败 | 对应后端 trait 实现是否存在，features 是否匹配 |
| 普通 CPU 可用，换设备 panic | 新后端是否注册并实现，具体 kernel 是否支持该运行时 |
| forward 正确，backward 不工作 | 自动微分 trait 实现、源叶子的 require_grad、上下文是否相容 |
| 开启 Fusion 才出错 | 方法注解、输出元数据、默认体与直接执行是否一致 |
| 转置输入错误 | 连续性假设或 stride 索引是否错误 |
| 长度不能整除线程组时错误 | 最后若干工作项的边界判断 |
| 相同 shape 却结果不对 | dtype、设备、权重布局和运算语义 |

验证顺序是：固定数值 → 多形状与设备约束 → 随机输入和容差 → 非连续布局 → 多种上游梯度 → 有限差分 → 性能。只调用一次同步不能证明所有输出都正确，应该实际读回并比较。

有限差分可用 `(f(x+ε)-f(x-ε))/(2ε)` 对照，但 ε 过小也会放大舍入问题。性能则另外测量，方法见[第 9 章](./09-fusion-and-performance.md)。

## 自测与答案

1. 宏中列出 Flex，就等于实现了 Flex 的数值计算吗？**不等于。** 本例还显式提供 impl，并复用默认体。
2. 本例为什么没有手写 backward？**因为自动微分默认体由已有的可微乘加原语组成。**
3. 专用前向 kernel 已写好，为什么还要决定自动微分怎么接？**框架不能从任意内核自动获知导数，也不会自动替换默认组合路径。**
4. `#[fusion(dtype=input,shape=input)]` 会自动比较真实输出的 shape 吗？**不会。debug 的 dtype/设备检查仍不能替代作者保证全部元数据正确。**
5. 内容相关的 count 能先随便填一个 usize 吗？**不能。** 生成的 Fusion 路径会立即返回元数据给出的非张量值。
6. 注册 Cube 后，WGSL 内核一定能在 CUDA 上执行吗？**不能。** 路由范围与内核实际支持范围需要同时满足。

继续按[源码阅读地图](./12-source-reading.md)追踪一次调用。想查签名限制、操作标识和标量编码，再读[固定版本宏参考](https://github.com/tracel-ai/burn/blob/v0.22.1/crates/burn-backend-extension/src/lib.rs)；先把上面的最小例子解释清楚，再深入宏内部更容易建立联系。
