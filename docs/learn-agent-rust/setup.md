---
title: 环境准备
description: 安装 Rust、graph-flow 与 langchain-rust，获取课程固定依赖，分别验证基础工具链与两库集成。
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
- 获取并编译 `graph-flow` 与 `langchain-rust`，核对课程固定版本与两库运行结果。
- 说明模型服务与数据库分别在什么时候准备。

**前置：** 能打开终端、切换目录；Rust 语法可在后续章节中补齐。

**实践方式：** 下载<a href="/learn-agent-rust/code/check-environment.sh" download>环境自检脚本</a>，在 macOS、Linux 或 WSL 的 Bash 中运行。Windows 原生安装说明见下文。
:::

先让电脑编译出一个能打印文字的程序。这个过程会经过 Rust 编译器、Cargo 和系统链接器，能够尽早发现安装与路径问题。完成这一步后，再进入模型与工具循环的学习。

## 下载全书实验代码

<a href="/learn-agent-rust/learn-agent-rust-experiments.zip" download>全书实验代码库（zip）</a>收录每章的完整工程、夹具、输出与 README。解压后运行 `python3 run.py list` 查看对应关系；先按本页安装环境，再用 `python3 run.py run R01` 或 `python3 run.py test R01` 运行。统一入口需要 Python 3.9+，只用标准库；各章仍可按自己的 README 独立执行。全部条件与逐章入口见[实验代码库索引](./experiments.md)。

## 1. 现在需要准备哪些东西

![应用策略与图执行器位于 Rust 进程中，模型服务、会话存储和工作区从各自的边界接入。](/learn-agent-rust/figures/runtime-architecture.svg)

本页先准备图左侧 Rust 进程的运行环境。应用实现随章节加入，右侧外部服务在对应实验开始前配置。图表达课程目标结构，具体分工见[课程架构](./architecture.md)。

| 内容 | 何时准备 | 用途 |
| --- | --- | --- |
| Rust、Cargo、rustfmt、Clippy | 现在 | 编译、运行、格式化与静态检查。 |
| 系统 C 编译工具与链接器 | 现在 | 链接可执行程序，支持需要编译本地代码的依赖。 |
| Git、终端和文本编辑器 | 现在 | 阅读源码、记录修改并执行命令。 |
| `graph-flow`、`langchain-rust` 与课程工程 | 完成基础自检后，按本页第 4 节准备 | 下载 R02 工程，通过 Cargo 获取并编译固定依赖；R00、R01 仍可独立运行标准库示例。 |
| 支持工具调用的模型服务与凭据 | 真实模型实验前 | 在脚本模型实验通过后，验证请求、响应和工具协议。 |
| PostgreSQL 18 服务端工具 | [P01 检查点实验](./postgres-checkpoints.md)前 | 在专用临时集群验证保存与跨进程恢复。 |

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
sudo apt install build-essential git curl ca-certificates unzip pkg-config libssl-dev
```

`unzip` 用于解压课程工程；`pkg-config` 与 `libssl-dev` 用于两库传递依赖中 OpenSSL 的发现和编译。然后执行上面的 rustup 安装命令，完成后重新打开终端。其他发行版按其包管理器安装 GCC 或 Clang 与链接器，具体参照 [Rust 安装章节](https://doc.rust-lang.org/book/ch01-01-installation.html)。

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

## 4. 安装 graph-flow 与 langchain-rust {#install-frameworks}

基础自检通过后，接下来把架构图中的两个库接进一个实际工程。这里的“安装”是**把库声明为项目依赖，由 Cargo 下载并编译**。`cargo install` 用于安装命令行可执行程序；本课程通过 `Cargo.toml` 使用这两个库。

| 库 | 在课程里负责什么 | 课程固定来源 | Rust 中的引用名 |
| --- | --- | --- | --- |
| `graph-flow` | 图节点、路由、会话与执行状态 | `a-agmon/rs-graph-llm`，revision `9bbca193f20a8c4ba23289621549ecb3d35fee64`；锁文件记录版本 `0.8.1` | `graph_flow` |
| `langchain-rust` | 模型接口、消息与工具调用数据 | `Abraxas-365/langchain-rust`，revision `5fc3f5aca4380da48829f95d6e2fd0217b1f2013`；锁文件记录版本 `8.0.0` | `langchain_rust` |

这些是当前课程工程验证过的源码版本。依赖名中的连字符在 Rust `use` 路径里写成下划线；版本核对以课程文件为准。

### 4.1 下载并解压课程工程

推荐先使用 <a href="/learn-agent-rust/tools-and-graph.zip" download>R02 章节工程 tools-and-graph.zip</a>。它已经包含源码、`Cargo.toml`、`Cargo.lock`、`rust-toolchain.toml` 和 README，无需提前克隆两个上游仓库。

macOS、Linux 与 WSL 可以在自己选定的学习目录执行以下命令。解压目标应是一个尚未存在的 `tools-and-graph` 目录：

```sh
curl -fL https://lewislau86.github.io/learn-agent-rust/tools-and-graph.zip -o tools-and-graph.zip
unzip tools-and-graph.zip
cd tools-and-graph
```

Windows 原生环境可通过上面的下载链接保存 zip，使用资源管理器“全部解压”，再在包含 `Cargo.toml` 的 `tools-and-graph` 目录打开 PowerShell。后续 Cargo 命令在各平台相同。若刚更新了本站而线上下载包尚未部署，先等待 Pages 发布完成。

如果已经克隆网站源码，直接进入仓库中的 `docs/public/learn-agent-rust/code/tools-and-graph/`，不必再下载一份。

### 4.2 选择工程固定的 Rust 工具链

在工程目录执行：

```sh
rustup toolchain install 1.99.1 --profile minimal --component rustfmt --component clippy
rustup show active-toolchain
rustc --version
```

本工程的工具链文件如下，直接引用下载包对应的原文件：

<<< @/public/learn-agent-rust/code/tools-and-graph/rust-toolchain.toml

在没有环境变量或显式命令覆盖时，进入这个目录，rustup 会按该文件选择 `1.99.1`。若仍显示 `stable` 或其他版本，先检查是否设置过 `RUSTUP_TOOLCHAIN`；也可用 `cargo +1.99.1 …` 为单条命令明确选择工具链。本页先前的 `RUSTUP_TOOLCHAIN=stable bash check-environment.sh` 只对那次脚本调用生效。

### 4.3 获取两个库及其传递依赖

仍在同一个工程根目录执行：

```sh
cargo fetch --locked
cargo build --locked
```

`cargo fetch --locked` 按现有锁文件获取 Git 源码和 registry 依赖；`cargo build --locked` 将它们和课程程序一起编译。首次执行需要网络与磁盘空间，终端可能长时间显示依赖下载或编译进度。两条命令均以退出码 0 结束，才完成“依赖已取得并可编译”的验收。

工程中的依赖声明直接引用这里的唯一来源：

<<< @/public/learn-agent-rust/code/tools-and-graph/Cargo.toml

读这份文件时注意三件事：

- `git` 指向源码仓库，`rev` 固定具体提交；Cargo 会在仓库中找到对应 crate，`graph-flow` 位于上游工作区的子目录。
- 两库都设置 `default-features = false`。课程按当前实验所需能力接入，暂时关闭默认 feature；数据库能力在后续实验单独启用和验证。
- `tokio`、`serde` 等依赖服务于课程程序。`Cargo.toml` 声明依赖要求，随包提供的 `Cargo.lock` 固定完整解析结果；复现时保留锁文件并使用 `--locked`。

Cargo 通常把下载的 registry 与 Git 源码缓存在 `~/.cargo/`，编译产物放在工程的 `target/`；配置了 `CARGO_HOME` 或 `CARGO_TARGET_DIR` 时位置会改变。读者无需手工把库复制进工程。

### 4.4 核对版本，再运行一次两库集成

先检查依赖树，确认当前工程实际使用的是哪两个库：

```sh
cargo tree --locked -i graph-flow
cargo tree --locked -i langchain-rust
```

输出应分别包含表中记录的 `graph-flow v0.8.1`、`langchain-rust v8.0.0`，Git 来源的提交缩写分别为 `9bbca193`、`5fc3f5ac`。如果显示其他来源或版本，先核对是否进入了下载包的工程目录，以及是否保留了原始 `Cargo.toml` 与 `Cargo.lock`。

然后运行实际调用两库的课程程序与测试：

```sh
cargo run --locked
cargo test --locked
```

默认运行会比较显式循环和 `graph-flow` 图执行的结果。以下是该工程验证脚本保存的完整输出；每种场景的 `equal=true` 表示两种实现的状态一致，正常场景还应出现从 README 读取的启动命令：

<<< @/public/learn-agent-rust/outputs/r02-summary.txt

这里的脚本模型实现了 `langchain-rust` 的模型接口，图版通过 `graph-flow` 实际调度节点。它使用程序自建的临时文件，无需 API Key、GPU 或 PostgreSQL。失败场景中的 `tool_error` 等停止原因是刻意触发的实验结果，具体含义在[第 2 章](./tools-and-graph.md)展开。

依赖和工具链已完整下载后，可以验证离线重跑：

```sh
cargo run --locked --offline
```

基础自检通过、两库编译通过、两库集成运行通过分别记录；以上步骤完成后，才可认为本机已准备好 R02 的课程环境。

第 7 章提供另一个可独立下载的<a href="/learn-agent-rust/skill-loading.zip" download>技能加载工程</a>，使用相同两库源码版本与工具链，并增加 YAML 解析和 SHA-256 依赖。进入其 `skill-loading` 目录，沿用本节的 `cargo fetch --locked`、构建与运行流程；具体场景见[第 7 章](./skill-loading.md)。

第 8 章提供独立的<a href="/learn-agent-rust/context-compaction.zip" download>上下文压缩工程</a>，使用相同工具链与两库源码版本。进入 `context-compaction` 目录，执行 `cargo fetch --locked`、`cargo run --locked` 与 `cargo test --locked`。Agent 与摘要器使用脚本模型，归档只写入自建临时目录；具体预算、对照场景和运行边界见[第 8 章](./context-compaction.md)。

第 15 章的<a href="/learn-agent-rust/agent-teams.zip" download>Agent 团队工程</a>沿用相同工具链与两库源码版本，启用 Tokio 的 `sync`、`time` 功能以支持有界邮箱、取消和等待。进入 `agent-teams` 目录，执行 `cargo fetch --locked`、`cargo run --locked` 与 `cargo test --locked`。实验只操作自建临时文件，使用脚本模型；具体场景与并发范围见[第 15 章](./agent-teams.md)。

第 16 章提供独立的<a href="/learn-agent-rust/team-protocols.zip" download>团队协作协议工程</a>。进入解压后的 `team-protocols` 目录，执行 `cargo fetch --locked`、`cargo run --locked` 与 `cargo test --locked`，固定 Rust 1.99.1 与 Tokio 1.54.1，另用 Serde、SHA-256 和 tempfile。它直接验证请求身份、计划审批、期限、关闭握手与队友回收，首次需下载依赖，运行时无需模型密钥、数据库、graph-flow 或 langchain-rust；实验范围见[第 16 章](./team-protocols.md)。

专题 2 提供独立的<a href="/learn-agent-rust/side-effect-reliability.zip" download>外部操作可靠性工程</a>。进入 `side-effect-reliability` 目录，执行 `cargo fetch --locked`、`cargo run --locked` 和 `cargo test --locked`。它固定 Rust 1.99.1，使用随工程编译的 SQLite，需要本机 C 编译工具链；无需安装数据库服务或配置 API Key。默认演示仅操作自建临时目录，独立客户端与 provider 进程通过本机 CLI JSON 通信；详细故障实验见[专题 2](./side-effect-reliability.md)。

### 4.5 自己新建项目时，怎样添加这两个库？

这一节用于想从空项目开始练习的读者。已完成上面课程工程安装的读者可直接进入下一节。在一个新的学习目录执行：

```sh
cargo +1.99.1 new --edition 2024 agent-lab
cd agent-lab
cargo +1.99.1 add graph-flow --git https://github.com/a-agmon/rs-graph-llm.git --rev 9bbca193f20a8c4ba23289621549ecb3d35fee64 --no-default-features
cargo +1.99.1 add langchain-rust --git https://github.com/Abraxas-365/langchain-rust.git --rev 5fc3f5aca4380da48829f95d6e2fd0217b1f2013 --no-default-features
cargo +1.99.1 build --locked
```

`cargo add` 将依赖写入新项目的 `Cargo.toml` 并解析依赖。此时新项目仍只有 Cargo 生成的 Hello World；还需要按 R02 接入模型、工具和图节点。新项目生成的传递依赖锁定结果可能与课程包不同，完整复现课程实验时使用原包及其 `Cargo.lock`，后续引入模型服务或数据库 feature 时再核对新增依赖。

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
| 提示找不到 `Cargo.toml` | 先 `cd tools-and-graph`，确认当前目录包含解压得到的 `Cargo.toml`。 |
| `failed to run custom build command for openssl-sys` | Debian / Ubuntu 安装 `pkg-config libssl-dev`，并核对系统链接器；其他平台按该平台原生 TLS 依赖的首条错误排查。 |
| `--locked` 提示锁文件缺失或需要更新 | 使用课程包原始 `Cargo.toml` 和 `Cargo.lock`；不要通过删锁文件来跳过复现要求。 |
| `--offline` 报缺少 crate 或 Git revision | 联网执行 `cargo fetch --locked`，再构建并离线重跑；同时确认工程固定工具链已安装。 |
| Git 依赖获取失败，但 `git` 命令可以正常访问上游 | 可尝试 `cargo --config net.git-fetch-with-cli=true fetch --locked`，让 Cargo 使用系统 Git 获取源码，再检查代理与证书配置。 |
| 自检成功，但课程工程构建失败 | 单独检查课程固定工具链、依赖与 feature，保留第一条错误；两项验证分别处理。 |

::: warning 常见误区
基础自检只证明 Rust 小程序可以在当前机器上编译运行。Agent 的工具协议、两库集成、真实服务和数据库恢复需要在对应章节另行验证。进入正式工程后，以工程工具链为准，避免用全局 stable 覆盖课程固定版本。
:::

## 本章结论

现在应能完成两层验收：基础工具链可运行标准库程序；课程工程可按锁文件获取并编译 `graph-flow`、`langchain-rust`，运行两库集成用例。之后再按章节引入真实模型和存储，每增加一层都保留自己的验证结果。

## 检查理解

1. 为什么已经装好 `rustc`，仍可能编译失败？

   <details><summary>参考答案</summary>

   编译可执行程序还需要系统链接器；部分第三方依赖也需要 C 编译工具。此外，工程可能指定其他工具链或依赖。先看失败命令和第一条错误，区分安装、版本与依赖问题。

   </details>

2. 自检使用 `--offline`，是否意味着第一次学习全程都不需要网络？

   <details><summary>参考答案</summary>

   自检程序没有第三方依赖，已安装的工具链可以完成它。首次安装 Rust、获取正式工程依赖，以及后续请求外部模型服务，都可能需要网络。课程的脚本模型实验强调运行时无需外部模型。

   </details>

3. 为什么添加 `graph-flow` 和 `langchain-rust` 使用 `cargo add` 或 `Cargo.toml`，而不使用 `cargo install`？

   <details><summary>参考答案</summary>

   这里需要的是供 Rust 程序引用的库依赖。`cargo add` 修改项目依赖声明，构建时 Cargo 下载并编译这些库；`cargo install` 用于安装可执行程序。复现本课程时，直接使用原始工程与锁文件。

   </details>

4. 自检通过后，能否认为两库组合的 Agent 循环已经通过？

   <details><summary>参考答案</summary>

   自检只执行 Cargo 生成的小程序。还要按第 4 节获取固定依赖、编译并运行 R02 两库工程，核对模型与工具消息、图路由和停止条件。R00、R01 的标准库示例可独立运行。

   </details>

## 参考资料

- [Rust 官方安装指引](https://www.rust-lang.org/tools/install)
- [The Rust Programming Language：Installation](https://doc.rust-lang.org/book/ch01-01-installation.html)
- [rustup：Components](https://rust-lang.github.io/rustup/concepts/components.html)
- [rustup：Toolchain overrides](https://rust-lang.github.io/rustup/overrides.html)
- [Cargo：cargo new](https://doc.rust-lang.org/cargo/commands/cargo-new.html) 与 [cargo run](https://doc.rust-lang.org/cargo/commands/cargo-run.html)
- [Cargo：声明 Git 依赖](https://doc.rust-lang.org/cargo/reference/specifying-dependencies.html#specifying-dependencies-from-git-repositories)、[cargo add](https://doc.rust-lang.org/cargo/commands/cargo-add.html) 与 [cargo fetch](https://doc.rust-lang.org/cargo/commands/cargo-fetch.html)
- [Cargo：cargo install](https://doc.rust-lang.org/cargo/commands/cargo-install.html)：用于安装可执行程序。
- [graph-flow 固定源码](https://github.com/a-agmon/rs-graph-llm/tree/9bbca193f20a8c4ba23289621549ecb3d35fee64/graph-flow) 与 [langchain-rust 固定源码](https://github.com/Abraxas-365/langchain-rust/tree/5fc3f5aca4380da48829f95d6e2fd0217b1f2013)

下一篇：[课程架构与框架分工](./architecture.md)，把运行环境放回模型、工具与状态的数据流中。

## Agent RSI 专题的独立环境 {#rsi-lab}

[专题 6](./agent-rsi.md)使用 Rust 1.99.1 标准库，不增加 Cargo 依赖，不需要模型密钥或数据库。解压[学习包](/learn-agent-rust/agent-rsi-lab.zip)后进入 agent-rsi，先运行 `cargo test --locked --offline`，再按 README 用尚不存在的临时目录运行七类场景。指定工具链首次安装需要网络，实验本身离线运行。

下载包实现的是有界策略搜索、固定验收与发布回滚；递归元改进属于后续研究边界。课程基线与最新一手资料的差异统一记录在[技术跟踪](./technology-radar.md)，不要为了追随版本号直接改动所有学习包。
