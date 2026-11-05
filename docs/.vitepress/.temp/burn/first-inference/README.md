# Burn 首次推理学习包

对应网站《深入理解 Burn 深度学习框架》第 2～5、7～16 章的配套实验（第 17 章为源码阅读，第 18 章为实验索引），固定 Burn 0.22.1。
A–F 使用 Rust/Cargo 1.98.1 验证；G–O 在 macOS aarch64、Rust/Cargo 1.99.0 上运行或复跑。
Burn 本体声明最低 Rust 1.95，较旧工具链未在本次验证。
CPU Flex 后端，无需 GPU；首次构建需要联网下载依赖。

在本目录运行：

```sh
cargo run --locked --bin burn-first-inference
cargo run --locked --bin module
cargo run --locked --bin autodiff
cargo run --locked --bin backend_extension
cargo run --locked --bin comparison
cargo run --locked --bin regression_train -- artifacts/regression
cargo run --locked --bin regression_verify -- artifacts/regression
cargo run --locked --bin tensors
cargo run --locked --bin rust_basics
cargo run --locked --bin dispatch_path
cargo run --locked --bin optimizers
cargo run --locked --bin execution_trace
cargo run --locked --bin gpu_probe
cargo run --locked --bin fusion_measure
```

前五个程序打印一次推理、Module、求导、后端扩展与对照结果。`regression_*` 验证训练 → 保存 → 新进程加载：第一个训练 `Linear(1,1)` 拟合 `y=2x+1`，写出 `model_config.json`、`model.bpk`、`baseline.txt`；第二个只读文件重建模型并核对。回归示例把权重和偏置初始化为 `0.5`，让输出可以复现；这不是深层网络的通用初始化方式。

`tensors`、`rust_basics`、`dispatch_path`、`optimizers`、`execution_trace`、`gpu_probe`、`fusion_measure` 分别对应第 3、4、9、11、12、5、13 章。它们都只使用 CPU，命令在 macOS、Linux 和 Windows PowerShell 中相同；计时数字随机器变化，不构成性能基准。

预期分别包含：

```text
H = [5.0, 2.0]
Module H = [5.0, 2.0]; parameters = 6
dy/dx at x=3 = [7.0]
Flex forward: x=[-2, 0, 3], y=[2.0, 0.0, 12.0]
2D forward: shape=[2, 3], y=[2.0, 0.0, 12.0, 0.0, 2.0, 6.0]
Autodiff sum: dL/dx=[-3.0, 1.0, 7.0]
Autodiff weighted sum: g=[2, -1, 0.5], dL/dx=[-6.0, -1.0, 3.5]
H = [5.0, 2.0]; shape = [1, 2]
dX = [0.0, 3.0]; dW = [1.0, 1.0, 2.0, 2.0]; db = [1.0, 1.0]
weighted dX = [-6.0, -1.0, 3.5]
SGD w = [1.6]; loss after = [0.6399999]
step   1  loss = 16.296368
weights = [2.0000002]
bias    = [0.9999994]
predictions = [-3.000001, -1.0000008, 0.9999994, 2.9999995, 5.0, 7.0000005, 9.0, 11.0]
max |loaded - saved|  = 0.000000
max |loaded - target| = 0.000001
OK: reloaded model reproduces the baseline and the target function
A @ B = [22.0, 28.0, 49.0, 64.0]
rect area = 6
x device = Device<Flex(Cpu)>
SGD       final w =  3.00000  loss =   0.000000
```

数值示例用断言检查形状、设备、前向结果、参数量与梯度。`optimizers` 打印优化轨迹；`execution_trace`、`gpu_probe` 与 `fusion_measure` 打印计时观察，需要人工核对输出，不设置固定加速比或性能阈值。计时程序正常退出不能单独证明数值正确或优化有效。
第 15 章通过 backend_extension 宏注册接口，复用 Flex / Autodiff 的乘加操作计算 y=x²+x。
它验证后端扩展的连接，没有编写专用 kernel，也未启用 Fusion。
第 16 章的 comparison 验证主线前向、输入与参数梯度，并手动做一次 SGD 数学更新。
PyTorch 对照程序单独运行：

```sh
python -c "import torch; print(torch.__version__)"
python pytorch_compare.py
```

本次使用 Python 3.13.5、PyTorch 2.12.1+cpu。Python 环境与 Cargo 依赖分开管理。
若未安装 PyTorch，按 https://pytorch.org/get-started/locally/ 选择适合本机的 CPU 安装方式。
两个程序验证相同的手算值；Python 另验证 nn.Linear 的权重需要从主线 W 转置写入。
comparison 的单步更新只是公式验证。regression_train/regression_verify 另外验证 Burn 的 `SgdConfig` 优化器 API、小模型训练收敛与推理恢复；它们不保存优化器状态，因此不验证精确的训练恢复，也不代表 GPU、外部模型导入或性能已经验证。
验证环境与状态请查看网站第 18 章。
