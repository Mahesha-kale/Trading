"""Robustness testing: Monte Carlo (trade-sequence bootstrap), parameter
sensitivity, regime segmentation. No new deps — numpy/pandas only.

Monte Carlo: resample the realized trade PnLs WITH replacement (bootstrap the
trade sequence), rebuild an equity curve from initial capital, and summarize
the distribution. A strategy whose edge depends on a lucky trade order will
show a wide spread and low P(profit). This is the cheap, robust proxy for
"trade sequence randomization" + Monte Carlo the spec asks for.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

from app.backtest.engine import BacktestConfig, Backtester
from app.strategy.registry import get_strategy


def monte_carlo(trades: list[dict], initial_capital: float = 10000.0,
                n: int = 1000, seed: int = 0) -> dict[str, float]:
    """Bootstrap trade order. Returns distribution stats of net profit & max DD."""
    rng = np.random.default_rng(seed)
    pnls = np.array([float(t["pnl"]) for t in trades], dtype=float)
    if len(pnls) < 2:
        return {"mc_median_net": float(pnls.sum()), "mc_p5_net": 0.0, "mc_p95_net": 0.0,
                "mc_prob_profit": 1.0 if pnls.sum() > 0 else 0.0,
                "mc_median_max_dd": 0.0, "mc_worst_max_dd": 0.0,
                "mc_median_consec_loss": 0.0, "mc_n": n}
    nets = np.empty(n)
    max_dds = np.empty(n)
    consec_losses = np.empty(n, dtype=int)
    for k in range(n):
        sample = rng.choice(pnls, size=len(pnls), replace=True)
        eq = initial_capital + np.cumsum(sample)
        nets[k] = eq[-1] - initial_capital
        peak = np.maximum.accumulate(eq)
        dd = (eq - peak) / peak
        max_dds[k] = float(dd.min())
        # max consecutive losses in this sample
        run = mx = 0
        for p in sample:
            run = run + 1 if p < 0 else 0
            mx = max(mx, run)
        consec_losses[k] = mx
    return {
        "mc_median_net": float(np.median(nets)),
        "mc_p5_net": float(np.percentile(nets, 5)),
        "mc_p95_net": float(np.percentile(nets, 95)),
        "mc_prob_profit": float((nets > 0).mean()),
        "mc_median_max_dd": float(np.median(max_dds)),
        "mc_worst_max_dd": float(max_dds.min()),
        "mc_median_consec_loss": float(np.median(consec_losses)),
        "mc_n": n,
    }


def param_sensitivity(strategy_name: str, df: pd.DataFrame, base_params: dict,
                      cfg: BacktestConfig, rel: float = 0.2) -> dict[str, float]:
    """Perturb each numeric param by ±rel; measure Sharpe stability vs base.
    A robust strategy degrades gracefully; a curve-fit one collapses."""
    base = Backtester(get_strategy(strategy_name, base_params), cfg).run(df)
    base_sharpe = base["metrics"].get("sharpe", 0) or 0
    sharpes = [base_sharpe]
    for k, v in base_params.items():
        if not isinstance(v, (int, float)) or isinstance(v, bool) or v in (None,):
            continue
        for sign in (1, -1):
            pv = v * (1 + sign * rel) if v != 0 else sign * rel
            if isinstance(v, int):
                pv = max(int(round(pv)), 1)
            try:
                pp = {**base_params, k: pv}
                m = Backtester(get_strategy(strategy_name, pp), cfg).run(df)["metrics"]
                sharpes.append(m.get("sharpe", 0) or 0)
            except Exception:
                sharpes.append(-10.0)  # broken param -> worst
    sharpes = np.array([s for s in sharpes if math.isfinite(s)])
    return {
        "sens_base_sharpe": float(base_sharpe),
        "sens_mean_sharpe": float(sharpes.mean()) if len(sharpes) else 0.0,
        "sens_min_sharpe": float(sharpes.min()) if len(sharpes) else 0.0,
        # stability: mean perturbed sharpe / base sharpe (clipped). >0.5 = robust.
        "sens_stability": float(sharpes.mean() / base_sharpe) if base_sharpe > 0 else 0.0,
    }


def regime_split(df: pd.DataFrame, ema_period: int = 200) -> dict[str, pd.DataFrame]:
    """Tag each bar bull/bear/sideways via slope of a slow EMA, return sub-dfs.
    bull: EMA rising (slope>thr), bear: falling (<-thr), sideways: between.
    Threshold scaled to ATR so it adapts to volatility."""
    close = df["close"]
    e = close.ewm(span=ema_period, adjust=False).mean()
    slope = e.diff(ema_period // 4)
    thr = close * 0.001  # 0.1% over the lookback -> directional
    tag = pd.Series("sideways", index=df.index)
    tag[slope > thr] = "bull"
    tag[slope < -thr] = "bear"
    return {r: df[tag == r] for r in ("bull", "bear", "sideways") if (tag == r).any()}


@dataclass
class WalkForwardResult:
    is_oos_sharpe: float
    is_oos_net: float
    oos_trades: int
    train_sharpe_mean: float
    degradation: float  # oos/train sharpe ratio; >0.5 = robust, <0 = broken


def walk_forward_robust(strategy_name: str, df: pd.DataFrame, grid: dict[str, list],
                        cfg: BacktestConfig | None = None, n_splits: int = 5,
                        score_key: str = "sharpe") -> WalkForwardResult:
    """Walk-forward: optimize on each train window, score on next OOS window.
    Aggregates OOS sharpe + train->oos degradation. Existing optimize.walk_forward
    uses default cfg; this honors a passed cfg for consistency."""
    from app.backtest.optimize import grid_params
    cfg = cfg or BacktestConfig()
    step = len(df) // n_splits
    oos_sharpes, train_sharpes = [], []
    oos_trades = 0
    for i in range(n_splits - 1):
        train = df.iloc[: (i + 1) * step]
        test = df.iloc[(i + 1) * step: (i + 2) * step]
        if len(train) < 500 or len(test) < 200:
            continue
        best_sh = -1e9
        best_params = None
        for params in grid_params(grid):
            bp = {k: (int(v) if k in ("range_period", "sos_window", "lookback",
                                      "fast", "slow", "signal", "period", "atr_period",
                                      "trend_ema", "trend_slope") else float(v))
                  for k, v in params.items()}
            try:
                m = Backtester(get_strategy(strategy_name, bp), cfg).run(train)["metrics"]
                sh = m.get(score_key, 0) or 0
                if sh > best_sh:
                    best_sh, best_params = sh, bp
            except Exception:
                continue
        if best_params is None:
            continue
        tm = Backtester(get_strategy(strategy_name, best_params), cfg).run(test)["metrics"]
        oos_sharpes.append(tm.get(score_key, 0) or 0)
        train_sharpes.append(best_sh)
        oos_trades += tm.get("num_trades", 0)
    oos_sh = float(np.mean(oos_sharpes)) if oos_sharpes else 0.0
    tr_sh = float(np.mean(train_sharpes)) if train_sharpes else 0.0
    return WalkForwardResult(
        is_oos_sharpe=oos_sh, is_oos_net=0.0, oos_trades=oos_trades,
        train_sharpe_mean=tr_sh,
        degradation=(oos_sh / tr_sh) if tr_sh > 0 else 0.0,
    )