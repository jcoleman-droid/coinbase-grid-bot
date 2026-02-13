from __future__ import annotations

import asyncio
import json
import time

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter()


@router.websocket("/live")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    bot = websocket.app.state.bot

    try:
        while True:
            position = bot.position_tracker
            engines = bot.grid_engines if hasattr(bot, "grid_engines") else {}
            prices = bot.last_live_prices if hasattr(bot, "last_live_prices") else {}

            # Per-pair data
            pairs_data = {}
            all_grid_levels = []
            for sym, engine in engines.items():
                pair_state = position.pair_state(sym) if position else None
                current_price = prices.get(sym, 0.0)

                # Find matching grid config
                grid_cfg = None
                for gc in bot._config.grids:
                    if gc.symbol == sym:
                        grid_cfg = gc
                        break

                levels = [
                    {
                        "index": l.index,
                        "price": l.price,
                        "side": l.side,
                        "status": l.status,
                    }
                    for l in engine.levels
                ]
                all_grid_levels.extend(levels)

                pairs_data[sym] = {
                    "current_price": current_price,
                    "base_balance": round(pair_state.base_balance, 8) if pair_state else 0,
                    "avg_entry_price": round(pair_state.avg_entry_price, 6) if pair_state else 0,
                    "realized_pnl": round(pair_state.realized_pnl, 2) if pair_state else 0,
                    "unrealized_pnl": round(pair_state.unrealized_pnl, 2) if pair_state else 0,
                    "trade_count": pair_state.trade_count if pair_state else 0,
                    "grid_levels": levels,
                    "grid_config": (
                        {
                            "lower_price": grid_cfg.lower_price,
                            "upper_price": grid_cfg.upper_price,
                            "num_levels": grid_cfg.num_levels,
                            "order_size_usd": grid_cfg.order_size_usd,
                            "spacing": grid_cfg.spacing.value,
                            "trailing_enabled": grid_cfg.trailing_enabled,
                        }
                        if grid_cfg
                        else None
                    ),
                    "trailing": (
                        {
                            "enabled": True,
                            "trigger_pct": grid_cfg.trailing_trigger_pct,
                            "rebalance_pct": grid_cfg.trailing_rebalance_pct,
                            "shift_count": engine.trailing_shift_count,
                        }
                        if grid_cfg and grid_cfg.trailing_enabled
                        else None
                    ),
                    "halted": (
                        bot.risk_manager.is_pair_halted(sym)
                        if bot.risk_manager
                        else False
                    ),
                }

            # Pool / aggregate data
            pool = position.pool if position else None
            total_equity = position.total_equity_usd if position else 0.0

            payload = {
                "status": bot.status.value,
                "total_equity": round(total_equity, 2),
                "pairs": pairs_data,
                "pool": (
                    {
                        "available_usd": round(pool.available_usd, 2),
                        "secured_profits": round(pool.secured_profits, 2),
                        "total_fees": round(pool.total_fees, 2),
                        "total_trade_count": pool.total_trade_count,
                    }
                    if pool
                    else None
                ),
                "position": (
                    {
                        "base_balance": 0,
                        "quote_balance": round(pool.available_usd, 2) if pool else 0,
                        "avg_entry_price": 0,
                        "realized_pnl": round(
                            sum(p.realized_pnl for p in position.all_pair_states.values()), 2
                        ) if position else 0,
                        "unrealized_pnl": round(
                            sum(p.unrealized_pnl for p in position.all_pair_states.values()), 2
                        ) if position else 0,
                        "total_fees": round(pool.total_fees, 2) if pool else 0,
                        "trade_count": pool.total_trade_count if pool else 0,
                        "secured_profits": round(pool.secured_profits, 2) if pool else 0,
                    }
                    if position
                    else None
                ),
                "grid_levels": all_grid_levels,
                "open_order_count": (
                    bot.order_manager.open_order_count if bot.order_manager else 0
                ),
                "risk_halted": (
                    bot.risk_manager.is_halted if bot.risk_manager else False
                ),
                "timestamp": int(time.time() * 1000),
            }
            await websocket.send_text(json.dumps(payload))
            await asyncio.sleep(2.0)

    except WebSocketDisconnect:
        pass
    except Exception:
        pass
