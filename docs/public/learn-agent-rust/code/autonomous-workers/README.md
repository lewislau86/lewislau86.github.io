# R17 自主任务领取实验

Rust 2024，rusqlite 0.37.0（bundled SQLite）、serde、serde_json；依赖由 Cargo.lock 固定。首次编译需下载依赖和本机 C 编译器。无模型密钥、无网络服务。

```sh
cargo test --locked
cargo run --locked -- tasks.db '{"op":"init"}'
cargo run --locked -- tasks.db '{"op":"add","id":"report","title":"整理日报","max_claims":3}'
cargo run --locked -- tasks.db '{"op":"claim","owner":"worker-a","now":100,"ttl":10}'
cargo run --locked -- tasks.db '{"op":"renew","id":"report","owner":"worker-a","token":1,"now":105,"ttl":10}'
cargo run --locked -- tasks.db '{"op":"claim","owner":"worker-b","now":115,"ttl":10}'
cargo run --locked -- tasks.db '{"op":"complete","id":"report","owner":"worker-a","token":1,"now":116,"result":"旧结果"}'
cargo run --locked -- tasks.db '{"op":"complete","id":"report","owner":"worker-b","token":2,"now":116,"result":"已核对"}'
cargo run --locked -- tasks.db '{"op":"show"}'
```

倒数第三条故意返回 `lease_rejected` / 退出码 1。`now` 是秒级逻辑时间夹具；省略或传 null 时，在获得写事务后读取主机 UTC Unix 秒。真实时钟模式需使用新的数据库，避免混用时间轴。有效租约为 `now < lease_until`，相等时允许接管。成功的 timed 命令（包括 empty）保存 last_now，拒绝回拨；失败命令回滚全部修改。

`claim` 自动选择按 ID 排序的第一个 pending 或过期 running 任务。没有依赖图、模型、常驻循环、通知或权限认证；owner 由可信调用方传入。任务身份不删除、不复用，token 对每个任务单调增加。每个任务最多领取 1–8 次，最多保存 32 条。耗尽后保留现场，由调用方对账；不自动标成功或无限重试。

## 本地业务副作用重放

在另一套全新文件上运行：

```sh
cargo run --locked -- replay.db '{"op":"init"}'
cargo run --locked -- replay.db '{"op":"add","id":"report","title":"整理日报","max_claims":3}'
cargo run --locked -- replay.db '{"op":"work","owner":"worker-a","now":100,"ttl":10,"ledger":"business.db","dedupe":false}' --exit-after-effect
cargo run --locked -- replay.db '{"op":"work","owner":"worker-b","now":110,"ttl":10,"ledger":"business.db","dedupe":false}'
cargo run --locked -- business.db '{"op":"effects"}'
```

第一次 worker 提交业务动作后以 75 退出，任务未完成；第二次接管后再次投递，业务数据库 calls 与 reports 都是 2 行。换全新文件，两次都使用 `dedupe:true`，calls 仍为 2 行、reports 为 1 行。该模式的业务服务在自己的事务里以 `report:<task_id>` 记录去重键和报告。一次实验固定一个模式，混用模式不在协议内。业务库没有校验租约，也没有网络，不能据此宣称分布式外部工具只执行一次。

## 故障开关与证据

`--gate` 在尝试写事务前输出 ready，等待 stdin 一个字节；`--hold` 在更新后、提交前输出 updated_uncommitted，等待一个字节。验证器用管道和检查点组织真实进程竞争。`--exit-before-commit`/`--exit-after-commit` 分别以 73/74 退出；`--fail-before-commit` 正常返回错误并回滚。这些开关用于教学故障注入。

outputs/ 保存验证器生成的 CLI 记录（键排序、数据库路径归一化），race 输出为核对后的摘要；evidence.json 保存源码摘要、12 个 Rust 测试及每个场景证据。网站仓库运行 `python3 scripts/verify-agent-workers.py --check`，会独立解压此 zip、重新编译并复验全部场景。

教程正文以 https://lewislau86.github.io/learn-agent-rust/autonomous-workers.html 为准。
