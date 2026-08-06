# Strategy Development

A strategy returns a pandas `Series` of signals aligned to the OHLCV index:
- `+1` long entry
- `0`  flat / exit long
- `-1` short (only if `allow_short`/`use_short` set; engine supports it but backtest default long-only)

## Minimal example

```python
from app.strategy.base import BaseStrategy, StrategyMeta
from app.strategy.indicators import ema, rsi

class EmaRsi(BaseStrategy):
    meta = StrategyMeta(name="ema_rsi", timeframe="15m", warmup=200)
    params = {"fast": 21, "slow": 50, "rsi_low": 30}

    def generate_signals(self, df):
        fast, slow = ema(df["close"], self.params["fast"]), ema(df["close"], self.params["slow"])
        r = rsi(df["close"], 14)
        sig = (fast > slow) & (r < self.params["rsi_low"])   # combine conditions = AND
        return sig.astype(int)                                # True -> 1 entry
```

Register: add to `REGISTRY` in `app/strategy/registry.py`.

## Built-in
- `ema_cross` — fast/slow EMA crossover
- `rsi_reversal` — RSI oversold/overbought mean reversion
- `supertrend` — Supertrend direction-flip trend following

Indicators (`app/strategy/indicators.py`): `ema, rsi, atr, supertrend, macd, bollinger, vwap`. Vectorized pandas, no TA-Lib dep.

## Costs

Backtest (`app/backtest/engine.py`) models `taker_fee`/`maker_fee` + `slippage_bps` (config) on entry and exit, plus per-8h funding, leverage, and isolated-margin liquidation — so strategy metrics are realistic, not optimistic. The same slippage + fees are applied to paper/live PnL estimates and surfaced on the UI (risk panel + signal `reason` = `entry | cost X INR` + trade `fees` column). When tuning a strategy, expect live results to track the backtest net of these costs.

`BacktestConfig` levers (see `scripts/rank.py` `cfg_for(kind)` for the right
preset per strategy kind):
- `maker_on_limit` — limit entries pay maker (halves entry cost). Trend/reversion
  configs set this true.
- `regime_sma` — block new longs while `close < SMA(N)` (open positions still
  exit via trailing). Symmetric with `allow_short`: longs above SMA(N), shorts
  below. The gate **lags on lower TFs** — a choppy downtrend crosses SMA(N) on
  rallies and re-arms longs; it only goes flat on daily. See `docs/strategies_report.md` §18.4.
- `allow_short` — sig `-1` opens a short when flat; direction-aware manage/
  liquidation/funding. For long/short trend strategies use a **persistent-direction**
  signal (+1 uptrend / -1 downtrend) so the engine re-arms after a stop-out
  (`supertrend` does this when `use_short=True`).
- `funding_rates` — optional `pd.Series` of signed per-8h funding rates (index =
  8h mark UTC). If given, the engine asof-looks-up the rate at each 8h event
  instead of the flat `funding_rate` — models real dynamic/signed funding (pull
  via `scripts/pull_funding.py`, cached `reports/binance_BTCUSDT_funding.csv`).

**Perp futures carry no 1% TDS** (CoinDCX INR-margin, verified via support —
Section 194S covers VDA *transfer*; cash-settled futures are not a transfer). So
the perp backtest cost model (fee + slippage + funding, no TDS) is correct. The
1% TDS drag is **spot-only** — spot strategies (`scripts/grid_bot.py`) model it.

**Engine exit contract:** `engine.py` exits via ATR trailing (trend) or fixed
stop + `strategy.take_profit` (reversion), **NOT on signal 0** — signal-0 exit
lives in `faithful.py` + the live engine. Always use `cfg_for(kind)`, not the
default `BacktestConfig` (which gives a degenerate 1-trade trend result). See
`docs/strategies_report.md` §18.2.