# R10：系统提示词组装

解压后进入本目录，使用固定 Rust 1.99.1。首次构建需要联网获取工具链、
Cargo.lock 中的依赖和固定 Git revisions；不需要模型密钥或数据库。

```sh
cargo run --locked
cargo run --locked -- --json normal
cargo run --locked -- memory-update
cargo run --locked -- knowledge-injection
cargo test --locked
cargo fmt --check
cargo clippy --locked --all-targets -- -D warnings
```

全部 14 个场景名在 src/main.rs 的 SCENARIOS；非法名称返回非零退出状态。
8 个 Rust 测试核对确定性、缓存命中时的来源核验、身份和大小限制、
JSON 数据包装、完整请求字节边界、历史配对以及图执行和场景结果。

程序将 fixtures 写入自己拥有的临时目录，实际读取来源 JSON 和 README。
每轮由 graph-flow 执行 AssemblePrompt → ModelTurn → ExecuteTools，
脚本模型实现 langchain-rust 的 LLM trait，收到实际组装的 Message 列表。
两个库的 Git revision 与课程 R02/R07 一致，禁用默认 features。

policy 是应用选择的策略，工具目录由执行注册表生成，环境只取显式白名单。
选中的技能和记忆作为 JSON reference_data 进入独立 human 消息，保留来源。
这些记录是固定输入，不实现技能发现或长期记忆提取、检索和持久化。
本实验不连接真实 HTTP provider；工具 schema 作为消息内教学目录展示，
真实 provider 的原生 tools 字段需要专门适配和协议验证。

缓存只复用当前 Assembler 实例中的消息前缀。命中前仍读文件核对摘要，
完整消息不写回持久历史。它不代表 provider prompt caching。
预算按 serde_json 序列化的 Message 列表计算 UTF-8 字节，不是模型 token。
文件访问限于独占临时目录；这里没有通用目录沙箱或并发不可信文件防护。

knowledge-injection 主动让脚本模型提出被禁止的写文件请求，
验证应用执行器会拒绝，不能据此声称模型抵御了提示注入。

课程正文：https://lewislau86.github.io/learn-agent-rust/system-prompts
网站中运行 python3 scripts/verify-agent-prompts.py 生成输出、证据与学习包，
追加 --check 检查是否过期。图由 generate-learn-agent-rust-figures.py --lesson R10 生成。
