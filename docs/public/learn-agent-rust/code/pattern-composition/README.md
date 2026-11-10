# D08 · 模式组合与选型实战

教程：https://lewislau86.github.io/learn-agent-rust/pattern-composition

本目录可独立复制。Rust 1.99.1，固定 graph-flow git 提交，Cargo.lock 固定解析结果；首次下载依赖需要网络，之后可加 --offline。

```sh
cargo run --locked -- suite
cargo test --locked
cargo clippy --locked --all-targets -- -D warnings
```

输出字段 scenario/trace/used/limit/stop/data。stop=completed 是业务通过，图结束本身不等于通过。节点执行和派发 worker 在同一账本扣费，默认 32，budget 场景为 1。输入与角色决策均为固定夹具；真实图、Tokio 与文件范围见 evidence.json。

真实图、Tokio、报告文件与本地 HTTP；模型决策和批准仍为夹具。

下载包附 outputs/suite.json 和 evidence.json。网站唯一源码与包内容由 scripts/verify-agent-patterns.py 核对，并解压最终包离线重跑。包内没有源码依赖上级或相邻目录。

报告落盘：`cargo run --locked -- discover new-report.json`；已有文件拒绝覆盖。图内验收与 CLI 写文件并非事务恢复。

模型比较：`python3 model_compare.py self-test ./fixture-run`。真实服务由你自行配置 OPENAI_BASE_URL（含 /v1）、OPENAI_MODEL 和 OPENAI_API_KEY（如需要），再运行 `python3 model_compare.py live ./live-run --repeats 3`。

全九种变体 4 题 × 3 次重复 = 108 个计划任务，每任务最多 8 次请求、每次最多 512 生成 token。最大请求数 864；token 上限不等于费用上限。也可 `--variants single composed` 先跑 24 任务。输出目录必须不存在。只发送公开 model-cases.json，不读取项目文件；密钥只用于 Authorization，不保存到结果。服务兼容性与真实质量等待配置后实测。

报告记录计划/实际分母、失败、请求与响应模型、哈希、usage 与耗时；缺 usage 为 null，费用未知。四题公开合成诊断不用于泛化和排名。human 为脚本批准，不测真实人类；Python HTTP 对照与 Rust graph-flow 验证是独立入口，目前没有 Rust live provider 接线。
