from __future__ import annotations

import ccxt.async_support as ccxt
import structlog

from ..utils.decorators import retry_with_backoff
from .models import Balance, OrderResult, Ticker
from .rate_limiter import TokenBucketRateLimiter

logger = structlog.get_logger()

# Maps our internal symbol format to CCXT krakenfutures format
# e.g. "SOL/USD" -> "SOL/USD:USD"
def _to_futures_symbol(symbol: str) -> str:
    if symbol.endswith(":USD"):
        return symbol
    base, quote = symbol.split("/")
    return f"{base}/{quote}:{quote}"


class KrakenFuturesConnector:
    """
    Kraken Futures connector using CCXT.
    Implements the same ExchangeInterface as CoinbaseConnector, plus
    futures-specific methods: set_leverage, get_positions, close_position.

    Testnet (sandbox=True): https://demo-futures.kraken.com
    """

    def __init__(self, api_key: str, api_secret: str, sandbox: bool = True):
        config: dict = {
            "apiKey": api_key,
            "secret": api_secret,
            "enableRateLimit": True,
            "options": {"defaultType": "swap"},
        }
        if sandbox:
            config["urls"] = {
                "api": {
                    "public": "https://demo-futures.kraken.com/derivatives/api/v3",
                    "private": "https://demo-futures.kraken.com/derivatives/api/v3",
                }
            }
        self._exchange = ccxt.krakenfutures(config)
        self._rate_limiter = TokenBucketRateLimiter(rate=10, capacity=15)
        self._sandbox = sandbox
        self._leverage: dict[str, int] = {}

    async def connect(self) -> None:
        await self._exchange.load_markets()
        logger.info("exchange_connected", exchange="krakenfutures", sandbox=self._sandbox)

    async def close(self) -> None:
        await self._exchange.close()

    def _sym(self, symbol: str) -> str:
        return _to_futures_symbol(symbol)

    @retry_with_backoff(
        max_retries=3,
        base_delay=1.0,
        retryable_exceptions=(ccxt.NetworkError, ccxt.ExchangeNotAvailable),
    )
    async def get_ticker(self, symbol: str) -> Ticker:
        await self._rate_limiter.acquire()
        raw = await self._exchange.fetch_ticker(self._sym(symbol))
        return Ticker.from_ccxt(raw)

    @retry_with_backoff(max_retries=3, base_delay=1.0)
    async def get_balance(self) -> Balance:
        await self._rate_limiter.acquire()
        raw = await self._exchange.fetch_balance()
        # Kraken Futures returns collateral under 'USD' or 'USDT'
        return Balance.from_ccxt(raw)

    @retry_with_backoff(
        max_retries=3,
        base_delay=1.0,
        retryable_exceptions=(ccxt.NetworkError, ccxt.ExchangeNotAvailable),
    )
    async def place_limit_order(
        self,
        symbol: str,
        side: str,
        amount: float,
        price: float,
        *,
        reduce_only: bool = False,
    ) -> OrderResult:
        await self._rate_limiter.acquire()
        params: dict = {}
        if reduce_only:
            params["reduceOnly"] = True
        raw = await self._exchange.create_order(
            symbol=self._sym(symbol),
            type="limit",
            side=side,
            amount=amount,
            price=price,
            params=params,
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
            symbol=self._sym(symbol),
            type="market",
            side=side,
            amount=amount,
        )
        return OrderResult.from_ccxt(raw)

    @retry_with_backoff(max_retries=3, base_delay=0.5)
    async def cancel_order(self, order_id: str, symbol: str) -> bool:
        await self._rate_limiter.acquire()
        try:
            await self._exchange.cancel_order(order_id, self._sym(symbol))
            return True
        except ccxt.OrderNotFound:
            logger.warning("cancel_order_not_found", order_id=order_id)
            return False

    @retry_with_backoff(max_retries=3, base_delay=0.5)
    async def get_order(self, order_id: str, symbol: str) -> OrderResult:
        await self._rate_limiter.acquire()
        raw = await self._exchange.fetch_order(order_id, self._sym(symbol))
        return OrderResult.from_ccxt(raw)

    @retry_with_backoff(max_retries=3, base_delay=0.5)
    async def get_open_orders(self, symbol: str) -> list[OrderResult]:
        await self._rate_limiter.acquire()
        raw_orders = await self._exchange.fetch_open_orders(self._sym(symbol))
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
        return await self._exchange.fetch_ohlcv(
            self._sym(symbol), timeframe, since, limit
        )

    # ── Futures-specific methods ──────────────────────────────────────────────

    @retry_with_backoff(max_retries=3, base_delay=1.0)
    async def set_leverage(self, symbol: str, leverage: int) -> None:
        await self._rate_limiter.acquire()
        try:
            await self._exchange.set_leverage(leverage, self._sym(symbol))
            self._leverage[symbol] = leverage
            logger.info("leverage_set", symbol=symbol, leverage=leverage)
        except Exception as e:
            logger.warning("set_leverage_failed", symbol=symbol, error=str(e))

    @retry_with_backoff(max_retries=3, base_delay=1.0)
    async def get_positions(self) -> list[dict]:
        """Return all open futures positions."""
        await self._rate_limiter.acquire()
        raw = await self._exchange.fetch_positions()
        positions = []
        for pos in raw:
            if pos.get("contracts", 0) and pos["contracts"] != 0:
                positions.append({
                    "symbol": pos["symbol"],
                    "side": pos.get("side", "long"),
                    "size": abs(pos.get("contracts", 0)),
                    "entry_price": pos.get("entryPrice", 0.0),
                    "unrealized_pnl": pos.get("unrealizedPnl", 0.0),
                    "liquidation_price": pos.get("liquidationPrice", 0.0),
                    "leverage": pos.get("leverage", 1),
                    "margin": pos.get("initialMargin", 0.0),
                })
        return positions

    @retry_with_backoff(max_retries=3, base_delay=1.0)
    async def close_position(self, symbol: str) -> None:
        """Flatten any open position for this symbol at market price."""
        await self._rate_limiter.acquire()
        positions = await self.get_positions()
        fut_sym = self._sym(symbol)
        for pos in positions:
            if pos["symbol"] == fut_sym and pos["size"] > 0:
                close_side = "sell" if pos["side"] == "long" else "buy"
                await self._exchange.create_order(
                    symbol=fut_sym,
                    type="market",
                    side=close_side,
                    amount=pos["size"],
                    params={"reduceOnly": True},
                )
                logger.info(
                    "position_closed",
                    symbol=symbol,
                    side=pos["side"],
                    size=pos["size"],
                )
