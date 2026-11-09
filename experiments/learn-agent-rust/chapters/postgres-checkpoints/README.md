# P01 · PostgreSQL 检查点

教程：https://lewislau86.github.io/learn-agent-rust/postgres-checkpoints.html

独立的应用状态机实验，使用同步 postgres 0.19.12 驱动和真实 PostgreSQL 18。Cargo.lock 固定传递依赖；本次编译 Rust 1.99.1、edition 2024。模型采用固定响应，无密钥、无模型 HTTP；没有接入 graph-flow Storage 或 langchain-rust。本章单独验证持久化契约。

## 一键实验

准备 Rust、Cargo、rustfmt、Clippy、Python 3.9+ 和 PostgreSQL 18 的服务端工具（initdb、pg_ctl、postgres、psql），以普通用户在 macOS、Linux 或 WSL 运行。

```sh
export P01_PG_BIN=/opt/homebrew/opt/postgresql@18/bin  # macOS Homebrew 示例，按实际安装修改
cargo test --locked
cargo build --locked
python3 lab.py --binary target/debug/learn-agent-p01 --output ./results
```

Linux 的目录通常为 `/usr/lib/postgresql/18/bin`。未配置 P01_PG_BIN 时，脚本从 PATH 中 postgres 的真实路径寻找同目录工具。首次 Cargo 构建需要网络；后续实验只使用本机 Unix socket，不启用 TCP 监听。不要以 root 运行 initdb。

lab.py 自动创建全新的 `/tmp/p01-pg-*` 数据目录，以 p01 用户初始化独立集群，使用独有 socket 目录和固定 socket 端口 55431，开启 fsync、synchronous_commit 和 full_page_writes；运行 25 个场景后停止并删除本次临时集群。它不读取现有数据库连接变量，不操作已安装的常驻数据库服务。实验中的两次 immediate stop 只针对自己创建的集群。

results/results.json 保存每条 CLI 请求与实际响应；各 txt 是验证器的断言摘要。下载包中的 outputs/ 和 evidence.json 是打包时的记录。一键实验重新生成的 results/ 用于自己复核。

## 逐步练习（自备专用练习数据库）

以下命令仅用于一个已启动的、空白的专用练习数据库。连接凭据通过环境变量传入，程序不会打印连接串；NoTls 仅用于本地实验。

```sh
export P01_DATABASE_URL='host=/你的/socket/目录 port=55431 user=p01 dbname=postgres connect_timeout=3'
cargo run --locked -- '{"op":"init"}'
cargo run --locked -- '{"op":"create","id":"demo","profile":"read_only","granularity":"tool"}'
mkdir -p workspace
printf '启动：cargo run\n' > workspace/README.md
printf '[package]\nname = "demo"\n' > workspace/Cargo.toml
cargo run --locked -- '{"op":"step","id":"demo","expected":0,"workspace":"workspace"}'
cargo run --locked -- '{"op":"step","id":"demo","expected":2,"workspace":"workspace"}'
cargo run --locked -- '{"op":"step","id":"demo","expected":4,"workspace":"workspace"}'
cargo run --locked -- '{"op":"step","id":"demo","expected":6,"workspace":"workspace"}'
cargo run --locked -- '{"op":"show","id":"demo"}'
cargo run --locked -- '{"op":"history","id":"demo"}'
```

每个正常 step 先提交 in-flight 标记及预算，再执行模型/工具，再提交结果；因此修订分别到 2、4、6、8。每个命令都是新进程。初始快照为 revision=0，最终共 9 份快照。恢复时从 show 取得最新 revision；expected 过期会拒绝，不重新执行动作。

granularity=batch 将两个只读工具放入同一次结果保存；第一次工具之后没有可独立恢复的结果。effect profile 只允许 tool 模式：第二个工具实际追加 workspace/audit.log。调用前标记存在、结果不存在时，下一次 step 进入 reconcile，不自动重放；该状态没有自动解决命令，需要人工核对或后续专题的业务协议。

## 保存与故障接口

save 是可信应用/验证夹具的存储接口，接收完整 State、expected 和 save_id。校验状态形状与预算，以行锁和 CAS 保存最新状态及追加快照；它不做身份认证，也不把任意快照转换成合法业务迁移。实际迁移由 driver.rs 负责。save_id 相同且 expected/完整状态相同，返回原修订的 receipt；不同内容返回 save_identity_conflict。旧 receipt 不能当作当前状态，继续执行前重新 load。

故障开关：

- --gate：尝试保存前输出 ready，等待 stdin 一个字节。
- --hold：更新后、事务提交前输出 updated_uncommitted，等待一个字节。
- --fail-before-commit：普通错误并回滚。
- --exit-before-commit / --exit-after-commit：在提交两侧以 73 / 74 退出。
- --exit-after-action / --exit-after-model：动作或模型返回后、结果保存前以 75 / 76 退出。

step 的保存故障施加于结果提交；in-flight 标记先正常提交。门闩供 lab.py 组织真实进程竞争，不依赖固定 sleep 判定结果。故障接口仅用于教学。

保留上限：状态 JSON 16 KiB、每个工具内容 4096 UTF-8 字节、ID 40 个 ASCII 字符、每会话最多修订 1000，单次命令 JSON 32 KiB；固定 2 次模型与 2 次工具累计预算。快照历史没有自动清理。工作区由实验自己创建并信任，文件工具不是进程沙箱。

## 边界

应用检查点与 PostgreSQL 内部 CHECKPOINT 是不同层次。实验验证真实跨进程/数据库进程重启、提交边界与并发拒写；没有物理断电、磁盘损坏、远端网络丢包、主从切换、TLS、租户权限、旧格式迁移、真实模型或完整 Agent 集成验收。in-flight 不确定状态可能表示尚未调用、调用中或已调用但未保存；保守停下来避免自动重复，不能用它证明外部业务只执行一次。
