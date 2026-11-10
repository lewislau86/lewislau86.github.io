# D05 · 协调者、工作者与任务交接

教程：https://lewislau86.github.io/learn-agent-rust/orchestrator-workers-handoffs

本目录可独立复制。Rust 1.99.1，固定 graph-flow git 提交，Cargo.lock 固定解析结果；首次下载依赖需要网络，之后可加 --offline。

```sh
cargo run --locked -- suite
cargo test --locked
cargo clippy --locked --all-targets -- -D warnings
```

输出字段 scenario/trace/used/limit/stop/data。stop=completed 是业务通过，图结束本身不等于通过。节点执行和派发 worker 在同一账本扣费，默认 32，budget 场景为 1。输入与角色决策均为固定夹具；真实图、Tokio 与文件范围见 evidence.json。

真实 Tokio 动态派发与角色状态；消息为脚本，非真实多模型协作。

下载包附 outputs/suite.json 和 evidence.json。网站唯一源码与包内容由 scripts/verify-agent-patterns.py 核对，并解压最终包离线重跑。包内没有源码依赖上级或相邻目录。
