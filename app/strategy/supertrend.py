"""Supertrend trend-following. Direction flip -> enter; flip back -> exit."""
from __future__ import annotations

import pandas as pd

from app.strategy.base import BaseStrategy, StrategyMeta
from app.strategy.indicators import supertrend


class SupertrendStrategy(BaseStrategy):
    meta = StrategyMeta(name="supertrend", timeframe="15m", warmup=300)
    params = {"period": 10, "multiplier": 3.0, "use_short": False}

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        _, direction = supertrend(df["high"], df["low"], df["close"],
                                  self.params["period"], self.params["multiplier"])
        sig = pd.Series(0, index=df.index, dtype=int)
        # state-hold: once in trend, stay until flip
        pos = 0
        for i in range(len(df)):
            d = direction.iloc[i]
            if pd.isna(d):
                continue
            d = int(d)
            if d == 1 and pos == 0:
                sig.iloc[i] = 1
                pos = 1
            elif d == -1 and pos == 1:
                if self.params["use_short"]:
                    sig.iloc[i] = -1
                else:
                    sig.iloc[i] = 0
                pos = 0 if not self.params["use_short"] else -1
        return sig