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
from ..position.tracker import MultiPairPositionTracker
from ..risk.manager import RiskManager
from ..risk.position_stop_loss import PositionStopLoss
from ..strategy.dip_sniper import DipSniper
from ..strategy.grid_engine import GridEngine, smart_price_round
from ..strategy.momentum_rider import MomentumRider
from ..strategy.pair_rotator import PairRotator
from ..strategy.trend_filter import TrendFilter

logger = structlog.get_logger()


class BotStatus(str, Enum):
    IDLE = "idle"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    ERROR = "error"


class BotOrchestrator:
    POLL_INTERVAL = 3.0
    SNAPSHOT_INTERVAL = 60.0

    def __init__(self, config: BotConfig, settings: Settings):
        self._config = config
        self._settings = settings
        self._status = BotStatus.IDLE
        self._db: Database | None = None
        self._exchange: CoinbaseConnector | PaperConnector | None = None
        self._grid_engines: dict[str, GridEngine] = {}
        self._order_mgr: OrderManager | None = None
        self._position: MultiPairPositionTracker | None = None
        self._risk_mgr: RiskManager | None = None
        self._trend_filter: TrendFilter | None = None
        self._stop_loss: PositionStopLoss | None = None
        self._pair_rotator: PairRotator | None = None
        self._momentum_rider: MomentumRider | None = None
        self._momentum_position: MultiPairPositionTracker | None = None
        self._dip_sniper: DipSniper | None = None
        self._dip_position: MultiPairPositionTracker | None = None
        self._shutdown_event = asyncio.Event()
        self._main_task: asyncio.Task | None = None
        self._last_live_prices: dict[str, float] = {}

    @property
    def symbols(self) -> list[str]:
        return [g.symbol for g in self._config.grids]

    async def start(self) -> None:
        self._status = BotStatus.STARTING
        self._shutdown_event.clear()
        logger.info("bot_starting", pairs=len(self._config.grids))

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

        # Order manager (shared across all pairs)
        self._order_mgr = OrderManager(self._exchange, order_repo, level_repo)
        for grid_cfg in self._config.grids:
            await self._order_mgr.reconcile_with_exchange(grid_cfg.symbol)

        # Capital allocation across strategies
        symbols = self.symbols
        total_usd = (
            self._config.pool.initial_balance_usd
            if self._config.paper_trading.enabled
            else 0.0
        )
        alloc = self._config.strategy_allocation
        grid_capital = total_usd * alloc.grid_pct / 100
        momentum_capital = total_usd * alloc.momentum_pct / 100
        dip_capital = total_usd * alloc.dip_sniper_pct / 100
        logger.info(
            "capital_allocation",
            grid=grid_capital, momentum=momentum_capital, dip=dip_capital,
        )

        # Grid position tracker (primary)
        self._position = MultiPairPositionTracker(
            symbols, self._exchange, trade_repo, snapshot_repo,
            initial_usd=grid_capital,
        )

        # Momentum Rider tracker
        if self._config.momentum_rider.enabled:
            self._momentum_position = MultiPairPositionTracker(
                symbols, self._exchange, trade_repo, snapshot_repo,
                initial_usd=momentum_capital,
            )

        # Dip Sniper tracker
        if self._config.dip_sniper.enabled:
            self._dip_position = MultiPairPositionTracker(
                symbols, self._exchange, trade_repo, snapshot_repo,
                initial_usd=dip_capital,
            )

        # Defensive features
        if self._config.trend_filter.enabled:
            self._trend_filter = TrendFilter(
                short_window=self._config.trend_filter.short_window,
                long_window=self._config.trend_filter.long_window,
            )

        if self._config.position_stop_loss.enabled:
            self._stop_loss = PositionStopLoss(
                threshold_pct=self._config.position_stop_loss.threshold_pct,
                cooldown_secs=self._config.position_stop_loss.cooldown_secs,
            )

        if self._config.pair_rotation.enabled:
            self._pair_rotator = PairRotator(
                evaluation_interval_secs=self._config.pair_rotation.evaluation_interval_secs,
                pause_threshold=self._config.pair_rotation.pause_threshold,
                min_trades_before_eval=self._config.pair_rotation.min_trades_before_eval,
            )

        # Momentum Rider strategy
        if self._config.momentum_rider.enabled and self._trend_filter:
            self._momentum_rider = MomentumRider(
                config=self._config.momentum_rider,
                exchange=self._exchange,
                position_tracker=self._momentum_position,
                trend_filter=self._trend_filter,
            )
            logger.info("momentum_rider_initialized", capital=momentum_capital)

        # Dip Sniper strategy
        if self._config.dip_sniper.enabled:
            self._dip_sniper = DipSniper(
                config=self._config.dip_sniper,
                exchange=self._exchange,
                position_tracker=self._dip_position,
            )
            logger.info("dip_sniper_initialized", capital=dip_capital)

        # Risk manager (shared for grid strategy)
        self._risk_mgr = RiskManager(
            self._config.risk, self._position, self._order_mgr,
            trend_filter=self._trend_filter,
        )

        # Fetch live prices for all pairs and auto-center grids
        if isinstance(self._exchange, PaperConnector):
            live_prices = await self._fetch_live_prices()
            if live_prices:
                self._last_live_prices = live_prices
            for grid_cfg in self._config.grids:
                price = live_prices.get(grid_cfg.symbol)
                if price:
                    grid_range = grid_cfg.upper_price - grid_cfg.lower_price
                    new_lower = price - grid_range / 2
                    # Ensure lower price stays positive
                    if new_lower <= 0:
                        new_lower = price * 0.5
                        grid_range = price  # symmetric around price
                    grid_cfg.lower_price = smart_price_round(new_lower)
                    grid_cfg.upper_price = smart_price_round(new_lower + grid_range)
                    logger.info(
                        "live_price_init",
                        symbol=grid_cfg.symbol,
                        price=price,
                        grid_lower=grid_cfg.lower_price,
                        grid_upper=grid_cfg.upper_price,
                    )
                else:
                    mid = (grid_cfg.lower_price + grid_cfg.upper_price) / 2
                    self._last_live_prices[grid_cfg.symbol] = mid
                    logger.warning(
                        "live_price_unavailable_using_config",
                        symbol=grid_cfg.symbol,
                    )

            # Seed paper connector with all prices
            self._exchange.simulate_prices(self._last_live_prices)

        # Create one GridEngine per pair
        for grid_cfg in self._config.grids:
            engine = GridEngine(
                grid_cfg, self._config.risk,
                self._exchange, self._order_mgr, self._risk_mgr,
            )
            await engine.initialize_grid()
            self._grid_engines[grid_cfg.symbol] = engine
            logger.info("grid_initialized_pair", symbol=grid_cfg.symbol)

        # Save configs
        for grid_cfg in self._config.grids:
            await config_repo.save(grid_cfg.model_dump())

        self._status = BotStatus.RUNNING
        logger.info("bot_running", pairs=len(self._grid_engines))
        self._main_task = asyncio.create_task(self._run_loop())

    async def _run_loop(self) -> None:
        snapshot_timer = 0.0
        is_paper = isinstance(self._exchange, PaperConnector)
        try:
            while not self._shutdown_event.is_set():
                # ── Fetch prices ──
                if is_paper:
                    live_prices = await self._fetch_live_prices()
                    if live_prices:
                        self._last_live_prices.update(live_prices)
                    self._exchange.simulate_prices(self._last_live_prices)
                    # Record paper fills
                    for filled in self._exchange._last_fills:
                        self._position.record_fill(
                            filled.symbol,
                            filled.side,
                            filled.amount,
                            filled.avg_fill_price,
                            filled.fee,
                        )
                else:
                    for sym in self.symbols:
                        try:
                            ticker = await self._exchange.get_ticker(sym)
                            self._last_live_prices[sym] = ticker.last
                        except Exception as e:
                            logger.debug("ticker_failed", symbol=sym, error=str(e))

                # ── Record prices for trend filter ──
                if self._trend_filter:
                    for sym, price in self._last_live_prices.items():
                        if price > 0:
                            self._trend_filter.record_price(sym, price)

                # ── Per-pair logic ──
                for grid_cfg in self._config.grids:
                    sym = grid_cfg.symbol
                    engine = self._grid_engines.get(sym)
                    if not engine:
                        continue

                    current_price = self._last_live_prices.get(sym, 0.0)
                    if current_price <= 0:
                        continue

                    # Skip paused pairs (pair rotation)
                    if self._pair_rotator and self._pair_rotator.is_paused(sym):
                        continue

                    # Position stop-loss check
                    if self._stop_loss:
                        if self._stop_loss.is_in_cooldown(sym):
                            continue
                        if self._stop_loss.should_trigger(
                            sym, self._position, current_price
                        ):
                            await engine.cancel_all_grid_orders()
                            await self._stop_loss.execute_stop_loss(
                                sym, self._exchange, self._position
                            )
                            continue

                    # Risk checks (skip when trailing)
                    if not grid_cfg.trailing_enabled:
                        if self._risk_mgr.check_stop_loss(
                            sym, current_price, grid_cfg.lower_price
                        ):
                            logger.critical("stop_loss_pair", symbol=sym)
                            await engine.cancel_all_grid_orders()
                            continue
                        if self._risk_mgr.check_take_profit(
                            sym, current_price, grid_cfg.upper_price
                        ):
                            logger.info("take_profit_pair", symbol=sym)
                            await engine.cancel_all_grid_orders()
                            continue

                    # Check fills
                    fill_count = await engine.check_and_process_fills()
                    if fill_count > 0:
                        await self._position.update_unrealized_pnl(sym)
                        logger.info(
                            "fills_processed",
                            symbol=sym,
                            count=fill_count,
                            price=round(current_price, 2),
                        )

                    # Trailing grid
                    if grid_cfg.trailing_enabled:
                        shifted = await engine.check_trailing(current_price)
                        if shifted:
                            logger.info(
                                "grid_trailing_rebalanced",
                                symbol=sym,
                                new_lower=grid_cfg.lower_price,
                                new_upper=grid_cfg.upper_price,
                                shifts=engine.trailing_shift_count,
                            )

                # ── Momentum Rider ──
                if self._momentum_rider:
                    for grid_cfg in self._config.grids:
                        sym = grid_cfg.symbol
                        price = self._last_live_prices.get(sym, 0.0)
                        if price > 0:
                            await self._momentum_rider.evaluate(sym, price)

                # ── Dip Sniper ──
                if self._dip_sniper:
                    for grid_cfg in self._config.grids:
                        sym = grid_cfg.symbol
                        price = self._last_live_prices.get(sym, 0.0)
                        if price > 0:
                            await self._dip_sniper.evaluate(sym, price)

                # ── Pair rotation evaluation ──
                if self._pair_rotator and self._pair_rotator.should_evaluate():
                    scores = self._pair_rotator.evaluate_pairs(
                        self._position, self._trend_filter
                    )
                    to_pause = self._pair_rotator.get_pairs_to_pause(scores)
                    for sym in to_pause:
                        engine = self._grid_engines.get(sym)
                        if engine:
                            await engine.cancel_all_grid_orders()
                        await self._pair_rotator.sell_off_pair(
                            sym, self._exchange, self._position
                        )

                # ── Global checks ──
                total_equity = self._position.total_equity_usd if self._position else 0
                if self._momentum_position:
                    total_equity += self._momentum_position.total_equity_usd
                if self._dip_position:
                    total_equity += self._dip_position.total_equity_usd
                if self._risk_mgr.check_drawdown(total_equity):
                    await self._emergency_shutdown("drawdown_limit")
                    return

                # Periodic snapshot
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

    async def _fetch_live_prices(self) -> dict[str, float]:
        """Fetch real-time prices from Coinbase public API for all symbols."""
        prices: dict[str, float] = {}
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
                        prices[sym] = price
        except Exception as e:
            logger.debug("live_prices_fetch_failed", error=str(e))
        return prices

    @staticmethod
    async def _fetch_one_price(
        session: aiohttp.ClientSession, symbol: str, url: str
    ) -> tuple[str, float]:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
            if resp.status == 200:
                data = await resp.json()
                return (symbol, float(data["data"]["amount"]))
        raise ValueError(f"Failed to fetch price for {symbol}")

    async def stop(self) -> None:
        self._status = BotStatus.STOPPING
        self._shutdown_event.set()

        if self._main_task:
            self._main_task.cancel()
            try:
                await self._main_task
            except asyncio.CancelledError:
                pass

        for sym, engine in self._grid_engines.items():
            cancelled = await engine.cancel_all_grid_orders()
            logger.info("orders_cancelled_on_shutdown", symbol=sym, count=cancelled)

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
        for engine in self._grid_engines.values():
            await engine.cancel_all_grid_orders()
        self._status = BotStatus.ERROR

    async def reconfigure(self, new_grid_config: GridConfig) -> None:
        sym = new_grid_config.symbol
        engine = self._grid_engines.get(sym)
        if engine:
            await engine.cancel_all_grid_orders()
        # Update the matching config in the grids list
        for i, gc in enumerate(self._config.grids):
            if gc.symbol == sym:
                self._config.grids[i] = new_grid_config
                break
        new_engine = GridEngine(
            new_grid_config, self._config.risk,
            self._exchange, self._order_mgr, self._risk_mgr,
        )
        await new_engine.initialize_grid()
        self._grid_engines[sym] = new_engine
        logger.info("bot_reconfigured", symbol=sym)

    @property
    def status(self) -> BotStatus:
        return self._status

    @property
    def grid_engines(self) -> dict[str, GridEngine]:
        return dict(self._grid_engines)

    @property
    def grid_engine(self) -> GridEngine | None:
        """Backward compat — returns first engine or None."""
        if self._grid_engines:
            return next(iter(self._grid_engines.values()))
        return None

    @property
    def position_tracker(self) -> MultiPairPositionTracker | None:
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

    @property
    def trend_filter(self) -> TrendFilter | None:
        return self._trend_filter

    @property
    def stop_loss(self) -> PositionStopLoss | None:
        return self._stop_loss

    @property
    def pair_rotator(self) -> PairRotator | None:
        return self._pair_rotator

    @property
    def momentum_rider(self) -> MomentumRider | None:
        return self._momentum_rider

    @property
    def dip_sniper(self) -> DipSniper | None:
        return self._dip_sniper

    @property
    def momentum_position_tracker(self) -> MultiPairPositionTracker | None:
        return self._momentum_position

    @property
    def dip_position_tracker(self) -> MultiPairPositionTracker | None:
        return self._dip_position

    @property
    def last_live_prices(self) -> dict[str, float]:
        return dict(self._last_live_prices)
