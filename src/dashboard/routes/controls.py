from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter()


class ReconfigureRequest(BaseModel):
    symbol: str
    lower_price: float | None = None
    upper_price: float | None = None
    num_levels: int | None = None
    order_size_usd: float | None = None
    trailing_enabled: bool | None = None
    trailing_trigger_pct: float | None = None
    trailing_rebalance_pct: float | None = None


@router.post("/start")
async def start_bot(request: Request):
    bot = request.app.state.bot
    if bot.status.value == "running":
        raise HTTPException(400, "Bot is already running")
    await bot.start()
    return {"status": "started"}


@router.post("/stop")
async def stop_bot(request: Request):
    bot = request.app.state.bot
    if bot.status.value not in ("running", "error"):
        raise HTTPException(400, "Bot is not running")
    await bot.stop()
    return {"status": "stopped"}


@router.post("/reconfigure")
async def reconfigure_bot(request: Request, body: ReconfigureRequest):
    bot = request.app.state.bot
    if bot.status.value != "running":
        raise HTTPException(400, "Bot must be running to reconfigure")

    # Find the matching grid config by symbol
    current = None
    for gc in bot._config.grids:
        if gc.symbol == body.symbol:
            current = gc
            break
    if not current:
        raise HTTPException(404, f"Symbol {body.symbol} not found in config")

    updates = {k: v for k, v in body.model_dump().items() if v is not None and k != "symbol"}
    new_config = current.model_copy(update=updates)
    await bot.reconfigure(new_config)
    return {"status": "reconfigured", "symbol": body.symbol, "new_config": new_config.model_dump()}


@router.post("/reset-halt")
async def reset_halt(request: Request):
    bot = request.app.state.bot
    if bot.risk_manager:
        bot.risk_manager.reset_halt()
    return {"status": "halt_reset"}
