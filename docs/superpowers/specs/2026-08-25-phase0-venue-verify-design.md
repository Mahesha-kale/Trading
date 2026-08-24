# Phase 0 Venue-Verify — Design Spec (sub-project 4)

Date: 2026-08-25
Status: design, pending implementation plan
Goal: a read-only probe harness that verifies CoinDCX perp + spot venue truth against the carry deploy's assumptions, and gates `carry_trader --live` on a data-driven PASS/FAIL verdict. A valid outcome is either (a) `verdict: PASS` → `--live` unlocked for Phase 1 paper / Phase 2 small-real, or (b) `verdict: FAIL` on the FX-conversion probe → `--live` stays locked and a hedge-redesign sub-project (USDT-margined perp to kill the FX leg) is mandated before any live trade. No manual go/no-go decision — the JSON verdict is the gate.

## Background

Sub-project 1 (PR #16) built the hybrid carry trader: delta-neutral funding harvest (SHORT `B-BTC_USDT` perp + LONG `BTCINR` spot), 8h cycle, 25% DD halt, fail-safe flatten+halt, pluggable tilt slot. Sub-project 2 (PR #17) ran the regime-gate tilt sweep → 0/18 pass → `NoTilt`; carry-only deploy (~5-6%/yr) is the only standing edge. The carry trader is built but **not deployed**: `--live` is gated behind `trading_mode=="live"` in `.env` AND (per the research conclusion §27/§29) behind Phase 0 venue-verify → Phase 1 paper → Phase 2 small-real.

The `app/exchange/coindcx.py` client was written against docs.coindcx.com (2026-07) and carries explicit `ponytail: re-check before live money` markers on every load-bearing assumption. Phase 0 is the systematic re-check. It is **read-only**: CoinDCX has no testnet/sandbox, so the order write-path (create_order / exit_position / create_spot_order) cannot be verified without real money and is deferred to Phase 2.

The §29 post-conclusion followup flagged "carry LESS deployable, FX leg." Confirmed: CoinDCX INR-margined perps settle via a platform USDT↔INR *conversion rate* that is **not** spot USDTINR. The delta-neutral hedge (short perp + long BTCINR spot) therefore leaks FX basis whenever `conversion_rate ≠ spot USDTINR`. Phase 0 measures this gap; per the user's decision it is a **gate + redesign trigger** (automated, no manual work).

## Constraints (from user decisions)

- Free public data + retail execution; CoinDCX perp (linear, INR-margined) + BTCINR spot. No testnet exists → Phase 0 is **read-only** (public + private read endpoints only; no order placement).
- **No manual go/no-go:** the `reports/venue_verify.json` `verdict` field is the gate. `carry_trader --live` refuses unless `verdict==PASS` + fresh. No human reads-and-decides step.
- **FX-conversion gate + redesign trigger:** `fx_conversion` probe PASS iff mean gap < 10bps. FAIL → `redesign_required: true` → a separate hedge-redesign sub-project (USDT-margined perp) is mandated before any live trade. The redesign is *triggered*, not built here.
- No real `--live` orders until Phase 0 PASS + Phase 1 paper + Phase 2 small-real. Phase 0 places NO orders.
- Perp carries **no 1% TDS** (TDS is spot-sell only; the perp is naked, the spot leg is the hedge). The spot leg IS subject to TDS on sell — Phase 0 records the spot fee + notes TDS as a known cost on the hedge-leg close (already in the §29 cost model).
- API keys in `.env` via `app.config.settings`, never logged. Fail-safe = flatten+halt on every fault (unchanged from sub-project 1). 25% portfolio DD hard stop (sub-project 1, unchanged).
- `ruff` line-length 100, Python 3.12. `scripts/` → `__main__` assert `demo()` (NO pytest). `app/` + `tests/` → pytest (`asyncio_mode=auto`). gh at `C:\Program Files\GitHub CLI\gh.exe`.

## The probe set (all read-only)

| # | Probe | Source | What it verifies | PASS criterion |
|---|---|---|---|---|
| 1 | `auth_liveness` | REST private read | HMAC signing works; private endpoints live | `get_wallets()` + `get_positions(pair="B-BTC_USDT")` both return 2xx (no `CoinDCXError`) |
| 2 | `instrument_perp` | `get_instrument("B-BTC_USDT")` | perp metadata vs §29 cost model | taker fee within ±5bps of 0.059%; leverage tier ≥ 3 (our cap); `min_quantity` ≤ our typical size; lot/tick size parse to floats |
| 3 | `instrument_spot` | `get_instrument`/spot metadata for `BTCINR` | spot hedge-leg metadata | `min_quantity` ≤ hedge size; fee known + recorded; lot size parses |
| 4 | `funding_accrual` | `reports/coindcx_venue.csv` (recorder, 60s-polled) | the §20 backtest used Binance funding as a PROXY (~7%/yr); Phase 0 confirms real CoinDCX `fr` is accruing + its magnitude | CSV present, BTC rows span ≥8h (≥ one funding cycle), `fr` non-empty for ≥90% of BTC rows; record mean `abs(fr)` and compare to the Binance proxy (~0.0064%/8h ≈ 7%/yr). The 8h *settlement interval* is a CoinDCX venue fact asserted from docs (the recorder's 60s `fr` is the rate-in-force, not a settlement event). PASS if accruing + fr present + span ≥8h. |
| 5 | `fx_conversion` | `get_conversion_rate()` vs `get_usdt_inr()` | **§29 FX-leg crux** — hedge leak | mean `abs(conversion_price − spot_usdtinr) / spot_usdtinr` over N samples (default N=8, sampled over the probe run) < 10bps |
| 6 | `basis_proxy` | recorder `coindcx_venue.csv` `basis_bps` column (pre-computed) | spot-ticker-as-perp-mark proxy assumption (used for sizing + basis-stop) | median `abs(basis_bps)` over the CSV window < 100bps (the basis_stop threshold). The recorder pre-computes `basis_bps = (mp / (spot_inr/usdtinr) − 1)*1e4` — this IS the venue finding (USDTINR FX risk the Binance proxy did not carry). A leaky proxy >100bps would mis-trigger the basis-stop and mis-size entries → hard FAIL, recorded. |
| 7 | `rate_limit` | REST (light) | documented 16/s, 960/min | 2 rapid successive reads succeed with no 429; limit recorded. No stress test. |

Probes 1, 2, 3, 5, 7 hit REST; probes 4, 6 read the recorder CSV. No write endpoint is touched.

## FX-conversion gate + redesign trigger (the binding decision)

- `fx_conversion` samples `get_conversion_rate()` (the `/api/v1/derivatives/futures/data/conversions` endpoint → `conversion_price`) and `get_usdt_inr()` (spot USDTINR ticker) N times (default 8, spaced ~1s apart within the single probe-run), computes `gap_bps = abs(conv − spot)/spot * 1e4` per sample, takes the mean.
- **PASS:** `mean_gap_bps < 10`. → contributes to `verdict: PASS`.
- **FAIL:** `mean_gap_bps ≥ 10`. → `verdict: FAIL`, `redesign_required: true`, and the JSON `fail_reason` names the FX leg. The §32 appendix records the measured gap. A follow-up **hedge-redesign sub-project** (switch the carry to a USDT-margined perp so the hedge has no platform-conversion-rate leg) is mandated; **no live trade until that sub-project ships its own Phase 0 PASS.**
- Threshold 10bps is conservative (carry edge ~500-600bps/yr; 10bps persistent leak < 2% of edge). Hardcoded default, documented in the spec; not grid-searched (this is a gate, not a strategy).

## Gate freshness

`carry_trader --live` refuses unless `reports/venue_verify.json`:
1. exists,
2. `verdict == "PASS"`,
3. `timestamp` within **24h** of now.

Stale or missing → refuse with a message to re-run `python scripts/venue_verify.py run`. Prevents deploying on a venue state verified days ago. The 24h window is hardcoded; the recorder runs 24/7 so re-verification is cheap.

## Components

1. **`app/exchange/coindcx.py`** — add one method:
   ```python
   async def get_conversion_rate(self) -> float:
       """Current USDT<>INR conversion rate for INR-margined futures (read-only,
       signed). Endpoint /api/v1/derivatives/futures/data/conversions takes a
       SECONDS timestamp (not ms like other endpoints). Returns conversion_price."""
   ```
   Reuses the signing pattern but with a seconds timestamp (explicit, commented gotcha). Adds the endpoint path to `EP` as `"conversions": "/api/v1/derivatives/futures/data/conversions"`.

2. **`scripts/venue_verify.py`** (new) — the harness:
   - `PROBES`: the 7 probes above, each a function `(client) -> ProbeResult` returning `{name, pass: bool, detail: dict, error: str|None}`.
   - `run_probes(client) -> list[ProbeResult]`: runs all 7, catches per-probe exceptions → that probe FAIL with the error string (harness never crashes).
   - `verdict(results) -> dict`: `PASS` iff all probes pass; else `FAIL` + `redesign_required` (true iff `fx_conversion` failed) + `fail_reason`.
   - `main()` (CLI arg `run`): constructs `CoinDCXClient`, runs probes, writes `reports/venue_verify.json` (`{timestamp, verdict, redesign_required, fail_reason, probes: [...], threshold_bps, freshness_h}`) + `reports/venue_verify.log` (human-readable table). No `run` arg → `demo()`.
   - `demo()`: synthetic FakeClient → assert JSON schema; assert PASS on good metadata; assert FAIL on fee mismatch (probe 2); assert fx_conversion gap math (probe 5) correct; assert redesign_required set when fx_conversion fails. No live calls.
   - `FX_THRESHOLD_BPS = 10`, `FRESHNESS_H = 24`, `FX_SAMPLES = 8` constants.

3. **`scripts/carry_trader.py`** — extend the `--live` guard in `main()` (after the `settings.live` check, before constructing the client):
   ```python
   from scripts.venue_verify import load_gate  # or inline
   gate = load_gate()  # reads reports/venue_verify.json
   if gate is None or gate["verdict"] != "PASS" or stale(gate):
       print(f"Refusing --live: venue gate {gate and gate['verdict']}, re-run scripts/venue_verify.py run"); return
   ```
   ~10 lines. The 5 existing demo OK lines (signal/faults/reconcile/sign/tilt) must stay green (regression guard). Add a `_demo_venue_gate()` asserting refuse on missing/stale/FAIL + allow on PASS (uses a tmp gate file). Keep `demo()` printing `carry_trader venue OK` as a 6th OK line.

4. **`tests/test_exchange.py`** — add `test_get_conversion_rate`: mocked httpx response with a seconds-timestamp signed body, assert it parses `conversion_price` and the request body uses seconds. pytest, asyncio_mode=auto. Existing tests stay green.

5. **`docs/strategies_report.md §32`** — Phase 0 venue-verify appendix: probe results table, the measured FX gap, the verdict, and (on FAIL) the redesign-trigger note. Committed regardless of outcome.

**Reused unchanged:** `coindcx.CoinDCXClient` (read methods), `get_instrument`, `get_usdt_inr`, `get_positions`, `get_wallets`; the recorder's `reports/coindcx_venue.csv`; sub-project 1's fault-handling + reconcile logic (untouched).

## Data flow

```
.env (api keys) → CoinDCXClient
   ↓
venue_verify.run_probes:
   auth_liveness  → get_wallets / get_positions
   instrument_*   → get_instrument (perp + spot)
   fx_conversion  → get_conversion_rate (N samples) vs get_usdt_inr
   rate_limit     → 2 rapid reads
   funding_accrual → reports/coindcx_venue.csv (recorder, 60s-polled)
   basis_proxy    → reports/coindcx_venue.csv (basis_bps column)
   ↓
reports/venue_verify.json  ({timestamp, verdict, redesign_required, fail_reason, probes[]})
reports/venue_verify.log   (human table)
   ↓
carry_trader --live guard: load_gate() → refuse unless PASS + fresh
   ↓
PASS → --live proceeds (Phase 1 paper / Phase 2 small-real)
FAIL → --live locked; fx fail → hedge-redesign sub-project mandated
```

## Error handling

1. **Probe throws** (endpoint down, auth fail, non-JSON) → that probe `pass: false`, `error: str(e)`; harness continues other probes; never crashes.
2. **Missing `coindcx_venue.csv`** → `funding_accrual` + `basis_proxy` FAIL (recorder not running); `verdict: FAIL`. Honest — can't verify the carry edge's load-bearing funding/basis assumptions without the recorder.
3. **`conversions` endpoint 4xx/5xx** → `fx_conversion` FAIL, `error` set, `redesign_required: false` (can't measure ≠ measured-bad), `verdict: FAIL` (can't verify = can't deploy). Logged.
4. **Auth fails** (`auth_liveness` FAIL) → all REST probes that depend on auth also FAIL; `verdict: FAIL`. The log names auth as the root cause.
5. **Instrument fee mismatch** (probe 2) → FAIL; `fail_reason` names the fee delta vs §29. May indicate the cost model needs update, not that the venue is broken — recorded either way.
6. **Stale gate at --live** → `carry_trader` refuses with re-run instruction; no crash, no order.

## Testing (scripts/ `__main__` + app/ pytest)

- `venue_verify.py` `__main__`/`demo()`: synthetic FakeClient → JSON schema assert; PASS on good metadata; FAIL on fee mismatch; fx gap math correct; redesign_required set on fx FAIL. No live calls in self-check.
- `coindcx.py` `get_conversion_rate`: `tests/test_exchange.py` mocked-httpx unit test (seconds-ts signing + `conversion_price` parse). pytest.
- `carry_trader.py` `demo()`: add `_demo_venue_gate()` (6th OK line: `carry_trader venue OK`); 5 existing OK lines unchanged (regression guard).
- No live calls in any self-check / unit test. `venue_verify.py run` is the only live invocation.

## Interface to carry_trader (the gate)

- `scripts/venue_verify.py` exposes `load_gate(path="reports/venue_verify.json") -> dict | None` (returns parsed JSON or None if missing/corrupt) and `gate_is_fresh(gate, freshness_h=24) -> bool`.
- `carry_trader.main()` `--live` branch calls these before constructing the client; refusal prints the verdict + re-run instruction + returns (no order, no crash).
- `load_gate` is robust: corrupt/missing JSON → None (treated as refuse). Never raises into the live path.

## Out of scope

- Order write-path verification (create_order / exit_position / create_spot_order) — no testnet, deferred to Phase 2 small-real.
- Continuous venue monitoring — Phase 0 is a one-shot pre-deploy gate (the recorder already runs continuously for market data).
- The hedge-redesign sub-project (USDT-margined perp) — triggered by `fx_conversion` FAIL, separate spec/plan cycle. Not built here.
- Live deployment, Phase 1 paper run, Phase 2 small-real — separate cycles after Phase 0 PASS.
- Re-deriving the carry signal, tilt slot, or risk overlay — sealed (sub-project 1/2/3).
- Paid data, colocation, cross-venue arbitrage.

## Open questions for implementation plan

- `get_instrument` for the spot leg `BTCINR`: the current `get_instrument` targets the derivatives instrument endpoint. Spot metadata may need the spot instruments endpoint (`/exchange/v1/instruments`) or a ticker-derived min-qty. Resolve in plan: check which endpoint exposes BTCINR lot/min-qty + fee; if none clean, probe 3 falls back to ticker + a documented min-qty from CoinDCX support docs.
- N samples for `fx_conversion` (default 8) and inter-sample spacing (default ~1s) — pick in plan; default kept unless plan finds a reason.
- Whether to also hit a CoinDCX funding REST endpoint (if one exists) to cross-check probe 4's recorder-based `fr` magnitude, or rely on the recorder CSV alone — resolve in plan (recorder CSV is the live data source either way; CoinDCX exposes no public funding *history* per the recorder's own §20 note).