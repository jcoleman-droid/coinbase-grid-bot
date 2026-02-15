from __future__ import annotations

import time

import aiohttp
import structlog

from ..config.schema import LunarCrushConfig

logger = structlog.get_logger()

# Map trading pair symbols to CoinGecko IDs
SYMBOL_MAP: dict[str, str] = {
    "BONK/USD": "bonk",
    "WIF/USD": "dogwifhat",
    "PEPE/USD": "pepe",
    "SHIB/USD": "shiba-inu",
    "SUI/USD": "sui",
    "INJ/USD": "injective-protocol",
    "BTC/USD": "bitcoin",
    "ETH/USD": "ethereum",
    "SOL/USD": "solana",
    "DOGE/USD": "dogecoin",
    "XRP/USD": "ripple",
    "ADA/USD": "cardano",
}

REVERSE_MAP: dict[str, str] = {v: k for k, v in SYMBOL_MAP.items()}


class LunarCrushProvider:
    """Fetches market sentiment from CoinGecko free API (single batch call).

    Uses a normalized score 0-100 based on 24h price change and market activity.
    Coins with strong positive momentum score high; dumping coins score low.
    Caches results with a configurable TTL.
    """

    MARKETS_URL = "https://api.coingecko.com/api/v3/coins/markets"

    def __init__(self, config: LunarCrushConfig):
        self._config = config
        self._cache: dict[str, dict] = {}
        self._cache_time: float = 0.0

    async def fetch_scores(self, symbols: list[str]) -> None:
        now = time.time()
        if now - self._cache_time < self._config.cache_ttl_secs and self._cache:
            return

        coin_ids = []
        for sym in symbols:
            cid = SYMBOL_MAP.get(sym)
            if cid:
                coin_ids.append(cid)

        if not coin_ids:
            return

        new_cache: dict[str, dict] = {}
        try:
            params = {
                "vs_currency": "usd",
                "ids": ",".join(coin_ids),
                "order": "market_cap_desc",
                "per_page": str(len(coin_ids)),
                "page": "1",
                "sparkline": "false",
                "price_change_percentage": "24h",
            }
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    self.MARKETS_URL,
                    params=params,
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        for coin in data:
                            sym = REVERSE_MAP.get(coin["id"])
                            if not sym:
                                continue
                            pct_24h = coin.get("price_change_percentage_24h") or 0
                            # Normalize to 0-100 scale:
                            # -10% or worse = 0, +10% or better = 100, 0% = 50
                            score = max(0.0, min(100.0, 50.0 + pct_24h * 5))
                            new_cache[sym] = {
                                "galaxy_score": round(score, 1),
                                "sentiment": round(score, 1),
                                "price_change_24h": round(pct_24h, 2),
                                "market_cap_rank": coin.get("market_cap_rank"),
                                "source": "coingecko",
                            }
                    elif resp.status == 429:
                        logger.debug("coingecko_rate_limited")
                    else:
                        logger.debug("coingecko_fetch_status", status=resp.status)

            if new_cache:
                self._cache = new_cache
                self._cache_time = now
                logger.info(
                    "sentiment_updated",
                    coins=len(new_cache),
                    scores={
                        s: d["galaxy_score"]
                        for s, d in new_cache.items()
                    },
                )
        except Exception as e:
            logger.warning("sentiment_fetch_failed", error=str(e))

    def get_score(self, symbol: str) -> dict | None:
        return self._cache.get(symbol)

    def get_all_scores(self) -> dict[str, dict]:
        return dict(self._cache)

    @property
    def last_fetch_time(self) -> float:
        return self._cache_time
