"""ORB recent win/loss trade stats (sub-project 7, §35.12).

The rigor gate refuted the 1y edge=True cells as path luck. But the recent fold
IS printing winners right now. This prints the raw win/loss trade counts + %
for a given cell/window, and splits the window into chronological quarters so
the "working until it doesn't" pattern is visible.

run:  python -m scripts.orb_winrate --asset BTC --tf 15m --session 07:00 --rb 3 --rr 2.0 --years 1.0
"""
from __future__ import annotations

import argparse
import logging

import pandas as pd

from app.backtest.engine import BacktestConfig, Backtester
from app.logging import configure_logging
from app.strategy.registry import get_strategy

configure_logging()
import structlog as _sl
_sl.configure(wrapper_class=_sl.make_filtering_bound_logger(logging.ERROR),
               cache_logger_on_first_use=False)

CSV = {"BTC": {"15m": "reports/binance_BTCUSDT_15m.csv", "5m": "reports/binance_BTCUSDT_5m.csv"},
       "ETH": {"15m": "reports/binance_ETHUSDT_15m.csv"},
       "SOL": {"15m": "reports/binance_SOLUSDT_15m.csv"}}
RESAMPLE_FROM = "15m"
BARS_PER_DAY = {"5m": 288, "15m": 96, "1h": 24, "4h": 6}


def load_tf(asset, tf):
    path = CSV.get(asset, {}).get(tf)
    if path:
        df = pd.read_csv(path, index_col=0, parse_dates=True)
    else:
        base = CSV.get(asset, {}).get(RESAMPLE_FROM)
        df = pd.read_csv(base, index_col=0, parse_dates=True)
        df = df.resample(tf).agg({"open": "first", "high": "max", "low": "min",
                                  "close": "last", "volume": "sum"}).dropna()
    df.index = pd.to_datetime(df.index, utc=True, errors="coerce")
    df = df.dropna(subset=["open", "high", "low", "close"]).sort_index()
    df = df[~df.index.duplicated(keep="last")]
    return df[["open", "high", "low", "close", "volume"]]


def cfg():
    return BacktestConfig(use_trailing=False, risk_pct_stop=0.02, leverage=3,
                          break_even_at=0.0, maker_on_limit=True, allow_short=True,
                          maker_fee=0.00025, taker_fee=0.0006, slippage_bps=2.0,
                          max_drawdown=0.0, max_positions=99, max_daily_loss=0.0)


def winloss(trades):
    pnls = [float(t["pnl"]) for t in trades]
    n = len(pnls)
    if not n:
        return n, 0, 0, 0.0, 0.0, 0.0
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    awg = sum(wins) / len(wins) if wins else 0.0
    alg = sum(losses) / len(losses) if losses else 0.0
    return n, len(wins), len(losses), 100.0 * len(wins) / n, awg, alg


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--asset", required=True)
    ap.add_argument("--tf", default="15m")
    ap.add_argument("--session", required=True)
    ap.add_argument("--rb", type=int, required=True)
    ap.add_argument("--rr", type=float, default=2.0)
    ap.add_argument("--reversal", action="store_true")
    ap.add_argument("--years", type=float, default=1.0)
    args = ap.parse_args()

    params = {"range_bars": args.rb, "session_open": args.session,
              "reversal": args.reversal, "rr": args.rr}
    df = load_tf(args.asset, args.tf)
    df = df.iloc[-int(args.years * 365 * BARS_PER_DAY.get(args.tf, 96)):]
    res = Backtester(get_strategy("orb_max", params), cfg()).run(df)
    trades = res["trades"]
    n, w, l, pct, awg, alg = winloss(trades)
    net = sum(float(t["pnl"]) for t in trades)
    print(f"##### {args.asset} {args.tf} {args.session} rb={args.rb} rr={args.rr} "
          f"rev={args.reversal} | {args.years}y {df.index[0].date()} -> {df.index[-1].date()} #####")
    print(f"FULL: trades={n} wins={w} losses={l} win%={pct:.1f} avg_win={awg:.1f} avg_loss={alg:.1f} net={net:.1f}")
    # 4 chronological quarters — show "working until it isn't"
    tdf = pd.DataFrame(trades)
    if len(tdf):
        tdf["entry_ts"] = pd.to_datetime(tdf["entry_ts"], utc=True)
        tdf = tdf.sort_values("entry_ts").reset_index(drop=True)
        q = max(1, len(tdf) // 4)
        for i in range(4):
            seg = tdf.iloc[i * q:(i + 1) * q] if i < 3 else tdf.iloc[3 * q:]
            if len(seg):
                n2, w2, l2, p2, aw2, al2 = winloss(seg.to_dict("records"))
                net2 = sum(float(t["pnl"]) for t in seg.to_dict("records"))
                print(f"  Q{i+1} {seg['entry_ts'].iloc[0].date()}..{seg['entry_ts'].iloc[-1].date()}: "
                      f"tr={n2} win={w2} loss={l2} win%={p2:.1f} net={net2:.1f}")


if __name__ == "__main__":
    main()