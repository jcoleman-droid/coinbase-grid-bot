import pytest
import pytest_asyncio

from src.config.schema import GridConfig, GridSpacing, RiskConfig
from src.db.repositories import GridLevelRepository, OrderRepository
from src.exchange.paper_connector import PaperConnector
from src.orders.manager import OrderManager
from src.position.tracker import PositionTracker
from src.risk.manager import RiskManager
from src.strategy.grid_engine import GridEngine
from src.db.repositories import PositionSnapshotRepository, TradeRepository


@pytest_asyncio.fixture
async def grid_engine(db, paper_exchange):
    order_repo = OrderRepository(db.conn)
    level_repo = GridLevelRepository(db.conn)
    trade_repo = TradeRepository(db.conn)
    snapshot_repo = PositionSnapshotRepository(db.conn)

    order_mgr = OrderManager(paper_exchange, order_repo, level_repo)
    position = PositionTracker(
        "BTC/USD", paper_exchange, trade_repo, snapshot_repo, initial_quote=10000.0
    )
    risk_mgr = RiskManager(RiskConfig(), position, order_mgr)

    config = GridConfig(
        symbol="BTC/USD",
        lower_price=55000.0,
        upper_price=65000.0,
        num_levels=5,
        spacing=GridSpacing.ARITHMETIC,
        order_size_usd=100.0,
    )

    engine = GridEngine(config, RiskConfig(), paper_exchange, order_mgr, risk_mgr)
    return engine


@pytest.mark.asyncio
async def test_initialize_grid(grid_engine):
    await grid_engine.initialize_grid()
    levels = grid_engine.levels
    assert len(levels) == 5
    # All levels should have orders placed
    placed = [l for l in levels if l.status == "order_placed"]
    assert len(placed) == 5


@pytest.mark.asyncio
async def test_grid_levels_have_correct_sides(grid_engine):
    await grid_engine.initialize_grid()
    levels = grid_engine.levels
    # Price is 60000, so levels below should be buy, above should be sell
    for l in levels:
        if l.price < 60000:
            assert l.side == "buy"
        else:
            assert l.side == "sell"
