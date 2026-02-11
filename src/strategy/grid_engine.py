from __future__ import annotations

import time
from dataclasses import dataclass

import structlog

from ..config.schema import GridConfig, RiskConfig
from ..exchange.base import ExchangeInterface
from ..orders.manager import OrderManager
from ..risk.manager import RiskManager
from .grid_math import calculate_order_amount, compute_grid_levels, determine_order_sides

logger = structlog.get_logger()


@dataclass
class GridLevel:
    index: int
    price: float
    side: str
    status: str = "pending"
    exchange_order_id: str | None = None


class GridEngine:
    def __init__(
        self,
        config: GridConfig,
        risk_config: RiskConfig,
        exchange: ExchangeInterface,
        order_manager: OrderManager,
        risk_manager: RiskManager,
    ):
        self._config = config
        self._risk_config = risk_config
        self._exchange = exchange
        self._order_mgr = order_manager
        self._risk_mgr = risk_manager
        self._levels: list[GridLevel] = []
        self._trailing_shift_count: int = 0
        self._last_trailing_shift_time: float = 0.0

    async def initialize_grid(self) -> None:
        prices = compute_grid_levels(
            self._config.lower_price,
            self._config.upper_price,
            self._config.num_levels,
            self._config.spacing.value,
        )
        ticker = await self._exchange.get_ticker(self._config.symbol)
        current_price = ticker.last

        sides = determine_order_sides(prices, current_price)
        self._levels = [
            GridLevel(index=i, price=round(p, 2), side=s)
            for i, (p, s) in enumerate(sides)
        ]

        placed = 0
        for level in self._levels:
            if not self._risk_mgr.can_place_order(level.side, level.price):
                continue
            amount = calculate_order_amount(
                self._config.order_size_usd,
                self._config.order_size_base,
                level.price,
            )
            order = await self._order_mgr.place_grid_order(
                symbol=self._config.symbol,
                side=level.side,
                amount=round(amount, 8),
                price=level.price,
                grid_level_index=level.index,
            )
            level.exchange_order_id = order.exchange_order_id
            level.status = "order_placed"
            placed += 1

        logger.info(
            "grid_initialized",
            levels=len(self._levels),
            orders_placed=placed,
            price=current_price,
        )

    async def on_fill(self, filled_level: GridLevel) -> None:
        filled_level.status = "filled"
        opposite_side = "sell" if filled_level.side == "buy" else "buy"

        target_index = (
            filled_level.index + 1
            if opposite_side == "sell"
            else filled_level.index - 1
        )

        if 0 <= target_index < len(self._levels):
            target_level = self._levels[target_index]
            if not self._risk_mgr.can_place_order(opposite_side, target_level.price):
                return
            amount = calculate_order_amount(
                self._config.order_size_usd,
                self._config.order_size_base,
                target_level.price,
            )
            order = await self._order_mgr.place_grid_order(
                symbol=self._config.symbol,
                side=opposite_side,
                amount=round(amount, 8),
                price=target_level.price,
                grid_level_index=target_index,
            )
            target_level.side = opposite_side
            target_level.exchange_order_id = order.exchange_order_id
            target_level.status = "order_placed"

    async def check_and_process_fills(self) -> int:
        fills = await self._order_mgr.check_fills(self._config.symbol)
        for filled_order in fills:
            level = self._find_level_by_order_id(filled_order.exchange_order_id)
            if level:
                await self.on_fill(level)
        return len(fills)

    async def cancel_all_grid_orders(self) -> int:
        count = 0
        for level in self._levels:
            if level.status == "order_placed" and level.exchange_order_id:
                await self._order_mgr.cancel_order(
                    level.exchange_order_id, self._config.symbol
                )
                level.status = "cancelled"
                count += 1
        logger.info("grid_orders_cancelled", count=count)
        return count

    def _find_level_by_order_id(self, order_id: str) -> GridLevel | None:
        for level in self._levels:
            if level.exchange_order_id == order_id:
                return level
        return None

    async def check_trailing(self, current_price: float) -> bool:
        """Check if the grid should shift to follow the price trend.
        Returns True if the grid was rebalanced."""
        if not self._config.trailing_enabled:
            return False

        # Cooldown: minimum 60 seconds between shifts to avoid churning
        cooldown_secs = self._config.trailing_cooldown_secs
        if time.time() - self._last_trailing_shift_time < cooldown_secs:
            return False

        lower = self._config.lower_price
        upper = self._config.upper_price
        grid_range = upper - lower
        trigger_pct = self._config.trailing_trigger_pct / 100.0
        rebalance_pct = self._config.trailing_rebalance_pct / 100.0

        # How far the price is into the grid range (0.0 = at lower, 1.0 = at upper)
        position_in_range = (current_price - lower) / grid_range

        should_shift = False
        shift_amount = 0.0

        if position_in_range >= trigger_pct:
            # Price near upper bound — shift grid UP
            shift_amount = grid_range * rebalance_pct
            should_shift = True
        elif position_in_range <= (1.0 - trigger_pct):
            # Price near lower bound — shift grid DOWN
            shift_amount = -(grid_range * rebalance_pct)
            should_shift = True

        if not should_shift:
            return False

        new_lower = round(lower + shift_amount, 2)
        new_upper = round(upper + shift_amount, 2)

        if new_lower <= 0:
            return False

        logger.info(
            "trailing_grid_shift",
            direction="up" if shift_amount > 0 else "down",
            old_range=f"{lower:.2f}-{upper:.2f}",
            new_range=f"{new_lower:.2f}-{new_upper:.2f}",
            trigger_price=round(current_price, 2),
        )

        # Cancel all existing orders
        await self.cancel_all_grid_orders()

        # Update config bounds
        self._config.lower_price = new_lower
        self._config.upper_price = new_upper

        # Re-initialize the grid at new range
        await self.initialize_grid()
        self._trailing_shift_count += 1
        self._last_trailing_shift_time = time.time()
        return True

    @property
    def trailing_shift_count(self) -> int:
        return self._trailing_shift_count

    @property
    def levels(self) -> list[GridLevel]:
        return list(self._levels)
