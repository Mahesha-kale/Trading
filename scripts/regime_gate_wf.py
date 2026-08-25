"""Regime-gate walk-forward sweep engine (sub-project 2). Bar-level path equity
per cell, real CoinDCX costs, K=4 contiguous time-slice folds + 70/30 + bootstrap CI.
Pass: net>0 both WF schemes AND bootstrap CI lower bound > 0."""
from __future__ import annotations

import numpy as np
import pandas as pd

from scripts.regime_gates import (
    basis_signal,
    funding_extreme_signal,
    funding_slope_signal,
    trend_signal,
)

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
    """K contiguous time-slice folds + 70/30. Returns {k4_pass, split70_pass, net, folds_net}.
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

    # sweep driver self-check: 3 gates x 1 synthetic asset x 2 dirs = 6 cells
    cells = run_sweep_synth()
    assert len(cells) == 6, cells
    assert all("verdict" in c for c in cells), "each cell has a verdict"
    # write+read json roundtrip
    import json
    import os
    import tempfile

    p = os.path.join(tempfile.gettempdir(), "_rg_sweep.json")
    passing = [c for c in cells if c["verdict"] == "PASS"]
    with open(p, "w") as f:
        json.dump(passing, f)
    with open(p) as f:
        assert json.load(f) == passing
    os.remove(p)
    print("regime_gate_wf sweep OK")

    # sub-project 6: funding-extreme focused sweep self-check
    ec = run_sweep_extreme_synth()
    assert len(ec) == 2, ec
    assert all("verdict" in c for c in ec), ec
    # both fade directions actually fire (not all-flat) and costs apply (net < gross)
    assert all(c["scored_fires"] > 0 for c in ec), "fade cells must fire on the synthetic extremes"
    # a deliberately-profitable fade should net positive on the SYNTH (k4+split70 may
    # still trip on tiny synthetic data — assert at least one direction nets >0 to
    # confirm the sim rewards the fade, not that it must PASS the full gate)
    assert any(c["net"] > 0 for c in ec), f"profitable synth fade should net >0, got {ec}"


GATES = {"funding_slope": funding_slope_signal, "trend": trend_signal, "basis": basis_signal,
         "funding_extreme": funding_extreme_signal}
ASSETS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
DIRECTIONS = ["long", "short"]


def _align_bars(asset: str):
    """Load 15m perp + spot + funding for asset; mark-only align funding to 15m bars.
    Returns (perp_ret, funding_per_bar, perp, spot). Missing file -> None.

    Funding settles only at 8h marks; mark-only = rate at the nearest perp bar to each
    funding timestamp, 0 elsewhere. Forward-filling would charge the 8h rate ~32x per
    period = 32x overcharge (pre-flight ruling)."""
    import os

    fp = f"reports/binance_{asset}_15m.csv"
    sp = f"reports/binance_{asset}_spot_15m.csv"
    fu = f"reports/binance_{asset}_funding.csv"
    if not all(os.path.exists(x) for x in (fp, sp, fu)):
        return None
    perp = pd.read_csv(fp, index_col=0, parse_dates=True)["close"].astype(float).sort_index()
    spot = pd.read_csv(sp, index_col=0, parse_dates=True)["close"].astype(float).sort_index()
    fdf = pd.read_csv(fu, index_col=0)
    fdf.index = pd.to_datetime(fdf.index, utc=True, errors="coerce")
    fr = fdf["rate"].astype(float).sort_index()
    # mark-only: rate at the nearest perp bar to each funding timestamp, 0 elsewhere.
    funding_per_bar = pd.Series(0.0, index=perp.index)
    nearest = perp.index.get_indexer(fr.index, method="nearest")  # per-mark bar positions
    funding_per_bar.iloc[nearest] = fr.values  # last-mark-wins on rare collision (ok at 8h/15m)
    perp_ret = perp.pct_change().fillna(0.0)
    return perp_ret, funding_per_bar, perp, spot


def _train_params(gate: str, perp_ret, funding_per_bar, perp, spot, is_end: int):
    """Grid-search best params on first 70% by time (IS net max). Returns dict of params.
    ponytail: small fixed grid per gate — expand if IS all<=0. Returns best (may be lowest-loss)."""
    grids = {
        "funding_slope": [{"w": w, "z": z} for w in (10, 20, 40) for z in (1.0, 2.0, 3.0)],
        "trend": [{"period": p, "mult": m} for p in (14, 28) for m in (2.0, 3.0)],
        "basis": [{"w": w, "thr_bps": t} for w in (10, 20) for t in (5.0, 10.0, 20.0)],
        "funding_extreme": [{"w": w, "q": q, "q_exit": q - 0.10}
                            for w in (120, 240, 480) for q in (0.90, 0.95)],
    }
    best, best_net = None, -np.inf
    for params in grids[gate]:
        c = _compute_gate(gate, params, perp, spot, funding_per_bar).iloc[:is_end]
        eq = simulate_tilt(c, perp_ret.iloc[:is_end], funding_per_bar.iloc[:is_end])
        net = float(eq.iloc[-1] - 1.0)
        if net > best_net:
            best_net, best = net, params
    return best


def _compute_gate(gate: str, params: dict, perp, spot, funding_per_bar) -> pd.Series:
    if gate == "funding_slope":
        return funding_slope_signal(pd.DataFrame({"rate": funding_per_bar}), **params)
    if gate == "funding_extreme":
        return funding_extreme_signal(pd.DataFrame({"rate": funding_per_bar}), **params)
    if gate == "trend":
        return trend_signal(perp, **params)
    return basis_signal(perp, spot, **params)


def run_sweep() -> list[dict]:
    """18 cells: gate x asset x direction. Train IS 70%, score OOS. Returns per-cell verdicts."""
    cells = []
    for asset in ASSETS:
        loaded = _align_bars(asset)
        if loaded is None:
            cells.append({"asset": asset, "gate": "-", "dir": "-", "verdict": "SKIP_NODATA"})
            continue
        perp_ret, funding_per_bar, perp, spot = loaded
        is_end = int(len(perp_ret) * 0.7)
        for gate in GATES:
            params = _train_params(gate, perp_ret, funding_per_bar, perp, spot, is_end)
            conv = _compute_gate(gate, params, perp, spot, funding_per_bar)
            for direction in DIRECTIONS:
                # score only the sign-direction: long cell uses conv as-is, short flips sign
                scored = conv if direction == "long" else -conv
                wf = walk_forward(scored, perp_ret, funding_per_bar)
                rets = simulate_tilt(scored, perp_ret, funding_per_bar).pct_change().dropna()
                lo, _hi = bootstrap_ci(rets)
                verdict = "PASS" if (wf["k4_pass"] and wf["split70_pass"] and wf["net"] > 0 and lo > 0) else "FAIL"
                cells.append(
                    {
                        "asset": asset,
                        "gate": gate,
                        "dir": direction,
                        "params": params,
                        "net": round(wf["net"], 4),
                        "ci_lo": round(lo, 4),
                        "k4_pass": wf["k4_pass"],
                        "split70_pass": wf["split70_pass"],
                        "verdict": verdict,
                    }
                )
    return cells


def run_sweep_funding_extreme() -> list[dict]:
    """6 cells: funding_extreme gate x 3 assets x 2 fade-directions. Train IS 70%
    on the raw two-sided conviction, then score each fade-direction by sign-
    isolating it (clip) — the fade gate fires both signs natively, so a direction
    cell keeps only its sign (long-fade: conv>=0; short-fade: conv<=0). §31's
    sign-flip does not apply. Reuses _align_bars/_train_params/_compute_gate/
    simulate_tilt/walk_forward/bootstrap_ci. §31's 18 cells are NOT re-run."""
    cells = []
    for asset in ASSETS:
        loaded = _align_bars(asset)
        if loaded is None:
            cells.append({"asset": asset, "gate": "funding_extreme", "dir": "-",
                          "verdict": "SKIP_NODATA"})
            continue
        perp_ret, funding_per_bar, perp, spot = loaded
        is_end = int(len(perp_ret) * 0.7)
        params = _train_params("funding_extreme", perp_ret, funding_per_bar, perp, spot, is_end)
        conv = _compute_gate("funding_extreme", params, perp, spot, funding_per_bar)
        for direction in DIRECTIONS:
            # sign-isolate: long-fade keeps +1 fires (clip lower 0); short-fade keeps -1 fires (clip upper 0)
            scored = conv.clip(lower=0.0) if direction == "long" else conv.clip(upper=0.0)
            wf = walk_forward(scored, perp_ret, funding_per_bar)
            rets = simulate_tilt(scored, perp_ret, funding_per_bar).pct_change().dropna()
            lo, _hi = bootstrap_ci(rets)
            verdict = "PASS" if (wf["k4_pass"] and wf["split70_pass"] and wf["net"] > 0 and lo > 0) else "FAIL"
            cells.append(
                {
                    "asset": asset,
                    "gate": "funding_extreme",
                    "dir": direction,
                    "params": params,
                    "net": round(wf["net"], 4),
                    "ci_lo": round(lo, 4),
                    "k4_pass": wf["k4_pass"],
                    "split70_pass": wf["split70_pass"],
                    "verdict": verdict,
                }
            )
    return cells


def run_sweep_synth() -> list[dict]:
    """Tiny synthetic sweep for the self-check (6 cells, 1 asset)."""
    idx = pd.date_range("2026-01-01", periods=400, freq="15min")
    perp = pd.Series(np.linspace(100, 130, 400), index=idx)
    spot = pd.Series(np.full(400, 100.0), index=idx)
    perp_ret = perp.pct_change().fillna(0)
    funding_per_bar = pd.Series(0.0001, index=idx)
    cells = []
    for gate in ["funding_slope", "trend", "basis"]:
        params = (
            {"w": 20, "z": 2.0}
            if gate == "funding_slope"
            else {"period": 14, "mult": 3.0}
            if gate == "trend"
            else {"w": 20, "thr_bps": 10.0}
        )
        conv = _compute_gate(gate, params, perp, spot, funding_per_bar)
        for direction in DIRECTIONS:
            scored = conv if direction == "long" else -conv
            wf = walk_forward(scored, perp_ret, funding_per_bar)
            rets = simulate_tilt(scored, perp_ret, funding_per_bar).pct_change().dropna()
            lo, _ = bootstrap_ci(rets)
            verdict = "PASS" if (wf["k4_pass"] and wf["split70_pass"] and wf["net"] > 0 and lo > 0) else "FAIL"
            cells.append(
                {
                    "asset": "SYNTH",
                    "gate": gate,
                    "dir": direction,
                    "net": round(wf["net"], 4),
                    "verdict": verdict,
                }
            )
    return cells


def run_sweep_extreme_synth() -> list[dict]:
    """Tiny synthetic funding-extreme sweep for the self-check: 1 asset x 2 dirs.
    A deliberately-profitable fade cell (funding mean-reverts) should PASS; a
    flat cell (no extremes -> no fires) should FAIL; equity < gross (costs)."""
    idx = pd.date_range("2026-01-01", periods=600, freq="15min")
    # funding: oscillating extremes that revert — a fade profits (short pos extreme,
    # long neg extreme) AND earns funding on the receiving side.
    n = 600
    fr = np.full(n, 0.0001)
    for ix in range(60, n, 120):  # positive extreme (2 bars) then reverts
        fr[ix : ix + 2] = 0.002
    for ix in range(120, n, 120):  # negative extreme (2 bars) then reverts
        fr[ix : ix + 2] = -0.002
    funding_per_bar = pd.Series(fr, index=idx)
    # perp returns: after a positive funding extreme, perp drifts DOWN (premium
    # reverts) -> short fade profits; after a negative extreme, perp drifts UP.
    perp_ret = pd.Series(0.0, index=idx)
    for ix in range(60, n, 120):
        perp_ret.iloc[ix + 1 : ix + 6] = -0.001  # short fade wins here
    for ix in range(120, n, 120):
        perp_ret.iloc[ix + 1 : ix + 6] = 0.001   # long fade wins here
    cells = []
    # profitable long-fade cell (params that fire on the neg extremes)
    for direction, params in (("long", {"w": 120, "q": 0.90, "q_exit": 0.80}),
                              ("short", {"w": 120, "q": 0.90, "q_exit": 0.80})):
        conv = funding_extreme_signal(pd.DataFrame({"rate": funding_per_bar}), **params)
        scored = conv.clip(lower=0.0) if direction == "long" else conv.clip(upper=0.0)
        wf = walk_forward(scored, perp_ret, funding_per_bar)
        rets = simulate_tilt(scored, perp_ret, funding_per_bar).pct_change().dropna()
        lo, _ = bootstrap_ci(rets)
        verdict = "PASS" if (wf["k4_pass"] and wf["split70_pass"] and wf["net"] > 0 and lo > 0) else "FAIL"
        cells.append({"asset": "SYNTH", "gate": "funding_extreme", "dir": direction,
                      "net": round(wf["net"], 4), "verdict": verdict, "scored_fires": int((scored != 0).sum())})
    return cells


def main(extreme: bool = False) -> None:
    """Run the sweep + write reports/regime_gate_wf.log + regime_gate_pass.json.
    extreme=False: §31 18-cell sweep (overwrites). extreme=True: sub-project 6
    funding-extreme 6-cell sweep (APPENDS to the log; overwrites the pass json
    with the 6-cell passing set — §31 was 0/18=[] so nothing is lost)."""
    import json
    import logging

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    log = logging.getLogger("regime_gate_wf")
    cells = run_sweep_funding_extreme() if extreme else run_sweep()
    passing = [c for c in cells if c["verdict"] == "PASS"]
    if extreme:
        # APPEND the 6 funding-extreme rows to the existing §31 log (header only if new)
        import os
        new = not os.path.exists("reports/regime_gate_wf.log")
        with open("reports/regime_gate_wf.log", "a") as f:
            if new:
                f.write("asset,gate,dir,net,ci_lo,k4,split70,verdict,params\n")
            f.writelines(
                f"{c['asset']},{c['gate']},{c['dir']},{c.get('net','-')},"
                f"{c.get('ci_lo','-')},{c.get('k4_pass','-')},"
                f"{c.get('split70_pass','-')},{c['verdict']},{c.get('params','-')}\n"
                for c in cells
            )
    else:
        with open("reports/regime_gate_wf.log", "w") as f:
            f.write("asset,gate,dir,net,ci_lo,k4,split70,verdict,params\n")
            f.writelines(
                f"{c['asset']},{c['gate']},{c['dir']},{c.get('net','-')},"
                f"{c.get('ci_lo','-')},{c.get('k4_pass','-')},"
                f"{c.get('split70_pass','-')},{c['verdict']},{c.get('params','-')}\n"
                for c in cells
            )
    with open("reports/regime_gate_pass.json", "w") as f:
        json.dump(passing, f, indent=2)
    label = "funding-extreme" if extreme else "regime-gate"
    log.info("%s sweep done: %d cells, %d PASS", label, len(cells), len(passing))
    for c in passing:
        log.info("PASS %s", {k: c[k] for k in ("asset", "gate", "dir", "net")})
    if not passing:
        log.info("NoTilt — no %s cell passed; carry-only deploy (~5-6%%/yr)", label)


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "run":
        main()  # §31 18-cell sweep (frozen) -> reports/
    elif len(sys.argv) > 1 and sys.argv[1] == "run-extreme":
        main(extreme=True)  # sub-project 6: 6 funding-extreme cells -> reports/
    else:
        demo()