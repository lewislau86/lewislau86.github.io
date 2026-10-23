# 资料、版本与术语

## 本书使用的版本

首版核对日期：**2026-10-23**。示例与源码阅读统一固定在 **Burn v0.22.1**，对应提交 [`907ab111a02c2dea47bc41633754f095c6b2220e`](https://github.com/tracel-ai/burn/commit/907ab111a02c2dea47bc41633754f095c6b2220e)。这是本次核对时 GitHub 标为 Latest 的稳定发布；以[发布页面](https://github.com/tracel-ai/burn/releases/tag/v0.22.1)和[该标签的 Cargo.toml](https://github.com/tracel-ai/burn/blob/v0.22.1/Cargo.toml)为准。

学习包使用 `version = "=0.22.1"` 固定直接依赖，并随包提供 `Cargo.lock` 固定依赖解析。Burn 包声明的最低 Rust 版本为 **1.95**，见[包配置](https://github.com/tracel-ai/burn/blob/v0.22.1/crates/burn/Cargo.toml)。网站构建与 Rust 实验是两类检查，验证范围分别记录在[第 13 章](./13-learning-labs.md)。

PyTorch 用作对照学习。第 14 章完整程序实测环境为 **Python 3.13.5、PyTorch 2.12.1+cpu**；主要 API 语义链接固定到 2.12 文档。核对时官方在线 `stable` 指向 2.14，其他章节的官方教程链接可能随网站更新。PyTorch 版本号与 Burn 版本号没有对应关系，不能用数字大小判断功能或速度。

## 三份引用资料各有什么作用

| 资料 | 适合用来做什么 | 阅读时需要留意什么 |
| --- | --- | --- |
| [《Burn 引擎深度解析》](https://book.longcipher.com/burn/) | 梳理后端、张量、自动微分、计算图和扩展点等主题 | 该站首页声明源码基准为 `91d892a4a`，其泛型后端讲法不能直接套用到 0.22 公共 API |
| [Burn Contributor Book](https://burn.dev/books/contributor/overview.html) | 理解设计理由和参与开发的方法 | 在线内容随项目变化；需要复现时读[固定标签的书稿](https://github.com/tracel-ai/burn/tree/v0.22.1/contributor-book/src) |
| [tracel-ai/burn](https://github.com/tracel-ai/burn) | 核对类型、函数、features、测试和示例 | 区分 `main`、发布标签与 crates.io 包版本 |

补充使用[固定版本的 Burn Book](https://github.com/tracel-ai/burn/tree/v0.22.1/burn-book/src)说明应用层用法。技术事实优先核对官方文档和源码；本书不逐章翻译第三方材料，也不把参考资料的性能主张当作本机测试结果。

## 两篇需要重点展开的官方文档

这两篇作为正文的核心依据，不只列作延伸链接。在线页面用于阅读，代码与实现细节统一核对 v0.22.1。

| 核心资料 | 在本书中怎样展开 | 固定版本依据 |
| --- | --- | --- |
| [Backend 架构](https://burn.dev/books/contributor/project-architecture/backend.html) | 第 5 章从小算例解释后端类型、运算接口、dtype、分派与自动微分装饰器，区分调用和实际完成 | [架构书稿](https://github.com/tracel-ai/burn/blob/v0.22.1/contributor-book/src/project-architecture/backend.md)、[后端源码](https://github.com/tracel-ai/burn/tree/v0.22.1/crates/burn-backend/src) |
| [Backend Extension](https://burn.dev/books/burn/advanced/backend-extension/index.html) | 第 11 章从可运行的 CPU 扩展讲到注册、求导、融合元数据、结构化输入输出，再读专用内核 | [扩展指南](https://github.com/tracel-ai/burn/blob/v0.22.1/burn-book/src/advanced/backend-extension/README.md)、[扩展宏源码](https://github.com/tracel-ai/burn/tree/v0.22.1/crates/burn-backend-extension/src) |

## 先避开几处版本混淆

| 主题 | 旧资料常见写法 | 本书的 0.22.1 写法或理解 |
| --- | --- | --- |
| 公共张量类型 | `Tensor<B, D>` | `Tensor<D>`，完整形式包含 kind 参数 |
| 模型定义 | `Model<B: Backend>` | 普通应用模型无需传播后端类型参数 |
| 选择后端 | 在应用类型中选择 `B` | Cargo 启用实现，`Device` 选择资源 |
| 自动求导 | 应用层 `Autodiff<B>` 类型切换 | 设备/张量携带运行时自动微分上下文；底层仍有装饰器 |
| CPU 起步 | `NdArray` | 本书用 `Device::flex()`；CubeCL CPU 是另一条实现路径 |
| 精度与形状 | 从泛型推测一切 | rank 和 kind 在类型里；轴长度、dtype、设备等在运行时 |
| 关闭训练 | 只看是否调用 `backward` | 区分梯度记录、参数可训练性与模块的训练状态 |

可参见[0.22 迁移说明](https://github.com/tracel-ai/burn/blob/v0.22.1/burn-book/src/migrating-to-0.22.md)和[固定版本张量架构说明](https://github.com/tracel-ai/burn/blob/v0.22.1/contributor-book/src/project-architecture/tensor.md)。本次读取 `main` 的包版本为 `0.23.0-pre.1`；正文不将开发分支的变化混入示例。

## 原理、阅读片段与实验的标记

**手算/示意**用于解释机制，未声称是 Burn 内部逐行实现。**阅读片段**省略完整项目环境，只帮助识别类型和调用。**CPU 学习包**包含第 3、4、6、11、14 章对应的完整 Cargo 项目，以及独立的 PyTorch 对照程序，实际执行状态见第 13 章。后端扩展的 CPU 组合实现和跨框架小算例已运行；Fusion、专用 GPU kernel 和模型导入目前是导读与实验计划。

同样，图中的箭头表示职责或调用方向，不承诺每次 API 调用都立即启动 kernel。自动微分图用于求梯度，融合记录用于组合计算；两者目的不同，不应把所有“图”当作一个固定的全模型静态图。

## 术语对照

| 英文 | 本书用语 | 首次阅读只需知道 |
| --- | --- | --- |
| rank | 阶数 / 轴的数量 | `[2, 3]` 有两条轴 |
| shape | 形状 | `[2, 3]` 表示每条轴的长度 |
| dtype | 数据类型 | 如 f32，影响存储和计算精度 |
| backend | 后端 | 张量运算的实现 |
| dispatch | 分派 | 将调用交给对应实现 |
| primitive | 底层张量表示 | 后端实际接收和返回的数据表示 |
| autodiff | 自动微分 | 按运算规则自动计算导数 |
| kernel | 核函数 | 执行底层数值计算的程序 |
| fusion | 算子融合 | 将适合合并的计算组合执行 |
| runtime | 运行时 | 管理执行资源与提交等工作的组件 |
| JIT | 即时编译 | 在运行过程中生成/编译执行代码 |
| checkpoint strategy | 求导检查点策略 | 为反向决定哪些中间值保存、哪些重算 |
| training checkpoint | 训练检查点 | 保存模型及所需训练状态，以便恢复训练 |
| batch | 批次 | 一次一起处理的若干样本 |
| reduction | 归约 | 沿指定轴求和、平均等，合并该轴上的元素 |
| gradient | 梯度 | 目标对各变量的局部变化率，不是自动更新指令 |
| upstream gradient | 上游梯度 | 最终目标传回当前输出的变化率 |
| stride | 步幅 | 沿一条轴移动一步，对应存储位置移动多少 |
| bandwidth | 带宽 | 单位时间可搬运的数据量 |
| serialization | 序列化 | 把状态编码成可以保存或传输的形式 |

## 推荐的原始阅读入口

- 第一次使用：[Getting started](https://github.com/tracel-ai/burn/blob/v0.22.1/burn-book/src/getting-started.md)。
- 框架结构：[Tensor](https://github.com/tracel-ai/burn/blob/v0.22.1/contributor-book/src/project-architecture/tensor.md)、[Backend](https://github.com/tracel-ai/burn/blob/v0.22.1/contributor-book/src/project-architecture/backend.md)。
- 后端扩展：[接口与分派](https://github.com/tracel-ai/burn/blob/v0.22.1/burn-book/src/advanced/backend-extension/README.md)、[CubeCL 内核](https://github.com/tracel-ai/burn/blob/v0.22.1/burn-book/src/advanced/backend-extension/custom-cubecl-kernel.md)、[WGPU 内核](https://github.com/tracel-ai/burn/blob/v0.22.1/burn-book/src/advanced/backend-extension/custom-wgpu-kernel.md)。
- 参数与状态：[Module](https://github.com/tracel-ai/burn/blob/v0.22.1/burn-book/src/building-blocks/module.md)、[Autodiff](https://github.com/tracel-ai/burn/blob/v0.22.1/burn-book/src/building-blocks/autodiff.md)。
- 执行效率：[Performance](https://github.com/tracel-ai/burn/tree/v0.22.1/burn-book/src/performance)。
- 复用模型：[Saving & Loading](https://github.com/tracel-ai/burn/blob/v0.22.1/burn-book/src/saving-and-loading.md)、[ONNX Import](https://github.com/tracel-ai/burn/blob/v0.22.1/burn-book/src/onnx-import.md)。
- PyTorch 对照：[张量](https://docs.pytorch.org/tutorials/beginner/basics/tensorqs_tutorial.html)、[自动微分](https://docs.pytorch.org/docs/2.12/notes/autograd.html)、[Linear](https://docs.pytorch.org/docs/2.12/generated/torch.nn.Linear.html)、[backward](https://docs.pytorch.org/docs/2.12/generated/torch.Tensor.backward.html)；按[第 14 章](./14-pytorch-comparison.md)的问题映射回 Burn。

不需要把这些资料一次读完。先读本书的一章，带着该章的问题去查对应入口，更容易判断自己正在看哪一层。
