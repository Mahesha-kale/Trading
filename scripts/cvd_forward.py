"""Forward-test CVD as a short-horizon directional signal (step 3 analysis).

NOT backtestable from history (no tick archive) -> the microstructure recorder
(`scripts/microstructure.py`, deployed on Oracle cloud) accumulates real
CoinDCX trades to reports/ticks_<pair>.csv. This is the forward-test that runs
on that accrued sample once it is large enough (>=1 week per the plan).

Ticks carry REAL aggressor side: `side` = +1 (buyer taker, m=false) / -1
(seller taker, m=true). CVD = sum(side*qty). Question: does rolling CVD predict
the next-horizon price return direction (hit rate > 50%) and does it survive
perp round-trip costs on position flips?

Design (time bars, the way you'd actually trade an order-flow signal):
  - resample ticks to BAR_S-second bars: cvd = sum(side*qty), px = last price.
  - signal at bar t = sign of rolling CVD over `lookback` bars (order-flow
    pressure direction).
  - fwd_ret = (px[t+h] - px[t]) / px[t], h = HORIZON_S / BAR_S.
  - hit rate = mean(sign(fwd_ret) == sign(signal)) over bars where signal != 0.
  - bare equity = product(1 + signal*fwd_ret) (long/short per CVD, hold h bars).
  - net equity = same but subtract round-trip cost (2*FEE_TAKER + 2*slippage)
    each time the position flips vs the prior bar.

This is informational-edge detection, not a deployable backtest: no funding
(irrelevant at second horizon), no slippage model beyond a flat bps, no
walk-forward (single accrual window). A significant hit rate + net-positive
equity justifies a proper walk-forward; neither -> CVD has no short-horizon
edge and the last structurally-different info source is closed.

Usage: python scripts/cvd_forward.py [pair]   # pair default B_BTC_USDT
       Reads reports/ticks_<pair>.csv (recorder output).
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

from scripts.funding_carry_band import FEE_TAKER  # 0.0004 per fill

SLIPPAGE_BPS = 2.0                     # flat, per fill
FLIP_COST = 2 * FEE_TAKER + 2 * SLIPPAGE_BPS / 1e4   # round-trip on a flip
# (bar, horizon, lookback) grid — short horizons (order flow decays fast)
GRID = [(1, 1, 20), (1, 5, 20), (5, 5, 50), (5, 15, 50), (5, 30, 100),
        (15, 15, 100), (15, 30, 200)]


def load_ticks(pair: str) -> pd.DataFrame:
    p = Path(f"reports/ticks_{pair.replace('-', '_').replace('@', '_')}.csv")
    if not p.exists():
        raise FileNotFoundError(f"{p} not found (run the recorder first)")
    df = pd.read_csv(p)
    df["ts"] = pd.to_datetime(df["ts_ms"], unit="ms", utc=True)
    df = df.sort_values("ts").set_index("ts")
    # sanity: side in {-1,+1}
    df = df[df["side"].isin([-1, 1])]
    return df[["price", "qty", "side"]]


def bars(df: pd.DataFrame, bar_s: int) -> pd.DataFrame:
    """Resample ticks to bar_s-second bars: cvd = sum(side*qty), px = last."""
    signed = df["side"] * df["qty"]            # precompute (SeriesGroupBy can't multiply)
    r = signed.resample(f"{bar_s}s")
    out = pd.DataFrame({
        "px": df["price"].resample(f"{bar_s}s").last(),
        "cvd": r.sum(),
        "n": df["side"].resample(f"{bar_s}s").size(),
    }).dropna(subset=["px"])
    return out


def test_window(b: pd.DataFrame, horizon: int, lookback: int) -> dict:
    """hit rate + bare/net equity for one (bar,horizon,lookback) combo."""
    sig = np.sign(b["cvd"].rolling(lookback).sum()).shift(1)   # use past only
    fwd = (b["px"].shift(-horizon) - b["px"]) / b["px"]
    # NaN != 0 is True in pandas, so explicitly require sig.notna() or NaN leaks
    # into the product and turns bare/net equity into NaN.
    mask = sig.notna() & (sig != 0) & fwd.notna()
    if mask.sum() < 30:                       # too few bars -> not meaningful
        return dict(n=int(mask.sum()), hit=np.nan, bare=np.nan, net=np.nan,
                    flips=np.nan)
    s = sig[mask]; f = fwd[mask]
    hit = float((np.sign(f) == s).mean())
    bare = float(np.prod(1 + s.values * f.values))
    # net: subtract flip cost when position changes bar-to-bar
    pos = s.values.astype(float)
    flips = int(np.diff(pos, prepend=pos[0]).astype(bool).sum())
    net = float(np.prod(1 + pos * f.values - FLIP_COST * np.diff(pos, prepend=pos[0]).astype(bool)))
    return dict(n=int(mask.sum()), hit=hit, bare=bare, net=net, flips=flips)


def main(pair: str = "B_BTC_USDT"):
    df = load_ticks(pair)
    span = (df.index[-1] - df.index[0]).total_seconds() / 3600
    print(f"CVD forward-test | {pair} | {len(df)} ticks, {span:.2f}h span, "
          f"{df.index[0]} -> {df.index[-1]}\n")
    if span < 1:
        print("WARN: <1h sample -> numbers are noise, structure only. "
              "Re-run once >=1 week of ticks has accrued.\n")
    print(f"{'bar_s':>5}{'horizon':>8}{'lookback':>9}{'n_bars':>7}{'hit%':>7}"
          f"{'bare_eq':>9}{'net_eq':>9}{'flips':>6}")
    for bar_s, horizon, lookback in GRID:
        b = bars(df, bar_s)
        if len(b) < lookback + horizon + 30:
            print(f"{bar_s:>5}{horizon:>8}{lookback:>9}{len(b):>7}   (not enough bars)")
            continue
        r = test_window(b, horizon, lookback)
        hit_s = f"{r['hit']*100:6.1f}" if r["hit"] == r["hit"] else "   nan"
        bare_s = f"{r['bare']:8.3f}" if r["bare"] == r["bare"] else "     nan"
        net_s = f"{r['net']:8.3f}" if r["net"] == r["net"] else "     nan"
        print(f"{bar_s:>5}{horizon:>8}{lookback:>9}{r['n']:>7}{hit_s}{bare_s}"
              f"{net_s}{r['flips']:>6}")
    print("\nhit% = fraction of bars where rolling-CVD sign matched next-horizon")
    print("return sign (>50% = directional edge). bare_eq = long/short per CVD,")
    print("no costs. net_eq = minus round-trip cost on each position flip.")
    print("Verdict gate: hit% materially >50% AND net_eq>1 over a >=1 week sample")
    print("-> justify a proper walk-forward. Else CVD has no short-horizon edge.")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "B_BTC_USDT")