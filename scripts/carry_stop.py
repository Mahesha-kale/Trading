"""Basis-stop de-risk for the funding-carry harvest (step 2 engineering, §23 follow-up).

§20/§23: the one-sided carry (SHORT perp + LONG spot, harvest positive funding) is
~7%/yr on notional but exposed to a rare perp-premium blowout (short squeeze) that
historically wipes a whole cycle's income. (c) tests whether a BASIS-STOP makes the
tail BOUNDED for an affordable in-sample insurance cost:

  while holding: if perp premium B (bps) > stop_bps -> FLATTEN (realize the adverse
  basis move = stop_bps of notional + close fees + 1% TDS on the spot sell), go flat.
  re-enter (re-open short perp + long spot) only when B < reentry_bps AND funding
  still positive (hysteresis -> don't reopen into an ongoing squeeze).

The in-sample window (2023-2026) has NO cascade, so the stop can only show its COST
(false triggers + fees + missed funding while flat). If that cost is small, the stop
is cheap insurance that caps the (out-of-window) tail at `stop_bps` -> bounded downside.

Reuses load_funding/load_price (scripts.funding_carry_band / .funding_carry),
load_spot_close (scripts.basis_risk), metrics (scripts.funding_carry).
One-sided (CoinDCX-executable: no spot short). Lev 1.

Usage: python scripts/carry_stop.py
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from scripts.funding_carry import align, load_price, metrics
from scripts.funding_carry_band import load_funding, FEE_TAKER, MAKER
from scripts.basis_risk import load_spot_close

FEE = FEE_TAKER * (0.5 if MAKER else 1.0)   # per-fill
TDS = 0.01                                   # 1% on spot SELL (flatten only)
OPEN_COST = 2 * FEE                           # short perp + long spot (spot buy: no TDS)
CLOSE_COST = 2 * FEE + TDS                    # buy perp (close short) + SELL spot
BAND = 0.0002                                 # one-sided: hold only when rate > band
STOPS = [None, 30, 50, 100, 200, 500]         # bps; None = no stop (= §20 baseline)


def frame_15m(symbol: str) -> pd.DataFrame:
    """15m frame: basis_bps (every bar) + forward-filled funding rate."""
    perp = load_price(symbol); spot = load_spot_close(symbol)
    df = pd.DataFrame({"perp": perp, "spot": spot}).dropna()
    df["basis_bps"] = (df["perp"] / df["spot"] - 1.0) * 1e4
    fund = load_funding(symbol)
    df["rate"] = fund["rate"].reindex(df.index, method="ffill")
    return df.dropna(subset=["rate"])


BARS_PER_MARK = 32  # 15m bars per 8h funding period


def simulate(df: pd.DataFrame, stop: float | None) -> tuple:
    """Equity PATH (15m) + (n_flat, n_stop, n_reopen). stop=None = §20 baseline.

    15m resolution: basis-stop checks EVERY bar (catches intra-8h squeezes that
    8h-mark sampling misses). Funding accrues PRO-RATA each bar: (1+r)^(1/32) while
    holding (Binance funding is time-pro-rata; this is gap-robust vs mark-matching).
    One-sided harvest: hold SHORT, collect/pay funding; deadband (flatten when
    funding r<-BAND, re-enter when r>+BAND); basis-stop flattens on perp-premium
    spike and re-enters when basis calms (hysteresis stop/2).
    """
    rate = df["rate"].values; bv = df["basis_bps"].values
    eq = 1.0; side = 0; n_flat = n_stop = n_reopen = 0
    reentry = stop / 2.0 if stop is not None else 0.0
    accr = 1.0 / BARS_PER_MARK
    path = np.empty(len(df))
    for i in range(len(df)):
        r = rate[i]; prem = bv[i]
        if side == 0:
            enter = (r > BAND) or (i == 0 and r > 0)        # init short on first positive funding
            if enter and (stop is None or prem < reentry):
                eq *= (1.0 - OPEN_COST); side = 1
                if i > 0:
                    n_reopen += 1
        else:  # holding short
            eq *= (1.0 + r) ** accr                         # pro-rata funding accrual
            if r < -BAND:                                  # funding deeply negative -> flatten
                eq *= (1.0 - CLOSE_COST); side = 0; n_flat += 1
            elif stop is not None and prem > stop:         # basis-stop (squeeze) -> flatten
                eq *= (1.0 - prem / 1e4 - CLOSE_COST); side = 0; n_stop += 1
        path[i] = eq
    return pd.Series(path, index=df.index), n_flat, n_stop, n_reopen


def main():
    print(f"One-sided funding carry + basis-stop | band={BAND} fee/fill={FEE:.5f} "
          f"TDS={TDS} lev 1 | 2023-01..2026-07 (NO cascade in window -> stop cost only)\n")
    print(f"{'sym':8}{'stop':>6}{'net%':>8}{'/yr%':>7}{'flat_f':>7}{'stops':>7}"
          f"{'reopen':>7}{'maxdd':>7}{'sh':>6}   note")
    for sym in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):
        df = frame_15m(sym)
        yrs = len(df) / (96 * 365)
        for stop in STOPS:
            path, nf, ns, nr = simulate(df, stop)
            me = metrics(path)
            lbl = "none" if stop is None else str(stop)
            note = "= §20 baseline" if stop is None else ""
            print(f"{sym:8}{lbl:>6}{(path.iloc[-1]-1)*100:8.1f}"
                  f"{((path.iloc[-1]**(1/yrs)-1))*100:7.2f}{nf:7d}{ns:7d}{nr:7d}"
                  f"{me['max_dd']:7.3f}{me['sharpe']:6.2f}   {note}")
        print()


if __name__ == "__main__":
    main()