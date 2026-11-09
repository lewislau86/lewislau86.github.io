# R12 持久化任务系统

教程：https://lewislau86.github.io/learn-agent-rust/task-system

Rust 1.99.1，edition 2024；依赖标准库、serde、serde_json。
首次下载工具链与依赖需要网络；运行无需模型密钥或数据库。

    cargo build --locked
    cargo test --locked
    cargo clippy --locked --all-targets -- -D warnings
    cargo run --locked -- demo init
    cargo run --locked -- demo apply 0 '{"op":"add","id":"readme","title":"读取项目说明","depends_on":[],"max_attempts":2}'
    cargo run --locked -- demo apply 1 '{"op":"add","id":"guide","title":"整理启动指南","depends_on":["readme"],"max_attempts":2}'
    cargo run --locked -- demo apply 2 '{"op":"start","id":"readme"}'
    cargo run --locked -- demo show
    cargo run --locked -- demo apply 3 '{"op":"complete","id":"readme","attempt":1,"result":"已核对启动命令 cargo run"}'

每条命令是独立进程。apply 的数字是整板 revision；complete/fail 还要匹配 attempt。
操作包括 add / set_dependencies / start / complete / fail / retry。
完成、失败由可信调用者提供；程序不执行任务标题中的命令。
Running 在重启后保留，待核对；retry 只接受 Failed，保留累计 attempts 和 last_error。
最多一个 Running 任务。文件锁串行化 CLI 命令，不提供租约或多执行者领取。

tasks.json 保存整板快照；.tasks.lock 是保留的锁文件，锁状态由操作系统管理。
保存：校验 -> 独占新建 .tasks.pending -> 写入并 sync_all -> 同目录 rename。
Unix 再同步父目录，之后才返回成功。加载失败会报错并保留原始数据。
已本地验证 macOS arm64；CI 配置在 Ubuntu 重验。未实测 Windows、网络文件系统或断电。

apply 的 JSON 参数后可附加实验选项：
--fail-before-rename / --fail-after-rename / --pause-before-rename / --pause-after-commit。
pause 会输出并刷新 JSON event，然后等待 stdin 字节；验证脚本在此 kill + wait。
rename 前 kill 会遗留 .tasks.pending，程序保留它供检查并拒绝新的保存。
仅在专用实验目录确认无写进程、正式快照有效后，才可核对并移走未提交候选文件。
不要删除 .tasks.lock：文件存在不表示有人持锁。
committed=true 表示已越过 rename 边界，应重读快照；它不承诺断电持久性。
外部动作与快照的原子性由后续可靠性专题讨论。

outputs/ 是实际 CLI 返回字段整理的摘要；evidence.json 包含原始返回与文件检查记录。
网站仓库 scripts/verify-agent-tasks.py 负责生成证据；运行本包不需要 Python。
