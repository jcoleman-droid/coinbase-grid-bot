from __future__ import annotations

import time

import aiohttp
import structlog

logger = structlog.get_logger()

TRENDING_URL = "https://api.coingecko.com/api/v3/search/trending"

# Map CoinGecko coin IDs to our trading symbols
COINGECKO_TO_SYMBOL: dict[str, str] = {
    "bonk": "BONK/USD",
    "dogwifcoin": "WIF/USD",
    "pepe": "PEPE/USD",
    "shiba-inu": "SHIB/USD",
    "sui": "SUI/USD",
    "injective-protocol": "INJ/USD",
    "bitcoin": "BTC/USD",
    "ethereum": "ETH/USD",
    "solana": "SOL/USD",
    "dogecoin": "DOGE/USD",
}


class SocialTrending:
    """Tracks CoinGecko trending coins and flags our coins that are trending."""

    def __init__(self, cache_ttl_secs: float = 300.0):
        self._cache_ttl = cache_ttl_secs
        self._trending: list[dict] = []
        self._our_trending: set[str] = set()
        self._cache_time: float = 0.0

    async def fetch(self) -> None:
        now = time.time()
        if now - self._cache_time < self._cache_ttl and self._trending:
            return

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    TRENDING_URL, timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        coins = data.get("coins", [])
                        self._trending = []
                        self._our_trending = set()

                        for i, entry in enumerate(coins):
                            item = entry.get("item", {})
                            coin_id = item.get("id", "")
                            name = item.get("name", "")
                            symbol = item.get("symbol", "")
                            self._trending.append({
                                "rank": i + 1,
                                "id": coin_id,
                                "name": name,
                                "symbol": symbol,
                            })
                            our_sym = COINGECKO_TO_SYMBOL.get(coin_id)
                            if our_sym:
                                self._our_trending.add(our_sym)

                        self._cache_time = now
                        if self._our_trending:
                            logger.info(
                                "social_trending_our_coins",
                                trending=list(self._our_trending),
                            )
                        else:
                            logger.debug(
                                "social_trending_updated",
                                total=len(self._trending),
                            )
                    elif resp.status == 429:
                        logger.debug("coingecko_trending_rate_limited")
                    else:
                        logger.debug("trending_fetch_status", status=resp.status)
        except Exception as e:
            logger.warning("trending_fetch_failed", error=str(e))

    def is_trending(self, symbol: str) -> bool:
        return symbol in self._our_trending

    def get_trending(self) -> list[dict]:
        return list(self._trending)

    def get_our_trending(self) -> list[str]:
        return list(self._our_trending)

    @property
    def last_fetch_time(self) -> float:
        return self._cache_time
