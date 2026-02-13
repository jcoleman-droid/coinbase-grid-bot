from __future__ import annotations

import pytest
import pytest_asyncio
import aiosqlite

from src.db.database import Database
from src.db.migrations import run_migrations
from src.exchange.paper_connector import PaperConnector
from src.config.schema import PaperTradingConfig


@pytest_asyncio.fixture
async def db(tmp_path):
    db_path = str(tmp_path / "test.db")
    database = Database(db_path)
    await database.connect()
    await run_migrations(database.conn)
    yield database
    await database.close()


@pytest.fixture
def paper_exchange():
    config = PaperTradingConfig(
        enabled=True,
        initial_balance_usd=10000.0,
        initial_balance_base=0.0,
        simulated_fee_pct=0.006,
    )
    connector = PaperConnector(config)
    connector.simulate_price(60000.0, symbol="BTC/USD")
    return connector
