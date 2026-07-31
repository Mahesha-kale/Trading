# Troubleshooting

| Symptom | Cause / Fix |
|---------|-------------|
| `no data in DB` on backtest | run `/api/data/download` or `trader download` first |
| orders rejected `timestamp >10s` | clock drift; host must sync NTP. Client stamps on send. |
| `leverage mismatch` reject | order leverage must equal position leverage; engine sets both from config. |
| tests: `ModuleNotFoundError structlog` | `pip install structlog` (or `pip install -e ".[dev]"`) |
| WS reconnects constantly | check network; backoff caps at 30s. Re-subscribes on reconnect. |
| paper mode no fills | engine needs `warmup` bars; ensure WS feeding 1m candles for ~warmup before signal. |
| liquidation price seems off | `liquidation_price()` is simplified isolated + flat maint margin; exchange uses tiered. Use as warning only. (`# ponytail:` marker in code) |
| `KILL ENGAGED` after a manual trade | Bad TP/SL side (e.g. long with `take_profit` below price). Pre-flight now rejects it as `409` before any exchange call, so the kill no longer arms. If it still shows, release it: `POST /api/kill {"on":false}` or the dashboard button. |
| kill arms on `http 422` | Deterministic exchange validation reject (bad TP/SL/qty). 4xx errors now fast-fail (`409 "order rejected by exchange: …"`) — no retry, no kill. Only transient 5xx/network retried → kill. |
| position open on exchange but engine `has_position:false` (orphan) | Was a double-insert of the same `client_order_id` (unique constraint) raising on the `"filled"` write → 3 retries → kill, `self.pos` never set. Fixed: `_persist_order` upserts by `client_order_id`. Flatten any orphan via `POST /api/trade {"action":"close"}` or a direct reduce-only market order. |
| orders invisible in UI (paper) | `GET /api/positions` returns the engine's simulated position in paper/test; the Trades table needs a closed trade row (`_persist_trade` on close). Fees column now populated from the trade `fees` field. |
| slippage / fees not reflected | Backtest models `slippage_bps` + maker/taker fees in PnL. Live/paper close now applies exit slippage + entry+exit fees to the estimated PnL (live realized truth still comes from the exchange wallet via `_refresh_equity`). UI shows `fee≈ · slip≈ · round-trip cost` in the risk panel; signals carry `cost X INR` in `reason`. |
| INR/USDT mismatch in sizing | INR-margined account, contract quoted in USDT. `position_size()` takes `fx_rate` (USDT/INR); `manual_trade` derives `qty = margin*lev/(price*fx)`. PnL settled in INR via FX at close. |

## What's NOT in MVP (add when needed)
- Strategies: MACD, VWAP, Bollinger, Breakout, ATR-trend (indicators exist; wrap a class)
- Discord / email / desktop notifiers (Telegram done; same httpx pattern)
- PDF reports (HTML done; use a headless renderer if PDF needed)
- Alembic migrations (create_all used)
- Stress tests, integration/API tests
- Sequence diagrams (README has architecture ASCII)