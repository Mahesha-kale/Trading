"""Performance metrics from equity curve + trade list."""
from __future__ import annotations

import math
from decimal import Decimal

import numpy as np
import pandas as pd


def compute_metrics(equity: pd.Series, trades: list[dict]) -> dict[str, float | Decimal]:
    if equity.empty:
        return _empty()
    rets = equity.pct_change().dropna()
    wins = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] < 0]
    gross_profit = sum(t["pnl"] for t in wins)
    gross_loss = -sum(t["pnl"] for t in losses)
    net = sum(t["pnl"] for t in trades)
    win_rate = len(wins) / len(trades) if trades else 0
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (float("inf") if gross_profit > 0 else 0)
    avg_win = (gross_profit / len(wins)) if wins else 0
    avg_loss = (gross_loss / len(losses)) if losses else 0
    expectancy = net / len(trades) if trades else 0
    # drawdown
    peak = equity.cummax()
    dd = (equity - peak) / peak
    max_dd = float(dd.min()) if not dd.empty else 0.0
    # sharpe / sortino (annualized by bars per year caller supplies via periods)
    rf = 0.0
    sharpe = (rets.mean() - rf) / rets.std() * math.sqrt(_bars_per_year(equity)) if rets.std() > 0 else 0
    downside = rets[rets < 0].std()
    sortino = (rets.mean() - rf) / downside * math.sqrt(_bars_per_year(equity)) if downside and downside > 0 else 0
    recovery = net / abs(max_dd * equity.iloc[0]) if max_dd != 0 else 0
    return {
        "net_profit": net,
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "max_drawdown": abs(max_dd),
        "sharpe": sharpe,
        "sortino": sortino,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "expectancy": expectancy,
        "recovery_factor": recovery,
        "num_trades": len(trades),
    }


def _bars_per_year(equity: pd.Series) -> int:
    if len(equity) < 2:
        return 252
    delta = equity.index.to_series().diff().median()
    if delta is None or pd.isna(delta) or delta == pd.Timedelta(0):
        return 252
    secs = delta.total_seconds()
    if secs <= 0:
        return 252
    # crypto trades 24/7/365
    return int(round(365 * 24 * 3600 / secs))


def _empty() -> dict[str, float | Decimal]:
    return {k: 0 for k in ("net_profit", "win_rate", "profit_factor", "max_drawdown",
                          "sharpe", "sortino", "avg_win", "avg_loss", "expectancy",
                          "recovery_factor", "num_trades")}