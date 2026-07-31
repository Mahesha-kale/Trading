# Installation

## Prereqs
- Python 3.12+ (tested run on 3.10 for core tests; 3.12 recommended for prod)
- Docker + Docker Compose
- CoinDCX API key + secret (futures enabled)

## Steps
1. `cp .env.example .env`, fill credentials. `TRADING_MODE=paper` to start safely.
2. `pip install -e ".[dev]"`
3. `docker compose up -d postgres redis`
4. `trader download 365 15m` — populate history.
5. `trader serve` — API on :8000. Tables auto-created via `init_db()` (create_all).
   For real prod migrations, use Alembic (not included in MVP).

## Verify
- `curl localhost:8000/api/health` -> `{"status":"ok"}`
- `pytest` -> core tests green.
- `trader backtest ema_cross 180` -> prints metrics.