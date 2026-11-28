# K02 · 联网搜索（ADK-Rust 3.0）

教程：https://lewislau86.github.io/learn-agent-rust/web-search

工作区助手被问到“ADK-Rust 3.0 什么时候发布”，本地资料里没有，要上网查。搜索走 adk-harness 的受管 `web_search`：

- 策略决定能不能搜、要不要先问人；
- 搜索后端由应用提供，这里是离线的假后端，按场景返回固定结果；
- 结果经过筛查（标出注入句、遮住密钥、丢掉内网地址），放进 `<untrusted-content>` 块再交给模型；
- 应用最后核对：回答里的链接是不是这一轮真的搜到的。

模型是按规则回复的替身，“人”是按场景批准或拒绝的替身。没有任何网络请求。

## 准备 ADK-Rust 源码

```sh
python3 fetch-adk-rust.py ../adk-rust     # 需要 git 与 GitHub 访问；不行时加 --method cdn
```

下面的命令都要在本目录里运行（cargo 只读取当前目录及上级目录的 `.cargo/config.toml`）。

## 运行

```sh
cargo run --locked                    # 全部 10 个场景的摘要
cargo run --locked -- screening       # 某个场景的完整轨迹（事件、问人记录、后端收到的查询、回答）
cargo test --locked
cargo fmt --check
cargo clippy --locked --all-targets -- -D warnings
```

## 可选：接真实的搜索后端

```sh
SEARXNG_URL=http://localhost:8888 cargo run --locked -- live "adk-rust 3.0 release"
DEEPSEEK_API_KEY=sk-... cargo run --locked -- live "adk-rust 3.0 release"
```

`live` 把离线假后端换成 adk-harness 自带的 `SearxngSearch`（自建 SearXNG，不需要 key；实例要在 `settings.yml` 的
`search.formats` 里开启 `json`，否则返回 403）或 `DeepSeekSearch`（需要 DeepSeek 的 API key，返回结果的搜索按次计费），
其余接线完全相同：同样经过策略、问人（替身批准这次搜索）、筛查和不可信内容块，打印整条轨迹。
它需要网络，结果每次都可能不同，不在验证范围内。

`rust-toolchain.toml` 固定 Rust 1.99.1；`Cargo.lock` 固定全部依赖。
编译时会看到 adk-core 的 3 条 `fetch_update` 弃用警告（上游固定 1.95.0），不影响本章代码的检查。

## 实验边界

- adk-harness 在 ADK-Rust 3.0 里是 Beta：接口可能在小版本之间变化。
- 筛查按英文短语、角色标签和密钥格式匹配；中文写的同一句指令不会被标出来。
- 服务商在模型内部执行的搜索（Gemini `google_search`、Anthropic `web_search` 等）不经过这条受管路径，本章只在正文里说明。
