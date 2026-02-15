from __future__ import annotations

import time

import aiohttp
import structlog

logger = structlog.get_logger()

GLOBAL_URL = "https://api.coingecko.com/api/v3/global"


class BTCDominanceProvider:
    """Tracks Bitcoin market dominance from CoinGecko.

    When BTC dominance drops below threshold (default 50%), it signals
    alt season — money rotating from BTC into altcoins like our meme coins.
    """

    def __init__(
        self, alt_season_threshold: float = 50.0, cache_ttl_secs: float = 300.0
    ):
        self._threshold = alt_season_threshold
        self._cache_ttl = cache_ttl_secs
        self._dominance: float | None = None
        self._total_market_cap: float | None = None
        self._cache_time: float = 0.0

    async def fetch(self) -> None:
        now = time.time()
        if now - self._cache_time < self._cache_ttl and self._dominance is not None:
            return

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    GLOBAL_URL, timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        market = data.get("data", {})
                        pcts = market.get("market_cap_percentage", {})
                        self._dominance = round(pcts.get("btc", 0), 2)
                        self._total_market_cap = market.get("total_market_cap", {}).get(
                            "usd"
                        )
                        self._cache_time = now
                        logger.info(
                            "btc_dominance_updated",
                            dominance=self._dominance,
                            alt_season=self.is_alt_season(),
                        )
                    elif resp.status == 429:
                        logger.debug("coingecko_global_rate_limited")
                    else:
                        logger.debug("btc_dominance_fetch_status", status=resp.status)
        except Exception as e:
            logger.warning("btc_dominance_fetch_failed", error=str(e))

    def get_dominance(self) -> float | None:
        return self._dominance

    def is_alt_season(self) -> bool:
        if self._dominance is None:
            return False
        return self._dominance < self._threshold

    @property
    def total_market_cap(self) -> float | None:
        return self._total_market_cap

    @property
    def last_fetch_time(self) -> float:
        return self._cache_time
