# ibs-lab：从零写一个 NautilusTrader 指标

《深入理解 NautilusTrader》第 12 章第 8 节的配套代码。指标是平均内部 K 线强度（Internal Bar Strength，IBS）：一根 K 线的 IBS 是 `(close - low) / (high - low)`，`InternalBarStrength(period)` 取最近 `period` 根的平均值。

依赖固定在 NautilusTrader `develop` 分支的提交 `364254f`，Rust 工具链 1.100.0。

## Rust

```bash
cargo test                       # 13 个单元测试和属性测试
cargo run --example backtest_ibs -- /path/to/nautilus_trader/test_data/binance/ethusdt-trades.csv
```

`backtest_ibs` 把指标注册到 `ETHUSDT.BINANCE-250-TICK-LAST-INTERNAL` K 线上跑一遍回测，再用一份独立的朴素算法从原始成交重算，两边逐根比较，最后打印 `OK`。

## Python

在已经按“从零编译”一章编好 Python 部分的 nautilus_trader 检出目录里运行：

```bash
uv run --project python --no-sync pytest /path/to/ibs-lab/python/test_ibs.py
uv run --project python --no-sync python /path/to/ibs-lab/python/backtest_ibs.py
```

Python 版是纯 Python 类，注册方式和 Rust 版相同，用 pandas 做独立核对。两个回测打印的数值应当一致。
