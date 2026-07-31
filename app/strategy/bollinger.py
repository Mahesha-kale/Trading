"""Bollinger mean-reversion. Close at/below lower band -> long; exit at mid."""
from __future__ import annotations

import pandas as pd

from app.strategy.base import BaseStrategy, StrategyMeta
from app.strategy.indicators import bollinger


class BollingerReversion(BaseStrategy):
    meta = StrategyMeta(name="bollinger_reversion", timeframe="15m", warmup=200)
    params = {"period": 20, "std_mult": 2.0, "use_short": False}

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        mid, _upper, lower = bollinger(df["close"], self.params["period"], self.params["std_mult"])
        sig = pd.Series(0, index=df.index, dtype=int)
        pos = 0
        for i in range(len(df)):
            if pd.isna(mid.iloc[i]):
                continue
            c = df["close"].iloc[i]
            if pos == 0 and c <= lower.iloc[i]:
                sig.iloc[i] = 1
                pos = 1
            elif pos == 1 and c >= mid.iloc[i]:
                sig.iloc[i] = -1 if self.params["use_short"] else 0
                pos = 0
        return sig