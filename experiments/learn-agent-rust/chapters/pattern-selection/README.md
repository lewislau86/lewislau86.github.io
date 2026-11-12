# D01 · 模式选择：单次调用、工作流与自主循环

教程：https://lewislau86.github.io/learn-agent-rust/pattern-selection

本目录可独立复制。Rust 1.99.1，固定 graph-flow git 提交，Cargo.lock 固定解析结果；首次下载依赖需要网络，之后可加 --offline。

```sh
cargo run --locked -- suite
cargo test --locked
cargo clippy --locked --all-targets -- -D warnings
```

输出字段 scenario/trace/used/limit/stop/data。stop=completed 是业务通过，图结束本身不等于通过。节点执行和派发 worker 在同一账本扣费，默认 32，budget 场景为 1。输入与角色决策均为固定夹具；真实图、Tokio 与文件范围见 evidence.json。

真实 graph-flow；读取与决策是内存夹具，模型质量另验。

下载包附 outputs/suite.json 和 evidence.json。网站唯一源码与包内容由 scripts/verify-agent-patterns.py 核对，并解压最终包离线重跑。包内没有源码依赖上级或相邻目录。
