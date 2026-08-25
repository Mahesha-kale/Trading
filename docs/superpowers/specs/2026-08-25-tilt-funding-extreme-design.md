# Funding-Extreme Fade Tilt — Design Spec (sub-project 6)

Date: 2026-08-25
Status: design, pending implementation plan
Goal: test one new directional tilt signal — a **funding-extreme fade** — on top of the delta-neutral carry core, via a pre-registered walk-forward sweep. A valid outcome is **0/6 cells pass → tilt class closes negative** (like the order-flow class §25/§26), and the carry-only deploy stands. If a cell passes, it becomes a `TiltSignal`; else `NoTilt` stays.

## Background

§31 (sub-project 2, PR #17) swept 3 regime gates (funding-slope, trend, basis) × 3 assets × 2 directions = 18 cells; **0/18 passed** → tilt slot sealed `NoTilt`. Failure modes:
- **funding-slope** = churn-ruin (~10,105 flips; per-flip fee+slippage > directional capture).
- **trend long** = bull-beta path-luck (fails split70 or bootstrap CI; §19 trap).
- **trend short / basis** = negative net (basis carries no independent directional info).

The funding-extreme fade is a **deliberately different, low-frequency** funding bet that targets the funding-slope churn failure: instead of slope (which flips continuously), fire only at funding **levels** in the extreme tail of their recent distribution, and fade them. This is the user's binding-sequence item #3 ("new tilt research"). It does not reopen the carry signal (§20/§27) or the §31 gates.

## Thesis

Funding-rate extremes mean-revert. A naked perp on the **funding-receiving side** at the extreme captures both the funding income and the reversion:

- `fr` extreme-positive (top decile) → **SHORT** perp. Short receives funding (fr>0 = longs pay shorts) AND the perp-spot premium reverts down as funding normalizes → short benefits.
- `fr` extreme-negative (bottom decile) → **LONG** perp. Long receives funding (fr<0 = shorts pay longs) AND the premium reverts up.

Funding income **aligns** with the fade direction — a stronger thesis than a pure directional bet. The named failure mode is the §27 squeeze risk: funding extremes can **persist** (a sustained squeeze keeps fr elevated), in which case the fade loses on the directional leg while still earning funding — the sweep surfaces this honestly.

## Distinction from the carry core

The carry (§27) is delta-neutral (short perp + long spot, band-gated, always harvesting). The fade tilt is a **naked perp** (no spot leg → no 1% TDS, same as §31), directional, firing only at extremes. Same underlying `fr` state, different instrument structure + different timing (extreme decile vs band) + different PnL (directional + funding, not hedged harvest). Not redundant.

## Constraints (from user decisions + §31 convention)

- Free public data only; retail execution; CoinDCX perp (linear). Tilt = naked perp → **no 1% TDS** (TDS is spot-sell only).
- ≤25% portfolio DD hard stop (the tilt slot's risk budget; enforced by the existing carry_trader fail-safe, unchanged).
- **Sweep scope:** 1 gate (funding-extreme) × 3 assets (BTC/ETH/SOL) × 2 fade-directions (short-fade = positive-extreme→short, long-fade = negative-extreme→long) = **6 cells**.
- **Pass criterion (pre-registered, identical to §31):** net>0 after real costs in **all three** guards — (1) K=4 contiguous time-slice walk-forward: net>0 in ≥3/4 folds AND aggregate net>0; (2) 70/30 split: net>0 on the 30% test slice; (3) bootstrap CI: 1000 resample, circular-block `block=10`, seed `np.random.default_rng(0)`, 95% CI lower bound >0. No Bonferroni (bootstrap+split70 is the path-luck guard).
- Params trained on first 70% by time (IS net max, grid search), no OOS peek (§20 convention).

## The signal

`funding_extreme_signal(funding, w, q, q_exit)` in `scripts/regime_gates.py`:

- Rolling window `W` marks on the 8h funding rate `fr` (mark-aligned to 15m bars by `_align_bars`, §31).
- **Enter** short when `fr` > `q`-quantile (e.g. 0.90) of the rolling window; **exit** when `fr` falls below the `q_exit`-quantile (e.g. 0.80). Symmetric for long: enter when `fr` < `1-q` quantile, exit above `1-q_exit`. **Hysteresis** (`q` ≠ `q_exit`) prevents boundary churn — the §31 funding-slope failure mode.
- Conviction is **binary ±1** (crisp, like `trend_signal`): +1 long-fade, -1 short-fade, 0 no-trade. (Magnitude scaling parked — binary is the minimal test of the thesis.)
- NaN/empty window → 0 (no NaN propagation, §31 guard).

Quantile (nonparametric) is chosen over z-score because funding is fat-tailed; a fixed z-threshold over-/under-fires across regime shifts. The rolling window adapts the "extreme" definition to the recent funding distribution.

## Sweep wiring (reuse §31 engine)

- Register `funding_extreme_signal` in `regime_gate_wf.GATES`. Add a param grid: `W` ∈ {120, 240, 480} marks (~40d/80d/160d at 8h), `q` ∈ {0.90, 0.95}, `q_exit` = `q - 0.10`. `_train_params` grid-searches IS 70%; `_compute_gate` gets a branch for `funding_extreme`.
- **§31's 18 cells are NOT re-run** (frozen verdict). The driver runs only the 6 new funding-extreme cells (focused `run_sweep_funding_extreme()` reusing `_align_bars`/`_train_params`/`simulate_tilt`/`walk_forward`/`bootstrap_ci`, OR extend `run_sweep` and filter — plan decides). Output: per-cell verdict table + append to `reports/regime_gate_wf.log`; passing cells (if any) → `reports/regime_gate_pass.json` + a `TiltSignal` impl in `tilt_signal.py`.
- Cost model (§29, unchanged): taker 0.059% + 5bps/side slippage, funding paid/received at 8h marks **mark-aligned** (NOT forward-filled — 32× overcharge fix), no TDS.

## Components

1. **`scripts/regime_gates.py`** — add `funding_extreme_signal` (one function + `__main__` self-check: signed conviction ∈ [-1,+1], NaN/empty masks to 0, hysteresis enter/exit on a synthetic extreme-reverting series, both fade directions fire, low flip count vs a slope signal on the same series).
2. **`scripts/regime_gate_wf.py`** — register the gate + grid + `_compute_gate` branch; add the focused 6-cell sweep driver; `__main__` self-check (synthetic profitable-fade cell passes, flat cell fails, cost model subtracts fee+funding). `main()` runs the 6-cell sweep, logs + writes pass json.
3. **`scripts/tilt_signal.py`** — (only if a cell passes) wrap the trained gate into the `TiltSignal` interface. If 0/6 pass, no change (`NoTilt` stays).
4. **Reports:** append 6-cell verdict table to `reports/regime_gate_wf.log`; update `reports/regime_gate_pass.json`.
5. **`docs/strategies_report.md §34`** — sweep results appendix (verdict table + criterion + cost model + conclusion), committed regardless of outcome.

**Reused unchanged:** `_align_bars`, `simulate_tilt`, `walk_forward`, `bootstrap_ci`, `funding_carry_band.load_funding`/`BANDS`/`FEE`, the §29 cost model, `carry_trader.TiltSignal`/`NoTilt` seam.

## Data flow

```
reports/binance_{BTC,ETH,SOL}USDT_funding.csv  (8h funding)
reports/binance_{BTC,ETH,SOL}USDT_15m.csv       (perp OHLCV, for returns + funding mark-align)
  ↓ _align_bars (mark-only funding to 15m bars)
regime_gates.funding_extreme_signal  → per-bar signed conviction [-1,+1], params trained IS 70%
  ↓ per cell (gate × asset × fade-direction): bar-level path equity sim
  ↓ fees 0.059% + slippage 5bps/side + funding paid/received at 8h marks
K=4 regime-balanced WF + 70/30 + bootstrap CI  → 6-cell verdict table
  ↓
0/6 pass → NoTilt stays, tilt class closes negative, §34 appended
≥1 pass → TiltSignal impl in tilt_signal.py → candidate for the carry_trader tilt slot (Phase 3, still gated)
```

## Error handling (same envelope as §31)

1. Missing data file → skip that asset's cells, log, continue.
2. Gate NaN/Inf (empty funding window) → mask conviction to 0, log count. Never propagate NaN into equity sim.
3. All-flat gate (fires 0 times in a cell) → cell scored no-trade, net=0, verdict FAIL (no edge, not an error). Logged.
4. Bootstrap fails (too few trades) → verdict FAIL "insufficient trades", logged.
5. Param grid empty / IS net all ≤0 → best = lowest-loss, carried to OOS honestly; verdict likely FAIL, logged.
6. 0/6 pass → **not an error**. Report states "tilt class closes negative — NoTilt, carry-only deploy", §34 appended. Valid expected outcome per §28.

## Testing (scripts/ `__main__` assert convention, no pytest)

- `regime_gates.py` `__main__`: assert `funding_extreme_signal` returns signed conviction ∈ [-1,+1]; NaN/empty masks to 0; on a synthetic extreme-reverting series both fade directions fire; flip count << funding_slope_signal's on the same series (the churn fix); hysteresis holds (exit fires only after crossing back past `q_exit`).
- `regime_gate_wf.py` `__main__`: assert on a tiny synthetic dataset that (a) a deliberately-profitable fade cell passes (net>0, CI>0, k4+split70), (b) a flat/no-trade cell fails, (c) cost model subtracts fee+funding (equity < gross).
- `tilt_signal.py` `__main__`: unchanged unless a cell passes (then assert the impl returns the trained gate's conviction + sign matches direction).
- `carry_trader.py` demo stays green (no change unless a tilt is produced).

## Out of scope

- Cross-asset relative value, parked approaches B (event-study) + C (signal IC/threshold), sub-project 3 (asymmetric risk overlay) — separate/future.
- Re-deriving the carry signal or basis-stop (proven §20/§24).
- Re-running the §31 18 cells (frozen).
- Conviction magnitude scaling (binary is the minimal test).
- Options, cross-venue arbitrage, paid data, colocation.
- Live deployment of the tilt (Phase 3, gated behind the redesign's Phase 0/1/2).

## Open questions for the implementation plan

- Exact param grid bounds (`W`, `q`, `q_exit` gap) — defaults above; expand if IS all ≤0.
- Focused 6-cell driver vs extend-and-filter `run_sweep` — pick the smaller diff in the plan.
- Conviction binary vs scaled by quantile-distance — binary default; scaled only if binary 0/6 and a scaled variant is worth a second pass (parked).
- Funding marks alignment — already resolved by `_align_bars` (mark-only, §31); reuse as-is.