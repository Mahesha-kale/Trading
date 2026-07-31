# CoinDCX BTC/USDT Perpetual Futures Trading Platform

Automated trading platform: live, paper, backtest, optimize, risk-managed. CoinDCX futures, BTC/USDT perp.

## Quick start

```bash
cp .env.example .env          # fill COINDCX_API_KEY/SECRET, set TRADING_MODE=paper
python -m venv .venv && . .venv/Scripts/activate   # Windows
pip install -e ".[dev]"

# DB + infra (Postgres, Redis, nginx)
docker compose up -d postgres redis

# Download history
trader download 365 15m

# Backtest
trader backtest ema_cross 180

# API server (dashboard backend)
trader serve                  # http://localhost:8000/api/health
```

Frontend: real React + TypeScript + Tailwind app in `frontend/`. Dev: `cd frontend && npm install && npm run dev` (proxies `/api` to :8000). Tabs: Dashboard (equity via TradingView Lightweight Charts, PnL area via Recharts), Positions, Trades, Signals, Strategies, Backtest, Optimize. Polls `/api/*` every 5s. Prod: served by nginx in docker-compose.

Manual trading + control bar (top of every tab): AUTO ON/OFF (signal-driven trading), strategy dropdown, manual BUY/SELL/CLOSE with leverage, INR margin (or explicit qty), TP, SL. **Min** button autofills the minimum tradeable margin at the chosen leverage; **Show Risk** displays notional, margin, fee, slippage, round-trip cost, risk@SL, and liq distance. Costs (taker fees + `slippage_bps`) are modeled in backtest, paper, and live PnL, and shown on the UI for every trade — manual (risk panel + alert) and automatic (signal `reason` = `entry | cost X INR`).

## Architecture

```
            +-----------------+     +-----------------+
            |  CoinDCX REST   |     |  CoinDCX WS     |
            +--------+--------+     +--------+--------+
                     |                       |  candles/fills
                     v                       v
        +------------+-----------------------+-----------+
        |                TradingEngine (live/paper)      |
        |  signal -> RiskManager -> idempotent orders     |
        +----+--------------+-------------+---------------+
             |              |             |
       +-----v----+   +------v------+  +---v--------+
       |Backtest  |   | Optimizer    |  |  FastAPI   |
       |engine    |   | grid/WF      |  |  REST API  |
       +----+-----+   +-------------+  +---+--------+
            \                              |  /api/*
             \                            v
        +-----+-----------------------------------+
        | PostgreSQL (candles,trades,signals,results)
        +-----------------------------------------+
```

Signal flow: WS candle -> buffer -> strategy.generate_signals() -> RiskManager.can_open() + position_size() -> create_order(idempotent client_order_id) -> persist Order/Signal -> notify. Manual trades route through the same `_open`/`_close` with pre-flight TP/SL + qty validation.

INR margin: this account margines BTC/USDT perps in INR; contracts quote in USDT, PnL settles in INR. `position_size()` takes `fx_rate` (USDT/INR from the public ticker); `qty = margin*leverage/(price*fx)`. Backtest is single-currency (fx=1); live/paper use the live FX.

## Modules

| Path | Role |
|------|------|
| `app/exchange/coindcx.py` | REST client, HMAC auth, endpoint map, order builder |
| `app/exchange/ws.py` | WS feed, auto-reconnect, resubscribe |
| `app/data/downloader.py` | OHLCV fetch + upsert into DB |
| `app/strategy/` | BaseStrategy + indicators + 3 examples + registry |
| `app/risk/manager.py` | sizing, daily loss, drawdown, kill switch, liq price |
| `app/backtest/engine.py` | event loop, fees/slippage/funding/leverage/liq |
| `app/backtest/metrics.py` | sharpe/sortino/PF/DD/expectancy |
| `app/backtest/optimize.py` | grid + walk-forward |
| `app/live/engine.py` | paper/live execution, idempotency, reconcile |
| `app/api/routes.py` | REST endpoints |
| `app/notify/telegram.py` | trade alerts |

## Strategy dev

Subclass `BaseStrategy`, implement `generate_signals(df) -> Series` of +1/0/-1, register in `registry.py`. See `docs/STRATEGY.md`.

## Migrations

Dev uses `init_db()` (`create_all`) for zero-friction bootstrap. Prod / schema
changes use Alembic:

```bash
alembic upgrade head      # fresh DB: creates all tables
alembic stamp 0001        # existing create_all DB: mark baseline without rerunning
alembic revision -m "add X" --autogenerate   # new schema change
alembic upgrade head      # apply
```

## Safety

- Idempotent orders: `client_order_id` = uuid4 hex, reused on retry; exchange dedups. `_persist_order` upserts by `client_order_id` (unique) — never double-inserts.
- Crash recovery: `reconcile()` restores open position from exchange on startup.
- Kill switch arms only on **repeated transient** order failure (5xx/network) or max daily loss / drawdown. 4xx validation rejects (bad TP/SL/qty) fast-fail as `409` — no retry, no kill.
- Pre-flight validation: qty vs `min_quantity`/`min_notional`, and TP/SL side (long: `TP>price`, `SL<price`; short reversed) checked before any exchange call.
- Slippage + fees modeled in backtest, paper, and live PnL so results are realistic, not optimistic.
- Credentials from env only, never committed (`.env` gitignored; see `.gitignore`).
- API bound to `127.0.0.1` (no auth) by default — do not expose publicly without adding auth.

## Status / what's MVP

Done & tested: exchange client, data, 3 strategies, risk, backtest, metrics, optimize, live+paper engine, REST API, Docker, core tests, manual trading UI (auto on/off, strategy switch, buy/sell/close + TP/SL/leverage/margin/qty), INR-margined FX-aware sizing + PnL, slippage + fees modeling + UI display, kill-switch hardening (4xx fast-fail, TP/SL pre-flight).

Deferred (not built, add when needed): MACD/VWAP/Bollinger/Breakout/ATR-trend strategy classes, Discord/email/desktop notifiers, PDF reports, Alembic migrations, stress tests, sequence/architecture diagrams beyond this README. Details: `docs/TROUBLESHOOTING.md`.