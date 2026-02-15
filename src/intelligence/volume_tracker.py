from __future__ import annotations

from collections import deque

import structlog

logger = structlog.get_logger()


class VolumeTracker:
    """Tracks 24h volume per symbol and detects unusual spikes.

    A spike = current volume > spike_multiplier * rolling average.
    Volume data comes from CoinGecko market data (piggybacked on sentiment fetch).
    """

    def __init__(self, spike_multiplier: float = 2.0, lookback: int = 20):
        self._spike_multiplier = spike_multiplier
        self._volumes: dict[str, deque[float]] = {}
        self._lookback = lookback

    def record_volume(self, symbol: str, volume_24h: float) -> None:
        if symbol not in self._volumes:
            self._volumes[symbol] = deque(maxlen=self._lookback)
        self._volumes[symbol].append(volume_24h)

    def is_spike(self, symbol: str) -> bool:
        vols = self._volumes.get(symbol)
        if not vols or len(vols) < 3:
            return False
        avg = sum(list(vols)[:-1]) / (len(vols) - 1)
        if avg <= 0:
            return False
        return vols[-1] > avg * self._spike_multiplier

    def get_info(self, symbol: str) -> dict | None:
        vols = self._volumes.get(symbol)
        if not vols:
            return None
        vol_list = list(vols)
        latest = vol_list[-1]
        avg = sum(vol_list) / len(vol_list) if vol_list else 0
        return {
            "volume_24h": round(latest, 2),
            "avg_volume": round(avg, 2),
            "spike": self.is_spike(symbol),
            "data_points": len(vols),
        }

    def get_all(self) -> dict[str, dict]:
        return {sym: self.get_info(sym) for sym in self._volumes if self.get_info(sym)}
