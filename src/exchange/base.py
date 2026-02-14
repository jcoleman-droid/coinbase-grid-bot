from __future__ import annotations

from typing import Protocol, runtime_checkable

from .models import Balance, OrderResult, Ticker


@runtime_checkable
class ExchangeInterface(Protocol):
    async def connect(self) -> None: ...

    async def close(self) -> None: ...

    async def get_ticker(self, symbol: str) -> Ticker: ...

    async def get_balance(self) -> Balance: ...

    async def place_limit_order(
        self, symbol: str, side: str, amount: float, price: float
    ) -> OrderResult: ...

    async def cancel_order(self, order_id: str, symbol: str) -> bool: ...

    async def get_order(self, order_id: str, symbol: str) -> OrderResult: ...

    async def get_open_orders(self, symbol: str) -> list[OrderResult]: ...

    async def place_market_order(
        self, symbol: str, side: str, amount: float
    ) -> OrderResult: ...

    async def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        since: int | None = None,
        limit: int | None = None,
    ) -> list[list]: ...
