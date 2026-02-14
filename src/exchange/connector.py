from __future__ import annotations

import ccxt.async_support as ccxt
import structlog

from ..utils.decorators import retry_with_backoff
from .models import Balance, OrderResult, Ticker
from .rate_limiter import TokenBucketRateLimiter

logger = structlog.get_logger()


class CoinbaseConnector:
    def __init__(self, api_key: str, api_secret: str, sandbox: bool = False):
        self._exchange = ccxt.coinbase(
            {
                "apiKey": api_key,
                "secret": api_secret,
                "enableRateLimit": True,
                "sandbox": sandbox,
                "options": {"defaultType": "spot"},
            }
        )
        self._rate_limiter = TokenBucketRateLimiter(rate=25, capacity=30)

    async def connect(self) -> None:
        await self._exchange.load_markets()
        logger.info("exchange_connected", exchange="coinbase")

    async def close(self) -> None:
        await self._exchange.close()

    @retry_with_backoff(
        max_retries=3,
        base_delay=1.0,
        retryable_exceptions=(ccxt.NetworkError, ccxt.ExchangeNotAvailable),
    )
    async def get_ticker(self, symbol: str) -> Ticker:
        await self._rate_limiter.acquire()
        raw = await self._exchange.fetch_ticker(symbol)
        return Ticker.from_ccxt(raw)

    @retry_with_backoff(max_retries=3, base_delay=1.0)
    async def get_balance(self) -> Balance:
        await self._rate_limiter.acquire()
        raw = await self._exchange.fetch_balance()
        return Balance.from_ccxt(raw)

    @retry_with_backoff(
        max_retries=3,
        base_delay=1.0,
        retryable_exceptions=(ccxt.NetworkError, ccxt.ExchangeNotAvailable),
    )
    async def place_limit_order(
        self, symbol: str, side: str, amount: float, price: float
    ) -> OrderResult:
        await self._rate_limiter.acquire()
        raw = await self._exchange.create_order(
            symbol=symbol,
            type="limit",
            side=side,
            amount=amount,
            price=price,
        )
        return OrderResult.from_ccxt(raw)

    @retry_with_backoff(
        max_retries=3,
        base_delay=1.0,
        retryable_exceptions=(ccxt.NetworkError, ccxt.ExchangeNotAvailable),
    )
    async def place_market_order(
        self, symbol: str, side: str, amount: float
    ) -> OrderResult:
        await self._rate_limiter.acquire()
        raw = await self._exchange.create_order(
            symbol=symbol,
            type="market",
            side=side,
            amount=amount,
        )
        return OrderResult.from_ccxt(raw)

    @retry_with_backoff(max_retries=3, base_delay=0.5)
    async def cancel_order(self, order_id: str, symbol: str) -> bool:
        await self._rate_limiter.acquire()
        try:
            await self._exchange.cancel_order(order_id, symbol)
            return True
        except ccxt.OrderNotFound:
            logger.warning("cancel_order_not_found", order_id=order_id)
            return False

    @retry_with_backoff(max_retries=3, base_delay=0.5)
    async def get_order(self, order_id: str, symbol: str) -> OrderResult:
        await self._rate_limiter.acquire()
        raw = await self._exchange.fetch_order(order_id, symbol)
        return OrderResult.from_ccxt(raw)

    @retry_with_backoff(max_retries=3, base_delay=0.5)
    async def get_open_orders(self, symbol: str) -> list[OrderResult]:
        await self._rate_limiter.acquire()
        raw_orders = await self._exchange.fetch_open_orders(symbol)
        return [OrderResult.from_ccxt(o) for o in raw_orders]

    @retry_with_backoff(max_retries=3, base_delay=1.0)
    async def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        since: int | None = None,
        limit: int | None = None,
    ) -> list[list]:
        await self._rate_limiter.acquire()
        return await self._exchange.fetch_ohlcv(symbol, timeframe, since, limit)
