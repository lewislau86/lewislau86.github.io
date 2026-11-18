---
title: "从零编译 NautilusTrader：Rust 与 Python 两部分"
description: 在一台干净的 macOS 或 Ubuntu 机器上，从安装工具链开始，分别编译并运行 NautilusTrader 的 Rust 部分（cargo 直接跑回测示例）和 Python 部分（make build-debug 生成扩展模块），并解释每一步背后在做什么。
---

# 从零编译 NautilusTrader：Rust 与 Python 两部分

[全书目录](./index.md) · [下一篇](./nautilus-architecture.md)

::: tip 本篇目标
从一台只装了操作系统的机器开始，走完两条路：

- **Rust 部分**：不装 Python，用 `cargo` 编译一个 crate、跑通 `engine-ema-cross` 回测示例、跑单元测试；
- **Python 部分**：用 `make build-debug` 编出 `nautilus_trader._libnautilus` 扩展模块，在 `python/.venv` 里导入它，跑通一个 Python 回测示例。

每一步都说明它在做什么、产物放在哪里、出错时先查什么。

**源码版本：** `develop` 分支，提交 `5997d82`（2026-11-17）。命令取自同一提交的 `Makefile`、`docs/getting_started/installation.md`、`docs/developer_guide/environment_setup.md` 和 `python/README.md`。项目的构建脚本改动很频繁，命令跑不通时先对照这几个文件。
:::

::: info 实测记录（2026-11-18）
本篇的 Linux 路线在一台 Ubuntu 22.04（aarch64，4 核，3.9 GB 内存，glibc 2.35）上按顺序走了一遍，源码是当天 `develop` 的 `364254f`，和 `5997d82` 相比构建相关的文件只有几个依赖版本号不同。实际跑通的有：工具链自动安装、`make check-cargo-cooldown`、第 3.3～3.5 节的三条 `cargo` 命令、`make sync`、第 4.2 节的环境变量、`make build-debug`、第 4.4 节的两条验证命令。各步的实际输出写在对应小节里，过程中真实遇到的错误和处理办法集中在第 5 节。

没有实测的有：macOS 路线、`make install-tools` 和 `make cargo-test-core-local`、`make build`、`make build-wheel`、`make pytest`、Windows。那台机器没有 root 权限，`clang`、`lld`、`patchelf` 都装不上，下文在对应位置说明了当时的替代做法和观察到的结果。
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

**磁盘要留足。** 实测（Linux aarch64）下载缓存和工具链约 7 GB（rustup 4.2 GB、Cargo 缓存 1.1 GB、uv 和 Python 1.4 GB）；Rust 部分的 `target/debug` 约 5 GB；`make build-debug` 用的 `target/nextest` 约 23 GB，编出来的扩展模块单个文件就有 860 MB。只做 Python 部分也建议预留 35 GB 以上。

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

Ubuntu 上的 `lld` 不能省。仓库的 `.cargo/config.toml` 给 Linux 目标写死了 `-C link-arg=-fuse-ld=lld`，这组参数对依赖的构建脚本和过程宏同样生效，所以没装 `lld` 时，第一个需要链接的东西就会失败。实测的报错见第 5.4 节。没有 root 权限装不了 `lld` 时，可以借用 Rust 工具链自带的 `rust-lld`：在 `PATH` 靠前的目录里建一个名叫 `ld.lld` 的符号链接指向它。实测这样能正常完成本篇的所有构建：

```bash
# 第 2.2、2.4 节之后在仓库目录里执行（这样 rustc 指向锁定的 1.100.0）；~/bin 要在 PATH 里
ln -s "$(rustc --print sysroot)/lib/rustlib/$(rustc -vV | sed -n 's/host: //p')/bin/rust-lld" ~/bin/ld.lld
```

`patchelf` 是 `python/README.md` 列出的 Linux 前置依赖，maturin 在需要给扩展模块设置 rpath 时用它；官方的快速安装命令里没有它，这里一并装上。实测没装它时 `make build-debug` 也成功了，没有出现 rpath 相关的警告。同样，实测机器上没有 `clang`，用系统的 `gcc` 编依赖里的 C 代码也没有出问题；不过官方文档要求装 `clang`，照装即可。

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

实测：在仓库里第一次运行 `rustc --version` 时，rustup 打印 `syncing channel updates for 1.100.0-aarch64-unknown-linux-gnu` 并开始下载。这次下载如果被打断，后面会报 `missing manifest`，处理办法见第 5.2 节。

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

`--depth 1` 只取最新一个提交，适合只想编译和阅读的场景。克隆下来的目录里，第 0 章要讲的 `crates/`、`python/` 都在，另外还有 Python 示例要用的 `test_data/` 和 `docs/tutorials/`。

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

它会对照 `origin/develop` 这个引用做校验。按上面 `--depth 1 --branch develop` 克隆，`origin/develop` 是存在的，检查会正常对照它。实测几秒钟就结束，最后一行是 `OK: all 892 bumped crate(s) are at least 3 days old.`，发布日期全部来自仓库里的数据库，不需要联网查询。完整克隆却缺少 `origin/develop` 时检查会失败，需要先 fetch；浅克隆里解析不到它时，脚本会打印一条 NOTE，改为信任 `.supply-chain/crate-dates.json` 里记录的日期。

### 3.3 编一个 crate，验证工具链

```bash
cargo build --locked -p nautilus-model
```

产物在 `target/debug/`。这一步只编 `nautilus-model` 和它依赖的 `nautilus-core`、`nautilus-macros` 以及第三方包（实测共 94 个包，4 核机器上一分钟左右），很快就能确认编译器、链接器都正常。

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

注意它编译的东西比想象的多：示例可以用 `nautilus-backtest` 的 dev-dependencies，其中包括数据目录相关的 crate，所以 `arrow`、`parquet`、`datafusion` 也会被编进来。实测这一步要下载两百多个 crate、编译约四百个，`target/debug` 涨到 5 GB 左右。

终端里会看到引擎和策略的日志，程序正常退出就说明 Rust 部分从编译到运行都通了。可执行文件留在 `target/debug/examples/` 下。实测日志最后的 `BACKTEST POST-RUN` 汇总是：

```text
Iterations: 745
Total events: 24
Total orders: 12
Total positions: 12
...
PnL (total):                    0.00
```

745 条报价对得上第 5 步的计算。12 笔订单开出了 12 个仓位、总盈亏为 0，原因是第 2 步选了对冲式仓位（`OmsType::Hedging`）：每一笔成交都开一个新仓位，卖单不会去平之前的买单，所以没有任何仓位被平掉，也就没有已实现盈亏。这个示例只演示流程，不是一个能赚钱的策略。

两点补充：

- 这样编出来的是**标准精度**（64 位定点数）。想和 Python 包保持一致，用 `--features examples,high-precision`。原因见第 0 章第 5.1 节。
- 加 `--release` 会用 `[profile.release]`：`opt-level = 3`、`lto = "fat"`、`codegen-units = 1`、`panic = "abort"`。运行快，但编译慢、内存占用高，只在需要测性能时再用。

### 3.5 跑测试

最直接的是只测一个 crate，不需要任何额外工具：

```bash
cargo test --locked -p nautilus-model --lib
```

实测结果是 `test result: ok. 4362 passed; 0 failed; 1 ignored`。有几个测试在编译期读取 `crates/model/test_data/` 下的 JSON，所以要用完整的克隆，否则见第 5.5 节。

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

如果机器上没有 3.13 到 3.15 之间的 Python，uv 会自己下载一个独立构建的 CPython（实测下载的是 `cpython-3.14.10`，约 30 MB），然后输出 `Resolved 72 packages`，装好其中适用于本平台的 69 个。想指定版本，在同一个终端里先设置 `UV_PYTHON`。用 3.15 时要多一步，因为 `docs` 依赖组还不支持 3.15（PyYAML 没有发布 3.15 的 wheel）：

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

实测的输出依次是 `Generating Python type stubs...`、一长串 `Compiling`、`Stub generation completed successfully`，然后是 `Building the Python extension in debug mode...`，最后：

```text
📦 Built wheel for CPython 3.14 to …/nautilus_trader-2.0.0-cp314-cp314-linux_aarch64.whl
✏️ Setting installed package as editable
🛠 Installed nautilus-trader-2.0.0
```

也就是说，maturin 先在临时目录打出一个 wheel，再以**可编辑方式**装进 `python/.venv`：包指向源码目录，扩展模块文件 `_libnautilus.cpython-314-aarch64-linux-gnu.so` 实测出现在 `python/nautilus_trader/` 下，大小约 860 MB。生成存根之后 `git status` 是干净的，说明生成的 `.pyi` 和仓库里提交的一致。

实测机器只有 3.9 GB 内存，整个过程没有出现内存不足。中途遇到过一次 `Too many open files`，原因和处理见第 5.7 节。

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

应当输出 `2.0.0`（实测如此，不需要先设置第 4.2 节的环境变量）。如果输出的是 `1.2xx`，说明当前环境里装的是 PyPI 上的 v1，要换一个干净的虚拟环境：两代都以 `nautilus_trader` 为包名，不能装在一起。

再跑一个完整的回测示例：

```bash
uv run --project python --no-sync python examples/backtest/crypto_ema_cross_ethusdt_trade_ticks.py
```

这个脚本用 Python 版的 `BacktestEngine` 搭了一个币安现货的模拟交易所（现金账户、净头寸、万分之一手续费），从 `test_data/binance/ethusdt-trades.csv` 读入 ETHUSDT 的逐笔成交，用 `docs/tutorials/ema_cross.py` 里的 `EMACross` 策略在 250 笔成交聚合的 K 线上做均线交叉，最后用 pandas 打印账户报告、成交报告和仓位报告。能看到这三张表，Python 部分就通了。实测几秒钟跑完，汇总是 `Iterations: 69_806`、`Total orders: 30`、`Total positions: 15`，总盈亏 `-1.07`（USDT），胜率 0.2。

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

## 5. 编译中实际遇到的错误

下面是本篇开头“实测记录”那次完整编译里真实出现过的错误，按出现的先后排列。每条给出原样的报错、原因和处理办法。有几条和网络、磁盘、共享目录有关，在开发机上未必会遇到，但遇到时报错信息不太直观，所以一并记下。

### 5.1 克隆时连接被断开

```text
fatal: unable to access 'https://github.com/nautechsystems/nautilus_trader/': GnuTLS recv error (-110): The TLS connection was non-properly terminated.
fatal: unable to access 'https://github.com/nautechsystems/nautilus_trader/': Failed to connect to github.com port 443 after 30003 ms: Connection refused
```

**原因：** 到 GitHub 的网络不稳定，`git clone` 中途失败就要整个重来。

**处理：** 重试；改用 HTTP/1.1 往往更稳。网络很差时可以先只拿提交和目录树，再检出文件，这样失败后重试的代价小：

```bash
git -c http.version=HTTP/1.1 clone --branch develop --depth 1 --filter=blob:none \
    https://github.com/nautechsystems/nautilus_trader
```

检出过程被打断（Ctrl+C、断网）后，已经写了一半的文件会留在工作区里，`git status` 会显示它们被修改或删除。先 `git checkout -- .` 恢复，再继续。

### 5.2 工具链下载被打断：`missing manifest`

```text
error: missing manifest in toolchain '1.100.0-aarch64-unknown-linux-gnu'
help: this may happen if the toolchain installation was interrupted
```

**原因：** 第 2.2 节说过，在仓库里第一次运行 `rustc` 或 `cargo` 会按 `rust-toolchain.toml` 自动下载 1.100.0。这次下载如果中途断开，留下的是一个不完整的工具链目录，之后的自动安装不会再重试。

**处理：** 手动装一次。rustup 会接着已下载的部分继续：

```bash
rustup toolchain install 1.100.0
```

### 5.3 长时间停在 `Updating crates.io index`

**原因：** 不是卡死。第一次构建时 Cargo 要为 `Cargo.lock` 里的近九百个包逐个拉取索引文件（sparse 协议，每个包一个小请求），网络慢时要好几分钟。中断后已拉到的索引会保留，重新运行会接着做。

**处理：** 等待，或中断后重跑。

### 5.4 Linux 上一开始就链接失败：`cannot find 'ld'`

```text
error: linking with `cc` failed: exit status: 1
  = note:  "cc" … "-fuse-ld=lld" "-Wl,--gc-sections" "-Wl,--as-needed" "-Wl,-z,norelro"
  = note: collect2: fatal error: cannot find 'ld'
error: could not compile `serde_core` (build script) due to 1 previous error
error: could not compile `proc-macro2` (build script) due to 1 previous error
```

**原因：** `.cargo/config.toml` 要求 Linux 上用 `lld` 链接（命令行里的 `-fuse-ld=lld`），机器上没有 `ld.lld`。第一个需要链接的是依赖的构建脚本，所以构建刚开始就失败。

**处理：** `sudo apt-get install lld`。没有 root 权限时，用第 2.1 节的办法把 Rust 工具链自带的 `rust-lld` 链接成 `ld.lld`。

### 5.5 测试编译失败：找不到 `test_data` 里的文件

```text
error: couldn't read `crates/model/src/accounts/../../test_data/account_legacy_cash.json`: No such file or directory (os error 2)
error: could not compile `nautilus-model` (lib test) due to 3 previous errors
```

**原因：** `nautilus-model` 的部分测试在编译期用 `include_str!` 读取 `crates/model/test_data/` 下的文件。克隆不完整（稀疏检出、或 5.1 节那样检出被打断）时，这些文件不存在。`cargo build` 不受影响，只有 `cargo test` 会失败。

**处理：** 恢复完整的工作区：`git sparse-checkout disable`（如果用过稀疏检出），再 `git checkout -- .`。

### 5.6 `make sync` 停在下载大文件上

```text
>  Syncing Python dependencies...
Downloading cpython-3.14.10-linux-aarch64-gnu (download) (29.4MiB)
…
Downloading pyarrow (48.6MiB)
Downloading polars-runtime-32 (48.1MiB)
```

**原因：** uv 默认同时下载很多文件，网络慢时每个文件都分到很少的带宽，大文件迟迟下不完；中断后，没下完的文件下次要从头再下（已经下完的会留在 uv 的缓存里）。

**处理：** 先减少并发再重跑，让文件一个个下完、进缓存：

```bash
UV_CONCURRENT_DOWNLOADS=2 make sync
```

网络实在太差时，可以用支持断点续传的 `curl -C -` 先把大文件下到本地：

- **Python 解释器：** 把 `uv python list 3.14 --output-format json` 里给出的 `url` 下载到 `<目录>/<发布日期>/` 下，再用 `UV_PYTHON_INSTALL_MIRROR=file://<目录> uv python install 3.14` 安装。
- **wheel：** 从 `python/uv.lock` 里找到对应平台的 URL 下载到一个目录，用 `uv pip install --python python/.venv/bin/python --no-deps --no-index --find-links <目录> pyarrow==26.0.0 …` 装进环境，然后再跑 `make sync`。

这里有个细节：必须用 `--find-links` 按包名和版本安装。如果直接写 wheel 的文件路径（`uv pip install ./pyarrow-….whl`），uv 会把来源记成本地文件，下一次 `make sync` 认为它和锁文件里的来源不一致，又会重新下载一遍。

### 5.7 并行编译时 `Too many open files`，接着报找不到 crate

```text
error: failed to build archive at `…/target/nextest/build/nautilus-analysis/…/libnautilus_analysis-….rlib`: failed to open object file …rcgu.o: Too many open files (os error 24)
error: error writing dependencies to `…/nautilus_analysis-….d`: Too many open files (os error 24)
error[E0463]: can't find crate for `tracing_subscriber`
error[E0463]: can't find crate for `tokio`
error[E0463]: can't find crate for `futures`
error: could not compile `nautilus-common` (lib) due to 3 previous errors
Build failed: Command '['cargo', 'run', '--locked', '--bin', 'python-stub-gen', '--profile', 'nextest', '--features', 'arrow,high-precision,mimalloc,redis,postgres,defi,hypersync,tracing-bridge,nautilus-interactive-brokers/gateway']' returned non-zero exit status 101.
make: *** [Makefile:370: …/target/.py-stubs.stamp] Error 1
```

**原因：** 出现在 `make build-debug` 的存根生成阶段。`nextest` profile 打开了增量编译，每个 crate 会产生两百多个目标文件；几个 `rustc` 并行写这些文件，超过了打开文件数的上限。后面几条 `can't find crate` 是连锁反应：依赖的库文件没能打开，并不是真的缺少依赖。最后那行 `Build failed: Command [...]` 是 `generate_stubs.py` 打出来的，只说明存根生成器编译失败，**真正的错误要往上翻**。

这次的 `target` 目录放在虚拟机挂载的共享目录上，把本进程的 `ulimit -n` 提到 65536 也没用，限制来自共享目录那一侧；`target` 在本地磁盘上时一般碰不到。macOS 终端默认的 `ulimit -n` 只有 256，比 Linux 常见的 1024 低得多，如果遇到同样的报错，先试试调高它。

**处理：** 降低并行数后重跑，已经编好的 crate 不会重编：

```bash
CARGO_BUILD_JOBS=2 make build-debug
```

另外两个办法：把产物放到本地磁盘（`TARGET_DIR=/本地/路径 make build-debug`），或者 `ulimit -n 10240`。

### 5.8 磁盘空间

这次没有真的写满磁盘，但第 1 节列的数字值得再强调一次：完整走完本篇，`target` 目录约 28 GB（`target/debug` 5 GB，`target/nextest` 23 GB），工具链和下载缓存另有约 7 GB。空间不足时报 `No space left on device`，可以用 `TARGET_DIR` 把产物放到大盘上。

### 5.9 其他可能遇到的问题

下面几种这次没有遇到，来自官方文档和仓库配置：

| 现象 | 多半是 | 处理 |
| --- | --- | --- |
| `make sync` 报 uv 版本不符 | 本机 uv 不在 `>=0.13,<0.14` | `make install-uv` |
| 编译报一堆 `warning` 然后失败 | 没有用 1.100.0（警告被当成错误） | 在仓库目录里看 `rustc --version`，去掉 `RUSTUP_TOOLCHAIN` 一类的覆盖 |
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

两部分都跑通之后，就可以边读边改了。下一篇先看全景：一个节点分几层、每层在哪个目录、核心数据结构长什么样：[第 0 章：NautilusTrader 架构](./nautilus-architecture.md)。
