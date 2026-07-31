# Run Steps

End-to-end from empty clone to running platform.

## 1. Prereqs
- Python 3.12+, Docker, Node 20+, CoinDCX API key (futures enabled)

## 2. Configure
```bash
cp .env.example .env
# edit .env: COINDCX_API_KEY, COINDCX_API_SECRET, TRADING_MODE=paper
```
`paper` = safe start (no real orders). `live` = real money.

## 3. Backend
```bash
python -m venv .venv
. .venv/Scripts/activate          # Windows (bash: source .venv/Scripts/activate)
pip install -e ".[dev]"

# start infra
docker compose up -d postgres redis

# download history (needed before backtest)
trader download 365 15m
```

## 4. Backtest (verify strategy)
```bash
trader backtest ema_cross 180
```
Prints metrics. HTML report at `reports/backtest.html`.

## 5. API server
```bash
trader serve
```
- REST: http://localhost:8000/api/health
- OpenAPI: http://localhost:8000/docs

## 6. Frontend
```bash
cd frontend
npm install
npm run dev
```
Dashboard at http://localhost:5173 (proxies `/api` to :8000).

## 6b. Trade manually (paper first)
The control bar (top of every tab) has: AUTO ON/OFF, strategy dropdown, and a manual form — side (buy/sell), leverage, INR margin (or qty BTC), TP, SL.
- **Min** autofills the minimum tradeable margin at the chosen leverage.
- **Show Risk** shows notional, margin, fee, slippage, round-trip cost, risk@SL, liq distance — slippage + fees are modeled in PnL, not hidden.
- TP/SL are validated pre-flight (long: `TP>price`, `SL<price`; short reversed). Wrong side → a `409` error, no exchange call, no kill switch.
- AUTO ON lets the strategy open/close on its signals; AUTO OFF = manual only. Either way, costs show in the signal (`entry | cost X INR`) and the trade's `fees`.

## 7. One-command prod (Docker)
```bash
docker compose up -d --build
```
- Frontend: http://localhost
- API: http://localhost/api/health
Tables auto-created on first boot (`init_db` create_all).

## 8. Verify
```bash
pytest                                # backend tests green
curl localhost:8000/api/health        # {"status":"ok"}
```

## 9. Go live (only after paper works)
- Set `TRADING_MODE=live` in `.env` (or Mode → live → Apply in the UI, which requires confirm)
- Start small: `DEFAULT_LEVERAGE=1`, `RISK_PER_TRADE=0.005`
- Watch logs; kill switch button on dashboard / `RiskManager.kill_switch()`. Kill arms only on repeated transient (5xx/network) failure or daily-loss/drawdown — a bad TP/SL now rejects as `409` without arming it.
- Re-verify CoinDCX endpoints against current docs before first real order (`# ponytail:` marker in `app/exchange/coindcx.py`)
- Never leave the live engine running unattended; rotate API keys periodically.