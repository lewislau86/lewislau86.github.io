# python-lab：第七部分的实验

每章一个脚本，分几段验证 Python 组件在 NautilusTrader v2 里是什么、回调怎样穿过 PyO3 边界、开销多大：`ch39_python_strategy.py` 对应第 39 章（Python 策略），`ch40_python_components.py` 对应第 40 章（DataActor、ExecutionAlgorithm、Controller）。依赖 nautilus_trader 2.0（`develop` 分支提交 `364254f`）编出的 Python 扩展模块和仓库自带的 `test_data/binance/ethusdt-trades.csv`。

在 nautilus_trader 的检出目录里（环境按“从零编译”一章准备）：

```bash
uv run --project python --no-sync python /path/to/ch39_python_strategy.py            # 全部
uv run --project python --no-sync python /path/to/ch39_python_strategy.py overhead   # 只跑开销测量
```

第 39 章的段落：`what`、`ids`、`callbacks`、`errors`、`weakref`、`live`、`overhead`；`live` 段会起一个不接任何交易所的 `LiveNode`，约 1 秒后自动停止。

第 40 章的段落：`ids`、`lifecycle`、`reentry`、`signals`、`custom`、`algo`、`controller`。`controller` 段用模块路径导入脚本里的类，所以要直接运行这个文件，不要改名。
