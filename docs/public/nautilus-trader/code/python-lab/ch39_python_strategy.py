"""Chapter 39 experiments: what a Python strategy is, and what crossing the boundary costs.

Run inside the nautilus_trader checkout's Python environment:
    uv run --project python --no-sync python /path/to/ch39_python_strategy.py
"""

import gc
import sys
import threading
import time
from datetime import timedelta
from decimal import Decimal

from nautilus_trader.adapters.binance import BINANCE_VENUE
from nautilus_trader.backtest import BacktestEngine
from nautilus_trader.common import Environment, LogLevel
from nautilus_trader.config import BacktestEngineConfig, LoggerConfig, StrategyConfig
from nautilus_trader.execution import MakerTakerFeeModel
from nautilus_trader.live import LiveNode
from nautilus_trader.model import (
    AccountType, BarType, Currency, Money, OmsType, OrderSide, StrategyId, TraderId,
)
from nautilus_trader.testkit.providers import TestDataProvider, TestInstrumentProvider
from nautilus_trader.trading import Strategy

INSTRUMENT = TestInstrumentProvider.ethusdt_binance()
TRADES = TestDataProvider.trades_from_binance_csv(instrument=INSTRUMENT, csv_name="binance/ethusdt-trades.csv")
BAR_TYPE = BarType.from_str("ETHUSDT.BINANCE-250-TICK-LAST-INTERNAL")
MAIN = threading.get_ident()


def new_engine() -> BacktestEngine:
    engine = BacktestEngine(BacktestEngineConfig(
        trader_id=TraderId("BACKTESTER-001"),
        logging=LoggerConfig(stdout_level=LogLevel.ERROR),
    ))
    engine.add_venue(
        venue=BINANCE_VENUE, oms_type=OmsType.NETTING, account_type=AccountType.CASH, base_currency=None,
        starting_balances=[Money(1_000_000, Currency.from_str("USDT")), Money(10, Currency.from_str("ETH"))],
        fee_model=MakerTakerFeeModel(maker_rate=Decimal(0), taker_rate=Decimal(0)),
    )
    engine.add_instrument(INSTRUMENT)
    engine.add_data(TRADES)
    return engine


# region what
def what_is_it() -> None:
    class Mine(Strategy):
        def on_bar(self, bar) -> None:
            pass

    print("Strategy.on_bar :", type(Strategy.on_bar).__name__, "(implemented in Rust)")
    print("Mine.on_bar     :", type(Mine.on_bar).__name__, "(your Python override)")
    print("Mine.on_trade   :", type(Mine.on_trade).__name__, "(inherited from Rust)")
    s = Mine()
    print("before registration: strategy_id =", s.strategy_id)
    try:
        s.clock
    except RuntimeError as e:
        print("before registration: self.clock ->", e)
# endregion what


# region ids
def strategy_ids() -> None:
    class Mine(Strategy):
        pass

    engine = new_engine()
    strategies = [Mine(), Mine(), Mine(StrategyConfig(order_id_tag="007"))]
    for s in strategies:
        engine.add_strategy(s)
    print("  registered ids:", [str(s.strategy_id) for s in strategies])
    for wanted in ("LAB-001", "LAB-002"):
        try:
            engine.add_strategy(Mine(StrategyConfig(strategy_id=StrategyId(wanted))))
            print(f"  add {wanted}: ok")
        except RuntimeError as e:
            print(f"  add {wanted}: RuntimeError: {e}")
    engine.dispose()
# endregion ids


# region callbacks
class Probe(Strategy):
    """Records where callbacks run and what the objects it receives are."""

    def __init__(self) -> None:
        super().__init__()
        self.bars = 0
        self.first_bar = None
        self.threads = set()
        self.order = None

    def on_start(self) -> None:
        self.threads.add(threading.get_ident())
        self.subscribe_bars(BAR_TYPE)

    def on_bar(self, bar) -> None:
        self.bars += 1
        self.threads.add(threading.get_ident())
        if self.first_bar is None:
            self.first_bar = bar
        if self.bars == 3:
            self.order = self.order_factory.market(INSTRUMENT.id, OrderSide.BUY, INSTRUMENT.make_qty(0.1))
            self.submit_order(self.order)
            print(f"  bar 3: submitted {self.order.client_order_id}, held object status = {self.order.status}")

    def on_order_filled(self, event) -> None:
        cached = self.cache.order(self.order.client_order_id)
        print(f"  on_order_filled: held object status = {self.order.status}, cache.order(...) status = {cached.status}")
        cached_again = self.cache.order(self.order.client_order_id)
        print(f"  two cache reads are the same object: {cached is cached_again}")


def callbacks() -> None:
    engine = new_engine()
    probe = Probe()
    engine.add_strategy(probe)
    engine.run()
    print(f"  bars delivered: {probe.bars}")
    print(f"  callbacks ran on the thread that called engine.run(): {probe.threads == {MAIN}}")
    print(f"  first bar kept after the run: close = {probe.first_bar.close}")
    engine.dispose()
# endregion callbacks


# region errors
class Faulty(Strategy):
    def __init__(self) -> None:
        super().__init__()
        self.bars = 0

    def on_start(self) -> None:
        self.subscribe_bars(BAR_TYPE)

    def on_bar(self, bar) -> None:
        self.bars += 1
        if self.bars == 3:
            raise ValueError("boom in on_bar")


class FaultyStart(Strategy):
    def on_start(self) -> None:
        raise ValueError("boom in on_start")


def errors() -> None:
    engine = new_engine()
    engine.add_strategy(FaultyStart())
    try:
        engine.run()
        print("  on_start raised: engine.run() returned normally")
    except RuntimeError as e:
        print(f"  on_start raised: engine.run() -> RuntimeError: {str(e).splitlines()[0]}")
    engine.dispose()

    engine = new_engine()
    faulty = Faulty()
    engine.add_strategy(faulty)
    try:
        engine.run()
        print(f"  engine.run() returned normally; on_bar was called {faulty.bars} times")
    except Exception as e:
        first = str(e).splitlines()[0]
        print(f"  engine.run() raised {type(e).__name__}: {first}")
        print(f"  on_bar was called {faulty.bars} times before the run stopped")
    engine.dispose()
# endregion errors


# region weakref
CALLS = {"on_bar": 0}


class Unreferenced(Strategy):
    def on_start(self) -> None:
        self.subscribe_bars(BAR_TYPE)

    def on_bar(self, bar) -> None:
        CALLS["on_bar"] += 1


def weakref_demo() -> None:
    engine = new_engine()
    engine.add_strategy(Unreferenced())  # no Python reference kept
    gc.collect()
    engine.run()
    print(f"  strategy added without keeping a reference: on_bar called {CALLS['on_bar']} times")
    engine.dispose()
# endregion weakref


# region overhead
class Empty(Strategy):
    def __init__(self, subscribe: bool) -> None:
        super().__init__()
        self.subscribe = subscribe

    def on_start(self) -> None:
        if self.subscribe:
            self.subscribe_trades(INSTRUMENT.id)


class Passing(Empty):
    def on_trade(self, trade) -> None:
        pass


class Reading(Empty):
    def __init__(self, subscribe: bool) -> None:
        super().__init__(subscribe)
        self.total = 0.0

    def on_trade(self, trade) -> None:
        self.total += float(trade.price) * float(trade.size)


class CacheReading(Empty):
    def on_trade(self, trade) -> None:
        self.cache.instrument(trade.instrument_id)


def timed(strategy: Strategy) -> float:
    engine = new_engine()
    engine.add_strategy(strategy)
    t0 = time.perf_counter()
    engine.run()
    elapsed = time.perf_counter() - t0
    engine.dispose()
    return elapsed


def overhead() -> None:
    n = len(TRADES)
    rows = [
        ("not subscribed", Empty(False)),
        ("subscribed, on_trade not overridden", Empty(True)),
        ("subscribed, on_trade: pass", Passing(True)),
        ("subscribed, on_trade reads price and size", Reading(True)),
        ("subscribed, on_trade queries cache.instrument", CacheReading(True)),
    ]
    base = None
    for label, strategy in rows:
        best = min(timed(type(strategy)(strategy.subscribe)) for _ in range(3))
        if base is None:
            base = best
            print(f"  {label:<46} {best:6.3f} s")
        else:
            print(f"  {label:<46} {best:6.3f} s  (+{(best - base) / n * 1e6:5.2f} µs per trade)")
# endregion overhead


# region live
class LiveProbe(Strategy):
    """In a LiveNode: which threads run callbacks and timer callbacks."""

    def __init__(self) -> None:
        super().__init__()
        self.seen = []

    def note(self, what: str) -> None:
        self.seen.append((what, threading.current_thread().name, threading.get_ident() == MAIN))

    def on_start(self) -> None:
        self.note("on_start")
        self.clock.set_timer("plain", timedelta(milliseconds=300))
        self.clock.set_timer("with_callback", timedelta(milliseconds=300), callback=self.on_timer)

    def on_time_event(self, event) -> None:
        self.note(f"on_time_event({event.name})")

    def on_timer(self, event) -> None:
        self.note(f"callback({event.name})")

    def on_stop(self) -> None:
        self.note("on_stop")


def live_node() -> None:
    node = (
        LiveNode.builder("LAB", TraderId("LAB-001"), Environment.LIVE)
        .with_reconciliation(False)
        .with_delay_post_stop_secs(0)
        .with_logging(LoggerConfig(stdout_level=LogLevel.ERROR))
        .build()
    )
    probe = LiveProbe()
    node.add_strategy(probe)

    # A pure-Python thread that only needs the GIL: does it make progress while run() blocks?
    ticks = {"n": 0}
    stop = threading.Event()

    def spin() -> None:
        while not stop.is_set():
            ticks["n"] += 1

    # Baseline: the same loop for the same time, with the main thread just sleeping.
    spinner = threading.Thread(target=spin, name="spinner")
    spinner.start()
    time.sleep(1.1)
    stop.set()
    spinner.join()
    baseline = ticks["n"]
    ticks["n"] = 0
    stop.clear()

    spinner = threading.Thread(target=spin, name="spinner")
    spinner.start()
    handle = node.handle()
    threading.Timer(1.0, handle.stop).start()
    t0 = time.perf_counter()
    node.run()
    elapsed = time.perf_counter() - t0
    stop.set()
    spinner.join()
    node.dispose()

    for what, name, on_main in probe.seen[:6] + probe.seen[-1:]:
        print(f"  {what:<28} thread={name:<12} main thread={on_main}")
    print(f"  spinner alone for 1.10 s (main thread sleeping): {baseline:,} loops")
    print(f"  spinner while run() blocked for {elapsed:.2f} s: {ticks['n']:,} loops")
# endregion live


def main() -> None:
    sections = {
        "what": what_is_it, "ids": strategy_ids, "callbacks": callbacks,
        "errors": errors, "weakref": weakref_demo, "live": live_node, "overhead": overhead,
    }
    names = sys.argv[1:] or list(sections)
    print(f"{len(TRADES)} trades loaded")
    for name in names:
        print(f"== {name}")
        sections[name]()


if __name__ == "__main__":
    main()
