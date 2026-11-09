# R03 工具权限与审批实验

教程正文以网站为准：https://lewislau86.github.io/learn-agent-rust/permissions
需要支持 edition 2024 的 Rust 稳定工具链（Rust 1.85 或更新）。无第三方依赖。

在解压后的目录中运行：

    rustc --edition=2024 -D warnings permissions.rs -o permissions
    ./permissions approve
    ./permissions wait
    ./permissions decline
    ./permissions tamper
    ./permissions replay
    ./permissions write-error
    rustc --edition=2024 -D warnings --test permissions.rs -o permission-tests
    ./permission-tests

Windows 用户将 ./permissions 与 ./permission-tests 换成对应 .exe 路径。
全部场景：read deny invalid-path unknown wait approve decline tamper replay write-error。
每次运行创建并清理自己的临时工作区，不需要从教程仓库启动。
模型请求与人工回复由程序固定生成，实际调用 std::fs 读写文件。
wait 只在本次进程内保留状态；再次启动命令会创建新会话。
这不是通用文件系统沙箱，也不提供真实模型、认证 UI 或跨进程恢复。
outputs/ 与 evidence.json 是生成学习包时的实际运行记录。
