---
title: "从零编译 NautilusTrader：Rust 与 Python 两部分"
description: 在一台干净的 macOS 或 Ubuntu 机器上，从安装工具链开始，分别编译并运行 NautilusTrader 的 Rust 部分（cargo 直接跑回测示例）和 Python 部分（make build-debug 生成扩展模块），并解释每一步背后在做什么。
---

# 从零编译 NautilusTrader：Rust 与 Python 两部分

[全书目录](./index.md) · [上一章](./nautilus-architecture.md) · [下一章](./architecture.md)

::: tip 本篇目标
从一台只装了操作系统的机器开始，走完两条路：

- **Rust 部分**：不装 Python，用 `cargo` 编译一个 crate、跑通 `engine-ema-cross` 回测示例、跑单元测试；
- **Python 部分**：用 `make build-debug` 编出 `nautilus_trader._libnautilus` 扩展模块，在 `python/.venv` 里导入它，跑通一个 Python 回测示例。

每一步都说明它在做什么、产物放在哪里、出错时先查什么。

**源码版本：** `develop` 分支，提交 `5997d82`（2026-11-17）。命令取自同一提交的 `Makefile`、`docs/getting_started/installation.md`、`docs/developer_guide/environment_setup.md` 和 `python/README.md`。项目的构建脚本改动很频繁，命令跑不通时先对照这几个文件。
:::

本篇以 macOS（Apple Silicon）和 Ubuntu 22.04 及以上为主，这也是官方 CI 覆盖的平台（另有 Windows Server 2022 及以上，见第 6 节）。Linux 上先用 `ldd --version` 确认 glibc 不低于 2.35。

## 1. 先看全貌：要装什么，编出什么

![从零编译的两条流水线：上方是共用的 rustup 工具链、Cargo.lock 和依赖冷却期检查；左边 Rust 部分直接用 cargo 编译、运行示例和测试；右边 Python 部分由 make build-debug 依次执行 make sync、生成类型存根、maturin develop 编译扩展模块，再在 python/.venv 里运行](/nautilus-trader/figures/build-pipeline.svg)

怎么读这张图：两条路共用同一个 Cargo 工作区和同一个 `target/` 目录，区别在于编什么、用哪组 feature。

- **Rust 部分**按需编译：`cargo build -p <crate>` 只编这个 crate 和它的依赖，默认 feature 很少，不碰 Python。
- **Python 部分**一次编全：`make build-debug` 用 `python/pyproject.toml` 里 `[tool.maturin]` 列出的整组 feature（`extension-module`、`arrow`、`high-precision`、`redis`、`postgres`、`defi`、`hypersync` 等，外加 `pyo3` crate 默认打开的全部适配器）编出一个扩展模块。生成类型存根那一步还会用几乎同一组 feature（去掉 `extension-module`、补上 `nautilus-interactive-brokers/gateway`）再编一个 `python-stub-gen` 可执行文件。所以第一次构建 Python 部分，比只编 Rust 部分慢得多。

需要准备的东西：

| 工具 | 版本从哪里来 | 用途 | 必需？ |
| --- | --- | --- | --- |
| C 工具链 | macOS：Xcode 命令行工具；Ubuntu：`build-essential clang lld pkg-config` | 编译依赖里的 C 代码、链接 | 必需 |
| `git`、`make` | 系统自带或包管理器 | 取源码；所有构建入口都在 `Makefile` | 必需 |
| rustup + Rust | `rust-toolchain.toml` 锁定 `1.100.0`，rustup 自动安装 | 编译全部 Rust 代码 | 必需 |
| uv | `python/pyproject.toml` 要求 `>=0.13,<0.14` | 管 Python 解释器和依赖 | Python 部分必需 |
| Python | `requires-python = ">=3.13,<3.16"`，uv 可自动下载 | 运行 Python 包 | Python 部分必需 |
| maturin | `python/pyproject.toml` 的 `dev` 依赖组锁定 `1.16.0`，`make sync` 自动装 | 把 Rust 编成 Python 扩展 | 自动安装 |
| cargo-nextest 等 | `make install-tools` 按仓库的版本表安装 | 仓库的测试目标用 nextest 跑 | 跑测试时需要 |
| Cap'n Proto | `./scripts/install-capnp.sh` | 只在开发 HyperSync 模式定义时用；正常构建不重新生成它的代码 | 不需要 |

依赖的规模：`Cargo.lock` 里有 937 个包，其中 48 个是工作区自己的 crate，889 个来自 crates.io（锁文件覆盖所有平台，有些只在别的平台用到）；`python/uv.lock` 里有 72 个包。第一次构建的大部分时间花在下载和编译当前平台、当前 feature 用到的那几百个 Rust 依赖上。

## 2. 准备机器

### 2.1 系统工具

::: code-group

```bash [macOS]
xcode-select --install
```

```bash [Ubuntu]
sudo apt-get update
sudo apt-get install -y build-essential clang lld curl git make pkg-config patchelf
```

:::

Ubuntu 上的 `lld` 不能省。仓库的 `.cargo/config.toml` 给 Linux 目标写死了 `-C link-arg=-fuse-ld=lld`，这组参数对依赖的构建脚本和过程宏同样生效，所以没装 `lld` 时，第一个需要链接的东西就会失败，构建几乎一开始就报错。`patchelf` 是 `python/README.md` 列出的 Linux 前置依赖，maturin 用它给编出的扩展模块设置 rpath；官方的快速安装命令里没有它，这里一并装上。

### 2.2 Rust

```bash
curl https://sh.rustup.rs -sSf | sh
source "$HOME/.cargo/env"
```

这里装的 rustup 默认工具链是什么版本并不重要。仓库根目录有一个 `rust-toolchain.toml`：

```toml
[toolchain]
channel = "1.100.0"
```

在仓库目录里第一次运行 `cargo` 或 `rustc` 时，rustup 会读这个文件，自动下载并切换到 1.100.0。之所以锁得这么死，是因为 `.cargo/config.toml` 里有两行：

```toml
# 示意，节选自 .cargo/config.toml
[build]
warnings = "deny"

[target.'cfg(all())']
rustflags = ["-Dwarnings"]
```

所有警告都当成错误。换一个更新的编译器，新增的 lint 就可能让整个工作区编不过。所以不要用 `cargo +stable` 之类的方式绕开锁定的版本。

### 2.3 uv

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"
uv --version
```

`python/pyproject.toml` 的 `[tool.uv]` 写了 `required-version = ">=0.13,<0.14"`，版本不在这个区间时 `make sync` 会直接报错。版本不对就在仓库里运行 `make install-uv`，它会装上仓库锁定的那个版本。

### 2.4 取源码

```bash
git clone --branch develop --depth 1 https://github.com/nautechsystems/nautilus_trader
cd nautilus_trader
rustc --version    # 应当显示 rustc 1.100.0，第一次会先下载工具链
```

`--depth 1` 只取最新一个提交，适合只想编译和阅读的场景。克隆下来的目录里，第 0 章讲过的 `crates/`、`python/` 都在，另外还有 Python 示例要用的 `test_data/` 和 `docs/tutorials/`。

## 3. Rust 部分：不经过 Python

### 3.1 平台差异都写在 `.cargo/config.toml` 里

| 目标平台 | 额外的链接参数 | 作用 |
| --- | --- | --- |
| Linux | `-fuse-ld=lld`、`--gc-sections`、`--as-needed`、`-z norelro`、`relocation-model=pic` | 用 lld 加快链接，去掉没用到的段和库 |
| macOS（x86_64、aarch64） | `-undefined dynamic_lookup` | 允许 Python 扩展模块里留下未解析的 Python 符号，加载时由解释器提供 |
| Windows（MSVC） | `+crt-static` | 静态链接 C 运行时 |

macOS 那一条是为 Python 扩展准备的：扩展模块不应该链接某一个具体的 `libpython`，而是在被解释器加载时再去找符号。它对所有 macOS 链接都生效，对符号都能解析的程序没有实际影响，只是缺符号时会从链接错误变成运行时加载错误。

macOS 上还有一个只在直接用 `cargo` 时才会遇到的坑。`[build] warnings = "deny"` 让构建过程中的所有警告都算失败，而 Apple 的链接器在链接很大的 Rust 程序时可能输出 compact-unwind 相关的警告。`Makefile` 在 macOS 上会为编译类目标自动设置 `CARGO_BUILD_WARNINGS=warn`（Rust 源码的警告仍由 `-Dwarnings` 拦下）；直接用 `cargo` 时，遇到这类链接器警告导致失败，在命令前加同样的变量：

```bash
export CARGO_BUILD_WARNINGS=warn   # 只在 macOS 上需要
```

### 3.2 先做一次依赖冷却期检查

仓库对依赖版本有一条供应链规则：`.cargo/config.toml` 里设置了 `min-publish-age = "3 days"`，发布不满冷却期的新版本不会被解析进来；`scripts/check-cargo-cooldown.sh` 还会逐一核对 `Cargo.lock` 里每个版本的发布日期。`Makefile` 里所有会编译 Rust 的目标都先跑这个检查，直接用 `cargo` 就绕过了它。官方开发指南的建议是：直接用 `cargo` 之前先跑一次检查，并且总是带上 `--locked`。

```bash
make check-cargo-cooldown
```

它会对照 `origin/develop` 这个引用做校验。按上面 `--depth 1 --branch develop` 克隆，`origin/develop` 是存在的，检查会正常对照它。完整克隆却缺少 `origin/develop` 时检查会失败，需要先 fetch；浅克隆里解析不到它时，脚本会打印一条 NOTE，改为信任 `.supply-chain/crate-dates.json` 里记录的日期。

### 3.3 编一个 crate，验证工具链

```bash
cargo build --locked -p nautilus-model
```

产物在 `target/debug/`。这一步只编 `nautilus-model` 和它依赖的 `nautilus-core`、`nautilus-macros` 以及第三方包，很快就能确认编译器、链接器都正常。

开发构建用的是 `Cargo.toml` 里的 `[profile.dev]`：工作区自己的 crate 用 `opt-level = 0`，第三方依赖用 `opt-level = 1`（依赖很少重编，多花一点编译时间换来更快的测试和运行），并且关掉了调试信息来加快编译。

### 3.4 跑一个回测：`engine-ema-cross`

```bash
cargo run --locked -p nautilus-backtest --example engine-ema-cross --features examples
```

这个示例在 `crates/backtest/examples/engine_ema_cross.rs`。`crates/backtest/Cargo.toml` 给它声明了 `required-features = ["examples"]`，所以必须带上 `--features examples`；这个 feature 会打开 `nautilus-trading/examples`，示例策略 `EmaCross` 就在那里。

它做的事很简单，正好对应第 1 章讲的回测外壳：

1. 用 `BacktestEngine::new` 建一个回测引擎；
2. `add_venue` 加一个名为 `SIM` 的模拟交易所：保证金账户、对冲式仓位（`OmsType::Hedging`）、L1 订单簿、初始资金 1,000,000 USD、手续费为零；
3. 加一个标的 `AUD/USD`（来自 `nautilus-model` 的测试桩 `audusd_sim()`，通过 dev-dependency 的 `test-support` feature 引入）；
4. 加一个快线 10、慢线 20 的 `EmaCross` 策略，每次下单 100,000；
5. 自己生成 745 条报价：先是 25 条平价报价，让两条均线收敛，然后重复 6 轮“40 步上涨、80 步下跌”，制造多次交叉；
6. `engine.run(...)` 跑完。

终端里会看到引擎和策略的日志，程序正常退出就说明 Rust 部分从编译到运行都通了。可执行文件留在 `target/debug/examples/` 下。

两点补充：

- 这样编出来的是**标准精度**（64 位定点数）。想和 Python 包保持一致，用 `--features examples,high-precision`。原因见第 0 章第 4.1 节。
- 加 `--release` 会用 `[profile.release]`：`opt-level = 3`、`lto = "fat"`、`codegen-units = 1`、`panic = "abort"`。运行快，但编译慢、内存占用高，只在需要测性能时再用。

### 3.5 跑测试

最直接的是只测一个 crate，不需要任何额外工具：

```bash
cargo test --locked -p nautilus-model --lib
```

仓库自己的测试目标用的是 [cargo-nextest](https://nexte.st/)。先装开发工具（`make install-tools` 第一次运行前要先装 `cargo-binstall`，命令见 `docs/developer_guide/environment_setup.md` 的 “One-off prerequisite”），再用 Make 目标：

```bash
make install-tools
make cargo-test-core-local     # 只测 22 个核心 crate，不编适配器的测试
```

注意 `cargo-test-core-local` 用的不是默认 feature，而是 `scripts/cargo-features.bash` 给出的工作区 feature 组合，再加上 `nautilus-serialization/sbe` 和 `nautilus-infrastructure/postgres`。官方文档要求用 uv 装的 Python 跑 Rust 测试前设好 `PYTHONHOME`，所以跑仓库的测试目标之前，先完成第 4.2 节的环境变量设置。

### 3.6 在自己的 Rust 项目里用它

crates.io 上的版本落后于 `develop`：写这篇时 crates.io 最新是 `0.68.0`，`develop` 的工作区版本是 `0.69.0`。想跟着 `develop` 走，用 git 依赖：

```toml
# 示意：自己项目的 Cargo.toml
[dependencies]
nautilus-model = { git = "https://github.com/nautechsystems/nautilus_trader", branch = "develop", features = ["high-precision"] }
nautilus-backtest = { git = "https://github.com/nautechsystems/nautilus_trader", branch = "develop" }
```

两个注意点：各 crate 声明了 `rust-version = 1.100.0`，你的工具链不能更旧；仓库里的 `.cargo/config.toml`（警告当错误、Linux 用 lld、冷却期）只在仓库目录内生效，不会带到你的项目里。

## 4. Python 部分：编出 `_libnautilus`

### 4.1 `make sync`：先把依赖装好

```bash
make sync
```

它实际运行的是：

```bash
# 示意，节选自 Makefile 的 sync 目标
cd python && VIRTUAL_ENV= uv sync --all-groups --all-extras --no-install-package nautilus-trader $(UV_SYNC_FLAGS)
```

`UV_SYNC_FLAGS` 默认是 `--inexact`（保留不在锁文件里的包），下面设置它时会整体替换这个默认值。

几个参数的含义：所有依赖组（`dev` 里有 maturin、ruff、ty，`test` 里有 pytest、pyarrow 等，`docs` 是文档工具）和所有 extras 都装；`--no-install-package nautilus-trader` 表示**不装这个包本身**，因为它要等 Rust 编完才有；虚拟环境放在 `python/.venv`，和 `python/pyproject.toml` 放在一起。

如果机器上没有 3.13 到 3.15 之间的 Python，uv 会自己下载一个独立构建的 CPython。想指定版本，在同一个终端里先设置 `UV_PYTHON`。用 3.15 时要多一步，因为 `docs` 依赖组还不支持 3.15（PyYAML 没有发布 3.15 的 wheel）：

```bash
export UV_PYTHON=3.15
export UV_SYNC_FLAGS="--inexact --no-group docs"
make sync
```

另一个容易踩的坑：`[tool.uv]` 里有 `exclude-newer = "7 days"`，uv 解析依赖时忽略最近 7 天内发布的版本。这也是供应链防护的一部分，正常情况下不需要改它。

### 4.2 三个环境变量

在仓库根目录、`make sync` 之后执行（Bash / Zsh）：

```bash
source python/.venv/bin/activate

export PYO3_PYTHON="$PWD/python/.venv/bin/python"

# 只在 Linux 上需要
PYTHON_LIB_DIR="$("$PYO3_PYTHON" -c 'import sysconfig; print(sysconfig.get_config_var("LIBDIR"))')"
export LD_LIBRARY_PATH="$PYTHON_LIB_DIR${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

export PYTHONHOME="$("$PYO3_PYTHON" -c 'import sys; print(sys.base_prefix)')"
```

它们分别解决一个问题：

| 变量 | 解决什么 |
| --- | --- |
| `PYO3_PYTHON` | 告诉 PyO3 的构建脚本用哪个解释器。不设的话它会去 `PATH` 里找，找到的解释器一变，所有依赖 PyO3 的 crate 都要重编 |
| `LD_LIBRARY_PATH`（仅 Linux） | 打开 `python` feature 的 Rust **测试程序**会链接 `libpython`；uv 下载的 Python 把它放在自己的 `LIBDIR` 里，运行时要能找到 |
| `PYTHONHOME` | 同样是给 Rust 测试程序用：程序里内嵌了一个解释器，需要知道标准库在哪；不设时 `make cargo-test` 里依赖 PyO3 的测试会找不到 Python 运行时 |

官方的快速安装流程在 `make build-debug` 之前就把三个变量都设好了，照做最省事；后两个主要是给内嵌 Python 解释器的 Rust 程序（测试、存根生成器）用的。这些路径和具体的检出目录绑定，换了检出目录、重建了 `python/.venv` 或换了 Python 版本，都要重新设置。

### 4.3 `make build-debug`：三步编出扩展模块

```bash
make build-debug
```

这个目标依赖 `check-cargo-cooldown` 和 `py-stubs`，`py-stubs` 又依赖 `sync`，所以实际顺序是：

1. **依赖冷却期检查**，同第 3.2 节。
2. **生成类型存根。** `python/generate_stubs.py` 先运行 `generate_docstrings.py` 把 Rust 文档注释同步到绑定代码上，再读取 `pyproject.toml` 里 maturin 的 feature 列表，去掉 `extension-module`、加上 `nautilus-interactive-brokers/gateway`，然后在 `crates/pyo3` 下运行 `cargo run --locked --bin python-stub-gen --profile nextest --features …`（程序在 `crates/pyo3/bin/stub_gen.rs`，profile 由 Makefile 通过 `NAUTILUS_STUB_PROFILE` 传入，和第 3 步一致，所以能共用 `target/` 里的产物）。这个程序根据各 crate 里的 `#[gen_stub_pyclass]` 标注写出 `.pyi`，脚本再做一轮后处理。输入没变时这一步会被跳过。
3. **编译并安装扩展模块。** 在 `python/` 目录下运行 `uv run --no-sync maturin develop --profile nextest --locked`：maturin 按 `[tool.maturin]` 的 `manifest-path = "../crates/pyo3/Cargo.toml"` 和整组 feature 编译 `nautilus-pyo3`，产出名为 `nautilus_trader._libnautilus` 的扩展模块，文件是 `python/nautilus_trader/_libnautilus.<abi>.so`（Windows 上是 `.pyd`），和只放类型存根的 `_libnautilus/` 目录并列（`Makefile` 里的 `PYTHON_EXTENSION_PATH` 就按这个路径找它），再把包装进 `python/.venv`。

两个容易忽略的细节：

- 第 2 步和第 3 步的 feature 不完全相同（差一个 `extension-module`），一部分 crate 要按两组 feature 各编一次。这就是第一次 `make build-debug` 特别慢的原因。
- 所谓 debug 构建用的是 `--profile nextest`（`Makefile` 里 `CARGO_CI_PROFILE` 的默认值），它继承 `[profile.test]`：工作区 crate 不优化（第三方依赖仍是 `opt-level = 1`），**打开 `debug-assertions` 和 `overflow-checks`**，不带调试信息。所以 debug 版的 Python 包运行起来比正式 wheel 慢，但能更早暴露整数溢出一类的错误。

`Makefile` 还会自动做两件事：机器上装了 `sccache` 就用它缓存编译结果（不想用时 `make build-debug SCCACHE=`）；并行任务数默认取 CPU 核数，最多 32，可以用 `CARGO_BUILD_JOBS` 改。

### 4.4 验证：导入并跑一个回测

先确认导入的是刚编出来的 v2：

```bash
uv run --project python --no-sync python -c \
  'import nautilus_trader; print(nautilus_trader.__version__)'
```

应当输出 `2.0.0`。如果输出的是 `1.2xx`，说明当前环境里装的是 PyPI 上的 v1，要换一个干净的虚拟环境：两代都以 `nautilus_trader` 为包名，不能装在一起。

再跑一个完整的回测示例：

```bash
uv run --project python --no-sync python examples/backtest/crypto_ema_cross_ethusdt_trade_ticks.py
```

这个脚本用 Python 版的 `BacktestEngine` 搭了一个币安现货的模拟交易所（现金账户、净头寸、万分之一手续费），从 `test_data/binance/ethusdt-trades.csv` 读入 ETHUSDT 的逐笔成交，用 `docs/tutorials/ema_cross.py` 里的 `EMACross` 策略在 250 笔成交聚合的 K 线上做均线交叉，最后用 pandas 打印账户报告、成交报告和仓位报告。能看到这三张表，Python 部分就通了。

测试数据的查找规则在 `nautilus_trader/testkit/providers.py`：先找仓库根目录的 `test_data/`，找不到才从 GitHub 下载。所以在源码目录里运行不需要联网。

### 4.5 正式版构建和 wheel

```bash
make build                 # maturin develop --release，装进 python/.venv
make build-wheel           # maturin build --release，wheel 输出到 dist/
```

正式版用 `[profile.release]` 的 fat LTO 和单个代码生成单元，链接阶段内存占用很高。官方的说法是 16 GB 内存的机器在能用满内存、并且有足够 swap 时可以完成；链接器内存不够时，改用 ThinLTO：

```bash
CARGO_PROFILE_RELEASE_LTO=thin make build
```

ThinLTO 只适合本地用，测性能时仍以默认的 fat LTO 为准。

如果需要标准精度（64 位）的 Python 包，只删 `high-precision` 是不够的（官方 installation.md 只提了这一项）：maturin 的 feature 里还有 `defi` 和 `hypersync`，`hypersync` 隐含 `defi`，而 `defi` 会经 `nautilus-model/defi` 重新打开 `high-precision`。要把 `high-precision`、`defi`、`hypersync` 三项一起从 `python/pyproject.toml` 的 maturin `features` 里删掉，再 `make build-debug`，并接受失去 DeFi 和 HyperSync 功能。注意数据目录里两种精度的 Parquet 文件不能混用。

### 4.6 改了代码之后怎么重编

| 改了什么 | 运行 | 更新的东西 |
| --- | --- | --- |
| `python/pyproject.toml` 或 `python/uv.lock` | `make sync` | `python/.venv` 里的依赖 |
| Rust 绑定、Python 包代码、存根的输入 | `make build-debug` | debug 版 Python 包和类型存根 |
| CLI 代码或 `schema/sql` | `make install-cli` | `~/.cargo/bin/nautilus` |
| 工具版本（Cargo、uv、prek 等） | `make install-tools` | 开发工具 |

Python 测试用 `make pytest`，它会先执行 `make build-debug`，再在 `python/tests/` 上跑 pytest。

## 5. 出错时先查什么

| 现象 | 多半是 | 处理 |
| --- | --- | --- |
| `make sync` 报 uv 版本不符 | 本机 uv 不在 `>=0.13,<0.14` | `make install-uv` |
| 编译报一堆 `warning` 然后失败 | 没有用 1.100.0（警告被当成错误） | 在仓库目录里看 `rustc --version`，去掉 `RUSTUP_TOOLCHAIN` 一类的覆盖 |
| Linux 上一开始就报 `linking with cc failed`，常见 `cannot find 'ld'` | 没装 `lld`（配置要求用它链接） | `sudo apt-get install lld` |
| macOS 上直接用 `cargo` 时，链接器警告导致失败 | `warnings = "deny"` 把 Apple ld 的警告也当成失败 | `export CARGO_BUILD_WARNINGS=warn`，或改用 Make 目标 |
| `check-cargo-cooldown` 失败 | 没有 `origin/develop`，或 `Cargo.lock` 被改过 | 按 `--branch develop` 重新克隆；不要手改锁文件 |
| Rust 测试找不到 Python 或 `libpython` | 没设 `PYTHONHOME`（Linux 还有 `LD_LIBRARY_PATH`） | 按第 4.2 节设置 |
| 改了 Python 版本后反复全量重编 | `PYO3_PYTHON` 指向的解释器变了 | 重新 `make sync`，重设 `PYO3_PYTHON` |
| `make build` 链接时被杀掉 | fat LTO 内存不够 | `CARGO_PROFILE_RELEASE_LTO=thin make build`，或先用 `make build-debug` |
| 导入后版本是 `1.2xx` | 环境里是 PyPI 的 v1 | 换干净环境，用 `uv run --project python` 运行 |

## 6. Windows

官方支持 Windows Server 2022 及以上（x86_64，CI 固定在 windows-2022），步骤和上面一样，区别在工具：rustup 用 `rustup-init.exe`，C 工具链用 Visual Studio 2022 Build Tools 的 “Desktop development with C++”，clang 通过 Visual Studio Installer 的 “C++ Clang tools for Windows” 安装并加进 `PATH`，uv 用 PowerShell 安装脚本，`make` 需要 MSYS2 或 WSL 提供。第 4.2 节的环境变量只适用于 Linux 和 macOS。具体命令见官方 `docs/getting_started/installation.md` 的 “From source”。

::: warning 常见误区
- **用最新的 stable Rust 编。** 仓库把警告当错误，工具链必须是 `rust-toolchain.toml` 锁定的版本。
- **以为 Python 包是纯 Python 的。** `make build-debug` 是一次完整的 Rust 编译，第一次要编几百个依赖包；之后才是增量编译。
- **拿 debug 版的速度评估性能。** debug 版用 `nextest` profile，工作区代码不优化还开着溢出检查；测性能要用 `make build` 或官方 wheel。
- **v1 和 v2 装进同一个环境。** 两者包名相同，后装的会覆盖先装的，导入时可能拿到另一代。
- **直接跑 `cargo` 却不加 `--locked`。** 依赖可能被重新解析，绕过仓库的冷却期检查。
:::

## 检查理解

1. 为什么 Rust 部分可以完全不装 Python，而 `make build-debug` 必须先 `make sync`？

   <details><summary>参考答案</summary>

   `cargo build -p nautilus-backtest` 用的是各 crate 的默认 feature，里面没有 `python`，不会编 PyO3，也就用不到 Python 解释器。`make build-debug` 用的是 `[tool.maturin]` 的整组 feature，含 `extension-module` 和各 crate 的 Python 绑定；它还要用 `python/.venv` 里的 maturin 去编译和安装扩展模块，存根生成脚本本身也是 Python 程序，这些都依赖 `make sync` 先建好的虚拟环境。

   </details>

2. 同样一份源码，`cargo run --example engine-ema-cross --features examples` 编出来的程序，和 Python 包里的 `Price` 精度一样吗？

   <details><summary>参考答案</summary>

   不一样。`nautilus-backtest` 和 `nautilus-model` 默认不开 `high-precision`，这个示例是 64 位、9 位小数的标准精度；Python 包的 maturin feature 里有 `high-precision`，是 128 位、16 位小数。要一致，给示例加上 `--features examples,high-precision`。

   </details>

3. `make build-debug` 里的 “debug” 和 `cargo build` 默认的 dev profile 是一回事吗？

   <details><summary>参考答案</summary>

   不是。`make build-debug` 传给 maturin 的是 `--profile nextest`，它继承 `[profile.test]`，打开了 `debug-assertions` 和 `overflow-checks`；`cargo build` 默认用 `[profile.dev]`，仓库把这两项都关掉了。两者对工作区 crate 都不优化（第三方依赖都是 `opt-level = 1`），区别在检查的严格程度。

   </details>

## 参考资料

- 官方文档：[Installation · From source](https://github.com/nautechsystems/nautilus_trader/blob/develop/docs/getting_started/installation.md) · [Environment setup](https://github.com/nautechsystems/nautilus_trader/blob/develop/docs/developer_guide/environment_setup.md) · [python/README.md](https://github.com/nautechsystems/nautilus_trader/blob/develop/python/README.md)
- 构建配置：[`Makefile`](https://github.com/nautechsystems/nautilus_trader/blob/develop/Makefile) · [`rust-toolchain.toml`](https://github.com/nautechsystems/nautilus_trader/blob/develop/rust-toolchain.toml) · [`.cargo/config.toml`](https://github.com/nautechsystems/nautilus_trader/blob/develop/.cargo/config.toml) · [`Cargo.toml`（profile）](https://github.com/nautechsystems/nautilus_trader/blob/develop/Cargo.toml) · [`python/pyproject.toml`](https://github.com/nautechsystems/nautilus_trader/blob/develop/python/pyproject.toml) · [`python/generate_stubs.py`](https://github.com/nautechsystems/nautilus_trader/blob/develop/python/generate_stubs.py)
- 示例：[`crates/backtest/examples/engine_ema_cross.rs`](https://github.com/nautechsystems/nautilus_trader/blob/develop/crates/backtest/examples/engine_ema_cross.rs) · [`examples/backtest/crypto_ema_cross_ethusdt_trade_ticks.py`](https://github.com/nautechsystems/nautilus_trader/blob/develop/examples/backtest/crypto_ema_cross_ethusdt_trade_ticks.py)
- 配图由 `scripts/generate-nautilus-trader-figures.py` 生成。

两部分都跑通之后，就可以边读边改了。下一章从内核的启动开始，跟着一条报价和一笔订单走一遍运行时：[第 1 章：整体架构](./architecture.md)。
