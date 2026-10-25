---
title: "第 4 章：阅读计算代码所需的 Rust"
description: "读懂所有权、trait、关联类型、宏和 Cargo feature。"
pageClass: burn-course
---

# 第 4 章：阅读计算代码所需的 Rust

[课程总览](./index.md) · [上一章](./tensors-and-memory.md) · [下一章](./gpu-programming.md) · [资料与版本](./references.md)

::: tip 本章学习目标
读懂所有权、trait、关联类型、宏和 Cargo feature。

**实践方式：** rust_basics：Rust 基础断言。历史验证范围统一见[实验索引](./learning-labs.md)。
:::

> 本章是首版导读，实验状态见[第 18 章](./learning-labs.md)；本书固定版本见[资料与版本](./references.md)。代码以阅读片段为主，完整运行步骤放在第 7 章。

本章不准备把 Rust 语法全部讲完。目标是看见一段 Burn 代码时，能分清“这是数学计算”“这是类型约束”以及“这是资源使用规则”。

特别注意版本：本书基线的公共张量写法是 `Tensor<2>`。旧教程里的 `Tensor<B, 2>` 把后端类型 `B` 放进公共泛型参数；不要把那套写法直接混进本书代码。[固定版本张量定义](https://github.com/tracel-ai/burn/blob/v0.22.1/crates/burn-tensor/src/tensor/api/base.rs)

如果只想尽快跑通第 7 章，先掌握 `let`、函数、`use`、移动与 `clone`、Cargo 即可。本章后半的 trait、关联类型和宏是阅读第 9、15 章的准备，可以在第一次遇到源码签名时回来重读。

## 先读懂一段最小函数 {#先读懂一段最小函数}

下面是普通 Rust，不需要 Burn：

```rust
fn add_one(x: f32) -> f32 {
    let y = x + 1.0;
    y
}
```

`fn` 声明函数；`x: f32` 表示参数 x 是 32 位浮点数；`-> f32` 表示返回值类型。`let y = ...;` 把表达式结果绑定到名称 y。最后一行 `y` 没有分号，表示把它作为函数结果返回；也可以明确写 `return y;`。

`let` 绑定默认不能被重新赋值，需要修改绑定时写 `let mut ...`。这不表示任何没有 `mut` 的对象内部都绝不可能变化；它首先是当前绑定可怎样使用的语言规则。读 Burn 时先关注函数参数按值接收还是借用，不必一开始研究全部内部可变性机制。[Rust 变量与函数](https://doc.rust-lang.org/book/ch03-03-how-functions-work.html)

## crate、模块和 use：先知道代码从哪里来 {#crate、模块和-use-先知道代码从哪里来}

crate 是 Rust 的编译单元，可以是库，也可以是可执行程序。Cargo 是常用的项目构建与依赖管理工具，`Cargo.toml` 描述项目和依赖。

模块（module）在 crate 内组织代码；`use` 把某条路径下的名称引入当前作用域。看到下面这行，可以读成“这份代码要使用 Burn 张量模块里的 Tensor 类型”：

```rust
use burn::tensor::Tensor;
```

源码仓库里会出现多个名字以 `burn-` 开头的 crate，它们把不同职责拆开。公共入口再次导出某些类型，因此用户代码中的路径不一定就是该类型最初定义的文件路径。

阅读源码时，沿着 `pub use` 找到实际定义即可。不要因为同一个名字经过多次导出，就以为运行时会把数据经过多层复制。[Rust 包与 crate](https://doc.rust-lang.org/book/ch07-01-packages-and-crates.html)

## const generic：Tensor 后面的 2 到底是什么 {#const-generic-tensor-后面的-2-到底是什么}

普通泛型使用类型作为参数，例如 `Vec<f32>` 是“保存 `f32` 的动态数组”。常量泛型（const generic）使用编译期常量作为参数，`Tensor<2>` 中的 `2` 就属于这种情况。

下面是语法示意，不是 Burn 的完整源码：

```rust
struct Grid<const D: usize> {
    dims: [usize; D],
}
```

`D` 是一个常量参数；`usize` 是用于索引和长度的整数类型；`[usize; D]` 表示长度为 `D` 的数组。`Grid<2>` 和 `Grid<3>` 是不同类型。

对应到张量，`D` 表示轴的数量，实际形状长度仍在运行时确定。两个 `Tensor<2>` 可能分别为 `[1, 2]` 和 `[3, 4]`，并不能因此相乘。类型系统提前排除一部分错误，算子仍要检查具体尺寸。[Rust 常量泛型](https://doc.rust-lang.org/reference/items/generics.html#const-generics)

下面这个阅读片段只把张量原样返回；它能用于不同阶数，但每次调用的输入和输出阶数必须一致：

```rust
fn identity<const D: usize>(x: Tensor<D>) -> Tensor<D> {
    x
}
```

`Tensor<2, Int>` 还会出现第二个类型参数，它表达张量种类。默认的浮点种类不等于在类型里固定某种浮点精度，具体 dtype 仍需结合运行时信息判断。

## 所有权：为什么算完后 x 不能再用 {#所有权-为什么算完后-x-不能再用}

Rust 用所有权（ownership）规则管理资源。对不具备隐式复制能力的值，赋值或按值传入函数通常会转移所有权，这叫移动（move）。移动不等于把整份设备数据复制到新位置。[Rust 所有权](https://doc.rust-lang.org/book/ch04-01-what-is-ownership.html)

张量操作经常按值接收张量句柄。先看一个阅读片段：

```rust
fn twice(x: Tensor<2>) -> Tensor<2> {
    x.clone() + x
}
```

这里需要两次使用 `x`，先 clone 一个句柄用于加法左侧，再把原句柄交给右侧。返回的是逐元素相加的结果。若把某个句柄交给会消耗它的操作，就不能继续把那个已移动的变量当作有效入口使用。

`clone()` 的含义由类型实现决定：对普通 `Vec` 往往会复制元素，对张量则不能直接等同于复制完整的设备缓冲区。读性能代码时，还要分析共享句柄如何影响后续缓冲区复用。

### 把一个常见编译错误完整走一遍 {#把一个常见编译错误完整走一遍}

下面是**故意不能编译**的阅读片段：

```rust
let y = x + x;
```

对于这里按值接收输入的张量加法，第一个 `x` 已把句柄交出去，第二个 `x` 又试图使用已移动的值，编译器会提示值已被移动。若加完不再需要原句柄，改为 `let y = x.clone() + x;`；若后面还需要 x，例如第 10 章要用它查询梯度，则写成 `let y = x.clone() + x.clone();`。

不要因此机械地给每个变量都加 clone。先看下一次是否仍需使用它，再保留必要的句柄。Rust 的检查帮助我们在编译阶段发现“继续使用已交出去的入口”，不是在推理时逐个检查变量名。

借用（borrowing）让函数暂时访问一个值，而不拿走所有权。`&device` 是共享借用；`&mut value` 是可变借用。它们首先是 Rust 资源访问规则，不是“把张量搬到设备”的指令。[Rust 引用与借用](https://doc.rust-lang.org/book/ch04-02-references-and-borrowing.html)

与 Python 对照时，`y = x` 通常给同一对象增加一个名称，原来的 x 还能使用；Rust 中一个不具备 `Copy` 的值按值赋给 y 后，原 x 会失效。两者的资源规则不同，所以照抄 PyTorch 的表达式时，数学相同也可能需要不同的句柄写法。PyTorch 的 `torch.clone(x)` 又是显式的数据复制操作，不能用于解释这里的 Rust clone 成本。[PyTorch clone](https://docs.pytorch.org/docs/stable/generated/torch.clone.html)

## struct、impl、Self：读懂后续的模型代码 {#struct、impl、self-读懂后续的模型代码}

`struct` 声明一组字段，`impl` 给这个类型增加函数或方法。继续使用普通 Rust 示意：

```rust
struct Scale {
    factor: f32,
}

impl Scale {
    fn new(factor: f32) -> Self {
        Self { factor }
    }

    fn apply(&self, x: f32) -> f32 {
        self.factor * x
    }
}
```

`Self` 在这里就是 `Scale`。`Scale::new(2.0)` 不需要一个已有对象，因此用 `::` 调用关联函数；得到 `scale` 后，`scale.apply(3.0)` 借用已有对象，因此通过点号调用方法。`&self` 说明这个方法借用对象，不会把整个 Scale 消耗掉。

把 `factor` 换成一个 `Linear` 字段，再把 `apply` 换成接收张量的 `forward`，就接近第 8 章的模型骨架。字段保存部件，方法组织计算；名字叫 `forward` 并不会让编译器自动推导网络结构。

## trait：把“具备什么能力”写进约束 {#trait-把-具备什么能力-写进约束}

trait 定义一组约定的行为。`T: SomeTrait` 可以读成“这里的类型 T 必须具备 SomeTrait 要求的能力”，它与面向对象语言的接口有相似之处。[Rust trait](https://doc.rust-lang.org/book/ch10-02-traits.html)

下面是纯教学示意，不是 Burn API：

```rust
trait Describe {
    fn describe(&self) -> String;
}

fn show<T: Describe>(value: &T) {
    println!("{}", value.describe());
}
```

`show` 不要求 T 是某个固定结构体，只要求它实现 `Describe`。你以后在底层源码看到 `B: Backend`，就可以先读成“B 是一种满足后端约定的类型”，再去查看约定有哪些能力。

本书版本把公共设备选择集中在 `Device`；底层后端实现仍使用 trait。新手写第一条推理时不必把底层 `B` 参数重新加回 `Tensor`。

## 关联类型：让实现选择配套的类型 {#关联类型-让实现选择配套的类型}

关联类型（associated type）是 trait 内部的类型占位符，具体实现决定它是什么。例如一个执行实现可以决定自己的设备表示和底层张量表示。[Rust 关联类型](https://doc.rust-lang.org/book/ch20-02-advanced-traits.html)

以下是对固定版本 `BackendTypes` 的删减阅读片段，省略了完整约束和其他关联类型：

```rust
trait BackendTypes {
    type Device;
    type FloatTensorPrimitive;
}
```

`type Device;` 不是创建一个设备对象，而是要求实现填写“配套的设备类型”。阅读 `B::Device` 时，可以理解为“B 选择的设备类型”。实际源码将这些关联类型放在 `BackendTypes` 中，并由后端能力约定继续使用。[固定版本 BackendTypes](https://github.com/tracel-ai/burn/blob/v0.22.1/crates/burn-backend/src/backend/base.rs)

这也解释了为什么源码中的具体底层类型很多，而面向用户的 `Device` 可以保持统一入口。公共接口与内部实现承担不同职责，阅读时要看清所在层次。

刚开始可把 `B::FloatTensorPrimitive` 记作“B 实现使用的底层张量类型”。等第 9 章追踪 `float_add` 时再展开它的约束；无需为了运行公共 `Tensor<2>`，提前实现一个新的 Backend。

## derive：让编译期代码生成替你写重复实现 {#derive-让编译期代码生成替你写重复实现}

`#[derive(...)]` 让编译器或过程宏为类型生成相应实现。以下是独立的 Rust 阅读片段：

```rust
#[derive(Clone, Debug)]
struct Label {
    text: String,
}
```

`Clone` 提供显式复制能力，`Debug` 支持调试格式输出。derive 发生在编译阶段，不是在每次预测时解析注解。Burn 也使用 derive 简化模型等结构的实现，后面介绍模型时再分析它生成了哪些能力。[Rust 可派生 trait](https://doc.rust-lang.org/book/appendix-03-derivable-traits.html)

## Cargo feature：编译哪些能力，与运行选哪台设备 {#cargo-feature-编译哪些能力-与运行选哪台设备}

feature 是 Cargo 的条件编译与可选依赖机制。它不是训练时从数据中学习到的“特征”。开启某个后端 feature，表示把相应能力编进程序；创建 `Device` 才表达代码选择的执行上下文。[Cargo features](https://doc.rust-lang.org/cargo/reference/features.html)

在本书版本中，默认 feature 不会自动提供执行后端；要明确选择所需后端。即使公共张量类型能被编译出来，也不能据此判断程序已经具有可用计算设备。具体依赖配置放在第 7 章，避免在这里引入第二套配置。[固定版本设备选择说明](https://github.com/tracel-ai/burn/blob/v0.22.1/crates/burn-tensor/src/device.rs)

同样，自动微分需要相应 feature，并通过设备的 `.autodiff()` 等接口配置。能创建普通推理张量，与为训练建立梯度计算环境，是不同步骤。

从文件到运行，可以按这条路径理解：

```text
Cargo.toml 声明直接依赖与 features
  → Cargo 解析整套依赖，Cargo.lock 记录选中的版本
  → Rust 编译源码与所需依赖
  → 运行可执行程序
  → 程序创建 Device、张量并执行计算
```

`cargo check` 主要检查代码能否通过编译分析，`cargo run` 还会构建并运行程序。`--locked` 要求使用现有锁文件且不能悄悄修改依赖解析；它不是关闭网络或跳过编译的开关。首次下载、编译和模型前向是不同阶段，第 7 章会把它们分开观察。[Cargo run](https://doc.rust-lang.org/cargo/commands/cargo-run.html)

## Option、Result 和 unwrap：看懂失败路径 {#option、result-和-unwrap-看懂失败路径}

`Option<T>` 表示“可能有一个 T，也可能没有”，常见分支是 `Some(value)` 与 `None`。`Result<T, E>` 表示“成功得到 T，或失败得到 E”，常见分支是 `Ok(value)` 与 `Err(error)`。这是类型的一部分，不是正常数字结果里的某个特殊值。

`unwrap()` 会取出成功值，遇到没有值或错误时使程序 panic。小实验里它能让失败立刻显现，生产代码则常用 `match` 或 `?` 把错误交给上层处理。第 7 章的 `try_to_vec::<f32>().unwrap()` 就是“尝试读取为 f32 数组，失败就终止这个教学程序”，不是保证任何 dtype 都能无条件转换。

这里的 `::<f32>` 是显式指定泛型参数的写法，常被叫作 turbofish。它告诉编译器“我要读取为哪种元素类型”；不会自行改变模型执行时的计算精度。[Rust 错误处理](https://doc.rust-lang.org/book/ch09-02-recoverable-errors-with-result.html)

## 读到什么程度可以继续 {#读到什么程度可以继续}

第一遍读 Burn 不需要掌握全部 Rust。下面这些“看到时不慌”即可；遇到不认识的语法，先回到这张表定位，再查 [The Rust Programming Language](https://doc.rust-lang.org/book/)。

| 你会看到 | 先这样读 | 主要出现在 |
| --- | --- | --- |
| `fn f<const D: usize>(...)` | 常量泛型，`D` 是编译期确定的阶数 | 第 3、4、7 章 |
| `B: Backend`、`impl Trait`、`where` | 对类型能力的约束，不是运行时对象 | 第 9、15 章 |
| `type FloatTensorPrimitive;` | 关联类型，由具体实现填写 | 第 9、15 章 |
| `#[derive(Module)]`、`#[derive(Config)]` | 编译期生成实现，不是每次前向都解析 | 第 8、14 章 |
| `&device`、`clone()` | 借用与句柄复制；不等于搬运整份设备数据 | 第 7、10 章 |
| `Option`、`Result`、`?` | 可能缺失、可能失败，以及向上传递错误 | 第 7、18 章 |
| `#[backend_extension(...)]` 等宏 | 生成 trait 实现与注册代码；先看它生成了什么职责 | 第 15 章 |

本章没有展开生命周期标注、`async`/`await`、宏展开细节和 `unsafe`。第 9、15 章遇到时可以先跳读，先回答“这段代码解决什么问题”，再回来补语法；不必在第一遍背下所有类型签名。

## 本章实验 {#本章实验}

`rust_basics` 是一个不依赖 Burn 的最小 Rust 程序，覆盖移动、`clone`、trait、`Option` 和 `Result`：

```sh
cargo run --locked --bin rust_basics
```

预期输出 `rect area = 6`、`String length = 4` 等。故意把 `let y = x;` 之后再次使用 `x`，再编译一次，观察借用检查器的报错；这比只读语法解释更能建立所有权直觉。

## 常见误解与自测 {#常见误解与自测}

**“类型里有数字，就说明所有形状都在编译期确定。”** `Tensor<2>` 固定阶数，矩阵的行数和列数仍需运行时检查。

**“Rust 是零成本抽象，所以 clone、搬运和同步都免费。”** 语言的抽象方式不消除计算和数据访问开销；必须区分具体操作做了什么。

1. `Tensor<2>` 与形状 `[2]` 的张量是一回事吗？
2. `&device` 会取得 device 的所有权吗？
3. 开启 GPU 后端 feature 后，能否只看类型就确认运行时使用了某块 GPU？
4. `fn forward(&self, x: Tensor<2>)` 中，对模型和输入张量分别采用什么接收方式？

::: details 简短答案
1. 不是。前者表示两条轴，后者只有一条轴、长度为 2。
2. 不会，它是共享借用。
3. 不能。还要检查设备创建方式与实际执行环境。
4. `&self` 借用模型，`x` 按值传入并把该张量句柄交给函数；函数可以继续把它交给算子。
:::

## 参考与下一步 {#参考与下一步}

- [The Rust Programming Language](https://doc.rust-lang.org/book/)：按需补充模块、所有权、trait 和泛型。
- [Cargo feature 文档](https://doc.rust-lang.org/cargo/reference/features.html)：核对依赖和编译能力的关系。
- [Burn v0.22.1 张量定义](https://github.com/tracel-ai/burn/blob/v0.22.1/crates/burn-tensor/src/tensor/api/base.rs)、[设备定义](https://github.com/tracel-ai/burn/blob/v0.22.1/crates/burn-tensor/src/device.rs)：核对本章公共接口。

下一章先把计算展开到 GPU：从向量加法的索引和数据流开始，理解工作怎样分配，再进入 Rust GPU 与 Burn 实践。
