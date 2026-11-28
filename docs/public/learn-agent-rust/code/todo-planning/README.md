# R05 · 可见的任务清单（ADK-Rust 3.0）

教程：https://lewislau86.github.io/learn-agent-rust/todo-planning

清单存在会话状态（session state）的 `plan` 键里：`todo_write` 工具读出当前清单，整批校验候选清单，
通过后写进这次调用的 `state_delta`，由框架合并进会话状态。每次请求模型之前，`before_model` 回调把最新清单
作为一条 system 内容放进请求。模型是按规则回复的 `PlanLlm`，只看得到请求内容；文件工具真实读取临时目录。

## 准备 ADK-Rust 源码

```sh
python3 fetch-adk-rust.py ../adk-rust     # 需要 git 与 GitHub 访问；不行时加 --method cdn
```

下面的命令都要在本目录里运行（cargo 只读取当前目录及上级目录的 `.cargo/config.toml`）。

## 运行

```sh
cargo run --locked                    # 全部 24 个场景的摘要
cargo run --locked -- normal          # 某个场景的完整轨迹，另见 claims-only、template-only 等
cargo test --locked
cargo fmt --check
cargo clippy --locked --all-targets -- -D warnings
```

`rust-toolchain.toml` 固定 Rust 1.99.1；`Cargo.lock` 固定全部依赖。
编译时会看到 adk-core 的 3 条 `fetch_update` 弃用警告（上游固定 1.95.0），不影响本章代码的检查。

## 实验边界

- 会话服务是内存版：同一进程里同一会话的下一次运行能看到清单，进程退出后清单就没了。
- `goal_verified` 是这个固定任务的独立验收：成功读取一次，最终答案等于“启动说明：”加读取到的完整正文；不是通用的质量判定器。
- 应用策略拒绝 `write_file`；清单里写着“写入 summary.txt”也不会让它执行。
- 模型是规则模型，不代表真实模型会不会主动列计划、何时更新。
