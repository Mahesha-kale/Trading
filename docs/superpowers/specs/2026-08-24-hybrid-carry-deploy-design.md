# Hybrid Carry Deploy — Design Spec (sub-project 1)

Date: 2026-08-24
Status: design, pending implementation plan
Goal: deploy the one net-positive research result (band-gated funding carry, §20/§27) as a live CoinDCX hybrid — delta-neutral carry core (proven ~5-6%/yr on capital) plus a small directional tilt slot (shot at more, sourced from sub-project 2's regime-gate research).

## Background

The research (`docs/strategies_report.md` §1-§29) concluded no **robust across-both-regimes** edge at free-data retail resolution. Under the relaxed goalpost the user accepted — profit in one regime + survive the other — the funding carry is the one result that is net-positive after all real costs (~7%/yr BTC/ETH on perp notional at lev 1; ~4.6%/yr SOL). §27 showed it is positive-funding-regime income with a small negative-regime bleed (BTC -0.47%, ETH -1.17%, SOL -2.55%), not a robust regime-agnostic edge, but under the one-regime rule it qualifies. §24 bounds the squeeze/basis tail at ~1-2% via a 100bps basis-stop. §29 #1 venue-verify found CoinDCX fees (maker 0.0236% / taker 0.059%) and that funding/basis are forward-only on CoinDCX (no public history), with an extra USDTINR FX leg in the hedge; a recorder is accruing to close those caveats.

This spec covers the deploy engineering only. It does not reopen the signal question — the carry signal (`funding_carry_band.dn_band`) and the basis-stop (`carry_stop`) are taken as proven from §20/§24. The tilt-signal source is sub-project 2 (separate spec).

## Constraints (from user decisions)

- Live CoinDCX account + API key/secret + capital ready.
- Aggressive risk policy: max ~25% portfolio drawdown → stop.
- Free public data only; retail execution; CoinDCX perp (linear) + CoinDCX spot (BTCINR).
- Hybrid shape: delta-neutral carry core + small directional tilt (≤20% of perp notional naked), sized within the 25% risk budget.
- Carry caps at ~5-6%/yr on total capital delta-neutral (the spot leg is unleveraged; leverage only shrinks perp margin, not spot). Leverage is not the income multiplier here — it mainly frees capital and scales the tail.

## Architecture: four gated phases

### Phase 0 — venue-verify gate (accruing now, no deploy)

`coindcx-venue.service` (already deployed on the Oracle Cloud box) polls the real-time endpoint every 60s → `reports/coindcx_venue.csv` (ts, sym, fr, efr, mp, ls, spot_inr, usdtinr, basis_bps). Wait until enough data confirms:

- (a) CoinDCX `fr`/`efr` tracks Binance funding level over time (validates the §20 ~7%/yr proxy on the actual venue).
- (b) Basis stays <100bps so the §24 basis-stop is cheap to run on CoinDCX.
- (c) Quantify the USDTINR FX-leg residual variance (the risk the Binance perp+USDT-spot proxy did not have).

**Gate to Phase 1:** weeks of accrual show (a) tracks within tolerance and (b) holds. No deploy until this passes — else the §20/§23 venue caveats are unverified. Sub-project 2 (regime-gate research) runs in parallel during the wait; it does not need the venue data.

### Phase 1 — paper-trader (no real orders)

New `scripts/carry_trader.py` runs the live loop on the venue feed but places no orders — logs every decision it WOULD take. Reuses the full stack (see Components). Confirms signal→order plumbing, basis-stop behavior on live data, and that paper marks match `coindcx_venue.csv`.

**Gate to Phase 2:** runs clean ≥1 week; synthetic chaos checks pass (feed outage, basis spike, restart mid-position, orphan-leg handling); paper marks reconcile with the venue recorder.

### Phase 2 — small-size real, delta-neutral core, tilt OFF

Lev ~3, isolated margin, basis-stop on, 25% portfolio DD hard stop. Short BTC perp + long BTCINR spot, band-selected (band trained on first 70% by time per §20, no OOS peeking). Start at ~10% of deploy capital; scale if it behaves over 2-4 weeks.

**Gate to Phase 3:** 2-4 weeks live, funding income tracks the §20 model within tolerance, no stop events beyond the basis-stop, FX residual within the Phase-0 measured band.

### Phase 3 — tilt slot ON

Enabled only when sub-project 2 delivers a regime gate with positive capture/bleed in walk-forward. Tilt = small directional perp exposure (≤20% of perp notional naked, no spot hedge), sign from the gate, sized within the remaining 25% risk budget. Sub-project 3 (asymmetric risk overlay) sizes and stops the tilt.

## Components

New (minimal):

1. **`scripts/carry_trader.py`** — the live loop. Async, one process, acts on funding marks (8h cycle). Reads venue feed → signal → orders → monitors basis-stop + DD stop. State persisted to `reports/carry_trader_state.json` for restart recovery. HALT file kill-switch.
2. **`app/exchange/coindcx.py` +1 method** — `create_spot_order()` for the BTCINR spot hedge leg. Reuses `_sign`/`_signed_post`, new endpoint `/exchange/v1/orders/create`. ~15 lines. The only new exchange code (futures order/position/leverage/instrument methods already exist).
3. **`scripts/risk_budget.py`** — sizing math: given the 25% DD cap, the §24 basis-stop loss estimate, and the funding income rate → per-position size, leverage, and tilt-slot size. Pure function, unit-tested.

Reused unchanged:

- `funding_carry_band.dn_band(rate, band, fee)` — entry/flatten signal (rate > +band → short perp + long spot; rate < −band → flatten; deadband → hold).
- `carry_stop` — basis-stop logic (flatten on basis >100bps spike).
- `coindcx_venue_recorder.sample()` — live fr/efr/basis/spot/USDTINR feed.
- `CoinDCXClient`: `create_order`, `positions`, `exit_position`, `update_leverage`, `get_instrument`, `spot_usdt_inr`.
- `CoinDCXWS` — optional tighter price feed for the basis-stop (Phase 2+).

## Data flow (one 8h funding cycle)

```
coindcx-venue recorder (fr/efr/basis every 60s)
  ↓
carry_trader reads latest sample
  ↓
dn_band(signal) on fr history → action: ENTER_SHORT / FLATTEN / HOLD
  ↓
ENTER_SHORT (rate > +band, no position):
  risk_budget.size() → qty
  [Phase 2+] create_order(short perp, lev 3) then create_spot_order(long BTCINR, qty)
  [Phase 1] log only
FLATTEN (rate < −band):
  [Phase 2+] exit_position(perp) then create_spot_order(sell BTCINR)  [spot sell = 1% TDS, spot-only]
  [Phase 1] log only
HOLD: do nothing (deadband)
  ↓
basis-stop monitor (every 60s): basis >100bps → force FLATTEN
  ↓
DD-stop (every cycle): portfolio DD >25% → flatten all, halt
  ↓
log decision + mark-to-market PnL (TDS-modeled) to reports/carry_trader.log
```

Tilt slot (Phase 3): same loop, extra branch — when the sub-project 2 gate fires, `risk_budget.tilt_size()` → naked perp order (no spot hedge), sign from the gate, stopped by the sub-project 3 overlay.

## Key design choices

- **Spot leg pays 1% TDS on sell** (spot-only, confirmed) — already baked into the §20 band selection; carry survives it (§20 net-positive).
- **Delta-neutral** — perp delta ≈ spot delta, so price moves cancel; net income = funding − fees − TDS-on-spot-sell − adverse-funding-bleed. The USDTINR FX residual (perp USDT-notional vs spot INR) is a small extra risk measured in Phase 0/1.
- **Isolated margin** per position — loss capped to position margin, not the whole account. Bounds blow-up.
- **8h cycle** matches funding frequency — no sub-second latency needed (retail-friendly, consistent with the §29 OBI latency read).
- **Orphan-leg safety** — perp entered first, confirmed filled, then spot hedge; spot reject within N seconds → exit perp, halt. Never hold one leg naked unintentionally.
- **Fail-safe = flatten + halt** — every fault path (feed outage, restart, unknown state) resolves to "flatten what's open, halt, await human," not "keep trading."

## Error handling

1. **Order reject / partial fill / timeout** — two-leg entry risks an orphan leg. Perp first, confirm fill, then spot; if spot rejects within N seconds → exit perp, log, halt. Never hold one leg orphaned.
2. **Position drift** — every cycle reconcile `positions()` against `state.json`; mismatch → trust exchange truth, log, re-sync. Never act on stale local state.
3. **Feed outage** — no fresh venue sample within 2 cycles (16min) → flatten + halt (cannot monitor basis-stop blind).
4. **Basis-stop execution gap** — squeeze gaps <100→500-2000bps in one print; stop fills at 2-5% not 1%. Mitigation: isolated margin (loss capped) + 25% portfolio DD stop as backstop. The basis-stop is a circuit breaker, not a guaranteed fill price.
5. **Restart mid-position** — `state.json` holds open positions + band + entry prices. On restart: reconcile with exchange truth, resume. If `state.json` missing/corrupt → flatten whatever exchange shows, halt (do not guess).
6. **Kill switch** — `reports/carry_trader.HALT` file checked each cycle; present → flatten all, halt. Manual override.
7. **API key safety** — keys in `.env` via Settings, never logged; `_sign` redacts. No keys in state.json or logs.
8. **TDS in mark-to-market** — 1% spot-sell TDS modeled in the PnL/DD number so the 25% stop reflects realized equity, not gross.

## Testing

- **`risk_budget.py` unit tests** — pure function; assert sizing for edge cases (zero funding, max DD, tilt within budget). One `test_risk_budget.py`, stdlib `assert`.
- **Signing dry-run** — `build_order` + `_sign` against a known vector without sending; verify signature matches CoinDCX docs. Catch auth bugs before any real order.
- **Phase 1 paper-trader = the integration test** — live venue feed, logs every decision, no orders. Gate: ≥1 week clean; paper marks reconcile with `coindcx_venue.csv`; basis-stop fires on synthetic spike injection. This is the pre-deploy test; no separate mock framework.
- **Chaos checks (paper):** kill feed mid-cycle (rule 3), inject synthetic basis spike (basis-stop), restart mid-position (state recovery), inject order-reject (orphan-leg). Manual, scripted in paper mode.
- **Self-checks reused:** `funding_carry_band`, `carry_stop` keep their `__main__` checks passing.

No new test framework — stdlib `assert` + the paper-trader, per the project's lazy-code convention.

## Out of scope

- The tilt-signal design (sub-project 2 spec).
- The asymmetric risk-overlay design (sub-project 3 spec).
- Re-deriving the carry signal or basis-stop (proven §20/§24).
- Options, cross-venue arbitrage, paid data, colocation (user kept free-data + retail + CoinDCX-perp-linear constraints).
- Parameter re-tuning the 23 price strategies (closed, §7/§11).

## Open questions for implementation plan

- Spot order endpoint exact path + body schema (CoinDCX spot vs futures create_order differ) — resolve at Phase 1 build via a signed dry-run against the instrument/ticker, not a live order.
- N-second orphan-leg timeout value — pick a conservative default (e.g. 30s) and tune in paper.
- Band retrain cadence live (§20 trained on first 70% by time) — fixed at deploy, or periodic retrain? Decide in plan; default fixed to avoid look-ahead.