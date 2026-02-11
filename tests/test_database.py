import pytest
import pytest_asyncio

from src.db.repositories import BotStateRepository, OrderRepository, TradeRepository


@pytest.mark.asyncio
async def test_insert_and_get_order(db):
    repo = OrderRepository(db.conn)
    order_id = await repo.insert(
        {
            "exchange_order_id": "test-123",
            "symbol": "BTC/USD",
            "side": "buy",
            "price": 55000.0,
            "amount": 0.001,
        }
    )
    assert order_id is not None

    order = await repo.get_by_exchange_id("test-123")
    assert order is not None
    assert order["side"] == "buy"
    assert order["price"] == 55000.0


@pytest.mark.asyncio
async def test_update_order_status(db):
    repo = OrderRepository(db.conn)
    await repo.insert(
        {
            "exchange_order_id": "test-456",
            "symbol": "BTC/USD",
            "side": "sell",
            "price": 65000.0,
            "amount": 0.001,
        }
    )
    await repo.update_status("test-456", "filled", 0.001, 65000.0, 0.39)
    order = await repo.get_by_exchange_id("test-456")
    assert order["status"] == "filled"
    assert order["filled_amount"] == 0.001


@pytest.mark.asyncio
async def test_open_orders(db):
    repo = OrderRepository(db.conn)
    await repo.insert(
        {
            "exchange_order_id": "o1",
            "symbol": "BTC/USD",
            "side": "buy",
            "price": 55000.0,
            "amount": 0.001,
        }
    )
    await repo.insert(
        {
            "exchange_order_id": "o2",
            "symbol": "BTC/USD",
            "side": "sell",
            "price": 65000.0,
            "amount": 0.001,
            "status": "filled",
        }
    )
    open_orders = await repo.get_open_orders()
    assert len(open_orders) == 1
    assert open_orders[0]["exchange_order_id"] == "o1"


@pytest.mark.asyncio
async def test_trade_pnl(db):
    repo = TradeRepository(db.conn)
    await repo.insert(
        {
            "symbol": "BTC/USD",
            "buy_price": 55000.0,
            "sell_price": 56000.0,
            "amount": 0.01,
            "profit_usd": 10.0,
            "fees_usd": 0.66,
            "net_profit_usd": 9.34,
        }
    )
    total = await repo.get_total_pnl()
    assert abs(total - 9.34) < 0.01


@pytest.mark.asyncio
async def test_bot_state(db):
    repo = BotStateRepository(db.conn)
    await repo.set("last_price", "60000.0")
    val = await repo.get("last_price")
    assert val == "60000.0"

    await repo.set("last_price", "61000.0")
    val = await repo.get("last_price")
    assert val == "61000.0"

    all_state = await repo.get_all()
    assert "last_price" in all_state
