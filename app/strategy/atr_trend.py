"""ATR trailing-stop trend follow. Enter on momentum thrust; exit when close
crosses the rising trailing stop (long-side only)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from app.strategy.base import BaseStrategy, StrategyMeta
from app.strategy.indicators import atr


class AtrTrend(BaseStrategy):
    meta = StrategyMeta(name="atr_trend", timeframe="15m", warmup=200)
    params = {"period": 14, "multiplier": 3.0, "use_short": False}

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        a = atr(df["high"], df["low"], df["close"], self.params["period"])
        mult = self.params["multiplier"]
        sig = pd.Series(0, index=df.index, dtype=int)
        pos = 0
        trail = np.nan
        for i in range(len(df)):
            if pd.isna(a.iloc[i]):
                continue
            c = df["close"].iloc[i]
            if pos == 0:
                if i > 0 and c > df["close"].iloc[i - 1] + mult * a.iloc[i]:
                    sig.iloc[i] = 1
                    pos = 1
                    trail = c - mult * a.iloc[i]
            else:
                trail = max(trail, c - mult * a.iloc[i])
                if c < trail:
                    sig.iloc[i] = -1 if self.params["use_short"] else 0
                    pos = 0
                    trail = np.nan
        return sig