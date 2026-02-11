from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class GridSpacing(str, Enum):
    ARITHMETIC = "arithmetic"
    GEOMETRIC = "geometric"


class ExchangeConfig(BaseModel):
    name: str = "coinbase"
    sandbox: bool = False
    rate_limit_ms: int = 100


class GridConfig(BaseModel):
    symbol: str
    lower_price: float = Field(gt=0)
    upper_price: float = Field(gt=0)
    num_levels: int = Field(ge=2, le=200)
    spacing: GridSpacing = GridSpacing.ARITHMETIC
    order_size_usd: float | None = Field(default=100.0, gt=0)
    order_size_base: float | None = None
    trailing_enabled: bool = False
    trailing_trigger_pct: float = Field(default=75.0, ge=50, le=95)
    trailing_rebalance_pct: float = Field(default=50.0, ge=10, le=100)
    trailing_cooldown_secs: float = Field(default=60.0, ge=10)


class RiskConfig(BaseModel):
    max_position_usd: float = 5000.0
    max_open_orders: int = 40
    stop_loss_pct: float = 5.0
    take_profit_pct: float = 3.0
    max_drawdown_pct: float = 10.0


class PaperTradingConfig(BaseModel):
    enabled: bool = True
    initial_balance_usd: float = 10000.0
    initial_balance_base: float = 0.0
    simulated_fee_pct: float = 0.006


class BacktestConfig(BaseModel):
    default_timeframe: str = "1m"
    slippage_bps: float = 5


class DashboardConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8080
    enable_controls: bool = True


class BotConfig(BaseModel):
    exchange: ExchangeConfig
    grid: GridConfig
    risk: RiskConfig
    paper_trading: PaperTradingConfig = PaperTradingConfig()
    backtest: BacktestConfig = BacktestConfig()
    dashboard: DashboardConfig = DashboardConfig()
