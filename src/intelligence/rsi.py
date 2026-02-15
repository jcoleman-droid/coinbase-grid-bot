from __future__ import annotations

from collections import deque

import structlog

logger = structlog.get_logger()


class RSIIndicator:
    """Per-symbol RSI (Relative Strength Index) calculator.

    Uses the standard Wilder smoothing method over a configurable period.
    Returns 0-100 scale: <30 = oversold, >70 = overbought.
    """

    def __init__(self, period: int = 14):
        self._period = period
        self._prices: dict[str, deque[float]] = {}

    def record_price(self, symbol: str, price: float) -> None:
        if symbol not in self._prices:
            self._prices[symbol] = deque(maxlen=self._period + 1)
        self._prices[symbol].append(price)

    def get_rsi(self, symbol: str) -> float | None:
        prices = self._prices.get(symbol)
        if not prices or len(prices) < self._period + 1:
            return None

        price_list = list(prices)
        gains = []
        losses = []
        for i in range(1, len(price_list)):
            change = price_list[i] - price_list[i - 1]
            if change > 0:
                gains.append(change)
                losses.append(0.0)
            else:
                gains.append(0.0)
                losses.append(abs(change))

        avg_gain = sum(gains) / self._period
        avg_loss = sum(losses) / self._period

        if avg_loss == 0:
            return 100.0

        rs = avg_gain / avg_loss
        rsi = 100.0 - (100.0 / (1.0 + rs))
        return round(rsi, 2)

    def get_all_rsi(self) -> dict[str, float | None]:
        return {sym: self.get_rsi(sym) for sym in self._prices}

    def data_points(self, symbol: str) -> int:
        prices = self._prices.get(symbol)
        return len(prices) if prices else 0
