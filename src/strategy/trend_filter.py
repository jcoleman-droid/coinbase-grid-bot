from __future__ import annotations

from collections import deque
from enum import Enum

import structlog

logger = structlog.get_logger()


class TrendDirection(str, Enum):
    UP = "up"
    DOWN = "down"
    NEUTRAL = "neutral"


class TrendFilter:
    """Per-pair trend detection using SMA crossover on polled prices.

    Collects prices from the orchestrator's 5-second poll cycle.
    Short SMA > Long SMA = uptrend (allow buys).
    Short SMA < Long SMA = downtrend (block buys, allow sells only).
    Until enough data is collected, returns NEUTRAL (allows all trades).
    """

    def __init__(
        self,
        short_window: int = 10,
        long_window: int = 60,
    ):
        self._short_window = short_window
        self._long_window = long_window
        self._histories: dict[str, deque[float]] = {}

    def record_price(self, symbol: str, price: float) -> None:
        if symbol not in self._histories:
            self._histories[symbol] = deque(maxlen=self._long_window)
        self._histories[symbol].append(price)

    def get_trend(self, symbol: str) -> TrendDirection:
        history = self._histories.get(symbol)
        if not history or len(history) < self._long_window:
            return TrendDirection.NEUTRAL

        prices = list(history)
        short_sma = sum(prices[-self._short_window :]) / self._short_window
        long_sma = sum(prices[-self._long_window :]) / self._long_window

        if short_sma > long_sma:
            return TrendDirection.UP
        elif short_sma < long_sma:
            return TrendDirection.DOWN
        return TrendDirection.NEUTRAL

    def should_allow_buy(self, symbol: str) -> bool:
        trend = self.get_trend(symbol)
        if trend == TrendDirection.DOWN:
            logger.info("trend_filter_blocked_buy", symbol=symbol, trend=trend.value)
            return False
        return True

    def get_all_trends(self) -> dict[str, TrendDirection]:
        return {sym: self.get_trend(sym) for sym in self._histories}

    def data_points(self, symbol: str) -> int:
        history = self._histories.get(symbol)
        return len(history) if history else 0
