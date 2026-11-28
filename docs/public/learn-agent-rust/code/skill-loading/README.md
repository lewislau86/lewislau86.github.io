# R07 · 按需加载技能（ADK-Rust 3.0 / adk-skill）

教程：https://lewislau86.github.io/learn-agent-rust/skill-loading

每个场景把 `skills/` 里的两份技能复制到临时工作区的 `.skills/`，启动时由 `load_skill_index` 建成索引。
主线用 `SkillToolset`：模型先 `list_skills` 看目录，再 `load_skill` 取正文，需要时 `load_skill_resource` 读附带资源；
技能 frontmatter 里的 `allowed-tools` 只能从宿主的 `ToolRegistry` 里取工具，取出来的工具仍经过应用策略。
对照场景 `auto-inject` 用 `SkillInjector` 方式，按问题文字自动把一份技能正文放进用户消息。
模型是按规则回复的 `RuleLlm`，只看得到请求；文件工具真实读写临时目录。

## 准备 ADK-Rust 源码

```sh
python3 fetch-adk-rust.py ../adk-rust     # 需要 git 与 GitHub 访问；不行时加 --method cdn
```

下面的命令都要在本目录里运行（cargo 只读取当前目录及上级目录的 `.cargo/config.toml`）。

## 运行

```sh
cargo run --locked                    # 全部 15 个场景的摘要
cargo run --locked -- normal          # 某个场景的完整轨迹（事件 + 每次请求的消息角色与工具列表）
cargo test --locked
cargo fmt --check
cargo clippy --locked --all-targets -- -D warnings
```

`rust-toolchain.toml` 固定 Rust 1.99.1；`Cargo.lock` 固定全部依赖。
编译时会看到 adk-core 的 3 条 `fetch_update` 弃用警告（上游固定 1.95.0），不影响本章代码的检查。

## 实验边界

- 单进程、内存会话、程序自建的静态技能目录；没有远程技能库、热更新或脚本执行。
- `resource`、`two-skills` 场景记录了固定提交里的实测行为：工具执行时读不到激活记录，默认的 `ActivatedOnly` 下加载之后读资源仍被拒绝，后加载的技能覆盖先加载的（见正文第 6 节）。
- 模型是规则模型，不代表真实模型能否选中合适的技能或理解说明。
