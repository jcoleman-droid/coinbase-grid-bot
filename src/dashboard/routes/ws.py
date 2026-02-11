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
            engine = bot.grid_engine
            position = bot.position_tracker
            exchange = bot._exchange if hasattr(bot, "_exchange") else None

            current_price = 0.0
            if exchange and bot._config:
                try:
                    ticker = await exchange.get_ticker(bot._config.grid.symbol)
                    current_price = ticker.last
                except Exception:
                    pass

            total_equity = 0.0
            if position:
                total_equity = round(
                    position.state.quote_balance
                    + position.state.base_balance * current_price,
                    2,
                )

            grid_config = None
            trailing_info = None
            if bot._config:
                gc = bot._config.grid
                grid_config = {
                    "symbol": gc.symbol,
                    "lower_price": gc.lower_price,
                    "upper_price": gc.upper_price,
                    "num_levels": gc.num_levels,
                    "order_size_usd": gc.order_size_usd,
                    "spacing": gc.spacing.value,
                }
                if gc.trailing_enabled:
                    trailing_info = {
                        "enabled": True,
                        "trigger_pct": gc.trailing_trigger_pct,
                        "rebalance_pct": gc.trailing_rebalance_pct,
                        "shift_count": (
                            bot.grid_engine.trailing_shift_count
                            if bot.grid_engine
                            else 0
                        ),
                    }

            payload = {
                "status": bot.status.value,
                "current_price": current_price,
                "total_equity": total_equity,
                "grid_config": grid_config,
                "grid_levels": [
                    {
                        "index": l.index,
                        "price": l.price,
                        "side": l.side,
                        "status": l.status,
                    }
                    for l in (engine.levels if engine else [])
                ],
                "position": (
                    {
                        "base_balance": round(position.state.base_balance, 8),
                        "quote_balance": round(position.state.quote_balance, 2),
                        "avg_entry_price": round(position.state.avg_entry_price, 2),
                        "realized_pnl": round(position.state.realized_pnl, 2),
                        "unrealized_pnl": round(position.state.unrealized_pnl, 2),
                        "total_fees": round(position.state.total_fees, 2),
                        "trade_count": position.state.trade_count,
                    }
                    if position
                    else None
                ),
                "open_order_count": (
                    bot.order_manager.open_order_count if bot.order_manager else 0
                ),
                "risk_halted": (
                    bot.risk_manager.is_halted if bot.risk_manager else False
                ),
                "trailing": trailing_info,
                "timestamp": int(time.time() * 1000),
            }
            await websocket.send_text(json.dumps(payload))
            await asyncio.sleep(2.0)

    except WebSocketDisconnect:
        pass
    except Exception:
        pass
