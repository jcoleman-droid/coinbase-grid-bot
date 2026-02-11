import pytest
import pytest_asyncio

from src.db.repositories import GridLevelRepository, OrderRepository
from src.orders.manager import OrderManager


@pytest_asyncio.fixture
async def order_mgr(db, paper_exchange):
    order_repo = OrderRepository(db.conn)
    level_repo = GridLevelRepository(db.conn)
    return OrderManager(paper_exchange, order_repo, level_repo)


@pytest.mark.asyncio
async def test_place_order(order_mgr):
    result = await order_mgr.place_grid_order(
        symbol="BTC/USD", side="buy", amount=0.001, price=55000.0, grid_level_index=0
    )
    assert result.exchange_order_id
    assert result.side == "buy"
    assert order_mgr.open_order_count == 1


@pytest.mark.asyncio
async def test_cancel_order(order_mgr):
    result = await order_mgr.place_grid_order(
        symbol="BTC/USD", side="buy", amount=0.001, price=55000.0, grid_level_index=0
    )
    success = await order_mgr.cancel_order(result.exchange_order_id, "BTC/USD")
    assert success is True
    assert order_mgr.open_order_count == 0
