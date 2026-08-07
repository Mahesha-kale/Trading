"""Regime-balanced walk-forward. The fixed 70/30 split lands OOS entirely in the
2025-26 downtrend -- structurally adversarial to long-only (cannot profit there)
and makes any short edge single-regime bear beta. This splits the series into K
contiguous time-folds and scores EACH as OOS with FIXED params (no per-fold tuning
-- the stringent "one config generalizes across every regime" test, avoids
overfit). Each fold is tagged up/dn by its buy&hold sign.

A strategy is robust only if: positive net in a MAJORITY of folds AND across
BOTH regime types (a strategy that only profits in the downtrend fold = bear
beta, not edge). Real per-8h funding (final cost model, no TDS).

Multi-symbol (BTC/ETH/SOL): a different asset's regime sequence is the cheapest
falsifier of "it's just BTC's regime luck." If the edge is regime-structural it
shows on every asset; if it's BTC-luck it dies on ETH/SOL. Usage: python scripts/regime_wf.py
"""
from __future__ import annotations

import logging

import pandas as pd
import structlog as _sl

from app.backtest.engine import BacktestConfig, Backtester
from app.strategy.registry import get_strategy

_sl.configure(wrapper_class=_sl.make_filtering_bound_logger(logging.ERROR),
               cache_logger_on_first_use=False)

SMA = 200
LEV = 3
K = 4  # folds
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]


def load_funding(symbol: str) -> pd.Series:
    s = pd.read_csv(f"reports/binance_{symbol}_funding.csv", index_col=0)["rate"]
    s.index = pd.to_datetime(s.index, utc=True, format="ISO8601")
    return s.astype(float).sort_index()


def resample(symbol: str, tf: str) -> pd.DataFrame:
    df = pd.read_csv(f"reports/binance_{symbol}_15m.csv", index_col=0, parse_dates=True).sort_index()
    return df.resample(tf).agg({"open": "first", "high": "max", "low": "min",
                                "close": "last", "volume": "sum"}).dropna()


def cfg(kind: str, atr_mult: float, short: bool, gated: bool, funding) -> BacktestConfig:
    if kind == "reversion":
        c = BacktestConfig(use_trailing=False, risk_pct_stop=0.02, leverage=LEV,
                          break_even_at=0.0, maker_on_limit=True, allow_short=short)
    else:
        c = BacktestConfig(use_trailing=True, trailing_mult=atr_mult, leverage=LEV,
                           break_even_at=0.0, maker_on_limit=True, allow_short=short)
    c.regime_sma = SMA if gated else None
    c.funding_rates = funding
    return c


def mr(m: dict) -> dict:
    return {"tr": int(m.get("num_trades", 0)),
            "sh": round(float(m.get("sharpe", 0)), 2),
            "net": round(float(m.get("net_profit", 0)), 1),
            "dd": round(float(m.get("max_drawdown", 0)), 3),
            "pf": round(float(m.get("profit_factor", 0)), 2)}


def folds(df: pd.DataFrame):
    step = len(df) // K
    return [df.iloc[i * step:(i + 1) * step] for i in range(K)]


def run_fold(name, params, seg, kind, short, gated, funding, am):
    p = dict(params); p["use_short"] = short
    return Backtester(get_strategy(name, p), cfg(kind, am, short, gated, funding)).run(seg)["metrics"]


# (label, name, params, tf, kind, short, gated, atr_mult)
CANDS = [
    ("ema_cross 4h L gated",   "ema_cross",  {"fast": 21, "slow": 50}, "4h", "trend", False, True,  3.0),
    ("supertrend 4h L gated",   "supertrend", {"period": 10, "multiplier": 3.0}, "4h", "trend", False, True, 3.0),
    ("adx_trend 4h L gated",    "adx_trend",  {"adx_thresh": 25}, "4h", "trend", False, True,  3.0),
    ("adx_trend 4h L ungated",  "adx_trend",  {"adx_thresh": 28}, "4h", "trend", False, False, 3.0),
    ("ema_cross 1d L gated",    "ema_cross",  {"fast": 21, "slow": 50}, "1D", "trend", False, True,  3.0),
    ("supertrend 1d L gated",   "supertrend", {"period": 10, "multiplier": 3.0}, "1D", "trend", False, True, 3.0),
    ("supertrend 4h L/S ungated","supertrend",{"period": 10, "multiplier": 3.0}, "4h", "trend", True,  False, 3.0),
    ("supertrend 1d L/S",       "supertrend", {"period": 10, "multiplier": 3.0}, "1D", "trend", True,  False, 3.0),
    ("ema_cross 4h L/S",        "ema_cross",  {"fast": 21, "slow": 50}, "4h", "trend", True,  False, 3.0),
]


def run_symbol(symbol: str):
    fr = load_funding(symbol)
    bars = {tf: resample(symbol, tf) for tf in {c[3] for c in CANDS}}
    print(f"\n=== {symbol} | K={K} contiguous folds, fixed params, real funding ===", flush=True)
    print(f"{'candidate':26}{'fold':5}{'reg':4}{'bh%':>6}{'tr':>4}{'sh':>6}{'net':>9}{'dd':>7}{'pf':>6}",
          flush=True)
    for label, name, params, tf, kind, short, gated, am in CANDS:
        segs = folds(bars[tf])
        agg_net = 0.0; pos = 0; pos_up = 0; pos_dn = 0; n_up = n_dn = 0
        for i, seg in enumerate(segs):
            bh = seg["close"].iloc[-1] / seg["close"].iloc[0] - 1
            reg = "up" if bh >= 0 else "dn"
            m = run_fold(name, params, seg, kind, short, gated, fr, am)
            r = mr(m)
            agg_net += r["net"]
            if r["net"] > 0: pos += 1
            if reg == "up":
                n_up += 1; pos_up += r["net"] > 0
            else:
                n_dn += 1; pos_dn += r["net"] > 0
            print(f"{label:26}{i+1:5}{reg:4}{bh*100:6.0f}{r['tr']:4d}{r['sh']:6.2f}"
                  f"{r['net']:9.1f}{r['dd']:7.3f}{r['pf']:6.2f}", flush=True)
        robust = pos > K / 2 and pos_up > 0 and pos_dn > 0
        tag = "ROBUST" if robust else ("bear-beta" if pos_dn > pos_up else "bull-beta")
        print(f"{label:26} agg_net={agg_net:9.1f} pos={pos}/{K} (up {pos_up}/{n_up}, "
              f"dn {pos_dn}/{n_dn}) -> {tag}\n", flush=True)


def main():
    for sym in SYMBOLS:
        run_symbol(sym)
    print("Robust = positive net in >half folds AND across BOTH up & dn regimes. "
          "bear-beta = only profits in downtrend folds; bull-beta = only in uptrend folds.")


if __name__ == "__main__":
    main()