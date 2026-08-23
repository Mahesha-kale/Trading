# Handoff prompt — paste into a new Claude session

Continue the CoinDCX BTC/ETH/SOL perp strategy research in D:\Programming\Trading.

## CONTEXT — read first
- Memory index: `C:\Users\mahes\.claude\projects\D--Programming-Trading\memory\MEMORY.md`.
  Read all listed files — each is one fact. Key ones: `coindcx-spot-cost-model`,
  `grid-edge-refuted-under-real-costs`, `backtest-engine-exit-contract`,
  `multi-asset-regime-walkforward`, `funding-carry-band`, `macro-prior-walkforward`,
  `microstructure-feed-unblocked`, `cvd-forward-test`, `taker-ratio-walkforward`,
  `carry-funding-regime-walkforward` (§27), `post-conclusion-followups` (§29).
- Research log: `docs/strategies_report.md` — now through **§29**. §1-17 = prior
  sprint (grid, ensemble, funding carry, macro, microstructure); §18 = real perp
  cost model + regime-balanced walk-forward; §19 = multi-asset regime WF; §20 =
  band-gated funding carry (first net-positive); §21 = microstructure feed
  unblocked; §22 = macro prior WF; §23 = carry basis tail; §24 = basis-stop
  de-risk; §25 = CVD forward-test (closes negative); §26 = taker-ratio WF
  (closes negative); **§27 = carry FUNDING-regime WF (closes negative — the last
  open rigor gap); §28 = FINAL SYNTHESIS (research concludes); §29 =
  post-conclusion follow-ups (venue-verify #1, OBI depth #2, volume profile #3)**.
  Read §18-§29 in full.
- Git: on `main`. PR **#14** (order-flow walk-forward) MERGED (commit 0a70545).
  This session's follow-up work is UNCOMMITTED — commit when the user asks.
  Uncommitted: `scripts/carry_funding_regime.py`, `scripts/coindcx_venue.py`,
  `scripts/coindcx_venue_recorder.py`, `scripts/obi_forward.py`,
  `scripts/volume_profile.py`, `scripts/microstructure.py` (MODIFIED — added
  `depth-update-20` capture), `docs/strategies_report.md` (§27/§28/§29 appended).
  `reports/depth_*.csv` and `reports/coindcx_venue.csv` are gitignored data.

## ESTABLISHED FACTS — do not re-derive
- Perp INR-margin futures carry NO 1% TDS (verified CoinDCX support). Perp cost
  model = maker/taker fee + slippage_bps + funding_rate, NO TDS. Do NOT add TDS
  to perp backtests. 1% TDS is SPOT-only (`grid_bot.py` models it).
- `engine.py` exits via ATR-trailing (trend) or fixed-stop+TP (reversion), NOT on
  signal 0. Always use `cfg_for(kind)` from `scripts/rank.py`.
- The fixed 70/30 OOS lands entirely in the 2025-26 downtrend (adversarial to
  long-only; short edge = single-regime bear beta). REGIME-BALANCED WALK-FORWARD
  (`regime_wf.py`: K=4 contiguous folds, fixed params, tagged by buy&hold sign)
  is the PRIMARY gate. Robust = net positive in >half folds AND across BOTH
  regime types. Reproduces §18/§19 exactly (incl the ETH supertrend 1d L/S
  +1058 outlier) — sanity check it still does after any engine change.
- CoinDCX perp fees (VERIFIED via instrument endpoint): maker 0.0236%,
  taker 0.059% — slightly HIGHER than the carry backtest assumed (0.02%/0.04%),
  negligible on carry (few flips). `funding_frequency=8h`.
- CoinDCX funding: NO public HISTORY. Only real-time endpoint
  `public.coindcx.com/market_data/v3/current_prices/futures/rt` (fields
  `fr`=current, `efr`=next, `mp`=mark, `ls`=last). Spot-check: CoinDCX
  `efr=0.0001` = Binance now.
- CoinDCX basis: INR-margin perp has NO USDT spot leg (spot is BTCINR). Synthetic
  USDT spot = BTCINR / USDTINR (2 INR legs → USDTINR FX risk Binance proxy did
  NOT have). INR-spot OHLC history NOT public. Current basis −32..−38bps (within
  Binance §23 range).
- CoinDCX WS exposes depth: `depth-update-20` = 20-level SNAPSHOT ~1/s (NOT a
  diff → OBI = (Σbid−Σask)/(Σbid+Σask) directly, no local book). Retail-friendly
  latency (~1/s, not microsecond HFT).

## VERDICT SO FAR — NO ROBUST EDGE FOUND. RESEARCH CONCLUDED (§28), then §29 follow-ups confirmed.
Every thread closed or parked (full history in report + memory):
- Spot grid / long-short grid: refuted under real spot costs (TDS kills it).
- 23 price strategies + ensemble: empty (§7/§11); diversification = in-sample
  artifact.
- Multi-asset regime WF (BTC/ETH/SOL): no robust edge; 1 ETH outlier = path luck.
- Funding carry (band-gated §20): first net-positive (~7%/yr) but funding-regime
  income + unmodeled basis tail. §23 quantified tail; §24 basis-stop bounds it at
  ~1% for ~0 in-sample cost. §27 funding-regime WF: carry BLEEDS SMALL (NOT flat)
  in negative funding, all income from positive funding → NOT robust.
  Status: WATCHLIST, bounded-tail, execution-dependent — NOT deployed. The ONE
  deploy candidate. §29 venue-verify made it LESS deployable (FX leg +
  forward-only caveats), not more.
- Macro prior (DXY/US10Y/VIX/SP500): no robust edge; VIX best, SVB-contaminated flat.
- Microstructure CVD (§25): 16d ticks, hit%<50% everywhere. CLOSED.
- Taker-buy-ratio (§26): bar order-flow WF, zero robust flags. CLOSED.
- §29 #1 venue-verify: fees verified (higher), funding/basis forward-only, carry
  harder to deploy (FX leg). #2 OBI: accruing (verdict pending). #3 VP: tested on
  16d ticks, no edge (n=8-14 void, maps to refuted reversion/breakout classes).

## LIVE: 4 recorders running 24/7 on Oracle Cloud (140.245.19.185)
- Box: Oracle Cloud Always Free A1.Flex (ARM Ampere), `140.245.19.185`, Ubuntu.
  SSH key: `C:\Users\mahes\Downloads\ssh-key-2026-08-07.key`
  (copy to `/tmp/cloudkey`, `chmod 600`; `ssh -i /tmp/cloudkey ubuntu@140.245.19.185`).
  Verified alive 2026-08-24: 15d up, all 4 units active.
- `recorder-btc/eth/sol` (systemd): now write TWO files each — trades
  (`ticks_B_*.csv`, ~10.4M/9.9M/2.2M rows) AND depth OBI (`depth_B_*.csv`, ~1/s,
  `ts_ms,obi,bid_qty,ask_qty,top_bid,top_ask`). `microstructure.py` was modified
  to capture `depth-update-20` alongside `new-trade`.
- `coindcx-venue.service` (NEW, deployed this session): polls the rt endpoint +
  spot ticker every 60s → `reports/coindcx_venue.csv` (`ts,sym,fr,efr,mp,ls,
  spot_inr,usdtinr,basis_bps`). Accruing CoinDCX funding + basis to close the
  §20/§23 venue caveats forward.
- KEEP VERIFYING each session:
  `ssh -i /tmp/cloudkey ubuntu@140.245.19.185 'systemctl is-active recorder-btc
  coindcx-venue; wc -l ~/Trading/reports/depth_B_BTC_USDT.csv
  ~/Trading/reports/coindcx_venue.csv'`. If box reclaimed → reprovision per
  `deploy/README.md`, re-point at new IP (data on box disk LOST on reclamation;
  periodically `scp` down: `scp -i /tmp/cloudkey
  ubuntu@140.245.19.185:~/Trading/reports/depth_B_BTC_USDT.csv reports/` — one
  file at a time, Windows scp can't split a quoted multi-file path).
- Local data (gitignored): `reports/ticks_B_{BTC,ETH,SOL}_USDT.csv` (16d ticks),
  `reports/binance_{BTCUSDT,ETHUSDT,SOLUSDT}_15m.csv` (perp, w/ taker_buy_base),
  `reports/binance_*_spot_15m.*`, `reports/binance_*_funding.csv`.

## PENDING / NEXT STEPS (in priority order)
1. **OBI forward-test — the ONE live pending verdict (§29 #2).** depth accruing
   ~1/s; needs ≥1 week. `scp` `reports/depth_B_*.csv` down, then
   `PYTHONPATH=. .venv/Scripts/python scripts/obi_forward.py B_BTC_USDT` (and
   ETH/SOL). Gate: hit% materially >50% AND net_eq>1 over ≥1 week. EXPECTED
   NEGATIVE (order flow already-priced per §25/§26; OBI is the third derivative).
   If it closes negative → order-flow class closes at a THIRD level (tick CVD +
   bar ratio + book OBI). This is the strongest remaining test.
2. **Volume profile longer-sample re-test (§29 #3).** 16d was thin (n=8-14,
   void). After MONTHS of accrual, re-run `scripts/volume_profile.py` (try
   smaller windows — 1h/2h — for more samples; or per-session). Both uses map to
   refuted classes (reversion=mean-revert §18, breakout=bull-beta §18) → low EV,
   but real tick VP over a long sample is the honest untested config.
3. **Venue-recorder analysis — close the §20/§23 caveats (§29 #1).** After WEEKS
   of `coindcx_venue.csv` accrual, analyze: (a) does CoinDCX fr/efr track Binance
   funding over time (is the ~7%/yr proxy right)? (b) does CoinDCX basis stay
   <100bps so the §24 basis-stop is free on the actual venue? (c) quantify the
   USDTINR FX-leg noise. This determines whether the carry is deployable on
   CoinDCX at all. Build a small analysis script reading
   `reports/coindcx_venue.csv` (compare fr/efr vs `reports/binance_*_funding.csv`
   aligned by 8h marks; basis distribution vs §23).
4. **Commit the uncommitted work** (when the user asks). Suggested message:
   `feat(research): §27-§29 carry funding-regime WF + post-conclusion follow-ups
   (venue verify, OBI, volume profile); no robust edge, research concludes`.
   Do NOT push without asking. Branch off `main` if committing.
5. **If #1 (OBI) also closes negative → the order-flow class is fully exhausted
   at 3 levels → final stop is warranted.** No new signal class remains untested
   at retail free-data resolution.

## STRATEGIES NOT YET TRIED (honest, mostly LOW-EV or out-of-scope — list, don't auto-pursue)
- Regime-conditional / regime-switch meta-strategy: TESTED (SMA200 gate §18) =
  breakeven, not edge (regime detection lags). A fancier classifier (HMM on
  funding+vol+trend) re-introduces lag + overfit; each regime's strategy is still
  thin after costs. Low EV.
- Confluence / ensemble across classes: TESTED (§11) = in-sample artifact. Each
  class closed negative independently → no expectancy to combine. Low EV.
- VWAP: execution benchmark, not alpha. VWAP reversion/breakout = refuted classes.
- Cross-venue arbitrage (CoinDCX perp vs Binance perp basis): structurally
  different, but needs latency + capital on both venues + withdrawal friction;
  retail execution can't compete. Out of free-data retail scope.
- Lower-fee venue / maker-rebate: the 0.4% taker + slippage is the wall. A
  maker-fee-rebate or lower-fee venue changes the breakeven math — but that's
  venue selection, not a signal. Worth noting, not a strategy to build here.
- Options (if CoinDCX offers crypto options): convex payoffs differ from linear
  perp — genuinely untested info source. Out of current data scope.
- The carry is the ONLY deploy candidate. To actually deploy: verify venue
  (#3 above), engineer the squeeze hedge / reserve (§24), confirm ~7%/yr worth
  the bounded tail + FX leg. Real execution engineering, not a backtest.

## GOAL (unchanged)
Find a strategy with a ROBUST OUT-OF-SAMPLE edge — must hold across BOTH bull
and bear regimes (regime-balanced walk-forward). Always report full AND OOS AND
walk-forward per-fold, flag single-regime results, compare to buy&hold on the
same window. Do not claim edge until positive across BOTH regime types OOS.
(§28 concluded none exists at retail free-data resolution; the remaining work is
closing the 3 pending tests honestly, not re-opening closed classes.)

## CONSTRAINTS
- Real perp costs: maker/taker fee + slippage + funding (use real `funding_rates`
  for the final check), no TDS. Leverage 3, maker_on_limit=True. CoinDCX ACTUAL
  fees maker 0.0236% / taker 0.059% (verified) — prefer these over the old
  0.02/0.04 for any new carry run.
- Regime-balanced walk-forward (K=4 contiguous folds) is the primary gate; 70/30
  split only as a secondary sanity check.
- Always compare to buy&hold on the same window.
- If positive full-sample but negative walk-forward, or positive only in one
  regime type, it's regime beta — say so (the recurring trap).
- ponytail (lazy: reuse, stdlib, shortest diff, no new deps) + caveman (terse)
  are project defaults via hooks. Commit/push only when asked.
- Do NOT spend time on: more parameter tuning on the 23 price strategies (empty),
  ensemble of breakeven signals, re-adding TDS to perp backtests, more
  taker-ratio variants (§26 closed), re-testing grid, more CVD variants (§25
  closed).

## FIRST ACTION
1. Re-read `docs/strategies_report.md` §27-§29 + the memory files (especially
   `post-conclusion-followups`, `carry-funding-regime-walkforward`).
2. Verify the cloud box alive + accruing:
   `ssh -i /tmp/cloudkey ubuntu@140.245.19.185 'systemctl is-active recorder-btc
   recorder-eth recorder-sol coindcx-venue; wc -l ~/Trading/reports/depth_B_BTC_USDT.csv
   ~/Trading/reports/coindcx_venue.csv'`
   `scp` the depth CSVs down if ≥1 week has elapsed (for the OBI forward-test).
3. If ≥1 week of depth has accrued → run `scripts/obi_forward.py` for BTC/ETH/SOL
   (the one live pending verdict). Report hit%/net_eq per pair/config + verdict.
   If <1 week → say so, note accrual progress, and instead either (a) analyze
   `coindcx_venue.csv` if weeks of venue data accrued (close §20/§23 caveats),
   or (b) commit the uncommitted work if the user asks.
4. Do not claim edge. The honest default is: the three pending tests (#1 OBI,
   #2 VP longer-sample, #3 venue accrual) close the remaining rigor, expected
   negative, confirming §28. New signal classes are exhausted at retail
   free-data resolution.