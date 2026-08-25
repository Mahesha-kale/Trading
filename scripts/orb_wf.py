"""ORB walk-forward rigor gate (sub-project 7).

The 70/30 + grid sweep flagged two thin-sample "edge=True" cells (BTC 5m 01:00,
ETH 15m 00:00) with 3-29 OOS trades and PF 10-17 — the classic path-luck
signature. This gate applies the project's standard rigor (mirrors
regime_gate_wf): K=4 contiguous time-slice folds + 70/30 + circular-block
bootstrap CI. Pass requires net>0 in >=3/4 folds AND aggregate>0 AND 70/30 OOS
net>0 AND bootstrap CI lower bound > 0. Anything else = path luck, not edge.

run:  python -m scripts.orb_wf --asset BTC --tf 5m --session 01:00 --rb 3 --rr 3.0
"""
from __future__ import annotations

import argparse
import logging

import numpy as np
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
       "SOL": {"15m": "reports/binance_SOLUSDT_15m.csv"},
       "XAU": {"15m": "reports/binance_PAXGUSDT_15m.csv"}}
RESAMPLE_FROM = "15m"
BARS_PER_DAY = {"5m": 288, "15m": 96, "1h": 24, "4h": 6}
INIT_CAP = 10000.0


def load_csv(path):
    df = pd.read_csv(path, index_col=0, parse_dates=True)
    df.index = pd.to_datetime(df.index, utc=True, errors="coerce")
    return df.dropna(subset=["open", "high", "low", "close"]).sort_index()[
        ["open", "high", "low", "close", "volume"]]


def load_tf(asset, tf):
    path = CSV.get(asset, {}).get(tf)
    if path:
        return load_csv(path)
    base = CSV.get(asset, {}).get(RESAMPLE_FROM)
    if not base or tf not in BARS_PER_DAY:
        return None
    df = load_csv(base)
    df = df.resample(tf).agg({"open": "first", "high": "max", "low": "min",
                              "close": "last", "volume": "sum"}).dropna()
    return df[["open", "high", "low", "close", "volume"]]


def cfg_orb():
    # ungated (raw pattern read); maker-on-limit real costs
    return BacktestConfig(use_trailing=False, risk_pct_stop=0.02, leverage=3,
                          break_even_at=0.0, maker_on_limit=True, allow_short=True,
                          maker_fee=0.00025, taker_fee=0.0006, slippage_bps=2.0,
                          max_drawdown=0.0, max_positions=99, max_daily_loss=0.0)


def net_of(df_slice):
    """Run engine on slice, return (net_profit, equity_curve, trades)."""
    strat = get_strategy("orb_max", _PARAMS)
    res = Backtester(strat, cfg_orb()).run(df_slice)
    eq = res["equity"]
    net = float(eq.iloc[-1] - eq.iloc[0]) if len(eq) > 1 else 0.0
    return net, eq, res["trades"]


_PARAMS = {}


def bootstrap_ci(returns, n=1000, ci=0.95):
    r = returns.dropna().values
    if len(r) < 20:
        return -np.inf, np.inf
    rng = np.random.default_rng(0)
    block = 10
    draws = np.empty(n)
    for i in range(n):
        starts = rng.integers(0, len(r), size=len(r) // block + 1)
        idx = (starts[:, None] + np.arange(block)[None, :]).ravel()[: len(r)] % len(r)
        draws[i] = r[idx].sum()
    return float(np.quantile(draws, (1 - ci) / 2)), float(np.quantile(draws, 1 - (1 - ci) / 2))


def main():
    global _PARAMS
    ap = argparse.ArgumentParser()
    ap.add_argument("--asset", required=True)
    ap.add_argument("--tf", default="15m")
    ap.add_argument("--session", required=True)
    ap.add_argument("--rb", type=int, required=True)
    ap.add_argument("--rr", type=float, default=2.0)
    ap.add_argument("--reversal", action="store_true")
    ap.add_argument("--years", type=float, default=0.0, help="0=all")
    args = ap.parse_args()

    _PARAMS = {"range_bars": args.rb, "session_open": args.session,
               "reversal": args.reversal, "rr": args.rr}
    df = load_tf(args.asset, args.tf)
    if df is None or len(df) < 100:
        print(f"no data for {args.asset} {args.tf}")
        return
    if args.years:
        df = df.iloc[-int(args.years * 365 * BARS_PER_DAY.get(args.tf, 96)):]
    n = len(df)
    print(f"{args.asset} {args.tf} {df.index[0].date()} -> {df.index[-1].date()} | {n} bars")
    print(f"params: {_PARAMS}\n")

    # K=4 contiguous folds
    k = 4
    fold = max(1, n // k)
    folds_net = []
    fold_trades = []
    for i in range(k):
        s = df.iloc[i * fold:(i + 1) * fold]
        net, _eq, tr = net_of(s)
        folds_net.append(net)
        fold_trades.append(len(tr))
        print(f"  fold {i+1}: net={net:9.1f} trades={len(tr):4}  {s.index[0].date()}..{s.index[-1].date()}")
    k4_pass = (sum(nf > 0 for nf in folds_net) >= 3) and (sum(folds_net) > 0)
    print(f"K4: folds_net={folds_net} -> k4_pass={k4_pass}\n")

    # 70/30
    cut = int(n * 0.7)
    net_oos, eq_oos, _ = net_of(df.iloc[cut:])
    split70_pass = net_oos > 0
    print(f"70/30 OOS net={net_oos:.1f} -> split70_pass={split70_pass}")

    # full + bootstrap CI on full equity returns
    net_full, eq_full, trades_full = net_of(df)
    rets = eq_full.pct_change().dropna()
    lo, hi = bootstrap_ci(rets)
    ci_pass = lo > 0
    print(f"full net={net_full:.1f} trades={len(trades_full)} | bootstrap CI lo={lo:.2f} hi={hi:.2f} -> ci_pass={ci_pass}")

    verdict = "PASS" if (k4_pass and split70_pass and net_full > 0 and ci_pass) else "FAIL"
    print(f"\nVERDICT: {verdict}")
    print("  " + ("edge survives WF + bootstrap" if verdict == "PASS"
                  else "path luck / thin sample -> refuted"))


if __name__ == "__main__":
    main()