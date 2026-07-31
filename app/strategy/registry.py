"""Strategy registry. Add new strategy: subclass BaseStrategy + register."""
from __future__ import annotations

from app.strategy.atr_trend import AtrTrend
from app.strategy.base import BaseStrategy
from app.strategy.bollinger import BollingerReversion
from app.strategy.breakout import Breakout
from app.strategy.ema_cross import EmaCross
from app.strategy.macd import MacdCross
from app.strategy.rsi_reversal import RsiReversal
from app.strategy.supertrend import SupertrendStrategy
from app.strategy.vwap import VwapReclaim

REGISTRY: dict[str, type[BaseStrategy]] = {
    EmaCross.meta.name: EmaCross,
    RsiReversal.meta.name: RsiReversal,
    SupertrendStrategy.meta.name: SupertrendStrategy,
    MacdCross.meta.name: MacdCross,
    VwapReclaim.meta.name: VwapReclaim,
    BollingerReversion.meta.name: BollingerReversion,
    Breakout.meta.name: Breakout,
    AtrTrend.meta.name: AtrTrend,
}


def get_strategy(name: str, params: dict | None = None) -> BaseStrategy:
    if name not in REGISTRY:
        raise KeyError(f"unknown strategy '{name}'. known: {list(REGISTRY)}")
    return REGISTRY[name](params)