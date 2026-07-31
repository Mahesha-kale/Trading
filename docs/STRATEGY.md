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