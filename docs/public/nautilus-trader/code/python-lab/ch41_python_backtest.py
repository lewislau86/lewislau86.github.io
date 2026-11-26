"""Chapter 41 experiments: running backtests from Python.

Run inside the nautilus_trader checkout's Python environment:
    uv run --project python --no-sync python /path/to/ch41_python_backtest.py [section ...]
"""

import os
import sys
import tempfile
import time
from decimal import Decimal
from functools import cache

from nautilus_trader.adapters.binance import BINANCE_VENUE
from nautilus_trader.backtest import BacktestEngine, BacktestNode
from nautilus_trader.common import LogLevel
from nautilus_trader.config import (
    BacktestDataConfig, BacktestEngineConfig, BacktestRunConfig, BacktestVenueConfig,
    ImportableStrategyConfig, LoggerConfig, StrategyConfig,
)
from nautilus_trader.execution import MakerTakerFeeModel
from nautilus_trader.indicators import ExponentialMovingAverage
from nautilus_trader.model import AccountType, BarType, Currency, Money, NautilusDataType, OmsType, OrderSide
from nautilus_trader.persistence import DataCatalogConfig, ParquetDataCatalog
from nautilus_trader.testkit.providers import TestDataProvider, TestInstrumentProvider
from nautilus_trader.trading import Strategy

BAR_TYPE = BarType.from_str("ETHUSDT.BINANCE-250-TICK-LAST-INTERNAL")
MODULE = "ch41_python_backtest"  # importable configs refer to classes by module path


@cache
def instrument():
    return TestInstrumentProvider.ethusdt_binance()


@cache
def trades():
    return TestDataProvider.trades_from_binance_csv(instrument=instrument(), csv_name="binance/ethusdt-trades.csv")


# region strategy
class EmaCrossConfig(StrategyConfig):
    def __init__(self, *, fast: int = 10, slow: int = 20, **_kwargs) -> None:
        super().__init__()
        self.fast = fast
        self.slow = slow


class EmaCross(Strategy):
    def __init__(self, config: EmaCrossConfig) -> None:
        super().__init__(config)
        self.fast = ExponentialMovingAverage(config.fast)
        self.slow = ExponentialMovingAverage(config.slow)
        self.bars = 0

    def on_start(self) -> None:
        self.register_indicator_for_bars(BAR_TYPE, self.fast)
        self.register_indicator_for_bars(BAR_TYPE, self.slow)
        self.subscribe_bars(BAR_TYPE)

    def on_bar(self, bar) -> None:
        self.bars += 1
        if not self.indicators_initialized():
            return
        iid = instrument().id
        want_long = self.fast.value >= self.slow.value
        if want_long and self.portfolio.is_net_flat(iid):
            self.submit_order(self.order_factory.market(iid, OrderSide.BUY, instrument().make_qty(0.1)))
        elif not want_long and self.portfolio.is_net_long(iid):
            self.close_all_positions(iid)

    def on_stop(self) -> None:
        self.close_all_positions(instrument().id)
# endregion strategy


def engine_config(**kwargs) -> BacktestEngineConfig:
    return BacktestEngineConfig(logging=LoggerConfig(stdout_level=LogLevel.ERROR), **kwargs)


def new_engine(**kwargs) -> BacktestEngine:
    engine = BacktestEngine(engine_config(**kwargs))
    engine.add_venue(
        venue=BINANCE_VENUE, oms_type=OmsType.NETTING, account_type=AccountType.CASH, base_currency=None,
        starting_balances=[Money(1_000_000, Currency.from_str("USDT")), Money(10, Currency.from_str("ETH"))],
        fee_model=MakerTakerFeeModel(maker_rate=Decimal(0), taker_rate=Decimal(0)),
    )
    engine.add_instrument(instrument())
    return engine


def describe(label: str, r) -> None:
    pnl = r.stats_pnls.get("USDT", {}).get("PnL (total)")
    pnl_text = f"{pnl:.4f}" if pnl is not None else "n/a"
    print(f"  {label}: iterations={r.iterations} orders={r.total_orders} "
          f"positions={r.total_positions} PnL(USDT)={pnl_text}")


# region engine
def engine_run() -> None:
    engine = new_engine()
    engine.add_data(trades())
    engine.add_strategy(EmaCross(EmaCrossConfig()))
    t0 = time.perf_counter()
    engine.run()
    print(f"  run took {time.perf_counter() - t0:.2f} s")
    r = engine.get_result()
    describe("get_result()", r)
    print(f"  stats_pnls currencies: {sorted(r.stats_pnls)}; first stats_returns keys: {sorted(r.stats_returns)[:3]}")
    for name in ("generate_orders_report", "generate_order_fills_report", "generate_positions_report"):
        df = getattr(engine, name)()
        print(f"  {name}(): {type(df).__name__} {df.shape}")
    engine.dispose()
# endregion engine


# region reset
def reset_runs() -> None:
    engine = new_engine()
    t0 = time.perf_counter()
    engine.add_data(trades())
    print(f"  add_data once: {time.perf_counter() - t0:.2f} s for {len(trades())} trades")
    for fast, slow in [(10, 20), (10, 20), (5, 15)]:
        engine.clear_strategies()
        engine.add_strategy(EmaCross(EmaCrossConfig(fast=fast, slow=slow)))
        t0 = time.perf_counter()
        engine.run()
        took = time.perf_counter() - t0
        describe(f"EMA({fast},{slow}) in {took:.2f} s", engine.get_result())
        engine.reset()
    engine.dispose()
# endregion reset


# region streaming
def streaming() -> None:
    engine = new_engine()
    strategy = EmaCross(EmaCrossConfig())
    engine.add_strategy(strategy)
    data = trades()
    batch = 10_000
    for i in range(0, len(data), batch):
        engine.add_data(data[i:i + batch])
        engine.run(streaming=True)
        engine.clear_data()
    engine.end()
    describe(f"streaming, {batch} trades per batch", engine.get_result())
    print(f"  strategy saw {strategy.bars} bars")
    engine.dispose()
# endregion streaming


# region node
def node_run() -> None:
    path = tempfile.mkdtemp(prefix="nt-catalog-")
    catalog = ParquetDataCatalog(path)
    catalog.write_instruments([instrument()])
    catalog.write_trade_ticks(trades())
    files = sorted(os.path.relpath(os.path.join(d, f), path) for d, _, fs in os.walk(path) for f in fs)
    print(f"  catalog files: {files}")

    venue = BacktestVenueConfig(
        name="BINANCE", oms_type="NETTING", account_type="CASH",
        starting_balances=["1_000_000 USDT", "10 ETH"],
        fee_model=MakerTakerFeeModel(maker_rate=Decimal(0), taker_rate=Decimal(0)),
    )
    data = BacktestDataConfig(
        data_type=NautilusDataType.TradeTick,
        catalog=DataCatalogConfig(path=path),
        instrument_id=instrument().id,
    )
    strategy = ImportableStrategyConfig(
        strategy_path=f"{MODULE}:EmaCross", config_path=f"{MODULE}:EmaCrossConfig", config={"fast": 10, "slow": 20},
    )
    for chunk_size in (None, 5_000):
        config = BacktestRunConfig(
            venues=[venue], data=[data], engine=engine_config(), chunk_size=chunk_size,
            dispose_on_completion=False,
        )
        node = BacktestNode([config])
        node.build()
        node.add_strategy_from_config(config.id, strategy)
        t0 = time.perf_counter()
        results = node.run()
        took = time.perf_counter() - t0
        describe(f"BacktestNode chunk_size={chunk_size} in {took:.2f} s", results[0])
        print(f"    order fills report after the run: {node.generate_order_fills_report(config.id).shape}")
        node.dispose()
# endregion node


# region shutdown
class Grumpy(EmaCross):
    def on_bar(self, bar) -> None:
        super().on_bar(bar)
        if self.bars == 100:
            self.log.error("something is wrong, giving up")


def shutdown() -> None:
    for flag in (False, True):
        engine = new_engine(shutdown_on_error=flag)
        engine.add_data(trades())
        strategy = Grumpy(EmaCrossConfig())
        engine.add_strategy(strategy)
        engine.run()
        r = engine.get_result()
        print(f"  shutdown_on_error={flag}: bars seen={strategy.bars}, iterations={r.iterations}")
        engine.dispose()
# endregion shutdown


# region tearsheet
def tearsheet() -> None:
    from nautilus_trader.analysis.tearsheet import create_tearsheet

    engine = new_engine()
    engine.add_data(trades())
    engine.add_strategy(EmaCross(EmaCrossConfig()))
    engine.run()
    out = os.path.join(tempfile.mkdtemp(), "tearsheet.html")
    create_tearsheet(engine, output_path=out)
    print(f"  create_tearsheet wrote {os.path.getsize(out) / 1024:.0f} KiB of HTML")
    engine.dispose()
# endregion tearsheet


def main() -> None:
    sections = {
        "engine": engine_run, "reset": reset_runs, "streaming": streaming, "node": node_run,
        "shutdown": shutdown, "tearsheet": tearsheet,
    }
    for name in sys.argv[1:] or list(sections):
        print(f"== {name}")
        sections[name]()


if __name__ == "__main__":
    main()
