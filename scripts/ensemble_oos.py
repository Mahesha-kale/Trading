"""Ensemble OOS walk-forward: tune portfolio weights on train, score out-of-sample.

§10 of the report showed the portfolio's Sharpe/dd benefit was in-sample only.
This closes that: split each strategy's faithful equity into train (70%) / OOS
(30%), derive weights from TRAIN daily returns (inverse-vol + min-variance), apply
those frozen weights to the OOS equity, and report OOS portfolio metrics vs
equal-weight and best-single. If diversification helps OOS, OOS portfolio Sharpe
> best single OOS Sharpe; if not, confirms §10 (in-sample artifact).

Usage: python scripts/ensemble_oos.py [B-ETH_USDT]
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

FALLBACK = [
    ("vwap_pullback", "5m", {"tol_atr": 0.7, "atr_mult": 3.5}),
    ("liquidity_sweep", "5m", {"atr_mult": 3.5, "sweep_pen": 0.001}),
    ("ema_pullback", "15m", {"tol_atr": 0.4, "atr_mult": 4.0}),
    ("adx_trend", "15m", {"adx_thresh": 28, "atr_mult": 4.0}),
    ("donchian_breakout", "15m", {"lookback": 50, "atr_mult": 4.0}),
]
LEVERAGE = 3


def pick_top(path, symbol, n=5):
    try:
        rows = json.load(open(path))[symbol]
    except Exception:
        return None
    rows = [r for r in rows if "score" in r and r["score"] > -1]
    rows.sort(key=lambda x: x["score"], reverse=True)
    return [(r["name"], r["tf"], r["params"]) for r in rows[:n]]


def _override(m, port):
    m["net_profit"] = round(float(port.iloc[-1] - port.iloc[0]), 2)
    dr = port.resample("1D").last().ffill().pct_change().fillna(0)
    gp = dr[dr > 0].sum(); gl = -dr[dr < 0].sum()
    m["profit_factor"] = round(float(gp / gl), 2) if gl > 0 else 0.0


def daily_equity(eq, df):
    """Sparse trade-time equity -> dense daily equity across the FULL df span
    (ffill, dormant = flat). Strategies go silent for long stretches; resample
    alone only covers first->last trade, missing the dormant tail + the pre-first
    flat stretch. Reindex onto the df's daily range so every strategy spans its
    whole data window."""
    days = pd.date_range(df.index[0].normalize(), df.index[-1].normalize(), freq="1D", tz=df.index.tz)
    d = eq.resample("1D").last().reindex(days).ffill().bfill()
    return d


def min_var_weights(cov):
    """Closed-form min-variance: w ∝ inv(cov) · 1, normalize (long-only clipped)."""
    cov = cov.values
    inv = np.linalg.pinv(cov)
    w = inv @ np.ones(cov.shape[0])
    w = np.clip(w, 0, None)  # long-only
    if w.sum() <= 0:
        w = np.ones(len(w))
    return w / w.sum()


async def main(symbol="B-ETH_USDT"):
    top = pick_top("reports/rank_faithful.json", symbol) or FALLBACK
    print(f"ensemble OOS on {symbol}: {[(n, tf) for n, tf, _ in top]}", flush=True)
    dfs = {}
    for _, tf, _ in top:
        if tf not in dfs:
            days = {"5m": 150, "15m": 330}[tf]
            end = datetime.now(timezone.utc)
            dfs[tf] = await load_candles(symbol, tf, end - timedelta(days=days), end)
            print(f"  {tf}: {len(dfs[tf])} bars", flush=True)
    cfg = BacktestConfig(maker_on_limit=True, leverage=LEVERAGE)
    # dense daily equity per strategy, aligned on a common daily index (union of
    # all spans); dormant stretches become flat (held last value).
    daily = {}
    for name, tf, params in top:
        df = dfs[tf]
        if len(df) < 2000:
            continue
        eq = run_faithful(get_strategy(name, params), df, cfg)["equity"]
        daily[name] = daily_equity(eq, df)
        print(f"  {name:22} daily bars={len(daily[name])} "
              f"span {daily[name].index[0].date()}->{daily[name].index[-1].date()}", flush=True)
    if len(daily) < 2:
        print("need >=2 strategies"); return
    D = pd.DataFrame(daily).ffill().bfill()  # align on union daily index
    # single train/OOS boundary: 70% of the COMMON daily span
    split = D.index[int(len(D) * 0.7)]
    train = D.loc[:split]
    oos = D.loc[split:]
    print(f"\ncommon daily span: {D.index[0].date()} -> {D.index[-1].date()} "
          f"| split {split.date()} | train {len(train)} OOS {len(oos)}", flush=True)
    # single-strategy OOS Sharpe (best-single benchmark)
    oos_sh = {}
    for n in D:
        m = compute_metrics(oos[n], [])
        _override(m, oos[n])
        oos_sh[n] = m["sharpe"]
        print(f"  {n:22} oos_sh={m['sharpe']:.2f} oos_net={m['net_profit']:.1f}", flush=True)
    # weights tuned on TRAIN daily returns (inverse-vol, min-variance, equal)
    tr = train.pct_change().fillna(0)
    vol = tr.std()
    schemes = {
        "inverse_vol": (1.0 / vol).to_dict(),
        "min_variance": dict(zip(D.columns, min_var_weights(tr.cov()))),
        "equal": {n: 1.0 for n in D.columns},
    }
    print(f"\n{'scheme':14} {'PF':>5} {'net':>8} {'sharpe':>7} {'maxDD':>7} {'annRet':>7}", flush=True)
    results = {}
    for scheme, w in schemes.items():
        ws = pd.Series(w) / sum(w.values())
        port = (oos[ws.index] / oos[ws.index].iloc[0] * ws).sum(axis=1) * 10000.0
        m = compute_metrics(port, [])
        _override(m, port)
        results[scheme] = m
        print(f"{scheme:14} {m['profit_factor']:5.2f} {m['net_profit']:8.1f} "
              f"{m['sharpe']:7.2f} {m['max_drawdown']:7.3f} {m['annualized_return']:7.3f}", flush=True)
    best_single = max(oos_sh, key=oos_sh.get)
    print(f"\nbest single OOS: {best_single:22} sharpe={oos_sh[best_single]:.2f}")
    inv_sh = results["inverse_vol"]["sharpe"]
    verdict = "DIVERSIFICATION HELPS OOS" if inv_sh > oos_sh[best_single] \
        else "diversification does NOT help OOS (in-sample artifact confirmed)"
    print(f"\nverdict: {verdict}")
    out = {"symbol": symbol, "strategies": [(n, tf, p) for n, tf, p in top],
            "oos_window": [str(oos.index[0]), str(oos.index[-1])],
            "single_oos_sharpe": {n: round(s, 2) for n, s in oos_sh.items()},
            "portfolio_oos": {s: {k: round(float(v), 4) for k, v in m.items()}
                              for s, m in results.items()},
            "verdict": verdict}
    json.dump(out, open("reports/ensemble_oos.json", "w"), indent=2, default=str)
    print("\n-> reports/ensemble_oos.json")


if __name__ == "__main__":
    import sys
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "B-ETH_USDT"))