from __future__ import annotations

from dataclasses import dataclass

from ..db.repositories import PositionSnapshotRepository, TradeRepository
from ..exchange.base import ExchangeInterface


@dataclass
class PositionState:
    base_balance: float = 0.0
    quote_balance: float = 0.0
    avg_entry_price: float = 0.0
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    total_fees: float = 0.0
    trade_count: int = 0


class PositionTracker:
    def __init__(
        self,
        symbol: str,
        exchange: ExchangeInterface,
        trade_repo: TradeRepository,
        snapshot_repo: PositionSnapshotRepository,
        initial_quote: float = 0.0,
    ):
        self._symbol = symbol
        self._exchange = exchange
        self._trade_repo = trade_repo
        self._snapshot_repo = snapshot_repo
        self._state = PositionState(quote_balance=initial_quote)

    def record_fill(self, side: str, amount: float, price: float, fee: float) -> None:
        if side == "buy":
            total_cost = self._state.base_balance * self._state.avg_entry_price
            new_cost = amount * price
            self._state.base_balance += amount
            self._state.quote_balance -= amount * price + fee
            if self._state.base_balance > 0:
                self._state.avg_entry_price = (
                    (total_cost + new_cost) / self._state.base_balance
                )
        elif side == "sell":
            profit = (price - self._state.avg_entry_price) * amount - fee
            self._state.realized_pnl += profit
            self._state.base_balance -= amount
            self._state.quote_balance += amount * price - fee

        self._state.total_fees += fee
        self._state.trade_count += 1

    async def update_unrealized_pnl(self) -> float:
        ticker = await self._exchange.get_ticker(self._symbol)
        current_price = ticker.last
        if self._state.base_balance > 0:
            self._state.unrealized_pnl = (
                (current_price - self._state.avg_entry_price)
                * self._state.base_balance
            )
        else:
            self._state.unrealized_pnl = 0.0
        return self._state.unrealized_pnl

    async def save_snapshot(self) -> None:
        ticker = await self._exchange.get_ticker(self._symbol)
        total_equity = (
            self._state.quote_balance + self._state.base_balance * ticker.last
        )
        await self._snapshot_repo.insert(
            {
                "symbol": self._symbol,
                "base_balance": self._state.base_balance,
                "quote_balance": self._state.quote_balance,
                "avg_entry_price": self._state.avg_entry_price,
                "current_price": ticker.last,
                "unrealized_pnl_usd": self._state.unrealized_pnl,
                "realized_pnl_usd": self._state.realized_pnl,
                "total_equity_usd": total_equity,
            }
        )

    @property
    def state(self) -> PositionState:
        return self._state
