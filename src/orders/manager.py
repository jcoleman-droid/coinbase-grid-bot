from __future__ import annotations

import structlog

from ..db.repositories import GridLevelRepository, OrderRepository
from ..exchange.base import ExchangeInterface
from ..exchange.models import OrderResult

logger = structlog.get_logger()


class OrderManager:
    def __init__(
        self,
        exchange: ExchangeInterface,
        order_repo: OrderRepository,
        level_repo: GridLevelRepository,
    ):
        self._exchange = exchange
        self._order_repo = order_repo
        self._level_repo = level_repo
        self._open_order_ids: set[str] = set()

    async def place_grid_order(
        self,
        symbol: str,
        side: str,
        amount: float,
        price: float,
        grid_level_index: int,
    ) -> OrderResult:
        result = await self._exchange.place_limit_order(symbol, side, amount, price)
        await self._order_repo.insert(
            {
                "exchange_order_id": result.exchange_order_id,
                "grid_level_id": grid_level_index,
                "symbol": symbol,
                "side": side,
                "price": price,
                "amount": amount,
                "status": "open",
            }
        )
        await self._level_repo.update_status(
            grid_level_index, "order_placed", result.exchange_order_id
        )
        self._open_order_ids.add(result.exchange_order_id)
        logger.info(
            "order_placed",
            side=side,
            price=price,
            amount=round(amount, 8),
            order_id=result.exchange_order_id,
        )
        return result

    async def check_fills(self, symbol: str) -> list[OrderResult]:
        filled = []
        for oid in list(self._open_order_ids):
            order = await self._exchange.get_order(oid, symbol)
            if order.status in ("closed", "filled"):
                await self._order_repo.update_status(
                    oid, "filled", order.filled_amount, order.avg_fill_price, order.fee
                )
                self._open_order_ids.discard(oid)
                filled.append(order)
                logger.info(
                    "order_filled",
                    order_id=oid,
                    side=order.side,
                    price=order.avg_fill_price,
                )
            elif order.status == "partially_filled":
                await self._order_repo.update_status(
                    oid,
                    "partially_filled",
                    order.filled_amount,
                    order.avg_fill_price,
                    order.fee,
                )
        return filled

    async def cancel_order(self, order_id: str, symbol: str) -> bool:
        success = await self._exchange.cancel_order(order_id, symbol)
        if success:
            await self._order_repo.update_status(order_id, "cancelled")
            self._open_order_ids.discard(order_id)
        return success

    async def reconcile_with_exchange(self, symbol: str) -> None:
        exchange_orders = await self._exchange.get_open_orders(symbol)
        exchange_ids = {o.exchange_order_id for o in exchange_orders}
        stale = self._open_order_ids - exchange_ids
        for oid in stale:
            await self._order_repo.update_status(oid, "cancelled")
        self._open_order_ids = exchange_ids
        logger.info(
            "reconciled",
            exchange_open=len(exchange_ids),
            stale_cancelled=len(stale),
        )

    @property
    def open_order_count(self) -> int:
        return len(self._open_order_ids)
