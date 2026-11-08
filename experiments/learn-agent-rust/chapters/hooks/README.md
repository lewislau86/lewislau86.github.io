# R04 生命周期与 Hooks

教程：https://lewislau86.github.io/learn-agent-rust/hooks
最低 Rust 1.85，edition 2024；只依赖标准库。下载后从任意目录运行：

    rustc --edition=2024 -D warnings hooks.rs -o hooks
    ./hooks normal
    ./hooks pre-block
    ./hooks pre-panic
    ./hooks pre-timeout
    ./hooks post-error
    ./hooks stop-timeout
    rustc --edition=2024 -D warnings --test hooks.rs -o hook-tests
    ./hook-tests

Windows 将 ./hooks 和 ./hook-tests 换为对应 .exe 路径。
全部场景见源码 SCENARIOS；不带参数默认为 normal。
每次新建并清理临时工作区。请求和既有批准为固定输入，实际写文件。
普通回调在进程内；panic/hang 实验启动本程序的固定 worker 模式。
父进程超时后 kill + wait 回收直属 worker；不实现任意进程树管理或沙箱。
后置回调失败会保留写入结果。Stop 只通知一次，不强制续跑。
本包不提供模型服务、审批 UI、数据库或与 graph-flow 的集成。
outputs/ 和 evidence.json 是生成本包时的实际记录。
