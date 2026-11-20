"""Chapter 40 experiments: DataActor, ExecutionAlgorithm and Controller from Python.

Run inside the nautilus_trader checkout's Python environment:
    uv run --project python --no-sync python /path/to/ch40_python_components.py [section ...]
"""

import sys
from decimal import Decimal
from functools import cache

from nautilus_trader.adapters.binance import BINANCE_VENUE
from nautilus_trader.backtest import BacktestEngine
from nautilus_trader.common import DataActor, LogLevel
from nautilus_trader.config import (
    BacktestEngineConfig, DataActorConfig, ExecutionAlgorithmConfig, ImportableControllerConfig,
    ImportableStrategyConfig, LoggerConfig, StrategyConfig,
)
from nautilus_trader.execution import MakerTakerFeeModel
from nautilus_trader.model import (
    AccountType, ActorId, BarType, Currency, CustomData, DataType, ExecAlgorithmId, InstrumentId, Money,
    OmsType, OrderSide, register_custom_data_class,
)
from nautilus_trader.model.custom import customdataclass
from nautilus_trader.testkit.providers import TestDataProvider, TestInstrumentProvider
from nautilus_trader.trading import Controller, ExecutionAlgorithm, Strategy

BAR_TYPE = BarType.from_str("ETHUSDT.BINANCE-250-TICK-LAST-INTERNAL")
LOG: list[str] = []


@cache
def instrument():
    return TestInstrumentProvider.ethusdt_binance()


@cache
def trades():
    return TestDataProvider.trades_from_binance_csv(instrument=instrument(), csv_name="binance/ethusdt-trades.csv")


def new_engine(controller=None, with_data=True) -> BacktestEngine:
    engine = BacktestEngine(BacktestEngineConfig(
        logging=LoggerConfig(stdout_level=LogLevel.ERROR), run_analysis=False, controller=controller,
    ))
    engine.add_venue(
        venue=BINANCE_VENUE, oms_type=OmsType.NETTING, account_type=AccountType.CASH, base_currency=None,
        starting_balances=[Money(1_000_000, Currency.from_str("USDT")), Money(10, Currency.from_str("ETH"))],
        fee_model=MakerTakerFeeModel(maker_rate=Decimal(0), taker_rate=Decimal(0)),
    )
    engine.add_instrument(instrument())
    if with_data:
        engine.add_data(trades())
    return engine


def try_add(label, fn, component) -> None:
    try:
        fn(component)
        print(f"  {label}: ok, id = {getattr(component, 'actor_id', None) or getattr(component, 'exec_algorithm_id', None)}")
    except RuntimeError as e:
        print(f"  {label}: RuntimeError: {e}")


# region ids
class Watcher(DataActor):
    pass


class Slicer(ExecutionAlgorithm):
    pass


def ids() -> None:
    engine = new_engine(with_data=False)
    try_add("add_actor(Watcher())", engine.add_actor, Watcher())
    try_add("add_actor(Watcher()) again", engine.add_actor, Watcher())
    try_add("add_actor(Watcher(DataActorConfig(actor_id='WATCH-2')))", engine.add_actor,
            Watcher(DataActorConfig(actor_id=ActorId("WATCH-2"))))
    try_add("add_exec_algorithm(Slicer())", engine.add_exec_algorithm, Slicer())
    engine.dispose()
# endregion ids


# region lifecycle
def lifecycle_component(base):
    class Component(base):
        def on_start(self) -> None:
            LOG.append(f"start {type(self).__name__}")

        def on_stop(self) -> None:
            LOG.append(f"stop  {type(self).__name__}")
    return Component


ActorA = type("ActorA", (lifecycle_component(DataActor),), {})
StrategyS = type("StrategyS", (lifecycle_component(Strategy),), {})
AlgoE = type("AlgoE", (lifecycle_component(ExecutionAlgorithm),), {})


def lifecycle() -> None:
    engine = new_engine(with_data=False)
    engine.add_strategy(StrategyS())          # added first
    engine.add_exec_algorithm(AlgoE())
    engine.add_actor(ActorA())                # added last
    engine.run()
    engine.dispose()
    print("  order added: StrategyS, AlgoE, ActorA")
    for line in LOG:
        print(f"  {line}")
    LOG.clear()
# endregion lifecycle


# region reentry
def reentrant(base):
    class Subscriber(base):
        def on_start(self) -> None:
            self.subscribe_signal("reentry")

        def on_signal(self, signal) -> None:
            if signal.value == "outer":
                self.publish_signal("reentry", "inner", ts_event=2)  # delivered synchronously, nested
            else:
                try:
                    self.unsubscribe_signal("reentry")
                    print(f"  {base.__name__}: nested unsubscribe ok")
                except RuntimeError as e:
                    print(f"  {base.__name__}: nested unsubscribe -> RuntimeError: {e}")
    return Subscriber


def publisher(base):
    class Publisher(base):
        def on_start(self) -> None:
            self.publish_signal("reentry", "outer", ts_event=1)
    return Publisher


def reentry() -> None:
    for base in (DataActor, Strategy):
        engine = new_engine(with_data=False)
        add = engine.add_actor if base is DataActor else engine.add_strategy
        add(reentrant(base)())
        add(publisher(base)())  # same kind, added later, so it starts after the subscriber
        engine.run()
        engine.dispose()
# endregion reentry


# region signals
class SignalSender(Strategy):
    def on_start(self) -> None:
        for value in (42, 3.5, "high", True, {"a": 1}):
            self.publish_signal("regime", value, ts_event=1)


class SignalListener(DataActor):
    def on_start(self) -> None:
        self.subscribe_signal("regime")

    def on_signal(self, signal) -> None:
        print(f"  on_signal: name={signal.name!r} value={signal.value!r} ({type(signal.value).__name__})")


def signals() -> None:
    engine = new_engine(with_data=False)
    engine.add_actor(SignalListener())  # actors start before strategies
    engine.add_strategy(SignalSender())
    engine.run()
    engine.dispose()
# endregion signals


# region custom
@customdataclass
class Sentiment:
    instrument_id: InstrumentId = InstrumentId.from_str("ETHUSDT.BINANCE")
    score: float = 0.0


register_custom_data_class(Sentiment)
SENT = []


class SentimentSender(Strategy):
    def on_start(self) -> None:
        obj = Sentiment(score=0.8, ts_event=1, ts_init=1)
        SENT.append(obj)
        self.publish_data(DataType("Sentiment"), CustomData(DataType("Sentiment"), obj))


class SentimentListener(DataActor):
    def on_start(self) -> None:
        self.subscribe_data(DataType("Sentiment"))

    def on_data(self, data) -> None:
        inner = data.data
        print(f"  on_data: {type(data).__name__} wrapping {type(inner).__name__}, score={inner.score}")
        print(f"  the payload is the publisher's own Python object: {inner is SENT[0]}")


def custom() -> None:
    engine = new_engine(with_data=False)
    engine.add_actor(SentimentListener())
    engine.add_strategy(SentimentSender())
    engine.run()
    engine.dispose()
# endregion custom


# region algo
class ThreeSlices(ExecutionAlgorithm):
    """Splits every primary order into three equal market slices."""

    def on_order(self, order) -> None:
        third = instrument().make_qty(float(order.quantity) / 3)
        for i in range(3):
            if i < 2:
                child = self.spawn_market(order, third)
                print(f"  algo: spawned {child.client_order_id} qty={child.quantity}")
                self.submit_order(child)
            else:
                cached = self.cache.order(order.client_order_id)
                print(f"  algo: last slice is the primary itself; the order passed in still says "
                      f"qty={order.quantity}, the cache says qty={cached.quantity}")
                self.submit_order(order)


class AlgoUser(Strategy):
    def on_start(self) -> None:
        self.subscribe_bars(BAR_TYPE)
        self.done = False

    def on_bar(self, bar) -> None:
        if self.done:
            return
        self.done = True
        order = self.order_factory.market(
            instrument().id, OrderSide.BUY, instrument().make_qty(0.3),
            exec_algorithm_id=ExecAlgorithmId("SLICES"),
        )
        print(f"  strategy: submit {order.client_order_id} qty={order.quantity} via SLICES")
        self.submit_order(order)

    def on_order_filled(self, event) -> None:
        print(f"  strategy: on_order_filled {event.client_order_id} qty={event.last_qty}")


def algo() -> None:
    engine = new_engine()
    engine.add_exec_algorithm(ThreeSlices(ExecutionAlgorithmConfig(exec_algorithm_id=ExecAlgorithmId("SLICES"))))
    engine.add_strategy(AlgoUser())
    engine.run()
    for o in engine.cache.orders():
        print(f"  cache: {o.client_order_id} {o.status} filled={o.filled_qty} strategy={o.strategy_id}")
    engine.dispose()
# endregion algo


# region controller
class Late(Strategy):
    def on_start(self) -> None:
        print(f"  {self.strategy_id}: on_start (created at runtime by the controller)")


class LabController(Controller):
    def on_start(self) -> None:
        sid = self.create_strategy_from_config(ImportableStrategyConfig(
            strategy_path=f"{__name__}:Late",
            config_path="nautilus_trader.config:StrategyConfig",
            config={"order_id_tag": "009"},
        ))
        print(f"  controller {self.actor_id}: created and started {sid}")


def controller() -> None:
    module = "ch40_python_components"
    engine = new_engine(with_data=False, controller=ImportableControllerConfig(
        controller_path=f"{module}:LabController",
        config_path="nautilus_trader.config:DataActorConfig",
        config={},
    ))
    engine.run()
    engine.dispose()

    # The same class added as a plain actor is never bound to the trader.
    engine = new_engine(with_data=False)
    engine.add_actor(LabController())
    try:
        engine.run()
    except RuntimeError as e:
        print(f"  added with add_actor instead: {[l for l in str(e).splitlines() if 'Error' in l][-1]}")
    engine.dispose()
# endregion controller


def main() -> None:
    sections = {
        "ids": ids, "lifecycle": lifecycle, "reentry": reentry, "signals": signals,
        "custom": custom, "algo": algo, "controller": controller,
    }
    for name in sys.argv[1:] or list(sections):
        print(f"== {name}")
        sections[name]()


if __name__ == "__main__":
    main()
