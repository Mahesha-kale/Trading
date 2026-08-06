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
