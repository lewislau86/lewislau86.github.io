"""Chapter 44 experiments: where the Python layer's boundaries are.

Run inside the nautilus_trader checkout's Python environment:
    uv run --project python --no-sync python /path/to/ch44_python_boundaries.py [section ...]
"""

import ast
import os
import sys
from decimal import Decimal

import nautilus_trader
from nautilus_trader import model
from nautilus_trader.adapters.binance import BINANCE_VENUE
from nautilus_trader.backtest import BacktestEngine
from nautilus_trader.common import LogLevel
from nautilus_trader.config import BacktestEngineConfig, LoggerConfig
from nautilus_trader.execution import MakerTakerFeeModel
from nautilus_trader.model import (
    AccountType, Currency, InstrumentId, Money, OmsType, OrderSide, PositionSide, Price, Quantity, TraderId,
)
from nautilus_trader.testkit.providers import TestDataProvider, TestInstrumentProvider
from nautilus_trader.trading import Strategy

PACKAGE = os.path.dirname(nautilus_trader.__file__)


# region contract
def stub_methods(module: str, cls: str) -> set[str]:
    """Methods and attributes the generated stub declares for a class: the supported contract."""
    path = os.path.join(PACKAGE, *module.split("."), "__init__.pyi")
    for node in ast.parse(open(path).read()).body:
        if isinstance(node, ast.ClassDef) and node.name == cls:
            return {
                n.name if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) else n.target.id
                for n in node.body
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                or (isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name))
            }
    raise KeyError(cls)


V1_STRATEGY = '''
class Legacy(Strategy):
    def on_start(self):
        self.subscribe_quote_ticks(self.instrument_id)
        if self.is_initialized:
            self.log.info(f"{self.id} ready")
    def on_quote_tick(self, tick):
        self.last = self.cache.quote_tick(self.instrument_id)
    def on_order_book_deltas(self, deltas):
        pass
'''


def lint(source: str, contract: set[str]) -> None:
    """Flag on_* overrides and self.<name> uses that the Strategy stub does not declare."""
    findings = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.FunctionDef) and node.name.startswith("on_") and node.name not in contract:
            findings.append((node.lineno, f"def {node.name} is not a Strategy callback; it will never be called"))
        if (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "self"
                and node.attr not in contract and node.attr not in {"instrument_id", "last"}):
            findings.append((node.lineno, f"self.{node.attr} is not in the Strategy stub"))
    for lineno, message in sorted(findings):
        print(f"  line {lineno}: {message}")


def contract() -> None:
    stubs = [os.path.join(d, f) for d, _, fs in os.walk(PACKAGE) for f in fs if f.endswith(".pyi")]
    lines = sum(len(open(p).readlines()) for p in stubs)
    print(f"  {len(stubs)} generated .pyi files, {lines} lines")
    print(f"  HIGH_PRECISION={model.HIGH_PRECISION} FIXED_PRECISION={model.FIXED_PRECISION} "
          f"FIXED_SCALAR={model.FIXED_SCALAR:.0e}")
    strategy = stub_methods("trading", "Strategy")
    print(f"  Strategy stub declares {len(strategy)} members, "
          f"{sum(m.startswith('on_') for m in strategy)} of them on_* callbacks")
    lint(V1_STRATEGY, strategy)
# endregion contract


# region values
def values() -> None:
    p = Price.from_str("1.50")
    for label, expr in [
        ("Price + Price", lambda: p + Price.from_str("0.25")),
        ("Price + Decimal", lambda: p + Decimal("0.25")),
        ("Price + int", lambda: p + 1),
        ("Price + float", lambda: p + 0.25),
        ("Price * Price", lambda: p * p),
        ("Price(1.25, 1)", lambda: Price(1.25, 1)),
        ("Price.from_str('1.' + 16 digits)", lambda: Price.from_str("1.1234567890123456")),
        ("Price.from_str('1.' + 17 digits)", lambda: Price.from_str("1.12345678901234567")),
    ]:
        r = expr()
        print(f"  {label:34} -> {type(r).__name__:8} {r}")
    print(f"  Price.from_str('0.7') == 0.7      -> {Price.from_str('0.7') == 0.7}")
    print(f"  Decimal('0.70000') == 0.7         -> {Decimal('0.70000') == 0.7}")
    print(f"  OrderSide.NO_ORDER_SIDE           -> {OrderSide.NO_ORDER_SIDE!r}")
    print(f"  PositionSide.NO_POSITION_SIDE     -> {PositionSide.NO_POSITION_SIDE!r}")
# endregion values


# region errors
def errors() -> None:
    usd, hkd = Currency.from_str("USD"), Currency.from_str("HKD")
    cases = [
        ("Price.from_str('abc')", lambda: Price.from_str("abc")),
        ("Price('1.5', 1)", lambda: Price("1.5", 1)),
        ("Price(1.5, 17)", lambda: Price(1.5, 17)),
        ("Quantity(-1, 0)", lambda: Quantity(-1, 0)),
        ("Quantity(1, 0) - Quantity(2, 0)", lambda: Quantity(1, 0) - Quantity(2, 0)),
        ("Price(1.7e13, 0) + Price(1.7e13, 0)", lambda: Price(17014118346046, 0) + Price(17014118346046, 0)),
        ("Money USD + Money HKD", lambda: Money(1, usd) + Money(1, hkd)),
        ("InstrumentId.from_str('BAD')", lambda: InstrumentId.from_str("BAD")),
        ("TraderId('nohyphen')", lambda: TraderId("nohyphen")),
        ("Currency.from_str('XXXQ', strict=True)", lambda: Currency.from_str("XXXQ", strict=True)),
    ]
    for label, f in cases:
        try:
            f()
            print(f"  {label:38} ok")
        except Exception as e:
            print(f"  {label:38} {type(e).__name__}: {str(e)[:70]}")
# endregion errors


# region silent
class Ported(Strategy):
    """A half-ported v1 strategy: one callback renamed, one still on its v1 name."""

    def __init__(self) -> None:
        super().__init__()
        self.v1_calls = 0
        self.v2_calls = 0

    def on_start(self) -> None:
        iid = InstrumentId.from_str("ETHUSDT.BINANCE")
        try:
            self.subscribe_trade_ticks(iid)
        except AttributeError as e:
            print(f"  loud: {e}")
        self.subscribe_trades(iid)
        self.submit_order(self.order_factory.market(iid, OrderSide.BUY, Quantity.from_str("0.10000")))

    def on_trade_tick(self, tick) -> None:  # v1 name: nothing calls it in v2
        self.v1_calls += 1

    def on_trade(self, trade) -> None:
        self.v2_calls += 1


def silent() -> None:
    try:
        from nautilus_trader.live.node import TradingNode  # noqa: F401  (v1 path)
    except ImportError as e:
        print(f"  loud: {type(e).__name__}: {e}")
    engine = BacktestEngine(BacktestEngineConfig(logging=LoggerConfig(stdout_level=LogLevel.ERROR)))
    engine.add_venue(
        venue=BINANCE_VENUE, oms_type=OmsType.NETTING, account_type=AccountType.CASH, base_currency=None,
        starting_balances=[Money(1_000_000, Currency.from_str("USDT")), Money(10, Currency.from_str("ETH"))],
        fee_model=MakerTakerFeeModel(maker_rate=Decimal(0), taker_rate=Decimal(0)),
    )
    instrument = TestInstrumentProvider.ethusdt_binance()
    engine.add_instrument(instrument)
    engine.add_data(TestDataProvider.trades_from_binance_csv(instrument=instrument,
                                                            csv_name="binance/ethusdt-trades.csv")[:1000])
    strategy = Ported()
    engine.add_strategy(strategy)
    engine.run()
    print(f"  on_trade_tick (v1 name) called {strategy.v1_calls} times; on_trade called {strategy.v2_calls} times")
    order = engine.cache.orders()[0]
    print(f"  order.avg_px = {order.avg_px!r} ({type(order.avg_px).__name__}); "
          f"== {float(order.avg_px)} as float: {order.avg_px == float(order.avg_px)}")
    print(f"  strategy.state() = {strategy.state()}, is_ready() = {strategy.is_ready()}, "
          f"hasattr(is_initialized) = {hasattr(strategy, 'is_initialized')}")
    engine.dispose()
# endregion silent


def main() -> None:
    sections = {"contract": contract, "values": values, "errors": errors, "silent": silent}
    for name in sys.argv[1:] or list(sections):
        print(f"== {name}")
        sections[name]()


if __name__ == "__main__":
    main()
