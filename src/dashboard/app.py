from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from ..bot.orchestrator import BotOrchestrator
from .routes import api, controls, ws
from .routes import futures_api


def create_dashboard_app(bot: BotOrchestrator, futures_bot=None) -> FastAPI:
    app = FastAPI(title="Grid Trading Bot", version="0.1.0")

    app.state.bot = bot
    app.state.futures_bot = futures_bot  # None if not running

    app.include_router(api.router, prefix="/api", tags=["data"])
    app.include_router(ws.router, prefix="/ws", tags=["websocket"])
    app.include_router(controls.router, prefix="/api/bot", tags=["controls"])
    app.include_router(futures_api.router, prefix="/api/futures", tags=["futures"])

    static_dir = Path(__file__).parent / "static"
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    @app.get("/")
    async def serve_dashboard():
        return FileResponse(str(static_dir / "index.html"))

    return app
