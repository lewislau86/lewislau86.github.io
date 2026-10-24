# 第 11 章：权重导入与部署

[学习总览](./index.md) · [上一章：融合与性能](./10-fusion-and-performance.md) · [下一章：后端扩展与自定义算子](./12-custom-operators.md)

“我在别的工具里训练好了模型，怎样交给 Burn 预测？”先不要把模型理解成一个万能文件。一次可复现的预测，需要同时带齐**计算结构、参数权重、输入输出处理规则**。

本章以 **Burn 0.22.1** 为基线，先用原生回归模型验证“保存参数 → 新进程加载 → 预测一致”，再介绍其他迁移路线。ONNX 转换、GPU 与浏览器部分仍是阅读说明，尚未完成对应部署实验；验证记录见[第 14 章](./14-learning-labs.md)。

读完第 7 章，你已经知道怎样让训练模型进入推理模式；第 8～10 章解释了它在设备上怎样执行。本章接着解决“怎样把同一套计算和参数带到另一个程序”。第一次阅读先掌握 11.1、11.2 和 11.6；选定实际迁移路线后，再阅读对应的加载代码。

## 11.1 先把“模型”拆成三份

把我们的主线模型想成一张配方：先计算 `XW + b`，再做 ReLU。配方描述结构，`W` 和 `b` 是需要填进去的数，怎样把真实输入变成 `X` 则是预处理。

| 部分 | 主线例子 | 图像模型中的例子 |
| --- | --- | --- |
| 结构 | 线性层后接 ReLU | 卷积、归一化、激活的连接方式 |
| 权重 | `W = [[1,-1],[2,1]]`，`b = [0,1]` | 各层学到的参数，以及需要保留的状态 |
| 处理规则 | 输入是一行两个浮点数 | RGB 顺序、缩放、归一化、输出类别顺序 |

同样的权重配上错误的处理规则，也能正常运行，却给出错误结果。例如训练时把像素除以 `255`，部署时直接输入 `0..255`，就改变了模型看到的数据。

后处理也属于这份约定：两个输出究竟是回归值、分类分数，还是概率？我们的小模型输出 `[[5,2]]`，不能因为有两个数就把它叫作“两个类别的概率”。

这里再区分三个常被混用的词。**序列化**是把内存中的数值和必要说明写成文件；**编译**是把程序转换为目标机器可执行的形式；**部署**是把程序、参数及输入输出约定放进目标环境并验证。保存权重完成了第一项工作，不会同时完成后两项。

“checkpoint”也有不同上下文：训练 checkpoint 是用于恢复某个训练时刻的文件或状态集合，通常涉及模型、优化器、调度器以及应用自己的训练进度。第 12 章的 `CheckpointStrategy` 则决定反向传播时怎样保存或重算中间值，两者不是同一种对象。

## 11.2 三条导入路线，各自带来什么

| 路线 | 已经有什么 | 还需要做什么 |
| --- | --- | --- |
| 原生 Rust 模型 | 用 Burn 写好的结构和 `forward` | 加载匹配的权重，准备输入 |
| ONNX 导入 | 一个表达计算图、参数等信息的 ONNX 模型 | 转换为 Burn 的 Rust 代码，核对算子与输入约定 |
| PyTorch / SafeTensors 权重导入 | 命名张量及其数值 | 先实现对应 Burn 结构，再处理名称、布局与类型差异 |

**权重文件通常不能替你生成模型结构。** SafeTensors 主要存放张量，不会凭空还原 Python 的 `forward`。读取 PyTorch 参数也不等于执行 Python 对象中的任意代码。

如果只是学习，先选第一条：同一份 Burn 结构保存再加载。能证明这一步正确，再处理跨框架差异，问题会容易定位很多。

### 文件扩展名只能提供线索

| 常见文件 | 通常带有什么 | 读文件前仍要确认什么 |
| --- | --- | --- |
| `.bpk` | Burn 的参数记录或训练状态记录 | 对应哪种记录、哪套模型结构与版本 |
| `.safetensors` | 带名称、shape、dtype 的张量集合 | 哪个名称对应哪一层，是否需要布局适配 |
| `.pt`、`.pth` | 由保存代码决定，不能只看后缀判定 | 是否为导入器支持的权重组织形式 |
| `.onnx` | 计算图描述，通常还包含参数或参数引用 | 图的输入输出、opset、算子及外部数据是否齐全 |

PyTorch 的 `state_dict` 可以作为熟悉的参照：它把参数名映射到参数及注册 buffer 等张量，加载时仍要先有对应的模型类。`.pt`、`.pth` 只是常见命名约定，既可能保存参数字典，也可能保存其他 Python 对象。[PyTorch 保存与加载教程](https://docs.pytorch.org/tutorials/beginner/saving_loading_models.html)解释了这些区别。ONNX 参数也可以放在模型旁边的外部数据文件中，复制 `.onnx` 时应一并检查引用，见 [ONNX 外部数据说明](https://onnx.ai/onnx/repo-docs/ExternalData.html)。

**配置文件**还可能决定层数、隐藏维度、类别数等结构信息。即使参数都在，使用不同配置创建的模型也可能无法加载。保存格式里的 dtype 描述存储的数值类型；改文件后缀不会改变精度，也不会让后端自动获得某种低精度运算能力。

## 11.3 Burn 原生保存：把参数装进 burnpack

Burn 0.22 使用 **burnpack**，通常以 `.bpk` 为扩展名。可以把它理解成有目录的参数容器：目录说明张量的名字、shape 和 dtype，数据区放数值字节。

`ModuleRecord` 保存模块参数；`OptimizerRecord` 和 `LrSchedulerRecord` 分别保存优化器与学习率调度器的状态。只做推理通常不需要后两者，但恢复训练不能只靠一份模型权重。

下面是 API 阅读片段，假设 `model` 是已有模型，`model_config.init(&device)` 能创建同一结构：

```rust
use burn::{module::Module, store::ModuleRecord};

model.clone().into_record().save("tiny-model.bpk")?;
let record = ModuleRecord::load("tiny-model.bpk")?;
let loaded = model_config.init(&device).try_load_record(record)?;
let inference_model = loaded.valid();
```

这不是完整可运行程序：模型定义、配置、设备和返回错误的函数外壳需要由应用提供。关键顺序是“创建结构 → 读参数 → 应用参数 → 进入验证/推理模式”。

文件保存了参数，不会自动保存应用的预处理代码和类别表。模型拥有的 training flags 也不是 `ModuleRecord` 中的参数；加载后应显式决定运行模式。

### 用两个程序核对保存和加载

第 7 章的回归实验把这段流程补成两个可独立执行的程序。在[完整 CPU 学习包](/burn/first-inference.zip)目录中运行：

```sh
cargo run --locked --bin regression_train -- artifacts/regression
cargo run --locked --bin regression_verify -- artifacts/regression
```

`regression_train` 负责训练与写文件；它退出后，`regression_verify` 从指定目录读文件，创建 `Linear(1, 1)`，加载参数，再以推理模式计算。验证程序不依赖训练进程留下的对象，也不通过重新训练来得到相同输出。本例实际写出 `model_config.json`、`model.bpk` 和 `baseline.txt`，两个程序都接受同一个目录参数。

保存目录中的三类信息各有职责：

| 信息 | 用途 | 加载时的职责 |
| --- | --- | --- |
| 模型配置 | 输入、输出维度和偏置等结构约定 | 创建与记录匹配的模型结构 |
| `.bpk` 参数记录 | 训练得到的权重与偏置 | 替换新模型的初始化参数 |
| 基线预测 | 固定输入 `x`、解析目标与保存前预测 | 验证文件往返结果；不参与恢复参数 |

这个模型直接接收 `[N, 1]` 的浮点数，没有归一化和额外后处理。配置与程序共同定义这份约定，权重文件本身不会推断输入含义。应用更复杂时，预处理版本、类别表等也应随模型分发。

核对时既比较“加载后 vs. 保存前”，也比较“预测 vs. `2x+1`”。前者检验文件往返，后者检验这次训练的结果。具体文件名、误差阈值和运行记录见[第 14 章](./14-learning-labs.md#第三阶段-完成一个训练与保存闭环)。实验使用同一版本与 CPU 后端，不据此声称跨 Burn 版本、跨后端或跨精度仍有相同误差。

旧教程的 `.mpk`、`.bin`、JSON recorder 文件不能靠改扩展名变成 `.bpk`。应在能读取旧文件的 Burn 版本中加载并导出权重，再迁入 0.22；这条迁移路线不自动迁移旧优化器状态。

## 11.4 ONNX：先生成 Rust，再运行 Burn

**ONNX** 是描述机器学习计算的交换格式；图中的节点表示算子，连线表示张量怎样流动。**opset** 则是算子语义的版本集合，同名算子在不同版本中的参数约定可能不同。

Burn 的 `burn-onnx` 导入路线会生成 Rust 模型代码和权重文件。应用运行时执行生成的 Burn 代码，这条路线不要求把 ONNX Runtime 一起嵌进去。

这里的“图”描述前向计算依赖，与第 6 章记录反向步骤的求导图用途不同。例如 ONNX 的 MatMul 节点告诉导入器“这两个输入要做矩乘”，不表示文件已经带齐 Burn 的梯度实现或目标设备内核。

```text
训练工具导出 model.onnx
    → burn-onnx 解析与转换
    → 生成 Rust 模型代码 + .bpk 权重
    → Cargo 编译应用
    → Burn 后端执行预测
```

以下是官方构建脚本形式的片段，放在已有项目的 `build.rs` 中理解即可：

```rust
use burn_onnx::ModelGen;

fn main() {
    ModelGen::new()
        .input("src/model/tiny.onnx")
        .out_dir("model/")
        .run_from_script();
}
```

导入器作为构建依赖，生成代码所需的 `burn-store` 则是应用依赖。`burn-onnx` 独立发布；实践时应选择与 Burn 0.22 兼容的版本并保留 `Cargo.lock`，完整项目按官方导入指南配置。

`build.rs` 是 Cargo 在编译应用时运行的构建脚本。这里先在构建机器上读取 ONNX、写出 Rust 与 `.bpk`；随后 Rust 编译器编译生成的代码。生成结果位于 Cargo 的 `OUT_DIR`，不是默认写回 `src/model/`。应用需要通过官方示例中的 `include!(concat!(env!("OUT_DIR"), ...))` 把生成的 `.rs` 接进自己的模块。

运行时还要**真正加载生成的权重**。官方生成模型的 `Model::new(&device)` 只创建结构与初始化值，不能把它当作已经加载训练结果。桌面项目通常使用 `Model::from_file(path, &device)`；浏览器等环境可选择生成 `from_bytes`，再从取得的字节加载。构建目录中的绝对路径适合开发，分发程序时应明确安排权重位置或嵌入方式。

不要把“支持某个 opset”理解成“任何模型都能导入”。还要核对具体算子、属性值、输入组合、动态 shape，以及导出工具是否生成了自定义节点。失败时先看出错节点和生成代码，再决定改导出方式或补实现。

## 11.5 导入其他框架的权重：对齐比读文件更关键

`burn-store` 支持读取 PyTorch 权重和 SafeTensors 等格式，并提供参数名称映射、格式适配等能力。名称映射解决“它们是不是同一个参数”，布局适配解决“这些数怎样排列”。

一个容易漏掉的例子是线性层：Burn 的权重 shape 为 `[输入特征, 输出特征]`，计算 `XW`；PyTorch 的线性层权重通常是 `[输出特征, 输入特征]`，计算时使用转置。

这里描述的是两个框架的 Linear 模块参数约定，依据为 [Burn 固定版本 Linear 源码](https://github.com/tracel-ai/burn/blob/v0.22.1/crates/burn-nn/src/modules/linear.rs)与 [PyTorch Linear 文档](https://docs.pytorch.org/docs/stable/generated/torch.nn.Linear.html)。普通张量的矩乘本身并没有“框架不同就自动转置权重”的规则。

在我们的例子里，Burn 权重为 `[[1,-1],[2,1]]`，对应的 PyTorch 权重应为 `[[1,2],[-1,1]]`。两者都是 `2×2`，**只检查 shape 看不出转置错误**，还必须比较数值输出。

`PytorchStore` 自带 PyTorch 到 Burn 的适配；读取来自 PyTorch 的 SafeTensors 时，官方示例显式使用 `PyTorchToBurnAdapter`。不要对已转换的 Burn 权重再次手动转置。

下面是加载片段，需要已有的同结构模型与 `burn-store` 依赖：

```rust
use burn_store::{ModuleSnapshot, PyTorchToBurnAdapter, SafetensorsStore};

let mut store = SafetensorsStore::from_file("model.safetensors")
    .with_from_adapter(PyTorchToBurnAdapter);
model.load_from(&mut store)?;
let inference_model = model.valid();
```

初次迁移应保持完整参数校验。缺失参数时直接忽略错误，可能留下初始化参数，得到一个“能预测但不是原模型”的网络。部分加载适合有意替换分类头等场景，需要明确记录哪些参数没有加载。

## 11.6 怎样证明迁移后算对了

先保存一份原框架的固定输入与参考输出，再把**同一份已预处理数值**交给 Burn。主线输入 `[[1,2]]` 应依次得到 `XW = [[5,1]]`、加偏置 `[[5,2]]`、ReLU 后 `[[5,2]]`。

核对顺序是：输入 shape → 轴的含义 → dtype → 预处理 → 参数名称和布局 → 中间结果 → 最终输出。图像常见的 `NCHW` 表示批次、通道、高、宽；它与 `NHWC` 的轴顺序不同。

浮点比较使用容差：例如逐元素检查 `|实际值 - 参考值| ≤ atol + rtol × |参考值|`。`atol` 是接近零时的绝对误差余量，`rtol` 是相对误差余量；数值取值应依据 dtype、模型和任务要求。

例如参考值接近 `0` 时，只看相对误差会非常敏感，需要绝对误差余量。参考值较大时，相对项允许误差随数值尺度变化。先用高精度基线定位问题，再按任务要求选择容差，不能为让测试通过而无限增大容差。

先用 CPU 的浮点基线定位迁移问题，再评估 GPU 或低精度带来的数值差异。最终分类相同只能说明部分行为一致，中间数值错误可能暂时没有改变最大分数的位置。

## 11.7 部署分三步走

1. **本机 CPU**：用 `flex` 和 `Device::flex()` 跑固定样本，保存模型配置、权重、预处理与输出约定，先证明结果正确。
2. **本机或服务器 GPU**：启用对应后端，重新创建目标设备上的模型并加载同一份参数；用 `model.valid()` 和无 autodiff 的新输入核对输出，然后分别测启动耗时、传输耗时与稳定运行耗时。
3. **浏览器 Wasm**：Wasm 是浏览器可加载的编译目标，Flex 可走 CPU，WebGPU 可使用浏览器提供的 GPU 能力；还要接好 JavaScript 输入、权重获取、异步初始化与结果回读。

浏览器部署不只是替换一个设备构造函数：运行环境、构建目标、异步接口和支持的能力都要匹配。应从固定版本的 Web 示例开始；0.22.1 的 WebGPU 文档还包含一次性启动初始化要求，先理解示例再集成。

如果模型来自训练，保留原训练模型并创建 `model.valid()` 副本；仅给设备调用 `without_autodiff()` 不会修改已有模型。参见[第 7 章](./07-training-to-inference.md)。

## 本章实验

`regression_train` 与 `regression_verify` 验证“训练 → 保存 → 新进程加载”：

```sh
cargo run --locked --bin regression_train -- artifacts/regression
cargo run --locked --bin regression_verify -- artifacts/regression
```

第一条写出 `model_config.json`、`model.bpk`、`baseline.txt`；第二条只读文件重建模型。预期加载后与保存前的最大差为 `0.000000`，并输出 `OK`。没有保存优化器状态，所以这不等于精确恢复训练。

## 11.8 自测：能加载，就算部署成功了吗

1. 有一份 `.safetensors` 文件，就能自动得到任意模型的 `forward` 吗？
2. 权重是 `2×2`，Burn 和 PyTorch 之间是否可以省略布局核对？
3. ONNX 导入成功、Rust 编译通过，是否已证明预测和原模型一致？
4. 只带 `.bpk` 就能保证另一台机器复现相同的图像预测吗？

**答案：**1. 不能，还需要匹配结构；2. 不能，方阵转置后 shape 不变；3. 不能，还需固定输入和数值比较；4. 不能，还需结构、预处理、标签约定及兼容运行环境。

## 11.9 固定版本参考

- [保存和加载](https://github.com/tracel-ai/burn/blob/v0.22.1/burn-book/src/saving-and-loading.md)、[Record 与 burnpack](https://github.com/tracel-ai/burn/blob/v0.22.1/burn-book/src/building-blocks/record.md)：参数、训练状态和跨框架权重。
- [ONNX 导入](https://github.com/tracel-ai/burn/blob/v0.22.1/burn-book/src/onnx-import.md)：生成代码、依赖与兼容性边界；导入器的详细支持列表需随所选版本核查。
- [0.22 checkpoint 迁移](https://github.com/tracel-ai/burn/blob/v0.22.1/burn-book/src/migrating-to-0.22.md#migrating-checkpoints)、[WebAssembly](https://github.com/tracel-ai/burn/blob/v0.22.1/burn-book/src/advanced/web-assembly.md)：旧格式与浏览器环境的注意点。

下一章进入[自定义算子](./12-custom-operators.md)：当已有算子不能直接表达你的需求时，怎样逐层决定扩展位置。
