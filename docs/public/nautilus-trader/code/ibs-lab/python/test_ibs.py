import math

import pytest
from nautilus_trader.model import Bar, BarType, Price, Quantity

from ibs import InternalBarStrength

# Hand-computed IBS: 0.75, 0.25, 0.5, 0.0
BARS = [(12.0, 8.0, 11.0), (10.0, 8.0, 8.5), (20.0, 12.0, 16.0), (5.0, 1.0, 1.0)]


def feed(ind, bars):
    for h, l, c in bars:
        ind.update_raw(h, l, c)


def test_value_is_zero_until_initialized():
    ind = InternalBarStrength(3)
    feed(ind, BARS[:2])
    assert ind.has_inputs and not ind.initialized
    assert ind.value == 0.0


@pytest.mark.parametrize(("n_bars", "expected"), [(3, 0.5), (4, 0.25)])
def test_hand_computed_values(n_bars, expected):
    ind = InternalBarStrength(3)
    feed(ind, BARS[:n_bars])
    assert ind.initialized
    assert ind.value == pytest.approx(expected, rel=1e-9)


def test_zero_range_bar_is_skipped():
    ind = InternalBarStrength(3)
    feed(ind, BARS[:3])
    ind.update_raw(7.0, 7.0, 7.0)
    assert ind.value == pytest.approx(0.5)


@pytest.mark.parametrize("hlc", [(math.nan, 1.0, 1.0), (1.0, 2.0, 1.5), (2.0, 1.0, 3.0)])
def test_invalid_input_is_ignored(hlc):
    ind = InternalBarStrength(3)
    ind.update_raw(*hlc)
    assert not ind.has_inputs


def test_handle_bar_with_real_bar():
    bar = Bar(
        BarType.from_str("ETHUSDT.BINANCE-250-TICK-LAST-INTERNAL"),
        Price.from_str("10.00"),
        Price.from_str("12.00"),
        Price.from_str("8.00"),
        Price.from_str("11.00"),
        Quantity.from_str("1.00000"),
        0,
        0,
    )
    ind = InternalBarStrength(3)
    for _ in range(3):
        ind.handle_bar(bar)
    assert ind.value == 0.75


def test_reset():
    ind = InternalBarStrength(3)
    feed(ind, BARS)
    first = ind.value
    ind.reset()
    assert (ind.value, ind.initialized, ind.has_inputs) == (0.0, False, False)
    feed(ind, BARS)
    assert ind.value == first
