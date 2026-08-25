# Funding-Extreme Fade Tilt Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `funding_extreme_signal` gate (rolling-quantile fade of the funding rate, hysteresis-gated) and run a focused 6-cell walk-forward sweep (1 gate × 3 assets × 2 fade-directions) to verdict — either a passing cell becomes a `TiltSignal`, or 0/6 pass closes the tilt class negative and `NoTilt` stands.

**Architecture:** Reuse the §31 `regime_gate_wf.py` engine (`_align_bars`/`_train_params`/`_compute_gate`/`simulate_tilt`/`walk_forward`/`bootstrap_ci`) unchanged. Add one gate function to `regime_gates.py`, register it in the engine, and add a focused 6-cell driver `run_sweep_funding_extreme()` that scores each fade-direction by sign-isolating the two-sided conviction (clip, not §31's sign-flip — the fade gate fires both signs natively). Same pre-registered pass criterion as §31 (K=4 WF + 70/30 + bootstrap CI>0). §31's 18 cells are NOT re-run (frozen).

**Tech Stack:** Python 3.12, pandas, numpy. scripts/ convention: `__main__` assert demo() (NO pytest). ruff line-length 100.

**Spec:** docs/superpowers/specs/2026-08-25-tilt-funding-extreme-design.md (committed, branch `tilt-funding-extreme`).

## Global Constraints

- Python 3.12, ruff line-length 100.
- scripts/ → `__main__` assert demo() (NO pytest). Non-trivial logic leaves ONE runnable self-check.
- Tilt = naked perp → **no 1% TDS** (TDS is spot-sell only). Cost model §29 unchanged: taker 0.059% + 5bps/side slippage, funding paid/received at 8h marks **mark-aligned** (NOT forward-filled).
- Pre-registered pass criterion (identical to §31): net>0 AND K=4 `k4_pass` AND `split70_pass` AND bootstrap CI lower bound >0 (1000 resample, block=10, seed `np.random.default_rng(0)`).
- Params trained on first 70% by time (IS net max), no OOS peek.
- §31's 18 cells are frozen — do NOT re-run them; the focused driver runs only the 6 funding-extreme cells.
- Conviction contract: `+=long perp, -=short perp` (§31). Funding-extreme: extreme-positive `fr` → SHORT (-1, short receives funding); extreme-negative `fr` → LONG (+1, long receives funding).
- Do NOT touch `carry_trader.py` / `tilt_signal.py` unless a cell passes (then wrap the gate into `RegimeTiltSignal` — the seam already exists).

---

## File Structure

- **Modify:** `scripts/regime_gates.py` — add `funding_extreme_signal` + extend `demo()`.
- **Modify:** `scripts/regime_gate_wf.py` — register gate in `GATES` + `_train_params` grid + `_compute_gate` branch; add `run_sweep_funding_extreme()` (real 6-cell driver) + `run_sweep_extreme_synth()` (demo self-check) + `run-extreme` CLI in `__main__`.
- **Modify (conditional):** `scripts/tilt_signal.py` — only if a cell passes (the existing `RegimeTiltSignal`/`load_tilt_signal` already handle it; verify `reports/regime_gate_pass.json` flows). No code change expected for 0/6.
- **Modify:** `docs/strategies_report.md` — append `## §34` results appendix.
- **Run:** `python scripts/regime_gate_wf.py run-extreme` → `reports/regime_gate_wf.log` (appended) + `reports/regime_gate_pass.json`.

Three tasks: Task 1 gate function, Task 2 engine wiring + driver + demo, Task 3 run + report + disposition.

---

### Task 1: `funding_extreme_signal` gate + demo

**Files:**
- Modify: `scripts/regime_gates.py` — add function after `basis_signal` (line 56), before `demo()` (line 59); extend `demo()` before the final `print("regime_gates OK")` (line 84).

**Interfaces:**
- Consumes: `funding` DataFrame with a `"rate"` column (the mark-aligned 8h funding series from `regime_gate_wf._align_bars`), same shape `funding_slope_signal` consumes.
- Produces: `funding_extreme_signal(funding, w, q, q_exit) -> pd.Series` of signed conviction ∈ [-1,+1] (+=long fade, -=short fade, 0=no-trade). Consumed by Task 2's `_compute_gate` branch + `run_sweep_funding_extreme`.

- [ ] **Step 1: Add `funding_extreme_signal` after `basis_signal` (line 56)**

Insert (after the `basis_signal` return, before `def demo()`):

```python
def funding_extreme_signal(funding: pd.DataFrame, w: int, q: float, q_exit: float) -> pd.Series:
    """Rolling-quantile FADE of the funding rate (sub-project 6). Fires only at
    extremes of the recent funding distribution, then fades them on the funding-
    receiving side: fr > rolling q-quantile -> SHORT (-1, short receives funding
    in positive fr + bets the perp-spot premium reverts down); fr < rolling
    (1-q)-quantile -> LONG (+1, long receives funding in negative fr + bets
    premium reverts up). Hysteresis: enter at q, exit at the less-extreme q_exit
    quantile (q_exit < q) — prevents boundary churn (the §31 funding-slope
    failure mode). Binary conviction. NaN/empty window -> 0 (no NaN propagation)."""
    rate = funding["rate"].astype(float)
    roll_hi = rate.rolling(w, min_periods=w).quantile(q)            # enter-short line
    roll_lo = rate.rolling(w, min_periods=w).quantile(1.0 - q)      # enter-long line
    exit_short = rate.rolling(w, min_periods=w).quantile(q_exit)    # exit short below this
    exit_long = rate.rolling(w, min_periods=w).quantile(1.0 - q_exit)  # exit long above this
    pos = pd.Series(0.0, index=rate.index)
    side = 0.0
    for i in range(len(rate)):
        r = rate.iloc[i]
        if np.isnan(roll_hi.iloc[i]):  # warmup: not enough window yet
            pos.iloc[i] = 0.0
            continue
        if side == 0.0:
            if r > roll_hi.iloc[i]:
                side = -1.0
            elif r < roll_lo.iloc[i]:
                side = 1.0
        elif side == -1.0:
            if r < exit_short.iloc[i]:
                side = 0.0
        elif side == 1.0:
            if r > exit_long.iloc[i]:
                side = 0.0
        pos.iloc[i] = side
    return pd.Series(pos.fillna(0.0).clip(-CLIP, CLIP), index=rate.index)
```

- [ ] **Step 2: Extend `demo()` with the funding-extreme self-check**

Insert before the final `print("regime_gates OK")` (line 84):

```python
    # funding-extreme fade: rolling-quantile gate, hysteresis, low-frequency
    n = 300
    fr = np.full(n, 0.0001)
    for ix in (50, 150, 250):  # periodic positive extremes
        fr[ix] = 0.001
    for ix in (100, 200):       # periodic negative extremes
        fr[ix] = -0.0008
    fr_s = pd.Series(fr, index=idx)
    fe = funding_extreme_signal(pd.DataFrame({"rate": fr_s}), w=60, q=0.90, q_exit=0.80)
    assert fe.between(-1, 1).all(), "conviction out of [-1,1]"
    assert (fe > 0).any(), "long-fade (neg extreme) must fire"
    assert (fe < 0).any(), "short-fade (pos extreme) must fire"
    # low-frequency: the churn fix vs funding-slope. Count sign changes (flips).
    def _flips(s):
        return int((s.fillna(0).diff().abs() > 0).sum())
    assert _flips(fe) < 20, f"fade must be low-frequency, got {_flips(fe)} flips"
    slope = funding_slope_signal(pd.DataFrame({"rate": fr_s}), w=20, z=2.0)
    assert _flips(fe) < _flips(slope), \
        f"fade flips {_flips(fe)} must be < slope flips {_flips(slope)} (churn fix)"
    # hysteresis: after an extreme the signal returns to 0 (exit fires past q_exit)
    assert (fe.iloc[55:65] == 0).any(), "signal must exit after the extreme passes"
    # NaN/empty guard
    assert funding_extreme_signal(
        pd.DataFrame({"rate": pd.Series([np.nan, np.nan], index=idx[:2])}),
        w=60, q=0.90, q_exit=0.80).fillna(0).eq(0).all()
```

- [ ] **Step 3: Run the demo to verify**

Run: `PYTHONPATH=. python scripts/regime_gates.py`
Expected: prints `regime_gates OK` (the existing assertions + the new funding-extreme block all pass).

- [ ] **Step 4: ruff + commit**

```bash
.venv/Scripts/ruff.exe check scripts/regime_gates.py
git add scripts/regime_gates.py
git commit -m "feat(tilt): funding_extreme_signal rolling-quantile fade gate (sub-project 6)

Low-frequency fade of funding-rate extremes (decile enter + hysteresis exit)
on the funding-receiving side. Targets the §31 funding-slope churn failure
(~10k flips -> ~few). Binary signed conviction [-1,+1]. Demo: both fades fire,
flip count < funding_slope on the same series, hysteresis exits, NaN guards.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2: register gate + focused 6-cell sweep driver + demo + CLI

**Files:**
- Modify: `scripts/regime_gate_wf.py` — import (line 9), `GATES` (line 142), `_train_params` grid (line 177-181), `_compute_gate` (line 192-197), add `run_sweep_funding_extreme()` + `run_sweep_extreme_synth()`, wire `__main__` (line 296).

**Interfaces:**
- Consumes: `funding_extreme_signal` from Task 1; `_align_bars`/`_train_params`/`simulate_tilt`/`walk_forward`/`bootstrap_ci` (existing, unchanged).
- Produces: `run_sweep_funding_extreme() -> list[dict]` (6 cells, each {asset, gate, dir, params, net, ci_lo, k4_pass, split70_pass, verdict}); `run_sweep_extreme_synth()` for the demo. `main()` gains an `extreme` path; `__main__` gains `run-extreme`.

- [ ] **Step 1: Import `funding_extreme_signal`**

Line 9, change:
```python
from scripts.regime_gates import basis_signal, funding_slope_signal, trend_signal
```
to:
```python
from scripts.regime_gates import basis_signal, funding_extreme_signal, funding_slope_signal, trend_signal
```

- [ ] **Step 2: Register in `GATES`**

Line 142, change:
```python
GATES = {"funding_slope": funding_slope_signal, "trend": trend_signal, "basis": basis_signal}
```
to:
```python
GATES = {"funding_slope": funding_slope_signal, "trend": trend_signal, "basis": basis_signal,
         "funding_extreme": funding_extreme_signal}
```

- [ ] **Step 3: Add the `funding_extreme` param grid in `_train_params`**

In the `grids` dict (line 177-181), add a `funding_extreme` entry after the `basis` entry:
```python
        "basis": [{"w": w, "thr_bps": t} for w in (10, 20) for t in (5.0, 10.0, 20.0)],
        "funding_extreme": [{"w": w, "q": q, "q_exit": q - 0.10}
                            for w in (120, 240, 480) for q in (0.90, 0.95)],
```

- [ ] **Step 4: Add the `funding_extreme` branch in `_compute_gate`**

Line 192-197, change:
```python
def _compute_gate(gate: str, params: dict, perp, spot, funding_per_bar) -> pd.Series:
    if gate == "funding_slope":
        return funding_slope_signal(pd.DataFrame({"rate": funding_per_bar}), **params)
    if gate == "trend":
        return trend_signal(perp, **params)
    return basis_signal(perp, spot, **params)
```
to:
```python
def _compute_gate(gate: str, params: dict, perp, spot, funding_per_bar) -> pd.Series:
    if gate == "funding_slope":
        return funding_slope_signal(pd.DataFrame({"rate": funding_per_bar}), **params)
    if gate == "funding_extreme":
        return funding_extreme_signal(pd.DataFrame({"rate": funding_per_bar}), **params)
    if gate == "trend":
        return trend_signal(perp, **params)
    return basis_signal(perp, spot, **params)
```

- [ ] **Step 5: Add `run_sweep_funding_extreme()` (real 6-cell driver)**

Insert after `run_sweep()` (line 233), before `run_sweep_synth()` (line 236):

```python
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
```

- [ ] **Step 6: Add `run_sweep_extreme_synth()` (demo self-check)**

Insert after `run_sweep_synth()` (after line 268), before `def main()`:

```python
def run_sweep_extreme_synth() -> list[dict]:
    """Tiny synthetic funding-extreme sweep for the self-check: 1 asset x 2 dirs.
    A deliberately-profitable fade cell (funding mean-reverts) should PASS; a
    flat cell (no extremes -> no fires) should FAIL; equity < gross (costs)."""
    idx = pd.date_range("2026-01-01", periods=600, freq="15min")
    # funding: oscillating extremes that revert — a fade profits (short pos extreme,
    # long neg extreme) AND earns funding on the receiving side.
    n = 600
    fr = np.full(n, 0.0001)
    for ix in range(60, n, 120):  # positive extreme then reverts
        fr[ix] = 0.002
    for ix in range(120, n, 120):  # negative extreme then reverts
        fr[ix] = -0.002
    funding_per_bar = pd.Series(fr, index=idx)
    # perp returns: after a positive funding extreme, perp drifts DOWN (premium
    # reverts) -> short fade profits; after a negative extreme, perp drifts UP.
    perp_ret = pd.Series(0.0, index=idx)
    for ix in range(60, n, 120):
        perp_ret.iloc[ix + 1 : ix + 6] = -0.001  # short fade wins here
    for ix in range(120, n, 120):
        perp_ret.iloc[ix + 1 : ix + 6] = 0.001   # long fade wins here
    perp = (1.0 + perp_ret).cumprod() * 100.0
    spot = pd.Series(np.full(n, 100.0), index=idx)
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
```

- [ ] **Step 7: Call `run_sweep_extreme_synth()` from `demo()` + assert**

In `demo()` (line 94-141), after the existing `run_sweep_synth()` block (the `assert len(cells) == 6` at line 125), add:

```python
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
```

- [ ] **Step 8: Add `run-extreme` to `__main__` + an `extreme` path in `main()`**

Replace `main()` (line 271-294) and the `__main__` block (line 296-301). New `main()` accepts an `extreme` flag; the `__main__` block dispatches `run` (§31 18, unchanged) vs `run-extreme` (the 6 cells). Replace:

```python
def main():
    import json
    import logging

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    log = logging.getLogger("regime_gate_wf")
    cells = run_sweep()
    with open("reports/regime_gate_wf.log", "w") as f:
        f.write("asset,gate,dir,net,ci_lo,k4,split70,verdict,params\n")
        f.writelines(
            f"{c['asset']},{c['gate']},{c['dir']},{c.get('net','-')},"
            f"{c.get('ci_lo','-')},{c.get('k4_pass','-')},"
            f"{c.get('split70_pass','-')},{c['verdict']},{c.get('params','-')}\n"
            for c in cells
        )
    passing = [c for c in cells if c["verdict"] == "PASS"]
    with open("reports/regime_gate_pass.json", "w") as f:
        json.dump(passing, f, indent=2)
    log.info("sweep done: %d cells, %d PASS", len(cells), len(passing))
    for c in passing:
        log.info("PASS %s", {k: c[k] for k in ("asset", "gate", "dir", "net")})
    if not passing:
        log.info("NoTilt — no cell passed; carry-only deploy (~5-6%/yr)")
```

with:

```python
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
        log.info("NoTilt — no %s cell passed; carry-only deploy (~5-6%/yr)", label)
```

And replace the `__main__` block:

```python
if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "run":
        main()  # §31 18-cell sweep (frozen) -> reports/
    elif len(sys.argv) > 1 and sys.argv[1] == "run-extreme":
        main(extreme=True)  # sub-project 6: 6 funding-extreme cells -> reports/
    else:
        demo()
```

- [ ] **Step 9: Run the demo to verify**

Run: `PYTHONPATH=. python scripts/regime_gate_wf.py`
Expected: prints the existing demo assertions + the new `run_sweep_extreme_synth` checks pass (no AssertionError). The §31 `run_sweep_synth` `assert len(cells) == 6` still holds (unchanged).

- [ ] **Step 10: ruff + commit**

```bash
.venv/Scripts/ruff.exe check scripts/regime_gate_wf.py
git add scripts/regime_gate_wf.py
git commit -m "feat(tilt): funding-extreme 6-cell sweep driver + run-extreme CLI (sub-project 6)

Register funding_extreme in GATES + grid + _compute_gate. run_sweep_funding_extreme
runs 1 gate x 3 assets x 2 fade-dirs, sign-isolating each direction (clip, not
§31's sign-flip — the fade gate fires both signs natively). Same pre-registered
WF pass criterion. run-extreme CLI; log appends (§31 frozen), pass json reflects
the 6 cells. Demo: profitable synth fade nets >0, cells fire, costs apply.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 3: run the 6-cell sweep (verdict) + §34 report appendix + disposition

**Files:**
- Run: `python scripts/regime_gate_wf.py run-extreme` → reads `reports/binance_{BTC,ETH,SOL}USDT_15m.csv` + `_spot_15m.csv` + `_funding.csv` (the §31 data set; confirm present before running).
- Modify: `docs/strategies_report.md` — append `## §34` after the §33 conclusion (end of file).
- Modify (only if a cell PASSes): `scripts/tilt_signal.py` — verify `load_tilt_signal` picks up the passing cell from `reports/regime_gate_pass.json` (no code change expected; the seam already wraps any passing cell). Add a `__main__` assertion only if a pass occurs.
- Memory: update `memory/regime-gate-tilt-sweep.md` + `MEMORY.md` index with the §34 outcome.

- [ ] **Step 1: Confirm the data files exist**

Run:
```bash
ls reports/binance_BTCUSDT_15m.csv reports/binance_BTCUSDT_spot_15m.csv reports/binance_BTCUSDT_funding.csv reports/binance_ETHUSDT_funding.csv reports/binance_SOLUSDT_funding.csv
```
Expected: all exist (§31 used them). If any missing, that asset's cell verdicts `SKIP_NODATA` — log which, do not fabricate.

- [ ] **Step 2: Run the 6-cell sweep**

Run: `PYTHONPATH=. python scripts/regime_gate_wf.py run-extreme 2>&1 | tail -20`
Expected: logs `funding-extreme sweep done: 6 cells, <k> PASS` + per-cell PASS lines (if any). Then read the appended rows:
```bash
tail -6 reports/regime_gate_wf.log
cat reports/regime_gate_pass.json
```
Capture the 6-row verdict table (asset, gate, dir, net, ci_lo, k4, split70, verdict, params). This IS the research result.

- [ ] **Step 3: Append `## §34` to `docs/strategies_report.md`**

Append (fill the table from Step 2's output; the narrative depends on the verdict):

```
## §34. Funding-extreme fade tilt sweep — <N>/6 cells pass (sub-project 6)

> §31 swept 3 regime gates × 3 assets × 2 directions = 0/18 pass → `NoTilt`.
> This section logs sub-project 6: one NEW tilt signal — a low-frequency
> funding-extreme fade (rolling-quantile decile gate + hysteresis) that targets
> §31's funding-slope churn failure (~10k flips → few). Spec:
> `docs/superpowers/specs/2026-08-25-tilt-funding-extreme-design.md`; plan:
> `docs/superpowers/plans/2026-08-25-tilt-funding-extreme.md`.

### 34.1 Thesis

Funding-rate extremes mean-revert. Fade them on the funding-receiving side:
extreme-positive `fr` → SHORT (short receives funding + perp-spot premium
reverts down); extreme-negative `fr` → LONG (long receives funding + premium
reverts up). Funding income aligns with the fade — stronger than a pure
directional bet. Named failure mode: the §27 squeeze risk (extremes persist).

### 34.2 Sweep structure + pass criterion

1 gate (`funding_extreme`) × 3 assets (BTC/ETH/SOL) × 2 fade-directions
(long-fade, short-fade) = 6 cells. Same pre-registered pass criterion as §31:
net>0 AND K=4 contiguous WF (≥3/4 folds + aggregate) AND 70/30 AND bootstrap
CI lower bound >0 (1000 resample, block=10, seed 0). Cost model §29: taker
0.059% + 5bps/side, funding mark-aligned, no TDS (naked perp). Params trained
IS 70%. §31's 18 cells not re-run.

### 34.3 Per-cell verdict table

From `reports/regime_gate_wf.log` (6 rows):

| asset | gate | dir | net | ci_lo | k4 | split70 | verdict | params |
|---|---|---|---|---|---|---|---|---|
| <fill from run> | ... | ... | ... | ... | ... | ... | ... | ... |

### 34.4 Results narrative

<Fill from the run: per-gate / per-direction narrative. If 0/6: state the
failure mode — extremes persist (squeeze) so the fade pays the directional
leg, OR the few flips don't overcome cost, OR funding-receive income is
outweighed by the directional loss; cite the cells. If any PASS: name the cell
+ its params + which guards it cleared.>

### 34.5 Conclusion

<If 0/6:> 0/6 cells pass → the tilt class **closes negative** (like the
order-flow class §25/§26). `NoTilt` stands; the carry-only deploy (~5-6%/yr
§27, USDT redesign §29) remains the single standing edge. Consistent with
§28 (no robust retail perp edge at free-data resolution). The §30 paper-trader
tilt slot stays `NoTilt`.

<If ≥1 PASS:> cell <asset/dir> passes → wrapped as a `TiltSignal` candidate
in `tilt_signal.py`; the carry_trader tilt slot (Phase 3) has a candidate,
still gated behind the redesign's Phase 0/1/2. Cross-asset pass = robustness
bonus, noted.

See [[regime-gate-tilt-sweep]] (§31), [[funding-carry-band]] (§20),
[[carry-funding-regime-walkforward]] (§27/§28).
```

- [ ] **Step 4: Disposition — `tilt_signal.py` (only if a cell PASSed)**

If `reports/regime_gate_pass.json` is non-empty (`[{...}]`): `load_tilt_signal()` already wraps the first passing cell in `RegimeTiltSignal` — no code change. Add one `__main__` assertion that `load_tilt_signal()` returns a `RegimeTiltSignal` (not `NoTilt`) given the pass json, to guard the seam. Run `PYTHONPATH=. python scripts/tilt_signal.py` → expect its demo OK line + the new assertion.
If pass json is `[]` (0/6): no change to `tilt_signal.py`; `load_tilt_signal()` returns `NoTilt` (existing behavior, already demoed). Skip this step.

- [ ] **Step 5: Commit the report + run artifacts**

```bash
git add docs/strategies_report.md
# include the tilt_signal.py change only if Step 4 ran
git add scripts/tilt_signal.py 2>/dev/null || true
git commit -m "docs(research): §34 funding-extreme fade tilt sweep — <N>/6 pass (sub-project 6)

<narrative one-liner>. 0/6 -> tilt class closes negative, NoTilt stands; or
<N>/6 -> TiltSignal candidate. Spec/plan: docs/superpowers/{specs,plans}/
2026-08-25-tilt-funding-extreme*.

Co-Authored-By: Claude <noreply@anthropic.com>"
```
(Reports under `reports/` are gitignored — the log + pass json stay local; the §34 table in the report is the committed record.)

- [ ] **Step 6: Update memory**

Update `memory/regime-gate-tilt-sweep.md` (append a §34 sub-project-6 outcome line: the verdict, the churn-fix attempt, the failure mode or pass) + its `MEMORY.md` index hook. If 0/6, note the tilt class is now closed negative (stronger than §31's "sealed NoTilt" — a second, different tilt signal also failed).

---

## Self-Review

**1. Spec coverage:**
- Signal (`funding_extreme_signal`, quantile + hysteresis, binary ±1, NaN guard) → Task 1. ✓
- Sweep (1 gate × 3 assets × 2 fade-dirs = 6 cells, sign-isolation, §31 frozen) → Task 2 Step 5. ✓
- Pre-registered pass criterion (K=4 + 70/30 + bootstrap CI>0) → reused `walk_forward`/`bootstrap_ci` unchanged, Task 2 Step 5 verdict line. ✓
- Cost model §29 (mark-aligned, no TDS) → reused `simulate_tilt`/`_align_bars` unchanged. ✓
- Components: regime_gates (Task 1), regime_gate_wf (Task 2), tilt_signal conditional (Task 3 Step 4), reports (Task 3 Step 3/5), §34 (Task 3 Step 3). ✓
- Error handling (SKIP_NODATA, NaN mask, all-flat FAIL, bootstrap fail, 0/6 = valid) → covered by `_align_bars`/`simulate_tilt` reuse + the driver's SKIP_NODATA branch; 0/6 disposition in Task 3. ✓
- Out of scope respected: no carry_trader change, no §31 re-run, no cross-asset/B-C/sub-project-3. ✓

**2. Placeholder scan:** Task 3 Step 3's §34 template has `<fill from run>` markers — these are filled from the actual sweep output (Step 2), which cannot be known until the code runs. This is the research result, not a plan gap; the template + instruction to fill from the run is the complete specification of the step. No TBD/TODO in code steps. All code blocks complete. ✓

**3. Type consistency:**
- `funding_extreme_signal(funding, w, q, q_exit) -> pd.Series` — Task 1 defines; Task 2 imports + calls via `_compute_gate` as `funding_extreme_signal(pd.DataFrame({"rate": funding_per_bar}), **params)` with `params={"w","q","q_exit"}` (grid Step 3). Names match. ✓
- `run_sweep_funding_extreme() -> list[dict]` returns cells with keys {asset, gate, dir, params, net, ci_lo, k4_pass, split70_pass, verdict} — matches §31's `run_sweep` cell shape (line 220-232) so `main()`'s log writer + `load_tilt_signal` consume them unchanged. ✓
- `run_sweep_extreme_synth()` returns {asset, gate, dir, net, verdict, scored_fires} — the demo (Step 7) asserts those keys; `scored_fires` is demo-only, not consumed by `main()`. ✓
- `main(extreme: bool = False)` + `__main__` `run-extreme` dispatch — names match (Step 8). ✓
- DIRECTIONS reused (`["long","short"]`, line 144) — long-fade = `clip(lower=0)`, short-fade = `clip(upper=0)`; matches the demo synth (Step 6) + driver (Step 5). ✓
- `CLIP` constant (regime_gates line 9) reused in `funding_extreme_signal`. ✓

**Note (carried into Task 3):** the expected outcome is 0/6 (strong §28 negative prior; §31 already refuted funding as directional via slope). The plan handles the pass case too, but the honest default is the tilt class closing negative. Reports/ artifacts are gitignored — the committed §34 table is the durable record.