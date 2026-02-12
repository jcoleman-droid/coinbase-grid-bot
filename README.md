# Coinbase Grid Trading Bot

A grid trading bot for Coinbase with a trailing grid strategy, real-time web dashboard, paper trading simulation, and backtesting engine.

## What is Grid Trading?

Grid trading places buy and sell orders at preset price intervals (a "grid") around a base price. When a buy order fills, a sell order is placed one level above. When a sell order fills, a buy order is placed one level below. Profit comes from capturing the spread as price oscillates within the grid range.

**Trailing grid** extends this by automatically shifting the entire grid when price trends toward an edge, so the bot follows the trend instead of getting stuck with one-sided orders.

## Features

- **Grid Strategy** - Arithmetic or geometric spacing across configurable price levels
- **Trailing Grid** - Auto-shifts the grid range to follow price trends with configurable trigger, rebalance percentage, and cooldown
- **Paper Trading** - Simulated exchange connector with price random walk for risk-free testing
- **Web Dashboard** - Real-time trading terminal with WebSocket updates, equity chart, grid visualization, and bot controls
- **Backtesting** - Test strategies against historical OHLCV data with slippage simulation
- **Risk Management** - Stop-loss, take-profit, max drawdown circuit breaker, and position limits
- **SQLite Persistence** - Async database with WAL mode for orders, trades, and equity snapshots
- **Coinbase Integration** - Production exchange connector via ccxt with rate limiting and retry logic

## Quick Start

### Prerequisites

- Python 3.12+

### Installation

```bash
git clone https://github.com/jcoleman-droid/coinbase-grid-bot.git
cd coinbase-grid-bot
pip install -e ".[dev]"
```

### Run in Paper Trading Mode

No API keys needed - the bot simulates trades locally:

```bash
python -m src.main run --dashboard
```

Open **http://127.0.0.1:8080** to view the dashboard.

### Run with Coinbase (Live)

1. Copy the environment file and add your API keys:

```bash
cp .env.example .env
```

2. Edit `.env` with your Coinbase API credentials:

```
GRIDBOT_COINBASE_API_KEY=your_api_key
GRIDBOT_COINBASE_API_SECRET=your_api_secret
```

3. Disable paper trading in `config/default.yaml`:

```yaml
paper_trading:
  enabled: false
```

4. Run the bot:

```bash
python -m src.main run --dashboard
```

## Configuration

All settings are in `config/default.yaml`:

```yaml
grid:
  symbol: "BTC/USD"
  lower_price: 55000.0
  upper_price: 65000.0
  num_levels: 20
  spacing: arithmetic           # arithmetic or geometric
  order_size_usd: 100.0
  trailing_enabled: true
  trailing_trigger_pct: 75.0    # shift when price reaches 75% toward an edge
  trailing_rebalance_pct: 50.0  # shift the grid by 50% of its range
  trailing_cooldown_secs: 30.0  # minimum seconds between shifts

risk:
  max_position_usd: 5000.0
  max_open_orders: 40
  stop_loss_pct: 5.0
  take_profit_pct: 3.0
  max_drawdown_pct: 10.0
```

### Trailing Grid Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `trailing_enabled` | `true` | Enable/disable trailing |
| `trailing_trigger_pct` | `75.0` | Shift when price reaches this % toward grid edge (50-95) |
| `trailing_rebalance_pct` | `50.0` | Shift the grid by this % of its range (10-100) |
| `trailing_cooldown_secs` | `30.0` | Minimum seconds between shifts to prevent churning |

## Project Structure

```
coinbase-grid-bot/
  config/default.yaml          # Bot configuration
  src/
    main.py                    # CLI entry point
    bot/orchestrator.py        # Main bot loop and coordination
    config/                    # Pydantic config schema and settings loader
    db/                        # SQLite database, migrations, repositories
    exchange/                  # Exchange connectors (Coinbase + paper trading)
    strategy/                  # Grid math and grid engine
    orders/                    # Order lifecycle management
    position/                  # Position tracking and P&L
    risk/                      # Risk management (stop-loss, drawdown, etc.)
    backtest/                  # Backtesting engine and reports
    dashboard/                 # FastAPI web dashboard with WebSocket
      static/                  # HTML, CSS, JS for trading terminal UI
  tests/                       # 22 tests covering all modules
```

## Tests

```bash
pytest tests/ -v
```

## Disclaimer

This software is for educational purposes only. Cryptocurrency trading involves substantial risk of loss. Use at your own risk. Always test with paper trading before risking real funds.
