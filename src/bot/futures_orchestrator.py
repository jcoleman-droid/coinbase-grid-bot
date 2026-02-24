from __future__ import annotations

import asyncio

import aiohttp
import structlog

from ..bot.orchestrator import BotStatus
from ..config.schema import FuturesBotConfig
from ..config.settings import Settings
from ..db.database import Database
from ..db.migrations import run_migrations
from ..db.repositories import GridLevelRepository, OrderRepository, TradeRepository
from ..exchange.kraken_futures_connector import KrakenFuturesConnector
from ..intelligence.lunarcrush import LunarCrushProvider
from ..orders.manager import OrderManager
from ..strategy.futures_grid_engine import FuturesGridEngine
from ..strategy.trend_filter import TrendDirection, TrendFilter

logger = structlog.get_logger()


class FuturesBotOrchestrator:
    """
    Runs directional futures grids on Kraken.
    Shares TrendFilter and LunarCrush with the spot BotOrchestrator.

    Direction logic:
      TrendDirection.UP   → long grid
      TrendDirection.DOWN → short grid
      TrendDirection.NEUTRAL → keep existing direction (or long if fresh start)
    """

    POLL_INTERVAL = 5.0

    def __init__(
        self,
        config: FuturesBotConfig,
        settings: Settings,
        shared_trend_filter: TrendFilter | None = None,
        shared_lunarcrush: LunarCrushProvider | None = None,
    ):
        self._config = config
        self._settings = settings
        self._status = BotStatus.IDLE
        self._trend_filter = shared_trend_filter
        self._lunarcrush = shared_lunarcrush

        self._db: Database | None = None
        self._exchange: KrakenFuturesConnector | None = None
        self._order_mgr: OrderManager | None = None
        self._futures_engines: dict[str, FuturesGridEngine] = {}
        self._last_live_prices: dict[str, float] = {}
        self._shutdown_event = asyncio.Event()
        self._main_task: asyncio.Task | None = None

        # Own TrendFilter if not shared
        if self._trend_filter is None:
            self._trend_filter = TrendFilter(
                short_window=self._config.direction_filter.short_window,
                long_window=self._config.direction_filter.long_window,
            )

    @property
    def symbols(self) -> list[str]:
        return [g.symbol for g in self._config.grids]

    @property
    def status(self) -> BotStatus:
        return self._status

    @property
    def futures_engines(self) -> dict[str, FuturesGridEngine]:
        return dict(self._futures_engines)

    @property
    def last_live_prices(self) -> dict[str, float]:
        return dict(self._last_live_prices)

    @property
    def margin_utilization(self) -> float:
        """Rough estimate: sum of open position notional / total collateral."""
        if not self._exchange:
            return 0.0
        # Will be populated from balance checks in the run loop
        return self._margin_utilization

    async def start(self) -> None:
        self._status = BotStatus.STARTING
        self._shutdown_event.clear()
        self._margin_utilization = 0.0

        logger.info("futures_bot_starting", pairs=len(self._config.grids))

        # Database — share with spot bot via the same path
        self._db = Database(self._settings.db_path)
        await self._db.connect()
        await run_migrations(self._db.conn)

        order_repo = OrderRepository(self._db.conn)
        level_repo = GridLevelRepository(self._db.conn)

        # Exchange
        self._exchange = KrakenFuturesConnector(
            api_key=self._settings.kraken_futures_api_key,
            api_secret=self._settings.kraken_futures_api_secret,
            sandbox=self._config.exchange.sandbox,
        )
        try:
            await self._exchange.connect()

            # Set leverage for each pair
            for grid_cfg in self._config.grids:
                await self._exchange.set_leverage(grid_cfg.symbol, self._config.exchange.leverage)

            # Order manager
            self._order_mgr = OrderManager(self._exchange, order_repo, level_repo)
            for grid_cfg in self._config.grids:
                await self._order_mgr.reconcile_with_exchange(grid_cfg.symbol)

            # Fetch live prices
            await self._refresh_prices()

            # Create one FuturesGridEngine per pair and deploy initial direction
            for grid_cfg in self._config.grids:
                engine = FuturesGridEngine(
                    config=grid_cfg,
                    risk_config=self._config.risk,
                    exchange=self._exchange,
                    order_manager=self._order_mgr,
                )
                initial_direction = self._decide_direction(grid_cfg.symbol, grid_cfg.direction)
                await engine.initialize_grid(initial_direction)
                self._futures_engines[grid_cfg.symbol] = engine
        except Exception:
            await self._exchange.close()
            self._exchange = None
            raise

        self._status = BotStatus.RUNNING
        logger.info("futures_bot_running", pairs=len(self._futures_engines))
        self._main_task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        self._status = BotStatus.STOPPING
        self._shutdown_event.set()

        if self._main_task:
            self._main_task.cancel()
            try:
                await self._main_task
            except asyncio.CancelledError:
                pass

        for sym, engine in self._futures_engines.items():
            await engine.cancel_all_grid_orders()
            logger.info("futures_orders_cancelled_on_shutdown", symbol=sym)

        if self._exchange:
            await self._exchange.close()
        if self._db:
            await self._db.close()

        self._status = BotStatus.STOPPED
        logger.info("futures_bot_stopped")

    async def _run_loop(self) -> None:
        equity_peak = 0.0
        try:
            while not self._shutdown_event.is_set():
                await self._refresh_prices()

                # Feed prices into trend filter
                for sym, price in self._last_live_prices.items():
                    if price > 0:
                        self._trend_filter.record_price(sym, price)

                # Update margin utilization
                await self._update_margin()

                # Margin safety check — pause all grids if margin too high
                if self._margin_utilization > self._config.risk.margin_utilization_limit:
                    logger.warning(
                        "margin_limit_exceeded",
                        utilization=round(self._margin_utilization, 3),
                    )
                    for engine in self._futures_engines.values():
                        await engine.cancel_all_grid_orders()
                    await asyncio.sleep(self.POLL_INTERVAL)
                    continue

                # Per-pair logic
                for grid_cfg in self._config.grids:
                    sym = grid_cfg.symbol
                    engine = self._futures_engines.get(sym)
                    if not engine:
                        continue

                    # Determine desired direction from trend
                    desired = self._decide_direction(sym, grid_cfg.direction)

                    # Switch direction if needed and cooldown elapsed
                    if desired != engine.direction and engine.can_switch:
                        await engine.switch_direction(desired)

                    # Process fills
                    fill_count = await engine.check_and_process_fills()
                    if fill_count > 0:
                        logger.info(
                            "futures_fills_processed",
                            symbol=sym,
                            count=fill_count,
                            direction=engine.direction,
                        )

                # Global drawdown check via unrealized PnL from positions
                positions = await self._exchange.get_positions()
                total_pnl = sum(p.get("unrealized_pnl", 0.0) for p in positions)
                if equity_peak == 0.0 or total_pnl > equity_peak:
                    equity_peak = max(total_pnl, 0.0)
                if equity_peak > 0:
                    drawdown = (equity_peak - total_pnl) / equity_peak * 100
                    if drawdown >= self._config.risk.max_drawdown_pct:
                        logger.critical(
                            "futures_drawdown_limit",
                            drawdown=round(drawdown, 2),
                        )
                        for engine in self._futures_engines.values():
                            await engine.cancel_all_grid_orders()
                        self._status = BotStatus.ERROR
                        return

                await asyncio.sleep(self.POLL_INTERVAL)

        except asyncio.CancelledError:
            logger.info("futures_loop_cancelled")
        except Exception as e:
            self._status = BotStatus.ERROR
            logger.exception("futures_loop_error", error=str(e))

    def _decide_direction(self, symbol: str, config_direction: str) -> str:
        """Resolve the grid direction for a symbol."""
        if config_direction in ("long", "short"):
            return config_direction
        # auto: use trend filter
        trend = self._trend_filter.get_trend(symbol)
        if trend == TrendDirection.UP:
            return "long"
        elif trend == TrendDirection.DOWN:
            return "short"
        # NEUTRAL: keep current direction if engine exists, else default long
        engine = self._futures_engines.get(symbol)
        return engine.direction if engine else "long"

    async def _refresh_prices(self) -> None:
        try:
            async with aiohttp.ClientSession() as session:
                tasks = []
                for sym in self.symbols:
                    pair = sym.replace("/", "-")
                    url = f"https://api.coinbase.com/v2/prices/{pair}/spot"
                    tasks.append(self._fetch_one_price(session, sym, url))
                results = await asyncio.gather(*tasks, return_exceptions=True)
                for result in results:
                    if isinstance(result, tuple):
                        sym, price = result
                        self._last_live_prices[sym] = price
        except Exception as e:
            logger.debug("futures_price_fetch_failed", error=str(e))

    @staticmethod
    async def _fetch_one_price(
        session: aiohttp.ClientSession, symbol: str, url: str
    ) -> tuple[str, float]:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
            if resp.status == 200:
                data = await resp.json()
                return (symbol, float(data["data"]["amount"]))
        raise ValueError(f"Failed to fetch price for {symbol}")

    async def _update_margin(self) -> None:
        try:
            balance = await self._exchange.get_balance()
            total_collateral = balance.total.get("USD", 0.0) or balance.total.get("USDT", 0.0)
            if total_collateral <= 0:
                self._margin_utilization = 0.0
                return
            positions = await self._exchange.get_positions()
            used_margin = sum(p.get("margin", 0.0) for p in positions)
            self._margin_utilization = used_margin / total_collateral
        except Exception as e:
            logger.debug("margin_update_failed", error=str(e))
