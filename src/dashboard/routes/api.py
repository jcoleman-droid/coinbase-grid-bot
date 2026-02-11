from __future__ import annotations

from fastapi import APIRouter, Request

from ...db.repositories import OrderRepository, PositionSnapshotRepository, TradeRepository

router = APIRouter()


@router.get("/status")
async def get_status(request: Request):
    bot = request.app.state.bot
    position = bot.position_tracker
    return {
        "status": bot.status.value,
        "position": (
            {
                "base_balance": position.state.base_balance,
                "quote_balance": position.state.quote_balance,
                "avg_entry_price": position.state.avg_entry_price,
                "realized_pnl": position.state.realized_pnl,
                "unrealized_pnl": position.state.unrealized_pnl,
                "total_fees": position.state.total_fees,
                "trade_count": position.state.trade_count,
            }
            if position
            else None
        ),
    }


@router.get("/grid")
async def get_grid(request: Request):
    engine = request.app.state.bot.grid_engine
    if not engine:
        return {"levels": []}
    return {
        "levels": [
            {
                "index": l.index,
                "price": l.price,
                "side": l.side,
                "status": l.status,
            }
            for l in engine.levels
        ]
    }


@router.get("/orders")
async def get_orders(request: Request, status: str = "all", limit: int = 100):
    db = request.app.state.bot.database
    if not db:
        return {"orders": []}
    repo = OrderRepository(db.conn)
    if status == "all":
        orders = await repo.get_recent(limit)
    else:
        orders = await repo.get_by_status(status, limit)
    return {"orders": orders}


@router.get("/trades")
async def get_trades(request: Request, limit: int = 100):
    db = request.app.state.bot.database
    if not db:
        return {"trades": []}
    repo = TradeRepository(db.conn)
    trades = await repo.get_recent(limit)
    return {"trades": trades}


@router.get("/pnl")
async def get_pnl(request: Request, period: str = "24h"):
    db = request.app.state.bot.database
    if not db:
        return {"snapshots": [], "realized_pnl": 0.0}
    repo = PositionSnapshotRepository(db.conn)
    snapshots = await repo.get_range_by_period(period)
    position = request.app.state.bot.position_tracker
    return {
        "snapshots": snapshots,
        "realized_pnl": position.state.realized_pnl if position else 0.0,
    }


@router.get("/equity-curve")
async def get_equity_curve(request: Request):
    db = request.app.state.bot.database
    if not db:
        return {"curve": []}
    repo = PositionSnapshotRepository(db.conn)
    snapshots = await repo.get_all()
    return {"curve": snapshots}
