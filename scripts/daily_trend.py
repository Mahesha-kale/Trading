"""Daily (1d) trend test — the cheapest untested lever. Resample 15m->1d, run
supertrend + ema_cross (trend cfg, regime_sma=200) long-only AND long/short,
full + 70/30 OOS. Daily cuts turnover to ~30 trades/3.5y so fees stop dominating.

Reuses scripts/rank.py cfg_for('trend') (engine ATR trailing) + the real perp
cost model (maker/taker fee + slippage + funding, NO TDS — perp futures carry
none). Same params per strategy for clean long vs long/short comparison.

Usage: python scripts/daily_trend.py
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd
import structlog as _sl

from app.backtest.engine import BacktestConfig, Backtester
from app.strategy.registry import get_strategy

_sl.configure(wrapper_class=_sl.make_filtering_bound_logger(logging.ERROR),
               cache_logger_on_first_use=False)

LEVERAGE = 3
SMA = 200  # regime gate period (days)


def load_1d() -> pd.DataFrame:
    df = pd.read_csv("reports/binance_BTCUSDT_15m.csv", index_col=0, parse_dates=True)
    df = df.sort_index()
    # resample 15m OHLCV -> daily OHLCV (open first, high max, low min, close last, vol sum)
    d = df.resample("1D").agg({"open": "first", "high": "max", "low": "min",
                               "close": "last", "volume": "sum"}).dropna()
    return d


def cfg_trend(atr_mult: float = 3.0, allow_short: bool = False) -> BacktestConfig:
    # mirrors rank.py cfg_for('trend'): ATR trailing, maker-on-limit entry.
    return BacktestConfig(use_trailing=True, trailing_mult=atr_mult,
                          leverage=LEVERAGE, break_even_at=0.0,
                          maker_on_limit=True, allow_short=allow_short,
                          regime_sma=SMA)


def run(name: str, params: dict, df: pd.DataFrame, short: bool) -> dict:
    p = dict(params)
    p["use_short"] = short
    am = float(p.get("atr_mult", 3.0))
    strat = get_strategy(name, p)
    return Backtester(strat, cfg_trend(am, allow_short=short)).run(df)["metrics"]


def buyhold(df: pd.DataFrame) -> tuple[float, float]:
    ret = df["close"].iloc[-1] / df["close"].iloc[0] - 1
    end = 10000 * (1 + ret)
    return ret, end


def mrow(m: dict) -> dict:
    return {
        "trades": int(m.get("num_trades", 0)),
        "win": round(float(m.get("win_rate", 0)), 3),
        "sharpe": round(float(m.get("sharpe", 0)), 2),
        "net": round(float(m.get("net_profit", 0)), 1),
        "maxdd": round(float(m.get("max_drawdown", 0)), 3),
        "pf": round(float(m.get("profit_factor", 0)), 2),
    }


def main():
    df = load_1d()
    split_ts = df.index[int(len(df) * 0.7)]
    train, oos = df.loc[:split_ts], df.loc[split_ts:]
    bh_full, bh_oos = buyhold(df), buyhold(oos)
    print(f"1d BTC: {len(df)} bars {df.index[0].date()}->{df.index[-1].date()} "
          f"| split {split_ts.date()} | train {len(train)} oos {len(oos)}", flush=True)
    print(f"buy&hold: full {bh_full[0]*100:.0f}% (end {bh_full[1]:.0f}) | "
          f"oos {bh_oos[0]*100:.0f}% (end {bh_oos[1]:.0f})\n", flush=True)

    strats = {
        "supertrend": {"period": 10, "multiplier": 3.0},
        "ema_cross":  {"fast": 21, "slow": 50},
    }
    # table: strategy x {full, oos} x {trades, win, sharpe, net, maxdd, pf}
    print(f"{'strategy':18}{'side':10}{'win':5}{'tr':>4}{'sharpe':>7}{'net':>9}"
          f"{'maxdd':>7}{'pf':>6}   (full | oos)", flush=True)
    for name, p in strats.items():
        for short, side in ((False, "long"), (True, "long/short")):
            f, o = run(name, p, df, short), run(name, p, oos, short)
            ff, oo = mrow(f), mrow(o)
            print(f"{name:18}{side:10}"
                  f"{'FULL':5}{ff['trades']:4d}{ff['sharpe']:7.2f}{ff['net']:9.1f}"
                  f"{ff['maxdd']:7.3f}{ff['pf']:6.2f}", flush=True)
            print(f"{'':18}{'':10}"
                  f"{'OOS':5}{oo['trades']:4d}{oo['sharpe']:7.2f}{oo['net']:9.1f}"
                  f"{oo['maxdd']:7.3f}{oo['pf']:6.2f}", flush=True)
    # OOS regime flag: 2025-07->2026-07 was a downtrend (buyhold negative).
    oos_regime = "downtrend (buyhold<0)" if bh_oos[0] < 0 else "uptrend"
    print(f"\nOOS regime: {oos_regime}. If a result is positive full but negative "
          f"OOS -> bull beta, not edge. Do not claim edge until OOS sharpe>0 & net>0.")
    # walk-forward: do the long/short shorts profit only in downtrend folds, or
    # across regimes? Decisive bear-beta vs edge test. 4 rolling folds, fixed
    # params (no per-fold tuning -- just split the daily series into regimes).
    print("\n=== WALK-FORWARD (long/short, fixed params, regime per fold) ===", flush=True)
    print(f"{'strategy':14}{'fold':5}{'bh%':>6}{'tr':>4}{'sh':>6}{'net':>9}{'dd':>7}{'pf':>6}",
          flush=True)
    n = 4
    step = len(df) // n
    for name, p in strats.items():
        agg_net = 0.0
        pos = 0
        for i in range(n):
            seg = df.iloc[i * step:(i + 1) * step]
            bh = seg["close"].iloc[-1] / seg["close"].iloc[0] - 1
            m = run(name, p, seg, True)
            mr = mrow(m)
            agg_net += mr["net"]
            if mr["net"] > 0:
                pos += 1
            tag = "dn" if bh < 0 else "up"
            print(f"{name:14}{i+1:5}{bh*100:6.0f}{mr['trades']:4d}{mr['sharpe']:6.2f}"
                  f"{mr['net']:9.1f}{mr['maxdd']:7.3f}{mr['pf']:6.2f}  ({tag})", flush=True)
        print(f"{name:14} agg oos net={agg_net:.1f} pos_folds={pos}/{n}\n", flush=True)


if __name__ == "__main__":
    main()