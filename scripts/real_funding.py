"""Step 4: dynamic signed funding. The fixed +0.0001/8h model overstates cost
in periods where real funding is lower (the 2025-26 OOS mean is +0.000034, 3x
below the flat rate) and understates in hot bulls. Re-tests the marginal
candidates (ema_cross 4h gated long-only was the all-time best at OOS sh 0.09)
with REAL per-8h signed funding vs the fixed rate, to see if the verdict moves.

Real funding pulled by scripts/pull_funding.py -> reports/binance_BTCUSDT_funding.csv
(signed; negative marks = longs receive, shorts pay). Engine uses cfg.funding_rates
asof each 8h event. Real perp costs (no TDS). Usage: python scripts/real_funding.py
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
FIXED = 0.0001  # engine default (FUNDING_RATE_DEFAULT)


def load_funding() -> pd.Series:
    s = pd.read_csv("reports/binance_BTCUSDT_funding.csv", index_col=0)["rate"]
    s.index = pd.to_datetime(s.index, utc=True, format="ISO8601")  # CSV round-trip drops tz
    return s.astype(float).sort_index()


def resample(tf: str) -> pd.DataFrame:
    df = pd.read_csv("reports/binance_BTCUSDT_15m.csv", index_col=0, parse_dates=True).sort_index()
    return df.resample(tf).agg({"open": "first", "high": "max", "low": "min",
                                "close": "last", "volume": "sum"}).dropna()


def cfg(kind: str, atr_mult: float, allow_short: bool, gated: bool, funding) -> BacktestConfig:
    if kind == "reversion":
        c = BacktestConfig(use_trailing=False, risk_pct_stop=0.02, leverage=LEV,
                          break_even_at=0.0, maker_on_limit=True, allow_short=allow_short)
    else:
        c = BacktestConfig(use_trailing=True, trailing_mult=atr_mult, leverage=LEV,
                           break_even_at=0.0, maker_on_limit=True, allow_short=allow_short)
    c.regime_sma = SMA if gated else None
    c.funding_rates = funding  # None -> fixed rate; Series -> real per-8h
    return c


def mr(m: dict) -> dict:
    return {"tr": int(m.get("num_trades", 0)),
            "sh": round(float(m.get("sharpe", 0)), 2),
            "net": round(float(m.get("net_profit", 0)), 1),
            "dd": round(float(m.get("max_drawdown", 0)), 3),
            "pf": round(float(m.get("profit_factor", 0)), 2)}


def bench(name, params, tf_df, kind, short, gated, funding, am):
    p = dict(params); p["use_short"] = short
    full = Backtester(get_strategy(name, p), cfg(kind, am, short, gated, funding)).run(tf_df)["metrics"]
    split = int(len(tf_df) * 0.7); oos = tf_df.iloc[split:]
    o = Backtester(get_strategy(name, p), cfg(kind, am, short, gated, funding)).run(oos)["metrics"]
    return mr(full), mr(o)


def main():
    fr = load_funding()
    print(f"funding: {len(fr)} marks, full mean {fr.mean():.6f}, "
          f"OOS mean {fr.loc['2025-07':].mean():.6f}, frac<0 OOS {(fr.loc['2025-07':]<0).mean():.2f}\n",
          flush=True)
    df4 = resample("4h"); df1 = resample("1D")
    bh4 = df4["close"].iloc[-1] / df4["close"].iloc[0] - 1
    bh4o = df4["close"].iloc[int(len(df4)*0.7):].iloc[-1] / df4["close"].iloc[int(len(df4)*0.7):].iloc[0] - 1
    print(f"4h buyhold full {bh4*100:.0f}% oos {bh4o*100:.0f}% | 1d oos -42%\n", flush=True)
    # candidates: (label, name, params, df, kind, short, gated, atr_mult)
    cands = [
        ("ema_cross 4h L gated",   "ema_cross",  {"fast": 21, "slow": 50}, df4, "trend", False, True,  3.0),
        ("ema_cross 4h L/S",       "ema_cross",  {"fast": 21, "slow": 50}, df4, "trend", True,  False, 3.0),
        ("supertrend 4h L gated",   "supertrend", {"period": 10, "multiplier": 3.0}, df4, "trend", False, True, 3.0),
        ("supertrend 4h L/S",       "supertrend", {"period": 10, "multiplier": 3.0}, df4, "trend", True,  False, 3.0),
        ("ema_cross 1d L gated",   "ema_cross",  {"fast": 21, "slow": 50}, df1, "trend", False, True,  3.0),
        ("ema_cross 1d L/S",       "ema_cross",  {"fast": 21, "slow": 50}, df1, "trend", True,  False, 3.0),
        ("supertrend 1d L gated",  "supertrend", {"period": 10, "multiplier": 3.0}, df1, "trend", False, True, 3.0),
        ("supertrend 1d L/S",      "supertrend", {"period": 10, "multiplier": 3.0}, df1, "trend", True,  False, 3.0),
    ]
    print(f"{'candidate':22}{'funding':9}{'tr':>4}{'sh':>6}{'net':>9}{'dd':>7}{'pf':>6}   (full | oos)",
          flush=True)
    for label, name, params, df, kind, short, gated, am in cands:
        for ftag, fund in (("fixed", None), ("real", fr)):
            ff, oo = bench(name, params, df, kind, short, gated, fund, am)
            print(f"{label:22}{ftag:9}"
                  f"{'FULL':4}{ff['tr']:4d}{ff['sh']:6.2f}{ff['net']:9.1f}{ff['dd']:7.3f}{ff['pf']:6.2f}",
                  flush=True)
            print(f"{'':22}{'':9}"
                  f"{'OOS':4}{oo['tr']:4d}{oo['sh']:6.2f}{oo['net']:9.1f}{oo['dd']:7.3f}{oo['pf']:6.2f}",
                  flush=True)
    print("\nReal funding is LOWER than the fixed 0.0001 (full +0.000066, OOS +0.000034) "
          "and only 22% negative in OOS -- the 'downtrend' wasn't a crash, funding stayed "
          "positive. So longs pay LESS with real funding -> long-only nudges up; shorts "
          "receive less. Edge only if real-funding OOS sh>0 & net>0 where fixed was breakeven.")


if __name__ == "__main__":
    main()