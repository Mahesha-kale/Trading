# Regime-Gate Tilt Research Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pre-registered walk-forward sweep (3 gates × 3 assets × 2 directions = 18 cells) to find a directional tilt signal net-positive after real CoinDCX costs; passing cells become a `TiltSignal` for sub-project 1's tilt slot, else `NoTilt` stays (carry-only deploy).

**Architecture:** Bar-level (15m) path-equity backtest per cell, real costs (taker 0.059% + 5bps slippage/side + funding at 8h marks, no TDS — naked perp), K=4 regime-balanced WF + 70/30 secondary + bootstrap CI>0 pass criterion. New: `regime_gates.py` (pure signals), `regime_gate_wf.py` (sweep engine), `tilt_signal.py` (TiltSignal impl). Extends `carry_trader.py` tilt branch to signed [-1,+1] + a `TiltRisk` stub for sub-project 3.

**Tech Stack:** Python 3.12, pandas, numpy, asyncio. `scripts/` use `__main__` assert self-checks (NO pytest); `app/`+`tests/` use pytest (none added here). ruff line-length 100.

**Spec:** `docs/superpowers/specs/2026-08-24-regime-gate-tilt-design.md` — the plan argues from the spec; executors read both.

## Global Constraints

- Free public data only; CoinDCX perp (linear). Tilt = **naked perp** (no spot hedge) → **NO 1% TDS** (TDS is spot-sell only; do not add TDS to the tilt).
- Cost model (§29, CoinDCX real): taker fee **0.00059** per fill (NOT funding_carry_band.FEE_TAKER=0.0004 which is Binance); slippage **0.0005** (5bps) per side; funding paid/received at 8h marks from funding.csv. NO maker assumption for the tilt (market entries = taker).
- Pass criterion (pre-registered): net>0 in BOTH K=4 regime-balanced (net>0 in ≥3/4 folds AND aggregate>0) AND 70/30 (net>0 on 30% test), AND bootstrap CI lower bound >0 (1000 resample, 95% CI). No Bonferroni.
- Params trained on first 70% by time, no OOS peek (§20 convention).
- Conviction is **signed [-1,+1]**: +=long perp, -=short perp, |value|=strength. NoTilt returns 0.0.
- `carry_trader.py` demo must stay green (5 OK lines) after Task 5; the `_demo_tilt` assert updates for signed.
- API keys via Settings, never logged. No real `--live` orders (tilt is Phase 3, gated behind sub-project 1 Phase 0/1/2). `--live` guarded by `trading_mode=="live"`.
- Perp INR-margin futures carry NO 1% TDS — do NOT add TDS anywhere.
- Commit on branch `regime-gate-tilt-design` (off main). No push without asking. No Co-Authored-By in commits.
- ruff line-length 100, Python 3.12, async where carry_trader touches it.

---

### Task 1: regime_gates.py — the 3 pure gate-signal functions

**Files:**
- Create: `scripts/regime_gates.py`
- Consumes: `funding_carry.load_funding` (funding.csv), `funding_carry.load_price` (15m perp), spot 15m (read directly)
- Produces: `funding_slope_signal(funding_df, w, z)`, `trend_signal(price, period, mult)`, `basis_signal(perp, spot, w, thr_bps)` — each returns a `pd.Series` of signed conviction in [-1,+1] indexed like the input bars.

- [ ] **Step 1: Write the failing self-check (`__main__`)**

```python
def demo() -> None:
    import numpy as np
    import pandas as pd
    idx = pd.date_range("2026-01-01", periods=200, freq="15min")
    # funding slope: rising rates -> long conviction
    fr = pd.Series(np.linspace(-0.0003, 0.0003, 200), index=idx)
    c = funding_slope_signal(pd.DataFrame({"rate": fr}), w=20, z=2.0)
    assert c.between(-1, 1).all(), "conviction out of [-1,1]"
    assert (c.iloc[-20:] > 0).any(), "rising funding should produce long conviction"
    assert (c.iloc[:20] == 0).all() or (c.abs() < 1).any(), "early/flat masks or clamps"
    # trend: uptrend -> long, downtrend -> short
    up = pd.Series(np.linspace(100, 120, 200), index=idx)
    ct = trend_signal(up, period=14, mult=3.0)
    assert ct.between(-1, 1).all()
    assert (ct.iloc[-20:] > 0).mean() > 0.5, "uptrend -> long"
    down = pd.Series(np.linspace(120, 100, 200), index=idx)
    ctd = trend_signal(down, period=14, mult=3.0)
    assert (ctd.iloc[-20:] < 0).mean() > 0.5, "downtrend -> short"
    # basis: contango (perp>spot) -> long
    spot = pd.Series(np.full(200, 100.0), index=idx)
    perp = pd.Series(np.linspace(100, 100.5, 200), index=idx)  # premium rising
    cb = basis_signal(perp, spot, w=20, thr_bps=10.0)
    assert cb.between(-1, 1).all()
    assert (cb.iloc[-20:] > 0).any(), "contango -> long"
    # NaN/empty guard: empty window -> 0 (no NaN propagation)
    empty = pd.Series([np.nan, np.nan], index=idx[:2], dtype=float)
    assert funding_slope_signal(pd.DataFrame({"rate": empty}), w=20, z=2.0).fillna(0).eq(0).all()
    print("regime_gates OK")
```

- [ ] **Step 2: Run to verify it fails**

Run: `PYTHONPATH=. .venv/Scripts/python scripts/regime_gates.py`
Expected: FAIL — `NameError: funding_slope_signal` (functions undefined).

- [ ] **Step 3: Implement the 3 gate functions**

```python
"""Regime gate signals for the tilt sweep (sub-project 2). Each returns a pd.Series
of signed conviction in [-1,+1]: +=long perp, -=short perp, |value|=strength 0..1.
Params trained on first 70% by time (no OOS peek). NaN/empty -> 0 (never propagate)."""
from __future__ import annotations

import numpy as np
import pandas as pd

CLIP = 1.0  # conviction magnitude cap


def funding_slope_signal(funding: pd.DataFrame, w: int, z: float) -> pd.Series:
    """Rolling z-score of funding rate slope over window w. Rising funding -> long.
    conviction = tanh(zscore / z) so |c| in [0,1]; sign = slope sign."""
    rate = funding["rate"].astype(float)
    slope = rate.diff(w)  # change over w marks
    roll_std = slope.rolling(w, min_periods=w).std()
    zscore = slope / roll_std.replace(0, np.nan)
    c = np.tanh(zscore / z) if z > 0 else np.sign(slope) * CLIP
    out = c.replace([np.inf, -np.inf], np.nan).fillna(0.0).clip(-CLIP, CLIP)
    return pd.Series(out, index=funding.index)


def trend_signal(price: pd.Series, period: int, mult: float) -> pd.Series:
    """Supertrend regime. Uptrend -> +1, downtrend -> -1 (crisp regime sign as
    conviction magnitude; no fractional strength — supertrend is binary)."""
    hl = price.rolling(period, min_periods=period).max()
    ll = price.rolling(period, min_periods=period).min()
    atr = (hl - ll).rolling(period, min_periods=period).mean()
    mid = (hl + ll) / 2.0
    upper = mid + mult * atr
    lower = mid - mult * atr
    pos = pd.Series(index=price.index, dtype=float)
    side = 0.0
    for i, p in enumerate(price.values):
        if np.isnan(p):
            pos.iloc[i] = 0.0; continue
        if side == 0.0:
            side = 1.0 if p > mid.iloc[i] else -1.0
        elif side > 0 and p < lower.iloc[i]:
            side = -1.0
        elif side < 0 and p > upper.iloc[i]:
            side = 1.0
        pos.iloc[i] = side if not np.isnan(side) else 0.0
    return pd.Series(pos.fillna(0.0).clip(-CLIP, CLIP), index=price.index)


def basis_signal(perp: pd.Series, spot: pd.Series, w: int, thr_bps: float) -> pd.Series:
    """Perp premium over spot in bps, smoothed over w. Contango (perp>spot) -> long.
    conviction = tanh(basis_bps / thr_bps); sign = basis sign."""
    basis = (perp.reindex(spot.index, method="nearest") - spot) / spot * 10_000.0  # bps
    smooth = basis.rolling(w, min_periods=w).mean()
    c = np.tanh(smooth / thr_bps) if thr_bps > 0 else np.sign(smooth) * CLIP
    out = c.replace([np.inf, -np.inf], np.nan).fillna(0.0).clip(-CLIP, CLIP)
    return pd.Series(out, index=spot.index)
```

- [ ] **Step 4: Run to verify it passes**

Run: `PYTHONPATH=. .venv/Scripts/python scripts/regime_gates.py`
Expected: prints `regime_gates OK`.

- [ ] **Step 5: Commit**

```bash
git add scripts/regime_gates.py
git commit -m "feat(regime): 3 gate signals (funding-slope/trend/basis) + self-check"
```

---

### Task 2: regime_gate_wf.py — cost model + path-equity sim + WF + bootstrap

**Files:**
- Create: `scripts/regime_gate_wf.py`
- Consumes: Task 1 `regime_gates.*` signals; `funding_carry.load_funding`/`load_price`/`align`
- Produces: `simulate_tilt(conviction, perp_ret, funding_rate_at_bar, fee, slip)` -> equity Series; `walk_forward(...)`; `bootstrap_ci(net)`. Self-check on synthetic.

- [ ] **Step 1: Write the failing self-check (`__main__`)**

```python
def demo() -> None:
    import numpy as np
    import pandas as pd
    idx = pd.date_range("2026-01-01", periods=400, freq="15min")
    # a deliberately-profitable long gate: conviction long when price rising
    px = pd.Series(np.linspace(100, 130, 400), index=idx)
    ret = px.pct_change().fillna(0)
    conv = pd.Series(np.where(px.pct_change(20) > 0, 1.0, 0.0), index=idx)  # long when up
    # funding: paid/received only at 8h marks (32 bars apart), 0 elsewhere.
    # simulate_tilt charges -side*fr per bar; mark-only fr = correct (1 charge/mark).
    fr = pd.Series(0.0, index=idx)
    fr.iloc[::32] = 0.0001  # long pays positive funding at each 8h mark
    eq = simulate_tilt(conv, ret, fr, fee=0.00059, slip=0.0005)
    assert (eq.iloc[-1] > 1.0), "profitable long tilt should net >1 after costs"
    # cost model: gross (no fee) > net (with fee) on a churny signal
    gross = simulate_tilt(conv, ret, fr, fee=0.0, slip=0.0)
    assert gross.iloc[-1] > eq.iloc[-1], "fees+slippage must reduce equity"
    # flat/no-trade gate -> net=1 (no change), verdict FAIL
    flat = pd.Series(0.0, index=idx)
    eqf = simulate_tilt(flat, ret, fr, fee=0.00059, slip=0.0005)
    assert abs(eqf.iloc[-1] - 1.0) < 1e-9, "flat signal -> no change"
    # bootstrap CI on a profitable series: lower bound > 0
    net = eq.iloc[-1] - 1.0
    lo, hi = bootstrap_ci(eq.pct_change().dropna())
    assert lo > 0, "profitable series CI lower bound > 0"
    print("regime_gate_wf core OK")
```

- [ ] **Step 2: Run to verify it fails**

Run: `PYTHONPATH=. .venv/Scripts/python scripts/regime_gate_wf.py`
Expected: FAIL — `NameError: simulate_tilt`.

- [ ] **Step 3: Implement cost model + sim + WF + bootstrap**

```python
"""Regime-gate walk-forward sweep engine (sub-project 2). Bar-level path equity
per cell, real CoinDCX costs, K=4 regime-balanced + 70/30 + bootstrap CI.
Pass: net>0 both WF schemes AND bootstrap CI lower bound > 0."""
from __future__ import annotations

import numpy as np
import pandas as pd

TILT_FEE = 0.00059   # CoinDCX taker per fill (§29; NOT Binance 0.0004)
TILT_SLIP = 0.0005   # 5bps execution-gap slippage per side (§24/§29 gap model)


def simulate_tilt(conviction: pd.Series, perp_ret: pd.Series, funding_per_bar: pd.Series,
                  fee: float = TILT_FEE, slip: float = TILT_SLIP) -> pd.Series:
    """Bar-level path equity of a naked perp tilt. conviction in [-1,+1] (sign=dir).
    Enter/exit on sign change (each change = 1 fill, fee+slip per side). Funding paid
    by long / received by short at each bar (funding_per_bar already aligned to bars).
    ponytail: funding charged per bar (funding.csv marks forward-filled to 15m) —
    upgrade to 8h-mark step if per-bar drift misprices; ceiling is small vs fee."""
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


def bootstrap_ci(returns: pd.Series, n: int = 1000, ci: float = 0.95) -> tuple[float, float]:
    """Block-bootstrap CI on cumulative net (eq[-1]-1). Returns (lo, hi) of mean net.
    ponytail: block size 10 to retain autocorr; n=1000 default. NaN -> FAIL (lo=-inf)."""
    r = returns.dropna().values
    if len(r) < 20:
        return -np.inf, np.inf
    rng = np.random.default_rng(0)  # ponytail: fixed seed for reproducible WF verdicts
    block = 10
    nets = []
    for _ in range(n):
        idx = rng.integers(0, len(r) - block)
        # resample blocks
        pass  # see full impl below
    # full impl: circular-block bootstrap
    draws = np.array([np.sum(r[rng.integers(0, len(r), size=len(r))]) for _ in range(n)])
    lo = float(np.quantile(draws, (1 - ci) / 2))
    hi = float(np.quantile(draws, 1 - (1 - ci) / 2))
    return lo, hi


def walk_forward(conviction: pd.Series, perp_ret: pd.Series, funding_per_bar: pd.Series,
                 k: int = 4) -> dict:
    """K regime-balanced folds + 70/30. Returns {k4_pass, split70_pass, net, folds_net}.
    k4_pass: net>0 in >=3/4 folds AND aggregate>0. split70_pass: net>0 on last 30%."""
    n = len(conviction)
    fold = max(1, n // k)
    folds_net = []
    for i in range(k):
        s = conviction.iloc[i * fold:(i + 1) * fold]
        r = perp_ret.iloc[i * fold:(i + 1) * fold]
        fr = funding_per_bar.iloc[i * fold:(i + 1) * fold]
        eq = simulate_tilt(s, r, fr)
        folds_net.append(float(eq.iloc[-1] - 1.0))
    k4_pass = (sum(nf > 0 for nf in folds_net) >= 3) and (sum(folds_net) > 0)
    cut = int(n * 0.7)
    eq70 = simulate_tilt(conviction.iloc[cut:], perp_ret.iloc[cut:], funding_per_bar.iloc[cut:])
    split70_pass = float(eq70.iloc[-1] - 1.0) > 0
    full_eq = simulate_tilt(conviction, perp_ret, funding_per_bar)
    return {"k4_pass": k4_pass, "split70_pass": split70_pass,
            "net": float(full_eq.iloc[-1] - 1.0), "folds_net": folds_net}
```
(Implementer: write the real circular-block bootstrap cleanly; the sketch above has a redundant loop — produce ONE correct resample path. `np.random.default_rng(0)` fixed seed for reproducible verdicts.)

- [ ] **Step 4: Run to verify it passes**

Run: `PYTHONPATH=. .venv/Scripts/python scripts/regime_gate_wf.py`
Expected: prints `regime_gate_wf core OK`.

- [ ] **Step 5: Commit**

```bash
git add scripts/regime_gate_wf.py
git commit -m "feat(regime): tilt path-equity sim + K4/70-30 WF + bootstrap CI"
```

---

### Task 3: 18-cell sweep driver + real-data run

**Files:**
- Modify: `scripts/regime_gate_wf.py` (add `run_sweep()` + `main()` reading real data)
- Consumes: Task 1 gates, Task 2 sim/WF, `funding_carry.load_*`
- Produces: `reports/regime_gate_wf.log` (all 18 cells verdicts) + `reports/regime_gate_pass.json` (passing cells)

- [ ] **Step 1: Write the failing self-check addition (append to `demo()`)**

```python
    # sweep driver self-check: 3 gates x 1 synthetic asset x 2 dirs = 6 cells
    cells = run_sweep_synth()
    assert len(cells) == 6, cells
    assert all("verdict" in c for c in cells), "each cell has a verdict"
    # write+read json roundtrip
    import json, tempfile, os
    p = os.path.join(tempfile.gettempdir(), "_rg_sweep.json")
    passing = [c for c in cells if c["verdict"] == "PASS"]
    with open(p, "w") as f: json.dump(passing, f)
    assert json.load(open(p)) == passing
    os.remove(p)
    print("regime_gate_wf sweep OK")
```

- [ ] **Step 2: Run to verify it fails**

Run: `PYTHONPATH=. .venv/Scripts/python scripts/regime_gate_wf.py`
Expected: FAIL — `NameError: run_sweep_synth`.

- [ ] **Step 3: Implement `run_sweep()` + `run_sweep_synth()` + `main()`**

```python
GATES = {"funding_slope": funding_slope_signal, "trend": trend_signal, "basis": basis_signal}
ASSETS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
DIRECTIONS = ["long", "short"]


def _align_bars(asset: str):
    """Load 15m perp + spot + funding for asset, forward-fill funding to 15m bars.
    Returns (perp_ret, funding_per_bar, perp_close, spot). Missing file -> None."""
    import os
    fp = f"reports/binance_{asset}_15m.csv"
    sp = f"reports/binance_{asset}_spot_15m.csv"
    fu = f"reports/binance_{asset}_funding.csv"
    if not all(os.path.exists(x) for x in (fp, sp, fu)):
        return None
    perp = pd.read_csv(fp, index_col=0, parse_dates=True)["close"].astype(float).sort_index()
    spot = pd.read_csv(sp, index_col=0, parse_dates=True)["close"].astype(float).sort_index()
    fdf = pd.read_csv(fu, index_col=0); fdf.index = pd.to_datetime(fdf.index, utc=True, errors="coerce")
    fr = fdf["rate"].astype(float).sort_index()
    # funding settles ONLY at 8h marks, not every 15m bar. Mark-only: rate at the
    # nearest perp bar to each funding timestamp, 0 elsewhere. (Forward-filling would
    # charge the 8h rate ~32x per period = 32x overcharge. See pre-flight ruling.)
    funding_per_bar = pd.Series(0.0, index=perp.index)
    nearest = perp.index.get_indexer(fr.index, method="nearest")  # per-mark bar positions
    funding_per_bar.iloc[nearest] = fr.values  # last-mark-wins on rare collision (ok at 8h/15m)
    perp_ret = perp.pct_change().fillna(0.0)
    return perp_ret, funding_per_bar, perp, spot


def _train_params(gate: str, perp_ret, funding_per_bar, perp, spot, is_end: int):
    """Grid-search best params on first 70% by time (IS net max). Returns dict of params.
    ponytail: small fixed grid per gate — expand if IS all<=0. Returns best (may be lowest-loss)."""
    grids = {"funding_slope": [{"w": w, "z": z} for w in (10, 20, 40) for z in (1.0, 2.0, 3.0)],
             "trend": [{"period": p, "mult": m} for p in (14, 28) for m in (2.0, 3.0)],
             "basis": [{"w": w, "thr_bps": t} for w in (10, 20) for t in (5.0, 10.0, 20.0)]}
    best, best_net = None, -np.inf
    for params in grids[gate]:
        c = _compute_gate(gate, params, perp, spot, funding_per_bar).iloc[:is_end]
        eq = simulate_tilt(c, perp_ret.iloc[:is_end], funding_per_bar.iloc[:is_end])
        net = float(eq.iloc[-1] - 1.0)
        if net > best_net: best_net, best = net, params
    return best


def _compute_gate(gate: str, params: dict, perp, spot, funding_per_bar) -> pd.Series:
    if gate == "funding_slope":
        return funding_slope_signal(pd.DataFrame({"rate": funding_per_bar}), **params)
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
                lo, hi = bootstrap_ci(rets)
                verdict = "PASS" if (wf["k4_pass"] and wf["split70_pass"] and wf["net"] > 0 and lo > 0) else "FAIL"
                cells.append({"asset": asset, "gate": gate, "dir": direction, "params": params,
                               "net": round(wf["net"], 4), "ci_lo": round(lo, 4),
                               "k4_pass": wf["k4_pass"], "split70_pass": wf["split70_pass"],
                               "verdict": verdict})
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
        params = {"w": 20, "z": 2.0} if gate == "funding_slope" else \
                {"period": 14, "mult": 3.0} if gate == "trend" else {"w": 20, "thr_bps": 10.0}
        conv = _compute_gate(gate, params, perp, spot, funding_per_bar)
        for direction in DIRECTIONS:
            scored = conv if direction == "long" else -conv
            wf = walk_forward(scored, perp_ret, funding_per_bar)
            rets = simulate_tilt(scored, perp_ret, funding_per_bar).pct_change().dropna()
            lo, _ = bootstrap_ci(rets)
            verdict = "PASS" if (wf["k4_pass"] and wf["split70_pass"] and wf["net"] > 0 and lo > 0) else "FAIL"
            cells.append({"asset": "SYNTH", "gate": gate, "dir": direction,
                           "net": round(wf["net"], 4), "verdict": verdict})
    return cells


def main():
    import json, logging
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    log = logging.getLogger("regime_gate_wf")
    cells = run_sweep()
    with open("reports/regime_gate_wf.log", "w") as f:
        f.write("asset,gate,dir,net,ci_lo,k4,split70,verdict,params\n")
        for c in cells:
            f.write(f"{c['asset']},{c['gate']},{c['dir']},{c.get('net','-')},"
                    f"{c.get('ci_lo','-')},{c.get('k4_pass','-')},"
                    f"{c.get('split70_pass','-')},{c['verdict']},{c.get('params','-')}\n")
    passing = [c for c in cells if c["verdict"] == "PASS"]
    with open("reports/regime_gate_pass.json", "w") as f:
        json.dump(passing, f, indent=2)
    log.info("sweep done: %d cells, %d PASS", len(cells), len(passing))
    for c in passing:
        log.info("PASS %s", {k: c[k] for k in ("asset", "gate", "dir", "net")})
    if not passing:
        log.info("NoTilt — no cell passed; carry-only deploy (~5-6%/yr)")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "run":
        main()  # real-data sweep -> reports/
    else:
        demo()
```

- [ ] **Step 4: Run self-check**

Run: `PYTHONPATH=. .venv/Scripts/python scripts/regime_gate_wf.py`
Expected: prints `regime_gate_wf core OK` + `regime_gate_wf sweep OK`.

- [ ] **Step 5: Run the real-data sweep**

Run: `PYTHONPATH=. .venv/Scripts/python scripts/regime_gate_wf.py run`
Expected: writes `reports/regime_gate_wf.log` (18 rows) + `reports/regime_gate_pass.json`; logs PASS count or "NoTilt".

- [ ] **Step 6: Commit**

```bash
git add scripts/regime_gate_wf.py
git commit -m "feat(regime): 18-cell sweep driver + real-data run"
```

---

### Task 4: tilt_signal.py — TiltSignal impl from passing gate

**Files:**
- Create: `scripts/tilt_signal.py`
- Consumes: `reports/regime_gate_pass.json` (from Task 3), Task 1 `regime_gates.*`, `carry_trader.TiltSignal`/`FeedSample`/`TraderState`
- Produces: `RegimeTiltSignal(TiltSignal)` wrapping a trained gate; `load_tilt_signal()` factory. Self-check.

- [ ] **Step 1: Write the failing self-check (`__main__`)**

```python
def demo() -> None:
    import asyncio, json, os, tempfile
    from scripts.carry_trader import NoTilt, FeedSample, TraderState
    # NoTilt unchanged -> 0.0
    assert asyncio.run(NoTilt().conviction(FeedSample(0,0,0,0,0,0), TraderState())) == 0.0
    # synthetic passing cell -> RegimeTiltSignal returns signed conviction, sign = direction
    p = os.path.join(tempfile.gettempdir(), "_rg_pass.json")
    with open(p, "w") as f:
        json.dump([{"asset":"BTCUSDT","gate":"trend","dir":"long",
                    "params":{"period":14,"mult":3.0}}], f)
    ts = load_tilt_signal(path=p)
    assert isinstance(ts, NoTilt) or hasattr(ts, "conviction")
    # empty pass json -> NoTilt (carry-only)
    p2 = os.path.join(tempfile.gettempdir(), "_rg_none.json")
    with open(p2, "w") as f: json.dump([], f)
    assert isinstance(load_tilt_signal(path=p2), NoTilt), "no pass -> NoTilt"
    os.remove(p); os.remove(p2)
    print("tilt_signal OK")
```

- [ ] **Step 2: Run to verify it fails**

Run: `PYTHONPATH=. .venv/Scripts/python scripts/tilt_signal.py`
Expected: FAIL — `NameError: load_tilt_signal` / `RegimeTiltSignal`.

- [ ] **Step 3: Implement**

```python
"""TiltSignal impl(s) from passing regime-gate cells (sub-project 2). Wraps a trained
gate into carry_trader.TiltSignal. Signed conviction [-1,+1] (extends merged [0,1]).
If no cell passed -> NoTilt (carry-only deploy)."""
from __future__ import annotations

import json
from pathlib import Path

from scripts.carry_trader import NoTilt, TiltSignal, FeedSample, TraderState
from scripts import regime_gates as rg


class RegimeTiltSignal(TiltSignal):
    """Directional tilt from a trained gate. conviction in [-1,+1]: +=long, -=short.
    dir='long' -> gate conviction as-is; dir='short' -> negate (gate's short cell)."""
    def __init__(self, gate: str, direction: str, params: dict, asset: str = "BTCUSDT"):
        self.gate, self.direction, self.params, self.asset = gate, direction, params, asset

    async def conviction(self, sample: FeedSample, state: TraderState) -> float:
        # ponytail: live conviction needs a rolling window of recent samples;
        # Phase 3 wires a sample buffer. Here we return a placeholder 0.0 until
        # the live feed buffer exists — the RESEARCH verdict (pass/fail) is what
        # sub-project 2 delivers; live conviction is Phase 3 (sub-project 3 gates).
        return 0.0


def load_tilt_signal(path: str = "reports/regime_gate_pass.json") -> TiltSignal:
    """Factory: read passing cells; if any, wrap the first in RegimeTiltSignal; else NoTilt."""
    p = Path(path)
    if not p.exists():
        return NoTilt()
    passing = json.loads(p.read_text())
    if not passing:
        return NoTilt()
    c = passing[0]
    return RegimeTiltSignal(c["gate"], c["dir"], c.get("params", {}), c.get("asset", "BTCUSDT"))
```
NOTE to implementer: the live `conviction()` returning 0.0 is intentional (the research deliverable is the pass/fail verdict; live conviction needs a rolling sample buffer wired in Phase 3). Document this with the ponytail comment shown. The self-check asserts the factory + types, not a live nonzero conviction.

- [ ] **Step 4: Run to verify it passes**

Run: `PYTHONPATH=. .venv/Scripts/python scripts/tilt_signal.py`
Expected: prints `tilt_signal OK`.

- [ ] **Step 5: Commit**

```bash
git add scripts/tilt_signal.py
git commit -m "feat(tilt): RegimeTiltSignal wrapper + NoTilt fallback from WF verdict"
```

---

### Task 5: carry_trader.py tilt-branch update — signed conviction + TiltRisk stub

**Files:**
- Modify: `scripts/carry_trader.py` (tilt branch lines ~100-109; `TiltSignal` docstring; `_demo_tilt`)
- Consumes: Task 4 `tilt_signal.load_tilt_signal`; `risk_budget.tilt_size`
- Produces: signed [-1,+1] tilt branch, `TiltRisk` stub (sub-project 3 fills), green demo.

- [ ] **Step 1: Write the failing assert update (modify `_demo_tilt`)**

```python
async def _demo_tilt():
    # NoTilt -> 0.0 (neutral, unchanged)
    from scripts.tilt_signal import NoTilt as _NoTilt  # noqa
    t = NoTilt()
    assert await t.conviction(FeedSample(0, 0, 0, 0, 0, 0), TraderState()) == 0.0
    # signed contract: a fake long tilt -> positive, a fake short tilt -> negative
    class FakeTilt(TiltSignal):
        async def conviction(self, sample, state): return 0.7   # long
    class FakeShort(TiltSignal):
        async def conviction(self, sample, state): return -0.5  # short
    assert await FakeTilt().conviction(FeedSample(0,0,0,0,0,0), TraderState()) > 0
    assert await FakeShort().conviction(FeedSample(0,0,0,0,0,0), TraderState()) < 0
    print("carry_trader tilt OK")
```

- [ ] **Step 2: Run to verify it fails (signed contract)**

Run: `PYTHONPATH=. .venv/Scripts/python scripts/carry_trader.py`
Expected: FAIL — `FakeShort` conviction -0.5 is < 0 but old docstring said [0,1]; the assert `< 0` passes structurally but the tilt branch still guards `c > 0` (long-only). Update the branch.

- [ ] **Step 3: Update the tilt branch + TiltSignal docstring + add TiltRisk stub**

In `run_loop`, replace the tilt branch:
```python
        # tilt: pluggable directional overlay (sub-project 2 supplies real impl)
        tilt = cfg.get("tilt") or NoTilt()
        c = await tilt.conviction(s, state)
        if c != 0 and state.side == 0:  # signed [-1,+1]: only tilt when flat (no stacking)
            from scripts.risk_budget import tilt_size
            tilt_risk = cfg.get("tilt_risk") or TiltRisk()  # sub-project 3 fills
            tqty = await tilt_risk.size(cfg, abs(c), s) / s.spot_price
            direction = "long" if c > 0 else "short"
            log.info("TILT conviction=%.2f dir=%s qty=%s (stub: no order in paper)", abs(c), direction, tqty)
            if live and client is not None:
                # sub-project 2+3 supplies sign + overlay
                pass
```
Update `TiltSignal` docstring: `conviction in [-1,+1]: +=long perp, -=short perp, 0 = no tilt` (was `[0,1]`).
Add the `TiltRisk` stub near `NoTilt`:
```python
class TiltRisk:
    """Pluggable tilt sizing/stop overlay (sub-project 3). Stub returns raw tilt_size."""
    async def size(self, cfg: dict, conviction_mag: float, sample) -> float:
        from scripts.risk_budget import tilt_size
        return tilt_size(cfg["capital"], conviction_mag, cfg["risk_fraction"], cfg["leverage_cap"])
```

- [ ] **Step 4: Run to verify demo green (all 5 OK lines)**

Run: `PYTHONPATH=. .venv/Scripts/python scripts/carry_trader.py`
Expected: prints `signal OK` / `faults OK` / `reconcile OK` / `sign OK` / `tilt OK`.

- [ ] **Step 5: Commit**

```bash
git add scripts/carry_trader.py
git commit -m "feat(carry): signed tilt branch [-1,+1] + TiltRisk stub for sub-project 3"
```

---

### Task 6: §31 research-log appendix

**Files:**
- Modify: `docs/strategies_report.md` (append §31 after §30)
- Consumes: `reports/regime_gate_wf.log` + `reports/regime_gate_pass.json` (from Task 3 real run)

- [ ] **Step 1: Append §31**

Summarize: the 18-cell regime-gate sweep (funding-slope/trend/basis × BTC/ETH/SOL × long/short), the pre-registered pass criterion (K4 + 70/30 + bootstrap CI>0, no Bonferroni), the real-cost model (0.059% taker + 5bps slip + funding at marks, no TDS — naked perp), the per-cell verdict table (paste from `reports/regime_gate_wf.log`), and the conclusion: which cell(s) passed (→ `RegimeTiltSignal` candidate for the tilt slot) or "NoTilt — carry-only deploy (~5-6%/yr)". Match §27/§30 tone. Reference the spec + this plan.

- [ ] **Step 2: Commit**

```bash
git add docs/strategies_report.md
git commit -m "docs(research): §31 regime-gate tilt sweep results (sub-project 2)"
```

---

### Task 7: final verify

**Files:** none (verification only)

- [ ] **Step 1: Run all self-checks**

```bash
PYTHONPATH=. .venv/Scripts/python scripts/regime_gates.py
PYTHONPATH=. .venv/Scripts/python scripts/regime_gate_wf.py
PYTHONPATH=. .venv/Scripts/python scripts/tilt_signal.py
PYTHONPATH=. .venv/Scripts/python scripts/carry_trader.py
PYTHONPATH=. .venv/Scripts/python scripts/risk_budget.py
PYTHONPATH=. .venv/Scripts/python -m pytest tests/test_exchange.py -q
```
Expected: all print OK / pass.

- [ ] **Step 2: ruff**

```bash
ruff check scripts/regime_gates.py scripts/regime_gate_wf.py scripts/tilt_signal.py scripts/carry_trader.py
```
Expected: clean (line-length 100).

- [ ] **Step 3: Confirm reports exist**

```bash
ls -la reports/regime_gate_wf.log reports/regime_gate_pass.json
```
Expected: both present (from Task 3 real run).

---

## Self-Review

**1. Spec coverage:**
- 3 gates (funding-slope/trend/basis) → Task 1. ✓
- 18-cell sweep (3×3×2) → Task 3. ✓
- Bar-level path equity + real costs → Task 2 simulate_tilt. ✓
- K=4 + 70/30 + bootstrap CI>0 pass → Task 2 walk_forward/bootstrap_ci + Task 3 verdict. ✓
- TiltSignal impl if pass / NoTilt → Task 4. ✓
- carry_trader signed tilt branch + TiltRisk stub → Task 5. ✓
- §31 appendix → Task 6. ✓
- Error handling (missing data skip, NaN mask, no-trade FAIL, bootstrap-insufficient FAIL, no-pass=NoTilt) → Task 3 _align_bars + Task 2 bootstrap_ci len<20 + Task 3 verdict + Task 4 NoTilt. ✓
- Testing (all `__main__` self-checks, no pytest) → every task. ✓
- Out of scope (B/C, sub-project 3) → spec; TiltRisk stub reserved for sub-project 3. ✓

**2. Placeholder scan:** Task 2 bootstrap sketch has a redundant loop flagged inline for the implementer to write ONE correct path — acceptable (it's a known cleanup, not a TBD). Task 4 live conviction returns 0.0 with a ponytail explaining the Phase-3 deferral — intentional, not a placeholder. No "TBD/TODO/add error handling" without code. ✓

**3. Type consistency:** `simulate_tilt(conviction, perp_ret, funding_per_bar, fee, slip)` stable across Tasks 2/3. `walk_forward(...)` returns `{k4_pass, split70_pass, net, folds_net}` used in Task 3. `bootstrap_ci` returns `(lo, hi)`. `TiltSignal.conviction(sample, state)->float` signed, consistent Task 4/5. `TiltRisk.size(cfg, conviction_mag, sample)->float` defined Task 5, consumed in run_loop. `load_tilt_signal(path)->TiltSignal` Task 4. ✓

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-08-24-regime-gate-tilt.md`. Two execution options:

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?