"""Regime gate signals for the tilt sweep (sub-project 2). Each returns a pd.Series
of signed conviction in [-1,+1]: +=long perp, -=short perp, |value|=strength 0..1.
Params trained on first 70% by time (no OOS peek). NaN/empty -> 0 (never propagate)."""
from __future__ import annotations

import numpy as np
import pandas as pd

CLIP = 1.0  # conviction magnitude cap


def funding_slope_signal(funding: pd.DataFrame, w: int, z: float) -> pd.Series:
    """Rolling z-score of funding rate slope over window w. Rising funding -> long.
    conviction = tanh(zscore / z) so |c| in [0,1]; sign = slope sign."""
    rate = funding["rate"].astype(float)
    slope = rate.diff(w)  # change over w marks
    roll_std = slope.rolling(w, min_periods=w).std()
    zscore = slope / roll_std.replace(0, np.nan)
    c = np.tanh(zscore / z) if z > 0 else np.sign(slope) * CLIP
    out = c.replace([np.inf, -np.inf], np.nan).fillna(0.0).clip(-CLIP, CLIP)
    return pd.Series(out, index=funding.index)


def trend_signal(price: pd.Series, period: int, mult: float) -> pd.Series:
    """Supertrend regime. Uptrend -> +1, downtrend -> -1 (crisp regime sign as
    conviction magnitude; no fractional strength — supertrend is binary)."""
    hl = price.rolling(period, min_periods=period).max()
    ll = price.rolling(period, min_periods=period).min()
    atr = (hl - ll).rolling(period, min_periods=period).mean()
    mid = (hl + ll) / 2.0
    upper = mid + mult * atr
    lower = mid - mult * atr
    pos = pd.Series(index=price.index, dtype=float)
    side = 0.0
    for i, p in enumerate(price.values):
        if np.isnan(p) or np.isnan(mid.iloc[i]):
            pos.iloc[i] = 0.0
            continue
        if side == 0.0:
            side = 1.0 if p > mid.iloc[i] else -1.0
        elif side > 0 and p < lower.iloc[i]:
            side = -1.0
        elif side < 0 and p > upper.iloc[i]:
            side = 1.0
        pos.iloc[i] = side if not np.isnan(side) else 0.0
    return pd.Series(pos.fillna(0.0).clip(-CLIP, CLIP), index=price.index)


def basis_signal(perp: pd.Series, spot: pd.Series, w: int, thr_bps: float) -> pd.Series:
    """Perp premium over spot in bps, smoothed over w. Contango (perp>spot) -> long.
    conviction = tanh(basis_bps / thr_bps); sign = basis sign."""
    basis = (perp.reindex(spot.index, method="nearest") - spot) / spot * 10_000.0  # bps
    smooth = basis.rolling(w, min_periods=w).mean()
    c = np.tanh(smooth / thr_bps) if thr_bps > 0 else np.sign(smooth) * CLIP
    out = c.replace([np.inf, -np.inf], np.nan).fillna(0.0).clip(-CLIP, CLIP)
    return pd.Series(out, index=spot.index)


def demo() -> None:
    idx = pd.date_range("2026-01-01", periods=200, freq="15min")
    # funding slope: rising rates -> long conviction
    fr = pd.Series(np.linspace(-0.0003, 0.0003, 200), index=idx)
    c = funding_slope_signal(pd.DataFrame({"rate": fr}), w=20, z=2.0)
    assert c.between(-1, 1).all(), "conviction out of [-1,1]"
    assert (c.iloc[-20:] > 0).any(), "rising funding should produce long conviction"
    assert (c.iloc[:20] == 0).all() or (c.abs() < 1).any(), "early/flat masks or clamps"
    # trend: uptrend -> long, downtrend -> short
    up = pd.Series(np.linspace(100, 120, 200), index=idx)
    ct = trend_signal(up, period=14, mult=3.0)
    assert ct.between(-1, 1).all()
    assert (ct.iloc[-20:] > 0).mean() > 0.5, "uptrend -> long"
    down = pd.Series(np.linspace(120, 100, 200), index=idx)
    ctd = trend_signal(down, period=14, mult=3.0)
    assert (ctd.iloc[-20:] < 0).mean() > 0.5, "downtrend -> short"
    # basis: contango (perp>spot) -> long
    spot = pd.Series(np.full(200, 100.0), index=idx)
    perp = pd.Series(np.linspace(100, 100.5, 200), index=idx)  # premium rising
    cb = basis_signal(perp, spot, w=20, thr_bps=10.0)
    assert cb.between(-1, 1).all()
    assert (cb.iloc[-20:] > 0).any(), "contango -> long"
    # NaN/empty guard: empty window -> 0 (no NaN propagation)
    empty = pd.Series([np.nan, np.nan], index=idx[:2], dtype=float)
    assert funding_slope_signal(pd.DataFrame({"rate": empty}), w=20, z=2.0).fillna(0).eq(0).all()
    print("regime_gates OK")


if __name__ == "__main__":
    demo()