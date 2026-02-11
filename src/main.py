from __future__ import annotations

import asyncio

import click
import uvicorn

from .config.settings import Settings, load_config
from .bot.orchestrator import BotOrchestrator
from .utils.logging import setup_logging


@click.group()
def cli():
    """Coinbase Grid Trading Bot"""
    pass


@cli.command()
@click.option("--config", default="config/default.yaml", help="Config file path")
@click.option("--dashboard/--no-dashboard", default=True, help="Run web dashboard")
def run(config: str, dashboard: bool) -> None:
    """Start the grid trading bot."""
    settings = Settings(config_path=config)
    bot_config = load_config(settings)
    setup_logging()

    bot = BotOrchestrator(bot_config, settings)

    async def _main() -> None:
        await bot.start()

        if dashboard:
            from .dashboard.app import create_dashboard_app

            app = create_dashboard_app(bot)
            uv_config = uvicorn.Config(
                app,
                host=bot_config.dashboard.host,
                port=bot_config.dashboard.port,
                log_level="info",
            )
            server = uvicorn.Server(uv_config)
            try:
                await server.serve()
            finally:
                await bot.stop()
        else:
            try:
                while bot.status.value == "running":
                    await asyncio.sleep(1)
            except (KeyboardInterrupt, asyncio.CancelledError):
                pass
            finally:
                await bot.stop()

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
        grid_config=bot_config.grid,
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
