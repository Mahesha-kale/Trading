"""Perp-spot basis tail risk for the funding-carry harvest (step 2 follow-up).

§20 showed the band-gated carry is the first net-positive-after-costs result
(~7%/yr) but flagged an UNMODELED basis/short-squeeze tail as the deployability
blocker: the carry harvest is SHORT perp + LONG spot (delta neutral, keep
funding). The short-perp leg loses notional faster than the spot hedge in a
perp-premium spike (short squeeze) -> margin call / liquidation on the perp
alone. One squeeze > a year's funding income kills the strategy.

This quantifies the tail from REAL perp-vs-spot basis:
  basis B = perp/spot - 1 (fractional premium; B>0 = perp premium).
  short-perp+long-spot PnL vs basis = B_entry - B_close  -> PROFITS when B falls,
  LOSES when B rises (premium widens / squeeze). Adverse excursion = max(B) - B0
  over a hold = the margin-call drawdown (bps of notional).

Compares the worst basis spike (and its frequency) to 1yr of funding income
(the wipe threshold). Spot 15m pulled by `pull_binance.py ... spot` (Binance
Vision data/spot/monthly/klines); perp 15m already cached.

Usage: python scripts/basis_risk.py
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from scripts.funding_carry import load_price  # perp close
from scripts.funding_carry_band import load_funding, gross_funding  # reuse


def load_spot_close(symbol: str) -> pd.Series:
    """Spot 15m close, mirroring load_price but reading the _spot_ cache.

    Spot monthly CSVs occasionally carry a stray bad-timestamp row (open_time
    far outside the window); parse with coerce + drop so it doesn't poison the
    index (and force the whole index to object/str, breaking alignment).
    """
    for ext in ("parquet", "csv"):
        p = f"reports/binance_{symbol}_spot_15m.{ext}"
        try:
            df = (pd.read_parquet(p) if ext == "parquet"
                  else pd.read_csv(p, index_col=0))
            if df.index.dtype.kind != "M":
                idx = pd.to_datetime(df.index, errors="coerce", utc=True)
                df = df[~idx.isna()]
                df.index = idx[~idx.isna()]
            elif df.index.tz is None:
                df.index = df.index.tz_localize("UTC")
            return df["close"].astype(float).sort_index()
        except Exception:
            continue
    raise FileNotFoundError(f"no spot 15m cache for {symbol} (run pull_binance spot)")


def main():
    print("Perp-spot basis tail risk for funding-carry harvest | 2023-01..2026-07\n"
          "(window EXCLUDES 2020/2022 crashes -> UNDERSTATES the true tail)\n")
    print(f"{'sym':8}{'bars':>7}{'basis_bps mean':>16}{'std':>7}{'p1':>6}"
          f"{'p99':>6}{'max':>7}{'min':>7}{'1yr_fund%':>10}{'worst_spike_bps':>16}"
          f"{'spikes>1yr':>11}")
    for sym in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):
        try:
            perp = load_price(sym)
            spot = load_spot_close(sym)
        except FileNotFoundError as e:
            print(f"{sym:8} skip: {e}")
            continue
        df = pd.DataFrame({"perp": perp, "spot": spot}).dropna()
        if df.empty:
            print(f"{sym:8} empty after align")
            continue
        b = (df["perp"] / df["spot"] - 1.0) * 1e4          # basis, bps
        yrs = len(df) / (96 * 365)                          # 15m bars/yr
        # 1yr funding income (always-receive, no fee) = |rate| over the window /yrs
        try:
            f = load_funding(sym)
            fund_1yr = gross_funding(f) / (len(f) / (3 * 365)) * 100  # 3 marks/day
        except Exception:
            fund_1yr = float("nan")
        # worst adverse basis excursion = max premium over the whole window
        # (BTC carry holds the WHOLE period per §20, so the margin-call drawdown
        #  is the largest premium spike from entry onward).
        worst = float(b.max() - b.iloc[0])
        # how many distinct 8h windows had a premium > 1yr of funding (wipe events)
        thr = fund_1yr * 100  # 1yr funding income, in bps
        b8h = b.resample("8h").max()
        spikes = int((b8h > thr).sum()) if thr == thr else -1
        print(f"{sym:8}{len(df):7d}{b.mean():16.1f}{b.std():7.1f}{b.quantile(.01):6.0f}"
              f"{b.quantile(.99):6.0f}{b.max():7.0f}{b.min():7.0f}{fund_1yr:10.2f}"
              f"{worst:16.0f}{spikes:11d}")

    print("\nBasis = perp/spot - 1 (bps). B>0 = perp premium (short-squeeze hurts")
    print("the short-perp carry leg). worst_spike = max premium over window = the")
    print("margin-call drawdown vs entry. spikes>1yr = 8h windows with a premium")
    print("jump larger than 1yr funding income (a wipe-class event).")
    print("\nVerdict gate: if worst_spike_bps > 1yr_fund%*100, a single squeeze can")
    print("wipe > a year of funding income -> carry NOT safely deployable at any")
    print("leverage; needs an explicit basis/short-squeeze hedge or much lower lev.")


if __name__ == "__main__":
    main()