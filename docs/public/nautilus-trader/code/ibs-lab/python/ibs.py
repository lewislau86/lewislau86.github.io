import math
from collections import deque


class InternalBarStrength:
    """Mean Internal Bar Strength over the last `period` bars (pure Python)."""

    def __init__(self, period: int) -> None:
        if period <= 0:
            raise ValueError(f"`period` must be positive, was {period}")
        self.period = period
        self.value = 0.0
        self.initialized = False
        self.has_inputs = False
        self._window: deque[float] = deque()
        self._sum = 0.0

    def update_raw(self, high: float, low: float, close: float) -> None:
        if not (math.isfinite(high) and math.isfinite(low) and math.isfinite(close)):
            return
        if not low <= close <= high:
            return
        rng = high - low
        if rng == 0.0:
            return  # no range, no position within it
        ibs = (close - low) / rng
        self.has_inputs = True
        if len(self._window) == self.period:
            self._sum -= self._window.popleft()
        self._window.append(ibs)
        self._sum += ibs
        if len(self._window) == self.period:
            self.initialized = True
        if self.initialized:
            self.value = self._sum / self.period

    def handle_bar(self, bar) -> None:
        self.update_raw(bar.high.as_double(), bar.low.as_double(), bar.close.as_double())

    def reset(self) -> None:
        self._window.clear()
        self._sum = 0.0
        self.value = 0.0
        self.has_inputs = False
        self.initialized = False
