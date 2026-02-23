from __future__ import annotations

import math
import time
from typing import TYPE_CHECKING

import structlog

from ..config.schema import DynamicPairSelectorConfig, GridConfig

if TYPE_CHECKING:
    from ..bot.orchestrator import BotOrchestrator

logger = structlog.get_logger()


class DynamicPairSelector:
    """Monitors a candidate pool of coins and swaps the worst active pair
    for the best-scoring candidate every evaluation_interval_secs.

    Scoring per coin:
      trend:        UP=+2, NEUTRAL=0, DOWN=-2 (active: SMA filter; candidate: 24h change proxy)
      24h change:   pct_24h * 0.1, capped ±2.0
      volume:       log10(volume_24h) * 0.1
      sentiment:    (galaxy_score - 50) * 0.02
      volume spike: +0.5
    Swap fires only when best_candidate_score > worst_active_score + swap_score_threshold.
    """

    def __init__(self, config: DynamicPairSelectorConfig) -> None:
        self._config = config
        self._last_eval_time: float = 0.0
        self._last_swap: dict | None = None  # {removed, added, timestamp}
        self._scores: dict[str, float] = {}  # latest scores for all candidates

    def should_evaluate(self) -> bool:
        return time.time() - self._last_eval_time >= self._config.evaluation_interval_secs

    def score_coin(
        self,
        symbol: str,
        lunarcrush,
        trend_filter,
        volume_tracker,
        is_active: bool = False,
    ) -> float:
        score = 0.0

        lc = lunarcrush.get_score(symbol) if lunarcrush else None

        # --- Trend component ---
        if is_active and trend_filter:
            from ..strategy.trend_filter import TrendDirection
            trend = trend_filter.get_trend(symbol)
            score += {
                TrendDirection.UP: 2.0,
                TrendDirection.NEUTRAL: 0.0,
                TrendDirection.DOWN: -2.0,
            }[trend]
        elif lc:
            # Proxy: 24h price change as trend signal
            pct = lc.get("price_change_24h", 0)
            if pct > 2:
                score += 2.0
            elif pct > 0:
                score += 0.0
            else:
                score += -2.0

        # --- 24h price change ---
        if lc:
            pct_24h = lc.get("price_change_24h", 0)
            score += max(-2.0, min(2.0, pct_24h * 0.1))

        # --- Volume ---
        if lc:
            vol = lc.get("total_volume", 0)
            if vol > 0:
                score += math.log10(vol) * 0.1

        # --- Sentiment ---
        if lc:
            galaxy = lc.get("galaxy_score", 50)
            score += (galaxy - 50) * 0.02

        # --- Volume spike bonus ---
        if volume_tracker:
            info = volume_tracker.get_info(symbol)
            if info and info.get("spike"):
                score += 0.5

        return round(score, 3)

    async def evaluate_and_swap(self, bot: BotOrchestrator) -> str | None:
        """Score all candidates, swap worst active for best candidate if warranted.
        Returns the symbol of the newly added pair, or None if no swap occurred."""
        self._last_eval_time = time.time()

        active_symbols = set(bot.symbols)
        candidate_pool = self._config.candidate_pool

        lc = bot._lunarcrush
        tf = bot._trend_filter
        vt = bot._volume_tracker

        # Score every candidate (active and inactive)
        all_scores: dict[str, float] = {}
        for sym in candidate_pool:
            is_active = sym in active_symbols
            all_scores[sym] = self.score_coin(sym, lc, tf, vt, is_active=is_active)

        self._scores = all_scores

        # Find best non-active candidate
        candidates = {s: v for s, v in all_scores.items() if s not in active_symbols}
        if not candidates:
            return None
        best_candidate = max(candidates, key=candidates.get)
        best_score = candidates[best_candidate]

        # Find worst active pair
        active_scores = {s: all_scores[s] for s in active_symbols if s in all_scores}
        if not active_scores:
            return None
        worst_active = min(active_scores, key=active_scores.get)
        worst_score = active_scores[worst_active]

        logger.info(
            "dynamic_pair_eval",
            best_candidate=best_candidate,
            best_score=best_score,
            worst_active=worst_active,
            worst_score=worst_score,
            threshold=self._config.swap_score_threshold,
        )

        if best_score <= worst_score + self._config.swap_score_threshold:
            return None  # Not enough improvement to warrant a swap

        # Get current price for the new coin
        lc_data = lc.get_score(best_candidate) if lc else None
        current_price = lc_data.get("current_price", 0) if lc_data else 0
        if current_price <= 0:
            logger.warning("dynamic_pair_no_price", symbol=best_candidate)
            return None

        # Auto-calculate grid range centered around current price
        half = self._config.range_pct / 100.0 / 2.0
        lower = round(current_price * (1 - half), 10)
        upper = round(current_price * (1 + half), 10)

        # Inherit grid settings from the pair being replaced
        old_grid = next((g for g in bot._config.grids if g.symbol == worst_active), None)
        if not old_grid:
            return None

        new_grid = GridConfig(
            symbol=best_candidate,
            lower_price=lower,
            upper_price=upper,
            num_levels=old_grid.num_levels,
            spacing=old_grid.spacing,
            order_size_usd=old_grid.order_size_usd,
            order_size_base=old_grid.order_size_base,
            trailing_enabled=old_grid.trailing_enabled,
            trailing_trigger_pct=old_grid.trailing_trigger_pct,
            trailing_rebalance_pct=old_grid.trailing_rebalance_pct,
            trailing_cooldown_secs=old_grid.trailing_cooldown_secs,
        )

        logger.info(
            "dynamic_pair_swap",
            removing=worst_active,
            adding=best_candidate,
            price=current_price,
            lower=lower,
            upper=upper,
        )

        await bot.swap_pair(worst_active, new_grid)

        self._last_swap = {
            "removed": worst_active,
            "added": best_candidate,
            "timestamp": time.time(),
            "worst_score": worst_score,
            "best_score": best_score,
        }
        return best_candidate

    def get_scores(self) -> dict[str, float]:
        return dict(self._scores)

    @property
    def last_swap(self) -> dict | None:
        return self._last_swap
