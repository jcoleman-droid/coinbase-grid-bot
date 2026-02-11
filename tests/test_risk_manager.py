import pytest
import pytest_asyncio

from src.config.schema import RiskConfig
from src.db.repositories import (
    GridLevelRepository,
    OrderRepository,
    PositionSnapshotRepository,
    TradeRepository,
)
from src.orders.manager import OrderManager
from src.position.tracker import PositionTracker
from src.risk.manager import RiskManager


@pytest_asyncio.fixture
async def risk_setup(db, paper_exchange):
    order_repo = OrderRepository(db.conn)
    level_repo = GridLevelRepository(db.conn)
    trade_repo = TradeRepository(db.conn)
    snapshot_repo = PositionSnapshotRepository(db.conn)

    order_mgr = OrderManager(paper_exchange, order_repo, level_repo)
    position = PositionTracker(
        "BTC/USD", paper_exchange, trade_repo, snapshot_repo, initial_quote=10000.0
    )
    config = RiskConfig(
        max_position_usd=5000.0,
        max_open_orders=5,
        stop_loss_pct=5.0,
        take_profit_pct=3.0,
        max_drawdown_pct=10.0,
    )
    risk_mgr = RiskManager(config, position, order_mgr)
    return risk_mgr, order_mgr, position


@pytest.mark.asyncio
async def test_can_place_order(risk_setup):
    risk_mgr, _, _ = risk_setup
    assert risk_mgr.can_place_order("buy", 55000.0) is True


@pytest.mark.asyncio
async def test_max_open_orders(risk_setup, paper_exchange):
    risk_mgr, order_mgr, _ = risk_setup
    for i in range(5):
        await order_mgr.place_grid_order(
            "BTC/USD", "buy", 0.001, 55000.0 + i * 100, i
        )
    assert risk_mgr.can_place_order("buy", 55000.0) is False


def test_stop_loss(risk_setup):
    risk_mgr, _, _ = risk_setup
    # Lower grid at 55000, stop_loss_pct = 5% -> stop at 52250
    assert risk_mgr.check_stop_loss(53000.0, 55000.0) is False
    assert risk_mgr.check_stop_loss(52000.0, 55000.0) is True
    assert risk_mgr.is_halted is True


def test_take_profit(risk_setup):
    risk_mgr, _, _ = risk_setup
    # Upper grid at 65000, take_profit_pct = 3% -> TP at 66950
    assert risk_mgr.check_take_profit(66000.0, 65000.0) is False
    assert risk_mgr.check_take_profit(67000.0, 65000.0) is True


def test_drawdown_halt(risk_setup):
    risk_mgr, _, _ = risk_setup
    risk_mgr.check_drawdown(10000.0)  # set peak
    assert risk_mgr.check_drawdown(9500.0) is False  # 5% < 10%
    assert risk_mgr.check_drawdown(8900.0) is True  # 11% > 10%
    assert risk_mgr.is_halted is True


def test_reset_halt(risk_setup):
    risk_mgr, _, _ = risk_setup
    risk_mgr.check_stop_loss(50000.0, 55000.0)
    assert risk_mgr.is_halted is True
    risk_mgr.reset_halt()
    assert risk_mgr.is_halted is False
