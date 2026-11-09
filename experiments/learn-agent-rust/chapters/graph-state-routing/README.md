# G01 · graph-flow 状态与路由

教程：https://lewislau86.github.io/learn-agent-rust/graph-state-routing

真实调用 graph-flow 0.8.1，固定 Git revision `9bbca193f20a8c4ba23289621549ecb3d35fee64`；Rust 1.99.1。不依赖 langchain-rust，不调用模型服务。首次获取 Cargo 依赖需要网络，缓存后可 `--offline`。

```sh
cargo test --locked
cargo clippy --locked --all-targets -- -D warnings
cargo run --locked -- normal
cargo run --locked -- direct
cargo run --locked -- exhausted
cargo run --locked -- probes
```

验证类型化业务状态、条件边、GoTo 修复循环、Continue 与 ContinueAndExecute、悬空边、缺失起点、无边暂停、错误跳转、单次链式上限和 Context 共享。生成/校验采用固定整数规则，图执行真实。节点失败不会自动回滚已修改的 Context。
