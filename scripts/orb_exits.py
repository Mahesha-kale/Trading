"""ORB exit-method sweep (sub-project 7, §35.14).

User asked: trailing stop + fib TP, and other SL/TP ways to optimize. This
sweeps 10 exit configs (fib TP levels, ATR trailing, break-even, partial scale-
out, ATR stop, pure trail) on the 3 best 15m cells, over the last 1y, and runs
a K-fold rigor gate inline. Any config with bootstrap CI lo > 0 = candidate.

run:  python -m scripts.orb_exits
"""
from __future__ import annotations

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

CSV = {"BTC": "reports/binance_BTCUSDT_15m.csv",
       "ETH": "reports/binance_ETHUSDT_15m.csv",
       "SOL": "reports/binance_SOLUSDT_15m.csv",
       "XAU": "reports/binance_PAXGUSDT_15m.csv"}
# best cells from §35 (15m, fixed by the post-bug re-run)
CELLS = [("BTC", "07:00", 3), ("ETH", "00:00", 3), ("SOL", "01:00", 2),
         ("XAU", "00:00", 5)]
# §35.16 NY+Asia-only (drop London 07:00): best cell per asset restricted to
# Asia(00:00,01:00)+NY(13:00,14:30) sessions, 1y. BTC flipped London->Asia 00:00,
# ETH flipped Asia 00:00 -> NY 13:00 (selection leak, K-fold kills it below).
CELLS_NY_ASIA = [("BTC", "00:00", 5), ("ETH", "13:00", 3), ("SOL", "01:00", 3),
                 ("XAU", "00:00", 5)]


def load_csv(path):
    df = pd.read_csv(path, index_col=0, parse_dates=True)
    df.index = pd.to_datetime(df.index, utc=True, errors="coerce")
    df = df.dropna(subset=["open", "high", "low", "close"]).sort_index()
    df = df[~df.index.duplicated(keep="last")]
    return df[["open", "high", "low", "close", "volume"]]


def cfg(**kw):
    base = dict(use_trailing=False, risk_pct_stop=0.02, leverage=3,
                break_even_at=0.0, maker_on_limit=True, allow_short=True,
                maker_fee=0.00025, taker_fee=0.0006, slippage_bps=2.0,
                partial_exit=False, partial_frac=0.5,
                max_drawdown=0.0, max_positions=99, max_daily_loss=0.0)
    base.update(kw)
    return BacktestConfig(**base)


# exit configs: (label, strategy_params, cfg_kwargs)
EXITS = [
    ("E1 base ORstop+rr2",        {"tp_mode": "rr", "rr": 2.0, "sl_mode": "or"}, {}),
    ("E2 ORstop+fib1.618",        {"tp_mode": "fib", "fib": 1.618, "sl_mode": "or"}, {}),
    ("E3 ORstop+fib2.618",        {"tp_mode": "fib", "fib": 2.618, "sl_mode": "or"}, {}),
    ("E4 ORstop+fib3.618",        {"tp_mode": "fib", "fib": 3.618, "sl_mode": "or"}, {}),
    ("E5 ORstop+fib2.618+trail2", {"tp_mode": "fib", "fib": 2.618, "sl_mode": "or"},
        {"use_trailing": True, "trailing_mult": 2.0}),
    ("E6 ORstop+fib2.618+trail3", {"tp_mode": "fib", "fib": 2.618, "sl_mode": "or"},
        {"use_trailing": True, "trailing_mult": 3.0}),
    ("E7 ORstop+fib2.618+BE1+tr2",{"tp_mode": "fib", "fib": 2.618, "sl_mode": "or"},
        {"use_trailing": True, "trailing_mult": 2.0, "break_even_at": 1.0}),
    ("E8 ORstop+partial1.618+tr2",{"tp_mode": "fib", "fib": 1.618, "sl_mode": "or"},
        {"use_trailing": True, "trailing_mult": 2.0, "partial_exit": True, "partial_frac": 0.5}),
    ("E9 pure ATR trail2 (no TP)",{"tp_mode": "trail", "sl_mode": "or"},
        {"use_trailing": True, "trailing_mult": 2.0}),
    ("E10 ATRstop1.5+fib2.618+tr2",{"tp_mode": "fib", "fib": 2.618, "sl_mode": "atr", "atr_mult": 1.5},
        {"use_trailing": True, "trailing_mult": 2.0}),
]


def winloss(trades):
    pnls = [float(t["pnl"]) for t in trades]
    n = len(pnls)
    if not n:
        return 0, 0, 0, 0.0
    w = sum(1 for p in pnls if p > 0)
    return n, w, n - w, 100.0 * w / n


def run(df, sp, ck):
    base = {"range_bars": None, "session_open": None, "reversal": False, "rr": 2.0}
    base.update(sp)
    res = Backtester(get_strategy("orb_max", base), cfg(**ck)).run(df)
    return res


def kfold_ci(df, sp, ck, k=4, n_boot=500):
    """K=4 contiguous folds + circular-block bootstrap CI on full-window returns."""
    nn = len(df); fold = max(1, nn // k); fnets = []
    for i in range(k):
        eq = run(df.iloc[i * fold:(i + 1) * fold], sp, ck)["equity"]
        fnets.append(float(eq.iloc[-1] - eq.iloc[0]) if len(eq) > 1 else 0.0)
    full = run(df, sp, ck)
    eqf = full["equity"]
    net = float(eqf.iloc[-1] - eqf.iloc[0])
    rets = eqf.pct_change().dropna()
    lo = -np.inf
    if len(rets) >= 20:
        rng = np.random.default_rng(0); block = 10; r = rets.values
        draws = np.empty(n_boot)
        for i in range(n_boot):
            st = rng.integers(0, len(r), size=len(r) // block + 1)
            idx = (st[:, None] + np.arange(block)[None, :]).ravel()[:len(r)] % len(r)
            draws[i] = r[idx].sum()
        lo = float(np.quantile(draws, 0.025))
    return fnets, net, lo, full["trades"], full["metrics"]


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--ny-asia", action="store_true",
                    help="use NY+Asia-only cells (drop London 07:00)")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    cells = CELLS_NY_ASIA if args.ny_asia else CELLS
    out = open(args.out, "w") if args.out else None
    def emit(s=""):
        print(s); out and out.write(s + "\n")
    rows = []
    for asset, sess, rb in cells:
        df = load_csv(CSV[asset]).iloc[-35040:]  # last 1y
        emit(f"\n##### {asset} 15m {sess} rb={rb} | 1y {df.index[0].date()} -> {df.index[-1].date()} #####")
        for label, sp, ck in EXITS:
            sp = {**sp, "range_bars": rb, "session_open": sess}
            try:
                fnets, net, lo, trades, m = kfold_ci(df, sp, ck)
            except Exception as e:  # noqa: BLE001
                emit(f"  {label:30} ERR {str(e)[:60]}")
                continue
            n, w, l_, pct = winloss(trades)
            k4 = sum(f > 0 for f in fnets) >= 3 and sum(fnets) > 0
            verdict = "PASS" if (k4 and net > 0 and lo > 0) else "fail"
            rows.append((asset, label, n, w, l_, pct, net, lo, k4, verdict))
            emit(f"  {label:30} tr={n:4} win%={pct:4.0f} net={net:8.0f} dd={m.get('max_drawdown',0):.2f} "
                  f"folds=[{','.join(str(round(f)) for f in fnets)}] CIlo={lo:.2f} {verdict}")
    emit("\n===== PASSING (CI lo > 0 AND >=3/4 folds AND net>0) =====")
    any_pass = False
    for asset, label, n, w, l_, pct, net, lo, k4, verdict in rows:
        if verdict == "PASS":
            any_pass = True
            emit(f"  {asset} {label}: tr={n} win%={pct:.0f} net={net:.0f} CIlo={lo:.2f}")
    if not any_pass:
        emit("  NONE -- all exit configs fail K-fold rigor; ORB stays refuted")
    out and out.close()


if __name__ == "__main__":
    main()