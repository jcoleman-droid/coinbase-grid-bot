from __future__ import annotations

from pathlib import Path

import pandas as pd

from ..exchange.base import ExchangeInterface


class DataLoader:
    @staticmethod
    def from_csv(filepath: str | Path) -> pd.DataFrame:
        df = pd.read_csv(filepath, parse_dates=["timestamp"])
        df.sort_values("timestamp", inplace=True)
        df.reset_index(drop=True, inplace=True)
        return df

    @staticmethod
    async def from_exchange(
        exchange: ExchangeInterface,
        symbol: str,
        timeframe: str = "1m",
        since: int | None = None,
        limit: int = 1000,
    ) -> pd.DataFrame:
        raw = await exchange.fetch_ohlcv(symbol, timeframe, since, limit)
        df = pd.DataFrame(
            raw, columns=["timestamp", "open", "high", "low", "close", "volume"]
        )
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
        return df
