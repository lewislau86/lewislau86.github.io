# R19 MCP 外部工具

教程：https://lewislau86.github.io/learn-agent-rust/mcp-tools

固定 Rust 1.99.1、rmcp 3.9.0、MCP 2025-11-25（initialize 生命周期）。
此处是有意固定的协议契约，不表示 MCP 最新版本；其余依赖由 Cargo.lock 固定。
首次获取工具链与依赖需要网络，运行仅连接本工程启动的本地 stdio 服务。
无需模型密钥、Python、数据库或第三方 MCP 服务。

    cargo test --locked
    cargo run --locked -- normal demo-normal
    cargo run --locked -- dual-server demo-dual
    cargo run --locked -- denied-write demo-denied
    cargo run --locked -- write-timeout demo-timeout

最后一个参数必须是不存在的目录，父目录须存在；程序拒绝覆盖已存在的目录。
完整场景名见 src/lab.rs 的 SCENARIOS；每次运行只输出 JSON，包含完整协议帧与结果。
服务使用同一个二进制的 server 子命令，真实子进程、管道与文件操作，启动配置来自可信宿主。
命令不经过 shell，环境清空；这不是 OS 安全沙箱，也不隔离任意服务器的文件/网络权限。

本地与远端工具共用 function 描述和调用入口；本章未接入 langchain-rust、graph-flow
或真实模型。调用由固定脚本提供。role/tool_call_id 是适配器内部结果信封，接入具体
模型消息类型时还需转换；诊断重复调用的结果不可直接追加为第二条同 ID 工具消息。

注册表分页发现后一次性发布；支持命名空间、原始名称路由、受限 JSON Schema、
可信宿主写入策略、整次调用绑定的模拟审批与重复调用拒绝。
只接受 object + required + additionalProperties:false，属性类型 string + maxLength；
不支持 $ref、组合关键字或 outputSchema，遇到这些情况拒绝注册。

初始化上限 2000 ms，发现/调用上限 250 ms；测试使用真实 Tokio 时钟，不报告延迟性能。
单帧上限 65536 字节、单次注册最多 3 页、总工具最多 24 个（包含本地工具）、
每轮最多 8 次远端派发、结果最多 4096 字节。上限针对实验控制流。

超时/断连后连接不再派发，关闭时撤销注册条目，先关闭协议任务、再等待子进程；
超出退出宽限后终止并 wait，最后回收中继任务。只管理直属子进程。
write-timeout 会真实写一行后不返回成功；结果为 outcome_unknown，不重试。
发送取消/关闭管道不证明业务效果被撤销。重连、外部幂等、HTTP/OAuth 和完整 Agent
集成分别验证，均不属于本实验的已验证结论。

outputs/ 是从实际运行 JSON 和磁盘检查生成的摘要；evidence.json 保存源码哈希、
完整工具描述、协议请求/响应与场景证据。为可重复比对，省略 PID、退出耗时、
可选取消通知以及退出信号细节；验证器在现场独立检查每个 PID 已不存在。
