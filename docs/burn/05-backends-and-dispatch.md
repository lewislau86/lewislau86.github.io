# 第 5 章：Backend 与执行路径

[学习总览](./index.md) · [上一章：模型与 Module](./04-models-and-modules.md) · [下一章：自动微分](./06-autodiff.md)

第 3 章的一行 `x.matmul(w)` 可以在 CPU 执行，也可以在启用相应支持后交给 GPU。模型代码怎样找到不同实现？为什么扩展算子要定义 `Backend` trait，而调用模型时只写 `Tensor<2>`？本章从一组加法开始，把这些接口连起来。

本章依据 **Burn v0.22.1**，固定提交 `907ab111a02c2dea47bc41633754f095c6b2220e`。正文同时参考[官方 Backend 架构页](https://burn.dev/books/contributor/project-architecture/backend.html)与[Backend Extension 指南](https://burn.dev/books/burn/advanced/backend-extension/index.html)，并以固定版本源码核对接口。在线文档会继续更新；以后若与本章不同，请分别阅读对应版本，避免拼接 API。实验进展见[第 13 章](./13-learning-labs.md)。

::: tip 本章分两遍读
第一遍跟住一条主线：**公式相同 → 实现可以不同 → Device 给张量指定资源 → Dispatch 把操作交给具体实现**。先读 5.1、5.2 开头、5.3 的路径图、5.5 前三段和 5.7，再进入第 6 章。

第二遍在阅读源码或第 11 章扩展时回来：理解关联类型、函数签名、默认 dtype、Cube 别名与装饰器细节。`GraphPrimitive`、checkpoint、NodeGuard 是实现背景，初读不需要记住所有名字。
:::

## 5.1 先区分公式、实现和设备

“把两组数相加”规定了数学结果，却没有规定怎样得到结果。CPU 可以循环处理内存；GPU 可以让许多工作项处理不同位置，并通过运行时提交计算。框架希望模型只表达运算，把这些执行细节交给下层。

先手算下面的例子。两组数的形状都是 `[1, 3]`，结果仍是 `[1, 3]`：

```text
a = [[1, 2, 3]]
b = [[4, 5, 6]]
c = a + b = [[5, 7, 9]]

CPU 实现的思路：依次计算 c[i] = a[i] + b[i]
GPU 实现的思路：多个工作项分别负责各自的 i
```

上面是实现思路，不是完整设备内核。实际实现还要考虑数据类型、内存布局、广播与边界。

| 名字 | 用一句话解释 | 在这个例子中是什么 |
| --- | --- | --- |
| 运算 / operator | 要计算的数学行为 | 逐元素加法 |
| Backend | 提供张量表示和运算实现的接口与实现者 | Flex、CubeBackend 等实现路径 |
| Device | 应用持有的计算资源与执行上下文入口 | 某个 CPU 资源或某块 GPU |
| Runtime | 与执行资源通信、管理和提交工作的设施 | CUDA、WGPU 等运行时 |
| Kernel | 具体执行一段数值计算的设备程序 | 实现各位置加法的程序 |

Backend 不是权重文件，也不是显卡本身。可以把它类比成“打印接口及其驱动实现”，把 Device 类比成选定的打印资源；但真实计算还受 dtype、内存与异步执行约束。

## 5.2 公共 Tensor 与 primitive 为什么要分层

用户需要 `matmul`、`reshape` 和形状检查，后端需要自己的内存句柄、布局和设备信息。让所有用户代码直接操作 GPU 缓冲区，会把模型与某种设备绑在一起；强制所有后端只使用同一种数组表示，又会限制实现和优化。

Burn 因此区分公共张量与 **primitive（后端底层张量表示）**。primitive 不是“一个数字”，也不是“必然存放在 CPU 的数组”；它可以是带元数据的设备缓冲区句柄，也可以是装饰器包裹的表示。

| 表示 | 谁主要使用 | 保留什么自由度 |
| --- | --- | --- |
| `Tensor<D, K>` | 模型作者与应用 | 统一操作；`D` 表示阶数，`K` 表示数值类别 |
| `BridgeTensor` | 公共接口内部 | 隐藏具体实现类型，连接公共 API 与分派 |
| `DispatchTensor` | 运行时分派层 | 依据张量和上下文把操作送往具体实现 |
| Backend primitive | 后端或扩展作者 | 使用适合自身的存储、元数据与执行方式 |

`Tensor<2>` 表示二维浮点张量，不能仅凭类型判断它在 CPU 还是 CUDA，也不能判断它是 `[1, 3]` 还是 `[100, 200]`。长度、设备与实际 dtype 还需要运行时信息。

可以用第 3 章的 W 检查这个区别：公共层看到“一个形状为 `[2,2]`、能参加 matmul 的张量”；Flex 实现需要知道如何读取它的数值；GPU 实现需要知道设备缓冲区、布局和运行时。模型仍写 `x.matmul(w)`，底层表示可以不同。统一的是操作含义，并不是强制所有实现采用同一个存储结构。

### BackendTypes：先约定各类表示是什么

Rust 的 **trait** 可以理解为接口；**关联类型**是在接口中留出的类型位置，由实现者填写。`BackendTypes` 就像一张“本实现使用哪些表示”的表。

下面对应[固定版本 `base.rs`](https://github.com/tracel-ai/burn/blob/v0.22.1/crates/burn-backend/src/backend/base.rs)的核心类型，省略了约束，不是完整 trait 定义：

| 关联类型 | 负责什么 | 不要误解成 |
| --- | --- | --- |
| `Device` | 此实现使用的底层设备类型 | 应用必须公开这个具体类型 |
| `FloatTensorPrimitive` | 浮点张量表示 | 固定只能存 `f32` |
| `IntTensorPrimitive` | 整数张量表示 | 固定只能存 `i32` |
| `BoolTensorPrimitive` | 布尔张量表示 | 一定采用 Rust `bool` 的存储方式 |
| `QuantizedTensorPrimitive` | 量化张量表示 | 任意整数数组都能当作量化张量 |
| `GraphPrimitive` | 后端捕获的启动序列表示 | 自动微分记录的求导图 |

分开约定这些类型，是允许不同类别采用不同表示；某个后端也可以让几个关联类型复用同一种内部结构。量化表示还需要量化规则等信息，后文再解释。

`GraphPrimitive` 用于支持捕获的后端记录设备启动序列并重放；不支持者可使用 `GraphUnsupported`。这不代表所有后端都支持捕获，也不要求入门代码手动操作它。它与“记录导数关系”的图解决不同问题。

### `FloatTensor<B>`：后端底层表示的缩写

在底层源码中，这两种写法表示同一类型：

```rust
// 固定版本 alias.rs 中的类型别名。
pub type FloatTensor<B> = <B as BackendTypes>::FloatTensorPrimitive;
```

把它读成“后端 B 使用的浮点张量表示”。尖括号中的 `B` 是后端类型参数。它与应用使用的 `Tensor<D>` 处于不同层次，不能看到两个名字都带 Tensor 就混为一谈。[类型别名源码](https://github.com/tracel-ai/burn/blob/v0.22.1/crates/burn-backend/src/alias.rs)。

## 5.3 从一次加法看完整执行路径

根据[固定版本的张量架构说明](https://github.com/tracel-ai/burn/blob/v0.22.1/contributor-book/src/project-architecture/tensor.md)，可以按下面的层次阅读。它们是职责划分，并不表示每层都复制一次数据。

![从模型到硬件的执行路径，区分公共 API、分派、后端与运行时](/burn/execution-stack.svg)

图中以模型直接调用 `Tensor::matmul` 等操作为例。Linear 模块的普通浮点路径可以整体分派 `linear`，再由后端默认体组合矩乘与加法，不必先回到公共 `Tensor::matmul`；[第 12 章](./12-source-reading.md)会把这两条路线分开追踪。

```text
模型 / Module：决定先加法，再做什么
  → 公共 Tensor：接收 a + b，检查用户层形状条件
  → Bridge：转交底层表示与对应操作
  → Dispatch：依据已有张量及执行上下文路由
  → Backend / 装饰器：计算，或记录并转发工作
  → 执行设施：使用 CPU 路径或向相应运行时提交 kernel
  → 结果表示逐层包装，回到可继续使用的 Tensor
```

先假设 `a`、`b` 都是同一设备上的相容浮点张量。公共操作经过桥接和分派后，最终进入对应实现的浮点加法；完成或登记工作后，返回该实现的浮点 primitive。

阅读入口依次是 [`api/numeric.rs`](https://github.com/tracel-ai/burn/blob/v0.22.1/crates/burn-tensor/src/tensor/api/numeric.rs)、[`bridge/ops/float.rs`](https://github.com/tracel-ai/burn/blob/v0.22.1/crates/burn-tensor/src/bridge/ops/float.rs)、[`burn-dispatch/src/ops/tensor.rs`](https://github.com/tracel-ai/burn/blob/v0.22.1/crates/burn-dispatch/src/ops/tensor.rs)。先搜索 `add` / `float_add` 和调用方向，暂时跳过宏展开细节。

“拿出底层表示”不等于“从 GPU 下载数组”。许多步骤只是转交、包装句柄；只有实际的数据传输操作才负责搬运。

### 怎样读后端操作的函数签名

`Backend` 除了继承 `BackendTypes`，还要求浮点、整数、布尔、激活、模块等操作 trait。初读时可把它理解成“表示清单 + 运算能力清单”。

下面是[浮点操作 trait](https://github.com/tracel-ai/burn/blob/v0.22.1/crates/burn-backend/src/backend/ops/tensor.rs)中的一条真实签名；它位于以 `B` 为参数的操作 trait 中：

```rust
fn float_add(lhs: FloatTensor<B>, rhs: FloatTensor<B>) -> FloatTensor<B>;
```

逐段读：`lhs` / `rhs` 是左、右操作数；两者使用后端 B 的底层浮点表示；返回值也使用 B 的表示。函数没有 `&self`，所以它是关联函数，不需要先创建一个“后端对象”再调用。

在实现内部常见的 `B::float_add(lhs, rhs)`，意思是“调用 B 提供的加法能力”。设备信息由输入表示等信息携带；不需要每次加法额外传入一个模型对象。

这一接口的参数按值传递，允许实现掌握所有权并判断存储能否复用，但不保证每次都会原地修改。共享存储时必须保持其他有效句柄可观察到的结果正确。

## 5.4 dtype 在运行时决定，设备默认值要提前配置

**dtype** 表示元素实际采用的数据类型，例如 F32 或 F16。数值类别“浮点”和实际精度“F32”不是同一个层次：同属浮点类别的两个张量，可以采用不同精度。

在本章固定版本中，`BackendTypes` **没有 `FloatElem` / `IntElem` 关联类型**。primitive 通过元数据报告 dtype，操作按需要接收 dtype 或标量信息。不能照搬旧资料中的 `type Backend = Wgpu<f32, i32>`，解释为本版公共模型的选型方式。

源码测试里仍可能出现 `FloatElem` / `IntElem`：那可以是测试目标的类型别名，不能据此推断它们仍是 `BackendTypes` 的关联类型。[固定版本的 Backend 说明](https://github.com/tracel-ai/burn/blob/v0.22.1/contributor-book/src/project-architecture/backend.md)。

| 需求 | 应在何处处理 | 对已有张量的影响 |
| --- | --- | --- |
| 指定以后默认创建的 dtype | 首次创建张量前调用 `device.configure(...)` | 不会批量转换已有张量 |
| 为一个新张量指定 dtype | 使用相应的显式 dtype 创建接口 | 只决定这个新张量 |
| 转换一个已有张量 | 使用 `tensor.cast(...)` | 返回转换后的张量，不修改设备默认值 |
| 判断某设备是否支持 dtype | `device.supports_dtype(...)` | 查询能力，不执行转换 |

设备默认设置只能初始化一次。**首次张量创建会锁定默认设置，即使该次创建显式指定了 dtype**；之后再 `configure` 会返回 `AlreadyInitialized`。因此顺序应是“选设备 → 配置默认值 → 创建张量或模型参数”。仅查询 `settings()` 不会锁定设置。[设备配置源码](https://github.com/tracel-ai/burn/blob/v0.22.1/crates/burn-tensor/src/device.rs)。

支持某 dtype 也有层次。`supports_dtype` 问的是它能否用于一般张量操作，需要存储、转换和基本运算等能力；硬件能在某种特殊矩阵指令里使用某精度，不一定意味着能把它当作所有普通运算的默认 dtype。不要仅凭显卡规格作出判断。

## 5.5 Cargo 选择可用能力，Device 选择执行资源

下面是第 3 章使用的 API 阅读片段；完整工程配置与验证状态见[实验路线](./13-learning-labs.md)：

```rust
let device = Device::flex();
let x = Tensor::<2>::from_floats([[1.0, 2.0]], &device);
```

启用 `flex` Cargo feature，意味着应用包含这条实现路径；调用 `Device::flex()`，明确给这次张量创建指定 Flex CPU 资源。一个是构建阶段的能力开关，一个是运行时的资源选择。

Dispatch 依据已有张量等信息调用对应实现，并不会为每次加法比较所有显卡、自动挑最快的一块。普通分派也不会替你把不同设备的输入搬到一起。

已经存在的张量保留自己的执行信息。只修改局部变量 `device` 不会使旧张量搬家；迁移需要明确的数据迁移接口。两个形状相同的张量，也可能因设备或 dtype 不相容而无法直接参与同一操作。

### CubeBackend、Cube、Cuda、Wgpu 为什么容易混淆

在固定版本中，CubeCL 的多个运行时共用 **`burn_cubecl::CubeBackend`**。底层 `CubeDevice` 指明具体运行时资源；应用仍使用统一 `Device` 选择资源。

```text
CubeBackend                 直接实现 CubeCL 张量操作
Cube                        分派使用的类型别名
  fusion 关闭时             = CubeBackend
  fusion 开启时             = Fusion<CubeBackend>
Cuda / Wgpu 等运行时门面名  对应上述共同的 Cube 类型结构
具体使用 CUDA 还是 WGPU     由设备选择，不靠 Tensor<2> 的类型区分
```

对应源码是 [`burn-cubecl/src/lib.rs`](https://github.com/tracel-ai/burn/blob/v0.22.1/crates/burn-cubecl/src/lib.rs)、[`burn-cuda/src/lib.rs`](https://github.com/tracel-ai/burn/blob/v0.22.1/crates/burn-cuda/src/lib.rs)和 [`burn-wgpu/src/lib.rs`](https://github.com/tracel-ai/burn/blob/v0.22.1/crates/burn-wgpu/src/lib.rs)。门面 crate 负责引入或配置相应运行时，但没有给扩展创造一套全新的后端选择器。

所以扩展宏写 `#[backend_extension(Cube)]`，而不是 `#[backend_extension(Cuda)]` 或 `#[backend_extension(Wgpu)]`。但**选择 Cube 不等于你的内核天然支持所有运行时**：CubeCL 可移植内核和只适用于兼容 WGPU 编译路径的 WGSL 内核，适用范围不同。[第 11 章](./11-custom-operators.md)会把注册与真实实现一起展开。

## 5.6 装饰器怎样增加自动微分与融合能力

**装饰器**是在原实现外增加行为的一层。它继续满足后端接口，同时把实际数值工作交给内层。比如餐厅在原有厨房外增加订单记录系统，厨房仍负责做菜；这个类比只说明记录与执行的分工。

| 层 | 增加的能力 | 它自己不会代办的工作 |
| --- | --- | --- |
| `Autodiff<B, C>` | 记录反向所需关系，计算一阶反向模式梯度 | 自动推导任意手写内核的导数 |
| `Fusion<B>` | 记录待执行操作，提供延迟执行和融合优化机会 | 保证任意相邻算子都合成一个内核 |
| 内层 B | 实现真正的张量运算 | 凭空获得外层未提供的扩展行为 |

`B` 是内层后端，`C` 是 **checkpoint strategy（检查点策略）**：决定反向需要的某些中间值怎样保存或重算，以权衡内存与计算。检查点不是模型权重存档，也不会让已消耗的反向图永久保留。

公共 API 不再让每个应用张量暴露 B；自动微分上下文在运行时由张量携带，Device 可以提供创建默认值。底层仍通过 `Autodiff<B, C>` 组织实现，因此“应用不写 B”和“源码有泛型 B”可以同时成立。

### 开启能力、跟踪计算、保留梯度是三回事

考虑 `x = [2, 3]`、`y = x²`、`L = sum(y)`：手算得到 `y = [4, 9]`、`L = 13`、`dL/dx = [4, 6]`。框架要得到最后一组数，必须知道 L 怎样依赖 x。

1. `.autodiff()` 使设备创建的张量具备自动微分上下文。
2. 在需要求导的**源叶子**上使用 `.require_grad()`，声明需要它的梯度；源叶子就是这段计算的起点，例如输入或参数。
3. 依赖被跟踪输入的操作记录反向步骤。常量不因为处于同一设备就自动变成求导目标。
4. `backward()` 沿记录反向计算，返回梯度容器；`x.grad(&grads)` 取出 x 被保留的梯度。

中间量参与链式求导，不等于其梯度一定为用户保留。`is_autodiff()`、`is_tracked()`、`is_require_grad()` 分别回答“有没有上下文”“是否参与跟踪”“是否要求保留梯度”，应按需要区分。不要在已经参与跟踪的中间量上随意补 `require_grad()` 来索取梯度；本版本对非叶子的这种转换有限制。

### backward 会消耗图，clone 不会复制一份求导历史

固定版本的 `backward(&self)` 虽然借用张量，却会**消耗从输出可达的反向步骤**；克隆句柄共享这些步骤。对同一已消耗中间图再次反向会被拒绝，本版没有 `retain_graph` 支持。[公共接口的生命周期约定](https://github.com/tracel-ai/burn/blob/v0.22.1/crates/burn-tensor/src/tensor/api/autodiff.rs)。

如果两个损失共享中间计算，可以先合成总损失再反向；或者各自重新执行前向，再分别反向。参数叶子可以用于新的前向计算，所以这并不妨碍训练循环的下一轮。

`detach()` 表示主动切断之前的求导关系，不会恢复已消耗的图；仅为避免报错而使用它，可能切掉原本需要的参数梯度。梯度容器中的结果与原图步骤也不是一回事：能够再次读取已保留梯度，不表示能够再次执行原图的 backward。

### 自定义反向为什么还涉及 NodeGuard

这是扩展作者才需要操作的底层机制，第一次阅读可以跳到 5.7，先在下一章学会链式法则。构造子操作时，如果父输入句柄先被消耗或释放，运行时可能认为那部分无人使用的图已经可以回收；`NodeGuard` 让父节点活到子步骤注册完成。

固定版本通过 `AutodiffTensor::node()` 获取 guard，或通过 `into_parts()` 一起取出 primitive 和 guard，再把 guard 交给 `Backward::prepare`。它应该覆盖注册阶段，**不能塞进反向状态或 checkpoint 状态长期保存**，否则无人使用的图也可能无法回收。

同样，不应照抄旧资料直接访问 `.node` / `.primitive` 字段；本版字段为私有，提供 `node()`、`primitive()`、`into_parts()` 等接口。这些约束见 [`AutodiffTensor`](https://github.com/tracel-ai/burn/blob/v0.22.1/crates/burn-autodiff/src/tensor.rs)与 [`NodeGuard`](https://github.com/tracel-ai/burn/blob/v0.22.1/crates/burn-autodiff/src/ops/base.rs)，具体实现留到自定义反向时结合源码学习。

## 5.7 返回一个张量，为什么不代表设备已经算完

后端操作可以同步计算，也可以把工作排队，或让 Fusion 先登记操作。函数返回的句柄足以继续描述后续计算，不一定代表 CPU 已经能够立即读到结果。

这与内存复用是两个维度：一个关乎“何时执行”，另一个关乎“是否需要新的存储”。接口按值接收张量，可以让实现检查存储是否独占；独占时可能复用，共享时则必须维护正确语义。`clone()` 常用于复制句柄，不能把它简单换算成复制多少显存。

因此不能只用 CPU 包住 `a + b` 的调用就断言“GPU 加法耗时”。测性能要处理同步、预热与读回边界；详见[第 9 章：融合与性能](./09-fusion-and-performance.md)。模型运行正确与计时方法正确，需要分别验证。

## 5.8 扩展一个算子，不等于注册一个新后端

先区分两种目标：“在已有设备实现里增加 `square`”和“接入一种框架尚不认识的执行系统”。用户扩展通常做前一种。

固定版本的运行时分派使用[后端目录 `catalog.rs`](https://github.com/tracel-ai/burn/blob/v0.22.1/crates/burn-backend-extension/src/catalog.rs)。其中有 Cube、Flex、NdArray、LibTorch、Remote，以及用于特殊捕获路径的 Capture；这些项还受构建配置限制。Capture 是特殊路径，不能据此推断它与普通执行后端拥有相同功能。

这里的 Capture 记录张量操作而不执行数值计算。它与前文 `GraphPrimitive` 表达的设备启动序列捕获不同，也不是自动微分的求导图；看到“捕获”或“图”时，要先看记录的对象是什么。

`#[backend_extension(...)]` 在这套机制中扩展**操作**，不会凭一个新的名字自动注册未知后端。其基本路线是：

```text
声明新操作的后端 trait
  → 为支持的具体后端提供实现
  → 宏生成 Dispatch 路由
  → 公共 Tensor 包装函数调用路由
  → 需要训练或融合时，分别提供相应支持
```

宏既不替具体后端编写 kernel，也不从任意 kernel 自动求导。组合已有可微运算的默认实现，可以复用它们的微分路径；手写专门内核则必须明确处理反向。shape、dtype、设备检查也仍由包装或具体实现负责。

等读完自动微分和 GPU 基础后，再到[第 11 章：后端扩展与自定义算子](./11-custom-operators.md)，用可手算的函数学习 trait、宏、公共包装、具体实现、Fusion 与 Autodiff 怎样配合。这里先记住分工，后面才能判断“这一段到底补上了哪层能力”。

## 5.9 自测与答案

1. **`Tensor<2>` 能证明张量在 CUDA 且使用 F32 吗？** 不能。它表示阶数与默认浮点类别，设备和实际 dtype 是运行时信息。
2. **`FloatTensor<B>` 与用户的 `Tensor<2>` 是同一种接口吗？** 不是。前者是 B 的底层浮点表示别名，后者是公共张量 API。
3. **经过 Bridge、Dispatch 就复制了两遍数组吗？** 不一定。这些步骤可以只包装、转交句柄；不能从层数推出数据复制次数。
4. **已经创建张量后，再配置设备默认 dtype 可以吗？** 默认设置已初始化时不行，会返回 `AlreadyInitialized`；单个张量仍可用受支持的显式 dtype 创建或 cast。
5. **扩展宏应选择 Cube 还是 Cuda / Wgpu？** 此版本选择 Cube。真实内核仍受目标运行时和编译路径约束。
6. **开启 autodiff 后所有输入都有可读取梯度吗？** 不是。需要在源叶子上声明 `require_grad()`，记录依赖，再从反向返回的容器取梯度。
7. **克隆 loss 后，能用两份句柄对同一中间图反向两次吗？** 不能。句柄共享图步骤；应合并损失或重新执行前向。
8. **注册扩展、支持反向、支持融合，是一件事吗？** 不是。它们分别解决路由、导数和延迟优化接入；完整扩展需要逐项实现与验证。

后端不同，应保持同一运算的数学含义；具体布局、kernel、可用 dtype、执行顺序和速度可以不同。浮点结果通常按合理误差比较，不能要求所有设备逐位一致。教学先在 Flex 上验证小结果，再研究加速与差异。

接下来读[第 6 章：自动微分](./06-autodiff.md)，从链式法则理解为什么同一条执行路径能够记录并计算梯度。
