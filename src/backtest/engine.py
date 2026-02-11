from __future__ import annotations

import pandas as pd

from ..config.schema import GridConfig
from ..strategy.grid_math import (
    calculate_order_amount,
    compute_grid_levels,
    determine_order_sides,
)
from .report import BacktestReport
from .simulator import BacktestSimulator


class BacktestEngine:
    def __init__(
        self,
        grid_config: GridConfig,
        fee_pct: float = 0.006,
        slippage_bps: float = 5.0,
        initial_quote: float = 10000.0,
        initial_base: float = 0.0,
    ):
        self._config = grid_config
        self._simulator = BacktestSimulator(fee_pct, slippage_bps)
        self._simulator.set_balances(initial_base, initial_quote)
        self._equity_curve: list[dict] = []
        self._trades: list[dict] = []

    def run(self, data: pd.DataFrame) -> BacktestReport:
        prices = compute_grid_levels(
            self._config.lower_price,
            self._config.upper_price,
            self._config.num_levels,
            self._config.spacing.value,
        )

        initial_price = float(data.iloc[0]["close"])
        sides = determine_order_sides(prices, initial_price)

        # Place initial grid
        for price, side in sides:
            amount = calculate_order_amount(
                self._config.order_size_usd, self._config.order_size_base, price
            )
            self._simulator.place_order(side, price, amount)

        # Process each candle
        for _, candle in data.iterrows():
            high = float(candle["high"])
            low = float(candle["low"])
            close = float(candle["close"])

            filled = self._simulator.process_candle(high, low)

            for order in filled:
                self._trades.append(
                    {
                        "timestamp": candle["timestamp"],
                        "side": order.side,
                        "price": order.fill_price,
                        "amount": order.amount,
                        "fee": order.fee,
                    }
                )
                # Place opposite order at adjacent grid level
                opposite = "sell" if order.side == "buy" else "buy"
                idx = self._find_nearest_level_index(order.price, prices)
                target_idx = idx + 1 if opposite == "sell" else idx - 1
                if 0 <= target_idx < len(prices):
                    amount = calculate_order_amount(
                        self._config.order_size_usd,
                        self._config.order_size_base,
                        prices[target_idx],
                    )
                    self._simulator.place_order(opposite, prices[target_idx], amount)

            # Equity snapshot
            base = self._simulator.base_balance
            quote = self._simulator.quote_balance
            self._equity_curve.append(
                {
                    "timestamp": candle["timestamp"],
                    "price": close,
                    "base_balance": base,
                    "quote_balance": quote,
                    "total_equity": quote + base * close,
                }
            )

        return BacktestReport(
            equity_curve=pd.DataFrame(self._equity_curve),
            trades=pd.DataFrame(self._trades) if self._trades else pd.DataFrame(columns=["timestamp", "side", "price", "amount", "fee"]),
            config=self._config,
        )

    def _find_nearest_level_index(self, price: float, levels: list[float]) -> int:
        return min(range(len(levels)), key=lambda i: abs(levels[i] - price))
