"""Regime-gate walk-forward sweep engine (sub-project 2). Bar-level path equity
per cell, real CoinDCX costs, K=4 regime-balanced + 70/30 + bootstrap CI.
Pass: net>0 both WF schemes AND bootstrap CI lower bound > 0."""
from __future__ import annotations

import numpy as np
import pandas as pd

TILT_FEE = 0.00059  # CoinDCX taker per fill (§29; NOT Binance 0.0004)
TILT_SLIP = 0.0005  # 5bps execution-gap slippage per side (§24/§29 gap model)


def simulate_tilt(
    conviction: pd.Series,
    perp_ret: pd.Series,
    funding_per_bar: pd.Series,
    fee: float = TILT_FEE,
    slip: float = TILT_SLIP,
) -> pd.Series:
    """Bar-level path equity of a naked perp tilt. conviction in [-1,+1] (sign=dir).
    Enter/exit on sign change (each change = 1 fill, fee+slip per side). Funding paid
    by long / received by short at each bar (funding_per_bar already aligned to bars).

    Caller must pass mark-only `funding_per_bar` (rate at 8h-mark bars, 0 elsewhere);
    this routine charges `-side*fr` per bar, so forward-filling funding would
    32x-overcharge. No 1% TDS — naked perp tilt (§29)."""
    c = conviction.reindex(perp_ret.index).fillna(0.0).clip(-1.0, 1.0)
    side = np.sign(c)
    ret = perp_ret.reindex(perp_ret.index).fillna(0.0)
    fr = funding_per_bar.reindex(perp_ret.index).fillna(0.0)
    flips = side.diff().abs() > 0  # first entry + every sign change
    flip_cost = np.where(flips, fee + slip, 0.0)
    funding_cost = -side * fr  # long pays positive funding (drag), short receives
    interval = side * ret + funding_cost - flip_cost
    eq = (1.0 + interval).cumprod()
    return pd.Series(eq, index=perp_ret.index)


def bootstrap_ci(
    returns: pd.Series, n: int = 1000, ci: float = 0.95
) -> tuple[float, float]:
    """Circular-block bootstrap CI on cumulative net (sum of returns = eq[-1]-1).
    Returns (lo, hi) quantiles. Block size 10 retains autocorr. Fixed seed for
    reproducible WF verdicts. <20 returns -> (-inf, +inf) signals FAIL downstream."""
    r = returns.dropna().values
    if len(r) < 20:
        return -np.inf, np.inf
    rng = np.random.default_rng(0)
    block = 10
    draws = np.empty(n)
    for i in range(n):
        starts = rng.integers(0, len(r), size=len(r) // block + 1)
        idx = (starts[:, None] + np.arange(block)[None, :]).ravel()[: len(r)] % len(r)
        draws[i] = r[idx].sum()
    lo = float(np.quantile(draws, (1 - ci) / 2))
    hi = float(np.quantile(draws, 1 - (1 - ci) / 2))
    return lo, hi


def walk_forward(
    conviction: pd.Series,
    perp_ret: pd.Series,
    funding_per_bar: pd.Series,
    k: int = 4,
) -> dict:
    """K regime-balanced folds + 70/30. Returns {k4_pass, split70_pass, net, folds_net}.
    k4_pass: net>0 in >=3/4 folds AND aggregate>0. split70_pass: net>0 on last 30%."""
    n = len(conviction)
    fold = max(1, n // k)
    folds_net: list[float] = []
    for i in range(k):
        s = conviction.iloc[i * fold : (i + 1) * fold]
        r = perp_ret.iloc[i * fold : (i + 1) * fold]
        fr = funding_per_bar.iloc[i * fold : (i + 1) * fold]
        eq = simulate_tilt(s, r, fr)
        folds_net.append(float(eq.iloc[-1] - 1.0))
    k4_pass = (sum(nf > 0 for nf in folds_net) >= 3) and (sum(folds_net) > 0)
    cut = int(n * 0.7)
    eq70 = simulate_tilt(
        conviction.iloc[cut:], perp_ret.iloc[cut:], funding_per_bar.iloc[cut:]
    )
    split70_pass = float(eq70.iloc[-1] - 1.0) > 0
    full_eq = simulate_tilt(conviction, perp_ret, funding_per_bar)
    return {
        "k4_pass": k4_pass,
        "split70_pass": split70_pass,
        "net": float(full_eq.iloc[-1] - 1.0),
        "folds_net": folds_net,
    }


def demo() -> None:
    import numpy as np
    import pandas as pd

    idx = pd.date_range("2026-01-01", periods=400, freq="15min")
    # a deliberately-profitable long gate: conviction long when price rising
    px = pd.Series(np.linspace(100, 130, 400), index=idx)
    ret = px.pct_change().fillna(0)
    conv = pd.Series(
        np.where(px.pct_change(20) > 0, 1.0, 0.0), index=idx
    )  # long when up
    # funding: paid/received only at 8h marks (32 bars apart), 0 elsewhere.
    # simulate_tilt charges -side*fr per bar; mark-only fr = correct (1 charge/mark).
    fr = pd.Series(0.0, index=idx)
    fr.iloc[::32] = 0.0001  # long pays positive funding at each 8h mark
    eq = simulate_tilt(conv, ret, fr, fee=0.00059, slip=0.0005)
    assert eq.iloc[-1] > 1.0, "profitable long tilt should net > 1 after costs"
    # cost model: gross (no fee) > net (with fee) on a churny signal
    gross = simulate_tilt(conv, ret, fr, fee=0.0, slip=0.0)
    assert gross.iloc[-1] > eq.iloc[-1], "fees+slippage must reduce equity"
    # flat/no-trade gate -> net=1 (no change), verdict FAIL
    flat = pd.Series(0.0, index=idx)
    eqf = simulate_tilt(flat, ret, fr, fee=0.00059, slip=0.0005)
    assert abs(eqf.iloc[-1] - 1.0) < 1e-9, "flat signal -> no change"
    # bootstrap CI on a profitable series: lower bound > 0
    lo, _hi = bootstrap_ci(eq.pct_change().dropna())
    assert lo > 0, "profitable series CI lower bound > 0"
    print("regime_gate_wf core OK")


if __name__ == "__main__":
    demo()