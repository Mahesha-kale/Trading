"""Portfolio ensemble: combine the top robust low-correlation strategies with
inverse-volatility capital weighting. Marginal single edges -> viable portfolio
via diversification, IF the edges are uncorrelated.

Reads reports/rank_faithful.json (produced by rank_faithful.py) for the per-symbol
leaderboard; picks the top-N deployable strategies on a symbol, reruns each via
run_faithful to get its equity curve, aligns daily returns, builds the
correlation matrix, sizes by inverse-vol, and backtests the combined portfolio.

If rank_faithful.json is absent, falls back to the BTC top-5 from the earlier
taker/maker rank (docs/strategies_report.md §2).
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import structlog as _sl

from app.backtest.engine import BacktestConfig
from app.backtest.faithful import run_faithful
from app.backtest.metrics import compute_metrics
from app.data.downloader import load_candles
from app.strategy.registry import get_strategy

_sl.configure(wrapper_class=_sl.make_filtering_bound_logger(logging.ERROR),
               cache_logger_on_first_use=False)

# fallback top-5 (BTC, deployable) if rank_faithful.json missing
FALLBACK = [
    ("stochrsi_reversal", "5m", {"atr_mult": 3.0, "tp_mult": 2.0}),
    ("obv_divergence", "15m", {"swing": 40, "atr_mult": 4.0}),
    ("ema_pullback", "15m", {"tol_atr": 0.4, "atr_mult": 4.0}),
    ("donchian_breakout", "15m", {"lookback": 50, "atr_mult": 4.0}),
    ("psar_trend", "15m", {"atr_mult": 4.0}),
]
LEVERAGE = 3


def pick_top(path: str, symbol: str, n: int = 5):
    """Top-N deployable strategies by score from rank_faithful.json."""
    try:
        data = json.load(open(path))[symbol]
    except Exception:
        return None
    rows = [r for r in data if "score" in r and r["score"] > -1]
    rows.sort(key=lambda x: x["score"], reverse=True)
    out = []
    for r in rows[:n]:
        out.append((r["name"], r["tf"], r["params"]))
    return out


async def equity_for(name, tf, params, df):
    cfg = BacktestConfig(maker_on_limit=True, leverage=LEVERAGE)
    r = run_faithful(get_strategy(name, params), df, cfg)
    return r["equity"], r["metrics"], r["trades"]


def combine(eqs: dict, weights: dict, capital: float = 10000.0):
    # normalize each equity to start at 1, weight, sum -> portfolio
    norm = pd.DataFrame({k: v / v.iloc[0] for k, v in eqs.items()}).ffill().fillna(1.0)
    w = pd.Series(weights)
    w = w / w.sum()
    port = (norm[w.index] * w).sum(axis=1) * capital
    return port


def _equity_override(m: dict, port: pd.Series) -> None:
    """compute_metrics gets net/PF from a trade list; portfolios have none, so
    derive net from the equity curve and PF from daily returns (sum+ / |sum-|)."""
    m["net_profit"] = round(float(port.iloc[-1] - port.iloc[0]), 2)
    dr = port.resample("1D").last().ffill().pct_change().fillna(0)
    gp = dr[dr > 0].sum(); gl = -dr[dr < 0].sum()
    m["profit_factor"] = round(float(gp / gl), 2) if gl > 0 else 0.0


async def main(symbol: str = "B-BTC_USDT"):
    top = pick_top("reports/rank_faithful.json", symbol, n=5)
    if not top:
        print("rank_faithful.json missing/empty -> using fallback top-5", flush=True)
        top = FALLBACK
    print(f"ensemble on {symbol}: {[(n, tf) for n, tf, _ in top]}", flush=True)
    # load needed timeframes
    dfs = {}
    for _, tf, _ in top:
        if tf not in dfs:
            days = {"5m": 150, "15m": 330}[tf]
            dfs[tf] = await load_candles(symbol, tf,
                                         datetime.now(timezone.utc) - timedelta(days=days),
                                         datetime.now(timezone.utc))
            print(f"  {tf}: {len(dfs[tf])} bars", flush=True)
    eqs, metas = {}, {}
    for name, tf, params in top:
        df = dfs[tf]
        if len(df) < 2000:
            continue
        eq, m, _ = await equity_for(name, tf, params, df)
        eqs[name] = eq
        metas[name] = m
        print(f"  {name:22} PF={m['profit_factor']:.2f} net={m['net_profit']:7.1f} "
              f"sh={m['sharpe']:.2f} dd={m['max_drawdown']:.3f} tr={m['num_trades']}", flush=True)
    if len(eqs) < 2:
        print("need >=2 strategies for ensemble"); return
    # daily returns + correlation. equity is sparse (trade-times only) so
    # resample.last().ffill() leaves leading NaN before a strategy's first trade;
    # back-fill with its initial capital so pre-start = 0 return (flat), making
    # all columns dense + aligned on the same span.
    daily = pd.DataFrame({
        k: v.resample("1D").last().ffill().fillna(v.iloc[0]).pct_change().fillna(0)
        for k, v in eqs.items()})
    corr = daily.corr()
    print("\ncorrelation matrix:\n", corr.round(2).to_string(), flush=True)
    # inverse-vol weights
    vol = daily.std()
    weights = (1.0 / vol).to_dict()
    port = combine(eqs, weights)
    pm = compute_metrics(port, [])
    _equity_override(pm, port)  # net/PF from equity curve (no trade list for portfolio)
    print(f"\nPORTFOLIO (inverse-vol): PF={pm['profit_factor']:.2f} net={pm['net_profit']:.1f} "
          f"sh={pm['sharpe']:.2f} dd={pm['max_drawdown']:.3f} annRet={pm['annualized_return']:.3f}", flush=True)
    # equal-weight comparison
    eqw = {k: 1.0 for k in eqs}
    port_eq = combine(eqs, eqw)
    em = compute_metrics(port_eq, [])
    _equity_override(em, port_eq)
    print(f"PORTFOLIO (equal-w):     PF={em['profit_factor']:.2f} net={em['net_profit']:.1f} "
          f"sh={em['sharpe']:.2f} dd={em['max_drawdown']:.3f}", flush=True)
    out = {"symbol": symbol, "strategies": [(n, tf, p) for n, tf, p in top],
           "correlation": corr.round(3).to_dict(),
           "portfolio_invvol": {k: round(float(v), 4) for k, v in pm.items()},
           "portfolio_equalw": {k: round(float(v), 4) for k, v in em.items()}}
    json.dump(out, open("reports/ensemble.json", "w"), indent=2, default=str)
    print("\n-> reports/ensemble.json")


if __name__ == "__main__":
    import sys
    sym = sys.argv[1] if len(sys.argv) > 1 else "B-BTC_USDT"
    asyncio.run(main(sym))