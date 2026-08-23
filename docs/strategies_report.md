# BTC/USDT Perp — Strategy Research, Backtest & Robustness Report

**Symbol:** B-BTC_USDT (CoinDCX perpetual, isolated margin, INR)
**Date:** 2026-08-05
**Data:** 1m (62d, ~90k bars, ends 2026-07-27), 5m (150d, ~52k bars), 15m (330d, ~35k bars)
**Commission:** maker/taker fees + slippage + funding as configured in `BacktestConfig`
**Risk controls (institutional, applied in every backtest):** leverage 3, **5% daily-loss
kill-switch** (new trades blocked once daily realized loss ≥ 5% of day-start equity),
max-drawdown guard, **1 position only**, ATR-based stops, break-even, partial exits.
**Capital:** 10,000. **Tuning:** grid search on a recent 8,000-bar train slice per
strategy, scored by Sharpe; final metrics on full sample + 30% OOS holdout.

> **Headline (evidence-based, not assumed):** Under the above realistic controls,
> **no single static strategy is profitable** full-sample. Every entry has negative
> Sharpe, profit factor < 1, and Monte-Carlo P(profit) ≤ 0.29. **However**, regime
> segmentation reveals **conditional edge**: several strategies are strongly profitable
> in one regime and bleed in the others. The robustness-ranked top 5 are the *least
> fragile* (low DD, non-curve-fit, statistically sufficient trades), not the most
> profitable — per the stated priority of consistency/robustness over max profit.

---

## 1. Methodologies & indicators covered

**Methodologies implemented as strategies:** Wyckoff (spring/SOS), Trend (EMA/ADX/PSAR/
SuperTrend/Ichimoku/Donchian breakout), Mean-Reversion (Bollinger/RSI/StochRSI/CCI/
Keltner), Breakout (Donchian/Opening-Range), Pullback (EMA/VWAP), Liquidity Sweep,
Fair-Value-Gap, OBV divergence, MACD. 22 strategies total (14 new persistent-1 +
8 original transition-semantic).

**Indicators (app/strategy/indicators.py):** EMA, SMA, VWAP, RSI, MACD, ADX (Wilder),
ATR, Bollinger, SuperTrend, Ichimoku, Donchian, Keltner, CCI, OBV, CMF, volume MA,
StochRSI, PSAR, pivots.

**Metrics (app/backtest/metrics.py):** net/gross profit/loss, win/loss rate, profit
factor, max drawdown, Sharpe, Sortino, Calmar, recovery factor, avg & largest win/loss,
expectancy, avg duration, consecutive wins/losses, monthly & annualized return, return
on capital, trade count.

**Robustness (app/backtest/robustness.py):**
- **Monte Carlo** — bootstrap trade-sequence 500× (resample realized PnLs with
  replacement), report median/p5/p95 net, P(profit), median & worst max-DD, median
  consecutive losses.
- **Regime split** — tag bars bull/bear/sideways via slow-EMA slope (ATR-scaled
  threshold); backtest each regime separately.
- **Parameter sensitivity / walk-forward** — implemented; not run on the full 22
  (compute cost) — reserved for the top 5 in §5.

**Weighted score (0–100, what the leaderboard ranks on):**
PF(OOS) 20 · Sharpe(OOS) 15 · Sharpe(full) 10 · low-DD 15 · **OOS/full stability
(curve-fit guard) 15** · MC P(profit) 10 · trade-count sufficiency (≥30) 10 ·
non-deployable penalty −5. OOS metrics carry more weight than full-sample to resist
overfitting, exactly as requested.

---

## 2. Leaderboard (all 22, ranked)

`dep` = paper/live deployable (persistent-1 signal semantics). `mcP` = Monte-Carlo
P(profit). Full-sample columns.

| # | strategy | tf | score | PF | Sharpe | maxDD | trades | mcP | dep |
|---|----------|----|------:|---:|-------:|------:|-------:|----:|:---:|
| 1 | stochrsi_reversal | 5m | 10.27 | 0.81 | -2.45 | 0.098 | 229 | 0.22 | Y |
| 2 | obv_divergence | 15m | 5.94 | 0.58 | -2.03 | 0.114 | 28 | 0.12 | Y |
| 3 | ema_pullback | 15m | 5.15 | 0.79 | -1.56 | 0.136 | 63 | 0.23 | Y |
| 4 | donchian_breakout | 15m | 3.06 | 0.64 | -2.20 | 0.101 | 48 | 0.09 | Y |
| 5 | psar_trend | 15m | 2.32 | 0.44 | -2.00 | 0.097 | 19 | 0.11 | Y |
| 6 | adx_trend | 15m | 1.91 | 0.46 | -1.76 | 0.094 | 16 | 0.12 | Y |
| 7 | liquidity_sweep | 5m | 1.86 | 0.41 | -3.22 | 0.087 | 20 | 0.07 | Y |
| 8 | opening_range_breakout | 15m | 1.61 | 0.34 | -2.23 | 0.073 | 16 | 0.04 | Y |
| 9 | cci_reversion | 5m | 0.09 | 0.38 | -5.87 | 0.079 | 214 | 0.00 | Y |
| 10 | ichimoku_breakout | 15m | -0.75 | 0.32 | -2.82 | 0.089 | 18 | 0.04 | Y |
| 11 | fair_value_gap | 5m | -1.0 | 0.44 | -1.73 | 0.047 | 4 | 0.29 | Y |
| 12 | wyckoff | 15m | -1.0 | 0.17 | -2.86 | 0.060 | 13 | 0.00 | Y |
| 13 | keltner_mr | 5m | -1.17 | 0.53 | -5.38 | 0.098 | 253 | 0.01 | Y |
| 14 | macd | 15m | -3.56 | 0.39 | -2.54 | 0.089 | 20 | 0.04 | N |
| 15 | vwap_reclaim | 15m | -4.78 | 0.41 | -2.46 | 0.123 | 19 | 0.07 | N |
| 16 | vwap_pullback | 5m | -7.34 | 0.00 | -4.25 | 0.059 | 9 | 0.00 | Y |
| 17 | supertrend | 15m | -8.09 | 0.33 | -2.96 | 0.092 | 18 | 0.02 | N |
| 18 | breakout | 15m | -10.19 | 0.31 | -2.75 | 0.077 | 16 | 0.02 | N |
| 19 | rsi_reversal | 15m | -10.3 | 0.00 | -2.53 | 0.057 | 5 | 0.00 | N |
| 20 | ema_cross | 15m | -11.11 | 0.28 | -2.75 | 0.099 | 14 | 0.02 | N |
| 21 | bollinger | 15m | -11.2 | 0.00 | -2.55 | 0.058 | 5 | 0.00 | N |
| 22 | atr_trend | 15m | -11.34 | 0.17 | -3.02 | 0.072 | 14 | 0.00 | N |

Full per-strategy metrics (OOS, MC distribution, regime split, optimized params) in
`reports/rank_results.json`.

---

## 3. Top 5 — robustness detail

### #1 stochrsi_reversal (5m) — score 10.27 — **most robust**
- Optimized params: `atr_mult=3.0` (rsi/stoch/atr period 14, TP 2×ATR)
- Full: PF 0.81, net -327, Sharpe -2.45, Sortino -0.31, Calmar -1.61, maxDD **0.098**,
  win-rate **0.917**, 229 trades, expectancy -1.43, ann. -15.8%
- OOS (30% holdout): PF 0.86, Sharpe -2.11, 65 trades — **OOS ≈ full → not curve-fit**
- Monte Carlo: P(profit) 0.22, median net -339, p5 -1058 / p95 +324, median DD -6%,
  worst DD -20%, median consec-loss 2
- **Regime:** bull **+23** (147 trades), bear -512 (71), sideways -353 (119)
- Profile: classic mean-reversion — 92% hit-rate, small wins, fat-tail losers. Lowest
  DD of the high-trade-count group; the 5% daily-loss switch caps the left tail.
- **Verdict:** most statistically significant (229 trades) and least curve-fit, but
  negative expectancy full-sample. **Paper-forward-validate.**

### #2 obv_divergence (15m) — score 5.94
- Params: `swing=40, atr_mult=4.0`. PF 0.58, Sharpe -2.03, maxDD 0.114, 28 trades,
  win-rate 0.25, expectancy -19.9. MC P(profit) 0.12.
- **Regime:** sideways **+1367** (80 trades), bear -519, bull -207. Strong sideways edge.

### #3 ema_pullback (15m) — score 5.15
- Params: `tol_atr=0.4, atr_mult=4.0`. PF 0.79, Sharpe -1.56 (best Sharpe of top 5),
  maxDD 0.136, 63 trades, win-rate 0.41, expectancy -8.2. MC P(profit) 0.23.
- **Regime:** sideways **+1532** (26), bear **+358** (83), bull -557 (50). Profitable
  in 2 of 3 regimes; loses only in bull.

### #4 donchian_breakout (15m) — score 3.06
- Params: `lookback=50, atr_mult=4.0`. PF 0.64, Sharpe -2.20, maxDD 0.101, 48 trades,
  win-rate 0.42, expectancy -11.7. MC P(profit) 0.09. Regime: bear +29 only positive.

### #5 psar_trend (15m) — score 2.32
- Params: `atr_mult=4.0`. PF 0.44, Sharpe -2.00, maxDD 0.097, 19 trades, win-rate 0.21,
  expectancy -26.4. MC P(profit) 0.11. **Regime: sideways +1326** (74), else negative.

---

## 4. Cross-cutting findings (evidence, not assumption)

1. **No static strategy survives full-sample.** All 22 have PF < 1 and Sharpe < 0
   under realistic fees + 5% daily-loss + leverage 3. This is the dominant finding.
2. **Regime-conditional edge is real and large.** Sideways regime: obv +1367,
   ema_pullback +1532, psar +1326 (on 10k capital, over the sideways bars). Bull
   regime: stochrsi +23 (positive, high-trade-count). The edge is there — it is
   *regime-filtered*, not evergreen. **A regime switch (EMA-slope / ADX gate) that
   enables stochrsi in bull and the reversion/pullback book in sideways is the
   evidence-backed path to live profitability.**
3. **Mean-reversion profile dominates the top.** stochrsi/ema_pullback show high
   hit-rate + fat left tail; the institutional daily-loss switch is exactly what
   caps that tail — without it the left tail is worse (this is why tight risk
   control ranks them above raw-return trend systems).
4. **Tuning did not create overfits.** OOS Sharpe ≈ full-sample Sharpe for the top
   entries (stochrsi -2.11 vs -2.45; ema_pullback degrades, flagged). The stability
   score component rewarded consistency and penalized curve-fits.
5. **Original 8 transition-semantic strategies** rank bottom and are flagged
   non-deployable (their signal exits on the next bar in the live engine); kept for
   backtest comparison only.
6. **Wyckoff** (the originally researched method) has no edge on BTC 15m in this
   window: 13 trades, PF 0.17, MC P(profit) 0.00. The spring/SOS schematic is too
   rare intraday on BTC perp to generate statistical weight — documented in
   `docs/wyckoff.md`.

---

## 5. Recommendation & deployment

**Live deployment: NONE.** Quantitative evidence does not support live capital on
any single static strategy — all have negative expectancy full-sample and MC
P(profit) < 0.3. Per the requirement that recommendations be evidence-based, I do
not recommend going live.

**Paper deployment (forward validation): `stochrsi_reversal` on 5m.**
- Rationale: highest robustness score, lowest DD (0.098) of the high-trade-count
  group, 229 trades (statistical significance), OOS≈full (not curve-fit), and the
  only top-5 entry positive in the bull regime. Paper is the correct venue for an
  unproven-but-robust strategy. `.env` `DEFAULT_STRATEGY=stochrsi_reversal`,
  `TRADING_MODE=paper`, `DEFAULT_LEVERAGE=3`.
- **Acceptance gate for live:** ≥200 paper trades, OOS-style PF > 1.1, MC P(profit)
  > 0.6, maxDD < 8%, and the regime filter of §4.2 implemented and verified.

**Next engineering step (evidence-backed, not speculative):** add a regime gate
(EMA-200 slope + ADX) that routes to stochrsi_reversal in bull / ema_pullback or
obv_divergence in sideways / flat in bear. This is the single change the data says
would flip the book positive; it is the natural follow-on, not new speculation.

---

*Artifacts: `reports/rank_results.json` (full metrics), `scripts/rank.py`
(harness, re-runnable), `app/backtest/robustness.py` (MC/regime/sensitivity/walk-forward).*

---

## 6. Follow-on: regime gate — TESTED, did NOT flip positive

Built `RegimeGate` (`app/strategy/batch.py`): tags bars bull/bear/sideways via
EMA-200 slope + ADX, routes entries to a per-regime sub-strategy (default
sideways+bear → `ema_pullback`, bull → flat or `stochrsi_reversal`), flat
otherwise. Backtested 8 variants (bull ∈ {None, stochrsi}, ADX-thresh ∈ {15,25},
atr_mult ∈ {3,4}) on 15m full + 30% OOS:

| bull | adx | am | full PF | full net | full Sharpe | full DD | trades | OOS PF | OOS Sharpe |
|------|-----|----|--------:|---------:|------------:|--------:|-------:|-------:|-----------:|
| None | 15 | 3.0 | 0.67 | -506 | -1.62 | 0.091 | 31 | 0.69 | -2.89 |
| None | 15 | 4.0 | 0.54 | -526 | -1.90 | 0.091 | 24 | 0.55 | -3.50 |
| None | 25 | 3.0 | 0.45 | -503 | -2.21 | 0.083 | 20 | 0.65 | -3.41 |
| None | 25 | 4.0 | 0.78 | -546 | -1.54 | 0.135 | 58 | 0.62 | -3.28 |
| stochrsi | 15 | 3.0 | 0.63 | -505 | -1.96 | 0.099 | 33 | 0.67 | -2.95 |
| stochrsi | 15 | 4.0 | 0.60 | -509 | -2.05 | 0.110 | 31 | 0.65 | -2.59 |
| stochrsi | 25 | 3.0 | 0.63 | -505 | -1.96 | 0.099 | 33 | 0.67 | -2.95 |
| stochrsi | 25 | 4.0 | 0.60 | -509 | -2.05 | 0.110 | 31 | 0.65 | -2.59 |

**All negative.** No variant beats `ema_pullback` alone, let alone flips positive.

**Why the §4.2 sideways optimism did not survive:** the +1532 sideways result
came from the `regime_split` helper, which runs an **independent backtest per
regime — each resetting capital and position state**. A continuous gated
backtest does not reproduce that because (a) it takes far fewer gated trades
(20–58 vs 63 ungated), (b) the gate's regime tag (EMA-slope **+ ADX**) differs
from the split's tag (EMA-slope only) so "sideways" is a different bar set,
(c) daily-loss / position carry across regime boundaries is lost in per-regime
resets, and (d) the sideways "edge" was likely a handful of lucky trades that
don't recur when gated. **The independent-reset regime split overstated
conditional edge.** This *strengthens* the headline conclusion: no static or
simple-regime-gated strategy is profitable on BTC perp in this window under
realistic controls.

**Decision:** `RegimeGate` stays in the registry as a tested research artifact
but is **not deployed**. Paper deployment remains `stochrsi_reversal` (still
the most robust by the §2 criteria). The realistic path to live is not a
cleverer gate but more edge sources: longer/different data, more instruments,
or a fundamentally different signal — not re-routing the current negative-
expectancy book.

---

## 7. Follow-on: "make it profitable" — exhaustive cost/risk tuning (TESTED, NOT profitable)

Goal: find any config that flips a strategy to full-sample PF>1, Sharpe>0 under
realistic costs. Levers applied (in order of expected payoff):

1. **Maker-fee entry (engine fix, KEPT).** `app/backtest/engine.py` entry fee
   now respects `maker_on_limit` (was dead config — entry always taker). Realistic
   limit-entry model halves entry cost (0.025% vs 0.06%). Lifted PF ~10% across
   the board (stochrsi 0.81→0.89). Real improvement, committed.
2. **Re-ran all 23 strategies with maker + a tighter reversion stop (0.02 not
   0.05).** Leaderboard (`reports/rank_maker.json`): all 23 STILL negative.
   Best: stochrsi PF 0.89, ema_pullback 0.80, regime_gate 0.64. None PF>1.
3. **Stop-width sweep** (stochrsi, maker, rps 0.006–0.03): PF 0.82–0.95, win-rate
   60–88% — no width crosses PF>1. The 5% stop's rare fat losses and tight stops'
   noise exits both lose; the gross edge is ~break-even so fees dominate either way.
4. **Daily-loss limit sweep** (0.05 / 0.10 / off): **identical results** — at 1%
   risk-per-trade it never trips (needs ~5 losing trades in one day). Not a lever.
5. **atr_mult sweep** (2.5–6.0): best at 3.0; wider stops worse. Not a lever.
6. **TP-multiple sweep** (`tp_mult` param added to `stochrsi_reversal`, KEPT).
   Bigger target shrinks the fee fraction of each win. **One positive-OOS-Sharpe
   config found**: `tp_mult=8, atr_mult=2.5, maker` → OOS PF 1.11, Sharpe **+0.31**,
   +152 net over 31 trades (the only positive Sharpe in the entire search). But
   full-sample still PF 0.89 / -504 — the edge is confined to the recent 30%
   (trending) regime; train 70% is strongly negative. **Regime luck, not robust.**
   No `tp_mult` achieves full-sample PF>1.

**Decisive negative result — live/paper engine diverges from backtest.** The
live engine (`app/live/engine.py`) exits purely on `sig==0` (the strategy's own
internal TP/SL in `generate_signals`), with a hardcoded 2 ATR sizing stop; it
ignores `risk_pct_stop`, `atr_mult`, and the engine's own trailing. So the
backtest risk tuning above does NOT transfer to paper/live. A signal-faithful
sim (entry on 0→1, exit on 1→0, maker fees, no daily-loss gate) shows the
strategy-driven exits churn far more trades than the engine backtest (1575 vs
311 on stochrsi tpm=2) → fees compound to a **-92%** result. The daily-loss gate
in the live RiskManager cuts this back toward the backtest's trade count, but
the live exit logic is materially different and untested by the engine backtest.

**Verdict:** No combination of cost/risk/TP tuning makes any of the 23 strategies
profitable full-sample under realistic costs. The gross edge is ~break-even;
fees + the stop asymmetry + live churn push it negative. "Making it profitable"
is not achievable by parameter tuning on this strategy set + data — it requires
a new edge source (different instrument, longer history, or a different signal
family), not more knobs on the current negative-expectancy book.

**Delivered (real improvements, kept in code):** maker-fee entry engine fix;
`tp_mult` parameter on `stochrsi_reversal`; `RegimeGate`; structlog-silenced
re-runnable harnesses (`scripts/rank.py`, `scripts/sweep.py`).

**Paper deploy recommendation:** the most *robust* config — `stochrsi_reversal`
default params (`tp_mult=2`, maker) — for forward validation only, with the
explicit expectation it is **not backtest-profitable**. The `tp_mult=8` OOS-
positive config is a higher-EV but fragile gamble (regime luck, 31 OOS trades);
deploy it to paper only if accepting that it is chasing a recent-regime fluke.
Live capital: still not warranted on the evidence.
---

## §8. Signal-faithful multi-symbol rank (BTC / ETH / SOL)

The engine backtest does not predict paper/live (§7), so all prior ranks were
tuning the wrong sim. Built `app/backtest/faithful.py` — `run_faithful`
reproduces the live engine loop exactly: entry on 0→1, exit on 1→0,
`RiskManager` gating (daily-loss / drawdown / max-pos), 2-ATR sizing stop,
maker/taker fees, isolated-margin liquidation, 8h funding. Self-check passed
(3 trades on synthetic). `scripts/rank_faithful.py` grids each persistent-1
strategy on train tail(8000), runs full + OOS (last 30%) via `run_faithful`,
scores (PF/Sharpe/maxDD/stability/trade-count + profit bonus). Reports
`reports/rank_faithful.json`.

**Cross-symbol profitable (full-sample net>0 AND PF>1):**

| symbol | profitable | best (full) | OOS Sharpe |
|--------|-----------|-------------|-----------|
| BTC | 1 | vwap_pullback 5m +553 PF1.09 | **-126** |
| ETH | 6 | donchian 15m +1289 PF1.11; ema_pullback +1077 PF1.20 sh1.52 | **-8 to -193** |
| SOL | 1 | stochrsi 5m +10 PF1.00 | -92 |

**Every "profitable" config has a deeply negative OOS Sharpe.** Full-sample
profit on ETH (6 strategies, some with full Sharpe >1) is **regime luck**: the
last 30% OOS window is uniformly negative. `regime_gate` blows up (liquidation,
dd 1.16-1.49) on all three symbols — the router adds risk without edge. No
strategy transfers edge to ETH/SOL either; the edge simply does not exist in
this signal family under realistic costs.

## §9. Long-history walk-forward (2.5yr Binance public data, multi-regime)

The CoinDCX API caps 15m at ~330d — a single regime, which is why everything
looked like regime luck. Pulled 2.5yr (2023-01..2025-07) BTC + ETH 15m from
Binance Vision public klines (`scripts/pull_binance.py`, stdlib only, ~90k bars
each, cached `reports/binance_*_15m.csv`). `scripts/long_history.py` runs each
15m deployable strategy via `run_faithful` full-sample + 4-fold rolling
walk-forward (tune on expanding train window, score next OOS window).

BTC 15m results (the decisive test — 2.5yr spans 2023 bear → 2024 bull → 2025
chop):

| strategy | full PF | full net | full Sharpe | OOS folds pos | agg OOS net |
|----------|--------|---------|------------|--------------|-------------|
| obv_divergence | **1.43** | **+4112** | **5.50** | **0/4** | **-2413** |
| adx_trend | 1.33 | +3081 | 2.19 | 0/4 | -2355 |
| ichimoku_breakout | 1.28 | +1577 | 1.39 | 0/4 | -2158 |
| opening_range_breakout | 1.27 | +1759 | 1.90 | 0/4 | -2252 |
| donchian_breakout | 1.08 | +919 | -0.01 | 0/4 | -2414 |
| regime_gate | 1.10 | — | — | 1/4 | -1817 |
| ema_pullback | 0.61 | -608 | -12.6 | 0/4 | -2349 |
| psar_trend | 0.37 | -581 | -22.7 | 0/4 | -2181 |
| wyckoff | 0.21 | -538 | -6.7 | 1/4 | -1214 |

**Zero strategies are durable** (need full PF>1, >50% pos folds, agg OOS>0).
The strongest in-sample case (obv_divergence, full PF 1.43, +4112, Sharpe 5.5)
loses -2413 aggregated across the four OOS windows with **0/4 positive folds**.
At best two strategies scrape 1/4 positive folds (wyckoff, regime_gate) — both
still full-negative or agg-OOS-negative. This is the cleanest possible negative
result: on multi-regime data, the gross "edge" is pure in-sample fit; it has
**zero out-of-sample persistence**. The single-regime CoinDCX window was hiding
this by making the in-sample fit look like a real edge.

## §10. Portfolio ensemble + correlation sizing

`scripts/ensemble.py` — picks the top-5 faithful-ranked ETH strategies, reruns
each via `run_faithful`, builds daily-return correlation, sizes by inverse-vol,
backtests the blended portfolio. Reports `reports/ensemble.json`.

Correlation (ETH top-5): low cross-block — 5m strategies corr 0.25 with each
other, 15m block corr 0.42-0.76, near-zero across the 5m/15m divide. Low
correlation is the precondition for diversification.

| portfolio | PF | net | Sharpe | maxDD | annRet |
|-----------|----|-----|--------|-------|--------|
| inverse-vol | 1.04 | +131 | 0.31 | 0.122 | 5.0% |
| equal-weight | 1.03 | +58 | 0.21 | 0.100 | — |
| (best single, donchian) | 1.11 | +1288 | 0.47 | 0.189 | — |

**Diversification works mechanically** — it cuts drawdown (0.12 vs 0.19 single)
and smooths the curve (Sharpe 0.31 where the equal-weight blend of dead-OOS
strategies would naively be ~0). But this is **full-sample, in-sample**: every
component's OOS Sharpe is deeply negative (§8), and §9 shows zero OOS fold
persistence. Blending uncorrelated negative-expectancy strategies does not
manufacture positive expectancy out-of-sample — it only reduces variance. The
portfolio's 5% annRet / 0.31 Sharpe is the same regime-luck artifact as the
single strategies, just averaged.

## Overall verdict (post §8-§10)

The four follow-ups converge on one evidence-based conclusion: **no strategy in
this 23-strategy family has out-of-sample edge** under realistic perp costs on
BTC, ETH, or SOL, on either the 330d CoinDCX window or 2.5yr multi-regime
Binance history. Full-sample profit appears (ETH, 2.5yr) but **never persists
OOS** (0/4 walk-forward folds, every OOS Sharpe negative). The faithful engine
now lets us measure this honestly — prior engine backtests were misleading.

Live capital is not warranted. The path forward is not more parameter tuning on
this signal set (proven empty), but a new edge source: regime-conditional
meta-strategies, cross-exchange basis, funding-rate carry, or order-flow /
microstructure signals — validated with the same faithful + walk-forward rigour.

**Delivered this sprint (kept):** `app/backtest/faithful.py` (live-predicting
backtest), `scripts/rank_faithful.py` (multi-symbol faithful rank),
`scripts/pull_binance.py` (long public history), `scripts/long_history.py`
(multi-regime walk-forward), `scripts/ensemble.py` (portfolio + correlation).
`reports/rank_faithful.json`, `reports/ensemble.json`, Binance 15m caches.

---

## §11. Ensemble OOS walk-forward

§10 showed the portfolio's Sharpe/dd benefit was in-sample only. This closes
that: dense daily equity per strategy (dormant stretches = flat, ffill), weights
tuned on TRAIN 70% daily returns (inverse-vol + closed-form min-variance + equal),
frozen and applied to OOS 30%. `scripts/ensemble_oos.py` → `reports/ensemble_oos.json`.

| scheme | OOS PF | OOS net | OOS Sharpe | OOS maxDD |
|--------|--------|---------|-----------|-----------|
| inverse-vol | 0.10 | -334 | -4.69 | 0.033 |
| min-variance | 0.14 | -209 | -3.75 | 0.021 |
| equal-weight | 0.09 | -452 | -5.00 | 0.045 |
| best single (flat) | — | 0 | 0.00 | — |

**Verdict: diversification does NOT help OOS.** Every weighting scheme loses OOS
(OOS Sharpe -3.8 to -5.0), worse than the best single (flat at 0). The §10
portfolio benefit was an in-sample artifact — blending uncorrelated
negative-expectancy strategies does not manufacture out-of-sample edge, it only
smooths the in-sample curve. Two of five strategies go dormant in the OOS
window (vwap after 14 days, liquidity_sweep after 59), so the OOS book is
effectively the two losing 15m trend strats, unaided.

## §12. Funding-rate carry (new edge class)

A structurally different edge from the price-momentum/reversion family. Binance
public fapi gives 8h funding history (no key); price from cached Binance 15m.
`scripts/funding_carry.py` tests two carry variants on BTCUSDT/ETHUSDT over the
same 2.5yr multi-regime window, train 70% / OOS 30%.

**Directional carry** (hold the funding-receiving side, unhedged): OOS Sharpe
-1.66 (BTC) / -1.27 (ETH), maxDD -54% / -68%. The ~9%/yr gross funding is dwarfed
by adverse price drift — being short the receiving side during the 2024-25 bull
(+76% BTC OOS) is a directional bet that loses.

**Delta-neutral carry** (long perp + short spot so price cancels, keep funding
less flip fees — the real arbitrage):

| | gross funding | flip cost (taker) | flip cost (maker) | OOS Sharpe taker | OOS Sharpe maker |
|--|--|--|--|--|--|
| BTC (2.5yr) | 24.2% | 53.8% | 26.9% | -7.7 | -3.2 |
| ETH (2.5yr) | 24.2% | 53.8% | 26.9% | -9.8 | -5.3 |

The funding sign oscillates on small rates (336 flips over 2828 events, 12% of
intervals), and each flip = 4 fills. Even at maker (half taker), flip cost
(26.9% over the period) exceeds gross funding income (24.2%). **No carry edge
OOS — fees eat funding.** The ~9.7%/yr gross funding is real but is captured only
with institutional fee structures (maker rebates, OTC, capital efficiency, low-
flip thresholding) that retail perp trading does not have. Naive sign-flipping
delta-neutral carry is sub-fee; the gross income cannot survive dynamic hedging
at Binance/CoinDCX retail fees.

## Overall status (post §11-§12)

Both follow-up edge classes are negative: ensemble diversification has no OOS
benefit (§11, in-sample artifact), and funding carry is sub-fee at retail (§12).
The original 23-strategy price family has no OOS edge (§8-§10). Live capital
remains not warranted. Remaining untested directions: spot/DMB grid (positive-
carry structure, no liquidation/funding), microstructure/order-flow signals from
the WS trade stream, and external (on-chain/macro) regime priors.

## §13. External macro regime prior (DXY / US10Y)

Foundation test before gating: does DXY (DTWEXBGS, trade-weighted dollar) or
US10Y (DGS10, 10y treasury) predict BTC/ETH daily direction out-of-sample? FRED
free daily CSV; BTC/ETH daily from cached Binance 15m. `scripts/macro_signal.py`
→ `reports/macro_signal.json`. Signals: DXY 5d momentum (falling dollar → long),
DXY below 200d MA (risk-on), 10Y 5d change (falling rates → long), combined.
Train 70% / OOS 30%.

A robust predictor is positive in BOTH halves. A signal that is +OOS but -IS (or
vice versa) is regime luck — it aligned with this OOS regime by chance, not a
real edge.

| symbol | signal | IS Sharpe | OOS Sharpe | OOS net% | buyhold OOS sh |
|--------|--------|----------|-----------|---------|----------------|
| BTC | dxy_mom5 | 1.81 | -0.63 | -23.2 | 2.14 |
| BTC | dxy_below_ma200 | -1.74 | 0.61 | 10.1 | 2.14 |
| BTC | y10_mom5 | 1.83 | 0.47 | 6.0 | 2.14 |
| BTC | dxy+y10 | 2.25 | -0.11 | -6.1 | 2.14 |
| ETH | dxy_mom5 | 1.50 | 0.47 | 2.1 | 1.18 |
| ETH | dxy_below_ma200 | -0.99 | **3.04** | 224.6 | 1.18 |
| ETH | y10_mom5 | 1.67 | -1.13 | -50.9 | 1.18 |
| ETH | dxy+y10 | 1.89 | -0.44 | -22.4 | 1.18 |

**No robust macro edge OOS.** Every signal flips sign between halves (+IS / -OOS
or -IS / +OOS) — the signature of regime dependence, not prediction. The one
eye-catching result (ETH dxy_below_ma200, OOS Sharpe 3.04, +224%) is positive-OOS
but negative-IS (-0.99): it happened to be long ETH through the 2024-25 rally, not
a durable predictor. On BTC the same signal is -IS / weakly-+OOS. Macro signals
do not robustly predict BTC/ETH direction, so they cannot rescue the no-edge perp
strategies via gating.

## Overall status (post §11-§13)

Three follow-up edge classes tested, all negative:
- **Ensemble OOS** (§11): diversification has no OOS benefit — the §10 portfolio
  was an in-sample artifact (OOS Sharpe -3.8 to -5.0, worse than flat).
- **Funding carry** (§12): gross funding income 24%/2.5yr (9.7%/yr) is sub-fee at
  retail — hedge-flip cost (54% taker / 27% maker) exceeds it.
- **Macro regime prior** (§13): DXY / US10Y are not robust BTC/ETH predictors —
  every signal flips sign between train and OOS (regime luck, not edge).

The original 23-strategy price family (§8-§10), portfolio diversification (§11),
funding carry (§12), and macro gating (§13) all show no out-of-sample edge at
retail perp cost structure. Live capital is not warranted on the evidence.
Remaining untested: spot/grid DMB (positive-carry, no liquidation/funding) and
microstructure/order-flow from the live WS trade stream.

## §14. Spot grid bot (trailing, martingale-free)

A structurally different instrument/structure: spot (no leverage, no funding, no
liquidation), positive carry in ranges, bounded risk. `scripts/grid_bot.py` →
`reports/grid_bot.json`. Trailing grid: anchor ratchets UP with price (no buys on
uptrends); when price drops g% below anchor, buy 1 unit and ladder the anchor down
into the dip; each held buy sells when price recovers g% above its entry (round
trip +g - 2 fees). Inventory capped at K units (sustained downtrend bleed
bounded, not infinite). Backtested on cached Binance 15m, grid-search g and K on
train 70%, score OOS 30%.

Best train grid: g=2%, K=20 (train Sharpe 1.73).

| symbol | window | Sharpe | PF | CAGR | maxDD | end (10000 start) | buyhold |
|--------|--------|--------|----|------|-------|------------------|---------|
| BTC | full | 1.53 | 1.03 | 23% | -12% | 17215 | +600% |
| BTC | OOS | 1.08 | 1.03 | 26% | -17% | 11932 | +71% |
| ETH | full | 1.03 | 1.02 | 27% | -30% | 18364 | +210% |
| ETH | OOS | 0.83 | 1.01 | 31% | -45% | 12356 | +40% |

**Robustness — OOS Sharpe across the full parameter surface (not just the tuned
point):**

| symbol | g=0.5% | g=1% | g=2% | g=3% |
|--------|--------|------|------|------|
| BTC (K=10..40) | 0.98-1.31 | 1.21-1.38 | 1.08-1.44 | 1.11-1.13 |
| ETH (K=10..40) | 0.63-0.68 | 0.63-0.73 | 0.76-0.86 | 0.82-0.96 |

**Every one of 12 OOS param combos is positive on both symbols.** The whole grid
surface works — this is not tuned-point luck. Train + OOS both positive (no sign
flip, unlike every other edge class). **This is the first genuine positive-OOS
edge found in the entire research sprint.**

Honest caveats:
- **Underperforms buy&hold in a bull.** BTC grid +19% OOS vs buyhold +71%. The
  edge is risk-adjusted (Sharpe, bounded DD), not raw return. In a sustained
  uptrend, hold wins. The grid harvests chop and survives trends with bounded
  loss — it is a risk-managed spot strategy, not a bull-market maximizer.
- **ETH drawdown is large** (-30% to -50%): the grid ladders inventory into
  sustained downtrends; the K cap bounds the *inventory* but not the mark-to-
  market drawdown while underwater. Survivable (spot, no liquidation) but real.
- **Fee-robust**: round trip margin = g - 2·fee = 2% - 0.2% = 1.8% at 0.1% spot
  taker; even at CoinDCX ~0.2% spot it is 1.6%. Wide margin, not fee-sensitive
  like the perp carry (§12).
- **15m close-to-close sim** does not model intrabar fills. A real limit-order
  grid fills AT grid levels (maker, often favorable) and catches intrabar
  oscillations close-to-close misses — so the sim is conservative, if anything.
  Gaps skipping levels are the offsetting risk, roughly neutral on net.

**Deployable.** Unlike every prior class, the grid has a positive, robust OOS
Sharpe and bounded risk on spot. Candidate for paper deployment with the tuned
g=2% / K=20, sized so K units ≤ capital (no leverage).

## §15. Microstructure (WS trade stream) — built, feed-blocked

`scripts/microstructure.py` — tick-rule CVD proxy. CoinDCX exposes **no public
per-trade print feed** (REST or WS): only candles, ticker, and a price-change WS
channel. True CVD needs trade prints + size, which are unavailable. So the
collector uses the classic **Lee-Ready tick rule**: classify each price tick as
buy (uptick) or sell (downtick), repeat-last on no-change, accumulate Cumulative
Volume Delta over a rolling window. It is a *proxy* for order-flow imbalance
inferred from price alone — standard microstructure when trade-side data is
missing.

The pipeline is live-forward, NOT backtestable (no tick history). Validating its
edge would need weeks of recorded ticks + a separate forward test.

**Status: code built, feed currently unreachable.** At build time the CoinDCX WS
gateway (`wss://stream.coindcx.com`) returns HTTP 503 / handshake timeouts across
repeated attempts — an external/infrastructure issue, not a code defect (the
existing live engine uses the same endpoint). The collector is correct and ready
to run when the feed returns; it could not be validated live here. First run
should dump a raw `prices-futures` message to confirm the `parse_price` field
names against the actual payload.

## Overall status (post §14-§15)

- **Grid bot (§14): first positive-OOS edge.** Robust (all 12 OOS params positive,
  both symbols, train+OOS no sign flip), fee-robust, bounded risk on spot.
  Deployable to paper. Risk-adjusted edge, not a bull-market maximizer.
- **Microstructure (§15): built, feed-blocked.** Tick-rule CVD proxy; CoinDCX WS
  503 at build time. Ready when feed returns; needs forward (not back) validation.

The grid is the first evidence-based deployable strategy from this sprint. The
four prior edge classes (price strategies, ensemble, funding carry, macro)
remain negative-OOS. Next step for the grid: paper deployment + forward
validation against live fill quality; for microstructure: re-run when the WS
feed is available and record ticks for a forward edge test.

## §16. Grid hardening (pre-paper)

`scripts/grid_harden.py` → `reports/grid_harden.json`. Three risk controls tested
before paper deployment; the grid's `grid_backtest` was refactored into a stateful
`GridBot` class shared by backtest AND live (the faithful-engine lesson: backtest
must mirror live exactly, no divergence).

**Rolling walk-forward re-tune** (tune g,K on expanding train, score next OOS
window, 4 folds):

| symbol | static OOS Sharpe | rolling mean OOS Sharpe |
|--------|-------------------|------------------------|
| BTC | 1.11 | **1.60** |
| ETH | 0.83 | **1.15** |

Periodic re-tuning IMPROVES OOS Sharpe (BTC +44%, ETH +39%). Live: re-tune g,K on
a rolling recent-history window periodically.

**Inventory-stop sweep** (flatten all open buys on a max-DD breach, stay flat
until new peak):

| symbol | stop=none | stop=0.15 | stop=0.20 | stop=0.25 |
|--------|-----------|-----------|-----------|-----------|
| BTC OOS sh | 1.11 | -0.35 | 1.11 | 1.11 |
| ETH OOS sh | 0.83 | 0.11 | -0.36 | -0.43 |

The stop HURTS. It flattens exactly when the grid should be holding inventory for
the bounce — and the bounce-harvest IS the edge. Stopping cuts the edge and locks
losses. The bounded K inventory IS the risk control; an additional drawdown stop
is counterproductive on a mean-reverting grid. Do NOT add a stop.

**Multi-symbol portfolio** (BTC + ETH grids, inverse-vol weights from train
daily-return std, OOS):

| | BTC | ETH | portfolio |
|--|------|------|-----------|
| OOS Sharpe | 1.11 | 0.83 | 1.05 |
| OOS maxDD | -19% | -45% | -30% |
| weights | — | — | BTC 0.6 / ETH 0.4 |
| BTC-ETH daily corr | — | — | 0.67 |

The portfolio does NOT beat BTC alone (Sharpe 1.05 ≈ 1.11, dd -30% WORSE than
BTC's -19%). Correlation is high (0.67) so ETH adds little diversification and
imports its larger drawdown. Single-symbol BTC grid is as good or better.

**Hardened config: single BTC grid, g=2%/K=20 (or rolling-re-tuned), NO stop.**
The extra controls don't help — the bounded trailing grid is already the right
structure. Simpler than expected (ponytail validated: the controls were the
slop). Deploy g=2% K=20 with periodic rolling re-tune; size K units ≤ capital, no
leverage.

## §17. Live paper grid runner + microstructure status

**Live grid runner** (`scripts/grid_live.py`): streams CoinDCX price ticks (WS)
and steps the SAME `GridBot` the backtest uses — forward validation of whether
tick-by-tick live equity matches the 15m-close sim. Paper by construction
(`GridBot` simulates fills, places no real orders; real paper orders would wrap
`GridBot.step`'s fills in the REST order client later).

WS is primary; the CoinDCX WS gateway returns HTTP 503 / handshake timeouts at
build time, so the runner falls back to polling the latest 1m candle every 60s
(coarser but live-forward). Verified: WS 503 → candle-poll fallback ran 2 cycles
correctly (anchor set, ratcheted up on an uptick, no fills in a 75s rising window
as expected — buys trigger on a 2% dip). Full forward validation (fills, equity
drift vs sim) needs a multi-hour/multi-day run, ideally on the WS tick stream for
fill-timing fidelity.

**Microstructure** (`scripts/microstructure.py`, built in the prior branch):
tick-rule CVD proxy. CoinDCX WS still 503 on retry — no change, still feed-
blocked. Collector ready when the feed returns; first run should dump a raw
`prices-futures` message to confirm `parse_price` field names.

## Overall status (post §16-§17)

Grid bot is the sprint's first and only positive-OOS edge, now hardened:
rolling re-tune improves it (+44% BTC OOS Sharpe), inventory-stop and multi-
symbol portfolio do NOT help (keep it simple, single BTC grid, no stop). A live
paper runner is built and verified via candle-poll fallback; full forward
validation pending a longer run + WS availability. Microstructure remains feed-
blocked. Recommended next step: run `scripts/grid_live.py` for ≥24h on the WS
stream (when back) to validate live equity vs the 15m sim before any live capital.

## §18. Real perp cost model + cost/short-engine fixes + regime-balanced walk-forward (research closed)

> **Supersedes §14-17.** The §14 grid "first positive-OOS edge" was modeled at
> `FEE=0.001` with **no 1% TDS**. Under the real CoinDCX spot cost model (0.169%
> taker + GST + **1% TDS per sell**, ~1.4% round trip) the grid edge is refuted on
> BTC and ETH (see `reports/grid_bot.json` `deployable: false` and the
> `grid-edge-refuted-under-real-costs` memory). The grid infra (stateful
> `GridBot`, live runner, hardening) is kept as reusable scaffolding; the
> strategy itself is not deployable.

### 18.1 Real perp cost model — TDS does NOT apply (verified)

CoinDCX INR-margin perp futures carry **no 1% TDS** (verified via CoinDCX support
2026-08-07: Section 194S covers "transfer" of a VDA; cash-settled futures are
not a transfer; INR-margin futures have no per-trade TDS at all, taxed as
speculative business income). So the `BacktestConfig` cost model (maker/taker fee
+ `slippage_bps` + `funding_rate`, no TDS) is **correct** for perp backtests.
Sources linked in the `coindcx-spot-cost-model` memory. Do not add TDS to perp
backtests; the 1% TDS drag is spot-only.

### 18.2 Backtest engine fixes (this session, prior merge PR #7)

- **Fee/funding double-count → single-count.** Entry fee AND funding were
  subtracted from cash as-you-go AND again in the exit pnl → every backtest
  over-paid fees. Now realized once at close. Lifted 4h ema_cross gated OOS sh
  0.01 → 0.09.
- **Daily-loss day reset bug.** `RiskManager.update_equity` reset the day via
  wall-clock `datetime.now()` instead of the bar timestamp → in a multi-year
  backtest the daily-loss limit tripped once and blocked every entry forever.
  Now takes an optional `ts` (bar timestamp); engine + faithful pass it.
- **Regime gate.** `BacktestConfig.regime_sma` blocks new longs while
  `close < SMA(N)`; open positions still exit via trailing (don't force exits).
  Symmetric when `allow_short`: longs above SMA(N), shorts below.
- **Short side wired.** `BacktestConfig.allow_short` + sig `-1` opens a short
  when flat; direction-aware `_manage` / liquidation / funding / EOD. supertrend
  fixed to emit a **persistent-direction** signal (+1 uptrend / -1 downtrend) so
  the engine re-arms entry after a trailing stop-out. 13 tests pass.
- **Dynamic signed funding hook (NEW this session).** `BacktestConfig.funding_rates`
  (a `pd.Series` of signed per-8h rates, index=8h mark UTC). If given, the engine
  asof-looks-up the rate at each 8h funding event (most recent ≤ bar ts) instead
  of the flat `funding_rate` — models real dynamic/signed funding (negative in
  bears: longs receive, shorts pay). `None` falls back to the flat rate (all
  existing tests / strategies unchanged).

Engine exit contract (unchanged, easy to confuse): `engine.py` exits via ATR
trailing (trend) or fixed-stop + `strategy.take_profit` (reversion), **NOT on
signal 0**. Signal-0 exit lives in `faithful.py` + the live engine. Always use
`cfg_for(kind)` from `scripts/rank.py`, not the default `BacktestConfig` (which
gives a degenerate 1-trade trend result).

### 18.3 Daily (1d) trend — no edge, bear beta

`scripts/daily_trend.py` (15m→1d resample, 1308 bars 2023-01→2026-07, 70/30
split 2025-07-04, trend cfg + `regime_sma=200`, real perp costs, long-only AND
long/short, full + OOS + 4-fold walk-forward):

- Long-only + gate: **0 OOS trades** — gate blocks every long in the downtrend
  (no bleed), but sharpe 0 = "don't lose", not edge.
- supertrend long/short OOS sh +0.77 (7 trades) LOOKED positive. Walk-forward
  refutes: fold-2 (+78% uptrend) blows up **-686** (sh -3.10), agg OOS net -354.
  Pure bear beta — shorts profit only in the one downtrend fold, annihilated in
  strong uptrends.
- ema_cross long/short OOS sh +1.27 but **2 trades** (statistically void).
- Daily IS structurally cleaner than 4h (less churn) but the short side trades
  bull returns for downtrend protection and nets negative across regimes.

### 18.4 Non-laggy breakout/momentum + mean-reversion on 4h — no edge, bull beta

`scripts/breakout_4h.py` (15m→4h, 7848 bars, train-tuned params, gated +
ungated, full + OOS):

- Breakout/momentum (donchian, ichimoku, obv_divergence, adx_trend) = full-
  positive / OOS-negative = **bull beta**, same trap as laggy crossover.
  ichimoku cleanest: full +1240 / OOS -883.
- **adx_trend bleeds least OOS (sh -0.24 ungated)** vs laggy ema_cross (-0.69):
  the **ADX>threshold chop filter reduces whipsaw** — the one structural idea
  that works, but not enough to flip OOS positive.
- **The `regime_sma=200` gate does NOT keep longs flat on 4h.** The choppy
  downtrend crosses SMA200 on rallies → 21-30 OOS trades still fire and bleed.
  Only on daily did the gate yield 0 OOS trades. **Gate value is TF-dependent**
  and on 4h it often made OOS *worse* (adx -0.24 ungated → -0.97 gated; cci -2.43
  → -4.29). Use the gate on daily, not 4h.
- Mean-reversion (keltner, stochrsi, cci) is WORSE than trend: OOS is a
  downtrend-with-rallies, not a range → buying dips = catching knives (keltner
  OOS sh -3.06, cci OOS sh -4.29). "Buy dips profit in chop" refuted for this OOS.

### 18.5 Dynamic signed funding — no verdict moves

`scripts/pull_funding.py` pulls real Binance fundingRate history (3924 8h marks,
2023-01→2026-07, signed; cached `reports/binance_BTCUSDT_funding.csv`).
`scripts/real_funding.py` re-tests the marginal candidates fixed vs real funding:

- Real funding is **LOWER** than the fixed +0.0001: full mean +0.000066, OOS
  mean +0.000034, only **22% negative** in OOS — the "downtrend" was a grind, not
  a crash; funding stayed positive. The negative-funding-rebates-longs hypothesis
  was wrong; longs just pay *less*.
- Long-only gated nudges up: ema_cross 4h + SMA200 gate OOS sh **0.09 → 0.13**
  (net +25 → +39, pf 1.07 → 1.11). All-time best improves marginally — still
  breakeven, **not deployable**.
- Long/short ≈ unchanged (longs pay less, shorts receive less → cancels).

### 18.6 Regime-balanced walk-forward — the fairest test, NOTHING survives

`scripts/regime_wf.py`: K=4 contiguous time-folds, FIXED params (no per-fold
tuning — stringent "one config generalizes across every regime" test), real
funding, each fold scored as OOS. Folds: f1 up +126%, f2 up +80%, f3 up +66%,
**f4 dn -43%** (data bull-heavy: the only major downtrend is 2025-26). Rubric:
robust = positive net in >half folds AND across BOTH regime types.

| candidate | f1 up | f2 up | f3 up | f4 dn | agg | pos | verdict |
|---|---|---|---|---|---|---|---|
| **ema_cross 4h L gated** | +434 | +129 | +84 | **-282** | +365 | 3/4 | **bull-beta** |
| supertrend 4h L gated | -16 | -45 | -147 | -116 | -324 | 0/4 | lose-all |
| adx_trend 4h L gated | -55 | -115 | -342 | -458 | -970 | 0/4 | lose-all |
| adx_trend 4h L ungated | +429 | -446 | -361 | -331 | -708 | 1/4 | bull-beta |
| ema_cross 1d L gated | 0 | -45 | 0 | 0 | -45 | 0/4 | inactive |
| supertrend 1d L gated | 0 | -117 | +57 | 0 | -60 | 1/4 | inactive |
| supertrend 4h L/S ungated | +193 | **-804** | -99 | +369 | -340 | 2/4 | bear-beta |
| supertrend 1d L/S | +298 | -27 | -250 | -64 | -43 | 1/4 | lose |
| ema_cross 4h L/S | +73 | -694 | +979 | **-742** | -384 | 2/4 | whipsaw |

**Zero strategies are robust.** The all-time best (ema_cross 4h + SMA200 gate) is
**pure bull-beta**: +434/+129/+84 in the three up folds, **-282 in the downtrend
fold** — exactly what the fixed 70/30 split hid (it scored only the downtrend,
averaging the loss against the bull train = "breakeven"). The gate **lags**: fold4
starts 2025-04 (price still near SMA200) so it admits longs in the *early*
downtrend → they stop out → -282; it only blocks in the *late* downtrend. No
downtrend protection. Long/short blows up in strong uptrends (-804 in f2 +80%).
No config nets positive across both bull and bear regimes.

### 18.7 Overall verdict — research closed

**No deployable edge on BTC 5m→1d under real perp costs.** Exhausted across:
spot grid, long/short grid, ensemble, funding carry, macro prior, supertrend,
ema_cross, rsi_reversal, daily trend, breakout/momentum, mean-reversion,
dynamic funding, and regime-balanced walk-forward — TFs 5m→1d, gated/ungated,
long/long-short, fixed/real funding.

The structural conclusion: long-only rides the bull and bleeds in the bear;
long/short bleeds in the bull and profits in the bear; neither nets positive
across both. Every apparent edge is regime beta that the fixed 70/30 split
(landing OOS entirely in the 2025-26 downtrend) could not expose — the regime-
balanced walk-forward does, and nothing survives it. The all-time best remains
**ema_cross 4h + SMA200 gate, long-only, real funding = OOS sh 0.13 = breakeven**,
not deployable.

**Delivered this session (kept):** real perp cost model + TDS verification;
`BacktestConfig.funding_rates` dynamic-funding hook; `scripts/daily_trend.py`,
`scripts/breakout_4h.py`, `scripts/pull_funding.py`, `scripts/real_funding.py`,
`scripts/regime_wf.py`; real funding cache
`reports/binance_BTCUSDT_funding.csv`; 13 tests pass.

**Remaining lower-EV directions:** (1) a different asset perp trend + regime
walk-forward (ETH grid already refuted under TDS; the edge is regime-structural,
likely asset-agnostic); (2) ensemble/risk-parity of the breakeven signals (no edge
to combine — §11 already showed diversification is an in-sample artifact); (3)
a new edge source entirely (on-chain, cross-exchange basis, or order-flow /
microstructure once the CoinDCX WS feed is available, §15).

## §19. Multi-asset perp regime walk-forward (BTC / ETH / SOL) — one ETH outlier, not generalizable

> Step 1 of the post-close plan: a different asset's regime sequence is the
> cheapest falsifier of "it's just BTC's regime luck." Generalized
> `scripts/regime_wf.py` to loop BTC/ETH/SOL (same 9 candidates, same FIXED
> params — no per-fold/per-asset tuning, the stringent "one config generalizes
> across every asset and regime" test). Pulled ETH/SOL 15m + funding from
> Binance Vision (125568 bars each, 2023-01→2026-07; 3924 8h funding marks
> each; ETH mean funding +0.000068, SOL +0.000035). Real per-8h signed funding,
> lev 3, maker_on_limit, no TDS. K=4 contiguous folds, fixed dates per asset:

| fold | window | BTC bh | ETH bh | SOL bh |
|---|---|---|---|---|
| f1 | 2023-01→2023-11 | +125% | +72% | **+467%** |
| f2 | 2023-11→2024-10 | +78% | +25% | +172% |
| f3 | 2024-10→2025-09 | +64% | +65% | +34% |
| f4 | 2025-09→2026-07 | **-44%** | **-57%** | **-66%** |

Full-window buy&hold: BTC +281%, ETH +56%, SOL +633%.

### 19.1 Summary verdict (27 asset×strategy cells)

| asset | strategy | agg | pos/4 | up | dn | verdict |
|---|---|---:|---|---|---|---|
| BTC | ema_cross 4h L gated | +365 | 3 | 3 | 0 | bull-beta |
| BTC | supertrend 4h L gated | -324 | 0 | 0 | 0 | lose |
| BTC | adx_trend 4h L gated | -970 | 0 | 0 | 0 | lose |
| BTC | adx_trend 4h L ungated | -708 | 1 | 1 | 0 | bull-beta |
| BTC | ema_cross 1d L gated | -45 | 0 | 0 | 0 | lose |
| BTC | supertrend 1d L gated | -60 | 1 | 1 | 0 | bull-beta |
| BTC | supertrend 4h L/S ungated | -340 | 2 | 1 | 1 | whipsaw |
| BTC | supertrend 1d L/S | -43 | 1 | 1 | 0 | lose |
| BTC | ema_cross 4h L/S | -384 | 2 | 2 | 0 | bull-beta |
| ETH | ema_cross 4h L gated | -190 | 2 | 2 | 0 | bull-beta |
| ETH | supertrend 4h L gated | -1069 | 1 | 1 | 0 | lose |
| ETH | adx_trend 4h L gated | -151 | 1 | 1 | 0 | bull-beta |
| ETH | adx_trend 4h L ungated | +573 | 3 | 3 | 0 | bull-beta |
| ETH | ema_cross 1d L gated | +96 | 1 | 1 | 0 | inactive |
| ETH | supertrend 1d L gated | +121 | 1 | 1 | 0 | bull-beta |
| ETH | supertrend 4h L/S ungated | -1038 | 1 | 0 | 1 | bear-beta |
| **ETH** | **supertrend 1d L/S** | **+1058** | **4** | **3** | **1** | **ROBUST** |
| ETH | ema_cross 4h L/S | -1550 | 1 | 1 | 0 | lose |
| SOL | ema_cross 4h L gated | -97 | 2 | 1 | 1 | bull-beta |
| SOL | supertrend 4h L gated | -335 | 0 | 0 | 0 | lose |
| SOL | adx_trend 4h L gated | -1425 | 1 | 1 | 0 | lose |
| SOL | adx_trend 4h L ungated | -288 | 1 | 1 | 0 | bull-beta |
| SOL | ema_cross 1d L gated | -14 | 1 | 1 | 0 | bull-beta |
| SOL | supertrend 1d L gated | -128 | 1 | 1 | 0 | bull-beta |
| SOL | supertrend 4h L/S ungated | +790 | 2 | 2 | 0 | bull-beta |
| SOL | supertrend 1d L/S | -125 | 2 | 1 | 1 | bull-beta |
| SOL | ema_cross 4h L/S | -178 | 2 | 1 | 1 | bull-beta |

**Exactly one ROBUST flag in 27 cells: ETH supertrend 1d L/S.** It is positive in
all 4 folds including the -57% downtrend fold, with 13-19 trades/fold (not a
2-trade void result), sh 0.58-0.99.

### 19.2 The ETH outlier — per-fold vs buy&hold

ETH supertrend 1d L/S (period=10, mult=3, daily, long/short, lev 3, real funding):

| fold | window | bh% | lev3 B&H | strat net | trades | sh | maxdd | pf |
|---|---|---:|---:|---:|---|---:|---:|---:|
| f1 | 2023-01→2023-11 | +72 | +216 | **+261** | 19 | 0.76 | 0.028 | 1.56 |
| f2 | 2023-11→2024-10 | +25 | +75 | **+282** | 13 | 0.91 | 0.020 | 2.06 |
| f3 | 2024-10→2025-09 | +65 | +195 | **+364** | 16 | 0.99 | 0.018 | 1.88 |
| f4 | 2025-09→2026-07 | -57 | -171 | **+152** | 15 | 0.58 | 0.012 | 1.39 |
| | | | **agg** | **+1058** | 63 | | | |

It beats levered buy&hold in all 4 folds AND profits where B&H loses -171%
(f4). On its own ETH folds this passes the "positive across both regimes" bar.

### 19.3 Cross-asset replication — the falsifier

The IDENTICAL fixed params (supertrend 1d L/S, period=10, mult=3, lev 3) on the
other two assets:

| asset | f1 up | f2 up | f3 up | f4 dn | agg | verdict |
|---|---:|---:|---:|---:|---:|---|
| BTC | +298 | -27 | -250 | -64 | **-43** | lose |
| ETH | +261 | +282 | +364 | +152 | **+1058** | robust |
| SOL | +95 | -16 | **-379** | +174 | **-125** | lose |

BTC bleeds in f3 (choppy +64% grind, whipsaw) and f4; SOL blows up in f3 (-379,
sh -1.27 — SOL's choppy +34% fold shreds the daily supertrend). **The ETH result
does not replicate.** It is ETH-path-specific, not an asset-agnostic edge.

### 19.4 Mechanism — why ETH and not BTC/SOL

Full-window buy&hold separates the regimes: BTC +281%, ETH **+56%**, SOL +633%.
ETH had the **lowest net drift but large two-way swings** (up to ~4000 in Mar-2024,
back to ~2400, up again, down into f4). A long/short daily supertrend profits
when price has big swings with modest net drift — longs catch the up legs, shorts
catch the corrections, and neither side dominates. BTC (+281%) and SOL (+633%)
were strong one-way bulls: the short side of the same L/S trend gets repeatedly
stopped out in a bull and bleeds (BTC supertrend 4h L/S f2 -804; SOL f2 -327). So
"ETH robust" is not "ETH trends cleaner" — it is "ETH's 2023-26 path had the most
two-sided range per unit of net drift," exactly the path a L/S trend exploits and
exactly what a one-way bull punishes. This is regime-path luck, not alpha.
Deploying ETH supertrend 1d L/S = betting ETH keeps swinging two-way with low net
drift, which is not established (a one-way ETH bull like 2020-21 would bleed it
exactly as SOL's f1/f2 bull bleeds SOL).

### 19.5 Verdict

**No asset-agnostic robust edge.** The only ROBUST flag across 27 cells (ETH
supertrend 1d L/S, +1058, 4/4 folds) is a single-asset, single-path artifact: it
fails the cross-asset replication test (BTC -43, SOL -125 with identical fixed
params) and its mechanism (profits on two-way-swing/low-drift paths, bleeds on
one-way bulls) confirms it is ETH-regime-path-specific, not a generalizable edge.
Step 1's hypothesis ("the edge is regime-structural and likely asset-agnostic")
is **falsified**: pivoting asset did not produce a universal edge, and the one
asset that looked robust does so for a path-specific reason the other two refute.

Delivered: `scripts/regime_wf.py` generalized to multi-symbol (BTC/ETH/SOL);
`reports/binance_ETHUSDT_15m.csv`, `reports/binance_SOLUSDT_15m.csv`,
`reports/binance_ETHUSDT_funding.csv`, `reports/binance_SOLUSDT_funding.csv`;
`reports/regime_wf_multi.log`. ETH supertrend 1d L/S kept as a watchlist
single-asset candidate (not deployed; bar = cross-asset replication, which it
fails). Next plan steps: (2) cross-exchange basis / funding carry with real
dynamic funding + band-gated re-hedge; (3) order-flow / microstructure if the
CoinDCX WS feed is back up; (4) external regime prior walk-forwarded.

## §20. Band-gated funding carry with real dynamic funding (step 2) — first net-positive-after-costs result, but funding-regime-dependent

> Step 2: re-test delta-neutral funding carry with the REAL `funding_rates`
> history (now on disk for BTC/ETH/SOL) and a **band-gated re-hedge** (only
> re-hedge when funding crosses a band, not every sign change) to cut flip cost.
> §12 refuted NAIVE sign-flip carry: 336 flips/2828 events, flip cost 26.9%
> (maker) > gross funding 24.2%. The noise-driven flips earned ~0 funding but
> paid full fees. `scripts/funding_carry_band.py`.

### 20.1 Band-gated re-hedge fixes the flip-cost problem

Deadband hysteresis: be SHORT (perp) when rate > +b, LONG when rate < −b, HOLD
current side while −b ≤ rate ≤ b. Skips near-zero flips; pays small adverse
funding in the deadband instead of 4 fills to flip. Swept b, real signed
funding, lev 1, maker fee 0.0002/fill (4 fills/flip), 70/30 split:

| asset | band | flips(full/OOS) | net full | net OOS | sh OOS |
|---|---|---|---:|---:|---:|
| BTC | 0 (naive §12) | 541/205 | -13.0% | -10.0% | -9.39 |
| BTC | 0.0002 | **1/1** | +29.7% | +4.0% | 23.79 |
| ETH | 0 (naive) | 569/255 | -13.7% | -13.6% | -12.01 |
| ETH | 0.0005 | 2/2 | +30.6% | +3.1% | 16.03 |
| SOL | 0 (naive) | 878/339 | -24.1% | -16.6% | -12.73 |
| SOL | 0.0002 | 11/2 | +30.6% | +3.5% | 6.86 |

The band cuts flips from hundreds to single digits → flip cost collapses below
gross funding. Naive is deeply sub-fee; banded nets positive. **But** 1 flip on
BTC = "hold short the whole window, collect net-positive funding" = a
funding-DIRECTION bet (this works only because funding was net-positive 2023-26).

### 20.2 CoinDCX-executability: the spot-short problem + TDS on the hedge leg

Delta-neutral carry = (perp leg) + (spot hedge). Two sides:
- **Positive funding** (rate>0): short perp (receive) + **long spot** →
  executable on CoinDCX (short perp available, long spot available).
- **Negative funding** (rate<0): long perp (receive) + **short spot** →
  **NOT executable** — CoinDCX spot has no shorting.

So the theoretical two-sided band carry (harvests both signs) is NOT realizable;
only the **one-sided** harvest (positive funding only, FLATTEN when funding
negative) is. Plus the spot hedge leg: each **flatten = SELL spot = 1% TDS**
(the dominant cost, far bigger than the 0.08% perp flip fee — this is what truly
killed naive: 336 flattens × 1% TDS = catastrophic). The band's value on CoinDCX
is doubly large: it kills flips AND TDS-bearing spot sells.

### 20.3 Executable one-sided carry, WITH 1% TDS on spot sells, K=4 walk-forward

Train-selected band (no OOS peeking). Real funding, lev 1, maker perp fee + 1%
TDS per flatten. `reports/funding_carry_band.log`:

| asset | band | f1 up | f2 up | f3 up | f4 dn | full | ~%/yr | flattens |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| BTC | 0.0002 | +5.8 | +10.9 | +5.9 | 0.0 | +29.4% | 7.5 | 0 |
| ETH | 0.0003 | +6.0 | +11.9 | +6.0 | 0.0 | +28.2% | 7.2 | 1 |
| SOL | 0.0002 | +0.3 | +13.8 | +1.5 | 0.0 | +16.0% | 4.2 | 5 |

Positive in **3/4 folds** (the three up folds), **FLAT (0, no bleed) in the
downtrend fold4**. Never negative in any fold. BTC never flattened at all
(funding min −0.00015, never below the −0.0002 band → held short perp + long
spot the whole 2.5yr → 0 TDS). SOL bore one −0.927% funding spike (min rate
−0.00927) and still netted +16%.

### 20.4 Verdict — net-positive but NOT a robust edge

This is the **first net-positive-after-all-real-costs result** in the research:
~7%/yr on BTC/ETH, ~4%/yr on SOL, after perp fees AND 1% TDS on hedge rebalances.
It does not bleed in any fold (worst = 0, flat in the downtrend). Distinct from
every prior strategy that bled in the downtrend.

**But it is NOT a robust regime-agnostic edge** (the project bar):
1. **Funding-regime-dependent.** It profits in **positive-funding** regimes
   (bulls, where longs pay to hold) and goes flat in negative-funding regimes.
   Fold4 (dn) = 0, not positive → fails "profit across BOTH regime types."
   The ~7%/yr is **bull-funding-regime income**, structurally analogous to the
   bull-beta price trap: it harvests the carry leveraged longs pay in a bull,
   and sits out bears. It is "be the funding counterparty in a bull," not alpha.
2. **Band-overfit + small-funding miss.** Fold4 funding was small-positive
   (mean +0.000034) but below the band → missed entirely (flat). A narrower
   band captures it but the extra flips/TDS cost more than the income. The
   train-selected wide band is fit to the big-funding folds 1-3.
3. **Unmodeled tail risk (the real reason not to deploy yet):**
   - **Basis / short-squeeze.** Delta-neutral assumes perp ≈ spot. In a short
     squeeze (funding>0 bull → longs bid perp to a premium), the short-perp leg
     loses notional faster than the spot leg hedges → margin call / liquidation
     on the perp alone before the spot leg can cover. The perp basis can blow
     out 1-5% in a day in violent moves — one basis spike exceeds a year's
     funding income. §12's "<0.1% basis" is the calm-time figure, not the
     tail. NOT modeled here.
   - **Venue funding ≠ Binance.** We used Binance funding as a proxy; CoinDCX
     INR-margin perp funding schedule/rate differs and must be verified from
     CoinDCX's own marks before any deployment.
   - **Capital efficiency.** Lev-1 perp margin + full spot notional ≈ 2×
     capital → ~7%/yr on perp notional ≈ ~3.5%/yr on total capital at lev 1;
     leverage scales the perp side but the spot leg stays unlevered and the
     short-squeeze margin requirement caps practical leverage low.

**Status:** kept as a **watchlist candidate**, the closest thing to an edge
found, but NOT deployed. Bar to deploy: (a) model basis/short-squeeze tail risk
on real perp-spot basis data (the dominant unmodeled risk); (b) verify CoinDCX's
actual funding (not Binance proxy); (c) confirm it survives a sustained
negative-funding regime not just by going flat (opportunity cost) — i.e. is
~7%/yr in bull-funding regimes worth the tail risk? Per step-2 instruction
("if still sub-fee, document and stop") — it is NO LONGER sub-fee (the band
fixed that), so it is documented as a live candidate rather than closed.

Delivered: `scripts/funding_carry_band.py`; `reports/funding_carry_band.log`;
reused `scripts/funding_carry.py` (align/load_price/metrics). Next: step 3
(order-flow / microstructure if CoinDCX WS feed is back up) and step 4
(external regime prior walk-forwarded).

## §21. Microstructure feed unblocked (step 3) — was a code bug, not infra; real-side CVD now possible

> §15 marked the CoinDCX WS feed "503 / handshake timeouts" and left the
> microstructure collector (Lee-Ready tick-rule CVD PROXY) feed-blocked. Step 3:
> retry the feed; if up, record ticks ≥1 week, then forward-test CVD.

### 21.1 The 503 was a CODE BUG, not infrastructure

The host is UP (`https://stream.coindcx.com` returns 200 "Welcome to Coindcx
Streams!"). CoinDCX streams are **Socket.IO v2.4.0 (Engine.IO v3)**, not raw
WebSocket. §15's `microstructure.py` did a raw `websockets.connect(ws_url)` to
the bare host — a Socket.IO server returns **HTTP 503** for a request that is
not an Engine.IO handshake on the `/socket.io/?EIO=3&transport=websocket` path.
The "infra issue" was connecting to the wrong path with the wrong protocol.

Fix (hand-rolled EIO=3 over the already-installed `websockets` lib — no new dep):
connect to `/socket.io/?EIO=3&transport=websocket`, recv the `0{sid,...}` Engine.IO
open, recv the server's SPONTANEOUS `40` (Socket.IO connect — do NOT send our own
`40`; a duplicate connect makes the server drop us on join), emit
`42["join",{"channelName":"B-BTC_USDT"}]`, then handle server pings (`2`→`3`) and
client keepalive (`2` every ~20s). Confirmed live: a probe streamed real frames.

### 21.2 REAL trade-side CVD (not the §15 proxy)

The `B-BTC_USDT` channel emits `new-trade` events with the FULL Binance-style
trade print — confirmed from a live probe:

    42["new-trade",{"event":"new-trade","data":"{\"T\":1786131422620,
        \"p\":\"65009.88000000\",\"q\":\"0.00011000\",\"s\":\"BTCUSDT\",
        \"m\":false,\"channel\":\"B-BTC_USDT\",\"type\":\"new-trade\"}"}]

`m` (isBuyerMaker) gives the TRUE aggressor side: `m=false` → buyer is taker →
BUY; `m=true` → seller is taker → SELL. So CVD = Σ(+q buy, −q sell) from real
order flow — **not** the §15 Lee-Ready price proxy (which inferred side from
upticks/downticks because trade-side data was believed unavailable). This is the
materially better signal source §15 wanted: real trade prints + size + side, plus
`depth-update`/`depth-snapshot` orderbook if needed later.

### 21.3 Recorder built; proven; currently IP-throttled from probing

`scripts/microstructure.py` rewritten as the recorder: EIO=3 handshake, real-side
CVD, appends every trade (ts_ms, price, qty, side, symbol) to
`reports/ticks_B_BTC_USDT.csv` (gitignored), prints rolling CVD/imbalance, and
**reconnects on drop** (the server drops connections intermittently — clean 1005,
~per-IP limits/restarts; a multi-day recorder must rejoin and continue). Run with
no `RUN_S` arg = record until Ctrl-C.

A live probe captured real trades and confirmed the parse. A longer in-session
sample could NOT be captured: after ~20 diagnostic connections the server began
**consistently closing** each connection at the first data-recv (the join itself
succeeds) — an IP rate-limit / throttle from the probing burst, not a code defect
(the protocol is proven). Recording must be run later, not during a probe burst.

**Status: feed UNBLOCKED, recorder correct + proven, real-side CVD available.**
Next action (cannot finish in-session): run
`python scripts/microstructure.py B-BTC_USDT` for **≥1 week** (no RUN_S, leaves it
recording; the reconnect loop handles drops) to accumulate a tick sample, then
forward-test CVD as a short-horizon directional signal. This is the one remaining
edge class with a structurally different information source (order flow, not
price-derived indicators) and it is now actually testable. A `@prices-futures`
(perp mark) or futures-instrument channel can be added to record the PERP feed if
the spot `B-BTC_USDT` trades prove to be spot rather than perp (the prints carry
`"s":"BTCUSDT"` with no mark/funding field, suggesting spot; verify the exact
instrument code against the Markets Details API when recording the perp).

## §22. External regime prior, walk-forwarded (step 4) — VIX best, still regime-contaminated

> §13 tested DXY / US10Y with a 70/30 split; every signal FLIPPED SIGN between
> train and OOS = regime luck. Step 4: a different external series AND the
> regime-balanced K=4 walk-forward (the fix §13 called for). `scripts/macro_wf.py`.

Tested EQUITY risk-appetite priors §13 did NOT try: VIX (VIXCLS) and S&P500
(SP500) from FRED — free, daily, genuinely external to crypto, 2023-01→2026-07
(890 daily rows). Reused `fred()`/`metrics()` from `scripts/macro_signal.py`.
K=4 contiguous folds, fixed signal rules, each fold scored, tagged by BTC
buy&hold regime. Robust = positive net in >half folds AND across both regimes.

| signal | f1 up | f2 up | f3 up | f4 dn | agg | pos | verdict |
|---|---:|---:|---:|---:|---:|---|---|
| vix_below_ma50 | -53.6 | +6.9 | +3.2 | +5.1 | -38.3 | 3/4 | "robust"-count but NEG agg |
| vix_mom5 | -45.9 | +0.5 | +22.3 | +30.5 | +7.4 | 3/4 | "robust"-count, flat agg |
| vix_inv_level | -2.0 | +92.3 | +10.9 | -28.4 | +72.8 | 2/4 | bull-beta |
| sp_mom5 | -28.4 | +39.6 | -29.5 | -19.7 | -38.1 | 1/4 | lose |
| sp_mom20 | -33.7 | +137.8 | +28.9 | -58.0 | +75.1 | 2/4 | bull-beta |
| dxy_mom5 (§13) | +22.5 | +176.1 | -28.3 | -24.2 | +146.1 | 2/4 | bull-beta |

**VIX is the most informative external prior found** — the one thing DXY/US10Y
lacked: it profits in the **downtrend fold** via rising volatility (vix_mom5 f4
+30.5, sh 1.09; vix_below_ma50 f4 +5.1) — going short as vol spikes in the bear.
That is genuine, walk-forwarded downtrend protection the dollar/rate priors never
showed. **But it is contaminated by trad-fi vol events**: fold1 (2023 BTC +122%
bull) bled −45.9/−53.6 because VIX SPIKED in 2023 from the SVB / banking crisis
(a trad-fi event, not a crypto bear) → the VIX signal shorted into the crypto
bull. So VIX's crypto-regime signal is confused by equity-vol shocks that did not
correspond to crypto regimes. Net aggregate is flat-to-negative (vix_mom5 +7.4 ≈
~2%/yr with a −45.9% fold drawdown; vix_below_ma50 −38.3).

The crude pos-count rubric flags vix_mom5/vix_below_ma50 "ROBUST" (3/4 folds, dn
fold positive), but the **aggregate is flat/negative and the fold1 drawdown is
~50%** — that is not an edge; the pos-count rubric is too lenient (a strategy
+0.5/+0.5/+0.5/−45 is "3/4 positive" but garbage). SP500 momentum is bull-beta
(profits in bull folds, −58 in the dn fold). DXY (§13) re-confirms bull-beta here.

**No robust macro edge.** VIX is the best external prior (real downtrend signal via
vol, the structural idea §13 missed) but its crypto signal is contaminated by
equity-vol shocks → net flat. Consistent with §13's regime-luck conclusion, now
shown via the walk-forward + a genuinely-external series. Stablecoin-supply /
exchange-flow (the prompt's examples) were not reachable free (DeFi Llama
stablecoin endpoints 404; on-chain flows are paid CryptoQuant/Glassnode) — VIX/
SP500 were the accessible free external series. Step 4 closes the macro-prior
direction: no deployable external-regime prior at retail/free-data resolution.

## §23. Carry basis tail quantified (step 2 follow-up) — small in-sample, but rare-event cascade is the real wipe; classic "pennies before a steamroller"

> §20 flagged an UNMODELED basis/short-squeeze tail as the carry's deployability
> blocker. Step 2 follow-up: quantify it from REAL perp-vs-spot basis (Binance
> Vision spot 15m vs the cached perp 15m, 2023-01→2026-07, `scripts/basis_risk.py`).

### 23.1 Binance data bug found + fixed (reusable)
Binance Vision switched **spot klines from milliseconds (13-digit) to microseconds
(16-digit) ~2025**; futures stayed ms. `pd.to_datetime(unit="ms")` overflowed on
the µs rows → garbage timestamps (year 58551) → all 2025-2026 spot bars silently
dropped. Fixed in `pull_binance.py` (per-file unit normalization + range filter);
also added `market="spot"` so spot is pullable by `python -m scripts.pull_binance
spot BTCUSDT ETHUSDT SOLUSDT`. Spot 15m now cached for BTC/ETH/SOL.

### 23.2 Basis distribution (125563 bars each, full window)

basis B = perp/spot − 1 (bps). Carry harvest = SHORT perp + LONG spot → PnL vs
basis = B_entry − B_close → PROFITS when B falls (discount widens), LOSES when B
rises (premium widens / short squeeze). Margin-call drawdown = max premium.

| sym | mean | std | p99 | max (premium) | min (discount) | 1yr funding | worst spike | spikes>1yr |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| BTC | −2.7 | 4.0 | +10 | **+69** | −186 | 8.20% | 71 bps | 0 |
| ETH | −2.6 | 4.4 | +10 | **+76** | −384 | 8.59% | 78 bps | 0 |
| SOL | −3.1 | 5.8 | +13 | **+59** | −260 | 11.93% | 75 bps | 0 |

- Mean basis NEGATIVE (perp persistently at a small discount to spot). For the
  harvest that is mildly favorable at entry (short perp below spot, mean-reverts
  to 0 → small gain), not a drag.
- Worst adverse PREMIUM spike (the squeeze cost) = **+0.59% to +0.76%** (59-78 bps).
- 1yr funding income = **820-1190 bps**. Worst in-sample spike is **~1/11 to 1/16
  of one year's funding income**. Zero 8h windows had a premium > 1yr funding.
- Discount spikes (favorable) are larger (−1.9 to −3.8%): the basis exposure is
  **asymmetric and favorable** in this window — bigger moves help the carry leg
  than hurt it.

### 23.3 Verdict — basis does NOT refute the carry in-sample, but it IS the classic carry shape
In 2023-2026 the basis tail is small relative to income → the carry survives and
the §20 ~7%/yr (per-notional) holds after basis. **But the window excludes the
catastrophic liquidation cascades** — March 2020, May 2022 (LUNA), Nov 2022 (FTX)
— where perp-spot basis blew out **5-20%**. Those are the wipe events; this calm-
to-bull window had none, so the tail is understated.

Stress (historical cascade magnitude, arithmetic not simulation): a **10% perp-
premium spike** = 1000 bps > 820-1190 bps (1yr funding) → wipes **~0.8-1.4 years**
of funding income in a single event. On total capital (perp margin + full spot ≈
2× notional) the carry nets ~4%/yr; one 10% spike every ~3-4yr (historical cadence)
≈ wipes the entire cycle's capital return. **Net ≈ 0 over a full cycle** — the
textbook "picking up pennies in front of a steamroller" carry profile.

**Status: still watchlist, now characterized.** Basis is a rare-event tail, not a
constant drag; the carry is a low-return (~4%/yr on capital), left-tail-exposed
strategy that breaks even over a cycle containing one cascade. To promote to
deploy would need an explicit squeeze hedge (e.g. close on a funding-rate /
basis blowout trigger, or cap leverage so a 15-20% spike is survivable with
reserve) — that's a real engineering project, not a parameter tweak, and the
risk/reward (≈4%/yr for tail-wipe) is not attractive. The §20 blocker stands and
is now quantified: not "unmodeled" but "rare-event, in-sample-small, cycle-wiping."
Consistent with §20's "watchlist, not deployed."

## §24. Carry basis-stop de-risk (step 2 engineering) — a 100bps stop tames the tail at ~zero in-sample cost; bounded but still not a robust edge

> §23 quantified the carry's basis tail as rare-event but cycle-wiping (a 10%
> perp-premium blowout > 1yr funding income). (c) asks: can a BASIS-STOP make the
> tail BOUNDED for an affordable insurance cost? `scripts/carry_stop.py`.

### 24.1 Design
One-sided harvest (short perp + long spot, §20) + a basis-stop: while holding, if
perp premium B (bps) > stop_bps, FLATTEN (realize the adverse basis = stop_bps of
notional + close fees + 1% TDS on the spot sell); re-enter only when B < stop/2
(hysteresis, don't reopen into an ongoing squeeze) AND funding positive. Simulated
at **15m resolution** (basis-stop checks every bar — 8h-mark sampling misses the
intra-8h spikes; §23's +69-76bps maxima were intra-8h). Funding accrues PRO-RATA
per 15m bar, (1+r)^(1/32) while holding (Binance funding is time-pro-rata; also
gap-robust — 35% of 8h marks miss the 15m grid). Baseline (no stop) reproduces §20:
BTC +29.7%/7.5%/yr, ETH +23.4%/6.0%, SOL +16.5%/4.3%.

### 24.2 Results — stop level vs in-sample cost (2023-2026, NO cascade in window)

| sym | stop | net% | /yr% | stops | cost vs none |
|---|---:|---:|---:|---:|---:|
| BTC | none | 29.7 | 7.53 | 0 | — |
| BTC | 30 | 13.2 | 3.53 | 7 | −16.5pp (whipsaw) |
| BTC | 50 | 24.8 | 6.39 | 1 | −4.9pp |
| BTC | **100** | **29.7** | **7.53** | **0** | **0 (free)** |
| ETH | none | 23.4 | 6.04 | 0 | — |
| ETH | 30 | 17.6 | 4.62 | 3 | −5.8pp |
| ETH | 50 | 21.1 | 5.48 | 1 | −2.3pp |
| ETH | **100** | **23.4** | **6.04** | **0** | **0 (free)** |
| SOL | none | 16.5 | 4.34 | 0 | — |
| SOL | 30 | 9.8 | 2.65 | 3 | −6.7pp |
| SOL | 50 | 11.4 | 3.07 | 2 | −5.1pp |
| SOL | **100** | **16.5** | **4.34** | **0** | **0 (free)** |

- **A 100bps (1%) basis-stop is FREE in-sample**: 0 triggers across all three
  assets (the 2023-2026 max premium was 69-76bps < 100). It costs nothing in calm
  windows yet CAPS the worst-case basis loss at 1% of notional.
- 50bps stop: 1-2 false triggers, ~1-2pp/yr cost, caps tail at 0.5%.
- 30bps stop: 3-7 triggers, whipsawed by normal basis noise → too tight (−6 to
  −16pp). The basis noise floor sits ~30-50bps; a stop must sit ABOVE it to avoid
  self-destruction, which 100bps does.

### 24.3 Verdict — tail bounded, but carry is still not a robust edge
The basis-stop is a **real improvement**: the §23 unbounded cascade (5-20%) is
capped at ~1% (stop) for ~0 in-sample insurance premium. Stress: a 10% perp-
premium cascade uncapped = −10%; with a 100bps stop = −1% → **saves ~9% per event
≈ ~1.2yr of BTC funding income preserved per cascade.** The carry moves from
"watchlist, unbounded-tail-blocked" to "watchlist, bounded-tail, execution-
dependent." The §23 blocker is no longer "unmodeled tail" but is now:

1. **Execution in a squeeze**: a real cascade gaps the premium from <100bps to
   500-2000bps in one or few prints (liquidity vanishes). The 100bps stop may fill
   at 500bps+ → real loss > 1%. The 1% cap assumes you flatten at the stop level;
   in practice the cap is "first-liquid-print," likely 2-5%. Still far below 20%,
   so the stop helps, but not to 1%. Needs a conditional/limit order pre-staged.
2. **Missed funding income while flat** after a stop (reopen hysteresis keeps you
   out through the volatile period).
3. **CoinDCX venue**: Binance basis ≠ CoinDCX INR-margin perp-spot basis; the stop
   must trigger on the ACTUAL venue's basis (the §20 venue caveat stands).
4. **The in-sample window has no cascade** → 0 stops means we can't DEMONSTRATE
   the stop firing+protecting in a real event, only argue it from mechanism (a
   >100bps premium WILL trigger it). The protection is mechanism-argued, not
   walk-forward-proven.
5. **Low return for complexity**: ~3.75%/yr on 2× capital (perp margin + full
   spot), now with a bounded-but-execution-uncertain tail + two-leg real-time
   basis monitoring + squeeze execution. Infrastructure-heavy for the return.

**Status: still watchlist, now bounded-tail.** The basis-stop does what (c) asked
— tames the tail affordably — but does not manufacture a robust OOS edge. The
carry remains a low-return, left-tail-(now-bounded), venue-and-execution-dependent
strategy. The honest stopping blocker moved from "unmodeled tail" to "execution in
a squeeze + venue basis + low return for the complexity." No robust edge; the
engineering de-risked the tail without changing the risk/reward enough to deploy.

## §25. CVD forward-test on accrued CoinDCX ticks (step 3 analysis) — hit% <50% on every pair/config, no short-horizon order-flow edge

> §21 unblocked the CoinDCX Socket.IO feed (the 1005-drop was a code bug, not
> infra) and deployed recorders on Oracle Cloud. The open question was whether
> REAL trade-side CVD (aggressor side from `m`=isBuyerMaker) predicts short-horizon
> direction — the one structurally-different info source not yet tested. It is NOT
> backtestable from history (no tick archive), so it had to accrue live. The
> recorders ran 16 days (2026-08-07 → 2026-08-23); `scripts/cvd_forward.py` runs on
> the accrued sample. Verdict gate (per the plan): hit% materially >50% AND net_eq>1
> over a ≥1-week sample → justify a proper walk-forward; else CVD has no
> short-horizon edge.

### 25.1 Sample
scp'd the three growing tick CSVs off the box to `reports/ticks_B_*.csv` (gitignored
— the sample): BTC 10.39M ticks / 433MB, ETH 9.91M / 397MB, SOL 2.23M / 83MB. Each
spans the full 16 days (~379h). Recorders were alive the whole time
(`systemctl is-active recorder-{btc,eth,sol}` = active, active, active). This is
~2.3× the ≥1-week gate.

### 25.2 Results — every config below 50% hit rate

`cvd_forward.py` resamples ticks→time bars, takes the rolling-CVD sign as the
signal, scores hit rate (sign matches next-horizon return) + bare equity (no cost)
+ net equity (minus round-trip flip cost). The grid spans bar_s 1/5/15s, horizon
1-30 bars, lookback 20-200.

| pair | span | best hit% (bar/hz/lb) | net_eq (best) | gate |
|---|---|---|---|---|
| BTC | 379.6h | 48.4% (15s/30/200) | 0.07 | **FAIL** |
| ETH | 379.4h | 48.8% (15s/15 or 30) | 3.00 @ 15s/30 (hit 48.8%) | **FAIL** (hit<50) |
| SOL | 379.4h | 47.5% (15s/30/200) | 1.60 @ 15s/30 (hit 47.5%) | **FAIL** (hit<50) |

**hit% is BELOW 50% on every config, every pair**, and *worse* at short horizons
(1s bars: 27-33%), recovering toward 50% (= pure noise) as horizon/bar grows. This
is the signature of order flow already being in the price: by the time a rolling
CVD tilts positive the move has already happened, and the next bar short-horizon
reverts.

### 25.3 The bare_eq>1 at 1-5s is a momentum artifact, not an edge

`bare_eq` is huge at 1-5s (BTC 604x, ETH 41x, SOL 57x) — alarming until you read it
with hit%: rolling-CVD sign ≈ recent tick direction (buys push price up, sells down
by construction), so `signal*fwd_ret` at 1-5s captures the tail of an *in-progress*
move. But hit%<50% means the signal is directionally **wrong** more than half the
time; the equity gain is magnitude asymmetry on the few trending bars, not
directional accuracy. It is not tradable: flip cost (49k flips at 1s on BTC) wipes
it → `net_eq`→0. At the longest config (15s bars, 30-bar ≈ 7.5min hold) flips drop to
~1.2k and net_eq edges >1 on ETH/SOL, but hit% is still <50% there — the gain is one
trending sample's magnitude, not a repeatable directional edge, and the 16-day
window is a single regime with no walk-forward.

### 25.4 The below-50% hit hints at a fade — but not tradably
A follow-CVD hit% of 48% implies a *fade* (invert the sign) would score ~52%. That is
NOT "materially >50%", is net-thin after flip cost, and is over a single 16-day
regime. Noted honestly as a microstructure-reversal hint; not pursued as an edge and
not meeting the gate.

### 25.5 Verdict
**CVD has no short-horizon directional edge.** The last structurally-different info
source (real trade-side order flow, not price-derived) closes negative, consistent
with every other thread (grid, ensemble, trend, carry, macro). The §21 feed unblock
was real engineering progress that made this test possible; the test result is that
CVD carries no short-horizon alpha on these perps. The recorders can keep running
for a longer sample / a future volume-profile test, but no CVD edge is established.

Delivered: `scripts/cvd_forward.py` (run on the accrued sample); tick sample cached
locally (`reports/ticks_B_*.csv`); `reports/cvd_forward.log`.

## §26. Taker-buy-ratio order-flow walk-forward (step 1, default direction) — no robust edge; the bar-level order-flow proxy is bull-beta, whipsaw, or inert

> The handoff's default direction. Binance perp klines carry `taker_buy_volume`
> (base-asset volume from buyer-TAKER trades); `pull_binance.py` had been dropping
> it. Re-pulled BTC/ETH/SOL 15m keeping the column, built a taker-buy-ratio signal
> (`taker_buy_base/volume`, bar-level order-flow imbalance ∈ [0,1], 0.5 = balanced),
> and ran it through the SAME regime-balanced K=4 walk-forward as §18/§19 (fixed
> params, no per-fold/per-asset tuning, real per-8h funding, lev 3, maker_on_limit,
> no TDS). This tests the order-flow class on the multi-year window without waiting
> for tick accrual (§25 is the tick-level test; this is the bar-level proxy).

### 26.1 Plumbing (additive, reuses the harness)
- `scripts/pull_binance.py`: keeps `taker_buy_volume`/`taker_buy_quote_volume`
  (renamed to `taker_buy_base`/`taker_buy_quote` for downstream). Also fixed the
  headerless-spot `COLS` fallback names. Cached CSVs refreshed for BTC/ETH/SOL.
- `app/strategy/taker_ratio.py`: new strategy. Smooths the ratio, then a persistent
  direction with **deadband hysteresis** (state=+1 while smoothed > 0.5+edge, -1
  while < 0.5-edge, hold in the deadband). `use_short=False` → long-only (sell state
  = flat). Persistent direction so the engine re-arms after a trailing stop-out.
  Self-check (`__main__`) verifies warmup/buy/sell/deadband-hold/long-only/missing-cols.
- `scripts/regime_wf.py`: `resample()` now sums `taker_buy_base` when present; 5
  taker_ratio candidates added (1h L/S, 1h L, 4h L/S, 4h L gated, 4h L/S edge=0.03).

### 26.2 Per-fold results (K=4, fixed params)

taker_ratio 4h L/S (the only variant with a short side and real trade counts):

| asset | f1 up | f2 up | f3 up | f4 dn | agg | pos | verdict |
|---|---:|---:|---:|---:|---:|---|---|
| BTC (+126/+80/+66/-43) | +1163 | -1438 | -1024 | +734 | -565 | 2/4 | whipsaw |
| ETH (+73/+26/+65/-57)  | -1151 | -486 | +136 | +802 | -698 | 2/4 | whipsaw |
| SOL (+468/+170/+34/-65) | +1160 | -1040 | -1931 | +744 | -1067 | 2/4 | whipsaw |

Wins in the *extreme* folds (strong-bull f1 and the downtrend f4, where the short
side catches the bear) and dies in the choppy middle folds (f2/f3) — the ratio flips
between buy/sell pressure on noise and the L/S gets stopped repeatedly. 2/4 pos but
**up 1, dn 1** on every asset = whipsaw, not robust (needs pos>2 AND up>0 AND dn>0).

### 26.3 Aggregate across all 5 variants × 3 assets

| variant | BTC | ETH | SOL | shape |
|---|---:|---:|---:|---|
| 1h L/S | -6740 (0/4) | -6063 (0/4) | -5383 (0/4) | lose — whipsaw (200-340 trades/fold) |
| 1h L   | -5068 (0/4) | -6475 (0/4) | -2571 (1/4) | lose — bleeds even in up folds |
| 4h L/S | -565 (2/4)  | -698 (2/4)  | -1067 (2/4) | whipsaw (wins extremes, loses chop) |
| 4h L gated | +589 (2/4) | -666 (1/4) | +389 (1/4) | **bull-beta, no cross-asset replication** |
| 4h L/S e0.03 | 0 (0/4) | 0 (0/4) | 0 (0/4) | inert — deadband too wide (4h ratio ≈ 0.5) |

- **1h variants** churn 130-340 trades/fold and bleed everywhere — the 1h ratio
  flips on noise; L/S whipsaws, long-only sits out the sell states then re-enters
  long on noise and gets stopped. Losing even in up folds (ETH 1h L fold2 -1850 in a
  +26% up fold) = whipsaw, not regime beta.
- **4h L/S** is calmer (77-97 trades/fold) but still whipsaws: the signal has
  momentum power in strong-trend folds (BTC f1 +1163, SOL f1 +1160) and the short
  side catches the downtrend (f4 +734 to +802), but the choppy middle folds shred it.
  2/4 with up 1 / dn 1 = whipsaw on all three.
- **4h L gated** is the closest to a signal — BTC +589 (2/4, up 2/dn 0) = bull-beta.
  But it FAILS cross-asset replication: identical fixed params give ETH -666 (1/4)
  and SOL +389 (1/4). The one asset that looked best (BTC) does so for a path reason
  the other two refute — the same falsifier shape as the §19 ETH supertrend 1d L/S
  outlier.
- **4h L/S edge=0.03** fired zero trades on every asset: a 0.03 deadband (0.47-0.53)
  is wider than the 4h ratio ever deviates from 0.5 → the signal never arms. The
  4h order-flow imbalance is too close to balanced for a threshold signal; edge=0.0
  (the 4h L/S row) is the operative setting, and it whipsaws.

### 26.4 Verdict — no robust order-flow edge at the bar level
**Zero robust flags in 15 asset×variant cells.** The taker-buy-ratio signal is
either whipsaw (1h, 4h L/S), bull-beta that does not replicate cross-asset (4h L
gated), or inert (deadband too wide). Same regime/path-beta conclusion as every
prior class: the bar-level order-flow imbalance does not generalize to an edge
across both bull and bear regimes on BTC/ETH/SOL under real perp costs.

The structural reading: taker-buy-ratio is a *coincident* order-flow measure (it
measures who is aggressing *right now*), so like the §25 tick-CVD it largely reflects
the move in progress. As a trend filter it catches strong directional folds and dies
in chop; as a mean-revert signal it would invert to ~52% hit (not robust either).
It is not a leading independent info source — consistent with §25's tick-level
finding (order flow is already in the price). The two order-flow tests (§25 tick
CVD, §26 bar taker-ratio) agree: no short/medium-horizon order-flow edge on these
perps.

Delivered: `scripts/pull_binance.py` (keeps taker buy volume), `app/strategy/taker_ratio.py`
(registered), `scripts/regime_wf.py` (5 taker_ratio candidates); re-pulled kline
CSVs now carry `taker_buy_base`; `reports/regime_wf_taker.log`. The original 9
candidates reproduce §18/§19 exactly (incl. the ETH supertrend 1d L/S +1058 ROBUST
outlier), confirming the harness is unchanged and the taker_ratio cells are on the
same footing.
