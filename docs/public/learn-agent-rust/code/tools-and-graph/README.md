# R02：工具注册与图调度

课程正文：https://lewislau86.github.io/learn-agent-rust/tools-and-graph

本目录是独立 Cargo 工程。脚本模型实现固定版本 langchain-rust 的 LLM trait，
文件工具读取程序自己创建的临时目录；图版实际使用 graph-flow。
程序不读取模型凭据，不访问外部模型，不连接数据库。

## 运行

需要 rustup、系统 C 链接器及网络（首次获取工具链与依赖）。进入本目录：

```sh
cargo run --locked
cargo run --locked -- --json normal
cargo run --locked -- --json batch
cargo test --locked
cargo fmt --check
cargo clippy --locked --all-targets -- -D warnings
```

`rust-toolchain.toml` 固定 Rust 1.99.1；`Cargo.lock` 固定传递依赖。
两库按 Cargo.toml 中的 Git revision 获取，不依赖作者电脑的相邻 checkout。
下载并编译依赖后可加 `--offline` 重跑。

默认运行九种用例，并逐字段比较显式版与图版的全部可序列化状态。
`--json` 的用例名：normal、batch、unknown-tool、invalid-json、invalid-args、
missing-file、duplicate-id、zero-budget、turn-limit。
`tool_dispatches` 统计分发尝试，包括分发返回错误的情况，并非成功文件读取次数。
每次运行在临时目录创建固定文件，退出后由 TempDir 回收。

## 实验边界

- 这是控制流与接口接线实验，工具调用由确定性规则生成；没有测量真实模型选工具的能力。
- 同轮工具按返回顺序执行；没有启动并发工具任务。
- `Session` 和 `Context` 只在内存里使用，没有调用 SessionStorage。
- 工具只接受 `.` 和 `README.md` 的限定参数；面向程序自建的可信临时目录。
  canonicalize 检查不是防止外部进程竞争修改文件的完整沙箱。
- `completed` 对应本例的固定输出断言；通用业务任务还需要各自的完成标准。

网站维护者在仓库根目录运行 `python3 scripts/verify-learn-agent-rust-r02.py`，
会在独立临时解压目录构建、测试并生成输出、证据与下载包；
`--check` 重新执行并检查已有产物是否过期。
