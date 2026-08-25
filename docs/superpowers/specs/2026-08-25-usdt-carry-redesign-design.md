# USDT-margined carry redesign — design spec

**Goal:** Redesign the delta-neutral funding carry to dodge the 250 bps INR-conversion leak that refuted the INR-margined version (definitive Phase 0 FAIL, 2026-08-25), by margining the same `B-BTC_USDT` perp in USDT + hedging with `BTCUSDT` spot. Re-backtest under real CoinDCX USDT costs (incl. 2% spot TDS round-trip) is the gate; only if the edge survives do we re-point the paper-trader + pursue Phase 2.

**Architecture:** SHORT USDT-margined `B-BTC_USDT` perp (settles USDT, no INR conversion) + LONG `BTCUSDT` spot. Pure-USDT structure — the same shape the §27/§28 Binance-proxy backtest tested (~7%/yr gross), now on CoinDCX with real Indian costs. Funding `fr` is per-contract (margin-currency-independent); the edge is unchanged, only the cost model differs.

**Tech stack:** Python 3.12, scripts/ (`__main__` assert demo, no pytest), app/+tests/ (pytest asyncio_mode=auto), ruff line-length 100. Reuses `scripts/carry_funding_regime.py` + `funding_carry_band` + `funding_carry` (§27 harness), `scripts/carry_trader.py` (paper-trader), `scripts/venue_verify.py` (Phase 0 gate), `scripts/coindcx_venue_recorder.py` (feed).

**Context / authority:**
- Definitive Phase 0 verdict (2026-08-25, `reports/venue_verify.json` on Oracle box): FAIL, `redesign_required=True` — fx_conversion mean gap **250.49 bps** (INR-margin USDT<>INR conversion 102.0 vs spot USDTINR ~99.5). 6/7 probes PASS. INR-margined perp carry REFUTED. See [[post-conclusion-followups]] §29, commit `b993cf7` (PR #20).
- §27/§28 carry funding-regime walk-forward (`scripts/carry_funding_regime.py`): the one edge that survived rigor — but backtest modeled 1% sell-only TDS + NO FX-conversion leak (the leak was unmeasured until today). [[carry-funding-regime-walkforward]]
- Venue probe (2026-08-25): `B-BTC_USDT` is USDT-settled (`settle_currency=USDT`, `max_leverage_short=20`, active); `BTCUSDT` spot live (78349 USDT); account has only an INR futures wallet (USDT wallet must be funded by the user before Phase 2).
- TDS (CoinDCX support + Section 194S): INR pairs = 1% sell-side only; **USDT (C2C) pairs = 1% on BOTH buy + sell = 2% round-trip on the spot leg**; futures = no TDS.

## The crux: cost model comparison

| leg / version | INR-margin (refuted) | USDT-margin (this redesign) |
|---|---|---|
| perp fee | 5.9 bps taker ×2, no TDS | 5.9 bps taker ×2, no TDS |
| spot TDS | 1% sell-only = 100 bps | **1% buy + 1% sell = 200 bps round-trip** |
| FX conversion | **250 bps leak** (measured) | none |
| spot fee | ~0.169%+GST ×2 (BTCINR) | ~0.169%+GST ×2 (BTCUSDT, verify) |
| funding | fr 8h (per-contract, same) | fr 8h (same) |
| basis | perp vs BTCINR (~19.9 bps median) | perp vs BTCUSDT (~19.9 bps, same) |

USDT removes the 250 bps FX leak but adds 100 bps extra TDS (buy-side) vs the §27 backtest's sell-only model. **Net round-trip spot cost ≈ 200 bps TDS + spot fees.** The §27 ~7%/yr was scored with 100 bps sell-TDS + zero FX. The USDT re-backtest adds 100 bps entry-TDS; whether ~7%/yr survives depends on the strategy's flip frequency (low-flip = amortizes; high-flip = killed). **The re-backtest decides.**

## Components

### 1. Re-backtest (THE GATE) — `scripts/carry_funding_regime.py` + cost model

Modify `carry_oneside` to charge TDS on the **entry spot BUY** as well as the exit sell (USDT C2C = both sides), then re-run the §27 funding-regime walk-forward. Keep everything else identical (Binance-proxy funding history — fr is per-contract; same train-select band on first 70%; lev 1; maker fee where applicable).

- **Cost change:** `TDS = 0.01` currently applied at flatten (sell). Add `TDS_BUY = 0.01` at entry (buy spot). Round-trip spot TDS = 2%. Document that this reflects USDT C2C pairs (Section 194S; INR pairs are sell-only — keep a flag/variant so both cost models are auditable).
- **Verdict:** re-score pos-regime profit + neg-regime bleed (the §27 gate: profit in pos, ≥0 in neg). Compare net_eq / annualized to the §27 sell-only-TDS baseline.
- **PASS:** edge survives the 2% spot TDS at the strategy's actual flip frequency (net positive annualized, neg-regime flat). → proceed to components 2-4.
- **FAIL:** edge killed by the entry TDS. → redesign ends here (option C, abandon). No paper-trader re-point, no Phase 2. Report + update §29/§33.
- **Output:** a `__main__` demo asserting the re-scored result + a printed comparison to the §27 baseline. Commit the cost-model variant (do not overwrite §27's sell-only result — add a USDT-cost path).

### 2. Paper-trader re-point — `scripts/carry_trader.py` (+ feed)

Re-point the deployed paper-trader from INR-margin/BTCINR to USDT-margin/BTCUSDT. Conditional on component 1 PASS.

- **Accounting INR→USDT:** `peak_equity` + `capital` in USDT (not INR). Funding accrual `qty * fr * entry_spot_usdt` (USDT). `_basis_mtm` = perp − BTCUSDT spot (USDT), no FX residual. Remove the §29 FX-leg residual from `_mark_equity` (the USDT structure has no FX leg).
- **Feed:** BTCUSDT spot price. Two options (pick the simpler in the plan): (a) derive `BTCUSDT = spot_inr / usdtinr` from the existing venue recorder fields (no recorder change — arbitrage keeps BTCINR/USDTINR ≈ BTCUSDT), or (b) extend `coindcx_venue_recorder.py` to sample BTCUSDT spot directly. Prefer (a) unless the synthetic drifts > a few bps vs live BTCUSDT (verify in the plan).
- **Spot pair:** `--spot-pair BTCUSDT` (was BTCINR). `--pair B-BTC_USDT` unchanged (same contract, USDT margin chosen at the exchange level, not the pair).
- **Capital unit:** USDT. argparse `--capital` default changes to a USDT amount (e.g., 1000 USDT) — document the unit change.
- **No-orders invariant unchanged:** paper places no orders (`live and client is not None` guard). Notional qty for PnL as before.

### 3. Phase 0 re-frame — `scripts/venue_verify.py`

The fx_conversion probe measured the INR-margin leak; for the USDT path there is no INR conversion. Re-frame the gate for USDT margin:

- `fx_conversion` probe: N/A for USDT margin (no conversion endpoint used). Replace/adapt: verify the **USDT futures wallet is live + funded** (wallets probe shows a USDT wallet, non-zero balance) — this is the USDT-path equivalent of "no FX leak." Keep the fx_conversion probe available as an INR-path diagnostic but not gating for USDT.
- Keep the 6 passing probes (auth, perp fee 5.9 bps, spot, funding-accrual, basis-proxy, rate-limit) as the USDT gate. Add a spot-fee verification for BTCUSDT (verify the ~0.169%+GST assumption for the USDT pair).
- `instrument_perp` leverage: read `max_leverage_short` (the instrument exposes it as 20, not under `leverage`) — minor improvement to the probe (currently treats null as not-exposed; can now verify ≥ cap informatively).
- Verdict logic: USDT path PASS = 6 probes + USDT-wallet-live. `redesign_required` stays False for USDT path (no FX leg).

### 4. Phase 2 small-real — gated

Conditional on components 1-3 + the user funding a USDT futures margin wallet (account action, UI — cannot be done via API).

- SMALL size: SHORT USDT-margined `B-BTC_USDT` perp + LONG `BTCUSDT` spot, minimal notional, isolated margin, lev 1-3.
- Gate: component 1 backtest PASS + component 3 USDT Phase 0 PASS + paper-trader (component 2) clean ≥7d on the 5 `paper_check` criteria + USDT wallet funded + §27 edge verdict standing.
- Fail-safe unchanged: 25% portfolio DD → flatten + halt; flatten + halt on every fault; `--live` guarded by `trading_mode=="live"` AND USDT Phase 0 gate (PASS + fresh <24h).

## Success criteria

1. **Backtest gate (component 1):** USDT-cost walk-forward net positive annualized + neg-regime flat. If FAIL, stop here.
2. **Paper-trader (component 2):** deployed on Oracle box, USDT accounting, no orders, clean ≥7d on `paper_check` 5 criteria.
3. **Phase 0 USDT (component 3):** `venue_verify.py run` → USDT-path PASS (6 probes + USDT wallet live, no FX leg).
4. **Phase 2 (component 4):** small-real fills reconcile, no faults, funding accrues as paper-predicted.

## Risks

- **2% spot TDS kills the edge** (component 1 FAIL) — the most likely failure mode; the backtest is first precisely to catch this cheaply. If it fails, abandon (option C).
- **BTCUSDT spot fee ≠ BTCINR fee** — verify in component 3; if higher, compounds the TDS cost.
- **Synthetic BTCUSDT drift** (feed option a) — if BTCINR/USDTINR diverges from live BTCUSDT by > a few bps, switch to recorder option (b).
- **USDT wallet funding delay** (user action) — blocks Phase 2 only; components 1-3 proceed without it.
- **BTCUSDT spot liquidity / slippage** — small-real size mitigates; verify in Phase 2.
- **Funding history is Binance-proxy** (CoinDCX has no public funding history, §29) — the recorder accrues real CoinDCX fr forward; the backtest uses proxy history (fr is per-contract, regime structure transferable). This caveat is unchanged from §27.

## Out of scope

- Two-sided negative-funding harvest (not executable on CoinDCX — no spot short; §27 by-design).
- Tilt overlay (slot stays NoTilt per [[regime-gate-tilt-sweep]] §31; the user's binding sequence item #3 — new tilt research — is separate from this redesign).
- Any change to the running coindcx-venue.service recorder (proven uptime; do not disturb).

## References

- [[post-conclusion-followups]] §29 (FX leg, now measured 250 bps), [[carry-funding-regime-walkforward]] §27/§28, [[phase1-paper-trader]] (deployed paper-trader to re-point), [[regime-gate-tilt-sweep]] §31, [[funding-carry-band]] §20.
- `docs/strategies_report.md` §20/§23/§27/§28/§29/§33.
- Definitive venue verdict: `reports/venue_verify.json` (Oracle box), commit `b993cf7`, PR #20.