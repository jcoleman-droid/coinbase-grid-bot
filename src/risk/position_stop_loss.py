from __future__ import annotations

import time

import structlog

from ..position.tracker import MultiPairPositionTracker

logger = structlog.get_logger()


class PositionStopLoss:
    """Per-pair position stop-loss based on unrealized P&L percentage.

    If unrealized_pnl / position_value drops below -threshold_pct,
    the entire position for that pair is sold at market.
    After triggering, the pair enters a cooldown period.
    """

    def __init__(
        self,
        threshold_pct: float = 2.0,
        cooldown_secs: float = 300.0,
    ):
        self._threshold_pct = threshold_pct
        self._cooldown_secs = cooldown_secs
        self._triggered_at: dict[str, float] = {}

    def is_in_cooldown(self, symbol: str) -> bool:
        triggered = self._triggered_at.get(symbol)
        if triggered is None:
            return False
        if time.time() - triggered >= self._cooldown_secs:
            del self._triggered_at[symbol]
            logger.info("position_stop_loss_cooldown_expired", symbol=symbol)
            return False
        return True

    def cooldown_remaining(self, symbol: str) -> float:
        triggered = self._triggered_at.get(symbol)
        if triggered is None:
            return 0.0
        return max(0.0, self._cooldown_secs - (time.time() - triggered))

    def should_trigger(
        self,
        symbol: str,
        position_tracker: MultiPairPositionTracker,
        current_price: float,
    ) -> bool:
        if self.is_in_cooldown(symbol):
            return False

        pair = position_tracker.pair_state(symbol)
        if pair.base_balance <= 0:
            return False

        position_value = pair.base_balance * pair.avg_entry_price
        if position_value <= 0:
            return False

        unrealized_pnl = (current_price - pair.avg_entry_price) * pair.base_balance
        loss_pct = abs(unrealized_pnl / position_value) * 100

        if unrealized_pnl < 0 and loss_pct >= self._threshold_pct:
            logger.warning(
                "position_stop_loss_triggered",
                symbol=symbol,
                unrealized_pnl=round(unrealized_pnl, 4),
                loss_pct=round(loss_pct, 2),
                position_value=round(position_value, 4),
            )
            return True
        return False

    async def execute_stop_loss(
        self,
        symbol: str,
        exchange,
        position_tracker: MultiPairPositionTracker,
    ) -> bool:
        pair = position_tracker.pair_state(symbol)
        if pair.base_balance <= 0:
            return False

        amount = pair.base_balance
        try:
            result = await exchange.place_market_order(symbol, "sell", amount)
            position_tracker.record_fill(
                symbol,
                "sell",
                result.filled_amount or amount,
                result.avg_fill_price or result.price,
                result.fee,
            )
            self._triggered_at[symbol] = time.time()
            logger.critical(
                "position_stop_loss_executed",
                symbol=symbol,
                amount=amount,
                fill_price=result.avg_fill_price or result.price,
                fee=result.fee,
            )
            return True
        except Exception as e:
            logger.error("position_stop_loss_failed", symbol=symbol, error=str(e))
            return False

    @property
    def all_cooldowns(self) -> dict[str, float]:
        return {
            sym: self.cooldown_remaining(sym)
            for sym in list(self._triggered_at)
            if self.is_in_cooldown(sym)
        }
