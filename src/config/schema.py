from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field, model_validator


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
    trailing_cooldown_secs: float = Field(default=60.0, ge=5)


class RiskConfig(BaseModel):
    max_position_usd: float = 5000.0
    max_position_usd_per_pair: float = 200.0
    max_open_orders: int = 200
    stop_loss_pct: float = 5.0
    take_profit_pct: float = 3.0
    max_drawdown_pct: float = 10.0


class PoolConfig(BaseModel):
    initial_balance_usd: float = 1000.0


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


class TrendFilterConfig(BaseModel):
    enabled: bool = True
    short_window: int = 10
    long_window: int = 60


class PositionStopLossConfig(BaseModel):
    enabled: bool = True
    threshold_pct: float = 2.0
    cooldown_secs: float = 300.0


class PairRotationConfig(BaseModel):
    enabled: bool = True
    evaluation_interval_secs: float = 1800.0
    pause_threshold: float = -1.0
    min_trades_before_eval: int = 5


class StrategyAllocationConfig(BaseModel):
    grid_pct: float = Field(default=60.0, ge=0, le=100)
    momentum_pct: float = Field(default=25.0, ge=0, le=100)
    dip_sniper_pct: float = Field(default=15.0, ge=0, le=100)

    @model_validator(mode="after")
    def check_total(self) -> StrategyAllocationConfig:
        total = self.grid_pct + self.momentum_pct + self.dip_sniper_pct
        if abs(total - 100.0) > 0.01:
            raise ValueError(f"Strategy allocations must sum to 100%, got {total}%")
        return self


class MomentumRiderConfig(BaseModel):
    enabled: bool = False
    position_size_usd: float = Field(default=40.0, gt=0)
    min_trend_confirms: int = Field(default=3, ge=1)


class DipSniperConfig(BaseModel):
    enabled: bool = False
    position_size_usd: float = Field(default=25.0, gt=0)
    lookback_count: int = Field(default=10, ge=3)
    dip_threshold_pct: float = Field(default=-3.0, lt=0)
    take_profit_pct: float = Field(default=1.5, gt=0)
    stop_loss_pct: float = Field(default=2.0, gt=0)
    cooldown_secs: float = Field(default=30.0, ge=0)


class RSIConfig(BaseModel):
    enabled: bool = True
    period: int = Field(default=14, ge=2)
    oversold: float = Field(default=30.0, ge=0, le=50)
    overbought: float = Field(default=70.0, ge=50, le=100)


class LunarCrushConfig(BaseModel):
    enabled: bool = True
    min_galaxy_score: float = Field(default=40.0, ge=0, le=100)
    cache_ttl_secs: float = Field(default=300.0, ge=60)


class FearGreedConfig(BaseModel):
    enabled: bool = True
    extreme_fear_threshold: int = Field(default=25, ge=0, le=50)
    reduce_size_pct: float = Field(default=50.0, ge=0, le=100)


class BotConfig(BaseModel):
    exchange: ExchangeConfig
    grids: list[GridConfig]
    risk: RiskConfig
    pool: PoolConfig = PoolConfig()
    paper_trading: PaperTradingConfig = PaperTradingConfig()
    backtest: BacktestConfig = BacktestConfig()
    dashboard: DashboardConfig = DashboardConfig()
    trend_filter: TrendFilterConfig = TrendFilterConfig()
    position_stop_loss: PositionStopLossConfig = PositionStopLossConfig()
    pair_rotation: PairRotationConfig = PairRotationConfig()
    strategy_allocation: StrategyAllocationConfig = StrategyAllocationConfig()
    momentum_rider: MomentumRiderConfig = MomentumRiderConfig()
    dip_sniper: DipSniperConfig = DipSniperConfig()
    rsi: RSIConfig = RSIConfig()
    lunarcrush: LunarCrushConfig = LunarCrushConfig()
    fear_greed: FearGreedConfig = FearGreedConfig()

    @model_validator(mode="before")
    @classmethod
    def migrate_single_grid(cls, data: dict) -> dict:
        """Backward compat: accept 'grid' key and wrap it in a list."""
        if isinstance(data, dict) and "grid" in data and "grids" not in data:
            data["grids"] = [data.pop("grid")]
        return data
