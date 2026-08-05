"""Ranking harness: backtest every strategy on its timeframe, grid-tune on a
train slice, score OOS + full, run Monte Carlo, weighted-rank, emit leaderboard.

Backtest cfg per `kind`: trend -> engine ATR trailing (mirrors atr_mult);
reversion -> engine fixed stop + strategy.take_profit. Score blends OOS metrics
(curve-fit resistance) with full-sample robustness. Deployable = persistent-1
strategies (the 13 batch + wyckoff); the 8 original transition-semantic ones
are backtested but flagged non-deployable to paper/live.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

from app.backtest.engine import BacktestConfig, Backtester
from app.backtest.robustness import monte_carlo, regime_split
from app.data.downloader import load_candles
from app.logging import configure_logging
from app.strategy.registry import REGISTRY, get_strategy

configure_logging()
import structlog as _sl  # reconfigure at ERROR so cached risk logger stops spamming
_sl.configure(wrapper_class=_sl.make_filtering_bound_logger(logging.ERROR),
               cache_logger_on_first_use=False)

# name -> (timeframe, kind, deployable, grid). kind None = infer from class.
STRATEGIES = {
    # --- deployable (persistent-1) ---
    "liquidity_sweep":      ("5m",  "trend",     True,  {"atr_mult": [2.5, 3.5], "sweep_pen": [0.001, 0.002]}),
    "fair_value_gap":       ("5m",  "reversion", True,  {"atr_mult": [2.0, 3.0]}),
    "opening_range_breakout": ("15m", "trend",   True,  {"range_bars": [3, 5], "atr_mult": [3.0, 4.0]}),
    "vwap_pullback":        ("5m",  "trend",     True,  {"tol_atr": [0.4, 0.7], "atr_mult": [2.5, 3.5]}),
    "keltner_mr":           ("5m",  "reversion", True,  {"mult": [1.8, 2.2], "atr_mult": [2.0, 3.0]}),
    "stochrsi_reversal":    ("5m",  "reversion", True,  {"atr_mult": [2.0, 3.0]}),
    "cci_reversion":        ("5m",  "reversion", True,  {"period": [15, 20], "atr_mult": [2.0, 3.0]}),
    "adx_trend":            ("15m", "trend",     True,  {"adx_thresh": [20, 28], "atr_mult": [3.0, 4.0]}),
    "donchian_breakout":    ("15m", "trend",     True,  {"lookback": [30, 50], "atr_mult": [3.0, 4.0]}),
    "ichimoku_breakout":    ("15m", "trend",     True,  {"atr_mult": [3.0, 4.0]}),
    "psar_trend":           ("15m", "trend",     True,  {"atr_mult": [3.0, 4.0]}),
    "obv_divergence":       ("15m", "trend",     True,  {"swing": [25, 40], "atr_mult": [3.0, 4.0]}),
    "ema_pullback":         ("15m", "trend",     True,  {"tol_atr": [0.4, 0.7], "atr_mult": [3.0, 4.0]}),
    "wyckoff":              ("15m", "trend",     True,  {"sos_window": [40, 80], "atr_mult": [3.0, 5.0]}),
    "regime_gate":          ("15m", "trend",     True,  {"bull": [None, "stochrsi_reversal"], "adx_thresh": [15, 25], "atr_mult": [3.0, 4.0]}),
    # --- non-deployable (transition-semantic, backtest only) ---
    "ema_cross":            ("15m", "trend",     False, {"fast": [10, 20], "slow": [40, 60]}),
    "macd":                 ("15m", "trend",     False, {"atr_mult": [3.0, 4.0]}),
    "supertrend":           ("15m", "trend",     False, {"multiplier": [2.5, 3.5], "period": [7, 10]}),
    "atr_trend":            ("15m", "trend",     False, {"multiplier": [2.5, 3.5]}),
    "breakout":             ("15m", "trend",     False, {"lookback": [20, 40]}),
    "vwap_reclaim":         ("15m", "trend",     False, {"atr_mult": [3.0, 4.0]}),
    "bollinger":            ("15m", "reversion", False, {"std_mult": [1.8, 2.2]}),
    "rsi_reversal":         ("15m", "reversion", False, {"period": [10, 14]}),
}

# mapping of strategy name -> registry key (some classes use different reg keys)
REG_KEY = {
    "bollinger": "bollinger_reversion", "macd": "macd_cross",
}  # others: rank-dict name == registry meta.name verbatim

TF_DAYS = {"1m": 60, "5m": 150, "15m": 330}
LEVERAGE = 3
INIT_CAP = 10000.0


def cfg_for(kind: str, atr_mult: float) -> BacktestConfig:
    if kind == "reversion":
        # maker_on_limit: realistic limit-entry model halves entry fee. rps 0.02
        # (not 0.05): tighter than the old catastrophic 5% stop but wider than ATR
        # noise so the mean-revert bounce isn't stopped out pre-TP.
        return BacktestConfig(use_trailing=False, risk_pct_stop=0.02, leverage=LEVERAGE,
                              break_even_at=0.0, maker_on_limit=True)
    return BacktestConfig(use_trailing=True, trailing_mult=atr_mult, leverage=LEVERAGE,
                          break_even_at=0.0, maker_on_limit=True)


def grid_combos(grid: dict[str, list]) -> list[dict]:
    keys = list(grid)
    base = [{}]
    for k in keys:
        base = [dict(b, **{k: v}) for b in base for v in grid[k]]
    return base


def cast_params(name: str, params: dict) -> dict:
    int_keys = {"range_bars", "lookback", "period", "fast", "slow", "sos_window",
                "swing", "adx_thresh", "adx_period", "atr_period", "trend_ema",
                "trend_slope", "tenkan", "kijun", "senkou_b", "rsi_period",
                "stoch_period", "signal"}
    out = {}
    for k, v in params.items():
        if k in int_keys and v is not None:
            out[k] = int(v)
        else:
            out[k] = v
    return out


def score(m_full: dict, m_test: dict, mc: dict, deployable: bool) -> float:
    """Weighted 0-100. Penalizes curve-fit (OOS vs full), thin trade count, DD."""
    if m_test["num_trades"] < 5:
        return -1.0  # too few OOS trades to trust
    oos_sharpe = max(m_test.get("sharpe", 0), -5)
    oos_pf = min(m_test.get("profit_factor", 0), 5)
    full_sharpe = max(m_full.get("sharpe", 0), -5)
    full_pf = min(m_full.get("profit_factor", 0), 5)
    max_dd = m_full.get("max_drawdown", 1)
    mc_prob = mc.get("mc_prob_profit", 0)
    stability = (oos_sharpe / full_sharpe) if full_sharpe > 0 else (1.0 if oos_sharpe > 0 else 0)
    stability = max(min(stability, 2.0), -1.0)
    n_trades = m_full.get("num_trades", 0)
    trade_pen = min(n_trades / 30.0, 1.0)  # want >=30 trades for statistical weight
    s = (20 * np.tanh(oos_pf / 2)        # profit factor (OOS)
         + 15 * np.tanh(oos_sharpe / 2)  # sharpe (OOS)
         + 10 * np.tanh(full_sharpe / 2)
         + 15 * (1 - min(max_dd, 0.3) / 0.3)   # low drawdown
         + 15 * stability                    # OOS/full consistency (curve-fit guard)
         + 10 * mc_prob                      # monte carlo P(profit)
         + 10 * trade_pen                    # statistical sufficiency
         - (5 if not deployable else 0))     # non-deployable penalty
    return float(s)


async def run_one(name: str, tf: str, kind: str, deployable: bool, grid: dict, data_cache: dict) -> dict:
    key = REG_KEY.get(name, name)
    if key not in REGISTRY:
        return {"name": name, "error": "not in registry"}
    df = data_cache[tf]
    if df.empty:
        return {"name": name, "error": f"no {tf} data"}
    split = int(len(df) * 0.7)
    train_slice = df.iloc[:split].tail(8000)  # tune on recent 8000 of train
    test = df.iloc[split:]
    # grid tune on train slice (sharpe)
    best = None
    for params in grid_combos(grid):
        bp = cast_params(name, params)
        am = float(bp.get("atr_mult", 3.0))
        try:
            m = Backtester(get_strategy(key, bp), cfg_for(kind, am)).run(train_slice)["metrics"]
            sh = m.get("sharpe", 0) or 0
            if best is None or sh > best[1]:
                best = (bp, sh)
        except Exception:
            continue
    bp = best[0] if best else {}
    am = float(bp.get("atr_mult", 3.0))
    strat = get_strategy(key, bp)
    full = Backtester(strat, cfg_for(kind, am)).run(df)
    test_res = Backtester(get_strategy(key, bp), cfg_for(kind, am)).run(test)
    m_full, m_test = full["metrics"], test_res["metrics"]
    mc = monte_carlo(full["trades"], INIT_CAP, n=500)
    sc = score(m_full, m_test, mc, deployable)
    # regime breakdown (full sample)
    reg = {}
    for rname, rdf in regime_split(df).items():
        if len(rdf) > 500:
            rm = Backtester(get_strategy(key, bp), cfg_for(kind, am)).run(rdf)["metrics"]
            reg[rname] = {"net": float(rm["net_profit"]), "trades": rm["num_trades"]}
    return {
        "name": name, "tf": tf, "kind": kind, "deployable": deployable,
        "params": bp, "score": round(sc, 2),
        "full": {k: (round(float(v), 4) if isinstance(v, (float, np.floating)) else float(v)
                      if isinstance(v, bool) else v)
                 for k, v in m_full.items()},
        "oos": {k: (round(float(v), 4) if isinstance(v, (float, np.floating)) else v) for k, v in m_test.items()},
        "mc": {k: round(float(v), 4) for k, v in mc.items()},
        "regimes": reg,
        "trades_full": len(full["trades"]),
    }


async def main():
    cache = {}
    for tf in ("1m", "5m", "15m"):
        d = TF_DAYS[tf]
        cache[tf] = await load_candles("B-BTC_USDT", tf,
                                       datetime.now(timezone.utc) - timedelta(days=d),
                                       datetime.now(timezone.utc))
        print(f"loaded {tf}: {len(cache[tf])} bars")
    results = []
    for i, (name, (tf, kind, dep, grid)) in enumerate(STRATEGIES.items(), 1):
        print(f"[{i}/{len(STRATEGIES)}] {name} ({tf})...", flush=True)
        try:
            r = await run_one(name, tf, kind, dep, grid, cache)
        except Exception as e:  # noqa: BLE001
            r = {"name": name, "error": str(e)[:160]}
        results.append(r)
        if "score" in r:
            print(f"    score={r['score']} full_sharpe={r['full'].get('sharpe')} "
                  f"oos_sharpe={r['oos'].get('sharpe')} trades={r['trades_full']}", flush=True)
        else:
            print(f"    ERROR: {r.get('error')}", flush=True)
    results.sort(key=lambda x: x.get("score", -999), reverse=True)
    with open("reports/rank_maker.json", "w") as f:
        json.dump(results, f, indent=2, default=str)
    # leaderboard table
    print("\n=== LEADERBOARD ===")
    print(f"{'rank':4}{'strategy':24}{'tf':4}{'score':7}{'PF':6}{'sharpe':7}{'maxDD':7}{'trades':7}{'mcP':6}{'dep':4}")
    for r, row in enumerate(results, 1):
        if "score" not in row:
            print(f"{r:4}{row['name']:24}{'':4}{'ERR':7}{row.get('error','')[:40]}")
            continue
        f = row["full"]
        print(f"{r:4}{row['name']:24}{row['tf']:4}{row['score']:7}{f.get('profit_factor',0):6.2f}"
              f"{f.get('sharpe',0):7.2f}{f.get('max_drawdown',0):7.3f}{row['trades_full']:7}"
              f"{row['mc'].get('mc_prob_profit',0):6.2f}{'Y' if row['deployable'] else 'N':4}")
    print("\nresults -> reports/rank_results.json")


if __name__ == "__main__":
    asyncio.run(main())