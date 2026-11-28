# R06 · 子 Agent 与上下文隔离（ADK-Rust 3.0）

教程：https://lewislau86.github.io/learn-agent-rust/subagents

父 Agent（coordinator）把“从 README 提取启动命令”交给子 Agent（reader）。主线用 `AgentTool` 把子 Agent 当成工具：
子 Agent 在一个新的空会话里运行，只把最终回答交回父 Agent；对照场景 `transfer` 用 `transfer_to_agent` 把控制权交给子 Agent。
外面再包一层宿主契约 `Delegate`：子任务说明不能为空、不超过 256 字节，回传不超过 160 字节。
父子模型都是按规则回复的 `RuleLlm`，各自只看得到自己的请求；文件工具真实读取临时目录。

## 准备 ADK-Rust 源码

```sh
python3 fetch-adk-rust.py ../adk-rust     # 需要 git 与 GitHub 访问；不行时加 --method cdn
```

下面的命令都要在本目录里运行（cargo 只读取当前目录及上级目录的 `.cargo/config.toml`）。

## 运行

```sh
cargo run --locked                    # 全部 15 个场景的摘要
cargo run --locked -- normal          # 某个场景的完整轨迹（父子事件 + 父子各自收到的请求）
cargo test --locked
cargo fmt --check
cargo clippy --locked --all-targets -- -D warnings
```

`rust-toolchain.toml` 固定 Rust 1.99.1；`Cargo.lock` 固定全部依赖。
编译时会看到 adk-core 的 3 条 `fetch_update` 弃用警告（上游固定 1.95.0），不影响本章代码的检查。

## 实验边界

- 子 Agent 与父 Agent 在同一个进程里运行（框架为每次委派开一个单独的异步任务）；新会话只隔离模型看到的内容，不隔离文件系统。
- `PARENT_ONLY_NOTE` 写在用户的问题里，`transfer` 场景里它会出现在子 Agent 的请求中，这是交接的正常结果。
- `PARENT_ONLY_NOTE`、`CHILD_RAW_ONLY` 两个标记只检查本实验的数据流，不是通用的防泄漏机制。
- 取消只验证了“子模型正在生成读取请求时”这一个时刻：那条回复被丢弃，读取没有进入分派。
- 模型是规则模型，不代表真实模型的委派质量。
