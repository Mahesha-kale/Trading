# Handoff prompt — paste into a new Claude session

Continue the CoinDCX BTC/USDT perp strategy research in D:\Programming\Trading.

## CONTEXT — read first
- Memory index: `C:\Users\mahes\.claude\projects\D--Programming-Trading\memory\MEMORY.md`.
  Read all listed files — each is one fact. Key ones: `coindcx-spot-cost-model`,
  `grid-edge-refuted-under-real-costs`, `backtest-engine-exit-contract`,
  `multi-asset-regime-walkforward`, `funding-carry-band`, `macro-prior-walkforward`,
  `microstructure-feed-unblocked`, `cvd-forward-test`, `taker-ratio-walkforward`.
- Research log: `docs/strategies_report.md` — now through **§26**. §1-17 = prior
  sprint (grid, ensemble, funding carry, macro, microstructure); §18 = real perp
  cost model + engine fixes + regime-balanced walk-forward; §19 = multi-asset
  regime WF (BTC/ETH/SOL); §20 = band-gated funding carry (first net-positive);
  §21 = microstructure feed unblocked; §22 = macro prior walk-forwarded; §23 =
  carry basis tail quantified; §24 = basis-stop de-risk; **§25 = CVD forward-test
  on 16-day accrued ticks (NEW — closes negative); §26 = taker-buy-ratio
  order-flow regime WF (NEW — closes negative)**. Read §18-§26 in full.
- Git: on `main`. PR **#14** (order-flow walk-forward: taker-ratio + CVD
  forward-test, branch `order-flow-walkforward`) opened this session — merge it
  if not yet merged, then continue on `main`. Scripts on main after merge:
  `daily_trend.py`, `breakout_4h.py`, `pull_funding.py`, `real_funding.py`,
  `regime_wf.py` (now taker-ratio-aware: resample sums `taker_buy_base`, 5 added
  candidates), `funding_carry.py`, `funding_carry_band.py`, `basis_risk.py`,
  `carry_stop.py`, `microstructure.py`, `cvd_forward.py`, `pull_binance.py`
  (now futures+spot, ms→µs fix, AND keeps `taker_buy_base`/`taker_buy_quote`),
  `app/strategy/taker_ratio.py` (NEW registered strategy).
- Engine: `app/backtest/engine.py` has `BacktestConfig.funding_rates` (dynamic
  signed funding) + `regime_sma` + `allow_short` + `maker_on_limit`.
  `app/strategy/taker_ratio.py`: persistent-direction + deadband-hysteresis
  order-flow signal (ratio = taker_buy_base/volume ∈ [0,1], 0.5 = balanced).
- Data on disk (gitignored, local): `reports/binance_{BTCUSDT,ETHUSDT,SOLUSDT}_15m.csv`
  (perp, 2023-01→2026-07, NOW carry `taker_buy_base`/`taker_buy_quote`),
  `reports/binance_{BTCUSDT,ETHUSDT,SOLUSDT}_spot_15m.*` (spot, same window),
  `reports/binance_*_funding.csv` (8h marks), `reports/ticks_B_{BTC,ETH,SOL}_USDT.csv`
  (16 days of real CoinDCX perp trades, ~10.4M/9.9M/2.2M rows, scp'd from the box).

## ESTABLISHED FACTS — do not re-derive
- Perp INR-margin futures carry NO 1% TDS (verified CoinDCX support). Perp cost
  model = maker/taker fee + slippage_bps + funding_rate, NO TDS. Do NOT add TDS
  to perp backtests. 1% TDS is SPOT-only (`grid_bot.py` models it).
- CoinDCX spot has NO shorting → delta-neutral carry is one-sided only (short
  perp + long spot, harvest positive funding; 1% TDS on the spot SELL at flatten).
- `engine.py` exits via ATR-trailing (trend) or fixed-stop + take_profit
  (reversion), NOT on signal 0. Always use `cfg_for(kind)` from `scripts/rank.py`.
- For long/short use a PERSISTENT-direction signal so the engine re-arms after a
  stop-out (supertrend with use_short=True; taker_ratio is built this way).
- The single 70/30 OOS lands entirely in the 2025-26 downtrend — adversarial to
  long-only, makes short edge = single-regime bear beta. USE THE REGIME-BALANCED
  WALK-FORWARD (`regime_wf.py`: K=4 contiguous folds, fixed params, each scored,
  tagged up/dn by buy&hold sign) as the PRIMARY robustness test. Robust = net
  positive in >half the folds AND across BOTH regime types. Reproduces §18/§19
  exactly (incl the ETH supertrend 1d L/S +1058 ROBUST outlier) — sanity check it
  still does after any engine change.
- `pull_binance.py` NOW keeps `taker_buy_volume`/`taker_buy_quote_volume` (aliased
  to `taker_buy_base`/`taker_buy_quote`). No pyarrow locally → `fetch_binance`
  writes CSV (parquet attempt fails, falls back); the "cached -> .parquet" log
  line is misleading, it actually wrote .csv. `regime_wf.resample()` reads the
  .csv and sums `taker_buy_base` when present.

## VERDICT SO FAR — NO ROBUST EDGE FOUND (order-flow class now CLOSED)
Every thread closed or parked (full history in the report + memory):
- Spot grid / long-short grid: refuted under real spot costs (TDS kills it).
- 23 price strategies + ensemble: proven empty (§7, §11); diversification is an
  in-sample artifact.
- Multi-asset regime WF (BTC/ETH/SOL perp, supertrend/ema/etc): no robust edge.
  1 ETH outlier (supertrend 1d L/S) = path luck, fails cross-asset.
- Funding carry (band-gated, §20): first net-positive after costs (~7%/yr
  in-sample) but over a funding-positive bull window; §23 quantified the basis
  tail; §24 a 100bps basis-stop is FREE in-sample and caps the tail at 1%.
  **Status: watchlist, bounded-tail, execution-dependent — NOT deployed.**
  Carry was NEVER walk-forwarded across FUNDING regimes (only price regimes
  tested) — the ONE open rigor gap (see open decision #1).
- Macro prior (DXY/US10Y/VIX, §22): no robust edge; VIX best prior but
  SVB-contaminated to flat.
- Microstructure CVD (§25): recorder FIXED + DEPLOYED; forward-test on 16-day
  ticks — hit% <50% on every config/pair, no short-horizon CVD edge. CLOSED.
- Taker-buy-ratio order-flow (§26): bar-level order-flow imbalance regime WF on
  BTC/ETH/SOL — zero robust flags in 15 cells (whipsaw / bull-beta that fails
  cross-asset replication / inert). CLOSED. Both order-flow tests (tick §25 +
  bar §26) agree: order flow is coincident, already in the price.

## LIVE: microstructure recorders running 24/7 (Oracle Cloud)
- Box: Oracle Cloud Always Free A1.Flex (ARM Ampere), `140.245.19.185`, Ubuntu.
  SSH key: `C:\Users\mahes\Downloads\ssh-key-2026-08-07.key`
  (copy to /tmp/cloudkey, chmod 600; `ssh -i /tmp/cloudkey ubuntu@140.245.19.185`).
- Verified alive 2026-08-23: all 3 units active (`recorder-btc/eth/sol`), 16 days
  of ticks accrued (BTC 10.4M rows) — the continuous WS traffic kept the box past
  the ~7d reclamation window (confirms the memory hypothesis). KEEP VERIFYING
  each session; if reclaimed → reprovision per `deploy/README.md`, re-point at new
  IP (accrued ticks on box disk are LOST on reclamation; periodically `scp` down).
- Data: `~/Trading/reports/ticks_{B_BTC_USDT,B_ETH_USDT,B_SOL_USDT}.csv`
  (gitignored). scp one at a time (Windows scp does NOT split a quoted
  multi-file remote path — `scp host:'f1 f2'` fails; loop per file or use a glob).
- `scripts/cvd_forward.py` runs on the accrued sample. Verdict gate: hit%
  materially >50% AND net_eq>1 over ≥1 week. §25 result: FAILS (hit%<50% everywhere).

## OPEN DECISION — pick a direction (my recommendation first)
1. **(RECOMMENDED) Carry funding-regime walk-forward — the one untested rigor
   gap.** Carry (§20) was only tested in-sample over a bull/funding-positive
   window + price-regime folds. It was NEVER walk-forwarded across FUNDING
   regimes OOS. Split the window by FUNDING regime (sustained positive vs
   negative funding periods) and score carry OOS in each — does it survive a
   negative-funding regime, or only go flat (opportunity cost)? Caveat: 2023-26
   is ~78% positive funding (only ~22% negative), so negative-regime folds may be
   thin. Low deploy priority (CoinDCX no spot short + basis tail §23-§24) even if
   it passes, but it closes the last open thread rigorously. Reuses
   `funding_carry_band.py` + the funding CSVs.
2. **Volume profile (POC / value areas) from accrued ticks.** 16 days of ticks
   now on disk → a crude volume-at-price VP is testable (true VP needs more
   accrual; the OHLC-approximation is weaker). Lower confidence than (1); the
   order-flow class already closed negative at two levels (§25/§26), so VP is a
   long shot.
3. **Conclude the research.** Every thread is closed or parked: spot grid,
   ensemble, trend (5m-1d, gated/ungated, L/L-S), carry, macro, order-flow (tick
   CVD + bar taker-ratio). No robust retail edge exists on these perps at
   free-data resolution across both bull and bear regimes. The honest next step
   may be a final synthesis + stop, optionally leaving the carry watchlist
   (bounded-tail, execution-dependent) as the only deploy candidate if the
   venue/basis execution is ever engineered. If (1) also closes negative, this
   is the conclusion.

## GOAL (unchanged)
Find a strategy with a ROBUST OUT-OF-SAMPLE edge — must hold across BOTH bull
and bear regimes (regime-balanced walk-forward). Always report full AND OOS AND
walk-forward per-fold, flag single-regime results, compare to buy&hold on the
same window. Do not claim edge until positive across BOTH regime types OOS.

## CONSTRAINTS
- Real perp costs: maker/taker fee + slippage + funding (use real `funding_rates`
  for the final check), no TDS. Leverage 3, maker_on_limit=True.
- Regime-balanced walk-forward (K=4 contiguous folds) is the primary gate; 70/30
  split only as a secondary sanity check.
- Always compare to buy&hold on the same window.
- If positive full-sample but negative walk-forward, or positive only in one
  regime type, it's regime beta — say so (the recurring trap).
- ponytail (lazy: reuse, stdlib, shortest diff, no new deps) + caveman (terse)
  are project defaults via hooks. Commit/push only when asked.
- Do NOT spend time on: more parameter tuning on the 23 price strategies (proven
  empty), ensemble of breakeven signals, re-adding TDS to perp backtests, more
  taker-ratio variants (§26 closed the class — 1h/4h/gated/edge all tested).

## FIRST ACTION
Re-read `docs/strategies_report.md` §18-§26 + the memory files. Verify the cloud
box is alive (`ssh ... systemctl is-active recorder-btc`) and the PR #14 branch
is merged. Then start the chosen direction (default: #1 carry funding-regime
walk-forward — build a funding-regime split, run `funding_carry_band` OOS in each
funding regime, report per-regime carry net + whether it survives negative
funding or only goes flat). If #1 closes negative → write the final synthesis
(option #3). Report per-regime tables: asset × {funding regime, events, flips,
gross funding, net after costs, flattens} + verdict. Do not claim edge until
positive across BOTH funding-regime types out-of-sample. use caveman ponytail