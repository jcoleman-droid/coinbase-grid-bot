from __future__ import annotations

import structlog

from ..config.schema import MomentumRiderConfig
from ..exchange.base import ExchangeInterface
from ..position.tracker import MultiPairPositionTracker
from .trend_filter import TrendDirection, TrendFilter

logger = structlog.get_logger()


class MomentumRider:
    """Trend-following strategy: buy on confirmed UP trend, sell on DOWN flip."""

    def __init__(
        self,
        config: MomentumRiderConfig,
        exchange: ExchangeInterface,
        position_tracker: MultiPairPositionTracker,
        trend_filter: TrendFilter,
    ):
        self._config = config
        self._exchange = exchange
        self._position = position_tracker
        self._trend_filter = trend_filter
        self._up_confirms: dict[str, int] = {}

    async def evaluate(self, symbol: str, current_price: float) -> None:
        if current_price <= 0:
            return

        trend = self._trend_filter.get_trend(symbol)
        pair_state = self._position.pair_state(symbol)
        has_position = pair_state.base_balance > 0

        # Track consecutive UP confirms
        if trend == TrendDirection.UP:
            self._up_confirms[symbol] = self._up_confirms.get(symbol, 0) + 1
        else:
            self._up_confirms[symbol] = 0

        # EXIT: sell if trend flips to DOWN and we hold
        if has_position and trend == TrendDirection.DOWN:
            await self._sell(symbol, pair_state.base_balance, current_price)

        # ENTER: buy if UP trend confirmed N times and no position
        elif (
            not has_position
            and trend == TrendDirection.UP
            and self._up_confirms.get(symbol, 0) >= self._config.min_trend_confirms
            and self._position.can_afford_buy(self._config.position_size_usd)
        ):
            amount = self._config.position_size_usd / current_price
            await self._buy(symbol, amount, current_price)

    async def _buy(self, symbol: str, amount: float, price: float) -> None:
        try:
            result = await self._exchange.place_market_order(symbol, "buy", amount)
            self._position.record_fill(
                symbol, "buy",
                result.filled_amount or amount,
                result.avg_fill_price or result.price,
                result.fee,
            )
            logger.info(
                "momentum_buy", symbol=symbol,
                amount=round(amount, 6), price=round(price, 8),
            )
        except Exception as e:
            logger.error("momentum_buy_failed", symbol=symbol, error=str(e))

    async def _sell(self, symbol: str, amount: float, price: float) -> None:
        try:
            pair = self._position.pair_state(symbol)
            entry = pair.avg_entry_price
            result = await self._exchange.place_market_order(symbol, "sell", amount)
            self._position.record_fill(
                symbol, "sell",
                result.filled_amount or amount,
                result.avg_fill_price or result.price,
                result.fee,
            )
            pnl = (price - entry) * amount
            logger.info(
                "momentum_sell", symbol=symbol,
                amount=round(amount, 6), price=round(price, 8),
                est_pnl=round(pnl, 4),
            )
        except Exception as e:
            logger.error("momentum_sell_failed", symbol=symbol, error=str(e))

    @property
    def active_positions(self) -> dict[str, float]:
        return {
            sym: ps.base_balance
            for sym, ps in self._position.all_pair_states.items()
            if ps.base_balance > 0
        }

    @property
    def position_tracker(self) -> MultiPairPositionTracker:
        return self._position
