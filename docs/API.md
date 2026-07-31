# REST API

Base: `http://localhost:8000/api` · OpenAPI: `http://localhost:8000/docs`

## Market data / backtest

| Method | Path | Body | Returns |
|--------|------|------|---------|
| GET | `/health` | — | `{"status":"ok"}` |
| GET | `/strategies` | — | list of strategies + default params + timeframe |
| POST | `/data/download` | `{"timeframe","days"}` | rows inserted |
| POST | `/backtest` | `{"strategy","params","timeframe","days","initial_capital","leverage"}` | metrics + report path |
| POST | `/optimize` | `{"strategy","grid","timeframe","days","score_key","walk_forward","n_splits"}` | best params / WF results |

## History / state

| Method | Path | Returns |
|--------|------|---------|
| GET | `/trades?limit=` | recent trades (incl. `fees`, `pnl`, `exit_reason`, `source`) |
| GET | `/signals?limit=` | recent signals; `reason` carries round-trip cost for entries, e.g. `entry \| cost 10.0 INR` |
| GET | `/positions` | live mode → exchange positions; paper/test → engine's simulated position |
| GET | `/balance` | live → exchange wallets (all currencies); paper → engine equity |
| GET | `/engine` | `{running, auto, strategy, kill, paper, has_position}` |

## Quote (for the manual-trade UI)

| Method | Path | Returns |
|--------|------|---------|
| GET | `/quote` | `{symbol, margin_currency, price, fx, equity, taker_fee, maker_fee, slippage_bps, min_quantity, quantity_increment, min_notional, price_increment}` |

`price` = BTC spot last (proxy for perp mark); `fx` = USDT/INR (INR-margined accounts); cost knobs let the UI compute round-trip fee + slippage without hardcoding.

## Trading / control (LIVE = real money)

| Method | Path | Body | Returns |
|--------|------|------|---------|
| POST | `/trade` | `{"action":"buy\|sell\|close","leverage","take_profit","stop_loss","margin","qty"}` | `{action, qty, price, fx, stop, leverage, take_profit, fee_inr, slippage_inr, cost_inr}` |
| POST | `/mode` | `{"mode":"test\|paper\|live","confirm"}` | mode + paper flag; live requires `confirm:true` |
| POST | `/kill` | `{"on":true\|false}` | `{kill, equity}` |
| POST | `/auto` | `{"on":true\|false}` | auto-trade on/off (signal-driven open/close) |
| POST | `/strategy` | `{"name"}` | swap active strategy |

### `/trade` semantics
- `action=buy` opens long, `sell` opens short, `close` exits the current position.
- `qty` (BTC) overrides `margin`; else `qty = margin * leverage / (price * fx)` (INR margin → USDT notional via FX).
- `take_profit` / `stop_loss` are optional but **validated pre-flight**: long needs `TP > price`, `SL < price`; short reversed. Wrong side → `409` (no exchange call, no kill switch).
- Response carries the estimated round-trip cost: `fee_inr` (taker both sides), `slippage_inr` (slippage_bps both sides), `cost_inr` (sum).
- 4xx exchange validation (e.g. a reject that slipped past pre-flight) surfaces as `409 "order rejected by exchange: ..."` — **does not** arm the kill switch. Only repeated transient (5xx/network) failures arm the kill.

## Examples

```bash
# backtest EMA cross on 180d of 15m candles
curl -X localhost:8000/api/backtest -d '{"strategy":"ema_cross","days":180,"leverage":3}' -H 'Content-Type: application/json'

# walk-forward optimize
curl -X localhost:8000/api/optimize -d '{"strategy":"ema_cross","grid":{"fast":[5,10,20],"slow":[40,50,100]},"walk_forward":true}' -H 'Content-Type: application/json'

# manual buy 0.001 BTC, lev 10, SL 62000, TP 66000
curl -X localhost:8000/api/trade -d '{"action":"buy","qty":0.001,"leverage":10,"stop_loss":62000,"take_profit":66000}' -H 'Content-Type: application/json'

# flip to live (REAL money — confirm required)
curl -X localhost:8000/api/mode -d '{"mode":"live","confirm":true}' -H 'Content-Type: application/json'
```