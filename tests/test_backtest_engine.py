import pandas as pd
import pytest

from src.backtest.engine import BacktestEngine
from src.config.schema import GridConfig, GridSpacing


def make_sample_data() -> pd.DataFrame:
    """Create synthetic BTC price data oscillating between 55k-65k."""
    import numpy as np

    timestamps = pd.date_range("2024-01-01", periods=500, freq="1h")
    base = 60000.0
    amplitude = 4000.0
    t = np.linspace(0, 8 * np.pi, 500)
    prices = base + amplitude * np.sin(t) + np.random.normal(0, 200, 500)

    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": prices,
            "high": prices + np.abs(np.random.normal(100, 50, 500)),
            "low": prices - np.abs(np.random.normal(100, 50, 500)),
            "close": prices + np.random.normal(0, 100, 500),
            "volume": np.random.uniform(100, 1000, 500),
        }
    )


def test_backtest_runs():
    config = GridConfig(
        symbol="BTC/USD",
        lower_price=55000.0,
        upper_price=65000.0,
        num_levels=10,
        spacing=GridSpacing.ARITHMETIC,
        order_size_usd=100.0,
    )
    engine = BacktestEngine(
        grid_config=config,
        fee_pct=0.006,
        slippage_bps=5.0,
        initial_quote=10000.0,
    )
    data = make_sample_data()
    report = engine.run(data)

    summary = report.summary()
    assert "total_return_pct" in summary
    assert "max_drawdown_pct" in summary
    assert "total_trades" in summary
    assert "sharpe_ratio" in summary
    assert report.total_trades > 0
    assert len(report.equity_curve) == 500


def test_backtest_no_trades_when_price_flat():
    config = GridConfig(
        symbol="BTC/USD",
        lower_price=55000.0,
        upper_price=65000.0,
        num_levels=10,
        spacing=GridSpacing.ARITHMETIC,
        order_size_usd=100.0,
    )
    engine = BacktestEngine(grid_config=config, initial_quote=10000.0)

    # All candles at 60000 with no range crossing grid levels
    timestamps = pd.date_range("2024-01-01", periods=10, freq="1h")
    data = pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": [60000.0] * 10,
            "high": [60000.5] * 10,
            "low": [59999.5] * 10,
            "close": [60000.0] * 10,
            "volume": [100.0] * 10,
        }
    )
    report = engine.run(data)
    # Very few or no trades since price barely moves
    assert report.total_trades <= 2
