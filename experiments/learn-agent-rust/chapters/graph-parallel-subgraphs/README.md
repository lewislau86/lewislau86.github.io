# G03 · graph-flow 并行与子图

教程：https://lewislau86.github.io/learn-agent-rust/graph-parallel-subgraphs

真实调用 graph-flow 0.8.1，固定 Git revision `9bbca193f20a8c4ba23289621549ecb3d35fee64`；Rust 1.99.1。不依赖 langchain-rust，不调用模型服务。首次获取 Cargo 依赖需要网络，缓存后可 `--offline`。

```sh
cargo test --locked
cargo clippy --locked --all-targets -- -D warnings
cargo run --locked -- normal
cargo run --locked -- failure
cargo run --locked -- collision
cargo run --locked -- subgraph
cargo run --locked -- timeout
```

真实 FanOutTask 与子 Graph。Barrier 确认两个异步任务均已进入；没有性能加速结论。成功结果按固定 ID 顺序归并；失败保留兄弟结果，合并节点不会运行。collision 故意复现共享读改写丢更新。子图通过应用 Task 包装器执行，新 Session 隔离上下文；父子只传显式字段，不提供跨进程子图恢复。timeout 是真实待定 future 的任务超时，未验证任意系统进程取消。
