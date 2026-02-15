from __future__ import annotations

import structlog

from ..config.schema import FearGreedConfig, RiskConfig
from ..intelligence.fear_greed import FearGreedProvider
from ..orders.manager import OrderManager
from ..position.tracker import MultiPairPositionTracker
from ..strategy.trend_filter import TrendFilter

logger = structlog.get_logger()


class RiskManager:
    def __init__(
        self,
        config: RiskConfig,
        position_tracker: MultiPairPositionTracker,
        order_manager: OrderManager,
        trend_filter: TrendFilter | None = None,
        fear_greed: FearGreedProvider | None = None,
        fear_greed_config: FearGreedConfig | None = None,
    ):
        self._config = config
        self._position = position_tracker
        self._orders = order_manager
        self._trend_filter = trend_filter
        self._fear_greed = fear_greed
        self._fg_config = fear_greed_config
        self._peak_equity: float = 0.0
        self._is_halted: bool = False
        self._halted_pairs: set[str] = set()

    def can_place_order(
        self, symbol: str, side: str, price: float, amount: float = 0.0
    ) -> bool:
        if self._is_halted:
            logger.warning("risk_halted", reason="global halt active")
            return False

        if symbol in self._halted_pairs:
            return False

        if self._orders.open_order_count >= self._config.max_open_orders:
            logger.warning("risk_reject", reason="max_open_orders")
            return False

        if (
            side == "buy"
            and self._trend_filter is not None
            and not self._trend_filter.should_allow_buy(symbol)
        ):
            return False

        # Block grid buys during extreme fear
        if (
            side == "buy"
            and self._fear_greed is not None
            and self._fg_config is not None
        ):
            fg_val = self._fear_greed.get_index()
            if fg_val is not None and fg_val <= self._fg_config.extreme_fear_threshold:
                logger.info(
                    "risk_blocked_extreme_fear",
                    symbol=symbol, fear_greed=fg_val,
                )
                return False

        if side == "buy":
            cost = amount * price if amount > 0 else 0
            if cost > 0 and not self._position.can_afford_buy(cost):
                logger.warning(
                    "risk_reject", reason="insufficient_pool", symbol=symbol
                )
                return False

            pair_state = self._position.pair_state(symbol)
            current_pair_value = pair_state.base_balance * pair_state.avg_entry_price
            if current_pair_value >= self._config.max_position_usd_per_pair:
                logger.warning(
                    "risk_reject", reason="max_position_per_pair", symbol=symbol
                )
                return False

            total_position = self._position.total_base_value_usd
            if total_position >= self._config.max_position_usd:
                logger.warning("risk_reject", reason="max_position_global")
                return False

        return True

    def check_stop_loss(
        self, symbol: str, current_price: float, lower_grid: float
    ) -> bool:
        stop_price = lower_grid * (1 - self._config.stop_loss_pct / 100)
        if current_price <= stop_price:
            logger.critical(
                "stop_loss_triggered",
                symbol=symbol,
                current_price=current_price,
                stop_price=round(stop_price, 2),
            )
            self._halted_pairs.add(symbol)
            return True
        return False

    def check_take_profit(
        self, symbol: str, current_price: float, upper_grid: float
    ) -> bool:
        tp_price = upper_grid * (1 + self._config.take_profit_pct / 100)
        if current_price >= tp_price:
            logger.info(
                "take_profit_triggered",
                symbol=symbol,
                current_price=current_price,
                tp_price=round(tp_price, 2),
            )
            self._halted_pairs.add(symbol)
            return True
        return False

    def check_drawdown(self, current_equity: float) -> bool:
        self._peak_equity = max(self._peak_equity, current_equity)
        if self._peak_equity > 0:
            drawdown_pct = (
                (self._peak_equity - current_equity) / self._peak_equity * 100
            )
            if drawdown_pct >= self._config.max_drawdown_pct:
                logger.critical("drawdown_halt", drawdown_pct=round(drawdown_pct, 2))
                self._is_halted = True
                return True
        return False

    def is_pair_halted(self, symbol: str) -> bool:
        return symbol in self._halted_pairs

    def reset_halt(self) -> None:
        self._is_halted = False
        self._halted_pairs.clear()
        logger.info("risk_halt_reset")

    @property
    def is_halted(self) -> bool:
        return self._is_halted
