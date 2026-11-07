---
title: 环境准备
description: 安装 Rust 与系统编译工具，运行基础环境自检，明确模型和数据库的准备时机。
pageClass: learn-agent-rust-course
prev:
  text: 学习路径 · 能力演化
  link: /learn-agent-rust/learning-path
next:
  text: 课程架构与框架分工
  link: /learn-agent-rust/architecture
---

# 环境准备

[课程总览](./index.md) · [学习路径](./learning-path.md) · [下一篇：课程架构](./architecture.md)

::: tip 本章学习目标
- 准备 Rust、Cargo、格式化工具、Clippy 和系统链接器。
- 编译运行一个没有第三方依赖的小程序，确认基础工具链可用。
- 说明课程源码、模型服务与数据库分别在什么时候准备。

**前置：** 能打开终端、切换目录；Rust 语法可在后续章节中补齐。

**实践方式：** 下载<a href="/learn-agent-rust/code/check-environment.sh" download>环境自检脚本</a>，在 macOS、Linux 或 WSL 的 Bash 中运行。Windows 原生安装说明见下文。
:::

先让电脑编译出一个能打印文字的程序。这个过程会经过 Rust 编译器、Cargo 和系统链接器，能够尽早发现安装与路径问题。完成这一步后，再进入模型与工具循环的学习。

## 1. 现在需要准备哪些东西

![应用策略与图执行器位于 Rust 进程中，模型服务、会话存储和工作区从各自的边界接入。](/learn-agent-rust/figures/runtime-architecture.svg)

本页先准备图左侧 Rust 进程的运行环境。应用实现随章节加入，右侧外部服务在对应实验开始前配置。图表达课程目标结构，具体分工见[课程架构](./architecture.md)。

| 内容 | 何时准备 | 用途 |
| --- | --- | --- |
| Rust、Cargo、rustfmt、Clippy | 现在 | 编译、运行、格式化与静态检查。 |
| 系统 C 编译工具与链接器 | 现在 | 链接可执行程序，支持需要编译本地代码的依赖。 |
| Git、终端和文本编辑器 | 现在 | 阅读源码、记录修改并执行命令。 |
| 课程 Rust 工程与固定依赖 | 完成自检后进入 R02 | [R02 独立工程](./tools-and-graph.md)已提供工具链、锁文件与下载包。 |
| 支持工具调用的模型服务与凭据 | 真实模型实验前 | 在脚本模型实验通过后，验证请求、响应和工具协议。 |
| PostgreSQL | P01 等数据库实验前 | 验证检查点保存与跨进程恢复。 |

基础学习路线按 CPU 环境设计。本页自检只运行标准库程序，无需 GPU、模型密钥或数据库。首次安装 Rust 和后续首次获取 Cargo 依赖需要网络；运行时不请求模型，与安装阶段是否联网是两个条件。

## 2. 安装系统工具与 Rust

以下代码块是终端安装命令，按自己的操作系统执行。已经安装相应工具的读者可以直接进入自检。

### macOS

先检查命令行开发工具的位置：

```sh
xcode-select -p
git --version
```

若尚未安装，执行下面的命令并完成系统安装窗口：

```sh
xcode-select --install
```

然后按 [Rust 官方安装指引](https://www.rust-lang.org/tools/install)安装 rustup。rustup 管理工具链，`rustc` 编译源码，Cargo 管理工程与依赖：

```sh
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
```

完成后重新打开终端，让安装器写入的路径设置生效。

### Linux 与 WSL

先按发行版安装 C 编译工具、Git 和 curl。以下命令适用于使用 APT 的 Debian / Ubuntu 环境：

```sh
sudo apt update
sudo apt install build-essential git curl ca-certificates
```

然后执行上面的 rustup 安装命令，完成后重新打开终端。其他发行版按其包管理器安装 GCC 或 Clang 与链接器，具体参照 [Rust 安装章节](https://doc.rust-lang.org/book/ch01-01-installation.html)。

### Windows 原生环境

从 [Rust 官方安装页](https://www.rust-lang.org/tools/install)下载适合机器架构的 `rustup-init.exe`，按提示准备 MSVC 的 C++ 构建工具与 Windows SDK。详细步骤见 [MSVC prerequisites](https://rust-lang.github.io/rustup/installation/windows-msvc.html)。

本页自动自检脚本使用 Bash。Windows 原生环境可检查下节的版本命令；自动自检请在 WSL 内使用同一套 Linux 工具链。Windows 与 WSL 的 Rust 安装分别管理。

### 已有 rustup：准备 stable 工具链

以下命令为自检准备 stable 及其格式化、静态检查组件，不修改其他项目的工具链配置：

```sh
rustup toolchain install stable --profile minimal --component rustfmt --component clippy
```

编辑器使用自己熟悉的即可；需要补全、跳转和诊断时，可以启用其 Rust 支持。

## 3. 用一个临时工程做自检

::: info 源码与运行范围
完整代码只有一份：<a href="/learn-agent-rust/code/check-environment.sh" download>check-environment.sh</a>。下文片段直接从该脚本导入。脚本检查已有工具，创建临时工程，退出时清理临时目录；它不安装工具、不读取模型凭据，也不调用模型服务。
:::

将脚本下载到本地后，在保存它的目录运行：

```sh
RUSTUP_TOOLCHAIN=stable bash check-environment.sh
```

先看脚本打印的工具版本。下面的命令在脚本进程选定的同一工具链下执行；单独排查时，也可以运行 `rustup show active-toolchain` 查看当前选择：

<<< @/public/learn-agent-rust/code/check-environment.sh#versions

接下来创建一个 edition 2024 的 Cargo 程序，检查格式、编译运行并执行 Clippy。程序由 `cargo new` 生成，没有第三方 crate，适合用 `--offline` 检查基础编译链：

<<< @/public/learn-agent-rust/code/check-environment.sh#smoke

成功时，除各工具版本外，可以看到以下两行：

```text
Hello, world!
Environment check passed: Rust + Cargo + rustfmt + Clippy.
```

这里的通过条件是程序输出符合预期，并且格式检查与 Clippy 均成功退出。失败时脚本会停在具体命令处，可按下节的排查表处理。

## 4. 固定版本与课程依赖怎样准备

环境自检使用 stable 来确认基础安装。正式课程工程发布后，进入其根目录，优先遵循工程自带的 `rust-toolchain.toml` 和 `Cargo.lock`：前者选择 Rust 工具链，后者记录依赖解析结果。选择规则见 [rustup overrides](https://rust-lang.github.io/rustup/overrides.html)。

`langchain-rust` 与 `graph-flow` 是课程程序的库依赖，由 [R02 独立工程](./tools-and-graph.md)的 `Cargo.toml` 声明固定 Git revision，并通过 Cargo 获取。该工程固定 Rust 1.99.1、关闭两库的默认 feature，按 `Cargo.lock` 构建；进入工程后运行 `cargo run --locked`。本页基础自检仍只检查标准库程序，两库集成由 R02 单独验证。

现在可以下载 <a href="/learn-agent-rust/tools-and-graph.zip" download>R02 章节工程</a>，其中含源码、锁文件、工具链与运行说明，已在独立临时解压目录验证。读者无需复制作者电脑上的相邻仓库或个人路径。全课程学习包随后续章节补齐。

## 5. 模型与数据库按实验阶段配置

首批最小循环计划使用脚本模型：输入固定时返回预设的工具请求或最终消息，帮助观察控制流。真实服务实验会另行确认模型是否支持工具定义、结构化调用、调用 ID 和工具结果回传。

后续工程将明确读取以下配置。这里先说明含义，具体取值和加载方式随真实模型章节提供：

| 配置 | 要解决的问题 |
| --- | --- |
| `LLM_PROVIDER` | 选择经过课程验证的客户端适配路径。 |
| `LLM_MODEL` | 使用哪个具体模型，是否满足该实验的工具协议。 |
| `LLM_BASE_URL` | 请求发往哪个 API 地址，路径如何由客户端组装。 |
| `LLM_API_KEY` | 为该服务提供凭据；运行自检时不需要。 |

`.env` 是否自动加载由应用代码决定。课程工程提供 `.env.example` 后，再复制并填写本地配置；密钥放在本地配置或进程环境中，公开输出只保留脱敏结果。

PostgreSQL 的版本、连接串和初始化步骤将在数据库实验中一起给出。内存运行、脚本模型通过、真实模型通过和数据库恢复通过分别记录。

## 6. 常见安装问题

| 现象 | 先检查什么 |
| --- | --- |
| 找不到 `rustc` / `cargo` / `rustup` | 重新打开终端，确认 Unix 的 `~/.cargo/bin` 或 Windows 的 `%USERPROFILE%\.cargo\bin` 在 PATH 中。 |
| `linker cc not found` 或缺少 `link.exe` | 回到操作系统安装步骤，完成 C 工具链与链接器安装。 |
| 找不到 `fmt` 或 `clippy` 子命令 | 为实际使用的工具链安装 `rustfmt` 与 `clippy`，核对 `rustup show active-toolchain`。 |
| edition 2024 不受支持 | 核对是否选中了旧工具链，按本页命令准备 stable 后重跑自检。 |
| 工具链或依赖下载失败 | 检查网络、代理与证书；`--offline` 只使用本地已具备的工具和依赖。 |
| 自检成功，但课程工程构建失败 | 单独检查课程固定工具链、依赖与 feature，保留第一条错误；两项验证分别处理。 |

::: warning 常见误区
基础自检只证明 Rust 小程序可以在当前机器上编译运行。Agent 的工具协议、两库集成、真实服务和数据库恢复需要在对应章节另行验证。进入正式工程后，以工程工具链为准，避免用全局 stable 覆盖课程固定版本。
:::

## 本章结论

现在应具备终端、Git、Rust 编译器、Cargo 和所需检查工具，并能运行无第三方依赖的 Cargo 程序。后续按章节引入课程工程、模型和存储，每增加一层都保留自己的验证结果。

## 检查理解

1. 为什么已经装好 `rustc`，仍可能编译失败？

   <details><summary>参考答案</summary>

   编译可执行程序还需要系统链接器；部分第三方依赖也需要 C 编译工具。此外，工程可能指定其他工具链或依赖。先看失败命令和第一条错误，区分安装、版本与依赖问题。

   </details>

2. 自检使用 `--offline`，是否意味着第一次学习全程都不需要网络？

   <details><summary>参考答案</summary>

   自检程序没有第三方依赖，已安装的工具链可以完成它。首次安装 Rust、获取正式工程依赖，以及后续请求外部模型服务，都可能需要网络。课程的脚本模型实验强调运行时无需外部模型。

   </details>

3. 自检通过后，能否认为两库组合的 Agent 循环已经通过？

   <details><summary>参考答案</summary>

   自检只执行 Cargo 生成的小程序。两库的固定依赖、模型与工具消息、图路由和停止条件，需要在 R00–R02 的课程工程中逐项运行与核对。

   </details>

## 参考资料

- [Rust 官方安装指引](https://www.rust-lang.org/tools/install)
- [The Rust Programming Language：Installation](https://doc.rust-lang.org/book/ch01-01-installation.html)
- [rustup：Components](https://rust-lang.github.io/rustup/concepts/components.html)
- [rustup：Toolchain overrides](https://rust-lang.github.io/rustup/overrides.html)
- [Cargo：cargo new](https://doc.rust-lang.org/cargo/commands/cargo-new.html) 与 [cargo run](https://doc.rust-lang.org/cargo/commands/cargo-run.html)

下一篇：[课程架构与框架分工](./architecture.md)，把运行环境放回模型、工具与状态的数据流中。
