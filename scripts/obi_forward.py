"""Forward-test order-book imbalance (OBI) as a short-horizon signal (§2 follow-up
to the order-flow class, post §25/§26).

Order flow (trade-side CVD §25, bar taker-ratio §26) closed negative: coincident,
already in the price. OBI is a DIFFERENT order-flow derivative — RESTING liquidity
(top-20 bid vs ask qty), not executed flow — so it is the one untested order-flow
proxy. The depth recorder (scripts/microstructure.py, depth-update-20 capture)
accrues reports/depth_<pair>.csv: ts_ms, obi, bid_qty, ask_qty, top_bid, top_ask.

~1/s depth snapshots (retail-friendly, not microsecond HFT). OBI is noisy at 1s
(swings -0.9..+0.9), so the signal uses a rolling-mean over `lookback` bars and
tests whether it predicts next-horizon MID return direction (hit% > 50%) and
survives perp round-trip flip costs.

NOT a deployable backtest: no funding (second-horizon), flat slippage, no
walk-forward (single accrual). Gate (same as §25): hit% materially >50% AND
net_eq>1 over >=1 week -> justify a proper walk-forward; else OBI is also already
priced and the order-flow class closes at a third level.

Usage: python scripts/obi_forward.py [pair]   # default B_BTC_USDT
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

from scripts.funding_carry_band import FEE_TAKER

SLIPPAGE_BPS = 2.0
FLIP_COST = 2 * FEE_TAKER + 2 * SLIPPAGE_BPS / 1e4
GRID = [(1, 1, 20), (1, 5, 20), (5, 5, 50), (5, 15, 50), (5, 30, 100),
        (15, 15, 100), (15, 30, 200)]


def load_depth(pair: str) -> pd.DataFrame:
    p = Path(f"reports/depth_{pair.replace('-', '_').replace('@', '_')}.csv")
    if not p.exists():
        raise FileNotFoundError(f"{p} not found (run the depth recorder >=1 week)")
    df = pd.read_csv(p)
    df["ts"] = pd.to_datetime(df["ts_ms"], unit="ms", utc=True)
    df = df.sort_values("ts").set_index("ts")
    df["mid"] = (df["top_bid"] + df["top_ask"]) / 2
    return df[["obi", "mid"]].dropna()


def bars(df: pd.DataFrame, bar_s: int) -> pd.DataFrame:
    r = df.resample(f"{bar_s}s")
    return pd.DataFrame({"obi": r["obi"].last(), "px": r["mid"].last()}).dropna()


def test_window(b: pd.DataFrame, horizon: int, lookback: int) -> dict:
    sig = np.sign(b["obi"].rolling(lookback).mean()).shift(1)   # smoothed, past only
    fwd = (b["px"].shift(-horizon) - b["px"]) / b["px"]
    mask = sig.notna() & (sig != 0) & fwd.notna()
    if mask.sum() < 30:
        return dict(n=int(mask.sum()), hit=np.nan, bare=np.nan, net=np.nan, flips=np.nan)
    s = sig[mask]; f = fwd[mask]
    hit = float((np.sign(f) == s).mean())
    bare = float(np.prod(1 + s.values * f.values))
    pos = s.values.astype(float)
    flips = int(np.diff(pos, prepend=pos[0]).astype(bool).sum())
    net = float(np.prod(1 + pos * f.values -
                        FLIP_COST * np.diff(pos, prepend=pos[0]).astype(bool)))
    return dict(n=int(mask.sum()), hit=hit, bare=bare, net=net, flips=flips)


def main(pair: str = "B_BTC_USDT"):
    df = load_depth(pair)
    span = (df.index[-1] - df.index[0]).total_seconds() / 3600
    print(f"OBI forward-test | {pair} | {len(df)} snapshots, {span:.2f}h span, "
          f"{df.index[0]} -> {df.index[-1]}\n")
    if span < 168:
        print(f"WARN: <1 week sample ({span:.1f}h) -> noise, structure only. "
              "Re-run once >=1 week of depth has accrued.\n")
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
    print("\nhit% = fraction of bars where smoothed-OBI sign matched next-horizon")
    print("MID return sign. bare_eq/net_eq = long/short per OBI, minus flip cost.")
    print("Gate: hit% materially >50% AND net_eq>1 over >=1 week -> walk-forward;")
    print("else OBI is also already-priced (order-flow class closes at 3rd level).")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "B_BTC_USDT")