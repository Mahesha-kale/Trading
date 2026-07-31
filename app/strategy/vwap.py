"""VWAP reclaim. Close above session VWAP -> long; close back below -> exit."""
from __future__ import annotations

import pandas as pd

from app.strategy.base import BaseStrategy, StrategyMeta
from app.strategy.indicators import vwap


class VwapReclaim(BaseStrategy):
    meta = StrategyMeta(name="vwap_reclaim", timeframe="15m", warmup=50)
    params = {"use_short": False}

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        v = vwap(df)
        sig = pd.Series(0, index=df.index, dtype=int)
        above = df["close"] > v
        long_cond = above & (~above).shift(1, fill_value=False)
        exit_cond = (~above) & above.shift(1, fill_value=False)
        sig[long_cond] = 1
        sig[exit_cond] = -1 if self.params["use_short"] else 0
        return sig