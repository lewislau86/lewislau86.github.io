# R10 · 系统提示词组装（ADK-Rust 3.0）

教程：https://lewislau86.github.io/learn-agent-rust/system-prompts

工作区助手接到任务“读取 README，解释启动命令与环境要求”。一次模型请求由几部分组成：

- 应用策略与 AGENTS.md：`static_instruction`，原样发送；
- 环境（工作区、语言、只读）：`instruction` 模板，按 `{键}` 读会话状态；
- 选中的技能：`with_skills`，放进用户这一轮；
- 工具声明，按注册顺序；
- 会话历史。

模型是按规则回复的替身，记下每一次收到的完整请求。程序据此比较前缀（全部系统消息加工具声明）有没有变。
文件工具真实读取临时目录里的 README；写文件的工具由策略在执行前拒绝。

## 准备 ADK-Rust 源码

```sh
python3 fetch-adk-rust.py ../adk-rust     # 需要 git 与 GitHub 访问；不行时加 --method cdn
```

下面的命令都要在本目录里运行（cargo 只读取当前目录及上级目录的 `.cargo/config.toml`）。

## 运行

```sh
cargo run --locked                    # 全部 13 个场景的摘要
cargo run --locked -- normal          # 某个场景的完整轨迹：事件、每次请求的角色、工具、前缀指纹与第一次请求的原文
cargo test --locked
cargo fmt --check
cargo clippy --locked --all-targets -- -D warnings
```

`rust-toolchain.toml` 固定 Rust 1.99.1；`Cargo.lock` 固定全部依赖。
编译时会看到 adk-core 的 3 条 `fetch_update` 弃用警告（上游固定 1.95.0），不影响本章代码的检查。

## 实验边界

- 前缀指纹是本章对“全部系统消息加工具声明”的 SHA-256 前 12 位，用来判断两次请求的开头是否相同；
  它不是任何服务商的缓存键，本章也没有调用服务商的前缀缓存。
- 字节数是 `contents` 序列化成 JSON 的长度，不是 token 数。
- 替身模型看到技能里的“写入 summary.txt”就会照做，用来检查执行边界；真实模型是否受诱导没有测试。
