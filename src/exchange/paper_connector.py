from __future__ import annotations

import time
import uuid

import structlog

from ..config.schema import PaperTradingConfig
from .models import Balance, OrderResult, Ticker

logger = structlog.get_logger()


class PaperConnector:
    """Drop-in replacement for CoinbaseConnector that simulates trades locally."""

    def __init__(self, config: PaperTradingConfig):
        self._fee_pct = config.simulated_fee_pct
        self._balances: dict[str, float] = {
            "USD": config.initial_balance_usd,
        }
        if config.initial_balance_base > 0:
            self._balances["BTC"] = config.initial_balance_base
        self._orders: dict[str, dict] = {}
        self._last_price: float = 0.0
        self._last_fills: list[OrderResult] = []

    async def connect(self) -> None:
        logger.info("paper_exchange_connected")

    async def close(self) -> None:
        pass

    async def get_ticker(self, symbol: str) -> Ticker:
        return Ticker(
            symbol=symbol,
            last=self._last_price,
            bid=self._last_price * 0.999,
            ask=self._last_price * 1.001,
            timestamp=int(time.time() * 1000),
        )

    async def get_balance(self) -> Balance:
        return Balance(
            free=dict(self._balances),
            used={},
            total=dict(self._balances),
        )

    async def place_limit_order(
        self, symbol: str, side: str, amount: float, price: float
    ) -> OrderResult:
        oid = str(uuid.uuid4())[:12]
        self._orders[oid] = {
            "id": oid,
            "symbol": symbol,
            "side": side,
            "price": price,
            "amount": amount,
            "filled": 0.0,
            "status": "open",
            "timestamp": int(time.time() * 1000),
        }
        logger.info(
            "paper_order_placed",
            order_id=oid,
            side=side,
            price=price,
            amount=amount,
        )
        return OrderResult(
            exchange_order_id=oid,
            symbol=symbol,
            side=side,
            order_type="limit",
            price=price,
            amount=amount,
            status="open",
            timestamp=int(time.time() * 1000),
        )

    async def cancel_order(self, order_id: str, symbol: str) -> bool:
        if order_id in self._orders:
            self._orders[order_id]["status"] = "cancelled"
            return True
        return False

    async def get_order(self, order_id: str, symbol: str) -> OrderResult:
        o = self._orders[order_id]
        return OrderResult(
            exchange_order_id=o["id"],
            symbol=o["symbol"],
            side=o["side"],
            order_type="limit",
            price=o["price"],
            amount=o["amount"],
            filled_amount=o["filled"],
            avg_fill_price=o["price"] if o["filled"] > 0 else None,
            fee=o["filled"] * o["price"] * self._fee_pct if o["filled"] > 0 else 0.0,
            status=o["status"],
            timestamp=o["timestamp"],
        )

    async def get_open_orders(self, symbol: str) -> list[OrderResult]:
        results = []
        for o in self._orders.values():
            if o["status"] == "open" and o["symbol"] == symbol:
                results.append(
                    OrderResult(
                        exchange_order_id=o["id"],
                        symbol=o["symbol"],
                        side=o["side"],
                        order_type="limit",
                        price=o["price"],
                        amount=o["amount"],
                        status="open",
                        timestamp=o["timestamp"],
                    )
                )
        return results

    async def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        since: int | None = None,
        limit: int | None = None,
    ) -> list[list]:
        return []

    def simulate_price(self, price: float) -> list[OrderResult]:
        """Simulate price movement. Call this to trigger fills on paper orders.
        Returns list of orders that were filled."""
        self._last_price = price
        self._last_fills = []
        filled = []
        base_currency = "BTC"

        for oid, o in list(self._orders.items()):
            if o["status"] != "open":
                continue
            should_fill = (o["side"] == "buy" and price <= o["price"]) or (
                o["side"] == "sell" and price >= o["price"]
            )
            if should_fill:
                fee = o["amount"] * o["price"] * self._fee_pct
                if o["side"] == "buy":
                    cost = o["amount"] * o["price"] + fee
                    if self._balances.get("USD", 0) >= cost:
                        self._balances["USD"] -= cost
                        self._balances[base_currency] = (
                            self._balances.get(base_currency, 0) + o["amount"]
                        )
                    else:
                        continue
                else:
                    if self._balances.get(base_currency, 0) >= o["amount"]:
                        self._balances[base_currency] -= o["amount"]
                        self._balances["USD"] += o["amount"] * o["price"] - fee
                    else:
                        continue

                o["status"] = "closed"
                o["filled"] = o["amount"]
                filled.append(
                    OrderResult(
                        exchange_order_id=oid,
                        symbol=o["symbol"],
                        side=o["side"],
                        order_type="limit",
                        price=o["price"],
                        amount=o["amount"],
                        filled_amount=o["amount"],
                        avg_fill_price=o["price"],
                        fee=fee,
                        status="closed",
                        timestamp=int(time.time() * 1000),
                    )
                )
                logger.info(
                    "paper_order_filled",
                    order_id=oid,
                    side=o["side"],
                    price=o["price"],
                )
        self._last_fills = filled
        return filled
