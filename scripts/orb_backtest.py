"""ORB backtest + optimization harness (sub-project 7).

Faithful `orb_max` (video spec: shorts, retest, OR-level stop, 2:1 TP, failed-
breakout reversal) vs existing long-only ATR-trail stub, across assets / timeframes
/ session opens, under real CoinDCX perp costs.

Offline: reads reports/binance_<ASSET>_<TF>.csv directly. UNGATED by default
(max_drawdown=0, max_positions=99) so the risk gate doesn't truncate trades
after a 20% DD — that conflates pattern edge with risk control (the §35 BTC
gated-run confound). Gated mode (--gated) restores the deploy risk gates.

Two-phase optimization per asset/tf:
  A) find best (session, range_bars) in retest mode, rr=2
  B) on that best session, sweep reversal x rr to test the failed-breakout play
     and reward:risk sensitivity.

run:  python -m scripts.orb_backtest                       # 15m BTC+ETH+SOL ungated
      python -m scripts.orb_backtest --tf 5m --asset BTC     # 5m BTC
      python -m scripts.orb_backtest --gated                 # deploy risk gates on
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import time

import numpy as np
import pandas as pd

from app.backtest.engine import BacktestConfig, Backtester
from app.backtest.robustness import monte_carlo, regime_split
from app.logging import configure_logging
from app.strategy.registry import get_strategy

configure_logging()
import structlog as _sl  # reconfigure at ERROR so the risk drawdown logger stops spamming
_sl.configure(wrapper_class=_sl.make_filtering_bound_logger(logging.ERROR),
               cache_logger_on_first_use=False)

CSV = {  # asset -> {tf: path}
    "BTC": {"15m": "reports/binance_BTCUSDT_15m.csv", "5m": "reports/binance_BTCUSDT_5m.csv"},
    "ETH": {"15m": "reports/binance_ETHUSDT_15m.csv"},
    "SOL": {"15m": "reports/binance_SOLUSDT_15m.csv"},
    "XAU": {"15m": "reports/binance_PAXGUSDT_15m.csv"},  # PAX Gold = XAU/USDT gold perp proxy
}
# higher TFs resampled from 15m base (1d = 1 bar/day, no intraday range -> skip)
RESAMPLE_FROM = "15m"
BARS_PER_DAY = {"5m": 288, "15m": 96, "1h": 24, "4h": 6}
LEVERAGE = 3
INIT_CAP = 10000.0
MAKER = 0.00025
TAKER = 0.0006
SLIP = 2.0
SESSIONS = ["00:00", "01:00", "07:00", "13:00", "14:30"]  # UTC/Asia-HK/London/NY-pre/US-open


def load_csv(path: str) -> pd.DataFrame:
    df = pd.read_csv(path, index_col=0, parse_dates=True)
    df.index = pd.to_datetime(df.index, utc=True, errors="coerce")
    df = df.dropna(subset=["open", "high", "low", "close"]).sort_index()
    df = df[~df.index.duplicated(keep="last")]
    return df[["open", "high", "low", "close", "volume"]]


def load_tf(asset: str, tf: str) -> pd.DataFrame | None:
    """Load bars for asset/tf. Direct CSV if present, else resample from 15m base."""
    path = CSV.get(asset, {}).get(tf)
    if path:
        return load_csv(path)
    base = CSV.get(asset, {}).get(RESAMPLE_FROM)
    if not base or tf not in BARS_PER_DAY or tf == "5m":
        return None
    df = load_csv(base)
    df = df.resample(tf).agg({"open": "first", "high": "max", "low": "min",
                              "close": "last", "volume": "sum"}).dropna()
    return df[["open", "high", "low", "close", "volume"]]


def cfg_trend(atr_mult: float, gated: bool) -> BacktestConfig:
    kw = dict(use_trailing=True, trailing_mult=atr_mult, leverage=LEVERAGE,
              break_even_at=0.0, maker_on_limit=True, allow_short=False,
              maker_fee=MAKER, taker_fee=TAKER, slippage_bps=SLIP)
    if not gated:
        kw.update(max_drawdown=0.0, max_positions=99, max_daily_loss=0.0)
    return BacktestConfig(**kw)


def cfg_orb(gated: bool) -> BacktestConfig:
    kw = dict(use_trailing=False, risk_pct_stop=0.02, leverage=LEVERAGE,
              break_even_at=0.0, maker_on_limit=True, allow_short=True,
              maker_fee=MAKER, taker_fee=TAKER, slippage_bps=SLIP)
    if not gated:
        kw.update(max_drawdown=0.0, max_positions=99, max_daily_loss=0.0)
    return BacktestConfig(**kw)


def grid_combos(grid: dict[str, list]) -> list[dict]:
    keys = list(grid)
    base = [{}]
    for k in keys:
        base = [dict(b, **{k: v}) for b in base for v in grid[k]]
    return base


INT_KEYS = {"range_bars"}


def cast_params(params: dict) -> dict:
    return {k: (int(v) if k in INT_KEYS and v is not None else v) for k, v in params.items()}


def backtest(strat, cfg, df):
    return Backtester(strat, cfg).run(df)


def score_grid(name, key, grid, cfg_fn, df, label=""):
    """Grid-tune on train (70% net), score OOS (30%) + full + MC. Returns rows sorted by OOS net."""
    split = int(len(df) * 0.7)
    train, test = df.iloc[:split], df.iloc[split:]
    rows = []
    for params in grid_combos(grid):
        bp = cast_params(params)
        try:
            strat = get_strategy(key, bp)
            cfg = cfg_fn(bp)
            full = backtest(strat, cfg, df)          # run ONCE: metrics + trades
            m_full, trades = full["metrics"], full["trades"]
            m_test = backtest(get_strategy(key, bp), cfg, test)["metrics"]
            mc = monte_carlo(trades, INIT_CAP, n=200)
        except Exception as e:  # noqa: BLE001
            rows.append({"name": name, "params": bp, "error": str(e)[:100]})
            continue
        rows.append({
            "name": name, "params": bp,
            "trades": m_full.get("num_trades", 0),
            "net_full": round(float(m_full.get("net_profit", 0)), 1),
            "sharpe_full": round(float(m_full.get("sharpe", 0)), 2),
            "pf_full": round(float(m_full.get("profit_factor", 0)), 2),
            "maxdd": round(float(m_full.get("max_drawdown", 0)), 3),
            "oos_net": round(float(m_test.get("net_profit", 0)), 1),
            "oos_sharpe": round(float(m_test.get("sharpe", 0)), 2),
            "oos_trades": m_test.get("num_trades", 0),
            "mc_prob": round(float(mc.get("mc_prob_profit", 0)), 2),
        })
    rows.sort(key=lambda r: r.get("oos_net", -9e9), reverse=True)
    return rows


def has_edge(r):
    return (r and "error" not in r and r["oos_net"] > 0 and r["oos_sharpe"] > 0
            and r["oos_trades"] >= 10 and r["mc_prob"] > 0.5)


def fmt(r):
    if "error" in r:
        return f"  ERR {r['error']}"
    p = r["params"]
    ps = ",".join(f"{k}={v}" for k, v in p.items())
    return (f"  {ps:46} tr={r['trades']:4} net={r['net_full']:9} sh={r['sharpe_full']:6} "
            f"pf={r['pf_full']:5} dd={r['maxdd']:6} | OOS net={r['oos_net']:9} "
            f"sh={r['oos_sharpe']:6} tr={r['oos_trades']:3} mcP={r['mc_prob']}")


def run_asset(asset: str, tf: str, gated: bool, years: float) -> dict:
    df = load_tf(asset, tf)
    if df is None or len(df) < 200:
        print(f"\n##### {asset} {tf}: NO DATA #####")
        return {}
    if years:
        df = df.iloc[-int(years * 365 * BARS_PER_DAY.get(tf, 96)):]
    print(f"\n##### {asset} {tf} {'gated' if gated else 'ungated'} | {len(df)} bars "
          f"{df.index[0].date()} -> {df.index[-1].date()} #####")

    # stub baseline
    stub_grid = {"range_bars": [3, 5], "atr_mult": [3.0, 4.0]}
    stub = score_grid("stub", "opening_range_breakout", stub_grid,
                      lambda bp: cfg_trend(float(bp.get("atr_mult", 3.0)), gated), df)
    print("stub (long-only ATR trail):")
    for r in stub:
        print(fmt(r))

    # Phase A: best session + range_bars (retest, rr=2)
    if tf == "5m":
        range_grid = [1, 2, 3]
    elif tf == "1h":
        range_grid = [1, 2, 3, 4]
    elif tf == "4h":
        range_grid = [1, 2]  # 6 bars/day -> opening range can't exceed ~half the day
    else:
        range_grid = [2, 3, 5]
    phaseA = score_grid("orb_max", "orb_max",
                       {"range_bars": range_grid, "session_open": SESSIONS, "reversal": [False], "rr": [2.0]},
                       lambda bp: cfg_orb(gated), df)
    print("Phase A (retest, rr=2) best per session:")
    seen = set()
    for r in phaseA:
        s = r["params"].get("session_open")
        if s not in seen and "error" not in r:
            seen.add(s)
            print(fmt(r))
    bestA = phaseA[0] if phaseA and "error" not in phaseA[0] else None
    best_sess = bestA["params"]["session_open"] if bestA else "07:00"
    best_rb = bestA["params"]["range_bars"] if bestA else 3
    print(f"  -> best session={best_sess} range_bars={best_rb}")

    # Phase B: on best session, sweep reversal x rr
    phaseB = score_grid("orb_max", "orb_max",
                       {"range_bars": [best_rb], "session_open": [best_sess],
                        "reversal": [False, True], "rr": [1.5, 2.0, 3.0]},
                       lambda bp: cfg_orb(gated), df)
    print(f"Phase B (session={best_sess}, rb={best_rb}, sweep reversal x rr):")
    for r in phaseB:
        print(fmt(r))

    bestB = phaseB[0] if phaseB and "error" not in phaseB[0] else None
    print(f"VERDICT {asset} {tf}: stub_edge={has_edge(stub[0] if stub else None)} "
          f"orb_edge={has_edge(bestB)} best_orb_oos_net={bestB['oos_net'] if bestB else '-'}")
    return {"asset": asset, "tf": tf, "stub": stub, "phaseA": phaseA, "phaseB": phaseB,
            "best_session": best_sess, "best_range": best_rb}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--asset", default="all", help="BTC|ETH|SOL|all")
    ap.add_argument("--tf", default="15m", help="15m|5m|1h|4h")
    ap.add_argument("--gated", action="store_true", help="enable deploy risk gates")
    ap.add_argument("--years", type=float, default=2.0)
    ap.add_argument("--sessions", default=None, help="comma list of sessions to keep (default all)")
    args = ap.parse_args()
    if args.sessions:
        keep = set(args.sessions.split(","))
        SESSIONS[:] = [s for s in SESSIONS if s in keep]
    # 5m has 4x bars -> trim harder to keep runtime sane
    if args.tf == "5m":
        args.years = min(args.years, 1.0)

    assets = ["BTC", "ETH", "SOL"] if args.asset == "all" else [args.asset]
    # skip assets lacking the requested tf (direct CSV or resample-able from 15m)
    assets = [a for a in assets if load_tf(a, args.tf) is not None]
    all_res = {}
    for a in assets:
        all_res[a] = run_asset(a, args.tf, args.gated, args.years)

    print("\n===== SUMMARY =====")
    for a, res in all_res.items():
        if not res:
            continue
        bB = res["phaseB"][0] if res["phaseB"] and "error" not in res["phaseB"][0] else None
        st = res["stub"][0] if res["stub"] and "error" not in res["stub"][0] else None
        print(f"{a} {args.tf}: best session={res['best_session']} rb={res['best_range']} | "
              f"stub OOS net={st['oos_net'] if st else '-'} edge={has_edge(st)} | "
              f"orb best OOS net={bB['oos_net'] if bB else '-'} sh={bB['oos_sharpe'] if bB else '-'} "
              f"tr={bB['oos_trades'] if bB else '-'} mcP={bB['mc_prob'] if bB else '-'} "
              f"edge={has_edge(bB)}")

    import json
    tag = f"{args.tf}_{'gated' if args.gated else 'ungated'}"
    with open(f"reports/orb_backtest_{tag}.json", "w") as f:
        json.dump(all_res, f, indent=2, default=str)
    print(f"\nresults -> reports/orb_backtest_{tag}.json")


if __name__ == "__main__":
    main()