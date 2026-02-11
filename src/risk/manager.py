from __future__ import annotations

import structlog

from ..config.schema import RiskConfig
from ..orders.manager import OrderManager
from ..position.tracker import PositionTracker

logger = structlog.get_logger()


class RiskManager:
    def __init__(
        self,
        config: RiskConfig,
        position_tracker: PositionTracker,
        order_manager: OrderManager,
    ):
        self._config = config
        self._position = position_tracker
        self._orders = order_manager
        self._peak_equity: float = 0.0
        self._is_halted: bool = False

    def can_place_order(self, side: str, price: float) -> bool:
        if self._is_halted:
            logger.warning("risk_halted", reason="bot is halted by risk manager")
            return False

        if self._orders.open_order_count >= self._config.max_open_orders:
            logger.warning("risk_reject", reason="max_open_orders")
            return False

        state = self._position.state
        if side == "buy":
            current_position_value = state.base_balance * state.avg_entry_price
            if current_position_value >= self._config.max_position_usd:
                logger.warning("risk_reject", reason="max_position_usd")
                return False

        return True

    def check_stop_loss(self, current_price: float, lower_grid: float) -> bool:
        stop_price = lower_grid * (1 - self._config.stop_loss_pct / 100)
        if current_price <= stop_price:
            logger.critical(
                "stop_loss_triggered",
                current_price=current_price,
                stop_price=round(stop_price, 2),
            )
            self._is_halted = True
            return True
        return False

    def check_take_profit(self, current_price: float, upper_grid: float) -> bool:
        tp_price = upper_grid * (1 + self._config.take_profit_pct / 100)
        if current_price >= tp_price:
            logger.info(
                "take_profit_triggered",
                current_price=current_price,
                tp_price=round(tp_price, 2),
            )
            self._is_halted = True
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

    def reset_halt(self) -> None:
        self._is_halted = False
        logger.info("risk_halt_reset")

    @property
    def is_halted(self) -> bool:
        return self._is_halted
