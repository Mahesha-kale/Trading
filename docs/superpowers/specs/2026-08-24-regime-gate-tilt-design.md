# Regime-Gate Tilt Research — Design Spec (sub-project 2)

Date: 2026-08-24
Status: design, pending implementation plan
Goal: find a regime-conditional **directional tilt** signal (the "shot at more" on top of the delta-neutral carry core from sub-project 1) via a pre-registered walk-forward sweep. A valid outcome is **no gate passes → tilt slot stays `NoTilt`, deploy is carry-only (~5-6%/yr)**. The tilt is upside optionality, not a requirement.

## Background

The research (`docs/strategies_report.md` §1-§30) concluded no **robust across-both-regimes** edge at free-data retail resolution. Under the relaxed goalpost the user accepted — profit in one regime + survive the other — sub-project 1 deployed the funding carry (§20/§27, ~7%/yr BTC/ETH, ~4.6%/yr SOL) as a delta-neutral paper→live trader with a pluggable tilt slot (`carry_trader.NoTilt` / `TiltSignal`, Phase 3, gated off). Sub-project 2 fills that slot: a regime gate whose walk-forward capture is net-positive after real costs becomes a `TiltSignal`; if none passes, `NoTilt` stays.

This spec covers the **research + signal production** only. It does not reopen the carry signal. The **risk overlay** (sizing/stopping the tilt) is sub-project 3 (separate spec); sub-project 2 produces the signal (direction + conviction), sub-project 3 governs the size + stop.

## Constraints (from user decisions)

- Free public data only; retail execution; CoinDCX perp (linear). Tilt is a **naked perp** overlay (no spot hedge) — so **no 1% TDS** (TDS is spot-sell only).
- Aggressive risk policy carried from sub-project 1: ≤25% portfolio DD hard stop (sub-project 3 enforces on the tilt).
- Hybrid shape: delta-neutral carry core + small directional tilt (≤20% of perp notional naked), within the 25% risk budget.
- **Sweep scope:** 3 gate classes (funding-slope, trend, basis) × 3 assets (BTC/ETH/SOL) × 2 directions (long/short) = 18 cells. Deploy any cell that passes; cross-asset pass = robustness bonus, not required.
- **Tilt direction:** long/short (the gate's signed conviction produces both signs; a cell is scored per the sign-direction we evaluate — a gate that only fires long gets its short cell scored no-trade).
- **Pass criterion (pre-registered):** net-positive after real costs in BOTH K=4 regime-balanced WF AND 70/30 secondary, per cell, AND bootstrap CI lower bound >0 on net (1000 resample, 95% CI). No Bonferroni (relaxed goalpost; bootstrap guards path-luck). This is the §19 path-luck trap guard.

## Approach

**A) Bar-level path equity per cell (chosen).** Load 15m perp + spot + funding per asset, compute each gate signal, simulate long/short tilt with real CoinDCX costs, K=4 regime-balanced WF + 70/30, bootstrap CI on net. Matches the §20/§27 carry-backtest convention so tilt net% is directly comparable to the carry floor and to the 25% DD budget — the thing the tilt slot actually consumes. Reuses `funding_carry_band.load_funding` + the §29 cost model.

Approaches B (event-study) and C (signal IC/threshold) are **out of scope, parked for future**.

## The 3 gate signals

All gates output **per-bar signed conviction in [-1,+1]** (sign=direction: +=long perp, -=short perp; |value|=strength 0..1). Params trained on first 70% by time, no OOS peek (§20 convention).

1. **Funding-slope gate** (`funding_slope_signal`) — rolling slope/z-score of the 8h funding rate over window W. Rising funding → long (longs piling, momentum continuation); falling/extreme-negative → short. Untested as *directional* — §27 used funding only for carry entry/flatten. Params: window W, z-score threshold. Grid trained IS 70%.

2. **Trend gate** (`trend_signal`) — supertrend (or MA-slope) regime on the 15m perp close. Uptrend → long, downtrend → short. §19 territory (supertrend 1d L/S, 1 ETH outlier = path luck); here it is a *tilt overlay* on the carry core (which hedges the off-regime), 15m not 1d, with the pre-registered bootstrap-CI pass criterion guarding path-luck. Params: supertrend period/multiplier (or MA short/long). Grid trained IS 70%.

3. **Basis gate** (`basis_signal`) — perp premium over spot (contango = perp>spot → bullish → long; backwardation → short), or the *change* in basis. basis = (perp_mark - spot)/spot in bps, from 15m perp + spot. Untested as directional — §24 used basis only for the carry squeeze-stop. Params: basis smoothing window, threshold in bps. Grid trained IS 70%.

**Sweep structure:** 3 gates × 3 assets × 2 directions = 18 cells. "2 directions" is realized by the gate's signed conviction (a gate naturally produces both signs); the cell label records which sign-direction is scored, so a gate that only fires long gets its short cell scored no-trade (correctly void, net=0, verdict FAIL).

## Components (new, minimal)

1. **`scripts/regime_gate_wf.py`** — the sweep engine. Per cell: load data → gate signal → long/short tilt path-equity sim (real costs) → K=4 regime-balanced WF + 70/30 → bootstrap CI. Outputs a per-cell verdict table + `reports/regime_gate_pass.json` of passing cells. `__main__` assert self-check (no pytest — `scripts/` convention).
2. **`scripts/regime_gates.py`** — pure gate-signal functions, one per class: `funding_slope_signal`, `trend_signal`, `basis_signal`. Each returns per-bar signed conviction [-1,+1]. Params trained IS 70%. `__main__` self-check.
3. **`scripts/tilt_signal.py`** — the `TiltSignal` impl(s) if a cell passes. Wraps a trained gate into the `async conviction(sample, state) -> float` interface `carry_trader.NoTilt` defines. Signed [-1,+1] (extends the merged [0,1] contract — see Interface). `__main__` self-check.
4. **Reports:** `reports/regime_gate_wf.log` (all 18 cells, verdicts) + `reports/regime_gate_pass.json`.
5. **`docs/strategies_report.md §31`** — sweep results appendix (verdict table + criterion + cost model + conclusion), committed regardless of outcome.

**Reused unchanged:**
- `funding_carry_band.load_funding` / `BANDS` / `FEE` (funding load + fee constants).
- The §29 real-cost model (maker 0.0236% / taker 0.059%, funding 8h, no TDS on perp).
- `carry_trader.TiltSignal` / `NoTilt` interface (the seam).

## Backtest + cost model + walk-forward

**Sim per cell:**
- Bar = 15m. Hold cash when |conviction| below threshold; enter naked perp in sign(conviction) when conviction crosses in (hysteresis band to avoid churn); exit on cross-out.
- Equity compounds bar-to-bar: perp PnL = sign × qty × price_ret; **funding paid/received** on the naked perp at every 8h funding mark (long in positive funding pays; short in positive funding receives — the carry's income source, now a cost on a long tilt).
- Costs per entry/exit: taker fee 0.059% (market) + execution-gap slippage estimate 5bps per side (from the §24/§29 basis-stop gap model). **NO TDS** (perp only).

**Walk-forward (pre-registered, no peeking):**
- Train: best param per gate on first 70% by time (IS net% max), grid search.
- Primary gate: **K=4 regime-balanced folds** (§19 convention) — split OOS by funding/price regime so each fold has both; score net% per fold, require net>0 in ≥3/4 folds AND aggregate net>0.
- Secondary gate: **70/30 split** (train 70% / test 30% by time) net>0 on the 30% test.
- **Pass:** net>0 in both WF schemes AND bootstrap CI lower bound >0 on net (1000 resample, 95% CI).
- Multiple cells may pass; each = a candidate TiltSignal. Cross-asset pass (same gate on ≥2 assets) = robustness bonus, noted not required.

## Data flow

```
reports/binance_{BTC,ETH,SOL}USDT_15m.csv  (perp OHLCV)
reports/binance_{BTC,ETH,SOL}USDT_spot_15m.csv  (spot OHLCV)
reports/binance_{BTC,ETH,SOL}USDT_funding.csv  (8h funding)
  ↓
regime_gates.funding_slope_signal / trend_signal / basis_signal
  → per-bar signed conviction [-1,+1], params trained IS 70%
  ↓
per cell (gate × asset × direction): bar-level path equity sim
  → fees 0.059% + slippage 5bps/side + funding paid/received at 8h marks
  ↓
K=4 regime-balanced WF + 70/30 + bootstrap CI
  ↓
reports/regime_gate_wf.log  (per-cell verdict table, all 18 cells)
reports/regime_gate_pass.json  (passing cells → TiltSignal candidates)
  ↓
if any pass: scripts/tilt_signal.py wraps the winning gate → TiltSignal impl
else: NoTilt stays (carry-only deploy ~5-6%/yr)
```

## Error handling

1. **Missing data file** → skip that asset's cells, log, continue. Report which assets skipped.
2. **Gate NaN/Inf** (empty funding window, div-by-zero basis) → mask conviction to 0 (no-trade), log count. Never propagate NaN into equity sim.
3. **All-flat gate** (fires 0 times in a cell) → cell scored no-trade, net=0, verdict FAIL (no edge, not an error). Logged.
4. **Bootstrap fails** (too few trades to resample) → verdict FAIL "insufficient trades", logged.
5. **Param grid empty / IS net all ≤0** → best param = lowest-loss, carry to OOS honestly; verdict likely FAIL, logged.
6. **No cell passes** → not an error. Report states "NoTilt — carry-only deploy", §31 appended. Valid expected outcome per §28.

## Testing (no new framework — `scripts/` `__main__` assert convention)

- `regime_gates.py` `__main__`: assert each gate returns signed conviction in [-1,+1] on a synthetic series; assert NaN/empty input masks to 0; assert both signs occur on a trending series.
- `regime_gate_wf.py` `__main__`: assert on a tiny synthetic dataset that (a) a deliberately-profitable gate cell passes (net>0, CI>0), (b) a flat/no-trade cell fails, (c) the cost model subtracts fees+funding (equity < gross).
- `tilt_signal.py` `__main__`: assert the impl returns the trained gate's conviction on a sample; assert NoTilt returns 0.0; assert sign matches direction.
- Existing `carry_trader.py` demo stays green (5 OK lines).

## Interface to carry_trader (the tilt slot — interface extension)

- The merged `TiltSignal.conviction(sample, state) -> float` was documented [0,1] (magnitude-only, long-only tilt branch). Sub-project 2 extends it to **signed [-1,+1]**: sign = direction (+=long perp, -=short perp), |value| = conviction. `NoTilt` still returns 0.0 (neutral, unaffected).
- `carry_trader.py` tilt-branch update (part of this sub-project's deliverable — the slot is the seam): change guard `if c > 0 and state.side == 0` → `if c != 0 and state.side == 0`; enter naked perp in direction `sign(c)`; size via `risk_budget.tilt_size(capital, abs(c), risk_fraction, leverage_cap)` (magnitude only). Live path stays `pass` (Phase 3, gated).
- **Sizing + stop = sub-project 3.** The carry_trader tilt branch calls a pluggable `TiltRisk` overlay (stub returns the raw `tilt_size` for now) that sub-project 3 fills. Sub-project 2 produces the signal only.

## Out of scope

- Approach B (event-study) and C (signal IC/threshold) — parked for future.
- Sub-project 3 (asymmetric risk overlay — sizes/stops the tilt) — separate spec.
- Re-deriving the carry signal or basis-stop (proven §20/§24).
- Options, cross-venue arbitrage, paid data, colocation.
- Live deployment of the tilt (Phase 3, gated behind Phase 0/1/2 of sub-project 1).

## Open questions for implementation plan

- Supertrend vs MA-slope for the trend gate (and exact param grid per gate) — pick supertrend first (matches §19 vocabulary), MA-slope as a fallback grid; decide in plan.
- Conviction strength mapping: raw z-score → [0,1] via tanh/clamp, or rank-percentile? Decide in plan; default tanh-clamp.
- Hysteresis band width to avoid churn (entry/exit threshold gap) — pick a conservative default (e.g. entry |c|>0.5, exit |c|<0.2) and grid it in IS training.
- Funding marks alignment to 15m bars (8h funding timestamp → nearest 15m bar) — resolve in plan (as-of join, forward-fill funding until next mark).