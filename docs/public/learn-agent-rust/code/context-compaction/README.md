# R08 · 上下文压缩（ADK-Rust 3.0）

教程：https://lewislau86.github.io/learn-agent-rust/context-compaction

一次代码审查：第一次运行读审查规范、读 `src/first.rs`、读 `docs/` 下三份大资料；第二次运行“继续，给出结论”。
压缩由框架执行：运行之间用 `EventsCompactionConfig`，运行之内用 `IntraCompactionConfig`，`naive-trim` 用
`RunConfig::history_max_events` 只装入最近的事件作对照。摘要器是应用自写的 `FactSummarizer`：让摘要模型按
事实清单写 JSON，逐项核对值和来源，通过才交给框架；不通过就返回错误，框架保留原历史。
审查模型和摘要模型都是按规则回复的替身，只看得到各自的请求；文件工具真实读取临时目录。

## 准备 ADK-Rust 源码

```sh
python3 fetch-adk-rust.py ../adk-rust     # 需要 git 与 GitHub 访问；不行时加 --method cdn
```

下面的命令都要在本目录里运行（cargo 只读取当前目录及上级目录的 `.cargo/config.toml`）。

## 运行

```sh
cargo run --locked                    # 全部 10 个场景的摘要
cargo run --locked -- normal          # 某个场景的完整轨迹（事件、压缩摘要、每次请求的消息角色与估算 token）
cargo test --locked
cargo fmt --check
cargo clippy --locked --all-targets -- -D warnings
```

`rust-toolchain.toml` 固定 Rust 1.99.1；`Cargo.lock` 固定全部依赖。
编译时会看到 adk-core 的 3 条 `fetch_update` 弃用警告（上游固定 1.95.0），不影响本章代码的检查。

## 实验边界

- token 数是框架的估算（约 4 个 UTF-8 字节算 1 个 token，一个汉字约 3 字节），不是任何模型的 tokenizer，也不是费用。
- 事实清单是为这次固定审查声明的；核对器检查清单里的事实有没有被保留或改写，不判断任意摘要的真假。
- 会话在内存里；跨进程恢复、真实模型的摘要质量都没有验证。
