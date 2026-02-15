from __future__ import annotations

import time

import aiohttp
import structlog

from ..config.schema import LunarCrushConfig

logger = structlog.get_logger()

# Map trading pair symbols to LunarCrush topic names
SYMBOL_MAP: dict[str, str] = {
    "BONK/USD": "bonk",
    "WIF/USD": "wif",
    "PEPE/USD": "pepe",
    "SHIB/USD": "shib",
    "SUI/USD": "sui",
    "INJ/USD": "injective",
    "BTC/USD": "bitcoin",
    "ETH/USD": "ethereum",
    "SOL/USD": "solana",
    "DOGE/USD": "dogecoin",
    "XRP/USD": "xrp",
    "ADA/USD": "cardano",
}


class LunarCrushProvider:
    """Fetches galaxy score and sentiment from LunarCrush public API.

    Caches results with a configurable TTL to avoid rate limits.
    """

    BASE_URL = "https://lunarcrush.com/api4/public/topic"

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
                    topic = SYMBOL_MAP.get(sym)
                    if not topic:
                        continue
                    try:
                        url = f"{self.BASE_URL}/{topic}/v1"
                        async with session.get(
                            url, timeout=aiohttp.ClientTimeout(total=10)
                        ) as resp:
                            if resp.status == 200:
                                data = await resp.json()
                                topic_data = data.get("data", {})
                                new_cache[sym] = {
                                    "galaxy_score": topic_data.get("galaxy_score", 0),
                                    "sentiment": topic_data.get("sentiment", 0),
                                    "interactions": topic_data.get("interactions_24h", 0),
                                    "topic": topic,
                                }
                            else:
                                logger.debug(
                                    "lunarcrush_fetch_status",
                                    symbol=sym, status=resp.status,
                                )
                    except Exception as e:
                        logger.debug(
                            "lunarcrush_fetch_one_failed",
                            symbol=sym, error=str(e),
                        )

            if new_cache:
                self._cache = new_cache
                self._cache_time = now
                logger.info(
                    "lunarcrush_updated",
                    coins=len(new_cache),
                    scores={
                        s: round(d["galaxy_score"], 1)
                        for s, d in new_cache.items()
                    },
                )
        except Exception as e:
            logger.warning("lunarcrush_fetch_failed", error=str(e))

    def get_score(self, symbol: str) -> dict | None:
        return self._cache.get(symbol)

    def get_all_scores(self) -> dict[str, dict]:
        return dict(self._cache)

    @property
    def last_fetch_time(self) -> float:
        return self._cache_time
