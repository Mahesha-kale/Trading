"""MACD crossover. MACD line crosses above signal line -> long; below -> exit."""
from __future__ import annotations

import pandas as pd

from app.strategy.base import BaseStrategy, StrategyMeta
from app.strategy.indicators import macd


class MacdCross(BaseStrategy):
    meta = StrategyMeta(name="macd_cross", timeframe="15m", warmup=200)
    params = {"fast": 12, "slow": 26, "signal": 9, "use_short": False}

    def validate(self) -> None:
        if not self.params["fast"] < self.params["slow"]:
            raise ValueError("fast must be < slow")

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        macd_line, sig_line, _ = macd(df["close"], self.params["fast"],
                                     self.params["slow"], self.params["signal"])
        sig = pd.Series(0, index=df.index, dtype=int)
        long_cond = (macd_line > sig_line) & (macd_line.shift(1) <= sig_line.shift(1))
        exit_cond = (macd_line < sig_line) & (macd_line.shift(1) >= sig_line.shift(1))
        sig[long_cond] = 1
        sig[exit_cond] = -1 if self.params["use_short"] else 0
        sig.iloc[: self.params["slow"] + self.params["signal"]] = 0
        return sig