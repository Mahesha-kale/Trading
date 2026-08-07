"""External regime prior, walk-forwarded (step 4). §13 tested DXY / US10Y with a
70/30 split and every signal FLIPPED SIGN between train and OOS = regime luck,
not prediction. The fix the §13 conclusion called for: (a) a different external
series and (b) the regime-balanced K=4 walk-forward, not the single 70/30 split.

Tests EQUITY risk-appetite priors §13 did NOT try: VIX (VIXCLS) and S&P500 (SP500)
from FRED — free, daily, genuinely external to crypto, 2023-2026. Hypothesis: low
/ falling VIX and rising SP500 (risk-on) → long BTC; high VIX → flat/short.
Reuses `fred()` + `metrics()` from `scripts/macro_signal.py`.

Robust = positive net in a MAJORITY of the K=4 folds AND across BOTH BTC up & dn
regime folds (a prior that only profits in bull folds = bull beta, the §13 trap).
Usage: python scripts/macro_wf.py [BTCUSDT]
"""
from __future__ import annotations

import sys

import numpy as np
import pandas as pd

from scripts.macro_signal import fred, btc_daily, metrics  # reuse

K = 4
LEV = 1  # macro prior is a directional daily position; lev only scales


def signal_pnl(sig: pd.Series, ret: pd.Series) -> pd.Series:
    pnl = (sig.shift(1) * ret).fillna(0)   # act on prior close, no lookahead
    return (1 + pnl).cumprod()


def build_signals(df: pd.DataFrame) -> dict:
    out = {}
    out["vix_below_ma50"] = (df["VIXCLS"] < df["VIXCLS"].rolling(50).mean()).astype(int) * 2 - 1
    out["vix_mom5"] = -np.sign(df["VIXCLS"].diff(5))              # falling vol -> long
    out["vix_inv_level"] = -np.sign((df["VIXCLS"] - df["VIXCLS"].rolling(100).mean()))  # low vix -> long
    out["sp_mom5"] = np.sign(df["SP500"].pct_change(5))           # rising equities -> long
    out["sp_mom20"] = np.sign(df["SP500"].pct_change(20))
    out["dxy_mom5"] = -np.sign(df["DTWEXBGS"].pct_change(5))      # §13 baseline, for re-compare
    return out


def folds(df: pd.DataFrame):
    step = len(df) // K
    return [df.iloc[i * step:(i + 1) * step] for i in range(K)]


def main(symbol="BTCUSDT"):
    px = btc_daily(symbol)
    px.index = px.index.tz_localize(None)
    dxy = fred("DTWEXBGS")
    vix = fred("VIXCLS")
    sp = fred("SP500")
    df = px.join(dxy, how="inner").join(vix, how="inner").join(sp, how="inner").dropna()
    df["ret"] = df["btc"].pct_change()
    df = df.dropna()
    sigs = build_signals(df)
    print(f"{symbol}: {len(df)} daily rows {df.index[0].date()}->{df.index[-1].date()} "
          f"| external: DXY, VIX, SP500\n", flush=True)
    print(f"{'signal':14}{'fold':5}{'reg':4}{'bh%':>6}{'net%':>7}{'sh':>6}", flush=True)
    for name, sig in sigs.items():
        segs = folds(df)
        agg = 0.0; pos = 0; pos_up = 0; pos_dn = 0; n_up = n_dn = 0
        for i, seg in enumerate(segs):
            bh = seg["btc"].iloc[-1] / seg["btc"].iloc[0] - 1
            reg = "up" if bh >= 0 else "dn"
            eq = signal_pnl(sig.loc[seg.index], seg["ret"])
            net = (eq.iloc[-1] - 1) * 100
            sh = metrics(eq)["sharpe"]
            agg += net
            if net > 0: pos += 1
            if reg == "up": n_up += 1; pos_up += net > 0
            else: n_dn += 1; pos_dn += net > 0
            print(f"{name:14}{i+1:5}{reg:4}{bh*100:6.0f}{net:7.1f}{sh:6.2f}", flush=True)
        robust = pos > K / 2 and pos_up > 0 and pos_dn > 0
        tag = "ROBUST" if robust else ("bear-beta" if pos_dn > pos_up else "bull-beta/weak")
        print(f"{name:14} agg_net={agg:7.1f} pos={pos}/{K} (up {pos_up}/{n_up}, "
              f"dn {pos_dn}/{n_dn}) -> {tag}\n", flush=True)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "BTCUSDT")