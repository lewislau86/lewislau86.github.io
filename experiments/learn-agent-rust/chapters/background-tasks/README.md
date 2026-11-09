# R13：后台任务独立实验

教程：https://lewislau86.github.io/learn-agent-rust/background-tasks

最低 Rust 1.85（edition 2024），只依赖标准库。无需模型密钥、Cargo 依赖、网络或数据库。

```sh
rustc --edition=2024 -D warnings background-tasks.rs -o background
./background normal
./background cancel
./background notifications
./background shutdown
rustc --edition=2024 -D warnings --test background-tasks.rs -o background-tests
./background-tests
```

Windows 使用对应的 .exe。源码 SCENARIOS 列出了全部 14 个场景；默认场景是 normal。

默认在自动清理的临时目录运行；可指定一个尚不存在的目录，检查真实结果：

```sh
./background normal ./inspect-normal
cat ./inspect-normal/job-1.txt
./background cancel ./inspect-cancel
```

已有目录会被拒绝，里面的文件不会被覆盖。场景结束后线程全部 join，显式指定的实验目录保留。

实验使用真实 OS 线程与真实文件写入。Condvar 的 permits 是实验控制门，用来精确观察指定写入次数，未使用 sleep 伪造耗时或竞态。前台只执行固定脚本步骤，未接入 LLM、langchain-rust 或 graph-flow。

并发上限 2；满载直接拒绝，不排队。运行记录只存在于本进程。终态历史与输出文件最多保留最近 4 条，通知缓冲最多 1 条，通知溢出时可查询状态。poll 在宿主事件循环边界调用；query 返回上次收集的快照。

取消是协作请求；本实验在小块本地文件写入之间检查取消，并在同一互斥锁中决定取消或发布谁先发生。不会回滚已发布文件；不保证阻塞系统调用、外部进程树或远端操作可被中断。

shutdown 关闭准入、取消剩余任务并 join；Drop 做同样清理。它没有强制终止超时，依赖 worker 响应取消。panic 回收只在 unwind 模式生效；默认 rustc 即为该模式。进程被强杀、panic=abort、断电恢复及跨进程重放均未实现。

outputs/ 与 evidence.json 保存打包时的实际结果。仓库中运行 python3 scripts/verify-agent-background.py 可重新生成全部输出与下载包；--check 会重跑验证、从最终下载包解压编译并复验。
