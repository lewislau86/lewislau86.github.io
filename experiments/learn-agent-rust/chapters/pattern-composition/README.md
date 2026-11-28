# D08 · 模式组合与选型实战（ADK-Rust 3.0）

教程：https://lewislau86.github.io/learn-agent-rust/pattern-composition

升级发布流程是一个 `SequentialAgent`，把前面几章的模式串起来：

- checks：`ParallelAgent` 同时运行依赖、文档两个检查者（第 18 章）；
- merge：`CustomAgent` 核对成员与修订，不对就上报，整个流程停下；
- refine：`LoopAgent` 让写作者和评估者轮流工作，最多 3 轮（第 21 章），外面包一层接缝适配器；
- publisher：发布要人批准，挂起、批准、恢复（第 22 章）。

整次运行共用一个 `RunBudget`。默认模型是按规则回复的替身。

## 准备 ADK-Rust 源码

```sh
python3 fetch-adk-rust.py ../adk-rust     # 需要 git 与 GitHub 访问；不行时加 --method cdn
```

下面的命令都要在本目录里运行（cargo 只读取当前目录及上级目录的 `.cargo/config.toml`）。

## 运行

```sh
cargo run --locked                    # 全部 6 个场景的摘要
cargo run --locked -- naive           # 某个场景的完整轨迹
cargo test --locked
cargo fmt --check
cargo clippy --locked --all-targets -- -D warnings
```

## 换成真实服务

`live` 子命令把替身换成 adk-model 的 `OpenAIClient::compatible`，流程不变。服务地址（含 `/v1`）、模型和密钥只从环境变量读取，不要写进仓库：

```sh
OPENAI_BASE_URL=... OPENAI_MODEL=... OPENAI_API_KEY=... cargo run --locked -- live
```

没有服务时，用本地 fixture 检查接线（只认非流式 `/v1/chat/completions`，按替身的规则回答）：

```sh
python3 live_fixture.py -- cargo run --locked -- live
```

## 模式对照

`model_compare.py`（只用 Python 标准库）用公开的 `model-cases.json` 比较九种结构：

```sh
python3 model_compare.py self-test ./fixture-run          # 本地 HTTP 自检，36 项任务
python3 model_compare.py live ./live-run --repeats 3     # 需要先配置 OPENAI_BASE_URL、OPENAI_MODEL、OPENAI_API_KEY
```

全九种变体 4 题 × 3 次重复 = 108 个计划任务，每任务最多 8 次请求、每次最多 512 生成 token；也可 `--variants single composed` 先跑 24 任务。输出目录必须不存在。只发送公开的 `model-cases.json`，密钥只用于 Authorization，不保存到结果。

`rust-toolchain.toml` 固定 Rust 1.99.1；`Cargo.lock` 固定全部依赖。
编译时会看到 adk-core 的 3 条 `fetch_update` 弃用警告（上游固定 1.95.0），不影响本章代码的检查。

## 实验边界

- 替身与 fixture 按固定规则回答；真实服务没有运行，没有模型质量结论。
- 四题公开诊断集不用于泛化与排名；`human` 变体的批准是脚本输入。
