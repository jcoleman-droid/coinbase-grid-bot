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
        self._last_prices: dict[str, float] = {}
        self._last_fills: list[OrderResult] = []

    async def connect(self) -> None:
        logger.info("paper_exchange_connected")

    async def close(self) -> None:
        pass

    async def get_ticker(self, symbol: str) -> Ticker:
        price = self._last_prices.get(symbol, 0.0)
        return Ticker(
            symbol=symbol,
            last=price,
            bid=price * 0.999,
            ask=price * 1.001,
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

    async def place_market_order(
        self, symbol: str, side: str, amount: float
    ) -> OrderResult:
        """Simulate a market order that fills immediately at current price."""
        price = self._last_prices.get(symbol, 0.0)
        if price <= 0:
            raise ValueError(f"No price available for {symbol}")
        oid = str(uuid.uuid4())[:12]
        base_currency = symbol.split("/")[0]
        fee = amount * price * self._fee_pct

        if side == "sell":
            if self._balances.get(base_currency, 0) < amount:
                raise ValueError(f"Insufficient {base_currency} balance")
            self._balances[base_currency] -= amount
            self._balances["USD"] += amount * price - fee
        else:
            cost = amount * price + fee
            if self._balances.get("USD", 0) < cost:
                raise ValueError("Insufficient USD balance")
            self._balances["USD"] -= cost
            self._balances[base_currency] = self._balances.get(base_currency, 0) + amount

        result = OrderResult(
            exchange_order_id=oid,
            symbol=symbol,
            side=side,
            order_type="market",
            price=price,
            amount=amount,
            filled_amount=amount,
            avg_fill_price=price,
            fee=fee,
            status="closed",
            timestamp=int(time.time() * 1000),
        )
        logger.info(
            "paper_market_order_filled",
            order_id=oid,
            side=side,
            price=price,
            amount=amount,
            symbol=symbol,
        )
        return result

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

    def simulate_price(self, price: float, symbol: str = "SOL/USD") -> list[OrderResult]:
        """Simulate price movement for a single symbol. Backward-compatible wrapper."""
        return self.simulate_prices({symbol: price})

    def simulate_prices(self, prices: dict[str, float]) -> list[OrderResult]:
        """Simulate price movement for multiple symbols at once.
        Returns list of orders that were filled across all symbols."""
        self._last_prices.update(prices)
        self._last_fills = []
        filled = []

        for oid, o in list(self._orders.items()):
            if o["status"] != "open":
                continue

            sym = o["symbol"]
            if sym not in prices:
                continue

            price = prices[sym]
            base_currency = sym.split("/")[0]

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
                    symbol=sym,
                )
        self._last_fills = filled
        return filled
