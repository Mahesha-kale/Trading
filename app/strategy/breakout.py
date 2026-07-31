"""Donchian breakout. Close > N-bar high (excl. current) -> long; < N-bar low -> exit."""
from __future__ import annotations

import pandas as pd

from app.strategy.base import BaseStrategy, StrategyMeta


class Breakout(BaseStrategy):
    meta = StrategyMeta(name="breakout", timeframe="15m", warmup=200)
    params = {"lookback": 20, "use_short": False}

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        n = self.params["lookback"]
        hh = df["high"].rolling(n).max().shift(1)
        ll = df["low"].rolling(n).min().shift(1)
        sig = pd.Series(0, index=df.index, dtype=int)
        pos = 0
        for i in range(len(df)):
            if pd.isna(hh.iloc[i]):
                continue
            c = df["close"].iloc[i]
            if pos == 0 and c > hh.iloc[i]:
                sig.iloc[i] = 1
                pos = 1
            elif pos == 1 and c < ll.iloc[i]:
                sig.iloc[i] = -1 if self.params["use_short"] else 0
                pos = 0
        return sig