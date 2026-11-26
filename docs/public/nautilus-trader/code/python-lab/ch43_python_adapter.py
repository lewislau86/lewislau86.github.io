"""Chapter 43 experiment: a complete Python adapter against a fake, Futu-like venue.

The "venue" is an in-process asyncio object standing in for Futu OpenD: it pushes quotes
for 00700.HKEX, accepts market orders after a short delay, and can lose an acknowledgement
(like OpenD returning retType = -100) while still filling the order. The adapter is written
against nautilus_trader.live.clients, registered by factory, and driven by a LiveNode.

Run inside the nautilus_trader checkout's Python environment:
    uv run --project python --no-sync python /path/to/ch43_python_adapter.py
"""

import asyncio
import threading
import time
from decimal import Decimal

from nautilus_trader.common import Environment, LogLevel
from nautilus_trader.config import (
    DataClientConfig, ExecutionClientConfig, InstrumentProviderConfig, LoggerConfig,
)
from nautilus_trader.live import LiveExecutionEngineConfig, LiveNode, LiveNodeConfig
from nautilus_trader.live.clients import (
    DataClientFactory, ExecutionClient, ExecutionClientFactory, MarketDataClient,
)
from nautilus_trader.live.providers import InstrumentProvider
from nautilus_trader.model import (
    AccountBalance, AccountId, AccountType, Currency, Equity, FillReport, InstrumentId,
    LiquiditySide, Money, OmsType, OrderSide, OrderStatus, OrderStatusReport, OrderType, Price,
    Quantity, QuoteTick, Symbol, TimeInForce, TradeId, TraderId, Venue, VenueOrderId,
)
from nautilus_trader.trading import Strategy

VENUE = Venue("HKEX")
INSTRUMENT_ID = InstrumentId.from_str("00700.HKEX")
ACCOUNT_ID = AccountId("FUTU-001")
HKD = Currency.from_str("HKD")
T0 = time.perf_counter()


def ms() -> str:
    return f"{(time.perf_counter() - T0) * 1000:7.0f} ms"


def thread() -> str:
    return threading.current_thread().name


# region venue
class FakeOpenD:
    """Stands in for the OpenD gateway: quotes, market orders, and one lost acknowledgement."""

    def __init__(self) -> None:
        self.mid = Decimal("500.0")
        self.step = 0
        self.orders: dict[str, dict] = {}  # what the venue really did, keyed by client order id

    def next_quote(self) -> tuple[Decimal, Decimal]:
        self.step += 1
        self.mid += Decimal("0.5") if (self.step // 5) % 2 == 0 else Decimal("-0.5")
        return self.mid - Decimal("0.5"), self.mid + Decimal("0.5")

    async def place_market(self, client_order_id: str, side: OrderSide, qty: Decimal, lose_ack: bool) -> dict:
        await asyncio.sleep(0.03)  # network round trip
        price = self.mid + Decimal("0.5") if side == OrderSide.BUY else self.mid - Decimal("0.5")
        record = {"venue_order_id": f"V{len(self.orders) + 1}", "price": price, "qty": qty, "side": side}
        self.orders[client_order_id] = record  # the venue filled it either way
        if lose_ack:
            raise TimeoutError("retType=-100: request timed out")
        return record
# endregion venue


OPEND = FakeOpenD()


# region provider
class LabInstrumentProvider(InstrumentProvider):
    async def load_all_async(self, filters: dict | None = None) -> None:
        self.add(Equity(
            instrument_id=INSTRUMENT_ID, raw_symbol=Symbol("00700"), currency=HKD,
            price_precision=1, price_increment=Price.from_str("0.5"),
            lot_size=Quantity.from_int(100), ts_event=0, ts_init=0,
        ))
# endregion provider


# region data
class LabDataClient(MarketDataClient):
    async def _connect(self) -> None:
        print(f"  {ms()}  data _connect on thread {thread()}, loop bound: {self.loop is not None}")
        await self.instrument_provider.initialize()
        for instrument in self.instrument_provider.list_all():
            self._handle_instrument(instrument)  # queued for the core, which owns the cache
        self._streaming = False

    async def _disconnect(self) -> None:
        self._streaming = False

    async def _subscribe_quotes(self, command) -> None:
        print(f"  {ms()}  _subscribe_quotes {[str(i) for i in command.instrument_ids]}")
        self._streaming = True
        self.create_task(self._stream(), "quote-stream")  # supervised background work

    async def _unsubscribe_quotes(self, command) -> None:
        self._streaming = False

    async def _stream(self) -> None:
        while self._streaming:
            bid, ask = OPEND.next_quote()
            now = self.clock.timestamp_ns()
            self._handle_data(QuoteTick(
                instrument_id=INSTRUMENT_ID, bid_price=Price(bid, 1), ask_price=Price(ask, 1),
                bid_size=Quantity.from_int(1000), ask_size=Quantity.from_int(1000), ts_event=now, ts_init=now,
            ))
            await asyncio.sleep(0.05)
# endregion data


# region execution
class LabExecutionClient(ExecutionClient):
    async def _connect(self) -> None:
        self.generate_account_state(
            balances=[AccountBalance(Money(1_000_000, HKD), Money(0, HKD), Money(1_000_000, HKD))],
            margins=[], reported=True, ts_event=self.clock.timestamp_ns(),
        )

    async def _disconnect(self) -> None:
        pass

    async def _generate_order_status_reports(self, command) -> list[OrderStatusReport]:
        return []

    async def _generate_fill_reports(self, command) -> list[FillReport]:
        return []

    async def _generate_position_status_reports(self, command) -> list:
        return []

    async def _submit_order(self, command) -> None:
        order = command.order
        if order.order_type != OrderType.MARKET:
            self.generate_order_denied(order, "lab venue executes market orders only")
            return
        self.generate_order_submitted(order)
        self.create_task(self._place(order), "place-order")  # return quickly, keep the queue moving

    async def _place(self, order) -> None:
        lose_ack = "lose-ack" in (order.tags or [])
        try:
            r = await OPEND.place_market(str(order.client_order_id), order.side, order.quantity.as_decimal(), lose_ack)
        except TimeoutError as e:
            # Outcome unknown: do not reject, leave it to reconciliation.
            print(f"  {ms()}  venue: {e} for {order.client_order_id}; leaving it SUBMITTED")
            return
        venue_order_id = VenueOrderId(r["venue_order_id"])
        now = self.clock.timestamp_ns()
        self.generate_order_accepted(order, venue_order_id, now)
        self.generate_order_filled(
            order, venue_order_id, None, TradeId(f"T-{r['venue_order_id']}"), order.quantity,
            Price(r["price"], 1), HKD, Money(10, HKD), LiquiditySide.TAKER, now,
        )

    async def _query_order(self, command) -> None:
        cid = str(command.client_order_id)
        r = OPEND.orders.get(cid)
        print(f"  {ms()}  _query_order {cid}: venue says {'FILLED' if r else 'unknown'}")
        if r is None:
            return
        now = self.clock.timestamp_ns()
        venue_order_id = VenueOrderId(r["venue_order_id"])
        report = OrderStatusReport(
            account_id=ACCOUNT_ID, instrument_id=INSTRUMENT_ID, venue_order_id=venue_order_id,
            order_side=r["side"], order_type=OrderType.MARKET, time_in_force=TimeInForce.GTC,
            order_status=OrderStatus.FILLED, quantity=Quantity(r["qty"], 0), filled_qty=Quantity(r["qty"], 0),
            ts_accepted=now, ts_last=now, ts_init=now, client_order_id=command.client_order_id,
            avg_px=r["price"],
        )
        fill = FillReport(
            account_id=ACCOUNT_ID, instrument_id=INSTRUMENT_ID, venue_order_id=venue_order_id,
            trade_id=TradeId(f"T-{r['venue_order_id']}"), order_side=r["side"], last_qty=Quantity(r["qty"], 0),
            last_px=Price(r["price"], 1), commission=Money(10, HKD), liquidity_side=LiquiditySide.TAKER,
            ts_event=now, ts_init=now, client_order_id=command.client_order_id,
        )
        self._handle_report(report, fills=[fill])
# endregion execution


# region factories
class LabDataClientFactory(DataClientFactory):
    @staticmethod
    def create(*, name, config, cache, clock):
        return LabDataClient(
            name=name, config=config, cache=cache, clock=clock, venue=VENUE,
            instrument_provider=LabInstrumentProvider(config.instrument_provider),
        )


class LabExecutionClientFactory(ExecutionClientFactory):
    @staticmethod
    def create(*, name, config, cache, clock, trader_id):
        client = LabExecutionClient(
            name=name, config=config, cache=cache, clock=clock, trader_id=trader_id, venue=VENUE,
            account_id=ACCOUNT_ID, account_type=AccountType.CASH, oms_type=OmsType.NETTING,
        )
        print(f"  {ms()}  factory: created {name} execution client, loop bound: {client.loop is not None}")
        return client
# endregion factories


# region strategy
class Probe(Strategy):
    def __init__(self) -> None:
        super().__init__()
        self.quotes = 0
        self.ids = []

    def on_start(self) -> None:
        print(f"  {ms()}  strategy on_start on thread {thread()}")
        self.subscribe_quotes(INSTRUMENT_ID)

    def on_quote(self, quote) -> None:
        self.quotes += 1
        if self.quotes in (3, 6):
            tags = ["lose-ack"] if self.quotes == 6 else None
            order = self.order_factory.market(INSTRUMENT_ID, OrderSide.BUY, Quantity.from_int(100), tags=tags)
            self.ids.append(order.client_order_id)
            print(f"  {ms()}  quote #{self.quotes} ask={quote.ask_price}: submit {order.client_order_id} tags={tags}")
            self.submit_order(order)

    def on_order_filled(self, event) -> None:
        print(f"  {ms()}  on_order_filled {event.client_order_id} {event.last_qty} @ {event.last_px} on thread {thread()}")

    def on_stop(self) -> None:
        for cid in self.ids:
            o = self.cache.order(cid)
            print(f"  {ms()}  on_stop: {cid} status={o.status} filled={o.filled_qty}")
        pos = self.portfolio.net_position(INSTRUMENT_ID)
        print(f"  {ms()}  on_stop: net position {pos}, quotes seen {self.quotes}")
# endregion strategy


# region node
def main() -> None:
    config = LiveNodeConfig(
        environment=Environment.LIVE,
        trader_id=TraderId("LAB-001"),
        logging=LoggerConfig(stdout_level=LogLevel.ERROR),
        delay_post_stop_secs=0.5,
        data_clients={"LAB": DataClientConfig(instrument_provider=InstrumentProviderConfig(load_all=True))},
        exec_clients={"LAB": ExecutionClientConfig()},
        exec_engine=LiveExecutionEngineConfig(reconciliation_startup_delay_secs=1.0),
    )
    node = LiveNode.build(
        "LAB", config,
        data_factories={"LAB": LabDataClientFactory},
        exec_factories={"LAB": LabExecutionClientFactory},
    )
    node.add_strategy(Probe())
    threading.Timer(10.0, node.handle().stop).start()
    print(f"  {ms()}  node.run() on thread {thread()}")
    node.run()
    print(f"  {ms()}  node.run() returned")
    node.dispose()
# endregion node


if __name__ == "__main__":
    main()
