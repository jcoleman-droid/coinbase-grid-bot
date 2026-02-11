from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass
class BacktestReport:
    equity_curve: pd.DataFrame
    trades: pd.DataFrame
    config: object

    @property
    def total_return_pct(self) -> float:
        if len(self.equity_curve) < 2:
            return 0.0
        start = self.equity_curve.iloc[0]["total_equity"]
        end = self.equity_curve.iloc[-1]["total_equity"]
        if start == 0:
            return 0.0
        return ((end - start) / start) * 100

    @property
    def max_drawdown_pct(self) -> float:
        if len(self.equity_curve) < 2:
            return 0.0
        equity = self.equity_curve["total_equity"]
        peak = equity.cummax()
        drawdown = (peak - equity) / peak * 100
        return float(drawdown.max())

    @property
    def total_trades(self) -> int:
        return len(self.trades)

    @property
    def total_fees(self) -> float:
        if len(self.trades) == 0:
            return 0.0
        return float(self.trades["fee"].sum())

    @property
    def sharpe_ratio(self) -> float:
        if len(self.equity_curve) < 2:
            return 0.0
        returns = self.equity_curve["total_equity"].pct_change().dropna()
        if returns.std() == 0:
            return 0.0
        return float((returns.mean() / returns.std()) * (252**0.5))

    def summary(self) -> dict:
        final_equity = 0.0
        if len(self.equity_curve) > 0:
            final_equity = round(float(self.equity_curve.iloc[-1]["total_equity"]), 2)
        return {
            "total_return_pct": round(self.total_return_pct, 2),
            "max_drawdown_pct": round(self.max_drawdown_pct, 2),
            "total_trades": self.total_trades,
            "total_fees": round(self.total_fees, 4),
            "sharpe_ratio": round(self.sharpe_ratio, 3),
            "final_equity": final_equity,
        }
