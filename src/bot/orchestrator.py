from __future__ import annotations

import asyncio
from enum import Enum

import aiohttp
import structlog

from ..config.schema import BotConfig, GridConfig
from ..config.settings import Settings
from ..db.database import Database
from ..db.migrations import run_migrations
from ..db.repositories import (
    GridConfigRepository,
    GridLevelRepository,
    OrderRepository,
    PositionSnapshotRepository,
    TradeRepository,
)
from ..exchange.connector import CoinbaseConnector
from ..exchange.paper_connector import PaperConnector
from ..orders.manager import OrderManager
from ..position.tracker import PositionTracker
from ..risk.manager import RiskManager
from ..strategy.grid_engine import GridEngine

logger = structlog.get_logger()


class BotStatus(str, Enum):
    IDLE = "idle"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    ERROR = "error"


class BotOrchestrator:
    POLL_INTERVAL = 5.0
    SNAPSHOT_INTERVAL = 60.0

    def __init__(self, config: BotConfig, settings: Settings):
        self._config = config
        self._settings = settings
        self._status = BotStatus.IDLE
        self._db: Database | None = None
        self._exchange: CoinbaseConnector | PaperConnector | None = None
        self._grid_engine: GridEngine | None = None
        self._order_mgr: OrderManager | None = None
        self._position: PositionTracker | None = None
        self._risk_mgr: RiskManager | None = None
        self._shutdown_event = asyncio.Event()
        self._main_task: asyncio.Task | None = None
        self._last_live_price: float = 0.0

    async def start(self) -> None:
        self._status = BotStatus.STARTING
        self._shutdown_event.clear()
        logger.info("bot_starting")

        # Database
        self._db = Database(self._settings.db_path)
        await self._db.connect()
        await run_migrations(self._db.conn)

        # Repositories
        order_repo = OrderRepository(self._db.conn)
        trade_repo = TradeRepository(self._db.conn)
        config_repo = GridConfigRepository(self._db.conn)
        level_repo = GridLevelRepository(self._db.conn)
        snapshot_repo = PositionSnapshotRepository(self._db.conn)

        # Exchange
        if self._config.paper_trading.enabled:
            self._exchange = PaperConnector(self._config.paper_trading)
        else:
            self._exchange = CoinbaseConnector(
                api_key=self._settings.coinbase_api_key,
                api_secret=self._settings.coinbase_api_secret,
                sandbox=self._config.exchange.sandbox,
            )
        await self._exchange.connect()

        # Order manager
        self._order_mgr = OrderManager(self._exchange, order_repo, level_repo)
        await self._order_mgr.reconcile_with_exchange(self._config.grid.symbol)

        # Position tracker
        initial_quote = (
            self._config.paper_trading.initial_balance_usd
            if self._config.paper_trading.enabled
            else 0.0
        )
        self._position = PositionTracker(
            self._config.grid.symbol,
            self._exchange,
            trade_repo,
            snapshot_repo,
            initial_quote=initial_quote,
        )

        # Risk manager
        self._risk_mgr = RiskManager(
            self._config.risk, self._position, self._order_mgr
        )

        # Grid engine
        self._grid_engine = GridEngine(
            self._config.grid,
            self._config.risk,
            self._exchange,
            self._order_mgr,
            self._risk_mgr,
        )

        # For paper trading, fetch real BTC price and auto-center the grid
        if isinstance(self._exchange, PaperConnector):
            live_price = await self._fetch_live_price()
            if live_price:
                self._last_live_price = live_price
                # Auto-center the grid around the real price
                grid_range = (
                    self._config.grid.upper_price - self._config.grid.lower_price
                )
                self._config.grid.lower_price = round(live_price - grid_range / 2, 2)
                self._config.grid.upper_price = round(live_price + grid_range / 2, 2)
                self._exchange.simulate_price(live_price)
                logger.info(
                    "live_price_init",
                    price=live_price,
                    grid_lower=self._config.grid.lower_price,
                    grid_upper=self._config.grid.upper_price,
                )
            else:
                mid_price = (
                    self._config.grid.lower_price + self._config.grid.upper_price
                ) / 2
                self._last_live_price = mid_price
                self._exchange.simulate_price(mid_price)
                logger.warning("live_price_unavailable_using_config")

        await self._grid_engine.initialize_grid()

        # Save config
        await config_repo.save(self._config.grid.model_dump())

        self._status = BotStatus.RUNNING
        logger.info("bot_running")
        self._main_task = asyncio.create_task(self._run_loop())

    async def _run_loop(self) -> None:
        snapshot_timer = 0.0
        is_paper = isinstance(self._exchange, PaperConnector)
        tick = 0
        try:
            while not self._shutdown_event.is_set():
                # Get current price
                if is_paper:
                    live_price = await self._fetch_live_price()
                    if live_price:
                        self._last_live_price = live_price
                    current_price = self._last_live_price
                    self._exchange.simulate_price(current_price)
                    # Process any fills that happened from the price move
                    for filled in self._exchange._last_fills:
                        self._position.record_fill(
                            filled.side, filled.amount, filled.avg_fill_price, filled.fee
                        )
                else:
                    ticker = await self._exchange.get_ticker(self._config.grid.symbol)
                    current_price = ticker.last

                # Risk checks (skip stop-loss/take-profit when trailing — the grid follows the trend)
                if not self._config.grid.trailing_enabled:
                    if self._risk_mgr.check_stop_loss(
                        current_price, self._config.grid.lower_price
                    ):
                        await self._emergency_shutdown("stop_loss")
                        return

                    if self._risk_mgr.check_take_profit(
                        current_price, self._config.grid.upper_price
                    ):
                        await self._emergency_shutdown("take_profit")
                        return

                # Check fills
                fill_count = await self._grid_engine.check_and_process_fills()
                if fill_count > 0:
                    await self._position.update_unrealized_pnl()
                    logger.info(
                        "fills_processed",
                        count=fill_count,
                        price=round(current_price, 2),
                    )

                # Trailing grid — shift the range if price approaches an edge
                if self._config.grid.trailing_enabled:
                    shifted = await self._grid_engine.check_trailing(current_price)
                    if shifted:
                        logger.info(
                            "grid_trailing_rebalanced",
                            new_lower=self._config.grid.lower_price,
                            new_upper=self._config.grid.upper_price,
                            shifts=self._grid_engine.trailing_shift_count,
                        )

                # Drawdown check
                total_equity = (
                    self._position.state.quote_balance
                    + self._position.state.base_balance * current_price
                )
                if self._risk_mgr.check_drawdown(total_equity):
                    await self._emergency_shutdown("drawdown_limit")
                    return

                # Periodic snapshot (every 15s in paper mode for faster chart updates)
                snap_interval = 15.0 if is_paper else self.SNAPSHOT_INTERVAL
                snapshot_timer += self.POLL_INTERVAL
                if snapshot_timer >= snap_interval:
                    await self._position.save_snapshot()
                    snapshot_timer = 0.0

                await asyncio.sleep(self.POLL_INTERVAL)

        except asyncio.CancelledError:
            logger.info("bot_loop_cancelled")
        except Exception as e:
            self._status = BotStatus.ERROR
            logger.exception("bot_loop_error", error=str(e))

    async def _fetch_live_price(self) -> float | None:
        """Fetch real-time price from Coinbase public API for the configured symbol."""
        try:
            # Convert "SOL/USD" -> "SOL-USD" for Coinbase API
            pair = self._config.grid.symbol.replace("/", "-")
            url = f"https://api.coinbase.com/v2/prices/{pair}/spot"
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url, timeout=aiohttp.ClientTimeout(total=5),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        price = float(data["data"]["amount"])
                        return price
        except Exception as e:
            logger.debug("live_price_fetch_failed", error=str(e))
        return None

    async def stop(self) -> None:
        self._status = BotStatus.STOPPING
        self._shutdown_event.set()

        if self._main_task:
            self._main_task.cancel()
            try:
                await self._main_task
            except asyncio.CancelledError:
                pass

        if self._grid_engine:
            cancelled = await self._grid_engine.cancel_all_grid_orders()
            logger.info("orders_cancelled_on_shutdown", count=cancelled)

        if self._position:
            await self._position.save_snapshot()

        if self._exchange:
            await self._exchange.close()
        if self._db:
            await self._db.close()

        self._status = BotStatus.STOPPED
        logger.info("bot_stopped")

    async def _emergency_shutdown(self, reason: str) -> None:
        logger.critical("emergency_shutdown", reason=reason)
        if self._grid_engine:
            await self._grid_engine.cancel_all_grid_orders()
        self._status = BotStatus.ERROR

    async def reconfigure(self, new_grid_config: GridConfig) -> None:
        if self._grid_engine:
            await self._grid_engine.cancel_all_grid_orders()
        self._config.grid = new_grid_config
        self._grid_engine = GridEngine(
            self._config.grid,
            self._config.risk,
            self._exchange,
            self._order_mgr,
            self._risk_mgr,
        )
        await self._grid_engine.initialize_grid()
        logger.info("bot_reconfigured")

    @property
    def status(self) -> BotStatus:
        return self._status

    @property
    def grid_engine(self) -> GridEngine | None:
        return self._grid_engine

    @property
    def position_tracker(self) -> PositionTracker | None:
        return self._position

    @property
    def risk_manager(self) -> RiskManager | None:
        return self._risk_mgr

    @property
    def order_manager(self) -> OrderManager | None:
        return self._order_mgr

    @property
    def database(self) -> Database | None:
        return self._db
