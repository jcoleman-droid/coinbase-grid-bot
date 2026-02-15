from __future__ import annotations

import time

from fastapi import APIRouter, Request

from ...db.repositories import OrderRepository, PositionSnapshotRepository, TradeRepository

router = APIRouter()


@router.get("/status")
async def get_status(request: Request):
    bot = request.app.state.bot
    position = bot.position_tracker
    prices = bot.last_live_prices if hasattr(bot, "last_live_prices") else {}

    pairs = {}
    if position:
        for sym, ps in position.all_pair_states.items():
            pairs[sym] = {
                "base_balance": ps.base_balance,
                "avg_entry_price": ps.avg_entry_price,
                "realized_pnl": ps.realized_pnl,
                "unrealized_pnl": ps.unrealized_pnl,
                "trade_count": ps.trade_count,
                "current_price": prices.get(sym, 0.0),
            }

    return {
        "status": bot.status.value,
        "symbols": bot.symbols if hasattr(bot, "symbols") else [],
        "pool": (
            {
                "available_usd": position.pool.available_usd,
                "secured_profits": position.pool.secured_profits,
                "total_fees": position.pool.total_fees,
                "total_trade_count": position.pool.total_trade_count,
            }
            if position
            else None
        ),
        "total_equity": _aggregate_equity(bot),
        "pairs": pairs,
        "position": (
            {
                "base_balance": 0,
                "quote_balance": position.pool.available_usd,
                "avg_entry_price": 0,
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
async def get_grid(request: Request, symbol: str | None = None):
    engines = request.app.state.bot.grid_engines
    if not engines:
        return {"levels": {}}

    if symbol:
        engine = engines.get(symbol)
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

    result = {}
    for sym, engine in engines.items():
        result[sym] = [
            {
                "index": l.index,
                "price": l.price,
                "side": l.side,
                "status": l.status,
            }
            for l in engine.levels
        ]
    return {"levels": result}


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


@router.get("/defenses")
async def get_defenses(request: Request):
    bot = request.app.state.bot

    # Trend filter
    trend_data = {}
    tf = bot.trend_filter if hasattr(bot, "trend_filter") else None
    if tf:
        for sym, trend in tf.get_all_trends().items():
            trend_data[sym] = {
                "trend": trend.value,
                "data_points": tf.data_points(sym),
            }

    # Position stop-loss
    stop_loss_data = {}
    sl = bot.stop_loss if hasattr(bot, "stop_loss") else None
    if sl:
        stop_loss_data = {
            sym: round(remaining, 1)
            for sym, remaining in sl.all_cooldowns.items()
        }

    # Pair rotation
    rotation_data = {}
    pr = bot.pair_rotator if hasattr(bot, "pair_rotator") else None
    if pr:
        rotation_data = {
            "paused_pairs": pr.paused_pairs,
            "scores": {
                sym: {
                    "score": round(ps.score, 4),
                    "realized_pnl": round(ps.realized_pnl, 4),
                    "unrealized_pnl": round(ps.unrealized_pnl, 4),
                    "trade_count": ps.trade_count,
                    "trend": ps.trend.value,
                }
                for sym, ps in pr.latest_scores.items()
            },
        }

    return {
        "trend_filter": trend_data,
        "position_stop_loss_cooldowns": stop_loss_data,
        "pair_rotation": rotation_data,
    }


def _aggregate_equity(bot) -> float:
    total = 0.0
    position = bot.position_tracker
    if position:
        total += position.total_equity_usd
    mr_pos = getattr(bot, "momentum_position_tracker", None)
    if mr_pos:
        total += mr_pos.total_equity_usd
    ds_pos = getattr(bot, "dip_position_tracker", None)
    if ds_pos:
        total += ds_pos.total_equity_usd
    return total


@router.get("/strategies")
async def get_strategies(request: Request):
    bot = request.app.state.bot
    prices = bot.last_live_prices if hasattr(bot, "last_live_prices") else {}

    result = {"grid": None, "momentum_rider": None, "dip_sniper": None}

    # Grid strategy
    grid_pos = bot.position_tracker
    if grid_pos:
        result["grid"] = {
            "pool": {
                "available_usd": grid_pos.pool.available_usd,
                "secured_profits": grid_pos.pool.secured_profits,
                "total_fees": grid_pos.pool.total_fees,
                "total_trade_count": grid_pos.pool.total_trade_count,
            },
            "total_equity": grid_pos.total_equity_usd,
        }

    # Momentum Rider
    mr = getattr(bot, "momentum_rider", None)
    mr_pos = getattr(bot, "momentum_position_tracker", None)
    if mr and mr_pos:
        active = mr.active_positions
        result["momentum_rider"] = {
            "pool": {
                "available_usd": mr_pos.pool.available_usd,
                "secured_profits": mr_pos.pool.secured_profits,
                "total_fees": mr_pos.pool.total_fees,
                "total_trade_count": mr_pos.pool.total_trade_count,
            },
            "total_equity": mr_pos.total_equity_usd,
            "active_positions": {
                sym: {
                    "base_balance": bal,
                    "current_price": prices.get(sym, 0.0),
                }
                for sym, bal in active.items()
            },
        }

    # Dip Sniper
    ds = getattr(bot, "dip_sniper", None)
    ds_pos = getattr(bot, "dip_position_tracker", None)
    if ds and ds_pos:
        active = ds.active_positions
        result["dip_sniper"] = {
            "pool": {
                "available_usd": ds_pos.pool.available_usd,
                "secured_profits": ds_pos.pool.secured_profits,
                "total_fees": ds_pos.pool.total_fees,
                "total_trade_count": ds_pos.pool.total_trade_count,
            },
            "total_equity": ds_pos.total_equity_usd,
            "active_positions": {
                sym: {
                    "entry_price": pos.entry_price,
                    "amount": pos.amount,
                    "take_profit": pos.take_profit_price,
                    "stop_loss": pos.stop_loss_price,
                    "current_price": prices.get(sym, 0.0),
                    "hold_secs": round(time.time() - pos.entry_time, 1),
                }
                for sym, pos in active.items()
            },
        }

    return result
