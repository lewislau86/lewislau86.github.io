# K01 · RAG：把检索证据带入回答

教程：https://lewislau86.github.io/learn-agent-rust/retrieval-augmented-generation

独立 Rust 1.99.1 工程，仅使用标准库，无密钥、网络或数据库依赖。

```sh
cargo test --locked --offline
cargo clippy --locked --offline -- -D warnings
cargo run --locked --offline -- suite /tmp/my-rag-lab
cargo run --locked --offline -- query corpus A 'upgrade Rust'
cargo run --locked --offline -- query corpus A 'revert disaster'
```

`suite` 的路径必须尚不存在。套件创建教学资料，实际读写、更新、删除文件，保留目录供检查。再次运行请使用新路径；目录由读者自行清理。`query` 只读已有资料；输入范围 A/B 模拟宿主已解析的身份，不提供身份认证。

真实执行：按段落切块、来源行号、权限范围过滤、BM25 检索、上下文预算、逐字摘录引用校验、过期拒绝与重建、公开标签上的检索评估。

生成器为固定摘录夹具，输出第一条证据的原文与引用。它验证接口和宿主检查，不验证真实 LLM 的回答能力或提示注入抵抗力。英文 ASCII 分词有意保留同义词失败；未实现 embedding、向量库、reranker、中文分词或框架/MCP 集成。Rust 2.00.0 仅是更新场景的合成文本。

公开 4 道教学检索题的 Recall@2 与 MRR@2 分开于答案正确率；其中一题故意没有词面重合。FNV 显示指纹不具备密码学保证；过期检查比较完整来源文本，发布证据另有 SHA-256。索引在进程内，每次 `query` 重新构建；更新场景在同一进程中保留旧索引再修改磁盘以模拟过期。
