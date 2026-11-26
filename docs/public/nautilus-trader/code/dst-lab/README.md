# dst-lab：第 37 章的确定性仿真实验

同一个异步小程序分别跑在真的 Tokio 和 madsim 上：五个任务在 `yield_now` 处交错、睡 3 秒、生成一个 UUID、遍历一个 `AHashMap`。每个种子在一个新的子进程里运行。依赖固定在 NautilusTrader 的提交 `364254f`。

```bash
cargo run --features sim                            # 只开特性：仍是真的 Tokio
RUSTFLAGS="--cfg madsim" cargo run --features sim   # 确定性仿真
```

两次构建的 `RUSTFLAGS` 不同，Cargo 会各自完整编译一遍。
