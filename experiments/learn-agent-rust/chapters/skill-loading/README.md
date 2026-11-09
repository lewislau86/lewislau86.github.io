# R07：按需加载技能

正文以网站为准：https://lewislau86.github.io/learn-agent-rust/skill-loading

本包使用 R02 相同的 graph-flow 与 langchain-rust Git revisions，固定 Rust 1.99.1。
首次获取工具链与依赖需要网络；Linux 的原生 TLS 依赖需要 pkg-config、libssl-dev。

在解压后的 skill-loading 目录执行：

```sh
cargo fetch --locked
cargo run --locked
cargo run --locked -- repeat
cargo run --locked -- permission
cargo run --locked -- --json normal
cargo test --locked
cargo fmt --check
cargo clippy --locked --all-targets -- -D warnings
```

下载依赖后可用 cargo run --locked --offline 重跑。
场景：normal no-skill repeat unknown invalid-name changed missing oversize budget permission version-two empty-catalog。

每次运行把 skills/ 中随包提供的两份 SKILL.md 编译进程序，再复制到临时目录进行真实读取。
编辑技能示例后重新 cargo run，即可编译并使用新内容。程序不扫描用户的全局技能，
不读取密钥、不请求模型、不连接数据库。graph-flow 实际推进节点；脚本模型实现真实 LLM trait。
permission 场景是用于验证权限边界的故障注入，其中的文字不应当作为对读者或助手的指令。

本实现只扫描一个可信、静态、直接子目录集合；最多 32 项，每份文件最多 8192 字节。
读取 YAML frontmatter 的 name、description、metadata.version，其他可选字段不授予权限。
version 是本课的必填约定，Agent Skills 标准本身没有要求这个字段。
不会执行 scripts/，不会自动读 references/，没有安装器、远程发现、热更新或沙箱。
规范支持的其他可选字段和完整客户端行为不在本例覆盖范围内。

重复加载在同一会话里省略已注入的正文，但仍有工具往返和元信息开销。
SHA-256 用于检测发现之后文件是否改变，不代表签名或可信来源认证。
canonicalize 与符号链接检查仅验证自建目录的静态路径，不解决恶意进程并发替换路径的问题。
injected_bytes 只统计成功注入的技能正文 UTF-8 字节，不是 tokenizer 的 token，也不是总上下文上限。

网站维护者运行 python3 scripts/verify-agent-skills.py 更新输出、证据与 zip，
加 --check 在临时解压目录重新运行并检查产物是否过期。
