"""Strategy registry. Add new strategy: subclass BaseStrategy + register."""
from __future__ import annotations

from app.strategy.atr_trend import AtrTrend
from app.strategy.base import BaseStrategy
from app.strategy.bollinger import BollingerReversion
from app.strategy.breakout import Breakout
from app.strategy.ema_cross import EmaCross
from app.strategy.macd import MacdCross
from app.strategy.orb_max import ORBMax
from app.strategy.rsi_reversal import RsiReversal
from app.strategy.batch import (AdxTrend, CciReversion, DonchianBreakout,
                                 EmaPullback, FairValueGap, IchimokuBreakout,
                                 KeltnerMeanReversion, LiquiditySweep,
                                 ObvDivergence, OpeningRangeBreakout, PsarTrend,
                                 StochrsiReversal, VwapPullback, RegimeGate)
from app.strategy.supertrend import SupertrendStrategy
from app.strategy.taker_ratio import TakerRatio
from app.strategy.vwap import VwapReclaim
from app.strategy.wyckoff import Wyckoff

REGISTRY: dict[str, type[BaseStrategy]] = {
    EmaCross.meta.name: EmaCross,
    RsiReversal.meta.name: RsiReversal,
    SupertrendStrategy.meta.name: SupertrendStrategy,
    MacdCross.meta.name: MacdCross,
    VwapReclaim.meta.name: VwapReclaim,
    BollingerReversion.meta.name: BollingerReversion,
    Breakout.meta.name: Breakout,
    AtrTrend.meta.name: AtrTrend,
    Wyckoff.meta.name: Wyckoff,
    LiquiditySweep.meta.name: LiquiditySweep,
    FairValueGap.meta.name: FairValueGap,
    OpeningRangeBreakout.meta.name: OpeningRangeBreakout,
    VwapPullback.meta.name: VwapPullback,
    KeltnerMeanReversion.meta.name: KeltnerMeanReversion,
    StochrsiReversal.meta.name: StochrsiReversal,
    CciReversion.meta.name: CciReversion,
    AdxTrend.meta.name: AdxTrend,
    DonchianBreakout.meta.name: DonchianBreakout,
    IchimokuBreakout.meta.name: IchimokuBreakout,
    PsarTrend.meta.name: PsarTrend,
    ObvDivergence.meta.name: ObvDivergence,
    EmaPullback.meta.name: EmaPullback,
    RegimeGate.meta.name: RegimeGate,
    TakerRatio.meta.name: TakerRatio,
    ORBMax.meta.name: ORBMax,
}


def get_strategy(name: str, params: dict | None = None) -> BaseStrategy:
    if name not in REGISTRY:
        raise KeyError(f"unknown strategy '{name}'. known: {list(REGISTRY)}")
    return REGISTRY[name](params)