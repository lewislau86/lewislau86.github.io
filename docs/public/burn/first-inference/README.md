# Burn 首次推理学习包

对应网站《深入理解 Burn 深度学习框架》第 3、4、6、11、14 章，固定 Burn 0.22.1。
本次验证使用 Rust/Cargo 1.98.1；Burn 本体声明最低 Rust 1.95，较旧工具链未在本次验证。
CPU Flex 后端，无需 GPU；首次构建需要联网下载依赖。

在本目录运行：

```sh
cargo run --locked --bin burn-first-inference
cargo run --locked --bin module
cargo run --locked --bin autodiff
cargo run --locked --bin backend_extension
cargo run --locked --bin comparison
```

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
```

程序内的断言检查形状、设备、前向结果、参数量与梯度。
第 11 章通过 backend_extension 宏注册接口，复用 Flex / Autodiff 的乘加操作计算 y=x²+x。
它验证后端扩展的连接，没有编写专用 kernel，也未启用 Fusion。
第 14 章的 comparison 验证主线前向、输入与参数梯度，并手动做一次 SGD 数学更新。
PyTorch 对照程序单独运行：

```sh
python -c "import torch; print(torch.__version__)"
python pytorch_compare.py
```

本次使用 Python 3.13.5、PyTorch 2.12.1+cpu。Python 环境与 Cargo 依赖分开管理。
若未安装 PyTorch，按 https://pytorch.org/get-started/locally/ 选择适合本机的 CPU 安装方式。
两个程序验证相同的手算值；Python 另验证 nn.Linear 的权重需要从主线 W 转置写入。
单步更新只是公式验证，不是优化器 API、完整训练收敛或文件保存加载测试。
这些小例子仅验证 CPU 基础执行，不代表 GPU、训练收敛、导入或性能已经验证。
验证环境与状态请查看网站第 13 章。
