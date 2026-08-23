"""Volume-profile forward-test from accrued CoinDCX ticks (direction #3).

§25/§26 closed trade-flow order signals negative (already in the price). Volume
profile (VP) is volume-at-PRICE — a different slicing. Its two canonical uses
both map to classes §18 already refuted on price bars:
  - VP REVERSION: fade above VAH / below VAL (mean-reversion, refuted §18).
  - VP BREAKOUT:  close above VAH -> long / below VAL -> short (breakout = bull-
    beta, refuted §18).
This tests them on REAL tick volume-at-price (not the OHLC approximation §25 called
weaker), as the honest "try it" check. 16d of ticks (BTC 10.4M) is ~96 4h windows
-> a structure check, NOT a robust walk-forward (need months). Maps to refuted
classes + thin sample = low EV, but the data is real.

Per discrete W-hour window: bin ticks by price -> volume-at-price -> POC (max-vol
price), value area = prices around POC covering 70% of window volume, VAH/VAL =
its top/bottom, close = last tick price. Signal at window close -> next-window
return. reversion: close>VAH short / <VAL long. breakout: close>VAH long / <VAL
short. hit% + bare/net equity (flip cost), both signal types reported.

Usage: python scripts/volume_profile.py [pair] [window_h]
       Reads reports/ticks_<pair>.csv (recorder output).
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

from scripts.funding_carry_band import FEE_TAKER

SLIPPAGE_BPS = 2.0
FLIP_COST = 2 * FEE_TAKER + 2 * SLIPPAGE_BPS / 1e4
VA_PCT = 0.70          # value area = 70% of volume around POC


def load_ticks(pair: str) -> pd.DataFrame:
    p = Path(f"reports/ticks_{pair.replace('-', '_').replace('@', '_')}.csv")
    if not p.exists():
        raise FileNotFoundError(f"{p} not found")
    df = pd.read_csv(p, usecols=["ts_ms", "price", "qty"])
    df["ts"] = pd.to_datetime(df["ts_ms"], unit="ms", utc=True)
    return df.sort_values("ts").set_index("ts")[["price", "qty"]]


def vp_window(ticks: pd.DataFrame) -> dict | None:
    """POC / VAH / VAL / close for one window's ticks."""
    if len(ticks) < 50:
        return None
    lo, hi = ticks["price"].min(), ticks["price"].max()
    step = max((hi - lo) / 200, 1e-9)               # ~200 price bins across the range
    bins = (ticks["price"] / step).astype(int)
    vol = ticks["qty"].groupby(bins).sum()
    poc_bin = int(vol.idxmax())
    total = vol.sum(); target = VA_PCT * total
    # expand around POC until 70% covered
    order = vol.sort_values(ascending=False)
    covered = 0.0; va_bins = set()
    for b, v in order.items():
        covered += v; va_bins.add(int(b))
        if covered >= target:
            break
    prices = (np.array(list(va_bins)) + 0.5) * step
    return {"poc": (poc_bin + 0.5) * step, "vah": prices.max(), "val": prices.min(),
            "close": float(ticks["price"].iloc[-1])}


def build(pair: str, window_h: int):
    df = load_ticks(pair)
    span_h = (df.index[-1] - df.index[0]).total_seconds() / 3600
    print(f"Volume-profile forward-test | {pair} | {len(df)} ticks, {span_h:.1f}h span "
          f"| window={window_h}h\n")
    if span_h < window_h * 20:
        print(f"WARN: <{window_h*20}h sample ({span_h:.0f}h) -> structure only, "
              f"need months for a robust VP walk-forward.\n")
    ws = int(window_h * 3600)
    start = int(df.index[0].timestamp()) // ws * ws
    end = int(df.index[-1].timestamp())
    rows = []
    for t0 in range(start, end - ws, ws):          # non-overlapping windows
        w = df.loc[(df.index >= pd.Timestamp(t0, unit="s", tz="UTC")) &
                   (df.index < pd.Timestamp(t0 + ws, unit="s", tz="UTC"))]
        vp = vp_window(w)
        if vp:
            rows.append(vp)
    if len(rows) < 20:
        print(f"only {len(rows)} windows -> too few to test")
        return
    V = pd.DataFrame(rows)
    V["ret"] = V["close"].pct_change().shift(-1)    # next-window return
    return V


def test_signal(V: pd.DataFrame, kind: str):
    """kind = 'reversion' (fade VAH/VAL) or 'breakout' (follow VAH/VAL)."""
    if kind == "reversion":
        sig = np.where(V["close"] > V["vah"], -1.0, np.where(V["close"] < V["val"], 1.0, 0.0))
    else:
        sig = np.where(V["close"] > V["vah"], 1.0, np.where(V["close"] < V["val"], -1.0, 0.0))
    sig = pd.Series(sig, index=V.index).shift(1)    # past window -> next return
    fwd = V["ret"]
    mask = sig.notna() & (sig != 0) & fwd.notna()
    if mask.sum() < 10:
        print(f"  {kind}: {int(mask.sum())} signals -> too few")
        return
    s = sig[mask]; f = fwd[mask]
    hit = float((np.sign(f) == s).mean())
    bare = float(np.prod(1 + s.values * f.values))
    pos = s.values.astype(float)
    flips = int(np.diff(pos, prepend=pos[0]).astype(bool).sum())
    net = float(np.prod(1 + pos * f.values -
                        FLIP_COST * np.diff(pos, prepend=pos[0]).astype(bool)))
    mean_r = float((s.values * f.values).mean() * 100)
    print(f"  {kind:9} n={int(mask.sum()):3} hit%={hit*100:5.1f} "
          f"mean_ret/win={mean_r:+.3f}% bare_eq={bare:6.3f} net_eq={net:6.3f} flips={flips}")


def main(pair: str = "B_BTC_USDT", window_h: int = 4):
    V = build(pair, window_h)
    if V is None:
        return
    print(f"{len(V)} windows built. POC/VAH/VAL from real tick volume-at-price.\n")
    print(f"signals (close vs VA at window close -> next-{window_h}h return):")
    test_signal(V, "reversion")
    test_signal(V, "breakout")
    # how often does close sit inside vs outside VA? (signal frequency)
    out = ((V["close"] > V["vah"]) | (V["close"] < V["val"])).mean()
    print(f"\nclose outside VA (signal fires): {out*100:.0f}% of windows; "
          f"inside (no signal): {(1-out)*100:.0f}%")
    print("\nhit% >50% materially AND net_eq>1 (both kinds) over a multi-month sample")
    print("-> VP edge. Else VP maps to the refuted reversion/breakout classes.")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "B_BTC_USDT",
         int(sys.argv[2]) if len(sys.argv) > 2 else 4)