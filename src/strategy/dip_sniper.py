from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass

import structlog

from ..config.schema import DipSniperConfig
from ..exchange.base import ExchangeInterface
from ..position.tracker import MultiPairPositionTracker

logger = structlog.get_logger()


@dataclass
class DipPosition:
    symbol: str
    entry_price: float
    amount: float
    entry_time: float
    take_profit_price: float
    stop_loss_price: float


class DipSniper:
    """Quick dip-buy strategy: detect sharp drops, buy, exit at TP/SL."""

    def __init__(
        self,
        config: DipSniperConfig,
        exchange: ExchangeInterface,
        position_tracker: MultiPairPositionTracker,
    ):
        self._config = config
        self._exchange = exchange
        self._position = position_tracker
        self._price_windows: dict[str, deque[float]] = {}
        self._active: dict[str, DipPosition] = {}
        self._cooldown_until: dict[str, float] = {}

    def record_price(self, symbol: str, price: float) -> None:
        if symbol not in self._price_windows:
            self._price_windows[symbol] = deque(maxlen=self._config.lookback_count)
        self._price_windows[symbol].append(price)

    async def evaluate(self, symbol: str, current_price: float) -> None:
        if current_price <= 0:
            return

        self.record_price(symbol, current_price)

        # If we have an active position, check TP/SL
        if symbol in self._active:
            await self._check_exit(symbol, current_price)
            return

        # Otherwise, check for dip entry
        if self._is_in_cooldown(symbol):
            return

        if self._detect_dip(symbol):
            await self._enter(symbol, current_price)

    def _detect_dip(self, symbol: str) -> bool:
        window = self._price_windows.get(symbol)
        if not window or len(window) < self._config.lookback_count:
            return False

        prices = list(window)
        window_high = max(prices[:-1])
        current = prices[-1]

        if window_high <= 0:
            return False

        pct_change = ((current - window_high) / window_high) * 100

        if pct_change <= self._config.dip_threshold_pct:
            logger.info(
                "dip_detected", symbol=symbol,
                pct_change=round(pct_change, 2),
                window_high=round(window_high, 8),
                current=round(current, 8),
            )
            return True
        return False

    async def _enter(self, symbol: str, price: float) -> None:
        if not self._position.can_afford_buy(self._config.position_size_usd):
            return

        amount = self._config.position_size_usd / price
        try:
            result = await self._exchange.place_market_order(symbol, "buy", amount)
            fill_price = result.avg_fill_price or result.price
            fill_amount = result.filled_amount or amount

            self._position.record_fill(
                symbol, "buy", fill_amount, fill_price, result.fee,
            )

            self._active[symbol] = DipPosition(
                symbol=symbol,
                entry_price=fill_price,
                amount=fill_amount,
                entry_time=time.time(),
                take_profit_price=fill_price * (1 + self._config.take_profit_pct / 100),
                stop_loss_price=fill_price * (1 - self._config.stop_loss_pct / 100),
            )

            logger.info(
                "dip_sniper_buy", symbol=symbol,
                amount=round(fill_amount, 6), price=round(fill_price, 8),
                tp=round(self._active[symbol].take_profit_price, 8),
                sl=round(self._active[symbol].stop_loss_price, 8),
            )
        except Exception as e:
            logger.error("dip_sniper_buy_failed", symbol=symbol, error=str(e))

    async def _check_exit(self, symbol: str, current_price: float) -> None:
        pos = self._active[symbol]

        exit_reason = None
        if current_price >= pos.take_profit_price:
            exit_reason = "take_profit"
        elif current_price <= pos.stop_loss_price:
            exit_reason = "stop_loss"

        if exit_reason:
            await self._exit(symbol, pos, current_price, exit_reason)

    async def _exit(
        self, symbol: str, pos: DipPosition, price: float, reason: str
    ) -> None:
        try:
            result = await self._exchange.place_market_order(
                symbol, "sell", pos.amount,
            )
            fill_price = result.avg_fill_price or result.price

            self._position.record_fill(
                symbol, "sell",
                result.filled_amount or pos.amount,
                fill_price, result.fee,
            )

            pnl = (fill_price - pos.entry_price) * pos.amount - result.fee
            hold_secs = time.time() - pos.entry_time

            logger.info(
                "dip_sniper_sell", symbol=symbol, reason=reason,
                entry=round(pos.entry_price, 8), exit=round(fill_price, 8),
                pnl=round(pnl, 4), hold_secs=round(hold_secs, 1),
            )

            del self._active[symbol]
            self._cooldown_until[symbol] = time.time() + self._config.cooldown_secs

        except Exception as e:
            logger.error("dip_sniper_sell_failed", symbol=symbol, error=str(e))

    def _is_in_cooldown(self, symbol: str) -> bool:
        until = self._cooldown_until.get(symbol, 0)
        if time.time() >= until:
            if symbol in self._cooldown_until:
                del self._cooldown_until[symbol]
            return False
        return True

    @property
    def active_positions(self) -> dict[str, DipPosition]:
        return dict(self._active)

    @property
    def position_tracker(self) -> MultiPairPositionTracker:
        return self._position
