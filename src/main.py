from __future__ import annotations

import asyncio
import os

import click
import structlog
import uvicorn

from .config.settings import Settings, load_config, load_futures_config
from .bot.orchestrator import BotOrchestrator
from .bot.futures_orchestrator import FuturesBotOrchestrator
from .utils.logging import setup_logging

_log = structlog.get_logger()


@click.group()
def cli():
    """Coinbase Grid Trading Bot"""
    pass


@cli.command()
@click.option("--config", default="config/default.yaml", help="Config file path")
@click.option("--futures-config", default="", help="Kraken futures config file path (optional)")
@click.option("--dashboard/--no-dashboard", default=True, help="Run web dashboard")
def run(config: str, futures_config: str, dashboard: bool) -> None:
    """Start the grid trading bot (optionally with Kraken futures bot alongside)."""
    settings = Settings(config_path=config)
    bot_config = load_config(settings)
    setup_logging()

    bot = BotOrchestrator(bot_config, settings)

    futures_bot: FuturesBotOrchestrator | None = None
    if futures_config:
        futures_cfg = load_futures_config(futures_config)
        futures_bot = None  # created after spot bot starts (to share intelligence)

    async def _main() -> None:
        nonlocal futures_bot
        await bot.start()

        # Create futures bot after spot bot is running so we can share intelligence
        if futures_config:
            try:
                futures_cfg = load_futures_config(futures_config)
                futures_bot = FuturesBotOrchestrator(
                    config=futures_cfg,
                    settings=settings,
                    shared_trend_filter=bot.trend_filter,
                    shared_lunarcrush=bot.lunarcrush,
                )
                await futures_bot.start()
            except Exception as exc:
                _log.error("futures_bot_start_failed", error=str(exc))
                futures_bot = None

        if dashboard:
            from .dashboard.app import create_dashboard_app

            app = create_dashboard_app(bot, futures_bot=futures_bot)
            port = int(os.environ.get("PORT", bot_config.dashboard.port))
            uv_config = uvicorn.Config(
                app,
                host=bot_config.dashboard.host,
                port=port,
                log_level="info",
            )
            server = uvicorn.Server(uv_config)
            try:
                await server.serve()
            finally:
                await bot.stop()
                if futures_bot:
                    await futures_bot.stop()
        else:
            try:
                while bot.status.value == "running":
                    await asyncio.sleep(1)
            except (KeyboardInterrupt, asyncio.CancelledError):
                pass
            finally:
                await bot.stop()
                if futures_bot:
                    await futures_bot.stop()

    asyncio.run(_main())


@cli.command()
@click.option("--config", default="config/default.yaml", help="Config file path")
@click.option("--data", required=True, help="Path to OHLCV CSV file")
@click.option("--initial-balance", default=10000.0, help="Starting USD balance")
def backtest(config: str, data: str, initial_balance: float) -> None:
    """Run a backtest on historical data."""
    settings = Settings(config_path=config)
    bot_config = load_config(settings)
    setup_logging()

    from .backtest.data_loader import DataLoader
    from .backtest.engine import BacktestEngine

    df = DataLoader.from_csv(data)
    engine = BacktestEngine(
        grid_config=bot_config.grids[0],
        fee_pct=bot_config.paper_trading.simulated_fee_pct,
        slippage_bps=bot_config.backtest.slippage_bps,
        initial_quote=initial_balance,
    )
    report = engine.run(df)
    summary = report.summary()

    click.echo("\n=== Backtest Results ===")
    for k, v in summary.items():
        click.echo(f"  {k}: {v}")
    click.echo()


if __name__ == "__main__":
    cli()
