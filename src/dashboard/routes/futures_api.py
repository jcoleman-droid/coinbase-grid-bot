from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter()


def _get_futures_bot(request: Request):
    return getattr(request.app.state, "futures_bot", None)


@router.get("/status")
async def futures_status(request: Request):
    bot = _get_futures_bot(request)
    if not bot:
        return {"enabled": False}

    prices = bot.last_live_prices
    engines = bot.futures_engines

    pairs = {}
    for sym, engine in engines.items():
        pairs[sym] = {
            "direction": engine.direction,
            "can_switch": engine.can_switch,
            "open_position_size": engine.open_position_size,
            "current_price": prices.get(sym, 0.0),
            "levels_placed": sum(1 for l in engine.levels if l.status == "order_placed"),
        }

    return {
        "enabled": True,
        "status": bot.status.value,
        "symbols": bot.symbols,
        "margin_utilization": round(bot.margin_utilization, 4),
        "pairs": pairs,
    }


@router.get("/positions")
async def futures_positions(request: Request):
    bot = _get_futures_bot(request)
    if not bot or not bot._exchange:
        return {"positions": []}
    try:
        positions = await bot._exchange.get_positions()
        return {"positions": positions}
    except Exception as e:
        return {"positions": [], "error": str(e)}


@router.get("/grid")
async def futures_grid(request: Request, symbol: str | None = None):
    bot = _get_futures_bot(request)
    if not bot:
        return {"levels": {}}

    engines = bot.futures_engines

    if symbol:
        engine = engines.get(symbol)
        if not engine:
            return {"levels": []}
        return {
            "direction": engine.direction,
            "levels": [
                {
                    "index": l.index,
                    "price": l.price,
                    "side": l.side,
                    "reduce_only": l.reduce_only,
                    "status": l.status,
                }
                for l in engine.levels
            ],
        }

    result = {}
    for sym, engine in engines.items():
        result[sym] = {
            "direction": engine.direction,
            "levels": [
                {
                    "index": l.index,
                    "price": l.price,
                    "side": l.side,
                    "reduce_only": l.reduce_only,
                    "status": l.status,
                }
                for l in engine.levels
            ],
        }
    return {"levels": result}
