"""RSI Reversal (mean reversion). RSI < oversold -> long; RSI > overbought -> exit."""
from __future__ import annotations

import pandas as pd

from app.strategy.base import BaseStrategy, StrategyMeta
from app.strategy.indicators import rsi


class RsiReversal(BaseStrategy):
    meta = StrategyMeta(name="rsi_reversal", timeframe="15m", warmup=200)
    params = {"period": 14, "oversold": 30, "overbought": 70}

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        r = rsi(df["close"], self.params["period"])
        sig = pd.Series(0, index=df.index, dtype=int)
        sig[(r < self.params["oversold"]) & (r.shift(1) >= self.params["oversold"])] = 1
        sig[(r > self.params["overbought"]) & (r.shift(1) <= self.params["overbought"])] = 0
        return sig