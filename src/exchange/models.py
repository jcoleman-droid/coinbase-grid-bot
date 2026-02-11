from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Ticker:
    symbol: str
    last: float
    bid: float = 0.0
    ask: float = 0.0
    timestamp: int = 0

    @classmethod
    def from_ccxt(cls, raw: dict) -> Ticker:
        return cls(
            symbol=raw.get("symbol", ""),
            last=float(raw.get("last", 0)),
            bid=float(raw.get("bid") or 0),
            ask=float(raw.get("ask") or 0),
            timestamp=int(raw.get("timestamp") or 0),
        )


@dataclass
class OrderResult:
    exchange_order_id: str
    symbol: str
    side: str
    order_type: str
    price: float
    amount: float
    filled_amount: float = 0.0
    avg_fill_price: float | None = None
    fee: float = 0.0
    fee_currency: str = ""
    status: str = "open"
    timestamp: int = 0

    @classmethod
    def from_ccxt(cls, raw: dict) -> OrderResult:
        fee_info = raw.get("fee") or {}
        return cls(
            exchange_order_id=str(raw.get("id", "")),
            symbol=raw.get("symbol", ""),
            side=raw.get("side", ""),
            order_type=raw.get("type", "limit"),
            price=float(raw.get("price") or 0),
            amount=float(raw.get("amount") or 0),
            filled_amount=float(raw.get("filled") or 0),
            avg_fill_price=float(raw["average"]) if raw.get("average") else None,
            fee=float(fee_info.get("cost") or 0),
            fee_currency=fee_info.get("currency", ""),
            status=raw.get("status", "open"),
            timestamp=int(raw.get("timestamp") or 0),
        )


@dataclass
class Balance:
    free: dict[str, float] = field(default_factory=dict)
    used: dict[str, float] = field(default_factory=dict)
    total: dict[str, float] = field(default_factory=dict)

    @classmethod
    def from_ccxt(cls, raw: dict) -> Balance:
        return cls(
            free=raw.get("free", {}),
            used=raw.get("used", {}),
            total=raw.get("total", {}),
        )


@dataclass
class OHLCV:
    timestamp: int
    open: float
    high: float
    low: float
    close: float
    volume: float
