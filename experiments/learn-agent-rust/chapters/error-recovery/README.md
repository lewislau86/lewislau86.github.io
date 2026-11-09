# 错误分类与恢复

教程：https://lewislau86.github.io/learn-agent-rust/error-recovery
最低 Rust 1.85，edition 2024；只依赖标准库，无需 Python、密钥或数据库。

    rustc --edition=2024 -D warnings error-recovery.rs -o recovery
    ./recovery backoff
    ./recovery resume-budget
    ./recovery append-unknown
    rustc --edition=2024 -D warnings --test error-recovery.rs -o recovery-tests
    ./recovery-tests

默认使用自动清理的临时目录；可提供一个尚不存在的目录，保留实际文件供检查：

    ./recovery append-unknown ./inspect-unknown

现有目录会被拒绝，不覆盖其中内容。Windows 使用对应 .exe。
全部 21 个场景见源码 SCENARIOS。不带参数等同 normal。
故障、Retry-After 值、每次尝试耗时与等待均为注入，虚拟时间不实际 sleep。
成功读取、缺文件错误和日志追加由标准库真实执行。
暂停和恢复只发生在同一进程，转移原状态的所有权并复用累计账本。
截止时间限制下次尝试的准入，不中断正在执行的文件 I/O。
写入结果不明后停止；本包不实现自动对账、业务幂等或断电持久性。
没有模型服务、消息协议集成、上下文压缩、模型切换或 graph-flow 集成。
outputs/ 与 evidence.json 是打包时的实际记录。
