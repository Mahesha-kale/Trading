"""Taker-buy-ratio order-flow signal.

Binance perp klines carry `taker_buy_base` (volume from buyer-TAKER trades) and
`volume` (total). taker_buy_ratio = taker_buy_base/volume in [0,1]; 0.5 = balanced
order flow, >0.5 = buy-pressure, <0.5 = sell-pressure. This is a bar-level order-
flow imbalance proxy -- a structurally different info source from price-derived
indicators (the one class not yet walk-forwarded).

Signal: persistent direction with deadband hysteresis. Smooth the ratio, then
    state = +1 while smoothed > 0.5+edge   (buy pressure -> long)
    state = -1 while smoothed < 0.5-edge   (sell pressure -> short)
    hold prior state in the deadband (skip noise flips near 0.5).
use_short=False -> long-only (sell-pressure state = flat, sit out).
Persistent direction so the engine re-arms entry after a trailing stop-out
(the backtest-engine-exit-contract). Trend kind: ride the ATR trailer.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from app.strategy.base import BaseStrategy, StrategyMeta


class TakerRatio(BaseStrategy):
    meta = StrategyMeta(name="taker_ratio", timeframe="15m", warmup=200)
    params = {"smooth": 20, "edge": 0.0, "use_short": False}

    def validate(self) -> None:
        if self.params["smooth"] < 1:
            raise ValueError("smooth must be >= 1")
        if not 0.0 <= self.params["edge"] < 0.5:
            raise ValueError("edge must be in [0, 0.5)")

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        if "taker_buy_base" not in df.columns or "volume" not in df.columns:
            # No order-flow cols -> flat (lets this strategy no-op on old data).
            return pd.Series(0, index=df.index, dtype=int)
        vol = df["volume"].to_numpy()
        tbb = df["taker_buy_base"].to_numpy()
        # 0-volume bars -> neutral 0.5 (no order-flow info), not 0/inf.
        # np.divide with where avoids the div-by-0 warning np.where would emit
        # (np.where evaluates both branches, computing tbb/vol even where vol==0).
        ratio = np.divide(tbb, vol, out=np.full(tbb.shape, 0.5, float), where=vol > 0)
        s = pd.Series(ratio, index=df.index)
        smooth = int(self.params["smooth"])
        sm = s.rolling(smooth, min_periods=smooth).mean()
        edge = float(self.params["edge"])
        up = sm > (0.5 + edge)
        dn = sm < (0.5 - edge)
        # Persistent state with hysteresis: stamp +1/-1 on cross, ffill, start flat.
        state = pd.Series(np.nan, index=df.index)
        state[up] = 1
        state[dn] = -1
        state = state.ffill().fillna(0).astype(int)
        if self.params["use_short"]:
            sig = state.copy()                       # +1 long, -1 short
        else:
            sig = state.where(state > 0, 0)          # long-only: sell state = flat
        sig.iloc[:smooth] = 0                        # warmup
        return sig.astype(int)


def _demo() -> None:  # ponytail: one runnable self-check for the deadband logic.
    n = 300
    idx = pd.date_range("2024-01-01", periods=n, freq="15min", tz="UTC")
    # 0..99 buy (0.7), 100..199 deadband (0.5, inside 0.45-0.55), 200..299 sell (0.3).
    tbb = np.r_[np.full(100, 0.7), np.full(100, 0.5), np.full(100, 0.3)] * 100.0
    df = pd.DataFrame({"open": 1, "high": 1, "low": 1, "close": 1,
                       "volume": 100.0, "taker_buy_base": tbb}, index=idx)
    s = TakerRatio({"smooth": 10, "edge": 0.05, "use_short": True}).generate_signals(df)
    assert s.iloc[:10].eq(0).all(), "warmup must be flat"
    assert s.iloc[30:90].eq(1).all(), "buy-pressure regime must hold +1"
    # deadband (smoothed 0.5, inside 0.45-0.55) holds prior +1, does not go flat/flip.
    assert s.iloc[120:190].eq(1).all(), "deadband must hold prior state (+1)"
    assert s.iloc[230:290].eq(-1).all(), "sell-pressure regime must hold -1"
    # long-only: sell regime -> flat (0), not short.
    sl = TakerRatio({"smooth": 10, "edge": 0.05, "use_short": False}).generate_signals(df)
    assert sl.iloc[230:290].eq(0).all(), "long-only must be flat in sell regime"
    # missing order-flow cols -> flat (no-op on old data).
    s3 = TakerRatio({}).generate_signals(df.drop(columns=["taker_buy_base", "volume"]))
    assert s3.eq(0).all(), "missing cols must yield flat"
    print("taker_ratio self-check OK")


if __name__ == "__main__":
    _demo()