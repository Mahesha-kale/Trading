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
        # long/short: emit the current supertrend direction as a persistent state
        # signal (+1 uptrend, -1 downtrend). The engine opens long/short only when
        # flat, and the trailing stop exits -- so a state signal re-arms the entry
        # on the bar after a stop-out. (The prior use_short path set pos=-1 and
        # never returned to 0, so it emitted once and never re-entered long.)
        if self.params["use_short"]:
            return direction.fillna(0).astype(int)
        # long-only: pulse +1 at the flip into an uptrend; engine exits via trailing.
        sig = pd.Series(0, index=df.index, dtype=int)
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
                sig.iloc[i] = 0
                pos = 0
        return sig