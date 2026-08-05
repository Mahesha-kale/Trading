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
