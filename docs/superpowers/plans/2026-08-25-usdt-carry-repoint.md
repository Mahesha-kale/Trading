# USDT carry redesign — paper-trader re-point (component 2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Re-point the deployed paper-trader from INR-margin/BTCINR accounting to USDT-margin/BTCUSDT accounting, so its paper PnL is honest (no 250bps INR-FX-leak optimism) and it mirrors the USDT structure that survived the component-1 cost gate.

**Architecture:** The recorder already computes `synth = spot_inr/usdtinr` (synthetic BTCUSDT) + `basis_bps = mp/synth - 1` (perp USDT-mark vs synthetic USDT spot — already USDT-correct). So the re-point is a unit change in `carry_trader.py`: `FeedSample.spot_price` becomes BTCUSDT (`spot_inr/usdtinr`) instead of BTCINR; all downstream accounting (qty, entry_spot, funding accrual, basis MTM, equity, peak/capital) follows in USDT. No recorder change (feed option a — derive BTCUSDT from existing fields; arbitrage keeps BTCINR/USDTINR ≈ BTCUSDT, and for paper MTM with no orders the cross-rate residual is immaterial). The §29 FX-leg residual framing is removed — the USDT structure has no FX leg. Then redeploy to the Oracle box with a state/ledger reset (units change).

**Tech Stack:** Python 3.12, numpy. scripts/ convention: `__main__` assert demo() (NO pytest). ruff line-length 100.

**Spec:** docs/superpowers/specs/2026-08-25-usdt-carry-redesign-design.md (component 2; component 1 PASSED — costs survived).

## Global Constraints

- Python 3.12, ruff line-length 100.
- scripts/ → `__main__` assert demo() (NO pytest). Non-trivial logic leaves ONE runnable self-check.
- `FeedSample.spot_price` semantics change BTCINR → BTCUSDT (= `spot_inr / usdtinr`). `usdtinr` field retained for diagnostics.
- `basis_bps` is already USDT-correct (recorder: perp USDT mark vs synthetic USDT spot) — NO change to basis handling.
- `--capital` default changes 100_000 INR → 1000 USDT (document the unit change). `--spot-pair` default BTCINR → BTCUSDT. `--pair` stays `B-BTC_USDT` (same contract; margin currency is chosen at the exchange level, not the pair).
- No-orders invariant unchanged: paper places no orders (`live and client is not None` guard). Notional qty for PnL as before.
- Do NOT touch `scripts/coindcx_venue_recorder.py` / `coindcx-venue.service` on the box (proven uptime; the recorder is currency-agnostic — it already emits the USDT-correct basis + the spot_inr/usdtinr fields we derive from).
- Re-point RESETS the running paper run: the INR state.json + carry_paper.csv are unit-incompatible → delete + restart. The INR run was already known-optimistic/invalid-for-deployment per the Phase 0 FAIL, so no data loss that mattered.
- Fail-safe unchanged: 25% portfolio DD → flatten + halt; flatten + halt on every fault; `--live` guarded by `trading_mode=="live"` AND venue gate. Paper mode (`--live` absent) places no orders.

---

## File Structure

- **Modify:** `scripts/carry_trader.py` — feed (`_paper_feed`, `csv_feed`): `spot_price = spot_inr/usdtinr`; `FeedSample` docstring; `_basis_mtm`/`_mark_equity` comments (remove §29 FX-leg framing); `main()` argparse defaults (`--capital` 1000, `--spot-pair` BTCUSDT) + capital-unit doc; demos (`_demo_paper_pnl`, `_demo_feed`, `_demo_faults`) USDT unit values.
- **Deploy (Task 3):** Oracle box `~/Trading/scripts/carry_trader.py` via rsync; reset `reports/carry_trader_state.json` + `reports/carry_paper.csv`; restart `carry-trader.service`; verify USDT accounting in logs.

Single source file + a deploy. Three tasks: Task 1 feed+accounting+comments, Task 2 argparse+main, Task 3 deploy.

---

### Task 1: feed + accounting INR→USDT + comment/demo updates

**Files:**
- Modify: `scripts/carry_trader.py` — `_paper_feed` (lines 609-624), `csv_feed` (627-653), `FeedSample` docstring (33-39), `_basis_mtm` (192-196), `_mark_equity` (163-169), `_demo_paper_pnl` (348-420), `_demo_feed` (478-549), `_demo_faults` (561-579).

**Interfaces:**
- Consumes: recorder CSV/sample fields `spot_inr`, `usdtinr` (already present, unchanged).
- Produces: `FeedSample.spot_price` now in USDT (= `spot_inr/usdtinr`). Downstream `_enter_short`, `_accrue_funding`, `_basis_mtm`, `_mark_equity`, `position_size` call unchanged — they consume `s.spot_price`/`st.entry_spot`, now USDT-denominated.

- [ ] **Step 1: Update `_paper_feed` — spot_price = spot_inr/usdtinr**

In `_paper_feed` (line 622-623), change the `spot_price=` argument from `float(sinr)` to the synthetic BTCUSDT. Replace:

```python
        return FeedSample(ts=int(r["ts"]), fr=float(fr), efr=float(r.get("efr") or 0.0),
                          basis_bps=float(bb), spot_price=float(sinr), usdtinr=float(uinr))
```

with:

```python
        # USDT re-point: spot_price is synthetic BTCUSDT = spot_inr/usdtinr (the
        # recorder's own `synth`), so all downstream accounting is USDT-denominated.
        # basis_bps is already USDT-correct (perp USDT mark vs this synth).
        return FeedSample(ts=int(r["ts"]), fr=float(fr), efr=float(r.get("efr") or 0.0),
                          basis_bps=float(bb), spot_price=float(sinr) / float(uinr),
                          usdtinr=float(uinr))
```

- [ ] **Step 2: Update `csv_feed` — spot_price = spot_inr/usdtinr**

In `csv_feed` (line 649-651), change `spot_price=float(r["spot_inr"])` to the synthetic. Replace:

```python
        return FeedSample(ts=int(float(r["ts"])), fr=float(r["fr"]), efr=float(r["efr"]),
                          basis_bps=float(r["basis_bps"]), spot_price=float(r["spot_inr"]),
                          usdtinr=float(r["usdtinr"]))
```

with:

```python
        # USDT re-point: spot_price is synthetic BTCUSDT = spot_inr/usdtinr.
        return FeedSample(ts=int(float(r["ts"])), fr=float(r["fr"]), efr=float(r["efr"]),
                          basis_bps=float(r["basis_bps"]),
                          spot_price=float(r["spot_inr"]) / float(r["usdtinr"]),
                          usdtinr=float(r["usdtinr"]))
```

- [ ] **Step 3: Update `FeedSample` docstring**

Change the `spot_price` field comment (line 38) from `# BTCINR spot` to `# BTCUSDT spot (= spot_inr/usdtinr)`:

```python
    spot_price: float   # BTCUSDT spot (= spot_inr/usdtinr)
    usdtinr: float
```

- [ ] **Step 4: Update `_basis_mtm` + `_mark_equity` comments (remove §29 FX-leg framing)**

In `_mark_equity` (lines 164-166), the comment says basis_mtm is "the §29 FX leg" — for USDT there is no FX leg. Replace the comment block:

```python
    # paper PnL equity: peak + accrued funding (8h marks) + unrealized basis MTM.
    # Replaces the sub-project-1 placeholder. Real MTM deferred to Phase 2 live fills in
    # the perp/spot leg fills; here basis_mtm is the delta-neutral residual (the §29 FX leg).
```

with:

```python
    # paper PnL equity (USDT): peak + accrued funding (8h marks) + unrealized basis
    # MTM. USDT structure has NO §29 FX leg (no INR conversion); basis_mtm is the
    # pure perp-vs-BTCUSDT-spot basis residual. Real MTM deferred to Phase 2 live fills.
```

In `_basis_mtm` (line 193), change `# Unrealized basis/FX MTM on the open delta-neutral position (INR). 0 when flat.` to:

```python
    """Unrealized basis MTM on the open delta-neutral position (USDT). 0 when flat."""
```

- [ ] **Step 5: Update `_demo_paper_pnl` to USDT units**

The demo uses `entry_spot=9_000_000`/`spot_price=9_000_000` (INR BTC) → change to `100_000` (USDT BTC). `usdtinr=90` stays. `peak_equity=100_000` stays (now USDT). `qty=0.1` stays. The derived expected values change: accrual `0.1*0.0003*100_000 = 3.0` (was 270), basis_mtm `0.1*0.0005*100_000 = 5.0` (was 450), equity `100_000+3+5 = 100_008.0` (was 100_720). Apply these specific edits:

- Line 351-352: `entry_perp=9_000_000, entry_spot=9_000_000` → `entry_perp=100_000, entry_spot=100_000`
- Line 354: `s_seed = FeedSample(... spot_price=9_000_000, usdtinr=90)` → `spot_price=100_000`
- Line 361: `s_mark = FeedSample(... spot_price=9_000_000, usdtinr=90)` → `spot_price=100_000`
- Line 363: `assert abs(st.accrued_funding - 270.0) < 1e-6` → `abs(st.accrued_funding - 3.0) < 1e-6`
- Line 367-368: the same-mark sample `spot_price=9_000_000` → `100_000`
- Line 375: `s_gap = FeedSample(... spot_price=9_000_000, ...)` → `spot_price=100_000`
- Line 378: `abs(st_gap.accrued_funding - 270.0)` → `abs(st_gap.accrued_funding - 3.0)`
- Line 381: `abs(_basis_mtm(st, s_mark) - 450.0)` → `abs(_basis_mtm(st, s_mark) - 5.0)`
- Line 383: `abs(_mark_equity(st, s_mark) - 100_720.0)` → `abs(_mark_equity(st, s_mark) - 100_008.0)`
- Line 394: `samp = FeedSample(... spot_price=9_000_000, usdtinr=90)` → `spot_price=100_000`
- Line 408: `s_ent = FeedSample(... spot_price=9_000_000, ...)` → `spot_price=100_000`

- [ ] **Step 6: Update `_demo_feed` USDT assertion**

The good sample has `spot_inr: 2700000, usdtinr: 90` → `spot_price = 30000` (USDT). Line 497: `assert ... s.spot_price == 2700000` → `s.spot_price == 30000`. The BTC interleaving regression (line 526-527): `s3.spot_price == 2700000.0` → `s3.spot_price == 30000.0` (the BTC row spot_inr=2700000/usdtinr=90 = 30000).

- [ ] **Step 7: Update `_demo_faults` spot_price**

Line 572: `s = FeedSample(... spot_price=9_000_000, usdtinr=90)` → `spot_price=100_000`.

- [ ] **Step 8: Run the demo to verify**

Run: `PYTHONPATH=. python scripts/carry_trader.py`
Expected: PASS — prints `carry_trader signal OK`, `paper-pnl OK`, `tilt OK`, `venue OK`, `feed OK`, `sign OK`, `faults OK`, `reconcile OK`. (No args → runs `demo()`.)

- [ ] **Step 9: ruff**

Run: `ruff check scripts/carry_trader.py`
Expected: no NEW errors (pre-existing RUF010/I001 may remain — leave per "do not modify §27-style pre-existing").

- [ ] **Step 10: Commit**

```bash
git add scripts/carry_trader.py
git commit -m "feat(carry): re-point paper-trader accounting INR->USDT (redesign comp 2)

FeedSample.spot_price is now synthetic BTCUSDT = spot_inr/usdtinr (the
recorder's own synth); basis_bps was already USDT-correct. All downstream
accounting (qty, entry_spot, funding accrual, basis MTM, equity) follows in
USDT. Removed the §29 FX-leg framing — the USDT structure has no INR
conversion. Demos updated to USDT units (BTC \$100k). No recorder change.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2: argparse defaults — capital USDT, spot-pair BTCUSDT

**Files:**
- Modify: `scripts/carry_trader.py` — `main()` argparse (lines 656-672).

- [ ] **Step 1: Change `--capital` + `--spot-pair` defaults**

In `main()` (lines 661-663), replace:

```python
    ap.add_argument("--capital", type=float, default=100_000.0)
    ap.add_argument("--pair", default="B-BTC_USDT")
    ap.add_argument("--spot-pair", default="BTCINR")
```

with:

```python
    ap.add_argument("--capital", type=float, default=1000.0,
                    help="paper capital in USDT (USDT-margin re-point; was INR)")
    ap.add_argument("--pair", default="B-BTC_USDT")
    ap.add_argument("--spot-pair", default="BTCUSDT")
```

- [ ] **Step 2: Run demo + a CLI smoke (paper, no orders)**

Run: `PYTHONPATH=. python scripts/carry_trader.py`  (demo, expect PASS as in Task 1 Step 8).
Then smoke the argparse (it will try the REST feed / loop — kill after a moment, just confirm it parses + starts):
Run: `PYTHONPATH=. timeout 5 python scripts/carry_trader.py --feed csv 2>&1 | head -5` (or run ~5s then interrupt).
Expected: starts without argparse error; `--capital` default 1000, `--spot-pair` BTCUSDT in cfg. (A feed outage / no-CSV exit is fine — we only check it parses + starts.)

- [ ] **Step 3: ruff + commit**

```bash
ruff check scripts/carry_trader.py
git add scripts/carry_trader.py
git commit -m "feat(carry): argparse defaults --capital 1000 USDT, --spot-pair BTCUSDT (comp 2)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 3: deploy to Oracle box + reset state/ledger + verify

**Files:**
- Deploy: `scripts/carry_trader.py` → `ubuntu@140.245.19.185:~/Trading/scripts/carry_trader.py` (rsync mirror).
- Reset on box: `~/Trading/reports/carry_trader_state.json`, `~/Trading/reports/carry_paper.csv` (unit-incompatible with the USDT re-point).
- Restart: `carry-trader.service` (systemd).

**SSH key:** `~/Downloads/ssh-key-2026-08-07.key`. **Do NOT touch** `coindcx-venue.service` / `coindcx_venue_recorder.py`.

- [ ] **Step 1: rsync the updated carry_trader.py to the box**

```bash
rsync -avz -e "ssh -i ~/Downloads/ssh-key-2026-08-07.key" scripts/carry_trader.py ubuntu@140.245.19.185:~/Trading/scripts/carry_trader.py
```

- [ ] **Step 2: Reset the INR state.json + paper ledger (units change) + restart service**

```bash
ssh -i ~/Downloads/ssh-key-2026-08-07.key ubuntu@140.245.19.185 '
  cd ~/Trading &&
  cp reports/carry_trader_state.json reports/carry_trader_state.inr.bak 2>/dev/null;
  cp reports/carry_paper.csv reports/carry_paper.inr.bak 2>/dev/null;
  rm -f reports/carry_trader_state.json reports/carry_paper.csv reports/carry_trader.HALT;
  sudo systemctl restart carry-trader.service &&
  sleep 3 && systemctl is-active carry-trader.service'
```
Expected: `active`. The `.inr.bak` files preserve the old INR run for the record.

- [ ] **Step 3: Verify USDT accounting in the logs + feed cadence**

```bash
ssh -i ~/Downloads/ssh-key-2026-08-07.key ubuntu@140.245.19.185 '
  cd ~/Trading &&
  journalctl -u carry-trader.service --since "1 min ago" --no-pager | tail -15 &&
  echo "--- ledger ---" &&
  cat reports/carry_paper.csv 2>/dev/null | tail -5'
```
Expected: logs show `band=0.0002`, no crash, feed advancing (last_feed_ts moving at 60s BTC cadence). The first ENTER_SHORT (when fr>band) logs `qty=<USDT-capital/BTCUSDT-spot>` — qty should be ~`1000/100000 = 0.01` BTC-scale, NOT the old `100000/9000000 = 0.0111`-INR-scale (the numbers are coincidentally close, so confirm via the `--capital 1000 USDT` + `--spot-pair BTCUSDT` in the cfg + the USDT spot_price ~100000 in any basis/spot log). If the service is `failed` or logs show a crash, stop + diagnose (do NOT leave a crashlooping service).

- [ ] **Step 4: Record deploy in the SDD ledger**

Append to `.superpowers/sdd/2026-08-25-usdt-carry-redesign-backtest/progress.md` (or the component-2 ledger): deploy verdict — `carry-trader.service` active, USDT accounting, INR state/ledger reset to `.inr.bak`, paper run restarted in USDT. Note the 7-14d USDT paper run begins now (paper_check 5-criteria gate for component 4).

---

## Self-Review

**1. Spec coverage (component 2):** Spec component 2 = "Accounting INR→USDT (peak/capital USDT, funding accrual qty*fr*entry_spot_usdt, basis MTM perp−BTCUSDT, remove §29 FX residual); Feed BTCUSDT (option a derive from recorder fields); --spot-pair BTCUSDT; --capital USDT; no-orders invariant unchanged." Task 1 covers feed+accounting+FX-leg-removal; Task 2 covers argparse defaults; Task 3 covers the deploy + reset. ✓ The spec's "verify synthetic drift > few bps → switch to recorder option (b)" — deferred: the paper-trader is MTM-only (no orders), so cross-rate residual is immaterial to paper PnL; a live BTCUSDT-vs-synthetic comparison belongs in component 3 (Phase 0 re-frame, spot-fee verification), noted in the spec. ✓

**2. Placeholder scan:** No TBD/TODO. All code edits are exact old→new strings. Demo expected values are computed (accrual 3.0, mtm 5.0, equity 100_008). ✓

**3. Type consistency:** `FeedSample.spot_price` stays `float` (now USDT-denominated). `_enter_short`/`_accrue_funding`/`_basis_mtm`/`_mark_equity` consume it unchanged. `position_size(capital,...) / s.spot_price` now yields qty = USDT-capital / BTCUSDT-spot = BTC qty (same formula, USDT units). `--capital` default 1000.0 (USDT). `--spot-pair` BTCUSDT flows to `create_spot_order` (live only, paper-guarded). ✓

**Note (carried into Task 3):** the re-point resets the paper run (INR state/ledger unit-incompatible). The INR run was already known-optimistic/invalid-for-deployment per Phase 0 FAIL — no meaningful data loss. The `.inr.bak` preserves it.