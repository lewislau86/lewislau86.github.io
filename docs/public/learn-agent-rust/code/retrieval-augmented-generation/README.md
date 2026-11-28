# K01 · RAG：检索、证据与回答（ADK-Rust 3.0 / adk-rag）

教程：https://lewislau86.github.io/learn-agent-rust/retrieval-augmented-generation

四份小型 Markdown 资料（`corpus/`）：发布说明、运维步骤、一条含恶意指令的导入工单（范围 A），以及另一个租户的私有说明（范围 B）。
切块、词袋 embedding 与按范围的向量检索由 adk-rag 的 `RagPipeline` 执行（`InMemoryVectorStore`，不联网）；
来源时效、上下文预算和引用校验由本工程的宿主代码执行。生成器是“摘录第一条证据”的确定性夹具；
`agent-*` 场景用 `ScriptedLlm` 调用 `RagTool`，并用 `CitationRequired` 检查最终回答的引用。

## 准备 ADK-Rust 源码

```sh
python3 fetch-adk-rust.py ../adk-rust     # 需要 git 与 GitHub 访问；不行时加 --method cdn
```

下面的命令都要在本目录里运行（cargo 只读取当前目录及上级目录的 `.cargo/config.toml`）。

## 运行

```sh
cargo run --locked -- query corpus A 'upgrade Rust'     # 只读本目录的 corpus/
cargo run --locked -- suite /tmp/my-rag-lab             # 目标目录必须尚不存在；跑完保留供检查
cargo test --locked
cargo fmt --check
cargo clippy --locked --all-targets -- -D warnings
```

`suite` 依次运行：normal、no-hit、zero-score、scope、budget、injection、bad-citation、evaluation、lexical-gap、
swap-embedder、collision、stale、updated、deleted、agent-cited、agent-uncited。它会修改再删除目标目录里的
`release.md`，不要把已有资料目录作为目标。

`rust-toolchain.toml` 固定 Rust 1.99.1；`Cargo.lock` 固定全部依赖。
编译时会看到 adk-core 的 3 条 `fetch_update` 弃用警告（上游固定 1.95.0），不影响本章代码的检查。

## 实验边界

- 词袋 embedding 只认英文单词，不懂同义词；`swap-embedder` 用的同义词表是手写替身，不是语义模型。
- 真实语义向量要用 adk-rag 的 `onnx` 特性（首次需要下载模型）或在线 provider，本工程没有运行。
- 四道评估查询和标签都是公开的教学样例，不代表生产检索或真实模型质量。
- 生成器是固定夹具；`agent-*` 场景的模型是脚本，只验证检索工具、来源记录和引用检查的接线。
