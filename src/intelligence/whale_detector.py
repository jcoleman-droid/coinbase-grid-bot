from __future__ import annotations

from collections import deque

import structlog

logger = structlog.get_logger()


class WhaleDetector:
    """Detects whale activity via price velocity (large moves in a single poll cycle).

    A 0.5%+ move in 3 seconds strongly suggests whale-sized orders.
    Computed locally from the existing price feed — no extra API calls.
    """

    def __init__(self, velocity_threshold_pct: float = 0.5):
        self._threshold = velocity_threshold_pct
        self._prices: dict[str, deque[float]] = {}

    def record_price(self, symbol: str, price: float) -> None:
        if symbol not in self._prices:
            self._prices[symbol] = deque(maxlen=5)
        self._prices[symbol].append(price)

    def get_velocity(self, symbol: str) -> float | None:
        prices = self._prices.get(symbol)
        if not prices or len(prices) < 2:
            return None
        prev = prices[-2]
        curr = prices[-1]
        if prev <= 0:
            return None
        return round(((curr - prev) / prev) * 100, 4)

    def is_whale_move(self, symbol: str) -> bool:
        vel = self.get_velocity(symbol)
        if vel is None:
            return False
        is_whale = abs(vel) >= self._threshold
        if is_whale:
            logger.info(
                "whale_move_detected",
                symbol=symbol,
                velocity_pct=vel,
                direction="up" if vel > 0 else "down",
            )
        return is_whale

    def get_all(self) -> dict[str, dict]:
        result = {}
        for sym in self._prices:
            vel = self.get_velocity(sym)
            result[sym] = {
                "velocity_pct": vel,
                "is_whale_move": self.is_whale_move(sym) if vel is not None else False,
            }
        return result
