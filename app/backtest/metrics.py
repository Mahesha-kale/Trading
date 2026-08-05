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
    bpy = _bars_per_year(equity)
    # sharpe / sortino (annualized by bars per year)
    rf = 0.0
    sharpe = (rets.mean() - rf) / rets.std() * math.sqrt(bpy) if rets.std() > 0 else 0
    downside = rets[rets < 0].std()
    sortino = (rets.mean() - rf) / downside * math.sqrt(bpy) if downside and downside > 0 else 0
    recovery = net / abs(max_dd * equity.iloc[0]) if max_dd != 0 else 0
    # Calmar = annualized return / max drawdown
    yrs = max(len(equity) / bpy, 1e-9)
    cagr = (equity.iloc[-1] / equity.iloc[0]) ** (1 / yrs) - 1 if equity.iloc[0] > 0 else 0
    calmar = cagr / abs(max_dd) if max_dd != 0 else 0
    # consecutive wins / losses from trade sequence
    consec_w = consec_l = 0
    if trades:
        run_w = run_l = 0
        for t in trades:
            if t["pnl"] > 0:
                run_w += 1; run_l = 0; consec_w = max(consec_w, run_w)
            elif t["pnl"] < 0:
                run_l += 1; run_w = 0; consec_l = max(consec_l, run_l)
            else:
                run_w = run_l = 0
    # avg trade duration (hours)
    durations = []
    for t in trades:
        try:
            durations.append((t["exit_ts"] - t["entry_ts"]).total_seconds() / 3600.0)
        except Exception:
            pass
    avg_duration = float(np.mean(durations)) if durations else 0.0
    # monthly returns (pct) from equity curve
    try:
        monthly = equity.resample("ME").last().ffill().pct_change().dropna()
        monthly_ret = float(monthly.mean()) if not monthly.empty else 0.0
    except Exception:
        monthly_ret = 0.0
    init_cap = float(equity.iloc[0])
    return {
        "net_profit": net,
        "gross_profit": gross_profit,
        "gross_loss": gross_loss,
        "win_rate": win_rate,
        "loss_rate": 1 - win_rate,
        "profit_factor": profit_factor,
        "max_drawdown": abs(max_dd),
        "sharpe": sharpe,
        "sortino": sortino,
        "calmar": calmar,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "largest_win": max((t["pnl"] for t in wins), default=0),
        "largest_loss": min((t["pnl"] for t in losses), default=0),
        "expectancy": expectancy,
        "recovery_factor": recovery,
        "avg_duration_h": avg_duration,
        "consecutive_wins": consec_w,
        "consecutive_losses": consec_l,
        "monthly_return": monthly_ret,
        "annualized_return": cagr,
        "return_on_capital": net / init_cap if init_cap else 0,
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
    keys = ("net_profit", "gross_profit", "gross_loss", "win_rate", "loss_rate",
            "profit_factor", "max_drawdown", "sharpe", "sortino", "calmar",
            "avg_win", "avg_loss", "largest_win", "largest_loss", "expectancy",
            "recovery_factor", "avg_duration_h", "consecutive_wins",
            "consecutive_losses", "monthly_return", "annualized_return",
            "return_on_capital", "num_trades")
    return {k: 0 for k in keys}