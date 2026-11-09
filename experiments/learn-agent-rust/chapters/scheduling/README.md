# R14 定时调度实验

网站正文：https://lewislau86.github.io/learn-agent-rust/scheduling

验证环境 Rust 1.99.1、edition 2024。依赖版本固定在 Cargo.lock：chrono 0.4.45、chrono-tz 0.10.4、rusqlite 0.37.0（bundled SQLite，不需要数据库服务）及 serde_json。首次构建需要网络和 C 编译器；macOS 可使用 Xcode Command Line Tools，Linux CI 使用系统 C 工具链。

```sh
cargo build --locked
cargo test --locked
cargo run --locked -- init demo.db
cargo run --locked -- add demo.db report Asia/Shanghai 09:00 coalesce --start 2026-11-07T00:59:00Z
cargo run --locked -- tick demo.db 2026-11-07T01:00:00Z
cargo run --locked -- tick demo.db 2026-11-07T01:00:00Z
cargo run --locked -- show demo.db
```

每个 cargo run 的子进程结束后才启动下一次。第二次相同 tick 新增 0 条任务。tasks 只是持久化的 daily_report / queued 记录，本包不执行报告或接入 Agent。

命令：

- `init DB`：只创建新库，拒绝已有文件。
- `add DB ID ZONE HH:MM coalesce|skip --start RFC3339`：添加不可变的每日计划。start 是已检查完的游标，首次扫描区间为 `(start, now]`，不回溯 start 以前的计划。
- `tick DB RFC3339 [--fail-after-insert|--exit-after-insert|--exit-after-commit]`：用指定时刻扫描，便于可重复实验。后两个故障直接退出进程，退出码为 73 / 74。
- `tick-now DB`：用真实 UTC 时钟扫描一次。
- `run DB N`：真实时钟轮询 N 次，范围 1–60，轮次之间等待 1 秒，遇错退出。它是有界前台程序，不安装系统服务；进程退出期间由下次启动按策略补触发。
- `show DB`：一致读取计划与队列，便于验证游标和任务身份。
- `resolve ZONE YYYY-MM-DD HH:MM`：直接查看本地时刻映射。

```sh
cargo run --locked -- resolve America/New_York 2026-03-08 02:30
cargo run --locked -- resolve America/New_York 2026-11-01 01:30
```

策略：

- 具名 IANA 时区，按当地日历每天求候选时刻，再转换成 UTC。春季不存在的时刻跳过；秋季重复时刻选较早一次。
- `coalesce` 每次扫描只补最近一个到期点，丢弃同窗口更早的点。
- `skip` 也只考虑最近一个到期点，只有它距离 now 不超过 60 秒时才入队。60 秒是本例的宽限常量。
- 每个计划最多新增 1 条任务；计划最多 32 条；队列最多 4096 条；单次向前扫描最多 31×86400 秒；支持 UTC 年份 2000–2100 的整秒时间。
- 计划配置与 ID 不可修改、删除或复用。新配置使用新 ID；暂停、删除、编辑与旧计划迁移未实现。
- 同一 SQLite 事务插入任务并推进游标。任务身份为 `ID@到期UTC秒`，另有 UNIQUE(schedule_id,due_utc)。跨进程扫描遵循 SQLite 写锁；忙时返回 store_busy，由调用方决定后续有界重试。
- 使用 DELETE journal、synchronous=FULL；存储目录应可信、可写。不要手删活动 journal。只验证指定进程退出点和本地文件系统，未演练断电、网络盘、多机调度与损坏修复。
- 唯一入队不保证外部业务只执行一次。消费者领取、工具执行、业务幂等与完成确认需要独立验证。
- 假如发生系统时钟回拨，tick 返回 clock_regression 且整次回滚；超过扫描窗口返回 scan_window_limit，需要人工选择分段补扫或新的起点。本包不自动跳过这些问题。

站内验证命令：

```sh
python3 scripts/verify-agent-scheduling.py
python3 scripts/verify-agent-scheduling.py --check
python3 scripts/generate-learn-agent-rust-figures.py --lesson R14
```

源码和测试只有一份；验证器在临时目录编译，记录真实输出，再实际解压最终 zip 重新编译并复验。测试注入固定时刻，无需等待真实日期；另外核对两次真实时钟轮询正常退出，不测长期准点率。
