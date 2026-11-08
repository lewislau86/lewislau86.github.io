# G02 · graph-flow 暂停与恢复

教程：https://lewislau86.github.io/learn-agent-rust/graph-pause-resume

真实调用 graph-flow 0.8.1，固定 Git revision `9bbca193f20a8c4ba23289621549ecb3d35fee64`；Rust 1.99.1。不依赖 langchain-rust，不调用模型服务。首次获取 Cargo 依赖需要网络，缓存后可 `--offline`。

```sh
cargo test --locked
cargo clippy --locked --all-targets -- -D warnings
cargo run --locked -- /tmp/my-graph.db init
cargo run --locked -- /tmp/my-graph.db step
cargo run --locked -- /tmp/my-graph.db step
cargo run --locked -- /tmp/my-graph.db approve 1 yes
cargo run --locked -- /tmp/my-graph.db step
cargo run --locked -- /tmp/my-graph.db step
cargo run --locked -- /tmp/my-graph.db show
```

实现真实 SessionStorage trait，以 SQLite 事务存储整个 Session 与版本。每条命令是独立进程；使用新的数据库路径，不会重置已有会话。批准是固定 CLI 输入，不提供身份认证。校验 graph/schema/cursor，保存与恢复真实；terminal 由应用持久化，重复 step 不再运行结束节点。限定单执行者业务推进；存储 CAS 拒绝旧写入，不代表恰好一次外部效果。无真实发布或外部副作用，报告保存在 Context。同步 SQLite 适合小型 CLI，服务端需隔离阻塞 I/O。
