from __future__ import annotations

from datetime import datetime, timedelta

import aiosqlite


class OrderRepository:
    def __init__(self, conn: aiosqlite.Connection):
        self._conn = conn

    async def insert(self, order: dict) -> int:
        cursor = await self._conn.execute(
            """INSERT INTO orders
               (exchange_order_id, grid_level_id, symbol, side, order_type,
                price, amount, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                order.get("exchange_order_id"),
                order.get("grid_level_id"),
                order["symbol"],
                order["side"],
                order.get("order_type", "limit"),
                order["price"],
                order["amount"],
                order.get("status", "open"),
            ),
        )
        await self._conn.commit()
        return cursor.lastrowid  # type: ignore[return-value]

    async def update_status(
        self,
        exchange_order_id: str,
        status: str,
        filled_amount: float | None = None,
        avg_fill_price: float | None = None,
        fee: float | None = None,
    ) -> None:
        parts = ["status = ?", "updated_at = datetime('now')"]
        params: list = [status]
        if filled_amount is not None:
            parts.append("filled_amount = ?")
            params.append(filled_amount)
        if avg_fill_price is not None:
            parts.append("avg_fill_price = ?")
            params.append(avg_fill_price)
        if fee is not None:
            parts.append("fee = ?")
            params.append(fee)
        params.append(exchange_order_id)
        sql = f"UPDATE orders SET {', '.join(parts)} WHERE exchange_order_id = ?"
        await self._conn.execute(sql, params)
        await self._conn.commit()

    async def get_open_orders(self) -> list[dict]:
        cursor = await self._conn.execute(
            "SELECT * FROM orders WHERE status IN ('open', 'partially_filled')"
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def get_by_exchange_id(self, eid: str) -> dict | None:
        cursor = await self._conn.execute(
            "SELECT * FROM orders WHERE exchange_order_id = ?", (eid,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def get_recent(self, limit: int = 100) -> list[dict]:
        cursor = await self._conn.execute(
            "SELECT * FROM orders ORDER BY created_at DESC LIMIT ?", (limit,)
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def get_by_status(self, status: str, limit: int = 100) -> list[dict]:
        cursor = await self._conn.execute(
            "SELECT * FROM orders WHERE status = ? ORDER BY created_at DESC LIMIT ?",
            (status, limit),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


class TradeRepository:
    def __init__(self, conn: aiosqlite.Connection):
        self._conn = conn

    async def insert(self, trade: dict) -> int:
        cursor = await self._conn.execute(
            """INSERT INTO trades
               (buy_order_id, sell_order_id, symbol, buy_price, sell_price,
                amount, profit_usd, fees_usd, net_profit_usd)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                trade.get("buy_order_id"),
                trade.get("sell_order_id"),
                trade["symbol"],
                trade["buy_price"],
                trade["sell_price"],
                trade["amount"],
                trade["profit_usd"],
                trade["fees_usd"],
                trade["net_profit_usd"],
            ),
        )
        await self._conn.commit()
        return cursor.lastrowid  # type: ignore[return-value]

    async def get_recent(self, limit: int = 100) -> list[dict]:
        cursor = await self._conn.execute(
            "SELECT * FROM trades ORDER BY closed_at DESC LIMIT ?", (limit,)
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def get_total_pnl(self) -> float:
        cursor = await self._conn.execute(
            "SELECT COALESCE(SUM(net_profit_usd), 0) FROM trades"
        )
        row = await cursor.fetchone()
        return row[0] if row else 0.0


class GridConfigRepository:
    def __init__(self, conn: aiosqlite.Connection):
        self._conn = conn

    async def save(self, config: dict) -> int:
        cursor = await self._conn.execute(
            """INSERT INTO grid_configs
               (symbol, lower_price, upper_price, num_levels, spacing,
                order_size_usd, order_size_base)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                config["symbol"],
                config["lower_price"],
                config["upper_price"],
                config["num_levels"],
                config.get("spacing", "arithmetic"),
                config.get("order_size_usd"),
                config.get("order_size_base"),
            ),
        )
        await self._conn.commit()
        return cursor.lastrowid  # type: ignore[return-value]

    async def get_active(self) -> dict | None:
        cursor = await self._conn.execute(
            "SELECT * FROM grid_configs WHERE is_active = 1 ORDER BY id DESC LIMIT 1"
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def deactivate(self, config_id: int) -> None:
        await self._conn.execute(
            "UPDATE grid_configs SET is_active = 0 WHERE id = ?", (config_id,)
        )
        await self._conn.commit()


class GridLevelRepository:
    def __init__(self, conn: aiosqlite.Connection):
        self._conn = conn

    async def insert_levels(self, config_id: int, levels: list[dict]) -> None:
        await self._conn.executemany(
            """INSERT INTO grid_levels
               (config_id, level_index, price, side, status)
               VALUES (?, ?, ?, ?, ?)""",
            [
                (config_id, l["level_index"], l["price"], l["side"], "pending")
                for l in levels
            ],
        )
        await self._conn.commit()

    async def update_status(
        self, level_index: int, status: str, exchange_order_id: str | None = None
    ) -> None:
        if exchange_order_id:
            await self._conn.execute(
                """UPDATE grid_levels
                   SET status = ?, exchange_order_id = ?, updated_at = datetime('now')
                   WHERE level_index = ?""",
                (status, exchange_order_id, level_index),
            )
        else:
            await self._conn.execute(
                """UPDATE grid_levels
                   SET status = ?, updated_at = datetime('now')
                   WHERE level_index = ?""",
                (status, level_index),
            )
        await self._conn.commit()

    async def get_by_config(self, config_id: int) -> list[dict]:
        cursor = await self._conn.execute(
            "SELECT * FROM grid_levels WHERE config_id = ? ORDER BY level_index",
            (config_id,),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


class PositionSnapshotRepository:
    def __init__(self, conn: aiosqlite.Connection):
        self._conn = conn

    async def insert(self, snapshot: dict) -> None:
        await self._conn.execute(
            """INSERT INTO position_snapshots
               (symbol, base_balance, quote_balance, avg_entry_price,
                current_price, unrealized_pnl_usd, realized_pnl_usd,
                total_equity_usd, secured_profits_usd)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                snapshot["symbol"],
                snapshot["base_balance"],
                snapshot["quote_balance"],
                snapshot.get("avg_entry_price"),
                snapshot["current_price"],
                snapshot["unrealized_pnl_usd"],
                snapshot["realized_pnl_usd"],
                snapshot["total_equity_usd"],
                snapshot.get("secured_profits_usd", 0.0),
            ),
        )
        await self._conn.commit()

    async def get_all(self) -> list[dict]:
        cursor = await self._conn.execute(
            "SELECT * FROM position_snapshots ORDER BY timestamp"
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def get_range_by_period(self, period: str) -> list[dict]:
        hours = {"1h": 1, "6h": 6, "24h": 24, "7d": 168, "30d": 720}
        h = hours.get(period, 24)
        since = (datetime.utcnow() - timedelta(hours=h)).isoformat()
        cursor = await self._conn.execute(
            "SELECT * FROM position_snapshots WHERE timestamp >= ? ORDER BY timestamp",
            (since,),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


class BotStateRepository:
    def __init__(self, conn: aiosqlite.Connection):
        self._conn = conn

    async def set(self, key: str, value: str) -> None:
        await self._conn.execute(
            """INSERT INTO bot_state (key, value, updated_at)
               VALUES (?, ?, datetime('now'))
               ON CONFLICT(key) DO UPDATE SET value = ?, updated_at = datetime('now')""",
            (key, value, value),
        )
        await self._conn.commit()

    async def get(self, key: str) -> str | None:
        cursor = await self._conn.execute(
            "SELECT value FROM bot_state WHERE key = ?", (key,)
        )
        row = await cursor.fetchone()
        return row[0] if row else None

    async def get_all(self) -> dict[str, str]:
        cursor = await self._conn.execute("SELECT key, value FROM bot_state")
        rows = await cursor.fetchall()
        return {r[0]: r[1] for r in rows}
