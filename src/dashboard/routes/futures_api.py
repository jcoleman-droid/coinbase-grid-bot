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
            "unrealized_pnl": 0.0,
            "entry_price": 0.0,
        }

    # Fetch live positions to get P&L per pair
    total_unrealized_pnl = 0.0
    open_position_count = 0
    account_balance = 0.0
    try:
        if bot._exchange:
            positions = await bot._exchange.get_positions()
            for pos in positions:
                raw_sym = pos.get("symbol", "")
                # Normalize "SOL/USD:USD" -> "SOL/USD"
                norm = raw_sym.split(":")[0] if ":" in raw_sym else raw_sym
                upnl = pos.get("unrealized_pnl", 0.0)
                total_unrealized_pnl += upnl
                if pos.get("size", 0) > 0:
                    open_position_count += 1
                if norm in pairs:
                    pairs[norm]["unrealized_pnl"] = round(upnl, 4)
                    pairs[norm]["entry_price"] = pos.get("entry_price", 0.0)

            balance = await bot._exchange.get_balance()
            account_balance = (
                balance.total.get("USD", 0.0)
                or balance.total.get("USDT", 0.0)
                or 0.0
            )
    except Exception:
        pass

    return {
        "enabled": True,
        "status": bot.status.value,
        "symbols": bot.symbols,
        "margin_utilization": round(bot.margin_utilization, 4),
        "account_balance": round(account_balance, 2),
        "total_unrealized_pnl": round(total_unrealized_pnl, 4),
        "open_position_count": open_position_count,
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
