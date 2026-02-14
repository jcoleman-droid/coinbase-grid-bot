from __future__ import annotations

import time
from dataclasses import dataclass

import structlog

from ..position.tracker import MultiPairPositionTracker
from .trend_filter import TrendDirection, TrendFilter

logger = structlog.get_logger()


@dataclass
class PairScore:
    symbol: str
    realized_pnl: float
    unrealized_pnl: float
    trade_count: int
    trend: TrendDirection
    score: float


class PairRotator:
    """Periodically evaluates pairs and pauses persistent losers.

    Score = realized_pnl + unrealized_pnl + (trade_count * 0.01) + trend_bonus
    where trend_bonus = +0.5 for UP, 0 for NEUTRAL, -0.5 for DOWN.
    Pairs below pause_threshold are paused and their inventory sold.
    """

    def __init__(
        self,
        evaluation_interval_secs: float = 1800.0,
        pause_threshold: float = -1.0,
        min_trades_before_eval: int = 5,
    ):
        self._eval_interval = evaluation_interval_secs
        self._pause_threshold = pause_threshold
        self._min_trades = min_trades_before_eval
        self._last_eval_time: float = time.time()
        self._paused_pairs: dict[str, float] = {}
        self._scores: dict[str, PairScore] = {}

    def is_paused(self, symbol: str) -> bool:
        return symbol in self._paused_pairs

    def should_evaluate(self) -> bool:
        return time.time() - self._last_eval_time >= self._eval_interval

    def evaluate_pairs(
        self,
        position_tracker: MultiPairPositionTracker,
        trend_filter: TrendFilter | None = None,
    ) -> list[PairScore]:
        self._last_eval_time = time.time()
        scores = []

        for symbol, pair_state in position_tracker.all_pair_states.items():
            if pair_state.trade_count < self._min_trades:
                continue

            trend = (
                trend_filter.get_trend(symbol)
                if trend_filter
                else TrendDirection.NEUTRAL
            )
            trend_bonus = {
                TrendDirection.UP: 0.5,
                TrendDirection.NEUTRAL: 0.0,
                TrendDirection.DOWN: -0.5,
            }[trend]

            score_val = (
                pair_state.realized_pnl
                + pair_state.unrealized_pnl
                + (pair_state.trade_count * 0.01)
                + trend_bonus
            )

            pair_score = PairScore(
                symbol=symbol,
                realized_pnl=pair_state.realized_pnl,
                unrealized_pnl=pair_state.unrealized_pnl,
                trade_count=pair_state.trade_count,
                trend=trend,
                score=score_val,
            )
            scores.append(pair_score)
            self._scores[symbol] = pair_score

            logger.info(
                "pair_rotation_score",
                symbol=symbol,
                score=round(score_val, 4),
                realized_pnl=round(pair_state.realized_pnl, 4),
                unrealized_pnl=round(pair_state.unrealized_pnl, 4),
                trades=pair_state.trade_count,
                trend=trend.value,
            )

        return scores

    def get_pairs_to_pause(self, scores: list[PairScore]) -> list[str]:
        to_pause = []
        for ps in scores:
            if ps.score < self._pause_threshold and not self.is_paused(ps.symbol):
                to_pause.append(ps.symbol)
                self._paused_pairs[ps.symbol] = time.time()
                logger.warning(
                    "pair_rotation_paused",
                    symbol=ps.symbol,
                    score=round(ps.score, 4),
                    threshold=self._pause_threshold,
                )
        return to_pause

    async def sell_off_pair(
        self,
        symbol: str,
        exchange,
        position_tracker: MultiPairPositionTracker,
    ) -> bool:
        pair = position_tracker.pair_state(symbol)
        if pair.base_balance <= 0:
            return True

        try:
            result = await exchange.place_market_order(symbol, "sell", pair.base_balance)
            position_tracker.record_fill(
                symbol,
                "sell",
                result.filled_amount or pair.base_balance,
                result.avg_fill_price or result.price,
                result.fee,
            )
            logger.info(
                "pair_rotation_sold_off",
                symbol=symbol,
                amount=pair.base_balance,
                price=result.avg_fill_price or result.price,
            )
            return True
        except Exception as e:
            logger.error("pair_rotation_sell_failed", symbol=symbol, error=str(e))
            return False

    @property
    def paused_pairs(self) -> dict[str, float]:
        return dict(self._paused_pairs)

    @property
    def latest_scores(self) -> dict[str, PairScore]:
        return dict(self._scores)
