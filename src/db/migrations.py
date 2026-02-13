from __future__ import annotations

import aiosqlite

SCHEMA = """
CREATE TABLE IF NOT EXISTS grid_configs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol          TEXT NOT NULL,
    lower_price     REAL NOT NULL,
    upper_price     REAL NOT NULL,
    num_levels      INTEGER NOT NULL,
    spacing         TEXT NOT NULL DEFAULT 'arithmetic',
    order_size_usd  REAL,
    order_size_base REAL,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    is_active       INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS grid_levels (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    config_id           INTEGER NOT NULL REFERENCES grid_configs(id),
    level_index         INTEGER NOT NULL,
    price               REAL NOT NULL,
    side                TEXT NOT NULL,
    status              TEXT NOT NULL DEFAULT 'pending',
    exchange_order_id   TEXT,
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at          TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS orders (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    exchange_order_id   TEXT UNIQUE,
    grid_level_id       INTEGER,
    symbol              TEXT NOT NULL,
    side                TEXT NOT NULL,
    order_type          TEXT NOT NULL DEFAULT 'limit',
    price               REAL NOT NULL,
    amount              REAL NOT NULL,
    filled_amount       REAL NOT NULL DEFAULT 0.0,
    avg_fill_price      REAL,
    fee                 REAL NOT NULL DEFAULT 0.0,
    fee_currency        TEXT,
    status              TEXT NOT NULL DEFAULT 'open',
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at          TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS trades (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    buy_order_id    INTEGER REFERENCES orders(id),
    sell_order_id   INTEGER REFERENCES orders(id),
    symbol          TEXT NOT NULL,
    buy_price       REAL NOT NULL,
    sell_price      REAL NOT NULL,
    amount          REAL NOT NULL,
    profit_usd      REAL NOT NULL,
    fees_usd        REAL NOT NULL,
    net_profit_usd  REAL NOT NULL,
    closed_at       TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS position_snapshots (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp           TEXT NOT NULL DEFAULT (datetime('now')),
    symbol              TEXT NOT NULL,
    base_balance        REAL NOT NULL,
    quote_balance       REAL NOT NULL,
    avg_entry_price     REAL,
    current_price       REAL NOT NULL,
    unrealized_pnl_usd REAL NOT NULL,
    realized_pnl_usd   REAL NOT NULL,
    total_equity_usd    REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS bot_state (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);
CREATE INDEX IF NOT EXISTS idx_orders_exchange_id ON orders(exchange_order_id);
CREATE INDEX IF NOT EXISTS idx_orders_symbol ON orders(symbol);
CREATE INDEX IF NOT EXISTS idx_grid_levels_config ON grid_levels(config_id);
CREATE INDEX IF NOT EXISTS idx_position_snapshots_ts ON position_snapshots(timestamp);
CREATE INDEX IF NOT EXISTS idx_position_snapshots_symbol ON position_snapshots(symbol);
CREATE INDEX IF NOT EXISTS idx_trades_symbol ON trades(symbol);
"""

MIGRATIONS = [
    "ALTER TABLE position_snapshots ADD COLUMN secured_profits_usd REAL NOT NULL DEFAULT 0.0",
]


async def run_migrations(conn: aiosqlite.Connection) -> None:
    await conn.executescript(SCHEMA)
    for sql in MIGRATIONS:
        try:
            await conn.execute(sql)
        except Exception:
            pass  # Column already exists
    await conn.commit()
