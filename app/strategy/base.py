"""Strategy framework. Subclass BaseStrategy, implement generate_signals().

A "signal" is +1 (long entry), -1 (short/exit), 0 (flat). The engine interprets
the transition flat->long as open long, long->flat as close. Combining conditions
is just AND in pandas — strategies express that in their signal logic.

Config is a plain dict, validated in validate() per strategy (optional).
"""
from __future__ import annotations

from typing import Any

import pandas as pd


class StrategyMeta:
    def __init__(self, name: str, timeframe: str = "15m", warmup: int = 200):
        self.name = name
        self.timeframe = timeframe
        self.warmup = warmup


class BaseStrategy:
    """Override params + generate_signals. Stateless w.r.t. positions."""

    meta: StrategyMeta = StrategyMeta(name="base")
    params: dict[str, Any] = {}  # subclasses set defaults here

    def __init__(self, params: dict[str, Any] | None = None):
        merged = dict(type(self).params)
        if params:
            merged.update(params)
        self.params = merged
        self.validate()

    def validate(self) -> None:
        """Override for strict validation. Default: no-op."""

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        """Return int Series: +1 long, -1 short, 0 flat. Index = df.index."""
        raise NotImplementedError

    def stop_loss(self, df: pd.DataFrame, entry_idx) -> float | None:
        return None

    def take_profit(self, df: pd.DataFrame, entry_idx) -> float | None:
        return None

    @property
    def warmup(self) -> int:
        return self.meta.warmup