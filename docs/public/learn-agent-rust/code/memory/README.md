# R09 跨会话记忆实验

网站正文是教程唯一来源：https://lewislau86.github.io/learn-agent-rust/memory

Rust edition 2024，验证环境为 Rust 1.99.1。依赖 serde / serde_json，版本由 Cargo.lock 固定；首次构建需要网络，不需要模型密钥和数据库。

```sh
cargo build --locked
cargo test --locked
printf '请记住：reply_language=中文\n' > message.txt
cargo run --locked -- apply demo-store project-a session-A 1 0 user --message message.txt
# 上个进程已经结束。新进程只读取同一个磁盘目录：
cargo run --locked -- recall demo-store project-a reply_language
printf '请记住：reply_language=English\n' > message.txt
cargo run --locked -- apply demo-store project-a session-C 1 1 user --message message.txt
cargo run --locked -- recall demo-store project-a reply_language
printf '请忘记：reply_language\n' > message.txt
cargo run --locked -- apply demo-store project-a session-D 1 2 user --message message.txt
cargo run --locked -- recall demo-store project-a reply_language
```

`apply ROOT SCOPE SESSION TURN EXPECTED_REVISION ROLE --message FILE [--fail-before-rename]`

`recall ROOT SCOPE KEY`

- ROLE 只接受 user，来源身份和 SCOPE 应由可信应用提供。命令行调用者本身具有写权限；这不是身份认证或租户授权实现。
- 提取规则严格匹配“请记住：KEY=VALUE”或“请忘记：KEY”；只允许 reply_language / run_command。固定规则不是 LLM。
- 修订号是整个存储的全局序号。更新前先 recall 获得 revision；过期写入返回 revision_conflict。相同值且版本匹配时返回 unchanged，不更新原来源。
- `memory.json` 保留所有事件和原话；Forget 只是停止召回，历史、备份及已经生成的上下文仍可能保留原文。不要把密钥或敏感数据当作本教程输入。
- 限额：文件 65536 字节、64 个事件、原话 512 字节、值 160 字节。字节数均为 UTF-8。满额后拒写，需要另行设计归档与迁移。
- 写者用 create_new 创建 .memory.lock，整个读改写期间持有。崩溃可能留下锁或 .memory.pending；先确认没有活跃写者，备份并检查文件后再人工处理。程序不自动抢锁或修复损坏记录。
- 同目录临时文件 sync_all 后 rename 替换；Unix 下再同步目录。durability_unknown 表示 rename 已成功但目录同步失败，必须重新读取确认。演练只覆盖 rename 前失败，未验证断电恢复、网络盘及跨平台持久性。
- 所有写者必须遵循本例协议，并使用私人可信目录。路径检查不构成防恶意进程替换文件的沙箱。
- 召回结果是带来源的 JSON 数据，run_command 的值只作资料返回，不会被执行。接入工具循环时仍走独立权限入口。

学习包附 outputs/、evidence.json。站内维护命令：

```sh
python3 scripts/verify-agent-memory.py
python3 scripts/verify-agent-memory.py --check
python3 scripts/generate-learn-agent-rust-figures.py --lesson R09
```

验证器在临时目录编译，通过独立 CLI 进程验证保存、召回和失败分支，然后实际解压学习包、重新编译并复验。实验不读取用户的全局 Codex memory。
