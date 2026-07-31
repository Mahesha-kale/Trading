"""EMA Crossover. fast EMA crosses above slow EMA -> long; below -> exit."""
from __future__ import annotations

import pandas as pd

from app.strategy.base import BaseStrategy, StrategyMeta
from app.strategy.indicators import ema


class EmaCross(BaseStrategy):
    meta = StrategyMeta(name="ema_cross", timeframe="15m", warmup=200)
    params = {"fast": 21, "slow": 50, "use_short": False}

    def validate(self) -> None:
        if self.params["fast"] >= self.params["slow"]:
            raise ValueError("fast EMA must be < slow EMA")

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        fast = ema(df["close"], self.params["fast"])
        slow = ema(df["close"], self.params["slow"])
        sig = pd.Series(0, index=df.index, dtype=int)
        long_cond = (fast > slow) & (fast.shift(1) <= slow.shift(1))
        exit_cond = (fast < slow) & (fast.shift(1) >= slow.shift(1))
        sig[long_cond] = 1
        if self.params["use_short"]:
            sig[exit_cond] = -1
        else:
            sig[exit_cond] = 0
        sig.iloc[: self.params["slow"]] = 0
        return sig