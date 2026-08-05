"""Long-history faithful backtest on 2.5yr Binance public data (2023-01..2025-07).

The CoinDCX window is one regime (~330d); no strategy showed durable edge there.
This runs the 15m deployable strategies via run_faithful over a multi-regime
window (2023 bear -> 2024 bull -> 2025 chop) with rolling walk-forward, to see if
any edge survives across regimes. Uses the signal-faithful engine (predicts live).

Usage: python scripts/long_history.py [BTCUSDT|ETHUSDT]
"""
from __future__ import annotations

import json
import logging
import sys

import numpy as np
import pandas as pd
import structlog as _sl

from app.backtest.engine import BacktestConfig
from app.backtest.faithful import run_faithful
from app.strategy.registry import get_strategy

_sl.configure(wrapper_class=_sl.make_filtering_bound_logger(logging.ERROR),
               cache_logger_on_first_use=False)

# 15m persistent-1 deployable strategies + a small grid (tuned per train fold).
STRATS = {
    "ema_pullback":      {"tol_atr": [0.4, 0.7], "atr_mult": [3.0, 4.0]},
    "obv_divergence":    {"swing": [30, 40], "atr_mult": [3.0, 4.0]},
    "psar_trend":        {"atr_mult": [3.0, 4.0]},
    "donchian_breakout": {"lookback": [40, 50], "atr_mult": [3.0, 4.0]},
    "adx_trend":         {"adx_thresh": [20, 28], "atr_mult": [3.0, 4.0]},
    "ichimoku_breakout": {"atr_mult": [3.0, 4.0]},
    "opening_range_breakout": {"range_bars": [3, 5], "atr_mult": [3.0, 4.0]},
    "wyckoff":           {"sos_window": [60, 80], "atr_mult": [4.0, 5.0]},
    "regime_gate":       {"bull": [None], "adx_thresh": [20, 25]},
}
INT_KEYS = {"lookback", "period", "sos_window", "swing", "adx_thresh",
            "range_bars", "atr_period"}
LEVERAGE = 3


def load(symbol: str) -> pd.DataFrame:
    for ext in ("parquet", "csv"):
        p = f"reports/binance_{symbol}_15m.{ext}"
        try:
            return (pd.read_parquet(p) if ext == "parquet" else pd.read_csv(p, index_col=0, parse_dates=True))
        except Exception:
            continue
    raise SystemExit(f"no Binance cache for {symbol}; run scripts/pull_binance.py first")


def combos(grid):
    keys = list(grid); out = [{}]
    for k in keys:
        out = [dict(b, **{k: v}) for b in out for v in grid[k]]
    return out


def cast(p):
    return {k: (int(v) if k in INT_KEYS and v is not None else v) for k, v in p.items()}


def faithful(name, params, df):
    return run_faithful(get_strategy(name, params), df,
                        BacktestConfig(maker_on_limit=True, leverage=LEVERAGE))["metrics"]


def walk_forward(name, grid, df, n=4):
    """Rolling walk-forward: tune on each train window, score next OOS window.
    Returns list of OOS metrics dicts + best params per fold."""
    step = len(df) // (n + 1)
    folds = []
    for i in range(n):
        train = df.iloc[: (i + 1) * step]
        test = df.iloc[(i + 1) * step: (i + 2) * step]
        if len(train) < 4000 or len(test) < 2000:
            continue
        best, best_sh = None, -1e9
        for p in combos(grid):
            try:
                m = faithful(name, cast(p), train)
                sh = m.get("sharpe", 0) or 0
                if sh > best_sh:
                    best_sh, best = sh, cast(p)
            except Exception:
                continue
        if best is None:
            continue
        om = faithful(name, best, test)
        folds.append({"params": best, "train_sh": round(best_sh, 2),
                      "oos_pf": round(om["profit_factor"], 2),
                      "oos_net": round(om["net_profit"], 1),
                      "oos_sh": round(om["sharpe"], 2),
                      "oos_dd": round(om["max_drawdown"], 3),
                      "oos_tr": om["num_trades"]})
    return folds


def main(symbol="BTCUSDT"):
    df = load(symbol)
    print(f"{symbol} 15m: {len(df)} bars {df.index[0].date()} -> {df.index[-1].date()}", flush=True)
    out = {}
    for name, grid in STRATS.items():
        try:
            full = faithful(name, cast(combos(grid)[0]), df)
        except Exception as e:  # noqa: BLE001
            print(f"{name:24} ERR {str(e)[:60]}")
            continue
        folds = walk_forward(name, grid, df)
        oos_shs = [f["oos_sh"] for f in folds]
        oos_nets = [f["oos_net"] for f in folds]
        pos_folds = sum(1 for x in oos_nets if x > 0)
        out[name] = {"full_pf": round(full["profit_factor"], 2),
                     "full_net": round(full["net_profit"], 1),
                     "full_sh": round(full["sharpe"], 2),
                     "full_dd": round(full["max_drawdown"], 3),
                     "full_tr": full["num_trades"],
                     "wf_oos_sh_mean": round(float(np.mean(oos_shs)), 2) if oos_shs else None,
                     "wf_oos_net_sum": round(float(sum(oos_nets)), 1) if oos_nets else None,
                     "wf_pos_folds": f"{pos_folds}/{len(folds)}",
                     "folds": folds}
        print(f"{name:24} full PF={full['profit_factor']:.2f} net={full['net_profit']:7.1f} "
              f"sh={full['sharpe']:.2f} dd={full['max_drawdown']:.3f} tr={full['num_trades']} | "
              f"WF oos_sh_mean={out[name]['wf_oos_sh_mean']} oos_net_sum={out[name]['wf_oos_net_sum']} "
              f"pos_folds={out[name]['wf_pos_folds']}", flush=True)
    json.dump(out, open("reports/long_history.json", "w"), indent=2, default=str)
    # durable edge = full PF>1 AND >half positive OOS folds AND positive aggregate OOS net
    print("\n=== DURABLE (full PF>1, >50% pos folds, agg OOS net>0) ===")
    for n, r in out.items():
        pos = r["wf_pos_folds"]
        pp, tot = (int(x) for x in pos.split("/")) if "/" in pos else (0, 0)
        pf_ok = r["full_pf"] > 1 and r["full_net"] > 0
        agg = (r["wf_oos_net_sum"] or 0) > 0
        durable = pf_ok and tot > 0 and pp > tot / 2 and agg
        flag = "  <<< DURABLE" if durable else ""
        print(f"  {n:24} full_pf={r['full_pf']} pos_folds={pos} agg_oos={r['wf_oos_net_sum']}{flag}")
    print("\n-> reports/long_history.json")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "BTCUSDT")