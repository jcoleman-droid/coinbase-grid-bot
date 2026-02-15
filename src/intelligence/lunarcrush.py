from __future__ import annotations

import asyncio
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


class LunarCrushProvider:
    """Fetches sentiment scores from CoinGecko free API.

    Uses sentiment_votes_up_percentage (0-100) as the primary score.
    Caches results with a configurable TTL to avoid rate limits.
    """

    def __init__(self, config: LunarCrushConfig):
        self._config = config
        self._cache: dict[str, dict] = {}
        self._cache_time: float = 0.0

    async def fetch_scores(self, symbols: list[str]) -> None:
        now = time.time()
        if now - self._cache_time < self._config.cache_ttl_secs and self._cache:
            return

        new_cache: dict[str, dict] = {}
        try:
            async with aiohttp.ClientSession() as session:
                for sym in symbols:
                    coin_id = SYMBOL_MAP.get(sym)
                    if not coin_id:
                        continue
                    try:
                        url = (
                            f"https://api.coingecko.com/api/v3/coins/{coin_id}"
                            "?localization=false&tickers=false&market_data=false"
                            "&community_data=true&developer_data=false&sparkline=false"
                        )
                        async with session.get(
                            url, timeout=aiohttp.ClientTimeout(total=10)
                        ) as resp:
                            if resp.status == 200:
                                data = await resp.json()
                                sentiment_up = data.get(
                                    "sentiment_votes_up_percentage", 0
                                ) or 0
                                new_cache[sym] = {
                                    "galaxy_score": sentiment_up,
                                    "sentiment": sentiment_up,
                                    "sentiment_down": data.get(
                                        "sentiment_votes_down_percentage", 0
                                    ) or 0,
                                    "source": "coingecko",
                                }
                            elif resp.status == 429:
                                logger.debug("coingecko_rate_limited")
                                break
                            else:
                                logger.debug(
                                    "coingecko_fetch_status",
                                    symbol=sym, status=resp.status,
                                )
                        # Small delay between calls to respect rate limits
                        await asyncio.sleep(1.5)
                    except Exception as e:
                        logger.debug(
                            "coingecko_fetch_one_failed",
                            symbol=sym, error=str(e),
                        )

            if new_cache:
                self._cache = new_cache
                self._cache_time = now
                logger.info(
                    "sentiment_updated",
                    coins=len(new_cache),
                    scores={
                        s: round(d["galaxy_score"], 1)
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
