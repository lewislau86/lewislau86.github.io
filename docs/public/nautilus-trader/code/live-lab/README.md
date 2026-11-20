# live-lab：第五部分的实验

《深入理解 NautilusTrader》第 29～33 章的配套实验，每章一个 example。依赖固定在 NautilusTrader `develop` 分支的提交 `364254f`，Rust 工具链 1.100.0。线程列表读的是 Linux 的 `/proc`，在 macOS 上只会打印一行提示，其余结果不受影响。

```bash
cargo run --example ch29_runtime        # 全局运行时：懒创建、线程数、注入、同步调异步
cargo run --example ch30_live_node      # 不带客户端的 LiveNode：回调线程、单节点规则、停止宽限期（约 15 秒）
cargo run --example ch31_task_group     # TaskGroup：三种任务的两段关闭、准入、代、panic、TaskSlot
NAUTILUS_WORKER_THREADS=1 cargo run --example ch32_live_clock   # AtomicTime 与实时计时器
cargo run --example ch33_network        # GCRA 限流、退避序列、对本地 WebSocket 服务的重连（约 60 秒）
```

`ch32_live_clock` 的 C 段要把唯一的 Tokio 工作线程堵住，所以要带 `NAUTILUS_WORKER_THREADS=1` 运行。
