"""ORB regime-gate + visit-count spike harness (sub-project 7, H1/H2/H3).

Tests whether regime-gating or a visit-count filter rescues orb_max from the
§35 "no edge" verdict. Three hypotheses:
  H1 trend gate:  regime_sma = block longs below SMA / shorts above (ex-ante).
  H2 regime attribution: tag each trade by ex-ante (trend dir, vol tier); does
       any regime profit CONSISTENTLY across 4 chronological folds? (not "the
       winning window" = path luck — regime is ex-ante, consistency across folds)
  H3 visit-count: min_visits = require the stop level tested >= N times pre-break.

run:  python -m scripts.orb_regime --asset BTC --tf 5m --session 01:00 --rb 3 --rr 3
      python -m scripts.orb_regime --asset ETH --tf 15m --session 00:00 --rb 2 --regime-sma 200
      python -m scripts.orb_regime --asset SOL --tf 15m --session 13:00 --rb 2 --reversal --min-visits 1
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
INIT_CAP = 10000.0


def load_csv(path):
    df = pd.read_csv(path, index_col=0, parse_dates=True)
    df.index = pd.to_datetime(df.index, utc=True, errors="coerce")
    return df.dropna(subset=["open", "high", "low", "close"]).sort_index()[
        ["open", "high", "low", "close", "volume"]]


def cfg_orb(regime_sma=None, min_visits=0):
    kw = dict(use_trailing=False, risk_pct_stop=0.02, leverage=3,
              break_even_at=0.0, maker_on_limit=True, allow_short=True,
              maker_fee=0.00025, taker_fee=0.0006, slippage_bps=2.0,
              max_drawdown=0.0, max_positions=99, max_daily_loss=0.0)
    if regime_sma:
        kw["regime_sma"] = regime_sma
    return BacktestConfig(**kw)


def run_engine(df, params, regime_sma=None):
    strat = get_strategy("orb_max", params)
    res = Backtester(strat, cfg_orb(regime_sma)).run(df)
    return res


def kfold(df, params, regime_sma, k=4):
    """K=4 contiguous folds net + bootstrap CI. Returns (folds_net, full_net, ci_lo)."""
    n = len(df); fold = max(1, n // k); folds = []
    for i in range(k):
        eq = run_engine(df.iloc[i*fold:(i+1)*fold], params, regime_sma)["equity"]
        folds.append(float(eq.iloc[-1] - eq.iloc[0]) if len(eq) > 1 else 0.0)
    full = run_engine(df, params, regime_sma)
    eq_full = full["equity"]
    full_net = float(eq_full.iloc[-1] - eq_full.iloc[0])
    rets = eq_full.pct_change().dropna()
    lo = -np.inf
    if len(rets) >= 20:
        rng = np.random.default_rng(0); block = 10; draws = np.empty(1000)
        r = rets.values
        for i in range(1000):
            st = rng.integers(0, len(r), size=len(r)//block+1)
            idx = (st[:, None] + np.arange(block)[None, :]).ravel()[:len(r)] % len(r)
            draws[i] = r[idx].sum()
        lo = float(np.quantile(draws, 0.025))
    return folds, full_net, lo, full["trades"]


def regime_tags(df):
    """Ex-ante (trend_dir, vol_tier) per bar. trend = prior-day close vs SMA(200d
    on 15m, fall back to 50 if short history). vol_tier = rolling ATR(14)
    percentile rank (prior bar, ex-ante), 3 tiers."""
    close = df["close"]
    # daily SMA for trend (ex-ante: shift 1 day)
    day = close.resample("1D").last().dropna()
    sma_len = 200 if len(day) > 250 else 50
    sma = day.rolling(sma_len, min_periods=max(10, sma_len//4)).mean()
    trend_daily = (day > sma).astype(int).replace({1: 1, 0: -1}).shift(1)  # prior-day regime
    trend = trend_daily.reindex(df.index, method="ffill").fillna(0)
    # vol tier: ATR(14) percentile rank, ex-ante (shift 1)
    hl, ll = df["high"].rolling(14).max(), df["low"].rolling(14).min()
    atr = (hl - ll).rolling(14).mean()
    pct = atr.rolling(1000, min_periods=100).rank(pct=True).shift(1)
    vol_tier = pd.cut(pct, bins=[-0.01, 0.34, 0.67, 1.01],
                      labels=["low", "mid", "high"]).astype("object")
    vol_tier = vol_tier.fillna("mid")
    return trend, vol_tier


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--asset", required=True)
    ap.add_argument("--tf", default="15m")
    ap.add_argument("--session", required=True)
    ap.add_argument("--rb", type=int, required=True)
    ap.add_argument("--rr", type=float, default=2.0)
    ap.add_argument("--reversal", action="store_true")
    ap.add_argument("--min-visits", type=int, default=0)
    ap.add_argument("--regime-sma", type=int, default=None)
    args = ap.parse_args()

    params = {"range_bars": args.rb, "session_open": args.session,
              "reversal": args.reversal, "rr": args.rr, "min_visits": args.min_visits}
    df = load_csv(CSV[args.asset][args.tf])
    print(f"##### {args.asset} {args.tf} | {len(df)} bars {df.index[0].date()} -> {df.index[-1].date()}")
    print(f"params={params} regime_sma={args.regime_sma}\n")

    # H1: K-fold overall (gated if regime_sma set)
    folds, full_net, ci_lo, trades = kfold(df, params, args.regime_sma)
    k4_pass = (sum(f > 0 for f in folds) >= 3) and sum(folds) > 0
    verdict = "PASS" if (k4_pass and full_net > 0 and ci_lo > 0) else "FAIL"
    print(f"H1 K-fold: folds={[round(f) for f in folds]} full={full_net:.0f} ci_lo={ci_lo:.2f} -> {verdict}")
    if not trades:
        print("no trades; aborting regime breakdown")
        return
    print(f"  trades={len(trades)}\n")

    # H2: per-regime fold consistency
    trend, vol_tier = regime_tags(df)
    tdf = pd.DataFrame(trades)
    tdf["entry_ts"] = pd.to_datetime(tdf["entry_ts"], utc=True)
    tdf = tdf.set_index("entry_ts")
    tdf["trend"] = trend.reindex(tdf.index, method="ffill").fillna(0).astype(int)
    tdf["vol_tier"] = vol_tier.reindex(tdf.index, method="ffill").fillna("mid")
    tdf["dir"] = tdf["side"].map({"long": 1, "short": -1})

    print(f"{'regime':22} {'n':>4} {'net':>9} {'win%':>5} {'fold nets':>30} {'consist':>8}")
    any_regime_edge = False
    for (tr, vt), g in tdf.groupby(["trend", "vol_tier"]):
        tr_lbl = "up" if tr == 1 else ("down" if tr == -1 else "range")
        nets = g["pnl"].astype(float).values
        n = len(nets); net = nets.sum(); win = (nets > 0).mean() * 100 if n else 0
        # 4 chronological folds of this regime's trades
        fold_n = max(1, n // 4); fold_nets = []
        for fi in range(4):
            seg = nets[fi*fold_n:(fi+1)*fold_n] if fi < 3 else nets[3*fold_n:]
            fold_nets.append(seg.sum())
        consist = sum(fn > 0 for fn in fold_nets)
        edge = (n >= 10 and net > 0 and consist >= 3)
        any_regime_edge = any_regime_edge or edge
        mark = "  <== EDGE" if edge else ""
        print(f"  trend={tr_lbl:5} vol={vt:4} {n:4} {net:9.0f} {win:5.0f} "
              f"{str([round(fn) for fn in fold_nets]):30} {consist}/4{mark}")

    print(f"\nH2: any regime with >=10 trades + net>0 + >=3/4 folds positive: {any_regime_edge}")
    print(f"OVERALL: H1={verdict} H2_regime_edge={any_regime_edge}")
    if verdict == "PASS" or any_regime_edge:
        print("  -> candidate survives; bounded build warranted (wire regime gate + deploy path)")
    else:
        print("  -> no rescue; ORB stays refuted (path luck not regime-conditional edge)")


if __name__ == "__main__":
    main()