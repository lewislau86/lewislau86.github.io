# 第 12 章：源码阅读地图

[学习总览](./index.md) · [上一章：后端扩展与自定义算子](./11-custom-operators.md) · [下一章：实验路线](./13-learning-labs.md)

第一次打开 Burn 仓库，会看到很多 crate。**crate** 是 Rust 编译和组织代码的单位；这个仓库把张量、模块、后端等职责拆开了。你不需要先读完整个 workspace，先追踪一次能手算的预测即可。

本章按 **Burn v0.22.1** 给出任务地图。每一步只带一个问题进入源码，找到答案就先停；命令与代码片段用于阅读导引，整仓构建与调试尚待后续实验验证。

先确认自己能回答三个问题：主线 `XW+b` 的形状怎样变化；公共 Tensor、Dispatch、具体后端各负责什么；前向计算与反向记录有什么区别。若还说不清，可分别回看[第 1 章](./01-tensors-and-memory.md)、[第 5 章](./05-backends-and-dispatch.md)、[第 6 章](./06-autodiff.md)。读源码的目标是解释已知现象，不是一次记住所有内部类型。

## 12.1 先固定版本和预期答案

```powershell
git clone --branch v0.22.1 --depth 1 https://github.com/tracel-ai/burn.git burn-source
cd burn-source
git rev-parse HEAD
```

这个 tag 对应 `907ab111a02c2dea47bc41633754f095c6b2220e`。浅克隆先下载指定版本所需的历史，足够进行本章阅读；以后要研究版本演进，再补历史。

该版本 `crates/burn/Cargo.toml` 声明 `rust-version = "1.95"`，编译前准备 **Rust 1.95 或更高版本**，并用 `rustc --version` 检查。阅读源码本身不要求先编译整个仓库。

这项声明是包的最低 Rust 版本要求，不等于本教程已经用每个较新工具链编译了所有可选后端。学习包实际验证的工具链是 Rust/Cargo 1.98.1；完整 workspace、目标设备及依赖版本的组合仍需按各自构建说明验证。

在纸上留一份参照，后面所有实现都应服务于这次计算：

```text
X 的 shape = [1,2]，X = [[1,2]]
W 的 shape = [2,2]，W = [[1,-1],[2,1]]
b 的 shape = [2]，  b = [0,1]
XW = [[1×1+2×2, 1×(-1)+2×1]] = [[5,1]]
Z = XW + b = [[5,2]]
H = ReLU(Z) = [[5,2]]
```

## 12.2 一次只读一条调用链

| 顺序 | 你的问题 | 起点 |
| --- | --- | --- |
| 1 | 模型怎样拿到权重并调用线性运算？ | `burn-nn/src/modules/linear.rs` |
| 2 | 线性层怎样交给张量实现？ | `burn-tensor/src/tensor/module.rs` |
| 3 | 张量是什么，矩乘检查什么？ | `burn-tensor/src/tensor/api/` |
| 4 | 相同 API 怎样找到不同后端？ | `burn-tensor/src/bridge/`、`burn-dispatch/src/` |
| 5 | 到底在哪儿计算或提交计算？ | `burn-flex/src/ops/` 或 `burn-cubecl/src/ops/` |
| 6 | 训练与融合额外增加什么？ | `burn-autodiff/`、`burn-fusion/` |

表中路径均相对 `crates/`。先理解函数之间的输入输出，再看泛型和宏；宏负责生成重复代码，第一次遇到时先记录其用途即可。

这些 crate 的名字表达职责：`burn-nn` 组织神经网络模块，`burn-tensor` 提供张量接口，`burn-dispatch` 转发操作，`burn-backend` 定义后端契约，`burn-flex` 提供一种具体执行实现。同一名字的 `linear` 或 `matmul` 出现在不同 crate 并不一定是重复实现，而可能是不同层的入口。

### 先分清两条入口，避免把搜索结果拼成错误调用链

第 3 章直接写 Tensor 运算，第 4 章用 Linear 模块包装参数。它们表达相同的线性数学关系，但不要求逐个经过相同的公共函数：

```text
直接 Tensor 路线：
Tensor::matmul → Bridge 的浮点实现 → Dispatch::float_matmul
              → B::float_matmul

Linear 模块路线（普通浮点路径）：
Linear::forward → tensor::module::linear → Dispatch::linear
                → B::linear → 默认实现中的 B::float_matmul 等操作
```

具体后端可以覆盖线性操作的默认实现。**默认后端实现内部的 `B::float_matmul` 已位于后端层，不需要先重新包装成公共 Tensor 再从最外层分派一次。**下面第一、二站读 Linear 路线；第三站起切到直接 Tensor 路线，最后都观察所选后端怎样完成计算。

## 12.3 第一站：Linear 负责组织参数

```powershell
rg -n 'pub struct Linear|pub fn forward|let weight|linear\(' crates/burn-nn/src/modules/linear.rs
```

找到 `Linear::forward`：它通过 `self.weight.val()` 取得参数值，读取输入特征长度，并把输入、权重和可选偏置交给 `linear(...)`。`Param` 是参数包装，`val()` 取得用于本次运算的张量值。

此处先问：“输入最后一维是不是 2？权重第一维是不是 2？”我们的输入 `[1,2]` 与权重 `[2,2]` 相容，输出最后一维应变成权重的第二维 2。

注意 `Param` 是长期持有模型参数的包装，`val()` 交出本次运算使用的张量值，不是每次 forward 都重新随机初始化权重。初始化属于配置创建模块的阶段，加载属于把训练后的参数应用到模块的阶段，forward 则使用当前参数。

`forward` 不负责手写矩阵乘法循环，也不负责为每个输出挑选 GPU。找到这条职责边界，就完成了第一站。[固定源码](https://github.com/tracel-ai/burn/blob/v0.22.1/crates/burn-nn/src/modules/linear.rs)

## 12.4 第二站：张量函数如何表达线性运算

```powershell
rg -n 'pub fn linear|fn linear_impl|Dispatch::linear' crates/burn-tensor/src/tensor/module.rs
rg -n 'fn linear|float_matmul|float_add' crates/burn-backend/src/backend/ops/modules/linear.rs
```

先看公共 `linear` 与 `linear_impl` 的连接，再看后端默认组合。它们之间还经过分派层，不能把第二条命令理解成直接调用跳转。

默认线性实现可以用下面的**数学示意**理解，真实源码还处理批次、shape 变换和其他路径：

```text
product = matmul(input, weight)     // [1,2] × [2,2] → [1,2]
output = product + broadcast(bias) // 把 [2] 偏置用于这一行
```

**广播**是按形状规则复用较小张量的值，不要求在公共 API 中先创建很多份偏置。源码也可能把多个前导维度合并成矩阵行，改善矩乘形态，再把结果恢复为原 shape。

当前只追普通浮点、二维输入。遇到量化分支或高阶 shape 优化，先在笔记标注“另一路径”，等[第 9 章](./09-fusion-and-performance.md)以后再回来读。

## 12.5 第三站：Tensor 表示与矩乘入口

```powershell
rg -n 'pub struct Tensor|primitive: BridgeTensor' crates/burn-tensor/src/tensor/api/base.rs
rg -n 'pub fn matmul|TensorCheck::matmul|K::matmul' crates/burn-tensor/src/tensor/api/numeric.rs
```

公共类型是 `Tensor<const D: usize, K = Float>`：`D` 是阶数，`K` 是浮点、整数或布尔等类别。`Tensor<2>` 不表示每条轴长度都是 2；`[1,2]`、`[8,64]` 都是二阶张量。

`Tensor::matmul` 检查形状，再交给类别对应的矩乘实现。你会看到内部字段是 `BridgeTensor`，而不是直接暴露 `Vec<f32>`。张量可能位于 GPU，底层表示也可能保存设备缓冲区句柄。

0.22 的应用层没有 `Tensor<B,D>` 中的 `B`，但底层后端仍然可以使用泛型。旧教程与这里不同的原因见[资料与版本](./references.md)，不要把两套 API 拼在一个例子里。

第一次读实现可以把各类检查与运算分开标注：shape 检查回答“这次矩乘在数学上是否合法”，桥接与分派回答“把它交给谁”，具体后端回答“怎样算出来”。找到一项检查并不意味着它负责后面所有层的全部约束。

## 12.6 第四站：Bridge 和 Dispatch 各做什么

```powershell
rg -n 'fn matmul|Dispatch::float_matmul' crates/burn-tensor/src/bridge/ops/float.rs
rg -n 'backend_dispatch|fn float_matmul|B::float_matmul' crates/burn-dispatch/src/ops/tensor.rs
```

普通浮点矩乘的路径是 `Tensor::matmul → Float 的桥接实现 → Dispatch::float_matmul → 所选后端的 B::float_matmul`。返回时，结果逐层包装回公共张量。

**Bridge** 把具体底层表示藏在公共 API 后面，减少应用编译时暴露的复杂类型；**Dispatch** 根据张量已有的后端与上下文转发操作。两层不是每次都复制一遍数值，也不会每次重新寻找最快显卡。

`#[backend_dispatch]` 生成具体后端路由，所以上下文中会出现看似没有在函数局部声明的 `B`。第一次阅读先理解“这里调用对应实现”，以后再研究宏展开。[固定架构说明](https://github.com/tracel-ai/burn/blob/v0.22.1/contributor-book/src/project-architecture/tensor.md)

遇到陌生语法时，用第 2 章的读法逐个替换：`B::float_matmul` 是“类型 B 提供的矩乘”；`FloatTensor<B>` 是“B 的浮点底层表示”；`impl ... for ...` 是“为右侧类型提供这组能力”。先用这些中文句子重述调用，再追求读懂长泛型签名中的每个约束。

## 12.7 第五站：先读 CPU，再选 GPU 路径

```powershell
rg -n 'float_matmul|fn matmul' crates/burn-flex/src/ops/float.rs crates/burn-flex/src/ops/matmul.rs
rg -n 'fn float_matmul|MatmulStrategy' crates/burn-cubecl/src/ops/tensor.rs
```

Flex 是首个例子的纯 Rust CPU 后端。先看它把什么输入交给矩乘实现，再关注张量的布局、stride 和输出 shape；不要立刻深入 SIMD 指令等优化。

选择 CubeCL 路径时，Burn 的后端算子进入 kernel 和运行时设施。CubeCL 提供可编译执行的内核基础，不是一份模型文件；WGPU、CUDA 等路径由设备与已启用功能决定，概念见[第 8 章](./08-gpu-and-kernels.md)。

读到 `float_matmul` 不等于已经找到“GPU 正在做乘法”的那一行。还可能有算法选择、编译缓存、缓冲区管理、排队与提交；先画出这些职责所在的位置，再挑一个继续深入。

## 12.8 第六站：分别打开自动微分和融合

```powershell
rg -n 'fn float_matmul|struct Matmul|fn backward' crates/burn-autodiff/src/ops/tensor.rs
rg -n 'fn float_matmul' crates/burn-fusion/src/ops/tensor.rs
rg -n 'pub type Cube|Fusion<CubeBackend>' crates/burn-cubecl/src/lib.rs
```

先读自动微分：前向仍要算 `XW`，但在需要梯度时额外登记反向步骤及其所需信息。忽略广播细节，若上游梯度是 `G`，矩乘反向可先理解为 `dX = G Wᵀ`、`dW = Xᵀ G`；并不是重新训练一套后端。

再读融合：它可以先登记运算，在合适时机把部分操作一起优化执行。`Fusion<CubeBackend>` 表达“给 Cube 后端附加融合能力”；它不承诺把完整网络压成一个 kernel，也不同于求梯度的计算图。

为了避免混淆，分两次画图：一张标出前向数据与反向依赖，一张标出待执行算子、融合候选及实际提交。两者关注的问题不同，具体机制分别回到[第 6 章](./06-autodiff.md)和[第 9 章](./09-fusion-and-performance.md)。

## 12.9 反向追踪一次后端扩展

理解内置调用后，再带着第 11 章的 `y=x²+x` 看扩展机制。这里不必先读宏生成的全部代码，先找到三件事：允许选择哪些后端，怎样生成 Dispatch 路由，Fusion 怎样取得输出元数据。

```powershell
rg -n 'Flex|Cube|Capture' crates/burn-backend-extension/src/catalog.rs
rg -n 'backend_extension|ExtensionType|fusion' crates/burn-backend-extension/src/lib.rs
rg -n 'Dispatch|routing|fusion' crates/burn-backend-extension/src/extension.rs
```

再对照[官方专用内核示例](https://github.com/tracel-ai/burn/tree/v0.22.1/examples/custom-cubecl-kernel/src)：`lib.rs` 连接接口与 Tensor，`forward.rs` 提交前向，`kernel.rs` 定义设备计算，`backward.rs` 接上反向。每个文件负责的事情已经在[第 11 章](./11-custom-operators.md)分步解释。不要把“宏生成分派”当作“宏生成内核和导数”。

## 12.10 每读一站，留下四行笔记

记录“输入是什么、输出是什么、这里新增了什么责任、下一层去哪里”。例如 Bridge 站可写：输入是桥接张量；输出仍是桥接张量；新增类别与表示转发；下一层是 Dispatch。

如果卡住，先缩小问题：只追普通浮点、二维、单设备的一条路径。`rg` 搜索函数名后，再读函数前后的类型与注释；不要只凭命中行猜整个模块的行为。理解主线后，可按[第 11 章](./11-custom-operators.md)反向思考“新增一个操作需要改哪些层”。

搜索命令中的 `-n` 用来显示行号，`|` 在引号内是正则表达式的“或”；它们只帮你找位置，不能直接证明函数调用关系。应再打开命中文件，确认调用方传入了什么类型、被调用方法属于哪个 trait。没有 `rg` 时，用编辑器的全局搜索查同样的函数名即可。

一份可交付的小练习是：画出直接 Tensor 矩乘的四层路径，在每层写一条实际函数名和一个文件位置，再解释哪些地方只换表示、哪些地方可能登记工作、哪里真正计算。能完成这张图，就比读完许多优化代码但说不清输入去向更接近本章目标。

## 12.11 自测与下一步

1. `Tensor<2>` 能否在编译期保证输入 shape 是 `[1,2]`？
2. Bridge 解包是不是把 GPU 数值下载到 CPU？
3. Dispatch 的 `B::float_matmul` 为什么不能证明操作立刻执行？
4. 第一遍应该优先读宏展开，还是先画出完整调用方向？

**答案：**1. 不能，只约束阶数；2. 不是，可能只是取出设备数据的表示；3. 可能到达融合或其他排队实现；4. 先画调用方向，能用自己的话解释每层职责后再深入宏。

## 12.12 固定版本参考

- [Tensor 架构](https://github.com/tracel-ai/burn/blob/v0.22.1/contributor-book/src/project-architecture/tensor.md)、[Backend 架构](https://github.com/tracel-ai/burn/blob/v0.22.1/contributor-book/src/project-architecture/backend.md)：表示、分派与装饰器。
- [线性层默认组合](https://github.com/tracel-ai/burn/blob/v0.22.1/crates/burn-backend/src/backend/ops/modules/linear.rs)、[自动微分算子](https://github.com/tracel-ai/burn/blob/v0.22.1/crates/burn-autodiff/src/ops/tensor.rs)：把公式对应到实现。
- [CubeCL 后端入口](https://github.com/tracel-ai/burn/blob/v0.22.1/crates/burn-cubecl/src/lib.rs)、[Rust 版本声明](https://github.com/tracel-ai/burn/blob/v0.22.1/crates/burn/Cargo.toml)：后端组成与工具链基线。

下一章是[实验路线与后续计划](./13-learning-labs.md)。把这里的阅读任务变成小实验，每次只验证一个理解。
