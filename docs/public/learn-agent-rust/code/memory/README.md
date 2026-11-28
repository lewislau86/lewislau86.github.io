# R09 · 跨会话记忆（ADK-Rust 3.0）

教程：https://lewislau86.github.io/learn-agent-rust/memory

工作区助手在会话 A 里听到“请记住：reply_language=中文”，进程退出；会话 B 是另一个进程，消息历史是空的，
只能从 SQLite 文件里找回这条偏好。记忆服务是 adk-memory 的 `SqliteMemoryService`（FTS5 全文检索），
写入、召回、遗忘由应用自己的工具 `remember` / `recall_memory` / `forget` 把关；对照组用 adk-tool 的
`LoadMemoryTool` 和 `PreloadMemoryTool`。模型是按规则回复的替身，只看得到自己的请求。

## 准备 ADK-Rust 源码

```sh
python3 fetch-adk-rust.py ../adk-rust     # 需要 git 与 GitHub 访问；不行时加 --method cdn
```

下面的命令都要在本目录里运行（cargo 只读取当前目录及上级目录的 `.cargo/config.toml`）。

## 运行

```sh
cargo run --locked                    # 全部 14 个场景的摘要；每一步都是程序自己启动的独立子进程
cargo run --locked -- new-process     # 某个场景的完整轨迹（每个子进程的事件、请求与结果）
cargo test --locked
cargo fmt --check
cargo clippy --locked --all-targets -- -D warnings
```

自己动手跨进程：

```sh
cargo run --locked -- chat demo.db user-1 project-a session-A "请记住：reply_language=中文"
# 上一个进程已经退出。新进程只有同一个 demo.db：
cargo run --locked -- chat demo.db user-1 project-a session-B "以后请用什么语言回答？"
cargo run --locked -- chat demo.db user-1 project-b session-C "以后请用什么语言回答？"   # 换个项目
cargo run --locked -- chat demo.db user-1 project-a session-D "以后请用什么语言回答？" --recall preload
cargo run --locked -- erase demo.db user-1 --compact
```

`chat DB USER PROJECT SESSION MESSAGE [--recall tool|load|preload]`：`tool` 是应用的 `recall_memory`（默认），
`load` 换成 `LoadMemoryTool`，`preload` 换成 `PreloadMemoryTool` 的模型前回调。

`rust-toolchain.toml` 固定 Rust 1.99.1；`Cargo.lock` 固定全部依赖（SQLite 由 sqlx 自带的源码编译，不需要系统库）。
编译时会看到 adk-core 的 3 条 `fetch_update` 弃用警告（上游固定 1.95.0），不影响本章代码的检查。

## 实验边界

- USER、PROJECT、SESSION 由命令行给出，代表可信应用传入的身份；这里没有身份认证。
- 只记住用户这一轮原话里逐字出现的 `请记住：键=值`，键只允许 `reply_language`、`run_command`。
- 没有测试多个进程同时写入；SQLite 自己的锁之外，应用没有比较版本再写。
- `erase --compact` 删除后合并全文索引并 VACUUM，文件里不再有原文；备份、日志和已经发给模型的上下文不在此列。
  不要把密钥或个人敏感信息当作练习输入。
