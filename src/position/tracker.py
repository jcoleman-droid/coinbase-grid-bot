from __future__ import annotations

from dataclasses import dataclass, field

from ..db.repositories import PositionSnapshotRepository, TradeRepository
from ..exchange.base import ExchangeInterface


@dataclass
class PairPositionState:
    symbol: str = ""
    base_balance: float = 0.0
    avg_entry_price: float = 0.0
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    trade_count: int = 0


@dataclass
class PoolState:
    available_usd: float = 0.0
    secured_profits: float = 0.0
    total_fees: float = 0.0
    total_trade_count: int = 0


@dataclass
class PositionState:
    """Aggregated view across all pairs — backward compat."""

    base_balance: float = 0.0
    quote_balance: float = 0.0
    avg_entry_price: float = 0.0
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    total_fees: float = 0.0
    trade_count: int = 0
    secured_profits: float = 0.0


class MultiPairPositionTracker:
    def __init__(
        self,
        symbols: list[str],
        exchange: ExchangeInterface,
        trade_repo: TradeRepository,
        snapshot_repo: PositionSnapshotRepository,
        initial_usd: float = 0.0,
    ):
        self._symbols = symbols
        self._exchange = exchange
        self._trade_repo = trade_repo
        self._snapshot_repo = snapshot_repo
        self._pool = PoolState(available_usd=initial_usd)
        self._pairs: dict[str, PairPositionState] = {
            s: PairPositionState(symbol=s) for s in symbols
        }

    def record_fill(
        self, symbol: str, side: str, amount: float, price: float, fee: float
    ) -> None:
        pair = self._pairs[symbol]
        if side == "buy":
            total_cost = pair.base_balance * pair.avg_entry_price
            new_cost = amount * price
            pair.base_balance += amount
            self._pool.available_usd -= amount * price + fee
            if pair.base_balance > 0:
                pair.avg_entry_price = (total_cost + new_cost) / pair.base_balance
        elif side == "sell":
            profit = (price - pair.avg_entry_price) * amount - fee
            pair.realized_pnl += profit
            pair.base_balance -= amount
            self._pool.available_usd += amount * price - fee
            if profit > 0:
                self._pool.secured_profits += profit
                self._pool.available_usd -= profit

        self._pool.total_fees += fee
        pair.trade_count += 1
        self._pool.total_trade_count += 1

    def can_afford_buy(self, cost_usd: float) -> bool:
        return self._pool.available_usd >= cost_usd

    async def update_unrealized_pnl(self, symbol: str) -> float:
        pair = self._pairs[symbol]
        ticker = await self._exchange.get_ticker(symbol)
        if pair.base_balance > 0:
            pair.unrealized_pnl = (
                (ticker.last - pair.avg_entry_price) * pair.base_balance
            )
        else:
            pair.unrealized_pnl = 0.0
        return pair.unrealized_pnl

    async def save_snapshot(self) -> None:
        for symbol, pair in self._pairs.items():
            try:
                ticker = await self._exchange.get_ticker(symbol)
                current_price = ticker.last
            except Exception:
                current_price = pair.avg_entry_price

            await self._snapshot_repo.insert(
                {
                    "symbol": symbol,
                    "base_balance": pair.base_balance,
                    "quote_balance": self._pool.available_usd,
                    "avg_entry_price": pair.avg_entry_price,
                    "current_price": current_price,
                    "unrealized_pnl_usd": pair.unrealized_pnl,
                    "realized_pnl_usd": pair.realized_pnl,
                    "secured_profits_usd": self._pool.secured_profits,
                    "total_equity_usd": self.total_equity_usd,
                }
            )

    @property
    def pool(self) -> PoolState:
        return self._pool

    def pair_state(self, symbol: str) -> PairPositionState:
        return self._pairs[symbol]

    @property
    def all_pair_states(self) -> dict[str, PairPositionState]:
        return dict(self._pairs)

    @property
    def total_base_value_usd(self) -> float:
        return sum(
            p.base_balance * p.avg_entry_price for p in self._pairs.values()
        )

    @property
    def total_equity_usd(self) -> float:
        return (
            self._pool.available_usd
            + self._pool.secured_profits
            + sum(
                p.base_balance * p.avg_entry_price + p.unrealized_pnl
                for p in self._pairs.values()
            )
        )

    @property
    def state(self) -> PositionState:
        """Aggregated view for backward compat."""
        return PositionState(
            base_balance=0.0,
            quote_balance=self._pool.available_usd,
            avg_entry_price=0.0,
            realized_pnl=sum(p.realized_pnl for p in self._pairs.values()),
            unrealized_pnl=sum(p.unrealized_pnl for p in self._pairs.values()),
            total_fees=self._pool.total_fees,
            trade_count=self._pool.total_trade_count,
            secured_profits=self._pool.secured_profits,
        )
