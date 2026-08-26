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

## §27. Carry funding-regime walk-forward (step 2, the one untested rigor gap) — carry is funding-regime-dependent; it bleeds small (not flat) in negative funding, all income from positive funding; NOT a robust edge

> The one open rigor gap from the handoff. §20 tested carry across PRICE-regime
> folds (K=4 by time, tagged by buy&hold sign) — but every one of those folds had
> POSITIVE mean funding (BTC fold4 posFund +3.5%, the "downtrend" fold included),
> so §20 never isolated a NEGATIVE-funding regime. §20 asserted "funding-regime-
> dependent, flat in negative funding" without ever scoring a negative-funding
> regime directly. This splits the window by FUNDING regime (sustained positive
> vs negative funding via a rolling mean) and scores the executable one-sided
> carry in each. `scripts/carry_funding_regime.py` (reuses
> `funding_carry_band.load_funding`/BANDS/FEE + `funding_carry.metrics`).

### 27.1 Design
Funding regime = sign of the rolling mean of the 8h funding rate over W marks
(funding is 3/day; W=21 ≈ 1 week — "sustained"). Segmented into contiguous
positive/negative regime runs. Executable one-sided carry (the deployable
CoinDCX version, §20.2-20.3): SHORT perp + LONG spot when rate > +band (harvest
positive funding), FLATTEN when rate < −band, HOLD in the deadband (pay small
adverse funding). Each flatten = spot SELL (1% TDS, spot-only — confirmed) + perp
close; each entry = 2 fills. Band train-selected on the first 70% by time (no
OOS peeking), as §20. Carry net decomposed per-regime as the sum of per-mark
net over the regime's marks (≈ log-return; per-mark returns are ~0.01% so the
decomposition is clean and the parts sum to the whole).

Gate (handoff framing): does carry SURVIVE a negative-funding regime, or only
go flat (opportunity cost)? On CoinDCX (no spot short) flat-in-negative is the
BEST achievable — the two-sided harvest of negative funding is not executable.
So the robust-edge bar is: profit in pos-regime AND no-bleed (≥0) in neg-regime.

### 27.2 Results (train-selected band, W=21, robust to W=42/63)

| asset | band | pos marks | pos net% | neg marks | neg net% | flattens | full net% | ~%/yr |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| BTC | 0.0002 | 3557 (91%) | **+26.3** | 361 (9%) | **−0.47** | 0 | +29.5 | 7.5 |
| ETH | 0.0003 | 3589 (91%) | **+26.1** | 329 (8%) | **−1.17** | 1 | +28.3 | 7.2 |
| SOL | 0.0005 | 2744 (70%) | **+18.6** | 1174 (30%) | **−2.55** | 2 | +17.4 | 4.6 |

Window-robust (W=21/42/63): neg-regime net stays negative on every asset at every
window — BTC −0.18 to −0.47, ETH −1.14 to −1.18, SOL −1.84 to −2.55. Pos-regime
net is stable (+26/+26/+18). Funding is ~91% positive for BTC/ETH (only ~9%
negative), 70/30 for SOL (SOL is materially more two-sided — that is why §20 SOL
had 5 flattens to BTC's 0).

### 27.3 Verdict — carry survives by a small bleed, NOT by going flat
**§20's "flat (0, no bleed) in negative funding" is REFUTED.** In actual
negative-funding regimes the carry BLEEDS a small amount (BTC −0.47%, ETH
−1.17%, SOL −2.55% over 2.5yr); it does not go flat. Why: the band holds through
mild-negative marks (rate between −band and 0, in the deadband) to avoid the
flip+TDS cost of flattening — so it pays small adverse funding instead of sitting
out. BTC never flattens at all (its funding min −0.00015 never crosses the
−0.0002 band), so it holds short through every negative-regime period and pays
the cumulative adverse funding. ETH/SOL flatten once or twice on the deeper
negative periods (e.g. ETH 2026-02→03, SOL 2023-09→10) but still net negative in
the regime.

This bleed is the cost-optimal band's deliberate residual: §20 already showed
band=0 (flatten on every sign change) is deeply negative (flip+TDS cost >
adverse funding), so holding through mild negatives IS the cost-minimizing choice.
The negative-regime bleed is the price of avoiding TDS-bearing flattens — not a
bug, but it means the carry does NOT cleanly sit out bears; it leaks.

**The carry still survives overall** (net +29.5/+28.3/+17.4%, the neg-regime
drag is ~2-9% of the pos income), but the robust-edge gate FAILS: the
negative-funding regime is NEGATIVE, not positive and not flat. The income is
entirely positive-funding-regime income (~7%/yr BTC/ETH, ~4.6%/yr SOL — being
the carry counterparty to leveraged longs in positive-funding regimes).
**NOT a robust regime-agnostic edge** — the same shape as the bull-beta price
trap, now shown directly across FUNDING regimes (not just price regimes).

This closes the one open rigor gap. §20's "funding-regime-dependent" conclusion
is confirmed with funding-regime evidence, and refined: neg-regime is a small
bleed, not flat. The carry remains the **watchlist** candidate (bounded-tail via
the §24 basis-stop, execution/venue-dependent) — the only non-negative-result in
the research — but it is NOT a robust OOS edge across both funding regimes, and
it was never going to be (by construction it harvests positive funding only).

Delivered: `scripts/carry_funding_regime.py`; `reports/carry_funding_regime.log`.
See [[funding-carry-band]] (§20), [[multi-asset-regime-walkforward]] (§19).

## §28. Final synthesis — no robust retail perp edge at free-data resolution across bull and bear; research concludes

> §27 closes the last open thread (the carry funding-regime rigor gap). Every
> direction is now closed or parked. This is the concluding synthesis.

### 28.1 The thread ledger
| § | class | result | shape |
|---|---|---|---|
| 1-7,11 | 23 price strategies + ensemble | empty | diversification = in-sample artifact |
| 18 | real-cost + regime-balanced WF (BTC) | closed | every apparent edge = bull/bear beta |
| 19 | multi-asset perp regime WF (BTC/ETH/SOL) | closed | 1 ETH outlier = path luck, fails cross-asset |
| 20 | band-gated funding carry | **watchlist** (net-pos, not robust) | funding-regime income + unmodeled tail |
| 21-25 | microstructure: feed fix → CVD forward-test | closed negative | order flow already in the price |
| 22 | macro prior WF (DXY/US10Y/VIX/SP500) | closed | VIX best, SVB-contaminated to flat |
| 23-24 | carry basis tail + basis-stop | watchlist de-risk | bounded tail, execution-dependent |
| 26 | taker-buy-ratio bar order-flow WF | closed negative | whipsaw / bull-beta / inert |
| 27 | carry funding-regime WF | closed (not robust) | neg-regime bleeds small, not flat |

### 28.2 The conclusion
**No strategy with a ROBUST OUT-OF-SAMPLE edge — one that holds across BOTH bull
and bear regimes — exists on these perps (BTC/ETH/SOL) at free-data resolution
under real CoinDCX perp costs.** Every apparent edge is one of:
- **Bull beta** — rides the 2023-25 bull, bleeds in the 2025-26 downtrend
  (grid, long-only trend, breakout/momentum, funding carry positive-regime,
  macro SP500/DXY, taker-ratio 4h L gated on one asset).
- **Bear beta** — shorts profit only in the one downtrend, blow up in bulls
  (long/short trend, daily supertrend L/S, VIX, taker-ratio 4h L/S short leg).
- **Path luck** — one asset/period looks best for a reason the others refute
  (ETH supertrend 1d L/S §19, BTC taker-ratio 4h L gated §26).
- **Whipsaw** — chews itself on noise in choppy regimes (1h order-flow, 4h L/S).
- **Coincident, not leading** — order flow (tick CVD §25, bar ratio §26)
  reflects the move in progress; already in the price.

The fixed 70/30 split was adversarial (OOS = the single 2025-26 downtrend), but
the regime-balanced K=4 walk-forward — the fairest test, scoring every regime —
refuted every candidate too. Long-only rides bulls and bleeds in bears;
long/short bleeds in bulls and profits in bears; neither nets positive across
both. Funding carry nets positive but is funding-regime income (positive-funding
harvest), not alpha, with a left-tail (now bounded by the §24 basis-stop) and
venue/execution dependence.

### 28.3 The one non-negative result — funding carry, watchlist, not deployed
The band-gated one-sided funding carry (~7%/yr BTC/ETH, ~4.6%/yr SOL on perp
notional; ~3.5%/yr on 2× total capital at lev 1) is the only net-positive-
after-all-real-costs result. It is the single deploy candidate, kept on the
**watchlist** (NOT deployed), because:
1. Not a robust edge — positive-funding-regime income only; §27 shows neg-regime
   bleeds small (not flat). Fails "profit across both regime types."
2. Left-tail — §23 quantified the basis/short-squeeze tail (rare-event, cycle-
   wiping 5-20% in cascades excluded from the 2023-26 sample). §24 showed a 100bps
   basis-stop caps it at ~1% for ~0 in-sample cost, but squeeze *execution* (the
   premium gaps <100→500-2000bps in one print) means a real stop fills at 2-5%,
   not 1% — bounded in theory, execution-uncertain in practice.
3. Venue — Binance funding/basis ≠ CoinDCX INR-margin perp; must verify CoinDCX's
   own marks before any deployment.
4. Low return for complexity — ~3.75%/yr on 2× capital for two-leg real-time basis
   monitoring + squeeze execution + the tail risk. Infrastructure-heavy for the
   return.

Bar to deploy (unchanged): verify CoinDCX actual funding + basis; engineer the
squeeze hedge / reserve for a 15-20% spike; confirm the ~7%/yr is worth the
(now-bounded) tail. None of these are parameter tweaks — they are real execution
engineering on the venue, which is out of scope for this research phase.

### 28.4 What was built (reusable infra, kept)
- `app/backtest/engine.py`: dynamic signed funding (`funding_rates`), regime
  gate (`regime_sma`), shorts (`allow_short`), maker-on-limit, fee/funding
  double-count fix, wall-clock daily-loss fix. `cfg_for(kind)` exit contract.
- `scripts/regime_wf.py`: the regime-balanced K=4 walk-forward harness (the
  primary gate); taker-ratio-aware resample.
- `scripts/pull_binance.py` + `pull_funding.py`/`real_funding.py`: perp+spot
  klines (taker buy volume kept), real funding history, ms/µs fix.
- `scripts/funding_carry_band.py` + `carry_funding_regime.py`: band-gated carry
  + funding-regime decomposition.
- `scripts/basis_risk.py` + `carry_stop.py`: basis tail quant + basis-stop de-risk.
- `scripts/microstructure.py`: CoinDCX Socket.IO EIO=3 recorder (the §21 feed
  unblock — real engineering progress). Deployed on Oracle Cloud, recording 24/7.
- `scripts/cvd_forward.py`: tick CVD forward-test harness.
- `app/strategy/taker_ratio.py`: bar order-flow signal.

### 28.5 Honest framing
This is the negative result the research set out to find or rule out. "No robust
retail edge on these perps at free-data resolution across both regimes" is itself
the finding — it is not a failure to find a strategy, it is a characterization of
the market: at retail cost + free public data, price/order-flow/macro signals are
either regime beta, path luck, or already-priced. The carry is the exception that
proves the rule — it is positive because it is paid to provide a service (funding
liquidity to leveraged longs), not because it predicts price. Deployable only if
the venue execution and the (bounded) tail are engineered, at a return that may
not justify the work.

**Research concludes.** Recorders stay running on the Oracle box (accruing a
longer tick sample / future volume-profile option); the carry stays on the
watchlist as the only deploy candidate if execution is ever engineered.

## §29. Post-conclusion follow-ups — venue-verify (#1), order-book depth (#2), volume profile (#3); none manufactures a robust edge

> After §28, the three "could there still be something" directions were tried in
> order: (1) engineer the carry toward deploy via venue verification, (2) order-
> book depth (the one untested order-flow derivative), (3) volume profile from
> accrued ticks. None produces a robust edge; #1 makes the carry LESS deployable
> on the actual venue, #2/#3 are forward-accrual / thin and map to closed classes.

### 29.1 #1 — CoinDCX venue verification (the §20/§23 venue caveats)
`scripts/coindcx_venue.py` (public API, no auth) + a forward recorder
`scripts/coindcx_venue_recorder.py` (deployed on the cloud box as
`coindcx-venue.service`, polling every 60s). Findings:

- **Fees verified** (instrument endpoint): CoinDCX INR-margin perp maker **0.0236%** /
  taker **0.059%** — slightly HIGHER than the carry backtest assumed (0.02%/0.04%).
  Negligible on carry (1-10 flips/2.5yr → fee delta ≪ funding income). Verdict holds.
  `funding_frequency=8h` confirmed (matches model).
- **Funding: NO public history.** CoinDCX exposes no funding-rate-history endpoint;
  the real-time endpoint `public.coindcx.com/market_data/v3/current_prices/futures/rt`
  (`fr` current / `efr` next) is the only public source. Spot-check NOW: CoinDCX
  `efr`=0.0001 = Binance `lastFunding`=0.0001 for BTC/ETH/SOL → the Binance funding
  PROXY is reasonable for the funding LEVEL. But history cannot be pulled → the
  ~7%/yr cannot be recomputed on CoinDCX funding retrospectively; must be accrued
  forward (the recorder does this).
- **Basis: INR-margin has NO USDT spot leg.** CoinDCX spot is INR-quoted (BTCINR), not
  BTCUSDT. Synthetic USDT spot = BTCINR / USDTINR = TWO INR legs → carries a USDTINR
  FX risk the Binance perp+USDT-spot proxy did NOT have. INR-spot OHLC history is
  NOT public (candle endpoint returns no_data for BTCINR; v2 needs auth). Current
  basis snapshot = perp mark vs synthetic spot = **−32 to −38bps** (within the
  Binance §23 range of −186..+69bps; no red flag from 1 snapshot).

**Net #1: the carry is LESS deployable on CoinDCX than the Binance-proxy backtest
suggested**, not more: an extra USDTINR FX leg in the hedge, and BOTH venue caveats
(§20 funding, §23 basis) are forward-only (no public history). The forward recorder
will close both over time — until then the §20/§23 venue caveats STAND. Fees higher
(negligible). No new edge; the deploy bar (engineer the squeeze hedge + verify
venue) is unchanged and now known to be harder (FX leg). Carry stays watchlist,
NOT deployed.

### 29.2 #2 — order-book imbalance (OBI) from depth (the untested order-flow derivative)
`scripts/microstructure.py` extended to capture `depth-update-20` (CoinDCX emits
it on the same channel as `new-trade` — a 20-level SNAPSHOT ~1/s, NOT a diff, so
OBI = (Σbid_qty − Σask_qty)/(Σbid_qty+Σask_qty) directly, no local book). Deployed
across the 3 recorders (BTC/ETH/SOL `depth_*.csv` accruing). `scripts/obi_forward.py`
(forward-test harness, mirrors §25 `cvd_forward.py`: smoothed-OBI sign vs next-
horizon MID return, hit% + flip-cost net equity). Same gate as §25 (hit%
materially >50% AND net_eq>1 over ≥1 week).

Status: accrual started (depth ~1/s, retail-friendly latency — NOT microsecond
HFT, so the "retail can't compete" concern is milder than feared). OBI is noisy
at 1s (swings −0.93..+0.95 in samples). Forward-test in ≥1 week. Honest prior:
§25 (trade CVD) and §26 (bar taker-ratio) both closed order flow as coincident /
already-priced; OBI is RESTING liquidity (different in theory) but is the third
order-flow derivative tested — expected to close the same way. Not run yet
(needs accrual).

### 29.3 #3 — volume profile from accrued ticks (the low-EV "long shot")
`scripts/volume_profile.py` — REAL tick volume-at-price (not the OHLC
approximation §25 called weaker): per 4h window, bin ticks by price → POC (max-
vol price), value area (70% of volume around POC), VAH/VAL; forward-test
reversion (fade VAH/VAL) vs breakout (follow VAH/VAL). Ran on the 16d accrued
tick sample (BTC 10.4M / ETH 9.9M / SOL 2.2M rows, ~95 windows):

| pair | kind | n | hit% | net_eq |
|---|---|---:|---:|---:|
| BTC | reversion | 10 | 40.0 | 0.990 |
| BTC | breakout | 10 | 60.0 | 1.003 |
| ETH | reversion | 8 | too few | — |
| ETH | breakout | 8 | too few | — |
| SOL | reversion | 14 | 35.7 | 0.982 |
| SOL | breakout | 14 | 64.3 | 0.996 |

Signal fires only 8-15% of windows (close sits inside VA otherwise). **No edge:**
n=8-14 per kind is statistically VOID; reversion hit% < 50% everywhere; breakout
hit% > 50% but net_eq ≤ 1.003 (breakeven-to-negative after flip cost). 16d is too
thin for a robust VP walk-forward (need months). Both VP uses map to classes §18
refuted on price bars (reversion = mean-revert; breakout = bull-beta). Consistent
with the handoff's "long shot." Recorders keep accruing for a longer-sample test,
but the structural read says low EV.

### 29.4 Net
No robust edge from any follow-up. #1 made the carry's deploy bar HARDER (FX leg +
forward-only venue caveats), not easier. #2 is accruing (verdict in ≥1 week, prior
negative). #3 is thin + maps to refuted classes. The §28 conclusion holds: no
robust retail perp edge at free-data resolution across both regimes. The carry
remains the only watchlist candidate, now with a known-harder venue path; OBI is
the one live test still pending. New scripts: `coindcx_venue.py`,
`coindcx_venue_recorder.py`, `obi_forward.py`, `volume_profile.py`;
`microstructure.py` extended (depth). Logs: `reports/coindcx_venue.log`,
`reports/volume_profile_btc.log`.

## §30. Hybrid carry deploy built (sub-project 1) — paper-trader + components; 4-phase gated, NOT deployed

> §28 closed the research (no robust retail perp edge at free-data resolution).
> §29 hardened the carry's deploy bar (venue-verify made it HARDER, not easier;
> OBI still accruing). This section logs that the **engineering** sub-project —
> building the deployable paper-trader for the one watchlist candidate (the
> §20/§24 band-gated carry, basis-stop de-risked) — is now BUILT. It is paper-
> gated, not live. Spec: `docs/superpowers/specs/2026-08-24-hybrid-carry-deploy-design.md`;
> plan: `docs/superpowers/plans/2026-08-24-hybrid-carry-deploy.md`.

### 30.1 What was built (Tasks 1-7)

| component | file | role |
|---|---|---|
| risk budget | `scripts/risk_budget.py` | pure sizing: `position_size(capital, stop_fill_est, risk_fraction, leverage_cap)`, `tilt_size(capital, conviction, risk_fraction, leverage_cap)` (≤20% of perp notional naked), `max_dd_halt(equity, peak, max_dd)`. stdlib `assert` self-check. |
| spot order | `app/exchange/coindcx.py` `create_spot_order(side, pair, order_type, quantity, price=None)` | signs body + `self._priv.post` directly (mirrors `create_order`); endpoint `/exchange/v1/orders/create` flagged `# ponytail: unverified vs live docs` — Phase 0/1 paper + Phase 2 signing dry-run resolve; **no live orders until Phase 2**. |
| carry trader | `scripts/carry_trader.py` | the async live loop: `decide(rate_history, band, side)` signal; `run_loop(cfg, client, feed, live)`; fault handling (feed outage 2×poll_s halt, basis-stop > cfg `basis_stop_bps`, DD-stop via `max_dd_halt`, orphan-leg guard perp-first→spot with reject→exit perp+halt, HALT-file kill-switch); `reconcile(st, client, pair)` against exchange truth; state persisted `reports/carry_trader_state.json`. |
| tilt slot | `scripts/carry_trader.py` `TiltSignal` / `NoTilt` | pluggable interface (Phase 3); `NoTilt` stub returns conviction 0.0 — ON only when sub-project 2 (regime-gate) + sub-project 3 (asymmetric risk overlay) land. |
| signing test | `tests/test_exchange.py` | pytest: real hmac over captured content + `X-AUTH-APIKEY`. |

`run_loop` argparse: `--live` / `--band` / `--capital` / `--pair` / `--spot-pair` /
`--leverage`. `--live` is refused unless `settings.trading_mode == "live"`. The
`_live_feed` reads `reports/coindcx_venue.csv` (the Phase 0 venue-verify output)
— so the paper loop cannot even start against a stale venue truth.

### 30.2 Four-phase gating status (NOT DEPLOYED — paper-gated)

| phase | gate | status |
|---|---|---|
| 0 venue-verify | CoinDCX INR-margin perp + spot-leg venue truth (§29.1) | **ACCRUING** — recorder on Oracle Cloud box, needs weeks; no deploy. |
| 1 paper-trader | `scripts/carry_trader.py` paper mode | **READY** to run once the Phase 0 venue-gate passes (venue csv non-empty + clean). Paper IS the integration test. |
| 2 small real | `--live` + small capital | gated behind ≥1 week of clean Phase 1 paper; signing dry-run first. |
| 3 tilt ON | `TiltSignal` non-stub | gated behind sub-project 2 (regime-gate research) + sub-project 3 (asymmetric risk overlay). `NoTilt` returns 0.0 until then. |

### 30.3 Fail-safe contract

Every fault path → flatten + halt: feed outage (2× poll_s with no tick), restart
(`reconcile` on startup vs exchange truth — adopts exchange size/side or halts on
mismatch, never guesses), orphan leg (perp-first→spot; on spot reject → exit perp
+ halt), unknown/corrupt state (halt, do not trade), HALT file
(`reports/carry_trader.HALT` → flatten all + halt). Isolated margin. Perp
INR-margin futures carry **no 1% TDS** (TDS is spot-sell only — confirmed in §20/§27);
the spot leg's sell pays it. `ponytail:` markers flag the known simplifications
with ceilings and upgrade paths (global rate lock, `_mark_equity` placeholder,
unverified endpoint path).

### 30.4 What this is NOT

This is engineering, not a new edge. §27's verdict (carry is funding-regime-
dependent, bleeds small in negative funding, NOT a robust regime-agnostic edge)
stands — this sub-project does not reopen it. The carry remains the single
watchlist candidate (bounded-tail via §24 basis-stop, execution/venue-dependent),
now with a real paper-trader to surface venue/execution risk the backtest cannot
see (slippage, funding-timing, orphan-leg paths, venue-lag). The tilt slot is the
hook for sub-project 2's regime-gate signal and sub-project 3's asymmetric risk
overlay — both separate specs, neither built. Deployment decisions remain gated
behind Phase 0 (venue truth) + Phase 1 (clean paper ≥1 week) + §27 (no robust
edge — size accordingly).

Delivered: `scripts/risk_budget.py`, `scripts/carry_trader.py`,
`tests/test_exchange.py`, `app/exchange/coindcx.py` (`create_spot_order`).
State: `reports/carry_trader_state.json`. Kill-switch: `reports/carry_trader.HALT`.
See [[funding-carry-band]] (§20), [[carry-basis-stop]] (§24),
[[carry-funding-regime-walkforward]] (§27), [[post-conclusion-followups]] (§29).

## §31. Regime-gate tilt sweep — 0/18 cells pass; NoTilt; carry-only deploy stands (sub-project 2)

> §30 built the carry paper-trader with a pluggable tilt slot (`TiltSignal` /
> `NoTilt`). This section logs sub-project 2: a pre-registered walk-forward
> sweep of 3 regime-gate signals × 3 assets × 2 directions (18 cells) to find
> a directional tilt for a delta-neutral carry trader. Result: **0/18 cells
> PASS → `NoTilt`**. The tilt slot stays sealed; deploy remains carry-only
> (~5-6%/yr, §27). Spec:
> `docs/superpowers/specs/2026-08-24-regime-gate-tilt-design.md`; plan:
> `docs/superpowers/plans/2026-08-24-regime-gate-tilt.md`.

### 31.1 Sweep structure

3 gates × 3 assets × 2 directions = 18 cells.

- **Gates:** `funding_slope_signal` (rolling-window z-score of funding rate
  slope), `trend_signal` (supertrend-style: `period` + `mult`), `basis_signal`
  (rolling-window basis threshold `thr_bps`). Each gate outputs signed
  conviction ∈ [-1, +1]: `+=long perp, -=short perp` (the tilt slot contract
  from §30.1).
- **Assets:** BTCUSDT, ETHUSDT, SOLUSDT (perp).
- **Directions:** long, short (swept independently — the gate's conviction
  sign is forced, not derived; this tests each direction as a standalone tilt).
- **Path:** bar-level path equity, 15m bars, over the §27 walk-forward
  window.

### 31.2 Pass criterion (pre-registered)

A cell PASSes iff net > 0 after real costs in **all three** guards
simultaneously:

1. **K=4 contiguous time-slice walk-forward:** net > 0 in ≥ 3/4 folds AND
   aggregate net > 0.
2. **70/30 split:** train 70% / test 30% by time; net > 0 on the test slice.
3. **Bootstrap CI:** 1000 resample, circular-block `block=10`, fixed seed
   `np.random.default_rng(0)`, 95% CI lower bound > 0.

No Bonferroni (relaxed goalpost; the bootstrap+split70 guard is the path-luck
guard). This is the §19 path-luck guard
([[multi-asset-regime-walkforward]]) — the same one that killed the §13
walk-forward's single 1 ETH outlier.

### 31.3 Cost model (§29 CoinDCX real)

- Taker fee **0.059% per entry/exit** ( CoinDCX perp taker, §29).
- **5 bps/side execution-gap slippage**.
- **Funding paid/received at 8h marks ONLY** (mark-aligned, NOT
  forward-filled — forward-fill = 32× overcharge, the §27 calibration fix).
- **NO 1% TDS** — naked perp, no spot leg (TDS is spot-sell only, §20/§27).
- On the naked tilt: long in positive funding **pays**; short in positive
  funding **receives** (and vice versa in negative funding).

### 31.4 Per-cell verdict table

From `reports/regime_gate_wf.log` (18 rows):

| asset | gate | dir | net | ci_lo | k4 | split70 | verdict | params |
|---|---|---|---|---|---|---|---|---|
| BTCUSDT | funding_slope | long | -1.0 | -11.4951 | False | False | FAIL | `{'w': 40, 'z': 1.0}` |
| BTCUSDT | funding_slope | short | -1.0 | -11.4103 | False | False | FAIL | `{'w': 40, 'z': 1.0}` |
| BTCUSDT | trend | long | 2.141 | -0.0129 | True | False | FAIL | `{'period': 28, 'mult': 3.0}` |
| BTCUSDT | trend | short | -0.8575 | -3.2365 | False | True | FAIL | `{'period': 28, 'mult': 3.0}` |
| BTCUSDT | basis | long | -0.7296 | -2.7402 | False | True | FAIL | `{'w': 20, 'thr_bps': 5.0}` |
| BTCUSDT | basis | short | 0.0983 | -1.177 | True | False | FAIL | `{'w': 20, 'thr_bps': 5.0}` |
| ETHUSDT | funding_slope | long | -1.0 | -11.565 | False | False | FAIL | `{'w': 40, 'z': 1.0}` |
| ETHUSDT | funding_slope | short | -1.0 | -11.517 | False | False | FAIL | `{'w': 40, 'z': 1.0}` |
| ETHUSDT | trend | long | 2.7402 | -0.1823 | True | True | FAIL | `{'period': 28, 'mult': 2.0}` |
| ETHUSDT | trend | short | -0.9351 | -4.3179 | False | False | FAIL | `{'period': 28, 'mult': 2.0}` |
| ETHUSDT | basis | long | -0.6649 | -2.8257 | False | False | FAIL | `{'w': 10, 'thr_bps': 5.0}` |
| ETHUSDT | basis | short | -0.6142 | -2.6847 | False | False | FAIL | `{'w': 10, 'thr_bps': 5.0}` |
| SOLUSDT | funding_slope | long | -1.0 | -11.6753 | False | False | FAIL | `{'w': 20, 'z': 1.0}` |
| SOLUSDT | funding_slope | short | -1.0 | -11.9071 | False | False | FAIL | `{'w': 20, 'z': 1.0}` |
| SOLUSDT | trend | long | 5.3468 | 0.1793 | True | False | FAIL | `{'period': 14, 'mult': 3.0}` |
| SOLUSDT | trend | short | -0.9917 | -6.5961 | False | True | FAIL | `{'period': 14, 'mult': 3.0}` |
| SOLUSDT | basis | long | -0.9517 | -4.6394 | False | True | FAIL | `{'w': 20, 'thr_bps': 5.0}` |
| SOLUSDT | basis | short | -0.374 | -2.363 | False | False | FAIL | `{'w': 20, 'thr_bps': 5.0}` |

### 31.5 Results narrative

All 18 cells FAIL → `reports/regime_gate_pass.json` is `[]` →
`load_tilt_signal()` returns `NoTilt`. The tilt slot stays `NoTilt`; deploy is
carry-only (~5-6%/yr, §27). Consistent with §28 (no robust retail perp edge
at free-data resolution).

**funding_slope (all 6 cells):** every cell net = -1.0 (total wipeout). Cause:
conviction flips ~10,105 times over the window — the per-flip cost
(fee + slippage on each entry/exit) exceeds any directional capture. Funding
slope as a directional signal is churn-ruin, not edge. The bootstrap ci_lo
(~-11.4 to -11.9) confirms the wipeout is not path-luck; it is structural.

**trend long (3 cells, the only positive-net cells):** BTC +2.141, ETH +2.7402,
SOL +5.3468 — proves the sim is sane (it rewards bull-beta, as it should in a
bull window). But every one fails the path-luck guard:
- BTC: `k4=True` but `split70=False` (train captures the bull, test doesn't).
- ETH: `k4=True` and `split70=True` but bootstrap `ci_lo=-0.1823` (<0).
- SOL: `k4=True` but `split70=False` (`ci_lo=+0.1793` would pass the
  bootstrap guard alone, but split70 kills it).

Trend-long is one-regime bull-beta, not a robust edge — exactly the §19
path-luck trap the bootstrap+split70 guard was built to catch. The guard
earned its keep: three cells that look net-positive fall to different guards
each, the signature of path luck, not edge.

**trend short / basis (both directions, all 9 cells):** all negative net.
Short trend fights the bull regime (expected — short in a bull window pays
the negative drift). Basis (contango→long / backwardation→short) has no
directional capture after costs; the basis threshold is too coarse a signal
to time directional bets, and the basis itself is dominated by the same
funding/regime state the carry core already monetizes — no independent
directional information.

### 31.6 Conclusion

No regime gate produces a net-positive-after-real-costs directional tilt
robust to path-luck. The carry core (~5-6%/yr, §27
[[carry-funding-regime-walkforward]]) remains the only standing edge. Tilt
slot sealed `NoTilt`. Sub-project 3 (asymmetric risk overlay) is moot unless
a future gate passes — there is nothing to overlay. The §30 paper-trader's
tilt slot stays `NoTilt` (returns conviction 0.0); deploy is carry-only.

See [[funding-carry-band]] (§20), [[carry-funding-regime-walkforward]] (§27),
[[post-conclusion-followups]] (§29), [[multi-asset-regime-walkforward]] (§19).

## §32. Phase 0 venue-verify — read-only probe harness + FX-conversion gate (sub-project 4)

> §30 built the carry paper-trader; §31 sealed the tilt slot `NoTilt` (0/18
> regime-gate cells pass); the carry-only deploy (~5-6%/yr, §27) is the single
> standing edge, still NOT deployed. The §29 post-conclusion followup flagged
> the carry as "LESS deployable, FX leg": CoinDCX INR-margined perps settle via
> a platform USDT↔INR *conversion rate* that is NOT spot USDTINR, so the
> delta-neutral hedge (short perp + long BTCINR spot) leaks FX basis whenever
> the two diverge. This section logs sub-project 4: a **read-only probe
> harness** that verifies CoinDCX perp + spot venue truth against the carry
> deploy's assumptions and gates `carry_trader --live` on a data-driven
> PASS/FAIL JSON verdict — no manual go/no-go. Spec:
> `docs/superpowers/specs/2026-08-25-phase0-venue-verify-design.md`; plan:
> `docs/superpowers/plans/2026-08-25-phase0-venue-verify.md`.

### 32.1 Purpose + read-only constraint

Phase 0 is the systematic re-check of every load-bearing assumption in
`app/exchange/coindcx.py` (written against docs.coindcx.com 2026-07, every
such assumption flagged `ponytail: re-check before live money`). It is
strictly **read-only**: CoinDCX exposes no testnet/sandbox, so the order
write-path (`create_order` / `exit_position` / `create_spot_order`) cannot be
verified without real money and is deferred to Phase 2 small-real. Phase 0
touches public + private read endpoints only — no order is placed, no write
endpoint is called. The output is a single JSON verdict file that becomes the
`--live` gate. A valid outcome is either (a) `verdict: PASS` → `--live`
unlocked for Phase 1 paper / Phase 2 small-real, or (b) `verdict: FAIL` on
the FX-conversion probe → `--live` stays locked and a hedge-redesign
sub-project (USDT-margined perp, to kill the FX leg) is mandated before any
live trade. No human reads-and-decides step — the JSON verdict is the gate.

### 32.2 The probe set (7 read-only probes)

| # | Probe | Source | Verifies | PASS criterion |
|---|---|---|---|---|
| 1 | `auth_liveness` | REST private read | HMAC signing works; private endpoints live | `get_wallets()` + `get_positions(pair="B-BTC_USDT")` both 2xx (no `CoinDCXError`) |
| 2 | `instrument_perp` | `get_instrument("B-BTC_USDT")` | perp metadata vs §29 cost model | taker fee within ±5bps of 0.059%; leverage tier ≥ 3 (our cap); `min_quantity` ≤ typical size; lot/tick parse to floats |
| 3 | `instrument_spot` | spot metadata / `get_last_price("BTCINR")` | spot hedge-leg metadata | `min_quantity` ≤ hedge size; fee known + recorded; lot parses (falls back to ticker liveness + documented min-qty if no spot-instruments endpoint) |
| 4 | `funding_accrual` | `reports/coindcx_venue.csv` (recorder, 60s-polled) | the §20 backtest used Binance funding as a PROXY (~7%/yr); Phase 0 confirms real CoinDCX `fr` is accruing + its magnitude | CSV present, BTC rows span ≥8h (≥ one funding cycle), `fr` non-empty for ≥90% of BTC rows; records mean `abs(fr)` vs the Binance proxy (~0.0064%/8h). The 8h *settlement interval* is a CoinDCX venue fact from docs; the recorder's 60s `fr` is the rate-in-force, not a settlement event. |
| 5 | `fx_conversion` | `get_conversion_rate()` vs `get_usdt_inr()` | **§29 FX-leg crux** — hedge leak | mean `abs(conversion_price − spot_usdtinr) / spot_usdtinr` over N=8 samples (sampled ~1s apart within the single probe run) < 10bps |
| 6 | `basis_proxy` | recorder `coindcx_venue.csv` `basis_bps` column (pre-computed) | spot-ticker-as-perp-mark proxy (used for sizing + basis-stop) | median `abs(basis_bps)` over the CSV window < 100bps (the `basis_stop` threshold). The recorder pre-computes `basis_bps = (mp / (spot_inr/usdtinr) − 1)*1e4` — this IS the venue finding (USDTINR FX risk the Binance proxy did not carry). A leaky proxy >100bps would mis-trigger the basis-stop and mis-size entries → hard FAIL. |
| 7 | `rate_limit` | REST (light) | documented 16/s, 960/min | 2 rapid successive reads succeed with no 429; limit recorded. No stress test. |

Probes 1, 2, 3, 5, 7 hit REST; probes 4 and 6 read the recorder CSV
(`reports/coindcx_venue.csv`). No write endpoint is touched. A probe that
throws (endpoint down, auth fail, non-JSON) → that probe `pass: false` with
the error string; the harness continues the other probes and never crashes.
Missing `coindcx_venue.csv` → probes 4 + 6 FAIL (honest — the recorder is the
load-bearing source for funding/basis truth); `verdict: FAIL`. Auth FAIL →
every auth-dependent REST probe FAILs with auth named as root cause.

### 32.3 FX-conversion gate + redesign trigger (the binding decision)

The `fx_conversion` probe is the binding decision of Phase 0. It samples
`get_conversion_rate()` (the `/api/v1/derivatives/futures/data/conversions`
endpoint → `conversion_price`) and `get_usdt_inr()` (spot USDTINR ticker) N=8
times, spaced ~1s apart, computes `gap_bps = abs(conv − spot)/spot * 1e4` per
sample, takes the mean.

- **PASS:** `mean_gap_bps < 10` → contributes to `verdict: PASS`.
- **FAIL:** `mean_gap_bps ≥ 10` → `verdict: FAIL`,
  `redesign_required: true`, JSON `fail_reason` names the FX leg. A follow-up
  **hedge-redesign sub-project** (switch the carry to a USDT-margined perp so
  the hedge has no platform-conversion-rate leg) is *mandated*; no live trade
  until that sub-project ships its own Phase 0 PASS. The redesign is
  triggered, not built here.
- **`conversions` endpoint 4xx/5xx:** `fx_conversion` FAIL with `error` set,
  but `redesign_required: false` (can't-measure ≠ measured-bad);
  `verdict: FAIL` (can't verify = can't deploy).

The 10bps threshold is conservative: the carry edge is ~500-600bps/yr
([[funding-carry-band]] §20), so a 10bps persistent leak is < 2% of the edge.
It is hardcoded, not grid-searched — this is a gate, not a strategy. There is
no manual go/no-go decision anywhere in the flow: the JSON `verdict` field is
the gate, and `carry_trader --live` reads it programmatically.

### 32.4 Gate freshness + carry_trader wiring

`carry_trader --live` refuses unless `reports/venue_verify.json`:

1. exists (missing/corrupt → treated as refuse; `load_gate` never raises into
   the live path),
2. `verdict == "PASS"`,
3. `timestamp` within **24h** of now.

Stale or missing → refuse with a message to re-run
`python scripts/venue_verify.py run`. The 24h window is hardcoded; the
recorder runs 24/7 on the Oracle Cloud host, so re-verification is cheap and
there is no reason to deploy on a venue state verified days ago. The guard
sits in `carry_trader.main()` after the `settings.live` check and before
`CoinDCXClient` construction — a missing/stale/failing gate never
instantiates the client, never places an order.

### 32.5 Implementation (`venue_verify.py` + `get_conversion_rate`)

- **`app/exchange/coindcx.py::get_conversion_rate()`** — one new method,
  signed, endpoint `/api/v1/derivatives/futures/data/conversions`. The
  load-bearing gotcha: this endpoint takes a **SECONDS** timestamp, not
  milliseconds like other CoinDCX endpoints. Returns `conversion_price` for
  `symbol=USDTINR`. This is the one method that enables read-only FX-gap
  measurement without an open position — before it existed, the gap could
  only be observed by holding the hedge and watching the P&L leak.
- **`scripts/venue_verify.py`** — the harness. `PROBES` is the 7 functions
  above; `run_probes(client)` runs all 7 with per-probe try/except (a probe
  never crashes the harness); `verdict(results)` returns `PASS` iff all pass,
  else `FAIL` + `redesign_required` (true iff `fx_conversion` failed on a
  measured gap) + `fail_reason`. `main()` CLI arg `run` constructs
  `CoinDCXClient`, runs probes, writes `reports/venue_verify.json`
  (`{timestamp, verdict, redesign_required, fail_reason, probes[],
  threshold_bps, freshness_h}`) + a human-readable `venue_verify.log`. No
  `run` arg → `demo()`: a synthetic `FakeClient` exercises the JSON schema,
  PASS on good metadata, FAIL on fee mismatch (probe 2), the FX gap math
  (probe 5), and `redesign_required` set on FX FAIL — no live calls in the
  self-check. Constants: `FX_THRESHOLD_BPS = 10`, `FRESHNESS_H = 24`,
  `FX_SAMPLES = 8`, `BASIS_THRESHOLD_BPS = 100`, `FUNDING_MIN_SPAN_H = 8`.
- **`scripts/carry_trader.py`** — the `--live` guard calls
  `load_gate()` / `gate_is_fresh()` from `venue_verify`; refusal prints the
  verdict + re-run instruction and returns (no order, no crash). The 5
  existing demo OK lines (signal / faults / reconcile / sign / tilt) stay
  green; a 6th `carry_trader venue OK` line covers the gate.
- **`tests/test_exchange.py`** — `test_get_conversion_rate_seconds_ts`:
  mocked httpx response with a seconds-timestamp signed body, asserts it
  parses `conversion_price` and the request body uses seconds (not ms).

Reused unchanged: `CoinDCXClient` read methods (`get_instrument`,
`get_usdt_inr`, `get_positions`, `get_wallets`), the recorder's
`reports/coindcx_venue.csv`, and sub-project 1's fault-handling / reconcile
logic. The perp carries **no 1% TDS** (TDS is spot-sell only; the perp is
naked, the spot leg is the hedge and pays TDS on sell — already in the §29
cost model).

### 32.6 Probe results / status

No live `venue_verify.py run` has been executed in this environment — no API
keys are present here, and the recorder CSV (`reports/coindcx_venue.csv`) lives
on the Oracle Cloud host that runs the recorder 24/7
([[microstructure-feed-unblocked]]). The harness is built and its offline
`demo()` self-check is green (synthetic `FakeClient` exercises every probe's
PASS path, the fee-mismatch FAIL path, the FX-gap math, and the
`redesign_required` trigger; the `carry_trader` demo prints all 6 OK lines
including `venue OK`). The unit test for `get_conversion_rate` (seconds-ts
signing + `conversion_price` parse) passes. Phase 0 is therefore
**awaiting first live run on the recorder host** — pending the first
`python scripts/venue_verify.py run` there, which will write
`reports/venue_verify.json` + `reports/venue_verify.log` with the measured FX
gap, funding-accrual magnitude, and basis-proxy median. The §32 appendix will
be updated with that table once a live run lands; until then the gate is
absent and `carry_trader --live` refuses by construction.

### 32.7 Conclusion

Phase 0 venue-verify closes the §29 followup's "LESS deployable, FX leg"
concern into a data-driven gate. The 7-probe harness is built and self-checked
offline; the binding decision (FX-conversion gap < 10bps) is a hardcoded gate
that, on FAIL, auto-triggers a hedge-redesign sub-project rather than asking
a human to adjudicate. The carry deploy remains NOT deployed — now gated
behind (a) a live Phase 0 PASS on the recorder host, (b) Phase 1 clean paper
≥1 week, (c) §27's standing verdict that carry is funding-regime-dependent,
not a robust edge. The order write-path remains unverified by construction
(no testnet); Phase 2 small-real is where it first gets exercised against
real money. Sub-project 4's deliverable is the gate itself; the measured
venue truth is the next data point, expected from the recorder host.

See [[post-conclusion-followups]] (§29 — the FX-leg crux that motivated this),
[[funding-carry-band]] (§20 — the carry edge Phase 0 verifies),
[[carry-funding-regime-walkforward]] (§27 — the standing edge verdict),
[[microstructure-feed-unblocked]] (the recorder on Oracle Cloud, the CSV
source for probes 4 + 6).

## §33. Phase 1 paper-trader — two-feed paper run + operational validation gate (sub-project 5)

### 33.1 Purpose + no-orders constraint

Phase 0 (§32) built the venue-verify gate but left the carry deploy
**not deployed**: the paper feed was a stub, paper PnL a placeholder, and no
live `venue_verify.py run` had executed. Phase 1 closes those gaps **without
risking capital**: wire the stub paper feed to real CoinDCX data, replace the
placeholder equity with real paper-PnL accounting, run 7-14d on the Oracle
host (paper, no orders), and produce the definitive Phase 0 verdict by
running `venue_verify.py run` where the CSV lives. This is **operational
validation**, not edge re-confirmation — §20 already proved the edge; Phase 1
proves the loop runs end-to-end on the live venue.

Paper mode places **no orders**: `live=False`, `client=None` → `_enter_short`
sets `qty=0.0`, logs only. The Phase 0 venue gate is `--live`-only and does
not block paper. Phase 2 small-real remains gated behind Phase 0 PASS + Phase
1 operational-validation success.

### 33.2 The two-feed design (one `FeedSample` contract)

`FeedSample(ts, fr, efr, basis_bps, spot_price, usdtinr)` — unchanged from
sub-project 1. Two implementations, selected by `main()`'s new `--feed
{rest,csv}` (default `rest`); `--live` forces `csv` (live runs on Oracle where
the CSV exists) and keeps the Phase 0 gate.

**REST feed (`--feed rest`, dev / this Windows box):** `_paper_feed()` reuses
`scripts/coindcx_venue_recorder.py::sample()` — public REST, no auth, stdlib
`urllib`. That function already fetches `futures_rt()` (PUB
`/market_data/v3/current_prices/futures/rt`) + `spot_prices()`
(`/exchange/ticker` → BTCINR/USDTINR) and computes
`basis_bps = (mp/(spot_inr/usdtinr) - 1)*1e4`. `_paper_feed()` takes the BTC
row → `FeedSample`; on `sample()` failure or missing BTC row → `None` (the
existing feed-outage path). **No new fetch code.**

**CSV feed (`--feed csv`, Oracle):** `csv_feed()` extracted from the existing
`_live_feed()` body — reads the last row of `reports/coindcx_venue.csv` →
`FeedSample`. Same contract. The venue recorder writes this CSV 60s-polled.
Missing/empty/parse-error → `None` → outage path.

### 33.3 Paper-PnL accounting (replaces the placeholder equity)

The sub-project-1 `_mark_equity` was a `ponytail: placeholder` deferring real
MTM to Phase 2. Phase 1 replaces it with real accrual-based paper equity so
the 7-14d run produces a meaningful carry-income number on the live venue.

**Funding accrual at 8h marks:** CoinDCX settles funding every 8h
(00:00/08:00/16:00 UTC — `FUNDING_MARK_S = 8*3600`; the accrual keys on
`ts - (ts % FUNDING_MARK_S)`). When the feed's `ts` crosses a mark while
`state.side == -1`, accrue `accrued_funding += qty * fr_at_mark * entry_spot`.
This is the real CoinDCX carry income (vs the §20 Binance proxy); the 7-14d
rate is compared to ~7%/yr as a sanity check, not a re-proof. A mark crossing
missed by a feed gap accrues on the first post-gap `fr` (rate-in-force at
resumption) — honest, not fabricated.

**Basis MTM:** delta-neutral cancels the BTC price leg; the residual is the
FX/basis leg. `basis_mtm = qty * ((basis_bps - entry_basis_bps)/1e4) *
entry_spot` (0 if flat), so the equity curve reflects the §29 FX-leg leak
honestly. `basis_bps > 100` → basis-stop fires (unchanged).

**Equity + DD:** `equity = peak_equity` if flat, else
`peak_equity + accrued_funding + basis_mtm`. DD halt (25%) + basis-stop
(100bps) + flatten now drive off this real paper equity. Paper "flatten" =
`state.side = 0`, log the exit + realized paper PnL. No order. `TraderState`
gained four persisted fields (`accrued_funding`, `basis_mtm`, `last_mark_ts`,
`entry_basis_bps`); `_load_state` is field-tolerant (`d.pop("corrupt")` before
the `__dataclass_fields__` filter) so old sub-project-1 state files load with
defaults.

### 33.4 Paper ledger + 5-criteria gate (`paper_check.py`)

Append-only `reports/carry_paper.csv`, one row per state-changing event or
accrual: `ts, event, side, fr, efr, basis_bps, accrued_funding, equity`.
Events: `ENTER_SHORT`, `FUNDING_ACCRUE`, `BASIS_STOP`, `FLATTEN`, `DD_HALT`,
`FEED_OUTAGE` — all guarded `if not live` (never written in a real run). This
is the success-criteria evidence.

`scripts/paper_check.py` reads the ledger + state and emits the verdict
against five criteria over a contiguous 7-14d window:
1. **zero_faults** — no `DD_HALT`, not `halted_orphan`, not corrupt.
2. **feed_live** — `FEED_OUTAGE` < 5% of polls.
3. **signal_fired** — ≥1 `ENTER_SHORT` + ≥1 `FLATTEN` on funding-band
   crossings (`band=0.0002`).
4. **funding_nonneg** — `accrued_funding ≥ 0`; annualized within an order of
   magnitude of the §20 ~7%/yr proxy (sanity, not proof).
5. **state_clean** — not halted.

PASS on all five → Phase 2 small-real unlocked. The perp carries **no 1% TDS**
(TDS is spot-sell only); the spot-leg TDS on sell is a known §29 cost not
simulated in paper (paper never sells; it accrues funding) — recorded as a
caveat.

### 33.5 Oracle deploy + definitive Phase 0

Two systemd units committed (mirror the microstructure recorder pattern:
`User=ubuntu`, `WorkingDirectory=/home/ubuntu/Trading`, `Restart=always`):
- `deploy/coindcx-venue.service` — the REST venue recorder
  (`scripts/coindcx_venue_recorder.py`, public endpoints, no auth, no `.env`),
  writing `reports/coindcx_venue.csv` 60s-polled. A **separate** service from
  the microstructure `recorder-btc/eth/sol` units (which write `ticks_*.csv`).
- `deploy/carry-paper.service` — `python scripts/carry_trader.py --feed csv
  --pair B-BTC_USDT --spot-pair BTCINR --leverage 3` (paper, no `--live`),
  `After=coindcx-venue.service`, state persists across restarts.

`deploy/README.md` documents the recorder-first deploy order, the one-shot
`venue_verify.py run` (definitive Phase 0 verdict — probes 4+6 read the CSV
present on the host), and the `paper_check.py` success-criteria command. If
`fx_conversion` FAILs → `redesign_required: true` → hedge-redesign
sub-project mandated (per §32); Phase 1 paper continues for operational
validation only, the paper PnL noting the measured FX leak.

### 33.6 Implementation status

Sub-project 5 built (7-task TDD plan, all tasks review-clean):
- Task 1: `--feed {rest,csv}` + REST paper feed (reuses `recorder.sample()`)
  + `csv_feed` extracted from `_live_feed`; `--live` gate byte-identical.
- Task 2: `TraderState` +4 paper-PnL fields + field-tolerant loader.
- Task 3: 8h funding accrual + basis MTM + real `_mark_equity`.
- Task 4: paper ledger `carry_paper.csv` + 6 event logs.
- Task 5: `paper_check.py` 5-criteria verdict.
- Task 6: Oracle systemd units (paper-trader + venue recorder) + deploy README.

`carry_trader.py` `__main__` self-check: 8 OK lines
(signal/faults/reconcile/sign/tilt/venue/feed/paper-pnl), all paths exercised
offline (mocked `sample()`, simulated 8h mark, no network). `paper_check.py`
`__main__`: pass-case + DD_HALT fail-case. No live calls in any self-check.

### 33.7 Conclusion

Phase 1 ships the paper-trader as a deployable, instrumented loop: real
CoinDCX funding accrual + basis MTM on the live venue, an append-only evidence
ledger, and a data-driven 5-criteria gate to Phase 2. The deploy is
**artifact-ready** — the user runs the Oracle deploy (recorder-first, then
paper-trader, then the one-shot `venue_verify.py run`). No paper run is
executed in this environment (no Oracle host here); the 7-14d result +
definitive Phase 0 verdict are the next data points, expected from the
recorder host. The carry deploy remains NOT live — now gated behind (a) a
live Phase 0 PASS, (b) Phase 1 clean paper ≥7d on all five criteria, (c) §27's
standing verdict that carry is funding-regime-dependent, not a robust edge.
The tilt slot stays sealed `NoTilt` ([[regime-gate-tilt-sweep]], §31).

See [[funding-carry-band]] (§20 — the carry edge Phase 1 operationally
validates), [[post-conclusion-followups]] (§29 — FX-leg + cost model), §32
(the Phase 0 gate run on the same host), [[microstructure-feed-unblocked]]
(the Oracle recorder host Phase 1 deploys alongside),
[[regime-gate-tilt-sweep]] (§31 — NoTilt sealed).

## §34. Funding-extreme fade tilt sweep — 0/6 cells pass; tilt class closes negative (sub-project 6)

> §31 swept 3 regime gates × 3 assets × 2 directions = 0/18 pass → `NoTilt`.
> This section logs sub-project 6: one NEW tilt signal — a low-frequency
> funding-extreme fade (rolling-quantile decile gate + hysteresis) that targets
> §31's funding-slope churn failure (~10k flips → few). Spec:
> `docs/superpowers/specs/2026-08-25-tilt-funding-extreme-design.md`; plan:
> `docs/superpowers/plans/2026-08-25-tilt-funding-extreme.md`.

### 34.1 Thesis

Funding-rate extremes mean-revert. Fade them on the funding-receiving side:
extreme-positive `fr` → SHORT (short receives funding + perp-spot premium
reverts down); extreme-negative `fr` → LONG (long receives funding + premium
reverts up). Funding income aligns with the fade — stronger than a pure
directional bet. Named failure mode: the §27 squeeze risk (extremes persist).

### 34.2 Sweep structure + pass criterion

1 gate (`funding_extreme`) × 3 assets (BTC/ETH/SOL) × 2 fade-directions
(long-fade, short-fade) = 6 cells. Same pre-registered pass criterion as §31:
net>0 AND K=4 contiguous WF (≥3/4 folds + aggregate) AND 70/30 AND bootstrap
CI lower bound >0 (1000 resample, block=10, seed 0). Cost model §29: taker
0.059% + 5bps/side, funding mark-aligned, no TDS (naked perp). Params trained
IS 70%. §31's 18 cells not re-run.

### 34.3 Per-cell verdict table

From `reports/regime_gate_wf.log` (6 rows, appended 2026-08-25):

| asset | gate | dir | net | ci_lo | k4 | split70 | verdict | params |
|---|---|---|---|---|---|---|---|---|
| BTCUSDT | funding_extreme | long | 0.2832 | -0.1962 | True | False | FAIL | `{'w': 480, 'q': 0.9, 'q_exit': 0.8}` |
| BTCUSDT | funding_extreme | short | -0.7734 | -2.7387 | False | True | FAIL | `{'w': 480, 'q': 0.9, 'q_exit': 0.8}` |
| ETHUSDT | funding_extreme | long | 0.2683 | -0.4204 | True | False | FAIL | `{'w': 480, 'q': 0.9, 'q_exit': 0.8}` |
| ETHUSDT | funding_extreme | short | -0.5907 | -2.4017 | False | False | FAIL | `{'w': 480, 'q': 0.9, 'q_exit': 0.8}` |
| SOLUSDT | funding_extreme | long | -0.0015 | -1.0622 | False | True | FAIL | `{'w': 120, 'q': 0.9, 'q_exit': 0.8}` |
| SOLUSDT | funding_extreme | short | -0.9737 | -5.4918 | False | True | FAIL | `{'w': 120, 'q': 0.9, 'q_exit': 0.8}` |

`reports/regime_gate_pass.json` = `[]`.

### 34.4 Results narrative

All 6 cells FAIL → `reports/regime_gate_pass.json` is `[]` →
`load_tilt_signal()` returns `NoTilt` (unchanged from §31).

**Long-fade (3 cells, BTC/ETH/SOL, extreme-negative funding → LONG):** the
thesis works *weakly* in-sample on BTC and ETH — net +0.2832 / +0.2683 and
K=4 passes (≥3/4 folds + aggregate net > 0). But both fail the 70/30 split
(train captures the few extreme-negative reversion events, test doesn't) and
the bootstrap CI lower bound is negative (`-0.1962` / `-0.4204`) — the edge is
path-lucky, not robust. SOL long-fade is flat (`net=-0.0015`, K=4 fails,
split70 passes trivially on a near-zero series, `ci_lo=-1.0622`). The
funding-receive income + premium reversion is real but small, and it
concentrates in a few IS windows that the 70/30 split + bootstrap correctly
flag as not repeatable.

**Short-fade (3 cells, extreme-positive funding → SHORT):** uniformly negative
net (`-0.7734` / `-0.5907` / `-0.9737`) with deeply negative bootstrap ci_lo
(`-2.4` to `-5.5`). This is the §27 squeeze risk surfacing in the data:
extreme-positive funding **persists** during sustained squeezes, so the short
pays the directional leg while the funding income received doesn't cover it.
2/3 short cells pass split70 (BTC, SOL) — but only because both train and test
slices lose together; passing split70 on a uniformly-losing cell is not edge.

**Churn-fix verdict:** the hysteresis (`q=0.90` enter, `q_exit=0.80` exit) +
long window (`W=480` marks ≈ 160d for BTC/ETH; `W=120` ≈ 40d for SOL) DID fix
the §31 funding-slope churn failure — flip count dropped from ~10,105 to few.
Low frequency alone does not manufacture edge: the few fires don't overcome
cost on the short side (squeeze persists) and don't repeat OOS on the long
side (path-luck). The churn fix was necessary but not sufficient.

### 34.5 Conclusion

0/6 cells pass → the tilt class **closes negative** (like the order-flow class
§25/§26). `NoTilt` stands; the carry-only deploy (~5-6%/yr §27, USDT redesign
§29) remains the single standing edge. Consistent with §28 (no robust retail
perp edge at free-data resolution). The §30 paper-trader tilt slot stays
`NoTilt`. A second, structurally different funding tilt (level-quantile fade
vs §31's slope) also failing — with the churn failure explicitly fixed —
strengthens the §31 verdict from "sealed NoTilt on the gates tested" to "the
tilt class closes negative: no free-data funding signal, slope OR level,
survives real costs + path-luck guards."

See [[regime-gate-tilt-sweep]] (§31), [[funding-carry-band]] (§20),
[[carry-funding-regime-walkforward]] (§27/§28).

## §35. Opening Range Breakout (ORB) — 0 edge across all sessions (sub-project 7)

Source: Max Options Trading ORB video (https://www.youtube.com/watch?v=lZn7zVRtAWk).
US-equity ORB: mark opening-range candle high/low, break + retest → entry, stop
beyond the opposite OR edge, 2:1 target, optional failed-breakout reversal.

### 35.1 The crypto problem

ORB is a market-OPEN strategy. Crypto trades 24/7 with no bell, so "opening
range" must be redefined per session. Tested three session opens (UTC=00:00,
London=07:00, US=14:30) — the user's specific ask. Two builds compared under
real CoinDCX perp costs (maker 0.025% / taker 0.06% / 2bps slip, maker-on-limit;
no TDS — §18):

1. **Existing stub** `opening_range_breakout` (long-only, ATR-trail exit, UTC-day range).
2. **Faithful `orb_max`** (new): long+short retest entry, OR-level stop, 2:1 TP,
   failed-breakout reversal toggle, session-aware range.

### 35.2 Engine contract (two small fixes)

The backtest engine ignored `BaseStrategy.stop_loss()` (dead hook) and denied
`take_profit` to shorts. Both fixed — honor strategy stop_loss absolute level,
honor take_profit on both sides. No behavior change for existing strategies
(base returns `None`). `tests/test_core.py` 8/8 pass. `orb_max` runs as
reversion-kind cfg (`use_trailing=False` keeps the OR-level stop fixed).

### 35.3 Results (15m BTC, 2.5y, 70/30 split, MC n=500, regime-split)

Harness: `scripts/orb_backtest.py` (CSV-direct, offline). Self-check passes.

| build       | session | range_bars | full net | OOS net | OOS sh | OOS trades | mcP |
|-------------|---------|-----------|----------|---------|--------|-----------|-----|
| stub        | (UTC)   | 3-5       | -1043..-1186 | -2005..-2083 | -2.9..-3.9 | 84-114 | 0.17-0.26 |
| orb_max     | 00:00   | 3,5       | -1964,-1980 | -1962,-2037 | -3.5,-4.2 | 33,38 | 0 |
| orb_max     | 07:00   | 3,5       | -2025,-1998 | +6475,+8374 | +1.06,+1.16 | 9,3 | 0 |
| orb_max     | 14:30   | 3,5       | -2051,-1952 | +2870,+2870 | +1.16,+1.16 | 1,1 | 0 |

### 35.4 Conclusion

**No robust ORB edge in crypto under real costs, any session.**

- Stub loses on every config (OOS sharpe -2.9 to -3.9). Same fate as every
  breakout/trend strategy under real costs (§19/§30) — costs + whipsaw kill it.
- orb_max full-sample (train) loses ~-2000 on EVERY config — the dominant
  signal. The 07:00/14:30 OOS "wins" are 1-9 trades (mcP=0.0): path luck, not
  edge. `edge()` correctly returns False for all (requires ≥10 OOS trades + mcP>0.5).
- 00:00 (UTC/Asia) loses both IS and OOS.
- The dd-wall (0.20 max_drawdown gate) throttled trade counts on all runs — a
  confound, but it cuts both ways and cannot manufacture edge from a -2000 train.

The faithful video spec (shorts, retest, OR stop, 2:1, reversal) does NOT
rescue ORB in 24/7 crypto. ORB class closes negative, joining the order-flow
class (§25/§26) and tilt class (§31/§34). Carry-only (~5-6%/yr §27, USDT
redesign §29) remains the single standing edge.

Not deployed. No live/paper wiring (research verdict was the gate).

See [[orb-max-no-edge]] (§35), [[regime-gate-tilt-sweep]] (§31/§34),
[[funding-carry-band]] (§20), [[post-conclusion-followups]] (§29).

### 35.5 Expanded sweep — multi-tf / multi-asset / sessions / optimization (§35 phase 2)

User asked to extend to other timeframes + ETH/SOL + XAU (gold) and check
optimizations. Harness `scripts/orb_backtest.py` rewritten: multi-asset/tf,
**UNGATED** (max_drawdown=0 — the §35.3 gated run's dd-wall throttled trades,
a confound; ungated gives the raw pattern read), 2-phase optimization
(Phase A best session+range, Phase B sweep reversal x rr). Engine gained
risk-gate overrides on BacktestConfig (max_drawdown/max_positions/max_daily_loss).
`test_core.py` 8/8 still pass. Sessions tested: 00:00 (UTC/Asia), 01:00
(Asia-HK), 07:00 (London), 13:00 (NY-pre), 14:30 (US open).

| asset | tf | best session | rb | OOS net | OOS trades | mcP | edge flag |
|-------|----|-----------|----|---------|-----------|-----|-----------|
| BTC | 15m | 07:00 | 3 | +7145 | 25 | 0.09 | False |
| BTC | 5m  | 01:00 | 3 | +6583 | 24 | 0.73 | **True** |
| ETH | 15m | 00:00 | 2 | +5331 | 23 | 0.67 | **True** |
| SOL | 15m | 13:00 | 2 | +19483 | 28 | 0.50 | False |
| XAU | 15m | 07:00 | 2 | +15905 | 6  | 0.03 | False |

Optimizations tested: reversal toggle, rr {1.5,2,3}, range_bars {1,2,3,5},
5 sessions. Findings:
- **failed-breakout reversal fails catastrophically** on BTC5m/ETH/XAU
  (dd 0.98-0.99, PF 0.02-0.34) — the video's "12:1 bonus" does NOT transfer.
  SOL is the lone exception where reversal helped OOS (still refuted below).
- **rr is robust** (1.5/2/3 similar within a config) — RR is not the lever.
- **stub loses everywhere** (long-only ATR trail chopped to death, dd 0.5-0.99,
  OOS sharpe -3 to -16). Same fate as all trend/breakout under real costs.

### 35.6 Walk-forward rigor gate — all flags refuted as path luck

The three "edge=True"-ish flags (BTC5m 01:00, ETH15m 00:00, SOL15m 13:00
reversal) are 17-28 OOS-trade cells with PF 10-17 — the classic thin-sample
path-luck signature this project has seen before ([[multi-asset-regime-walkforward]]).
Applied the standard rigor gate (`scripts/orb_wf.py`, mirrors [[regime-gate-tilt-sweep]]:
K=4 contiguous folds + 70/30 + circular-block bootstrap CI). Pass = net>0 in
>=3/4 folds AND aggregate>0 AND 70/30 OOS>0 AND CI lo>0.

| candidate | fold1 | fold2 | fold3 | fold4 | full | CI lo | verdict |
|-----------|-------|-------|-------|-------|------|-------|---------|
| BTC 5m 01:00 retest rr=3 | -7027 | -7273 | -4491 | +21639 | -8815 | -3.74 | **FAIL** |
| ETH 15m 00:00 retest rr=2 | -4440 | +254 | -3462 | +5693 | -4638 | -1.46 | **FAIL** |
| SOL 15m 13:00 reversal rr=2 | -8852 | -7735 | -3402 | +2897 | -9752 | -5.10 | **FAIL** |

Every flag fails: folds 1-3 lose on 68-221 trades; only fold-4 (the last ~year,
17-28 trades) wins. Full-sample net negative. Bootstrap CI lower bound < 0.
The 70/30 "edge" was one lucky regime window — not edge.

### 35.7 Conclusion (expanded, definitive)

**No robust ORB edge in crypto or gold perp, any timeframe / session / asset /
mode, under real CoinDCX perp costs.** The faithful video spec (shorts, retest,
OR-level stop, 2:1 TP, failed-breakout reversal) and its optimizations (rr,
session, range_bars) do not survive K-fold walk-forward + bootstrap CI. Every
"edge=True" 70/30 flag refuted as last-year OOS path luck. The failed-breakout
reversal actively destroys capital (dd ~0.99) — the video's headline "12:1"
play does not transfer to 24/7 perp.

ORB class closes negative, definitively (rigor-gated), joining order-flow
(§25/§26) and tilt (§31/§34). Strengthens §28: no robust retail perp edge at
free-data resolution across yet another structurally different class. Carry-only
(~5-6%/yr §27, USDT redesign §29) remains the single standing edge.

Engine improvements kept (no regression): `BaseStrategy.stop_loss()` honored
(absolute level), `take_profit()` honored on shorts, BacktestConfig risk-gate
overrides. `orb_max` + `scripts/orb_backtest.py` + `scripts/orb_wf.py` retained
as reproducible research artifacts. NOT deployed; no live/paper wiring.

See [[orb-max-no-edge]] (§35), [[regime-gate-tilt-sweep]] (§31/§34),
[[multi-asset-regime-walkforward]] (path-luck precedent), [[post-conclusion-followups]] (§29).

### 35.8 Regime-gate + visit-count rescue attempt — 0/10 survives (§35 phase 3)

User asked: can regime-gating or a "put your order where your stop goes, count
visits" filter rescue ORB? Three hypotheses tested via `scripts/orb_regime.py`
(regime attribution + per-regime K-fold consistency) on the 3 thin-sample
"edge=True" candidates, 10 configs total:

- **H1 trend gate** (`regime_sma=200` — engine built-in: longs only above SMA,
  shorts only below; zero new code): no rescue. SOL reversal → all 4 folds turn
  negative (-7254/-4468/-7006/-6942); the gate removes even the fold-4 luck.
  ETH → folds 2&4 win (+6454/+7337) but folds 1&3 lose, full -5157, still FAIL.
- **H3 visit-count** (`min_visits` on orb_max — count pre-break touches of the
  stop level; new param + self-check): no rescue. min_visits 1/2 leave the
  verdict unchanged (SOL identical to baseline; ETH same fold-4-luck pattern).
- **H2 per-regime attribution** (ex-ante trend dir via prior-day SMA x vol tier
  via rolling ATR percentile): NO regime has >=10 trades + net>0 + >=3/4 folds
  positive. The textbook ORB regime (ETH trend=up vol=high, 58 trades) nets
  +658 but only 1/4 folds — all profit is fold-4 (+2065); folds 1-3 lose.
  Win rates 11-24% across regimes. The "profitable regime" was fold-4 path
  luck, not a regime-conditional edge.

| config | H1 folds | full | ci_lo | H1 | H2 |
|--------|----------|------|-------|----|----|
| BTC 5m baseline | -7027/-7273/-4491/+21639 | -8815 | -3.74 | FAIL | False |
| BTC 5m +regime_sma200 | -3961/-6211/-3938/-1547 | -8771 | -2.87 | FAIL | False |
| BTC 5m +min_visits1 | -5517/-5858/-6022/+954 | -9191 | -3.60 | FAIL | False |
| ETH 15m baseline | -4440/+254/-3462/+5693 | -4638 | -1.46 | FAIL | False |
| ETH 15m +regime_sma200 | -6089/+6454/-2573/+7337 | -5157 | -1.60 | FAIL | False |
| ETH 15m +min_visits1 | -4158/-420/-2425/+5659 | -5286 | -1.73 | FAIL | False |
| ETH 15m +min_visits2 | -4538/+232/-1959/+6861 | -4647 | -1.62 | FAIL | False |
| SOL 15m reversal baseline | -8851/-7735/-3402/+2897 | -9752 | -5.10 | FAIL | False |
| SOL 15m reversal +regime_sma200 | -7254/-4468/-7006/-6942 | -9876 | -5.16 | FAIL | False |
| SOL 15m reversal +min_visits1 | -8851/-7735/-3402/+2897 | -9752 | -5.10 | FAIL | False |

### 35.9 How ORB could be deployed (if it ever passed the gate) — NOT triggered

The plumbing exists and was verified, so the deploy path is documented for
completeness — but the research gate (edge) is NOT met, so none of this fires:
- `orb_max` is registered in `app/strategy/registry.py` → `get_strategy("orb_max", ...)`.
- Trend regime gate = engine `BacktestConfig.regime_sma` (already wired; tested
  above). A richer ex-ante regime filter would be a `regime_filter` param on
  orb_max gating entry by (trend_dir, vol_tier) — but H2 showed no such filter
  has consistent edge, so it would be fitting noise.
- Live/paper: add `orb_max` to `rank.py` STRATEGIES + boot the existing paper-
  trader (`scripts/carry_trader.py` pattern) with it. No new live infra needed.
- The §35 verdict blocks all of this: no edge = no deploy.

### 35.10 Final conclusion (sub-project 7 closed)

ORB is refuted across every dimension tested: 2 timeframes (5m/15m), 4 assets
(BTC/ETH/SOL/XAU-gold), 5 sessions, 2 modes (retest/reversal), RR 1.5-3,
range_bars 1-5, trend regime gate (regime_sma), vol-tier regime, and visit-count
filter. 0/10 rescue configs survive K-fold walk-forward + bootstrap CI. The
"profitable regime" hypothesis (the project's recurring "no robust edge, but
maybe a conditional one" pattern) is refuted for ORB: the only positive cells
are fold-4 (last-year) path luck, not a regime-conditional edge — win rates stay
11-24% even in the textbook uptrend+high-vol regime.

ORB class closes negative, definitively. Joins order-flow (§25/§26), tilt
(§31/§34), and now breakout/ORB. Strengthens §28 (no robust retail perp edge at
free-data resolution) across a fourth structurally different class. Carry-only
(~5-6%/yr §27, USDT redesign §29) remains the single standing edge.

Retained (no regression, test_core 8/8): engine stop_loss/short-TP/risk-gate
overrides; `orb_max` (+ min_visits); `scripts/orb_backtest.py`,
`scripts/orb_wf.py`, `scripts/orb_regime.py` as reproducible artifacts. NOT
deployed; no live/paper wiring.

See [[orb-max-no-edge]] (§35), [[regime-gate-tilt-sweep]] (§31/§34 — same
regime-gate class refuted), [[multi-asset-regime-walkforward]] (path-luck
precedent), [[post-conclusion-followups]] (§29).

### 35.11 Higher timeframe test (1h, 4h) — thinner = more path luck, 0 edge

User asked to try higher TFs. 1d skipped (1 bar/day, no intraday range = no
session ORB). 1h and 4h resampled from 15m base (`scripts/orb_backtest.py`
gained `load_tf` resample; 2.5y BTC/ETH/SOL, ungated, real perp costs).

Prediction confirmed: higher TF = fewer trades = MORE path luck, not less.

| TF | asset | best cell | OOS tr | OOS net | OOS sh | mcP | edge |
|----|-------|-----------|-------:|--------:|-------:|----:|------|
| 1h | BTC | 13:00 rb=1 rr=3 | 3 | +7811 | 1.17 | 0.69 | False |
| 1h | ETH | 07:00 rb=1 rr=1.5 | 3 | +8138 | 1.19 | 0.69 | False |
| 1h | SOL | 07:00 rb=1 rr=3 | 3 | +3738 | 1.18 | 0.69 | False |
| 4h | BTC | 07:00 rb=1 rr=2 | 2 | +3887 | 1.21 | 0.41 | False |
| 4h | ETH | 07:00 rb=1 rev rr=1.5 | 9 | +2446 | 0.86 | 0.70 | False |
| 4h | SOL | 07:00 rb=1 rr=2 | 19 | +3182 | 0.83 | 0.20 | False |

- 1h: every "best" cell = 3 OOS trades. Pure 3-trade lottery. Reversal destroys
  capital (dd 0.92-0.94) as at lower TFs.
- 4h: sessions 13:00/14:30 = 0 trades (4h bars don't align to those opens — the
  opening range never forms). Closest-to-flag SOL 4h (19 trades, +3182) fails
  mcP=0.20; ETH 4h reversal (9 trades) fails the >=10 trade count.
- No cell reaches the edge bar (`oos_net>0 AND oos_sharpe>0 AND oos_trades>=10
  AND mcP>0.5`). K-fold rigor gate not even run — flagged cells are 2-19 trades
  TOTAL; K-fold = 0-5 trades/fold = pure noise. Rigor fails before it starts.

ORB refuted across 4 timeframes now (5m/15m/1h/4h). Higher TF makes it WORSE,
not better — the "edge" was always thin-sample fold-4 luck, and higher TF
thins the sample further. §35.10 verdict stands.

### 35.12 Recent-window stats (1y, 3m) — more edge=True flags, ALL fail rigor

User asked for past-1y and past-3m stats. Short windows flag MORE edge=True
cells than full-sample — and that is exactly why they are path luck, not edge.

**Selection leak (harness):** `score_grid` sorts by `oos_net` — "best session"
is picked by *test-window* performance, not train. So edge=True is selected on
the very window being judged. A 1y window IS fold-4 (the lucky last-year fold
refuted in §35.7). edge=True on 1y = the path luck itself.

1y edge=True flags (7 cells): BTC/ETH/SOL 15m, BTC 5m, BTC/SOL 1h, BTC 4h.
K-fold rigor gate (K=4 quarterly folds + 70/30 + bootstrap CI) run on each:

| cell (1y) | folds net | CI lo | verdict |
|-----------|-----------|------:|---------|
| BTC 15m 07:00 rb=3 | -501/+2817/+52/+2825 | -0.18 | FAIL |
| ETH 15m 00:00 rb=3 | -190/-645/+1270(1tr)/+3953(9tr) | -0.15 | FAIL |
| BTC 5m 01:00 rb=3 | +3880/-3775(60tr)/+2978(2tr)/+7102 | -0.15 | FAIL |
| BTC 1h 07:00 rb=2 | -447/+2820(3tr)/-579/+2343 | -0.15 | FAIL |
| SOL 1h 00:00 rb=1 | +97/+898/-499/+3268 | -0.23 | FAIL |
| SOL 15m 01:00 rb=2 | +2454/+4416(4tr)/+213/+2894 | -0.19 | FAIL |
| BTC 4h 00:00 rb=1 | -55/+791(2tr)/-128/+1757 | -0.10 | FAIL |

**0/7 survive.** Every CI lower bound < 0. Fold pattern is the tell: single-fold
wins on 1-9 trades, losing/flat folds on 24-60 trades. BTC 5m: fold 2 loses
-3775 on 60 trades while fold 4 wins +7102 on 11 — variance, not edge.

3m window (1 quarter): even thinner. Only ETH 15m 13:00 (14 trades, mcP 0.8)
flags edge=True; rest edge=False on 5-14 trades. K-fold on 3m = monthly folds of
~3-4 trades = noise; not runnable. A 3-month/14-trade lottery is not a strategy.

**Conclusion:** recent windows refute ORB *harder*, not rescue it. Short windows
inflate path luck (fewer trades = more variance = more lucky cells pass mcP>0.5)
and the selection leak picks the luckiest. The rigor gate — built for exactly
this — catches all 7. §35.10 verdict stands: no ORB edge, any window, any TF.

### 35.13 ENGINE BUG: short take_profit never passed — §35 short-side corrupted; corrected recent-window results

A real engine bug was found while answering "recent win/loss counts."
`app/backtest/engine.py` line 190 hardcoded `take_profit=None` for shorts,
ignoring the strategy's `take_profit` (the §35 phase-1 "fix" computed `tp` but
never passed it to the short Position). Effect: every short that ran into
profit held until stop_loss or end-of-data — never taking its 2:1 target. One
short on BTC 15m 07:00 rb=3 opened 2025-10-27 at 115077 and rode BTC's -45%
drop to 2026-07-31 (9 months), force-closed "eod" at 62872 for +4106 — a single
buggy trade that manufactured the entire "+3238 net, edge=True" flag.

Fix: line 190 `take_profit=None` -> `take_profit=tp`. `_manage` is already
symmetric (line 270-276: `tp_hit = row["low"] <= tp` for shorts). test_core 8/8.

**Impact: the §35.12 "edge=True" recent-window flags were ALL this bug.** With
the fix, re-run win/loss on every flagged cell. The "current regime works"
story was a bug — ORB is a clean cost-bleed, not even path luck.

Corrected 1y (best cells, ungated, real perp costs):

| cell (1y) | trades | wins | losses | win% | avg_win | avg_loss | net | Q1 | Q2 | Q3 | Q4 |
|-----------|-------:|-----:|-------:|-----:|--------:|---------:|----:|---:|---:|---:|---:|
| BTC 15m 07:00 rb=3 | 329 | 137 | 192 | 41.6 | 83 | -81 | **-4130** | -1301 | -2471 | +209 | -567 |
| ETH 15m 00:00 rb=3 | 313 | 129 | 184 | 41.2 | 117 | -96 | **-2529** | -536 | -290 | -1453 | -251 |
| SOL 15m 01:00 rb=2 | 336 | 144 | 192 | 42.9 | 113 | -97 | **-2397** | +275 | -884 | -1507 | -281 |
| BTC 5m 01:00 rb=3 | 338 | 129 | 209 | 38.2 | 75 | -75 | **-5937** | -1806 | -1976 | -1088 | -1066 |
| BTC 1h 07:00 rb=2 | 242 | 100 | 142 | 41.3 | 86 | -85 | **-3482** | -416 | -1562 | -1252 | -251 |
| SOL 1h 00:00 rb=1 | 200 | 84 | 116 | 42.0 | 101 | -95 | **-2474** | +9 | -486 | -1077 | -920 |
| BTC 4h 00:00 rb=1 | 118 | 58 | 60 | 49.2 | 103 | -96 | +231 | +431 | -615 | -167 | +582 |

6 of 7 cells net negative over 1y. Win% 38-43%. The "2:1 RR" is theoretical:
realized avg_win/avg_loss ≈ 1.0-1.3 (TP hits at exactly 2:1, but stops + fees
+ slippage compress the realized ratio to ~1.1). At 41% win and 1.1 realized
RR, ORB is a net cost-bleed. The lone positive (BTC 4h, +231 on 118 trades =
+0.2%/trade) is statistical flat: bootstrap CI -0.18 to 0.24, k4_pass=False.

Corrected 3m (last quarter 2026-05..07): all 3 cells net negative (ETH 13:00
-101, BTC 14:30 -371, SOL 00:00 -786); only the last ~3 weeks (Q4) positive on
tiny samples (13-23 trades), preceded by 3 losing quarters.

K-fold (corrected) confirms clean loss, not path luck:
- BTC 15m 07:00: folds -1396/-2825/+353/-822, CI **-0.92 to -0.09** (entire CI < 0).
- SOL 15m 01:00: folds +229/-848/-1523/-376, CI -0.68 to 0.12, k4_pass=False.
- BTC 4h 00:00: folds +131/-314/-2/+366, CI -0.18 to 0.24 (flat).

**Answer to "the current regime works until it doesn't":** it was never
working. The "working" was a single buggy short riding a 9-month trend to
end-of-data. With take_profit honored, ORB loses in 6/7 cells over the last
year and all recent cells lose over the last 3 months. Win rate 38-43%, realized
RR ~1.1 (not 2:1) — a steady cost-bleed, not a regime-conditional edge that
"works until it doesn't." There is no profitable recent regime to deploy into.

The §35 no-edge verdict STRENGTHENS (the bug made shorts look better than
reality; fixing it makes ORB worse). All prior §35 short-side numbers (reversal
mode especially) were computed with this bug and are conservative in the
no-edge direction — the verdict stands a fortiori.

### 35.14 Exit-method optimization sweep — 0/30 rescue; problem is entry, not exit

User asked to try trailing stop + fib-level TP, and other SL/TP methods. Built
exit-management params into `orb_max` (`tp_mode` rr|fib|trail, `fib`, `sl_mode`
or|atr, `atr_mult`) and swept 10 exit configs on the 3 best 15m cells (BTC
07:00, ETH 00:00, SOL 01:00), last 1y, ungated, real perp costs, K-fold rigor
inline (`scripts/orb_exits.py`).

| config | BTC net | ETH net | SOL net | effect |
|-------|--------:|--------:|--------:|--------|
| E1 ORstop+rr2 (base)       | -4130 | -2529 | -2397 | baseline (post-bug) |
| E2 ORstop+fib1.618        | -3542 | -2670 | -2140 | win% 48-50 (best) but net still neg |
| E3 ORstop+fib2.618        | -4225 | -2766 | -2731 | win% 33-35 -- target too far |
| E4 ORstop+fib3.618        | -2963 | -2173 | -3142 | win% 26-30 -- fewer wins, smaller |
| E5 +fib2.618+ATRtrail2    | -6016 | -4435 | -4708 | trailing WORSE, win% 28-33, dd 0.6 |
| E6 +fib2.618+ATRtrail3    | -5822 | -4211 | -4231 | same, trail3 marginally better |
| E7 +BE@1R+trail2          | -6016 | -4435 | -4708 | == E5 (BE subsumed by trail) |
| E8 +partial1.618+trail2   | -6698 | -5910 | -6229 | WORST -- bank half wins, full losses |
| E9 pure ATR trail2 (no TP) | -6251 | -4612 | -5092 | no cap = whipsaw bleed, win% 27-32 |
| E10 ATRstop1.5+fib2.618+tr2| -7084 | -5560 | -4669 | wider stop = bigger losses, dd 0.71 |

**0/30 pass K-fold rigor (all CI lo < 0, all k4_pass=False).** None net positive.

Findings:
- Fib TP: arbitrary in 24/7 crypto (no market open, no real "extension"). Higher
  fib shrinks win% (target harder to reach); lower fib shrinks avg_win. The RR
  compression (entry gaps above the retest -> stop distance grows, TP distance
  shrinks, realized RR ~1.1 not 2.0) is structural and unfixable from the exit.
- Trailing/partial/ATR-stop all INCREASE the cost-bleed: more turnover (335 ->
  451 trades on partial), higher dd (0.47 -> 0.71), whipsaw in chop. Trailing
  helps in trends but ORB breaks happen in chop where it gets cut.
- Break-even@1R is redundant once a trail ratchets (E7 == E5).
- Best win% of any config (E2 fib1.618, 48-50%) still nets negative -- because
  the win rate, not the payoff, is the binding constraint.

**Diagnosis:** ORB's problem is the ENTRY signal (breakouts mostly fail, 38-43%
win), not the exit. No SL/TP method recovers a sub-50% win rate with realized
RR ~1.1 under real perp costs. Exit optimization is refuted. The §35.10 verdict
stands -- the edge cannot be manufactured from the exit side.

Engine/strategy retained (no regression, test_core 8/8 + orb_max self-check):
`orb_max` gained `tp_mode`/`fib`/`sl_mode`/`atr_mult`; `scripts/orb_exits.py` is
a reproducible artifact. NOT deployed.

### 35.15 Exit sweep extended to XAU (gold) — same verdict, 0/40 total

User asked about ETH/SOL/XAU for the exit sweep. ETH and SOL were already in
§35.14 (BTC 07:00, ETH 00:00, SOL 01:00). XAU best 15m cell (00:00 rb=5) added;
re-ran the full 10-config sweep across all 4 cells (40 configs total).

XAU 15m 00:00 rb=5, last 1y:

| config | trades | win% | net | dd | CI lo | verdict |
|--------|-------:|-----:|----:|---:|------:|---------|
| E1 ORstop+rr2 | 270 | 44 | -2448 | 0.35 | -0.71 | fail |
| E2 +fib1.618 | 287 | 46 | -3365 | 0.39 | -0.80 | fail |
| E3 +fib2.618 | 236 | 40 | +47 | 0.31 | -0.45 | fail (fold-4 luck) |
| E4 +fib3.618 | 179 | 34 | +982 | 0.28 | -0.34 | fail (fold-4 luck) |
| E5 +fib2.618+trail2 | 336 | 26 | -6150 | 0.62 | -1.19 | fail |
| E6 +fib2.618+trail3 | 326 | 30 | -5683 | 0.58 | -1.15 | fail |
| E7 +BE1+trail2 | 336 | 26 | -6150 | 0.62 | -1.19 | fail (==E5) |
| E8 +partial1.618+trail2 | 393 | 35 | -6586 | 0.66 | -1.29 | fail |
| E9 pure ATR trail2 | 335 | 26 | -6201 | 0.62 | -1.21 | fail |
| E10 ATRstop1.5+fib2.618+tr2 | 336 | 26 | -8307 | 0.83 | -2.15 | fail |

**0/40 pass.** XAU mirrors crypto: trailing/partial/ATR-stop all worse than the
fixed baseline. The only configs that nudge positive (E3 +47, E4 +982) are
fold-4 path luck -- the 2026 gold rally hits the 3.618 target while chop
quarters stop out; folds 1-2 lose -1400, fold 4 wins +2889/+3330, CI lo < 0.
That is the "rare big win compensates for many small losses" signature, not a
regime-conditional edge -- K-fold refutes it.

XAU baseline win% 44%, same entry problem as BTC/ETH/SOL (breakouts mostly fail).
Gold's larger opening ranges (rb=5) don't change the win rate; the higher-fib
TPs just let the rare trending sessions reach target, which is fold-luck not
edge. The §35.14 diagnosis holds across all 4 assets: ORB's binding constraint is
the entry (38-44% win), not the exit; no SL/TP method recovers it under real
costs. Exit optimization refuted, 0/40.

### §35.16 — NY + Asia session-open only (rescue attempt 8)

**Question (user):** what if ORB is tested *only* on New York and Asia session
opens (drop London)? NY liquidity / Asia range theory might be where ORB works.

**Setup.** Restricted the session grid to Asia (00:00, 01:00) + NY (13:00,
14:30), dropped London 07:00. Re-picked best cell per asset on the restricted
grid (1y, scripts/orb_backtest.py `--sessions`), then ran the full 10-exit
sweep (E1-E10) on those NY/Asia-only cells with K-fold rigor
(scripts/orb_exits.py `--ny-asia`).

Best NY/Asia cells (1y): BTC 00:00 rb=5 (Asia — flipped from London 07:00),
ETH 13:00 rb=3 (NY-pre — flipped from Asia 00:00, selection leak), SOL 01:00
rb=3 (Asia), XAU 00:00 rb=5 (Asia, unchanged — was already global best).

**Results: 0/40 pass.** reports/orb_exits_nyasia.log.

| asset | cell | best exit | net | folds | CIlo | verdict |
|-------|------|-----------|-----|-------|------|---------|
| BTC | 00:00 rb=5 | E2 fib1.618 | -2533 | -702,-2007,-522,723 | -0.69 | fail |
| ETH | 13:00 rb=3 | E4 fib3.618 | +2536 | 1514,-301,4,1099 | -0.20 | fail |
| SOL | 01:00 rb=3 | E1 rr2 | -204 | 157,-693,-282,739 | -0.44 | fail |
| XAU | 00:00 rb=5 | E4 fib3.618 | +982 | -1398,-1423,1071,3330 | -0.34 | fail |

**Closest call.** ETH 13:00 (NY) E1 base ORstop+rr2: net +1294, 3/4 folds
positive [821,-883,734,840] — the only cell to clear the k4 gate — but bootstrap
CIlo=-0.21 <0 → fail. This is exactly the ETH "edge=True" flag from the
restricted grid (mcP=0.56, OOS +1078): selection picked NY 13:00 by OOS net,
fold-4 luck pushed 3/4 folds positive, but the circular-block bootstrap sees
the negative fold-2 and the thin per-trade edge → CI straddles zero. Path luck,
not edge — the CI gate is what kills it, as designed.

**Diagnosis unchanged.** NY+Asia restriction does not rescue ORB. Dropping
London removes BTC's only decent cell (07:00 was its global best) and forces BTC
onto a worse Asia cell (-2533 vs -4130 is just less bad). ETH's "improvement"
(+1294 vs -2529) is selection-on-OOS leak + fold-4 luck, refuted by CI. Exit
methods track the §35.14 pattern exactly: trailing/partial/ATR-stop all worsen
net and dd (whipsaw in chop); higher-fib TPs lower win% but let fold-4 trend
bars reach target (XAU E4 +982 on fold-4 +3330, folds 1-2 deeply negative).
Entry remains the binding constraint (win% 34-53, mostly <50).

**Verdict.** ORB refuted on NY+Asia-only sessions, 0/40 pass K-fold rigor.
Joins the full-session (0/40, §35.14/15), higher-TF (§35.11), recent-window
(§35.12), regime-gate + visit-count (§35.8-10), and engine-bug-corrected
(§35.13) refutations. ORB class closed negative across every session subset
tested. Carry-only (~5-6%/yr §27/§29) remains the single standing edge.

### §35.17 — ORB live paper trader (observation, not deployment)

**User decision:** paper-trade ETH + gold ORB despite §35.16 0/40 K-fold fail
(CIlo<0). Rationale: observe out-of-sample before any real money; "see what
happens." Research verdict unchanged — this is observation, not deployment.

**Built:** `scripts/orb_paper.py` — bar-driven live paper runner (NOT the carry
funding/tick loop). Binance USDT-M perp public REST klines
(`fapi.binance.com/fapi/v1/klines`), 15m, polled every 60s, acts only on CLOSED
candles (no look-ahead). One position per asset, single-position model mirroring
`engine.py:163`. Reuses `orb_max` (generate_signals + stop_loss/take_profit)
causally — signal at bar i computed on `df.iloc[:i+1]` only.

**Config (§35.16 best NY/Asia cells, exit E1 rr2 OR-stop):**
- ETHUSDT 13:00 rb=3 (NY)
- PAXGUSDT 00:00 rb=5 (Asia gold)

**Costs/sizing:** real perp costs (maker 0.025%/taker 0.06%/2bps slip each side,
taker both sides = market entry/exit), lev 3, $200 notional/trade, $1000 paper
capital, 25% DD flatten+halt. Honest paper PnL, not optimistic.

**Ledger/state:** `reports/orb_paper.csv` (ts,sym,event,price,qty,pnl,equity —
events ENTER_LONG/SHORT, EXIT_TP/SL/DD, DD_HALT), `reports/orb_paper_state.json`
(per-asset pos/equity/peak/halted, survives restart). Separate from carry
ledger. Carry's `paper_check` criteria don't apply (funding_nonneg) — orb-
specific check deferred; first observe ≥7d raw.

**Deploy:** `deploy/orb-paper.service` (systemd, Oracle, 24/7 alongside carry).

**Self-check:** `python -m scripts.orb_paper demo` — long retest entry, TP exit,
short entry + SL exit, state round-trip, PnL = gross - round-trip cost. PASS.
Live smoke (real klines, last 40 bars): ETH ENTER_LONG @2481.56 → EXIT_SL
@2453.0 (-2.62, cost-bleed as predicted); PAXG no signal in window. test_core 8/8.

**Expectation:** per §35.16, CIlo<0 → expect steady cost-bleed, not edge. Paper
will show whether fold-3/4 regime continues out-of-sample or reverts to the
negative mean. Either outcome is informative; neither changes the research
verdict (paper = observation, comp4 gate is carry-only).

### §35.18 — Retrace-depth + sub-1 RR (Instagram reel variant, DEFINITIVE)

User shared an Instagram reel (alphazone.ai, DYfw365ik_K) showing a RoboQuant-
coded ORB bot with a "beautiful" 1y equity curve. Extracted via Whisper
transcript: same ORB template as orb_max (session-open range, break, wait for
retrace, OR-level stop, RR target), two wrinkles vs what §35 had swept:
(a) entry on a DEEP RETRACE into the range (reel: 40% of range) instead of the
edge-touch retest, (b) a sub-1 RR target (reel: 0.8R).

**Test:** added `retrace_pct` param to orb_max (entry AT the deep-retrace touch,
no close-back filter; 0.0 = legacy edge-touch retest). Swept retrace_pct
{0.25, 0.4, 0.5} x rr {0.8, 1.0, 1.5} on the 4 NY+Asia best cells (§35.16),
last 1y, K-fold (K=4) + circular-block bootstrap CI gate
(scripts/orb_retrace.py, log reports/orb_retrace.log).

**Result: 0/36 pass.** Every config net negative (-3218 to -8227), every CIlo
< 0 (-0.85 to -2.30). Deep retrace is monotonically WORSE than the edge-touch
retest it replaces: more trades (deeper trigger fires more often) at lower win%
(BTC 41% -> 24% as retrace deepens 0.25 -> 0.5; XAU worst, dd up to 0.83).
Sub-1 RR (0.8) does not rescue: win% rises a few points but stays 31-45%, far
below the ~57%+ breakeven sub-1 RR needs under real taker costs. SOL fold-1
gains (+1763 to +3567 across retrace0.5 rows) are the same single-fold luck
pattern K-fold exists to kill.

**Verdict:** the reel's edge is an unknown-instrument, no-stated-costs,
single-window TradingView curve — overfit showcase. Ported faithfully and run
through the rigor gate, the variant fails harder than the base. The ORB class
is now refuted across entry style (edge-touch retest, deep retrace, reversal),
exit method (rr/fib/trail/partial/BE/ATR-stop, rr 0.8-3.0), session (5 opens,
NY+Asia subsets), asset (BTC/ETH/SOL/XAU), and TF (5m-4h). No corner left.
§35 closed. Carry-only stands.

### §35.19 — Close-entry + breakout-strength filters (prop-firm reel, 0/36)

Second Instagram reel (DZvAMYZA1ae): ORB with entry AT the breakout-bar close
(no retest), plus per-signal strength filters (relative volume, ATR floor) to
trade only "strong" breaks. Distinct from §35 phase-3 slow regime gates
(SMA200 trend x vol tier) — these filter the breakout bar itself.

**Test:** orb_max gained `entry_mode` (retest|close), `min_relvol` (bar vol /
20-bar mean), `min_atr_pct` (ATR14/close floor); a blocked fire does not
consume the session. Swept rv {0, 1.5, 2.0} x atr {0, 0.002, 0.004} on the 4
NY+Asia best cells (§35.16), 1y, K-fold + bootstrap-CI gate
(scripts/orb_filters.py, log reports/orb_filters.log).

**Result: 0/36 pass.** BTC / SOL / XAU: all cells net-negative (best BTC
-2343 at rv2.0 — filters cut losses but never turn the sign). **ETH 13:00
rb=3 is the closest cell in all of §35**: rv2.0+atr0 net +3573, win% 55,
dd 0.12, 4/4 folds positive [1408, 90, 745, 1052] — clears k4 AND net>0,
killed only by CIlo = -0.06. All 9 ETH cells net-positive (+1241..+3573);
all CIlo in [-0.23, -0.06]. The filters + close entry genuinely improve ETH
(win% 38-43 -> 48-55, dd 0.4 -> 0.11), but ~300 trades/1y with
bootstrap-resampled paths still crossing zero is NOT proof of edge — the
verdict is indeterminate, not refuted, on this one cell.

**Action:** research gate stands (0 passes). ETH close/rv2.0 cell promoted to
LIVE-FORWARD OBSERVATION via orb_paper (see §35.17 paper infra) — out-of-sample
accrual resolves what the bootstrap cannot. No capital commitment; comp-4 gate
unchanged (carry-only).
