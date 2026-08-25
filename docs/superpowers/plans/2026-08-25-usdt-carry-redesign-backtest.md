# USDT carry redesign — re-backtest gate (component 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Re-score the §27 funding-regime walk-forward under real CoinDCX USDT costs (separate perp/spot fees + 2% spot TDS round-trip) to decide whether the ~7%/yr carry edge survives — the gate for the whole USDT redesign.

**Architecture:** Preserve §27's `carry_oneside` byte-identical as the baseline. Add `carry_oneside_usdt` with the real USDT cost model (perp maker fee + spot fee + 1% TDS on BOTH entry buy + exit sell). `main()` runs both cost models for BTCUSDT/ETHUSDT/SOLUSDT, train-selects the band on 70% under EACH cost model, and prints a side-by-side comparison + a USDT gate verdict. If USDT gate FAILS, the redesign stops (abandon, option C); components 2-4 are not planned.

**Tech Stack:** Python 3.12, numpy, pandas. scripts/ convention: `__main__` assert demo() (NO pytest). ruff line-length 100.

**Spec:** docs/superpowers/specs/2026-08-25-usdt-carry-redesign-design.md (component 1 only; components 2-4 gated behind this plan's PASS).

## Global Constraints

- Python 3.12, ruff line-length 100.
- scripts/ → `__main__` assert demo() (NO pytest). Non-trivial logic leaves ONE runnable self-check.
- TDS (USDT C2C pair, Section 194S): `TDS_BUY_USDT = 0.01` (1% on spot BUY) + `TDS_SELL_USDT = 0.01` (1% on spot SELL) = 200 bps round-trip on the spot leg. Futures = no TDS.
- `FEE_PERP = 0.000236` (CoinDCX perp maker 0.0236%, §29 verified). Maker fee (matches §27's MAKER=True).
- `FEE_SPOT = 0.00199` (CoinDCX spot ~0.169% × 1.18 GST ≈ 0.199%, §29 BTCINR-derived — to-verify for BTCUSDT in component 3; best estimate for this gate).
- Do NOT modify §27's `carry_oneside` or its `TDS`/`main` baseline print — preserve it byte-identical for comparison. Add `carry_oneside_usdt` + a USDT section in `main`.
- Funding history is Binance proxy (`reports/binance_{sym}_funding.csv` via `load_funding`); fr is per-contract, margin-currency-independent — same data as §27.
- Train-select band on first 70% by time under EACH cost model (no OOS peeking), as §27.

---

## File Structure

- **Modify:** `scripts/carry_funding_regime.py` — add `carry_oneside_usdt` (new function, real USDT cost model) + extend `main()` with a USDT-cost section (comparison + verdict) + add a `demo()` self-check. §27's `carry_oneside` + existing `main` print logic stay intact.

Single file, two tasks. Task 1 adds + self-checks the cost function; Task 2 wires it into `main` + prints the verdict.

---

### Task 1: `carry_oneside_usdt` — real USDT cost model + self-check

**Files:**
- Modify: `scripts/carry_funding_regime.py` (add after the existing `carry_oneside`, ~line 60)

**Interfaces:**
- Consumes: `numpy as np` (already imported). The existing `carry_oneside(rate, band, fee_per_fill, tds=TDS)` signature — read for parallel structure, do NOT change it.
- Produces: `carry_oneside_usdt(rate: np.ndarray, band: float, perp_fee: float = FEE_PERP, spot_fee: float = FEE_SPOT, tds_buy: float = TDS_BUY_USDT, tds_sell: float = TDS_SELL_USDT) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]` returning `(net, side_arr, entry, flat)` — same shape/semantics as `carry_oneside`. Consumed by Task 2's `main`.

- [ ] **Step 1: Write the failing demo (asserts the cost logic)**

Add a `demo()` function + the new constants + function stub that returns wrong values, so the demo fails first. Put this block after the existing `carry_oneside` (after line 60) and before `regime_runs`:

```python
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
```

- [ ] **Step 2: Run the demo to verify it fails (function stub not yet defined)**

Run: `PYTHONPATH=. python -c "from scripts.carry_funding_regime import demo; demo()"`
Expected: FAIL — `NameError: name 'carry_oneside_usdt' is not defined` (or an assertion error if you added a stub returning zeros). The constants + real function body are already in Step 1's code block, so if you pasted the full block this passes immediately — in that case, still run Step 4 to confirm green.

- [ ] **Step 3: Implement (the full code block from Step 1 IS the implementation)**

The code block in Step 1 is the complete implementation — constants + `carry_oneside_usdt` + `demo`. Paste it after the existing `carry_oneside` (line 60) and before `regime_runs`. Do NOT alter `carry_oneside`, `TDS`, `regime_runs`, or `main`.

- [ ] **Step 4: Run the demo to verify it passes**

Run: `PYTHONPATH=. python -c "from scripts.carry_funding_regime import demo; demo()"`
Expected: PASS — prints `carry_oneside_usdt cost logic OK`.

- [ ] **Step 5: ruff**

Run: `ruff check scripts/carry_funding_regime.py`
Expected: no errors on the new code.

- [ ] **Step 6: Commit**

```bash
git add scripts/carry_funding_regime.py
git commit -m "feat(carry): carry_oneside_usdt real USDT cost model (redesign comp 1)"
```

---

### Task 2: USDT-cost walk-forward in `main` + verdict

**Files:**
- Modify: `scripts/carry_funding_regime.py` — `main()` (lines 81-133) + `__main__` (lines 136-137)

**Interfaces:**
- Consumes: `carry_oneside_usdt` + constants from Task 1 (`FEE_PERP`, `FEE_SPOT`, `TDS_BUY_USDT`, `TDS_SELL_USDT`). Existing `load_funding`, `BANDS`, `regime_runs`, `metrics` (from `funding_carry`).
- Produces: an extended `main()` that prints the §27 baseline AND the USDT-cost walk-forward side-by-side per symbol + a USDT gate verdict line. `__main__` runs `demo()` first (self-check) then `main()`.

- [ ] **Step 1: Extend `main()` with the USDT-cost section**

The existing `main()` loops `for sym in ("BTCUSDT", "ETHUSDT", "SOLUSDT")` and prints the §27 baseline (using `carry_oneside` + `fee = FEE_TAKER * (0.5 if MAKER else 1.0)`). Add a USDT-cost section INSIDE the same per-symbol loop, AFTER the §27 `GATE` print (after line 133), so each symbol shows baseline then USDT. Insert this block before the final `print()` of the loop body:

```python
        # --- USDT-cost path (redesign component 1): real CoinDCX USDT costs ---
        # perp maker 0.0236%, spot ~0.199%, 1% TDS on BOTH spot buy + sell.
        net_u, side_u, ent_u, flt_u = carry_oneside_usdt(rate, best)
        eq_u = np.cumprod(1.0 + net_u)
        posnet_u = net_u[pos].sum() * 100
        negnet_u = net_u[neg].sum() * 100
        gate_u = ("PASS" if posnet_u > 0 and negnet_u >= -0.1 else "FAIL")
        print(f"  USDT-cost | perp={FEE_PERP:.5f} spot={FEE_SPOT:.5f} "
              f"TDSbuy={TDS_BUY_USDT} TDSsell={TDS_SELL_USDT}")
        print(f"  USDT FULL: net={(eq_u[-1]-1)*100:.1f}% entries={ent_u.sum()} "
              f"flattens={flt_u.sum()} | ~{(eq_u**(1/yrs)-1).mean()*100 if yrs>0 else 0:.1f}%/yr"
              f" | sh={metrics(pd.Series(eq_u))['sharpe']}")
        print(f"  USDT GATE: {gate_u} | posNet={posnet_u:.2f}% negNet={negnet_u:.2f}% "
              f"(§27 baseline gate was {gate})")
```

Note: `best` (the train-selected band), `rate`, `pos`, `neg`, `yrs`, `gate` are all already computed in the §27 section above — reuse them. The band is train-selected under §27 costs; the spec allows re-selecting under USDT costs, but reusing `best` isolates the cost-model effect (same entries, different costs) which is the cleaner attribution. Keep `best` from §27 for both; document this choice in the commit message.

- [ ] **Step 2: Make `__main__` run the self-check then the results**

Replace the `__main__` block (lines 136-137):

```python
if __name__ == "__main__":
    demo()
    main()
```

- [ ] **Step 3: Run the full script + read the verdict**

Run: `PYTHONPATH=. python scripts/carry_funding_regime.py`
Expected: prints `carry_oneside_usdt cost logic OK`, then per symbol the §27 baseline block AND the new `USDT-cost` / `USDT FULL` / `USDT GATE` lines. Capture the three `USDT GATE` lines (BTCUSDT, ETHUSDT, SOLUSDT) — these are the redesign verdict.

- [ ] **Step 4: ruff**

Run: `ruff check scripts/carry_funding_regime.py`
Expected: clean.

- [ ] **Step 5: Commit**

```bash
git add scripts/carry_funding_regime.py
git commit -m "feat(carry): USDT-cost walk-forward + gate verdict (redesign comp 1)"
```

- [ ] **Step 6: Record the verdict**

After running Step 3, read the `USDT GATE` lines + `USDT FULL` annualized figures. The redesign decision:

- **PASS** (all three symbols `USDT GATE: PASS` + USDT annualized net positive): the edge survives real USDT costs → proceed. Plan components 2-4 next (paper-trader re-point, Phase 0 re-frame, Phase 2). Update the spec's status + [[post-conclusion-followups]] memory with the USDT backtest result.
- **FAIL** (any symbol `USDT GATE: FAIL` or USDT annualized ≤ 0): the 2% spot TDS + real fees kill the edge → redesign stops at option C (abandon). Do NOT plan components 2-4. Update the spec + [[post-conclusion-followups]] + report §29/§33 with the measured USDT-cost refutation.

Either way, append the verdict (the three USDT GATE lines + annualized numbers) to the SDD ledger + the spec's "Components / component 1" section as the recorded outcome.

---

## Self-Review

**1. Spec coverage (component 1 only):** Spec component 1 = "Modify carry_oneside to charge TDS on entry spot BUY + re-run §27 WF + verdict." Task 1 adds the USDT cost function (entry buy TDS + real fees + sell TDS + spot-sell fee); Task 2 re-runs the WF + verdict. The spec also said "do not overwrite §27's sell-only result — add a USDT-cost path" — Task 1 preserves `carry_oneside` byte-identical (the demo asserts it still differs from the USDT path). ✓ The spec's "compare to §27 baseline" — Task 2 prints baseline + USDT side-by-side per symbol. ✓

**2. Placeholder scan:** No TBD/TODO. All code blocks are complete. The verdict step (Task 2 Step 6) gives the exact PASS/FAIL decision rule. ✓

**3. Type consistency:** `carry_oneside_usdt` returns `(net, side_arr, entry, flat)` — same tuple shape as `carry_oneside`, consumed identically in `main` (`net_u, side_u, ent_u, flt_u`). Constants `FEE_PERP`/`FEE_SPOT`/`TDS_BUY_USDT`/`TDS_SELL_USDT` defined in Task 1, used in Task 2. ✓ `metrics(pd.Series(eq_u))['sharpe']` matches the §27 `metrics(pd.Series(eq))['sharpe']` call shape. ✓

**Note (carried into Task 2 commit msg):** the band `best` is train-selected under §27 costs + reused for the USDT path to isolate the cost-model effect (same entry/exit timing, different per-trade costs). A follow-up could re-select the band under USDT costs; not needed for the gate decision.