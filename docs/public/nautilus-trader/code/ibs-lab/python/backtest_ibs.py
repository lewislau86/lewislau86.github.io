"""Verify the pure-Python InternalBarStrength inside a real BacktestEngine run."""
from decimal import Decimal

import pandas as pd
from nautilus_trader.adapters.binance import BINANCE_VENUE
from nautilus_trader.backtest import BacktestEngine
from nautilus_trader.config import BacktestEngineConfig, StrategyConfig
from nautilus_trader.execution import MakerTakerFeeModel
from nautilus_trader.model import AccountType, BarType, Currency, Money, OmsType
from nautilus_trader.testkit.providers import TestDataProvider, TestInstrumentProvider
from nautilus_trader.trading import Strategy

from ibs import InternalBarStrength

PERIOD = 10
TICKS_PER_BAR = 250
BAR_TYPE = BarType.from_str("ETHUSDT.BINANCE-250-TICK-LAST-INTERNAL")


# region probe
class IbsProbe(Strategy):
    def __init__(self) -> None:
        super().__init__(StrategyConfig())
        self.ibs = InternalBarStrength(PERIOD)
        self.rows = []

    def on_start(self) -> None:
        self.register_indicator_for_bars(BAR_TYPE, self.ibs)
        self.subscribe_bars(BAR_TYPE)

    def on_bar(self, bar) -> None:
        # The framework has already fed this bar to the indicator.
        self.rows.append((float(bar.high), float(bar.low), float(bar.close),
                          self.ibs.value, self.ibs.initialized))

    def on_stop(self) -> None:
        self.unsubscribe_bars(BAR_TYPE)
# endregion probe


# region oracle
def oracle(prices: pd.Series) -> pd.DataFrame:
    """Independent check with pandas: 250-trade bars, IBS, rolling mean."""
    n = len(prices) // TICKS_PER_BAR * TICKS_PER_BAR
    groups = prices.iloc[:n].groupby(prices.index[:n] // TICKS_PER_BAR)
    bars = groups.agg(["max", "min", "last"]).set_axis(["high", "low", "close"], axis=1)
    rng = bars["high"] - bars["low"]
    ibs = ((bars["close"] - bars["low"]) / rng).where(rng > 0).dropna()
    bars["value"] = ibs.rolling(PERIOD).mean().reindex(bars.index).ffill()
    return bars
# endregion oracle


def main() -> None:
    engine = BacktestEngine(BacktestEngineConfig())
    engine.add_venue(
        venue=BINANCE_VENUE,
        oms_type=OmsType.NETTING,
        account_type=AccountType.CASH,
        base_currency=None,
        starting_balances=[Money(1_000_000, Currency.from_str("USDT")),
                           Money(10, Currency.from_str("ETH"))],
        fee_model=MakerTakerFeeModel(maker_rate=Decimal(0), taker_rate=Decimal(0)),
    )
    instrument = TestInstrumentProvider.ethusdt_binance()
    engine.add_instrument(instrument)
    trades = TestDataProvider.trades_from_binance_csv(
        instrument=instrument, csv_name="binance/ethusdt-trades.csv",
    )
    engine.add_data(trades)
    probe = IbsProbe()
    engine.add_strategy(probe)
    engine.run()

    rows = pd.DataFrame(probe.rows, columns=["high", "low", "close", "value", "initialized"])
    expected = oracle(pd.Series([float(t.price) for t in trades]))
    print(f"trades: {len(trades)}")
    print(f"bars seen by strategy: {len(rows)}, oracle bars: {len(expected)}")
    assert len(rows) == len(expected)
    assert (rows[["high", "low", "close"]].values == expected[["high", "low", "close"]].values).all()

    first = int(rows["initialized"].idxmax())
    print(f"first initialized at bar #{first + 1} (1-based)")
    assert (rows["value"].iloc[:first] == 0.0).all()
    err = (rows["value"].iloc[first:] - expected["value"].iloc[first:]).abs().max()
    print(f"max |indicator - oracle| = {err:e}")
    assert err < 1e-12

    for i in range(first, first + 3):
        r = rows.iloc[i]
        print(f"bar #{i + 1:>3}: high={r.high:.2f} low={r.low:.2f} close={r.close:.2f} ibs={r.value:.6f}")
    print(f"last bar: ibs={rows['value'].iloc[-1]:.6f}")
    print("OK")
    engine.dispose()


if __name__ == "__main__":
    main()
