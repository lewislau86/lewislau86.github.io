---
title: 序言：环境与工具链
description: 在 macOS、Linux 与 Windows 上安装 Rust、Cargo、编辑器和可选 Python/GPU 环境，并验证 Burn 学习包。
---

# 序言：环境与工具链

这本书的实验以 Rust 为主，CPU 上的 Flex 后端即可完成大部分章节；GPU、PyTorch 对照和 MLX 是可选路径。下面按“必须安装”“按需安装”“验证安装”三部分整理。命令在 macOS/Linux 的终端和 Windows 的 PowerShell 中分别给出；没有特别说明时，两者等价。

## 1. 必须安装：Rust、Cargo 与 C 工具链

Rust 通过 [rustup](https://rustup.rs/) 安装，Cargo 会随工具链一起安装。Burn 0.22.1 声明最低 Rust 1.95；本书验证使用 1.98/1.99，建议安装当前 stable。

### macOS

先安装 Xcode Command Line Tools（提供 `cc`、链接器和系统头文件）：

```sh
xcode-select --install
```

然后安装 rustup：

```sh
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
source "$HOME/.cargo/env"
rustup default stable
```

Apple Silicon 与 Intel Mac 都使用同一条命令；`rustup` 会自动选择 `aarch64-apple-darwin` 或 `x86_64-apple-darwin`。

### Linux

以 Debian/Ubuntu 为例，先安装编译工具和下载工具：

```sh
sudo apt update
sudo apt install -y build-essential curl pkg-config
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
source "$HOME/.cargo/env"
rustup default stable
```

其他发行版把 `apt install` 换成对应的包管理器即可；关键是要有 C 编译器、链接器和 `pkg-config`。

### Windows

1. 安装 **Visual Studio Build Tools**，勾选“使用 C++ 的桌面开发”工作负载，确保有 MSVC 链接器 `link.exe`。只装 VS Code 不够。
2. 安装 rustup：从 [rustup.rs](https://rustup.rs/) 下载 `rustup-init.exe` 并运行；也可以使用：

```powershell
winget install --id Rustlang.Rustup -e
```

3. 重新打开 PowerShell，确认 `rustc` 与 `cargo` 在 PATH 中。若使用 MSVC 工具链，`rustup` 会默认选择 `stable-x86_64-pc-windows-msvc`。

Windows 的长路径可能影响深层依赖构建；如果遇到路径过长错误，可在“设置 → 系统 → 开发者选项”中启用长路径支持，或把学习包解压到较短的目录（例如 `C:\burn-lab`）。

### 验证工具链

三个系统都运行：

```sh
rustc --version
cargo --version
rustup show active-toolchain
```

`rustc` 至少应为 1.95，建议 1.98 或更新。若提示 `cargo: command not found`，重新打开终端；macOS/Linux 也可以手动执行 `source "$HOME/.cargo/env"`。

可选安装格式化和静态检查组件：

```sh
rustup component add rustfmt clippy
```

它们不是运行本书实验的必需项，但提交代码或排查常见问题时很有用。

## 2. 按需安装：编辑器、Python 与 GPU

### 编辑器

推荐 VS Code 加 [rust-analyzer](https://rust-analyzer.github.io/) 扩展；它能补全类型、跳转定义并显示编译错误。也可以使用 RustRover、Neovim 或任何支持 LSP 的编辑器。本书不依赖特定编辑器。

### Python 与 PyTorch（第 15 章）

只有做 PyTorch 对照实验时才需要。建议使用独立虚拟环境，避免污染系统 Python：

```sh
python3 -m venv .venv
source .venv/bin/activate        # Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install torch
python -c "import torch; print(torch.__version__)"
```

Windows 上如果 `python3` 不存在，使用 `py -3` 或 `python`。PyTorch 的 CPU 版本即可完成第 15 章；CUDA/MPS 只影响可选计时。

### GPU（可选）

- **WGPU**：跨平台，macOS/Linux/Windows 都可用；Burn 的 `wgpu` feature 需要能创建图形设备。
- **CUDA**：仅 NVIDIA 显卡与对应驱动；需要安装 CUDA Toolkit，并确认 `nvidia-smi` 可用。
- **Metal/MPS**：Apple Silicon 上的 PyTorch 可选路径；Rust 侧通常走 WGPU/Metal。

本书的必做实验都在 CPU 上运行。第 8～10 章的 GPU 内容是“有设备时观察、没有设备时理解机制”，不要求先买显卡。不要在没有测量的情况下假定 GPU 一定更快。

## 3. 获取学习包并验证

从[第 3 章](./03-first-inference.md)或[第 14 章](./14-learning-labs.md)下载 `first-inference.zip`，解压到任意目录。所有命令都在解压后的目录（含 `Cargo.toml` 的那一层）执行：

```sh
cargo build --locked
cargo run --locked --bin burn-first-inference
```

预期输出包含：

```text
H = [5.0, 2.0]; shape = [1, 2]
```

首次构建会下载并编译依赖，耗时取决于网络与机器；之后的增量构建会快很多。`--locked` 要求使用包内 `Cargo.lock`，避免依赖版本漂移。

如果不想在站点目录里产生 `target/`，可以指定外部构建目录：

```sh
CARGO_TARGET_DIR=/tmp/burn-target cargo run --locked --bin burn-first-inference
```

Windows PowerShell：

```powershell
$env:CARGO_TARGET_DIR = "$env:TEMP\burn-target"
cargo run --locked --bin burn-first-inference
```

## 4. 常见问题

| 现象 | 先检查什么 | 处理 |
| --- | --- | --- |
| `cargo: command not found` | PATH 是否包含 `~/.cargo/bin` | 重开终端；macOS/Linux 执行 `source "$HOME/.cargo/env"` |
| 链接器找不到 / `link.exe not found` | 是否安装 C 工具链 | macOS 装 Xcode CLT；Linux 装 `build-essential`；Windows 装 MSVC Build Tools |
| 编译很慢或卡在下载 | 网络、代理、磁盘空间 | 先 `cargo build --locked` 单独构建；配置 Cargo 镜像或代理；确认至少有数 GB 空间 |
| `--locked` 报依赖变化 | 是否改过 `Cargo.toml` | 恢复原文件；学习包应整体解压，不要只复制部分文件 |
| GPU 示例无法初始化 | 驱动、feature、设备可用性 | 先跑 CPU 版本；WGPU/CUDA 的初始化错误与模型代码分开排查 |
| Windows 路径过长 | 解压目录层级 | 解压到较短路径，或启用长路径支持 |

## 5. 本书的实验约定

- 命令统一写成 `cargo run --locked --bin <名称>`；在 Windows PowerShell、macOS 和 Linux 中相同。
- 需要文件路径时使用相对路径（如 `artifacts/regression`），由程序创建目录，不依赖 `mkdir -p` 或 `rm -rf`。
- 计时实验先预热，再区分“提交”“执行”“读回”三个阶段；具体做法见[第 9 章](./09-how-execution-works.md)。
- 每章末尾的“本章实验”给出命令、预期输出和可修改的参数；没有 GPU 时按 CPU 路径完成。
- 验证环境与限制记录在[第 14 章](./14-learning-labs.md)，不把一次运行结果推广到所有硬件。

环境准备好后，从[第 0 章](./00-model-to-framework.md)开始；如果只想先跑通程序，可以直接去[第 3 章](./03-first-inference.md)，再回头补概念。
