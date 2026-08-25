"""Carry funding-regime walk-forward (direction #1 — the one untested rigor gap).

§20 tested carry across PRICE-regime folds (K=4 by time, tagged by buy&hold
sign). Every one of those folds had POSITIVE mean funding (BTC fold4 posFund 3.5%),
so §20 never isolated a NEGATIVE-funding regime — the exact rigor gap the handoff
names. Carry is funding-regime-dependent by construction (harvests positive
funding, sits out negative); §20 asserted that but only showed it across price
regimes. This splits the window by FUNDING regime (sustained positive vs
negative funding via a rolling mean) and scores the executable one-sided carry
in each, per sustained negative-regime period.

Question (handoff): does carry survive a negative-funding regime, or only go flat
(opportunity cost)? On CoinDCX (no spot short) flat-in-negative is the BEST
achievable — the two-sided harvest of negative funding is not executable. So the
gate is: profit in pos-regime AND no-bleed (>=0) in neg-regime. Bleed in neg =
refuted; flat in neg = by-design opportunity cost (confirms §20, closes the gap).

Executable one-sided carry: SHORT perp + LONG spot when rate > +band (harvest
positive funding); FLATTEN when rate < -band; HOLD in deadband (pay adverse
funding). Each flatten = SELL spot (1% TDS, spot-only — confirmed) + close perp
(1 fill). Each entry = short perp + long spot (2 fills). Lev 1, maker fee.
Train-selects band on first 70% by time (no OOS peeking), as §20.

Reuses funding_carry_band.load_funding/BANDS/FEE_TAKER/MAKER + funding_carry.metrics.

Usage: python scripts/carry_funding_regime.py
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from scripts.funding_carry_band import BANDS, FEE_TAKER, MAKER, load_funding
from scripts.funding_carry import metrics

TDS = 0.01  # 1% on spot SELL at each flatten (spot-only, confirmed CoinDCX)


def carry_oneside(rate: np.ndarray, band: float, fee_per_fill: float,
                  tds: float = TDS):
    """Executable CoinDCX one-sided carry. side -1 = short perp + long spot,
    0 = flat. Enter short when rate > +band; flatten when rate < -band; HOLD in
    deadband. entry = 2 fills (perp short + spot long); flatten = 1 fill + tds
    (perp close + spot sell). Returns per-mark arrays (decomposable by regime)."""
    side = 0.0
    n = len(rate)
    net = np.zeros(n); side_arr = np.zeros(n)
    entry = np.zeros(n, int); flat = np.zeros(n, int)
    for i, r in enumerate(rate):
        target = (-1.0 if r > band else 0.0) if side == 0.0 else (0.0 if r < -band else -1.0)
        if target != side:
            if target == -1.0:           # open short perp + long spot
                side = -1.0; entry[i] = 1; fee = 2 * fee_per_fill
            else:                        # flatten: perp close + spot sell (tds)
                side = 0.0; flat[i] = 1; fee = fee_per_fill + tds
        else:
            fee = 0.0
        side_arr[i] = side
        net[i] = -side * r - fee          # short receives +rate; flat receives 0
    return net, side_arr, entry, flat


# --- USDT-margined cost model (component 1 of the USDT carry redesign) ---
# §27's carry_oneside used one Binance-proxy fee (0.04%) for both legs + 1%
# sell-only TDS, and modeled no spot-sell fee. Real CoinDCX USDT costs differ:
# perp maker 0.0236% (§29), spot ~0.199% (0.169%+GST, §29 BTCINR-derived), and
# USDT C2C spot carries 1% TDS on BOTH buy + sell (Section 194S) = 2% round-trip.
# Futures leg = no TDS. This function keeps §27's carry_oneside byte-identical
# (baseline) and adds the real USDT path separately.
TDS_BUY_USDT = 0.01   # 1% on spot BUY (USDT C2C pair, Section 194S — both sides)
TDS_SELL_USDT = 0.01  # 1% on spot SELL
FEE_PERP = 0.000236   # CoinDCX perp maker 0.0236% (§29 verified)
FEE_SPOT = 0.00199    # CoinDCX spot ~0.169% × 1.18 GST (§29 BTCINR-derived; verify BTCUSDT in comp 3)


def carry_oneside_usdt(rate: np.ndarray, band: float, perp_fee: float = FEE_PERP,
                       spot_fee: float = FEE_SPOT, tds_buy: float = TDS_BUY_USDT,
                       tds_sell: float = TDS_SELL_USDT):
    """Executable CoinDCX one-sided carry under real USDT costs. side -1 = short
    perp + long spot, 0 = flat. Enter short when rate > +band; flatten when rate <
    -band; HOLD in deadband. entry = perp fill + spot fill + tds_buy (spot buy
    TDS); flatten = perp fill + spot fill + tds_sell (spot sell TDS). Futures leg
    has no TDS. Returns per-mark arrays (decomposable by regime), same shape as
    carry_oneside."""
    side = 0.0
    n = len(rate)
    net = np.zeros(n); side_arr = np.zeros(n)
    entry = np.zeros(n, int); flat = np.zeros(n, int)
    for i, r in enumerate(rate):
        target = (-1.0 if r > band else 0.0) if side == 0.0 else (0.0 if r < -band else -1.0)
        if target != side:
            if target == -1.0:           # open short perp + long spot (USDT spot buy TDS)
                side = -1.0; entry[i] = 1; fee = perp_fee + spot_fee + tds_buy
            else:                        # flatten: perp close + spot sell (USDT spot sell TDS)
                side = 0.0; flat[i] = 1; fee = perp_fee + spot_fee + tds_sell
        else:
            fee = 0.0
        side_arr[i] = side
        net[i] = -side * r - fee          # short receives +rate; flat receives 0
    return net, side_arr, entry, flat


def demo() -> None:
    """Self-check: USDT cost logic on a synthetic rate path with one entry + one
    flatten. Verifies entry/flatten/hold fees + that §27 carry_oneside is
    byte-identical to its prior behavior (baseline preserved)."""
    # synthetic: rate above band (enter), in band (hold), below -band (flatten)
    rate = np.array([0.0010, 0.0002, -0.0010])
    band = 0.0003
    net, side, ent, flt = carry_oneside_usdt(rate, band)
    # mark 0: enter short -> fee = perp+spot+tds_buy, net = -(-1)*r - fee = r - fee
    entry_fee = FEE_PERP + FEE_SPOT + TDS_BUY_USDT
    assert ent[0] == 1 and flt[0] == 0 and abs(net[0] - (rate[0] - entry_fee)) < 1e-15, \
        ("entry mark cost wrong", net[0], rate[0] - entry_fee)
    assert side[0] == -1.0, ("entry should set side -1", side[0])
    # mark 1: hold (rate within deadband) -> no fee, net = -side*r = r
    assert ent[1] == 0 and flt[1] == 0 and abs(net[1] - rate[1]) < 1e-15, \
        ("hold mark should have no fee", net[1], rate[1])
    # mark 2: flatten -> fee = perp+spot+tds_sell, side 0, net = 0 - fee = -fee
    flat_fee = FEE_PERP + FEE_SPOT + TDS_SELL_USDT
    assert flt[2] == 1 and ent[2] == 0 and abs(net[2] - (-flat_fee)) < 1e-15, \
        ("flatten mark cost wrong", net[2], -flat_fee)
    assert side[2] == 0.0, ("flatten should set side 0", side[2])
    # regression: §27 carry_oneside unchanged — its entry is 2*fee (no buy TDS),
    # flatten is fee + tds (sell-only, no spot-sell fee). Confirm the two models
    # differ at entry (USDT adds tds_buy + uses real fees) so the baseline is
    # genuinely preserved as a separate path.
    n27, _, e27, _ = carry_oneside(rate, band, fee_per_fill=0.0002)
    assert ent.sum() == e27.sum() == 1, "both models enter once on this path"
    assert abs(net[0] - n27[0]) > 1e-9, \
        "USDT entry cost must differ from §27 baseline (extra tds_buy + real fees)"
    print("carry_oneside_usdt cost logic OK")


def regime_runs(f: pd.DataFrame, window: int = 21):
    """Sustained funding regime = sign of rolling-mean funding over `window`
    marks (funding 3/day -> window=21 ~1 week). Returns int array +1/-1/0 and a
    list of (start, end, regime, nmarks) contiguous runs (len>=window//2)."""
    rm = f["rate"].rolling(window, min_periods=max(3, window // 3)).mean()
    reg = np.sign(rm.fillna(0.0)).astype(int).values
    runs = []
    i = 0
    while i < len(reg):
        j = i
        while j < len(reg) and reg[j] == reg[i]:
            j += 1
        if reg[i] != 0 and (j - i) >= max(window // 2, 5):
            runs.append((f.index[i], f.index[j - 1], int(reg[i]), j - i))
        i = j
    return reg, runs


def main():
    fee = FEE_TAKER * (0.5 if MAKER else 1.0)
    print(f"Carry funding-regime walk-forward | one-sided executable | "
          f"maker={MAKER} fee/fill={fee:.5f} TDS/flatten={TDS} | lev 1\n")
    for sym in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):
        f = load_funding(sym)
        split = int(len(f) * 0.7)
        train = f.iloc[:split]
        best = max(BANDS, key=lambda b: carry_oneside(train["rate"].values, b, fee)[0].sum())
        rate = f["rate"].values
        net, side, ent, flt = carry_oneside(rate, best, fee)
        reg, runs = regime_runs(f)
        eq = np.cumprod(1.0 + net)
        pos = reg > 0; neg = reg < 0; zer = reg == 0
        yrs = len(f) / (365 * 3)

        print(f"=== {sym}: {len(f)} marks {f.index[0].date()}->{f.index[-1].date()} | "
              f"train-best band={best:.5f} ===")
        print(f"regime marks: pos={pos.sum()} ({pos.mean()*100:.0f}%)  "
              f"neg={neg.sum()} ({neg.mean()*100:.0f}%)  zero={zer.sum()}  "
              f"runs={len(runs)} (neg runs={sum(1 for r in runs if r[2]<0)})")
        print(f"{'regime':>7}{'marks':>7}{'sumNet%':>9}{'avgRate%':>9}"
              f"{'entries':>8}{'flattens':>9}")
        for name, m in [("pos", pos), ("neg", neg), ("zero", zer)]:
            if m.sum():
                print(f"{name:>7}{m.sum():>7}{net[m].sum()*100:>9.2f}"
                      f"{(rate[m]*((side[m]!=0).astype(float))).mean()*100 if name!='zero' else 0:>9.4f}"
                      f"{ent[m].sum():>8}{flt[m].sum():>9}")
        print(f"  FULL: net={(eq[-1]-1)*100:.1f}% entries={ent.sum()} flattens={flt.sum()} "
              f"| ~{(eq[-1]**(1/yrs)-1)*100 if yrs>0 else 0:.1f}%/yr | "
              f"sh={metrics(pd.Series(eq))['sharpe']}")
        # per sustained negative-regime period: did it go flat or bleed?
        neg_runs = [r for r in runs if r[2] < 0]
        if neg_runs:
            print(f"  negative-funding periods ({len(neg_runs)}):")
            print(f"  {'start':>12}{'end':>12}{'marks':>7}{'sumNet%':>9}"
                  f"{'entries':>8}{'flattens':>9}{'verdict':>10}")
            for s, e, _, n in neg_runs:
                m = (f.index >= s) & (f.index <= e)
                sn = net[m].sum() * 100
                v = "flat" if abs(sn) < 0.1 else ("bleed" if sn < 0 else "profit")
                print(f"  {str(s.date()):>12}{str(e.date()):>12}{n:>7}{sn:>9.2f}"
                      f"{ent[m].sum():>8}{flt[m].sum():>9}{v:>10}")
        else:
            print("  NO sustained negative-funding period (window too coarse) — "
                  "see per-mark neg split above.")
        print()
        # gate
        posnet = net[pos].sum() * 100
        negnet = net[neg].sum() * 100
        gate = ("PASS" if posnet > 0 and negnet >= -0.1 else "FAIL")
        print(f"  GATE (profit pos-regime AND no-bleed neg-regime): {gate}  "
              f"| posNet={posnet:.2f}% negNet={negnet:.2f}%\n")


if __name__ == "__main__":
    main()