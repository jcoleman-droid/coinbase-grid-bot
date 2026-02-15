from __future__ import annotations

import time

import aiohttp
import structlog

logger = structlog.get_logger()

API_URL = "https://api.alternative.me/fng/"


class FearGreedProvider:
    """Fetches the Crypto Fear & Greed Index from alternative.me.

    Scale: 0 = Extreme Fear, 100 = Extreme Greed.
    Caches the result with a configurable TTL.
    """

    def __init__(self, cache_ttl_secs: float = 300.0):
        self._cache_ttl = cache_ttl_secs
        self._value: int | None = None
        self._classification: str = "unknown"
        self._cache_time: float = 0.0

    async def fetch(self) -> None:
        now = time.time()
        if now - self._cache_time < self._cache_ttl and self._value is not None:
            return

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    API_URL, timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        entry = data.get("data", [{}])[0]
                        self._value = int(entry.get("value", 50))
                        self._classification = entry.get(
                            "value_classification", "unknown"
                        )
                        self._cache_time = now
                        logger.info(
                            "fear_greed_updated",
                            value=self._value,
                            classification=self._classification,
                        )
                    else:
                        logger.debug("fear_greed_fetch_status", status=resp.status)
        except Exception as e:
            logger.warning("fear_greed_fetch_failed", error=str(e))

    def get_index(self) -> int | None:
        return self._value

    @property
    def classification(self) -> str:
        return self._classification

    @property
    def last_fetch_time(self) -> float:
        return self._cache_time
