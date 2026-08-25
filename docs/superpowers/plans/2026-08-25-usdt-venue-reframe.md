# USDT carry redesign — Phase 0 venue re-frame (component 3) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Re-frame `venue_verify.py` so the Phase 0 gate matches the USDT-margin structure: the fx_conversion probe (INR-margin leak) is N/A for USDT, replaced by a `usdt_wallet` probe (USDT futures wallet live + funded — the USDT-path equivalent of "no FX leak"). Add a `--margin {usdt,inr}` flag; USDT verdict = 6 venue probes + usdt_wallet, `redesign_required=False` (no FX leg). The live USDT run is expected to FAIL on `usdt_wallet` until the user funds a USDT futures margin wallet (account/UI action, not API) — that is the honest gate.

**Architecture:** Single file `scripts/venue_verify.py`. Add `usdt_wallet` probe. Parameterize `instrument_spot` with a `spot_pair` (BTCUSDT for USDT, BTCINR for legacy INR) + record the doc-derived spot fee (no public spot-fee endpoint exists; true fee confirmation is a forward Phase-2-fill caveat). Build the probe set per `--margin`: USDT = [auth, perp, spot(BTCUSDT), funding, basis, rate, usdt_wallet] (fx_conversion NOT run — it's an INR-path probe); INR = the existing 7. Verdict branches on margin: USDT `redesign_required=False`; INR keeps the current fx-conversion-gating logic. Then run it live on the box (expected: 6 venue probes PASS, usdt_wallet FAIL → gate FAIL pending wallet funding).

**Tech Stack:** Python 3.12. scripts/ convention: `__main__` assert demo() (NO pytest). ruff line-length 100. `asyncio.run` for live probes.

**Spec:** docs/superpowers/specs/2026-08-25-usdt-carry-redesign-design.md (component 3; components 1-2 done — backtest passed, paper-trader re-pointed + deployed USDT).

## Global Constraints

- Python 3.12, ruff line-length 100.
- scripts/ → `__main__` assert demo() (NO pytest). Non-trivial logic leaves ONE runnable self-check.
- USDT margin has NO INR conversion → fx_conversion is an INR-path probe, NOT run for `--margin usdt`. `redesign_required` is False for the USDT path (no FX leg).
- USDT gate = [auth_liveness, instrument_perp, instrument_spot(BTCUSDT), funding_accrual, basis_proxy, rate_limit, usdt_wallet] all PASS.
- `usdt_wallet` PASS = a USDT wallet exists in `get_wallets()` with `balance > 0`. Funding the USDT margin wallet is an account/UI action only the user can do (not API) — a FAIL here is the expected blocker, not a code bug.
- Spot fee (~0.169%+GST, §29 BTCINR-derived) has NO public verification endpoint → `instrument_spot` records the doc fee as `detail` + notes the Phase-2-fill caveat. Do NOT invent a fee endpoint.
- `--live` guard in `carry_trader.py` reads `venue_verify.json` verdict — the USDT gate's `verdict` field stays "PASS"/"FAIL" so that guard is unchanged. The gate's `margin` field is new metadata.
- Do NOT touch `coindcx-venue.service` / `coindcx_venue_recorder.py` on the box.

---

## File Structure

- **Modify:** `scripts/venue_verify.py` — add `usdt_wallet` probe; parameterize `instrument_spot(spot_pair="BTCUSDT")`; add `_probes(margin)` builder (functools.partial for instrument_spot); extend `verdict(results, margin)` + `write_gate` (margin field); add `--margin` CLI to `main()`/`_run_live`; extend `demo()` with usdt_wallet + USDT-verdict cases.

Single file, two tasks: Task 1 probes + verdict + demo; Task 2 CLI + live box run (expected usdt_wallet FAIL).

---

### Task 1: usdt_wallet probe + instrument_spot param + verdict branch + demo

**Files:**
- Modify: `scripts/venue_verify.py` — add `usdt_wallet` (after fx_conversion, ~line 148); change `instrument_spot` (lines 81-94) signature + body; add `_probes(margin)` + replace `PROBES`/`run_probes`; extend `verdict` (194-204) + `write_gate` (207-213); extend `demo()` (259-328).

**Interfaces:**
- Consumes: `client.get_wallets()` (returns list of wallet dicts with `currency`/`balance`/`locked`), `client.get_last_price(spot_pair)`.
- Produces: `usdt_wallet` ProbeResult; `verdict(results, margin="usdt")` returns dict with `margin` field; `_probes(margin)` returns the probe list. Consumed by Task 2's `_run_live`/`main`.

- [ ] **Step 1: Add `usdt_wallet` probe (after `fx_conversion`, ~line 148)**

Insert after the `_gap_bps` helper (line 171) or after `fx_conversion` — place it right before `basis_proxy` for logical grouping. Insert:

```python
# --- probe 5b: USDT futures wallet live + funded (USDT-path "no FX leak" equivalent) ---
async def usdt_wallet(client) -> ProbeResult:
    """USDT-margin path has no INR conversion, so the fx_conversion leak is N/A.
    The USDT-path equivalent of 'no FX leak' is a live, funded USDT futures
    margin wallet. PASS = a USDT wallet exists with balance > 0. FAIL = absent or
    zero — funding the USDT margin wallet is an account/UI action (not API-doable);
    a FAIL here is the expected blocker pending the user funding it, not a bug."""
    try:
        wallets = await client.get_wallets()
        rows = wallets if isinstance(wallets, list) else [wallets]
        usdt = None
        for w in rows:
            cur = str(w.get("currency") or w.get("asset") or "").upper()
            if cur == "USDT":
                usdt = w
                break
        if usdt is None:
            return ProbeResult("usdt_wallet", False, {"usdt_wallet": None},
                               "no USDT wallet — fund USDT futures margin via account UI (not API)")
        bal = float(usdt.get("balance") or 0)
        passed = bal > 0
        return ProbeResult("usdt_wallet", passed,
                           {"usdt_balance": bal, "locked": usdt.get("locked")},
                           None if passed else
                           "USDT wallet balance=0 — fund it via account UI (not API)")
    except Exception as e:  # noqa: BLE001
        return ProbeResult("usdt_wallet", False, error=f"{type(e).__name__}: {e}")
```

- [ ] **Step 2: Parameterize `instrument_spot` with `spot_pair`**

Replace the existing `instrument_spot` (lines 81-94):

```python
# --- probe 3: spot leg liveness (BTCUSDT for USDT redesign; BTCINR legacy) ---
async def instrument_spot(client, spot_pair: str = "BTCUSDT") -> ProbeResult:
    """Spot hedge-leg liveness for `spot_pair`. Spot fee is doc-derived (~0.169%
    +GST, §29 BTCINR-derived) — CoinDCX exposes no public spot-fee endpoint, so
    this verifies ticker liveness + records the doc fee; true fee confirmation is
    a forward Phase-2-fill caveat (component 4)."""
    try:
        px = await client.get_last_price(spot_pair)
        DOC_SPOT_FEE_PCT = 0.169  # §29 BTCINR-derived; verify BTCUSDT via real fill in Phase 2
        detail = {"last_price": px, "spot_pair": spot_pair,
                  "doc_spot_fee_pct": DOC_SPOT_FEE_PCT,
                  "note": "spot fee doc-derived; confirm via real fill in Phase 2"}
        return ProbeResult("instrument_spot", px > 0, detail,
                           None if px > 0 else f"{spot_pair} ticker returned 0/None")
    except Exception as e:  # noqa: BLE001
        return ProbeResult("instrument_spot", False, error=f"{type(e).__name__}: {e}")
```

- [ ] **Step 3: Replace `PROBES`/`run_probes` with a margin-aware builder**

Replace the `PROBES` list + `run_probes` (lines 186-191):

```python
def _probes(margin: str = "usdt"):
    """Probe set per margin path. USDT: 6 venue probes + usdt_wallet (fx_conversion
    is an INR-path probe, not run for USDT — USDT margin has no INR conversion).
    INR: the legacy 7 (fx_conversion gating). instrument_spot's spot_pair follows
    the margin path (BTCUSDT / BTCINR)."""
    import functools
    spot = "BTCUSDT" if margin == "usdt" else "BTCINR"
    spot_probe = functools.partial(instrument_spot, spot_pair=spot)
    base = [auth_liveness, instrument_perp, spot_probe,
            funding_accrual, basis_proxy, rate_limit]
    if margin == "usdt":
        return base + [usdt_wallet]
    return [auth_liveness, instrument_perp, spot_probe,
            funding_accrual, fx_conversion, basis_proxy, rate_limit]


async def run_probes(client, margin: str = "usdt") -> list[ProbeResult]:
    return [await p(client) for p in _probes(margin)]
```

- [ ] **Step 4: Extend `verdict` with margin branch**

Replace `verdict` (lines 194-204):

```python
def verdict(results: list[ProbeResult], margin: str = "usdt") -> dict:
    if margin == "usdt":
        # USDT path: no INR conversion -> no FX leg -> redesign_required always
        # False. fx_conversion is not in the USDT probe set; gate = all run probes.
        all_pass = all(r.passed for r in results)
        fails = [r.name for r in results if not r.passed]
        return {"verdict": "PASS" if all_pass else "FAIL",
                "redesign_required": False, "margin": "usdt",
                "fail_reason": None if all_pass else f"failed probes: {fails}"}
    # INR legacy path: fx_conversion gap is the §29 crux + gates redesign.
    all_pass = all(r.passed for r in results)
    fx = next((r for r in results if r.name == "fx_conversion"), None)
    redesign = bool(fx and not fx.passed and fx.detail.get("mean_gap_bps") is not None)
    fail_reason = None
    if not all_pass:
        fails = [r.name for r in results if not r.passed]
        fail_reason = "fx_conversion gap >= threshold" if "fx_conversion" in fails and redesign \
            else f"failed probes: {fails}"
    return {"verdict": "PASS" if all_pass else "FAIL",
            "redesign_required": redesign, "margin": "inr", "fail_reason": fail_reason}
```

- [ ] **Step 5: Extend `write_gate` to record margin**

In `write_gate` (line 209), the `out` dict spreads `**vdict` which now includes `margin` — no change needed (margin flows through automatically). Verify by reading: the `out = {"timestamp": ..., **vdict, ...}` already carries margin. No edit required. (If `margin` is absent in an old INR vdict it's fine — `verdict` always sets it now.)

- [ ] **Step 6: Extend `demo()` with usdt_wallet + USDT-verdict cases**

In `demo()`, after the existing `r3 = asyncio.run(instrument_spot(FakeClient()))` block (line 281-282), add a USDT spot-pair check + the usdt_wallet probe + USDT verdict. Insert after the `r3` assertions:

```python
    # USDT re-point: instrument_spot takes spot_pair (BTCUSDT liveness)
    r3u = asyncio.run(instrument_spot(FakeClient(), spot_pair="BTCUSDT"))
    assert r3u.passed and r3u.detail["spot_pair"] == "BTCUSDT" and \
        r3u.detail["doc_spot_fee_pct"] == 0.169, r3u
    # usdt_wallet probe: funded -> PASS; absent/zero -> FAIL (expected blocker)
    class WalletClient(FakeClient):
        async def get_wallets(self):
            return [{"currency": "INR", "balance": 50000},
                    {"currency": "USDT", "balance": 120.0, "locked": 0}]
    rw = asyncio.run(usdt_wallet(WalletClient()))
    assert rw.passed and rw.detail["usdt_balance"] == 120.0, rw
    class NoUsdtWallet(FakeClient):
        async def get_wallets(self): return [{"currency": "INR", "balance": 50000}]
    rw2 = asyncio.run(usdt_wallet(NoUsdtWallet()))
    assert not rw2.passed and "fund USDT" in (rw2.error or ""), rw2
    class ZeroUsdtWallet(FakeClient):
        async def get_wallets(self): return [{"currency": "USDT", "balance": 0}]
    rw3 = asyncio.run(usdt_wallet(ZeroUsdtWallet()))
    assert not rw3.passed and "balance=0" in (rw3.error or ""), rw3
    # USDT verdict: all-pass (incl usdt_wallet) -> PASS, redesign_required False
    usdt_results = [
        ProbeResult("auth_liveness", True), ProbeResult("instrument_perp", True),
        ProbeResult("instrument_spot", True), ProbeResult("funding_accrual", True),
        ProbeResult("basis_proxy", True), ProbeResult("rate_limit", True),
        ProbeResult("usdt_wallet", True, {"usdt_balance": 120.0})]
    vu = verdict(usdt_results, margin="usdt")
    assert vu["verdict"] == "PASS" and vu["redesign_required"] is False and \
        vu["margin"] == "usdt", vu
    # USDT verdict: usdt_wallet FAIL -> gate FAIL (not redesign — no FX leg)
    usdt_fail = [r if r.name != "usdt_wallet" else
                 ProbeResult("usdt_wallet", False, {"usdt_balance": 0}, "balance=0") for r in usdt_results]
    vuf = verdict(usdt_fail, margin="usdt")
    assert vuf["verdict"] == "FAIL" and vuf["redesign_required"] is False, vuf
    # _probes margin selector: usdt set has usdt_wallet, no fx_conversion; inr set has fx_conversion
    usdt_names = [p.func.__name__ if hasattr(p, "func") else p.__name__ for p in _probes("usdt")]
    inr_names = [p.func.__name__ if hasattr(p, "func") else p.__name__ for p in _probes("inr")]
    assert "usdt_wallet" in usdt_names and "fx_conversion" not in usdt_names, usdt_names
    assert "fx_conversion" in inr_names and "usdt_wallet" not in inr_names, inr_names
```

(The existing demo's `crafted`/`verdict(crafted)` calls at line 313 use the default `margin="usdt"` now — but `crafted` includes an `fx_conversion` result. Under USDT verdict, fx_conversion is just ignored (gate = all run probes, fx not in USDT set but the verdict's `all(r.passed for r in results)` would include it if passed). The existing `crafted` has fx_conversion PASS, so `verdict(crafted, margin="usdt")` → all pass → PASS, redesign_required=False. The existing assertion `v["verdict"]=="PASS" and v["redesign_required"] is False` STILL HOLDS. The `crafted_fx_fail` case: `verdict(crafted_fx_fail, margin="usdt")` → fx_conversion FAIL → `all_pass=False` → verdict FAIL, redesign_required=False. But the existing assertion (line 320) checks `vf["verdict"]=="FAIL" and vf["redesign_required"] is True` — that BREAKS under the new USDT default (redesign_required is now False for USDT). FIX: the existing INR-verdict demo cases must call `verdict(..., margin="inr")` to preserve their meaning. Update lines 313 + 320 to pass `margin="inr"`.)

- [ ] **Step 7: Fix the existing INR-verdict demo calls to pass `margin="inr"`**

At line 313: `v = verdict(crafted)` → `v = verdict(crafted, margin="inr")`. At line 319-320: `vf = verdict(crafted_fx_fail)` → `vf = verdict(crafted_fx_fail, margin="inr")`. (These exercise the INR fx-conversion-gating logic, which now lives under `margin="inr"`.)

- [ ] **Step 8: Run the demo to verify**

Run: `PYTHONPATH=. python scripts/venue_verify.py`
Expected: PASS — prints `venue_verify all probes + gate OK`.

- [ ] **Step 9: ruff + commit**

```bash
ruff check scripts/venue_verify.py
git add scripts/venue_verify.py
git commit -m "feat(venue): USDT-margin Phase 0 re-frame (redesign comp 3)

Add usdt_wallet probe (USDT-path 'no FX leak' equivalent — funded USDT
futures wallet; funding is a user account/UI action, not API). Parameterize
instrument_spot(spot_pair) — BTCUSDT for USDT, BTCINR legacy; records the
doc-derived spot fee (no public fee endpoint; Phase-2-fill caveat). --margin
{usdt,inr} selects the probe set: USDT = 6 venue + usdt_wallet (fx_conversion
is INR-only, not run); INR = legacy 7. USDT verdict redesign_required=False
(no FX leg). Demo covers usdt_wallet + both verdict paths.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2: `--margin` CLI + live box run (expected usdt_wallet FAIL)

**Files:**
- Modify: `scripts/venue_verify.py` — `main()` (250-256) + `_run_live` (240-247).
- Run on box: `python scripts/venue_verify.py run --margin usdt` (needs `.env` API keys, present on box).

- [ ] **Step 1: Add `--margin` to `main()` + pass to `_run_live`**

Replace `main()` (lines 250-256):

```python
def main() -> None:
    import argparse
    import asyncio
    import sys
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", nargs="?", default="demo",
                    help="'run' = live probes -> venue_verify.json; else demo")
    ap.add_argument("--margin", choices=["usdt", "inr"], default="usdt",
                    help="margin path: usdt (redesign, no FX leg) or inr (legacy, fx_conversion gating)")
    args = ap.parse_args()
    if args.cmd == "run":
        asyncio.run(_run_live(args.margin))
    else:
        demo()
```

Replace `_run_live` (lines 240-247):

```python
async def _run_live(margin: str = "usdt") -> None:
    from app.exchange.coindcx import CoinDCXClient
    async with CoinDCXClient() as client:
        results = await run_probes(client, margin)
    v = verdict(results, margin)
    write_gate(results, v)
    print(f"venue_verify [{margin}] {v['verdict']} -> {GATE_PATH} "
          f"(redesign_required={v['redesign_required']})")
```

Note: this changes the CLI from `venue_verify.py run` (positional) to `venue_verify.py run --margin usdt`. The positional `cmd` preserves `run` (and bare invocation → demo). `carry_trader.py`'s `--live` guard reads `venue_verify.json` verdict — unaffected (verdict field unchanged).

- [ ] **Step 2: Run demo + ruff + commit**

```bash
PYTHONPATH=. python scripts/venue_verify.py   # demo, expect 'venue_verify all probes + gate OK'
PYTHONPATH=. python scripts/venue_verify.py --margin usdt   # demo (cmd defaults to demo)
ruff check scripts/venue_verify.py
git add scripts/venue_verify.py
git commit -m "feat(venue): --margin CLI for USDT/INR Phase 0 gate (comp 3)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

- [ ] **Step 3: scp to box + run live (expected: usdt_wallet FAIL pending wallet funding)**

```bash
scp -i ~/Downloads/ssh-key-2026-08-07.key scripts/venue_verify.py ubuntu@140.245.19.185:~/Trading/scripts/venue_verify.py
ssh -i ~/Downloads/ssh-key-2026-08-07.key ubuntu@140.245.19.185 '
  cd ~/Trading && PYTHONPATH=. .venv/bin/python scripts/venue_verify.py run --margin usdt 2>&1 | tail -20'
```
Expected: 6 venue probes PASS (auth, perp fee 5.9bps, BTCUSDT spot, funding-accrual, basis-proxy, rate-limit) + `usdt_wallet FAIL` (no USDT wallet / balance=0) → `verdict [usdt] FAIL (redesign_required=False)`. The FAIL is the expected blocker pending the user funding a USDT futures margin wallet — NOT a code bug. If a venue probe errors unexpectedly, diagnose before proceeding.

- [ ] **Step 4: Record the live USDT verdict**

Append to `.superpowers/sdd/2026-08-25-usdt-carry-redesign-backtest/progress.md`: the live `--margin usdt` result (which probes passed, usdt_wallet FAIL reason). Note the gate is BLOCKED on the user funding a USDT futures margin wallet (account/UI action). Component 4 (Phase 2 small-real) is gated on this wallet + a fresh USDT PASS + paper_check clean ≥7d.

---

## Self-Review

**1. Spec coverage (component 3):** Spec = "fx_conversion N/A for USDT → USDT-wallet-live check; keep 6 probes; add BTCUSDT spot-fee verify; instrument_perp leverage read max_leverage_short; verdict USDT PASS = 6 + USDT-wallet, redesign_required False." Task 1 adds usdt_wallet (USDT-wallet-live), parameterizes instrument_spot (BTCUSDT + doc spot fee), _probes margin builder (USDT = 6 + usdt_wallet, no fx_conversion), verdict branch (redesign_required False for USDT). Task 2 adds --margin CLI + live run. The instrument_perp leverage point: the probe already handles null leverage (lev_ok = lev is None or ...); the spec's "read max_leverage_short" is an informative improvement — the current code reads `inst.get("leverage") or inst.get("max_leverage")` which already catches max_leverage. No change needed (already covered). ✓

**2. Placeholder scan:** No TBD/TODO. All code blocks complete. The live-run expected outcome (usdt_wallet FAIL) is explicit. ✓

**3. Type consistency:** `instrument_spot(client, spot_pair="BTCUSDT")` — demo's existing `instrument_spot(FakeClient())` call still works (default spot_pair). `functools.partial(instrument_spot, spot_pair=spot)` → `await p(client)` calls `instrument_spot(client, spot_pair=spot)`. ✓ `verdict(results, margin="usdt")` returns `margin` field; `write_gate` spreads vdict (margin flows). `_run_live(margin)` + `run_probes(client, margin)` + `_probes(margin)` — names match across Task 1/2. ✓ The `_probes` name-extraction in the demo (`p.func.__name__ if hasattr(p, "func") else p.__name__`) handles both partials + plain functions. ✓

**Note (carried into Task 2 commit msg):** the live USDT run is EXPECTED to FAIL on usdt_wallet until the user funds a USDT futures margin wallet. That's the honest gate, not a bug. Component 4 is blocked on it.