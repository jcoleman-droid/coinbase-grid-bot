from __future__ import annotations

import time
from dataclasses import dataclass, field

import structlog

from ..config.schema import FuturesGridConfig, FuturesRiskConfig
from ..exchange.kraken_futures_connector import KrakenFuturesConnector
from ..orders.manager import OrderManager
from .grid_engine import smart_price_round, smart_round

logger = structlog.get_logger()

# Minimum seconds between direction switches to prevent thrashing
_DIRECTION_COOLDOWN = 1800.0


@dataclass
class FuturesGridLevel:
    index: int
    price: float
    side: str                           # "buy" (open long / close short) or "sell" (open short / close long)
    reduce_only: bool = False           # True = closing leg
    status: str = "pending"             # "pending", "order_placed", "filled", "cancelled"
    exchange_order_id: str | None = None


class FuturesGridEngine:
    """
    Direction-aware grid engine for perpetual futures.

    Long grid (uptrend):
      - BUY orders below price → open long (reduce_only=False)
      - SELL orders above price → close long (reduce_only=True)
      - On BUY fill: place SELL (reduce_only) at next level up
      - On SELL fill: place BUY at next level down

    Short grid (downtrend):
      - SELL orders above price → open short (reduce_only=False)
      - BUY orders below price → close short (reduce_only=True)
      - On SELL fill: place BUY (reduce_only) at next level down
      - On BUY fill: place SELL at next level up
    """

    def __init__(
        self,
        config: FuturesGridConfig,
        risk_config: FuturesRiskConfig,
        exchange: KrakenFuturesConnector,
        order_manager: OrderManager,
    ):
        self._config = config
        self._risk_config = risk_config
        self._exchange = exchange
        self._order_mgr = order_manager
        self._levels: list[FuturesGridLevel] = []
        self._direction: str = "long"
        self._last_direction_switch: float = 0.0
        self._open_position_size: float = 0.0

    async def initialize_grid(self, direction: str) -> None:
        """Deploy a fresh directional grid. direction must be 'long' or 'short'."""
        self._direction = direction
        self._levels = []

        ticker = await self._exchange.get_ticker(self._config.symbol)
        current_price = ticker.last

        # Build equally-spaced levels
        half_range = current_price * (self._config.range_pct / 100.0) / 2
        lower = smart_price_round(current_price - half_range)
        upper = smart_price_round(current_price + half_range)
        if lower <= 0:
            lower = current_price * 0.01

        step = (upper - lower) / max(self._config.num_levels - 1, 1)
        prices = [smart_price_round(lower + i * step) for i in range(self._config.num_levels)]

        if direction == "long":
            # Buys below price (open long), sells above (close long)
            for i, p in enumerate(prices):
                side = "buy" if p <= current_price else "sell"
                reduce_only = side == "sell"
                self._levels.append(
                    FuturesGridLevel(index=i, price=p, side=side, reduce_only=reduce_only)
                )
        else:  # short
            # Sells above price (open short), buys below (close short)
            for i, p in enumerate(prices):
                side = "sell" if p >= current_price else "buy"
                reduce_only = side == "buy"
                self._levels.append(
                    FuturesGridLevel(index=i, price=p, side=side, reduce_only=reduce_only)
                )

        placed = 0
        for level in self._levels:
            amount = self._config.order_size_usd / level.price
            amount = smart_round(amount, level.price)
            if amount <= 0:
                continue
            try:
                order = await self._order_mgr.place_grid_order(
                    symbol=self._config.symbol,
                    side=level.side,
                    amount=amount,
                    price=level.price,
                    grid_level_index=level.index,
                )
                level.exchange_order_id = order.exchange_order_id
                level.status = "order_placed"
                placed += 1
            except Exception as e:
                logger.warning(
                    "futures_order_failed",
                    symbol=self._config.symbol,
                    side=level.side,
                    price=level.price,
                    error=str(e),
                )

        logger.info(
            "futures_grid_initialized",
            symbol=self._config.symbol,
            direction=direction,
            levels=len(self._levels),
            orders_placed=placed,
            price=round(current_price, 4),
        )

    async def on_fill(self, filled_level: FuturesGridLevel) -> None:
        filled_level.status = "filled"

        if self._direction == "long":
            if filled_level.side == "buy":
                # Opened long → place closing sell above
                self._open_position_size += self._config.order_size_usd / filled_level.price
                target_index = filled_level.index + 1
                opposite_side = "sell"
                opposite_reduce_only = True
            else:
                # Closed long → place opening buy below
                self._open_position_size -= self._config.order_size_usd / filled_level.price
                target_index = filled_level.index - 1
                opposite_side = "buy"
                opposite_reduce_only = False
        else:  # short
            if filled_level.side == "sell":
                # Opened short → place closing buy below
                self._open_position_size += self._config.order_size_usd / filled_level.price
                target_index = filled_level.index - 1
                opposite_side = "buy"
                opposite_reduce_only = True
            else:
                # Closed short → place opening sell above
                self._open_position_size -= self._config.order_size_usd / filled_level.price
                target_index = filled_level.index + 1
                opposite_side = "sell"
                opposite_reduce_only = False

        if 0 <= target_index < len(self._levels):
            target = self._levels[target_index]
            amount = self._config.order_size_usd / target.price
            amount = smart_round(amount, target.price)
            if amount <= 0:
                return
            try:
                order = await self._order_mgr.place_grid_order(
                    symbol=self._config.symbol,
                    side=opposite_side,
                    amount=amount,
                    price=target.price,
                    grid_level_index=target_index,
                )
                target.side = opposite_side
                target.reduce_only = opposite_reduce_only
                target.exchange_order_id = order.exchange_order_id
                target.status = "order_placed"
            except Exception as e:
                logger.warning(
                    "futures_mirror_order_failed",
                    symbol=self._config.symbol,
                    error=str(e),
                )

    async def check_and_process_fills(self) -> int:
        fills = await self._order_mgr.check_fills(self._config.symbol)
        for filled_order in fills:
            level = self._find_level(filled_order.exchange_order_id)
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
        logger.info("futures_grid_cancelled", symbol=self._config.symbol, count=count)
        return count

    async def switch_direction(self, new_direction: str) -> None:
        """Cancel all orders, flatten position, redeploy in new direction."""
        if new_direction == self._direction:
            return
        if not self.can_switch:
            logger.debug(
                "direction_switch_in_cooldown",
                symbol=self._config.symbol,
                remaining=round(_DIRECTION_COOLDOWN - (time.time() - self._last_direction_switch), 0),
            )
            return

        logger.info(
            "direction_switching",
            symbol=self._config.symbol,
            old=self._direction,
            new=new_direction,
        )
        await self.cancel_all_grid_orders()
        await self._exchange.close_position(self._config.symbol)
        self._open_position_size = 0.0
        self._last_direction_switch = time.time()

        # Brief pause to let exchange process the close
        import asyncio
        await asyncio.sleep(2.0)

        await self.initialize_grid(new_direction)

    def _find_level(self, order_id: str) -> FuturesGridLevel | None:
        for level in self._levels:
            if level.exchange_order_id == order_id:
                return level
        return None

    @property
    def direction(self) -> str:
        return self._direction

    @property
    def can_switch(self) -> bool:
        return time.time() - self._last_direction_switch >= _DIRECTION_COOLDOWN

    @property
    def levels(self) -> list[FuturesGridLevel]:
        return list(self._levels)

    @property
    def open_position_size(self) -> float:
        return max(self._open_position_size, 0.0)
