"""Strategy optimization: grid + random search, walk-forward. Minimal but real.

Walk-forward: split data into N train/test windows, optimize params on train,
evaluate on out-of-sample test; aggregate. Heatmap data returned for plotting.
"""
from __future__ import annotations

import itertools
import random
from dataclasses import dataclass
from typing import Any

import pandas as pd

from app.backtest.engine import BacktestConfig, Backtester
from app.strategy.base import BaseStrategy
from app.strategy.registry import get_strategy


def grid_params(param_grid: dict[str, list]) -> list[dict]:
    keys = list(param_grid)
    return [dict(zip(keys, vs)) for vs in itertools.product(*param_grid.values())]


def random_params(param_space: dict[str, tuple], n: int, seed: int = 0) -> list[dict]:
    rng = random.Random(seed)
    out = []
    for _ in range(n):
        out.append({k: rng.uniform(lo, hi) if isinstance(lo, float) else rng.randint(lo, hi)
                    for k, (lo, hi) in param_space.items()})
    return out


@dataclass
class OptResult:
    params: dict
    score: float
    metrics: dict


def optimize_grid(strategy_name: str, df: pd.DataFrame, grid: dict[str, list],
                  score_key: str = "sharpe") -> OptResult:
    best = None
    for params in grid_params(grid):
        strat = get_strategy(strategy_name, {k: (int(v) if isinstance(v, float) and v.is_integer() else v)
                                              for k, v in params.items()})
        res = Backtester(strat).run(df)
        sc = res["metrics"].get(score_key, 0) or 0
        if best is None or sc > best.score:
            best = OptResult(params, sc, res["metrics"])
    return best or OptResult({}, 0, {})


def walk_forward(strategy_name: str, df: pd.DataFrame, grid: dict[str, list],
                 n_splits: int = 5, score_key: str = "sharpe") -> list[OptResult]:
    """Optimize on train window, evaluate next test window. Returns per-window test results."""
    splits = list(_windows(df, n_splits))
    results = []
    for train_df, test_df in splits:
        if train_df.empty or test_df.empty:
            continue
        best = optimize_grid(strategy_name, train_df, grid, score_key)
        strat = get_strategy(strategy_name, best.params)
        test_res = Backtester(strat).run(test_df)
        results.append(OptResult(best.params, test_res["metrics"].get(score_key, 0) or 0, test_res["metrics"]))
    return results


def _windows(df: pd.DataFrame, n: int):
    if n < 2:
        return
    step = len(df) // n
    for i in range(n - 1):
        train = df.iloc[: (i + 1) * step]
        test = df.iloc[(i + 1) * step: (i + 2) * step]
        yield train, test