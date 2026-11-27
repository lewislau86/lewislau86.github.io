# R04：生命周期与回调（ADK-Rust 3.0）

课程正文：https://lewislau86.github.io/learn-agent-rust/hooks

把检查、记录与收尾挂在 ADK-Rust 的四个回调位置上：`before_agent`、`before_tool`、`after_tool`、`after_agent`。
每个场景只改变一个回调的行为（拦下、出错、panic、超时、改写），或者制造一次工具失败，观察文件、模型看到的结果
和任务结果各发生了什么。模型是 `ScriptedLlm`；策略是文件里的 `WritePolicy`；文件工具写程序自建的临时目录。

## 准备 ADK-Rust 源码

```sh
python3 fetch-adk-rust.py ../adk-rust     # 需要 git 与 GitHub 访问；不行时加 --method cdn
```

下面的命令都要在本目录里运行（cargo 只读取当前目录及上级目录的 `.cargo/config.toml`）。

## 运行

```sh
cargo run --locked                    # normal
cargo run --locked -- pre-timeout
cargo run --locked -- post-error
cargo run --locked -- stop-error
cargo test --locked
cargo fmt --check
cargo clippy --locked --all-targets -- -D warnings
```

场景：normal、prompt-block、prompt-error、permission-deny、pre-block、pre-error、pre-panic、pre-timeout、
post-error、post-timeout、post-rewrite、tool-error、stop-error、stop-timeout、stop-rewrite。
`pre-panic` 会在标准错误输出打印一条 panic 信息，这是回调里故意制造的 panic，框架已经接住，运行照常继续。

`rust-toolchain.toml` 固定 Rust 1.99.1；`Cargo.lock` 固定全部依赖。编译时会看到 adk-core 的
3 条 `fetch_update` 弃用警告（上游固定 1.95.0），不影响本章代码的检查。

## 实验边界

- 回调都在同一个进程里；超时靠回调自己的 `tokio::time::timeout`，只能在 `.await` 处生效，
  打断不了阻塞线程的同步代码。需要隔离不可信或会卡死的代码，要放到单独的进程里。
- 模型请求是固定脚本；模型说“摘要已写入”并不代表写入了，任务结果看 `task_ok`。
- 只用了 Agent 自己的回调，没有用 Runner 级插件（插件的同类回调先于 Agent 的回调运行）。

网站维护者在仓库根目录运行 `python3 scripts/verify-agent-hooks.py`，`--check` 检查产物是否过期。
