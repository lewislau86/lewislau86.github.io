# R05：可见的任务清单

这是可独立解压运行的会话内清单实验。Rust 工具链固定为 1.99.1，
Cargo.lock 固定依赖；首次构建需联网下载工具链与 crates。
无需模型密钥、数据库、相邻课程代码或网站脚本。

```sh
cargo run --locked
cargo run --locked -- --json normal
cargo run --locked -- --json claims-only
cargo test --locked
cargo fmt --check
cargo clippy --locked --all-targets -- -D warnings
```

默认命令执行全部 20 个场景，每个场景均有断言，失败会以非零状态退出。
`--json SCENARIO` 输出单场景证据，场景名见默认输出或源码 CASES。
六个 Rust 测试覆盖迁移矩阵、整批原子拒绝、全部场景、每轮上下文、
更换 README 后的实际回答以及输入长度和格式边界。

固定脚本模型产生 JSON 工具调用。程序创建临时 README，使用 std::fs 真实读取，
离开作用域后由 tempfile 清理。所有清单与消息只在当前 Runtime 的内存里。
程序执行器允许读取固定 README、读取和更新清单；拒绝所有写文件请求。
它未接入真实模型、langchain-rust、graph-flow 或持久化存储。

`goal_verified` 是这个固定任务的独立验收：成功读取一次，最终答案包含读取到的完整正文。
它用于展示清单状态与执行证据的区别，不代表通用的任务质量判定器。

课程正文：https://lewislau86.github.io/learn-agent-rust/todo-planning

在网站仓库中重新生成输出与下载包：
`python3 scripts/verify-learn-agent-rust-r05.py`。
检查是否过期追加 `--check`；配图运行
`python3 scripts/generate-learn-agent-rust-figures.py --lesson R05`。
