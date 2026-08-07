"""Band-gated delta-neutral funding carry (step 2 of post-close plan).

§12 refuted naive sign-flip delta-neutral carry: funding sign oscillates on
small rates (336 flips / 2828 events, 12%), each flip = 4 fills, so flip cost
(26.9% maker over 2.5yr) > gross funding income (24.2%). The noise-driven flips
earn ~0 funding but pay full fees.

Band-gated re-hedge = hysteresis deadband: go SHORT only when rate > +b, LONG only
when rate < -b, HOLD current side while -b <= rate <= b. Skips near-zero flips
(pays small adverse funding in the deadband instead of 4 fills to flip). Net
improves if the saved flip fees exceed the deadband adverse funding paid.

Real signed funding from the cached Binance funding CSVs (pulled by
pull_funding.py). Delta-neutral: price cancels perp vs spot; PnL = funding
received/paid - flip fees. Lev 1 (carry is capital-efficient; lev only scales,
not sharpe). Train 70% / OOS 30% + band swept; naive b=0 baseline = §12.

Usage: python scripts/funding_carry_band.py
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from scripts.funding_carry import align, load_price, metrics  # reuse

BANDS = [0.0, 0.00005, 0.0001, 0.0002, 0.0003, 0.0005]
FEE_TAKER = 0.0004
# 4 fills per flip (close old + open new, perp + spot). maker ~ half taker.
MAKER = True


def load_funding(symbol: str) -> pd.DataFrame:
    f = pd.read_csv(f"reports/binance_{symbol}_funding.csv", index_col=0)
    f.index = pd.to_datetime(f.index, utc=True, format="ISO8601")
    return f[["rate"]].astype(float).sort_index()


def dn_band(rate: np.ndarray, band: float, fee_per_fill: float) -> tuple[pd.Series, int]:
    """Deadband delta-neutral equity curve + flip count. side=+1 long / -1 short.
    funding_to_you = -side*rate (receiving side = -sign(rate)). flip = 4 fills."""
    side = 0.0
    eq = np.ones(len(rate))
    flips = 0
    for i, r in enumerate(rate):
        target = -1.0 if r > band else (1.0 if r < -band else side)
        if target == 0.0:  # init while still in deadband: take receiving side
            target = -1.0 if r > 0 else 1.0
        if side == 0.0:  # first interval: open (counts as a flip, 4 fills)
            side = -1.0 if r > 0 else 1.0
            flips += 1
            fee = 4 * fee_per_fill
        elif target != side:
            side = target
            flips += 1
            fee = 4 * fee_per_fill
        else:
            fee = 0.0
        net = -side * r - fee
        eq[i] = eq[i - 1] * (1.0 + net) if i > 0 else (1.0 + net)
    return pd.Series(eq, index=rate.index if hasattr(rate, "index") else None), flips


def gross_funding(f: pd.DataFrame) -> float:
    """Sum of |rate| over the window = income if always on receiving side (no fees)."""
    return float(f["rate"].abs().sum())


def main():
    fee = FEE_TAKER * (0.5 if MAKER else 1.0)
    print(f"Band-gated delta-neutral funding carry | maker={MAKER} fee/fill={fee:.5f} "
          f"| 4 fills/flip | lev 1\n")
    for sym in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):
        price = load_price(sym)
        f = align(price, load_funding(sym))
        split = int(len(f) * 0.7)
        train, oos = f.iloc[:split], f.iloc[split:]
        gf_full = gross_funding(f) * 100
        print(f"=== {sym}: {len(f)} events {f.index[0].date()}->{f.index[-1].date()} "
              f"| gross|funding| full={gf_full:.1f}% (always-receive, no fee) ===")
        print(f"split {f.index[split].date()} | train {len(train)} oos {len(oos)}")
        print(f"{'band':>9}{'flips_f':>8}{'flips_o':>8}{'net_f%':>8}{'sh_f':>6}"
              f"{'net_o%':>8}{'sh_o':>6}{'dd_o':>7}{'pf_o':>6}")
        best_oos = (-9e9, None)
        for b in BANDS:
            ef, nf = dn_band(f["rate"].values, b, fee)
            eo, no = dn_band(oos["rate"].values, b, fee)
            mf = metrics(ef); mo = metrics(eo)
            print(f"{b:9.5f}{nf:8d}{no:8d}{(ef.iloc[-1]-1)*100:8.1f}{mf['sharpe']:6.2f}"
                  f"{(eo.iloc[-1]-1)*100:8.1f}{mo['sharpe']:6.2f}{mo['max_dd']:7.3f}{mo['pf']:6.2f}")
            if (eo.iloc[-1] - 1) > best_oos[0]:
                best_oos = ((eo.iloc[-1] - 1), b)
        # train-selected band -> OOS (honest, no OOS peeking)
        best_train = max(BANDS, key=lambda b: dn_band(train["rate"].values, b, fee)[0].iloc[-1])
        eo_ts, _ = dn_band(oos["rate"].values, best_train, fee)
        m_ts = metrics(eo_ts)
        bh_oos = oos["px_next"].iloc[-1] / oos["px"].iloc[0] - 1
        print(f"  train-best band={best_train:.5f} -> OOS net {(eo_ts.iloc[-1]-1)*100:.1f}% "
              f"sh {m_ts['sharpe']} | B&H OOS {bh_oos*100:.0f}%")
        print(f"  best-in-sample-OOS band={best_oos[1]:.5f} net {best_oos[0]*100:.1f}% (optimistic)\n")


if __name__ == "__main__":
    main()