# Phase 1 Paper-Trader Run — Design Spec (sub-project 5)

Date: 2026-08-25
Status: design, pending implementation plan
Goal: wire the carry trader's stub paper feed + add real paper-PnL accounting, run it 7-14 days on live CoinDCX data (paper, no orders) to validate the **operational loop** end-to-end, and produce the definitive Phase 0 venue verdict by running `venue_verify.py run` on the Oracle recorder host (where `coindcx_venue.csv` lives). A valid outcome is: zero faults over the window, the signal fires on funding-band crossings, paper funding accrual is non-negative and comparable to the §20 ~7%/yr proxy, state survives restarts → **Phase 2 small-real unlocked**. Operational validation, NOT edge re-confirmation (§20 backtest already proved the edge).

## Background

Sub-project 1 (PR #16) built the hybrid carry trader (`scripts/carry_trader.py`): delta-neutral funding harvest (SHORT `B-BTC_USDT` perp + LONG `BTCINR` spot), 8h cycle, 25% DD halt, fail-safe flatten+halt, pluggable tilt slot. Sub-project 2 (PR #17) sealed the tilt slot `NoTilt` (0/18 gates pass). Sub-project 4 (PR #18) built the Phase 0 venue-verify harness (`scripts/venue_verify.py` + `get_conversion_rate`) and gated `carry_trader --live` on a PASS+24h-fresh `venue_verify.json`. The carry trader is built but **not deployed**: paper feed is a stub, paper PnL is a placeholder, and no live `venue_verify.py run` has been executed (§32: "awaiting first live run on the recorder host").

Phase 1 closes those gaps without risking capital:
1. Wire `_paper_feed()` (currently `await asyncio.sleep(0)` — a stub) to real live data.
2. Replace the `_mark_equity` placeholder (`ponytail: placeholder equity; real MTM deferred to Phase 2 live`) with real paper-PnL accounting (funding accrued at 8h marks + basis MTM).
3. Run paper on Oracle (CSV feed, alongside the recorder) 7-14d via systemd.
4. Run `venue_verify.py run` on Oracle → definitive Phase 0 verdict (probes 4+6 have the CSV there; locally they FAIL on the missing CSV).

Paper mode places **no orders** (`live=False`, `client=None` → `_enter_short` sets `qty=0.0`, logs only). The venue gate is `--live`-only and does not block paper. Phase 2 small-real remains gated behind Phase 0 PASS + Phase 1 operational-validation success.

## Constraints (from user decisions)

- Free public data + retail execution; CoinDCX perp (linear, INR-margined) + BTCINR spot. **No real orders in Phase 1** — paper mode only (`--live` untouched, still gated by Phase 0 venue gate + `trading_mode=="live"`).
- **Both venues** (user decision): develop + iterate the REST paper feed on this Windows box; run the 7-14d paper validation on the Oracle Cloud host (CSV feed, alongside the recorder, 24/7 systemd). Two feed implementations, one shared `FeedSample` contract.
- **Operational validation scope** (user decision): 7-14 days. Success = zero faults, feed never starves, signal fires on band crossings, paper PnL tracked. NOT a multi-month edge re-confirmation. Then Phase 2 small-real.
- Perp carries **no 1% TDS** (TDS is spot-sell only; the perp is naked). The spot leg TDS on sell is a known cost in the §29 cost model — not simulated in paper PnL (paper never sells; it accrues funding). Recorded as a caveat.
- API keys in `.env` via `app.config.settings`, never logged. The REST paper feed uses **public endpoints, no auth** (mirrors the recorder). `venue_verify.py run` on Oracle uses the Oracle host's `.env`.
- Fail-safe = flatten+halt on every fault (unchanged from sub-project 1). 25% portfolio DD hard stop (unchanged). In paper mode "flatten" is a state transition (side→0, log), not an order.
- `ruff` line-length 100, Python 3.12. `scripts/` → `__main__` assert `demo()` (NO pytest). `app/` + `tests/` → pytest (`asyncio_mode=auto`). gh at `C:\Program Files\GitHub CLI\gh.exe`.

## The feed (two implementations, one contract)

`FeedSample(ts, fr, efr, basis_bps, spot_price, usdtinr)` — unchanged from sub-project 1. `run_loop` consumes `s.ts`, `s.fr` (signal `decide`), `s.basis_bps` (basis-stop), `s.spot_price` (entry/exit/equity).

**REST feed (dev, this Windows box) — `--feed rest` (default):**
- Reuses `scripts/coindcx_venue_recorder.py::sample()` (public REST, no auth, stdlib `urllib`). That function already fetches `futures_rt()` (`PUB /market_data/v3/current_prices/futures/rt` → `{fr, efr, mp, ls}` per pair) + `spot_prices()` (`API /exchange/ticker` → `{market: last_price}`, incl. BTCINR + USDTINR) and computes `basis_bps = (mp/(spot_inr/usdtinr) - 1)*1e4`.
- `_paper_feed()` calls `sample()`, takes the BTC row (`sym == "BTC"`), returns `FeedSample(ts=row["ts"], fr=row["fr"], efr=row["efr"], basis_bps=row["basis_bps"], spot_price=row["spot_inr"], usdtinr=row["usdtinr"])`. On `sample()` failure or missing BTC row → return `None` (feed-outage path, already handled by `run_loop`).
- No new fetch code. No auth. No orders. No venue gate.

**CSV feed (Oracle) — `--feed csv`:**
- Extract `csv_feed()` from the existing `_live_feed()` body (lines 387-399: reads the last row of `reports/coindcx_venue.csv` → `FeedSample`). Same contract. The recorder writes this CSV 60s-polled on Oracle.
- `--live` forces `--feed csv` (live runs on Oracle where the CSV exists) and keeps the Phase 0 venue gate. Paper-on-Oracle uses `--feed csv` without `--live` (no gate, no orders).

**Selection:** `main()` adds `--feed {rest,csv}`, default `rest`. `--live` overrides to `csv`. Paper mode (`--live` absent) uses the selected feed with `client=None`, `live=False`.

## Paper-PnL accounting (replaces the `_mark_equity` placeholder)

The current `_mark_equity` is `ponytail: placeholder equity (peak + funding proxy); real MTM deferred to Phase 2 live`. Phase 1 replaces it with real accrual-based paper equity so the 7-14d run produces a meaningful carry-income number on the live venue.

**Funding accrual at 8h marks:**
- CoinDCX settles funding every 8h (venue fact asserted from docs; standard 00:00/08:00/16:00 UTC schedule — confirm on first live run from the recorder's `efr` transitions; the accrual logic keys on crossing these mark timestamps).
- When the feed's `ts` crosses an 8h mark while `state.side == -1` (short perp, harvesting positive funding), accrue `accrued_funding += qty * fr_at_mark * entry_spot` to equity. `fr_at_mark` = the `fr` of the feed sample at the mark crossing (the rate-in-force that settles).
- This is the real CoinDCX carry income (vs the §20 Binance proxy). The 7-14d accrual rate is compared to the §20 ~7%/yr proxy as a sanity check, NOT a re-proof.

**Basis MTM:**
- Delta-neutral: perp PnL + spot PnL cancel on BTC price movement. The residual is the FX/basis leg (`basis_bps` = perp mark vs synthetic USDT spot = BTCINR/USDTINR). Track the cumulative basis drift as a paper-equity component so the equity curve reflects the §29 FX-leg leak honestly.
- `basis_bps > basis_stop_bps (100)` → basis-stop fires (unchanged). The paper equity records the basis-stop exit.

**Equity + DD:**
- `equity = peak_equity + accrued_funding + basis_mtm`. DD halt (25%) + basis-stop (100bps) + flatten now drive off this real paper equity. `state.peak_equity` updated on each poll.
- Paper "flatten" = `state.side = 0`, log the exit + realized paper PnL. No order.

**Paper ledger:** append-only `reports/carry_paper.csv`, one row per poll that changes state or accrues funding: `ts, event, side, fr, efr, basis_bps, accrued_funding, equity`. Events: `ENTER_SHORT`, `FUNDING_ACCRUE`, `BASIS_STOP`, `FLATTEN`, `DD_HALT`, `FEED_OUTAGE`. This is the success-criteria evidence.

## Oracle deploy + definitive Phase 0

**Paper-trader systemd unit (Oracle):**
- Runs `python scripts/carry_trader.py --feed csv` (paper mode, no `--live`). `Restart=always`, `WorkingDirectory` the repo, state file `reports/carry_trader_state.json` persists across restarts. Matches the recorder's systemd pattern (memory: recorder deployed Oracle cloud systemd, recording 24/7 since 2026-08-07).
- The recorder must already be running on the same host (writes `coindcx_venue.csv`). The paper-trader reads it.
- Deploy artifacts committed: the systemd unit file + a short deploy README. User deploys (no manual work = I prepare artifacts; deployment to Oracle is the one step the user runs, consistent with the recorder deploy).

**Definitive Phase 0 venue verdict:**
- On Oracle (CSV present), run `python scripts/venue_verify.py run` → writes `reports/venue_verify.json` with all 7 probes real (incl. probes 4+6 reading the CSV). This is the definitive Phase 0 verdict §32 was "awaiting."
- If `verdict == PASS` → Phase 0 complete; `--live` unlocked for Phase 2.
- If `fx_conversion` FAIL → `redesign_required: true` → hedge-redesign sub-project mandated (per Phase 0 spec). Phase 1 paper continues for operational validation only; the paper PnL notes the measured FX leak so the damage is visible.

## Success criteria (7-14d) + gate to Phase 2

The run passes (Phase 2 unlocked) iff ALL hold over a contiguous 7-14d window:
1. **Zero faults:** no `halted_orphan`, no reconcile halt, no corrupt-state halt, no unplanned DD halt. (A DD halt from a real 25% paper drawdown would itself be a finding — the carry edge should not draw down 25% in 14d.)
2. **Feed never starves:** `feed()` returns non-None ≥ 95% of polls; `FEED_OUTAGE` events < 5% of polls.
3. **Signal fires:** ≥ 1 `ENTER_SHORT` and ≥ 1 `FLATTEN` on funding-band crossings (`band=0.0002`) over the window — confirms `decide` reacts to live CoinDCX funding, not just the backtest series.
4. **Paper funding accrual ≥ 0** over the window; accrual annualized within an order of magnitude of the §20 ~7%/yr proxy (sanity, not proof — 7-14d is too short to nail the rate).
5. **State survives restart:** restart the systemd unit mid-run; state reloads non-corrupt, side/qty/accrued_funding preserved.

A `scripts/paper_check.py` (or a section of the §33 appendix) reads `reports/carry_paper.csv` + `carry_trader_state.json` and emits the verdict against these criteria. `docs/strategies_report.md §33` records the run + verdict.

## Components

1. **`scripts/carry_trader.py`** (modify):
   - Wire `_paper_feed()` → REST feed (reuse `coindcx_venue_recorder.sample()`).
   - Extract `csv_feed()` from `_live_feed()`; keep `_live_feed()` as a thin wrapper or replace both with `--feed` selection.
   - `main()`: add `--feed {rest,csv}` (default `rest`); `--live` forces `csv`. Paper path uses selected feed, `client=None`, `live=False`.
   - Replace `_mark_equity` with real paper equity: funding accrual at 8h marks + basis MTM. Add `accrued_funding` + `basis_mtm` to `TraderState` (persisted).
   - Paper ledger: append `reports/carry_paper.csv` on state changes / accruals.
   - `demo()` / `__main__`: extend the self-check to cover the REST feed (mocked `sample()`), paper-PnL accrual at a simulated 8h mark, `--feed` selection, and the paper ledger. Keep the 6 existing OK lines green (regression guard) — add a 7th `carry_trader paper-feed OK` (or fold into existing lines; the demo must exercise the new paths offline).

2. **`scripts/paper_check.py`** (new, `__main__` demo): reads `reports/carry_paper.csv` + state, emits the 5-criteria verdict. Offline demo on a synthetic ledger.

3. **Oracle deploy artifacts** (new, committed):
   - `deploy/carry-paper.service` (systemd unit) — `python scripts/carry_trader.py --feed csv`, `Restart=always`, `WorkingDirectory`, state path.
   - `deploy/README.md` — deploy steps (scp, systemctl enable/start, confirm recorder running first, run `venue_verify.py run`).

4. **`docs/strategies_report.md §33`** — Phase 1 paper-trader run appendix: the two-feed design, paper-PnL accounting, Oracle deploy, success criteria, the definitive Phase 0 verdict (paste `venue_verify.json` from the Oracle run), the 7-14d result. Committed regardless of outcome.

**Reused unchanged:** `coindcx_venue_recorder.sample()` (REST feed source), `run_loop`/`decide`/`FeedSample`/`TraderState` (extended, not rewritten), `venue_verify.py` (run on Oracle as-is), `risk_budget`, the recorder's systemd pattern.

## Data flow

```
DEV (Windows, --feed rest, paper):
  coindcx_venue_recorder.sample()  →  _paper_feed()  →  FeedSample
     (public REST, no auth)                                     ↓
                                          run_loop (live=False, client=None)
                                                  ↓
                                   paper-PnL: 8h funding accrual + basis MTM
                                                  ↓
                                          reports/carry_paper.csv

ORACLE (systemd, --feed csv, paper):
  recorder (24/7) → reports/coindcx_venue.csv  →  csv_feed()  →  FeedSample
                                                                    ↓
                                          run_loop (live=False, client=None)
                                                  ↓
                                          reports/carry_paper.csv + state.json

ORACLE (one-shot):
  venue_verify.py run  →  reports/venue_verify.json (definitive Phase 0 verdict)

paper_check.py  ←  carry_paper.csv + state.json  →  §33 verdict (Phase 2 gate)
```

## Error handling

1. **REST feed `sample()` fails** (network, endpoint down) → `_paper_feed()` returns `None` → `run_loop` feed-outage path (`_on_feed_outage`): logs `FEED_OUTAGE`, sleeps `poll_s`, continues. No halt on a single outage; sustained outage accrues `FEED_OUTAGE` rows (counts against criterion 2).
2. **CSV feed missing/empty** (`coindcx_venue.csv` absent or no rows) → `csv_feed()` returns `None` → same outage path. On Oracle this means the recorder stopped — `FEED_OUTAGE` rows surface it.
3. **8h mark crossing missed** (feed gap spans a mark) → accrue using the first post-gap `fr` (rate-in-force at resumption); log a `FUNDING_ACCRUE` with a `gap=true` flag. Honest, not fabricated.
4. **State corrupt at restart** → existing corrupt-state halt (SPEC rule 5): flatten + halt, don't guess. Counts against criterion 1 (a finding, not auto-fail if explained).
5. **Paper equity DD > 25%** → DD halt (unchanged). Counts against criterion 1 — a real finding (carry should not draw down 25% in 14d).
6. **`venue_verify.py run` on Oracle FAILs fx_conversion** → `redesign_required: true`; Phase 1 paper continues (operational validation); §33 notes the measured FX leak; Phase 2 blocked until hedge-redesign sub-project ships its own Phase 0 PASS.

## Testing (scripts/ `__main__` + app/ pytest)

- `carry_trader.py` `__main__`/`demo()`: mocked `coindcx_venue_recorder.sample()` → REST feed returns a `FeedSample`; simulate an 8h mark crossing → assert `accrued_funding` increments by `qty * fr * entry_spot`; assert `--feed` selection (rest/csv); assert paper ledger row written. 6 existing OK lines stay green; new paper-feed path covered. No live calls in self-check.
- `paper_check.py` `__main__`/`demo()`: synthetic `carry_paper.csv` → assert the 5-criteria verdict (pass-case + fail-case: a `halted_orphan` row → criterion 1 fail).
- No pytest changes required (all new logic is in `scripts/`). If any helper merits a pytest unit, add to `tests/` with `asyncio_mode=auto`.
- No live calls in any self-check. `carry_trader.py --feed rest` against live CoinDCX is the dev iteration invocation; `--feed csv` on Oracle is the validation run.

## Interface (unchanged external surface)

- `run_loop(cfg, client=None, feed=None, state_path=None, live=False)` — signature unchanged. `feed` is now wired by default in `main()` per `--feed`; tests still inject a fake feed.
- `FeedSample` — unchanged. `TraderState` — extended with `accrued_funding: float = 0.0`, `basis_mtm: float = 0.0` (persisted, additive — old state files missing these fields load with defaults via the existing `_load_state` `TraderState(**d)` path; confirm no KeyError on missing keys, or make the loader field-tolerant).
- `venue_verify.py` — unchanged; run on Oracle.

## Out of scope

- Real orders / `--live` (Phase 2 small-real, still gated by Phase 0 PASS + Phase 1 success).
- The hedge-redesign sub-project (USDT-margined perp) — triggered by `fx_conversion` FAIL, separate spec/plan cycle.
- Re-proving the carry edge (§20 backtest did that; Phase 1 is operational validation only).
- Tilt slot / asymmetric risk overlay — sealed `NoTilt` (sub-project 2/3).
- Multi-asset (ETH/SOL) paper — BTC only in Phase 1 (the deploy is BTC; ETH/SOL were walk-forward probes only).
- Continuous paper monitoring beyond the 7-14d window — Phase 1 is a bounded validation run.
- Paid data, colocation, cross-venue arbitrage.

## Open questions for implementation plan

- **8h funding-mark schedule:** confirm 00:00/08:00/16:00 UTC from CoinDCX docs (or infer from the recorder's `efr` transitions on the first Oracle run). The accrual logic keys on crossing these; if the schedule differs, the mark-detection constant updates. Resolve in plan: check docs.coindcx.com funding section; default to 00:00/08:00/16:00 UTC with a logged assertion on first accrual.
- **`TraderState` field-tolerance:** old `carry_trader_state.json` (from sub-project 1 tests/demos) lacks `accrued_funding`/`basis_mtm`. `_load_state` does `TraderState(**d)` — extra keys would TypeError, missing keys use dataclass defaults. Confirm the loader handles both (drop unknown keys, default missing ones) so a state file from sub-project 1 doesn't crash the loader. Resolve in plan.
- **`--feed` arg vs auto-detect:** explicit `--feed {rest,csv}` (default `rest`) is chosen; plan confirms this composes with `--live` (which forces `csv`). Alternatively auto-detect by CSV presence — rejected (explicit is clearer for systemd).
- **Paper-check as script vs §33 section:** `scripts/paper_check.py` (reusable, `__main__` demo) is chosen over an inline §33 analysis; plan confirms the demo self-check.